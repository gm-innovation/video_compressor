#!/usr/bin/env python3
"""Prova de TELA: a pagina unica "Gravacoes" do app do cliente (0.24.0).

Palavras do dono (26/11/2026): "as telas 'Gravacoes' e 'Radar de oleo (HD)' podem ser uma pagina
apenas 'Gravacoes'".

Sobe a API de verdade (banco proprio) e abre o Chromium do Playwright. O que se prova, olhando a tela:
  1) o menu do cliente tem UM item so' de gravacoes — nao existe mais o item "Radar de oleo (HD)" /
     "Imagens gravadas a bordo";
  2) a pagina "Gravacoes" abre com a faixa de filtro (data e hora) e com DOIS blocos: o gravado a
     bordo (HD do PC de captura) em cima e o gravado em terra embaixo;
  3) o bloco de bordo lista os trechos do HD (pedir/baixar) e o resumo diz quantos e de quando a quando;
  4) o bloco de terra lista a gravacao que chegou nas transmissoes, com o link de baixar;
  5) a tela NAO pisca: recarregar o desenho (o ciclo de 5 s) nao apaga o palco;
  6) o PEDIR continua chegando de verdade no lado terra (fila do bordo) e o BAIXAR entrega o arquivo;
  7) as outras telas de tabela (Cameras) continuam funcionando depois da troca do montador de tabela;
  8) nenhum erro de javascript.

    python tests/e2e-pagina-unica-de-gravacoes.py
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
SENHA = "senha-da-prova-da-pagina-unica"
TOKEN_INGESTAO = "token-da-prova-da-pagina-unica"
TRANS = "prova-transmissao-unica"
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


def entrar(pag, base: str, email: str) -> None:
    pag.goto(base + "/app/")
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=25000)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-pagina-unica-"))
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
    grav = tmp / "gravacoes"
    grav.mkdir(parents=True, exist_ok=True)
    try:
        con = sqlite3.connect(str(banco))
        con.row_factory = sqlite3.Row
        dono = con.execute("SELECT cliente_id FROM usuarios WHERE email='cliente@lecsor.test'").fetchone()
        emb = con.execute("SELECT id FROM embarcacoes WHERE cliente_id=? LIMIT 1",
                          (dono["cliente_id"],)).fetchone()
        if not emb:
            print("FALHA o banco de demonstracao nao tem embarcacao para o cliente")
            return 1
        emb_id = emb["id"]
        agora = time.time()

        # ---- 1) o HD do bordo: uma camera de RADAR com 3 trechos publicados
        con.execute("""INSERT OR REPLACE INTO cameras
                       (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo,
                        tipo_definido_pelo_admin)
                       VALUES ('radar-01',?,'Radar de oleo (prova)','radar-01','mastro',1,'','','dshow','',
                               '300k','radar',1)""", (emb_id,))
        blocos = []
        for k in (0, 1, 2):
            nome = time.strftime("bloco-%Y%m%d-%H%M%S", time.localtime(agora - k * 60)) + ".mp4"
            (hd / nome).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"radar" * (2000 + k))
            blocos.append({"arquivo": nome,
                           "inicio": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora - k * 60)),
                           "bytes": (hd / nome).stat().st_size})
        con.execute("""INSERT OR REPLACE INTO hd_catalogo (embarcacao_id,camera_id,resumo,blocos,atualizado_em)
                       VALUES (?, 'radar-01', ?, ?, ?)""",
                    (emb_id, json.dumps({"blocos": len(blocos)}), json.dumps(blocos),
                     time.strftime("%Y-%m-%dT%H:%M:%S")))
        # o mais novo ja' foi pedido e chegou em terra: a tela mostra "pronto em terra" e BAIXAR
        pronto_nome = "ped-0001-" + blocos[0]["arquivo"]
        (hd / pronto_nome).write_bytes((hd / blocos[0]["arquivo"]).read_bytes())
        con.execute("""INSERT OR REPLACE INTO hd_pedidos
                       (id,embarcacao_id,camera_id,arquivo,usuario_email,estado,trecho,bytes,motivo,
                        criado_em,pronto_em)
                       VALUES ('ped-0001',?,'radar-01',?,'cliente@lecsor.test','enviado',?,?,'',?,?)""",
                    (emb_id, blocos[0]["arquivo"], pronto_nome, (hd / pronto_nome).stat().st_size,
                     time.strftime("%Y-%m-%dT%H:%M:%S"), time.strftime("%Y-%m-%dT%H:%M:%S")))

        # ---- 2) o gravado EM TERRA: uma transmissao encerrada com gravacao (linha + arquivo)
        fim = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora))
        ini = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora - 180))
        con.execute("""INSERT OR REPLACE INTO transmissoes (id,seq,embarcacao_id,camera_id,fluxo_id,
                        usuario_email,segundos_max,criada_em,batimento_em,termina_em,encerrada_em,
                        estado,motivo,gravando)
                       VALUES (?,0,?,'radar-01','radar-01','cliente@lecsor.test',900,?,?,?,?,
                               'encerrada','prova da pagina unica',0)""",
                    (TRANS, emb_id, ini, ini, fim, fim))
        (grav / (TRANS + ".mp4")).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"terra" * 3000)
        con.execute("""INSERT OR REPLACE INTO gravacoes (transmissao_id,embarcacao_id,usuario_email,
                        camera_id,comecou_em,bytes,segundos,pronta_em,avisada_em,baixada_em,apagada_em)
                       VALUES (?,?,'cliente@lecsor.test','radar-01',?,?,180,?,'','','')""",
                    (TRANS, emb_id, ini, (grav / (TRANS + ".mp4")).stat().st_size, fim))
        con.commit()
        con.close()

        with sync_playwright() as pw:
            nav = pw.chromium.launch(executable_path=_chromium() or None)
            pag = nav.new_context(viewport={"width": 1500, "height": 950}).new_page()
            erros: list[str] = []
            pag.on("pageerror", lambda e: erros.append(str(e)))
            entrar(pag, base, "cliente@lecsor.test")

            print("== 1. o menu do cliente")
            menu = pag.inner_text(".lateral")
            checar("existe UM item de menu 'Gravações'", menu.count("Gravações") == 1, menu[:200])
            checar("nao existe mais o item separado do radar/HD gravado",
                   pag.locator('.lateral .item[data-tela="radar_hd"]').count() == 0
                   and "Radar de óleo (HD)" not in menu and "Imagens gravadas a bordo" not in menu,
                   menu[:200])

            print()
            print("== 2. a página única, com dois blocos")
            pag.click('.lateral .item[data-tela="gravacoes"]')
            pag.wait_for_selector("#hd-filtro:not(.oculto)", timeout=25000)
            pag.wait_for_selector("section.bloco-gravacao", timeout=25000)
            pag.wait_for_timeout(2500)
            blocos_tela = pag.locator("section.bloco-gravacao")
            checar("a página desenha DOIS blocos (bordo + terra)", blocos_tela.count() == 2,
                   f"{blocos_tela.count()} bloco(s)")
            primeiro = blocos_tela.nth(0).inner_text()
            segundo = blocos_tela.nth(1).inner_text()
            checar("o 1º bloco é o gravado a bordo (radar de óleo / HD do PC de captura)",
                   "Gravado a bordo" in primeiro and "Radar de óleo" in primeiro,
                   primeiro[:160].replace("\n", " | "))
            checar("o 2º bloco é o gravado em terra (transmissões)",
                   "Gravado em terra" in segundo, segundo[:160].replace("\n", " | "))
            checar("a faixa de filtro por data e hora está na página",
                   pag.locator("#hd-de").count() == 1 and pag.locator("#hd-ate").count() == 1)

            print()
            print("== 3. o bloco de bordo (o que era a tela 'Radar de óleo (HD)')")
            linhas_hd = blocos_tela.nth(0).locator("tbody tr")
            checar("o bloco de bordo lista os 3 trechos do HD", linhas_hd.count() == 3,
                   f"{linhas_hd.count()} linha(s)")
            resumo = pag.locator("#hd-resumo").inner_text()
            checar("o resumo conta os trechos e o intervalo", "3 trecho(s)" in resumo and " até " in resumo,
                   resumo)
            checar("o trecho que já chegou em terra mostra BAIXAR",
                   blocos_tela.nth(0).locator('a[href*="/api/hd/baixar?id="]').count() == 1)
            checar("os trechos ainda no HD do barco mostram PEDIR",
                   blocos_tela.nth(0).locator("button", has_text="pedir").count() == 2,
                   f"{blocos_tela.nth(0).locator('button', has_text='pedir').count()} botão(ões)")

            print()
            print("== 4. o bloco de terra (o que era a tela 'Gravações')")
            linhas_terra = blocos_tela.nth(1).locator("tbody tr")
            checar("o bloco de terra lista a gravação das transmissões", linhas_terra.count() == 1,
                   f"{linhas_terra.count()} linha(s)")
            baixar_terra = blocos_tela.nth(1).locator('a[href*="/api/gravacoes/"]')
            checar("a gravação de terra tem o link de baixar",
                   baixar_terra.count() == 1 and "baixar" in baixar_terra.first.inner_text().lower())

            print()
            print("== 5. a tela não pisca (o ciclo de 5 s não remonta o palco)")
            pag.evaluate("() => { const p = document.querySelector('#palco'); p.dataset.marca = 'x'; }")
            pag.wait_for_timeout(6500)
            checar("o palco sobrevive ao ciclo de atualização (não foi remontado à toa)",
                   pag.evaluate("() => document.querySelector('#palco').dataset.marca") == "x")
            checar("e os dois blocos continuam lá", pag.locator("section.bloco-gravacao").count() == 2,
                   f"{pag.locator('section.bloco-gravacao').count()}")

            print()
            print("== 6. pedir e baixar continuam funcionando na página única")
            with pag.expect_response(lambda r: "/api/hd/pedir" in r.url) as resp:
                blocos_tela.nth(0).locator("button", has_text="pedir").first.click()
            print("     POST /api/hd/pedir -> %s %s" % (resp.value.status, resp.value.text()[:120]))
            time.sleep(1.5)
            con = sqlite3.connect(str(banco))
            novos = con.execute("SELECT COUNT(*) FROM hd_pedidos WHERE estado='pedido'").fetchone()[0]
            con.close()
            checar("o clique em PEDIR criou o pedido no lado terra (fila do bordo)", novos >= 1, f"{novos}")
            with pag.expect_download() as dl:
                blocos_tela.nth(0).locator('a[href*="/api/hd/baixar?id="]').first.click()
            tamanho = pathlib.Path(dl.value.path()).stat().st_size
            checar("o BAIXAR do bloco de bordo entrega o arquivo inteiro",
                   tamanho == (hd / blocos[0]["arquivo"]).stat().st_size,
                   f"{tamanho} B x {(hd / blocos[0]['arquivo']).stat().st_size} B")

            print()
            print("== 7. as outras telas de tabela continuam funcionando")
            pag.click('.lateral .item[data-tela="cameras"]')
            pag.wait_for_selector("#palco table", timeout=25000)
            checar("a tela 'Câmeras' desenha a tabela depois da troca do montador de tabela",
                   pag.locator("#palco table tbody tr").count() >= 1,
                   f"{pag.locator('#palco table tbody tr').count()}")
            pag.click('.lateral .item[data-tela="gravacoes"]')
            pag.wait_for_selector("section.bloco-gravacao", timeout=25000)
            checar("voltar para 'Gravações' volta com os dois blocos",
                   pag.locator("section.bloco-gravacao").count() == 2)
            checar("a página única não tem erro de javascript", not erros, "; ".join(erros)[:200])
            nav.close()
    finally:
        api.terminate()

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — 'Gravações' é uma página só, com o gravado a bordo e o gravado em terra")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
