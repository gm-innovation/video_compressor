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
import os
import secrets
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "db" / "pipeline.db"
CAMPOS_OBRIGATORIOS = ("valor", "fonte", "data", "hardware_versao", "comando")
PORTA_WEBRTC, PORTA_HLS, PORTA_API_MEDIAMTX = 8889, 8888, 9997
DURACAO_SESSAO_H = 12
PAPEL_ADMIN = ("operador", "admin")


def conexao() -> sqlite3.Connection:
    c = sqlite3.connect(BANCO)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
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
        for cam in json.loads((RAIZ / "ground" / "receivers.json").read_text(encoding="utf-8")):
            c.execute("""INSERT OR IGNORE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local)
                         VALUES (?,?,?,?,?)""",
                      (cam["id"], "bancada", cam["rotulo"], cam["id"], "bancada"))
        # embarcacao do cliente demo: mesma bancada, outro dono (prova o isolamento por cliente)
        c.execute("""INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)
                     VALUES ('psv-exemplo','armador-demo','PSV Exemplo (demo)','9123456','em operacao')""")
        for cam in json.loads((RAIZ / "ground" / "receivers.json").read_text(encoding="utf-8")):
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
            ("admin@lecsor.test", "Administrador LECSOR (demo)", "admin", None)]
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
def mediamtx_json(caminho: str) -> dict:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTA_API_MEDIAMTX}{caminho}", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def fluxos() -> dict:
    mt = {p["name"]: p for p in mediamtx_json("/v3/paths/list").get("items", [])}
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
                "gerado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds")}


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
    def do_GET(self) -> None:  # noqa: N802
        rota = urlparse(self.path).path
        u = self._sessao()
        if rota == "/api/saude":
            return self._json(200, {"ok": True, "banco": str(BANCO), "python": sys.version.split()[0]})
        if rota == "/api/eu":
            if not u:
                return self._json(200, {"autenticado": False})
            return self._json(200, {"autenticado": True, "email": u["email"], "nome": u["nome"], "papel": u["papel"]})
        if rota == "/api/fluxos":
            return self._json(200, fluxos())
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
        if rota == "/api/cameras":
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            emb = parse_qs(urlparse(self.path).query).get("embarcacao", [None])[0]
            mt = {p["name"]: p for p in mediamtx_json("/v3/paths/list").get("items", [])}
            saida = []
            with conexao() as c:
                sql = "SELECT * FROM cameras WHERE ativo=1" + (" AND embarcacao_id=?" if emb else "")
                for cam in c.execute(sql, ((emb,) if emb else ())).fetchall():
                    if not pode_ver_camera(u, cam):
                        continue
                    p = mt.get(cam["fluxo_id"], {})
                    # so o que a tela precisa: sem endereco de camera, sem credencial, sem porta interna
                    saida.append({"id": cam["id"], "rotulo": cam["rotulo"], "embarcacao_id": cam["embarcacao_id"],
                                  "local": cam["local"], "no_ar": bool(p.get("ready")), "tracks": p.get("tracks", []),
                                  "leitores": len(p.get("readers", [])), "encoder": perfil_encoder(cam["fluxo_id"])})
            return self._json(200, {"cameras": saida})
        if rota == "/api/decisoes":
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            return self._json(200, {"decisoes": ler_tudo()["decisoes"]})
        if rota == "/api/auditoria":
            if not (u and u["papel"] in PAPEL_ADMIN):
                return self._json(401, {"erro": "so operador/admin"})
            return self._json(200, {"auditoria": ler_tudo()["auditoria"]})
        if rota == "/api/eventos":
            if not u:
                return self._json(401, {"erro": "entre no sistema"})
            return self._json(200, {"eventos": ler_tudo()["eventos"]})
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
            with conexao() as c:
                alvo = c.execute("SELECT * FROM usuarios WHERE email=? AND ativo=1",
                                 (str(d.get("email", "")).strip().lower(),)).fetchone()
            if not alvo or not conferir_senha(alvo, str(d.get("senha", ""))):
                auditar(None, "entrada_falha", str(d.get("email", ""))[:80], self.client_address[0])
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
                cur = c.execute("""INSERT INTO analytics_eventos (camera_id,tipo,inicio,fim,confianca,clipe,metadados)
                                   VALUES (?,?,?,?,?,?,?)""",
                                (d["camera_id"], d["tipo"], d["inicio"], d.get("fim"), d.get("confianca"),
                                 d.get("clipe", ""), json.dumps(d.get("metadados", {}), ensure_ascii=False)))
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
    def _whep(self, camera_id: str, usuario) -> None:
        if not usuario:
            return self._json(401, {"erro": "entre no sistema"})
        with conexao() as c:
            cam = c.execute("SELECT * FROM cameras WHERE id=? AND ativo=1", (camera_id,)).fetchone()
        if not pode_ver_camera(usuario, cam):
            auditar(usuario, "acesso_negado", camera_id, self.client_address[0])
            return self._json(403, {"erro": "voce nao tem acesso a esta camera"})
        fluxo = cam["fluxo_id"]
        corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        req = urllib.request.Request(f"http://127.0.0.1:{PORTA_WEBRTC}/{fluxo}/whep", data=corpo,
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
        if not usuario:
            return self._json(401, {"erro": "entre no sistema"})
        partes = resto.split("/", 1)
        camera_id, resto_fluxo = partes[0], ("/" + partes[1]) if len(partes) > 1 else "/index.m3u8"
        with conexao() as c:
            cam = c.execute("SELECT * FROM cameras WHERE id=? AND ativo=1", (camera_id,)).fetchone()
        if not pode_ver_camera(usuario, cam):
            return self._json(403, {"erro": "voce nao tem acesso a esta camera"})
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORTA_HLS}/{cam['fluxo_id']}{resto_fluxo}", timeout=10) as r:
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


def principal() -> int:
    args = [a for a in sys.argv[1:]]
    semear = "--semear-demo" in args
    porta = next((int(a) for a in args if a.isdigit()), 8765)
    inicializar(semear)
    print(f"[ok] sistema em http://127.0.0.1:{porta}/  (bancada: /  ·  cliente: /app  ·  admin: /admin)")
    ThreadingHTTPServer(("127.0.0.1", porta), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
