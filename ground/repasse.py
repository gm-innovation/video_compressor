#!/usr/bin/env python3
"""Repassa para o lado terra (VPS ou outro PC da rede) o fluxo JA COMPRIMIDO publicado nesta maquina.

Quem chama e' o mediamtx local, pelo `runOnReady` (um processo por fluxo, que volta quando o fluxo
volta). Tambem roda na mao, para testar:

    python ground/repasse.py <fluxo> [host:porta]

Regras que valem sempre:
- **Sem destino nao ha repasse.** O destino vem do argumento ou de `LECSOR_DESTINO_SRT`. Sem ele o
  script sai na hora — e' o que impede a propria VPS (que roda o mesmo mediamtx) de subir para si.
- **`-c copy`, nunca reencodar.** O fluxo que chega aqui ja foi comprimido no PC de captura; o
  repasse so troca de transporte (RTSP local -> SRT) e mantem os mesmos bytes.
- **Volta sozinho.** Se o link cair ou o ffmpeg morrer, tenta de novo a cada 2 s enquanto o fluxo
  existir. Trava de PID por fluxo, para nao duplicar envio.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))
import licenca  # noqa: E402  (a embarcacao vem da LICENCA quando existe; senao, do ambiente)

LOG_DIR = RAIZ / "ground" / "envios" / "log"
TRAVA_DIR = RAIZ / "ground" / ".repasse"
SEGUNDOS_ENTRE_TENTATIVAS = 2


def _log(fluxo: str, linha: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    carimbo = time.strftime("%Y-%m-%d %H:%M:%S")
    texto = f"{carimbo} [{fluxo}] {linha}"
    print(texto, flush=True)
    try:
        with (LOG_DIR / f"repasse-{fluxo}.log").open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except Exception:
        pass


def _estado_arquivo() -> Path:
    # `LECSOR_REPASSE_ESTADO` deixa o teste apontar o estado para uma pasta propria (sem sujar o
    # repositorio nem herdar tentativa de rodada anterior — foi o que fez um teste mentir em 18/11).
    return Path(os.environ.get("LECSOR_REPASSE_ESTADO") or (TRAVA_DIR / "estado.json"))


def _estado(fluxo: str, ok: bool, motivo: str = "") -> None:
    """Guarda o resultado da ULTIMA tentativa de publicar, por fluxo.

    Existe porque o anuncio falhava so' no arquivo de log: a tela nao dizia nada e o dono ficava
    olhando a camera sem aparecer ("o que mais precisa corrigir?"). Aqui o resultado vira dado que a
    tela le' (`/api/publicacao`), com o motivo junto. Nunca guarda valor de segredo.
    """
    if not fluxo:
        return
    try:
        caminho = _estado_arquivo()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:
            dados = {}
        if not isinstance(dados, dict):
            dados = {}
        dados[fluxo] = {"ok": bool(ok), "motivo": (motivo or "").strip()[:300],
                        "em": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def sou_o_lado_terra() -> bool:
    """Esta maquina E' o lado terra? (o `ambiente.json` do pacote traz o endereco dele proprio).

    Numa instalacao que E' o lado terra o anuncio nao tem destino: as cameras desta maquina ja' estao
    no banco que as telas leem. Sem esta checagem a tela mostrava TODA camera como "nao publicada" com
    o motivo "sem lado terra ou sem token" — falso e assustador (medido na VPS, 18/11/2026).
    """
    base = (os.environ.get("LECSOR_LADO_TERRA_API") or "").strip()
    if not base:
        return False
    try:
        from ferramentas import eh_esta_maquina

        return bool(eh_esta_maquina(base))
    except Exception:  # noqa: BLE001
        return False


def estado_do_anuncio() -> dict:
    """O que a tela precisa saber para explicar "por que minha camera nao apareceu".

    Devolve se o anuncio esta' de pe' (lado terra + token + embarcacao presentes) e o resultado da
    ultima tentativa por fluxo. Sem isto, o unico lugar onde o erro existia era o log de arquivo.
    """
    base = (os.environ.get("LECSOR_LADO_TERRA_API") or os.environ.get("LECSOR_DESTINO_SRT") or "").strip()
    token = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
    emb = (os.environ.get("LECSOR_EMBARCACAO") or "").strip()
    dono_do_cadastro = sou_o_lado_terra()
    faltando = []
    if not base and not dono_do_cadastro:
        faltando.append("endereço do lado terra")
    if not token and not dono_do_cadastro:
        faltando.append("token de ingestão")
    if not emb and not dono_do_cadastro:
        faltando.append("embarcação")
    try:
        tentativas = json.loads(_estado_arquivo().read_text(encoding="utf-8"))
    except Exception:
        tentativas = {}
    if not isinstance(tentativas, dict):
        tentativas = {}
    por_fluxo = {k: v for k, v in tentativas.items() if isinstance(v, dict)}
    ultimo = ""
    for v in por_fluxo.values():
        ultimo = max(ultimo, str(v.get("em") or ""))
    return {"de_pe": (not faltando), "faltando": faltando, "token": bool(token),
            "lado_terra": base, "embarcacao": emb, "ultimo": ultimo, "tentativas": por_fluxo,
            "sou_o_lado_terra": dono_do_cadastro,
            "papel": ("esta máquina é o lado terra: o cadastro daqui já é o que as telas leem"
                      if dono_do_cadastro else "esta máquina envia o cadastro para o lado terra"),
            "onde": str(_estado_arquivo())}


def _instrumentar(fn):
    """Registra o resultado de toda publicacao, sem repetir o registro em cada funcao."""

    def embruxado(*a, **kw):
        fluxo = ""
        if a and isinstance(a[0], dict):
            fluxo = str(a[0].get("fluxo_id") or a[0].get("id") or "")
        elif a and isinstance(a[0], str):
            fluxo = a[0]
        if sou_o_lado_terra():
            # publicar para si mesmo nao existe: aqui o cadastro local JA' e' o do lado terra
            r = {"ok": True, "local_lado_terra": True,
                 "motivo": "esta máquina é o lado terra: o cadastro daqui já é o que as telas leem"}
            _estado(fluxo, True, r["motivo"])
            return r
        r = fn(*a, **kw)
        if not isinstance(r, dict):
            return r
        _estado(fluxo, bool(r.get("ok")), r.get("motivo") or r.get("erro") or "")
        return r

    embruxado.__name__ = fn.__name__
    embruxado.__doc__ = fn.__doc__
    return embruxado


def _ja_rodando(fluxo: str) -> bool:
    """Um repasse por fluxo: se ja' existe processo vivo, este sai sem enviar."""
    from ingestao import _processo_vivo  # mesma checagem usada pelo envio para a VPS
    TRAVA_DIR.mkdir(parents=True, exist_ok=True)
    trava = TRAVA_DIR / f"{fluxo}.pid"
    try:
        pid = int(trava.read_text(encoding="utf-8").strip())
    except Exception:
        pid = 0
    if pid and pid != os.getpid() and _processo_vivo(pid):
        return True
    trava.write_text(str(os.getpid()), encoding="utf-8")
    return False


sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferramentas import caminho_ffmpeg  # noqa: E402


def _comando(fluxo: str, destino: str, origem: str) -> list[str]:
    return [
        caminho_ffmpeg(), "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-rtsp_transport", "tcp", "-i", f"{origem.rstrip('/')}/{fluxo}",
        # o encode ja' veio pronto do PC de captura: aqui so' troca o transporte
        "-c", "copy", "-f", "mpegts",
        f"srt://{destino}?mode=caller&latency=200&pkt_size=1316&streamid=publish:{fluxo}",
    ]


def _api_lado_terra(destino: str) -> str:
    """Base HTTP do lado terra: `LECSOR_LADO_TERRA_API` ou o host do SRT na porta 8085.

    Endereco que aponta para ESTA maquina vale vazio: e' o caso do proprio lado terra (o
    `ambiente.json` do pacote traz o endereco dele) tentando publicar para si mesmo.
    """
    base = (os.environ.get("LECSOR_LADO_TERRA_API") or "").strip().rstrip("/")
    if base:
        try:
            from ferramentas import eh_esta_maquina

            if eh_esta_maquina(base):
                return ""
        except Exception:  # noqa: BLE001
            pass
        return base
    host = (destino or "").split(":")[0].strip()
    return f"http://{host}:{os.environ.get('LECSOR_PORTA_API', '8085')}" if host else ""


def anunciar(fluxo: str, destino: str, rotulo: str | None = None) -> dict:
    """Avisa o lado terra que este fluxo entrou no ar, para ele aparecer na tela do cliente.

    Sem isto o fluxo chega no mediamtx do lado terra mas nao existe linha em `cameras` la' e
    ninguem ve' nada (foi o "cliente nao recebe o video"). O anuncio e' autenticado pelo token de
    ingestao (nunca por sessao de navegador) e so' cria/atualiza o cadastro da camera.
    """
    base = _api_lado_terra(destino)
    token = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
    if not base or not token:
        _log(fluxo, "sem lado terra/token de ingestao — nao anunciei o fluxo (ninguem vera' na tela)")
        return {"ok": False, "motivo": "sem lado terra ou sem LECSOR_TOKEN_INGESTAO"}
    corpo = {"fluxo_id": fluxo, "rotulo": (rotulo or os.environ.get("LECSOR_ROTULO") or fluxo)}
    emb = licenca.embarcacao()   # LICENCA deste PC de captura (dono, 19/11/2026); senao o ambiente
    if emb:
        corpo["embarcacao_id"] = emb
    dados = json.dumps(corpo).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/cameras/anuncio", data=dados,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read() or b"{}")
        _log(fluxo, f"anunciei ao lado terra: {j.get('id')} em {j.get('embarcacao_id')}")
        return {"ok": bool(j.get("ok")), "resposta": j}
    except Exception as e:
        _log(fluxo, f"nao consegui anunciar ao lado terra ({type(e).__name__}: {e}) — o fluxo chega, mas nao aparece na tela")
        return {"ok": False, "erro": str(e)}


def publicar_cadastro(camera: dict, destino: str | None = None, remover: bool = False) -> dict:
    """Publica o CADASTRO de uma camera desta maquina no lado terra, sem esperar o fluxo subir.

    Era o furo do "cadastrei cam-01 e cam-02 no PC de captura e o app do cliente nao mostra nada": a
    linha da camera existia so' no banco daqui, e o lado terra (que serve a tela do cliente) so' ganhava
    a camera quando o fluxo entrava no ar. Aqui vai o cadastro inteiro — id, rotulo, fluxo e se esta'
    ativa — nunca endereco, porta, protocolo ou credencial (nada disso sai desta maquina).
    """
    if not isinstance(camera, dict) or not str(camera.get("fluxo_id") or "").strip():
        return {"ok": False, "motivo": "camera sem fluxo_id"}
    fluxo = str(camera["fluxo_id"]).strip()
    base = _api_lado_terra(destino or (os.environ.get("LECSOR_DESTINO_SRT") or ""))
    token = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
    if not base or not token:
        _log(fluxo, "sem lado terra/token de ingestao — cadastro desta camera nao foi publicado")
        return {"ok": False, "motivo": "sem lado terra ou sem LECSOR_TOKEN_INGESTAO"}
    corpo = {"id": camera.get("id") or fluxo, "fluxo_id": fluxo,
             "rotulo": camera.get("rotulo") or fluxo,
             "ativo": 0 if str(camera.get("ativo", 1)).strip() in ("0", "False", "false") else 1}
    if remover:
        # avisa o lado terra que a camera saiu de operacao: ele APAGA o cadastro (nao e' desativar)
        corpo["remover"] = True
    emb = str(camera.get("embarcacao_id") or licenca.embarcacao() or "").strip()
    if emb:
        corpo["embarcacao_id"] = emb
    req = urllib.request.Request(f"{base}/api/cameras/anuncio", data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read() or b"{}")
        _log(fluxo, f"cadastro publicado no lado terra: {j.get('id')} em {j.get('embarcacao_id')}"
                    + ("" if j.get("ativo", True) else " (desativada)"))
        return {"ok": bool(j.get("ok")), "resposta": j}
    except Exception as e:
        _log(fluxo, f"nao consegui publicar o cadastro no lado terra ({type(e).__name__}: {e})")
        return {"ok": False, "erro": str(e)}


def publicar_qualidade(medicao: dict, destino: str | None = None) -> dict:
    """Publica no lado terra o SSIM medido AQUI (na maquina que tem a fonte crua).

    O SSIM exige o original e o comprimido lado a lado, e o original so' existe na maquina de
    captura: por isso o lado terra nunca consegue calcular esse numero sozinho — ele precisa RECEBER.
    Era o "nao tenho medicao de SSIM": a medicao rodava no bordo e ficava so' no banco local. Aqui
    vao os numeros da medicao (nunca endereco, porta, protocolo ou credencial de camera).
    """
    if not isinstance(medicao, dict) or not str(medicao.get("fluxo_id") or "").strip():
        return {"ok": False, "motivo": "medicao sem fluxo_id"}
    fluxo = str(medicao["fluxo_id"]).strip()
    if medicao.get("ssim") is None:
        return {"ok": False, "motivo": "medicao sem SSIM"}
    base = _api_lado_terra(destino or (os.environ.get("LECSOR_DESTINO_SRT") or ""))
    token = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
    if not base or not token:
        _log(fluxo, "sem lado terra/token de ingestao — medicao de qualidade nao foi publicada")
        return {"ok": False, "motivo": "sem lado terra ou sem LECSOR_TOKEN_INGESTAO"}
    campos = ("fluxo_id", "ssim", "ajuste", "resolucao", "fps", "segundos", "mb_alvo", "mb_original",
              "compressao_pct", "fonte", "medido_em")
    corpo = {k: medicao.get(k) for k in campos if medicao.get(k) is not None}
    req = urllib.request.Request(f"{base}/api/qualidade/anuncio", data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read() or b"{}")
        _log(fluxo, f"medicao de qualidade publicada no lado terra: SSIM {corpo.get('ssim')}"
                    f" (ajuste {corpo.get('ajuste') or '?'})")
        return {"ok": bool(j.get("ok")), "resposta": j}
    except Exception as e:
        _log(fluxo, f"nao consegui publicar a medicao de qualidade ({type(e).__name__}: {e})")
        return {"ok": False, "erro": str(e)}


def publicar_envio(envio: dict, destino: str | None = None) -> dict:
    """Declara ao lado terra o que ESTA maquina esta enviando, junto com o video.

    E' o lado "declarado" do atestado do trecho de 1 minuto: kbps de entrada (o que o encoder
    recebe), kbps de saida (o que sai para a rede), corte %, alvo, codec, resolucao, fps e o
    instante. Sem isto o lado terra so' tem o que ELE mediu no arquivo e o atestado responde
    "o PC de captura nao informou" — era o pedido do dono em 15/11/2026 (comparativos completos).
    Nunca sai daqui endereco, porta, protocolo ou credencial de camera: so' numeros do envio.
    """
    if not isinstance(envio, dict) or not str(envio.get("fluxo_id") or "").strip():
        return {"ok": False, "motivo": "envio sem fluxo_id"}
    fluxo = str(envio["fluxo_id"]).strip()
    base = _api_lado_terra(destino or (os.environ.get("LECSOR_DESTINO_SRT") or ""))
    token = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
    if not base or not token:
        _log(fluxo, "sem lado terra/token de ingestao — declaracao do envio NAO publicada "
                    "(o atestado vai dizer 'o PC de captura nao informou')")
        return {"ok": False, "motivo": "sem lado terra ou sem LECSOR_TOKEN_INGESTAO"}
    campos = ("fluxo_id", "camera_id", "rotulo", "tipo", "codec", "resolucao", "fps", "bitrate_alvo",
              "bitrate_entrada_kbps", "bitrate_saida_kbps", "corte_pct", "velocidade", "tamanho_mb",
              "duracao_s", "estado", "fonte", "carimbo")
    corpo = {k: envio.get(k) for k in campos if envio.get(k) is not None}
    req = urllib.request.Request(f"{base}/api/envios/anuncio", data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read() or b"{}")
        _log(fluxo, f"envio declarado ao lado terra: entrada {corpo.get('bitrate_entrada_kbps') or '?'} kbps"
                    f" -> saida {corpo.get('bitrate_saida_kbps') or '?'} kbps"
                    f" (corte {corpo.get('corte_pct') if corpo.get('corte_pct') is not None else '?'}%)")
        return {"ok": bool(j.get("ok")), "resposta": j}
    except Exception as e:
        _log(fluxo, f"nao consegui declarar o envio ao lado terra ({type(e).__name__}: {e}) — o atestado"
                    f" vai mostrar 'o PC de captura nao informou'")
        return {"ok": False, "erro": str(e)}


# O ambiente do pacote (token de ingestao, embarcacao, lado terra) e' carregado AQUI tambem: este
# arquivo roda sozinho pelo mediamtx (`python ground/repasse.py ...`), sem passar pelo app.
try:
    from ferramentas import carregar_ambiente

    carregar_ambiente()
except Exception:  # noqa: BLE001
    pass

# Toda publicacao passa a registrar o proprio resultado (a tela le' de `/api/publicacao`).
for _nome in ("anunciar", "publicar_cadastro", "publicar_qualidade", "publicar_envio"):
    globals()[_nome] = _instrumentar(globals()[_nome])


def repassar(fluxo: str, destino: str, origem: str) -> int:
    if not destino:
        _log(fluxo, "sem destino (LECSOR_DESTINO_SRT) — nada a repassar")
        return 0
    if _ja_rodando(fluxo):
        _log(fluxo, "ja' existe repasse vivo deste fluxo — saindo sem duplicar")
        return 0
    anunciar(fluxo, destino)
    _log(fluxo, f"repassando {origem}/{fluxo} -> srt://{destino} (-c copy)")
    while True:
        r = subprocess.run(_comando(fluxo, destino, origem), capture_output=True, text=True)
        if r.returncode == 0:
            _log(fluxo, "fluxo encerrado na origem — repasse parado")
            return 0
        erro = (r.stderr or "").strip().splitlines()
        _log(fluxo, f"reenvio em {SEGUNDOS_ENTRE_TENTATIVAS}s ({erro[-1] if erro else 'sem mensagem'})")
        time.sleep(SEGUNDOS_ENTRE_TENTATIVAS)


def principal() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    fluxo = sys.argv[1]
    destino = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("LECSOR_DESTINO_SRT", "")
    origem = os.environ.get("LECSOR_ORIGEM_RTSP", "rtsp://127.0.0.1:8554")
    return repassar(fluxo, destino, origem)


if __name__ == "__main__":
    raise SystemExit(principal())
