#!/usr/bin/env python3
"""PROVA VIVA: a licenca funciona no LADO TERRA QUE ESTA' NO AR (VPS, rodada 0.10.0).

Esta prova roda **no host da VPS** (nao no PC): ela fala com a API de producao
(`http://127.0.0.1:8085`) e com o banco de producao, provando o que as provas de bancada nao provam —
que a 0.10.0 esta' de fato publicada e comporta-se igual na VPS:

  1. a tabela `licencas` existe (o `db/schema-fase7.sql` foi aplicado no restart);
  2. sem sessao, `POST /api/licencas` NAO gera (403) — so' o admin;
  3. o admin entra, gera a licenca de uma embarcacao e recebe a chave legivel `XXXX-XXXX-XXXX-XXXX`;
  4. o admin LE'/COPIA a chave inteira de novo quantas vezes quiser (lista), e o banco guarda a chave;
  5. a trilha de auditoria registra a acao COM A PEGADA e SEM a chave em texto;
  6. a pagina `/licenca` (a tela que o PC de captura mostra) e' servida.

Limpeza: no fim, a licenca criada pela prova e' REVOGADA e a linha e' apagada (o dono exige limpeza do que
a campanha inseriu); as linhas de auditoria permanecem — elas sao a trilha imutavel do que aconteceu.

    scp tests/prova-viva-licenca-no-terra.py root@187.127.60.250:/root/
    ssh root@187.127.60.250 'python3 /root/prova-viva-licenca-no-terra.py'
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import pathlib
import sqlite3
import sys
import urllib.error
import urllib.request

RAIZ = pathlib.Path("/opt/pipeline/app")
BASE = "http://127.0.0.1:8085"
BANCO = RAIZ / "db" / "pipeline.db"
falhas: list[str] = []


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def senha_do_admin() -> str:
    for nome in ("ground/.env.local", "ground/.env"):
        arq = RAIZ / nome
        if not arq.exists():
            continue
        for linha in arq.read_text(encoding="utf-8", errors="replace").splitlines():
            if linha.strip().startswith("LECSOR_SENHA_DEMO="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def abre():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def pedir(aberto, metodo, caminho, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    req = urllib.request.Request(BASE + caminho, data=dados, method=metodo, headers=cab)
    def corpo(b: bytes, status: int):
        """Rota que devolve HTML (`/licenca`) nao pode derrubar a prova."""
        try:
            return status, (json.loads(b) if b else {})
        except Exception:  # noqa: BLE001
            return status, {"_html_bytes": len(b)}

    try:
        with aberto.open(req, timeout=60) as f:
            return corpo(f.read(), f.status)
    except urllib.error.HTTPError as e:
        return corpo(e.read() or b"{}", e.code)


def main() -> int:
    con = sqlite3.connect(str(BANCO))
    tabelas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    exigir("licencas" in tabelas and "licenca_usos" in tabelas,
           "a 0.10.0 esta' no ar: as tabelas `licencas`/`licenca_usos` existem no banco de producao")
    linha = con.execute("SELECT id, nome FROM embarcacoes ORDER BY id LIMIT 1").fetchone()
    exigir(bool(linha), f"ha' embarcacao cadastrada para a prova: {linha}")
    if not linha:
        return 1
    emb, nome_emb = linha

    anon, _ = abre()
    c, _ = pedir(anon, "POST", "/api/licencas", {"embarcacao_id": emb})
    exigir(c in (401, 403), f"sem sessao, gerar licenca e' recusado ({c}) — so' o admin")

    senha = senha_do_admin()
    if not senha:
        print("FALHA nao achei a senha de demonstracao em ground/.env.local (nao imprimo o valor)")
        return 1
    aberto, jar = abre()
    c, r = pedir(aberto, "POST", "/api/entrar", {"email": "admin@lecsor.test", "senha": senha})
    exigir(c == 200 and bool(jar), f"o admin entrou na API de producao ({c}, sessao={'sim' if jar else 'nao'})")

    c, criada = pedir(aberto, "POST", "/api/licencas",
                      {"embarcacao_id": emb, "validade_tipo": "indeterminada", "maquinas_max": 1})
    chave = str(criada.get("chave") or "")
    exigir(c == 201 and len(chave) == 19 and chave.count("-") == 3,
           f"o admin gerou a licenca de `{nome_emb}` e a chave veio legivel: {chave}")

    c, lista = pedir(aberto, "GET", "/api/licencas")
    de_novo = [x for x in (lista.get("licencas") or []) if str(x.get("id")) == str(criada.get("id"))]
    exigir(c == 200 and bool(de_novo) and de_novo[0].get("chave") == chave,
           "o admin le'/copia a chave inteira de novo pela lista (decisao D4 do dono)")

    guardada = con.execute("SELECT chave, status FROM licencas WHERE id=?", (criada.get("id"),)).fetchone()
    exigir(bool(guardada) and guardada[0] == chave,
           "o banco de producao guarda a chave vigente (e' de onde o admin copia)")

    pegada = hashlib.sha256(chave.replace("-", "").encode()).hexdigest()[:16]
    trilha = con.execute("SELECT acao, alvo FROM auditoria_acesso ORDER BY id DESC LIMIT 40").fetchall()
    texto = json.dumps(trilha, ensure_ascii=False)
    exigir(chave not in texto, "a auditoria NAO guarda a chave em texto")
    exigir(pegada in texto or any("licenca" in str(a) for a, _ in trilha),
           "a auditoria registra a acao da licenca (com a pegada)")

    c, pagina = pedir(anon, "GET", "/licenca")
    exigir(c == 200, f"a tela da chave (`/licenca`) e' servida na VPS ({c})")

    print("\n== limpeza do que a prova inseriu ==")
    pedir(aberto, "POST", f"/api/licencas/{criada.get('id')}/revogar", {"motivo": "prova viva 0.10.0"})
    con.execute("DELETE FROM licencas WHERE id=?", (criada.get("id"),))
    con.commit()
    sobraram = con.execute("SELECT COUNT(*) FROM licencas WHERE id=?", (criada.get("id"),)).fetchone()[0]
    exigir(sobraram == 0, "a licenca da prova foi revogada e a linha apagada (a trilha de auditoria ficou)")
    n_aud = con.execute("SELECT COUNT(*) FROM auditoria_acesso").fetchone()[0]
    print(f"     (a auditoria tem {n_aud} linhas; as da prova permanecem — trilha imutavel, por decisao do dono)")
    con.close()

    if falhas:
        print(f"\nRESULTADO: {len(falhas)} falha(s):")
        for f in falhas:
            print("  - " + f)
        return 1
    print("\nRESULTADO: tudo passou — a licenca 0.10.0 esta' viva no lado terra de producao.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
