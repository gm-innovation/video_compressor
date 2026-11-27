#!/usr/bin/env python3
"""Prova de TELA (0.21.0): a QUALIDADE de envio e o TETO moram em "Empresas e configuração".

O dono (26/11/2026): "inclua no plano mais possibilidades de qualidade de envio, 2mbps, 2,5mbps e
3mbps" · "o bloco de seleção de qualidade de envio sumiu da tela de configuração de bordo" ·
"se eu consigo editar empresa, embarcação e câmeras em 'Empresas e configuração', é necessário
'Configuração do bordo'?" · "não daria pra mudar para essa outra tela e remover configuração do bordo?
precisamos deixar tudo mais simples".

Sobe a API de verdade e abre navegador de verdade (Chromium do Playwright):

  1) o menu do admin NÃO tem mais "Configuração do bordo" (a tela saiu nesta rodada);
  2) o cartão da EMBARCAÇÃO (dentro de "Empresas e configuração" → "Abrir") tem o TETO de transmissão;
  3) cada cartão de CÂMERA tem o seletor da qualidade de envio com os NOVE níveis, do maior para o
     menor, incluindo os três novos (3,0 / 2,5 / 2,0 Mbps);
  4) escolher 3,0 Mbps no cartão da câmera PUBLICA `alvo_kbps=3000` (o banco prova);
  5) publicar o teto pelo cartão da embarcação grava `teto_s` (o banco prova);
  6) a lista do servidor aceita 3000 e recusa 4000 (a lista continua fechada);
  7) sem erro de javascript na área de empresas.

    python tests/e2e-qualidade-e-teto-em-empresas.py
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
SENHA = "senha-da-prova-qualidade-0210"
ESPERA = 25000


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


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-qualidade-"))
    banco = tmp / "pipeline.db"
    env = dict(os.environ)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_SENHA_DEMO": SENHA,
                "LECSOR_GRAVACOES_DIR": str(tmp / "gravacoes"), "PYTHONIOENCODING": "utf-8"})
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_EMBARCACAO", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
    porta = porta_livre()
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
                           cwd=str(RAIZ), env=env, stdout=(tmp / "api.log").open("wb"),
                           stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    pronto = False
    for _ in range(80):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                pronto = True
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    if not pronto:
        print("FALHA a API nao subiu:", (tmp / "api.log").read_text(errors="replace")[-400:])
        api.terminate()
        return 1

    # cameras como as do dono (uma comum, uma radar e a FLIR): o cartao de cada uma tem de oferecer a
    # qualidade de envio
    con = sqlite3.connect(str(banco))
    dono = con.execute("SELECT cliente_id FROM usuarios WHERE email='cliente@lecsor.test'").fetchone()
    emb = con.execute("SELECT id FROM embarcacoes WHERE cliente_id=? LIMIT 1", (dono[0],)).fetchone()
    embarcacao = emb[0]
    for cid, rot, tipo in (("cam-proa", "Proa (camera 1)", "camera"),
                           ("radar-01", "Radar de oleo", "radar"),
                           ("flir-01", "FLIR (termica)", "flir")):
        con.execute("""INSERT OR REPLACE INTO cameras
                       (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                       VALUES (?,?,?,'',1,1,'','','dshow','','500k',?)""", (cid, embarcacao, rot, tipo))
    con.commit()
    con.close()

    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch(executable_path=_chromium() or None)
            adm = nav.new_context(viewport={"width": 1500, "height": 980}).new_page()
            erros: list[str] = []
            adm.on("pageerror", lambda e: erros.append(str(e)))
            adm.goto(base + "/admin/")
            adm.fill("#email", "admin@lecsor.test")
            adm.fill("#senha", SENHA)
            adm.click("form#form-entrar button[type=submit]")
            adm.wait_for_selector("#sistema:not(.oculto)", timeout=ESPERA)

            # ---- 1) a tela "Configuração do bordo" saiu ------------------------------------------
            checar("o menu do admin NÃO tem mais 'Configuração do bordo'",
                   adm.locator('button.item[data-tela="config_bordo"]').count() == 0)

            # ---- 2) o TETO no cartão da embarcação ------------------------------------------------
            adm.click('[data-tela="empresas"]')
            adm.wait_for_selector("button.marca:has-text('Abrir')", timeout=ESPERA)
            adm.locator("button.marca:has-text('Abrir')").first.click()
            try:
                adm.wait_for_selector("input[id^=cfg-teto-]", timeout=ESPERA)
            except Exception:  # noqa: BLE001
                pass
            checar("o cartão da embarcação tem o campo do TETO (cfg-teto)",
                   adm.locator("input[id^=cfg-teto-]").count() >= 1)
            checar("...com o botão de publicar o teto junto",
                   adm.locator("button:has-text('Publicar teto')").count() >= 1)

            # ---- 3) a lista da qualidade no cartão da CÂMERA --------------------------------------
            cartoes = adm.locator("select[data-papel=alvo]").count()
            checar("cada cartão de câmera tem o seletor da qualidade de envio",
                   cartoes >= 1 and cartoes == adm.locator("select[data-papel=tipo]").count(),
                   "seletores da qualidade: %d (mesma contagem do tipo)" % cartoes)
            con = sqlite3.connect(str(banco))
            antes = con.execute("SELECT COUNT(*) FROM config_bordo WHERE chave='alvo_kbps'").fetchone()[0]
            con.close()
            checar("antes de mexer, NADA de alvo publicado no config_bordo (a prova do passo 4 vale)",
                   antes == 0, "linhas de alvo_kbps: %d" % antes)
            opcoes = adm.eval_on_selector_all(
                "select[data-papel=alvo]",
                "ss => ss[0] ? Array.from(ss[0].options).map(o => o.value) : []")
            esperado = ["3000", "2500", "2000", "1500", "1200", "1000", "800", "500", "300"]
            checar("a lista oferece os NOVE níveis, do maior para o menor", opcoes == esperado,
                   "na tela: %s" % opcoes)
            checar("o menu NUNCA abre em branco (a primeira opção fica escolhida)",
                   adm.eval_on_selector("select[data-papel=alvo]", "s => s.selectedIndex") == 0,
                   "selectedIndex=%s" % adm.eval_on_selector("select[data-papel=alvo]", "s => s.selectedIndex"))

            # ---- 4) publicar 3,0 Mbps pelo CARTÃO DA CÂMERA ---------------------------------------
            adm.locator("select[data-papel=alvo]").first.select_option("3000")
            adm.locator("select[data-papel=alvo]").first.locator(
                "xpath=following-sibling::button[contains(., 'aplicar qualidade')]").click()
            publicado = False
            for _ in range(40):
                con = sqlite3.connect(str(banco))
                linha = con.execute("SELECT valor FROM config_bordo WHERE chave='alvo_kbps' AND valor='3000'").fetchone()
                con.close()
                if linha:
                    publicado = True
                    break
                time.sleep(0.5)
            checar("escolher 3,0 Mbps no cartão da câmera publica `alvo_kbps=3000` (o banco prova)",
                   publicado)

            # ---- 4b) O DEFEITO DO DONO (3ª vez, 27/11/2026): "altero a qualidade, aplico e ela
            #          retorna a anterior". As câmeras desta prova foram gravadas com `alvo='500k'` e o
            #          LADO TERRA nunca recebe esse campo do bordo — o menu lia `cameras.alvo` e voltava
            #          ao valor velho. Agora ele lê a config PUBLICADA (a mesma da linha "publicado ao
            #          bordo"): publicamos 3000 e o menu TEM de continuar em 3000.
            mostrado = adm.eval_on_selector("select[data-papel=alvo]", "s => s.value")
            checar("publicar 3000 e o menu do cartão CONTINUA mostrando a qualidade publicada (o defeito era voltar ao valor velho)",
                   mostrado == "3000", "no menu: %r (publicado: 3000)" % mostrado)

            # ---- 5) publicar o TETO pelo CARTÃO DA EMBARCAÇÃO ------------------------------------
            adm.fill("input[id^=cfg-teto-]", "50")
            adm.locator("button:has-text('Publicar teto')").first.click()
            do_teto = False
            for _ in range(40):
                con = sqlite3.connect(str(banco))
                linha = con.execute("SELECT valor FROM config_bordo WHERE chave='teto_s' AND camera_id=''").fetchone()
                con.close()
                if linha and str(linha[0]) == "3000":
                    do_teto = True
                    break
                time.sleep(0.5)
            checar("publicar o teto pelo cartão da embarcação grava `teto_s=3000` (50 min)", do_teto)

            # ---- 6) a lista do SERVIDOR continua FECHADA (3,0 Mbps entra, 4,0 Mbps não) -----------
            def alvo_na_api(valor: str) -> int:
                return adm.evaluate(
                    """(v) => fetch('/api/cameras/cam-proa/alvo', {method: 'POST',
                         headers: {'Content-Type': 'application/json'},
                         body: JSON.stringify({alvo: v})}).then((r) => r.status)""", valor)
            checar("o servidor aceita 3000k (o nível novo pedido pelo dono)", alvo_na_api("3000k") == 200,
                   "http %s" % alvo_na_api("3000k"))
            checar("o servidor recusa 4000k (a lista continua FECHADA)", alvo_na_api("4000k") == 422,
                   "http %s" % alvo_na_api("4000k"))

            checar("sem erro de javascript na área de empresas", not erros, "; ".join(erros[:3]))
            nav.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass

    print()
    if falhas:
        print(f"E2E-QUALIDADE-E-TETO: {len(falhas)} FALHA(S): " + " · ".join(falhas))
        return 1
    print("E2E-QUALIDADE-E-TETO_OK — a qualidade (3000/2500/2000 kbps) e o teto moram em "
          "'Empresas e configuração', e a tela 'Configuração do bordo' não existe mais")
    return 0


if __name__ == "__main__":
    sys.exit(main())
