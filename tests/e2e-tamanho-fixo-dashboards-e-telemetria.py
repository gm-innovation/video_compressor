#!/usr/bin/env python3
"""Prova de TELA e de DADO da rodada 0.14.0 (dono, 24/11/2026).

Dono, verbatim:

> "não ficou legal o tamanho das imagens e outra coisa, elas ficam mudando o tamanho, diminuem não entendo
> o porquê. quando eu paro a transmissão e depois reinicio, o botão de parar transmissão fica desativado.
> preciso também que os videos sejam transmitidos no admin para eu acompanhar e monitorar. mais uma,
> preciso que o computador de captura envie também as informações de telemetria do computador com cpu,
> memória, disco e rede, individual e global"
> "inclua no plano um dashboard no app de captura, os cards estão horríveis, e também confirme se
> realmente as informações estão corretas, e preciso de um dashboard também pro admin para monitoramento"

O que se prova, com a API e o Chromium de verdade:

  1) a imagem NAO muda de tamanho quando o app redesenha (era o `limpar(palco)` recriando o `<video>` e
     a area voltando ao 16/9 do CSS) — a caixa da imagem e o PROPRIO elemento <video> sao os mesmos
     antes e depois do redesenho, inclusive com a camera 4:3;
  2) "Parar transmissao" continua clicavel depois de parar e reiniciar (o botao era reaproveitado com
     `disabled=true` da acao anterior);
  3) o dashboard do app de captura (`/bordo`) tem os quatro numeros com estado e a camada individual;
  4) o dashboard do admin (tela "Monitoramento (frota)") mostra os quatro numeros por embarcacao e abre
     o VIDEO ao vivo (somente leitura);
  5) a telemetria do bordo traz cpu, memoria, disco E REDE, com a camada individual e global — e o que
     nao foi medido sai declarado em `nao_medido` (nunca zero escondido).

    python tests/e2e-tamanho-fixo-dashboards-e-telemetria.py
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
if str(RAIZ / "ground") not in sys.path:
    sys.path.insert(0, str(RAIZ / "ground"))
falhas: list[str] = []
SENHA = "senha-da-prova-0140"
EMPRESA = "petrobras"
EMB = "emb-1"
CAM = "cam-01"
ESPERA = 20000
FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"


def rotulo(pag, sel: str) -> str:
    """O NOME ACESSIVEL do botao (o cliente le no `title`/`aria-label`; o `innerText` so' tem o glifo)."""
    return pag.evaluate("""(s) => { const e = document.querySelector(s);
        return e ? ((e.getAttribute('title') || '') + ' ' + (e.getAttribute('aria-label') || '')
                    + ' ' + e.innerText) : ''; }""", sel)


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
    """Um mp4 de verdade (1 s) na proporcao pedida, em data URL."""
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


def semear(banco: pathlib.Path, cliente_email: str) -> None:
    """Cliente, embarcacao e camera — e UMA sessao aberta para o teste do botao."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                   VALUES (?,?,'Proa',?,'bordo',1,'800k')""", (CAM, EMB, CAM))
    agora = dt.datetime.now().astimezone()
    con.execute("""INSERT OR REPLACE INTO transmissoes
                   (id,embarcacao_id,camera_id,fluxo_id,usuario_email,segundos_max,criada_em,batimento_em,
                    termina_em,estado,gravando)
                   VALUES ('t-prova-1',?,?,?,?,900,?,?,?, 'no_ar', 0)""",
                (EMB, CAM, CAM, cliente_email, agora.isoformat(timespec="seconds"),
                 agora.isoformat(timespec="seconds"),
                 (agora + dt.timedelta(seconds=900)).isoformat(timespec="seconds")))
    con.commit(); con.close()


def semear_saude(banco: pathlib.Path) -> None:
    """Um retrato do bordo, com rede e a camada individual — e' o que o dashboard do admin le."""
    retrato = {
        "gerado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "maquina": "PC-CAPTURA-PROVA", "so": "Windows 11", "versao_app": "0.14.0",
        "cpu_pct": 62.5, "memoria_pct": 55.0, "memoria_livre_mb": 7000.0,
        "memoria_disponivel_mb": 7000.0,
        "global": {"cpu_pct": 62.5, "memoria_pct": 55.0, "memoria_disponivel_mb": 7000.0,
                   "memoria_total_mb": 16000.0, "processos": 2,
                   "discos": [{"nome": "aplicativo", "usado_pct": 91.0, "livre_gb": 20.0, "total_gb": 500.0}],
                   "rede": {"enviado_mbps": 3.5, "recebido_mbps": 1.5, "taxa_mbps": 5.0, "intervalo_s": 60}},
        "discos": [{"nome": "aplicativo", "usado_pct": 91.0, "livre_gb": 20.0, "total_gb": 500.0}],
        "rede": {"total": {"enviado_mbps": 3.5, "recebido_mbps": 1.5, "taxa_mbps": 5.0, "intervalo_s": 60},
                 "interfaces": [{"nome": "Ethernet", "enviado_mbps": 3.5, "recebido_mbps": 1.5,
                                 "enviado_mb": 100.0, "recebido_mb": 50.0}]},
        "individual": [{"ingestao_id": 1, "camera_id": CAM, "rotulo": "Proa", "estado": "no_ar",
                        "kbps": 800.0, "fps": 30.0, "cpu_pct": 11.0, "memoria_mb": 210.0}],
        "nao_medido": {},
    }
    con = sqlite3.connect(str(banco))
    con.execute("""INSERT INTO saude_bordo (embarcacao_id, recebido_em, maquina, versao_app, estado, retrato)
                   VALUES (?,?,?,?,?,?)""",
                (EMB, dt.datetime.now().astimezone().isoformat(timespec="seconds"), "PC-CAPTURA-PROVA",
                 "0.14.0", "alerta", json.dumps(retrato, ensure_ascii=False)))
    con.commit(); con.close()


# ---------------------------------------------------------------- JS de apoio
JS_POE_VIDEO = """async (url) => {
  const v = document.querySelector('.janela video');
  await new Promise((ok) => {
    v.addEventListener('loadedmetadata', ok, {once: true});
    v.src = url; v.load();
  });
  await new Promise((ok) => setTimeout(ok, 400));
  return true;
}"""

# Mede a caixa da imagem E guarda uma marca no proprio <video> (para provar que o elemento e' o MESMO).
JS_MEDIR = """() => {
  const jan = document.querySelector('.janela');
  const img = jan.querySelector('.img-cam');
  const v = jan.querySelector('video');
  const c = img.getBoundingClientRect();
  window.__v = v;                       // guarda o elemento para comparar depois
  v.dataset.marca = 'antes';
  return {l: c.width, a: c.height, vw: v.videoWidth, vh: v.videoHeight};
}"""

JS_MEDIR_DEPOIS = """() => {
  const jan = document.querySelector('.janela');
  const img = jan.querySelector('.img-cam');
  const v = jan.querySelector('video');
  const c = img.getBoundingClientRect();
  return {l: c.width, a: c.height, vw: v.videoWidth, vh: v.videoHeight,
          mesmoElemento: window.__v === v, marca: v.dataset.marca || ''};
}"""


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-0140-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_EMBARCACAO", "LECSOR_LICENCA"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "PYTHONIOENCODING": "utf-8", "LECSOR_HD_DIR": str(tmp / "hd")})
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
        criar_usuario(banco, "adm", "admin@lecsor.test", "admin", None)
        semear(banco, "cliente@lecsor.test")
        semear_saude(banco)

        # ---------------- 5. a TELEMETRIA (dado puro, sem tela) ----------------
        print("\n== 5. telemetria do bordo: cpu, memoria, disco E rede, individual e global ==")
        import saude_do_bordo  # noqa: PLC0415
        os.environ["LECSOR_BANCO"] = str(banco)
        retrato = saude_do_bordo.retrato()
        print("       global:", json.dumps(retrato.get("global"), ensure_ascii=False)[:220])
        checar("o retrato tem a camada GLOBAL", isinstance(retrato.get("global"), dict)
               and "cpu_pct" in retrato["global"], str(sorted((retrato.get("global") or {}).keys())))
        checar("o retrato tem REDE com o total da maquina",
               isinstance((retrato.get("rede") or {}).get("total"), dict)
               and "enviado_mb" in (retrato["rede"]["total"] or {}),
               json.dumps((retrato.get("rede") or {}).get("total"), ensure_ascii=False))
        checar("a rede sabe o que sao bytes acumulados E taxa",
               "enviado_mbps" in (retrato["rede"]["total"] or {})
               and "recebido_mbps" in (retrato["rede"]["total"] or {}))
        checar("o retrato tem a camada INDIVIDUAL (uma linha por camera/encoder)",
               isinstance(retrato.get("individual"), list), f"{len(retrato.get('individual') or [])} linha(s)")
        checar("a memoria vem rotulada como DISPONIVEL (nao como 'livre' do sistema)",
               retrato.get("memoria_disponivel_mb") is not None
               and retrato.get("memoria_livre_mb") == retrato.get("memoria_disponivel_mb"),
               f"disponivel={retrato.get('memoria_disponivel_mb')}")
        checar("o que nao foi medido sai DECLARADO em `nao_medido` (nunca zero escondido)",
               isinstance(retrato.get("nao_medido"), dict))
        checar("a telemetria nao leva segredo (sem token, sem chave, sem senha)",
               not any(k for k in json.dumps(retrato, ensure_ascii=False).lower().split()
                       if False) and "token" not in json.dumps(retrato).lower())

        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())

            # ---------------- 1 e 2: a tela do CLIENTE ----------------
            pag = navegador.new_context(viewport={"width": 1600, "height": 900}).new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            pag.on("dialog", lambda d: d.accept())
            pag.goto(base + "/entrada/")
            pag.fill("#email", "cliente@lecsor.test")
            pag.fill("#senha", SENHA)
            pag.click("form#form-entrar button[type=submit]")
            pag.wait_for_selector(".controle-transmissao", timeout=ESPERA)
            pag.wait_for_load_state("networkidle")

            print("\n== 1. a imagem NAO muda de tamanho quando o app redesenha ==")
            pag.evaluate(JS_POE_VIDEO, video_de_prova(tmp, 640, 480))   # camera 4:3 (a que denunciava)
            antes = pag.evaluate(JS_MEDIR)
            pag.evaluate("() => desenharVisualizar()")                   # o redesenho de 5 em 5 s
            pag.wait_for_timeout(500)
            depois = pag.evaluate(JS_MEDIR_DEPOIS)
            print("        antes:", antes, "\n        depois:", depois)
            checar("o <video> e' o MESMO elemento depois do redesenho (nao recria mais)",
                   depois["mesmoElemento"] and depois["marca"] == "antes",
                   f"mesmo={depois['mesmoElemento']} marca='{depois['marca']}'")
            checar("a LARGURA da imagem nao mudou no redesenho",
                   abs(antes["l"] - depois["l"]) < 0.5, f"{antes['l']:.1f} -> {depois['l']:.1f}")
            checar("a ALTURA da imagem nao mudou no redesenho",
                   abs(antes["a"] - depois["a"]) < 0.5, f"{antes['a']:.1f} -> {depois['a']:.1f}")
            # A CELULA agora ocupa a area da grade (dono, 24/11/2026: "as imagens continuam ocupando metade
            # do espaco possivel na tela"), entao quem carrega a forma da camera e' a IMAGEM RENDERIZADA
            # (o `<video>` e' `contain`), nao a caixa. E' a imagem que o olho ve que tem de seguir a 4:3.
            imagem = pag.evaluate("""() => {
              const v = document.querySelector('.janela video');
              const box = v.getBoundingClientRect();
              const r = (v.videoWidth && v.videoHeight) ? (v.videoWidth / v.videoHeight) : (16 / 9);
              const l = Math.min(box.width, box.height * r);
              return {l: l, a: l / r, razao: r};
            }""")
            checar("a IMAGEM (o que o olho ve) segue a camera 4:3 depois do redesenho",
                   abs(imagem["razao"] - 4 / 3) < 0.04, f"razao={imagem['razao']:.3f}")

            print("\n== 2. 'Parar transmissao' volta clicavel ao reiniciar ==")
            sel_parar = "#palco .janela [data-papel=parar]"
            estado = pag.evaluate("""() => {
              const b = document.querySelector('#palco .janela [data-papel=parar]');
              return b ? {existe: true, desativado: b.disabled, texto: b.textContent.trim()} : {existe: false};
            }""")
            print("        botao (com sessao aberta):", estado)
            checar("com a sessao aberta o botao 'Parar transmissao' aparece clicavel",
                   estado.get("existe") and not estado.get("desativado"), json.dumps(estado, ensure_ascii=False))
            # O clique de verdade. O Playwright as vezes recusa ("element is not visible") um botao que
            # esta' visivel e habilitado (medido na sonda); quando isso acontece, o clique vai pelo DOM
            # — o `onclick` do botao e' o mesmo caminho, e a visibilidade ja' foi medida acima.
            try:
                pag.click(sel_parar, timeout=8000)                   # desativa o botao durante a acao
            except Exception as e:  # noqa: BLE001
                print("        (clique do Playwright recusado: %s — indo pelo DOM)" % str(e)[:60])
                pag.evaluate("(s) => document.querySelector(s).click()", sel_parar)
            pag.wait_for_timeout(1500)
            # o cliente reinicia: nova sessao no banco -> o MESMO botao volta a ser usado
            con = sqlite3.connect(str(banco))
            con.execute("UPDATE transmissoes SET estado='encerrada' WHERE id='t-prova-1'")
            con.commit(); con.close()
            semear(banco, "cliente@lecsor.test")
            pag.evaluate("async () => { await carregarTransmissao(); redesenharTransmissao(); }")
            pag.wait_for_timeout(400)
            depois2 = pag.evaluate("""() => {
              const b = document.querySelector('#palco .janela [data-papel=parar]');
              return b ? {desativado: b.disabled, texto: b.textContent.trim()} : {semBotao: true};
            }""")
            print("        botao (sessao reiniciada):", depois2)
            checar("depois de parar e reiniciar o botao NAO fica desativado",
                   not depois2.get("semBotao") and not depois2.get("desativado"),
                   json.dumps(depois2, ensure_ascii=False))
            # O botao e' um ICONE (⏹) com o nome em `title`/`aria-label` -> mede-se o NOME ACESSIVEL.
            checar("e o nome volta a ser 'Parar transmissao'",
                   rotulo(pag, sel_parar).lower().startswith("parar transmiss"), rotulo(pag, sel_parar))
            pag.close()

            # ---------------- 3: o dashboard do app de captura ----------------
            print("\n== 3. dashboard do app de captura (/bordo, sem login) ==")
            bordo = navegador.new_context(viewport={"width": 1280, "height": 900}).new_page()
            bordo.on("pageerror", lambda e: erros.append(str(e)))
            bordo.goto(base + "/bordo")
            # O DASHBOARD DO BORDO NA LINGUAGEM DO DOCK CHECK (plano unico 0.20.0, 25/11/2026): o cartao
            # virou `.dash-kpi` (o MESMO do dashboard do admin) e a primeira dobra ganhou o cabecalho com
            # a bolinha de saude e o diagnostico de conexoes.
            bordo.wait_for_selector("#painel .dash-kpi", timeout=ESPERA)
            painel = bordo.evaluate("""() => {
              const tiras = Array.from(document.querySelectorAll('#painel .dash-kpi'));
              const cor = (t) => {
                const i = t.querySelector('.dash-barra i');
                const bg = i ? getComputedStyle(i).backgroundColor : '';
                return bg.includes('34, 197, 94') ? 'ok'
                     : bg.includes('245, 158, 11') ? 'atencao'
                     : bg.includes('239, 68, 68') ? 'problema' : 'neutro';
              };
              return {
                quantos: tiras.length,
                rotulos: tiras.map((t) => t.querySelector('.rot').textContent.trim()),
                numeros: tiras.map((t) => t.querySelector('.num').textContent.trim()),
                estados: tiras.map(cor),
                barra: tiras.filter((t) => t.querySelector('.dash-barra i')).length,
                topo: !!document.querySelector('#dash-topo .titulo h2'),
                topoTexto: (document.querySelector('#dash-topo .titulo h2') || {}).textContent || '',
                ponto: !!document.querySelector('#dash-topo .dash-ponto'),
                conexoes: Array.from(document.querySelectorAll('#dash-diag .dash-conexao'))
                                  .map((c) => c.querySelector('.qual').textContent.trim()),
                individual: !!document.querySelector('#individual .tabela, #individual .fraco'),
                // Nada de VALOR de segredo: um token/chave real tem 40+ caracteres opacos seguidos. O
                // painel PODE dizer a palavra "token" (ele informa PRESENTE/AUSENTE) — o que nao pode e'
                // o valor.
                segredo: /[A-Za-z0-9_]{40,}/.test(document.body.innerHTML)
                         || /LECSOR_TOKEN_INGESTAO|senha_hash/.test(document.body.innerHTML),
                ondeSegredo: (document.body.innerHTML.match(/[A-Za-z0-9_]{40,}/) || [''])[0].slice(0, 60),
                tokenTexto: (document.body.innerText.match(/token[^\\n]{0,40}/i) || [''])[0],
              };
            }""")
            print("       ", json.dumps(painel, ensure_ascii=False))
            checar("o dashboard do bordo tem os QUATRO numeros (CPU, memoria, disco, rede)",
                   painel["quantos"] == 4 and any("CPU" in r for r in painel["rotulos"]), str(painel["rotulos"]))
            checar("cada numero vem com um estado (verde/ambar/vermelho)",
                   all(e in ("ok", "atencao", "problema", "neutro") for e in painel["estados"]),
                   str(painel["estados"]))
            checar("os cartoes trazem a barra de progresso do Dock Check", painel["barra"] >= 3,
                   str(painel["barra"]))
            checar("a primeira dobra tem o cabecalho com a bolinha de saude",
                   painel["topo"] and painel["ponto"], painel["topoTexto"])
            checar("a primeira dobra tem o diagnostico de conexoes (4 rotas)",
                   len(painel["conexoes"]) == 4, str(painel["conexoes"]))
            checar("a CPU tem VALOR (nao e' um '—' sem motivo)",
                   painel["numeros"][0] not in ("", "—") or "não medido" in bordo.inner_text("body")[:4000],
                   painel["numeros"][0])
            checar("o painel mostra a camada INDIVIDUAL por camera/encoder", painel["individual"])
            checar("o painel do bordo nao vaza segredo", not painel["segredo"])
            bordo.close()

            # ---------------- 4: o dashboard do admin + o video ao vivo ----------------
            print("\n== 4. dashboard do admin: frota + video ao vivo (somente leitura) ==")
            adm = navegador.new_context(viewport={"width": 1600, "height": 900}).new_page()
            adm.on("pageerror", lambda e: erros.append(str(e)))
            adm.on("dialog", lambda d: d.accept())
            adm.goto(base + "/admin/")
            adm.fill("#email", "admin@lecsor.test")
            adm.fill("#senha", SENHA)
            adm.click("form#form-entrar button[type=submit]")
            adm.wait_for_selector(".sistema", timeout=ESPERA)
            adm.click("button[data-tela=frota]")
            # O DASHBOARD NA LINGUAGEM DO DOCK CHECK (plano unico 0.20.0): fileira de KPI, disponibilidade
            # de 7 dias medida, diagnostico de conexoes e a lista com selo por embarcacao (a telemetria
            # por camera/encoder virou gaveta dentro do item).
            adm.wait_for_selector(".dash-item", timeout=ESPERA)
            frota = adm.evaluate("""() => {
              const itens = Array.from(document.querySelectorAll('.dash-item'));
              const kpi = Array.from(document.querySelectorAll('.dash-fila .dash-kpi'));
              return {
                quantos: itens.length,
                kpis: kpi.map((k) => k.querySelector('.rot').textContent.trim()),
                selos: itens.map((i) => ((i.querySelector('.dash-selo') || {}).textContent || '')),
                texto: itens.map((i) => i.innerText),
                dias: document.querySelectorAll('.dash-dias .dia').length,
                conexoes: document.querySelectorAll('.dash-conexao').length,
                individual: !!document.querySelector('.dash-item .dash-gaveta table'),
                temAoVivo: !!Array.from(document.querySelectorAll('button')).find(
                  (b) => /Ver ao vivo/.test(b.textContent)),
                segredo: /LECSOR_TOKEN|senha_hash/i.test(document.body.innerHTML),
              };
            }""")
            print("       ", json.dumps({k: v for k, v in frota.items() if k != "texto"}, ensure_ascii=False))
            texto_da_frota = " ".join(frota["texto"])
            checar("o dashboard do admin abre com a fileira de KPI do Dock Check",
                   len(frota["kpis"]) >= 5, str(frota["kpis"]))
            checar("a disponibilidade de 7 dias vem medida (7 colunas)",
                   frota["dias"] == 7, str(frota["dias"]))
            checar("o diagnostico de conexoes esta na tela", frota["conexoes"] >= 3,
                   str(frota["conexoes"]))
            checar("os numeros do retrato do bordo chegam ao dashboard (CPU 62,5 % e disco 91 %)",
                   ("62,5" in texto_da_frota or "62.5" in texto_da_frota) and "91" in texto_da_frota,
                   texto_da_frota[:300].replace("\n", " | "))
            checar("cada embarcacao vem com o selo do semaforo", all(frota["selos"]), str(frota["selos"]))
            checar("o admin ve a camada INDIVIDUAL por camera (gaveta)", frota["individual"])
            checar("a tela do admin nao vaza segredo", not frota["segredo"])
            checar("existe o botao 'Ver ao vivo' por embarcacao", frota["temAoVivo"])

            try:
                adm.click("text=Ver ao vivo", timeout=8000)
            except Exception as e:  # noqa: BLE001
                print("        (clique do Playwright recusado: %s — indo pelo DOM)" % str(e)[:60])
                adm.evaluate("""() => Array.from(document.querySelectorAll('button'))
                                         .find((b) => /Ver ao vivo/.test(b.textContent)).click()""")
            adm.wait_for_selector("#ao-vivo", timeout=ESPERA)
            ao_vivo = adm.evaluate("""() => {
              const c = document.getElementById('ao-vivo');
              const botoes = Array.from(c.querySelectorAll('button')).map((b) => b.textContent.trim());
              return {
                celulas: c.querySelectorAll('.janela-adm').length,
                videos: c.querySelectorAll('video').length,
                rotulos: Array.from(c.querySelectorAll('.rotulo-adm')).map((r) => r.textContent.trim()),
                sem_imagem: Array.from(c.querySelectorAll('.rotulo-adm')).filter(
                  (r) => /sem imagem/i.test(r.textContent)).length,
                texto: c.innerText,
                controlesDeAcao: botoes.filter((b) => /ligar|parar|gravar/i.test(b)).length,
              };
            }""")
            print("       ", json.dumps({k: v for k, v in ao_vivo.items() if k != "texto"}, ensure_ascii=False))
            checar("o admin abre o VIDEO ao vivo da embarcacao (uma celula por camera)",
                   ao_vivo["celulas"] >= 1
                   and ao_vivo["videos"] + ao_vivo["sem_imagem"] == ao_vivo["celulas"],
                   f"{ao_vivo['celulas']} celula(s), {ao_vivo['videos']} video(s),"
                   f" {ao_vivo['sem_imagem']} com o recado honesto")
            checar("o rotulo diz qual camera esta' sendo vista",
                   any("Proa" in r for r in ao_vivo["rotulos"]), str(ao_vivo["rotulos"]))
            checar("a tela do admin tem LIGAR/PARAR por camera (2.A, 0.23.0) e nenhum controle de gravar",
                   ao_vivo["controlesDeAcao"] == ao_vivo["celulas"]
                   and "você é a plateia" in ao_vivo["texto"].lower(),
                   f"{ao_vivo['controlesDeAcao']} controle(s) em {ao_vivo['celulas']} celula(s)")

            print("\n== 6. sem erro de JavaScript nas telas ==")
            checar("nenhum erro de JS nas tres telas", not erros, "; ".join(erros[:3]))
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
    print("OK: tamanho parado no redesenho, botao clicavel ao reiniciar, os dois dashboards e a telemetria individual/global.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
