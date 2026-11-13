#!/usr/bin/env python3
"""Regressão do bug "câmera não reconhecida" (12/11/2026).

O dono instalou o app no PC de teste, com duas câmeras ligadas nele, e a tela só mostrava o nome da
webcam da bancada de desenvolvimento. Causa: `listar_dispositivos()` devolvia, como "padrão", um nome
FIXO no código (`DISPOSITIVO_PADRAO = "ACER HD User Facing"`, a webcam da bancada) sempre que o ffmpeg
não encontrava câmera — então qualquer máquina sem câmera exibia um dispositivo que não existe.

O que este teste prova:
  1) sem câmera, a lista volta VAZIA e com `motivo` — e sem inventar `padrao`;
  2) ffmpeg ausente vira `erro` explícito (não silêncio) e `padrao` continua vazio;
  3) com câmeras, as duas aparecem e `padrao` é a primeira (nada de nome fixo);
  4) `LECSOR_DISPOSITIVO` é a única fonte do nome padrão, e o nome da bancada não existe mais no código;
  5) subir captura de câmera sem escolher dispositivo é RECUSADO na borda, com mensagem clara;
  6) subir captura com dispositivo escolhido continua passando da guarda (não quebrou o caminho bom).
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import tempfile
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

import ingestao  # noqa: E402

falhas: list[str] = []


def checar(cond: bool, texto: str) -> None:
    print(("  ok   " if cond else "  FALHA") + f" — {texto}")
    if not cond:
        falhas.append(texto)


class FalsoRun:
    """Substitui subprocess.run só dentro de `listar_dispositivos`."""

    def __init__(self, stderr: str = "", erro: Exception | None = None):
        self.stderr, self.erro = stderr, erro

    def __call__(self, *a, **k):
        if self.erro:
            raise self.erro
        return types.SimpleNamespace(stderr=self.stderr, stdout="", returncode=1)


SAIDA_DUAS = """[dshow @ 000] "USB Video 1" (video)
[dshow @ 000]   Alternative name "@device_pnp_1"
[dshow @ 000] "USB Video 2" (video)
[dshow @ 000]   Alternative name "@device_pnp_2"
[dshow @ 000] "Microfone (USB Audio)" (audio)
[dshow @ 000]   Alternative name "@device_pnp_3"
"""


def com_run(falso, fn):
    original = ingestao.subprocess
    ingestao.subprocess = types.SimpleNamespace(run=falso)
    try:
        return fn()
    finally:
        ingestao.subprocess = original


print("1) máquina sem câmera: lista vazia, com motivo, sem dispositivo inventado")
d = com_run(FalsoRun("ffmpeg version 6.1\n[dshow @ 000] 'dummy' (video)\n"), ingestao.listar_dispositivos)
checar(d["video"] == [], "video veio vazio")
checar(d["padrao"] == "", "padrao veio vazio (antes vinha o nome da webcam da bancada)")
checar(bool(d.get("motivo")) and "não encontrou" in d["motivo"].replace("nao", "não"), f"motivo explicando: {d.get('motivo')!r}")
checar(bool(d.get("maquina")), f"diz de qual máquina é a lista: {d.get('maquina')!r}")

print("2) ffmpeg ausente: erro explícito, nunca silêncio")
d = com_run(FalsoRun(erro=FileNotFoundError("ffmpeg")), ingestao.listar_dispositivos)
checar("ffmpeg" in (d.get("erro") or ""), f"erro fala de ffmpeg: {d.get('erro')!r}")
checar("ffmpeg" in (d.get("motivo") or ""), "motivo diz o que fazer")
checar(d["video"] == [] and d["padrao"] == "", "sem lista e sem padrão inventado")

print("3) duas câmeras: as duas aparecem e o padrão é a primeira")
d = com_run(FalsoRun(SAIDA_DUAS), ingestao.listar_dispositivos)
checar(d["video"] == ["USB Video 1", "USB Video 2"], f"listou as duas: {d['video']}")
checar(d["audio"] == ["Microfone (USB Audio)"], f"listou o áudio: {d['audio']}")
checar(d["padrao"] == "USB Video 1", "padrão = primeira encontrada")
checar("motivo" not in d, "sem câmera não há motivo de vazio")

print("4) o nome da bancada não existe mais no código; o padrão vem do ambiente")
fonte = (RAIZ / "ground" / "ingestao.py").read_text(encoding="utf-8")
checar("ACER HD User Facing" not in fonte, "nenhum nome de dispositivo fixo em ground/ingestao.py")
checar("LECSOR_DISPOSITIVO" in fonte, "o padrão vem de LECSOR_DISPOSITIVO")
os.environ["LECSOR_DISPOSITIVO"] = "Camera do Cliente"
ingestao = importlib.reload(ingestao)
d = com_run(FalsoRun(""), ingestao.listar_dispositivos)
checar(d["padrao"] == "Camera do Cliente", "com LECSOR_DISPOSITIVO definido, o padrão é ele")
del os.environ["LECSOR_DISPOSITIVO"]
ingestao = importlib.reload(ingestao)
checar(ingestao.DISPOSITIVO_PADRAO == "", "sem a variável, o padrão é vazio (nunca um chute)")

print("5) captura de câmera sem dispositivo escolhido é recusada na borda")
tmp = Path(tempfile.mkdtemp(prefix="disp-honesto-"))
ingestao.BANCO = tmp / "teste.db"
r = ingestao.iniciar("", rotulo="teste sem camera", tipo="camera")
checar("erro" in r and "camera" in r["erro"], f"recusou com mensagem clara: {r.get('erro')!r}")
checar(not (tmp / "semear").exists(), "nada foi semeado no banco pelo caminho recusado")

print("6) com dispositivo escolhido a guarda não atrapalha (erro passa a ser de outra natureza)")
r = ingestao.iniciar("", rotulo="teste com camera", tipo="camera", dispositivo="USB Video 1",
                     srt_host="127.0.0.1", srt_port=8890, registrar_camera=False)
checar(r.get("erro", "") == "" or "escolha a camera" not in r.get("erro", ""),
       f"não foi barrado pela guarda de dispositivo: {r.get('erro') or 'subiu'!r}")
if r.get("id"):
    try:
        ingestao.parar(r["id"])          # o banco do teste é temporário: não mexe no repositório
    except Exception as e:                # noqa: BLE001
        print(f"  (encerramento reclamou de {type(e).__name__}, sem efeito no repositório)")
    print("  (a captura chegou a subir nesta máquina: encerrada)")

print()
if falhas:
    print(f"FALHOU — {len(falhas)} verificação(ões):")
    for f in falhas:
        print(" - " + f)
    raise SystemExit(1)
print("OK — lista de câmeras honesta e recusa na borda")
