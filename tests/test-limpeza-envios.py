#!/usr/bin/env python3
"""Regressao do defeito de 09/11/2026: a API morria no boot com 'database is locked'.

Causa: `limpar_vivos_mortos()` percorria o SELECT e, com o cursor ABERTO na mesma conexao,
fazia UPDATE — o SQLite tentava subir de leitura para escrita e devolvia 'database is locked'
na hora (o busy_timeout nao vale para essa subida). Como isso roda no inicio do api.py, o
servico saia, nada escutava na porta e os aplicativos abriam em branco, sem tela de autenticacao.

Este teste garante que a limpeza roda ate o fim, marcando a linha de teste como 'erro'.
"""
import os
import sys

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))
os.chdir(RAIZ)
import ingestao as ing  # noqa: E402


def main() -> int:
    with ing.conexao() as c:
        c.execute("DELETE FROM ingestoes WHERE id=999999")
        c.execute("""INSERT INTO ingestoes (id, fluxo_id, rotulo, fonte, tipo, estado, pid, criado_em, atualizado_em)
                     VALUES (999999, 'teste-limpeza', 'teste', 'arquivo', 'arquivo', 'no_ar', 999999, ?, ?)""",
                  (ing.agora(), ing.agora()))
    n = ing.limpar_vivos_mortos()          # NAO pode levantar
    with ing.conexao() as c:
        r = c.execute("SELECT estado, erro FROM ingestoes WHERE id=999999").fetchone()
        estado = r["estado"] if r else None
        c.execute("DELETE FROM ingestoes WHERE id=999999")
    print(f"limpar_vivos_mortos() voltou n={n}; a linha de teste ficou estado={estado}")
    ok = n >= 1 and estado == "erro"
    print("OK: limpeza rodou sem travar o banco" if ok else "FALHOU: limpeza nao marcou a linha de teste")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
