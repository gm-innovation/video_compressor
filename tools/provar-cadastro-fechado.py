#!/usr/bin/env python3
"""Prova, pela fonte, que o cadastro público está FECHADO no Supabase do produto.

Diferente do `conferir-signup.py` (que só lê `disable_signup` na configuração), este prova o COMPORTAMENTO:

1. `GET {url}/auth/v1/settings`          -> `disable_signup` tem de vir `true`.
2. `POST {url}/auth/v1/signup`           -> uma tentativa de cadastro de fora (e-mail de domínio válido) tem de ser
   RECUSADA com `error_code` `signup_disabled` (hoje 422 "Signups not allowed for this instance").

Sem nenhuma credencial privilegiada: usa só a chave anônima (a mesma que o aplicativo leva). A chave nunca é
impressa. Sai 0 = fechado e provado; 1 = cadastro público ABERTO (o problema continua); 2 = não deu para perguntar
(sem rede/chave).

Uso:  python tools/provar-cadastro-fechado.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent.parent
AMBIENTE = RAIZ / "desktop" / "ambiente.json"
ANON_KEY_SUPABASE = "LECSOR_SUPABASE_ANON_KEY"
URL_SUPABASE = "LECSOR_SUPABASE_URL"
EMAIL_DE_PROVA = "prova-cadastro-fechado@gmail.com"  # domínio válido: a recusa tem de vir da POLÍTICA, não do e-mail


def ambiente() -> tuple[str, str]:
    """URL e chave anônima: do `desktop/ambiente.json` ou do ambiente do processo."""
    import os

    url = (os.environ.get(URL_SUPABASE) or "").strip().rstrip("/")
    chave = (os.environ.get(ANON_KEY_SUPABASE) or "").strip()
    if AMBIENTE.exists():
        try:
            dados = json.loads(AMBIENTE.read_text(encoding="utf-8"))
        except Exception:
            dados = {}
        chave = chave or str(dados.get(ANON_KEY_SUPABASE) or "").strip()
        url = url or str(dados.get(URL_SUPABASE) or "").strip().rstrip("/")
    return url, chave


def pedir(url: str, chave: str, caminho: str, corpo: dict | None = None) -> tuple[int, dict]:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(
        url + caminho, data=dados, method="POST" if corpo is not None else "GET",
        headers={"apikey": chave, "Authorization": f"Bearer {chave}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:  # rede fora, DNS, TLS...
        return 0, {"erro_de_rede": type(e).__name__}


def principal() -> int:
    url, chave = ambiente()
    if not url or not chave:
        print("NAO SEI — falta URL/chave anonima do Supabase (desktop/ambiente.json ou LECSOR_SUPABASE_*)")
        return 2

    status, config = pedir(url, chave, "/auth/v1/settings")
    if status != 200:
        print(f"NAO SEI — nao deu para ler /auth/v1/settings (status {status})")
        return 2
    desligado = config.get("disable_signup")
    print(f"disable_signup     : {desligado}")
    if desligado is not True:
        print("CADASTRO PUBLICO ABERTO — o pedido do dono ('quem cadastra usuario e' o admin') NAO esta cumprido.")
        print("Desligue em Authentication -> Sign In / Providers -> Email -> desmarcar 'Allow new users to sign up'.")
        return 1

    status, corpo = pedir(url, chave, "/auth/v1/signup",
                          {"email": EMAIL_DE_PROVA, "password": "ProvaCadastroFechado123!"})
    erro = str(corpo.get("error_code") or corpo.get("code") or "")
    if status in (400, 401, 403, 422) and "signup_disabled" in erro:
        print(f"tentativa de fora  : {status} {erro} — RECUSADA (o caminho de cadastro de fora nao existe)")
        print("OK — cadastro publico FECHADO e provado na fonte: usuario so' entra se o administrador cadastrar.")
        return 0
    print(f"CONFIRMACAO DESCONHECIDA — a tentativa de cadastro devolveu {status} {erro or corpo}")
    print("A configuracao diz fechado, mas o comportamento nao confirmou: investigue antes de afirmar.")
    return 1


if __name__ == "__main__":
    sys.exit(principal())
