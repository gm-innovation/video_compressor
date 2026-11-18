#!/usr/bin/env python3
"""Prova de TELA no CELULAR: o cliente abre a transmissao pela web num telefone, sem instalar app.

Sobe a API de verdade (banco proprio, contas de demonstracao) e abre a tela do cliente `/app` num
navegador de verdade com a janela do tamanho de um telefone (390x844: iPhone 14 / Android medio),
com toque ligado. O que se prova, olhando a tela:
  1) a tela "Transmitir" nao estoura para o lado (nenhuma rolagem horizontal);
  2) o menu e as linhas de camera cabem na largura do telefone;
  3) o botao de iniciar tem alvo de dedo (>= 32 px de altura) e responde ao TOQUE;
  4) a tela "Tempo de transmissao" tambem cabe no telefone.

    LECSOR_SENHA_DEMO=... python tests/test-app-no-celular.py
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "") or "senha-de-bancada-transmissao"
TOKEN = "token-de-teste-do-celular"
LARGURA = 390
ALTURA = 844


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


def entrar(pag, base: str, email: str) -> None:
    pag.goto(base + "/app/")
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=20000)


def estoura_para_o_lado(pag) -> tuple[int, int, list[str]]:
    """Devolve (largura do conteudo, largura da janela, quem passa da tela do telefone).

    O navegador do telefone, quando o conteudo nao cabe, ALARGA a janela em vez de rolar — entao
    medir contra a janela esconderia o defeito. A medida que vale e' a largura do proprio telefone.
    """
    largura = pag.evaluate("document.documentElement.scrollWidth")
    janela = pag.evaluate("window.innerWidth")
    culpados = pag.evaluate(f"""() => {{
        const fora = [];
        for (const e of document.querySelectorAll('body *')) {{
            const r = e.getBoundingClientRect();
            if (r.width > 0 && r.height > 0 && r.right > {LARGURA} + 1 && e.children.length === 0) {{
                fora.push((e.id ? '#' + e.id : e.tagName.toLowerCase() + (e.className ? '.' + String(e.className).split(' ')[0] : ''))
                          + ' ate ' + Math.round(r.right) + 'px');
            }}
        }}
        return [...new Set(fora)].slice(0, 6);
    }}""")
    return largura, janela, culpados


def cabe_na_tela(pag, seletor: str) -> tuple[bool, str]:
    """A caixa do elemento esta' inteira dentro da largura do telefone?"""
    caixa = pag.locator(seletor).first.bounding_box()
    if not caixa:
        return False, "sem caixa"
    esq, dirr = caixa["x"], caixa["x"] + caixa["width"]
    return (esq >= -1 and dirr <= LARGURA + 1), f"x={esq:.0f} ate {esq + caixa['width']:.0f}"


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-celular-"))
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(tmp / "pipeline.db")
    env["LECSOR_SENHA_DEMO"] = SENHA
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["LECSOR_GRAVACOES_DIR"] = str(tmp / "gravacoes")
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    porta = porta_livre()
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    pronto = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                pronto = True
                break
        except Exception:
            time.sleep(0.5)
    if not pronto:
        print("FALHA a API nao subiu:", (tmp / "api.log").read_text(errors="replace")[-400:])
        api.terminate()
        return 1
    try:
        with sync_playwright() as pw:
            navegador = pw.chromium.launch(executable_path=_chromium())
            ctx = navegador.new_context(
                viewport={"width": LARGURA, "height": ALTURA},
                device_scale_factor=3, is_mobile=True, has_touch=True,
            )
            pag = ctx.new_page()
            pag.goto(base + "/app/")
            endereco = pag.locator("#endereco-texto").inner_text()
            checar("a entrada mostra o endereco da tela (o cliente so' abre o link)",
                   endereco.startswith("http") and endereco.endswith("/app/"), endereco)
            entrar(pag, base, "cliente@lecsor.test")

            # 1) o menu do cliente cabe e a tela nao estoura para o lado
            largura_conteudo, largura_janela, culpados = estoura_para_o_lado(pag)
            checar("a tela de entrada cabe na largura do telefone",
                   largura_conteudo <= LARGURA + 2 and largura_janela <= LARGURA + 2,
                   f"conteudo {largura_conteudo}px / janela {largura_janela}px / tela {LARGURA}px {culpados}")
            cabe, onde = cabe_na_tela(pag, '[data-tela="transmissao"]')
            checar("o botao do menu 'Transmitir' cabe no telefone", cabe, onde)

            # 2) a tela Transmitir, com as cameras do cliente
            pag.tap('[data-tela="transmissao"]')
            pag.wait_for_selector(".transmissao-linha", timeout=20000)
            largura_conteudo, largura_janela, culpados = estoura_para_o_lado(pag)
            checar("a tela 'Transmitir' cabe na largura do telefone",
                   largura_conteudo <= LARGURA + 2 and largura_janela <= LARGURA + 2,
                   f"conteudo {largura_conteudo}px / janela {largura_janela}px / tela {LARGURA}px {culpados}")
            cabe, onde = cabe_na_tela(pag, ".transmissao-linha")
            checar("a linha da camera cabe no telefone", cabe, onde)

            # 3) alvo de dedo e TOQUE de verdade no iniciar
            cam = pag.locator(".transmissao-linha").first.get_attribute("data-camera")
            botao = pag.locator(f"#iniciar-{cam}")
            caixa = botao.bounding_box() or {"height": 0, "width": 0}
            checar("o botao de iniciar tem alvo de dedo (>= 32 px de altura)",
                   caixa["height"] >= 32, f"{caixa['height']:.0f}px de altura")
            botao.tap()
            dito = ""
            fim = time.time() + 20
            while time.time() < fim:
                linhas = pag.locator(".transmissao-linha").first.inner_text()
                if linhas and linhas.strip():
                    dito = linhas
                if "pedido enviado" in dito.lower() or "no ar" in dito.lower():
                    break
                pag.wait_for_timeout(400)
            checar("o toque no iniciar mandou o pedido ao bordo",
                   "pedido enviado" in dito.lower() or "no ar" in dito.lower(),
                   dito.replace("\n", " · ")[:90])

            # 4) a tela de tempo tambem cabe
            pag.tap('[data-tela="configuracao"]')
            pag.wait_for_selector("#tempo-maximo", timeout=20000)
            largura_conteudo, largura_janela, culpados = estoura_para_o_lado(pag)
            checar("a tela 'Tempo de transmissao' cabe na largura do telefone",
                   largura_conteudo <= LARGURA + 2 and largura_janela <= LARGURA + 2,
                   f"conteudo {largura_conteudo}px / janela {largura_janela}px / tela {LARGURA}px {culpados}")
            cabe, onde = cabe_na_tela(pag, "#tempo-maximo")
            checar("o campo de tempo cabe no telefone", cabe, onde)

            ctx.close()
            navegador.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:
            api.kill()

    print(("CELULAR_OK" if not falhas else f"CELULAR_FALHOU: {', '.join(falhas)}"))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
