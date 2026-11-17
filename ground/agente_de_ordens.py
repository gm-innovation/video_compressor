#!/usr/bin/env python3
"""Agente de ordens do BORDO: obedece o que o cliente pediu na tela web.

Ligacao (17/11/2026): o CLIENTE inicia a transmissao pela web; a ordem NASCE no lado terra e este
agente, que roda na maquina de captura, pergunta e executa. **Nao ha' tecnico confirmando nada na
embarcacao** (decisao do dono) e **o bordo nao abre porta nenhuma**: quem mantem a ligacao e' este
agente, que segura a resposta do lado terra ate' aparecer ordem (espera longa) e obedece direto.

O que ele faz com cada ordem:
  - `iniciar` -> chama a API LOCAL (`/api/cameras/ligar`) e a camera entra no ar (mesma cadeia do
    "Enviar video": comprime nesta maquina e o fluxo comprimido vai para o lado terra);
  - `parar`   -> chama `/api/cameras/desligar` e a camera sai do ar.
O resultado (abriu? falhou? por que?) volta ao lado terra, e e' isso que aparece no historico do
cliente.

Uso (roda junto com o app de captura):
    python ground/agente_de_ordens.py                 # fica vivo, perguntando o lado terra
    python ground/agente_de_ordens.py --uma-vez       # atende o que existe agora e sai (teste)
    python ground/agente_de_ordens.py --espera 5      # tempo de cada pergunta

Ambiente (o mesmo do envio ao lado terra):
    LECSOR_LADO_TERRA_API   base HTTP do lado terra (senao: host do LECSOR_DESTINO_SRT + porta)
    LECSOR_DESTINO_SRT      host:porta do SRT do lado terra (para descobrir a base HTTP)
    LECSOR_TOKEN_INGESTAO   token do bordo (obrigatorio)
    LECSOR_EMBARCACAO       embarcacao DESTA maquina (obrigatorio: a ordem e' dela)
    LECSOR_PORTA_LOCAL      porta da API local (padrao: LECSOR_PORTA_API ou 8085)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LOG_DIR = RAIZ / "ground" / "ordens" / "log"
ESPERA_PADRAO = 20.0


def _log(linha: str) -> None:
    texto = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {linha}"
    print(texto, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "agente-de-ordens.log").open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except Exception:
        pass


def base_do_lado_terra() -> str:
    base = (os.environ.get("LECSOR_LADO_TERRA_API") or "").strip().rstrip("/")
    if base:
        return base
    host = (os.environ.get("LECSOR_DESTINO_SRT") or "").split(":")[0].strip()
    porta = (os.environ.get("LECSOR_PORTA_API") or "8085").strip() or "8085"
    return f"http://{host}:{porta}" if host else ""


def base_local() -> str:
    porta = (os.environ.get("LECSOR_PORTA_LOCAL") or os.environ.get("LECSOR_PORTA_API") or "8085").strip()
    return f"http://127.0.0.1:{porta or '8085'}"


def _http(metodo: str, url: str, corpo: dict | None = None, token: str = "", timeout: float = 40.0):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cabecalhos = {"Content-Type": "application/json"} if dados else {}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _chave(acao: str) -> str:
    return "/api/cameras/ligar" if acao == "iniciar" else "/api/cameras/desligar"


def atender(ordem: dict, local: str, base: str, token: str) -> dict:
    """Executa UMA ordem e conta o resultado ao lado terra. Nunca inventa sucesso."""
    cam_id = str(ordem.get("camera_id") or "").strip()
    acao = str(ordem.get("acao") or "").strip()
    if not cam_id or acao not in ("iniciar", "parar"):
        return {"ok": False, "motivo": f"ordem invalida ({acao} / {cam_id})"}
    try:
        s, r = _http("POST", local + _chave(acao), {"camera_id": cam_id})
    except Exception as e:
        # a API local fora do ar NAO pode virar "atendida": a ordem falha e o lado terra fica sabendo
        s, r = 0, {"erro": f"nao alcancei a API local ({type(e).__name__}: {e})"}
    if s == 200 and not r.get("erro"):
        detalhe = f"camera {cam_id}: {acao} feito"
    else:
        erro = str(r.get("erro") or f"a API local respondeu {s}")
        detalhe = f"camera {cam_id}: {acao} falhou ({erro})"
        _log(detalhe)
    corpo = {"estado": "atendida" if s == 200 and not r.get("erro") else "erro",
             "resultado": detalhe, "fluxo_id": str(r.get("fluxo_id") or ordem.get("fluxo_id") or "")}
    # o resultado volta pelo mesmo lado terra que deu a ordem
    try:
        s2, r2 = _http("POST", f"{base}/api/ordens/{ordem['id']}/resultado", corpo, token=token)
    except Exception as e:
        _log(f"aviso: nao consegui contar o resultado da ordem {ordem['id']} ({type(e).__name__}: {e})")
        return {"ok": False, "resultado": detalhe, "resposta_lado_terra": {}}
    if s2 != 200:
        _log(f"aviso: nao consegui contar o resultado da ordem {ordem['id']} ({s2} {r2.get('erro')})")
    return {"ok": corpo["estado"] == "atendida", "resultado": detalhe, "resposta_lado_terra": r2}


def uma_rodada(base: str, local: str, token: str, emb: str, espera: float) -> int:
    s, j = _http("GET", f"{base}/api/ordens?embarcacao_id={emb}&espera={espera:g}", token=token,
                 timeout=max(40.0, espera + 20))
    if s != 200:
        _log(f"aviso: o lado terra recusou a pergunta das ordens ({s} {j.get('erro')})")
        return 0
    ordens = j.get("ordens") or []
    if ordens:
        _log(f"recebi {len(ordens)} ordem(ns) do lado terra")
    for ordem in ordens:
        try:
            atender(ordem, local, base, token)
        except Exception as e:   # uma ordem torta nao pode parar as outras
            _log(f"aviso: falha ao atender a ordem {ordem.get('id')} ({type(e).__name__}: {e})")
    return len(ordens)


def principal() -> int:
    args = sys.argv[1:]
    uma_vez = "--uma-vez" in args
    espera = ESPERA_PADRAO
    if "--espera" in args:
        try:
            espera = float(args[args.index("--espera") + 1])
        except Exception:
            espera = ESPERA_PADRAO
    base = base_do_lado_terra()
    local = base_local()
    token = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
    emb = (os.environ.get("LECSOR_EMBARCACAO") or "").strip()
    if not base or not token or not emb:
        _log("sem lado terra, sem LECSOR_TOKEN_INGESTAO ou sem LECSOR_EMBARCACAO: o agente nao pergunta "
             "nada (a ordem do cliente nao chega nesta maquina). Configure o mesmo ambiente do envio.")
        return 2
    _log(f"agente de ordens no ar: embarcacao {emb} · lado terra {base} · API local {local}")
    while True:
        try:
            uma_rodada(base, local, token, emb, espera)
        except Exception as e:
            _log(f"aviso: falha na rodada ({type(e).__name__}: {e})")
            time.sleep(2)
        if uma_vez:
            return 0


if __name__ == "__main__":
    raise SystemExit(principal())
