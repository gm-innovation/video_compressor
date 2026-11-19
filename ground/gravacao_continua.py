#!/usr/bin/env python3
"""GRAVACAO CONTINUA no PC de captura (dono, 19/11/2026).

Palavras do dono:

> "no computador de captura precisamos preparar o app para que em determinados casos termos um hd salvando
> full time as imagens do radar de oleo, as imagens devem ser comprimidas e guardadas para eventuais
> pesquisas, ou seja, mesmo que o cliente nao acione o streaming do radar de oleo, as imagens estarao
> sendo comprimidas e gravadas full time, o cliente pode acessar as imagens a qualquer momento"

> "nao precisaremos mais fazer o trabalho de conversao dos dados do radar de oleo em video, receberemos as
> imagens ja compiladas via hdmi, elas seguem o mesmo protocolo das cameras, recebemos as imagens,
> comprimimos, e enviamos (no caso do radar de oleo, gravamos tambem)"

> "pode ir gravando e quando acabar o espaco comeca a gravar por cima do mais antigo"

E a linha do tempo (para o cliente achar pelo horario):
> escolha do dono: "blocos menores e' o melhor, ate' mesmo pra encontrar os horarios na linha do tempo,
> pois o cliente vai procurar na linha do tempo de acordo com data e hora, podendo ser por filtro ou linha
> do tempo arrastavel"

Como funciona:
  * um ffmpeg proprio (o `gravador`), SEPARADO do streaming, abre a entrada de video (`dshow:<dispositivo>`)
    e grava em BLOCOS CURTOS num diretorio do HD local, com `-segment_atclocktime` (o bloco comeca no
    minuto cheio — e' o que faz a linha do tempo bater com o relogio);
  * o NOME do bloco carrega o inicio (bloco-AAAAMMDD-HHMMSS.mp4): responder "o que existe entre 14:03 e
    14:37" e' filtrar nome de arquivo, sem abrir video nenhum;
  * RETENCAO = ANEL: quando o espaco do volume acaba, o bloco MAIS ANTIGO e' apagado e a gravacao NAO para
    (o dono: "quando acabar o espaco comeca a gravar por cima do mais antigo");
  * nao depende de internet, de sessao nem da flag: e' a memoria local do radar;
  * nasce DESLIGADA — quem liga e' o admin (`LECSOR_GRAVACAO_CONTINUA=1` + dispositivo).

Uso:
    python ground/gravacao_continua.py                 # fica vivo, garantindo os blocos
    python ground/gravacao_continua.py --uma-vez       # uma passada (teste)
    python ground/gravacao_continua.py --estado        # so' mostra o estado e sai

Ambiente:
    LECSOR_GRAVACAO_CONTINUA   liga/desliga (1/0). Ausente = DESLIGADA.
    LECSOR_HD_DIR              onde os blocos ficam (padrao: ground/hd)
    LECSOR_BLOCO_SEGUNDOS      tamanho do bloco (padrao 60)
    LECSOR_HD_RESERVA_MB       espaco que NAO pode ser usado (padrao 512 MB) — ao bater, o mais antigo sai
    LECSOR_HD_DISPOSITIVO      dispositivo de video (dshow) — o radar no HDMI
    LECSOR_HD_CAMERA           rotulo/camera_id que o bloco serve (padrao: radar)
    LECSOR_HD_BITRATE          perfil de compressao (padrao 1500k)
    LECSOR_HD_RESOLUCAO        resolucao (padrao 1280x720)
    LECSOR_HD_FPS              quadros por segundo (padrao 30)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parent.parent
NOME_BLOCO = re.compile(r"^bloco-(\d{8})-(\d{6})\.mp4$")
LOG_DIR = RAIZ / "ground" / "hd"


def ligada() -> bool:
    """A gravacao continua esta' ligada? (o admin liga; ausente = desligada)."""
    v = (os.environ.get("LECSOR_GRAVACAO_CONTINUA") or "").strip().lower()
    return v in ("1", "sim", "true", "on", "ligada")


def diretorio() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("LECSOR_HD_DIR") or (RAIZ / "ground" / "hd"))
    return d


def bloco_segundos() -> int:
    try:
        v = int(float(os.environ.get("LECSOR_BLOCO_SEGUNDOS") or 60))
    except Exception:
        v = 60
    return max(2, min(3600, v))


def reserva_bytes() -> int:
    try:
        mb = float(os.environ.get("LECSOR_HD_RESERVA_MB") or 512)
    except Exception:
        mb = 512.0
    return int(max(16.0, mb) * 1024 * 1024)


def dispositivo() -> str:
    return (os.environ.get("LECSOR_HD_DISPOSITIVO") or "").strip()


def camera() -> str:
    return (os.environ.get("LECSOR_HD_CAMERA") or "radar").strip() or "radar"


def perfil() -> dict:
    return {"bitrate": (os.environ.get("LECSOR_HD_BITRATE") or "1500k").strip(),
            "resolucao": (os.environ.get("LECSOR_HD_RESOLUCAO") or "1280x720").strip(),
            "fps": (os.environ.get("LECSOR_HD_FPS") or "30").strip()}


def _log(linha: str) -> None:
    texto = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {linha}"
    print(texto, flush=True)
    try:
        (diretorio() / "log").mkdir(parents=True, exist_ok=True)
        with (diretorio() / "log" / "gravacao-continua.log").open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------------------------- blocos no disco
def _quando(nome: str):
    """Inicio do bloco pelo NOME (o nome e' o relogio). Devolve datetime ou None."""
    m = NOME_BLOCO.match(nome)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except Exception:
        return None


def blocos() -> list[dict]:
    """Os blocos que existem AGORA, do mais antigo para o mais novo (com tamanho e quando fecharam)."""
    d = diretorio()
    if not d.exists():
        return []
    saida = []
    for p in sorted(d.glob("bloco-*.mp4")):
        quando = _quando(p.name)
        if not quando:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        saida.append({"arquivo": p.name, "inicio": quando.isoformat(timespec="seconds"),
                      "bytes": st.st_size, "fim": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return saida


def blocos_no_intervalo(de: str, ate: str) -> list[dict]:
    """O que existe entre dois horarios (ISO). E' o que a LINHA DO TEMPO do cliente pergunta."""
    try:
        d0 = dt.datetime.fromisoformat(de)
        d1 = dt.datetime.fromisoformat(ate)
    except Exception:
        return []
    return [b for b in blocos() if d0 <= dt.datetime.fromisoformat(b["inicio"]) <= d1]


def resumo() -> dict:
    """Estado do HD do radar: quantos blocos, o primeiro, o ultimo, quanto ocupa, quanto ha' livre."""
    bs = blocos()
    try:
        uso = shutil.disk_usage(diretorio())
        livre, total = uso.free, uso.total
    except OSError:
        livre = total = 0
    return {"ligada": ligada(), "dispositivo": dispositivo(), "camera": camera(),
            "bloco_segundos": bloco_segundos(), "diretorio": str(diretorio()),
            "blocos": len(bs), "bytes": sum(b["bytes"] for b in bs),
            "primeiro": bs[0]["inicio"] if bs else "", "ultimo": bs[-1]["inicio"] if bs else "",
            "livre_bytes": livre, "total_bytes": total,
            "proximo_bloco_em": (max(0.0, bloco_segundos() - (time.time() % bloco_segundos()))
                                 if ligada() else 0.0)}


def _mais_antigo():
    bs = blocos()
    return (diretorio() / bs[0]["arquivo"]) if bs else None


def manter_anel(quantos: int = 1) -> list[str]:
    """Espaco acabou? Apaga o bloco MAIS ANTIGO e segue gravando (anel). Devolve o que saiu."""
    d = diretorio()
    fora = []
    if not d.exists():
        return fora
    for _ in range(max(1, quantos)):
        try:
            uso = shutil.disk_usage(d)
        except OSError:
            return fora
        if uso.free >= reserva_bytes():
            return fora
        alvo = _mais_antigo()
        if not alvo:
            return fora
        try:
            alvo.unlink()
            fora.append(alvo.name)
            _log(f"anel: espaco no fim — apaguei o bloco mais antigo ({alvo.name})")
        except OSError as e:
            _log(f"aviso: nao consegui apagar o bloco {alvo.name} ({e})")
            return fora
    return fora


# ---------------------------------------------------------------------------------------- gravador
def comando_do_gravador() -> list:
    p = perfil()
    d = diretorio()
    return ["ffmpeg", "-hide_banner", "-nostdin",
            "-rtbufsize", "512M",
            "-f", "dshow", "-framerate", p["fps"], "-video_size", p["resolucao"],
            "-i", f"video={dispositivo()}",
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", p["bitrate"], "-maxrate", p["bitrate"], "-bufsize", "2M",
            "-g", p["fps"],
            "-f", "segment", "-segment_time", str(bloco_segundos()),
            "-segment_atclocktime", "1", "-reset_timestamps", "1",
            "-strftime", "1", str(d / "bloco-%Y%m%d-%H%M%S.mp4")]


def gravar(ficheiro_log=None):
    """Sobe o gravador (bloqueante). Quem chama e' o `rodar()` — que garante que ele volte se cair."""
    d = diretorio()
    d.mkdir(parents=True, exist_ok=True)
    (d / "log").mkdir(parents=True, exist_ok=True)
    log = open(ficheiro_log or (d / "log" / "gravador.log"), "ab")
    return subprocess.Popen(comando_do_gravador(), cwd=str(RAIZ), stdout=log, stderr=subprocess.STDOUT)


def rodar(uma_vez: bool = False) -> int:
    """Fica vivo: garante o gravador de pe', mantem o anel e publica o resumo. Nada de internet aqui."""
    if not ligada():
        _log("gravacao continua DESLIGADA (LECSOR_GRAVACAO_CONTINUA): nao ha' o que gravar")
        return 0
    if not dispositivo():
        _log("gravacao continua ligada mas SEM dispositivo (LECSOR_HD_DISPOSITIVO): nada a fazer")
        return 2
    _log(f"gravacao continua no ar: camera {camera()} · dispositivo {dispositivo()} · "
         f"blocos de {bloco_segundos()}s em {diretorio()}")
    proc = None
    while True:
        if proc is None or proc.poll() is not None:
            saida = manter_anel()
            if saida:
                _log(f"anel: saiu {len(saida)} bloco(s) antigo(s)")
            proc = gravar()
            _log(f"gravador no ar (pid {proc.pid})")
        if uma_vez:
            time.sleep(0.5)
            return 0
        time.sleep(2.0)


def principal() -> int:
    args = sys.argv[1:]
    if "--estado" in args:
        print(json.dumps(resumo(), ensure_ascii=False, indent=1))
        return 0
    return rodar(uma_vez="--uma-vez" in args)


if __name__ == "__main__":
    raise SystemExit(principal())
