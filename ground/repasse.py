#!/usr/bin/env python3
"""Repassa para o lado terra (VPS ou outro PC da rede) o fluxo JA COMPRIMIDO publicado nesta maquina.

Quem chama e' o mediamtx local, pelo `runOnReady` (um processo por fluxo, que volta quando o fluxo
volta). Tambem roda na mao, para testar:

    python ground/repasse.py <fluxo> [host:porta]

Regras que valem sempre:
- **Sem destino nao ha repasse.** O destino vem do argumento ou de `LECSOR_DESTINO_SRT`. Sem ele o
  script sai na hora — e' o que impede a propria VPS (que roda o mesmo mediamtx) de subir para si.
- **`-c copy`, nunca reencodar.** O fluxo que chega aqui ja foi comprimido no PC de captura; o
  repasse so troca de transporte (RTSP local -> SRT) e mantem os mesmos bytes.
- **Volta sozinho.** Se o link cair ou o ffmpeg morrer, tenta de novo a cada 2 s enquanto o fluxo
  existir. Trava de PID por fluxo, para nao duplicar envio.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

LOG_DIR = RAIZ / "ground" / "envios" / "log"
TRAVA_DIR = RAIZ / "ground" / ".repasse"
SEGUNDOS_ENTRE_TENTATIVAS = 2


def _log(fluxo: str, linha: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    carimbo = time.strftime("%Y-%m-%d %H:%M:%S")
    texto = f"{carimbo} [{fluxo}] {linha}"
    print(texto, flush=True)
    try:
        with (LOG_DIR / f"repasse-{fluxo}.log").open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except Exception:
        pass


def _ja_rodando(fluxo: str) -> bool:
    """Um repasse por fluxo: se ja' existe processo vivo, este sai sem enviar."""
    from ingestao import _processo_vivo  # mesma checagem usada pelo envio para a VPS
    TRAVA_DIR.mkdir(parents=True, exist_ok=True)
    trava = TRAVA_DIR / f"{fluxo}.pid"
    try:
        pid = int(trava.read_text(encoding="utf-8").strip())
    except Exception:
        pid = 0
    if pid and pid != os.getpid() and _processo_vivo(pid):
        return True
    trava.write_text(str(os.getpid()), encoding="utf-8")
    return False


def _comando(fluxo: str, destino: str, origem: str) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-rtsp_transport", "tcp", "-i", f"{origem.rstrip('/')}/{fluxo}",
        # o encode ja' veio pronto do PC de captura: aqui so' troca o transporte
        "-c", "copy", "-f", "mpegts",
        f"srt://{destino}?mode=caller&latency=200&pkt_size=1316&streamid=publish:{fluxo}",
    ]


def repassar(fluxo: str, destino: str, origem: str) -> int:
    if not destino:
        _log(fluxo, "sem destino (LECSOR_DESTINO_SRT) — nada a repassar")
        return 0
    if _ja_rodando(fluxo):
        _log(fluxo, "ja' existe repasse vivo deste fluxo — saindo sem duplicar")
        return 0
    _log(fluxo, f"repassando {origem}/{fluxo} -> srt://{destino} (-c copy)")
    while True:
        r = subprocess.run(_comando(fluxo, destino, origem), capture_output=True, text=True)
        if r.returncode == 0:
            _log(fluxo, "fluxo encerrado na origem — repasse parado")
            return 0
        erro = (r.stderr or "").strip().splitlines()
        _log(fluxo, f"reenvio em {SEGUNDOS_ENTRE_TENTATIVAS}s ({erro[-1] if erro else 'sem mensagem'})")
        time.sleep(SEGUNDOS_ENTRE_TENTATIVAS)


def principal() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    fluxo = sys.argv[1]
    destino = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("LECSOR_DESTINO_SRT", "")
    origem = os.environ.get("LECSOR_ORIGEM_RTSP", "rtsp://127.0.0.1:8554")
    return repassar(fluxo, destino, origem)


if __name__ == "__main__":
    raise SystemExit(principal())
