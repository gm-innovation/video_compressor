#!/usr/bin/env python3
"""Identidade de processo: **um pid sozinho nao e' identidade** — o Windows recicla numero.

Medido no PC real em 27/11/2026 (0.29.0): o gravador do HD morria com `Exiting normally, received
signal 15` a cada ~6 s (4 blocos, o ultimo `bloco-20261127-150400.mp4`) porque o produto manda sinal a
partir de um *pid guardado numa linha do banco* — `parar()` em `ground/ingestao.py` faz
`os.kill(r["pid"], SIGTERM)`. Quando aquele processo ja' tinha morrido, o numero do pid passou a ser de
outro (o ffmpeg do gravador, que sobe um por vez) e o produto matou o que nao era dele.

Aqui ficam as duas perguntas que o produto precisa saber responder sem se enganar:

    criado_em(pid)                          -> quando o processo NASCEU (epoch) ou 0.0 se nao sei
    mesmo_processo(pid, criado_em_esperado) -> o pid de agora e' o MESMO processo que eu subi?

Regra de ouro: **na duvida, nao e' o nosso** (nunca matar/derrubar o que nao se pode provar). Quem
solta camera presa tem o `liberar_camera()` (por dispositivo) como ultimo recurso.
"""
from __future__ import annotations

import calendar
import os
import subprocess
import time

# Folga entre "mandei subir" e "a linha do banco foi gravada" (segundos). O processo nasce ANTES da
# linha existir, entao a criacao esperada e' sempre <= a linha; a comparacao e' assimetrica de proposito.
FOLGA_S = 120.0


def _por_psutil(pid: int) -> float:
    try:
        import psutil  # noqa: PLC0415  (o pacote do PC de captura leva o psutil dentro)
        p = psutil.Process(int(pid))
        return float(p.create_time())
    except Exception:
        return 0.0


def _por_windows(pid: int) -> float:
    """Sem psutil: a hora de criacao vem do WMI (a mesma fonte que o `liberar_camera` ja' usa)."""
    if os.name != "nt":
        return 0.0
    try:
        texto = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\").CreationDate"
             ".ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss')"],
            capture_output=True, timeout=12).stdout
        bruto = (texto or b"").decode("utf-8", "ignore").strip()
        if not bruto or "cannot" in bruto.lower():
            return 0.0
        return float(calendar.timegm(time.strptime(bruto[:19], "%Y-%m-%dT%H:%M:%S")))
    except Exception:
        return 0.0


def criado_em(pid) -> float:
    """Quando o processo <pid> nasceu (epoch). 0.0 = nao existe ou nao consegui medir."""
    try:
        n = int(pid or 0)
    except (TypeError, ValueError):
        return 0.0
    if n <= 0:
        return 0.0
    t = _por_psutil(n)
    if not t and os.name == "nt":
        t = _por_windows(n)
    return t


def vivo(pid) -> bool:
    """Existe processo com este pid? (nao diz de QUEM ele e' — para isso, `mesmo_processo`.)"""
    try:
        n = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if n <= 0:
        return False
    if os.name == "nt":
        # `os.kill(pid, 0)` no Windows FECHA o processo: aqui so' a checagem de existencia, via psutil
        # (barato) e, sem ele, pelo proprio `criado_em`.
        return bool(criado_em(n))
    try:
        os.kill(n, 0)
        return True
    except OSError:
        return False


def mesmo_processo(pid, criado_em_esperado, folga: float = FOLGA_S) -> bool:
    """O pid de agora e' o MESMO processo que eu subi (pela hora de criacao)?

    - pid sem processo -> False
    - sem `criado_em_esperado` (linha antiga, sem o campo) -> False: **nao da' para provar**, entao
      nao se mata (a linha antiga e' limpa, nao usada como desculpa para derrubar processo alheio)
    - criacao do pid mais NOVA que a esperada + folga -> **pid reciclado** -> False
    """
    try:
        n = int(pid or 0)
    except (TypeError, ValueError):
        return False
    esperado = float(criado_em_esperado or 0.0)
    if n <= 0 or esperado <= 0.0:
        return False
    agora = criado_em(n)
    if not agora:
        return False
    return agora <= (esperado + float(folga))


def reciclado(pid, criado_em_esperado) -> bool:
    """O pid existe mas NAO e' o nosso: o numero foi reaproveitado (o caso medido no PC real)."""
    return vivo(pid) and not mesmo_processo(pid, criado_em_esperado)


def espera_do_sobrou(segundos: float = 0.4) -> None:
    """Respiro curto depois de mandar sinal (para o processo sair e o dshow soltar o dispositivo)."""
    if segundos > 0:
        time.sleep(segundos)
