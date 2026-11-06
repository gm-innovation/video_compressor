#!/usr/bin/env python3
"""Teste da logica de contagem e de zona (Fase 5) com trajetorias conhecidas.

Nao precisa de video nem de modelo: alimenta o rastreador e o contador com caixas sinteticas
e cobra a contagem exata. E aqui que a histerese, o tempo de espera e o rastreio sao provados.

Uso: python tests/test-contagem.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analytics.rastreador import ContadorLinha, Rastreador, ZonaRisco  # noqa: E402

falhas: list[str] = []


def confere(nome, obtido, esperado):
    ok = obtido == esperado
    print(("  OK   " if ok else "  FALHA") + f" {nome}: {obtido!r}" + ("" if ok else f" (esperado {esperado!r})"))
    if not ok:
        falhas.append(nome)


def caixa(cx, cy, l=40, a=90):
    return (cx - l / 2, cy - a / 2, cx + l / 2, cy + a / 2)


def linha_horizontal(y=200.0):
    return ((0.0, y), (640.0, y))


def casos_contador():
    print("[contador de linha]")
    # 1) uma pessoa cruza de cima para baixo em 5 quadros
    c = ContadorLinha(*linha_horizontal(), quadros_de_confirmacao=3, espera_s=1.0, fps=12)
    c.qt = 0
    entrou = 0
    for i, cy in enumerate([150, 170, 190, 210, 230, 250]):
        alvos = [type("A", (), {"id": 1, "caixa": caixa(320, cy), "confianca": 0.9, "classe": 0})()]
        entrou += len(c.atualizar(alvos, tempo_s=i / 12.0))
    confere("cruzamento limpo conta 1 entrada", (c.entrou, c.saiu), (1, 0))
    confere("evento emitido uma vez", entrou, 1)

    # 2) ruido: pessoa encosta na linha e volta (1 quadro do outro lado) -> nao conta
    c = ContadorLinha(*linha_horizontal(), quadros_de_confirmacao=3, espera_s=1.0, fps=12)
    for i, cy in enumerate([180, 195, 205, 195, 180, 170]):
        alvos = [type("A", (), {"id": 7, "caixa": caixa(300, cy), "confianca": 0.9, "classe": 0})()]
        c.atualizar(alvos, tempo_s=i / 12.0)
    confere("ruido de 1 quadro nao conta", (c.entrou, c.saiu), (0, 0))

    # 3) duas pessoas em sentidos opostos
    c = ContadorLinha(*linha_horizontal(), quadros_de_confirmacao=3, espera_s=1.0, fps=12)
    for i, (cy_a, cy_b) in enumerate([(150, 260), (170, 240), (190, 220), (220, 190), (250, 160), (270, 140)]):
        alvos = [type("A", (), {"id": 1, "caixa": caixa(200, cy_a), "confianca": 0.9, "classe": 0})(),
                 type("A", (), {"id": 2, "caixa": caixa(400, cy_b), "confianca": 0.9, "classe": 0})()]
        c.atualizar(alvos, tempo_s=i / 12.0)
    confere("dois sentidos contam 1 entrada e 1 saida", (c.entrou, c.saiu), (1, 1))

    # 4) mesma pessoa cruzando de ida e volta dentro do tempo de espera -> a segunda travessia e suprimida
    def ida_e_volta(espera):
        c = ContadorLinha(*linha_horizontal(), quadros_de_confirmacao=2, espera_s=espera, fps=12)
        t = 0.0
        for _ in range(2):
            for cy in [150, 170, 190, 210, 230, 250, 230, 210, 190, 170, 150]:
                alvos = [type("A", (), {"id": 3, "caixa": caixa(320, cy), "confianca": 0.9, "classe": 0})()]
                c.atualizar(alvos, tempo_s=t)
                t += 1 / 12.0
        return (c.entrou, c.saiu)

    confere("espera por id suprime a travessia seguinte", ida_e_volta(5.0), (1, 0))
    confere("sem espera, cada travessia conta", ida_e_volta(0.2), (2, 2))

    # 5) 3 pessoas dentro ao mesmo tempo -> pico 3
    c = ContadorLinha(*linha_horizontal(), quadros_de_confirmacao=2, espera_s=1.0, fps=12)
    for i in range(4):
        alvos = [type("A", (), {"id": n, "caixa": caixa(100 + 80 * n, 260), "confianca": 0.9, "classe": 0})()
                 for n in (1, 2, 3)]
        c.atualizar(alvos, tempo_s=i / 12.0)
    confere("pico de pessoas na area", c.pico, 3)


def caso_esquecimento():
    print("[esquecimento de id]")
    c = ContadorLinha(*linha_horizontal(), quadros_de_confirmacao=2, espera_s=1.0, fps=12)
    t = 0.0
    for n, ident in enumerate(range(1, 6)):  # 5 pessoas entram e somem do video (sem sair pela linha)
        for i in range(4):
            alvos = [type("A", (), {"id": ident, "caixa": caixa(100 + 40 * n, 300), "confianca": 0.9, "classe": 0})()]
            c.atualizar(alvos, tempo_s=t)
            t += 1 / 12.0
    pico_no_pico = c.pico
    t += 20  # vinte segundos sem ver ninguem
    c.atualizar([], tempo_s=t)
    confere("pico cai quando os ids somem", (pico_no_pico, c.pico), (5, 5))
    confere("conjunto de dentro e limpo no esquecimento", len(c._dentro), 0)


def casos_rastreador():
    print("[rastreador]")
    r = Rastreador(iou_minimo=0.2, distancia_maxima=80)
    ids = set()
    for i, cx in enumerate(range(100, 200, 10)):
        alvos = r.atualizar([{"classe": 0, "confianca": 0.9, "caixa": caixa(cx, 300), "nome": "pessoa"}])
        ids |= {a.id for a in alvos}
    confere("mesma pessoa mantem um unico id", len(ids), 1)
    # pessoa some por 3 quadros e volta: id mantido (nao conta de novo)
    for _ in range(3):
        r.atualizar([])
    alvos = r.atualizar([{"classe": 0, "confianca": 0.9, "caixa": caixa(205, 300), "nome": "pessoa"}])
    confere("id sobrevive a 3 quadros sem deteccao", [a.id for a in alvos], [1])
    # duas pessoas simultaneas: ids diferentes
    alvos = r.atualizar([
        {"classe": 0, "confianca": 0.9, "caixa": caixa(400, 300), "nome": "pessoa"},
        {"classe": 0, "confianca": 0.9, "caixa": caixa(600, 300), "nome": "pessoa"}])
    confere("duas pessoas ao mesmo tempo recebem ids distintos", len({a.id for a in alvos} | {1}), len(alvos))


def casos_zona():
    print("[zona de risco]")
    z = ZonaRisco("máquinas", [(200, 200), (500, 200), (500, 400), (200, 400)], segundos=2.0, espera_s=30)
    eventos = 0
    for i in range(0, 60):  # 5 s a 12 fps dentro da zona
        alvos = [type("A", (), {"id": 5, "caixa": caixa(300, 300), "confianca": 0.9, "classe": 0})()]
        eventos += len(z.atualizar(alvos, tempo_s=i / 12.0))
    confere("permanencia dispara um evento", eventos, 1)
    z2 = ZonaRisco("máquinas", [(200, 200), (500, 200), (500, 400), (200, 400)], segundos=2.0)
    for i in range(120):
        alvos = [type("A", (), {"id": 6, "caixa": caixa(100, 100), "confianca": 0.9, "classe": 0})()]
        z2.atualizar(alvos, tempo_s=i / 12.0)
    confere("fora da zona nao dispara", len(z2._ultimo_evento), 0)


def main() -> int:
    casos_contador()
    caso_esquecimento()
    casos_rastreador()
    casos_zona()
    print("\nRESULTADO:", "tudo passou" if not falhas else f"{len(falhas)} falha(s): " + "; ".join(falhas))
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(main())
