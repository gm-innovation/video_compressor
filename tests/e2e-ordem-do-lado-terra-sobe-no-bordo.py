#!/usr/bin/env python3
"""CADEIA INTEIRA da 0.6.10: o cliente ativa no painel (LADO TERRA) e o BORDO liga a camera de verdade.

Regra do produto (dono, 19/11/2026): "o nosso sistema transmite apenas quando o cliente ativar no painel
web" — e o clique nasce no lado terra. Nada de tecnico na embarcacao: a ordem vai para o bordo e o AGENTE
DE ORDENS do bordo obedece.

    python tests/e2e-ordem-do-lado-terra-sobe-no-bordo.py

Este e' o teste que faltava: os outros provam as PECAS (o lado terra cria ordem; o agente obedece; o
stand-by nao abre camera). Aqui as pecas rodam JUNTAS, de ponta a ponta, com camera REAL:

  1) os dois lados de pe' (lado terra e bordo) e o agente do bordo vivo — em repouso, NENHUM ffmpeg;
  2) o operador clica "ligar" no LADO TERRA (requisicao de fora da maquina, como o navegador):
     - o lado terra responde 200 e diz `enviado_ao_bordo: true`;
     - NENHUM ffmpeg nasce no lado terra (ele nao tem entrada de video: quem captura e' o bordo);
  3) o AGENTE do bordo pega a ordem e a camera entra NO AR no bordo (ffmpeg do fluxo vivo, medido por
     processo); a ordem vira `atendida` no lado terra com o resultado do bordo;
  4) a trilha do lado terra registra `ordem_camera_ligada` (e nunca um `camera_ligada` falso);
  5) ao desligar, a ordem `parar` chega, o ffmpeg do bordo morre e a camera volta ao stand-by.

Sem dispositivo de video nesta maquina a parte ao vivo e' declarada NAO MEDIDA (o resto roda).
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
TOKEN = "token-de-ingestao-do-teste"
FLUXO = "vivo-cadeia-1901"
MEDIAMTX = RAIZ / "tools" / "mediamtx" / ("mediamtx.exe" if os.name == "nt" else "mediamtx")
CONF_MEDIAMTX = RAIZ / "ground" / "mediamtx.yml"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def agora() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


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


def ip_lan() -> str:
    """IP desta maquina na rede: por ele a requisicao NAO conta como 'local' (como o navegador de fora)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def pedir(metodo, url, corpo=None, cookie="", token=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token:
        cab["Authorization"] = f"Bearer {token}"
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
                return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-400:])


def sessao_de(con, uid="admin-1", email="admin@lecsor.test", papel="operador"):
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


def espera(cond, teto_s: float = 60.0) -> bool:
    fim = time.time() + teto_s
    while time.time() < fim:
        if cond():
            return True
        time.sleep(1.0)
    return False


def estado_da_ordem(banco: pathlib.Path, seq_ou_id: str) -> dict:
    con = sqlite3.connect(banco)
    con.row_factory = sqlite3.Row
    try:
        l = con.execute("SELECT * FROM ordens_do_bordo WHERE id=? OR seq=?", (seq_ou_id, seq_ou_id)).fetchone()
        return dict(l) if l else {}
    finally:
        con.close()


def trilha(banco: pathlib.Path, acao: str) -> int:
    con = sqlite3.connect(banco)
    try:
        return int(con.execute("SELECT COUNT(*) FROM auditoria_acesso WHERE acao=?", (acao,)).fetchone()[0])
    finally:
        con.close()


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-cadeia-"))
    terra_db, bordo_db = tmp / "terra.db", tmp / "bordo.db"
    p_terra, p_bordo = porta_livre(), porta_livre()
    while p_bordo == p_terra:
        p_bordo = porta_livre({p_terra})
    lan = ip_lan()
    procs: list = []
    faixas: list = [None]
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

    try:
        base_terra_cfg = f"http://127.0.0.1:{p_terra}"
        proc_t = sobe_api(terra_db, p_terra, {"LECSOR_LADO_TERRA_API": base_terra_cfg,   # o lado terra e' o lado terra
                                             "LECSOR_BIND": "0.0.0.0",                 # escuta como o servico da VPS
                                             "LECSOR_TOKEN_INGESTAO": TOKEN})          # o lado terra CONFERE o token do bordo
        procs.append(proc_t)
        proc_b = sobe_api(bordo_db, p_bordo, {"LECSOR_EMBARCACAO": "bancada",           # ESTA maquina e' o bordo
                                              "LECSOR_LADO_TERRA_API": base_terra_cfg,
                                              "LECSOR_TOKEN_INGESTAO": TOKEN,
                                              "LECSOR_PORTA_API": str(p_bordo)})
        procs.append(proc_b)
        base_terra_local = f"http://127.0.0.1:{p_terra}"
        base_bordo = f"http://127.0.0.1:{p_bordo}"
        # o clique do operador chega de FORA (navegador): pelo IP de rede a API nao trata como local
        base_terra = f"http://{lan}:{p_terra}" if lan != "127.0.0.1" else base_terra_local
        nota(f"lado terra {base_terra_local} (clique por {base_terra}) · bordo {base_bordo}")

        # dispositivo REAL desta maquina, lido pelo proprio produto
        _, disp = pedir("GET", base_bordo + "/api/dispositivos")
        video = (disp.get("dispositivos") or disp.get("video") or [])
        nomes = [d.get("video") if isinstance(d, dict) else d for d in video]
        dispositivo = (nomes or [""])[0]
        nota(f"dispositivos de video nesta maquina: {nomes or 'nenhum'}")

        # base dos dois lados: mesma camera, mesma embarcacao
        for banco in (terra_db, bordo_db):
            con = sqlite3.connect(banco)
            con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
            con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
            con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                           VALUES ('cam-01','bancada','Proa',?,'','1','','','rtsp','','300k')""", (FLUXO,))
            con.commit()
            con.close()
        # no BORDO, o ultimo envio diz a entrada real (dshow). No lado terra nao ha' envio nenhum: ele
        # nao captura — e' justamente isso que este teste prova.
        con = sqlite3.connect(bordo_db)
        con.execute("""INSERT INTO ingestoes (fluxo_id,rotulo,fonte,tipo,repetir,codec,bitrate_alvo,
                       resolucao,fps,estado,srt_host,criado_em,atualizado_em)
                       VALUES (?,?,?,'camera',1,'libx264','300k','1280x720',30,'parado','127.0.0.1',?,?)""",
                    (FLUXO, "cam-01", f"dshow:{dispositivo or 'ENTRADA-QUE-NAO-EXISTE'}", agora(), agora()))
        con.commit()
        con.close()
        con = sqlite3.connect(terra_db)
        tok = sessao_de(con)
        con.close()

        # --- 1) em repouso, ninguem ligou nada, mas ja' ha' ordem de camera antes de o cliente pedir
        exigir(not ffmpeg_do_fluxo(FLUXO),
               f"em repouso nenhum ffmpeg do fluxo roda ({len(ffmpeg_do_fluxo(FLUXO))})")
        _, pront = pedir("GET", base_bordo + "/api/cameras/prontidao", cookie=tok)
        exigir(pront.get("maquina_de_captura") is True,
               "o bordo se reconhece como a maquina de captura")

        # --- 2) o operador clica LIGAR no lado terra (pedido de fora da maquina)
        n_ff_terra_antes = len([l for l in comandos_dos_ffmpeg()])
        st, jl = pedir("POST", base_terra + "/api/cameras/ligar", {"camera_id": "cam-01"}, cookie=tok)
        exigir(st == 200 and jl.get("enviado_ao_bordo") is True,
               f"o lado terra aceita o clique e diz que enviou ao bordo ({st}, {str(jl)[:100]})")
        seq = jl.get("ordem")
        exigir(not ffmpeg_do_fluxo(FLUXO),
               f"o lado terra NAO abre camera nenhuma (ffmpeg do fluxo nele: {len(ffmpeg_do_fluxo(FLUXO))})")
        exigir(trilha(terra_db, "ordem_camera_ligada") == 1 and trilha(terra_db, "camera_ligada") == 0,
               "a trilha do lado terra registra ordem_camera_ligada (e nenhum camera_ligada falso)")

        if not dispositivo or not (MEDIAMTX.exists() and CONF_MEDIAMTX.exists() or tomadas):
            nota("NAO MEDIDO: sem dispositivo de video ou sem mediamtx — a parte ao vivo fica de fora")
        else:
            # --- 3) o AGENTE DO BORDO pega a ordem e a camera entra no ar
            env_ag = dict(os.environ)
            env_ag.update({"LECSOR_LADO_TERRA_API": base_terra_cfg,
                           "LECSOR_EMBARCACAO": "bancada",
                           "LECSOR_TOKEN_INGESTAO": TOKEN,
                           "LECSOR_PORTA_LOCAL": str(p_bordo),
                           "LECSOR_ORDENS_ESTADO": str(tmp / "ligados.json"),
                           "PYTHONIOENCODING": "utf-8"})
            log_ag = (tmp / "agente.log").open("wb")
            agente = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py"),
                                       "--espera", "3"], cwd=str(RAIZ), env=env_ag,
                                      stdout=log_ag, stderr=subprocess.STDOUT)
            procs.append(agente)
            entrou = espera(lambda: len(ffmpeg_do_fluxo(FLUXO)) >= 1, 70.0)
            exigir(entrou, f"o agente do bordo obedeceu: a camera esta' NO AR no bordo "
                           f"(ffmpeg do fluxo: {len(ffmpeg_do_fluxo(FLUXO))})")
            atendida = espera(lambda: estado_da_ordem(terra_db, str(seq)).get("estado") == "atendida", 40.0)
            o = estado_da_ordem(terra_db, str(seq))
            exigir(atendida and "feito" in str(o.get("resultado") or "").lower(),
                   f"a ordem vira 'atendida' no lado terra com o resultado do bordo "
                   f"({o.get('estado')!r}: {str(o.get('resultado'))[:90]!r})")

            # --- 5) o cliente sai: ordem `parar` chega ao bordo e a camera volta ao stand-by
            st2, j2 = pedir("POST", base_terra + "/api/cameras/desligar", {"camera_id": "cam-01"}, cookie=tok)
            exigir(st2 == 200 and j2.get("enviado_ao_bordo") is True,
                   f"o clique de desligar vira ordem para o bordo ({st2})")
            morreu = espera(lambda: not ffmpeg_do_fluxo(FLUXO), 70.0)
            exigir(morreu, f"o bordo obedeceu o parar: nenhum ffmpeg do fluxo continua "
                           f"({len(ffmpeg_do_fluxo(FLUXO))})")
            exigir(trilha(terra_db, "ordem_camera_desligada") == 1,
                   "a trilha do lado terra registra ordem_camera_desligada")
            _, p2 = pedir("GET", base_bordo + "/api/cameras/prontidao", cookie=tok)
            est = {c["id"]: c.get("estado") for c in (p2.get("cameras") or [])}
            exigir(est.get("cam-01") == "pronta",
                   f"a camera voltou ao stand-by no bordo (estado={est.get('cam-01')!r})")
    finally:
        for p in procs:
            try:
                p.terminate()
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
    print("OK — a cadeia inteira funciona: o cliente ativa no painel, o lado terra manda a ordem, "
          "o bordo liga a camera e o resultado volta")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
