#!/usr/bin/env python3
"""Fase 5 do radar: o radar da embarcacao entra AO VIVO, pela REDE, no lugar do arquivo.

O sinal de radar deixa de ser so' arquivo: entra por TCP (`tcp://host:porta`), no MESMO formato de
quadro medido no `.drq` (2.240 B, tipo=3), e cai na MESMA cadeia (desenho -> ffmpeg -> SRT -> mediamtx).
A bancada reproduz o radar com `ground/radar_tcp.py`, que serve o arquivo por TCP.

Provas (medidas, com mediamtx de verdade):
  1) pedido errado e' recusado com recado claro (`tcp://` sem porta) — nada de subir envio torto;
  2) RADAR FORA DO AR nao vira "no ar" mentiroso: com a porta fechada o caminho NAO fica pronto;
  3) com o radar servindo por TCP o caminho fica ONLINE no mediamtx, por SRT, em H264 — a mesma
     entrada da camera (nenhum caminho paralelo);
  4) o alvo de bitrate escolhido e' obedecido no que sai pela rede;
  5) o que trafega tem o tamanho do desenho (1.024x1.024 cinza = 1.048.576 B por quadro);
  6) o radar por TCP entrega a MESMA sinal que o arquivo (mesmo azimute/hora do primeiro quadro);
  7) parada limpa: o caminho sai do ar;
  8) a placa do dono (fonte por arquivo) continua funcionando: o conector e' escolhido pela fonte.

    python tests/test-radar-ao-vivo-tcp.py
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
MEDIAMTX = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
LADO = 1024
sys.path.insert(0, str(RAIZ / "ground"))


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def gravar_drq(caminho: pathlib.Path, voltas: int = 2, quadros_por_grau: int = 20) -> int:
    """Arquivo no MESMO formato do radar do dono: cabecalho 1.024 B + quadros de 2.240 B."""
    cab = bytearray(1024)
    struct.pack_into("<II", cab, 0, 0, 1)
    struct.pack_into("<II", cab, 128, 3539456, 4096)
    n = voltas * 360 * quadros_por_grau
    t0 = datetime.datetime(2026, 11, 6, 16, 44, 27)
    with open(caminho, "wb") as f:
        f.write(bytes(cab))
        for i in range(n):
            q = bytearray(2240)
            grau = (i // quadros_por_grau) % 360
            fino = (grau * 4096 // 360) % 4096
            dt = t0 + datetime.timedelta(seconds=i / (quadros_por_grau * 24.0))
            ft = int((dt - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)
            struct.pack_into("<II", q, 0, 3, 2240)
            struct.pack_into("<Q", q, 24, ft)
            struct.pack_into("<II", q, 40, grau, fino)
            struct.pack_into("<H", q, 188, 1024)
            for k in range(1024):
                v = 3000 - k // 2
                if abs(grau - 90) <= 1 and abs(k - 300) <= 3:
                    v = 4090
                struct.pack_into("<H", q, 192 + 2 * k, max(0, min(4095, v)))
            f.write(bytes(q))
    return n


def caminhos(porta_api: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{porta_api}/v3/paths/list", timeout=5) as f:
        return {p["name"]: p for p in json.load(f)["items"]}


def ler_exato(sock: socket.socket, n: int) -> bytes:
    """Le exatamente n bytes (MSG_WAITALL nao existe no socket do Windows)."""
    partes = b""
    while len(partes) < n:
        pedaco = sock.recv(n - len(partes))
        if not pedaco:
            break
        partes += pedaco
    return partes


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-radar-tcp-"))
    falhas: list[str] = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    if not MEDIAMTX.exists():
        print("PULADA: sem tools/mediamtx/mediamtx.exe — este teste precisa dele")
        return 0

    drq = tmp / "radar-teste.drq"
    quadros = gravar_drq(drq)
    print(f"  sinal de radar de teste: {drq.name} ({quadros} quadros)\n")

    porta_srt, porta_mtx_api, porta_rtsp = porta_livre(), porta_livre(), porta_livre()
    porta_radar = porta_livre()
    porta_vazia = porta_livre()                     # ninguem escuta aqui: radar FORA DO AR
    conf = tmp / "mediamtx.yml"
    conf.write_text(f"""logLevel: error
rtspAddress: 127.0.0.1:{porta_rtsp}
rtspTransports: [tcp]
srt: yes
srtAddress: 127.0.0.1:{porta_srt}
api: yes
apiAddress: 127.0.0.1:{porta_mtx_api}
metricsAddress: 127.0.0.1:{porta_livre()}
pprofAddress: 127.0.0.1:{porta_livre()}
playbackAddress: 127.0.0.1:{porta_livre()}
hls: no
webrtc: no
rtmp: no
playback: no
paths:
  all_others:
""", encoding="utf-8")
    log_mtx = (tmp / "mediamtx.log").open("wb")
    mtx = subprocess.Popen([str(MEDIAMTX), str(conf)], cwd=str(RAIZ / "tools" / "mediamtx"),
                           stdout=log_mtx, stderr=subprocess.STDOUT)

    log_radar = (tmp / "radar_tcp.log").open("wb")
    radar = None

    os.environ["LECSOR_BANCO"] = str(tmp / "pipeline.db")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ.pop("LECSOR_LADO_TERRA_API", None)
    os.environ.pop("LECSOR_TOKEN_INGESTAO", None)

    sujos: list[int] = []
    try:
        import sqlite3
        import ingestao
        import radar_drq

        con = sqlite3.connect(os.environ["LECSOR_BANCO"])
        for esquema in [RAIZ / "db" / "schema.sql"] + sorted(
                p for p in (RAIZ / "db").glob("schema*.sql") if p.name != "schema.sql"):
            con.executescript(esquema.read_text(encoding="utf-8"))
        con.execute("INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)"
                    " VALUES ('bancada','lecsor','Bancada de testes','','em operacao')")
        con.commit()
        con.close()

        pronto = False
        for _ in range(40):
            try:
                caminhos(porta_mtx_api)
                pronto = True
                break
            except Exception:
                time.sleep(0.5)
        if not pronto:
            print("FALHA o mediamtx de teste nao subiu; log:", (tmp / "mediamtx.log").read_text(errors="replace")[-300:])
            return 1

        # --- 1) pedido errado e' recusado com recado claro ---------------------------------------
        r1 = ingestao.ao_vivo(tipo="radar", radar_fonte="tcp://127.0.0.1")
        exigir("erro" in r1 and "porta" in str(r1.get("erro")).lower(),
               f"tcp:// sem porta e' recusado com recado claro ({r1.get('erro')})")
        r2 = ingestao.ao_vivo(tipo="radar", radar_fonte="")
        exigir("erro" in r2, f"radar sem fonte e' recusado ({r2.get('erro')})")

        # --- 2) radar FORA DO AR nao pode virar "no ar" mentiroso --------------------------------
        r_fora = ingestao.ao_vivo(tipo="radar", radar_fonte=f"tcp://127.0.0.1:{porta_vazia}",
                                  radar_modo="ppi", radar_taxa="30fps", bitrate="1000k",
                                  fluxo_id="radar-fora-do-ar", rotulo="Radar fora do ar",
                                  embarcacao_id="bancada", srt_host="127.0.0.1", srt_port=porta_srt)
        if r_fora.get("id"):
            sujos.append(int(r_fora["id"]))
        exigir("erro" not in r_fora, "o envio sobe e o erro do radar aparece depois (nao trava a tela)")
        ficou_pronto = None
        for _ in range(15):
            time.sleep(1)
            p = caminhos(porta_mtx_api).get("radar-fora-do-ar")
            if p and p.get("ready"):
                ficou_pronto = p
                break
        exigir(ficou_pronto is None, "radar FORA DO AR nao aparece como caminho pronto no mediamtx")
        if r_fora.get("id"):
            ingestao.parar(int(r_fora["id"]))
            sujos.remove(int(r_fora["id"]))
        con = sqlite3.connect(os.environ["LECSOR_BANCO"])
        estado = con.execute("SELECT estado, erro FROM ingestoes WHERE id=?", (int(r_fora.get("id") or 0),)).fetchone()
        con.close()
        exigir(bool(estado) and (estado[0] in ("erro", "parado")),
               f"o envio sem radar fica registrado como nao-no-ar ({estado})")
        exigir(bool(estado) and ("radar" in str(estado[1] or "").lower()),
               f"o recado do radar fora do ar fala do RADAR, nao de camera ({estado[1] if estado else None})")

        # --- 3) com o radar servindo por TCP, o caminho fica ONLINE -------------------------------
        radar = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "radar_tcp.py"), str(drq),
                                  "--porta", str(porta_radar), "--ritmo", "livre"],
                                 cwd=str(RAIZ), stdout=log_radar, stderr=subprocess.STDOUT)
        serviu = False
        for _ in range(20):
            try:
                with socket.create_connection(("127.0.0.1", porta_radar), timeout=1):
                    serviu = True
                    break
            except Exception:
                time.sleep(0.5)
        exigir(serviu, f"a bancada do radar esta servindo em tcp://127.0.0.1:{porta_radar}")

        r = ingestao.ao_vivo(tipo="radar", radar_fonte=f"tcp://127.0.0.1:{porta_radar}",
                             radar_modo="ppi", radar_taxa="30fps", bitrate="1000k",
                             fluxo_id="radar-ao-vivo-tcp", rotulo="Radar ao vivo (TCP)",
                             embarcacao_id="bancada", srt_host="127.0.0.1", srt_port=porta_srt)
        if r.get("id"):
            sujos.append(int(r["id"]))
        exigir("erro" not in r, f"o radar AO VIVO por TCP subiu (erro={r.get('erro')})")

        online = None
        for _ in range(30):
            time.sleep(1)
            p = caminhos(porta_mtx_api).get("radar-ao-vivo-tcp")
            if p and p.get("ready"):
                online = p
                break
        exigir(online is not None, "o radar que veio pela REDE ficou ONLINE no mediamtx")
        if online:
            exigir((online.get("source") or {}).get("type") == "srtConn",
                   f"entrou pela MESMA porta da camera (SRT): {online.get('source')}")
            exigir(any("H264" in str(t) for t in (online.get("tracks") or [])),
                   f"sobe H264 como a camera (trilhas: {online.get('tracks')})")

        # --- 4) o alvo escolhido e' obedecido no que sai pela rede --------------------------------
        p1 = caminhos(porta_mtx_api).get("radar-ao-vivo-tcp") or {}
        b1 = p1.get("bytesReceived") or 0
        time.sleep(6)
        p2 = caminhos(porta_mtx_api).get("radar-ao-vivo-tcp") or {}
        b2 = p2.get("bytesReceived") or 0
        kbps = (b2 - b1) * 8 / 6 / 1000
        exigir(kbps > 0, f"o radar ao vivo tem bitrate medido na rede ({kbps:.0f} kbps)")
        exigir(kbps <= 1000 * 2.5, f"o alvo de 1.000 kbps e' obedecido (medido {kbps:.0f} kbps)")

        # --- 6) a bancada mandou sinal e o produto leu o MESMO formato ---------------------------
        log_radar.flush()
        texto_radar = (tmp / "radar_tcp.log").read_text(errors="replace")
        exigir("cliente 127.0.0.1" in texto_radar, "a bancada registrou o produto conectando no radar")
        con = sqlite3.connect(os.environ["LECSOR_BANCO"])
        linha = con.execute("SELECT fonte, tipo FROM ingestoes WHERE fluxo_id=?",
                            ("radar-ao-vivo-tcp",)).fetchone()
        con.close()
        exigir(linha and linha[0].startswith("radar:tcp://"), f"a fonte registrada e' o radar pela rede ({linha})")
        exigir(linha and linha[1] == "radar", f"o registro diz que a fonte e' radar (tipo={linha[1]})")

        # o mesmo sinal, lido pelo conector do arquivo: o primeiro quadro tem de ser o MESMO radial
        r_arquivo = radar_drq.montar_quadro(drq.read_bytes()[1024:1024 + 2240], 0)
        con_tcp = socket.create_connection(("127.0.0.1", porta_radar), timeout=5)
        con_tcp.settimeout(5)
        q = ler_exato(con_tcp, 2240)
        r_tcp = radar_drq.montar_quadro(q, 0)
        con_tcp.close()
        exigir(r_arquivo is not None and r_tcp is not None and r_arquivo["az_fino"] == r_tcp["az_fino"]
               and r_arquivo["hora"] == r_tcp["hora"],
               "o radar pela rede entrega o MESMO sinal do arquivo (azimute e hora do 1o quadro)")

        px, info = next(radar_drq.quadros_ao_vivo_tcp("127.0.0.1", porta_radar, "ppi", "30fps", 30))
        exigir(len(px) == LADO * LADO, f"o quadro que vai ao ffmpeg e' 1.024x1.024 cinza ({len(px)} B)")
        exigir(info.get("az_graus") is not None, f"cada quadro traz o proprio azimute ({info.get('az_graus')})")

        # --- 7) parada limpa ---------------------------------------------------------------------
        parada = ingestao.parar(int(r["id"]))
        sujos.remove(int(r["id"]))
        exigir(parada.get("ok") is True, f"o radar ao vivo parou ({parada})")
        saiu = False
        for _ in range(20):
            time.sleep(0.5)
            p = caminhos(porta_mtx_api).get("radar-ao-vivo-tcp")
            if not p or not p.get("ready"):
                saiu = True
                break
        exigir(saiu, "o caminho do radar ao vivo saiu do ar depois da parada")

        # --- 8) a fonte por ARQUIVO continua funcionando (o conector vem da fonte) ----------------
        r_arq = ingestao.ao_vivo(tipo="radar", radar_fonte=str(drq), radar_modo="ppi",
                                 radar_taxa="volta", bitrate="800k", fluxo_id="radar-por-arquivo",
                                 rotulo="Radar por arquivo", embarcacao_id="bancada",
                                 srt_host="127.0.0.1", srt_port=porta_srt)
        if r_arq.get("id"):
            sujos.append(int(r_arq["id"]))
        exigir("erro" not in r_arq, f"o radar por arquivo continua subindo ({r_arq.get('erro')})")
        pronto_arq = False
        for _ in range(25):
            time.sleep(1)
            p = caminhos(porta_mtx_api).get("radar-por-arquivo")
            if p and p.get("ready"):
                pronto_arq = True
                break
        exigir(pronto_arq, "o radar por arquivo chega ao mediamtx (nenhuma fonte foi quebrada)")
        if r_arq.get("id"):
            ingestao.parar(int(r_arq["id"]))
            sujos.remove(int(r_arq["id"]))

    finally:
        for ident in list(sujos):
            try:
                ingestao.parar(int(ident))
            except Exception:
                pass
        for p in (radar, mtx):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except Exception:
                    p.kill()
        log_radar.close()
        log_mtx.close()

    print()
    if falhas:
        print(f"FALHAS ({len(falhas)}):")
        for f in falhas:
            print(" -", f)
        return 1
    print("TUDO OK — o radar entra ao vivo pela rede, na mesma cadeia, e para limpo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
