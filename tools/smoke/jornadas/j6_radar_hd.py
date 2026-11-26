#!/usr/bin/env python3
"""J6 — O radar de oleo: HD gravando full time e o cliente baixando o trecho.

Acao do usuario: o cliente abre o "Radar de oleo (HD)" e clica em PEDIR num trecho.

Efeito medido, ponta a ponta: o HD do PC de captura grava o radar de oleo DIRETO (ninguem pediu
nada), o agente do bordo publica o catalogo no lado terra, o cliente VE o catalogo na tela, pede o
trecho, o BORDO envia o bloco (o bordo nao abre porta: ele olha a fila do lado terra) e o cliente
BAIXA o arquivo inteiro.

O que e' de verdade aqui: o daemon de gravacao continua do produto (`ground/gravacao_continua.py`,
gravando de um dispositivo de video real desta maquina), o agente do produto, o SQLite, o HTTP e o
Chromium. Sem dispositivo de video nesta maquina, a jornada fica NAO MEDIDA — nunca "OK".
"""
from __future__ import annotations

import pathlib
import sys
import time
from typing import cast

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import pedir, senha_de_demo, sql  # noqa: E402
from relatorio import Jornada  # noqa: E402

CAM = "radar-01"
LIMITE_HD_S = 40.0        # o HD grava um bloco deste tamanho em segundos (2 s), com folga
LIMITE_CATALOGO_S = 90.0  # o agente publica o catalogo a cada rodada
LIMITE_ENVIO_S = 90.0     # o bordo olha a fila de pedidos a cada rodada


def _catalogo(terra: str, sessao: str, camera: str = CAM) -> dict:
    codigo, r = pedir("GET", f"{terra}/api/hd/catalogo?camera_id={camera}", sessao=sessao)
    if codigo != 200 or not isinstance(r, dict):
        return {}
    catalogos = r.get("catalogos") or []
    if catalogos and isinstance(catalogos[0], dict):
        return cast(dict, catalogos[0])
    return {}


def _espera(condicao, segundos: float):
    """Espera de verdade: o relogio e' o limite, nao um `sleep` chutado."""
    fim = time.time() + segundos
    ultimo = None
    while time.time() < fim:
        try:
            ultimo = condicao()
            if ultimo:
                return ultimo
        except Exception:  # noqa: BLE001
            ultimo = None
        time.sleep(0.7)
    return ultimo


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(6, "O radar de oleo: HD full time e o trecho na tela do cliente",
                "o cliente ve e baixa as imagens do radar de oleo sem o bordo abrir porta nenhuma")
    navegador = ctx.get("navegador")
    if navegador is None:
        j.erro = "sem navegador no contexto"
        return j

    # ---------------------------------------------------------------- 1) o HD grava full time
    disp = amb.dispositivo_do_radar()
    j.checar("esta maquina tem dispositivo de video para o HD do radar", bool(disp),
             disp or "nenhum dispositivo dshow (o HD do radar nao pode ser medido aqui)", medido=True)
    if not disp:
        return j
    j.medir(dispositivo=disp)

    amb.camera_do_bordo(CAM)                       # o radar no banco do bordo (idempotente)
    amb.publicar_camera_no_terra(CAM)              # e o cadastro ao lado terra, pelo caminho do produto
    if not amb.subir_hd_do_radar(dispositivo=disp, camera=CAM, bloco_segundos=2):
        j.erro = "o HD do radar nao subiu"
        return j
    # O AGENTE e' quem publica o catalogo: precisa subir com o ambiente do HD (grelhado/fiado na
    # bancada — sem isto o agente nao enxerga a gravacao e o catalogo sai vazio).
    if not amb.reiniciar_agente():
        j.erro = "nao consegui subir o agente com o HD do radar ligado"
        return j

    t0 = time.time()
    blocos = _espera(lambda: amb.blocos_no_hd() or None, LIMITE_HD_S)
    segundos_ate_1o = round(time.time() - t0, 1)
    blocos = amb.blocos_no_hd()
    bytes_no_hd = sum(b.stat().st_size for b in blocos)
    j.medir(blocos_no_hd=len(blocos), bytes_no_hd=bytes_no_hd, segundos_ate_o_1o_bloco=segundos_ate_1o)
    j.checar("o HD do radar grava full time, sem ninguem pedir", bool(blocos),
             f"{len(blocos)} bloco(s), {bytes_no_hd} B em {segundos_ate_1o}s")

    # ------------------------------------------------- 2) o agente publica o catalogo em terra
    sessao = amb.entrar("cliente@lecsor.test")
    if not sessao:
        j.erro = "nao consegui entrar como cliente no lado terra"
        return j

    t0 = time.time()
    cat = _espera(lambda: (_catalogo(amb.terra, sessao) or {}).get("blocos") or None, LIMITE_CATALOGO_S)
    destacado = j.checar("o agente publica o catalogo do HD no lado terra", bool(cat),
                         f"{len(cat or [])} bloco(s) no catalogo em {round(time.time() - t0, 1)}s "
                         f"(o bordo so' olha a fila: nada sai de terra para o bordo)")
    if not destacado:
        return j
    j.medir(blocos_no_catalogo=len(cat or []))

    # ------------------------------------------------- 3) o cliente ve, pede e baixa (a tela real)
    ctxx = navegador.new_context(viewport={"width": 1500, "height": 950}, accept_downloads=True)
    pagina = ctxx.new_page()
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("dialog", lambda d: d.accept())
    try:
        pagina.goto(f"{amb.terra}/app/")
        pagina.fill("#email", "cliente@lecsor.test")
        pagina.fill("#senha", senha_de_demo())
        pagina.click("form#form-entrar button[type=submit]")
        pagina.wait_for_selector("#sistema:not(.oculto)", timeout=25000)
        pagina.click('[data-tela="gravacoes"]')
        pagina.wait_for_selector("#hd-filtro:not(.oculto)", timeout=25000)
        # RODADA 0.24.0: "Gravacoes" e' uma pagina SO' — o bloco do bordo (HD do PC de captura) em cima
        # e o gravado em terra embaixo. Os dois testes abaixo falam do bloco do BORDO (o 1o).
        pagina.wait_for_selector("section.bloco-gravacao", timeout=25000)
        j.checar("a pagina unica 'Gravacoes' abre com o gravado a bordo e o gravado em terra",
                 pagina.locator("section.bloco-gravacao").count() == 2,
                 f"{pagina.locator('section.bloco-gravacao').count()} bloco(s)")
        bloco_bordo = lambda: pagina.locator("section.bloco-gravacao").nth(0)  # noqa: E731

        # A tabela nasce com uma linha de "carregando": contar linha nao prova NADA. O que prova e' o
        # resumo dizer quantos trechos existem (o app so' escreve isso DEPOIS de o catalogo chegar).
        linhas, resumo = 0, ""
        fim = time.time() + 30
        while time.time() < fim:
            try:
                resumo = pagina.locator("#hd-resumo").inner_text()
            except Exception:  # noqa: BLE001
                resumo = ""
            linhas = bloco_bordo().locator("tbody tr").count()
            if "trecho(s)" in resumo and linhas >= 1:
                break
            pagina.wait_for_timeout(700)
        j.checar("o cliente VE o catalogo do HD na tela", "trecho(s)" in resumo and linhas >= 1,
                 f"{linhas} linha(s) · {resumo[:90]}")

        pedir_btn = bloco_bordo().locator("button", has_text="pedir")
        j.checar("o trecho que ainda esta' no HD do barco mostra PEDIR", pedir_btn.count() >= 1,
                 f"{pedir_btn.count()} botao(oes) PEDIR")
        if pedir_btn.count() == 0:
            return j

        with pagina.expect_response(lambda r: "/api/hd/pedir" in r.url, timeout=30000) as resp:
            pedir_btn.first.click()
        codigo_pedido = resp.value.status
        j.checar("o cliente PEDE o trecho pela tela (o pedido nasce no lado terra)", codigo_pedido == 201,
                 f"HTTP {codigo_pedido} · {resp.value.text()[:120]}")

        fila = _espera(lambda: [dict(r) for r in sql(amb.banco_terra,
                                                    "SELECT id,estado,bytes FROM hd_pedidos "
                                                    "ORDER BY rowid DESC LIMIT 1")] or None, 20.0)
        estado_do_pedido = (fila or [{}])[0].get("estado", "")
        j.checar("o pedido fica na fila do bordo (quem envia e' o bordo, nao terra)", bool(fila),
                 f"estado na fila: {estado_do_pedido or 'nenhum'}")

        enviado = _espera(lambda: [dict(r) for r in sql(amb.banco_terra,
                                                       "SELECT id,estado,bytes FROM hd_pedidos "
                                                       "WHERE estado='enviado' ORDER BY rowid DESC LIMIT 1")] or None,
                          LIMITE_ENVIO_S)
        bytes_enviados = (enviado or [{}])[0].get("bytes") or 0
        j.checar("o BORDO enviou o bloco (ele olhou a fila do lado terra)", bool(enviado),
                 f"{len(enviado or [])} pedido(s) enviado(s) · {bytes_enviados} B")
        j.medir(bytes_enviados=bytes_enviados)
        if not enviado:
            return j

        # a tela troca PEDIR por BAIXAR quando o trecho chega; o download e' o que fecha a conta.
        # A tela NAO se atualiza sozinha: quem faz o que o cliente faria e' reabrir a tela de gravacoes
        # (na pagina unica, o ciclo de 5 s do palco tambem repinta o bloco do bordo).
        link = bloco_bordo().locator('a[href*="/api/hd/baixar?id="]')
        fim = time.time() + 40
        while time.time() < fim and link.count() == 0:
            pagina.click('[data-tela="gravacoes"]')
            pagina.wait_for_timeout(2500)
            link = bloco_bordo().locator('a[href*="/api/hd/baixar?id="]')
        j.checar("a tela do cliente mostra BAIXAR quando o trecho chega em terra", link.count() >= 1,
                 f"{link.count()} link(s) BAIXAR")
        if link.count() >= 1:
            with pagina.expect_download(timeout=30000) as dl:
                link.first.click()
            caminho = pathlib.Path(dl.value.path())
            baixados = caminho.stat().st_size
            j.medir(bytes_baixados=baixados)
            j.checar("o cliente BAIXOU o trecho inteiro pela tela do HD", baixados > 0,
                     f"{baixados} B baixados (o bloco no HD tem {blocos[0].stat().st_size} B)")
        j.checar("a pagina unica 'Gravacoes' do cliente abriu sem erro de javascript", not erros,
                 "; ".join(erros)[:160])
    finally:
        try:
            ctxx.close()
        except Exception:  # noqa: BLE001
            pass
    return j
