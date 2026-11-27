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
  * nasce DESLIGADA — quem liga e' o ADMIN, pelo botao da tela: terra publica a configuracao
    `gravacao_continua` (0/1), o bordo OLHA e aplica, escrevendo o DESEJO no `ligada.txt` do HD
    (`LECSOR_HD_DIR`) — o `LECSOR_GRAVACAO_CONTINUA=1` fica so' como padrao da INSTALACAO.

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


def _arquivo_do_desejo() -> pathlib.Path:
    """O DESEJO do admin (ligar/desligar) mora em ARQUIVO, dentro do HD da gravacao (dono, 26/11/2026).

    E' o que o botao do admin escreve (config publicada -> o bordo OLHA -> API local -> aqui) e o que o
    laco vivo obedece. Fica junto dos blocos (`LECSOR_HD_DIR`) para nao sujar o pacote e para o teste
    poder apontar para uma pasta temporaria. Sem isso, ligar exigiria mexer em variavel de ambiente e
    reiniciar o servico — e o admin so' tem a tela."""
    return diretorio() / "ligada.txt"


def desejo() -> str:
    """O que o admin pediu: "" (nunca decidido), "0" (desligar) ou "1" (ligar)."""
    try:
        v = _arquivo_do_desejo().read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return v if v in ("0", "1") else ""


def ligada() -> bool:
    """A gravacao continua esta' ligada?

    Quem manda e' o DESEJO escrito pela tela (arquivo); sem ele, vale a variavel de ambiente da
    instalacao (LECSOR_GRAVACAO_CONTINUA); ausente = DESLIGADA (nasce desligada)."""
    d = desejo()
    if d == "1":
        return True
    if d == "0":
        return False
    v = (os.environ.get("LECSOR_GRAVACAO_CONTINUA") or "").strip().lower()
    return v in ("1", "sim", "true", "on", "ligada")


def _arquivo_do_pid() -> pathlib.Path:
    return diretorio() / "gravador.pid"


def _pid_vivo(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def gravador_pid() -> int:
    try:
        return int((_arquivo_do_pid().read_text(encoding="utf-8").strip() or 0))
    except Exception:
        return 0


def _subir_gravador():
    """Sobe o laco do gravador DESACOPLADO do servidor de captura. 0 = ja' estava de pe'."""
    if _pid_vivo(gravador_pid()):
        return 0
    diretorio().mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve())],
                             cwd=str(RAIZ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=(0x00000008 | 0x00000200) if os.name == "nt" else 0)
    except Exception as e:  # noqa: BLE001
        _log(f"aviso: nao consegui subir o gravador ({e})")
        return 0
    try:
        _arquivo_do_pid().write_text(str(p.pid), encoding="utf-8")
    except Exception:
        pass
    _log(f"gravador subido pelo desejo do admin (pid {p.pid})")
    return p.pid


def _parar_gravador() -> bool:
    pid = gravador_pid()
    if not _pid_vivo(pid):
        return False
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
        else:
            os.kill(pid, 15)
    except Exception as e:  # noqa: BLE001
        _log(f"aviso: nao consegui parar o gravador (pid {pid}): {e}")
        return False
    try:
        _arquivo_do_pid().unlink()
    except Exception:
        pass
    _log(f"gravador parado a pedido (pid {pid})")
    return True


def ligar() -> str:
    """LIGA a gravacao continua: escreve o desejo e garante o gravador de pe'. Devolve o motivo REAL."""
    diretorio().mkdir(parents=True, exist_ok=True)
    _arquivo_do_desejo().write_text("1", encoding="utf-8")
    if not dispositivo():
        r = resolucao(recarregar=True)
        _log(f"gravacao continua LIGADA mas SEM dispositivo de video: {r.get('motivo')}")
        return f"ligada, mas nada sera' gravado: {r.get('motivo') or 'sem dispositivo de video'}"
    pid = _subir_gravador()
    return (f"gravacao continua ligada (gravador no ar, pid {pid})" if pid
            else "gravacao continua ligada (o gravador ja' estava de pe')")


def desligar() -> str:
    """DESLIGA: o desejo vira 0 (o laco vivo sai sozinho) e o gravador e' parado agora."""
    _arquivo_do_desejo().write_text("0", encoding="utf-8")
    parado = _parar_gravador()
    return "gravacao continua desligada" + (" e gravador parado" if parado else "")


def gravando_agora() -> bool:
    """ESTA' GRAVANDO DE VERDADE? Ligada E gravador de pe' E bloco recente.

    Nao basta o desejo: sem quadro chegando nao ha' bloco novo, e a tela nao pode dizer "gravando"."""
    if not ligada():
        return False
    pid = gravador_pid()
    if pid and not _pid_vivo(pid):
        return False
    bs = blocos()
    if not bs:
        return False
    try:
        ultimo = dt.datetime.fromisoformat(bs[-1]["inicio"])
    except Exception:
        return False
    return (dt.datetime.now() - ultimo).total_seconds() <= 2 * bloco_segundos() + 30


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


RESOLUCAO_SEGUNDOS = 60.0
_RESOLUCAO: dict = {"em": 0.0, "valor": None}


def _modulo_da_api():
    """O módulo da API: o `__main__` do servidor (`python ground/api.py`) ou o `api` importado.

    Evita importar uma SEGUNDA cópia do módulo dentro do processo do servidor (o `import api` criaria
    outro módulo, com outra conexão, além da que já está rodando).
    """
    m = sys.modules.get("__main__")
    if m is not None and hasattr(m, "dispositivo_do_radar"):
        return m
    # O python EMBUTIDO do pacote (`tools/python/python312._pth`) monta o `sys.path` só com
    # `python312.zip`, `.` e `Lib\site-packages`: a pasta DO SCRIPT não entra. Rodando o laco
    # como processo separado (o caso do app instalado), o `import api` explodia com
    # `ModuleNotFoundError: No module named 'api'` e o gravador saia sem gravar nada.
    aqui = str(pathlib.Path(__file__).resolve().parent)
    if aqui not in sys.path:
        sys.path.insert(0, aqui)
    import api  # noqa: PLC0415  (o gravador rodando sozinho, fora do servidor)
    return api


def _do_cadastro() -> dict:
    """O que o CADASTRO desta máquina diz sobre o radar (a câmera do tipo que o admin escolheu).

    Quem responde é o `api.dispositivo_do_radar()` (leitura pura do banco local + a lista de
    dispositivos). Sem `api` (módulo isolado, teste), devolve vazio COM o motivo.
    """
    try:
        return dict(_modulo_da_api().dispositivo_do_radar() or {})
    except Exception as e:  # noqa: BLE001
        return {"dispositivo": "", "origem": "",
                "motivo": f"nao consegui ler o cadastro desta maquina ({type(e).__name__}: {e})"}


def resolucao(recarregar: bool = False) -> dict:
    """Qual dispositivo de vídeo serve o HD, de onde ele veio e — quando não há — o MOTIVO.

    Regra do dono (26/11/2026): **o TIPO que o admin escolheu manda** ("ele precisa detectar pelo nome
    que eu crio em terra ou pelo tipo que e' selecionado do app do admin"). Ordem:
      1. `LECSOR_HD_DISPOSITIVO` — override de técnico/bancada (não é exigido);
      2. o cadastro do admin: a câmera de tipo `radar` e o dispositivo dela;
      3. nada casa → VAZIO com o motivo (nunca "ligada" que não grava).
    Fica em cache por 60 s: o laço do gravador pergunta a cada 2 s e a lista de dispositivos custa ~1 s.
    """
    agora = time.time()
    guardada = _RESOLUCAO.get("valor")
    if not recarregar and guardada is not None and agora - float(_RESOLUCAO.get("em") or 0) < RESOLUCAO_SEGUNDOS:
        return dict(guardada)
    ambiente = (os.environ.get("LECSOR_HD_DISPOSITIVO") or "").strip()
    if ambiente:
        r = {"dispositivo": ambiente, "origem": "env", "motivo": "", "camera": "", "rotulo": "", "nome": ""}
    else:
        cadastro = _do_cadastro()
        if cadastro.get("dispositivo"):
            r = {"dispositivo": cadastro["dispositivo"], "origem": cadastro.get("origem") or "cadastro",
                 "motivo": "", "camera": cadastro.get("camera") or "",
                 "rotulo": cadastro.get("rotulo") or "", "nome": cadastro.get("nome") or ""}
        else:
            r = {"dispositivo": "", "origem": "", "camera": cadastro.get("camera") or "",
                 "rotulo": cadastro.get("rotulo") or "", "nome": "",
                 "motivo": cadastro.get("motivo") or "nao ha dispositivo: nenhuma camera de radar no cadastro"}
    _RESOLUCAO.update(em=agora, valor=dict(r))
    return r


def dispositivo() -> str:
    return resolucao()["dispositivo"]


def origem() -> str:
    """De onde veio o dispositivo: `env`, `tipo` (o que o admin escolheu), `nome` ou `cadastro`."""
    return resolucao().get("origem") or ""


def camera() -> str:
    return (os.environ.get("LECSOR_HD_CAMERA") or "radar").strip() or "radar"


def camera_id() -> str:
    """O ID da câmera que os blocos servem: a do radar do cadastro (a que o admin nomeou) ou "radar"."""
    return (resolucao().get("camera") or "").strip() or camera()


def rotulo() -> str:
    """O NOME que o admin deu ao radar em terra (é ele que o bloco carrega). Sem nome, o alvo ("radar")."""
    return (resolucao().get("rotulo") or "").strip() or camera()


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
    r = resolucao()
    try:
        uso = shutil.disk_usage(diretorio())
        livre, total = uso.free, uso.total
    except OSError:
        livre = total = 0
    # `gravando` e' a MEDIDA, nao o desejo (dono, 27/11/2026: o HD ficou 0 blocos enquanto as telas
    # diziam "gravando"/"ligada"). Vai no resumo para o catalogo de terra e as duas telas: ligada mas
    # sem gravador de pe' tem que aparecer como NAO gravando.
    return {"ligada": ligada(), "gravando": gravando_agora(),
            "dispositivo": r["dispositivo"], "dispositivo_origem": r.get("origem") or "",
            "motivo": r.get("motivo") or "", "camera": camera(), "camera_id": camera_id(),
            "camera_rotulo": rotulo(), "nome_dispositivo": r.get("nome") or "",
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
        r = resolucao(recarregar=True)
        _log(f"gravacao continua ligada mas SEM dispositivo de video: {r.get('motivo')} — nada a fazer")
        return 2
    r0 = resolucao()
    _log(f"gravacao continua no ar: camera {rotulo()} ({camera_id()}) · dispositivo {dispositivo()} "
         f"(origem {origem()}{', nome ' + r0['nome'] if r0.get('nome') else ''}) · "
         f"blocos de {bloco_segundos()}s em {diretorio()}")
    try:
        _arquivo_do_pid().write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    proc = None
    while True:
        # O DESEJO manda (dono, 26/11/2026): desligou na tela, o laco sai e o gravador para — sem
        # reiniciar servico e sem ninguem entrar na maquina.
        if not ligada():
            _log("gravacao continua DESLIGADA pelo desejo da tela: saindo")
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                _arquivo_do_pid().unlink()
            except Exception:
                pass
            return 0
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
