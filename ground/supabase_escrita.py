#!/usr/bin/env python3
"""Espelha o CADASTRO para o Supabase (a base de verdade), com o SQLite como banco de operacao.

O dono (19/11/2026) abriu a tabela `cameras` do Supabase e viu **1** linha enquanto a VPS tinha **16**:
o cadastro so' era gravado no SQLite local. Aqui o LADO TERRA (o unico que tem a chave de servico) faz o
upsert do cadastro em `public.cameras`. O endereco da camera (`ip`/`porta`) **nunca** sobe — a migracao
`20261111130000_cameras_sem_endereco_para_cliente.sql` tirou essas colunas do papel `cliente`, e aqui elas
nem sao enviadas.

Por que o lado terra e nao o bordo: a chave de servico fica **so' no servidor em terra** (regra do dono:
nada de segredo no instalador nem na maquina de captura). O bordo continua publicando o cadastro para o lado
terra (`POST /api/cameras/anuncio`), e o lado terra e' quem espelha na nuvem.

Variaveis de ambiente (nenhum segredo entra em log ou em resposta):
    LECSOR_SUPABASE_URL          https://<ref>.supabase.co
    LECSOR_SUPABASE_SERVICE_KEY  chave de servico (so' no servidor em terra)
    LECSOR_SUPABASE_CLIENTE_ID   (opcional) uuid do cliente usado ao criar uma embarcacao nova no Supabase
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferramentas import caminho_banco  # noqa: E402

TEMPO_PADRAO = 8.0


def _url() -> str:
    return (os.environ.get("LECSOR_SUPABASE_URL") or "").strip().rstrip("/")


def _servico() -> str:
    return (os.environ.get("LECSOR_SUPABASE_SERVICE_KEY") or "").strip()


def configurado() -> bool:
    """Espelhar existe quando a URL e a chave de servico estao no ambiente (so' no lado terra)."""
    return bool(_url() and _servico())


def _agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _pedido(caminho: str, corpo: dict | None = None, metodo: str = "POST",
            tempo: float = TEMPO_PADRAO) -> tuple[int, object]:
    """Chama a REST do Supabase. Devolve (status, dados) e nunca levanta: quem chama decide o que fazer."""
    base, chave = _url(), _servico()
    if not base or not chave:
        return 0, {"erro": "sem LECSOR_SUPABASE_URL / LECSOR_SUPABASE_SERVICE_KEY"}
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    cabecalhos = {"apikey": chave, "Authorization": f"Bearer {chave}", "Content-Type": "application/json"}
    if corpo is not None:
        # upsert por chave: `Prefer` resolve o conflito em vez de estourar "duplicate key"
        cabecalhos["Prefer"] = "resolution=merge-duplicates,return=representation"
    pedido = urllib.request.Request(base + caminho, data=dados, headers=cabecalhos, method=metodo)
    try:
        with urllib.request.urlopen(pedido, timeout=tempo) as f:
            bruto = f.read()
            return f.status, (json.loads(bruto) if bruto else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001  (rede fora, DNS, timeout)
        return 0, {"erro": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------ equivalencia slug <-> uuid
def _conexao() -> sqlite3.Connection:
    c = sqlite3.connect(caminho_banco(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _tabela_de_equivalencia(c: sqlite3.Connection) -> None:
    """O Supabase usa uuid em `embarcacoes`; aqui a embarcacao e' texto (`'bancada'`). Sem esta ponte o
    upsert de camera falharia por chave estrangeira (a camera aponta para a embarcacao)."""
    c.execute("""CREATE TABLE IF NOT EXISTS embarcacoes_supabase (
                   slug           TEXT PRIMARY KEY,
                   uuid           TEXT NOT NULL,
                   nome           TEXT DEFAULT '',
                   atualizado_em  TEXT NOT NULL)""")


def nome_da_embarcacao(slug: str) -> str:
    """O nome que ESTA embarcacao tem aqui (e' por ele que achamos a linha ja' existente no Supabase).

    Sem isso, quem chama `espelhar()` sem passar o nome criava uma embarcacao NOVA na nuvem com o nome
    do slug (`bancada`), duplicando "Bancada de testes (propria)" — medido em 19/11/2026 na VPS.
    """
    slug = (slug or "").strip()
    if not slug:
        return ""
    try:
        with _conexao() as c:
            linha = c.execute("SELECT nome FROM embarcacoes WHERE id=?", (slug,)).fetchone()
        return str(linha["nome"]) if linha else ""
    except Exception:  # noqa: BLE001
        return ""


def uuid_da_embarcacao(slug: str) -> str:
    """A equivalencia ja' conhecida para esta embarcacao local ('' se ainda nao existe)."""
    slug = (slug or "").strip()
    if not slug:
        return ""
    with _conexao() as c:
        _tabela_de_equivalencia(c)
        linha = c.execute("SELECT uuid FROM embarcacoes_supabase WHERE slug=?", (slug,)).fetchone()
    return str(linha["uuid"]) if linha else ""


def guardar_equivalencia(slug: str, uuid: str, nome: str = "") -> None:
    with _conexao() as c:
        _tabela_de_equivalencia(c)
        c.execute("""INSERT INTO embarcacoes_supabase (slug,uuid,nome,atualizado_em) VALUES (?,?,?,?)
                     ON CONFLICT(slug) DO UPDATE SET uuid=excluded.uuid, nome=excluded.nome,
                       atualizado_em=excluded.atualizado_em""",
                  ((slug or "").strip(), (uuid or "").strip(), nome or "", _agora()))


def garantir_embarcacao(slug: str, nome: str = "") -> dict:
    """Devolve {"ok", "uuid", "motivo"} para a embarcacao desta camera.

    Ordem: equivalencia ja' gravada -> embarcacao de MESMO NOME no Supabase -> cria (com o cliente do
    ambiente, ou o primeiro cliente) -> falha explicita. Nunca devolve uuid inventado nem cria camera orfa.
    """
    slug = (slug or "").strip()
    if not slug:
        return {"ok": False, "motivo": "camera sem embarcacao_id (nao sei a que embarcacao pertence)"}
    conhecido = uuid_da_embarcacao(slug)
    if conhecido:
        return {"ok": True, "uuid": conhecido, "motivo": "equivalencia ja' gravada"}
    if not configurado():
        return {"ok": False, "motivo": "sem chave de servico (so' o lado terra espelha)"}
    if nome:
        st, d = _pedido(f"/rest/v1/embarcacoes?select=id,nome&nome=eq.{urllib.parse.quote(nome)}", None, "GET")
        if st == 200 and isinstance(d, list) and d:
            guardar_equivalencia(slug, str(d[0]["id"]), nome)
            return {"ok": True, "uuid": str(d[0]["id"]), "motivo": "embarcacao de mesmo nome ja' existia"}
    cliente = (os.environ.get("LECSOR_SUPABASE_CLIENTE_ID") or "").strip()
    if not cliente:
        st, d = _pedido("/rest/v1/clientes?select=id&limit=1", None, "GET")
        if st == 200 and isinstance(d, list) and d:
            cliente = str(d[0]["id"])
    if not cliente:
        return {"ok": False, "motivo": "nao ha cliente no Supabase para pendurar a embarcacao "
                                      "(defina LECSOR_SUPABASE_CLIENTE_ID)"}
    st, d = _pedido("/rest/v1/embarcacoes?on_conflict=id",
                    {"cliente_id": cliente, "nome": nome or slug}, "POST")
    if st in (200, 201):
        linha = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else {})
        novo = str((linha or {}).get("id") or "")
        if novo:
            guardar_equivalencia(slug, novo, nome or slug)
            return {"ok": True, "uuid": novo, "motivo": "embarcacao criada no Supabase"}
    return {"ok": False, "motivo": f"nao criei a embarcacao no Supabase (HTTP {st} {str(d)[:140]})"}


# ------------------------------------------------------------------ cameras
def salvar_camera(cam: dict | None) -> dict:
    """Grava (upsert) o cadastro da camera em `public.cameras` e devolve {"ok","motivo","uuid"}.

    Vai SO' identidade: id, embarcacao (uuid), rotulo, fluxo_id, ativo. Endereco (`ip`/`porta`),
    protocolo e canal NAO sobem — o cliente nunca pode ler isso (regra da migracao 20261111130000).
    """
    if not configurado():
        return {"ok": False, "motivo": "sem chave de servico (so' o lado terra espelha)"}
    cid = str((cam or {}).get("id") or "").strip()
    if not cid:
        return {"ok": False, "motivo": "camera sem id"}
    fluxo = str((cam or {}).get("fluxo_id") or cid).strip() or cid
    # o nome vem de quem chama; se nao veio, ele e' buscado AQUI (senao a embarcacao seria duplicada)
    emb_slug = str((cam or {}).get("embarcacao_id") or "")
    emb = garantir_embarcacao(emb_slug, str((cam or {}).get("embarcacao_nome") or "")
                              or nome_da_embarcacao(emb_slug))
    if not emb.get("ok"):
        return {"ok": False, "motivo": f"embarcacao: {emb.get('motivo')}"}
    ativo = (cam or {}).get("ativo", 1)
    corpo = {"id": cid, "embarcacao_id": emb["uuid"],
             "rotulo": str((cam or {}).get("rotulo") or fluxo)[:120], "fluxo_id": fluxo,
             "ativo": str(ativo).strip().lower() not in ("0", "false", "nao", "não", "n")}
    st, d = _pedido("/rest/v1/cameras?on_conflict=id", corpo, "POST")
    if st in (200, 201):
        return {"ok": True, "motivo": "gravada no banco", "uuid": str(emb["uuid"])}
    return {"ok": False, "motivo": f"cameras: HTTP {st} {str(d)[:150]}"}


def remover_camera(camera_id: str | None) -> dict:
    """Tira a camera do Supabase (o dono removeu na tela). Nada de historico aqui: a serie e' telemetria."""
    cid = str(camera_id or "").strip()
    if not cid:
        return {"ok": False, "motivo": "camera sem id"}
    if not configurado():
        return {"ok": False, "motivo": "sem chave de servico (so' o lado terra espelha)"}
    st, d = _pedido(f"/rest/v1/cameras?id=eq.{urllib.parse.quote(cid)}", None, "DELETE")
    if st in (200, 204):
        return {"ok": True, "motivo": "removida do banco"}
    return {"ok": False, "motivo": f"cameras: HTTP {st} {str(d)[:150]}"}


def espelhar(cam: dict | None, remover: bool = False) -> dict:
    """Um so' ponto de entrada para o resto do servidor: espelha ou remove o cadastro."""
    try:
        return remover_camera((cam or {}).get("id")) if remover else salvar_camera(cam)
    except Exception as e:  # noqa: BLE001  (o espelho nunca derruba o cadastro local)
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"}


def diagnostico() -> dict:
    """O que o `/api/saude` mostra: sem segredo, so' se o espelho tem como funcionar."""
    if not configurado():
        return {"configurado": False,
                "motivo": "sem LECSOR_SUPABASE_URL / LECSOR_SUPABASE_SERVICE_KEY nesta instalacao"}
    st, _d = _pedido("/rest/v1/cameras?select=id&limit=1", None, "GET")
    if st == 200:
        return {"configurado": True, "alcance": "ok"}
    return {"configurado": True, "alcance": f"falhou (HTTP {st})"}
