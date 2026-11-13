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
    """Base HTTP do lado terra: `LECSOR_LADO_TERRA_API` ou o host do SRT na porta 8085."""
    base = (os.environ.get("LECSOR_LADO_TERRA_API") or "").strip().rstrip("/")
    if base:
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
    emb = (os.environ.get("LECSOR_EMBARCACAO") or "").strip()
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


def publicar_cadastro(camera: dict, destino: str | None = None) -> dict:
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
    emb = str(camera.get("embarcacao_id") or os.environ.get("LECSOR_EMBARCACAO") or "").strip()
    if emb:
        corpo["embarcacao_id"] = emb
    req = urllib.request.Request(f"{base}/api/cameras/anuncio", data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read() or b"{}")
        _log(fluxo, f"cadastro publicado no lado terra: {j.get('id')} em {j.get('embarcacao_id')}"
                    + ("" if j.get("ativo") else " (desativada)"))
        return {"ok": bool(j.get("ok")), "resposta": j}
    except Exception as e:
        _log(fluxo, f"nao consegui publicar o cadastro no lado terra ({type(e).__name__}: {e})")
        return {"ok": False, "erro": str(e)}


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
