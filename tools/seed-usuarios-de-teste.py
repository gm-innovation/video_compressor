#!/usr/bin/env python3
"""Semente dos QUATRO TIPOS DE CLIENTE, para o dono testar (pedido de 26/11/2026: "preciso de
usuarios de todos os tipos de clientes para testar, essa que estamos utilizando aparentemente e' de
clientes que tem acesso a apenas uma embarcacao").

O TIPO nao e' um campo: ele e' DERIVADO dos vinculos (ver `escopo_do_cliente`, ground/api.py):

    observador  -> todas_as_empresas               (tipo 4 — Petrobras/IBAMA)
    0 vinculos  -> todas_as_embarcacoes_da_empresa (tipo 3)
    1 vinculo   -> uma_embarcacao_da_empresa       (tipo 1)
    2+ vinculos -> algumas_embarcacoes_da_empresa  (tipo 2)

Por isso a semente precisa de ESTRUTURA, nao de codigo: uma empresa com TRES embarcacoes, radar em
duas empresas e um usuario por tipo. Ela cria:

  * `teste-psv-2` e `teste-psv-3` na empresa `armador-demo` (que passa a ter 3 embarcacoes);
  * um RADAR DE OLEO em `teste-psv-2` (a `bancada` ja' tem, entao o observador ve radar em 2 empresas);
  * blocos no catalogo do HD (`hd_catalogo`) e UM trecho gravado em terra (`gravacoes` + o arquivo),
    para as duas tabelas da pagina "Gravacoes" nao nascerem vazias;
  * os 4 usuarios (3 clientes + 1 observador) e os vinculos de cada um.

Idempotente: o que ja' existe NAO e' tocado (rodar duas vezes nao duplica e nao troca senha de quem
ja' entrou). A senha inicial e' ALEATORIA e NUNCA e' impressa — quem passa a conhece-la e' quem
redefine pelo painel do admin (Usuarios -> "redefinir senha", que mostra uma vez na tela).

Uso:
  python3 tools/seed-usuarios-de-teste.py --banco /opt/pipeline/app/db/pipeline.db
  python3 tools/seed-usuarios-de-teste.py --banco ... --limpar
  python3 tools/seed-usuarios-de-teste.py --banco db/pipeline.db --sem-supabase   (bancada local)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path

INTERACOES = 200_000
PREFIXO = "TESTE"
EMB2, EMB3 = "teste-psv-2", "teste-psv-3"
CAM_RADAR, CAM_PROA, CAM_POPA = "teste-radar-psv2", "teste-cam-psv2", "teste-cam-psv3"
# um radar TAMBEM na terceira embarcacao: e' o que separa "uma" de "algumas da empresa" na pagina
# "Gravacoes" (o catalogo do HD tem conteudo nas duas, e nao so' na primeira)
CAM_RADAR3 = "teste-radar-psv3"
# uma embarcacao de TESTE na OUTRA empresa (`lecsor`), com radar: e' o que prova o tipo 4
# (observador = todas as embarcacoes de TODAS as empresas — sem duas empresas nao ha' o que medir)
EMB_LECSOR, CAM_RADAR_LECSOR = "teste-emb-lecsor", "teste-radar-lecsor"
CAMERAS_DE_TESTE = (CAM_RADAR, CAM_PROA, CAM_POPA, CAM_RADAR3, CAM_RADAR_LECSOR)
EMBARCACOES_DE_TESTE = (EMB2, EMB3, EMB_LECSOR)
TRANS = "teste-transmissao-1"
EMPRESA = "armador-demo"
# (id, email, nome, papel, embarcacoes concedidas)
USUARIOS = [
    ("teste-cliente-1", "cliente-1-embarcacao@demo.test",
     "TESTE · Cliente de UMA embarcação", "cliente", [EMB2]),
    ("teste-cliente-2", "cliente-2-embarcacoes@demo.test",
     "TESTE · Cliente de ALGUMAS embarcações", "cliente", [EMB2, EMB3]),
    ("teste-cliente-3", "cliente-todas-da-empresa@demo.test",
     "TESTE · Cliente de TODAS as da empresa", "cliente", []),
    ("teste-observador", "observador@demo.test",
     "TESTE · Observador (Petrobras/IBAMA)", "observador", []),
]


def agora() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def hash_senha(senha: str, salt: str) -> str:
    """Mesma conta do servidor (`hash_senha`, ground/api.py) — assim o login local confere."""
    return hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt), INTERACOES).hex()


def abrir(banco: str) -> sqlite3.Connection:
    c = sqlite3.connect(banco)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def existe(c, sql, args) -> bool:
    return c.execute(sql, args).fetchone() is not None


# ------------------------------------------------------------------ o que a semente cria

def criar_embarcacao(c, eid, nome, cliente=EMPRESA, imo=""):
    if existe(c, "SELECT 1 FROM embarcacoes WHERE id=?", (eid,)):
        return "ja' existia"
    c.execute("""INSERT INTO embarcacoes (id,cliente_id,nome,imo,estado)
                 VALUES (?,?,?,?,'em operacao')""", (eid, cliente, nome, imo))
    return "criada"


def criar_camera(c, cid, emb, rotulo, tipo="camera", local=""):
    if existe(c, "SELECT 1 FROM cameras WHERE id=?", (cid,)):
        return "ja' existia"
    c.execute("""INSERT INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,tipo,
                                      tipo_definido_pelo_admin)
                 VALUES (?,?,?,?,?,1,?,1)""", (cid, emb, rotulo, cid, local, tipo))
    return "criada"


def criar_blocos_do_hd(c, emb, cam, quantos=4, atraso_min=5):
    """Catalogo do HD do radar: blocos de 60 s, com o nome no padrao que o produto exige
    (`bloco-AAAAMMDD-HHMMSS.mp4`) — sem isso o "pedir" da tela seria recusado. O `atraso_min` muda o
    passo entre os blocos, para o catalogo de uma embarcacao nao ter os mesmos nomes do de outra."""
    linhas = []
    base = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    for i in range(quantos):
        quando = base - dt.timedelta(minutes=(i + 1) * atraso_min)
        linhas.append({"arquivo": "bloco-%s.mp4" % quando.strftime("%Y%m%d-%H%M%S"),
                       "inicio": quando.replace(microsecond=0).isoformat(),
                       "bytes": 12_000_000 + i * 250_000})
    blocos = list(reversed(linhas))
    resumo = {"blocos": len(blocos), "bytes": sum(b["bytes"] for b in blocos),
              "primeiro": blocos[0]["inicio"], "ultimo": blocos[-1]["inicio"], "livre": 900_000_000}
    c.execute("""INSERT INTO hd_catalogo (embarcacao_id,camera_id,resumo,blocos,atualizado_em)
                 VALUES (?,?,?,?,?)
                 ON CONFLICT(embarcacao_id,camera_id) DO UPDATE SET
                   resumo=excluded.resumo, blocos=excluded.blocos, atualizado_em=excluded.atualizado_em""",
              (emb, cam, json.dumps(resumo, ensure_ascii=False),
               json.dumps(blocos, ensure_ascii=False), agora()))
    return "%d bloco(s)" % len(blocos)


def criar_gravacao_em_terra(c, emb, cam, email, diretorio):
    """Um trecho que "ja' chegou em terra": a linha em `gravacoes`, a linha em `transmissoes` (o
    historico da tela) E o arquivo — e' o ARQUIVO que a tela consulta (`gravacao.estado`) para saber
    se existe gravacao e quanto ela tem."""
    if existe(c, "SELECT 1 FROM transmissoes WHERE id=?", (TRANS,)):
        return "ja' existia"
    fim = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    ini = fim - dt.timedelta(minutes=3)
    carimbo_ini = ini.isoformat(timespec="seconds")
    carimbo_fim = fim.isoformat(timespec="seconds")
    c.execute("""INSERT INTO transmissoes (id,seq,embarcacao_id,camera_id,fluxo_id,usuario_email,
                    segundos_max,criada_em,batimento_em,termina_em,encerrada_em,estado,motivo,gravando)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (TRANS, 0, emb, cam, cam, email, 900, carimbo_ini, carimbo_ini, carimbo_fim,
               carimbo_fim, "encerrada", "transmissao de TESTE (linha do historico)", 0))
    bytes_arq = 0
    if diretorio is not None:
        try:
            diretorio.mkdir(parents=True, exist_ok=True)
            alvo = diretorio / (TRANS + ".mp4")
            if not alvo.exists():
                # um mp4 de mentira, pequeno e reconhecivel: so' para a tela ter o que baixar no teste
                alvo.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048)
            bytes_arq = alvo.stat().st_size
        except OSError as e:
            print("  aviso: nao consegui escrever o arquivo da gravacao:", e)
    c.execute("""INSERT OR REPLACE INTO gravacoes (transmissao_id,embarcacao_id,usuario_email,camera_id,
                    comecou_em,bytes,segundos,pronta_em,avisada_em,baixada_em,apagada_em)
                 VALUES (?,?,?,?,?,?,180,?,'','','')""",
              (TRANS, emb, email, cam, carimbo_ini, bytes_arq, carimbo_fim))
    return "linha + arquivo de %d B" % bytes_arq


def criar_usuario(c, uid, email, nome, papel, concedidas, provisionar) -> str:
    if existe(c, "SELECT 1 FROM usuarios WHERE email=?", (email,)):
        return "ja' existia (senha NAO foi tocada)"
    senha = secrets.token_urlsafe(12)
    salt = secrets.token_hex(16)
    c.execute("""INSERT INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                 VALUES (?,?,?,?,?,?,?,?,1)""",
              (uid, email, nome, papel, (EMPRESA if papel == "cliente" else None),
               hash_senha(senha, salt), salt, INTERACOES))
    for e in concedidas:
        c.execute("""INSERT OR IGNORE INTO usuario_embarcacoes (usuario_id,embarcacao_id,concedido_por)
                     VALUES (?,?,'semente-de-teste')""", (uid, e))
    return provisionar(email, senha, nome)


def montar(banco: str, provisionar) -> None:
    c = abrir(banco)
    print("== banco:", banco)
    if not existe(c, "SELECT 1 FROM clientes WHERE id=?", (EMPRESA,)):
        print("ABORTA: a empresa %r nao existe neste banco" % EMPRESA)
        sys.exit(2)

    print("-- embarcações de teste (a empresa %s precisa de 3 para 'algumas' != 'todas')" % EMPRESA)
    print("   %s %s" % (EMB2, criar_embarcacao(c, EMB2, "PSV Exemplo II (teste)")))
    print("   %s %s" % (EMB3, criar_embarcacao(c, EMB3, "PSV Exemplo III (teste)")))
    print("   %s %s" % (EMB_LECSOR, criar_embarcacao(c, EMB_LECSOR, "Bancada de testes (LECSOR, teste)",
                                                    cliente="lecsor")))

    print("-- câmeras de teste (o RADAR é o que o observador enxerga)")
    print("   %s %s" % (CAM_RADAR, criar_camera(c, CAM_RADAR, EMB2, "TESTE · Radar de óleo · PSV II",
                                                tipo="radar", local="mastro")))
    print("   %s %s" % (CAM_PROA, criar_camera(c, CAM_PROA, EMB2, "TESTE · Proa · PSV II", local="proa")))
    print("   %s %s" % (CAM_POPA, criar_camera(c, CAM_POPA, EMB3, "TESTE · Popa · PSV III", local="popa")))
    print("   %s %s" % (CAM_RADAR3, criar_camera(c, CAM_RADAR3, EMB3, "TESTE · Radar de óleo · PSV III",
                                                tipo="radar", local="mastro")))
    print("   %s %s" % (CAM_RADAR_LECSOR,
                        criar_camera(c, CAM_RADAR_LECSOR, EMB_LECSOR,
                                     "TESTE · Radar de óleo · Bancada LECSOR", tipo="radar", local="mastro")))

    print("-- catalogo do HD do radar (o que a página \"Gravações\" lista do bordo)")
    print("   %s: %s" % (CAM_RADAR, criar_blocos_do_hd(c, EMB2, CAM_RADAR)))
    print("   %s: %s" % (CAM_RADAR3, criar_blocos_do_hd(c, EMB3, CAM_RADAR3, atraso_min=17)))
    print("   %s: %s" % (CAM_RADAR_LECSOR, criar_blocos_do_hd(c, EMB_LECSOR, CAM_RADAR_LECSOR,
                                                             atraso_min=11)))

    print("-- um trecho gravado em terra (linha do histórico + o arquivo)")
    print("   %s: %s" % (TRANS, criar_gravacao_em_terra(c, EMB2, CAM_RADAR, USUARIOS[0][1],
                                                       DIRETORIO_DE_GRAVACOES)))

    print("-- usuários (um por tipo; senha inicial aleatória, NUNCA impressa)")
    for uid, email, nome, papel, concedidas in USUARIOS:
        print("   %-38s %-11s vinculos=%s  supabase=%s"
              % (email, papel, ",".join(concedidas) or "0", criar_usuario(
                  c, uid, email, nome, papel, concedidas, provisionar)))
    c.commit()
    relatorio(c)


def relatorio(c) -> None:
    """Imprime o que CADA usuário deve enxergar — é isto que a prova confere contra o servidor."""
    print()
    print("== o que cada um deve enxergar")
    for uid, email, _nome, papel, _c in USUARIOS:
        n = c.execute("SELECT count(*) n FROM usuario_embarcacoes WHERE usuario_id=?", (uid,)).fetchone()["n"]
        if papel == "observador":
            escopo = "todas_as_empresas"
            embarcacoes = [r["id"] for r in c.execute(
                "SELECT id FROM embarcacoes ORDER BY id")]
            # o observador so' alcanca radar/FLIR
            alcance = [r["id"] for r in c.execute(
                """SELECT DISTINCT embarcacao_id AS id FROM cameras
                   WHERE tipo IN ('radar','flir') ORDER BY embarcacao_id""")]
        elif n == 0:
            escopo = "todas_as_embarcacoes_da_empresa"
            embarcacoes = alcance = [r["id"] for r in c.execute(
                "SELECT id FROM embarcacoes WHERE cliente_id=? ORDER BY id", (EMPRESA,))]
        else:
            escopo = "uma_embarcacao_da_empresa" if n == 1 else "algumas_embarcacoes_da_empresa"
            embarcacoes = alcance = [r["embarcacao_id"] for r in c.execute(
                "SELECT embarcacao_id FROM usuario_embarcacoes WHERE usuario_id=? ORDER BY embarcacao_id",
                (uid,))]
        print("   %-38s tipo=%-32s embarcacoes=%s" % (email, escopo, embarcacoes or "-"))
        if papel == "observador":
            print("   %-38s (com radar/FLIR: %s)" % ("", alcance or "-"))
    print()
    print("== HD publicado (blocos no catalogo)")
    for r in c.execute("""SELECT camera_id, embarcacao_id,
                                 json_array_length(blocos) AS n FROM hd_catalogo ORDER BY camera_id"""):
        print("   %-22s %-14s %s bloco(s)" % (r["camera_id"], r["embarcacao_id"], r["n"]))
    print()
    print("SENHAS: nada foi impresso. Redefina no painel (Usuarios -> redefinir senha) para entrar.")


def limpar(banco: str) -> None:
    c = abrir(banco)
    print("== limpando os dados de TESTE em", banco)
    ids_u = [u[0] for u in USUARIOS]
    emails = [u[1] for u in USUARIOS]
    marcas = ",".join("?" * len(ids_u))
    marcas_cam = ",".join("?" * len(CAMERAS_DE_TESTE))
    marcas_emb = ",".join("?" * len(EMBARCACOES_DE_TESTE))
    c.execute("DELETE FROM usuario_embarcacoes WHERE usuario_id IN (%s)" % marcas, ids_u)
    for cartao in (
        ("DELETE FROM gravacoes WHERE transmissao_id=?", (TRANS,)),
        ("DELETE FROM transmissoes WHERE id=?", (TRANS,)),
        ("DELETE FROM hd_pedidos WHERE camera_id IN (%s)" % marcas_cam, CAMERAS_DE_TESTE),
        ("DELETE FROM hd_catalogo WHERE camera_id IN (%s)" % marcas_cam, CAMERAS_DE_TESTE),
        ("DELETE FROM estado_bordo WHERE camera_id IN (%s)" % marcas_cam, CAMERAS_DE_TESTE),
        ("DELETE FROM cameras WHERE id IN (%s)" % marcas_cam, CAMERAS_DE_TESTE),
        ("DELETE FROM embarcacoes WHERE id IN (%s)" % marcas_emb, EMBARCACOES_DE_TESTE),
    ):
        c.execute(*cartao)
    c.execute("DELETE FROM usuarios WHERE id IN (%s)" % marcas, ids_u)
    c.commit()
    if DIRETORIO_DE_GRAVACOES is not None:
        try:
            (DIRETORIO_DE_GRAVACOES / (TRANS + ".mp4")).unlink()
            print("   arquivo de teste apagado:", DIRETORIO_DE_GRAVACOES / (TRANS + ".mp4"))
        except OSError:
            pass
    for t in ("usuarios", "cameras", "embarcacoes", "hd_catalogo", "transmissoes"):
        n = c.execute("SELECT count(*) n FROM " + t).fetchone()["n"]
        print("   %-14s %s linha(s)" % (t, n))
    print("   e-mails de teste que sobraram:",
          [r["email"] for r in c.execute("SELECT email FROM usuarios ORDER BY email")]
          or "nenhum")
    print("   (as contas de auth no Supabase NAO sao apagadas por aqui: sao credenciais, se ficarem"
          " sem uso podem ser removidas no painel do Supabase)")


# ------------------------------------------------------------------ entrada

def provisionador(sem_supabase: bool, raiz: Path):
    """Devolve a funcao que cria/atualiza a credencial no Supabase Auth (o login do produto e' la').

    Sem chave de servico (ou com --sem-supabase) devolve um aviso em vez de falhar: o usuario jah
    esta' no banco local, e o painel do admin ("redefinir senha") provisiona quando a rede existir.
    """
    if sem_supabase:
        return lambda email, senha, nome: "nao provisionado (--sem-supabase)"
    env = raiz / "ground" / ".env.local"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    sys.path.insert(0, str(raiz / "ground"))
    try:
        import supabase_auth  # noqa: PLC0415
        if not supabase_auth.pode_administrar():
            return lambda email, senha, nome: "sem chave de servico"
    except Exception as e:  # modulo ausente / sem rede de configuracao
        return lambda email, senha, nome: "sem modulo (%s)" % type(e).__name__

    def prov(email, senha, nome):
        try:
            r = supabase_auth.definir_senha(email, senha, nome)
            return "atualizado" if r.get("atualizado") else "criado"
        except Exception as e:
            return "falhou: %s" % type(e).__name__
    return prov


def main() -> int:
    p = argparse.ArgumentParser(description="Semente dos 4 tipos de cliente (LECSOR).")
    p.add_argument("--banco", default="/opt/pipeline/app/db/pipeline.db")
    p.add_argument("--raiz", default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--sem-supabase", action="store_true",
                   help="nao mexe no Supabase Auth (bancada local, sem .env.local)")
    p.add_argument("--limpar", action="store_true", help="remove TUDO que esta semente criou")
    args = p.parse_args()

    global DIRETORIO_DE_GRAVACOES
    raiz = Path(args.raiz)
    sys.path.insert(0, str(raiz / "ground"))
    DIRETORIO_DE_GRAVACOES = None
    try:
        import gravacao  # noqa: PLC0415
        env = raiz / "ground" / ".env.local"
        if env.exists():
            for linha in env.read_text(encoding="utf-8").splitlines():
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    k, v = linha.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        DIRETORIO_DE_GRAVACOES = gravacao.diretorio()
    except Exception as e:
        print("aviso: sem modulo de gravacao (%s) — o trecho de terra fica sem arquivo" % type(e).__name__)

    if args.limpar:
        limpar(args.banco)
        return 0
    montar(args.banco, provisionador(args.sem_supabase, raiz))
    return 0


DIRETORIO_DE_GRAVACOES = None

if __name__ == "__main__":
    raise SystemExit(main())
