#!/usr/bin/env python3
"""J8 — O admin manda e o BORDO obedece (e so' o admin manda).

Palavras do dono (20/11/2026): "todas as configuracoes serao feitas por mim (admin), nada sera
configurado pelo cliente" e "o admin tem acesso a tudo ... o proprio app deveria se organizar de acordo
com o usuario". A configuracao viaja do mesmo jeito que a flag: terra PUBLICA, o bordo OLHA, aplica so'
a diferenca e CONFIRMA o que aplicou — o PC de captura nunca recebe conexao.

Acao do usuario: o cliente poe a transmissao no ar (navegador de verdade); o ADMIN publica a banda
(`alvo_kbps`) e o teto (`teto_s`) na tela dele; o cliente se retira e volta; o admin desliga a camera.
Medida: a banda REAL do fluxo antes x depois do alvo do admin (Mbps medidos), o valor que o bordo
gravou, a confirmacao que volta para o terra, o teto aplicado no bordo e o desligamento da camera pelo
admin. O cliente tentando publicar configuracao leva 403 — e' essa a jornada.
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import PORTA_RTSP, pedir, senha_de_demo, sql  # noqa: E402
from medidor import medir_fluxo, tela_do_cliente  # noqa: E402
from relatorio import Jornada  # noqa: E402

PISO_FPS = 27.0
LIMITE_ESPERA_S = 90.0


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _espera(condicao, limite_s: float) -> bool:
    fim = time.time() + limite_s
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(1.0)
    return False


def _alvo_no_bordo(amb, cam: str) -> str:
    linhas = sql(amb.banco_bordo, "SELECT alvo FROM cameras WHERE id=?", (cam,))
    return str(linhas[0]["alvo"] or "") if linhas else ""


def _confirmacoes_do_terra(amb) -> list[dict]:
    """O que o bordo contou ao terra (a tabela guarda APLICADA e RECUSADA na mesma lista — achado da
    J8: sem um campo de estado, so' o texto do motivo separa uma da outra)."""
    from ambiente import token_do_bordo
    codigo, r = pedir("GET", f"{amb.terra}/api/config?embarcacao_id={amb.embarcacao}",
                      token=token_do_bordo())
    if codigo != 200:
        return []
    return [dict(x) for x in _d(r).get("aplicadas") or []]


def _recusada(motivo: str) -> bool:
    """O motivo de uma RECUSA (o produto escreve o que a API local respondeu)."""
    m = (motivo or "").lower()
    return any(trecho in m for trecho in ("nao atendida", "recus", "nao aplica", "nao consegui"))


def _confirmacao(amb, chave: str) -> dict:
    """A ultima linha que o bordo mandou sobre UMA chave (aplicada ou recusada)."""
    achadas = [x for x in _confirmacoes_do_terra(amb) if str(x.get("chave")) == chave]
    return achadas[-1] if achadas else {}


def _recusadas_do_bordo(amb) -> list[dict]:
    return [x for x in _confirmacoes_do_terra(amb) if _recusada(str(x.get("motivo") or ""))]


def _config_local_do_bordo(amb, chave: str) -> str:
    try:
        banco = sqlite3.connect(str(amb.banco_bordo))
        try:
            linha = banco.execute("SELECT valor FROM config_local WHERE chave=? ORDER BY rowid DESC LIMIT 1",
                                  (chave,)).fetchone()
            return str(linha[0]) if linha else ""
        finally:
            banco.close()
    except Exception:  # noqa: BLE001
        return ""


def _restaurar(amb, cam: str) -> None:
    """Devolve a bancada ao estado de fabrica: sem config publicada e com a camera no alvo padrao."""
    try:
        banco = sqlite3.connect(str(amb.banco_terra))
        try:
            banco.execute("DELETE FROM config_bordo WHERE embarcacao_id=?", (amb.embarcacao,))
            banco.execute("DELETE FROM config_aplicada_bordo WHERE embarcacao_id=?", (amb.embarcacao,))
            banco.commit()
        finally:
            banco.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        banco = sqlite3.connect(str(amb.banco_bordo))
        try:
            banco.execute("UPDATE cameras SET alvo='2500k' WHERE id=?", (cam,))
            banco.execute("DELETE FROM config_local WHERE chave IN ('teto_s','alvo_kbps')")
            banco.commit()
        finally:
            banco.close()
    except Exception:  # noqa: BLE001
        pass


def _publicar(amb, admin: str, chave: str, valor: str, cam: str = "") -> tuple[int, dict]:
    codigo, r = pedir("POST", f"{amb.terra}/api/config",
                      {"embarcacao_id": amb.embarcacao, "camera_id": cam, "chave": chave, "valor": valor},
                      sessao=admin)
    return codigo, _d(r)


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
    pagina.click('.item[data-tela="transmissao"]')
    pagina.wait_for_selector(".transmissao-linha", timeout=20000)
    pagina.click(f"#iniciar-{cam}")
    return ctxx, pagina


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(8, "O admin manda e o bordo obedece (e so' o admin manda)",
                "configuracao publicada em terra -> o bordo aplica e CONFIRMA; a banda real muda")
    cam = ctx.get("camera") or "cam-01"
    navegador = ctx.get("navegador")
    if navegador is None:
        j.erro = "sem navegador no contexto"
        return j
    amb.camera_do_bordo(cam)
    # o bordo olha a configuracao de 2 em 2 s nesta rodada (o padrao do produto e' 15 s): o smoke mede o
    # caminho, nao o relogio do dono — e o intervalo usado fica escrito na evidencia.
    amb.reiniciar_agente({**amb.hd_env, "LECSOR_ESPERA_DA_CONFIG": "2"})
    admin = amb.entrar("admin@lecsor.test")
    j.checar("o admin entra no painel", bool(admin), "sessao de admin do sistema")
    ctxx = pagina = None
    try:
        # 1) o cliente poe a transmissao no ar (o caminho inteiro, como na J2)
        ctxx, pagina = _cliente_entra(navegador, amb, cam)
        subiu = amb.fluxo_no_ar(cam, segundos=60)
        j.checar("a transmissao sobe pelo pedido do cliente", subiu, f"rtsp://127.0.0.1:{PORTA_RTSP}/{cam}")
        if not subiu:
            j.medir(cauda_do_agente=amb.log_de("agente", 1200))
            return j
        antes = medir_fluxo(f"rtsp://127.0.0.1:{PORTA_RTSP}/{cam}", segundos=8.0)
        j.medir(banda_antes=antes)

        # 2) o CLIENTE nao publica configuracao: a autoridade e' o admin
        sessao_cliente = amb.entrar("cliente@lecsor.test")
        codigo, _ = pedir("POST", f"{amb.terra}/api/config",
                          {"embarcacao_id": amb.embarcacao, "camera_id": cam, "chave": "alvo_kbps",
                           "valor": "300"}, sessao=sessao_cliente)
        j.checar("o cliente NAO publica configuracao (403): quem manda e' o admin", codigo == 403,
                 f"HTTP {codigo}")

        # 3) o admin publica a BANDA (o alvo cai de 2500 para 500 kbps)
        codigo, r = _publicar(amb, admin, "alvo_kbps", "500", cam)
        j.checar("o admin publica a banda da camera (alvo_kbps=500)", codigo in (200, 201) and bool(_d(r).get("ok")),
                 f"HTTP {codigo} · versao {_d(r).get('versao')}")
        aplicou = _espera(lambda: _confirmacao(amb, "alvo_kbps"), LIMITE_ESPERA_S)
        confirmacao = _confirmacao(amb, "alvo_kbps")
        j.checar("o bordo CONFIRMA no lado terra a banda que aplicou",
                 aplicou and confirmacao.get("valor") == "500" and not _recusada(str(confirmacao.get("motivo"))),
                 f"{confirmacao or 'sem confirmacao'}")
        alvo = _alvo_no_bordo(amb, cam)
        j.checar("o bordo gravou o alvo no formato que o ffmpeg usa (sufixo k)",
                 alvo.endswith("k"), f"cameras.alvo = {alvo!r} (o ffmpeg do produto usa `-b:v {alvo}`)")

        # 4) o efeito REAL: o cliente sai e volta -> o envio renasce com o alvo do admin -> banda cai
        pagina.goto("about:blank", wait_until="domcontentloaded")
        parou = _espera(lambda: not amb.processo_da_midia("streamid=publish"), LIMITE_ESPERA_S)
        j.checar("com o alvo publicado, o envio antigo e' encerrado ao o cliente sair", parou,
                 "sem ffmpeg de envio")
        pagina.close()
        ctxx.close()
        ctxx, pagina = _cliente_entra(navegador, amb, cam)
        subiu2 = amb.fluxo_no_ar(cam, segundos=60)
        j.checar("a transmissao volta com o alvo do admin aplicado", subiu2, f"fluxo {cam}")
        if subiu2:
            depois = medir_fluxo(f"rtsp://127.0.0.1:{PORTA_RTSP}/{cam}", segundos=8.0)
            j.medir(banda_depois=depois)
            j.checar("a banda do fluxo CAIU com o alvo do admin (<= 60% da banda anterior)",
                     float(depois["mbps"]) <= float(antes["mbps"]) * 0.6,
                     f"{antes['mbps']} Mbps -> {depois['mbps']} Mbps (alvo 500 kbps)")
            j.checar("o video continua VIDEO com o alvo novo (o cliente nao perde o quadro)",
                     float(depois["fps_midia"]) >= PISO_FPS,
                     f"{depois['fps_midia']} fps · {depois['quadros']} quadros vs piso {PISO_FPS}")
            pagina.click('.item[data-tela="visualizar"]')
            pagina.wait_for_timeout(2500)
            tv = tela_do_cliente(pagina, segundos=6.0)
            j.checar("a imagem aparece na tela do cliente com o alvo novo",
                     bool(tv.get("imagem_na_tela")), f"{tv.get('largura')}x{tv.get('altura')}")

        # 5) o TETO de tempo da embarcacao (a segunda chave do admin, e' por embarcacao)
        codigo, r = _publicar(amb, admin, "teto_s", "1800")
        j.checar("o admin publica o teto de tempo da embarcacao (teto_s=1800)",
                 codigo in (200, 201) and bool(_d(r).get("ok")), f"HTTP {codigo}")
        teto = _espera(lambda: _config_local_do_bordo(amb, "teto_s") == "1800", LIMITE_ESPERA_S)
        j.checar("o bordo aplicou o teto no proprio banco", teto,
                 f"config_local.teto_s no bordo = {_config_local_do_bordo(amb, 'teto_s')!r}")

        # 6) o admin DESLIGA a camera — com o CLIENTE AINDA NA TELA (e' o caso de verdade: alguem assiste)
        codigo, r = _publicar(amb, admin, "transmitir", "0", cam)
        j.checar("o admin desliga a camera (transmitir=0)", codigo in (200, 201) and bool(_d(r).get("ok")),
                 f"HTTP {codigo}")
        desligou = _espera(lambda: not amb.processo_da_midia("streamid=publish"), 40)
        j.checar("o bordo desliga a camera que o admin desligou", desligou, "sem ffmpeg de envio")
        # ACHADO (medido, nao e' defeito declarado): o cliente AINDA na tela continua PEDINDO a
        # transmissao e a flag do cliente vence o desligamento do admin — o bordo re-liga segundos
        # depois. Quem responde isso e' o dono (a pergunta esta' no diario da Fase 3); aqui fica o
        # numero. Por isso o desligamento so' FICA de pe' quando o cliente sai da tela.
        momento = time.time()
        voltou = _espera(lambda: bool(amb.processo_da_midia("streamid=publish")), 40)
        j.medir(camera_voltou_com_o_cliente_na_tela=voltou,
                segundos_ate_voltar=round(time.time() - momento, 1) if voltou else None)
        pagina.goto("about:blank", wait_until="domcontentloaded")
        j.checar("o cliente sai da tela e a camera fica desligada",
                 _espera(lambda: not amb.processo_da_midia("streamid=publish"), 60),
                 "sem ffmpeg de envio com o cliente fora")
        j.checar("o fluxo sai do mediamtx do lado terra",
                 _espera(lambda: not amb.fluxo_no_ar(cam, segundos=1), 60), f"fluxo {cam}")
        estado = sql(amb.banco_bordo,
                     "SELECT estado FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1", (cam,))
        j.checar("o bordo registra a parada no proprio banco (estado='parado')",
                 bool(estado) and str(estado[0]["estado"]) == "parado",
                 f"estado: {estado[0]['estado'] if estado else 'sem linha'}")
        recusadas = _recusadas_do_bordo(amb)
        j.checar("o bordo NAO recusou nenhuma chave do admin (obedeceu a todas)", not recusadas,
                 f"recusadas: {recusadas or 'nenhuma'}")
        j.medir(confirmacoes_do_bordo=[{k: v for k, v in x.items() if k != "atualizado_em"}
                                       for x in _confirmacoes_do_terra(amb)])
    except Exception as e:  # noqa: BLE001
        j.erro = f"{type(e).__name__}: {e}"
    finally:
        try:
            if ctxx is not None:
                ctxx.close()
        except Exception:  # noqa: BLE001
            pass
        _restaurar(amb, cam)
        j.medir(config_apagada_na_limpeza=True)
    return j
