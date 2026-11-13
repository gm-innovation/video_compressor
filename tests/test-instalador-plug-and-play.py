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
  9) instalação limpa cria o banco COMPLETO (todos os `db/schema*.sql`, inclusive a ingestão), e o
     banco mora na pasta do usuário — sobrevive a atualização do aplicativo.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
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

print()
if falhas:
    print(f"FALHOU — {len(falhas)} verificação(ões):")
    for f in falhas:
        print(" - " + f)
    sys.exit(1)
print("OK — instalador plug & play: servidor dentro do pacote, papel de fábrica e falha em voz alta")
