#!/usr/bin/env python3
"""Tira da tela o entulho de teste: câmeras que não funcionam e histórico de fluxo que não é mais câmera.

Decisão do dono (11/11/2026): pela tela o botão só DESATIVA (some da visão do cliente, histórico
fica). A exclusão de verdade é por aqui, com alvo explícito, sem tocar em nada que esteja no ar e
com relatório do que sai antes de sair.

O que sai (lista fechada — nada fora dela é tocado):

  câmeras de teste da bancada : cam-01, cam-02, cam-conves, cam-teste-ip, vivo-webcam
  envios de teste             : envio-clipe-do-dono-mp4, envio-clipe-do-youtube,
                                envio-youtube-link-de-p-gina, teste-latencia

O que fica:

  vps-webcam-bancada          (a que funciona) e as 4 câmeras demo do "PSV Exemplo (demo)"

Uso:
  python ground/limpar-cameras-teste.py                      # só mostra o que sairia
  python ground/limpar-cameras-teste.py --aplicar            # apaga de verdade, numa transação
  python ground/limpar-cameras-teste.py --db /opt/pipeline/app/db/pipeline.db --aplicar
  python ground/limpar-cameras-teste.py --orfaos --aplicar   # + histórico de fluxo que não é câmera
                                                             # (as "câmeras fantasma" da tela Produção)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# câmeras que saem (id da tabela `cameras`)
CAMERAS_ALVO = ["cam-01", "cam-02", "cam-conves", "cam-teste-ip", "vivo-webcam",
                "envio-clipe-do-dono-mp4", "envio-clipe-do-youtube",
                "envio-youtube-link-de-p-gina", "teste-latencia"]

# o que é da câmera e vai junto (coluna que aponta para o fluxo da câmera)
DEPENDENTES = [
    ("ingestoes", "fluxo_id"),
    ("ingestoes_amostras", "ingestao_id"),   # via ingestoes (tratado à parte)
    ("telemetria_minuto", "fluxo_id"),
    ("compressoes", "fluxo_id"),
    ("medicoes_qualidade", "fluxo_id"),
    ("latencia_medicoes", "fluxo_id"),
]
# tabelas que apontam para o id da câmera (não para o fluxo)
DEPENDENTES_POR_CAMERA = [
    ("analytics_eventos", "camera_id"),
    ("analytics_contagens", "camera_id"),
    ("analytics_agentes", "camera_id"),
    ("analytics_marcas", "camera_id"),
]


def apagar(c: sqlite3.Connection, tabela: str, coluna: str, valor, varios: bool = False) -> None:
    """Apaga tolerando banco antigo que ainda não tem a tabela (a VPS tem menos tabelas que a bancada).
    `varios=True` quando a condição é `... IN (?, ?, ...)` e o valor é a lista inteira."""
    try:
        c.execute(f"DELETE FROM {tabela} WHERE {coluna}=?", valor if varios else (valor,))
    except sqlite3.Error as e:
        print(f"      (aviso: {tabela} não saiu neste banco — {e})")


def apagar_in(c: sqlite3.Connection, tabela: str, coluna: str, valores) -> None:
    """Apaga por lista (`WHERE coluna IN (...)`), montando os marcadores no momento da chamada."""
    lista = list(valores)
    if not lista:
        return
    try:
        c.execute(f"DELETE FROM {tabela} WHERE {coluna} IN ({','.join('?' * len(lista))})", lista)
    except sqlite3.Error as e:
        print(f"      (aviso: {tabela} não saiu neste banco — {e})")


def contar(c: sqlite3.Connection, tabela: str, coluna: str, valor: str) -> int:
    try:
        return c.execute(f"SELECT count(*) FROM {tabela} WHERE {coluna}=?", (valor,)).fetchone()[0]
    except sqlite3.Error:
        return 0


def fluxos_no_ar(c: sqlite3.Connection) -> set[str]:
    return {r[0] for r in c.execute("SELECT DISTINCT fluxo_id FROM ingestoes WHERE estado='no_ar'")}


def main() -> int:
    p = argparse.ArgumentParser(description="Limpa as câmeras de teste e o histórico de fluxo órfão.")
    p.add_argument("--db", default=str(RAIZ / "db" / "pipeline.db"), help="banco a limpar")
    p.add_argument("--aplicar", action="store_true", help="apaga de verdade (sem isto, só mostra)")
    p.add_argument("--orfaos", action="store_true",
                   help="também apaga o histórico de fluxo que não é mais câmera (as linhas fantasma da Produção)")
    p.add_argument("--forcar", action="store_true", help="permite mexer em fluxo que está no ar")
    a = p.parse_args()

    if not os.path.exists(a.db):
        print(f"banco não encontrado: {a.db}")
        return 2

    c = sqlite3.connect(a.db)
    c.row_factory = sqlite3.Row
    no_ar = fluxos_no_ar(c)
    existentes = {r["id"]: r for r in c.execute("SELECT * FROM cameras")}

    print(f"banco: {a.db}")
    print(f"câmeras hoje: {len(existentes)} · fluxos no ar agora: {sorted(no_ar) or 'nenhum'}\n")

    alvos, pulados = [], []
    for cam in CAMERAS_ALVO:
        if cam not in existentes:
            pulados.append((cam, "não existe mais no banco"))
            continue
        if cam in no_ar and not a.forcar:
            pulados.append((cam, "está no ar agora — pare o envio antes de excluir"))
            continue
        alvos.append(cam)

    print("SAI:")
    plano = []
    for cam in alvos:
        linha = existentes[cam]
        print(f"  câmera {linha['rotulo']}  ({cam}, embarcação {linha['embarcacao_id']})")
        for tabela, coluna in DEPENDENTES:
            n = contar(c, tabela, coluna, cam)
            if n:
                print(f"      {tabela}: {n}")
        total_amostras = c.execute(
            "SELECT count(*) FROM ingestoes_amostras WHERE ingestao_id IN "
            "(SELECT id FROM ingestoes WHERE fluxo_id=?)", (cam,)).fetchone()[0]
        if total_amostras:
            print(f"      ingestoes_amostras: {total_amostras}")
        for tabela, coluna in DEPENDENTES_POR_CAMERA:
            n = contar(c, tabela, coluna, cam)
            if n:
                print(f"      {tabela}: {n}")
        plano.append(cam)

    print("\nFICA:")
    for cam, linha in existentes.items():
        if cam not in CAMERAS_ALVO:
            print(f"  {linha['rotulo']}  ({cam})")

    if pulados:
        print("\nNÃO MEXIDO:")
        for cam, motivo in pulados:
            print(f"  {cam}: {motivo}")

    orfaos: set[str] = set()
    if a.orfaos:
        todos = {r[0] for r in c.execute("SELECT DISTINCT fluxo_id FROM ingestoes")}
        todos |= {r[0] for r in c.execute("SELECT DISTINCT fluxo_id FROM telemetria_minuto")}
        orfaos = {f for f in todos if f and f not in existentes and f not in no_ar
                  and f not in CAMERAS_ALVO}
        if orfaos:
            print(f"\nHISTÓRICO ÓRFÃO (fluxo que não é câmera nenhuma) — sai com --orfaos:")
            orf_ing = c.execute("SELECT count(*) FROM ingestoes WHERE fluxo_id IN (%s)"
                                % ",".join("?" * len(orfaos)), tuple(orfaos)).fetchone()[0]
            orf_tel = c.execute("SELECT count(*) FROM telemetria_minuto WHERE fluxo_id IN (%s)"
                                % ",".join("?" * len(orfaos)), tuple(orfaos)).fetchone()[0]
            print(f"  {len(orfaos)} fluxo(s) · ingestoes: {orf_ing} · telemetria_minuto: {orf_tel}")

    if not a.aplicar:
        print("\n(nada foi apagado — rode com --aplicar para valer)")
        return 0

    with c:                                    # uma transação: ou sai tudo, ou não sai nada
        for cam in plano:
            ids = [r[0] for r in c.execute("SELECT id FROM ingestoes WHERE fluxo_id=?", (cam,))]
            if ids:
                c.execute("DELETE FROM ingestoes_amostras WHERE ingestao_id IN (%s)"
                          % ",".join("?" * len(ids)), tuple(ids))
            for tabela, coluna in DEPENDENTES:
                if tabela == "ingestoes_amostras":
                    continue
                apagar(c, tabela, coluna, cam)
            for tabela, coluna in DEPENDENTES_POR_CAMERA:
                apagar(c, tabela, coluna, cam)
            c.execute("DELETE FROM cameras WHERE id=?", (cam,))
        if orfaos:
            lista = list(orfaos)
            marca = ",".join("?" * len(lista))
            ids = [r[0] for r in c.execute(f"SELECT id FROM ingestoes WHERE fluxo_id IN ({marca})", lista)]
            if ids:
                apagar_in(c, "ingestoes_amostras", "ingestao_id", ids)
            apagar_in(c, "ingestoes", "fluxo_id", lista)
            apagar_in(c, "telemetria_minuto", "fluxo_id", lista)

    sobrou = [r["rotulo"] for r in c.execute("SELECT rotulo FROM cameras ORDER BY id")]
    print(f"\nAPAGADO: {len(plano)} câmera(s)" + (f" e {len(orfaos)} histórico(s) órfão(s)" if orfaos else ""))
    print(f"câmeras que ficaram ({len(sobrou)}): {', '.join(sobrou)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
