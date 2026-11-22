#!/usr/bin/env python3
"""Regressao curada da 0.10.0 (chave de licenca do PC de captura).

Roda cada prova num processo proprio e imprime `rc` por prova — o que o dono le' e' a lista. As 4
primeiras sao as NOVAS (a licenca, de ponta a ponta: lado terra, lado bordo e as duas telas); o resto e'
o que a 0.9.0 ja' provava e passa pelas mesmas rotas que a licenca encostou (`ground/api.py`,
`ground/repasse.py`, `ground/varredura_do_bordo.py`, `desktop/servidor.js`, `admin/admin.js`).

    python tools/regressao-0100.py
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# Toda prova sobe servidor proprio: sem isto ela herdaria o lado terra (VPS), o token e o Supabase do
# `ambiente.json` que esta' no repositorio, e passaria a falar com a producao em vez de responder em casa.
os.environ["LECSOR_SEM_AMBIENTE"] = "1"
PROVAS = (
    # CHAVE DE LICENCA (rodada 0.10.0)
    "tests/test-licenca-de-ativacao.py",
    "tests/test-licenca-do-bordo.py",
    "tests/e2e-licenca-no-admin.py",
    "tests/e2e-app-ativado-por-licenca.py",
    "tests/test-licenca-nao-vaza.py",
    "tests/test-licenca-isola-embarcacao.py",
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
                              capture_output=True, text=True, timeout=900, errors="replace")
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
