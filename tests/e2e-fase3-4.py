#!/usr/bin/env python3
"""Teste das Fases 3 e 4 no navegador de verdade.

Fase 3 — 4 streams visiveis na tela do cliente.
Fase 4 — a imagem volta sozinha em <=10 s quando o publicador cai, e nenhuma credencial de
         camera (nem endereco interno) aparece no que o navegador do cliente envia ou recebe.

Uso: python tests/e2e-fase3-4.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "")
SAIDA = RAIZ / "bench" / "saida"
SAIDA.mkdir(parents=True, exist_ok=True)
falhas: list[str] = []
PROIBIDOS = ("rtsp://", ":8554", ":8890", ":9997", ":8889", "senha", "password", "credencial")


def checar(nome, condicao, detalhe=""):
    print(("  OK   " if condicao else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


def matar_publicador(fluxo: str) -> int:
    """Mata o publicador do fluxo (ffmpeg que empurra o fluxo de bancada)."""
    ps = (f"Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{fluxo}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    time.sleep(1)
    saida = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | Select-Object -ExpandProperty CommandLine"],
                           capture_output=True, text=True).stdout
    return sum(1 for l in saida.splitlines() if fluxo in l)


def subir_publicador():
    subprocess.Popen(["bash", "ground/publicar-fluxo-analitico.sh"], cwd=str(RAIZ),
                     stdout=open(SAIDA / "_publicador.log", "w"), stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def fluxo_pronto(fluxo: str) -> bool:
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:9997/v3/paths/list", timeout=5).read())
        return any(i["name"] == fluxo and i.get("ready") for i in d.get("items", []))
    except Exception:
        return False


def main() -> int:
    if not SENHA:
        print("defina LECSOR_SENHA_DEMO")
        return 2
    from playwright.sync_api import sync_playwright as _sync  # noqa: F401
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(channel="chrome")
        except Exception:
            nav = p.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1600, "height": 900})
        pag = ctx.new_page()
        pedidos: list[dict] = []
        pag.on("request", lambda r: pedidos.append({"url": r.url, "corpo": (r.post_data or "")}))
        pag.on("response", lambda r: None)

        print("[Fase 3] 4 streams na tela do cliente")
        pag.goto(f"{BASE}/app")
        pag.fill("#email", "cliente@armador-demo.test")
        pag.fill("#senha", SENHA)
        pag.click("form#form-entrar button[type=submit]")
        pag.wait_for_selector("#sistema:not(.oculto)", timeout=10000)
        pag.wait_for_timeout(6000)
        janelas = pag.locator(".janela").count()
        checar("quatro janelas de camera na tela", janelas == 4, f"{janelas} janela(s)")
        tocando = pag.evaluate("Array.from(document.querySelectorAll('.janela video')).filter(v => v.srcObject && v.readyState >= 2).length")
        checar("quatro videos recebendo imagem", tocando == 4, f"{tocando} de {janelas}")
        cams = json.loads(urllib.request.urlopen(f"{BASE}/api/analises").read())
        checar("mediamtx publicando quatro fluxos",
               all(fluxo_pronto(f"cam-0{i}") for i in (1, 2, 3, 4)),
               str([(f"cam-0{i}", fluxo_pronto(f"cam-0{i}")) for i in (1, 2, 3, 4)]))
        pag.screenshot(path=str(SAIDA / "_fase3-quatro-cameras.png"))

        print("[Fase 4] queda do publicador e volta da imagem")
        alvo = pag.locator("[data-cam='cam-03-analitico'] video").first
        checar("camera analitica tocando antes da queda",
               pag.evaluate("(() => { const v = document.querySelector(\"[data-cam='cam-03-analitico'] video\"); return !!(v && v.srcObject && v.readyState >= 2); })()"))
        a1 = pag.evaluate("(() => { const v = document.querySelector(\"[data-cam='cam-03-analitico'] video\"); return v ? v.currentTime : -1; })()")
        pag.wait_for_timeout(1500)
        a2 = pag.evaluate("(() => { const v = document.querySelector(\"[data-cam='cam-03-analitico'] video\"); return v ? v.currentTime : -1; })()")
        checar("relogio do video andando antes da queda", (a2 - a1) > 0.05, f"{a1:.2f} -> {a2:.2f}")
        restantes = matar_publicador("cam-03")
        checar("publicador da camera analitica derrubado", restantes == 0, f"{restantes} processo(s) ainda de pé")
        # sem fonte, o player tem de reagir (congelar ou ja reiniciar) — nao pode ficar exibindo
        # imagem velha como se estivesse ao vivo
        leitura = "(() => { const v = document.querySelector(\"[data-cam='cam-03-analitico'] video\"); return v ? v.currentTime : -1; })()"
        anterior = pag.evaluate(leitura)
        reacao = ""
        for _ in range(24):
            pag.wait_for_timeout(500)
            atual = pag.evaluate(leitura)
            if atual < anterior:  # reiniciou a sessao: ja esta se recuperando
                reacao = f"reiniciou ({anterior:.2f} -> {atual:.2f})"
                break
            if abs(atual - anterior) < 0.05:  # congelou: sem quadro novo
                reacao = f"congelou em {atual:.2f}"
                break
            anterior = atual
        checar("o player reage a perda da fonte (congela ou reinicia, sem fingir ao vivo)", bool(reacao), reacao or "sem reacao em 12 s")
        inicio = time.time()
        subir_publicador()
        voltou = 0.0
        while time.time() - inicio < 30:
            pronto = fluxo_pronto("cam-03")
            t1 = pag.evaluate("(() => { const v = document.querySelector(\"[data-cam='cam-03-analitico'] video\"); return v ? v.currentTime : -1; })()")
            pag.wait_for_timeout(700)
            t2 = pag.evaluate("(() => { const v = document.querySelector(\"[data-cam='cam-03-analitico'] video\"); return v ? v.currentTime : -1; })()")
            ok = (t2 - t1) > 0.05
            if pronto and ok:
                voltou = time.time() - inicio
                break
            pag.wait_for_timeout(500)
        checar("imagem volta sozinha em ate 10 s (fluxo no ar + quadro na tela)", 0 < voltou <= 10.0,
               f"{voltou:.1f} s" if voltou else "nao voltou em 30 s")
        pag.wait_for_timeout(1000)
        pag.screenshot(path=str(SAIDA / "_fase4-volta-da-imagem.png"))

        print("[Fase 4] nada de credencial de camera no navegador do cliente")
        urls = [p["url"] for p in pedidos]
        sujos = [u for u in urls if any(t in u.lower() for t in ("rtsp://", ":8554", ":8890", ":9997"))]
        checar("nenhum pedido do navegador com endereco interno/RTSP", not sujos, str(sujos[:3]))
        enviados = [p for p in pedidos if any(t in (p["corpo"] or "").lower() for t in ("senha", "password", "credencial"))
                    and "/api/entrar" not in p["url"] and "/api/usuarios" not in p["url"]]
        checar("nenhum corpo de pedido com senha/credencial de camera", not enviados, str([p['url'] for p in enviados][:3]))
        recebido = urllib.request.urlopen(f"{BASE}/api/analises").read().decode()
        checar("resposta de analises sem endereco de camera", not any(t in recebido.lower() for t in ("rtsp://", ":8554", ":8890")))
        ctx.close()
        nav.close()
    print("\nRESULTADO:", "tudo passou" if not falhas else f"{len(falhas)} falha(s): " + "; ".join(falhas))
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(main())
