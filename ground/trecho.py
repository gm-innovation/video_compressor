#!/usr/bin/env python3
"""Trecho de 1 minuto do video QUE CHEGA no lado terra — a prova de que a compressao informada existe.

Por que este modulo existe: o dono quer, no app do cliente, um botao que baixe 1 minuto do video como
ele chega na VPS/terra, para conferir POR FORA (tamanho em disco, ffprobe) se o Mbps e a porcentagem de
compressao que o Admin/Captura informam sao reais. Sem isso a reducao de banda e' palavra.

Duas decisoes que fazem a prova valer:

1. o trecho e' lido do mediamtx do lado terra com `-c copy`: o arquivo baixado sao os BITS QUE CHEGARAM.
   Reencodar aqui destruiria a prova (o proprio download recomprimiria o video);
2. o numero do atestado e' CALCULADO aqui (bytes x 8 / segundos reais do arquivo) e posto ao lado do
   numero DECLARADO pelo PC de captura, com o veredito `bate: sim|nao`. Repetir a porcentagem do bordo
   nao provaria nada.

O trecho e' sob demanda (nao ha gravacao continua): 1 clique = 1 leitor do caminho no mediamtx, sem
tocar no PC de captura e sem derrubar o envio.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))
from ferramentas import caminho_ffmpeg, caminho_ffprobe  # noqa: E402
from producao import agora, conexao_banco  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
SEGUNDOS_PADRAO, SEGUNDOS_MIN, SEGUNDOS_MAX = 60, 10, 60
TTL_S = 3600.0                      # o arquivo nao fica na VPS: 1 h e' suficiente para o cliente baixar
TOLERANCIA_KBPS = 0.15              # +-15%: o minuto baixado nao e' o mesmo instante medido no bordo
TETO_POR_JANELA, JANELA_S = 3, 600  # 3 trechos por cliente a cada 10 min
TETO_SIMULTANEO = 2                 # gravacoes ao mesmo tempo no lado terra
PORTA_RTSP_PADRAO = 8554
PORTA_API_MEDIAMTX_PADRAO = 9997


def _porta_api_mediamtx() -> int:
    """Porta da API do mediamtx (env para bancada/teste: aqui o mediamtx roda em outra porta)."""
    try:
        return int(os.environ.get("LECSOR_PORTA_MEDIAMTX_API") or PORTA_API_MEDIAMTX_PADRAO)
    except ValueError:
        return PORTA_API_MEDIAMTX_PADRAO

_travas: set[str] = set()
_trava_lock = threading.Lock()
_parcial: dict[str, tuple[Path, float]] = {}   # gravacao em andamento: arquivo -> quando comecou


def diretorio() -> Path:
    """Onde os trechos ficam (env `LECSOR_TRECHOS_DIR` para tirar do repositorio em producao)."""
    d = Path(os.environ.get("LECSOR_TRECHOS_DIR") or (RAIZ / "ground" / "trechos"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitizar_fluxo(fluxo_id: str) -> str:
    """O fluxo vem da URL: vira so' [a-zA-Z0-9_-] antes de virar pedaco de comando ou de nome de arquivo."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "-", str(fluxo_id or "").strip())[:60]


def limitar_segundos(segundos) -> int:
    try:
        n = int(float(segundos))
    except (TypeError, ValueError):
        n = SEGUNDOS_PADRAO
    return max(SEGUNDOS_MIN, min(SEGUNDOS_MAX, n))


def garantir_tabela() -> None:
    """Historico dos trechos: quem baixou o que, quando e com que tamanho (auditoria simples)."""
    with conexao_banco() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS trechos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fluxo_id TEXT NOT NULL, arquivo TEXT NOT NULL, host TEXT,
                        segundos_pedidos INTEGER, duracao_s REAL, bytes INTEGER, kbps REAL,
                        sha256 TEXT, quem TEXT, criado_em TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_trecho_fluxo ON trechos (fluxo_id, id)")


# --------------------------------------------------------------------------- mediamtx (so' leitura)
def _paths(host: str, timeout: float = 1.5) -> dict:
    try:
        with urllib.request.urlopen(f"http://{host}:{_porta_api_mediamtx()}/v3/paths/list", timeout=timeout) as r:
            return {p["name"]: p for p in json.loads(r.read().decode()).get("items", [])}
    except Exception:
        return {}


def _hosts() -> list[str]:
    """Esta maquina + cada host que aparece nos envios recentes (mesma regra da lista de cameras)."""
    hosts = ["127.0.0.1"]
    try:
        with conexao_banco() as c:
            for r in c.execute("""SELECT DISTINCT srt_host FROM ingestoes
                                  WHERE srt_host IS NOT NULL AND srt_host <> ''
                                  ORDER BY id DESC LIMIT 10"""):
                h = (r["srt_host"] or "").strip()
                if h and h not in hosts:
                    hosts.append(h)
    except Exception:
        pass
    return hosts


def host_com_fluxo(fluxo: str) -> str | None:
    """De onde puxar o trecho: o primeiro mediamtx que tem este caminho no ar. None = ninguem tem."""
    for h in _hosts():
        p = _paths(h).get(fluxo)
        if p and p.get("ready"):
            return h
    return None


# --------------------------------------------------------------------------- contas do atestado
def _ffprobe(caminho: Path) -> dict:
    r = subprocess.run([caminho_ffprobe(), "-v", "error", "-show_entries",
                        "stream=codec_name,profile,width,height,avg_frame_rate:format=duration,bit_rate,size",
                        "-of", "json", str(caminho)], capture_output=True, text=True, timeout=60, errors="replace")
    try:
        j = json.loads(r.stdout or "{}")
        st = (j.get("streams") or [{}])[0]
        fm = j.get("format") or {}
        fps = st.get("avg_frame_rate") or "0/1"
        try:
            num, den = fps.split("/")
            fps_num = round(float(num) / float(den), 2) if float(den) else None
        except Exception:
            fps_num = None
        return {"codec": st.get("codec_name"), "perfil": st.get("profile"),
                "resolucao": f"{st.get('width')}x{st.get('height')}" if st.get("width") else None,
                "fps": fps_num, "duracao_s": round(float(fm.get("duration") or 0), 3),
                "bit_rate_bps": int(fm.get("bit_rate") or 0) or None, "bytes": int(fm.get("size") or 0) or None}
    except Exception as e:
        return {"erro": f"ffprobe falhou: {type(e).__name__}: {e}"}


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


# --------------------------------------------------------------------------- gravacao
def pode_gravar(quem: str | None = None) -> tuple[bool, str]:
    """Teto de uso: sem isso o botao vira gravador e o lado terra paga o consumo de banda."""
    with _trava_lock:
        if len(_travas) >= TETO_SIMULTANEO:
            return False, f"o lado terra ja esta gravando {len(_travas)} trechos ao mesmo tempo (maximo {TETO_SIMULTANEO})"
    if quem:
        garantir_tabela()
        desde = time.time() - JANELA_S
        with conexao_banco() as c:
            quantos = c.execute("SELECT COUNT(*) FROM trechos WHERE quem=? AND criado_em >= ?",
                                (quem, agora_como_tempo(desde))).fetchone()[0]
        if quantos >= TETO_POR_JANELA:
            return False, (f"limite de {TETO_POR_JANELA} trechos por {JANELA_S // 60} min atingido "
                           f"para este usuario — tente mais tarde")
    return True, ""


def agora_como_tempo(quando: float) -> str:
    """Converte epoch para o MESMO formato que `agora()` grava (ISO com fuso), para comparar no banco."""
    import datetime as dt
    return dt.datetime.fromtimestamp(quando).astimezone().isoformat(timespec="seconds")


def gravar(fluxo_id: str, segundos: int = SEGUNDOS_PADRAO, quem: str | None = None,
           host: str | None = None) -> dict:
    """Grava N segundos do fluxo COMO CHEGAM (sem reencodar) e devolve o caminho + os numeros medidos."""
    garantir_tabela()
    fluxo = sanitizar_fluxo(fluxo_id)
    if not fluxo:
        return {"erro": "fluxo invalido", "codigo": 422}
    segundos = limitar_segundos(segundos)
    livre, motivo = pode_gravar(quem)
    if not livre:
        return {"erro": motivo, "codigo": 429}
    with _trava_lock:
        if fluxo in _travas:
            return {"erro": f"ja existe uma gravacao de \"{fluxo}\" em andamento — espere ela terminar",
                    "codigo": 409, "ocupado": True}
        _travas.add(fluxo)
    try:
        h = host or host_com_fluxo(fluxo)
        if not h:
            return {"erro": f"o fluxo \"{fluxo}\" nao esta no ar no lado terra: sem video chegando, nao ha trecho",
                    "codigo": 404}
        pasta = diretorio()
        limpar_antigos()
        nome = f"{fluxo}-{time.strftime('%Y%m%d-%H%M')}-{segundos}s.mp4"
        saida = pasta / nome
        porta = int(os.environ.get("LECSOR_PORTA_RTSP") or PORTA_RTSP_PADRAO)
        cmd = [caminho_ffmpeg(), "-hide_banner", "-loglevel", "warning", "-nostdin", "-y",
               "-rtsp_transport", "tcp", "-i", f"rtsp://{h}:{porta}/{fluxo}",
               "-t", str(segundos),
               # -c copy: o arquivo sao os bits que chegaram. -faststart deixa o mp4 tocavel/baixavel
               "-c", "copy", "-movflags", "+faststart", str(saida)]
        with _trava_lock:
            _parcial[fluxo] = (saida, time.time())
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=segundos + 90, errors="replace")
        if r.returncode != 0 or not saida.exists() or saida.stat().st_size == 0:
            ultima = ((r.stderr or "").strip().splitlines() or ["sem detalhe"])[-1][:240]
            try:
                saida.unlink(missing_ok=True)
            except Exception:
                pass
            return {"erro": f"nao consegui gravar o trecho: {ultima}", "codigo": 502}
        info = _ffprobe(saida)
        bytes_ = saida.stat().st_size
        duracao = float(info.get("duracao_s") or 0) or float(segundos)
        kbps = round(bytes_ * 8 / duracao / 1000.0, 1)
        digest = _sha256(saida)
        when = agora()
        with conexao_banco() as c:
            cur = c.execute("""INSERT INTO trechos (fluxo_id, arquivo, host, segundos_pedidos, duracao_s,
                                bytes, kbps, sha256, quem, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (fluxo, nome, h, segundos, round(duracao, 3), bytes_, kbps, digest,
                             (quem or "")[:200], when))
            ident = cur.lastrowid
        return {"id": ident, "fluxo_id": fluxo, "arquivo": str(saida), "nome": nome, "host": h,
                "segundos_pedidos": segundos, "duracao_s": round(duracao, 3), "bytes": bytes_,
                "mb": round(bytes_ / 1e6, 2), "kbps_medidos": kbps, "sha256": digest,
                "stream": info, "criado_em": when}
    finally:
        with _trava_lock:
            _travas.discard(fluxo)
            _parcial.pop(fluxo, None)


def estado(fluxo_id: str) -> dict:
    """Quanto ja' entrou da gravacao em andamento — a tela mostra os bytes subindo em tempo real.

    E' isto que deixa o dono comparar, no mesmo minuto, o que a tela do Admin diz e o que o arquivo
    que ele vai baixar esta' realmente recebendo.
    """
    fluxo = sanitizar_fluxo(fluxo_id)
    with _trava_lock:
        item = _parcial.get(fluxo)
    if not item:
        return {"fluxo_id": fluxo, "gravando": False}
    arquivo, inicio = item
    try:
        bytes_ = arquivo.stat().st_size
    except OSError:
        bytes_ = 0
    return {"fluxo_id": fluxo, "gravando": True, "arquivo": arquivo.name, "bytes": bytes_,
            "mb": round(bytes_ / 1e6, 2), "segundos": round(time.time() - inicio, 1),
            "kbps_agora": round(bytes_ * 8 / max(0.5, time.time() - inicio) / 1000.0, 1)}


def limpar_antigos(ttl_s: float = TTL_S) -> int:
    """Apaga trecho vencido: o lado terra nao pode virar deposito de video."""
    n = 0
    limite = time.time() - ttl_s
    try:
        for f in diretorio().glob("*.mp4"):
            if f.stat().st_mtime < limite:
                f.unlink(missing_ok=True)
                n += 1
    except Exception:
        pass
    return n


def listar(fluxo_id: str | None = None, limite: int = 20) -> list[dict]:
    garantir_tabela()
    sql = "SELECT * FROM trechos" + (" WHERE fluxo_id=?" if fluxo_id else "") + " ORDER BY id DESC LIMIT ?"
    args = ((sanitizar_fluxo(fluxo_id), limite) if fluxo_id else (limite,))
    with conexao_banco() as c:
        linhas = [dict(r) for r in c.execute(sql, args)]
    for l in linhas:
        l["existe"] = (diretorio() / l["arquivo"]).exists()
    return linhas


# --------------------------------------------------------------------------- atestado (a prova)
def _kbps_de_mb(mb, segundos) -> float | None:
    """kbps de um arquivo de `mb` megabytes em `segundos` — a MESMA conta que se faz no arquivo baixado."""
    try:
        mb, segundos = float(mb or 0), float(segundos or 0)
    except (TypeError, ValueError):
        return None
    if mb <= 0 or segundos <= 0:
        return None
    return round(mb * 8_000_000 / segundos / 1000.0, 1)


def atestado(trecho_id: int) -> dict:
    """Poe o que o ARQUIVO prova ao lado do que o PC de captura DECLAROU, com veredito.

    De onde vem o "declarado" (e o atestado diz qual foi a origem, sem disfarcar):
    - `medicoes_qualidade` — a medicao que o bordo faz com a fonte crua e ANUNCIA ao lado terra
      (`POST /api/qualidade/anuncio`). E' dela que sai o kbps do comprimido (`mb_alvo` / segundos), o
      kbps do original (`mb_original` / segundos) e a PORCENTAGEM DE COMPRESSAO informada pelo bordo;
    - `ingestoes` — quando o proprio envio foi registrado nesta maquina (bancada / lado do bordo).
    O que o arquivo prova e' independente: bytes x 8 / segundos reais do MP4 baixado.
    """
    garantir_tabela()
    with conexao_banco() as c:
        t = c.execute("SELECT * FROM trechos WHERE id=?", (trecho_id,)).fetchone()
        if not t:
            return {"erro": f"trecho {trecho_id} nao existe", "codigo": 404}
        t = dict(t)
        # as duas tabelas podem nao existir no lado terra (elas nascem no bordo): sem esse cuidado o
        # atestado derrubava a conexao com "no such table: medicoes_qualidade" em vez de responder
        env = {}
        q = {}
        try:
            linha = c.execute("""SELECT fluxo_id, rotulo, fonte, tipo, codec, bitrate_alvo, resolucao, fps,
                                        bitrate_entrada_kbps, bitrate_saida_kbps, corte_pct, estado, atualizado_em
                                 FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1""",
                              (t["fluxo_id"],)).fetchone()
            env = dict(linha) if linha else {}
        except sqlite3.Error:
            pass
        try:
            linha = c.execute("""SELECT ssim, ajuste, resolucao, fps, segundos, mb_alvo, mb_original,
                                        compressao_pct, fonte, medido_em FROM medicoes_qualidade
                                 WHERE fluxo_id=? ORDER BY id DESC LIMIT 1""", (t["fluxo_id"],)).fetchone()
            q = dict(linha) if linha else {}
        except sqlite3.Error:
            pass

    caminho = diretorio() / t["arquivo"]
    stream = _ffprobe(caminho) if caminho.exists() else {}
    duracao = float(t["duracao_s"] or 0) or float(t["segundos_pedidos"] or SEGUNDOS_PADRAO)
    medidos_kbps = round(t["bytes"] * 8 / duracao / 1000.0, 1)

    # kbps do comprimido e do original que o bordo informou (a medicao que ele anunciou ao lado terra)
    saida_kbps = env.get("bitrate_saida_kbps") or _kbps_de_mb(q.get("mb_alvo"), q.get("segundos"))
    entrada_kbps = env.get("bitrate_entrada_kbps") or _kbps_de_mb(q.get("mb_original"), q.get("segundos"))
    origem = ("envio registrado nesta maquina" if env.get("bitrate_saida_kbps")
              else ("medicao de qualidade anunciada pelo bordo" if saida_kbps else "nada declarado"))
    compr_declarada = q.get("compressao_pct")
    bytes_original = (entrada_kbps * 1000.0 / 8.0 * duracao) if entrada_kbps else None
    compr_calculada = (round((1 - t["bytes"] / bytes_original) * 100, 2) if bytes_original else None)

    def dentro(a, b) -> bool | None:
        if a is None or b is None or not float(b):
            return None
        return abs(float(a) - float(b)) / float(b) <= TOLERANCIA_KBPS

    bate = dentro(medidos_kbps, saida_kbps)
    bate_compr = (abs(float(compr_declarada) - float(compr_calculada)) <= 15.0
                  if (compr_declarada is not None and compr_calculada is not None) else None)
    return {
        "trecho": {"id": t["id"], "fluxo_id": t["fluxo_id"], "arquivo": t["arquivo"],
                   "segundos_pedidos": t["segundos_pedidos"], "criado_em": t["criado_em"],
                   "quem": t["quem"], "host_lado_terra": t["host"]},
        "medido_no_arquivo": {"bytes": t["bytes"], "mb": round(t["bytes"] / 1e6, 2),
                              "duracao_s": round(duracao, 3), "kbps": medidos_kbps,
                              "sha256": t["sha256"], "stream": stream},
        "declarado_pelo_pc_de_captura": {
            "kbps_saida": saida_kbps, "kbps_entrada": entrada_kbps,
            "alvo": env.get("bitrate_alvo") or q.get("ajuste"),
            "codec": env.get("codec"), "resolucao": env.get("resolucao") or q.get("resolucao"),
            "fps": env.get("fps") or q.get("fps"),
            "compressao_pct": compr_declarada, "ssim": q.get("ssim"),
            "corte_pct": env.get("corte_pct"), "estado": env.get("estado"),
            "medido_em": q.get("medido_em"), "atualizado_em": env.get("atualizado_em"),
            "fonte": env.get("fonte") or q.get("fonte"), "origem": origem},
        "contas": {"tolerancia_pct": int(TOLERANCIA_KBPS * 100),
                   "bate": bate, "diferenca_pct": (round((medidos_kbps - saida_kbps) / float(saida_kbps) * 100, 2)
                                                   if saida_kbps else None),
                   "compressao_pct_declarada": compr_declarada,
                   "compressao_pct_calculada": compr_calculada,
                   "bate_compressao": bate_compr,
                   "original_estimado_mb": (round(bytes_original / 1e6, 2) if bytes_original else None),
                   "base_do_original": ("bitrate de entrada informado pelo PC de captura" if bytes_original
                                        else "sem o original informado pelo PC de captura: a compressao nao fecha a conta")},
        "leitura": _leitura(medidos_kbps, saida_kbps, bate, compr_declarada, compr_calculada, bate_compr, origem),
    }


def _leitura(medidos, declarados, bate, compr_declarada, compr_calculada, bate_compr, origem) -> str:
    """Frase curta e verificavel do que o arquivo prova — a resposta que o dono quer poder contestar."""
    if not declarados:
        return (f"o arquivo prova {medidos} kbps num trecho; o PC de captura nao informou o kbps deste fluxo "
                f"({origem}) — nao ha com o que comparar")
    frase = (f"o arquivo prova {medidos} kbps; o PC de captura declarou {declarados} kbps ({origem}) — "
             + ("dentro da tolerancia de" if bate else "FORA da tolerancia de")
             + f" {int(TOLERANCIA_KBPS * 100)}%")
    if compr_declarada is not None and compr_calculada is not None:
        frase += (f"; compressao informada {compr_declarada}% x recalculada aqui {compr_calculada}% — "
                  + ("confere" if bate_compr else "NAO confere"))
    elif compr_calculada is None:
        frase += "; compressao: sem o original informado, a conta nao fecha"
    return frase
