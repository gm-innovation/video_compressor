#!/usr/bin/env python3
"""O HD FULL-TIME DO RADAR ACHA O DISPOSITIVO SOZINHO (dono, 26/11/2026).

Palavras do dono, com a tela na mao:

    "tem dispositivo sim, ele precisa detectar pelo nome que eu crio em terra ou pelo tipo que e'
     selecionado do app do admin"

Ate' aqui o gravador dependia de uma variavel (`LECSOR_HD_DISPOSITIVO`) que ninguem definia: a tela
dizia "Gravação full-time: ligada — radar, 0 bloco(s)" para sempre e nao havia pista nenhuma do porque.
O que esta prova mede, na ORDEM das decisoes do dono:

  1) o TIPO que o admin escolheu MANDA — a camera marcada como `radar` no cadastro decide o
     dispositivo do HD (casamento pelo ID do dispositivo, o mesmo que a varredura usa);
  2) sem casar pelo id (placa nova, id novo), vale o NOME que o admin criou em terra ("detectar pelo
     nome que eu crio em terra");
  3) se nada casar NAO ha' dispositivo e a resposta traz o MOTIVO — nunca um "ligado" mudo;
  4) sem nenhuma camera de radar no cadastro, o motivo diz exatamente isso;
  5) a escolha JA APLICADA nesta maquina (config_local) vence o palpite da varredura;
  6) `LECSOR_HD_DISPOSITIVO` continua valendo — mas como ajuste de bancada (origem "env");
  7) a pagina do bordo (HTTP `/api/bordo`) publica o dispositivo, a ORIGEM e o motivo — e o catalogo
     que chega ao cliente carrega o MOTIVO medido a bordo (a tela de terra tem o que escrever).

    python tests/test-o-hd-acha-o-dispositivo-do-radar.py
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
GROUND = RAIZ / "ground"
sys.path.insert(0, str(GROUND))

falhas: list[str] = []

# o seletor REAL de um aparelho de video ligado nesta maquina (o `@device_pnp_...` e' unico por aparelho)
SELETOR = "@device_pnp_usb\\vid_345f&pid_2131&mi_00\\6&f69"
NOME_DO_APARELHO = "USB Video Device"
TOKEN = "token-da-prova-do-hd-acha-o-dispositivo"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(metodo, url, corpo=None, cookie=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            try:
                return f.status, json.loads(b or b"{}"), b
            except Exception:
                return f.status, {}, b
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}"), b
        except Exception:
            return e.code, {}, b


def executa(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def um(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def sessao_de(con, uid, email, papel="cliente", cliente_id="lecsor"):
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


def sobe_api(banco: pathlib.Path, porta: int):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT",
              "LECSOR_HD_DISPOSITIVO"):
        env.pop(k, None)
    log = (banco.parent / f"api-{porta}.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(GROUND / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: " + (banco.parent / f"api-{porta}.log").read_text(
                errors="replace")[-800:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def aparelho(video=NOME_DO_APARELHO, seletor=SELETOR):
    """Um aparelho de video como o ffmpeg devolve: nome amigavel + seletor unico."""
    return {"video": video, "seletor": seletor, "rotulo": video, "indice": 0}


def main() -> int:
    import varredura_do_bordo as v            # a MESMA funcao de id que a varredura usa
    id_do_aparelho = v._id_da_camera(aparelho(), set())
    nota(f"o id que a varredura da' a este aparelho: {id_do_aparelho}")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-hd-acha-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    proc = None
    try:
        proc = sobe_api(banco, porta)          # cria o ESQUEMA no banco do bordo
        base = f"http://127.0.0.1:{porta}"

        executa(banco, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        executa(banco, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")

        def poe_radar(camera_id, rotulo="Radar de Óleo", tipo="radar", definido=1):
            executa(banco, """INSERT OR REPLACE INTO cameras
                              (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,
                               tipo,tipo_definido_pelo_admin)
                              VALUES (?, 'bancada', ?, '', 'mastro', 1, '', '', 'dshow', '', '300k', ?, ?)""",
                    (camera_id, rotulo, tipo, definido))

        poe_radar(id_do_aparelho)
        # uma camera COMUM, para provar que quem manda e' o TIPO (o radar), nao a ordem da tabela
        executa(banco, """INSERT OR REPLACE INTO cameras
                          (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,
                           tipo,tipo_definido_pelo_admin)
                          VALUES ('cam-comum','bancada','Camera de proa','','proa',1,'','','dshow','',
                                  '300k','',0)""")

        # ---- as leituras do gravador, no processo do teste, com o ffmpeg trocado por um FIXO --------
        os.environ["LECSOR_BANCO"] = str(banco)
        os.environ["LECSOR_HD_DIR"] = str(tmp / "hd")
        os.environ.pop("LECSOR_HD_DISPOSITIVO", None)
        import ingestao
        import api
        import gravacao_continua as g

        def aparelhos(lista, **extra):
            d = {"video": [x["video"] for x in lista], "audio": [], "dispositivos": lista,
                 "padrao": (lista[0]["video"] if lista else ""), "maquina": "bancada-de-prova"}
            d.update(extra)
            return d

        def resolver(lista, **extra):
            ingestao.listar_dispositivos = lambda: aparelhos(lista, **extra)
            g._RESOLUCAO.update(em=0.0, valor=None)     # derruba o cache de 60 s
            return g.resolucao(recarregar=True)

        print()
        print("== 1. o TIPO que o admin escolheu MANDA (o bordo acha o aparelho sozinho)")
        r = resolver([aparelho(), aparelho("Webcam da bancada", "@device_pnp_usb\\vid_1111&pid_2222\\9&aa")])
        exigir(r.get("dispositivo") == SELETOR,
               f"o dispositivo veio do cadastro (o tipo radar), sem nenhuma variavel de ambiente [{r.get('dispositivo')}]")
        exigir(r.get("origem") == "tipo", f"e a resposta DIZ de onde veio: origem '{r.get('origem')}' (tipo)")
        exigir(r.get("camera") == id_do_aparelho and r.get("rotulo") == "Radar de Óleo",
               "a resposta carrega a camera que decidiu (id e nome que o admin deu)")
        exigir(not r.get("motivo"), "achando o aparelho nao ha' motivo de falha")

        print()
        print("== 2. sem casar pelo id, vale o NOME que o admin criou em terra")
        executa(banco, "DELETE FROM cameras WHERE id=?", (id_do_aparelho,))   # so' sobra o radar novo
        poe_radar("cam-placa-nova", rotulo="Radar de Óleo")
        r = resolver([aparelho("Radar de Óleo", "@device_pnp_usb\\vid_9999&pid_8888\\7&bb"),
                      aparelho()])
        exigir(r.get("dispositivo") == "@device_pnp_usb\\vid_9999&pid_8888\\7&bb",
               f"o bordo casou pelo NOME que o admin deu [{r.get('dispositivo')}]")
        exigir(r.get("origem") == "nome", f"e diz que foi pelo nome (origem '{r.get('origem')}')")

        print()
        print("== 3. se nada casar, NAO grava e DIZ o motivo (nunca um 'ligado' mudo)")
        r = resolver([aparelho("Webcam qualquer", "@device_pnp_usb\\vid_0001&pid_0002\\1&cc")])
        exigir(r.get("dispositivo") == "", "sem casar, nao ha' dispositivo nenhum (nada de chute)")
        exigir("nao casou" in (r.get("motivo") or "") and "Radar de Óleo" in (r.get("motivo") or ""),
               f"o motivo NOMEIA a camera do radar que nao casou [{r.get('motivo')}]")
        exigir("Webcam qualquer" in (r.get("motivo") or ""),
               "e LISTA o que o bordo viu nesta maquina (o admin consegue corrigir o cadastro)")
        motivo_medido = r.get("motivo") or ""

        r = resolver([], motivo="o ffmpeg nao encontrou camera nesta maquina: confira o driver")
        exigir(r.get("dispositivo") == "" and "ffmpeg" in (r.get("motivo") or ""),
               f"maquina sem camera nenhuma: o motivo e' o que o ffmpeg disse [{r.get('motivo')}]")

        print()
        print("== 4. sem camera marcada como radar, o motivo diz exatamente isso")
        executa(banco, "UPDATE cameras SET tipo='' WHERE id=?", (id_do_aparelho,))
        executa(banco, "UPDATE cameras SET tipo='' WHERE id='cam-placa-nova'")
        r = resolver([aparelho()])
        exigir(r.get("dispositivo") == "" and "radar de óleo" in (r.get("motivo") or "").lower(),
               f"nenhuma camera de radar no cadastro: o motivo manda marcar no admin [{r.get('motivo')}]")

        print()
        print("== 5. a escolha JA APLICADA nesta maquina vence o palpite da varredura")
        poe_radar(id_do_aparelho)
        executa(banco, """INSERT OR REPLACE INTO config_local (camera_id,chave,valor,atualizado_em)
                          VALUES (?,'dispositivo','@device_pnp_escolhido_a_mao',?)""",
                (id_do_aparelho, time.strftime("%Y-%m-%dT%H:%M:%S")))
        r = resolver([aparelho()])
        exigir(r.get("dispositivo") == "@device_pnp_escolhido_a_mao" and r.get("origem") == "cadastro",
               f"o aparelho apontado a mao (config_local) e' respeitado [{r.get('dispositivo')}]")
        executa(banco, "DELETE FROM config_local WHERE chave='dispositivo' AND camera_id=?",
                (id_do_aparelho,))

        print()
        print("== 6. `LECSOR_HD_DISPOSITIVO` continua valendo (ajuste de bancada / tecnico)")
        os.environ["LECSOR_HD_DISPOSITIVO"] = "@device_pnp_do_tecnico"
        r = resolver([aparelho()])
        exigir(r.get("dispositivo") == "@device_pnp_do_tecnico" and r.get("origem") == "env",
               f"a variavel de ambiente ainda manda, com origem 'env' [{r.get('dispositivo')}]")
        os.environ.pop("LECSOR_HD_DISPOSITIVO", None)

        print()
        print("== 7. as duas telas: a pagina do bordo e o catalogo que chega ao cliente")
        ingestao.listar_dispositivos = lambda: aparelhos([aparelho()])
        g._RESOLUCAO.update(em=0.0, valor=None)
        st, bordo, _ = pedir("GET", base + "/api/bordo")
        exigir(st == 200 and isinstance(bordo.get("gravacao"), dict),
               "a pagina do bordo devolve o estado do gravador (HTTP /api/bordo)")
        grav = bordo.get("gravacao") or {}
        exigir("dispositivo" in grav and "dispositivo_origem" in grav and "motivo" in grav
               and "camera_rotulo" in grav and "nome_dispositivo" in grav,
               f"o bloco do HD traz o dispositivo, a ORIGEM e o motivo medidos [{sorted(grav)[:6]}...]")
        exigir(bool(grav.get("dispositivo")) != bool(grav.get("motivo")),
               f"ou ha' dispositivo, ou ha' motivo — nunca os dois vazios e nunca 'ligado' sem os dois "
               f"[dispositivo={grav.get('dispositivo')!r} motivo={grav.get('motivo')!r}]")

        # o MOTIVO que o bordo mediu tem de sobreviver ate' a tela de terra (o cliente tem o que ler)
        executada = um(banco, "SELECT COUNT(*) c FROM hd_catalogo")["c"]
        con = sqlite3.connect(str(banco))
        tok = sessao_de(con, "cli-radar", "cliente@lecsor.test")
        con.close()
        executa(banco, """INSERT OR REPLACE INTO hd_catalogo (embarcacao_id,camera_id,resumo,blocos,atualizado_em)
                          VALUES ('bancada',?,?,?,?)""",
                (id_do_aparelho,
                 json.dumps({"ligada": True, "dispositivo": "", "motivo": motivo_medido,
                             "camera_rotulo": "Radar de Óleo", "camera_id": id_do_aparelho, "blocos": 0}),
                 json.dumps([]), time.strftime("%Y-%m-%dT%H:%M:%S")))
        st, cat, _ = pedir("GET", base + f"/api/hd/catalogo?camera_id={id_do_aparelho}", cookie=tok)
        exigir(st == 200, f"o cliente le o catalogo do HD (HTTP {st})")
        resumo = {}
        for c in (cat.get("catalogos") or []):
            if c.get("camera_id") == id_do_aparelho:
                resumo = c.get("resumo") or {}
                break
        exigir(resumo.get("motivo") == motivo_medido,
               f"o MOTIVO medido a bordo chega inteiro na tela de terra [{str(resumo.get('motivo'))[:70]}...]")
        exigir(not resumo.get("dispositivo") and resumo.get("camera_rotulo") == "Radar de Óleo",
               "e o catalogo diz o NOME do radar e que nao houve dispositivo (o cliente entende o vazio)")
        nota(f"catalogos antes da prova: {executada}")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except Exception:  # noqa: BLE001
                proc.kill()

    print()
    if falhas:
        print(f"RESULTADO: {len(falhas)} falha(s)")
        for f in falhas:
            print("  -", f)
        return 1
    print("RESULTADO: tudo passou — o HD full-time acha o dispositivo pelo tipo/nome do admin e, quando "
          "nao acha, diz o motivo nas duas telas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
