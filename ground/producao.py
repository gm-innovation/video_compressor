#!/usr/bin/env python3
"""Producao: o que o dono quer ver em tempo real e em 30 dias (cards, nao envio por envio).

Separa duas coisas que estavam misturadas:

- **tempo real** (`tempo_real()`): estado agora por fluxo (enviando/parado), taxa, compressao do
  momento, banda consumida e economizada, e o que o SRT diz do LINK (RTT, taxa do link, perdas,
  atraso do buffer SRT) mais a latencia de internet medida por ping.
- **historico** (`fechar_minutos()` + `resumo_producao()`): fecha minuto a minuto o que foi medido
  (media de compressao, MB, segundos no ar) para permitir media de 30 dias, horas de streaming e
  disponibilidade (%) com filtro de periodo/embarcacao/camera.

A fonte dos numeros e sempre uma medicao nossa: a taxa vem do `-progress` do ffmpeg de envio
(gravada 1x/s em `ingestoes`), as amostras de 1 s ficam em `ingestoes_amostras`, e o link vem da
API de estatisticas do mediamtx (`msRTT`, `mbpsLinkCapacity`, `msSendTsbPdDelay`, ...).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from etapas import RAIZ, _agora as agora, conexao_banco, envio  # reaproveita a base da bancada

MEDIAMTX_API = os.environ.get("LECSOR_MEDIAMTX_API", "http://127.0.0.1:9997")
PING_ALVO = os.environ.get("LECSOR_PING_ALVO", "8.8.8.8")
RETENCAO_DIAS = int(os.environ.get("LECSOR_RETENCAO_DIAS", "30"))
FUSO = timezone(timedelta(hours=-3))


# --------------------------------------------------------------------------- tabelas e historico
def garantir_tabelas() -> None:
    with conexao_banco() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS telemetria_minuto (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fluxo_id TEXT NOT NULL, camera_id TEXT, embarcacao_id TEXT,
                        minuto TEXT NOT NULL,
                        entrada_kbps REAL, saida_kbps REAL, compressao_pct REAL,
                        mb_enviados REAL, segundos_no_ar REAL, amostras INTEGER,
                        criado_em TEXT NOT NULL,
                        UNIQUE(fluxo_id, minuto))""")
        c.execute("""CREATE TABLE IF NOT EXISTS latencia_medicoes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fluxo_id TEXT, ms REAL NOT NULL, caminho TEXT, em TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_minuto ON telemetria_minuto(minuto)")


def _fluxo_do_banco(fluxo_id: str) -> dict:
    with conexao_banco() as c:
        r = c.execute("SELECT * FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1", (fluxo_id,)).fetchone()
        d = dict(r) if r else {}
        cam = None
        if d.get("camera_id"):
            cam = c.execute("SELECT * FROM cameras WHERE id=?", (d["camera_id"],)).fetchone()
            cam = dict(cam) if cam else None
        if not cam and d.get("fluxo_id"):
            cam = c.execute("SELECT * FROM cameras WHERE fluxo_id=?", (d["fluxo_id"],)).fetchone()
            cam = dict(cam) if cam else None
    if not cam and d.get("fluxo_id"):
        # camera cadastrada com o fluxo ou, na falta, o nome do fluxo como rotulo
        cam = {"id": d.get("camera_id") or d["fluxo_id"], "rotulo": d.get("rotulo") or d["fluxo_id"],
               "embarcacao_id": "", "local": ""}
    return {"ingestao": d, "camera": cam or {}}


def fechar_minutos(*, limpar_amostras: bool = False) -> dict:
    """Fecha o que ainda nao virou historico: agrega `ingestoes_amostras` por minuto e por fluxo.

    Roda quantas vezes quiser: o UNIQUE(fluxo_id, minuto) faz o reprocessamento ser idempotente.
    Retorna quantos minutos fecharam e quantos foram apagados por retencao.
    """
    garantir_tabelas()
    fechados, apagados = 0, 0
    with conexao_banco() as c:
        linhas = [dict(x) for x in c.execute("""
            SELECT a.ingestao_id, i.fluxo_id, i.camera_id, i.bitrate_entrada_kbps, i.fonte,
                   substr(a.em, 1, 16) AS minuto,   -- mantem o horario LOCAL (strftime converteria para UTC)
                   AVG(a.taxa_saida_kbps) AS saida_medio, AVG(a.corte_pct) AS corte_medio,
                   COUNT(*) AS amostras
              FROM ingestoes_amostras a JOIN ingestoes i ON i.id = a.ingestao_id
             GROUP BY a.ingestao_id, minuto""")]
        originais = {x["fluxo_id"]: dict(x) for x in c.execute(
            "SELECT fluxo_id, bitrate_entrada_kbps FROM compressoes WHERE fluxo_id IS NOT NULL")}
        por_arquivo = {}
        for x in c.execute("SELECT arquivo_saida, bitrate_entrada_kbps FROM compressoes"):
            if x["arquivo_saida"]:
                por_arquivo[os.path.basename(str(x["arquivo_saida"]).replace("\\", "/"))] = x["bitrate_entrada_kbps"]
        for l in linhas:
            comp = originais.get(l["fluxo_id"]) or {}
            entrada = comp.get("bitrate_entrada_kbps")
            if not entrada and l.get("fonte"):
                entrada = por_arquivo.get(os.path.basename(str(l["fonte"]).replace("\\", "/")))
            entrada = entrada or l["bitrate_entrada_kbps"]
            saida = l["saida_medio"] or 0
            # a compressao do minuto e' recalculada com a entrada CERTA (do arquivo original):
            # o corte gravado na amostra usa a entrada da linha de ingestao, que no caso de um
            # arquivo ja comprimido publicado e' o proprio arquivo comprimido (daria negativo)
            corte = round((1 - saida / entrada) * 100, 2) if (entrada and saida) else l["corte_medio"]
            mb = round((saida or 0) * (l["amostras"] or 0) / 1000 / 8, 4)   # kbps * 1 s -> MB
            emb = ""
            cam = c.execute("SELECT embarcacao_id FROM cameras WHERE id=? OR fluxo_id=? LIMIT 1",
                            (l["camera_id"], l["fluxo_id"])).fetchone()
            if cam:
                emb = cam["embarcacao_id"] or ""
            if not emb:
                emb = c.execute("SELECT embarcacao_id FROM cameras WHERE embarcacao_id<>'' ORDER BY id LIMIT 1").fetchone()
                emb = (emb["embarcacao_id"] if emb else "")
            c.execute("""INSERT INTO telemetria_minuto
                         (fluxo_id,camera_id,embarcacao_id,minuto,entrada_kbps,saida_kbps,
                          compressao_pct,mb_enviados,segundos_no_ar,amostras,criado_em)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(fluxo_id,minuto) DO UPDATE SET
                           entrada_kbps=excluded.entrada_kbps, saida_kbps=excluded.saida_kbps,
                           compressao_pct=excluded.compressao_pct, mb_enviados=excluded.mb_enviados,
                           segundos_no_ar=excluded.segundos_no_ar, amostras=excluded.amostras""",
                      (l["fluxo_id"], l["camera_id"], emb, l["minuto"], entrada, round(saida, 1),
                       corte, mb, l["amostras"], l["amostras"], agora()))
            fechados += 1
        if RETENCAO_DIAS > 0:
            limite = (datetime.now(FUSO) - timedelta(days=RETENCAO_DIAS)).strftime("%Y-%m-%dT%H:%M")
            cur = c.execute("DELETE FROM telemetria_minuto WHERE minuto < ?", (limite,))
            apagados = cur.rowcount or 0
        if limpar_amostras:
            c.execute("DELETE FROM ingestoes_amostras WHERE em < ?",
                      ((datetime.now(FUSO) - timedelta(hours=2)).isoformat(timespec="seconds"),))
    return {"minutos_fechados": fechados, "minutos_apagados_por_retencao": apagados,
            "retencao_dias": RETENCAO_DIAS, "em": agora()}


# --------------------------------------------------------------------------- link e atraso
def _mediamtx(caminho: str) -> dict:
    try:
        return json.loads(urllib.request.urlopen(MEDIAMTX_API + caminho, timeout=6).read())
    except Exception:
        return {}


def link_srt(fluxo_id: str | None = None) -> dict:
    """O que o SRT sabe do LINK: RTT, taxa que cabe no link, perdas e o atraso do buffer.

    `msSendTsbPdDelay`/`msReceiveTsbPdDelay` e' o buffer de latencia do SRT em ms (o atraso que o
    transporte assume). `mbpsLinkCapacity` e' a capacidade estimada do link pelo proprio SRT —
    e' o numero que mais se aproxima de "qual a banda que a internet local aguenta".
    """
    dados = _mediamtx("/v3/srtconns/list").get("items", [])
    if fluxo_id:
        dados = [d for d in dados if str(d.get("path") or "").strip("/") == fluxo_id] or dados
    pubs = [d for d in dados if d.get("state") == "publish"]
    leituras = [d for d in dados if d.get("state") in ("read", "idle", "publish")]
    escolhida = (pubs or leituras or [None])[0]
    if not escolhida:
        return {"disponivel": False, "motivo": "nenhuma conexao SRT agora"}
    def _n(k, casas=2):
        v = escolhida.get(k)
        return round(float(v), casas) if isinstance(v, (int, float)) else None
    atraso = escolhida.get("msSendTsbPdDelay") or escolhida.get("msReceiveTsbPdDelay")
    return {
        "disponivel": True,
        "fluxo": str(escolhida.get("path") or "").strip("/") or None,
        "remoto": escolhida.get("remoteAddr"),
        "rtt_ms": _n("msRTT", 3),
        "taxa_envio_mbps": _n("mbpsSendRate", 3),
        "taxa_recebida_mbps": _n("mbpsReceiveRate", 3),
        "capacidade_link_mbps": _n("mbpsLinkCapacity", 3),
        "perda_envio_pct": _n("packetsSendLossRate", 3),
        "perda_recebida_pct": _n("packetsReceivedLossRate", 3),
        "retransmitidos": escolhida.get("packetsRetrans"),
        "atraso_buffer_ms": round(float(atraso), 1) if isinstance(atraso, (int, float)) else None,
        "fonte": "estatisticas do mediamtx (SRT)",
    }


_CACHE_PING: dict = {"em": 0.0, "dados": None}


def latencia_internet(alvo: str | None = None, *, validade_s: int = 15) -> dict:
    """Latencia da internet local, com cache curto (ping leva ~1,5 s; o painel atualiza a cada 2 s)."""
    """Latencia da internet local: ping no alvo (padrao 8.8.8.8).

    Sem resposta de ping (bloqueado), cai para o tempo de abertura de conexao TCP em 1.1.1.1:443,
    que mede ida e volta do handshake — numero diferente de ping, e dito no campo `fonte`.
    """
    alvo = alvo or PING_ALVO
    if (alvo == PING_ALVO and _CACHE_PING["dados"] is not None
            and time.time() - _CACHE_PING["em"] < validade_s):
        return _CACHE_PING["dados"]
    t0 = time.time()
    try:
        p = subprocess.run(["ping", "-n", "4", "-w", "1200", alvo], capture_output=True, timeout=20)
        txt = (p.stdout or b"").decode("cp850", "replace") + (p.stderr or b"").decode("cp850", "replace")
    except Exception as e:
        return {"alvo": alvo, "disponivel": False, "motivo": f"ping falhou: {type(e).__name__}"}
    def _num(padrao):
        m = re.search(padrao, txt)
        return float(m.group(1)) if m else None
    medio = _num(r"(?:M[eé]dia|Average)\s*=\s*([0-9]+)ms")
    minimo = _num(r"(?:M[ií]nimo|Minimum)\s*=\s*([0-9]+)ms")
    maximo = _num(r"(?:M[aá]ximo|Maximum)\s*=\s*([0-9]+)ms")
    perdidos = _num(r"Perdidos\s*=\s*[0-9]+\s*\(([0-9]+)%") or _num(r"\(([0-9]+)%")
    if medio is None:
        # ping bloqueado: mede o handshake TCP
        import socket
        tc0 = time.time()
        try:
            with socket.create_connection(("1.1.1.1", 443), timeout=5):
                ms = round((time.time() - tc0) * 1000, 1)
            d = {"alvo": "1.1.1.1:443", "disponivel": True, "ms_medio": ms, "ms_minimo": ms,
                 "ms_maximo": ms, "perda_pct": None, "levou_s": round(time.time() - t0, 2),
                 "fonte": "abertura de conexao TCP (o ping foi bloqueado)"}
            _CACHE_PING.update(em=time.time(), dados=d)
            return d
        except Exception as e:
            return {"alvo": alvo, "disponivel": False, "motivo": f"sem resposta ({type(e).__name__})",
                    "fonte": "ping e TCP"}
    d = {"alvo": alvo, "disponivel": True, "ms_medio": medio, "ms_minimo": minimo, "ms_maximo": maximo,
         "perda_pct": perdidos, "levou_s": round(time.time() - t0, 2), "fonte": "ping"}
    _CACHE_PING.update(em=time.time(), dados=d)
    return d


def atraso_stream(fluxo_id: str) -> dict:
    """Atraso do streaming: o buffer SRT agora + a ultima medicao ponta a ponta (relogio queimado).

    O buffer SRT e' continuo e sai do mediamtx. A medicao de ponta a ponta (quadro decodificado tela
    afora) e' rodada a mao por `etapas.latencia_ponta_a_ponta()` e fica guardada em `latencia_medicoes`.
    """
    link = link_srt(fluxo_id)
    with conexao_banco() as c:
        r = c.execute("SELECT ms, caminho, em FROM latencia_medicoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1",
                      (fluxo_id,)).fetchone()
    ponta = dict(r) if r else None
    return {"buffer_srt_ms": link.get("atraso_buffer_ms"),
            "ponta_a_ponta": {"ms": ponta["ms"], "caminho": ponta["caminho"], "em": ponta["em"]} if ponta else None,
            "rtt_ms": link.get("rtt_ms"), "fonte": "SRT (buffer) + medicao de ponta a ponta registrada"}


def registrar_latencia(fluxo_id: str, ms: float, caminho: str = "") -> None:
    garantir_tabelas()
    with conexao_banco() as c:
        c.execute("INSERT INTO latencia_medicoes (fluxo_id, ms, caminho, em) VALUES (?,?,?,?)",
                  (fluxo_id, float(ms), caminho, agora()))


# --------------------------------------------------------------------------- tempo real
def tempo_real() -> dict:
    """Estado agora, por fluxo, com o que o dono pediu: enviando/parado, compressao, banda do link."""
    garantir_tabelas()
    with conexao_banco() as c:
        vistas, linhas = set(), []
        for r in c.execute("SELECT * FROM ingestoes WHERE estado IN ('no_ar','no ar') ORDER BY id DESC LIMIT 60"):
            d = dict(r)
            if d["fluxo_id"] in vistas:
                continue
            vistas.add(d["fluxo_id"])
            linhas.append(d)
        originais = {x["fluxo_id"]: dict(x) for x in c.execute(
            "SELECT fluxo_id, bitrate_entrada_kbps, compressao_pct, ssim FROM compressoes WHERE fluxo_id IS NOT NULL")}
        cameras = {x["id"]: dict(x) for x in c.execute("SELECT * FROM cameras")}
        por_fluxo = {x["fluxo_id"]: dict(x) for x in c.execute("SELECT * FROM cameras")}
    relogio = datetime.now(FUSO)

    def _idade(iso):
        try:
            return (relogio - datetime.fromisoformat(iso)).total_seconds()
        except Exception:
            return None

    fluxos = []
    for d in linhas:
        comp = originais.get(d["fluxo_id"]) or {}
        entrada = (comp.get("bitrate_entrada_kbps") or d.get("bitrate_entrada_kbps") or 0) / 1000.0
        saida = (d.get("bitrate_saida_kbps") or 0) / 1000.0
        cam = cameras.get(d.get("camera_id")) or por_fluxo.get(d["fluxo_id"]) or {}
        idade = _idade(d.get("atualizado_em") or "")
        vivo = bool(idade is not None and idade < 6)
        fluxos.append({
            "fluxo_id": d["fluxo_id"], "rotulo": d.get("rotulo") or d["fluxo_id"],
            "camera_id": cam.get("id") or d.get("camera_id") or d["fluxo_id"],
            "camera_rotulo": cam.get("rotulo") or d.get("rotulo") or d["fluxo_id"],
            "embarcacao_id": cam.get("embarcacao_id") or d.get("embarcacao_id") or "",
            "tipo": d.get("tipo"),
            "estado": "enviando" if vivo else "parado",
            "erro": d.get("erro"),
            "idade_s": round(idade, 1) if idade is not None else None,
            "entrada_mbps": round(entrada, 3), "saida_mbps": round(saida, 3),
            "taxa_agora_mbps": round(saida, 3),
            "banda_economizada_mbps": round(max(0.0, entrada - saida), 3),
            "compressao_agora_pct": round((1 - saida / entrada) * 100, 2) if (entrada and saida) else None,
            "compressao_arquivo_pct": comp.get("compressao_pct"), "ssim": comp.get("ssim"),
            "mb_enviados": d.get("tamanho_mb"), "fps": d.get("fps"),
            "segundos_no_ar": d.get("duracao_s"),
        })
    link = link_srt()
    total = {"fluxos": 0, "enviando": 0, "entrada_mbps": 0.0, "saida_mbps": 0.0,
             "banda_economizada_mbps": 0.0, "mb_enviados": 0.0}
    for f in fluxos:
        if f["estado"] != "enviando":
            continue
        total["fluxos"] += 1
        total["enviando"] += 1
        total["entrada_mbps"] += f["entrada_mbps"]
        total["saida_mbps"] += f["saida_mbps"]
        total["banda_economizada_mbps"] += f["banda_economizada_mbps"]
        total["mb_enviados"] += f["mb_enviados"] or 0
    for k, v in list(total.items()):
        total[k] = round(v, 3) if isinstance(v, float) else v
    total["compressao_agora_pct"] = (round((1 - total["saida_mbps"] / total["entrada_mbps"]) * 100, 2)
                                     if total["entrada_mbps"] else None)
    return {"em": agora(), "fluxos": fluxos, "total": total, "link": link}


# --------------------------------------------------------------------------- 30 dias / cards
def resumo_producao(*, dias: int = 30, embarcacao_id: str | None = None, camera_id: str | None = None,
                    so_enviando: bool = False) -> dict:
    """Cards de producao: por embarcacao e por camera, com a janela pedida (padrao 30 dias).

    Regras que o dono cobrou:

    - **entrada e' a da FONTE ORIGINAL**: vem do proprio minuto fechado (`entrada_kbps`, que o rollup
      ja corrige pelo registro da compressao). Ler a ultima ingestao daria o arquivo JA comprimido e
      a economia apareceria como zero.
    - **disponibilidade e' proporcional ao periodo que o sistema realmente rodou**, nunca aos 30 dias
      cheios: se o historico comeca hoje, o denominador vai do primeiro minuto ate agora.
    - **fonte que esta enviando AGORA aparece mesmo sem historico fechado** (webcam ao vivo, por
      exemplo): senao o rotulo criado pelo dono nao apareceria em lugar nenhum e ele nao teria como
      saber se a camera esta no ar.
    - filtros: por embarcacao, por camera (id OU rotulo) e `so_enviando` (apenas quem esta enviando).
    """
    garantir_tabelas()
    agora_dt = datetime.now(FUSO)
    comeco_pedido = agora_dt - timedelta(days=max(1, int(dias)))
    with conexao_banco() as c:
        primeiro = c.execute("SELECT MIN(minuto) AS m FROM telemetria_minuto").fetchone()
        primeiro = primeiro["m"] if primeiro else None
        onde, par = ["minuto >= ?"], [comeco_pedido.strftime("%Y-%m-%dT%H:%M")]
        if embarcacao_id:
            onde.append("embarcacao_id = ?"); par.append(embarcacao_id)
        if camera_id:
            onde.append("(camera_id = ? OR fluxo_id = ?)"); par += [camera_id, camera_id]
        linhas = [dict(x) for x in c.execute(
            f"""SELECT embarcacao_id, camera_id, fluxo_id,
                       SUM(segundos_no_ar) AS segundos, SUM(mb_enviados) AS mb,
                       AVG(compressao_pct) AS compressao_medio, COUNT(*) AS minutos,
                       AVG(entrada_kbps) AS entrada_medio, MIN(minuto) AS de, MAX(minuto) AS ate
                  FROM telemetria_minuto WHERE {' AND '.join(onde)}
                 GROUP BY embarcacao_id, camera_id, fluxo_id""", par)]
        embarcacoes = {x["id"]: dict(x) for x in c.execute("SELECT * FROM embarcacoes")}
        cameras = {x["id"]: dict(x) for x in c.execute("SELECT * FROM cameras")}
        if not embarcacao_id:
            for l in linhas:
                if not l["embarcacao_id"]:
                    cam = cameras.get(l["camera_id"]) or {}
                    l["embarcacao_id"] = cam.get("embarcacao_id") or ""
    # janela efetiva: o pedido, cortado pelo inicio do historico
    comeco = comeco_pedido
    if primeiro:
        try:
            primeiro_dt = datetime.fromisoformat(primeiro) if len(primeiro) <= 16 else datetime.fromisoformat(primeiro)
            if primeiro_dt.tzinfo is None:
                primeiro_dt = primeiro_dt.replace(tzinfo=FUSO)
            if primeiro_dt > comeco:
                comeco = primeiro_dt
        except Exception:
            pass
    minutos_janela = max(1, int((agora_dt - comeco).total_seconds() // 60))
    vivo = tempo_real()
    ao_vivo = {f["fluxo_id"]: f for f in vivo["fluxos"]}
    cards, por_fluxo = [], {}
    for l in linhas:
        segundos = l["segundos"] or 0
        mb = l["mb"] or 0
        saida_mbps = round(mb * 8 / segundos, 3) if segundos else None
        entrada_mbps = round((l["entrada_medio"] or 0) / 1000, 3) if l["entrada_medio"] else None
        cam = cameras.get(l["camera_id"]) or {}
        emb_id = cam.get("embarcacao_id") or l["embarcacao_id"]
        emb = embarcacoes.get(emb_id) or {}
        card = {
            "embarcacao_id": emb_id, "embarcacao": emb.get("nome") or emb_id or "—",
            "camera_id": l["camera_id"], "camera": cam.get("rotulo") or l["camera_id"],
            "fluxo_id": l["fluxo_id"], "tipo": (ao_vivo.get(l["fluxo_id"]) or {}).get("tipo"),
            "compressao_medio_pct": (round(l["compressao_medio"], 2)
                                     if (l["compressao_medio"] is not None and l["compressao_medio"] >= 0) else None),
            "entrada_mbps": entrada_mbps,
            "banda_utilizada_mbps": saida_mbps,
            "banda_economizada_mbps": (round(max(0.0, entrada_mbps - saida_mbps), 3)
                                       if (entrada_mbps and saida_mbps) else None),
            "horas_streaming": round(segundos / 3600, 2),
            "mb_enviados": round(mb, 2),
            "minutos_no_ar": l["minutos"] or 0,
            "disponibilidade_pct": round(min(100.0, (l["minutos"] or 0) / minutos_janela * 100), 3),
            "de": l["de"], "ate": l["ate"],
            "estado": (ao_vivo.get(l["fluxo_id"]) or {}).get("estado", "parado"),
        }
        cards.append(card); por_fluxo[l["fluxo_id"]] = card
    # quem esta enviando AGORA e ainda nao tem minuto fechado (fonte viva recem-ligada)
    for f in vivo["fluxos"]:
        if f["fluxo_id"] in por_fluxo or f.get("estado") != "enviando":
            continue
        cam = cameras.get(f.get("camera_id") or "") or {}
        emb = embarcacoes.get(f.get("embarcacao_id") or cam.get("embarcacao_id") or "") or {}
        cards.append({
            "embarcacao_id": f.get("embarcacao_id") or cam.get("embarcacao_id") or "",
            "embarcacao": emb.get("nome") or f.get("embarcacao_id") or "—",
            "camera_id": f.get("camera_id") or f["fluxo_id"],
            "camera": f.get("camera_rotulo") or cam.get("rotulo") or f.get("rotulo") or f["fluxo_id"],
            "fluxo_id": f["fluxo_id"], "tipo": f.get("tipo"), "compressao_medio_pct": None,
            "entrada_mbps": None, "banda_utilizada_mbps": f.get("saida_mbps") or None,
            "banda_economizada_mbps": None,
            "horas_streaming": round((f.get("segundos_no_ar") or 0) / 3600, 2),
            "mb_enviados": round(f.get("mb_enviados") or 0, 2), "minutos_no_ar": 0,
            "disponibilidade_pct": None, "de": None, "ate": None, "estado": "enviando",
            "sem_historico": True,
        })
    if camera_id:
        alvo = camera_id.lower()
        cards = [c for c in cards if alvo in str(c["camera_id"]).lower() or alvo in str(c["camera"]).lower()]
    if embarcacao_id:
        cards = [c for c in cards if c["embarcacao_id"] == embarcacao_id]
    if so_enviando:
        cards = [c for c in cards if c["estado"] == "enviando"]
    cards.sort(key=lambda x: (x["embarcacao"], x["camera"]))
    tot = {
        "cards": len(cards),
        "horas_streaming": round(sum(c["horas_streaming"] for c in cards), 2),
        "mb_enviados": round(sum(c["mb_enviados"] for c in cards), 2),
        "banda_utilizada_mbps": round(sum(c["banda_utilizada_mbps"] or 0 for c in cards), 3),
        "banda_economizada_mbps": round(sum(c["banda_economizada_mbps"] or 0 for c in cards), 3),
        "enviando": sum(1 for c in cards if c["estado"] == "enviando"),
    }
    return {"dias": int(dias), "desde": comeco.strftime("%Y-%m-%dT%H:%M"), "so_enviando": bool(so_enviando),
            "camera": camera_id, "janela_efetiva_dias": round(minutos_janela / 1440, 3),
            "janela_efetiva_min": minutos_janela, "primeiro_minuto": primeiro,
            "agora": agora_dt.strftime("%Y-%m-%dT%H:%M"), "cards": cards, "total": tot,
            "embarcacoes": [{"id": k, "nome": v.get("nome")} for k, v in embarcacoes.items()],
            "cameras": sorted({(c["camera_id"], c["camera"]) for c in cards
                               if (c["camera"] or "").strip()}, key=lambda x: str(x[1])),
            "nota": ("disponibilidade = minutos no ar / minutos do periodo que o sistema ja rodou "
                     "(nao dos 30 dias cheios quando o historico e' mais curto)")}


