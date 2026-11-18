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

# o menu "Subir o servidor local" libera a CAPTURA sem trocar o endereco da tela (dono, 18/11/2026:
# "o admin tem acesso a tudo, ja deve ter por padrao todas as autorizacoes"). Antes este item trocava a
# base para o loopback e o login caia num banco local vazio -> "e-mail ou senha invalidos".
main = (RAIZ / "desktop" / "main.js").read_text(encoding="utf-8")
checar("Subir o servidor local nesta maquina" in main and "config.capturaLocal = true" in main
       and "config.base = local" not in main,
       "subir o servidor local libera a captura SEM trocar o endereco da tela (login segue no lado terra)")
checar("config.destinoSrt = (PAPEIS[PAPEL] || {}).destinoSrt || PADRAO.destinoSrt" in main,
       "subir o servidor local tambem preenche o destino do repasse quando esta vazio")

# o pacote TEM que levar o módulo novo, senão o app quebra ao abrir
pkg = json.loads((RAIZ / "desktop" / "package.json").read_text(encoding="utf-8"))
checar("configuracao.js" in pkg["build"]["files"], "configuracao.js entra no pacote (build.files)")

# --- o APLICATIVO UNICO nasce com a captura liberada e sem trocar o endereco (dono, 18/11/2026) ----
print()
print("5) aplicativo unico: captura liberada de fabrica, login sempre no lado terra")
PAPEIS_UNICO = dict(PAPEIS)
PAPEIS_UNICO["unico"] = {"base": "http://187.127.60.250:8085", "destinoSrt": "187.127.60.250:8890",
                         "servidorLocal": {"ligado": True, "portaApi": 8765},
                         "capturaLocal": True, "abrirComWindows": False}

CASOS_UNICO = [
    ("unico", None, "http://187.127.60.250:8085", True, True, False,
     "instalacao limpa do app unico ja nasce com captura liberada e o login no lado terra"),
    ("unico", {"papel": "unico", "base": "http://127.0.0.1:8765",
               "servidorLocal": {"ligado": False, "portaApi": 8765}, "capturaLocal": False,
               "ajuste_manual": False},
     "http://187.127.60.250:8085", True, True, True,
     "O CASO DO DONO: config velho (base loopback, capturaLocal false, servidor desligado) e corrigido "
     "sozinho no boot"),
    ("unico", {"papel": "unico", "base": "http://127.0.0.1:8765",
               "servidorLocal": {"ligado": True, "portaApi": 8765}, "capturaLocal": False},
     "http://187.127.60.250:8085", True, True, True,
     "mesmo com o servidor local ligado, o app unico NAO joga a tela no loopback (era o login caindo "
     "no banco local vazio)"),
]
for i, (papel, usuario, base_esp, cap_esp, lig_esp, corr_esp, prova) in enumerate(CASOS_UNICO, 1):
    js = f"""
const {{resolver}} = require({json.dumps(str(RAIZ / 'desktop' / 'configuracao.js'))});
const r = resolver({json.dumps(PADRAO)}, {json.dumps(PAPEIS_UNICO)}, {json.dumps(papel)}, {json.dumps(usuario)});
console.log(JSON.stringify({{base: r.config.base, capturaLocal: !!r.config.capturaLocal,
  ligado: !!r.config.servidorLocal.ligado, corrigido: !!r.corrigido}}));
"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout.strip().splitlines()[-1])
    checar(d["base"] == base_esp and d["capturaLocal"] is cap_esp and d["ligado"] is lig_esp
           and d["corrigido"] is corr_esp,
           f"unico {i}: {prova} (base={d['base']}, captura={d['capturaLocal']}, ligado={d['ligado']}, "
           f"corrigido={d['corrigido']})")

# o papel unico do pacote de VERDADE tem que declarar a captura (senao a maquina de captura nao captura)
papeis_reais = json.loads((RAIZ / "desktop" / "papeis.json").read_text(encoding="utf-8"))
unico = papeis_reais.get("unico", {})
checar(unico.get("capturaLocal") is True and (unico.get("servidorLocal") or {}).get("ligado") is True,
       f"o papel `unico` de fabrica libera a captura e sobe o servidor local ({unico.get('capturaLocal')}, "
       f"{(unico.get('servidorLocal') or {}).get('ligado')})")
checar("127.0.0.1" not in str(unico.get("base", "")) and "localhost" not in str(unico.get("base", "")),
       f"e o endereco de fabrica do `unico` e' o lado terra, nao o loopback ({unico.get('base')})")
js = f"""
const {{resolver}} = require({json.dumps(str(RAIZ / 'desktop' / 'configuracao.js'))});
const r = resolver({json.dumps(PADRAO)}, {json.dumps(papeis_reais)}, "unico",
  {{papel: "unico", base: "http://127.0.0.1:8765", capturaLocal: false,
    servidorLocal: {{ligado: false, portaApi: 8765}}, ajuste_manual: false}});
console.log(JSON.stringify({{base: r.config.base, capturaLocal: !!r.config.capturaLocal}}));
"""
r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
d = json.loads(r.stdout.strip().splitlines()[-1])
checar(d["base"] == unico.get("base") and d["capturaLocal"] is True,
       f"com o papeis.json do pacote, a config velha volta para o lado terra com a captura liberada "
       f"(base={d['base']}, captura={d['capturaLocal']})")

print()
print("6) de onde vem a ENTRADA (dono, 18/11/2026: o app se organiza pelo usuário)")
print()
CASOS_ENTRADA = [
    # config de captura local ligada, servidor local ligado
    ({"base": "http://187.127.60.250:8085", "capturaLocal": True,
      "servidorLocal": {"ligado": True, "portaApi": 8765}},
     {"temUsuarios": False, "ladoTerraResponde": True}, "http://187.127.60.250:8085",
     "servidor local VAZIO + lado terra respondendo: a entrada vem do lado terra (era o login caindo "
     "no banco local vazio)"),
    ({"base": "http://187.127.60.250:8085", "capturaLocal": True,
      "servidorLocal": {"ligado": True, "portaApi": 8765}},
     {"temUsuarios": False, "ladoTerraResponde": False}, "http://127.0.0.1:8765",
     "bordo SEM internet (ninguem responde): a entrada continua a do servidor local, onde o primeiro "
     "acesso e' criado na propria maquina"),
    ({"base": "http://187.127.60.250:8085", "capturaLocal": True,
      "servidorLocal": {"ligado": True, "portaApi": 8765}},
     {"temUsuarios": True, "ladoTerraResponde": True}, "http://127.0.0.1:8765",
     "servidor local com cadastro proprio: a entrada e' a dele"),
    ({"base": "http://187.127.60.250:8085", "capturaLocal": False,
      "servidorLocal": {"ligado": False, "portaApi": 8765}},
     {"temUsuarios": None, "ladoTerraResponde": True}, "http://187.127.60.250:8085",
     "sem captura nesta maquina: a entrada e' a do lado terra, como as outras telas"),
]
for i, (cfg, medido, esperado, prova) in enumerate(CASOS_ENTRADA, 1):
    js = f"""
const {{enderecoDaEntrada}} = require({json.dumps(str(RAIZ / 'desktop' / 'configuracao.js'))});
console.log(JSON.stringify(enderecoDaEntrada({json.dumps(cfg)}, {json.dumps(medido)})));
"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout.strip().splitlines()[-1])
    checar(d == esperado, f"entrada {i}: {prova} (endereco={d})")

checar("await definirEnderecoDaEntrada();" in main and "for (const nome of config.abrirAoIniciar) abrir(nome);" in main
       and main.index("await definirEnderecoDaEntrada();") < main.index("for (const nome of config.abrirAoIniciar) abrir(nome);"),
       "main.js decide o endereco da entrada ANTES de abrir as janelas")
checar("await definirEnderecoDaEntrada();" in main.split("async function recarregarTelas")[1][:200],
       "e volta a decidir quando as telas sao recarregadas (subir/desligar a captura muda o lado)")

print()
print("7) as telas de captura so' abrem depois do servidor local responder (dono, 18/11/2026)")
print()
checar("await esperarServidorLocal();" in main and
       main.index("await esperarServidorLocal();") < main.index("for (const nome of config.abrirAoIniciar) abrir(nome);"),
       "main.js espera o servidor local antes de abrir as janelas")
checar("await esperarServidorLocal();" in main.split("async function recarregarTelas")[1][:300],
       "e espera de novo quando as telas sao recarregadas (subir/desligar a captura muda o lado)")
checar("async function esperarServidorLocal(tentativas = 12, intervaloMs = 1000)" in main
       and "return null;" in main.split("async function esperarServidorLocal")[1][:600],
       "a espera desiste em vez de travar a abertura para sempre")

print()
if falhas:
    print(f"FALHOU — endereço do app: {len(falhas)} verificação(ões)")
    sys.exit(1)
print("OK — endereço do app vem do papel do instalador; config velho de loopback não manda mais")
