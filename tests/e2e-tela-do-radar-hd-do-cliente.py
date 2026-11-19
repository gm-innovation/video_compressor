#!/usr/bin/env python3
"""Prova de TELA: o CLIENTE ve o HD do radar, procura por data e hora, PEDE o trecho e BAIXA (0.7.0).

Palavras do dono (19/11/2026): "mesmo que o cliente nao acione o streaming do radar de oleo, as imagens
estarao sendo comprimidas e gravadas full time, o cliente pode acessar as imagens a qualquer momento" e
"o cliente vai procurar na linha do tempo de acordo com data e hora, podendo ser por filtro ou linha do
tempo arrastavel".

    python tests/e2e-tela-do-radar-hd-do-cliente.py

Sobe a API de verdade (banco proprio) e abre o Chromium do Playwright. O que se prova, olhando a tela:
  1) o menu do cliente tem "Radar de oleo (HD)" e a tela abre com a faixa de filtro (data e hora);
  2) a tabela lista os trechos que o PC de captura publicou (horario + tamanho), do mais novo para o mais
     antigo, e o resumo diz quantos sao e de quando ate' quando;
  3) o filtro por data e hora ESTREITA a lista (o cliente procura pelo horario que quer);
  4) o trecho que ele ja' pediu aparece "pronto em terra" e BAIXA (o arquivo chega inteiro);
  5) o trecho novo tem o botao PEDIR, e o clique vira pedido de verdade no lado terra (fila do bordo);
  6) a tela nao tem erro de javascript.
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
SENHA = "senha-da-prova-do-radar-070"
TOKEN_INGESTAO = "token-da-prova-do-radar"
falhas: list[str] = []


def checar(texto: str, cond, detalhe: str = "") -> None:
    print(("OK   " if cond else "FALHA ") + texto + (f" — {detalhe}" if detalhe and not cond else ""))
    if not cond:
        falhas.append(texto)


def _chromium() -> str:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else ""


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def entrar(pag, base: str, raiz: str, email: str) -> None:
    pag.goto(base + raiz)
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=20000)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-tela-hd-"))
    banco = tmp / "pipeline.db"
    env = dict(os.environ)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_SENHA_DEMO": SENHA,
                "LECSOR_TOKEN_INGESTAO": TOKEN_INGESTAO,
                "LECSOR_GRAVACOES_DIR": str(tmp / "gravacoes"), "PYTHONIOENCODING": "utf-8"})
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_EMBARCACAO"):
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
        except Exception:
            time.sleep(0.5)
    if not pronto:
        print("FALHA a API nao subiu:", (tmp / "api.log").read_text(errors="replace")[-500:])
        api.terminate()
        return 1

    hd = tmp / "gravacoes" / "hd"
    hd.mkdir(parents=True, exist_ok=True)
    try:
        con = sqlite3.connect(str(banco))
        con.row_factory = sqlite3.Row
        dono = con.execute("SELECT cliente_id FROM usuarios WHERE email='cliente@lecsor.test'").fetchone()
        emb = con.execute("SELECT id FROM embarcacoes WHERE cliente_id=? LIMIT 1", (dono["cliente_id"],)).fetchone()
        if not emb:
            print("FALHA o banco de demonstracao nao tem embarcacao para o cliente")
            return 1
        emb_id = emb["id"]
        con.execute("""INSERT OR REPLACE INTO cameras
                       (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                       VALUES ('radar-01',?,'Radar de oleo','',1,1,'','','dshow','','300k')""", (emb_id,))
        agora = time.time()
        blocos = []
        for k in (0, 1, 2):
            nome = time.strftime("bloco-%Y%m%d-%H%M%S", time.localtime(agora - k * 60)) + ".mp4"
            bloco = hd / nome
            bloco.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"radar" * (2000 + k))
            blocos.append({"arquivo": nome, "inicio": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                                    time.localtime(agora - k * 60)),
                           "bytes": bloco.stat().st_size, "fim": ""})
        resumo = {"ligada": True, "camera": "radar-01", "blocos": len(blocos),
                  "bytes": sum(b["bytes"] for b in blocos)}
        con.execute("""INSERT OR REPLACE INTO hd_catalogo (embarcacao_id,camera_id,resumo,blocos,atualizado_em)
                       VALUES (?, 'radar-01', ?, ?, ?)""",
                    (emb_id, json.dumps(resumo), json.dumps(blocos), time.strftime("%Y-%m-%dT%H:%M:%S")))
        # o mais novo ja' foi pedido e chegou: o cliente ve "pronto em terra" e baixa
        pronto_nome = f"ped-0001-{blocos[0]['arquivo']}"
        (hd / pronto_nome).write_bytes((hd / blocos[0]["arquivo"]).read_bytes())
        con.execute("""INSERT OR REPLACE INTO hd_pedidos
                       (id,embarcacao_id,camera_id,arquivo,usuario_email,estado,trecho,bytes,motivo,criado_em,pronto_em)
                       VALUES ('ped-0001',?,'radar-01',?,'cliente@lecsor.test','enviado',?,?,?, ?, ?)""",
                    (emb_id, blocos[0]["arquivo"], pronto_nome, (hd / pronto_nome).stat().st_size,
                     "", time.strftime("%Y-%m-%dT%H:%M:%S"), time.strftime("%Y-%m-%dT%H:%M:%S")))
        con.commit()
        con.close()

        with sync_playwright() as pw:
            nav = pw.chromium.launch(executable_path=_chromium() or None)
            pag = nav.new_context(viewport={"width": 1500, "height": 950}).new_page()
            erros: list[str] = []
            pag.on("pageerror", lambda e: erros.append(str(e)))
            entrar(pag, base, "/app/", "cliente@lecsor.test")

            menu = pag.locator(".lateral").inner_text()
            checar('o menu do cliente tem "Radar de óleo (HD)"', "Radar de óleo (HD)" in menu, menu[:120])
            pag.click('[data-tela="radar_hd"]')
            pag.wait_for_selector("#hd-filtro:not(.oculto)", timeout=20000)
            pag.wait_for_timeout(2500)

            checar("a faixa de filtro por data e hora está na tela",
                   pag.locator("#hd-de").count() == 1 and pag.locator("#hd-ate").count() == 1)
            linhas = pag.locator("#palco tbody tr")
            checar("a tabela lista os 3 trechos que o PC de captura publicou", linhas.count() == 3,
                   f"na tela: {linhas.count()}")
            resumo_txt = pag.locator("#hd-resumo").inner_text()
            checar("o resumo diz quantos trechos existem e de quando até quando",
                   "3 trecho(s)" in resumo_txt and " até " in resumo_txt, resumo_txt)
            baixar = pag.locator('#palco a[href*="/api/hd/baixar?id="]')
            checar("o trecho que já chegou em terra mostra BAIXAR", baixar.count() == 1,
                   f"{baixar.count()} link(s)")
            pedir = pag.locator("#palco button", has_text="pedir")
            checar("os trechos ainda no HD do barco mostram PEDIR", pedir.count() == 2,
                   f"{pedir.count()} botão(ões)")

            # o cliente procura por um horário: o filtro estreita a lista
            hoje = time.strftime("%Y-%m-%dT%H:%M", time.localtime(agora))
            pag.fill("#hd-de", hoje)
            pag.click("#hd-filtrar")
            pag.wait_for_timeout(800)
            checar("o filtro por data e hora estreita a lista",
                   pag.locator("#palco tbody tr").count() < 3,
                   f"na tela: {pag.locator('#palco tbody tr').count()}")
            pag.click("#hd-tudo")
            pag.wait_for_timeout(800)

            # o cliente pede um trecho: o pedido chega de verdade no lado terra
            with pag.expect_response(lambda r: "/api/hd/pedir" in r.url) as resp:
                pag.locator("#palco button", has_text="pedir").first.click()
            nota_pedido = f"{resp.value.status} {resp.value.text()[:160]}"
            print("     POST /api/hd/pedir -> " + nota_pedido)
            time.sleep(2.0)
            con = sqlite3.connect(str(banco))
            novos = con.execute("SELECT COUNT(*) FROM hd_pedidos WHERE estado='pedido'").fetchone()[0]
            con.close()
            checar("o clique em PEDIR criou o pedido no lado terra (fila do bordo)", novos >= 1, f"{novos}")

            # e baixa o trecho pronto
            with pag.expect_download() as dl:
                baixar.first.click()
            caminho = dl.value.path()
            tamanho = pathlib.Path(caminho).stat().st_size
            esperado = (hd / blocos[0]["arquivo"]).stat().st_size
            checar("o cliente BAIXOU o trecho inteiro pela tela do HD", tamanho == esperado,
                   f"{tamanho} B x {esperado} B")
            checar("a tela do radar abriu sem erro de javascript", not erros, "; ".join(erros)[:160])
            nav.close()
    finally:
        api.terminate()

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — a tela do cliente mostra o HD do radar, filtra por data e hora, pede o trecho e baixa")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())