#!/usr/bin/env python3
"""O aplicativo ABRE? (o servidor local do app precisa subir sem estourar)

Causa do defeito (19/11/2026): em `desktop/servidor.js`, `subir()` devolvia `hd` no `return`, mas `hd`
nascia DENTRO do `try` — `ReferenceError: hd is not defined` em TODA chamada. O unico chamador e' o
`app.whenReady()` do `main.js`, entao a promessa do arranque quebrava e o aplicativo instalado nao
abria janela nenhuma (o dono instalou em 2 computadores e "nenhum deles abre"). `node --check` NAO pega:
e' erro de escopo, nao de sintaxe. E o teste de tela em modo de bancada (`PAPEL=bancada`, servidor local
desligado) tambem nao pegava, porque nele `subir()` nunca e' chamado.

O que esta prova faz: monta um "repositorio" minimo em pasta temporaria, chama `subir()` de verdade
(como o papel `unico` do pacote faz, com o servidor local LIGADO) e exige um resultado com `ok` e `hd`.
Rodar contra a versao com o defeito tem de FALHAR — o proprio teste traz essa prova quando o arquivo
antigo e' acessivel pelo git.

    python tests/test-app-sobe-o-servidor-local.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
SERVIDOR = RAIZ / "desktop" / "servidor.js"
falhas: list[str] = []


def checar(nome, condicao, detalhe=""):
    print(("  OK    " if condicao else "  FALHA ") + nome + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


HARNESS = r"""
// Chama subir() como o papel `unico` do pacote chama (servidor local LIGADO) e conta o que voltou.
const caminho = process.argv[2];
const repo = process.argv[3];
const servidor = require(caminho);
let saida;
try {
  const r = servidor.subir({ capturaLocal: true, servidorLocal: { ligado: true, repo, portaApi: 8799 },
                             base: 'http://127.0.0.1:1', destinoSrt: '' });
  saida = { estourou: false, ok: !!r.ok, chaves: Object.keys(r).sort(), subiu: r.subiu, hd: typeof r.hd };
  servidor.parar();
} catch (e) {
  saida = { estourou: true, erro: String(e && e.message || e), nome: String(e && e.name || '') };
  try { servidor.parar(); } catch (e2) {}
}
setTimeout(() => { console.log('RESULTADO ' + JSON.stringify(saida)); process.exit(0); }, 1200);
"""


def rodar(arquivo_js: pathlib.Path, repo: pathlib.Path) -> dict:
    env = dict(os.environ)
    env["LECSOR_PYTHON"] = sys.executable          # um python de verdade, para passar do `faltando()`
    env["LECSOR_BANCO"] = str(repo / "nao-usado.db")
    with tempfile.TemporaryDirectory(prefix="lecsor-harness-") as tmp:
        h = pathlib.Path(tmp) / "harness.js"
        h.write_text(HARNESS, encoding="utf-8")
        r = subprocess.run(["node", str(h), str(arquivo_js), str(repo)], capture_output=True, text=True,
                           timeout=180, env=env, errors="replace")
    saida = r.stdout + r.stderr
    for linha in saida.splitlines():
        if linha.startswith("RESULTADO "):
            return json.loads(linha[len("RESULTADO "):])
    return {"estourou": True, "erro": "sem RESULTADO na saida: " + saida[-400:]}


def repositorio_de_mentira(tmp: pathlib.Path) -> pathlib.Path:
    """O minimo que `faltando()` exige, para o `try` de `subir()` rodar inteiro."""
    for rel in ("ground/api.py", "ground/mediamtx.yml", "ground/repasse.py"):
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        # a API de mentira fica viva ate' o `parar()`: e' o processo que o app teria subido
        p.write_text("import time\ntime.sleep(600)\n" if rel.endswith("api.py") else "", encoding="utf-8")
    mtx = tmp / "tools" / "mediamtx" / "mediamtx.exe"
    mtx.parent.mkdir(parents=True, exist_ok=True)
    fonte = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
    if fonte.exists():
        shutil.copy2(fonte, mtx)                    # o mediamtx de verdade: spawn de arquivo vazio daria
    else:                                           # 'error' nao tratado e mataria o node do teste
        mtx.write_text("", encoding="utf-8")
    return tmp


def main() -> int:
    print("== o aplicativo sobe o servidor local sem estourar?")
    checar("desktop/servidor.js existe", SERVIDOR.exists(), str(SERVIDOR))
    if not SERVIDOR.exists():
        return 1

    with tempfile.TemporaryDirectory(prefix="lecsor-repo-fake-") as tmpdir:
        repo = repositorio_de_mentira(pathlib.Path(tmpdir))
        r = rodar(SERVIDOR, repo)
        checar("subir() nao estoura", not r.get("estourou"), str(r.get("erro", ""))[:200])
        checar("subir() devolve ok", bool(r.get("ok")), str(r.get("chaves", r))[:200])
        checar("subir() devolve o campo `hd` da gravacao continua do radar",
               r.get("hd") == "string", str(r.get("hd")))

    # A prova de que o teste enxerga o defeito: a versao ANTERIOR do arquivo (do git) tem de falhar.
    antigo = None
    try:
        fonte = subprocess.run(["git", "show", "c874f54:desktop/servidor.js"], cwd=str(RAIZ),
                               capture_output=True, text=True, timeout=60, errors="replace")
        if fonte.returncode == 0 and "let hd = ''" in fonte.stdout:
            antigo = fonte.stdout
    except Exception:
        antigo = None
    if antigo is None:
        print("  PULOU  a prova contra a versao com defeito (git indisponivel nesta copia)")
    else:
        with tempfile.TemporaryDirectory(prefix="lecsor-repo-fake-") as tmpdir:
            repo = repositorio_de_mentira(pathlib.Path(tmpdir))
            ruim = pathlib.Path(tmpdir) / "servidor-com-defeito.js"
            ruim.write_text(antigo, encoding="utf-8")
            r = rodar(ruim, repo)
            checar("a versao COM o defeito estoura (o teste pega)",
                   r.get("estourou") and "hd is not defined" in str(r.get("erro", "")), str(r)[:200])

    print()
    if falhas:
        print("FALHOU: " + "; ".join(falhas))
        return 1
    print("PASSOU: o app sobe o servidor local e o defeito nao voltou")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
