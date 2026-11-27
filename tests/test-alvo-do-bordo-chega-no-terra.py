"""O ALVO (kbps) que o BORDO aplica viaja no estado real e vira `cameras.alvo` no LADO TERRA.

Defeito do dono, 3ª vez (27/11/2026): *"em admin>empresas e configuracao, quando altero a qualidade e
aplico, ela nao persiste, retorna a anterior"*. Medido no banco de producao: a publicacao grava
(`config_bordo` alvo_kbps v7/500) e o bordo aplica (`config_aplicada_bordo` v7/500), mas
`cameras.alvo` do lado TERRA fica `''` nas 9 cameras — porque quem escreve esse campo e' o
`aplicar_config_local()` do PC de captura e o unico caminho do bordo para o terra e' o anuncio, que
NAO levava o alvo. Sem ele a tela cai no 1o item do menu ("3000 kbps (padrao do produto)").

    python tests/test-alvo-do-bordo-chega-no-terra.py

Provas:
  1) o estado real do bordo, com `alvo`, GRAVA `cameras.alvo` no lado terra;
  2) um estado sem `alvo` (bordo antigo) NAO apaga o que ja' esta' gravado;
  3) o que a tela le' (a arvore) mostra o alvo publicado por ULTIMO — o mesmo que o menu exibe.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ground"))
falhas: list[str] = []


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-alvo-terra-"))
    os.environ["LECSOR_BANCO"] = str(tmp / "pipeline.db")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    con = sqlite3.connect(os.environ["LECSOR_BANCO"])
    esquemas = [RAIZ / "db" / "schema.sql"] + sorted(
        p for p in (RAIZ / "db").glob("schema*.sql") if p.name != "schema.sql")
    for esquema in esquemas:
        con.executescript(esquema.read_text(encoding="utf-8"))
    con.execute("INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)"
                " VALUES ('bancada','lecsor','Bancada','','em operacao')")
    con.execute("INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)"
                " VALUES ('cam-radar','bancada','Radar de oleo','vivo-radar','',1,'')")
    con.commit()
    con.close()

    import api  # noqa: PLC0415

    # 1) o bordo conta o estado real JUNTO com o alvo que ele tem gravado
    r = api.guardar_estado_real("bancada", [{"camera_id": "cam-radar", "estado": "parado",
                                             "motivo": "parada (ninguem assistindo)",
                                             "alvo": "500k"}], de=None)
    exigir(r.get("ok") is True, "o lado terra aceita o estado real do bordo")
    c = sqlite3.connect(os.environ["LECSOR_BANCO"])
    guardado = c.execute("SELECT alvo FROM cameras WHERE id='cam-radar'").fetchone()
    c.close()
    exigir(guardado and str(guardado[0]) == "500k",
           f"`cameras.alvo` do lado TERRA passa a valer o alvo do bordo: {guardado[0] if guardado else None!r}")

    # 2) bordo antigo (sem `alvo`) nao apaga o que ja' esta'
    api.guardar_estado_real("bancada", [{"camera_id": "cam-radar", "estado": "parado", "alvo": ""}], de=None)
    c = sqlite3.connect(os.environ["LECSOR_BANCO"])
    depois = c.execute("SELECT alvo FROM cameras WHERE id='cam-radar'").fetchone()
    c.close()
    exigir(depois and str(depois[0]) == "500k",
           f"estado SEM alvo nao apaga o que ja' esta' gravado: {depois[0] if depois else None!r}")

    # 3) a PUBLICACAO continua sendo a fonte da verdade para aquela camera (e' o que a tela le')
    r = api.publicar_config("bancada", "cam-radar", "alvo_kbps", "3000")
    exigir(r.get("ok") is True and str(r.get("valor")) == "3000",
           f"publicar `alvo_kbps` grava o valor novo do bordo: {r.get('motivo') or r.get('erro') or r.get('valor')}")
    c = sqlite3.connect(os.environ["LECSOR_BANCO"])
    linha = c.execute("SELECT valor,versao FROM config_bordo WHERE chave='alvo_kbps'"
                      " AND camera_id='cam-radar'").fetchone()
    c.close()
    exigir(linha and linha[0] == "3000" and int(linha[1]) >= 1,
           f"e a config publicada tem o valor + versao que o bordo usa: {linha}")

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} exigencia(s)")
        return 1
    print("TUDO OK — o alvo do bordo chega no lado terra e a tela tem de onde ler")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
