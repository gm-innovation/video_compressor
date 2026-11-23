#!/usr/bin/env python3
"""Prova de ponta a ponta (plano de 19/11/2026, Fase 2): a VARREDURA do bordo cadastra sozinha.

O dono (19/11/2026): "o app a bordo pode carregar ja' com o inicio do sistema, faz a varredura das
cameras e radar, cadastra internamente, envia as informacoes pro admin, o admin configura e o cliente
passa a acessar na web".

Sobe DUAS APIs de verdade (o lado terra e o bordo, bancos separados) e poe um `ffmpeg` DE MENTIRA na
frente do produto (`LECSOR_FFMPEG`) que anuncia, como o dshow do Windows:

  * DUAS cameras de MESMO NOME ("USB Video Device") com seletores `@device_pnp_...` diferentes — o caso
    que antes virava uma camera so';
  * uma placa de captura de HDMI ("Ezcap HDMI Capture"), que e' o caminho do radar de oleo.

E prova:

  1) no BOOT o bordo varre sozinho, cria as duas cameras na embarcacao do pacote (com id distinto e o
     dispositivo gravado em `config_local`) e NAO cadastra o radar como camera;
  2) o cadastro CHEGA ao lado terra (a camera aparece no banco de terra) e a publicacao e' relatada;
  3) a varredura NAO sobrescreve o que o admin configurou (`alvo`, `ativo` continuam como estavam);
  4) dispositivo que sai da lista (cabo/USB removido) NAO e' apagado nem desativado pela varredura;
  5) a varredura manual (botao da tela, `POST /api/varredura`) funciona e o `GET /api/varredura` conta.

    python tests/e2e-varredura-do-bordo.py
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
CLIENTE = "lecsor"

# O que o ffmpeg de mentira anuncia. Duas cameras de MESMO nome com seletores diferentes + a placa HDMI.
DEVICES_COMPLETO = [
    ("USB Video Device", "video", r"@device_pnp_\\?\usb#vid_1bcf&pid_2c99#01#{65e8773d}"),
    ("USB Video Device", "video", r"@device_pnp_\\?\usb#vid_0408&pid_4035#02#{65e8773d}"),
    ("Ezcap HDMI Capture", "video", r"@device_pnp_\\?\usb#vid_1c40&pid_0534#03#{65e8773d}"),
    ("Microfone (USB Audio)", "audio", ""),
]
DEVICES_SEM_UMA = [DEVICES_COMPLETO[0], DEVICES_COMPLETO[2], DEVICES_COMPLETO[3]]


def exigir(cond, texto):
    print(("  OK   " if cond else "  FALHA") + " " + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def portas_livres(quantas: int, evitar=()) -> list[int]:
    """`quantas` portas DISTINTAS.

    Sondar e soltar porta a porta nao serve: o sistema devolve a MESMA porta efemera de novo, e as duas
    APIs do teste acabavam na mesma porta (no Windows, `allow_reuse_address` deixa o segundo bind passar
    e o teste fala com o processo errado). Aqui as portas ficam presas ao mesmo tempo ate' serem lidas.
    """
    presas: list[socket.socket] = []
    portas: list[int] = []
    try:
        while len(portas) < quantas:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
            presas.append(s)
            if p not in evitar and p not in portas:
                portas.append(p)
        return portas
    finally:
        for s in presas:
            s.close()


def escrever_fake_ffmpeg(caminho: pathlib.Path, devices) -> None:
    """Escreve o `ffmpeg` de mentira (mesmo formato de `-list_devices` do dshow, no STDERR, rc=1)."""
    linhas = ["@echo off"]
    for nome, tipo, seletor in devices:
        linhas.append(f'echo [dshow @ 000] "{nome}" ({tipo}) 1>&2')
        if seletor:
            linhas.append(f'echo [dshow @ 000]   Alternative name "{seletor}" 1>&2')
    linhas.append("exit /b 1")
    # `write_bytes`: em modo texto o Windows troca "\n" por "\r\n" e o arquivo fica com "\r\r\n",
    # que o cmd le' mal (medido: a varredura enxergava UM dispositivo de cada vez).
    caminho.write_bytes(("\r\n".join(linhas) + "\r\n").encode("latin-1"))


def pedir(metodo, url, corpo=None, cookie=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
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
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT",
              "LECSOR_TOKEN_INGESTAO", "LECSOR_FFMPEG"):
        env.pop(k, None)
    env.update(env_extra)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-800:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def semear(banco: pathlib.Path, radar_fonte: str) -> str:
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (CLIENTE, "LECSOR (teste)"))
    con.execute("""INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado,radar_fonte)
                   VALUES (?,?,?,?,?,?)""", (EMB, CLIENTE, "Bancada do teste", "", "em operacao", radar_fonte))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES ('admin','admin@lecsor.test','admin','admin',NULL,?,?,200000,1)""", (senha, salt))
    tok = "tok-admin"
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, "admin", exp, "teste"))
    con.commit()
    con.close()
    return tok


def cameras_da_varredura(banco: pathlib.Path) -> list[dict]:
    """As cameras que a VARREDURA criou: as que tem o seletor de dispositivo em `config_local`.

    O banco do bordo tambem nasce com as cameras de demonstracao (a API semeia `cam-01`/`cam-02`);
    contar todas confundiria a prova com a bancada.
    """
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        linhas = con.execute("""SELECT c.* FROM cameras c
                                JOIN config_local l ON l.camera_id = c.id AND l.chave='dispositivo'
                                WHERE l.valor LIKE '@device_pnp_%'
                                ORDER BY c.id""").fetchall()
        return [dict(x) for x in linhas]
    finally:
        con.close()


def cameras_do_banco(banco: pathlib.Path) -> list[dict]:
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        return [dict(x) for x in con.execute("SELECT * FROM cameras ORDER BY id").fetchall()]
    finally:
        con.close()


def dispositivo_de(banco: pathlib.Path, camera_id: str) -> str:
    con = sqlite3.connect(str(banco))
    try:
        r = con.execute("SELECT valor FROM config_local WHERE camera_id=? AND chave='dispositivo'",
                        (camera_id,)).fetchone()
        return (r[0] if r else "") or ""
    finally:
        con.close()


def esperar_varredura(base_bordo: str, tok: str, segundos: int = 40) -> dict:
    """Espera a varredura do BOOT terminar (ela roda em segundo plano, ~5 s depois de subir)."""
    fim = time.time() + segundos
    ultimo = {}
    while time.time() < fim:
        c, j = pedir("GET", f"{base_bordo}/api/varredura", cookie=tok)
        ultimo = j.get("varredura") or {}
        if ultimo.get("vistos"):
            return ultimo
        time.sleep(1.5)
    return ultimo


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-varredura-"))
    terra_db, bordo_db = tmp / "terra.db", tmp / "bordo.db"
    p_terra, p_bordo = portas_livres(2)
    exigir(p_terra != p_bordo, f"as duas APIs do teste em portas diferentes ({p_terra}/{p_bordo})")
    fake = tmp / "ffmpeg-falso.cmd"
    escrever_fake_ffmpeg(fake, DEVICES_COMPLETO)
    procs: list = []
    try:
        base_terra = f"http://127.0.0.1:{p_terra}"
        procs.append(sobe_api(terra_db, p_terra, {"LECSOR_LADO_TERRA_API": base_terra,
                                                  "LECSOR_BIND": "0.0.0.0",
                                                  "LECSOR_TOKEN_INGESTAO": TOKEN}))
        tok_terra = semear(terra_db, "")
        procs.append(sobe_api(bordo_db, p_bordo, {"LECSOR_EMBARCACAO": EMB,
                                                  "LECSOR_LADO_TERRA_API": base_terra,
                                                  "LECSOR_TOKEN_INGESTAO": TOKEN,
                                                  "LECSOR_FFMPEG": str(fake),
                                                  "LECSOR_ESPERA_DA_VARREDURA": "30"}))
        tok = semear(bordo_db, "Ezcap")   # o radar DESTA embarcacao e' a placa de HDMI
        base_bordo = f"http://127.0.0.1:{p_bordo}"

        # ---- 0. o bordo JA' varreu sozinho depois de subir (o laco roda sem ninguem pedir)
        # DEBUG (temporario): quem responde em cada porta
        for rot, b in (("terra", base_terra), ("bordo", base_bordo)):
            ca, ja = pedir("GET", f"{b}/api/saude")
            cv, jv = pedir("GET", f"{b}/api/varredura", cookie=tok)
            nota(f"DEBUG {rot} {b}: saude={ca} varredura={cv} resumo={json.dumps({k: (jv.get('varredura') or {}).get(k) for k in ('ok', 'vistos', 'embarcacao_id', 'motivo')}, ensure_ascii=False)[:200]}")
        r_boot = esperar_varredura(base_bordo, tok)
        exigir("vistos" in r_boot, f"o bordo varreu sozinho no boot (resultado no GET: {bool(r_boot)})")
        nota(f"varredura do boot: {json.dumps({k: r_boot.get(k) for k in ('ok', 'vistos', 'cadastradas', 'motivo')}, ensure_ascii=False)}")

        # ---- 1. a varredura cadastra: duas cameras de MESMO NOME viram DUAS cameras
        c, r = pedir("POST", f"{base_bordo}/api/varredura", {}, cookie=tok)
        exigir(c == 200, f"a varredura responde 200 ({c})")
        exigir(r.get("vistos") == 3, f"o bordo viu os 3 dispositivos de video (viu {r.get('vistos')})")
        novas = (r.get("cadastradas") or []) + (r.get("atualizadas") or [])
        exigir(len(novas) == 2, f"a varredura cuidou das 2 cameras de video ({novas})")
        cams = cameras_da_varredura(bordo_db)
        exigir(len(cams) == 2, f"a varredura criou 2 cameras (criou {len(cams)})")
        exigir(all(c["embarcacao_id"] == EMB for c in cams), "as 2 nasceram na embarcacao do pacote")
        exigir(len({c["id"] for c in cams}) == 2, f"ids DISTINTOS para cameras de mesmo nome ({[c['id'] for c in cams]})")
        exigir(all((c["protocolo"] or "") == "dshow" for c in cams), "nasceram como dshow (camera local)")
        disp = [dispositivo_de(bordo_db, c["id"]) for c in cams]
        exigir(all(d.startswith("@device_pnp_") for d in disp),
               f"o dispositivo gravado e' o SELETOR unico ({disp})")
        exigir(len(set(disp)) == 2, "cada camera ficou com o SEU dispositivo (nao a mesma)")
        exigir(not any("Ezcap" in (c["rotulo"] or "") for c in cams),
               "o radar NAO foi cadastrado como camera")

        # ---- 2. o radar e' relatado (e casado com a fonte declarada), sem inventar cadastro
        radar = r.get("radar") or {}
        exigir(radar.get("fonte_declarada") == "Ezcap", f"o bordo le' a fonte de radar declarada ({radar.get('fonte_declarada')})")
        exigir(radar.get("casou") == "Ezcap HDMI Capture",
               f"a varredura casou a fonte com o dispositivo de captura ({radar.get('casou')})")
        exigir(not radar.get("cadastrado"), "o radar continua por embarcacao (nao virou camera)")

        # ---- 3. o cadastro CHEGOU ao lado terra
        exigir(bool(r.get("publicadas")), f"a varredura relatou publicacao ({r.get('publicadas')})")
        # No lado terra nao existe `config_local` (o dispositivo e' de quem captura): o que identifica a
        # camera publicada e' o proprio id, derivado do seletor.
        terra_cams = [x for x in cameras_do_banco(terra_db) if str(x["id"]).startswith("cam-device-pnp-")]
        exigir(len(terra_cams) == 2, f"as 2 cameras chegaram ao banco de TERRA (n={len(terra_cams)})")
        exigir({c["id"] for c in terra_cams} == {c["id"] for c in cams},
               f"terra recebeu os MESMOS ids do bordo ({sorted(c['id'] for c in terra_cams)})")
        exigir(not (r.get("falhas_de_publicacao") or []), f"sem falha de publicacao ({r.get('falhas_de_publicacao')})")

        # ---- 4. a varredura NAO sobrescreve o que o admin configurou
        alvo_cam = cams[0]["id"]
        con = sqlite3.connect(str(bordo_db))
        con.execute("UPDATE cameras SET alvo='800', ativo=0 WHERE id=?", (alvo_cam,))
        con.commit()
        con.close()
        c, r2 = pedir("POST", f"{base_bordo}/api/varredura", {}, cookie=tok)
        exigir(c == 200, f"POST /api/varredura (botao da tela) responde 200 (veio {c})")
        exigir(not (r2.get("cadastradas") or []), f"a 2a varredura nao re-cadastra o que ja' existe ({r2.get('cadastradas')})")
        checada = [x for x in cameras_do_banco(bordo_db) if x["id"] == alvo_cam][0]
        exigir(checada["alvo"] == "800", f"o alvo do admin sobreviveu a varredura ({checada['alvo']!r})")
        exigir(checada["ativo"] == 0, "o 'ativo' do admin sobreviveu a varredura (nao foi religada)")

        # ---- 4b. o NOME que o admin deu sobrevive a varredura (0.12.0, dono 23/11/2026:
        #      "a captura pega as informacoes e replica no app de captura, inclusive os nomes das
        #      cameras"). Quem aplica a chave `rotulo` no cadastro local e' o agente do bordo, pela rota
        #      local — aqui ela e' chamada direto, como o agente chama.
        c, rn = pedir("POST", f"{base_bordo}/api/config/aplicar",
                      {"camera_id": alvo_cam, "chave": "rotulo", "valor": "Proa de boreste"}, cookie=tok)
        exigir(c == 200 and rn.get("ok"), f"a maquina de captura aplicou o nome que veio de terra ({c})")
        nome_antes = [x for x in cameras_do_banco(bordo_db) if x["id"] == alvo_cam][0]["rotulo"]
        exigir(nome_antes == "Proa de boreste", f"o cadastro LOCAL ja' mostra o nome do admin ({nome_antes!r})")
        c, _ = pedir("POST", f"{base_bordo}/api/varredura", {}, cookie=tok)
        nome_depois = [x for x in cameras_do_banco(bordo_db) if x["id"] == alvo_cam][0]["rotulo"]
        exigir(nome_depois == "Proa de boreste" and nome_depois != "USB Video Device",
               f"a varredura NAO reescreve o nome com o do dispositivo (ficou {nome_depois!r})")

        # ---- 5. dispositivo que sai da lista NAO e' apagado nem desativado
        escrever_fake_ffmpeg(fake, DEVICES_SEM_UMA)
        c, r3 = pedir("POST", f"{base_bordo}/api/varredura", {}, cookie=tok)
        restantes = cameras_da_varredura(bordo_db)
        exigir(len(restantes) == 2, f"a camera que sai da lista continua no banco (n={len(restantes)})")
        exigir(all(x["id"] != alvo_cam or x["ativo"] == 0 for x in restantes), "o 'ativo' continua como estava")
        exigir(not (r3.get("cadastradas") or []), "nada novo foi criado ao remover um dispositivo")

        # ---- 6. o GET conta o que a tela mostra, e a saude do bordo carrega a varredura
        c, j = pedir("GET", f"{base_bordo}/api/varredura", cookie=tok)
        exigir(c == 200 and isinstance(j.get("varredura"), dict) and "intervalo_s" in j,
               f"GET /api/varredura conta o resultado e o intervalo ({c})")
        exigir(j.get("intervalo_s") == 30, f"o intervalo vem do ambiente ({j.get('intervalo_s')})")
        # O retrato que o bordo MONTA (e que sobe pelo envio de saude) tem de carregar a varredura.
        # O gerador e' `saude_do_bordo.retrato()`; aqui ele roda com o mesmo ambiente do bordo.
        amb = dict(os.environ)
        amb.update({"LECSOR_BANCO": str(bordo_db), "LECSOR_EMBARCACAO": EMB, "LECSOR_FFMPEG": str(fake)})
        rr = subprocess.run([sys.executable, "-c",
                             "import json,sys;sys.path.insert(0,'ground');import varredura_do_bordo as v;"
                             "import saude_do_bordo as s;v.varrer();"
                             "print(json.dumps(s.retrato().get('varredura') or {}))"],
                            cwd=str(RAIZ), env=amb, capture_output=True, text=True, timeout=120, errors="replace")
        try:
            varredura_no_retrato = json.loads((rr.stdout or "{}").strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            varredura_no_retrato = {}
        exigir("vistos" in varredura_no_retrato or "cadastradas" in varredura_no_retrato,
               f"o retrato da saude carrega a varredura ({json.dumps(varredura_no_retrato, ensure_ascii=False)[:120]})")

        # ---- 7. quem varre e' a maquina de captura ou a operacao/admin: cliente NAO varre
        con = sqlite3.connect(str(bordo_db))
        salt = os.urandom(16).hex()
        senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
        con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                       VALUES ('cli','cli@lecsor.test','cli','cliente',?,?,?,200000,1)""",
                    (CLIENTE, senha, salt))
        con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                    ("tok-cli", "cli", (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds"), "teste"))
        con.commit()
        con.close()
        c, _ = pedir("POST", f"{base_bordo}/api/varredura", {}, cookie="tok-cli")
        exigir(c == 401, f"cliente NAO dispara varredura -> 401 (veio {c})")
    finally:
        for pr in procs:
            pr.terminate()
        for pr in procs:
            try:
                pr.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pr.kill()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s): " + "; ".join(falhas))
        return 1
    print("RESULTADO: tudo passou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
