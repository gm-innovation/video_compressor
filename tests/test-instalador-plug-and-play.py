#!/usr/bin/env python3
"""Regressão do instalador PLUG & PLAY: o pacote leva o servidor dentro e o app nasce configurado.

Por que existe: no cliente não pode haver etapa manual (editar config.json, instalar Python, copiar
repositório). O instalador passou a levar `resources/servidor` (código + mediamtx + Python portátil)
e o papel escolhido no build decide o que vem de fábrica (PC de captura aponta para si mesmo, com o
servidor local ligado).

O que este teste prova:
  1) o empacotamento declara o servidor inteiro (código, mediamtx, Python) além do ffmpeg;
  2) os papéis de fábrica: captura -> 127.0.0.1:8765 e ligado; terra -> servidor e desligado;
  3) `servidor.repoDe` prefere a pasta do config quando ela existe e cai para a pasta EMBUTIDA;
  4) `pythonDe` prefere LECSOR_PYTHON, depois .venv, depois o Python embutido, depois o PATH;
  5) `amb` entrega ffmpeg, ffprobe, Python e as pastas no PATH dos filhos (o mediamtx chama
     `python ground/repasse.py`, então o PATH dele precisa do Python embutido);
  6) `subir` sem mediamtx no pacote FALHA dizendo o que falta (nada de servidor "no ar" mentiroso);
  7) o menu mostra o erro do `subir` em vez de descartá-lo, e existe o item de abrir com o Windows;
  8) a análise local é opcional: só sobe se o Python tiver numpy/onnxruntime, e o reinício automático
     tem limite (nada de processo girando para sempre);
  9) instalação limpa cria o banco COMPLETO (todos os `db/schema*.sql`, inclusive a ingestão) e as
     tabelas que o código criava sob demanda (compressoes, telemetria_minuto), e o banco mora na
     pasta do usuário — sobrevive a atualização do aplicativo;
 10) o pacote leva as TELAS inteiras (`fronts/`: vms.css, admin.css, video.js) e o build PARA sem elas;
 11) PROVA DE EXECUÇÃO: o servidor montado como no pacote serve /admin e /fronts/*.css com 200 (era
     404 — foi o "sem css" que o dono viu na instalação do cliente);
 12) a câmera e o papel pela TELA: menu "Testar câmeras desta máquina", endereço e destino editáveis,
     presets de papel e estado do servidor que só diz "no ar" com processo vivo;
 13) a lista de câmeras não volta calada quando a API nega o pedido, e o botão Atualizar dá retorno.
"""
from __future__ import annotations

import json
import os
import shutil
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
    if cond:
        print("  ok    —", texto)
    else:
        print("  FALHOU—", texto)
        falhas.append(texto)


def node(script: str, env: dict | None = None) -> str:
    import os
    amb = dict(os.environ)
    amb.update(env or {})
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=180, env=amb, cwd=str(RAIZ))
    return (r.stdout or "") + (r.stderr or "")


print("1) o empacotamento leva o servidor dentro")
pkg = json.loads((RAIZ / "desktop" / "package.json").read_text(encoding="utf-8"))
extra = json.dumps(pkg["build"]["extraResources"], ensure_ascii=False)
for alvo, nome in [("servidor/ground", "código da API"), ("servidor/tools/mediamtx", "mediamtx"),
                   ("servidor/python", "Python portátil"), ("servidor/admin", "tela de operação"),
                   ("servidor/app", "tela do cliente"), ("ffmpeg/ffmpeg.exe", "ffmpeg")]:
    checar(alvo in extra, f"extraResources leva {nome} ({alvo})")
checar("papeis.json" in json.dumps(pkg["build"]["files"]), "papeis.json entra no app")
checar(pkg["version"] != "0.1.4", f"versão do pacote avançou ({pkg['version']})")

print("2) os papéis de fábrica")
papeis = json.loads((RAIZ / "desktop" / "papeis.json").read_text(encoding="utf-8"))
cap = papeis["captura"]
checar(cap["base"] == "http://127.0.0.1:8765", "captura nasce apontado para esta máquina")
checar(cap["servidorLocal"]["ligado"] is True, "captura nasce com o servidor local ligado")
checar(bool(cap["destinoSrt"]), f"captura nasce com destino de repasse ({cap['destinoSrt']})")
checar(cap.get("abrirComWindows") is True, "captura nasce abrindo junto com o Windows")
terra = papeis["terra"]
checar(terra["base"].startswith("http://") and "8765" not in terra["base"], f"terra aponta para o lado terra ({terra['base']})")
checar(terra["servidorLocal"]["ligado"] is False, "terra nasce com o servidor local desligado")

print("3-6) resolução de pasta, python e ambiente (rodando servidor.js no node)")
tmp = Path(tempfile.mkdtemp(prefix="plugplay-"))
try:
    embutido = tmp / "recursos" / "servidor"
    (embutido / "ground").mkdir(parents=True)
    (embutido / "ground" / "api.py").write_text("# api\n", encoding="utf-8")
    (embutido / "ground" / "mediamtx.yml").write_text("paths: {}\n", encoding="utf-8")
    (embutido / "ground" / "repasse.py").write_text("# repasse\n", encoding="utf-8")
    (embutido / "tools" / "mediamtx").mkdir(parents=True)
    (embutido / "tools" / "mediamtx" / "mediamtx.exe").write_bytes(b"x")
    (embutido / "python").mkdir(parents=True)
    (embutido / "python" / "python.exe").write_bytes(b"x")
    fora = tmp / "repo-do-config"
    (fora / "ground").mkdir(parents=True)
    (fora / "ground" / "api.py").write_text("# api\n", encoding="utf-8")
    (fora / "ground" / "mediamtx.yml").write_text("paths: {}\n", encoding="utf-8")
    (fora / "ground" / "repasse.py").write_text("# repasse\n", encoding="utf-8")
    (fora / "tools" / "mediamtx").mkdir(parents=True)
    (fora / "tools" / "mediamtx" / "mediamtx.exe").write_bytes(b"x")
    (fora / "analytics").mkdir(parents=True)

    script = r"""
const path = require('path');
Object.defineProperty(process, 'resourcesPath', { value: process.env.FAKE_RES });
const s = require(process.env.SERV_JS);
const saida = {};
saida.embutido = s.servidorEmbutido();
saida.comConfig = s.repoDe({ servidorLocal: { repo: process.env.FAKE_REPO } });
saida.configInexistente = s.repoDe({ servidorLocal: { repo: path.join(process.env.FAKE_RES, 'nao-existe') } });
saida.semNada = s.repoDe({});
saida.pythonVar = s.pythonDe(process.env.FAKE_RES + '/servidor');
saida.repo = s.repoDe({ servidorLocal: { repo: process.env.FAKE_REPO } });
saida.amb = s.amb({}, { destinoSrt: '1.2.3.4:8890' }, process.env.FAKE_RES + '/servidor/python/python.exe');
saida.subirComMediamtx = s.subir({ servidorLocal: { repo: process.env.FAKE_REPO, portaApi: 8798 } });
s.parar();
console.log(JSON.stringify(saida));
"""
    serv_js = str(RAIZ / "desktop" / "servidor.js")
    saida_txt = node(script, {"FAKE_RES": str(embutido.parent), "FAKE_REPO": str(fora), "SERV_JS": serv_js})
    linha = [l for l in saida_txt.splitlines() if l.strip().startswith("{")]
    d = json.loads(linha[-1]) if linha else {}
    checar(Path(d.get("embutido", "")) == embutido, f"acha a pasta embutida: {d.get('embutido')}")
    checar(Path(d.get("comConfig", "")) == fora, "usa a pasta do config quando ela existe (bancada)")
    checar(Path(d.get("configInexistente", "")) == embutido, "pasta do config inválida cai para a embutida")
    checar(Path(d.get("semNada", "")) == embutido, "sem nada no config, usa a embutida")
    checar(str(d.get("pythonVar", "")).endswith("python.exe"), f"python resolvido: {d.get('pythonVar')}")
    amb = d.get("amb", {})
    checar(str(amb.get("LECSOR_PYTHON", "")).endswith("python.exe"), "amb entrega LECSOR_PYTHON")
    checar("python" in str(amb.get("PATH", "")).lower(), "amb põe a pasta do python no PATH (o mediamtx chama `python`)")
    checar(amb.get("LECSOR_DESTINO_SRT") == "1.2.3.4:8890", "amb entrega o destino do repasse")
    sub = d.get("subirComMediamtx", {})
    # O binário do fixture é falso, então o spawn falha: o que se prova aqui é que a resolução passou
    # (nada de "faltando") e que o `subir` chegou a tentar subir os processos.
    checar("faltando" not in str(sub.get("erro", "")), f"subir resolve repo/python/mediamtx com o repo do config ({sub})")
    checar(bool(sub.get("ok")) or "spawn" in str(sub.get("erro", "")), f"subir tentou subir os processos ({sub})")

    # faltando mediamtx dentro do pacote: tem que falhar dizendo o que falta
    (embutido / "tools" / "mediamtx" / "mediamtx.exe").unlink()
    saida2 = node(script.replace("process.env.FAKE_REPO", "process.env.FAKE_RES + '/servidor'"), 
                  {"FAKE_RES": str(embutido.parent), "FAKE_REPO": str(fora), "SERV_JS": serv_js})
    linhas2 = [l for l in saida2.splitlines() if l.strip().startswith("{")]
    d2 = json.loads(linhas2[-1]) if linhas2 else {}
    erro = str(d2.get("subirComMediamtx", {}).get("erro", ""))
    checar("mediamtx" in erro, f"sem mediamtx o subir FALHA dizendo o que falta: {erro[:90]}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("7) o menu mostra o erro e o app nasce configurado")
main = (RAIZ / "desktop" / "main.js").read_text(encoding="utf-8")
checar("showErrorBox" in main and "Servidor local NAO subiu" in main, "falha do servidor aparece na tela")
checar("PAPEIS" in main and "papel" in main, "main.js lê o papel do pacote")
checar("gravarConfig(c)" in main, "primeira execução grava o config resolvido")
checar("herdado" in main and "doUsuario.papel !== PAPEL" in main,
       "config herdado de outro papel (ou das versões antigas) não vence o papel do build")
checar('--config.extraMetadata.productName' in (RAIZ / "desktop" / "construir-instaladores.sh").read_text(encoding="utf-8"),
       "cada instalador tem productName próprio no pacote (userData separado)")
checar("Abrir junto com o Windows" in main and "setLoginItemSettings" in main, "item de abrir com o Windows")
baixador = (RAIZ / "desktop" / "baixar-servidor.sh").read_text(encoding="utf-8")
checar("python-3.12" in baixador and len([1 for l in baixador.splitlines() if l.startswith("PY_SHA=")]) == 1,
       "baixador do Python portátil com hash pinado")
checar("python-3.12.7-embed-amd64.zip" in baixador, "fonte do Python é o pacote oficial embeddable")
construir = (RAIZ / "desktop" / "construir-instaladores.sh").read_text(encoding="utf-8")
checar("baixar-servidor.sh" in construir, "o build chama o baixador do servidor")
checar("--config.extraMetadata.papel" in construir, "o build grava o papel no pacote")
checar('construir "LECSOR Captura" admin captura captura' in construir, "existe o instalador do PC de captura")
checar('construir "LECSOR Terra" cliente terra terra' in construir, "existe o instalador do lado terra")
checar("tools/python/" in (RAIZ / ".gitignore").read_text(encoding="utf-8"), "o Python portátil está fora do Git")

print("8) a análise local é opcional; o servidor sobe mesmo sem ela")
srv = (RAIZ / "desktop" / "servidor.js").read_text(encoding="utf-8")
checar("temAnalise" in srv and "import numpy, onnxruntime" in srv,
       "o agente de análise só sobe se o Python tiver as dependências (o portátil não tem)")
checar("registro.tentativas >= 3" in srv, "reinício automático tem limite (não gira para sempre)")
checar("analise local: desligada" in srv, "o app registra no log por que a análise não subiu")
por_from = {e["from"]: e.get("filter", []) for e in pkg["build"]["extraResources"]}
checar({"detector.py", "rastreador.py", "__init__.py"} <= set(por_from.get("../analytics", [])),
       "o pacote leva os módulos que o agente importa (detector/rastreador)")
checar("*.md" not in por_from.get("../ground", []), "o pacote não leva os EVIDENCIA-*.md da bancada")

print("9) o banco: um lugar só e todas as tabelas em instalação limpa")
ferr = (RAIZ / "ground" / "ferramentas.py").read_text(encoding="utf-8")
checar("VAR_BANCO = \"LECSOR_BANCO\"" in ferr and "def caminho_banco" in ferr,
       "caminho do banco resolvido num lugar só (LECSOR_BANCO)")
checar("LECSOR_BANCO" in main, "o app aponta o banco para a pasta do usuário (sobrevive à atualização)")
tmpdb = Path(tempfile.mkdtemp(prefix="plugplay-db-")) / "pipeline.db"
amb = dict(os.environ)
amb["LECSOR_BANCO"] = str(tmpdb)
r = subprocess.run(
    [sys.executable, "-c",
     "import sqlite3, sys; sys.path.insert(0, 'ground'); import api; api.inicializar();\n"
     "print(sorted(x[0] for x in sqlite3.connect(api.BANCO).execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"],
    capture_output=True, text=True, timeout=180, env=amb, cwd=str(RAIZ))
tabelas = r.stdout.strip()
checar(tmpdb.exists(), "banco vazio criado no caminho apontado por LECSOR_BANCO")
checar("ingestoes" in tabelas and "ingestoes_amostras" in tabelas,
       f"instalação limpa cria as tabelas da ingestão (faltava o schema-ingestao.sql): {tabelas[:120]}")
checar("cameras" in tabelas and "usuarios" in tabelas, "as tabelas básicas do acompanhamento entram")
shutil.rmtree(tmpdb.parent, ignore_errors=True)


print("10) o pacote leva as TELAS inteiras (css e video), nao so o servidor")
checar(any(e.get("from") == "../fronts" and e.get("to") == "servidor/fronts" for e in pkg["build"]["extraResources"]),
       "extraResources leva fronts/ -> servidor/fronts (as telas pedem /fronts/vms.css, /fronts/admin.css, /fronts/video.js)")
checar(not any(e.get("from") == "../portal" for e in pkg["build"]["extraResources"]),
       "portal/ saiu do pacote (nenhuma rota da API serve /portal)")
checar(all(f in construir for f in ("../fronts/vms.css", "../fronts/admin.css", "../fronts/video.js")),
       "o build PARA se faltar css/js das telas (mesma regra do ffmpeg)")
for f in ("vms.css", "admin.css", "video.js", "estilo.css"):
    checar((RAIZ / "fronts" / f).is_file() and (RAIZ / "fronts" / f).stat().st_size > 500,
           f"fronts/{f} existe e nao esta vazio")

print("11) o servidor DO PACOTE serve as telas estilizadas (prova de execucao, nao de texto)")
por_from = {e["from"]: e.get("to") for e in pkg["build"]["extraResources"]}
pyserv = RAIZ / "tools" / "python" / "python.exe"
if not pyserv.is_file():
    print("   (pulado: tools/python/python.exe nao esta nesta maquina — rode desktop/baixar-servidor.sh)")
    checar(False, "Python portatil presente para a prova de execucao do pacote")
else:
    pkgdir = Path(tempfile.mkdtemp(prefix="plugplay-pacote-")) / "servidor"
    pkgdir.mkdir(parents=True)
    for origem in ("ground", "admin", "app", "board", "db", "analytics", "fronts"):
        shutil.copytree(RAIZ / origem, pkgdir / origem, ignore=shutil.ignore_patterns("__pycache__", "desktop-logs"))
    porta = 18799
    ambiente = dict(os.environ, LECSOR_BANCO=str(pkgdir / "pipeline.db"), LECSOR_BIND="127.0.0.1")
    proc = subprocess.Popen([str(pyserv), str(pkgdir / "ground" / "api.py"), str(porta)],
                            cwd=str(pkgdir), env=ambiente, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    def buscar(rota):
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{porta}{rota}", timeout=2) as r:
                    return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")
            except Exception:
                time.sleep(0.5)
        return 0, "", ""
    try:
        st, ct, corpo = buscar("/admin")
        checar(st == 200 and "text/html" in ct, f"o servidor do pacote serve /admin (HTTP {st})")
        for arquivo, tipo in (("vms.css", "text/css"), ("admin.css", "text/css"), ("video.js", "javascript")):
            st, ct, corpo = buscar("/fronts/" + arquivo)
            checar(st == 200 and tipo in ct and len(corpo) > 500,
                   f"/fronts/{arquivo} responde HTTP {st} {ct} com conteudo (era 404: pacote sem fronts/)")
        st, ct, _ = buscar("/api/dispositivos")
        checar(st == 200, f"/api/dispositivos responde 200 no servidor do pacote (HTTP {st})")
        st, ct, _ = buscar("/portal")
        checar(st != 200, f"/portal nao e servido pela API (HTTP {st}) — portal/ nao pertence ao pacote")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(pkgdir.parent, ignore_errors=True)

print("12) a camera e o papel: pela TELA, sem editar JSON")
checar("Testar c" in main and "api/dispositivos" in main,
       "menu \"Testar cameras desta maquina\": consulta o loopback (127.0.0.1) mesmo com base no lado terra")
checar("pedirTexto" in main and "LECSOR_RESPOSTA:" in main,
       "o menu pede o valor em janela propria (nao manda mais editar config.json)")
checar("Usar como PC de captura" in main and "Usar como lado terra" in main,
       "presets: uma maquina vira captura ou lado terra sem reinstalar")
checar("ajuste_manual" in main and "!doUsuario.ajuste_manual" in main,
       "escolha do operador na tela vence o papel do instalador no proximo boot")
checar("Destino do repasse (lado terra)" in main and "config.destinoSrt = valor" in main,
       "destino do repasse e' editavel pela tela e grava no config")
checar("vivos()" in srv and "MORREU (codigo" in srv and "servidor local PARADO" in srv,
       "estado do servidor so diz \"no ar\" com processo vivo; morto diz o motivo (porta ocupada)")
checar("caixaServidor" in main, "o menu confere o estado depois de subir e mostra o veredito")

print("13) a lista de cameras nao volta mais calada")
adm = (RAIZ / "admin" / "admin.js").read_text(encoding="utf-8")
checar("if (!r.ok) return;" not in adm, "preencherDispositivos nao retorna em silencio quando a API nega o pedido")
checar("respondeu HTTP" in adm and "location.origin" in adm,
       "a tela diz o que a API respondeu e em que endereco ela esta (camera, ffmpeg ou endereco errado)")
checar("Testar c" in adm, "a propria mensagem aponta o menu \"Testar cameras desta maquina\"")
checar("statusAtualizar" in adm and "sem mudan" in adm,
       "botao Atualizar mostra o que fez (atualizando / sem mudancas desde HH:MM:SS)")
checar("status-atualizar" in (RAIZ / "admin" / "index.html").read_text(encoding="utf-8"),
       "o lugar do aviso existe na barra da tela")

print("14) instalacao limpa nao reclama de tabela ausente")
api_txt = (RAIZ / "ground" / "api.py").read_text(encoding="utf-8")
checar("garantir_tabela" in api_txt and "garantir_tabelas" in api_txt,
       "inicializar() cria as tabelas que o codigo criava sob demanda (compressoes, telemetria_minuto)")
tmp14 = Path(tempfile.mkdtemp(prefix="plugplay-tab-")) / "pipeline.db"
amb14 = dict(os.environ, LECSOR_BANCO=str(tmp14))
r14 = subprocess.run(
    [sys.executable, "-c",
     "import sqlite3, sys; sys.path.insert(0, 'ground'); import api; api.inicializar();\n"
     "print(sorted(x[0] for x in sqlite3.connect(api.BANCO).execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"],
    capture_output=True, text=True, timeout=180, env=amb14, cwd=str(RAIZ))
tabelas_limpas = r14.stdout.strip() + r14.stderr.strip()
checar("erro" not in r14.stderr.lower(), f"inicializar() de instalacao limpa nao levanta erro: {r14.stderr.strip()[:120]}")
shutil.rmtree(tmp14.parent, ignore_errors=True)
checar("compressoes" in tabelas_limpas and "telemetria_minuto" in tabelas_limpas,
       f"banco de instalacao limpa ja tem compressoes/telemetria_minuto: {tabelas_limpas[:160]}")


print("15) primeiro acesso: instalacao nova tem como entrar (login de verdade, ponta a ponta)")
checar("primeiro-acesso" in (RAIZ / "ground" / "api.py").read_text(encoding="utf-8"),
       "a API cria o primeiro administrador quando o banco nao tem usuario nenhum")
checar('id="form-primeiro"' in (RAIZ / "admin" / "index.html").read_text(encoding="utf-8"),
       "a tela do admin mostra o formulario de primeiro acesso (sem ele, login novo = beco sem saida)")
checar("primeiroAcesso" in adm and "conferirPrimeiroAcesso" in adm,
       "a tela chama o primeiro acesso quando a API diz que precisa")
porta15 = 18811
db15 = Path(tempfile.mkdtemp(prefix="plugplay-login-")) / "pipeline.db"
prints = [(RAIZ / "ground"), (RAIZ / "db"), (RAIZ / "admin"), (RAIZ / "app"), (RAIZ / "fronts"), (RAIZ / "analytics"), (RAIZ / "board")]
casa = Path(tempfile.mkdtemp(prefix="plugplay-login-")) / "servidor"
for d15 in prints:
    shutil.copytree(d15, casa / d15.name, ignore=shutil.ignore_patterns("__pycache__", "desktop-logs"))
amb15 = dict(os.environ, LECSOR_BANCO=str(db15), LECSOR_BIND="127.0.0.1")
pyserv15 = RAIZ / "tools" / "python" / "python.exe"
if not pyserv15.is_file():
    print("   (pulado: sem tools/python/python.exe nesta maquina)")
else:
    proc15 = subprocess.Popen([str(pyserv15), str(casa / "ground" / "api.py"), str(porta15)],
                              cwd=str(casa), env=amb15, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    def pedir(rota, dados=None, cookie=None):
        req = urllib.request.Request(f"http://127.0.0.1:{porta15}{rota}", method="POST" if dados is not None else "GET")
        if dados is not None:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(dados).encode()
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, json.loads(r.read().decode()), r.headers.get("Set-Cookie", "")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode()), ""
            except Exception:
                return e.code, {}, ""
        except Exception:
            return 0, {}, ""
    for _ in range(40):
        if pedir("/api/primeiro-acesso")[0] == 200:
            break
        time.sleep(0.5)
    try:
        st, corpo, _ = pedir("/api/primeiro-acesso")
        checar(st == 200 and corpo.get("precisa") is True,
               f"instalacao limpa responde precisa=true (HTTP {st}: {corpo})")
        st, corpo, _ = pedir("/api/entrar", {"email": "ninguem@teste.local", "senha": "senha-de-teste-123"})
        checar(st == 401, f"antes do primeiro acesso, login normal falha (HTTP {st}) — era o beco sem saida")
        st, corpo, _ = pedir("/api/primeiro-acesso", {"nome": "Operador de bancada", "email": "operador-teste@local.test",
                                                      "senha": "curta"})
        checar(st == 400, f"senha curta e recusada no primeiro acesso (HTTP {st})")
        st, corpo, setcookie = pedir("/api/primeiro-acesso", {"nome": "Operador de bancada",
                                                              "email": "operador-teste@local.test", "senha": "senha-de-teste-123"})
        cookie = setcookie.split(";")[0] if setcookie else ""
        checar(st == 200 and corpo.get("papel") == "admin" and cookie.startswith("sessao="),
               f"o primeiro acesso cria o administrador e ja abre sessao (HTTP {st}, papel {corpo.get('papel')})")
        st, corpo, _ = pedir("/api/eu", cookie=cookie)
        checar(st == 200 and corpo.get("autenticado") is True, f"a sessao criada vale (HTTP {st}: {corpo})")
        st, corpo, _ = pedir("/api/entrar", {"email": "operador-teste@local.test", "senha": "senha-de-teste-123"})
        checar(st == 200 and corpo.get("ok") is True, f"o login normal passa a funcionar com essa conta (HTTP {st})")
        st, corpo, _ = pedir("/api/primeiro-acesso", {"nome": "Outro", "email": "outro@local.test", "senha": "senha-de-teste-123"})
        checar(st == 403, f"depois do primeiro usuario a rota fecha (HTTP {st}: {corpo.get('erro')})")
        st, corpo, _ = pedir("/api/primeiro-acesso")
        checar(st == 200 and corpo.get("precisa") is False, "instalacao com usuario responde precisa=false")
    finally:
        proc15.terminate()
        try:
            proc15.wait(timeout=10)
        except Exception:
            proc15.kill()
        shutil.rmtree(casa.parent, ignore_errors=True)
        shutil.rmtree(db15.parent, ignore_errors=True)

print()
print("== 16. ambiente do pacote (Supabase/token de ingestao) vai no PC de captura e so nele ==")
marc = (RAIZ / "desktop" / "construir-instaladores.sh").read_text(encoding="utf-8")
checar("ambiente.json" in marc and "leva_ambiente" in marc,
       "o build decide por papel se o ambiente entra no pacote")
checar('construir "LECSOR Captura" admin captura captura 1' in marc,
       "o PC de captura LEVA o ambiente (nasce plug & play)")
for papel_args in ('construir "LECSOR Terra" cliente terra terra 0',
                   'construir "LECSOR Admin" admin terra admin 0',
                   'construir "LECSOR Cliente" cliente terra cliente 0'):
    checar(papel_args in marc, f"so' mostra tela -> SEM ambiente: {papel_args}")
ser = (RAIZ / "desktop" / "servidor.js").read_text(encoding="utf-8")
checar("ambienteDoPacote" in ser and "ambiente.json" in ser,
       "o servidor embutido le' o ambiente do pacote para os processos filhos")
gi = (RAIZ / ".gitignore").read_text(encoding="utf-8")
checar("desktop/ambiente.json" in gi and "ground/ambiente.json" in gi,
       "o ambiente (segredo) esta fora do git")

print()
print("== 17. duas cameras USB de MESMO nome coexistem ==")
r17 = subprocess.run([sys.executable, str(RAIZ / "tests" / "test-cameras-iguais.py")],
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
checar(r17.returncode == 0, "test-cameras-iguais.py passou" if r17.returncode == 0
       else f"test-cameras-iguais.py FALHOU: {(r17.stdout or '')[-400:]}")

print()
print("== 18. o fluxo enviado pelo bordo aparece no lado terra ==")
r18 = subprocess.run([sys.executable, str(RAIZ / "tests" / "test-fluxo-no-lado-terra.py")],
                     capture_output=True, text=True, encoding="utf-8", errors="replace")
checar(r18.returncode == 0, "test-fluxo-no-lado-terra.py passou" if r18.returncode == 0
       else f"test-fluxo-no-lado-terra.py FALHOU: {(r18.stdout or '')[-400:]}")

print()
if falhas:
    print(f"FALHOU — {len(falhas)} verificação(ões):")
    for f in falhas:
        print(" - " + f)
    sys.exit(1)
print("OK — instalador plug & play: servidor dentro do pacote, papel de fábrica e falha em voz alta")
