#!/usr/bin/env python3
"""J10 — Licenca revogada corta o que esta' no ar.

Palavras do dono (19/11/2026): "o admin tem acesso a tudo" e, na rodada da licenca (0.10.0), "revogar /
reemitir corta na hora".

Acao do usuario: o cliente poe a transmissao de um barco no ar; o ADMIN revoga a chave daquele barco.
Medida: o bordo CONSULTA o lado terra sozinho (ninguem abre tela no barco), a transmissao morre com o
tempo de reacao medido, a tela do bordo DIZ o motivo, a trilha registra o corte, o vinculo NAO e'
apagado — e a reativacao do admin devolve o barco ao ar.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import PORTA_RTSP, iniciar_transmissao, pedir, senha_de_demo, sql  # noqa: E402
from relatorio import Jornada  # noqa: E402

# O bordo do produto confere a licenca a cada 300 s. A bancada encurta o CICLO (5 s) para a medida
# caber no relogio; o intervalo usado fica escrito na evidencia.
CICLO_DA_BANCADA_S = 5
# O lado terra fecha a sessao do cliente que fica 60 s sem "estou aqui" (`SEGUNDOS_SEM_BATIMENTO`):
# esperar mais que isso mediria o batimento, nao a licenca. A folga e' o ciclo do bordo (5 s aqui).
LIMITE_REACAO_S = 45.0


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _espera(condicao, limite_s: float, intervalo: float = 1.0) -> bool:
    fim = time.time() + limite_s
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(intervalo)
    return False


def _licenca_do_bordo(amb) -> dict:
    codigo, r = pedir("GET", f"{amb.bordo}/api/licenca")
    return _d(r) if codigo == 200 else {}


def _cliente_entra(navegador, amb, cam: str):
    """Abre a tela do cliente e pede a transmissao. Devolve (contexto, pagina)."""
    ctxx = navegador.new_context(viewport={"width": 1500, "height": 900})
    pagina = ctxx.new_page()
    pagina.on("dialog", lambda d: d.accept())
    pagina.goto(amb.terra + "/app/", wait_until="domcontentloaded")
    pagina.fill("#email", "cliente@lecsor.test")
    pagina.fill("#senha", senha_de_demo())
    pagina.click("form#form-entrar button[type=submit]")
    pagina.wait_for_selector("#sistema:not(.oculto)", timeout=25000)
    # PLANO UNICO (25/11/2026): a tela "Transmitir" saiu do cliente - o controle de transmissao
    # (iniciar/parar/contagem/gravar) mora na GRADE, no quadro de cada camera. O cliente ja'
    # cai nessa tela ao entrar; quem pede a transmissao e' o `iniciar_transmissao` (ele encerra
    # antes a sessao que uma jornada anterior deixou de pe' — o "iniciar" so' aparece com a
    # camera parada para este usuario, que e' o comportamento certo da tela).
    iniciar_transmissao(pagina, cam)
    return ctxx, pagina


def _garantir_chave(amb, ctx: dict, admin: str, j: Jornada) -> tuple[str, str]:
    """A chave deste barco ativa no bordo. Vem da J1 quando ela rodou; sozinha, a J10 gera e ativa."""
    chave = str(ctx.get("chave") or "")
    if not chave:
        codigo, r = amb.gerar_licenca(admin, maquinas=2)
        chave = str(_d(r).get("chave") or "")
        if chave:
            amb.ativar_no_bordo(chave)
        j.checar("a jornada sozinha gera e ativa a chave do barco", codigo == 201 and bool(chave),
                 f"HTTP {codigo}")
    guardado = amb.licenca_do_bordo()
    if not str(guardado.get("chave") or ""):
        j.erro = "o bordo nao tem chave guardada — a J10 precisa do vinculo"
        return "", ""
    return chave, str(guardado.get("licenca_id") or "")


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(10, "Licenca revogada corta o que esta' no ar",
                "admin revoga a chave -> o bordo consulta o terra -> a transmissao para e a tela diz por que")
    cam = ctx.get("camera") or "cam-01"
    navegador = ctx.get("navegador")
    if navegador is None:
        j.erro = "sem navegador no contexto"
        return j
    admin = amb.entrar("admin@lecsor.test")
    j.checar("o admin entra no painel", bool(admin), "sessao de admin do sistema")
    if not admin:
        return j
    chave, ident = _garantir_chave(amb, ctx, admin, j)
    if not chave or not ident:
        j.medir(licenca_do_bordo=amb.licenca_do_bordo())
        return j
    # O lado terra e' a autoridade da licenca: confere a chave na tabela `licencas` dele.
    guardada = sql(amb.banco_terra, "SELECT id,status FROM licencas WHERE chave=?", (chave,))
    j.checar("o lado terra conhece a chave deste barco",
             bool(guardada) and str(guardada[0]["id"]) == ident,
             f"licenca_id no bordo={ident!r} no terra={guardada[0]['id'] if guardada else 'AUSENTE'}")

    # o bordo confere a licenca de 5 em 5 s NESTA rodada (o padrao do produto e' 300 s)
    amb.reiniciar_agente({**amb.hd_env, "LECSOR_ESPERA_DA_LICENCA": str(CICLO_DA_BANCADA_S),
                          "LECSOR_ESPERA_DA_SAUDE": "30"})
    amb.camera_do_bordo(cam)
    ctxx = pagina = None
    try:
        # 1) com a chave ATIVA, o bordo nao bloqueia nada
        antes = _licenca_do_bordo(amb)
        j.checar("com a chave ativa, o bordo NAO bloqueia nada", not antes.get("bloqueada"),
                 f"estado={antes.get('estado') or 'sem leitura'} · status={antes.get('status') or ''}")

        # 2) o cliente poe a transmissao no ar (o caminho inteiro, como na J2)
        ctxx, pagina = _cliente_entra(navegador, amb, cam)
        subiu = amb.fluxo_no_ar(cam, segundos=60)
        j.checar("a transmissao do barco esta' no ar antes da revogacao", subiu,
                 f"rtsp://127.0.0.1:{PORTA_RTSP}/{cam}")
        if not subiu:
            j.medir(cauda_do_agente=amb.log_de("agente", 1200))
            return j

        # 3) o ADMIN revoga a chave daquele barco (com o motivo que aparece para o cliente)
        codigo, _ = pedir("POST", f"{amb.terra}/api/licencas/{ident}/revogar",
                          {"motivo": "revogada pelo smoke da J10"}, sessao=admin)
        j.checar("o admin revoga a chave do barco", codigo == 200, f"HTTP {codigo}")
        revogada = sql(amb.banco_terra, "SELECT status FROM licencas WHERE id=?", (ident,))
        j.checar("o lado terra marca a chave como revogada", bool(revogada)
                 and str(revogada[0]["status"]) == "revogada",
                 f"status={revogada[0]['status'] if revogada else 'AUSENTE'}")

        # 4) O BORDO CONSULTA SOZINHO e PARA O QUE ESTA' NO AR (ninguem abriu tela no barco)
        t0 = time.time()
        parou = _espera(lambda: not amb.processo_da_midia("streamid=publish"), LIMITE_REACAO_S)
        segundos = round(time.time() - t0, 1)
        j.medir(reacao_da_revogacao_s=segundos, ciclo_da_bancada_s=CICLO_DA_BANCADA_S)
        j.checar("o bordo consulta o lado terra sozinho e PARA a transmissao", parou,
                 f"o envio morreu em {segundos}s (ciclo da bancada: {CICLO_DA_BANCADA_S}s)")
        j.checar("o fluxo sai do mediamtx do lado terra",
                 _espera(lambda: not amb.fluxo_no_ar(cam, segundos=1), 60), f"fluxo {cam}")

        # 5) A TELA DO BORDO diz o motivo (e' o mesmo endpoint que a tela da licenca le)
        depois = _licenca_do_bordo(amb)
        j.checar("a tela do bordo diz que a licenca caiu, com o motivo", bool(depois.get("bloqueada")),
                 f"{str(depois.get('texto') or '')[:80]!r}")
        j.checar("a tela do bordo aponta a embarcacao e o dono da chave",
                 bool(depois.get("embarcacao_id")), f"embarcacao={depois.get('embarcacao_id')!r}")

        # 6) o cliente INSISTE (a pagina continua pedindo) e o bordo NAO religa sob licenca revogada
        esperou = 30.0
        religou = _espera(lambda: bool(amb.processo_da_midia("streamid=publish")), esperou)
        j.checar("o bordo NAO religa a camera com a licenca revogada (o cliente insistindo)",
                 not religou, f"apos a revogacao, {esperou:.0f}s sem religar")

        # 7) a TRILHA registra o corte pela licenca (o bordo para por ordem da licenca, e conta)
        eventos = sql(amb.banco_bordo, "SELECT acao FROM auditoria_acesso WHERE acao LIKE '%licenca%'")
        acoes = [str(x["acao"]) for x in eventos]
        j.medir(acoes_de_licenca_no_bordo=acoes)
        j.checar("a trilha do bordo registra a captura parada pela licenca",
                 any("captura_parada_por_licenca" in a for a in acoes), f"acoes: {acoes}")

        # 8) a revogacao NAO apaga o vinculo (o "nada e' apagado" e' da trilha; a chave segue guardada)
        guardado = amb.licenca_do_bordo()
        j.checar("a chave e o vinculo continuam guardados no bordo", str(guardado.get("chave")) == chave,
                 f"chave {'guardada' if guardado.get('chave') == chave else 'AUSENTE'}")

        # 9) o admin REATIVA e o barco volta a transmitir (o corte e' reversivel, pelo mesmo caminho)
        codigo, _ = pedir("POST", f"{amb.terra}/api/licencas/{ident}/reativar", {}, sessao=admin)
        j.checar("o admin reativa a chave do barco", codigo == 200, f"HTTP {codigo}")
        desbloqueou = _espera(lambda: not _licenca_do_bordo(amb).get("bloqueada"), LIMITE_REACAO_S)
        j.checar("o bordo ve' a chave reativada na proxima consulta", desbloqueou, "sem bloqueio")
        if desbloqueou:
            ctxx.close()      # o cliente fecha a aba antiga e entra de novo (o caminho do dia a dia)
            ctxx, pagina = _cliente_entra(navegador, amb, cam)
            subiu2 = amb.fluxo_no_ar(cam, segundos=90)
            j.checar("com a chave reativada, o barco volta a transmitir", subiu2, f"fluxo {cam}")
        return j
    finally:
        try:
            if ctxx is not None:
                ctxx.close()
        except Exception:  # noqa: BLE001
            pass
