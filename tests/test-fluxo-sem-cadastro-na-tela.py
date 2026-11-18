#!/usr/bin/env python3
"""Fluxo no ar SEM cadastro aparece no "Tempo real" e na "Produção" (e não derruba a tela).

Por que este teste existe (dono, 18/11/2026): o vídeo das câmeras dele chegava ao lado terra, mas o
cadastro não — e as telas ficavam VAZIAS, como se nada estivesse no ar. As telas liam só as câmeras
cadastradas; o fluxo vivo sem cadastro não existia para elas.

Aqui o mediamtx é substituído por uma lista fixa (`_caminhos_vivos`), então o teste roda sem rede e sem
mediamtx de verdade, e prova:

  1. fluxo vivo sem cadastro ENTRA no "Tempo real" marcado (`sem_cadastro`), com leitores/tracks;
  2. os totais não quebram (o fluxo sem cadastro não tem medida — a conta é com `0.0`, não com `None`);
  3. a "Produção" gera card para ele (foi o que faltava: `producao: []` com 3 fluxos no ar);
  4. fluxo que TEM cadastro não é duplicado.

Uso: python tests/test-fluxo-sem-cadastro-na-tela.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

TEMP = Path(tempfile.mkdtemp(prefix="sem-cadastro-"))
os.environ["LECSOR_BANCO"] = str(TEMP / "pipeline.db")
os.environ.pop("LECSOR_LADO_TERRA_API", None)

import producao  # noqa: E402  (depois do LECSOR_BANCO: o caminho do banco é lido em tempo de chamada)

falhas: list = []


def checar(condicao: bool, texto: str) -> None:
    print(("  ok    — " if condicao else "  FALHA — ") + texto)
    if not condicao:
        falhas.append(texto)


def preparar_banco() -> None:
    import api                                     # o esquema completo é do servidor: um só lugar
    api.inicializar(False)                        # sem semear demo: banco limpo, só o que o teste cria
    c = sqlite3.connect(os.environ["LECSOR_BANCO"])
    try:
        c.execute("INSERT OR REPLACE INTO clientes (id, nome) VALUES ('cli-1', 'Cliente do teste')")
        c.execute("INSERT OR REPLACE INTO embarcacoes (id, cliente_id, nome) "
                  "VALUES ('bancada-demo', 'cli-1', 'Bancada')")
        c.execute("INSERT OR REPLACE INTO cameras (id, embarcacao_id, rotulo, fluxo_id, local, ativo) "
                  "VALUES ('cam-com-cadastro', 'bancada-demo', 'Câmera cadastrada', "
                  "'cam-com-cadastro', '', 1)")
        c.commit()
    finally:
        c.close()


def caminhos_falsos() -> dict:
    """O que o mediamtx diria: um fluxo com cadastro e um sem (o caso do dono)."""
    return {
        "cam-com-cadastro": {"name": "cam-com-cadastro", "ready": True, "tracks": ["video"],
                             "readers": [{"type": "rtspSession"}]},
        "comp-1": {"name": "comp-1", "ready": True, "tracks": ["video"], "readers": []},
    }


def principal() -> int:
    preparar_banco()
    producao._caminhos_vivos = caminhos_falsos      # sem mediamtx: o teste não depende de rede

    print("fluxo sem cadastro — o vídeo que chega e não tem câmera cadastrada não some da tela")

    orfaos = producao.fluxos_sem_cadastro()
    por_fluxo = {o["fluxo_id"]: o for o in orfaos}
    checar(set(por_fluxo) == {"comp-1", "cam-com-cadastro"},
           "todo fluxo vivo sem linha de ingestão entra na lista (com cadastro e sem)")
    checar(por_fluxo.get("comp-1", {}).get("sem_cadastro") is True,
           "sem cadastro no banco, ele vem marcado (a tela avisa em vez de fingir que é câmera normal)")
    checar(por_fluxo.get("cam-com-cadastro", {}).get("sem_cadastro") is False,
           "com cadastro, ele vem como câmera normal (nada de 'sem cadastro' à toa)")
    checar(por_fluxo.get("cam-com-cadastro", {}).get("camera_rotulo") == "Câmera cadastrada",
           "e aparece com o RÓTULO da câmera, não com o nome cru do fluxo")

    vivo = producao.tempo_real()
    por_id = {f["fluxo_id"]: f for f in vivo["fluxos"]}
    checar("comp-1" in por_id, "o fluxo sem cadastro aparece no Tempo real")
    checar((por_id.get("comp-1") or {}).get("estado") == "enviando",
           "e aparece como enviando (tem vídeo chegando agora)")
    checar("sem cadastro" in str((por_id.get("comp-1") or {}).get("camera_rotulo", "")),
           "com o rótulo dizendo que falta o cadastro")
    checar(vivo["total"].get("fluxos", 0) >= 2,
           "os totais somam os dois sem estourar (fluxo sem medida conta 0, não None)")
    checar(len([f for f in vivo["fluxos"] if f["fluxo_id"] == "cam-com-cadastro"]) == 1,
           "o fluxo que TEM cadastro aparece uma vez só (não é duplicado)")

    try:
        d = producao.resumo_producao(dias=30)
        cards = d.get("cards", [])
        nomes = [str(c.get("camera", "")) for c in cards]
        checar(any("sem cadastro" in n for n in nomes),
               "a Produção gera card para o fluxo sem cadastro (antes vinha vazia)")
        orfa = [c for c in cards if c.get("fluxo_id") == "comp-1"]
        checar(bool(orfa) and orfa[0].get("sem_cadastro") is True,
               "o card vem MARCADO como sem cadastro (a tela avisa; não parece câmera normal)")
    except Exception as e:  # noqa: BLE001
        checar(False, f"a Produção não quebra com fluxo sem cadastro (estourou: {type(e).__name__}: {e})")

    if falhas:
        print(f"\nFLUXO_SEM_CADASTRO_FALHOU — {len(falhas)} checagem(ns) vermelha(s)")
        return 1
    print("\nFLUXO_SEM_CADASTRO_OK — o que está no ar aparece nas telas, com ou sem cadastro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
