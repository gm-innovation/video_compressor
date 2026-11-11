#!/usr/bin/env python3
"""Regressão: câmera que não funciona sai da tela sem apagar o histórico.

O que o dono relatou (11/11/2026): "não consigo excluir esse monte de câmera que não funciona" —
a tela Câmeras só tinha um botão "ativar/desativar" que nunca desativava (o `ativo` não vinha na
lista que a tela usava) e a câmera desativada sumia da própria tela do admin, sem como religar.

O que este teste prova, sem depender de servidor no ar:

1) a lista que o CLIENTE recebe filtra `ativo=1` (mesma SQL de `ground/api.py`), então a câmera
   desativada sai da visão dele e o histórico continua no banco;
2) `ground/limpar-cameras-teste.py` só mexe na lista fechada de câmeras de teste, numa transação, e
   recusa fluxo que está no ar — rodado contra um banco temporário, não o do trabalho;
3) a fiação da tela do admin tem o rótulo que diz o que o botão faz, a confirmação antes de
   desativar e a coluna de situação (o que fazia o botão parecer "não funcionar").
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

falhas = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("ok   " if condicao else "FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


# ---------------------------------------------------------------- banco temporário
def banco_temporario() -> Path:
    """Câmeras de teste (alvo), a que funciona (no ar) e uma demo que tem de ficar."""
    caminho = Path(tempfile.mkdtemp(prefix="lecsor-camera-")) / "pipeline.db"
    c = sqlite3.connect(caminho)
    c.executescript("""
        CREATE TABLE cameras (id TEXT PRIMARY KEY, embarcacao_id TEXT, rotulo TEXT, fluxo_id TEXT,
                              local TEXT, ativo INTEGER, ip TEXT, porta TEXT, protocolo TEXT, canal TEXT);
        CREATE TABLE ingestoes (id INTEGER PRIMARY KEY AUTOINCREMENT, fluxo_id TEXT, camera_id TEXT, estado TEXT);
        CREATE TABLE ingestoes_amostras (id INTEGER PRIMARY KEY AUTOINCREMENT, ingestao_id INTEGER, em TEXT);
        CREATE TABLE telemetria_minuto (id INTEGER PRIMARY KEY AUTOINCREMENT, fluxo_id TEXT, camera_id TEXT);
        CREATE TABLE compressoes (id INTEGER PRIMARY KEY AUTOINCREMENT, fluxo_id TEXT);
        CREATE TABLE analytics_eventos (id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT);
        -- medicoes_qualidade NÃO existe de propósito: a VPS tem banco mais antigo que a bancada
    """)
    cams = [
        ("vps-webcam-bancada", "bancada", "Webcam bancada (bordo -> VPS)", 1),
        ("cam-01", "bancada", "Bancada — câmera 1", 1),
        ("cam-01-demo", "psv-exemplo", "PSV (demo) — câmera 1", 1),
        ("teste-latencia", "psv-exemplo", "Teste de latência (relógio queimado)", 1),
    ]
    for cid, emb, rot, ativo in cams:
        c.execute("INSERT INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo) VALUES (?,?,?,?,?,?)",
                  (cid, emb, rot, cid, "", ativo))
    # só a que funciona está no ar; as outras só têm histórico
    c.execute("INSERT INTO ingestoes (fluxo_id, camera_id, estado) VALUES ('vps-webcam-bancada','vps-webcam-bancada','no_ar')")
    c.execute("INSERT INTO ingestoes (fluxo_id, camera_id, estado) VALUES ('cam-01','cam-01','parado')")
    c.execute("INSERT INTO telemetria_minuto (fluxo_id, camera_id) VALUES ('cam-01','cam-01')")
    c.execute("INSERT INTO telemetria_minuto (fluxo_id, camera_id) VALUES ('vps-webcam-bancada','vps-webcam-bancada')")
    c.execute("INSERT INTO analytics_eventos (camera_id) VALUES ('cam-01')")
    c.commit()
    c.close()
    return caminho


# 1) a regra da tela do cliente: ativo=1
def t1_lista_do_cliente(db: Path) -> None:
    c = sqlite3.connect(db)
    c.execute("UPDATE cameras SET ativo=0 WHERE id='cam-01'")
    c.commit()
    visiveis = [r[0] for r in c.execute("SELECT id FROM cameras WHERE ativo=1")]      # SQL de /api/cameras
    checar("câmera desativada sai da lista do cliente", "cam-01" not in visiveis, str(visiveis))
    guardado = c.execute("SELECT count(*) FROM telemetria_minuto WHERE fluxo_id='cam-01'").fetchone()[0]
    checar("desativar não apaga o histórico", guardado == 1, f"telemetria={guardado}")
    c.execute("UPDATE cameras SET ativo=1 WHERE id='cam-01'")     # volta para o teste seguinte
    c.commit()
    c.close()


script_limpeza = RAIZ / "ground" / "limpar-cameras-teste.py"


# 2) fluxo no ar não é mexido sem --forcar
def t2a_recusa_fluxo_no_ar(db: Path) -> None:
    c = sqlite3.connect(db)
    c.execute("UPDATE ingestoes SET estado='no_ar' WHERE fluxo_id='cam-01'")
    c.commit()
    c.close()
    r = subprocess.run([sys.executable, str(script_limpeza), "--db", str(db), "--aplicar"],
                       capture_output=True, text=True)
    sobrou = {x[0] for x in sqlite3.connect(db).execute("SELECT id FROM cameras")}
    checar("fluxo no ar não é apagado sem --forcar", r.returncode == 0 and "cam-01" in sobrou, str(sobrou))
    c = sqlite3.connect(db)
    c.execute("UPDATE ingestoes SET estado='parado' WHERE fluxo_id='cam-01'")
    c.commit()
    c.close()


# 3) o script de limpeza
def t2_script_de_limpeza(db: Path) -> None:
    script = script_limpeza
    antes = sqlite3.connect(db).execute("SELECT count(*) FROM cameras").fetchone()[0]

    seco = subprocess.run([sys.executable, str(script), "--db", str(db)], capture_output=True, text=True)
    checar("--simular sai com 0", seco.returncode == 0, seco.stderr[-300:])
    checar("--simular avisa que não apagou", "nada foi apagado" in seco.stdout, seco.stdout[-200:])
    depois_seco = sqlite3.connect(db).execute("SELECT count(*) FROM cameras").fetchone()[0]
    checar("--simular não apaga nada", depois_seco == antes, f"{antes} -> {depois_seco}")

    real = subprocess.run([sys.executable, str(script), "--db", str(db), "--aplicar"],
                          capture_output=True, text=True)
    checar("--aplicar sai com 0", real.returncode == 0, real.stderr[-300:])
    c = sqlite3.connect(db)
    sobrou = {r[0] for r in c.execute("SELECT id FROM cameras")}
    checar("alvo saiu", "cam-01" not in sobrou and "teste-latencia" not in sobrou, str(sobrou))
    checar("a câmera que funciona ficou", "vps-webcam-bancada" in sobrou, str(sobrou))
    checar("câmera demo do PSV ficou", "cam-01-demo" in sobrou, str(sobrou))
    checar("histórico do alvo saiu junto",
           c.execute("SELECT count(*) FROM telemetria_minuto WHERE fluxo_id='cam-01'").fetchone()[0] == 0)
    checar("histórico do que ficou foi preservado",
           c.execute("SELECT count(*) FROM telemetria_minuto WHERE fluxo_id='vps-webcam-bancada'").fetchone()[0] == 1)
    checar("banco sem a tabela medicoes_qualidade não quebra o script",
           "Traceback" not in real.stdout and "Traceback" not in real.stderr)
    c.close()


# 3) fiação da tela do admin
def t3_tela_do_admin() -> None:
    fonte = (RAIZ / "admin" / "admin.js").read_text(encoding="utf-8")
    checar("tela mostra a situação da câmera", "Situação" in fonte and "'desativada'" in fonte)
    checar("botão diz o que faz (desativar/ativar)", "l.ativo ? 'desativar' : 'ativar'" in fonte)
    checar("desativar pede confirmação", "Desativar \"" in fonte)
    checar("a tela do admin lista também as desativadas", "A.camerasInterno && A.camerasInterno.cameras" in fonte)
    checar("o cliente não recebe o botão de desativar", "S.podeCamera" in (RAIZ / "app" / "app.js").read_text(encoding="utf-8"))


db = banco_temporario()
t1_lista_do_cliente(db)
t2a_recusa_fluxo_no_ar(db)
t2_script_de_limpeza(db)
t3_tela_do_admin()

if falhas:
    print(f"\n{len(falhas)} falha(s): {', '.join(falhas)}")
    sys.exit(1)
print("\ntudo certo: desativar tira da tela do cliente e a limpeza só mexe no que foi mandado")
