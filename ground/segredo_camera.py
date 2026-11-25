"""Segredo da camera de REDE (RTSP): vive SO' no PC de captura.

Dono (25/11/2026, verbatim): "senha nao pode vazar, entao tem que tudo ficar no bordo, entao nao vamos
poder inserir nem o ip no admin, o cadastro das cameras ip terao que ser no app de captura".

Consequencia: o cadastro da camera de rede (endereco/porta/canal) e' feito NO PC DE CAPTURA, e a
credencial nao entra no banco, no repositorio, no chat, no log nem em resposta de API. O que a tela
mostra e' so' "segredo configurado: sim/nao" — nunca o valor.

ONDE O SEGREDO MORA (D1 do dono: "a forma mais segura"):

  - Windows: %PROGRAMDATA%\\LECSOR\\segredos\\cam-<id>.txt
  - Linux:   ~/.lecsor/segredos/cam-<id>.txt
  - ou a pasta que LECSOR_SEGREDOS apontar.
  - a variavel de ambiente LECSOR_CAM_<ID>_SEGREDO tem PRECEDENCIA (cofre/servico do Windows).

CONTEUDO do arquivo: UMA linha, no formato ``usuario:senha`` (ou so' a senha — nesse caso vale o
usuario `admin`, que e' o padrao de fabrica da maioria das cameras). O arquivo e' escrito A MAO, no PC
de captura: o produto NUNCA pede senha em formulario.

LIMITE HONESTO (declarado no plano aprovado): o ffmpeg recebe a URL com a credencial, entao ela aparece
na linha de comando do processo — visivel para ADMIN LOCAL daquela maquina (o dono dela). Nao ha
vazamento para o lado terra, para o banco, para o repositorio, para o chat ou para o app do cliente:
por isso `url_com_segredo()` e' a UNICA funcao que devolve o valor, e `redigir()` limpa qualquer log.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote

USUARIO_PADRAO = "admin"


def pasta() -> Path:
    """A pasta dos segredos DESTA maquina (nunca sai daqui)."""
    por_env = (os.environ.get("LECSOR_SEGREDOS") or "").strip()
    if por_env:
        return Path(por_env)
    if os.name == "nt":
        base = (os.environ.get("PROGRAMDATA") or "").strip() or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "LECSOR" / "segredos"
    return Path.home() / ".lecsor" / "segredos"


def _identificador(camera_id: str) -> str:
    """Nome de arquivo seguro para o id da camera (mesma regra do id em todo o produto)."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "-", str(camera_id or "").strip())[:80] or "cam"


def caminho(camera_id: str) -> Path:
    return pasta() / f"cam-{_identificador(camera_id)}.txt"


def nome_da_variavel(camera_id: str) -> str:
    """A variavel de ambiente que pode substituir o arquivo (cofre/servico do Windows)."""
    return "LECSOR_CAM_" + re.sub(r"[^A-Za-z0-9]", "_", str(camera_id or "")).upper() + "_SEGREDO"


def _do_ambiente(camera_id: str) -> str:
    return (os.environ.get(nome_da_variavel(camera_id)) or "").strip()


def ler(camera_id: str) -> tuple[str, str] | None:
    """(usuario, senha) do segredo desta camera — DESTA maquina. None = nao configurado.

    NUNCA devolva o par para a tela, para o log ou para o lado terra.
    """
    bruto = _do_ambiente(camera_id)
    if not bruto:
        p = caminho(camera_id)
        try:
            if not p.exists():
                return None
            bruto = p.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
    if not bruto:
        return None
    primeira = bruto.splitlines()[0].strip()
    if not primeira:
        return None
    if ":" in primeira:
        usuario, senha = primeira.split(":", 1)
        return (usuario.strip() or USUARIO_PADRAO, senha)
    return (USUARIO_PADRAO, primeira)


def configurado(camera_id: str) -> bool:
    """A tela so' mostra isto: sim/nao. Nunca o valor."""
    par = ler(camera_id)
    return bool(par and par[1])


def origem(camera_id: str) -> str:
    """De onde o segredo esta vindo (texto tecnico, sem o valor): 'ambiente' | 'arquivo' | ''."""
    if _do_ambiente(camera_id):
        return "ambiente"
    return "arquivo" if caminho(camera_id).exists() else ""


def esquecer(camera_id: str) -> bool:
    """Apaga o ARQUIVO do segredo desta camera (nao mexe em variavel de ambiente)."""
    try:
        p = caminho(camera_id)
        if p.exists():
            p.unlink()
            return True
    except OSError:
        return False
    return False


def url_com_segredo(endereco: str, camera_id: str) -> str | None:
    """Monta a URL do RTSP com a credencial LOCAL: rtsp://usuario:senha@ip:porta/caminho.

    `endereco` vem do cadastro do bordo (identidade, SEM credencial): ex. "10.0.0.7:554/1" ou
    "10.0.0.7:554/Streaming/Channels/101". Devolve None quando nao ha segredo configurado — quem
    chama tem de dizer na tela que falta configurar, nunca mandar credencial vazia para a camera.
    """
    par = ler(camera_id)
    if not par:
        return None
    usuario, senha = par
    alvo = str(endereco or "").strip()
    if not alvo:
        return None
    esquema = "rtsp"
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://(.*)$", alvo)
    if m:
        esquema, alvo = (m.group(1).lower(), m.group(2))
        esquema = esquema if esquema in ("rtsp", "rtsps", "http", "https") else "rtsp"
    if not alvo:
        return None
    return f"{esquema}://{quote(usuario, safe='')}:{quote(senha, safe='')}@{alvo}"


def redigir(texto: str | None, camera_id: str | None = None) -> str:
    """Tira a credencial de qualquer texto que va' para log, banco ou tela.

    Cinto e suspensorio: a URL com senha so' existe na linha de comando do ffmpeg. Se um pedaco dela
    cair num log (o ffmpeg imprimir a URL de entrada, por exemplo), aqui ela sai mascarada.
    """
    t = str(texto or "")
    if not t:
        return t
    pares = [ler(camera_id)] if camera_id else []
    for par in pares:
        if not par:
            continue
        usuario, senha = par
        for pedaco in (f"{quote(usuario, safe='')}:{quote(senha, safe='')}",
                       f"{usuario}:{senha}"):
            if pedaco and pedaco in t:
                t = t.replace(pedaco, f"{usuario}:***")
    # qualquer userinfo de URL que sobrou (rtsp://algo:algo@host) sai mascarado
    return re.sub(r"((?:rtsps?|https?)://[^:/@\s]+):[^@\s]+@", r"\1:***@", t)
