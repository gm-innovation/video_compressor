#!/usr/bin/env python3
"""Regressão: o ffmpeg vai EMBUTIDO no instalador e o sistema usa o binário certo.

Por que existe: no PC de teste com duas câmeras USB o sistema não listava nenhuma porque **não havia
ffmpeg na máquina** (a única enumeração de dispositivo é `ffmpeg -list_devices`). Agora o instalador
carrega `ffmpeg.exe`/`ffprobe.exe` em `resources/ffmpeg/` e o app entrega o caminho aos processos
filhos por `LECSOR_FFMPEG`/`LECSOR_FFPROBE` (+ a pasta no PATH).

O que este teste prova:
  1) `caminho_ffmpeg()`/`caminho_ffprobe()` preferem o binário do app e caem para o PATH quando a
     variável não existe ou aponta para arquivo inexistente (nunca devolvem caminho que não existe);
  2) a enumeração de dispositivos usa ESSE caminho (argv[0] conferido), não a string "ffmpeg";
  3) não sobrou chamada literal `["ffmpeg", ...]`/`["ffprobe", ...]` nos arquivos de produção;
  4) o empacotamento está declarado: `extraResources` com os dois binários, o script de download
     chamado antes do build, e `tools/ffmpeg/` fora do Git;
  5) `desktop/servidor.js` injeta `LECSOR_FFMPEG` e a pasta no PATH dos filhos quando o binário
     embutido existe (provado rodando o módulo no node com `process.resourcesPath` de mentira).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

import ferramentas  # noqa: E402
import ingestao  # noqa: E402

falhas: list[str] = []


def checar(cond: bool, texto: str) -> None:
    print(("  ok   " if cond else "  FALHA") + f" — {texto}")
    if not cond:
        falhas.append(texto)


local = shutil.which("ffmpeg") or ""
tmp = Path(tempfile.mkdtemp(prefix="ff-embutido-"))
falso = tmp / "ffmpeg.exe"
falso.write_bytes(b"nao e' um ffmpeg de verdade")

print("1) resolução do binário (embutido > PATH > nome puro)")
os.environ["LECSOR_FFMPEG"] = str(falso)
os.environ["LECSOR_FFPROBE"] = str(falso)
d = ferramentas.onde_vem("ffmpeg")
checar(d["origem"] == "embutido no app", f"variável define a origem: {d['origem']!r}")
checar(d["caminho"] == str(falso), "caminho é o da variável")
os.environ["LECSOR_FFMPEG"] = str(tmp / "nao-existe.exe")     # caminho mentiroso
checar(ferramentas.caminho_ffmpeg() != str(tmp / "nao-existe.exe"), "caminho inexistente é ignorado")
os.environ.pop("LECSOR_FFMPEG")
checar(ferramentas.caminho_ffmpeg() == (local or "ffmpeg"), f"sem variável cai para o PATH: {ferramentas.caminho_ffmpeg()!r}")

print("2) a enumeração de câmeras usa o caminho resolvido, não a string 'ffmpeg'")
os.environ["LECSOR_FFMPEG"] = str(falso)
vistos: list[list[str]] = []


class RunFalso:
    def __call__(self, cmd, *a, **k):
        vistos.append(list(cmd))
        return types.SimpleNamespace(stderr='[dshow @ 0] "USB Camera 1" (video)\n', stdout="", returncode=1)


original = ingestao.subprocess
ingestao.subprocess = types.SimpleNamespace(run=RunFalso())
try:
    r = ingestao.listar_dispositivos()
finally:
    ingestao.subprocess = original
checar(bool(vistos) and vistos[0][0] == str(falso), f"argv[0] é o binário do app: {vistos[0][0] if vistos else 'nada'}")
checar(r["video"] == ["USB Camera 1"], f"a câmera foi lida: {r['video']}")
checar(ingestao.caminho_ffprobe() == str(falso), "o ffprobe segue o mesmo caminho")
os.environ.pop("LECSOR_FFMPEG")
os.environ.pop("LECSOR_FFPROBE")

print("3) nenhuma chamada literal sobrou nos arquivos de produção")
alvos = ["ground/ingestao.py", "ground/etapas.py", "ground/qualidade.py", "ground/repasse.py", "board/agent.py"]
texto = "\n".join((RAIZ / a).read_text(encoding="utf-8") for a in alvos)
checar('["ffmpeg"' not in texto and '["ffprobe"' not in texto, "sem `[\"ffmpeg\"` / `[\"ffprobe\"` nos 5 arquivos")
checar("caminho_ffmpeg()" in texto and "caminho_ffprobe()" in texto, "as chamadas passaram pelo resolvedor")

print("4) o empacotamento está declarado")
pkg = json.loads((RAIZ / "desktop" / "package.json").read_text(encoding="utf-8"))
extra = json.dumps(pkg.get("build", {}).get("extraResources", []))
checar("ffmpeg/ffmpeg.exe" in extra, "extraResources leva o ffmpeg.exe")
checar("ffmpeg/ffprobe.exe" in extra, "extraResources leva o ffprobe.exe")
construir = (RAIZ / "desktop" / "construir-instaladores.sh").read_text(encoding="utf-8")
checar("baixar-ffmpeg.sh" in construir, "o build chama o download do binário")
checar("ERRO" in construir, "sem binário o build PARA (não gera instalador sem ffmpeg)")
checar("tools/ffmpeg/" in (RAIZ / ".gitignore").read_text(encoding="utf-8"), "tools/ffmpeg/ está fora do Git")

print("5) servidor.js injeta o binário embutido nos filhos (rodando o módulo no node)")
exe_dir = tmp / "resources" / "ffmpeg"
exe_dir.mkdir(parents=True, exist_ok=True)
(exe_dir / "ffmpeg.exe").write_bytes(b"x")
(exe_dir / "ffprobe.exe").write_bytes(b"x")
script = (
    "const s=require(process.argv[1]); const e=s.amb({}, {});"
    "console.log(JSON.stringify({ff:e.LECSOR_FFMPEG||'', fp:e.LECSOR_FFPROBE||'', path:(e.PATH||'').split(require('path').delimiter)[0]}));"
)
node = shutil.which("node")
if not node:
    print("  (pulado: node não está nesta máquina)")
else:
    r = subprocess.run([node, "-e", "process.resourcesPath=process.argv[2];" + script,
                        str(RAIZ / "desktop" / "servidor.js"), str(tmp / "resources")],
                       capture_output=True, text=True, timeout=120)
    try:
        env = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        env = {}
    checar(env.get("ff", "").endswith("ffmpeg.exe"), f"LECSOR_FFMPEG aponta para o embutido: {env.get('ff')!r}")
    checar(env.get("fp", "").endswith("ffprobe.exe"), f"LECSOR_FFPROBE idem: {env.get('fp')!r}")
    checar(Path(env.get("path", "/nao-existe")).name == "ffmpeg", f"a pasta entrou no PATH: {env.get('path')!r}")
    if not env:
        print("      saída do node:", (r.stdout or "")[:200], (r.stderr or "")[:200])

print()
if falhas:
    print(f"FALHOU — {len(falhas)} verificação(ões):")
    for f in falhas:
        print(" - " + f)
    raise SystemExit(1)
print("OK — ffmpeg embutido resolvido, usado e declarado no empacotamento")
