#!/usr/bin/env python3
"""Verificacao automatizada dos dois fronts (cliente e admin) com navegador de verdade.

Roda contra a API local (padrao http://127.0.0.1:8765). Usa as contas de demonstracao:
a senha vem de LECSOR_SENHA_DEMO (nunca fica no repositorio).

Uso: python tests/e2e-fronts.py [url]
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]


def subir_agente(segundos: int = 90):
    """Sobe o agente de análise de bordo para o teste não depender de sorte: sem ele não há
    caixa de detecção nem contagem chegando na tela. Devolve o processo para encerrar depois."""
    env = dict(os.environ)
    for poluido in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(poluido, None)
    env.update({k: v for k, v in (l.strip().split("=", 1)
                                  for l in (RAIZ / "ground/.env.local").read_text(encoding="utf-8").splitlines() if "=" in l)})
    return subprocess.Popen([str(RAIZ / ".venv/Scripts/python.exe"), "-u", "analytics/agente.py",
                             "--perfil", "analytics/perfis/cam-03.json", "--duracao", str(segundos)],
                            cwd=str(RAIZ), env=env, stdout=open(SAIDA / "_agente-fronts.log", "w"),
                            stderr=subprocess.STDOUT)

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "")
SAIDA = Path(__file__).resolve().parents[1] / "bench" / "saida"
SAIDA.mkdir(parents=True, exist_ok=True)
falhas: list[str] = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("  OK   " if condicao else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


def entrar(pagina, email: str) -> None:
    pagina.goto(f"{BASE}/{'app' if 'app' in pagina.url or True else 'admin'}")
    pagina.fill("#email", email)
    pagina.fill("#senha", SENHA)
    pagina.click("form#form-entrar button[type=submit]")
    pagina.wait_for_selector("#sistema:not(.oculto)", timeout=10000)


def verificar_cliente(navegador) -> None:
    print("[cliente] /app")
    ctx = navegador.new_context(viewport={"width": 1600, "height": 900})
    pag = ctx.new_page()
    pag.goto(f"{BASE}/app")
    pag.fill("#email", "cliente@armador-demo.test")
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=10000)
    pag.wait_for_timeout(3500)  # deixa a sessao WebRTC subir e o video pintar
    checar("barra lateral com as tres secoes",
           all(pag.locator(f"text={s}").count() > 0 for s in ("EVENTOS", "CADASTROS", "CONFIGURAÇÃO")))
    checar("titulo das transmissoes", pag.locator("#titulo-tela").inner_text().strip().startswith("Transmissões"))
    janelas = pag.locator(".janela").count()
    checar("janela de video por camera", janelas >= 1, f"{janelas} janela(s)")
    tocando = pag.evaluate("Array.from(document.querySelectorAll('.janela video')).filter(v => v.srcObject && v.readyState >= 2).length")
    checar("video recebendo (srcObject + readyState>=2)", tocando >= 1, f"{tocando} de {janelas}")
    rotulo = pag.locator(".janela .rotulo-cam").first.inner_text() if janelas else ""
    checar("rotulo da camera na janela", "PSV" in rotulo or "câmera" in rotulo, rotulo)
    relogio = pag.locator(".janela .marca-dagua").first.inner_text() if janelas else ""
    checar("relogio na janela", len(relogio) >= 19, relogio)
    checar("rodape com câmeras selecionadas", "câmeras selecionadas" in pag.locator("#contagem-selecao").inner_text())
    pag.screenshot(path=str(SAIDA / "_front-cliente-live.png"))
    for tela in ("Alertas", "Relatórios", "Câmeras"):
        pag.click(f"button.item[data-tela]:has-text('{tela}')")
        pag.wait_for_timeout(600)
        checar(f"tela {tela} abre com tabela",
               pag.locator("table").count() > 0 and pag.locator("#titulo-tela").inner_text().strip().startswith(tela))
    pag.screenshot(path=str(SAIDA / "_front-cliente-relatorios.png"))
    ctx.close()


def verificar_admin(navegador) -> None:
    print("[admin] /admin")
    ctx = navegador.new_context(viewport={"width": 1600, "height": 900})
    pag = ctx.new_page()
    pag.goto(f"{BASE}/admin")
    pag.fill("#email", "admin@lecsor.test")
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=10000)
    pag.wait_for_timeout(2000)
    grupos = all(pag.locator(f"text={s}").count() > 0 for s in ("PROJETO", "SISTEMA"))
    checar("barra lateral com PROJETO e SISTEMA", grupos)
    cartoes = pag.locator(".cartao-dado").count()
    checar("cartoes do painel do projeto", cartoes >= 5, f"{cartoes} cartoes")
    fases = pag.locator(".tabela tbody tr").count()
    checar("tabela de fases", fases >= 9, f"{fases} linhas")
    pag.screenshot(path=str(SAIDA / "_front-admin-painel.png"))
    # usuarios (so admin)
    pag.click("button.item[data-tela='usuarios']")
    pag.wait_for_timeout(800)
    checar("tela de usuarios com formulario", pag.locator("#u-email").count() == 1)
    checar("tabela de usuarios", pag.locator(".tabela tbody tr").count() >= 3)
    pag.screenshot(path=str(SAIDA / "_front-admin-usuarios.png"))
    # saude do sistema
    pag.click("button.item[data-tela='saude']")
    pag.wait_for_timeout(800)
    checar("saude do sistema com contagens", "Sessões abertas" in pag.content())
    pag.screenshot(path=str(SAIDA / "_front-admin-saude.png"))
    # create pela tela: cliente novo
    pag.click("button.item[data-tela='clientes']")
    pag.wait_for_timeout(800)
    pag.fill("#c-id", "armador-e2e")
    pag.fill("#c-nome", "Armador E2E (criado pela tela)")
    pag.click("button.acao.marca")
    pag.wait_for_timeout(1500)
    texto = pag.locator("#tela").inner_text()
    checar("cadastro de cliente pela tela (ou já cadastrado, sem erro na tela)",
           ("armador-e2e" in texto) and
           any(m in texto for m in ("cliente cadastrado", "já existe", "ja existe")))
    checar("cliente aparece na tabela", "Armador E2E" in pag.locator(".tabela").inner_text())
    pag.screenshot(path=str(SAIDA / "_front-admin-clientes.png"))
    ctx.close()


def verificar_analises(navegador) -> None:
    """Fase 5 na tela: o cliente liga a IA e ve contagem, linha e caixas; o admin ve o estado do agente."""
    import json as _json
    import urllib.request as _url
    print("[cliente] IA · Análises")
    ctx = navegador.new_context(viewport={"width": 1600, "height": 900})
    pag = ctx.new_page()
    pag.goto(f"{BASE}/app")
    pag.fill("#email", "cliente@armador-demo.test")
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=10000)
    pag.wait_for_timeout(3000)
    checar("pílula de IA presente na barra de controles", pag.locator("#btn-ia").count() == 1)
    pag.click("#btn-ia")
    pag.wait_for_timeout(2500)
    checar("selo com contagem por câmera", pag.locator(".selo-ia").count() >= 1)
    selo = pag.locator(".selo-ia").first.inner_text() if pag.locator(".selo-ia").count() else ""
    checar("selo mostra entrou/saiu", ("entrou" in selo and "saiu" in selo), selo)
    checar("linha de contagem desenhada", pag.locator(".linha-ia").count() >= 1)
    dados = _json.loads(_url.urlopen(f"{BASE}/api/analises").read())
    ag = (dados.get("agentes") or [{}])[0]
    checar("agente de análise reportando estado", ag.get("estado") in ("no ar", "parado"), str(ag.get("estado")))
    checar("modelo e quadros por segundo informados", bool(ag.get("modelo")) and (ag.get("fps") or 0) > 0,
           f"{ag.get('modelo')} @ {ag.get('fps')} q/s")
    caixas = 0
    for _ in range(10):  # a detecção depende de haver pessoa no quadro: tenta por ~40 s
        caixas = pag.locator(".caixa").count()
        if caixas:
            break
        pag.wait_for_timeout(4000)
    pico = 0
    try:
        import sqlite3
        con = sqlite3.connect(RAIZ / "db/pipeline.db"); con.row_factory = sqlite3.Row
        r = con.execute("SELECT max(pico) AS p FROM analytics_contagens WHERE camera_id='cam-03-analitico'").fetchone()
        pico = int(r["p"] or 0); con.close()
    except Exception:
        pass
    checar("caixa de detecção desenhada sobre o vídeo", caixas >= 1, f"{caixas} caixa(s)")
    checar("o agente realmente detectou pessoas nesta rodada", pico >= 1, f"pico de {pico} pessoa(s) na janela")
    pag.screenshot(path=str(SAIDA / "_front-cliente-ia.png"))
    ctx.close()

    print("[admin] Análises")
    ctx = navegador.new_context(viewport={"width": 1600, "height": 900})
    pag = ctx.new_page()
    pag.goto(f"{BASE}/admin")
    pag.fill("#email", "admin@lecsor.test")
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=10000)
    pag.wait_for_timeout(2000)
    pag.click("button.item[data-tela='analises']")
    pag.wait_for_timeout(1500)
    texto = pag.locator("#tela").inner_text()
    checar("admin vê o agente de bordo na tela de Análises", "agente-bordo-01" in texto)
    checar("admin vê modelo e quadros por segundo", "yolov10n" in texto and "Quadros/s" in texto)
    checar("admin vê contagem de pessoas", "entrou" in texto.lower() or "Entrou" in texto)
    pag.screenshot(path=str(SAIDA / "_front-admin-analises.png"))
    ctx.close()


def main() -> int:
    agente = subir_agente()   # a tela de IA precisa de um agente vivo produzindo deteccao
    time.sleep(20)
    if not SENHA:
        print("defina LECSOR_SENHA_DEMO com a senha das contas de demonstracao")
        return 2
    with sync_playwright() as p:
        # usa o Chrome instalado (o navegador empacotado do Playwright pode estar em outra versao)
        try:
            nav = p.chromium.launch(channel="chrome")
        except Exception:
            nav = p.chromium.launch()
        verificar_cliente(nav)
        verificar_admin(nav)
        verificar_analises(nav)
        nav.close()
    agente.terminate()
    print("\nRESULTADO:", "tudo passou" if not falhas else f"{len(falhas)} falha(s): " + "; ".join(falhas))
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(main())
