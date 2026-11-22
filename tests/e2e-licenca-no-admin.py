#!/usr/bin/env python3
"""Prova de TELA: o admin gera, ve' e revoga a chave da licenca (dono, 19/11/2026).

Pedido do dono, verbatim: *"quero apenas instalar o app no computador de captura, inserir a chave da
licenca e assim fazer a conexao com a empresa e embarcacao cadastradas, e a licenca pode ser
configuravel por tempo ou indeterminado"*. E, na mesma rodada, ele travou duas decisoes: a licenca vale
para UMA embarcacao, e **"sim, o admin pode ver e copiar a chave inteira quando quiser"**.

Aqui se prova com navegador de verdade (Chromium do Playwright) e API de verdade que, na tela
`Licenças` do painel:

  1. a tela esta' no menu e abre;
  2. o admin escolhe a embarcacao, o prazo (sem prazo ou ate' uma data) e quantos PCs;
  3. a chave sai no formato `XXXX-XXXX-XXXX-XXXX` e o admin consegue COPIAR de novo depois, quantas
     vezes quiser (a chave nao se perde);
  4. quantos PCs ja' usam e' visivel no cartao;
  5. revogar e reativar funcionam na propria tela;
  6. "gerar outra chave" troca a chave (a antiga morre);
  7. o operador NAO ve' licenca nenhuma (a tela diz que e' do admin);
  8. sem erro de javascript.

    python tests/e2e-licenca-no-admin.py
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
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
SENHA = "senha-do-admin-de-teste"
ESPERA = 20000
EMPRESA = "armador-teste"
EMB_A, EMB_B = "emb-a-teste", "emb-b-teste"
FORMATO = re.compile(r"^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$")


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


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,NULL,?,?,200000,1)""", (uid, email, uid, papel, senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Armador Teste"))
    for eid, nome in ((EMB_A, "Embarcacao A (teste)"), (EMB_B, "Embarcacao B (teste)")):
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                    (eid, EMPRESA, nome))
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


def palco(pag) -> str:
    try:
        return pag.inner_text("#tela")
    except Exception:  # noqa: BLE001
        return ""


def abrir_licencas(pag) -> None:
    pag.click("button[data-tela=licencas]")
    pag.wait_for_function("() => /Nova licença/.test(document.querySelector('#tela').innerText)",
                          timeout=ESPERA)


def chave_no_cartao(pag) -> str:
    """A chave que esta' escrita no cartao da licenca (o admin le'/copia a qualquer momento)."""
    for i in range(pag.locator("#tela code").count()):
        texto = pag.locator("#tela code").nth(i).inner_text().strip()
        if FORMATO.match(texto):
            return texto
    return ""


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-licenca-admin-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO", "LECSOR_EMBARCACAO", "LECSOR_LICENCA"):
        env.pop(k, None)
    # `LECSOR_SEM_AMBIENTE=1`: sem o `ambiente.json` do pacote este servidor E' o lado terra (nao
    # encaminha para a VPS) e o login cai no hash local do banco da prova (nao chama o Supabase).
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_EMBARCACAO": "bancada", "LECSOR_SENHA_DEMO": "senha-de-bancada-nao-usada",
                "PYTHONIOENCODING": "utf-8"})
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=3):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("a API nao subiu; log em %s" % (tmp / "api.log"))

        criar_usuario(banco, "admin", "admin@lecsor.test", "admin")
        criar_usuario(banco, "operacao", "operacao@lecsor.test", "operador")
        semear(banco)

        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            contexto = navegador.new_context(permissions=["clipboard-read", "clipboard-write"])
            pag = contexto.new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))

            print("\n== 1. a tela esta' no menu do admin ==")
            entrar(pag, base, "admin@lecsor.test", "button[data-tela=licencas]")
            checar("o painel do admin tem o menu 'Licenças'", visivel(pag, "button[data-tela=licencas]"))
            abrir_licencas(pag)
            checar("a tela de licencas abre", "Nova licença" in palco(pag))
            checar("e explica como funciona (a chave se digita no PC de captura)", "computador de captura" in palco(pag))
            opcoes = [pag.locator(".caixa-form select").nth(0).locator("option").nth(i).get_attribute("value")
                      for i in range(pag.locator(".caixa-form select").nth(0).locator("option").count())]
            checar("o admin escolhe a EMBARCACAO (as duas cadastradas aparecem)",
                   {EMB_A, EMB_B} <= set(opcoes), f"{opcoes}")

            print("\n== 2. gerar a chave (sem prazo, 2 PCs) ==")
            pag.locator(".caixa-form select").nth(0).select_option(EMB_A)
            pag.fill("#lic-maquinas", "2")
            pag.click("text=Gerar chave")
            pag.wait_for_function("() => /[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}/"
                                  ".test(document.querySelector('#tela').innerText)", timeout=ESPERA)
            chave = chave_no_cartao(pag)
            checar("a chave sai no cartao em `XXXX-XXXX-XXXX-XXXX`", bool(chave), f"{chave!r}")
            titulo = pag.locator("#tela h2").last.inner_text()
            checar("o cartao diz de qual embarcacao e' a chave",
                   "Embarcacao A (teste)" in titulo and EMB_A in titulo, titulo[:120])
            checar("o cartao diz a empresa dona", "Armador Teste" in titulo, titulo[:160])
            cartao = palco(pag)
            checar("e diz que ainda nenhum PC usou (0 de 2)", "PCs: 0/2 usados" in cartao,
                   cartao[:200].replace("\n", " | "))

            print("\n== 3. o admin copia a chave inteira de novo (pedido do dono) ==")
            pag.click("text=copiar chave")
            pag.wait_for_timeout(700)
            recado = palco(pag)
            checar("o botao 'copiar chave' confirma com a chave na tela", chave in recado, recado[:160].replace("\n", " | "))
            lida = ""
            try:
                lida = str(pag.evaluate("navigator.clipboard.readText()") or "").strip()
            except Exception:  # noqa: BLE001
                lida = ""
            checar("a area de transferencia recebeu a chave inteira (ou o aviso diz para copiar na mao)",
                   lida == chave or "na mão" in recado, f"area de transferencia: {lida!r}")

            print("\n== 4. revogar, reativar e gerar outra chave pela tela ==")
            pag.click("text=revogar")
            pag.wait_for_function("() => /revogada/.test(document.querySelector('#tela').innerText)",
                                  timeout=ESPERA)
            checar("revogar marca a licenca como revogada na tela", "revogada" in palco(pag))
            pag.click("text=reativar")
            pag.wait_for_function("() => /licença sem prazo/.test(document.querySelector('#tela').innerText)",
                                  timeout=ESPERA)
            cartao = palco(pag)
            checar("reativar devolve a licenca ao estado ativo",
                   "licença sem prazo" in cartao and "revogada" not in cartao, cartao[:200].replace("\n", " | "))
            pag.click("text=gerar outra chave")
            pag.wait_for_function(
                f"() => !document.querySelector('#tela').innerText.includes('{chave}')", timeout=ESPERA)
            nova = chave_no_cartao(pag)
            checar("gerar outra chave troca a chave do cartao", bool(nova) and nova != chave, f"{nova!r}")

            print("\n== 5. prazo por data e numero de PCs ajustavel pela tela ==")
            pag.click("text=prazo e nº de PCs")
            pag.wait_for_selector(".form-licenca select", timeout=ESPERA)
            pag.locator(".form-licenca select").select_option("ate")
            pag.locator(".form-licenca input[type=date]").fill("2027-06-30")
            pag.locator(".form-licenca input[type=number]").fill("4")
            pag.click(".form-licenca >> text=salvar")
            pag.wait_for_function("() => /até 2027-06-30/.test(document.querySelector('#tela').innerText)",
                                  timeout=ESPERA)
            cartao = palco(pag)
            checar("a tela passa a mostrar o prazo por data", "até 2027-06-30" in cartao, cartao[:200].replace("\n", " | "))
            checar("e o numero de PCs ajustado (0 de 4)", "PCs: 0/4 usados" in cartao, cartao[:240].replace("\n", " | "))

            checar("sem erro de javascript na tela do admin", not erros, "; ".join(erros[:3]))

            print("\n== 6. o operador nao ve' licenca nenhuma ==")
            contexto2 = navegador.new_context()   # sem a sessao do admin
            pag2 = contexto2.new_page()
            pag2.on("pageerror", lambda e: erros.append(str(e)))
            entrar(pag2, base, "operacao@lecsor.test", "button[data-tela=painel]")
            pag2.click("button[data-tela=licencas]")
            pag2.wait_for_timeout(1200)
            corpo = palco(pag2)
            checar("o operador recebe o aviso de que a area e' do admin",
                   "Somente o administrador" in corpo, corpo[:160].replace("\n", " | "))
            checar("o operador NAO ve' chave nenhuma", not FORMATO.search(corpo), corpo[:160].replace("\n", " | "))
            checar("nem o formulario de gerar chave", "Gerar chave" not in corpo)
            checar("o operador continua sem erro de javascript", not erros, "; ".join(erros[:3]))
            contexto2.close()

            navegador.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            api.kill()
        log.close()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s): " + "; ".join(falhas))
        return 1
    print("RESULTADO: tudo passou — o admin gera, le', copia, muda prazo/nº de PCs, revoga e reemite a "
          "chave pela tela; o operador nao ve' nada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
