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
import json
import re
import os
import secrets
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
from ingestao import iniciar as ing_iniciar, parar as ing_parar, listar as ing_listar  # noqa: E402
from ingestao import desligar_camera as ing_desligar_camera, ligar_camera as ing_ligar_camera  # noqa: E402
from ingestao import capturar as ing_capturar, listar_dispositivos as ing_dispositivos, ao_vivo as ing_ao_vivo
from ingestao import limpar_vivos_mortos as ing_limpar_vivos
import etapas as etapas_pipeline  # noqa: E402
import producao as producao_pipeline  # noqa: E402
from urllib.parse import parse_qs, unquote, urlparse

RAIZ = Path(__file__).resolve().parent.parent
COMPRIMIDOS = RAIZ / "ground" / "envios" / "comprimido"
BANCO = RAIZ / "db" / "pipeline.db"
CAMPOS_OBRIGATORIOS = ("valor", "fonte", "data", "hardware_versao", "comando")
PORTA_WEBRTC, PORTA_HLS, PORTA_API_MEDIAMTX = 8889, 8888, 9997
_CACHE_METRICAS: dict = {}
DURACAO_SESSAO_H = 12
INICIADO_EM = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
PAPEL_ADMIN = ("operador", "admin")


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


def pode_ver_camera(usuario, camera: sqlite3.Row | None) -> bool:
    """Cliente so ve camera da propria empresa; operador/admin veem tudo."""
    if camera is None:
        return False
    if usuario["papel"] in PAPEL_ADMIN:
        return True
    with conexao() as c:
        emb = c.execute("SELECT cliente_id FROM embarcacoes WHERE id = ?", (camera["embarcacao_id"],)).fetchone()
    return bool(emb) and emb["cliente_id"] == usuario["cliente_id"]


# --------------------------------------------------------------------------- banco / inicializacao
def inicializar(semear_demo: bool = False) -> None:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    with conexao() as c:
        c.executescript((RAIZ / "db" / "schema.sql").read_text(encoding="utf-8"))
        c.executescript((RAIZ / "db" / "schema-fase4.sql").read_text(encoding="utf-8"))
        c.executescript((RAIZ / "db" / "schema-fase5.sql").read_text(encoding="utf-8"))
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
        for k, v in (cabecalhos or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _sessao(self):
        token = None
        if "Cookie" in self.headers:
            ck = SimpleCookie(self.headers["Cookie"])
            token = ck["sessao"].value if "sessao" in ck else None
        return usuario_da_sessao(token)

    def _local(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _chave_analytics(self) -> bool:
        """A ingestao de analise exige a chave do agente (variavel de ambiente no servidor).
        Sem chave configurada, a porta fica fechada — nao existe caminho sem credencial."""
        esperada = os.environ.get("LECSOR_CHAVE_ANALYTICS", "")
        recebida = self.headers.get("X-Chave-Analytics", "")
        return bool(esperada) and secrets.compare_digest(esperada, recebida)

    def end_headers(self) -> None:
        if self.path.endswith((".html", ".css", ".js")) or urlparse(self.path).path in ("/", "/app", "/admin"):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        rota = urlparse(path).path
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

    def do_GET(self) -> None:  # noqa: N802
        rota = urlparse(self.path).path
        u = self._sessao()
        if rota == "/favicon.ico":
            return self._json(204, {}, {"Cache-Control": "max-age=86400"})
        if rota == "/api/saude":
            return self._json(200, {"ok": True, "banco": str(BANCO), "python": sys.version.split()[0]})
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
                if u["papel"] in PAPEL_ADMIN:
                    linhas = c.execute("SELECT * FROM embarcacoes ORDER BY nome").fetchall()
                else:
                    linhas = c.execute("SELECT * FROM embarcacoes WHERE cliente_id=? ORDER BY nome", (u["cliente_id"],)).fetchall()
            return self._json(200, {"embarcacoes": [dict(x) for x in linhas]})
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
            return self._json(200, {"qualidade": producao_pipeline._qualidade_por_fluxo()},
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
            d["sintetica"] = {"tipo": "sintetica", "descricao": "teste sintetico (testsrc2), sem camera",
                              "resolucoes": ["1920x1080", "1280x720"]}
            return self._json(200, d, {"Cache-Control": "no-store"})
        if rota in ("/api/cameras/detalhe", "/api/cameras/interno"):
            # endereco da camera so para a operacao: o app do cliente nunca recebe isso
            if not (u and u["papel"] in PAPEL_ADMIN) and not self._local():
                return self._json(403, {"erro": "so a operacao ve o endereco da camera"})
            with conexao() as c:
                linhas = [dict(x) for x in c.execute(
                    "SELECT id,rotulo,fluxo_id,embarcacao_id,local,ativo,ip,porta,protocolo,canal "
                    "FROM cameras ORDER BY id")]
            for l in linhas:
                if l.get("ip"):
                    canal = str(l.get("canal") or "")
                    l["captura"] = ("rtsp://$USUARIO:$SENHA@" + l["ip"] + ":" + str(l.get("porta") or 554)
                                    + ("/Streaming/Channels/" + canal if canal else ""))
                else:
                    l["captura"] = ""
            return self._json(200, {"cameras": linhas}, {"Cache-Control": "no-store"})
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
                                  "local": cam["local"], "no_ar": no_ar, "motivo": motivo, "tracks": p.get("tracks", []),
                                  "leitores": len(p.get("readers", [])), "encoder": perfil_encoder(cam["fluxo_id"])})
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
            return self._json(200, {"usuarios": [dict(x) for x in linhas]})
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
        u = self._sessao()
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
            if veredito is None:
                entrou = bool(alvo) and conferir_senha(alvo, senha)
            else:
                entrou = bool(veredito.get("ok")) and bool(alvo)
            if not entrou:
                auditar(None, "entrada_falha", email[:80], self.client_address[0])
                return self._json(401, {"erro": "e-mail ou senha invalidos"})
            token = criar_sessao(alvo["id"], self.headers.get("User-Agent", ""))
            auditar(alvo, "entrada", alvo["email"], self.client_address[0])
            return self._json(200, {"ok": True, "nome": alvo["nome"], "papel": alvo["papel"]},
                              {"Set-Cookie": f"sessao={token}; HttpOnly; SameSite=Lax; Path=/",
                               "Cache-Control": "no-store"})
        if rota == "/api/sair":
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
        if rota in ("/api/ingestao/ao-vivo", "/api/envios/ao-vivo"):
            # STREAMING CONTINUO de uma fonte viva (webcam do notebook / fonte sintetica):
            # sem duracao determinada, igual a operacao — so para quando mandarem parar.
            if not (self._pode_operar(u) or self._local()):
                return self._json(403, {"erro": "so operacao e administrador transmitem ao vivo"})
            d = self._corpo()
            r = ing_ao_vivo(tipo=str(d.get("tipo") or "camera"),
                            dispositivo=(str(d.get("dispositivo") or "").strip() or None),
                            resolucao=str(d.get("resolucao") or "1920x1080"), fps=int(d.get("fps") or 30),
                            rotulo=str(d.get("rotulo") or ""), fluxo_id=(str(d.get("fluxo_id") or "").strip() or None),
                            bitrate=str(d.get("bitrate") or "auto"))
            if "erro" in r:
                return self._json(422, r)
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
            if d["papel"] not in ("cliente", "operador", "admin"):
                return self._json(422, {"erro": "papel invalido", "aceitos": ["cliente", "operador", "admin"]})
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
            auditar(u, "criar_usuario", email, self.client_address[0])
            # a senha inicial aparece UMA vez, para quem criou entregar; o banco guarda so o hash
            return self._json(201, {"id": uid, "email": email, "papel": d["papel"], "senha_inicial": senha})
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
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "entre no sistema"})
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
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "entre no sistema"})
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
        if rota == "/api/cameras":
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "entre no sistema"})
            d = self._corpo()
            # identificador derivado do fluxo: menos campo para o dono preencher
            if not str(d.get("id", "")).strip():
                d["id"] = re.sub(r"[^a-zA-Z0-9_\\-]", "-", str(d.get("fluxo_id", "")).strip())
            d["rotulo"] = str(d.get("rotulo") or d.get("fluxo_id", "")).strip()
            ip = str(d.get("ip") or "").strip()
            porta = str(d.get("porta") or "").strip()
            if ip and not re.match(r"^[0-9a-zA-Z.:\\-]{3,64}$", ip):
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
                c.execute("""INSERT OR REPLACE INTO cameras
                             (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal)
                             VALUES (?,?,?,?,?,1,?,?,?,?)""",
                          (d["id"], d["embarcacao_id"], d["rotulo"], d["fluxo_id"], d.get("local", ""),
                           ip, porta, str(d.get("protocolo") or "rtsp"), str(d.get("canal") or "")))
            auditar(u, "criar_camera", (d["id"] + " " + ip + ":" + porta).strip(": "), self.client_address[0])
            return self._json(201, {"id": d["id"], "ip": ip, "porta": porta})
        if rota.startswith("/api/cameras/") and rota.endswith("/ativo"):
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "entre no sistema"})
            cid = rota[len("/api/cameras/"):-len("/ativo")]
            novo = 1 if self._corpo().get("ativo", True) else 0
            with conexao() as c:
                if not c.execute("SELECT 1 FROM cameras WHERE id=?", (cid,)).fetchone():
                    return self._json(404, {"erro": "camera inexistente"})
                c.execute("UPDATE cameras SET ativo=? WHERE id=?", (novo, cid))
            auditar(u, "ativar_camera" if novo else "desativar_camera", cid, self.client_address[0])
            return self._json(200, {"id": cid, "ativo": bool(novo)})
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


def _fechar_minutos_em_loop() -> None:
    """Fecha o historico de producao a cada minuto (card de 30 dias depende disso rodando)."""
    while True:
        try:
            producao_pipeline.fechar_minutos()
        except Exception as e:
            print("[aviso] fechar_minutos:", type(e).__name__, e)
        time.sleep(60)


def principal() -> int:
    args = [a for a in sys.argv[1:]]
    semear = "--semear-demo" in args
    porta = next((int(a) for a in args if a.isdigit()), 8765)
    inicializar(semear)
    try:
        ing_limpar_vivos()      # envio que ficou 'no_ar' com processo morto
    except Exception as e:
        # limpeza e higiene: se o banco estiver ocupado nesse instante, a API sobe de todo jeito.
        # Antes isso derrubava o servico no boot e o aplicativo abria em branco, sem tela de login.
        print(f"[api] aviso: limpeza de envios vivos falhou ({type(e).__name__}: {e}); seguindo", flush=True)
    threading.Thread(target=_fechar_minutos_em_loop, daemon=True).start()
    print(f"[ok] sistema em http://127.0.0.1:{porta}/  (bancada: /  ·  cliente: /app  ·  admin: /admin)")
    # por padrão o servidor fica SÓ no loopback da máquina; no lado terra ele precisa aceitar o
    # acesso do navegador do cliente, então o endereço vem do ambiente (LECSOR_BIND)
    endereco = (os.environ.get("LECSOR_BIND") or "127.0.0.1", porta)
    ThreadingHTTPServer(endereco, Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
