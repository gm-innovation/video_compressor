#!/usr/bin/env python3
"""Envia para o Supabase o histórico fechado na bancada (minuto a minuto) e uma amostra do link.

Nao guarda credencial: le tudo de variavel de ambiente.

    LECSOR_SUPABASE_URL=https://<ref>.supabase.co
    LECSOR_TOKEN_INGESTAO=<token-do-servidor-de-bordo>
    python ground/publicar_telemetria.py [--simular] [--desde-dias 1]

Se as variaveis nao estiverem definidas, o script explica e sai (nada de chave embutida).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import producao  # noqa: E402

FUSO = timezone(timedelta(hours=-3))


def _montar(desde_dias: int = 1) -> dict:
    producao.fechar_minutos()
    inicio = (datetime.now(FUSO) - timedelta(days=max(1, desde_dias))).strftime("%Y-%m-%dT%H:%M")
    with producao.conexao_banco() as c:
        linhas = [dict(x) for x in c.execute("""
            SELECT fluxo_id, camera_id, embarcacao_id, minuto, entrada_kbps, saida_kbps,
                   compressao_pct, mb_enviados, segundos_no_ar
              FROM telemetria_minuto WHERE minuto >= ? ORDER BY minuto""", (inicio,))]
    link = producao.link_srt()
    net = producao.latencia_internet()
    return {
        "embarcacao": os.environ.get("LECSOR_EMBARCACAO") or _embarcacao_do_banco(),
        "fluxos": linhas,
        "link": {
            "fluxo_id": link.get("fluxo"), "rtt_ms": link.get("rtt_ms"),
            "capacidade_mbps": link.get("capacidade_link_mbps"),
            "taxa_envio_mbps": link.get("taxa_recebida_mbps"),
            "atraso_buffer_ms": link.get("atraso_buffer_ms"),
            "perda_pct": link.get("perda_recebida_pct"),
            "latencia_internet_ms": net.get("ms_medio"),
            "fonte": f"{(link.get('fonte') or 'SRT')} + {net.get('fonte') or 'sem ping'}",
        },
    }


def _embarcacao_do_banco() -> str:
    with producao.conexao_banco() as c:
        r = c.execute("SELECT id FROM embarcacoes ORDER BY id LIMIT 1").fetchone()
    return (r["id"] if r else "")


def main(argv: list[str]) -> int:
    simular = "--simular" in argv
    dias = 1
    if "--desde-dias" in argv:
        try:
            dias = int(argv[argv.index("--desde-dias") + 1])
        except (IndexError, ValueError):
            pass
    carga = _montar(dias)
    print(f"[i] {len(carga['fluxos'])} minuto(s) de histórico, embarcação {carga['embarcacao']!r}")
    if simular:
        print(json.dumps(carga, ensure_ascii=False)[:1500])
        return 0
    url = (os.environ.get("LECSOR_SUPABASE_URL") or "").rstrip("/")
    token = os.environ.get("LECSOR_TOKEN_INGESTAO") or ""
    if not url or not token:
        print("[!] defina LECSOR_SUPABASE_URL e LECSOR_TOKEN_INGESTAO (nenhuma chave vai para o repo)")
        return 2
    if not carga["fluxos"]:
        print("[i] nada para enviar ainda (o histórico fecha enquanto há envio no ar)")
        return 0
    pedido = urllib.request.Request(
        f"{url}/functions/v1/telemetria-ingestao",
        data=json.dumps(carga).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-token-embarcacao": token},
        method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=30) as r:
            print("[ok]", r.status, r.read().decode("utf-8")[:300])
    except urllib.error.HTTPError as e:
        print("[!] o Supabase recusou:", e.code, e.read().decode("utf-8")[:300])
        return 1
    except Exception as e:
        print("[!] falhou:", type(e).__name__, str(e)[:200])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
