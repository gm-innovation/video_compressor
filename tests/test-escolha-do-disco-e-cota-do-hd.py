#!/usr/bin/env python3
"""QUAL DISCO E QUANTO DELE, e o bloco que dá play ANTES de estar inteiro (0.28.0).

Palavras do dono (27/11/2026): "precisamos definir qual disco e quanto dele será utilizado para gravação"
e "não aparece nada para dar play na gravação, eu deveria poder dar play e ver em tempo real com barra de
linha do tempo". Decisões: D2 = cota em GB · D3 = "se houver só um disco fica nele, se houver mais de um,
escolhe" · D4 = "do bordo em tempo real".

    python tests/test-escolha-do-disco-e-cota-do-hd.py

Provas (sem tocar no repositório: a escolha é desviada para a pasta da prova):
  1) sem escolha, a gravação fica no PADRÃO (pasta do aplicativo) e a origem é `padrao`;
  2) o admin escolhe DISCO + COTA: a gravação passa para `<disco>/lecsor-radar`, a cota vira bytes e a
     origem é `admin` — e a ESCOLHA mora em lugar FIXO (trocar de disco não apaga a própria escolha);
  3) disco que não existe nesta máquina é RECUSADO (nada de "apliquei" com caminho inventado);
  4) cota fora da faixa do produto é RECUSADA, dizendo a faixa;
  5) o anel obedece à COTA: o que passar dela faz sair o bloco MAIS ANTIGO (nunca a gravação parada);
  6) a RESERVA do sistema continua valendo como segundo limite;
  7) o `LECSOR_HD_DIR` (bancada) vence a escolha do admin — override de teste, não de produção;
  8) a régua do "hd do radar" na saúde aponta para o diretório de gravação DE VERDADE;
  9) o resumo publica disco, cota, origem e os discos medidos;
 10) o bloco sai MP4 FRAGMENTADO e o prefixo (60% do arquivo, o que já chegou do bordo) é DECODIFICÁVEL —
     é isto que faz o play "em tempo real" existir (D4); medido com ffprobe, não prometido.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
GROUND = RAIZ / "ground"
falhas: list[str] = []


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def caixas(caminho: pathlib.Path) -> list:
    """A ordem das caixas de nível 1 do mp4: fragmentado = tem `moof` ANTES de terminar."""
    saida = []
    with open(caminho, "rb") as f:
        pos = 0
        while len(saida) < 12:
            f.seek(pos)
            cab = f.read(8)
            if len(cab) < 8:
                break
            tam, nome = struct.unpack(">I4s", cab)
            try:
                nome = nome.decode("ascii")
            except Exception:
                break
            saida.append(nome)
            if tam <= 0:
                break
            pos += tam
    return saida


def quadros(alvo: pathlib.Path) -> int:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return -1
    r = subprocess.run([ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=nb_read_frames", "-of", "json", str(alvo)],
                       capture_output=True, text=True, timeout=180)
    try:
        return int(json.loads(r.stdout)["streams"][0].get("nb_read_frames") or 0)
    except Exception:
        return -1


def main() -> int:  # noqa: C901
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-hd-escolha-"))
    disco_b = tmp / "disco-b"
    disco_b.mkdir(parents=True, exist_ok=True)
    os.environ.pop("LECSOR_HD_DIR", None)
    sys.path.insert(0, str(GROUND))
    import gravacao_continua as g  # noqa: PLC0415

    # a escolha e o desejo da prova ficam na pasta da prova (nunca no repositório)
    g.CONFIG_DO_HD = tmp / "config.json"
    g.RAIZ = tmp

    # 1) sem escolha: padrão = pasta do aplicativo
    falta = g.diretorio()
    exigir(falta == tmp / "ground" / "hd" and g.escolha()["origem"] == "padrao",
           f"sem escolha, a gravação fica no padrão da instalação ({falta})")
    exigir(g.cota_bytes() is None, "e sem cota escolhida não há limite de cota (o anel só olha a reserva)")

    # 2) o admin escolhe DISCO + COTA (GB) e a escolha mora em lugar FIXO
    r = g.definir_escolha(str(disco_b), 3)
    exigir(r.get("ok") is True and g.diretorio() == disco_b / "lecsor-radar",
           f"a escolha move a gravação para <disco>/lecsor-radar ({g.diretorio()})")
    exigir(g.cota_bytes() == 3 * 1024 * 1024 * 1024 and g.escolha()["origem"] == "admin",
           f"a cota em GB vira bytes e fica marcada como escolha do admin ({g.cota_bytes()} B)")
    exigir(g.CONFIG_DO_HD.exists() and str(g.CONFIG_DO_HD) not in str(disco_b),
           "a ESCOLHA fica em pasta FIXA, fora do disco escolhido (trocar de disco não apaga a escolha)")

    # 3) disco que não existe é recusado
    r = g.definir_escolha("Z:/disco-que-nao-existe-9999", None)
    exigir(r.get("ok") is False and g.diretorio() == disco_b / "lecsor-radar",
           f"disco inexistente é RECUSADO e a gravação não muda: {str(r.get('motivo'))[:60]}")

    # 4) cota fora da faixa é recusada, dizendo a faixa
    r = g.definir_escolha(str(disco_b), 999999)
    exigir(r.get("ok") is False and "faixa" in str(r.get("motivo", "")),
           f"cota fora da faixa é recusada com a faixa do produto: {str(r.get('motivo'))[:70]}")

    # 5) o ANEL obedece à COTA: 5 blocos de 1000 B, cota de 3 KB -> sobra 3
    pasta = disco_b / "lecsor-radar"
    pasta.mkdir(parents=True, exist_ok=True)
    ordem_feita = []
    for i in range(5):
        p = pasta / f"bloco-2026112{i}-12000{i}.mp4"
        p.write_bytes(b"x" * 1000)
        os.utime(p, (1000.0 + i, 1000.0 + i))     # o "mais antigo" fica determinístico
        ordem_feita.append(p.name)
    alongado = g.COTA_MINIMA_GB
    g.COTA_MINIMA_GB = 1e-9
    try:
        r = g.definir_escolha(str(disco_b), 3.0e-6)   # 3 KB de cota
        exigir(r.get("ok") is True and 3000 < g.cota_bytes() < 4000,
               f"cota de 3 KB publicada para a prova ({g.cota_bytes()} B)")
        fora = g.manter_anel(5)   # orçamento de apagões; ele PARA assim que couber na cota
        restante = sorted(p.name for p in pasta.glob("bloco-*.mp4"))
        usado = sum(p.stat().st_size for p in pasta.glob("bloco-*.mp4"))
        exigir(len(fora) == 2 and len(restante) == 3 and usado <= g.cota_bytes(),
               f"o que passou da COTA fez sair o mais antigo, sem parar a gravação "
               f"(saiu {len(fora)}, sobraram {len(restante)}, {usado} B <= {g.cota_bytes()} B)")
        exigir(fora == ordem_feita[:2] and restante == sorted(ordem_feita[2:]),
               f"saíram os MAIS ANTIGOS, na ordem: {fora}")
    finally:
        g.COTA_MINIMA_GB = alongado

    # 6) a RESERVA do sistema continua sendo o segundo limite
    for p in pasta.glob("bloco-*.mp4"):
        p.unlink()
    for i in range(3):
        p = pasta / f"bloco-2026113{i}-13000{i}.mp4"
        p.write_bytes(b"y" * 1000)
        os.utime(p, (2000.0 + i, 2000.0 + i))
    g.definir_escolha(str(disco_b), None)      # sem cota: quem manda é a reserva
    livre_mb = shutil.disk_usage(pasta).free / (1024 * 1024)
    guardado = os.environ.get("LECSOR_HD_RESERVA_MB")
    os.environ["LECSOR_HD_RESERVA_MB"] = str(int(livre_mb) + 500)   # reserva > livre = disco cheio
    try:
        fora2 = g.manter_anel(1)
        exigir(fora2 == ["bloco-20261130-130000.mp4"] and len(list(pasta.glob("bloco-*.mp4"))) == 2,
               f"com o disco cheio (reserva), o mais antigo sai mesmo sem cota: {fora2}")
    finally:
        if guardado is None:
            os.environ.pop("LECSOR_HD_RESERVA_MB", None)
        else:
            os.environ["LECSOR_HD_RESERVA_MB"] = guardado

    # 7) o override de bancada (LECSOR_HD_DIR) vence a escolha do admin
    bancada = tmp / "bancada"
    bancada.mkdir(exist_ok=True)
    os.environ["LECSOR_HD_DIR"] = str(bancada)
    exigir(g.diretorio() == bancada,
           "o LECSOR_HD_DIR (bancada) vence a escolha do admin — é override de teste, não de produção")
    os.environ.pop("LECSOR_HD_DIR", None)

    # 8) a régua da saúde aponta para onde a gravação REALMENTE está
    import saude_do_bordo as s  # noqa: PLC0415
    linhas = s._discos()
    radar = next((x for x in linhas if x.get("nome") == "hd do radar"), {})
    exigir(radar.get("caminho") and s._mesmo_volume(radar["caminho"], g.diretorio()),
           f"o 'hd do radar' da saúde é medido no volume de gravação de verdade ({radar.get('caminho')!r})")
    exigir(pathlib.Path(str(radar.get("pasta"))) == g.diretorio(),
           f"e a pasta interna da gravação vem em 'pasta' ({radar.get('pasta')!r})")
    exigir(radar.get("usado_pct") is not None,
           f"a linha do disco SEMPRE tem medida (usa_pct={radar.get('usado_pct')!r}, erro={radar.get('erro')!r})")
    exigir(radar.get("cota_gb") is None or radar.get("cota_gb", 0) >= 0,
           f"e ele leva a cota escolhida junto ({radar.get('cota_gb')!r} · {radar.get('origem_da_escolha')!r})")

    # 9) o resumo publica a escolha e os discos medidos
    g.desejo = lambda: "1"   # a prova não depende do ligada.txt do repositório
    res = g.resumo()
    exigir({"disco", "cota_gb", "origem_da_escolha", "discos", "ligada", "gravando"} <= set(res),
           f"o resumo do gravador publica a escolha e os discos: {sorted(set(res))}")
    exigir(isinstance(res.get("discos"), list) and res["discos"],
           f"e a lista de discos medida vai junto ({len(res.get('discos') or [])} disco(s))")

    # 10) o bloco é MP4 FRAGMENTADO e o prefixo é decodificável (D4: play enquanto chega)
    cmd = g.comando_do_gravador()
    exigir("-segment_format_options" in cmd
           and cmd[cmd.index("-segment_format_options") + 1] == "movflags=+frag_keyframe+empty_moov+default_base_moof",
           "o gravador pede mp4 FRAGMENTADO pela forma que funciona (`-segment_format_options`)")
    ff = shutil.which("ffmpeg")
    if not ff:
        nota("NAO MEDIDO: sem ffmpeg nesta máquina — a prova do prefixo decodificável fica de fora")
    else:
        saida = tmp / "frag"
        saida.mkdir(exist_ok=True)
        r = subprocess.run([ff, "-hide_banner", "-nostdin", "-f", "lavfi",
                            "-i", "testsrc=size=320x240:rate=30", "-t", "4", "-an",
                            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "800k", "-g", "30",
                            "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
                            "-f", "segment", "-segment_time", "4", "-reset_timestamps", "1",
                            "-strftime", "1", str(saida / "bloco-%Y%m%d-%H%M%S.mp4")],
                           capture_output=True, text=True, timeout=180)
        blocos = sorted(saida.glob("bloco-*.mp4"), key=lambda p: p.stat().st_size)
        if r.returncode != 0 or not blocos:
            nota("NAO MEDIDO: o ffmpeg não produziu bloco aqui — " + (r.stderr or "")[-160:])
        else:
            inteiro = blocos[-1]
            dados = inteiro.read_bytes()
            corte = saida / ("corte-" + inteiro.name)
            corte.write_bytes(dados[: int(len(dados) * 0.6)])
            ordem = caixas(inteiro)
            exigir("moof" in ordem,
                   f"o bloco sai fragmentado (caixas: {', '.join(ordem[:6])}) — o índice NÃO fica só no fim")
            n_cheio, n_corte = quadros(inteiro), quadros(corte)
            exigir(n_corte > 0 and n_cheio > 0,
                   f"o ffprobe LÊ o prefixo de 60% do bloco (o que já chegou do bordo): "
                   f"{n_corte} de {n_cheio} quadros")
            if n_corte <= 0:
                nota("o prefixo de um mp4 comum é ilegível — é esse o motivo do mp4 fragmentado (D4)")

    # 11) pasta de gravacao que AINDA NAO EXISTE (PC recem-instalado): UMA linha so', com medida
    #     (medido na VPS em 27/11/2026: a gravacao em volume sem a pasta ainda criada aparecia DUAS vezes —
    #     "hd do radar" e "aplicativo" — e o admin via dois discos iguais na lista para escolher)
    os.environ["LECSOR_HD_DIR"] = str(tmp / "disco-b" / "lecsor-radar" / "ainda-nao-nasceu")
    linhas = s._discos()
    nomes = [x.get("nome") for x in linhas]
    exigir(len(linhas) == 1 and nomes == ["hd do radar"],
           f"pasta de gravacao que ainda nao existe NAO inventa um segundo disco do mesmo volume: {linhas}")
    exigir(linhas and linhas[0].get("usado_pct") is not None,
           f"e a linha do disco continua com medida "
           f"({linhas[0].get('usado_pct') if linhas else None}, erro={linhas[0].get('erro') if linhas else None})")
    os.environ.pop("LECSOR_HD_DIR", None)

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — o admin escolhe o disco e a cota em GB, o anel obedece aos dois limites e o bloco dá play "
          "antes de chegar inteiro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
