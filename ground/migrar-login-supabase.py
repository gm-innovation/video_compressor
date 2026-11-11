#!/usr/bin/env python3
"""Poe os usuarios do app no Supabase Auth com a MESMA senha que ja se usa (idempotente).

Nao inventa senha e nao imprime senha: a senha vem de `LECSOR_SENHA_DEMO` (ambiente ou
`ground/.env.local`). Este script so cria o que falta e confere o login real no
Supabase Auth (`entrar()`), o mesmo caminho que a API usa.

    python ground/migrar-login-supabase.py                 # lista e confere (nao cria)
    python ground/migrar-login-supabase.py --aplicar       # cria o que falta e confere
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

import supabase_auth  # noqa: E402


def ler_env_local(caminho: Path) -> None:
    """Carrega `.env.local` (KEY=VALOR) sem sobrescrever o que ja veio do ambiente."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip().lstrip("\ufeff")
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(RAIZ / "db" / "pipeline.db"))
    ap.add_argument("--env-file", default=str(RAIZ / "ground" / ".env.local"))
    ap.add_argument("--aplicar", action="store_true", help="cria no Supabase o usuario que faltar")
    args = ap.parse_args()

    ler_env_local(Path(args.env_file))
    senha = os.environ.get("LECSOR_SENHA_DEMO", "").strip()
    if not supabase_auth.configurado():
        print("faltam LECSOR_SUPABASE_URL / LECSOR_SUPABASE_ANON_KEY no ambiente")
        return 2
    if not senha:
        print("falta LECSOR_SENHA_DEMO (senha dos usuarios de demonstracao)")
        return 2

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    usuarios = con.execute("SELECT email, nome FROM usuarios WHERE ativo=1 ORDER BY email").fetchall()
    print(f"{len(usuarios)} usuario(s) ativo(s) no banco local")

    faltando = 0
    for u in usuarios:
        email = u["email"].strip().lower()
        ident = supabase_auth.id_por_email(email)
        if ident and not args.aplicar:
            pass
        if args.aplicar and not ident:
            r = supabase_auth.criar_usuario(email, senha, u["nome"])
            ident = r["id"]
            faltando += 1
            print(f"  criado no Supabase Auth: {email} ({'novo' if r['criado'] else 'ja existia'})")
        veredito = supabase_auth.entrar(email, senha)
        situacao = ("existe" if ident else "nao existe") + " / login " + (
            "confere" if (veredito or {}).get("ok") else
            "NAO confere" if veredito is not None else "sem resposta")
        print(f"  {email}: {situacao}")
    if not args.aplicar and faltando == 0:
        print("nada foi criado (rode com --aplicar para criar o que falta)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
