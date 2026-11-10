#!/usr/bin/env python3
"""Envia a webcam DESTA bancada comprimida para a VPS e fica vivo (teste real ponta-a-ponta).

A captura e o encode sao locais (a camera e' fisica nesta maquina); o transporte atravessa a internet,
porque o destino SRT e' o IP publico da VPS. Do outro lado a VPS recebe, publica em WebRTC e serve o
app do cliente, que decodifica no player local.

A camera SEMPRE volta sozinha: se o envio cair (a rede mudou, o link caiu, o ffmpeg travou), este
supervisor solta o dispositivo e reabre a webcam — ninguem precisa desconectar nada na mao.

Uso: python ground/enviar_para_vps.py [host] [porta] [rotulo] [segundos] [resolucao] [bitrate]
Sem `segundos`, transmite ate alguem parar.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

from ingestao import DISPOSITIVO_PADRAO, _processo_vivo, ao_vivo, conexao, parar  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else "187.127.60.250"
PORTA = int(sys.argv[2]) if len(sys.argv) > 2 else 8890
ROTULO = sys.argv[3] if len(sys.argv) > 3 else "Webcam bancada (bordo -> VPS)"
SEGUNDOS = int(sys.argv[4]) if len(sys.argv) > 4 else 0
# a webcam desta bancada entrega 1280x720@30 — pedir 1080p ao dshow faz o ffmpeg falhar
RESOLUCAO = sys.argv[5] if len(sys.argv) > 5 else "1280x720"
# 2500k/3000k e' o menor ajuste medido que passa do piso de qualidade (SSIM >= 0,9713): 1500k
# media 0,958-0,972 na webcam desta bancada, abaixo do piso.
BITRATE = sys.argv[6] if len(sys.argv) > 6 else "3000k"

TRAVA = RAIZ / "ground" / ".enviar-para-vps.pid"
SEM_BYTES_S = 30   # quanto tempo sem subir byte nenhum antes de considerar o link caido


def _outro_remetente_vivo() -> int | None:
    try:
        pid = int(TRAVA.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    if pid != os.getpid() and _processo_vivo(pid):
        return pid
    return None


def _megabytes_da_linha(ident: int) -> float:
    with conexao() as c:
        r = c.execute("SELECT tamanho_mb FROM ingestoes WHERE id=?", (ident,)).fetchone()
    return float((r["tamanho_mb"] if r else 0) or 0)


def _foi_desligada(ident: int) -> bool:
    """Diz se quem parou o envio foi a tela (estado 'parado'), e nao uma queda de rede."""
    with conexao() as c:
        r = c.execute("SELECT estado FROM ingestoes WHERE id=?", (ident,)).fetchone()
    return bool(r) and r["estado"] == "parado"


if __name__ == "__main__":
    anterior = _outro_remetente_vivo()
    if anterior:
        print(f"ja existe um remetente no ar (pid {anterior}) — nao subo um segundo", flush=True)
        sys.exit(0)
    TRAVA.write_text(str(os.getpid()), encoding="utf-8")
    fim = time.time() + SEGUNDOS if SEGUNDOS else None
    desligada_pela_tela = False
    try:
        while not desligada_pela_tela and (fim is None or time.time() < fim):
            # ao_vivo ja solta sozinho quem estiver segurando a webcam antes de abrir
            r = ao_vivo(tipo="camera", dispositivo=DISPOSITIVO_PADRAO, rotulo=ROTULO,
                        fluxo_id="vps-webcam-bancada", fps=30, resolucao=RESOLUCAO, bitrate=BITRATE,
                        srt_host=HOST, srt_port=PORTA)
            if r.get("erro"):
                print(f"nao consegui transmitir: {r['erro']} — tento de novo em 15 s", flush=True)
                time.sleep(15)
                continue
            ident, pid = r["id"], r["pid"]
            print({"id": ident, "fluxo_id": r.get("fluxo_id"), "destino": f"srt://{HOST}:{PORTA}",
                   "pid": pid}, flush=True)
            # vigia: com o envio de pe, espera. Se o processo morrer OU os bytes pararem de subir
            # (soquete morto com o processo ainda vivo), derruba e reabre a webcam sozinho.
            # Excecao: se o envio esta "parado" no banco, foi a tela que desligou a camera — entao
            # eu NAO reabro (o botao Ligar da tela que manda).
            ultimo, ultima_mudanca = None, time.time()
            while fim is None or time.time() < fim:
                time.sleep(5)
                if not _processo_vivo(pid):
                    time.sleep(4)  # deixa quem parou (a tela/API) terminar de gravar o estado
                    if _foi_desligada(ident):
                        print("a camera foi desligada pela tela — nao reabro sozinho", flush=True)
                        desligada_pela_tela = True
                    else:
                        print("o envio caiu — reabrindo a webcam sozinho", flush=True)
                    break
                mb = _megabytes_da_linha(ident)
                if ultimo is None or mb > ultimo:
                    ultimo, ultima_mudanca = mb, time.time()
                elif time.time() - ultima_mudanca > SEM_BYTES_S:
                    print(f"o envio parou de subir bytes por {SEM_BYTES_S}s (link caiu) — "
                          "reiniciando sozinho", flush=True)
                    break
            if not desligada_pela_tela:
                parar(ident)
                time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            TRAVA.unlink()
        except Exception:
            pass
        print("parado", flush=True)
