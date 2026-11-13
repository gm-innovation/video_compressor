#!/usr/bin/env python3
"""Onde esta' o ffmpeg (e o ffprobe) que o sistema deve usar.

O aplicativo instalado EMBUTE o ffmpeg (`resources/ffmpeg/ffmpeg.exe`) e o entrega aos processos
filhos pela variavel `LECSOR_FFMPEG`, com a pasta tambem no PATH. Ordem de resolucao:

1. a variavel do app (`LECSOR_FFMPEG` / `LECSOR_FFPROBE`) — o binario embutido;
2. o que estiver no PATH da maquina (`shutil.which`);
3. o nome puro (`ffmpeg`), ultimo recurso: o erro sobe com a mensagem do proprio sistema.

Nunca devolve um caminho que nao existe: se a variavel aponta para arquivo ausente, cai para o PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

VAR_FFMPEG = "LECSOR_FFMPEG"
VAR_FFPROBE = "LECSOR_FFPROBE"
VAR_BANCO = "LECSOR_BANCO"


def _da_variavel(variavel: str) -> str:
    valor = os.environ.get(variavel, "").strip()
    return valor if valor and Path(valor).exists() else ""


def caminho_ffmpeg() -> str:
    """O ffmpeg a executar (embutido > PATH > nome puro)."""
    return _da_variavel(VAR_FFMPEG) or shutil.which("ffmpeg") or "ffmpeg"


def caminho_ffprobe() -> str:
    """O ffprobe a executar (embutido > PATH > nome puro)."""
    return _da_variavel(VAR_FFPROBE) or shutil.which("ffprobe") or "ffprobe"


def caminho_banco() -> Path:
    """O banco do acompanhamento. Fonte unica: o app aponta `LECSOR_BANCO` para a pasta do usuario
    (o banco sobrevive a atualizacao/reinstalacao); sem a variavel, e' o `db/` ao lado do codigo."""
    valor = os.environ.get(VAR_BANCO, "").strip()
    if valor:
        return Path(valor)
    return Path(__file__).resolve().parent.parent / "db" / "pipeline.db"


def onde_vem(qual: str = "ffmpeg") -> dict:
    """De onde vem o binario e qual versao — para a tela dizer, em vez de adivinhar."""
    embutido = _da_variavel(VAR_FFMPEG if qual == "ffmpeg" else VAR_FFPROBE)
    caminho = caminho_ffmpeg() if qual == "ffmpeg" else caminho_ffprobe()
    if embutido:
        origem = "embutido no app"
    elif caminho != qual:
        origem = "PATH da maquina"
    else:
        origem = "nenhum (nem embutido, nem PATH)"
    d = {"qual": qual, "origem": origem, "caminho": caminho if origem != "nenhum (nem embutido, nem PATH)" else ""}
    try:
        r = subprocess.run([caminho, "-hide_banner", "-version"], capture_output=True, text=True, timeout=30)
        primeira = (r.stdout or "").splitlines()[0] if r.stdout else ""
        d["versao"] = primeira.split(" Copyright")[0].strip()
    except Exception as e:  # noqa: BLE001
        d["versao"] = ""
        if origem == "nenhum (nem embutido, nem PATH)":
            d["erro"] = str(e)
    return d


def resumo() -> dict:
    """Os dois binarios de uma vez (usado pelo `/api/dispositivos` e pelo estado do servidor)."""
    return {"ffmpeg": onde_vem("ffmpeg"), "ffprobe": onde_vem("ffprobe")}


if __name__ == "__main__":  # prova rapida na linha de comando
    import json

    print(json.dumps(resumo(), ensure_ascii=False, indent=2))
