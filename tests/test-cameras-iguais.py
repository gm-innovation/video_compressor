"""Duas cameras USB de MESMO nome precisam coexistir.

O defeito da instalacao real: as duas cameras apareciam como "USB Video Device", o cadastro
casava por nome e a segunda era recusada ("ja esta em uso"). Aqui a saida do
`ffmpeg -list_devices` e' injetada como se houvesse duas cameras identicas e o teste exige
duas entradas distintas, com seletores (@device_pnp_...) distintos.

    python tests/test-cameras-iguais.py
"""
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ground"))

import ingestao  # noqa: E402

SAIDA = (
    '[dshow @ 000001] "USB Video Device" (video)\n'
    '[dshow @ 000001]   Alternative name "@device_pnp_\\\\?\\usb#vid_1c4f&pid_3000#'
    '6&1f2e3d4c&0&1#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\\global"\n'
    '[dshow @ 000001] "USB Video Device" (video)\n'
    '[dshow @ 000001]   Alternative name "@device_pnp_\\\\?\\usb#vid_1c4f&pid_3000#'
    '7&2a3b4c5d&0&2#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\\global"\n'
    '[dshow @ 000001] "Microfone (USB)" (audio)\n'
    '[dshow @ 000001]   Alternative name "@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}'
    '\\wave_{0000}"\n'
)


class _Saida:
    def __init__(self):
        self.stderr = SAIDA


def principal() -> int:
    original = ingestao.subprocess.run
    ingestao.subprocess.run = lambda *a, **k: _Saida()
    try:
        d = ingestao.listar_dispositivos()
    finally:
        ingestao.subprocess.run = original

    falhas = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    disp = d.get("dispositivos") or []
    exigir(len(disp) == 2, "duas cameras identicas -> duas entradas (veio %d)" % len(disp))
    exigir(len(d.get("video") or []) == 2, "lista `video` mantem os dois nomes")
    exigir(len(d.get("audio") or []) == 1, "microfone listado em `audio` (video nao conta audio)")
    if len(disp) == 2:
        exigir(disp[0]["seletor"] != disp[1]["seletor"],
               "seletores distintos (%s vs %s)" % (disp[0]["seletor"][:28], disp[1]["seletor"][:28]))
        exigir(disp[0]["seletor"].startswith("@device_pnp_"), "seletor e' o Alternative name")
        exigir(disp[0]["rotulo"] == "USB Video Device (1)", "rotulo 1 desambigua: %r" % disp[0]["rotulo"])
        exigir(disp[1]["rotulo"] == "USB Video Device (2)", "rotulo 2 desambigua: %r" % disp[1]["rotulo"])
        exigir(d.get("padrao_seletor") == disp[0]["seletor"], "`padrao_seletor` aponta a 1a camera")

    exigir(ingestao._normalizar_dispositivo("video=@x") == "@x", "normaliza prefixo `video=`")
    exigir(ingestao._normalizar_dispositivo(" @y ") == "@y", "normaliza espacos")
    # a chave do registro de "camera em uso" tem que ser o seletor: nomes iguais NAO colidem
    k1 = "dshow:" + ingestao._normalizar_dispositivo(disp[0]["seletor"]) if len(disp) == 2 else ""
    k2 = "dshow:" + ingestao._normalizar_dispositivo(disp[1]["seletor"]) if len(disp) == 2 else ""
    exigir(bool(k1) and k1 != k2, "chaves de identidade diferentes: nao ha falso 'ja esta em uso'")

    print()
    if falhas:
        print("FALHOU: %d verificacao(oes)" % len(falhas))
        return 1
    print("PASSOU: duas cameras de mesmo nome coexistem")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
