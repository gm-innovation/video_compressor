#!/usr/bin/env python3
""""REFAZER VARREDURA" A PEDIDO DO ADMIN (Fase 3, 26/11/2026) — provado de ponta a ponta.

O dono (26/11/2026, verbatim): "nesta tela preciso tambem de um botao para refazer varredura, para que
caso tenha sido removida uma camera por engano, ou nao estao aparecendo cameras novas, o app de captura
precisa refazer a varredura das cameras, mas apenas inclui as que nao estao aparecendo, nao remonta tudo
pra nao perder as configuracoes ja feitas".

O que ja' existia: `varredura_do_bordo.varrer()` SEMPRE so' acrescentou. O que faltava era o GATILHO —
o terra NAO abre conexao para o bordo; o bordo OLHA. Por isso o pedido vira uma CHAVE da configuracao
publicada (`varrer`), que o bordo aplica sozinho (mesmo caminho de `alvo_kbps`/`rotulo`).

O que se prova aqui (com `ffmpeg` de mentira, sem camera de verdade — a bancada nao tem uma):

  1) `varrer` e' do lado da EMBARCACAO: pedir com `camera_id` e' RECUSADO (quem varre e' o PC);
  2) cada pedido INCREMENTA a versao (o bordo distingue pedido novo de pedido velho);
  3) aplicado no bordo, a varredura RODA e devolve o que fez (nao um "ok" vazio);
  4) uma camera NOVA do dispositivo entra (`cadastradas`);
  5) a camera que JA' existia e' so' ATUALIZADA, e o admin manda: `rotulo` dele, `alvo` e `ativo`
     ficam INTOCADOS ("nao remonta tudo pra nao perder as configuracoes ja feitas");
  6) camera que SUMIU do barramento NAO e' apagada nem desativada;
  7) repetir o pedido NAO duplica camera (a varredura e' idempotente).

    python tests/test-varredura-a-pedido.py
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
EMB = "bancada"

# Nomes SEM "radar/oleo/hdmi/capture": quero duas CAMERAS comuns (o radar nao entra no cadastro).
SEL_1 = r"@device_pnp_\\?\usb#vid_1bcf&pid_2c99#01#{65e8773d}"
SEL_2 = r"@device_pnp_\\?\usb#vid_0408&pid_4035#02#{65e8773d}"

CHAIN = r'''
import json, os, sys
sys.path.insert(0, "ground")
import api
import varredura_do_bordo as v

api.inicializar()   # banco limpo ganha o mesmo esquema da bancada (sem semear demo)

EMB = "bancada"
sel1, sel2 = sys.argv[1], sys.argv[2]
id1 = "cam-" + v._slug(sel1)          # o id que a varredura VAI gerar para o dispositivo 1
id2 = "cam-" + v._slug(sel2)

# ---- bancada: empresa, embarcacao, a camera do ADMIN (com nome/alvo/ativo dele) e a que SUMIU
with api.conexao() as c:
    c.execute("INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR (teste)')")
    c.execute("""INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome,imo,estado,radar_fonte)
                 VALUES (?,?,?,?,?,?)""", (EMB, "lecsor", "Bancada do teste", "", "em operacao", ""))
    c.execute("""INSERT OR REPLACE INTO cameras
                 (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                 VALUES (?,?,?,?,'',1,'','','dshow','',1500,'camera')""",
              (id1, EMB, "Equipamento OCM", id1))
    # o admin JA' nomeou esta camera em terra (a marca fica em config_local) — a varredura nao mexe
    c.execute("""INSERT OR REPLACE INTO config_local (camera_id,chave,valor,versao,atualizado_em)
                 VALUES (?,'rotulo',?,1,'2026-11-26T10:00:00-03:00')""", (id1, "Equipamento OCM"))
    # camera que o admin configurou e cujo dispositivo NAO esta' mais no barramento
    c.execute("""INSERT OR REPLACE INTO cameras
                 (id,embarcacao_id,rotulo,fluxo_id,local,ativo,ip,porta,protocolo,canal,alvo,tipo)
                 VALUES ('cam-que-sumiu',?,'Camera que sumiu','',1,1,'','','dshow','',800,'camera')""", (EMB,))

with api.conexao() as c:
    saida = {"id1": id1, "id2": id2,
             "antes": sorted(x["id"] for x in c.execute("SELECT id FROM cameras").fetchall())}

# ---- 1. o pedido e' da EMBARCACAO: com camera_id tem que ser RECUSADO
saida["recusa_com_camera"] = api.publicar_config(EMB, id1, "varrer", "2026-11-26T14:00:00-03:00")

# ---- 2/3. o admin pede DUAS vezes: a versao tem que SUBIR em cada pedido
saida["pedido_1"] = api.publicar_config(EMB, "", "varrer", "2026-11-26T14:00:00-03:00")
saida["pedido_2"] = api.publicar_config(EMB, "", "varrer", "2026-11-26T14:05:00-03:00")

# ---- 4. o BORDO aplica o pedido (e' o que o laco de ordens faz ao ver a chave nova)
saida["aplicar_1"] = api.aplicar_config_local("", "varrer", "2026-11-26T14:00:00-03:00")
saida["aplicar_2"] = api.aplicar_config_local("", "varrer", "2026-11-26T14:05:00-03:00")

# ---- estado final das cameras
with api.conexao() as c:
    saida["cameras"] = [dict(x) for x in c.execute(
        "SELECT id,rotulo,ativo,alvo FROM cameras ORDER BY id").fetchall()]
    saida["dispositivos"] = {x["camera_id"]: x["valor"] for x in
                             c.execute("SELECT camera_id,valor FROM config_local WHERE chave='dispositivo'")}
print(json.dumps(saida, ensure_ascii=False))
'''


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


def escrever_fake_ffmpeg(caminho: pathlib.Path, devices) -> None:
    linhas = ["@echo off"]
    for nome, tipo, seletor in devices:
        linhas.append(f'echo [dshow @ 000] "{nome}" ({tipo}) 1>&2')
        if seletor:
            linhas.append(f'echo [dshow @ 000]   Alternative name "{seletor}" 1>&2')
    linhas.append("exit /b 1")
    caminho.write_bytes(("\r\n".join(linhas) + "\r\n").encode("latin-1"))


def main() -> int:
    print("REFAZER VARREDURA A PEDIDO — 26/11/2026: o pedido viaja pela configuracao e o bordo SO' ACRESCENTA.\n")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-varredura-pedido-"))
    banco = tmp / "bordo.db"
    fake = tmp / "ffmpeg-falso.cmd"
    escrever_fake_ffmpeg(fake, [("Webcam de Boreste", "video", SEL_1),
                                ("Optica de Bombordo", "video", SEL_2)])
    script = tmp / "corrente.py"
    script.write_text(CHAIN, encoding="utf-8")

    env = dict(os.environ)
    env.update({"LECSOR_BANCO": str(banco), "LECSOR_EMBARCACAO": EMB, "LECSOR_FFMPEG": str(fake),
                "PYTHONIOENCODING": "utf-8"})
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_DESTINO_SRT", "LECSOR_TOKEN_INGESTAO"):
        env.pop(k, None)

    p = subprocess.run([sys.executable, str(script), SEL_1, SEL_2], cwd=str(RAIZ), env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if p.returncode != 0 or not (p.stdout or "").strip():
        print("  FALHA a corrente do bordo nao rodou")
        print("   stdout:", (p.stdout or "")[-1500:])
        print("   stderr:", (p.stderr or "")[-2500:])
        return 1
    try:
        d = json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        print(f"  FALHA nao entendi a saida da corrente ({e})\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
        return 1

    id1, id2 = d["id1"], d["id2"]
    notas = {x["id"]: x for x in d["cameras"]}

    # ---- 1. o pedido e' da embarcacao
    rec = d.get("recusa_com_camera") or {}
    checar("pedir 'varrer' com camera_id e' RECUSADO (a varredura olha a maquina toda)",
           bool(rec.get("erro")), f"{rec}")

    # ---- 2. a versao sobe a cada pedido (pedido novo != pedido velho)
    p1, p2 = d.get("pedido_1") or {}, d.get("pedido_2") or {}
    v1, v2 = p1.get("versao"), p2.get("versao")
    checar("o pedido publica a chave 'varrer' na embarcacao",
           bool(p1.get("ok")) and not p1.get("erro"), f"{p1}")
    checar("dois pedidos => DUAS versoes (o bordo ve o pedido novo)",
           bool(v1) and bool(v2) and v2 > v1, f"v1={v1} v2={v2}")

    # ---- 3. o bordo roda a varredura de verdade
    a1 = d.get("aplicar_1") or {}
    checar("o bordo aplica o pedido e a varredura RODA", bool(a1.get("ok")), f"{a1}")
    checar("e conta o que fez (1 nova + 1 ja' cadastrada)",
           len(a1.get("cadastradas") or []) == 1 and len(a1.get("atualizadas") or []) == 1,
           f"cadastradas={a1.get('cadastradas')} atualizadas={a1.get('atualizadas')}")

    # ---- 4. a camera NOVA entrou
    checar("a camera do dispositivo NOVO foi cadastrada", id2 in notas, f"{sorted(notas)}")
    checar("a nova nasceu na embarcacao do pacote e com o dispositivo gravado",
           bool(notas.get(id2)) and d["dispositivos"].get(id2) == SEL_2,
           f"dispositivo={d['dispositivos'].get(id2)}")

    # ---- 5. a camera do admin NAO perdeu configuracao
    c1 = notas.get(id1) or {}
    checar("a camera que ja' existia continua no ar (ativo=1)", str(c1.get("ativo")) == "1", f"{c1}")
    checar("o ALVO que o admin definiu (1500) nao foi tocado",
           str(c1.get("alvo")) == "1500", f"alvo={c1.get('alvo')!r}")
    checar("o NOME que o admin deu ('Equipamento OCM') nao foi sobrescrito",
           c1.get("rotulo") == "Equipamento OCM", f"rotulo={c1.get('rotulo')!r}")

    # ---- 6. o que sumiu NAO e' apagado
    sumiu = notas.get("cam-que-sumiu")
    checar("a camera que sumiu do barramento NAO foi apagada nem desativada",
           bool(sumiu) and str(sumiu.get("ativo")) == "1" and str(sumiu.get("alvo")) == "800",
           f"{sumiu}")

    # ---- 7. idempotente: o segundo pedido nao duplica camera
    a2 = d.get("aplicar_2") or {}
    checar("repetir a varredura nao cria camera de novo (0 novas, 2 atualizadas)",
           len(a2.get("cadastradas") or []) == 0 and len(a2.get("atualizadas") or []) == 2,
           f"cadastradas={a2.get('cadastradas')} atualizadas={a2.get('atualizadas')}")
    checar("nenhuma camera saiu do banco (o que havia antes + a nova que apareceu)",
           set(d["antes"]) | {id2} == set(notas), f"antes={d['antes']} depois={sorted(notas)}")

    print(f"   (bancada: {tmp})")
    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} verificacao(oes) — {falhas}")
        return 1
    print("TUDO VERDE: o pedido de varredura viaja, o bordo varre e SO' ACRESCENTA — nada do admin se perde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
