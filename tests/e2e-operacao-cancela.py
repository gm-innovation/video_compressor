#!/usr/bin/env python3
"""Prova de TELA da OPERACAO: ve o pedido do cliente e cancela (plano, Fase 2 P1).

Sobe a API de verdade (banco proprio, contas de demonstracao) e abre DOIS navegadores de verdade
(Chromium do Playwright): um cliente e um operador. O que se prova, olhando a tela:

  1) o operador entra na tela de administracao e, em "Enviar vídeo", ve os pedidos dos clientes
     (embarcação, câmera e quem pediu) — antes o pedido ficava só no banco, ninguém enxergava;
  2) o operador CANCELA o pedido pela tela, a tela diz que cancelou, o pedido some da lista e o
     bordo recebe a ordem de parar (a operação vê o efeito do que fez);
  3) o histórico do cliente guarda "cancelada pela operação" (nada apagado);
  4) a tela do operador mostra o endereço da tela do cliente para mandar junto com o acesso.

    LECSOR_SENHA_DEMO=... python tests/e2e-operacao-cancela.py
"""
from __future__ import annotations

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
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "") or "senha-de-bancada-transmissao"
TOKEN = "token-de-teste-da-operacao"


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


def entrar(pag, base: str, raiz: str, email: str) -> None:
    pag.goto(base + raiz)
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=20000)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-operacao-"))
    banco = tmp / "pipeline.db"
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
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
            ctx_cli = navegador.new_context(viewport={"width": 1500, "height": 900})
            ctx_op = navegador.new_context(viewport={"width": 1500, "height": 900})
            pag_cli, pag_op = ctx_cli.new_page(), ctx_op.new_page()
            erros: list[str] = []
            pag_op.on("pageerror", lambda e: erros.append(str(e)))

            # --- 1) o CLIENTE pede a transmissao pela web -------------------------------------------
            entrar(pag_cli, base, "/app/", "cliente@lecsor.test")
            # PLANO UNICO (25/11/2026): a tela "Transmitir" saiu do cliente - o controle (iniciar/parar/
            # contagem/gravar) mora na GRADE, no quadro de cada camera, e o cliente ja' cai nela.
            cam = pag_cli.eval_on_selector_all(".janela", "ls => ls.map(l => l.dataset.cam)")[0]
            pag_cli.wait_for_selector(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]', timeout=20000)
            pag_cli.click(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]')
            pedido_na_tela = ""
            fim = time.time() + 15
            while time.time() < fim:
                pedido_na_tela = pag_cli.locator(f'[data-estado="{cam}"]').inner_text()
                if "pedido enviado" in pedido_na_tela.lower():
                    break
                pag_cli.wait_for_timeout(300)
            checar("o cliente pediu pela web e a tela diz que o pedido foi para o bordo",
                   "pedido enviado" in pedido_na_tela.lower(), pedido_na_tela.replace("\n", " · ")[:80])

            # --- 2) o OPERADOR ve o pedido e cancela -------------------------------------------------
            entrar(pag_op, base, "/admin/", "operacao@lecsor.test")
            pag_op.click('[data-tela="envios"]')
            pag_op.wait_for_selector("#env-pedidos", timeout=20000)
            pag_op.wait_for_selector("#env-pedidos table", timeout=20000)
            texto_pedidos = pag_op.locator("#env-pedidos").inner_text()
            _con = sqlite3.connect(banco)
            _r = _con.execute("SELECT rotulo FROM cameras WHERE fluxo_id=?", (cam,)).fetchone()
            _con.close()
            rotulo_cam = _r[0] if _r else cam          # a tela mostra o ROTULO da camera, nao o id interno
            checar("a operacao ve o pedido do cliente (quem pediu e qual camera)",
                   "cliente@lecsor.test" in texto_pedidos and rotulo_cam in texto_pedidos,
                   f"procurado: cliente@lecsor.test + {rotulo_cam!r} · na tela: {texto_pedidos.replace(chr(10), ' · ')[:140]}")
            botao_cancelar = pag_op.locator('#env-pedidos button:has-text("cancelar pedido")').first
            checar("a operacao tem o botao de cancelar o pedido", botao_cancelar.count() >= 1)
            botao_cancelar.click()
            recado = ""
            fim = time.time() + 15
            while time.time() < fim:
                try:
                    recado = pag_op.locator("#tela .recado").first.inner_text(timeout=2000)
                except Exception:
                    recado = ""
                if "cancelado" in recado.lower():
                    break
                pag_op.wait_for_timeout(300)
            checar("a operacao cancela pela tela e a tela diz que cancelou",
                   "cancelado" in recado.lower(), recado[:120])
            pag_op.wait_for_timeout(1200)
            depois = pag_op.locator("#env-pedidos").inner_text()
            checar("o pedido sai da lista de pedidos abertos",
                   "nenhum pedido aberto" in depois.lower(), depois.replace("\n", " · ")[:120])

            # --- 3) o historico do cliente guarda quem cancelou ---------------------------------------
            con = sqlite3.connect(banco)
            linha = con.execute("""SELECT estado, motivo FROM transmissoes
                                   WHERE usuario_email='cliente@lecsor.test' ORDER BY criada_em DESC LIMIT 1""").fetchone()
            ordem_parar = con.execute("SELECT COUNT(*) FROM ordens_do_bordo WHERE acao='parar'").fetchone()[0]
            con.close()
            checar("o historico guarda 'cancelada' com quem cancelou",
                   bool(linha) and linha[0] == "cancelada" and "operacao" in (linha[1] or "").lower(),
                   f"{linha}")
            checar("o bordo recebeu a ordem de parar", ordem_parar >= 1, f"{ordem_parar} ordem(ns) de parar")

            # --- 4) o endereco do cliente na tela da operacao -----------------------------------------
            pag_op.click('[data-tela="clientes"]')
            pag_op.wait_for_selector("#end-cliente", timeout=20000)
            endereco = pag_op.locator("#end-cliente").inner_text()
            checar("a operacao tem o endereco da tela do cliente para mandar junto com o acesso",
                   "/app/" in endereco, endereco.replace("\n", " ")[:120])

            checar("nenhum erro de script na tela da operacao", not erros, "; ".join(erros)[:120])
            ctx_cli.close()
            ctx_op.close()
            navegador.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=15)
        except Exception:
            api.kill()
        log.close()

    print()
    if falhas:
        print(f"FALHAS ({len(falhas)}):")
        for f in falhas:
            print(" -", f)
        return 1
    print("OPERACAO_CANCELA_OK — a operacao ve o pedido do cliente, cancela pela tela e o bordo obedece.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
