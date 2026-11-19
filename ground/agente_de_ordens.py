#!/usr/bin/env python3
"""Agente de ordens do BORDO: obedece o que o cliente pediu na tela web.

Ligacao (17/11/2026): o CLIENTE inicia a transmissao pela web; a ordem NASCE no lado terra e este
agente, que roda na maquina de captura, pergunta e executa. **Nao ha' tecnico confirmando nada na
embarcacao** (decisao do dono) e **o bordo nao abre porta nenhuma**: quem mantem a ligacao e' este
agente, que segura a resposta do lado terra ate' aparecer ordem (espera longa) e obedece direto.

O que ele faz com cada ordem:
  - `iniciar` -> chama a API LOCAL (`/api/cameras/ligar`) e a camera entra no ar (mesma cadeia do
    "Enviar video": comprime nesta maquina e o fluxo comprimido vai para o lado terra);
  - `parar`   -> chama `/api/cameras/desligar` e a camera sai do ar.
Alem disso, o agente OLHA a CONFIGURACAO publicada por terra (0.8.0): `GET /api/config-desejada` traz as
chaves que o admin publicou (alvo por camera, teto, ...); ele aplica SO' a diferenca pela API local
(`POST /api/config/aplicar`), guarda o que ja' aplicou em disco e confirma em `POST /api/config-aplicada`
— inclusive o que RECUSOU, com o motivo. Sem lado terra novo (404), ele segue so' com a flag.

O agente guarda o que ELE ligou e corta sozinho depois do TETO (`LECSOR_TETO_DO_BORDO` ou o que o admin
publicou em `teto_s`, padrao 2 h): e' a rede de seguranca do envio ORFAO — a ordem foi entregue, o `parar` nunca chegou e a
camera ficaria no ar para sempre. So' mexe no que ele mesmo ligou.
O resultado (abriu? falhou? por que?) volta ao lado terra, e e' isso que aparece no historico do
cliente.

Uso (roda junto com o app de captura):
    python ground/agente_de_ordens.py                 # fica vivo, perguntando o lado terra
    python ground/agente_de_ordens.py --uma-vez       # atende o que existe agora e sai (teste)
    python ground/agente_de_ordens.py --espera 5      # tempo de cada pergunta

Ambiente (o mesmo do envio ao lado terra):
    LECSOR_LADO_TERRA_API   base HTTP do lado terra (senao: host do LECSOR_DESTINO_SRT + porta)
    LECSOR_DESTINO_SRT      host:porta do SRT do lado terra (para descobrir a base HTTP)
    LECSOR_TOKEN_INGESTAO   token do bordo (obrigatorio)
    LECSOR_EMBARCACAO       embarcacao DESTA maquina (obrigatorio: a ordem e' dela)
    LECSOR_PORTA_LOCAL      porta da API local (padrao: LECSOR_PORTA_API ou 8085)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LOG_DIR = RAIZ / "ground" / "ordens" / "log"
ESPERA_PADRAO = 20.0
TETO_DO_BORDO_PADRAO = 7200.0      # 2 h: o maior tempo que o produto oferece ao cliente

# O que ESTE agente ligou e ainda nao foi mandado parar: {fluxo: {"camera_id", "desde"}}.
# Fica em DISCO (ground/ordens/ligados.json): se o agente reiniciar (reboot da maquina de captura),
# ele ainda sabe o que estava no ar — sem isso, a camera ficaria ligada para sempre depois do reboot.
LIGADOS: dict[str, dict] = {}


def caminho_do_estado() -> Path:
    """Onde fica o que este agente ligou (LECSOR_ORDENS_ESTADO troca o caminho — usado nos testes)."""
    trocado = (os.environ.get("LECSOR_ORDENS_ESTADO") or "").strip()
    return Path(trocado) if trocado else (LOG_DIR.parent / "ligados.json")


def _carregar_ligados() -> dict:
    """Le do disco o que ja' estava ligado. Arquivo torto/ausente nao derruba o agente."""
    try:
        d = json.loads(caminho_do_estado().read_text(encoding="utf-8"))
        return {str(k): v for k, v in d.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _salvar_ligados() -> None:
    """Guarda o que esta' ligado. Falhar aqui nao pode derrubar o atendimento das ordens."""
    try:
        alvo = caminho_do_estado()
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(json.dumps(LIGADOS, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        _log(f"aviso: nao consegui guardar o que liguei ({type(e).__name__}: {e})")


def teto_do_bordo() -> float:
    """Teto LOCAL do bordo (segundos).

    A configuracao PUBLICADA por terra manda (0.8.0): o admin define o teto no painel e o bordo aplica
    aqui (`config_local`). Sem config publicada, vale o env `LECSOR_TETO_DO_BORDO`; valor torto volta ao
    padrao — o bordo nunca fica sem teto.
    """
    try:
        import sqlite3
        if str(RAIZ / "ground") not in sys.path:
            sys.path.insert(0, str(RAIZ / "ground"))
        from ferramentas import caminho_banco
        c = sqlite3.connect(caminho_banco(), timeout=10)
        c.row_factory = sqlite3.Row
        try:
            linha = c.execute("""SELECT valor FROM config_local WHERE camera_id='' AND chave='teto_s'"""
                              ).fetchone()
        finally:
            c.close()
        if linha and str(linha["valor"]).strip():
            v = float(linha["valor"])
            if v > 0:
                return v
    except Exception:  # noqa: BLE001  (banco ausente/torto: cai no env)
        pass
    try:
        v = float(os.environ.get("LECSOR_TETO_DO_BORDO") or TETO_DO_BORDO_PADRAO)
    except Exception:
        v = TETO_DO_BORDO_PADRAO
    return v if v > 0 else TETO_DO_BORDO_PADRAO


def _log(linha: str) -> None:
    texto = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {linha}"
    print(texto, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "agente-de-ordens.log").open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except Exception:
        pass


def base_do_lado_terra() -> str:
    base = (os.environ.get("LECSOR_LADO_TERRA_API") or "").strip().rstrip("/")
    if base:
        return base
    host = (os.environ.get("LECSOR_DESTINO_SRT") or "").split(":")[0].strip()
    porta = (os.environ.get("LECSOR_PORTA_API") or "8085").strip() or "8085"
    return f"http://{host}:{porta}" if host else ""


def base_local() -> str:
    porta = (os.environ.get("LECSOR_PORTA_LOCAL") or os.environ.get("LECSOR_PORTA_API") or "8085").strip()
    return f"http://127.0.0.1:{porta or '8085'}"


def _http(metodo: str, url: str, corpo: dict | None = None, token: str = "", timeout: float = 40.0):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cabecalhos = {"Content-Type": "application/json"} if dados else {}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _chave(acao: str) -> str:
    return "/api/cameras/ligar" if acao == "iniciar" else "/api/cameras/desligar"


def atender(ordem: dict, local: str, base: str, token: str) -> dict:
    """Executa UMA ordem e conta o resultado ao lado terra. Nunca inventa sucesso."""
    cam_id = str(ordem.get("camera_id") or "").strip()
    acao = str(ordem.get("acao") or "").strip()
    if not cam_id or acao not in ("iniciar", "parar"):
        return {"ok": False, "motivo": f"ordem invalida ({acao} / {cam_id})"}
    try:
        s, r = _http("POST", local + _chave(acao), {"camera_id": cam_id})
    except Exception as e:
        # a API local fora do ar NAO pode virar "atendida": a ordem falha e o lado terra fica sabendo
        s, r = 0, {"erro": f"nao alcancei a API local ({type(e).__name__}: {e})"}
    if s == 200 and not r.get("erro"):
        detalhe = f"camera {cam_id}: {acao} feito"
    else:
        erro = str(r.get("erro") or f"a API local respondeu {s}")
        detalhe = f"camera {cam_id}: {acao} falhou ({erro})"
        _log(detalhe)
    deu_certo = s == 200 and not r.get("erro")
    corpo = {"estado": "atendida" if deu_certo else "erro",
             "resultado": detalhe, "fluxo_id": str(r.get("fluxo_id") or ordem.get("fluxo_id") or "")}
    if deu_certo and acao == "iniciar":
        fluxo = corpo["fluxo_id"] or cam_id
        LIGADOS[fluxo] = {"camera_id": cam_id, "desde": time.time()}
        _salvar_ligados()
    elif acao == "parar":
        # o lado terra mandou parar: sai da conta do teto (mesmo se a ordem falhou, nao insistimos)
        for f in [f for f, d in LIGADOS.items() if d.get("camera_id") == cam_id or f == corpo["fluxo_id"]]:
            LIGADOS.pop(f, None)
        _salvar_ligados()
    # o resultado volta pelo mesmo lado terra que deu a ordem
    try:
        s2, r2 = _http("POST", f"{base}/api/ordens/{ordem['id']}/resultado", corpo, token=token)
    except Exception as e:
        _log(f"aviso: nao consegui contar o resultado da ordem {ordem['id']} ({type(e).__name__}: {e})")
        return {"ok": False, "resultado": detalhe, "resposta_lado_terra": {}}
    if s2 != 200:
        _log(f"aviso: nao consegui contar o resultado da ordem {ordem['id']} ({s2} {r2.get('erro')})")
    return {"ok": corpo["estado"] == "atendida", "resultado": detalhe, "resposta_lado_terra": r2}


def vigiar_teto(local: str) -> list[dict]:
    """Corta no PROPRIO bordo o envio que passou do teto sem ordem viva (envio orfao).

    O lado terra ja' corta pelo tempo da sessao; isto cobre o caso em que o `parar` nunca chegou
    (a ordem foi atendida por outro caminho). So' mexe no que ESTE agente ligou, e diz na cara quando
    nao conseguiu desligar — nunca finge que cortou.
    """
    agora, teto, cortados = time.time(), teto_do_bordo(), []
    for fluxo, dado in list(LIGADOS.items()):
        passou = agora - float(dado.get("desde") or agora)
        if passou < teto:
            continue
        cam = str(dado.get("camera_id") or fluxo)
        try:
            s, r = _http("POST", local + "/api/cameras/desligar", {"camera_id": cam})
        except Exception as e:
            s, r = 0, {"erro": f"nao alcancei a API local ({type(e).__name__}: {e})"}
        if s == 200 and not r.get("erro"):
            _log(f"teto do bordo: a camera {cam} passou de {teto:g}s sem ordem viva — desliguei")
            LIGADOS.pop(fluxo, None)
            _salvar_ligados()
            cortados.append({"fluxo": fluxo, "camera_id": cam})
        else:
            _log(f"teto do bordo: a camera {cam} passou de {teto:g}s sem ordem viva e eu NAO consegui "
                 f"desligar ({r.get('erro') or s}) — vou tentar de novo")
    return cortados


def ler_flag(base: str, token: str, emb: str):
    """Le a FLAG de terra (dono, 19/11/2026): o desejo por camera, na versao atual.

    Devolve `None` quando o lado terra ainda nao tem a rota (`/api/estado-desejado`) — nesse caso o
    agente cai na pergunta antiga das ordens, para nao parar em pe' com um lado terra mais velho.
    """
    s, j = _http("GET", f"{base}/api/estado-desejado?embarcacao_id={emb}", token=token, timeout=30)
    if s == 404 or (s == 422 and "rota" in str(j.get("erro") or "").lower()):
        return None
    if s != 200:
        _log(f"aviso: o lado terra recusou a leitura da flag ({s} {j.get('erro')})")
        return None
    return j


def _ligado(cam_id: str) -> str:
    """Fluxo deste camera se ESTE agente o tem no ar (senao string vazia)."""
    for fluxo, dado in LIGADOS.items():
        if str(dado.get("camera_id") or "") == cam_id:
            return fluxo
    return ""


def aplicar_flag(cameras: list, local: str, base: str, token: str, emb: str) -> dict:
    """Compara a flag de terra com o que ESTA' no ar aqui e age so' na diferenca. Nunca finge sucesso."""
    acoes, reais = [], []
    for cam in cameras:
        cam_id = str((cam or {}).get("camera_id") or "").strip()
        desejo = str((cam or {}).get("desejo") or "").strip()
        if not cam_id or desejo not in ("ligar", "parar"):
            continue
        fluxo_ligado = _ligado(cam_id)
        if desejo == "ligar" and not fluxo_ligado:
            s, r = _chamar_local(local, "iniciar", cam_id)
            if s == 200 and not r.get("erro"):
                fluxo = str(r.get("fluxo_id") or (cam or {}).get("fluxo_id") or cam_id)
                LIGADOS[fluxo] = {"camera_id": cam_id, "desde": time.time()}
                _salvar_ligados()
                _log(f"flag: o desejo virou LIGAR — abri a camera {cam_id} ({fluxo})")
                acoes.append({"camera_id": cam_id, "acao": "ligar", "ok": True})
            else:
                erro = str(r.get("erro") or f"a API local respondeu {s}")
                _log(f"flag: NAO consegui ligar a camera {cam_id} ({erro})")
                acoes.append({"camera_id": cam_id, "acao": "ligar", "ok": False, "erro": erro})
        elif desejo == "parar" and fluxo_ligado:
            s, r = _chamar_local(local, "desligar", cam_id)
            if s == 200 and not r.get("erro"):
                LIGADOS.pop(fluxo_ligado, None)
                _salvar_ligados()
                _log(f"flag: o desejo virou PARAR — desliguei a camera {cam_id}")
                acoes.append({"camera_id": cam_id, "acao": "parar", "ok": True})
            else:
                erro = str(r.get("erro") or f"a API local respondeu {s}")
                _log(f"flag: NAO consegui desligar a camera {cam_id} ({erro})")
                acoes.append({"camera_id": cam_id, "acao": "parar", "ok": False, "erro": erro})
        # o que eu conto e' o que esta' NO AR aqui, medido por mim (nao o que o lado terra esperava)
        fluxo_agora = _ligado(cam_id)
        ultima = [a for a in acoes if a["camera_id"] == cam_id and not a.get("ok")]
        reais.append({"camera_id": cam_id,
                      "estado": "no_ar" if fluxo_agora else ("erro" if ultima else "parado"),
                      "motivo": (ultima[-1].get("erro") if ultima else
                                 ("no ar por ordem do cliente" if fluxo_agora else "parada (ninguem assistindo)")),
                      "fluxo_id": fluxo_agora,
                      "desde": (time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.localtime(LIGADOS.get(fluxo_agora, {}).get("desde", time.time())))
                                if fluxo_agora else ""),
                      "versao_desejo": int((cam or {}).get("versao") or 0)})
    if reais:
        try:
            _http("POST", f"{base}/api/estado-real", {"embarcacao_id": emb, "cameras": reais}, token=token)
        except Exception as e:
            _log(f"aviso: nao consegui contar o estado real ao lado terra ({type(e).__name__}: {e})")
    return {"acoes": acoes, "reais": reais}


def _chamar_local(local: str, acao: str, cam_id: str):
    """Chama a API LOCAL desta maquina (quem captura e' ela). Erro de rede nao pode virar 'feito'."""
    try:
        return _http("POST", local + _chave(acao), {"camera_id": cam_id})
    except Exception as e:
        return 0, {"erro": f"nao alcancei a API local ({type(e).__name__}: {e})"}


def _http_bytes(url: str, dados: bytes, token: str):
    """Envia BYTES crus (o bloco do HD) — o mesmo caminho de saida do bordo, nunca uma porta aberta."""
    req = urllib.request.Request(url, data=dados, method="POST",
                                 headers={"Content-Type": "application/octet-stream",
                                          "Content-Length": str(len(dados)),
                                          "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"erro": f"{type(e).__name__}: {e}"}


def _gravacao_continua():
    """O modulo do HD do radar, se este pacote tiver (guardado: sem ele o agente segue normal)."""
    try:
        import gravacao_continua as g   # noqa: PLC0415
        return g
    except Exception:
        try:
            sys.path.insert(0, str(RAIZ / "ground"))
            import gravacao_continua as g   # noqa: PLC0415
            return g
        except Exception:
            return None


def publicar_catalogo(base: str, token: str, emb: str) -> None:
    """Publica o catalogo do HD do radar em terra: o cliente pesquisa por data e hora (nao sobe video)."""
    g = _gravacao_continua()
    if not g or not g.ligada():
        return
    try:
        resumo = g.resumo()
        blocos = g.blocos()[-500:]
        _http("POST", f"{base}/api/hd/catalogo",
              {"embarcacao_id": emb, "camera_id": g.camera(), "resumo": resumo, "blocos": blocos},
              token=token)
    except Exception as e:
        _log(f"aviso: nao consegui publicar o catalogo do HD ({type(e).__name__}: {e})")


def atender_pedidos(base: str, token: str, emb: str, pedidos: list) -> int:
    """Envia ao lado terra os blocos que o cliente pediu. Bloco que ja' saiu do HD volta como motivo."""
    g = _gravacao_continua()
    if not g or not pedidos:
        return 0
    enviados = 0
    for p in pedidos[:5]:
        pid, arquivo = str(p.get("id") or ""), str(p.get("arquivo") or "")
        if not pid or not arquivo:
            continue
        caminho = g.diretorio() / Path(arquivo).name
        if not caminho.exists() or not caminho.is_file():
            _log(f"pedido {pid}: o bloco {arquivo} ja' saiu do HD (anel de disco)")
            _http("POST", f"{base}/api/hd/trecho?id={pid}&motivo=bloco+ja+saiu+do+HD+%28anel+de+disco%29",
                  {}, token=token)
            continue
        try:
            dados = caminho.read_bytes()
        except OSError as e:
            _log(f"pedido {pid}: nao consegui ler {arquivo} ({e})")
            continue
        s, r = _http_bytes(f"{base}/api/hd/trecho?id={pid}&arquivo={arquivo}", dados, token)
        if s == 200 and not r.get("erro"):
            enviados += 1
            _log(f"pedido {pid}: enviei o bloco {arquivo} ({len(dados)} B)")
        else:
            _log(f"pedido {pid}: o lado terra recusou o bloco {arquivo} ({s} {r.get('erro')})")
    return enviados


# ---------------------------------------------------------------------------------------------
# CONFIGURACAO PUBLICADA POR TERRA (0.8.0). O bordo OLHA o que terra publicou, aplica SO' a diferenca
# (guarda o que ja' aplicou em disco) e CONFIRMA — inclusive o que RECUSOU, com o motivo.
# ---------------------------------------------------------------------------------------------
JA_APLICADAS: dict[str, int] = {}
ULTIMA_CONFIG = 0.0


def caminho_da_config() -> Path:
    trocado = (os.environ.get("LECSOR_CONFIG_ESTADO") or "").strip()
    return Path(trocado) if trocado else (LOG_DIR.parent / "config_aplicada.json")


def _carregar_aplicadas() -> dict:
    try:
        dados = json.loads(caminho_da_config().read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in (dados or {}).items()}
    except Exception:  # noqa: BLE001  (arquivo torto/ausente nao derruba o agente)
        return {}


def _salvar_aplicadas() -> None:
    try:
        caminho_da_config().parent.mkdir(parents=True, exist_ok=True)
        caminho_da_config().write_text(json.dumps(JA_APLICADAS), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        _log(f"aviso: nao guardei o que ja' apliquei ({type(e).__name__}: {e})")


def intervalo_da_config() -> float:
    """De quanto em quanto tempo o bordo OLHA a configuracao (env `LECSOR_ESPERA_DA_CONFIG`, padrao 15 s).

    Configuracao muda raramente: olhar no ritmo da flag (2 s) seria gasto a toa.
    """
    try:
        v = float(os.environ.get("LECSOR_ESPERA_DA_CONFIG") or 15.0)
    except Exception:
        v = 15.0
    return min(600.0, max(2.0, v))


def ler_config(base: str, token: str, emb: str):
    """Le o que terra publicou. `None` quando o lado terra ainda nao tem a rota (compatibilidade)."""
    s, j = _http("GET", f"{base}/api/config-desejada?embarcacao_id={emb}", token=token, timeout=30)
    if s == 404 or (s == 422 and "rota" in str(j.get("erro") or "").lower()):
        return None
    if s != 200:
        _log(f"aviso: o lado terra recusou a leitura da configuracao ({s} {j.get('erro')})")
        return None
    return j


def _aplicar_transmitir(cam: str, valor: str, local: str) -> tuple[bool, str]:
    """`transmitir` ligado/desligado pelo admin EM TERRA: quem age e' este agente, pela API local.

    O admin publica; o bordo nao recebe conexao nenhuma — ele OLHA, age na diferenca e conta o que fez.
    Se a camera nao abrir, o motivo volta para terra em vez de virar "apliquei".
    """
    quer_ligar = str(valor or "").strip().lower() in ("1", "sim", "true", "ligar", "on", "ativo")
    if not cam:
        return False, "transmitir e' por camera: informe camera_id"
    ja_ligado = bool(_ligado(cam))
    if quer_ligar == ja_ligado:
        return True, ("ja' estava no ar" if ja_ligado else "ja' estava parada")
    s, r = _chamar_local(local, "iniciar" if quer_ligar else "desligar", cam)
    if s == 200 and not r.get("erro"):
        if quer_ligar:
            fluxo = str(r.get("fluxo_id") or cam)
            LIGADOS[fluxo] = {"camera_id": cam, "desde": time.time(), "ordem": "admin(terra)"}
        else:
            LIGADOS.pop(_ligado(cam), None)
        _salvar_ligados()
        _log(f"config: transmitir={'ligar' if quer_ligar else 'parar'} — "
             f"{'abri' if quer_ligar else 'desliguei'} a camera {cam} por publicacao do admin")
        return True, ("no ar por publicacao do admin" if quer_ligar else "parada por publicacao do admin")
    return False, str(r.get("erro") or f"a API local respondeu {s}")


def aplicar_config(cfg, local: str, base: str, token: str, emb: str) -> dict:
    """Aplica SO' a diferenca, valida antes (a API local decide) e conta o resultado ao lado terra."""
    global ULTIMA_CONFIG
    ULTIMA_CONFIG = time.time()
    if not cfg:
        return {"aplicadas": [], "recusadas": []}
    aplicadas, recusadas = [], []
    for item in cfg.get("chaves") or []:
        cam = str((item or {}).get("camera_id") or "")
        chave = str((item or {}).get("chave") or "")
        valor = str((item or {}).get("valor") or "")
        if not chave:
            continue
        try:
            versao = int((item or {}).get("versao") or 0)
        except (TypeError, ValueError):
            versao = 0
        marca = f"{cam}|{chave}"
        if versao and versao <= int(JA_APLICADAS.get(marca, 0)):
            continue                                    # ja' apliquei esta versao: nao repito
        if chave == "transmitir":
            # Ligar/desligar a transmissao NAO passa pela rota de configuracao: quem age e' o agente,
            # pelo mesmo caminho local que a flag usa (dono, 19/11/2026: a flag pode ser acionada
            # "pelo usuario ou automatica"). Falhou -> nao congelo a versao, para tentar de novo.
            ok_t, motivo_t = _aplicar_transmitir(cam, valor, local)
            if ok_t:
                JA_APLICADAS[marca] = versao
                aplicadas.append({"camera_id": cam, "chave": chave, "valor": valor, "versao": versao,
                                  "motivo": motivo_t})
            else:
                _log(f"config: NAO apliquei transmitir={valor} ({cam}): {motivo_t}")
                recusadas.append({"camera_id": cam, "chave": chave, "valor": valor, "versao": versao,
                                  "motivo": motivo_t})
            continue
        s, r = _http("POST", local + "/api/config/aplicar",
                     {"camera_id": cam, "chave": chave, "valor": valor})
        if s == 200 and r.get("ok"):
            JA_APLICADAS[marca] = versao
            aplicadas.append({"camera_id": cam, "chave": chave, "valor": valor, "versao": versao,
                              "motivo": str(r.get("motivo") or "")})
            _log(f"config: apliquei {chave}={valor} ({cam or 'embarcacao'}) v{versao}")
        else:
            motivo = str(r.get("motivo") or r.get("erro") or f"a API local respondeu {s}")
            if s == 422:                                # recusa DEFINITIVA desta versao (a tela mostra)
                JA_APLICADAS[marca] = versao
            recusadas.append({"camera_id": cam, "chave": chave, "valor": valor, "versao": versao,
                              "motivo": motivo})
            _log(f"config: RECUSEI {chave}={valor} ({cam or 'embarcacao'}): {motivo}")
    if aplicadas or recusadas:
        _salvar_aplicadas()
        try:
            _http("POST", f"{base}/api/config-aplicada",
                  {"embarcacao_id": emb, "versao": cfg.get("versao"),
                   "aplicadas": aplicadas, "recusadas": recusadas}, token=token)
        except Exception as e:  # noqa: BLE001
            _log(f"aviso: nao consegui contar ao lado terra o que apliquei ({type(e).__name__}: {e})")
    return {"aplicadas": aplicadas, "recusadas": recusadas}


def intervalo_da_flag() -> float:
    """De quanto em quanto tempo o bordo OLHA a flag (env `LECSOR_ESPERA_DA_FLAG`, padrao 2 s)."""
    try:
        v = float(os.environ.get("LECSOR_ESPERA_DA_FLAG") or 2.0)
    except Exception:
        v = 2.0
    return min(30.0, max(0.5, v))


# ---------------------------------------------------------------------------------------------
# SAUDE DO BORDO (0.8.0, Fase 5). O bordo CONTA como ele esta' (mesmo caminho de saida de sempre) e
# escreve o proprio "estive aqui" — e' a idade desse arquivo que o retrato usa para dizer se o laco
# esta' vivo. Terra so' guarda e classifica.
# ---------------------------------------------------------------------------------------------
ULTIMA_SAUDE = 0.0
RODADAS = 0


def intervalo_da_saude() -> float:
    """De quanto em quanto tempo o bordo reporta a saude (env `LECSOR_ESPERA_DA_SAUDE`, padrao 60 s)."""
    try:
        v = float(os.environ.get("LECSOR_ESPERA_DA_SAUDE") or 60.0)
    except Exception:  # noqa: BLE001
        v = 60.0
    return min(3600.0, max(10.0, v))


def caminho_do_vivo() -> Path:
    trocado = (os.environ.get("LECSOR_AGENTE_ESTADO") or "").strip()
    return Path(trocado) if trocado else (LOG_DIR.parent / "agente-vivo.json")


def marcar_vivo() -> None:
    global RODADAS
    RODADAS += 1
    try:
        caminho_do_vivo().parent.mkdir(parents=True, exist_ok=True)
        caminho_do_vivo().write_text(json.dumps({"em": time.strftime("%Y-%m-%dT%H:%M:%S"), "rodadas": RODADAS}),
                                     encoding="utf-8")
    except Exception:  # noqa: BLE001  (nao poder escrever aqui nao pode derrubar a rodada)
        pass


def retrato_de_saude() -> dict:
    """O retrato montado NO BORDO. Sem segredo nenhum; import tardio para o agente nao pesar no boot."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import saude_do_bordo
        return saude_do_bordo.retrato()
    except Exception as e:  # noqa: BLE001
        return {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "nao_medido": {"retrato": f"{type(e).__name__}: {e}"}}


def enviar_saude(base: str, token: str, emb: str) -> dict:
    """Manda o retrato para o admin. Falha aqui NAO derruba nada: a captura continua."""
    global ULTIMA_SAUDE
    ULTIMA_SAUDE = time.time()
    retrato = retrato_de_saude()
    try:
        s, r = _http("POST", f"{base}/api/saude-do-bordo", {"embarcacao_id": emb, "retrato": retrato},
                     token=token, timeout=60)
        if s != 200:
            _log(f"aviso: o lado terra recusou a saude do bordo ({s} {r.get('erro')})")
        return r if isinstance(r, dict) else {}
    except Exception as e:  # noqa: BLE001
        _log(f"aviso: nao consegui enviar a saude do bordo ({type(e).__name__}: {e})")
        return {}


def uma_rodada(base: str, local: str, token: str, emb: str, espera: float) -> int:
    marcar_vivo()
    # A FLAG VEM PRIMEIRO (dono, 19/11/2026): o computador de captura nao recebe conexao nenhuma — ele
    # olha para terra. A fila de ordens continua sendo atendida quando existir (lado terra mais velho).
    flag = ler_flag(base, token, emb)
    if flag is not None:
        aplicar_flag(flag.get("cameras") or [], local, base, token, emb)
        atender_pedidos(base, token, emb, flag.get("pedidos") or [])
        publicar_catalogo(base, token, emb)
        if time.time() - ULTIMA_CONFIG >= intervalo_da_config():
            aplicar_config(ler_config(base, token, emb), local, base, token, emb)
        if time.time() - ULTIMA_SAUDE >= intervalo_da_saude():
            enviar_saude(base, token, emb)
        vigiar_teto(local)
        time.sleep(intervalo_da_flag())   # olhar de novo em instantes, sem martelar o lado terra
        return 0
    s, j = _http("GET", f"{base}/api/ordens?embarcacao_id={emb}&espera={espera:g}", token=token,
                 timeout=max(40.0, espera + 20))
    if s != 200:
        _log(f"aviso: o lado terra recusou a pergunta das ordens ({s} {j.get('erro')})")
        return 0
    ordens = j.get("ordens") or []
    if time.time() - ULTIMA_SAUDE >= intervalo_da_saude():
        enviar_saude(base, token, emb)
    if ordens:
        _log(f"recebi {len(ordens)} ordem(ns) do lado terra")
    for ordem in ordens:
        try:
            atender(ordem, local, base, token)
        except Exception as e:   # uma ordem torta nao pode parar as outras
            _log(f"aviso: falha ao atender a ordem {ordem.get('id')} ({type(e).__name__}: {e})")
    vigiar_teto(local)
    return len(ordens)


def principal() -> int:
    args = sys.argv[1:]
    uma_vez = "--uma-vez" in args
    espera = ESPERA_PADRAO
    if "--espera" in args:
        try:
            espera = float(args[args.index("--espera") + 1])
        except Exception:
            espera = ESPERA_PADRAO
    base = base_do_lado_terra()
    local = base_local()
    token = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
    emb = (os.environ.get("LECSOR_EMBARCACAO") or "").strip()
    if not base or not token or not emb:
        _log("sem lado terra, sem LECSOR_TOKEN_INGESTAO ou sem LECSOR_EMBARCACAO: o agente nao pergunta "
             "nada (a ordem do cliente nao chega nesta maquina). Configure o mesmo ambiente do envio.")
        return 2
    LIGADOS.clear()
    LIGADOS.update(_carregar_ligados())
    JA_APLICADAS.clear()
    JA_APLICADAS.update(_carregar_aplicadas())
    _log(f"agente de ordens no ar: embarcacao {emb} · lado terra {base} · API local {local}"
         + (f" · {len(LIGADOS)} envio(s) meu(s) no ar antes de eu comecar" if LIGADOS else ""))
    while True:
        try:
            uma_rodada(base, local, token, emb, espera)
        except Exception as e:
            _log(f"aviso: falha na rodada ({type(e).__name__}: {e})")
            time.sleep(2)
        if uma_vez:
            return 0


if __name__ == "__main__":
    raise SystemExit(principal())
