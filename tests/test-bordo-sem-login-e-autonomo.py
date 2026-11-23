#!/usr/bin/env python3
"""PC DE CAPTURA AUTONOMO — sem login, com painel proprio e publicando sozinho.

Por que este teste existe (dono, 23/11/2026): *"inseri a chave de acesso no app no computador de captura,
depois me pede email e senha, mas não aceita nenhum que já tenho. após o reconhecimento da licença não
deveria precisar fazer mais nada no app de captura, ele já deveria fazer a varredura e enviar as
informações"* — e depois: *"no pc de captura ninguém precisa abrir nada, tudo deve ser feito no admin e
cliente, o app de captura deve ser autônomo, faz as varreduras locais e fica verificando as flags de terra
e enviando as respostas e fazendo as atuações"*.

O que era: depois da chave o app mandava a pessoa para o LOGIN (`/entrada`, encaminhado ao lado terra) e
o login do servidor LOCAL desta maquina so' aceita quem esta' no cadastro dela
(`ground/api.py` -> "esta conta nao esta cadastrada nesta instalacao") — dava "não aceita nenhum que já
tenho". O que passou a ser: a entrada da maquina de captura e' o PAINEL DO BORDO (`/bordo`), servido pelo
proprio bordo, SEM LOGIN, e o agente de ordens espera a chave em vez de morrer.

Provas (medidas, com o `ground/api.py` de verdade):
  1. `/bordo` responde 200 HTML SEM sessao e a pagina diz o que faz;
  2. `/api/bordo` responde o estado SEM sessao — licenca, token, lado terra, agente, varredura, saude;
  3. a resposta NAO carrega segredo: a chave da licenca so' nos ultimos 4 digitos e o token so' como
     presente/ausente;
  4. com licenca gravada a maquina se declara ativada; sem licenca, "esta maquina ainda nao foi ativada";
  5. o sinal do agente de ordens e o que ele tem no ar aparecem no painel (e o sinal velho = "sem sinal");
  6. o app (main.js/configuracao.js/servidor.js), a tela da chave e o agente: a entrada da maquina de
     captura e' o painel (nao o login), o pacote de captura sobe no boot do Windows, o agente espera a
     chave e a tela da chave pede a varredura e vai para o painel.

Uso: python tests/test-bordo-sem-login-e-autonomo.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas: list = []
TOKEN = "token-de-teste-do-bordo"
# O vinculo que o lado terra grava quando o PC digita a chave (`<dados>/licenca.json`).
LICENCA = {"chave": "ABCD-EFGH-JKMN-PQRS", "licenca_id": "lic-1", "embarcacao_id": "emb-teste",
           "embarcacao_nome": "Embarcacao de Teste", "cliente_id": "cli-1",
           "cliente_nome": "Empresa de Teste", "validade_tipo": "indeterminada", "validade_em": "",
           "status": "ativa", "motivo": "", "maquina": "pc-teste",
           "ativada_em": "2026-11-23T10:00:00", "conferida_em": "2026-11-23T10:00:00", "origem": "terra"}


def checar(condicao: bool, texto: str) -> None:
    print(("  ok    — " if condicao else "  FALHA — ") + texto)
    if not condicao:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pegar(url: str, dados: dict | None = None, timeout: float = 15, cru: bool = False):
    """GET/POST sem cookie nenhum (e' assim que a maquina de captura abre o painel: sem login)."""
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
            return r.status, (b.decode("utf-8", "replace") if cru else json.loads(b or b"{}"))
    except urllib.error.HTTPError as e:
        try:
            b = e.read()
            return e.code, (b.decode("utf-8", "replace") if cru else json.loads(b or b"{}"))
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, (f"{type(e).__name__}: {e}" if cru else {"erro": f"{type(e).__name__}: {e}"})


def ambiente_do_caso(pasta: Path, token: str = TOKEN, licenca: dict | None = None,
                     declarada: bool = False) -> dict:
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(pasta / "pipeline.db")
    env["LECSOR_GRAVACOES_DIR"] = str(pasta / "gravacoes")
    env["LECSOR_AGENTE_ESTADO"] = str(pasta / "agente-vivo.json")
    env["LECSOR_ORDENS_ESTADO"] = str(pasta / "ligados.json")
    env["LECSOR_LICENCA"] = str(pasta / "licenca.json")
    env["LECSOR_SEM_AMBIENTE"] = "1"          # nao ler o ambiente.json do repo
    if declarada:
        # e' assim que o app diz que ESTA maquina e' a de captura (`amb()`, desktop/servidor.js)
        env["LECSOR_CAPTURA_LOCAL"] = "1"
    else:
        env.pop("LECSOR_CAPTURA_LOCAL", None)
    env.pop("LECSOR_EMBARCACAO", None)
    env.pop("LECSOR_DESTINO_SRT", None)
    env["LECSOR_LADO_TERRA_API"] = "http://127.0.0.1:1"   # ninguem atende: o bordo nao depende disso
    if token:
        env["LECSOR_TOKEN_INGESTAO"] = token
    else:
        env.pop("LECSOR_TOKEN_INGESTAO", None)
    if licenca:
        (pasta / "licenca.json").write_text(json.dumps(licenca, ensure_ascii=False), encoding="utf-8")
    return env


def subir_bordo(env: dict):
    porta = porta_livre()
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(40):
        if pegar(base + "/api/saude")[0] == 200:
            return proc, base
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("o servidor do bordo nao subiu para o teste")


def principal() -> int:
    print("PC de captura autonomo — painel do bordo sem login e publicando sozinho")

    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)

        # ------------------------------------------------------------------ 1) SEM licenca ainda
        print("\n1) maquina ainda sem chave: o painel abre SEM LOGIN e diz que falta a chave")
        env = ambiente_do_caso(pasta)
        proc, base = subir_bordo(env)
        try:
            c, html = pegar(base + "/bordo", cru=True)
            checar(c == 200 and isinstance(html, str) and "<html" in html.lower(),
                   f"`/bordo` e' servida sem sessao nenhuma ({c})")
            checar("Bordo" in html and "autôno" in html,
                   "a pagina do bordo e' o painel da maquina autonoma (nao e' tela de login)")
            checar('type="password"' not in html and "/api/entrar" not in html,
                   "a pagina do bordo nao tem campo de senha nem login (ela so' INFORMA)")

            c, d = pegar(base + "/api/bordo")
            checar(c == 200 and d.get("ok") is True, f"`/api/bordo` responde o estado sem login ({c})")
            for chave in ("licenca", "token", "lado_terra", "agente", "varredura", "saude", "no_ar"):
                checar(chave in d, f"o estado do bordo traz `{chave}`")
            lic = d.get("licenca") or {}
            checar(lic.get("tem") is False and "não foi ativada" in str(lic.get("texto", "")),
                   f"sem chave, o painel diz que a maquina nao foi ativada ({lic.get('texto')!r})")
            checar(d.get("token", {}).get("presente") is True,
                   "o token do INSTALADOR aparece como presente (D1: o token continua no instalador)")
            checar("chave" not in lic,
                   "a resposta NAO carrega a chave da licenca (so' `chave_ultimos4`)")
            checar("chave_ultimos4" in lic, "e carrega os ultimos 4 digitos, que nao sao segredo")

            # sinal do agente: ausente = sem sinal; fresco = no ar; velho = sem sinal
            ag = d.get("agente") or {}
            checar(ag.get("no_ar") is False, "sem sinal do agente, o painel diz que ele NAO esta no ar")
            Path(env["LECSOR_AGENTE_ESTADO"]).write_text(
                json.dumps({"em": time.strftime("%Y-%m-%dT%H:%M:%S"), "rodadas": 7}), encoding="utf-8")
            _, d2 = pegar(base + "/api/bordo")
            ag2 = d2.get("agente") or {}
            checar(ag2.get("no_ar") is True and ag2.get("rodadas") == 7,
                   f"com sinal fresco, o painel diz que o agente esta no ar ({ag2.get('rodadas')} rodadas)")
            Path(env["LECSOR_AGENTE_ESTADO"]).write_text(
                json.dumps({"em": "2020-01-01T00:00:00", "rodadas": 2}), encoding="utf-8")
            _, d3 = pegar(base + "/api/bordo")
            checar((d3.get("agente") or {}).get("no_ar") is False,
                   "sinal velho = agente parado (o painel nao inventa 'no ar')")

            # o que o bordo tem no ar (o que ELE ligou, pela ordem do cliente/admin)
            Path(env["LECSOR_ORDENS_ESTADO"]).write_text(json.dumps(
                {"cam-01": {"camera_id": "cam-01", "desde": time.time(), "ordem": "cliente"}}),
                encoding="utf-8")
            _, d4 = pegar(base + "/api/bordo")
            no_ar = d4.get("no_ar") or []
            checar(len(no_ar) == 1 and no_ar[0].get("camera_id") == "cam-01"
                   and no_ar[0].get("ordem") == "cliente",
                   "o painel mostra o que o bordo tem no ar, com a origem da ordem")
            checar(isinstance(d4.get("varredura"), dict),
                   "o painel traz a varredura local como objeto (mesmo vazia, com o motivo)")
            checar(isinstance(d4.get("saude"), dict) and d4["saude"],
                   "o painel traz a saude do bordo (o que o admin acompanha do lado terra)")

            # sem chave a maquina NAO varre sozinha: a varredura nao teria onde pendurar a camera
            c, _ = pegar(base + "/api/varredura", dados={})
            checar(c == 401,
                   f"sem chave, a varredura nao e' aceita (a camera nao tem embarcacao; {c})")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()

        # ------------------------------------- 1b) chave SEM o app se declarar maquina de captura
        print("\n1b) com chave, mas SEM o app se declarar: a varredura por loopback continua exigindo sessao")
        pasta1b = pasta / "sem-declaracao"
        pasta1b.mkdir()
        env1b = ambiente_do_caso(pasta1b, licenca=dict(LICENCA), declarada=False)
        proc1b, base1b = subir_bordo(env1b)
        try:
            c, _ = pegar(base1b + "/api/varredura", dados={})
            checar(c == 401,
                   f"sem a declaracao do app, o loopback NAO varre sozinho (a regra de sessao vale; {c})")
        finally:
            proc1b.terminate()
            try:
                proc1b.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc1b.kill()

        # ------------------------------------------------------------------ 2) COM licenca gravada
        print("\n2) maquina ATIVADA pela chave: o painel confirma a embarcacao (e nao ha login)")
        pasta2 = pasta / "ativada"
        pasta2.mkdir()
        env2 = ambiente_do_caso(pasta2, licenca=dict(LICENCA), declarada=True)
        proc2, base2 = subir_bordo(env2)
        try:
            _, d = pegar(base2 + "/api/bordo")
            lic = d.get("licenca") or {}
            checar(lic.get("tem") is True and lic.get("embarcacao_id") == "emb-teste",
                   f"a maquina ativada se declara ligada a embarcacao da chave ({lic.get('embarcacao_id')})")
            checar(lic.get("estado") == "ativa", "e o estado da licenca aparece no painel")
            checar("chave" not in lic and lic.get("chave_ultimos4") == "PQRS",
                   f"a chave inteira NAO vai para a tela; so' os ultimos 4 ({lic.get('chave_ultimos4')})")
            # COM a chave, a PROPRIA maquina pede a varredura (sem login nenhum): e' ela que ve a camera
            c, v = pegar(base2 + "/api/varredura", dados={})
            checar(c != 401 and isinstance(v, dict),
                   f"com a chave, a propria maquina pede a varredura sem login ({c})")
            checar(str(v.get("motivo") or "").strip() != "" or v.get("ok") is True,
                   "e a varredura diz o que fez (ou o motivo de nao ter cadastrado nada)")
        finally:
            proc2.terminate()
            try:
                proc2.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc2.kill()

        # ------------------------ 2b) o que ela FAZ agora, o que MEDIU e o que ela mesma configurou
        print("\n2b) processos em andamento, desempenho medido e a configuracao local autonoma")
        pasta2b = pasta / "autonoma"
        pasta2b.mkdir()
        env2b = ambiente_do_caso(pasta2b, licenca=dict(LICENCA), declarada=True)
        # (1) a gravacao full-time do radar esta ligada, com 2 blocos no HD local
        hd = pasta2b / "hd"
        hd.mkdir()
        for nome, tam in (("bloco-20261123-140000.mp4", 2048), ("bloco-20261123-140100.mp4", 4096)):
            (hd / nome).write_bytes(b"x" * tam)
        env2b["LECSOR_GRAVACAO_CONTINUA"] = "1"
        env2b["LECSOR_HD_DIR"] = str(hd)
        env2b["LECSOR_HD_CAMERA"] = "radar"
        # (2) a telemetria do ULTIMO minuto: o que o proprio bordo mediu (entrada x saida)
        con = sqlite3.connect(env2b["LECSOR_BANCO"])
        con.execute("""CREATE TABLE IF NOT EXISTS telemetria_minuto (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fluxo_id TEXT NOT NULL, camera_id TEXT,
            embarcacao_id TEXT, minuto TEXT NOT NULL, entrada_kbps REAL, saida_kbps REAL,
            compressao_pct REAL, mb_enviados REAL, segundos_no_ar REAL, amostras INTEGER,
            criado_em TEXT NOT NULL, UNIQUE(fluxo_id, minuto))""")
        con.execute("INSERT INTO telemetria_minuto (fluxo_id,camera_id,embarcacao_id,minuto,"
                    "entrada_kbps,saida_kbps,compressao_pct,mb_enviados,segundos_no_ar,amostras,criado_em)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("cam-01", "cam-01", "emb-teste", time.strftime("%Y-%m-%dT%H:%M"),
                     4512.0, 812.0, 82.0, 12.4, 58.0, 60, time.strftime("%Y-%m-%dT%H:%M:%S")))
        con.commit()
        con.close()
        # (3) o cliente mandou a camera 1 subir; o radar esta' gravando => os dois, com nomes certos
        Path(env2b["LECSOR_ORDENS_ESTADO"]).write_text(json.dumps(
            {"cam-01": {"camera_id": "cam-01", "desde": time.time(), "ordem": "cliente"},
             "radar": {"camera_id": "radar", "desde": time.time(), "ordem": "admin"}}), encoding="utf-8")
        Path(env2b["LECSOR_AGENTE_ESTADO"]).write_text(
            json.dumps({"em": time.strftime("%Y-%m-%dT%H:%M:%S"), "rodadas": 12}), encoding="utf-8")
        proc2b, base2b = subir_bordo(env2b)
        try:
            t0 = time.time()
            c, d = pegar(base2b + "/api/bordo", timeout=90)
            demora = time.time() - t0
            checar(c == 200, f"o painel responde com tudo ligado ({c}, {demora:.1f}s)")
            por_fluxo = {str(p.get("fluxo")): p for p in (d.get("processos") or [])}
            checar(por_fluxo.get("radar", {}).get("estado") == "transmitindo e gravando",
                   "o radar aparece como 'transmitindo e gravando' "
                   f"({por_fluxo.get('radar', {}).get('estado')})")
            checar(por_fluxo.get("cam-01", {}).get("estado") == "transmitindo",
                   f"a camera 1 aparece como 'transmitindo' ({por_fluxo.get('cam-01', {}).get('estado')})")
            checar(por_fluxo.get("radar", {}).get("gravando") is True,
                   "e o radar esta' marcado como GRAVANDO (nao so' 'no ar')")
            g = d.get("gravacao") or {}
            checar(g.get("ligada") is True and g.get("blocos") == 2,
                   f"a gravacao full-time aparece ligada, com os 2 blocos do HD ({g.get('blocos')})")
            des = d.get("desempenho") or {}
            f0 = (des.get("fluxos") or [{}])[0]
            checar(des.get("medido") is True and f0.get("entrada_kbps") == 4512.0
                   and f0.get("saida_kbps") == 812.0,
                   f"o desempenho MEDIDO aparece na tela ({f0.get('entrada_kbps')} -> "
                   f"{f0.get('saida_kbps')} kbps)")
            checar(f0.get("compressao_pct") == 82.0, "e a reducao de banda medida tambem (82 %)")
            cfg = {str(x.get("passo")): x for x in (d.get("configuracao") or [])}
            checar(cfg.get("Chave de licenca desta maquina", {}).get("feito") is True,
                   "a configuracao local traz a chave como passo CUMPRIDO")
            checar(any("flags" in k and v.get("feito") is True for k, v in cfg.items()),
                   "e mostra que ela ja' olha as flags do lado terra e obedece")
            checar("sem medida" not in json.dumps(des.get("fluxos") or []),
                   "com medicao no banco, a tela NAO diz 'sem medida' (numero real, nao inventado)")
            # o link custa um ping + o mediamtx (~5 s): ele e' guardado em cache curto para o painel
            # (que se atualiza a cada 10 s) nao pagar 5 s toda vez — e o campo diz ha' quanto foi lido
            t1 = time.time()
            _, d_lento = pegar(base2b + "/api/bordo", timeout=90)
            t1 = time.time() - t1
            checar("medido_ha_s" in ((d_lento.get("desempenho") or {}).get("link") or {}),
                   "o painel diz ha' quanto tempo o link foi medido (numero com procedencia)")
            checar(t1 < demora + 1.0,
                   f"a segunda leitura usa o cache do link e nao paga tudo de novo ({t1:.1f}s vs {demora:.1f}s)")

            # sem NADA ligado e sem medicao, a tela diz o que e' verdade — e nao inventa numero
            Path(env2b["LECSOR_ORDENS_ESTADO"]).write_text("{}", encoding="utf-8")
            env2b["LECSOR_GRAVACAO_CONTINUA"] = "0"
            proc2c, base2c = subir_bordo({**env2b, "LECSOR_BANCO": str(pasta2b / "vazio.db")})
            try:
                _, dv = pegar(base2c + "/api/bordo", timeout=90)
                checar((dv.get("processos") or []) == []
                       or all(p.get("estado") == "parado" for p in dv.get("processos") or []),
                       "sem ordem e sem gravacao, o painel nao diz que algo esta no ar")
                desv = dv.get("desempenho") or {}
                checar(desv.get("medido") is False and str(desv.get("motivo") or "") != "",
                       f"sem medicao, o painel diz 'sem medida' e o motivo ({desv.get('motivo')!r})")
            finally:
                proc2c.terminate()
                try:
                    proc2c.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    proc2c.kill()
        finally:
            proc2b.terminate()
            try:
                proc2b.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc2b.kill()

    # ---------------------------------------------------------------------- 3) o APP nao pede login
    print("\n3) o aplicativo: a entrada da maquina de captura e' o painel, nao o login")
    main = (RAIZ / "desktop" / "main.js").read_text(encoding="utf-8")
    conf = (RAIZ / "desktop" / "configuracao.js").read_text(encoding="utf-8")
    serv = (RAIZ / "desktop" / "servidor.js").read_text(encoding="utf-8")
    tela_chave = (RAIZ / "licenca" / "index.html").read_text(encoding="utf-8")
    agente = (RAIZ / "ground" / "agente_de_ordens.py").read_text(encoding="utf-8")

    checar("bordo: { titulo:" in main and "rota: '/bordo'" in main,
           "main.js: existe a superficie `bordo` na rota /bordo")
    checar("function ehMaquinaDeCaptura()" in main
           and "if (nome === 'entrada' && baseLocalDaCaptura && ehMaquinaDeCaptura())" in main
           and "'/bordo'" in main,
           "main.js: na maquina de captura a ENTRADA e' o painel do bordo (nunca o login)")
    checar("precisaDeLicenca" in main and "replace(/\\/$/, '') + '/licenca'" in main,
           "main.js: sem chave, a entrada continua sendo a TELA DA CHAVE (nada de login)")
    checar("abrirComWindows" in conf and "if (!escolheu && config.abrirComWindows !== true) config.abrirComWindows = true;"
           in conf,
           "configuracao.js: o pacote de captura sobe junto com o Windows (maquina autonoma)")
    checar("saida.LECSOR_CAPTURA_LOCAL = '1'" in serv,
           "servidor.js: o app DECLARA a maquina de captura ao servidor local (e' o que autoriza a "
           "varredura pelo loopback sem sessao — so' a propria maquina)")
    checar("!String(env.LECSOR_EMBARCACAO || '').trim() ||" not in serv
           and "falta o LECSOR_TOKEN_INGESTAO do pacote" in serv,
           "servidor.js: o agente de ordens so' depende do TOKEN do pacote (a embarcacao vem da chave)")
    checar("aguardando a CHAVE DE LICENCA" in agente and "while not emb:" in agente,
           "agente-de-ordens: sem chave ele ESPERA a chave em vez de morrer (o app nao morre com ele)")
    checar("'/bordo'" in tela_chave.replace('"', "'") and "/api/varredura" in tela_chave,
           "a tela da chave pede a varredura e leva para o painel do bordo (nada mais a fazer)")
    pagina = (RAIZ / "bordo" / "index.html").read_text(encoding="utf-8")
    checar((RAIZ / "bordo" / "index.html").exists(), "o painel do bordo vem no pacote (bordo/index.html)")
    checar("O que está acontecendo agora" in pagina and "Saúde e desempenho" in pagina
           and "Como esta máquina se configurou sozinha" in pagina,
           "o painel tem os tres cartoes do dono: o que acontece agora, saude e desempenho, e a "
           "configuracao que ela mesma fez")
    checar('id="processos"' in pagina and 'id="desempenho"' in pagina and 'id="configuracao"' in pagina,
           "o painel desenha os processos em andamento, o desempenho medido e a configuracao local")
    pkg = json.loads((RAIZ / "desktop" / "package.json").read_text(encoding="utf-8"))
    recursos = json.dumps(pkg.get("build", {}).get("extraResources", []))
    checar('"../bordo"' in recursos and "servidor/bordo" in recursos,
           "e o INSTALADOR leva o painel (extraResources: ../bordo -> servidor/bordo)")

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} prova(s) — {falhas[0]}")
        return 1
    print("TUDO VERDE — o PC de captura e' autonomo: painel sem login, chave, varredura e publicacao")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
