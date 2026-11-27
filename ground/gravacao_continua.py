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

A ESCOLHA DO ADMIN (dono, 27/11/2026 — "qual disco e quanto dele") NAO usa variavel de ambiente: fica no
arquivo `ground/hd/config.json` (`{"disco": "D:\\", "pasta": "...", "cota_gb": 500}`), gravado pela rota
local quando a config publicada de terra chega. A escolha vence o padrao e perde para o `LECSOR_HD_DIR`
(override de bancada). O arquivo mora em lugar FIXO — trocar de disco nao apaga a escolha.
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import processos  # noqa: E402  (identidade de processo: um pid sozinho NAO e' identidade)

RAIZ = pathlib.Path(__file__).resolve().parent.parent
NOME_BLOCO = re.compile(r"^bloco-(\d{8})-(\d{6})\.mp4$")
LOG_DIR = RAIZ / "ground" / "hd"

# ------------------------------------------------------------------ O RELE' (dono, 27/11/2026)
# A camera do radar so' abre UMA vez (dshow) e o GRAVADOR e' quem a segura 24h. Sem isto, quando o
# cliente pedia o vivo da MESMA camera o app "liberava" o dispositivo (matando o gravador — medido em
# 27/11/2026: 5 blocos de 1 s e o laco morto) ou o vivo nao subia. Com o rele', o gravador PUBLICA o
# fluxo que ja' comprimiu no mediamtx DESTA maquina, e o vivo le' dali — ninguem abre a camera duas
# vezes. O caminho do rele' tem prefixo fixo e NAO entra no repasse para o lado terra (senao a banda
# iria embora 24h por dia): quem publica para o mundo e' o envio do vivo, so' quando alguem pede.
PREFIXO_DO_RELAY = "gravador-"
MEDIAMTX_RTSP = "127.0.0.1:8554"     # `rtspAddress` do ground/mediamtx.yml
MEDIAMTX_SRT = "127.0.0.1:8890"      # `srtAddress` do ground/mediamtx.yml


def relay_ligado() -> bool:
    """O rele' nasce LIGADO (e' o que deixa o gravador e o vivo conviverem). `LECSOR_HD_RELAY=0` desliga."""
    v = (os.environ.get("LECSOR_HD_RELAY") or "").strip().lower()
    return v not in ("0", "nao", "não", "no", "false", "off")


def _endereco_do_mediamtx(qual: str) -> str:
    if qual == "srt":
        return (os.environ.get("LECSOR_MEDIAMTX_SRT") or "").strip() or MEDIAMTX_SRT
    return (os.environ.get("LECSOR_MEDIAMTX_RTSP") or "").strip() or MEDIAMTX_RTSP


def fluxo_do_relay() -> str:
    """O nome do caminho no mediamtx local: `gravador-<fluxo_id da camera do radar>`.

    Usa o `fluxo_id` do cadastro (o mesmo nome que o vivo publica) para a tela e o mediamtx falarem a
    mesma lingua; sem cadastro, cai no `camera_id` e, em ultimo caso, no rotulo do perfil.
    """
    cam = camera_id()
    fluxo = ""
    try:
        db = _modulo_da_api()
        if db:
            with db.conexao() as c:
                r = c.execute("SELECT fluxo_id FROM cameras WHERE id=?", (cam,)).fetchone()
                if r:
                    fluxo = str(r["fluxo_id"] or "").strip()
    except Exception:
        fluxo = ""
    return PREFIXO_DO_RELAY + (fluxo or cam or "radar")


def url_do_relay() -> str:
    """Onde o vivo LE' o fluxo do gravador (RTSP no mediamtx desta maquina)."""
    return f"rtsp://{_endereco_do_mediamtx('rtsp')}/{fluxo_do_relay()}"


def destino_do_relay() -> str:
    """Para onde o gravador PUBLICA (SRT no mediamtx desta maquina, mesma forma do envio do vivo)."""
    return (f"srt://{_endereco_do_mediamtx('srt')}?mode=caller&latency=200&pkt_size=1316"
            f"&streamid=publish:{fluxo_do_relay()}")


def camera_do_gravador() -> str:
    """A camera cujo dispositivo o gravador segura (para o vivo saber de quem e' a camera)."""
    return camera_id()


def gravador_de_pe() -> bool:
    """O laco do gravador esta' VIVO agora (a medida, nao o desejo)."""
    return _laco_vivo()


def dono_da_camera(camera_id_ou_fluxo: str) -> bool:
    """Esta camera e' a do gravador E o gravador esta' de pe'? (o vivo tem de ler o rele').

    Compara por id e por `fluxo_id`: a tela do cliente e o agente do bordo falam dos dois jeitos.
    """
    alvo = str(camera_id_ou_fluxo or "").strip()
    if not alvo or not relay_ligado() or not gravador_de_pe():
        return False
    meu = camera_do_gravador()
    if alvo in (meu, fluxo_do_relay(), PREFIXO_DO_RELAY + meu):
        return True
    try:
        db = _modulo_da_api()
        if db:
            with db.conexao() as c:
                r = c.execute("SELECT id, fluxo_id FROM cameras WHERE id=? OR fluxo_id=?",
                              (alvo, alvo)).fetchone()
                if r and str(r["id"]) == meu:
                    return True
    except Exception:
        return False
    return False


def garantir() -> dict:
    """O gravador TEM de estar de pe' enquanto o desejo do admin for LIGADO.

    Medido em 27/11/2026: o laco morreu calado as 13:20:29 (o `gravador.pid` ficou no disco e ninguem
    o reergueu) — o HD ficou sem blocos novos e a tela so' dizia "nao esta' de pe'". Quem chama isto e'
    o servidor, de tempo em tempo.
    """
    if not ligada():
        return {"ok": True, "ligada": False, "motivo": "desligada pelo desejo"}
    if not dispositivo():
        r = resolucao(recarregar=True)
        return {"ok": False, "ligada": True, "motivo": f"sem dispositivo de video: {r.get('motivo') or ''}"}
    subido = _subir_gravador()   # 0 = ja' estava de pe' (ou nao subiu — conferido logo abaixo)
    if subido:
        _log(f"gravador reerguido (pid {subido}) — o laco anterior tinha morrido com o desejo ligado")
    # O supervisor NAO pode achar que esta' tudo bem so' porque pediu para subir (dono, 27/11/2026: o
    # laco morreu calado e nada o reergueu). Se depois de garantir o laco nao esta' de pe', isto e'
    # falha declarada — e vai com motivo para a tela e para o catalogo de terra.
    if not _laco_vivo():
        motivo = "o laco do gravador nao subiu (veja ground/hd/log/gravacao-continua.log)"
        _log(f"aviso: {motivo}")
        return {"ok": False, "ligada": True, "subido": subido, "pid": gravador_pid(),
                "motivo": motivo, "gravando": False}
    return {"ok": True, "ligada": True, "subido": subido, "pid": gravador_pid(),
            "gravando": gravando_agora()}


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
    """Existe processo com este pid? (nao diz de QUEM ele e' — para isso ver `_laco_vivo`).

    MEDIDO NESTA MAQUINA em 27/11/2026: `os.kill(pid, 0)` no Windows **MATA** o processo (chama
    `TerminateProcess`), nao apenas "pergunta se existe" como no Linux — conferido com um processo
    de teste: `os.kill(pid, 0)` o fez sair com codigo `0xC000013A`. Era o codigo daqui: entao TODA
    checagem de vida do gravador (o supervisor, a tela, o `gravador_de_pe`) DERRUBAVA o proprio laco
    que estava conferindo — e o `_subir_gravador` respondia "ja' estava de pe'". A checagem passa a
    ser pelo `processos` (psutil/WMI), que so' OLHA.
    """
    return processos.vivo(pid)


def _linhas_do_pid() -> list[str]:
    try:
        return [x.strip() for x in _arquivo_do_pid().read_text(encoding="utf-8").splitlines() if x.strip()]
    except Exception:
        return []


def gravador_pid() -> int:
    linhas = _linhas_do_pid()
    try:
        return int(linhas[0]) if linhas else 0
    except ValueError:
        return 0


def gravador_criado_em() -> float:
    """Quando o laco do gravador nasceu (epoch), gravado na 2a linha do `gravador.pid`.

    Arquivo antigo (so' o pid): vale a hora do ARQUIVO como piso — e' o suficiente para provar que um
    pid nao foi reciclado (um pid reciclado nasceu DEPOIS do arquivo). 0.0 = nao sei.
    """
    linhas = _linhas_do_pid()
    if len(linhas) >= 2:
        try:
            return float(linhas[1])
        except ValueError:
            return 0.0
    try:
        return _arquivo_do_pid().stat().st_mtime
    except OSError:
        return 0.0


def _laco_vivo() -> bool:
    """O laco do gravador esta' de pe' **E e' o NOSSO** (pid + hora de criacao)?

    Um pid sozinho nao serve (o Windows recicla numero): sem a hora de criacao, um pid reciclado faz
    o supervisor achar que o gravador esta' no ar quando o dono dele ja' morreu.
    """
    pid = gravador_pid()
    if pid <= 0:
        return False
    return processos.mesmo_processo(pid, gravador_criado_em())


def _subir_gravador():
    """Sobe o laco do gravador DESACOPLADO do servidor de captura. 0 = ja' estava de pe'."""
    if _laco_vivo():
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
        # (pid, hora de criacao) — e' o que permite, depois, dizer se o pid de agora ainda e' ESTE laco.
        _arquivo_do_pid().write_text(f"{p.pid}\n{processos.criado_em(p.pid)}", encoding="utf-8")
    except Exception:
        pass
    _log(f"gravador subido pelo desejo do admin (pid {p.pid})")
    return p.pid


def _parar_gravador() -> bool:
    pid = gravador_pid()
    if not _laco_vivo():
        # nao e' o nosso laco (ou ja' morreu): NAO se mata nada. O pid gravado pode ter sido reciclado
        # pelo Windows e pertencer a outro processo — apagar o carimbo e' o certo aqui.
        try:
            _arquivo_do_pid().unlink()
        except Exception:
            pass
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
    if not _laco_vivo():
        return False
    bs = blocos()
    if not bs:
        return False
    try:
        ultimo = dt.datetime.fromisoformat(bs[-1]["inicio"])
    except Exception:
        return False
    return (dt.datetime.now() - ultimo).total_seconds() <= 2 * bloco_segundos() + 30


# ---------------------------------------------------------------- ESCOLHA DO DISCO E DA COTA (dono, 27/11/2026)
# Dono: "precisamos definir qual disco e quanto dele será utilizado para gravação" · "D1 sim (o PC mede e
# propõe) · D2 GB · D3 um disco só grava nele, com dois ou mais o admin escolhe" · D4 · D5 · D6.
# O BORDO mede os discos e PROPÕE (vão no retrato e no catálogo); o ADMIN escolhe na tela; o comando volta
# pelo caminho que já existe (config publicada → o bordo olha → a rota local chama `definir_escolha`).
# O ARQUIVO da escolha mora em lugar FIXO — mas FORA da pasta de instalacao. Se morasse NO disco
# escolhido, trocar de disco apagaria a propria escolha; e se morasse na pasta do aplicativo
# (`resources/servidor/...`), a ATUALIZACAO a apagaria: MEDIDO em 27/11/2026, ao passar de 0.28.1 para
# 0.29.0 a escolha de `D:\` sumiu (`origem_da_escolha: padrao`) e a gravacao voltou para a pasta do
# pacote. Por isso a escolha vai para a pasta do USUARIO (`LECSOR_HD_CONFIG`, que o app aponta — mesma
# ideia do banco em `LECSOR_BANCO`); sem a variavel (bancada), vale a pasta do codigo. Nada do que foi
# gravado e' movido (D3).
def _config_do_hd() -> pathlib.Path:
    v = (os.environ.get("LECSOR_HD_CONFIG") or "").strip()
    return pathlib.Path(v) if v else (RAIZ / "ground" / "hd" / "config.json")


CONFIG_DO_HD = _config_do_hd()
_PADRAO_DO_PACOTE = RAIZ / "ground" / "hd" / "config.json"   # onde a escolha morava (leitura de resgate)
PASTA_NO_DISCO = "lecsor-radar"
COTA_MINIMA_GB, COTA_MAXIMA_GB = 0.1, 100000.0


def _ler_escolha() -> dict:
    for caminho in (CONFIG_DO_HD, _PADRAO_DO_PACOTE):
        try:
            d = json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, dict) and d:
            return d
    return {}


def escolha() -> dict:
    """A escolha do admin: o disco (`disco`), a pasta que grava (`pasta`) e a cota (`cota_gb`).

    `origem` diz de onde veio: `admin` (escolhida na tela) ou `padrao` (nada escolhido — o produto usa a
    pasta do aplicativo, como sempre). Sem escolha, `disco`/`cota_gb` são vazios — a tela diz "padrão".
    """
    d = _ler_escolha()
    pasta = str(d.get("pasta") or "").strip()
    bruto = d.get("cota_gb")
    try:
        cota = float(bruto) if bruto not in (None, "") else None
    except (TypeError, ValueError):
        cota = None
    if not pasta and not cota:
        return {"disco": "", "pasta": "", "cota_gb": None, "origem": "padrao", "em": ""}
    return {"disco": str(d.get("disco") or ""), "pasta": pasta, "cota_gb": cota,
            "origem": str(d.get("origem") or "admin"), "em": str(d.get("em") or "")}


def cota_bytes() -> int | None:
    """A cota em BYTES (o espaço que a gravação pode ocupar neste disco) — `None` = sem cota escolhida."""
    c = escolha().get("cota_gb")
    if not c:
        return None
    return int(max(COTA_MINIMA_GB, float(c)) * 1024 * 1024 * 1024)


def definir_escolha(disco: str, cota_gb) -> dict:
    """Grava a escolha do admin (disco + cota em GB) e leva o DESEJO junto para o disco novo.

    O desejo (`ligada.txt`) fica no disco da gravação; se ele mudasse sem acompanhar, "ligada" se perderia
    na troca. Devolve `{"ok", "pasta", "cota_gb", "motivo"}` — e recusa disco que não existe nesta máquina
    (nunca "apliquei" com caminho inventado). Não apaga nem move trecho nenhum (D3).
    """
    antes = diretorio()
    desejo_antes = desejo()
    disco = (disco or "").strip()
    cota: float | None
    try:
        cota = float(str(cota_gb).strip()) if str(cota_gb or "").strip() else None
    except (TypeError, ValueError):
        return {"ok": False, "motivo": f"cota invalida: {cota_gb!r}"}
    if cota is not None and not (COTA_MINIMA_GB <= cota <= COTA_MAXIMA_GB):
        return {"ok": False, "motivo": f"cota fora da faixa do produto ({COTA_MINIMA_GB:g} a {COTA_MAXIMA_GB:g} GB) — veio {cota_gb!r}"}
    if disco:
        raiz = pathlib.Path(disco)
        if not raiz.exists():
            return {"ok": False, "motivo": f"o disco {disco!r} nao existe nesta maquina"}
        pasta = raiz / PASTA_NO_DISCO
    else:
        pasta = RAIZ / "ground" / "hd"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        CONFIG_DO_HD.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_DO_HD.write_text(json.dumps(
            {"disco": disco, "pasta": str(pasta), "cota_gb": cota, "origem": "admin",
             "em": dt.datetime.now().astimezone().isoformat(timespec="seconds")},
            ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "motivo": f"nao consegui gravar a escolha ({type(e).__name__}: {e})"}
    if desejo_antes in ("0", "1") and pasta != antes:
        try:
            (pasta / "ligada.txt").write_text(desejo_antes, encoding="utf-8")
        except Exception:
            pass
    return {"ok": True, "pasta": str(pasta), "disco": disco, "cota_gb": cota, "origem": "admin",
            "motivo": (f"gravacao vai para {pasta}"
                       + (f", usando no maximo {cota:g} GB deste disco" if cota else ""))}


def discos() -> list[dict]:
    """TODOS os discos fixos desta máquina, medidos — é o que o bordo PROPÕE ao admin (D1).

    O disco onde a gravação está agora vem marcado com `gravando: True`. Sem psutil não se inventa lista:
    sobra o disco do aplicativo, medido por `shutil` (mesma régua do resto do produto).
    """
    saida: list[dict] = []
    partes = []
    try:
        import psutil   # noqa: PLC0415
        partes = list(psutil.disk_partitions(all=False))
    except Exception:
        partes = []
    for p in partes:
        mp = str(getattr(p, "mountpoint", "") or "")
        if not mp or "cdrom" in str(getattr(p, "opts", "") or ""):
            continue
        linha = _medir_volume(mp)
        if linha:
            saida.append(linha)
    if not saida:
        linha = _medir_volume(str(RAIZ), nome="aplicativo")
        if linha:
            saida.append(linha)
    atual = str(diretorio())
    for d in saida:
        d["gravando"] = bool(d.get("caminho")) and atual.lower().startswith(str(d["caminho"]).lower())
        if d["gravando"]:
            d["pasta"] = atual
    return saida


def _medir_volume(caminho: str, nome: str = "") -> dict | None:
    try:
        uso = shutil.disk_usage(caminho)
    except Exception:
        return None
    return {"nome": nome or caminho, "caminho": caminho,
            "total_gb": round(uso.total / 1e9, 1), "livre_gb": round(uso.free / 1e9, 1),
            "usado_pct": round(100.0 * uso.used / uso.total, 1) if uso.total else None}


def diretorio() -> pathlib.Path:
    """Onde os blocos ficam AGORA: o override de bancada, a escolha do admin ou a pasta do aplicativo."""
    amb = (os.environ.get("LECSOR_HD_DIR") or "").strip()
    if amb:
        return pathlib.Path(amb)
    p = str(escolha().get("pasta") or "").strip()
    return pathlib.Path(p) if p else (RAIZ / "ground" / "hd")


def reiniciar_gravador() -> bool:
    """Para e sobe o gravador — usado quando o DISCO da gravação muda (o ffmpeg fica preso no antigo)."""
    parou = _parar_gravador()
    if not ligada() or not dispositivo():
        return parou
    _subir_gravador()
    return True


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


def _segundos_desde(iso: str) -> float:
    """Segundos inteiros desde um carimbo ISO local; -1.0 se nao der para ler (nunca explode a tela)."""
    try:
        return max(0.0, (dt.datetime.now() - dt.datetime.fromisoformat(iso)).total_seconds())
    except Exception:
        return -1.0


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
    esc = escolha()
    cota = cota_bytes()
    usado = sum(b["bytes"] for b in bs)
    return {"ligada": ligada(), "gravando": gravando_agora(),
            "dispositivo": r["dispositivo"], "dispositivo_origem": r.get("origem") or "",
            "motivo": r.get("motivo") or "", "camera": camera(), "camera_id": camera_id(),
            "camera_rotulo": rotulo(), "nome_dispositivo": r.get("nome") or "",
            "bloco_segundos": bloco_segundos(), "diretorio": str(diretorio()),
            # A ESCOLHA DO ADMIN (dono, 27/11/2026): qual disco, qual pasta e quanto dele. `origem` diz se
            # foi ele quem escolheu ou se é o padrão da instalação — a tela nunca diz "escolhido" sem ser.
            "disco": esc.get("disco") or "", "cota_gb": esc.get("cota_gb"),
            "origem_da_escolha": esc.get("origem") or "padrao",
            "cota_bytes": cota, "cota_usada_pct": (round(100.0 * usado / cota, 1) if cota else None),
            "discos": discos(),
            "blocos": len(bs), "bytes": usado,
            "primeiro": bs[0]["inicio"] if bs else "", "ultimo": bs[-1]["inicio"] if bs else "",
            "livre_bytes": livre, "total_bytes": total,
            # O RELE' (dono, 27/11/2026): com ele a camera que o gravador ja' segura tambem alimenta o
            # vivo — a tela mostra que o vivo NAO esta' abrindo o dispositivo. `de_pe` e' a MEDIDA do
            # laco (o desejo e' `ligada`), e e' o que o `garantir()` usa para reerguer.
            "relay": relay_ligado(), "relay_fluxo": (fluxo_do_relay() if relay_ligado() else ""),
            "relay_url": (url_do_relay() if relay_ligado() else ""), "gravador_de_pe": gravador_de_pe(),
            # A IDENTIDADE do laco (dono, 27/11/2026): a tela e o catalogo de terra mostram QUEM e' o
            # gravador — sem isto, um pid sozinho nao diz se o laco de agora e' o mesmo que subiu. Junto
            # vai o que a tela precisava para nao so' dizer "parado": quando foi o ultimo bloco e o
            # motivo declarado de nao estar de pe'.
            "laco_pid": gravador_pid(), "laco_criado_em": gravador_criado_em(),
            "ultimo_bloco_em": (bs[-1]["fim"] if bs else ""),
            "segundos_sem_bloco": (_segundos_desde(bs[-1]["fim"]) if bs else None),
            "motivo_de_nao_subir": ("desligada" if not ligada()
                                    else ("" if _laco_vivo() else "o laco do gravador nao esta' de pe'")),
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
        # DOIS LIMITES (dono, 27/11/2026): o espaço que NÃO pode acabar no disco (reserva do sistema, como
        # sempre) e a COTA que o admin escolheu para a gravação ("quanto dele será utilizado"). O que passar
        # de qualquer um dos dois faz sair o bloco MAIS ANTIGO — o anel, nunca a gravação parada.
        if uso.free >= reserva_bytes():
            cota = cota_bytes()
            if not cota or sum(b["bytes"] for b in blocos()) <= cota:
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
def _escapar_no_tee(caminho: "str | pathlib.Path") -> str:
    r"""Caminho do Windows dentro do spec do muxer `tee`: barras normais e `:` escapado.

    Medido no prototipo de 27/11/2026: sem isto o ffmpeg entende o `:` do `C:\` como separador de
    opcao do tee e o destino sai errado. O `\` tambem precisa virar `/`.
    """
    return str(caminho).replace("\\", "/").replace(":", "\\:")


def especificacao_do_tee(blocos: pathlib.Path, relay: bool | None = None) -> str:
    """O spec do `tee` do gravador: bloco no HD (primeiro) + relé no mediamtx local (segundo).

    UM encode, DOIS destinos — provado em 27/11/2026 (prototipo): os blocos saem no HD e o fluxo
    aparece no mediamtx local (`gravador-...`), sem reencode e sem custo de CPU dobrado.
    """
    if relay is None:
        relay = relay_ligado()
    segundos = bloco_segundos()
    spec = ("[f=segment:segment_time=" + str(segundos) + ":segment_atclocktime=1:reset_timestamps=1:"
            "strftime=1:segment_format_options=movflags=+frag_keyframe+empty_moov+default_base_moof]"
            + _escapar_no_tee(blocos))
    if relay:
        # SRT no mediamtx DESTA maquina (mesma forma que o envio do vivo usa). Os `:` do URL entram
        # escapados porque dentro do tee eles separam opcao.
        spec += "|[f=mpegts]" + destino_do_relay().replace(":", "\\:")
    return spec


def comando_do_gravador() -> list:
    p = perfil()
    d = diretorio()
    if relay_ligado():
        # COM O RELE': o mesmo comando de sempre, mas o muxer vira `tee` e o bloco vira o PRIMEIRO
        # destino (o nome e os parametros do segmento moram dentro do spec — ver `especificacao_do_tee`).
        return ["ffmpeg", "-hide_banner", "-nostdin",
                "-rtbufsize", "512M",
                "-f", "dshow", "-framerate", p["fps"], "-video_size", p["resolucao"],
                "-i", f"video={dispositivo()}",
                "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-b:v", p["bitrate"], "-maxrate", p["bitrate"], "-bufsize", "2M",
                "-g", p["fps"],
                "-f", "tee", "-map", "0:v",
                especificacao_do_tee(d / "bloco-%Y%m%d-%H%M%S.mp4")]
    return ["ffmpeg", "-hide_banner", "-nostdin",
            "-rtbufsize", "512M",
            "-f", "dshow", "-framerate", p["fps"], "-video_size", p["resolucao"],
            "-i", f"video={dispositivo()}",
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-b:v", p["bitrate"], "-maxrate", p["bitrate"], "-bufsize", "2M",
            "-g", p["fps"],
            # MP4 FRAGMENTADO (dono, 27/11/2026, D4: "dar play e ver em tempo real"): o bloco tem de ser
            # decodificavel ANTES de estar inteiro — e' o que deixa o cliente tocar o trecho ENQUANTO ele
            # chega do bordo (`/api/hd/tocar` serve o arquivo que CRESCE). MEDIDO: com o `-movflags` antes
            # do `-f segment` o arquivo sai com o indice NO FIM (ftyp,free,mdat,moov) e o prefixo e'
            # ilegivel; a forma que vale e' `-segment_format_options movflags=...` — o arquivo sai
            # ftyp,moov,moof,mdat e o ffprobe LE quadros do arquivo cortado em 60%.
            "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
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
        # (pid, hora de criacao): o laco se identifica — o mesmo par que o supervisor confere depois.
        _arquivo_do_pid().write_text(f"{os.getpid()}\n{processos.criado_em(os.getpid())}", encoding="utf-8")
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
