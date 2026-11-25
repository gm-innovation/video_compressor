#!/usr/bin/env python3
"""MATRIZ DE PERMISSOES DA CONFIGURACAO (0.8.0, Fase 3) — provada por HTTP, nao por leitura de codigo.

O dono (17/11/2026): "um usuario nao pode se cadastrar, quem cadastra os usuarios e' o admin... vamos
empacotar em um app apenas, o tipo de app e' definido pela role do usuario". E (19/11/2026): "estou
pensando em utilizar no computador de captura apenas o usuario de captura, apenas para cadastrar as
cameras e radar de oleo, eu configuraria tudo pelo meu usuario admin".

Quem pode, provado:

  | acao                                  | cliente | tecnico/captura | operador | admin |
  |---------------------------------------|---------|-----------------|----------|-------|
  | publicar config do bordo              |   nao   |       nao       |   sim    |  sim  |
  | ver desejada x aplicada               |   nao   |       nao       |   sim    |  sim  |
  | cadastrar camera REMOTO               |   nao   |       nao       |   nao    |  sim  |
  | cadastrar camera na PROPRIA maquina   |   nao   |       sim       |   nao    |  sim  |
  | ler a config que terra publicou (bordo)|   nao   |  so' com token  |   nao    |  nao  |

D4 do dono (25/11/2026, verbatim: "D4. so' admin"): CADASTRAR/EDITAR o cadastro de camera e' do ADMIN.
O operador continua OPERANDO (qualidade, tempo) — o que ele perde e' o cadastro novo. Na PROPRIA maquina
de captura o cadastro segue local (o painel do bordo nao tem login).

"Remoto" aqui e' pedido vindo de outro IP (a API chama de `local` o pedido da propria maquina de captura);
o teste sobe a API com `LECSOR_BIND=0.0.0.0` e fala com ela pelo IP da maquina para ter os dois casos.

    python tests/test-papeis-de-config.py
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
BANCO = pathlib.Path(tempfile.mkdtemp(prefix="papeis-080-")) / "pipeline.db"
EMB = "bancada"
TOKEN_BORDO = "token-do-bordo-do-teste"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ip_da_maquina() -> str:
    """O IP por onde OUTRA maquina fala com esta: e' o que faz o pedido deixar de ser `local`."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return ""
    finally:
        s.close()


def pedir(metodo, url, corpo=None, cookie="", token=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            return f.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def sobe_api(porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(BANCO)
    env["PYTHONIOENCODING"] = "utf-8"
    env["LECSOR_BIND"] = "0.0.0.0"       # para haver "remoto" de verdade
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra)
    log = (BANCO.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (BANCO.parent / f"api-{porta}.log").read_text(errors="replace")[-600:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def sessao_de(uid, email, papel):
    con = sqlite3.connect(str(BANCO))
    con.row_factory = sqlite3.Row
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, None, senha, salt))
    tok = "tok-" + uid
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    con.close()
    return tok


def main() -> int:
    porta = porta_livre()
    ip = ip_da_maquina()
    print(f"[teste] API na porta {porta}; o IP desta maquina e' {ip or '(nao descoberto)'}")
    proc = sobe_api(porta, {"LECSOR_TOKEN_INGESTAO": TOKEN_BORDO, "LECSOR_EMBARCACAO": EMB})
    try:
        interno = f"http://127.0.0.1:{porta}"          # loopback  -> a API chama de `local`
        externo = f"http://{ip}:{porta}" if ip else interno   # outro IP  -> nao e' `local`
        if not ip:
            nota("sem IP de rede: os casos 'remoto' usam o loopback e valem menos — anote no resultado")
        time.sleep(1.0)

        toks = {p: sessao_de(p, f"{p}@lecsor.test", p) for p in ("cliente", "tecnico", "operador", "admin")}
        con = sqlite3.connect(str(BANCO))
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                    (EMB, "cliente", "Bancada de testes"))
        con.commit()
        con.close()

        # ---- 1. sem login: nada de config, nada de cadastro
        c, _ = pedir("POST", f"{externo}/api/config", {"embarcacao_id": EMB, "camera_id": "cam-1",
                                                       "chave": "alvo_kbps", "valor": "800"})
        exigir(c == 403, f"sem login POST /api/config -> 403 (veio {c})")
        c, _ = pedir("GET", f"{externo}/api/config?embarcacao_id={EMB}")
        exigir(c == 403, f"sem login GET /api/config -> 403 (veio {c})")
        c, _ = pedir("POST", f"{externo}/api/cameras", {"id": "x", "rotulo": "x", "fluxo_id": "x"})
        exigir(c == 401, f"sem login POST /api/cameras -> 401 (veio {c})")

        # ---- 2. cliente: ve o proprio video, nao configura nada
        c, j = pedir("GET", f"{externo}/api/config?embarcacao_id={EMB}", cookie=toks["cliente"])
        exigir(c == 403, f"cliente GET /api/config -> 403 (veio {c})")
        c, j = pedir("POST", f"{externo}/api/config", {"embarcacao_id": EMB, "camera_id": "cam-1",
                                                       "chave": "alvo_kbps", "valor": "800"}, cookie=toks["cliente"])
        exigir(c == 403, f"cliente POST /api/config -> 403 (veio {c})")
        c, j = pedir("POST", f"{externo}/api/cameras", {"id": "cli-1", "rotulo": "cli", "fluxo_id": "cli-1"},
                     cookie=toks["cliente"])
        exigir(c == 401, f"cliente POST /api/cameras -> 401 (veio {c})")

        # ---- 3. tecnico (captura) REMOTO: nao configura e nao cadastra
        c, _ = pedir("GET", f"{externo}/api/config?embarcacao_id={EMB}", cookie=toks["tecnico"])
        exigir(c == 403, f"tecnico remoto GET /api/config -> 403 (veio {c})")
        c, _ = pedir("POST", f"{externo}/api/config", {"embarcacao_id": EMB, "camera_id": "cam-1",
                                                       "chave": "alvo_kbps", "valor": "800"}, cookie=toks["tecnico"])
        exigir(c == 403, f"tecnico remoto POST /api/config -> 403 (veio {c})")
        c, _ = pedir("POST", f"{externo}/api/cameras", {"id": "tec-r", "rotulo": "tec-r", "fluxo_id": "tec-r"},
                     cookie=toks["tecnico"])
        exigir(c == 401, f"tecnico REMOTO POST /api/cameras -> 401 (veio {c})")

        # ---- 4. tecnico (captura) NA PROPRIA maquina: cadastra (e' o unico usuario do PC de captura)
        c, j = pedir("POST", f"{interno}/api/cameras",
                     {"id": "cam-do-bordo", "rotulo": "Câmera do convés", "fluxo_id": "cam-do-bordo",
                      "embarcacao_id": EMB, "local": "proa", "protocolo": "dshow"},
                     cookie=toks["tecnico"])
        exigir(c == 201, f"tecnico LOCAL POST /api/cameras -> 201 (veio {c}: {j})")
        # ...e continua sem poder configurar qualidade/tempo (isso e' do admin, em terra)
        c, _ = pedir("POST", f"{interno}/api/config", {"embarcacao_id": EMB, "camera_id": "cam-do-bordo",
                                                       "chave": "alvo_kbps", "valor": "800"}, cookie=toks["tecnico"])
        exigir(c == 403, f"tecnico LOCAL POST /api/config -> 403 (veio {c})")

        # ---- 5. operador/admin: configuram e cadastram
        c, j = pedir("POST", f"{externo}/api/config", {"embarcacao_id": EMB, "camera_id": "cam-do-bordo",
                                                       "chave": "alvo_kbps", "valor": "800"},
                     cookie=toks["admin"])
        exigir(c == 201 and j.get("versao") == 1, f"admin POST /api/config alvo -> 201 v1 (veio {c}: {j})")
        c, j = pedir("POST", f"{externo}/api/config", {"embarcacao_id": EMB, "camera_id": "",
                                                       "chave": "teto_s", "valor": "900"}, cookie=toks["operador"])
        exigir(c == 201, f"operador POST /api/config teto -> 201 (veio {c}: {j})")
        c, j = pedir("GET", f"{externo}/api/config?embarcacao_id={EMB}", cookie=toks["admin"])
        exigir(c == 200 and {k["chave"] for k in j.get("chaves", [])} == {"alvo_kbps", "teto_s"},
               f"admin GET /api/config ve' desejo x aplicado (veio {c}: {[k['chave'] for k in j.get('chaves', [])]})")
        # D4 (dono, 25/11/2026: "so' admin"): o operador REMOTO configura a qualidade, mas NAO cadastra
        # camera nova; quem cadastra e' o admin.
        c, j = pedir("POST", f"{externo}/api/cameras", {"id": "cam-remota", "rotulo": "remota",
                                                        "fluxo_id": "cam-remota", "embarcacao_id": EMB},
                     cookie=toks["operador"])
        exigir(c == 401, f"operador REMOTO POST /api/cameras -> 401 (D4: so' admin; veio {c}: {j})")
        c, j = pedir("POST", f"{externo}/api/cameras", {"id": "cam-remota", "rotulo": "remota",
                                                        "fluxo_id": "cam-remota", "embarcacao_id": EMB},
                     cookie=toks["admin"])
        exigir(c == 201, f"admin POST /api/cameras remoto -> 201 (veio {c}: {j})")

        # ---- 6. validacao na borda: o que o produto nao tem, terra recusa
        c, j = pedir("POST", f"{externo}/api/config", {"embarcacao_id": EMB, "camera_id": "cam-do-bordo",
                                                       "chave": "alvo_kbps", "valor": "777"},
                     cookie=toks["admin"])
        exigir(c == 422, f"alvo fora da lista -> 422 (veio {c}: {j.get('erro', '')[:60]})")
        c, j = pedir("POST", f"{externo}/api/config", {"embarcacao_id": EMB, "camera_id": "",
                                                       "chave": "qualquer_coisa", "valor": "1"},
                     cookie=toks["admin"])
        exigir(c == 422, f"chave desconhecida -> 422 (veio {c})")

        # ---- 7. o bordo LE o que terra publicou — e so' ele, com o token dele
        c, _ = pedir("GET", f"{externo}/api/config-desejada?embarcacao_id={EMB}")
        exigir(c == 401, f"GET /api/config-desejada sem token do bordo -> 401 (veio {c})")
        c, j = pedir("GET", f"{externo}/api/config-desejada?embarcacao_id={EMB}", token=TOKEN_BORDO)
        exigir(c == 200 and j.get("versao", 0) >= 1, f"bordo com token LE a config (veio {c}: v{j.get('versao')})")
        c, _ = pedir("GET", f"{externo}/api/config-desejada?embarcacao_id={EMB}", cookie=toks["admin"])
        exigir(c == 401, f"a sessao do admin NAO serve como token do bordo -> 401 (veio {c})")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()

    print()
    if falhas:
        print(f"FALHOU ({len(falhas)}):")
        for f in falhas:
            print("  - " + f)
        return 1
    print("TUDO OK — a matriz de permissoes esta' provada por HTTP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
