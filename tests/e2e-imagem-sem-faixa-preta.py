#!/usr/bin/env python3
"""A IMAGEM NAO TEM FAIXA PRETA LATERAL E FICA MAIOR (dono, 24/11/2026).

Dono, verbatim, com o print da tela do cliente (1908x841, 4 cameras em 2x2, menu RECOLHIDO):

> deve haver outra forma de exibir as imagens sem ficar com essas faixas laterais pretas, sem cortar as
> imagens e sem deixar os videos pequenos na tela

O QUE ESTAVA ERRADO (medido com a sonda, antes desta rodada — o numero que abre o plano):
  celula 934x364 (2,57:1) e video 16:9 dentro dela -> a imagem so' usava a ALTURA e sobrava
  **176 px de preto de cada lado** (38% da celula); e o card, ABAIXO da imagem, comia 34 px de altura
  (x 1,78 = 60 px de largura). No print do dono a imagem saia 582x328.

O QUE SE MEDE AQUI (Chromium de verdade, 4 cameras, o "antes" fica gravado no codigo):

 1. FAIXA: a imagem enche a celula (ate' 2px de cada lado = a borda) nas TRES janelas do dono;
 2. TAMANHO: a imagem e' MAIOR que a "antes" de cada janela (a area cresce — nao e' so' mover o preto);
 3. CENTRADO: a sobra do palco vira margem SIMETRICA (esquerda = direita) — nao tarja por imagem;
 4. SEM CORTE: a proporcao da imagem e' a do video, em 16:9 E em 4:3 (a celula segue o FLUXO);
 5. CARD: o card flutua SOBRE a imagem, com altura fixa (nao come altura da imagem);
 6. CLIQUE: com DUAS cameras no ar, o aviso do ultimo minuto aparece nas duas e o "Continuar conectado"
    das duas funciona — era o que o dono apontou na 0.15.0 ("nao da pra clicar no botao para continuar
    conectado nas duas cameras").
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
SENHA = "senha-da-prova-0160"
ESPERA = 20000
FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"

# O "ANTES" desta rodada (sonda de 24/11/2026, 4 cameras, menu recolhido) — imagem desenhada, em CSS px.
# A area e' o que tem de CRESCER; a largura/altura sozinhas nao contam a historia (a faixa podia sair de
# um lado e aparecer do outro).
ANTES = {
    (1908, 841): {"l": 582, "a": 328, "area": 190769},
    (1536, 700): {"l": 457, "a": 257, "area": 117492},
    (1920, 1080): {"l": 798, "a": 449, "area": 355340},
}
JANELAS = [(1908, 841), (1536, 700), (1920, 1080)]   # a 1a e' o tamanho do print do dono

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


def video_de_prova(pasta: pathlib.Path, tamanho: str) -> str:
    """Um mp4 de verdade em data URL. `tamanho` no formato WxH (640x360 = 16:9, 640x480 = 4:3)."""
    saida = pasta / ("prova-" + tamanho.replace("x", "_") + ".mp4")
    if not saida.exists():
        subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"testsrc=size={tamanho}:rate=10", "-t", "1",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)],
                       check=True, capture_output=True)
    return "data:video/mp4;base64," + base64.b64encode(saida.read_bytes()).decode()


def criar_usuario(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES ('cli','cliente@lecsor.test','cli','cliente',?,?,?,200000,1)""", (EMPRESA, senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)", (EMB, EMPRESA, "PSV I"))
    for cid, rot in CAMS:
        con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                       VALUES (?,?,?,?,'bordo',1,'800k')""", (cid, EMB, rot, cid))
    con.commit()
    con.close()


def ajustar_termina(banco: pathlib.Path, segundos: int) -> None:
    """Adianta o fim das sessoes vivas (o relogio controlado da prova: sem esperar 15 min)."""
    quando = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=segundos)).isoformat(timespec="seconds")
    con = sqlite3.connect(str(banco))
    con.execute("UPDATE transmissoes SET termina_em=? WHERE estado IN ('pedida','no_ar')", (quando,))
    con.commit()
    con.close()


def restantes(banco: pathlib.Path) -> list:
    """Segundos que faltam em CADA sessao viva (a prova do clique por camera)."""
    con = sqlite3.connect(str(banco))
    linhas = con.execute("SELECT termina_em FROM transmissoes WHERE estado IN ('pedida','no_ar')").fetchall()
    con.close()
    fora = []
    for (quando,) in linhas:
        if not quando:
            continue
        t = dt.datetime.fromisoformat(quando)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        fora.append(int((t - dt.datetime.now(dt.timezone.utc)).total_seconds()))
    return sorted(fora)


# `provaRazao`: guardar a proporcao do video de prova NO MOMENTO em que o aplicativo a le'. O lado terra
# reaponta o `<video>` para o fluxo do servidor logo depois (nao ha fluxo na bancada) e o `videoWidth`
# volta a zero — a medida da imagem desenhada tem de usar a proporcao que valeu no layout, nao a que
# sobrou depois.
JS_POE_VIDEO = """async (url) => {
  const alvos = Array.from(document.querySelectorAll('.janela video'));
  for (const v of alvos) {
    v.dataset.prova = '1';
    await new Promise((ok) => { v.addEventListener('loadedmetadata', ok, {once: true}); v.src = url; v.load(); });
    if (v.videoWidth && v.videoHeight) v.dataset.provaRazao = String(v.videoWidth / v.videoHeight);
  }
  await new Promise((ok) => setTimeout(ok, 700));
  return alvos.map((v) => v.dataset.provaRazao || null);
}"""

# A GEOMETRIA crua: celula, caixa da imagem, imagem DESENHADA (o que o `contain` desenha) e as margens.
JS_MEDIR = """() => {
  const grade = document.querySelector('.grade-vms');
  const palco = document.querySelector('#palco');
  const est = getComputedStyle(palco);
  const rp = palco.getBoundingClientRect();
  const rg = grade.getBoundingClientRect();
  const uteisL = rp.width - (parseFloat(est.paddingLeft) || 0) - (parseFloat(est.paddingRight) || 0);
  const uteisA = rp.height - (parseFloat(est.paddingTop) || 0) - (parseFloat(est.paddingBottom) || 0);
  const janelas = Array.from(document.querySelectorAll('.janela'));
  const medir = (j) => {
    const v = j.querySelector('video');
    if (!v) return null;
    const rj = j.getBoundingClientRect();
    const box = v.getBoundingClientRect();
    const r = Number(v.dataset.provaRazao) || ((v.videoWidth && v.videoHeight) ? (v.videoWidth / v.videoHeight) : (16 / 9));
    const l = Math.min(box.width, box.height * r);      // o que o `contain` DESENHA
    const a = l / r;
    const card = j.querySelector('.card-cam');
    const rc = card ? card.getBoundingClientRect() : null;
    return {celulaL: rj.width, celulaA: rj.height, l: l, a: a, razaoVideo: r,
            razaoDesenhada: l / a,
            faixaL: (rj.width - l) / 2, faixaA: (rj.height - a) / 2,
            cardA: rc ? rc.height : 0,
            /* o card esta' DENTRO da celula (sobre a imagem) e nao abaixo dela? */
            cardSobre: rc ? (rc.bottom <= rj.bottom + 1 && rc.top > rj.top) : false,
            fundoDaIgnorada: getComputedStyle(v).getPropertyValue('--nao-existe')};
  };
  return {
    tela: [window.innerWidth, window.innerHeight],
    palco: [Math.round(rp.width), Math.round(rp.height)], uteis: [Math.round(uteisL), Math.round(uteisA)],
    grade: [Math.round(rg.width), Math.round(rg.height)],
    margemEsq: Math.round(rg.left - rp.left), margemDir: Math.round(rp.right - rg.right),
    margemTopo: Math.round(rg.top - rp.top), margemBaixo: Math.round(rp.bottom - rg.bottom),
    colunas: grade.dataset.escolhidas, projecao: grade.dataset.imagem,
    imagens: janelas.map(medir),
  };
}"""


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-faixa-"))
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
    erros: list[str] = []
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

        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            url169 = video_de_prova(tmp, "640x360")
            for larg, alt in JANELAS:
                antes = ANTES[(larg, alt)]
                pag = navegador.new_context(viewport={"width": larg, "height": alt}).new_page()
                pag.on("pageerror", lambda e: erros.append(str(e)))
                pag.goto(base + "/entrada/")
                pag.fill("#email", "cliente@lecsor.test")
                pag.fill("#senha", SENHA)
                pag.click("form#form-entrar button[type=submit]")
                pag.wait_for_selector(".grade-vms .janela", timeout=ESPERA)
                # o estado do print do dono: menu RECOLHIDO
                if pag.evaluate("() => !!document.querySelector('#btn-menu')"):
                    pag.click("#btn-menu")
                    pag.wait_for_timeout(700)
                pag.evaluate(JS_POE_VIDEO, url169)
                pag.wait_for_timeout(600)
                m = pag.evaluate(JS_MEDIR)
                print(f"\n== JANELA {larg}x{alt} (menu recolhido) — palco {m['palco']} util {m['uteis']} "
                      f"grade {m['grade']} colunas {m['colunas']} projecao {m['projecao']} ==")
                print("        imagens:", json.dumps([{k: (round(v, 1) if isinstance(v, float) else v)
                                                       for k, v in im.items() if k != 'fundoDaIgnorada'}
                                                      for im in m["imagens"] if im], ensure_ascii=False))
                checar(f"{larg}x{alt}: as 4 cameras estao na grade",
                       len([i for i in m["imagens"] if i]) == 4, str(len([i for i in m["imagens"] if i])))
                checar(f"{larg}x{alt}: o painel esta CENTRADO (margem esquerda = direita, ate' 2px)",
                       abs(m["margemEsq"] - m["margemDir"]) <= 2,
                       f"esq {m['margemEsq']} | dir {m['margemDir']}")
                checar(f"{larg}x{alt}: o painel cabe no palco (nao estoura)",
                       m["grade"][0] <= m["uteis"][0] + 2 and m["grade"][1] <= m["uteis"][1] + 2,
                       f"grade {m['grade']} em util {m['uteis']}")
                for i, im in enumerate(m["imagens"]):
                    if not im:
                        continue
                    checar(f"{larg}x{alt} imagem {i + 1}: ZERO faixa lateral na celula (ate' 2px de cada lado)",
                           im["faixaL"] <= 2 and im["faixaA"] <= 2,
                           f"celula {round(im['celulaL'])}x{round(im['celulaA'])} | "
                           f"imagem {round(im['l'])}x{round(im['a'])} | faixa {round(im['faixaL'])}x{round(im['faixaA'])}")
                    checar(f"{larg}x{alt} imagem {i + 1}: sem corte (proporcao da imagem = a do video)",
                           abs(im["razaoDesenhada"] - im["razaoVideo"]) < 0.005,
                           f"{im['razaoDesenhada']:.3f}")
                    ganho = (im["l"] * im["a"]) / antes["area"] - 1
                    checar(f"{larg}x{alt} imagem {i + 1}: MAIOR que antes "
                           f"({antes['l']}x{antes['a']} -> {round(im['l'])}x{round(im['a'])})",
                           im["l"] * im["a"] > antes["area"], f"area {ganho * 100:+.1f}%")
                    checar(f"{larg}x{alt} imagem {i + 1}: o card fica SOBRE a imagem (altura fixa)",
                           im["cardSobre"] and 0 < im["cardA"] <= 34, f"card {round(im['cardA'])}px")
                pag.close()

            # --- 4:3: a celula segue o FLUXO (nao um 16:9 chumbado) -------------------------------
            pag = navegador.new_context(viewport={"width": 1908, "height": 841}).new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.goto(base + "/entrada/")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector(".grade-vms .janela", timeout=ESPERA)
            pag.evaluate(JS_POE_VIDEO, video_de_prova(tmp, "640x480"))
            pag.wait_for_timeout(900)
            m43 = pag.evaluate(JS_MEDIR)
            print(f"\n== VIDEO 4:3 (640x480), janela 1908x841 — celula {m43['grade']} ==")
            print("        imagens:", json.dumps([{k: round(v, 1) for k, v in im.items() if k != 'fundoDaIgnorada'}
                                                  for im in m43["imagens"] if im], ensure_ascii=False))
            for i, im in enumerate(m43["imagens"]):
                if not im:
                    continue
                checar(f"4:3 imagem {i + 1}: a celula acompanha o FLUXO (4:3), sem faixa",
                       abs(im["razaoDesenhada"] - 4 / 3) < 0.02 and im["faixaL"] <= 2 and im["faixaA"] <= 2,
                       f"celula {round(im['celulaL'])}x{round(im['celulaA'])} imagem {round(im['l'])}x{round(im['a'])}")
            checar("sem erro de JS na tela do cliente", not erros, "; ".join(erros[:2]))
            pag.screenshot(path=str(RAIZ / ".hermes" / "prova-sem-faixa.png"))
            pag.close()

            # --- 6. O CLIQUE DO AVISO NAS DUAS CAMERAS (o bug que o dono apontou na 0.15.0) -------
            # "nao da pra clicar no botao para continuar conectado nas duas cameras". A causa era o card
            # de UMA linha: o aviso caia dentro dele e os botoes ficavam FORA da janela (cortados pelo
            # `overflow:hidden`) — o clique nao chegava. Agora o aviso mora DENTRO da imagem.
            pag = navegador.new_context(viewport={"width": 1908, "height": 841}).new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())
            pag.goto(base + "/entrada/")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector(".grade-vms .janela [data-papel='iniciar']", timeout=ESPERA)
            print("\n== 6. 'Continuar conectado' nas DUAS cameras (o bug da 0.15.0) ==")
            botoes = pag.locator(".grade-vms .janela [data-papel='iniciar']")
            checar("a grade tem um controle de transmissao por camera (>=2)",
                   botoes.count() >= 2, f"{botoes.count()} controles")
            for i in range(2):
                botoes.nth(i).click()
                pag.wait_for_timeout(1200)
            checar("as duas cameras entraram no ar", len(restantes(banco)) == 2, f"{restantes(banco)}s")
            ajustar_termina(banco, 30)
            pag.wait_for_function("() => document.querySelectorAll('.st-aviso.mostra').length >= 2",
                                  timeout=ESPERA + 15000)
            checar("o aviso do ultimo minuto aparece NAS DUAS cameras",
                   pag.locator(".st-aviso.mostra").count() == 2, f"{pag.locator('.st-aviso.mostra').count()}")
            checar("e as duas transmissoes estao mesmo no ultimo minuto",
                   len([r for r in restantes(banco) if r < 60]) == 2, f"{restantes(banco)}s")
            # O CLIQUE. A ordem NAO importa (medida: a 2a janela renovou a sessao da 1a e vice-versa) —
            # o que tem de valer e' que clicar em CADA UM dos dois avisos renova uma transmissao.
            pag.locator(".st-aviso.mostra [data-papel='continuar']").nth(1).click()
            pag.wait_for_timeout(2500)
            r2 = restantes(banco)
            checar("o 1o clique renova UMA transmissao (o botao que nao chegava na 0.15.0)",
                   len(r2) == 2 and min(r2) < 60 and max(r2) > 300, f"{r2}s restantes")
            # depois de renovar, o aviso daquela camera perde os botoes -> sobra UM aviso clicavel
            pag.wait_for_function("() => document.querySelectorAll('.st-aviso.mostra [data-papel=\\'continuar\\']').length === 1",
                                  timeout=ESPERA)
            pag.locator(".st-aviso.mostra [data-papel='continuar']").nth(0).click()
            pag.wait_for_timeout(2500)
            r1 = restantes(banco)
            checar("e o 2o clique renova a OUTRA: as DUAS continuam conectadas",
                   len(r1) == 2 and min(r1) > 300, f"{r1}s restantes")
            pag.screenshot(path=str(RAIZ / ".hermes" / "prova-aviso-nas-duas.png"))
            navegador.close()

        print("\n" + "=" * 72)
        if falhas:
            print(f"FALHOU: {len(falhas)} — " + "; ".join(falhas))
            return 1
        print("TUDO VERDE: a imagem enche a celula (zero faixa preta), fica MAIOR, sem corte, com o card "
              "sobre a imagem — em 16:9 e em 4:3.")
        return 0
    finally:
        api.terminate()


if __name__ == "__main__":
    sys.exit(main())
