#!/usr/bin/env python3
"""Prova de TELA: saude e desempenho do bordo NA AREA UNICA do admin (24/11/2026, Fase 2).

Dono, verbatim: *"nao tenho nenhuma informacao de saude e desempenho"*. Antes a area unica mostrava so'
"Câmeras: N · no ar: M · último retrato do bordo: <hora> · PC(s): <máquina>" — os NUMEROS (CPU, memoria,
disco/anel do HD, ffmpeg, captura, mediamtx, dispositivos, varredura) existiam so' na tela antiga.

O que se prova, contra a API e a TELA de verdade:

  1) `GET /api/empresas` traz `saude` com o NUMERO de cada sinal (cpu_pct, memoria_pct, hd_radar_usado_pct,
     ffmpeg, mediamtx, dispositivos, varredura) e a lista de `sinais` com limiar e "o que fazer";
  2) a TELA do admin (area unica, na embarcacao) desenha esses numeros — CPU, memoria, ffmpeg, mediamtx;
  3) SEGURANCA (P0 medido em 24/11/2026): a chave da LICENCA nao sai inteira em `maquinas[]` — so' os
     4 ultimos digitos (`licenca_ultimos4`), inclusive para o papel `observador` (Petrobras).

    python tests/e2e-saude-e-desempenho-na-area.py
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

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = "senha-da-prova-de-saude"
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
CHAVE = "R8B2-78NM-C11Z-VR9U"
ESPERA = 20000


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str, cliente_id: str | None = None) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    con.commit(); con.close()


def semear(banco: pathlib.Path) -> None:
    agora = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    retrato = {
        "gerado_em": agora, "maquina": "DESKTOP-78DSH57", "so": "Windows 11 10.0.26100",
        "versao_app": "0.12.0", "uptime_s": 7200,
        "cpu_pct": 42.0, "memoria_pct": 61.0, "memoria_livre_mb": 5120.0,
        "discos": [{"nome": "aplicativo", "total_gb": 500.0, "livre_gb": 410.0, "usado_pct": 18.0},
                   {"nome": "hd do radar", "total_gb": 2000.0, "livre_gb": 1250.0, "usado_pct": 37.5, "blocos": 48}],
        "ffmpeg": {"presente": True, "caminho": "C:/tools/ffmpeg.exe", "versao": "ffmpeg version 7.1"},
        "dispositivos_video": {"quantos": 5, "nomes": ["USB Video Device"]},
        "agente": {"laco_vivo": True, "idade_s": 3},
        "mediamtx": {"ativo": True, "caminhos": 4},
        "banco": {"ok": True, "cameras": 4, "pedidos_pendentes": 0, "erros_24h": 0},
        "varredura": {"ok": True, "vistos": 5, "publicadas": ["cam-01"]},
        "nao_medido": {},
    }
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                   VALUES (?,?,'Proa',?,'bordo',1,'800k')""", (CAM, EMB, CAM))
    con.execute("""INSERT INTO saude_bordo (embarcacao_id,recebido_em,maquina,versao_app,estado,retrato)
                   VALUES (?,?,?,?,?,?)""",
                (EMB, agora, "DESKTOP-78DSH57", "0.12.0", "ok", json.dumps(retrato)))
    con.execute("""INSERT OR REPLACE INTO licencas (id,chave,embarcacao_id,validade_tipo,validade_em,
                     maquinas_max,status) VALUES ('lic-1',?,?,'indeterminada','',3,'ativa')""", (CHAVE, EMB))
    con.execute("""INSERT OR REPLACE INTO licenca_usos (licenca_id,maquina,primeiro_em,ultimo_em)
                   VALUES ('lic-1','DESKTOP-78DSH57',?,?)""", (agora, agora))
    con.commit(); con.close()


def pedir(metodo: str, url: str, corpo=None, cookie: str = ""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)
    if dados is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", "sessao=" + cookie)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}"), (r.headers.get("Set-Cookie") or "")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), ""
        except Exception:  # noqa: BLE001
            return e.code, {}, ""


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-saude-area-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_EMBARCACAO", "LECSOR_LICENCA"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
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

        criar_usuario(banco, "admin", "admin@lecsor.test", "admin")
        criar_usuario(banco, "obs", "petrobras@lecsor.test", "observador")
        semear(banco)

        print("\n== 1. GET /api/empresas traz a SAUDE com o numero de cada sinal ==")
        st, _c, ck = pedir("POST", base + "/api/entrar", {"email": "admin@lecsor.test", "senha": SENHA})
        cookie = ck.split("sessao=")[1].split(";")[0]
        st, arv, _ = pedir("GET", base + "/api/empresas", cookie=cookie)
        checar("a rota respondeu (admin)", st == 200, f"{st}")
        empresa = next(e for e in arv["empresas"] if e["id"] == EMPRESA)
        emb = next(x for x in empresa["embarcacoes"] if x["id"] == EMB)
        s = emb.get("saude") or {}
        checar("a saude traz a CPU medida", s.get("cpu_pct") == 42.0, str(s.get("cpu_pct")))
        checar("e a memoria", s.get("memoria_pct") == 61.0, str(s.get("memoria_pct")))
        checar("e o disco do HD do radar", s.get("hd_radar_usado_pct") == 37.5, str(s.get("hd_radar_usado_pct")))
        checar("e o ffmpeg presente com a versao", s.get("ffmpeg") is True and "7.1" in (s.get("ffmpeg_versao") or ""),
               str(s.get("ffmpeg_versao")))
        checar("e o mediamtx ativo", s.get("mediamtx") is True)
        checar("e os dispositivos de video contados", s.get("dispositivos") == 5, str(s.get("dispositivos")))
        checar("e a varredura (quantos viu)", s.get("varredura") == 5, str(s.get("varredura")))
        checar("e a versao do app que esta' rodando no barco", s.get("versao_app") == "0.12.0",
               str(s.get("versao_app")))
        sinais = s.get("sinais") or []
        checar("vem a lista de sinais com limiar e 'o que fazer'",
               bool(sinais) and all("limiar" in x and "o_que_fazer" in x for x in sinais),
               f"{len(sinais)} sinais")

        print("\n== 2. a TELA do admin (area unica) desenha os numeros ==")
        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            pag = navegador.new_context().new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())
            pag.goto(base + "/entrada/")
            pag.fill("#email", "admin@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector("button[data-tela=empresas]", timeout=ESPERA)
            pag.wait_for_load_state("networkidle")
            pag.locator(".cartao-empresa").filter(has_text="Petrobras").locator("text=Abrir").first.click()
            pag.wait_for_function("t => document.querySelector('#tela').innerText.includes(t)", arg="PSV LECSOR I",
                                  timeout=ESPERA)
            corpo = pag.inner_text("#tela")
            checar("a tela mostra 'CPU 42%'", "CPU 42%" in corpo, corpo[:400].replace("\n", " | "))
            checar("e a memoria '61%'", "61%" in corpo)
            checar("e o ffmpeg presente", "ffmpeg presente" in corpo)
            checar("e o mediamtx ativo", "mediamtx ativo" in corpo)
            checar("e o HD do radar", "HD do radar" in corpo)
            checar("sem erro de JS na tela", not erros, "; ".join(erros[:3]))
            navegador.close()

        print("\n== 3. SEGURANCA: a chave da licenca NAO sai inteira (so' os 4 ultimos) ==")
        maquinas = emb.get("maquinas") or []
        checar("a maquina aparece com os ultimos 4 digitos",
               bool(maquinas) and maquinas[0].get("licenca_ultimos4") == CHAVE[-4:], json.dumps(maquinas))
        checar("e a chave INTEIRA nao vai no corpo da resposta",
               CHAVE not in json.dumps(arv), "chave vazou!" if CHAVE in json.dumps(arv) else "ok, so' os 4")
        st, _c, ck2 = pedir("POST", base + "/api/entrar", {"email": "petrobras@lecsor.test", "senha": SENHA})
        ck_obs = ck2.split("sessao=")[1].split(";")[0]
        st, arv_obs, _ = pedir("GET", base + "/api/empresas", cookie=ck_obs)
        checar("o observador (Petrobras) ate' pode ver a area, mas a chave inteira NAO aparece",
               CHAVE not in json.dumps(arv_obs))
    finally:
        try:
            api.terminate(); api.wait(timeout=15)
        except Exception:  # noqa: BLE001
            pass

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} prova(s): " + "; ".join(falhas))
        return 1
    print("OK: a area unica mostra saude e desempenho, e a chave da licenca nunca sai inteira.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
