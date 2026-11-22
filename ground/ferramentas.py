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


# ------------------------------------------------------------------ ambiente do pacote (plug & play)
# O instalador grava `ambiente.json` DENTRO do pacote (Supabase, token de ingestao, embarcacao). Ele
# nasce em `ground/ambiente.json`; o app lia so' `ambiente.json` na raiz do repositorio e por isso o
# servidor subia SEM token nem embarcacao — e o anuncio do cadastro ao lado terra falhava em silencio
# ("sem lado terra/token de ingestao"), deixando a camera fora de "Tempo real", "Producao" e da tela
# do cliente (medido 18/11/2026). Aqui o proprio python carrega o arquivo, em qualquer uma das duas
# posicoes, sem sobrepor o que ja' veio do ambiente (bancada e systemd mandam).
AMBIENTE_ARQUIVOS = (("ambiente.json",), ("ground", "ambiente.json"))


def caminhos_do_ambiente() -> list[Path]:
    raiz = Path(__file__).resolve().parent.parent
    return [raiz.joinpath(*partes) for partes in AMBIENTE_ARQUIVOS]


def carregar_ambiente() -> dict:
    """Le o `ambiente.json` do pacote para o ambiente do processo. Devolve o que FALTOU, para a tela.

    `LECSOR_SEM_AMBIENTE=1` desliga a leitura. Serve para as PROVAS: sem isto, toda prova que sobe um
    servidor proprio herda o lado terra (VPS), o token e o Supabase do `ambiente.json` que esta' no
    repositorio, e passa a falar com a producao em vez de responder em casa — foi medido em 19/11/2026
    (`tests/test-escopos-de-acesso.py` com 17 falhas por isso: as listas vinham vazias, do lado terra).
    """
    import json

    faltando: dict = {}
    if os.environ.get("LECSOR_SEM_AMBIENTE", "").strip() == "1":
        return faltando
    for arquivo in caminhos_do_ambiente():
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(dados, dict):
            continue
        for chave, valor in dados.items():
            if isinstance(valor, str) and valor.strip() and not os.environ.get(chave, "").strip():
                os.environ[chave] = valor.strip()
    for chave in ("LECSOR_TOKEN_INGESTAO", "LECSOR_EMBARCACAO", "LECSOR_LADO_TERRA_API"):
        if not os.environ.get(chave, "").strip():
            faltando[chave] = "ausente"
    return faltando


def meus_enderecos() -> set:
    """Os IPs desta maquina: loopback, os do nome do host e o que a rota de saida usa."""
    import socket

    meus = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
    try:
        meus.add(socket.gethostbyname(socket.gethostname()))
        meus.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:  # noqa: BLE001
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # nao envia nada: so' descobre a rota
        s.connect(("8.8.8.8", 80))
        meus.add(s.getsockname()[0])
        s.close()
    except Exception:  # noqa: BLE001
        pass
    return meus


def minha_porta() -> int:
    """A porta em que ESTE servidor atende: `LECSOR_PORTA_API`, o argumento (`api.py 8085`), 8765.

    O lado terra sobe por systemd como `python3 ground/api.py 8085` e o pacote do PC de captura pelo
    `LECSOR_PORTA_API` — sao as duas formas em uso, e sem saber a porta nao da' para distinguir "esta
    maquina" de "outra maquina com o mesmo IP" (a prova levanta um lado terra falso em 127.0.0.1).
    """
    try:
        v = os.environ.get("LECSOR_PORTA_API")
        if v:
            return int(v)
    except Exception:  # noqa: BLE001
        pass
    try:
        import sys

        for a in list(getattr(sys, "argv", []))[1:]:
            if str(a).strip().isdigit():
                return int(str(a).strip())
    except Exception:  # noqa: BLE001
        pass
    return 8765


def eh_esta_maquina(url: str) -> bool:
    """O endereco aponta para ESTE servidor? (evita o servidor encaminhar para si mesmo).

    O `ambiente.json` do pacote traz `LECSOR_LADO_TERRA_API`. Numa instalacao cujo papel E' o lado terra
    esse endereco e' o dela propria — e o servidor passou a encaminhar as proprias telas para si, dando
    502 em `/admin/` (medido 18/11/2026, logo depois de ligar a leitura do ambiente no boot).

    Precisa ser IP **e porta** deste servidor: so' o IP nao basta. Numa prova com um lado terra falso em
    `127.0.0.1:<outra porta>` o anuncio seria engolido como "esta maquina" e o cadastro nunca chegaria.
    """
    from urllib.parse import urlparse

    try:
        u = urlparse(url)
        host = (u.hostname or "").strip().lower()
    except Exception:  # noqa: BLE001
        return False
    if not host or host not in {h.lower() for h in meus_enderecos()}:
        return False
    porta = u.port or (443 if (u.scheme or "").lower() == "https" else 80)
    return porta == minha_porta()


if __name__ == "__main__":  # prova rapida na linha de comando
    import json

    print(json.dumps(resumo(), ensure_ascii=False, indent=2))
