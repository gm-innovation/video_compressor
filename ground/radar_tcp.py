#!/usr/bin/env python3
"""Bancada do radar AO VIVO: serve os quadros de um `.drq` por TCP, no formato medido.

Serve para provar o conector ao vivo (`radar_drq.quadros_ao_vivo_tcp`) antes de existir hardware de
radar na bancada. O que sai no fio e' o MESMO quadro de 2.240 B medido no arquivo do dono (tipo=3) —
nada de formato inventado: se o radar do cliente entregar esse formato pela rede, o produto ja' o
consome; se entregar outro, e' outro conector (declarado em contrato), nao um ajuste as cegas.

    python ground/radar_tcp.py ARQUIVO.drq [--porta 47001] [--ritmo real|livre] [--voltas 0]

`--ritmo real` (padrao) manda no ritmo da gravacao (a hora de cada quadro manda o passo); `livre`
manda o mais rapido que der. `--voltas 0` fica em repeticao.
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import radar_drq as R  # noqa: E402

PARADOS = 0
ENVIADOS = 0
TRAVA = threading.Lock()


def servir_cliente(con, endereco, caminho: str, ritmo: str, voltas: int, logar) -> None:
    """Manda os quadros do arquivo para UM cliente, em sequencia (sem seek: le de uma vez)."""
    global ENVIADOS, PARADOS
    anterior = None
    volta_atual = 0
    try:
        while True:
            with open(caminho, "rb") as f:
                f.seek(R.CABECALHO)
                i = 0
                while True:
                    q = f.read(R.QUADRO)
                    if len(q) != R.QUADRO:
                        break
                    r = R.montar_quadro(q, i)
                    i += 1
                    if r is None:
                        continue                      # so' o tipo de sinal (tipo=3) vai para o fio
                    if ritmo == "real" and anterior is not None:
                        espera = (r["hora"] - anterior).total_seconds()
                        if espera > 0:
                            time.sleep(min(espera, 0.5))
                    anterior = r["hora"]
                    con.sendall(q)
                    with TRAVA:
                        ENVIADOS += 1
            volta_atual += 1
            if voltas and volta_atual >= voltas:
                break
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        with TRAVA:
            PARADOS += 1
        try:
            con.close()
        except Exception:
            pass
        logar(f"cliente {endereco[0]}:{endereco[1]} saiu")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Bancada: radar .drq servido por TCP (formato medido)")
    p.add_argument("arquivo", help="arquivo .drq a servir")
    p.add_argument("--porta", type=int, default=47001)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--ritmo", choices=("real", "livre"), default="real")
    p.add_argument("--voltas", type=int, default=0, help="0 = fica em repeticao")
    a = p.parse_args(argv)

    if not Path(a.arquivo).exists():
        print(f"arquivo nao encontrado: {a.arquivo}")
        return 1
    cab = R.ler_cabecalho(a.arquivo)

    def logar(msg):
        print(f"[radar_tcp] {msg}", flush=True)

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((a.host, a.porta))
    servidor.listen(4)
    logar(f"servindo {Path(a.arquivo).name} em tcp://{a.host}:{a.porta} "
          f"({cab['quadros']} quadros, ritmo {a.ritmo})")
    try:
        while True:
            con, endereco = servidor.accept()
            logar(f"cliente {endereco[0]}:{endereco[1]} conectou")
            threading.Thread(target=servir_cliente,
                             args=(con, endereco, a.arquivo, a.ritmo, a.voltas, logar),
                             daemon=True).start()
    except KeyboardInterrupt:
        logar(f"parando (quadros enviados: {ENVIADOS}, clientes que sairam: {PARADOS})")
    finally:
        servidor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
