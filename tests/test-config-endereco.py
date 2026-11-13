#!/usr/bin/env python3
"""Endereço do app tem que sair do PAPEL do instalador, não de um config velho em %APPDATA%.

Por que existe: numa instalação nova do LECSOR Admin a tela abriu em `http://127.0.0.1:8765/admin`
e disse "o servidor do lado terra não respondeu (conexão recusada)". O `config.json` do pacote está
certo (`http://187.127.60.250:8085`); o endereço errado veio do config que a versão anterior gravou
em `%APPDATA%\\<app>\\config.json` com o MESMO `papel`, caso em que o guard de papel não corrigia
nada. Agora um endereço de loopback num papel que NÃO sobe servidor local (nada escuta nessa porta)
volta para o de fábrica do papel.

Roda a lógica REAL (`desktop/configuracao.js`), a mesma que o `main.js` usa, com node.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas: list[str] = []


def checar(cond: bool, texto: str) -> None:
    print(("  ok    — " if cond else "  FALHOU— ") + texto)
    if not cond:
        falhas.append(texto)


PADRAO = {"base": "http://187.127.60.250:8085", "destinoSrt": "187.127.60.250:8890",
          "abrirAoIniciar": ["cliente", "admin", "bancada"], "modoQuiosque": False,
          "servidorLocal": {"ligado": False, "repo": "", "portaApi": 8765}}
PAPEIS = {
    "captura": {"base": "http://127.0.0.1:8765", "destinoSrt": "187.127.60.250:8890",
                "servidorLocal": {"ligado": True, "portaApi": 8765}, "abrirComWindows": True},
    "terra": {"base": "http://187.127.60.250:8085", "destinoSrt": "",
              "servidorLocal": {"ligado": False, "portaApi": 8765}, "abrirComWindows": False},
    "bancada": {"base": "http://187.127.60.250:8085", "destinoSrt": "",
                "servidorLocal": {"ligado": False, "portaApi": 8765}, "abrirComWindows": False},
}

CASOS = [
    # (papel, config do usuário, base esperada, corrigido esperado, herdado esperado, o que prova)
    ("terra", None, "http://187.127.60.250:8085", False, False,
     "instalação limpa do lado terra nasce no servidor da Lecsor"),
    ("terra", {"papel": "terra", "base": "http://127.0.0.1:8765",
               "servidorLocal": {"ligado": False, "portaApi": 8765}, "ajuste_manual": False},
     "http://187.127.60.250:8085", True, False,
     "O CASO DO DONO: config velho com o mesmo papel e base 127.0.0.1 é corrigido"),
    ("bancada", {"papel": "bancada", "base": "http://localhost:8765", "servidorLocal": {"ligado": False}},
     "http://187.127.60.250:8085", True, False,
     "loopback por 'localhost' também é corrigido"),
    ("terra", {"papel": "terra", "base": "http://10.0.0.9:8085", "ajuste_manual": True,
               "servidorLocal": {"ligado": False}},
     "http://10.0.0.9:8085", False, False,
     "endereço remoto escolhido na mão continua valendo"),
    ("captura", {"papel": "captura", "base": "http://127.0.0.1:8765",
                 "servidorLocal": {"ligado": True, "portaApi": 8765}},
     "http://127.0.0.1:8765", False, False,
     "no PC de captura o loopback é o endereço CERTO (o servidor local dele sobe)"),
    ("captura", {"papel": "terra", "base": "http://187.127.60.250:8085",
                 "servidorLocal": {"ligado": False, "portaApi": 8765}},
     "http://127.0.0.1:8765", False, True,
     "config de OUTRO papel é herdado: o captura volta para si mesmo, com servidor local"),
    ("terra", {"papel": "terra", "base": "http://127.0.0.10:8765", "ajuste_manual": True,
               "servidorLocal": {"ligado": False}},
     "http://127.0.0.10:8765", False, False,
     "127.0.0.10 não é loopback (não casa o prefixo por engano)"),
]

for i, (papel, usuario, base_esp, corr_esp, herd_esp, prova) in enumerate(CASOS, 1):
    js = f"""
const {{resolver}} = require({json.dumps(str(RAIZ / 'desktop' / 'configuracao.js'))});
const r = resolver({json.dumps(PADRAO)}, {json.dumps(PAPEIS)}, {json.dumps(papel)}, {json.dumps(usuario)});
console.log(JSON.stringify({{base: r.config.base, corrigido: !!r.corrigido, herdado: !!r.herdado,
  ligado: !!r.config.servidorLocal.ligado, destinoSrt: r.config.destinoSrt,
  modoQuiosque: !!r.config.modoQuiosque, abrirAoIniciar: r.config.abrirAoIniciar}}));
"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        print(f"  FALHOU— caso {i} não respondeu: {(r.stdout or '')[-200:]} {(r.stderr or '')[-200:]}")
        falhas.append(f"caso {i}")
        continue
    checar(d["base"] == base_esp and d["corrigido"] is corr_esp and d["herdado"] is herd_esp,
           f"caso {i}: {prova} (base={d['base']}, corrigido={d['corrigido']}, herdado={d['herdado']})")
    checar(d["abrirAoIniciar"] == PADRAO["abrirAoIniciar"] and d["modoQuiosque"] is False,
           f"caso {i}: abrirAoIniciar/modoQuiosque vêm do padrão")

# o papel do lado terra não inventa destino SRT nem "abrir com o Windows"
r = subprocess.run(["node", "-e", f"""
const {{resolver}} = require({json.dumps(str(RAIZ / 'desktop' / 'configuracao.js'))});
const r = resolver({json.dumps(PADRAO)}, {json.dumps(PAPEIS)}, "terra", null);
console.log(JSON.stringify({{destinoSrt: r.config.destinoSrt, abrir: !!r.config.abrirComWindows, ligado: !!r.config.servidorLocal.ligado}}));
"""], capture_output=True, text=True, timeout=60)
d = json.loads(r.stdout.strip().splitlines()[-1])
checar(d["destinoSrt"] == "" and d["abrir"] is False and d["ligado"] is False,
       "lado terra: sem destino SRT, sem autostart e sem servidor local (só mostra tela)")

# --- servidor local LIGADO nesta máquina: o app fala com ele -------------------------------
print()
print("4) servidor local ligado nesta maquina")
CASOS_LOCAL = [
    ("terra", {"papel": "terra", "base": "http://187.127.60.250:8085",
               "servidorLocal": {"ligado": True, "portaApi": 8765}},
     "http://127.0.0.1:8765", "187.127.60.250:8890",
     "O CASO DO DONO: ligou o servidor local numa instalacao apontada para o lado terra -> a tela "
     "passa a vir do servidor local (com as cameras desta maquina) e o repasse fica configurado"),
    ("terra", {"papel": "terra", "base": "http://187.127.60.250:8085", "destinoSrt": "",
               "servidorLocal": {"ligado": True, "portaApi": 8765}},
     "http://127.0.0.1:8765", "",
     "destino apagado DE PROPOSITO continua vazio (o repasse nao volta sozinho)"),
    ("terra", {"papel": "terra", "base": "http://187.127.60.250:8085",
               "servidorLocal": {"ligado": False, "portaApi": 8765}},
     "http://187.127.60.250:8085", "",
     "servidor local desligado: lado terra continua sendo o endereco, sem inventar repasse"),
]
for i, (papel, usuario, base_esp, destino_esp, prova) in enumerate(CASOS_LOCAL, 1):
    js = f"""
const {{resolver}} = require({json.dumps(str(RAIZ / 'desktop' / 'configuracao.js'))});
const r = resolver({json.dumps(PADRAO)}, {json.dumps(PAPEIS)}, {json.dumps(papel)}, {json.dumps(usuario)});
console.log(JSON.stringify({{base: r.config.base, destinoSrt: r.config.destinoSrt, corrigido: !!r.corrigido}}));
"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout.strip().splitlines()[-1])
    checar(d["base"] == base_esp and d["destinoSrt"] == destino_esp,
           f"local {i}: {prova} (base={d['base']}, destino={d['destinoSrt']!r})")

# o menu "Subir servidor nesta maquina" tem que reapontar a tela (nao basta subir o processo)
main = (RAIZ / "desktop" / "main.js").read_text(encoding="utf-8")
checar("Subir servidor nesta maquina" in main and "config.base = local" in main,
       "subir o servidor local reaponta a tela para ele (o menu nao so sobe o processo)")
checar("config.destinoSrt = (PAPEIS[PAPEL] || {}).destinoSrt || PADRAO.destinoSrt" in main,
       "subir o servidor local tambem preenche o destino do repasse quando esta vazio")

# o pacote TEM que levar o módulo novo, senão o app quebra ao abrir
pkg = json.loads((RAIZ / "desktop" / "package.json").read_text(encoding="utf-8"))
checar("configuracao.js" in pkg["build"]["files"], "configuracao.js entra no pacote (build.files)")

print()
if falhas:
    print(f"FALHOU — endereço do app: {len(falhas)} verificação(ões)")
    sys.exit(1)
print("OK — endereço do app vem do papel do instalador; config velho de loopback não manda mais")
