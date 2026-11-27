#!/usr/bin/env python3
"""O GRAVADOR DO HD FALA COM O CADASTRO MESMO NO PYTHON EMBUTIDO (dono, 27/11/2026).

O que o dono via, com a tela na mao:

    no sistema do admin: "o hd de bordo continua nao gravando as imagens do radar de oleo"
    no app de bordo:     "radar - gravando - 0 bloco(s) no HD"
    e o log do gravador (D:\\gravacao-continua.log) tinha UMA linha:

        2026-11-27 09:46:34 gravador subido pelo desejo do admin (pid 4908)
        2026-11-27 09:46:34 gravacao continua ligada mas SEM dispositivo de video:
            nao consegui ler o cadastro desta maquina (ModuleNotFoundError: No module named 'api')
            — nada a fazer

CAUSA: o pacote roda o laco do gravador como processo separado com o Python EMBUTIDO
(`tools/python/python.exe`, o `python312._pth` do instalador). O `._pth` monta o `sys.path` só com
`python312.zip`, `.` e `Lib\\site-packages` — a pasta DO SCRIPT nao entra. Entao o `import api`, que
le o cadastro desta maquina, explodia com `ModuleNotFoundError` e o laco saia na PRIMEIRA linha: 0
blocos, e o `log/gravador.log` do ffmpeg (que so nasce dentro do `gravar()`) nunca existia.

Esta prova mede as duas metades, SEMPRE com o Python do pacote (nunca o Python do sistema, que tem a
pasta do script no `sys.path` e por isso escondia o defeito):

  1) `--estado` (le o cadastro e publica o resumo) tem que devolver o MOTIVO REAL — nunca
     "nao consegui ler o cadastro desta maquina" e nunca um `ModuleNotFoundError`;
  2) o LACO de verdade (`--uma-vez`) sobe e chega a gravar ("gravacao continua no ar ..."), tambem
     sem o erro de import.

    python tests/test-o-gravador-fala-com-o-cadastro-no-python-embutido.py
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import uuid

RAIZ = pathlib.Path(__file__).resolve().parents[1]
PORTATIL = RAIZ / "tools" / "python" / "python.exe"
LACO = RAIZ / "ground" / "gravacao_continua.py"
ERRO_DE_IMPORT = "nao consegui ler o cadastro desta maquina"

falhas: list[str] = []


def exigir(cond: bool, msg: str) -> None:
    marca = "OK  " if cond else "FALHA"
    print(f"  [{marca}] {msg}")
    if not cond:
        falhas.append(msg)


def nota(msg: str) -> None:
    print(f"  [nota] {msg}")


def _rodar(argumentos: list[str], hd: pathlib.Path, extra_env: dict | None = None, timeout: int = 90):
    env = dict(os.environ)
    env["LECSOR_HD_DIR"] = str(hd)
    env.pop("LECSOR_HD_DISPOSITIVO", None)
    env.update(extra_env or {})
    return subprocess.run([str(PORTATIL), str(LACO), *argumentos], cwd=str(RAIZ), env=env,
                          capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def _log(hd: pathlib.Path) -> str:
    p = hd / "log" / "gravacao-continua.log"
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def _desejo_ligado(hd: pathlib.Path) -> None:
    hd.mkdir(parents=True, exist_ok=True)
    (hd / "ligada.txt").write_text("1", encoding="utf-8")


def main() -> int:
    print("O GRAVADOR DO HD FALA COM O CADASTRO NO PYTHON EMBUTIDO (0 blocos, dono 27/11/2026)")
    print()
    print("1) o python do PACOTE e' mesmo o embutido (sem a pasta do script no sys.path)")
    exigir(PORTATIL.exists(), f"o python do pacote existe ({PORTATIL})")
    exigir(LACO.exists(), f"o laco do gravador existe ({LACO})")
    if not PORTATIL.exists() or not LACO.exists():
        print("\nRESULTADO: nao deu para medir (falta o python do pacote ou o laco)")
        return 1
    sonda = subprocess.run([str(PORTATIL), "-c", "import sys, json; print(json.dumps([p for p in sys.path]))"],
                           capture_output=True, text=True, timeout=60, cwd=str(RAIZ))
    try:
        caminhos = json.loads(sonda.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        caminhos = []
    nota(f"sys.path do pacote: {caminhos}")
    exigir(str(LACO.parent) not in [str(p) for p in caminhos],
           "o sys.path do pacote NAO tem a pasta do laco — e' exatamente o que derrubava o `import api`")
    print()

    with tempfile.TemporaryDirectory(prefix="lecsor-hd-prova-") as tmp:
        hd = pathlib.Path(tmp) / "hd"

        print("2) `--estado` (le o cadastro desta maquina) com o python do pacote")
        p = _rodar(["--estado"], hd)
        nota(f"exit={p.returncode} stderr={(p.stderr or '').strip()[:200]!r}")
        try:
            resumo = json.loads(p.stdout[p.stdout.index("{"):p.stdout.rindex("}") + 1])
        except Exception:  # noqa: BLE001
            resumo = {}
        if not resumo:
            nota(f"stdout: {(p.stdout or '')[:400]!r}")
        exigir(bool(resumo), "o `--estado` devolveu o resumo do HD em JSON")
        motivo = str(resumo.get("motivo") or "")
        exigir(ERRO_DE_IMPORT not in motivo,
               f"o motivo NAO e' mais o erro de import (motivo medido: {motivo[:90]!r})")
        exigir("ModuleNotFoundError" not in motivo and "ModuleNotFoundError" not in (p.stdout or ""),
               "nenhum `ModuleNotFoundError` no motivo nem na saida do laco")
        nota(f"dispositivo={resumo.get('dispositivo')!r} origem={resumo.get('dispositivo_origem')!r} "
             f"camera={resumo.get('camera_rotulo')!r}")
        print()

        print("3) o LACO de verdade (`--uma-vez`) sobe e chega a gravar")
        _desejo_ligado(hd)
        aparelho = f"NAO-EXISTE-{uuid.uuid4().hex[:8]}"
        p2 = _rodar(["--uma-vez"], hd, extra_env={"LECSOR_HD_DISPOSITIVO": aparelho,
                                                  "LECSOR_BLOCO_SEGUNDOS": "2"})
        texto = _log(hd)
        nota(f"exit={p2.returncode}")
        nota(f"log do laco:\n" + "\n".join("        " + linha for linha in texto.strip().splitlines()[:6]))
        exigir(ERRO_DE_IMPORT not in texto, "o log do laco nao tem o erro de import")
        exigir("ModuleNotFoundError" not in texto, "o log do laco nao tem `ModuleNotFoundError`")
        exigir("gravacao continua no ar" in texto,
               "o laco subiu de verdade e chegou a gravar (`gravacao continua no ar`)")
        exigir(aparelho in texto, "o laco usou o dispositivo que veio do cadastro/ajuste desta maquina")

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s)")
        for f in falhas:
            print("  -", f)
        return 1
    print("RESULTADO: tudo passou — o gravador le o cadastro e sobe mesmo rodando no Python embutido do "
          "pacote (o defeito dos 0 blocos de 27/11/2026 nao volta)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
