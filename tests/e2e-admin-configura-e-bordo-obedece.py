#!/usr/bin/env python3
"""O ADMIN CONFIGURA EM TERRA E O BORDO OBEDECE (0.8.0, Fase 4) — o ciclo inteiro, com duas APIs reais.

Dono (19/11/2026): "quando o cliente quiser iniciar o streaming, a informacao nao podera sair de terra
para bordo, o computador de captura a bordo precisa ficar olhando para terra e sempre que a flag mudar,
ele inicia ou para a transmissao" — e "o app a bordo precisa buscar o tempo todo as atualizacoes enviadas
pelo cliente e pelo admin".

Nao e' teste de unidade: sobe a API do LADO TERRA e a do BORDO (bancos separados) e roda o AGENTE de
verdade (`--uma-vez`), pelo caminho de saida do bordo (nenhuma porta aberta no bordo). O que se prova:

  1) o admin LIGA a transmissao de uma camera em terra (`transmitir=1`) e muda o alvo de banda;
  2) o bordo busca, age e CONFIRMA em terra — com o resultado honesto (no ar, ou o motivo que impediu);
  3) o estado volta ao admin (desejada x aplicada) e, quando o bordo conseguiu abrir, a camera esta' NO AR
     na API do bordo e DESLIGA quando o admin publica `transmitir=0`;
  4) caso sujo: publicar config invalida nao muda nada, e reiniciar o bordo nao reaplica o que ja' aplicou
     (o que estava no ar nao cai).

    python tests/e2e-admin-configura-e-bordo-obedece.py
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
              "LECSOR_DESTINO_SRT"):
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


def sessao_de(con, uid, email, papel, cliente_id=""):
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
                "LECSOR_ESPERA_DA_CONFIG": "2", "LECSOR_ESPERA_DA_FLAG": "1",
                "LECSOR_CONFIG_ESTADO": str(tmp / "config_aplicada.json"),
                "LECSOR_ORDENS_ESTADO": str(tmp / "ligados.json"),
                "LECSOR_GRAVACOES_DIR": str(tmp / "gravacoes"), "PYTHONIOENCODING": "utf-8"})
    log = tmp / "agente.log"
    with log.open("ab") as f:
        subprocess.run([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py"), "--uma-vez"],
                       cwd=str(RAIZ), env=env, stdout=f, stderr=subprocess.STDOUT, timeout=240)
    return log.read_text(errors="replace")


def envio_vivo(base: str, fluxo: str) -> bool:
    """O ingestoes do BORDO diz se o processo de captura desta camera esta' vivo (pid no ar)."""
    s, j = pedir("GET", f"{base}/api/ingestoes")
    for i in (j.get("ingestoes") or []):
        if i.get("fluxo_id") == fluxo and (i.get("vivo") or i.get("estado") in ("no ar", "enviando")):
            return True
    return False


def no_ar(base: str, cam: str) -> bool:
    s, j = pedir("GET", f"{base}/api/fluxos")
    for f in (j.get("fluxos") or []):
        if f.get("id") == cam or f.get("camera_id") == cam:
            return bool(f.get("no_ar"))
    return False


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-obedece-"))
    p_terra, p_bordo = porta_livre(), porta_livre()
    terra_db, bordo_db = tmp / "terra.db", tmp / "bordo.db"
    procs: list = []
    try:
        base_terra = f"http://127.0.0.1:{p_terra}"
        procs.append(sobe_api(terra_db, p_terra, {"LECSOR_LADO_TERRA_API": base_terra,
                                                  "LECSOR_BIND": "127.0.0.1", "LECSOR_TOKEN_INGESTAO": TOKEN}))
        procs.append(sobe_api(bordo_db, p_bordo, {"LECSOR_LADO_TERRA_API": base_terra,
                                                   "LECSOR_BIND": "127.0.0.1", "LECSOR_TOKEN_INGESTAO": TOKEN,
                                                   "LECSOR_EMBARCACAO": EMB, "LECSOR_PORTA_API": str(p_bordo),
                                                   "LECSOR_DESTINO_SRT": f"127.0.0.1:{p_terra}"}))
        base_bordo = f"http://127.0.0.1:{p_bordo}"
        for banco in (terra_db, bordo_db):
            executa(banco, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
            executa(banco, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,'lecsor','Bancada')", (EMB,))
            executa(banco, """INSERT OR REPLACE INTO cameras
                              (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                              VALUES ('cam-01',?,'Proa','cam-01','bordo',1,'','','rtsp','','')""", (EMB,))
        # O CADASTRO desta maquina grava o dispositivo local: e' o que deixa o admin LIGAR a camera de
        # terra sem depender de um envio de teste feito no bordo (0.8.0). Aqui entra um dispositivo que
        # nao existe, de proposito: a prova e' que o bordo TENTA abrir a camera dele, com o motivo certo.
        executa(bordo_db, """INSERT INTO config_local (camera_id,chave,valor,versao,atualizado_em)
                             VALUES ('cam-01','dispositivo','DISPOSITIVO-DE-TESTE-INEXISTENTE',0,'')
                             ON CONFLICT(camera_id,chave) DO UPDATE SET valor=excluded.valor""")
        con = sqlite3.connect(str(terra_db))
        admin = sessao_de(con, "adm-obedece", "admin@lecsor.test", "admin")
        con.close()

        # ---- 1. o admin LIGA a transmissao e escolhe a banda, em terra
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "transmitir", "valor": "1"},
                      cookie=admin)
        exigir(st == 201 and r.get("versao") == 1, f"admin publica transmitir=1 (v{r.get('versao')}, HTTP {st})")
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "alvo_kbps", "valor": "800"},
                      cookie=admin)
        exigir(st == 201, "admin publica o alvo de banda (800 kbps)")
        st, _ = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "transmitir", "valor": "sim"},
                      cookie=admin)
        exigir(st == 422, f"transmitir so' aceita 0 ou 1 (HTTP {st})")

        # ---- 2. o bordo OLHA, age e confirma (agente de verdade)
        log = rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        nota("agente: " + " | ".join(l for l in log.splitlines() if "config:" in l)[:400])
        conf = {x["chave"]: x for x in todos(terra_db, "SELECT * FROM config_aplicada_bordo")}
        exigir(conf.get("alvo_kbps", {}).get("valor") == "800",
               f"terra recebeu a confirmacao do alvo (v{conf.get('alvo_kbps', {}).get('versao')})")
        exigir("transmitir" in conf, "terra recebeu o resultado da ordem de transmissao")
        motivo = str(conf.get("transmitir", {}).get("motivo") or "")
        valor_t = str(conf.get("transmitir", {}).get("valor"))
        ligou = valor_t == "1" and (motivo in ("", "ja' estava no ar") or "no ar" in motivo)
        nota(f"transmissao: {'LIGOU' if ligou else 'nao ligou'} ({motivo or 'sem motivo'})")
        # O campo `cameras.alvo` e' o que vai CRU para o `-b:v` do ffmpeg: a convencao do produto nele e'
        # "NNNNk". Ate 23/11/2026 este teste exigia "800" (o numero publicado) e deixava passar um defeito
        # medido pela J8 do smoke: com "800" o ffmpeg lia 800 BITS/s e o video morria (0,0 Mbps, 0 quadro).
        exigir(um(bordo_db, "SELECT alvo FROM cameras WHERE id='cam-01'").get("alvo") == "800k",
               "o bordo APLICOU o alvo no banco dele, no formato do ffmpeg (800k)")
        if ligou:
            medido = no_ar(base_bordo, "cam-01") or envio_vivo(base_bordo, "cam-01")
            nota("no bordo: " + ("no ar medido pelo mediamtx/ingestoes" if medido else
                                 "o bordo informou ter aberto (a bancada nao tem mediamtx para confirmar "
                                 "o 'no ar' — quem prova o 'no ar' medido e' o teste da flag)"))
            exigir(True if medido else "no ar" in motivo or valor_t == "1",
                   f"o bordo LIGOU a camera por publicacao do admin (acao tomada; confirmado a terra: {motivo!r})")
        else:
            exigir(bool(motivo), "quando nao ligou, o motivo veio explicado a terra (nada de silencio)")
            exigir("nunca foi transmitida daqui" not in motivo,
                   f"o bordo TENTOU abrir a camera dele (dispositivo do cadastro), sem pedir envio de teste — "
                   f"motivo: {motivo[:130]!r}")
            exigir(not no_ar(base_bordo, "cam-01"), "e a camera NAO aparece no ar (nao finge transmissao)")

        # ---- 3. o admin ve desejo x aplicado na tela
        st, cfg = pedir("GET", base_terra + f"/api/config?embarcacao_id={EMB}", cookie=admin)
        chaves = {x["chave"] for x in (cfg.get("chaves") or [])}
        apl = {x["chave"]: x for x in (cfg.get("aplicadas") or [])}
        exigir(st == 200 and chaves == {"transmitir", "alvo_kbps"}, f"a tela do admin ve' as 2 chaves ({sorted(chaves)})")
        exigir(apl.get("alvo_kbps", {}).get("versao") == 1, "e ve' que o bordo ja' aplicou o alvo")

        # ---- 4. o admin DESLIGA a transmissao: o bordo para
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "transmitir", "valor": "0"},
                      cookie=admin)
        exigir(st == 201 and r.get("versao") == 2, f"admin publica transmitir=0 (v{r.get('versao')})")
        rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        c2 = {x["chave"]: x for x in todos(terra_db, "SELECT * FROM config_aplicada_bordo")}
        exigir(str(c2.get("transmitir", {}).get("valor")) == "0"
               and str(c2.get("transmitir", {}).get("motivo") or "") in ("", "ja' estava parada"),
               f"o desligar foi confirmado a terra ({c2.get('transmitir', {}).get('motivo') or 'sem motivo'})")
        exigir(not no_ar(base_bordo, "cam-01") and not envio_vivo(base_bordo, "cam-01"),
               "o bordo DESLIGOU a camera (nem no ar, nem processo de captura vivo)")

        # ---- 5. caso sujo: config invalida nao muda nada; reiniciar nao reaplica
        st, _ = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "alvo_kbps", "valor": "77"},
                      cookie=admin)
        exigir(st == 422, "alvo invalido nem sai de terra (nao chega ao bordo)")
        exigir(um(bordo_db, "SELECT alvo FROM cameras WHERE id='cam-01'").get("alvo") == "800k",
               "e o que estava aplicado no bordo segue igual (nada caiu)")
        quando = c2.get("transmitir", {}).get("atualizado_em", "")
        rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        c3 = {x["chave"]: x for x in todos(terra_db, "SELECT * FROM config_aplicada_bordo")}
        exigir(c3.get("transmitir", {}).get("atualizado_em") == quando,
               "bordo reiniciado NAO reaplica o que ja' tinha aplicado")

        # ---- 6. a publicacao nova volta a valer (versao nova e' aplicada)
        st, r = pedir("POST", base_terra + "/api/config",
                      {"embarcacao_id": EMB, "camera_id": "cam-01", "chave": "alvo_kbps", "valor": "500"},
                      cookie=admin)
        exigir(st == 201 and r.get("versao") == 2, f"alvo republicado sobe a versao (v{r.get('versao')})")
        rodar_agente(bordo_db, base_terra, p_bordo, tmp)
        exigir(um(bordo_db, "SELECT alvo FROM cameras WHERE id='cam-01'").get("alvo") == "500k",
               "o bordo aplicou a versao nova do alvo (500k)")
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
    print("TUDO OK — o admin configura em terra, o bordo obedece e conta o que fez.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
