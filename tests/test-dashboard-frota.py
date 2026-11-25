#!/usr/bin/env python3
"""OS DOIS DASHBOARDS NO PADRAO DOCK CHECK (0.20.0, Fases P1/P2) — provado por HTTP.

O dono (25/11/2026, verbatim): "tanto o dashboard do admin quanto o do app de captura continuam
horriveis, precisa ser algo mais proximo desse do Dock Check".

A regra desta prova e' a mesma do smoke: SEM MEDIDA NAO E' "OK". O que se prova aqui:

  1) `/api/frota-resumo` e' do ADMIN: sem sessao 401, com sessao de CLIENTE 401 (o cliente ja' tem a
     area dele em `/api/empresas` + `/api/eu`);
  2) com admin: vem kpis, embarcacoes, alertas, conexoes e a disponibilidade de 7 dias;
  3) a disponibilidade e' MEDIDA do que o bordo mandou (retratos de `saude_bordo`), dia a dia, e um
     bordo silencioso NAO vira "ok" — sai como sem dado / problema;
  4) o semaforo da embarcacao e' o MESMO `classificar_saude` do painel (cpu 93 -> problema, cpu 22 -> ok);
  5) a tela do admin veste a linguagem do Dock Check (`fronts/dashboard.css`, cartao `dash-kpi`) e a
     tela do bordo tambem (cabecalho + diagnostico de conexoes + `dash-kpi`).

    python tests/test-dashboard-frota.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = "senha-do-dashboard-de-teste"
EMPRESA = "empresa-dash"
EMB_SAUDAVEL = "emb-dash-ok"
EMB_DOENTE = "emb-dash-ruim"
EMB_ATENCAO = "emb-dash-atencao"     # cpu 78: 'atencao' — o vocabulario do semaforo tem dois nomes
EMB_MUDA = "emb-dash-muda"          # nunca mandou retrato: NAO pode aparecer como "ok"


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str, cliente_id=None) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    con.commit()
    con.close()


def retrato(cpu: float, memoria: float) -> str:
    """Retrato COMPLETO o bastante para o semaforo poder dizer 'ok' — assim a prova isola o sinal que
    quer medir (cpu/memoria). Sem `ffmpeg`/`agente`/`mediamtx`/`banco` o proprio semaforo diria
    'problema' e a prova nao mediria nada."""
    return json.dumps({"cpu_pct": cpu, "memoria_pct": memoria,
                       "discos": [{"nome": "C:", "usado_pct": 20.0, "livre_gb": 90.0}],
                       "rede": {"enviado_mbps": 3.0, "recebido_mbps": 1.0},
                       "ffmpeg": {"presente": True, "versao": "ffmpeg test"},
                       "agente": {"laco_vivo": True, "idade_s": 3},
                       "mediamtx": {"ativo": True, "caminhos": 1},
                       "banco": {"erros_24h": 0},
                       "maquina": "PC-DASH", "versao_app": "0.20.0"})


def semear(banco: pathlib.Path) -> None:
    """Uma empresa, quatro embarcacoes: uma saudavel (2 retratos), uma em atencao, uma doente (cpu 93)
    e uma MUDA — que nunca reportou e por isso nao pode aparecer como 'ok'."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Empresa Dash"))
    for eid, nome in ((EMB_SAUDAVEL, "Embarcacao Saudavel"), (EMB_DOENTE, "Embarcacao Doente"),
                      (EMB_ATENCAO, "Embarcacao Em Atencao"), (EMB_MUDA, "Embarcacao Muda")):
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado) VALUES (?,?,?,?,'em operacao')",
                    (eid, EMPRESA, nome, ""))
    agora = dt.datetime.now(dt.timezone.utc)   # o carimbo do sistema e' UTC (em_iso)
    # as duas da embarcacao SAUDAVEL: uma AGORA (dentro do limiar de "mudo") e uma de ontem, para a
    # disponibilidade ter dois dias. A DOENTE tambem reporta agora: o unico motivo do 'problema' dela
    # e' o cpu 93 — a prova mede o semaforo, nao o silencio.
    for eid, cpu, mem, quando_atras in ((EMB_SAUDAVEL, 22.0, 41.0, dt.timedelta(seconds=40)),
                                        (EMB_SAUDAVEL, 18.0, 40.0, dt.timedelta(hours=26)),
                                        (EMB_DOENTE, 93.0, 71.0, dt.timedelta(seconds=35)),
                                        (EMB_ATENCAO, 78.0, 66.0, dt.timedelta(seconds=45))):
        quando = (agora - quando_atras).isoformat(timespec="seconds")
        con.execute("INSERT INTO saude_bordo (embarcacao_id,recebido_em,maquina,versao_app,estado,retrato)"
                    " VALUES (?,?,?,?,?,?)", (eid, quando, "PC-DASH", "0.20.0", "", retrato(cpu, mem)))
    con.commit()
    con.close()


def subir(banco: pathlib.Path, tmp: pathlib.Path):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_SENHA_DEMO"] = "senha-de-bancada-nao-usada"
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
    porta = porta_livre()
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(80):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                return api, base
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    api.kill()
    raise RuntimeError("a API nao subiu; log em %s" % (tmp / "api.log"))


def entrar(base: str, email: str) -> str:
    req = urllib.request.Request(base + "/api/entrar", method="POST",
                                 data=json.dumps({"email": email, "senha": SENHA}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return (r.headers.get("Set-Cookie") or "").split(";")[0]


def pedir(base: str, rota: str, cookie: str = ""):
    cab = {"Cookie": cookie} if cookie else {}
    rq = urllib.request.Request(base + rota, headers=cab)
    try:
        with urllib.request.urlopen(rq, timeout=8) as r:
            corpo = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(corpo or "{}")
            except json.JSONDecodeError:
                return r.status, corpo
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(corpo or "{}")
        except json.JSONDecodeError:
            return e.code, corpo


def principal() -> int:
    print("== dashboard do admin: a leitura e' do ADMIN e a medida vem do bordo ==")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-dash-"))
    banco = tmp / "pipeline.db"
    api, base = subir(banco, tmp)
    try:
        criar_usuario(banco, "admin", "admin@lecsor.test", "admin")
        criar_usuario(banco, "cliente", "cliente@empresa.test", "cliente", EMPRESA)
        semear(banco)

        s, _ = pedir(base, "/api/frota-resumo")
        checar("sem sessao: 401", s == 401, f"veio {s}")

        cookie_cliente = entrar(base, "cliente@empresa.test")
        s, j = pedir(base, "/api/frota-resumo", cookie_cliente)
        checar("com sessao de CLIENTE: 401 (e' painel do admin)", s == 401,
               f"veio {s} {json.dumps(j)[:80]}")

        cookie = entrar(base, "admin@lecsor.test")
        s, d = pedir(base, "/api/frota-resumo", cookie)
        checar("com sessao de admin: 200", s == 200, f"veio {s}")
        if s != 200 or not isinstance(d, dict):
            return resumo_final()
        for chave in ("agora", "kpis", "embarcacoes", "alertas", "conexoes"):
            checar(f"a resposta traz `{chave}`", chave in d)
        k = d.get("kpis") or {}
        checar("kpis contam pelo menos as embarcacoes do teste", k.get("embarcacoes", 0) >= 3,
               json.dumps(k))
        checar("3 bordos reportando (a muda nao)", k.get("bordo_reportando") == 3, json.dumps(k))
        checar("o semaforo conta 1 ok, 1 atencao e 1 problema",
               k.get("ok") == 1 and k.get("atencao") == 1 and k.get("problema") == 1, json.dumps(k))
        checar("ha alertas com 'o que fazer'",
               bool(d.get("alertas")) and all(a.get("o_que_fazer") for a in d["alertas"][:3]),
               str(len(d.get("alertas") or [])) + " alerta(s)")

        por_id = {e["id"]: e for e in (d.get("embarcacoes") or [])}
        checar("as quatro embarcacoes do teste estao no painel",
               all(x in por_id for x in (EMB_SAUDAVEL, EMB_DOENTE, EMB_ATENCAO, EMB_MUDA)))
        checar("a embarcacao do cpu 93 saiu 'problema'",
               por_id.get(EMB_DOENTE, {}).get("estado") == "problema",
               str(por_id.get(EMB_DOENTE, {}).get("estado")))
        checar("a embarcacao do cpu 78 saiu 'atencao'",
               por_id.get(EMB_ATENCAO, {}).get("estado") in ("atencao", "alerta"),
               str(por_id.get(EMB_ATENCAO, {}).get("estado")))
        checar("a embarcacao saudavel saiu 'ok'", por_id.get(EMB_SAUDAVEL, {}).get("estado") == "ok",
               str(por_id.get(EMB_SAUDAVEL, {}).get("estado")) + " | sinais: "
               + json.dumps([a.get("sinal") for a in (d.get("alertas") or [])
                             if a.get("embarcacao_id") == EMB_SAUDAVEL]))
        checar("a embarcacao MUDA nao virou 'ok'", por_id.get(EMB_MUDA, {}).get("estado") != "ok",
               repr(por_id.get(EMB_MUDA, {}).get("estado")))
        posicao = {e.get("id"): i for i, e in enumerate(d.get("embarcacoes") or [])}
        checar("a ordem e' pior primeiro: problema, atencao, ok e o sem dado no fim",
               posicao.get(EMB_DOENTE, 99) < posicao.get(EMB_ATENCAO, 99) < posicao.get(EMB_SAUDAVEL, 99)
               < posicao.get(EMB_MUDA, 99),
               str([e.get("id") for e in (d.get("embarcacoes") or [])]))
        checar("a empresa vai junto de cada embarcacao do teste",
               all(por_id.get(x, {}).get("empresa") == "Empresa Dash"
                   for x in (EMB_SAUDAVEL, EMB_DOENTE, EMB_MUDA)),
               json.dumps({x: por_id.get(x, {}).get("empresa") for x in (EMB_SAUDAVEL, EMB_MUDA)}))

        disp = por_id.get(EMB_SAUDAVEL, {}).get("disponibilidade") or {}
        dias = disp.get("dias") or []
        checar("disponibilidade: 7 dias na janela", len(dias) == 7, str(len(dias)))
        checar("disponibilidade: MEDIDA do que o bordo mandou (2 retratos)",
               disp.get("retratos") == 2, json.dumps(disp)[:120])
        checar("disponibilidade: cobertura 2 dias da janela",
               disp.get("dias_com_retrato") == 2, json.dumps(disp)[:120])
        checar("o dia de ontem entrou na serie",
               any(x.get("retratos") == 1 and x.get("ok") == 1 for x in dias),
               json.dumps([x for x in dias if x.get("retratos")]))
        checar("a embarcacao muda tem 0 retrato (nada inventado)",
               (por_id.get(EMB_MUDA, {}).get("disponibilidade") or {}).get("retratos") == 0)

        cx = d.get("conexoes") or {}
        checar("o diagnostico diz quando foi o ultimo retrato", bool(cx.get("ultimo_retrato_em")))
        checar("o diagnostico traz a rota do video (fluxos/ingestao)",
               "fluxos_no_ar" in cx and "ultima_ingestao_em" in cx, json.dumps(cx)[:120])

        # ---- a TELA (o que o admin e o bordo carregam de fato) ------------------------------------
        print("== a linguagem do Dock Check nas DUAS telas ==")
        s, css = pedir(base, "/fronts/dashboard.css")
        checar("fronts/dashboard.css e' servido", s == 200 and "dash-kpi" in str(css), f"veio {s}")
        s, js = pedir(base, "/admin/admin.js")
        checar("a tela do admin usa os cartoes do Dock Check",
               s == 200 and "dash-kpi" in str(js) and "/api/frota-resumo" in str(js))
        s, html = pedir(base, "/admin")
        checar("a tela do admin linka o dashboard.css",
               s == 200 and "/fronts/dashboard.css" in str(html))
        s, bordo = pedir(base, "/bordo")
        texto = str(bordo)
        checar("a tela do bordo carrega", s == 200, f"veio {s}")
        checar("a tela do bordo linka o dashboard.css", "/fronts/dashboard.css" in texto)
        checar("a tela do bordo tem o cabecalho e o diagnostico",
               'id="dash-topo"' in texto and 'id="dash-diag"' in texto)
        checar("o cartao do bordo virou o do Dock Check (dash-kpi)", "dash-kpi" in texto)
    finally:
        api.kill()
        try:
            api.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    return resumo_final()


def resumo_final() -> int:
    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} verificacao(oes): " + "; ".join(falhas))
        return 1
    print("OK — os dois dashboards medem o que mostram, no padrao do Dock Check.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
