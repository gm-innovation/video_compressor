#!/usr/bin/env python3
"""Prova de TELA da Fase 6 do radar: a escolha e' do operador, na tela de captura.

Sobe a API de verdade com banco proprio e contas de demonstracao (senha em `LECSOR_SENHA_DEMO`) e abre a
tela do admin num navegador de verdade (Chromium do Playwright). O que se prova, olhando a tela:
  1) a captura ganha a opcao "radar da embarcacao" e, escolhida, a LINHA do radar aparece (a linha so'
     existe no modo radar — nada de formulario morto na tela dos outros modos);
  2) o botao passa a dizer "Transmitir o radar ao vivo" (nao "Comprimir e medir");
  3) "Gravar na embarcacao" grava e a propria tela confirma em voz alta o que ficou gravado;
  4) recarregando a tela, o que ficou gravado VOLTA preenchido naquela embarcacao (leitura de verdade);
  5) pedido torto (fonte que nao e' sinal) e' recusado NA TELA, com o motivo.

    LECSOR_SENHA_DEMO=... python tests/e2e-radar-na-tela.py
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "") or "senha-de-bancada-radar"


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def gravar_drq(caminho: pathlib.Path) -> None:
    """Um .drq minimo no formato medido (1.024 B de cabecalho + quadros de 2.240 B, tipo=3)."""
    import datetime
    cab = bytearray(1024)
    struct.pack_into("<II", cab, 0, 0, 1)
    struct.pack_into("<II", cab, 128, 3539456, 4096)
    t0 = datetime.datetime(2026, 11, 6, 16, 44, 27)
    with open(caminho, "wb") as f:
        f.write(bytes(cab))
        for i in range(360 * 4):
            q = bytearray(2240)
            grau = i % 360
            dt = t0 + datetime.timedelta(seconds=i / 24.0)
            ft = int((dt - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)
            struct.pack_into("<II", q, 0, 3, 2240)
            struct.pack_into("<Q", q, 24, ft)
            struct.pack_into("<II", q, 40, grau, grau * 4096 // 360)
            struct.pack_into("<H", q, 188, 1024)
            for k in range(1024):
                struct.pack_into("<H", q, 192 + 2 * k, 3000 - k // 2)
            f.write(bytes(q))


def _chromium() -> str | None:
    """Usa o Chromium que JA esta na maquina (cache do ms-playwright) — nada de baixar de novo."""
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-radar-tela-"))
    banco = tmp / "pipeline.db"
    drq = tmp / "sinal-do-radar.drq"
    gravar_drq(drq)

    porta = porta_livre()
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_SENHA_DEMO"] = SENHA
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
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
            pag = navegador.new_context(viewport={"width": 1600, "height": 950}).new_page()
            erros: list[str] = []
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.goto(base + "/admin/")
            pag.fill("#email", "admin@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector("#sistema:not(.oculto)", timeout=15000)
            # a caixa de captura mora na tela "Enviar vídeo" (o menu do admin)
            pag.click('[data-tela="envios"]')
            pag.wait_for_selector("#env-modo", timeout=15000)

            opcoes = pag.eval_on_selector_all("#env-modo option", "os => os.map(o => o.value)")
            checar("a captura tem a opcao de radar", "radar" in opcoes, f"opcoes: {opcoes}")
            checar("a linha do radar comeca escondida (so' aparece no modo radar)",
                   pag.locator("#env-radar").is_hidden())

            pag.select_option("#env-modo", "radar")
            # espera a PRIMEIRA leitura do radar chegar (as embarcacoes aparecerem) antes de agir
            pag.wait_for_function("document.querySelectorAll('#env-radar-embarcacao option').length > 0",
                                  timeout=15000)
            pag.wait_for_timeout(300)
            checar("escolhido o radar, a LINHA do radar aparece", pag.locator("#env-radar").is_visible())
            texto = pag.locator("#env-comprimir").inner_text().strip()
            checar("o botao passa a transmitir o radar", "radar" in texto.lower(), texto)
            embarcacoes = pag.eval_on_selector_all("#env-radar-embarcacao option", "os => os.map(o => o.value)")
            checar("as embarcacoes aparecem para escolher", len(embarcacoes) >= 1, f"{embarcacoes}")

            # pedido torto: fonte que nao e' sinal de radar -> recusa NA TELA
            pag.fill("#env-radar-fonte", "video-do-radar.mp4")
            pag.click("#env-radar button.acao")
            pag.wait_for_timeout(600)
            aviso = pag.locator("#env-radar-aviso").inner_text().strip()
            checar("a tela recusa fonte que nao e' sinal", aviso.startswith("recusado"), aviso)

            # grava de verdade
            pag.fill("#env-radar-fonte", str(drq))
            pag.select_option("#env-radar-modo", "cru")
            pag.select_option("#env-radar-taxa", "volta")
            pag.select_option("#env-radar-alvo", "800k")
            pag.click("#env-radar button.acao")
            pag.wait_for_timeout(800)
            aviso = pag.locator("#env-radar-aviso").inner_text().strip()
            checar("a tela confirma o que ficou gravado", aviso.startswith("gravado"), aviso)

            # recarrega: o gravado VOLTA na tela (leitura de verdade)
            pag.reload()
            pag.wait_for_selector("#sistema:not(.oculto)", timeout=15000)
            pag.click('[data-tela="envios"]')
            pag.wait_for_selector("#env-modo", timeout=15000)
            pag.select_option("#env-modo", "radar")
            pag.wait_for_timeout(800)
            checar("recarregando, a fonte gravada volta na tela",
                   str(drq) in pag.input_value("#env-radar-fonte"), pag.input_value("#env-radar-fonte"))
            checar("recarregando, a imagem gravada volta na tela",
                   pag.input_value("#env-radar-modo") == "cru", pag.input_value("#env-radar-modo"))
            checar("recarregando, a taxa gravada volta na tela",
                   pag.input_value("#env-radar-taxa") == "volta", pag.input_value("#env-radar-taxa"))
            checar("recarregando, o alvo gravado volta na tela",
                   pag.input_value("#env-radar-alvo") == "800k", pag.input_value("#env-radar-alvo"))
            checar("nenhum erro de script na tela", not erros, "; ".join(erros[:2]))
            pag.screenshot(path=str(tmp / "tela-radar.png"))
            print("captura de tela:", tmp / "tela-radar.png")
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
    print("RADAR_TELA_OK — a escolha do radar funciona na tela, fica gravada e volta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
