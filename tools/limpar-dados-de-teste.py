#!/usr/bin/env python3
"""APAGA OS DADOS DE TESTE DO LADO TERRA, MANTENDO A ESTRUTURA E OS 4 USUARIOS (dono, 26/11/2026).

O dono olhou a tela "Gravacoes" e perguntou: "nao entendi esse bloco, isso foi teste?" — era mesmo: o
bloco `teste-radar-lecsor` no HD do barco (dado semeado) e um pedido de trecho tracado
(`8b8e2c59ea7a70b5`) que o bordo nunca ia responder. Decisao P4: apagar AGORA o pedido preso e os dados
de teste da VPS.

O que este roteiro APAGA (somente dado de teste, reconhecivel pelo prefixo `teste-`):

  * `hd_pedidos`   — os pedidos de trecho das cameras de teste (inclui o pedido preso);
  * `hd_catalogo`  — o catalogo de HD publicado pelas cameras de teste (o bloco que o dono viu);
  * `gravacoes`    — os trechos "que ja' chegaram em terra" das transmissoes de teste;
  * `transmissoes` — as transmissoes de teste (historico);
  * o arquivo de mentira da gravacao de teste, se existir no disco.

O que este roteiro NAO toca (e' o que o dono mandou MANTER):

  * empresas, embarcacoes e cameras (a ESTRUTURA — e' ela que da' o escopo dos 4 usuarios);
  * `usuarios` e `usuario_embarcacoes` — os 4 usuarios de teste dos 4 tipos de cliente;
  * qualquer coisa que nao tenha o prefixo `teste-`.

NADA e' apagado sem querer: por padrao o roteiro so' MOSTRA o que faria (`--seco`). Com `--confirmar`
ele apaga e grava UMA linha na auditoria (`dados_de_teste_apagados`) — a trilha de quem apagou o que.

    python3 tools/limpar-dados-de-teste.py --banco db/pipeline.db            # so' mostra (seco)
    python3 tools/limpar-dados-de-teste.py --banco db/pipeline.db --confirmar
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys

# so' o que comeca com TESTE entra na conta (nunca um id de verdade)
PREFIXO = "teste-"
PEDIDO_PRESO = "8b8e2c59ea7a70b5"        # o pedido que o dono viu como "chegando…" travado


def abrir(banco: pathlib.Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(banco), timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def contar(con, sql, args=()) -> int:
    try:
        return con.execute(sql, args).fetchone()[0]
    except sqlite3.OperationalError:
        return 0          # tabela que ainda nao existe neste banco


def alvos(con) -> dict:
    """Tudo que e' dado de TESTE — medido, nao suposto (as contagens saem do proprio banco)."""
    return {
        "hd_pedidos": contar(con, "SELECT count(*) FROM hd_pedidos WHERE id LIKE ? OR camera_id LIKE ?",
                             (PREFIXO + "%", PREFIXO + "%")),
        "hd_pedidos_presos": contar(con, "SELECT count(*) FROM hd_pedidos WHERE id=?", (PEDIDO_PRESO,)),
        "hd_catalogo": contar(con, "SELECT count(*) FROM hd_catalogo WHERE camera_id LIKE ?", (PREFIXO + "%",)),
        "gravacoes": contar(con, "SELECT count(*) FROM gravacoes WHERE transmissao_id LIKE ? OR embarcacao_id LIKE ?",
                            (PREFIXO + "%", PREFIXO + "%")),
        "transmissoes": contar(con, "SELECT count(*) FROM transmissoes WHERE id LIKE ?", (PREFIXO + "%",)),
    }


def manter(con) -> dict:
    """O que tem de FICAR: a estrutura e os 4 usuarios (a prova de que o roteiro nao passou do ponto)."""
    return {
        "clientes": contar(con, "SELECT count(*) FROM clientes"),
        "embarcacoes": contar(con, "SELECT count(*) FROM embarcacoes"),
        "cameras": contar(con, "SELECT count(*) FROM cameras"),
        "usuarios": contar(con, "SELECT count(*) FROM usuarios"),
        "usuarios_de_teste": contar(con, "SELECT count(*) FROM usuarios WHERE email LIKE '%@demo.test'"),
        "vinculos": contar(con, "SELECT count(*) FROM usuario_embarcacoes"),
    }


def montar(con, alvo: dict) -> list[tuple[str, str, tuple]]:
    return [
        ("hd_pedidos", "DELETE FROM hd_pedidos WHERE id LIKE ? OR camera_id LIKE ?",
         (PREFIXO + "%", PREFIXO + "%")),
        ("hd_catalogo", "DELETE FROM hd_catalogo WHERE camera_id LIKE ?", (PREFIXO + "%",)),
        ("gravacoes", "DELETE FROM gravacoes WHERE transmissao_id LIKE ? OR embarcacao_id LIKE ?",
         (PREFIXO + "%", PREFIXO + "%")),
        ("transmissoes", "DELETE FROM transmissoes WHERE id LIKE ?", (PREFIXO + "%",)),
    ]


def arquivos_de_teste(diretorio: pathlib.Path | None) -> list[pathlib.Path]:
    if not diretorio or not diretorio.is_dir():
        return []
    return sorted(p for p in diretorio.rglob("*") if p.is_file() and p.name.startswith(PREFIXO))


def gravar_auditoria(con, feito: dict, usuario: str) -> None:
    """UMA linha na trilha (quem apagou, quando, o que) — as colunas sao as de verdade
    (`auditoria_acesso(usuario_id,email,acao,alvo,em,ip)`, db/schema-fase4.sql)."""
    agora = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    try:
        con.execute("""INSERT INTO auditoria_acesso (usuario_id,email,acao,alvo,em,ip)
                       VALUES (?,?,?,?,?,?)""",
                    (None, usuario, "dados_de_teste_apagados",
                     "lado terra: " + json.dumps(feito, ensure_ascii=False), agora, "local"))
    except sqlite3.OperationalError:
        # a tabela de auditoria nem sempre existe (bancada) — a limpeza nao pode falhar por isso
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Apaga os dados de TESTE do lado terra (mantendo a estrutura e os usuarios).")
    ap.add_argument("--banco", required=True, help="caminho do pipeline.db")
    ap.add_argument("--gravacoes", default="", help="pasta das gravacoes (para apagar o mp4 de mentira)")
    ap.add_argument("--usuario", default="alexandre@lecsor.com.br", help="quem esta' limpando (vai para a auditoria)")
    ap.add_argument("--confirmar", action="store_true", help="apaga de verdade (sem isto, so' mostra)")
    args = ap.parse_args()

    banco = pathlib.Path(args.banco)
    if not banco.is_file():
        print("nao achei o banco:", banco)
        return 2
    diretorio = pathlib.Path(args.gravacoes) if args.gravacoes else None

    con = abrir(banco)
    try:
        antes_alvo, antes_manter = alvos(con), manter(con)
        print("== O QUE E' DADO DE TESTE (prefixo %r) ==" % PREFIXO)
        for k, v in antes_alvo.items():
            print("   %-20s %d" % (k, v))
        if antes_alvo["hd_pedidos_presos"]:
            preso = con.execute("""SELECT id,camera_id,usuario_email,estado,criado_em FROM hd_pedidos
                                   WHERE id=?""", (PEDIDO_PRESO,)).fetchone()
            print("   -> pedido PRESO: %s | %s | %s | %s | %s" % tuple(preso))

        arquivos = arquivos_de_teste(diretorio)
        print("   %-20s %d   %s" % ("arquivos no disco", len(arquivos),
                                    ", ".join(p.name for p in arquivos[:6])))

        if not args.confirmar:
            print()
            print("== O QUE VAI FICAR (nao e' tocado) ==")
            for k, v in antes_manter.items():
                print("   %-20s %d" % (k, v))
            print()
            print("modo SECO: nada foi apagado. Rode de novo com --confirmar para apagar.")
            return 0

        feito: dict[str, int] = {}
        con.execute("BEGIN IMMEDIATE")
        for nome, sql, par in montar(con, antes_alvo):
            cur = con.execute(sql, par)
            feito[nome] = cur.rowcount
        for p in arquivos:
            try:
                p.unlink()
                feito["arquivos"] = feito.get("arquivos", 0) + 1
            except OSError as e:
                print("   aviso: nao consegui apagar %s: %s" % (p, e))
        gravar_auditoria(con, feito, args.usuario)
        con.commit()

        depois_alvo, depois_manter = alvos(con), manter(con)
        print()
        print("== APAGADO ==")
        for k in antes_alvo:
            print("   %-20s %d -> %d" % (k, antes_alvo[k], depois_alvo[k]))
        print("   %-20s %d" % ("arquivos no disco", feito.get("arquivos", 0)))
        print()
        print("== O QUE FICOU (a estrutura e os usuarios de teste) ==")
        for k in antes_manter:
            print("   %-20s %d -> %d" % (k, antes_manter[k], depois_manter[k]))
        print()
        print("auditoria: 1 linha 'dados_de_teste_apagados' por %s" % args.usuario)
        sobra = sum(depois_alvo[k] for k in ("hd_pedidos", "hd_catalogo", "gravacoes", "transmissoes"))
        print("RESULTADO:", "nada de teste sobrou" if sobra == 0 else "AINDA SOBRARAM %d linha(s) de teste" % sobra)
        return 0 if sobra == 0 else 1
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
