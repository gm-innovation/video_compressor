#!/usr/bin/env python3
"""API + banco do modulo de acompanhamento (Fase 3, versao local da bancada).

Banco: SQLite por enquanto (mesmo desenho do alvo Postgres em db/schema.sql).
Serve o portal e os dados reais medidos na bancada. Nada de numero digitado a mao.
"""
from __future__ import annotations
import csv, json, sqlite3, subprocess, sys, datetime as dt
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "db" / "pipeline.db"
CAMPOS_OBRIGATORIOS = ("valor", "fonte", "data", "hardware_versao", "comando")

def conexao() -> sqlite3.Connection:
    c = sqlite3.connect(BANCO)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c

def inicializar() -> None:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    with conexao() as c:
        c.executescript((RAIZ / "db" / "schema.sql").read_text(encoding="utf-8"))
        for f in json.loads((RAIZ / "db" / "fases-seed.json").read_text(encoding="utf-8")):
            c.execute("""INSERT INTO fases (id,numero,nome,prioridade,status,criterio_aceite,evidencia)
                         VALUES (:id,:numero,:nome,:prioridade,:status,:criterio_aceite,:evidencia)
                         ON CONFLICT(id) DO UPDATE SET numero=:numero,nome=:nome,prioridade=:prioridade,
                           status=:status,criterio_aceite=:criterio_aceite,evidencia=:evidencia""", f)
        # inventario de cameras (CSV real)
        csvp = RAIZ / "bench" / "inventario-cameras.csv"
        if csvp.exists():
            with open(csvp, newline="", encoding="utf-8") as fh:
                for linha in csv.DictReader(fh):
                    if not (linha.get("id") or "").strip():
                        continue
                    linha["id"] = linha["id"].strip()
                    colunas = ["id","fabricante_modelo","ip","porta","protocolo","canal_gravador",
                               "resolucao","fps","codec_nativo","credencial_ref","local_instalacao","restricao_acesso"]
                    c.execute(f"INSERT OR REPLACE INTO inventario_cameras ({','.join(colunas)}) "
                              f"VALUES ({','.join(':'+k for k in colunas)})", {k: linha.get(k, "") for k in colunas})
        # medicoes da bancada (JSON real) -> uma linha por medicao, com os 5 campos
        for jp in sorted((RAIZ / "bench" / "saida").glob("*.json")) if (RAIZ / "bench" / "saida").exists() else []:
            try:
                d = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:
                continue
            hw = f"{d['hardware']['gpu']} | {d['versoes']['ffmpeg'].split(' Copyright')[0]}"
            for m in d.get("medicoes", []):
                if m.get("status") != "ok":
                    continue
                valor = (f"bitrate {m.get('bitrate_cod_mbps')} Mbps; corte {m.get('corte_pct')}%; "
                         f"VMAF {m.get('vmaf')}; {m.get('vezes_tempo_real')}x tempo real")
                comando = m.get("comando", "")
                fonte_rel = str(jp.relative_to(RAIZ).as_posix())
                ja = c.execute("SELECT 1 FROM medicoes WHERE valor=? AND fonte=? AND comando=?",
                               (valor, fonte_rel, comando)).fetchone()
                if not ja:
                    c.execute("""INSERT INTO medicoes (valor,fonte,data,hardware_versao,comando,fase_id)
                                 VALUES (?,?,?,?,?,?)""",
                              (valor, fonte_rel, d["gerado_em"], hw, comando, "fase-0a"))
        # evidencias
        ev = [("fase-0a","bench/EVIDENCIA-fase0a.md","Evidencia da Fase 0-A (medicoes, SRT e teste negativo)","2026-11-06"),
              ("fase-0a","bench/saida/resultado-fase0.json","Registro bruto das medicoes","2026-11-06"),
              ("fase-3","bench/painel-bancada.html","Painel de bancada (este portal, versao local)","2026-11-06")]
        for f, caminho, desc, data in ev:
            if not c.execute("SELECT 1 FROM evidencias WHERE caminho=?", (caminho,)).fetchone():
                c.execute("INSERT INTO evidencias (fase_id,caminho,descricao,data) VALUES (?,?,?,?)", (f, caminho, desc, data))

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

PORTA_WEBRTC, PORTA_HLS, PORTA_API_MEDIAMTX = 8889, 8888, 9997

def mediamtx_paths() -> dict:
    """Le o estado real do lado terra (mediamtx) pela API dele."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTA_API_MEDIAMTX}/v3/paths/list", timeout=3) as r:
            dados = json.loads(r.read().decode())
        return {p["name"]: p for p in dados.get("items", [])}
    except Exception:
        return {}

def ler_json(caminho: Path) -> dict:
    """Leitura tolerante: arquivo escrito por outro processo pode estar parcial."""
    for _ in range(3):
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            import time as _t; _t.sleep(0.1)
    return {}

def fluxos() -> dict:
    st = RAIZ / "ground" / "status.json"
    dados = ler_json(st) if st.exists() else {"fluxos": [], "atualizado_em": None}
    mt = mediamtx_paths()
    cfg = json.loads((RAIZ / "ground" / "receivers.json").read_text(encoding="utf-8"))
    for c in cfg:
        p = mt.get(c["id"], {})
        dados.setdefault("fluxos", [])
        item = next((f for f in dados["fluxos"] if f["id"] == c["id"]), None)
        if item is None:
            item = {"id": c["id"], "rotulo": c["rotulo"], "srt_port": c["srt_port"]}
            dados["fluxos"].append(item)
        item.update({
            "no_ar": bool(p.get("ready")),
            "tracks": p.get("tracks", []),
            "leitores": p.get("readers", []),
            "link_webrtc": f"http://127.0.0.1:{PORTA_WEBRTC}/{c['id']}/whep",
            "link_hls_mediamtx": f"http://127.0.0.1:{PORTA_HLS}/{c['id']}/index.m3u8",
        })
    dados["mediamtx"] = {"porta_webrtc": PORTA_WEBRTC, "porta_hls": PORTA_HLS, "porta_api": PORTA_API_MEDIAMTX,
                         "ativo": bool(mt)}
    return dados

def ler_tudo() -> dict:
    with conexao() as c:
        q = lambda sql, *a: [dict(r) for r in c.execute(sql, a).fetchall()]
        return {
            "fases": q("SELECT * FROM fases ORDER BY numero, id"),
            "medicoes": q("SELECT * FROM medicoes ORDER BY id DESC"),
            "inventario": q("SELECT * FROM inventario_cameras ORDER BY id"),
            "evidencias": q("SELECT * FROM evidencias ORDER BY fase_id, id"),
            "gerado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(RAIZ / "portal"), **kw)

    def log_message(self, *a):  # silencio
        pass

    def end_headers(self) -> None:  # o HTML do portal nao pode ficar em cache:
        # pagina antiga em cache ja ficou rodando em paralelo e abriu sessao de video a cada ciclo
        if self.path.endswith((".html", ".css", ".js")) or self.path in ("/", ""):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def _json(self, codigo: int, corpo: dict) -> None:
        b = json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self) -> None:  # noqa: N802
        rota = urlparse(self.path).path
        if rota == "/api/resumo":
            return self._json(200, ler_tudo())
        if rota == "/api/fases":
            return self._json(200, {"fases": ler_tudo()["fases"]})
        if rota == "/api/medicoes":
            return self._json(200, {"medicoes": ler_tudo()["medicoes"]})
        if rota == "/api/inventario":
            return self._json(200, {"inventario": ler_tudo()["inventario"]})
        if rota == "/api/fluxos":
            return self._json(200, fluxos())
        if rota == "/api/saude":
            return self._json(200, {"ok": True, "banco": str(BANCO), "python": sys.version.split()[0]})
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/medicoes":
            return self._json(404, {"erro": "rota inexistente"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            dados = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"erro": "JSON invalido"})
        codigo, corpo = inserir_medicao(dados)
        return self._json(codigo, corpo)

def principal() -> int:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    inicializar()
    print(f"[ok] portal em http://127.0.0.1:{porta}/  (api: /api/resumo)")
    ThreadingHTTPServer(("127.0.0.1", porta), Handler).serve_forever()
    return 0

if __name__ == "__main__":
    sys.exit(principal())
