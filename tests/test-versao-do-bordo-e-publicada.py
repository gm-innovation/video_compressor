#!/usr/bin/env python3
"""O APP DO PC DE CAPTURA ESTA' ANTIGO? (dono, 26/11/2026)

Palavras do dono, com a tela na mao:

    "gravação contínua: publicada LIGADA — o bordo: ligada (ligada, mas esta maquina nao tem
     dispositivo de video configurado (LECSOR_HD_DISPOSITIVO): nada sera' gravado)"

Aquela mensagem **so' existia na versao antiga**: o PC de captura estava na 0.25.0 e NADA no produto
dizia isso — o admin via "publicada LIGADA" e um "nada sera' gravado" que parece defeito do produto,
quando o caso era o app de captura velho. Esta prova mede o que passou a existir:

  1) `comparar_versao()` — o bordo ANTIGO e' denunciado, nomeando as duas versoes;
  2) versao igual (ou do bordo mais nova) NAO vira alarme;
  3) versao desconhecida NUNCA vira "esta' tudo certo" (`None` + motivo, nunca `False` por omissao);
  4) a versao DESTE lado sai do `VERSION` da raiz quando nao ha' `LECSOR_VERSAO_APP`;
  5) HTTP `/api/config` (a tela do admin) entrega `versao_do_bordo`, `versao_publicada`,
     `bordo_desatualizado` e o motivo — e o `lado` diz de quem e' a tela;
  6) no `lado bordo` (`/api/config-desejada`, o bordo puxando a config) a comparacao nao inventa
     "publicada": a versao publicada e' desconhecida ali, e o produto admite isso.

    python tests/test-versao-do-bordo-e-publicada.py
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
GROUND = RAIZ / "ground"
sys.path.insert(0, str(GROUND))

falhas: list[str] = []
TOKEN = "token-da-prova-da-versao-do-bordo"


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


def pedir(metodo, url, corpo=None, cookie="", portador=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if portador:                      # o mesmo que o agente do bordo manda (Bearer, nunca sessao)
        cab["Authorization"] = f"Bearer {portador}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            try:
                return f.status, json.loads(b or b"{}"), b
            except Exception:  # noqa: BLE001
                return f.status, {}, b
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}"), b
        except Exception:  # noqa: BLE001
            return e.code, {}, b


def executa(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def sessao_de(con, uid, email, papel="admin", cliente_id="lecsor"):
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


def sobe_api(banco: pathlib.Path, porta: int, extra_env: dict | None = None):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("LECSOR_SUPABASE_URL", None)
    env.pop("LECSOR_LADO_TERRA_API", None)
    env.pop("LECSOR_EMBARCACAO_BORDO", None)
    env.pop("LECSOR_VERSAO_APP", None)
    env.update(extra_env or {})
    log = (banco.parent / f"api-versao-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(GROUND / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (banco.parent / f"api-versao-{porta}.log").read_text(
                errors="replace")[-800:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def poe_retrato(banco, emb, versao, maquina="PC-DE-CAPTURA"):
    executa(banco, """INSERT INTO saude_bordo (embarcacao_id,recebido_em,maquina,versao_app,estado,retrato)
                      VALUES (?,?,?,?,?,?)""",
            (emb, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), maquina, versao,
             "atencao", json.dumps({"versao_app": versao, "maquina": maquina})))


def main() -> int:
    print("== 1. comparar_versao(): o bordo ANTIGO e' denunciado, nomeando as duas versoes")
    os.environ.pop("LECSOR_VERSAO_APP", None)
    import api

    r = api.comparar_versao("0.25.0", "0.27.0")
    exigir(r["desatualizado"] is True, f"0.25.0 contra 0.27.0 -> desatualizado={r['desatualizado']!r}")
    exigir("0.25.0" in r["motivo"] and "0.27.0" in r["motivo"],
           f"o motivo NOMEIA as duas versoes (o dono le o que fazer) [{r['motivo']}]")
    exigir("atualizar" in r["motivo"].lower(), "e diz o que fazer: atualizar o app de captura")

    print()
    print("== 2. igual (ou mais nova) NAO vira alarme")
    exigir(api.comparar_versao("0.27.0", "0.27.0")["desatualizado"] is False,
           "mesma versao -> em dia (sem alarme falso)")
    exigir(api.comparar_versao("0.30.0", "0.27.0")["desatualizado"] is False,
           "bordo mais NOVO que o publicado -> sem alarme (nao se inventa problema)")
    exigir(api.comparar_versao("0.26.10", "0.27.0")["desatualizado"] is True,
           "0.26.10 < 0.27.0 (comparacao por numero, nao por texto)")

    print()
    print("== 3. versao desconhecida NUNCA vira 'esta tudo certo'")
    r = api.comparar_versao("", "0.27.0")
    exigir(r["desatualizado"] is None and "versao" in r["motivo"],
           f"bordo sem versao -> 'nao se sabe' com motivo, nunca False [{r['motivo']}]")
    r = api.comparar_versao("0.25.0", "")
    exigir(r["desatualizado"] is None,
           f"tela sem a versao publicada -> 'nao se sabe' (o bordo esta' na v0.25.0) [{r['motivo']}]")
    exigir(api.comparar_versao("versao-antiga", "0.27.0")["desatualizado"] is None,
           "versao nao numerica -> 'nao consegui comparar', sem chute")
    nota(f"versao_em_trio: 0.25.0={api.versao_em_trio('0.25.0')} · 0.26.10={api.versao_em_trio('0.26.10')}")

    print()
    print("== 4. a versao DESTE lado sai do `VERSION` da raiz (o deploy do terra leva o arquivo)")
    arquivo = RAIZ / "VERSION"
    exigir(arquivo.exists(), "existe o `VERSION` na raiz (fonte unica da versao do lado terra)")
    do_arquivo = arquivo.read_text(encoding="utf-8").strip() if arquivo.exists() else ""
    nota(f"VERSION = {do_arquivo!r}")
    exigir(api.versao_do_app() == do_arquivo,
           f"sem LECSOR_VERSAO_APP, a versao deste lado e' a do VERSION [{api.versao_do_app()!r}]")
    os.environ["LECSOR_VERSAO_APP"] = "9.9.9-prova"
    exigir(api.versao_do_app() == "9.9.9-prova", "com LECSOR_VERSAO_APP quem manda e' o ambiente (o app)")
    os.environ.pop("LECSOR_VERSAO_APP", None)
    # o pacote tem de LEVAR o VERSION junto: sem ele o servidor empacotado nao sabe a propria versao
    pkg = json.loads((RAIZ / "desktop" / "package.json").read_text(encoding="utf-8"))
    leva_version = any((x.get("from") or "").endswith("VERSION") for x in pkg["build"]["extraResources"])
    exigir(leva_version, "o instalador leva o VERSION dentro do pacote (servidor/VERSION)")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-versao-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    proc = None
    try:
        proc = sobe_api(banco, porta)                     # cria o ESQUEMA
        base = f"http://127.0.0.1:{porta}"
        executa(banco, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        executa(banco, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        con = sqlite3.connect(str(banco))
        con.row_factory = sqlite3.Row
        tok = sessao_de(con, "adm-versao", "admin@lecsor.test", papel="admin")
        con.close()

        print()
        print("== 5. HTTP /api/config (a tela do admin) denuncia o app antigo do PC de captura")
        poe_retrato(banco, "bancada", "0.25.0")
        st, cfg, _ = pedir("GET", base + "/api/config?embarcacao_id=bancada", cookie=tok)
        exigir(st == 200, f"a tela do admin le a configuracao (HTTP {st})")
        exigir(cfg.get("lado") == "terra", f"e diz de que lado esta' a tela [{cfg.get('lado')!r}]")
        exigir(cfg.get("versao_do_bordo") == "0.25.0",
               f"a versao QUE O BORDO INFORMOU chega a tela [{cfg.get('versao_do_bordo')!r}]")
        exigir(cfg.get("versao_publicada") == do_arquivo,
               f"e a versao publicada vem do VERSION [{cfg.get('versao_publicada')!r}]")
        exigir(cfg.get("bordo_desatualizado") is True,
               f"o bordo ANTIGO e' acusado: bordo_desatualizado={cfg.get('bordo_desatualizado')!r}")
        exigir("0.25.0" in (cfg.get("motivo_da_versao") or "")
               and do_arquivo in (cfg.get("motivo_da_versao") or ""),
               f"o motivo na tela carrega as duas versoes [{cfg.get('motivo_da_versao')}]")

        print()
        print("== 6. o bordo que se atualiza para de ser acusado (e o silencio nao vira 'atualizado')")
        executa(banco, "DELETE FROM saude_bordo WHERE embarcacao_id='bancada'")
        poe_retrato(banco, "bancada", do_arquivo)
        _, cfg, _ = pedir("GET", base + "/api/config?embarcacao_id=bancada", cookie=tok)
        exigir(cfg.get("bordo_desatualizado") is False,
               "depois de atualizar, a tela cala a boca (nada de alarme falso)")
        executa(banco, "DELETE FROM saude_bordo WHERE embarcacao_id='bancada'")
        _, cfg, _ = pedir("GET", base + "/api/config?embarcacao_id=bancada", cookie=tok)
        exigir(cfg.get("bordo_desatualizado") is None and cfg.get("motivo_da_versao"),
               f"sem retrato nenhum, 'nao se sabe' com motivo — nunca 'em dia' "
               f"[{cfg.get('bordo_desatualizado')!r} · {cfg.get('motivo_da_versao')}]")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except Exception:  # noqa: BLE001
                proc.kill()

    # ---- 7. do lado BORDO (o proprio PC de captura puxando a config) ------------------------------
    banco2 = tmp / "bordo.db"
    porta2 = porta_livre()
    proc2 = None
    try:
        proc2 = sobe_api(banco2, porta2, {"LECSOR_EMBARCACAO_BORDO": "bancada",
                                          "LECSOR_VERSAO_APP": "0.25.0"})
        base2 = f"http://127.0.0.1:{porta2}"
        executa(banco2, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        executa(banco2, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        print()
        print("== 7. no lado BORDO a resposta nao inventa 'publicada' (ali nao se sabe qual e')")
        st, cfg, _ = pedir("GET", base2 + "/api/config-desejada?embarcacao_id=bancada", portador=TOKEN)
        exigir(st == 200, f"o bordo puxa a configuracao desejada (HTTP {st})")
        exigir(cfg.get("lado") == "bordo", f"a resposta sabe que esta' no bordo [{cfg.get('lado')!r}]")
        exigir(cfg.get("versao_do_bordo") == "0.25.0",
               f"a versao do bordo e' a DELE (do app que esta' rodando) [{cfg.get('versao_do_bordo')!r}]")
        exigir(cfg.get("versao_publicada") == "" and cfg.get("bordo_desatualizado") is None,
               f"e nao chuta a publicada (fica 'nao se sabe') "
               f"[publicada={cfg.get('versao_publicada')!r} desatualizado={cfg.get('bordo_desatualizado')!r}]")
    finally:
        if proc2:
            proc2.terminate()
            try:
                proc2.wait(timeout=20)
            except Exception:  # noqa: BLE001
                proc2.kill()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s)")
        for f in falhas:
            print("  -", f)
        return 1
    print("RESULTADO: tudo passou — o produto denuncia o app de captura ANTIGO (com as duas versoes) e "
          "nunca diz 'em dia' quando a versao nao foi informada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
