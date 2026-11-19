#!/usr/bin/env python3
"""FLAG DE ESTADO (0.7.0): o cliente ativa na tela e o BORDO liga a camera — sem terra alcancar o bordo.

Regras do dono (19/11/2026):
  * "nao podemos contar que o computador de captura a bordo tera porta aberta para receber comandos ou
    informacoes, a unica certeza e' de que ele podera enviar";
  * "o computador de captura a bordo precisa ficar olhando para terra e sempre que a flag mudar, ele
    inicia ou para a transmissao";
  * "terra (vps) precisa saber se a tela foi fechada, computador desligado ou falta de conexao no
    computador do usuario para interromper a transmissao, a menos que haja outro usuario conectado".

    python tests/e2e-flag-de-estado-liga-a-camera.py

O que este teste mede (com camera REAL e o agente de verdade):

  1) em repouso: NENHUM ffmpeg do fluxo em lugar nenhum;
  2) o CLIENTE inicia a transmissao na tela (`POST /api/transmissao/iniciar`): a sessao nasce `pedida`;
  3) o bordo LE A FLAG (`GET /api/estado-desejado`) e, so' porque o desejo virou `ligar`, abre a camera
     — medido por processo (ffmpeg do fluxo no ar no bordo, NADA no lado terra);
  4) o bordo CONTA o estado real (`POST /api/estado-real`): a sessao do cliente vira `no_ar` no lado terra
     e a trilha guarda `desejo_camera_mudou` + `estado_real_do_bordo`;
  5) a ORDEM que o lado terra escreveu na fila (compatibilidade com a 0.6.10 instalada) fica `atendida`
     quando o bordo conta `no_ar` — senao o vigia do "sem resposta" mataria a sessao com a camera no ar;
  6) o cliente SAI da tela (`POST /api/transmissao/sair`): o desejo vira `parar`, o bordo desliga a
     camera (nenhum ffmpeg) e ela volta a `parado` no estado real.

Sem dispositivo de video nesta maquina a parte ao vivo e' declarada NAO MEDIDA (o resto roda).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
TOKEN = "token-de-ingestao-do-teste"
FLUXO = "vivo-flag-1901"
MEDIAMTX = RAIZ / "tools" / "mediamtx" / ("mediamtx.exe" if os.name == "nt" else "mediamtx")
CONF_MEDIAMTX = RAIZ / "ground" / "mediamtx.yml"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def porta_livre(excluir=None) -> int:
    excluir = excluir or set()
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        if p not in excluir:
            return p


def portas_tomadas() -> set:
    tomadas = set()
    for p in (8890, 9997):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) == 0:
                tomadas.add(p)
    return tomadas


def pedir(metodo, url, corpo=None, cookie="", token=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=40) as f:
            return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def comandos_dos_ffmpeg() -> list:
    if os.name == "nt":
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
                            "Select-Object -ExpandProperty CommandLine"],
                           capture_output=True, text=True, errors="replace")
        return [l for l in (r.stdout or "").splitlines() if l.strip()]
    r = subprocess.run(["bash", "-lc", "pgrep -af ffmpeg || true"], capture_output=True, text=True,
                       errors="replace")
    return [l for l in (r.stdout or "").splitlines() if l.strip()]


def ffmpeg_do_fluxo(fluxo: str) -> list:
    return [l for l in comandos_dos_ffmpeg() if fluxo in l]


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError(f"a API saiu com codigo {proc.returncode}: "
                               + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-500:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu: " + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-500:])


def sessao_de(con, uid, email, papel, cliente_id="lecsor"):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id, senha, salt))
    tok = "tok-" + uid
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    return tok


def espera(cond, teto_s=70.0) -> bool:
    fim = time.time() + teto_s
    while time.time() < fim:
        if cond():
            return True
        time.sleep(1.0)
    return False


def um(banco: pathlib.Path, sql: str, args=()):
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def contagem(banco: pathlib.Path, sql: str, args=()) -> int:
    con = sqlite3.connect(str(banco))
    try:
        return int(con.execute(sql, args).fetchone()[0])
    finally:
        con.close()


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-flag-"))
    terra_db, bordo_db = tmp / "terra.db", tmp / "bordo.db"
    p_terra = porta_livre()
    p_bordo = porta_livre({p_terra})
    procs: list = []
    faixas: list = [None]
    tomadas = portas_tomadas()
    if tomadas & {8890, 9997}:
        nota(f"mediamtx nao subiu por mim: as portas {sorted(tomadas)} ja' estao em uso")
    elif MEDIAMTX.exists() and CONF_MEDIAMTX.exists():
        log = (tmp / "mediamtx.log").open("wb")
        faixas[0] = subprocess.Popen([str(MEDIAMTX), str(CONF_MEDIAMTX)], cwd=str(RAIZ),
                                     stdout=log, stderr=subprocess.STDOUT)
        time.sleep(2.5)

    try:
        base_cfg = f"http://127.0.0.1:{p_terra}"
        proc_t = sobe_api(terra_db, p_terra, {"LECSOR_LADO_TERRA_API": base_cfg,
                                              "LECSOR_BIND": "0.0.0.0",
                                              "LECSOR_TOKEN_INGESTAO": TOKEN})
        procs.append(proc_t)
        proc_b = sobe_api(bordo_db, p_bordo, {"LECSOR_EMBARCACAO": "bancada",
                                              "LECSOR_LADO_TERRA_API": base_cfg,
                                              "LECSOR_TOKEN_INGESTAO": TOKEN,
                                              "LECSOR_PORTA_API": str(p_bordo)})
        procs.append(proc_b)
        base_terra, base_bordo = f"http://127.0.0.1:{p_terra}", f"http://127.0.0.1:{p_bordo}"

        _, disp = pedir("GET", base_bordo + "/api/dispositivos")
        video = (disp.get("dispositivos") or disp.get("video") or [])
        nomes = [d.get("video") if isinstance(d, dict) else d for d in video]
        dispositivo = (nomes or [""])[0]
        nota(f"dispositivos de video desta maquina: {nomes or 'nenhum'}")

        for banco in (terra_db, bordo_db):
            con = sqlite3.connect(str(banco))
            con.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
            con.execute("INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
            con.execute("""INSERT OR REPLACE INTO cameras
                           (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo)
                           VALUES ('cam-01','bancada','Proa',?,'',1,'','','rtsp','','300k')""", (FLUXO,))
            con.commit()
            con.close()
        con = sqlite3.connect(str(bordo_db))
        con.execute("""INSERT INTO ingestoes (fluxo_id,rotulo,fonte,tipo,repetir,codec,bitrate_alvo,
                       resolucao,fps,estado,srt_host,criado_em,atualizado_em)
                       VALUES (?,?,?,'camera',1,'libx264','300k','1280x720',30,'parado','127.0.0.1',?,?)""",
                    (FLUXO, "cam-01", f"dshow:{dispositivo or 'ENTRADA-INEXISTENTE'}",
                     dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                     dt.datetime.now().astimezone().isoformat(timespec="seconds")))
        con.commit()
        con.close()
        con = sqlite3.connect(str(terra_db))
        tok = sessao_de(con, "cli-1", "cliente@lecsor.test", "cliente", "lecsor")
        con.close()

        # --- 1) em repouso nada roda
        exigir(not ffmpeg_do_fluxo(FLUXO), f"em repouso nenhum ffmpeg do fluxo roda ({len(ffmpeg_do_fluxo(FLUXO))})")

        # --- 2) o cliente inicia a transmissao na tela
        st, ji = pedir("POST", base_terra + "/api/transmissao/iniciar", {"camera_id": "cam-01"}, cookie=tok)
        tid = ((ji.get("transmissao") or {}).get("id") or "")
        exigir(st == 201 and tid, f"o cliente iniciou a transmissao e a sessao nasceu ({st}, {str(ji)[:90]})")

        # --- a FLAG ja' existe ANTES de qualquer bordo perguntar (e terra nao abriu camera)
        st, jd = pedir("GET", base_terra + f"/api/estado-desejado?embarcacao_id=bancada", token=TOKEN)
        cams = {c["camera_id"]: c for c in (jd.get("cameras") or [])}
        exigir(st == 200 and cams.get("cam-01", {}).get("desejo") == "ligar",
               f"a flag em terra diz LIGAR para cam-01 ({cams.get('cam-01', {}).get('desejo')!r}, "
               f"motivo {str(cams.get('cam-01', {}).get('motivo'))[:50]!r})")
        exigir(contagem(terra_db, "SELECT COUNT(*) FROM auditoria_acesso WHERE acao='desejo_camera_mudou' "
                                   "AND alvo LIKE 'cam-01 -> ligar%'") == 1,
               "a trilha registrou a mudanca do desejo de cam-01 para LIGAR (desejo_camera_mudou)")
        exigir(not ffmpeg_do_fluxo(FLUXO), "o lado terra nao abriu camera nenhuma so' por ter o desejo")

        if not dispositivo or not (tomadas or MEDIAMTX.exists()):
            nota("NAO MEDIDO: sem dispositivo de video ou sem mediamtx — a parte ao vivo fica de fora")
        else:
            # --- 3) o agente do bordo OLHA a flag e obedece
            env_ag = dict(os.environ)
            env_ag.update({"LECSOR_LADO_TERRA_API": base_cfg,
                           "LECSOR_EMBARCACAO": "bancada",
                           "LECSOR_TOKEN_INGESTAO": TOKEN,
                           "LECSOR_PORTA_LOCAL": str(p_bordo),
                           "LECSOR_ORDENS_ESTADO": str(tmp / "ligados.json"),
                           "LECSOR_ESPERA_DA_FLAG": "1",
                           "PYTHONIOENCODING": "utf-8"})
            agente = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "agente_de_ordens.py")],
                                     cwd=str(RAIZ), env=env_ag,
                                     stdout=(tmp / "agente.log").open("wb"), stderr=subprocess.STDOUT)
            procs.append(agente)
            entrou = espera(lambda: len(ffmpeg_do_fluxo(FLUXO)) >= 1, 70.0)
            exigir(entrou, f"o bordo obedeceu a flag: a camera esta' NO AR (ffmpeg do fluxo: {len(ffmpeg_do_fluxo(FLUXO))})")

            # --- 4) o bordo conta o estado real e a sessao do cliente acompanha
            no_ar = espera(lambda: um(terra_db, "SELECT estado FROM transmissoes WHERE id=?", (tid,)).get("estado") == "no_ar", 40.0)
            est = um(terra_db, "SELECT * FROM estado_bordo WHERE camera_id='cam-01'")
            exigir(no_ar and est.get("estado") == "no_ar",
                   f"o bordo contou o estado real e a sessao virou no_ar (sessao={um(terra_db, 'SELECT estado FROM transmissoes WHERE id=?', (tid,)).get('estado')!r}, "
                   f"bordo={est.get('estado')!r})")
            exigir(contagem(terra_db, "SELECT COUNT(*) FROM auditoria_acesso WHERE acao='estado_real_do_bordo'") >= 1,
                   "a trilha registrou o estado real contado pelo bordo")
            # --- 5) compatibilidade: a ordem escrita na fila fica atendida
            exigir(um(terra_db, "SELECT estado FROM ordens_do_bordo WHERE camera_id='cam-01' AND acao='iniciar' "
                                "ORDER BY seq DESC").get("estado") == "atendida",
                   "a ordem antiga da fila ficou 'atendida' quando o bordo contou no_ar (nada de 'sem resposta')")

            # --- 6) o cliente sai da tela: o desejo vira parar e o bordo desliga
            st, js = pedir("POST", base_terra + "/api/transmissao/sair", {}, cookie=tok)
            exigir(st == 200 and js.get("sessoes_fechadas") == 1,
                   f"o cliente saiu da tela e a sessao dele caiu ({st}, {str(js)[:70]})")
            morreu = espera(lambda: not ffmpeg_do_fluxo(FLUXO), 70.0)
            parou = espera(lambda: um(terra_db, "SELECT estado FROM estado_bordo WHERE camera_id='cam-01'").get("estado") == "parado", 30.0)
            exigir(morreu, f"o bordo obedeceu o parar: nenhum ffmpeg do fluxo ({len(ffmpeg_do_fluxo(FLUXO))})")
            exigir(parou, "o bordo contou 'parado' no estado real")
            exigir(contagem(terra_db, "SELECT COUNT(*) FROM auditoria_acesso WHERE acao='desejo_camera_mudou' "
                                       "AND alvo LIKE 'cam-01 -> parar%'") == 1,
                   "a trilha registrou a volta do desejo de cam-01 para PARAR")
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        if faixas[0]:
            try:
                faixas[0].terminate()
            except Exception:
                pass

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — a flag de estado funciona: o cliente ativa na tela, terra publica o desejo, o bordo OLHA "
          "e liga a camera, conta o que subiu, e quando o cliente sai o bordo desliga")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
