#!/usr/bin/env python3
"""A TELA NAO "PISCA" E TEM O BOTAO DE REFAZER VARREDURA (Fases 2 e 3, 26/11/2026) — prova de TELA.

O dono (26/11/2026, verbatim):
  * "quando a pagina atualiza, parece que remonta toda a pagina, isso e' horrivel, eu estou fazendo algo
    e do nada a pagina 'pisca' e eu perco o que estou fazendo";
  * "nesta tela preciso tambem de um botao para refazer varredura, para que caso tenha sido removida uma
    camera por engano, ou nao estao aparecendo cameras novas, o app de captura precisa refazer a
    varredura das cameras, mas apenas inclui as que nao estao aparecendo, nao remonta tudo pra nao perder
    as configuracoes ja feitas".

Como se prova "nao remontou" sem confiar em narrativa: poe-se uma MARCA no objeto do DOM (uma propriedade
que so' existe naquele no') e confere-se, DEPOIS da acao, que o no' e' o MESMO. Marca que sobrevive =
no' que nao foi recriado. E' o unico jeito honesto de mostrar que a tela nao foi reconstruida.

    python tests/test-tela-sem-piscar-e-varredura.py
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
EMPRESA, EMB = "petrobras", "emb-1"
CAM_1, CAM_2 = "cam-01", "cam-02"


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


def criar_usuario(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES ('admin','admin@lecsor.test','admin','admin',NULL,?,?,200000,1)""", (senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    for cid, rot in ((CAM_1, "Proa"), (CAM_2, "Popa")):
        con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo,tipo)
                       VALUES (?,?,?,?,'bordo',1,'800k','camera')""", (cid, EMB, rot, cid))
    con.commit()
    con.close()


def entrar(pag, base: str) -> None:
    pag.goto(base + "/entrada/")
    pag.fill("#email", "admin@lecsor.test")
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector("button[data-tela=empresas]", timeout=ESPERA)
    pag.wait_for_load_state("networkidle")


def pedir(metodo: str, url: str, corpo=None, cookie: str = ""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)
    if dados is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", "sessao=" + cookie)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


MARCA_JS = ("window.__marca = 'viva';"
            "document.querySelectorAll('.cartao-camera').forEach((n) => { n.__marca = 'viva'; });"
            "document.querySelectorAll('.cartao-embarcacao').forEach((n) => { n.__marca = 'viva'; });"
            "true")


def main() -> int:
    print("TELA SEM PISCA + REFAZER VARREDURA — 26/11/2026\n")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-sem-piscar-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO", "LECSOR_LICENCA"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_EMBARCACAO": "bancada", "LECSOR_SENHA_DEMO": "senha-de-bancada-nao-usada",
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
            raise RuntimeError("a API nao subiu: " + (tmp / "api.log").read_text(errors="replace")[-800:])
        criar_usuario(banco)
        semear(banco)

        erros: list[str] = []
        with sync_playwright() as p:
            nav = p.chromium.launch(executable_path=_chromium())
            pag = nav.new_context().new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())
            entrar(pag, base)
            pag.locator(".cartao-empresa").filter(has_text="Petrobras").locator("text=Abrir").first.click()
            pag.wait_for_selector('.cartao-camera[data-cam="cam-01"]', timeout=ESPERA)
            pag.wait_for_timeout(1200)
            checar("a empresa abriu com os 2 cartoes de camera",
                   pag.locator(".cartao-camera").count() == 2,
                   f"{pag.locator('.cartao-camera').count()} cartoes")

            # ===================== FASE 2: a acao NAO remonta a tela =====================
            print("\n== Fase 2: aplicar o TIPO atualiza SO' o cartao (a tela nao e' remontada) ==")
            pag.evaluate(MARCA_JS)
            carta1 = pag.locator('.cartao-camera[data-cam="' + CAM_1 + '"]')
            carta1.locator('select[data-papel="tipo"]').select_option("radar")
            carta1.locator("text=aplicar tipo").click()
            pag.wait_for_function("document.querySelector('#tela').innerText.includes('tipo gravado')", timeout=ESPERA)
            # (a) o TIPO aparece no cartao depois da acao (o defeito do dono: "nao esta persistindo")
            checar("o cartao passa a mostrar o tipo aplicado (radar de oleo)",
                   carta1.locator('select[data-papel="tipo"]').input_value() == "radar",
                   carta1.locator('select[data-papel="tipo"]').input_value())
            checar("e o selo do tipo aparece no cartao ('radar de oleo')",
                   "radar de óleo" in pag.locator('.cartao-camera[data-cam="' + CAM_1 + '"]').inner_text(),
                   pag.locator('.cartao-camera[data-cam="' + CAM_1 + '"]').inner_text()[:120].replace("\n", " | "))
            # (b) o OUTRO cartao continua sendo o MESMO no' do DOM (marca viva): a tela nao foi remontada
            marca2 = pag.evaluate("(document.querySelector('.cartao-camera[data-cam=\"cam-02\"]') || {}).__marca || ''")
            checar("o OUTRO cartao e' o MESMO no' do DOM (a tela nao foi remontada)", marca2 == "viva", f"marca={marca2!r}")
            marcaEmb = pag.evaluate("(document.querySelector('.cartao-embarcacao') || {}).__marca || ''")
            checar("e o cartao da embarcacao idem (o resto da tela ficou intacto)", marcaEmb == "viva", f"marca={marcaEmb!r}")

            # ===================== FASE 3: o botao de refazer varredura =====================
            print("\n== Fase 3: o botao 'refazer varredura' na embarcacao ==")
            # Marca um no' FORA do cartao da embarcacao (um cartao de camera e um bloco da tela): e' por
            # eles que se prova que o resto da tela nao foi remontado quando o cartao da embarcacao muda.
            pag.evaluate(MARCA_JS)
            pag.evaluate("document.querySelectorAll('.caixa-form').forEach((n) => { n.__marca = 'viva'; }); true")
            cartaEmb = pag.locator(".cartao-embarcacao").filter(has_text="PSV LECSOR I")
            tem = cartaEmb.locator("text=refazer varredura").count()
            checar("o botao existe no cartao da embarcacao", tem == 1, f"{tem} botao(oes)")
            cartaEmb.locator("text=refazer varredura").first.click()
            pag.wait_for_function("document.querySelector('#tela').innerText.includes('varredura pedida')", timeout=ESPERA)
            con = sqlite3.connect(str(banco))
            linha = con.execute("""SELECT valor,versao FROM config_bordo
                                   WHERE embarcacao_id=? AND camera_id='' AND chave='varrer'""", (EMB,)).fetchone()
            con.close()
            checar("o pedido saiu como CONFIGURACAO publicada (chave `varrer` na embarcacao)",
                   bool(linha) and bool(linha[0]), f"{linha}")
            nota = pag.locator(".cartao-embarcacao").filter(has_text="PSV LECSOR I").inner_text()
            checar("e o cartao diz que o pedido esta' esperando o bordo",
                   "pedido:" in nota and "aguardando o bordo" in nota, nota[:160].replace("\n", " | "))
            fora = pag.evaluate("""() => {
                const ns = Array.from(document.querySelectorAll('.caixa-form'));
                return ns.length && ns.every((n) => n.__marca === 'viva');
            }""")
            checar("o resto da tela NAO foi remontado (os blocos fora do cartao seguem os mesmos no's)", bool(fora))
            # Pedir DE NOVO tem que gerar versao NOVA (e' a versao que faz o bordo ver pedido novo).
            cartaEmb.locator("text=refazer varredura").first.click()
            versao2 = 0
            for _ in range(20):
                con = sqlite3.connect(str(banco))
                v = con.execute("""SELECT versao FROM config_bordo
                                   WHERE embarcacao_id=? AND camera_id='' AND chave='varrer'""", (EMB,)).fetchone()
                con.close()
                versao2 = int(v[0]) if v else 0
                if versao2 >= 2:
                    break
                time.sleep(0.5)
            checar("pedir de novo gera uma versao NOVA (o bordo nao confunde pedido velho com novo)",
                   versao2 >= 2, f"versao={versao2}")

            # ===================== FASE 2 (timer): 15 s depois a tela continua a mesma =================
            print("\n== Fase 2 (timer de 15 s): mudanca no servidor NAO repinta a tela de trabalho ==")
            pag.evaluate(MARCA_JS)
            # Mexe no dado PELO SERVIDOR (muda o rotulo por HTTP): a assinatura da tela muda de verdade e o
            # timer de 15 s acorda com novidade — que e' exatamente o gatilho do "pisca" do dono.
            pag.evaluate("""async () => {
                await fetch('/api/cameras/' + encodeURIComponent('cam-02') + '/editar',
                            { method: 'POST', headers: {'Content-Type': 'application/json'},
                              body: JSON.stringify({ rotulo: 'Popa (mudou no servidor)' }) });
            }""")
            print("   ..   esperando o timer de 15 s acionar (ate' 35 s)…")
            try:
                pag.wait_for_function(
                    "() => ((document.getElementById('status-atualizar') || {}).textContent || '')"
                    ".indexOf('mudan\\u00e7a nova') >= 0", timeout=35000)
                avisou = True
            except Exception:  # noqa: BLE001
                avisou = False
            checar("o auto-refresh AVISA ('ha mudanca nova') em vez de repintar por baixo do usuario", avisou,
                   (pag.inner_text("#status-atualizar") if pag.locator("#status-atualizar").count() else ""))
            marcas = pag.evaluate("""() => {
                const ns = Array.from(document.querySelectorAll('.cartao-camera'));
                return ns.length && ns.every((n) => n.__marca === 'viva');
            }""")
            checar("e a tela continua a MESMA (nenhum cartao recriado pelo timer)", bool(marcas), f"marcas={marcas}")
            checar("o campo em que o usuario estava nao foi perdido (o cartao do tipo segue com 'radar')",
                   pag.locator('.cartao-camera[data-cam="' + CAM_1 + '"] select[data-papel="tipo"]').input_value() == "radar")
            # O plano pede MAIS DE DOIS CICLOS do timer (40 s no total): mais um ciclo sem remontagem.
            print("   ..   mais um ciclo do timer (16 s) para fechar 2 ciclos…")
            pag.wait_for_timeout(16000)
            segue = pag.evaluate("""() => {
                const ns = Array.from(document.querySelectorAll('.cartao-camera'));
                return ns.length && ns.every((n) => n.__marca === 'viva');
            }""")
            checar("depois de DOIS ciclos do timer a tela continua a mesma (nada foi remontado)", bool(segue))
            checar("nenhum erro de JavaScript na tela", not erros, "; ".join(erros[:3]))
            nav.close()
        print(f"   (bancada: {tmp})")
    finally:
        api.kill()

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} verificacao(oes) — {falhas}")
        return 1
    print("TUDO VERDE: a acao atualiza so' o cartao, o timer nao repinta a tela de trabalho e o pedido de varredura sai.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
