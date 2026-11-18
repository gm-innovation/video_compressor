#!/usr/bin/env python3
"""Prova: UM aplicativo só, e a tela que abre é a do PAPEL do usuário.

Pedido do dono (17/11/2026, verbatim): *"vamos empacotar em um app apenas, o tipo de app é definido pela
role do usuário"*.

O que esta prova mede (fonte lida + lógica REAL rodada com node + servidor de verdade):

  1) existe a tela de entrada (`entrada/index.html` + `entrada/entrada.js`) e ela roteia pela role:
     cliente -> /app, operador|admin -> /admin, tecnico|captura -> / (Enviar video);
  2) o servidor serve `/entrada` (200, sem cache) — servidor de verdade na porta livre;
  3) o instalador é UM (`construir-instaladores.sh`) no papel `unico`, e `configuracao.js` (a lógica que
     o `main.js` usa, rodada com node) abre `["entrada"]` nesse papel, com a base do lado terra;
  4) o app sabe achar a entrada no servidor LOCAL quando a captura está liberada nesta máquina, e a
     navegação permite o redirecionamento do login;
  5) o console do admin não convida ninguém a se cadastrar: cliente/técnico são mandados para a tela do
     próprio papel, e a tela de usuários mostra a credencial e o botão de redefinir senha.

Uso: python tests/test-app-unico-por-papel.py
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas: list[str] = []


def checar(cond: bool, texto: str) -> None:
    print(("  ok    — " if cond else "  FALHOU— ") + texto)
    if not cond:
        falhas.append(texto)


def ler(rel: str) -> str:
    caminho = RAIZ / rel
    return caminho.read_text(encoding="utf-8", errors="replace") if caminho.exists() else ""


def porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


# ---------------------------------------------------------------- 1) a tela de entrada
print("== 1. a entrada existe e roteia pela role ==")
html = ler("entrada/index.html")
js = ler("entrada/entrada.js")
checar("form-entrar" in html and 'id="senha"' in html and 'id="email"' in html,
       "entrada/index.html tem o formulario de e-mail e senha")
checar("primeiro acesso" in html.lower(),
       "entrada/index.html tambem cobre instalacao nova (primeiro acesso), senao o PC de captura nasce sem login")
checar(re.search(r"TELAS\s*=\s*\{[^}]*cliente:\s*'/app'", js) is not None and
       re.search(r"operador:\s*'/admin'", js) is not None and
       re.search(r"tecnico:\s*'/'", js) is not None,
       "entrada.js mapeia cliente->/app, operador/admin->/admin e tecnico/captura->/")
checar("/api/eu" in js and "/api/entrar" in js and "location.replace" in js,
       "a entrada usa a sessao existente (/api/eu), entra pelo /api/entrar e troca de tela (replace)")
checar("permissao" in js and "SERVIDOR" in js.upper(),
       "o comentario deixa escrito que quem decide e' o servidor (a interface so' escolhe a tela)")

# ---------------------------------------------------------------- 2) o servidor serve /entrada
print("\n== 2. o servidor serve /entrada (servidor de verdade) ==")
porta = porta_livre()
tmp = tempfile.TemporaryDirectory(prefix="prova-app-unico-")
env = dict(os.environ)
env["LECSOR_BANCO"] = str(Path(tmp.name) / "banco.db")
env["LECSOR_BIND"] = "127.0.0.1"
log = open(Path(tmp.name) / "api.log", "w", encoding="utf-8")
proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                        cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
base = f"http://127.0.0.1:{porta}"
try:
    limite = time.time() + 45
    subiu = False
    while time.time() < limite:
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=5) as r:
                subiu = r.status == 200
                break
        except Exception:
            time.sleep(0.5)
    checar(subiu, "a API subiu na porta livre")
    if subiu:
        try:
            with urllib.request.urlopen(base + "/entrada", timeout=8) as r:
                corpo = r.read().decode()
                cache = r.headers.get("Cache-Control", "")
                checar(r.status == 200 and "form-entrar" in corpo,
                       "GET /entrada responde 200 com o formulario de entrada")
                checar("no-store" in cache, "a entrada vem sem cache (no-store): a tela nao pode envelhecer")
        except urllib.error.HTTPError as e:
            checar(False, f"GET /entrada devolveu {e.code}")
        try:
            with urllib.request.urlopen(base + "/entrada/entrada.js", timeout=8) as r:
                checar(r.status == 200, "o /entrada/entrada.js e' servido junto (a tela funciona fora do pacote)")
        except urllib.error.HTTPError as e:
            checar(False, f"GET /entrada/entrada.js devolveu {e.code}")
finally:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    log.close()
    tmp.cleanup()

# ---------------------------------------------------------------- 3) UM instalador
print("\n== 3. um instalador só, no papel `unico` ==")
sh = ler("desktop/construir-instaladores.sh")
linhas = [l.strip() for l in sh.splitlines() if l.strip().startswith("construir ")]
checar(len(linhas) == 1, f"construir-instaladores.sh tem UMA linha de construcao (achei {len(linhas)})")
checar(linhas and linhas[0] == 'construir "LECSOR" entrada unico unico 1',
       f"e essa linha e' o pacote unico que abre a entrada: {linhas[0] if linhas else '(nada)'}")
checar("LECSOR Captura" not in sh and "LECSOR Admin" not in sh and "LECSOR Cliente" not in sh,
       "os quatro instaladores antigos sairam de linha")

papeis = json.loads(ler("desktop/papeis.json") or "{}")
unico = papeis.get("unico") or {}
checar(unico.get("abrirAoIniciar") == ["entrada"], "papeis.json: o papel unico abre a tela de ENTRADA")
checar(unico.get("servidorLocal", {}).get("ligado") is True and unico.get("capturaLocal") is True,
       "papeis.json: o pacote unico nasce com o servidor local e a captura liberados (dono, 18/11/2026: "
       "'o admin tem acesso a tudo, ja deve ter por padrao todas as autorizacoes')")
checar(str(unico.get("base", "")).startswith("http://187.127.60.250:8085"),
       "papeis.json: o pacote unico nasce apontado para o lado terra")

probe = RAIZ / "desktop" / "_probe-app-unico.js"
probe.write_text("""const c = require('./configuracao.js');
const PADRAO = require('./config.json');
const PAPEIS = require('./papeis.json');
const r = c.resolver(PADRAO, PAPEIS, 'unico', null);
process.stdout.write(JSON.stringify({ abrir: r.config.abrirAoIniciar, base: r.config.base,
  servidor: r.config.servidorLocal, captura: !!r.config.capturaLocal }));
""", encoding="utf-8")
try:
    saida = subprocess.run(["node", str(probe)], cwd=str(RAIZ / "desktop"), capture_output=True, text=True, timeout=60)
    resolvido = json.loads(saida.stdout or "{}")
except Exception as e:
    resolvido = {}
    print("  (node falhou:", e, ")")
finally:
    probe.unlink(missing_ok=True)
checar(resolvido.get("abrir") == ["entrada"],
       "configuracao.js (logica real, node): o papel unico abre ['entrada']")
checar(str(resolvido.get("base", "")).startswith("http://187.127.60.250:8085"),
       "configuracao.js: a base do pacote unico e' o lado terra")
checar(resolvido.get("servidor", {}).get("ligado") is True and resolvido.get("captura") is True,
       "configuracao.js: o pacote unico ja nasce com servidor local e captura liberados (plug & play)")

pkg = json.loads(ler("desktop/package.json") or "{}")


def _versao_ok(v: str, minimo: str) -> bool:
    """A versao do pacote e' >= minimo? (a REGRA e' 'da 0.6.0 em diante e' um app so'', nao um numero
    fixo: prender o teste a uma versao faz ele virar vermelho em toda publicacao — foi o que aconteceu
    ao subir a 0.6.1)."""
    try:
        return [int(x) for x in str(v).split(".")] >= [int(x) for x in minimo.split(".")]
    except ValueError:
        return False


checar(_versao_ok(pkg.get("version"), "0.6.0"),
       f"package.json: versao {pkg.get('version')} (>= 0.6.0 = UM aplicativo so', LECSOR-<versao>-x64.exe)")
extras = [e.get("to") for e in (pkg.get("build", {}).get("extraResources") or [])]
checar("servidor/entrada" in extras, "package.json: a pasta entrada vai dentro do pacote")

# ---------------------------------------------------------------- 4) o app abre a entrada certa
print("\n== 4. o app abre a entrada (e acha o servidor local quando captura) ==")
main = ler("desktop/main.js")
checar(re.search(r"entrada:\s*\{[^}]*rota:\s*'/entrada'", main) is not None,
       "main.js: existe a superficie 'entrada' na rota /entrada")
checar("function baseDaEntrada()" in main and "config.capturaLocal" in main,
       "main.js: com a captura liberada nesta maquina a entrada vem do servidor LOCAL (bordo sem internet)")
checar("const permitidos = [config.base, baseDaEntrada(), 'data:']" in main,
       "main.js: a navegacao permite o redirecionamento do login (senao a entrada ficava presa)")
checar("atalhos = { entrada: '0'" in main, "main.js: o menu de superficies nao roubou o atalho das telas")

# ---------------------------------------------------------------- 5) o admin nao convida a cadastrar
print("\n== 5. o console nao convida a cadastrar (quem cadastra e' o admin) ==")
adm = ler("admin/admin.js")
checar("eu.corpo.papel === 'cliente') { window.location.replace('/app')" in adm,
       "admin.js: conta de cliente vai para /app (nao cai na tela de primeiro acesso)")
checar("eu.corpo.papel === 'tecnico') { window.location.replace('/')" in adm,
       "admin.js: conta de tecnico vai para a bancada (Enviar video)")
checar("'Credencial'" in adm and "redefinir senha" in adm,
       "admin.js: a lista de usuarios mostra a credencial no Supabase e o botao de redefinir senha")
checar("/api/usuarios?credencial=1" in adm,
       "admin.js: a verificacao de credencial e' sob demanda (a tela nao depende de rede para desenhar)")
checar("Quem cadastra usuários é o administrador. Não existe cadastro pelo próprio usuário" in adm,
       "admin.js: o texto diz que quem cadastra e' o administrador")
checar("Não existe cadastro pelo próprio usuário" in ler("admin/index.html"),
       "admin/index.html: o login do console repete o aviso")
f4 = ler("db/schema-fase4.sql")
checar("'cliente','operador','admin','tecnico'" in f4,
       "db/schema-fase4.sql: o papel tecnico existe no CHECK (banco novo ja' nasce certo)")
checar((RAIZ / "db" / "migracao-tecnico.sql").exists() and "migracao-tecnico.sql" in ler("ground/api.py"),
       "db/migracao-tecnico.sql existe e a API aplica sozinha na atualizacao (sem passo manual no cliente)")

print("\n" + ("FALHAS: " + "; ".join(falhas) if falhas else
              "OK — um aplicativo só: a tela é a do papel do usuário (entrada única, pacote `unico`, 1 instalador)"))
sys.exit(1 if falhas else 0)
