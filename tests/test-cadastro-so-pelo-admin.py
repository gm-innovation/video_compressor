#!/usr/bin/env python3
"""Prova: quem cadastra usuário é o ADMINISTRADOR, e o usuário que ele cria CONSEGUE entrar.

Pedido do dono (17/11/2026, verbatim): *"olha só, estamos tendo muitos problemas, um usuário não pode
se cadastrar, quem cadastra os usuários é o admin"*.

O que esta prova mede, com servidor de verdade (porta livre) e o Supabase DUBLADO no próprio processo
(um `supabase_auth.py` de mentira no PYTHONPATH — nenhuma chamada de rede, nenhuma credencial real):

  1) conta que o Supabase reconhece e esta instalação NÃO conhece toma **403** e **nenhuma** linha é
     criada em `usuarios` (antes o `/api/entrar` adotava a identidade no ato do login);
  2) `POST /api/usuarios` (só admin) cria o usuário local **e** a credencial no Supabase — é o que faz
     o usuário criado pelo administrador conseguir entrar (antes ele tomava 401: senha só local);
  3) o primeiro acesso desta máquina também deixa a credencial nos dois lados e nasce como **admin**;
  4) papel `tecnico` (bordo) é aceito no cadastro e entra;
  5) `POST /api/usuarios/<id>/senha` põe a senha nova nos dois lados (conserto de quem ficou só local);
  6) `GET /api/usuarios?credencial=1` diz quem tem credencial no Supabase (uma listagem, não uma por
     linha) e, sem o parâmetro, responde sem tocar na rede;
  7) não-admin (técnico) não cria usuário nem redefine senha.

Uso: python tests/test-cadastro-so-pelo-admin.py     (ou: python -m unittest tests.test_cadastro_so_pelo_admin)
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Supabase de mentira: guarda os e-mails/senhas em um JSON e registra cada chamada. Fica em um arquivo
# porque roda em OUTRO processo (o do servidor) — a prova lê o estado de lá.
STUB = '''"""Supabase Auth DUBLADO (só para a prova): estado em JSON, nenhuma rede."""
import json, os

print("[dublê] supabase_auth de mentira carregado", flush=True)
ARQ = os.environ.get("LECSOR_STUB_ESTADO", "")


def _ler() -> dict:
    if ARQ and os.path.exists(ARQ):
        with open(ARQ, encoding="utf-8") as f:
            return json.load(f)
    return {"usuarios": {}, "chamadas": []}


def _grava(d: dict) -> None:
    if ARQ:
        with open(ARQ, "w", encoding="utf-8") as f:
            json.dump(d, f)


def configurado() -> bool:
    return True


def pode_administrar() -> bool:
    return True


def entrar(email: str, senha: str, tempo: float = 5) -> dict:
    d = _ler()
    d["chamadas"].append(["entrar", email.lower()])
    _grava(d)
    atual = d["usuarios"].get(email.strip().lower())
    if atual is None or atual != senha:
        return {"ok": False, "erro": "e-mail ou senha invalidos"}
    return {"ok": True, "id": "sup-" + email.strip().lower(), "email": email.strip().lower(),
            "nome": "", "papel": ""}


def criar_usuario(email: str, senha: str, nome: str = "", tempo: float = 5) -> dict:
    d = _ler()
    alvo = email.strip().lower()
    d["chamadas"].append(["criar_usuario", alvo])
    novo = alvo not in d["usuarios"]
    d["usuarios"][alvo] = senha
    _grava(d)
    return {"id": "sup-" + alvo, "email": alvo, "criado": novo}


def id_por_email(email: str, tempo: float = 5):
    d = _ler()
    alvo = email.strip().lower()
    return ("sup-" + alvo) if alvo in d["usuarios"] else None


def emails(tempo: float = 5):
    return set(_ler()["usuarios"].keys())


def definir_senha(email: str, senha: str, nome: str = "", tempo: float = 5) -> dict:
    d = _ler()
    alvo = email.strip().lower()
    d["chamadas"].append(["definir_senha", alvo])
    existia = alvo in d["usuarios"]
    d["usuarios"][alvo] = senha
    _grava(d)
    if existia:
        return {"id": "sup-" + alvo, "email": alvo, "atualizado": True}
    return {"id": "sup-" + alvo, "email": alvo, "criado": True}
'''


WRAPPER = '''"""Sobe o `ground/api.py` com o Supabase DUBLADO na frente do sys.path."""
import os, runpy, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ["LECSOR_GROUND"])            # o código de verdade (e seus vizinhos)
sys.path.insert(0, AQUI)                                   # o dublê na frente
# Importa o dublê AQUI, antes do api.py: o api.py faz `sys.path.insert(0, ground)` na linha 35, o que
# devolveria o módulo de verdade para a frente do sys.path. Com o dublê já em `sys.modules`, o
# `import supabase_auth` do api.py (feito dentro do handler) acha ESTE e não o real: nenhuma rede.
import supabase_auth as _duble                                     # noqa: F401
sys.argv = [os.path.join(os.environ["LECSOR_GROUND"], "api.py")] + sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


def porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


def pede(url: str, metodo: str = "GET", corpo=None, cookie: str = "") -> tuple:
    """(status, cabecalhos, corpo-json). Devolve o corpo mesmo em 4xx — é o que a prova lê."""
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            texto = r.read().decode()
            return r.status, dict(r.headers), (json.loads(texto) if texto else None)
    except urllib.error.HTTPError as e:
        texto = e.read().decode()
        try:
            devolvido = json.loads(texto) if texto else None
        except Exception:
            devolvido = {"cru": texto[:200]}
        return e.code, dict(e.headers), devolvido


def cookie_de(resposta) -> str:
    valor = resposta[1].get("Set-Cookie") or resposta[1].get("set-cookie") or ""
    return valor.split(";")[0]


class CadastroSoPeloAdmin(unittest.TestCase):
    """Servidor de verdade + Supabase dublado: cada passo é um fato medido, não uma expectativa."""

    cookie_admin = ""
    cookie_tecnico = ""
    id_tecnico = ""

    @classmethod
    def setUpClass(cls):
        cls.porta = porta_livre()
        cls.tmp = tempfile.TemporaryDirectory(prefix="prova-cadastro-admin-")
        raiz = Path(cls.tmp.name)
        cls.stubdir = raiz / "stub"
        cls.stubdir.mkdir()
        (cls.stubdir / "supabase_auth.py").write_text(STUB, encoding="utf-8")
        (cls.stubdir / "servidor_de_prova.py").write_text(WRAPPER, encoding="utf-8")
        cls.estado = raiz / "estado.json"
        cls.estado.write_text(json.dumps({"usuarios": {}, "chamadas": []}), encoding="utf-8")
        cls.banco = raiz / "banco.db"
        env = dict(os.environ)
        env["LECSOR_BANCO"] = str(cls.banco)
        env["LECSOR_BIND"] = "127.0.0.1"
        env["LECSOR_STUB_ESTADO"] = str(cls.estado)
        env["LECSOR_GROUND"] = str(RAIZ / "ground")
        cls.log = open(raiz / "api.log", "w", encoding="utf-8")
        # O wrapper põe o DUBLÊ na frente do sys.path: é o que faz o `import supabase_auth` do api.py
        # achar o de mentira em vez do módulo real que está ao lado dele (nenhuma rede, nenhuma chave).
        cls.proc = subprocess.Popen([sys.executable, str(cls.stubdir / "servidor_de_prova.py"), str(cls.porta)],
                                    cwd=str(RAIZ), env=env, stdout=cls.log, stderr=subprocess.STDOUT)
        cls.base = f"http://127.0.0.1:{cls.porta}"
        limite = time.time() + 45
        while time.time() < limite:
            try:
                if pede(cls.base + "/api/saude")[0] == 200:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        cls.log.flush()
        raise AssertionError("o servidor nao subiu em 45 s: " +
                             (raiz / "api.log").read_text(encoding="utf-8", errors="replace")[-2000:])

    @classmethod
    def tearDownClass(cls):
        for perto in (lambda: cls.proc.terminate(), lambda: cls.proc.wait(timeout=10)):
            try:
                perto()
            except Exception:
                pass
        try:
            cls.proc.kill()
        except Exception:
            pass
        try:
            cls.log.close()
            cls.tmp.cleanup()
        except Exception:
            pass

    # ---- utilidades da prova
    @classmethod
    def stub_estado(cls) -> dict:
        return json.loads(cls.estado.read_text(encoding="utf-8"))

    @classmethod
    def stub_semear(cls, email: str, senha: str) -> None:
        """Simula alguém que se cadastrou POR FORA (conta existe no Supabase, não na instalação)."""
        d = cls.stub_estado()
        d["usuarios"][email.lower()] = senha
        cls.estado.write_text(json.dumps(d), encoding="utf-8")

    @classmethod
    def stub_recebeu(cls, funcao: str, email: str) -> bool:
        return [funcao, email.lower()] in cls.stub_estado()["chamadas"]

    def usuarios_locais(self) -> list:
        with sqlite3.connect(self.banco) as c:
            c.row_factory = sqlite3.Row
            return [dict(x) for x in c.execute("SELECT id,email,nome,papel,ativo FROM usuarios")]

    # ---- 1) primeiro acesso desta máquina
    def test_01_primeiro_acesso_cria_admin_nos_dois_lados(self):
        codigo, _, corpo = pede(self.base + "/api/primeiro-acesso", "POST",
                                {"nome": "Alexandre", "email": "alexandre@lecsor.test",
                                 "senha": "senhaforte1"})
        self.assertEqual(codigo, 200, corpo)
        self.assertEqual(corpo.get("papel"), "admin")
        self.assertEqual(corpo.get("supabase"), "ok", "a credencial tem de subir para o Supabase")
        self.assertTrue(self.stub_recebeu("definir_senha", "alexandre@lecsor.test"),
                        "o Supabase dublado tinha de receber a senha do primeiro acesso")
        locais = self.usuarios_locais()
        self.assertEqual(len(locais), 1)
        self.assertEqual(locais[0]["papel"], "admin")
        # o Set-Cookie vem da resposta real: entra de novo guardando o cabecalho
        codigo, cab, corpo = pede(self.base + "/api/entrar", "POST",
                                  {"email": "alexandre@lecsor.test", "senha": "senhaforte1"})
        self.assertEqual(codigo, 200, corpo)
        self.__class__.cookie_admin = cookie_de((codigo, cab, corpo))
        self.assertTrue(self.__class__.cookie_admin.startswith("sessao="))

    # ---- 2) quem se cadastrou por fora NÃO entra (e nada é criado no banco local)
    def test_02_conta_de_fora_toma_403_e_nao_cria_linha(self):
        self.stub_semear("invasor@exemplo.test", "senha12345")
        antes = len(self.usuarios_locais())
        codigo, _, corpo = pede(self.base + "/api/entrar", "POST",
                                {"email": "invasor@exemplo.test", "senha": "senha12345"})
        self.assertEqual(codigo, 403, corpo)
        self.assertIn("administrador", json.dumps(corpo, ensure_ascii=False))
        self.assertEqual(len(self.usuarios_locais()), antes,
                         "o login NAO pode criar usuario: quem cadastra e' o administrador")
        self.assertTrue(self.stub_recebeu("entrar", "invasor@exemplo.test"),
                        "a prova precisa mostrar que o Supabase reconheceu — e a instalacao recusou")

    # ---- 3) o administrador cria o tecnico; o tecnico ENTRA
    def test_03_usuario_criado_pelo_admin_entra(self):
        codigo, _, corpo = pede(self.base + "/api/usuarios", "POST",
                                {"nome": "Tecnico Bordo", "email": "tecnico@lecsor.test",
                                 "papel": "tecnico"}, cookie=self.cookie_admin)
        self.assertEqual(codigo, 201, corpo)
        self.assertEqual(corpo.get("papel"), "tecnico", "papel tecnico (bordo) tem de ser aceito")
        self.assertEqual(corpo.get("supabase"), "ok", corpo.get("supabase"))
        # a credencial é posta pelo `definir_senha` (cria se não existe; troca se existe) — é o mesmo
        # caminho do "redefinir senha", de propósito: uma função só para os dois casos
        self.assertTrue(self.stub_recebeu("definir_senha", "tecnico@lecsor.test"))
        senha = corpo["senha_inicial"]
        codigo, cab, corpo2 = pede(self.base + "/api/entrar", "POST",
                                   {"email": "tecnico@lecsor.test", "senha": senha})
        self.assertEqual(codigo, 200, corpo2)
        self.assertEqual(corpo2.get("papel"), "tecnico")
        self.__class__.id_tecnico = corpo["id"]
        self.__class__.cookie_tecnico = cookie_de((codigo, cab, corpo2))

    # ---- 4) não-admin não cria usuário nem redefine senha
    def test_04_tecnico_nao_cadastra_nem_redefine(self):
        codigo, _, corpo = pede(self.base + "/api/usuarios", "POST",
                                {"nome": "X", "email": "x@lecsor.test", "papel": "admin"},
                                cookie=self.cookie_tecnico)
        self.assertIn(codigo, (401, 403), corpo)
        codigo, _, corpo = pede(self.base + f"/api/usuarios/{self.id_tecnico}/senha", "POST", {},
                                cookie=self.cookie_tecnico)
        self.assertIn(codigo, (401, 403), corpo)

    # ---- 5) redefinir senha grava dos DOIS lados (conserto de quem ficou só com senha local)
    def test_05_redefinir_senha_vale_nos_dois_lados(self):
        antiga = self.stub_estado()["usuarios"]["tecnico@lecsor.test"]
        codigo, _, corpo = pede(self.base + f"/api/usuarios/{self.id_tecnico}/senha", "POST", {},
                                cookie=self.cookie_admin)
        self.assertEqual(codigo, 200, corpo)
        nova = corpo["senha_nova"]
        self.assertNotEqual(nova, antiga)
        self.assertEqual(self.stub_estado()["usuarios"]["tecnico@lecsor.test"], nova,
                         "a senha nova tem de valer no Supabase (e' la' que o login confere)")
        self.assertEqual(pede(self.base + "/api/entrar", "POST",
                              {"email": "tecnico@lecsor.test", "senha": nova})[0], 200)
        self.assertEqual(pede(self.base + "/api/entrar", "POST",
                              {"email": "tecnico@lecsor.test", "senha": antiga})[0], 401)

    # ---- 6) a lista diz quem tem credencial (e só pergunta ao Supabase quando pedido)
    def test_06_lista_mostra_credencial(self):
        codigo, _, corpo = pede(self.base + "/api/usuarios", cookie=self.cookie_admin)
        self.assertEqual(codigo, 200, corpo)
        self.assertFalse(corpo.get("verificado"), "sem ?credencial=1 a tela nao pode depender de rede")
        self.assertTrue(all(l["supabase"] is None for l in corpo["usuarios"]))
        codigo, _, corpo = pede(self.base + "/api/usuarios?credencial=1", cookie=self.cookie_admin)
        self.assertEqual(codigo, 200, corpo)
        self.assertTrue(corpo.get("verificado"))
        por_email = {l["email"]: l["supabase"] for l in corpo["usuarios"]}
        self.assertTrue(por_email["tecnico@lecsor.test"])
        self.assertTrue(por_email["alexandre@lecsor.test"])

    # ---- 7) o cadastro por fora continua fechado no NOSSO código, não só no painel
    def test_07_codigo_nao_adota_identidade_no_login(self):
        fonte = (RAIZ / "ground" / "api.py").read_text(encoding="utf-8")
        self.assertNotIn("alvo = self._adotar_do_supabase(email, veredito, senha)", fonte,
                         "o /api/entrar nao pode adotar identidade de fora")
        self.assertIn("quem cadastra usuarios e' o administrador", fonte)
        # e a migração do papel tecnico roda sozinha na atualização (nenhum passo manual no cliente)
        self.assertIn("migracao-tecnico.sql", fonte)
        self.assertTrue((RAIZ / "db" / "migracao-tecnico.sql").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
