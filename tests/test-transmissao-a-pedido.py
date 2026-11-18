#!/usr/bin/env python3
"""Transmissao a pedido do cliente (17/11/2026): o cliente abre pela WEB, a ordem vai ao bordo.

Plano: .hermes/plans/2026-11-17-transmissao-a-pedido-do-cliente.md
Provas, com a API de verdade rodando e o banco de verdade:
  1) quem pede e' APENAS o cliente (operador e' recusado) e so' a embarcacao da PROPRIA empresa;
  2) o pedido cria a sessao e a ORDEM na fila do bordo (nasce no lado terra);
  3) o bordo so' entra na fila com o token de ingestao (sem token / token errado = 401);
  4) a ordem e' entregue UMA vez e o resultado do bordo vira "no ar" na tela do cliente;
  5) batimento mantem a sessao viva; TEMPO MAXIMO: estoura -> para e o cliente inicia de novo;
  6) GRAVANDO no lado terra nao corta no tempo (decisao do dono);
  7) corte POR SESSAO: quem fecha a tela derruba so' a propria sessao; o outro cliente continua vendo;
  8) a camera so' para quando NAO ha' mais ninguem vendo; tela fechada/computador desligado = para;
  9) o historico fica (nada e' apagado) e a tela de configuracao grava o tempo do cliente.

    python tests/test-transmissao-a-pedido.py
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
TOKEN = "token-de-teste-do-bordo"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(metodo: str, url: str, corpo=None, token_sessao: str = "", token_bordo: str = "", bruto: bytes | None = None):
    if bruto is not None:
        dados = bruto
    else:
        dados = json.dumps(corpo).encode() if corpo is not None else None
    cabecalhos = {"Content-Type": "application/json"} if dados and bruto is None else {}
    if dados and bruto is not None:
        cabecalhos["Content-Type"] = "text/plain"
    if token_sessao:
        cabecalhos["Cookie"] = f"sessao={token_sessao}"
    if token_bordo:
        cabecalhos["Authorization"] = f"Bearer {token_bordo}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=40) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def baixar(url: str, token_sessao: str = ""):
    """Baixa um ARQUIVO (a gravacao): devolve o status e os bytes crus, sem tentar virar JSON."""
    req = urllib.request.Request(url, method="GET",
                                 headers={"Cookie": f"sessao={token_sessao}"} if token_sessao else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            return f.status, f.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def agora_iso(deslocamento_s: float = 0) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=deslocamento_s)).isoformat(timespec="seconds")


def usuario(con, uid, email, papel, cliente_id="lecsor"):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    tok = f"tok-{uid}"
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, agora_iso(3600), "teste"))
    return tok


def estado_da_sessao(banco, tid):
    con = sqlite3.connect(banco)
    r = con.execute("SELECT estado, motivo, gravando, segundos_max, termina_em FROM transmissoes WHERE id=?",
                    (tid,)).fetchone()
    con.close()
    return r


def ordens_do_bordo(banco, emb="bancada", acao=""):
    con = sqlite3.connect(banco)
    sql = "SELECT id, acao, camera_id, estado, motivo, transmissao_id FROM ordens_do_bordo WHERE embarcacao_id=?"
    if acao:
        sql += f" AND acao='{acao}'"
    sql += " ORDER BY seq"
    linhas = con.execute(sql, (emb,)).fetchall()
    con.close()
    return linhas


def mexer(banco, sql, args=()):
    con = sqlite3.connect(banco)
    con.execute(sql, args)
    con.commit()
    con.close()


def esperar_vigia(banco, tid, estados, limite=14.0):
    """O vigia roda a cada 5 s na API: espera a sessao sair de 'pedida'/'no_ar'."""
    fim = time.time() + limite
    while time.time() < fim:
        r = estado_da_sessao(banco, tid)
        if r and r[0] in estados:
            return r
        time.sleep(0.5)
    return estado_da_sessao(banco, tid)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-transmissao-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["LECSOR_GRAVACOES_DIR"] = str(tmp / "gravacoes")   # as gravacoes do lado terra ficam aqui
    env["PYTHONIOENCODING"] = "utf-8"
    # o lado terra nao fala com Supabase nem com outro lado terra neste teste
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    pronto = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                pronto = True
                break
        except Exception:
            time.sleep(0.5)
    if not pronto:
        print("FALHA a API de teste nao subiu; log:", (tmp / "api.log").read_text(errors="replace")[-600:])
        api.terminate()
        return 1

    try:
        con = sqlite3.connect(banco)
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        exigir({"transmissoes", "ordens_do_bordo", "configs_do_cliente"} <= tabelas,
               f"as tabelas da transmissao existem no banco ({sorted(tabelas & {'transmissoes', 'ordens_do_bordo', 'configs_do_cliente'})})")
        # a API ja' semeia a bancada no boot: aqui e' upsert, para o teste nao brigar com o seed
        con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('outra','Outra Empresa')")
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('psv-01','outra','PSV 01 (de outra empresa)')")
        for cam, emb, rot in (("cam-01", "bancada", "Proa"), ("cam-02", "bancada", "Popa"),
                              ("cam-09", "psv-01", "Casa de maquinas")):
            con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo)
                           VALUES (?,?,?,?, 'bordo', 1)""", (cam, emb, rot, cam))
        con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo)
                       VALUES ('cam-off','bancada','Desativada','cam-off','bordo',0)""")
        tok_cli = usuario(con, "cli1", "cliente@pipeline.test", "cliente")
        tok_cli2 = usuario(con, "cli2", "cliente2@pipeline.test", "cliente")
        tok_op = usuario(con, "ope1", "operacao@pipeline.test", "operador")
        tok_outro = usuario(con, "cli3", "cliente@outra.test", "cliente", cliente_id="outra")
        tok_adm = usuario(con, "adm1", "admin@pipeline.test", "admin")
        con.commit()
        con.close()

        # --- 1) quem pede e' o CLIENTE, e so' da propria empresa ------------------------------------
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01"}, token_sessao=tok_op)
        exigir(s == 403 and "cliente" in str(j.get("erro")), f"operador nao inicia transmissao ({s} {j.get('erro')})")
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01"}, token_sessao=tok_outro)
        exigir(s == 403, f"cliente de outra empresa nao alcanca camera que nao e' dele ({s} {j.get('erro')})")
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-09"}, token_sessao=tok_cli)
        exigir(s == 403, f"cliente nao alcanca camera de outra embarcacao ({s})")
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-nao-existe"}, token_sessao=tok_cli)
        exigir(s == 404, f"camera inexistente e' recusada ({s})")
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-off"}, token_sessao=tok_cli)
        exigir(s == 422 and "desativada" in str(j.get("erro")), f"camera desativada e' recusada ({s} {j.get('erro')})")
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01", "segundos_max": 123},
                     token_sessao=tok_cli)
        exigir(s == 422 and "300" in str(j.get("erro")), f"tempo fora da lista e' recusado ({s} {j.get('erro')})")

        # --- 2) o pedido cria a sessao e a ORDEM para o bordo ---------------------------------------
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01", "segundos_max": 900},
                     token_sessao=tok_cli)
        exigir(s == 201 and j.get("transmissao", {}).get("estado") == "pedida",
               f"o cliente abriu a transmissao ({s} {j.get('erro')})")
        tid = (j.get("transmissao") or {}).get("id", "")
        fila = ordens_do_bordo(banco, "bancada", "iniciar")
        exigir(len(fila) == 1 and fila[0][3] == "pedido" and fila[0][5] == tid,
               f"a ordem nasceu no lado terra para o bordo ({fila})")
        exigir(j["transmissao"]["segundos_max"] == 900 and j["transmissao"]["termina_em"],
               f"a sessao carrega o tempo escolhido e o fim ({j['transmissao']['segundos_max']}s)")
        s, j2 = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01"}, token_sessao=tok_cli)
        exigir(s == 200 and j2.get("ja_aberta") and len(ordens_do_bordo(banco, "bancada", "iniciar")) == 1,
               f"pedir de novo nao abre segunda sessao nem segunda ordem ({s})")

        # --- 3) o bordo so' entra na fila com o token de ingestao -----------------------------------
        s, j = pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0")
        exigir(s == 401, f"sem token o bordo nao recebe ordem ({s})")
        s, j = pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo="token-errado")
        exigir(s == 401, f"token errado e' recusado ({s})")
        s, j = pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)
        exigir(s == 200 and len(j.get("ordens") or []) == 1 and j["ordens"][0]["acao"] == "iniciar",
               f"o bordo recebeu a ordem de iniciar ({s} {j.get('ordens')})")
        exigir(j["ordens"][0]["camera_id"] == "cam-01" and j["ordens"][0]["transmissao_id"] == tid,
               "a ordem diz a camera e a sessao")
        s, j = pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)
        exigir(s == 200 and not j.get("ordens"), f"a ordem e' entregue UMA vez ({j.get('ordens')})")
        s, j = pedir("POST", base + f"/api/ordens/{fila[0][0]}/resultado",
                     {"estado": "atendida", "resultado": "camera cam-01: iniciar feito", "fluxo_id": "cam-01"},
                     token_bordo=TOKEN)
        exigir(s == 200 and j.get("estado") == "atendida", f"o bordo contou o resultado ({s})")
        exigir(estado_da_sessao(banco, tid)[0] == "no_ar", f"a sessao do cliente ficou no ar ({estado_da_sessao(banco, tid)})")
        s, j = pedir("POST", base + "/api/ordens/nao-existe/resultado", {"estado": "atendida"}, token_bordo=TOKEN)
        exigir(s == 404, f"resultado de ordem inexistente e' recusado ({s})")

        # --- 4) batimento + o que a tela ve ---------------------------------------------------------
        s, j = pedir("GET", base + "/api/transmissao?embarcacao=bancada", token_sessao=tok_cli)
        exigir(s == 200 and any(t["id"] == tid for t in j.get("abertas") or []),
               f"a tela ve a transmissao aberta ({s})")
        exigir(j.get("tempos") == [300, 900, 1800, 3600, 7200],
               f"os tempos vem em lista fechada ({j.get('tempos')})")
        exigir(j.get("tempo_maximo_s") == 900, f"o tempo padrao do cliente aparece ({j.get('tempo_maximo_s')})")
        s, j = pedir("POST", base + f"/api/transmissao/{tid}/batimento", {}, token_sessao=tok_cli)
        exigir(s == 200, f"o batimento da tela e' aceito ({s})")
        s, j = pedir("POST", base + f"/api/transmissao/{tid}/batimento", {}, token_sessao=tok_cli2)
        exigir(s == 403, f"outro cliente nao bate na sessao alheia ({s})")
        s, j = pedir("GET", base + "/api/transmissao?embarcacao=psv-01", token_sessao=tok_cli)
        exigir(s == 403, f"cliente nao le a transmissao de embarcacao que nao e' dele ({s})")

        # --- 5) tela de configuracao do cliente -----------------------------------------------------
        s, j = pedir("POST", base + "/api/transmissao/config", {"tempo_maximo_s": 300}, token_sessao=tok_cli)
        exigir(s == 200 and j.get("tempo_maximo_s") == 300, f"o cliente gravou o tempo dele ({s})")
        s, j = pedir("POST", base + "/api/transmissao/config", {"tempo_maximo_s": 42}, token_sessao=tok_cli)
        exigir(s == 422, f"tempo fora da lista nao e' gravado ({s})")
        s, j = pedir("GET", base + "/api/transmissao?embarcacao=bancada", token_sessao=tok_cli)
        exigir(j.get("tempo_maximo_s") == 300, f"a tela le o tempo configurado ({j.get('tempo_maximo_s')})")

        # --- 6) corte POR SESSAO: o outro cliente continua vendo -------------------------------------
        pedir("POST", base + "/api/transmissao/config", {"tempo_maximo_s": 300}, token_sessao=tok_cli2)
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01"}, token_sessao=tok_cli2)
        exigir(s == 201, f"o segundo cliente abriu a MESMA camera ({s} {j.get('erro')})")
        tid2 = (j.get("transmissao") or {}).get("id", "")
        exigir(estado_da_sessao(banco, tid2)[3] == 300,
               f"a sessao do segundo cliente usa o tempo DELE na tela de configuracao ({estado_da_sessao(banco, tid2)})")
        s, j = pedir("POST", base + f"/api/transmissao/{tid2}/encerrar", {}, token_sessao=tok_cli)
        exigir(s == 403 and estado_da_sessao(banco, tid2)[0] in ("pedida", "no_ar"),
               f"um cliente nao encerra a sessao do outro ({s} {estado_da_sessao(banco, tid2)})")
        s, j = pedir("POST", base + f"/api/transmissao/{tid2}/batimento", {}, token_sessao=tok_cli)
        exigir(s == 403, f"e nao bate na sessao do outro ({s})")
        s, j = pedir("POST", base + f"/api/transmissao/{tid2}/encerrar", {}, token_sessao=tok_cli2)
        exigir(s == 200 and estado_da_sessao(banco, tid2)[0] == "encerrada",
               f"o dono encerra a propria tela ({s} {estado_da_sessao(banco, tid2)})")
        exigir(estado_da_sessao(banco, tid)[0] == "no_ar",
               f"fechar UMA tela nao derruba a sessao do outro cliente ({estado_da_sessao(banco, tid)})")
        exigir(not ordens_do_bordo(banco, "bancada", "parar"),
               f"a camera NAO para enquanto o outro cliente esta' vendo ({ordens_do_bordo(banco, 'bancada', 'parar')})")
        s, j = pedir("POST", base + f"/api/transmissao/{tid}/encerrar", {}, token_sessao=tok_cli)
        exigir(estado_da_sessao(banco, tid)[0] == "encerrada", "o dono da sessao encerra a propria")
        parar = ordens_do_bordo(banco, "bancada", "parar")
        exigir(len(parar) == 1 and parar[0][2] == "cam-01",
               f"agora sim a camera para (ordem de parar enfileirada) ({parar})")
        s, j = pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)
        exigir(s == 200 and any(o["acao"] == "parar" for o in j.get("ordens") or []),
               f"o bordo recebe o pedido de parar ({j.get('ordens')})")
        pedir("POST", base + f"/api/ordens/{parar[0][0]}/resultado", {"estado": "atendida"}, token_bordo=TOKEN)
        # e o caso "tela fechada / computador desligado": ninguem bate, a sessao morre sozinha
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01", "segundos_max": 300},
                     token_sessao=tok_cli)
        tid_b = (j.get("transmissao") or {}).get("id", "")
        mexer(banco, "UPDATE transmissoes SET batimento_em=? WHERE id=?", (agora_iso(-120), tid_b))
        r = esperar_vigia(banco, tid_b, {"encerrada"})
        exigir(r and r[0] == "encerrada" and "fechada" in (r[1] or ""),
               f"sem batimento (tela fechada/computador desligado) a sessao morre ({r})")
        exigir(len(ordens_do_bordo(banco, "bancada", "parar")) == 2,
               f"e a camera para de verdade ({ordens_do_bordo(banco, 'bancada', 'parar')})")

        # --- 7) tempo maximo: estoura -> para e o cliente inicia de novo ----------------------------
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-02", "segundos_max": 300},
                     token_sessao=tok_cli)
        tid3 = (j.get("transmissao") or {}).get("id", "")
        con = sqlite3.connect(banco)
        con.execute("UPDATE transmissoes SET estado='no_ar' WHERE id=?", (tid3,))
        con.commit()
        con.close()
        mexer(banco, "UPDATE transmissoes SET batimento_em=?, termina_em=? WHERE id=?",
              (agora_iso(), agora_iso(-1), tid3))
        r = esperar_vigia(banco, tid3, {"expirada"})
        exigir(r and r[0] == "expirada" and "acabou" in (r[1] or ""),
               f"ao estourar o tempo a transmissao para e o cliente inicia de novo ({r})")
        exigir(not [o for o in ordens_do_bordo(banco, "bancada") if o[1] == "iniciar" and o[4] and "reinicia" in o[4]],
               "nao existe reinicio automatico (quem inicia de novo e' o cliente)")

        # --- 8) GRAVANDO no lado terra: o tempo NAO corta --------------------------------------------
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-02", "segundos_max": 300},
                     token_sessao=tok_cli2)
        tid4 = (j.get("transmissao") or {}).get("id", "")
        # a gravacao de verdade mora no lado terra: sem fluxo no ar, ela NAO pode ser dada como boa
        # (fluxo que nao existe na maquina: nunca ha' duvida sobre o que esta' no ar na bancada)
        mexer(banco, "UPDATE transmissoes SET fluxo_id=? WHERE id=?", ("cam-que-nao-existe", tid4))
        s, j = pedir("POST", base + f"/api/transmissao/{tid4}/gravando", {"gravando": True}, token_sessao=tok_cli2)
        exigir(s == 422 and j.get("gravando") is False and "erro" in j,
               f"sem fluxo no ar a gravacao e' recusada com o motivo, nao fingida ({s} {j.get('erro','')[:80]})")
        exigir(estado_da_sessao(banco, tid4)[2] == 0, "a bandeira de gravacao nao fica ligada")
        s, j = pedir("GET", base + f"/api/transmissao?embarcacao=bancada", token_sessao=tok_cli2)
        achou = [t for t in (j.get("abertas") or []) + (j.get("historico") or []) if t.get("id") == tid4]
        exigir(bool(achou), f"a sessao aparece na tela (abertas/historico) "
                            f"{[t.get('id') for t in (j.get('abertas') or []) + (j.get('historico') or [])]}")
        exigir(achou[0].get("gravacao", {}).get("tem") is False
               and achou[0].get("gravacao", {}).get("gravando") is False,
               f"a tela diz que NAO ha' gravacao (sem arquivo): {achou[0].get('gravacao') if achou else None}")
        # quem decide que grava e' o lado terra: aqui a bandeira e' posta direto para provar a regra do tempo
        mexer(banco, "UPDATE transmissoes SET gravando=1 WHERE id=?", (tid4,))
        mexer(banco, "UPDATE transmissoes SET batimento_em=?, termina_em=? WHERE id=?",
              (agora_iso(), agora_iso(-1), tid4))
        time.sleep(7)
        r = estado_da_sessao(banco, tid4)
        exigir(r[0] in ("pedida", "no_ar") and r[2] == 1,
               f"gravando, o tempo NAO corta a transmissao ({r})")
        mexer(banco, "UPDATE transmissoes SET gravando=0 WHERE id=?", (tid4,))
        r = esperar_vigia(banco, tid4, {"expirada"})
        exigir(r[0] == "expirada", f"sem gravar, o tempo volta a cortar ({r})")

        # --- 9) erro do bordo fecha a sessao com a verdade do bordo ---------------------------------
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01", "segundos_max": 300},
                     token_sessao=tok_cli)
        tid5 = (j.get("transmissao") or {}).get("id", "")
        s, j = pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)
        oid5 = [o["id"] for o in j.get("ordens") or [] if o["transmissao_id"] == tid5][0]
        s, j = pedir("POST", base + f"/api/ordens/{oid5}/resultado",
                     {"estado": "erro", "resultado": "camera cam-01: iniciar falhou (dispositivo ocupado)"},
                     token_bordo=TOKEN)
        r = estado_da_sessao(banco, tid5)
        exigir(r[0] == "erro" and "dispositivo ocupado" in (r[1] or ""),
               f"erro do bordo fecha a sessao com o motivo do bordo ({r})")

        # --- 9b) GRAVACAO: baixar so' quem ve a sessao, e o arquivo e' o que esta' no disco ---------
        grav = pathlib.Path(env["LECSOR_GRAVACOES_DIR"])
        grav.mkdir(parents=True, exist_ok=True)
        (grav / f"{tid4}.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"GRAVACAO-REAL-EM-TESTE" * 100)
        combinado = b"\x00\x00\x00\x18ftypisom" + b"GRAVACAO-REAL-EM-TESTE" * 100
        s, dados = baixar(base + f"/api/gravacoes/{tid4}", tok_cli2)
        exigir(s == 200 and dados == combinado,
               f"o dono da sessao baixa a gravacao, byte a byte ({s}, {len(dados)} B)")
        s, _ = baixar(base + f"/api/gravacoes/{tid4}", tok_cli)
        exigir(s == 403, f"outro cliente NAO baixa a gravacao alheia ({s})")
        s, _ = baixar(base + f"/api/gravacoes/{tid5}", tok_cli2)
        exigir(s == 403, f"sessao de outro cliente nem chega a saber se tem gravacao ({s})")
        s, j = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-01"},
                     token_sessao=tok_cli2)
        tid6 = (j.get("transmissao") or {}).get("id", "")
        exigir(bool(tid6), f"a operacao abre uma sessao para testar o 404 ({s} {j})")
        s, _ = baixar(base + f"/api/gravacoes/{tid6}", tok_cli2)
        exigir(s == 404, f"sessao sem gravacao devolve 404, nao arquivo vazio ({s})")
        s, _ = baixar(base + "/api/gravacoes/nao-existe-123", tok_cli2)
        exigir(s == 404, f"transmissao que nao existe devolve 404 ({s})")

        # --- 10) o historico fica (nada e' apagado) -------------------------------------------------
        s, j = pedir("GET", base + "/api/transmissao?embarcacao=bancada", token_sessao=tok_cli)
        hist = j.get("historico") or []
        ids_hist = {t["id"] for t in hist}
        exigir({tid, tid2, tid3, tid4, tid5} <= ids_hist,
               f"todas as transmissoes ficam no historico ({len(hist)} linhas)")
        motivos = {t["id"]: t.get("motivo") or "" for t in hist}
        exigir(all(motivos.get(x) for x in (tid, tid2, tid3, tid4, tid5)),
               "cada transmissao fechada tem o motivo no historico")
        exigir(all("senha" not in json.dumps(t).lower() and "rtsp" not in json.dumps(t).lower() for t in hist),
               "o historico nao devolve endereco nem credencial de camera")

        # --- 11) a OPERACAO ve os pedidos abertos e cancela (plano, Fase 2 P1) ----------------------
        s, j = pedir("GET", base + "/api/transmissao/pedidos", token_sessao=tok_cli)
        exigir(s == 403, f"o CLIENTE nao ve a lista da operacao ({s})")
        s, _junto = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": "cam-02"},
                          token_sessao=tok_cli2)
        tid7 = (_junto.get("transmissao") or {}).get("id", "")
        exigir(bool(tid7), f"o cliente pediu a cam-02 para o teste do cancelamento ({s})")
        s, j = pedir("GET", base + "/api/transmissao/pedidos", token_sessao=tok_op)
        exigir(s == 200, f"a operacao ve os pedidos abertos ({s} {j.get('erro')})")
        pedidos = j.get("pedidos") or []
        exigir(any(p["id"] == tid7 for p in pedidos), f"a lista traz o pedido do cliente ({len(pedidos)})")
        exigir(all("senha" not in json.dumps(p).lower() and "rtsp" not in json.dumps(p).lower() for p in pedidos),
               "a lista da operacao nao devolve credencial nem endereco de camera")
        s, j = pedir("POST", base + f"/api/transmissao/{tid7}/cancelar", {}, token_sessao=tok_op)
        exigir(s == 200 and j.get("cancelada") is True, f"a operacao cancela o pedido ({s} {j})")
        exigir(j.get("camera_mandada_parar") is True,
               "sem ninguem mais vendo, o bordo recebe a ordem de PARAR")
        s, j2 = pedir("GET", base + "/api/transmissao?embarcacao=bancada", token_sessao=tok_op)
        linha7 = [x for x in (j2.get("historico") or []) if x["id"] == tid7]
        exigir(bool(linha7) and linha7[0]["estado"] == "cancelada", "o historico guarda 'cancelada'")
        exigir("operacao" in (linha7[0].get("motivo") or "").lower(),
               f"o historico diz QUEM cancelou ({linha7[0].get('motivo')})")
        s, j = pedir("POST", base + f"/api/transmissao/{tid7}/cancelar", {}, token_sessao=tok_op)
        exigir(s == 200 and j.get("cancelada") is False, f"cancelar de novo nao faz nada ({s} {j})")
        s, j = pedir("POST", base + f"/api/transmissao/{tid7}/cancelar", {}, token_sessao=tok_cli)
        exigir(s == 403, f"o CLIENTE nao cancela pela porta da operacao ({s})")
        s, j = pedir("POST", base + "/api/transmissao/nao-existe/cancelar", {}, token_sessao=tok_op)
        exigir(s == 404, f"cancelar o que nao existe devolve 404 ({s})")

        # --- 12) TETO DO PRODUTO: so' o admin define, e o cliente nao passa dele (Fase 3 P2) --------
        s, j = pedir("POST", base + "/api/transmissao/teto", {"tempo_maximo_s": 1800}, token_sessao=tok_op)
        exigir(s == 403, f"a OPERACAO nao define o teto do produto ({s})")
        s, j = pedir("POST", base + "/api/transmissao/teto", {"tempo_maximo_s": 123}, token_sessao=tok_adm)
        exigir(s == 422, f"teto fora da lista e' recusado, nao arredondado ({s})")
        s, j = pedir("POST", base + "/api/transmissao/teto", {"tempo_maximo_s": 300}, token_sessao=tok_adm)
        exigir(s == 200 and j.get("teto_do_produto_s") == 300, f"o admin define o teto ({s} {j})")
        s, j = pedir("GET", base + "/api/transmissao?embarcacao=bancada", token_sessao=tok_cli)
        exigir(j.get("tempos") == [300], f"o cliente ve a lista JA' cortada pelo teto ({j.get('tempos')})")
        exigir(j.get("teto_do_produto_s") == 300, "a tela do cliente sabe qual e' o teto do produto")
        s, j = pedir("POST", base + "/api/transmissao/config", {"tempo_maximo_s": 1800}, token_sessao=tok_cli)
        exigir(s == 422 and "liberado" in (j.get("erro") or ""),
               f"o cliente NAO configura acima do teto ({s} {j})")
        s, j = pedir("POST", base + "/api/transmissao/iniciar",
                     {"camera_id": "cam-02", "segundos_max": 3600}, token_sessao=tok_cli)
        linha_teto = j.get("transmissao") or {}
        exigir(s == 201 and linha_teto.get("segundos_max") == 300,
               f"pedido acima do teto e' cortado no teto ({s}, pediu 3600, saiu {linha_teto.get('segundos_max')})")
        exigir(j.get("cortado_pelo_teto_do_produto") is True,
               "o pedido diz que foi cortado pelo teto do produto")
        s, j = pedir("POST", base + "/api/transmissao/teto", {"tempo_maximo_s": 0}, token_sessao=tok_adm)
        exigir(s == 200 and j.get("teto_do_produto_s") == 0, f"o admin tira o teto ({s} {j})")
        s, j = pedir("GET", base + "/api/transmissao?embarcacao=bancada", token_sessao=tok_cli)
        tempos_volta = j.get("tempos") or []
        exigir(300 in tempos_volta and 7200 in tempos_volta,
               f"sem teto, a lista volta inteira ({tempos_volta})")
    finally:
        api.terminate()
        try:
            api.wait(timeout=15)
        except Exception:
            api.kill()
        log.close()

    print()
    if falhas:
        print(f"FALHAS ({len(falhas)}):")
        for f in falhas:
            print(" -", f)
        return 1
    print("TUDO OK — o cliente abre a transmissao pela web, a ordem vai ao bordo e o corte e' por sessao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
