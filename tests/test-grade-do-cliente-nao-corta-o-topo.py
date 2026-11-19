#!/usr/bin/env python3
"""Prova, num navegador de verdade, que a tela do cliente (`/app`) NAO corta a linha de cima.

A queixa do dono (18/11/2026): na grade "Transmissoes ao vivo" a primeira fileira de janelas
encostava no cabecalho e o `overflow:hidden` do palco comia o topo — o contorno azul da janela
selecionada (`outline:2px` + `outline-offset:1px`, 3 px acima do topo da janela) aparecia cortado.

O que este teste MEDE (nao confere texto, confere geometria):
1. `padding-top` do palco >= 3 px (a folga e' o que impede o corte);
2. folga entre o topo do palco e a primeira fileira >= 3 px;
3. contorno da janela selecionada INTEIRO dentro do palco (`topo - offset - largura` >= topo do palco);
4. vale nos 3 tamanhos de janela e nas grades 2x2, 3x3 e 4x4 (a grade muda a altura das fileiras).
"""
from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TELA = (1920, 1080), (1536, 780), (1366, 768)
GRADES = "2", "3", "4"
FOLGA_MINIMA = 3.0
falhas: list[str] = []


def senha_de_bancada() -> str:
    if os.environ.get("LECSOR_SENHA_DEMO"):
        return os.environ["LECSOR_SENHA_DEMO"]
    arq = RAIZ / "ground" / ".env.local"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("LECSOR_SENHA_DEMO="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def subir_api(pasta: Path) -> tuple[subprocess.Popen, str, Path]:
    """Sobe o lado terra numa porta livre, com banco temporario e os usuarios/cameras de demonstracao."""
    banco = pasta / "pipeline.db"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LECSOR_", "SUPABASE_"))}
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_DADOS": str(pasta),
                "LECSOR_SENHA_DEMO": senha_de_bancada()})
    porta = porta_livre()
    log = open(pasta / "api.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/api/saude", timeout=2).read()
            return proc, base, banco
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("o lado terra nao subiu: " + (pasta / "api.log").read_text(errors="replace")[-400:])


def semear_cameras(banco: Path, quantas: int = 6) -> int:
    """A grade so' fica com 3 colunas (como no print do dono) se houver cameras suficientes."""
    with sqlite3.connect(banco) as c:
        linha = c.execute("SELECT embarcacao_id FROM cameras GROUP BY embarcacao_id "
                          "ORDER BY count(*) DESC LIMIT 1").fetchone()
        if not linha:
            return 0
        emb = linha[0]
        for i in range(1, quantas + 1):
            c.execute("INSERT OR REPLACE INTO cameras (id, embarcacao_id, rotulo, fluxo_id, local, ativo) "
                      "VALUES (?,?,?,?,?,1)",
                      (f"grade-cam-{i}", emb, f"Camera {i} da prova", f"grade-cam-{i}", ""))
        return c.execute("SELECT count(*) FROM cameras WHERE embarcacao_id=?", (emb,)).fetchone()[0]


MEDIDA = """() => {
  const palco = document.getElementById('palco');
  const csp = getComputedStyle(palco);
  const pg = palco.getBoundingClientRect();
  const janelas = Array.from(document.querySelectorAll('.grade-vms .janela')).map((j) => {
    const b = j.getBoundingClientRect();
    const cs = getComputedStyle(j);
    const ow = parseFloat(cs.outlineWidth) || 0;
    const oo = parseFloat(cs.outlineOffset) || 0;
    return {selecionada: j.classList.contains('selecionada'),
            topo: b.top, folga: b.top - pg.top,
            contorno_topo: b.top - oo - ow,
            contorno_no_palco: (b.top - oo - ow) - pg.top};
  });
  return {padding_top: parseFloat(csp.paddingTop) || 0, overflow: csp.overflow,
          topo_palco: pg.top, janelas};
}"""


def conferir(rotulo: str, m: dict) -> None:
    if m["padding_top"] < FOLGA_MINIMA:
        falhas.append(f"{rotulo}: padding-top do palco = {m['padding_top']} px (minimo {FOLGA_MINIMA})")
    if m["overflow"] != "hidden":
        falhas.append(f"{rotulo}: palco sem overflow:hidden (mudou o desenho — conferir o teste)")
    menor_topo = min(j["topo"] for j in m["janelas"])
    primeira_fileira = [j for j in m["janelas"] if j["topo"] <= menor_topo + 1]
    for j in primeira_fileira:
        if j["folga"] < m["padding_top"] - 0.6:
            falhas.append(f"{rotulo}: janela encostou no cabecalho (folga {j['folga']:.1f} px < "
                          f"padding {m['padding_top']} px)")
        if j["contorno_no_palco"] < 0:
            falhas.append(f"{rotulo}: contorno da janela cortado em {abs(j['contorno_no_palco']):.1f} px")
    print(f"  ok  {rotulo}: padding-top={m['padding_top']:.0f} px · primeira fileira com folga "
          f"{min(j['folga'] for j in primeira_fileira):.1f} px · contorno "
          f"{min(j['contorno_no_palco'] for j in primeira_fileira):+.1f} px dentro do palco")


def main() -> int:
    if not senha_de_bancada():
        print("FALHA: falta LECSOR_SENHA_DEMO (ground/.env.local) — sem ela o login do cliente da' 401")
        return 2
    from playwright.sync_api import sync_playwright

    pasta = Path(tempfile.mkdtemp(prefix="grade-do-cliente-"))
    api, base, banco = subir_api(pasta)
    print("lado terra de prova:", base)
    try:
        total = semear_cameras(banco)
        print(f"cameras da embarcacao do cliente: {total}")
        if total < 5:
            print("FALHA: sem cameras suficientes para a grade de 3 (como no print do dono)")
            return 2
        with sync_playwright() as pw:
            try:
                nav = pw.chromium.launch(channel="chrome")
            except Exception:
                nav = pw.chromium.launch()
            for largura, altura in TELA:
                ctx = nav.new_context(viewport={"width": largura, "height": altura})
                pg = ctx.new_page()
                pg.goto(base + "/app", wait_until="domcontentloaded")
                pg.fill("#email", "cliente@armador-demo.test")
                pg.fill("#senha", senha_de_bancada())
                pg.click("#form-entrar button")
                pg.wait_for_selector(".grade-vms", timeout=30000)
                pg.wait_for_timeout(1200)
                for grade in GRADES:
                    pg.click(f'[data-layout="{grade}"]')
                    pg.wait_for_timeout(800)
                    m = pg.evaluate(MEDIDA)
                    conferir(f"{largura}x{altura} · grade {grade}", m)
                ctx.close()
            nav.close()
    finally:
        api.terminate()
    if falhas:
        print("\nFALHAS:")
        for f in falhas:
            print(" -", f)
        print(f"\nnao passou: {len(falhas)} falha(s)")
        return 1
    print(f"\nTUDO OK: {len(TELA) * len(GRADES)} combinacoes medidas (3 tamanhos de janela x grades 2/3/4), "
          f"nenhuma cortada — folga no topo do palco e contorno da janela inteiros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
