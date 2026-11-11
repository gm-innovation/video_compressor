#!/usr/bin/env python3
"""Regressão: o login é do Supabase Auth, com os MESMOS usuários e senha do app.

Decisão do dono (11/11/2026): "login no supabase com os mesmos usuários e senha que já estamos
utilizando". O navegador continua sem falar com o Supabase — quem fala é a API, no servidor.

O que este teste prova, sem depender de rede nem de servidor no ar:

1) sem `LECSOR_SUPABASE_URL`/`LECSOR_SUPABASE_ANON_KEY` o módulo devolve `None` (indisponível), o
   que faz a API cair no hash local: bancada sem credencial/rede fora continua entrando;
2) o Supabase respondendo "credencial não vale" vira recusa, sem segunda tentativa local (senha
   trocada no Supabase vale aqui);
3) a fiação de `ground/api.py` chama `supabase_auth.entrar` ANTES do hash local, e o caminho do
   auth local só é usado quando o veredito é `None`;
4) `criar_usuario` sem chave de serviço falha alto, em vez de fingir que criou.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
import urllib.error
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

falhas = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("ok   " if condicao else "FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


import supabase_auth  # noqa: E402


def sem_env() -> None:
    for chave in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY"):
        os.environ.pop(chave, None)


# ---------------------------------------------------------------- 1) indisponível -> None
sem_env()
checar("sem URL/chave o módulo não se diz configurado", supabase_auth.configurado() is False)
checar("sem configuração, entrar() devolve None (não recusa o usuário)",
       supabase_auth.entrar("admin@lecsor.test", "qualquer") is None)

# ---------------------------------------------------------------- 2) veredito do Supabase
os.environ["LECSOR_SUPABASE_URL"] = "https://exemplo.supabase.co"
os.environ["LECSOR_SUPABASE_ANON_KEY"] = "chave-falsa-de-teste"
checar("com URL/chave o módulo se diz configurado", supabase_auth.configurado() is True)

original = supabase_auth._pedido
try:
    supabase_auth._pedido = lambda *a, **k: {"user": {"id": "u-1", "email": "Admin@Lecsor.test"}}
    r = supabase_auth.entrar("admin@lecsor.test", "senha")
    checar("resposta com token vira ok", bool(r and r.get("ok")) and r["id"] == "u-1", str(r))
    checar("e-mail volta em minúsculas", (r or {}).get("email") == "admin@lecsor.test", str(r))

    def recusado(*a, **k):
        raise urllib.error.HTTPError("u", 400, "bad", {}, None)
    supabase_auth._pedido = recusado
    r2 = supabase_auth.entrar("admin@lecsor.test", "senha-errada")
    checar("credencial recusada vira {ok: False} (não None)", r2 == {"ok": False, "erro": "e-mail ou senha invalidos", "codigo": 400}, str(r2))

    def caiu(*a, **k):
        raise TimeoutError("rede fora")
    supabase_auth._pedido = caiu
    checar("rede fora vira None (cai no hash local)", supabase_auth.entrar("admin@lecsor.test", "senha") is None)
finally:
    supabase_auth._pedido = original
    sem_env()

# ---------------------------------------------------------------- 3) fiação da API
fonte = (RAIZ / "ground" / "api.py").read_text(encoding="utf-8")
trecho = fonte.split('if rota == "/api/entrar":', 1)[1].split('if rota == "/api/sair":', 1)[0]
checar("a API importa e chama supabase_auth.entrar no /api/entrar",
       "import supabase_auth" in trecho and "supabase_auth.entrar(email, senha)" in trecho)
pos_auth = trecho.find("supabase_auth.entrar(email, senha)")
pos_local = trecho.find("conferir_senha(alvo, senha)")
checar("o Supabase é consultado antes do hash local", -1 < pos_auth < pos_local, f"{pos_auth} < {pos_local}")
checar("o hash local só entra quando o veredito é None", "if veredito is None:" in trecho)
checar("recusa do Supabase não cai para o hash local",
       "entrou = bool(veredito.get(\"ok\")) and bool(alvo)" in trecho)

# ---------------------------------------------------------------- 4) criar usuário sem chave
try:
    supabase_auth.criar_usuario("x@y.test", "senha")
    checar("criar_usuario sem chave de serviço falha alto", False, "não levantou erro")
except RuntimeError:
    checar("criar_usuario sem chave de serviço falha alto", True)

print()
if falhas:
    print("FALHOU:", ", ".join(falhas))
    raise SystemExit(1)
print("tudo certo: o login é do Supabase Auth e o hash local é só a rede de proteção")
