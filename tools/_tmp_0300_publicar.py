#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica a release v0.30.0 no gm-innovation/video_compressor (instalador unico) SEM tocar nas outras.

Antes de criar qualquer coisa, confere que TODA versao em VERSOES_PUBLICADAS (fora a 0.30.0) ja' tem
release no ar — e' isso que impede o `main()` de criar release VAZIA de versao antiga. Depois cria a
v0.30.0 (`make_latest`), sobe `dist/unico/LECSOR-0.30.0-x64.exe`, confere tamanho e digest.

    python tools/_tmp_0300_publicar.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ALVO = "0.30.0"

# 0) a credencial de ESCRITA: a que o proprio git usa (Git Credential Manager). Nunca impressa.
r = subprocess.run(["git", "credential", "fill"], cwd=str(RAIZ),
                   input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True)
token = ""
for linha in (r.stdout or "").splitlines():
    if linha.startswith("password="):
        token = linha[len("password="):]
if not token:
    print("ABORTA: sem credencial de escrita do git (GCM):", (r.stderr or "")[:200])
    sys.exit(2)
os.environ["GITHUB_TOKEN_FOR_RELEASES"] = token

spec = importlib.util.spec_from_file_location("publicar_releases", RAIZ / "tools" / "publicar-releases.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)

# 1) sanidade: as outras versoes publicadas ja' existem no ar?
s, rels = pr.pedir(f"{pr.API}/releases?per_page=100")
if s != 200:
    print(f"ABORTA: nao consegui listar as releases ({s}): {json.dumps(rels)[:200]}")
    sys.exit(2)
no_ar = {x["tag_name"] for x in rels}
faltando = [v for v in pr.VERSOES_PUBLICADAS if v != ALVO and f"v{v}" not in no_ar]
if faltando:
    print(f"ABORTA: estas versoes publicadas NAO tem release no ar (criariam release vazia): {faltando}")
    sys.exit(2)
print(f"OK: {len(pr.VERSOES_PUBLICADAS) - 1} versao(oes) publicada(s) ja' no ar; nada de release vazia.")
print(f"OK: a nota da {ALVO} esta' em publicar-releases.py ({len(pr.NOTAS.get(ALVO, ''))} chars)")

# 2) cria a release (se ja' existir, usa a que esta' la')
s, j = pr.pedir(f"{pr.API}/releases/tags/v{ALVO}")
if s == 200:
    rid, existentes = j["id"], {a["name"] for a in j["assets"]}
    print(f"[{ALVO}] release ja' existia (id {rid}), {len(existentes)} asset(s)")
else:
    s, j = pr.pedir(f"{pr.API}/releases", {"tag_name": f"v{ALVO}", "name": f"v{ALVO}", "body": pr.NOTAS[ALVO],
                                           "draft": False, "prerelease": False, "make_latest": "true"}, "POST")
    if s not in (200, 201):
        print(f"[{ALVO}] FALHOU criar a release: {s} {json.dumps(j)[:300]}")
        sys.exit(1)
    rid, existentes = j["id"], set()
    print(f"[{ALVO}] release criada (id {rid}) — make_latest")

# 3) sobe o instalador
local = pr.instaladores(ALVO)
print(f"instaladores da {ALVO}: {[x.name for x in local]}")
for arquivo in local:
    if not arquivo.exists():
        print(f"[{ALVO}] FALTA o instalador {arquivo}")
        sys.exit(1)
    if arquivo.name in existentes:
        print(f"[{ALVO}] {arquivo.name} ja' estava no ar")
        continue
    print(f"[{ALVO}] subindo {arquivo.name} ({arquivo.stat().st_size} B)…", flush=True)
    print(f"[{ALVO}] -> {pr.subir_asset(rid, arquivo)}", flush=True)

# 4) prova do que ficou no ar
s, rel = pr.pedir(f"{pr.API}/releases/tags/v{ALVO}")
print(f"== release v{ALVO} id {rel.get('id')} publicado em {rel.get('published_at')}")
for a in rel.get("assets", []):
    print(f"   asset: {a['name']} {a['size']} B digest={a.get('digest')}")
s, lat = pr.pedir(f"{pr.API}/releases/latest")
print(f"== latest do repo: {lat.get('tag_name')} id {lat.get('id')}")
h = hashlib.sha256()
with open(RAIZ / "desktop" / "dist" / "unico" / f"LECSOR-{ALVO}-x64.exe", "rb") as fh:
    for bloco in iter(lambda: fh.read(1 << 20), b""):
        h.update(bloco)
sha = h.hexdigest()
digs = [(a.get("digest") or "").split(":")[-1] for a in rel.get("assets", [])]
tam_local = (RAIZ / "desktop" / "dist" / "unico" / f"LECSOR-{ALVO}-x64.exe").stat().st_size
print(f"sha256 local: {sha}")
print(f"TAMANHO BATE: {all(a['size'] == tam_local for a in rel.get('assets', []) if a['name'].endswith('.exe'))}")
print(f"DIGEST BATE: {sha in digs}")
print(f"E' O LATEST: {lat.get('tag_name') == 'v' + ALVO}")
