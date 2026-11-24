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
    # A VERSAO DO APP QUE ESTA' RODANDO (24/11/2026): quem manda e' o Electron (`app.getVersion()`, no
    # `desktop/main.js`), porque no PACOTE nao existe `desktop/package.json` — e o retrato subia com
    # `versao_app` vazio, deixando o admin sem saber qual versao estava no barco.
    v = (os.environ.get("LECSOR_VERSAO_APP") or "").strip()
    if v:
        return v
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


def _memoria_total_mb() -> float | None:
    try:
        import psutil
        return round(psutil.virtual_memory().total / 1e6, 1)
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------- REDE (global: por interface)
# A taxa e' a media do intervalo entre DUAS leituras (o retrato sobe de 60 em 60 s), nao um instantaneo:
# o painel diz "desde a ultima leitura" para nao parecer um medidor ao vivo.
_REDE_ANTES: dict = {"t": 0.0, "por": {}}


def _rede() -> tuple[list, dict, str]:
    """(interfaces, total, motivo) — bytes acumulados e taxa por interface + o somatorio da maquina.

    Sem `psutil` nao se inventa numero: devolve ([], {}, motivo) e o motivo sobe em `nao_medido`.
    """
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return [], {}, "sem psutil: rede nao medida"
    try:
        cont = psutil.net_io_counters(pernic=True)
    except Exception as e:  # noqa: BLE001
        return [], {}, f"{type(e).__name__}: {e}"
    agora = time.time()
    dt_s = agora - float(_REDE_ANTES.get("t") or 0)
    antes_por = _REDE_ANTES.get("por") or {}
    interfaces: list = []
    total = {"enviado_mb": 0.0, "recebido_mb": 0.0, "enviado_mbps": 0.0, "recebido_mbps": 0.0,
             "taxa_mbps": 0.0, "intervalo_s": round(dt_s, 1) if _REDE_ANTES.get("t") else None}
    for nome, c in cont.items():
        linha = {"nome": nome, "enviado_mb": round(c.bytes_sent / 1e6, 2),
                 "recebido_mb": round(c.bytes_recv / 1e6, 2)}
        antes = antes_por.get(nome)
        if antes and dt_s > 0:
            linha["enviado_mbps"] = round((c.bytes_sent - antes[0]) * 8 / 1e6 / dt_s, 3)
            linha["recebido_mbps"] = round((c.bytes_recv - antes[1]) * 8 / 1e6 / dt_s, 3)
        interfaces.append(linha)
        for k in ("enviado_mb", "recebido_mb", "enviado_mbps", "recebido_mbps"):
            total[k] += float(linha.get(k) or 0)
    for k in ("enviado_mb", "recebido_mb", "enviado_mbps", "recebido_mbps"):
        total[k] = round(total[k], 2)
    total["taxa_mbps"] = round(total["enviado_mbps"] + total["recebido_mbps"], 2)
    _REDE_ANTES["t"] = agora
    _REDE_ANTES["por"] = {n: (c.bytes_sent, c.bytes_recv) for n, c in cont.items()}
    return interfaces, total, ""


def _individual() -> list:
    """A camada POR CAMERA/encoder: o que cada fluxo desta maquina esta' consumindo agora.

    Uma linha por ingestao no ar, com o que o banco sabe (kbps/fps/estado) e o que o processo do
    ffmpeg daquele fluxo gasta (CPU, memoria) — o "individual" que o dono pediu (24/11/2026).
    """
    try:
        import psutil
    except Exception:  # noqa: BLE001
        psutil = None
    try:
        con = sqlite3.connect(str(_banco()), timeout=10)
        con.row_factory = sqlite3.Row
        try:
            regs = con.execute("SELECT id, camera_id, rotulo, estado, bitrate_saida_kbps, fps, pid, codec "
                               "FROM ingestoes WHERE estado NOT IN ('parado','fim') ORDER BY id").fetchall()
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        return [{"erro": f"{type(e).__name__}: {e}"}]
    saida = []
    for r in regs:
        linha = {"ingestao_id": r["id"], "camera_id": r["camera_id"], "rotulo": r["rotulo"],
                 "estado": r["estado"], "kbps": r["bitrate_saida_kbps"], "fps": r["fps"],
                 "codec": r["codec"], "pid": r["pid"], "cpu_pct": None, "memoria_mb": None}
        if psutil is not None and r["pid"]:
            try:
                p = psutil.Process(int(r["pid"]))
                linha["cpu_pct"] = round(p.cpu_percent(interval=0.1), 1)
                linha["memoria_mb"] = round(p.memory_info().rss / 1e6, 1)
            except Exception as e:  # noqa: BLE001
                linha["processo"] = f"{type(e).__name__}"   # processo ja' morreu: mede quem estiver vivo
        elif psutil is None:
            linha["processo"] = "sem psutil"
        saida.append(linha)
    return saida


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
    """O laco do agente esta' vivo? O sinal e' a idade do arquivo de estado dele (o ultimo 'estive aqui').

    O caminho e' do PROPRIO agente (`caminho_do_vivo()`): quem escreve decide onde. Havia dois padroes
    diferentes (aqui `ground/agente-vivo.json`, no agente `ordens/agente-vivo.json`) e a saude passava a
    dizer "o agente nunca escreveu o estado" numa maquina que estava trabalhando — fonte unica, sempre.
    """
    try:
        from agente_de_ordens import caminho_do_vivo
        padrao = caminho_do_vivo()
    except Exception:  # noqa: BLE001
        padrao = RAIZ / "ordens" / "agente-vivo.json"
    caminho = pathlib.Path(os.environ.get("LECSOR_AGENTE_ESTADO") or padrao)
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


def _varredura() -> dict:
    """O ultimo resultado da varredura do bordo, sem segredo (contagens, ids e motivo)."""
    try:
        import varredura_do_bordo
        r = varredura_do_bordo.ultima()
        if not r:
            return {"ainda": "nenhuma varredura desde que o sistema subiu"}
        return {"ok": bool(r.get("ok")), "vistos": r.get("vistos"),
                "cadastradas": r.get("cadastradas") or [], "atualizadas": r.get("atualizadas") or [],
                "publicadas": r.get("publicadas") or [],
                "falhas_de_publicacao": r.get("falhas_de_publicacao") or [],
                "radar": r.get("radar") or {}, "motivo": r.get("motivo") or "",
                "intervalo_s": varredura_do_bordo.intervalo()}
    except Exception as e:  # noqa: BLE001
        return {"erro": f"{type(e).__name__}: {e}"}


def retrato() -> dict:
    """O retrato completo — sem segredo nenhum. E' isto que sobe para o admin."""
    cpu, mem, mem_livre, nao_medido = _cpu_memoria()
    discos = _discos()
    interfaces, rede_total, rede_motivo = _rede()
    if rede_motivo:
        nao_medido["rede"] = rede_motivo
    individual = _individual()
    # O "GLOBAL" (dono, 24/11/2026): a maquina inteira num lugar so' — CPU, memoria, disco e rede.
    global_ = {
        "cpu_pct": cpu,
        "memoria_pct": mem,
        # ATENCAO: `memoria_livre_mb` e' o DISPONIVEL do psutil (inclui cache/standby) — o "livre" do
        # Windows e' ~5 % menor. O rotulo do painel diz "disponivel" (conferido em 24/11/2026).
        "memoria_disponivel_mb": mem_livre,
        "memoria_total_mb": _memoria_total_mb(),
        "discos": discos,
        "rede": rede_total,
        "processos": len(individual),
    }
    r = {
        "gerado_em": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "maquina": socket.gethostname(),
        "so": f"{platform.system()} {platform.release()}",
        "versao_app": _versao_app(),
        "uptime_s": _uptime_s(),
        "cpu_pct": cpu,
        "memoria_pct": mem,
        "memoria_livre_mb": mem_livre,
        "memoria_disponivel_mb": mem_livre,
        "discos": discos,
        # TELEMETRIA INDIVIDUAL E GLOBAL (dono, 24/11/2026): "individual" = uma linha por
        # camera/encoder desta maquina; "global" = a maquina inteira. Os campos de cima continuam
        # iguais (compatibilidade com o que o admin ja' le).
        "individual": individual,
        "global": global_,
        "rede": {"interfaces": interfaces, "total": rede_total},
        "ffmpeg": _ffmpeg(),
        "dispositivos_video": _dispositivos(),
        "agente": _agente(),
        "mediamtx": _mediamtx(),
        "banco": _banco_resumo(),
        # VARREDURA DO BORDO (Fase 2, 19/11/2026): o que o app achou nesta maquina sozinho — quantos
        # dispositivos viu, o que cadastrou e o que ficou sem publicar. Sem segredo: so' contagem e id.
        "varredura": _varredura(),
        "nao_medido": nao_medido,
    }
    return r


# ------------------------------------------------------------------ HISTORICO DA SAUDE (dono, 24/11/2026)
# "preciso de um dashboard real no pc de captura ... so tem um monte de cards". Um painel de verdade
# mostra a EVOLUCAO da medida, nao so' o numero de agora: esta maquina guarda uma linha por rodada da
# saude (60 s) num anel de 2 dias e a pagina `/bordo` desenha as curvas. Nada de segredo: CPU, memoria,
# disco e rede — os mesmos numeros que ja' sobem para o lado terra.
MAX_PONTOS_DO_HISTORICO = 2880          # 2 dias a 60 s


def caminho_do_historico() -> pathlib.Path:
    """Onde fica o anel da saude (`LECSOR_SAUDE_HISTORICO` troca o caminho — usado nos testes)."""
    trocado = (os.environ.get("LECSOR_SAUDE_HISTORICO") or "").strip()
    return pathlib.Path(trocado) if trocado else (RAIZ / "saude" / "historico-da-saude.jsonl")


def ponto_do_retrato(r: dict) -> dict:
    """O retrato inteiro reduzido a UMA linha — e' o ponto que o grafico do painel desenha."""
    discos = [d for d in (r.get("discos") or []) if isinstance(d, dict)]
    hd = next((d for d in discos if d.get("nome") == "hd do radar"), None) or (discos[0] if discos else {})
    total = ((r.get("rede") or {}).get("total") or {})
    return {"t": r.get("gerado_em") or dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "cpu": r.get("cpu_pct"), "mem": r.get("memoria_pct"),
            "disco": hd.get("usado_pct"), "disco_livre_gb": hd.get("livre_gb"),
            "disco_nome": hd.get("nome") or "",
            "rede_mbps": total.get("taxa_mbps"), "rede_env_mb": total.get("enviado_mb"),
            "rede_rec_mb": total.get("recebido_mb"), "up_s": r.get("uptime_s")}


def registrar_historico(r: dict, limite: int = MAX_PONTOS_DO_HISTORICO) -> dict:
    """Grava o ponto desta rodada no anel. Falhar aqui NUNCA derruba a captura (quem chama ignora)."""
    try:
        alvo = caminho_do_historico()
        alvo.parent.mkdir(parents=True, exist_ok=True)
        linhas = []
        if alvo.exists():
            linhas = [x for x in alvo.read_text(encoding="utf-8").splitlines() if x.strip()]
        linhas.append(json.dumps(ponto_do_retrato(r), ensure_ascii=False))
        linhas = linhas[-max(1, int(limite)):]
        alvo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        return {"ok": True, "pontos": len(linhas)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"}


def historico(limite: int = 720) -> list:
    """A serie recente (padrao 720 pontos = 12 h a 60 s), do mais ANTIGO para o mais NOVO."""
    try:
        linhas = caminho_do_historico().read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001  (sem historico ainda: a pagina sabe dizer "sem serie")
        return []
    pontos = []
    for linha in linhas[-max(1, int(limite)):]:
        try:
            d = json.loads(linha)
            if isinstance(d, dict) and d.get("t"):
                pontos.append(d)
        except Exception:  # noqa: BLE001  (linha torta nao derruba a serie inteira)
            continue
    return pontos


if __name__ == "__main__":
    print(json.dumps(retrato(), ensure_ascii=False, indent=2))
