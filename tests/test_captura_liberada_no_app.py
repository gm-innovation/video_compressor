#!/usr/bin/env python3
"""Prova NO APLICATIVO: liberar as funcoes de captura NAO tira as telas do lado terra (dono, 16/11/2026).

Este e' o teste da area alterada do `desktop/` (o `test_captura_no_admin.py` prova o servidor e a
resolucao de config; aqui o proprio Electron sobe e diz o que resolveu):

  * sobe o aplicativo de verdade (`npx electron . --verificar`) com `LECSOR_CAPTURA_LOCAL=1`;
  * o relatorio do proprio app tem de dizer: telas continuam no lado terra (`base`), captura ligada,
    servidor local no ar respondendo `/api/saude`, e a ponte (`preload.js`) entregando para a pagina o
    endereco do servidor de captura desta maquina — que e' o que faz a tela "Enviar video" enxergar as
    cameras plugadas aqui;
  * a interface continua SEM Node.

Uso: python tests/test_captura_liberada_no_app.py
"""
from __future__ import annotations
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DESKTOP = RAIZ / "desktop"
TERRA = "http://187.127.60.250:8085"
falhas: list[str] = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("  OK   " if condicao else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


def porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> int:
    if not (DESKTOP / "node_modules" / "electron").exists():
        print("instale o aplicativo antes: cd desktop && npm install")
        return 2
    porta = porta_livre()
    config = DESKTOP / "config.json"
    antigo = config.read_text(encoding="utf-8")
    atual = json.loads(antigo)
    atual["base"] = TERRA
    atual.pop("capturaLocal", None)
    config.write_text(json.dumps(atual, indent=2) + "\n", encoding="utf-8")
    try:
        env = dict(os.environ)
        env["LECSOR_CAPTURA_LOCAL"] = "1"          # liga as funcoes de captura sem tocar no config gravado
        env["LECSOR_PORTA_API"] = str(porta)       # porta propria: nao disputa a 8765 de outro servidor
        env["LECSOR_REPO"] = str(RAIZ)             # em desenvolvimento o codigo do servidor vem da bancada
        env.pop("LECSOR_SUPERFICIE", None)
        r = subprocess.run(["npx", "electron", ".", "--verificar"], cwd=str(DESKTOP),
                           capture_output=True, text=True, timeout=420, env=env, shell=True)
        saida = (r.stdout or "") + (r.stderr or "")
        bloco = saida.split("VERIFICACAO", 1)[1] if "VERIFICACAO" in saida else ""
        if not bloco:
            print(saida[-2000:])
        checar("o aplicativo subiu e respondeu", bool(bloco), f"rc={r.returncode}")
        if not bloco:
            return 1

        linha_config = next((l for l in bloco.splitlines() if l.startswith("config\t")), "")
        print("  relatorio do app: " + linha_config)
        checar("as telas continuam no lado terra (a base NAO virou loopback)",
               f"base={TERRA}" in linha_config, linha_config[:160])
        checar("a captura ficou ligada nesta maquina", "capturaLocal=true" in linha_config)
        checar("o servidor local desta maquina esta no ar respondendo a API",
               "captura_servidor=ok" in linha_config)
        checar("a ponte entrega a pagina o endereco da captura desta maquina",
               f"enderecoCaptura=http://127.0.0.1:{porta}" in linha_config)
        checar("a pagina recebe esse endereco (e' o que liga a tela a camera plugada aqui)",
               f'"captura":"http://127.0.0.1:{porta}"' in bloco)
        checar("todas as janelas seguiram sem Node na interface",
               bloco.count('"node":"undefined"') == 3, f"{bloco.count(chr(34) + 'node' + chr(34) + ':' + chr(34) + 'undefined' + chr(34))} de 3")
    finally:
        config.write_text(antigo, encoding="utf-8")

    print("\n" + ("RESULTADO: tudo passou" if not falhas
                  else "RESULTADO: falhou — " + "; ".join(falhas)))
    print("CAPTURA_LIBERADA_NO_APP_OK" if not falhas else "CAPTURA_LIBERADA_NO_APP_FALHOU")
    return 0 if not falhas else 1


if __name__ == "__main__":
    sys.exit(main())
