#!/usr/bin/env python3
"""Prova de TELA: a imagem da grade NAO e' cortada e nao sobra faixa preta (24/11/2026).

Dono, verbatim: *"agora com o card abaixo das imagens e a remoção das faixas pretas laterais, as imagens
estão sendo cortadas"* e, na sequencia, *"não cortar ... preciso das imagens inteiras"*.

A causa: a area da imagem era `1fr` da TELA (`.grade-vms{height:100%}` + `repeat(N,1fr)`) — nunca tinha a
proporcao da camera — e o `object-fit:cover` preenchia essa area CORTANDO a sobra. Agora a area da imagem
recebe a PROPORCAO REAL do video (`videoWidth/videoHeight`) e a grade e' dimensionada por ela.

O que se prova, num Chromium de verdade contra a API de verdade, com DOIS videos de proporcoes diferentes
(4:3 e 16:9) gerados aqui dentro:

  1) a area da imagem TEM a proporcao da camera (medida nos dois casos) — nao e' mais 16/9 fixo;
  2) `object-fit:contain` + a area na proporcao da camera => o quadro inteiro aparece (nada e' cortado e
     nao sobra barra escura: a imagem preenche a area exatamente);
  3) a grade continua INTEIRA dentro do palco (o calculo da coluna cabe na altura disponivel);
  4) o card segue ABAIXO da imagem.

    python tests/e2e-imagem-da-grade-nao-corta.py
"""
from __future__ import annotations

import base64
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
SENHA = "senha-da-prova-da-imagem"
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
ESPERA = 20000
FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"


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


def video_de_prova(pasta: pathlib.Path, largura: int, altura: int) -> str:
    """Um mp4 de verdade (1 s de barras) na proporcao pedida, em data URL — nada de stream aqui."""
    saida = pasta / f"prova-{largura}x{altura}.mp4"
    subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"testsrc=size={largura}x{altura}:rate=10", "-t", "1",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)],
                   check=True, capture_output=True)
    b64 = base64.b64encode(saida.read_bytes()).decode()
    return "data:video/mp4;base64," + b64


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


# Le a geometria da PRIMEIRA janela e a proporcao que o app deduziu do video.
JS_MEDIR = """() => {
  const jan = document.querySelector('.janela');
  const img = jan.querySelector('.img-cam');
  const v = jan.querySelector('video');
  const caixa = img.getBoundingClientRect();
  return {
    videoW: v.videoWidth, videoH: v.videoHeight,
    caixaL: caixa.width, caixaA: caixa.height,
    proporcaoDaArea: caixa.width / caixa.height,
    proporcaoDoVideo: v.videoWidth / v.videoHeight,
    fit: getComputedStyle(v).objectFit,
    cardTopo: jan.querySelector('.card-cam').getBoundingClientRect().top,
    imgBase: caixa.bottom,
  };
}"""

# Poe um video de verdade (data URL) no video do app e espera o metadado — o proprio codigo do app
# (proporcaoDaImagem) e' quem reage ao `loadedmetadata`.
JS_POR_VIDEO = """async (url) => {
  const v = document.querySelector('.janela video');
  await new Promise((ok) => {
    v.addEventListener('loadedmetadata', ok, {once: true});
    v.src = url; v.load();
  });
  await new Promise((ok) => setTimeout(ok, 300));
  return true;
}"""


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-imagem-"))
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
            pag = navegador.new_context(viewport={"width": 1600, "height": 900}).new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())
            pag.goto(base + "/entrada/")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector(".controle-transmissao", timeout=ESPERA)
            pag.wait_for_load_state("networkidle")

            print("\n== 1. a imagem nao entra por `cover` (que corta) ==")
            fit = pag.evaluate("() => getComputedStyle(document.querySelector('.janela video')).objectFit")
            checar("o video NAO usa mais `object-fit:cover`", fit == "contain", f"object-fit={fit}")

            print("\n== 2. camera 4:3 (640x480): a AREA DA IMAGEM acompanha a camera ==")
            url43 = video_de_prova(tmp, 640, 480)
            pag.evaluate(JS_POR_VIDEO, url43)
            m43 = pag.evaluate(JS_MEDIR)
            print("      ", m43)
            checar("o app leu a proporcao REAL do video (4:3 = 1,333)", abs(m43["proporcaoDoVideo"] - 4 / 3) < 0.02,
                   f"{m43['proporcaoDoVideo']:.3f}")
            checar("a AREA DA IMAGEM tem a proporcao da camera (nao 16:9 fixo)",
                   abs(m43["proporcaoDaArea"] - m43["proporcaoDoVideo"]) < 0.03,
                   f"area={m43['proporcaoDaArea']:.3f} video={m43['proporcaoDoVideo']:.3f}")
            checar("com a area na proporcao da camera + `contain` o quadro entra INTEIRO (sem corte)",
                   m43["fit"] == "contain"
                   and abs(m43["proporcaoDaArea"] - m43["proporcaoDoVideo"]) < 0.03)
            checar("o card continua ABAIXO da imagem", m43["cardTopo"] >= m43["imgBase"] - 1.5,
                   f"card={m43['cardTopo']:.1f} imagem={m43['imgBase']:.1f}")

            print("\n== 3. camera 16:9 (1280x720): a area acompanha de novo ==")
            url169 = video_de_prova(tmp, 1280, 720)
            pag.evaluate(JS_POR_VIDEO, url169)
            m169 = pag.evaluate(JS_MEDIR)
            print("      ", m169)
            checar("a AREA DA IMAGEM foi para 16:9 (1,778) com o video 16:9",
                   abs(m169["proporcaoDaArea"] - 16 / 9) < 0.03, f"area={m169['proporcaoDaArea']:.3f}")
            checar("e a area segue a camera, nao o tamanho da tela",
                   abs(m169["proporcaoDaArea"] - m169["proporcaoDoVideo"]) < 0.03)

            print("\n== 4. a grade inteira cabe no palco (nada estoura por baixo) ==")
            caixa = pag.evaluate("""() => {
              const palco = document.getElementById('palco').getBoundingClientRect();
              const grade = document.querySelector('.grade-vms').getBoundingClientRect();
              return {palcoBase: palco.bottom, gradeBase: grade.bottom, gradeTopo: grade.top, palcoTopo: palco.top};
            }""")
            print("      ", caixa)
            checar("a grade nao passa por baixo do rodape (base dentro do palco)",
                   caixa["gradeBase"] <= caixa["palcoBase"] + 1.5,
                   f"grade={caixa['gradeBase']:.1f} palco={caixa['palcoBase']:.1f}")
            checar("a grade nao sobe para fora do palco",
                   caixa["gradeTopo"] >= caixa["palcoTopo"] - 1.5,
                   f"grade={caixa['gradeTopo']:.1f} palco={caixa['palcoTopo']:.1f}")

            print("\n== 5. o rodape baixou e ficou so' a linha de direitos (dono, 24/11/2026) ==")
            rod = pag.evaluate("""() => {
              const r = document.querySelector('.rodape');
              const anos = r.querySelector('#ano');
              return {
                texto: r.innerText.trim(),
                altura: r.getBoundingClientRect().height,
                botoes: r.querySelectorAll('button').length,
                ano: anos ? anos.textContent.trim() : '',
              };
            }""")
            print("      ", rod)
            checar("o rodape tem SO' a linha de direitos",
                   rod["texto"].startswith("Lecsor - Todos os direitos reservados"), rod["texto"])
            checar("nenhum botao no rodape (sairam alertas, relatorios e limpar selecao)",
                   rod["botoes"] == 0, f"{rod['botoes']} botao(oes)")
            checar("o ano da linha de direitos esta preenchido", len(rod["ano"]) == 4, rod["ano"])
            checar("o rodape ficou BAIXO (<= 30 px de altura)", rod["altura"] <= 30,
                   f"{rod['altura']:.1f} px")

            print("\n== 6. sem erro de JavaScript na tela ==")
            checar("nenhum erro de JS na tela", not erros, "; ".join(erros[:3]))
            navegador.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            api.kill()

    print()
    if falhas:
        print("FALHOU: %d prova(s) — %s" % (len(falhas), "; ".join(falhas)))
        return 1
    print("OK: a imagem da grade entra INTEIRA (4:3 e 16:9), sem corte e sem faixa preta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
