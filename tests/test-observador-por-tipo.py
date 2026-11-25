#!/usr/bin/env python3
"""O OBSERVADOR FILTRA POR TIPO, NAO POR NOME (0.19.0, Fase 4) — provado por HTTP.

O dono (25/11/2026, verbatim): "petrobras ou ibama pode acessar todas as embarcacoes de todas as
empresas, mas apenas do radar de oleo e camera flir se tiver". E antes: "tem muita redundancia, telas
inuteis ou que nao funcionam".

O que se prova aqui, sem navegador (a defesa esta' no SERVIDOR):

  1) uma camera cujo NOME nao tem "radar" mas cujo TIPO e' 'radar' APARECE para o observador
     (o criterio e' o tipo, nao o nome);
  2) uma camera cujo NOME tem "radar" mas cujo TIPO e' 'camera' NAO aparece
     (o nome deixou de decidir);
  3) a camera 'flir' aparece (o dono pediu a FLIR);
  4) a camera comum ('camera') nao aparece;
  5) a MIGRACAO: um banco ANTIGO (sem a coluna `tipo`) ganha a coluna ao subir e o backfill pelo
     nome de hoje marca o radar como 'radar' — sem passo manual no cliente.

    python tests/test-observador-por-tipo.py
"""
from __future__ import annotations

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
SENHA = "senha-do-observador-de-teste"
EMPRESA_A, EMPRESA_B = "empresa-a-tipo", "empresa-b-tipo"
EMB_A, EMB_B = "emb-a-tipo", "emb-b-tipo"
# ids das cameras do teste (nomes ESCOLHIDOS para o nome NAO decidir o tipo):
TIPO_RADAR_SEM_NOME = "equip-ocm-01"      # tipo='radar', nome SEM "radar"  -> deve aparecer
TIPO_CAMERA_COM_NOME = "radar-anta-99"    # tipo='camera', nome COM "radar" -> NAO deve aparecer
TIPO_FLIR = "sens-iv-01"                  # tipo='flir', nome SEM "flir"   -> deve aparecer
TIPO_COMUM = "cam-proa-01"                # tipo='camera'                  -> NAO deve aparecer


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str, cliente_id=None) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    """Duas empresas; quatro cameras que juntas provam que o TIPO decide, nao o nome."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA_A, "Empresa A (tipo)"))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA_B, "Empresa B (tipo)"))
    for eid, cid, nome in ((EMB_A, EMPRESA_A, "Embarcacao A"), (EMB_B, EMPRESA_B, "Embarcacao B")):
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado,radar_fonte)"
                    " VALUES (?,?,?,?,?,?)", (eid, cid, nome, "", "em operacao", "dshow:EZCAP"))
    linhas = (
        (TIPO_RADAR_SEM_NOME, EMB_A, "Equipamento OCM", "radar"),   # radar pelo TIPO
        (TIPO_CAMERA_COM_NOME, EMB_A, "Radar de antena (antigo)", "camera"),  # "radar" no NOME, tipo camera
        (TIPO_FLIR, EMB_B, "Sensor IV", "flir"),                    # FLIR pelo TIPO
        (TIPO_COMUM, EMB_B, "Camera de proa", "camera"),            # camera comum
    )
    for cid, eid, rotulo, tipo in linhas:
        con.execute("""INSERT OR REPLACE INTO cameras
                       (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                       VALUES (?,?,?,?,'',1,'','','dshow','','',?)""", (cid, eid, rotulo, cid, tipo))
    con.commit()
    con.close()


def preparar_banco_antigo(caminho: pathlib.Path) -> None:
    """Um banco ANTIGO: a tabela `cameras` SEM a coluna `tipo`, com um radar que so' o NOME identifica."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(caminho))
    con.execute("""CREATE TABLE cameras (
                     id TEXT PRIMARY KEY, embarcacao_id TEXT, rotulo TEXT, fluxo_id TEXT,
                     local TEXT, ativo INTEGER, ip TEXT, porta TEXT, protocolo TEXT, canal TEXT,
                     alvo TEXT)""")
    con.execute("INSERT INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)"
                " VALUES ('radar-legado','emb-legado','Radar de oleo (legado)','radar-legado','',1,'','','dshow','','')")
    con.commit()
    con.close()


def subir(banco: pathlib.Path, tmp: pathlib.Path):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_SENHA_DEMO"] = "senha-de-bancada-nao-usada"
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
    porta = porta_livre()
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(80):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                return api, base, tmp / "api.log"
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    api.kill()
    raise RuntimeError("a API nao subiu; log em %s" % (tmp / "api.log"))


def entrar(base: str, email: str) -> str:
    req = urllib.request.Request(base + "/api/entrar", method="POST",
                                 data=json.dumps({"email": email, "senha": SENHA}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return (r.headers.get("Set-Cookie") or "").split(";")[0]


def pedir(base: str, rota: str, cookie: str):
    rq = urllib.request.Request(base + rota, headers={"Cookie": cookie})
    try:
        with urllib.request.urlopen(rq, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")


def testar_tipo_decide() -> None:
    print("== a coluna `tipo` decide o que o observador ve' ==")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-obs-tipo-"))
    banco = tmp / "pipeline.db"
    api, base, log = subir(banco, tmp)
    try:
        criar_usuario(banco, "petrobras", "petrobras@petrobras.test", "observador")
        criar_usuario(banco, "admin", "admin@lecsor.test", "admin")
        semear(banco)
        cookie = entrar(base, "petrobras@petrobras.test")

        s, j = pedir(base, "/api/cameras", cookie)
        ids = {c["id"] for c in (j.get("cameras") or [])}
        checar("radar pelo TIPO (nome sem 'radar') aparece", TIPO_RADAR_SEM_NOME in ids, f"veio {sorted(ids)}")
        checar("FLIR (tipo 'flir') aparece", TIPO_FLIR in ids, f"veio {sorted(ids)}")
        checar("camera com 'radar' no NOME mas tipo 'camera' NAO aparece",
               TIPO_CAMERA_COM_NOME not in ids, f"veio {sorted(ids)}")
        checar("camera comum NAO aparece", TIPO_COMUM not in ids, f"veio {sorted(ids)}")

        por_id = {c["id"]: c for c in (j.get("cameras") or [])}
        checar("a resposta diz o tipo de cada camera",
               por_id.get(TIPO_RADAR_SEM_NOME, {}).get("tipo") == "radar"
               and por_id.get(TIPO_FLIR, {}).get("tipo") == "flir",
               json.dumps({k: v.get("tipo") for k, v in por_id.items()}))

        # o observador continua vendo as DUAS empresas (tipo 4 do dono)
        s, j = pedir(base, "/api/embarcacoes", cookie)
        checar("o observador ve' as embarcacoes das duas empresas",
               {EMB_A, EMB_B} <= {e["id"] for e in (j.get("embarcacoes") or [])})
    finally:
        api.kill()
        print(f"   (log: {log})")


def testar_migracao() -> None:
    print("== migracao: banco antigo ganha `tipo` e o backfill marca o radar pelo nome de hoje ==")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-obs-migra-"))
    banco = tmp / "pipeline.db"
    preparar_banco_antigo(banco)
    api, base, log = subir(banco, tmp)
    try:
        con = sqlite3.connect(str(banco))
        colunas = {linha[1] for linha in con.execute("PRAGMA table_info(cameras)")}
        checar("a coluna `tipo` foi criada no banco antigo", "tipo" in colunas, f"colunas={sorted(colunas)}")
        linha = con.execute("SELECT tipo FROM cameras WHERE id='radar-legado'").fetchone()
        con.close()
        checar("o radar antigo foi marcado como 'radar' pelo backfill",
               bool(linha) and linha[0] == "radar", f"tipo={linha[0] if linha else None}")
    finally:
        api.kill()
        print(f"   (log: {log})")


def main() -> int:
    print("OBSERVADOR POR TIPO — 0.19.0 (Fase 4): radar de oleo e FLIR, por TIPO e nao por nome.\n")
    testar_tipo_decide()
    print()
    testar_migracao()
    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} verificacao(oes) — {falhas}")
        return 1
    print("TUDO VERDE: o observador filtra por tipo (radar/FLIR) e a migracao corre sozinha.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
