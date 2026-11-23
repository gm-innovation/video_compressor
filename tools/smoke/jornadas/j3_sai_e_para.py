#!/usr/bin/env python3
"""J3 — O cliente sai e a banda volta.

Acao do usuario: o cliente FECHA a tela (pagehide: e' o aviso do proprio app, nao um pedido de teste).
Efeito: o lado terra marca a sessao como encerrada -> a flag vira `parar` -> o bordo desliga a camera
-> o envio SRT morre e o fluxo sai do mediamtx.
Medida: o tempo de parada, o processo de envio morto e a banda de volta a ~0.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import pedir, sql, token_do_bordo  # noqa: E402
from medidor import medir_mbps, tela_do_cliente  # noqa: E402
from relatorio import Jornada  # noqa: E402

LIMITE_PARADA_S = 60.0


def _espera_parar(amb, cam: str, limite_s: float = LIMITE_PARADA_S) -> dict:
    """Espera o lado terra virar `parar` para aquela camera (rota real do agente)."""
    fim = time.time() + limite_s
    ultimo: dict = {}
    while time.time() < fim:
        _, r = pedir("GET", f"{amb.terra}/api/estado-desejado?embarcacao_id={amb.embarcacao}",
                     token=token_do_bordo())
        for d in (r or {}).get("cameras") or []:
            if str(d.get("camera_id")) == cam:
                ultimo = d
                if str(d.get("desejo")) == "parar":
                    return d
        time.sleep(1.0)
    return ultimo


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(3, "O cliente sai e a banda volta",
                "fechar a tela tem que parar o envio do barco — sem ninguem clicando em nada no bordo")
    cam = ctx.get("camera") or "cam-01"
    pagina = ctx.get("pagina_do_cliente")
    if pagina is None:
        j.checar("precisa da jornada 2 (cliente na tela) para medir a saida", False,
                 "rode com --jornadas 1,2,3", medido=False)
        return j

    # pre-condicao: a midia esta' no ar (senao nao ha' o que interromper)
    no_ar = ctx.get("tem_camera_no_ar") or amb.fluxo_no_ar(cam, segundos=8)
    j.checar("pre-condicao: a transmissao estava no ar", bool(no_ar), f"fluxo {cam}")
    if not no_ar:
        return j
    procs_antes = len(amb.processo_da_midia("streamid=publish"))
    j.medir(fps_e_envios_antes=procs_antes)

    # 1) o cliente FECHA a tela (pagehide do proprio app -> sendBeacon /api/transmissao/sair)
    t_saida = time.time()
    pagina.goto("about:blank", wait_until="domcontentloaded")
    j.checar("o cliente fecha a tela", True, "navegador do cliente fora da tela")

    # 2) o lado terra vira `parar` sozinho
    desejo = _espera_parar(amb, cam)
    t_desejo = time.time()
    j.checar("o lado terra marca a saida e a flag vira PARAR",
             str(desejo.get("desejo")) == "parar", f"{desejo or 'sem resposta'}")

    # 3) o bordo obedece: o envio morre
    fim = time.time() + 40
    morto = False
    while time.time() < fim:
        if not amb.processo_da_midia("streamid=publish"):
            morto = True
            break
        time.sleep(1.0)
    t_parado = time.time()
    j.checar("o processo de envio do bordo morre (SRT encerrado)", morto,
             f"{len(amb.processo_da_midia('streamid=publish'))} processo(s) depois de {t_parado - t_saida:.1f}s")

    # 4) o fluxo sai do mediamtx do lado terra
    saiu = False
    for _ in range(12):
        if not amb.fluxo_no_ar(cam, segundos=1):
            saiu = True
            break
        time.sleep(2.0)
    j.checar("o fluxo desaparece do mediamtx do lado terra (ninguem mais consome)", saiu, f"fluxo {cam}")

    # 5) a banda de subida volta a ~0 (medido: o fluxo nao existe mais para ler)
    b = medir_mbps(f"rtsp://127.0.0.1:8554/{cam}", segundos=3.0)
    j.medir(mbps_depois=b["mbps"], bytes_depois=b["bytes"])
    j.checar("a banda de subida volta a ~0", b["mbps"] < 0.05, f"{b['mbps']} Mbps medidos depois da saida")

    # 6) o bordo registra o envio como parado (estado do produto, nao impressao do teste)
    linha = sql(amb.banco_bordo,
                "SELECT estado FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1", (cam,))
    j.checar("o banco do bordo diz que o envio parou",
             bool(linha) and "parado" in str(linha[0]["estado"]).lower(),
             f"{dict(linha[0]) if linha else 'sem linha'}")

    # 7) a trilha do lado terra conta a saida do cliente
    nova = sql(amb.banco_terra, "SELECT acao FROM auditoria_acesso ORDER BY id DESC LIMIT 40")
    j.checar("a trilha registra a saida do cliente da tela",
             any("saiu_da_tela" in str(x["acao"]) or "encerr" in str(x["acao"]) for x in nova),
             ", ".join(sorted({str(x["acao"]) for x in nova})[:5]))

    parada = t_parado - t_saida
    j.medir(parada_s=round(parada, 1), desejo_em_s=round(t_desejo - t_saida, 1))
    j.checar("a parada acontece em tempo aceitavel (<= 60 s do fechamento)", parada <= 60.0,
             f"{parada:.1f}s do fechamento da tela ate' o envio morrer")
    ctx["tem_camera_no_ar"] = False
    ctx["pagina_do_cliente"] = None
    return j
