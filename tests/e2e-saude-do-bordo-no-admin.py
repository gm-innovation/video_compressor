#!/usr/bin/env python3
"""A SAUDE DO COMPUTADOR DE CAPTURA CHEGA AO ADMIN (0.8.0, Fase 5) — prova de ponta a ponta.

Dono (19/11/2026): "vamos incluir tambem uma forma de o app de captura enviar para o admin dados de saude
para monitorarmos se esta tudo okay ou se ha algum problema que devemos corrigir ou acompanhar".

API do lado terra + API do bordo + o AGENTE de verdade (que e' quem envia o retrato), mais o painel aberto
num navegador de verdade. O que se prova:

  1) o bordo reporta sozinho (o agente envia no boot e no ritmo de `LECSOR_ESPERA_DA_SAUDE`) e terra guarda;
  2) o painel classifica cada sinal com LIMIAR declarado e diz "o que fazer";
  3) bordo que NUNCA reportou nao vira verde: e' PROBLEMA ("silencio nao e' saude");
  4) disco acima do limiar vira PROBLEMA (e o aviso aponta o anel do HD, nao um acesso ao bordo);
  5) a serie guarda 30 dias e o corte fica registrado (nada some sem explicacao);
  6) a tela "Saude do bordo" do admin abre com o semaforo e sem erro de javascript.

    python tests/e2e-saude-do-bordo-no-admin.py
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
TOKEN = "token-de-ingestao-do-teste"
EMB = "bancada"
SENHA = "senha-do-admin-de-teste"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(metodo, url, corpo=None, cookie="", token=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            return f.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_DESTINO_SRT", "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO"):
        env.pop(k, None)
    env.update(env_extra)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: "
                               + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-700:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def sessao_de(con, uid, email, papel):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, None, senha, salt))
    tok = "tok-" + uid
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    return tok


def executa(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def todos(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def rodar_agente(bordo_db: pathlib.Path, base_terra: str, p_bordo: int, tmp: pathlib.Path) -> str:
    env = dict(os.environ)
    env.update({"LECSOR_BANCO": str(bordo_db), "LECSOR_LADO_TERRA_API": base_terra,
                "LECSOR_TOKEN_INGESTAO": TOKEN, "LECSOR_EMBARCACAO": EMB,
                "LECSOR_PORTA_LOCAL": str(p_bordo), "LECSOR_PORTA_API": str(p_bordo),
                "LECSOR_ESPERA_DA_CONFIG": "2", "LECSOR_ESPERA_DA_FLAG": "1",
                "LECSOR_ESPERA_DA_SAUDE": "10", "LECSOR_CONFIG_ESTADO": str(tmp / "config_aplicada.json"),
                "LECSOR_ORDENS_ESTADO": str(tmp / "ligados.json"),
                "LECSOR_AGENTE_ESTADO": str(tmp / "agente-vivo.json"),
                "LECSOR_GRAVACOES_DIR": str(tmp / "gravacoes"), "PYTHONIOENCODING": "utf-8"})
    log = tmp / "agente.log"
    with log.open("ab") as f:
        subprocess.run([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py"), "--uma-vez"],
                       cwd=str(RAIZ), env=env, stdout=f, stderr=subprocess.STDOUT, timeout=240)
    return log.read_text(errors="replace")


def _chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-saude-"))
    p_terra, p_bordo = porta_livre(), porta_livre()
    terra_db, bordo_db = tmp / "terra.db", tmp / "bordo.db"
    procs: list = []
    try:
        base_terra = f"http://127.0.0.1:{p_terra}"
        procs.append(sobe_api(terra_db, p_terra, {"LECSOR_LADO_TERRA_API": base_terra,
                                                  "LECSOR_BIND": "127.0.0.1", "LECSOR_TOKEN_INGESTAO": TOKEN}))
        procs.append(sobe_api(bordo_db, p_bordo, {"LECSOR_LADO_TERRA_API": base_terra,
                                                  "LECSOR_BIND": "127.0.0.1", "LECSOR_TOKEN_INGESTAO": TOKEN,
                                                  "LECSOR_EMBARCACAO": EMB, "LECSOR_PORTA_API": str(p_bordo)}))
        for banco in (terra_db, bordo_db):
            executa(banco, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
            executa(banco, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,'lecsor','Bancada de testes')", (EMB,))
        con = sqlite3.connect(str(terra_db))
        admin = sessao_de(con, "adm-saude", "admin@lecsor.test", "admin")
        con.close()

        # ---- 1. sem NINGUEM ter reportado, o painel nao finge saude
        st, s0 = pedir("GET", base_terra + f"/api/saude-do-bordo?embarcacao_id={EMB}", cookie=admin)
        exigir(st == 200 and (s0.get("atual") or {}).get("estado") == "problema",
               f"bordo que nunca reportou e' PROBLEMA, nao verde ({st} {(s0.get('atual') or {}).get('estado')!r})")
        exigir(any("nunca reportou" in str(s.get("o_que_fazer")) or "nunca reportou" in str(s.get("sinal"))
                   for s in ((s0.get("atual") or {}).get("sinais") or [])),
               "e a tela diz o que fazer (app aberto? rede?)")

        # ---- 2. o BORDO reporta sozinho (agente de verdade): terra guarda e classifica
        log = rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        nota("agente: " + " | ".join(l for l in log.splitlines() if "saude" in l.lower())[:200] or "     (sem linha de saude no log)")
        guardados = todos(terra_db, "SELECT * FROM saude_bordo WHERE embarcacao_id=?", (EMB,))
        exigir(len(guardados) >= 1, f"terra recebeu o retrato do bordo ({len(guardados)} linha(s))")
        st, s1 = pedir("GET", base_terra + f"/api/saude-do-bordo?embarcacao_id={EMB}", cookie=admin)
        atual = s1.get("atual") or {}
        exigir(bool(atual.get("recebido_em")) and bool(atual.get("sinais")),
               f"o painel mostra o retrato classificado ({len(atual.get('sinais') or [])} sinal(is))")
        sinais = {x["sinal"]: x for x in (atual.get("sinais") or [])}
        exigir("ffmpeg" in sinais and "agente" in sinais and "disco_pct" in sinais,
               f"os sinais de captura estao la': {sorted(sinais)[:6]}")
        exigir(bool(sinais) and all(x.get("limiar") for x in sinais.values()),
               "cada sinal diz o LIMIAR (sem limiar o semaforo seria adivinhacao)")
        nota("semaforo do bordo agora: " + atual.get("estado", "?"))

        # ---- 3. disco acima do limiar vira PROBLEMA e aponta o anel do HD do radar
        retrato_ruim = {"maquina": "pc-de-teste", "versao_app": "0.8.0",
                        "discos": [{"nome": "hd do radar", "caminho": "D:\\hd", "usado_pct": 97.5,
                                    "livre_gb": 12.0, "blocos": 144, "mais_antigo": "2026-11-18T02:00:00-03:00"}],
                        "ffmpeg": {"presente": True}, "agente": {"laco_vivo": True, "idade_s": 3},
                        "mediamtx": {"ativo": True, "caminhos": 2},
                        "banco": {"ok": True, "erros_24h": 0, "pedidos_pendentes": 0}}
        st, _ = pedir("POST", base_terra + "/api/saude-do-bordo",
                      {"embarcacao_id": EMB, "retrato": retrato_ruim}, token=TOKEN)
        exigir(st == 200, f"o bordo envia um retrato com disco cheio (HTTP {st})")
        st, s2 = pedir("GET", base_terra + f"/api/saude-do-bordo?embarcacao_id={EMB}", cookie=admin)
        a2 = s2.get("atual") or {}
        s_disco = next((x for x in (a2.get("sinais") or []) if x["sinal"] == "disco_pct"), {})
        exigir(a2.get("estado") == "problema" and s_disco.get("estado") == "problema",
               f"disco com 97,5% usado vira PROBLEMA (estado geral {a2.get('estado')!r})")
        exigir("anel" in str(s_disco.get("o_que_fazer")),
               "e o aviso fala do anel do HD (o que grava por cima do mais antigo)")
        trilha = todos(terra_db, """SELECT acao,alvo FROM auditoria_acesso
                                    WHERE acao LIKE '%saude_do_bordo%' ORDER BY id DESC LIMIT 10""")
        exigir(any("problema" in str(l["alvo"]) for l in trilha),
               f"a trilha guarda a VIRADA do semaforo ({[l['alvo'] for l in trilha][:2]})")

        # ---- 4. nada de segredo no retrato (defesa em profundidade em terra)
        st, _ = pedir("POST", base_terra + "/api/saude-do-bordo",
                      {"embarcacao_id": EMB, "retrato": {"maquina": "pc", "token": "NAO-PODE-SUBIR",
                                                         "senha": "NAO-PODE-SUBIR"}}, token=TOKEN)
        guardado = todos(terra_db, "SELECT retrato FROM saude_bordo WHERE embarcacao_id=? ORDER BY id DESC LIMIT 1", (EMB,))
        exigir("NAO-PODE-SUBIR" not in (guardado[0]["retrato"] if guardado else ""),
               "token/senha no corpo do retrato sao descartados antes de gravar")

        # ---- 5. retencao de 30 dias, com o corte registrado
        velho = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40)).isoformat(timespec="seconds")
        executa(terra_db, """INSERT INTO saude_bordo (embarcacao_id,recebido_em,maquina,versao_app,estado,retrato)
                             VALUES (?,?,?,?,?,?)""", (EMB, velho, "antigo", "0.7.0", "ok", "{}"))
        antes = len(todos(terra_db, "SELECT 1 FROM saude_bordo WHERE recebido_em < ?",
                          ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec="seconds"),)))
        pedir("POST", base_terra + "/api/saude-do-bordo", {"embarcacao_id": EMB, "retrato": {"maquina": "pc"}},
              token=TOKEN)
        depois = len(todos(terra_db, "SELECT 1 FROM saude_bordo WHERE recebido_em < ?",
                           ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec="seconds"),)))
        cortes = todos(terra_db, "SELECT * FROM saude_bordo_corte ORDER BY cortado_em DESC LIMIT 1")
        exigir(antes >= 1 and depois == 0, f"a serie guarda 30 dias (antes {antes}, depois {depois})")
        exigir(bool(cortes) and int(cortes[0]["quantos"]) >= 1,
               f"o corte fica REGISTRADO ({cortes[0]['quantos'] if cortes else 0} linha(s), regra {cortes[0]['regra'] if cortes else '-'})")

        # ---- 6. so' a operacao ve; de fora, nao
        st, _ = pedir("GET", base_terra + f"/api/saude-do-bordo?embarcacao_id={EMB}")
        exigir(st == 200, "o proprio computador de captura le' sua saude pela rota LOCAL (nada de porta "
                          "aberta: e' o mesmo endereco do app a bordo)")
        con = sqlite3.connect(str(terra_db))
        cli = sessao_de(con, "cli-saude", "cliente@lecsor.test", "cliente")
        con.close()
        st, _ = pedir("GET", base_terra + f"/api/saude-do-bordo?embarcacao_id={EMB}", cookie=cli)
        exigir(st == 403, f"cliente NAO ve a saude do computador de captura (HTTP {st})")

        # ---- 7. a TELA do admin abre com o semaforo
        from playwright.sync_api import sync_playwright
        erros: list[str] = []
        with sync_playwright() as p:
            nav = p.chromium.launch(executable_path=_chromium())
            pag = nav.new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.goto(base_terra + "/admin")
            pag.fill("#email", "admin@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector("#sistema:not(.oculto)", timeout=20000)
            pag.click('button.item[data-tela="saude_bordo"]')
            pag.wait_for_function("() => /Sinal|sinal/.test(document.getElementById('tela').textContent)", timeout=20000)
            texto = pag.inner_text("#tela")
            exigir("Bancada de testes" in texto, "a tela mostra a embarcação")
            exigir(any(t in texto for t in ("tudo ok", "atenção", "problema")),
                   "a tela mostra o semáforo")
            exigir("O que fazer" in texto, "e a coluna 'O que fazer' (o admin nao fica sem próximo passo)")
            exigir(not erros, "sem erro de javascript na tela de saude do bordo: " + "; ".join(erros[:2]))
            nav.close()
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)

    print()
    if falhas:
        print(f"FALHOU ({len(falhas)})")
        for f in falhas:
            print("  - " + f)
        return 1
    print("TUDO OK — a saude do bordo chega ao admin, com semaforo, limiar e o que fazer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
