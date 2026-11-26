#!/usr/bin/env python3
"""O PEDIDO DE TRECHO QUE O BORDO NAO RESPONDE NAO FICA PENDURADO (dono, 26/11/2026).

Palavras do dono, com o print da tela "Gravacoes" na mao:

    "não entendi esse bloco, isso foi teste? esse "chegando..." parece que está travado."

O que estava acontecendo: o pedido de um trecho ficava `pedido` para SEMPRE quando a embarcacao nao tem
bordo no ar, e a tela so' sabia escrever "pedindo…/chegando…". Esta prova mede a regra nova, com a API de
verdade num banco proprio e o prazo reduzido a 1 minuto (`LECSOR_MINUTOS_SEM_RESPOSTA_HD=1`):

  1) o pedido nasce `pedido` e o catalogo diz a IDADE dele (a tela escreve "ha' X min");
  2) repetir o pedido do mesmo bloco NAO cria pedido duplicado para o bordo;
  3) passado o prazo, o pedido vira `sem_resposta` COM o motivo — a tela para de dizer "chegando…";
  4) NADA e' apagado: o pedido continua no historico e a virada entra na auditoria;
  5) depois de "sem resposta" o cliente PODE pedir o mesmo trecho de novo (nao fica preso);
  6) o pedido novo, dentro do prazo, continua `pedido`.

    python tests/test-pedido-do-hd-sem-resposta.py
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
TOKEN = "token-do-teste-do-pedido-sem-resposta"
CAM = "radar-do-teste"
ARQUIVO = "bloco-20261126-170000.mp4"
MINUTOS = "1"          # o prazo de resposta do bordo, reduzido para a prova


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


def pedir(metodo, url, corpo=None, cookie=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            try:
                return f.status, json.loads(b or b"{}"), b
            except Exception:
                return f.status, {}, b
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}"), b
        except Exception:
            return e.code, {}, b


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (banco.parent / f"api-{porta}.log").read_text(
                errors="replace")[-600:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def sessao_de(con, uid, email, papel="cliente", cliente_id="lecsor"):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    tok = "tok-" + uid
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    return tok


def um(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def executa(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def pedido_do_catalogo(base, tok, pid):
    _st, cat, _ = pedir("GET", base + f"/api/hd/catalogo?camera_id={CAM}", cookie=tok)
    for p in (cat.get("pedidos") or []):
        if p.get("id") == pid:
            return p, cat
    return {}, cat


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-pedido-sem-resposta-"))
    banco = tmp / "terra.db"
    porta = porta_livre()
    proc = None
    try:
        proc = sobe_api(banco, porta, {"LECSOR_TOKEN_INGESTAO": TOKEN,
                                       "LECSOR_MINUTOS_SEM_RESPOSTA_HD": MINUTOS})
        base = f"http://127.0.0.1:{porta}"

        executa(banco, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        executa(banco, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        executa(banco, """INSERT OR REPLACE INTO cameras
                          (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                          VALUES (?,'bancada','Radar de oleo','','mastro',1,'','','rtsp','','300k','radar')""",
                (CAM,))
        con = sqlite3.connect(str(banco))
        tok = sessao_de(con, "cli-hd", "cliente@lecsor.test")
        con.close()

        # 1) o cliente PEDE o trecho ---------------------------------------------------------------
        st, j, _ = pedir("POST", base + "/api/hd/pedir", {"camera_id": CAM, "arquivo": ARQUIVO}, cookie=tok)
        exigir(st == 201 and j.get("ok") is True, "o cliente pede o trecho do HD e o pedido nasce no lado terra")
        pid = j.get("id") or ""
        exigir(bool(pid), "o pedido tem id (e' por ele que a tela acompanha o trecho)")

        # 2) a tela sabe a IDADE do pedido (era o que faltava: "chegando…" sem tempo nenhum) --------
        p, cat = pedido_do_catalogo(base, tok, pid)
        exigir(p.get("estado") == "pedido", "o catalogo devolve o pedido como 'pedido' (a tela escreve 'chegando…')")
        exigir(isinstance(p.get("ha_segundos"), int),
               f"o catalogo devolve a IDADE do pedido em segundos (medido: {p.get('ha_segundos')})")
        exigir(cat.get("limite_sem_resposta_s") == 60,
               f"o catalogo publica o prazo de resposta do bordo (medido: {cat.get('limite_sem_resposta_s')} s)")

        # 3) pedir de novo NAO duplica o pedido do bordo -------------------------------------------
        st, j2, _ = pedir("POST", base + "/api/hd/pedir", {"camera_id": CAM, "arquivo": ARQUIVO}, cookie=tok)
        exigir(j2.get("ja_tinha") is True and j2.get("id") == pid,
               "repetir o pedido do mesmo bloco NAO cria um pedido duplicado para o bordo")

        # 4) o prazo vence (3 min atras, com o limite em 1 min) ------------------------------------
        velho = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)).isoformat(timespec="seconds")
        executa(banco, "UPDATE hd_pedidos SET criado_em=? WHERE id=?", (velho, pid))
        p, _cat = pedido_do_catalogo(base, tok, pid)
        exigir(p.get("estado") == "sem_resposta",
               "o pedido que o bordo nao respondeu no prazo vira 'sem_resposta' (a tela para de dizer 'chegando…')")
        exigir("nao respondeu" in (p.get("motivo") or ""),
               "o pedido vencido carrega o MOTIVO, para a tela poder explicar (nao e' um traco mudo)")

        # 5) NADA e' apagado: historico + auditoria ------------------------------------------------
        exigir(um(banco, "SELECT estado FROM hd_pedidos WHERE id=?", (pid,)).get("estado") == "sem_resposta",
               "o pedido NAO e' apagado do historico (fica como 'sem resposta' do cliente)")
        exigir(bool(um(banco, "SELECT id FROM auditoria_acesso WHERE acao='trecho_do_hd_sem_resposta'")),
               "a virada entra na AUDITORIA (sempre se sabe qual trecho ficou sem resposta)")
        exigir(not um(banco, "SELECT id FROM hd_pedidos WHERE id=? AND estado='pedido'", (pid,)),
               "o pedido vencido nao fica mais na fila do bordo (ninguem vai responder o que nao existe)")

        # 6) o cliente pede DE NOVO — e nao fica preso --------------------------------------------
        st, j3, _ = pedir("POST", base + "/api/hd/pedir", {"camera_id": CAM, "arquivo": ARQUIVO}, cookie=tok)
        exigir(st == 201 and j3.get("ok") is True and j3.get("id") != pid,
               "depois de 'sem resposta' o MESMO trecho pode ser pedido outra vez (o cliente nao fica preso)")
        p, _cat = pedido_do_catalogo(base, tok, j3.get("id"))
        exigir(p.get("estado") == "pedido",
               "o pedido novo, dentro do prazo, continua 'pedido' (quem acabou de pedir nao e' punido)")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except Exception:  # noqa: BLE001
                proc.kill()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s)")
        for f in falhas:
            print("  -", f)
        return 1
    print("RESULTADO: tudo passou — o pedido que o bordo nao responde nao parece mais travado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
