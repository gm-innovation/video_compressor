#!/usr/bin/env python3
"""O GRAVADOR E' O DONO DA CAMERA DO RADAR: o vivo le' o RELE' e o laco nao morre mais calado.

Incidente do dono (27/11/2026), palavras dele no app de captura: *"radar - parado - 5 bloco(s) no HD -
a gravacao full-time esta' ligada (desejo do admin), mas o gravador NAO esta' de pe'"*. A causa foi
fechada por MEDICAO: o `gravador.log` tem 5 execucoes do ffmpeg e **todas** as 5 terminam em
`Exiting normally, received signal 15.` — o ffmpeg do HD estava sendo MORTO pelo proprio app, porque o
vivo abria a MESMA camera (`liberar_camera()` mata quem tem `video=<camera>` na linha de comando) e,
depois, o laco morreu calado (o `gravador.pid` ficou no disco e ninguem o reergueu).

    python tests/test-rele-do-gravador-e-supervisor.py

Provas (a gravacao e' desviada para pasta de teste; nada do repositorio e' tocado):
  1) o RELE' nasce LIGADO e os enderecos sao os do mediamtx do produto;
  2) o spec do muxer `tee`: o BLOCO no HD vem primeiro (o HD nao depende do rele' para gravar), o rele'
     vem depois, e o `:` do caminho do Windows vai escapado (dentro do tee ele separa opcao);
  3) o `mediamtx.yml` do produto NAO repassa o caminho do rele' (`~^gravador-`) — senao o gravador,
     que publica 24h por dia, mandaria a banda embora sem ninguem pedindo;
  4) o `liberar_camera` (o texto do PowerShell que o produto executa) NAO mata o gravador;
  5) o vivo LE' o rele' quando a camera e' a do gravador — nunca abre o dispositivo;
  6) o `garantir()`: desejo desligado nao faz nada, sem dispositivo diz o motivo, e com o desejo ligado
     o laco e' REERGUIDO (foi o que faltou as 13:20:29);
  7) MEDICAO REAL: o ffmpeg e o mediamtx DO PRODUTO, com o spec DO PRODUTO — um encode, o bloco no HD
     E o fluxo no rele', lido por ffprobe ENQUANTO publica.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
GROUND = RAIZ / "ground"
falhas: list[str] = []


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def main() -> int:  # noqa: C901
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-rele-"))
    hd = tmp / "hd"
    hd.mkdir(parents=True, exist_ok=True)
    os.environ.pop("LECSOR_HD_DIR", None)
    os.environ["LECSOR_HD_DIR"] = str(hd)     # a prova NUNCA escreve no hd do repositorio
    os.environ.pop("LECSOR_HD_RELAY", None)   # o padrao do produto manda: o rele' nasce LIGADO
    os.environ["LECSOR_BLOCO_SEGUNDOS"] = "5"  # bloco curto: a prova do rele' nao dura 1 minuto
    sys.path.insert(0, str(GROUND))
    import gravacao_continua as g   # noqa: PLC0415
    import ingestao as ing          # noqa: PLC0415

    g.CONFIG_DO_HD = tmp / "config.json"
    g.RAIZ = tmp
    g._modulo_da_api = lambda: None   # a prova nao toca no banco do produto

    # 1) o RELE' nasce ligado e aponta para o mediamtx DO PRODUTO
    yml = (GROUND / "mediamtx.yml").read_text(encoding="utf-8")
    exigir(g.relay_ligado() is True, "o rele' do gravador nasce LIGADO (o vivo nao abre a camera)")
    exigir(g.MEDIAMTX_RTSP in g.MEDIAMTX_RTSP and g.MEDIAMTX_RTSP == "127.0.0.1:8554"
           and g.MEDIAMTX_SRT == "127.0.0.1:8890",
           f"os enderecos do rele' sao os do mediamtx do produto ({g.MEDIAMTX_RTSP} / {g.MEDIAMTX_SRT})")
    exigir(f"rtspAddress: {g.MEDIAMTX_RTSP}" in yml and f"srtAddress: {g.MEDIAMTX_SRT}" in yml,
           "e o mediamtx.yml do produto usa exatamente esses enderecos")

    g.camera_id = lambda: "cam-radar-de-teste"
    fluxo = g.fluxo_do_relay()
    exigir(fluxo == "gravador-cam-radar-de-teste", f"o caminho do rele' tem prefixo fixo ({fluxo})")
    exigir(g.url_do_relay() == f"rtsp://{g.MEDIAMTX_RTSP}/{fluxo}", "o vivo le' por RTSP local")
    exigir(g.destino_do_relay().startswith(f"srt://{g.MEDIAMTX_SRT}?")
           and g.destino_do_relay().endswith(f"streamid=publish:{fluxo}"),
           "e o gravador publica por SRT local, com o mesmo streamid do vivo")

    # 2) o spec do tee
    bloco = hd / "bloco-%Y%m%d-%H%M%S.mp4"
    spec = g.especificacao_do_tee(bloco)
    destinos = spec.split("|")
    exigir(len(destinos) == 2 and destinos[0].endswith(".mp4") and "f=segment" in destinos[0],
           "o PRIMEIRO destino do tee e' o BLOCO no HD (o HD nao depende do rele' para gravar)")
    exigir(destinos[1].startswith("[f=mpegts]srt\\://"), "o segundo destino e' o rele' no mediamtx local")
    exigir(destinos[1].count("\\:") >= 3 and destinos[1].endswith(fluxo),
           "e os `:` do endereco vao ESCAPADOS (dentro do tee, `:` separa opcao) — medido no prototipo")
    exigir("segment_format_options=movflags=+frag_keyframe+empty_moov+default_base_moof" in spec,
           "o bloco continua MP4 FRAGMENTADO (o play do trecho que ja' chegou depende disto)")
    cmd = g.comando_do_gravador()
    depois_do_an = cmd.index("-f", cmd.index("-an"))
    exigir(cmd[depois_do_an + 1] == "tee" and cmd[-1] == spec and cmd[cmd.index("-map") + 1] == "0:v",
           "o comando do gravador usa o muxer tee com o spec do produto (UM encode, dois destinos)")

    # 3) o caminho do rele' NAO entra no repasse para terra
    linhas = yml.splitlines()
    i = next((n for n, l in enumerate(linhas) if "~^gravador-" in l), -1)
    exigir(i >= 0, "o mediamtx.yml do produto declara o caminho do rele' (`~^gravador-`)")
    if i >= 0:
        exigir(linhas[i].strip().endswith("{}"),
               f"e ele NAO repassa para terra (a banda do gravador nao vai embora 24h): {linhas[i].strip()}")
    repasse = [l for l in linhas if "all_others" in l or "repasse.py" in l]
    exigir(len(repasse) == 2, f"quem repassa e' so' o `all_others` (o fluxo do vivo): {len(repasse)} linha(s)")

    # 4) o `liberar_camera` NAO mata o gravador (o texto que o produto executa de verdade)
    ps = ing._ps_do_liberar("@device_pnp_\\\\?\\usb#vid_345f&pid_2131", 4242)
    exigir("-ne $r" in ps and "4242" in ps, "o PowerShell da liberacao exclui o pid do laco do gravador")
    exigir("-ne $r" in ps and "$_.ParentProcessId -ne $r" in ps,
           "e tambem os FILHOS dele (o ffmpeg do HD e' filho do laco)")
    exigir("-notlike '*gravacao_continua*'" in ps, "e qualquer processo do modulo de gravacao continua")
    exigir("*video=@device_pnp_" in ps and "vid_345f" in ps,
           "sem deixar de soltar quem segura a camera (a funcao nao virou inutil)")

    # 5) o vivo LE' o rele' quando a camera e' a do gravador
    #    (identidade: pid + hora de criacao — um pid sozinho nao basta, o Windows recicla numero)
    import processos as _pr   # noqa: PLC0415
    g.gravador_pid = lambda: os.getpid()      # um pid VIVO (este processo) = o laco de pe'
    g.gravador_criado_em = lambda: _pr.criado_em(os.getpid())
    try:
        exigir(g.gravador_de_pe() is True, "com o pid do laco vivo, `gravador_de_pe()` e' True (a MEDIDA)")
        exigir(g.dono_da_camera("cam-radar-de-teste") is True,
               "e o gravador e' o DONO da camera do radar")
        exigir(g.dono_da_camera("cam-de-outro-dono") is False, "e NAO e' dono de outra camera")
        args = ing._args_fonte_viva("camera", "video=@device_pnp_\\\\?\\usb#vid_345f", "1280x720", 30,
                                    "cam-radar-de-teste")
        exigir(args and args[-1] == g.url_do_relay() and args[-1].startswith("rtsp://"),
               f"o vivo le' o RELE' em vez de abrir o dispositivo ({args[-1] if args else args!r})")
        exigir(ing._rele_do_gravador("cam-radar-de-teste") == g.url_do_relay(),
               "e o `iniciar()` enxerga o rele' (nao passa por `liberar_camera`)")
    finally:
        g.gravador_pid = lambda: 0
        g.gravador_criado_em = lambda: 0.0
    exigir(g.gravador_de_pe() is False and g.dono_da_camera("cam-radar-de-teste") is False,
           "sem o laco de pe', nada de rele': o vivo volta a abrir a camera (nunca fica mudo)")
    exigir(ing._rele_do_gravador("cam-radar-de-teste") == "",
           "e o ingest devolve \"\" nesse caso (o envio segue pela via de sempre)")

    # 6) o supervisor do laco
    antigo = {k: getattr(g, k) for k in ("ligada", "dispositivo", "_subir_gravador", "gravando_agora")}
    g.ligada = lambda: False
    r = g.garantir()
    exigir(r.get("ligada") is False and "subido" not in r, "desejo DESLIGADO: o supervisor nao sobe nada")
    g.ligada = lambda: True
    g.dispositivo = lambda: ""
    r = g.garantir()
    exigir(r.get("ok") is False and "dispositivo" in str(r.get("motivo")),
           f"desejo LIGADO sem dispositivo: DIZ o motivo, nao finge que grava ({str(r.get('motivo'))[:52]})")
    g.dispositivo = lambda: "video=fake"
    g._subir_gravador = lambda: 4242
    g.gravando_agora = lambda: True
    r = g.garantir()
    exigir(r.get("subido") == 4242, "com o desejo LIGADO e o laco morto, o supervisor REERGUEO")
    g._subir_gravador = lambda: 0
    exigir(g.garantir().get("subido") == 0, "com o laco JA' de pe' nao sobe um segundo (nao duplica)")
    for k, v in antigo.items():
        setattr(g, k, v)

    # 7) MEDICAO REAL: ffmpeg + mediamtx do produto, spec do produto
    ff = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"
    fp = RAIZ / "tools" / "ffmpeg" / "ffprobe.exe"
    mtx = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
    if not (ff.exists() and mtx.exists()):
        nota("NAO MEDIDO: sem tools/ffmpeg ou tools/mediamtx nesta copia — a prova do rele' fica de fora")
        return fim()
    log_mtx = open(tmp / "mtx.log", "wb")
    servidor = subprocess.Popen([str(mtx), str(GROUND / "mediamtx.yml")],
                                stdout=log_mtx, stderr=subprocess.STDOUT)
    try:
        time.sleep(3)
        spec = g.especificacao_do_tee(hd / "bloco-%Y%m%d-%H%M%S.mp4")
        # `-re` porque a fonte da prova e' SINTETICA (produz mais rapido que o tempo real); a camera de
        # verdade (dshow) ja' entrega no tempo real — e' o que o comando do produto usa.
        linha = [str(ff), "-hide_banner", "-nostdin", "-loglevel", "warning",
                 "-re", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                 "-b:v", "800k", "-maxrate", "800k", "-bufsize", "1M", "-g", "30",
                 "-f", "tee", "-map", "0:v", spec]
        publica = subprocess.Popen(linha, stdout=open(tmp / "ff.log", "wb"), stderr=subprocess.STDOUT)
        try:
            time.sleep(10)
            blocos = sorted(hd.glob("bloco-*.mp4"))
            exigir(bool(blocos) and blocos[0].stat().st_size > 0,
                   f"o HD recebeu bloco com o rele' ligado ({[b.name + ' ' + str(b.stat().st_size) + 'B' for b in blocos]})")
            nomes = []
            try:
                d = json.loads(urllib.request.urlopen("http://127.0.0.1:9997/v3/paths/list", timeout=3).read())
                nomes = [(i.get("name"), bool(i.get("ready"))) for i in (d.get("items") or [])]
            except Exception as e:
                nota(f"NAO MEDIDO: a API do mediamtx nao respondeu ({type(e).__name__}: {e})")
            exigir(any(n == fluxo and pronto for n, pronto in nomes),
                   f"e o RELE' esta' no ar no mediamtx local: {nomes}")
            r = subprocess.run([str(fp), "-v", "error", "-rtsp_transport", "tcp", "-select_streams",
                                "v:0", "-show_entries", "stream=codec_name,width,height", "-of",
                                "csv=p=0", f"rtsp://{g.MEDIAMTX_RTSP}/{fluxo}"],
                               capture_output=True, text=True, timeout=30)
            saida = (r.stdout or "").strip()
            exigir("h264" in saida, f"e o vivo CONSEGUE LER o fluxo do gravador enquanto ele grava: {saida!r}")
        finally:
            publica.terminate()
            try:
                publica.wait(timeout=15)
            except Exception:
                publica.kill()
        texto = (tmp / "mtx.log").read_text(errors="ignore")
        exigir("repasse" not in texto.lower() and "FOGEU" not in texto,
               "e o caminho do gravador NAO disparou o repasse para terra (a banda fica onde deve)")
    finally:
        servidor.terminate()
        try:
            servidor.wait(timeout=15)
        except Exception:
            servidor.kill()
        log_mtx.close()

    return fim()


def fim() -> int:
    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} exigencia(s)")
        for f in falhas:
            print("  - " + f)
        return 1
    print("TUDO OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
