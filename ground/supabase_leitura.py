"""Leitura do Supabase pelo servidor em terra (producao e disponibilidade).

O navegador NUNCA fala com o Supabase: quem le e' este modulo, rodando no servidor em terra
(nuvem ou do cliente), com as variaveis de ambiente

    LECSOR_SUPABASE_URL          https://<ref>.supabase.co
    LECSOR_SUPABASE_SERVICE_KEY  chave de servico (fica so no ambiente do servidor)

Sem essas variaveis o modulo devolve `configurado: False` e o produto continua funcionando com o
banco local — a integracao nao pode derrubar a tela. Nenhuma chave aparece no codigo nem no repo.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.request

VIEWS = ("v_producao_30d", "v_disponibilidade_30d")
VALIDADE_S = 4.0
_CACHE: dict = {"em": 0.0, "dados": None}


def configurado() -> bool:
    """Diz se o servidor tem URL e chave de servico no ambiente."""
    return bool(os.environ.get("LECSOR_SUPABASE_URL") and os.environ.get("LECSOR_SUPABASE_SERVICE_KEY"))


def _rest(view: str, limite: int = 200, timeout: float = 8.0) -> list:
    """Le uma view pela API REST do Supabase (PostgREST) com a chave de servico do ambiente."""
    base = (os.environ.get("LECSOR_SUPABASE_URL") or "").rstrip("/")
    chave = os.environ.get("LECSOR_SUPABASE_SERVICE_KEY") or ""
    if not base or not chave:
        raise RuntimeError("LECSOR_SUPABASE_URL / LECSOR_SUPABASE_SERVICE_KEY nao definidos")
    pedido = urllib.request.Request(
        f"{base}/rest/v1/{view}?select=*&limit={int(limite)}",
        headers={"apikey": chave, "Authorization": f"Bearer {chave}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(pedido, timeout=timeout) as r:
        corpo = r.read().decode("utf-8") or "null"
    dados = json.loads(corpo)
    return dados if isinstance(dados, list) else []


def resumo(validade_s: float = VALIDADE_S) -> dict:
    """Devolve producao e disponibilidade que estao no Supabase (com cache curto).

    Formato: {"configurado": bool, "producao": [...], "disponibilidade": [...], "erro": str | None}
    """
    import time as _t

    if not configurado():
        return {"configurado": False, "producao": [], "disponibilidade": [],
                "erro": "servidor sem LECSOR_SUPABASE_URL / LECSOR_SUPABASE_SERVICE_KEY",
                "em": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    guardado = _CACHE.get("dados")
    if guardado and (_t.time() - float(_CACHE.get("em") or 0.0)) < validade_s:
        return guardado

    saida: dict = {"configurado": True, "producao": [], "disponibilidade": [], "erro": None,
                   "em": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    for view in VIEWS:
        try:
            saida[view.replace("v_", "").replace("_30d", "")] = _rest(view)
        except urllib.error.HTTPError as e:
            saida["erro"] = f"{view}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:120]}"
        except Exception as e:  # rede fora, DNS, timeout: a tela segue com o banco local
            saida["erro"] = f"{view}: {type(e).__name__} {str(e)[:120]}"
    _CACHE["em"], _CACHE["dados"] = _t.time(), saida
    return saida
