#!/usr/bin/env python3
"""Prova o aplicativo Windows (Electron): as três superfícies abrem e a interface não tem Node.

Roda o app em modo --verificar (abre as janelas, confere e sai) contra a API local e checa o que
o próprio app relata. Uso: python tests/e2e-desktop.py [url-do-lado-terra]
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DESKTOP = RAIZ / "desktop"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
falhas: list[str] = []


def checar(nome, condicao, detalhe=""):
    print(("  OK   " if condicao else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


def main() -> int:
    if not (DESKTOP / "node_modules" / "electron").exists():
        print("instale o aplicativo antes: cd desktop && npm install"); return 2
    config = DESKTOP / "config.json"
    antigo = config.read_text(encoding="utf-8")
    config.write_text(antigo.replace("http://127.0.0.1:8765", BASE), encoding="utf-8")
    try:
        env = dict(os.environ)
        senha = env.get("LECSOR_SENHA_DEMO", "")
        if senha:
            # a credencial entra pelo ambiente do teste: o aplicativo nao guarda senha
            env["LECSOR_VERIFICAR_ENTRAR"] = f"cliente@armador-demo.test:{senha}"
        r = subprocess.run(["npx", "electron", ".", "--verificar"], cwd=str(DESKTOP), capture_output=True,
                           text=True, timeout=240, env=env, shell=True)
        saida = (r.stdout or "") + (r.stderr or "")
        bloco = saida.split("VERIFICACAO", 1)[1] if "VERIFICACAO" in saida else ""
        linhas = [l for l in bloco.splitlines() if "\t" in l]
        print("  app respondeu:", bool(linhas))
        por_nome = {}
        for l in linhas:
            campos = l.split("\t")
            dados = {"url": campos[1] if len(campos) > 1 else ""}
            dados.update(dict(c.split("=", 1) for c in campos[2:] if "=" in c))
            por_nome[campos[0]] = dados
        checar("o aplicativo abre as três superfícies", set(por_nome) >= {"cliente", "admin", "bancada"},
               ", ".join(sorted(por_nome)))
        checar("a janela do cliente carrega /app", por_nome.get("cliente", {}).get("url", "").endswith("/app"),
               por_nome.get("cliente", {}).get("url", ""))
        checar("a janela do admin carrega /admin", por_nome.get("admin", {}).get("url", "").endswith("/admin"),
               por_nome.get("admin", {}).get("url", ""))
        checar("a janela da bancada carrega /", por_nome.get("bancada", {}).get("url", "").endswith("/"),
               por_nome.get("bancada", {}).get("url", ""))
        checar("as janelas ficaram visíveis", all(v.get("visivel") == "true" for v in por_nome.values()),
               str({k: v.get("visivel") for k, v in por_nome.items()}))
        checar("a página carregou de verdade (tem título)", all(v.get("titulo") for v in por_nome.values()),
               str({k: v.get("titulo") for k, v in por_nome.items()}))
        import json
        provas = {k: json.loads(v["prova"]) for k, v in por_nome.items() if v.get("prova", "").startswith("{")}
        vidros = {k: (v.get("video_janelas"), v.get("video_tocando")) for k, v in provas.items() if "video_janelas" in v}
        if senha:
            checar("o cliente vê as câmeras ao vivo DENTRO do aplicativo",
                   any((t_ or 0) >= 1 for _, t_ in vidros.values()),
                   f"janelas/tocando por superfície: {vidros}")
        checar("nenhuma janela tem Node na interface (require/process ausentes)",
               all(p["node"] == "undefined" and p["processo"] == "undefined" for p in provas.values()), str(provas))
        checar("a interface não recebe o endereço do lado terra por variável (ponte devolve nulo sem LECSOR_BASE)",
               all(p["endereco"] is None for p in provas.values()), str({k: p["endereco"] for k, p in provas.items()}))
    finally:
        config.write_text(antigo, encoding="utf-8")
    print("\nRESULTADO:", "tudo passou" if not falhas else f"{len(falhas)} falha(s): " + "; ".join(falhas))
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(main())
