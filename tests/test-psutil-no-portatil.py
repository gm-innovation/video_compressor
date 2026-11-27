#!/usr/bin/env python3
"""CPU, MEMORIA E REDE DE VERDADE NO PC DE CAPTURA (dono, 26/11/2026).

Palavras do dono:

    "outra coisa, para termos as informações de cpu, memória e rede, precisamos instalar o psutil,
     inclua isso no plano que está em aberto"

O `ground/saude_do_bordo.py` ja' media por psutil e, sem ele, subia `nao_medido` com o motivo (honesto,
porem mudo). O que faltava era o PACOTE: o Python embeddable 3.12.7 nao tem `Lib/site-packages` nem
`import site` no `python312._pth`, entao `import psutil` nunca funcionava no PC de captura — medido no
retrato REAL da VPS (26/11/2026): `{"cpu_memoria": "sem psutil neste Windows (instalar psutil para
medir)", "rede": "sem psutil: rede nao medida"}`.

Esta prova mede:
  1) a wheel fixada esta' DENTRO de `tools/python/Lib/site-packages` (com o sha256 do que foi baixado);
  2) o `python312._pth` enxerga `Lib\\site-packages` e roda `import site` (sem isso a pasta e' inerte);
  3) o PYTHON DO PACOTE importa e MEDE CPU, memoria e rede (o que vai para o cliente, nao o nosso);
  4) o RETRATO DE SAUDE do proprio python do pacote sai sem `nao_medido` de cpu/memoria e de rede, com
     numero de verdade — e o ponto do historico tambem sai medido;
  5) o build nao pode mais deixar isso cair: os scripts de empacotamento chamam/exigem o psutil.

    python tests/test-psutil-no-portatil.py
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
PYEXE = RAIZ / "tools" / "python" / "python.exe"
SITE = RAIZ / "tools" / "python" / "Lib" / "site-packages"
PTH = RAIZ / "tools" / "python" / "python312._pth"

falhas: list[str] = []


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def roda(args, **kw):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=300, **kw)


def main() -> int:
    print("== 1. a wheel esta' DENTRO do pacote (nao no Python de quem constroi)")
    inicio = SITE / "psutil" / "__init__.py"
    exigir(inicio.exists(), f"tools/python/Lib/site-packages/psutil existe [{inicio}]")
    if not inicio.exists():
        print("\nRESULTADO: sem psutil no pacote nao ha' o que medir — rode: python tools/psutil_no_portatil.py")
        return 1
    dist = sorted(p.name for p in SITE.glob("psutil-*.dist-info"))
    exigir(bool(dist), f"e a wheel deixou o METADADO (versao instalada) [{dist[:1]}]")
    nota("a wheel usada: psutil-7.2.2-cp37-abi3-win_amd64.whl (sha256 "
         "eb7e81434c8d223ec4a219b5fc1c47d0417b12be7ea866e24fb5ad6e84b3d988)")

    print()
    print("== 2. o `_pth` do embeddable aponta para a pasta (sem isso ela e' inerte)")
    linhas = [l.strip() for l in PTH.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") if l.strip()]
    exigir(r"Lib\site-packages" in linhas, f"python312._pth lista Lib\\site-packages [{linhas}]")
    exigir("import site" in linhas, "e roda `import site` (descomentado) — o embeddable nao faz sozinho")
    exigir("#import site" not in linhas, "e nao ficou comentado")

    print()
    print("== 3. o PYTHON DO PACOTE importa e MEDE (e' ele que roda no PC de captura)")
    codigo = ("import json, psutil;"
              "v=psutil.virtual_memory();n=psutil.net_io_counters();"
              "print(json.dumps({'versao': psutil.__version__, 'cpu_pct': psutil.cpu_percent(interval=0.2),"
              " 'mem_pct': v.percent, 'mem_total_mb': round(v.total/1e6,1),"
              " 'enviados': n.bytes_sent, 'recebidos': n.bytes_recv}))")
    r = roda([PYEXE, "-c", codigo])
    med = {}
    try:
        med = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        med = {}
    exigir(r.returncode == 0 and bool(med), f"o python do pacote importou psutil [{r.stdout.strip()[:120] or r.stderr.strip()[:200]}]")
    exigir(isinstance(med.get("cpu_pct"), (int, float)) and 0 <= med["cpu_pct"] <= 100,
           f"CPU medida de verdade [{med.get('cpu_pct')}%]")
    exigir(isinstance(med.get("mem_pct"), (int, float)) and 0 < med["mem_pct"] <= 100,
           f"memoria medida de verdade [{med.get('mem_pct')}% de {med.get('mem_total_mb')} MB]")
    exigir((med.get("enviados") or 0) > 0 or (med.get("recebidos") or 0) > 0,
           f"rede medida de verdade [enviados={med.get('enviados')} recebidos={med.get('recebidos')}]")
    nota(f"psutil {med.get('versao')} no python do pacote")

    print()
    print("== 4. o RETRATO DE SAUDE (o que sobe para o admin) sai medido, nao 'nao medido'")
    sonda = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-psutil-")) / "sonda.py"
    caminho_ground = repr(str(RAIZ / "ground"))
    sonda.write_text(
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {caminho_ground})\n"
        "import saude_do_bordo as s\n"
        "r = s.retrato()\n"
        "print(json.dumps({'cpu_pct': r.get('cpu_pct'), 'memoria_pct': r.get('memoria_pct'),\n"
        "  'memoria_total_mb': (r.get('global') or {}).get('memoria_total_mb'),\n"
        "  'global_cpu': (r.get('global') or {}).get('cpu_pct'),\n"
        "  'interfaces': len(((r.get('rede') or {}).get('interfaces') or [])),\n"
        "  'rede_total': ((r.get('rede') or {}).get('total') or {}),\n"
        "  'ponto': s.ponto_do_retrato(r), 'nao_medido': r.get('nao_medido')}, ensure_ascii=False))\n",
        encoding="utf-8")
    r = roda([PYEXE, str(sonda)])
    ret = {}
    try:
        ret = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        ret = {}
    if not ret:
        nota(f"saida do retrato: {r.stdout[-400:]!r} {r.stderr[-400:]!r}")
    exigir(bool(ret), "o python do pacote rodou o retrato de saude do bordo")
    nm = ret.get("nao_medido") or {}
    exigir("cpu_memoria" not in nm, f"`nao_medido` NAO tem mais cpu/memoria [{nm}]")
    exigir("rede" not in nm, f"`nao_medido` NAO tem mais rede [{nm}]")
    exigir(not nm, f"e nao sobrou nada sem medir nesta maquina [{nm}]")
    exigir(ret.get("cpu_pct") is not None and ret.get("memoria_pct") is not None,
           f"o retrato leva CPU e memoria medidas [{ret.get('cpu_pct')}% / {ret.get('memoria_pct')}%]")
    exigir(ret.get("memoria_total_mb"), f"e o total de memoria [{ret.get('memoria_total_mb')} MB]")
    exigir((ret.get("global_cpu") is not None), f"o bloco GLOBAL da maquina tambem mede [{ret.get('global_cpu')}]")
    exigir((ret.get("interfaces") or 0) > 0, f"a rede traz as interfaces medidas [{ret.get('interfaces')} interface(s)]")
    ponto = ret.get("ponto") or {}
    exigir(ponto.get("cpu") is not None and ponto.get("mem") is not None,
           f"o ponto do historico (a curva do painel) tambem sai medido [cpu={ponto.get('cpu')} mem={ponto.get('mem')}]")
    nota(f"total de rede: {json.dumps({k: v for k, v in (ret.get('rede_total') or {}).items() if 'mb' in k or 'taxa' in k}, ensure_ascii=False)}")

    print()
    print("== 5. o build nao pode deixar o psutil cair de novo")
    r = roda([sys.executable, RAIZ / "tools" / "psutil_no_portatil.py", "--somente-conferir"])
    exigir(r.returncode == 0, f"`tools/psutil_no_portatil.py --somente-conferir` passa (o proprio portao do build) [{r.stdout.strip().splitlines()[-1][:120] if r.stdout.strip() else r.stderr[-200:]}]")
    baixar = (RAIZ / "desktop" / "baixar-servidor.sh").read_text(encoding="utf-8", errors="replace")
    exigir("psutil_no_portatil.py" in baixar, "`desktop/baixar-servidor.sh` instala o psutil (o pacote nasce medindo)")
    construir = (RAIZ / "desktop" / "construir-instaladores.sh").read_text(encoding="utf-8", errors="replace")
    exigir("site-packages/psutil" in construir,
           "`desktop/construir-instaladores.sh` PARA o build sem psutil (build que falha e' barato)")
    pkg = json.loads((RAIZ / "desktop" / "package.json").read_text(encoding="utf-8"))
    leva = any((x.get("to") or "").startswith("servidor/python") for x in pkg["build"]["extraResources"])
    exigir(leva, "o instalador leva `tools/python` inteiro (com o Lib/site-packages dentro)")

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s)")
        for f in falhas:
            print("  -", f)
        return 1
    print("RESULTADO: tudo passou — o python que vai para o cliente mede CPU, memoria e rede de verdade")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
