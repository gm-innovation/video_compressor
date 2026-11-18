#!/usr/bin/env python3
"""A tela de entrada nao pode acusar a SENHA quando o que falta e' a INSTALACAO.

Por que existe (dono, 18/11/2026): o app estava apontado para o servidor LOCAL da propria maquina,
cujo banco nao tem usuario nenhum, e a tela repetia "e-mail ou senha invalidos" a cada tentativa —
parecia senha errada, e o dono reabriu o app varias vezes atras do defeito errado. Agora a resposta
de um servidor local SEM usuario nenhum diz o que falta e traz `primeiro_acesso`, e a tela abre o
cadastro do primeiro administrador desta maquina em vez de insistir no aviso de senha.

O que este teste prova (API de verdade, banco temporario, pedido de dentro da maquina):
  1) instalacao vazia: 401 que aponta o que falta, NAO diz "senha invalidos", e marca
     `primeiro_acesso`/`base_local` para a tela trocar de formulario;
  2) a porta do primeiro acesso esta aberta enquanto nao ha usuario nenhum (`precisa: true`);
  3) cadastrado o primeiro administrador, a mensagem VOLTA a ser a de sempre ("e-mail ou senha
     invalidos") — a instalacao deixou de ser o problema e nao se pode confundir usuario com defeito.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent.parent
falhas: list[str] = []


def exigir(cond: bool, texto: str) -> None:
    print(("  ok    — " if cond else "  FALHOU— ") + texto)
    if not cond:
        falhas.append(texto)


def porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


def pedir(metodo: str, url: str, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        texto = e.read()
        try:
            return e.code, json.loads(texto or b"{}")
        except Exception:
            return e.code, {"_bruto": texto.decode("utf-8", "replace")[:200]}


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-entrada-vazia-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_BIND"] = "127.0.0.1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Sem Supabase neste teste: quem julga e' o hash local, e e' assim que a bancada roda.
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY"):
        env.pop(k, None)
    log = (tmp / "api.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"

    try:
        for _ in range(80):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=2):
                    break
            except Exception:
                continue
        else:
            print("FALHOU— a API nao subiu; log em", tmp / "api.log")
            return 1

        # 1) banco local vazio: a resposta tem que dizer o que falta
        st, corpo = pedir("POST", base + "/api/entrar",
                          {"email": "admin@lecsor.test", "senha": "seja-la-o-que-for"})
        msg = str(corpo.get("erro", ""))
        exigir(st == 401, f"instalacao vazia responde 401 (recebido {st})")
        exigir("usuario nenhum" in msg, f"a mensagem diz que a instalacao nao tem usuario: {msg!r}")
        exigir("senha invalidos" not in msg,
               "a mensagem NAO acusa a senha quando o banco local esta vazio")
        exigir(corpo.get("primeiro_acesso") is True and corpo.get("base_local") is True,
               "a resposta marca primeiro_acesso/base_local (a tela troca de formulario)")

        # 2) a porta do primeiro acesso esta aberta (e aponta que e' criado nesta maquina)
        st, pa = pedir("GET", base + "/api/primeiro-acesso")
        exigir(st == 200 and pa.get("precisa") is True,
               f"sem usuario nenhum, /api/primeiro-acesso pede o cadastro (recebido {pa})")

        # 3) cadastrado o primeiro administrador, a mensagem volta a ser a de sempre
        st, criado = pedir("POST", base + "/api/primeiro-acesso",
                           {"nome": "Administrador da Maquina", "email": "admin@local.test",
                            "senha": "senha-de-bancada-1"})
        exigir(st == 200 and criado.get("papel") == "admin",
               f"o primeiro administrador desta maquina e' criado como admin (recebido {st} {criado})")
        con = sqlite3.connect(banco)
        try:
            n = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        finally:
            con.close()
        exigir(n == 1, f"o banco local passou a ter 1 usuario (tem {n})")

        st, corpo = pedir("POST", base + "/api/entrar",
                          {"email": "admin@local.test", "senha": "senha-errada"})
        exigir(st == 401 and corpo.get("erro") == "e-mail ou senha invalidos",
               f"com usuario cadastrado volta a mensagem de sempre (recebido {st} {corpo})")
        exigir(corpo.get("primeiro_acesso") is None,
               "e nao manda mais a tela para o cadastro do primeiro acesso")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()

    print()
    if falhas:
        print(f"FALHOU — entrada: {len(falhas)} verificacao(oes)")
        return 1
    print("OK — instalacao vazia diz o que falta, nao acusa a senha do usuario")
    return 0


if __name__ == "__main__":
    sys.exit(main())
