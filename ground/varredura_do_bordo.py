#!/usr/bin/env python3
"""VARREDURA DO BORDO (plano de 19/11/2026, Fase 2) — o app de captura olha a propria maquina.

O dono (19/11/2026): "o app a bordo pode carregar ja' com o inicio do sistema, faz a varredura das
cameras e radar, cadastra internamente, envia as informacoes pro admin, o admin configura e o cliente
passa a acessar na web" — e "cada app ja' deve ter seu id cadastrado no banco com o nome da empresa e
embarcacao, quando instalado em um computador de captura".

O que esta rotina faz (e o que NAO faz):

  * percorre os dispositivos que o ffmpeg enxerga NESTA maquina (`ingestao.listar_dispositivos()`) —
    nunca inventa dispositivo: sem camera, devolve lista vazia com o motivo;
  * cria a linha da camera na embarcacao que o pacote ja' traz (`LECSOR_EMBARCACAO`), com o ID derivado
    do SELETOR unico do dispositivo (`@device_pnp_...`, o que separa duas cameras de mesmo nome) e o
    dispositivo gravado em `config_local` — e' o que deixa ligar a camera sem envio de teste;
  * publica o cadastro no lado terra (`repasse.publicar_cadastro`) e espelha no Supabase, do mesmo jeito
    do cadastro pela tela — sem endereco de camera e sem credencial nenhuma;
  * NAO TOCA no que o admin configurou: alvo, ativo e a transmissao de uma camera que ja' existe nao sao
    sobrescritos por uma varredura (so' o rotulo acompanha o nome do dispositivo);
  * o RADAR nao vira camera: ele e' por embarcacao (`embarcacoes.radar_fonte`). Se a fonte ja' estiver
    declarada, a varredura diz se casou com um dispositivo; se nao estiver, so' RELATA o candidato e nao
    inventa fonte.
"""
from __future__ import annotations

import os
import re
import unicodedata

import licenca  # a embarcacao vem da LICENCA quando existe (senao, do ambiente do pacote)

# Nomes que, no Windows, aparecem em placa de captura/HDMI — o radar de oleo chega assim (dono,
# 19/11/2026: "receberemos as imagens ja' compiladas via hdmi"). E' so' PALPITE de relato: nada e'
# cadastrado a partir disto.
# Nomes ESPECIFICOS de placa de captura/HDMI. Nada generico ("usb video", "capture" sozinho): uma
# webcam comum aparece como "USB Video Device" e seria tratada como radar por engano.
PISTAS_DE_RADAR = ("radar", "oleo", "hdmi", "ezcap", "grabber", "video capture", "capture card")

_ULTIMA: dict = {}


def ultima() -> dict:
    """O resultado da ultima varredura desta maquina (o que a tela e a saude mostram)."""
    return dict(_ULTIMA)


def _slug(texto: str, limite: int = 44) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:limite] or "dispositivo"


def _id_da_camera(dispositivo: dict, existentes: set) -> str:
    """ID ESTAVEL do dispositivo: sai do seletor unico (`@device_pnp_...`), nao do nome amigavel.

    Duas webcams de mesmo nome tem seletores diferentes, logo ids diferentes — e o mesmo dispositivo,
    no mesmo lugar, mantem o mesmo id entre reinicios (a varredura nao duplica a camera).
    """
    base = _slug(dispositivo.get("seletor") or dispositivo.get("video") or "")
    candidato = "cam-" + base
    if candidato not in existentes:
        return candidato
    # seletor igual so' acontece para o MESMO dispositivo: id igual e' o comportamento correto.
    return candidato


def _embarcacao_do_pacote(embarcacao_id: str | None) -> str:
    """A embarcacao DESTA maquina: a da LICENCA (dono, 19/11/2026: "inserir a chave da licenca e assim
    fazer a conexao com a empresa e embarcacao cadastradas"), senao a do pacote (instalacao antiga)."""
    return str(embarcacao_id or licenca.embarcacao() or "").strip()


def _parece_radar(nome: str) -> bool:
    n = unicodedata.normalize("NFKD", (nome or "").lower()).encode("ascii", "ignore").decode()
    return any(p in n for p in PISTAS_DE_RADAR)


def varrer(embarcacao_id: str | None = None, aplicar: bool = True) -> dict:
    """Uma varredura. `aplicar=False` so' MEDE (nao escreve nada) — usado pelo relato.

    Devolve sempre um dicionario com `ok`, `motivo` quando nao deu, e as listas do que foi visto,
    cadastrado, atualizado e publicado. Sem dispositivo o resultado e' vazio COM motivo — nunca um
    sucesso falso.
    """
    import ingestao

    emb = _embarcacao_do_pacote(embarcacao_id)
    r: dict = {"ok": False, "embarcacao_id": emb, "maquina": "",
               "vistos": 0, "cadastradas": [], "atualizadas": [], "publicadas": [],
               "falhas_de_publicacao": [], "radar": {}, "motivo": ""}
    try:
        d = ingestao.listar_dispositivos()
    except Exception as e:  # noqa: BLE001
        r["motivo"] = f"nao consegui listar os dispositivos ({type(e).__name__}: {e})"
        _ULTIMA.clear()
        _ULTIMA.update(r)
        return r
    r["maquina"] = d.get("maquina") or ""
    dispositivos = list(d.get("dispositivos") or [])
    r["vistos"] = len(dispositivos)
    if not dispositivos:
        r["motivo"] = d.get("motivo") or d.get("erro") or "o ffmpeg nao encontrou dispositivo nesta maquina"
        _ULTIMA.clear()
        _ULTIMA.update(r)
        return r
    if not emb:
        r["motivo"] = ("esta maquina nao tem embarcacao definida: ative a CHAVE DE LICENCA (tela do "
                       "app) ou ponha LECSOR_EMBARCACAO — sem isso o cadastro automatico nao tem onde "
                       "pendurar as cameras")
        _ULTIMA.clear()
        _ULTIMA.update(r)
        return r

    import api
    with api.conexao() as c:
        if not c.execute("SELECT 1 FROM embarcacoes WHERE id=?", (emb,)).fetchone():
            r["motivo"] = f"a embarcacao '{emb}' do pacote nao existe no banco desta maquina"
            _ULTIMA.clear()
            _ULTIMA.update(r)
            return r
        existentes = {x["id"] for x in c.execute("SELECT id FROM cameras").fetchall()}
        fontes_radar = {x["id"]: (x["radar_fonte"] or "") for x in
                        c.execute("SELECT id,radar_fonte FROM embarcacoes").fetchall()}

    # RADAR: casa com a fonte declarada pela embarcacao; sem declaracao, so' relata o candidato.
    declarado = (fontes_radar.get(emb) or "").strip()
    candidatos = [x for x in dispositivos if _parece_radar(x.get("video") or "")]
    casado = ""
    if declarado:
        alvo = declarado.split("dshow:", 1)[1].strip() if declarado.startswith("dshow:") else declarado
        for x in dispositivos:
            if alvo and (alvo in (x.get("video") or "") or alvo == (x.get("seletor") or "")):
                casado = x.get("video") or ""
                break
    r["radar"] = {"fonte_declarada": declarado, "candidatos": [x.get("video") for x in candidatos],
                  "casou": casado, "cadastrado": False}

    cadastradas, atualizadas, publicadas, falhas = [], [], [], []
    achados = []  # o que a TELA mostra: o que encontrei e o que fiz com cada um
    if casado or (candidatos and not declarado):
        achados.append({"id": "", "rotulo": (casado or candidatos[0].get("video") or ""),
                        "radar": True, "cadastrada": False})
    for x in dispositivos:
        if _parece_radar(x.get("video") or "") and (casado == x.get("video") or not declarado):
            # O radar desta embarcacao nao vira camera: ele tem fonte propria por embarcacao.
            continue
        cid = _id_da_camera(x, existentes)
        rotulo = (x.get("rotulo") or x.get("video") or cid).strip()
        dispositivo = (x.get("seletor") or x.get("video") or "").strip()
        if not aplicar:
            (cadastradas if cid not in existentes else atualizadas).append(cid)
            achados.append({"id": cid, "rotulo": rotulo, "radar": False,
                            "cadastrada": cid in existentes})
            continue
        with api.conexao() as c:
            ja = c.execute("SELECT rotulo FROM cameras WHERE id=?", (cid,)).fetchone()
            if ja:
                # SO' o rotulo acompanha o dispositivo. `alvo`, `ativo` e a transmissao ficam como o
                # admin deixou: a varredura nao briga com a configuracao.
                # O NOME QUE O ADMIN DEU MANDA (dono, 23/11/2026: "a captura pega as informações e
                # replica no app de captura, inclusive os nomes das câmeras"): se a chave `rotulo`
                # ja' foi aplicada nesta maquina (config_local), a varredura NAO reescreve o nome.
                nomeado = c.execute("SELECT valor FROM config_local WHERE camera_id=? AND chave='rotulo'",
                                    (cid,)).fetchone()
                if not nomeado and (ja["rotulo"] or "") != rotulo:
                    c.execute("UPDATE cameras SET rotulo=? WHERE id=?", (rotulo, cid))
                atualizadas.append(cid)
            else:
                c.execute("""INSERT OR REPLACE INTO cameras
                             (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                             VALUES (?,?,?,?,'',1,'','','dshow','','')""", (cid, emb, rotulo, cid))
                cadastradas.append(cid)
            achados.append({"id": cid, "rotulo": rotulo, "radar": False, "cadastrada": bool(ja)})
            c.execute("""INSERT INTO config_local (camera_id,chave,valor,versao,atualizado_em)
                         VALUES (?,?,?,0,?)
                         ON CONFLICT(camera_id,chave) DO UPDATE SET valor=excluded.valor,
                           atualizado_em=excluded.atualizado_em""",
                      (cid, "dispositivo", dispositivo, api.em_iso()))
        existentes.add(cid)

    # Publicar em terra e espelhar no banco: a camera so' existe para o cliente DEPOIS disto.
    for cid in cadastradas + atualizadas:
        with api.conexao() as c:
            linha = c.execute("SELECT id,fluxo_id,rotulo,embarcacao_id,ativo FROM cameras WHERE id=?",
                              (cid,)).fetchone()
            nome_emb = c.execute("SELECT nome FROM embarcacoes WHERE id=?", (emb,)).fetchone()
        lado = {"ok": False, "motivo": "nao tentei"}
        try:
            import repasse
            lado = repasse.publicar_cadastro(dict(linha))
        except Exception as e:  # noqa: BLE001
            lado = {"ok": False, "motivo": f"{type(e).__name__}: {e}"}
        if lado.get("ok"):
            publicadas.append(cid)
        else:
            falhas.append({"camera": cid, "motivo": lado.get("motivo") or "publicacao recusada"})
        try:
            import supabase_escrita
            supabase_escrita.espelhar(dict(linha, embarcacao_nome=(nome_emb["nome"] if nome_emb else "")))
        except Exception:  # noqa: BLE001  (o espelho do Supabase nao impede operar: o SQLite e' o banco de operacao)
            pass

    if aplicar and (cadastradas or atualizadas):
        try:
            api.auditar(None, "varredura_do_bordo",
                        f"{emb}: +{','.join(cadastradas) or '-'} ~{','.join(atualizadas) or '-'}",
                        "")
        except Exception:  # noqa: BLE001
            pass

    # `ok` = a varredura ROLOU nesta maquina (viu dispositivo e sabia a embarcacao). Mudanca de cadastro
    # e' outra coisa: pode nao haver nada novo e a varredura estar perfeita.
    r.update(ok=True, cadastradas=cadastradas, atualizadas=atualizadas, publicadas=publicadas,
             falhas_de_publicacao=falhas, dispositivos=achados, quando=api.em_iso())
    if not (cadastradas or atualizadas) and not r["motivo"]:
        r["motivo"] = "nenhum dispositivo novo ou alterado nesta varredura"
    _ULTIMA.clear()
    _ULTIMA.update(r)
    return r


def intervalo() -> int:
    """De quanto em quanto tempo re-varrer (o cabo/USB pode entrar depois do boot)."""
    try:
        v = int(os.environ.get("LECSOR_ESPERA_DA_VARREDURA", "300"))
    except ValueError:
        v = 300
    return max(30, min(3600, v))


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(varrer(aplicar="--medir" not in sys.argv), ensure_ascii=False, indent=2))
