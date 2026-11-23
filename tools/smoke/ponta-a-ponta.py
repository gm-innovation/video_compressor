#!/usr/bin/env python3
"""SMOKE DE PONTA A PONTA do pipeline bordo -> terra -> tela.

O que este comando responde, com numero medido: *o sistema realmente funciona como esperado?* — acao do
usuario -> comando real de midia -> efeito medido -> evidencia guardada. Nao e' teste de integridade
("a tela abriu e nao quebrou"): cada jornada precisa de um NUMERO (fps, Mbps, latencia, tempo de
subida/parada) e de uma evidencia em disco. Sem medida, a jornada e' "NAO MEDIDA" — nunca "OK".

    python tools/smoke/ponta-a-ponta.py --rapido                  # J1+J2 (antes de cada commit)
    python tools/smoke/ponta-a-ponta.py --jornadas 1,2,3,4,6      # a bancada inteira
    python tools/smoke/ponta-a-ponta.py --modo producao \\
        --terra https://... --bordo http://... --jornadas 1,2     # contra a VPS + o PC de captura

Saida: `smoke/saida/<AAAA-MM-DD>/j<N>/{resultado.json,qa.md}` e `smoke/saida/<AAAA-MM-DD>/RESUMO.md`.
Codigo de saida: 0 = tudo OK (ou OK com ressalvas), 1 = alguma FALHA, 2 = nada foi medido.
"""
from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import subprocess
import sys
import time

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path.insert(0, str(AQUI))

from ambiente import Ambiente, chromium  # noqa: E402
from relatorio import qualidade, resumo_geral  # noqa: E402

MODULOS = {
    1: "jornadas.j1_vinculo",
    2: "jornadas.j2_ao_vivo",
    3: "jornadas.j3_sai_e_para",
    4: "jornadas.j4_dois_clientes",
    5: "jornadas.j5_gravacao_baixa_e_apaga",
    6: "jornadas.j6_radar_hd",
    7: "jornadas.j7_escopos",
    8: "jornadas.j8_admin_manda",
    9: "jornadas.j9_defeito_e_saude",
    10: "jornadas.j10_licenca_revogada",
}


def commit_atual() -> str:
    try:
        r = subprocess.run(["git", "-C", str(RAIZ), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def principal() -> int:
    p = argparse.ArgumentParser(description="smoke de ponta a ponta (bordo -> terra -> tela)")
    p.add_argument("--modo", default="bancada", choices=("bancada", "producao"))
    p.add_argument("--jornadas", default="", help="quais jornadas rodar (ex.: 1,2,3,4)")
    p.add_argument("--rapido", action="store_true", help="J1+J2 (o que roda antes de cada commit)")
    p.add_argument("--saida", default="", help="pasta da evidencia (padrao: smoke/saida)")
    p.add_argument("--terra", default="", help="lado terra pronto (producao ou bancada ja' no ar)")
    p.add_argument("--bordo", default="", help="bordo pronto (producao: o PC de captura)")
    p.add_argument("--embarcacao", default="bancada")
    p.add_argument("--cliente", default="lecsor")
    p.add_argument("--camera", default="cam-01")
    p.add_argument("--sem-navegador", action="store_true", help="nao abrir o Chromium (jornadas sem tela)")
    args = p.parse_args()

    if args.rapido and not args.jornadas:
        args.jornadas = "1,2"
    pedidas = sorted({int(x) for x in (args.jornadas or "1,2,3,4").replace(" ", "").split(",") if x})
    desconhecidas = [n for n in pedidas if n not in MODULOS]
    if desconhecidas:
        print(f"jornada(s) desconhecida(s): {desconhecidas}. Conhecidas: {sorted(MODULOS)}")
        return 2

    dia = time.strftime("%Y-%m-%d")
    raiz_saida = pathlib.Path(args.saida) if args.saida else (RAIZ / "smoke" / "saida")

    print("=" * 78)
    print(f"SMOKE PONTA A PONTA · modo {args.modo} · jornadas {pedidas} · {time.strftime('%d/%m/%Y %H:%M')}")
    print("=" * 78, flush=True)

    amb = Ambiente(modo=args.modo, embarcacao=args.embarcacao, cliente=args.cliente,
                   terra=args.terra, bordo=args.bordo, raiz_saida=raiz_saida)
    resultados: list[dict] = []
    ctx: dict = {"camera": args.camera, "navegador": None}
    try:
        pronto = amb.subir(com_agente=bool({1, 2, 3, 4, 5, 6, 8} & set(pedidas)))
        print(f"ambiente: {pronto}", flush=True)
        if not pronto.get("terra"):
            print("!! o lado terra nao subiu — nada a medir", flush=True)
            print(f"   (cauda do log: {amb.log_de('terra', 300)!r})")
            return 2
        if {2, 4, 5, 8} & set(pedidas):
            if not pronto.get("mediamtx"):
                print("!! sem mediamtx nao ha' midia para medir", flush=True)
                return 2
            # o agente do bordo sobe DEPOIS de a licenca existir? Nao: ele so' olha a flag e espera.
            if not pronto.get("agente", True):
                print(f"!! o agente do bordo nao subiu (cauda: {amb.log_de('agente', 300)!r})", flush=True)

        pw = None
        if not args.sem_navegador and ({2, 3, 4, 5, 6, 8, 10} & set(pedidas)):
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            ctx["navegador"] = pw.chromium.launch(executable_path=chromium())

        for numero in pedidas:
            mod = importlib.import_module(MODULOS[numero])
            print(f"\n--- J{numero} ---", flush=True)
            t0 = time.time()
            try:
                jornada = mod.rodar(amb, ctx)
            except Exception as e:  # noqa: BLE001 — jornada que explode nao derruba o smoke
                import traceback
                from relatorio import Jornada
                jornada = Jornada(numero, MODULOS[numero])
                jornada.erro = f"{type(e).__name__}: {e}"
                print(f"    ERRO {jornada.erro}", flush=True)
                # a jornada que explode precisa deixar a PILHA no log: "deu erro" sem o lugar e' meia-prova
                print("    " + traceback.format_exc().replace("\n", "\n    "), flush=True)
            dados = jornada.gravar(raiz_saida, dia, extratos={"cauda do bordo": amb.log_de("agente", 1500),
                                                              "cauda do terra": amb.log_de("terra", 800)})
            dados["segundos"] = round(time.time() - t0, 1)
            resultados.append(dados)
            print(f"    veredito J{numero}: {dados['veredito']} ({dados['segundos']}s)", flush=True)

        if pw is not None:
            try:
                ctx["navegador"].close()
            except Exception:  # noqa: BLE001
                pass
            pw.stop()
    finally:
        amb.fechar()

    ambiente_resumo = {"modo": args.modo, "embarcacao": args.embarcacao, "cliente": args.cliente,
                       "camera": args.camera, "terra": amb.terra, "bordo": amb.bordo,
                       "banco_do_terra": str(amb.banco_terra), "banco_do_bordo": str(amb.banco_bordo),
                       "mediamtx_proprio": amb.mediamtx_proprio}
    # OS TRES NUMEROS DO PRODUTO (Fase 4 do plano): fps, latencia e reducao de banda num lugar so', com o
    # comando e a maquina carimbados. Numero abaixo do alvo => "com ressalvas", nunca "OK".
    q = qualidade(resultados, ambiente_resumo, dia, comando=" ".join(sys.argv), commit=commit_atual())
    texto = resumo_geral(resultados, ambiente_resumo, dia, commit=commit_atual(), qualidade_do_dia=q)
    (raiz_saida / dia).mkdir(parents=True, exist_ok=True)
    (raiz_saida / dia / "RESUMO.md").write_text(texto, encoding="utf-8")
    (raiz_saida / dia / "qualidade.json").write_text(json.dumps(q, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    print(f"qualidade: {q['fps']} fps · {q['latencia_s']} s · {q['reducao_pct']}% de reducao "
          f"(vs bruto teorico {q['bruto_teorico_kbps']} kbps) -> {q['veredito']}"
          + (f" · fora do alvo: {', '.join(q['fora_do_alvo'])}" if q["fora_do_alvo"] else "")
          + (f" · sem medida: {', '.join(q['sem_medida'])}" if q["sem_medida"] else ""), flush=True)
    (raiz_saida / dia / "resultado.json").write_text(
        json.dumps({"dia": dia, "commit": commit_atual(), "ambiente": ambiente_resumo,
                    "jornadas": resultados}, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for r in resultados if r["veredito"] == "OK")
    falhas = [r for r in resultados if r["veredito"] == "FALHA"]
    sem_medida = [r for r in resultados if r["veredito"] == "NAO_MEDIDA"]
    ressalvas = [r for r in resultados if r["veredito"] == "OK_COM_RESSALVAS"]
    print()
    print("=" * 78)
    print(f"SMOKE: {ok}/{len(resultados)} OK · {len(falhas)} FALHA · {len(ressalvas)} com ressalvas · "
          f"{len(sem_medida)} NAO MEDIDA")
    for r in resultados:
        print(f"  J{r['jornada']} {r['veredito']:<16} {r['titulo']}"
              + (f"  [falhou: {', '.join(r['falhas'])}]" if r["falhas"] else "")
              + (f"  [sem medida: {', '.join(r['sem_medida'])}]" if r["sem_medida"] else ""))
    print(f"evidencia: {raiz_saida / dia / 'RESUMO.md'}")
    print("=" * 78)
    if falhas:
        return 1
    if sem_medida and len(sem_medida) == len(resultados):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
