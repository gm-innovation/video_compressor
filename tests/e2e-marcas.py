#!/usr/bin/env python3
"""Fase 5 pela tela: o operador desenha a marca, o agente de bordo obedece, e o cliente vê.

Prova que a linha e a zona saem da tela do admin, viram configuracao do agente e aparecem
na tela do cliente — e mede a demora do alerta de zona de risco ate o servidor gravar.

Uso: python tests/e2e-marcas.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "")
SAIDA = RAIZ / "bench" / "saida"
CAMPOS = {"a": [0.42, 0.0], "b": [0.42, 1.0]}          # linha vertical em 42% da largura
ZONA = {"nome": "faixa de teste", "x": 0.05, "y": 0.55, "l": 0.9, "a": 0.4, "segundos": 1.0}
falhas: list[str] = []


def checar(nome, condicao, detalhe=""):
    print(("  OK   " if condicao else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


def sessao_api(email, senha):
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    r = urllib.request.Request(f"{BASE}/api/entrar", data=json.dumps({"email": email, "senha": senha}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    op.open(r)
    return op


def ler_json(op, rota):
    with op.open(f"{BASE}{rota}") as r:
        return json.loads(r.read() or b"{}")


def matar_agentes():
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*analytics/agente.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)


def subir_agente():
    env = dict(os.environ)
    # o interpretador do agente tem de ser o do projeto: sem PYTHONPATH do ambiente externo
    for poluido in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(poluido, None)
    env.update({k: v for k, v in (l.strip().split("=", 1) for l in (RAIZ / "ground/.env.local").read_text(encoding="utf-8").splitlines() if "=" in l)})
    return subprocess.Popen([str(RAIZ / ".venv/Scripts/python.exe"), "-u", "analytics/agente.py",
                             "--perfil", "analytics/perfis/cam-03.json", "--duracao", "45"],
                            cwd=str(RAIZ), env=env, stdout=open(SAIDA / "_agente-marcas.log", "w"), stderr=subprocess.STDOUT)


def main() -> int:
    if not SENHA:
        print("defina LECSOR_SENHA_DEMO"); return 2
    SAIDA.mkdir(parents=True, exist_ok=True)
    print("[admin] desenhar a marca pela tela")
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(channel="chrome")
        except Exception:
            nav = p.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1600, "height": 900})
        pag = ctx.new_page()
        pag.goto(f"{BASE}/admin")
        pag.fill("#email", "admin@lecsor.test"); pag.fill("#senha", SENHA)
        pag.click("form#form-entrar button[type=submit]")
        pag.wait_for_selector("#sistema:not(.oculto)", timeout=10000)
        pag.click("button.item[data-tela='marcas']")
        pag.wait_for_selector("#mk-camera", timeout=8000)
        pag.select_option("#mk-camera", "cam-03-analitico")
        pag.wait_for_timeout(1200)
        pag.fill("#mk-ax", str(CAMPOS["a"][0])); pag.fill("#mk-ay", str(CAMPOS["a"][1]))
        pag.fill("#mk-bx", str(CAMPOS["b"][0])); pag.fill("#mk-by", str(CAMPOS["b"][1]))
        pag.fill("#mk-znome", ZONA["nome"]); pag.fill("#mk-zx", str(ZONA["x"])); pag.fill("#mk-zy", str(ZONA["y"]))
        pag.fill("#mk-zl", str(ZONA["l"])); pag.fill("#mk-za", str(ZONA["a"])); pag.fill("#mk-zs", str(ZONA["segundos"]))
        pag.click("button.acao.marca")
        pag.wait_for_timeout(1500)
        texto = pag.locator("#tela").inner_text()
        checar("a tela confirma a gravação da marca", "marcas gravadas" in texto, texto[:120].replace("\n", " "))
        linhas_svg = pag.locator("#mk-svg line").count()
        checar("a pré-visualização desenha a linha", linhas_svg >= 1, f"{linhas_svg} linha(s) no svg")
        pag.screenshot(path=str(SAIDA / "_fase5-marcas-admin.png"))

        op = sessao_api("operacao@lecsor.test", SENHA)
        marcas = ler_json(op, "/api/analytics/marcas?camera_id=cam-03-analitico")
        checar("a marca ficou gravada no servidor",
               abs(marcas["linha"]["a"][0] - CAMPOS["a"][0]) < 1e-6 and marcas["zonas"][0]["nome"] == ZONA["nome"],
               json.dumps(marcas, ensure_ascii=False)[:160])

        print("[agente] reiniciar para ler a marca do operador")
        matar_agentes()
        time.sleep(1)
        agente = subir_agente()
        time.sleep(35)
        dados = ler_json(op, "/api/analises")
        ag = dados["agentes"][0]
        linha = (ag.get("linhas") or [None])[0]
        checar("o agente está usando a linha desenhada na tela", bool(linha) and abs(linha["a"][0] - CAMPOS["a"][0]) < 0.01,
               json.dumps(linha, ensure_ascii=False))
        checar("o agente está no ar com a marca do operador", ag.get("estado") == "no ar",
               f"{ag.get('estado')} · {ag.get('fps')} quadros/s")

        print("[cliente] a linha desenhada aparece na tela do cliente")
        ctx2 = nav.new_context(viewport={"width": 1600, "height": 900})   # sessao limpa: papel de cliente
        pag2 = ctx2.new_page()
        pag2.goto(f"{BASE}/app")
        pag2.fill("#email", "cliente@armador-demo.test"); pag2.fill("#senha", SENHA)
        pag2.click("form#form-entrar button[type=submit]")
        pag2.wait_for_selector("#sistema:not(.oculto)", timeout=10000)
        pag2.click("#btn-ia")
        pag2.wait_for_timeout(3000)
        m = pag2.evaluate("""(() => { const j = document.querySelector("[data-cam='cam-03-analitico']");
            const e = j && j.querySelector('svg.camada-ia line.linha-ia');
            const z = j && j.querySelector('svg.camada-ia rect');
            return e ? { x1: parseFloat(e.getAttribute('x1')) / 100, y1: parseFloat(e.getAttribute('y1')) / 56.25,
                         zona: z ? parseFloat(z.getAttribute('y')) / 56.25 : -1 } : null; })()""")
        checar("linha do operador desenhada na janela do cliente, na posição desenhada",
               bool(m) and abs(m["x1"] - CAMPOS["a"][0]) < 0.02, f"x = {m['x1'] if m else '—'} (pedido {CAMPOS['a'][0]})")
        checar("zona de risco desenhada na janela do cliente",
               bool(m) and abs(m["zona"] - ZONA["y"]) < 0.02, f"topo em {m['zona'] if m else '—'} (pedido {ZONA['y']})")
        tem_selo = False
        for _ in range(20):
            if pag2.locator(".selo-ia").count() >= 1:
                tem_selo = True; break
            pag2.wait_for_timeout(1000)
        checar("contagem visível para o cliente", tem_selo, f"{pag2.locator('.selo-ia').count()} selo(s)")
        pag2.screenshot(path=str(SAIDA / "_fase5-marcas-cliente.png"))
        ctx.close(); nav.close()

    print("[servidor] alerta de zona de risco gravado e sua demora")
    con = sqlite3.connect(RAIZ / "db/pipeline.db"); con.row_factory = sqlite3.Row
    z = con.execute("SELECT * FROM analytics_eventos WHERE tipo='zona_risco' ORDER BY id DESC LIMIT 1").fetchone()
    if z:
        def instante(v):
            d = dt.datetime.fromisoformat(str(v))
            return d if d.tzinfo else d.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
        em = instante(z["inicio"]); gravado = instante(z["criado_em"])
        atraso = (gravado - em).total_seconds()
        checar("evento de zona de risco gravado no servidor", True, z["metadados"][:80])
        checar("alerta de zona em até 5 s do evento", atraso <= 5.0, f"{atraso:.1f} s")
    else:
        checar("evento de zona de risco gravado no servidor", False, "nenhum evento de zona no banco")
    con.close()
    agente.terminate()
    print("\nRESULTADO:", "tudo passou" if not falhas else f"{len(falhas)} falha(s): " + "; ".join(falhas))
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(main())
