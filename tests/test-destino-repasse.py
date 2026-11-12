#!/usr/bin/env python3
"""Regressão: o "destino do repasse" (PC de captura -> lado terra) está ligado de ponta a ponta.

O caminho é longo e fácil de quebrar em silêncio: `config.json` do app -> `servidor.js` (ambiente dos
processos filhos) -> `mediamtx.yml` (`runOnAvailable` chama `ground/repasse.py`) -> `repasse.py`
(pula tudo quando não há destino). Se qualquer elo desaparecer, o PC de captura para de subir o vídeo
sem avisar ninguém. Este teste lê cada elo e confere.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas: list[str] = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("ok   " if condicao else "FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


def ler(p: str) -> str:
    return (RAIZ / p).read_text(encoding="utf-8", errors="replace")


def main() -> int:
    # 1) o app declara o campo e ele chega ao lado terra
    cfg = json.loads(ler("desktop/config.json"))
    checar("desktop/config.json tem 'destinoSrt'", "destinoSrt" in cfg, f"chaves: {sorted(cfg)}")

    # 2) o app repassa o campo para o ambiente dos filhos (é o que o mediamtx lê)
    servidor = ler("desktop/servidor.js")
    checar("servidor.js monta o ambiente com LECSOR_DESTINO_SRT",
           "LECSOR_DESTINO_SRT" in servidor and "function amb(" in servidor and "delete saida.LECSOR_DESTINO_SRT" in servidor)
    checar("servidor.js exporta amb() para poder ser verificado",
           re.search(r"module\.exports\s*=\s*\{[^}]*amb", servidor) is not None)
    checar("servidor.js escolhe o python do .venv quando existe",
           ".venv" in servidor and "pythonDe" in servidor)
    checar("main.js lê 'destinoSrt' do config",
           "destinoSrt" in ler("desktop/main.js"))

    # 3) o mediamtx chama o repasse (chave nova: runOnReady está descontinuado no v1.21.3)
    yml = ler("ground/mediamtx.yml")
    checar("mediamtx.yml chama ground/repasse.py em runOnAvailable",
           "runOnAvailable: python ground/repasse.py $MTX_PATH" in yml and "runOnAvailableRestart: yes" in yml)
    checar("mediamtx.yml não usa a chave descontinuada runOnReady", "runOnReady:" not in yml)

    # 4) o repasse copia (não reencoda) e não sobe nada sem destino
    repasse = ler("ground/repasse.py")
    checar("repasse.py repassa com -c copy", '"-c", "copy"' in repasse)
    checar("repasse.py não sobe nada sem destino",
           'if not destino:' in repasse and "return 0" in repasse)

    # 5) a tela mostra o destino, e a API só entrega para a operação
    checar("admin.js mostra o destino do repasse", "env-destino" in ler("admin/admin.js"))
    api = ler("ground/api.py")
    msg = "so operacao e administrador veem o destino do repasse"
    trecho = api[max(0, api.find(msg) - 600):api.find(msg) + 200] if msg in api else ""
    checar("a rota do destino dá 403 para quem não é operação",
           msg in api and "403" in trecho and "self._pode_operar(u)" in trecho,
           "achar a rota sem o gate de papel deixaria o cliente receber o endereço interno")
    checar("a rota do destino NÃO usa a exceção de chamada local",
           "self._local()" not in trecho, "cliente logado na mesma máquina também não pode receber o endereço")

    # 6) versão do app é semver (o instalador é nomeado por ela)
    versao = json.loads(ler("desktop/package.json"))["version"]
    checar("versão do app é semver", re.fullmatch(r"\d+\.\d+\.\d+", versao) is not None, versao)
    return 1 if falhas else 0


if __name__ == "__main__":
    codigo = main()
    print("\n" + ("DESTINO DO REPASSE OK" if codigo == 0 else f"COM FALHA: {', '.join(falhas)}"))
    sys.exit(codigo)
