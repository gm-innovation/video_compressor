#!/usr/bin/env python3
"""J1 — Instalar e vincular: a chave de licenca liga o PC de captura a embarcacao.

Acao do usuario: o admin gera a chave no painel; o PC de captura (recem-instalado, sem usuario e sem
token) digita a chave.
Efeito: o bordo guarda o vinculo, e a camera do barco passa a existir NO LADO TERRA (o cliente so'
ve' a camera depois disto).
Medida: a embarcacao da chave e' a esperada; a camera aparece na lista do admin; a trilha registra a
geracao (e a chave NAO aparece na trilha — so' a pegada).
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ambiente import pedir, sql, token_do_bordo  # noqa: E402
from relatorio import Jornada  # noqa: E402


def rodar(amb, ctx: dict) -> Jornada:
    j = Jornada(1, "Instalar e vincular (chave -> embarcacao -> camera no lado terra)",
                "quem cadastra a embarcacao e' o admin; a chave e' a credencial do PC de captura")
    camera = ctx.get("camera") or "cam-01"
    emb = amb.embarcacao

    # 1) o operador/admin entra (a licenca so' o admin gera)
    sessao = amb.entrar("admin@lecsor.test")
    j.checar("o admin entra no painel do lado terra", bool(sessao),
             "cookie de sessao " + ("obtido" if sessao else "VAZIO"))
    if not sessao:
        j.erro = "sem sessao de admin nao da' para gerar a chave"
        return j
    ctx["sessao"] = sessao
    ctx["camera"] = camera

    # 2) o admin gera a chave DA EMBARCACAO
    codigo, r = amb.gerar_licenca(sessao, maquinas=2)
    chave = str(r.get("chave") or "")
    j.checar("o admin gera a chave no formato XXXX-XXXX-XXXX-XXXX", codigo == 201 and len(chave) == 19,
             f"HTTP {codigo} · {len(chave)} caracteres")
    if not chave:
        j.erro = f"nao veio chave ({r})"
        return j
    ctx["chave"] = chave

    # 3) a chave e' recusada quando esta' errada (prova negativa: nao entra qualquer coisa)
    c_ruim, r_ruim = amb.ativar_no_bordo("ZZZZ-ZZZZ-ZZZZ-ZZZZ")
    j.checar("a chave errada e' recusada pelo bordo", c_ruim in (403, 404, 422),
             f"HTTP {c_ruim} · {str(r_ruim.get('erro'))[:60]}")

    # 4) o PC DE CAPTURA digita a chave (sem sessao de usuario: a chave e' a credencial dele)
    codigo, r = amb.ativar_no_bordo(chave)
    lic = amb.licenca_do_bordo()
    j.checar("o bordo ativa a chave e guarda o vinculo", codigo == 200 and bool(lic.get("chave")),
             f"HTTP {codigo} · arquivo do vinculo " + ("gravado" if lic.get("chave") else "AUSENTE"))
    j.checar("a embarcacao do vinculo e' a da chave", str(lic.get("embarcacao_id") or "") == emb,
             f"vinculo={lic.get('embarcacao_id')!r} esperado={emb!r}")

    # 5) a camera do barco e' publicada no lado terra (caminho do produto: POST /api/publicacao no bordo)
    amb.camera_do_bordo(camera, fluxo=camera)
    codigo, texto = pedir("POST", f"{amb.bordo}/api/publicacao", {}, token=token_do_bordo(), bruto=True)
    publicado = "true" in str(texto).lower()
    j.checar("a camera do bordo e' publicada ao lado terra", codigo == 200,
             f"HTTP {codigo} · resposta {str(texto)[:80]}")

    # 6) o lado terra tem a camera, na embarcacao certa
    linhas = sql(amb.banco_terra, "SELECT id, embarcacao_id, ativo FROM cameras WHERE id=?", (camera,))
    j.checar("o lado terra guarda a camera na embarcacao do vinculo",
             bool(linhas) and str(linhas[0]["embarcacao_id"]) == emb,
             f"{dict(linhas[0]) if linhas else 'camera ausente no lado terra'}")
    if not publicado:
        j.medir(publicacao="o bordo respondeu que nao publicou (ver detalhe acima)")

    # 7) o ADMIN ve' a camera na tela (a rota que a tela do admin usa)
    codigo, r = pedir("GET", f"{amb.terra}/api/cameras", sessao=sessao)
    lista = r.get("cameras") if isinstance(r, dict) else None
    ids = [str(c.get("id")) for c in (lista or [])]
    j.checar("a camera aparece na lista que o admin/cliente enxerga", camera in ids,
             f"HTTP {codigo} · {len(ids)} camera(s): {', '.join(ids[:6])}")

    # 8) a licenca fica registrada no lado terra (autoridade) — e o uso por esta maquina
    dona = sql(amb.banco_terra, "SELECT id, embarcacao_id, status FROM licencas WHERE chave=?", (chave,))
    j.checar("a licenca fica registrada no lado terra para essa embarcacao",
             bool(dona) and str(dona[0]["embarcacao_id"]) == emb and str(dona[0]["status"]) == "ativa",
             str(dict(dona[0]) if dona else "licenca ausente no lado terra"))

    # 9) a trilha conta a acao — e a chave NUNCA entra na trilha (so' a pegada)
    trilha = sql(amb.banco_terra, "SELECT acao, alvo FROM auditoria_acesso ORDER BY id DESC LIMIT 60")
    acoes = [str(t["acao"]) for t in trilha]
    j.checar("a trilha registra a geracao da chave", any("licenca" in a for a in acoes),
             f"acoes vistas: {', '.join(sorted(set(acoes))[:6])}")
    vazou = [t["alvo"] for t in trilha if chave and chave.replace("-", "") in str(t["alvo"] or "").replace("-", "")]
    j.checar("a chave NAO aparece na trilha de auditoria (so' a pegada)", not vazou,
             f"{len(vazou)} linha(s) com a chave" if vazou else "nenhuma linha com a chave")

    j.medir(embarcacao=emb, camera=camera, chave_formato=f"{chave[:4]}-****-****-{chave[-4:]}",
            cameras_no_terra=len(ids))
    return j
