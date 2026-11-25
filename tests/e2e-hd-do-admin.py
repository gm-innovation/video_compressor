#!/usr/bin/env python3
"""Prova de TELA: o ADMIN acessa o gravado a bordo (0.20.0).

Palavras do dono (25/11/2026): "ainda nao consigo acessar as imagens na area do admin, precisa resolver
isso". O backend ja' atendia o admin (`/api/hd/catalogo`, `/api/hd/pedir`, `/api/hd/baixar`) e o
`admin/admin.js` tinha ZERO ocorrencias de `/api/hd/` — faltava a tela.

    python tests/e2e-hd-do-admin.py

Sobe a API de verdade (banco proprio, `--semear-demo`) e abre o Chromium do Playwright. O que se prova,
olhando a tela do admin:
  1) o menu do admin tem "Imagens gravadas a bordo" e a tela abre com o seletor de EMBARCACAO;
  2) a tabela lista os trechos que o PC de captura publicou (camera, quando, tamanho) e o resumo diz
     quantos sao;
  3) o trecho que ja' chegou em terra mostra BAIXAR e o arquivo desce inteiro;
  4) o trecho novo mostra PEDIR e o clique cria pedido de verdade no lado terra (fila do bordo);
  5) trocar a embarcacao no seletor RELE' o catalogo: sem catalogo a tela DIZ o motivo em vez de mentir
     (a gravacao continua a bordo nasce desligada);
  6) a tela nao tem erro de javascript e nao vaza segredo.
"""
from __future__ import annotations

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
SENHA = "senha-da-prova-do-hd-do-admin"
TOKEN_INGESTAO = "token-da-prova-do-hd-do-admin"
EMB_VAZIA = "emb-hd-sem-catalogo"
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
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-hd-admin-"))
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
            print("FALHA o banco de demonstracao nao tem embarcacao para o cliente interno")
            return 1
        emb_id = emb["id"]
        # a SEGUNDA embarcacao do mesmo cliente: nao publicou nada — e' ela que prova o recado honesto
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                    (EMB_VAZIA, dono["cliente_id"], "Embarcacao sem catalogo"))
        con.execute("""INSERT OR REPLACE INTO cameras
                       (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                       VALUES ('radar-01',?,'Radar de oleo','',1,1,'','','dshow','','300k')""", (emb_id,))
        agora = time.time()
        blocos = []
        for k in (0, 1, 2):
            nome = time.strftime("bloco-%Y%m%d-%H%M%S", time.localtime(agora - k * 60)) + ".mp4"
            bloco = hd / nome
            bloco.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"radar" * (2000 + k))
            blocos.append({"arquivo": nome,
                           "inicio": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora - k * 60)),
                           "bytes": bloco.stat().st_size, "fim": ""})
        resumo = {"ligada": True, "camera": "radar-01", "blocos": len(blocos),
                  "bytes": sum(b["bytes"] for b in blocos)}
        con.execute("""INSERT OR REPLACE INTO hd_catalogo (embarcacao_id,camera_id,resumo,blocos,atualizado_em)
                       VALUES (?, 'radar-01', ?, ?, ?)""",
                    (emb_id, json.dumps(resumo), json.dumps(blocos), time.strftime("%Y-%m-%dT%H:%M:%S")))
        # o mais novo ja' foi pedido e chegou: o admin ve "pronto em terra" e baixa
        pronto_nome = f"ped-9001-{blocos[0]['arquivo']}"
        (hd / pronto_nome).write_bytes((hd / blocos[0]["arquivo"]).read_bytes())
        con.execute("""INSERT OR REPLACE INTO hd_pedidos
                       (id,embarcacao_id,camera_id,arquivo,usuario_email,estado,trecho,bytes,motivo,criado_em,pronto_em)
                       VALUES ('ped-9001',?,'radar-01',?,'admin@lecsor.test','enviado',?,?,?, ?, ?)""",
                    (emb_id, blocos[0]["arquivo"], pronto_nome, (hd / pronto_nome).stat().st_size,
                     "", time.strftime("%Y-%m-%dT%H:%M:%S"), time.strftime("%Y-%m-%dT%H:%M:%S")))
        con.commit()
        con.close()

        with sync_playwright() as pw:
            nav = pw.chromium.launch(executable_path=_chromium() or None)
            pag = nav.new_context(viewport={"width": 1500, "height": 950}).new_page()
            erros: list[str] = []
            pag.on("pageerror", lambda e: erros.append(str(e)))
            entrar(pag, base, "/admin/", "admin@lecsor.test")

            menu = pag.locator(".lateral").inner_text()
            checar("o menu do admin tem 'Imagens gravadas a bordo'",
                   "Imagens gravadas a bordo" in menu, menu[:160])
            pag.click('[data-tela="hd_bordo"]')
            pag.wait_for_selector("#hd-emb", timeout=20000)
            pag.wait_for_timeout(2500)

            checar("a tela abre com o seletor de embarcacao", pag.locator("#hd-emb").count() == 1)
            opcoes = pag.locator("#hd-emb option").count()
            checar("o seletor lista as embarcacoes (>= 2, a vazia inclusive)", opcoes >= 2, f"{opcoes} opcao(oes)")
            linhas = pag.locator(".caixa-form tbody tr")
            checar("a tabela lista os 3 trechos publicados pelo PC de captura", linhas.count() == 3,
                   f"na tela: {linhas.count()}")
            nota = pag.locator(".caixa-form .nota").inner_text() if pag.locator(".caixa-form .nota").count() else ""
            checar("a nota diz quantos trechos existem", "3 trecho(s)" in nota, nota[:160])
            baixar = pag.locator('.caixa-form a[href*="/api/hd/baixar?id="]')
            checar("o trecho que ja' chegou em terra mostra BAIXAR", baixar.count() == 1, f"{baixar.count()}")
            pedir = pag.locator(".caixa-form button", has_text="pedir")
            checar("os trechos ainda no HD do barco mostram PEDIR", pedir.count() == 2, f"{pedir.count()}")

            # trocar a embarcacao RELE' o catalogo: sem catalogo, a tela diz o motivo
            pag.select_option("#hd-emb", EMB_VAZIA)
            pag.wait_for_timeout(2500)
            nota_vazia = pag.locator(".caixa-form .nota").inner_text() if pag.locator(".caixa-form .nota").count() else ""
            checar("sem catalogo a tela diz o MOTIVO (a gravacao continua nasce desligada a bordo)",
                   "nao publicou blocos" in nota_vazia or "não publicou blocos" in nota_vazia, nota_vazia[:200])
            checar("a embarcacao sem catalogo nao inventa trecho",
                   "nenhum trecho publicado" in pag.locator(".caixa-form tbody").inner_text(),
                   pag.locator(".caixa-form tbody").inner_text()[:120])

            # volta para a embarcacao com catalogo
            pag.select_option("#hd-emb", emb_id)
            pag.wait_for_timeout(2500)
            checar("voltar para a embarcacao com catalogo lista os trechos de novo",
                   pag.locator(".caixa-form tbody tr").count() == 3,
                   f"{pag.locator('.caixa-form tbody tr').count()} linha(s)")

            # o admin pede um trecho: o pedido chega de verdade no lado terra
            with pag.expect_response(lambda r: "/api/hd/pedir" in r.url) as resp:
                pag.locator(".caixa-form button", has_text="pedir").first.click()
            print("     POST /api/hd/pedir -> " + f"{resp.value.status} {resp.value.text()[:160]}")
            checar("o pedido do admin foi aceito (200/201)", resp.value.status in (200, 201),
                   str(resp.value.status))
            time.sleep(2.0)
            con = sqlite3.connect(str(banco))
            novos = con.execute("SELECT COUNT(*) FROM hd_pedidos WHERE usuario_email='admin@lecsor.test'"
                                " AND estado='pedido'").fetchone()[0]
            con.close()
            checar("o clique em PEDIR criou o pedido do ADMIN no lado terra (fila do bordo)", novos >= 1, f"{novos}")

            # e baixa o trecho pronto
            with pag.expect_download() as dl:
                baixar.first.click()
            caminho = dl.value.path()
            tamanho = pathlib.Path(caminho).stat().st_size
            esperado = (hd / blocos[0]["arquivo"]).stat().st_size
            checar("o admin BAIXOU o trecho inteiro pela tela do gravado a bordo", tamanho == esperado,
                   f"{tamanho} B x {esperado} B")
            checar("a tela nao vaza segredo",
                   "LECSOR_TOKEN" not in pag.content() and "senha_hash" not in pag.content())
            checar("a tela do gravado a bordo do admin abriu sem erro de javascript", not erros,
                   "; ".join(erros)[:160])
            nav.close()
    finally:
        api.terminate()

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — o admin escolhe a embarcacao, ve o catalogo do bordo, pede o trecho e baixa")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
