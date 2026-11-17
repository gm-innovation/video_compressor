#!/usr/bin/env python3
"""Prova: o envio ao vivo só pede à câmera um TAMANHO que ela aceita.

Pedido do dono (17/11/2026, verbatim): *"resolva isso então"* — a transmissão ao vivo pela webcam
morria com `Could not set video options` e a tela dizia "a camera nao abriu".

Causa medida na bancada (não era o seletor PnP): a tela pedia **1920x1080**, o padrão do produto, e a
webcam do notebook só aceita **1280x720, 640x480 e 640x360**. O ffmpeg recusa abrir o dispositivo
quando o tamanho pedido não existe, pelo NOME ou pelo seletor, com o mesmo erro. Pelo nome *funcionava*
no teste porque o teste pedia 1280x720.

O que esta prova mede (a lógica REAL do produto, com a lista REAL da câmera quando ela existe):

  1) lógica pura, com listas injetadas: o maior tamanho suportado que não passe do pedido; se nenhum
     couber, o menor disponível (câmera que só faz 1080p entrega 1080p, não falha); taxa mais próxima
     do pedido sem descer; lista vazia = não força tamanho (o ffmpeg negocia, em vez de derrubar);
  2) varredura da câmera da bancada: TODO tamanho que o produto mandaria existe na lista real dela
     (`-list_options`) — é o defeito que derrubava a transmissão, virado em teste;
  3) o `-video_size` sai de `_formato_do_dispositivo` em `_args_fonte_viva` (sem volta atrás).

Uso: python tests/test-camera-tamanho-suportado.py
"""
from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas: list[str] = []


def checar(cond: bool, texto: str) -> None:
    print(("  ok    — " if cond else "  FALHOU— ") + texto)
    if not cond:
        falhas.append(texto)


def ler(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8", errors="replace")


sys.path.insert(0, str(RAIZ / "ground"))
ingestao = importlib.import_module("ingestao")

print("camera: tamanho pedido x tamanho que a camera aceita\n")

# ---------------------------------------------------------------- 1) logica pura, listas injetadas
TEXTO = r"""
import sys, json
sys.path.insert(0, r"%s")
import ingestao
casos = json.loads(sys.stdin.read())
saida = []
for c in casos:
    ingestao._FORMATOS[c["disp"]] = [tuple(x) for x in c["formatos"]]
    saida.append(ingestao._formato_do_dispositivo(c["disp"], c["largura"], c["altura"], c["fps"]))
print(json.dumps(saida))
""" % str(RAIZ / "ground")

CASOS = [
    {"disp": "cam-720p", "formatos": [[1280, 720, 30.0], [640, 480, 30.0], [640, 360, 30.0], [1280, 720, 10.0]],
     "largura": 1920, "altura": 1080, "fps": 30},
    {"disp": "cam-480p", "formatos": [[1280, 720, 30.0], [640, 480, 30.0]], "largura": 640, "altura": 480, "fps": 30},
    {"disp": "cam-4k", "formatos": [[1920, 1080, 25.0]], "largura": 1280, "altura": 720, "fps": 30},
    {"disp": "cam-60", "formatos": [[1280, 720, 30.0]], "largura": 1280, "altura": 720, "fps": 60},
    {"disp": "cam-muda", "formatos": [], "largura": 1920, "altura": 1080, "fps": 30},
]
import json as _json
r = subprocess.run([sys.executable, "-c", TEXTO], input=_json.dumps(CASOS), capture_output=True, text=True,
                   errors="replace")
if r.returncode or not r.stdout.strip():
    checar(False, f"a logica de escolha roda: {(r.stderr or '')[-160:]}")
    saida = []
else:
    saida = _json.loads(r.stdout.strip())
    checar(True, "a logica de escolha roda isolada (listas injetadas, sem camera)")
if len(saida) == 5:
    checar(saida[0] == ["1280x720", 30], "pedido 1920x1080 numa webcam 720p -> 1280x720@30 (era o defeito do 'a camera nao abriu')")
    checar(saida[1] == ["640x480", 30], "pedido 640x480 -> 640x480@30 (o que a camera aceita e' respeitado)")
    checar(saida[2] == ["1920x1080", 25], "camera que so' faz 1080p25 entrega 1080p25 (nao falha por nao caber no pedido)")
    checar(saida[3] == ["1280x720", 30], "pedido 60 fps numa camera de 30 -> 30 fps (taxa suportada, sem descer demais)")
    checar(saida[4] == [None, 30], "camara que nao responde a lista -> nao forca tamanho (ffmpeg negocia)")

checar(ingestao._tamanho_pedido("lixo") == (1280, 720), "_tamanho_pedido: texto invalido cai no padrao, sem quebrar")

# ------------------------------------------------- 2) a varredura real da camera da bancada
DISP = "@device_pnp_\\\\?\\usb#vid_0408&pid_403d&mi_00#7&2103d784&0&0000#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\\global"
ingestao._FORMATOS.pop(DISP, None)
formatos = ingestao._formatos_do_dispositivo(DISP)
if formatos:
    print(f"  nota  — camera da bancada aceita: {sorted({(w, h) for w, h, _ in formatos})}")
    checar((1280, 720, 30.0) in [tuple(f) for f in formatos], "a lista real da camera traz 1280x720@30")
    checar(all(not (w == 1920 and h == 1080) for w, h, _ in formatos),
           "a lista real da camera NAO tem 1920x1080 (era isso que o produto pedia)")
    for tam in ("1920x1080", "1280x720", "640x480", "640x360", "3840x2160", "100x100"):
        larg, alt = ingestao._tamanho_pedido(tam)
        escolhido, taxa = ingestao._formato_do_dispositivo(DISP, larg, alt, 30)
        suportado = any(w == int(escolhido.split("x")[0]) and h == int(escolhido.split("x")[1]) and abs(f - taxa) < 0.01
                        for w, h, f in formatos)
        checar(suportado, f"pedido {tam:9s} -> {escolhido}@{taxa} existe na lista real da camera")
    args = ingestao._args_fonte_viva("camera", DISP, "1920x1080", 30)
    checar(args[-2:] == ["-i", f"video={DISP.strip()}"], "os argumentos abrem o dispositivo pelo nome/seletor que veio")
    i = args.index("-video_size") + 1 if "-video_size" in args else None
    checar(i is not None and args[i] == "1280x720", "com a camera plugada, o envio pede 1280x720 e nao 1920x1080")
else:
    print("  nota  — sem a webcam da bancada agora: a varredura real foi pulada (a logica acima ja' rodou)")

ingestao._FORMATOS["sintetica-teste"] = []
args_mudo = ingestao._args_fonte_viva("camera", "sintetica-teste", "1920x1080", 30)
checar("-video_size" not in args_mudo, "sem lista de formatos: os argumentos NAO fixam tamanho (o ffmpeg negocia)")
args_sint = ingestao._args_fonte_viva("sintetica", None, "1920x1080", 30)
checar("testsrc2=size=1920x1080:rate=30" in " ".join(args_sint), "fonte sintetica (teste da suite) nao foi tocada")

# ------------------------------------------------------------------- 3) a causa nao volta atras
corpo = ler("ground/ingestao.py")
m = re.search(r"def _args_fonte_viva.*?(?=\ndef )", corpo, re.S)
trecho = m.group(0) if m else ""
checar("_formato_do_dispositivo(" in trecho, "ground/ingestao.py: o tamanho do envio sai da lista REAL da camera")
checar("Could not set video options" in corpo or "1920x1080" in trecho,
       "ground/ingestao.py: o defeito medido esta' registrado no codigo, para nao ser reintroduzido")

print("\n" + ("FALHAS: " + "; ".join(falhas) if falhas else
              "OK — o envio ao vivo so' pede tamanho suportado: pedido 1920x1080 em webcam 720p vira 1280x720 e a transmissao sobe"))
sys.exit(1 if falhas else 0)
