#!/usr/bin/env python3
"""Agente de ordens do bordo: a ordem do lado terra chega e a maquina de captura OBEDECE.

Aqui rodam DOIS servidores de verdade (o lado terra e o bordo) e o agente de verdade, como processo:

    python tests/test-agente-de-ordens.py

Provas:
  1) sem LECSOR_TOKEN_INGESTAO / LECSOR_EMBARCACAO o agente nao pergunta nada e diz por que (sai 2);
  2) a ordem de INICIAR do cliente chega ao agente e ele chama a API LOCAL do bordo;
  3) o que a API local responde volta para o lado terra (o bordo nao inventa sucesso): a camera que
     nunca foi transmitida desta maquina devolve erro, e o erro CHEGA ao historico do cliente;
  4) a ordem de PARAR tambem e' executada e contada ao lado terra;
  5) API local fora do ar: o agente conta a falha, nunca "atendida";
  6) TETO DO BORDO: o envio que este agente ligou e ninguem mandou parar e' cortado pela PROPRIA
     maquina de captura depois do teto (envio orfao) — e ele nao finge corte quando a API local nao
     responde. O que ele ligou fica em disco e sobrevive ao reinicio do agente.
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
TOKEN = "token-de-teste-do-agente"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(metodo, url, corpo=None, token_sessao="", token_bordo=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if token_sessao:
        cab["Cookie"] = f"sessao={token_sessao}"
    if token_bordo:
        cab["Authorization"] = f"Bearer {token_bordo}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=40) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict | None = None):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra or {})
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                return proc, base, log
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"a API de {banco} nao subiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-400:])


def sessao_de(con, uid, email, papel="cliente"):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,'lecsor',?,?,200000,1)""", (uid, email, uid, papel, senha, salt))
    tok = f"tok-{uid}"
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    return tok


def agente(base_terra: str, porta_local: int, emb="bancada", token=TOKEN, espera="0"):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["LECSOR_LADO_TERRA_API"] = base_terra
    env["LECSOR_TOKEN_INGESTAO"] = token
    env["LECSOR_EMBARCACAO"] = emb
    env["LECSOR_PORTA_LOCAL"] = str(porta_local)
    for k in ("LECSOR_DESTINO_SRT",):
        env.pop(k, None)
    p = subprocess.run([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py"),
                        "--uma-vez", "--espera", espera],
                       cwd=str(RAIZ), env=env, capture_output=True, text=True, timeout=90)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def linha(banco, sql, args=()):
    con = sqlite3.connect(banco)
    r = con.execute(sql, args).fetchone()
    con.close()
    return r


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-agente-"))
    terra_db = tmp / "terra.db"
    bordo_db = tmp / "bordo.db"
    p_terra, p_bordo = porta_livre(), porta_livre()
    api_terra = api_bordo = None
    log_t = log_b = None
    try:
        api_terra, base_terra, log_t = sobe_api(terra_db, p_terra,
                                               {"LECSOR_TOKEN_INGESTAO": TOKEN, "LECSOR_EMBARCACAO": "bancada"})
        api_bordo, base_bordo, log_b = sobe_api(bordo_db, p_bordo,
                                                {"LECSOR_EMBARCACAO": "bancada", "LECSOR_PORT": str(p_bordo)})
        con = sqlite3.connect(terra_db)
        con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo)
                       VALUES ('cam-01','bancada','Proa','cam-01','bordo',1)""")
        tok = sessao_de(con, "cli1", "cliente@pipeline.test")
        con.commit()
        con.close()
        # no BORDO existe a MESMA camera, sem nenhum envio ainda (foi o caso real: camera cadastrada e
        # nunca transmitida daquela maquina)
        con = sqlite3.connect(bordo_db)
        con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo)
                       VALUES ('cam-01','bancada','Proa','cam-01','bordo',1)""")
        con.commit()
        con.close()

        # --- 1) sem configuracao o agente avisa e nao finge ------------------------------------------
        env_sem = dict(os.environ)
        env_sem.pop("LECSOR_TOKEN_INGESTAO", None)
        env_sem.pop("LECSOR_EMBARCACAO", None)
        env_sem.pop("LECSOR_LADO_TERRA_API", None)
        env_sem["PYTHONIOENCODING"] = "utf-8"
        p = subprocess.run([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py"), "--uma-vez"],
                           cwd=str(RAIZ), env=env_sem, capture_output=True, text=True, timeout=60)
        exigir(p.returncode == 2 and "LECSOR_EMBARCACAO" in (p.stdout + p.stderr),
               f"sem token/embarcacao o agente sai 2 e diz por que ({p.returncode})")

        # --- 2) o cliente pede: a ordem chega ao agente e ele chama a API local ----------------------
        s, j = pedir("POST", base_terra + "/api/transmissao/iniciar", {"camera_id": "cam-01", "segundos_max": 300},
                     token_sessao=tok)
        exigir(s == 201, f"o cliente abriu a transmissao no lado terra ({s} {j.get('erro')})")
        tid = (j.get("transmissao") or {}).get("id", "")
        rc, saida = agente(base_terra, p_bordo)
        exigir(rc == 0 and "recebi 1 ordem" in saida, f"o agente recebeu a ordem e saiu limpo ({rc}) {saida.strip()[:160]}")
        ordem = linha(terra_db, "SELECT id, estado, resultado FROM ordens_do_bordo ORDER BY seq LIMIT 1")
        exigir(ordem and ordem[1] == "erro",
               f"a API local recusou (camera nunca transmitida desta maquina) e o agente contou o ERRO, sem inventar ({ordem})")
        exigir(ordem and "nunca foi transmitida" in ordem[2],
               f"o motivo que voltou e' o da API local ({ordem[2] if ordem else None})")
        r = linha(terra_db, "SELECT estado, motivo FROM transmissoes WHERE id=?", (tid,))
        exigir(r and r[0] == "erro" and "nunca foi transmitida" in (r[1] or ""),
               f"o erro chegou ao historico do cliente ({r})")

        # --- 3) a ordem de PARAR tambem e' executada e contada ---------------------------------------
        s, j = pedir("POST", base_terra + "/api/transmissao/iniciar", {"camera_id": "cam-01", "segundos_max": 300},
                     token_sessao=tok)
        tid2 = (j.get("transmissao") or {}).get("id", "")
        pedir("POST", base_terra + f"/api/transmissao/{tid2}/encerrar", {}, token_sessao=tok)
        fila = linha(terra_db, "SELECT id FROM ordens_do_bordo WHERE acao='parar' AND estado='pedido' ORDER BY seq DESC LIMIT 1")
        exigir(bool(fila), "o lado terra enfileirou a ordem de parar")
        rc, saida = agente(base_terra, p_bordo)
        exigir(rc == 0, f"o agente rodou de novo ({rc})")
        o = linha(terra_db, "SELECT estado, resultado, atendida_em FROM ordens_do_bordo WHERE id=?", (fila[0],))
        exigir(o and o[0] == "atendida" and o[2],
               f"o agente executou o parar na API local e contou o resultado ({o})")

        # --- 4) API local fora do ar: o agente conta a falha (nunca "atendida") ----------------------
        api_bordo.terminate()
        api_bordo.wait(timeout=15)
        s, j = pedir("POST", base_terra + "/api/transmissao/iniciar", {"camera_id": "cam-01", "segundos_max": 300},
                     token_sessao=tok)
        rc, saida = agente(base_terra, p_bordo)
        exigir(rc == 0, f"o agente nao quebra quando a API local esta' fora do ar ({rc})")
        ordem = linha(terra_db, """SELECT estado, resultado FROM ordens_do_bordo
                                   WHERE acao='iniciar' ORDER BY seq DESC LIMIT 1""")
        exigir(ordem and ordem[0] == "erro" and ordem[1],
               f"sem API local, a ordem vira ERRO com o motivo, nao 'atendida' ({ordem})")
        s, j = pedir("GET", base_terra + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)
        exigir(s == 200 and not j.get("ordens"),
               f"nao sobra ordem pendente na fila do lado terra ({j.get('ordens')})")

        # --- 5) TETO DO BORDO: o envio orfao e' cortado pela propria maquina de captura --------------
        # A API local aqui e' um servidor de mentira que RESPONDE 200: o que se prova e' a regra do
        # agente (quando corta, o que ele chama e o que ele nao inventa), nao o ffmpeg da camera.
        import importlib.util
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        recebidas: list[tuple] = []

        class LocalDeMentira(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    corpo = json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    corpo = {}
                recebidas.append((self.path, corpo))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "fluxo_id": "cam-01"}).encode())

            def log_message(self, *a):
                pass

        p_fake = porta_livre()
        fake = HTTPServer(("127.0.0.1", p_fake), LocalDeMentira)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        local_fake = f"http://127.0.0.1:{p_fake}"

        spec = importlib.util.spec_from_file_location("agente_do_bordo", RAIZ / "ground" / "agente_de_ordens.py")
        ag = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ag)
        os.environ["LECSOR_ORDENS_ESTADO"] = str(tmp / "ligados.json")

        os.environ["LECSOR_TETO_DO_BORDO"] = "3600"
        ag.LIGADOS.clear()
        ag.LIGADOS["cam-01"] = {"camera_id": "cam-01", "desde": time.time()}
        ag._salvar_ligados()
        ag.LIGADOS.clear()
        ag.LIGADOS.update(ag._carregar_ligados())
        exigir(ag.LIGADOS.get("cam-01"),
               "o que o agente ligou fica guardado em disco (sobrevive ao reinicio do agente)")
        exigir(ag.vigiar_teto(local_fake) == [] and not recebidas,
               "antes do teto o agente NAO derruba o envio (nem toca na camera)")

        os.environ["LECSOR_TETO_DO_BORDO"] = "1"
        ag.LIGADOS["cam-01"] = {"camera_id": "cam-01", "desde": time.time() - 5}
        cortados = ag.vigiar_teto(local_fake)
        exigir([c["camera_id"] for c in cortados] == ["cam-01"],
               f"passado o teto, o agente corta o envio orfao sozinho ({cortados})")
        exigir(any(p == "/api/cameras/desligar" and c.get("camera_id") == "cam-01" for p, c in recebidas),
               f"o corte chama a API local de desligar ({recebidas})")
        exigir(not ag.LIGADOS, "depois de cortar, o agente esquece o envio (nao corta duas vezes)")

        os.environ["LECSOR_TETO_DO_BORDO"] = "1"
        ag.LIGADOS["cam-09"] = {"camera_id": "cam-09", "desde": time.time() - 5}
        cortados2 = ag.vigiar_teto("http://127.0.0.1:1")   # ninguem escutando nesta porta
        exigir(cortados2 == [] and bool(ag.LIGADOS.get("cam-09")),
               "API local fora do ar: o agente nao finge que cortou (vai tentar de novo)")
        os.environ.pop("LECSOR_TETO_DO_BORDO", None)
        os.environ.pop("LECSOR_ORDENS_ESTADO", None)
        fake.shutdown()
    finally:
        for proc in (api_terra, api_bordo):
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=15)
                except Exception:
                    proc.kill()
        for f in (log_t, log_b):
            if f:
                f.close()

    print()
    if falhas:
        print(f"FALHAS ({len(falhas)}):")
        for f in falhas:
            print(" -", f)
        return 1
    print("TUDO OK — o agente do bordo recebe a ordem do lado terra, obedece e conta exatamente o que houve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
