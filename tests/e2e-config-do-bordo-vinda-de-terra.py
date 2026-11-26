#!/usr/bin/env python3
"""A CONFIGURACAO CHEGA DO LADO TERRA PARA O BORDO (0.8.0, Fase 2) — prova de ponta a ponta.

Palavras do dono (19/11/2026): "eu configuraria tudo pelo meu usuario admin, pela premissa de nao enviar
nada para bordo, o app a bordo precisa buscar o tempo todo as atualizacoes enviadas pelo cliente e pelo
admin".

API de verdade nos dois lados + o AGENTE de verdade (`--uma-vez`). O que se prova:
  1) o admin PUBLICA configuracao em terra (alvo por camera, teto da embarcacao) e a versao sobe;
  2) o bordo OLHA (`GET /api/config-desejada`) e aplica SO' a diferenca pela API LOCAL;
  3) o efeito acontece no banco DO BORDO (alvo da camera, teto local) e o bordo CONFIRMA;
  4) rodar de novo NAO repete o que ja' estava aplicado (nao martela o lado terra);
  5) chave que o bordo nao consegue EXECUTAR volta com motivo — e o que estava no ar nao muda;
  6) publicacao nova (versao nova) e' aplicada na proxima rodada.

    python tests/e2e-config-do-bordo-vinda-de-terra.py
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


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def porta_livre(excluir=None) -> int:
    excluir = excluir or set()
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        if p not in excluir:
            return p


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
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra)
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env,
                            stdout=(banco.parent / f"api-{porta}.log").open("wb"),
                            stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: "
                               + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-600:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def sessao_de(con, uid, email, papel="admin", cliente_id=""):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id or None, senha, salt))
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


def um(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else {}
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
                "LECSOR_ESPERA_DA_CONFIG": "2", "LECSOR_CONFIG_ESTADO": str(tmp / "config_aplicada.json"),
                "LECSOR_ORDENS_ESTADO": str(tmp / "ligados.json"), "PYTHONIOENCODING": "utf-8"})
    log = tmp / "agente.log"
    with log.open("wb") as f:
        subprocess.run([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py"), "--uma-vez"],
                       cwd=str(RAIZ), env=env, stdout=f, stderr=subprocess.STDOUT, timeout=180)
    return log.read_text(errors="replace")


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-config-"))
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
        base_bordo = f"http://127.0.0.1:{p_bordo}"

        for banco in (terra_db, bordo_db):
            executa(banco, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
            executa(banco, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,'lecsor','Bancada')", (EMB,))
            executa(banco, """INSERT OR REPLACE INTO cameras
                                (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                                VALUES ('cam-01',?,'Proa','cam-01','bordo',1,'','','rtsp','','')""", (EMB,))
        con = sqlite3.connect(str(terra_db))
        admin = sessao_de(con, "adm-config", "admin@lecsor.test", "admin")
        con.close()

        # 1) o admin PUBLICA (terra valida na borda)
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "alvo_kbps", "valor": "300"},
                      cookie=admin)
        exigir(st == 201 and r.get("versao") == 1, f"admin publica alvo_kbps=300 (v{r.get('versao')}, HTTP {st})")
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "", "chave": "teto_s", "valor": "1800"},
                      cookie=admin)
        exigir(st == 201 and r.get("versao") == 1, "admin publica teto_s=1800 para a embarcacao")
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "alvo_kbps", "valor": "99999"},
                      cookie=admin)
        exigir(st == 422, f"valor fora do produto e' recusado JÁ em terra (HTTP {st})")
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "nao_existe", "valor": "1"},
                      cookie=admin)
        exigir(st == 422, "chave desconhecida e' recusada em terra")
        st, r = pedir("POST", base_terra + "/api/config", {"embarcacao_id": EMB, "chave": "teto_s", "valor": "10"},
                      cookie=admin)
        exigir(st == 422, "teto fora da faixa do produto e' recusado em terra")

        _, cfg = pedir("GET", base_terra + f"/api/config?embarcacao_id={EMB}", cookie=admin)
        exigir(cfg.get("versao") == 1 and len(cfg.get("chaves") or []) == 2,
               f"terra tem 2 chaves publicadas na v{cfg.get('versao')}")

        # 2) a FLAG e a CONFIG sao lidas pelo bordo (o agente de verdade)
        _, flag = pedir("GET", base_terra + f"/api/estado-desejado?embarcacao_id={EMB}", token=TOKEN)
        exigir(isinstance(flag.get("cameras"), list), "a flag continua respondendo (o desenho antigo nao quebrou)")
        _, desejo = pedir("GET", base_terra + f"/api/config-desejada?embarcacao_id={EMB}", token=TOKEN)
        exigir(desejo.get("versao") == 1 and len(desejo.get("chaves") or []) == 2,
               "o bordo le a configuracao publicada (com a versao)")
        st, _ = pedir("GET", base_terra + f"/api/config-desejada?embarcacao_id={EMB}")
        exigir(st == 401, f"sem token do bordo, a configuracao nao sai (HTTP {st})")

        log = rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        nota("agente (1a rodada): " + " | ".join(l for l in log.splitlines() if "config" in l.lower())[:400])
        alvo_bordo = um(bordo_db, "SELECT alvo FROM cameras WHERE id='cam-01'")
        # "300k": o campo `cameras.alvo` vai CRU para o `-b:v` do ffmpeg (a J8 do smoke mediu o defeito de
        # gravar so' "300": 300 BITS/s, video morto).
        exigir(alvo_bordo.get("alvo") == "300k",
               f"o bordo APLICOU o alvo no banco dele, no formato do ffmpeg (alvo={alvo_bordo.get('alvo')!r})")
        teto_local = um(bordo_db, "SELECT valor FROM config_local WHERE camera_id='' AND chave='teto_s'")
        exigir(teto_local.get("valor") == "1800", f"o bordo guardou o teto local ({teto_local.get('valor')!r})")

        aplicadas = {x["chave"]: x for x in todos(terra_db, "SELECT * FROM config_aplicada_bordo")}
        exigir(aplicadas.get("alvo_kbps", {}).get("valor") == "300",
               f"terra recebeu a confirmacao do alvo (v{aplicadas.get('alvo_kbps', {}).get('versao')})")
        exigir(aplicadas.get("teto_s", {}).get("valor") == "1800",
               "terra recebeu a confirmacao do teto")
        quando_1 = aplicadas.get("alvo_kbps", {}).get("atualizado_em", "")

        # 3) rodar de novo NAO repete (nao martela o lado terra)
        rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        depois = {x["chave"]: x for x in todos(terra_db, "SELECT * FROM config_aplicada_bordo")}
        exigir(depois.get("alvo_kbps", {}).get("atualizado_em") == quando_1,
               "a 2a rodada nao reaplica o que ja' estava aplicado (so' a diferenca)")

        # 4) chave que o bordo nao CONSEGUE EXECUTAR volta com MOTIVO — e o que esta' no ar nao muda.
        # (Na 0.23.0 a gravacao continua passou a ser APLICADA pelo bordo — ela virou chave de verdade,
        # por decisao do dono. O caminho da recusa COM MOTIVO segue provado: nesta bancada nao ha'
        # dispositivo de video, e o bordo conta isso em vez de fingir que gravou.)
        st, _ = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "", "chave": "gravacao_continua", "valor": "1"},
                      cookie=admin)
        exigir(st == 201, "terra aceita publicar gravacao_continua (o bordo e' quem decide se aplica)")
        rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        com_motivo = {x["chave"]: x for x in todos(terra_db, "SELECT * FROM config_aplicada_bordo WHERE motivo != ''")}
        exigir("gravacao_continua" in com_motivo and "dispositivo" in com_motivo["gravacao_continua"]["motivo"],
               f"o motivo chegou a terra: {com_motivo.get('gravacao_continua', {}).get('motivo')!r}")
        exigir(um(bordo_db, "SELECT alvo FROM cameras WHERE id='cam-01'").get("alvo") == "300k",
               "a chave da gravacao NAO derrubou o que ja' estava aplicado (alvo segue 300k)")

        # 5) publicacao NOVA (versao nova) e' aplicada na proxima rodada
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "", "chave": "teto_s", "valor": "3600"}, cookie=admin)
        exigir(st == 201 and r.get("versao") == 2, f"teto_s republicado sobe a versao (v{r.get('versao')})")
        rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        exigir(um(bordo_db, "SELECT valor FROM config_local WHERE camera_id='' AND chave='teto_s'").get("valor") == "3600",
               "versao nova do teto foi aplicada no bordo")

        # 6) o AGENTE passa a valer o teto publicado (nao o env)
        env = dict(os.environ)
        env.update({"LECSOR_BANCO": str(bordo_db), "LECSOR_TETO_DO_BORDO": "7200", "PYTHONIOENCODING": "utf-8"})
        saida = subprocess.run([sys.executable, "-c",
                                "import sys; sys.path.insert(0, r'%s'); import agente_de_ordens as a; "
                                "print(a.teto_do_bordo())" % str(RAIZ / "ground")],
                               cwd=str(RAIZ), env=env, capture_output=True, text=True, timeout=60)
        exigir(saida.stdout.strip().startswith("3600"),
               f"o teto PUBLICADO manda sobre o env (teto_do_bordo()={saida.stdout.strip()!r})")
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} verificacao(oes)")
        for f in falhas:
            print("  - " + f)
        return 1
    print("TUDO OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
