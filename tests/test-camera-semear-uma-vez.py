#!/usr/bin/env python3
"""Regressão: câmera excluída não volta quando a API reinicia.

Achado em 11/11/2026 (VPS): depois de limpar as câmeras de teste, reiniciar a API recriava
`cam-01` e `cam-02` da bancada — `inicializar()` semeava as câmeras de `ground/receivers.json` em
toda subida. Era por isso que "excluir câmera não pegava".

O que este teste prova, contra um banco temporário (não o do trabalho):

1) banco novo (instalação nova) ainda ganha as câmeras da bancada e as 4 de demonstração;
2) câmera apagada num banco já existente NÃO volta na inicialização seguinte;
3) subir duas vezes seguidas não duplica nem ressuscita nada.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

falhas = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("ok   " if condicao else "FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


import api  # noqa: E402


def cameras(banco: Path) -> list[str]:
    con = sqlite3.connect(banco)
    try:
        return [r[0] for r in con.execute("SELECT id FROM cameras ORDER BY id")]
    finally:
        con.close()


def main() -> int:
    # Diretório próprio em vez de TemporaryDirectory: o Windows não deixa apagar o banco
    # enquanto uma conexão do sqlite estiver aberta, e o fim do teste não é lugar de falhar.
    pasta = Path(tempfile.mkdtemp(prefix="lecsor-teste-camera-"))
    banco = pasta / "pipeline.db"
    original = api.BANCO
    try:
        api.BANCO = banco
        api.inicializar(False)
        primeira = cameras(banco)
        checar("instalação nova ganha câmera de bancada",
               any(not c.endswith("-demo") for c in primeira), str(primeira))
        bancada = sum(1 for c in primeira if not c.endswith("-demo"))
        checar("instalação nova ganha a demonstração espelhando a bancada",
               sum(1 for c in primeira if c.endswith("-demo")) == bancada, str(primeira))

        con = sqlite3.connect(banco)
        con.execute("DELETE FROM cameras WHERE id NOT LIKE '%-demo'")
        con.commit()
        con.close()
        apagada = cameras(banco)

        api.inicializar(False)
        segunda = cameras(banco)
        checar("câmera apagada não volta na subida seguinte", segunda == apagada,
               f"antes={apagada} depois={segunda}")

        api.inicializar(False)
        checar("subir de novo não duplica", cameras(banco) == segunda, str(cameras(banco)))
    finally:
        api.BANCO = original

    print()
    if falhas:
        print("FALHOU:", ", ".join(falhas))
        return 1
    print("tudo certo: a câmera excluída continua excluída depois de reiniciar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
