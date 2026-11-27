#!/usr/bin/env python3
"""Prova de TELA do PLAY DO TRECHO e do SElETOR DE PERÍODO SEM DIGITAR (0.28.0).

Palavras do dono (27/11/2026):
  "preciso poder selecionar data e hora, não ter que digitar";
  "não aparece nada para dar play na gravação, eu deveria poder dar play e ver em tempo real com barra de
   linha do tempo".
Decisões dele: D4 = "do bordo em tempo real" · D5 = "contínua" · D6 = "completo".

    python tests/e2e-play-do-trecho-e-seletor-sem-digitar.py

Sobe a API de verdade (banco próprio) e abre o Chrome do Playwright. O que se MEDE, olhando a tela:
  1) a faixa de período NÃO tem campo de texto nem `datetime-local` — dia é calendário (`input[type=date]`)
     e hora/minuto são LISTAS: nada de digitar;
  2) um CLIQUE no atalho de período ("ontem") preenche as duas pontas;
  3) a LINHA DO TEMPO mostra um segmento por bloco (e o "agora" fecha a linha);
  4) o botão "ver" existe em toda linha e abre o PLAYER com o vídeo apontando para o trecho do bordo;
  5) tocar um trecho que já chegou entrega 200 + o arquivo inteiro, e aceita `Range` (o player puxa pedaços);
  6) tocar um trecho que ainda ESTÁ CHEGANDO abre o player e a tela diz quanto já chegou (D4);
  7) o `<video>` NÃO é recriado enquanto o trecho cresce (o play não reinicia a cada atualização);
  8) a tela abre sem erro de javascript.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
SENHA = "senha-da-prova-do-play-028"
TOKEN_INGESTAO = "token-da-prova-do-play"
falhas: list[str] = []


def checar(texto: str, cond, detalhe: str = "") -> None:
    print(("OK   " if cond else "FALHA ") + texto + (f" — {detalhe}" if detalhe and not cond else ""))
    if not cond:
        falhas.append(texto)


def _chromium() -> str:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else ""


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def entrar(pag, base: str, raiz: str, email: str) -> None:
    pag.goto(base + raiz)
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("#sistema:not(.oculto)", timeout=20000)


def mp4_fragmentado(destino: pathlib.Path) -> bool:
    """Um bloco de VERDADE, com os MESMOS flags do gravador de bordo (mp4 fragmentado)."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    r = subprocess.run([ff, "-hide_banner", "-nostdin", "-f", "lavfi",
                        "-i", "testsrc=size=320x240:rate=30", "-t", "4", "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "800k", "-g", "30",
                        "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
                        "-f", "segment", "-segment_time", "4", "-reset_timestamps", "1",
                        "-strftime", "1", str(destino / "bloco-%Y%m%d-%H%M%S.mp4")],
                       capture_output=True, text=True, timeout=180)
    return r.returncode == 0 and bool(list(destino.glob("bloco-*.mp4")))


def main() -> int:  # noqa: C901  (a prova e' longa de proposito: mede a jornada inteira)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-play-028-"))
    banco = tmp / "pipeline.db"
    env = dict(os.environ)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_SENHA_DEMO": SENHA,
                "LECSOR_TOKEN_INGESTAO": TOKEN_INGESTAO,
                "LECSOR_GRAVACOES_DIR": str(tmp / "gravacoes"), "PYTHONIOENCODING": "utf-8"})
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_EMBARCACAO"):
        env.pop(k, None)
    porta = porta_livre()
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
                           cwd=str(RAIZ), env=env, stdout=(tmp / "api.log").open("wb"),
                           stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    pronto = False
    for _ in range(80):
        try:
            with urllib.request.urlopen(base + "/api/saude", timeout=3):
                pronto = True
                break
        except Exception:
            time.sleep(0.5)
    if not pronto:
        print("FALHA a API nao subiu:", (tmp / "api.log").read_text(errors="replace")[-500:])
        api.terminate()
        return 1

    hd = tmp / "gravacoes" / "hd"
    hd.mkdir(parents=True, exist_ok=True)
    try:
        # --- o que o PC de captura publicou: 3 blocos, 60 s um do outro -----------------------------
        agora = time.time()
        ini = [(agora - k * 60) for k in (0, 1, 2)]  # ini[0] = mais NOVO, ini[2] = mais antigo
        # o bloco mais antigo nasce de VERDADE (mp4 fragmentado do mesmo jeito que o gravador escreve)
        real = mp4_fragmentado(hd)
        if real:
            gerados = sorted(hd.glob("bloco-*.mp4"), key=lambda p: p.stat().st_size)
            escolhido = gerados[-1]
            alvo = hd / (time.strftime("bloco-%Y%m%d-%H%M%S", time.localtime(ini[2])) + ".mp4")
            if escolhido != alvo:
                escolhido.replace(alvo)
            for resto in (hd.glob("bloco-*.mp4")):
                if resto.name != alvo.name:
                    resto.unlink()
        blocos = []
        for k, t in enumerate(ini):
            if real and k == 2:
                continue
            nome = time.strftime("bloco-%Y%m%d-%H%M%S", time.localtime(t)) + ".mp4"
            (hd / nome).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"radar" * (200000 + k))
        for k, t in enumerate(ini):
            nome = time.strftime("bloco-%Y%m%d-%H%M%S", time.localtime(t)) + ".mp4"
            caminho = hd / nome
            if caminho.exists():
                blocos.append({"arquivo": nome, "inicio": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)),
                               "bytes": caminho.stat().st_size, "fim": ""})
        blocos.sort(key=lambda b: b["inicio"])   # ASC; a tela mostra do mais NOVO para o mais antigo
        novo, meio = blocos[-1], blocos[-2]
        print("     blocos publicados:", ", ".join(b["arquivo"] for b in blocos),
              "· mp4 de verdade:", real)

        # A TELA ORDENA DO MAIS NOVO PARA O MAIS ANTIGO: linha 0 = o mais novo (completo), linha 1 = o do
        # meio (ainda chegando) e linha 2 = o mais antigo (sem pedido nenhum).
        con = sqlite3.connect(str(banco))
        con.row_factory = sqlite3.Row
        dono = con.execute("SELECT cliente_id FROM usuarios WHERE email='cliente@lecsor.test'").fetchone()
        emb = con.execute("SELECT id FROM embarcacoes WHERE cliente_id=? LIMIT 1", (dono["cliente_id"],)).fetchone()
        emb_id = emb["id"]
        con.execute("""INSERT OR REPLACE INTO cameras
                       (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                       VALUES ('radar-01',?,'Radar de oleo','',1,1,'','','dshow','','300k')""", (emb_id,))
        resumo = {"ligada": True, "camera": "radar-01", "blocos": len(blocos),
                  "bytes": sum(b["bytes"] for b in blocos)}
        con.execute("""INSERT OR REPLACE INTO hd_catalogo (embarcacao_id,camera_id,resumo,blocos,atualizado_em)
                       VALUES (?, 'radar-01', ?, ?, ?)""",
                    (emb_id, json.dumps(resumo), json.dumps(blocos),
                     time.strftime("%Y-%m-%dT%H:%M:%S")))
        # Os pedidos nascem em UTC (o terra compara com o relógio dele — em hora local virariam "sem
        # resposta" na hora).
        agora_utc = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00"
        # (A) o mais NOVO já CHEGOU: o trecho inteiro está em terra -> play do arquivo completo
        pronto_nome = f"ped-0001-{novo['arquivo']}"
        (hd / pronto_nome).write_bytes((hd / novo["arquivo"]).read_bytes())
        con.execute("""INSERT OR REPLACE INTO hd_pedidos
                       (id,embarcacao_id,camera_id,arquivo,usuario_email,estado,trecho,bytes,motivo,criado_em,pronto_em)
                       VALUES ('ped-0001',?,'radar-01',?,'cliente@lecsor.test','enviado',?,?,?,?,?)""",
                    (emb_id, novo["arquivo"], pronto_nome, (hd / pronto_nome).stat().st_size, "",
                     agora_utc, agora_utc))
        # (B) o do MEIO ESTÁ CHEGANDO: só 40% do bloco está em terra -> D4 (play enquanto chega)
        dados = (hd / meio["arquivo"]).read_bytes()
        chegando_nome = f"ped-0002-{meio['arquivo']}"
        (hd / chegando_nome).write_bytes(dados[: max(4096, int(len(dados) * 0.4))])
        con.execute("""INSERT OR REPLACE INTO hd_pedidos
                       (id,embarcacao_id,camera_id,arquivo,usuario_email,estado,trecho,bytes,motivo,criado_em,pronto_em)
                       VALUES ('ped-0002',?,'radar-01',?,'cliente@lecsor.test','pedido','',0,'',?,'')""",
                    (emb_id, meio["arquivo"], agora_utc))
        con.commit()
        con.close()
        parcial_esperado = (hd / chegando_nome).stat().st_size

        with sync_playwright() as pw:
            nav = pw.chromium.launch(executable_path=_chromium() or None)
            pag = nav.new_context(viewport={"width": 1500, "height": 950}).new_page()
            erros: list[str] = []
            pag.on("pageerror", lambda e: erros.append(str(e)))
            entrar(pag, base, "/app/", "cliente@lecsor.test")
            pag.click('[data-tela="gravacoes"]')
            pag.wait_for_selector("#hd-filtro:not(.oculto)", timeout=20000)
            pag.wait_for_selector("section.bloco-gravacao", timeout=20000)
            pag.wait_for_timeout(2500)

            # (1) NADA DE DIGITAR: nenhum campo de texto e nenhum `datetime-local` na faixa de período
            faixa = pag.locator("#hd-filtro")
            texto = faixa.locator('input[type="text"], input[type="datetime-local"], textarea').count()
            dias = faixa.locator('input[type="date"]').count()
            listas = faixa.locator("select").count()
            checar("a faixa de período não tem campo de digitação (nada de text/datetime-local)",
                   texto == 0, f"{texto} campo(s) de digitação")
            checar("o dia se escolhe no calendário (input type=date) e hora/minuto em listas",
                   dias == 2 and listas == 4, f"date={dias} select={listas}")

            # (2) UM CLIQUE escolhe o período: o atalho "ontem" preenche as duas pontas (D6)
            pag.click('#hd-atalhos button[data-atalho="ontem"]')
            pag.wait_for_timeout(600)
            d_de = pag.input_value("#hd-de-data")
            d_ate = pag.input_value("#hd-ate-data")
            ontem = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
            checar("o clique no atalho 'ontem' preenche as duas pontas do período",
                   d_de == ontem and d_ate == ontem, f"de={d_de} ate={d_ate} (esperado {ontem})")
            pag.click("#hd-tudo")
            pag.wait_for_timeout(600)
            checar("'ver tudo' limpa o período escolhido",
                   pag.input_value("#hd-de-data") == "" and pag.input_value("#hd-ate-data") == "",
                   f"de={pag.input_value('#hd-de-data')!r}")

            # (4) o botão "ver" existe em toda linha do HD
            bloco_bordo = pag.locator("section.bloco-gravacao").nth(0)
            ver = bloco_bordo.locator('button[data-acao="ver"]')
            checar("toda linha do HD tem o botão 'ver' (o dono não achava nada para dar play)",
                   ver.count() == bloco_bordo.locator("tbody tr").count() == 3,
                   f"ver={ver.count()} linhas={bloco_bordo.locator('tbody tr').count()}")

            # (3) o play: clicar em "ver" abre a LINHA DO TEMPO + o player
            bloco_bordo.locator('button[data-acao="ver"]').first.click()
            pag.wait_for_selector("#hd-trecho:not(.oculto)", timeout=15000)
            pag.wait_for_selector(".video-trecho", timeout=15000)
            segs = pag.locator("#hd-trecho .seg-blocos").count()
            checar("a linha do tempo mostra um segmento por bloco gravado (D5: contínua)",
                   segs == 3, f"{segs} segmento(s)")
            checar("a linha do tempo diz em que ponto é o 'agora'",
                   "agora" in pag.locator("#hd-trecho .agora-blocos").inner_text(),
                   pag.locator("#hd-trecho .agora-blocos").inner_text())
            src = pag.get_attribute(".video-trecho", "src") or ""
            checar("o player aponta para o trecho puxado do computador de captura",
                   "/api/hd/tocar?id=ped-0001" in src, src)

            # (5) o trecho que já chegou: 200 + o arquivo INTEIRO, e aceita Range (o player puxa pedaços)
            inteiro = (hd / novo["arquivo"]).stat().st_size
            med = pag.evaluate("""async () => {
                const r = await fetch('/api/hd/tocar?id=ped-0001', {cache: 'no-store'});
                const b = await r.arrayBuffer();
                const r2 = await fetch('/api/hd/tocar?id=ped-0001', {headers: {Range: 'bytes=0-99'}});
                const b2 = await r2.arrayBuffer();
                return {status: r.status, bytes: b.byteLength, range: r2.status, rangeBytes: b2.byteLength};
            }""")
            checar("o trecho completo sai do bordo e chega inteiro (200 + tamanho exato)",
                   med["status"] == 200 and med["bytes"] == inteiro,
                   f"{med['status']} · {med['bytes']} B (esperado {inteiro} B)")
            checar("a rota do trecho aceita Range (o player puxa pedaços, não o arquivo todo de uma vez)",
                   med["range"] == 206 and med["rangeBytes"] == 100,
                   f"{med['range']} · {med['rangeBytes']} B")

            # (7) o <video> NÃO é recriado enquanto o trecho cresce (o play não reinicia a cada atualização)
            handle = pag.query_selector(".video-trecho")
            pag.wait_for_timeout(6000)
            ligado = pag.evaluate("(e) => !!(e && e.isConnected)", handle)
            checar("o <video> do play continua o MESMO durante a atualização da tela (não reinicia)",
                   ligado)

            # (6) o trecho que AINDA ESTÁ CHEGANDO: o player abre e a tela diz quanto já chegou (D4)
            bloco_bordo.locator('button[data-acao="ver"]').nth(1).click()
            pag.wait_for_selector(".video-trecho", timeout=15000)
            pag.wait_for_timeout(1500)
            estado = pag.locator("#hd-trecho .estado-trecho").inner_text()
            src2 = pag.get_attribute(".video-trecho", "src") or ""
            checar("tocar o trecho que está chegando abre o player do lado do bordo (D4)",
                   "/api/hd/tocar?id=ped-0002" in src2, src2)
            checar("a tela diz quanto do trecho já chegou, sem prometer mais do que tem",
                   "chegando do bordo" in estado and f"{parcial_esperado / 1048576:.1f} MB" in estado, estado)
            print(f"     parcial medido: {parcial_esperado} B — a tela escreveu: {estado}")

            checar("a página 'Gravações' com o play abriu sem erro de javascript", not erros,
                   "; ".join(erros)[:200])
            nav.close()
    finally:
        api.terminate()

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — o cliente escolhe o período clicando e toca o trecho do HD com linha do tempo (0.28.0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
