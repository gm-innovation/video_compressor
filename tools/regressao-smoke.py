#!/usr/bin/env python3
"""Regressao do SMOKE de ponta a ponta: o medidor mede, e as jornadas passam.

    python tools/regressao-smoke.py            # medidor + J1..J6 (o dia a dia)    ~8 min
    python tools/regressao-smoke.py --completo # medidor + J1..J10 (bancada toda) ~12 min
    python tools/regressao-smoke.py --rapido   # antes de commitar                ~2 min

Roda:
  1. `tests/smoke-medidor-detecta-falha.py` — prova que o medidor nao da' "OK" de graca;
  2. `tools/smoke/ponta-a-ponta.py` — as jornadas de ponta a ponta (--rapido = J1+J2).

Codigo de saida: 0 só quando tudo passa. Preserva a evidencia de cada rodada em `smoke/saida/`.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
AMBIENTE = {"LECSOR_SENHA_DEMO": __import__("os").environ.get("LECSOR_SENHA_DEMO", "senha-do-smoke-bancada"),
            "PYTHONIOENCODING": "utf-8"}


def rodar(nome: str, comando: list[str], teto: int) -> bool:
    print("=" * 78)
    print(f">> {nome}")
    print("=" * 78, flush=True)
    t0 = time.time()
    r = subprocess.run(comando, cwd=str(RAIZ), env={**__import__("os").environ, **AMBIENTE}, timeout=teto)
    ok = r.returncode == 0
    print(f"<< {nome}: {'OK' if ok else f'FALHOU (rc={r.returncode})'} em {time.time() - t0:.0f}s\n",
          flush=True)
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description="regressao do smoke de ponta a ponta")
    p.add_argument("--rapido", action="store_true", help="só J1+J2 no smoke")
    p.add_argument("--completo", action="store_true", help="a bancada toda (J1..J10)")
    p.add_argument("--sem-medidor", action="store_true", help="pula a prova do medidor")
    args = p.parse_args()

    provas: list[tuple[str, list[str], int]] = []
    if not args.sem_medidor:
        provas.append(("o medidor mede (e devolve zero quando nao ha' fluxo)",
                       [sys.executable, "tests/smoke-medidor-detecta-falha.py"], 420))
    # `--completo` = a bancada toda (J1..J10); sem ele, J1..J6 (o dia a dia, ~8 min). Jornada que depende de
    # dispositivo de video (J6, o HD do radar) se marca NAO MEDIDA sozinha, em vez de mentir "OK".
    # AVISO DE BANCADA (medido): a J2 mede fps e, com a maquina OCUPADA, pode nao sustentar os 30 fps do
    # produto (medido 26,4 fps; isolada, 30,0). Nao e' o produto — e' o host. Rode com a maquina ociosa.
    if args.rapido:
        jornadas = "1,2"
    elif args.completo:
        jornadas = "1,2,3,4,5,6,7,8,9,10"
    else:
        jornadas = "1,2,3,4,5,6"
    provas.append((f"smoke de ponta a ponta (jornadas {jornadas})",
                       [sys.executable, "tools/smoke/ponta-a-ponta.py", "--jornadas", jornadas], 2400))

    resultados = [(nome, rodar(nome, cmd, teto)) for nome, cmd, teto in provas]
    print("=" * 78)
    for nome, ok in resultados:
        print(f"{'OK   ' if ok else 'FALHA'} {nome}")
    falhou = [n for n, ok in resultados if not ok]
    print("=" * 78)
    if falhou:
        print(f"REGRESSAO DO SMOKE: FALHOU ({len(falhou)}): " + "; ".join(falhou))
        return 1
    print("REGRESSAO DO SMOKE: TUDO OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
