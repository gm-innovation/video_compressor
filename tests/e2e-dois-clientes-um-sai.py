#!/usr/bin/env python3
"""DOIS CLIENTES, UM SAI (0.7.0): a transmissao so' para quando NAO SOBRA ninguem assistindo.

Palavras do dono (19/11/2026): "terra (vps) precisa saber se a tela foi fechada, computador desligado ou
falta de conexao no computador do usuario para interromper a transmissao, a menos que haja outro usuario
conectado e acompanhando".

    python tests/e2e-dois-clientes-um-sai.py

O que este teste mede (camera real + agente de verdade, os dois lados de pe'):
  1) dois clientes abrem a MESMA camera: a flag diz `ligar` com 2 sessoes;
  2) o bordo entra no ar (ffmpeg do fluxo medido por processo);
  3) o cliente A SAI da tela: a sessao DELE cai (`cliente_saiu_da_tela`) e a camera CONTINUA no ar —
     porque o cliente B ainda esta' assistindo (a flag segue `ligar`, agora com 1 sessao);
  4) o cliente B PERDE A CONEXAO (batimento velho): o vigia do lado terra fecha a sessao dele e, como
     ninguem mais esta' vendo, a flag vira `parar` e o bordo desliga a camera;
  5) o TEMPO da sessao e' FIXADO pelo admin: o cliente pede 5 min e o admin fixou 30 min — a sessao
     nasce com 30 min (o que o cliente escolheu na tela nao vale).
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
FLUXO = "vivo-dois-1901"
MEDIAMTX = RAIZ / "tools" / "mediamtx" / ("mediamtx.exe" if os.name == "nt" else "mediamtx")
CONF_MEDIAMTX = RAIZ / "ground" / "mediamtx.yml"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def porta_livre(excluir=None) -> int:
    excluir = excluir or set()
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        if p not in excluir:
            return p


def portas_tomadas() -> set:
    t = set()
    for p in (8890, 9997):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) == 0:
                t.add(p)
    return t


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


def ffmpeg_do_fluxo(fluxo: str) -> list:
    if os.name == "nt":
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
                            "Select-Object -ExpandProperty CommandLine"],
                           capture_output=True, text=True, errors="replace")
        linhas = [l for l in (r.stdout or "").splitlines() if l.strip()]
    else:
        r = subprocess.run(["bash", "-lc", "pgrep -af ffmpeg || true"], capture_output=True, text=True,
                           errors="replace")
        linhas = [l for l in (r.stdout or "").splitlines() if l.strip()]
    return [l for l in linhas if fluxo in l]


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
            raise RuntimeError(f"a API saiu ({proc.returncode}): "
                               + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-500:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-500:])


def sessao_de(con, uid, email, papel="cliente", cliente_id="lecsor"):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    tok = "tok-" + uid
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    return tok


def espera(cond, teto_s=70.0) -> bool:
    fim = time.time() + teto_s
    while time.time() < fim:
        if cond():
            return True
        time.sleep(1.0)
    return False


def um(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def executa(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-dois-"))
    terra_db, bordo_db = tmp / "terra.db", tmp / "bordo.db"
    p_terra = porta_livre()
    p_bordo = porta_livre({p_terra})
    procs: list = []
    faixas: list = [None]
    tomadas = portas_tomadas()
    if not (tomadas & {8890, 9997}) and MEDIAMTX.exists() and CONF_MEDIAMTX.exists():
        faixas[0] = subprocess.Popen([str(MEDIAMTX), str(CONF_MEDIAMTX)], cwd=str(RAIZ),
                                     stdout=(tmp / "mediamtx.log").open("wb"), stderr=subprocess.STDOUT)
        time.sleep(2.5)
    try:
        base_cfg = f"http://127.0.0.1:{p_terra}"
        procs.append(sobe_api(terra_db, p_terra, {"LECSOR_LADO_TERRA_API": base_cfg,
                                                  "LECSOR_BIND": "0.0.0.0",
                                                  "LECSOR_TOKEN_INGESTAO": TOKEN}))
        procs.append(sobe_api(bordo_db, p_bordo, {"LECSOR_EMBARCACAO": "bancada",
                                                  "LECSOR_LADO_TERRA_API": base_cfg,
                                                  "LECSOR_TOKEN_INGESTAO": TOKEN,
                                                  "LECSOR_PORTA_API": str(p_bordo)}))
        base_terra, base_bordo = f"http://127.0.0.1:{p_terra}", f"http://127.0.0.1:{p_bordo}"
        _, disp = pedir("GET", base_bordo + "/api/dispositivos")
        video = (disp.get("dispositivos") or disp.get("video") or [])
        nomes = [d.get("video") if isinstance(d, dict) else d for d in video]
        dispositivo = (nomes or [""])[0]
        nota(f"dispositivos de video desta maquina: {nomes or 'nenhum'}")

        for banco in (terra_db, bordo_db):
            executa(banco, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
            executa(banco, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
            executa(banco, """INSERT OR REPLACE INTO cameras
                              (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                              VALUES ('cam-01','bancada','Proa',?,'',1,'','','rtsp','','300k')""", (FLUXO,))
        agora = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        executa(bordo_db, """INSERT INTO ingestoes (fluxo_id,rotulo,fonte,tipo,repetir,codec,bitrate_alvo,
                             resolucao,fps,estado,srt_host,criado_em,atualizado_em)
                             VALUES (?,?,?,'camera',1,'libx264','300k','1280x720',30,
                             'parado','127.0.0.1',?,?)""",
                (FLUXO, "cam-01", f"dshow:{dispositivo or 'ENTRADA-INEXISTENTE'}", agora, agora))
        con = sqlite3.connect(str(terra_db))
        tok_a = sessao_de(con, "cli-a", "a@lecsor.test")
        tok_b = sessao_de(con, "cli-b", "b@lecsor.test")
        con.close()
        # o admin FIXA o tempo da sessao em 30 min, na tela dele
        executa(terra_db, """INSERT INTO configs_do_produto (chave,valor,atualizado_em)
                             VALUES ('tempo_maximo_do_produto','1800',?)""", (agora,))

        # --- 1) os dois clientes abrem a mesma camera; o cliente A pede 5 min e o admin fixou 30
        st_a, ja = pedir("POST", base_terra + "/api/transmissao/iniciar",
                         {"camera_id": "cam-01", "segundos_max": 300}, cookie=tok_a)
        st_b, jb = pedir("POST", base_terra + "/api/transmissao/iniciar", {"camera_id": "cam-01"}, cookie=tok_b)
        ta = um(terra_db, "SELECT * FROM transmissoes WHERE usuario_email='a@lecsor.test'")
        exigir(st_a == 201 and ta.get("segundos_max") == 1800 and ja.get("cortado_pelo_teto_do_produto") is True,
               f"o tempo da sessao e' FIXADO pelo admin: o cliente A pediu 5 min e a sessao nasceu com "
               f"{ta.get('segundos_max')}s (teto do produto)")
        exigir(st_b == 201 and um(terra_db, "SELECT * FROM transmissoes WHERE usuario_email='b@lecsor.test'").get("id"),
               "o cliente B abriu a mesma camera (segunda sessao)")
        st, jd = pedir("GET", base_terra + "/api/estado-desejado?embarcacao_id=bancada", token=TOKEN)
        cam = {c["camera_id"]: c for c in (jd.get("cameras") or [])}.get("cam-01", {})
        exigir(cam.get("desejo") == "ligar" and "2 sessao" in str(cam.get("motivo")),
               f"a flag diz LIGAR por causa de 2 sessoes ({str(cam.get('motivo'))[:60]!r})")

        if not dispositivo or not (tomadas or MEDIAMTX.exists()):
            nota("NAO MEDIDO: sem dispositivo/mediamtx — a parte ao vivo fica de fora")
        else:
            env_ag = dict(os.environ)
            env_ag.update({"LECSOR_LADO_TERRA_API": base_cfg, "LECSOR_EMBARCACAO": "bancada",
                           "LECSOR_TOKEN_INGESTAO": TOKEN, "LECSOR_PORTA_LOCAL": str(p_bordo),
                           "LECSOR_ORDENS_ESTADO": str(tmp / "ligados.json"),
                           "LECSOR_ESPERA_DA_FLAG": "1", "PYTHONIOENCODING": "utf-8"})
            procs.append(subprocess.Popen([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py")],
                                          cwd=str(RAIZ), env=env_ag,
                                          stdout=(tmp / "agente.log").open("wb"), stderr=subprocess.STDOUT))
            exigir(espera(lambda: len(ffmpeg_do_fluxo(FLUXO)) >= 1, 70.0),
                   f"o bordo entrou no ar ({len(ffmpeg_do_fluxo(FLUXO))} ffmpeg do fluxo)")

            # --- 3) o cliente A SAI: a sessao dele cai e a camera CONTINUA (o B ainda assiste)
            st, js = pedir("POST", base_terra + "/api/transmissao/sair", {}, cookie=tok_a)
            exigir(st == 200 and js.get("sessoes_fechadas") == 1,
                   f"a sessao do cliente A caiu ({js.get('sessoes_fechadas')})")
            time.sleep(6)
            st, jd2 = pedir("GET", base_terra + "/api/estado-desejado?embarcacao_id=bancada", token=TOKEN)
            cam2 = {c["camera_id"]: c for c in (jd2.get("cameras") or [])}.get("cam-01", {})
            exigir(cam2.get("desejo") == "ligar" and "1 sessao" in str(cam2.get("motivo")),
                   f"a flag CONTINUA em LIGAR por causa do cliente B ({str(cam2.get('motivo'))[:60]!r})")
            exigir(len(ffmpeg_do_fluxo(FLUXO)) >= 1,
                   f"a camera CONTINUA no ar depois de o cliente A sair ({len(ffmpeg_do_fluxo(FLUXO))})")

            # --- 4) o cliente B perde a conexao (batimento velho): o vigia fecha a sessao e o bordo desliga
            velho = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=200)).isoformat(timespec="seconds")
            executa(terra_db, "UPDATE transmissoes SET batimento_em=? WHERE usuario_email='b@lecsor.test'", (velho,))
            fechou = espera(lambda: um(terra_db, "SELECT * FROM transmissoes WHERE usuario_email='b@lecsor.test'")
                            .get("estado") in ("encerrada", "expirada", "erro", "sem_sinal"), 40.0)
            exigir(fechou, "o vigia fechou a sessao do cliente B por falta de conexao (sem batimento)")
            desligou = espera(lambda: not ffmpeg_do_fluxo(FLUXO), 60.0)
            exigir(desligou, f"ninguem mais assistindo: o bordo desligou a camera ({len(ffmpeg_do_fluxo(FLUXO))} ffmpeg)")
            st, jd3 = pedir("GET", base_terra + "/api/estado-desejado?embarcacao_id=bancada", token=TOKEN)
            cam3 = {c["camera_id"]: c for c in (jd3.get("cameras") or [])}.get("cam-01", {})
            exigir(cam3.get("desejo") == "parar", f"a flag virou PARAR ({cam3.get('desejo')!r})")
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
    print("OK — a transmissao so' para quando NAO SOBRA ninguem assistindo, e o tempo da sessao e' o que "
          "o admin fixou")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
