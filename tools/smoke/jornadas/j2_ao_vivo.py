#!/usr/bin/env python3
"""J2 — O cliente pede e a camera sobe (o caminho inteiro, com midia de verdade).

Acao do usuario: o cliente entra na web e clica "Iniciar transmissao".
Efeito: o lado terra publica o DESEJO -> o bordo olha a flag e liga a camera -> o ffmpeg do produto
publica em SRT -> o mediamtx do lado terra entrega -> a imagem aparece na tela do cliente.
Medida: fps recebidos, banda (Mbps), latencia do caminho e o tempo de subida (clique -> no ar).
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import PORTA_RTSP, pedir, sql, token_do_bordo  # noqa: E402
from medidor import medir_fluxo, tela_do_cliente  # noqa: E402
from relatorio import Jornada  # noqa: E402

PISO_FPS = 27.0      # alvo do produto = 30 fps; 27 = 10% de folga de medida (fonte de 30 fps)


def _estado_da_tela(pagina, cam: str) -> str:
    try:
        return pagina.locator(f'[data-estado="{cam}"]').inner_text().strip()
    except Exception:  # noqa: BLE001
        return ""


def _espera_estado(pagina, cam: str, pedaco: str, limite_s: float = 60.0) -> str:
    fim = time.time() + limite_s
    texto = ""
    while time.time() < fim:
        texto = _estado_da_tela(pagina, cam)
        if pedaco.lower() in texto.lower():
            return texto
        time.sleep(0.5)
    return texto


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(2, "O cliente pede e a camera sobe",
                "acao de usuario -> flag no lado terra -> o bordo obedece -> imagem na tela")
    cam = ctx.get("camera") or "cam-01"
    # A camera do barco precisa existir no banco do BORDO com a fonte desta bancada. O J1 ja' faz
    # isso; repetir aqui deixa a jornada valer SOZINHA (e' idempotente: so' reescreve a fonte).
    amb.camera_do_bordo(cam)
    navegador = ctx.get("navegador")
    if navegador is None:
        j.erro = "sem navegador no contexto"
        return j

    ctxx = navegador.new_context(viewport={"width": 1500, "height": 900})
    pagina = ctxx.new_page()
    erros: list[str] = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("dialog", lambda d: d.accept())
    ctx["contexto_do_cliente"] = ctxx
    ctx["pagina_do_cliente"] = pagina

    # 1) o cliente entra
    pagina.goto(amb.terra + "/app/", wait_until="domcontentloaded")
    pagina.fill("#email", "cliente@lecsor.test")
    pagina.fill("#senha", __import__("ambiente").senha_de_demo())
    pagina.click("form#form-entrar button[type=submit]")
    pagina.wait_for_selector("#sistema:not(.oculto)", timeout=25000)
    j.checar("o cliente entra na web", True, "tela do cliente no ar")

    # 2) a camera do barco esta' na lista dele e ele PEDE a transmissao
# PLANO UNICO (25/11/2026): a tela "Transmitir" saiu do cliente - o controle de transmissao
    # (iniciar/parar/contagem/gravar) mora na GRADE, no quadro de cada camera. O cliente ja'
    # cai nessa tela ao entrar; o botao do quadro e' o `[data-papel="iniciar"]`.
    pagina.wait_for_selector(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]', timeout=20000)
    j.checar("a camera do barco aparece para o cliente", pagina.locator(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]').count() > 0,
             f"botao de iniciar da camera {cam}")
    t_clique = time.time()
    pagina.click(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]')
    pedido = _espera_estado(pagina, cam, "pedido", 20.0) or _estado_da_tela(pagina, cam)
    j.checar("o pedido sai da tela do cliente", "pedido" in pedido.lower() or "chegando" in pedido.lower(),
             f"estado na tela: {pedido[:70]!r}")

    # 3) o DESEJO chegou ao lado terra e o BORDO leu a flag (rota real do agente)
    codigo, r = pedir("GET", f"{amb.terra}/api/estado-desejado?embarcacao_id={amb.embarcacao}",
                      token=token_do_bordo())
    desejos = (r or {}).get("cameras") or []
    alvo = [d for d in desejos if str(d.get("camera_id")) == cam]
    j.checar("o lado terra publica o desejo de LIGAR aquela camera",
             codigo == 200 and bool(alvo) and str(alvo[0].get("desejo")) == "ligar",
             f"HTTP {codigo} · {alvo[0] if alvo else desejos[:2]}")

    # 4) o efeito real: a midia do bordo esta' no mediamtx do lado terra (quem responde e' o ffprobe)
    subiu = amb.fluxo_no_ar(cam, segundos=60)
    t_publicacao = time.time()
    j.checar("a midia do bordo chega ao lado terra (fluxo publicado)", subiu,
             f"rtsp://127.0.0.1:{PORTA_RTSP}/{cam}")
    if not subiu:
        j.medir(cauda_do_bordo=amb.log_de("agente", 1200), cauda_do_mediamtx=amb.log_de("mediamtx", 600))
        return j

    # 5) medidas do caminho: fps, banda e latencia
    m = medir_fluxo(f"rtsp://127.0.0.1:{PORTA_RTSP}/{cam}", segundos=8.0, t_publicacao=t_publicacao)
    j.medir(**m)
    j.checar("a fonte entrega em TEMPO REAL (a entrega nao e' mais rapida que a propria midia)",
             m.get("tempo_real") is True,
             f"entrega {m['fps_entrega']} q/s · midia {m['fps_midia']} q/s"
             + ("" if m.get("tempo_real") else " — a fonte esta' produzindo mais rapido que o tempo real"))
    j.checar(f"o fluxo carrega quadros na taxa do produto (medido: {m['fps_midia']} fps)",
             m["fps_midia"] >= PISO_FPS,
             f"{m['quadros']} quadros / {m['segundos_de_midia']}s de midia · alvo 30 fps "
             f"(piso de medida {PISO_FPS})")
    j.checar("a banda do caminho e' medida e nao e' zero", m["mbps"] > 0.2,
             f"{m['mbps']} Mbps ({m['bytes']} bytes contados no cano)")
    lat = m.get("latencia_s")
    if lat is not None and float(lat) >= 0:
        j.checar("a latencia do caminho respeita o alvo do produto (<= 3 s)", float(lat) <= 3.0,
                 f"{lat} s")
        ctx["latencia_s"] = lat
    else:
        j.checar("a latencia do caminho foi medida (numero utilizavel)", False,
                 f"medida devolveu {lat} — sem tempo real nao ha' latencia que valha", medido=False)

    # 6) o processo do bordo e' o do PRODUTO (o ingestao do app), nao um ffmpeg qualquer
    procs = amb.processo_da_midia("streamid=publish")
    j.checar("quem envia e' o ffmpeg do produto (SRT com streamid do bordo)", bool(procs),
             f"{len(procs)} processo(s) de envio")
    linha = sql(amb.banco_bordo,
                "SELECT estado, pid, fluxo_id FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1",
                (cam,))
    j.checar("o bordo registra o envio no proprio banco (estado do produto)",
             bool(linha) and str(linha[0]["estado"]) in ("no_ar", "no ar", "enviando", "ativo"),
             f"{dict(linha[0]) if linha else 'sem linha de envio'}")

    # 7) a IMAGEM na tela do cliente (o que o cliente ve', medido no navegador dele)
    tela = _espera_estado(pagina, cam, "no ar", 60.0)
    j.checar("a tela do cliente diz que a transmissao esta' no ar", "no ar" in tela.lower(), tela[:80])
    ctx["t_no_ar"] = time.time()
    arranque = ctx["t_no_ar"] - t_clique
    j.checar("o tempo de subida cabe no que o produto promete (<= 60 s)", arranque <= 60.0,
             f"{arranque:.1f}s do clique ate' o no ar")

    pagina.click('.item[data-tela="visualizar"]')
    pagina.wait_for_timeout(1000)
    tv = tela_do_cliente(pagina, segundos=6.0)
    j.medir(tela=tv)
    j.checar("o cliente RECEBE imagem (o video decodifica no navegador dele)",
             bool(tv.get("imagem_na_tela")), f"{tv.get('largura')}x{tv.get('altura')} · "
             f"tempo {tv['tempo_antes_s']}s -> {tv['tempo_depois_s']}s")
    j.checar("o video do cliente nao esta' travado", not tv.get("travado"),
             f"travado={tv.get('travado')}")
    if not tv.get("imagem_na_tela"):
        j.checar("erros de JavaScript na tela do cliente", not erros, "; ".join(erros[:2]))

    ctx["fluxo"] = cam
    ctx["tem_camera_no_ar"] = True
    j.medir(arranque_s=round(arranque, 1), t_clique=t_clique)
    return j
