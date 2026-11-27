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

            # ---- 8. o admin DENUNCIA o app de captura ANTIGO (dono, 26/11/2026) -------------------
            # O dono viu "gravação contínua: publicada LIGADA — o bordo: ligada (ligada, mas esta maquina
            # nao tem dispositivo de video configurado (LECSOR_HD_DISPOSITIVO): nada sera' gravado)" e
            # concluiu, com razao, que as imagens do radar nao estavam sendo gravadas. O texto era da
            # versao ANTIGA (0.25.0) e NADA na tela dizia isso. Aqui: um bordo velho (v0.0.9) e' acusado
            # na tela do admin, com as duas versoes.
            versao_daqui = (RAIZ / "VERSION").read_text(encoding="utf-8").strip()
            executa(terra_db, """INSERT INTO saude_bordo (embarcacao_id,recebido_em,maquina,versao_app,estado,retrato)
                                 VALUES (?,?,?,?,?,?)""",
                    (EMB, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "PC-ANTIGO", "0.0.9",
                     "ok", json.dumps({"versao_app": "0.0.9", "maquina": "PC-ANTIGO"})))
            st, _ = pedir("POST", base_terra + "/api/config",
                          {"embarcacao_id": EMB, "camera_id": "", "chave": "gravacao_continua", "valor": "1"},
                          cookie=admin)
            exigir(st == 201, f"o admin publica a gravacao continua (HTTP {st}) — a tela do dono")
            # A tela lista EMPRESAS; o cartao da embarcacao aparece depois de ABRIR a empresa dela
            # (pode haver mais de uma empresa — abre-se a que tem a nossa).
            cartao = f'.cartao-embarcacao[data-emb="{EMB}"]'
            pag.click('button.item[data-tela="empresas"]')
            pag.wait_for_selector(".cartao-empresa", timeout=20000)
            achou = False
            for i in range(pag.locator(".cartao-empresa").count()):
                pag.locator(".cartao-empresa").nth(i).locator("text=Abrir").first.click()
                try:
                    pag.wait_for_selector(cartao, timeout=8000)
                    achou = True
                    break
                except Exception:  # noqa: BLE001
                    pag.click('button.item[data-tela="empresas"]')
                    pag.wait_for_selector(".cartao-empresa", timeout=10000)
            exigir(achou, f"aberta a empresa da embarcacao {EMB} (o cartao aparece na tela do admin)")
            if not achou:
                nota("empresas na tela: " + " | ".join(pag.locator(".cartao-empresa").all_inner_texts())[:300])
                return 1
            pag.wait_for_function(
                "s => /publicada LIGADA/.test((document.querySelector(s) || {}).textContent || '')",
                arg=cartao, timeout=20000)
            texto2 = pag.inner_text(cartao)
            exigir("atualizar o app de captura" in texto2,
                   "a tela do admin ACUSA o PC de captura antigo (com o que fazer: atualizar)")
            exigir("0.0.9" in texto2 and versao_daqui in texto2,
                   f"e mostra as DUAS versoes (bordo v0.0.9 < publicada v{versao_daqui})")
            exigir("publicada LIGADA" in texto2,
                   "junto da linha da gravacao continua (o texto exato que o dono viu)")
            exigir(not erros, "sem erro de javascript na tela de empresas: " + "; ".join(erros[:2]))
            # 7) FONTE UNICA do caminho do estado do agente: a saude TEM de ler onde o agente escreve.
            #    Havia dois padroes (saude: ground/agente-vivo.json; agente: ordens/agente-vivo.json) e a
            #    saude dizia "o agente nunca escreveu o estado" numa maquina que estava trabalhando.
            guardado = os.environ.pop("LECSOR_AGENTE_ESTADO", None)
            sys.path.insert(0, str(RAIZ / "ground"))
            import agente_de_ordens as mod_agente
            import saude_do_bordo as mod_saude
            padrao = mod_agente.caminho_do_vivo()
            padrao.parent.mkdir(parents=True, exist_ok=True)
            padrao.write_text(json.dumps({"em": time.strftime("%Y-%m-%dT%H:%M:%S"), "rodadas": 1}),
                              encoding="utf-8")
            try:
                vivo = mod_saude._agente()
            finally:
                if guardado is not None:
                    os.environ["LECSOR_AGENTE_ESTADO"] = guardado
            exigir(vivo.get("laco_vivo") is True,
                   f"a saude le onde o AGENTE escreve ({padrao}) e ve o laco vivo: {vivo}")

            # ---- 9. a TELEMETRIA do PC de captura no CARTÃO: DISCO e REDE (dono, 27/11/2026, 0.28.0) ----
            # "a telemetria do pc de captura precisa estar evidente no dashboard do admin, note que não tem
            #  disco e nem rede" · "precisamos definir qual disco e quanto dele será utilizado".
            agora9 = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            retrato9 = {
                "gerado_em": agora9, "cpu_pct": 19.2, "memoria_pct": 60.2, "versao_app": versao_daqui,
                "discos": [
                    {"nome": "hd do radar", "caminho": "D:\\", "total_gb": 931.5, "livre_gb": 400.0,
                     "usado_pct": 57.1, "blocos": 12, "bytes": 1500000000, "mais_antigo": "2026-11-27T09:00:00",
                     "cota_gb": 50.0, "origem_da_escolha": "admin"},
                    {"nome": "aplicativo", "caminho": "C:\\", "total_gb": 254.0, "livre_gb": 194.8,
                     "usado_pct": 23.3},
                ],
                "rede": {"interfaces": [{"nome": "Ethernet", "enviado_mb": 3067.0, "recebido_mb": 412.0,
                                         "enviado_mbps": 3.067, "recebido_mbps": 0.412}],
                         "total": {"enviado_mbps": 3.067, "recebido_mbps": 0.412, "taxa_mbps": 3.48}},
                "gravacao_continua": {"ligada": True, "gravando": True, "disco": "D:\\", "cota_gb": 50.0},
            }
            executa(terra_db, """INSERT INTO saude_bordo (embarcacao_id,recebido_em,maquina,versao_app,estado,retrato)
                                 VALUES (?,?,?,?,?,?)""",
                    (EMB, agora9, "PC-CAPTURA-PROVA", versao_daqui, "ok", json.dumps(retrato9)))
            pag.click('button.item[data-tela="empresas"]')
            pag.wait_for_selector(".cartao-empresa", timeout=20000)
            for i in range(pag.locator(".cartao-empresa").count()):
                pag.locator(".cartao-empresa").nth(i).locator("text=Abrir").first.click()
                try:
                    pag.wait_for_selector(cartao, timeout=8000)
                    break
                except Exception:  # noqa: BLE001
                    pag.click('button.item[data-tela="empresas"]')
                    pag.wait_for_selector(".cartao-empresa", timeout=10000)
            pag.wait_for_function(
                "s => /disco do radar/.test((document.querySelector(s) || {}).textContent || '')",
                arg=cartao, timeout=20000)
            t9 = pag.inner_text(cartao)
            exigir("disco do radar" in t9 and "400.0 GB livres de 931.5 GB" in t9 and "57.1% usado" in t9,
                   "o cartão mostra o DISCO da gravação: livre de total e % usado (era 'HD do radar —')")
            exigir("rede ↑3.1 / ↓0.4 Mbps agora" in t9,
                   "o cartão mostra a REDE medida agora (o dono: 'não tem disco e nem rede')")
            exigir("cota 50 GB (escolha do admin)" in t9,
                   "e a COTA escolhida, dita como escolha do admin")

            # ---- 10. QUAL DISCO E QUANTO DELE: o admin escolhe da lista MEDIDA pelo próprio PC ---------
            sel9 = f"#hd-disco-{EMB}"
            cota9 = f"#hd-cota-{EMB}"
            exigir(pag.locator(sel9).count() == 1 and pag.locator(cota9).count() == 1,
                   "com DOIS discos medidos aparece o seletor de disco e o campo da cota")
            opcoes = pag.locator(sel9 + " option").all_inner_texts()
            exigir(len(opcoes) == 3 and any("D:\\" in o for o in opcoes) and any("C:\\" in o for o in opcoes),
                   f"o seletor lista os discos que o PC de captura MEDIU (+ o padrão): {opcoes}")
            pag.select_option(sel9, "C:\\")
            pag.fill(cota9, "20")
            pag.locator(cartao).locator("text=aplicar no PC de captura").first.click()
            time.sleep(2.5)
            escolhido = todos(terra_db, """SELECT chave,valor FROM config_bordo
                                           WHERE embarcacao_id=? AND camera_id='' AND chave IN ('hd_disco','hd_cota_gb')
                                           ORDER BY chave""", (EMB,))
            mapa = {x["chave"]: x["valor"] for x in escolhido}
            exigir(mapa.get("hd_disco") == "C:\\" and mapa.get("hd_cota_gb") == "20",
                   f"a escolha do disco e da cota vai publicada para o bordo: {mapa}")
            exigir(bool(todos(terra_db, "SELECT 1 FROM auditoria_acesso WHERE acao='hd_escolhido'")),
                   "e fica na trilha de auditoria quem escolheu o disco e a cota")
            exigir(not erros, "sem erro de javascript depois da escolha do HD: " + "; ".join(erros[:2]))
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
