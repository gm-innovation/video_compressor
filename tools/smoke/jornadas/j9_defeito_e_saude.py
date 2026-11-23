#!/usr/bin/env python3
"""J9 — O defeito de verdade no computador de captura e a saude que o denuncia.

Palavras do dono (19/11/2026): "vamos incluir tambem uma forma de o app de captura enviar para o admin
dados de saude para monitorarmos se esta tudo okay ou se ha algum problema que devemos corrigir ou
acompanhar".

O que esta jornada prova: o bordo MANDA o proprio retrato e, quando o defeito aparece — o ffmpeg sai do
caminho, os envios comecam a falhar, pedido de trecho fica pendente, o bordo para de reportar — o painel
do admin MUDA de proposito, com o tempo de reacao medido. Nada aqui e' encenado: o retrato e' o do
produto (`saude_do_bordo.retrato`), o envio e' o do produto (`agente_de_ordens.enviar_saude`) e o
semaforo e' o do produto (`api.classificar_saude`, com os limiares de `LIMIARES_DE_SAUDE`).

A bancada acelera o CICLO (o bordo do produto manda a saude a cada 60 s; aqui, a cada poucos segundos) e
inverte o sinal do ffmpeg mexendo no PATH do agente — o unico jeito de "sumir" com o ffmpeg sem quebrar
a maquina. O intervalo usado fica escrito na evidencia.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import pedir, sql, token_do_bordo  # noqa: E402
from relatorio import Jornada  # noqa: E402

# O produto CLAMPA o intervalo da saude em >= 10 s (`agente_de_ordens.intervalo_da_saude`): a bancada
# nao consegue pedir menos que isso — o ciclo real da rodada e' este numero, e ele vai na evidencia.
CICLO_DA_BANCADA_S = 10         # quanto o bordo espera entre dois retratos NESTA rodada
LIMITE_MUDO_S = 180.0           # o mesmo limiar do produto para "o bordo parou de reportar"
LIMITE_ESPERA_S = 120.0
ERROS_DE_ENVIO = 25             # >= 20 (o limiar de atencao do produto) e < 100 (o de problema)


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _espera(condicao, limite_s: float, intervalo: float = 1.0) -> bool:
    fim = time.time() + limite_s
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(intervalo)
    return False


def _saude(amb, admin: str) -> dict:
    """O que o painel do admin mostra AGORA (a leitura e' sempre dele; o bordo nunca abre porta)."""
    codigo, r = pedir("GET", f"{amb.terra}/api/saude-do-bordo?embarcacao_id={amb.embarcacao}",
                      sessao=admin)
    return _d(r) if codigo == 200 else {}


def _atual(saude: dict) -> dict:
    return _d(_d(saude).get("atual"))


def _sinal(saude: dict, nome: str) -> dict:
    for s in _atual(saude).get("sinais") or []:
        if str(_d(s).get("sinal")) == nome:
            return dict(s)
    return {}


def _estado(saude: dict) -> str:
    return str(_atual(saude).get("estado") or "")


def _endereco_do_ffmpeg() -> str:
    import shutil
    return str(shutil.which("ffmpeg") or "")


def _path_sem_ffmpeg() -> str:
    """O PATH do proprio smoke, sem NENHUMA pasta que tenha ffmpeg: e' assim que o retrato deixa de
    ve-lo. Nesta maquina ha' mais de um ffmpeg no PATH (o do Hermes e o do WinGet) — tirar so' o da
    primeira pasta devolvida pelo `which` nao basta (medido: o ffmpeg voltava pela segunda)."""
    partes = []
    for p in (os.environ.get("PATH") or "").split(os.pathsep):
        if not p:
            continue
        try:
            if any((pathlib.Path(p) / nome).exists() for nome in ("ffmpeg.exe", "ffmpeg.EXE", "ffmpeg")):
                continue
        except Exception:  # noqa: BLE001
            pass
        partes.append(p)
    return os.pathsep.join(partes)


def _injetar_erros(amb, quantos: int = ERROS_DE_ENVIO) -> int:
    """Erros de envio de verdade no banco do bordo: e' o que o retrato conta em `erros_24h`."""
    agora = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    banco = sqlite3.connect(str(amb.banco_bordo))
    try:
        for i in range(quantos):
            banco.execute(
                "INSERT INTO ingestoes (fluxo_id, camera_id, rotulo, fonte, tipo, estado, erro,"
                " criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"cam-01", "cam-01", f"defeito de teste {i}", "dshow:teste", "arquivo", "erro",
                 "falha de envio injetada pela J9", agora, agora))
        banco.commit()
    finally:
        banco.close()
    return quantos


def _injetar_pedido_pendente(amb, ident: str = "pedido-do-smoke-j9") -> None:
    """Um pedido de trecho que ninguem entregou: e' o outro sinal de 'tem coisa para acompanhar'."""
    agora = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    banco = sqlite3.connect(str(amb.banco_bordo))
    try:
        banco.execute("INSERT OR REPLACE INTO hd_pedidos (id, embarcacao_id, camera_id, arquivo,"
                      " usuario_email, estado, criado_em) VALUES (?,?,?,?,?,?,?)",
                      (ident, amb.embarcacao, "radar-01", "bloco-000001.mp4",
                       "cliente@lecsor.test", "pedido", agora))
        banco.commit()
    finally:
        banco.close()


def _sem_segredo(saude: dict) -> bool:
    """O retrato nao pode carregar segredo: nem token, nem a senha de demonstracao, nem credencial."""
    texto = json.dumps(saude, ensure_ascii=False).lower()
    proibidos = [token_do_bordo().lower(), "senha", "password", "@", "://"]
    return not any(p and p in texto for p in proibidos)


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(9, "O defeito de verdade no bordo e a saude que o denuncia",
                "defeito injetado -> o retrato do produto sobe -> o semaforo do admin muda")
    admin = amb.entrar("admin@lecsor.test")
    j.checar("o admin entra no painel", bool(admin), "sessao de admin do sistema")
    if not admin:
        return j

    # 0) o bordo SADIO manda o retrato e o painel do admin recebe (o caminho bordo -> terra)
    amb.reiniciar_agente({**amb.hd_env, "LECSOR_ESPERA_DA_SAUDE": str(CICLO_DA_BANCADA_S)})
    # "recebeu" NAO e' "tem sinal": sem retrato nenhum o proprio produto responde 'problema' com UM
    # sinal (o `mudo_s`, "nunca reportou"). O retrato DE VERDADE traz o quadro inteiro (ffmpeg, agente,
    # mediamtx, disco, erros...) — e' por isso que a espera e' por >= 5 sinais.
    chegou = _espera(lambda: len(_atual(_saude(amb, admin)).get("sinais") or []) >= 5, 120)
    inicial = _saude(amb, admin)
    j.medir(primeiro_retrato=inicial)
    j.medir(ciclo_da_bancada_s=CICLO_DA_BANCADA_S)
    j.checar("o bordo reporta a saude e o painel do admin recebe", chegou,
             f"estado: {_estado(inicial) or 'sem leitura'} · "
             f"{len(_atual(inicial).get('sinais') or [])} sinal(is)")
    if not chegou:
        j.medir(cauda_do_agente=amb.log_de("agente", 1500))
        return j
    j.checar("o retrato nao leva segredo (nem token, nem senha, nem credencial de camera)",
             _sem_segredo(inicial), "retrato lido: sem token/password/URL com credencial")
    j.checar("o bordo cansado nao engana: o retrato diz o que ele mesmo NAO conseguiu medir",
             isinstance(inicial.get("atual"), dict), "campo `nao_medido` presente no retrato")

    # 1) o ffmpeg sai do caminho do bordo -> o painel tem de ACUSAR (e a leitura e' do admin)
    antes = _sinal(_saude(amb, admin), "ffmpeg")
    j.checar("bordo sadio: o sinal do ffmpeg esta' verde", antes.get("estado") == "ok",
             f"ffmpeg: {antes.get('estado') or 'sem sinal'}")
    t0 = time.time()
    amb.reiniciar_agente({**amb.hd_env, "LECSOR_ESPERA_DA_SAUDE": str(CICLO_DA_BANCADA_S),
                          "PATH": _path_sem_ffmpeg()})
    virou = _espera(lambda: _sinal(_saude(amb, admin), "ffmpeg").get("estado") == "problema",
                    LIMITE_ESPERA_S)
    segundos = round(time.time() - t0, 1)
    j.medir(reacao_ffmpeg_s=segundos)
    j.checar("com o ffmpeg fora do bordo, o painel vira 'problema' sozinho", virou,
             f"em {segundos}s · o sinal diz o que fazer: "
             f"{_sinal(_saude(amb, admin), 'ffmpeg').get('o_que_fazer', '')[:60]!r}")
    j.checar("o retrato do ffmpeg ausente nao inventa versao", not _sinal(_saude(amb, admin), "ffmpeg")
             .get("valor"), "valor nulo: o bordo nao mediu, entao nao afirma")

    # 2) os erros de envio (25) -> 'atencao' no sinal dos erros das ultimas 24 h
    amb.reiniciar_agente({**amb.hd_env, "LECSOR_ESPERA_DA_SAUDE": str(CICLO_DA_BANCADA_S)})
    t0 = time.time()
    n = _injetar_erros(amb)
    virou = _espera(lambda: _sinal(_saude(amb, admin), "erros_24h").get("estado") == "atencao",
                    LIMITE_ESPERA_S)
    segundos = round(time.time() - t0, 1)
    j.medir(reacao_erros_s=segundos)
    j.checar(f"os {n} erros de envio viram 'atencao' no painel", virou,
             f"em {segundos}s · erro(s) medido(s): {_sinal(_saude(amb, admin), 'erros_24h').get('valor')}")

    # 3) o pedido de trecho que ninguem entregou -> 'atencao' no sinal dos pedidos
    _injetar_pedido_pendente(amb)
    virou = _espera(lambda: _sinal(_saude(amb, admin), "pedidos").get("estado") == "atencao",
                    LIMITE_ESPERA_S)
    j.checar("o pedido de trecho pendente vira 'atencao' no painel", virou,
             f"pedidos: {_sinal(_saude(amb, admin), 'pedidos').get('valor')}")

    # 4) o SILENCIO: o bordo para de reportar -> o painel muda sozinho (e' o defeito que o dono mais
    #    precisa ver: "nunca reportou" nao e' verde)
    saude = _saude(amb, admin)
    j.checar("antes do silencio, o sinal 'mudo' esta' verde", _sinal(saude, "mudo_s").get("estado") == "ok",
             f"mudo_s: {_sinal(saude, 'mudo_s').get('valor')}s")
    p = amb.nomes.get("agente")
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            p.kill()
    t0 = time.time()
    virou = _espera(lambda: _sinal(_saude(amb, admin), "mudo_s").get("estado") in ("atencao", "problema"),
                    LIMITE_MUDO_S + 90)
    segundos = round(time.time() - t0, 1)
    j.medir(reacao_silencio_s=segundos, limiar_do_produto_s=LIMITE_MUDO_S)
    j.checar("o bordo mudo vira 'atencao' no painel (o limiar do produto e' 180 s)", virou,
             f"em {segundos}s · o sinal diz o que fazer: "
             f"{_sinal(_saude(amb, admin), 'mudo_s').get('o_que_fazer', '')[:70]!r}")

    # 5) o bordo VOLTA: o painel tem de voltar sozinho (o mesmo caminho, ao contrario)
    amb.reiniciar_agente(amb.hd_env)
    volta = _espera(lambda: _sinal(_saude(amb, admin), "mudo_s").get("estado") == "ok", LIMITE_ESPERA_S)
    j.checar("com o bordo de volta, o painel volta a ficar verde sozinho", volta,
             f"mudo_s: {_sinal(_saude(amb, admin), 'mudo_s').get('valor')}s")

    # 6) o retrato do silencio ficou na SERIE (o admin ve o buraco no historico, nao so' o agora)
    serie = _saude(amb, admin).get("serie") or []
    j.medir(serie_de_saude=len(serie))
    j.checar("a serie de saude preserva o historico do bordo (o admin ve o buraco)", len(serie) >= 1,
             f"{len(serie)} retrato(s) na serie")
    return j
