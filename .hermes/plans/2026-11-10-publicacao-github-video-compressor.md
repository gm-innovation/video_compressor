# Plano — publicar o sistema no GitHub (`gm-innovation/video_compressor`)

Situação: **aprovado** pelo dono (2026-11-10). Pedido literal: "criei o repo no github, precisamos enviar o
sistema para lá, veja qual a melhor forma de acesso" + token fine-grained cadastrado.

## Objetivo

Publicar o sistema LECSOR de vídeo bordo→terra (o repositório local `lecsor-pipeline-video`, 198 arquivos
rastreados, 50 commits) no repositório remoto `gm-innovation/video_compressor`, sem reescrever histórico e
sem enviar segredo.

## Acesso (decisão)

**HTTPS + token fine-grained pelo Git Credential Manager.** Verificado nesta máquina: o helper
`git-credential-manager.exe` já está configurado, não existe chave SSH do GitHub instalada (`ssh -T` devolve
`Permission denied (publickey)`) e o `gh` não está instalado. O `git push --dry-run` já autenticou (o GitHub
respondeu "rejected ... fetch first", que é negociação autenticada, não falha de credencial). Logo o token
cadastrado pelo dono já está guardado e o envio não precisa de segredo em chat.

## Escopo do envio (video_compressor)

- Rama local `master` → `main` do remoto, com `-u`, **sem `--force`**: o merge do commit inicial do remoto
  (`1729d41 Initial commit`, só o README do GitHub) já foi feito em `eb150fb`, então o envio é fast-forward.
- Código: `ground/` (captura, SRT, API), `app/` e `admin/` (produto do cliente e operação), `desktop/`
  (Electron + instaladores), `fronts/`, `tests/`, `tools/`, `README.md`.
- O histórico traz também `tools/mediamtx/mediamtx.exe` (54,7 MB) e um vídeo de demonstração do Makito X4
  baixado do YouTube (26,9 MB) — o dono autorizou o uso dos vídeos e o encoder alvo é justamente o Makito X4.
  Repositório público hoje; trocar para privado é decisão do dono.
- Não sai segredo: `.env` está fora do repositório (só `.env.example` com marcadores), o `desktop/config.json`
  aponta para `127.0.0.1` e a varredura do histórico não encontrou valor de senha nem chave (só nomes de
  variável).

## Verificação

- `python -m unittest` (runner novo em `tests/suite.py`) roda os testes do projeto e precisa passar.
- Depois do envio: `git ls-remote origin` mostra `refs/heads/main` apontando para o commit local `HEAD`.
