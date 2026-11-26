#!/usr/bin/env python3
"""Prova dos QUATRO TIPOS de cliente (pedido do dono, 26/11/2026: "preciso de usuarios de todos os
tipos de clientes para testar, essa que estamos utilizando aparentemente e' de clientes que tem
acesso a apenas uma embarcacao").

O TIPO nao e' um campo no banco: e' DERIVADO dos vinculos (`escopo_do_cliente`, ground/api.py).
Esta prova sobe a API de verdade num banco proprio, roda a semente de teste
(`tools/seed-usuarios-de-teste.py --sem-supabase`) e entra com CADA um dos quatro usuarios medindo o
que cada um enxerga:

  1) tipo 1 (um vinculo)    -> 1 embarcacao, e o HD do bordo SO' dela
  2) tipo 2 (dois vinculos) -> 2 embarcacoes, HD das duas
  3) tipo 3 (sem vinculo)   -> todas as da propria empresa (3)
  4) tipo 4 (observador)    -> todas as embarcacoes de todas as empresas, e SO' radar/FLIR

    python tests/test-os-4-tipos-de-cliente.py
"""
from __future__ import annotations

import hashlib
import http.cookiejar
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
SENHA = "senha-da-prova-dos-4-tipos-de-cliente"
TOKEN_INGESTAO = "token-da-prova-dos-4-tipos"
EMB2, EMB3 = "teste-psv-2", "teste-psv-3"
EMB_LECSOR = "teste-emb-lecsor"
CAM_RADAR, CAM_RADAR3, CAM_RADAR_LECSOR = "teste-radar-psv2", "teste-radar-psv3", "teste-radar-lecsor"
TRANS = "teste-transmissao-1"
# (email, escopo que o proprio servidor deve devolver, embarcacoes que deve enxergar; None = "todas
# as de todas as empresas" — medido a parte, porque depende de quais embarcacoes existem no banco)
ESPERADO = [
    ("cliente-1-embarcacao@demo.test", "uma_embarcacao_da_empresa", [EMB2]),
    ("cliente-2-embarcacoes@demo.test", "algumas_embarcacoes_da_empresa", [EMB2, EMB3]),
    ("cliente-todas-da-empresa@demo.test", "todas_as_embarcacoes_da_empresa",
     ["psv-exemplo", EMB2, EMB3]),
    ("observador@demo.test", "todas_as_empresas", None),
]
falhas: list[str] = []


def checar(texto: str, cond, detalhe: str = "") -> None:
    print(("OK   " if cond else "FALHA ") + texto + (f" — {detalhe}" if detalhe and not cond else ""))
    if not cond:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def abrir_sessao(base: str, email: str):
    """Entra como o usuario e devolve o abridor com o cookie da sessao (o login e' do produto)."""
    jar = http.cookiejar.CookieJar()
    abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    corpo = json.dumps({"email": email, "senha": SENHA}).encode()
    req = urllib.request.Request(base + "/api/entrar", data=corpo,
                                 headers={"Content-Type": "application/json"})
    with abridor.open(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError("login recusado para %s: %s" % (email, r.status))
    return abridor


def ler(abridor, base: str, rota: str):
    req = urllib.request.Request(base + rota)
    try:
        with abridor.open(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__status": e.code, "erro": e.read().decode()[:200]}


def definir_senha(banco: pathlib.Path, emails: list[str], senha: str) -> None:
    """A semente deixa a senha ALEATORIA (nunca impressa); a prova define a senha que ela conhece."""
    con = sqlite3.connect(str(banco))
    for e in emails:
        salt = os.urandom(16).hex()
        h = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt), 200_000).hex()
        con.execute("UPDATE usuarios SET senha_hash=?, salt=?, interacoes=200000 WHERE email=?",
                    (h, salt, e))
    con.commit()
    con.close()


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-4-tipos-"))
    banco = tmp / "pipeline.db"
    env = dict(os.environ)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_SENHA_DEMO": SENHA,
                "LECSOR_TOKEN_INGESTAO": TOKEN_INGESTAO,
                "LECSOR_GRAVACOES_DIR": str(tmp / "gravacoes"), "PYTHONIOENCODING": "utf-8"})
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_EMBARCACAO"):
        env.pop(k, None)
    porta = porta_livre()
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
                           cwd=str(RAIZ), env=env, stdout=(tmp / "api.log").open("wb"),
                           stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    pronto = False
    for _ in range(80):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                pronto = True
                break
        except Exception:
            time.sleep(0.5)
    if not pronto:
        print("FALHA a API nao subiu:", (tmp / "api.log").read_text(errors="replace")[-500:])
        api.terminate()
        return 1

    try:
        print("== 1. semente dos 4 tipos (tools/seed-usuarios-de-teste.py --sem-supabase)")
        semente = subprocess.run(
            [sys.executable, str(RAIZ / "tools" / "seed-usuarios-de-teste.py"),
             "--banco", str(banco), "--raiz", str(RAIZ), "--sem-supabase"],
            cwd=str(RAIZ), env=env, capture_output=True, text=True, timeout=300)
        print(semente.stdout.strip()[-1200:] or semente.stderr.strip()[-600:])
        checar("a semente rodou sem erro", semente.returncode == 0,
               "rc=%s %s" % (semente.returncode, semente.stderr[-200:]))
        checar("a semente cria um usuario por tipo",
               all(e in semente.stdout for e, _s, _x in ESPERADO))
        definir_senha(banco, [e for e, _s, _x in ESPERADO], SENHA)

        print()
        print("== 2. o que CADA tipo enxerga (medido no servidor)")
        for email, escopo_esperado, embarcacoes_esperadas in ESPERADO:
            print("--", email)
            try:
                abridor = abrir_sessao(base, email)
            except Exception as e:  # noqa: BLE001
                checar("o usuario %s entra no sistema" % email, False, str(e))
                continue
            eu = ler(abridor, base, "/api/eu")
            checar("o servidor diz o tipo de cliente de %s" % email,
                   eu.get("escopo") == escopo_esperado, "escopo=%s" % eu.get("escopo"))
            embs = ler(abridor, base, "/api/embarcacoes")
            ids = sorted(x["id"] for x in (embs.get("embarcacoes") or []))
            if embarcacoes_esperadas is None:
                checar("o observador enxerga as embarcacoes de TODAS as empresas (>= 4)",
                       len(ids) >= 4 and {EMB2, EMB3, EMB_LECSOR} <= set(ids), "na tela: %s" % ids)
                con = sqlite3.connect(str(banco))
                donos = sorted({r[0] for r in con.execute(
                    "SELECT DISTINCT cliente_id FROM embarcacoes WHERE id IN (%s)"
                    % ",".join("?" * len(ids)), ids)})
                con.close()
                checar("as embarcacoes do observador sao de mais de uma empresa", len(donos) >= 2,
                       "empresas: %s" % donos)
            else:
                checar("%s enxerga as embarcacoes do seu tipo (%d)"
                       % (email, len(embarcacoes_esperadas)),
                       ids == sorted(embarcacoes_esperadas), "na tela: %s" % ids)

            cams = ler(abridor, base, "/api/cameras")
            tipos = sorted({c.get("tipo") for c in (cams.get("cameras") or [])})
            de_quais = sorted({c.get("embarcacao_id") for c in (cams.get("cameras") or [])})
            if escopo_esperado == "todas_as_empresas":
                checar("o observador so' ve radar/FLIR (nada de camera comum)",
                       set(tipos) <= {"radar", "flir"} and tipos, "tipos: %s" % tipos)
                checar("o observador ve radar/FLIR de embarcacoes de empresas diferentes",
                       {EMB_LECSOR, EMB2, EMB3} <= set(de_quais), "em: %s" % de_quais)
            else:
                checar("as cameras de %s sao so' das embarcacoes dele" % email,
                       set(de_quais) <= set(embarcacoes_esperadas) and de_quais,
                       "em: %s" % de_quais)

            cat = ler(abridor, base, "/api/hd/catalogo")
            cameras_com_hd = sorted(c["camera_id"] for c in (cat.get("catalogos") or []))
            if escopo_esperado == "uma_embarcacao_da_empresa":
                checar("o HD do bordo do tipo 1 SO' tem a embarcacao dele",
                       cameras_com_hd == [CAM_RADAR], "catalogos: %s" % cameras_com_hd)
            elif escopo_esperado == "algumas_embarcacoes_da_empresa":
                checar("o HD do bordo do tipo 2 tem as DUAS embarcacoes dele",
                       cameras_com_hd == sorted([CAM_RADAR, CAM_RADAR3]), "catalogos: %s" % cameras_com_hd)
            elif escopo_esperado == "todas_as_embarcacoes_da_empresa":
                checar("o HD do bordo do tipo 3 tem as duas embarcacoes com catalogo da empresa",
                       cameras_com_hd == sorted([CAM_RADAR, CAM_RADAR3]), "catalogos: %s" % cameras_com_hd)
            else:
                nomes = sorted({c.get("embarcacao_nome") for c in (cat.get("catalogos") or [])})
                checar("o observador ve no HD o radar das duas empresas, com o nome da embarcacao",
                       cameras_com_hd == sorted([CAM_RADAR, CAM_RADAR3, CAM_RADAR_LECSOR]) and nomes,
                       "catalogos: %s / nomes: %s" % (cameras_com_hd, nomes))

            if escopo_esperado != "todas_as_empresas":
                # a aba "Gravado em terra" da pagina nova le o historico da embarcacao escolhida
                est = ler(abridor, base, "/api/transmissao?embarcacao=" + EMB2)
                hist = est.get("historico") or []
                da_semente = [h for h in hist if h.get("id") == TRANS]
                if escopo_esperado == "uma_embarcacao_da_empresa":
                    checar("o tipo 1 ve o trecho gravado em terra da sua embarcacao",
                           bool(da_semente) and (da_semente[0].get("gravacao") or {}).get("tem") is True,
                           "historico: %s" % [h.get("id") for h in hist][:5])
                else:
                    checar("o tipo %s tambem alcanca o historico da embarcacao dele" % email,
                           bool(da_semente), "historico: %s / resposta: %s"
                           % ([h.get("id") for h in hist][:5], str(est)[:120]))

        # 3) o mesmo dono da instalacao ve TUDO (admin) — a regra nao pode ter apertado o admin
        print()
        print("== 3. o admin continua vendo tudo")
        abridor = abrir_sessao(base, "admin@lecsor.test")
        embs = ler(abridor, base, "/api/embarcacoes")
        checar("o admin ve todas as embarcacoes", len(embs.get("embarcacoes") or []) >= 4,
               "%d" % len(embs.get("embarcacoes") or []))
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            api.kill()

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — os quatro tipos de cliente existem, cada um enxerga o que o seu tipo manda")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
