#!/usr/bin/env python3
"""J4 — Dois clientes, um sai: a transmissao so' para quando NAO SOBRA ninguem assistindo.

Palavras do dono (19/11/2026): "terra (vps) precisa saber se a tela foi fechada, computador desligado
ou falta de conexao no computador do usuario para interromper a transmissao, a menos que haja outro
usuario conectado e acompanhando".

Acao do usuario: o admin cadastra o segundo cliente (regra: quem cadastra usuario e' o admin); os dois
clientes abrem a MESMA camera; o primeiro fecha a tela; depois o segundo.
Medida: com um cliente ainda assistindo a camera CONTINUA no ar (o bordo nao desliga); quando o ultimo
sai, a flag vira `parar` e o envio morre.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import pedir, senha_de_demo, token_do_bordo  # noqa: E402
from relatorio import Jornada  # noqa: E402

LIMITE_S = 60.0


def _estado(amb, cam: str) -> dict:
    _, r = pedir("GET", f"{amb.terra}/api/estado-desejado?embarcacao_id={amb.embarcacao}",
                 token=token_do_bordo())
    for d in (r or {}).get("cameras") or []:
        if str(d.get("camera_id")) == cam:
            return dict(d)
    return {}


def _espera(condicao, limite_s: float) -> bool:
    fim = time.time() + limite_s
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(1.0)
    return False


def _entrar_e_pedir(navegador, amb, email: str, senha: str, cam: str):
    """Abre um cliente de verdade (navegador) e clica em Iniciar transmissao. Devolve (ctx, pagina)."""
    ctxx = navegador.new_context(viewport={"width": 1400, "height": 850})
    pagina = ctxx.new_page()
    pagina.on("dialog", lambda d: d.accept())
    pagina.goto(amb.terra + "/app/", wait_until="domcontentloaded")
    pagina.fill("#email", email)
    pagina.fill("#senha", senha)
    pagina.click("form#form-entrar button[type=submit]")
    pagina.wait_for_selector("#sistema:not(.oculto)", timeout=25000)
# PLANO UNICO (25/11/2026): a tela "Transmitir" saiu do cliente - o controle de transmissao
    # (iniciar/parar/contagem/gravar) mora na GRADE, no quadro de cada camera. O cliente ja'
    # cai nessa tela ao entrar; o botao do quadro e' o `[data-papel="iniciar"]`.
    pagina.wait_for_selector(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]', timeout=20000)
    pagina.click(f'.janela[data-cam="{cam}"] [data-papel="iniciar"]')
    return ctxx, pagina


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(4, "Dois clientes, um sai",
                "a camera so' desliga quando o ULTIMO cliente sai — ninguem desliga a mao")
    cam = ctx.get("camera") or "cam-01"
    navegador = ctx.get("navegador")
    if navegador is None:
        j.erro = "sem navegador no contexto"
        return j
    amb.camera_do_bordo(cam)   # a jornada vale sozinha (idempotente)

    # 0) o ADMIN cadastra o segundo cliente (a regra do dono: quem cadastra usuario e' o admin)
    admin = amb.entrar("admin@lecsor.test")
    j.checar("o admin entra no painel", bool(admin), "sessao de admin do sistema")
    email_b = f"smoke-{int(time.time())}-b@lecsor.test"
    codigo, rb = pedir("POST", f"{amb.terra}/api/usuarios",
                       {"email": email_b, "nome": "Segundo cliente (smoke)", "papel": "cliente",
                        "cliente_id": amb.cliente}, sessao=admin)
    senha_b = str(rb.get("senha_inicial") or "")
    j.checar("o admin cadastra o segundo cliente da mesma empresa", codigo == 201 and bool(senha_b),
             f"HTTP {codigo} · {email_b}" + ("" if codigo == 201 else f" · {str(rb)[:80]}"))
    if not senha_b:
        return j

    abertos: list = []
    try:
        # 1) os dois clientes abrem a MESMA camera
        ctx_a, pag_a = _entrar_e_pedir(navegador, amb, "cliente@lecsor.test", senha_de_demo(), cam)
        abertos.append((ctx_a, pag_a))
        no_ar = amb.fluxo_no_ar(cam, segundos=90)
        j.checar("a midia sobe com o primeiro cliente (cliente A)", no_ar, f"fluxo {cam}")
        if not no_ar:
            j.medir(cauda_do_agente=amb.log_de("agente", 1200))
            return j
        ctx_b, pag_b = _entrar_e_pedir(navegador, amb, email_b, senha_b, cam)
        abertos.append((ctx_b, pag_b))
        dois = _espera(lambda: "2 sess" in str(_estado(amb, cam).get("motivo") or ""), 60)
        j.checar("o lado terra conta DUAS sessoes na mesma camera", dois,
                 f"{_estado(amb, cam)}")

        # 2) o cliente A SAI: a camera CONTINUA no ar (o B ainda assiste)
        pag_a.goto("about:blank", wait_until="domcontentloaded")
        j.checar("o cliente A fecha a tela", True, "pagehide do app")
        continua = _espera(lambda: str(_estado(amb, cam).get("desejo")) == "ligar"
                           and "1 sess" in str(_estado(amb, cam).get("motivo") or ""), LIMITE_S)
        j.checar("a flag CONTINUA em LIGAR por causa do cliente B", continua, f"{_estado(amb, cam)}")
        j.checar("a camera continua no ar depois de o cliente A sair",
                 bool(amb.processo_da_midia("streamid=publish")), "envio do bordo ainda de pe'")
        j.checar("o cliente B ainda recebe imagem", amb.fluxo_no_ar(cam, segundos=10),
                 "fluxo ainda publicado")

        # 3) o cliente B SAI: agora ninguem assiste -> a flag vira PARAR e o envio morre
        pag_b.goto("about:blank", wait_until="domcontentloaded")
        j.checar("o cliente B fecha a tela", True, "pagehide do app")
        parou = _espera(lambda: str(_estado(amb, cam).get("desejo")) == "parar", LIMITE_S)
        j.checar("ninguem mais assistindo: a flag vira PARAR", parou, f"{_estado(amb, cam)}")
        morreu = _espera(lambda: not amb.processo_da_midia("streamid=publish"), LIMITE_S)
        j.checar("o bordo desliga a camera (o envio morre)", morreu, "sem ffmpeg de envio")
        j.checar("o fluxo sai do mediamtx", _espera(lambda: not amb.fluxo_no_ar(cam, segundos=1), 30),
                 f"fluxo {cam}")
    finally:
        for ctxx, _ in abertos:
            try:
                ctxx.close()
            except Exception:  # noqa: BLE001
                pass
    ctx["tem_camera_no_ar"] = False
    return j
