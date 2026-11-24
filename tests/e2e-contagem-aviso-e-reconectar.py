#!/usr/bin/env python3
"""Prova de TELA: a contagem regressiva, o aviso do ultimo minuto e o "Reconectar" (Fase 3, 24/11/2026).

Dono, verbatim: *"precisa de um timer de contagem regressiva de acordo com a configuracao de tempo de
streaming para o cliente saber em quanto tempo as cameras serao desconectadas, e antes de desconectar, uma
mensagem perguntando se quer continuar conectado, se clicar em nao ou se nao houver resposta dentro de um
tempo determinado, desconecta, ai aparece um botao 'reconectar' para caso o cliente queira voltar a ver as
imagens"*. Decisoes: D1 = 1 minuto de aviso; D2 = silencio (nao agir) DESLIGA.

Antes desta rodada nada disso existia na tela que o cliente usa (a GRADE): o contador/gravar/comecar-parar
moravam na tela "Transmitir". Agora moram na grade, em cada janela.

O que se prova, num Chromium de verdade contra a API de verdade:

  1) a janela da grade tem o controle de transmissao e o botao "Iniciar transmissao";
  2) ao iniciar, aparece a CONTAGEM (mm:ss) e os botoes de gravar/parar;
  3) no ULTIMO MINUTO surge o aviso "quer continuar conectado?" (D1);
  4) "Continuar conectado" RENOVA o tempo (a contagem volta ao topo da janela configurada);
  5) sem resposta (silencio) a sessao EXPIRA no prazo (D2) e o botao vira "Reconectar";
  6) "Reconectar" poe a camera no ar de novo.

    python tests/e2e-contagem-aviso-e-reconectar.py
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
SENHA = "senha-da-prova-de-contagem"
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
ESPERA = 20000


def rotulo(pag, sel: str) -> str:
    """O NOME ACESSIVEL do botao (o que o cliente le no `title`/`aria-label`).

    Desde 24/11/2026 os botoes da grade sao ICONES com o nome completo em `title`/`aria-label` — o
    `innerText` so' traz o glifo. A prova mede o nome acessivel, que e' o que o leitor de tela e o
    proprio cliente usam.
    """
    return pag.evaluate("""(s) => { const e = document.querySelector(s);
        return e ? ((e.getAttribute('title') || '') + ' ' + (e.getAttribute('aria-label') || '')
                    + ' ' + e.innerText) : ''; }""", sel)


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


def ajustar_termina(banco: pathlib.Path, segundos: int) -> None:
    """Adianta/recua o fim da sessao viva — o relogio controlado da prova (sem esperar 15 min).

    O carimbo vai no MESMO formato que o servidor grava (ISO-8601 com offset UTC), senao o
    `new Date(...)` do navegador interpretaria como hora local e a contagem sairia errada.
    """
    quando = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=segundos)).isoformat(timespec="seconds")
    con = sqlite3.connect(str(banco))
    con.execute("UPDATE transmissoes SET termina_em=? WHERE estado IN ('pedida','no_ar')", (quando,))
    con.commit(); con.close()


def segundos_restantes(banco: pathlib.Path) -> int:
    con = sqlite3.connect(str(banco))
    r = con.execute("""SELECT termina_em FROM transmissoes WHERE estado IN ('pedida','no_ar')
                       ORDER BY criada_em DESC LIMIT 1""").fetchone()
    con.close()
    if not r or not r[0]:
        return -1
    quando = dt.datetime.fromisoformat(r[0])
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=dt.timezone.utc)
    return int((quando - dt.datetime.now(dt.timezone.utc)).total_seconds())


def sessoes_abertas(banco: pathlib.Path) -> int:
    con = sqlite3.connect(str(banco))
    n = con.execute("SELECT count(*) FROM transmissoes WHERE estado IN ('pedida','no_ar')").fetchone()[0]
    con.close()
    return int(n)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-contagem-"))
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

            print("\n== 1. a GRADE (tela que o cliente usa) tem o controle de transmissao ==")
            checar("a janela traz o controle com 'Iniciar transmissao'",
                   pag.locator('.controle-transmissao [data-papel="iniciar"]').count() == 1)
            checar("e o estado inicial e' 'parada'",
                   "parada" in pag.inner_text(".controle-transmissao").lower(),
                   pag.inner_text(".controle-transmissao"))

            print("\n== 2. iniciar -> a CONTAGEM e os botoes aparecem ==")
            pag.locator('.controle-transmissao [data-papel="iniciar"]').click()
            pag.wait_for_function("t => /\\d\\d:\\d\\d/.test(document.querySelector('.st-contagem').innerText)",
                                  timeout=ESPERA)
            checar("a contagem mm:ss aparece na janela",
                   bool(pag.inner_text(".st-contagem").strip()), pag.inner_text(".st-contagem"))
            checar("e o botao de GRAVAR aparece com a sessao",
                   pag.locator('.controle-transmissao [data-papel="gravar"]').is_visible())
            checar("e o botao de PARAR transmissao aparece",
                   pag.locator('.controle-transmissao [data-papel="parar"]').is_visible())

            print("\n== 3. no ULTIMO MINUTO o aviso 'quer continuar conectado?' aparece (D1) ==")
            # NAO recarregar: fechar/recarregar a pagina encerra a sessao (o `sendBeacon` do
            # beforeunload manda o "encerrar") — e' justamente o comportamento correto. Aqui o
            # cliente SEGUE na tela; so' o fim da sessao foi adiantado no banco.
            ajustar_termina(banco, 30)
            pag.wait_for_selector('.st-aviso.mostra', timeout=ESPERA + 15000)
            checar("o aviso do ultimo minuto aparece",
                   pag.locator('.st-aviso.mostra').is_visible())
            checar("e pergunta se quer continuar",
                   "continuar conectado" in pag.inner_text(".st-aviso").lower(),
                   pag.inner_text(".st-aviso"))

            print("\n== 4. 'Continuar conectado' RENOVA o tempo (a contagem volta ao topo) ==")
            pag.locator('.st-aviso [data-papel="continuar"]').click()
            pag.wait_for_timeout(1500)
            resta = segundos_restantes(banco)
            checar("o tempo da sessao foi renovado (>> 60 s)", resta > 300, f"{resta}s restantes")

            print("\n== 5. silencio DESLIGA (D2): sem resposta, a sessao expira e vira 'Reconectar' ==")
            ajustar_termina(banco, 3)
            # O botao e' um ICONE (⟳) com o nome em `title`/`aria-label` -> mede-se o NOME ACESSIVEL.
            pag.wait_for_function("() => { const b = document.querySelector('.controle-transmissao [data-papel=\"iniciar\"]');"
                                  " return !!(b && ((b.getAttribute('title') || '') + ' ' + (b.getAttribute('aria-label') || '')"
                                  " + ' ' + b.innerText).toLowerCase().includes('reconectar')); }", timeout=ESPERA + 10000)
            checar("a sessao expirou sozinha (nenhuma aberta)", sessoes_abertas(banco) == 0,
                   f"{sessoes_abertas(banco)} abertas")
            checar("e o botao virou 'Reconectar'",
                   "reconectar" in rotulo(pag, '.controle-transmissao [data-papel="iniciar"]').lower(),
                   rotulo(pag, '.controle-transmissao [data-papel="iniciar"]'))

            print("\n== 6. 'Reconectar' poe a camera no ar de novo ==")
            pag.locator('.controle-transmissao [data-papel="iniciar"]').click()
            pag.wait_for_function("() => document.querySelectorAll('.controle-transmissao [data-papel=\"parar\"]')"
                                  ".length && getComputedStyle(document.querySelector('.controle-transmissao "
                                  "[data-papel=\"parar\"]')).display !== 'none'", timeout=ESPERA)
            checar("a sessao voltou (o botao de parar reapareceu)", sessoes_abertas(banco) == 1,
                   f"{sessoes_abertas(banco)} abertas")
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
    print("OK: contagem, aviso do ultimo minuto, silencio-desliga e 'Reconectar' funcionam na GRADE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
