#!/usr/bin/env python3
"""Prova de TELA: o CLIENTE abre a transmissao pela web (sem instalar app) e a ordem vai ao bordo.

Sobe a API de verdade (banco proprio, contas de demonstracao) e abre a tela do cliente `/app` num
navegador de verdade (Chromium do Playwright). O que se prova, olhando a tela:
  1) o cliente entra pela WEB e ve a tela "Transmitir" (sem aplicativo instalado, sem menu de operacao);
  2) "Iniciar transmissao" cria o pedido e a tela diz em voz alta que a ordem foi para a maquina de captura;
  3) a ordem chega ao BORDO (simulado pela rota do agente) e, contada como atendida, a tela mostra
     "no ar" com o tempo restante;
  4) dois clientes da mesma empresa: um clica "Parar" e o OUTRO continua vendo (corte por sessao);
  5) fechar a tela derruba SO' a sessao de quem fechou; quando ninguem mais esta' vendo, a camera para;
  6) ninguem batendo (computador desligado) -> a sessao morre sozinha e a camera para (tempo real);
  7) a tela "Tempo de transmissao" grava o tempo do cliente e o proximo pedido sai com esse tempo.

    LECSOR_SENHA_DEMO=... python tests/e2e-transmissao-na-tela.py
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
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "") or "senha-de-bancada-transmissao"
TOKEN = "token-de-teste-da-tela"


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


def pedir(metodo: str, url: str, corpo=None, token_bordo: str = ""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if token_bordo:
        cab["Authorization"] = f"Bearer {token_bordo}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=30) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def segundo_cliente(banco: pathlib.Path, email: str) -> None:
    """Segundo cliente da MESMA empresa (o caso "outro esta' vendo"): criado direto no banco."""
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con = sqlite3.connect(banco)
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES ('cli2',?,?,'cliente','lecsor',?,?,200000,1)""", (email, "Segundo cliente", senha, salt))
    con.commit()
    con.close()


def entrar(pag, base: str, email: str) -> None:
    pag.goto(base + "/app/")
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=20000)


def tela_transmitir(pag) -> None:
    pag.click('[data-tela="transmissao"]')
    pag.wait_for_selector(".transmissao-linha", timeout=20000)


def estado_da(pag, cam: str) -> str:
    return pag.locator(f'[data-estado="{cam}"]').inner_text().strip()


def esperar_texto(pag, cam: str, pedaco: str, limite: int = 15000) -> str:
    fim = time.time() + limite / 1000
    texto = ""
    while time.time() < fim:
        try:
            texto = estado_da(pag, cam)
        except Exception:
            texto = ""
        if pedaco.lower() in texto.lower():
            return texto
        pag.wait_for_timeout(400)
    return texto


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-transmissao-tela-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_SENHA_DEMO"] = SENHA
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["LECSOR_GRAVACOES_DIR"] = str(tmp / "gravacoes")   # gravacoes do teste fora do repositorio
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
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
        print("FALHA a API nao subiu:", (tmp / "api.log").read_text(errors="replace")[-400:])
        api.terminate()
        return 1
    segundo_cliente(banco, "segundo.cliente@lecsor.test")

    def estado_no_banco(tid):
        con = sqlite3.connect(banco)
        r = con.execute("SELECT estado, motivo, usuario_email FROM transmissoes WHERE id=?", (tid,)).fetchone()
        con.close()
        return r

    def limpar_fila():
        pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)

    def ordens(acao=""):
        con = sqlite3.connect(banco)
        sql = "SELECT id, acao, camera_id, estado FROM ordens_do_bordo"
        if acao:
            sql += f" WHERE acao='{acao}'"
        linhas = con.execute(sql).fetchall()
        con.close()
        return linhas

    navegador = None
    try:
        with sync_playwright() as pw:
            navegador = pw.chromium.launch(executable_path=_chromium())
            ctx_a = navegador.new_context(viewport={"width": 1500, "height": 900})
            ctx_b = navegador.new_context(viewport={"width": 1500, "height": 900})
            pag_a = ctx_a.new_page()
            erros: list[str] = []
            pag_a.on("pageerror", lambda e: erros.append(str(e)))

            # --- 1) cliente entra pela web -----------------------------------------------------------
            entrar(pag_a, base, "cliente@lecsor.test")
            checar("o cliente entrou pelo navegador, sem app instalado", pag_a.locator("#sistema").is_visible())
            itens = pag_a.eval_on_selector_all(".item[data-tela]", "bs => bs.map(b => b.dataset.tela)")
            checar("a tela do cliente tem 'Transmitir' e 'Tempo de transmissão'",
                   "transmissao" in itens and "configuracao" in itens, f"{itens}")
            checar("a tela do cliente NAO tem menu de operacao (Enviar vídeo)",
                   "envios" not in itens, f"{itens}")

            # --- 2) o cliente define quando inicia ----------------------------------------------------
            tela_transmitir(pag_a)
            cam = pag_a.eval_on_selector_all(".transmissao-linha", "ls => ls.map(l => l.dataset.camera)")[0]
            checar("a transmissao comeca PARADA, com o botao de iniciar", "parada" in estado_da(pag_a, cam).lower(),
                   estado_da(pag_a, cam))
            pag_a.click(f"#iniciar-{cam}")
            checar("clicando, a tela avisa que a ordem foi para a maquina de captura",
                   "pedido enviado" in esperar_texto(pag_a, cam, "pedido enviado").lower(),
                   estado_da(pag_a, cam))

            # --- 3) a ordem chega ao bordo e volta como "no ar" ----------------------------------------
            s, j = pedir("GET", base + f"/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)
            checar("a ordem de iniciar chegou ao bordo", s == 200 and len(j.get("ordens") or []) == 1, f"{j}")
            ordem = (j.get("ordens") or [{}])[0]
            pedir("POST", base + f"/api/ordens/{ordem.get('id')}/resultado",
                  {"estado": "atendida", "resultado": "camera no ar", "fluxo_id": cam}, token_bordo=TOKEN)
            texto = esperar_texto(pag_a, cam, "no ar")
            checar("a tela mostra NO AR com o tempo restante do cliente",
                   "no ar" in texto.lower() and "tempo restante" in texto.lower(), texto)
            checar("o botao virou 'Parar transmissão'", pag_a.locator(f"#parar-{cam}").count() == 1)
            # GRAVAR no lado terra: sem fluxo chegando nesta maquina a tela NAO pode dizer que grava
            pag_a.click(f"#gravar-{cam}")
            pag_a.wait_for_timeout(8000)
            texto_g = estado_da(pag_a, cam)
            checar("sem fluxo no ar, a tela nao finge que esta' gravando",
                   "Parar gravação" not in texto_g, texto_g)
            checar("e a transmissao continua no ar depois da recusa", "no ar" in texto_g.lower(), texto_g)

            # --- 4) corte por sessao: o outro cliente continua vendo -----------------------------------
            pag_b = ctx_b.new_page()
            pag_b.on("pageerror", lambda e: erros.append("B: " + str(e)))
            entrar(pag_b, base, "segundo.cliente@lecsor.test")
            tela_transmitir(pag_b)
            texto_b = estado_da(pag_b, cam)
            checar("o segundo cliente ve que outro esta' assistindo", "outro cliente" in texto_b.lower(), texto_b)
            pag_b.click(f"#iniciar-{cam}")
            esperar_texto(pag_b, cam, "pedido enviado")
            # o bordo tambem obedece o pedido do SEGUNDO cliente
            s, j = pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)
            for o in (j.get("ordens") or []):
                pedir("POST", base + f"/api/ordens/{o['id']}/resultado",
                      {"estado": "atendida", "resultado": "camera no ar", "fluxo_id": cam}, token_bordo=TOKEN)
            texto_b = esperar_texto(pag_b, cam, "a sua transmissão")
            checar("o segundo cliente abriu a mesma camera", "a sua transmissão" in texto_b, texto_b)
            pag_a.click(f"#parar-{cam}")
            pag_a.wait_for_timeout(1500)
            texto_a = estado_da(pag_a, cam)
            checar("quem para encerra so' a propria sessao (a tela diz quem continua vendo)",
                   "outro cliente" in texto_a.lower(), texto_a)
            texto_b = esperar_texto(pag_b, cam, "a sua transmissão")
            checar("o outro cliente continua vendo a transmissao", "a sua transmissão" in texto_b, texto_b)
            checar("e a camera NAO recebeu ordem de parar", not ordens("parar"), f"{ordens('parar')}")
            con = sqlite3.connect(banco)
            vivas = con.execute("SELECT COUNT(*) FROM transmissoes WHERE estado IN ('pedida','no_ar')").fetchone()[0]
            con.close()
            checar("sobra exatamente uma sessao viva (a do outro cliente)", vivas == 1, f"{vivas}")

            # --- 5) fechar a tela do ultimo que via: agora a camera para -------------------------------
            pag_b.close()          # pagehide -> o aviso de fechar a tela sai na hora
            parou = False
            for _ in range(30):
                if ordens("parar"):
                    parou = True
                    break
                time.sleep(0.5)
            checar("fechando a ultima tela, a camera recebe a ordem de parar", parou, f"{ordens('parar')}")

            # --- 6) computador desligado (ninguem batendo): a sessao morre sozinha e a camera para -----
            antes = len(ordens("parar"))
            pag_a.click(f"#iniciar-{cam}")
            esperar_texto(pag_a, cam, "pedido enviado")
            s, j = pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)
            for o in (j.get("ordens") or []):
                pedir("POST", base + f"/api/ordens/{o['id']}/resultado",
                      {"estado": "atendida", "resultado": "camera no ar", "fluxo_id": cam}, token_bordo=TOKEN)
            checar("a camera voltou ao ar para provar o caso do computador desligado",
                   "no ar" in esperar_texto(pag_a, cam, "no ar").lower())
            # A MAQUINA CAIU (energia/rede): a tela para de bater ponto e nada avisa o servidor.
            # Fechar a aba NAO serve para provar isso: a propria tela avisa "encerrei" ao fechar.
            # Aqui o batimento e' cortado no navegador — e' a queda sem cooperacao nenhuma.
            pag_a.route("**/api/transmissao/*/batimento", lambda r: r.abort())
            con = sqlite3.connect(banco)
            vid = con.execute("SELECT id FROM transmissoes WHERE estado='no_ar' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
            con.execute("UPDATE transmissoes SET batimento_em=? WHERE id=?",
                        ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=90)).isoformat(timespec="seconds"), vid))
            con.commit(); con.close()
            r = None
            for _ in range(40):
                r = estado_no_banco(vid)
                if r and r[0] == "encerrada":
                    break
                time.sleep(1)
            checar("sem batimento (computador desligado), a transmissao para sozinha",
                   bool(r) and r[0] == "encerrada" and "fechada" in (r[1] or ""), f"{r}")
            checar("e a camera recebe a ordem de parar",
                   len(ordens("parar")) > antes, f"{ordens('parar')}")
            pedir("GET", base + "/api/ordens?embarcacao_id=bancada&espera=0", token_bordo=TOKEN)  # esvazia a fila
            pag_a.close()   # so' agora: a maquina morta sai de cena

            # --- 7) tela de configuracao do tempo ------------------------------------------------------
            # a maquina liga de novo: tela nova, mesmo cliente (a sessao do navegador continua valida)
            pag_a = ctx_a.new_page()
            pag_a.on("pageerror", lambda e: erros.append("A: " + str(e)))
            pag_a.goto(base + "/app/")
            pag_a.wait_for_selector("#sistema:not(.oculto)", timeout=20000)
            tela_transmitir(pag_a)
            pag_a.click('[data-tela="configuracao"]')
            pag_a.wait_for_selector("#tempo-maximo", timeout=15000)
            pag_a.select_option("#tempo-maximo", "300")
            pag_a.click("#gravar-tempo")
            pag_a.wait_for_timeout(1200)
            pag_a.click('[data-tela="transmissao"]')
            pag_a.wait_for_selector(".transmissao-linha", timeout=15000)
            pag_a.click(f"#iniciar-{cam}")
            pag_a.wait_for_timeout(1500)
            con = sqlite3.connect(banco)
            seg = con.execute("SELECT segundos_max FROM transmissoes ORDER BY rowid DESC LIMIT 1").fetchone()[0]
            con.close()
            checar("o tempo gravado na tela vale para o proximo pedido (300 s)", seg == 300, f"{seg}")
            # a tela "Gravacoes" deixou de ser um lugar vazio: ela le' o historico do lado terra
            pag_a.click('[data-tela="gravacoes"]')
            pag_a.wait_for_selector("#palco table", timeout=15000)
            texto_grav = pag_a.inner_text("#palco")
            checar("a tela Gravações mostra o que ficou gravado (ou diz que não há)",
                   "grava" in texto_grav.lower(), texto_grav[:120])

            checar("nenhum erro de script na tela", not erros, "; ".join(erros[:2]))
            pag_a.screenshot(path=str(tmp / "tela-transmissao.png"), full_page=True)
            print("captura de tela:", tmp / "tela-transmissao.png")
            ctx_a.close(); ctx_b.close(); navegador.close(); navegador = None
    finally:
        if navegador:
            try:
                navegador.close()
            except Exception:
                pass
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
    print("TRANSMISSAO_TELA_OK — o cliente abre a transmissao pela web, a ordem vai ao bordo e o corte e' por sessao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
