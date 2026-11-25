#!/usr/bin/env python3
"""Prova de TELA: a TELA CHEIA do video leva a contagem e o botao junto, e a PAUSA nao encolhe a grade.

Dono, verbatim (25/11/2026): *"quando o vídeo está em tela cheia, a contagem regressiva e o botão para
permanecer conectado não aparecem e quando o tempo se esgota, a transmissão é interrompida"* — e, na
mesma rodada: *"quando as transmissões estão pausadas, a tela diminui"*.

Causa medida no codigo: a tela cheia era pedida no proprio `<video>` (`v.requestFullscreen()`), e nessa
tela o navegador renderiza SO' o video — o card (com a contagem e o "Continuar conectado") e o aviso do
ultimo minuto sao IRMAOS dele. E `proporcaoDaGrade()` usava a MENOR proporcao conhecida: uma camera
parada (que reporta um quadro fora do padrao) encolhia a grade inteira.

O que se prova, num Chromium de verdade contra a API de verdade:

  1) a tela cheia e' pedida na JANELA e o `.janela:fullscreen` existe no CSS (e nao ha' mais nenhum
     `requestFullscreen` em `<video>`);
  2) o DESTAQUE (e a tela cheia) carrega o MESMO controle da grade: `.card-cam > .controle-transmissao`
     com `[data-st]`, o estado "no ar" e a CONTAGEM correndo (ela anda de segundo em segundo);
  3) a proporcao da grade e' a MEDIANA (antes a MENOR): com uma camera "de retrato" (0,5625) e tres 16:9,
     a grade vale 16:9 — a menor encolheria TODAS as celulas;
  4) a proporcao e' DECLARADA pelo encoder quando o video nao pode ser levado a serio: um quadro de
     "sem sinal" (1x1) nao sobrescreve a proporcao conhecida.

    python tests/e2e-tela-cheia-e-pausa.py
"""
from __future__ import annotations

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
SENHA = "senha-da-prova-da-tela-cheia"
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
ESPERA = 20000

JS_PARAR_VISIVEL = ("() => { const b = document.querySelector('.controle-transmissao [data-papel=parar]');"
                    " return b && getComputedStyle(b).display !== 'none'; }")


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


def sessoes_abertas(banco: pathlib.Path) -> int:
    con = sqlite3.connect(str(banco))
    n = con.execute("SELECT count(*) FROM transmissoes WHERE estado IN ('pedida','no_ar')").fetchone()[0]
    con.close()
    return int(n)


def principal() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-cheia-"))
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

            print("\n== 1. a tela cheia e' pedida na JANELA (nao no <video>) e o CSS a sustenta")
            codigo = urllib.request.urlopen(base + "/app/app.js", timeout=10).read().decode("utf-8", "replace")
            # a UNICA linha que pede tela cheia e' a de dentro de `alternarTelaCheia` (o alvo vem por
            # parametro); nenhuma outra aponta para um `<video>`.
            linhas = [ln.strip() for ln in codigo.splitlines() if "requestFullscreen" in ln]
            checar("ha' uma unica linha de tela cheia e ela e' a da janela (alternarTelaCheia)",
                   len(linhas) == 1 and "alvo.requestFullscreen" in linhas[0]
                   and "function alternarTelaCheia(alvo)" in codigo, str(linhas))
            checar("e nenhum <video> pede a tela cheia",
                   "v.requestFullscreen" not in codigo and "video.requestFullscreen" not in codigo)
            css = urllib.request.urlopen(base + "/fronts/vms.css", timeout=10).read().decode("utf-8", "replace")
            sem_espaco = css.replace(" ", "")
            checar("o CSS tem a regra da janela em tela cheia (.janela:fullscreen)",
                   ".janela:fullscreen{" in sem_espaco, sem_espaco[:0])
            checar("e o card fica no rodape da tela cheia (.card-cam dentro do :fullscreen)",
                   ".janela:fullscreen.card-cam{" in sem_espaco)

            print("\n== 2. a transmissao no ar e o DESTAQUE com o MESMO controle da grade")
            pag.locator('.controle-transmissao [data-papel="iniciar"]').click()
            pag.wait_for_function(JS_PARAR_VISIVEL, timeout=ESPERA)
            checar("a transmissao subiu (1 sessao aberta)", sessoes_abertas(banco) == 1,
                   f"{sessoes_abertas(banco)} aberta(s)")
            pag.click("#btn-destaque")
            pag.wait_for_selector("#destaque .janela", timeout=ESPERA)
            pag.wait_for_timeout(1500)
            checar("o destaque tem o card DENTRO da janela e o controle DENTRO do card",
                   pag.locator("#destaque .janela > .card-cam > .controle-transmissao").count() >= 1)
            checar("e o controle do destaque e' o do mesmo contrato ([data-st])",
                   pag.locator('#destaque .controle-transmissao[data-st]').count() >= 1)
            estado = pag.evaluate("""() => { const e = document.querySelector('#destaque [data-papel=estado]');
                return e ? e.textContent : ''; }""")
            # sem o bordo respondendo, a sessao fica "conectando…" (honesto): o que importa aqui e' que o
            # destaque PINTA o estado da transmissao, e nao que o bordo ja' tenha confirmado.
            checar("o destaque pinta o estado da transmissao (no ar / conectando)",
                   ("no ar" in estado.lower() or "conectando" in estado.lower()), estado)
            parar_visivel = pag.evaluate("""() => { const b = document.querySelector('#destaque [data-papel=parar]');
                return !!(b && getComputedStyle(b).display !== 'none'); }""")
            checar("e o botao 'Parar transmissao' esta visivel no destaque", parar_visivel)
            primeira = pag.evaluate("""() => { const c = document.querySelector('#destaque [data-papel=contagem]');
                return c ? c.textContent.trim() : ''; }""")
            checar("a CONTAGEM aparece no destaque", bool(primeira) and ":" in primeira, primeira)
            pag.wait_for_timeout(2600)
            segunda = pag.evaluate("""() => { const c = document.querySelector('#destaque [data-papel=contagem]');
                return c ? c.textContent.trim() : ''; }""")
            checar("e ela ANDA (o destaque e' alcancado pelo tick, nao fica congelado)",
                   bool(segunda) and segunda != primeira, f"{primeira} -> {segunda}")
            aviso = pag.evaluate("""() => { const a = document.querySelector('#destaque [data-papel=aviso]');
                return !!a; }""")
            checar("e o aviso do ultimo minuto existe no destaque (o mesmo que a grade usa)", aviso)

            print("\n== 3. o duplo clique poe a JANELA em tela cheia (card e contagem vao junto)")
            pag.evaluate("() => { const b = Array.from(document.querySelectorAll('#destaque .pil'))"
                         ".find((x) => (x.textContent || '').includes('Voltar')); if (b) b.click(); }")
            pag.wait_for_selector("#destaque", state="detached", timeout=ESPERA)
            pag.wait_for_timeout(600)
            pag.dblclick(".janela video")
            pag.wait_for_timeout(800)
            cheio = pag.evaluate("""() => { const f = document.fullscreenElement;
                if (!f) return null;
                const card = f.querySelector('.card-cam');
                return {classe: f.className, card: !!card,
                        ctrl: !!(card && card.querySelector('.controle-transmissao'))}; }""")
            checar("a tela cheia e' a JANELA (com o card dentro), nao o <video> sozinho",
                   bool(cheio) and "janela" in cheio["classe"] and cheio["card"] and cheio["ctrl"],
                   str(cheio))

            print("\n== 4. a proporcao da grade e' a MEDIANA (uma camera fora do padrao nao encolhe as outras)")
            r = pag.evaluate("""() => {
                const grade = document.createElement('div');
                const por = {a: 0.5625, b: 1.7777778, c: 1.7777778, d: 1.7777778};   // 'a' = retrato
                for (const id of Object.keys(por)) {
                    const j = document.createElement('div');
                    j.className = 'janela'; j.dataset.cam = id; grade.appendChild(j);
                    S.proporcao[id] = por[id];
                }
                return {mediana: proporcaoDaGrade(grade),
                        antigo: Math.min.apply(null, Object.values(por))};
            }""")
            checar("com tres 16:9 e uma de retrato, a grade vale 16:9",
                   abs(r["mediana"] - 16 / 9) < 0.01, str(r))
            checar("a MENOR (o criterio antigo) encolheria tudo", abs(r["antigo"] - 0.5625) < 0.001, str(r))

            print("\n== 4b. MEDICAO (a tela que 'diminui'): a celula com a proporcao errada x a do fluxo")
            # Mede o MESMO painel, no app de verdade, com a proporcao que a grade usa: a errada (1:1, o que
            # a camera parada forcava pelo criterio antigo) e a do fluxo (16:9, o que a mediana/declarada
            # sustenta agora). A imagem pintada e' `contain` dentro da celula, entao a conta e' a mesma da
            # prova de geometria (e2e-imagem-sem-faixa-preta.py).
            pag.evaluate("() => { if (document.fullscreenElement) document.exitFullscreen(); }")
            pag.wait_for_timeout(800)          # sai da tela cheia: a medicao e' na GRADE
            med = pag.evaluate("""() => {
                const jan = document.querySelector('.janela');
                const pintada = (b, r) => [Math.min(b.width, b.height * r), Math.min(b.height, b.width / r)];
                const medir = (razao, rotulo) => {
                    S.proporcao['cam-01'] = razao;
                    ajustarGrade();
                    const b = jan.getBoundingClientRect();
                    const im = pintada(b, 16 / 9);            // o quadro REAL da camera e' 16:9
                    return {rotulo, razao, celula: [Math.round(b.width), Math.round(b.height)],
                            imagem: [Math.round(im[0]), Math.round(im[1])],
                            area: Math.round(im[0] * im[1])};
                };
                return {errada: medir(1.0, 'proporcao 1:1 (a camera parada pelo criterio antigo)'),
                        fluxo: medir(16 / 9, 'proporcao do fluxo 16:9 (a que a mediana sustenta)')};
            }""")
            print("     ", med["errada"]["rotulo"], "-> celula", med["errada"]["celula"],
                  "imagem", med["errada"]["imagem"], f"({med['errada']['area']} px2)")
            print("     ", med["fluxo"]["rotulo"], "-> celula", med["fluxo"]["celula"],
                  "imagem", med["fluxo"]["imagem"], f"({med['fluxo']['area']} px2)")
            ganho = med["fluxo"]["area"] / max(1, med["errada"]["area"])
            print(f"       ganho de area da imagem: {ganho:.2f}x  (+{(ganho - 1) * 100:.0f}%)")
            checar("com a proporcao do fluxo a imagem pintada e' maior que com a errada",
                   med["fluxo"]["area"] > med["errada"]["area"], str(med))

            print("\n== 5. a proporcao do encoder vale quando o video e' um quadro de 'sem sinal'")
            r = pag.evaluate("""() => {
                S.proporcao['x'] = 0;
                const v = document.createElement('video');
                Object.defineProperty(v, 'videoWidth', {get: () => 1});
                Object.defineProperty(v, 'videoHeight', {get: () => 1});
                const img = document.createElement('div');
                proporcaoDaImagem(img, v, {id: 'x'});
                const ficou = S.proporcao['x'];
                const v2 = document.createElement('video');
                Object.defineProperty(v2, 'videoWidth', {get: () => 1280});
                Object.defineProperty(v2, 'videoHeight', {get: () => 720});
                proporcaoDaImagem(img, v2, {id: 'x'});
                return {sem_sinal: ficou, real: S.proporcao['x'],
                        declarada: proporcaoDeclarada({encoder: {resolucao: '1280x720'}}),
                        lixo: proporcaoDeclarada({encoder: {resolucao: 'sem-resolucao'}})};
            }""")
            checar("um quadro 1x1 NAO sobrescreve a proporcao conhecida",
                   r["sem_sinal"] in (0, None), str(r))
            checar("um quadro 1280x720 vale 16:9", abs((r["real"] or 0) - 16 / 9) < 0.01, str(r))
            checar("e a resolucao do encoder vira a proporcao declarada",
                   abs(r["declarada"] - 16 / 9) < 0.01 and r["lixo"] == 0, str(r))

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
    print("OK: a tela cheia leva a contagem junto e a pausa nao encolhe a grade.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
