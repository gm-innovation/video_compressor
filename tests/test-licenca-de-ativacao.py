#!/usr/bin/env python3
"""PROVA: a chave de licenca do PC de captura — lado TERRA (dono, 19/11/2026).

Pedido do dono, verbatim: *"quero apenas instalar o app no computador de captura, inserir a chave da
licenca e assim fazer a conexao com a empresa e embarcacao cadastradas, e a licenca pode ser
configuravel por tempo ou indeterminado"*.

Decisoes dele que esta prova mede:
  1. a chave tem o formato `XXXX-XXXX-XXXX-XXXX` e e' LEGIVEL/digitavel;
  2. o admin GERA a licenca para UMA embarcacao, com validade **indeterminada** ou **por tempo**;
  3. o admin **ve e copia a chave inteira** depois (pedido explicito do dono);
  4. `maquinas_max` e' **AJUSTAVEL** — e a licenca so' vale para o numero de PCs configurado;
  5. licenca **vencida** e licenca **revogada** NAO ativam;
  6. a chave NAO entra em log nem na auditoria (a trilha guarda a pegada, nao a chave);
  7. quem NAO e' admin nao gera, nao lista e nao ve chave nenhuma;
  8. instalacao ANTIGA (embarcacao sem licenca nenhuma) continua aceitando a captura — a licenca e'
     adicional, nada e' apagado.

Tudo por HTTP, contra um servidor de verdade em porta livre e banco em pasta temporaria. Nenhuma
chamada de rede para fora: a API sobe como LADO TERRA (sem `LECSOR_LADO_TERRA_API`).

    python tests/test-licenca-de-ativacao.py
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
BANCO = pathlib.Path(tempfile.mkdtemp(prefix="licenca-terra-")) / "pipeline.db"
TOKEN_INGESTAO = "token-de-teste-da-licenca"
EMPRESA, EMB = "armador-teste", "emb-teste"
EMB_SEM_LICENCA = "emb-sem-licenca"
EMB_ANTIGA = "emb-antiga-sem-licenca"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
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
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            return f.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def sobe_api(porta: int):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(BANCO)
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN_INGESTAO
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT", "LECSOR_LICENCA"):
        env.pop(k, None)
    # `LECSOR_SEM_AMBIENTE=1` impede que o `ground/ambiente.json` do pacote reponha o lado terra (VPS),
    # o token e o Supabase que os `pop` acima apagaram: esta prova sobe um servidor proprio e tem de
    # responder em casa, sem falar com a producao. Sem base nenhuma, este servidor E' o lado terra.
    env["LECSOR_PORTA_API"] = str(porta)
    env["LECSOR_SEM_AMBIENTE"] = "1"
    log = (BANCO.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (BANCO.parent / f"api-{porta}.log").read_text(errors="replace")[-800:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def semear() -> dict:
    con = sqlite3.connect(str(BANCO))
    con.row_factory = sqlite3.Row
    con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES (?,?)", (EMPRESA, "Armador Teste"))
    for eid, nome in ((EMB, "Embarcacao Teste"), (EMB_SEM_LICENCA, "Embarcacao Sem Licenca"),
                          (EMB_ANTIGA, "Embarcacao Instalada Sem Licenca")):
        con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES (?,?,?)", (eid, EMPRESA, nome))
    toks = {}
    for uid, email, papel in (("admin", "admin@licenca.test", "admin"),
                              ("tec", "tecnico@licenca.test", "tecnico")):
        salt = os.urandom(16).hex()
        senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
        con.execute("""INSERT OR REPLACE INTO usuarios
                       (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                       VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, None, senha, salt))
        tok = "tok-" + uid
        exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
        con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                    (tok, uid, exp, "teste"))
        toks[uid] = tok
    con.commit()
    con.close()
    return toks


def linhas(sql: str, *args) -> list[dict]:
    con = sqlite3.connect(str(BANCO))
    con.row_factory = sqlite3.Row
    try:
        return [dict(x) for x in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def main() -> int:
    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    proc = sobe_api(porta)
    toks = semear()
    try:
        print("\n== 1. quem NAO e' admin nao gera, nao lista e nao ve chave ==")
        c, j = pedir("GET", f"{base}/api/licencas")
        exigir(c == 403, f"sem login nao lista licencas -> {c} (esperado 403)")
        c, j = pedir("GET", f"{base}/api/licencas", cookie=toks["tec"])
        exigir(c == 403, f"tecnico nao lista licencas -> {c} (esperado 403)")
        c, j = pedir("POST", f"{base}/api/licencas", {"embarcacao_id": EMB}, cookie=toks["tec"])
        exigir(c == 403, f"tecnico nao gera licenca -> {c} (esperado 403)")

        print("\n== 2. o admin gera a licenca para UMA embarcacao (indeterminada) ==")
        c, criada = pedir("POST", f"{base}/api/licencas",
                          {"embarcacao_id": EMB, "validade_tipo": "indeterminada", "maquinas_max": 1},
                          cookie=toks["admin"])
        exigir(c == 201, f"admin gera licenca -> {c} (esperado 201) {json.dumps(criada)[:120]}")
        chave = str(criada.get("chave") or "")
        exigir(bool(re.fullmatch(r"[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}", chave)),
               f"a chave tem o formato XXXX-XXXX-XXXX-XXXX (veio {chave!r})")
        exigir(not any(ch in chave for ch in "IO"), "a chave nao usa I nem O (nao se confunde com 1 e 0)")
        exigir(criada.get("validade_tipo") == "indeterminada" and criada.get("validade_em") == "",
               "a licenca indeterminada nao tem data")
        ident = criada["id"]

        print("\n== 3. o admin VE e COPIA a chave inteira depois (pedido do dono) ==")
        c, lista = pedir("GET", f"{base}/api/licencas", cookie=toks["admin"])
        exigir(c == 200, f"admin lista licencas -> {c} (esperado 200)")
        item = next((x for x in (lista.get("licencas") or []) if x["id"] == ident), None)
        exigir(item is not None, "a licenca criada aparece na lista")
        if item:
            exigir(item["chave"] == chave, "a lista traz a CHAVE INTEIRA para o admin copiar de novo")
            exigir(item["chave_ultimos4"] == chave.replace("-", "")[-4:], "os 4 ultimos tambem vem")
            exigir(item["embarcacao_nome"] == "Embarcacao Teste" and item["cliente_nome"] == "Armador Teste",
                   "a lista diz a embarcacao e a empresa (o vinculo que a chave faz)")
            exigir(item["estado"] == "ativa" and not item["bloqueada"], "estado inicial: ativa")

        print("\n== 4. ativacao: chave errada, chave malformada e chave certa ==")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": "AAAA-BBBB-CCCC-DDDD", "maquina": "pc-1"})
        exigir(c == 404, f"chave inexistente nao ativa -> {c} (esperado 404)")
        exigir("encontrada" in json.dumps(j, ensure_ascii=False), "a resposta diz que nao encontrou (sem vazar nada)")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": "1234-ABCD", "maquina": "pc-1"})
        exigir(c == 422, f"chave malformada -> {c} (esperado 422)")
        c, ativ = pedir("POST", f"{base}/api/licenca/ativar", {"chave": chave.lower(), "maquina": "pc-1"})
        exigir(c == 200, f"chave certa (digitada em minusculas) ativa -> {c} (esperado 200) {json.dumps(ativ)[:160]}")
        lic = ativ.get("licenca") or {}
        exigir(lic.get("embarcacao_id") == EMB, "a ativacao devolve a EMBARCACAO cadastrada")
        exigir(lic.get("embarcacao_nome") == "Embarcacao Teste", "a ativacao devolve o NOME da embarcacao")
        exigir(lic.get("cliente_nome") == "Armador Teste", "a ativacao devolve a EMPRESA (cliente)")
        exigir(lic.get("maquinas") == 1, "a ativacao conta 1 PC usando a licenca")

        print("\n== 5. `maquinas_max` e' ajustavel e conta PC ==")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": chave, "maquina": "pc-2"})
        exigir(c == 409, f"2o PC com maquinas_max=1 e' recusado -> {c} (esperado 409)")
        exigir(j.get("maquinas_max") == 1 and (j.get("dica") or ""), "a recusa diz o limite e o que fazer")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": chave, "maquina": "pc-1"})
        exigir(c == 200, f"o MESMO PC pode reativar (nao soma maquina) -> {c} (esperado 200)")
        c, j = pedir("POST", f"{base}/api/licencas/{ident}/atualizar",
                     {"maquinas_max": 2}, cookie=toks["admin"])
        exigir(c == 200 and j.get("maquinas_max") == 2, f"admin aumenta para 2 PCs -> {c} {json.dumps(j)[:100]}")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": chave, "maquina": "pc-2"})
        exigir(c == 200, f"agora o 2o PC ativa -> {c} (esperado 200)")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": chave, "maquina": "pc-3"})
        exigir(c == 409, f"o 3o PC ainda e' recusado -> {c} (esperado 409)")
        itens = linhas("SELECT maquina FROM licenca_usos WHERE licenca_id=?", ident)
        exigir({x["maquina"] for x in itens} == {"pc-1", "pc-2"}, "o banco registra QUAIS PCs usam a licenca")

        print("\n== 6. licenca por TEMPO: vence e para de ativar ==")
        amanha = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        c, por_tempo = pedir("POST", f"{base}/api/licencas",
                             {"embarcacao_id": EMB_SEM_LICENCA, "validade_tipo": "ate", "validade_em": amanha,
                              "maquinas_max": 1}, cookie=toks["admin"])
        exigir(c == 201, f"licenca com prazo (ate amanha) -> {c} (esperado 201)")
        c, j = pedir("POST", f"{base}/api/licencas",
                     {"embarcacao_id": EMB, "validade_tipo": "ate", "validade_em": "2020-01-01"},
                     cookie=toks["admin"])
        exigir(c == 422, f"data no passado e' recusada na criacao -> {c} (esperado 422)")
        onte = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        c, j = pedir("POST", f"{base}/api/licencas/{por_tempo['id']}/atualizar",
                     {"validade_em": onte}, cookie=toks["admin"])
        exigir(c == 200, f"admin muda a data para ontem -> {c} (esperado 200)")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": por_tempo["chave"], "maquina": "pc-x"})
        exigir(c == 403, f"licenca VENCIDA nao ativa -> {c} (esperado 403)")
        exigir("vencida" in json.dumps(j, ensure_ascii=False).lower(), "a resposta diz que venceu")

        print("\n== 7. revogar, reativar e reemitir ==")
        c, j = pedir("POST", f"{base}/api/licencas/{ident}/revogar", {"motivo": "teste de revogacao"},
                     cookie=toks["admin"])
        exigir(c == 200 and j.get("status") == "revogada", f"admin revoga -> {c} {json.dumps(j)[:100]}")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": chave, "maquina": "pc-1"})
        exigir(c == 403, f"licenca REVOGADA nao ativa -> {c} (esperado 403)")
        exigir("revogada" in json.dumps(j, ensure_ascii=False).lower(), "a resposta diz que foi revogada")
        c, j = pedir("POST", f"{base}/api/licencas/{ident}/reativar", {}, cookie=toks["admin"])
        exigir(c == 200 and j.get("status") == "ativa", f"admin reativa -> {c}")
        c, j = pedir("POST", f"{base}/api/licencas/{ident}/reemitir", {}, cookie=toks["admin"])
        exigir(c == 200 and j.get("chave"), f"admin gera OUTRA chave -> {c}")
        nova = j.get("chave")
        exigir(nova != chave, "a chave nova e' diferente da antiga")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": chave, "maquina": "pc-1"})
        exigir(c == 404, f"a chave ANTIGA para de funcionar -> {c} (esperado 404)")
        c, j = pedir("POST", f"{base}/api/licenca/ativar", {"chave": nova, "maquina": "pc-9"})
        exigir(c == 200, f"a chave NOVA ativa -> {c} (esperado 200)")
        exigir(len(linhas("SELECT * FROM licenca_usos WHERE licenca_id=?", ident)) == 1,
               "reemitir limpa a contagem de PCs (a licenca recomeca do zero)")

        print("\n== 8. a chave NAO vaza: nem em log, nem na auditoria ==")
        auditoria = linhas("SELECT acao, alvo FROM auditoria_acesso ORDER BY id")
        exigir(any(x["acao"] == "criar_licenca" for x in auditoria), "a criacao da licenca fica na auditoria")
        exigir(not any(chave in (x["alvo"] or "") or chave in (x["acao"] or "") for x in auditoria),
               "a auditoria NAO guarda a chave (guarda a pegada)")
        exigir(any("pegada" not in (x["alvo"] or "") and len(x["alvo"] or "") > 10 for x in auditoria),
               "a auditoria registra o evento da licenca com identificacao da pegada")
        texto_log = ""
        for p in BANCO.parent.glob("api-*.log"):
            texto_log += p.read_text(errors="replace")
        exigir(chave not in texto_log, "a chave nao aparece no log da API do lado terra")
        exigir(nova not in texto_log, "a chave reemitida tambem nao aparece no log")

        print("\n== 9. instalacao ANTIGA (embarcacao sem licenca) continua capturando ==")
        c, j = pedir("POST", f"{base}/api/cameras/anuncio",
                     {"id": "cam-antiga", "fluxo_id": "fluxo-antigo", "rotulo": "antiga",
                      "embarcacao_id": EMB_ANTIGA}, token=TOKEN_INGESTAO)
        exigir(c in (200, 201), f"barco SEM licenca nenhuma continua aceito (instalacao antiga) -> {c}")
        c, j = pedir("POST", f"{base}/api/licencas/{ident}/revogar", {"motivo": "fim da prova"},
                     cookie=toks["admin"])
        exigir(c == 200, f"admin revoga de novo a licenca do barco -> {c}")
        c, j = pedir("POST", f"{base}/api/cameras/anuncio",
                     {"id": "cam-emb-teste", "fluxo_id": "fluxo-emb-teste", "rotulo": "cam",
                      "embarcacao_id": EMB}, token=TOKEN_INGESTAO)
        exigir(c == 403, f"com a licenca REVOGADA o lado terra RECUSA a captura daquele barco -> {c}")
        exigir("licenca" in json.dumps(j, ensure_ascii=False).lower(),
               "e a recusa diz que foi a licenca (o admin e' avisado pelo motivo)")
        c, j = pedir("POST", f"{base}/api/cameras/anuncio",
                     {"id": "cam-antiga", "fluxo_id": "fluxo-antigo", "rotulo": "antiga",
                      "embarcacao_id": EMB_ANTIGA}, token=TOKEN_INGESTAO)
        exigir(c in (200, 201), f"o barco sem licenca NADA sofre com a revogacao do outro -> {c}")
        c, j = pedir("GET", f"{base}/api/cameras", {"embarcacao_id": EMB})
        exigir("licenca" not in json.dumps(j, ensure_ascii=False).lower(),
               "a lista de cameras nao despeja detalhe de licenca para quem consulta")

        print("\n== 10. migracao: as tabelas existem em banco NOVO ==")
        tabelas = {x["name"] for x in linhas("SELECT name FROM sqlite_master WHERE type='table'")}
        exigir({"licencas", "licenca_usos"} <= tabelas, "banco novo ja' nasce com `licencas` e `licenca_usos`")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()

    if falhas:
        print(f"\nRESULTADO: {len(falhas)} falha(s):")
        for f in falhas:
            print("  - " + f)
        return 1
    print("\nRESULTADO: tudo passou — a licenca do PC de captura funciona no lado terra "
          "(gerar, ver/copiar, prazo ou indeterminada, nº de PCs ajustavel, vencida/revogada cortam, "
          "sem vazar a chave).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
