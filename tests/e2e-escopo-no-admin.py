#!/usr/bin/env python3
"""Prova de TELA e de EFEITO (plano de 19/11/2026, Fase 1 — escopo de acesso do cliente).

O dono (19/11/2026): "temos 4 tipos de clientes..." — e "quem cadastra os usuarios e' o admin". Aqui se
prova, com navegador de verdade (Chromium do Playwright) e API de verdade, que o ADMIN:

  1) abre Usuarios, clica "escopo de acesso" de um cliente e ve as embarcacoes da empresa dele com o que
     ja' esta concedido marcado;
  2) marca UMA embarcacao e salva -> o vinculo fica no banco (`usuario_embarcacoes`);
  3) desmarca tudo e salva -> volta ao tipo 3 (todas as da empresa, sem vinculo);
  4) o papel `observador` aparece na tela como "ve todas as empresas, so' leitura" (sem vinculo);
  5) sem erro de javascript na tela do admin.

    python tests/e2e-escopo-no-admin.py
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
import urllib.request

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = "senha-do-admin-de-teste"
ESPERA = 20000
EMPRESA = "empresa-do-teste"
EMB1, EMB2 = "emb-t1", "emb-t2"


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


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str, cliente_id=None) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    con.commit()
    con.close()


def entrar(pag, base: str, email: str, espera: str) -> None:
    pag.goto(base + "/entrada/")
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector(espera, timeout=ESPERA)
    pag.wait_for_load_state("networkidle")


def visivel(pag, sel: str) -> bool:
    try:
        return pag.is_visible(sel, timeout=2500)
    except Exception:  # noqa: BLE001
        return False


def vinculos(banco: pathlib.Path, uid: str) -> set:
    con = sqlite3.connect(str(banco))
    try:
        return {r[0] for r in con.execute("SELECT embarcacao_id FROM usuario_embarcacoes WHERE usuario_id=?",
                                          (uid,))}
    finally:
        con.close()


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-escopo-"))
    banco = tmp / "pipeline.db"
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
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=3):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("a API nao subiu")

        criar_usuario(banco, "admin", "admin@lecsor.test", "admin")
        criar_usuario(banco, "cliente-t", "cliente@empresa-teste.test", "cliente", EMPRESA)
        criar_usuario(banco, "observador", "petrobras@petrobras.test", "observador")
        con = sqlite3.connect(str(banco))
        con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Empresa do teste"))
        for eid, nome in ((EMB1, "Embarcação Um"), (EMB2, "Embarcação Dois")):
            con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado) VALUES (?,?,?,?,?)",
                        (eid, EMPRESA, nome, "", "em operacao"))
        con.commit()
        con.close()

        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            pag = navegador.new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))

            entrar(pag, base, "admin@lecsor.test", "button[data-tela=usuarios]")
            pag.click("button[data-tela=usuarios]")
            pag.wait_for_selector("text=escopo de acesso", timeout=ESPERA)

            # ---- 1. o painel abre com as embarcacoes da empresa e nada marcado (tipo 3)
            linhas = pag.locator("tr", has_text="cliente@empresa-teste.test")
            linhas.first.locator("button", has_text="escopo de acesso").click()
            pag.wait_for_selector("#escopo-de-acesso input[type=checkbox]", timeout=ESPERA)
            caixas = pag.locator("#escopo-de-acesso input[type=checkbox]")
            checar("o painel do escopo abre com as embarcacoes da empresa do cliente", caixas.count() == 2,
                   f"{caixas.count()} caixa(s)")
            checar("nada vem marcado antes de conceder (tipo 3)", not any(caixas.nth(i).is_checked() for i in range(caixas.count())))
            pag.wait_for_selector("#escopo-de-acesso", timeout=ESPERA)
            checar("a tela diz o que significa nenhuma marcada",
                   "TODAS as embarca" in pag.inner_text("#escopo-de-acesso"))

            # ---- 2. marca UMA e salva -> vinculo no banco (tipo 1). A ordem vem por NOME
            # ("Embarcação Dois" antes de "Embarcação Um"), entao o id marcado e' LIDO da tela, nao suposto.
            caixas.first.check()
            marcada = caixas.first.get_attribute("data-emb")
            checar("a caixa marcada diz qual embarcacao e'", marcada in (EMB1, EMB2), str(marcada))
            pag.click("#escopo-de-acesso button:has-text('Salvar escopo')")
            pag.wait_for_function("() => /escopo salvo/.test(document.body.innerText)", timeout=ESPERA)
            checar("salvar confirma na tela", "escopo salvo" in pag.inner_text("body"))
            checar("o vinculo da embarcacao marcada esta no banco", vinculos(banco, "cliente-t") == {marcada},
                   f"banco={sorted(vinculos(banco, 'cliente-t'))} tela={marcada}")

            # ---- 3. desmarca tudo e salva -> volta ao tipo 3 (sem vinculo)
            pag.click("button[data-tela=usuarios]")
            pag.wait_for_selector("text=escopo de acesso", timeout=ESPERA)
            pag.locator("tr", has_text="cliente@empresa-teste.test").first.locator(
                "button", has_text="escopo de acesso").click()
            pag.wait_for_selector("#escopo-de-acesso input[type=checkbox]", timeout=ESPERA)
            marcadas = pag.locator("#escopo-de-acesso input[type=checkbox]:checked")
            checar("o painel reabre com o que foi concedido MARCADO", marcadas.count() == 1, f"{marcadas.count()}")
            checar("...e e' a MESMA embarcacao que foi salva",
                   marcadas.first.get_attribute("data-emb") == marcada,
                   f"tela={marcadas.first.get_attribute('data-emb')} salva={marcada}")
            marcadas.first.uncheck()
            pag.click("#escopo-de-acesso button:has-text('Salvar escopo')")
            pag.wait_for_function("() => /sem vínculo|sem vinculo/.test(document.body.innerText)", timeout=ESPERA)
            checar("desmarcar tudo limpa o vinculo no banco", vinculos(banco, "cliente-t") == set(),
                   str(vinculos(banco, "cliente-t")))

            # ---- 4. o observador (tipo 4) aparece sem vinculo, como "todas as empresas"
            pag.click("button[data-tela=usuarios]")
            pag.wait_for_selector("text=escopo de acesso", timeout=ESPERA)
            pag.locator("tr", has_text="petrobras@petrobras.test").first.locator(
                "button", has_text="escopo de acesso").click()
            pag.wait_for_selector("#escopo-de-acesso", timeout=ESPERA)
            texto = pag.inner_text("#escopo-de-acesso")
            checar("o observador e' mostrado como 'todas as empresas'", "todas as empresas" in texto, texto[:120])
            checar("o observador e' mostrado como SO' LEITURA", "LEITURA" in texto)
            checar("o observador nao recebe caixa de vinculo",
                   pag.locator("#escopo-de-acesso input[type=checkbox]").count() == 0)

            checar("sem erro de javascript na tela do admin", not erros, "; ".join(erros[:3]))
            navegador.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            api.kill()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s): " + "; ".join(falhas))
        return 1
    print("RESULTADO: tudo passou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
