#!/usr/bin/env python3
"""Teste da leitura do Supabase pelo servidor em terra (sem rede).

Regras que este teste protege:
1. sem `LECSOR_SUPABASE_URL`/`LECSOR_SUPABASE_SERVICE_KEY` o modulo diz `configurado: False` e nao
   levanta — a tela do produto nao pode cair por causa da integracao;
2. com as variaveis, a leitura devolve producao e disponibilidade da view;
3. erro de rede/HTTP vira campo `erro`, nunca excecao;
4. o cache curto evita bater no Supabase a cada requisicao.
"""
import json
import os
import sys

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))
os.chdir(RAIZ)
import supabase_leitura as S  # noqa: E402


class RespostaFalsa:
    def __init__(self, corpo: str):
        self._corpo = corpo.encode()

    def read(self) -> bytes:
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def main() -> int:
    falhas = []

    # 1) sem configuracao
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_SERVICE_KEY"):
        os.environ.pop(k, None)
    S._CACHE["dados"] = None
    r = S.resumo(validade_s=0)
    if r.get("configurado") is not False or not r.get("erro"):
        falhas.append(f"sem configuracao esperava configurado=False com erro; veio {r}")
    print(f"1) sem configuracao: configurado={r.get('configurado')} erro={str(r.get('erro'))[:60]}")

    # 2) com configuracao e resposta falsa
    os.environ["LECSOR_SUPABASE_URL"] = "https://exemplo.supabase.co"
    os.environ["LECSOR_SUPABASE_SERVICE_KEY"] = "chave-de-teste"
    chamadas = {"n": 0}
    producao = [{"fluxo_id": "cam-01", "compressao_medio_pct": 99.06, "mb_enviados": 774.95,
                 "horas_streaming": 0.55, "banda_utilizada_mbps": 3.126}]
    disponibilidade = [{"fluxo_id": "cam-01", "minutos_no_ar": 344, "disponibilidade_pct": 0.796}]

    def urlopen_falso(pedido, timeout=None):
        chamadas["n"] += 1
        url = pedido.full_url if hasattr(pedido, "full_url") else str(pedido)
        if "v_producao_30d" in url:
            return RespostaFalsa(json.dumps(producao))
        if "v_disponibilidade_30d" in url:
            return RespostaFalsa(json.dumps(disponibilidade))
        return RespostaFalsa("[]")

    original = S.urllib.request.urlopen
    S.urllib.request.urlopen = urlopen_falso
    try:
        S._CACHE["dados"] = None
        r = S.resumo(validade_s=60)
        if r.get("erro"):
            falhas.append(f"leitura com resposta boa marcou erro: {r['erro']}")
        if not r.get("producao") or r["producao"][0]["banda_utilizada_mbps"] != 3.126:
            falhas.append(f"producao nao veio como esperado: {r.get('producao')}")
        if not r.get("disponibilidade") or r["disponibilidade"][0]["minutos_no_ar"] != 344:
            falhas.append(f"disponibilidade nao veio como esperado: {r.get('disponibilidade')}")
        print(f"2) com configuracao: producao={len(r['producao'])} disponibilidade={len(r['disponibilidade'])} "
              f"chamadas={chamadas['n']}")
        # 3) cache: segunda leitura nao chama o Supabase de novo
        antes = chamadas["n"]
        S.resumo(validade_s=60)
        if chamadas["n"] != antes:
            falhas.append(f"cache nao funcionou: {antes} -> {chamadas['n']} chamadas")
        print(f"3) cache: chamadas apos a 2a leitura = {chamadas['n']} (antes {antes})")

        # 4) erro HTTP vira campo 'erro', sem excecao
        def urlopen_erro(pedido, timeout=None):
            raise S.urllib.error.URLError("sem rede")

        S.urllib.request.urlopen = urlopen_erro
        S._CACHE["dados"] = None
        r = S.resumo(validade_s=0)
        if not r.get("erro"):
            falhas.append(f"erro de rede deveria virar campo 'erro'; veio {r}")
        print(f"4) erro de rede: erro={str(r.get('erro'))[:70]}")
    finally:
        S.urllib.request.urlopen = original

    if falhas:
        for f in falhas:
            print("[FALHA]", f)
        return 1
    print("[ok] leitura do Supabase: sem configuracao, com configuracao, cache e erro cobrem o modulo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
