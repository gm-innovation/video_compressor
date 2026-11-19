#!/usr/bin/env python3
"""ESCOPOS DE ACESSO DO CLIENTE (plano de 19/11/2026, Fase 1) — provado por HTTP, nao por leitura de codigo.

O dono (19/11/2026): "temos 4 tipos de clientes 1. cliente que pode ver apenas uma embarcacao da empresa
2. cliente que pode ver algumas embarcacoes da empresa 3. cliente que pode ver todas as embarcacoes da
empresa 4. cliente que pode ver todas as embarcacoes de todas as empresas (petrobras)".

  | tipo | quem                        | como o banco diz                                          |
  |------|-----------------------------|-----------------------------------------------------------|
  |  1   | uma embarcacao              | 1 linha em usuario_embarcacoes                            |
  |  2   | algumas embarcacoes         | N linhas em usuario_embarcacoes                           |
  |  3   | todas da empresa            | ZERO linhas + cliente_id da empresa (o que ja' existia)   |
  |  4   | todas as empresas (Petrobras)| papel `observador`, e SO' LEITURA                         |

Aqui se prova: a matriz por HTTP (o que cada um ve e o que cada um NAO pode), a concessao/revogacao pelo
admin com a trilha em auditoria_acesso, a recusa de embarcacao de OUTRA empresa, a migracao do CHECK de
`usuarios` (o papel observador existe no banco) e a tabela `usuario_embarcacoes`.

    python tests/test-escopos-de-acesso.py
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
BANCO = pathlib.Path(tempfile.mkdtemp(prefix="escopos-090-")) / "pipeline.db"

# ids proprios do teste: a API semeia em `armador-demo` (PSV Exemplo/bancada) no boot, e usar o mesmo
# cliente faria o teste confundir o que e' do teste com o que e' da bancada.
EMPRESA_A = "empresa-a-teste"       # 3 embarcacoes
EMPRESA_B = "empresa-b-teste"       # 1 embarcacao
EMB_A1, EMB_A2, EMB_A3 = "emb-a1", "emb-a2", "emb-a3"
EMB_B1 = "emb-b1"


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


def pedir(metodo, url, corpo=None, cookie=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
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


def sobe_api(porta: int):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(BANCO)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT",
              "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
    log = (BANCO.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (BANCO.parent / f"api-{porta}.log").read_text(errors="replace")[-800:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def semear_usuarios_e_mundo() -> dict:
    con = sqlite3.connect(str(BANCO))
    con.row_factory = sqlite3.Row
    for cid, nome in ((EMPRESA_A, "Armador Demo"), (EMPRESA_B, "Outra Empresa")):
        con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (cid, nome))
    for eid, cid, nome in ((EMB_A1, EMPRESA_A, "Embarcacao A1"), (EMB_A2, EMPRESA_A, "Embarcacao A2"),
                           (EMB_A3, EMPRESA_A, "Embarcacao A3"), (EMB_B1, EMPRESA_B, "Embarcacao B1")):
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)", (eid, cid, nome))
    for eid, rot in ((EMB_A1, "cam A1"), (EMB_A2, "cam A2"), (EMB_A3, "cam A3"), (EMB_B1, "cam B1")):
        con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,ativo)
                       VALUES (?,?,?,?,1)""", (f"cam-{eid}", eid, rot, f"fluxo-{eid}"))
    # usuarios: os quatro tipos + um admin
    toks = {}
    for uid, email, papel, cid in (("cli-uma", "uma@armador.test", "cliente", EMPRESA_A),
                                   ("cli-algumas", "algumas@armador.test", "cliente", EMPRESA_A),
                                   ("cli-todas", "todas@armador.test", "cliente", EMPRESA_A),
                                   ("cli-outra", "outra@empresa-b.test", "cliente", EMPRESA_B),
                                   ("observador", "petrobras@petrobras.test", "observador", None),
                                   ("admin", "admin@lecsor.test", "admin", None)):
        salt = os.urandom(16).hex()
        senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
        con.execute("""INSERT OR REPLACE INTO usuarios
                       (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                       VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cid, senha, salt))
        tok = "tok-" + uid
        exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
        con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                    (tok, uid, exp, "teste"))
        toks[uid] = tok
    # tipo 1: uma embarcacao; tipo 2: duas das tres; tipo 3: nenhum vinculo
    for uid, eids in (("cli-uma", [EMB_A1]), ("cli-algumas", [EMB_A1, EMB_A2])):
        for eid in eids:
            con.execute("INSERT OR REPLACE INTO usuario_embarcacoes (usuario_id,embarcacao_id,concedido_por)"
                        " VALUES (?,?,?)", (uid, eid, "admin@lecsor.test"))
    con.commit()
    con.close()
    return toks


def embarcacoes_visiveis(base: str, tok: str) -> set:
    c, j = pedir("GET", f"{base}/api/embarcacoes", cookie=tok)
    if c != 200:
        return set()
    return {x["id"] for x in j.get("embarcacoes", [])}


def cameras_visiveis(base: str, tok: str) -> set:
    c, j = pedir("GET", f"{base}/api/cameras", cookie=tok)
    if c != 200:
        return set()
    return {x["embarcacao_id"] for x in j.get("cameras", [])}


def main() -> int:
    porta = porta_livre()
    proc = sobe_api(porta)
    base = f"http://127.0.0.1:{porta}"
    try:
        time.sleep(1.0)

        # ---- 0. esquema: a tabela do vinculo existe e o CHECK aceita `observador` (migracao aplicada)
        con = sqlite3.connect(str(BANCO))
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        exigir("usuario_embarcacoes" in tabelas, "esquema: tabela usuario_embarcacoes criada")
        sql_usuarios = con.execute("SELECT sql FROM sqlite_master WHERE name='usuarios'").fetchone()[0]
        exigir("observador" in sql_usuarios, "esquema: CHECK de usuarios aceita o papel observador")
        exigir("tecnico" in sql_usuarios, "esquema: a migracao preservou o papel tecnico (CHECK completo)")
        n_antes = con.execute("SELECT count(*) FROM usuarios").fetchone()[0]
        con.close()

        toks = semear_usuarios_e_mundo()
        con = sqlite3.connect(str(BANCO))
        n_depois = con.execute("SELECT count(*) FROM usuarios").fetchone()[0]
        con.close()
        exigir(n_depois == n_antes + 6, f"migracao preservou as linhas: {n_antes} + 6 = {n_depois}")

        # ---- 1. tipo 1: ve APENAS uma embarcacao da empresa
        vis = embarcacoes_visiveis(base, toks["cli-uma"])
        exigir(vis == {EMB_A1}, f"tipo 1 ve exatamente 1 embarcacao ({sorted(vis)})")
        exigir(cameras_visiveis(base, toks["cli-uma"]) == {EMB_A1}, "tipo 1 ve a camera so' da sua embarcacao")

        # ---- 2. tipo 2: ve algumas
        vis = embarcacoes_visiveis(base, toks["cli-algumas"])
        exigir(vis == {EMB_A1, EMB_A2}, f"tipo 2 ve as concedidas ({sorted(vis)})")
        exigir(EMB_A3 not in vis, "tipo 2 NAO ve a embarcacao nao concedida")

        # ---- 3. tipo 3: sem vinculo, todas as da propria empresa (e nada de outra empresa)
        vis = embarcacoes_visiveis(base, toks["cli-todas"])
        exigir(vis == {EMB_A1, EMB_A2, EMB_A3}, f"tipo 3 ve todas as da empresa ({sorted(vis)})")
        exigir(EMB_B1 not in vis, "tipo 3 NAO atravessa empresa")
        # e o outro cliente (empresa B) ve so' a dele
        exigir(embarcacoes_visiveis(base, toks["cli-outra"]) == {EMB_B1}, "cliente da empresa B ve a sua")

        # ---- 4. tipo 4: observador ve TODAS as embarcacoes de TODAS as empresas, e so' leitura
        vis = embarcacoes_visiveis(base, toks["observador"])
        exigir({EMB_A1, EMB_A2, EMB_A3, EMB_B1} <= vis,
               f"tipo 4 ve as duas empresas ({sorted(vis)})")
        c, j = pedir("GET", f"{base}/api/usuarios", cookie=toks["observador"])
        exigir(c == 401, f"observador NAO lista usuarios -> 401 (veio {c})")
        c, _ = pedir("POST", f"{base}/api/config", {"embarcacao_id": EMB_A1, "camera_id": "cam-emb-a1",
                                                   "chave": "alvo_kbps", "valor": "800"},
                     cookie=toks["observador"])
        exigir(c == 403, f"observador NAO publica config do bordo -> 403 (veio {c})")
        c, _ = pedir("POST", f"{base}/api/usuarios/cli-uma/embarcacoes", {"embarcacao_ids": [EMB_A1]},
                     cookie=toks["observador"])
        exigir(c == 401, f"observador NAO concede escopo -> 401 (veio {c})")

        # ---- 5. o admin le e mostra o escopo de cada um
        c, j = pedir("GET", f"{base}/api/usuarios/cli-uma/embarcacoes", cookie=toks["admin"])
        exigir(c == 200 and j.get("vinculos") == 1 and j.get("escopo") == "uma_embarcacao_da_empresa",
               f"admin le o escopo do tipo 1 ({c}: {j.get('escopo')}/{j.get('vinculos')})")
        concedidas = {x["id"]: x["concedida"] for x in j.get("embarcacoes", [])}
        exigir(concedidas.get(EMB_A1) is True and concedidas.get(EMB_A2) is False,
               "admin ve marcado o que foi concedido e o que nao foi")
        c, j = pedir("GET", f"{base}/api/usuarios/cli-todas/embarcacoes", cookie=toks["admin"])
        exigir(c == 200 and j.get("vinculos") == 0 and j.get("escopo") == "todas_as_embarcacoes_da_empresa",
               "tipo 3 aparece como 'todas da empresa' (sem vinculo)")
        c, j = pedir("GET", f"{base}/api/usuarios/observador/embarcacoes", cookie=toks["admin"])
        exigir(c == 200 and j.get("escopo") == "todas_as_empresas",
               "observador aparece como 'todas as empresas' (nao recebe vinculo)")

        # ---- 6. admin CONCEDE (tipo 2 -> 1) e o efeito aparece na hora; trilha gravada
        c, j = pedir("POST", f"{base}/api/usuarios/cli-algumas/embarcacoes", {"embarcacao_ids": [EMB_A1]},
                     cookie=toks["admin"])
        exigir(c == 200 and j.get("ganhos") == [] and j.get("perdidos") == [EMB_A2],
               f"admin revoga uma embarcacao ({c}: perdeu {j.get('perdidos')})")
        exigir(embarcacoes_visiveis(base, toks["cli-algumas"]) == {EMB_A1},
               "a revogacao vale imediatamente (o cliente perde a embarcacao)")
        con = sqlite3.connect(str(BANCO))
        acoes = [r[0] for r in con.execute("SELECT acao FROM auditoria_acesso WHERE acao LIKE 'escopo_%'")]
        con.close()
        exigir("escopo_revogado" in acoes, f"trilha: escopo_revogado gravado ({sorted(set(acoes))})")
        c, j = pedir("POST", f"{base}/api/usuarios/cli-outra/embarcacoes",
                     {"embarcacao_ids": [EMB_B1, EMB_A2]}, cookie=toks["admin"])
        exigir(c == 422 and EMB_A2 in (j.get("fora") or []),
               f"admin NAO consegue conceder embarcacao de outra empresa ({c}: fora={j.get('fora')})")
        c, j = pedir("POST", f"{base}/api/usuarios/cli-algumas/embarcacoes", {"embarcacao_ids": []},
                     cookie=toks["admin"])
        exigir(c == 200 and j.get("vinculos") == 0, f"lista vazia volta ao tipo 3 ({c})")
        exigir(embarcacoes_visiveis(base, toks["cli-algumas"]) == {EMB_A1, EMB_A2, EMB_A3},
               "sem vinculo o cliente volta a ver todas as da empresa")

        # ---- 7. quem concede e' o admin: cliente e operador nao concedem
        c, _ = pedir("POST", f"{base}/api/usuarios/cli-uma/embarcacoes", {"embarcacao_ids": [EMB_A2]},
                     cookie=toks["cli-todas"])
        exigir(c == 401, f"cliente NAO concede escopo para ninguem -> 401 (veio {c})")
        c, _ = pedir("GET", f"{base}/api/usuarios/cli-uma/embarcacoes", cookie=toks["cli-todas"])
        exigir(c == 401, f"cliente NAO le o escopo dos outros -> 401 (veio {c})")
        c, _ = pedir("POST", f"{base}/api/usuarios/cli-uma/embarcacoes", {"embarcacao_ids": [EMB_A2]},
                     cookie=toks["admin"])
        exigir(c == 200, f"admin concede de verdade ({c})")
        exigir(embarcacoes_visiveis(base, toks["cli-uma"]) == {EMB_A2},
               "a concessao vale imediatamente (o cliente passa a ver a nova)")

        # ---- 8. sem login, nada
        c, _ = pedir("GET", f"{base}/api/usuarios/cli-uma/embarcacoes")
        exigir(c == 401, f"sem login nao le escopo -> 401 (veio {c})")
        c, _ = pedir("POST", f"{base}/api/usuarios/cli-uma/embarcacoes", {"embarcacao_ids": [EMB_A1]})
        exigir(c == 401, f"sem login nao concede escopo -> 401 (veio {c})")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s): " + "; ".join(falhas))
        return 1
    print("RESULTADO: tudo passou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
