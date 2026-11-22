#!/usr/bin/env python3
"""PROVA: a licenca do PC de captura — lado BORDO (dono, 19/11/2026).

O pedido do dono, verbatim: *"quero apenas instalar o app no computador de captura, inserir a chave da
licenca e assim fazer a conexao com a empresa e embarcacao cadastradas, e a licenca pode ser
configuravel por tempo ou indeterminado"*. E a arquitetura de comando (19/11/2026): *"a unica certeza e'
de que ele podera' enviar"* — o bordo PERGUNTA, terra responde; nada entra pelo bordo.

Esta prova levanta DOIS servidores de verdade em portas livres: um LADO TERRA (banco proprio + admin) e
um PC DE CAPTURA (banco proprio + arquivo de licenca em pasta temporaria), e mede:

  1. recem-instalado, o bordo diz a verdade: nao foi ativado;
  2. com a chave digitada, o bordo ATIVA e GRAVA o vinculo local (embarcacao + empresa);
  3. `licenca.embarcacao()` — a fonte que a varredura, o repasse e a telemetria usam — passa a devolver
     a embarcacao da LICENCA (era o `ambiente.json` do pacote);
  4. a tela `/licenca` e' servida pelo PROPRIO bordo (abre sem internet);
  5. chave errada NAO ativa (e a recusa vem de terra, sem vazar nada);
  6. `/api/licencas` (plural) e' rota do TERRA — o bordo nao tem painel de licenca;
  7. SEM REDE o bordo mantem tudo normalmente: nao muda o vinculo, nao para a captura (decisao do dono);
  8. REVOGACAO feita depois da ativacao CHEGA ao bordo pela conferencia de saida: a transmissao PARA e
     a tela diz por que;
  9. nem o vinculo local nem a auditoria guardam o valor da chave.

    python tests/test-licenca-do-bordo.py
"""
from __future__ import annotations

import datetime as dt
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

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
PASTA = pathlib.Path(tempfile.mkdtemp(prefix="licenca-bordo-"))
BANCO_TERRA = PASTA / "terra" / "pipeline.db"
BANCO_BORDO = PASTA / "bordo" / "pipeline.db"
ARQ_LICENCA = PASTA / "bordo" / "licenca.json"
EMPRESA, EMB = "armador-teste", "emb-teste"
CAM = "cam-teste"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(metodo, url, corpo=None, cookie=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            return f.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {"texto": b.decode("utf-8", "replace")}


def pedir_html(url):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as f:
        return f.status, f.read().decode("utf-8", "replace")


def sobe(porta: int, banco: pathlib.Path, extra: dict, nome: str):
    """Sobe `ground/api.py` de verdade, isolado: banco proprio, log proprio, ambiente controlado."""
    env = dict(os.environ)
    for k in ("LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT", "LECSOR_LICENCA",
              "LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY"):
        env.pop(k, None)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_PORTA_API": str(porta), "LECSOR_SEM_AMBIENTE": "1",
                "LECSOR_TOKEN_INGESTAO": "token-de-teste", "PYTHONIOENCODING": "utf-8", **extra})
    banco.parent.mkdir(parents=True, exist_ok=True)
    log = (PASTA / f"{nome}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError(f"{nome} saiu: " + (PASTA / f"{nome}.log").read_text(errors="replace")[-800:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError(f"{nome} nao subiu")


def semear_terra() -> str:
    con = sqlite3.connect(str(BANCO_TERRA))
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Armador Teste"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "Embarcacao Teste"))
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios
                   (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES ('admin','admin@licenca.test','admin','admin',NULL,?,?,200000,1)""", (senha, salt))
    tok = "tok-admin"
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, "admin", exp, "teste"))
    con.commit()
    con.close()
    return tok


def semear_bordo() -> None:
    """Uma camera LIGADA no PC de captura — e' ela que tem de PARAR se a licenca cair."""
    con = sqlite3.connect(str(BANCO_BORDO))
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Armador Teste"))
    con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)",
                (EMB, EMPRESA, "Embarcacao Teste"))
    con.execute("""INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,ativo)
                   VALUES (?,?,?,?,1)""", (CAM, EMB, "cam de prova", "fluxo-cam-teste"))
    con.commit()
    con.close()


def linhas(banco: pathlib.Path, sql: str, *args) -> list[dict]:
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        return [dict(x) for x in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def main() -> int:
    p_terra, p_bordo = porta_livre(), porta_livre()
    base_terra, base_bordo = f"http://127.0.0.1:{p_terra}", f"http://127.0.0.1:{p_bordo}"
    # O LADO TERRA se reconhece como "esta maquina" (porta propria) e nao encaminha para si mesmo.
    terra = sobe(p_terra, BANCO_TERRA, {}, "terra")   # sem base = ESTE e' o lado terra
    toks = semear_terra()
    bordo = None
    try:
        c, criada = pedir("POST", f"{base_terra}/api/licencas",
                          {"embarcacao_id": EMB, "validade_tipo": "indeterminada", "maquinas_max": 2},
                          cookie=toks)
        chave = criada.get("chave") or ""
        exigir(c == 201 and bool(chave), f"TERRA: admin gerou a chave da embarcacao -> {c}")

        # O PC DE CAPTURA: enxerga o terra, guarda o vinculo em pasta temporaria.
        bordo = sobe(p_bordo, BANCO_BORDO,
                     {"LECSOR_LADO_TERRA_API": base_terra, "LECSOR_LICENCA": str(ARQ_LICENCA)}, "bordo")
        semear_bordo()

        print("\n== 1. recem-instalado, o bordo diz a verdade ==")
        c, j = pedir("GET", f"{base_bordo}/api/licenca")
        exigir(c == 200 and j.get("tem") is False and j.get("ativada") is False,
               f"o app novo responde 'nao ativada' -> {c} {json.dumps(j, ensure_ascii=False)[:120]}")
        exigir(not ARQ_LICENCA.exists(), "nenhum vinculo gravado antes de digitar a chave")

        print("\n== 2. o usuario digita a chave e o bordo ativa ==")
        c, j = pedir("POST", f"{base_bordo}/api/licenca/ativar", {"chave": chave.lower()})
        exigir(c == 200 and j.get("ok") and j.get("guardado"),
               f"digitar a chave (em minusculas) ativa a maquina -> {c} {json.dumps(j, ensure_ascii=False)[:120]}")
        exigir(ARQ_LICENCA.exists(), "o vinculo foi gravado no PC de captura (sobrevive a atualizacao do app)")
        guardado = json.loads(ARQ_LICENCA.read_text(encoding="utf-8"))
        exigir(guardado.get("embarcacao_id") == EMB, "o vinculo local aponta para a EMBARCACAO cadastrada")
        exigir(guardado.get("cliente_nome") == "Armador Teste", "o vinculo local traz a EMPRESA")
        exigir(guardado.get("status") == "ativa" and guardado.get("maquina"), "status ativa + a maquina identificada")

        print("\n== 3. quem manda agora e' a licenca (varredura, repasse, telemetria) ==")
        r = subprocess.run([sys.executable, "-c", "import licenca;print(licenca.embarcacao())"],
                           cwd=str(RAIZ / "ground"), capture_output=True, text=True,
                           env={**os.environ, "LECSOR_LICENCA": str(ARQ_LICENCA),
                                "LECSOR_EMBARCACAO": "bancada-do-pacote"})
        exigir(r.stdout.strip() == EMB,
               f"`licenca.embarcacao()` devolve a licenca, nao o ambiente.json ({r.stdout.strip()!r})")
        c, j = pedir("GET", f"{base_bordo}/api/licenca")
        exigir(j.get("embarcacao_id") == EMB and j.get("embarcacao_nome") == "Embarcacao Teste",
               "a tela do bordo mostra a embarcacao e o nome")
        exigir(j.get("cliente_nome") == "Armador Teste", "e mostra a empresa dona do barco")
        exigir(j.get("bloqueada") is False and "sem prazo" in (j.get("texto") or ""),
               f"diz que esta' ativa e sem prazo ({j.get('texto')!r})")

        print("\n== 4. a tela da chave e' servida pelo PROPRIO bordo ==")
        c, html = pedir_html(f"{base_bordo}/licenca")
        exigir(c == 200 and "Chave de licença" in html, f"GET /licenca no bordo -> {c} (abre sem internet)")
        exigir("XXXX-XXXX-XXXX-XXXX" in html, "a tela ensina o formato da chave")
        exigir("LECSOR" in html or "licença" in html.lower(), "e' a tela da licenca da LECSOR")

        print("\n== 5. chave errada nao ativa ==")
        c, j = pedir("POST", f"{base_bordo}/api/licenca/ativar", {"chave": "ZZZZ-ZZZZ-ZZZZ-ZZZZ"})
        exigir(c == 403, f"chave que nao existe nao ativa -> {c} (esperado 403)")
        exigir("encontrada" in json.dumps(j, ensure_ascii=False), "a recusa diz que a chave nao foi encontrada")
        exigir(json.loads(ARQ_LICENCA.read_text(encoding="utf-8")).get("chave") == chave,
               "o vinculo BOM continua gravado (recusa nao estraga a maquina que ja' estava ativa)")

        print("\n== 6. /api/licencas (plural) e' rota do TERRA ==")
        c, j = pedir("GET", f"{base_bordo}/api/licencas")
        exigir(c in (401, 403), f"o bordo NAO tem painel de licenca (encaminha e terra recusa) -> {c}")
        c, j = pedir("GET", f"{base_bordo}/api/licencas", cookie=toks)
        exigir(c == 200, f"o MESMO caminho, com o admin do terra, lista -> {c}")

        print("\n== 7. SEM REDE o bordo mantem tudo normalmente (decisao do dono) ==")
        antes = ARQ_LICENCA.read_bytes()
        terra.terminate()
        try:
            terra.wait(timeout=10)
        except Exception:  # noqa: BLE001
            terra.kill()
        c, j = pedir("GET", f"{base_bordo}/api/licenca")
        exigir(c == 200 and j.get("tem") is True, f"com o terra fora do ar a tela continua respondendo -> {c}")
        exigir(j.get("bloqueada") is False, "SEM REDE a licenca NAO e' cortada")
        exigir(j.get("sem_rede") is True, "e a tela diz que nao falou com terra agora")
        exigir("captura segue" in (j.get("nota") or ""), f"a nota explica a regra do dono ({j.get('nota')!r})")
        exigir(ARQ_LICENCA.read_bytes() == antes, "o vinculo local nem foi tocado pela falta de rede")

        print("\n== 8. a REVOGACAO feita depois chega ao bordo e PARA a transmissao ==")
        terra = sobe(p_terra, BANCO_TERRA, {}, "terra")
        ligadas_antes = {x["id"] for x in linhas(BANCO_BORDO, "SELECT id FROM cameras WHERE ativo=1")}
        c, j = pedir("POST", f"{base_terra}/api/licencas/{criada['id']}/revogar", {"motivo": "contrato encerrado"},
                     cookie=toks)
        exigir(c == 200 and j.get("status") == "revogada", f"TERRA: admin revogou -> {c}")
        c, j = pedir("GET", f"{base_bordo}/api/licenca")
        exigir(j.get("bloqueada") is True, "o bordo percebe a revogacao pela conferencia de saida (sem porta aberta)")
        exigir("revogada" in (j.get("texto") or "").lower(), f"a tela diz que foi revogada ({j.get('texto')!r})")
        paradas = j.get("paradas") or []
        exigir(CAM in paradas, f"a transmissao desta camera PAROU: {paradas}")
        exigir(set(paradas) == ligadas_antes,
               f"e pararam TODAS as que estavam ligadas ({sorted(ligadas_antes)}), nenhuma ficou de pe'")
        exigir(json.loads(ARQ_LICENCA.read_text(encoding="utf-8")).get("status") == "revogada",
               "o vinculo local guardou o estado novo")
        c, j = pedir("POST", f"{base_bordo}/api/licenca/ativar", {"chave": chave})
        exigir(c == 403, f"a maquina nao 'reativa' sozinha com a chave revogada -> {c}")
        exigir("revogada" in json.dumps(j, ensure_ascii=False).lower(), "e a recusa diz que a licenca foi revogada")

        print("\n== 9. a chave nao fica guardada em log nem na auditoria ==")
        auditoria = linhas(BANCO_BORDO, "SELECT acao, alvo FROM auditoria_acesso ORDER BY id")
        acoes = {x["acao"] for x in auditoria}
        exigir("licenca_guardada_no_bordo" in acoes, "o bordo auditora a ativacao")
        exigir("captura_parada_por_licenca" in acoes, "e auditora a captura que parou por licenca")
        exigir(not any(chave in json.dumps(x, ensure_ascii=False) for x in auditoria),
               "a auditoria do bordo NAO guarda a chave (so' a pegada)")
        texto = "".join((PASTA / f"{n}.log").read_text(errors="replace") for n in ("terra", "bordo"))
        exigir(chave not in texto, "a chave nao aparece no log de nenhum dos dois lados")
    finally:
        for p in (terra, bordo):
            if p is None:
                continue
            try:
                p.terminate()
                p.wait(timeout=10)
            except Exception:  # noqa: BLE001
                p.kill()

    if falhas:
        print(f"\nRESULTADO: {len(falhas)} falha(s):")
        for f in falhas:
            print("  - " + f)
        return 1
    print("\nRESULTADO: tudo passou — instalar, digitar a chave e a maquina ja' e' do barco certo (e da "
          "empresa certa); sem rede nada para; revogacao chega e para a transmissao; a chave nao vira log.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
