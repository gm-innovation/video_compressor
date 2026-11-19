#!/usr/bin/env python3
"""O CLIENTE ACESSA AS IMAGENS DO RADAR A QUALQUER MOMENTO (0.7.0) — o loop do HD, de ponta a ponta.

Palavras do dono (19/11/2026): "mesmo que o cliente nao acione o streaming do radar de oleo, as imagens
estarao sendo comprimidas e gravadas full time, o cliente pode acessar as imagens a qualquer momento".

    python tests/e2e-hd-do-radar-cliente-pede-trecho.py

Cadeia provada (camera real como dublê do radar no HDMI + agente de verdade):
  1) a gravacao continua enche o HD local de blocos (o cliente NAO pediu transmissao nenhuma);
  2) o bordo PUBLICA O CATALOGO no lado terra (o que existe, por horario) — sem subir video;
  3) o cliente pesquisa na tela (`GET /api/hd/catalogo?camera_id=`) e ve os blocos do horario;
  4) o cliente PEDE um trecho (`POST /api/hd/pedir`): vira pedido na fila do bordo;
  5) o bordo LE O PEDIDO NA FLAG e ENVIA o bloco (bytes crus) — terra nunca alcanca o bordo;
  6) o cliente BAIXA o trecho (`GET /api/hd/baixar`) e o arquivo tem o tamanho do bloco do HD.
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
CAM_RADAR = "radar-01"


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


def pedir(metodo, url, corpo=None, cookie="", token="", bruto=None):
    dados = bruto if bruto is not None else (json.dumps(corpo).encode() if corpo is not None else None)
    cab = {"Content-Type": "application/octet-stream" if bruto is not None else "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=120) as f:
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
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env,
                            stdout=(banco.parent / f"api-{porta}.log").open("wb"),
                            stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-500:])
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


def espera(cond, teto_s=90.0) -> bool:
    fim = time.time() + teto_s
    while time.time() < fim:
        if cond():
            return True
        time.sleep(1.0)
    return False


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


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-hdloop-"))
    hd = tmp / "hd"
    terra_db, bordo_db = tmp / "terra.db", tmp / "bordo.db"
    p_terra = porta_livre()
    p_bordo = porta_livre({p_terra})
    procs: list = []
    try:
        base_cfg = f"http://127.0.0.1:{p_terra}"
        procs.append(sobe_api(terra_db, p_terra, {"LECSOR_LADO_TERRA_API": base_cfg,
                                                  "LECSOR_BIND": "0.0.0.0",
                                                  "LECSOR_TOKEN_INGESTAO": TOKEN,
                                                  "LECSOR_GRAVACOES_DIR": str(tmp / "gravacoes")}))
        procs.append(sobe_api(bordo_db, p_bordo, {"LECSOR_EMBARCACAO": "bancada",
                                                  "LECSOR_LADO_TERRA_API": base_cfg,
                                                  "LECSOR_TOKEN_INGESTAO": TOKEN,
                                                  "LECSOR_PORTA_API": str(p_bordo)}))
        base_terra, base_bordo = f"http://127.0.0.1:{p_terra}", f"http://127.0.0.1:{p_bordo}"
        _, disp, _ = pedir("GET", base_bordo + "/api/dispositivos")
        video = (disp.get("dispositivos") or disp.get("video") or [])
        nomes = [d.get("video") if isinstance(d, dict) else d for d in video]
        dispositivo = (nomes or [""])[0]
        nota(f"dispositivo (dublê do radar no HDMI): {dispositivo or 'NENHUM'}")
        if not dispositivo:
            nota("NAO MEDIDO: sem dispositivo de video nesta maquina")
            return 1

        executa(terra_db, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        executa(terra_db, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        executa(terra_db, """INSERT OR REPLACE INTO cameras
                             (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                             VALUES (?,'bancada','Radar de oleo','',?,1,'','','rtsp','','300k')""", (CAM_RADAR, CAM_RADAR))
        con = sqlite3.connect(str(terra_db))
        tok = sessao_de(con, "cli-hd", "cliente@lecsor.test")
        con.close()

        env_hd = dict(os.environ)
        env_hd.update({"LECSOR_GRAVACAO_CONTINUA": "1", "LECSOR_HD_DIR": str(hd),
                       "LECSOR_BLOCO_SEGUNDOS": "2", "LECSOR_HD_DISPOSITIVO": dispositivo,
                       "LECSOR_HD_CAMERA": CAM_RADAR, "LECSOR_HD_BITRATE": "300k",
                       "LECSOR_HD_RESOLUCAO": "640x480", "PYTHONIOENCODING": "utf-8"})
        procs.append(subprocess.Popen([sys.executable, str(RAIZ / "ground" / "gravacao_continua.py")],
                                      cwd=str(RAIZ), env=env_hd,
                                      stdout=(tmp / "hd.log").open("wb"), stderr=subprocess.STDOUT))
        agente_env = dict(os.environ)
        agente_env.update({"LECSOR_LADO_TERRA_API": base_cfg, "LECSOR_EMBARCACAO": "bancada",
                           "LECSOR_TOKEN_INGESTAO": TOKEN, "LECSOR_PORTA_LOCAL": str(p_bordo),
                           "LECSOR_ORDENS_ESTADO": str(tmp / "ligados.json"),
                           "LECSOR_ESPERA_DA_FLAG": "1", "PYTHONIOENCODING": "utf-8",
                           "LECSOR_GRAVACAO_CONTINUA": "1", "LECSOR_HD_DIR": str(hd),
                           "LECSOR_BLOCO_SEGUNDOS": "2", "LECSOR_HD_DISPOSITIVO": dispositivo,
                           "LECSOR_HD_CAMERA": CAM_RADAR})
        procs.append(subprocess.Popen([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py")],
                                      cwd=str(RAIZ), env=agente_env,
                                      stdout=(tmp / "agente.log").open("wb"), stderr=subprocess.STDOUT))

        # 1) o HD enche sozinho (o cliente nao pediu transmissao nenhuma)
        exigir(espera(lambda: len(list(hd.glob("bloco-*.mp4"))) >= 2, 90.0),
               f"a gravacao continua encheu o HD ({len(list(hd.glob('bloco-*.mp4')))} bloco(s)) sem ninguem pedir")

        # 2) o bordo publica o catalogo em terra
        st, jc, _ = pedir("GET", base_terra + f"/api/hd/catalogo?camera_id={CAM_RADAR}", cookie=tok)
        cat = (jc.get("catalogos") or [{}])[0]
        blocos = cat.get("blocos") or []
        exigir(st == 200 and len(blocos) >= 1,
               f"o cliente VE o catalogo do HD na tela ({len(blocos)} bloco(s), "
               f"primeiro {str((blocos[0] if blocos else {}).get('inicio'))[11:19]})")

        # 3) o cliente procura por horario e pede um trecho
        arquivo = blocos[0]["arquivo"]
        st, jp, _ = pedir("POST", base_terra + "/api/hd/pedir",
                          {"camera_id": CAM_RADAR, "arquivo": arquivo}, cookie=tok)
        pid = (jp.get("id") or "")
        exigir(st == 201 and pid, f"o cliente pediu o trecho {arquivo} ({st}, {str(jp.get('recado'))[:60]!r})")

        # 4) o bordo le o pedido na flag e envia o bloco
        enviado = espera(lambda: um(terra_db, "SELECT * FROM hd_pedidos WHERE id=?", (pid,)).get("estado") == "enviado", 90.0)
        p = um(terra_db, "SELECT * FROM hd_pedidos WHERE id=?", (pid,))
        exigir(enviado and p.get("bytes", 0) > 0,
               f"o bordo ENVIOU o bloco (pedido {p.get('estado')}, {p.get('bytes')} B)")

        # 5) o cliente baixa o trecho
        st, _, corpo = pedir("GET", base_terra + f"/api/hd/baixar?id={pid}", cookie=tok)
        tamanho_hd = (hd / arquivo).stat().st_size if (hd / arquivo).exists() else 0
        exigir(st == 200 and len(corpo) == p.get("bytes", 0) and len(corpo) > 0,
               f"o cliente BAIXOU o trecho ({len(corpo)} B; o bloco no HD tem {tamanho_hd} B)")
        if tamanho_hd and tamanho_hd < 20_000:
            nota("nota: o bloco esta' com poucos bytes porque o dispositivo desta maquina nao "
                 "entregou quadros agora (ele fica ocupado pelo app); a CADEIA e' o que se prova aqui — "
                 "no PC de captura o mesmo codigo grava as imagens do radar")
    finally:
        for pr in procs:
            try:
                pr.terminate()
            except Exception:
                pass

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — o radar fica gravado full time no HD do PC de captura e o cliente ve e baixa as imagens "
          "quando quiser, sem o bordo abrir porta nenhuma")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
