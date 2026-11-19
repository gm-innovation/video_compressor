#!/usr/bin/env python3
"""GRAVACAO CONTINUA DO RADAR no PC de captura (0.7.0) — blocos, linha do tempo e anel de disco.

Palavras do dono (19/11/2026): "as imagens devem ser comprimidas e guardadas para eventuais pesquisas,
ou seja, mesmo que o cliente nao acione o streaming do radar de oleo, as imagens estarao sendo comprimidas
e gravadas full time, o cliente pode acessar as imagens a qualquer momento" · "pode ir gravando e quando
acabar o espaco comeca a gravar por cima do mais antigo" · blocos menores para "encontrar os horarios na
linha do tempo".

    python tests/test-gravacao-continua-do-radar.py

Provas (com a camera REAL desta maquina como dublê do radar no HDMI):
  1) DESLIGADA por padrao: com `LECSOR_GRAVACAO_CONTINUA` ausente, `rodar()` nao sobe gravador nenhum;
  2) LIGADA: aparecem BLOCOS de 2 s no HD local, com nome-relogio (bloco-AAAAMMDD-HHMMSS.mp4);
  3) a LINHA DO TEMPO responde por horario (`blocos_no_intervalo`) sem abrir video;
  4) o RESUMO conta o que existe (quantos, primeiro, ultimo, bytes);
  5) ANEL: com o disco "cheio" (reserva maior que o livre), o bloco MAIS ANTIGO e' apagado e a gravacao
     continua — nunca para por falta de espaco;
  6) a gravacao NAO depende da flag/sessao: nenhuma transmissao foi pedida e os blocos existem.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
PY = sys.executable


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def roda(codigo: str, env: dict, timeout=90):
    e = dict(os.environ)
    e.update(env)
    e["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([PY, "-c", codigo], cwd=str(RAIZ), env=e, capture_output=True, text=True,
                          errors="replace", timeout=timeout)


def dispositivo_de_video() -> str:
    r = roda("import sys; sys.path.insert(0,'ground'); import ingestao as i; "
             "print((i.listar_dispositivos().get('dispositivos') or [{}])[0].get('video',''))", {})
    return (r.stdout or "").strip().splitlines()[-1].strip() if r.stdout.strip() else ""


def conta_blocos(hd: pathlib.Path) -> int:
    return len(list(hd.glob("bloco-*.mp4")))


def main() -> int:
    hd = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-hd-"))
    disp = dispositivo_de_video()
    nota(f"HD de teste: {hd} · dispositivo: {disp or 'NENHUM'}")
    env_base = {"LECSOR_HD_DIR": str(hd), "LECSOR_BLOCO_SEGUNDOS": "2",
                "LECSOR_HD_DISPOSITIVO": disp, "LECSOR_HD_CAMERA": "radar-oleo",
                "LECSOR_HD_BITRATE": "300k", "LECSOR_HD_RESOLUCAO": "640x480"}

    # 1) desligada por padrao
    r = roda("import sys; sys.path.insert(0,'ground'); import gravacao_continua as g; "
             "print('rc', g.rodar(uma_vez=True))", env_base)
    exigir("DESLIGADA" in r.stdout and conta_blocos(hd) == 0,
           f"com a gravacao desligada nada e' gravado ({r.stdout.strip()[:60]!r})")

    if not disp:
        nota("NAO MEDIDO: sem dispositivo de video nesta maquina — a parte ao vivo fica de fora")
        print()
        print("PARCIAL — o resto depende de um dispositivo de video")
        return 1 if falhas else 0

    # 2) ligada: blocos aparecem
    env = dict(env_base)
    env["LECSOR_GRAVACAO_CONTINUA"] = "1"
    proc = subprocess.Popen([PY, str(RAIZ / "ground" / "gravacao_continua.py")], cwd=str(RAIZ),
                            env={**os.environ, **env, "PYTHONIOENCODING": "utf-8"},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        achou = False
        fim = time.time() + 60
        while time.time() < fim:
            if conta_blocos(hd) >= 2:
                achou = True
                break
            time.sleep(1.0)
        exigir(achou, f"a gravacao continua produziu blocos de 2 s no HD ({conta_blocos(hd)} bloco(s))")
        if not achou:
            return 1

        # 3) a linha do tempo responde por horario
        r = roda("import sys,json,datetime as dt; sys.path.insert(0,'ground'); import gravacao_continua as g; "
                 "agora=dt.datetime.now(); de=(agora-dt.timedelta(minutes=5)).isoformat(timespec='seconds'); "
                 "ate=(agora+dt.timedelta(seconds=1)).isoformat(timespec='seconds'); "
                 "print(json.dumps([b['arquivo'] for b in g.blocos_no_intervalo(de,ate)]))", env)
        achados = json.loads((r.stdout or "[]").strip().splitlines()[-1] or "[]")
        exigir(len(achados) >= 1, f"a linha do tempo acha os blocos pelo horario ({len(achados)} no intervalo)")
        r2 = roda("import sys,json,datetime as dt; sys.path.insert(0,'ground'); import gravacao_continua as g; "
                  "agora=dt.datetime.now(); de=(agora+dt.timedelta(days=300)).isoformat(timespec='seconds'); "
                  "ate=(agora+dt.timedelta(days=301)).isoformat(timespec='seconds'); "
                  "print(json.dumps(g.blocos_no_intervalo(de,ate)))", env)
        exigir(json.loads((r2.stdout or "[]").strip().splitlines()[-1] or "[]") == [],
               "um intervalo sem bloco devolve VAZIO (nao inventa imagem)")

        # 4) o resumo conta o que existe
        r = roda("import sys,json; sys.path.insert(0,'ground'); import gravacao_continua as g; "
                 "print(json.dumps(g.resumo()))", env)
        res = json.loads((r.stdout or "{}").strip().splitlines()[-1] or "{}")
        exigir(res.get("blocos", 0) >= 1 and res.get("primeiro") and res.get("ultimo"),
               f"o resumo do HD conta os blocos e as pontas ({res.get('blocos')} blocos, "
               f"{str(res.get('primeiro'))[11:19]} ate' {str(res.get('ultimo'))[11:19]})")

        # 5) anel: com o disco "cheio", o mais antigo sai e a gravacao NAO para
        antes = sorted(p.name for p in hd.glob("bloco-*.mp4"))
        livre_mb = shutil.disk_usage(hd).free / (1024 * 1024)
        env_cheio = dict(env)
        env_cheio["LECSOR_HD_RESERVA_MB"] = str(int(livre_mb) + 200)   # reserva > livre = disco "cheio"
        r = roda("import sys,json; sys.path.insert(0,'ground'); import gravacao_continua as g; "
                 "print(json.dumps(g.manter_anel(1)))", env_cheio)
        saida = json.loads((r.stdout or "[]").strip().splitlines()[-1] or "[]")
        exigir(len(saida) == 1 and saida[0] == antes[0],
               f"anel: o bloco MAIS ANTIGO foi apagado quando o espaco acabou ({saida})")
        time.sleep(4)
        exigir(conta_blocos(hd) >= 1 and sorted(p.name for p in hd.glob("bloco-*.mp4")) != antes,
               f"a gravacao CONTINUOU depois do anel ({conta_blocos(hd)} bloco(s) no HD)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s): " + "; ".join(falhas[:4]))
        return 1
    print("OK — o radar de oleo e' gravado full time em blocos por horario, com anel de disco, sem "
          "depender do cliente pedir transmissao")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
