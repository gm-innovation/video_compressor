#!/usr/bin/env python3
"""AO VIVO DO ADMIN COM LIGAR/PARAR + "GRAVANDO A BORDO" NO MONITORAMENTO (rodada 0.23.0, 26/11/2026).

Palavras do dono (26/11/2026, verbatim):

> "eu devo poder ligar e parar a câmera também, 'imagens gravadas a bordo' não faz sentido, só preciso no
>  monitoramento saber se está sendo gravado a bordo, não preciso ver as imagens"

> "mas não são as imagens gravadas, é ao vivo, preciso poder selecionar a empresa>embarcação>câmera"

E as duas decisões dele sobre este plano: **2.A** (o admin é plateia: a câmera para quando ele fecha a
janela) e **botão ligar/desligar + indicador** para a gravação contínua do radar.

O que se prova aqui, com o servidor de verdade (sem câmera física — a bancada não tem uma):

  1) a tela "Imagens gravadas a bordo" SAIU do admin (menu e código), e as ROTAS `/api/hd/*` continuam
     no ar (são as do cliente "Radar de óleo (HD)" e do observador Petrobras/IBAMA);
  2) o admin LIGA a câmera (`POST /api/transmissao/iniciar` → 201) e o desejo publicado vira `ligar`
     porque a sessão DELE sustenta ("o admin é a plateia");
  3) a Auditoria guarda que quem ligou foi a OPERAÇÃO (`transmissao_pedida — operacao`);
  4) o admin PARA a câmera e o desejo volta a `parar`;
  5) um papel sem permissão (observador) continua RECUSADO (403);
  6) o bordo conta `gravando` no `/api/estado-real` → o monitoramento mostra "gravando a bordo: 1 câmera";
  7) sem a chave `gravando` no estado real a tela diz "NÃO MEDIDO" (nunca "desligado" sem medida);
  8) o botão da gravação contínua publica a chave (`gravacao_continua=1`) e o bordo APLICA de verdade
     (o desejo é escrito no HD e `ligada` vira True; `0` desliga); valor fora de 0/1 e pedido com
     `camera_id` são RECUSADOS com a razão.

    python tests/test-ao-vivo-do-admin-ligar-parar-e-gravando-a-bordo.py
"""
from __future__ import annotations

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
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
TOKEN = "token-de-ingestao-da-rodada-023"
EMB = "emb-023"

ADMIN = "admin@lecsor.test"
OBSERVADOR = "petrobras@lecsor.test"


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def nota(texto: str) -> None:
    print("     " + texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(metodo, url, corpo=None, cookie="", token=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"erro": f"{type(e).__name__}: {e}"}


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError(f"a API saiu com codigo {proc.returncode}: "
                               + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-700:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-700:])


def sessao_de(con, uid, email, papel, cliente_id="lecsor"):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    tok = "tok-" + uid
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    return tok


def main() -> int:
    print("AO VIVO DO ADMIN (ligar/parar) + GRAVANDO A BORDO NO MONITORAMENTO — 0.23.0, 26/11/2026.\n")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-aovivo-"))
    banco = tmp / "terra.db"
    hd = tmp / "hd"                       # o "HD" do PC de captura: recebe o ligada.txt do botao
    porta = porta_livre()
    proc = None
    try:
        proc = sobe_api(banco, porta, {"LECSOR_TOKEN_INGESTAO": TOKEN, "LECSOR_SEM_AMBIENTE": "1",
                                       "LECSOR_HD_DIR": str(hd)})
        base = f"http://127.0.0.1:{porta}"

        con = sqlite3.connect(str(banco))
        try:
            con.row_factory = sqlite3.Row
            con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR (teste)')")
            con.execute("""INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado)
                           VALUES (?,?,?,?,?)""", (EMB, "lecsor", "Bancada do teste", "", "em operacao"))
            con.execute("""INSERT OR REPLACE INTO cameras
                           (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                           VALUES ('cam-radar',?,'Radar de óleo','cam-radar','',1,'','','dshow','',1500,'radar')""",
                        (EMB,))
            con.commit()
            tok_admin = sessao_de(con, "adm1", ADMIN, "admin")
            tok_obs = sessao_de(con, "obs1", OBSERVADOR, "observador")
        finally:
            con.close()

        print("== 1. a tela 'Imagens gravadas a bordo' saiu do admin (e as rotas do cliente ficam)\n")
        try:
            with urllib.request.urlopen(f"{base}/admin/", timeout=10) as r:
                cod = r.status
        except urllib.error.HTTPError as e:
            cod = e.code
        except Exception as e:  # noqa: BLE001
            cod = f"{type(e).__name__}: {e}"
        checar("o admin abre (200)", cod == 200, f"{cod}")
        js = (RAIZ / "admin" / "admin.js").read_text(encoding="utf-8", errors="replace")
        html = (RAIZ / "admin" / "index.html").read_text(encoding="utf-8", errors="replace")
        checar("a tela saiu do menu e do codigo do admin",
               "Imagens gravadas a bordo" not in js and "Imagens gravadas a bordo" not in html
               and "telaHdDoBordo" not in js and "hd_bordo" not in js)
        checar("o admin ganhou o botao da gravacao continua e o ao vivo com ligar/parar",
               "gravacao_continua" in js and "ligarCameraNoAdmin" in js and "pararCameraNoAdmin" in js)
        checar("no lugar da tela velha, o admin mostra 'gravando a bordo' no monitoramento",
               "gravando a bordo" in js and "grav_a_bordo" not in js)
        # as rotas seguem servindo o cliente/observador (o catalogo responde, so' nao tem tela no admin)
        cod, cat = pedir("GET", f"{base}/api/hd/catalogo?embarcacao_id={EMB}", cookie=tok_admin)
        checar("as rotas /api/hd seguem no ar (o cliente e o observador usam)",
               cod == 200 and "catalogos" in cat, f"{cod} {str(cat)[:120]}")

        print("\n== 2. o admin LIGA a camera no ao vivo (2.A: ele e' a plateia)\n")
        cod, r = pedir("POST", f"{base}/api/transmissao/iniciar", {"camera_id": "cam-radar"}, cookie=tok_admin)
        t = (r or {}).get("transmissao") or {}
        checar("o admin abre a transmissao (201) — antes a rota respondia 403 'quem inicia e' o cliente'",
               cod == 201 and bool(t.get("id")), f"{cod} {str(r)[:150]}")
        checar("a sessao nasce 'pedida' e e' do admin", t.get("estado") == "pedida"
               and t.get("usuario_email") == ADMIN, f"{t.get('estado')} {t.get('usuario_email')}")

        cod, desejo = pedir("GET", f"{base}/api/estado-desejado?embarcacao_id={EMB}", token=TOKEN)
        cams = (desejo or {}).get("cameras") or []
        d0 = next((x for x in cams if x.get("camera_id") == "cam-radar"), {})
        checar("o desejo publicado vira LIGAR por causa da sessao do admin",
               d0.get("desejo") == "ligar", f"{d0}")
        checar("e o motivo diz que a plateia e' do admin", ADMIN in str(d0.get("motivo") or ""),
               f"{d0.get('motivo')!r}")

        con = sqlite3.connect(str(banco))
        try:
            con.row_factory = sqlite3.Row
            tr = dict(con.execute("SELECT email,acao,alvo FROM auditoria_acesso WHERE acao='transmissao_pedida' "
                                  "ORDER BY rowid DESC LIMIT 1").fetchone() or {})
        finally:
            con.close()
        checar("a Auditoria guarda que quem ligou foi a OPERACAO",
               "operacao" in str(tr.get("alvo") or "") and str(tr.get("email") or "") == ADMIN,
               f"{tr.get('email')} / {tr.get('alvo')}")

        print("\n== 3. o admin PARA a camera (e o desejo volta a 'parar')\n")
        # Fechar a JANELA manda `pendente: true` (a recarga nao pode derrubar a sessao): fica na carencia.
        cod, r = pedir("POST", f"{base}/api/transmissao/{t['id']}/encerrar", {"pendente": True}, cookie=tok_admin)
        checar("fechar a janela deixa a sessao na CARENCIA (o 'pendente' protege a recarga)",
               cod == 200 and r.get("pendente") is True and r.get("carencia_s"), f"{cod} {r}")
        # O botao "parar" e' decisao: encerra na hora e a camera para.
        cod, r = pedir("POST", f"{base}/api/transmissao/{t['id']}/encerrar", {}, cookie=tok_admin)
        checar("o botao PARAR encerra a sessao do admin na hora",
               cod == 200 and r.get("encerrada") is True, f"{cod} {r}")
        cod, desejo = pedir("GET", f"{base}/api/estado-desejado?embarcacao_id={EMB}", token=TOKEN)
        cams = (desejo or {}).get("cameras") or []
        d1 = next((x for x in cams if x.get("camera_id") == "cam-radar"), {})
        checar("sem a plateia do admin o desejo volta a PARAR (fechou, a camera para)",
               d1.get("desejo") == "parar", f"{d1}")

        print("\n== 4. quem nao pode, nao pode\n")
        cod, r = pedir("POST", f"{base}/api/transmissao/iniciar", {"camera_id": "cam-radar"}, cookie=tok_obs)
        checar("o observador (Petrobras/IBAMA) continua RECUSADO (403)",
               cod == 403 and "cliente" in str(r.get("erro") or ""), f"{cod} {r}")

        print("\n== 5. o bordo conta 'gravando' e o MONITORAMENTO mostra\n")
        cod, _ = pedir("POST", f"{base}/api/estado-real",
                       {"embarcacao_id": EMB, "cameras": [
                           {"camera_id": "cam-radar", "estado": "no_ar", "gravando": True}]}, token=TOKEN)
        checar("o bordo conta o estado real (200)", cod == 200, f"{cod}")
        cod, frota = pedir("GET", f"{base}/api/frota-resumo", cookie=tok_admin)
        e0 = next((x for x in ((frota or {}).get("embarcacoes") or []) if x.get("id") == EMB), {})
        checar("o monitoramento diz que ESTA' gravando a bordo (1 camera)",
               e0.get("gravando_a_bordo") == 1 and e0.get("gravacao_medida") is True, f"{e0}")
        cod, _ = pedir("POST", f"{base}/api/estado-real",
                       {"embarcacao_id": EMB, "cameras": [{"camera_id": "cam-radar", "estado": "no_ar"}]},
                       token=TOKEN)
        cod, frota = pedir("GET", f"{base}/api/frota-resumo", cookie=tok_admin)
        e0 = next((x for x in ((frota or {}).get("embarcacoes") or []) if x.get("id") == EMB), {})
        checar("sem a chave 'gravando' o monitoramento diz NAO MEDIDO (nunca 'desligado' sem medida)",
               e0.get("gravacao_medida") is False, f"{e0}")

        print("\n== 6. o botao ligar/desligar a gravacao continua do radar\n")
        cod, r = pedir("POST", f"{base}/api/config",
                       {"embarcacao_id": EMB, "camera_id": "", "chave": "gravacao_continua", "valor": "1"},
                       cookie=tok_admin)
        checar("o admin publica gravacao_continua=1 (201)", cod == 201 and not r.get("erro"),
               f"{cod} {str(r)[:140]}")
        cod, r = pedir("POST", f"{base}/api/config",
                       {"embarcacao_id": EMB, "camera_id": "cam-radar", "chave": "gravacao_continua", "valor": "1"},
                       cookie=tok_admin)
        checar("pedir a gravacao com camera_id e' RECUSADO (a gravacao e' do HD da maquina)",
               cod == 422 and "embarcacao" in str(r.get("erro") or ""), f"{cod} {str(r)[:140]}")
        cod, r = pedir("POST", f"{base}/api/config",
                       {"embarcacao_id": EMB, "camera_id": "", "chave": "gravacao_continua", "valor": "7"},
                       cookie=tok_admin)
        checar("valor fora de 0/1 e' RECUSADO com a lista", cod == 422 and "0" in str(r.get("erro") or ""),
               f"{cod} {str(r)[:140]}")

        cod, r = pedir("POST", f"{base}/api/config/aplicar",
                       {"camera_id": "", "chave": "gravacao_continua", "valor": "1"}, token=TOKEN)
        checar("o BORDO aplica a chave (200 e ok)", cod == 200 and r.get("ok") is True and r.get("ligada") is True,
               f"{cod} {str(r)[:180]}")
        ligada = hd / "ligada.txt"
        checar("e o DESEJO fica escrito no HD do bordo (e' o laco vivo que obedece)",
               ligada.exists() and ligada.read_text(encoding="utf-8").strip() == "1",
               f"{ligada.exists()}")
        checar("sem dispositivo de video o bordo DIZ que nao ha' o que gravar (nunca finge)",
               "dispositivo" in str(r.get("motivo") or "") and r.get("gravando") is False,
               f"{str(r.get('motivo'))[:120]}")
        cod, r = pedir("POST", f"{base}/api/config/aplicar",
                       {"camera_id": "", "chave": "gravacao_continua", "valor": "0"}, token=TOKEN)
        checar("o bordo DESLIGA (200, ligada=False)",
               cod == 200 and r.get("ok") is True and r.get("ligada") is False, f"{cod} {str(r)[:160]}")
        checar("e o desejo vira 0 no HD",
               ligada.read_text(encoding="utf-8").strip() == "0", "")

        print(f"\n   (bancada: {tmp})")
        print()
        if falhas:
            print(f"FALHOU: {len(falhas)} verificacao(oes) — {falhas}")
            return 1
        print("TUDO VERDE: o admin liga e para a camera no ao vivo (2.A), o monitoramento diz se esta' "
              "gravando a bordo, e o botao da gravacao continua viaja ate' o HD do bordo.")
        return 0
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
