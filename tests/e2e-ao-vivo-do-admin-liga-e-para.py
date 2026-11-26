#!/usr/bin/env python3
"""Prova de TELA: o AO VIVO do admin LIGA e PARA a câmera, e mostra "gravando a bordo" (0.23.0, 26/11/2026).

Pedido do dono, verbatim: *"eu devo poder ligar e parar a câmera também, 'imagens gravadas a bordo' não faz
sentido, só preciso no monitoramento saber se está sendo gravado a bordo, não preciso ver as imagens"* — e
as decisões dele para a rodada: **2.A** (o admin é plateia da mesma sessão do cliente: fechando a janela, a
câmera para) e **botão ligar/desligar + indicador** para a gravação contínua do radar.

Sobe a API de verdade (banco próprio) e abre um Chromium de verdade (Playwright). O que se prova NA TELA:

  1) o menu do admin NÃO tem mais "Imagens gravadas a bordo";
  2) "Monitoramento (frota)" -> "Ver ao vivo" abre a janela com Empresa -> Embarcação -> câmeras marcadas;
  3) a câmera fora do ar mostra o botão "ligar" e o selo "gravando a bordo: não medido" (não um zero com
     cara de saúde);
  4) clicar em "ligar" abre a MESMA sessão do cliente (o servidor ganha a transmissão `pedida` e o desejo
     do bordo vira `ligar`, com a plateia deste admin registrada na Auditoria);
  5) o bordo contando `gravando` faz o selo virar "gravando a bordo" na releitura (sem remontar a janela);
  6) "parar" encerra a sessão na hora (nenhuma transmissão viva, e a câmera volta a poder ser ligada);
  7) "Fechar" tira a janela e não sobra sessão;
  8) nenhum erro de JavaScript na tela.

    python tests/e2e-ao-vivo-do-admin-liga-e-para.py
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
SENHA = "senha-do-admin-de-teste"
ESPERA = 20000
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
CAM_RADAR = "cam-radar"


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


def _chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def pedir(metodo: str, url: str, corpo=None, cookie: str = "", token: str = ""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados is not None else {}
    if cookie:
        cab["Cookie"] = "sessao=" + cookie
    if token:
        cab["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-700:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,NULL,?,?,200000,1)""", (uid, email, uid, papel, senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    """A empresa, a embarcação e as duas câmeras: a comum (fora do ar — é a que o admin vai ligar) e o
    radar de óleo. NADA de `estado_bordo`: a primeira medida é "não medido" de propósito."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo,tipo)
                   VALUES (?,?,'Proa',?,'bordo',1,'800k','camera')""", (CAM, EMB, CAM))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo,tipo)
                   VALUES (?,?,'Radar de óleo',?,'bordo',1,'800k','radar')""", (CAM_RADAR, EMB, CAM_RADAR))
    con.commit()
    con.close()


def entrar(pag, base: str, email: str) -> None:
    pag.goto(base + "/entrada/")
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("button[data-tela=empresas]", timeout=ESPERA)
    pag.wait_for_load_state("networkidle")


def main() -> int:
    print("AO VIVO DO ADMIN — ligar/parar a camera e 'gravando a bordo' (0.23.0).\n")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-aovivo-tela-"))
    banco = tmp / "terra.db"
    porta = porta_livre()
    proc = None
    try:
        proc = sobe_api(banco, porta, {"LECSOR_SEM_AMBIENTE": "1", "LECSOR_HD_DIR": str(tmp / "hd"),
                                       "LECSOR_TOKEN_INGESTAO": "tok-bordo"})
        base = f"http://127.0.0.1:{porta}"
        criar_usuario(banco, "adm1", "admin@lecsor.test", "admin")
        semear(banco)

        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium()) if _chromium() \
                else p.chromium.launch(channel="chrome")
            pag = navegador.new_page(viewport={"width": 1500, "height": 950})
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)

            print("== 1. o menu do admin nao tem mais 'Imagens gravadas a bordo'\n")
            entrar(pag, base, "admin@lecsor.test")
            menu = pag.inner_text(".lateral")
            checar("a tela saiu do menu", "Imagens gravadas a bordo" not in menu)
            checar("e as telas de trabalho continuam la",
                   "Monitoramento (frota)" in menu and "Empresas e configuração" in menu)

            print("\n== 2. Monitoramento (frota) -> Ver ao vivo\n")
            pag.evaluate("() => document.querySelector('button[data-tela=frota]').click()")
            pag.wait_for_function("() => document.querySelector('#tela').innerText.includes('Ver ao vivo')",
                                  timeout=ESPERA)
            pag.evaluate("""() => { for (const b of document.querySelectorAll('#tela button'))
                                     if (b.textContent.includes('Ver ao vivo')) { b.click(); return; } }""")
            pag.wait_for_selector("#ao-vivo", timeout=ESPERA)
            checar("a janela do ao vivo abriu", pag.is_visible("#ao-vivo"))
            checar("com Empresa -> Embarcacao -> cameras",
                   pag.is_visible("#av-empresa") and pag.is_visible("#av-emb") and pag.is_visible("#av-cameras"),
                   pag.inner_text("#av-emb"))
            # O dono: "preciso poder selecionar a empresa>embarcação>câmera" — escolhe a Petrobras na mao.
            pag.select_option("#av-empresa", "Petrobras")
            try:
                pag.wait_for_function(
                    "() => Array.from(document.querySelectorAll('#av-emb option'))"
                    ".some(o => o.textContent.includes('PSV LECSOR I'))", timeout=8000)
                achou = True
            except Exception:  # noqa: BLE001
                achou = False
            checar("a embarcacao da empresa escolhida aparece no seletor", achou, pag.inner_text("#av-emb"))
            pag.select_option("#av-emb", EMB)
            checar("a embarcacao certa esta escolhida", "PSV LECSOR I" in pag.inner_text("#av-emb"))
            checar("as cameras vem marcadas e com o estado delas",
                   "Proa" in pag.inner_text("#av-cameras") and "Radar" in pag.inner_text("#av-cameras"),
                   pag.inner_text("#av-cameras").replace("\n", " | "))

            print("\n== 3. a camera fora do ar: botao LIGAR + 'gravando a bordo: nao medido'\n")
            ja = pag.locator(f".janela-adm[data-cam='{CAM}']")
            checar("a janela da camera existe", ja.count() == 1)
            checar("a camera fora do ar diz que o bordo so' transmite com plateia",
                   "sem imagem" in ja.inner_text(), ja.inner_text().replace("\n", " | "))
            checar("e o selo diz NAO MEDIDO (nunca um zero com cara de saude)",
                   "gravando a bordo: não medido" in ja.inner_text())
            bt = ja.locator("button", has_text="ligar")
            checar("o botao de ligar esta' na janela da camera", bt.count() == 1)

            print("\n== 4. LIGAR: abre a MESMA sessao do cliente (2.A)\n")
            bt.first.click()
            pag.wait_for_function("() => document.querySelector('#tela').innerText.includes('câmera pedida')",
                                  timeout=ESPERA)
            checar("a tela deu retorno na cara (nao silencio)",
                   "câmera pedida à máquina de captura" in pag.inner_text("#tela"))
            cod, desejo = pedir("GET", f"{base}/api/estado-desejado?embarcacao_id={EMB}", token="tok-bordo")
            cams = (desejo or {}).get("cameras") or []
            d0 = next((x for x in cams if x.get("camera_id") == CAM), {})
            checar("o servidor abriu a transmissao e o desejo do bordo virou LIGAR",
                   d0.get("desejo") == "ligar", f"{d0}")
            checar("a plateia registrada e' o admin que clicou",
                   "admin@lecsor.test" in str(d0.get("motivo") or ""), f"{d0.get('motivo')!r}")

            print("\n== 5. o bordo conta 'gravando' e o selo muda sem remontar a janela\n")
            cod, _ = pedir("POST", f"{base}/api/estado-real",
                           {"embarcacao_id": EMB, "cameras": [
                               {"camera_id": CAM, "estado": "no_ar", "gravando": True}]}, token="tok-bordo")
            checar("o bordo contou o estado real", cod == 200, f"{cod}")
            try:
                pag.wait_for_function(
                    f"() => {{ const j = document.querySelector(\".janela-adm[data-cam='{CAM}']\");"
                    " return j && j.innerText.includes('gravando a bordo')"
                    " && !j.innerText.includes('não medido'); }", timeout=ESPERA)
                mudou = True
            except Exception:  # noqa: BLE001
                mudou = False
            checar("o selo virou 'gravando a bordo' sozinho (releitura de 5 s)", mudou,
                   (pag.locator(f".janela-adm[data-cam='{CAM}']").inner_text() or "").replace("\n", " | "))

            print("\n== 6. PARAR: encerra a sessao na hora\n")
            pag.evaluate("""() => { const j = document.querySelector(".janela-adm[data-cam='%s']");
                                    for (const b of j.querySelectorAll('button'))
                                      if (b.textContent.includes('parar')) { b.click(); return; } }""" % CAM)
            # O retorno da tela some rapido (a releitura de 5 s repinta a frota): o que PROVA o parar e'
            # o servidor — a sessao encerrada e o desejo do bordo de volta em `parar`.
            encerrou = False
            d1 = {}
            for _ in range(60):
                cod, desejo = pedir("GET", f"{base}/api/estado-desejado?embarcacao_id={EMB}", token="tok-bordo")
                cams = (desejo or {}).get("cameras") or []
                d1 = next((x for x in cams if x.get("camera_id") == CAM), {})
                if d1.get("desejo") == "parar" and not d1.get("transmissao_id"):
                    encerrou = True
                    break
                time.sleep(0.5)
            checar("parar encerrou a sessao: sem plateia o desejo voltou a PARAR", encerrou, f"{d1}")
            con = sqlite3.connect(str(banco))
            try:
                con.row_factory = sqlite3.Row
                linha = dict(con.execute("SELECT estado,motivo FROM transmissoes WHERE camera_id=? "
                                         "ORDER BY rowid DESC LIMIT 1", (CAM,)).fetchone() or {})
            finally:
                con.close()
            checar("e a transmissao no banco ficou encerrada (nada no ar)",
                   linha.get("estado") == "encerrada", f"{linha}")
            try:
                pag.wait_for_function(
                    f"() => {{ const j = document.querySelector(\".janela-adm[data-cam='{CAM}']\");"
                    " return j && j.innerText.includes('ligar') && !j.innerText.includes('aguardando'); }",
                    timeout=ESPERA)
                voltou = True
            except Exception:  # noqa: BLE001
                voltou = False
            checar("a janela mostra a camera de volta ao ponto de ligar", voltou,
                   (pag.locator(f".janela-adm[data-cam='{CAM}']").inner_text() or "").replace("\n", " | "))

            print("\n== 7. FECHAR a janela nao deixa sessao\n")
            pag.evaluate("""() => { for (const b of document.querySelectorAll('#ao-vivo button'))
                                     if (b.textContent === 'Fechar') { b.click(); return; } }""")
            try:
                pag.wait_for_function("() => !document.getElementById('ao-vivo')", timeout=8000)
                fechou = True
            except Exception:  # noqa: BLE001
                fechou = False
            checar("a janela do ao vivo saiu da tela", fechou)

            print("\n== 8. nenhum erro de JavaScript\n")
            checar("a tela rodou sem erro de JS", not erros, " · ".join(erros[:3]))

            pag.screenshot(path=str(tmp / "ao-vivo-do-admin.png"), full_page=False)
            nota(f"print: {tmp / 'ao-vivo-do-admin.png'}")
            navegador.close()

        print()
        if falhas:
            print(f"FALHOU: {len(falhas)} verificacao(oes) — {falhas}")
            return 1
        print("TUDO VERDE: o admin liga e para a camera no ao vivo, o selo 'gravando a bordo' aparece no "
              "monitoramento, e fechar a janela nao deixa nada no ar.")
        return 0
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
