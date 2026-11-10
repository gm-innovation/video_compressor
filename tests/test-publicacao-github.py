"""Pré-publicação: o que vai para o GitHub pode ir sem vazar segredo e sem estourar limite.

Roda antes de `git push` do sistema (repositório gm-innovation/video_compressor):
confere o remoto, a ausência de segredo no que sai e o limite de tamanho de arquivo
do GitHub. Sem isso, "publicar" era um ato sem nenhuma verificação própria.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas = []


def checar(nome: str, ok: bool, detalhe: str = "") -> None:
    print(("ok    " if ok else "FALHA ") + nome + (" — " + detalhe if detalhe else ""))
    if not ok:
        falhas.append(nome)


def git(*args: str, entrada: str | None = None) -> str:
    proc = subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True, input=entrada)
    return proc.stdout


# 1) o remoto é o repositório do dono e está configurado
remoto = git("remote", "get-url", "origin").strip()
checar("remoto origin aponta para o repositório do dono",
       remoto.endswith("gm-innovation/video_compressor.git"), remoto or "(sem remote)")

# 2) `.env` (com segredo) fica de fora; o modelo `.env.example` entra
rastreados = git("ls-files").split()
checar("nenhum .env rastreado", not [p for p in rastreados if Path(p).name == ".env"],
       f"{len(rastreados)} arquivo(s) rastreado(s)")
checar(".env.example rastreado", ".env.example" in rastreados)

# 3) nenhum valor de segredo conhecido no que sai (histórico completo, sem contar
#    este próprio arquivo: ele descreve os padrões e se autoacusava)
historico = git("log", "-p", "--all", "--", ".", ":(exclude)tests/test-publicacao-github.py")
padroes = {
    # Literais quebrados de propósito: escritos inteiros, este arquivo entraria no
    # próprio histórico como "segredo encontrado" (foi o que aconteceu na 1ª versão).
    "chave JWT do Supabase": "eyJ" + "hbGciOi",
    "service_role": r"service_role\s*[:=]\s*['\"]?[A-Za-z0-9._-]{20,}",
    "senha de bancada": "Bancada#" + "4d0ef5",
    "chave privada": r"BEGIN (RSA|OPENSSH|PRIVATE) PRIVATE KEY",
}
for nome, padrao in padroes.items():
    achado = re.search(padrao, historico)
    checar(f"histórico sem {nome}", achado is None, achado.group(0)[:40] if achado else "")

# 4) nenhum objeto acima do limite de 100 MB do GitHub (o push seria recusado)
linhas = git("rev-list", "--objects", "--all").splitlines()
maior, caminho = 0, ""
if linhas:
    saida = subprocess.run(
        ["git", "-C", str(RAIZ), "cat-file", "--batch-check=%(objecttype) %(objectsize) %(rest)"],
        input="\n".join(linhas), capture_output=True, text=True,
    ).stdout
    for linha in saida.splitlines():
        partes = linha.split(" ", 2)
        if len(partes) == 3 and partes[0] == "blob":
            tamanho = int(partes[1])
            if tamanho > maior:
                maior, caminho = tamanho, partes[2]
checar("nenhum arquivo acima de 100 MB (limite do GitHub)",
       maior < 100 * 1024 * 1024, f"maior: {maior / 1048576:.1f} MB ({caminho})")

# 5) o envio é fast-forward (sem --force): o ref remoto tem de ser ancestral do HEAD
tem_remoto = git("rev-parse", "--verify", "--quiet", "origin/main").strip()
if tem_remoto:
    ancestral = subprocess.run(
        ["git", "-C", str(RAIZ), "merge-base", "--is-ancestor", "origin/main", "HEAD"]
    ).returncode == 0
    checar("envio é fast-forward (origin/main é ancestral do HEAD)", ancestral)
else:
    checar("origin/main ainda não buscado (primeiro envio)", True, "sem ref remota na cópia local")

print()
if falhas:
    print(f"{len(falhas)} falha(s): " + ", ".join(falhas))
    sys.exit(1)
print("tudo certo")
