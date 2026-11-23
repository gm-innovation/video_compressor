#!/usr/bin/env python3
"""J7 — Os 4 escopos de cliente (e o cliente NAO enxerga o vizinho).

Palavras do dono (20/11/2026): "temos 4 tipos de clientes 1. cliente que pode ver apenas uma embarcacao
da empresa 2. cliente que pode ver algumas embarcacoes da empresa 3. cliente que pode ver todas as
embarcacoes da empresa 4. cliente que pode ver todas as embarcacoes de todas as empresas (petrobras)".
O escopo e' o que o ADMIN concede; o cliente nao escolhe.

Acao do usuario (tudo pela mesma rota que a tela do admin usa): o admin cria a empresa de smoke, dois
barcos dela, um usuario de cada tipo e um observador (o observador nao recebe vinculo: ve' tudo).
Medida: cada usuario ENTRA de verdade (login real) e a lista de barcos que ele recebe e' contada — mais
o outro sentido, que e' o que prova o isolamento: o cliente de uma empresa NAO ve' o barco da outra, e
vincular barco de outra empresa e' recusado.

Some-se o que o smoke cria, o smoke apaga (S2 do plano): empresa, barcos, usuarios, vinculos e as
credenciais do Supabase Auth dos usuarios de smoke.
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import apagar_usuario_do_supabase, pedir, senha_de_demo  # noqa: E402
from relatorio import Jornada  # noqa: E402


def _d(x) -> dict:
    """A resposta do `pedir` so' e' dicionario quando deu certo — e o erro vira medida, nunca estouro."""
    return x if isinstance(x, dict) else {}


def _barcos(amb, sessao: str) -> list[dict] | None:
    """Os barcos que ESTE usuario recebe (o que a tela dele desenha). None = nao deu para perguntar."""
    codigo, r = pedir("GET", f"{amb.terra}/api/embarcacoes", sessao=sessao)
    if codigo != 200:
        return None
    return [dict(x) for x in _d(r).get("embarcacoes") or []]


def _escopo_do_admin(amb, admin: str, uid: str) -> tuple[int, dict]:
    codigo, r = pedir("GET", f"{amb.terra}/api/usuarios/{uid}/embarcacoes", sessao=admin)
    return codigo, _d(r)


def _limpar(amb, empresa: str, barcos: list[str], emails: list[str]) -> None:
    """Apaga TUDO o que o smoke criou. Roda no `finally` — nunca deixa lixo se a jornada falhar."""
    for email in emails:
        apagar_usuario_do_supabase(email)
    try:
        banco = sqlite3.connect(str(amb.banco_terra))
        try:
            banco.execute("DELETE FROM usuario_embarcacoes WHERE embarcacao_id IN (%s)"
                          % ",".join("?" * len(barcos)), barcos)
            for email in emails:
                linha = banco.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
                if linha:
                    banco.execute("DELETE FROM usuario_embarcacoes WHERE usuario_id=?", (linha[0],))
                    banco.execute("DELETE FROM sessoes WHERE usuario_id=?", (linha[0],))
                    banco.execute("DELETE FROM usuarios WHERE id=?", (linha[0],))
            for b in barcos:
                banco.execute("DELETE FROM cameras WHERE embarcacao_id=?", (b,))
                banco.execute("DELETE FROM embarcacoes WHERE id=?", (b,))
            banco.execute("DELETE FROM clientes WHERE id=?", (empresa,))
            banco.commit()
        finally:
            banco.close()
    except Exception:  # noqa: BLE001 — limpeza e' melhor-esforco: o relatorio diz o que sobrou
        pass


def _sobrou(amb, empresa: str, barcos: list[str], emails: list[str]) -> dict:
    """O que sobrou depois da limpeza. A jornada responde por isso: a base e' do dono."""
    sobrou: dict = {}
    try:
        banco = sqlite3.connect(str(amb.banco_terra))
        try:
            for tabela, campo, valores in (("clientes", "id", [empresa]), ("embarcacoes", "id", barcos),
                                           ("usuarios", "email", emails)):
                marcas = ",".join("?" * len(valores))
                n = banco.execute(f"SELECT count(*) FROM {tabela} WHERE {campo} IN ({marcas})",
                                  valores).fetchone()[0]
                if n:
                    sobrou[tabela] = n
        finally:
            banco.close()
    except Exception as e:  # noqa: BLE001
        sobrou["erro_de_leitura"] = type(e).__name__
    return sobrou


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(7, "Os 4 escopos de cliente (e o cliente nao enxerga o vizinho)",
                "o escopo e' do admin: 1 barco, alguns, todos da empresa, ou todos de todas as empresas")
    ts = int(time.time())
    empresa = f"smoke-{ts}"
    barcos = [f"smoke-{ts}-1", f"smoke-{ts}-2"]
    emails = [f"smoke-{ts}-um@lecsor.test", f"smoke-{ts}-alguns@lecsor.test",
              f"smoke-{ts}-todos@lecsor.test", f"smoke-{ts}-olho@lecsor.test"]
    criados: dict[str, str] = {}
    admin = amb.entrar("admin@lecsor.test")
    j.checar("o admin entra no painel", bool(admin), "sessao de admin do sistema")
    if not admin:
        return j
    try:
        # 1) a empresa e os dois barcos dela (o minimo para "uma" ser diferente de "todas")
        codigo, r = pedir("POST", f"{amb.terra}/api/clientes",
                          {"id": empresa, "nome": f"Smoke {ts} (empresa)"}, sessao=admin)
        j.checar("o admin cria a empresa", codigo in (200, 201), f"HTTP {codigo} · {empresa}")
        for b in barcos:
            codigo, rb = pedir("POST", f"{amb.terra}/api/embarcacoes",
                               {"id": b, "cliente_id": empresa, "nome": f"Barco {b}"}, sessao=admin)
            j.checar(f"o admin cria o barco {b}", codigo == 201, f"HTTP {codigo}")
        # a camera: o cliente so' existe com camera no barco (a rota /api/hd/catalogo exige camera)
        codigo, _ = pedir("POST", f"{amb.terra}/api/cameras",
                          {"id": f"{barcos[0]}-cam", "embarcacao_id": barcos[0], "rotulo": "cam do smoke",
                           "fluxo_id": f"{barcos[0]}-cam"}, sessao=admin)
        j.checar("o admin cadastra uma camera no primeiro barco", codigo == 201, f"HTTP {codigo}")

        # 2) um usuario de cada tipo (a senha inicial volta UMA vez — e' o que o admin entrega)
        papeis = [("um", "cliente"), ("alguns", "cliente"), ("todos", "cliente"), ("olho", "observador")]
        for nome, papel in papeis:
            email = f"smoke-{ts}-{nome}@lecsor.test"
            corpo = {"email": email, "nome": f"Smoke {nome}", "papel": papel}
            if papel == "cliente":
                corpo["cliente_id"] = empresa
            codigo, rb = pedir("POST", f"{amb.terra}/api/usuarios", corpo, sessao=admin)
            senha = str(_d(rb).get("senha_inicial") or "")
            criados[nome] = str(_d(rb).get("id") or "")
            j.checar(f"o admin cadastra o usuario {nome} ({papel})", codigo == 201 and bool(senha),
                     f"HTTP {codigo} · {email}" + ("" if codigo == 201 else f" · {str(rb)[:70]}"))
            if senha:
                ctx.setdefault("senhas_do_smoke", {})[email] = senha
        if not all(criados.values()):
            return j

        # 3) os vinculos: um barco, dois barcos, nenhum (e o observador nao recebe vinculo)
        codigo, _ = pedir("POST", f"{amb.terra}/api/usuarios/{criados['um']}/embarcacoes",
                          {"embarcacao_ids": [barcos[0]]}, sessao=admin)
        j.checar("o admin concede UM barco ao cliente 'um'", codigo == 200, f"HTTP {codigo}")
        codigo, _ = pedir("POST", f"{amb.terra}/api/usuarios/{criados['alguns']}/embarcacoes",
                          {"embarcacao_ids": barcos}, sessao=admin)
        j.checar("o admin concede OS DOIS barcos ao cliente 'alguns'", codigo == 200, f"HTTP {codigo}")

        # 4) a resposta do admin diz o escopo de cada um (e' o que a tela mostra)
        esperado = {"um": "uma_embarcacao_da_empresa", "alguns": "algumas_embarcacoes_da_empresa",
                    "todos": "todas_as_embarcacoes_da_empresa", "olho": "todas_as_empresas"}
        for nome, espera in esperado.items():
            codigo, r = _escopo_do_admin(amb, admin, criados[nome])
            escopo = str((r or {}).get("escopo") or "")
            j.checar(f"o painel do admin diz o escopo do '{nome}'", codigo == 200 and escopo == espera,
                     f"{escopo or 'sem resposta'} (HTTP {codigo})")

        # 5) o outro sentido: cada usuario ENTRA e a lista de barcos DELE e' contada
        medida: dict[str, int] = {}
        for nome in ("um", "alguns", "todos", "olho"):
            email = f"smoke-{ts}-{nome}@lecsor.test"
            senha = (ctx.get("senhas_do_smoke") or {}).get(email, "")
            sessao = amb.entrar(email, senha)
            lista = _barcos(amb, sessao) if sessao else None
            if lista is None:
                j.checar(f"o '{nome}' entra e ve' barcos", False, "sem sessao ou sem resposta da lista")
                medida[nome] = -1
                continue
            ids = {str(b.get("id")) for b in lista}
            medida[nome] = len(ids)
            if nome == "um":
                j.checar("tipo 1 (uma embarcacao): o cliente ve' SO' o barco dele",
                         ids == {barcos[0]}, f"{len(ids)} barco(s): {sorted(ids)}")
            elif nome == "alguns":
                j.checar("tipo 2 (algumas embarcacoes): o cliente ve' os dois concedidos",
                         ids == set(barcos), f"{len(ids)} barco(s): {sorted(ids)}")
            elif nome == "todos":
                j.checar("tipo 3 (todas da empresa): o cliente ve' todos os barcos da empresa dele",
                         ids == set(barcos), f"{len(ids)} barco(s): {sorted(ids)}")
            else:
                espera = {"bancada", "psv-exemplo", *barcos}
                j.checar("tipo 4 (observador): ve' as embarcacoes de TODAS as empresas",
                         espera <= ids, f"{len(ids)} barco(s): {sorted(ids)}")

        # 6) ISOLAMENTO, os dois sentidos — o que a J7 existe para provar
        if medida.get("todos", -1) >= 0:
            lista = _barcos(amb, amb.entrar("cliente@lecsor.test", senha_de_demo())) or []
            ids = {str(b.get("id")) for b in lista}
            j.checar("o cliente da LECSOR nao ve' o barco da outra empresa",
                     "psv-exemplo" not in ids and not ids.intersection(barcos),
                     f"{sorted(ids)}")
        outro = amb.entrar("cliente@armador-demo.test", senha_de_demo())
        lista_b = _barcos(amb, outro) if outro else None
        if lista_b is not None:
            ids_b = {str(b.get("id")) for b in lista_b}
            j.checar("o cliente da outra empresa nao ve' a bancada nem os barcos do smoke",
                     "bancada" not in ids_b and not ids_b.intersection(barcos), f"{sorted(ids_b)}")
        codigo, _ = pedir("POST", f"{amb.terra}/api/usuarios/{criados['um']}/embarcacoes",
                          {"embarcacao_ids": ["psv-exemplo"]}, sessao=admin)
        j.checar("vincular barco de OUTRA empresa e' recusado (vinculo nao amplia empresa)",
                 codigo in (400, 403, 422), f"HTTP {codigo}")
        sessao_um = amb.entrar(f"smoke-{ts}-um@lecsor.test",
                               (ctx.get("senhas_do_smoke") or {}).get(f"smoke-{ts}-um@lecsor.test", ""))
        codigo, _ = pedir("GET", f"{amb.terra}/api/hd/catalogo?camera_id=bancada-cam", sessao=sessao_um)
        j.checar("pedir dado de camera de outra empresa e' negado (403)", codigo == 403, f"HTTP {codigo}")

        j.medir(empresa=empresa, barcos=barcos, barcos_por_tipo=medida,
                escopos={n: esperado[n] for n in esperado})
    except Exception as e:  # noqa: BLE001
        j.erro = f"{type(e).__name__}: {e}"
    finally:
        _limpar(amb, empresa, barcos, emails)
        sobrou = _sobrou(amb, empresa, barcos, emails)
        j.checar("o smoke apaga o que criou (nao deixa lixo na base do dono)", sobrou == {},
                 f"sobrou: {sobrou}" if sobrou else "empresa, barcos, usuarios e vinculos removidos")
        j.medir(limpeza=sobrou or "limpo")
    return j
