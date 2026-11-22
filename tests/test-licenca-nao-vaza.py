#!/usr/bin/env python3
"""PROVA: a chave de licenca NAO vaza (dono, 19/11/2026 — plano, Fase 4 P1).

A chave e' uma credencial: quem a tem vira aquele barco. O dono decidiu (`clarify`, 19/11/2026) que o
admin **ve e copia a chave inteira sempre** — entao existem exatamente DOIS lugares onde ela pode estar:
  * o banco do lado terra (para o admin copiar de novo), e
  * o arquivo de vinculo do PC de captura (e' o que prova que a maquina e' daquele barco).

Em todo o resto ela NAO pode aparecer: log da API de qualquer um dos lados, trilha de auditoria
(`auditoria_acesso`, que guarda so' a PEGADA = sha256 curto), respostas de rota que nao sejam do admin.
Esta prova roda uma rodada real (gerar → ativar → revogar → reemitir → ativar de novo) e depois VARRRE
os arquivos que a rodada escreveu, dizendo onde a chave esta' e onde NAO esta'.

    python tests/test-licenca-nao-vaza.py
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
PASTA = pathlib.Path(tempfile.mkdtemp(prefix="licenca-vaza-"))
BANCO_TERRA, BANCO_BORDO = PASTA / "terra" / "pipeline.db", PASTA / "bordo" / "pipeline.db"
ARQ_LICENCA = PASTA / "bordo" / "licenca.json"
EMPRESA, EMB = "armador-teste", "emb-teste"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


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
        return e.code, json.loads(e.read() or b"{}")


def sobe(porta: int, banco: pathlib.Path, extra: dict, nome: str):
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_LICENCA", "LECSOR_EMBARCACAO"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_TOKEN_INGESTAO": "tok", "LECSOR_SENHA_DEMO": "senha-de-bancada-nao-usada",
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


def semear_terra() -> str:
    con = sqlite3.connect(str(BANCO_TERRA))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Armador Teste"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "Embarcacao Teste"))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios
                   (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES ('admin','admin@licenca.test','admin','admin',NULL,?,?,200000,1)""", (senha, salt))
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                ("tok-admin", "admin", exp, "teste"))
    con.commit()
    con.close()
    return "tok-admin"


def valor(banco: pathlib.Path, sql: str, *args):
    con = sqlite3.connect(str(banco))
    try:
        r = con.execute(sql, args).fetchone()
        return r[0] if r else None
    finally:
        con.close()


def linhas(banco: pathlib.Path, sql: str) -> list[tuple]:
    con = sqlite3.connect(str(banco))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def varrer(pasta: pathlib.Path, chave: str) -> list[str]:
    """Alvos (arquivo) que contem o valor da chave, varrendo TUDO o que a rodada escreveu."""
    achados = []
    for arquivo in sorted(pasta.rglob("*")):
        if not arquivo.is_file():
            continue
        try:
            dados = arquivo.read_bytes().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        if chave in dados or chave.replace("-", "") in dados.replace("-", ""):
            achados.append(arquivo.relative_to(pasta).as_posix())   # sempre com "/" (Windows e Linux)
    return achados


def main() -> int:
    p_terra, p_bordo = porta_livre(), porta_livre()
    base_terra, base_bordo = f"http://127.0.0.1:{p_terra}", f"http://127.0.0.1:{p_bordo}"
    terra = sobe(p_terra, BANCO_TERRA, {}, "terra")
    toks = semear_terra()
    bordo = sobe(p_bordo, BANCO_BORDO,
                 {"LECSOR_LADO_TERRA_API": base_terra, "LECSOR_LICENCA": str(ARQ_LICENCA)}, "bordo")
    try:
        c, criada = pedir("POST", f"{base_terra}/api/licencas",
                          {"embarcacao_id": EMB, "validade_tipo": "indeterminada", "maquinas_max": 1},
                          cookie=toks)
        chave = str(criada.get("chave") or "")
        pegada = hashlib.sha256(chave.replace("-", "").encode()).hexdigest()[:16]
        exigir(c == 201 and bool(chave), f"licenca gerada para a rodada -> {c}")
        pedir("POST", f"{base_bordo}/api/licenca/ativar", {"chave": chave, "maquina": "pc-da-prova"})
        pedir("POST", f"{base_terra}/api/licencas/{criada['id']}/revogar", {"motivo": "fim de contrato"},
              cookie=toks)
        pedir("GET", f"{base_bordo}/api/licenca")
        c, novo = pedir("POST", f"{base_terra}/api/licencas/{criada['id']}/reemitir", {}, cookie=toks)
        nova = str(novo.get("chave") or "")
        pedir("POST", f"{base_bordo}/api/licenca/ativar", {"chave": nova, "maquina": "pc-da-prova"})
        exigir(bool(nova) and nova != chave, "a rodada cobriu gerar, ativar, revogar, reemitir e ativar")

        print("\n== onde a chave PODE estar (por decisao do dono) ==")
        na_terra = valor(BANCO_TERRA, "SELECT chave FROM licencas WHERE id=?", criada["id"])
        exigir(na_terra == nova, "o banco do lado terra guarda a chave vigente (o admin copia de novo)")
        guardado = json.loads(ARQ_LICENCA.read_text(encoding="utf-8")) if ARQ_LICENCA.exists() else {}
        exigir(guardado.get("chave") == nova, "o vinculo do PC de captura guarda a chave vigente")
        exigir(guardado.get("embarcacao_id") == EMB, "e traz a embarcacao (o vinculo que a chave faz)")

        print("\n== onde ela NAO pode estar ==")
        logs = varrer(PASTA, chave) + varrer(PASTA, nova)
        # O proprio banco (e os arquivos `-wal`/`-shm` que o SQLite escreve ao lado) e o vinculo do PC
        # sao os dois lugares que o dono autorizou; o resto e' vazamento.
        permitidos = ("bordo/licenca.json", "bordo/pipeline.db", "terra/pipeline.db")
        indevidos = sorted(x for x in set(logs) if not x.startswith(permitidos))
        exigir(not indevidos, f"nenhum arquivo inesperado contem a chave (achados: {indevidos})")
        exigir("terra.log" not in logs and "bordo.log" not in logs,
               f"o log das duas APIs esta' limpo (achados: {sorted(set(logs))})")
        for banco, nome in ((BANCO_TERRA, "lado terra"), (BANCO_BORDO, "lado bordo")):
            trilha = json.dumps(linhas(banco, "SELECT acao, alvo FROM auditoria_acesso"), ensure_ascii=False)
            exigir(chave not in trilha and nova not in trilha,
                   f"a auditoria do {nome} nao guarda a chave")
            exigir(pegada in trilha or any(a.startswith("licenca") for a, _ in
                                           linhas(banco, "SELECT acao, alvo FROM auditoria_acesso")),
                   f"a auditoria do {nome} registra o evento da licenca (com a pegada, sem a chave)")

        print("\n== a chave antiga (reemitida) some de vez ==")
        exigir(valor(BANCO_TERRA, "SELECT COUNT(*) FROM licencas WHERE chave=?", chave) == 0,
               "a chave antiga nao existe mais no banco")
        exigir(chave not in json.dumps(linhas(BANCO_TERRA, "SELECT acao, alvo FROM auditoria_acesso")),
               "nem na auditoria — so' a pegada dela ficou")
    finally:
        for p in (terra, bordo):
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
    print("\nRESULTADO: tudo passou — a chave vive so' onde o dono mandou (banco do terra e vinculo do PC)"
          " e nao aparece em log nem na auditoria de nenhum dos lados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
