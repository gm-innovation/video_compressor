#!/usr/bin/env python3
"""O MEDIDOR do smoke: numeros com origem, nunca "parece que esta' bom".

Cada funcao daqui devolve medida + a origem da medida (o comando que rodou). Se a medida nao sai, a
funcao levanta ou devolve `None` — e a jornada escreve "NAO MEDIDA" com o motivo. Nao existe numero
estimado neste arquivo: ou foi medido, ou esta' ausente.

Medidas:
  `medir_fluxo`    fps / Mbps / quadros / latencia do fluxo que chega ao lado terra (ffmpeg -progress)
  `medir_borda`    o que o BORDO esta' enviando (kbps do proprio ffmpeg do envio, via o log do produto)
  `tela_do_cliente` o que o NAVEGADOR do cliente recebeu (elemento <video>: largura, tempo, travado)
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import time

from ambiente import FFMPEG, FFPROBE, RAIZ, sem_janela


def _ler_midia(comando: list[str], segundos: float, teto: float | None = None) -> dict:
    """Roda o ffmpeg lendo a MIDIA de verdade (os bytes que chegam) e o progresso ao mesmo tempo.

    A saida de media vai para um cano (stdout) e e' CONTADA — e' o unico jeito honesto de medir banda
    que chegou: `-f null` nao conta byte nenhum (medido em 23/11/2026: `total_size` vinha vazio e a
    banda saia 0,0 Mbps). O progresso (`-progress pipe:2`) traz quadro a quadro, com o relogio carimbado.
    """
    import threading

    p = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=sem_janela())
    conta = {"bytes": 0}
    valores: dict[str, str] = {}
    marcas: list[tuple[float, str]] = []

    def drenar() -> None:
        assert p.stdout is not None
        while True:
            pedaco = p.stdout.read(1 << 16)
            if not pedaco:
                break
            conta["bytes"] += len(pedaco)

    def drenar_erro() -> None:
        # O progresso vem no erro padrao. Ler em fio SEPARADO e' o que impede o medidor de travar:
        # uma fonte morta deixa o ffmpeg parado e CALADO, e o `for ... in p.stderr` bloquearia
        # para sempre (medido em 23/11/2026: o fluxo de sonda com o mediamtx derrubado pendurou o
        # teste inteiro, que so' morreu no tempo-limite do CI).
        assert p.stderr is not None
        for bruto in p.stderr:
            linha = bruto.decode("utf-8", "replace").strip()
            if "=" in linha:
                chave, _, valor = linha.partition("=")
                valores[chave.strip()] = valor.strip()
                marcas.append((time.time(), chave.strip()))

    fios = [threading.Thread(target=drenar, daemon=True),
            threading.Thread(target=drenar_erro, daemon=True)]
    for fio in fios:
        fio.start()
    t_ini = time.time()
    limite = t_ini + (teto or (segundos + 45))
    try:
        # espera o ffmpeg sair sozinho (ele sai no `-t`) ou o tempo-limite chegar
        while time.time() < limite and p.poll() is None:
            time.sleep(0.1)
    finally:
        t_fim = time.time()
        try:
            p.terminate()
            p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
        for fio in fios:
            fio.join(timeout=5)
    return {"valores": valores, "marcas": marcas, "t_inicio": t_ini, "t_fim": t_fim,
            "bytes": int(conta["bytes"])}


def _progresso(comando: list[str], segundos: float, teto: float | None = None) -> dict:
    """So' o progresso (sem medir bytes) — usado por quem nao precisa de banda."""
    return _ler_midia(comando, segundos, teto)


def medir_fluxo(rtsp: str, segundos: float = 8.0, t_publicacao: float | None = None) -> dict:
    """Le o fluxo do lado terra por `segundos` e devolve o que foi MEDIDO.

    `t_publicacao` (opcional) = o instante em que o BORDO comecou a enviar, no relogio desta maquina
    (bancada: bordo e terra sao a mesma maquina, entao o relogio e' o mesmo). Com ele da' para medir a
    latencia do caminho: `latencia = (agora - t_publicacao) - tempo_de_midia_do_quadro_lido`.
    """
    # `-c copy -f mpegts pipe:1`: a midia sai para um cano e e' contada (os bytes que CHEGARAM).
    # `-progress pipe:2`: o progresso vai no erro padrao, quadro a quadro, com o relogio carimbado.
    comando = [str(FFMPEG), "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:2",
               "-nostats", "-rtsp_transport", "tcp", "-i", rtsp, "-t",
               f"{segundos:g}", "-an", "-c", "copy", "-f", "mpegts", "pipe:1"]
    r = _ler_midia(comando, segundos)
    v = r["valores"]
    quadros = int(float(v.get("frame") or 0)) if (v.get("frame") or "").strip() not in ("", "N/A") else 0
    texto_ms = (v.get("out_time_ms") or "").strip()
    seg_midia = (float(texto_ms) / 1_000_000.0) if texto_ms.isdigit() else 0.0
    bytes_lidos = int(r["bytes"])
    # janela real: do primeiro carimbo de progresso ao ultimo (o tempo de relogio em que a midia veio)
    marcas_quadro = [t for t, chave in r["marcas"] if chave == "out_time_ms"]
    t_primeiro = marcas_quadro[0] if marcas_quadro else r["t_inicio"]
    janela = max(0.001, r["t_fim"] - t_primeiro)
    fps_entrega = (quadros / janela) if quadros else 0.0
    fps_midia = (quadros / seg_midia) if (quadros and seg_midia > 0) else 0.0
    mbps = (bytes_lidos * 8 / janela / 1_000_000.0) if bytes_lidos else 0.0
    latencia = None
    if t_publicacao and seg_midia > 0:
        latencia = (r["t_fim"] - t_publicacao) - seg_midia
    return {"fluxo": rtsp, "quadros": quadros, "segundos_de_midia": round(seg_midia, 3),
            "janela_s": round(janela, 3), "fps": round(fps_midia, 2), "fps_midia": round(fps_midia, 2),
            "fps_entrega": round(fps_entrega, 2), "mbps": round(mbps, 3), "bytes": bytes_lidos,
            "latencia_s": (round(latencia, 3) if latencia is not None else None),
            # a fonte entrega em TEMPO REAL? (sem isso, a taxa de entrega nao vale como medida)
            "tempo_real": None if not fps_midia else bool(fps_entrega <= 1.5 * fps_midia),
            "bitrate_do_ffmpeg": v.get("bitrate") or "", "speed": v.get("speed") or "",
            "comando": " ".join(comando[:14]) + " ..."}


def medir_mbps(fonte: str, segundos: float = 5.0) -> dict:
    """Quanto CHEGA pelo fluxo, em Mbps (os bytes sao contados no cano; nao ha' estimativa)."""
    comando = [str(FFMPEG), "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:2",
               "-nostats", "-rtsp_transport", "tcp", "-i", fonte, "-t",
               f"{segundos:g}", "-an", "-c", "copy", "-f", "mpegts", "pipe:1"]
    r = _ler_midia(comando, segundos)
    janela = max(0.001, r["t_fim"] - r["t_inicio"])
    return {"mbps": round(r["bytes"] * 8 / janela / 1_000_000.0, 3), "bytes": r["bytes"],
            "janela_s": round(janela, 3)}


def quadros_no_ar(fluxo: str, segundos: float = 4.0, porta: int = 8554) -> int:
    """Quantos quadros de video o mediamtx entrega NAQUELE caminho (0 = nao ha' fluxo)."""
    r = subprocess.run([str(FFPROBE), "-v", "error", "-count_frames",
                        "-select_streams", "v:0",
                        "-read_intervals", f"%+{segundos:g}", "-show_entries", "stream=nb_read_frames",
                        "-of", "json", f"rtsp://127.0.0.1:{porta}/{fluxo}"],
                       capture_output=True, timeout=90)
    try:
        d = json.loads((r.stdout or b"{}").decode("utf-8", "ignore"))
        return int(((d.get("streams") or [{}])[0] or {}).get("nb_read_frames") or 0)
    except Exception:  # noqa: BLE001
        return 0


def tela_do_cliente(pagina, segundos: float = 4.0) -> dict:
    """O que o NAVEGADOR do cliente recebeu: imagem decodificada, tempo andando e travado ou nao.

    Nao basta a tela existir: aqui a pergunta e' se o video APARECE (largura > 0) e se o tempo
    avanca — a prova de que o cliente esta' vendo imagem, e nao um retangulo preto.
    """
    def _ler() -> dict:
        # A leitura NAO pode derrubar a jornada: a tela do cliente se redesenha sozinha e uma leitura
        # pode pegar o instante da troca. Se nao vier um dicionario, e' leitura perdida — o veredito
        # sai "sem imagem" (com o motivo), nunca um AttributeError que esconde o estado do video.
        # (Medido em 23/11/2026: numa rodada do smoke a leitura voltou string e a J2 caiu inteira.)
        try:
            r = pagina.evaluate("""() => {
                const vs = [...document.querySelectorAll('video')];
                const v = vs.map(x => ({largura: x.videoWidth, altura: x.videoHeight,
                                        tempo: x.currentTime, travado: x.paused, pronto: x.readyState,
                                        src: (x.currentSrc || x.src || '').slice(0, 90)})).find(x => x.largura > 0) || vs[0] || {};
                return {quantidade: vs.length, video: v || {}};
            }""")
        except Exception as e:  # noqa: BLE001
            return {"quantidade": 0, "video": {}, "erro": f"{type(e).__name__}: {e}"}
        return r if isinstance(r, dict) else {"quantidade": 0, "video": {}, "erro": f"leitura inesperada: {type(r).__name__}"}

    antes = _ler()
    time.sleep(segundos)
    depois = _ler()
    t_antes = float((antes.get("video") or {}).get("tempo") or 0)
    t_depois = float((depois.get("video") or {}).get("tempo") or 0)
    return {"quantidade": antes.get("quantidade", 0), "erro": antes.get("erro") or depois.get("erro") or "",
            "largura": (depois.get("video") or {}).get("largura") or 0,
            "altura": (depois.get("video") or {}).get("altura") or 0,
            "tempo_antes_s": round(t_antes, 2), "tempo_depois_s": round(t_depois, 2),
            "avancou_s": round(t_depois - t_antes, 2),
            "travado": bool((depois.get("video") or {}).get("travado")),
            "src": (depois.get("video") or {}).get("src") or "",
            "imagem_na_tela": bool(((depois.get("video") or {}).get("largura") or 0) > 0
                                   and (t_depois - t_antes) > 0.5)}


def tempo_de_ligacao(logs: list[str], padrao: str = r"envio (\d+)") -> float | None:
    """(apoio) quanto tempo o bordo levou para o ffmpeg estar de pe', lido do log do proprio bordo."""
    for texto in logs:
        m = re.search(padrao, texto or "")
        if m:
            return float(m.group(1))
    return None


def pgm_conectado(nome: str) -> bool:
    """(apoio) um processo com esse nome esta' de pe' agora?"""
    r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {nome}", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, timeout=30)
    return nome.lower() in (r.stdout or "").lower()


def ultimo_log(caminho) -> str:
    try:
        return pathlib.Path(caminho).read_text(encoding="utf-8", errors="replace")[-3000:]
    except Exception:  # noqa: BLE001
        return ""
