#!/usr/bin/env python3
"""Prova de TELA: a tela do ADMIN fica limpa e a banda do vídeo ao vivo é escolhida de 1500 a 300 kbps.

Pedido do dono (18/11/2026, verbatim):
  "1. não vejo motivo pra 'Transmissões pedidas pelos clientes' existir no admin... precisa estar apenas
      no canal do cliente
   2. por que esses testes de vídeo estão na minha tela? isso não é necessário e ainda dá o aspecto de
      bagunçado
   3. ... não consigo escolher a qualidade do vídeo, continua com a caixa de seleção antiga, sem a
      seleção de 1500 a 300 kbps"

Sobe a API de verdade (banco próprio, contas de demonstração) e abre DOIS navegadores de verdade
(Chromium do Playwright). O que se prova, olhando a tela:

  1) como ADMIN: "Enviar vídeo" NÃO tem a caixa de pedidos dos clientes, NÃO tem "Teste de vídeo
     (bancada)" e NÃO tem "Qualidade por câmera" — e nada disso some da tela por acidente (a tela não
     pode ter erro de javascript);
  2) como ADMIN: a qualidade do ao vivo é a lista fechada 1500/1200/1000/800/500/300 kbps e o caminho de
     bancada (arquivo/link) não aparece;
  3) a banda escolhida CHEGA na API ao transmitir (`bitrate` no corpo do /api/ingestao/ao-vivo) — com a
     rota interceptada, sem ligar câmera nenhuma;
  4) como ADMIN: o "No ar agora" está na tela (é onde se PARA o envio contínuo);
  5) como OPERAÇÃO: a caixa de pedidos dos clientes CONTINUA (é ela que cancela), junto da bancada.

    python tests/e2e-tela-limpa-do-admin.py
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
import urllib.request

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "") or "senha-de-bancada-transmissao"
TOKEN = "token-de-teste-tela-limpa"
BANDAS = ["", "1500k", "1200k", "1000k", "800k", "500k", "300k"]


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
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-tela-limpa-"))
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
            ctx_adm = navegador.new_context(viewport={"width": 1500, "height": 950})
            ctx_op = navegador.new_context(viewport={"width": 1500, "height": 950})
            pag_adm, pag_op = ctx_adm.new_page(), ctx_op.new_page()
            erros: list[str] = []
            pag_adm.on("pageerror", lambda e: erros.append(str(e)))

            # --- 1) a TELA DO ADMIN, limpa -------------------------------------------------------
            entrar(pag_adm, base, "/admin/", "admin@lecsor.test")
            pag_adm.click('[data-tela="envios"]')
            pag_adm.wait_for_selector("#env-qualidade", timeout=20000)
            pag_adm.wait_for_timeout(1500)          # deixa a lista de cameras/dispositivos responder
            texto = pag_adm.locator("#tela").inner_text()

            for proibido in ("Transmissões pedidas pelos clientes", "Teste de vídeo (bancada)",
                             "Qualidade por câmera", "Comprimir e medir", "Publicar no ar"):
                checar(f"a tela do admin NÃO tem \"{proibido}\"", proibido.lower() not in texto.lower())
            checar("a tela do admin não tem a caixa de pedidos (#env-pedidos)",
                   pag_adm.locator("#env-pedidos").count() == 0)
            checar("a tela do admin não tem a caixa de qualidade por câmera (#env-qualidade-camera)",
                   pag_adm.locator("#env-qualidade-camera").count() == 0)
            checar("a tela do admin não tem a lista de compressões (bancada)",
                   pag_adm.locator("#env-comprimir").count() <= 1 and "Nenhuma compressão ainda" not in texto)
            checar("a tela do admin TEM o \"No ar agora\" (é onde se para o envio contínuo)",
                   pag_adm.locator("#env-no-ar").count() == 1)
            checar("a tela do admin tem o teto do produto e a trilha de gravações",
                   "Teto do produto" in texto and "Gravações" in texto)
            checar("a tela do admin abriu sem erro de javascript", not erros, "; ".join(erros)[:160])

            # --- 2) a banda do ao vivo é a lista fechada 1500...300 kbps ---------------------------
            rotulo_qual = pag_adm.locator("#env-qualidade").evaluate(
                "s => s.parentElement.querySelector('label').textContent")
            valores = pag_adm.eval_on_selector_all("#env-qualidade option", "os => os.map(o => o.value)")
            checar("a qualidade do ao vivo é a lista fechada de 1500 a 300 kbps",
                   [v for v in valores] == BANDAS, f"na tela: {valores}")
            checar("o rótulo diz que é BANDA (a caixa antiga de CRF saiu)", "banda" in rotulo_qual.lower(),
                   rotulo_qual)
            modos = pag_adm.eval_on_selector_all("#env-modo option", "os => os.map(o => o.value)")
            checar("a bancada (arquivo/link) não aparece para o admin",
                   "arquivo" not in modos and "url" not in modos, f"na tela: {modos}")
            checar("o admin continua podendo transmitir câmera, teste sintético e radar",
                   [m for m in modos] == ["camera", "sintetica", "radar"], f"na tela: {modos}")
            checar("o botão do admin é o de transmissão ao vivo",
                   "transmitir ao vivo" in pag_adm.locator("#env-comprimir").inner_text().lower(),
                   pag_adm.locator("#env-comprimir").inner_text())
            aviso_disp = pag_adm.locator("#env-dispositivo-aviso")
            # a enumeração do dshow (ffmpeg) leva segundos: espera a lista OU o motivo aparecer
            opcoes_disp, texto_aviso = 0, ""
            for _ in range(30):
                opcoes_disp = pag_adm.eval_on_selector_all("#env-dispositivo option", "os => os.length")
                texto_aviso = aviso_disp.inner_text() if aviso_disp.count() else ""
                if opcoes_disp > 0 or texto_aviso.strip():
                    break
                pag_adm.wait_for_timeout(1000)
            tem_aviso = aviso_disp.count() == 1 and bool(texto_aviso.strip())
            checar("a lista de câmeras desta máquina nunca fica muda (opção ou motivo na tela)",
                   opcoes_disp > 0 or tem_aviso,
                   f"opções={opcoes_disp} aviso={texto_aviso[:90]}")

            # --- 3) a banda escolhida CHEGA na API ------------------------------------------------
            capturado: dict = {}

            def _guardar(route):
                try:
                    capturado.update(json.loads(route.request.post_data or "{}"))
                except Exception:
                    capturado["bruto"] = route.request.post_data
                route.fulfill(status=201, content_type="application/json",
                              body=json.dumps({"fluxo_id": "vivo-teste", "alvo": "500k",
                                               "rotulo": capturado.get("rotulo") or "teste"}))
            pag_adm.route("**/api/ingestao/ao-vivo", _guardar)
            pag_adm.select_option("#env-qualidade", "500k")
            pag_adm.fill("#env-rotulo", "prova da banda")
            pag_adm.click("#env-comprimir")
            pag_adm.wait_for_timeout(1200)
            checar("a banda escolhida na tela chega na API ao transmitir",
                   capturado.get("bitrate") == "500k",
                   f"corpo enviado: { {k: v for k, v in capturado.items() if k != 'dispositivo'} }")
            checar("o modo enviado é o de câmera desta máquina", capturado.get("tipo") == "camera",
                   f"tipo={capturado.get('tipo')}")
            recado_tela = pag_adm.locator("#env-progresso").inner_text()
            checar("a tela diz que ficou no ar, com o alvo", "no ar" in recado_tela.lower() and "500k" in recado_tela,
                   recado_tela[:140])

            # --- 4) a tela da OPERAÇÃO continua com o que é dela -----------------------------------
            entrar(pag_op, base, "/admin/", "operacao@lecsor.test")
            pag_op.click('[data-tela="envios"]')
            pag_op.wait_for_selector("#env-qualidade", timeout=20000)
            pag_op.wait_for_timeout(1200)
            texto_op = pag_op.locator("#tela").inner_text()
            checar("a OPERAÇÃO continua vendo os pedidos dos clientes (é ela que cancela)",
                   pag_op.locator("#env-pedidos").count() == 1
                   and "Transmissões pedidas pelos clientes" in texto_op)
            checar("a OPERAÇÃO continua com a bancada (comprimir, medir e publicar)",
                   "Teste de vídeo (bancada)" in texto_op)
            modos_op = pag_op.eval_on_selector_all("#env-modo option", "os => os.map(o => o.value)")
            checar("a OPERAÇÃO continua com arquivo e link na lista de fontes",
                   "arquivo" in modos_op and "url" in modos_op, f"na tela: {modos_op}")
    finally:
        api.terminate()
    print()
    if falhas:
        print(f"E2E-TELA-LIMPA: {len(falhas)} FALHA(S): " + " · ".join(falhas))
        return 1
    print("E2E-TELA-LIMPA_OK — a tela do admin está limpa e a banda do vídeo ao vivo é 1500 a 300 kbps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
