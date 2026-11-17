#!/usr/bin/env python3
"""Confere, na fonte, se o CADASTRO PÚBLICO está desligado no Supabase do produto.

Por que existe: o dono pediu (17/11/2026) *"um usuário não pode se cadastrar, quem cadastra os usuários é
o admin"*. O código já não adota mais identidade de fora no login (ver `tests/test-cadastro-so-pelo-admin.py`),
mas o projeto do Supabase também tem de recusar o cadastro — e isso é ajuste de PAINEL, não de código.
Este comando lê o estado REAL do projeto para você não ficar no "deve estar desligado".

Como desligar (painel): supabase.com → abrir o projeto do produto → Authentication → Sign In / Providers →
Email → desmarcar **"Allow new users to sign up"** → Save.

Uso:  python tools/conferir-signup.py        (sai 0 se está fechado; 1 se está ABERTO; 2 se não deu para perguntar)

A chave anônima sai do ambiente do pacote (`desktop/ambiente.json` ou as variáveis `LECSOR_SUPABASE_*`);
NUNCA é impressa — só o estado das chaves de configuração.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def ambiente() -> tuple:
    url = os.environ.get("LECSOR_SUPABASE_URL", "").strip()
    anon = os.environ.get("LECSOR_SUPABASE_ANON_KEY", "").strip()
    if url and anon:
        return url, anon
    for caminho in (RAIZ / "desktop" / "ambiente.json", RAIZ / "ground" / "ambiente.json"):
        if not caminho.exists():
            continue
        try:
            d = json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = (d.get("LECSOR_SUPABASE_URL") or "").strip()
        anon = (d.get("LECSOR_SUPABASE_ANON_KEY") or "").strip()
        if url and anon:
            return url, anon
    return "", ""


def estado(url: str, anon: str) -> dict | None:
    pedido = urllib.request.Request(url.rstrip("/") + "/auth/v1/settings",
                                    headers={"apikey": anon, "Authorization": "Bearer " + anon})
    try:
        with urllib.request.urlopen(pedido, timeout=20) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        print(f"o projeto respondeu {e.code} ao pedido de configuração (chave anônima vale?)")
        return None
    except Exception as e:
        print(f"não deu para perguntar ao projeto: {type(e).__name__}: {e}")
        return None


def principal() -> int:
    url, anon = ambiente()
    if not url or not anon:
        print("sem LECSOR_SUPABASE_URL/_ANON_KEY no ambiente nem em desktop/ambiente.json — não sei dizer")
        return 2
    print(f"projeto: {url}  (chave anônima lida; nenhum segredo é impresso)")
    s = estado(url, anon)
    if s is None:
        return 2
    cadastro_aberto = not bool(s.get("disable_signup"))
    print(f"disable_signup      : {s.get('disable_signup')}")
    print(f"mailer_autoconfirm  : {s.get('mailer_autoconfirm')}")
    if cadastro_aberto:
        print("CADASTRO PUBLICO ABERTO — qualquer pessoa cria conta no Supabase (e o login do produto")
        print("recusa quem nao estiver cadastrado aqui, mas o caminho de fora continua existindo).")
        print("Desligue: Authentication -> Sign In / Providers -> Email -> desmarcar 'Allow new users to sign up'.")
        return 1
    print("OK — o cadastro publico esta FECHADO: usuario so' entra se o administrador cadastrar.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
