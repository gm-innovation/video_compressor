#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bump 0.29.0 -> 0.30.0: nota de release, lista de versoes publicadas, `desktop/package.json` e o
`VERSION` da raiz (a versao que o lado terra le' para comparar com a do bordo).

    python tools/_tmp_0300_bump.py              # aplica
    python tools/_tmp_0300_bump.py --verificar  # so' confere
"""
from __future__ import annotations

import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
NL = "\r\n"
ANTES = "0.29.0"
DEPOIS = "0.30.0"

# ------------------------------------------------------------------------------- a nota (dono, 27/11/2026)
NOTA = (
    "**O gravador do HD do radar voltava a morrer por `signal 15` — e a causa era do proprio app: um "
    "pid sozinho NAO e' identidade, e o Windows recicla numero.**\n\n"
    "Palavras do dono no app de captura (27/11/2026): *\"app de captura permanece da mesma forma, 4 "
    "blocos no hd e o gravador nao esta' de pe'\"*. Os dois logs que ele mandou fecharam o caso por "
    "MEDICAO:\n\n"
    "```\n"
    "gravador.log      -> ffmpeg abre a camera certo e morre 4x: Exiting normally, received signal 15\n"
    "gravacao-continua -> o laco subiu 15:03:39 (pid 11448), reergueu o ffmpeg 4x e morreu 15:04:02\n"
    "```\n\n"
    "Duas causas, as duas no produto:\n\n"
    "1. **A checagem de vida MATA.** Medido nesta bancada: `os.kill(pid, 0)` no **Windows MATA** o "
    "processo (chama `TerminateProcess`) — nao \"pergunta se existe\" como no Linux. Era o `_pid_vivo` do "
    "gravador: entao TODA checagem (o supervisor, a tela, o `gravador_de_pe`) DERRUBAVA o laco que "
    "estava conferindo, e o `_subir_gravador` respondia \"ja' estava de pe'\" — o oposto do que a tela "
    "mostrava. Agora a checagem e' pelo `psutil`/WMI, que so' OLHA;\n"
    "2. **O `parar()` matava por pid velho.** O unico ponto do produto que manda `signal 15` para um pid "
    "lido de uma LINHA DO BANCO e' o `parar()` (`ground/ingestao.py`). Quando o dono daquele pid ja' "
    "tinha morrido, o Windows reciclou o numero — e o produto matou o que nao era dele (o ffmpeg do "
    "gravador, que sobe um por vez).\n\n"
    "O que passa a valer: **um pid sozinho nao e' identidade**. `ground/processos.py` responde `criado_em(pid)` "
    "e `mesmo_processo(pid, criado_em_esperado)`, com a regra de ouro **\"na duvida, nao e' o nosso\"**. O "
    "`parar()` grava a hora de criacao do processo na linha ao subir o envio (`ingestoes.pid_criado_em`) e, "
    "na hora de parar, so' mata se a hora de criacao BATER (pid reciclado = nao mata nada, e fica "
    "registrado no log). O supervisor do gravador confere a identidade (nao acha mais que esta' tudo bem "
    "com um pid reciclado) e, se pedir para subir e o laco nao subir, DECLARA a falha com motivo — para a "
    "tela e para o catalogo de terra. O `resumo()` publica `laco_pid`, `laco_criado_em`, `ultimo_bloco_em`, "
    "`segundos_sem_bloco` e `motivo_de_nao_subir` (a tela para de dizer so' \"parado\").\n\n"
    "**A mesma rodada faz a ESCOLHA DO HD sobreviver a atualizacao.** Medido em 27/11/2026: ao passar de "
    "0.28.1 para 0.29.0 a escolha de `D:\\` sumiu (`origem_da_escolha: padrao`) porque o arquivo morava "
    "DENTRO da pasta de instalacao, que e' trocada a cada versao. Agora ele mora na pasta do usuario "
    "(`LECSOR_HD_CONFIG`, mesma ideia do banco em `LECSOR_BANCO`) e a escolha ANTIGA e' resgatada — a "
    "atualizacao nao apaga mais o disco escolhido.\n\n"
    "Provado: `tests/test-identidade-de-processo.py` (pid reciclado NAO mata o alheio; sem hora de criacao "
    "tambem nao; a identidade certa PARA o dono; `processos.vivo` nao mata o que confere; `_camera_em_uso` "
    "nao fica presa por pid de outro), a secao nova da `tests/test-escolha-do-disco-e-cota-do-hd.py` (a "
    "escolha antiga e' resgatada e a nova vence; `LECSOR_HD_CONFIG` tira a escolha do pacote) e a "
    "`tests/test-rele-do-gravador-e-supervisor.py` ajustada a identidade — mais `tools/regressao-0130.py` "
    "e `python -m unittest discover -s tests -p \"test_*.py\"`."
)


def ler(p: pathlib.Path) -> str:
    """Le' SEM traduzir fim de linha (CRLF tem de sobreviver)."""
    with open(p, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def escrever(p: pathlib.Path, texto: str) -> None:
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(texto)


def sanidade() -> bool:
    ok = True
    s = ler(RAIZ / "tools" / "publicar-releases.py")
    if f'VERSOES_PUBLICADAS = ("{DEPOIS}", "{ANTES}"' not in s:
        print(f"FALTA: VERSOES_PUBLICADAS com {DEPOIS}")
        ok = False
    if f'"{DEPOIS}": "' not in s:
        print(f"FALTA: a nota {DEPOIS} em publicar-releases.py")
        ok = False
    if f'"version": "{DEPOIS}"' not in ler(RAIZ / "desktop" / "package.json"):
        print(f"FALTA: desktop/package.json em {DEPOIS}")
        ok = False
    if (RAIZ / "VERSION").read_text(encoding="utf-8").strip() != DEPOIS:
        print(f"FALTA: VERSION com {DEPOIS}")
        ok = False
    return ok


if "--verificar" in sys.argv:
    _ok = sanidade()
    print(f"CONFERIDO: {DEPOIS} no lugar" if _ok else "INCOMPLETO")
    raise SystemExit(0 if _ok else 1)

arq = RAIZ / "tools" / "publicar-releases.py"
src = ler(arq)
orig = src
escapada = json.dumps(NOTA, ensure_ascii=False)[1:-1]

anc = "NOTAS = {" + NL
if src.count(anc) != 1:
    print(f"ABORTA: ancora `NOTAS = {{` esperava 1, achei {src.count(anc)}")
    sys.exit(2)
if f'"{DEPOIS}": ' in src:
    print(f"ja' estava: a nota {DEPOIS}")
else:
    src = src.replace(anc, anc + f'    "{DEPOIS}": "{escapada}",{NL}', 1)

anc2 = f'VERSOES_PUBLICADAS = ("{ANTES}"'
if f'VERSOES_PUBLICADAS = ("{DEPOIS}"' in src:
    print(f"ja' estava: VERSOES_PUBLICADAS com {DEPOIS}")
elif src.count(anc2) == 1:
    src = src.replace(anc2, f'VERSOES_PUBLICADAS = ("{DEPOIS}", "{ANTES}"', 1)
else:
    print(f"ABORTA: ancora VERSOES_PUBLICADAS esperava 1, achei {src.count(anc2)}")
    sys.exit(2)

if src != orig:
    escrever(arq, src)
    print(f"OK publicar-releases.py: nota {DEPOIS} + VERSOES_PUBLICADAS")
else:
    print("OK publicar-releases.py: ja' estava")

pkg = RAIZ / "desktop" / "package.json"
txt = pkg.read_text(encoding="utf-8")
if f'"version": "{DEPOIS}"' in txt:
    print(f"OK desktop/package.json: ja' estava {DEPOIS}")
else:
    alvo_ver = f'"version": "{ANTES}"'
    if txt.count(alvo_ver) != 1:
        print(f"ABORTA: version {ANTES} esperava 1, achei {txt.count(alvo_ver)}")
        sys.exit(2)
    escrever(pkg, txt.replace(alvo_ver, f'"version": "{DEPOIS}"', 1))
    print(f"OK desktop/package.json: {DEPOIS}")

ver = RAIZ / "VERSION"
if ver.exists() and ver.read_text(encoding="utf-8").strip() == DEPOIS:
    print(f"OK VERSION: ja' estava {DEPOIS}")
else:
    escrever(ver, DEPOIS + "\n")
    print(f"OK VERSION: {DEPOIS}")

import ast  # noqa: E402

ast.parse(arq.read_text(encoding="utf-8"))
json.loads(pkg.read_text(encoding="utf-8"))
print("OK ast.parse + json.loads")
if not sanidade():
    print("INCOMPLETO")
    sys.exit(1)
