"""A MESMA cena em 3 alvos, com SSIM e nitidez de cada um — o numero que responde "esta perdendo
qualidade?".

O dono disse "a cam02 esta perdendo bastante qualidade" e nao tinha como comparar: nao existia
medicao da MESMA cena em alvos diferentes. Aqui a fonte abre UMA vez e sai em 4 ramos: 3 alvos + um
ramo SEM PERDA (a referencia do SSIM). O resultado fica em clipes + CSV, para o dono ver lado a lado
e apontar qual alvo "ainda serve" — o numero sozinho nao decide pelo olho dele.

    python tests/test-comparacao-3-alvos.py
"""
import csv
import pathlib
import sqlite3
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ground"))


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-alvos-"))
    import os
    os.environ["LECSOR_BANCO"] = str(tmp / "pipeline.db")
    os.environ["PYTHONIOENCODING"] = "utf-8"

    con = sqlite3.connect(os.environ["LECSOR_BANCO"])
    esquemas = [RAIZ / "db" / "schema.sql"] + sorted(
        p for p in (RAIZ / "db").glob("schema*.sql") if p.name != "schema.sql")
    for esquema in esquemas:
        con.executescript(esquema.read_text(encoding="utf-8"))
    # um fluxo ja' enviado desta maquina (a fonte de comparacao e' a mesma dele)
    con.execute("INSERT INTO ingestoes (fluxo_id, camera_id, rotulo, fonte, tipo, repetir, codec,"
                " bitrate_alvo, resolucao, fps_nativo, estado, criado_em, atualizado_em)"
                " VALUES ('vivo-cam-02','cam-02','CAM 02','lavfi:testsrc2:1280x720','sintetica',0,"
                "'libx264','1500k','1280x720',30,'parado','2026-11-13T00:00:00-03:00',"
                "'2026-11-13T00:00:00-03:00')")
    con.commit()
    con.close()

    import qualidade

    falhas = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    r = qualidade.comparar_alvos("vivo-cam-02", alvos=("1500k", "2500k", "4000k"), segundos=4.0,
                                 pasta_saida=str(tmp / "clipes"))
    if r.get("erro"):
        print("FALHA nao comparou:", r["erro"])
        return 1

    linhas = r.get("alvos") or []
    exigir(len(linhas) == 3, "medou os 3 alvos (%d)" % len(linhas))
    for x in linhas:
        exigir(x.get("ssim") is not None and 0 < float(x["ssim"]) <= 1,
               "alvo %s tem SSIM medido: %s" % (x.get("alvo"), x.get("ssim")))
        exigir(x.get("nitidez_blur") is not None,
               "alvo %s tem nitidez sem referencia (blur): %s" % (x.get("alvo"), x.get("nitidez_blur")))
        exigir(pathlib.Path(str(x.get("clipe"))).exists(),
               "o clipe de %s existe para o dono ver: %s" % (x.get("alvo"), x.get("clipe")))
    exigir(pathlib.Path(str(r.get("original"))).exists(),
           "o clipe da referencia (SEM PERDA) existe: %s" % r.get("original"))

    por_alvo = {x["alvo"]: x for x in linhas}
    exigir(float(por_alvo["4000k"]["ssim"]) >= float(por_alvo["1500k"]["ssim"]),
           "mais alvo = melhor SSIM na MESMA cena (1500k %s x 4000k %s)"
           % (por_alvo["1500k"]["ssim"], por_alvo["4000k"]["ssim"]))
    exigir(float(por_alvo["4000k"]["mb"]) > float(por_alvo["1500k"]["mb"]),
           "e o clipe gasta mais banda como esperado (%s MB x %s MB)"
           % (por_alvo["1500k"]["mb"], por_alvo["4000k"]["mb"]))

    csv_arq = pathlib.Path(str(r.get("csv")))
    exigir(csv_arq.exists(), "gravou o CSV para anexar ao plano: %s" % csv_arq)
    if csv_arq.exists():
        with csv_arq.open(newline="", encoding="utf-8") as fh:
            linhas_csv = list(csv.DictReader(fh))
        exigir(len(linhas_csv) == 3 and set(linhas_csv[0]) == {"alvo", "ssim", "nitidez_blur", "mb", "clipe"},
               "o CSV tem uma linha por alvo, com ssim/nitidez/mb: %s" % (linhas_csv[0] if linhas_csv else {}))

    print()
    print("clipes em:", r.get("pasta"))
    if falhas:
        print("FALHOU: %d verificacao(oes)" % len(falhas))
        return 1
    print("PASSOU: a mesma cena em 3 alvos com SSIM, nitidez e clipes para o dono comparar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
