#!/usr/bin/env python3
"""Vigia da API da bancada: se a API cair, sobe de novo sozinha.

Motivo: no Windows nao existe systemd. Quando o processo da API morre (banco travado no boot, erro
de codigo, maquina reiniciada), ninguem re-ergue — e o aplicativo do dono abre em branco, sem tela
de login. Este vigia fecha esse buraco na bancada.

Uso: python tools/vigia-api.py [porta]
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PORTA = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
LOG = RAIZ / "ground" / "api-vigia.log"
INTERVALO = 10


def no_ar(porta: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=3):
            return True
    except OSError:
        return False


def registra(msg: str) -> None:
    linha = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(linha, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(linha + "\n")


def main() -> int:
    registra(f"vigia da API na porta {PORTA} (confere a cada {INTERVALO}s)")
    falhas = 0
    while True:
        if no_ar(PORTA):
            falhas = 0
        else:
            falhas += 1
            registra(f"porta {PORTA} sem resposta (falha {falhas})")
            if falhas >= 2:
                registra("subindo a API de novo")
                with open(RAIZ / "ground" / "api.log", "ab", buffering=0) as saida:
                    subprocess.Popen(["bash", "ground/start-api.sh", str(PORTA)],
                                     cwd=str(RAIZ), stdout=saida, stderr=saida, start_new_session=True)
                time.sleep(15)
                falhas = 0
        time.sleep(INTERVALO)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
