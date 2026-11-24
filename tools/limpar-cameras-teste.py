#!/usr/bin/env python3
"""Fase 10 (0.15.0): tira do lado terra as cameras de PROVA e a varredura DUPLICADA da `bancada`.

Dono, verbatim (24/11/2026): "voce deixou aquele monte de cameras de teste novamente".

O que sai (e so' isso):
  * as 4 de prova ................ `vivo-*` (criadas pelos testes de bancada);
  * a DUPLICATA `AFN-USB` ........ duas linhas para a MESMA entrada de video; fica a que tem transmissao
                                    (ou a primeira, se nenhuma tiver).

O que NAO se toca: as transmissoes e a auditoria (regra do dono: "o 'nada e apagado' refere-se a logs de
historico"). Backup CONSISTENTE do banco antes (API `sqlite3.backup`, nao copia de arquivo).
"""
import sqlite3
import sys

DB = "/opt/pipeline/app/db/pipeline.db"
BACKUP = "/opt/pipeline/app/db/pipeline.db.antes-limpeza"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

antes = [dict(r) for r in con.execute(
    "SELECT id, rotulo FROM cameras WHERE embarcacao_id='bancada' ORDER BY id")]
trans_antes = con.execute("SELECT COUNT(*) FROM transmissoes").fetchone()[0]

prova = [c["id"] for c in antes if c["id"].startswith("vivo-")]
afn = [c["id"] for c in antes if c["rotulo"] == "AFN-USB"]
duplicata = []
if len(afn) > 1:
    # fica a que tem transmissao (a que o dono ja' usou); sem transmissao, fica a primeira
    com_trafego = [cid for cid in afn
                   if con.execute("SELECT COUNT(*) FROM transmissoes WHERE camera_id=?", (cid,)).fetchone()[0]]
    manter = com_trafego[0] if com_trafego else sorted(afn)[0]
    duplicata = [cid for cid in afn if cid != manter]

sair = prova + duplicata
print("cameras da bancada ANTES :", len(antes))
for c in antes:
    marca = "  <-- SAI" if c["id"] in sair else ""
    print("   ", c["id"], "|", c["rotulo"], marca)
print("provas (vivo-*) a sair   :", prova)
print("duplicata AFN-USB a sair :", duplicata)

if "--aplicar" not in sys.argv:
    print("\n(ensaio: nada foi apagado; rode com --aplicar)")
    raise SystemExit(0)

bkp = sqlite3.connect(BACKUP)
con.backup(bkp)
bkp.close()
print("\nbackup consistente em", BACKUP)

for cid in sair:
    con.execute("DELETE FROM cameras WHERE id=?", (cid,))
con.commit()

depois = [dict(r) for r in con.execute(
    "SELECT id, rotulo FROM cameras WHERE embarcacao_id='bancada' ORDER BY id")]
trans_depois = con.execute("SELECT COUNT(*) FROM transmissoes").fetchone()[0]
print("\ncameras da bancada DEPOIS:", len(depois))
for c in depois:
    print("   ", c["id"], "|", c["rotulo"])
print("transmissoes (trilha de auditoria):", trans_antes, "->", trans_depois)
con.close()
