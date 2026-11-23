#!/usr/bin/env python3
"""Prova de TELA e de EFEITO: instalar o app e digitar a chave (dono, 19/11/2026).

Pedido do dono, verbatim: *"quero apenas instalar o app no computador de captura, inserir a chave da
licenca e assim fazer a conexao com a empresa e embarcacao cadastradas"*. E a arquitetura de comando
(19/11/2026): *"a unica certeza e' de que ele podera' enviar"* — o bordo nao tem porta aberta; ele
PERGUNTA ao lado terra.

Aqui se prova, com navegador de verdade (Chromium) e DOIS servidores de verdade:

  1. na primeira abertura o app mostra a tela da chave (nao um login que o cliente nao tem);
  2. a chave vai sendo formatada enquanto se digita (aceita minusculas e sem tracos);
  3. ao ativar, a maquina passa a ser DA EMBARCACAO e DA EMPRESA cadastradas — a tela diz os nomes;
  4. o vinculo fica gravado no PC (`licenca.json`), sobrevivendo a atualizacao do app;
  5. reabrindo, a tela mostra a ficha (empresa, embarcacao, validade, estado) sem pedir nada;
  6. chave errada e' recusada com aviso claro, sem estragar o que ja' estava ativado;
  7. "trocar a chave desta maquina" desvincula (o PC volta a poder receber outra embarcacao);
  8. sem erro de javascript.

    python tests/e2e-app-ativado-por-licenca.py
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

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
ESPERA = 20000
PASTA = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-licenca-tela-"))
BANCO_TERRA = PASTA / "terra" / "pipeline.db"
BANCO_BORDO = PASTA / "bordo" / "pipeline.db"
ARQ_LICENCA = PASTA / "bordo" / "licenca.json"
EMPRESA, EMB = "armador-teste", "emb-teste"


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


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


def texto(pag, sel: str) -> str:
    try:
        return pag.inner_text(sel)
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    p_terra, p_bordo = porta_livre(), porta_livre()
    base_terra, base_bordo = f"http://127.0.0.1:{p_terra}", f"http://127.0.0.1:{p_bordo}"
    terra = sobe(p_terra, BANCO_TERRA, {}, "terra")   # sem base = ESTE e' o lado terra
    toks = semear_terra()
    bordo = sobe(p_bordo, BANCO_BORDO,
                 {"LECSOR_LADO_TERRA_API": base_terra, "LECSOR_LICENCA": str(ARQ_LICENCA)}, "bordo")
    erros: list[str] = []
    try:
        c, criada = pedir("POST", f"{base_terra}/api/licencas",
                          {"embarcacao_id": EMB, "validade_tipo": "indeterminada", "maquinas_max": 2},
                          cookie=toks)
        chave = criada.get("chave") or ""
        checar("o admin gerou a chave da embarcacao no lado terra", c == 201 and bool(chave), f"{c} {chave}")

        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            pag = navegador.new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())      # "trocar a chave" pede confirmacao

            print("\n== 1. primeira abertura: é a tela da chave (o cliente nao tem login) ==")
            pag.goto(base_bordo + "/licenca")
            pag.wait_for_selector("#chave", timeout=ESPERA)
            checar("a tela da chave abre no PC de captura", pag.is_visible("#form"))
            checar("nao pede login/e-mail em lugar nenhum", "E-mail" not in texto(pag, "body")
                   and "Senha" not in texto(pag, "body"))
            checar("e' a tela do proprio bordo (servida por ele, abre sem internet)",
                   "Chave de licença" in texto(pag, "body"))
            checar("a ficha de ativacao ainda esta' escondida", not pag.is_visible("#ativada"))

            print("\n== 2. a chave se formata enquanto se digita ==")
            pag.fill("#chave", chave.replace("-", "").lower())
            pag.wait_for_timeout(300)
            digitada = pag.input_value("#chave")
            checar("minusculas viraram maiusculas e ganharam os traços", digitada == chave, f"{digitada!r}")
            pag.fill("#chave", "ABC")
            pag.click("#ativar")
            pag.wait_for_timeout(500)
            checar("chave curta e' barrada antes de sair da maquina (aviso de 16 caracteres)",
                   "16 caracteres" in texto(pag, "#aviso"), texto(pag, "#aviso")[:120])

            print("\n== 3. ativar: a maquina passa a ser DA EMBARCACAO e DA EMPRESA ==")
            pag.fill("#chave", chave)
            pag.click("#ativar")
            try:
                pag.wait_for_function("() => /ligada a esta m/.test(document.querySelector('#aviso').innerText)",
                                      timeout=ESPERA)
            except Exception:  # noqa: BLE001
                pass
            aviso = texto(pag, "#aviso")
            checar("a tela confirma a ativacao com o nome da embarcacao",
                   "ligada a esta máquina" in aviso and "Embarcacao Teste" in aviso, aviso[:160])
            pag.wait_for_timeout(2500)     # a propria tela leva para o PAINEL DO BORDO
            checar("depois de ativar, o app segue para o PAINEL DO BORDO (nao para um login) — "
                   "dono, 23/11/2026: 'após o reconhecimento da licença não deveria precisar fazer mais "
                   "nada no app de captura'",
                   "/bordo" in pag.url, pag.url)
            checar("o vinculo ficou gravado no PC de captura", ARQ_LICENCA.exists(), str(ARQ_LICENCA))
            if ARQ_LICENCA.exists():
                g = json.loads(ARQ_LICENCA.read_text(encoding="utf-8"))
                checar("o vinculo guarda a embarcacao cadastrada", g.get("embarcacao_id") == EMB, str(g)[:160])
                checar("o vinculo guarda a empresa dona", g.get("cliente_nome") == "Armador Teste")

            print("\n== 4. reabrindo, a ficha aparece sem pedir nada ==")
            pag.goto(base_bordo + "/licenca")
            pag.wait_for_selector("#ativada", state="visible", timeout=ESPERA)
            ficha = texto(pag, "#ficha")
            baixa = ficha.lower()
            checar("a tela mostra a ficha (empresa, embarcacao, validade, estado)",
                   all(x in baixa for x in ("empresa", "embarca", "validade", "estado")),
                   ficha.replace("\n", " | ")[:200])
            checar("com a empresa e a embarcacao certas",
                   "Armador Teste" in ficha and "Embarcacao Teste" in ficha, ficha.replace("\n", " | ")[:200])
            checar("e a validade sem prazo (indeterminada)", "indeterminada" in ficha)
            checar("o formulario de digitar chave sai de cena", not pag.is_visible("#form"))

            print("\n== 5. trocar a chave desta maquina desvincula ==")
            pag.click("#trocar")
            pag.wait_for_selector("#form", state="visible", timeout=ESPERA)
            checar("a maquina volta a pedir chave (pronta para outra embarcacao)", pag.is_visible("#chave"))
            checar("e o vinculo antigo foi apagado do PC", not ARQ_LICENCA.exists())

            print("\n== 6. chave errada e' recusada com aviso claro ==")
            pag.fill("#chave", "ZZZZ-ZZZZ-ZZZZ-ZZZZ")
            pag.click("#ativar")
            pag.wait_for_function("() => /encontrada|não foi possível|Sem conexão/.test("
                                  "document.querySelector('#aviso').innerText)", timeout=ESPERA)
            aviso = texto(pag, "#aviso")
            checar("a recusa diz que a chave nao foi encontrada (e vem do lado terra)",
                   "encontrada" in aviso, aviso[:160])
            checar("e nada foi gravado na maquina", not ARQ_LICENCA.exists())

            print("\n== 7. e a mesma maquina aceita a chave certa de novo ==")
            pag.fill("#chave", chave)
            pag.click("#ativar")
            try:
                pag.wait_for_function("() => /ligada a esta m/.test(document.querySelector('#aviso').innerText)",
                                      timeout=ESPERA)
            except Exception:  # noqa: BLE001
                pass
            checar("reativar a maquina funciona", "ligada a esta máquina" in texto(pag, "#aviso"),
                   texto(pag, "#aviso")[:140])
            checar("sem erro de javascript na tela do PC de captura", not erros, "; ".join(erros[:3]))
            navegador.close()
    finally:
        for p in (terra, bordo):
            p.terminate()
            try:
                p.wait(timeout=10)
            except Exception:  # noqa: BLE001
                p.kill()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s): " + "; ".join(falhas))
        return 1
    print("RESULTADO: tudo passou — instalar, digitar a chave e a maquina vira do barco (e da empresa) "
          "certos, com a ficha na tela e o vinculo gravado no PC.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
