#!/usr/bin/env python3
"""Regressao de 10/11/2026: a tela Producao/Tempo real do admin ficava VAZIA e demorada.

Causa: `tempo_real()` somava a entrada dos fluxos que estao no ar sem conversao — um fluxo de fonte
crua (webcam/sintetica) nao tem entrada medida (`bitrate_entrada_kbps` NULL) e o total fazia
`float += None` → TypeError. Como o `/api/producao` chama `tempo_real()`, a tela inteira estourava
(parecia "sem informacoes") e ainda gastava segundos antes de falhar.

Este teste so LE o banco: monta os numeros da Producao e do Tempo real e exige que voltem sem erro.
"""
import os
import sys

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))
os.chdir(RAIZ)
import producao as P  # noqa: E402


def main() -> int:
    falhas = []
    try:
        vivo = P.tempo_real(validade_s=0)
    except Exception as e:
        falhas.append(f"tempo_real levantou {type(e).__name__}: {e}")
        vivo = {}
    try:
        resumo = P.resumo_producao(dias=30)
    except Exception as e:
        falhas.append(f"resumo_producao levantou {type(e).__name__}: {e}")
        resumo = {}

    if vivo:
        t = vivo.get("total") or {}
        print(f"tempo_real: {len(vivo.get('fluxos', []))} fluxo(s) | total entrada "
              f"{t.get('entrada_mbps')} Mbps · saida {t.get('saida_mbps')} Mbps · "
              f"economia {t.get('banda_economizada_mbps')} Mbps")
        for f in vivo.get("fluxos", []):
            print(f"  - {f['fluxo_id']}: entrada={f.get('entrada_mbps')} "
                  f"({f.get('entrada_fonte')}) saida={f.get('taxa_agora_mbps')} "
                  f"compressao={f.get('compressao_agora_pct')}")
            if f.get("entrada_mbps") is None:
                falhas.append(f"fluxo {f['fluxo_id']} no ar sem entrada: o total vai estourar de novo")
    if resumo:
        print(f"resumo_producao: {len(resumo.get('cards', []))} card(s) | total {resumo.get('total')}")

    if falhas:
        print("FALHOU:")
        for f in falhas:
            print("  -", f)
        return 1
    print("OK: Producao e Tempo real montam os numeros sem estourar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
