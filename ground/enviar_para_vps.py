#!/usr/bin/env python3
"""Envia a webcam DESTA bancada comprimida para a VPS e fica vivo (teste real ponta-a-ponta).

A captura e o encode sao locais (a camera e' fisica nesta maquina); o transporte atravessa a internet,
porque o destino SRT e' o IP publico da VPS. Do outro lado a VPS recebe, publica em WebRTC e serve o
app do cliente, que decodifica no player local.

Uso: python ground/enviar_para_vps.py [host] [porta] [rotulo] [segundos]
Sem `segundos`, transmite ate alguem parar.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

from ingestao import DISPOSITIVO_PADRAO, ao_vivo, parar  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else "187.127.60.250"
PORTA = int(sys.argv[2]) if len(sys.argv) > 2 else 8890
ROTULO = sys.argv[3] if len(sys.argv) > 3 else "Webcam bancada (bordo -> VPS)"
SEGUNDOS = int(sys.argv[4]) if len(sys.argv) > 4 else 0

if __name__ == "__main__":
    # a webcam so abre uma vez: se outro envio a estiver segurando, tenta de novo em vez de desistir
    r = {}
    for tentativa in range(1, 61):
        r = ao_vivo(tipo="camera", dispositivo=DISPOSITIVO_PADRAO, rotulo=ROTULO,
                    fluxo_id="vps-webcam-bancada", fps=30, srt_host=HOST, srt_port=PORTA)
        if not r.get("erro"):
            break
        print(f"tentativa {tentativa}: {r['erro']}", flush=True)
        time.sleep(30)
    print({"id": r.get("id"), "fluxo_id": r.get("fluxo_id"), "destino": f"srt://{HOST}:{PORTA}",
           "erro": r.get("erro")}, flush=True)
    if r.get("erro"):
        sys.exit(1)
    # mantem o processo vivo para o ffmpeg continuar publicando enquanto o dono estiver fora
    fim = time.time() + SEGUNDOS if SEGUNDOS else None
    try:
        while fim is None or time.time() < fim:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        parar(r["id"])
        print("parado", flush=True)
