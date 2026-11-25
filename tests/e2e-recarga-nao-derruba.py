#!/usr/bin/env python3
"""Prova de TELA/API: RECARREGAR a pagina NAO derruba a transmissao (0.17.0).

Dono, verbatim (25/11/2026): *"quando recarrego a pagina, a transmissao e' interrompida"*.

O `pagehide` dispara IGUAL em F5 e em fechar a aba, entao o pedido de saida vai marcado `pendente` e o
lado terra o SEGURA por `SEGUNDOS_DE_CARENCIA` (8 s): se a pagina volta (recarga), o `baterPonto` cancela
o pedido; se nao volta, o vigia executa a saida. A saida PEDIDA pelo cliente (botao "parar transmissao"/
"Sair") continua valendo NA HORA, sem carencia.

O que se prova, contra a API de verdade:

  1) `pendente: true` no encerrar NAO fecha a sessao (responde `pendente: true` com a carencia) e a sessao
     continua aberta no banco;
  2) um batimento (a pagina voltou) CANCELA o pedido: a sessao segue aberta;
  3) sem ninguem voltar, o VIGIA executa a saida pendente depois da carencia (a sessao fecha sozinha);
  4) o encerrar PEDIDO pelo cliente (sem `pendente`) fecha NA HORA — a carencia nao adia a vontade dele;
  5) num Chromium de verdade: com a transmissao no ar, RECARREGAR a pagina (F5) mantem a sessao aberta e
     o botao continua "Parar transmissao" (nada de "Reconectar").

    python tests/e2e-recarga-nao-derruba.py
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

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = "senha-da-prova-da-recarga"
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
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


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str, cliente_id: str | None) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    con.commit(); con.close()


def semear(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                   VALUES (?,?,'Proa',?,'bordo',1,'800k')""", (CAM, EMB, CAM))
    con.commit(); con.close()


def sessoes_abertas(banco: pathlib.Path) -> int:
    con = sqlite3.connect(str(banco))
    n = con.execute("SELECT count(*) FROM transmissoes WHERE estado IN ('pedida','no_ar')").fetchone()[0]
    con.close()
    return int(n)


def rotulo(pag, sel: str) -> str:
    return pag.evaluate("""(s) => { const e = document.querySelector(s);
        return e ? ((e.getAttribute('title') || '') + ' ' + (e.getAttribute('aria-label') || '')
                    + ' ' + e.innerText) : ''; }""", sel)


def _abrir_html(resp) -> bytes:
    return resp.read()


class Cliente:
    """Cliente HTTP com cookie de sessao (o mesmo caminho do navegador)."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def json(self, metodo: str, caminho: str, corpo: dict | None = None) -> tuple[int, dict]:
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + caminho, data=dados, method=metodo,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.abridor.open(req, timeout=10) as r:
                bruto = _abrir_html(r)
                return r.status, (json.loads(bruto) if bruto else {})
        except urllib.error.HTTPError as e:
            bruto = e.read()
            try:
                return e.code, (json.loads(bruto) if bruto else {})
            except Exception:  # noqa: BLE001
                return e.code, {}


def principal() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-recarga-"))
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

        criar_usuario(banco, "cli", "cliente@lecsor.test", "cliente", EMPRESA)
        semear(banco)

        print("\n== 1. o pedido de saida com `pendente` e' SEGURADO, nao executado")
        cli = Cliente(base)
        cod, _ = cli.json("POST", "/api/entrar", {"email": "cliente@lecsor.test", "senha": SENHA})
        checar("o cliente entrou", cod == 200, f"HTTP {cod}")
        cod, r = cli.json("POST", "/api/transmissao/iniciar", {"camera_id": CAM})
        checar("a transmissao abriu", cod in (200, 201) and bool(r.get("transmissao")), f"HTTP {cod} {r}")
        tid = (r.get("transmissao") or {}).get("id", "")
        checar("e a sessao esta aberta (1)", sessoes_abertas(banco) == 1, f"{sessoes_abertas(banco)} aberta(s)")

        cod, r = cli.json("POST", f"/api/transmissao/{tid}/encerrar", {"pendente": True})
        checar("o encerrar `pendente` responde `pendente: true` com a carencia",
               cod == 200 and r.get("pendente") is True and r.get("carencia_s") == 8, f"HTTP {cod} {r}")
        checar("e a sessao CONTINUA aberta (a recarga nao derruba)",
               sessoes_abertas(banco) == 1, f"{sessoes_abertas(banco)} aberta(s)")

        print("\n== 2. a pagina voltou (batimento) CANCELA o pedido pendente")
        cod, r = cli.json("POST", f"/api/transmissao/{tid}/batimento")
        checar("o batimento foi aceito", cod == 200, f"HTTP {cod} {r}")
        checar("a sessao segue aberta", sessoes_abertas(banco) == 1, f"{sessoes_abertas(banco)} aberta(s)")

        print("\n== 3. sem ninguem voltar, o VIGIA executa a saida depois da carencia")
        cod, r = cli.json("POST", f"/api/transmissao/{tid}/encerrar", {"pendente": True})
        checar("o pedido pendente foi anotado de novo", cod == 200 and r.get("pendente") is True, f"{r}")
        limite = time.time() + 25
        while time.time() < limite and sessoes_abertas(banco) != 0:
            time.sleep(0.5)
        checar("o vigia fechou a sessao sozinho (a carencia passou)", sessoes_abertas(banco) == 0,
               f"{sessoes_abertas(banco)} aberta(s)")

        print("\n== 4. a saida PEDIDA pelo cliente fecha NA HORA (sem carencia)")
        cod, r = cli.json("POST", "/api/transmissao/iniciar", {"camera_id": CAM})
        tid2 = (r.get("transmissao") or {}).get("id", "")
        checar("nova transmissao aberta", sessoes_abertas(banco) == 1, f"{sessoes_abertas(banco)} aberta(s)")
        cod, r = cli.json("POST", f"/api/transmissao/{tid2}/encerrar", {})
        checar("o encerrar sem `pendente` fecha imediatamente", sessoes_abertas(banco) == 0,
               f"HTTP {cod} {r}; {sessoes_abertas(banco)} aberta(s)")

        print("\n== 5. num Chromium de verdade, RECARREGAR (F5) mantem a transmissao")
        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            pag = navegador.new_context().new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())
            pag.goto(base + "/entrada/")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector(".controle-transmissao", timeout=ESPERA)
            pag.wait_for_load_state("networkidle")
            pag.locator('.controle-transmissao [data-papel="iniciar"]').click()
            pag.wait_for_function("() => { const b = document.querySelector('.controle-transmissao [data-papel=parar]');"
                                  " return b && getComputedStyle(b).display !== 'none'; }", timeout=ESPERA)
            checar("a transmissao subiu no navegador (1 aberta)", sessoes_abertas(banco) == 1,
                   f"{sessoes_abertas(banco)} aberta(s)")
            pag.reload(wait_until="load")
            pag.wait_for_selector(".controle-transmissao", timeout=ESPERA)
            pag.wait_for_timeout(2000)
            checar("depois do F5 a sessao CONTINUA aberta (a recarga nao derrubou)",
                   sessoes_abertas(banco) == 1, f"{sessoes_abertas(banco)} aberta(s)")
            checar("e o botao continua 'Parar transmissao' (nao virou 'Reconectar')",
                   "parar transmiss" in rotulo(pag, '.controle-transmissao [data-papel="parar"]').lower(),
                   rotulo(pag, '.controle-transmissao [data-papel="parar"]'))
            checar("sem erro de JS na tela", not erros, "; ".join(erros[:3]))
            navegador.close()
    finally:
        try:
            api.terminate(); api.wait(timeout=15)
        except Exception:  # noqa: BLE001
            pass

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} prova(s): " + "; ".join(falhas))
        return 1
    print("OK: recarregar a pagina nao derruba a transmissao.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
