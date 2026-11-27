#!/usr/bin/env python3
"""UM PID SOZINHO NAO E' IDENTIDADE — o Windows recicla numero, e o app atirava no proprio gravador.

Incidente do dono (27/11/2026), no app de captura: *"4 blocos no hd e o gravador nao esta' de pe'"*.
Dois logs fecharam o caso por MEDICAO:

  * `D:\\gravador.log`: o ffmpeg abre a camera certo e morre 4x com `Exiting normally, received
    signal 15` (15:03:42/47/54/15:04:00) — ou seja, alguem de FORA matava o gravador;
  * medido nesta bancada: `os.kill(pid, 0)` no **Windows MATA** o processo (chama `TerminateProcess`)
    — nada de "so' pergunta se existe". Era o codigo do `_pid_vivo` do gravador: entao TODA checagem
    de vida (o supervisor, a tela, o `gravador_de_pe`) DERRUBAVA o laco que estava conferindo, e o
    `_subir_gravador` respondia "ja' estava de pe'".

    python tests/test-identidade-de-processo.py

Provas (nada do repositorio e' tocado; banco e HD vao para pasta temporaria):
  1) `processos.mesmo_processo` acerta a identidade: pid vivo com a hora de criacao certa = o NOSSO;
     hora de criacao mais nova que a esperada = pid RECICLADO (nao e' o nosso);
  2) `processos.vivo` NAO mata o processo que confere (o defeito do `os.kill(pid, 0)`);
  3) `gravacao_continua._pid_vivo` NAO mata (o laco do gravador sobrevive a propria checagem);
  4) `_laco_vivo()` so' diz "de pe'" com o par (pid, hora de criacao) — pid reciclado = NAO de pe';
  5) `_parar_gravador()` NAO mata um pid alheio que a linha diz ser nosso (reciclado) e para o nosso;
  6) `ingestao.parar()` NAO mata processo alheio (reciclado), NAO mata quem nao da' para provar, e
     PARA o dono certo quando a identidade bate (o caso do incidente);
  7) `_camera_em_uso`/`_linha_viva`: um pid reciclado NAO faz a camera parecer presa por outro.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
GROUND = RAIZ / "ground"
falhas: list[str] = []


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def espere_morte(p, segundos: float = 6.0) -> bool:
    fim = time.time() + segundos
    while time.time() < fim:
        if p.poll() is not None:
            return True
        time.sleep(0.15)
    return p.poll() is not None


def main() -> int:  # noqa: C901
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-identidade-"))
    hd = tmp / "hd"
    hd.mkdir(parents=True, exist_ok=True)
    os.environ["LECSOR_HD_DIR"] = str(hd)
    os.environ["LECSOR_BANCO"] = str(tmp / "pipeline.db")
    os.environ["LECSOR_SEM_AMBIENTE"] = "1"     # sem gravador de teste subindo sozinho
    sys.path.insert(0, str(GROUND))

    import processos            # noqa: PLC0415
    import gravacao_continua as g   # noqa: PLC0415
    import ingestao as ing      # noqa: PLC0415

    g.CONFIG_DO_HD = tmp / "config.json"
    g.RAIZ = tmp
    g._modulo_da_api = lambda: None
    ing._declarar_envio = lambda *a, **k: None   # sem rede: a prova e' sobre processo, nao sobre HTTP

    meu = os.getpid()
    criado_meu = processos.criado_em(meu)

    # 1) a IDENTIDADE
    exigir(processos.mesmo_processo(meu, criado_meu) is True,
           "mesmo_processo: o pid vivo com a hora de criacao certa e' o NOSSO")
    exigir(processos.mesmo_processo(meu, criado_meu - 7200) is False,
           "mesmo_processo: hora de criacao esperada 2h ANTES da real = pid reciclado (nao e' o nosso)")
    exigir(processos.mesmo_processo(meu, 0) is False,
           "mesmo_processo: sem hora de criacao (linha antiga) NAO da' para provar = nao e' o nosso")
    exigir(processos.mesmo_processo(999_999_999, time.time()) is False,
           "mesmo_processo: pid que nao existe = False")
    exigir(processos.reciclado(meu, criado_meu - 7200) is True,
           "reciclado: o pid existe mas a identidade nao bate (o caso medido no PC real)")

    # 2) `vivo` NAO mata — o defeito do `os.kill(pid, 0)` no Windows
    exigir(processos.vivo(meu) is True, "processos.vivo: o processo de agora esta' vivo")
    still = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        exigir(processos.vivo(still.pid) is True, "processos.vivo: processo recem-criado esta' vivo")
        time.sleep(0.6)
        exigir(still.poll() is None, "processos.vivo NAO mata o processo que conferiu (era o defeito)")
    finally:
        still.kill()

    # 3) `_pid_vivo` do gravador NAO mata
    exigir(g._pid_vivo(meu) is True, "gravacao_continua._pid_vivo: este processo esta' vivo")
    time.sleep(0.3)
    exigir(processos.vivo(meu) is True, "e o processo continua vivo depois da checagem (nao foi morto)")

    # 4) `_laco_vivo()` exige o PAR (pid, hora de criacao)
    g._arquivo_do_pid().parent.mkdir(parents=True, exist_ok=True)
    g._arquivo_do_pid().write_text(f"{meu}\n{criado_meu}", encoding="utf-8")
    exigir(g._laco_vivo() is True, "laco_vivo: (pid de agora + hora de criacao certa) = DE PE'")
    exigir(g.gravador_pid() == meu, "gravador_pid le' o pid da 1a linha")
    g._arquivo_do_pid().write_text(f"{meu}\n{criado_meu - 7200}", encoding="utf-8")
    exigir(g._laco_vivo() is False, "laco_vivo: mesmo pid, hora de criacao velha = RECICLADO = nao de pe'")
    exigir(g.gravador_de_pe() is False, "gravador_de_pe acompanha (a MEDIDA, nao o desejo)")

    # 5) `_parar_gravador()` nao mata pid alheio; mata o nosso
    alheio = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        g._arquivo_do_pid().write_text(f"{alheio.pid}\n{processos.criado_em(alheio.pid) - 7200}",
                                       encoding="utf-8")
        exigir(g._parar_gravador() is False, "_parar_gravador: pid reciclado -> devolve False")
        time.sleep(0.5)
        exigir(alheio.poll() is None, "e NAO mata o processo alheio (a correcao do incidente)")
        ours = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        g._arquivo_do_pid().write_text(f"{ours.pid}\n{processos.criado_em(ours.pid)}", encoding="utf-8")
        exigir(g._parar_gravador() is True, "_parar_gravador: identidade confere -> para o NOSSO")
        exigir(espere_morte(ours), "e o nosso processo morre de verdade")
    finally:
        for p in (alheio,):
            if p.poll() is None:
                p.kill()

    # 6) `ingestao.parar()` — o caminho exato que matava o gravador
    ing.garantir_schema()
    colunas = {r[1] for r in ing.conexao().execute("PRAGMA table_info(ingestoes)").fetchall()}
    exigir("pid_criado_em" in colunas, "o schema de `ingestoes` ganhou `pid_criado_em` (a identidade)")

    def _linha_de_teste(pid: int, criado) -> int:
        with ing.conexao() as c:
            cur = c.execute("""INSERT INTO ingestoes (fluxo_id, rotulo, fonte, tipo, estado, pid,
                                  pid_criado_em, srt_host, criado_em, atualizado_em)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (f"prova-{pid}-{time.time()}", "prova", "sintetica:teste", "sintetica",
                             "no_ar", pid, criado, "", ing.agora(), ing.agora()))
            return cur.lastrowid

    # 6a) pid reciclado: o dono ja' morreu e o numero virou de outro -> NAO mata
    alien = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        ident = _linha_de_teste(alien.pid, processos.criado_em(alien.pid) - 7200)
        r = ing.parar(ident)
        time.sleep(0.5)
        exigir(r.get("ok") is True, "parar(): marca a linha como parada (o estado nao depende do kill)")
        exigir(alien.poll() is None,
               "parar(): pid RECICLADO (dono ja' morreu, numero virou de outro) -> NAO mata o alheio")
        # 6b) linha antiga sem hora de criacao -> tambem NAO mata (nao da' para provar)
        ident2 = _linha_de_teste(alien.pid, None)
        ing.parar(ident2)
        time.sleep(0.4)
        exigir(alien.poll() is None, "parar(): linha antiga (sem hora de criacao) -> NAO mata (nao prova)")
    finally:
        if alien.poll() is None:
            alien.kill()

    # 6c) identidade certa -> PARA o dono (o caso que o produto PRECISA acertar)
    dono = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    ident3 = _linha_de_teste(dono.pid, processos.criado_em(dono.pid))
    exigir(ing.parar(ident3).get("ok") is True, "parar(): com a identidade certa, executa")
    exigir(espere_morte(dono), "e o dono CERTO e' parado (o produto nao ficou sem parar ninguem)")
    if dono.poll() is None:
        dono.kill()

    # 7) pid reciclado NAO faz a camera parecer presa por outro
    cam = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with ing.conexao() as c:
            c.execute("""UPDATE ingestoes SET tipo='camera', estado='no_ar', fonte='dshow:Prova Identidade',
                             pid=?, pid_criado_em=?, atualizado_em=? WHERE id=?""",
                      (cam.pid, processos.criado_em(cam.pid) - 7200, ing.agora(), ident3))
        exigir(ing._camera_em_uso("Prova Identidade") is None,
               "_camera_em_uso: pid reciclado -> camera LIVRE (nao fica presa por outro processo)")
        with ing.conexao() as c:
            c.execute("UPDATE ingestoes SET pid_criado_em=?, atualizado_em=? WHERE id=?",
                      (processos.criado_em(cam.pid), ing.agora(), ident3))
        exigir((ing._camera_em_uso("Prova Identidade") or {}).get("id") == ident3,
               "_camera_em_uso: identidade certa + envio vivo = camera EM USO (nao solta sem razao)")
    finally:
        if cam.poll() is None:
            cam.kill()

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} exigencia(s)")
        for f in falhas:
            print("  - " + f)
        return 1
    print("TUDO OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
