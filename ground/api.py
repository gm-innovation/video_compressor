#!/usr/bin/env python3
"""API do produto (Fase 3 + Fase 4) — banco, modulo de acompanhamento e porta unica do video.

Regras que o codigo tem de garantir:
- medicao sem valor+fonte+data+hardware_versao+comando NAO entra (o banco recusa);
- o navegador do cliente NUNCA recebe credencial de camera nem endereco de servico interno:
  ele fala so com esta API, que decide se pode e encaminha a sessao WebRTC ao mediamtx;
- todo acesso a video fica registrado em auditoria (quem viu qual camera, quando);
- escrita vinda da propria bancada (loopback) e aceita; escrita remota exige sessao e papel.

Uso: python ground/api.py [porta] [--semear-demo]
"""
from __future__ import annotations
import datetime as dt
import hashlib
import hmac
import json
import re
import os
import secrets
import socket
import sqlite3
import subprocess
import time
import sys
import threading
import urllib.error
import urllib.parse
from urllib.parse import parse_qs, urlparse
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---- captura vista pelo Admin (dono, 16/11/2026)
# O Admin (tela servida pelo lado terra) precisa enxergar as cameras DESTA maquina e repassar o fluxo
# SEM trocar de aplicativo. Para isso o servidor LOCAL responde a origem do lado terra do proprio
# cliente nas rotas de captura. Fechado por padrao: so' as origens declaradas abaixo (ou a lista de
# LECSOR_CORS_ORIGENS) recebem o cabecalho; qualquer outra origem fica sem CORS e o navegador bloqueia.
# Esta lista responde a DUAS perguntas diferentes — quem decide cada uma e' `eh_rota_de_captura`
# (roteamento: a rota e' desta maquina) e `eh_rota_de_captura_cors` (CORS: quem de fora pode chama-la).
ROTAS_CAPTURA = ("/api/dispositivos", "/api/envios", "/api/ingestao", "/api/ingestoes",
                 "/api/compressao", "/api/compressoes", "/api/medicoes", "/api/trecho", "/api/captura",
                 "/api/publicacao", "/api/cameras/publicar",
                 # LIGAR/DESLIGAR e PRONTIDAO sao da MAQUINA DE CAPTURA (dono, 19/11/2026): sem estas
                 # entradas o servidor do bordo encaminhava o clique para o lado terra, que tentava
                 # `-f dshow` no Linux e respondia "Unknown input format: 'dshow'" / codigo 234 —
                 # era ISSO que aparecia na tela do dono ("as cameras nao religam").
                 "/api/cameras/ligar", "/api/cameras/desligar", "/api/cameras/prontidao",
                 # A configuracao que o bordo APLICA e' desta maquina (quem publica e' terra, e a
                 # publicacao chega pelo agente). Sem esta entrada, o servidor do bordo encaminharia o
                 # "aplicar" para o lado terra — que nao tem a camera nem o alvo.
                 "/api/config/aplicar",
                 # A VARREDURA e' desta MAQUINA (plano de 19/11/2026, Fase 2): quem varre os dispositivos
                 # e' o PC de captura. Sem esta entrada o servidor do bordo encaminhava o pedido ao lado
                 # terra e a tela mostrava a varredura — e o banco — de OUTRA maquina (medido: a resposta
                 # vinha com o banco do lado terra e 1 dispositivo, que era o do lado terra).
                 "/api/varredura")

# Rotas de captura que valem por IGUALDADE (nao por prefixo): quem esta' sentado nesta maquina entra
# no sistema AQUI. O plano de 19/11/2026 (Fase 3) mediu que, sem isto, o bordo encaminhava `/api/entrar`
# para terra: a pessoa entrava, mas a sessao so' existia do outro lado e o cadastro local respondia 401 —
# o bordo ficava sem a camera que ele mesmo acabou de cadastrar.
ROTAS_CAPTURA_LOCAIS = ("/api/entrar", "/api/eu", "/api/sair", "/api/cameras",
                        # CHAVE DE LICENCA (dono, 19/11/2026): a tela da chave roda NA PROPRIA maquina
                        # de captura e quem fala com o lado terra e' o bordo — mesmo desenho das rotas
                        # de captura acima. `/api/licencas` (plural) e' do painel do lado terra e NAO
                        # entra aqui: essa e' encaminhada como qualquer rota de administracao.
                        "/api/licenca", "/api/licenca/ativar", "/api/licenca/esquecer", "/licenca",
                        # PAINEL DO BORDO (dono, 23/11/2026): "no pc de captura ninguém precisa abrir
                        # nada, tudo deve ser feito no admin e cliente, o app de captura deve ser
                        # autônomo". A tela de ENTRADA desta máquina é este painel — servido pelo próprio
                        # bordo, sem login — e é ele que diz se a licença, o token, o agente, a varredura
                        # e a publicação estão de pé.
                        "/bordo", "/api/bordo",
                        # A SERIE da saude (dono, 24/11/2026): o historico e' LOCAL desta maquina (e' o
                        # proprio bordo que mede). Sem esta entrada o pedido do grafico era encaminhado
                        # ao lado terra, que nao tem o anel deste PC de captura.
                        "/api/bordo/serie",
                        # DETALHE da camera: e' o cadastro DESTA maquina (com o endereco, que so' existe
                        # aqui). Sem esta entrada o painel do bordo (que mostra as cameras de rede)
                        # encaminhava o pedido ao lado terra e a tela vinha vazia/502.
                        "/api/cameras/detalhe")
ORIGENS_CAPTURA_PADRAO = ("http://187.127.60.250:8085", "http://127.0.0.1:8085",
                          "http://127.0.0.1:8765", "http://localhost:8765")


def origens_captura() -> tuple:
    bruto = os.environ.get("LECSOR_CORS_ORIGENS")
    if bruto is None:
        return ORIGENS_CAPTURA_PADRAO
    return tuple(o.strip() for o in bruto.split(",") if o.strip())


def eh_rota_de_captura(rota: str) -> bool:
    """Esta rota e' DESTA maquina (roteamento): aqui ela nao vai para o lado terra."""
    if rota in ROTAS_CAPTURA_LOCAIS:
        return True
    # O CRUD DA CAMERA e' DESTA maquina: `/api/cameras/<id>/<acao>` (segredo/editar/remover/nome/ativo).
    # O cadastro da camera vive aqui (o endereco de uma camera de rede so' existe nesta maquina — dono,
    # 25/11/2026: "senha nao pode vazar, tem que tudo ficar no bordo"). Sem estas entradas o painel do
    # bordo encaminhava o pedido ao lado terra (que nao tem o segredo nem o cadastro local) -> 502.
    if rota.startswith("/api/cameras/") and rota.rsplit("/", 1)[-1] in (
            "segredo", "editar", "remover", "nome", "ativo"):
        return True
    return any(rota == r or rota.startswith(r + "/") for r in ROTAS_CAPTURA)


def eh_rota_de_captura_cors(rota: str) -> bool:
    """Rotas que a pagina do LADO TERRA chama AQUI, de outra origem (so' estas levam CORS).

    Duas perguntas DIFERENTES, que ja' estiveram juntas e nao podiam estar (medido em 24/11/2026):

      * "de quem e' esta rota?" (roteamento) -> `eh_rota_de_captura`, que inclui as ROTAS_CAPTURA_LOCAIS
        (entrar/sair/eu/cameras/licenca/bordo): quem esta' sentado nesta maquina entra AQUI;
      * "quem de fora pode chama-la pelo navegador?" (CORS) -> SO' as rotas do Admin que a pagina do
        lado terra chama nesta maquina (a tela "Enviar video"). E' a mesma lista que o front usa em
        `admin/admin.js` (`ROTAS_CAPTURA`).

    A entrada, o cadastro e a licenca sao servidos pela MESMA origem que os usa: nao precisam de CORS
    e nao podem te-lo (uma origem declarada poderia entrar/agir no lugar da pessoa). Com a lista unica,
    `/api/eu` respondia `Access-Control-Allow-Origin` e o pre-voo devolvia 204 — provas 04 e 05 de
    `tests/test_captura_no_admin.py`.
    """
    return any(rota == r or rota.startswith(r + "/") for r in ROTAS_CAPTURA)
from ingestao import iniciar as ing_iniciar, parar as ing_parar, listar as ing_listar  # noqa: E402
from ingestao import desligar_camera as ing_desligar_camera, ligar_camera as ing_ligar_camera  # noqa: E402
from ingestao import capturar as ing_capturar, listar_dispositivos as ing_dispositivos, ao_vivo as ing_ao_vivo
from ingestao import maquina_de_captura as ing_maquina_de_captura  # noqa: E402
from ingestao import prontidao_das_cameras as ing_prontidao  # noqa: E402
import ingestao as ingestao_modulo  # noqa: E402  (endereco_da_camera: o apontamento da camera de rede)
from ingestao import limpar_vivos_mortos as ing_limpar_vivos
from ferramentas import caminho_banco, resumo as resumo_ferramentas  # noqa: E402
from ferramentas import carregar_ambiente  # noqa: E402
import etapas as etapas_pipeline  # noqa: E402
import gravacao as gravacao_modulo  # noqa: E402
import trecho as trecho_modulo  # noqa: E402
import producao as producao_pipeline  # noqa: E402
import licenca as licenca_modulo  # noqa: E402
import segredo_camera  # noqa: E402  (segredo da camera de rede: vive SO' no PC de captura)
from urllib.parse import parse_qs, unquote, urlparse

RAIZ = Path(__file__).resolve().parent.parent
COMPRIMIDOS = RAIZ / "ground" / "envios" / "comprimido"
BANCO = caminho_banco()
CAMPOS_OBRIGATORIOS = ("valor", "fonte", "data", "hardware_versao", "comando")
PORTA_WEBRTC, PORTA_HLS, PORTA_API_MEDIAMTX = 8889, 8888, 9997
_CACHE_METRICAS: dict = {}
# O painel do bordo (dono, 23/11/2026) mostra o DESEMPENHO do link: medir isso custa um ping e uma
# consulta ao mediamtx (~5 s). O painel se atualiza a cada 10 s e o link nao muda de segundo em
# segundo — um cache curto evita pagar 5 s toda vez sem mentir sobre o numero (ele e' "ha' quanto
# tempo foi medido" no proprio campo).
_CACHE_DESEMPENHO_BORDO: dict = {}
CACHE_DESEMPENHO_BORDO_S = 25.0
DURACAO_SESSAO_H = 12
INICIADO_EM = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
PAPEL_ADMIN = ("operador", "admin")
# tipo 4 do dono (19/11/2026, Petrobras): enxerga TODAS as embarcacoes de TODAS as empresas e SO'
# LEITURA — nenhuma rota de escrita/operacao aceita este papel (todas checam PAPEL_ADMIN), entao o
# observador nunca opera, nunca configura e nunca cadastra.
PAPEL_OBSERVADOR = "observador"
PAPEIS_VE_TUDO = PAPEL_ADMIN + (PAPEL_OBSERVADOR,)
PAPEIS_DE_USUARIO = ("cliente", "operador", "admin", "tecnico", PAPEL_OBSERVADOR)
# D4 do dono (25/11/2026, verbatim): "D4. so' admin". Vale para o CADASTRO e a EDICAO de
# empresa/embarcacao/camera/usuario. A OPERACAO (desligar, cancelar, escolher qualidade do que esta'
# no ar, enviar video) continua com operador+admin (`PAPEL_ADMIN`) — o dono so' tirou do operador o
# que e' CONFIGURAR. O usuario de captura segue cadastrando a camera NA PROPRIA maquina (regra de
# 19/11/2026), porque no PC de captura nao existe admin logado.
PAPEL_CONFIGURA = ("admin",)


def pode_configurar(u) -> bool:
    """Quem configura (cadastra/edita) — "so' admin", como o dono decidiu em 25/11/2026."""
    try:
        return bool(u and str(u["papel"]) in PAPEL_CONFIGURA)
    except Exception:  # noqa: BLE001
        return False


def _filhos_de(c: sqlite3.Connection, tabela: str, coluna: str) -> list[tuple[str, str]]:
    """(tabela, coluna) que REFERENCIAM `tabela.coluna` — lido do proprio banco (PRAGMA)."""
    achados: list[tuple[str, str]] = []
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        for fk in c.execute(f"PRAGMA foreign_key_list('{t}')"):
            if fk[2] == tabela and str(fk[4] or "") == coluna:
                achados.append((t, fk[3]))
    return achados


def renomear_identificador(tabela: str, id_antigo: str, id_novo: str) -> dict:
    """Troca a CHAVE de um cadastro (cliente/embarcacao) numa transacao UNICA.

    Dono (25/11/2026, D3): "renomeavel". Medido no banco: as chaves sao declaradas com `REFERENCES`
    e o banco roda com `PRAGMA foreign_keys=ON`, mas SEM `ON UPDATE CASCADE` — renomear o pai estoura
    se algum filho ainda apontar para o id antigo. Entao: FILHO PRIMEIRO, PAI DEPOIS, tudo numa
    transacao; qualquer falha volta tudo (nunca fica metade com o id antigo e metade com o novo).
    A descoberta da lista de filhos e' dinamica (PRAGMA) de proposito: tabela nova entra sozinha.
    """
    antigo, novo = str(id_antigo or "").strip(), str(id_novo or "").strip()
    if not antigo or not novo:
        return {"ok": False, "erro": "id vazio"}
    if not re.match(r"^[0-9a-zA-Z._\-]{1,64}$", novo):
        return {"ok": False, "erro": "identificador invalido: use letras, numeros, ponto, _ ou -"}
    if novo == antigo:
        return {"ok": True, "id": antigo, "mudou": False}
    with conexao() as c:
        if not c.execute(f"SELECT 1 FROM {tabela} WHERE id=?", (antigo,)).fetchone():
            return {"ok": False, "erro": "cadastro inexistente", "nao_encontrado": True}
        if c.execute(f"SELECT 1 FROM {tabela} WHERE id=?", (novo,)).fetchone():
            return {"ok": False, "erro": "ja existe um cadastro com esse identificador"}
        filhos = _filhos_de(c, tabela, "id")
        campos = [r[1] for r in c.execute(f"PRAGMA table_info({tabela})")]
        if "id" not in campos:
            return {"ok": False, "erro": "cadastro sem chave id"}
        c.execute("BEGIN IMMEDIATE")
        try:
            for t, col in filhos:
                c.execute(f"UPDATE {t} SET {col}=? WHERE {col}=?", (novo, antigo))
            c.execute(f"UPDATE {tabela} SET id=? WHERE id=?", (novo, antigo))
            if not c.execute(f"SELECT 1 FROM {tabela} WHERE id=?", (novo,)).fetchone():
                raise RuntimeError("o id novo nao ficou gravado")
            c.execute("COMMIT")
        except Exception as e:  # noqa: BLE001
            c.execute("ROLLBACK")
            return {"ok": False, "erro": f"nao renomeei (nada foi alterado): {type(e).__name__}: {e}"}
    return {"ok": True, "id": novo, "de": antigo, "mudou": True,
            "filhos_atualizados": [f"{t}.{col}" for t, col in filhos]}


def estado_do_segredo(camera_id: str) -> dict:
    """O que a tela (e a API) podem saber do segredo da camera de rede: NUNCA o valor.

    Devolve o estado e o CAMINHO do arquivo — o dono precisa saber onde por a senha no PC de captura.
    O caminho e' informacao de operacao; a senha, nao. Por isso este e' o unico recado sobre credencial
    que sai por HTTP (e ele nao tem como vazar porque nao carrega o valor).
    """
    return {"configurado": segredo_camera.configurado(str(camera_id)),
            "arquivo": str(segredo_camera.caminho(str(camera_id))),
            "origem": segredo_camera.origem(str(camera_id)),
            "formato": "uma linha `usuario:senha` no arquivo acima, NO PC DE CAPTURA"}


def conexao() -> sqlite3.Connection:
    c = sqlite3.connect(BANCO, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")     # integridade continua obrigatoria
    c.execute("PRAGMA busy_timeout=30000")
    try:
        c.execute("PRAGMA journal_mode=WAL")  # os medidores de encode escrevem enquanto a tela le
    except sqlite3.Error:
        pass
    return c


# --------------------------------------------------------------------------- senha e sessao
def hash_senha(senha: str, salt: str, interacoes: int = 200_000) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt), interacoes).hex()


def conferir_senha(usuario: sqlite3.Row, senha: str) -> bool:
    return secrets.compare_digest(hash_senha(senha, usuario["salt"], usuario["interacoes"]), usuario["senha_hash"])


def criar_sessao(usuario_id: str, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    expira = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=DURACAO_SESSAO_H)).isoformat(timespec="seconds")
    with conexao() as c:
        c.execute("INSERT INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                  (token, usuario_id, expira, user_agent[:200]))
    return token


def usuario_da_sessao(token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    with conexao() as c:
        u = c.execute("""SELECT u.* FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
                         WHERE s.token = ? AND s.expira_em > ? AND u.ativo = 1""",
                      (token, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))).fetchone()
    return u


def auditar(usuario, acao: str, alvo: str, ip: str = "") -> None:
    with conexao() as c:
        c.execute("INSERT INTO auditoria_acesso (usuario_id,email,acao,alvo,ip) VALUES (?,?,?,?,?)",
                  (usuario["id"] if usuario else None, usuario["email"] if usuario else "", acao, alvo, ip))


def licenca_bloqueio(embarcacao_id: str) -> str:
    """Motivo pelo qual a captura desta embarcacao esta' BLOQUEADA pela licenca ("" = liberada).

    Regra do dono (19/11/2026): sem internet o bordo MANTE'M TUDO NORMALMENTE — o corte acontece por
    VENCIMENTO ou REVOGACAO, nunca por falta de rede. Instalacao ANTIGA, sem nenhuma licenca no banco
    para aquela embarcacao, continua liberada: a licenca e' ADICIONAL, nada e' apagado.
    """
    emb = str(embarcacao_id or "").strip()
    if not emb:
        return ""
    try:
        with conexao() as c:
            linhas = c.execute("SELECT * FROM licencas WHERE embarcacao_id=?", (emb,)).fetchall()
    except Exception:  # noqa: BLE001  (banco antigo, sem a tabela: nao bloqueia nada)
        return ""
    if not linhas:
        return ""
    for linha in linhas:
        st = licenca_modulo.estado(linha["validade_tipo"], linha["validade_em"],
                                   linha["status"], linha["motivo"])
        if not st["bloqueada"]:
            return ""
    return licenca_modulo.estado(linhas[0]["validade_tipo"], linhas[0]["validade_em"],
                                 linhas[0]["status"], linhas[0]["motivo"])["texto"]


def parar_por_licenca(origem: str = "127.0.0.1") -> list:
    """Licenca vencida/revogada: PARA DE TRANSMITIR (desliga as cameras que ESTAO no ar) e conta o que fez.

    Para TODA camera habilitada desta maquina (a regra do dono e' "revogar corta na hora") e devolve quais
    foram. Quem chama e' `conferir_licenca_do_terra`, e so' na TRANSICAO (liberada -> bloqueada): repetir a
    parada a cada ciclo nao muda o estado do barco e suja a trilha — a J10 do smoke mediu 8 linhas
    `captura_parada_por_licenca` iguais em ~40 s, em 23/11/2026.
    """
    try:
        with conexao() as c:
            ligadas = [x["id"] for x in c.execute("SELECT id FROM cameras WHERE ativo=1")]
    except Exception:  # noqa: BLE001
        return []
    paradas = []
    for cam in ligadas:
        try:
            if not (ing_desligar_camera(cam) or {}).get("erro"):
                paradas.append(cam)
        except Exception:  # noqa: BLE001
            continue
    if paradas:
        auditar(None, "captura_parada_por_licenca", ", ".join(paradas), origem)
    return paradas


def conferir_licenca_do_terra(origem: str = "127.0.0.1") -> dict:
    """O que ESTA maquina tem guardado — e, com rede, o que o LADO TERRA diz agora.

    E' o miolo da rota local `GET /api/licenca`, e existe como funcao de modulo de proposito (J10 do
    smoke, 23/11/2026): quem PRECISA disso e' o laco de captura (`agente_de_ordens.uma_rodada`), que
    pergunta de tempos em tempos sem ninguem abrir a tela. Se a resposta for "caiu", a transmissao PARA
    aqui — corte visivel, nunca mudo.

    Sem rede nada muda: "mantém tudo normalmente" (o corte e' por vencimento/revogacao, nao por falta
    de rede) — por isso a falta de resposta vira `nota`, nunca desligamento.
    """
    r = licenca_modulo.resumo()
    ja_estava_bloqueada = bool(r.get("bloqueada"))
    if r.get("tem"):
        resp = licenca_modulo.pedir_ao_terra("/api/licenca/validar",
                                             {"chave": r["chave"], "maquina": licenca_modulo.maquina()},
                                             segundos=8)
        nova = dict(resp.get("licenca") or {}) if isinstance(resp.get("licenca"), dict) else {}
        if nova:
            guardado = licenca_modulo.ler()
            for campo in ("validade_tipo", "validade_em", "status", "motivo",
                          "embarcacao_id", "embarcacao_nome", "cliente_id", "cliente_nome"):
                if str(nova.get(campo, "")).strip() or campo in ("validade_em", "motivo"):
                    guardado[campo] = nova.get(campo, guardado.get(campo, ""))
            guardado["conferida_em"] = em_iso()
            licenca_modulo.gravar(guardado)
            r = licenca_modulo.resumo()
            r["conferida_em"] = guardado["conferida_em"]
        else:
            r["sem_rede"] = bool(resp.get("sem_rede"))
            r["nota"] = ("sem falar com o lado terra agora — a captura segue normal (quem corta é "
                         "vencimento ou revogação, não a falta de rede)"
                         if resp.get("sem_rede") else (resp.get("motivo") or "não conferi agora"))
        if r.get("bloqueada") and not ja_estava_bloqueada:
            # TRANSICAO (liberada -> bloqueada): e' agora que a captura tem de parar — uma vez, com a
            # trilha registrando o corte. Nas conferencias seguintes o estado ja' e' este: nao ha o que
            # cortar de novo e nao se escreve outra linha igual.
            r["paradas"] = parar_por_licenca(origem)
        elif r.get("bloqueada"):
            r["paradas"] = []
    return r


def licenca_do_terra(dados: dict, contar: bool = True) -> tuple[int, dict]:
    """(codigo, corpo) do LADO TERRA para ativar/validar uma chave de licenca.

    `contar=True` e' a ATIVACAO (a maquina passa a constar no uso da licenca); `contar=False` e' a
    REVALIDACAO periodica do bordo (nao soma maquina nova so' por perguntar de novo).

    Sem sessao e sem token de ingestao, de proposito: quem esta' ativando um PC de captura recem
    instalado nao tem usuario nem token ainda — a CHAVE e' a credencial (~2^81 de espaco, e chave
    invalida responde igual a chave inexistente, sem revelar se existe).
    """
    chave = licenca_modulo.normalizar(dados.get("chave", ""))
    if not chave:
        return 422, {"erro": "chave incompleta", "formato": "XXXX-XXXX-XXXX-XXXX",
                     "dica": "são 16 caracteres em 4 grupos — confira se copiou tudo"}
    nome_maquina = re.sub(r"[^a-zA-Z0-9_.\-]", "-", str(dados.get("maquina") or "").strip())[:80]
    with conexao() as c:
        linha = c.execute("SELECT * FROM licencas WHERE chave=?", (chave,)).fetchone()
    if not linha:
        return 404, {"erro": "chave não encontrada",
                     "dica": "confira a chave com quem gerou; ela vale para uma embarcação específica"}
    st = licenca_modulo.estado(linha["validade_tipo"], linha["validade_em"], linha["status"], linha["motivo"])
    licenca = {"chave": chave, "id": linha["id"], "embarcacao_id": linha["embarcacao_id"],
               "validade_tipo": linha["validade_tipo"], "validade_em": linha["validade_em"],
               "status": linha["status"], "motivo": linha["motivo"],
               "maquinas_max": int(linha["maquinas_max"] or 1), **{k: st[k] for k in ("estado", "bloqueada", "texto")}}
    if st.get("bloqueada"):
        return 403, {"ok": False, "erro": "licença não libera esta captura", "licenca": licenca}
    with conexao() as c:
        emb = c.execute("""SELECT e.id, e.nome, e.cliente_id, c.nome AS cliente_nome
                           FROM embarcacoes e LEFT JOIN clientes c ON c.id = e.cliente_id
                           WHERE e.id=?""", (linha["embarcacao_id"],)).fetchone()
        usadas = [r["maquina"] for r in c.execute("SELECT maquina FROM licenca_usos WHERE licenca_id=?",
                                                  (linha["id"],)).fetchall()]
        if contar and nome_maquina and nome_maquina not in usadas and len(usadas) >= int(linha["maquinas_max"] or 1):
            return 409, {"ok": False, "erro": "esta licença já está no limite de computadores",
                         "maquinas_max": int(linha["maquinas_max"] or 1), "maquinas": usadas,
                         "dica": "peça ao admin para aumentar o limite desta licença, ou use outra chave"}
        if nome_maquina and (contar or nome_maquina in usadas):
            c.execute("""INSERT INTO licenca_usos (licenca_id,maquina) VALUES (?,?)
                         ON CONFLICT(licenca_id,maquina) DO UPDATE SET ultimo_em=datetime('now')""",
                      (linha["id"], nome_maquina))
        c.execute("UPDATE licencas SET ultimo_uso_em=? WHERE id=?", (em_iso(), linha["id"]))
    licenca.update({"embarcacao_nome": (emb["nome"] if emb else ""),
                    "cliente_id": (emb["cliente_id"] if emb else ""),
                    "cliente_nome": (emb["cliente_nome"] if emb else "") or "",
                    "maquinas": len(set(usadas) | ({nome_maquina} if nome_maquina else set()))})
    return 200, {"ok": True, "licenca": licenca}


def pode_ver_embarcacao(usuario, embarcacao_id: str) -> bool:
    """A REGRA UNICA do acesso do cliente (dono, 19/11/2026: os quatro tipos).

    operador/admin veem tudo e operam; `observador` (Petrobras) ve tudo e NAO opera (as rotas de
    escrita checam PAPEL_ADMIN, nao esta funcao). Para o papel `cliente`:
      * com vinculo em `usuario_embarcacoes` -> EXATAMENTE as embarcacoes concedidas (tipos 1 e 2);
      * sem vinculo nenhum -> todas as embarcacoes do proprio `cliente_id` (tipo 3, o que ja' existia:
        instalacao antiga nao perde acesso).
    """
    if usuario is None or not embarcacao_id:
        return False
    if usuario["papel"] in PAPEIS_VE_TUDO:
        return True
    with conexao() as c:
        concedidas = [r["embarcacao_id"] for r in c.execute(
            "SELECT embarcacao_id FROM usuario_embarcacoes WHERE usuario_id=?", (usuario["id"],)).fetchall()]
        if concedidas:
            return embarcacao_id in concedidas
        emb = c.execute("SELECT cliente_id FROM embarcacoes WHERE id = ?", (embarcacao_id,)).fetchone()
    return bool(emb) and emb["cliente_id"] == usuario["cliente_id"]


def pode_ver_camera(usuario, camera: sqlite3.Row | None) -> bool:
    """Camera visivel = a embarcacao dela e' visivel (a regra esta em `pode_ver_embarcacao`).

    O papel `observador` (tipo 4, Petrobras — plano de 19/11/2026, Fase 4) e' a excecao: ele ve' os
    radares de oleo de TODAS as empresas e mais nada. Quem decide isso e' quem LISTA (`/api/cameras`),
    com `eh_camera_de_radar`: aqui a funcao continua sendo so' "a embarcacao e' visivel?".
    """
    if camera is None:
        return False
    return pode_ver_embarcacao(usuario, camera["embarcacao_id"])


def tipo_da_camera(camera) -> str:
    """O TIPO da camera: `camera` | `radar` | `flir`, gravado no cadastro do bordo (coluna `tipo`).
    Para uma linha antiga, sem a coluna, cai no NOME — o criterio que o observador usava antes
    (id/rotulo/fluxo_id/local/alvo dizendo "radar" ou "flir")."""
    if camera is None:
        return ""
    try:
        tipo = str(camera["tipo"] or "").strip().lower()
    except (KeyError, IndexError, TypeError):
        try:
            tipo = str(camera.get("tipo") or "").strip().lower()
        except Exception:  # noqa: BLE001
            tipo = ""
    if tipo in ("camera", "radar", "flir"):
        return tipo
    try:
        partes = [str(camera[k] or "") for k in ("id", "rotulo", "fluxo_id", "local", "alvo")]
    except (KeyError, IndexError, TypeError):
        try:
            partes = [str(camera.get(k) or "") for k in ("id", "rotulo", "fluxo_id", "local", "alvo")]
        except Exception:  # noqa: BLE001
            return "camera"
    nome = " ".join(partes).lower()
    if "flir" in nome:
        return "flir"
    return "radar" if "radar" in nome else "camera"


def pode_o_observador_ver(camera) -> bool:
    """O que o OBSERVADOR (Petrobras/IBAMA, tipo 4 do dono) ve de TODAS as empresas: o radar de oleo e
    a camera FLIR (se houver) — e nada mais. Dono (25/11/2026): "petrobras ou ibama pode acessar todas
    as embarcacoes de todas as empresas, mas apenas do radar de oleo e camera flir se tiver". O
    criterio e' o TIPO gravado no cadastro, nao mais o nome."""
    return tipo_da_camera(camera) in ("radar", "flir")


def eh_camera_de_radar(camera) -> bool:
    """O radar de oleo da embarcacao (tipo `radar`). O observador usa `pode_o_observador_ver`, que
    aceita tambem a FLIR."""
    return tipo_da_camera(camera) == "radar"



# ----------------------------------------------------------------- transmissao a pedido do cliente
# 17/11/2026 (plano .hermes/plans/2026-11-17-transmissao-a-pedido-do-cliente.md):
#  * quem PEDE e' o cliente (tela web `/app`, sem app instalado);
#  * a ORDEM nasce aqui (lado terra) e vai ao bordo — o bordo nao abre porta, ele pergunta e obedece;
#  * o corte e' POR SESSAO: quem fecha a tela derruba a propria sessao; se outro cliente esta' vendo, a
#    transmissao continua para ele;
#  * ao estourar o TEMPO a transmissao para e o cliente inicia de novo — a menos que esteja GRAVANDO;
#  * `transmissoes` e' o historico: nada e' apagado.
TEMPOS_DE_TRANSMISSAO = (300, 900, 1800, 3600, 7200)      # 5, 15, 30, 60 e 120 minutos (lista FECHADA)
TEMPO_MAXIMO_PADRAO = 900
# SAIDA DA TELA AO VIVO (dono, 24/11/2026): ao sair da tela das cameras e voltar em ate' 60 s a sessao
# continua de pe (o cliente ve outras coisas sem reconectar); passando disso a sessao morre sozinha. O
# batimento ("estou aqui") passou a ser mandado SO' pela tela do video — antes ele corria em qualquer tela
# e a sessao nunca expirava. Cobre tambem tela fechada / computador desligado.
SEGUNDOS_SEM_BATIMENTO = 60
# A RECARGA NAO E' SAIDA (dono, 25/11/2026: "quando recarrego a pagina, a transmissao e' interrompida").
# O `pagehide` da tela dispara IGUAL numa recarga (F5 / Ctrl+R) e ao fechar a aba — e o pedido de saida
# encerra a transmissao e apaga o que o cliente gravou. O pedido que vem marcado `pendente` (e' o que a
# tela manda no `pagehide`) fica PENDENTE por esta carencia: a pagina RECARREGADA bate ponto em seguida e
# CANCELA; quem nao volta, sai. A saida PEDIDA pelo cliente (botao "parar transmissao" / "Sair") nao passa
# por aqui — vale na hora, como sempre valeu.
SEGUNDOS_DE_CARENCIA = 8
SAIDAS_PENDENTES: dict[str, dict] = {}   # email -> {"prazo", "tipo", "ids", "embarcacao", "ip"}


def pendurar_saida(email: str, tipo: str, ids: list | None = None, embarcacao_id: str = "",
                   ip: str = "") -> None:
    """Guarda o pedido de saida da tela pela carencia: a recarga volta e cancela."""
    SAIDAS_PENDENTES[email] = {"prazo": time.monotonic() + SEGUNDOS_DE_CARENCIA, "tipo": tipo,
                               "ids": list(ids or []), "embarcacao": embarcacao_id or "", "ip": ip}


def cancelar_saida(email: str) -> bool:
    """A tela voltou (batimento/continuar): o pedido de saida pendente nao vale mais."""
    return SAIDAS_PENDENTES.pop(email, None) is not None


def saidas_vencidas(agora: float | None = None) -> list[dict]:
    """Os pedidos de saida cuja carencia passou sem a tela voltar."""
    t = agora if agora is not None else time.monotonic()
    return [dict(v, email=e) for e, v in list(SAIDAS_PENDENTES.items()) if v["prazo"] <= t]


def _executar_saida(item: dict) -> None:
    """Cumpriu a carencia: a tela NAO voltou — fecha as sessoes e apaga a gravacao (a regra do dono)."""
    email = item["email"]
    if item["tipo"] == "sair":
        sair_da_tela(email, item.get("embarcacao") or "", item.get("ip") or "")
        return
    for tid in item["ids"]:
        with conexao() as c:
            linha = c.execute("SELECT * FROM transmissoes WHERE id=?", (tid,)).fetchone()
        if not linha:
            continue
        t = dict(linha)
        if fechar_transmissao(tid, "encerrada", "a tela do cliente foi fechada"):
            parar_se_ninguem_vendo(t["embarcacao_id"], t["camera_id"], t["fluxo_id"],
                                   "nao havia mais ninguem vendo")
            auditar({"id": None, "email": email}, "transmissao_encerrada",
                    f"{t['camera_id']} (a tela nao voltou depois da recarga)", item.get("ip") or "")


SEGUNDOS_SEM_RESPOSTA = 30         # a maquina de captura nao respondeu a ordem (nunca foi entregue)
# BORDO MUDO (Fase 6, P0 — dono, 24/11/2026: "acabei de desinstalar o app de captura ... e a transmissao
# continua, como continua transmitindo se eu desinstalei o app?"). O batimento de 60 s acima e' do
# CLIENTE: enquanto o navegador dele estiver aberto a sessao fica de pe, mesmo que a maquina de captura a
# bordo tenha morrido — e a tela mente ("no ar") com a imagem parada. O bordo da' sinal de vida pela
# SAUDE (a cada 60 s) e pelo ESTADO REAL das cameras; silencio maior que isto ENCERRA as sessoes abertas
# daquela embarcacao, com o motivo real. Instalacao sem nenhum sinal conhecido nao conta como silencio.
SEGUNDOS_SEM_BORDO = 180
# AVISO DE 1 MINUTO ANTES DE CORTAR (dono, 24/11/2026, D1/D2): a tela pergunta "quer continuar
# conectado?" no ultimo minuto da sessao; sem o clique em "continuar" a sessao expira no prazo
# normal (o padrao e' desligar; seguir exige a acao do cliente).
AVISO_SEGUNDOS = 60
SEGUNDOS_ENTREGA_LENTA = 90        # a ordem foi entregue e a maquina nunca contou o que houve


def em_iso(quando=None) -> str:
    """Carimbo ISO-8601 UTC (com offset) — o MESMO formato nas tabelas novas."""
    return (quando or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")


def texto_do_tempo(segundos: int) -> str:
    return f"{max(1, int(segundos) // 60)} min"


def tempo_maximo_do_produto() -> int:
    """Teto do PRODUTO (o administrador define). ZERO quer dizer sem teto.

    Sem a tabela (instalacao antiga que ainda nao subiu) ou com valor torto, vale "sem teto" — nunca
    derruba a tela do cliente por causa de configuracao.
    """
    try:
        with conexao() as c:
            r = c.execute("SELECT valor FROM configs_do_produto WHERE chave='tempo_maximo_do_produto'").fetchone()
        v = int(str(r["valor"]).strip()) if r else 0
    except Exception:
        return 0
    return v if v in TEMPOS_DE_TRANSMISSAO else 0


def aplicar_teto_do_produto(segundos: int) -> tuple[int, bool]:
    """Corta o pedido do cliente no teto do produto. Devolve (segundos, foi_cortado)."""
    teto = tempo_maximo_do_produto()
    if teto and int(segundos) > teto:
        return teto, True
    return int(segundos), False


def enfileirar_ordem(embarcacao_id: str, camera_id: str, fluxo_id: str, acao: str,
                     motivo: str = "", transmissao_id: str = "") -> dict:
    """Poe a ordem na fila do bordo. A acao NASCE no lado terra: o bordo so' obedece (sem tecnico)."""
    with conexao() as c:
        seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 AS s FROM ordens_do_bordo").fetchone()["s"]
        oid = secrets.token_hex(8)
        c.execute("""INSERT INTO ordens_do_bordo
                     (id,seq,embarcacao_id,camera_id,fluxo_id,acao,transmissao_id,motivo,criado_em,estado)
                     VALUES (?,?,?,?,?,?,?,?,?,'pedido')""",
                  (oid, seq, embarcacao_id, camera_id, fluxo_id, acao, transmissao_id,
                   motivo[:200], em_iso()))
    auditar(None, f"ordem_{acao}", f"{camera_id} ({embarcacao_id})", "")
    return {"id": oid, "seq": seq, "acao": acao, "camera_id": camera_id}


def fechar_transmissao(tid: str, estado: str, motivo: str) -> dict | None:
    """Fecha a sessao UMA vez (None se ja' estava fechada) — e' o que entra no historico."""
    with conexao() as c:
        linha = c.execute("SELECT * FROM transmissoes WHERE id=?", (tid,)).fetchone()
        if not linha or linha["estado"] not in ("pedida", "no_ar"):
            return None
        c.execute("UPDATE transmissoes SET estado=?, motivo=?, encerrada_em=? WHERE id=?",
                  (estado, str(motivo)[:200], em_iso(), tid))
    return dict(linha)


def sessoes_vivas(embarcacao_id: str, camera_id: str) -> int:
    with conexao() as c:
        r = c.execute("""SELECT COUNT(*) AS n FROM transmissoes
                         WHERE embarcacao_id=? AND camera_id=? AND estado IN ('pedida','no_ar')""",
                      (embarcacao_id, camera_id)).fetchone()
    return int(r["n"])


def parar_se_ninguem_vendo(embarcacao_id: str, camera_id: str, fluxo_id: str, motivo: str) -> bool:
    """So' manda PARAR quando nao ha' mais nenhuma sessao viva naquela camera (corte por sessao)."""
    if sessoes_vivas(embarcacao_id, camera_id):
        return False
    enfileirar_ordem(embarcacao_id, camera_id, fluxo_id, "parar", motivo)
    return True


def _desejo_das_cameras(embarcacao_id: str) -> list[dict]:
    """O DESEJO de terra, por camera (dono, 19/11/2026).

    O computador de captura NAO tem porta aberta: a informacao nao sai de terra para o bordo. Quem sabe
    quem esta' assistindo e' terra, entao terra PUBLICA o desejo e o bordo OLHA. A `versao` sobe apenas
    quando o desejo muda — assim o bordo age na diferenca e nunca repete o que ja' esta' feito.
    """
    carimbo = em_iso()
    saida: list[dict] = []
    with conexao() as c:
        cams = [dict(x) for x in c.execute(
            "SELECT id, embarcacao_id, fluxo_id, ativo FROM cameras WHERE embarcacao_id=? ORDER BY id",
            (embarcacao_id,)).fetchall()]
    for cam in cams:
        cid = cam["id"]
        with conexao() as c:
            vivas = [dict(x) for x in c.execute(
                """SELECT id, usuario_email FROM transmissoes
                   WHERE camera_id=? AND estado IN ('pedida','no_ar') ORDER BY criada_em""",
                (cid,)).fetchall()]
            linha_manual = c.execute("SELECT manual FROM desejo_camera WHERE camera_id=?",
                                     (cid,)).fetchone()
        manual = (linha_manual["manual"] or "") if linha_manual else ""
        if not cam["ativo"]:
            desejo, motivo, tid = "parar", "a operacao desativou esta camera", ""
        elif manual == "parar":
            # o boto do operador (stand-by) manda: ele desligou esta camera na mao
            desejo, motivo, tid = "parar", "o operador desligou esta camera na mao", ""
        elif vivas:
            desejo = "ligar"
            quem = ", ".join(sorted({str(v["usuario_email"] or "tela") for v in vivas}))[:150]
            motivo = f"{len(vivas)} sessao(oes) assistindo: {quem}"
            tid = vivas[0]["id"]
        else:
            # D3 do dono (24/11/2026): "nao tem ligar agora do admin, so quem visualiza e' o cliente".
            # NAO existe mais o desejo manual de LIGAR — quem sustenta o `ligar` e' a SESSAO VIVA de quem
            # esta' assistindo (qualquer computador). Sem sessao, o desejo e' parar, sempre. (O
            # `manual=='parar'` acima continua valendo: a operacao pode desligar na mao.)
            desejo, motivo, tid = "parar", "ninguem esta' assistindo", ""
        mudou = False
        with conexao() as c:
            atual = c.execute("SELECT * FROM desejo_camera WHERE camera_id=?", (cid,)).fetchone()
            igual = bool(atual) and atual["desejo"] == desejo and (atual["motivo"] or "") == motivo \
                and (atual["transmissao_id"] or "") == (tid or "")
            if igual:
                versao = int(atual["versao"])
            else:
                versao = (int(atual["versao"]) + 1) if atual else 1
                c.execute("""INSERT INTO desejo_camera
                             (camera_id,embarcacao_id,desejo,versao,motivo,transmissao_id,atualizado_em)
                             VALUES (?,?,?,?,?,?,?) ON CONFLICT(camera_id) DO UPDATE SET
                               embarcacao_id=excluded.embarcacao_id, desejo=excluded.desejo,
                               versao=excluded.versao, motivo=excluded.motivo,
                               transmissao_id=excluded.transmissao_id,
                               atualizado_em=excluded.atualizado_em""",
                          (cid, embarcacao_id, desejo, versao, motivo, tid or "", carimbo))
                mudou = True
        if mudou:
            auditar(None, "desejo_camera_mudou", f"{cid} -> {desejo} (v{versao}): {motivo}")
        saida.append({"camera_id": cid, "fluxo_id": cam["fluxo_id"] or "", "desejo": desejo,
                      "versao": versao, "motivo": motivo, "transmissao_id": tid or ""})
    return saida


# Estados que o bordo conta no `/api/estado-real` (o que REALMENTE esta' no ar na maquina de captura).
ESTADOS_DO_BORDO = ("no_ar", "parado", "erro", "sem_entrada")


def guardar_estado_real(embarcacao_id: str, cameras: list, de=None) -> dict:
    """O bordo conta o que esta' no ar (dono, 19/11/2026). Quem manda no "de verdade" e' ele.

    E' por aqui que a tela do cliente sabe que a transmissao subiu — e, quando o bordo diz que a camera
    entrou no ar, a sessao do cliente vira `no_ar` na hora (sem depender de ordem atendida).
    """
    carimbo = em_iso()
    contados, mudancas = [], []
    for item in (cameras or [])[:80]:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("camera_id") or "").strip()
        if not cid:
            continue
        est = str(item.get("estado") or "").strip().lower()
        if est not in ESTADOS_DO_BORDO:
            est = "desconhecido"
        motivo = str(item.get("motivo") or "")[:300]
        fluxo = str(item.get("fluxo_id") or "")[:80]
        desde = str(item.get("desde") or "")[:40]
        gravando = 1 if item.get("gravando") else 0
        try:
            versao = int(item.get("versao_desejo") or 0)
        except Exception:
            versao = 0
        with conexao() as c:
            antigo = c.execute("SELECT * FROM estado_bordo WHERE camera_id=?", (cid,)).fetchone()
            c.execute("""INSERT INTO estado_bordo
                         (camera_id,embarcacao_id,estado,motivo,fluxo_id,desde,gravando,versao_desejo,atualizado_em)
                         VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(camera_id) DO UPDATE SET
                           embarcacao_id=excluded.embarcacao_id, estado=excluded.estado,
                           motivo=excluded.motivo, fluxo_id=excluded.fluxo_id, desde=excluded.desde,
                           gravando=excluded.gravando, versao_desejo=excluded.versao_desejo,
                           atualizado_em=excluded.atualizado_em""",
                      (cid, embarcacao_id, est, motivo, fluxo, desde, gravando, versao, carimbo))
            mudou = (not antigo) or antigo["estado"] != est or (antigo["motivo"] or "") != motivo
            if est == "no_ar":
                c.execute("""UPDATE transmissoes SET estado='no_ar',
                             fluxo_id=CASE WHEN ?<>'' THEN ? ELSE fluxo_id END
                             WHERE camera_id=? AND estado='pedida'""", (fluxo, fluxo, cid))
                # a ordem de iniciar que ficou na fila (lado terra que ainda escreve ordem) esta'
                # ATENDIDA de fato: o bordo contou que a camera esta' no ar. Sem isto o vigia do
                # "sem resposta" mataria a sessao do cliente depois de 30 s, com a camera funcionando.
                c.execute("""UPDATE ordens_do_bordo SET estado='atendida', atendida_em=?,
                             resultado=CASE WHEN resultado='' THEN 'feito: camera no ar (flag de estado)' ELSE resultado END
                             WHERE camera_id=? AND acao='iniciar' AND estado IN ('pedido','entregue')""",
                          (carimbo, cid))
            elif est == "parado":
                c.execute("""UPDATE ordens_do_bordo SET estado='atendida', atendida_em=?,
                             resultado=CASE WHEN resultado='' THEN 'feito: camera parada (flag de estado)' ELSE resultado END
                             WHERE camera_id=? AND acao='parar' AND estado IN ('pedido','entregue')""",
                          (carimbo, cid))
            elif est in ("erro", "sem_entrada"):
                # NAO fecha a sessao do cliente aqui: uma falha passageira (a API local reiniciando, o
                # cabo fora por um instante) nao pode derrubar quem esta' assistindo. A sessao segue
                # `pedida` e o vigia do lado terra a fecha com "sem sinal" se a maquina nao conseguir
                # mesmo — o bordo continua tentando a cada leitura da flag.
                pass
        if mudou:
            auditar(de, "estado_real_do_bordo", f"{cid}: {est} {motivo}"[:250])
            mudancas.append({"camera_id": cid, "estado": est})
        contados.append({"camera_id": cid, "estado": est})
    return {"ok": True, "contados": contados, "mudancas": mudancas, "agora": carimbo}


def hd_dir() -> Path:
    """Onde guardamos os trechos que o BORDO envia do HD do radar (dono, 19/11/2026)."""
    return gravacao_modulo.diretorio() / "hd"


def guardar_catalogo_do_hd(embarcacao_id: str, camera_id: str, resumo: dict, blocos: list) -> dict:
    """Terra guarda o CATALOGO do HD do bordo (o que existe, por horario) — nunca o video inteiro."""
    with conexao() as c:
        c.execute("""INSERT INTO hd_catalogo (embarcacao_id,camera_id,resumo,blocos,atualizado_em)
                     VALUES (?,?,?,?,?) ON CONFLICT(embarcacao_id,camera_id) DO UPDATE SET
                       resumo=excluded.resumo, blocos=excluded.blocos, atualizado_em=excluded.atualizado_em""",
                  (embarcacao_id, camera_id, json.dumps(resumo or {}, ensure_ascii=False)[:4000],
                   json.dumps((blocos or [])[-500:], ensure_ascii=False)[:200000], em_iso()))
    return {"ok": True, "camera_id": camera_id, "blocos": len(blocos or [])}


def catalogo_do_hd(embarcacao_id: str, camera_id: str = "") -> dict:
    """O catalogo publicado pelo bordo (para a tela pesquisar por data e hora)."""
    with conexao() as c:
        if camera_id:
            linhas = [dict(x) for x in c.execute(
                "SELECT * FROM hd_catalogo WHERE embarcacao_id=? AND camera_id=?",
                (embarcacao_id, camera_id)).fetchall()]
            pedidos = [dict(x) for x in c.execute(
                """SELECT id,camera_id,arquivo,estado,trecho,bytes,motivo,criado_em,pronto_em,usuario_email
                   FROM hd_pedidos WHERE embarcacao_id=? AND camera_id=? ORDER BY criado_em DESC LIMIT 50""",
                (embarcacao_id, camera_id)).fetchall()]
        else:
            linhas = [dict(x) for x in c.execute(
                "SELECT * FROM hd_catalogo WHERE embarcacao_id=?", (embarcacao_id,)).fetchall()]
            pedidos = [dict(x) for x in c.execute(
                """SELECT id,camera_id,arquivo,estado,trecho,bytes,motivo,criado_em,pronto_em,usuario_email
                   FROM hd_pedidos WHERE embarcacao_id=? ORDER BY criado_em DESC LIMIT 50""",
                (embarcacao_id,)).fetchall()]
    saida = []
    for l in linhas:
        try:
            l["resumo"] = json.loads(l["resumo"] or "{}")
        except Exception:
            l["resumo"] = {}
        try:
            l["blocos"] = json.loads(l["blocos"] or "[]")
        except Exception:
            l["blocos"] = []
        saida.append(l)
    return {"embarcacao_id": embarcacao_id, "catalogos": saida, "pedidos": pedidos}


def pedidos_de_hd(embarcacao_id: str) -> list:
    """Os trechos que o cliente pediu e o bordo ainda nao enviou (vai no corpo da flag)."""
    with conexao() as c:
        return [{"id": x["id"], "camera_id": x["camera_id"], "arquivo": x["arquivo"]}
                for x in c.execute("""SELECT id,camera_id,arquivo FROM hd_pedidos
                                      WHERE embarcacao_id=? AND estado='pedido' ORDER BY criado_em LIMIT 20""",
                                   (embarcacao_id,)).fetchall()]


def pedir_trecho_do_hd(usuario, camera_id: str, arquivo: str) -> dict:
    """O cliente pede um trecho do HD do radar: vira pedido para o bordo (quem envia e' o bordo)."""
    nome = Path(str(arquivo or "")).name
    if not re.match(r"^bloco-\d{8}-\d{6}\.mp4$", nome):
        return {"erro": "trecho invalido: informe um bloco (bloco-AAAAMMDD-HHMMSS.mp4)"}
    with conexao() as c:
        cam = c.execute("SELECT id, embarcacao_id FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not cam:
            return {"erro": "camera nao encontrada"}
        ja = c.execute("""SELECT id,estado FROM hd_pedidos WHERE camera_id=? AND arquivo=?
                          AND estado IN ('pedido','enviado') ORDER BY criado_em DESC""",
                       (camera_id, nome)).fetchone()
        if ja and ja["estado"] == "enviado":
            return {"ok": True, "ja_tinha": True, "id": ja["id"],
                    "recado": "este trecho ja' esta' em terra: baixe pelo historico"}
        pid = secrets.token_hex(8)
        c.execute("""INSERT INTO hd_pedidos (id,embarcacao_id,camera_id,arquivo,usuario_email,estado,criado_em)
                     VALUES (?,?,?,?,?,'pedido',?)""",
                  (pid, cam["embarcacao_id"], camera_id, nome, usuario["email"], em_iso()))
    auditar(usuario, "trecho_do_hd_pedido", f"{camera_id} {nome}", "")
    return {"ok": True, "id": pid, "recado": "pedido enviado ao PC de captura: o trecho chega em instantes"}


# --------------------------------------------------------------------------------------------
# CONFIGURACAO PUBLICADA POR TERRA (0.8.0, aprovado em 19/11/2026)
# O dono: "eu configuraria tudo pelo meu usuario admin, pela premissa de nao enviar nada para bordo, o
# app a bordo precisa buscar o tempo todo as atualizacoes". Mesmo desenho da flag: terra PUBLICA (com
# `versao`), o bordo OLHA, aplica SO' a diferenca e CONFIRMA o que aplicou.
# --------------------------------------------------------------------------------------------
CHAVES_DE_CONFIG = ("alvo_kbps", "teto_s", "gravacao_continua", "transmitir", "rotulo")
VALORES_DE_ALVO = ("1500", "1200", "1000", "800", "500", "300")   # a banda do produto, fechada
# O NOME da camera (dono, 23/11/2026): "a captura pega as informações e replica no app de captura,
# inclusive os nomes das câmeras". É a chave `rotulo` — o admin escreve o nome em terra e o bordo
# APLICA no cadastro local (e a varredura passa a respeitar o nome escolhido, em vez de reescrevê-lo
# com o nome do dispositivo a cada rodada).
LIMITE_NOME_CAMERA = 120
CHAVE_NOME_CAMERA = "rotulo"


def config_publicada(embarcacao_id: str) -> dict:
    """O que TERRA quer (com a versao maxima) + o que o BORDO ja' contou que aplicou."""
    with conexao() as c:
        chaves = [dict(x) for x in c.execute(
            """SELECT camera_id,chave,valor,versao,origem,atualizado_em FROM config_bordo
               WHERE embarcacao_id=? ORDER BY camera_id,chave""", (embarcacao_id,)).fetchall()]
        aplicadas = [dict(x) for x in c.execute(
            """SELECT camera_id,chave,valor,versao,motivo,atualizado_em FROM config_aplicada_bordo
               WHERE embarcacao_id=? ORDER BY camera_id,chave""", (embarcacao_id,)).fetchall()]
    return {"embarcacao_id": embarcacao_id, "versao": max([int(x["versao"]) for x in chaves], default=0),
            "chaves": chaves, "aplicadas": aplicadas}


def publicar_config(embarcacao_id: str, camera_id: str, chave: str, valor: str, origem: str = "") -> dict:
    """Publica (ou muda) UMA chave para o bordo. A `versao` sobe a cada publicacao — e' o que faz o
    bordo distinguir "nova" de "ja' tenho". Valida na borda: chave conhecida e valor dentro do produto."""
    emb = (embarcacao_id or "").strip()
    cam = (camera_id or "").strip()
    chave = (chave or "").strip()
    valor = str(valor if valor is not None else "").strip()
    if not emb:
        return {"erro": "informe a embarcacao"}
    if chave not in CHAVES_DE_CONFIG:
        return {"erro": f"chave desconhecida: {chave!r} (conhecidas: {', '.join(CHAVES_DE_CONFIG)})"}
    if chave == "alvo_kbps":
        if not cam:
            return {"erro": "alvo_kbps e' por camera: informe camera_id"}
        if valor not in VALORES_DE_ALVO:
            return {"erro": f"alvo fora da lista do produto: {valor!r} (use {', '.join(VALORES_DE_ALVO)})"}
    if chave == "transmitir":
        # Ligar/desligar a transmissao de UMA camera: e' o que o dono chama de "quais cameras transmitem".
        if not cam:
            return {"erro": "transmitir e' por camera: informe camera_id"}
        if valor not in ("0", "1"):
            return {"erro": f"transmitir aceita 0 ou 1 (veio {valor!r})"}
    if chave == "teto_s":
        try:
            n = int(float(valor))
        except (TypeError, ValueError):
            return {"erro": "teto_s precisa ser um numero de segundos"}
        if not 60 <= n <= 7200:
            return {"erro": "teto_s fora da faixa do produto (60 a 7200 s)"}
        valor = str(n)
    if chave == CHAVE_NOME_CAMERA:
        # O nome vai para o cadastro da camera NO BORDO: recusa o que nao e' nome (vazio, quebra de
        # linha, grande demais) aqui, na borda de quem publica — nunca "achei que apliquei".
        if not cam:
            return {"erro": "o nome e' por camera: informe camera_id"}
        if "\n" in valor or "\r" in valor or "\t" in valor:
            return {"erro": "o nome de uma linha so' (sem quebra de linha nem tabulacao)"}
        if not valor:
            return {"erro": "o nome nao pode ficar vazio"}
        if len(valor) > LIMITE_NOME_CAMERA:
            return {"erro": f"o nome cabe em {LIMITE_NOME_CAMERA} caracteres (veio com {len(valor)})"}
    with conexao() as c:
        if not c.execute("SELECT 1 FROM embarcacoes WHERE id=?", (emb,)).fetchone():
            return {"erro": f"embarcacao inexistente: {emb}"}
        if cam and not c.execute("SELECT 1 FROM cameras WHERE id=?", (cam,)).fetchone():
            return {"erro": f"camera inexistente nesta embarcacao: {cam}"}
        linha = c.execute("""SELECT versao FROM config_bordo
                             WHERE embarcacao_id=? AND camera_id=? AND chave=?""", (emb, cam, chave)).fetchone()
        versao = int(linha["versao"]) + 1 if linha else 1
        c.execute("""INSERT INTO config_bordo (embarcacao_id,camera_id,chave,valor,versao,origem,atualizado_em)
                     VALUES (?,?,?,?,?,?,?)
                     ON CONFLICT(embarcacao_id,camera_id,chave) DO UPDATE SET valor=excluded.valor,
                       versao=excluded.versao, origem=excluded.origem, atualizado_em=excluded.atualizado_em""",
                  (emb, cam, chave, valor, versao, origem or "", em_iso()))
    return {"ok": True, "embarcacao_id": emb, "camera_id": cam, "chave": chave, "valor": valor,
            "versao": versao}


def aplicar_config_local(camera_id: str, chave: str, valor: str) -> dict:
    """Aplica UMA chave no banco DESTA maquina (rota local, o agente do bordo chama).

    Valida ANTES de mexer: valor fora do produto, camera inexistente ou chave que esta versao ainda nao
    aplica voltam como recusa explicada — nunca "achei que apliquei", e nada do que esta' no ar cai.
    """
    cam = (camera_id or "").strip()
    chave = (chave or "").strip()
    valor = str(valor if valor is not None else "").strip()
    if chave == "alvo_kbps":
        if valor.rstrip("kK") not in VALORES_DE_ALVO:
            return {"ok": False, "motivo": f"alvo fora da lista do produto ({valor!r})"}
        if not cam:
            return {"ok": False, "motivo": "alvo_kbps e' por camera"}
        # O campo `cameras.alvo` e' o que o ffmpeg recebe cru (`-b:v`), e a convencao do produto nele e'
        # em MILHARES de bits ("1500k" — ver `ingestao.alvo_automatico` e a lista da tela da camera).
        # A lista publicada pelo admin e' o NUMERO em kbps ("500"): sem o sufixo o ffmpeg leria BITS por
        # segundo e o video morreria — medido na J8 (smoke) em 23/11/2026: alvo 500 -> 0,0 Mbps e ZERO
        # quadro. A conversao numero -> banda acontece AQUI, na borda de quem escreve no campo.
        banda = valor if valor.endswith(("k", "K")) else f"{valor}k"
        with conexao() as c:
            if not c.execute("SELECT 1 FROM cameras WHERE id=?", (cam,)).fetchone():
                return {"ok": False, "motivo": f"a camera {cam} nao existe nesta maquina"}
            c.execute("UPDATE cameras SET alvo=? WHERE id=?", (banda, cam))
            c.execute("""INSERT INTO config_local (camera_id,chave,valor,versao,atualizado_em)
                         VALUES (?,?,?,0,?)
                         ON CONFLICT(camera_id,chave) DO UPDATE SET valor=excluded.valor,
                           atualizado_em=excluded.atualizado_em""", (cam, chave, valor, em_iso()))
        return {"ok": True, "motivo": "alvo aplicado (vale no proximo inicio do envio)",
                "camera_id": cam, "chave": chave, "valor": valor}
    if chave == "teto_s":
        try:
            n = int(float(valor))
        except (TypeError, ValueError):
            return {"ok": False, "motivo": "teto_s nao e' numero"}
        if not 60 <= n <= 7200:
            return {"ok": False, "motivo": "teto fora da faixa do produto (60 a 7200 s)"}
        with conexao() as c:
            c.execute("""INSERT INTO config_local (camera_id,chave,valor,versao,atualizado_em)
                         VALUES ('',?,?,0,?)
                         ON CONFLICT(camera_id,chave) DO UPDATE SET valor=excluded.valor,
                           atualizado_em=excluded.atualizado_em""", (chave, str(n), em_iso()))
        return {"ok": True, "motivo": f"teto local do bordo em {n} s", "chave": chave, "valor": str(n)}
    if chave == CHAVE_NOME_CAMERA:
        # O NOME que o admin escolheu em terra, aplicado no CADASTRO LOCAL desta maquina. Fica em
        # `config_local` de proposito: e' o que faz a varredura respeitar o nome (ver
        # `varredura_do_bordo.varrer()`), em vez de reescrever o rotulo com o nome do dispositivo.
        if not valor or "\n" in valor or len(valor) > LIMITE_NOME_CAMERA:
            return {"ok": False, "motivo": "nome invalido (vazio, com quebra de linha ou grande demais)"}
        if not cam:
            return {"ok": False, "motivo": "o nome e' por camera"}
        with conexao() as c:
            if not c.execute("SELECT 1 FROM cameras WHERE id=?", (cam,)).fetchone():
                return {"ok": False, "motivo": f"a camera {cam} nao existe nesta maquina"}
            c.execute("UPDATE cameras SET rotulo=? WHERE id=?", (valor, cam))
            c.execute("""INSERT INTO config_local (camera_id,chave,valor,versao,atualizado_em)
                         VALUES (?,?,?,0,?)
                         ON CONFLICT(camera_id,chave) DO UPDATE SET valor=excluded.valor,
                           atualizado_em=excluded.atualizado_em""", (cam, chave, valor, em_iso()))
        return {"ok": True, "motivo": "nome aplicado no cadastro desta maquina",
                "camera_id": cam, "chave": chave, "valor": valor}
    if chave in ("gravacao_continua", "transmitir"):
        return {"ok": False, "motivo": f"{chave}: esta versao do app de captura ainda nao aplica "
                                        f"(a gravacao continua e' ligada pelo servico do bordo)"}
    return {"ok": False, "motivo": f"chave desconhecida: {chave}"}


def guardar_config_aplicada(embarcacao_id: str, versao, aplicadas: list, recusadas: list) -> dict:
    """O que o BORDO conta que aplicou (ou recusou): fecha o ciclo desejo -> realidade."""
    emb = (embarcacao_id or "").strip()
    if not emb:
        return {"erro": "informe a embarcacao"}
    try:
        v = int(versao or 0)
    except (TypeError, ValueError):
        v = 0
    gravadas = 0
    with conexao() as c:
        for item in (aplicadas or []) + (recusadas or []):
            cand = str(item.get("camera_id") or "").strip()
            chk = str(item.get("chave") or "").strip()
            if not chk:
                continue
            c.execute("""INSERT INTO config_aplicada_bordo
                           (embarcacao_id,camera_id,chave,valor,versao,motivo,atualizado_em)
                         VALUES (?,?,?,?,?,?,?)
                         ON CONFLICT(embarcacao_id,camera_id,chave) DO UPDATE SET valor=excluded.valor,
                           versao=excluded.versao, motivo=excluded.motivo,
                           atualizado_em=excluded.atualizado_em""",
                      (emb, cand, chk, str(item.get("valor") or ""), v,
                       str(item.get("motivo") or ""), em_iso()))
            gravadas += 1
    return {"ok": True, "gravadas": gravadas, "versao": v}


# ---------------------------------------------------------------------------------------------
# A ARVORE DO ADMIN (0.12.0, aprovado em 23/11/2026): EMPRESA -> EMBARCACAO -> CAMERAS.
# O dono: "preciso poder configurar cada cliente/embarcacao/cameras de forma unificada e simples, hoje
# eu tenho muitas paginas: clientes/embarcacoes/cameras/licencas/producao/tempo real/enviar
# videos/usuarios/configuracoes do bordo, tudo isso poderia ser uma area so, de configuracao por
# cliente e de embarcacoes pra baixo tudo vinculado ao cliente". E: "tempo real, producao e cameras e'
# a mesma coisa, nao precisa dividir". Uma leitura so, com o que a tela precisa para desenhar tudo —
# sem endereco, porta, protocolo ou credencial de camera (a regra de sempre).
# ---------------------------------------------------------------------------------------------
def e_camera_da_varredura(camera_id: str) -> bool:
    """A camera que a VARREDURA do PC de captura criou (o id nasce do dispositivo).

    A varredura monta o id a partir do caminho do dispositivo (`cam-device-pnp-usb-vid-...`), entao o
    proprio id diz de onde a camera veio — e' o que a tela usa para marcar "achada pela varredura" e
    separar do que foi cadastrado na mao.
    """
    cid = (camera_id or "").lower()
    return "-device-pnp-" in cid or cid.startswith("cam-device")


def _licenca_da_embarcacao(embarcacao_id: str) -> dict:
    """A licenca que vale hoje para esta embarcacao (a ultima), SEM a chave: a tela mostra os 4
    ultimos digitos e o admin copia a chave inteira pelo fluxo proprio (`GET /api/licencas`)."""
    with conexao() as c:
        x = c.execute("""SELECT id,validade_tipo,validade_em,maquinas_max,status,ultimo_uso_em,revogada_em
                         FROM licencas WHERE embarcacao_id=? ORDER BY rowid DESC LIMIT 1""",
                      (embarcacao_id,)).fetchone()
    return dict(x) if x else {}


def _maquinas_da_embarcacao(embarcacao_id: str) -> list:
    """Quantos PCs de captura usaram a licenca desta embarcacao (e quando) — o dono cobra "quantos
    PCs usam a mesma licenca"; e' ajustavel e isto e' o medido, nao o combinado.

    A CHAVE NUNCA SAI INTEIRA (regra do produto: "a chave nao circula"): sai so' os 4 ultimos digitos
    (`licenca_ultimos4`), como no resto do produto. A chave completa so' pelo fluxo proprio do admin
    (`GET /api/licencas`, que exige admin). Ate' 24/11/2026 esta funcao devolvia a chave inteira, e o
    papel `observador` (Petrobras) ve a area -> vazava a chave de todos os barcos.
    """
    with conexao() as c:
        linhas = [dict(x) for x in c.execute(
            """SELECT l.chave AS chave, u.maquina, u.primeiro_em, u.ultimo_em
               FROM licenca_usos u JOIN licencas l ON l.id=u.licenca_id
               WHERE l.embarcacao_id=? ORDER BY u.ultimo_em DESC""", (embarcacao_id,)).fetchall()]
    for x in linhas:
        x["licenca_ultimos4"] = licenca_modulo.ultimos4(x.pop("chave") or "")
    return linhas


def arvore_do_painel(usuario) -> dict:
    """Empresa -> embarcacoes -> cameras, com o que cada camera e' e o que da' para fazer com ela."""
    mt = caminhos_do_mediamtx()
    with conexao() as c:
        clientes = [dict(x) for x in c.execute("SELECT id,nome,ativo FROM clientes ORDER BY nome")]
        embs = [dict(x) for x in c.execute("SELECT * FROM embarcacoes ORDER BY nome")]
        linhas_cam = c.execute("""SELECT id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo
                                  FROM cameras ORDER BY rotulo""").fetchall()
        estados = {x["camera_id"]: dict(x) for x in c.execute(
            """SELECT camera_id,estado,motivo,fluxo_id,desde,gravando,atualizado_em
               FROM estado_bordo""")}
        desejos = {x["camera_id"]: dict(x) for x in c.execute(
            """SELECT camera_id,desejo,versao,motivo,manual,atualizado_em FROM desejo_camera""")}
        desejada: dict = {}
        for x in c.execute("""SELECT embarcacao_id,camera_id,chave,valor,versao,origem,atualizado_em
                              FROM config_bordo"""):
            desejada.setdefault((x["embarcacao_id"], x["camera_id"]), []).append(dict(x))
        aplicada: dict = {}
        for x in c.execute("""SELECT embarcacao_id,camera_id,chave,valor,versao,motivo,atualizado_em
                              FROM config_aplicada_bordo"""):
            aplicada.setdefault((x["embarcacao_id"], x["camera_id"]), []).append(dict(x))

    por_embarcacao: dict = {}
    for linha in linhas_cam:
        if not pode_ver_camera(usuario, linha):
            continue
        if usuario is not None and usuario["papel"] == PAPEL_OBSERVADOR and not pode_o_observador_ver(linha):
            continue  # o observador (Petrobras/IBAMA) ve o radar de oleo e a FLIR, e so' eles
        cam = dict(linha)
        p = mt.get(cam["fluxo_id"], {})
        est = estados.get(cam["id"], {})
        por_embarcacao.setdefault(cam["embarcacao_id"], []).append({
            "id": cam["id"], "rotulo": cam["rotulo"], "fluxo_id": cam["fluxo_id"],
            "tipo": tipo_da_camera(cam),
            "ativo": cam["ativo"], "alvo": cam["alvo"], "local": cam["local"],
            "achada_pela_varredura": e_camera_da_varredura(cam["id"]),
            "no_ar": bool(p.get("ready")) and bool(p.get("tracks")),
            "leitores": len(p.get("readers", [])),
            "encoder": perfil_encoder(cam["fluxo_id"]),
            "estado": {"estado": est.get("estado") or "sem retorno",
                       "motivo": est.get("motivo") or "", "desde": est.get("desde") or "",
                       "gravando": est.get("gravando") or "0",
                       "atualizado_em": est.get("atualizado_em") or ""},
            "desejo": desejos.get(cam["id"], {}),
            "config": {"desejada": desejada.get((cam["embarcacao_id"], cam["id"]), []),
                       "aplicada": aplicada.get((cam["embarcacao_id"], cam["id"]), [])},
        })

    def embarcacao_completa(emb: dict) -> dict:
        cams = por_embarcacao.get(emb["id"], [])
        achadas = [x for x in cams if x["achada_pela_varredura"]]
        return {
            "id": emb["id"], "nome": emb["nome"], "cliente_id": emb["cliente_id"],
            "imo": emb.get("imo") or "", "estado": emb.get("estado") or "",
            "radar": {"fonte": emb.get("radar_fonte") or "", "modo": emb.get("radar_modo") or "",
                      "taxa": emb.get("radar_taxa") or "", "alvo": emb.get("radar_alvo") or ""},
            "licenca": _licenca_da_embarcacao(emb["id"]),
            "maquinas": _maquinas_da_embarcacao(emb["id"]),
            "saude": _saude_resumida(emb["id"]),
            "cameras": cams,
            "resumo": {"cameras": len(cams), "no_ar": len([x for x in cams if x["no_ar"]]),
                       "ativas": len([x for x in cams if x["ativo"]]),
                       "achadas_pela_varredura": len(achadas),
                       "com_config_desejada": len([x for x in cams if x["config"]["desejada"]])},
        }

    empresas = []
    for cl in clientes:
        minhas = [embarcacao_completa(e) for e in embs if e["cliente_id"] == cl["id"]]
        empresas.append({"id": cl["id"], "nome": cl["nome"], "ativo": cl["ativo"],
                         "embarcacoes": minhas,
                         "resumo": {"embarcacoes": len(minhas),
                                    "cameras": sum(e["resumo"]["cameras"] for e in minhas),
                                    "no_ar": sum(e["resumo"]["no_ar"] for e in minhas),
                                    "achadas_pela_varredura": sum(e["resumo"]["achadas_pela_varredura"]
                                                                  for e in minhas)}})
    # Embarcacao sem empresa nao pode sumir da tela: a hierarquia manda, mas o dado e' do dono.
    sem_empresa = [embarcacao_completa(e) for e in embs
                   if not any(e["cliente_id"] == cl["id"] for cl in clientes)]
    return {"empresas": empresas, "embarcacoes_sem_empresa": sem_empresa, "agora": em_iso()}


def _tem_saude(embarcacao_id: str) -> bool:
    with conexao() as c:
        return bool(c.execute("SELECT 1 FROM saude_bordo WHERE embarcacao_id=? LIMIT 1",
                              (embarcacao_id,)).fetchone())


def _saude_resumida(embarcacao_id: str) -> dict:
    """A saude do bordo DAQUELA embarcacao, para a area unica (sem a serie inteira).

    Vai o SEMAFORO **com os motivos** (`sinais`, do `classificar_saude`) e os NUMEROS do ultimo retrato
    (cpu, memoria, disco, ffmpeg, mediamtx, dispositivos, varredura) — o dono pediu "saude E desempenho"
    (24/11/2026) e a tela so' mostrava o estado e a hora. Nada de caminho de arquivo no corpo: o retrato
    inteiro continua em `/api/saude-do-bordo` (a tela propria), aqui vai o que a area desenha.
    """
    if not _tem_saude(embarcacao_id):
        return {}
    at = (saude_de(embarcacao_id, pontos=1) or {}).get("atual") or {}
    r = at.get("retrato") or {}
    discos = [d for d in (r.get("discos") or []) if isinstance(d, dict)]
    hd = next((d for d in discos if d.get("nome") == "hd do radar"), None)
    ff = r.get("ffmpeg") or {}
    dispo = r.get("dispositivos_video") or {}
    varre = r.get("varredura") or {}
    return {
        "estado": at.get("estado") or "", "em": at.get("recebido_em") or "",
        "maquina": at.get("maquina") or "", "versao_app": at.get("versao_app") or "",
        "so": r.get("so") or "", "gerado_em": r.get("gerado_em") or "",
        "uptime_s": r.get("uptime_s"),
        "cpu_pct": r.get("cpu_pct"), "memoria_pct": r.get("memoria_pct"),
        "memoria_livre_mb": r.get("memoria_livre_mb"),
        "discos": [{"nome": d.get("nome"), "usado_pct": d.get("usado_pct"),
                    "livre_gb": d.get("livre_gb"), "total_gb": d.get("total_gb")} for d in discos],
        "hd_radar_usado_pct": (hd or {}).get("usado_pct"), "hd_radar_livre_gb": (hd or {}).get("livre_gb"),
        "ffmpeg": ff.get("presente"), "ffmpeg_versao": ff.get("versao") or ff.get("erro") or "",
        "mediamtx": bool((r.get("mediamtx") or {}).get("ativo")),
        "mediamtx_caminhos": (r.get("mediamtx") or {}).get("caminhos"),
        "dispositivos": dispo.get("quantos"), "dispositivos_nomes": dispo.get("nomes") or [],
        "varredura": varre.get("vistos"), "varredura_ok": varre.get("ok"),
        # TELEMETRIA INDIVIDUAL E GLOBAL (dono, 24/11/2026): a rede da maquina e a lista POR CAMERA
        # (o `individual` do retrato) sobem para o painel do admin junto com o resto. Campo ausente
        # (bordo antigo) sai como None/[] — a tela diz "nao medido" em vez de mostrar zero.
        "memoria_disponivel_mb": r.get("memoria_disponivel_mb", r.get("memoria_livre_mb")),
        "memoria_total_mb": (r.get("global") or {}).get("memoria_total_mb"),
        "rede": (r.get("rede") or {}).get("total") or (r.get("global") or {}).get("rede") or {},
        "individual": r.get("individual") or [],
        "nao_medido": r.get("nao_medido") or {},
        "sinais": at.get("sinais") or [],
    }


# ---------------------------------------------------------------------------------------------
# SAUDE DO BORDO NO PAINEL (0.8.0, Fase 5). O bordo ENVIA; terra guarda e classifica. Cada sinal tem
# LIMIAR DECLARADO e o "o que fazer" — o painel nao precisa saber regra nenhuma e o teste prova a regra
# pelo mesmo caminho que a tela ve. Sem dado recente NAO e' "ok": bordo mudo e' PROBLEMA (silencio nao
# pode parecer saude).
# ---------------------------------------------------------------------------------------------
LIMIARES_DE_SAUDE = {
    "cpu_pct": {"atencao": 75.0, "problema": 90.0, "unidade": "%"},
    "memoria_pct": {"atencao": 80.0, "problema": 92.0, "unidade": "%"},
    "disco_pct": {"atencao": 88.0, "problema": 95.0, "unidade": "% usado"},
    "mudo_s": {"atencao": 180.0, "problema": 600.0, "unidade": "s sem reportar"},
    "erros_24h": {"atencao": 20.0, "problema": 100.0, "unidade": "erros nas ultimas 24 h"},
}


def _sinal(nome: str, valor, estado: str, o_que_fazer: str) -> dict:
    lim = LIMIARES_DE_SAUDE.get(nome, {})
    regra = (f"atenção a partir de {lim['atencao']:g} / problema a partir de {lim['problema']:g} "
             f"{lim.get('unidade', '')}".strip() if lim else "sinal binário: precisa estar ativo")
    return {"sinal": nome, "valor": valor, "estado": estado, "limiar": regra, "o_que_fazer": o_que_fazer}


def classificar_saude(retrato: dict | None, idade_s: float | None) -> dict:
    """Semáforo por sinal: verde=ok, amarelo=atencao, vermelho=problema. O pior manda no retrato.

    `idade_s` e' a idade do ULTIMO retrato recebido: sem dado fresco a resposta e' "problema" — o
    silencio do computador de captura e' exatamente o que o admin precisa ver.
    """
    sinais: list[dict] = []
    if not retrato:
        sinais.append(_sinal("mudo_s", None, "problema",
                             "este computador de captura nunca reportou: verifique se o app está aberto "
                             "e se ele alcança o lado terra (rede/VPN)"))
        return {"estado": "problema", "sinais": sinais, "pior": "problema"}

    def numero(*caminho, padrao=None):
        atual = retrato
        for p in caminho:
            if not isinstance(atual, dict):
                return padrao
            atual = atual.get(p)
        return atual if isinstance(atual, (int, float)) else padrao

    # 1) o bordo esta' reportando?
    if idade_s is None:
        sinais.append(_sinal("mudo_s", None, "problema", "sem hora de recebimento registrada"))
    else:
        lim = LIMIARES_DE_SAUDE["mudo_s"]
        estado = "ok" if idade_s < lim["atencao"] else ("atencao" if idade_s < lim["problema"] else "problema")
        sinais.append(_sinal("mudo_s", round(idade_s), estado,
                             "ok" if estado == "ok" else
                             "o computador de captura parou de reportar: confira o app aberto, a energia e a "
                             "conexão; nada de sair da sala sem olhar isso"))

    # 2) CPU e memoria (quando o bordo conseguiu medir)
    for nome, caminho, fazer in (("cpu_pct", ("cpu_pct",), "CPU no limite: reduza o alvo de banda de alguma "
                                                      "câmera na tela Configuração do bordo ou feche programas"),
                                 ("memoria_pct", ("memoria_pct",), "memória cheia: reinicie o app de captura "
                                                                   "no fim do dia de operação")):
        v = numero(*caminho)
        if v is None:
            sinais.append(_sinal(nome, None, "atencao",
                                 "não medido pelo bordo (instalar psutil no computador de captura)"))
            continue
        lim = LIMIARES_DE_SAUDE[nome]
        estado = "ok" if v < lim["atencao"] else ("atencao" if v < lim["problema"] else "problema")
        sinais.append(_sinal(nome, round(float(v), 1), estado, "ok" if estado == "ok" else fazer))

    # 3) disco (por volume; o HD do radar mostra o anel)
    for d in (retrato.get("discos") or []):
        nome = str(d.get("nome") or "disco")
        pct = d.get("usado_pct")
        if pct is None:
            sinais.append(_sinal("disco_pct", None, "atencao",
                                 f"{nome}: não consegui medir ({d.get('erro') or 'sem número'})"))
            continue
        lim = LIMIARES_DE_SAUDE["disco_pct"]
        estado = "ok" if pct < lim["atencao"] else ("atencao" if pct < lim["problema"] else "problema")
        anel = f" · anel: {d.get('blocos')} bloco(s), mais antigo em {d.get('mais_antigo') or '—'}" if "blocos" in d else ""
        sinais.append(_sinal("disco_pct", pct, estado,
                             f"{nome}: livre {d.get('livre_gb')} GB{anel}" if estado == "ok" else
                             f"{nome} com {pct}% usado ({d.get('livre_gb')} GB livres): o anel começa a gravar "
                             f"por cima do mais antigo — libere espaço{anel}"))

    # 4) captura viva: ffmpeg presente e o laco do agente vivo
    if not (retrato.get("ffmpeg") or {}).get("presente"):
        sinais.append(_sinal("ffmpeg", False, "problema",
                             "o ffmpeg não foi encontrado no computador de captura: sem ele não há captura — "
                             "reinstale o app"))
    else:
        sinais.append(_sinal("ffmpeg", True, "ok",
                             (retrato.get("ffmpeg") or {}).get("versao", "")[:60]))
    ag = retrato.get("agente") or {}
    if ag.get("laco_vivo"):
        sinais.append(_sinal("agente", True, "ok", f"última rodada há {ag.get('idade_s')} s"))
    else:
        sinais.append(_sinal("agente", False, "problema",
                             f"o laço de captura não está rodando ({ag.get('motivo') or ag.get('erro') or 'sem sinal'}"
                             f"): abra o app de captura nesta máquina"))
    if "producao" in retrato.get("nao_medido", {}):
        pass

    # 5) mediamtx (o que entrega o vídeo para terra)
    mt = retrato.get("mediamtx") or {}
    sinais.append(_sinal("mediamtx", bool(mt.get("ativo")), "ok" if mt.get("ativo") else "atencao",
                         f"{mt.get('caminhos', 0)} caminho(s) publicado(s)" if mt.get("ativo") else
                         "o mediamtx não respondeu: sem ele o vídeo não sai do bordo — reinicie o serviço"))
    if "mediamtx" in (retrato.get("nao_medido") or {}):
        pass

    # 6) o trabalho do bordo: erros de 24 h e pedidos pendentes
    b = retrato.get("banco") or {}
    erros = b.get("erros_24h")
    if erros is None:
        sinais.append(_sinal("erros_24h", None, "atencao", "não consegui ler o banco do bordo"))
    else:
        lim = LIMIARES_DE_SAUDE["erros_24h"]
        estado = "ok" if erros < lim["atencao"] else ("atencao" if erros < lim["problema"] else "problema")
        sinais.append(_sinal("erros_24h", erros, estado,
                             "sem erros nas últimas 24 h" if estado == "ok" else
                             f"{erros} erro(s) de envio nas últimas 24 h: abra o app de captura e veja quais "
                             f"câmeras falharam"))
    pend = b.get("pedidos_pendentes")
    if pend:
        sinais.append(_sinal("pedidos", pend, "atencao",
                             f"{pend} pedido(s) de trecho do HD ainda não enviados: o bordo envia sozinho na "
                             f"próxima rodada — se persistir, veja o disco"))

    ordem = {"ok": 0, "atencao": 1, "problema": 2}
    pior = max((s["estado"] for s in sinais), key=lambda e: ordem.get(e, 0), default="ok")
    return {"estado": pior, "pior": pior, "sinais": sinais}


def receber_saude_do_bordo(embarcacao_id: str, retrato: dict) -> dict:
    """Grava o retrato do bordo (ultima + serie) e aplica a retencao de 30 dias."""
    emb = (embarcacao_id or "").strip()
    if not emb:
        return {"erro": "informe a embarcacao"}
    if not isinstance(retrato, dict) or not retrato:
        return {"erro": "retrato vazio"}
    # nada de segredo: o retrato sobe como veio, mas nunca com token/senha (defesa em profundidade)
    sujo = [k for k in ("token", "senha", "password", "key", "authorization") if k in retrato]
    for k in sujo:
        retrato.pop(k, None)
    # o estado que fica gravado e' o MESMO que o painel mostra: classificacao do proprio terra, feita
    # agora (acabou de chegar, logo nao esta' mudo). Assim a serie tem semaforo para comparar depois.
    estado = classificar_saude(retrato, 0.0).get("estado", "")
    agora = em_iso()
    with conexao() as c:
        ant = c.execute("SELECT estado FROM saude_bordo WHERE embarcacao_id=? ORDER BY id DESC LIMIT 1",
                        (emb,)).fetchone()
        anterior = str(ant[0] or "") if ant else ""
        c.execute("""INSERT INTO saude_bordo (embarcacao_id,recebido_em,maquina,versao_app,estado,retrato)
                     VALUES (?,?,?,?,?,?)""",
                  (emb, agora, str(retrato.get("maquina") or ""), str(retrato.get("versao_app") or ""),
                   estado, json.dumps(retrato, ensure_ascii=False)))
        # retencao: a serie guarda 30 dias; o corte fica registrado (nada some sem explicacao)
        corte = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec="seconds")
        cur = c.execute("DELETE FROM saude_bordo WHERE recebido_em < ?", (corte,))
        if cur.rowcount:
            c.execute("INSERT OR REPLACE INTO saude_bordo_corte (cortado_em,quantos,regra) VALUES (?,?,?)",
                      (agora, int(cur.rowcount), "serie de saude: 30 dias"))
    if anterior != estado:
        # P2: a trilha guarda a VIRADA (ficou vermelho / voltou ao normal), que e' o que o admin precisa
        # acompanhar depois — o numero cru ele ve' na hora, a historia ele so' ve' aqui.
        auditar(None, "saude_do_bordo_mudou", f"{emb}: {anterior or 'sem leitura'} -> {estado}",
                "computador de captura")
    return {"ok": True, "embarcacao_id": emb, "recebido_em": agora, "estado": estado, "estado_anterior": anterior}


def saude_de(embarcacao_id: str, pontos: int = 60) -> dict:
    """O que o painel mostra: a ULTIMA saude (classificada) e a serie recente, por embarcacao."""
    emb = (embarcacao_id or "").strip()
    with conexao() as c:
        linhas = [dict(x) for x in c.execute(
            """SELECT recebido_em,maquina,versao_app,retrato FROM saude_bordo
               WHERE embarcacao_id=? ORDER BY recebido_em DESC LIMIT ?""", (emb, max(1, int(pontos)))).fetchall()]
        cortes = [dict(x) for x in c.execute(
            "SELECT cortado_em,quantos,regra FROM saude_bordo_corte ORDER BY cortado_em DESC LIMIT 5").fetchall()]
    serie = []
    for i, linha in enumerate(linhas):
        try:
            retrato = json.loads(linha["retrato"] or "{}")
        except Exception:  # noqa: BLE001
            retrato = {}
        idade = None
        if i == 0 and linha["recebido_em"]:
            try:
                quando = dt.datetime.fromisoformat(linha["recebido_em"])
                if quando.tzinfo is None:
                    quando = quando.replace(tzinfo=dt.timezone.utc)
                idade = max(0.0, (dt.datetime.now(dt.timezone.utc) - quando).total_seconds())
            except Exception:  # noqa: BLE001
                idade = None
        if i == 0:
            atual = classificar_saude(retrato, idade)
            atual.update({"recebido_em": linha["recebido_em"], "maquina": linha["maquina"],
                          "versao_app": linha["versao_app"], "retrato": retrato})
        serie.append({"recebido_em": linha["recebido_em"], "maquina": linha["maquina"]})
    return {"embarcacao_id": emb, "atual": (atual if linhas else classificar_saude(None, None)),
            "serie": serie, "cortes": cortes}


def guardar_trecho_do_hd(pid: str, caminho: Path, bytes_recebidos: int, motivo: str = "") -> dict:
    """O bordo enviou o trecho: marca o pedido como pronto (o cliente baixa) ou registra o erro."""
    with conexao() as c:
        p = c.execute("SELECT * FROM hd_pedidos WHERE id=?", (pid,)).fetchone()
        if not p:
            return {"erro": "pedido nao encontrado"}
        if motivo:
            c.execute("UPDATE hd_pedidos SET estado='erro', motivo=?, pronto_em=? WHERE id=?",
                      (motivo[:200], em_iso(), pid))
        else:
            c.execute("""UPDATE hd_pedidos SET estado='enviado', trecho=?, bytes=?, motivo='', pronto_em=?
                         WHERE id=?""", (caminho.name, int(bytes_recebidos), em_iso(), pid))
    return {"ok": True, "id": pid, "estado": "enviado" if not motivo else "erro"}


def ler_desejo_e_estado(embarcacao_id: str) -> list[dict]:
    """Desejo (terra) x estado real (bordo) por camera — e' o que a tela do operador mostra lado a lado."""
    desejos = _desejo_das_cameras(embarcacao_id)
    with conexao() as c:
        reais = {r["camera_id"]: dict(r) for r in c.execute(
            "SELECT * FROM estado_bordo WHERE embarcacao_id=?", (embarcacao_id,)).fetchall()}
    for d in desejos:
        r = reais.get(d["camera_id"]) or {}
        d["estado_real"] = r.get("estado") or "desconhecido"
        d["estado_motivo"] = r.get("motivo") or ""
        d["gravando"] = bool(r.get("gravando"))
        d["estado_em"] = r.get("atualizado_em") or ""
    return desejos


def _vigiar_uma_vez(agora: dt.datetime | None = None) -> dict:
    """Uma passada da regra do tempo e do batimento (quem chama e' `vigiar_transmissoes`)."""
    agora = agora or dt.datetime.now(dt.timezone.utc)
    carimbo = agora.isoformat(timespec="seconds")
    limite_bat = (agora - dt.timedelta(seconds=SEGUNDOS_SEM_BATIMENTO)).isoformat(timespec="seconds")
    limite_resp = (agora - dt.timedelta(seconds=SEGUNDOS_SEM_RESPOSTA)).isoformat(timespec="seconds")
    limite_entrega = (agora - dt.timedelta(seconds=SEGUNDOS_ENTREGA_LENTA)).isoformat(timespec="seconds")
    limite_bordo = (agora - dt.timedelta(seconds=SEGUNDOS_SEM_BORDO)).isoformat(timespec="seconds")
    feitas = {"sem_batimento": [], "por_tempo": [], "sem_resposta": [], "bordo_mudo": []}
    with conexao() as c:
        # D-A (dono, 24/11/2026): a janela de 60 s vale tambem GRAVANDO — ao sair da tela e nao voltar em
        # 60 s a sessao morre (e a gravacao do lado terra encerra junto; o cliente e' avisado a baixar
        # antes). Por isso aqui NAO se filtra `gravando`: e' o contrario da expiracao POR TEMPO, que
        # espera a gravacao acabar (l. abaixo, `gravando=0`).
        sem_bat = [dict(x) for x in c.execute(
            "SELECT * FROM transmissoes WHERE estado IN ('pedida','no_ar') AND batimento_em < ?",
            (limite_bat,)).fetchall()]
        por_tempo = [dict(x) for x in c.execute(
            """SELECT * FROM transmissoes WHERE estado IN ('pedida','no_ar') AND gravando=0
               AND termina_em <> '' AND termina_em <= ?""", (carimbo,)).fetchall()]
        sem_resp = [dict(x) for x in c.execute(
            """SELECT t.* FROM transmissoes t
               JOIN ordens_do_bordo o ON o.transmissao_id = t.id AND o.acao='iniciar'
               WHERE t.estado='pedida'
                 AND ((o.estado='pedido' AND t.criada_em < ?)
                      OR (o.estado='entregue' AND o.entregue_em <> '' AND o.entregue_em < ?))""",
            (limite_resp, limite_entrega)).fetchall()]
        # FASE 6 (P0): de quem e' o ultimo sinal de vida? Vale o mais recente entre a SAUDE que o bordo
        # manda (60 s) e o ESTADO REAL das cameras que ele reporta. Silencio maior que SEGUNDOS_SEM_BORDO
        # em TODOS os sinais = a maquina de captura morreu (desinstalada, desligada, sem rede).
        mudo = []
        for linha in c.execute(
                "SELECT DISTINCT embarcacao_id FROM transmissoes WHERE estado IN ('pedida','no_ar')"
        ).fetchall():
            emb = linha["embarcacao_id"]
            sinais = []
            for sql in ("SELECT MAX(recebido_em) AS t FROM saude_bordo WHERE embarcacao_id=?",
                        "SELECT MAX(atualizado_em) AS t FROM estado_bordo WHERE embarcacao_id=?"):
                row = c.execute(sql, (emb,)).fetchone()
                if row and row["t"]:
                    sinais.append(row["t"])
            ultimo = max(sinais) if sinais else ""
            # sem NENHUM sinal conhecido (bordo novo, instalacao recente) nao e' silencio: nao encerra.
            if not ultimo or ultimo >= limite_bordo:
                continue
            for t in c.execute(
                    "SELECT * FROM transmissoes WHERE embarcacao_id=? AND estado IN ('pedida','no_ar')",
                    (emb,)).fetchall():
                mudo.append((dict(t), ultimo))
    for t, ultimo in mudo:
        # `sem_sinal` e' o estado que ja' existe para "a maquina de captura nao respondeu" (schema).
        if fechar_transmissao(t["id"], "sem_sinal",
                              "o computador de captura a bordo parou de responder (ultimo sinal "
                              + ultimo.replace("T", " ")[:19] + " UTC) — a transmissao foi encerrada"):
            feitas["bordo_mudo"].append(t["id"])
            parar_se_ninguem_vendo(t["embarcacao_id"], t["camera_id"], t["fluxo_id"],
                                   "o computador de captura a bordo ficou mudo")
    for t in sem_bat:
        if fechar_transmissao(t["id"], "encerrada",
                              "voce saiu da tela ao vivo por mais de 60 s (ou a tela foi fechada) — "
                              "a transmissao foi encerrada"):
            feitas["sem_batimento"].append(t["id"])
            parar_se_ninguem_vendo(t["embarcacao_id"], t["camera_id"], t["fluxo_id"],
                                   "nao havia mais ninguem vendo")
    for t in por_tempo:
        if fechar_transmissao(t["id"], "expirada", "o tempo da transmissao acabou — inicie de novo"):
            feitas["por_tempo"].append(t["id"])
            parar_se_ninguem_vendo(t["embarcacao_id"], t["camera_id"], t["fluxo_id"], "o tempo acabou")
    for t in sem_resp:
        if            fechar_transmissao(t["id"], "sem_sinal",
                               "a maquina de captura nao concluiu o pedido (sem resposta)"):
            feitas["sem_resposta"].append(t["id"])
    # A RECARGA NAO E' SAIDA: o pedido de saida que a tela mandou no `pagehide` so' vale se a tela NAO
    # voltar dentro da carencia — a pagina RECARREGADA bate ponto e cancela (`cancelar_saida`). Quem nao
    # volta, sai: as sessoes caem e o que ele gravou e' apagado (a regra do dono).
    for item in saidas_vencidas():
        SAIDAS_PENDENTES.pop(item["email"], None)
        try:
            _executar_saida(item)
            feitas.setdefault("saidas_da_tela", []).append(item["email"])
        except Exception as e:
            print("[api] aviso: saida da tela pendente:", type(e).__name__, e, flush=True)
    # gravacao pronta que ninguem baixou (a tela morreu sem avisar): o arquivo sai sozinho no prazo
    try:
        vencidas = apagar_gravacoes_vencidas()
        if vencidas["apagadas"]:
            feitas["gravacoes_vencidas"] = vencidas["apagadas"]
    except Exception as e:
        print("[api] aviso: limpeza das gravacoes vencidas:", type(e).__name__, e, flush=True)
    return feitas


# -------------------------------------- gravacao: avisar para baixar e apagar quando o cliente sai
# Decisao do dono (18/11/2026): a VPS mantem SO' O QUE FOI GRAVADO, e so' ate' o cliente baixar. No
# fim da gravacao o cliente e' AVISADO para baixar; quando ele sai da tela (ou desliga o sistema) o
# ARQUIVO e' apagado. O HISTORICO nao: `gravacoes` e a auditoria contam quem pediu, quem gravou, quem
# baixou e quando o arquivo saiu — sempre se sabe quais acoes foram tomadas e por quem.
MINUTOS_PARA_BAIXAR_PADRAO = 15.0


def minutos_para_baixar() -> float:
    """Quanto tempo o arquivo espera o cliente baixar (env `LECSOR_MINUTOS_PARA_BAIXAR`, padrao 15)."""
    try:
        return max(0.5, float(os.environ.get("LECSOR_MINUTOS_PARA_BAIXAR") or MINUTOS_PARA_BAIXAR_PADRAO))
    except Exception:
        return MINUTOS_PARA_BAIXAR_PADRAO


def _somar_minutos(carimbo, minutos: float) -> str:
    """`carimbo` + minutos, no mesmo formato do banco (ISO). Carimbo torto devolve ''."""
    try:
        return (dt.datetime.fromisoformat(str(carimbo))
                + dt.timedelta(minutes=float(minutos))).isoformat(timespec="seconds")
    except Exception:
        return ""


def registrar_gravacao_comecou(t) -> None:
    """A gravacao comecou: abre a ficha no banco (bytes/segundos entram quando ela fica pronta)."""
    with conexao() as c:
        c.execute("""INSERT INTO gravacoes (transmissao_id,embarcacao_id,usuario_email,camera_id,comecou_em)
                     VALUES (?,?,?,?,?) ON CONFLICT(transmissao_id) DO UPDATE SET
                       usuario_email=excluded.usuario_email, camera_id=excluded.camera_id""",
                  (t["id"], t["embarcacao_id"], t["usuario_email"], t["camera_id"], em_iso()))


def registrar_gravacao_pronta(tid: str, r: dict) -> None:
    """A gravacao acabou: o arquivo esta' pronto e o cliente TEM de ser avisado."""
    with conexao() as c:
        c.execute("UPDATE gravacoes SET bytes=?, segundos=?, pronta_em=? WHERE transmissao_id=?",
                  (int(r.get("bytes") or 0), int(r.get("segundos") or 0), em_iso(), tid))


def gravacoes_prontas_do_cliente(email: str, embarcacao_id: str = "") -> list:
    """As gravacoes prontas e ainda no disco deste cliente — o aviso da tela sai daqui."""
    with conexao() as c:
        if embarcacao_id:
            linhas = [dict(x) for x in c.execute(
                """SELECT * FROM gravacoes WHERE usuario_email=? AND apagada_em='' AND embarcacao_id=?
                   ORDER BY pronta_em DESC LIMIT 20""", (email, embarcacao_id)).fetchall()]
        else:
            linhas = [dict(x) for x in c.execute(
                """SELECT * FROM gravacoes WHERE usuario_email=? AND apagada_em=''
                   ORDER BY pronta_em DESC LIMIT 20""", (email,)).fetchall()]
    saidas = []
    for g in linhas:
        if not g.get("pronta_em"):
            continue                       # ainda gravando: nao ha' o que baixar
        if not (gravacao_modulo.arquivo(g["transmissao_id"]).exists()
                or gravacao_modulo.parcial(g["transmissao_id"]).exists()):
            continue                       # o arquivo ja' nao esta' no disco
        saidas.append({"transmissao_id": g["transmissao_id"], "camera_id": g["camera_id"],
                       "embarcacao_id": g["embarcacao_id"], "bytes": int(g.get("bytes") or 0),
                       "segundos": int(g.get("segundos") or 0), "pronta_em": g.get("pronta_em", ""),
                       "avisada_em": g.get("avisada_em", ""), "baixada_em": g.get("baixada_em", ""),
                       "baixar_em": f"/api/gravacoes/{g['transmissao_id']}",
                       "baixar_ate": _somar_minutos(g.get("pronta_em"), minutos_para_baixar())})
    return saidas


def marcar_gravacoes_avisadas(email: str, ip: str = "") -> int:
    """A primeira vez que o cliente ve o aviso: registra `gravacao_avisada` (uma vez por gravacao)."""
    n = 0
    for g in gravacoes_prontas_do_cliente(email):
        if g.get("avisada_em"):
            continue
        with conexao() as c:
            c.execute("UPDATE gravacoes SET avisada_em=? WHERE transmissao_id=? AND avisada_em=''",
                      (em_iso(), g["transmissao_id"]))
        auditar(None, "gravacao_avisada",
                f"{g['camera_id']} de {email} ({g['bytes']} B) — baixe antes de sair da tela", ip)
        n += 1
    return n


def apagar_gravacoes_do_cliente(u, motivo: str, ip: str = "", embarcacao_id: str = "") -> dict:
    """APAGA os ARQUIVOS das gravacoes prontas deste cliente. Historico e auditoria NAO sao tocados."""
    feito = {"apagadas": [], "adiadas": [], "bytes": 0, "motivo": motivo}
    for g in gravacoes_prontas_do_cliente(u["email"], embarcacao_id):
        r = gravacao_modulo.apagar(g["transmissao_id"])
        if r.get("adiado"):
            feito["adiadas"].append(g["transmissao_id"])      # tem download em andamento: tenta depois
            continue
        with conexao() as c:
            c.execute("UPDATE gravacoes SET apagada_em=? WHERE transmissao_id=?",
                      (em_iso(), g["transmissao_id"]))
        feito["bytes"] += int(r.get("bytes") or 0)
        feito["apagadas"].append(g["transmissao_id"])
        auditar(u, "gravacoes_apagadas",
                f"{g['camera_id']} de {u['email']} ({r.get('bytes', 0)} B) — {motivo}", ip)
    return feito


def sair_da_tela(email: str, embarcacao_id: str = "", ip: str = "", id_usuario=None) -> dict:
    """O CLIENTE SAIU DA TELA: as sessoes dele caem e o que ele gravou e' APAGADO. O historico e a
    auditoria ficam — sempre se sabe quais acoes foram tomadas e por quem (o dono, 18/11/2026).

    Dois caminhos chegam aqui: o pedido da PROPRIA tela (na hora) e o fim da carencia do `pagehide`
    (a recarga nao voltou — ver `pendurar_saida`). E' o mesmo trabalho nos dois.
    """
    quem = {"id": id_usuario, "email": email}
    with conexao() as c:
        abertas = [dict(x) for x in c.execute(
            "SELECT * FROM transmissoes WHERE usuario_email=? AND estado IN ('pedida','no_ar')",
            (email,)).fetchall()]
    fechadas = 0
    for t in abertas:
        if t.get("gravando"):
            # gravando, a sessao NAO morre no meio (o dono fixou: gravacao nao e' picada); a tela do
            # cliente esta' saindo, entao a gravacao PARA e o arquivo fica pronto para ser apagado
            # junto (o aviso nao teria onde aparecer: a tela foi embora).
            try:
                r = gravacao_modulo.parar(t["id"])
                registrar_gravacao_pronta(t["id"], r)
                with conexao() as c:
                    c.execute("UPDATE transmissoes SET gravando=0 WHERE id=?", (t["id"],))
                auditar(quem, "gravacao_parada",
                        f"{t['camera_id']} ({r.get('bytes', 0)} B) — o cliente saiu da tela", ip)
            except Exception:
                pass
        if fechar_transmissao(t["id"], "encerrada", "a tela do cliente foi fechada"):
            fechadas += 1
            parar_se_ninguem_vendo(t["embarcacao_id"], t["camera_id"], t["fluxo_id"],
                                   "o cliente saiu da tela")
    feito = apagar_gravacoes_do_cliente(quem, "o cliente saiu da tela", ip, embarcacao_id)
    auditar(quem, "cliente_saiu_da_tela",
            f"{fechadas} sessao(oes) fechada(s), {len(feito['apagadas'])} gravacao(oes) "
            f"apagada(s), {feito['bytes']} B", ip)
    return {"sessoes_fechadas": fechadas, **feito}


def gravacoes_recentes(limite: int = 50) -> list:
    """As gravacoes recentes de TODAS as embarcacoes (a operacao ve a trilha: quem, quanto, quando
    baixou e quando o ARQUIVO foi apagado — nunca o conteudo de outro cliente)."""
    with conexao() as c:
        linhas = [dict(x) for x in c.execute(
            """SELECT * FROM gravacoes ORDER BY comecou_em DESC LIMIT ?""", (int(limite),)).fetchall()]
        nomes_emb = {r["id"]: r["nome"] for r in c.execute("SELECT id,nome FROM embarcacoes")}
    for g in linhas:
        g["embarcacao_nome"] = nomes_emb.get(g["embarcacao_id"], g["embarcacao_id"])
        g["no_disco"] = bool(gravacao_modulo.arquivo(g["transmissao_id"]).exists())
        g["baixar_ate"] = _somar_minutos(g.get("pronta_em"), minutos_para_baixar()) if g.get("pronta_em") else ""
    return linhas


def gravacoes_da_embarcacao(embarcacao_id: str) -> list:
    """O que a OPERACAO ve: as gravacoes da embarcacao e QUANDO cada arquivo foi apagado.

    Nunca o conteudo de outro cliente — so' a trilha: quem pediu, quanto tinha, se baixou e quando o
    arquivo saiu (o dono quer saber sempre quais acoes foram tomadas e por quem).
    """
    with conexao() as c:
        linhas = [dict(x) for x in c.execute(
            """SELECT * FROM gravacoes WHERE embarcacao_id=? ORDER BY comecou_em DESC LIMIT 50""",
            (embarcacao_id,)).fetchall()]
    for g in linhas:
        g["no_disco"] = bool(gravacao_modulo.arquivo(g["transmissao_id"]).exists())
        g["baixar_ate"] = _somar_minutos(g.get("pronta_em"), minutos_para_baixar()) if g.get("pronta_em") else ""
    return linhas


def apagar_gravacoes_vencidas() -> dict:
    """Rede de seguranca: gravacao pronta que ninguem baixou (a tela morreu sem avisar) sai sozinha."""
    limite = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(minutes=minutos_para_baixar())).isoformat(timespec="seconds")
    with conexao() as c:
        vencidas = [dict(x) for x in c.execute(
            """SELECT * FROM gravacoes WHERE apagada_em='' AND pronta_em <> '' AND pronta_em < ?""",
            (limite,)).fetchall()]
    feito = {"apagadas": [], "adiadas": []}
    for g in vencidas:
        r = gravacao_modulo.apagar(g["transmissao_id"])
        if r.get("adiado"):
            feito["adiadas"].append(g["transmissao_id"])
            continue
        with conexao() as c:
            c.execute("UPDATE gravacoes SET apagada_em=? WHERE transmissao_id=?",
                      (em_iso(), g["transmissao_id"]))
        feito["apagadas"].append(g["transmissao_id"])
        auditar(None, "gravacoes_apagadas",
                f"{g['camera_id']} de {g['usuario_email']} ({r.get('bytes', 0)} B) — "
                "o prazo para baixar terminou", "")
    return feito


def vigiar_transmissoes(intervalo: float = 5.0) -> None:
    """Vigia do lado terra: tempo maximo e batimento da tela do cliente."""
    while True:
        try:
            _vigiar_uma_vez()
        except Exception as e:
            print("[api] aviso: vigia das transmissoes:", type(e).__name__, e, flush=True)
        time.sleep(intervalo)


# --------------------------------------------------------------------------- banco / inicializacao
def inicializar(semear_demo: bool = False) -> None:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    # Tabelas que o codigo criava sob demanda (compressoes, telemetria_minuto, latencia_medicoes):
    # numa instalacao limpa o historico de producao reclamava "no such table: compressoes" a cada
    # minuto e a tela de compressoes vinha vazia. Criar aqui deixa o banco novo igual ao da bancada.
    try:
        etapas_pipeline.garantir_tabela()
        trecho_modulo.garantir_tabela()   # historico dos trechos baixados (prova da compressao)
        producao_pipeline.garantir_tabelas()
    except Exception as e:  # banco ocupado no boot nao pode derrubar a API
        print("[api] aviso: nao criei as tabelas sob demanda:", type(e).__name__, e, flush=True)
    with conexao() as c:
        # schema.sql primeiro; os das fases em seguida. Todos os `db/schema*.sql` entram — instalar
        # num banco vazio tem que dar o MESMO banco que a bancada (faltava o schema-ingestao.sql:
        # em instalacao limpa a tabela `ingestoes` nao existia).
        esquemas = [RAIZ / "db" / "schema.sql"] + sorted(
            p for p in (RAIZ / "db").glob("schema*.sql") if p.name != "schema.sql")
        for esquema in esquemas:
            c.executescript(esquema.read_text(encoding="utf-8"))
        # Instalacao limpa/antiga fica com `cameras` SEM as colunas de endereco (o schema criava so'
        # id/embarcacao/rotulo/fluxo/local/ativo) e o CADASTRO DE CAMERA quebrava com "table cameras
        # has no column named ip" — exatamente na maquina das cameras, que e' onde o operador cadastra.
        # A coluna que faltar e' criada aqui; o endereco continua saindo so' para operacao
        # (`/api/cameras/detalhe`) e nunca para a tela do cliente.
        colunas = {r["name"] for r in c.execute("PRAGMA table_info(cameras)")}
        for nome, tipo in (("ip", "TEXT DEFAULT ''"), ("porta", "TEXT DEFAULT ''"),
                           ("protocolo", "TEXT DEFAULT 'rtsp'"), ("canal", "TEXT DEFAULT ''"),
                           ("alvo", "TEXT DEFAULT ''")):
            if nome not in colunas:
                c.execute(f"ALTER TABLE cameras ADD COLUMN {nome} {tipo}")
        # TIPO da camera (dono, 25/11/2026): "petrobras ou ibama pode acessar todas as embarcacoes de
        # todas as empresas, mas apenas do radar de oleo e camera flir se tiver". O filtro do
        # observador deixa de ser por NOME e passa a ser por TIPO gravado: camera | radar | flir.
        # Instalacao que ATUALIZA ganha a coluna aqui e o backfill pelo nome de hoje (quem diz "radar"
        # vira 'radar'; 'flir' vira 'flir'; o resto fica 'camera'). Sem passo manual no cliente.
        if "tipo" not in colunas:
            c.execute("ALTER TABLE cameras ADD COLUMN tipo TEXT NOT NULL DEFAULT 'camera'")
            nome_cam = ("lower(COALESCE(id,'')||' '||COALESCE(rotulo,'')||' '||COALESCE(fluxo_id,'')"
                        "||' '||COALESCE(local,'')||' '||COALESCE(alvo,''))")
            c.execute(f"UPDATE cameras SET tipo='flir' WHERE {nome_cam} LIKE '%flir%'")
            c.execute(f"UPDATE cameras SET tipo='radar' WHERE tipo='camera' AND {nome_cam} LIKE '%radar%'")
        # RADAR por embarcacao (Fase 6): instalacao que ATUALIZA ganha as colunas aqui, sem passo
        # manual no cliente — a config da embarcacao (fonte, modo, taxa, alvo) mora nestas colunas.
        colunas_emb = {r["name"] for r in c.execute("PRAGMA table_info(embarcacoes)")}
        for nome, tipo in (("radar_fonte", "TEXT DEFAULT ''"), ("radar_modo", "TEXT DEFAULT 'ppi'"),
                           ("radar_taxa", "TEXT DEFAULT '30fps'"), ("radar_alvo", "TEXT DEFAULT ''")):
            if nome not in colunas_emb:
                c.execute(f"ALTER TABLE embarcacoes ADD COLUMN {nome} {tipo}")
        # FLAG de estado (0.7.0): instalacao que atualiza ganha a coluna `manual` do desejo aqui — o
        # boto do operador (stand-by) precisa vencer o "ninguem esta' assistindo" sem passo manual.
        colunas_desejo = {r["name"] for r in c.execute("PRAGMA table_info(desejo_camera)")}
        if colunas_desejo and "manual" not in colunas_desejo:
            c.execute("ALTER TABLE desejo_camera ADD COLUMN manual TEXT NOT NULL DEFAULT ''")
        # D3 do dono (24/11/2026): o LIGAR manual nao existe mais — quem liga e' o cliente que esta'
        # assistindo. Uma instalacao que ATUALIZA pode ter `manual='ligar'` gravado pela versao antiga (e
        # era isso que mantinha a transmissao no ar sem ninguem vendo): limpa aqui, sozinho, no boot.
        if colunas_desejo:
            c.execute("UPDATE desejo_camera SET manual='' WHERE manual='ligar'")
        # Papel `tecnico` (bordo) precisa do CHECK novo. SQLite nao altera CHECK no lugar: o
        # `db/migracao-tecnico.sql` recria a tabela preservando as linhas, e roda aqui para a
        # instalacao que ATUALIZA se consertar sozinha (o dono nao faz passo manual no cliente).
        tabela = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone()
        if tabela and "tecnico" not in (tabela["sql"] or ""):
            import sqlite3 as _sqlite3
            script = (RAIZ / "db" / "migracao-tecnico.sql").read_text(encoding="utf-8")
            try:
                c.executescript(script)
                print("[api] migracao aplicada: papel tecnico em usuarios", flush=True)
            except _sqlite3.Error as e:
                print("[api] aviso: nao apliquei a migracao do papel tecnico:", e, flush=True)
        # Papel `observador` (tipo 4 do dono, 19/11/2026 — Petrobras ve todas as embarcacoes de todas
        # as empresas, so' leitura): mesmo caminho do tecnico, mesma tabela recriada preservando tudo.
        tabela = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone()
        if tabela and PAPEL_OBSERVADOR not in (tabela["sql"] or ""):
            import sqlite3 as _sqlite3
            script = (RAIZ / "db" / "migracao-observador.sql").read_text(encoding="utf-8")
            try:
                c.executescript(script)
                print("[api] migracao aplicada: papel observador em usuarios", flush=True)
            except _sqlite3.Error as e:
                print("[api] aviso: nao apliquei a migracao do papel observador:", e, flush=True)
        for f in json.loads((RAIZ / "db" / "fases-seed.json").read_text(encoding="utf-8")):
            c.execute("""INSERT INTO fases (id,numero,nome,prioridade,status,criterio_aceite,evidencia)
                         VALUES (:id,:numero,:nome,:prioridade,:status,:criterio_aceite,:evidencia)
                         ON CONFLICT(id) DO UPDATE SET numero=:numero,nome=:nome,prioridade=:prioridade,
                           status=:status,criterio_aceite=:criterio_aceite,evidencia=:evidencia""", f)
        csvp = RAIZ / "bench" / "inventario-cameras.csv"
        if csvp.exists():
            import csv as _csv
            with open(csvp, newline="", encoding="utf-8") as fh:
                for linha in _csv.DictReader(fh):
                    if not (linha.get("id") or "").strip():
                        continue
                    colunas = ["id", "fabricante_modelo", "ip", "porta", "protocolo", "canal_gravador",
                               "resolucao", "fps", "codec_nativo", "credencial_ref", "local_instalacao", "restricao_acesso"]
                    c.execute(f"INSERT OR REPLACE INTO inventario_cameras ({','.join(colunas)}) "
                              f"VALUES ({','.join(':' + k for k in colunas)})",
                              {k: (linha.get(k) or "").strip() for k in colunas})
        pasta_saida = RAIZ / "bench" / "saida"
        for jp in sorted(pasta_saida.glob("*.json")) if pasta_saida.exists() else []:
            try:
                d = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict) or "hardware" not in d or "versoes" not in d or "medicoes" not in d:
                continue  # nem todo JSON da bancada e resultado de medicao
            hw = f"{d['hardware']['gpu']} | {d['versoes']['ffmpeg'].split(' Copyright')[0]}"
            for m in d.get("medicoes", []):
                if m.get("status") != "ok":
                    continue
                valor = (f"bitrate {m.get('bitrate_cod_mbps')} Mbps; corte {m.get('corte_pct')}%; "
                         f"VMAF {m.get('vmaf')}; {m.get('vezes_tempo_real')}x tempo real")
                comando = m.get("comando", "")
                fonte_rel = str(jp.relative_to(RAIZ).as_posix())
                if not c.execute("SELECT 1 FROM medicoes WHERE valor=? AND fonte=? AND comando=?",
                                 (valor, fonte_rel, comando)).fetchone():
                    c.execute("""INSERT INTO medicoes (valor,fonte,data,hardware_versao,comando,fase_id)
                                 VALUES (?,?,?,?,?,?)""", (valor, fonte_rel, d["gerado_em"], hw, comando, "fase-0a"))
        for f, caminho, desc, data in [
            ("fase-0a", "bench/EVIDENCIA-fase0a.md", "Evidencia da Fase 0-A (medicoes, SRT e teste negativo)", "2026-11-06"),
            ("fase-0a", "bench/saida/resultado-fase0.json", "Registro bruto das medicoes", "2026-11-06"),
            ("fase-0a", "ground/EVIDENCIA-latencia-ponta-a-ponta.md", "Latencia ponta a ponta medida (live 1,568 s; HLS 2,596-3,087 s)", "2026-11-06"),
        ]:
            if not c.execute("SELECT 1 FROM evidencias WHERE caminho=?", (caminho,)).fetchone():
                c.execute("INSERT INTO evidencias (fase_id,caminho,descricao,data) VALUES (?,?,?,?)", (f, caminho, desc, data))
        # clientes / embarcacoes / cameras do produto
        c.execute("INSERT OR IGNORE INTO clientes (id,nome) VALUES ('lecsor','LECSOR (interno)')")
        c.execute("INSERT OR IGNORE INTO clientes (id,nome) VALUES ('armador-demo','Armador Exemplo')")
        c.execute("""INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)
                     VALUES ('bancada','lecsor','Bancada de testes (propria)','','em operacao')""")
        # cameras da bancada: so numa instalacao nova. Sem essa trava, toda reinicializacao
        # recriava a camera que o operador excluiu (era por isso que a exclusao "nao pegava").
        cameras_novas = not c.execute("SELECT 1 FROM cameras LIMIT 1").fetchone()
        for cam in json.loads((RAIZ / "ground" / "receivers.json").read_text(encoding="utf-8")):
            if not cameras_novas:
                break
            c.execute("""INSERT OR IGNORE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local)
                         VALUES (?,?,?,?,?)""",
                      (cam["id"], "bancada", cam["rotulo"], cam["id"], "bancada"))
        # embarcacao do cliente demo: mesma bancada, outro dono (prova o isolamento por cliente)
        c.execute("""INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)
                     VALUES ('psv-exemplo','armador-demo','PSV Exemplo (demo)','9123456','em operacao')""")
        for cam in json.loads((RAIZ / "ground" / "receivers.json").read_text(encoding="utf-8")):
            if not cameras_novas:
                break
            c.execute("""INSERT OR IGNORE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local)
                         VALUES (?,?,?,?,?)""",
                      (cam["id"] + "-demo", "psv-exemplo", cam["rotulo"].replace("Bancada —", "PSV (demo) —"), cam["id"], "bancada"))
        c.execute("""INSERT OR IGNORE INTO documentos (slug,titulo,caminho,versao,status,atualizado_em) VALUES
            ('pipeline','Plano de P&D — pipeline de video bordo->terra','.hermes/plans/2026-11-06_122553-pipeline-video-bordo-terra-starlink.md','v3','atual','2026-11-06'),
            ('software','Plano de desenvolvimento de software','.hermes/plans/2026-11-06_140030-plano-desenvolvimento-software-pipeline-video.md','v3','atual','2026-11-06'),
            ('ti','Guia tecnico do TI (bancada e testes)','.hermes/plans/2026-11-06_150540-guia-ti-bancada-testes-pipeline-video.md','v1','atual','2026-11-06')""")
    if semear_demo:
        semear_usuarios_demo()


def semear_usuarios_demo() -> None:
    """Cria os usuarios de demonstracao com senha ALEATORIA, impressa uma vez.

    Senha nunca fica no repositorio: so o hash entra no banco.
    """
    demo = [("cliente@armador-demo.test", "Cliente do armador (demo)", "cliente", "armador-demo"),
            ("operacao@lecsor.test", "Operacao LECSOR (demo)", "operador", None),
            ("admin@lecsor.test", "Administrador LECSOR (demo)", "admin", None),
            # a bancada e da LECSOR: este login de teste abre o app do cliente vendo a bancada
            ("cliente@lecsor.test", "Bancada de testes (cliente interno)", "cliente", "lecsor")]
    with conexao() as c:
        for email, nome, papel, cliente_id in demo:
            if c.execute("SELECT 1 FROM usuarios WHERE email=?", (email,)).fetchone():
                continue
            senha = os.environ.get("LECSOR_SENHA_DEMO") or secrets.token_urlsafe(9)
            salt = secrets.token_hex(16)
            c.execute("""INSERT INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt)
                         VALUES (?,?,?,?,?,?,?)""",
                      (email.split("@")[0] + "-" + secrets.token_hex(3), email, nome, papel, cliente_id,
                       hash_senha(senha, salt), salt))
            print(f"[demo] {email}  senha (mostrada uma vez): {senha}", flush=True)


def inserir_medicao(dados: dict) -> tuple[int, dict]:
    faltando = [k for k in CAMPOS_OBRIGATORIOS if not str(dados.get(k, "")).strip()]
    if faltando:
        return 422, {"erro": "medicao rejeitada pelo schema: campo obrigatorio vazio",
                     "campos_faltando": faltando,
                     "regra": "valor + fonte + data + hardware_versao + comando (NOT NULL)"}
    with conexao() as c:
        cur = c.execute("""INSERT INTO medicoes (valor,fonte,data,hardware_versao,comando,fase_id)
                           VALUES (:valor,:fonte,:data,:hardware_versao,:comando,:fase_id)""",
                        {**{k: dados.get(k, "") for k in CAMPOS_OBRIGATORIOS}, "fase_id": dados.get("fase_id")})
        return 201, {"id": cur.lastrowid, "status": "gravada"}


# --------------------------------------------------------------------------- estado do lado terra
_CACHE_HOST = {}          # host -> (quando, resposta, validade): falha fica em cache mais tempo


def mediamtx_json(caminho: str, host: str = "127.0.0.1", timeout: float = 1.0) -> dict:
    """Le a API do mediamtx de um host, com cache curto.

    Sem cache, um mediamtx que NAO esta no ar custa o timeout inteiro a cada requisicao (no Windows
    o connect para porta fechada chega a pendurar ~2 s) e a tela do dono demora para abrir.
    Sucesso fica em cache 2 s; falha, 10 s.
    """
    import time as _t
    agora_m = _t.time()
    guardado = _CACHE_HOST.get(host)
    if guardado and agora_m - guardado[0] < guardado[2]:
        return guardado[1]
    try:
        with urllib.request.urlopen(f"http://{host}:{PORTA_API_MEDIAMTX}{caminho}", timeout=timeout) as r:
            dados = json.loads(r.read().decode())
        _CACHE_HOST[host] = (agora_m, dados, 2.0)
        return dados
    except Exception:
        _CACHE_HOST[host] = (agora_m, {}, 10.0)
        return {}


def hosts_com_fluxo() -> list[str]:
    """Todos os mediamtx que podem ter fluxo: esta maquina + cada host usado pelos envios recentes.

    Sem isso o painel procurava o video so no mediamtx local e dizia 'sem sinal' para um fluxo que
    estava no ar em outro servidor (a webcam desta bancada publica na VPS).
    """
    hosts = ["127.0.0.1"]
    try:
        with conexao() as c:
            for r in c.execute("""SELECT DISTINCT srt_host FROM ingestoes
                                  WHERE srt_host IS NOT NULL AND srt_host <> ''
                                  ORDER BY id DESC LIMIT 10"""):
                h = (r["srt_host"] or "").strip()
                if h and h not in hosts:
                    hosts.append(h)
    except Exception:
        pass
    return hosts


_CACHE_MEDIAMTX = {"em": 0.0, "dados": {}}


def caminhos_do_mediamtx(validade_s: float = 2.0) -> dict:
    """Junta a lista de caminhos de TODOS os mediamtx conhecidos (local + lado terra).

    Fica em cache por 2 s: sem isso cada tela pagava o tempo de sondar o servidor remoto e o
    painel demorava para abrir.
    """
    import time as _t
    agora_m = _t.time()
    if _CACHE_MEDIAMTX["dados"] and (agora_m - _CACHE_MEDIAMTX["em"]) < validade_s:
        return _CACHE_MEDIAMTX["dados"]
    mt = {}
    for h in hosts_com_fluxo():
        for p in mediamtx_json("/v3/paths/list", h).get("items", []):
            mt[p["name"]] = p          # o local tem prioridade; o remoto completa o resto
    if mt:
        _CACHE_MEDIAMTX["em"], _CACHE_MEDIAMTX["dados"] = agora_m, mt
    return mt


def fluxos() -> dict:
    mt = caminhos_do_mediamtx()
    itens = []
    with conexao() as c:
        for cam in c.execute("SELECT * FROM cameras WHERE ativo=1 ORDER BY id").fetchall():
            p = mt.get(cam["fluxo_id"], {})
            itens.append({"id": cam["id"], "fluxo_id": cam["fluxo_id"], "rotulo": cam["rotulo"],
                          # o alvo vai aqui porque /api/fluxos e' a tela do PC DE CAPTURA (o dono escolhe
                          # a qualidade olhando a propria imagem); nao e' rota do app do cliente
                          "alvo": cam["alvo"] or "",
                          "embarcacao_id": cam["embarcacao_id"], "no_ar": bool(p.get("ready")),
                          "tracks": p.get("tracks", []), "leitores": len(p.get("readers", []))})
    return {"fluxos": itens, "atualizado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "mediamtx": {"ativo": bool(mt)}}


def perfil_encoder(camera_id: str) -> dict:
    """Dados reais do encode da bancada (perfil do agente), para a tela nao inventar numero."""
    for jp in sorted((RAIZ / "board" / "perfis").glob("*.json")) if (RAIZ / "board" / "perfis").exists() else []:
        try:
            for item in json.loads(jp.read_text(encoding="utf-8")):
                if item.get("id") == camera_id:
                    fonte = item.get("fonte", "")
                    import re as _re
                    m = _re.search(r"size=(\d+x\d+):rate=(\d+)", fonte)
                    return {"codec": item.get("codec", ""), "bitrate": item.get("bitrate", ""),
                            "resolucao": m.group(1) if m else "", "fps": int(m.group(2)) if m else None}
        except Exception:
            continue
    return {}


def ler_tudo() -> dict:
    with conexao() as c:
        q = lambda sql, *a: [dict(r) for r in c.execute(sql, a).fetchall()]
        return {"fases": q("SELECT * FROM fases ORDER BY numero, id"),
                "medicoes": q("SELECT * FROM medicoes ORDER BY id DESC"),
                "inventario": q("SELECT * FROM inventario_cameras ORDER BY id"),
                "evidencias": q("SELECT * FROM evidencias ORDER BY fase_id, id"),
                "documentos": q("SELECT * FROM documentos ORDER BY slug"),
                "decisoes": q("SELECT * FROM decisoes ORDER BY id DESC"),
                "auditoria": q("SELECT auditoria_acesso.*, u.nome AS usuario_nome FROM auditoria_acesso "
                               "LEFT JOIN usuarios u ON u.id = auditoria_acesso.usuario_id ORDER BY auditoria_acesso.id DESC LIMIT 200"),
                "eventos": q("SELECT * FROM analytics_eventos ORDER BY id DESC LIMIT 200"),
                "contagens": q("SELECT * FROM analytics_contagens ORDER BY id DESC LIMIT 200"),
                "agentes": q("SELECT * FROM analytics_agentes ORDER BY camera_id"),
                "gerado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds")}


# --------------------------------------------------------------------------- Fase 5: analises
def analises() -> dict:
    """O que a tela precisa saber das analises: estado do agente, ultimas caixas, contagens e eventos."""
    with conexao() as c:
        q = lambda sql, *a: [dict(r) for r in c.execute(sql, a).fetchall()]
        agentes = q("SELECT * FROM analytics_agentes ORDER BY camera_id")
        for ag in agentes:
            for campo in ("caixas", "linhas", "zonas"):
                try:
                    ag[campo] = json.loads(ag[campo] or "[]")
                except json.JSONDecodeError:
                    ag[campo] = []
        return {"agentes": agentes,
                "contagens": q("SELECT * FROM analytics_contagens ORDER BY id DESC LIMIT 60"),
                "eventos": q("SELECT * FROM analytics_eventos ORDER BY id DESC LIMIT 60"),
                "gerado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds")}


def ler_marcas(camera_id: str = "") -> dict:
    """Marcas desenhadas pelo operador (linha e zonas), em fracao do quadro."""
    with conexao() as c:
        if camera_id:
            r = c.execute("SELECT * FROM analytics_marcas WHERE camera_id=?", (camera_id,)).fetchone()
            if not r:
                return {"camera_id": camera_id, "linha": None, "zonas": []}
            return {"camera_id": r["camera_id"], "linha": json.loads(r["linha"]) if r["linha"] else None,
                    "zonas": json.loads(r["zonas"] or "[]"), "atualizado_em": r["atualizado_em"],
                    "atualizado_por": r["atualizado_por"]}
        return {"marcas": [dict(x) for x in c.execute("SELECT * FROM analytics_marcas ORDER BY camera_id").fetchall()]}


def gravar_marcas(usuario, camera_id: str, linha, zonas: list) -> dict:
    """Grava a linha e as zonas da camera. Tudo em fracao do quadro (0..1), validado na borda."""
    def ponto(p, nome):
        x, y = float(p[0]), float(p[1])
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"{nome}: coordenada fora do quadro ({x}, {y})")
        return [round(x, 4), round(y, 4)]

    if linha is not None:
        linha = {"a": ponto(linha["a"], "linha.a"), "b": ponto(linha["b"], "linha.b")}
    limpas = []
    for z in zonas or []:
        x, y, l, a2 = (float(z.get(k, 0)) for k in ("x", "y", "l", "a"))
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < l <= 1 and 0 < a2 <= 1):
            raise ValueError(f"zona {z.get('nome', '')}: retangulo fora do quadro")
        limpas.append({"nome": str(z.get("nome") or "zona"), "x": round(x, 4), "y": round(y, 4),
                       "l": round(l, 4), "a": round(a2, 4), "segundos": float(z.get("segundos") or 2.0)})
    agora = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with conexao() as c:
        if not c.execute("SELECT 1 FROM cameras WHERE id=?", (camera_id,)).fetchone():
            raise LookupError(f"camera {camera_id!r} nao cadastrada")
        c.execute("""INSERT INTO analytics_marcas (camera_id,linha,zonas,atualizado_em,atualizado_por)
                     VALUES (:camera_id,:linha,:zonas,:atualizado_em,:atualizado_por)
                     ON CONFLICT(camera_id) DO UPDATE SET linha=:linha, zonas=:zonas,
                       atualizado_em=:atualizado_em, atualizado_por=:atualizado_por""",
                  {"camera_id": camera_id, "linha": json.dumps(linha or "", ensure_ascii=False),
                   "zonas": json.dumps(limpas, ensure_ascii=False), "atualizado_em": agora,
                   "atualizado_por": (usuario["email"] if usuario else "agente")})
    auditar(usuario, "marcas_gravadas", camera_id)
    return ler_marcas(camera_id)


def registrar_eventos(camera_id: str, eventos: list) -> int:
    """Grava eventos de analise da camera. O video NAO sobe: so o evento e a contagem."""
    agora = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with conexao() as c:
        if not c.execute("SELECT 1 FROM cameras WHERE id=?", (camera_id,)).fetchone():
            raise LookupError(f"camera {camera_id!r} nao cadastrada")
        for ev in eventos[:500]:
            inicio = str(ev.get("em") or agora)
            c.execute("""INSERT INTO analytics_eventos (camera_id,tipo,inicio,fim,confianca,clipe,metadados,criado_em)
                         VALUES (?,?,?,?,?,?,?,?)""",
                      (camera_id, str(ev.get("tipo") or "contagem"), inicio, ev.get("fim"),
                       float(ev.get("confianca") or 0.0), str(ev.get("clipe") or ""),
                       json.dumps(ev.get("metadados") or {}, ensure_ascii=False), agora))
    return len(eventos[:500])


def registrar_contagem(camera_id: str, d: dict) -> int:
    """Grava a contagem da janela e atualiza o estado do agente (inclusive as ultimas caixas)."""
    agora = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    inicio = str(d.get("janela_inicio") or agora)
    fim = str(d.get("janela_fim") or agora)
    with conexao() as c:
        if not c.execute("SELECT 1 FROM cameras WHERE id=?", (camera_id,)).fetchone():
            raise LookupError(f"camera {camera_id!r} nao cadastrada")
        cur = c.execute("""INSERT INTO analytics_contagens (camera_id,janela_inicio,janela_fim,entrou,saiu,pico,fonte,criado_em)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (camera_id, inicio, fim, int(d.get("entrou") or 0), int(d.get("saiu") or 0),
                         int(d.get("pico") or 0), str(d.get("fonte") or ""), agora))
        ident = cur.lastrowid
        estado = str(d.get("estado") or "no ar")
        c.execute("""INSERT INTO analytics_agentes (camera_id,nome,modelo,fonte,fps,quadros,estado,caixas,caixas_idade,linhas,zonas,erros,ultimo_visto)
                     VALUES (:camera_id,:nome,:modelo,:fonte,:fps,:quadros,:estado,:caixas,:caixas_idade,:linhas,:zonas,:erros,:ultimo_visto)
                     ON CONFLICT(camera_id) DO UPDATE SET nome=:nome, modelo=:modelo, fonte=:fonte, fps=:fps,
                       quadros=:quadros, estado=:estado, caixas=:caixas, caixas_idade=:caixas_idade, linhas=:linhas, zonas=:zonas, erros=:erros,
                       ultimo_visto=:ultimo_visto""",
                  {"camera_id": camera_id, "nome": str(d.get("agente") or "agente-bordo"),
                   "modelo": str(d.get("modelo") or ""), "fonte": str(d.get("fonte") or ""),
                   "fps": float(d.get("fps") or 0.0), "quadros": int(d.get("quadros") or 0),
                   "estado": estado, "caixas": json.dumps(d.get("caixas") or [], ensure_ascii=False),
                   "linhas": json.dumps(d.get("linhas") or [], ensure_ascii=False),
                   "caixas_idade": float(d.get("caixas_idade") or 0.0),
                   "zonas": json.dumps(d.get("zonas") or [], ensure_ascii=False),
                   "erros": int(d.get("erros") or 0), "ultimo_visto": agora})
    return ident


# --------------------------------------------------------------------------- servidor
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(RAIZ / "portal"), **kw)

    def log_message(self, *a):
        pass

    # ---- utilidades
    def _corpo(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _corpo_bruto(self, destino, limite: int = 2_000_000_000) -> int:
        """Grava o corpo cru da requisicao em disco (envio de arquivo de video, sem multipart)."""
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ValueError("corpo vazio")
        if n > limite:
            raise ValueError(f"arquivo grande demais ({n} bytes); limite {limite}")
        destino.parent.mkdir(parents=True, exist_ok=True)
        restante = n
        with open(destino, "wb") as f:
            while restante > 0:
                bloco = self.rfile.read(min(1 << 20, restante))
                if not bloco:
                    break
                f.write(bloco); restante -= len(bloco)
        return n - restante

    def _pode_operar(self, u) -> bool:
        return bool(u) and u["papel"] in ("admin", "operador")

    # Niveis que a tela pode escolher POR CAMERA (pedido do dono, 16/11/2026): lista FECHADA. Qualquer
    # outro numero e' recusado com a lista na mensagem — alvo voltou a ser escolha, nao texto livre.
    ALVOS_DE_QUALIDADE = ("1500k", "1200k", "1000k", "800k", "500k", "300k")

    # RADAR por embarcacao (Fase 6, 17/11/2026): cada embarcacao pode ter o SEU radar — fonte, modo de
    # imagem e taxa ficam gravados nela, como o alvo por camera da 0.4.0. Listas FECHADAS, pelo mesmo
    # motivo: a tela escolhe entre opcoes medidas, nao digita numero.
    MODOS_DE_RADAR = ("ppi", "cru")
    TAXAS_DE_RADAR = ("30fps", "volta")

    def _radar_da_embarcacao(self, embarcacao_id: str) -> dict:
        """Config de radar gravada na embarcacao (vazia se nada gravado). Nunca devolve segredo."""
        vazio = {"embarcacao_id": embarcacao_id, "fonte": "", "modo": "", "taxa": "", "alvo": ""}
        if not embarcacao_id:
            return vazio
        try:
            with conexao() as c:
                r = c.execute("SELECT radar_fonte, radar_modo, radar_taxa, radar_alvo FROM embarcacoes"
                              " WHERE id=?", (embarcacao_id,)).fetchone()
        except Exception:
            return vazio
        if not r:
            return vazio
        return {"embarcacao_id": embarcacao_id, "fonte": r["radar_fonte"] or "",
                "modo": r["radar_modo"] or "", "taxa": r["radar_taxa"] or "", "alvo": r["radar_alvo"] or ""}

    def _validar_radar(self, d: dict) -> tuple:
        """Valida o pedido de radar por embarcacao. Devolve (erro, valores)."""
        embarcacao_id = str(d.get("embarcacao_id") or "").strip()
        fonte = str(d.get("fonte") or "").strip()
        modo = str(d.get("modo") or "").strip()
        taxa = str(d.get("taxa") or "").strip()
        alvo = str(d.get("alvo") or "").strip()
        if not embarcacao_id:
            return "informe a embarcacao (e' por embarcacao que a configuracao e' gravada)", None
        if not fonte:
            return "informe a fonte do radar: um arquivo de sinal (.drq) ou tcp://host:porta", None
        if fonte.lower().startswith("tcp://"):
            import radar_drq as _rd
            try:
                _rd.partir_fonte_tcp(fonte)
            except ValueError as e:
                return f"fonte de radar invalida: {e}", None
        elif not fonte.lower().endswith(".drq"):
            return "a fonte do radar por arquivo tem de ser um .drq (ou tcp://host:porta)", None
        if modo not in self.MODOS_DE_RADAR:
            return f"modo de imagem invalido: use {' ou '.join(self.MODOS_DE_RADAR)}", None
        if taxa not in self.TAXAS_DE_RADAR:
            return f"taxa invalida: use {' ou '.join(self.TAXAS_DE_RADAR)}", None
        if alvo and alvo not in self.ALVOS_DE_QUALIDADE:
            return "alvo fora da lista: " + ", ".join(self.ALVOS_DE_QUALIDADE), None
        return None, {"embarcacao_id": embarcacao_id, "fonte": fonte, "modo": modo, "taxa": taxa, "alvo": alvo}

    def _reabrir_para_aplicar(self, cam) -> dict:
        """Reabre o envio DAQUELA camera para o ajuste novo valer NO AR (nao so' na lista).

        Gravar o alvo nao mudava o video que estava no ar (o ffmpeg ja' tinha subido com o alvo antigo):
        a tela parecia que mudou, o kbps continuava o mesmo. Aqui a camera e' desligada e religada com o
        ajuste novo — so' ela, por ~2 s. Camera por endereco (RTSP) nao pode ser reaberta daqui (precisa
        da credencial pelo "Enviar video"): nesse caso dizemos em voz alta que vale no proximo envio.
        """
        if str(cam["ip"] or "").strip():
            return {"aplicado": False,
                    "motivo": "camera por endereco (RTSP): o alvo vale quando o Enviar video subir de novo"}
        if not ing_maquina_de_captura():
            return {"aplicado": False, "motivo": "esta maquina nao e' a de captura: o alvo vale no PC de bordo"}
        try:
            with conexao() as c:
                viva = c.execute("""SELECT id FROM ingestoes WHERE fluxo_id=? AND
                                    estado IN ('no_ar','no ar','iniciando') ORDER BY id DESC LIMIT 1""",
                                 (cam["fluxo_id"],)).fetchone()
        except Exception as e:
            return {"aplicado": False, "motivo": f"nao consegui ler o estado do envio ({type(e).__name__})"}
        if not viva:
            return {"aplicado": False, "motivo": "a camera nao estava no ar: o alvo vale quando ela subir"}
        try:
            ing_desligar_camera(cam["id"])
            r = ing_ligar_camera(cam["id"])
        except Exception as e:
            return {"aplicado": False, "motivo": f"{type(e).__name__}: {e}"}
        if isinstance(r, dict) and r.get("erro"):
            return {"aplicado": False, "motivo": str(r["erro"])}
        return {"aplicado": True, "envio": (r or {}).get("id"), "fluxo_id": cam["fluxo_id"]}

    def _enviar_arquivo(self, caminho: Path, baixar: bool = True) -> None:
        if not caminho.exists() or not caminho.is_file():
            return self._json(404, {"erro": "arquivo nao encontrado"})
        b = caminho.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(b)))
        if baixar:
            self.send_header("Content-Disposition", f'attachment; filename="{caminho.name}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _json(self, codigo: int, corpo, cabecalhos: dict | None = None) -> None:
        b = json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        # rotas de captura: a origem do lado terra do cliente (declarada) tambem le e age aqui
        juntos = self._cors(urlparse(self.path).path)
        juntos.update(cabecalhos or {})
        for k, v in juntos.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _sessao(self):
        token = None
        if "Cookie" in self.headers:
            ck = SimpleCookie(self.headers["Cookie"])
            token = ck["sessao"].value if "sessao" in ck else None
        return usuario_da_sessao(token)

    def _cors(self, rota: str) -> dict:
        """Cabecalhos de CORS SO' nas rotas de captura e SO' para as origens declaradas.

        E' o que deixa o Admin (pagina servida pelo lado terra) falar com o servidor LOCAL desta
        maquina para listar as cameras plugadas e repassar o fluxo — sem abrir a captura para
        qualquer origem: origem nao declarada fica sem cabecalho e o proprio navegador bloqueia.
        """
        if not eh_rota_de_captura_cors(rota):
            return {}
        origem = self.headers.get("Origin")
        if not origem or origem not in origens_captura():
            return {}
        return {"Access-Control-Allow-Origin": origem, "Vary": "Origin",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Credentials": "true"}

    def _local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _maquina_de_captura(self) -> bool:
        """A MAQUINA DE CAPTURA falando consigo mesma? (loopback + licenca/embarcacao desta maquina)

        A maquina de captura e' autonoma desde 23/11/2026 (dono: "no pc de captura ninguém precisa abrir
        nada ... o app de captura deve ser autônomo"): nao ha login nela, entao ela mesma pede a varredura
        (e so' a varredura) por loopback, sem sessao. O app DECLARA essa maquina (`LECSOR_CAPTURA_LOCAL=1`,
        ver `amb()` em `desktop/servidor.js`) E a licenca diz de que barco ela e' — sem as duas coisas,
        vale a regra de sempre (sessao de usuario do PC de captura). Fora do loopback nada muda: quem nao
        tem sessao continua de fora. Ver o uso em `POST /api/varredura`.
        """
        declarada = (os.environ.get("LECSOR_CAPTURA_LOCAL") or "").strip() == "1"
        return self._local() and declarada and bool(licenca_modulo.embarcacao())

    # ---- transmissao a pedido do cliente (17/11/2026)
    def _papel_cliente(self, u) -> bool:
        """Quem INICIA transmissao e' o cliente (dono, 17/11/2026: "apenas o cliente")."""
        return bool(u) and u["papel"] == "cliente"

    def _embarcacao_do_cliente(self, u, embarcacao_id: str) -> bool:
        """A embarcacao tem de ser VISIVEL para este usuario — mesma regra de `pode_ver_camera`.

        Uma regra so' (19/11/2026): quem tem vinculo em `usuario_embarcacoes` so' alcanca as
        concedidas; quem nao tem vinculo alcanca as da propria empresa.
        """
        return pode_ver_embarcacao(u, embarcacao_id)

    def _token_do_bordo(self) -> bool:
        """Autoriza o BORDO (agente de ordens): token de ingestao, nunca sessao de navegador."""
        esperado = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
        recebido = (self.headers.get("Authorization") or "").strip()
        if recebido.lower().startswith("bearer "):
            recebido = recebido[7:].strip()
        return bool(esperado) and hmac.compare_digest(recebido, esperado)

    def _tempo_do_cliente(self, usuario_id: str) -> int:
        """Tempo maximo que ESTE cliente configurou na tela de configuracao."""
        with conexao() as c:
            r = c.execute("SELECT tempo_maximo_s FROM configs_do_cliente WHERE usuario_id=?",
                          (usuario_id,)).fetchone()
        return int(r["tempo_maximo_s"]) if r else TEMPO_MAXIMO_PADRAO

    def _transmissao_aberta(self, usuario_email: str, camera_id: str):
        with conexao() as c:
            return c.execute("""SELECT * FROM transmissoes WHERE usuario_email=? AND camera_id=?
                                AND estado IN ('pedida','no_ar') ORDER BY criada_em DESC LIMIT 1""",
                             (usuario_email, camera_id)).fetchone()

    def _transmissao_da_tela(self, tid: str, u):
        """A sessao que a tela pode mexer: a propria, ou de qualquer um se for operacao/admin.

        Devolve `(linha, erro, codigo)`. `codigo` ZERO quer dizer liberado: quem chama TEM de
        interromper quando vem codigo — `_json` nao retorna nada, e o `if erro:` antigo seguia
        atendendo depois de responder 403 (um cliente encerrava a sessao de outro).
        """
        with conexao() as c:
            t = c.execute("SELECT * FROM transmissoes WHERE id=?", (tid,)).fetchone()
        if not t:
            return None, "transmissao nao encontrada", 404
        if u and (u["papel"] in PAPEL_ADMIN or u["email"] == t["usuario_email"]):
            return t, "", 0
        return None, "esta transmissao nao e' sua", 403

    def _json_transmissao(self, t) -> dict:
        """A linha da sessao como a tela ve: sem endereco de camera, sem credencial, sem porta."""
        d = dict(t)
        d["gravando"] = bool(d.get("gravando"))
        # a GRAVACAO mora no lado terra: o historico diz se existe arquivo e quanto ele tem
        try:
            g = gravacao_modulo.estado(d["id"])
            d["gravacao"] = {"tem": bool(g["arquivo"]), "bytes": g["bytes"], "segundos": g["segundos"],
                             "gravando": bool(g["gravando"])}
        except Exception:
            d["gravacao"] = {"tem": False, "bytes": 0, "segundos": 0, "gravando": False}
        d["segundos_restantes"] = 0
        if d.get("termina_em"):
            try:
                resta = (dt.datetime.fromisoformat(d["termina_em"])
                         - dt.datetime.now(dt.timezone.utc)).total_seconds()
                d["segundos_restantes"] = max(0, int(resta))
            except Exception:
                d["segundos_restantes"] = 0
        # a tela do cliente pergunta "quer continuar conectado?" quando faltam AVISO_SEGUNDOS
        d["aviso_segundos"] = AVISO_SEGUNDOS
        # quanto tempo fora da tela ao vivo ainda mantem a sessao de pe (a tela mostra "voce tem 60 s")
        d["janela_sem_tela"] = SEGUNDOS_SEM_BATIMENTO
        return d

    # ---- trecho de 1 minuto (prova da compressao)
    def _autoriza_fluxo(self, u, fluxo: str) -> tuple[bool, str]:
        """Quem pode baixar trecho DESTE fluxo: operacao/admin, o cliente dono da camera, ou a bancada.

        Mesma regra da lista de cameras: cliente so' alcanca camera da propria empresa. Aqui so' se
        decide sim/nao — nenhum endereco de camera, porta ou credencial entra na resposta.
        """
        if self._local():
            return True, ""
        if not u:
            return False, "entre no sistema"
        if u["papel"] in PAPEL_ADMIN:
            return True, ""
        with conexao() as c:
            cam = c.execute("SELECT * FROM cameras WHERE fluxo_id=? ORDER BY id LIMIT 1", (fluxo,)).fetchone()
        if cam and pode_ver_camera(u, cam):
            return True, ""
        return False, "esta camera nao e' do seu cliente"

    def _trecho_por_camera(self, cam_id: str, u, somente_estado: bool = False) -> None:
        """Mesma coisa, mas o app do cliente pede pela CAMERA (`/api/cameras/<id>/trecho`).

        O cliente nunca recebe o id do fluxo (`vivo-cam-01`): ele fala pela camera que ele ja' ve, e
        quem resolve camera -> fluxo e' o servidor. Assim o payload do cliente segue sem nome interno.
        """
        with conexao() as c:
            cam = c.execute("SELECT * FROM cameras WHERE id=? OR fluxo_id=? ORDER BY id LIMIT 1",
                            (cam_id, cam_id)).fetchone()
        if not cam:
            return self._json(404, {"erro": f"camera {cam_id} nao existe neste lado"})
        if not self._local():
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            if u["papel"] not in PAPEL_ADMIN and not pode_ver_camera(u, cam):
                return self._json(403, {"erro": "esta camera nao e' do seu cliente"})
        if somente_estado:
            return self._json(200, trecho_modulo.estado(cam["fluxo_id"]), {"Cache-Control": "no-store"})
        return self._trecho(cam["fluxo_id"], u)

    def _trecho(self, fluxo: str, u) -> None:
        """Grava N segundos do fluxo COMO CHEGOU e entrega o ARQUIVO — sem comparativo nenhum.

        Pedido do dono (16/11/2026): "nao vamos mais fazer o comparativo mbps quando baixar os videos
        de teste, vamos fazer um teste cego" — o download entrega o video e quem confere olha o
        TAMANHO do arquivo e compara a mao com o Mbps exibido no admin/captura. Por isso NAO vao no
        cabecalho kbps medido/declarado, compressao nem veredito `bate`: os `X-Lecsor-*` que ficam sao
        so' fatos do proprio arquivo (id, bytes, duracao, sha256), para o curl provar o tamanho antes
        de baixar o corpo.
        """
        ok, motivo = self._autoriza_fluxo(u, fluxo)
        if not ok:
            return self._json(401 if not u else 403, {"erro": motivo, "fluxo_id": fluxo})
        pedido = (parse_qs(urlparse(self.path).query).get("segundos") or [None])[0]
        # fora de 10..60 e' recusado em voz alta: pedir 1 hora e receber 60 s calado seria mentir
        if pedido not in (None, ""):
            try:
                n = int(float(pedido))
            except (TypeError, ValueError):
                return self._json(422, {"erro": f"segundos invalido ({pedido!r}): use "
                                               f"{trecho_modulo.SEGUNDOS_MIN} a {trecho_modulo.SEGUNDOS_MAX}"})
            if not (trecho_modulo.SEGUNDOS_MIN <= n <= trecho_modulo.SEGUNDOS_MAX):
                return self._json(422, {"erro": f"segundos fora do permitido ({n}): use "
                                               f"{trecho_modulo.SEGUNDOS_MIN} a {trecho_modulo.SEGUNDOS_MAX}"})
        segundos = trecho_modulo.limitar_segundos(pedido)
        r = trecho_modulo.gravar(fluxo, segundos=segundos, quem=(u["email"] if u else "bancada"))
        if r.get("erro"):
            return self._json(int(r.get("codigo") or 500), {"erro": r["erro"], "fluxo_id": fluxo},
                              {"Cache-Control": "no-store"})
        caminho = Path(r["arquivo"])
        if not caminho.exists():
            return self._json(500, {"erro": "o trecho foi gravado mas o arquivo sumiu (TTL ou limpeza)"})
        auditar(u, "baixar_trecho",
                f"{r['fluxo_id']} {r['segundos_pedidos']}s {r['mb']}MB {r['kbps_medidos']}kbps id={r['id']}",
                self.client_address[0])
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(r["bytes"]))
        self.send_header("Content-Disposition", f'attachment; filename="{r["nome"]}"')
        self.send_header("X-Lecsor-Trecho-Id", str(r["id"]))
        self.send_header("X-Lecsor-Bytes", str(r["bytes"]))
        self.send_header("X-Lecsor-Duracao-S", str(r["duracao_s"]))
        self.send_header("X-Lecsor-Sha256", r["sha256"])
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with caminho.open("rb") as fh:
            for bloco in iter(lambda: fh.read(1 << 20), b""):
                self.wfile.write(bloco)

    def _trechos(self, rota: str, u) -> None:
        """`/api/trechos` (lista do que ja' foi gravado) e `/api/trechos/<id>/atestado` (a prova)."""
        if rota.endswith("/atestado"):
            alvo = rota[len("/api/trechos/"):-len("/atestado")].strip("/")
            if not alvo.isdigit():
                return self._json(422, {"erro": "id do trecho invalido (use o numero)"})
            with conexao() as c:
                t = c.execute("SELECT fluxo_id FROM trechos WHERE id=?", (int(alvo),)).fetchone()
            if not t:
                return self._json(404, {"erro": f"trecho {alvo} nao existe"})
            # O ATESTADO E' o comparativo (medido no arquivo x declarado, compressao recalculada): nao
            # vai para o navegador do cliente — o dono pediu teste cego do Mbps no download. So
            # operacao/admin, SEM excecao de "chamada local": o app do cliente pode estar na MESMA
            # maquina do lado terra, e o comparativo nao e' dele (mesma regra do /api/declarado).
            if not self._pode_operar(u):
                return self._json(403, {"erro": "o comparativo do trecho e' da operacao — "
                                               "confira o tamanho do arquivo baixado"})
            return self._json(200, trecho_modulo.atestado(int(alvo)), {"Cache-Control": "no-store"})
        if not (self._pode_operar(u) or self._local()):
            return self._json(403, {"erro": "so operacao e administrador listam os trechos gravados"})
        fluxo = (parse_qs(urlparse(self.path).query).get("fluxo") or [None])[0]
        return self._json(200, {"trechos": trecho_modulo.listar(fluxo), "ttl_s": trecho_modulo.TTL_S,
                                "teto_por_janela": trecho_modulo.TETO_POR_JANELA,
                                "janela_s": trecho_modulo.JANELA_S},
                          {"Cache-Control": "no-store"})

    def _chave_analytics(self) -> bool:
        """A ingestao de analise exige a chave do agente (variavel de ambiente no servidor).
        Sem chave configurada, a porta fica fechada — nao existe caminho sem credencial."""
        esperada = os.environ.get("LECSOR_CHAVE_ANALYTICS", "")
        recebida = self.headers.get("X-Chave-Analytics", "")
        return bool(esperada) and secrets.compare_digest(esperada, recebida)

    def end_headers(self) -> None:
        if self.path.endswith((".html", ".css", ".js")) or urlparse(self.path).path in ("/", "/app", "/admin", "/entrada"):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        rota = urlparse(path).path
        if rota in ("/entrada", "/entrada/"):
            return str(RAIZ / "entrada" / "index.html")
        if rota.startswith("/entrada/"):
            return str(RAIZ / "entrada" / rota[len("/entrada/"):])
        if rota in ("/app", "/app/"):
            return str(RAIZ / "app" / "index.html")
        if rota.startswith("/app/"):
            return str(RAIZ / "app" / rota[len("/app/"):])
        if rota in ("/admin", "/admin/"):
            return str(RAIZ / "admin" / "index.html")
        if rota.startswith("/admin/"):
            return str(RAIZ / "admin" / rota[len("/admin/"):])
        if rota.startswith("/fronts/"):
            return str(RAIZ / "fronts" / rota[len("/fronts/"):])
        return super().translate_path(path)

    # ---- GET
    def handle_one_request(self) -> None:
        # navegador fechando a aba no meio de um HLS/WHEP aborta a conexao: nao e erro do servidor
        try:
            return super().handle_one_request()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True

    # ---- encaminhador para o lado terra (dono, 18/11/2026 — opcao A)
    # A tela do app passa a ser servida por ESTA maquina: mesma origem das rotas de captura, porque o
    # navegador nao deixa uma pagina vinda do lado terra (IP publico) falar com 127.0.0.1 (medido:
    # "Failed to fetch" no Chromium do app, com o servidor local respondendo 200 no curl). Tudo o que
    # NAO e' rota de captura (e nem a saude local) segue para o lado terra e volta como veio.
    def _base_do_lado_terra(self) -> str:
        """Endereco do lado terra: o app passa `LECSOR_LADO_TERRA_API` ao subir o servidor local.

        Se o endereco for DESTA maquina (o `ambiente.json` do pacote aponta para o proprio lado terra
        quando o papel e' lado terra), vale vazio: sem isso o servidor encaminhava as proprias telas
        para si mesmo e o `/admin/` respondia 502 (medido 18/11/2026). O `/api/saude` e o `/admin/`
        saem deste mesmo servidor em qualquer caso.
        """
        base = (os.environ.get("LECSOR_LADO_TERRA_API") or "").strip().rstrip("/")
        if not base:
            return ""
        try:
            from ferramentas import eh_esta_maquina
            if eh_esta_maquina(base):
                return ""
        except Exception:  # noqa: BLE001
            pass
        return base

    def _encaminhar(self, metodo: str) -> None:
        import http.client
        base = self._base_do_lado_terra()
        alvo = urlparse(base)
        if not alvo.hostname:
            return self._json(502, {"erro": "esta instalacao nao tem lado terra configurado"})
        corpo = None
        if metodo in ("POST", "PUT", "PATCH"):
            n = int(self.headers.get("Content-Length") or 0)
            corpo = self.rfile.read(n) if n else None
        # `X-LECSOR-Ponte` diz ao lado terra que quem fala e' o servidor local DESTA maquina de captura.
        # Sem compressao no pedido: o corpo da resposta e' repassado byte a byte.
        cab = {"Host": alvo.netloc, "X-LECSOR-Ponte": socket.gethostname(), "Accept-Encoding": "identity"}
        for k in ("Cookie", "Authorization", "Content-Type", "Accept", "Range", "User-Agent",
                  "If-None-Match", "If-Modified-Since"):
            v = self.headers.get(k)
            if v:
                cab[k] = v
        if corpo is not None:
            cab["Content-Length"] = str(len(corpo))
        cn = None
        try:
            cn = http.client.HTTPConnection(alvo.hostname, alvo.port or 80, timeout=120)
            cn.request(metodo, self.path, body=corpo, headers=cab)
            r = cn.getresponse()
            devolver = [(k, v) for k, v in r.getheaders()
                        if k.lower() not in ("transfer-encoding", "connection", "keep-alive")]
            juntos, corpo_json = None, b""
            if urlparse(self.path).path == "/api/eu" and r.status == 200:
                # `/api/eu` diz quem sou eu e se a captura e' DESTA maquina: o lado terra ve o IP do
                # PC de captura, nao o loopback — e e' isso que libera os botoes de camera. Aqui o
                # pedido veio pela ponte local, entao a captura e' daqui, por definicao.
                juntos = json.loads(r.read() or b"{}")
                juntos["local"] = True
                corpo_json = json.dumps(juntos, ensure_ascii=False).encode()
                devolver = [(k, v) for k, v in devolver if k.lower() != "content-length"]
                devolver.append(("Content-Length", str(len(corpo_json))))
            self.send_response_only(r.status)
            for k, v in devolver:
                self.send_header(k, v)
            self.end_headers()
            if juntos is not None:
                self.wfile.write(corpo_json)
            else:
                while True:                      # download de video/relatorio nao passa pela memoria
                    pedaco = r.read(65536)
                    if not pedaco:
                        break
                    self.wfile.write(pedaco)
        except Exception as e:
            try:
                self._json(502, {"erro": f"o lado terra nao respondeu ({type(e).__name__}: {e})"})
            except Exception:
                pass
        finally:
            if cn is not None:
                try:
                    cn.close()
                except Exception:
                    pass

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Pre-voo do navegador nas rotas de CAPTURA (e' assim que o Admin fala com esta maquina).

        Entrada/cadastro/licenca NAO entram aqui: sao da MESMA origem que as usa, entao pre-voo nelas
        e' 405 (nao existe origem de fora a autorizar). Ver `eh_rota_de_captura_cors`.
        """
        rota = urlparse(self.path).path
        if not eh_rota_de_captura_cors(rota):
            return self._json(405, {"erro": "metodo nao permitido"})
        cab = self._cors(rota)
        self.send_response(204)
        for k, v in cab.items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        rota = urlparse(self.path).path
        # A tela do app e' servida AQUI (mesma origem da captura). O que nao e' rota de captura nem a
        # saude local vai para o lado terra — inclusive as paginas, o css e as rotas de cadastro.
        if self._base_do_lado_terra() and rota != "/api/saude" and not eh_rota_de_captura(rota):
            return self._encaminhar("GET")
        u = self._sessao()
        if rota == "/favicon.ico":
            return self._json(204, {}, {"Cache-Control": "max-age=86400"})
        if rota == "/api/saude":
            # `anuncio` mostra, sem segredo, se o cadastro desta maquina consegue sair para o lado
            # terra (endereco + token + embarcacao) e o resultado da ultima tentativa por fluxo.
            try:
                import repasse as repasse_modulo
                anuncio = repasse_modulo.estado_do_anuncio()
            except Exception as e:  # noqa: BLE001
                anuncio = {"de_pe": False, "faltando": [f"modulo de repasse indisponivel ({type(e).__name__})"],
                           "tentativas": {}}
            # `supabase` diz, sem segredo, se esta instalacao consegue gravar o cadastro no banco
            # (o dono via a tabela `cameras` da nuvem parada e nada na tela explicava por que).
            try:
                import supabase_escrita
                banco_nuvem = supabase_escrita.diagnostico()
            except Exception as e:  # noqa: BLE001
                banco_nuvem = {"configurado": False, "motivo": f"{type(e).__name__}: {e}"}
            return self._json(200, {"ok": True, "banco": str(BANCO), "python": sys.version.split()[0],
                                    "anuncio": anuncio, "supabase": banco_nuvem},
                              {"Cache-Control": "no-store"})
        if rota == "/api/publicacao":
            # "por que minha camera nao apareceu no lado terra?": estado do anuncio + o resultado por
            # camera desta maquina, e o botao da tela republica tudo com esta rota (POST).
            import repasse as repasse_modulo
            with conexao() as c:
                cams = [dict(x) for x in c.execute("SELECT * FROM cameras ORDER BY id")]
            estado = repasse_modulo.estado_do_anuncio()
            tentativas = estado.get("tentativas") or {}
            itens = []
            for cam in cams:
                t = tentativas.get(cam["fluxo_id"]) or {}
                itens.append({"id": cam["id"], "fluxo_id": cam["fluxo_id"], "rotulo": cam["rotulo"],
                              "ativo": cam["ativo"], "publicado": bool(t.get("ok")),
                              "motivo": t.get("motivo") or "", "em": t.get("em") or ""})
            if self.command == "POST":
                return self._json(405, {"erro": "use POST em /api/publicacao para republicar"})
            return self._json(200, {"anuncio": estado, "cameras": itens}, {"Cache-Control": "no-store"})
        if rota == "/api/primeiro-acesso":
            # Instalacao nova nasce SEM nenhum usuario: sem esta rota ninguem consegue entrar no PC
            # de captura (foi o "abriu direto, sem login e senha" do cliente).
            with conexao() as c:
                quantos = c.execute("SELECT count(*) FROM usuarios WHERE ativo=1").fetchone()[0]
            try:
                import supabase_auth
                tem_supabase = supabase_auth.configurado()
            except Exception:
                tem_supabase = False
            return self._json(200, {"precisa": quantos == 0, "local": self._local(),
                                    "supabase": tem_supabase, "usuarios": quantos,
                                    "maquina": socket.gethostname()}, {"Cache-Control": "no-store"})
        if rota == "/api/eu":
            if not u:
                return self._json(200, {"autenticado": False, "local": self._local()})
            # "local" diz se quem fala com a API e' da propria maquina de captura: e' isso que
            # libera os botoes de ligar/desligar a CAMERA na tela (a captura so existe onde a
            # camera esta plugada). Cliente remoto nunca recebe esses botoes.
            return self._json(200, {"autenticado": True, "email": u["email"], "nome": u["nome"],
                                    "papel": u["papel"], "local": self._local()})
        if rota == "/api/fluxos":
            return self._json(200, fluxos())
        if rota == "/api/embarcacoes/radar":
            # RADAR por embarcacao (Fase 6): a tela de captura LE o que ficou gravado nesta embarcacao
            # (fonte, modo de imagem, taxa, alvo) e o que pode escolher. Quem captura precisa ler;
            # gravar e' da operacao/administrador.
            if not (self._pode_operar(u) or self._local()
                    or (u and u["papel"] == "tecnico")):
                return self._json(403, {"erro": "so a operacao, o administrador e o tecnico do bordo veem o radar"})
            q = parse_qs(urlparse(self.path).query)
            embarcacao_id = (q.get("embarcacao_id") or [""])[0].strip()
            embarcacoes = []
            try:
                with conexao() as c:
                    embarcacoes = [{"id": r["id"], "nome": r["nome"]} for r in
                                   c.execute("SELECT id, nome FROM embarcacoes ORDER BY nome")]
            except Exception:
                pass
            if not embarcacao_id and embarcacoes:
                embarcacao_id = embarcacoes[0]["id"]
            return self._json(200, {"radar": self._radar_da_embarcacao(embarcacao_id),
                                    "embarcacoes": embarcacoes,
                                    "modos": list(self.MODOS_DE_RADAR), "taxas": list(self.TAXAS_DE_RADAR),
                                    "alvos": list(self.ALVOS_DE_QUALIDADE)},
                              {"Cache-Control": "no-store"})
        # ---- trecho de 1 minuto: a prova de que a compressao informada e' real (dono, 15/11/2026)
        # O cliente baixa 60 s do video COMO ELE CHEGA aqui (`-c copy`, sem reencodar) e o atestado
        # poe o medido ao lado do declarado pelo PC de captura. Nada de endereco de camera no corpo.
        if rota.startswith("/api/fluxos/") and rota.endswith("/trecho/estado"):
            fluxo = unquote(rota[len("/api/fluxos/"):-len("/trecho/estado")]).strip("/")
            ok, motivo = self._autoriza_fluxo(u, fluxo)
            if not ok:
                return self._json(401 if not u else 403, {"erro": motivo, "fluxo_id": fluxo})
            return self._json(200, trecho_modulo.estado(fluxo), {"Cache-Control": "no-store"})
        if rota.startswith("/api/fluxos/") and rota.endswith("/trecho"):
            fluxo = unquote(rota[len("/api/fluxos/"):-len("/trecho")]).strip("/")
            return self._trecho(fluxo, u)
        if rota.startswith("/api/cameras/") and rota.endswith("/trecho/estado"):
            cam = unquote(rota[len("/api/cameras/"):-len("/trecho/estado")]).strip("/")
            return self._trecho_por_camera(cam, u, somente_estado=True)
        if rota.startswith("/api/cameras/") and rota.endswith("/trecho"):
            cam = unquote(rota[len("/api/cameras/"):-len("/trecho")]).strip("/")
            return self._trecho_por_camera(cam, u)
        if rota.startswith("/api/trechos"):
            return self._trechos(rota, u)
        if rota in ("/api/envio/destino", "/api/envios/destino"):
            # Para onde vao os fluxos DESTA maquina (PC de captura -> lado terra). So operacao ve:
            # e' endereco de servico interno e o navegador do cliente nunca recebe esse dado.
            # sem a excecao de "chamada local": um CLIENTE logado nesta mesma maquina tambem nao
            # pode receber endereco de servico interno (regra fixada pelo dono)
            if not self._pode_operar(u):
                return self._json(403, {"erro": "so operacao e administrador veem o destino do repasse"})
            destino = (os.environ.get("LECSOR_DESTINO_SRT") or "").strip()
            return self._json(200, {"destino": destino, "repassa": bool(destino)},
                              {"Cache-Control": "no-store"})
        if rota in ("/api/ingestoes", "/api/envios"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador enviam video de teste"})
            return self._json(200, {"ingestoes": ing_listar(), "atualizado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds")},
                              {"Cache-Control": "no-store"})
        if rota in ("/api/declarado", "/api/envios/declarado"):
            # O QUADRO do que o PC de captura declara: ultima declaracao de cada fluxo (com hora e
            # idade), ultima medicao de qualidade e a ULTIMA TENTATIVA de anuncio — aceita ou recusada.
            # E' o que responde "o barco esta' falando com terra?" sem precisar de ssh na maquina.
            # SO' operacao/admin, sem a excecao de "chamada local": o corpo traz o IP de quem
            # declarou, e um CLIENTE logado nesta mesma maquina nao pode receber endereco interno
            # (regra fixada pelo dono). O cliente ve o comparativo no comprovante do trecho.
            if not self._pode_operar(u):
                return self._json(403, {"erro": "so operacao e administrador veem o que o bordo declarou"})
            agora_dt = dt.datetime.now().astimezone()

            def _idade_de(quando):
                try:
                    return round((agora_dt - dt.datetime.fromisoformat(str(quando))).total_seconds(), 1)
                except Exception:
                    return None

            def ultima_tentativa(c, fluxo):
                try:
                    r = c.execute("""SELECT em, rota, aceito, motivo, ip FROM anuncios_recebidos
                                     WHERE fluxo_id=? ORDER BY id DESC LIMIT 1""", (fluxo,)).fetchone()
                except sqlite3.Error:
                    return None
                return dict(r) if r else None

            def qual(c, fluxo):
                try:
                    r = c.execute("""SELECT ssim, ajuste, medido_em, compressao_pct, mb_alvo, mb_original
                                     FROM medicoes_qualidade WHERE fluxo_id=? ORDER BY id DESC LIMIT 1""",
                                  (fluxo,)).fetchone()
                except sqlite3.Error:
                    return None
                return dict(r) if r else None

            declarado, sem_declaracao = [], []
            with conexao() as c:
                try:
                    linhas = [dict(r) for r in c.execute("""SELECT fluxo_id, rotulo, estado, tipo, codec,
                                resolucao, fps, bitrate_alvo, bitrate_entrada_kbps, bitrate_saida_kbps,
                                corte_pct, duracao_s, declarado_em, recebido_em, declarado_por
                            FROM ingestoes WHERE declarado_em IS NOT NULL
                            ORDER BY declarado_em DESC LIMIT 50""")]
                except sqlite3.Error:
                    linhas = []
                for l in linhas:
                    q = qual(c, l["fluxo_id"]) or {}
                    l["idade_s"] = _idade_de(l.get("declarado_em"))
                    l["recebido_ha_s"] = _idade_de(l.get("recebido_em"))
                    l["qualidade"] = ({**q, "idade_s": _idade_de(q.get("medido_em"))} if q else None)
                    l["ultima_tentativa"] = ultima_tentativa(c, l["fluxo_id"])
                    declarado.append(l)
                vistos = {l["fluxo_id"] for l in declarado}
                try:
                    fluxos_tentados = [dict(r) for r in c.execute("""SELECT DISTINCT fluxo_id
                                            FROM anuncios_recebidos WHERE fluxo_id IS NOT NULL AND fluxo_id<>''
                                            ORDER BY id DESC LIMIT 50""")]
                except sqlite3.Error:
                    fluxos_tentados = []
                for f in fluxos_tentados:
                    if f["fluxo_id"] in vistos:
                        continue
                    t = ultima_tentativa(c, f["fluxo_id"])
                    sem_declaracao.append({"fluxo_id": f["fluxo_id"], "ultima_tentativa": t,
                                           "qualidade": (qual(c, f["fluxo_id"]) or None)})
            return self._json(200, {"declarado": declarado, "sem_declaracao": sem_declaracao,
                                    "agora": agora_dt.isoformat(timespec="seconds"),
                                    "explica": ("'declarado' e' o que o PC de captura informou do envio; "
                                                "'sem_declaracao' lista quem tentou anunciar e nao tem "
                                                "declaracao gravada (com o motivo da recusa, quando houve)")},
                              {"Cache-Control": "no-store"})
        if rota in ("/api/compressoes", "/api/compressoes/lista"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem as compressoes"})
            return self._json(200, {"compressoes": etapas_pipeline.listar_compressoes()},
                              {"Cache-Control": "no-store"})
        if rota in ("/api/comprimidos", "/api/envios/comprimidos"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem os arquivos"})
            COMPRIMIDOS.mkdir(parents=True, exist_ok=True)
            itens = []
            for f in sorted(COMPRIMIDOS.glob("*.mp4"), key=lambda x: -x.stat().st_mtime)[:60]:
                itens.append({"nome": f.name, "bytes": f.stat().st_size, "mb": round(f.stat().st_size / 1e6, 2),
                              "modificado": dt.datetime.fromtimestamp(f.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                              "baixar": f"/api/comprimido/{f.name}"})
            return self._json(200, {"comprimidos": itens}, {"Cache-Control": "no-store"})
        if rota.startswith("/api/comprimido/"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador baixam o arquivo"})
            nome = Path(unquote(rota.split("/api/comprimido/", 1)[1])).name
            return self._enviar_arquivo(COMPRIMIDOS / nome)
        if rota.startswith("/api/etapas/"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador medem as etapas"})
            fluxo = Path(unquote(rota.split("/api/etapas/", 1)[1])).name
            import urllib.parse as _up
            q = parse_qs(urlparse(self.path).query)
            rel = {"envio": etapas_pipeline.envio(fluxo)}
            if (q.get("descompressao") or ["0"])[0] in ("1", "sim", "true"):
                rel["descompressao"] = etapas_pipeline.descompressao(fluxo)
            return self._json(200, rel, {"Cache-Control": "no-store"})
        if rota == "/api/resumo":
            if not (u or self._local()):
                return self._json(401, {"erro": "entre no sistema"})
            return self._json(200, ler_tudo())
        if rota in ("/api/fases", "/api/medicoes", "/api/inventario", "/api/evidencias", "/api/documentos",
                    "/api/decisoes", "/api/auditoria"):
            if not (u or self._local()):
                return self._json(401, {"erro": "entre no sistema"})
            return self._json(200, {rota.split("/")[-1]: ler_tudo()[rota.split("/")[-1]]})
        if rota == "/api/embarcacoes":
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            with conexao() as c:
                if u["papel"] in PAPEIS_VE_TUDO:
                    linhas = c.execute("SELECT * FROM embarcacoes ORDER BY nome").fetchall()
                else:
                    # escopo do cliente (19/11/2026): vinculo explicito = so' as concedidas; sem
                    # vinculo = todas as da propria empresa (o que ja' existia).
                    concedidas = [r["embarcacao_id"] for r in c.execute(
                        "SELECT embarcacao_id FROM usuario_embarcacoes WHERE usuario_id=?", (u["id"],)).fetchall()]
                    if concedidas:
                        marcas = ",".join("?" * len(concedidas))
                        linhas = c.execute(f"SELECT * FROM embarcacoes WHERE id IN ({marcas}) ORDER BY nome",
                                           concedidas).fetchall()
                    else:
                        linhas = c.execute("SELECT * FROM embarcacoes WHERE cliente_id=? ORDER BY nome",
                                           (u["cliente_id"],)).fetchall()
            return self._json(200, {"embarcacoes": [dict(x) for x in linhas]})
        if rota == "/licenca":
            return self._pagina_da_licenca()
        if rota == "/api/licenca":
            return self._estado_da_licenca()
        if rota == "/bordo":
            return self._pagina_do_bordo()
        if rota == "/api/bordo/serie":
            # A SERIE da saude — o que o dashboard de verdade desenha (dono, 24/11/2026: "preciso de um
            # dashboard real no pc de captura ... so' tem um monte de cards"). Duas origens, na ordem:
            #  1) o ANEL LOCAL desta maquina (`saude/historico-da-saude.jsonl`), que e' o do proprio PC
            #     de captura — quem mede e' ele;
            #  2) `?embarcacao=<id>`: a serie que o lado terra guardou (para o `/bordo` aberto NO TERRA),
            #     lida do banco. Sem nenhuma das duas, devolve `pontos: []` — a tela diz "sem serie",
            #     nunca inventa curva.
            q = parse_qs(urlparse(self.path).query)
            try:
                limite = max(2, min(2880, int((q.get("pontos", ["720"])[0] or "720"))))
            except Exception:  # noqa: BLE001
                limite = 720
            pontos, origem = [], ""
            try:
                import saude_do_bordo
                pontos = saude_do_bordo.historico(limite)
                origem = "anel local" if pontos else ""
            except Exception as e:  # noqa: BLE001
                pontos, origem = [], f"anel local indisponivel ({type(e).__name__})"
            emb = (q.get("embarcacao", [""])[0] or "").strip()
            if not pontos and emb:
                try:
                    with conexao() as c:
                        linhas = c.execute(
                            """SELECT recebido_em,retrato FROM saude_bordo WHERE embarcacao_id=?
                               ORDER BY recebido_em DESC LIMIT ?""", (emb, limite)).fetchall()
                    import saude_do_bordo
                    for linha in reversed(linhas):
                        try:
                            r = json.loads(linha["retrato"] or "{}")
                        except Exception:  # noqa: BLE001
                            continue
                        p = saude_do_bordo.ponto_do_retrato(r)
                        p["t"] = p.get("t") or linha["recebido_em"]
                        pontos.append(p)
                    if pontos:
                        origem = "serie do lado terra"
                except Exception as e:  # noqa: BLE001
                    origem = f"serie do lado terra indisponivel ({type(e).__name__})"
            return self._json(200, {"ok": True, "pontos": pontos, "limite": limite,
                                    "origem": origem, "embarcacao_id": emb},
                              {"Cache-Control": "no-store"})
        if rota == "/api/bordo":
            return self._estado_do_bordo()
        if rota == "/api/licencas":
            # PAINEL DO ADMIN (dono, 19/11/2026): gerar, ver/copiar a chave inteira, ver o uso e
            # revogar. Cliente e observador nao entram aqui.
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(403, {"erro": "esta lista e' do admin"})
            return self._json(200, {"licencas": self._licencas_do_painel()},
                              {"Cache-Control": "no-store"})
        if rota == "/api/transmissao/pedidos":
            # A OPERACAO ve os pedidos ABERTOS de todas as embarcacoes e cancela o que quiser (plano,
            # Fase 2 P1: "a operacao ve e pode cancelar o pedido"). O cliente nunca ve esta lista.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            if u["papel"] not in PAPEL_ADMIN:
                return self._json(403, {"erro": "esta lista e' da operacao"})
            with conexao() as c:
                abertas = [self._json_transmissao(dict(x)) for x in c.execute(
                    """SELECT * FROM transmissoes WHERE estado IN ('pedida','no_ar')
                       ORDER BY criada_em""").fetchall()]
                nomes_emb = {r["id"]: r["nome"] for r in c.execute("SELECT id,nome FROM embarcacoes")}
                nomes_cam = {r["id"]: r["rotulo"] for r in c.execute("SELECT id,rotulo FROM cameras")}
            for a in abertas:
                a["embarcacao_nome"] = nomes_emb.get(a["embarcacao_id"], a["embarcacao_id"])
                a["camera_rotulo"] = nomes_cam.get(a["camera_id"], a["camera_id"])
            return self._json(200, {"agora": em_iso(), "tempos": list(TEMPOS_DE_TRANSMISSAO),
                                    "teto_do_produto_s": tempo_maximo_do_produto(),
                                    "prazo_para_baixar_min": int(minutos_para_baixar()),
                                    "pedidos": abertas,
                                    "gravacoes": gravacoes_recentes()}, {"Cache-Control": "no-store"})
        if rota == "/api/transmissao":
            # A TELA DO CLIENTE: o que esta' no ar, o historico e o tempo configurado. O cliente so'
            # alcanca embarcacao da propria empresa; operacao/admin acompanham qualquer uma.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            emb = (parse_qs(urlparse(self.path).query).get("embarcacao", [""])[0] or "").strip()
            if not emb:
                return self._json(422, {"erro": "informe a embarcacao"})
            if u["papel"] not in PAPEL_ADMIN and not self._embarcacao_do_cliente(u, emb):
                return self._json(403, {"erro": "esta embarcacao nao e' da sua empresa"})
            # avisou o cliente? registra UMA vez por gravacao (gravacao_avisada na auditoria)
            if u["papel"] == "cliente":
                try:
                    marcar_gravacoes_avisadas(u["email"], self.client_address[0])
                except Exception:
                    pass
            with conexao() as c:
                # as abertas passam pelo mesmo enfeite do historico: a tela precisa do estado da
                # gravacao (e do tempo restante) tambem nas transmissoes que estao' no ar
                abertas = [self._json_transmissao(dict(x)) for x in c.execute(
                    """SELECT * FROM transmissoes WHERE embarcacao_id=? AND estado IN ('pedida','no_ar')
                       ORDER BY criada_em""", (emb,)).fetchall()]
                hist = [dict(x) for x in c.execute(
                    """SELECT * FROM transmissoes WHERE embarcacao_id=?
                       ORDER BY criada_em DESC LIMIT 100""", (emb,)).fetchall()]
            teto = tempo_maximo_do_produto()
            oferecidos = [t for t in TEMPOS_DE_TRANSMISSAO if not teto or t <= teto] or [TEMPO_MAXIMO_PADRAO]
            meu_tempo = self._tempo_do_cliente(u["id"])
            if teto and meu_tempo > teto:
                meu_tempo = teto          # o teto do produto manda
            return self._json(200, {"agora": em_iso(), "embarcacao_id": emb,
                                    "tempos": oferecidos,
                                    "tempo_maximo_s": meu_tempo,
                                    "teto_do_produto_s": teto,
                                    "aviso_segundos": AVISO_SEGUNDOS,
                                    "janela_sem_tela": SEGUNDOS_SEM_BATIMENTO,
                                    "papel": u["papel"],
                                    # o CLIENTE recebe o AVISO (o que ele pode baixar, so' o dele); a
                                    # operacao recebe a TRILHA (o que foi gravado na embarcacao, com o
                                    # tamanho e quando cada arquivo saiu) — nunca o arquivo alheio.
                                    ("gravacoes_prontas" if u["papel"] == "cliente" else "gravacoes"):
                                        (gravacoes_prontas_do_cliente(u["email"], emb)
                                         if u["papel"] == "cliente" else gravacoes_da_embarcacao(emb)),
                                    "abertas": abertas,
                                    "historico": [self._json_transmissao(t) for t in hist]},
                              {"Cache-Control": "no-store"})
        if rota.startswith("/api/gravacoes/"):
            # Baixar a gravacao (GET — fica no do_GET): so' quem ve a sessao (o dono dela ou a operacao).
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            tid = rota[len("/api/gravacoes/"):].strip("/")
            t, erro, codigo = self._transmissao_da_tela(tid, u)
            if codigo:
                return self._json(codigo, {"erro": erro})
            caminho = gravacao_modulo.arquivo(tid)
            if not caminho.exists():
                return self._json(404, {"erro": "esta transmissao nao tem gravacao"})
            auditar(u, "gravacao_baixada", f"{t['camera_id']}", self.client_address[0])
            # o arquivo NAO pode ser apagado no meio do download (o cliente pode sair da tela no meio
            # dele): fica marcado enquanto o download rola, e o apagamento espera terminar.
            gravacao_modulo.abrir_para_baixar(tid)
            try:
                with conexao() as c:
                    c.execute("""UPDATE gravacoes SET baixada_em=? WHERE transmissao_id=?
                                 AND baixada_em=''""", (em_iso(), tid))
                return self._enviar_arquivo(caminho, baixar=True)
            finally:
                gravacao_modulo.fechar_para_baixar(tid)
        if rota == "/api/ordens":
            # O AGENTE DO BORDO pergunta o que fazer e obedece direto (nao ha tecnico confirmando).
            # Autorizado pelo token de ingestao. Segura a resposta ate' `espera` segundos quando nao
            # ha' nada — e' assim que a ordem do cliente chega ao bordo sem o bordo abrir porta.
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            q = parse_qs(urlparse(self.path).query)
            emb = (q.get("embarcacao_id", [""])[0] or os.environ.get("LECSOR_EMBARCACAO_BORDO") or "").strip()
            if not emb:
                return self._json(422, {"erro": "informe a embarcacao"})
            try:
                espera = float(q.get("espera", ["20"])[0] or 20)
            except Exception:
                espera = 20.0
            fim = time.time() + min(30.0, max(0.0, espera))
            linhas = []
            while True:
                with conexao() as c:
                    linhas = [dict(x) for x in c.execute(
                        """SELECT * FROM ordens_do_bordo WHERE embarcacao_id=? AND estado='pedido'
                           ORDER BY seq""", (emb,)).fetchall()]
                    if linhas:
                        c.executemany("UPDATE ordens_do_bordo SET estado='entregue', entregue_em=? WHERE id=?",
                                      [(em_iso(), l["id"]) for l in linhas])
                if linhas or time.time() >= fim:
                    break
                time.sleep(0.4)
            return self._json(200, {"embarcacao_id": emb, "recebidas": len(linhas),
                                    "seq": max([l["seq"] for l in linhas], default=0),
                                    "ordens": [{"id": l["id"], "seq": l["seq"], "camera_id": l["camera_id"],
                                                "fluxo_id": l["fluxo_id"], "acao": l["acao"],
                                                "transmissao_id": l["transmissao_id"],
                                                "motivo": l["motivo"]} for l in linhas]},
                              {"Cache-Control": "no-store"})
        if rota == "/api/estado-desejado":
            if os.environ.get("LECSOR_SEM_FLAG") == "1":
                # lado terra ANTIGO: nao existe a flag (o agente do bordo cai na fila de ordens)
                return self._json(404, {"erro": "esta versao do lado terra nao tem a flag de estado"})
            # A FLAG (dono, 19/11/2026): o bordo NAO recebe conexao nenhuma — ele OLHA para terra e,
            # quando a flag muda, inicia ou para a transmissao. Responde na hora (o bordo compara com o
            # que ele tem no ar e so' age na diferenca); quem sustenta o "ligar" e' a sessao do cliente.
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            q = parse_qs(urlparse(self.path).query)
            emb = (q.get("embarcacao_id", [""])[0] or os.environ.get("LECSOR_EMBARCACAO_BORDO") or "").strip()
            if not emb:
                return self._json(422, {"erro": "informe a embarcacao"})
            try:
                cams = _desejo_das_cameras(emb)
                pedidos = pedidos_de_hd(emb)
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"erro": f"nao consegui calcular o desejo ({type(e).__name__}: {e})"})
            return self._json(200, {"embarcacao_id": emb, "agora": em_iso(), "cameras": cams,
                                    "pedidos": pedidos}, {"Cache-Control": "no-store"})
        if rota == "/api/config-desejada":
            # A CONFIGURACAO que terra publicou (0.8.0): o bordo olha aqui, aplica SO' a diferenca e
            # confirma em /api/config-aplicada. Mesmo desenho da flag — o bordo nao recebe conexao.
            if os.environ.get("LECSOR_SEM_CONFIG") == "1":
                return self._json(404, {"erro": "esta versao do lado terra nao publica configuracao"})
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            q = parse_qs(urlparse(self.path).query)
            emb = (q.get("embarcacao_id", [""])[0] or os.environ.get("LECSOR_EMBARCACAO_BORDO") or "").strip()
            if not emb:
                return self._json(422, {"erro": "informe a embarcacao"})
            try:
                return self._json(200, dict(config_publicada(emb), agora=em_iso()),
                                  {"Cache-Control": "no-store"})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"erro": f"nao consegui ler a configuracao ({type(e).__name__}: {e})"})
        if rota == "/api/saude-do-bordo":
            # A LEITURA da saude do bordo (o bordo so' ESCREVE, no ramo de escrita). Quem ve' e' a operacao;
            # `_local()` NAO entra: aqui nao ha' bordo pedindo, e' dado de operacao.
            # Duas portas, de proposito: a operacao (admin) ve' pelo painel; e o PROPRIO computador de
            # captura le' a sua saude pela rota local (o app a bordo se mostra). Cliente nao entra por
            # nenhuma delas.
            if u is None and not self._local():
                return self._json(401, {"erro": "entre para ver a saude do bordo"})
            if u is not None and not self._pode_operar(u):
                return self._json(403, {"erro": "so a operacao e o administrador veem a saude do bordo"})
            q = parse_qs(urlparse(self.path).query)
            emb = (q.get("embarcacao_id", [""])[0] or "").strip()
            if emb:
                return self._json(200, saude_de(emb), {"Cache-Control": "no-store"})
            with conexao() as c:
                embs = [dict(x) for x in c.execute("SELECT id,nome FROM embarcacoes ORDER BY nome").fetchall()]
            return self._json(200, {"embarcacoes": [
                dict(saude_de(e["id"], pontos=1), nome=e["nome"]) for e in embs]},
                {"Cache-Control": "no-store"})
        if rota == "/api/config":
            # A tela do admin publica e ve a configuracao (desejada x aplicada) por embarcacao.
            q = parse_qs(urlparse(self.path).query)
            emb = (q.get("embarcacao_id", [""])[0] or "").strip()
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem a configuracao"})
            if not emb:
                return self._json(422, {"erro": "informe a embarcacao"})
            return self._json(200, config_publicada(emb), {"Cache-Control": "no-store"})
        if rota == "/api/hd/catalogo":
            # O catalogo do HD do radar: o bordo publica o que existe; a tela pesquisa por data e hora.
            cam_id = (parse_qs(urlparse(self.path).query).get("camera_id", [""])[0] or "").strip()
            if cam_id:
                with conexao() as c:
                    cam = c.execute("SELECT * FROM cameras WHERE id=?", (cam_id,)).fetchone()
                if not pode_ver_camera(u, cam):
                    return self._json(403, {"erro": "esta camera nao e' da sua empresa"})
                if not u and not self._local():
                    return self._json(401, {"erro": "entre no sistema"})
                return self._json(200, catalogo_do_hd(cam["embarcacao_id"], cam_id),
                                  {"Cache-Control": "no-store"})
            if u and u["papel"] == PAPEL_OBSERVADOR:
                # Tipo 4 (Petrobras — plano de 19/11/2026, Fase 4): o HD do radar de TODAS as
                # embarcacoes de TODAS as empresas, com o nome de cada uma (a tela lista embarcacao a
                # embarcacao). E' o unico conteudo que este papel enxerga.
                with conexao() as c:
                    embs = [dict(x) for x in c.execute(
                        "SELECT id,nome FROM embarcacoes ORDER BY nome").fetchall()]
                junto = {"embarcacao_id": "", "embarcacoes": embs, "catalogos": [], "pedidos": []}
                for e in embs:
                    r = catalogo_do_hd(e["id"])
                    for cat in r["catalogos"]:
                        cat["embarcacao_nome"] = e["nome"]
                    junto["catalogos"] += r["catalogos"]
                    junto["pedidos"] += r["pedidos"]
                return self._json(200, junto, {"Cache-Control": "no-store"})
            if u and u["papel"] == "cliente":
                # O CLIENTE acessa as imagens da embarcacao dele (dono, 19/11/2026).
                with conexao() as c:
                    embs = [x["id"] for x in c.execute(
                        "SELECT id FROM embarcacoes WHERE cliente_id=?", (u["cliente_id"],)).fetchall()]
                junto = {"embarcacao_id": u["cliente_id"], "catalogos": [], "pedidos": []}
                for e in embs:
                    r = catalogo_do_hd(e)
                    junto["catalogos"] += r["catalogos"]
                    junto["pedidos"] += r["pedidos"]
                return self._json(200, junto, {"Cache-Control": "no-store"})
            if not (self._pode_operar(u) or self._local()):
                return self._json(401, {"erro": "entre no sistema"})
            emb2 = (parse_qs(urlparse(self.path).query).get("embarcacao_id", [""])[0] or "").strip()
            if not emb2:
                return self._json(422, {"erro": "informe a camera ou a embarcacao"})
            return self._json(200, catalogo_do_hd(emb2), {"Cache-Control": "no-store"})
        if rota == "/api/hd/baixar":
            # O cliente baixa o trecho que ELE pediu (ou a operacao/admin). O arquivo veio do bordo.
            qq = parse_qs(urlparse(self.path).query)
            pid = (qq.get("id", [""])[0] or "").strip()
            if not u or not pid:
                return self._json(401, {"erro": "entre no sistema e informe o trecho"})
            with conexao() as c:
                p = c.execute("SELECT * FROM hd_pedidos WHERE id=?", (pid,)).fetchone()
            if not p or p["estado"] != "enviado" or not p["trecho"]:
                return self._json(404, {"erro": "trecho nao esta' pronto em terra"})
            dono = (p["usuario_email"] or "") == (u["email"] or "") or u["papel"] in PAPEL_ADMIN \
                or u["papel"] in ("operador", "tecnico")
            if not dono:
                return self._json(403, {"erro": "este trecho nao e' seu"})
            return self._enviar_arquivo(hd_dir() / p["trecho"], baixar=True)
        if rota in ("/api/metricas", "/api/tempo-real", "/api/metricas/tempo-real"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem as metricas"})
            # 2 s de cache: metricas + link + ping somam segundos e a tela se atualiza a cada 2 s
            import time as _t
            g = _CACHE_METRICAS.get("d")
            if g and _t.time() - g[0] < 2.0:
                return self._json(200, g[1], {"Cache-Control": "no-store"})
            corpo = etapas_pipeline.metricas_ao_vivo()
            corpo["link"] = producao_pipeline.link_srt()
            corpo["latencia_internet"] = producao_pipeline.latencia_internet()
            _CACHE_METRICAS["d"] = (_t.time(), corpo)
            return self._json(200, corpo, {"Cache-Control": "no-store"})
        if rota in ("/api/tempo-real-completo", "/api/link"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem o link"})
            return self._json(200, {"link": producao_pipeline.link_srt(),
                                    "latencia_internet": producao_pipeline.latencia_internet(),
                                    "em": producao_pipeline.agora()}, {"Cache-Control": "no-store"})
        if rota.startswith("/api/qualidade"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem a qualidade"})
            q = parse_qs(urlparse(self.path).query)
            fluxo = (q.get("fluxo") or [""])[0].strip()
            import qualidade as _qualidade
            if fluxo:
                return self._json(200, {"qualidade": _qualidade.ultima(fluxo), "fluxo": fluxo},
                                  {"Cache-Control": "no-store"})
            # A MEDICAO de qualidade por camera. O numero e' medido no PC de captura (unica maquina
            # que tem a fonte crua para comparar) e chega aqui pelo anuncio autenticado: aqui vai o
            # ULTIMO SSIM de cada fluxo com a IDADE (qualidade sem "medida quando" nao vale) e o
            # proximo alvo a tentar quando o numero fica abaixo do piso.
            with conexao() as c:
                c.execute("""CREATE TABLE IF NOT EXISTS medicoes_qualidade (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                fluxo_id TEXT NOT NULL, ssim REAL, ajuste TEXT, res_coluna TEXT,
                                resolucao TEXT, fps REAL, segundos REAL, mb_alvo REAL, mb_original REAL,
                                compressao_pct REAL, fonte TEXT, medido_em TEXT NOT NULL)""")
                linhas = [dict(x) for x in c.execute(
                    """SELECT m.* FROM medicoes_qualidade m
                       JOIN (SELECT fluxo_id, MAX(id) AS ultimo FROM medicoes_qualidade GROUP BY fluxo_id) u
                         ON u.ultimo = m.id ORDER BY m.fluxo_id""")]
                alvos = {x["fluxo_id"]: x["alvo"] for x in c.execute("SELECT fluxo_id, alvo FROM cameras")}
                envios = {x["fluxo_id"]: x["bitrate_alvo"] for x in
                          c.execute("""SELECT fluxo_id, bitrate_alvo FROM ingestoes i
                                       WHERE id = (SELECT MAX(id) FROM ingestoes WHERE fluxo_id=i.fluxo_id)""")}
            agora_iso = dt.datetime.now().astimezone()
            itens = []
            for l in linhas:
                try:
                    idade = int((agora_iso - dt.datetime.fromisoformat(str(l["medido_em"]))).total_seconds())
                except Exception:
                    idade = None
                passa = l["ssim"] is not None and float(l["ssim"]) >= etapas_pipeline.PISO_QUALIDADE_ACEITO
                atual = str(alvos.get(l["fluxo_id"]) or envios.get(l["fluxo_id"]) or "")
                sugerido = ""
                if not passa and atual:
                    # A sugestao tem de ser um degrau da lista FECHADA de qualidade (senao a tela sugere
                    # um numero que o servidor recusa). E' sempre o degrau SEGUINTE: subir um nivel por
                    # vez e' como o dono compara na tela: 300k -> 500k -> 800k -> 1000k -> 1200k -> 1500k.
                    try:
                        kbps = int(re.sub(r"[^0-9]", "", atual) or 0)
                    except ValueError:
                        kbps = 0
                    acima = [n for n in ("300k", "500k", "800k", "1000k", "1200k", "1500k")
                             if int(n[:-1]) > kbps]
                    if acima:
                        sugerido = min(acima, key=lambda n: int(n[:-1]))
                    # no teto (1500k) nao ha' degrau acima: nao se sugere nada — o caminho ali e' a fonte
                itens.append({"fluxo_id": l["fluxo_id"], "ssim": l["ssim"], "ajuste": l["ajuste"],
                              "resolucao": l["resolucao"], "fps": l["fps"], "medido_em": l["medido_em"],
                              "idade_s": idade, "passa": bool(passa), "alvo_atual": atual,
                              "alvo_sugerido": sugerido,
                              "explica": ("medido na maquina de captura (a que tem a fonte crua) e "
                                          "publicado aqui pelo anuncio autenticado do bordo")})
            return self._json(200, {"qualidade": producao_pipeline._qualidade_por_fluxo(), "fluxos": itens,
                                    "piso_qualidade": etapas_pipeline.PISO_QUALIDADE_SSIM,
                                    "piso_aceito": etapas_pipeline.PISO_QUALIDADE_ACEITO,
                                    "atualizado_em": agora_iso.isoformat(timespec="seconds")},
                              {"Cache-Control": "no-store"})
        if rota == "/api/producao":
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem a producao"})
            q = parse_qs(urlparse(self.path).query)
            try:
                dias = max(1, min(365, int((q.get("dias") or ["30"])[0])))
            except ValueError:
                dias = 30
            dados = producao_pipeline.resumo_producao(
                dias=dias,
                embarcacao_id=(q.get("embarcacao") or [None])[0],
                camera_id=(q.get("camera") or [None])[0],
                so_enviando=(q.get("so_enviando") or ["0"])[0] in ("1", "sim", "true"))
            dados["tempo_real"] = producao_pipeline.tempo_real()
            return self._json(200, dados, {"Cache-Control": "no-store"})
        if rota in ("/api/supabase", "/api/supabase/resumo"):
            # Producao e disponibilidade lidas do Supabase pelo servidor. A chave de servico vive no
            # ambiente do servidor; o navegador nunca fala com o Supabase.
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem os dados do Supabase"})
            import supabase_leitura
            return self._json(200, supabase_leitura.resumo(), {"Cache-Control": "no-store"})
        if rota in ("/api/dispositivos", "/api/envios/dispositivos"):
            # webcam do proprio notebook: fonte de teste, sem camera de embarcacao e sem credencial
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem os dispositivos de captura"})
            d = ing_dispositivos()
            # de onde veio o pedido: com a lista vazia, a tela precisa saber se esta' falando com o
            # lado terra (outra maquina) ou com a propria maquina, onde as cameras estao ligadas
            d["pedido_de"] = "esta_maquina" if self._local() else "outra_maquina"
            # de onde vem o ffmpeg (embutido no app / PATH / nenhum): e' o que explica lista vazia
            d["ffmpeg"] = resumo_ferramentas()
            d["sintetica"] = {"tipo": "sintetica", "descricao": "teste sintetico (testsrc2), sem camera",
                              "resolucoes": ["1920x1080", "1280x720"]}
            return self._json(200, d, {"Cache-Control": "no-store"})
        if rota in ("/api/cameras/detalhe", "/api/cameras/interno"):
            # endereco da camera so para a operacao: o app do cliente nunca recebe isso
            if not (u and u["papel"] in PAPEL_ADMIN) and not self._local():
                return self._json(403, {"erro": "so a operacao ve o endereco da camera"})
            with conexao() as c:
                linhas = [dict(x) for x in c.execute(
                    "SELECT id,rotulo,fluxo_id,embarcacao_id,local,ativo,ip,porta,protocolo,canal,alvo "
                    "FROM cameras ORDER BY id")]
            for l in linhas:
                # ENTRADA e APONTAMENTO (dono, 25/11/2026): a tela precisa dizer para ONDE a captura
                # aponta (dshow da maquina ou o IP do cadastro local) — sem credencial nenhuma aqui.
                l["entrada"] = "rede" if str(l.get("ip") or "").strip() else "usb"
                l["aponta_para"] = ingestao_modulo.endereco_da_camera(l)
                if l.get("ip"):
                    canal = str(l.get("canal") or "")
                    l["captura"] = ("rtsp://$USUARIO:$SENHA@" + l["ip"] + ":" + str(l.get("porta") or 554)
                                    + ("/Streaming/Channels/" + canal if canal else ""))
                    # o estado do segredo (nunca o valor): quem opera sabe se falta por a senha no bordo
                    l["segredo_configurado"] = segredo_camera.configurado(str(l["id"]))
                else:
                    l["captura"] = ""
            return self._json(200, {"cameras": linhas}, {"Cache-Control": "no-store"})
        if rota.startswith("/api/cameras/") and rota.endswith("/segredo"):
            # ESTADO DO SEGREDO da camera de rede: NUNCA o valor (dono, 25/11/2026: "senha nao pode
            # vazar, tem que tudo ficar no bordo"). GET porque a tela do bordo so' LE o estado. So' a
            # PROPRIA maquina de captura (o arquivo mora nela) ou o admin veem o caminho.
            if not (pode_configurar(u) or self._local()):
                return self._json(403, {"erro": "so' a maquina de captura ou o admin veem o estado do segredo"})
            cid = unquote(rota[len("/api/cameras/"):-len("/segredo")]).strip("/")
            return self._json(200, estado_do_segredo(cid), {"Cache-Control": "no-store"})
        if rota == "/api/cameras/prontidao":
            # Estado de STAND-BY por camera NESTA maquina (pronta / no ar / ausente / em uso). Nao abre
            # camera nenhuma: le' a lista de dispositivos que o ffmpeg ja' entrega. E' o que a tela mostra
            # ANTES de o cliente ativar (o sinal chega pelo split o tempo todo; transmitimos sob ordem).
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem a prontidao das cameras"})
            try:
                d = ing_prontidao()
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"erro": f"nao consegui medir a prontidao ({type(e).__name__}: {e})"})
            return self._json(200, d, {"Cache-Control": "no-store"})
        if rota == "/api/varredura":
            # O que a VARREDURA DO BORDO achou nesta maquina (Fase 2, 19/11/2026) e de quanto em quanto
            # tempo ela repete. Le' o ultimo resultado: nao dispara varredura nova so' porque a tela abriu.
            if not (u or self._local()):
                return self._json(401, {"erro": "entre no sistema"})
            import varredura_do_bordo
            return self._json(200, {"varredura": varredura_do_bordo.ultima(),
                                    "intervalo_s": varredura_do_bordo.intervalo()},
                              {"Cache-Control": "no-store"})
        if rota == "/api/empresas":
            # A AREA UNICA (0.12.0): empresa -> embarcacoes -> cameras numa leitura so. E' o que
            # substitui as 8 paginas soltas — e responde de uma vez o que a tela precisa desenhar.
            if not (u and (u["papel"] in PAPEL_ADMIN or u["papel"] == PAPEL_OBSERVADOR)):
                return self._json(401, {"erro": "entre no sistema"})
            try:
                return self._json(200, arvore_do_painel(u), {"Cache-Control": "no-store"})
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"erro": f"nao consegui montar a area do cliente "
                                                f"({type(e).__name__}: {e})"})
        if rota == "/api/cameras":
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            emb = parse_qs(urlparse(self.path).query).get("embarcacao", [None])[0]
            mt = caminhos_do_mediamtx()      # local + lado terra
            saida = []
            with conexao() as c:
                sql = "SELECT * FROM cameras WHERE ativo=1" + (" AND embarcacao_id=?" if emb else "")
                for cam in c.execute(sql, ((emb,) if emb else ())).fetchall():
                    if not pode_ver_camera(u, cam):
                        continue
                    if u["papel"] == PAPEL_OBSERVADOR and not pode_o_observador_ver(cam):
                        continue  # tipo 4: radar de oleo e FLIR de todas as empresas, e so' eles
                    p = mt.get(cam["fluxo_id"], {})
                    no_ar = bool(p.get("ready")) and bool(p.get("tracks"))
                    # por que NAO esta no ar: estado e motivo do ultimo envio (a tela avisa em vez de
                    # deixar so um quadro preto). Sem endereco de camera, sem credencial, sem porta.
                    ult = c.execute("""SELECT estado, erro, atualizado_em FROM ingestoes
                                       WHERE fluxo_id=? ORDER BY id DESC LIMIT 1""", (cam["fluxo_id"],)).fetchone()
                    motivo = ""
                    if not no_ar:
                        if not ult:
                            motivo = "nenhum envio registrado para esta câmera"
                        elif ult["erro"]:
                            motivo = ult["erro"]
                        elif ult["estado"] in ("parado", "fim"):
                            motivo = "envio parado"
                        elif ult["estado"] == "iniciando":
                            motivo = "iniciando o envio…"
                        else:
                            motivo = "sem sinal"
                    saida.append({"id": cam["id"], "rotulo": cam["rotulo"], "embarcacao_id": cam["embarcacao_id"],
                                  "tipo": tipo_da_camera(cam),
                                  "local": cam["local"], "no_ar": no_ar, "motivo": motivo, "tracks": p.get("tracks", []),
                                  "leitores": len(p.get("readers", [])), "encoder": perfil_encoder(cam["fluxo_id"])})
                # O fluxo que CHEGA no lado terra nao tinha como aparecer: so' linha cadastrada era
                # listada, e o bordo nao escreve no banco daqui. Para operador/admin, mostra tambem
                # o caminho VIVO do mediamtx sem cadastro — e' o caso do PC de captura que subiu e
                # ainda nao foi cadastrado. Cliente NAO ve isto (nao ha contrato a verificar).
                if u["papel"] in PAPEL_ADMIN and not emb:
                    conhecidos = {x[0] for x in c.execute("SELECT fluxo_id FROM cameras").fetchall()}
                    for nome, p in mt.items():
                        if nome in conhecidos or not (p.get("ready") and p.get("tracks")):
                            continue
                        saida.append({"id": "fluxo:" + nome, "rotulo": nome + " (no ar, sem cadastro)",
                                      "embarcacao_id": None, "local": "bordo", "no_ar": True, "motivo": "",
                                      "tracks": p.get("tracks", []), "leitores": len(p.get("readers", [])),
                                      "encoder": {}, "sem_cadastro": True,
                                      "aviso": "fluxo recebido do bordo sem câmera cadastrada: cadastre no PC de captura"})
            return self._json(200, {"cameras": saida})
        if rota == "/api/decisoes":
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            return self._json(200, {"decisoes": ler_tudo()["decisoes"]})
        if rota == "/api/usuarios":
            if not (u and u["papel"] == "admin"):
                return self._json(401, {"erro": "so o administrador do sistema"})
            with conexao() as c:
                linhas = c.execute("""SELECT u.id,u.email,u.nome,u.papel,u.cliente_id,u.ativo,u.criado_em,
                                      (SELECT count(*) FROM sessoes s WHERE s.usuario_id=u.id) AS sessoes
                                      FROM usuarios u ORDER BY u.papel, u.email""").fetchall()
            usuarios = [dict(x) for x in linhas]
            # `?credencial=1` pergunta ao Supabase quais e-mails existem la (UMA listagem, nao uma
            # por linha). Sem o parametro a resposta sai na hora e a coluna vem "não verificado" —
            # a tela do admin nao pode depender de rede para desenhar.
            consulta = parse_qs(urlparse(self.path).query)
            conhecidos = None
            if (consulta.get("credencial") or ["0"])[0] == "1":
                try:
                    import supabase_auth
                    conhecidos = supabase_auth.emails()
                except Exception:
                    conhecidos = None
            for linha in usuarios:
                linha["supabase"] = (None if conhecidos is None
                                     else (str(linha["email"]).lower() in conhecidos))
            return self._json(200, {"usuarios": usuarios, "verificado": conhecidos is not None})
        if rota.startswith("/api/usuarios/") and rota.endswith("/embarcacoes"):
            # ESCOPO do cliente (dono, 19/11/2026): quais embarcacoes este usuario pode ver. Quem
            # concede e' o admin; a tela mostra o vinculo explicito e o que vem herdado do cliente_id.
            uid = rota[len("/api/usuarios/"):-len("/embarcacoes")].strip("/")
            if not (u and u["papel"] == "admin"):
                return self._json(401, {"erro": "so o administrador do sistema"})
            with conexao() as c:
                alvo = c.execute("SELECT id,email,nome,papel,cliente_id,ativo FROM usuarios WHERE id=?",
                                 (uid,)).fetchone()
                if not alvo:
                    return self._json(404, {"erro": "usuario nao encontrado"})
                if alvo["papel"] == PAPEL_OBSERVADOR:
                    return self._json(200, {"usuario": dict(alvo), "embarcacoes": [], "vinculos": 0,
                                            "escopo": "todas_as_empresas",
                                            "nota": "o observador (tipo 4) ve todas as embarcacoes de "
                                                    "todas as empresas e nao recebe vinculo"})
                if alvo["papel"] != "cliente":
                    return self._json(422, {"erro": "vinculo por embarcacao e' so' do papel cliente",
                                            "papel": alvo["papel"]})
                concedidas = {r["embarcacao_id"] for r in c.execute(
                    "SELECT embarcacao_id FROM usuario_embarcacoes WHERE usuario_id=?", (uid,)).fetchall()}
                linhas = c.execute("SELECT id,nome,cliente_id FROM embarcacoes WHERE cliente_id=? ORDER BY nome",
                                   (alvo["cliente_id"],)).fetchall()
            lista = [dict(x) for x in linhas]
            for x in lista:
                x["concedida"] = x["id"] in concedidas
            if not concedidas:
                escopo = "todas_as_embarcacoes_da_empresa"
            elif len(concedidas) == 1:
                escopo = "uma_embarcacao_da_empresa"
            else:
                escopo = "algumas_embarcacoes_da_empresa"
            return self._json(200, {"usuario": dict(alvo), "embarcacoes": lista, "vinculos": len(concedidas),
                                    "escopo": escopo,
                                    "nota": "sem nenhum vinculo o cliente ve todas as embarcacoes da "
                                            "propria empresa"})
        if rota == "/api/clientes":
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "entre no sistema"})
            with conexao() as c:
                linhas = c.execute("""SELECT cl.*, (SELECT count(*) FROM embarcacoes e WHERE e.cliente_id=cl.id) AS embarcacoes,
                                      (SELECT count(*) FROM usuarios us WHERE us.cliente_id=cl.id) AS usuarios
                                      FROM clientes cl ORDER BY cl.nome""").fetchall()
            return self._json(200, {"clientes": [dict(x) for x in linhas]})
        if rota == "/api/sistema":
            if not (u and u["papel"] == "admin"):
                return self._json(401, {"erro": "so o administrador do sistema"})
            with conexao() as c:
                contagens = {t_: c.execute(f"SELECT count(*) FROM {t_}").fetchone()[0] for t_ in
                             ("usuarios", "clientes", "embarcacoes", "cameras", "sessoes", "medicoes", "decisoes",
                              "evidencias", "documentos", "analytics_eventos", "analytics_contagens", "auditoria_acesso")}
            return self._json(200, {"sistema": {
                "api": "Fase 4", "banco": str(BANCO), "python": sys.version.split()[0],
                "iniciado_em": INICIADO_EM,
                "uptime_s": int((dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(INICIADO_EM)).total_seconds()),
                "mediamtx": bool(mediamtx_json("/v3/paths/list").get("items") is not None),
                "chave_analytics_configurada": bool(os.environ.get("LECSOR_CHAVE_ANALYTICS")),
                "retencao_dias": os.environ.get("LECSOR_RETENCAO_DIAS", "nao definida"),
                "contagens": contagens}})
        if rota == "/api/auditoria":
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "so operador/admin"})
            return self._json(200, {"auditoria": ler_tudo()["auditoria"]})
        if rota == "/api/eventos":
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            return self._json(200, {"eventos": ler_tudo()["eventos"]})
        if rota == "/api/analytics/marcas":
            consulta = parse_qs(urlparse(self.path).query)
            alvo = (consulta.get("camera_id") or [""])[0]
            if not (u or self._chave_analytics()):
                return self._json(401, {"erro": "entre no sistema"})
            if alvo and u and not self._chave_analytics():
                with conexao() as c:
                    cam = c.execute("SELECT * FROM cameras WHERE id=?", (alvo,)).fetchone()
                if not pode_ver_camera(u, cam):
                    return self._json(403, {"erro": "camera fora do seu contrato"})
            return self._json(200, ler_marcas(alvo) if alvo else ler_marcas())
        if rota == "/api/analises":
            if not (u or self._local()):
                return self._json(401, {"erro": "entre no sistema"})
            if u and u["papel"] == PAPEL_OBSERVADOR:
                # Tipo 4 (Petrobras): o radar de oleo, e nada de analytics/agentes (plano, Fase 4).
                return self._json(200, {"agentes": [], "contagens": [], "eventos": []})
            return self._json(200, analises())
        if rota.startswith("/hls/"):
            return self._hls(rota[len("/hls/"):], u)
        if rota.startswith("/api/relatorios/") and rota.endswith(".pdf"):
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "so operador/admin exporta documento"})
            return self._pdf(rota)
        return super().do_GET()

    # ---- POST
    def do_POST(self) -> None:  # noqa: N802
        rota = urlparse(self.path).path
        # POST de captura (ingestao, compressao, medicao, trecho) e' desta maquina; o resto
        # (entrar, cadastro, usuarios, gravacoes, transmissao pedida) e' do lado terra.
        #
        # ACHADO (19/11/2026, medido em bancada com duas APIs): o cadastro feito pelo usuario de captura
        # (`POST /api/cameras`) e' ENCAMINHADO para terra, e o bordo fica SEM a camera que ele acabou de
        # cadastrar. Ligar isto como rota local NAO resolve sozinho: `/api/entrar` tambem vai para terra,
        # entao a sessao do usuario de captura nao existe no banco do bordo e a rota local responde 401.
        # O conserto e' de desenho (autenticacao/sessao local no bordo + espelho dos usuarios que podem
        # capturar) e esta' registrado no plano da 0.8.0 como pendencia para aprovacao do dono.
        if self._base_do_lado_terra() and not eh_rota_de_captura(rota):
            return self._encaminhar("POST")
        u = self._sessao()
        if rota == "/api/licencas":
            # GERAR licenca: so' o admin (dono, 19/11/2026: quem cadastra e configura e' o admin).
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(403, {"erro": "so' o admin gera licenca"})
            return self._criar_licenca(u)
        if rota.startswith("/api/licencas/"):
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(403, {"erro": "so' o admin mexe em licenca"})
            return self._licenca_acao(u)
        if rota == "/api/licenca/ativar":
            # sem sessao de proposito: o PC de captura recem-instalado ainda nao tem usuario; a CHAVE
            # e' a credencial dele.
            return self._licenca_atender(contar=True)
        if rota == "/api/licenca/validar":
            return self._licenca_atender(contar=False)
        if rota == "/api/licenca/esquecer":
            return self._esquecer_licenca(u)
        if rota == "/api/publicacao":
            # "publicar agora": manda o cadastro de TODAS as cameras desta maquina ao lado terra e
            # devolve o resultado por camera. E' o botao que faltava quando o anuncio falhava em
            # silencio (a tela so' podia dizer "nao apareceu").
            if not (u and u["papel"] in PAPEL_ADMIN) and not self._local():
                return self._json(401, {"erro": "entre no sistema"})
            import repasse as repasse_modulo
            with conexao() as c:
                cams = [dict(x) for x in c.execute("SELECT * FROM cameras ORDER BY id")]
            enviadas = sum(1 for cam in cams if repasse_modulo.publicar_cadastro(cam).get("ok"))
            estado = repasse_modulo.estado_do_anuncio()
            tentativas = estado.get("tentativas") or {}
            itens = [{"id": cam["id"], "fluxo_id": cam["fluxo_id"], "rotulo": cam["rotulo"],
                      "ativo": cam["ativo"],
                      "publicado": bool((tentativas.get(cam["fluxo_id"]) or {}).get("ok")),
                      "motivo": (tentativas.get(cam["fluxo_id"]) or {}).get("motivo") or "",
                      "em": (tentativas.get(cam["fluxo_id"]) or {}).get("em") or ""} for cam in cams]
            return self._json(200, {"ok": enviadas == len(cams), "publicadas": enviadas,
                                    "total": len(cams), "anuncio": estado, "cameras": itens},
                              {"Cache-Control": "no-store"})
        if rota == "/api/entrar":
            d = self._corpo()
            email = str(d.get("email", "")).strip().lower()
            senha = str(d.get("senha", ""))
            with conexao() as c:
                alvo = c.execute("SELECT * FROM usuarios WHERE email=? AND ativo=1", (email,)).fetchone()
            # O login e do Supabase Auth (os MESMOS usuarios e senha que o app ja usa).
            # O hash local e a rede de protecao: bancada sem Supabase/rede fora continua entrando,
            # mas senha trocada no Supabase vale aqui — recusa de la nao cai para o local.
            import supabase_auth
            veredito = supabase_auth.entrar(email, senha)
            # Quem autoriza a entrar e' o CADASTRO DESTA INSTALACAO (dono, 17/11/2026: "um usuario
            # nao pode se cadastrar, quem cadastra os usuarios e' o admin"). O Supabase confere a
            # SENHA; se ele reconhecer alguem que nao esta cadastrado aqui (conta criada por fora),
            # a resposta e' 403 e NENHUMA linha nasce neste banco. Antes disso a identidade era
            # adotada no ato do login, o que fazia qualquer cadastro de fora entrar como cliente.
            if veredito is not None and veredito.get("ok") and not alvo:
                auditar(None, "adocao_recusada", email[:80], self.client_address[0])
                return self._json(403, {"erro": "esta conta nao esta cadastrada nesta instalacao: "
                                               "quem cadastra usuarios e' o administrador"})
            if veredito is None:
                entrou = bool(alvo) and conferir_senha(alvo, senha)
            else:
                entrou = bool(veredito.get("ok")) and bool(alvo)
            if not entrou:
                auditar(None, "entrada_falha", email[:80], self.client_address[0])
                # Instalacao SEM usuario nenhum e chamada de dentro da propria maquina: o defeito nao e'
                # a senha, e' a instalacao (dono, 18/11/2026: "já deve ter por padrão todas as
                # autorizações" — a tela ficava repetindo "e-mail ou senha invalidos" quando o que
                # faltava era justamente o primeiro administrador). Dizer o que falta, em vez de
                # acusar a senha do usuario.
                local_vazio = False
                if self._local():
                    with conexao() as c:
                        local_vazio = not c.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
                if local_vazio:
                    return self._json(401, {"erro": "esta instalacao ainda nao tem usuario nenhum: "
                                                   "crie o primeiro administrador desta maquina (formulario "
                                                   "abaixo) ou entre no lado terra",
                                            "base_local": True, "primeiro_acesso": True})
                return self._json(401, {"erro": "e-mail ou senha invalidos"})
            token = criar_sessao(alvo["id"], self.headers.get("User-Agent", ""))
            auditar(alvo, "entrada", alvo["email"], self.client_address[0])
            return self._json(200, {"ok": True, "nome": alvo["nome"], "papel": alvo["papel"]},
                              {"Set-Cookie": f"sessao={token}; HttpOnly; SameSite=Lax; Path=/",
                               "Cache-Control": "no-store"})
        if rota == "/api/primeiro-acesso":
            # Cria o PRIMEIRO administrador desta instalacao. Só vale enquanto nao existe usuario
            # nenhum (depois disso a porta fecha: 403) e só na propria maquina do servidor (quem
            # abre o aplicativo nela) — ninguem de fora pode reivindicar a instalacao.
            if not self._local():
                return self._json(403, {"erro": "o primeiro acesso e criado na propria maquina do servidor: abra o aplicativo nela"})
            with conexao() as c:
                if c.execute("SELECT count(*) FROM usuarios").fetchone()[0]:
                    return self._json(403, {"erro": "esta instalacao ja tem usuario: entre com a conta que ja existe"})
            d = self._corpo()
            nome = str(d.get("nome") or "").strip()
            email = str(d.get("email") or "").strip().lower()
            senha = str(d.get("senha") or "")
            if len(nome) < 3:
                return self._json(400, {"erro": "informe o nome de quem vai operar esta maquina"})
            if "@" not in email or "." not in email.split("@")[-1]:
                return self._json(400, {"erro": "informe um e-mail valido"})
            if len(senha) < 8:
                return self._json(400, {"erro": "a senha precisa de 8 caracteres ou mais"})
            # Se a credencial JA' existe no Supabase (o cliente que ja' usa o app), adota essa
            # identidade em vez de criar mais um administrador solto na maquina — era isso que
            # deixava o login novo "sem vinculo com o cliente que ja' estava sendo testado".
            import supabase_auth
            try:
                _cfg = supabase_auth.configurado()
            except Exception:
                _cfg = False
            if _cfg:
                v = supabase_auth.entrar(email, senha)
                if v and v.get("ok"):
                    # Primeiro acesso desta maquina e' o ADMINISTRADOR dela: adotar a identidade do
                    # Supabase aqui nao pode nascer como "cliente" (o papel vem do token, que nao
                    # guarda papel) — senao a instalacao nova nascia sem administrador.
                    alvo = self._adotar_do_supabase(email, v, senha, "admin")
                    self._provisionar_no_supabase(email, senha, nome)
                    token = criar_sessao(alvo["id"], self.headers.get("User-Agent", ""))
                    auditar(alvo, "primeiro_acesso_supabase", email, self.client_address[0])
                    return self._json(200, {"ok": True, "nome": alvo["nome"], "papel": alvo["papel"],
                                            "origem": "supabase"},
                                      {"Set-Cookie": f"sessao={token}; HttpOnly; SameSite=Lax; Path=/",
                                       "Cache-Control": "no-store"})
            salt = secrets.token_hex(8)
            uid = "admin-" + secrets.token_hex(3)
            with conexao() as c:
                c.execute("""INSERT INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt)
                             VALUES (?,?,?,?,?,?,?)""",
                          (uid, email, nome, "admin", None, hash_senha(senha, salt), salt))
                alvo = c.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
            # A senha digitada vale tambem no Supabase Auth: sem isso o login seguinte (que e' do
            # Supabase) recusava o administrador que esta tela acabou de criar.
            supabase = self._provisionar_no_supabase(email, senha, nome)
            token = criar_sessao(alvo["id"], self.headers.get("User-Agent", ""))
            auditar(alvo, "primeiro_acesso", email, self.client_address[0])
            return self._json(200, {"ok": True, "nome": alvo["nome"], "papel": alvo["papel"],
                                    "supabase": supabase},
                              {"Set-Cookie": f"sessao={token}; HttpOnly; SameSite=Lax; Path=/",
                               "Cache-Control": "no-store"})
        if rota == "/api/sair":
            # SAIR DO SISTEMA: as sessoes do cliente caem e o que foi gravado para ele e' APAGADO
            # (dono, 18/11/2026: o arquivo sai quando ele sair da tela ou desligar o sistema). O
            # historico e a auditoria ficam: sempre se sabe quais acoes foram tomadas e por quem.
            if u:
                try:
                    with conexao() as c:
                        abertas = [dict(x) for x in c.execute(
                            """SELECT * FROM transmissoes WHERE usuario_email=?
                               AND estado IN ('pedida','no_ar')""", (u["email"],)).fetchall()]
                    for t in abertas:
                        if fechar_transmissao(t["id"], "encerrada", "o cliente saiu do sistema"):
                            parar_se_ninguem_vendo(t["embarcacao_id"], t["camera_id"], t["fluxo_id"],
                                                   "o cliente saiu do sistema")
                    apagar_gravacoes_do_cliente(u, "o cliente saiu do sistema", self.client_address[0])
                    auditar(u, "cliente_saiu_do_sistema", f"{len(abertas)} sessao(oes) fechada(s)",
                            self.client_address[0])
                except Exception as e:
                    print("[api] aviso: limpeza ao sair:", type(e).__name__, e, flush=True)
            if "Cookie" in self.headers:
                ck = SimpleCookie(self.headers["Cookie"])
                if "sessao" in ck:
                    with conexao() as c:
                        c.execute("DELETE FROM sessoes WHERE token=?", (ck["sessao"].value,))
            return self._json(200, {"ok": True}, {"Set-Cookie": "sessao=; Max-Age=0; Path=/"})
        if rota.startswith("/api/qualidade/medir"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador medem a qualidade"})
            d = self._corpo()
            fluxo = str(d.get("fluxo") or d.get("fluxo_id") or "").strip()
            if not fluxo:
                return self._json(400, {"erro": "informe o fluxo (fluxo)"})
            import qualidade as _qualidade
            try:
                segundos = float(d.get("segundos") or 8)
            except Exception:
                segundos = 8.0
            r = _qualidade.medir(fluxo, segundos=segundos,
                                 bitrate=(str(d.get("bitrate")).strip() if d.get("bitrate") else None))
            return self._json(200 if r.get("ok") else 422, r, {"Cache-Control": "no-store"})
        if rota == "/api/qualidade/comparar":
            # A mesma cena em varios alvos, com SSIM e nitidez de cada um: e' o numero que responde
            # "esta perdendo qualidade?". Exige a fonte LIVRE (a medicao precisa dela), por isso
            # recusa com recado claro enquanto o envio estiver no ar.
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador comparam a qualidade"})
            d = self._corpo()
            fluxo = str(d.get("fluxo") or d.get("fluxo_id") or "").strip()
            if not fluxo:
                return self._json(422, {"erro": "informe o fluxo (fluxo)"})
            alvos = d.get("alvos") or ["1500k", "2500k", "4000k"]
            if isinstance(alvos, str):
                alvos = [x.strip() for x in alvos.split(",") if x.strip()]
            alvos = [str(x) for x in alvos if re.match(r"^\s*[0-9]{2,6}k?\s*$", str(x))]
            if not alvos:
                return self._json(422, {"erro": "informe os alvos (ex.: 1500k,2500k,4000k)"})
            try:
                segundos = float(d.get("segundos") or 6)
            except Exception:
                segundos = 6.0
            import qualidade as _qualidade
            r = _qualidade.comparar_alvos(fluxo, alvos=alvos, segundos=segundos)
            auditar(u, "comparar_alvos", f"{fluxo} {alvos}", self.client_address[0])
            return self._json(200 if r.get("ok") else 422, r, {"Cache-Control": "no-store"})
        if rota in ("/api/compressao/publicar", "/api/compressoes/publicar"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador publicam"})
            d = self._corpo()
            r = etapas_pipeline.publicar_compressao(int(d.get("id") or 0),
                                                    rotulo=d.get("rotulo") or None)
            if "erro" in r:
                return self._json(422, r)
            auditar(u, "publicar_compressao", f"id {d.get('id')} -> {r['fluxo_id']}", self.client_address[0])
            return self._json(201, r, {"Cache-Control": "no-store"})
        if rota in ("/api/compressao/remover", "/api/compressoes/remover"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador removem"})
            d = self._corpo()
            return self._json(200, etapas_pipeline.remover_compressao(int(d.get("id") or 0)))
        if rota in ("/api/ingestao/arquivo", "/api/envios/arquivo"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador enviam video de teste"})
            q = parse_qs(urlparse(self.path).query)
            def _q(k, p="") :
                return (q.get(k) or [p])[0]
            nome = re.sub(r"[^A-Za-z0-9 ._\-]", "_", Path(_q("nome", "video-enviado.mp4")).name)[:80] or "video-enviado.mp4"
            if Path(nome).suffix.lower() not in (".mp4", ".mkv", ".mov", ".m4v", ".webm", ".ts", ".avi", ".mpg", ".mpeg", ".flv"):
                nome += ".mp4"
            destino = RAIZ / "ground" / "envios" / nome
            try:
                gravados = self._corpo_bruto(destino)
            except ValueError as e:
                return self._json(422, {"erro": str(e)})
            r = ing_iniciar(str(destino), rotulo=_q("rotulo", Path(nome).stem), fluxo_id=_q("fluxo_id") or None,
                            bitrate=_q("bitrate", "auto"), codec=_q("codec", "libx264"),
                            repetir=_q("repetir", "1") not in ("0", "false", "nao"), tipo="arquivo",
                            audio=_q("audio", "0") in ("1", "sim", "true"),
                            fps=int(_q("fps", "30") or 30), guardar_arquivo=_q("guardar", "0") in ("1", "sim", "true"),
                            embarcacao_id=_q("embarcacao", "psv-exemplo"))
            if "erro" in r:
                return self._json(422, r)
            auditar(u, "envio_video", f"arquivo {nome} ({gravados} bytes) -> {r['fluxo_id']}", self.client_address[0])
            return self._json(201, {"ok": True, "bytes": gravados, **r}, {"Cache-Control": "no-store"})
        if rota == "/api/embarcacoes/radar":
            # GRAVA a config de radar daquela embarcacao (como o alvo por camera da 0.4.0). Fica no
            # banco do PC de captura e passa a ser o PADRAO dos proximos envios daquela embarcacao.
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so a operacao e o administrador gravam a config do radar"})
            d = self._corpo()
            erro, valores = self._validar_radar(d)
            if erro:
                return self._json(422, {"erro": erro, "modos": list(self.MODOS_DE_RADAR),
                                        "taxas": list(self.TAXAS_DE_RADAR),
                                        "alvos": list(self.ALVOS_DE_QUALIDADE)})
            with conexao() as c:
                existe = c.execute("SELECT id FROM embarcacoes WHERE id=?", (valores["embarcacao_id"],)).fetchone()
                if not existe:
                    return self._json(404, {"erro": f"embarcacao {valores['embarcacao_id']} nao existe"})
                c.execute("UPDATE embarcacoes SET radar_fonte=?, radar_modo=?, radar_taxa=?, radar_alvo=?"
                          " WHERE id=?", (valores["fonte"], valores["modo"], valores["taxa"],
                                          valores["alvo"], valores["embarcacao_id"]))
            auditar(u, "config_radar", f"{valores['embarcacao_id']} ({valores['modo']}/{valores['taxa']})",
                    self.client_address[0])
            return self._json(200, {"ok": True, "radar": self._radar_da_embarcacao(valores["embarcacao_id"])},
                              {"Cache-Control": "no-store"})
        if rota in ("/api/ingestao/ao-vivo", "/api/envios/ao-vivo"):
            # STREAMING CONTINUO de uma fonte viva (webcam do notebook / fonte sintetica):
            # sem duracao determinada, igual a operacao — so para quando mandarem parar.
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador transmitem ao vivo"})
            d = self._corpo()
            tipo = str(d.get("tipo") or "camera")
            embarcacao_id = str(d.get("embarcacao_id") or "").strip() or "bancada"
            radar = {"fonte": str(d.get("fonte") or "").strip(), "modo": str(d.get("modo") or "").strip(),
                     "taxa": str(d.get("taxa") or "").strip(), "alvo": str(d.get("bitrate") or "").strip()}
            if tipo == "radar":
                # Fase 6: o que ficou GRAVADO naquela embarcacao e' o padrao — a tela so' precisa
                # mandar o que o operador mudou agora.
                cfg = self._radar_da_embarcacao(embarcacao_id)
                for chave in ("fonte", "modo", "taxa", "alvo"):
                    if not radar[chave] and cfg.get(chave):
                        radar[chave] = cfg[chave]
                if not radar["fonte"]:
                    return self._json(422, {"erro": "escolha a fonte do radar (arquivo .drq ou "
                                                   "tcp://host:porta) ou grave a config da embarcacao",
                                            "radar": cfg})
                # nome legivel quando a tela nao manda um: quem opera ve "Radar de <embarcacao>" na
                # lista de envios, nao um fluxo sem nome.
                if not str(d.get("rotulo") or "").strip():
                    d["rotulo"] = f"Radar de {embarcacao_id}"
            r = ing_ao_vivo(tipo=tipo,
                            dispositivo=(str(d.get("dispositivo") or "").strip() or None),
                            resolucao=str(d.get("resolucao") or "1920x1080"), fps=int(d.get("fps") or 30),
                            rotulo=str(d.get("rotulo") or ""), fluxo_id=(str(d.get("fluxo_id") or "").strip() or None),
                            bitrate=(radar["alvo"] or str(d.get("bitrate") or "auto")),
                            embarcacao_id=embarcacao_id,
                            # RADAR (Fase 3/5): o sinal de radar entra na cadeia como uma camera — a fonte
                            # e' o arquivo .drq ou o radar pela rede, e o desenho (PPI/cru, 1 imagem por
                            # volta ou 30 fps) roda no servidor, que empurra os quadros crus no ffmpeg.
                            radar_fonte=(radar["fonte"] or None),
                            radar_modo=(radar["modo"] or "ppi"), radar_taxa=(radar["taxa"] or "30fps"))
            if "erro" in r:
                return self._json(422, r)
            # a resposta leva o nome do envio: a tela avisa "NO AR: <nome>" sem ter de adivinhar.
            if tipo == "radar":
                r.setdefault("rotulo", str(d.get("rotulo") or ""))
                r.setdefault("modo", radar["modo"] or "ppi")
                r.setdefault("taxa", radar["taxa"] or "30fps")
            auditar(u, "transmitir_ao_vivo", f"{r['fluxo_id']} ({r['alvo']})", self.client_address[0])
            return self._json(201, r, {"Cache-Control": "no-store"})
        if rota in ("/api/ingestao/capturar", "/api/envios/capturar"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador capturam video de teste"})
            d = self._corpo()
            tipo = str(d.get("tipo") or "camera")
            r = ing_capturar(tipo=tipo, dispositivo=(str(d.get("dispositivo") or "").strip() or None),
                             resolucao=str(d.get("resolucao") or "1920x1080"), fps=int(d.get("fps") or 30),
                             segundos=int(d.get("segundos") or 10), rotulo=str(d.get("rotulo") or ""))
            if "erro" in r:
                return self._json(422, r)
            auditar(u, "capturar_video",
                    f"{r['tipo']} {r['dispositivo']} -> {r['nome']} ({r['segundos']}s, {r['bitrate_kbps']} kbps)",
                    self.client_address[0])
            return self._json(201, r, {"Cache-Control": "no-store"})
        if rota in ("/api/ingestao/comprimir", "/api/envios/comprimir"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador comprimem video"})
            q = parse_qs(urlparse(self.path).query)
            def _qc(k, p=""):
                return (q.get(k) or [p])[0]
            qualidade = _qc("qualidade", "auto")
            fps = int(_qc("fps", "30") or 30)
            tipo_json = "application/json" in (self.headers.get("Content-Type") or "")
            if tipo_json:
                d = self._corpo()
                # fonte do JSON pode ser um LINK ou um clipe JA CAPTURADO da webcam/fonte sintetica
                arquivo_json = str(d.get("arquivo") or "").strip()
                endereco = str(d.get("url") or "").strip()
                comum = dict(qualidade=str(d.get("qualidade") or qualidade), fps=int(d.get("fps") or fps),
                             audio=bool(d.get("audio", False)), nome=str(d.get("rotulo") or "") or None)
                if arquivo_json:
                    nome_seguro = Path(arquivo_json).name
                    caminho = RAIZ / "ground" / "envios" / "originais" / nome_seguro
                    if not caminho.exists():
                        return self._json(404, {"erro": f"clipe capturado nao encontrado: {nome_seguro}"})
                    r = etapas_pipeline.comprimir(str(caminho), **comum)
                elif re.match(r"^https?://", endereco):
                    r = etapas_pipeline.comprimir(endereco, **comum)
                else:
                    return self._json(422, {"erro": "informe um link http(s) valido ou capture um clipe da webcam"})
            else:
                nome = re.sub(r"[^A-Za-z0-9 ._\-]", "_", Path(_qc("nome", "video.mp4")).name)[:80] or "video.mp4"
                origem_dir = RAIZ / "ground" / "envios" / "originais"
                origem_dir.mkdir(parents=True, exist_ok=True)
                destino = origem_dir / nome
                try:
                    self._corpo_bruto(destino)
                except ValueError as e:
                    return self._json(422, {"erro": str(e)})
                r = etapas_pipeline.comprimir(str(destino), qualidade=qualidade, fps=fps,
                                              nome=Path(nome).stem,
                                              audio=_qc("audio", "0") in ("1", "sim", "true"))
            if not r.get("ok"):
                return self._json(422, r)
            r["baixar"] = "/api/comprimido/" + r["nome_arquivo"]
            auditar(u, "comprimir_video",
                    f"{r['nome_arquivo']}: {r['entrada']['mb']} MB -> {r['comprimido']['mb']} MB ({r['corte_pct']}%)",
                    self.client_address[0])
            return self._json(201, r, {"Cache-Control": "no-store"})
        if rota in ("/api/ingestao/url", "/api/envios/url"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador enviam video de teste"})
            d = self._corpo()
            endereco = str(d.get("url") or "").strip()
            if not re.match(r"^https?://", endereco):
                return self._json(422, {"erro": "informe um link http(s) valido"})
            r = ing_iniciar(endereco, rotulo=str(d.get("rotulo") or "video por link"), fluxo_id=d.get("fluxo_id") or None,
                            bitrate=str(d.get("bitrate") or "auto"), codec=str(d.get("codec") or "libx264"),
                            repetir=bool(d.get("repetir", True)), tipo="url", audio=bool(d.get("audio", False)),
                                    fps=int(d.get("fps") or 30), guardar_arquivo=bool(d.get("guardar", False)),
                            embarcacao_id=str(d.get("embarcacao") or "psv-exemplo"))
            if "erro" in r:
                return self._json(422, r)
            auditar(u, "envio_video", f"link {endereco[:120]} -> {r['fluxo_id']}", self.client_address[0])
            return self._json(201, {"ok": True, **r}, {"Cache-Control": "no-store"})
        if rota == "/api/cameras/prontidao":
            # Estado de STAND-BY por camera NESTA maquina (pronta / no ar / ausente / em uso). Nao abre
            # camera nenhuma: le' a lista de dispositivos que o ffmpeg ja' entrega. E' o que a tela mostra
            # ANTES de o cliente ativar (regra do split: o sinal chega o tempo todo, nos transmitimos sob ordem).
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador veem a prontidao das cameras"})
            try:
                d = ing_prontidao()
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"erro": f"nao consegui medir a prontidao ({type(e).__name__}: {e})"})
            return self._json(200, d, {"Cache-Control": "no-store"})
        if rota in ("/api/cameras/desligar", "/api/cameras/ligar"):
            # ligar/desligar a camera pela tela: quem manda e' a operacao (o cliente so olha).
            # desligar = para o envio e SOLTA o dispositivo; ligar = reabre com o ultimo ajuste.
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador ligam e desligam a camera"})
            d = self._corpo()
            cam_id = str(d.get("camera_id") or d.get("id") or "").strip()
            if not cam_id:
                return self._json(422, {"erro": "informe a camera"})
            desligar = rota.endswith("desligar")
            # QUEM CAPTURA E' A MAQUINA DE CAPTURA (dono, 19/11/2026): o sinal chega pelo split direto no
            # nosso dispositivo, entao aqui no LADO TERRA o clique NAO abre camera — vira ORDEM para o bordo.
            # Medido em 19/11/2026: sem isso o lado terra tentava `-f dshow` no Linux e a tela respondia
            # "Unknown input format: 'dshow'" / codigo 234, sem ninguem entender de onde vinha.
            if not ing_maquina_de_captura():
                if self._local():
                    # o pedido nasceu NESTA maquina: nao ha' para onde mandar ordem (criar ordem aqui
                    # seria um pedido que ninguem escuta) — e a captura NAO acontece aqui. Diga a verdade.
                    return self._json(422, {
                        "erro": ("esta maquina nao e' a de captura: nao ha' entrada de video aqui — "
                                 "a camera liga no PC de bordo (confira o cabo/USB do split)"),
                        "maquina_de_captura": False}, {"Cache-Control": "no-store"})
                try:
                    with conexao() as c:
                        cam = c.execute("SELECT id, embarcacao_id, fluxo_id, rotulo FROM cameras WHERE id=?",
                                        (cam_id,)).fetchone()
                except Exception as e:  # noqa: BLE001
                    return self._json(500, {"erro": f"nao consegui ler a camera ({type(e).__name__})"})
                if not cam:
                    return self._json(422, {"erro": "camera nao encontrada"})
                if not str(cam["embarcacao_id"] or "").strip():
                    return self._json(422, {"erro": "a camera ainda nao pertence a uma embarcacao: cadastre antes"})
                quem = f"{u['papel']}:{u['email']}" if u else "tela local"
                o = enfileirar_ordem(cam["embarcacao_id"], cam_id, cam["fluxo_id"],
                                     "parar" if desligar else "iniciar", motivo=f"pedido de {quem}")
                # alem da ordem (compatibilidade), grava a INTENCAO na flag: o bordo olha o desejo e age
                # na diferenca — e' assim que o botao do operador chega ao PC de captura sem porta aberta.
                # D3 do dono (24/11/2026): so' o DESLIGAR tem override manual. O LIGAR **limpa** o manual —
                # quem sustenta o "ligar" e' a sessao de quem assiste (`_desejo_das_cameras`), nunca o admin.
                with conexao() as c:
                    c.execute("""INSERT INTO desejo_camera
                                   (camera_id,embarcacao_id,desejo,versao,motivo,transmissao_id,manual,atualizado_em)
                                 VALUES (?,?,?,0,'','',?,?)
                                 ON CONFLICT(camera_id) DO UPDATE SET manual=excluded.manual""",
                              (cam_id, cam["embarcacao_id"], "parar" if desligar else "ligar",
                               "parar" if desligar else "", em_iso()))
                auditar(u, "ordem_camera_desligada" if desligar else "ordem_camera_ligada",
                        f"{cam_id} ({cam['embarcacao_id']}) ordem #{o['seq']}", self.client_address[0])
                return self._json(200, {"ok": True, "ordem": o["seq"], "enviado_ao_bordo": True,
                                        "recado": ("esta maquina nao e' a de captura: a ordem foi enviada ao "
                                                   "bordo e o PC de captura liga a camera")},
                                  {"Cache-Control": "no-store"})
            r = ing_desligar_camera(cam_id) if desligar else ing_ligar_camera(cam_id)
            if "erro" in r:
                return self._json(422, r)
            auditar(u, "camera_desligada" if desligar else "camera_ligada", cam_id, self.client_address[0])
            return self._json(200, r, {"Cache-Control": "no-store"})
        if rota in ("/api/ingestao/parar", "/api/envios/parar"):
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador enviam video de teste"})
            d = self._corpo()
            try:
                ident = int(d.get("id"))
            except (TypeError, ValueError):
                return self._json(422, {"erro": "informe o id do envio"})
            r = ing_parar(ident, remover_camera=bool(d.get("remover")))
            if "erro" in r:
                return self._json(404, r)
            auditar(u, "envio_video_parado", f"envio {ident} ({r.get('fluxo_id')})", self.client_address[0])
            return self._json(200, r, {"Cache-Control": "no-store"})
        if rota == "/api/analytics/marcas":
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(403, {"erro": "so operacao e administrador desenham as marcas"})
            d = self._corpo()
            try:
                marcas = gravar_marcas(u, str(d.get("camera_id") or ""), d.get("linha"), list(d.get("zonas") or []))
            except LookupError as e:
                return self._json(422, {"erro": str(e)})
            except (ValueError, TypeError, KeyError) as e:
                return self._json(422, {"erro": f"marca invalida: {e}"})
            return self._json(201, {"ok": True, "marcas": marcas})
        if rota == "/api/analytics/eventos":
            if not self._chave_analytics():
                return self._json(401, {"erro": "chave do agente de analise ausente ou invalida"})
            d = self._corpo()
            try:
                n = registrar_eventos(str(d.get("camera_id") or ""), list(d.get("eventos") or []))
            except LookupError as e:
                return self._json(422, {"erro": str(e)})
            except Exception as e:  # banco recusou: responde explicando, nunca fecha a conexao
                return self._json(400, {"erro": f"evento recusado: {e}"})
            return self._json(201, {"ok": True, "gravados": n})
        if rota == "/api/analytics/contagens":
            if not self._chave_analytics():
                return self._json(401, {"erro": "chave do agente de analise ausente ou invalida"})
            d = self._corpo()
            try:
                ident = registrar_contagem(str(d.get("camera_id") or ""), d)
            except LookupError as e:
                return self._json(422, {"erro": str(e)})
            except Exception as e:  # banco recusou: responde explicando, nunca fecha a conexao
                return self._json(400, {"erro": f"contagem recusada: {e}"})
            return self._json(201, {"ok": True, "id": ident})
        if rota.startswith("/whep/"):
            return self._whep(rota[len("/whep/"):], u)
        if rota == "/api/medicoes":
            # sessao de cliente NAO grava medicao: a bancada (loopback, sem sessao de usuario) grava;
            # operador/admin autenticado grava.
            if u and u["papel"] not in PAPEL_ADMIN:
                auditar(u, "escrita_negada", "medicoes", self.client_address[0])
                return self._json(403, {"erro": "so operador/admin grava medicao"})
            if not (u or self._local()):
                return self._json(401, {"erro": "entre no sistema"})
            codigo, corpo = inserir_medicao(self._corpo())
            if codigo == 201 and u:
                auditar(u, "gravar_medicao", str(corpo.get("id")), self.client_address[0])
            return self._json(codigo, corpo)
        if rota == "/api/usuarios":
            if not (u and u["papel"] == "admin"):
                return self._json(401, {"erro": "so o administrador do sistema"})
            d = self._corpo()
            faltando = [k for k in ("email", "nome", "papel") if not str(d.get(k, "")).strip()]
            if faltando:
                return self._json(422, {"erro": "usuario incompleto", "campos_faltando": faltando})
            if d["papel"] not in PAPEIS_DE_USUARIO:
                return self._json(422, {"erro": "papel invalido", "aceitos": list(PAPEIS_DE_USUARIO)})
            if d["papel"] == "cliente" and not d.get("cliente_id"):
                return self._json(422, {"erro": "usuario de cliente precisa de cliente_id"})
            if d["papel"] != "cliente":
                d["cliente_id"] = None
            email = str(d["email"]).strip().lower()
            with conexao() as c:
                if c.execute("SELECT 1 FROM usuarios WHERE email=?", (email,)).fetchone():
                    return self._json(409, {"erro": "e-mail ja cadastrado"})
                if d.get("cliente_id") and not c.execute("SELECT 1 FROM clientes WHERE id=?", (d["cliente_id"],)).fetchone():
                    return self._json(422, {"erro": "cliente_id inexistente"})
                senha = secrets.token_urlsafe(9)
                salt = secrets.token_hex(16)
                uid = email.split("@")[0][:24] + "-" + secrets.token_hex(3)
                c.execute("""INSERT INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt)
                             VALUES (?,?,?,?,?,?,?)""",
                          (uid, email, d["nome"], d["papel"], d.get("cliente_id"), hash_senha(senha, salt), salt))
            # A senha vale dos DOIS lados: no banco local (rede de protecao sem rede) e no Supabase
            # Auth, que e' quem confere no login. Sem isto o usuario criado pelo administrador tomava
            # 401 ao entrar — era o "usuario nao consegue entrar" (dono, 17/11/2026). Falha de rede
            # nao esconde o usuario: a linha local ja' existe e a resposta diz o que faltou.
            supabase = self._provisionar_no_supabase(email, senha, str(d["nome"]))
            auditar(u, "criar_usuario", email, self.client_address[0])
            # a senha inicial aparece UMA vez, para quem criou entregar; o banco guarda so o hash
            return self._json(201, {"id": uid, "email": email, "papel": d["papel"],
                                    "senha_inicial": senha, "supabase": supabase})
        if rota.startswith("/api/usuarios/") and rota.endswith("/embarcacoes"):
            # CONCEDER/REVOGAR embarcacao para um cliente (admin). Grava o conjunto INTEIRO: o corpo
            # manda a lista final; lista vazia volta o usuario ao padrao (todas as da propria empresa).
            # Embarcacao de OUTRA empresa e' recusada — vinculo nao amplia empresa.
            uid = rota[len("/api/usuarios/"):-len("/embarcacoes")].strip("/")
            if not (u and u["papel"] == "admin"):
                return self._json(401, {"erro": "so o administrador do sistema"})
            d = self._corpo()
            ids = d.get("embarcacao_ids")
            if not isinstance(ids, list):
                return self._json(422, {"erro": "mande `embarcacao_ids` (lista; vazia = todas da empresa)"})
            ids = sorted({str(i).strip() for i in ids if str(i).strip()})
            with conexao() as c:
                alvo = c.execute("SELECT id,email,nome,papel,cliente_id FROM usuarios WHERE id=?",
                                 (uid,)).fetchone()
                if not alvo:
                    return self._json(404, {"erro": "usuario nao encontrado"})
                if alvo["papel"] != "cliente":
                    return self._json(422, {"erro": "vinculo por embarcacao e' so' do papel cliente",
                                            "papel": alvo["papel"]})
                antes = {r["embarcacao_id"] for r in c.execute(
                    "SELECT embarcacao_id FROM usuario_embarcacoes WHERE usuario_id=?", (uid,)).fetchall()}
                if ids:
                    marcas = ",".join("?" * len(ids))
                    validas = {r["id"] for r in c.execute(
                        f"SELECT id FROM embarcacoes WHERE id IN ({marcas}) AND cliente_id=?",
                        (*ids, alvo["cliente_id"])).fetchall()}
                    fora = [i for i in ids if i not in validas]
                    if fora:
                        return self._json(422, {"erro": "embarcacao nao e' da empresa deste cliente",
                                                "fora": fora})
                c.execute("DELETE FROM usuario_embarcacoes WHERE usuario_id=?", (uid,))
                for i in ids:
                    c.execute("""INSERT OR IGNORE INTO usuario_embarcacoes
                                 (usuario_id,embarcacao_id,concedido_por) VALUES (?,?,?)""",
                              (uid, i, u["email"]))
            depois = set(ids)
            ganhos, perdidos = sorted(depois - antes), sorted(antes - depois)
            if ganhos:
                auditar(u, "escopo_concedido", f"{alvo['email']}:{','.join(ganhos)}", self.client_address[0])
            if perdidos:
                auditar(u, "escopo_revogado", f"{alvo['email']}:{','.join(perdidos)}", self.client_address[0])
            return self._json(200, {"ok": True, "vinculos": len(depois), "concedidas": sorted(depois),
                                    "ganhos": ganhos, "perdidos": perdidos})
        if rota.startswith("/api/usuarios/") and rota.endswith("/senha"):
            # Redefinir senha pelo administrador: a senha nova vale no banco local E no Supabase.
            # E' o conserto de quem foi criado antes desta correcao (senha so' local -> 401 no login).
            if not (u and u["papel"] == "admin"):
                return self._json(401, {"erro": "so o administrador do sistema"})
            uid = rota[len("/api/usuarios/"):-len("/senha")]
            with conexao() as c:
                alvo = c.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
            if not alvo:
                return self._json(404, {"erro": "usuario inexistente"})
            senha = secrets.token_urlsafe(9)
            salt = secrets.token_hex(16)
            with conexao() as c:
                c.execute("UPDATE usuarios SET senha_hash=?, salt=?, interacoes=200000 WHERE id=?",
                          (hash_senha(senha, salt), salt, uid))
            supabase = self._provisionar_no_supabase(alvo["email"], senha, alvo["nome"])
            auditar(u, "redefinir_senha", alvo["email"], self.client_address[0])
            return self._json(200, {"id": uid, "email": alvo["email"], "senha_nova": senha,
                                    "supabase": supabase})
        if rota.startswith("/api/usuarios/") and rota.endswith("/ativo"):
            if not (u and u["papel"] == "admin"):
                return self._json(401, {"erro": "so o administrador do sistema"})
            uid = rota[len("/api/usuarios/"):-len("/ativo")]
            novo = 1 if self._corpo().get("ativo", True) else 0
            with conexao() as c:
                if not c.execute("SELECT 1 FROM usuarios WHERE id=?", (uid,)).fetchone():
                    return self._json(404, {"erro": "usuario inexistente"})
                c.execute("UPDATE usuarios SET ativo=? WHERE id=?", (novo, uid))
                if not novo:
                    c.execute("DELETE FROM sessoes WHERE usuario_id=?", (uid,))
            auditar(u, "ativar_usuario" if novo else "desativar_usuario", uid, self.client_address[0])
            return self._json(200, {"id": uid, "ativo": bool(novo)})
        if rota == "/api/clientes":
            # D4 (dono, 25/11/2026): cadastrar/editar empresa e' do ADMIN.
            if not pode_configurar(u):
                return self._json(401, {"erro": "so' o admin cadastra empresa"})
            d = self._corpo()
            faltando = [k for k in ("id", "nome") if not str(d.get(k, "")).strip()]
            if faltando:
                return self._json(422, {"erro": "cliente incompleto", "campos_faltando": faltando})
            with conexao() as c:
                ja = c.execute("SELECT nome FROM clientes WHERE id=?", (d["id"],)).fetchone()
                if ja:
                    # recadastrar o mesmo cliente com o mesmo nome nao e erro (a tela pode reenviar);
                    # trocar o nome de um identificador ja usado e que e conflito
                    if str(ja["nome"]).strip() == str(d["nome"]).strip():
                        return self._json(200, {"id": d["id"], "nome": d["nome"], "ja_existia": True})
                    return self._json(409, {"erro": "cliente ja existe com outro nome"})
                c.execute("INSERT INTO clientes (id,nome) VALUES (?,?)", (d["id"], d["nome"]))
            auditar(u, "criar_cliente", d["id"], self.client_address[0])
            return self._json(201, {"id": d["id"], "nome": d["nome"]})
        if rota == "/api/embarcacoes":
            # D4 (dono, 25/11/2026): cadastrar embarcacao e' do ADMIN.
            if not pode_configurar(u):
                return self._json(401, {"erro": "so' o admin cadastra embarcacao"})
            d = self._corpo()
            faltando = [k for k in ("id", "cliente_id", "nome") if not str(d.get(k, "")).strip()]
            if faltando:
                return self._json(422, {"erro": "embarcacao incompleta", "campos_faltando": faltando})
            with conexao() as c:
                if not c.execute("SELECT 1 FROM clientes WHERE id=?", (d["cliente_id"],)).fetchone():
                    return self._json(422, {"erro": "cliente_id inexistente"})
                if c.execute("SELECT 1 FROM embarcacoes WHERE id=?", (d["id"],)).fetchone():
                    return self._json(409, {"erro": "embarcacao ja existe"})
                c.execute("INSERT INTO embarcacoes (id,cliente_id,nome,imo,estado) VALUES (?,?,?,?,?)",
                          (d["id"], d["cliente_id"], d["nome"], d.get("imo", ""), d.get("estado", "em operacao")))
            auditar(u, "criar_embarcacao", d["id"], self.client_address[0])
            return self._json(201, {"id": d["id"]})
        if rota.startswith("/api/clientes/") and rota.endswith("/editar"):
            # EDITAR EMPRESA (dono, 25/11/2026, verbatim: "nao vejo onde editar as cameras,
            # embarcacoes e clientes"). Nome e IDENTIFICADOR — D3 = "renomeavel", com a transacao nos
            # filhos (`renomear_identificador`). A trilha de auditoria guarda de -> para.
            if not pode_configurar(u):
                return self._json(403, {"erro": "so' o admin edita empresa"})
            cid = rota[len("/api/clientes/"):-len("/editar")]
            d = self._corpo()
            with conexao() as c:
                linha = c.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
            if not linha:
                return self._json(404, {"erro": "empresa inexistente"})
            mudou, id_original = [], cid
            nome = str(d.get("nome") or "").strip()
            if nome and nome != str(linha["nome"] or "").strip():
                with conexao() as c:
                    c.execute("UPDATE clientes SET nome=? WHERE id=?", (nome, cid))
                mudou.append("nome")
            id_novo = str(d.get("id_novo") or d.get("novo_id") or "").strip()
            if id_novo and id_novo != cid:
                r = renomear_identificador("clientes", cid, id_novo)
                if not r.get("ok"):
                    return self._json(404 if r.get("nao_encontrado") else 422, r)
                cid = str(r["id"])
                mudou.append("id")
            if not mudou:
                return self._json(200, {"ok": True, "id": cid, "mudou": [],
                                        "observacao": "nada a mudar (nome igual e identificador igual)"})
            auditar(u, "editar_cliente", f"{id_original} -> {cid} [{','.join(mudou)}]",
                    self.client_address[0])
            return self._json(200, {"ok": True, "id": cid, "de": id_original, "mudou": mudou})
        if rota.startswith("/api/embarcacoes/") and rota.endswith("/editar"):
            # EDITAR EMBARCACAO: nome, IMO, vinculo com a empresa e o proprio identificador (D3).
            if not pode_configurar(u):
                return self._json(403, {"erro": "so' o admin edita embarcacao"})
            eid = rota[len("/api/embarcacoes/"):-len("/editar")]
            d = self._corpo()
            with conexao() as c:
                linha = c.execute("SELECT * FROM embarcacoes WHERE id=?", (eid,)).fetchone()
            if not linha:
                return self._json(404, {"erro": "embarcacao inexistente"})
            mudou, id_original = [], eid
            campos = {}
            for chave in ("nome", "imo", "estado"):
                if chave in d:
                    campos[chave] = str(d.get(chave) or "").strip()
            if "nome" in campos and not campos["nome"]:
                return self._json(422, {"erro": "nome da embarcacao nao pode ficar vazio"})
            cliente_novo = str(d.get("cliente_id") or "").strip()
            if cliente_novo:
                with conexao() as c:
                    if not c.execute("SELECT 1 FROM clientes WHERE id=?", (cliente_novo,)).fetchone():
                        return self._json(422, {"erro": "cliente_id inexistente"})
                campos["cliente_id"] = cliente_novo
            if campos:
                sets = ", ".join(f"{k}=?" for k in campos)
                with conexao() as c:
                    c.execute(f"UPDATE embarcacoes SET {sets} WHERE id=?", (*campos.values(), eid))
                mudou.extend(sorted(campos))
            id_novo = str(d.get("id_novo") or d.get("novo_id") or "").strip()
            if id_novo and id_novo != eid:
                r = renomear_identificador("embarcacoes", eid, id_novo)
                if not r.get("ok"):
                    return self._json(404 if r.get("nao_encontrado") else 422, r)
                eid = str(r["id"])
                mudou.append("id")
            if not mudou:
                return self._json(200, {"ok": True, "id": eid, "mudou": [], "observacao": "nada a mudar"})
            auditar(u, "editar_embarcacao", f"{id_original} -> {eid} [{','.join(mudou)}]",
                    self.client_address[0])
            return self._json(200, {"ok": True, "id": eid, "de": id_original, "mudou": mudou})
        if rota == "/api/varredura":
            # VARRER AGORA (botao da tela do bordo). Mesma regra do cadastro de camera: operacao/admin,
            # ou o usuario do PC de captura NA PROPRIA maquina (a varredura so' faz sentido onde a camera
            # esta' plugada). Cliente nao varre. A varredura nao mexe na configuracao do admin.
            #
            # 23/11/2026: a maquina de captura passou a ser AUTONOMA (nao ha login nela — "no pc de
            # captura ninguém precisa abrir nada"), entao a PROPRIA maquina de captura pede a varredura
            # por loopback, sem sessao: e' a mesma maquina que varre, nunca uma maquina de fora.
            if not ((u and u["papel"] in PAPEL_ADMIN)
                    or (u and u["papel"] in ("tecnico", "captura") and self._local())
                    or self._maquina_de_captura()):
                return self._json(401, {"erro": "entre no sistema"})
            import varredura_do_bordo
            r = varredura_do_bordo.varrer()
            return self._json(200 if r.get("ok") else 422, r)
        if rota == "/api/cameras/anuncio":
            return self._anuncio_bordo()
        if rota == "/api/qualidade/anuncio":
            return self._anuncio_qualidade()
        if rota == "/api/envios/anuncio":
            # o bordo DECLARA os numeros do envio que esta' no ar (lado "declarado" do atestado)
            return self._anuncio_envio()
        if rota == "/api/cameras":
            # Quem cadastra: (a) o ADMIN em terra (`pode_configurar` — D4 do dono, 25/11/2026: "so'
            # admin"); (b) a PROPRIA maquina de captura DECLARADA e ativada (`_maquina_de_captura` — o
            # painel do bordo e' servido pelo bordo, SEM login: dono 23/11/2026 "no pc de captura ninguem
            # precisa abrir nada" e 25/11/2026 "o cadastro das cameras ip terao que ser no app de
            # captura"); (c) o usuario de CAPTURA na PROPRIA maquina (papel + loopback). Loopback SEM
            # declaracao (o servidor de terra rodando na mesma maquina) NAO basta: um observador remoto
            # continua recusado, mesmo que fale por 127.0.0.1.
            if not (pode_configurar(u) or self._maquina_de_captura()
                    or (u and u["papel"] in ("tecnico", "captura") and self._local())):
                return self._json(401, {"erro": "entre no sistema"})
            d = self._corpo()
            # CREDENCIAL DE CAMERA NUNCA ENTRA NO CADASTRO. Dono (25/11/2026): "senha nao pode vazar,
            # entao tem que tudo ficar no bordo". Recusar aqui e' o que garante que a senha nao tem
            # como ser gravada no banco nem publicada no lado terra, mesmo por engano de quem chama.
            for proibido in ("senha", "password", "passwd", "pwd", "segredo", "credencial"):
                if proibido in d:
                    return self._json(422, {
                        "erro": ("a SENHA da camera nao entra no cadastro: o segredo fica no arquivo "
                                 "local do PC de captura (segredo_camera), nunca no banco nem no lado terra"),
                        "onde_por_o_segredo": str(segredo_camera.caminho(str(d.get("id") or "cam"))),
                        "formato": "uma linha `usuario:senha` no arquivo acima, no PC de captura"})
            # identificador derivado do fluxo: menos campo para o dono preencher
            if not str(d.get("id", "")).strip():
                d["id"] = re.sub(r"[^a-zA-Z0-9_\\-]", "-", str(d.get("fluxo_id", "")).strip())
            d["rotulo"] = str(d.get("rotulo") or d.get("fluxo_id", "")).strip()
            ip = str(d.get("ip") or "").strip()
            porta = str(d.get("porta") or "").strip()
            entrada = str(d.get("entrada") or ("rede" if ip else "usb")).strip().lower()
            if entrada not in ("usb", "rede"):
                return self._json(422, {"erro": "entrada invalida: use 'usb' (dshow/HDMI) ou 'rede' (IP)"})
            # TIPO da camera (dono, 25/11/2026): 'camera' | 'radar' | 'flir'. E' o que decide o que o
            # observador (Petrobras/IBAMA) ve. Sem informar, o nome decide — o mesmo criterio de antes,
            # para o cadastro que ja' existe continuar funcionando.
            tipo = str(d.get("tipo") or "").strip().lower()
            if tipo not in ("", "camera", "radar", "flir"):
                return self._json(422, {"erro": "tipo invalido: use 'camera', 'radar' ou 'flir'"})
            if not tipo:
                nome_cam = " ".join(str(x or "") for x in (
                    d.get("id"), d.get("rotulo"), d.get("fluxo_id"),
                    d.get("local"), d.get("alvo"))).lower()
                tipo = "flir" if "flir" in nome_cam else ("radar" if "radar" in nome_cam else "camera")
            if ip and not self._local():
                # D1 do dono (25/11/2026): "nao vamos poder inserir nem o ip no admin, o cadastro das
                # cameras ip terao que ser no app de captura". O endereco so' entra por aqui a partir
                # da PROPRIA maquina de captura (loopback) — nunca pelo navegador do admin.
                return self._json(422, {"erro": ("o endereco da camera (IP) e' cadastrado NO PC DE CAPTURA, "
                                                 "nao no admin: quem aponta para o IP e' o app de captura")})
            if entrada == "rede" and not ip:
                return self._json(422, {"erro": "camera de rede sem IP: informe o endereco no PC de captura"})
            if ip and not re.match(r"^[0-9a-zA-Z.:\-]{3,64}$", ip):
                return self._json(422, {"erro": "ip invalido"})
            if porta and not (porta.isdigit() and 1 <= int(porta) <= 65535):
                return self._json(422, {"erro": "porta invalida"})
            faltando = [k for k in ("id", "rotulo", "fluxo_id") if not str(d.get(k, "")).strip()]
            if faltando:
                return self._json(422, {"erro": "camera incompleta", "campos_faltando": faltando})
            with conexao() as c:
                if not str(d.get("embarcacao_id", "")).strip():
                    linha = c.execute("SELECT id FROM embarcacoes ORDER BY id LIMIT 1").fetchone()
                    if not linha:
                        return self._json(422, {"erro": "cadastre uma embarcacao primeiro"})
                    d["embarcacao_id"] = linha["id"]
                elif not c.execute("SELECT 1 FROM embarcacoes WHERE id=?", (d["embarcacao_id"],)).fetchone():
                    return self._json(422, {"erro": "embarcacao_id inexistente"})
                dispositivo = str(d.get("dispositivo") or "").strip()
                if dispositivo:
                    # dispositivo local desta maquina: e' o que permite LIGAR a camera sem envio de teste
                    c.execute("""INSERT INTO config_local (camera_id,chave,valor,versao,atualizado_em)
                                 VALUES (?,?,?,0,?)
                                 ON CONFLICT(camera_id,chave) DO UPDATE SET valor=excluded.valor,
                                   atualizado_em=excluded.atualizado_em""",
                              (d["id"], "dispositivo", dispositivo, em_iso()))
                # ENTRADA da camera (usb|rede) FICA NESTA MAQUINA: e' o que a tela do bordo e o agente
                # leem para saber se abrem o dshow ou apontam para o RTSP do cadastro local.
                c.execute("""INSERT INTO config_local (camera_id,chave,valor,versao,atualizado_em)
                             VALUES (?,?,?,0,?)
                             ON CONFLICT(camera_id,chave) DO UPDATE SET valor=excluded.valor,
                               atualizado_em=excluded.atualizado_em""",
                          (d["id"], "entrada", entrada, em_iso()))
                c.execute("""INSERT OR REPLACE INTO cameras
                             (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                             VALUES (?,?,?,?,?,1,?,?,?,?,?,?)""",
                          (d["id"], d["embarcacao_id"], d["rotulo"], d["fluxo_id"], d.get("local", ""),
                           ip, porta, str(d.get("protocolo") or "rtsp"), str(d.get("canal") or ""),
                           str(d.get("alvo") or ""), tipo))
            # ESPELHO NO BANCO (Fase 1, 0.8.0): o cadastro TAMBEM vai para o Supabase, que e' a base de
            # verdade do dono. So' o lado terra tem a chave de servico; falha aqui NAO impede cadastrar
            # nesta maquina (o SQLite e' o banco de operacao), mas aparece na resposta e em /api/saude.
            try:
                import supabase_escrita
                with conexao() as c:
                    nome_emb = c.execute("SELECT nome FROM embarcacoes WHERE id=?",
                                         (d["embarcacao_id"],)).fetchone()
                espelho = supabase_escrita.espelhar(dict(d, ativo=1,
                                                         embarcacao_nome=(nome_emb["nome"] if nome_emb else "")))
            except Exception as e:  # noqa: BLE001
                espelho = {"ok": False, "motivo": f"{type(e).__name__}: {e}"}
            auditar(u, "criar_camera", (d["id"] + " " + ip + ":" + porta).strip(": ")
                    + ("" if espelho.get("ok") else " [banco: NAO]"), self.client_address[0])
            # Publica o CADASTRO no lado terra na hora: a tela do cliente vive no lado terra, e ate'
            # aqui a camera so' chegava la' quando o fluxo subia ("cadastrei cam-01 aqui e o cliente
            # nao mostra nada"). Vai so' id/rotulo/fluxo/ativo — sem endereco nem credencial.
            lado = {"ok": False, "motivo": "nao tentei"}
            try:
                import repasse
                lado = repasse.publicar_cadastro({"id": d["id"], "fluxo_id": d["fluxo_id"],
                                                  "rotulo": d["rotulo"], "embarcacao_id": d["embarcacao_id"],
                                                  "ativo": 1})
            except Exception as e:
                lado = {"ok": False, "motivo": f"{type(e).__name__}: {e}"}
            resposta = {"id": d["id"], "ip": ip, "porta": porta, "entrada": entrada,
                        "lado_terra": lado, "supabase": espelho}
            if entrada == "rede":
                # a tela do bordo precisa saber se JA' tem segredo configurado (nunca o valor)
                resposta["segredo"] = estado_do_segredo(str(d["id"]))
            return self._json(201, resposta)
        if rota.startswith("/api/cameras/") and rota.endswith("/segredo"):
            # ESTADO DO SEGREDO da camera de rede (nunca o valor). So' a PROPRIA maquina de captura
            # (loopback) ou admin: o caminho do arquivo e' informacao de operacao do bordo.
            if not (self._local() or pode_configurar(u)):
                return self._json(403, {"erro": "so' a maquina de captura ve o estado do segredo"})
            cid = rota[len("/api/cameras/"):-len("/segredo")]
            with conexao() as c:
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone()
            if not cam:
                return self._json(404, {"erro": "camera inexistente"})
            e = estado_do_segredo(cid)
            e.update({"id": cid, "entrada": ("rede" if str(cam["ip"] or "").strip() else "usb"),
                      "aponta_para": ingestao_modulo.endereco_da_camera(cam)})
            return self._json(200, e, {"Cache-Control": "no-store"})
        if rota == "/api/cameras/publicar":
            # Forca a publicacao do cadastro das cameras DESTA maquina no lado terra. E' o que a tela
            # usa quando a camera ja' existia aqui antes (registrada quando a publicacao automatica
            # ainda nao existia) e o cliente nao mostra nada.
            if not (u and u["papel"] in PAPEL_ADMIN) and not self._local():
                return self._json(401, {"erro": "entre no sistema"})
            import repasse
            with conexao() as c:
                cams = [dict(x) for x in c.execute("SELECT * FROM cameras ORDER BY id")]
            enviadas, falhas = [], []
            for cam in cams:
                r = repasse.publicar_cadastro(cam)
                (enviadas if r.get("ok") else falhas).append(cam["id"])
            # E o mesmo botao tambem POE O CADASTRO NO BANCO (Supabase) — e' o que faz a tabela do
            # dono sair de 1 linha para o cadastro real, sem ele rodar script nenhum.
            no_banco, sem_banco = [], []
            try:
                import supabase_escrita
                for cam in cams:
                    r = supabase_escrita.espelhar(cam)
                    (no_banco if r.get("ok") else sem_banco).append(cam["id"])
            except Exception as e:  # noqa: BLE001
                sem_banco = [f"modulo indisponivel ({type(e).__name__}: {e})"]
            auditar(u, "publicar_cadastro_cameras", f"{len(enviadas)} ok / {len(falhas)} falha",
                    self.client_address[0])
            return self._json(200, {"ok": not falhas, "publicadas": enviadas, "falharam": falhas,
                                    "no_banco": no_banco, "fora_do_banco": sem_banco})
        if rota.startswith("/api/cameras/") and rota.endswith("/remover"):
            # Tirar da operacao a camera que nao e' mais usada: para o envio dela, apaga o cadastro
            # AQUI e publica a remocao no lado terra — senao a camera fica para sempre no app do
            # cliente (desativar escondia, mas o cadastro continuava). Trechos e auditoria ficam.
            # D4 (dono, 25/11/2026): remover cadastro de camera e' do ADMIN — ou da PROPRIA maquina de
            # captura DECLARADA e ativada (o painel do bordo remove o cadastro que ele mesmo criou).
            if not (pode_configurar(u) or self._maquina_de_captura()):
                return self._json(403, {"erro": "so' o admin remove camera (D4 de 25/11/2026)"})
            cid = rota[len("/api/cameras/"):-len("/remover")]
            with conexao() as c:
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone()
            if not cam:
                return self._json(404, {"erro": "camera inexistente"})
            parado = ing_desligar_camera(cid)
            with conexao() as c:
                c.execute("DELETE FROM cameras WHERE id=?", (cid,))
            # o cadastro sai do Supabase junto (senao a camera fica no banco depois de sumir da tela)
            try:
                import supabase_escrita
                banco = supabase_escrita.espelhar({"id": cid}, remover=True)
            except Exception as e:  # noqa: BLE001
                banco = {"ok": False, "motivo": f"{type(e).__name__}: {e}"}
            lado = {"ok": False, "motivo": "nao tentei"}
            try:
                import repasse
                lado = repasse.publicar_cadastro({"id": cam["id"], "fluxo_id": cam["fluxo_id"],
                                                  "rotulo": cam["rotulo"], "ativo": 0,
                                                  "embarcacao_id": cam["embarcacao_id"]}, remover=True)
            except Exception as e:
                lado = {"ok": False, "motivo": f"{type(e).__name__}: {e}"}
            auditar(u, "remover_camera", f"{cid} ({cam['fluxo_id']})", self.client_address[0])
            return self._json(200, {"ok": True, "id": cid, "fluxo_id": cam["fluxo_id"],
                                    "envio_parado": bool((parado or {}).get("ok")),
                                    "lado_terra": lado, "supabase": banco, "trechos_preservados": True})
        if rota.startswith("/api/cameras/") and rota.endswith("/nome"):
            # O NOME da camera (0.12.0, dono 23/11/2026): "a captura pega as informações e replica no
            # app de captura, inclusive os nomes das câmeras". Aqui o nome muda no cadastro do lado
            # terra E desce como a chave `rotulo` da config — o PC de captura aplica e confirma. Sem
            # isto o nome vivia so' aqui: o bordo continuava com o nome do dispositivo e a varredura
            # seguinte reescrevia o rotulo por cima.
            # D4 (dono, 25/11/2026): dar nome ao cadastro da camera e' do ADMIN.
            if not pode_configurar(u):
                return self._json(403, {"erro": "so' o admin da' nome a camera (D4 de 25/11/2026)"})
            cid = rota[len("/api/cameras/"):-len("/nome")]
            d = self._corpo()
            nome = str(d.get("rotulo") or "").strip()
            with conexao() as c:
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone()
            if not cam:
                return self._json(404, {"erro": "camera inexistente"})
            publicado = publicar_config(cam["embarcacao_id"], cid, CHAVE_NOME_CAMERA, nome,
                                        origem=(u["email"] if u else ""))
            if publicado.get("erro"):
                return self._json(422, publicado)
            with conexao() as c:
                c.execute("UPDATE cameras SET rotulo=? WHERE id=?", (nome, cid))
            auditar(u, "nome_da_camera", f"{cid} -> {nome!r} (v{publicado.get('versao')})",
                    self.client_address[0])
            return self._json(200, {"ok": True, "id": cid, "rotulo": nome, "bordo": publicado,
                                    "recado": "nome publicado para o PC de captura: ele aplica e "
                                              "confirma na proxima leitura"})
        if rota.startswith("/api/cameras/") and rota.endswith("/editar"):
            # Editar a camera EM OPERACAO, campo a campo. `POST /api/cameras` e' INSERT OR REPLACE
            # (recria a linha e zera `ativo`): serve para criar, nao para editar. Aqui muda SO' o que
            # veio no corpo, sem resetar `ativo`, `alvo` nem o que o cliente ja' ve.
            # D4 (dono, 25/11/2026): editar o CADASTRO da camera e' do ADMIN. Excecoes mantidas: a
            # PROPRIA maquina de captura DECLARADA e ativada (`_maquina_de_captura` — o painel do bordo,
            # servido pelo bordo, SEM login) e o usuario de CAPTURA no loopback — porque e' la' que o
            # endereco da camera de rede e' cadastrado (dono: "o cadastro das cameras ip terao que ser no
            # app de captura").
            if not (pode_configurar(u) or self._maquina_de_captura()
                    or (u and u["papel"] in ("tecnico", "captura") and self._local())):
                return self._json(403, {"erro": "so' o admin edita camera (ou a propria maquina de captura)"})
            cid = rota[len("/api/cameras/"):-len("/editar")]
            d = self._corpo()
            campos, mudados = {}, []
            with conexao() as c:
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone()
                if not cam:
                    return self._json(404, {"erro": "camera inexistente"})
                for chave in ("rotulo", "embarcacao_id", "ip", "porta", "protocolo", "canal", "fluxo_id"):
                    if chave not in d:
                        continue
                    if chave in ("ip", "porta", "protocolo", "canal") and not self._local():
                        # D1 do dono (25/11/2026): "nao vamos poder inserir nem o ip no admin".
                        return self._json(422, {"erro": ("o endereco da camera (ip/porta/canal) e' cadastrado "
                                                         "NO PC DE CAPTURA: o admin nao poe endereco de camera")})
                    valor = str(d.get(chave) or "").strip()
                    if chave == "rotulo" and not valor:
                        return self._json(422, {"erro": "rotulo nao pode ficar vazio"})
                    if chave == "ip" and valor and not re.match(r"^[0-9a-zA-Z.:\-]{3,64}$", valor):
                        return self._json(422, {"erro": "ip invalido"})
                    if chave == "porta" and valor and not (valor.isdigit() and 1 <= int(valor) <= 65535):
                        return self._json(422, {"erro": "porta invalida"})
                    if chave == "fluxo_id":
                        valor = re.sub(r"[^a-zA-Z0-9_\-]", "-", valor)
                    if valor != str(cam[chave] or ""):
                        campos[chave] = valor
                        mudados.append(chave)
                if not mudados:
                    return self._json(200, {"ok": True, "id": cid, "mudou": [],
                                            "observacao": "nada a mudar"})
                if campos.get("embarcacao_id") and not c.execute(
                        "SELECT 1 FROM embarcacoes WHERE id=?", (campos["embarcacao_id"],)).fetchone():
                    return self._json(422, {"erro": "embarcacao_id inexistente"})
                c.execute("UPDATE cameras SET " + ", ".join(f"{k}=?" for k in campos) + " WHERE id=?",
                          (*campos.values(), cid))
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone()
            # mexer na FONTE (endereco/porta/canal/fluxo) so' vale no ar se reabrir; rotulo nao mexe no video
            fonte_mudou = any(k in mudados for k in ("ip", "porta", "protocolo", "canal", "fluxo_id"))
            aplicado = (self._reabrir_para_aplicar(cam) if fonte_mudou
                        else {"aplicado": False, "motivo": "nao mexe na fonte: o video em curso segue"})
            auditar(u, "editar_camera", f"{cid} " + ",".join(mudados), self.client_address[0])
            try:
                import repasse
                repasse.publicar_cadastro({"id": cam["id"], "fluxo_id": cam["fluxo_id"],
                                           "rotulo": cam["rotulo"], "ativo": cam["ativo"],
                                           "embarcacao_id": cam["embarcacao_id"]})
            except Exception:
                pass
            return self._json(200, {"ok": True, "id": cid, "mudou": mudados, **aplicado})
        if rota.startswith("/api/cameras/") and rota.endswith("/alvo"):
            # Alvo de bitrate POR CAMERA: e' o ajuste que o dono escolhe olhando a imagem (ou o que a
            # sugestao da tela propõe quando o SSIM fica abaixo do piso). A lista e' FECHADA
            # (`ALVOS_DE_QUALIDADE`): 1500k/1200k/1000k/800k/500k/300k, e a escolha vale NO AR (a
            # camera e' reaberta com o alvo novo). Abaixo do piso o sistema so' avisa, nao recusa.
            # sem excecao de "chamada local": o app do CLIENTE pode estar na mesma maquina do lado
            # terra (correcao do dono: "operacao e admin sao iguais") e nao pode escolher qualidade
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(403, {"erro": "so a operacao define o alvo da camera"})
            cid = rota[len("/api/cameras/"):-len("/alvo")]
            alvo = str(self._corpo().get("alvo") or "").strip()
            if alvo and alvo not in self.ALVOS_DE_QUALIDADE:
                return self._json(422, {"erro": "alvo fora da lista de qualidade (so avisa, nao recusa: "
                                               "abaixo do piso o sistema mede e avisa)",
                                        "alvos": list(self.ALVOS_DE_QUALIDADE)})
            with conexao() as c:
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone()
                if not cam:
                    return self._json(404, {"erro": "camera inexistente"})
                c.execute("UPDATE cameras SET alvo=? WHERE id=?", (alvo, cid))
            aplicado = (self._reabrir_para_aplicar(cam) if alvo
                        else {"aplicado": False, "motivo": "sem alvo: a camera volta ao padrao da tela"})
            auditar(u, "definir_alvo_camera", f"{cid} alvo={alvo or 'padrao'} ({aplicado.get('motivo', '')})",
                    self.client_address[0])
            return self._json(200, {"id": cid, "alvo": alvo, "alvos": list(self.ALVOS_DE_QUALIDADE),
                                    **aplicado})
        if rota.startswith("/api/cameras/") and rota.endswith("/ativo"):
            # D4 (dono, 25/11/2026): o ATIVO da camera e' cadastro — quem mexe e' o ADMIN.
            if not pode_configurar(u):
                return self._json(401, {"erro": "so' o admin ativa/desativa camera (D4 de 25/11/2026)"})
            cid = rota[len("/api/cameras/"):-len("/ativo")]
            novo = 1 if self._corpo().get("ativo", True) else 0
            with conexao() as c:
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cid,)).fetchone()
                if not cam:
                    return self._json(404, {"erro": "camera inexistente"})
                c.execute("UPDATE cameras SET ativo=? WHERE id=?", (novo, cid))
            auditar(u, "ativar_camera" if novo else "desativar_camera", cid, self.client_address[0])
            # Desativar/reativar aqui tambem vale no lado terra: senao o cliente continua vendo a
            # camera que o operador acabou de desligar nesta maquina.
            lado = {"ok": False, "motivo": "nao tentei"}
            try:
                import repasse
                lado = repasse.publicar_cadastro({"id": cam["id"], "fluxo_id": cam["fluxo_id"],
                                                  "rotulo": cam["rotulo"],
                                                  "embarcacao_id": cam["embarcacao_id"], "ativo": novo})
            except Exception as e:
                lado = {"ok": False, "motivo": f"{type(e).__name__}: {e}"}
            return self._json(200, {"id": cid, "ativo": bool(novo), "lado_terra": lado})
        if rota == "/api/transmissao/iniciar":
            # O CLIENTE abre a transmissao pela web. A ordem nasce AQUI e vai ao bordo.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            if not self._papel_cliente(u):
                return self._json(403, {"erro": "quem inicia a transmissao e' o cliente"})
            d = self._corpo()
            cam_id = str(d.get("camera_id") or "").strip()
            if not cam_id:
                return self._json(422, {"erro": "escolha a camera"})
            with conexao() as c:
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cam_id,)).fetchone()
            if not cam:
                return self._json(404, {"erro": "camera nao encontrada"})
            if not cam["ativo"]:
                return self._json(422, {"erro": "esta camera esta desativada"})
            if not pode_ver_camera(u, cam):
                return self._json(403, {"erro": "esta camera nao e' da sua empresa"})
            seg_bruto = d.get("segundos_max")
            seg = self._tempo_do_cliente(u["id"]) if seg_bruto in (None, "") else seg_bruto
            try:
                seg = int(seg)
            except Exception:
                return self._json(422, {"erro": f"tempo invalido; escolha um de {list(TEMPOS_DE_TRANSMISSAO)}"})
            if seg not in TEMPOS_DE_TRANSMISSAO:
                return self._json(422, {"erro": f"tempo fora da lista; escolha um de {list(TEMPOS_DE_TRANSMISSAO)}"})
            seg, cortado_pelo_teto = aplicar_teto_do_produto(seg)   # o teto do produto manda na lista do cliente
            fixado = tempo_maximo_do_produto()
            if fixado:
                # dono (19/11/2026): "todas as configuracoes serao feitas por mim (admin)". O tempo da
                # sessao e' FIXADO pelo admin — o que o cliente escolheu na tela nao vale aqui.
                if seg != fixado:
                    cortado_pelo_teto = True
                seg = fixado
            with conexao() as c:
                _man = c.execute("SELECT manual FROM desejo_camera WHERE camera_id=?",
                                 (cam_id,)).fetchone()
            if _man and (_man["manual"] or "") == "parar":
                # A OPERACAO desligou esta camera na mao (stand-by): a sessao do cliente NAO fura isso
                # (dono, 24/11/2026). Antes o `/iniciar` apagava o override e a transmissao subia por
                # cima da decisao do operador — agora o desligar manual vale.
                return self._json(409, {"erro": "a operacao desligou esta camera na mao — fale com a "
                                                "operacao LECSOR para liberar"})
            aberta = self._transmissao_aberta(u["email"], cam_id)
            if aberta:
                # pedir de novo o que ja' esta' aberto nao abre uma segunda sessao (a tela pode
                # reenviar o clique sem medo)
                return self._json(200, {"ok": True, "ja_aberta": True,
                                        "transmissao": self._json_transmissao(aberta)},
                                  {"Cache-Control": "no-store"})
            agora = dt.datetime.now(dt.timezone.utc)
            tid = secrets.token_hex(8)
            termina = (agora + dt.timedelta(seconds=seg)).isoformat(timespec="seconds")
            carimbo = em_iso(agora)
            with conexao() as c:
                seq = c.execute("SELECT COALESCE(MAX(seq),0)+1 AS s FROM transmissoes").fetchone()["s"]
                c.execute("""INSERT INTO transmissoes
                             (id,seq,embarcacao_id,camera_id,fluxo_id,usuario_email,segundos_max,
                              criada_em,batimento_em,termina_em,estado,motivo)
                             VALUES (?,?,?,?,?,?,?,?,?,?,'pedida','')""",
                          (tid, seq, cam["embarcacao_id"], cam_id, cam["fluxo_id"], u["email"],
                           seg, carimbo, carimbo, termina))
                linha = c.execute("SELECT * FROM transmissoes WHERE id=?", (tid,)).fetchone()
                # D3 (dono, 24/11/2026): o override manual de LIGAR deixou de existir; se sobrou um
                # 'ligar' de versao antiga, ele sai de cena (a sessao passa a sustentar o "ligar"). O
                # 'parar' da operacao NAO se apaga aqui (o cliente nem chega: o 409 acima barra antes).
                c.execute("UPDATE desejo_camera SET manual='' WHERE camera_id=? AND manual='ligar'", (cam_id,))
            ordem = enfileirar_ordem(cam["embarcacao_id"], cam_id, cam["fluxo_id"], "iniciar",
                                     f"pedido do cliente {u['email']}", tid)
            auditar(u, "transmissao_pedida", f"{cam_id} ({texto_do_tempo(seg)})", self.client_address[0])
            return self._json(201, {"ok": True, "transmissao": self._json_transmissao(linha),
                                    "cortado_pelo_teto_do_produto": bool(cortado_pelo_teto),
                                    "ordem": ordem}, {"Cache-Control": "no-store"})
        if rota.startswith("/api/transmissao/") and rota.endswith("/batimento"):
            # "estou aqui": enquanto a tela bate, a sessao vive. Sem batimento por
            # SEGUNDOS_SEM_BATIMENTO o lado terra fecha a sessao e manda o bordo parar.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            tid = rota[len("/api/transmissao/"):-len("/batimento")]
            t, erro, codigo = self._transmissao_da_tela(tid, u)
            if codigo:
                return self._json(codigo, {"erro": erro})
            # a tela ESTA' VIVA: se havia um pedido de saida pendente (a pagina recarregou), cai.
            cancelar_saida(u["email"])
            with conexao() as c:
                c.execute("UPDATE transmissoes SET batimento_em=? WHERE id=?", (em_iso(), tid))
            return self._json(200, {"ok": True, "estado": t["estado"], "agora": em_iso()},
                              {"Cache-Control": "no-store"})
        if rota.startswith("/api/transmissao/") and rota.endswith("/continuar"):
            # "Continuar conectado" (dono, 24/11/2026, D1/D2): o cliente viu o aviso do ultimo minuto
            # e quer seguir. Renova a MESMA janela configurada (a lista fechada vale: continuar e' uma
            # nova janela do mesmo tempo, nunca tempo infinito) e zera o relogio do batimento.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            tid = rota[len("/api/transmissao/"):-len("/continuar")]
            t, erro, codigo = self._transmissao_da_tela(tid, u)
            if codigo:
                return self._json(codigo, {"erro": erro})
            if t["estado"] not in ("pedida", "no_ar"):
                return self._json(409, {"erro": "esta transmissao ja' terminou — use Reconectar"})
            cancelar_saida(u["email"])   # o cliente esta' na tela e quer seguir: pedido pendente cai
            seg = int(t["segundos_max"] or 0) or TEMPO_MAXIMO_PADRAO
            agora = dt.datetime.now(dt.timezone.utc)
            termina = (agora + dt.timedelta(seconds=seg)).isoformat(timespec="seconds")
            with conexao() as c:
                c.execute("UPDATE transmissoes SET termina_em=?, batimento_em=? WHERE id=?",
                          (termina, em_iso(agora), tid))
                linha = c.execute("SELECT * FROM transmissoes WHERE id=?", (tid,)).fetchone()
            auditar(u, "transmissao_continuada", f"{t['camera_id']} ({texto_do_tempo(seg)})",
                    self.client_address[0])
            return self._json(200, {"ok": True, "transmissao": self._json_transmissao(linha)},
                              {"Cache-Control": "no-store"})
        if rota.startswith("/api/transmissao/") and rota.endswith("/encerrar"):
            # Fechou a tela/navegador ou clicou em parar. Aceita corpo vazio (o aviso do
            # `sendBeacon` ao fechar a pagina nao e' JSON).
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            tid = rota[len("/api/transmissao/"):-len("/encerrar")]
            t, erro, codigo = self._transmissao_da_tela(tid, u)
            if codigo:
                return self._json(codigo, {"erro": erro})
            if self._corpo().get("pendente"):
                # veio do `pagehide` (pode ser RECARGA): fica pendente pela carencia e a pagina
                # recarregada cancela no primeiro batimento (`cancelar_saida`).
                emb = t["embarcacao_id"] if t else ""
                pendurar_saida(u["email"], "encerrar", [tid], emb, self.client_address[0])
                return self._json(200, {"ok": True, "pendente": True, "carencia_s": SEGUNDOS_DE_CARENCIA},
                                  {"Cache-Control": "no-store"})
            fechada = fechar_transmissao(tid, "encerrada", "a transmissao foi encerrada na tela do cliente")
            if fechada:
                parar_se_ninguem_vendo(t["embarcacao_id"], t["camera_id"], t["fluxo_id"],
                                       "nao havia mais ninguem vendo")
                auditar(u, "transmissao_encerrada", f"{t['camera_id']}", self.client_address[0])
            return self._json(200, {"ok": True, "encerrada": bool(fechada)}, {"Cache-Control": "no-store"})
        if rota.startswith("/api/transmissao/") and rota.endswith("/cancelar"):
            # A OPERACAO cancela o pedido do cliente (plano, Fase 2 P1). Quem PEDE e' o cliente; quem
            # cancela por cima e' a operacao/admin — e o HISTORICO guarda quem cancelou.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            if u["papel"] not in PAPEL_ADMIN:
                return self._json(403, {"erro": "quem cancela o pedido e' a operacao"})
            tid = rota[len("/api/transmissao/"):-len("/cancelar")]
            with conexao() as c:
                t = c.execute("SELECT * FROM transmissoes WHERE id=?", (tid,)).fetchone()
            if not t:
                return self._json(404, {"erro": "transmissao nao encontrada"})
            fechada = fechar_transmissao(tid, "cancelada", f"cancelada pela operacao ({u['email']})")
            if not fechada:
                return self._json(200, {"ok": True, "cancelada": False,
                                        "motivo": f"esta transmissao ja' estava {t['estado']}"},
                                  {"Cache-Control": "no-store"})
            parou = parar_se_ninguem_vendo(t["embarcacao_id"], t["camera_id"], t["fluxo_id"],
                                           f"pedido cancelado pela operacao ({u['email']})")
            auditar(u, "transmissao_cancelada", f"{t['camera_id']} de {t['usuario_email']}",
                    self.client_address[0])
            return self._json(200, {"ok": True, "cancelada": True,
                                    "camera_mandada_parar": bool(parou)},
                              {"Cache-Control": "no-store"})
        if rota.startswith("/api/transmissao/") and rota.endswith("/gravando"):
            # GRAVACAO NO LADO TERRA (decisao do dono, 17/11/2026): grava o video que JA' CHEGOU pela
            # rede, aqui na VPS — nao gasta banda do link da embarcacao. Enquanto grava, o corte por
            # TEMPO NAO acontece (a gravacao nao pode ser picada no meio).
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            tid = rota[len("/api/transmissao/"):-len("/gravando")]
            t, erro, codigo = self._transmissao_da_tela(tid, u)
            if codigo:
                return self._json(codigo, {"erro": erro})
            d = self._corpo()
            ligado = str(d.get("gravando", 1)).strip().lower() not in ("0", "false", "nao", "não")
            if ligado:
                r = gravacao_modulo.iniciar(tid, t["fluxo_id"] or t["camera_id"])
                if "erro" in r:
                    # a tela NAO pode dizer "gravando" quando o ffmpeg nao subiu
                    with conexao() as c:
                        c.execute("UPDATE transmissoes SET gravando=0 WHERE id=?", (tid,))
                    return self._json(422, {"erro": r["erro"], "gravando": False})
                with conexao() as c:
                    c.execute("UPDATE transmissoes SET gravando=1 WHERE id=?", (tid,))
                auditar(u, "gravacao_iniciada", f"{t['camera_id']}", self.client_address[0])
                registrar_gravacao_comecou(t)
                return self._json(200, {"ok": True, "gravando": True, "gravacao": r},
                                  {"Cache-Control": "no-store"})
            r = gravacao_modulo.parar(tid)
            with conexao() as c:
                c.execute("UPDATE transmissoes SET gravando=0 WHERE id=?", (tid,))
            auditar(u, "gravacao_parada", f"{t['camera_id']} ({r.get('bytes', 0)} B)",
                    self.client_address[0])
            # a gravacao ACABOU: o arquivo esta' pronto e o cliente passa a ser avisado na tela
            registrar_gravacao_pronta(tid, r)
            return self._json(200, {"ok": True, "gravando": False, "gravacao": r},
                              {"Cache-Control": "no-store"})
        if rota.startswith("/api/gravacoes/") and rota.endswith("/pronto"):
            # "JA' BAIXEI" (dono, 18/11/2026): o cliente confirma o download e o ARQUIVO sai agora — a
            # linha de `gravacoes` e a auditoria ficam (nunca se perde o que foi feito e por quem).
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            tid = rota[len("/api/gravacoes/"):-len("/pronto")].strip("/")
            t, erro, codigo = self._transmissao_da_tela(tid, u)
            if codigo:
                return self._json(codigo, {"erro": erro})
            if u["papel"] == "cliente" and t["usuario_email"] != u["email"]:
                return self._json(403, {"erro": "esta gravacao nao e' sua"})
            r = gravacao_modulo.apagar(tid)
            if r.get("adiado"):
                return self._json(409, {"erro": "tem um download desta gravacao em andamento; "
                                                "tente de novo em instantes", "adiado": True},
                                  {"Cache-Control": "no-store"})
            with conexao() as c:
                c.execute("""UPDATE gravacoes SET apagada_em=? WHERE transmissao_id=?""",
                          (em_iso(), tid))
            auditar(u, "gravacoes_apagadas", f"{t['camera_id']} ({r.get('bytes', 0)} B) "
                                             "— o cliente confirmou o download", self.client_address[0])
            return self._json(200, {"ok": True, "apagada": True, "bytes": r.get("bytes", 0)},
                              {"Cache-Control": "no-store"})
        if rota == "/api/transmissao/sair":
            # O CLIENTE SAIU DA TELA (ou desligou o computador), decisao do dono (18/11/2026): as sessoes
            # dele caem e o que foi gravado para ele e' APAGADO agora. O historico e a auditoria ficam:
            # sempre se sabe quais acoes foram tomadas e por quem (o "nada e' apagado" e' a trilha).
            # A tela chama isto no `pagehide` (sendBeacon) e no botao Sair.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            d = self._corpo()
            emb = str(d.get("embarcacao_id") or "").strip()
            if d.get("pendente"):
                # veio do `pagehide`: pode ser RECARGA — fica pendente e a pagina que voltar cancela.
                pendurar_saida(u["email"], "sair", [], emb, self.client_address[0])
                return self._json(200, {"ok": True, "pendente": True, "carencia_s": SEGUNDOS_DE_CARENCIA},
                                  {"Cache-Control": "no-store"})
            return self._json(200, {"ok": True, **sair_da_tela(u["email"], emb, self.client_address[0],
                                                              u["id"])},
                              {"Cache-Control": "no-store"})
        if rota == "/api/transmissao/teto":
            # TETO DO PRODUTO (plano, Fase 3 P2): so' o ADMINISTRADOR define o maximo que qualquer
            # cliente pode escolher. Zero quer dizer sem teto.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            if u["papel"] != "admin":
                return self._json(403, {"erro": "o teto do produto e' do administrador"})
            d = self._corpo()
            bruto = str(d.get("tempo_maximo_s", "")).strip().lower()
            if bruto in ("0", "", "sem teto", "nenhum", "none"):
                valor = 0
            else:
                try:
                    valor = int(bruto)
                except Exception:
                    return self._json(422, {"erro": f"informe um de {list(TEMPOS_DE_TRANSMISSAO)} "
                                                    f"(segundos) ou 0 para sem teto"})
                if valor not in TEMPOS_DE_TRANSMISSAO:
                    return self._json(422, {"erro": f"teto fora da lista; escolha um de "
                                                    f"{list(TEMPOS_DE_TRANSMISSAO)} ou 0"})
            with conexao() as c:
                c.execute("""INSERT INTO configs_do_produto (chave,valor,atualizado_em)
                             VALUES ('tempo_maximo_do_produto',?,?) ON CONFLICT(chave)
                             DO UPDATE SET valor=excluded.valor, atualizado_em=excluded.atualizado_em""",
                          (str(valor), em_iso()))
            auditar(u, "teto_do_produto_definido", (texto_do_tempo(valor) if valor else "sem teto"),
                    self.client_address[0])
            return self._json(200, {"ok": True, "teto_do_produto_s": valor}, {"Cache-Control": "no-store"})
        if rota == "/api/transmissao/config":
            # Tela de configuracao do cliente: o tempo maximo de cada transmissao.
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            # Com o tempo FIXADO pelo administrador (dono, 19/11/2026), o cliente nao configura nada:
            # o que ele escolher na tela nao vale — entao nao aceitamos a mudanca nem por API.
            fixado = tempo_maximo_do_produto()
            if fixado:
                return self._json(403, {
                    "erro": f"o tempo de transmissao e' definido pelo administrador ({texto_do_tempo(fixado)})",
                    "teto_do_produto_s": fixado, "configuravel": False}, {"Cache-Control": "no-store"})
            d = self._corpo()
            try:
                seg = int(d.get("tempo_maximo_s"))
            except Exception:
                return self._json(422, {"erro": f"informe o tempo em segundos; escolha um de {list(TEMPOS_DE_TRANSMISSAO)}"})
            if seg not in TEMPOS_DE_TRANSMISSAO:
                return self._json(422, {"erro": f"tempo fora da lista; escolha um de {list(TEMPOS_DE_TRANSMISSAO)}"})
            teto = tempo_maximo_do_produto()
            if teto and seg > teto:
                return self._json(422, {"erro": f"o maximo liberado para a sua empresa e' {texto_do_tempo(teto)}",
                                        "teto_do_produto_s": teto})
            with conexao() as c:
                c.execute("""INSERT INTO configs_do_cliente (usuario_id,tempo_maximo_s,atualizado_em)
                             VALUES (?,?,?) ON CONFLICT(usuario_id)
                             DO UPDATE SET tempo_maximo_s=excluded.tempo_maximo_s,
                                           atualizado_em=excluded.atualizado_em""",
                          (u["id"], seg, em_iso()))
            auditar(u, "tempo_de_transmissao_configurado", texto_do_tempo(seg), self.client_address[0])
            return self._json(200, {"ok": True, "tempo_maximo_s": seg}, {"Cache-Control": "no-store"})
        if rota.startswith("/api/ordens/") and rota.endswith("/resultado"):
            # O BORDO conta o que aconteceu com a ordem (abriu? falhou? por que?).
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            oid = rota[len("/api/ordens/"):-len("/resultado")]
            d = self._corpo()
            bruto = str(d.get("estado") or "").strip().lower()
            estado = "atendida" if bruto in ("atendida", "ok", "1", "true", "sim") else "erro"
            resultado = str(d.get("resultado") or d.get("motivo") or "").strip()[:300]
            with conexao() as c:
                o = c.execute("SELECT * FROM ordens_do_bordo WHERE id=?", (oid,)).fetchone()
                if not o:
                    return self._json(404, {"erro": "ordem nao encontrada"})
                c.execute("""UPDATE ordens_do_bordo SET estado=?, atendida_em=?, resultado=?
                             WHERE id=?""", (estado, em_iso(), resultado, oid))
            # a sessao do cliente acompanha: no ar quando abriu, erro quando nao deu.
            if o["transmissao_id"]:
                if estado == "atendida" and o["acao"] == "iniciar":
                    with conexao() as c:
                        c.execute("""UPDATE transmissoes SET estado='no_ar',
                                     fluxo_id=CASE WHEN ?<>'' THEN ? ELSE fluxo_id END
                                     WHERE id=? AND estado IN ('pedida','no_ar')""",
                                  (str(d.get("fluxo_id") or ""), str(d.get("fluxo_id") or ""),
                                   o["transmissao_id"]))
                elif estado == "erro" and o["acao"] == "iniciar":
                    fechar_transmissao(o["transmissao_id"], "erro",
                                       resultado or "a maquina de captura nao conseguiu abrir a camera")
            auditar(None, f"ordem_{estado}", f"{o['camera_id']} ({resultado})", self.client_address[0])
            return self._json(200, {"ok": True, "ordem": oid, "estado": estado, "resultado": resultado},
                              {"Cache-Control": "no-store"})
        if rota == "/api/config-aplicada":
            # O BORDO conta o que aplicou (e o que recusou, com motivo): e' o que a tela do admin mostra
            # como "desejada x aplicada". Autorizacao pela saida do bordo (token de ingestao).
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            d = self._corpo()
            r = guardar_config_aplicada(str(d.get("embarcacao_id") or "").strip(), d.get("versao"),
                                        d.get("aplicadas") or [], d.get("recusadas") or [])
            if r.get("erro"):
                return self._json(422, r)
            auditar(None, "config_aplicada_pelo_bordo",
                    f"{d.get('embarcacao_id')} v{d.get('versao')} "
                    f"({len(d.get('aplicadas') or [])} ok / {len(d.get('recusadas') or [])} recusada)",
                    self.client_address[0])
            return self._json(200, r)
        if rota == "/api/config":
            # Publicar (o admin configura tudo de terra). Nasce aqui, nao no bordo.
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(403, {"erro": "so o administrador publica configuracao"})
            d = self._corpo()
            r = publicar_config(str(d.get("embarcacao_id") or "").strip(),
                                str(d.get("camera_id") or "").strip(),
                                str(d.get("chave") or "").strip(), d.get("valor"),
                                origem=(u["email"] if u else ""))
            if r.get("erro"):
                return self._json(422, r)
            auditar(u, "config_publicada", f"{r['embarcacao_id']} {r['camera_id'] or '-'} "
                                          f"{r['chave']}={r['valor']} (v{r['versao']})",
                    self.client_address[0])
            return self._json(201, r)
        if rota == "/api/config/aplicar":
            # ROTA LOCAL: quem chama e' o agente do bordo, nesta maquina. Aplica UMA chave aqui e diz
            # na cara quando nao aplica (nada de "achei que apliquei").
            if not (self._local() or self._token_do_bordo()):
                return self._json(401, {"erro": "rota local do computador de captura"})
            d = self._corpo()
            r = aplicar_config_local(str(d.get("camera_id") or ""), str(d.get("chave") or ""),
                                     d.get("valor"))
            if not r.get("ok"):
                return self._json(422, r)
            return self._json(200, r)
        if rota == "/api/saude-do-bordo":
            # O BORDO ENVIA a propria saude (mesmo caminho de saida de sempre — nada de porta aberta no
            # bordo). Quem LE e' a operacao: e' o painel "como esta' o computador de captura".
            # (so' POST chega aqui: e' o bordo entregando o retrato)
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            d = self._corpo()
            emb = str(d.get("embarcacao_id") or os.environ.get("LECSOR_EMBARCACAO_BORDO") or "").strip()
            retrato = d.get("retrato") if isinstance(d.get("retrato"), dict) else {
                k: v for k, v in d.items() if k not in ("embarcacao_id", "retrato")}
            r = receber_saude_do_bordo(emb, retrato)
            if r.get("erro"):
                return self._json(422, r)
            maq = str(retrato.get("maquina") or "")
            ver = str(retrato.get("versao_app") or "")
            auditar(None, "saude_do_bordo_recebida", f"{emb} {maq} v{ver}", self.client_address[0])
            return self._json(200, r, {"Cache-Control": "no-store"})
        if rota == "/api/estado-real":
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            d = self._corpo()
            emb = str(d.get("embarcacao_id") or os.environ.get("LECSOR_EMBARCACAO_BORDO") or "").strip()
            if not emb:
                return self._json(422, {"erro": "informe a embarcacao"})
            cams = d.get("cameras")
            if not isinstance(cams, list):
                return self._json(422, {"erro": "informe a lista de cameras com o estado real"})
            r = guardar_estado_real(emb, cams, de=None)
            return self._json(200, r, {"Cache-Control": "no-store"})
        if rota == "/api/hd/catalogo":
            # O BORDO publica o catalogo do HD do radar (o que existe, por horario). So' o catalogo:
            # video sobe apenas quando o cliente pede um trecho.
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            d = self._corpo()
            emb = str(d.get("embarcacao_id") or "").strip()
            cam_id = str(d.get("camera_id") or "").strip()
            if not emb or not cam_id:
                return self._json(422, {"erro": "informe a embarcacao e a camera"})
            blocos = d.get("blocos") if isinstance(d.get("blocos"), list) else []
            r = guardar_catalogo_do_hd(emb, cam_id, d.get("resumo") or {}, blocos)
            return self._json(200, r, {"Cache-Control": "no-store"})
        if rota == "/api/hd/trecho":
            # O BORDO envia o bloco que o cliente pediu (corpo cru = o proprio mp4). Quem envia e' o
            # bordo; terra nunca alcanca o PC de captura.
            if not self._token_do_bordo():
                return self._json(401, {"erro": "token de ingestao invalido"})
            qq = parse_qs(urlparse(self.path).query)
            pid = (qq.get("id", [""])[0] or "").strip()
            motivo = (qq.get("motivo", [""])[0] or "").strip()
            if not pid:
                return self._json(422, {"erro": "informe o pedido (id)"})
            if motivo:
                r = guardar_trecho_do_hd(pid, Path(""), 0, motivo=motivo)
                auditar(None, "trecho_do_hd_erro", f"{pid}: {motivo}"[:200], self.client_address[0])
                return self._json(200, r, {"Cache-Control": "no-store"})
            nome = (qq.get("arquivo", [""])[0] or "trecho.mp4")
            destino = hd_dir() / f"{pid}-{Path(nome).name}"
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                n = self._corpo_bruto(destino, limite=200_000_000)
            except ValueError as e:
                return self._json(422, {"erro": str(e)})
            r = guardar_trecho_do_hd(pid, destino, n)
            auditar(None, "trecho_do_hd_recebido", f"{pid} {destino.name} ({n} B)", self.client_address[0])
            return self._json(200, {**r, "bytes": n}, {"Cache-Control": "no-store"})
        if rota == "/api/hd/pedir":
            # O cliente pede um trecho do HD do radar (por data/hora ele escolhe o bloco na tela).
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            d = self._corpo()
            cam_id = str(d.get("camera_id") or "").strip()
            with conexao() as c:
                cam = c.execute("SELECT * FROM cameras WHERE id=?", (cam_id,)).fetchone()
            if not pode_ver_camera(u, cam):
                return self._json(403, {"erro": "esta camera nao e' da sua empresa"})
            r = pedir_trecho_do_hd(u, cam_id, str(d.get("arquivo") or ""))
            if "erro" in r:
                return self._json(422, r)
            return self._json(201, r, {"Cache-Control": "no-store"})
        if rota == "/api/decisoes":
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "so operador/admin registra decisao"})
            d = self._corpo()
            faltando = [k for k in ("data", "titulo", "texto") if not str(d.get(k, "")).strip()]
            if faltando:
                return self._json(422, {"erro": "decisao incompleta", "campos_faltando": faltando})
            with conexao() as c:
                cur = c.execute("INSERT INTO decisoes (data,titulo,texto,autor,fase_id) VALUES (?,?,?,?,?)",
                                (d["data"], d["titulo"], d["texto"], u["nome"], d.get("fase_id")))
            auditar(u, "gravar_decisao", str(cur.lastrowid), self.client_address[0])
            return self._json(201, {"id": cur.lastrowid, "status": "decisao registrada"})
        if rota == "/api/eventos":  # o agente de analise de bordo usa chave de servico, nao sessao de usuario
            chave = os.environ.get("LECSOR_CHAVE_ANALYTICS", "")
            if chave and not secrets.compare_digest(self.headers.get("X-Chave-Analytics", ""), chave):
                return self._json(401, {"erro": "chave de analise invalida"})
            d = self._corpo()
            if not (d.get("camera_id") and d.get("tipo") and d.get("inicio")):
                return self._json(422, {"erro": "camera_id, tipo e inicio sao obrigatorios"})
            with conexao() as c:
                cur = c.execute("""INSERT INTO analytics_eventos (camera_id,tipo,inicio,fim,confianca,clipe,metadados,criado_em)
                                   VALUES (?,?,?,?,?,?,?,?)""",
                                (d["camera_id"], d["tipo"], d["inicio"], d.get("fim"), d.get("confianca"),
                                 d.get("clipe", ""), json.dumps(d.get("metadados", {}), ensure_ascii=False),
                                 dt.datetime.now().astimezone().isoformat(timespec="seconds")))
            return self._json(201, {"id": cur.lastrowid, "status": "evento gravado"})
        if rota == "/api/contagens":
            chave = os.environ.get("LECSOR_CHAVE_ANALYTICS", "")
            if chave and not secrets.compare_digest(self.headers.get("X-Chave-Analytics", ""), chave):
                return self._json(401, {"erro": "chave de analise invalida"})
            d = self._corpo()
            faltando = [k for k in ("camera_id", "janela_inicio", "janela_fim", "fonte") if not str(d.get(k, "")).strip()]
            if faltando:
                return self._json(422, {"erro": "contagem sem evidencia nao entra", "campos_faltando": faltando})
            with conexao() as c:
                cur = c.execute("""INSERT INTO analytics_contagens (camera_id,janela_inicio,janela_fim,entrou,saiu,pico,fonte)
                                   VALUES (?,?,?,?,?,?,?)""",
                                (d["camera_id"], d["janela_inicio"], d["janela_fim"],
                                 int(d.get("entrou", 0)), int(d.get("saiu", 0)), int(d.get("pico", 0)), d["fonte"]))
            return self._json(201, {"id": cur.lastrowid, "status": "contagem gravada"})
        return self._json(404, {"erro": "rota inexistente"})

    # ---- porta unica do video
    def _host_do_fluxo(self, fluxo: str) -> str:
        """Onde o fluxo foi PUBLICADO (quem tem o video para servir ao player).

        127.0.0.1 = esta maquina; um IP = o lado terra (ex.: a VPS). Sem isso o painel do cliente
        procurava o video so no mediamtx local e mostrava 'sem sinal' mesmo com o fluxo no ar em outro
        servidor — foi o caso da webcam desta bancada, publicada na VPS.
        """
        try:
            with conexao() as c:
                r = c.execute("""SELECT srt_host FROM ingestoes WHERE fluxo_id=?
                                 ORDER BY (estado IN ('no_ar','no ar')) DESC, id DESC LIMIT 1""",
                              (fluxo,)).fetchone()
            host = (r["srt_host"] if r else None) or ""
        except Exception:
            host = ""
        return host.strip() or "127.0.0.1"

    def _provisionar_no_supabase(self, email: str, senha: str, nome: str = "") -> str:
        """Garante a credencial no Supabase Auth e devolve o estado em uma palavra, para a tela.

        "ok" | "atualizado" | "sem_chave_servico" | "falhou: <Tipo>". Nunca levanta: o usuario ja'
        esta' gravado no banco local e a resposta precisa dizer a verdade em vez de estourar 500.
        """
        try:
            import supabase_auth
            if not supabase_auth.pode_administrar():
                return "sem_chave_servico"
            r = supabase_auth.definir_senha(email, senha, nome)
            return "atualizado" if r.get("atualizado") else "ok"
        except Exception as e:
            return "falhou: " + type(e).__name__

    def _adotar_do_supabase(self, email: str, veredito: dict, senha: str, papel_forcado: str = ""):
        """Cria a linha local para o usuario que o Supabase Auth reconheceu.

        Sem isto uma instalacao nova (banco local vazio) recusava o usuario que ja' existe no
        Supabase — era preciso criar "mais um login" em cada maquina. O papel NUNCA vem do token:
        nasce como `cliente` (menor privilegio) ate o administrador ajustar, porque o Supabase nao
        guarda papel nem cliente. O hash local guarda a MESMA senha informada, para o login
        continuar funcionando na bancada sem rede.
        """
        papel = str(papel_forcado or veredito.get("papel") or "").strip().lower()
        if papel not in ("cliente", "operador", "admin", "tecnico"):
            papel = "cliente"
        nome = str(veredito.get("nome") or "").strip() or email.split("@")[0]
        salt = secrets.token_hex(8)
        uid = "sb-" + secrets.token_hex(6)
        with conexao() as c:
            c.execute("""INSERT INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,ativo)
                         VALUES (?,?,?,?,NULL,?,?,1)""",
                      (uid, email, nome, papel, hash_senha(senha, salt), salt))
            linha = c.execute("SELECT * FROM usuarios WHERE email=? AND ativo=1", (email,)).fetchone()
        auditar(linha, "adocao_supabase", f"{email} ({papel})", self.client_address[0])
        return linha

    def _anuncio_bordo(self) -> None:
        """O PC de captura avisa o lado terra que um fluxo entrou no ar.

        Sem isto o fluxo chega no mediamtx do lado terra e nao aparece para ninguem: `GET /api/cameras`
        so' listava linhas da tabela `cameras`, e o bordo nao tem como escrever no banco daqui.
        Autorizacao pelo token de ingestao (nunca por sessao de navegador): quem anuncia e' o bordo.
        """
        esperado = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
        recebido = (self.headers.get("Authorization") or "").strip()
        if recebido.lower().startswith("bearer "):
            recebido = recebido[7:].strip()
        if not esperado or not hmac.compare_digest(recebido, esperado):
            return self._json(401, {"erro": "token de ingestao invalido"})
        d = self._corpo()
        fluxo = re.sub(r"[^a-zA-Z0-9_\-]", "-", str(d.get("fluxo_id") or "").strip())
        if not fluxo:
            return self._json(422, {"erro": "informe o fluxo_id"})
        # `id` proprio da camera no bordo: o lado terra passa a ter a MESMA linha que a maquina das
        # cameras (era o "cadastrei cam-01 e cam-02 aqui e o cliente nao ve nada"). Sem id, o fluxo
        # e' o id.
        cid = re.sub(r"[^a-zA-Z0-9_\-]", "-", str(d.get("id") or "").strip()) or fluxo
        rotulo = (str(d.get("rotulo") or fluxo).strip() or fluxo)[:120]
        # TIPO (dono, 25/11/2026): o bordo declara o tipo e ele viaja junto com o cadastro — e' o que faz
        # o observador (Petrobras/IBAMA) ver radar/FLIR e o menu "Radar de oleo (HD)" aparecer. Sem tipo
        # no aviso, o nome decide (o cadastro antigo continua funcionando).
        tipo = str(d.get("tipo") or "").strip().lower()
        if tipo not in ("camera", "radar", "flir"):
            _nome = f"{cid} {rotulo} {fluxo}".lower()
            tipo = "flir" if "flir" in _nome else ("radar" if "radar" in _nome else "camera")
        ativo = 0 if str(d.get("ativo", 1)).strip().lower() in ("0", "false", "nao", "não") else 1
        # REMOCAO: o bordo avisa que a camera saiu de operacao (o dono removeu na tela) e o lado terra
        # apaga o cadastro — desativar escondia, mas a camera continuava para sempre na lista do cliente.
        if str(d.get("remover", "")).strip().lower() in ("1", "true", "sim", "s"):
            with conexao() as c:
                c.execute("DELETE FROM cameras WHERE id=? OR fluxo_id=?", (cid, fluxo))
            try:
                import supabase_escrita
                banco = supabase_escrita.espelhar({"id": cid}, remover=True)
            except Exception as e:  # noqa: BLE001
                banco = {"ok": False, "motivo": f"{type(e).__name__}: {e}"}
            auditar(None, "camera_removida_pelo_bordo", f"{cid} ({fluxo})", self.client_address[0])
            return self._json(200, {"ok": True, "id": cid, "fluxo_id": fluxo, "removido": True,
                                    "supabase": banco})
        emb = str(d.get("embarcacao_id") or os.environ.get("LECSOR_EMBARCACAO_BORDO") or "").strip()
        with conexao() as c:
            if not emb:
                # sem embarcacao informada: a bancada propria e' o caso padrao do primeiro bordo
                linha = (c.execute("SELECT id FROM embarcacoes WHERE id='bancada'").fetchone()
                         or c.execute("SELECT id FROM embarcacoes ORDER BY id LIMIT 1").fetchone())
                if not linha:
                    return self._json(422, {"erro": "cadastre uma embarcacao no lado terra primeiro"})
                emb = linha["id"]
            elif not c.execute("SELECT 1 FROM embarcacoes WHERE id=?", (emb,)).fetchone():
                return self._json(422, {"erro": "embarcacao_id inexistente"})
            # LICENCA (dono, 19/11/2026): o lado terra e' a AUTORIDADE. Licenca REVOGADA ou VENCIDA
            # corta a captura deste barco AQUI, antes de qualquer cadastro — e o bordo recebe o motivo
            # na resposta (a tela mostra, em vez de ficar muda). Embarcacao SEM licenca nenhuma
            # (instalacao antiga) segue liberada: a licenca e' ADICIONAL, nada e' apagado.
            _bloqueio = licenca_bloqueio(emb)
            if _bloqueio:
                auditar(None, "captura_recusada_por_licenca",
                        f"{cid} ({fluxo}) -> {emb}: {_bloqueio}", self.client_address[0])
                return self._json(403, {"erro": "licenca desta embarcacao nao libera a captura",
                                        "licenca": _bloqueio, "embarcacao_id": emb,
                                        "dica": "fale com o admin: a licenca pode ser reemitida ou prorrogada"})
            c.execute("""INSERT INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,tipo)
                         VALUES (?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET rotulo=excluded.rotulo,
                             embarcacao_id=excluded.embarcacao_id, fluxo_id=excluded.fluxo_id,
                             ativo=excluded.ativo, tipo=excluded.tipo, local='bordo'""",
                      (cid, emb, rotulo, fluxo, "bordo", ativo, tipo))
        # ESPELHO: o lado terra e' quem tem a chave de servico — e' aqui que o cadastro do bordo
        # tambem entra no Supabase (o anexo do dono: a tabela `cameras` da nuvem parada em 1 linha).
        try:
            import supabase_escrita
            with conexao() as c:
                nome_emb = c.execute("SELECT nome FROM embarcacoes WHERE id=?", (emb,)).fetchone()
            banco = supabase_escrita.espelhar({"id": cid, "fluxo_id": fluxo, "rotulo": rotulo,
                                               "embarcacao_id": emb, "ativo": ativo,
                                               "embarcacao_nome": (nome_emb["nome"] if nome_emb else "")})
        except Exception as e:  # noqa: BLE001
            banco = {"ok": False, "motivo": f"{type(e).__name__}: {e}"}
        auditar(None, "anuncio_bordo", f"{cid} ({fluxo}) -> {emb}"
                + ("" if banco.get("ok") else " [banco: NAO]"), self.client_address[0])
        return self._json(201, {"ok": True, "id": cid, "fluxo_id": fluxo,
                                "embarcacao_id": emb, "rotulo": rotulo, "ativo": bool(ativo),
                                "supabase": banco})

    def _anuncio_qualidade(self) -> None:
        """O PC de captura manda o SSIM que ele mediu na fonte (o lado terra nao consegue medir).

        O SSIM precisa do original e do comprimido lado a lado; o original so' existe na maquina que
        tem a camera. Era o "nao tenho medicao de SSIM": o numero era medido no bordo e nunca saia de
        la'. Aqui ele entra em `medicoes_qualidade` do lado terra. Autorizacao pelo token de ingestao.
        """
        esperado = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
        recebido = (self.headers.get("Authorization") or "").strip()
        if recebido.lower().startswith("bearer "):
            recebido = recebido[7:].strip()
        if not esperado or not hmac.compare_digest(recebido, esperado):
            return self._json(401, {"erro": "token de ingestao invalido"})
        d = self._corpo()
        fluxo = re.sub(r"[^a-zA-Z0-9_\-]", "-", str(d.get("fluxo_id") or "").strip())
        if not fluxo:
            return self._json(422, {"erro": "informe o fluxo_id"})
        try:
            ssim = float(d.get("ssim"))
        except (TypeError, ValueError):
            return self._json(422, {"erro": "informe o ssim medido (numero entre 0 e 1)"})
        if not 0.0 < ssim <= 1.0:
            return self._json(422, {"erro": "ssim fora da faixa (0 a 1)"})

        def num(chave):
            try:
                bruto = d.get(chave)
                return float(bruto) if bruto not in (None, "") else None
            except (TypeError, ValueError):
                return None

        # tabela da qualidade: existe no bordo e no lado terra; se o lado terra estiver numa base nova,
        # e' criada aqui (mesmas colunas que `ground/qualidade.py`).
        with conexao() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS medicoes_qualidade (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            fluxo_id TEXT NOT NULL, ssim REAL, ajuste TEXT, res_coluna TEXT,
                            resolucao TEXT, fps REAL, segundos REAL, mb_alvo REAL, mb_original REAL,
                            compressao_pct REAL, fonte TEXT, medido_em TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS ix_qualidade_fluxo ON medicoes_qualidade (fluxo_id, id)")
            c.execute("""INSERT INTO medicoes_qualidade (fluxo_id, ssim, ajuste, res_coluna, resolucao,
                         fps, segundos, mb_alvo, mb_original, compressao_pct, fonte, medido_em)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (fluxo, ssim, str(d.get("ajuste") or ""), str(d.get("res_coluna") or ""),
                       str(d.get("resolucao") or ""), num("fps"), num("segundos"), num("mb_alvo"),
                       num("mb_original"), num("compressao_pct"), str(d.get("fonte") or ""),
                       str(d.get("medido_em") or dt.datetime.now().astimezone().isoformat(timespec="seconds"))))
        auditar(None, "anuncio_qualidade", f"{fluxo} ssim={round(ssim, 4)}", self.client_address[0])
        return self._json(201, {"ok": True, "fluxo_id": fluxo, "ssim": ssim})

    def _autoriza_ingestao(self) -> bool:
        """Token de ingestao: quem anuncia e' o BORDO (PC de captura), nunca um navegador."""
        esperado = (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip()
        recebido = (self.headers.get("Authorization") or "").strip()
        if recebido.lower().startswith("bearer "):
            recebido = recebido[7:].strip()
        return bool(esperado) and hmac.compare_digest(recebido, esperado)

    def _registrar_anuncio(self, rota: str, fluxo: str, aceito: bool, motivo: str = "") -> None:
        """Guarda TODA tentativa de anuncio (aceita ou recusada): e' isto que torna a falha visivel.

        Sem esta tabela, "nada chegou" nao tinha como ser distinguido de "o bordo nunca falou", de
        "falou errado" ou de "foi recusado" — e era exatamente o caso do dono em 15/11/2026 (0 linhas
        no lado terra e nenhuma pista). O IP fica aqui porque esta rota e' de operacao, nunca do cliente.
        """
        try:
            with conexao() as c:
                c.execute("""CREATE TABLE IF NOT EXISTS anuncios_recebidos (
                                id INTEGER PRIMARY KEY AUTOINCREMENT, em TEXT NOT NULL,
                                rota TEXT NOT NULL, fluxo_id TEXT, aceito INTEGER NOT NULL,
                                motivo TEXT, ip TEXT)""")
                c.execute("""INSERT INTO anuncios_recebidos (em, rota, fluxo_id, aceito, motivo, ip)
                             VALUES (?,?,?,?,?,?)""",
                          (dt.datetime.now().astimezone().isoformat(timespec="seconds"), rota, fluxo,
                           1 if aceito else 0, (motivo or "")[:200], self.client_address[0]))
        except Exception:
            pass

    def _anuncio_envio(self) -> None:
        """O PC de captura DECLARA os numeros do envio que esta' no ar (entrada, saida, corte, alvo...).

        E' o lado "declarado" do atestado do trecho de 1 minuto: o lado terra mede o arquivo que baixa,
        mas nao tem como saber o que a maquina de captura declara — os numeros nasciam na tabela
        `ingestoes` DO BORDO e nunca saiam de la'. Aqui eles entram em `ingestoes` daqui, que e' de
        onde o atestado ja' le'. Autorizacao pelo token de ingestao. Nunca recebe nem guarda endereco,
        porta, protocolo ou credencial de camera — so' o que o bordo declara do proprio envio.
        """
        d = self._corpo()
        fluxo = re.sub(r"[^a-zA-Z0-9_\-]", "-", str(d.get("fluxo_id") or "").strip())
        if not self._autoriza_ingestao():
            self._registrar_anuncio("envios", fluxo, False, "token de ingestao invalido")
            return self._json(401, {"erro": "token de ingestao invalido"})
        if not fluxo:
            self._registrar_anuncio("envios", "", False, "sem fluxo_id")
            return self._json(422, {"erro": "informe o fluxo_id"})

        def num(chave):
            bruto = d.get(chave)
            try:
                return float(bruto) if bruto not in (None, "") else None
            except (TypeError, ValueError):
                return None

        def texto(chave, limite: int = 120):
            return str(d.get(chave) or "").strip()[:limite]

        carimbo = str(d.get("carimbo") or "").strip() or dt.datetime.now().astimezone().isoformat(timespec="seconds")
        recebido = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        declarado_por = f"{self.client_address[0]} ({texto('motivo', 60)})" if texto("motivo") else self.client_address[0]
        valores = {"camera_id": texto("camera_id"), "rotulo": texto("rotulo") or fluxo,
                   "tipo": texto("tipo", 40), "codec": texto("codec", 40),
                   "bitrate_alvo": texto("bitrate_alvo", 20), "resolucao": texto("resolucao", 40),
                   "fps": num("fps"), "bitrate_entrada_kbps": num("bitrate_entrada_kbps"),
                   "bitrate_saida_kbps": num("bitrate_saida_kbps"), "corte_pct": num("corte_pct"),
                   "velocidade": num("velocidade"), "tamanho_mb": num("tamanho_mb"),
                   "duracao_s": num("duracao_s"), "estado": texto("estado", 20) or "no_ar",
                   "fonte": texto("fonte", 200), "declarado_em": carimbo, "declarado_por": declarado_por,
                   "recebido_em": recebido, "atualizado_em": carimbo}
        try:
            import ingestao as _ingestao
            _ingestao.garantir_schema()   # tabela `ingestoes` com as colunas da declaracao (idempotente)
        except Exception:
            pass
        with conexao() as c:
            linha = c.execute("SELECT id FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1",
                              (fluxo,)).fetchone()
            if linha:
                sets = ", ".join(f"{k}=?" for k in valores)
                c.execute(f"UPDATE ingestoes SET {sets} WHERE id=?", (*valores.values(), linha["id"]))
                ident = linha["id"]
            else:
                chaves = ["fluxo_id", *valores.keys()]
                marcas = ", ".join("?" * len(chaves))
                cur = c.execute(f"""INSERT INTO ingestoes ({", ".join(chaves)}) VALUES ({marcas})""",
                                (fluxo, *valores.values()))
                ident = cur.lastrowid
        self._registrar_anuncio("envios", fluxo, True, texto("motivo", 60))
        auditar(None, "anuncio_envio", f"{fluxo} id={ident}", self.client_address[0])
        return self._json(201, {"ok": True, "fluxo_id": fluxo, "id": ident,
                                "declarado_em": carimbo, "recebido_em": recebido,
                                "bitrate_entrada_kbps": valores["bitrate_entrada_kbps"],
                                "bitrate_saida_kbps": valores["bitrate_saida_kbps"],
                                "corte_pct": valores["corte_pct"]})

    def _whep(self, camera_id: str, usuario) -> None:
        # Sem sessao so a propria maquina do servidor ve o fluxo (painel de bancada); de fora, 401.
        if not usuario and not self._local():
            return self._json(401, {"erro": "entre no sistema"})
        with conexao() as c:
            cam = c.execute("SELECT * FROM cameras WHERE id=? AND ativo=1", (camera_id,)).fetchone()
        if not cam:
            return self._json(404, {"erro": "camera nao encontrada"})
        if usuario and not pode_ver_camera(usuario, cam):
            auditar(usuario, "acesso_negado", camera_id, self.client_address[0])
            return self._json(403, {"erro": "voce nao tem acesso a esta camera"})
        fluxo = cam["fluxo_id"]
        corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        servidor = self._host_do_fluxo(fluxo)      # o mediamtx que TEM o fluxo (local ou lado terra)
        req = urllib.request.Request(f"http://{servidor}:{PORTA_WEBRTC}/{fluxo}/whep", data=corpo,
                                     headers={"Content-Type": self.headers.get("Content-Type", "application/sdp")},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                sdp, codigo = r.read(), r.status
        except urllib.error.HTTPError as e:
            return self._json(502, {"erro": f"lado terra recusou a sessao ({e.code})"})
        except Exception:
            return self._json(502, {"erro": "lado terra fora do ar"})
        auditar(usuario, "ver_camera", cam["id"], self.client_address[0])
        self.send_response(codigo)
        self.send_header("Content-Type", "application/sdp")
        self.send_header("Content-Length", str(len(sdp)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(sdp)

    def _hls(self, resto: str, usuario) -> None:
        """HLS de reserva servido pela API: o navegador nunca fala com o mediamtx."""
        if not usuario and not self._local():
            return self._json(401, {"erro": "entre no sistema"})
        partes = resto.split("/", 1)
        camera_id, resto_fluxo = partes[0], ("/" + partes[1]) if len(partes) > 1 else "/index.m3u8"
        with conexao() as c:
            cam = c.execute("SELECT * FROM cameras WHERE id=? AND ativo=1", (camera_id,)).fetchone()
        if not cam:
            return self._json(404, {"erro": "camera nao encontrada"})
        if usuario and not pode_ver_camera(usuario, cam):
            return self._json(403, {"erro": "voce nao tem acesso a esta camera"})
        try:
            servidor = self._host_do_fluxo(cam["fluxo_id"])
            with urllib.request.urlopen(f"http://{servidor}:{PORTA_HLS}/{cam['fluxo_id']}{resto_fluxo}", timeout=10) as r:
                dados, tipo = r.read(), r.headers.get("Content-Type", "application/octet-stream")
        except Exception:
            return self._json(502, {"erro": "HLS indisponivel"})
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _pdf(self, rota: str) -> None:
        slug = rota[len("/api/relatorios/"):-len(".pdf")]
        with conexao() as c:
            doc = c.execute("SELECT * FROM documentos WHERE slug=?", (slug,)).fetchone()
        if not doc:
            return self._json(404, {"erro": "documento inexistente"})
        md = Path.home() / doc["caminho"]
        if not md.exists():
            return self._json(404, {"erro": "arquivo do documento nao encontrado"})
        saida = RAIZ / "bench" / "saida" / f"doc-{slug}.pdf"
        r = subprocess.run([sys.executable, str(RAIZ / "tools" / "gerar-pdf-plano.py"), str(md), doc["titulo"],
                            "P&amp;D &middot; documento do sistema", f"gerado pelo sistema em "
                            + dt.datetime.now().astimezone().strftime("%d/%m/%Y %H:%M"), "Documento do projeto", str(saida)],
                           capture_output=True, text=True)
        if not saida.exists():
            return self._json(500, {"erro": "falha ao gerar o PDF", "detalhe": (r.stderr or r.stdout)[-300:]})
        b = saida.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Content-Disposition", f'inline; filename="{slug}.pdf"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)


    # ---- CHAVE DE LICENCA do PC de captura (dono, 19/11/2026) ------------------------------------
    #
    # "quero apenas instalar o app no computador de captura, inserir a chave da licenca e assim fazer
    # a conexao com a empresa e embarcacao cadastradas, e a licenca pode ser configuravel por tempo ou
    # indeterminado". O LADO TERRA e' a autoridade (gera, valida, revoga); o BORDO guarda o vinculo em
    # `<dados>/licenca.json` e revalida de tempos em tempos, sempre por pedido de SAIDA.
    #
    # Decisoes do dono que estao nestes metodos:
    #   * quantos PCs por licenca -> `maquinas_max` ajustavel (`licencas`/`licenca_usos`);
    #   * sem internet por dias   -> NADA para: nao existe corte por falta de rede, so' por
    #     vencimento/revogacao, e so' quando a maquina consegue falar com o lado terra;
    #   * o admin ve e copia a CHAVE INTEIRA no painel (`_licencas_do_painel`);
    #   * a chave nunca entra em log nem na auditoria — a auditoria guarda a PEGADA (`licenca_modulo`).

    def _pagina_da_licenca(self) -> None:
        """A tela da chave, servida PELO PROPRIO BORDO.

        Nao vem do lado terra de proposito: assim ela abre (e diz a verdade) mesmo sem internet —
        "nao consegui falar com o lado terra agora", em vez de tela em branco.
        """
        pagina = RAIZ / "licenca" / "index.html"
        try:
            corpo = pagina.read_bytes()
        except Exception:  # noqa: BLE001
            corpo = ("<!doctype html><meta charset=\"utf-8\"><title>Chave de licença</title>"
                     "<h1>Chave de licença</h1><p>A tela da licença não veio neste pacote.</p>"
                     ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _estado_da_licenca(self) -> None:
        """O que ESTA maquina tem guardado (a rota local `/api/licenca`)."""
        return self._json(200, conferir_licenca_do_terra(self.client_address[0]),
                          {"Cache-Control": "no-store"})

    # ---- PAINEL DO BORDO (dono, 23/11/2026) ------------------------------------------------------
    #
    # "no pc de captura ninguém precisa abrir nada, tudo deve ser feito no admin e cliente, o app de
    # captura deve ser autônomo, faz as varreduras locais e fica verificando as flags de terra e enviando
    # as respostas e fazendo as atuações". Por isso a tela de entrada do PC de captura é ESTE painel —
    # servido pelo próprio bordo, SEM LOGIN — e ele só INFORMA: licença, token do pacote, lado terra,
    # agente de ordens, varredura/publicação e saúde. Quem configura é o admin, do lado terra.
    #
    # Nada de segredo aqui: a chave da licença aparece só nos últimos 4 dígitos e o token de ingestão
    # aparece como PRESENTE/AUSENTE — nunca com valor.

    def _pagina_do_bordo(self) -> None:
        """A tela do BORDO, servida pelo próprio bordo (mesmo desenho da tela da chave)."""
        pagina = RAIZ / "bordo" / "index.html"
        try:
            corpo = pagina.read_bytes()
        except Exception:  # noqa: BLE001
            corpo = ("<!doctype html><meta charset=\"utf-8\"><title>Bordo</title>"
                     "<h1>Bordo</h1><p>O painel do bordo não veio neste pacote.</p>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _estado_do_bordo(self) -> None:
        return self._json(200, self._resumo_do_bordo(), {"Cache-Control": "no-store"})

    @staticmethod
    def _ler_json_do_bordo(caminho: Path):
        """Le um JSON do estado do bordo. Ausente/torto devolve `{}` (a tela nunca fica em branco)."""
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _caminho_do_estado_do_agente(nome: str, env: str) -> Path:
        """Os mesmos caminhos que o agente usa, com as MESMAS variaveis de troca (`LECSOR_*`)."""
        trocado = (os.environ.get(env) or "").strip()
        return Path(trocado) if trocado else (RAIZ / "ordens" / nome)

    def _agente_do_bordo(self) -> dict:
        """O agente de ordens está vivo? Ele marca `ordens/agente-vivo.json` a cada rodada.

        Sem o sinal fresco o painel diz "sem sinal" — o mesmo que o silêncio do bordo significa para o
        admin no lado terra. O agente pergunta ao lado terra a cada poucos segundos; 3 minutos sem
        sinal já é agente parado (o agente espera a chave, e o log conta o motivo).
        """
        d = self._ler_json_do_bordo(self._caminho_do_estado_do_agente("agente-vivo.json",
                                                                     "LECSOR_AGENTE_ESTADO"))
        em = str((d or {}).get("em") or "")
        rodadas = (d or {}).get("rodadas")
        if not em:
            return {"no_ar": False, "em": "", "em_em_segundos": None, "rodadas": None,
                    "motivo": "o agente de ordens ainda não deu sinal nesta máquina"}
        try:
            quando = dt.datetime.strptime(em, "%Y-%m-%dT%H:%M:%S")
            idade = (dt.datetime.now() - quando).total_seconds()
        except Exception:  # noqa: BLE001
            return {"no_ar": False, "em": em, "em_em_segundos": None, "rodadas": rodadas,
                    "motivo": "não consegui ler a hora do último sinal do agente"}
        no_ar = idade <= 180.0
        return {"no_ar": no_ar, "em": em, "em_em_segundos": round(idade, 1), "rodadas": rodadas,
                "motivo": "" if no_ar else f"o agente não dá sinal há {int(idade)} s"}

    def _no_ar_do_bordo(self) -> list:
        """O que ESTE bordo ligou e ainda não foi mandado parar (`ordens/ligados.json`)."""
        d = self._ler_json_do_bordo(self._caminho_do_estado_do_agente("ligados.json",
                                                                     "LECSOR_ORDENS_ESTADO"))
        saida = []
        for fluxo, info in (d or {}).items():
            if not isinstance(info, dict):
                continue
            desde = info.get("desde")
            try:
                quando = dt.datetime.fromtimestamp(float(desde)).astimezone().isoformat(timespec="seconds")
            except Exception:  # noqa: BLE001
                quando = ""
            saida.append({"fluxo": str(fluxo), "camera_id": str(info.get("camera_id") or ""),
                          "desde": quando, "ordem": str(info.get("ordem") or "")})
        return sorted(saida, key=lambda x: x.get("desde") or "")

    # ------------------------------------------------------- painel do bordo: o que ele mediu e faz
    def _processos_do_bordo(self) -> list:
        """O que ESTA maquina esta fazendo AGORA, fluxo por fluxo (dono, 23/11/2026).

        > "exibe as informacoes de saude e desempenho na tela, bem como os processos em andamento,
        >  como stremming, salvando video, ambos, etc..."

        Duas fontes reais — nada de suposicao:
          * `ordens/ligados.json` (o mesmo que o agente usa): o que o cliente/admin mandou subir;
          * `gravacao_continua` (o gravador full-time do radar no HD local): o que esta GRAVANDO.
        """
        processos: dict = {}

        def _pega(fluxo: str, camera: str) -> dict:
            chave = (fluxo or camera or "fluxo").strip() or "fluxo"
            return processos.setdefault(chave, {"fluxo": fluxo, "camera_id": camera,
                                                "transmitindo": False, "gravando": False,
                                                "desde": "", "ordem": "", "desde_gravacao": "",
                                                "hd": None, "observacao": ""})

        for x in self._no_ar_do_bordo():
            p = _pega(str(x.get("fluxo") or ""), str(x.get("camera_id") or ""))
            p["transmitindo"] = True
            p["desde"] = x.get("desde") or ""
            p["ordem"] = x.get("ordem") or ""

        try:
            import gravacao_continua
            g = dict(gravacao_continua.resumo() or {})
            if g.get("ligada"):
                p = _pega(str(g.get("camera") or "radar"), "")
                p["gravando"] = True
                p["desde_gravacao"] = g.get("ultimo") or ""
                p["hd"] = {"diretorio": g.get("diretorio"), "blocos": g.get("blocos"),
                           "bytes": g.get("bytes"), "livre_bytes": g.get("livre_bytes"),
                           "total_bytes": g.get("total_bytes"),
                           "bloco_segundos": g.get("bloco_segundos")}
        except Exception as e:  # noqa: BLE001
            processos.setdefault("_gravacao", {}).update(
                {"fluxo": "(gravacao full-time)", "camera_id": "", "transmitindo": False,
                 "gravando": False, "observacao": f"nao consegui ler o gravador: {type(e).__name__}"})

        for p in processos.values():
            p["estado"] = ("transmitindo e gravando" if p["transmitindo"] and p["gravando"]
                           else "transmitindo" if p["transmitindo"]
                           else "gravando" if p["gravando"] else "parado")
            if not p["transmitindo"] and not p["gravando"] and not p.get("observacao"):
                p["observacao"] = "sem ordem do cliente/admin (e a gravacao full-time nao esta ligada)"
        return sorted(processos.values(), key=lambda p: (p["estado"] == "parado", p["fluxo"]))

    def _gravacao_do_bordo(self) -> dict:
        """O estado do gravador full-time do radar — o que o admin liga (`LECSOR_GRAVACAO_CONTINUA`)."""
        try:
            import gravacao_continua
            g = dict(gravacao_continua.resumo() or {})
            return {"ligada": bool(g.get("ligada")), "camera": g.get("camera") or "radar",
                    "diretorio": g.get("diretorio") or "", "blocos": g.get("blocos"),
                    "bytes": g.get("bytes"), "livre_bytes": g.get("livre_bytes"),
                    "total_bytes": g.get("total_bytes"), "bloco_segundos": g.get("bloco_segundos"),
                    "primeiro": g.get("primeiro") or "", "ultimo": g.get("ultimo") or "", "erro": ""}
        except Exception as e:  # noqa: BLE001
            return {"ligada": False, "erro": f"nao consegui ler o gravador ({type(e).__name__})"}

    def _desempenho_do_bordo(self) -> dict:
        """O que o bordo MEDIU: entrada x saida por fluxo e o estado do link (dono, 23/11/2026).

        Fonte: `telemetria_minuto` (o que o proprio bordo fechou, minuto a minuto) e o proprio SRT
        (`producao.link_srt`) + a latencia de internet. **O que nao tem fonte nao vira numero**: o
        `fps` nao e' medido aqui e a tela diz "sem medida" — numero inventado e' pior que numero nenhum.
        """
        desde = (dt.datetime.now() - dt.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
        fluxos: list = []
        erro = ""
        try:
            import producao
            with producao.conexao_banco() as c:
                linhas = [dict(x) for x in c.execute(
                    "SELECT fluxo_id, camera_id, minuto, entrada_kbps, saida_kbps, compressao_pct, "
                    "mb_enviados, segundos_no_ar FROM telemetria_minuto WHERE minuto >= ? "
                    "ORDER BY minuto DESC LIMIT 400", (desde,))]
            vistos: set = set()
            for l in linhas:                      # a linha mais NOVA de cada fluxo
                f = str(l.get("fluxo_id") or "")
                if f in vistos:
                    continue
                vistos.add(f)
                fluxos.append(l)
        except Exception as e:  # noqa: BLE001
            erro = f"nao consegui ler a telemetria ({type(e).__name__})"
        link: dict = {}
        agora_ts = time.time()
        guardado = _CACHE_DESEMPENHO_BORDO.get("link") or {}
        if guardado and agora_ts - float(_CACHE_DESEMPENHO_BORDO.get("link_em") or 0) < CACHE_DESEMPENHO_BORDO_S:
            link = dict(guardado)
        else:
            try:
                import producao
                link = dict(producao.link_srt() or {})
                link["latencia_internet_ms"] = (producao.latencia_internet() or {}).get("ms_medio")
            except Exception as e:  # noqa: BLE001
                link = {"erro": f"nao consegui ler o link ({type(e).__name__})"}
            _CACHE_DESEMPENHO_BORDO["link"] = dict(link)
            _CACHE_DESEMPENHO_BORDO["link_em"] = agora_ts
        link["medido_ha_s"] = round(max(0.0, agora_ts - float(_CACHE_DESEMPENHO_BORDO.get("link_em") or agora_ts)), 0)
        return {"medido": bool(fluxos), "fluxos": fluxos, "link": link, "erro": erro,
                "motivo": "" if fluxos else "esta maquina ainda nao fechou nenhum minuto de medicao"}

    def _configuracao_do_bordo(self) -> list:
        """A configuracao LOCAL autonoma: o que esta maquina ja fez sozinha (dono, 23/11/2026).

        > "apos a validacao da chave de acesso, o app inicia a sua configuracao local autonoma"

        A ordem e' a ordem em que acontece na vida real — e cada passo diz se ja' aconteceu, quando e
        o que deu. Sem chave, o passo 1 fica em aberto e os outros dizem que esperam por ela.
        """
        lic = licenca_modulo.resumo()
        try:
            import varredura_do_bordo
            v = dict(varredura_do_bordo.ultima() or {})
        except Exception:  # noqa: BLE001
            v = {}
        ag = self._agente_do_bordo()
        publicadas = list(v.get("publicadas") or [])
        return [
            {"passo": "Chave de licenca desta maquina", "feito": bool(lic.get("tem")),
             "em": lic.get("ativada_em") or lic.get("conferida_em") or "",
             "texto": (f"ligada a embarcacao {lic.get('embarcacao_nome') or lic.get('embarcacao_id')}"
                       f" ({lic.get('cliente_nome') or '—'})") if lic.get("tem")
                      else "em aberto: o aplicativo abre a tela da chave sozinho"},
            {"passo": "Varredura das cameras e entradas de video locais",
             "feito": bool(v.get("quando")), "em": v.get("quando") or "",
             "texto": (f"{v.get('vistos', 0)} dispositivo(s) visto(s); "
                       f"{(v.get('cadastradas') or []) and ', '.join(v.get('cadastradas') or []) or 'nenhuma nova'}"
                       f" cadastrada(s)") if v.get("quando") else "ainda nao rodou"},
            {"passo": "Publicacao do cadastro ao lado terra", "feito": bool(publicadas),
             "em": v.get("quando") or "",
             "texto": (f"{len(publicadas)} camera(s) publicada(s): {', '.join(publicadas)}") if publicadas
                      else (v.get("falhas_de_publicacao") and
                            "falhou: " + "; ".join(str(f.get('motivo') or '?')
                                                   for f in v.get("falhas_de_publicacao") or [])) or
                           "nada a publicar ainda"},
            {"passo": "Olhando as flags do lado terra e obedecendo", "feito": bool(ag.get("no_ar")),
             "em": ag.get("em") or "",
             "texto": ("no ar: o bordo pergunta ao lado terra e obedece" if ag.get("no_ar")
                       else (ag.get("motivo") or "sem sinal ainda"))},
        ]

    def _resumo_do_bordo(self) -> dict:
        lic = licenca_modulo.resumo()
        token = bool((os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip())
        base = licenca_modulo.base_do_terra() or ""
        try:
            import varredura_do_bordo
            varredura = dict(varredura_do_bordo.ultima() or {})
        except Exception as e:  # noqa: BLE001
            varredura = {"ok": False, "motivo": f"não consegui ler a varredura ({type(e).__name__})"}
        try:
            import saude_do_bordo
            saude = dict(saude_do_bordo.retrato() or {})
        except Exception as e:  # noqa: BLE001
            saude = {"nao_medido": {"retrato": f"{type(e).__name__}: {e}"}}
        lic_publica = {k: lic.get(k) for k in ("tem", "ativada", "embarcacao_id", "embarcacao_nome",
                                               "cliente_id", "cliente_nome", "validade_tipo",
                                               "validade_em", "estado", "texto", "motivo",
                                               "chave_ultimos4", "conferida_em", "ativada_em")}
        return {
            "ok": True,
            "maquina": licenca_modulo.maquina(),
            "licenca": lic_publica,
            "token": {"presente": token},
            "lado_terra": {"base": base,
                           "texto": ("o cadastro desta máquina publica por aqui"
                                     if token else
                                     "falta o token de ingestão no pacote: o cadastro não publica")},
            "agente": self._agente_do_bordo(),
            "varredura": varredura,
            "publicadas": list(varredura.get("publicadas") or []),
            "no_ar": self._no_ar_do_bordo(),
            "saude": saude,
            # O que esta maquina faz AGORA (transmitindo / gravando / os dois), o que ela MEDIU e a
            # configuracao local que ela mesma fez depois da chave (dono, 23/11/2026).
            "processos": self._processos_do_bordo(),
            "gravacao": self._gravacao_do_bordo(),
            "desempenho": self._desempenho_do_bordo(),
            "configuracao": self._configuracao_do_bordo(),
        }

    def _licenca_atender(self, contar: bool) -> None:
        """Ativar (`contar=True`) ou revalidar (`contar=False`) — a MESMA rota, dois papeis.

        No LADO TERRA ele valida/registra; no BORDO ele pergunta ao lado terra e, se liberar, guarda o
        vinculo local. Sem rede, o bordo NAO perde o que ja' tinha: "mantém tudo normalmente".
        """
        d = self._corpo()
        chave = licenca_modulo.normalizar(d.get("chave", ""))
        if not chave:
            return self._json(422, {"erro": "chave incompleta", "formato": "XXXX-XXXX-XXXX-XXXX",
                                    "dica": "são 16 caracteres em 4 grupos — confira se copiou tudo"})
        if not self._base_do_lado_terra():
            codigo, corpo = licenca_do_terra({"chave": chave, "maquina": d.get("maquina")}, contar=contar)
            if corpo.get("ok"):
                lic = corpo.get("licenca") or {}
                auditar(None, "licenca_ativada" if contar else "licenca_conferida",
                        f"{lic.get('id','')} -> {lic.get('embarcacao_id','')} "
                        f"({licenca_modulo.pegada(chave)})", self.client_address[0])
            return self._json(codigo, corpo)
        r = licenca_modulo.pedir_ao_terra("/api/licenca/ativar" if contar else "/api/licenca/validar",
                                          {"chave": chave, "maquina": licenca_modulo.maquina()})
        nova = r.get("licenca") if isinstance(r.get("licenca"), dict) else None
        if not r.get("ok"):
            if contar:
                return self._json(502 if r.get("sem_rede") else 403,
                                  {"erro": r.get("erro") or r.get("motivo") or "não foi possível ativar",
                                   "sem_rede": bool(r.get("sem_rede")), "licenca": nova})
            # revalidacao que nao passou: o que ja' esta' guardado continua valendo (nao paro por rede)
            return self._json(200, {"ok": False, "sem_rede": bool(r.get("sem_rede")),
                                    "motivo": r.get("motivo") or r.get("erro") or "não conferi agora",
                                    "licenca": licenca_modulo.resumo(), "guardado": bool(licenca_modulo.ler())})
        lic = dict(nova or {})
        guardado = licenca_modulo.gravar({
            "chave": chave, "licenca_id": lic.get("id", ""),
            "embarcacao_id": lic.get("embarcacao_id", ""), "embarcacao_nome": lic.get("embarcacao_nome", ""),
            "cliente_id": lic.get("cliente_id", ""), "cliente_nome": lic.get("cliente_nome", ""),
            "validade_tipo": lic.get("validade_tipo", "indeterminada"),
            "validade_em": lic.get("validade_em", ""), "status": lic.get("status", "ativa"),
            "motivo": lic.get("motivo", ""), "maquina": licenca_modulo.maquina(),
            "ativada_em": em_iso(), "conferida_em": em_iso(), "origem": "terra"})
        auditar(None, "licenca_guardada_no_bordo",
                f"{guardado.get('licenca_id','')} -> {guardado.get('embarcacao_id','')} "
                f"({licenca_modulo.pegada(chave)})", self.client_address[0])
        return self._json(200, {"ok": True, "guardado": True, "licenca": licenca_modulo.resumo()})

    def _esquecer_licenca(self, u) -> None:
        """Desvincula ESTA maquina (trocar de barco). Nao e' o cliente quem decide.

        Quem pode: o admin (de qualquer lugar) ou quem esta' NA PROPRIA maquina — o usuario de captura
        logado, ou o pedido vindo de `127.0.0.1` (a tela da chave e' servida por este servidor e e'
        exatamente quem esta' sentado no PC; sem isto, "trocar a chave desta maquina" dava 403 numa
        instalacao nova, em que ninguem esta' logado ainda). Pedido de fora continua exigindo sessao."""
        if not ((u and u["papel"] in PAPEL_ADMIN) or self._local()):
            return self._json(403, {"erro": "só o admin (ou o usuário de captura nesta máquina)"})
        tinha = bool(licenca_modulo.ler())
        apagado = licenca_modulo.apagar()
        auditar(u, "licenca_esquecida", f"tinha={tinha} apagado={apagado}", self.client_address[0])
        return self._json(200, {"ok": True, "apagado": apagado, "tinha": tinha})

    def _licencas_do_painel(self) -> list:
        """A lista do painel do admin. Traz a CHAVE INTEIRA (decisao do dono de 19/11/2026: "sim, o
        admin pode ver e copiar") — por isso ela e' recuperavel no banco, e nunca vai para log."""
        with conexao() as c:
            linhas = c.execute("""SELECT l.*, e.nome AS embarcacao_nome, e.cliente_id AS cliente_id,
                                         cl.nome AS cliente_nome
                                  FROM licencas l
                                  LEFT JOIN embarcacoes e ON e.id = l.embarcacao_id
                                  LEFT JOIN clientes cl ON cl.id = e.cliente_id
                                  ORDER BY l.criada_em DESC""").fetchall()
            usos: dict = {}
            for r in c.execute("SELECT * FROM licenca_usos ORDER BY ultimo_em DESC"):
                usos.setdefault(r["licenca_id"], []).append(
                    {"maquina": r["maquina"], "primeiro_em": r["primeiro_em"], "ultimo_em": r["ultimo_em"]})
        saida = []
        for linha in linhas:
            st = licenca_modulo.estado(linha["validade_tipo"], linha["validade_em"],
                                       linha["status"], linha["motivo"])
            item = dict(linha)
            item.update(st)
            item["chave_ultimos4"] = licenca_modulo.ultimos4(linha["chave"])
            item["pega"] = licenca_modulo.pegada(linha["chave"])
            item["maquinas_usadas"] = usos.get(linha["id"], [])
            item["maquinas_em_uso"] = len(item["maquinas_usadas"])
            item["maquinas_livres"] = max(0, int(linha["maquinas_max"] or 1) - item["maquinas_em_uso"])
            saida.append(item)
        return saida

    def _criar_licenca(self, u) -> None:
        """Gera a chave para UMA embarcacao. Tempo: `indeterminada` ou `ate <AAAA-MM-DD>`."""
        d = self._corpo()
        emb = str(d.get("embarcacao_id") or "").strip()
        if not emb:
            return self._json(422, {"erro": "informe a embarcação", "campos_faltando": ["embarcacao_id"]})
        tipo = str(d.get("validade_tipo") or "indeterminada").strip().lower()
        if tipo not in ("indeterminada", "ate"):
            return self._json(422, {"erro": "validade_tipo tem que ser 'indeterminada' ou 'ate'"})
        quando = str(d.get("validade_em") or "").strip()[:10]
        if tipo == "ate":
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", quando):
                return self._json(422, {"erro": "licença com prazo precisa de validade_em = AAAA-MM-DD"})
            if licenca_modulo.vencida(tipo, quando):
                return self._json(422, {"erro": "essa data já passou", "validade_em": quando})
        else:
            quando = ""
        try:
            maquinas = max(1, int(d.get("maquinas_max") or 1))
        except (TypeError, ValueError):
            return self._json(422, {"erro": "maquinas_max tem que ser um número (quantos PCs usam)"})
        with conexao() as c:
            if not c.execute("SELECT 1 FROM embarcacoes WHERE id=?", (emb,)).fetchone():
                return self._json(422, {"erro": "embarcacao_id inexistente",
                                        "dica": "cadastre a embarcação antes de gerar a licença"})
            chave = licenca_modulo.gerar()
            while c.execute("SELECT 1 FROM licencas WHERE chave=?", (chave,)).fetchone():
                chave = licenca_modulo.gerar()
            ident = "lic-" + secrets.token_hex(6)
            c.execute("""INSERT INTO licencas (id,chave,embarcacao_id,validade_tipo,validade_em,
                                               maquinas_max,status,motivo,criada_por,criada_em)
                         VALUES (?,?,?,?,?,?,'ativa',?,?,?)""",
                      (ident, chave, emb, tipo, quando, maquinas, str(d.get("motivo") or ""),
                       (u["email"] if u else ""), em_iso()))
        auditar(u, "criar_licenca", f"{ident} -> {emb} ({licenca_modulo.pegada(chave)})",
                self.client_address[0])
        return self._json(201, {"id": ident, "chave": chave, "embarcacao_id": emb,
                                "validade_tipo": tipo, "validade_em": quando, "maquinas_max": maquinas,
                                "formato": "XXXX-XXXX-XXXX-XXXX"})

    def _licenca_acao(self, u) -> None:
        """revogar / reativar / reemitir (chave nova) / atualizar (prazo e nº de PCs)."""
        partes = [p for p in urlparse(self.path).path.split("/") if p]
        if len(partes) < 4:
            return self._json(404, {"erro": "rota de licença desconhecida"})
        ident, acao = partes[2], partes[3]
        d = self._corpo()
        with conexao() as c:
            linha = c.execute("SELECT * FROM licencas WHERE id=?", (ident,)).fetchone()
        if not linha:
            return self._json(404, {"erro": "licença não encontrada"})
        if acao == "revogar":
            motivo = str(d.get("motivo") or "revogada pelo admin").strip()
            with conexao() as c:
                c.execute("""UPDATE licencas SET status='revogada', motivo=?, revogada_em=?, alterada_em=?
                             WHERE id=?""", (motivo, em_iso(), em_iso(), ident))
            auditar(u, "revogar_licenca", f"{ident} -> {linha['embarcacao_id']}: {motivo}",
                    self.client_address[0])
            return self._json(200, {"ok": True, "id": ident, "status": "revogada", "motivo": motivo})
        if acao == "reativar":
            with conexao() as c:
                c.execute("""UPDATE licencas SET status='ativa', motivo='', revogada_em='', alterada_em=?
                             WHERE id=?""", (em_iso(), ident))
            auditar(u, "reativar_licenca", f"{ident} -> {linha['embarcacao_id']}", self.client_address[0])
            return self._json(200, {"ok": True, "id": ident, "status": "ativa"})
        if acao == "reemitir":
            with conexao() as c:
                chave = licenca_modulo.gerar()
                while c.execute("SELECT 1 FROM licencas WHERE chave=?", (chave,)).fetchone():
                    chave = licenca_modulo.gerar()
                c.execute("""UPDATE licencas SET chave=?, status='ativa', motivo='', revogada_em='',
                             alterada_em=? WHERE id=?""", (chave, em_iso(), ident))
                c.execute("DELETE FROM licenca_usos WHERE licenca_id=?", (ident,))
            auditar(u, "reemitir_licenca", f"{ident} -> {linha['embarcacao_id']} "
                    f"(pegada nova {licenca_modulo.pegada(chave)})", self.client_address[0])
            return self._json(200, {"ok": True, "id": ident, "chave": chave, "status": "ativa",
                                    "dica": "a chave antiga parou de funcionar; digite esta no PC de captura"})
        if acao == "atualizar":
            tipo = str(d.get("validade_tipo") or linha["validade_tipo"]).strip().lower()
            if tipo not in ("indeterminada", "ate"):
                return self._json(422, {"erro": "validade_tipo tem que ser 'indeterminada' ou 'ate'"})
            quando = str(d.get("validade_em", linha["validade_em"]) or "").strip()[:10]
            if tipo == "ate" and not re.match(r"^\d{4}-\d{2}-\d{2}$", quando):
                return self._json(422, {"erro": "licença com prazo precisa de validade_em = AAAA-MM-DD"})
            if tipo == "indeterminada":
                quando = ""
            try:
                maquinas = max(1, int(d.get("maquinas_max", linha["maquinas_max"]) or 1))
            except (TypeError, ValueError):
                return self._json(422, {"erro": "maquinas_max tem que ser um número"})
            with conexao() as c:
                c.execute("""UPDATE licencas SET validade_tipo=?, validade_em=?, maquinas_max=?,
                             alterada_em=? WHERE id=?""", (tipo, quando, maquinas, em_iso(), ident))
            auditar(u, "atualizar_licenca",
                    f"{ident} -> {linha['embarcacao_id']}: {tipo} {quando} / {maquinas} PC(s)",
                    self.client_address[0])
            return self._json(200, {"ok": True, "id": ident, "validade_tipo": tipo,
                                    "validade_em": quando, "maquinas_max": maquinas})
        return self._json(404, {"erro": f"ação desconhecida: {acao}",
                                "acoes": ["revogar", "reativar", "reemitir", "atualizar"]})


def _fechar_minutos_em_loop() -> None:
    """Fecha o historico de producao a cada minuto (card de 30 dias depende disso rodando)."""
    while True:
        try:
            producao_pipeline.fechar_minutos()
        except Exception as e:
            print("[aviso] fechar_minutos:", type(e).__name__, e)
        time.sleep(60)


def _varredura_em_loop() -> None:
    """Varre os dispositivos desta maquina no boot e de tempo em tempo — sem nunca derrubar a API.

    So' roda em MAQUINA DE CAPTURA (a que tem embarcacao no pacote): o lado terra nao tem camera e nao
    teria o que cadastrar, e varrer la' seria trabalho a toa com resposta enganosa. Espera curta no
    inicio (a API precisa estar de pe' e o banco criado), depois usa o intervalo do ambiente
    (`LECSOR_ESPERA_DA_VARREDURA`, padrao 300 s). Falha vira aviso no log: a tela e a saude mostram.
    """
    if not licenca_modulo.embarcacao():
        print("[api] varredura do bordo: nao rodo aqui (esta maquina nao tem embarcacao: nao foi "
              "ativada com a chave de licenca e nao e' um computador de captura)", flush=True)
        return
    time.sleep(5)
    while True:
        try:
            import varredura_do_bordo
            r = varredura_do_bordo.varrer()
            if r.get("ok"):
                if r.get("cadastradas") or r.get("atualizadas"):
                    print(f"[api] varredura do bordo: +{len(r.get('cadastradas') or [])} "
                          f"~{len(r.get('atualizadas') or [])} camera(s) em {r.get('embarcacao_id')} "
                          f"(publicadas {len(r.get('publicadas') or [])})", flush=True)
            else:
                print(f"[api] varredura do bordo nao cadastrou nada: {r.get('motivo')}", flush=True)
            espera = varredura_do_bordo.intervalo()
        except Exception as e:  # noqa: BLE001
            print(f"[api] aviso: varredura do bordo falhou ({type(e).__name__}: {e})", flush=True)
            espera = 300
        time.sleep(espera)


def _publicar_cadastro_no_boot() -> None:
    """Publica no lado terra o cadastro das cameras desta maquina, e NAO DESISTE em silencio.

    Uma camera registrada nesta maquina so' era vista pelo cliente depois que o fluxo subia; camera
    cadastrada e parada ficava invisivel. Aqui o cadastro vai na subida (recupera tambem o caso das
    cameras registradas antes desta correcao) e continua sendo tentado de tempo em tempo enquanto
    alguma camera nao estiver publicada — antes ele tentava 5 vezes e ficava quieto, e o dono so'
    descobria pelo log de arquivo (18/11/2026: as cameras dele estavam no ar e fora da tela).
    """
    if not (os.environ.get("LECSOR_TOKEN_INGESTAO") or "").strip():
        print("[api] aviso: sem token de ingestao no ambiente: o cadastro das cameras NAO vai ser "
              "publicado no lado terra (a camera nao aparece na tela do cliente). Confira o "
              "ambiente.json do pacote.", flush=True)
        return
    import repasse
    tentativa, pausa = 0, 30
    while True:
        tentativa += 1
        try:
            with conexao() as c:
                cams = [dict(x) for x in c.execute("SELECT * FROM cameras ORDER BY id")]
        except Exception as e:
            print(f"[api] aviso: leitura das cameras para publicar falhou ({type(e).__name__}: {e})", flush=True)
            return
        if not cams:
            return
        ok = sum(1 for cam in cams if repasse.publicar_cadastro(cam).get("ok"))
        if ok == len(cams):
            print(f"[api] cadastro de {ok} camera(s) publicado no lado terra", flush=True)
            return
        print(f"[api] cadastro: {ok}/{len(cams)} publicado(s) no lado terra; tentativa {tentativa}",
              flush=True)
        # 5 tentativas rapidas (o servidor do lado terra pode estar subindo junto) e depois de 5 em
        # 5 minutos, para o cadastro entrar sozinho quando o link voltar.
        if tentativa >= 5:
            pausa = 300
        time.sleep(pausa)


def principal() -> int:
    args = [a for a in sys.argv[1:]]
    semear = "--semear-demo" in args
    porta = next((int(a) for a in args if a.isdigit()), 8765)
    # O ambiente do pacote (Supabase, token de ingestao, embarcacao, lado terra) entra aqui, do
    # arquivo que o instalador deixou no repositorio. Sem isto o servidor do PC de captura subia mudo
    # e o anuncio do cadastro ao lado terra falhava em silencio (medido 18/11/2026).
    faltando = carregar_ambiente()
    if faltando:
        print(f"[api] aviso: ambiente incompleto no pacote ({', '.join(faltando)}): "
              f"o anuncio do cadastro pode nao sair sem ele", flush=True)
    inicializar(semear)
    try:
        ing_limpar_vivos()      # envio que ficou 'no_ar' com processo morto
    except Exception as e:
        # limpeza e higiene: se o banco estiver ocupado nesse instante, a API sobe de todo jeito.
        # Antes isso derrubava o servico no boot e o aplicativo abria em branco, sem tela de login.
        print(f"[api] aviso: limpeza de envios vivos falhou ({type(e).__name__}: {e}); seguindo", flush=True)
    threading.Thread(target=_fechar_minutos_em_loop, daemon=True).start()
    # Publica o cadastro das cameras desta maquina no lado terra (best-effort, em segundo plano: nao
    # pode atrasar o boot da API).
    threading.Thread(target=_publicar_cadastro_no_boot, daemon=True).start()
    # VARREDURA DO BORDO (plano de 19/11/2026, Fase 2): no inicio do sistema o app olha a propria maquina,
    # cadastra a camera na embarcacao que o pacote ja' traz e publica em terra. Em segundo plano (nao
    # atrasa o boot) e repetida de tempo em tempo (cabo/USB que entrou depois).
    threading.Thread(target=_varredura_em_loop, daemon=True).start()
    # Vigia da transmissao a pedido do cliente: fecha a sessao sem batimento (tela fechada /
    # computador desligado), corta no tempo maximo e libera a camera quando ninguem mais esta' vendo.
    threading.Thread(target=vigiar_transmissoes, daemon=True).start()
    # gravacao que ficou com processo morto (a maquina reiniciou) e' marcada, sem apagar arquivo
    try:
        gravacao_modulo.limpar_orfas()
    except Exception as e:
        print(f"[api] aviso: limpeza das gravacoes falhou ({type(e).__name__}: {e})", flush=True)
    print(f"[ok] sistema em http://127.0.0.1:{porta}/  (bancada: /  ·  cliente: /app  ·  admin: /admin)")
    # por padrão o servidor fica SÓ no loopback da máquina; no lado terra ele precisa aceitar o
    # acesso do navegador do cliente, então o endereço vem do ambiente (LECSOR_BIND)
    endereco = (os.environ.get("LECSOR_BIND") or "127.0.0.1", porta)
    ThreadingHTTPServer(endereco, Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
