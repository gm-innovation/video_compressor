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

# 5) o motivo da falha separa LINK de CAMERA (o dono foi enganado por isso: o app dizia
#    "camera em uso" quando o que caiu foi o link SRT)
from pathlib import Path as _P  # noqa: E402
import tempfile  # noqa: E402

with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8") as _f:
    _f.write("12:07:57/!W:SRT.ks: CChannel::sendto call on ::WSAGetOverlappedResult failed with error: 0\n"
             "[vost#0:0/libx264] Error submitting a packet to the muxer: I/O error\n")
    _link = _P(_f.name)
with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8") as _f:
    _f.write("[dshow @ 0x1] Could not run filter\nCould not open video device: device already in use\n")
    _cam = _P(_f.name)

m_link = ingestao._motivo_da_falha(-5, _link, {})
m_cam = ingestao._motivo_da_falha(1, _cam, {})
checar("queda do link SRT vira recado de link", "link" in (m_link or "").lower(), str(m_link))
checar("camera ocupada continua recado de camera", "camera" in (m_cam or "").lower() and "link" not in (m_cam or "").lower(), str(m_cam))

print()
if falhas:
    print(f"{len(falhas)} falha(s): " + ", ".join(falhas))
    sys.exit(1)
print("tudo certo")
