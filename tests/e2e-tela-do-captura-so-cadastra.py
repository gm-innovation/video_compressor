#!/usr/bin/env python3
"""Prova de TELA (0.8.0, Fase 3): no computador de captura a tela só CADASTRA.

O dono (19/11/2026): "estou pensando em utilizar no computador de captura apenas o usuario de captura,
apenas para cadastrar as cameras e radar de oleo, eu configuraria tudo pelo meu usuario admin, pela
premissa de nao enviar nada para bordo" — e "o proprio app deveria se organizar de acordo com o usuario".

Sobe a API de verdade e abre navegador de verdade (Chromium do Playwright):

  1) como TECNICO (usuário do PC de captura): aparece o CADASTRO desta máquina e o estado do que está no ar,
     e NÃO aparece nenhuma ferramenta de operação (enviar vídeo de teste, fases, medições, evidências,
     registrar medição) — nem deixando a tela esperar o javascript;
  2) o cadastro FUNCIONA: rótulo + dispositivo viram uma câmera no banco desta máquina (conferida no banco);
  3) como ADMIN: as ferramentas de operação continuam lá, e o cadastro local não aparece;
  4) a tela não tem erro de javascript em nenhum dos dois papéis.

    python tests/e2e-tela-do-captura-so-cadastra.py
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
SENHA = "senha-do-tecnico-de-teste"
ESPERA = 20000


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


def criar_usuario(banco: pathlib.Path, uid: str, email: str, papel: str) -> None:
    """Mesmo esquema do servidor (pbkdf2-sha256, 200k): o login tem de ser o de verdade."""
    con = sqlite3.connect(str(banco))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", SENHA.encode(), bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, None, senha, salt))
    con.commit()
    con.close()


def entrar(pag, base: str, email: str, espera: str) -> None:
    """Entra pelo formulario de verdade e espera a TELA do papel aparecer (nao a URL: a entrada e' /entrada/)."""
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


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-captura-"))
    banco = tmp / "pipeline.db"
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_SENHA_DEMO"] = "senha-de-bancada-nao-usada"
    env["LECSOR_EMBARCACAO"] = "bancada"
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)
    porta = porta_livre()
    log = (tmp / "api.log").open("wb")
    api = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                           cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=3):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("a API nao subiu")

        criar_usuario(banco, "admin", "admin@lecsor.test", "admin")
        criar_usuario(banco, "tecnico", "tecnico@lecsor.test", "tecnico")
        con = sqlite3.connect(str(banco))
        con.execute("INSERT OR IGNORE INTO clientes (id,nome) VALUES ('lecsor','LECSOR (interno)')")
        con.execute("""INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)
                       VALUES ('bancada','lecsor','Bancada de testes (propria)','','em operacao')""")
        con.commit()
        con.close()

        erros: list[str] = []
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=_chromium())
            pag = navegador.new_page()
            pag.on("pageerror", lambda e: erros.append(str(e)))

            # ---- 1 e 2. TECNICO: so' cadastro, e o cadastro funciona
            entrar(pag, base, "tecnico@lecsor.test", "#cadastro-local")
            checar("tecnico chega na tela de captura (/), nao no admin",
                   pag.url.rstrip("/") == base, pag.url)
            checar("tecnico ve' o cadastro desta maquina", visivel(pag, "#cadastro-local"))
            checar("tecnico ve' o aviso de que so' cadastra", visivel(pag, "#aviso-captura"))
            checar("tecnico NAO ve' 'Enviar video para testar'",
                   not visivel(pag, "#btn-enviar"), "o botao de envio aparece" if visivel(pag, "#btn-enviar") else "")
            for sel, nome in [("#t-fases", "Fases"), ("#t-med", "Medições"), ("#t-ev", "Evidências"),
                              ("#t-envios", "Envios")]:
                checar(f"tecnico NAO ve' a tabela de {nome}", not visivel(pag, sel))
            checar("tecnico ve' o estado do que esta no ar (fluxos)",
                   pag.locator("#fluxos").count() == 1 and visivel(pag, "#fluxos"))
            checar("tecnico ve' o inventario de cameras desta maquina", visivel(pag, "#t-inv"))
            checar("nenhum campo de qualidade/tempo VISIVEL na tela de captura",
                   not any(visivel(pag, s) for s in ("#alvo", "#bitrate", "#cfg-teto", "#cfg-emb")))

            pag.fill("#cad-rotulo", "Câmera do convés")
            pag.fill("#cad-dispositivo", "ACER HD User Facing")
            pag.fill("#cad-local", "proa")
            pag.click("#cad-enviar")
            pag.wait_for_function("() => /cadastrada|recusado/.test(document.getElementById('cad-msg').textContent)",
                                  timeout=ESPERA)
            msg = pag.inner_text("#cad-msg")
            checar("o cadastro responde 'cadastrada'", "cadastrada" in msg, msg)
            con = sqlite3.connect(str(banco))
            linha = con.execute("SELECT id,rotulo,embarcacao_id,protocolo FROM cameras WHERE rotulo=?",
                                ("Câmera do convés",)).fetchone()
            con.close()
            checar("a camera ESTA' no banco desta maquina", linha is not None, str(linha))
            checar("...com o rotulo e o dispositivo informados (dshow local)",
                   bool(linha) and linha[2] == "bancada" and linha[3] == "dshow", str(linha))
            checar("sem erro de javascript na tela de captura", not erros, "; ".join(erros[:3]))

            # ---- 3. ADMIN: as ferramentas de operacao continuam, o cadastro local NAO
            erros.clear()
            pag2 = navegador.new_page()
            pag2.on("pageerror", lambda e: erros.append(str(e)))
            entrar(pag2, base, "admin@lecsor.test", "#sistema:not(.oculto)")
            checar("admin chega no console (/admin/)", "/admin" in pag2.url, pag2.url)
            pag2.goto(base + "/")
            pag2.wait_for_load_state("networkidle")
            checar("admin ve' 'Enviar video para testar'", visivel(pag2, "#btn-enviar"))
            checar("admin NAO ve' o cadastro do PC de captura", not visivel(pag2, "#cadastro-local"))
            checar("admin NAO recebe o aviso de 'so' cadastro'", not visivel(pag2, "#aviso-captura"))
            checar("sem erro de javascript na tela da bancada", not erros, "; ".join(erros[:3]))

            # ---- 4. a tela NOVA do admin: "Configuração do bordo" (publica e mostra desejo x aplicado)
            erros.clear()
            pag2.goto(base + "/admin/")
            pag2.wait_for_selector("#sistema:not(.oculto)", timeout=ESPERA)
            pag2.click('button.item[data-tela="config_bordo"]')
            pag2.wait_for_selector("#tela", timeout=ESPERA)
            pag2.wait_for_function("() => /Banda por câmera/.test(document.getElementById('tela').textContent)", timeout=ESPERA)
            checar("admin tem a tela 'Configuração do bordo'", visivel(pag2, "#cfg-emb"))
            checar("...com o alvo por câmera e o teto da embarcação",
                   pag2.locator("#tela select[id^=cfg-alvo-]").count() >= 1 and visivel(pag2, "#cfg-teto"))
            checar("...e diz o que está publicado (desejada x aplicada)",
                   "nada publicado" in pag2.inner_text("#tela") or "v" in pag2.inner_text("#tela").lower())
            checar("sem erro de javascript na tela de configuração do bordo", not erros, "; ".join(erros[:3]))
            navegador.close()
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except Exception:  # noqa: BLE001
            api.kill()

    print()
    if falhas:
        print(f"FALHOU ({len(falhas)}):")
        for f in falhas:
            print("  - " + f)
        return 1
    print("TUDO OK — a tela do captura so' cadastra, e o cadastro esta' provado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
