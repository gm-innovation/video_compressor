#!/usr/bin/env python3
"""J5 — Gravação: o cliente grava, é avisado, baixa e, ao sair, o arquivo é apagado (o histórico fica).

A regra do dono (19/11/2026), palavra por palavra: *"ao final da gravação, precisa avisar ao cliente
para ele fazer o download do vídeo; quando ele desligar o sistema ou sair da tela os arquivos serão
apagados"* — e o "nada é apagado" é o **histórico**: a linha da gravação e a trilha de auditoria ficam.

Ação do usuário, em navegador real: o cliente pede a transmissão (o fluxo sobe de verdade, pelo bordo),
clica em GRAVAR, depois em PARAR, lê o aviso, baixa o arquivo e SAI da tela.

Medida: os bytes e os segundos da gravação, o vídeo que o cliente baixou (quem lê é o ffprobe), o
apagamento no disco com o tempo que levou e as ações na trilha de auditoria.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import FFPROBE, sql  # noqa: E402
from relatorio import Jornada  # noqa: E402

TEMPO_GRAVANDO_S = 6.0
LIMITE_APAGAR_S = 25.0
ACOES_ESPERADAS = ("gravacao_iniciada", "gravacao_parada", "gravacao_avisada", "gravacao_baixada",
                   "gravacoes_apagadas")


def _estado(pagina, cam: str) -> str:
    try:
        return pagina.locator(f'[data-estado="{cam}"]').inner_text().strip()
    except Exception:  # noqa: BLE001
        return ""


def _espera_estado(pagina, cam: str, pedaco: str, limite_s: float = 60.0) -> str:
    fim = time.time() + limite_s
    texto = ""
    while time.time() < fim:
        texto = _estado(pagina, cam)
        if pedaco.lower() in texto.lower():
            return texto
        time.sleep(0.5)
    return texto


def _espera_texto(pagina, seletor: str, limite_s: float = 30.0) -> str:
    """Espera o elemento existir e devolve o texto dele (o botao vira 'Parar gravacao' gravando)."""
    fim = time.time() + limite_s
    texto = ""
    while time.time() < fim:
        try:
            texto = pagina.locator(seletor).inner_text()
            if texto.strip():
                return texto
        except Exception:  # noqa: BLE001
            texto = ""
        time.sleep(0.4)
    return texto


def _espera_botao(pagina, seletor: str, pedaco: str, limite_s: float = 30.0) -> str:
    """Espera o TEXTO do botao virar o pedaco esperado (o botao passa por 'gravando...' antes de
    'Parar gravacao' — devolver o primeiro texto nao-nulo leria o meio do caminho).

    Desde 24/11/2026 os botoes da GRADE sao ICONES com o nome completo no `title`/`aria-label`; por
    isso a espera le' o TEXTO junto do NOME ACESSIVEL.
    """
    fim = time.time() + limite_s
    texto = ""
    while time.time() < fim:
        try:
            e = pagina.locator(seletor).first
            texto = ((e.inner_text() or '') + ' ' + (e.get_attribute("title") or '') + ' '
                     + (e.get_attribute("aria-label") or ''))
        except Exception:  # noqa: BLE001
            texto = ""
        if pedaco.lower() in texto.lower():
            return texto
        time.sleep(0.4)
    return texto


def _video_de_verdade(caminho: pathlib.Path) -> tuple[bool, str]:
    """Quem le' o arquivo e' o ffprobe: e' a unica prova de que o cliente baixou VIDEO."""
    if not FFPROBE.exists():
        return False, "ffprobe do produto nao encontrado"
    r = subprocess.run([str(FFPROBE), "-v", "error", "-print_format", "json", "-show_streams",
                        str(caminho)], capture_output=True, timeout=40)
    try:
        info = json.loads((r.stdout or b"{}").decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return False, "ffprobe nao devolveu JSON"
    for s in info.get("streams") or []:
        if s.get("codec_type") == "video":
            return True, f"{s.get('codec_name')} {s.get('width')}x{s.get('height')}"
    return False, "sem trilha de video"


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(5, "O cliente grava, baixa e o arquivo some quando ele sai",
                "gravacao real, aviso para baixar, download pela web e o arquivo apagado na saida "
                "(o historico e a trilha ficam)")
    cam = ctx.get("camera") or "cam-01"
    amb.camera_do_bordo(cam)
    navegador = ctx.get("navegador")
    if navegador is None:
        j.erro = "sem navegador no contexto"
        return j

    ctxx = navegador.new_context(viewport={"width": 1500, "height": 900}, accept_downloads=True)
    pagina = ctxx.new_page()
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("dialog", lambda d: d.accept())
    try:
        # ------------------------------------------------------- 1) o cliente poe a transmissao no ar
        pagina.goto(amb.terra + "/app/", wait_until="domcontentloaded")
        pagina.fill("#email", "cliente@lecsor.test")
        pagina.fill("#senha", __import__("ambiente").senha_de_demo())
        pagina.click("form#form-entrar button[type=submit]")
        pagina.wait_for_selector("#sistema:not(.oculto)", timeout=25000)
# PLANO UNICO (25/11/2026): a tela "Transmitir" saiu do cliente - o controle de transmissao
        # (iniciar/parar/contagem/gravar) mora na GRADE, no quadro de cada camera. O cliente ja'
        # cai nessa tela ao entrar; o botao do quadro e' o `[data-papel="iniciar"]`.
        pagina.wait_for_selector(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]', timeout=20000)
        pagina.click(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]')
        no_ar = _espera_estado(pagina, cam, "no ar", 60.0)
        tem_fluxo = amb.fluxo_no_ar(cam, segundos=60)
        j.checar("a transmissao esta' no ar (com fluxo de verdade do bordo) para o cliente gravar",
                 "no ar" in no_ar.lower() and tem_fluxo, f"tela: {no_ar[:60]!r} · fluxo no ar: {tem_fluxo}")
        if not tem_fluxo:
            j.erro = "sem fluxo no lado terra: nao ha' o que gravar"
            return j

        # ------------------------------------------------------- 2) GRAVA (e a tela diz que grava)
        # PLANO UNICO (25/11/2026): a tela "Transmitir" saiu — o controle (iniciar/parar/gravar) mora no
        # quadro de cada camera, dentro da janela da GRADE.
        botao = f'.janela[data-cam="{cam}"] [data-papel="gravar"]'
        j.checar("a tela do cliente oferece GRAVAR aquela transmissao",
                 pagina.locator(botao).count() > 0, botao)
        if pagina.locator(botao).count() == 0:
            j.erro = "sem botao de gravar na tela"
            return j
        pagina.click(botao)
        texto_gravando = _espera_botao(pagina, botao, "parar", 30.0)
        j.checar("a tela diz que esta' GRAVANDO", "parar" in texto_gravando.lower(), texto_gravando[:60])
        time.sleep(TEMPO_GRAVANDO_S)
        pagina.click(botao)
        # ---------------------------------------------- 3) o AVISO ao cliente (regra do dono)
        aviso = _espera_texto(pagina, "#aviso-gravacao", 30.0).lower()
        j.checar("o cliente e' AVISADO de que a gravacao ficou pronta", "baixe agora" in aviso,
                 aviso[:90])
        j.checar("o aviso diz que o arquivo e' apagado quando ele sair",
                 "apagado quando você sair" in aviso, aviso[:140])

        linha = sql(amb.banco_terra,
                    "SELECT transmissao_id, bytes, segundos, pronta_em, avisada_em FROM gravacoes "
                    "ORDER BY comecou_em DESC LIMIT 1")
        if not linha:
            j.erro = "o lado terra nao registrou gravacao nenhuma"
            return j
        tid = str(linha[0]["transmissao_id"])
        bytes_g = int(linha[0]["bytes"] or 0)
        segundos_g = float(linha[0]["segundos"] or 0)
        j.medir(gravacao_id=tid, bytes_gravados=bytes_g, segundos_gravados=segundos_g)
        j.checar("a gravacao tem tamanho e a trilha marca pronto + avisado",
                 bytes_g > 0 and bool(linha[0]["pronta_em"]) and bool(linha[0]["avisada_em"]),
                 f"{bytes_g} B em {segundos_g:.1f}s de gravacao")
        arquivo = amb.gravacoes / f"{tid}.mp4"
        j.checar("o arquivo da gravacao esta' no disco do lado terra", arquivo.exists(), str(arquivo))

        # ---------------------------------------------- 4) o cliente BAIXA pela web (sem instalar nada)
        pagina.wait_for_selector(f"#baixar-{tid}", timeout=25000)
        with pagina.expect_download(timeout=60000) as espera:
            pagina.click(f"#baixar-{tid}")
        destino = amb.tmp / "baixado-pelo-smoke.mp4"
        espera.value.save_as(str(destino))
        eh_video, detalhe = _video_de_verdade(destino)
        baixados = destino.stat().st_size if destino.exists() else 0
        j.medir(bytes_baixados=baixados, video_baixado=detalhe)
        j.checar("o cliente BAIXOU o arquivo pela web", baixados > 0, f"{baixados} B")
        j.checar("e o que ele baixou e' VIDEO de verdade (quem le' e' o ffprobe)", eh_video, detalhe)
        trilha_baixou = sql(amb.banco_terra, "SELECT baixada_em FROM gravacoes WHERE transmissao_id=?",
                            (tid,))
        j.checar("a trilha registra que ele baixou", bool(trilha_baixou and trilha_baixou[0]["baixada_em"]),
                 str(trilha_baixou[0]["baixada_em"] if trilha_baixou else "sem baixada_em"))

        # ---------------------------------------------- 5) o cliente SAI: o arquivo some, a trilha fica
        t0 = time.time()
        pagina.goto("about:blank", wait_until="domcontentloaded")
        while time.time() - t0 < LIMITE_APAGAR_S and arquivo.exists():
            time.sleep(0.5)
        apagou_em = round(time.time() - t0, 1)
        j.medir(segundos_ate_apagar=apagou_em)
        j.checar("saindo da tela, o ARQUIVO e' apagado no disco", not arquivo.exists(),
                 f"apagado em {apagou_em}s" if not arquivo.exists() else f"ainda existe: {arquivo}")
        depois = sql(amb.banco_terra,
                     "SELECT apagada_em, baixada_em FROM gravacoes WHERE transmissao_id=?", (tid,))
        j.checar("a LINHA da gravacao continua (nao se apaga historico)",
                 bool(depois and depois[0]["apagada_em"] and depois[0]["baixada_em"]),
                 f"apagada_em={depois[0]['apagada_em'] if depois else '-'}")

        acoes = [r[0] for r in sql(amb.banco_terra,
                                   "SELECT acao FROM auditoria_acesso WHERE alvo LIKE ? ORDER BY id",
                                   (f"%{cam}%",))]
        faltando = [a for a in ACOES_ESPERADAS if a not in acoes]
        j.medir(auditoria=sorted(set(acoes)))
        j.checar("a auditoria guarda o que foi feito e por quem (gravar, avisar, baixar, apagar)",
                 not faltando, f"faltando: {faltando}" if faltando else f"{len(set(acoes))} acoes")
        j.checar("a tela nao deu erro de javascript", not erros, "; ".join(erros[:2]))
    finally:
        try:
            ctxx.close()
        except Exception:  # noqa: BLE001
            pass
    return j
