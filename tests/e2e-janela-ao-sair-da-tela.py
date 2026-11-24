#!/usr/bin/env python3
"""Prova de TELA: a janela de 60 s ao sair da tela ao vivo + o card abaixo da imagem (24/11/2026).

Dono, verbatim: *"eu saio da página de transmissão ao vivo, retorno a ela e a transmissão continua ativa,
tem algum espaço de tempo para encerrar a transmissão? seria bom determinarmos, talvez, 60s após sairmos da
página, encerrar a transmissão, assim, se o cliente precisar ver outras coisas enquanto acompanha o vídeo
do radar, ele não tem que ficar reconectando"*.

E, na mesma rodada: *"remover as informações e botões de cima da imagem, criar card abaixo da imagem da
câmera"* + *"a imagem da câmera deve ocupar todo o espaço destinado a ela, removendo as faixas pretas
laterais"*.

O que se prova, num Chromium de verdade contra a API de verdade:

  1) a GRADE: o card de informacoes/acoes fica ABAIXO da imagem (nada de controle por cima do video) e a
     imagem entra com `object-fit:cover` (a imagem ocupa o espaco, sem as faixas pretas laterais);
  2) o batimento SO' acontece na tela das cameras: sair para outra tela e ficar 13 s NAO avanca o
     `batimento_em` da sessao (antes o batimento corria em qualquer tela e a sessao nunca expirava);
  3) sair e VOLTAR dentro da janela mantem a sessao de pe (o botao continua "Parar transmissao",
     NAO vira "Reconectar") — o cliente ve outras coisas sem reconectar;
  4) fora da tela por mais que a janela, o lado terra encerra sozinho: a sessao fecha e, ao voltar,
     o botao esta "Reconectar" (e o historico diz que ele saiu da tela ao vivo).

    python tests/e2e-janela-ao-sair-da-tela.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
SENHA = "senha-da-prova-da-janela"
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


# ---------------------------------------------------------------- leitura/escrita no banco da prova
def sessoes_abertas(banco: pathlib.Path) -> int:
    con = sqlite3.connect(str(banco))
    n = con.execute("SELECT count(*) FROM transmissoes WHERE estado IN ('pedida','no_ar')").fetchone()[0]
    con.close()
    return int(n)


def batimento_em(banco: pathlib.Path) -> str:
    """O carimbo do ultimo `estou aqui` da sessao viva (string vazia se nao ha sessao)."""
    con = sqlite3.connect(str(banco))
    r = con.execute("""SELECT batimento_em FROM transmissoes WHERE estado IN ('pedida','no_ar')
                       ORDER BY criada_em DESC LIMIT 1""").fetchone()
    con.close()
    return (r[0] if r and r[0] else "")


def envelhecer_batimento(banco: pathlib.Path, segundos: int) -> None:
    """Adianta o relogio: o ultimo 'estou aqui' passa a ser de `segundos` atras (sem esperar 60 s)."""
    quando = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=segundos)).isoformat(timespec="seconds")
    con = sqlite3.connect(str(banco))
    con.execute("UPDATE transmissoes SET batimento_em=? WHERE estado IN ('pedida','no_ar')", (quando,))
    con.commit(); con.close()


# O JS da prova usa `[data-papel=xxx]` SEM aspas: valor de atributo que e' identificador valido nao
# precisa de aspas no CSS, e assim a string do Python nao carrega aspas escapadas.
JS_PARAR_VISIVEL = ("() => { const b = document.querySelector('.controle-transmissao [data-papel=parar]');"
                    " return b && getComputedStyle(b).display !== 'none'; }")
JS_INICIAR_RECONECTAR = ("() => { const b = document.querySelector('.controle-transmissao [data-papel=iniciar]');"
                         " return !!b && b.innerText.toLowerCase().includes('reconectar'); }")


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-janela-"))
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

            print("\n== 1. a GRADE: o card fica ABAIXO da imagem e a imagem preenche o espaco ==")
            jan = pag.locator(".janela").first
            checar("a janela tem a area da imagem (.img-cam) e o card (.card-cam)",
                   jan.locator(".img-cam").count() == 1 and jan.locator(".card-cam").count() == 1)
            pos = pag.evaluate("""() => {
                const j = document.querySelector('.janela');
                const img = j.querySelector('.img-cam').getBoundingClientRect();
                const card = j.querySelector('.card-cam').getBoundingClientRect();
                return {topoImg: img.top, baseImg: img.bottom, topoCard: card.top, baseCard: card.bottom};
            }""")
            checar("o card comeca onde a imagem termina (abaixo dela)",
                   pos["topoCard"] >= pos["baseImg"] - 1.5, str(pos))
            checar("o controle de transmissao mora DENTRO do card (nao sobre o video)",
                   jan.locator(".card-cam > .controle-transmissao").count() == 1
                   and jan.locator(".janela > .controle-transmissao").count() == 0)
            filhos = pag.evaluate("""() => {
                const j = document.querySelector('.janela');
                return Array.from(j.children).map((e) => e.className).sort().join('|');
            }""")
            checar("so' a area da imagem e o card sao filhos da janela", filhos == "card-cam|img-cam", filhos)
            # 0.13.1 -> 0.13.2: o `cover` CORTava a imagem (dono, 24/11/2026) — a area da imagem passou a
            # ter a proporcao da camera e o video entra por `contain` (imagem inteira, sem faixa preta).
            checar("a imagem entra com object-fit:contain (imagem inteira, sem corte)",
                   pag.evaluate("() => getComputedStyle(document.querySelector('.janela video')).objectFit")
                   == "contain")

            print("\n== 2. iniciar a transmissao, sair para OUTRA tela e o batimento PARA ==")
            pag.locator('.controle-transmissao [data-papel="iniciar"]').click()
            pag.wait_for_function(JS_PARAR_VISIVEL, timeout=ESPERA)
            checar("a sessao abriu (1 aberta)", sessoes_abertas(banco) == 1, f"{sessoes_abertas(banco)} abertas")
            t0 = batimento_em(banco)
            pag.click('.item[data-tela="relatorios"]')
            pag.wait_for_function("() => document.querySelectorAll('.janela').length === 0", timeout=ESPERA)
            pag.wait_for_timeout(13000)          # mais que o tick do batimento (10 s)
            t1 = batimento_em(banco)
            checar("fora da tela ao vivo o 'estou aqui' NAO avanca (batimento parou)", t0 == t1,
                   f"antes={t0} agora={t1}")
            checar("e a sessao continua de pe (dentro da janela)", sessoes_abertas(banco) == 1)

            print("\n== 3. voltar dentro da janela mantem a sessao (nada de reconectar) ==")
            pag.click('.item[data-tela="visualizar"]')
            pag.wait_for_selector(".controle-transmissao", timeout=ESPERA)
            pag.wait_for_timeout(1500)
            checar("o batimento volta NA HORA ao entrar na tela", batimento_em(banco) != t0,
                   f"antes={t0} agora={batimento_em(banco)}")
            checar("a sessao seguiu aberta", sessoes_abertas(banco) == 1)
            checar("o botao NAO virou 'Reconectar'",
                   "parar transmiss" in pag.inner_text('.controle-transmissao [data-papel="parar"]').lower(),
                   pag.inner_text('.controle-transmissao [data-papel="parar"]'))

            print("\n== 4. fora da tela por mais que a janela: o lado terra encerra sozinho ==")
            pag.click('.item[data-tela="relatorios"]')
            pag.wait_for_function("() => document.querySelectorAll('.janela').length === 0", timeout=ESPERA)
            envelhecer_batimento(banco, 120)     # o ultimo 'estou aqui' passa a ser de 2 min atras
            limite = time.time() + 30
            while time.time() < limite and sessoes_abertas(banco) != 0:
                time.sleep(0.5)
            checar("a sessao foi encerrada pelo vigia do lado terra (sem ninguem clicar)",
                   sessoes_abertas(banco) == 0, f"{sessoes_abertas(banco)} abertas")
            pag.click('.item[data-tela="visualizar"]')
            pag.wait_for_selector(".controle-transmissao", timeout=ESPERA)
            try:
                pag.wait_for_function(JS_INICIAR_RECONECTAR, timeout=ESPERA)
            except Exception:  # noqa: BLE001
                pass
            checar("e ao voltar o botao esta 'Reconectar'",
                   "reconectar" in pag.inner_text('.controle-transmissao [data-papel="iniciar"]').lower(),
                   pag.inner_text('.controle-transmissao [data-papel="iniciar"]'))

            print("\n== 5. o motivo do encerramento explica a saida da tela ==")
            con = sqlite3.connect(str(banco))
            linha = con.execute("SELECT estado, motivo FROM transmissoes ORDER BY criada_em DESC LIMIT 1").fetchone()
            con.close()
            checar("o historico diz que ele saiu da tela ao vivo",
                   bool(linha) and "tela ao vivo" in (linha[1] or ""), str(linha))
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
    print("OK: a janela de 60 s ao sair da tela e o card abaixo da imagem funcionam.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
