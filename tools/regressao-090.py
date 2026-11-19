#!/usr/bin/env python3
"""Regressao curada da 0.9.0 (escopos de cliente + varredura/cadastro automatico + observador).

Roda cada prova num processo proprio e imprime `rc` por prova — o que o dono le' e' a lista. NAO e' o
`suite.py` inteiro (45 scripts): aqui entram as provas da 0.7.0/0.8.0 que tocam o que mudou, mais as novas.

    python tools/regressao-090.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PROVAS = (
    # escopos de cliente (Fase 1)
    "tests/test-escopos-de-acesso.py",
    "tests/e2e-escopo-no-admin.py",
    # varredura / cadastro automatico (Fase 2)
    "tests/e2e-varredura-do-bordo.py",
    # cadastro do bordo nao se perde (Fase 3)
    "tests/test-fluxo-no-lado-terra.py",
    # observador / Petrobras (Fase 4)
    "tests/e2e-observador-do-radar.py",
    # o que a 0.8.0 ja' provava e passa por estas rotas
    "tests/test-papeis-de-config.py",
    "tests/test-cadastro-so-pelo-admin.py",
    "tests/test-app-unico-por-papel.py",
    "tests/e2e-cadastro-de-camera-salva-no-banco.py",
    "tests/e2e-config-do-bordo-vinda-de-terra.py",
    "tests/e2e-tela-do-captura-so-cadastra.py",
    "tests/e2e-admin-configura-e-bordo-obedece.py",
    "tests/e2e-saude-do-bordo-no-admin.py",
    "tests/e2e-flag-de-estado-liga-a-camera.py",
)


def main() -> int:
    ruins = []
    for prova in PROVAS:
        caminho = RAIZ / prova
        if not caminho.exists():
            print(f"PULOU (nao existe) {prova}")
            continue
        proc = subprocess.run([sys.executable, str(caminho)], cwd=str(RAIZ),
                              capture_output=True, text=True, timeout=600, errors="replace")
        ultima = ""
        for linha in reversed((proc.stdout or "").splitlines()):
            if linha.strip():
                ultima = linha.strip()
                break
        print(f"rc={proc.returncode:<3} {prova} — {ultima[:120]}")
        if proc.returncode != 0:
            ruins.append(prova)
    print()
    if ruins:
        print("FALHARAM: " + ", ".join(ruins))
        return 1
    print(f"TUDO VERDE ({len(PROVAS)} provas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
