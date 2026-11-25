#!/usr/bin/env python3
"""Prova de TELA: a AREA UNICA do admin — empresa -> embarcacao -> cameras (0.12.0, aprovado 23/11/2026).

Pedido do dono, verbatim: *"na area do admin, preciso poder configurar cada cliente/embarcacao/cameras
de forma unificada e simples, hoje eu tenho muitas paginas: clientes/embarcacoes/cameras/licencas/
producao/tempo real/enviar videos/usuarios/configuracoes do bordo, tudo isso poderia ser uma area so, de
configuracao por cliente e de embarcacoes pra baixo tudo vinculado ao cliente... e esta ainda truncado,
parece que esta tudo funcionando do lado da captura mas as cameras nao aparecem do lado do admin, pelo
menos nao com o nome que a varredura pegou, e nao consigo configurar e ligar as cameras"*. E o fluxo que
ele mandou seguir: *"o correto e' eu criar a empresa caso ainda nao tenha sido criada, depois embarcacao
vinculada a aquela empresa, gero a chave na embarcacao, na embarcacao aparecem as cameras encontradas na
varredura, configuro as cameras e a captura pega as informacoes e replica no app de captura, inclusive os
nomes das cameras"*.

Sobe a API de verdade (banco proprio) e abre um Chromium de verdade (Playwright). O que se prova:

  1) a tela de entrada do admin E' a area unica ("Empresas e configuracao"), com a empresa e o resumo dela;
  2) abrir a empresa -> as embarcacoes dela e, em cada uma, o cartao do PC de captura com a CHAVE;
  3) as cameras da VARREDURA aparecem ali COM O NOME QUE O DISPOSITIVO TEM (`USB Video Device`) e
     marcadas "achada pela varredura" — nao somem e nao vem truncadas (fim da tabela de 12 colunas);
  4) dar NOME a camera PUBLICa o nome para o PC de captura (a chave `rotulo` sai em `config_bordo`) e o
     cadastro do lado terra passa a mostrar o nome novo;
  5) escolher a qualidade de envio publica o `alvo_kbps` daquela camera;
  6) ativar/desativar muda o estado da camera;
  7) "ligar agora" da' retorno na cara (nunca silencio) e a chave da licenca se gera NA embarcacao;
  8) o menu esta' enxuto (as telas antigas sairam, a camera se edita DENTRO da empresa) e nao ha erro de JS.

    python tests/e2e-admin-unificado.py
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
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
EMPRESA = "petrobras"
EMB = "emb-1"
CAM_VARREDURA = "cam-device-pnp-usb-vid-046d-pid-0825"
NOME_DA_VARREDURA = "USB Video Device"
FORMATO_CHAVE = re.compile(r"^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$")


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def nota(texto: str) -> None:
    print("  ..   " + texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str) -> None:
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,NULL,?,?,200000,1)""", (uid, email, uid, papel, senha, salt))
    con.commit()
    con.close()


def semear(banco: pathlib.Path) -> None:
    """O estado que o dono viu: a empresa, a EMBARCACAO e as cameras — uma delas como a varredura a
    criou (id do dispositivo, nome do dispositivo) e outra cadastrada a mao."""
    con = sqlite3.connect(str(banco))
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Petrobras"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "PSV LECSOR I"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                   VALUES (?,?,?,?,?,1,'800k')""",
                (CAM_VARREDURA, EMB, NOME_DA_VARREDURA, CAM_VARREDURA, "bordo"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                   VALUES ('cam-01',?,'Proa','cam-01','bordo',1,'800k')""", (EMB,))
    # O bordo ja' contou que a camera da varredura esta' no ar (e' o que a tela tem de mostrar).
    con.execute("""INSERT OR REPLACE INTO estado_bordo (camera_id,embarcacao_id,estado,motivo,fluxo_id,
                      desde,gravando,atualizado_em)
                   VALUES (?,?,'transmitindo','',?,'2026-11-23T18:00:00-03:00',0,
                           '2026-11-23T18:05:00-03:00')""", (CAM_VARREDURA, EMB, CAM_VARREDURA))
    con.commit()
    con.close()


def entrar(pag, base: str, email: str, espera: str) -> None:
    pag.goto(base + "/entrada/")
    pag.fill("#email", email)
    pag.fill("#senha", SENHA)
    pag.click("form#form-entrar button[type=submit]")
    pag.wait_for_selector(espera, timeout=ESPERA)
    pag.wait_for_load_state("networkidle")


def visivel(pag, sel: str) -> bool:
    try:
        return pag.is_visible(sel, timeout=2500)
    except Exception:  # noqa: BLE001
        return False


def palco(pag) -> str:
    try:
        return pag.inner_text("#tela")
    except Exception:  # noqa: BLE001
        return ""


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


def esperar_texto(pag, trecho: str, ms: int = ESPERA) -> bool:
    try:
        pag.wait_for_function(
            "t => document.querySelector('#tela').innerText.includes(t)", arg=trecho, timeout=ms)
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-admin-unificado-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    env = dict(os.environ)
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO", "LECSOR_EMBARCACAO", "LECSOR_LICENCA"):
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
            raise RuntimeError("a API nao subiu; log em %s" % (tmp / "api.log"))

        criar_usuario(banco, "admin", "admin@lecsor.test", "admin")
        semear(banco)

        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            contexto = navegador.new_context()
            pag = contexto.new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))
            # "desativar" e "gerar outra chave" perguntam antes (confirm): o navegador de prova aceita.
            pag.on("dialog", lambda d: d.accept())
            entrada = "button[data-tela=empresas]"

            print("\n== 1. a tela de entrada do admin E' a area unica ==")
            entrar(pag, base, "admin@lecsor.test", entrada)
            checar("o menu tem 'Empresas e configuracao'", visivel(pag, entrada))
            checar("e ela e' a tela ABERTA (o caminho do dia a dia)",
                   visivel(pag, ".item[data-tela=empresas].on"))
            checar("a tela abre com o titulo da area unica",
                   "Empresas e configura" in pag.inner_text("#titulo-tela"), pag.inner_text("#titulo-tela"))
            corpo = palco(pag)
            checar("a empresa aparece na raiz", "Petrobras" in corpo and EMPRESA in corpo, corpo[:200].replace("\n", " | "))
            checar("e o resumo dela diz o que tem dentro (1 embarcacao, 2 cameras)",
                   "1 embarca" in corpo and "2 c" in corpo, corpo[:300].replace("\n", " | "))

            print("\n== 2. abrir a empresa -> embarcacao -> o cartao do PC de captura ==")
            pag.locator(".cartao-empresa").filter(has_text="Petrobras").locator("text=Abrir").first.click()
            checar("a pagina da empresa abre com a embarcacao dela",
                   esperar_texto(pag, "PSV LECSOR I"), palco(pag)[:200].replace("\n", " | "))
            checar("a embarcacao carrega o resumo de cameras",
                   "Câmeras: 2" in palco(pag), palco(pag)[:300].replace("\n", " | "))
            checar("e o campo de gerar a CHAVE fica na embarcacao (dono: 'gero a chave na embarcacao')",
                   "Gerar chave" in palco(pag))

            print("\n== 3. as cameras da VARREDURA aparecem, com o nome que a varredura pegou ==")
            checar("as cameras viram CARTAO (nada de tabela de 12 colunas truncada)",
                   pag.locator(".cartao-camera").count() == 2,
                   f"{pag.locator('.cartao-camera').count()} cartoes")
            carta_varredura = pag.locator(".cartao-camera").filter(has_text="cam-device-pnp")
            carta_cam01 = pag.locator(".cartao-camera").filter(has_text="fluxo cam-01")
            corpo = palco(pag)
            checar("e marcada como 'achada pela varredura'", "achada pela varredura" in corpo)
            checar("cada camera e' um cartao proprio (a da varredura e a cadastrada a mao)",
                   carta_varredura.count() == 1 and carta_cam01.count() == 1,
                   f"{carta_varredura.count()} + {carta_cam01.count()}")
            valor = carta_varredura.locator("input.nome-camera").input_value()
            checar("a camera da varredura chega com o NOME DO DISPOSITIVO no cartao",
                   valor == NOME_DA_VARREDURA, f"{valor!r}")
            checar("o nome no campo do cartao esta' INTEIRO (nao cortado)",
                   len(valor) == len(NOME_DA_VARREDURA), f"{len(valor)} de {len(NOME_DA_VARREDURA)}")
            checar("e a camera cadastrada a mao continua com o nome dela",
                   carta_cam01.locator("input.nome-camera").input_value() == "Proa",
                   f"{carta_cam01.locator('input.nome-camera').input_value()!r}")
            checar("o menu de qualidade ja' vem no valor atual daquela camera",
                   carta_cam01.locator("select").input_value() == "800",
                   f"{carta_cam01.locator('select').input_value()!r}")
            checar("e a qualidade aparece por extenso na ficha (sem 'k kbps')",
                   "800 kbps" in corpo and "k kbps" not in corpo)

            print("\n== 4. dar NOME a camera publica o nome para o PC de captura ==")
            carta_varredura.locator("input.nome-camera").fill("Proa de boreste")
            carta_varredura.locator("text=salvar nome").click()
            checar("a tela confirma o nome salvo e publicado",
                   esperar_texto(pag, "publicado para o PC de captura"), palco(pag)[:250].replace("\n", " | "))
            con = sqlite3.connect(str(banco))
            linha = con.execute("SELECT valor,versao FROM config_bordo WHERE camera_id=? AND chave='rotulo'",
                                (CAM_VARREDURA,)).fetchone()
            rotulo = con.execute("SELECT rotulo FROM cameras WHERE id=?", (CAM_VARREDURA,)).fetchone()
            con.close()
            checar("o nome saiu como configuracao para o bordo (chave `rotulo` em config_bordo)",
                   bool(linha) and linha[0] == "Proa de boreste", f"{linha}")
            checar("e o cadastro do lado terra ja' mostra o nome novo",
                   bool(rotulo) and rotulo[0] == "Proa de boreste", f"{rotulo}")

            print("\n== 5. escolher a qualidade de envio publica o alvo daquela camera ==")
            carta_cam01.locator("select").select_option("500")
            carta_cam01.locator("text=aplicar qualidade").click()
            checar("a tela confirma a qualidade publicada",
                   esperar_texto(pag, "qualidade publicada"), palco(pag)[:250].replace("\n", " | "))
            con = sqlite3.connect(str(banco))
            alvo = con.execute("SELECT valor FROM config_bordo WHERE camera_id='cam-01' AND chave='alvo_kbps'").fetchone()
            con.close()
            checar("o alvo da camera saiu como configuracao (alvo_kbps=500)", bool(alvo) and alvo[0] == "500", f"{alvo}")

            print("\n== 6. ativar / desativar a camera ==")
            carta_cam01.locator("text=desativar").click()
            pag.wait_for_timeout(1500)
            con = sqlite3.connect(str(banco))
            ativo = con.execute("SELECT ativo FROM cameras WHERE id='cam-01'").fetchone()
            con.close()
            checar("desativar tira a camera de circulacao no banco", bool(ativo) and ativo[0] == 0, f"{ativo}")

            print("\n== 7. D3: o admin NAO tem 'ligar agora' (so' quem assiste liga) e a chave se gera na embarcacao ==")
            # D3 do dono (24/11/2026): "nao tem ligar agora do admin, so quem visualiza e' o cliente".
            # O admin NAO liga camera — quem liga e' a sessao de quem esta' assistindo.
            checar("o cartao da camera NAO oferece 'ligar agora' (D3)",
                   carta_varredura.locator("text=ligar agora").count() == 0)
            tok = hashlib.sha256(os.urandom(16)).hexdigest()
            con = sqlite3.connect(str(banco))
            con.execute("""INSERT INTO sessoes (token,usuario_id,expira_em) VALUES (?,?,?)
                           ON CONFLICT(token) DO NOTHING""", (tok, "admin", "2099-01-01T00:00:00-03:00"))
            con.commit(); con.close()
            st, _r = pedir("POST", base + "/api/cameras/ligar", {"camera_id": CAM_VARREDURA}, cookie=tok)
            con = sqlite3.connect(str(banco))
            man = con.execute("SELECT COALESCE(manual,'') FROM desejo_camera WHERE camera_id=?",
                              (CAM_VARREDURA,)).fetchone()
            con.close()
            checar("e o 'ligar' do admin nao grava manual='ligar' (D3)",
                   (man is None) or (man[0] != "ligar"), f"HTTP {st}, manual={man}")
            pag.locator("text=Gerar chave").first.click()
            ok = esperar_texto(pag, "Digite esta chave no aplicativo")
            chave = ""
            for i in range(pag.locator("#tela code").count()):
                t = pag.locator("#tela code").nth(i).inner_text().strip()
                if FORMATO_CHAVE.match(t):
                    chave = t
            checar("a chave da licenca se gera NA embarcacao e aparece para copiar",
                   ok and bool(chave), f"{chave!r}")
            con = sqlite3.connect(str(banco))
            lic = con.execute("SELECT embarcacao_id FROM licencas").fetchone()
            con.close()
            checar("e a licenca fica presa a' aquela embarcacao", bool(lic) and lic[0] == EMB, f"{lic}")

            print("\n== 8. o menu do admin esta' enxuto (as telas antigas sairam) e a tela nao tem erro de JS ==")
            # 0.19.0 (dono, 25/11/2026: "muita redundancia, telas inuteis ou que nao funcionam"): as
            # telas antigas (clientes/embarcacoes/cameras/producao/tempo/analises/marcas) SAIRAM do menu —
            # a camera se edita DENTRO da empresa (a area unica). O que nao esta' no menu nao abre.
            antigas = ["clientes", "embarcacoes", "cameras", "producao", "tempo", "analises", "marcas"]
            restantes = [t for t in antigas
                         if pag.evaluate("(t) => !!document.querySelector('button[data-tela=' + t + ']')", t)]
            checar("as telas antigas sairam do menu do admin", not restantes, f"ainda no menu: {restantes}")
            checar("e a area unica (Empresas e configuracao) continua",
                   pag.evaluate("() => !!document.querySelector('button[data-tela=empresas]')"))
            checar("sem erro de javascript na area unica", not erros, "; ".join(erros[:3]))
            navegador.close()

            print("\n== 9. a rota da area unica responde o que a tela mostra ==")
            con = sqlite3.connect(str(banco))
            tok = hashlib.sha256(os.urandom(16)).hexdigest()
            con.execute("""INSERT INTO sessoes (token,usuario_id,expira_em) VALUES (?,?,?)
                           ON CONFLICT(token) DO NOTHING""",
                        (tok, "admin", "2099-01-01T00:00:00-03:00"))
            con.commit()
            con.close()
            st, arv = pedir("GET", base + "/api/empresas", None, cookie=tok)
            empresas = arv.get("empresas") or []
            uma = next((e for e in empresas if e["id"] == EMPRESA), {})
            embs = uma.get("embarcacoes") or []
            cams = (embs[0].get("cameras") if embs else []) or []
            nomes = [c["rotulo"] for c in cams]
            checar("GET /api/empresas traz a empresa com a embarcacao e as cameras", st == 200 and bool(cams),
                   f"HTTP {st}, {len(cams)} cameras")
            checar("e o nome publicado ja' aparece nela", "Proa de boreste" in nomes, f"{nomes}")
            achada = [c for c in cams if c.get("achada_pela_varredura")]
            checar("e a camera da varredura vem marcada como tal", len(achada) == 1, f"{len(achada)}")
            checar("sem endereco nem credencial de camera na resposta da tela",
                   not any(k in json.dumps(arv).lower() for k in ("senha", "\"ip\"", "rtsp://")),
                   "resposta limpa")
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            api.kill()
        log.close()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s): " + "; ".join(falhas))
        return 1
    print("RESULTADO: tudo passou — a area unica mostra empresa -> embarcacao -> cameras (com o nome da "
          "varredura), publica o nome e a qualidade para o PC de captura, liga/desliga e gera a chave no "
          "lugar certo; e o menu esta' enxuto (as telas antigas sairam).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
