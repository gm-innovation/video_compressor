#!/usr/bin/env python3
"""Prova da FLAG DE AUDIENCIA (dono, 24/11/2026, D3): quem sustenta o "ligar" e' o ESPECTADOR.

O dono testou e viu o defeito, verbatim: *"sai da tela de transmissao ao vivo do cliente e continuou
transmitindo, isso precisa ser flag para o app de captura enxergar e parar a transmissao, a nao ser que
esteja sendo visualizado em outro computador"*. E decidiu (D3): *"nao tem ligar agora do admin, so quem
visualiza e' o cliente"*.

Causa medida: `_desejo_das_cameras` deixava `manual=='ligar'` (gravado pelo botao "ligar agora" do admin)
VENCER o "ninguem esta' assistindo"; nada limpava esse `manual` quando o espectador saia.

O que se prova aqui, contra a API de verdade (banco proprio, sem navegador):

  1) cliente A abre a sessao  ->  `desejo=ligar` e o motivo CITA quem assiste;
  2) A some (sem batimento)   ->  em ate' `SEGUNDOS_SEM_BATIMENTO` a sessao fecha e `desejo=parar`;
  3) A e B assistindo, A sai  ->  CONTINUA `ligar` (o dono: "a nao ser que esteja sendo visualizado em
     outro computador");
  4) `manual='ligar'` sozinho  ->  NAO sustenta: sem sessao viva, o desejo e' `parar` (o botao do admin
     deixou de existir / deixou de valer);
  5) `manual='parar'` (a operacao desligou na mao) CONTINUA valendo mesmo com sessao aberta;
  6) a migracao de boot LIMPA o `manual='ligar'` deixado por versao antiga.

    python tests/e2e-flag-de-audiencia.py
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
SENHA = "senha-de-prova-da-flag"
TOKEN = "token-de-ingestao-da-prova"
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
AGUARDA_VIGIA = 9        # a vigia roda de 5 em 5 s; 9 s cobre a volta dela com folga


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def nota(texto: str) -> None:
    print("  ..   " + texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str, cliente_id: str | None) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                   VALUES (?,?,'Proa',?,'bordo',1,'800k')""", (CAM, EMB, CAM))
    con.commit()
    con.close()


def pedir(metodo: str, url: str, corpo=None, cookie: str = "", token: str = ""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)
    if dados is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", "sessao=" + cookie)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            cookie_novo = r.headers.get("Set-Cookie") or ""
            return r.status, json.loads(r.read() or b"{}"), cookie_novo
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), ""
        except Exception:  # noqa: BLE001
            return e.code, {}, ""


def entrar(base: str, email: str) -> str:
    st, corpo, ck = pedir("POST", base + "/api/entrar", {"email": email, "senha": SENHA})
    if st != 200:
        raise RuntimeError(f"login de {email} falhou: {st} {corpo}")
    tam = ck.split("sessao=")[1].split(";")[0]
    return tam


def desejo(base: str, cam: str = CAM) -> dict:
    st, corpo, _ = pedir("GET", f"{base}/api/estado-desejado?embarcacao_id={EMB}", token=TOKEN)
    if st != 200:
        raise RuntimeError(f"estado-desejado falhou: {st} {corpo}")
    for c in corpo.get("cameras", []):
        if c.get("camera_id") == cam:
            return c
    return {}


def abrir_sessao(base: str, cookie: str, cam: str = CAM) -> str:
    st, corpo, _ = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": cam}, cookie=cookie)
    if st not in (200, 201):
        raise RuntimeError(f"iniciar transmissao falhou: {st} {corpo}")
    return corpo["transmissao"]["id"]


def envelhecer_batimento(banco: pathlib.Path, tid: str, segundos: int) -> None:
    """Sem esperar 60 s de verdade: recua o 'estou aqui' no banco e deixa a vigia agir."""
    con = sqlite3.connect(str(banco))
    con.execute("UPDATE transmissoes SET batimento_em=datetime('now', ?) WHERE id=?",
                (f"-{segundos} seconds", tid))
    con.commit()
    con.close()


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-flag-audiencia-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_DESTINO_SRT", "LECSOR_EMBARCACAO", "LECSOR_LICENCA"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_TOKEN_INGESTAO": TOKEN, "LECSOR_SEM_FLAG": "0",
                "PYTHONIOENCODING": "utf-8"})
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=3):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("a API nao subiu; log em %s" % (tmp / "api.log"))

        criar_usuario(banco, "cli-a", "cliente.a@lecsor.test", "cliente", EMPRESA)
        criar_usuario(banco, "cli-b", "cliente.b@lecsor.test", "cliente", EMPRESA)
        semear(banco)

        print("\n== 1. cliente A abre a transmissao -> desejo=ligar, com o motivo dizendo quem assiste ==")
        ck_a = entrar(base, "cliente.a@lecsor.test")
        tid_a = abrir_sessao(base, ck_a)
        d = desejo(base)
        checar("com a sessao viva o desejo e' 'ligar'", d.get("desejo") == "ligar", str(d))
        checar("o motivo CITA o espectador (a trilha conta a verdade)",
               "cliente.a@lecsor.test" in (d.get("motivo") or ""), d.get("motivo", ""))

        print("\n== 2. A some (fecha a tela) -> a vigia fecha a sessao e o desejo vira 'parar' ==")
        envelhecer_batimento(banco, tid_a, 61)
        time.sleep(AGUARDA_VIGIA)
        d = desejo(base)
        checar("sem ninguem assistindo o desejo vira 'parar'", d.get("desejo") == "parar", str(d))
        checar("e o motivo diz que nao ha ninguem assistindo",
               "ninguem" in (d.get("motivo") or "").lower(), d.get("motivo", ""))

        print("\n== 3. A e B assistindo: A sai e a transmissao CONTINUA para B (o dono exigiu) ==")
        ck_b = entrar(base, "cliente.b@lecsor.test")
        tid_a = abrir_sessao(base, ck_a)
        abrir_sessao(base, ck_b)
        envelhecer_batimento(banco, tid_a, 61)
        time.sleep(AGUARDA_VIGIA)
        d = desejo(base)
        checar("com B ainda assistindo o desejo CONTINUA 'ligar'", d.get("desejo") == "ligar", str(d))
        checar("e o motivo cita quem ficou", "cliente.b@lecsor.test" in (d.get("motivo") or ""),
               d.get("motivo", ""))

        print("\n== 4. o 'ligar agora' do admin NAO sobrevive sem ninguem assistindo ==")
        # desliga a sessao viva de B para o quadro ficar sem espectador
        st, listagem, _ = pedir("GET", f"{base}/api/transmissao?embarcacao={EMB}", cookie=ck_b)
        for t in listagem.get("abertas", []):
            pedir("POST", f"{base}/api/transmissao/{t['id']}/encerrar", {}, cookie=ck_b)
        con = sqlite3.connect(str(banco))
        con.execute("""INSERT INTO desejo_camera (camera_id,embarcacao_id,desejo,versao,motivo,transmissao_id,
                         manual,atualizado_em)
                       VALUES (?,?,'ligar',99,'deixado por versao antiga','','ligar',datetime('now'))
                       ON CONFLICT(camera_id) DO UPDATE SET manual='ligar', desejo='ligar'""", (CAM, EMB))
        con.commit()
        con.close()
        d = desejo(base)
        checar("mesmo com manual='ligar' gravado, sem sessao o desejo e' 'parar'",
               d.get("desejo") == "parar", str(d))

        print("\n== 5. o 'desligar' da operacao (manual='parar') continua valendo: barra a sessao ==")
        con = sqlite3.connect(str(banco))
        con.execute("UPDATE desejo_camera SET manual='parar' WHERE camera_id=?", (CAM,))
        con.commit(); con.close()
        st, corpo, _ = pedir("POST", base + "/api/transmissao/iniciar", {"camera_id": CAM}, cookie=ck_a)
        checar("o cliente NAO fura o desligar do operador (409, com recado claro)",
               st == 409 and "operacao" in json.dumps(corpo).lower(), f"{st} {corpo}")
        d = desejo(base)
        checar("e o desejo e' 'parar' mesmo com o cliente pedindo",
               d.get("desejo") == "parar", str(d))
        checar("e o motivo diz que foi o operador",
               "operador" in (d.get("motivo") or "").lower(), d.get("motivo", ""))

        print("\n== 6. a migracao de boot limpa o manual='ligar' legado ==")
        con = sqlite3.connect(str(banco))
        con.execute("UPDATE desejo_camera SET manual='ligar' WHERE camera_id=?", (CAM,))
        con.commit(); con.close()
        api.terminate()
        api.wait(timeout=15)
        log.close()
        log = (tmp / "api2.log").open("wb")
        api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                               cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=3):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        con = sqlite3.connect(str(banco))
        linha = con.execute("SELECT manual FROM desejo_camera WHERE camera_id=?", (CAM,)).fetchone()
        con.close()
        checar("depois do boot o manual='ligar' virou '' (limpo)",
               bool(linha) and (linha[0] or "") == "", f"manual={linha[0]!r}" if linha else "sem linha")
    finally:
        try:
            api.terminate()
            api.wait(timeout=15)
        except Exception:  # noqa: BLE001
            pass

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} prova(s): " + "; ".join(falhas))
        return 1
    print("OK: a flag de audiencia se sustenta so' na sessao de quem assiste (desejo liga/para correto).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
