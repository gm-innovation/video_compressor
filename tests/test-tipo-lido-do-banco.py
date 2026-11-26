#!/usr/bin/env python3
"""O TIPO QUE O ADMIN APLICA VOLTA PARA A TELA (Fase 1, 26/11/2026) — provado por HTTP.

O dono (26/11/2026, verbatim): "eu aplico novo tipo a camera, mas nao esta persistindo".

Medido na bancada no mesmo dia: a GRAVACAO sempre esteve certa (`POST /api/cameras/<id>/editar`
grava `tipo` e `tipo_definido_pelo_admin=1`) e `GET /api/cameras` ja' devolvia `radar`. Quem mentia
era a LEITURA da AREA UNICA: `arvore_do_painel` montava o `SELECT` das cameras SEM a coluna `tipo`
e `tipo_da_camera` caia no fallback pelo NOME — entao uma camera que o banco tinha como `radar`
voltava para a tela como "camera comum" (o cartao repintava o seletor).

O que se prova aqui, sem navegador (a defesa esta' no SERVIDOR):

  1) o tipo aplicado pelo admin volta IGUAL na area unica (`/api/empresas`) — e nao pelo nome;
  2) vale para `radar` E `flir`;
  3) um tipo fora da lista (`antena`) e' RECUSADO (422) e o tipo gravado NAO muda;
  4) a lista crua (`/api/cameras`) e a area unica CONCORDAM (o mesmo tipo nos dois caminhos);
  5) `tipo_definido_pelo_admin` fica 1 (o anuncio do bordo nao pode desfazer a escolha do admin).

    python tests/test-tipo-lido-do-banco.py
"""
from __future__ import annotations

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
SENHA = "senha-do-tipo-de-teste"
EMPRESA, EMB = "empresa-tipo", "emb-tipo"
# Nome SEM "radar": se o nome decidisse, o tipo lido voltaria "camera" e o teste pegava a mentira.
CAM_ALVO = "equip-ocm-01"
CAM_FLIR = "sens-iv-01"


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def criar_admin(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES ('admin','admin@lecsor.test','admin','admin',NULL,?,?,200000,1)""", (senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    """Uma empresa, uma embarcacao e duas cameras cujo NOME nao entrega o tipo."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Empresa do tipo"))
    con.execute("""INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado,radar_fonte)
                   VALUES (?,?,?,?,?,?)""", (EMB, EMPRESA, "Embarcacao do tipo", "", "em operacao", ""))
    for cid, rotulo in ((CAM_ALVO, "Equipamento OCM"), (CAM_FLIR, "Sensor IV")):
        con.execute("""INSERT OR REPLACE INTO cameras
                       (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                       VALUES (?,?,?,?,'',1,'','','dshow','','','camera')""", (cid, EMB, rotulo, cid))
    con.commit()
    con.close()


def subir(banco: pathlib.Path, tmp: pathlib.Path):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_SENHA_DEMO"] = "senha-de-bancada-nao-usada"
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
    porta = porta_livre()
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(80):
        if api.poll() is not None:
            raise RuntimeError("a API saiu: " + (tmp / "api.log").read_text(errors="replace")[-800:])
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                return api, base, tmp / "api.log"
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    api.kill()
    raise RuntimeError("a API nao subiu")


def entrar(base: str) -> str:
    req = urllib.request.Request(base + "/api/entrar", method="POST",
                                 data=json.dumps({"email": "admin@lecsor.test", "senha": SENHA}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return (r.headers.get("Set-Cookie") or "").split(";")[0]


def pedir(base: str, rota: str, cookie: str):
    rq = urllib.request.Request(base + rota, headers={"Cookie": cookie})
    try:
        with urllib.request.urlopen(rq, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")


def enviar(base: str, rota: str, corpo: dict, cookie: str):
    rq = urllib.request.Request(base + rota, method="POST", data=json.dumps(corpo).encode(),
                                headers={"Content-Type": "application/json", "Cookie": cookie})
    try:
        with urllib.request.urlopen(rq, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")


def _andar(no, cam_id: str):
    """Acha a camera `cam_id` em QUALQUER profundidade da area unica (empresa>emb>camera)."""
    if isinstance(no, dict):
        if no.get("id") == cam_id and "tipo" in no:
            return no
        for v in no.values():
            achado = _andar(v, cam_id)
            if achado:
                return achado
    elif isinstance(no, list):
        for v in no:
            achado = _andar(v, cam_id)
            if achado:
                return achado
    return None


def tipo_no_banco(banco: pathlib.Path, cam_id: str):
    con = sqlite3.connect(str(banco))
    linha = con.execute("SELECT tipo,tipo_definido_pelo_admin FROM cameras WHERE id=?", (cam_id,)).fetchone()
    con.close()
    return linha


def main() -> int:
    print("TIPO LIDO DO BANCO — 26/11/2026: o tipo que o admin aplica volta para a tela, e nao pelo nome.\n")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-tipo-lido-"))
    banco = tmp / "pipeline.db"
    api, base, log = subir(banco, tmp)
    try:
        criar_admin(banco)
        semear(banco)
        cookie = entrar(base)

        # ---- 1. a area unica ANTES: as duas nascem "camera" (o nome nao decide)
        st, area = pedir(base, "/api/empresas", cookie)
        checar("a area unica responde 200", st == 200, f"HTTP {st}")
        antes = _andar(area, CAM_ALVO)
        checar("a camera do radar aparece na area unica ja' como 'camera'",
               bool(antes) and antes.get("tipo") == "camera",
               f"tipo={antes.get('tipo') if antes else None}")

        # ---- 2. o admin aplica `radar` na camera (o pedido do dono, exato)
        st, r = enviar(base, f"/api/cameras/{CAM_ALVO}/editar", {"tipo": "radar"}, cookie)
        checar("o admin aplicou o tipo 'radar' (HTTP 200)", st == 200, f"HTTP {st} {r}")
        linha = tipo_no_banco(banco, CAM_ALVO)
        checar("o banco guardou tipo='radar' com a marca do admin",
               bool(linha) and linha[0] == "radar" and linha[1] == 1, f"{linha}")

        # ---- 3. A PROVA DA FASE 1: a area unica (o que a tela desenha) devolve o MESMO tipo
        st, area = pedir(base, "/api/empresas", cookie)
        depois = _andar(area, CAM_ALVO)
        checar("a AREA UNICA devolve tipo='radar' (era 'camera' — a leitura mentia)",
               bool(depois) and depois.get("tipo") == "radar",
               f"tipo={depois.get('tipo') if depois else None}")

        # ---- 4. os dois caminhos concordam
        st, cams = pedir(base, "/api/cameras", cookie)
        por_id = {c["id"]: c for c in (cams.get("cameras") or [])}
        checar("a lista crua e a area unica concordam no tipo",
               por_id.get(CAM_ALVO, {}).get("tipo") == "radar" and (depois or {}).get("tipo") == "radar",
               f"lista={por_id.get(CAM_ALVO, {}).get('tipo')} area={(depois or {}).get('tipo')}")

        # ---- 5. vale para FLIR
        st, r = enviar(base, f"/api/cameras/{CAM_FLIR}/editar", {"tipo": "flir"}, cookie)
        st2, area = pedir(base, "/api/empresas", cookie)
        flir = _andar(area, CAM_FLIR)
        checar("o tipo 'flir' tambem volta para a area unica",
               st == 200 and bool(flir) and flir.get("tipo") == "flir",
               f"HTTP {st} tipo={flir.get('tipo') if flir else None}")

        # ---- 6. tipo fora da lista e' RECUSADO e o gravado nao muda
        st, r = enviar(base, f"/api/cameras/{CAM_ALVO}/editar", {"tipo": "antena"}, cookie)
        linha = tipo_no_banco(banco, CAM_ALVO)
        checar("tipo invalido ('antena') e' recusado com 422", st == 422, f"HTTP {st} {r}")
        checar("e o tipo gravado continua 'radar'", bool(linha) and linha[0] == "radar", f"{linha}")

        st, area = pedir(base, "/api/empresas", cookie)
        depois = _andar(area, CAM_ALVO)
        checar("a area unica segue mostrando 'radar' depois da recusa",
               bool(depois) and depois.get("tipo") == "radar",
               f"tipo={depois.get('tipo') if depois else None}")
    finally:
        api.kill()
        print(f"   (log: {log})")

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} verificacao(oes) — {falhas}")
        return 1
    print("TUDO VERDE: o tipo aplicado pelo admin volta IGUAL na area unica — a leitura deixou de mentir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
