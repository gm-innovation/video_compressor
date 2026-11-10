#!/usr/bin/env python3
"""Regressao: ligar/desligar a camera pela tela e soltar o dispositivo.

O que quebrou de verdade (10/11/2026): a rede caiu, o ffmpeg ficou preso segurando a webcam e o
envio seguinte respondia "camera em uso" — a camera so voltava desligando e ligando na mao.
Agora: (1) liberar_camera mata quem segura o dispositivo; (2) desligar_camera para o envio e
marca 'parado' ANTES de matar (o remetente nao reabre sozinho o que a tela desligou);
(3) ligar_camera reabre com o ultimo ajuste.

Este teste nao abre a camera de verdade: usa nomes que nao existem para provar que o caminho
de erro responde em vez de estourar.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

import ingestao  # noqa: E402

falhas = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("ok   " if condicao else "FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


# 1) liberar_camera num dispositivo que nao existe: nao estoura e nao mata ninguem
r = ingestao.liberar_camera("dispositivo-que-nao-existe-xyz")
checar("liberar_camera devolve dict", isinstance(r, dict), str(r))
checar("liberar_camera nao mata nada", r.get("liberados") == 0, str(r))

# 2) desligar/ligar camera inexistente: erro claro, sem excecao
d = ingestao.desligar_camera("camera-que-nao-existe")
checar("desligar_camera inexistente devolve erro", "erro" in d, str(d))
l = ingestao.ligar_camera("camera-que-nao-existe")
checar("ligar_camera inexistente devolve erro", "erro" in l, str(l))

# 3) parar() de um envio inexistente continua devolvendo erro (nao mexe em dispositivo)
p = ingestao.parar(999999999)
checar("parar inexistente devolve erro", "erro" in p, str(p))

# 4) o marcador de "desligada pela tela" e' o estado 'parado' no banco
checar("_foi_desligada existe no remetente", hasattr(__import__("enviar_para_vps"), "_foi_desligada"))

print()
if falhas:
    print(f"{len(falhas)} falha(s): " + ", ".join(falhas))
    sys.exit(1)
print("tudo certo")
