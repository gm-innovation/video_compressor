"""Publica as releases 0.2.8 / 0.2.9 / 0.3.0 / 0.4.0 no GitHub com os 4 instaladores cada.

O repositorio e' gm-innovation/video_compressor; a ultima release que existia era a v0.2.7.
O token sai do arquivo normalizado (~/.hermes/vps-deploy/gh-token.txt.norm) e NUNCA e' impresso.
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

REPO = "gm-innovation/video_compressor"
API = f"https://api.github.com/repos/{REPO}"
# O PAT de `.norm` so' LE (criar release devolve 403 "Resource not accessible"). Quem escreve e' a
# credencial que o proprio git usa (Git Credential Manager, token gho_ do dono) — passada pelo ambiente,
# nunca impressa. Ordem: GITHUB_TOKEN_FOR_RELEASES > GH_TOKEN > arquivo .norm.
TOKEN = (os.environ.get("GITHUB_TOKEN_FOR_RELEASES") or os.environ.get("GH_TOKEN")
         or pathlib.Path.home().joinpath(".hermes/vps-deploy/gh-token.txt.norm").read_text().strip())
DIST = pathlib.Path.home() / "lecsor-pipeline-video" / "desktop" / "dist"
PAPEIS = ("Captura", "Terra", "Admin", "Cliente")

NOTAS = {
    "0.4.1": (
        "Instaladores da 0.4.1 (Windows).\n\n"
        "**A tela \"Enviar video\" (com a taxa de envio por camera) volta para dentro do pacote — o PC de "
        "captura dos tecnicos passa a abrir exatamente essa tela.**\n\n"
        "1. O `portal/` (onde mora \"Enviar video para testar\" e o seletor `class=\"qualidade\"` de cada "
        "camera) tinha saido do pacote na 0.2.1 (commit f7f360d): o servidor serve o site pela RAIZ "
        "(`ground/api.py` -> `directory=RAIZ/portal`), entao sem ele `/` nao entregava tela nenhuma no PC "
        "de captura. Agora `portal/` vai em `extraResources` -> `servidor/portal`.\n"
        "2. O instalador do PC de captura nascia na superficie `admin` (o tecnico via o console do "
        "operador). Agora nasce na superficie **bancada** (rota `/`), que e' a tela \"Enviar video\", onde "
        "se escolhe a fonte e a taxa de cada camera.\n\n"
        "Provado na bancada: servidor do pacote serve `/` = 19.205 B com \"Enviar video\" e "
        "`class=\"qualidade\"`; `/admin` continua 200. Instaladores 0.4.1 gerados: "
        "Captura/Terra/Admin/Cliente.\n\n"
        "**A instalacao 0.4.1 que importa e' a do PC de captura** (a tela de envio e o encoder rodam nele)."
    ),
    "0.4.0": (
        "Instaladores da 0.4.0 (Windows).\n\n"
        "**Selecao de qualidade por camera, remover/editar em operacao e destaque na tela do cliente.**\n\n"
        "1. **Qualidade por camera**: cada camera tem a sua taxa de envio, escolhida numa lista FECHADA de "
        "1500k/1200k/1000k/800k/500k/300k. Valor fora da lista e' recusado (HTTP 422) com a lista na resposta. "
        "A escolha vale **no ar**: o envio daquela camera e' reaberto (~2 s) e a resposta diz se aplicou ou, "
        "quando nao aplicou, por que. Abaixo do piso de qualidade o sistema **so' avisa** (nunca recusa).\n"
        "2. **Remover camera** que nao e' mais usada: para o envio, apaga o cadastro aqui e publica a remocao "
        "ao lado terra (o cliente deixa de ver). Trechos e auditoria ficam guardados.\n"
        "3. **Editar camera em operacao**: muda so' o que voce digitar (rotulo/endereco/porta/canal), sem "
        "zerar `ativo` nem a qualidade escolhida; so' reabre o video quando mexe na fonte.\n"
        "4. **Destaque no app do cliente**: 1 camera em tela cheia e 2 a 4 em grade de destaque (botao "
        "Destacar, botao na janela ou duplo clique), sem mexer em banda nem resolucao.\n\n"
        "A selecao de qualidade aparece na tela do PC de captura (Enviar video) e no Admin.\n\n"
        "Provado: 2 testes novos + 12 de regressao rc=0 na bancada; chamada real na VPS com sessao de admin "
        "(alvo fora da lista -> 422; 800k -> aceito com aviso; editar rotulo; remover -> sumiu da lista; "
        "remover de novo -> 404).\n\n"
        "**A instalacao 0.4.0 que importa e' a do PC de captura** (encoder/perfil/alvo rodam nele). "
        "Terra/Admin/Cliente nao precisam ser reinstalados para esta rodada."
    ),
    "0.3.0": (
        "Instaladores da 0.3.0 (Windows).\n\n"
        "**Teste cego do Mbps: o download entrega o video, sem comparativo.**\n\n"
        "O botao \"Baixar 1 minuto\" entrega somente o ARQUIVO (Bytes, Duracao-S, Sha256, Trecho-Id); saiu o "
        "cabecalho de kbps medidos. Quem confere olha o tamanho do video e compara a mao com o Mbps que "
        "aparece no admin/captura. O kbps continua sendo medido e guardado no servidor.\n\n"
        "O **atestado** (comparativo medido x declarado, com a compressao recalculada) virou operacao/admin, "
        "sem excecao de \"chamada local\" - o app do cliente pode estar na mesma maquina do lado terra.\n\n"
        "Medido na VPS: 60 s do vivo-cam-01 = 11.129.556 B / 59,2 s = 1.504,0 kbps contra 1.520,5 kbps "
        "medidos na VPS (1,1%)."
    ),
    "0.2.9": (
        "Instaladores da 0.2.9 (Windows).\n\n"
        "**O que o PC de captura declara chega ao lado terra (declarado x medido).**\n\n"
        "O bordo passa a publicar o envio que esta' no ar (ao subir, a cada 30 s, no fim e ao parar) por "
        "anuncio autenticado com token de ingestao; o lado terra grava e mostra a ultima declaracao por "
        "fluxo, com idade e qualidade, e guarda toda tentativa (aceita ou recusada, com motivo). A medicao de "
        "SSIM reaproveitada do cache e' republicada quando precisa, para o lado terra nao ficar sem numero.\n\n"
        "**A instalacao 0.2.9 que importa e' a do PC de captura** - sem ela o lado terra continua vazio "
        "(era o caso medido: 0 linha em ingestoes/medicoes_qualidade no lado terra)."
    ),
    "0.2.8": (
        "Instaladores da 0.2.8 (Windows).\n\n"
        "**Botao \"Baixar 1 minuto\": a prova da compressao, medida no proprio arquivo.**\n\n"
        "O cliente baixa 60 s do video COMO ELE CHEGA em terra (copia direta, sem reencodar) e o lado terra "
        "guarda o trecho com auditoria; teto de 3 trechos por 10 minutos, 2 simultaneos, validade de 1 h. "
        "O navegador do cliente pede pela camera - nunca recebe fluxo, endereco, porta ou credencial."
    ),
}


def pedir(url: str, corpo=None, metodo="GET"):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
        "Content-Type": "application/json", "User-Agent": "lecsor-publicacao"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def subir_asset(release_id: int, caminho: pathlib.Path) -> str:
    tam = caminho.stat().st_size
    url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={caminho.name}"
    with open(caminho, "rb") as fh:
        req = urllib.request.Request(url, data=fh, method="POST", headers={
            "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/octet-stream",
            "Content-Length": str(tam), "User-Agent": "lecsor-publicacao"})
        try:
            with urllib.request.urlopen(req, timeout=7200) as r:
                return f"{r.status} {json.loads(r.read().decode()).get('name')}"
        except urllib.error.HTTPError as e:
            return f"ERRO {e.code} {e.read().decode()[:200]}"


def main() -> int:
    for versao in ("0.4.1", "0.4.0", "0.3.0", "0.2.9", "0.2.8"):
        s, j = pedir(f"{API}/releases/tags/v{versao}")
        if s == 200:
            rid, existentes = j["id"], {a["name"] for a in j["assets"]}
            print(f"[{versao}] release ja existia (id {rid}), {len(existentes)} asset(s)")
        else:
            s, j = pedir(f"{API}/releases", {"tag_name": f"v{versao}", "name": f"v{versao}",
                                             "body": NOTAS[versao], "draft": False,
                                             "prerelease": False,
                                             "make_latest": "true" if versao == "0.4.1" else "false"},
                         "POST")
            if s not in (200, 201):
                print(f"[{versao}] FALHOU criar release: {s} {json.dumps(j)[:300]}")
                continue
            rid, existentes = j["id"], set()
            print(f"[{versao}] release criada (id {rid})")
        for papel in PAPEIS:
            arquivo = DIST / papel.lower() / f"LECSOR-{papel}-{versao}-x64.exe"
            if not arquivo.exists():
                print(f"[{versao}] FALTA o instalador {arquivo}")
                continue
            if arquivo.name in existentes:
                print(f"[{versao}] {arquivo.name} ja' estava no ar")
                continue
            t0 = time.time()
            r = subir_asset(rid, arquivo)
            print(f"[{versao}] {arquivo.name} ({arquivo.stat().st_size // 1048576} MB) -> {r} "
                  f"em {time.time() - t0:.0f}s", flush=True)
    print("== estado final ==")
    s, j = pedir(f"{API}/releases?per_page=8")
    for r in j if isinstance(j, list) else []:
        print(f"  {r['tag_name']}: {len(r['assets'])} asset(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
