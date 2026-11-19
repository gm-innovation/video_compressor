#!/usr/bin/env python3
"""Quem captura e' a MAQUINA DE CAPTURA: no lado terra o clique vira ORDEM, nao captura local.

Medido em 19/11/2026 (base do lado terra, `ingestoes` 186-191): o admin clicou "ligar" no LADO TERRA e a
tela respondeu `ffmpeg saiu com codigo 234: Error opening input files: Invalid argument`, com o log
"Unknown input format: 'dshow'" — o lado terra (Linux, sem dshow) tentando abrir a camera do PC de bordo.
O sinal chega DIVIDIDO (split) na nossa maquina de captura; o lado terra so' manda ordem.

    python tests/test-lado-terra-nao-captura.py

Provas (com DOIS servidores de verdade, lado terra e bordo):
  1) no lado terra, `/api/cameras/ligar` NAO tenta capturar: responde "ordem enviada ao bordo" e grava a
     ordem (`iniciar`) na fila do bordo;
  2) `desligar` no lado terra tambem vira ordem (`parar`);
  3) NADA foi capturado no lado terra: nenhuma linha nova em `ingestoes` e nenhum processo de ffmpeg;
  4) o clique no lado terra entra na trilha de auditoria como `ordem_camera_ligada`/`ordem_camera_desligada`
     (com o numero da ordem), nunca como "camera_ligada" (isso seria mentira: ninguem ligou camera);
  5) na MAQUINA DE CAPTURA (bordo) o mesmo clique continua sendo captura local (sem ordem);
  6) `/api/cameras/prontidao` no lado terra diz `maquina_de_captura: false` — a tela nao mente dizendo
     "pronta" onde ninguem ve' o dispositivo.
"""
from __future__ import annotations

import datetime as dt
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
TOKEN = "token-de-teste-do-lado-terra"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def porta_livre(excluir: set[int] | None = None) -> int:
    excluir = excluir or set()
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        if p not in excluir:
            return p


def pedir(metodo, url, corpo=None, cookie="", token_bordo=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token_bordo:
        cab["Authorization"] = f"Bearer {token_bordo}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=40) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
    env.update(env_extra)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(60):
        if proc.poll() is not None:   # morreu: nao adianta esperar (porta tomada, erro de import)
            raise RuntimeError(f"a API de {banco} saiu com codigo {proc.returncode}: "
                               + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-400:])
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                return proc, base, log
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"a API de {banco} nao subiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-400:])


def sessao_de(con, uid, email, papel="admin"):
    import hashlib
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,'lecsor',?,?,200000,1)""", (uid, email, uid, papel, senha, salt))
    tok = f"tok-{uid}"
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    return tok


def semear(banco: pathlib.Path):
    con = sqlite3.connect(banco)
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                   VALUES ('cam-01','bancada','Cam 01','vivo-cam01-1901','','1','','','rtsp','','300k')""")
    con.commit()
    con.close()


def um(banco, sql, args=()):
    con = sqlite3.connect(banco)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, args).fetchone()
    finally:
        con.close()


def ffmpegs() -> int:
    """Contagem de processos ffmpeg VIVOS nesta maquina (prova do 'nao capturou aqui')."""
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/NH"],
                           capture_output=True, text=True, errors="replace")
        return sum(1 for l in (r.stdout or "").splitlines() if "ffmpeg.exe" in l)
    r = subprocess.run(["bash", "-lc", "pgrep -c -f ffmpeg || true"], capture_output=True, text=True)
    try:
        return int((r.stdout or "0").strip() or 0)
    except Exception:
        return 0


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-lado-terra-"))
    terra_db, bordo_db = tmp / "terra.db", tmp / "bordo.db"
    p_terra = porta_livre()
    p_bordo = porta_livre({p_terra})
    procs = []
    try:
        base_terra_cfg = f"http://127.0.0.1:{p_terra}"
        proc_t, base_terra, _ = sobe_api(terra_db, p_terra,
                                         {"LECSOR_LADO_TERRA_API": base_terra_cfg,   # o lado terra se reconhece
                                          "LECSOR_TOKEN_INGESTAO": TOKEN})            # e NAO tem embarcacao
        procs.append(proc_t)
        proc_b, base_bordo, _ = sobe_api(bordo_db, p_bordo,
                                         {"LECSOR_EMBARCACAO": "bancada",
                                          "LECSOR_LADO_TERRA_API": base_terra_cfg,
                                          "LECSOR_TOKEN_INGESTAO": TOKEN})
        procs.append(proc_b)
        semear(terra_db)
        semear(bordo_db)
        con = sqlite3.connect(terra_db)
        tok = sessao_de(con, "admin-1", "admin@lecsor.test", "admin")
        con.close()
        con = sqlite3.connect(bordo_db)
        sessao_de(con, "admin-1", "admin@lecsor.test", "admin")
        con.close()

        # --- 6) o lado terra sabe que NAO e' a maquina de captura
        st, pront = pedir("GET", base_terra + "/api/cameras/prontidao", cookie=tok)
        exigir(st == 200 and pront.get("maquina_de_captura") is False,
               f"lado terra: prontidao diz maquina_de_captura={pront.get('maquina_de_captura')!r} (esperado False)")

        antes = ffmpegs()
        n_ing_antes = um(terra_db, "SELECT COUNT(*) FROM ingestoes")[0]

        # --- 1) ligar no lado terra = ORDEM
        st, j = pedir("POST", base_terra + "/api/cameras/ligar", {"camera_id": "cam-01"}, cookie=tok)
        exigir(st == 200 and j.get("enviado_ao_bordo") is True and int(j.get("ordem") or 0) >= 1,
               f"ligar no lado terra virou ORDEM (status {st}, enviado_ao_bordo={j.get('enviado_ao_bordo')!r}, ordem={j.get('ordem')!r})")
        exigir("nao e' a de captura" in str(j.get("recado") or ""),
               f"a resposta explica por que nao capturou aqui: {(j.get('recado') or '')[:70]!r}")
        o = um(terra_db, "SELECT acao, camera_id, embarcacao_id, estado FROM ordens_do_bordo ORDER BY seq DESC LIMIT 1")
        exigir(bool(o) and o["acao"] == "iniciar" and o["camera_id"] == "cam-01",
               f"a fila do bordo tem a ordem 'iniciar' para cam-01 (linha: {dict(o) if o else None})")

        # --- 2) desligar no lado terra = ORDEM 'parar'
        st, j2 = pedir("POST", base_terra + "/api/cameras/desligar", {"camera_id": "cam-01"}, cookie=tok)
        o2 = um(terra_db, "SELECT acao FROM ordens_do_bordo ORDER BY seq DESC LIMIT 1")
        exigir(st == 200 and bool(o2) and o2["acao"] == "parar" and j2.get("enviado_ao_bordo") is True,
               f"desligar no lado terra virou ORDEM 'parar' (status {st}, acao={o2['acao'] if o2 else None!r})")

        # --- 3) NADA foi capturado aqui
        n_ing_depois = um(terra_db, "SELECT COUNT(*) FROM ingestoes")[0]
        exigir(n_ing_depois == n_ing_antes,
               f"nenhum envio nasceu no lado terra (ingestoes: {n_ing_antes} -> {n_ing_depois})")
        exigir(ffmpegs() <= antes,
               f"nenhum ffmpeg a mais no lado terra ({antes} -> {ffmpegs()})")

        # --- 4) trilha de auditoria
        aud = [r[0] for r in sqlite3.connect(terra_db).execute(
            "SELECT acao FROM auditoria_acesso WHERE acao LIKE 'ordem_camera%' ORDER BY id")]
        exigir("ordem_camera_ligada" in aud and "ordem_camera_desligada" in aud,
               f"trilha registra ordem_camera_ligada/desligada (auditoria: {aud})")
        mentiu = sqlite3.connect(terra_db).execute(
            "SELECT COUNT(*) FROM auditoria_acesso WHERE acao='camera_ligada'").fetchone()[0]
        exigir(mentiu == 0, f"nada de 'camera_ligada' no lado terra (achou {mentiu})")

        # --- 5) no BORDO o clique continua sendo captura local
        print(f"     (para o log) portas: terra={p_terra} bordo={p_bordo}")
        st, jb = pedir("POST", base_bordo + "/api/cameras/ligar", {"camera_id": "cam-01"}, cookie=tok)
        ordem_no_bordo = um(bordo_db, "SELECT COUNT(*) FROM ordens_do_bordo")[0]
        ordem_no_terra = um(terra_db, "SELECT COUNT(*) FROM ordens_do_bordo")[0]
        exigir(jb.get("enviado_ao_bordo") is not True and ordem_no_bordo == 0,
               f"no bordo o clique NAO vira ordem (status {st}, ordens no bordo={ordem_no_bordo}, "
               f"no lado terra={ordem_no_terra}, resposta: {str(jb)[:110]})")
        stb, prontb = pedir("GET", base_bordo + "/api/cameras/prontidao", cookie=tok)
        exigir(stb == 200 and prontb.get("maquina_de_captura") is True,
               f"o bordo se reconhece como maquina de captura (prontidao: {prontb.get('maquina_de_captura')!r})")
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(0.5)

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — o lado terra manda ORDEM e nao captura; a captura acontece (e e' dita) no bordo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
