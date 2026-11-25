#!/usr/bin/env python3
"""Prova de TELA e de EFEITO (plano de 19/11/2026, Fase 4 — Petrobras: radar de oleo de todas as empresas).

O dono (19/11/2026): "temos 4 tipos de clientes ... 4. cliente que pode ver todas as embarcacoes de todas
as empresas (petrobras) ... o mais importante hoje e' o radar de oleo e o acesso da petrobras".

Aqui se prova, com navegador de verdade (Chromium do Playwright) e API de verdade, que o papel
`observador` (tipo 4):

  1) entra e cai no radar: a tela dele NAO tem cadastro, transmissao, alertas, relatorios nem cameras;
  2) ve' o HD do radar das DUAS empresas (a tabela diz de qual embarcacao e' cada trecho);
  3) ve' o radar AO VIVO das duas embarcacoes (a lista vem do servidor: so' radar, nunca camera comum);
  4) nao consegue cadastrar nada (a rota recusa);
  5) e o isolamento do cliente comum continua: o cliente da Empresa A NAO ve' o radar da Empresa B;
  6) sem erro de javascript na tela.

    python tests/e2e-observador-do-radar.py
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

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = "senha-do-observador-de-teste"
ESPERA = 20000
EMPRESA_A, EMPRESA_B = "empresa-a-teste", "empresa-b-teste"
EMB_A, EMB_B = "emb-a-teste", "emb-b-teste"
RADAR_A, CAM_A = "radar-oleo-a-teste", "cam-conves-a-teste"
RADAR_B, CAM_B = "radar-oleo-b-teste", "cam-popa-b-teste"


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


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str, cliente_id=None) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    """Duas empresas, cada uma com um radar de oleo (com HD publicado) e uma camera comum."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA_A, "Empresa A (teste)"))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA_B, "Empresa B (teste)"))
    for eid, cid, nome in ((EMB_A, EMPRESA_A, "Embarcacao A"), (EMB_B, EMPRESA_B, "Embarcacao B")):
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado,radar_fonte)"
                    " VALUES (?,?,?,?,?,?)", (eid, cid, nome, "", "em operacao", "dshow:EZCAP"))
    for cid, eid, rotulo, alvo, tipo in ((RADAR_A, EMB_A, "Radar de oleo (A)", "radar-ppi", "radar"),
                                         (CAM_A, EMB_A, "Camera do conves (A)", "", "camera"),
                                         (RADAR_B, EMB_B, "Radar de oleo (B)", "radar-ppi", "radar"),
                                         (CAM_B, EMB_B, "Camera da popa (B)", "", "camera")):
        con.execute("""INSERT OR REPLACE INTO cameras
                       (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                       VALUES (?,?,?,?,'',1,'','','dshow','',?,?)""", (cid, eid, rotulo, cid, alvo, tipo))
    # O HD do radar de cada embarcacao (o que o PC de captura publica; aqui o catalogo e' do teste)
    for cid, eid, hora in ((RADAR_A, EMB_A, "2026-11-19T08:00:00"), (RADAR_B, EMB_B, "2026-11-19T09:30:00")):
        blocos = [{"arquivo": f"{hora[11:13]}-00.mp4", "inicio": hora, "bytes": 1_500_000, "segundos": 300}]
        con.execute("INSERT OR REPLACE INTO hd_catalogo (embarcacao_id,camera_id,resumo,blocos,atualizado_em)"
                    " VALUES (?,?,?,?,?)",
                    (eid, cid, json.dumps({"total": 1_500_000, "blocos": 1}), json.dumps(blocos),
                     "2026-11-19T10:00:00"))
    con.commit()
    con.close()


def entrar(pag, base: str, email: str, espera: str) -> None:
    pag.goto(base + "/entrada/")
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector(espera, timeout=ESPERA)
    pag.wait_for_load_state("networkidle")


def visivel(pag, sel: str) -> bool:
    try:
        return pag.is_visible(sel, timeout=2500)
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-observador-"))
    banco = tmp / "pipeline.db"
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
        criar_usuario(banco, "petrobras", "petrobras@petrobras.test", "observador")
        criar_usuario(banco, "cliente-a", "cliente@empresa-a.test", "cliente", EMPRESA_A)
        semear(banco)

        # ---- o que o SERVIDOR entrega ao observador (a defesa esta' aqui, nao na tela)
        req = urllib.request.Request(base + "/api/entrar", method="POST",
                                     data=json.dumps({"email": "petrobras@petrobras.test",
                                                      "senha": SENHA}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            cookie = (r.headers.get("Set-Cookie") or "").split(";")[0]

        def pedir(rota: str):
            rq = urllib.request.Request(base + rota, headers={"Cookie": cookie})
            try:
                with urllib.request.urlopen(rq, timeout=5) as r:
                    return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")

        s, j = pedir("/api/cameras")
        ids = {c["id"] for c in j.get("cameras", [])}
        checar("o observador ve' o radar das duas empresas",
               {RADAR_A, RADAR_B} <= ids, f"veio {sorted(ids)}")
        checar("e NAO ve camera comum nenhuma",
               not ({CAM_A, CAM_B} & ids), f"veio {sorted(ids)}")

        s, j = pedir("/api/hd/catalogo")
        cats = j.get("catalogos") or []
        nomes = {c.get("embarcacao_nome") for c in cats}
        checar("o catalogo do HD tem o radar das duas empresas (2 catalogos)", len(cats) == 2,
               f"{len(cats)} catalogo(s): {sorted(nomes)}")
        checar("o catalogo diz de qual embarcacao e' cada trecho",
               {"Embarcacao A", "Embarcacao B"} <= nomes, f"{sorted(nomes)}")

        s, j = pedir("/api/embarcacoes")
        checar("o observador ve' embarcacoes das duas empresas",
               {EMB_A, EMB_B} <= {e["id"] for e in j.get("embarcacoes", [])})

        s, j = pedir("/api/analises")
        checar("o observador nao recebe analytics", s == 200 and not (j.get("agentes") or j.get("contagens")),
               f"http {s}")

        # cadastrar e' do admin: o observador nao tem esse poder (nem por API)
        rq = urllib.request.Request(base + "/api/cameras", method="POST",
                                    data=json.dumps({"id": "x", "rotulo": "x", "fluxo_id": "x"}).encode(),
                                    headers={"Content-Type": "application/json", "Cookie": cookie})
        try:
            urllib.request.urlopen(rq, timeout=5)
            checar("o observador NAO consegue cadastrar camera", False, "aceitou o cadastro")
        except urllib.error.HTTPError as e:
            checar("o observador NAO consegue cadastrar camera", e.code in (401, 403), f"http {e.code}")

        # o cliente comum continua isolado na empresa dele (tipo 3 preservado)
        req = urllib.request.Request(base + "/api/entrar", method="POST",
                                     data=json.dumps({"email": "cliente@empresa-a.test",
                                                      "senha": SENHA}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r2:
            cookie_c = (r2.headers.get("Set-Cookie") or "").split(";")[0]
        rq = urllib.request.Request(base + "/api/hd/catalogo", headers={"Cookie": cookie_c})
        with urllib.request.urlopen(rq, timeout=5) as r3:
            jc = json.loads(r3.read().decode("utf-8", "replace") or "{}")
        ids_c = {c["camera_id"] for c in (jc.get("catalogos") or [])}
        checar("o cliente da Empresa A ve' so' o radar da empresa dele",
               RADAR_A in ids_c and RADAR_B not in ids_c, f"{sorted(ids_c)}")

        # ---- a TELA do observador
        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            pag = navegador.new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            entrar(pag, base, "petrobras@petrobras.test", "#palco")

            checar("o cabecalho diz que e' observador",
                   "Observador" in pag.inner_text("#conta-papel"), pag.inner_text("#conta-papel"))
            checar("a tela abre no RADAR AO VIVO (o menu marca 'Radar ao vivo')",
                   visivel(pag, ".lateral .item[data-tela=visualizar].on"), pag.inner_text("#titulo-tela"))
            for tela, nome in (("cameras", "Cameras"), ("pessoas", "Pessoas"),
                               ("transmissao", "Transmitir"), ("configuracao", "Tempo de transmissao"),
                               ("alertas", "Alertas"), ("relatorios", "Relatorios")):
                checar(f"a tela do observador nao oferece {nome}",
                       not visivel(pag, f".lateral .item[data-tela={tela}]"))

            # ---- radar AO VIVO: o seletor lista as embarcacoes de TODAS as empresas
            pag.wait_for_function(
                "() => /Radar de oleo \\(A\\)/.test(document.querySelector('#palco').innerText)",
                timeout=ESPERA)
            palco = pag.inner_text("#palco")
            checar("o radar ao vivo da primeira embarcacao aparece", "Radar de oleo (A)" in palco,
                   palco[:160].replace("\n", " | "))
            checar("nenhuma camera comum aparece na tela do observador",
                   "Camera do conves (A)" not in palco and "Camera da popa (B)" not in palco,
                   palco[:160].replace("\n", " | "))
            opcoes = [pag.locator("#embarcacao option").nth(i).get_attribute("value")
                      for i in range(pag.locator("#embarcacao option").count())]
            checar("o seletor de embarcacao esta' visivel com o grupo inteiro",
                   visivel(pag, "#embarcacao") and {EMB_A, EMB_B} <= set(opcoes), f"{opcoes}")

            pag.select_option("#embarcacao", EMB_B)
            pag.wait_for_function(
                "() => /Radar de oleo \\(B\\)/.test(document.querySelector('#palco').innerText)",
                timeout=ESPERA)
            checar("escolhendo a outra embarcacao, o radar da OUTRA empresa aparece",
                   "Radar de oleo (B)" in pag.inner_text("#palco"),
                   pag.inner_text("#palco")[:160].replace("\n", " | "))

            # ---- o HD do radar: os trechos das DUAS empresas numa tabela so'
            pag.click(".lateral .item[data-tela=radar_hd]")
            pag.wait_for_function(
                "() => /Embarcacao A/.test(document.querySelector('#palco').innerText) && "
                "/Embarcacao B/.test(document.querySelector('#palco').innerText)",
                timeout=ESPERA)
            corpo = pag.inner_text("#palco")
            checar("o HD lista os trechos do radar das DUAS empresas na mesma tabela",
                   "Embarcacao A" in corpo and "Embarcacao B" in corpo,
                   corpo[:200].replace("\n", " | "))
            checar("a tabela do HD diz de qual embarcacao e' cada trecho (coluna propria)",
                   "Embarca" in corpo.split("\n")[0] or "Embarca" in corpo[:80],
                   corpo[:80].replace("\n", " | "))

            checar("sem erro de javascript na tela do observador", not erros, "; ".join(erros[:3]))
            navegador.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            api.kill()
        log.close()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s): " + "; ".join(falhas))
        return 1
    print("RESULTADO: tudo passou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
