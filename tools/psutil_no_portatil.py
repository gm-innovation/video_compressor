#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POE O PSUTIL DENTRO DO PYTHON PORTATIL (26/11/2026, rodada 0.27.0).

O dono pediu CPU, memoria e rede de verdade no retrato de saude. O `ground/saude_do_bordo.py` ja' mede
por psutil quando ele existe e diz `nao_medido` quando nao existe — mas o pacote levava o Python
embeddable 3.12.7 **sem `Lib/site-packages`** e com `#import site` comentado no `python312._pth`, entao
`import psutil` nunca funcionava no PC de captura.

Este script (idempotente) faz tres coisas:
  1) descompacta a wheel fixada (`PSUTIL_WHEEL`/`PSUTIL_SHA256`) em `tools/python/Lib/site-packages/`;
  2) ajusta o `python312._pth` para `python312.zip`, `.`, `Lib\\site-packages` + `import site`;
  3) CONFERE com o proprio python do pacote: `python.exe -c "import psutil; ..."` — sem medir, ele FALHA
     (build que falha e' barato; pacote que sai sem medir e' caro).

Uso:
    python tools/psutil_no_portatil.py                 # instala/conserta e confere
    python tools/psutil_no_portatil.py --somente-conferir  # nao mexe em nada, so' prova (usado no build)
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys
import tempfile
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
PY_DIR = RAIZ / "tools" / "python"
SITE = PY_DIR / "Lib" / "site-packages"
PTH = PY_DIR / "python312._pth"
PYEXE = PY_DIR / "python.exe"

# Fixado (mesma wheel que o `pip download --platform win_amd64 --python-version 3.12 --implementation cp`
# devolveu e que esta' no `tools/python/Lib/site-packages` do pacote). abi3 => serve para 3.12.
PSUTIL_VERSAO = "7.2.2"
PSUTIL_WHEEL = f"psutil-{PSUTIL_VERSAO}-cp37-abi3-win_amd64.whl"
PSUTIL_SHA256 = "eb7e81434c8d223ec4a219b5fc1c47d0417b12be7ea866e24fb5ad6e84b3d988"

# O `_pth` do embeddable: sem `Lib\site-packages` e sem `import site` o `import psutil` nao acha nada.
PTH_LINHAS = ["python312.zip", ".", r"Lib\site-packages", "import site"]


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def arrumar_pth() -> bool:
    """Deixa o `python312._pth` do jeito que o embeddable precisa. Devolve True se mudou."""
    if not PTH.exists():
        raise SystemExit(f"ERRO: nao achei {PTH} (o python portatil existe?)")
    atual = PTH.read_text(encoding="utf-8").replace("\r\n", "\n")
    linhas = [l for l in atual.split("\n") if l.strip()]
    quer = list(PTH_LINHAS)
    if linhas == quer:
        return False
    PTH.write_bytes(("\r\n".join(quer) + "\r\n").encode("utf-8"))
    return True


def baixar_wheel(destino: pathlib.Path) -> pathlib.Path:
    """(re)baixa a wheel fixada e CONFERE o sha256 — o pacote tem de ser reconstruivel do zero.

    Usa o `pip download` (que resolve o endereco sozinho na PyPI) em vez de uma URL escrita a mao: URL
    inventada nao se sustenta, e o navegador de arquivos da PyPI tem caminho com hash que muda.
    """
    cmd = [sys.executable, "-m", "pip", "download", f"psutil=={PSUTIL_VERSAO}",
           "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.12",
           "--implementation", "cp", "--no-deps", "--no-cache-dir", "-d", str(destino)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise SystemExit(f"ERRO: o pip nao baixou a wheel:\n{(r.stdout or '')[-800:]}\n{(r.stderr or '')[-800:]}")
    alvo = destino / PSUTIL_WHEEL
    if not alvo.exists():
        achados = sorted(destino.glob("psutil-*.whl"))
        if not achados:
            raise SystemExit(f"ERRO: nenhuma wheel de psutil em {destino}")
        alvo = achados[0]
    obtido = sha256(alvo)
    if obtido != PSUTIL_SHA256:
        raise SystemExit(f"ERRO: sha256 da wheel nao confere (esperado {PSUTIL_SHA256}, obtido {obtido})")
    return alvo


def descompactar(wheel: pathlib.Path) -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as z:
        z.extractall(SITE)


def conferir() -> tuple[bool, str]:
    """O python DO PACOTE importa e mede? Devolve (ok, saida)."""
    if not PYEXE.exists():
        return False, f"sem {PYEXE}"
    codigo = (
        "import json, psutil, time;"
        "c=psutil.cpu_percent(interval=0.2);"
        "v=psutil.virtual_memory();"
        "n=psutil.net_io_counters();"
        "print(json.dumps({'psutil': psutil.__version__, 'cpu_pct': c, 'mem_pct': v.percent,"
        " 'mem_livre_mb': round(v.available/1e6,1), 'mem_total_mb': round(v.total/1e6,1),"
        " 'rede_bytes_enviados': n.bytes_sent, 'rede_bytes_recebidos': n.bytes_recv}))"
    )
    r = subprocess.run([str(PYEXE), "-c", codigo], capture_output=True, text=True, timeout=120)
    saida = (r.stdout or "").strip() or (r.stderr or "").strip()
    return r.returncode == 0 and saida.startswith("{"), saida


def main() -> int:
    ap = argparse.ArgumentParser(description="psutil dentro do Python portatil do pacote")
    ap.add_argument("--somente-conferir", action="store_true", help="nao instala nada, so' prova")
    args = ap.parse_args()

    if not args.somente_conferir:
        if not SITE.joinpath("psutil", "__init__.py").exists():
            with tempfile.TemporaryDirectory() as tmp:
                print(f"baixando {PSUTIL_WHEEL} (sha256 fixado)")
                wheel = baixar_wheel(pathlib.Path(tmp))
                print(f"  sha256 confere: {PSUTIL_SHA256[:16]}…")
                descompactar(wheel)
                print(f"  extraida em {SITE}")
        else:
            print(f"psutil ja' esta' em {SITE}")
        mudou = arrumar_pth()
        print(f"python312._pth: {'ajustado' if mudou else 'ja estava certo'}")

    ok, saida = conferir()
    print(("OK  " if ok else "FALHA ") + f"python do pacote: {saida[:300]}")
    if not ok:
        print("ERRO: o python do pacote NAO mediu CPU/memoria/rede com psutil.")
        return 1
    if not SITE.joinpath("psutil", "__init__.py").exists():
        print("ERRO: o psutil nao esta' dentro de tools/python/Lib/site-packages — o pacote sairia sem medir.")
        return 1
    print("CONFERIDO: psutil no python portatil e medindo (o retrato de saude deixa de dizer 'nao medido').")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
