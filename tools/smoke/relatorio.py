#!/usr/bin/env python3
"""Relatorio do smoke: uma jornada, uma lista de checagens, um veredito com numero.

Regra dura (plano de 23/11/2026): *sem medida, a jornada e' "NAO MEDIDA" — nunca "OK"*. Uma checagem
que nao pode ser feita entra como `medido=False` e aparece no relatorio com o motivo; o veredito so'
e' OK quando TODAS as checagens passaram com medida.

Vereditos: `OK` | `OK_COM_RESSALVAS` (passou tudo, mas algo ficou sem medida) | `FALHA` | `NAO_MEDIDA`.
"""
from __future__ import annotations

import json
import pathlib
import time


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


def resumo_geral(jornadas: list[dict], ambiente: dict, dia: str, commit: str = "") -> str:
    """O que o dono le' primeiro: veredito por jornada e o que ficou sem medida."""
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
    linhas += ["", "## Ambiente", "```json", json.dumps(ambiente, ensure_ascii=False, indent=2), "```"]
    return "\n".join(linhas) + "\n"
