#!/usr/bin/env python3
"""Fase 6 do radar: a escolha do radar fica POR EMBARCACAO, na tela de captura.

Cada embarcacao pode ter o SEU radar — fonte, modo de imagem, taxa e alvo — gravado nela, como o alvo
por camera da 0.4.0. Provas, com a API de verdade rodando:
  1) a instalacao que ATUALIZA ganha as colunas de radar sozinha (banco antigo -> colunas novas);
  2) a tela LE o que ficou gravado daquela embarcacao + as opcoes fechadas (modo, taxa, alvo);
  3) pedido torto e' RECUSADO com recado claro (modo/taxa fora da lista, alvo fora da lista, .drq invalido);
  4) gravar e' POR EMBARCACAO: duas embarcacoes guardam configs diferentes ao mesmo tempo;
  5) o envio ao vivo usa o que ficou GRAVADO como padrao (a tela so' manda o que mudou) — e o envio
     sobe de verdade com o modo/taxa/alvo daquela embarcacao;
  6) embarcacao que nao existe e' recusada (nada de gravar config no vazio).

    python tests/test-radar-por-embarcacao.py
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(metodo: str, url: str, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"} if dados else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def gravar_drq(caminho: pathlib.Path, voltas: int = 1, quadros_por_grau: int = 20) -> None:
    cab = bytearray(1024)
    struct.pack_into("<II", cab, 0, 0, 1)
    struct.pack_into("<II", cab, 128, 3539456, 4096)
    t0 = datetime.datetime(2026, 11, 6, 16, 44, 27)
    with open(caminho, "wb") as f:
        f.write(bytes(cab))
        for i in range(voltas * 360 * quadros_por_grau):
            q = bytearray(2240)
            grau = (i // quadros_por_grau) % 360
            fino = (grau * 4096 // 360) % 4096
            dt = t0 + datetime.timedelta(seconds=i / (quadros_por_grau * 24.0))
            ft = int((dt - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)
            struct.pack_into("<II", q, 0, 3, 2240)
            struct.pack_into("<Q", q, 24, ft)
            struct.pack_into("<II", q, 40, grau, fino)
            struct.pack_into("<H", q, 188, 1024)
            for k in range(1024):
                struct.pack_into("<H", q, 192 + 2 * k, max(0, min(4095, 3000 - k // 2)))
            f.write(bytes(q))


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-radar-emb-"))
    banco = tmp / "pipeline.db"
    drq = tmp / "radar-da-embarcacao.drq"
    gravar_drq(drq)

    # --- 1) banco "antigo": embarcacoes SEM as colunas de radar (instalacao que atualiza) ---------
    con = sqlite3.connect(banco)
    con.execute("""CREATE TABLE embarcacoes (
        id TEXT PRIMARY KEY, cliente_id TEXT NOT NULL, nome TEXT NOT NULL,
        imo TEXT DEFAULT '', estado TEXT NOT NULL DEFAULT 'em operacao')""")
    con.execute("INSERT INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada de testes')")
    con.execute("INSERT INTO embarcacoes (id,cliente_id,nome) VALUES ('psv-01','lecsor','PSV 01')")
    con.commit()
    colunas_antes = {r[1] for r in con.execute("PRAGMA table_info(embarcacoes)")}
    con.close()
    exigir("radar_fonte" not in colunas_antes, "o banco de teste comeca SEM as colunas de radar (como um cliente antigo)")

    porta = porta_livre()
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    pronto = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                pronto = True
                break
        except Exception:
            time.sleep(0.5)
    if not pronto:
        print("FALHA a API de teste nao subiu; log:", (tmp / "api.log").read_text(errors="replace")[-400:])
        api.terminate()
        return 1

    try:
        con = sqlite3.connect(banco)
        colunas_depois = {r[1] for r in con.execute("PRAGMA table_info(embarcacoes)")}
        con.close()
        exigir({"radar_fonte", "radar_modo", "radar_taxa", "radar_alvo"} <= colunas_depois,
               f"a API criou as colunas de radar no banco que ja existia ({sorted(colunas_depois)})")

        # --- 2) a tela LE a config da embarcacao + as opcoes fechadas ---------------------------
        s, j = pedir("GET", base + "/api/embarcacoes/radar?embarcacao_id=bancada")
        exigir(s == 200 and j.get("radar", {}).get("embarcacao_id") == "bancada",
               f"a tela le a config do radar da embarcacao ({s})")
        exigir(j.get("modos") == ["ppi", "cru"] and j.get("taxas") == ["30fps", "volta"],
               f"as opcoes de imagem e taxa vem fechadas ({j.get('modos')} / {j.get('taxas')})")
        exigir(j.get("alvos") == ["1500k", "1200k", "1000k", "800k", "500k", "300k"],
               f"os alvos sao a lista fechada de qualidade ({j.get('alvos')})")
        ids = {e["id"] for e in (j.get("embarcacoes") or [])}
        exigir({"bancada", "psv-01"} <= ids, f"as embarcacoes aparecem para escolher ({sorted(ids)})")

        # --- 3) pedido torto e' recusado com recado claro ----------------------------------------
        s, j = pedir("POST", base + "/api/embarcacoes/radar",
                     {"embarcacao_id": "bancada", "fonte": str(drq), "modo": "desenho", "taxa": "30fps"})
        exigir(s == 422 and "ppi" in str(j.get("erro")), f"modo fora da lista e' recusado ({s} {j.get('erro')})")
        s, j = pedir("POST", base + "/api/embarcacoes/radar",
                     {"embarcacao_id": "bancada", "fonte": str(drq), "modo": "ppi", "taxa": "turbo"})
        exigir(s == 422 and "volta" in str(j.get("erro")), f"taxa fora da lista e' recusada ({s} {j.get('erro')})")
        s, j = pedir("POST", base + "/api/embarcacoes/radar",
                     {"embarcacao_id": "bancada", "fonte": str(drq), "modo": "ppi", "taxa": "30fps", "alvo": "9999k"})
        exigir(s == 422 and "1500k" in str(j.get("erro")), f"alvo fora da lista e' recusado ({s} {j.get('erro')})")
        s, j = pedir("POST", base + "/api/embarcacoes/radar",
                     {"embarcacao_id": "bancada", "fonte": "radar.mp4", "modo": "ppi", "taxa": "30fps"})
        exigir(s == 422 and ".drq" in str(j.get("erro")), f"fonte que nao e' sinal de radar e' recusada ({s} {j.get('erro')})")
        s, j = pedir("POST", base + "/api/embarcacoes/radar",
                     {"embarcacao_id": "navio-fantasma", "fonte": str(drq), "modo": "ppi", "taxa": "30fps"})
        exigir(s == 404, f"embarcacao que nao existe e' recusada ({s})")

        # --- 4) gravar e' POR EMBARCACAO ---------------------------------------------------------
        s, j = pedir("POST", base + "/api/embarcacoes/radar",
                     {"embarcacao_id": "bancada", "fonte": str(drq), "modo": "ppi", "taxa": "30fps", "alvo": "1000k"})
        exigir(s == 200 and j.get("radar", {}).get("modo") == "ppi", f"gravei o radar da bancada ({s})")
        s, j = pedir("POST", base + "/api/embarcacoes/radar",
                     {"embarcacao_id": "psv-01", "fonte": "tcp://127.0.0.1:47001", "modo": "cru",
                      "taxa": "volta", "alvo": "500k"})
        exigir(s == 200 and j.get("radar", {}).get("fonte") == "tcp://127.0.0.1:47001",
               f"gravei OUTRO radar na outra embarcacao ({s})")
        s, b = pedir("GET", base + "/api/embarcacoes/radar?embarcacao_id=bancada")
        s2, p = pedir("GET", base + "/api/embarcacoes/radar?embarcacao_id=psv-01")
        exigir(b["radar"]["modo"] == "ppi" and b["radar"]["alvo"] == "1000k",
               f"a bancada manteve o que e' dela ({b['radar']})")
        exigir(p["radar"]["modo"] == "cru" and p["radar"]["alvo"] == "500k",
               f"o PSV 01 manteve o que e' dele ({p['radar']})")

        # --- 5) o envio ao vivo usa o que ficou GRAVADO como padrao -------------------------------
        # (a) sem mandar bitrate: vale TUDO o que ficou gravado na embarcacao (modo/taxa/alvo).
        s, j = pedir("POST", base + "/api/ingestao/ao-vivo",
                     {"tipo": "radar", "embarcacao_id": "bancada", "rotulo": "Radar da bancada"})
        exigir(s == 201, f"o radar subiu usando a config gravada (sem a tela repetir nada): {s} {j.get('erro')}")
        if s == 201:
            exigir(j.get("rotulo") == "Radar da bancada", f"o envio volta com o nome escolhido ({j.get('rotulo')})")
            con = sqlite3.connect(banco)
            linha = con.execute("SELECT fonte, bitrate_alvo FROM ingestoes WHERE fluxo_id=?",
                                (j["fluxo_id"],)).fetchone()
            con.close()
            exigir(linha and "ppi" in (linha[0] or "") and "30fps" in (linha[0] or ""),
                   f"o modo e a taxa gravados foram usados ({linha})")
            exigir(linha and (linha[1] or "") == "1000k", f"o alvo gravado foi usado ({linha})")
            pedir("POST", base + "/api/ingestao/parar", {"id": j.get("id"), "remover": False})
        # (b) a tela pode SOBREPOR uma escolha agora (o que ela mandar vence o gravado); a fonte, o modo
        # e a taxa que ela nao mandar continuam vindo do gravado naquela embarcacao.
        s, j2 = pedir("POST", base + "/api/ingestao/ao-vivo", {"tipo": "radar", "embarcacao_id": "psv-01",
                                                              "rotulo": "Radar do PSV 01", "bitrate": "800k"})
        exigir(s == 201, f"o radar da outra embarcacao subiu ({s} {j2.get('erro')})")
        if s == 201:
            con = sqlite3.connect(banco)
            linha2 = con.execute("SELECT fonte, bitrate_alvo FROM ingestoes WHERE fluxo_id=?",
                                 (j2["fluxo_id"],)).fetchone()
            con.close()
            exigir(linha2 and linha2[0].startswith("radar:tcp://") and "cru" in linha2[0] and "volta" in linha2[0],
                   f"a fonte/modo/taxa daquela embarcacao vieram do gravado ({linha2})")
            exigir(linha2 and linha2[1] == "800k",
                   f"a tela sobrepos o alvo agora (800k) mesmo com 500k gravado ({linha2})")
            pedir("POST", base + "/api/ingestao/parar", {"id": j2.get("id"), "remover": False})

        # --- 6) embarcacao sem radar gravado continua pedindo a fonte ----------------------------
        s, j = pedir("POST", base + "/api/embarcacoes/radar",
                     {"embarcacao_id": "psv-01", "fonte": "", "modo": "ppi", "taxa": "30fps"})
        exigir(s == 422 and "fonte" in str(j.get("erro")).lower(),
               f"gravar sem fonte e' recusado ({s} {j.get('erro')})")
    finally:
        api.terminate()
        try:
            api.wait(timeout=15)
        except Exception:
            api.kill()
        log.close()

    print()
    if falhas:
        print(f"FALHAS ({len(falhas)}):")
        for f in falhas:
            print(" -", f)
        return 1
    print("TUDO OK — a escolha do radar fica gravada POR EMBARCACAO e volta como padrao do envio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
