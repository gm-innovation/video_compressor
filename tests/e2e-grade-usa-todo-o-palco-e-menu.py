#!/usr/bin/env python3
"""A GRADE USA O PALCO INTEIRO e o MENU RECOLHE (dono, 24/11/2026).

Dono, verbatim, com o print da tela do cliente (1820x900, 4 cameras em 2x2):

> as imagens continuam ocupando metade do espaco possivel na tela, pode inclusive colocar um botao para
> colapsar o sidemenu e aumentar ainda mais o espaco util

O que se MEDE aqui (Chromium de verdade, 4 cameras com video real, janela 1820x900):

 1. a largura da GRADE em relacao a area util do PALCO (a queixa e' largura vira margem morta);
 2. a imagem renderizada de cada janela e' a MAIOR que cabe sem cortar (o `<video>` e' `contain`) e a
    proporcao da imagem e' a do video (sem corte);
 3. a imagem e' MAIOR que a da versao publicada (460x259, medido no print do dono nesse mesmo tamanho);
 4. o botao de recolher o menu devolve a largura da barra para o palco e o estado VOLTA depois de
    recarregar a pagina.
"""
from __future__ import annotations

import base64
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
import urllib.request

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[1]
EMPRESA, EMB = "emp-1", "emb-1"
CAMS = [("cam-01", "Proa"), ("cam-02", "Popa"), ("cam-03", "USB Video (1)"), ("cam-04", "USB Video (2)")]
SENHA = "senha-da-prova-0150"
ESPERA = 20000
FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"
# a medida do dono na versao publicada (print de 24/11/2026, 4 cameras em 2x2 num palco de 1500 px)
ANTES_L, ANTES_A = 460, 259

falhas: list[str] = []


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f"   [{detalhe}]" if detalhe else ""))
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


def video_de_prova(pasta: pathlib.Path) -> str:
    """Um mp4 de verdade (1 s, 640x360 = a proporcao de uma camera 16:9) em data URL."""
    saida = pasta / "prova-640x360.mp4"
    subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=size=640x360:rate=10", "-t", "1",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)],
                   check=True, capture_output=True)
    return "data:video/mp4;base64," + base64.b64encode(saida.read_bytes()).decode()


def criar_usuario(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES ('cli','cliente@lecsor.test','cli','cliente',?,?,?,200000,1)""",
                (EMPRESA, senha, salt))
    con.commit(); con.close()


def semear(banco: pathlib.Path) -> None:
    """Cliente, embarcacao e QUATRO cameras (a grade 2x2 do print do dono)."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    for cid, rot in CAMS:
        con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                       VALUES (?,?,?,?,'bordo',1,'800k')""", (cid, EMB, rot, cid))
    con.commit(); con.close()


# ---------------------------------------------------------------- JS de apoio
JS_POE_VIDEO = """async (url) => {
  const alvos = Array.from(document.querySelectorAll('.janela video'));
  for (const v of alvos) {
    if (v.dataset.prova) continue;
    v.dataset.prova = '1';
    await new Promise((ok) => { v.addEventListener('loadedmetadata', ok, {once: true}); v.src = url; v.load(); });
  }
  await new Promise((ok) => setTimeout(ok, 500));
  return alvos.length;
}"""

JS_MEDIR = """() => {
  const grade = document.querySelector('.grade-vms');
  const palco = document.querySelector('#palco');
  const est = getComputedStyle(palco);
  const rg = grade.getBoundingClientRect();
  const rp = palco.getBoundingClientRect();
  const uteis = rp.width - (parseFloat(est.paddingLeft) || 0) - (parseFloat(est.paddingRight) || 0);
  const janelas = Array.from(document.querySelectorAll('.janela'));
  const medirImagem = (j) => {
    const v = j.querySelector('video');
    if (!v) return null;
    const box = v.getBoundingClientRect();
    const r = (v.videoWidth && v.videoHeight) ? (v.videoWidth / v.videoHeight) : (16 / 9);
    const l = Math.min(box.width, box.height * r);
    const a = l / r;
    const card = j.querySelector('.card-cam');
    return {l: Math.round(l), a: Math.round(a), caixaL: Math.round(box.width), caixaA: Math.round(box.height),
            razao: Number((l / a).toFixed(3)), cardA: card ? Math.round(card.getBoundingClientRect().height) : 0};
  };
  return {
    palcoL: Math.round(rp.width), uteisL: Math.round(uteis), gradeL: Math.round(rg.width),
    gradeEsq: Math.round(rg.left), gradeDir: Math.round(rg.right),
    palcoEsq: Math.round(rp.left), palcoDir: Math.round(rp.right),
    fracao: Number((rg.width / uteis).toFixed(3)),
    colunas: grade.dataset.escolhidas, projecao: grade.dataset.imagem,
    imagens: janelas.map(medirImagem),
    menu: (document.querySelector('#btn-menu') || {}).textContent || '',
    rotuloMenu: document.querySelector('#btn-menu') ? document.querySelector('#btn-menu').getAttribute('aria-label') : null,
    lateralL: Math.round(document.querySelector('#lateral').getBoundingClientRect().width),
  };
}"""


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-palco-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_EMBARCACAO", "LECSOR_LICENCA"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_HD_DIR": str(tmp / "hd"), "PYTHONIOENCODING": "utf-8"})
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=3):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("a API nao subiu; log em %s" % (tmp / "api.log"))
        for _ in range(60):
            con = sqlite3.connect(str(banco))
            tem = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='usuarios'").fetchone()[0]
            con.close()
            if tem:
                break
            time.sleep(0.5)
        criar_usuario(banco)
        semear(banco)

        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            pag = navegador.new_context(viewport={"width": 1820, "height": 900}).new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.goto(base + "/entrada/")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector(".grade-vms .janela", timeout=ESPERA)
            url = video_de_prova(tmp)
            pag.evaluate(JS_POE_VIDEO, url)
            pag.wait_for_timeout(900)

            print("\n== 1. a grade ocupa o PALCO (4 cameras em 1820x900 — a tela do dono) ==")
            m = pag.evaluate(JS_MEDIR)
            print("       ", json.dumps({k: m[k] for k in ("palcoL", "uteisL", "gradeL", "fracao", "colunas",
                                                           "projecao", "lateralL")}, ensure_ascii=False))
            print("        imagens:", json.dumps(m["imagens"], ensure_ascii=False))
            checar("a GRADE usa pelo menos 95% da largura util do palco", m["fracao"] >= 0.95,
                   f"{m['gradeL']} de {m['uteisL']} = {m['fracao']:.1%}")
            checar("a grade comeca e termina DENTRO do palco",
                   m["gradeEsq"] >= m["palcoEsq"] and m["gradeDir"] <= m["palcoDir"] + 1,
                   f"grade {m['gradeEsq']}..{m['gradeDir']} | palco {m['palcoEsq']}..{m['palcoDir']}")
            checar("as QUATRO cameras estao na grade", len([i for i in m["imagens"] if i]) == 4,
                   str(len([i for i in m["imagens"] if i])))

            print("\n== 2. a imagem e' a MAIOR que cabe, e INTEIRA (sem corte) ==")
            for i, im in enumerate(m["imagens"]):
                if not im:
                    continue
                cabe_na_largura = im["l"] <= im["caixaL"] + 1
                checar(f"imagem {i + 1}: {im['l']}x{im['a']} nao passa da caixa e usa a altura ou a largura",
                       cabe_na_largura and (im["l"] >= im["caixaL"] - 1 or im["a"] >= im["caixaA"] - 1),
                       f"caixa {im['caixaL']}x{im['caixaA']}")
                checar(f"imagem {i + 1}: proporcao do VIDEO preservada (nada cortado)",
                       abs(im["razao"] - 16 / 9) < 0.02, str(im["razao"]))
                checar(f"imagem {i + 1}: MAIOR que a da versao publicada ({ANTES_L}x{ANTES_A})",
                       im["l"] > ANTES_L * 1.2 and im["a"] > ANTES_A, f"{im['l']}x{im['a']}")

            print("\n== 3. o botao recolhe o MENU e devolve a largura ==")
            antes = pag.evaluate(JS_MEDIR)
            pag.click("#btn-menu")
            pag.wait_for_timeout(600)
            depois = pag.evaluate(JS_MEDIR)
            print("        palco:", antes["palcoL"], "->", depois["palcoL"], "| barra:",
                  antes["lateralL"], "->", depois["lateralL"], "| menu:", repr(depois["menu"]))
            checar("a barra lateral foi a ZERO", depois["lateralL"] == 0, str(depois["lateralL"]))
            checar("o palco (e a grade) cresceram", depois["uteisL"] > antes["uteisL"]
                   and depois["gradeL"] > antes["gradeL"],
                   f"{antes['uteisL']}->{depois['uteisL']} / {antes['gradeL']}->{depois['gradeL']}")
            checar("e a grade continua usando o palco todo com o menu recolhido", depois["fracao"] >= 0.95,
                   f"{depois['fracao']:.1%}")
            checar("o botao diz que agora ABRE o menu", "Abrir menu" in (depois["rotuloMenu"] or ""),
                   str(depois["rotuloMenu"]))
            checar("a barra recolhida fica fora do foco/leitor de tela",
                   pag.evaluate("() => document.querySelector('#lateral').getAttribute('aria-hidden')") == "true")

            print("\n== 4. o estado do menu VOLTA depois de recarregar ==")
            pag.reload()
            pag.wait_for_selector(".grade-vms .janela", timeout=ESPERA)
            pag.wait_for_timeout(600)
            voltou = pag.evaluate(JS_MEDIR)
            print("        largura da barra depois do recarregar:", voltou["lateralL"])
            checar("a tela abre com o menu RECOLHIDO (a escolha foi guardada)", voltou["lateralL"] == 0,
                   str(voltou["lateralL"]))
            pag.click("#btn-menu")
            pag.wait_for_timeout(600)
            aberto = pag.evaluate(JS_MEDIR)
            checar("e o botao ABRE de novo (a barra volta)", aberto["lateralL"] > 100, str(aberto["lateralL"]))
            checar("sem erro de JS na tela do cliente", not erros, "; ".join(erros[:2]))
            pag.screenshot(path=str(RAIZ / ".hermes" / "prova-palco-e-menu.png"))
            navegador.close()

        print("\n" + "=" * 72)
        if falhas:
            print(f"FALHOU: {len(falhas)} — " + "; ".join(falhas))
            return 1
        print("TUDO VERDE: a grade usa o palco inteiro, a imagem entra inteira (a maior que cabe) e o menu recolhe.")
        return 0
    finally:
        api.terminate()


if __name__ == "__main__":
    sys.exit(main())
