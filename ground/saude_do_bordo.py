#!/usr/bin/env python3
"""RETRATO DE SAUDE DO COMPUTADOR DE CAPTURA (0.8.0, Fase 5).

Dono (19/11/2026): "vamos incluir tambem uma forma de o app de captura enviar para o admin dados de saude
para monitorarmos se esta tudo okay ou se ha algum problema que devemos corrigir ou acompanhar".

Regra dura: o retrato NAO leva segredo nenhum (nem endereco de camera, nem credencial, nem token). Ele
responde "esta tudo okay ou tem algo para corrigir/acompanhar" — CPU, memoria, disco (e o anel do HD do
radar), se o ffmpeg existe, se a captura esta' viva, se o mediamtx respondeu, quando foi a ultima saida
bem-sucedida, quantos pedidos estao pendentes e quantos erros houve nas ultimas 24 h.

Sem `psutil` o programa nao inventa numero: o que nao der para medir sai como `None` com o motivo em
`nao_medido` (numa bancada Linux a leitura vem de /proc; no Windows, de psutil quando ele existe).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "ground") not in sys.path:
    sys.path.insert(0, str(RAIZ / "ground"))

LIMITE_ERROS = 20            # a partir daqui o sinal de erros vira amarelo no painel


def _banco() -> pathlib.Path:
    trocado = (os.environ.get("LECSOR_BANCO") or "").strip()
    return pathlib.Path(trocado) if trocado else (RAIZ / "db" / "pipeline.db")


def _versao_app() -> str:
    for nome in ("VERSION", "versao.txt"):
        p = RAIZ / nome
        try:
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            pass
    try:
        pkg = json.loads((RAIZ / "desktop" / "package.json").read_text(encoding="utf-8"))
        return str(pkg.get("version") or "")
    except Exception:  # noqa: BLE001
        return ""


def _uptime_s() -> int | None:
    if os.name == "nt":
        try:
            import ctypes
            return int(ctypes.windll.kernel32.GetTickCount64() / 1000)
        except Exception:  # noqa: BLE001
            return None
    try:
        return int(float(pathlib.Path("/proc/uptime").read_text().split()[0]))
    except Exception:  # noqa: BLE001
        return None


def _cpu_memoria() -> tuple[float | None, float | None, float | None, dict]:
    """(cpu_pct, memoria_pct, memoria_livre_mb, nao_medido) — psutil quando existe, senao /proc."""
    nao_medido: dict = {}
    try:
        import psutil
        vm = psutil.virtual_memory()
        return (float(psutil.cpu_percent(interval=0.2)), float(vm.percent),
                round(vm.available / 1e6, 1), nao_medido)
    except Exception:  # noqa: BLE001
        pass
    if os.name != "nt":
        try:
            load = float(pathlib.Path("/proc/loadavg").read_text().split()[0])
            cpus = os.cpu_count() or 1
            info = {}
            for linha in pathlib.Path("/proc/meminfo").read_text().splitlines():
                k, _, v = linha.partition(":")
                info[k.strip()] = float(v.split()[0]) / 1024.0     # MB
            total, disp = info.get("MemTotal", 0.0), info.get("MemAvailable", 0.0)
            pct = round(100.0 * (total - disp) / total, 1) if total else None
            return (round(100.0 * load / cpus, 1), pct, round(disp, 1), nao_medido)
        except Exception as e:  # noqa: BLE001
            nao_medido["cpu_memoria"] = f"/proc nao pode ser lido ({type(e).__name__})"
            return None, None, None, nao_medido
    nao_medido["cpu_memoria"] = "sem psutil neste Windows (instalar psutil para medir)"
    return None, None, None, nao_medido


def _discos() -> list:
    """Onde o produto grava: a pasta do aplicativo e o HD do radar (o anel de gravacao continua)."""
    alvos = [("aplicativo", RAIZ)]
    hd = (os.environ.get("LECSOR_HD_DIR") or "").strip()
    if hd:
        alvos.append(("hd do radar", pathlib.Path(hd)))
    saida = []
    for nome, p in alvos:
        try:
            uso = shutil.disk_usage(str(p))
            linha = {"nome": nome, "caminho": str(p),
                     "total_gb": round(uso.total / 1e9, 1), "livre_gb": round(uso.free / 1e9, 1),
                     "usado_pct": round(100.0 * uso.used / uso.total, 1) if uso.total else None}
            if nome == "hd do radar":
                linha.update(_anel_do_hd(p))
            saida.append(linha)
        except Exception as e:  # noqa: BLE001
            saida.append({"nome": nome, "caminho": str(p), "erro": f"{type(e).__name__}: {e}"})
    return saida


def _anel_do_hd(pasta: pathlib.Path) -> dict:
    """O anel da gravacao continua: quantos blocos e qual o MAIS ANTIGO (e' ele que sai primeiro)."""
    try:
        blocos = sorted([x for x in pasta.glob("*.mp4") if x.is_file()], key=lambda x: x.stat().st_mtime)
        if not blocos:
            return {"blocos": 0, "mais_antigo": "", "mais_novo": ""}
        return {"blocos": len(blocos),
                "mais_antigo": dt.datetime.fromtimestamp(blocos[0].stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "mais_novo": dt.datetime.fromtimestamp(blocos[-1].stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "bytes": sum(x.stat().st_size for x in blocos)}
    except Exception as e:  # noqa: BLE001
        return {"erro": f"{type(e).__name__}: {e}"}


def _ffmpeg() -> dict:
    exe = shutil.which("ffmpeg")
    if not exe:
        local = RAIZ / "tools" / "ffmpeg.exe"
        exe = str(local) if local.exists() else ""
    if not exe:
        return {"presente": False, "caminho": ""}
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=20)
        return {"presente": True, "caminho": exe, "versao": (r.stdout or "").splitlines()[0][:120]}
    except Exception as e:  # noqa: BLE001
        return {"presente": True, "caminho": exe, "erro": f"{type(e).__name__}: {e}"}


def _dispositivos() -> dict:
    try:
        import ingestao  # o mesmo listador que a tela usa: uma fonte so'
        d = ingestao.listar_dispositivos()
        return {"quantos": len(d.get("dispositivos") or []),
                "padrao": str(d.get("padrao") or ""),
                "nomes": [str(x.get("rotulo") or x.get("video") or "") for x in (d.get("dispositivos") or [])][:8]}
    except Exception as e:  # noqa: BLE001
        return {"quantos": None, "erro": f"{type(e).__name__}: {e}"}


def _agente() -> dict:
    """O laco do agente esta' vivo? O sinal e' a idade do arquivo de estado dele (o ultimo 'estive aqui')."""
    caminho = pathlib.Path(os.environ.get("LECSOR_AGENTE_ESTADO") or (RAIZ / "ground" / "agente-vivo.json"))
    try:
        if not caminho.exists():
            return {"laco_vivo": False, "ultima_rodada_em": "", "motivo": "o agente nunca escreveu o estado"}
        idade = time.time() - caminho.stat().st_mtime
        dados = json.loads(caminho.read_text(encoding="utf-8") or "{}")
        return {"laco_vivo": idade < 300, "idade_s": round(idade),
                "ultima_rodada_em": str(dados.get("em") or ""), "rodadas": dados.get("rodadas")}
    except Exception as e:  # noqa: BLE001
        return {"laco_vivo": False, "erro": f"{type(e).__name__}: {e}"}


def _mediamtx() -> dict:
    try:
        import urllib.request
        porta = (os.environ.get("LECSOR_PORTA_API_MEDIAMTX") or "9997").strip()
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/v3/paths/list", timeout=5) as f:
            j = json.loads(f.read() or b"{}")
        return {"ativo": True, "caminhos": len(j.get("items") or [])}
    except Exception as e:  # noqa: BLE001
        return {"ativo": False, "motivo": f"{type(e).__name__}: {e}"}


def _banco_resumo() -> dict:
    """Contagens do bordo (nada de conteudo): cameras, pedidos pendentes, ultima saida e erros de 24 h."""
    caminho = _banco()
    if not caminho.exists():
        return {"ok": False, "motivo": f"banco nao encontrado em {caminho}"}
    try:
        con = sqlite3.connect(str(caminho), timeout=10)
        con.row_factory = sqlite3.Row
        try:
            def contar(sql, args=()):
                try:
                    return int(con.execute(sql, args).fetchone()[0])
                except Exception:  # noqa: BLE001
                    return None
            corte = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat(timespec="seconds")
            return {
                "ok": True,
                "cameras": contar("SELECT count(*) FROM cameras WHERE ativo=1"),
                "ingestoes_no_ar": contar("SELECT count(*) FROM ingestoes WHERE estado NOT IN ('parado','fim')"),
                "pedidos_pendentes": contar("SELECT count(*) FROM hd_pedidos WHERE estado NOT IN ('enviado','entregue','erro')"),
                "erros_24h": contar("SELECT count(*) FROM ingestoes WHERE erro != '' AND atualizado_em >= ?", (corte,)),
                "ultima_saida": (lambda r: str(r["atualizado_em"]) if r else "")(
                    con.execute("SELECT atualizado_em FROM ingestoes WHERE estado NOT IN ('erro') "
                                "ORDER BY atualizado_em DESC LIMIT 1").fetchone()),
            }
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"}


def retrato() -> dict:
    """O retrato completo — sem segredo nenhum. E' isto que sobe para o admin."""
    cpu, mem, mem_livre, nao_medido = _cpu_memoria()
    r = {
        "gerado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "maquina": socket.gethostname(),
        "so": f"{platform.system()} {platform.release()}",
        "versao_app": _versao_app(),
        "uptime_s": _uptime_s(),
        "cpu_pct": cpu,
        "memoria_pct": mem,
        "memoria_livre_mb": mem_livre,
        "discos": _discos(),
        "ffmpeg": _ffmpeg(),
        "dispositivos_video": _dispositivos(),
        "agente": _agente(),
        "mediamtx": _mediamtx(),
        "banco": _banco_resumo(),
        "nao_medido": nao_medido,
    }
    return r


if __name__ == "__main__":
    print(json.dumps(retrato(), ensure_ascii=False, indent=2))
