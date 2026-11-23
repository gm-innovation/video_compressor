#!/usr/bin/env python3
"""Relatorio do smoke: uma jornada, uma lista de checagens, um veredito com numero.

Regra dura (plano de 23/11/2026): *sem medida, a jornada e' "NAO MEDIDA" — nunca "OK"*. Uma checagem
que nao pode ser feita entra como `medido=False` e aparece no relatorio com o motivo; o veredito so'
e' OK quando TODAS as checagens passaram com medida.

Vereditos: `OK` | `OK_COM_RESSALVAS` (passou tudo, mas algo ficou sem medida) | `FALHA` | `NAO_MEDIDA`.
"""
from __future__ import annotations

import json
import os
import pathlib
import platform
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ / "ground") not in sys.path:
    sys.path.insert(0, str(RAIZ / "ground"))

# Os tres numeros que o produto promete ao cliente (Fase 4 do plano). Abaixo do alvo o veredito e'
# "com ressalvas", NUNCA "OK" — vale para o relatorio tambem, nao so' para as jornadas.
ALVO_FPS = 30.0
ALVO_LATENCIA_S = 3.0
ALVO_REDUCAO_PCT = 80.0


class Jornada:
    def __init__(self, numero: int, titulo: str, promessa: str = "") -> None:
        self.numero = numero
        self.titulo = titulo
        self.promessa = promessa
        self.checagens: list[dict] = []
        self.medidas: dict = {}
        self.t_inicio = time.time()
        self.t_fim: float | None = None
        self.erro: str = ""

    # ---------------------------------------------------------------- checagens
    def checar(self, nome: str, ok: bool, detalhe: str = "", medido: bool = True) -> bool:
        self.checagens.append({"nome": nome, "ok": bool(ok) if medido else None,
                               "medido": bool(medido), "detalhe": str(detalhe or "")})
        marca = ("OK   " if ok else "FALHA") if medido else "SEM M"
        print(f"    {marca} {nome}" + (f" — {detalhe}" if detalhe else ""), flush=True)
        return bool(ok) if medido else False

    def medir(self, **valores) -> None:
        self.medidas.update(valores)

    # ---------------------------------------------------------------- veredito
    def fechar(self) -> None:
        self.t_fim = time.time()

    def veredito(self) -> str:
        if self.erro:
            return "FALHA"
        falhas = [c for c in self.checagens if c["medido"] and not c["ok"]]
        sem_medida = [c for c in self.checagens if not c["medido"]]
        if falhas:
            return "FALHA"
        if not self.checagens:
            return "NAO_MEDIDA"
        if sem_medida:
            return "OK_COM_RESSALVAS"
        return "OK"

    def resumo(self) -> dict:
        return {"jornada": self.numero, "titulo": self.titulo, "promessa": self.promessa,
                "veredito": self.veredito(), "erro": self.erro,
                "duracao_s": round((self.t_fim or time.time()) - self.t_inicio, 1),
                "checagens": self.checagens, "medidas": self.medidas,
                "falhas": [c["nome"] for c in self.checagens if c["medido"] and not c["ok"]],
                "sem_medida": [c["nome"] for c in self.checagens if not c["medido"]]}

    # ---------------------------------------------------------------- evidencia
    def gravar(self, raiz: pathlib.Path, dia: str, extratos: dict | None = None) -> dict:
        self.fechar()
        pasta = pathlib.Path(raiz) / dia / f"j{self.numero}"
        pasta.mkdir(parents=True, exist_ok=True)
        dados = self.resumo()
        (pasta / "resultado.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        linhas = [f"# J{self.numero} — {self.titulo}", "", f"**Veredito: {dados['veredito']}**",
                  f"({dados['duracao_s']}s)", ""]
        if self.promessa:
            linhas += [f"> {self.promessa}", ""]
        if self.erro:
            linhas += [f"**Erro que interrompeu:** `{self.erro}`", ""]
        linhas.append("## Checagens")
        for c in self.checagens:
            if not c["medido"]:
                linhas.append(f"- [ ] SEM MEDIDA — {c['nome']} {c['detalhe']}")
            else:
                linhas.append(f"- [{'x' if c['ok'] else ' '}] {c['nome']}"
                              + (f" — {c['detalhe']}" if c["detalhe"] else ""))
        if self.medidas:
            linhas += ["", "## Medidas"]
            for k, v in self.medidas.items():
                linhas.append(f"- `{k}`: {v}")
        if extratos:
            for titulo, texto in extratos.items():
                linhas += ["", f"## {titulo}", "```", str(texto)[-4000:], "```"]
        (pasta / "qa.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
        return dados


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def qualidade(jornadas: list[dict], ambiente: dict, dia: str, comando: str = "", commit: str = "") -> dict:
    """OS TRES NUMEROS do produto num lugar so' (Fase 4 do plano), com o comando e a maquina carimbados.

    * **fps** e **latencia** saem da **J2** — a jornada que mede o caminho (a fonte entrega em tempo real,
      senao a taxa de entrega nao vale como medida);
    * **reducao de banda** e' medida contra o **bruto teorico da fonte**, pela regra do proprio produto
      (`ground/entrada.py`: `W x H x fps x 12 / 8`) — a fonte e' crua (webcam/`testsrc2`), entao nao existe
      fluxo comprimido de entrada para comparar; o que se mede e' quanto custaria mandar o video cru.

    Regra do plano: numero abaixo do alvo (ou sem medida) => **"funcionou com ressalvas", nunca "OK"**.
    """
    j2 = next((j for j in jornadas if j.get("jornada") == 2), None)
    medidas = (j2 or {}).get("medidas") or {}
    tela = medidas.get("tela") or {}
    fps = _numero(medidas.get("fps_midia"))
    latencia = _numero(medidas.get("latencia_s"))
    mbps = _numero(medidas.get("mbps"))
    largura = int(tela.get("largura") or 0)
    altura = int(tela.get("altura") or 0)

    bruto_kbps = None
    if largura and altura and fps:
        try:
            import entrada as _entrada   # regra do produto, nunca uma conta reescrita aqui
            bruto_kbps = _entrada.entrada_teorica_kbps(f"{largura}x{altura}", fps)
        except Exception:  # noqa: BLE001
            bruto_kbps = None
    reducao = (round((1 - (mbps * 1000.0) / bruto_kbps) * 100, 2)
               if (bruto_kbps and mbps is not None) else None)

    numeros = {"fps": fps, "latencia_s": latencia, "reducao_pct": reducao}
    alvos = {"fps": ALVO_FPS, "latencia_s": ALVO_LATENCIA_S, "reducao_pct": ALVO_REDUCAO_PCT}
    sem_medida = [k for k, v in numeros.items() if v is None]
    fora = [k for k, v in numeros.items()
            if v is not None and ((v > alvos[k]) if k == "latencia_s" else (v < alvos[k]))]
    if len(sem_medida) == len(numeros):
        veredito = "NAO_MEDIDA"
    elif sem_medida or fora:
        veredito = "OK_COM_RESSALVAS"
    else:
        veredito = "OK"

    return {"dia": dia, "commit": commit, "comando": comando, "jornada_da_medida": 2,
            "fps": fps, "latencia_s": latencia, "mbps": mbps,
            "resolucao": f"{largura}x{altura}" if (largura and altura) else "",
            "bruto_teorico_kbps": (round(bruto_kbps, 1) if bruto_kbps else None),
            "reducao_pct": reducao, "alvos": alvos,
            "fora_do_alvo": fora, "sem_medida": sem_medida, "veredito": veredito,
            "maquina": {"nome": platform.node(), "sistema": platform.platform(),
                        "processadores": os.cpu_count()},
            "ambiente": ambiente,
            "nota": ("a fonte e' crua (webcam/testsrc2): a reducao e' contra o bruto TEORICO "
                     "(ground/entrada.py), nao contra um fluxo comprimido de entrada")}


def resumo_geral(jornadas: list[dict], ambiente: dict, dia: str, commit: str = "",
                 qualidade_do_dia: dict | None = None) -> str:
    """O que o dono le' primeiro: veredito por jornada, os tres numeros do produto e o que ficou sem medida."""
    linhas = [f"# Smoke de ponta a ponta — {dia}", ""]
    if commit:
        linhas += [f"Commit: `{commit}`", ""]
    contagem: dict[str, int] = {}
    for j in jornadas:
        contagem[j["veredito"]] = contagem.get(j["veredito"], 0) + 1
    linhas += ["| Veredito | Jornadas |", "|---|---|"]
    for v in ("OK", "OK_COM_RESSALVAS", "NAO_MEDIDA", "FALHA"):
        if contagem.get(v):
            linhas.append(f"| {v} | {contagem[v]} |")
    linhas += ["", "| # | Jornada | Veredito | Falhou | Sem medida |", "|---|---|---|---|---|"]
    for j in jornadas:
        linhas.append(f"| J{j['jornada']} | {j['titulo']} | **{j['veredito']}** | "
                      f"{', '.join(j['falhas']) or '-'} | {', '.join(j['sem_medida']) or '-'} |")
    q = qualidade_do_dia or {}
    if q:
        linhas += ["", "## Os três números do produto (Fase 4)", "",
                   f"- **fps**: `{q.get('fps')}` (alvo ≥ {q.get('alvos', {}).get('fps')})",
                   f"- **latência**: `{q.get('latencia_s')}` s (alvo ≤ {q.get('alvos', {}).get('latencia_s')} s)",
                   f"- **redução de banda**: `{q.get('reducao_pct')}` % "
                   f"(alvo ≥ {q.get('alvos', {}).get('reducao_pct')} % · bruto teórico "
                   f"`{q.get('bruto_teorico_kbps')}` kbps · medido `{q.get('mbps')}` Mbps)",
                   f"- **veredito dos números**: **{q.get('veredito')}**"
                   + (f" — fora do alvo: {', '.join(q.get('fora_do_alvo') or [])}"
                      if q.get("fora_do_alvo") else "")]
    linhas += ["", "## Ambiente", "```json", json.dumps(ambiente, ensure_ascii=False, indent=2), "```"]
    return "\n".join(linhas) + "\n"
