#!/usr/bin/env python3
"""Prova, num navegador de verdade, o caminho de envio de video de teste:

1. no portal da bancada (`/`), o operador envia um ARQUIVO e cola um LINK;
2. a tela mostra a medicao (entrada, saida, corte, fps, tempo no ar) vinda do banco;
3. o fluxo enviado aparece na grade do CLIENTE (`/app`) e o video toca;
4. a deteccao de IA velha NAO fica desenhada (a caixa congelada sai da tela);
5. o que o navegador recebe nao tem endereco interno nem credencial.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE = os.environ.get("LECSOR_BASE", "http://127.0.0.1:8765")
SENHA = os.environ.get("LECSOR_SENHA_DEMO", "")
CLIPE = RAIZ / "analytics" / "midia" / "people-detection.mp4"
falhas: list[str] = []


def checar(cond, texto):
    print(("  ok   " if cond else "  FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def http(caminho: str, dados=None, metodo=None, cabecalhos=None):
    r = urllib.request.Request(BASE + caminho, data=dados,
                               headers=cabecalhos or {"Content-Type": "application/json"},
                               method=metodo or ("POST" if dados else "GET"))
    return json.loads(urllib.request.urlopen(r, timeout=20).read() or "{}")


def limpar_testes():
    """Limpa os envios de teste de execucoes anteriores (mantem a bancada apresentavel)."""
    try:
        for i in http("/api/ingestoes")["ingestoes"]:
            if "teste" in (i["rotulo"] or "").lower():
                http("/api/ingestao/parar", json.dumps({"id": i["id"], "remover": True}).encode())
    except Exception as e:
        print("  aviso: nao consegui limpar envios antigos:", e)


def main() -> int:
    from playwright.sync_api import sync_playwright
    limpar_testes()
    with sync_playwright() as pw:
        try:
            nav = pw.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
        except Exception:
            nav = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])

        # --- 1) portal da bancada: envio de ARQUIVO pela tela
        ctx = nav.new_context(viewport={"width": 1500, "height": 1000})
        pg = ctx.new_page()
        recebido: list[str] = []
        pg.on("request", lambda r: recebido.append(r.url))
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_selector("#solta")
        pg.fill("#rotulo", "Envio pela tela (teste)")
        pg.select_option("#bitrate", "auto")   # alvo automatico (metade da entrada)
        pg.set_input_files("#arquivo", str(CLIPE))
        pg.click("#btn-enviar")
        pg.wait_for_function("() => document.getElementById('msg').textContent.includes('no ar')", timeout=60000)
        print("  ok   envio por arquivo aceito na tela")
        pg.screenshot(path=str(RAIZ / "ground" / "print-portal-envio.png"), full_page=True)

        # --- 2) portal: link http(s)
        pg.click("#aba-link")
        pg.fill("#url", "http://127.0.0.1:8123/people-detection.mp4")
        pg.fill("#rotulo", "Envio por link (teste)")
        pg.click("#btn-enviar")
        pg.wait_for_function("() => document.getElementById('msg').textContent.includes('no ar')", timeout=60000)
        print("  ok   envio por link aceito na tela")

        # --- 2b) o encode COMPRIME de verdade: corte positivo no fluxo enviado
        corte = None
        for _ in range(20):
            d0 = http("/api/ingestoes")
            novo = [i for i in d0["ingestoes"] if "teste" in (i["rotulo"] or "").lower() and i["tipo"] == "arquivo"]
            if novo and novo[0].get("corte_pct") is not None and novo[0]["bitrate_saida_kbps"]:
                corte = novo[0]
                if (corte.get("duracao_s") or 0) >= 12:
                    break
            time.sleep(3)
        if corte:
            print("    medicao: entrada %s kbps -> saida %s kbps (corte %s%%) fps %s" % (
                corte["bitrate_entrada_kbps"], corte["bitrate_saida_kbps"], corte["corte_pct"], corte["fps"]))
            checar((corte["corte_pct"] or 0) > 0, "o encode reduz banda de verdade (corte positivo) com alvo automatico")
        else:
            checar(False, "nao obtive medicao de corte do envio")

        # --- 3) a medicao do banco aparece na tabela da tela
        for _ in range(20):
            texto = pg.inner_text("#t-envios")
            if "Mbps" in texto and "no_ar" in texto:
                break
            time.sleep(3)
        print("    tabela de envios:\n" + "\n".join("      " + l.strip() for l in texto.splitlines()[:12] if l.strip()))
        checar("Mbps" in texto, "a tabela mostra bitrate de entrada/saida (medido, nao digitado)")
        checar("no_ar" in texto, "o envio aparece como no ar")
        checar("fps" in texto.lower(), "a tabela mostra fps")
        pg.close(); ctx.close()

        # --- 4) o fluxo enviado aparece na grade do cliente e toca
        ctx2 = nav.new_context(viewport={"width": 1500, "height": 950})
        pc = ctx2.new_page()
        recebido2: list[str] = []
        pc.on("request", lambda r: recebido2.append(r.url))
        pc.goto(BASE + "/app", wait_until="domcontentloaded")
        pc.fill("#email", "cliente@armador-demo.test"); pc.fill("#senha", SENHA)
        pc.click("#form-entrar button")
        pc.wait_for_selector(".grade-vms .janela", timeout=30000)
        # descobre o fluxo enviado pela tela (o mais novo com 'teste' no rotulo)
        d = http("/api/ingestoes")
        alvos = [i["fluxo_id"] for i in d["ingestoes"] if "teste" in (i["rotulo"] or "").lower()]
        checar(len(alvos) >= 2, "a API registrou os dois envios feitos pela tela")
        enviado = alvos[0]
        print("    fluxo enviado:", enviado)
        # o cliente precisa enxergar a camera enviada (mesma embarcacao demo)
        visivel = pc.wait_for_function(
            f"() => (S.cameras || []).some(c => c.id === {enviado!r} && c.no_ar)",
            timeout=30000)
        checar(bool(visivel), "o cliente enxerga o fluxo enviado como camera no ar")
        # abre a pagina do palco que contem essa camera e espera o relogio do video andar
        tocando = False
        for _ in range(14):
            pc.evaluate(f"""() => {{
              const total = (typeof paginas === 'function') ? paginas() : 1;
              for (let p = 1; p <= total; p++) {{
                if (typeof irPara === 'function') irPara(p);
                if (document.querySelector('.janela[data-cam="{enviado}"]')) return true;
              }}
              return false;
            }}""")
            time.sleep(2)
            tocando = pc.evaluate(f"""() => {{
              const j = document.querySelector('.janela[data-cam="{enviado}"]');
              const v = j && j.querySelector('video');
              return !!(v && v.readyState >= 2 && v.currentTime > 0.3);
            }}""")
            if tocando:
                break
        checar(tocando, "o video enviado esta tocando no navegador do cliente")
        pc.screenshot(path=str(RAIZ / "ground" / "print-cliente-envio.png"), full_page=False)

        # --- 5) caixa de IA velha nao fica desenhada
        velha = pc.evaluate("""(cam) => {
          if (typeof desenharCaixas !== 'function') return null;
          if (!document.getElementById('caixas-' + cam)) return {semPalco: true};
          S.ia = true;
          S.agentesPorCamera[cam] = { caixas: [{caixa:[0.8,0.1,0.95,0.5], classe:'pessoa', confianca:0.5}], caixas_idade: 9,
                                      zonas: [], linhas: [] };
          S.analises.contagens = [{camera_id: cam, entrou: 1, saiu: 0}];
          desenharCaixas(cam);
          const velho = document.querySelectorAll('#caixas-' + cam + ' .caixa').length;
          const seloVelho = (document.querySelector('[data-cam="' + cam + '"] .selo-ia') || {}).textContent || '';
          S.agentesPorCamera[cam].caixas_idade = 0;
          desenharCaixas(cam);
          const novo = document.querySelectorAll('#caixas-' + cam + ' .caixa').length;
          return {velho, novo, selo: seloVelho};
        }""", enviado)
        if velha is None or velha.get("semPalco"):
            print("  aviso: o palco do cliente não tem a janela da IA para este fluxo — pulando a checagem de caixa")
        else:
            checar(velha["velho"] == 0, "deteccao de 9 s atras NAO desenha caixa (fim da caixa congelada)")
            checar(velha["novo"] == 1, "deteccao fresca desenha a caixa")
            checar("sem detec" in velha["selo"], "o selo explica que a leitura envelheceu: " + velha["selo"][:70])

        # --- 5b) app do admin: o formulario de envio nao se apaga enquanto o usuario digita
        # (o redesenho periodico da tela apagava link e rotulo e parecia que "o app voltava ao estado anterior")
        ctx3 = nav.new_context(viewport={"width": 1400, "height": 900})
        pa = ctx3.new_page()
        pa.goto(BASE + "/admin", wait_until="domcontentloaded")
        pa.fill("#email", "admin@lecsor.test"); pa.fill("#senha", SENHA)
        pa.click("#form-entrar button")
        pa.wait_for_selector("#sistema:not(.oculto)", timeout=15000)
        item = pa.query_selector("li.item[data-tela='envios'], [data-tela='envios']")
        if item:
            item.click()
        else:
            pa.evaluate("(() => { const b=[...document.querySelectorAll('button,a,li')].find(x=>/Enviar v[ií]deo/i.test(x.textContent)); if(b) b.click(); })()")
        pa.wait_for_selector("#env-modo", timeout=15000)
        pa.select_option("#env-modo", "url")
        pa.fill("#env-url", "https://www.youtube.com/watch?v=aqz-KE-bpKQ")
        pa.click("#env-rotulo")
        pa.type("#env-rotulo", "Clipe do YouTube (teste)", delay=400)
        pa.wait_for_timeout(18000)   # passa por pelo menos um redesenho automatico da tela
        modo = pa.input_value("#env-modo"); url = pa.input_value("#env-url"); rot = pa.input_value("#env-rotulo")
        print("    depois de 18 s: modo=%s url=%s rotulo=%s" % (modo, url[:38], rot))
        checar(modo == "url", "o seletor 'colar um link' continua escolhido depois do redesenho")
        checar(url.startswith("https://www.youtube.com"), "o link colado continua no campo")
        checar(rot == "Clipe do YouTube (teste)", "o rotulo digitado nao se perde")
        pa.close(); ctx3.close()

        # --- 5c) app do admin: UMA estrutura só — comprimir, medir e publicar
        # o dono pediu medições claras no mesmo painel: tempo da compressão, tamanho de entrada e
        # saída, economia de banda e qualidade; e a coluna "no ar" precisa dizer algo
        ctx4 = nav.new_context(viewport={"width": 1600, "height": 1000})
        pb = ctx4.new_page()
        pb.goto(BASE + "/admin", wait_until="domcontentloaded")
        pb.fill("#email", "admin@lecsor.test"); pb.fill("#senha", SENHA)
        pb.click("#form-entrar button")
        pb.wait_for_selector("#sistema:not(.oculto)", timeout=15000)
        pb.evaluate("(() => { const b=[...document.querySelectorAll('button,a,li')].find(x=>/Enviar v[ií]deo/i.test(x.textContent)); if(b) b.click(); })()")
        pb.wait_for_selector("#env-qualidade", timeout=15000)
        pb.fill("#env-rotulo", "Compressao pela tela (teste)")
        pb.select_option("#env-qualidade", "crf34")     # compressão máxima: encode rápido
        pb.set_input_files("#env-arquivo", str(CLIPE))
        pb.evaluate("(() => { const b=[...document.querySelectorAll('button')].find(x=>/Comprimir e medir/i.test(x.textContent)); b.click(); })()")
        texto_prog = ""
        for _ in range(60):
            pb.wait_for_timeout(2000)
            try:
                texto_prog = pb.inner_text("#env-progresso") or ""
            except Exception:
                texto_prog = ""
            if "comprimido" in texto_prog or "falhou" in texto_prog or "PISO" in texto_prog:
                break
        print("    progresso:", texto_prog[:200])
        checar("comprimido" in texto_prog, "a tela diz quanto o vídeo foi comprimido (MB → MB, %, qualidade, tempo)")
        checar("qualidade" in texto_prog, "a tela informa a qualidade que sobrou (SSIM)")
        # a tabela precisa trazer as colunas que o dono pediu, com número
        pb.wait_for_timeout(4000)
        cabecalho = pb.inner_text("#tela, main, body")
        for coluna in ["Entrada (original)", "Saída (comprimido)", "Compressão", "Tempo da compressão", "Qualidade"]:
            checar(coluna in cabecalho, f"a tabela tem a coluna \"{coluna}\"")
        checar("MB" in cabecalho and "kbps" in cabecalho, "a tabela mostra o tamanho real e o bitrate de entrada e saída")
        checar("s (" in cabecalho or " s " in cabecalho, "a tabela mostra em quanto tempo a compressão foi feita")
        checar("alvo" not in cabecalho.lower(), "a coluna confusa \"alvo\" saiu da tela")
        checar("PISO" in cabecalho and "73" in cabecalho and "0,9733" in cabecalho and "0,9713" in cabecalho,
               "a tela declara o piso: 73% de compressão e qualidade 0,9733 nominal (aceita 0,9713 com margem)")
        checar("✓" in cabecalho, "a linha mostra que a compressão bateu o piso (✓)")
        # publicar a última compressão: etapas 2 e 3 saem do mesmo painel
        pb.evaluate("(() => { const b=[...document.querySelectorAll('button')].find(x=>/Publicar no ar/i.test(x.textContent)); b.click(); })()")
        for _ in range(30):
            pb.wait_for_timeout(1000)
            if "no ar como" in (pb.inner_text("#env-progresso") or "") or "falhou" in (pb.inner_text("#env-progresso") or ""):
                break
        estado = pb.inner_text("#env-progresso") or ""
        print("    publicar:", estado[:160])
        checar("no ar como" in estado, "o mesmo painel publica a compressão no ar (etapas 2 e 3 em sequência)")
        pb.screenshot(path=str(RAIZ / "ground" / "print-admin-envios-final.png"), full_page=True)
        pb.close(); ctx4.close()

        # --- 6) nada de endereco interno nem credencial no que o navegador recebe
        proibido = re.compile(r"rtsp://|:8554|:8890|:9997|:8889|localhost|password|credencial|senha")
        vazou = [u for u in recebido + recebido2 if proibido.search(u)]
        checar(not vazou, "nenhum endereco interno/credencial nas requisicoes do navegador")
        if vazou:
            print("      vazou:", vazou[:5])
        nav.close()

    # --- 9) fontes sem câmera de embarcação: webcam do notebook e fonte sintética
    import urllib.error

    def _pedir(caminho, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(BASE + caminho, data=dados,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if dados else "GET")
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    st, disp = _pedir("/api/dispositivos")
    checar(st == 200 and isinstance(disp.get("video"), list),
           "a operação lista os dispositivos de captura ({} webcam(s): {})".format(
               len(disp.get("video") or []), ", ".join(disp.get("video") or []) or "nenhuma"))
    st, cap = _pedir("/api/ingestao/capturar", {"tipo": "sintetica", "segundos": 4, "fps": 30,
                                                "rotulo": "teste sintetico e2e"})
    checar(st == 201 and cap.get("mb") and cap.get("resolucao"),
           "capturei um clipe de teste sem câmera nenhuma ({} · {} fps · {} MB)".format(
               cap.get("resolucao"), cap.get("fps"), cap.get("mb")))
    st, comp = _pedir("/api/ingestao/comprimir", {"arquivo": cap.get("nome"), "rotulo": "teste sintetico e2e",
                                                  "qualidade": "auto", "fps": "30"})
    checar(st == 201 and comp.get("corte_pct"), "comprimi o clipe capturado ({}% menos banda · SSIM {})".format(
        comp.get("corte_pct"), comp.get("ssim")))
    checar(isinstance(comp.get("id"), int),
           "a compressão do clipe ficou gravada no banco (id {}) com veredito dos pisos".format(comp.get("id")))
    st, pub = _pedir("/api/compressao/publicar", {"id": comp.get("id")})
    checar(st == 201 and pub.get("fluxo_id"), "publiquei o clipe capturado no ar em SRT ({})".format(pub.get("fluxo_id")))
    if st == 201:
        _pedir("/api/ingestao/parar", {"id": pub.get("id"), "remover": True})
    st, err = _pedir("/api/ingestao/capturar", {"tipo": "televisao"})
    checar(st == 422, "captura de uma fonte desconhecida é recusada com 422")

    # --- 8) produção (cards de 30 dias) e link/latência em tempo real
    sys.path.insert(0, str(RAIZ / "ground"))
    import producao as prod
    f1 = prod.fechar_minutos()
    f2 = prod.fechar_minutos()
    checar(f1["minutos_fechados"] >= 0 and f2["minutos_fechados"] == f1["minutos_fechados"],
           "fechar_minutos é idempotente (rodar duas vezes não duplica o histórico)")
    checar(f1["retencao_dias"] >= 1, f"retenção do histórico configurada em {f1['retencao_dias']} dias")
    res = prod.resumo_producao(dias=30)
    campos = {"embarcacao", "camera", "compressao_medio_pct", "banda_utilizada_mbps",
              "banda_economizada_mbps", "horas_streaming", "disponibilidade_pct", "estado"}
    checar(bool(res["cards"]) and campos <= set(res["cards"][0]),
           f"o resumo de produção devolve os campos dos cards ({len(res['cards'])} câmera(s) com histórico)")
    checar(all(c["estado"] in ("enviando", "parado") for c in res["cards"]),
           "cada card diz se a câmera está enviando ou parada")
    checar(res["dias"] == 30 and "disponibilidade_pct" in res["cards"][0],
           "a janela padrão é de 30 dias e traz disponibilidade (%)")
    # disponibilidade proporcional ao tempo que o sistema já roda (não aos 30 dias cheios)
    checar(res["janela_efetiva_min"] < 30 * 24 * 60,
           f"a disponibilidade usa a janela efetiva ({res['janela_efetiva_min']} min desde {res['primeiro_minuto']}), não 30 dias cheios")
    checar(all(c["minutos_no_ar"] <= res["janela_efetiva_min"] + 1 for c in res["cards"]),
           "nenhum card conta mais minutos no ar do que a janela efetiva")
    com_comp = [c for c in res["cards"] if c["compressao_medio_pct"] and c["compressao_medio_pct"] > 0]
    checar(com_comp and all(c["banda_economizada_mbps"] is None or c["banda_economizada_mbps"] > 0 for c in com_comp),
           "banda economizada não aparece como 0 quando há compressão (usa a entrada original)")
    lk = prod.link_srt()
    checar("disponivel" in lk, "o link é lido do SRT (RTT, capacidade, atraso do buffer, perda)")
    if lk.get("disponivel"):
        checar({"rtt_ms", "capacidade_link_mbps", "atraso_buffer_ms", "perda_recebida_pct"} <= set(lk),
               "o link traz RTT, capacidade, atraso do buffer e perda")
    net = prod.latencia_internet()
    checar("disponivel" in net or "motivo" in net,
           "a latência de internet local é medida (ping), com motivo quando não há resposta")
    atraso = prod.atraso_stream("comp-01")
    checar("buffer_srt_ms" in atraso and "ponta_a_ponta" in atraso,
           "o atraso do streaming junta o buffer SRT e a última medição ponta a ponta")

    # --- 7) piso com margem, metricas de tempo real e endereco da camera so na operacao
    sys.path.insert(0, str(RAIZ / "ground"))
    import etapas as et
    checar(abs(et.PISO_QUALIDADE_ACEITO - 0.9713) < 1e-9,
           "o piso de qualidade aceita 0,9713 (0,9733 nominal com margem de 0,002)")
    ok_margem, _ = et.passa_pisos(78.11, 0.9720)
    checar(ok_margem, "78,11% de compressão com 0,9720 passa: o dono manda tratar o valor como mínimo com margem")
    ok_baixo, _ = et.passa_pisos(60.0, 0.9713)
    checar(not ok_baixo, "compressão abaixo de 73% continua reprovada (a banda é piso firme)")
    ok_qual, _ = et.passa_pisos(75.0, 0.9700)
    checar(not ok_qual, "qualidade abaixo da margem (0,9700) é reprovada")

    # tempo real: o painel do admin recebe os numeros do streaming AGORA
    tg = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            bb = pw.chromium.launch(channel="chrome")
            ctx = bb.new_context()
            pg = ctx.new_page()
            pg.goto(BASE + "/admin")
            pg.fill("#email", "admin@lecsor.test"); pg.fill("#senha", SENHA)
            pg.click("#form-entrar button")
            pg.wait_for_selector("#sistema:not(.oculto)", timeout=15000)
            corpo = pg.evaluate("(async () => { const r = await fetch('/api/metricas'); return r.status + '|' + JSON.stringify(await r.json()); })()")
            checar(corpo.startswith("200|"), "a operação tem /api/metricas (tempo real) respondendo")
            dados = json.loads(corpo.split("|", 1)[1])
            checar("total" in dados and "fluxos" in dados and {"entrada_mbps", "saida_mbps", "economia_mbps", "compressao_pct"} <= set(dados["total"]),
                   "as métricas trazem entrada, saída, compressão e banda economizada")
            pg.click("button[data-tela='producao']")
            pg.wait_for_timeout(4000)
            prod_txt = pg.inner_text("#prod-resumo")
            checar("câmera(s) com histórico" in prod_txt or "camera(s) com histórico" in prod_txt.lower(),
                   "a tela Produção mostra o resumo do período")
            checar(pg.evaluate("(() => document.querySelector('#prod-dias').options.length)()") >= 4,
                   "a tela Produção tem filtro de período")
            pg.screenshot(path=str(RAIZ / "ground" / "print-admin-producao.png"), full_page=True)
            pg.click("button[data-tela='tempo']")
            pg.wait_for_timeout(4000)
            tela = pg.inner_text("#tempo-resumo")
            checar("economia" in tela and "compressão agora" in tela,
                   "a tela Tempo real mostra compressão agora, banda consumida e economizada")
            checar("internet local" in tela and "atraso do buffer" in tela,
                   "a tela Tempo real mostra a latência da internet local e o atraso do buffer SRT")
            pg.screenshot(path=str(RAIZ / "ground" / "print-admin-tempo-real.png"), full_page=True)
            # cadastra a camera com IP e porta e confere o que o cliente recebe
            pg.click("button[data-tela='cameras']")
            pg.wait_for_selector("#k-ip", timeout=15000)
            pg.fill("#k-rot", "Câmera de teste (endereço)"); pg.fill("#k-fluxo", "cam-teste-ip")
            pg.fill("#k-ip", "10.99.0.7"); pg.fill("#k-porta", "555")
            pg.evaluate("(() => { const b=[...document.querySelectorAll('button')].find(x=>/Cadastrar câmera/i.test(x.textContent)); b.click(); })()")
            pg.wait_for_timeout(3000)
            det = pg.evaluate("(async () => { const r = await fetch('/api/cameras/detalhe'); const j = await r.json(); return JSON.stringify(j.cameras.filter(c=>c.ip)); })()")
            checar("10.99.0.7" in det and "555" in det, "a operação vê o IP e a porta da câmera")
            checar("$SENHA" in det and "rtsp://" in det, "a operação vê como o agente pega a câmera, com a senha como variável (não o valor)")
            ctx.close()
            # cliente: a lista de cameras NAO pode trazer endereco
            ctx2 = bb.new_context(); pc = ctx2.new_page()
            pc.goto(BASE + "/app")
            pc.fill("#email", "cliente@armador-demo.test"); pc.fill("#senha", SENHA)
            pc.click("#form-entrar button")
            pc.wait_for_selector("#grade, #sistema", timeout=15000)
            vista = pc.evaluate("(async () => { const r = await fetch('/api/cameras'); return JSON.stringify(await r.json()); })()")
            checar("10.99.0.7" not in vista and "rtsp" not in vista and "555" not in vista,
                   "o app do cliente nunca recebe o endereço da câmera")
            ctx2.close(); bb.close()
    except Exception as e:
        checar(False, f"tempo real / endereço da câmera: falhou ({type(e).__name__}: {e})")

    limpar_testes()   # nao deixa os envios do teste poluindo a grade do cliente
    print(("\nTUDO OK" if not falhas else f"\n{len(falhas)} FALHA(S): " + "; ".join(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
