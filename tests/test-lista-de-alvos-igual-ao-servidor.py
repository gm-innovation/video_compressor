#!/usr/bin/env python3
"""LISTA DE QUALIDADE DE ENVIO — uma fonte só, provada por igualdade (0.21.0, 26/11/2026).

O dono pediu "mais possibilidades de qualidade de envio, 2mbps, 2,5mbps e 3mbps" e a ordem do MAIOR
para o MENOR. A lista é FECHADA (o servidor recusa qualquer outro número), então ela não pode viver em
cópias que se contradizem — era o que acontecia: a lista estava copiada em 6 lugares e a escada de
sugestão do servidor ia parar em 1500k mesmo depois de a lista ganhar níveis acima.

Este teste não sobe servidor: ele lê os dois arquivos e exige que as duas listas sejam IDÊNTICAS.

    python tests/test-lista-de-alvos-igual-ao-servidor.py
"""
from __future__ import annotations

import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
ESPERADO = ["3000", "2500", "2000", "1500", "1200", "1000", "800", "500", "300"]


def exigir(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def lista(texto: str, padrao: str) -> list[str] | None:
    m = re.search(padrao, texto)
    if not m:
        return None
    return re.findall(r"[\"']([0-9]+k?)[\"']", m.group(1))


def main() -> int:
    api = (RAIZ / "ground" / "api.py").read_text(encoding="utf-8")
    adm = (RAIZ / "admin" / "admin.js").read_text(encoding="utf-8")
    html = (RAIZ / "admin" / "index.html").read_text(encoding="utf-8")

    servidor = lista(api, r"VALORES_DE_ALVO = \(([^)]*)\)")
    servidor_k = lista(api, r"ALVOS_DE_QUALIDADE = \(([^)]*)\)")
    admin = lista(adm, r"const ALVOS_DE_ENVIO = \[([^\]]*)\]")

    exigir("o servidor declara a lista (`VALORES_DE_ALVO`)", servidor is not None, str(servidor))
    exigir("o admin declara a lista (`ALVOS_DE_ENVIO`)", admin is not None, str(admin))
    exigir("o servidor tem a lista com sinal (`ALVOS_DE_QUALIDADE`)", servidor_k is not None, str(servidor_k))
    if servidor is None or admin is None or servidor_k is None:
        print("\ntest-lista-de-alvos: nao achei uma das listas — o teste nao pode passar em branco")
        return 1

    exigir("a lista do projeto é a pedida pelo dono (3 / 2,5 / 2 Mbps no topo)",
           servidor == ESPERADO, f"no servidor: {servidor}")
    exigir("o ADMIN oferece exatamente a MESMA lista do servidor (uma fonte, duas telas)",
           admin == servidor, f"admin={admin} x servidor={servidor}")
    exigir("a lista com sinal (`k`) acompanha a lista sem sinal, na mesma ordem",
           servidor_k == [v + "k" for v in servidor], f"no servidor: {servidor_k}")
    exigir("a lista está do MAIOR para o MENOR (ordem pedida pelo dono)",
           [int(v) for v in servidor] == sorted((int(v) for v in servidor), reverse=True),
           str(servidor))

    # as copias antigas não podem voltar: o admin não pode ter outra lista literal de kbps
    # uma lista da QUALIDADE do produto tem 4+ níveis em kbps; a bancada de medição tem a lista dela
    # (3 bandas para comparar), que não é escolha do produto e pode continuar sendo literal
    sobras = re.findall(r"\[\s*'[0-9]+k'(?:\s*,\s*'[0-9]+k'){3,}\s*\]", adm)
    exigir("o admin não tem NENHUMA outra lista literal da qualidade do produto (as 4 cópias saíram)",
           not sobras, str(sobras)[:160])
    exigir("a lista do admin vem de UMA constante (as telas derivam dela)",
           adm.count("const ALVOS_DE_ENVIO = ") == 1,
           "%d declaração(ões)" % adm.count("const ALVOS_DE_ENVIO = "))

    # a escada de sugestão do servidor tem de sair da MESMA lista (era outra cópia, parada em 1500k)
    exigir("a escada de sugestão do servidor deriva da lista (não é cópia parada em 1500k)",
           'acima = [n + "k" for n in VALORES_DE_ALVO if int(n) > kbps]' in api)

    # e a tela que saiu não pode voltar sozinha
    exigir("a tela 'Configuração do bordo' não existe mais no admin (JS)",
           "telaConfigDoBordo" not in adm and "config_bordo:" not in adm)
    exigir("a tela 'Configuração do bordo' não está no menu",
           'data-tela="config_bordo"' not in html)
    exigir("nada rotula aplicação como 'RECUSADO' (o motivo vai cru no cartão)",
           "RECUSADO" not in adm)

    print()
    if falhas:
        print(f"TEST-LISTA-DE-ALVOS: {len(falhas)} FALHA(S): " + " · ".join(falhas))
        return 1
    print("TEST-LISTA-DE-ALVOS_OK — servidor e admin com a MESMA lista fechada, "
          "3000/2500/2000/1500/1200/1000/800/500/300, do maior para o menor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
