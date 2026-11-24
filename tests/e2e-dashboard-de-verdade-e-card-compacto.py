#!/usr/bin/env python3
"""Prova de TELA e de DADO da rodada 0.15.0 — o card compacto, a grade responsiva, o bordo mudo e o
DASHBOARD DE VERDADE (24/11/2026).

Dono, verbatim:
  * *"continua diminuindo as telas quando reconecta principalmente, e as telas ainda estao pequenas, elas
    precisam ser mais responsivas e utilizar o maior espaco possivel"*;
  * *"acabei de desinstalar o app de captura para instalar a v0.14.0 e a transmissao continua, como
    continua transmitindo se eu desinstalei o app?"*;
  * *"voce chama aquilo que voce fez de dashboard? preciso de um dashboard real no pc de captura, so tem
    um monte de cards, mas eu quero um dashboard de verdade!"*.

O que se prova, com a API, o Chromium e o banco de verdade:

  1) o card do controle tem UMA linha e altura fixa (34 px) — e a IMAGEM NAO ENCOLHE quando o estado da
     sessao muda (parada -> no ar -> reconectar -> no ar). Era o texto do botao mudando a altura do card
     que encolhia o video ("diminui quando reconecta");
  2) a imagem APROVEITA o espaco da celula (nao sobra a faixa lateral que sobrava);
  3) a grade e' RESPONSIVA: mudar a largura da janela REMEDE a imagem (ResizeObserver no palco);
  4) o bordo MUDO (silencio maior que 180 s) ENCERRA, no lado terra, as sessoes abertas daquela
     embarcacao — e o cliente passa a ver o motivo real, nao "no ar agora" com a imagem parada;
  5) o dashboard do PC de captura e' de VERDADE: as QUATRO CURVAS (CPU, memoria, disco, rede) desenhadas
     a partir da serie que a propria maquina grava — e, sem serie, a tela DIZ "sem serie" (nao inventa);
  6) o Modo TV existe (o monitor do PC de captura fica ligado o dia todo).

    python tests/e2e-dashboard-de-verdade-e-card-compacto.py
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
EMPRESA, EMB, CAM, CAM2 = "emp-1", "emb-1", "cam-01", "cam-02"
SENHA = "senha-da-prova-0150"
ESPERA = 20000
FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f"   [{detalhe}]" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def rotulo(pag, sel: str) -> str:
    """O NOME ACESSIVEL do botao (o cliente le no `title`/`aria-label`; o `innerText` so' tem o glifo)."""
    return pag.evaluate("""(s) => { const e = document.querySelector(s);
        return e ? ((e.getAttribute('title') || '') + ' ' + (e.getAttribute('aria-label') || '')
                    + ' ' + e.innerText) : ''; }""", sel)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def video_de_prova(pasta: pathlib.Path, largura: int, altura: int) -> str:
    """Um mp4 de verdade (1 s) na proporcao pedida, em data URL (a camera 16:9 e' a da grade)."""
    saida = pasta / f"prova-{largura}x{altura}.mp4"
    subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"testsrc=size={largura}x{altura}:rate=10", "-t", "1",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(saida)],
                   check=True, capture_output=True)
    return "data:video/mp4;base64," + base64.b64encode(saida.read_bytes()).decode()


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str, cliente_id: str | None) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    con.commit(); con.close()


def semear(banco: pathlib.Path, com_sessao: bool = False) -> None:
    """Cliente, embarcacao e DUAS cameras. Sem sessao (a prova comeca na camera PARADA)."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    for cid, rot in ((CAM, "Proa"), (CAM2, "Popa")):
        con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                       VALUES (?,?,?,?,'bordo',1,'800k')""", (cid, EMB, rot, cid))
    if com_sessao:
        agora = dt.datetime.now().astimezone()
        con.execute("""INSERT OR REPLACE INTO transmissoes
                       (id,embarcacao_id,camera_id,fluxo_id,usuario_email,segundos_max,criada_em,batimento_em,
                        termina_em,estado,gravando)
                       VALUES ('t-prova-1',?,?,?,?,900,?,?,?, 'no_ar', 0)""",
                    (EMB, CAM, CAM, "cliente@lecsor.test", agora.isoformat(timespec="seconds"),
                     agora.isoformat(timespec="seconds"),
                     (agora + dt.timedelta(seconds=900)).isoformat(timespec="seconds")))
    con.commit(); con.close()


def abrir_sessao(banco: pathlib.Path, idade_do_batimento_s: int = 0) -> None:
    """Abre a sessao da camera 1 (o cliente 'iniciou a transmissao')."""
    con = sqlite3.connect(str(banco))
    agora = dt.datetime.now().astimezone()
    con.execute("""INSERT OR REPLACE INTO transmissoes
                   (id,embarcacao_id,camera_id,fluxo_id,usuario_email,segundos_max,criada_em,batimento_em,
                    termina_em,estado,gravando)
                   VALUES ('t-prova-1',?,?,?,?,900,?,?,?, 'no_ar', 0)""",
                (EMB, CAM, CAM, "cliente@lecsor.test", agora.isoformat(timespec="seconds"),
                 (agora - dt.timedelta(seconds=idade_do_batimento_s)).isoformat(timespec="seconds"),
                 (agora + dt.timedelta(seconds=900)).isoformat(timespec="seconds")))
    con.commit(); con.close()


def abrir_sessao_sem_bordo(banco: pathlib.Path, segundos_de_silencio: int) -> None:
    """Uma sessao aberta e um bordo que nao fala ha' `segundos_de_silencio` (o bordo mudo)."""
    con = sqlite3.connect(str(banco))
    antigo = (dt.datetime.now().astimezone()
              - dt.timedelta(seconds=segundos_de_silencio)).isoformat(timespec="seconds")
    con.execute("DELETE FROM estado_bordo WHERE embarcacao_id=?", (EMB,))
    con.execute("DELETE FROM saude_bordo WHERE embarcacao_id=?", (EMB,))
    con.execute("""INSERT INTO saude_bordo (embarcacao_id, recebido_em, maquina, versao_app, estado, retrato)
                   VALUES (?,?,?,?,?,?)""",
                (EMB, antigo, "PC-CAPTURA-PROVA", "0.15.0", "ok",
                 json.dumps({"gerado_em": antigo, "cpu_pct": 10.0, "memoria_pct": 20.0,
                             "discos": [], "rede": {}}, ensure_ascii=False)))
    con.execute("""INSERT OR REPLACE INTO transmissoes
                   (id,embarcacao_id,camera_id,fluxo_id,usuario_email,segundos_max,criada_em,batimento_em,
                    termina_em,estado,gravando)
                   VALUES ('t-mudo-1',?,?,?,?,7200,?,?,?, 'no_ar', 0)""",
                (EMB, CAM, CAM, "cliente@lecsor.test", antigo, antigo,
                 (dt.datetime.now().astimezone() + dt.timedelta(seconds=7200)).isoformat(timespec="seconds")))
    con.commit(); con.close()


def estado_da_sessao(banco: pathlib.Path, tid: str) -> tuple[str, str]:
    con = sqlite3.connect(str(banco))
    linha = con.execute("SELECT estado, COALESCE(motivo,'') FROM transmissoes WHERE id=?", (tid,)).fetchone()
    con.close()
    return (linha[0], linha[1]) if linha else ("", "")


def termina_em(banco: pathlib.Path, tid: str):
    """O `termina_em` da sessao como INSTANTE (o ISO vem com fuso: `-03:00` do semeio, `+00:00` da API)."""
    con = sqlite3.connect(str(banco))
    linha = con.execute("SELECT COALESCE(termina_em,'') FROM transmissoes WHERE id=?", (tid,)).fetchone()
    con.close()
    if not linha or not linha[0]:
        return None
    return dt.datetime.fromisoformat(linha[0])


def anotar_serie(pasta: pathlib.Path, quantos: int = 8) -> pathlib.Path:
    """O anel local da saude que ESTA maquina grava (o que o dashboard desenha)."""
    alvo = pasta / "historico-da-saude.jsonl"
    base = dt.datetime.now().astimezone() - dt.timedelta(seconds=60 * quantos)
    linhas = []
    for i in range(quantos):
        linhas.append(json.dumps({
            "t": (base + dt.timedelta(seconds=60 * i)).isoformat(timespec="seconds"),
            "cpu": 20 + 5 * i, "mem": 40 + 4 * i, "disco": 61.5, "disco_livre_gb": 120.0,
            "disco_nome": "hd do radar", "rede_mbps": 1.0 + 0.5 * i, "rede_env_mb": 100.0,
            "rede_rec_mb": 200.0, "up_s": 3600 + 60 * i}, ensure_ascii=False))
    alvo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return alvo


# ---------------------------------------------------------------- JS de apoio
JS_POE_VIDEO = """async (url) => {
  const v = document.querySelector('.janela video');
  await new Promise((ok) => { v.addEventListener('loadedmetadata', ok, {once: true}); v.src = url; v.load(); });
  await new Promise((ok) => setTimeout(ok, 400));
  return true;
}"""

JS_MEDIR = """() => {
  const jan = document.querySelector('.janela');
  const img = jan.querySelector('.img-cam');
  const card = jan.querySelector('.card-cam');
  const palco = document.querySelector('#palco');
  const cel = jan.getBoundingClientRect();
  const c = img.getBoundingClientRect();
  const k = card ? card.getBoundingClientRect() : {width: 0, height: 0};
  return {l: c.width, a: c.height, cardA: k.height, cardL: k.width,
          linhasDoCard: card ? card.getClientRects().length : 0,
          celulaL: cel.width, palcoL: palco.getBoundingClientRect().width};
}"""


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-0150-"))
    banco = tmp / "pipeline.db"
    historico = anotar_serie(tmp, 8)
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_EMBARCACAO", "LECSOR_LICENCA"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_SAUDE_HISTORICO": str(historico), "LECSOR_HD_DIR": str(tmp / "hd"),
                "PYTHONIOENCODING": "utf-8"})
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

        criar_usuario(banco, "cli", "cliente@lecsor.test", "cliente", EMPRESA)
        semear(banco, com_sessao=False)

        # ---------------- 4 (dado): o BORDO MUDO encerra a sessao ----------------
        print("\n== 4. bordo MUDO (silencio > 180 s) ENCERRA a sessao aberta no lado terra ==")
        abrir_sessao_sem_bordo(banco, segundos_de_silencio=400)
        est, motivo = estado_da_sessao(banco, "t-mudo-1")
        checar("a sessao comeca 'no_ar' (contra o bordo mudo)", est == "no_ar", est)
        limite = time.time() + 30
        while time.time() < limite and estado_da_sessao(banco, "t-mudo-1")[0] not in ("sem_sinal", "encerrada"):
            time.sleep(0.5)
        est, motivo = estado_da_sessao(banco, "t-mudo-1")
        print("        estado final:", est, "| motivo:", motivo)
        checar("o vigia do lado terra ENCERROU a sessao (ninguem clicou)",
               est in ("sem_sinal", "encerrada"), est)
        checar("e o motivo diz que o bordo ficou mudo", "bordo" in motivo.lower() or "mud" in motivo.lower()
               or "sinal" in motivo.lower(), motivo)

        # ---------------- 5 (dado): a SERIE que o dashboard desenha ----------------
        print("\n== 5. a serie da saude (o que o dashboard desenha) ==")
        with urllib.request.urlopen(base + "/api/bordo/serie?pontos=720", timeout=5) as r:
            serie = json.loads(r.read())
        print("        origem:", serie.get("origem"), "| pontos:", len(serie.get("pontos") or []))
        checar("a serie tem os oito pontos que a maquina gravou", len(serie.get("pontos") or []) == 8,
               str(len(serie.get("pontos") or [])))
        p0 = (serie.get("pontos") or [{}])[0]
        checar("cada ponto traz cpu, mem, disco e rede_mbps",
               all(k in p0 for k in ("cpu", "mem", "disco", "rede_mbps")), str(sorted(p0.keys())))

        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())

            # ---------------- 1 a 3: a tela do CLIENTE ----------------
            pag = navegador.new_context(viewport={"width": 1600, "height": 900}).new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())
            pag.goto(base + "/entrada/")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector(".card-cam", timeout=ESPERA)
            pag.wait_for_timeout(800)
            pag.evaluate(JS_POE_VIDEO, video_de_prova(tmp, 640, 360))

            print("\n== 1. o card tem UMA linha e altura fixa; a imagem NAO encolhe nos estados ==")
            parada = pag.evaluate(JS_MEDIR)
            print("        (parada):", json.dumps(parada))
            checar("o card do controle cabe em UMA linha de 34 px",
                   parada["cardA"] <= 40 and parada["cardA"] >= 26, f"altura={parada['cardA']:.1f}")
            # agora a sessao abre: o texto do botao muda para 'Parar'/'Reconectar'
            abrir_sessao(banco, 0)
            pag.evaluate("async () => { await carregarTransmissao(); redesenharTransmissao(); }")
            pag.wait_for_timeout(1200)
            no_ar = pag.evaluate(JS_MEDIR)
            print("        (no ar) :", json.dumps(no_ar))
            checar("a ALTURA da imagem NAO muda da parada para o ar (o card nao incha)",
                   abs(parada["a"] - no_ar["a"]) < 0.6, f"{parada['a']:.1f} -> {no_ar['a']:.1f}")
            checar("a LARGURA da imagem NAO muda da parada para o ar",
                   abs(parada["l"] - no_ar["l"]) < 0.6, f"{parada['l']:.1f} -> {no_ar['l']:.1f}")
            checar("e o card segue em UMA linha com a sessao no ar",
                   no_ar["cardA"] <= 40, f"altura={no_ar['cardA']:.1f}")

            print("\n== 2. a imagem APROVEITA o espaco da celula ==")
            aproveitamento = (no_ar["l"] / no_ar["celulaL"]) if no_ar["celulaL"] else 0
            print(f"        imagem={no_ar['l']:.0f} de {no_ar['celulaL']:.0f} da celula "
                  f"({aproveitamento * 100:.0f}%)")
            checar("a imagem ocupa a maior parte da largura da celula (>= 90%)", aproveitamento >= 0.90,
                   f"{aproveitamento * 100:.0f}%")

            print("\n== 3. a grade e' RESPONSIVA (mudar a janela REMEDE a imagem) ==")
            pag.set_viewport_size({"width": 1180, "height": 900})
            pag.wait_for_timeout(900)
            estreita = pag.evaluate(JS_MEDIR)
            print("        (janela 1180):", json.dumps(estreita))
            checar("a imagem remediu para a janela mais estreita",
                   abs(estreita["l"] - no_ar["l"]) > 2, f"{no_ar['l']:.1f} -> {estreita['l']:.1f}")
            pag.set_viewport_size({"width": 1600, "height": 900})
            pag.wait_for_timeout(900)
            voltei = pag.evaluate(JS_MEDIR)
            checar("e VOLTOU ao tamanho de antes quando a janela voltou",
                   abs(voltei["l"] - no_ar["l"]) < 2, f"{voltei['l']:.1f} vs {no_ar['l']:.1f}")
            checar("sem erro de JS na tela do cliente", not erros, "; ".join(erros[:3]))
            pag.close()

            # ---------------- 6: o dashboard de VERDADE ----------------
            print("\n== 6. dashboard do PC de captura: as curvas e o Modo TV ==")
            bordo = navegador.new_context(viewport={"width": 1400, "height": 950}).new_page()
            bordo.on("pageerror", lambda e: erros.append("bordo: " + str(e)))
            bordo.goto(base + "/bordo")
            bordo.wait_for_selector("#curvas", timeout=ESPERA)
            bordo.wait_for_timeout(1500)
            painel = bordo.evaluate("""() => {
              const svgs = Array.from(document.querySelectorAll('#curvas svg'));
              return {
                quantas: svgs.length,
                comLinha: svgs.filter((s) => s.querySelector('path.linha')).length,
                ids: svgs.map((s) => s.id),
                nota: (document.getElementById('curva-nota') || {}).textContent || '',
                valores: Array.from(document.querySelectorAll('#curvas .agora')).map((e) => e.textContent.trim()),
                tv: !!document.getElementById('tv'),
              };
            }""")
            print("       ", json.dumps(painel, ensure_ascii=False)[:320])
            checar("o dashboard tem as QUATRO curvas (CPU, memoria, disco, rede)", painel["quantas"] == 4,
                   str(painel["ids"]))
            checar("TODAS desenharam a LINHA da serie (nao sao so cartoes)", painel["comLinha"] == 4,
                   f"{painel['comLinha']}/4 com linha")
            checar("cada curva mostra o valor de agora", all(v not in ("", "—") for v in painel["valores"]),
                   str(painel["valores"]))
            checar("a nota declara a serie (de onde ela vem)", len(painel["nota"]) > 20, painel["nota"][:80])
            checar("existe o Modo TV", painel["tv"])

            print("\n== 6b. sem serie, a tela DIZ 'sem serie' (nao inventa curva) ==")
            bordo.evaluate("() => { for (const c of CURVAS) desenharCurva(c, []); }")
            vazio = bordo.evaluate("""() => {
              const svg = document.getElementById('g-cpu');
              return { linhas: svg.querySelectorAll('path.linha').length,
                       vazio: (svg.querySelector('text.vazio') || {}).textContent || '' };
            }""")
            checar("sem serie a curva fica VAZIA (nenhum traco) e a tela diz 'sem serie'",
                   vazio["linhas"] == 0 and "sem s\u00e9rie" in vazio["vazio"], json.dumps(vazio, ensure_ascii=False))
            falou = bordo.evaluate("""() => { carregarCurvas(); return true; }""")
            bordo.wait_for_timeout(800)
            nota = bordo.inner_text("#curva-nota")
            checar("e a serie VOLTA ao vivo quando ela existe", "ponto" in nota.lower(), nota[:90])
            bordo.close()

            # ---------------- 7: o aviso do ULTIMO MINUTO e' CLICAVEL na tela do dono ----------------
            print("\n== 7. 'Continuar conectado' e' CLICAVEL com TRES cameras em 1600x900 (a tela do dono) ==")
            # O dono (24/11/2026): "nao da pra clicar no botao para continuar conectado nas duas
            # cameras". A causa medida foi o aviso cair no CARD (o `.img-cam` ainda nao estava pendurado
            # no quadro quando o controle foi montado); com o card em uma linha, a caixa do aviso
            # estourava a largura da janela e o botao ficava FORA da area visivel, cortado pelo
            # `overflow:hidden`. Aqui se mede o que o clique acerta e se a sessao e' RENOVADA de verdade.
            con = sqlite3.connect(str(banco))
            con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                           VALUES ('cam-03',?,'USB Video (2)','cam-03','bordo',1,'800k')""", (EMB,))
            # ATENCAO: o vigia compara os carimbos como TEXTO e a API grava tudo em UTC (`+00:00`).
            # Semeie em UTC — semear no fuso local (`-03:00`) faz o texto parecer mais ANTIGO que o
            # limite e o proprio vigia encerra a sessao que a prova quer manter no ar.
            agora = dt.datetime.now(dt.timezone.utc)
            for tid in ("t-prova-1", "t-mudo-1"):
                con.execute("""INSERT OR REPLACE INTO transmissoes
                               (id,embarcacao_id,camera_id,fluxo_id,usuario_email,segundos_max,criada_em,
                                batimento_em,termina_em,estado,gravando)
                               VALUES (?,?,?,?,?,900,?,?,?, 'no_ar', 0)""",
                            (tid, EMB, CAM if tid == "t-prova-1" else CAM2, CAM, "cliente@lecsor.test",
                             agora.isoformat(timespec="seconds"), agora.isoformat(timespec="seconds"),
                             (agora + dt.timedelta(seconds=50)).isoformat(timespec="seconds")))
            # ... e um bordo VIVO: sem isto o vigia do bordo mudo (Fase 6) encerraria a sessao no meio da
            # prova e a assercao "segue no ar" mediria a regra do bordo mudo, nao o clique do aviso.
            con.execute("DELETE FROM saude_bordo WHERE embarcacao_id=?", (EMB,))
            con.execute("""INSERT INTO saude_bordo (embarcacao_id, recebido_em, maquina, versao_app, estado, retrato)
                           VALUES (?,?,?,?,?,?)""",
                        (EMB, agora.isoformat(timespec="seconds"), "PC-CAPTURA-PROVA", "0.15.0", "ok",
                         json.dumps({"gerado_em": agora.isoformat(timespec="seconds"), "cpu_pct": 10.0,
                                     "memoria_pct": 20.0, "discos": [], "rede": {}}, ensure_ascii=False)))
            con.commit(); con.close()
            pag7 = navegador.new_context(viewport={"width": 1600, "height": 900}).new_page()
            pag7.on("pageerror", lambda e: erros.append("p7: " + str(e)))
            pag7.goto(base + "/entrada/")
            pag7.fill("#email", "cliente@lecsor.test")
            pag7.fill("#senha", SENHA)
            pag7.click("form#form-entrar button[type=submit]")
            pag7.wait_for_selector(".st-aviso.mostra", timeout=ESPERA + 15000)
            pag7.wait_for_timeout(800)
            alvo = pag7.evaluate("""() => {
              const a = document.querySelector('.st-aviso.mostra');
              const b = a.querySelector('[data-papel="continuar"]');
              const rb = b.getBoundingClientRect();
              const cx = rb.left + rb.width / 2, cy = rb.top + rb.height / 2;
              const img = a.closest('.img-cam');
              const ri = img ? img.getBoundingClientRect() : null;
              const jan = a.closest('.janela').getBoundingClientRect();
              const rj = a.closest('.janela').getBoundingClientRect();
              const topo = document.elementFromPoint(cx, cy);
              return {aviso_dentro_da_imagem: !!img,
                      botao: {l: Math.round(rb.left), t: Math.round(rb.top), r: Math.round(rb.right),
                              b: Math.round(rb.bottom)},
                      imagem: ri ? {l: Math.round(ri.left), t: Math.round(ri.top), r: Math.round(ri.right),
                                    b: Math.round(ri.bottom)} : null,
                      janela: {l: Math.round(rj.left), t: Math.round(rj.top), r: Math.round(rj.right),
                               b: Math.round(rj.bottom)},
                      acerta_no_centro: topo ? (topo.tagName + '.' + String(topo.className || '')) : 'null',
                      clicavel: !!(topo && topo.getAttribute && topo.getAttribute('data-papel') === 'continuar')};
            }""")
            print("       ", json.dumps(alvo, ensure_ascii=False))
            checar("o aviso mora DENTRO da imagem (nao no card)", alvo["aviso_dentro_da_imagem"])
            checar("a caixa do aviso cabe na largura da janela",
                   alvo["janela"] and alvo["botao"]["r"] <= alvo["janela"]["r"]
                   and alvo["botao"]["l"] >= alvo["janela"]["l"],
                   f"botao={alvo['botao']} janela={alvo['janela']}")
            checar("o CENTRO do botao acerta o proprio botao (nao um elemento por cima)",
                   alvo["clicavel"], alvo["acerta_no_centro"])
            antes = termina_em(banco, "t-prova-1")
            botao7 = pag7.locator('.st-aviso [data-papel="continuar"]').first
            botao7.click(timeout=8000)
            pag7.wait_for_timeout(1500)
            depois = termina_em(banco, "t-prova-1")
            est7, _ = estado_da_sessao(banco, "t-prova-1")
            print(f"        termina_em: {antes} -> {depois} | estado: {est7}")
            checar("o clique RENOVOU a sessao (termina_em foi empurrado para frente)",
                   bool(antes and depois and depois > antes), f"{antes} -> {depois}")
            checar("e a sessao segue no ar (nao encerrou com o clique)", est7 == "no_ar", est7)
            pag7.close()
            navegador.close()

        print("\n" + "=" * 72)
        if falhas:
            print(f"FALHOU: {len(falhas)} — " + " | ".join(falhas))
            return 1
        print("TUDO VERDE: card compacto, grade responsiva, bordo mudo e dashboard de verdade.")
        return 0
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            api.kill()


falhas: list[str] = []

if __name__ == "__main__":
    sys.exit(main())
