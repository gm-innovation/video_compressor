#!/usr/bin/env python3
"""STAND-BY do PC de captura: em repouso nenhum ffmpeg roda; o cliente ativa e a camera entra no ar.

Regra do produto (dono, 19/11/2026): "as cameras ficam filmando o tempo todo e conectadas ao DVR e ao
nosso sistema; o nosso sistema transmite apenas quando o cliente ativar no painel web". O sinal chega
DIVIDIDO (split) — nos lemos a entrada que chega na nossa maquina de captura.

    python tests/test-stand-by-do-captura.py

Provas (por PROCESSO, nao por texto na tela):
  1) em STAND-BY: `GET /api/cameras/prontidao` diz `pronta (stand-by)` e NAO existe nenhum ffmpeg deste
     fluxo nesta maquina (o dispositivo nao fica aberto em repouso);
  2) depois que o CLIENTE ativa (a mesma cadeia do agente: `/api/cameras/ligar` na maquina de captura),
     o fluxo fica `no ar` e existe ffmpeg DESTE fluxo rodando;
  3) depois de sair (`/api/cameras/desligar`), nenhum ffmpeg deste fluxo continua e a camera volta a
     `pronta (stand-by)`;
  4) camera cujo dispositivo NAO esta' na maquina aparece como `ausente` ANTES de o cliente tentar:
     "confira o cabo/USB do split" — e nao como um erro cru de ffmpeg depois do clique;
  5) a medida da prontidao NAO abre camera nenhuma (nenhum ffmpeg nasce ao perguntar).

Sem dispositivo de video nesta maquina a prova ao vivo e' declarada NAO MEDIDA (e o resto roda).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
FLUXO = "vivo-standby-1901"
FLUXO_AUSENTE = "vivo-ausente-1901"
MEDIAMTX = RAIZ / "tools" / "mediamtx" / ("mediamtx.exe" if os.name == "nt" else "mediamtx")
CONF_MEDIAMTX = RAIZ / "ground" / "mediamtx.yml"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def porta_livre(excluir: set[int] | None = None) -> int:
    excluir = excluir or set()
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        if p not in excluir:
            return p


def portas_tomadas() -> set[int]:
    tomadas = set()
    for p in (8890, 9997):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) == 0:
                tomadas.add(p)
    return tomadas


def pedir(metodo, url, corpo=None, cookie=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=40) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def comandos_dos_ffmpeg() -> list[str]:
    """Linha de comando de TODO ffmpeg vivo nesta maquina (prova independente do produto)."""
    if os.name == "nt":
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
                            "Select-Object -ExpandProperty CommandLine"],
                           capture_output=True, text=True, errors="replace")
        return [l for l in (r.stdout or "").splitlines() if l.strip()]
    r = subprocess.run(["bash", "-lc", "pgrep -af ffmpeg || true"], capture_output=True, text=True,
                       errors="replace")
    return [l for l in (r.stdout or "").splitlines() if l.strip()]


def ffmpeg_do_fluxo(fluxo: str) -> list[str]:
    return [l for l in comandos_dos_ffmpeg() if fluxo in l]


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError(f"a API saiu com codigo {proc.returncode}: "
                               + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-400:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc, f"http://127.0.0.1:{porta}"
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-400:])


def sessao_de(con, uid="admin-1", email="admin@lecsor.test", papel="admin"):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,'lecsor',?,?,200000,1)""", (uid, email, uid, papel, senha, salt))
    tok = "tok-" + uid
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    return tok


def espera_estado(base: str, tok: str, fluxo: str, querido: str, teto_s: float = 40.0) -> str:
    fim = time.time() + teto_s
    estado = "?"
    while time.time() < fim:
        _, j = pedir("GET", base + "/api/cameras/prontidao", cookie=tok)
        for c in (j.get("cameras") or []):
            if c.get("fluxo_id") == fluxo:
                estado = c.get("estado") or "?"
        if estado == querido:
            return estado
        time.sleep(1.0)
    return estado


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-standby-"))
    banco = tmp / "bordo.db"
    porta = porta_livre()
    faixas = [None]
    tomadas = portas_tomadas()
    if tomadas & {8890, 9997}:
        nota(f"mediamtx nao subiu por mim: as portas {sorted(tomadas)} ja' estao em uso nesta maquina")
    elif MEDIAMTX.exists() and CONF_MEDIAMTX.exists():
        log = (tmp / "mediamtx.log").open("wb")
        faixas[0] = subprocess.Popen([str(MEDIAMTX), str(CONF_MEDIAMTX)], cwd=str(RAIZ),
                                     stdout=log, stderr=subprocess.STDOUT)
        time.sleep(2.5)
        nota("mediamtx de teste no ar (SRT 127.0.0.1:8890)")
    else:
        nota("mediamtx nao encontrado: a prova ao vivo depende de um mediamtx ja' rodando nesta maquina")

    api = None
    forcas = []
    try:
        api, base = sobe_api(banco, porta, {"LECSOR_EMBARCACAO": "bancada",
                                            "LECSOR_PORTA_API": str(porta)})
        # dispositivo REAL desta maquina (a prontidao le' a mesma lista que o produto usa)
        _, disp = pedir("GET", base + "/api/dispositivos")
        video = (disp.get("dispositivos") or disp.get("video") or [])
        nomes = [d.get("video") if isinstance(d, dict) else d for d in video]
        dispositivo = nomes[0] if nomes else ""
        nota(f"dispositivos de video nesta maquina: {nomes or 'nenhum'}")

        con = sqlite3.connect(banco)
        con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        for cid, fluxo in (("cam-standby", FLUXO), ("cam-ausente", FLUXO_AUSENTE)):
            con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                           VALUES (?,?,?,?,'','1','','','rtsp','','300k')""", (cid, "bancada", cid, fluxo))
        # o ultimo envio de cada camera diz QUAL entrada ela usa (e' o que o ligar reusa). Colunas reais
        # de `ingestoes`: sem `fps_alvo`/`srt_port` (o ligar cai nos padroes 30 fps e 8890 quando faltam).
        for fluxo, rotulo, fonte in ((FLUXO, "cam-standby", f"dshow:{dispositivo or 'ENTRADA-QUE-NAO-EXISTE'}"),
                                     (FLUXO_AUSENTE, "cam-ausente", "dshow:CAMERA-QUE-NAO-EXISTE-NESTA-MAQUINA")):
            con.execute("""INSERT INTO ingestoes (fluxo_id,rotulo,fonte,tipo,repetir,codec,bitrate_alvo,
                           resolucao,fps,estado,srt_host,criado_em,atualizado_em)
                           VALUES (?,?,?,'camera',1,'libx264','300k','1280x720',30,'parado','127.0.0.1',?,?)""",
                        (fluxo, rotulo, fonte, agora(), agora()))
        tok = sessao_de(con)
        con.close()

        # --- 5) perguntar a prontidao NAO abre camera nenhuma
        antes = len(comandos_dos_ffmpeg())
        _, pront = pedir("GET", base + "/api/cameras/prontidao", cookie=tok)
        depois = len(comandos_dos_ffmpeg())
        exigir(pront.get("maquina_de_captura") is True, "esta maquina se reconhece como a de captura")
        exigir(antes == depois and not ffmpeg_do_fluxo(FLUXO),
               f"medir a prontidao nao abre camera (ffmpeg antes={antes} depois={depois})")

        # --- 4) camera com dispositivo ausente
        est = {c["id"]: c for c in (pront.get("cameras") or [])}
        a = est.get("cam-ausente") or {}
        exigir(a.get("estado") == "ausente" and "split" in str(a.get("motivo") or ""),
               f"camera sem o dispositivo aparece 'ausente' antes do cliente tentar ({a.get('estado')!r}: {a.get('motivo')!r})")

        if not dispositivo:
            nota("NAO MEDIDO: a maquina nao tem dispositivo de video — a prova por processo fica de fora")
            s = est.get("cam-standby") or {}
            exigir(s.get("estado") in ("sem_dispositivo", "ausente"),
                   f"sem dispositivo, a tela diz sem_dispositivo/ausente em vez de 'pronta' ({s.get('estado')!r})")
        elif not (MEDIAMTX.exists() and CONF_MEDIAMTX.exists()) and not tomadas:
            nota("NAO MEDIDO: sem mediamtx nesta maquina para receber o fluxo (a prova por processo fica de fora)")
        else:
            # --- 1) STAND-BY: pronta e ZERO ffmpeg deste fluxo
            s = est.get("cam-standby") or {}
            exigir(s.get("estado") == "pronta", f"em stand-by a camera esta' 'pronta' ({s.get('estado')!r})")
            exigir(not ffmpeg_do_fluxo(FLUXO),
                   f"em stand-by nenhum ffmpeg deste fluxo roda (achou {len(ffmpeg_do_fluxo(FLUXO))})")

            # --- 2) o cliente ativa: a camera entra no ar e o ffmpeg aparece
            st, j = pedir("POST", base + "/api/cameras/ligar", {"camera_id": "cam-standby"}, cookie=tok)
            exigir(st in (200, 422), f"ligar respondeu {st}")
            estado = espera_estado(base, tok, FLUXO, "no_ar")
            vivos = ffmpeg_do_fluxo(FLUXO)
            exigir(estado == "no_ar" and len(vivos) >= 1,
                   f"depois da ativacao o fluxo esta' no ar com ffmpeg rodando (estado={estado!r}, "
                   f"processos={len(vivos)}, resposta do ligar={str(j)[:90]})")

            # --- 3) o cliente sai: nenhum ffmpeg continua e a camera volta ao stand-by
            st, j2 = pedir("POST", base + "/api/cameras/desligar", {"camera_id": "cam-standby"}, cookie=tok)
            estado2 = espera_estado(base, tok, FLUXO, "pronta")
            restou = ffmpeg_do_fluxo(FLUXO)
            exigir(estado2 == "pronta" and not restou,
                   f"depois de desligar: nenhum ffmpeg do fluxo e a camera volta ao stand-by "
                   f"(estado={estado2!r}, processos={len(restou)}, resposta={str(j2)[:80]})")
    finally:
        if api:
            try:
                api.terminate()
            except Exception:
                pass
        if faixas[0]:
            try:
                faixas[0].terminate()
            except Exception:
                pass

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — stand-by de verdade: nada rodando em repouso, camera no ar so' quando o cliente ativa")
    return 0


def agora() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
