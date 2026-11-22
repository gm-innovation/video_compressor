#!/usr/bin/env python3
"""PROVA: a licenca de um barco NAO enxerga o outro (plano da 0.10.0, Fase 4 P2).

A licenca diz a que EMBARCACAO aquele PC de captura pertence — e e' isso que decide o que ele pergunta ao
lado terra. Dois barcos da MESMA empresa ficam no mesmo banco: se o recorte fosse frouxo, o PC do barco A
poderia acabar perguntando (e ligando) camera do barco B.

O que se prova aqui, com dois barcos da mesma empresa cadastrados:
  1. a licenca do barco A deixa o PC de captura com a embarcacao A;
  2. o PC de captura pergunta ao lado terra SO' pela embarcacao da licenca (trecho estatico do agente);
  3. `GET /api/estado-desejado` do barco A devolve a camera de A e NUNCA a de B (e vice-versa).

    python tests/test-licenca-isola-embarcacao.py
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
PASTA = pathlib.Path(tempfile.mkdtemp(prefix="licenca-isola-"))
BANCO_TERRA, BANCO_BORDO = PASTA / "terra" / "pipeline.db", PASTA / "bordo" / "pipeline.db"
ARQ_LICENCA = PASTA / "bordo" / "licenca.json"
TOKEN = "token-de-ingestao-da-prova"
EMPRESA = "armador-isola"
A, B = "barco-a", "barco-b"
CAMA, CAMB = "cam-do-a", "cam-do-b"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(metodo, url, corpo=None, cookie="", token="", texto=False):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token:
        cab["Authorization"] = f"Bearer {token}"   # o mesmo cabecalho que o agente do bordo usa
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            return f.status, (b.decode("utf-8", "replace") if texto else (json.loads(b) if b else {}))
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, (b.decode("utf-8", "replace") if texto else (json.loads(b or b"{}") if b else {}))


def sobe(porta: int, banco: pathlib.Path, extra: dict, nome: str):
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_LICENCA", "LECSOR_EMBARCACAO"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_TOKEN_INGESTAO": TOKEN, "LECSOR_SENHA_DEMO": "senha-de-bancada-nao-usada",
                "PYTHONIOENCODING": "utf-8", **extra})
    banco.parent.mkdir(parents=True, exist_ok=True)
    log = (PASTA / f"{nome}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError(f"{nome} saiu: " + (PASTA / f"{nome}.log").read_text(errors="replace")[-800:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError(f"{nome} nao subiu")


def semear(banco: pathlib.Path, com_admin: bool) -> str:
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Armador Isola"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)", (A, EMPRESA, "Barco A"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)", (B, EMPRESA, "Barco B"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,ativo)
                   VALUES (?,?,?,?,1)""", (CAMA, A, "camera do barco A", "fluxo-a"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,ativo)
                   VALUES (?,?,?,?,1)""", (CAMB, B, "camera do barco B", "fluxo-b"))
    tok = ""
    if com_admin:
        salt = os.urandom(16).hex()
        senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
        con.execute("""INSERT OR REPLACE INTO usuarios
                       (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                       VALUES ('admin','admin@isola.test','admin','admin',NULL,?,?,200000,1)""", (senha, salt))
        exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
        con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                    ("tok-admin", "admin", exp, "teste"))
        tok = "tok-admin"
    con.commit()
    con.close()
    return tok


def main() -> int:
    p_terra, p_bordo = porta_livre(), porta_livre()
    base_terra, base_bordo = f"http://127.0.0.1:{p_terra}", f"http://127.0.0.1:{p_bordo}"
    terra = sobe(p_terra, BANCO_TERRA, {}, "terra")
    toks = semear(BANCO_TERRA, com_admin=True)
    bordo = None
    try:
        c, criada = pedir("POST", f"{base_terra}/api/licencas",
                          {"embarcacao_id": A, "validade_tipo": "indeterminada", "maquinas_max": 1},
                          cookie=toks)
        chave = criada.get("chave") or ""
        exigir(c == 201 and bool(chave), f"o admin gerou a licenca do barco A -> {c}")

        bordo = sobe(p_bordo, BANCO_BORDO, {"LECSOR_LADO_TERRA_API": base_terra,
                                           "LECSOR_LICENCA": str(ARQ_LICENCA)}, "bordo")
        semear(BANCO_BORDO, com_admin=False)
        c, j = pedir("POST", f"{base_bordo}/api/licenca/ativar", {"chave": chave})
        exigir(c == 200 and (json.loads(ARQ_LICENCA.read_text(encoding="utf-8"))["embarcacao_id"] == A),
               f"o PC de captura ativou com a licenca e virou o BARCO A -> {c}")

        print("\n== o PC de captura pergunta SO' pela embarcacao da licenca ==")
        fonte = (RAIZ / "ground" / "agente_de_ordens.py").read_text(encoding="utf-8")
        exigir("emb = licenca.embarcacao()" in fonte,
               "o agente tira a embarcacao da LICENCA (nao do ambiente do pacote)")
        exigir("/api/estado-desejado?embarcacao_id={emb}" in fonte,
               "e pergunta ao lado terra por ESSA embarcacao, e por nenhuma outra")

        print("\n== o desejo de um barco nao traz a camera do outro ==")
        c, da_a = pedir("GET", f"{base_terra}/api/estado-desejado?embarcacao_id={A}", token=TOKEN)
        ids_a = json.dumps(da_a, ensure_ascii=False)
        exigir(c == 200 and CAMA in ids_a and CAMB not in ids_a,
               f"o desejo do BARCO A traz a camera de A e nenhuma de B -> {c}")
        c, da_b = pedir("GET", f"{base_terra}/api/estado-desejado?embarcacao_id={B}", token=TOKEN)
        ids_b = json.dumps(da_b, ensure_ascii=False)
        exigir(c == 200 and CAMB in ids_b and CAMA not in ids_b,
               f"o desejo do BARCO B traz a camera de B e nenhuma de A -> {c}")
        exigir(CAMB not in json.dumps(da_a, ensure_ascii=False),
               "nenhum caminho faz o PC do barco A receber camera do barco B")
    finally:
        for p in (terra, bordo):
            if p is None:
                continue
            p.terminate()
            try:
                p.wait(timeout=10)
            except Exception:  # noqa: BLE001
                p.kill()

    if falhas:
        print(f"\nRESULTADO: {len(falhas)} falha(s):")
        for f in falhas:
            print("  - " + f)
        return 1
    print("\nRESULTADO: tudo passou — a licenca recorta o barco: A so' enxerga A, B so' enxerga B.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
