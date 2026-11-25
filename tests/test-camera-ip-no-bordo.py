#!/usr/bin/env python3
"""CAMERA IP (RTSP) — cadastro NO PC DE CAPTURA, com o segredo morando so' no bordo.

Dono (25/11/2026, verbatim): *"senha nao pode vazar, entao tem que tudo ficar no bordo, entao nao vamos
poder inserir nem o ip no admin, o cadastro das cameras ip terao que ser no app de captura"*.

O que esta prova mede, com o `ground/api.py` de verdade (servidor numa porta livre, banco novo, o app
DECLARANDO que esta maquina e' a de captura — `LECSOR_CAPTURA_LOCAL=1` + licenca):

  1. a MAQUINA DE CAPTURA (sem login) cadastra a camera de rede: 201 e o cadastro guarda o IP;
  2. o cadastro devolve so' o ESTADO do segredo (configurado: sim/nao) — nunca o valor;
  3. o cadastro RECUSA qualquer campo de senha (`senha`/`segredo`/... -> 422);
  4. com o arquivo de segredo no lugar, `segredo_configurado` vira `True` (lido da MAQUINA);
  5. `GET /api/cameras/<id>/segredo` responde o estado e o CAMINHO do arquivo, e NAO carrega o valor;
  6. `GET /api/cameras/detalhe` diz `entrada: "rede"` e `aponta_para: "<ip>:<porta>/<canal>"`;
  7. editar o endereco pela propria maquina funciona; o mesmo pedido SEM a declaracao e' RECUSADO
     (loopback sozinho nao basta: e' o que mantem o observador remoto de fora, mesmo em 127.0.0.1);
  8. remover o cadastro pela propria maquina funciona.

Uso: python tests/test-camera-ip-no-bordo.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas: list = []
TOKEN = "token-de-teste-do-bordo"
LICENCA = {"chave": "ABCD-EFGH-JKMN-PQRS", "licenca_id": "lic-1", "embarcacao_id": "emb-teste",
           "embarcacao_nome": "Embarcacao de Teste", "cliente_id": "cli-1",
           "cliente_nome": "Empresa de Teste", "validade_tipo": "indeterminada", "validade_em": "",
           "status": "ativa", "motivo": "", "maquina": "pc-teste",
           "ativada_em": "2026-11-25T10:00:00", "conferida_em": "2026-11-25T10:00:00", "origem": "terra"}


def checar(condicao: bool, texto: str) -> None:
    print(("  ok    — " if condicao else "  FALHA — ") + texto)
    if not condicao:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(url: str, dados: dict | None = None, timeout: float = 15):
    """GET/POST sem cookie nenhum (e' assim que a maquina de captura abre o painel: sem login)."""
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"erro": f"{type(e).__name__}: {e}"}


def ambiente(pasta: Path, declarada: bool) -> dict:
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(pasta / "pipeline.db")
    env["LECSOR_GRAVACOES_DIR"] = str(pasta / "gravacoes")
    env["LECSOR_AGENTE_ESTADO"] = str(pasta / "agente-vivo.json")
    env["LECSOR_ORDENS_ESTADO"] = str(pasta / "ligados.json")
    env["LECSOR_LICENCA"] = str(pasta / "licenca.json")
    env["LECSOR_SEM_AMBIENTE"] = "1"
    env["LECSOR_SEGREDOS"] = str(pasta / "segredos")      # os segredos desta maquina (nunca saem daqui)
    env["LECSOR_LADO_TERRA_API"] = "http://127.0.0.1:1"   # ninguem atende: o bordo nao depende disso
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    if declarada:
        env["LECSOR_CAPTURA_LOCAL"] = "1"
    else:
        env.pop("LECSOR_CAPTURA_LOCAL", None)
    env.pop("LECSOR_EMBARCACAO", None)
    env.pop("LECSOR_DESTINO_SRT", None)
    (pasta / "licenca.json").write_text(json.dumps(LICENCA, ensure_ascii=False), encoding="utf-8")
    return env


def semear(banco: Path) -> None:
    con = sqlite3.connect(str(banco))
    try:
        con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('cli-1','Empresa de Teste')")
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado) "
                    "VALUES ('emb-teste','cli-1','Embarcacao de Teste','','em operacao')")
        con.commit()
    finally:
        con.close()


def subir(env: dict):
    porta = porta_livre()
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(40):
        if pedir(base + "/api/saude")[0] == 200:
            return proc, base
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("o servidor do bordo nao subiu para o teste")


def parar(proc) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        proc.kill()


def principal() -> int:
    print("Camera IP — cadastro NO PC DE CAPTURA (o IP e a senha nunca saem do bordo)")
    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)

        # ============================================================= A) a maquina DECLARADA cadastra
        print("\nA) a maquina de captura (sem login) cadastra a camera de rede")
        env = ambiente(pasta, declarada=True)
        proc, base = subir(env)
        try:
            semear(pasta / "pipeline.db")
            c, j = pedir(base + "/api/cameras", {
                "id": "cam-rede-01", "rotulo": "Proa", "fluxo_id": "proa", "entrada": "rede",
                "ip": "10.0.0.7", "porta": "554", "protocolo": "rtsp", "canal": "1"})
            checar(c == 201, f"a maquina de captura cadastra a camera de rede -> 201 (veio {c}: {j})")
            checar((j.get("segredo") or {}).get("configurado") is False,
                   "o cadastro diz que o segredo ainda NAO esta configurado")
            checar(not any(k in j for k in ("senha", "password", "passwd", "pwd")),
                   "a resposta do cadastro NAO tem campo de senha")

            # CREDENCIAL NUNCA ENTRA NO CADASTRO
            c, j2 = pedir(base + "/api/cameras", {
                "id": "cam-rede-99", "rotulo": "x", "fluxo_id": "x", "entrada": "rede",
                "ip": "10.0.0.9", "senha": "supersecreta"})
            checar(c == 422 and "senha" in json.dumps(j2).lower(),
                   f"a senha no corpo do cadastro e' RECUSADA (veio {c})")

            # o detalhe mostra o apontamento (sem credencial) e o estado do segredo
            c, d = pedir(base + "/api/cameras/detalhe")
            cams = {x["id"]: x for x in d.get("cameras", [])}
            cam = cams.get("cam-rede-01") or {}
            checar(cam.get("entrada") == "rede", "detalhe: entrada = 'rede'")
            checar(str(cam.get("aponta_para") or "").startswith("10.0.0.7:554")
                   and "@" not in str(cam.get("aponta_para")),
                   f"detalhe: aponta_para sem credencial começa por '10.0.0.7:554' (veio {cam.get('aponta_para')!r})")
            checar(cam.get("segredo_configurado") is False, "detalhe: segredo_configurado = False")

            # o segredo configurado NA MAQUINA passa a valer (o produto nunca pede senha)
            (pasta / "segredos").mkdir(parents=True, exist_ok=True)
            (pasta / "segredos" / "cam-cam-rede-01.txt").write_text("operador:abacaxi123\n", encoding="utf-8")
            c, s = pedir(base + "/api/cameras/cam-rede-01/segredo")
            checar(c == 200 and s.get("configurado") is True,
                   f"com o arquivo na maquina, segredo_configurado vira True (veio {c}: {s})")
            checar("abacaxi" not in json.dumps(s), "a rota do segredo NAO carrega o valor da senha")
            checar(s.get("arquivo") and s["arquivo"].endswith("cam-cam-rede-01.txt"),
                   "a rota diz ONDE por a senha (o caminho do arquivo), sem o valor")
            c, d2 = pedir(base + "/api/cameras/detalhe")
            cam2 = {x["id"]: x for x in d2.get("cameras", [])}.get("cam-rede-01") or {}
            checar(cam2.get("segredo_configurado") is True,
                   "o detalhe passa a dizer segredo_configurado = True")

            # editar o endereco pela PROPRIA maquina
            c, e = pedir(base + "/api/cameras/cam-rede-01/editar", {"porta": "8554", "canal": "102"})
            checar(c == 200 and "ip" not in (e.get("mudou") or []) and "porta" in (e.get("mudou") or []),
                   f"a propria maquina edita porta/canal (veio {c}: {e.get('mudou')})")

            # remover o cadastro pela PROPRIA maquina
            c, r = pedir(base + "/api/cameras/cam-rede-01/remover", {})
            checar(c == 200 and r.get("ok") is True, f"a propria maquina remove o cadastro (veio {c}: {r})")
        finally:
            parar(proc)

        # ================================================ B) SEM a declaracao, loopback sozinho nao basta
        print("\nB) SEM a declaracao, o loopback sozinho NAO cadastra (o observador remoto fica de fora)")
        pasta_b = pasta / "sem-declaracao"
        pasta_b.mkdir()
        env_b = ambiente(pasta_b, declarada=False)
        proc_b, base_b = subir(env_b)
        try:
            semear(pasta_b / "pipeline.db")
            c, j = pedir(base_b + "/api/cameras", {
                "id": "cam-x", "rotulo": "x", "fluxo_id": "x", "entrada": "rede", "ip": "10.0.0.5"})
            checar(c == 401, f"sem declaracao (e sem sessao) o cadastro e' recusado -> 401 (veio {c}: {j})")
        finally:
            parar(proc_b)

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} prova(s):")
        for f in falhas:
            print("  - " + f)
        return 1
    print("TUDO VERDE — a camera IP e' cadastrada no bordo e o segredo nunca sai de la'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
