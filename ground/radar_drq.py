"""Sinais de radar -> video (arquivo .drq) para o pipeline de video bordo->terra.

Um quadro do .drq e' UM radial: 1.024 amostras u16, com azimute e hora proprios. Juntando os radiais
de uma volta do azimute sai a imagem do radar (PPI); o mesmo radial pode sair cru (desdobrado).

Medido no arquivo do dono (2026-11-06, 2.533.844.224 B):
  cabecalho 1.024 B | quadro 2.240 B (tipo=3 em +0, passo=2240 em +4) | 1.131.180 quadros
  +24 FILETIME (hora do quadro) | +40 azimute em graus | +44 azimute fino (0..4095, 4096 = 1 volta)
  +188 n de amostras (1024) | +192 inicio das 1.024 amostras u16 (amplitude nos 12 bits baixos)

Dois modos de imagem (o dono pediu os DOIS) e duas taxas (o dono pediu as DUAS):
  modo  ppi  = imagem de radar desenhada (1.024x1.024; centro = radar, raio = amostra)
  modo  cru  = os radiais como vieram, desdobrados em linhas (1.024x1.024)
  taxa  volta = uma imagem por volta do azimute (mais leve)
  taxa  30fps = 30 imagens por segundo de gravacao (mais fluido)

Sem dependencia externa: PNG e' escrito com zlib+struct (o Python portatil do pacote nao tem Pillow)
e o desenho usa tabela de tom e tabela de deslocamento por direcao (sem seno/cosseno por radial).

Como a PPI e' desenhada (declarado, nao escondido): a tela tem 1.024x1.024, ou seja 360 direcoes
visiveis; cada direcao recebe a ULTIMA radial daquela direcao na volta (pintar as 7.056 radiais de
uma volta repetiria 20x os mesmos pixels). O JSON de cada imagem traz "radiais_da_volta" e
"radiais_desenhadas" para essa reducao ficar a vista. Na taxa 30 fps a tela e' mantida entre imagens
(persistencia de uma volta) e so' as radiais novas sao pintadas; a volta fecha quando o azimute fino
volta ao comeco, e ai a tela e' limpa.

Uso:
  python ground/radar_drq.py ARQUIVO.drq --saida DIR --modo ppi --taxa volta [--segundos N]
         [--alvo 1500k] [--mp4]
"""
import argparse
import datetime
import json
import os
import socket
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

CABECALHO = 1024
QUADRO = 2240
AMOSTRAS = 1024
PPI = 1024                     # resolucao da PPI (o dono fechou em 1.024x1.024)
MODOS = ("ppi", "cru")
TAXAS = ("volta", "30fps")
ALVO_PADRAO = "1500k"
EPOCA_FILETIME = datetime.datetime(1601, 1, 1)
DIRECOES = 4096                # passos do azimute fino = uma volta
BINOS = 1024                   # direcoes visiveis na PPI: 1.024 px de tela, ~3 px de arco por direcao
FMT_AMOSTRAS = f"<{AMOSTRAS}H"


# ------------------------------------------------------------------ leitura do arquivo .drq
def hora_do_filetime(v: int) -> datetime.datetime:
    return EPOCA_FILETIME + datetime.timedelta(microseconds=v // 10)


def ler_cabecalho(caminho) -> dict:
    with open(caminho, "rb") as f:
        cab = f.read(CABECALHO)
    if len(cab) < CABECALHO:
        raise ValueError("arquivo menor que o cabecalho (nao parece .drq)")
    campo0 = struct.unpack("<I", cab[:4])[0]
    campo4 = struct.unpack("<I", cab[4:8])[0]
    n_res = struct.unpack("<I", cab[128:132])[0]
    amostras = struct.unpack("<I", cab[132:136])[0]
    tamanho = os.path.getsize(caminho)
    if tamanho < CABECALHO or (tamanho - CABECALHO) % QUADRO:
        raise ValueError("tamanho nao fecha com cabecalho + N quadros")
    return {"campo0": campo0, "campo4": campo4, "tamanho": tamanho, "n_res": n_res,
            "amostras": amostras, "quadros": (tamanho - CABECALHO) // QUADRO}


def montar_quadro(q: bytes, i: int):
    """Monta o quadro a partir dos 2.240 B ja' lidos. None se nao for do tipo de sinal (tipo=3)."""
    tipo, passo = struct.unpack_from("<II", q, 0)
    if tipo != 3 or passo != QUADRO:
        return None
    filetime = struct.unpack_from("<Q", q, 24)[0]
    az = struct.unpack_from("<I", q, 40)[0]
    az_fino = struct.unpack_from("<I", q, 44)[0]
    n = struct.unpack_from("<H", q, 188)[0] or AMOSTRAS
    n = min(n, AMOSTRAS)
    return {"amostras": struct.unpack_from(FMT_AMOSTRAS, q, 192)[:n], "az": az, "az_fino": az_fino,
            "hora": hora_do_filetime(filetime), "angulo": (az * 4096 + az_fino) / 4096.0,
            "indice": i}


def ler_quadro(f, i: int):
    """Le o quadro i por deslocamento (uso avulso/inspecao)."""
    f.seek(CABECALHO + i * QUADRO)
    q = f.read(QUADRO)
    return montar_quadro(q, i) if len(q) == QUADRO else None


def ler_quadro_seguido(f, i: int):
    """Le o proximo quadro em sequencia (sem seek): o laco quente le o arquivo de uma vez."""
    q = f.read(QUADRO)
    return montar_quadro(q, i) if len(q) == QUADRO else None


def janela_de_amplitude(caminho, quadros=200) -> tuple:
    """Faixa de amplitude vista no arquivo, para dar contraste a PPI.

    A amplitude vai nos 12 bits baixos da amostra (medido: 1.512..4.092 neste arquivo). Os 4 bits
    altos sao flag — semantica NAO medida (esta declarado como incognita no plano), por isso o
    desenho usa so' os 12 bits.
    """
    menor, maior = 4095, 0
    cab = ler_cabecalho(caminho)
    passo = max(1, cab["quadros"] // max(1, quadros))
    with open(caminho, "rb") as f:
        for i in range(0, cab["quadros"], passo):
            r = ler_quadro(f, i)
            if not r:
                continue
            for v in r["amostras"]:
                a = v & 0x0FFF
                if a < menor:
                    menor = a
                if a > maior:
                    maior = a
    if maior <= menor:
        maior = menor + 1
    return menor, maior


# ------------------------------------------------------------------ desenho (sem dependencia externa)
def tabela_cinza(menor: int, faixa: int) -> bytes:
    """Tabela amplitude (12 bits) -> tom de cinza, para nao fazer conta por pixel."""
    t = bytearray(4096)
    for a in range(4096):
        c = (a - menor) * 255 // faixa
        t[a] = 0 if c <= 0 else (255 if c > 255 else c)
    return bytes(t)


_TABELAS_DIRECAO = {}


def tabela_direcao(int_direcao: int, tela: int = PPI) -> tuple:
    """Deslocamentos (linha*tela+coluna) de cada amostra, para UMA direcao. Cacheado."""
    chave = ((int_direcao) & (BINOS - 1), tela)
    t = _TABELAS_DIRECAO.get(chave)
    if t is not None:
        return t
    import math
    rad = (chave[0] + 0.5) * 6.283185307179586 / BINOS
    sen, cos = math.sin(rad), math.cos(rad)
    raio_max = tela // 2 - 1
    cx = cy = tela // 2
    desloc = []
    for i in range(AMOSTRAS):
        raio = i * raio_max // AMOSTRAS
        x = cx + int(raio * sen)
        y = cy - int(raio * cos)
        desloc.append(y * tela + x if (0 <= x < tela and 0 <= y < tela) else -1)
    t = tuple(desloc)
    _TABELAS_DIRECAO[chave] = t
    return t


def direcao_de(r) -> int:
    """Direcao (0..BINOS-1) da radial: o azimute em graus virou passo do azimute fino."""
    return int(r["angulo"] * BINOS / 360.0) & (BINOS - 1)


def pintar_radial(px: bytearray, r, cinza: bytes, tela: int = PPI) -> None:
    """Pinta uma radial na direcao dela (a ultima radial da direcao vence)."""
    desloc = tabela_direcao(direcao_de(r), tela)
    amostras = r["amostras"]
    for j in range(len(desloc)):
        off = desloc[j]
        if off >= 0:
            px[off] = cinza[amostras[j] & 0x0FFF]


def desenhar_ppi(radiais, cinza: bytes, tela: int = PPI, fundo: int = 0) -> bytearray:
    """PPI montada do zero: uma radial por direcao (a ultima de cada direcao)."""
    px = bytearray([fundo]) * (tela * tela)
    vistas = {}
    for r in radiais:
        vistas[direcao_de(r)] = r
    for r in vistas.values():
        pintar_radial(px, r, cinza, tela)
    return px


def desenhar_cru(radiais, cinza: bytes, tela: int = PPI, fundo: int = 0) -> bytearray:
    """Quadro cru: cada radial como veio, uma linha por radial (desdobrado), sem desenho."""
    px = bytearray([fundo]) * (tela * tela)
    for linha, r in enumerate(radiais[:tela]):
        n = len(r["amostras"])
        base = linha * tela
        for col in range(tela):
            px[base + col] = cinza[r["amostras"][col * n // tela] & 0x0FFF]
    return px


def png_cinza(largura: int, altura: int, pixels: bytes) -> bytes:
    """PNG 8 bits escala de cinza com stdlib pura (zlib + struct). Sem Pillow."""
    linhas = bytearray()
    for y in range(altura):
        linhas.append(0)                                   # filtro "None"
        linhas += pixels[y * largura:(y + 1) * largura]

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 0, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(bytes(linhas), 6))
            + bloco(b"IEND", b""))


# ------------------------------------------------------------------ quadros de saida
def quadros_do_arquivo(caminho, modo: str, taxa: str, segundos=None, max_quadros=400_000):
    """Gera (nome, pixels, info) na ordem, sem guardar o arquivo na memoria.

    modo/taxa: ver o topo. `segundos` limita a gravacao processada (None = tudo).
    """
    if modo not in MODOS:
        raise ValueError(f"modo invalido: {modo} (use {' ou '.join(MODOS)})")
    if taxa not in TAXAS:
        raise ValueError(f"taxa invalida: {taxa} (use {' ou '.join(TAXAS)})")
    cab = ler_cabecalho(caminho)
    menor, maior = janela_de_amplitude(caminho)
    faixa = max(1, maior - menor)      # faixa = altura da janela; menor e maior sao os extremos medidos
    cinza = tabela_cinza(menor, faixa)
    cru = modo == "cru"
    out = []
    quadros_lidos = 0
    with open(caminho, "rb") as f:
        f.seek(CABECALHO)
        ultimo = None
        for i0 in range(cab["quadros"]):
            ultimo = ler_quadro_seguido(f, i0)
            if ultimo:
                break
        if ultimo is None:
            raise ValueError("o arquivo nao tem quadro de sinal (tipo=3)")
        t0 = ultimo["hora"]
        volta = [ultimo]                       # radiais da volta em formacao
        vistos = {direcao_de(ultimo): ultimo}
        az_anterior = ultimo["az_fino"]
        girado = 0
        proximo = 0.0
        decorrido = 0.0
        r = ultimo
        tela = bytearray(PPI * PPI) if (taxa == "30fps" and not cru) else None
        pintadas = set()

        def fecha(parcial=False):
            info_img = {"hora": r["hora"].isoformat(sep=" ")[:23], "az_graus": r["az"],
                        "az_fino": r["az_fino"], "volta_parcial": parcial, "girado": girado,
                        "radiais_da_volta": len(volta), "radiais_desenhadas": len(vistos),
                        "quadros": len(volta), "segundos": round(decorrido, 3)}
            if cru:
                px = desenhar_cru(volta, cinza)
            elif tela is None:
                px = desenhar_ppi(volta, cinza)
            else:
                px = bytearray(tela)
            out.append((f"{len(out):05d}.png", px, info_img))

        for i in range(min(cab["quadros"], max_quadros)):
            lido = ler_quadro_seguido(f, i)
            if not lido:
                continue
            r = lido
            quadros_lidos += 1
            decorrido = (r["hora"] - t0).total_seconds()
            if segundos is not None and decorrido > segundos:
                break
            direcao = direcao_de(r)
            girado += (r["az_fino"] - az_anterior) % DIRECOES
            fechou = r["az_fino"] + 100 < az_anterior      # o azimute fino voltou ao comeco
            az_anterior = r["az_fino"]
            voltou = fechou or girado >= DIRECOES
            vistos[direcao] = r
            volta.append(r)
            if taxa == "volta":
                if voltou:                                  # fecha a volta: imagem da volta inteira
                    fecha()
                    volta = []
                    vistos = {}
                    girado = 0
            else:
                if voltou:                                  # volta nova: limpa a tela
                    if tela is not None:
                        for k in range(len(tela)):
                            tela[k] = 0
                    pintadas = set()
                    girado = 0
                if tela is not None and direcao not in pintadas:   # so' pinta o que apareceu de novo
                    pintar_radial(tela, r, cinza)
                    pintadas.add(direcao)
                if decorrido >= proximo:
                    fecha()
                    proximo = decorrido + 1 / 30.0
        if taxa == "volta" and girado >= 1024:
            # a gravacao terminou no meio de uma volta: a imagem sai marcada como parcial
            fecha(parcial=True)
    return out, {"menor": menor, "maior": maior, "faixa": faixa, "modo": modo, "taxa": taxa,
                 "quadros_lidos": quadros_lidos, "quadros_no_arquivo": cab["quadros"]}


def gravar_pngs(quadros, destino: Path) -> int:
    destino.mkdir(parents=True, exist_ok=True)
    for nome, px, _ in quadros:
        (destino / nome).write_bytes(png_cinza(PPI, PPI, bytes(px)))
    return len(quadros)


# ------------------------------------------------ fluxo continuo (Fase 3: radar como camera)
def _info_do_quadro(r, volta, vistos, girado, decorrido, parcial=False) -> dict:
    return {"hora": r["hora"].isoformat(sep=" ")[:23], "az_graus": r["az"], "az_fino": r["az_fino"],
            "volta_parcial": parcial, "girado": girado, "radiais_da_volta": len(volta),
            "radiais_desenhadas": len(vistos), "quadros": len(volta), "segundos": round(decorrido, 3)}


def quadros_ao_vivo(caminho, modo: str = "ppi", taxa: str = "30fps", fps: int = 30,
                    repetir: bool = True, segundos=None, max_voltas=None):
    """Fluxo CONTINUO de quadros, um por vez, para o radar entrar na cadeia como uma "camera".

    Mesma regra do `quadros_do_arquivo` (PPI ou quadro cru; 1 imagem por volta ou 30 fps) e as mesmas
    medidas, mas em fluxo: devolve (pixels, info) a cada quadro, sem guardar a gravacao na memoria, e
    relê o arquivo do comeco quando ele termina (`repetir=True`) — o envio so' para quando o dono
    mandar, como o envio ao vivo de camera.

    O ritmo e' do GERADOR, medido no relogio de parede: no modo 30 fps ele dorme o que sobra de cada
    quadro (1/fps) — se o desenho for mais lento que o alvo, o fluxo anda mais devagar e o numero na
    tela mostra isso; em 'volta' sai uma imagem por volta, no ritmo em que o arquivo e' lido.

    Quadros crus: 1 byte por pixel (tons de cinza), 1.024x1.024 — vai direto no `-f rawvideo` do
    ffmpeg (o produto NAO guarda PNG no caminho ao vivo).
    """
    if modo not in MODOS:
        raise ValueError(f"modo invalido: {modo} (use {' ou '.join(MODOS)})")
    if taxa not in TAXAS:
        raise ValueError(f"taxa invalida: {taxa} (use {' ou '.join(TAXAS)})")
    voltas = 0
    while True:
        cab = ler_cabecalho(caminho)
        menor, maior = janela_de_amplitude(caminho)
        faixa = max(1, maior - menor)
        cinza = tabela_cinza(menor, faixa)
        cru = modo == "cru"
        with open(caminho, "rb") as f:
            f.seek(CABECALHO)
            ultimo = None
            for i0 in range(min(cab["quadros"], 5000)):
                ultimo = ler_quadro_seguido(f, i0)
                if ultimo:
                    break
            if ultimo is None:
                raise ValueError("o arquivo nao tem quadro de sinal (tipo=3)")
            t0 = ultimo["hora"]
            volta = [ultimo]
            vistos = {direcao_de(ultimo): ultimo}
            az_anterior = ultimo["az_fino"]
            girado = 0
            proximo = 0.0
            decorrido = 0.0
            r = ultimo
            tela = bytearray(PPI * PPI) if (taxa == "30fps" and not cru) else None
            pintadas = set()
            fim = False

            def monta(parcial=False):
                if cru:
                    return bytes(desenhar_cru(volta, cinza))
                if tela is None:
                    return bytes(desenhar_ppi(volta, cinza))
                return bytes(tela)

            for i in range(min(cab["quadros"], 4_000_000)):
                lido = ler_quadro_seguido(f, i)
                if not lido:
                    continue
                r = lido
                decorrido = (r["hora"] - t0).total_seconds()
                if segundos is not None and decorrido > segundos:
                    fim = True
                    break
                direcao = direcao_de(r)
                girado += (r["az_fino"] - az_anterior) % DIRECOES
                fechou = r["az_fino"] + 100 < az_anterior
                az_anterior = r["az_fino"]
                voltou = fechou or girado >= DIRECOES
                vistos[direcao] = r
                volta.append(r)
                if taxa == "volta":
                    if voltou:
                        px = monta()
                        info = _info_do_quadro(r, volta, vistos, girado, decorrido)
                        volta = []
                        vistos = {}
                        girado = 0
                        voltas += 1
                        yield px, info
                        if max_voltas and voltas >= max_voltas:
                            fim = True
                            break
                else:
                    if voltou:
                        if tela is not None:
                            for k in range(len(tela)):
                                tela[k] = 0
                        pintadas = set()
                        girado = 0
                    if tela is not None and direcao not in pintadas:
                        pintar_radial(tela, r, cinza)
                        pintadas.add(direcao)
                    if decorrido >= proximo:
                        marca = time.monotonic()          # o quadro e' medido: dorme so' o que sobra
                        yield monta(), _info_do_quadro(r, volta, vistos, girado, decorrido)
                        if max_voltas and len(volta) >= max_voltas:
                            fim = True
                            break
                        proximo = decorrido + 1 / max(1, int(fps))
                        sobra = (1.0 / max(1, int(fps))) - (time.monotonic() - marca)
                        if sobra > 0:
                            # ritmo de PAREDE: o proximo quadro sai em 1/fps mesmo que a leitura do
                            # arquivo seja instantanea (senao o fluxo correria a 2.800 quadros/s e o
                            # codificador receberia tudo de uma vez, sem parecer um radar ao vivo)
                            time.sleep(sobra)
            if taxa == "volta" and not fim and girado >= 1024:
                yield monta(), _info_do_quadro(r, volta, vistos, girado, decorrido, parcial=True)
        if not repetir or fim:
            return


# ------------------------------------------------ fonte AO VIVO por TCP (Fase 5: radar da embarcacao)
def es_fonte_tcp(fonte: str) -> bool:
    """A fonte e' um radar por TCP (`tcp://host:porta`) em vez de um arquivo `.drq`?"""
    return str(fonte or "").strip().lower().startswith("tcp://")


def partir_fonte_tcp(fonte: str) -> tuple:
    """Aceita `tcp://host:porta` (ou `host:porta`) e devolve (host, porta)."""
    bruto = str(fonte or "").strip()
    if bruto.lower().startswith("tcp://"):
        bruto = bruto[6:]
    bruto = bruto.split("/", 1)[0]
    if ":" not in bruto:
        raise ValueError(f"fonte TCP sem porta: {fonte!r} (use tcp://host:porta)")
    host, _, porta = bruto.rpartition(":")
    if not porta.isdigit() or not (0 < int(porta) < 65536):
        raise ValueError(f"porta invalida na fonte TCP: {fonte!r} (use tcp://host:porta)")
    return (host or "127.0.0.1"), int(porta)


def quadros_ao_vivo_tcp(host: str, porta: int, modo: str = "ppi", taxa: str = "30fps", fps: int = 30,
                        segundos=None, max_quadros=None, timeout: float = 15.0, repetir: bool = True):
    """Sinal de radar AO VIVO, por TCP, no MESMO formato de quadro medido no `.drq` (2.240 B, tipo=3).

    Diferenca do `quadros_ao_vivo` (arquivo): nao ha arquivo para ler nem para repetir — o radar manda
    o fluxo continuo e o desenhador consome. O resto e' identico de proposito (mesma janela de
    amplitude, mesmos modos, mesmas taxas, mesmo ritmo de parede), porque a imagem tem de sair igual
    venha ela de arquivo ou do radar.

    O que NAO esta' medido, e por isso NAO e' inventado aqui (ver plano, "Incognitas declaradas"):
    o protocolo de fio do radar original e a placa de aquisicao analogica do cliente. O clone do
    SeaDarQ fala RIU por linhas ASCII (comandos + `[TRIG]`, sem as amostras) e este conector fala o
    formato de QUADRO medido no arquivo do dono — que e' o que a bancada reproduz com
    `ground/radar_tcp.py`, e o que qualquer infra de cliente que entregue esse formato entrega.
    """
    if modo not in MODOS:
        raise ValueError(f"modo invalido: {modo} (use {' ou '.join(MODOS)})")
    if taxa not in TAXAS:
        raise ValueError(f"taxa invalida: {taxa} (use {' ou '.join(TAXAS)})")
    cru = modo == "cru"
    sock = socket.create_connection((host, int(porta)), timeout=timeout)
    sock.settimeout(timeout)
    buf = bytearray()
    i = 0

    def proximo():
        nonlocal buf, i
        while len(buf) < QUADRO:
            pedaco = sock.recv(65536)
            if not pedaco:
                return None
            buf.extend(pedaco)
        q = bytes(buf[:QUADRO])
        del buf[:QUADRO]
        r = montar_quadro(q, i)
        i += 1
        return r

    try:
        # Janela de contraste da FONTE: no arquivo ela e' medida no proprio arquivo
        # (`janela_de_amplitude`); aqui saem das primeiras radiais que o radar manda — sem isso a PPI
        # sairia preta (a tabela de cinza precisa da faixa real daquela fonte).
        inicio = []
        while len(inicio) < 200:
            r = proximo()
            if r is None:
                raise ConnectionError(f"o radar em {host}:{porta} nao mandou quadro de sinal "
                                      f"(chegaram {len(inicio)}) — a fonte caiu ou nao fala o formato medido")
            inicio.append(r)
        menor = 4095
        maior = 0
        for r in inicio:
            for v in r["amostras"]:
                a = v & 0x0FFF
                if a < menor:
                    menor = a
                if a > maior:
                    maior = a
        if maior <= menor:
            maior = menor + 1
        cinza = tabela_cinza(menor, maior - menor)

        tela = bytearray(PPI * PPI) if (taxa == "30fps" and not cru) else None
        pintadas = set()
        volta = []
        vistos = {}
        girado = 0
        az_anterior = None
        t0 = None
        quadros_enviados = 0

        def monta(parcial=False):
            if cru:
                return bytes(desenhar_cru(volta, cinza))
            if tela is None:
                return bytes(desenhar_ppi(volta, cinza))
            return bytes(tela)

        pendente = inicio
        while True:
            if pendente:
                r = pendente.pop(0)
            else:
                r = proximo()
            if r is None:
                return
            if t0 is None:
                t0 = r["hora"]
            decorrido = (r["hora"] - t0).total_seconds()
            if segundos is not None and decorrido > segundos:
                return
            direcao = direcao_de(r)
            if az_anterior is not None:
                girado += (r["az_fino"] - az_anterior) % DIRECOES
                fechou = r["az_fino"] + 100 < az_anterior
            else:
                fechou = False
            az_anterior = r["az_fino"]
            voltou = fechou or girado >= DIRECOES
            vistos[direcao] = r
            volta.append(r)
            if taxa == "volta":
                if voltou:
                    px = monta()
                    info = _info_do_quadro(r, volta, vistos, girado, decorrido)
                    volta = []
                    vistos = {}
                    girado = 0
                    quadros_enviados += 1
                    yield px, info
                    if max_quadros and quadros_enviados >= max_quadros:
                        return
            else:
                if voltou:
                    if tela is not None:
                        for k in range(len(tela)):
                            tela[k] = 0
                    pintadas = set()
                    girado = 0
                if tela is not None and direcao not in pintadas:
                    pintar_radial(tela, r, cinza)
                    pintadas.add(direcao)
                if decorrido >= (quadros_enviados / max(1, int(fps))):
                    marca = time.monotonic()
                    px = monta()
                    info = _info_do_quadro(r, volta, vistos, girado, decorrido)
                    quadros_enviados += 1
                    yield px, info
                    if max_quadros and quadros_enviados >= max_quadros:
                        return
                    sobra = (1.0 / max(1, int(fps))) - (time.monotonic() - marca)
                    if sobra > 0:
                        time.sleep(sobra)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def gerador_da_fonte(fonte, modo: str = "ppi", taxa: str = "30fps", fps: int = 30, repetir: bool = True,
                     segundos=None, max_quadros=None, timeout: float = 15.0):
    """Escolhe o conector pela FONTE: arquivo `.drq` ou radar por TCP — mesma saida nos dois.

    E' o que faz a fonte ser plugavel por embarcacao (decisao A do dono): o resto da cadeia (desenho,
    encode, SRT, mediamtx) nao sabe de onde o sinal veio.
    """
    if es_fonte_tcp(fonte):
        host, porta = partir_fonte_tcp(fonte)
        return quadros_ao_vivo_tcp(host, porta, modo=modo, taxa=taxa, fps=fps, segundos=segundos,
                                   max_quadros=max_quadros, timeout=timeout, repetir=repetir)
    return quadros_ao_vivo(fonte, modo, taxa, fps, repetir=repetir, segundos=segundos,
                           max_voltas=max_quadros)


# ------------------------------------------------------------------ codificacao (ffmpeg do produto)
def ffmpeg_do_produto() -> Path:
    raiz = Path(__file__).resolve().parent.parent
    for cand in (raiz / "tools" / "ffmpeg" / "ffmpeg.exe", raiz / "tools" / "ffmpeg" / "ffmpeg"):
        if cand.is_file():
            return cand
    return Path("ffmpeg")


def duracao(caminho: str) -> float:
    ffprobe = ffmpeg_do_produto().with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not Path(ffprobe).is_file():
        return 0.0
    r = subprocess.run([str(ffprobe), "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", caminho], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def codificar(pasta: Path, mp4: Path, alvo: str = ALVO_PADRAO, fps: int = 30) -> dict:
    """Codifica os PNG na taxa alvo com o ffmpeg do produto. Mede kbps do arquivo, nao estima."""
    alvo = alvo if alvo.endswith("k") else f"{alvo}k"
    kbps = int(alvo[:-1])
    matricula = "%05d.png"
    if os.name == "nt":                                    # binario nativo nao le caminho MSYS
        entrada = str(pasta.resolve()) + "\\" + matricula
        saida = str(mp4.resolve())
    else:
        entrada = str(pasta / matricula)
        saida = str(mp4)
    cmd = [str(ffmpeg_do_produto()), "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(fps), "-i", entrada,
           "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
           "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-b:v", alvo, "-maxrate", alvo, "-bufsize", f"{kbps * 2}k", saida]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ({r.returncode}): {r.stderr[:400]}")
    dur = duracao(saida)
    tam = os.path.getsize(mp4)
    return {"mp4": str(mp4), "bytes": tam, "segundos": round(dur, 3),
            "kbps": round(tam * 8 / dur / 1000, 1) if dur else None,
            "alvo": alvo, "alvo_kbps": kbps}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Sinais de radar .drq -> PNG -> mp4 (pipeline LECSOR)")
    p.add_argument("arquivo", help="arquivo .drq do radar")
    p.add_argument("--saida", required=True, help="pasta de saida")
    p.add_argument("--modo", default="ppi", choices=MODOS)
    p.add_argument("--taxa", default="volta", choices=TAXAS)
    p.add_argument("--segundos", type=float, default=None)
    p.add_argument("--alvo", default=ALVO_PADRAO, help="bitrate do video (ex.: 1500k)")
    p.add_argument("--mp4", action="store_true", help="codifica em mp4 com o ffmpeg do produto")
    a = p.parse_args(argv)
    saida = Path(a.saida)
    quadros, info = quadros_do_arquivo(a.arquivo, a.modo, a.taxa, a.segundos)
    n = gravar_pngs(quadros, saida)
    info.update({"arquivo": a.arquivo, "saida": str(saida), "pngs": n, "imagens": n,
                 "amplitude": {"menor": info["menor"], "maior": info["maior"]},
                 "primeiros": [i for _, _, i in quadros[:3]],
                 "por_imagem": [{"arquivo": nome, **i} for nome, _, i in quadros]})
    if a.mp4 and n:
        info["video"] = codificar(saida, saida / "radar.mp4", a.alvo)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
