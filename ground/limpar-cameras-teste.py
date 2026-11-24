#!/usr/bin/env python3
"""Tira da tela o entulho de teste: câmeras que não funcionam e histórico de fluxo que não é mais câmera.

Decisão do dono (11/11/2026): pela tela o botão só DESATIVA (some da visão do cliente, histórico
fica). A exclusão de verdade é por aqui, com alvo explícito, sem tocar em nada que esteja no ar e
com relatório do que sai antes de sair.

O que sai (lista fechada — nada fora dela é tocado):

  bancada "Bancada de testes (propria)" (19): as 3 cam-* (cam-01, cam-02, cam-09), as 6
      cam-device-pnp-* (a varredura do PC de captura), as 8 vivo-* (nome dos fluxos das provas) e as
      2 vps-* (vps-sintetica, vps-webcam-bancada);
  psv-exemplo "PSV Exemplo (demo)" (6): cam-01-demo..cam-04-demo e os 2 envio-*-teste;
  cliente armador-e2e "Armador E2E (criado pela tela)" — sem usuário, sem embarcação, sem câmera.

Não sobra câmera de campanha em nenhuma das duas embarcações de teste (decisão do dono, 24/11/2026).

A TRILHA DE AUDITORIA fica: `transmissoes` (histórico das sessões) e `ordens_do_bordo` NÃO são tocados —
"nada é apagado" (dono, 16/11/2026). O que sai COM a câmera é o que é dela: a telemetria/ingestão do
fluxo (ingestoes, telemetria_minuto, compressoes, medicoes_qualidade, latencia_medicoes), a analítica
por câmera e o que faria a câmera reaparecer nas telas (desejo_camera, config_*, estado_bordo, hd_*).

Cuidado: o PC de captura RE-VARRE a cada 5 min e recadastra o dispositivo que estiver plugado
(`varredura_do_bordo.varrer`). Câmera do bordo REMOVIDA volta na próxima varredura — a lista fecha só
o que os TESTES criaram.

Uso:
  python ground/limpar-cameras-teste.py                      # só mostra o que sairia
  python ground/limpar-cameras-teste.py --aplicar            # apaga de verdade, numa transação
  python ground/limpar-cameras-teste.py --db /opt/pipeline/app/db/pipeline.db --aplicar
  python ground/limpar-cameras-teste.py --orfaos --aplicar   # + histórico de fluxo que não é câmera
                                                             # (as "câmeras fantasma" da tela Produção)
  python ground/limpar-cameras-teste.py --sem-cliente --aplicar   # + o cliente armador-e2e
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# câmeras que saem (id da tabela `cameras`) — lista fechada da campanha (24/11/2026)
CAMERAS_ALVO = [
    # --- bancada (Bancada de testes (propria)) — 19
    "cam-01", "cam-02", "cam-09",
    "cam-device-pnp-usb-vid-0001-pid-a001-mi-00-6-21c",     # AFN-USB
    "cam-device-pnp-usb-vid-0408-pid-403d-mi-00-7-210",     # ACER HD User Facing
    "cam-device-pnp-usb-vid-1bcf-pid-2c99-01-65e8773d",     # USB Video Device
    "cam-device-pnp-usb-vid-345f-pid-2131-mi-00-6-f69",     # USB2 Video
    "cam-device-pnp-usb-vid-534d-pid-2109-mi-00-6-253",     # USB Video (2)
    "cam-device-pnp-usb-vid-534d-pid-2109-mi-00-6-37f",     # USB Video (1)
    "vivo-cam-01", "vivo-cam-02", "vivo-cam01-1811", "vivo-cam02-1811",
    "vivo-cam1-11-18", "vivo-cam2-11-18", "vivo-usb-video", "vivo-webcam-da-bancada-prova",
    "vps-sintetica", "vps-webcam-bancada",
    # --- psv-exemplo (PSV Exemplo (demo)) — 6
    "cam-01-demo", "cam-02-demo", "cam-03-analitico", "cam-04-demo",
    "envio-envio-pela-tela-teste", "envio-envio-por-link-teste",
]

# cliente de teste que sai junto (id da tabela `clientes`); só com --sem-cliente
CLIENTE_ALVO = "armador-e2e"

# o que é da câmera e vai junto (coluna que aponta para o fluxo da câmera)
DEPENDENTES = [
    ("ingestoes", "fluxo_id"),
    ("ingestoes_amostras", "ingestao_id"),   # via ingestoes (tratado à parte)
    ("telemetria_minuto", "fluxo_id"),
    ("compressoes", "fluxo_id"),
    ("medicoes_qualidade", "fluxo_id"),
    ("latencia_medicoes", "fluxo_id"),
]
# tabelas que apontam para o id da câmera (não para o fluxo). As de CONFIGURACAO/ESTADO saem com a
# câmera (senão ela reaparece nas telas); os HISTORICOS (transmissoes, ordens_do_bordo, ingestoes,
# telemetria_minuto, gravacoes) ficam — a trilha de auditoria não é apagada (decisão do dono).
DEPENDENTES_POR_CAMERA = [
    ("analytics_eventos", "camera_id"),
    ("analytics_contagens", "camera_id"),
    ("analytics_agentes", "camera_id"),
    ("analytics_marcas", "camera_id"),
    ("desejo_camera", "camera_id"),
    ("config_bordo", "camera_id"),
    ("config_aplicada_bordo", "camera_id"),
    ("config_local", "camera_id"),
    ("estado_bordo", "camera_id"),
    ("hd_catalogo", "camera_id"),
    ("hd_pedidos", "camera_id"),
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
    p.add_argument("--sem-cliente", action="store_true",
                   help=f"também apaga o cliente de teste {CLIENTE_ALVO} (sem usuário/embarcação/câmera)")
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

    cliente_sai = ""
    if a.sem_cliente:
        cli = c.execute("SELECT id, nome FROM clientes WHERE id=?", (CLIENTE_ALVO,)).fetchone()
        if cli:
            embs = [r[0] for r in c.execute("SELECT id FROM embarcacoes WHERE cliente_id=?", (CLIENTE_ALVO,))]
            usus = [r[0] for r in c.execute("SELECT id FROM usuarios WHERE cliente_id=?", (CLIENTE_ALVO,))]
            if embs or usus:
                print(f"\n  (o cliente {CLIENTE_ALVO} tem embarcação/usuário — NÃO sai: {embs} {usus})")
            else:
                cliente_sai = CLIENTE_ALVO
                print(f"\nCLIENTE QUE SAI ({CLIENTE_ALVO}): {cli['nome']} — sem usuário, sem embarcação")

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
        if cliente_sai:
            c.execute("DELETE FROM clientes WHERE id=?", (cliente_sai,))

    sobrou = [r["rotulo"] for r in c.execute("SELECT rotulo FROM cameras ORDER BY id")]
    print(f"\nAPAGADO: {len(plano)} câmera(s)" + (f" e {len(orfaos)} histórico(s) órfão(s)" if orfaos else ""))
    print(f"câmeras que ficaram ({len(sobrou)}): {', '.join(sobrou)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
