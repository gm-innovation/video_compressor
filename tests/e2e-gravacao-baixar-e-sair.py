#!/usr/bin/env python3
"""PROVA DE TELA da gravacao do lado terra (dono, 18/11/2026): grava de verdade, avisa o cliente para
baixar, o cliente BAIXA pela web e, quando ele SAI da tela, o ARQUIVO e' apagado — o historico fica.

Diferente do e2e-transmissao-na-tela (que prova que a tela NAO finge gravar sem fluxo), aqui ha' fluxo
de verdade: mediamtx + ffmpeg publicando. A gravacao e' real, o download e' real (o navegador salva o
arquivo) e o apagamento e' conferido NO DISCO e na trilha do banco.

    python tests/e2e-gravacao-baixar-e-sair.py
"""
from __future__ import annotations

import datetime as dt
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
sys.path.insert(0, str(RAIZ / "ground"))

FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"
MEDIAMTX = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
TOKEN = "token-de-teste-do-bordo"
SENHA = os.environ.get("LECSOR_SENHA_DEMO") or "senha-de-bancada-transmissao"
PORTA_RTSP = 8655                      # porta propria: nao atropela a bancada (8554) nem o outro teste
falhas: list[str] = []


def checar(nome: str, ok: bool, detalhe: str = "") -> None:
    print(("  OK   " if ok else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not ok:
        falhas.append(nome)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def sem_janela():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def pedir(metodo: str, url: str, corpo=None, token_sessao: str = "", token_bordo: str = ""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cabecalhos = {"Content-Type": "application/json"} if dados else {}
    if token_sessao:
        cabecalhos["Cookie"] = f"sessao={token_sessao}"
    if token_bordo:
        cabecalhos["Authorization"] = f"Bearer {token_bordo}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=40) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def wait_estado(pag, cam: str, pedaco: str, limite: int = 20000) -> str:
    """Espera o estado DAQUELA camera na tela conter o pedaco (nao olha a linha de outra camera)."""
    seletor = f'[data-estado="{cam}"]'
    fim = time.time() + limite / 1000
    texto = ""
    while time.time() < fim:
        try:
            texto = pag.locator(seletor).inner_text().strip()
        except Exception:
            texto = ""
        if pedaco.lower() in texto.lower():
            return texto
        time.sleep(0.4)
    return texto


def esperar_botao(pag, seletor: str, texto: str, limite: int = 25000) -> bool:
    """Espera o botao daquela camera mostrar o texto (a linha e' redesenhada a cada acao).

    Desde 24/11/2026 os botoes da GRADE sao ICONES com o nome completo no `title`/`aria-label` — o
    `innerText` so' traz o glifo. A prova mede o nome ACESSIVEL junto do texto.
    """
    fim = time.time() + limite / 1000
    while time.time() < fim:
        try:
            e = pag.locator(seletor).first
            junto = ((e.inner_text() or '') + ' ' + (e.get_attribute("title") or '') + ' '
                     + (e.get_attribute("aria-label") or ''))
            if texto in junto:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def espera_porta(porta, segundos=20.0) -> bool:
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=1):
                return True
        except Exception:
            time.sleep(0.3)
    return False


def fluxo_no_ar(porta, fluxo, segundos=25.0) -> bool:
    ffprobe = RAIZ / "tools" / "ffmpeg" / "ffprobe.exe"
    fim = time.time() + segundos
    while time.time() < fim:
        r = subprocess.run([str(ffprobe), "-v", "error", "-print_format", "json", "-show_streams",
                            f"rtsp://127.0.0.1:{porta}/{fluxo}"], capture_output=True, timeout=30)
        try:
            info = json.loads((r.stdout or b"{}").decode("utf-8", "ignore"))
        except Exception:
            info = {}
        if any(s.get("codec_type") == "video" for s in (info.get("streams") or [])):
            return True
        time.sleep(0.7)
    return False


def main() -> int:
    from playwright.sync_api import sync_playwright

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-gravacao-e2e-"))
    banco = tmp / "pipeline.db"
    pasta = tmp / "gravacoes"
    porta = porta_livre()

    cfg = tmp / "mediamtx.yml"
    cfg.write_text("logLevel: info\n"
                   f"rtspAddress: 127.0.0.1:{PORTA_RTSP}\n"
                   "rtmp: no\nhls: no\nwebrtc: no\nsrt: no\napi: no\nmetrics: no\n"
                   "paths:\n  all_others:\n", encoding="utf-8")
    log = (tmp / "mediamtx.log").open("wb")
    mt = subprocess.Popen([str(MEDIAMTX), str(cfg)], stdout=log, stderr=subprocess.STDOUT,
                          creationflags=sem_janela())

    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_SENHA_DEMO"] = SENHA
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["LECSOR_GRAVACOES_DIR"] = str(pasta)
    env["LECSOR_PORTA_RTSP"] = str(PORTA_RTSP)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)

    api = pub = None
    navegador = None
    try:
        checar("o mediamtx do lado terra subiu", espera_porta(PORTA_RTSP), f"porta {PORTA_RTSP}")
        logapi = (tmp / "api.log").open("wb")
        api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
                               cwd=str(RAIZ), env=env, stdout=logapi, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{porta}"
        pronto = False
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=3):
                    pronto = True
                    break
            except Exception:
                time.sleep(0.5)
        checar("a API do lado terra subiu", pronto, (tmp / "api.log").read_text(errors="replace")[-200:])
        if not pronto:
            return 1

        # a camera do cliente e' a primeira da bancada semeada; o fluxo dela e' o que a embarcacao manda
        con = sqlite3.connect(banco)
        cam, fluxo, emb = con.execute(
            "SELECT id, COALESCE(fluxo_id, id), embarcacao_id FROM cameras WHERE ativo=1 ORDER BY id").fetchone()
        con.close()

        # publica o que a embarcacao mandaria (a gravacao do lado terra le' daqui)
        pub = subprocess.Popen(
            [str(FFMPEG), "-nostdin", "-loglevel", "warning", "-re",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15",
             "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "15",
             "-pix_fmt", "yuv420p", "-f", "rtsp", "-rtsp_transport", "tcp",
             f"rtsp://127.0.0.1:{PORTA_RTSP}/{fluxo}"],
            stdout=log, stderr=subprocess.STDOUT, creationflags=sem_janela())
        checar("o fluxo da embarcacao esta' no ar (o que chega pela rede)", fluxo_no_ar(PORTA_RTSP, fluxo), fluxo)

        with sync_playwright() as pw:
            navegador = pw.chromium.launch(executable_path=_chromium())
            ctx = navegador.new_context(viewport={"width": 1500, "height": 900}, accept_downloads=True)
            pag = ctx.new_page()
            erros: list[str] = []
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())          # o aviso do navegador ao sair: aceita sair

            # --- o cliente entra, pede a transmissao e ela vai ao ar --------------------------------
            pag.goto(base + "/app/", wait_until="domcontentloaded")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector("#sistema:not(.oculto)", timeout=20000)
# PLANO UNICO (25/11/2026): a tela "Transmitir" saiu do cliente - o controle de transmissao
            # (iniciar/parar/contagem/gravar) mora na GRADE, no quadro de cada camera. O cliente ja'
            # cai nessa tela ao entrar; o botao do quadro e' o `[data-papel="iniciar"]`.
            pag.wait_for_selector(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]', timeout=15000)
            pag.click(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]')
            wait_estado(pag, cam, "pedido enviado", 20000)
            s, j = pedir("GET", base + f"/api/ordens?embarcacao_id={emb}&espera=0", token_bordo=TOKEN)
            ordens = j.get("ordens") or []
            checar("a ordem do cliente chegou a maquina de captura", bool(ordens), f"{j}")
            ordem = (ordens or [{}])[0]
            pedir("POST", base + f"/api/ordens/{ordem.get('id')}/resultado",
                  {"estado": "atendida", "resultado": "camera no ar", "fluxo_id": fluxo}, token_bordo=TOKEN)
            texto_ar = wait_estado(pag, cam, "no ar", 25000)
            checar("a transmissao esta' no ar para o cliente", "no ar" in texto_ar.lower(), texto_ar)

            # --- GRAVAR de verdade (o arquivo sai do fluxo que chegou) -------------------------------
            pag.click(f'.janela[data-cam="{cam}"] [data-papel="gravar"]')
            gravando = esperar_botao(pag, f'.janela[data-cam="{cam}"] [data-papel="gravar"]', "Parar gravação", 30000)
            checar("a tela diz que esta' GRAVANDO (com fluxo de verdade, agora e' verdade)", gravando,
                   pag.locator(f'[data-estado="{cam}"]').inner_text() if not gravando else "")
            pag.wait_for_timeout(6000)
            pag.click(f'.janela[data-cam="{cam}"] [data-papel="gravar"]')                      # para a gravacao -> o arquivo fica pronto
            pag.wait_for_selector("#aviso-gravacao", timeout=25000)

            # --- o AVISO ao cliente (dono: "ao final da gravacao, precisa avisar ao cliente") --------
            texto = pag.inner_text("#aviso-gravacao")
            checar("o cliente e' AVISADO de que a gravacao ficou pronta",
                   "baixe agora" in texto.lower(), texto[:120])
            checar("o aviso diz que o arquivo e' apagado quando ele sair",
                   "apagado quando você sair" in texto.lower(), texto[:200])
            con = sqlite3.connect(banco)
            linha = con.execute("""SELECT transmissao_id, bytes, segundos, pronta_em, avisada_em
                                   FROM gravacoes ORDER BY comecou_em DESC LIMIT 1""").fetchone()
            con.close()
            tid, bytes_g = linha[0], linha[1]
            checar("o banco tem a gravacao com tamanho e o aviso marcado",
                   bool(tid) and bytes_g > 0 and bool(linha[3]) and bool(linha[4]),
                   f"{linha}")
            arq = pasta / f"{tid}.mp4"
            checar("o arquivo da gravacao esta' no disco do lado terra", arq.exists(), str(arq))

            # --- o cliente BAIXA pela web (o navegador salva o arquivo) ------------------------------
            with pag.expect_download(timeout=60000) as espera:
                pag.click(f"#baixar-{tid}")
            baixado = espera.value
            destino = tmp / "baixado.mp4"
            baixado.save_as(str(destino))
            checar("o cliente baixa o arquivo pela web, sem instalar nada",
                   destino.exists() and destino.stat().st_size > 0,
                   f"{destino.stat().st_size if destino.exists() else 0} B")
            ffprobe = RAIZ / "tools" / "ffmpeg" / "ffprobe.exe"
            r = subprocess.run([str(ffprobe), "-v", "error", "-print_format", "json", "-show_streams",
                                str(destino)], capture_output=True, timeout=30)
            info = json.loads((r.stdout or b"{}").decode("utf-8", "ignore"))
            checar("e o que ele baixou e' video de verdade (quem le' e' o ffprobe)",
                   any(s.get("codec_type") == "video" for s in (info.get("streams") or [])), "")
            con = sqlite3.connect(banco)
            baixada_em = con.execute("SELECT baixada_em FROM gravacoes WHERE transmissao_id=?",
                                     (tid,)).fetchone()[0]
            con.close()
            checar("a trilha registra que ele baixou", bool(baixada_em), str(baixada_em))

            # --- o cliente SAI DA TELA: o arquivo e' apagado, o historico fica -----------------------
            pag.goto("about:blank", wait_until="domcontentloaded")   # pagehide -> avisa o lado terra
            fim = time.time() + 20
            while time.time() < fim and arq.exists():
                time.sleep(0.5)
            checar("saindo da tela, o ARQUIVO e' apagado no disco", not arq.exists(), str(arq))
            con = sqlite3.connect(banco)
            apagada_em, baixada_em2 = con.execute(
                "SELECT apagada_em, baixada_em FROM gravacoes WHERE transmissao_id=?", (tid,)).fetchone()
            acoes = [r[0] for r in con.execute(
                "SELECT acao FROM auditoria_acesso WHERE alvo LIKE ? ORDER BY id", (f"%{cam}%",)).fetchall()]
            con.close()
            checar("a LINHA da gravacao continua (nada de historico apagado)",
                   bool(apagada_em) and bool(baixada_em2), f"apagada_em={apagada_em} baixada_em={baixada_em2}")
            for acao in ("gravacao_iniciada", "gravacao_parada", "gravacao_avisada", "gravacao_baixada",
                         "gravacoes_apagadas"):
                checar(f"a auditoria guarda '{acao}' (sempre se sabe o que foi feito e por quem)",
                       acao in acoes, f"{sorted(set(acoes))}")

            # --- a OPERACAO ve o que houve (tamanho, quem gravou, quando o arquivo saiu) --------------
            # a OPERACAO (criada direto no banco: o teste nao depende do que o seed cria)
            con = sqlite3.connect(banco)
            con.execute("""INSERT OR REPLACE INTO usuarios
                           (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                           VALUES ('ope1','operacao@lecsor.test','Operacao','operador','lecsor','','',200000,1)""")
            con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) "
                        "VALUES ('tok-ope1','ope1',?,'teste')",
                        ((dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds"),))
            con.commit()
            con.close()
            tok_op = "tok-ope1"
            if tok_op:
                s, j = pedir("GET", base + "/api/transmissao/pedidos", token_sessao=tok_op)
                trilha = [g for g in (j.get("gravacoes") or []) if g.get("transmissao_id") == tid]
                checar("a operacao ve a trilha da gravacao (com o arquivo ja' apagado)",
                       bool(trilha) and trilha[0].get("apagada_em") and trilha[0].get("no_disco") is False,
                       f"{trilha[:1]}")
            else:
                checar("a operacao ve a trilha da gravacao (com o arquivo ja' apagado)", False,
                       "sem usuario de operacao semeado")

            checar("a tela nao deu erro de javascript", not erros, str(erros[:3]))
    finally:
        for proc in (pub, api, mt):
            if proc and proc.poll() is None:
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=20)
                except Exception:
                    pass
        if navegador:
            try:
                navegador.close()
            except Exception:
                pass
        try:
            log.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    print("prova de tela: grava, avisa para baixar, o cliente baixa e sai — e o arquivo e' apagado")
    main()
    if falhas:
        print(f"\nFALHAS ({len(falhas)}):")
        for f in falhas:
            print(f" - {f}")
        sys.exit(1)
    print("\nGRAVACAO_AVISA_E_APAGA_OK — gravou de verdade, avisou, o cliente baixou e saiu, "
          "o arquivo foi apagado e o historico ficou.")
