#!/usr/bin/env python3
"""Gravacao do LADO TERRA: grava o video que JA' CHEGOU pela rede (decisao do dono, 17/11/2026).

Por que aqui e nao no bordo: o link da embarcacao custa banda — gravar no bordo gastaria o link duas
vezes (uma para transmitir, outra para subir a gravacao). Aqui grava-se o que chegou, com `-c copy`:
o arquivo sao os BITS QUE CHEGARAM, sem reencode.

Quem manda gravar e' a tela do cliente, na sessao da transmissao. **Enquanto grava, o corte por TEMPO
nao acontece** (decisao do dono): gravacao nao pode ser picada no meio. Ao parar, o arquivo fica no
historico — nada e' apagado.

Uso pela API (nao tem linha de comando de producao; a tela manda):
    iniciar(transmissao_id, fluxo)  -> {"ok": True, "arquivo": ..., "pid": ...}
    parar(transmissao_id)           -> {"ok": True, "arquivo": ..., "bytes": ..., "segundos": ...}
    estado(transmissao_id)          -> {"gravando": bool, "arquivo": ..., "bytes": ..., "segundos": ...}
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))
from ferramentas import caminho_ffmpeg  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PORTA_RTSP_PADRAO = 8554
ESPERA_PADRAO = 6.0          # quanto se espera o ffmpeg fechar o arquivo ao parar
ESPERA_SUBIDA = 5.0          # quanto se espera o fluxo mandar o 1o pedaco antes de dizer que falhou


def diretorio() -> Path:
    """Onde as gravacoes ficam (env `LECSOR_GRAVACOES_DIR` para tirar do repositorio em producao)."""
    d = Path(os.environ.get("LECSOR_GRAVACOES_DIR") or (RAIZ / "ground" / "gravacoes"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitizar(tid: str) -> str:
    """O id vem da URL: vira so' [a-zA-Z0-9_-] antes de virar nome de arquivo."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "-", str(tid or "").strip())[:60] or "gravacao"


def arquivo(tid: str) -> Path:
    """O arquivo FINAL (mp4 normal, com moov: abre em qualquer programa)."""
    return diretorio() / f"{sanitizar(tid)}.mp4"


def parcial(tid: str) -> Path:
    """O arquivo ENQUANTO GRAVA: mp4 fragmentado — se a maquina morrer no meio, ele ainda abre.

    (mp4 normal so' ganha o indice no fim; um kill no meio deixaria um arquivo imprestavel. Com
    fragmentos o que ja' chegou continua legivel, e no fim ele e' remontado no arquivo final.)
    """
    return diretorio() / f"{sanitizar(tid)}.parcial.mp4"


def _trava(tid: str) -> Path:
    return diretorio() / f"{sanitizar(tid)}.json"


def _processo_vivo(pid) -> bool:
    if not pid:
        return False
    try:
        bruto = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                               capture_output=True, timeout=5).stdout
        saida = (bruto or b"").decode("utf-8", "ignore") or (bruto or b"").decode("cp850", "ignore")
        return str(int(pid)) in saida
    except Exception:
        return False


def _ficha(tid: str) -> dict:
    try:
        return json.loads(_trava(tid).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gravar_ficha(tid: str, d: dict) -> None:
    _trava(tid).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _matar(pid) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=15)
    except Exception:
        pass


def _segundos_desde(iniciado) -> int:
    try:
        return max(0, int(time.time() - float(iniciado)))
    except Exception:
        return 0


def estado(tid: str) -> dict:
    """Se esta' gravando de verdade: o processo vivo E a ficha em disco dizem a mesma coisa."""
    f = _ficha(tid)
    final, meio = arquivo(tid), parcial(tid)
    vivo = bool(f.get("pid")) and _processo_vivo(f["pid"])
    vendo = meio if (vivo or not final.exists()) else final
    return {"gravando": vivo, "arquivo": str(vendo) if vendo.exists() else "",
            "bytes": vendo.stat().st_size if vendo.exists() else 0,
            "segundos": _segundos_desde(f.get("iniciado_em")) if vivo else 0,
            "fluxo_id": f.get("fluxo_id", "")}


# --- Download x apagamento ----------------------------------------------------------------
# O cliente baixa e SAI da tela; o arquivo e' apagado (decisao do dono, 18/11/2026). Sem esta
# trava, o arquivo podia ser apagado no meio de um download e o cliente levaria um mp4 pela
# metade. `abrir_para_baixar`/`fechar_para_baixar` marcam o download em andamento; `apagar`
# espera ele terminar (quem chama tenta de novo no proximo ciclo).
_baixando: dict[str, int] = {}
_trava_baixando = threading.Lock()


def abrir_para_baixar(tid: str) -> None:
    with _trava_baixando:
        _baixando[tid] = _baixando.get(tid, 0) + 1


def fechar_para_baixar(tid: str) -> None:
    with _trava_baixando:
        if _baixando.get(tid):
            _baixando[tid] -= 1
            if _baixando[tid] <= 0:
                _baixando.pop(tid, None)


def baixando(tid: str) -> bool:
    with _trava_baixando:
        return bool(_baixando.get(tid))


def apagar(tid: str) -> dict:
    """APAGA O ARQUIVO da gravacao (mp4 final, sobra .parcial, ficha e log).

    Nao apaga o HISTORICO: quem pediu, quem gravou, quem baixou e quando foi apagado continuam na
    auditoria. Devolve `adiado` quando ha' download em andamento — quem chama tenta depois.
    """
    if baixando(tid):
        return {"ok": False, "adiado": True, "motivo": "tem download em andamento", "bytes": 0, "arquivos": []}
    livre, apagados = 0, []
    for p in (arquivo(tid), parcial(tid), _trava(tid), diretorio() / f"{sanitizar(tid)}.log"):
        try:
            if p.exists():
                livre += p.stat().st_size
                p.unlink()
                apagados.append(p.name)
        except Exception:
            pass
    return {"ok": True, "adiado": False, "bytes": livre, "arquivos": apagados}


def _porta() -> int:
    """Mesma porta que o resto do sistema usa para o mediamtx local (`trecho.py`)."""
    try:
        return int(os.environ.get("LECSOR_PORTA_RTSP") or PORTA_RTSP_PADRAO)
    except Exception:
        return PORTA_RTSP_PADRAO


def iniciar(tid: str, fluxo: str, host: str = "127.0.0.1", porta: int = 0) -> dict:
    """Comeca a gravar o fluxo que JA' ESTA' chegando no mediamtx desta maquina (lado terra)."""
    if not str(fluxo or "").strip():
        return {"erro": "sem fluxo para gravar"}
    atual = estado(tid)
    if atual["gravando"]:
        return {"ok": True, "ja_gravando": True, **atual}
    saida = parcial(tid)
    log = diretorio() / f"{sanitizar(tid)}.log"
    url = f"rtsp://{host}:{int(porta) if porta else _porta()}/{fluxo}"
    cmd = [caminho_ffmpeg(), "-nostdin", "-loglevel", "warning", "-rtsp_transport", "tcp",
           "-timeout", "5000000",          # nunca fica pendurado esperando um fluxo que nao responde
           "-i", url, "-c", "copy",
           "-movflags", "+frag_keyframe+empty_moov+default_base_moof",   # sobrevive a kill
           "-f", "mp4", "-y", str(saida)]
    try:
        with log.open("wb") as lg:
            proc = subprocess.Popen(cmd, stdout=lg, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        return {"erro": f"nao consegui iniciar a gravacao ({type(e).__name__}: {e})"}
    # um ffmpeg VIVO mas sem arquivo NAO e' gravacao: espera o fluxo mandar o primeiro pedaco.
    # (aconteceu de verdade: sem fluxo no ar o ffmpeg ficava pendurado e a tela dizia que gravava)
    fim = time.time() + ESPERA_SUBIDA
    while time.time() < fim:
        if not _processo_vivo(proc.pid):
            break
        if saida.exists() and saida.stat().st_size > 0:
            break
        time.sleep(0.4)
    if not (saida.exists() and saida.stat().st_size > 0):
        _matar(proc.pid)
        detalhe = ""
        try:
            detalhe = log.read_text(encoding="utf-8", errors="replace")[-300:]
        except Exception:
            pass
        return {"erro": f"o fluxo {fluxo} nao mandou imagem nenhuma em {int(ESPERA_SUBIDA)} s "
                        f"(ele esta' no ar? a camera esta' ligada?) {detalhe}".strip()}
    _gravar_ficha(tid, {"pid": proc.pid, "iniciado_em": time.time(), "fluxo_id": fluxo,
                        "arquivo": str(saida), "url": url})
    return {"ok": True, "arquivo": str(saida), "pid": proc.pid, "fluxo_id": fluxo}


def parar(tid: str, espera: float = ESPERA_PADRAO) -> dict:
    """Termina a gravacao (o ffmpeg fecha o mp4) e devolve o que ficou no disco."""
    f = _ficha(tid)
    p = arquivo(tid)
    if f.get("pid") and _processo_vivo(f["pid"]):
        _matar(f["pid"])
        fim = time.time() + espera
        while time.time() < fim and _processo_vivo(f["pid"]):
            time.sleep(0.3)
    duracao = _segundos_desde(f.get("iniciado_em")) if f else 0
    # remonta o parcial (fragmentado) no arquivo final: agora sim um mp4 que abre em qualquer lugar
    entregue, aviso = p, ""
    if parcial(tid).exists() and parcial(tid).stat().st_size > 0:
        try:
            r = subprocess.run([caminho_ffmpeg(), "-nostdin", "-loglevel", "error", "-i", str(parcial(tid)),
                                "-c", "copy", "-movflags", "+faststart", "-y", str(p)],
                               capture_output=True, timeout=120)
            if p.exists() and p.stat().st_size > 0:
                parcial(tid).unlink(missing_ok=True)
            else:
                entregue = parcial(tid)
                aviso = "nao consegui remontar o mp4 final; o arquivo gravado e' o .parcial.mp4"
        except Exception as e:
            entregue = parcial(tid)
            aviso = f"nao consegui remontar o mp4 final ({type(e).__name__}); entreguei o .parcial.mp4"
    ficha = {"ok": True, "arquivo": str(entregue) if entregue.exists() else "",
             "fluxo_id": f.get("fluxo_id", ""),
             "bytes": entregue.stat().st_size if entregue.exists() else 0,
             "segundos": duracao, "aviso": aviso}
    if f:
        _gravar_ficha(tid, {**f, "pid": 0, "parado_em": time.time(), "bytes": ficha["bytes"],
                            "segundos": duracao, "arquivo": ficha["arquivo"], "aviso": aviso})
    return ficha


def listar() -> list:
    """As gravacoes que ficaram no disco (o historico do cliente le daqui)."""
    saidas = []
    for p in sorted(g for g in diretorio().glob("*.mp4") if ".parcial." not in g.name):
        st = p.stat()
        saidas.append({"transmissao_id": p.stem, "arquivo": str(p), "bytes": st.st_size,
                       "modificado_em": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))})
    return saidas


def limpar_orfas() -> int:
    """Sobra de gravacao (a maquina reiniciou no meio): remonta o que der, limpa a sobra e marca.

    A VPS tem de ficar so' com o que foi gravado (dono, 18/11/2026): o fragmento bom vira mp4 final,
    a sobra imprestavel some. Nada de HISTORICO se apaga aqui — so' arquivo de video.
    Devolve quantas gravacoes ficaram orfas (marca na ficha), como antes.
    """
    n = 0
    for f in sorted(diretorio().glob("*.json")):
        tid = f.stem
        d = _ficha(tid)
        if not (d.get("pid") and not _processo_vivo(d["pid"])):
            continue
        # o fragmento sobreviveu ao reboot: tenta fechar o mp4 final (senao ele fica imprestavel)
        if parcial(tid).exists() and parcial(tid).stat().st_size > 0:
            if not (arquivo(tid).exists() and arquivo(tid).stat().st_size > 0):
                try:
                    subprocess.run([caminho_ffmpeg(), "-nostdin", "-loglevel", "error", "-i", str(parcial(tid)),
                                    "-c", "copy", "-movflags", "+faststart", "-y", str(arquivo(tid))],
                                   capture_output=True, timeout=180)
                    if arquivo(tid).exists() and arquivo(tid).stat().st_size > 0:
                        d = {**d, "bytes": arquivo(tid).stat().st_size,
                             "aviso": "mp4 final remontado no start (a maquina caiu gravando)"}
                        parcial(tid).unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                try:                       # o final esta' bom: o fragmento e' so' sobra
                    parcial(tid).unlink()
                except Exception:
                    pass
        _gravar_ficha(tid, {**d, "pid": 0, "orfao": True})
        n += 1
    return n


if __name__ == "__main__":   # consulta rapida na bancada
    if len(sys.argv) > 1 and sys.argv[1] == "listar":
        print(json.dumps(listar(), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1:
        print(json.dumps(estado(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
