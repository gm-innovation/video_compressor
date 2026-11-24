#!/usr/bin/env python3
"""Prova de TELA: o botao de GRAVAR a partir da GRADE do cliente (Fase 4, 24/11/2026).

Dono, verbatim: *"e precisa tambem de um botao para iniciar gravacao"*. E a regra que fixa o que a
gravacao E' (D4, 24/11/2026): *"so' o que chegou"* — o arquivo e' o video que JA' CHEGOU no lado terra
(gravado com `-c copy`), nunca uma gravacao nova pedida ao barco. "Enquanto grava, o corte por tempo nao
acontece" (decisao de 17/11/2026) — a gravacao nao pode ser picada no meio.

Antes desta rodada o botao so' existia na tela "Transmitir"; agora esta' na GRADE, em cada janela.

A prova e' PONTA A PONTA com fonte de verdade: um `mediamtx` local recebe o fluxo que a embarcacao
mandaria (publicado com ffmpeg) e a API grava dele — o mesmo caminho de producao. O que se prova:

  1) o botao "Gravar (no lado terra)" aparece na GRADE, com a sessao;
  2) clicar LIGA a gravacao (o ffmpeg sobe, o arquivo nasce com bytes) e o botao vira "Parar gravacao";
  3) `GET /api/transmissao` confirma `gravando: true`;
  4) clicar de novo PARA e o mp4 final fica no disco, com tamanho > 0 — so' o que chegou.

    python tests/e2e-gravacao-no-cliente.py
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
FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"
MEDIAMTX = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
falhas: list[str] = []
SENHA = "senha-da-prova-de-gravacao"
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
ESPERA = 25000


def rotulo(pag, sel: str) -> str:
    """O NOME ACESSIVEL do botao (o cliente le no `title`/`aria-label`; o `innerText` so' tem o glifo)."""
    return pag.evaluate("""(s) => { const e = document.querySelector(s);
        return e ? ((e.getAttribute('title') || '') + ' ' + (e.getAttribute('aria-label') || '')
                    + ' ' + e.innerText) : ''; }""", sel)


_SEL_GRAVAR = '.controle-transmissao [data-papel="gravar"]'


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sem_janela():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def espera_porta(porta: int, segundos: float = 20.0) -> bool:
    fim = time.time() + segundos
    while time.time() < fim:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                return True
        time.sleep(0.3)
    return False


def fluxo_no_ar(porta: int, fluxo: str, segundos: float = 20.0) -> bool:
    ffprobe = str(FFMPEG).replace("ffmpeg.exe", "ffprobe.exe")
    fim = time.time() + segundos
    while time.time() < fim:
        r = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_streams",
                            f"rtsp://127.0.0.1:{porta}/{fluxo}"], capture_output=True, timeout=30)
        try:
            info = json.loads((r.stdout or b"{}").decode("utf-8", "ignore"))
        except Exception:  # noqa: BLE001
            info = {}
        if any(s.get("codec_type") == "video" for s in (info.get("streams") or [])):
            return True
        time.sleep(0.7)
    return False


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


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-gravacao-cli-"))
    banco = tmp / "pipeline.db"
    grav = tmp / "gravacoes"
    porta = porta_livre()
    porta_rtsp = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    cfg = tmp / "mediamtx.yml"
    cfg.write_text("logLevel: info\n"
                   f"rtspAddress: 127.0.0.1:{porta_rtsp}\n"
                   "rtmp: no\nhls: no\nwebrtc: no\nsrt: no\napi: no\nmetrics: no\n"
                   "paths:\n  all_others:\n", encoding="utf-8")
    log = (tmp / "mediamtx.log").open("wb")
    mt = subprocess.Popen([str(MEDIAMTX), str(cfg)], stdout=log, stderr=subprocess.STDOUT,
                          creationflags=sem_janela())
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_EMBARCACAO", "LECSOR_LICENCA", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_GRAVACOES_DIR": str(grav), "LECSOR_PORTA_RTSP": str(porta_rtsp),
                "PYTHONIOENCODING": "utf-8"})
    api = pub = None
    try:
        checar("o mediamtx do lado terra subiu", espera_porta(porta_rtsp), f"porta {porta_rtsp}")
        logapi = (tmp / "api.log").open("wb")
        api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                               cwd=str(RAIZ), env=env, stdout=logapi, stderr=subprocess.STDOUT)
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

        # publica o que a embarcacao mandaria (a gravacao do lado terra le' daqui, com -c copy)
        pub = subprocess.Popen(
            [str(FFMPEG), "-nostdin", "-loglevel", "warning", "-re",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15",
             "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "15",
             "-pix_fmt", "yuv420p", "-f", "rtsp", "-rtsp_transport", "tcp",
             f"rtsp://127.0.0.1:{porta_rtsp}/{CAM}"],
            stdout=log, stderr=subprocess.STDOUT, creationflags=sem_janela())
        checar("o fluxo da embarcacao esta' no ar (o que chega pela rede)", fluxo_no_ar(porta_rtsp, CAM), CAM)

        with sync_playwright() as pw:
            navegador = pw.chromium.launch(executable_path=_chromium())
            pag = navegador.new_context(viewport={"width": 1500, "height": 900}).new_page()
            pag.on("dialog", lambda d: d.accept())
            pag.goto(base + "/entrada/")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector('.controle-transmissao [data-papel="iniciar"]', timeout=ESPERA)
            pag.wait_for_load_state("networkidle")
            pag.locator('.controle-transmissao [data-papel="iniciar"]').click()
            pag.wait_for_selector('.controle-transmissao [data-papel="gravar"]:visible', timeout=ESPERA)

            print("\n== 1. o botao de GRAVAR aparece na GRADE, com a sessao ==")
            # Os botoes da grade sao ICONES com o nome em `title`/`aria-label`: mede-se o NOME ACESSIVEL.
            checar("o botao 'Gravar (no lado terra)' esta' visivel",
                   "gravar" in rotulo(pag, _SEL_GRAVAR).lower(), rotulo(pag, _SEL_GRAVAR))

            print("\n== 2. clicar LIGA a gravacao (o arquivo nasce com bytes) ==")
            pag.locator('.controle-transmissao [data-papel="gravar"]').dispatch_event("click")
            pag.wait_for_function("() => { const b = document.querySelector('.controle-transmissao [data-papel=\"gravar\"]');"
                                  " return !!(b && ((b.getAttribute('title') || '') + ' ' + (b.getAttribute('aria-label') || '')"
                                  " + ' ' + b.innerText).toLowerCase().includes('parar')); }", timeout=ESPERA + 25000)
            checar("o botao virou 'Parar gravacao'",
                   "parar" in rotulo(pag, _SEL_GRAVAR).lower(), rotulo(pag, _SEL_GRAVAR))
            time.sleep(2.5)
            arquivos = list(grav.glob("*.mp4"))
            checar("nasceu arquivo de gravacao no disco", bool(arquivos), f"{[a.name for a in arquivos]}")
            checar("e o arquivo tem TAMANHO (esta' gravando de verdade)",
                   bool(arquivos) and max(a.stat().st_size for a in arquivos) > 0,
                   f"{[a.stat().st_size for a in arquivos]} B")

            print("\n== 3. a API confirma 'gravando: true' ==")
            corpo = pag.evaluate("JSON.stringify(((S.transmissao||{}).abertas||[])[0]||{})").replace(" ", "")
            checar("a sessao publica gravando=true", '"gravando":true' in corpo, corpo[:200])

            print("\n== 4. clicar de novo PARA e o mp4 fica no disco (so' o que chegou) ==")
            pag.locator('.controle-transmissao [data-papel="gravar"]').dispatch_event("click")
            pag.wait_for_function("() => { const b = document.querySelector('.controle-transmissao [data-papel=\"gravar\"]');"
                                  " return !!(b && ((b.getAttribute('title') || '') + ' ' + (b.getAttribute('aria-label') || '')"
                                  " + ' ' + b.innerText).toLowerCase().includes('gravar (no lado')); }", timeout=ESPERA + 25000)
            time.sleep(2.0)
            finais = [a for a in grav.glob("*.mp4") if ".parcial." not in a.name]
            checar("o mp4 final ficou no disco, com tamanho > 0",
                   bool(finais) and max(a.stat().st_size for a in finais) > 0,
                   f"{[(a.name, a.stat().st_size) for a in finais]}")
            navegador.close()
    finally:
        for pr in (pub, api, mt):
            try:
                if pr:
                    pr.terminate(); pr.wait(timeout=15)
            except Exception:  # noqa: BLE001
                try:
                    pr.kill()
                except Exception:  # noqa: BLE001
                    pass

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} prova(s): " + "; ".join(falhas))
        return 1
    print("OK: o cliente grava pela GRADE o que JA' CHEGOU no lado terra (liga, para, arquivo fica).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
