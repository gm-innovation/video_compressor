# Embutir o ffmpeg no instalador (o app nasce capaz de listar e capturar câmera)

**Status:** **aprovado e executado** (dono: "prossiga" em 13/11/2026) — Fases 1 a 5 concluídas no
mesmo dia; números medidos abaixo.

**Decisões tomadas dentro das recomendadas:** build *essentials* do fornecedor oficial (ffmpeg 9.0.2,
`ffmpeg.exe` 105.423.872 B + `ffprobe.exe` 105.221.120 B), **embutido nos dois instaladores**, binário
fora do Git (baixado e conferido por SHA-256 no build).

**Evidência de fechamento (13/11/2026):**

| o que foi provado | como |
|---|---|
| binário embutido no pacote | `desktop/dist/{cliente,admin}/win-unpacked/resources/ffmpeg/{ffmpeg.exe,ffprobe.exe}` com 105.423.872 / 105.221.120 B e `ffmpeg.exe -version` = `ffmpeg version 9.0.2-essentials_build` |
| o app entrega o caminho aos filhos | asar com `ffmpegDe` (4×) e `LECSOR_FFMPEG` (1×); `tests/test-ffmpeg-embutido.py` roda `desktop/servidor.js` no node e confere `LECSOR_FFMPEG`, `LECSOR_FFPROBE` e a pasta no PATH |
| o sistema usa o binário resolvido | mesmo teste: `argv[0]` da enumeração é o caminho do app (não a string `ffmpeg`); sem variável cai para o PATH; caminho inexistente é ignorado |
| nada quebrou na troca dos 13 pontos / 5 arquivos | `python -m unittest discover -s tests -p 'suite.py' -t .` → OK (20,400 s); `tests/test-dispositivos-honesto.py` → OK |
| tamanho medido | instalador de **81,7 MB → 137.905.275 B (cliente) / 137.905.323 B (admin)** = ~131,5 MB cada |
| release publicada | **v0.1.4** com os dois `.exe` (`uploaded`, tamanhos conferidos na API do GitHub) |
| script de download | `desktop/baixar-ffmpeg.sh` gravando ao lado do destino (no `/tmp` o curl morria com erro 23) e **sem `-C -`** (resume + retry confundia o offset); hash publicado conferido (`60f4672…` do pacote baixado = o publicado) |
**Pedido do dono (13/11/2026):** *"você não consegue inserir o ffmpeg no .exe e instalar no computador junto com o app?"* — depois de confirmar no PC de teste que **não há ffmpeg naquela máquina** (a lista de câmeras fica vazia por isso, mesmo com as duas no Gerenciador de Dispositivos).

## 1. Situação medida (13/11/2026)

| fato | evidência |
|---|---|
| O pacote **não** leva `ffmpeg.exe` | `desktop/dist/admin/win-unpacked/` tem só `ffmpeg.dll` (do Electron) |
| O unico enumerador de camera e' o ffmpeg | `ground/ingestao.py:515` roda `ffmpeg -hide_banner -list_devices true -f dshow -i dummy` |
| O binario existe nesta bancada e tem tamanho conhecido | `%LOCALAPPDATA%\hermes\tools\ffmpeg-9.0.1-win32-x64\bin\ffmpeg.exe` = **144.862.208 B (138 MB)**; `ffplay`/`ffprobe` 140 MB cada |
| Instalador atual (0.1.3) | ~81,7 MB por arquivo (`LECSOR-Cliente`/`LECSOR-Admin`) |
| Superficie a ajustar | `"ffmpeg"` literal em **13 pontos, em 10 arquivos .py** (`ground/ingestao.py` 16 menções, `board/agent.py`, `ground/etapas.py`, `qualidade.py`, etc.) |
| `package.json` nao tem `extraResources` | `build.files` = `main.js, preload.js, servidor.js, config.json, janelas/**` |
| O app ja' injeta ambiente nos filhos | `desktop/servidor.js` `amb()` injeta `LECSOR_DESTINO_SRT`; `pythonDe()` acha o `python` do repo |

## 2. Decisão de projeto (o que embutir e como o app acha)

1. O binário entra por **`extraResources`** (fica fora do `app.asar`, em `resources/ffmpeg/ffmpeg.exe`) —
   dentro do asar ele não é executável.
2. **O binario nao e' versionado no Git** (138 MB no repositório é lixo permanente): um script
   `desktop/baixar-ffmpeg.sh` baixa a build oficial, **confere SHA-256** e deixa em `tools/ffmpeg/`
   (que entra no `.gitignore`); `construir-instaladores.sh` chama esse script antes do build. Se já
   houver o `.exe` local com o hash certo, não baixa de novo.
3. O app passa o caminho para os processos filhos: `LECSOR_FFMPEG=<resources>/ffmpeg/ffmpeg.exe`
   (mesmo lugar onde já injeta `LECSOR_DESTINO_SRT`) **e** põe a pasta no `PATH` dos filhos, para
   qualquer chamada que eu não tenha trocado continuar funcionando.
4. No Python, uma única função `caminho_ffmpeg()` (em `ground/ingestao.py`, importada pelos outros)
   devolve `os.environ.get("LECSOR_FFMPEG")` quando existir, senão `shutil.which("ffmpeg")`, senão
   `"ffmpeg"` — e os 13 pontos passam a usá-la.

## 3. Fases

### Fase 1 — P0 · Empacotar o binário
- `desktop/baixar-ffmpeg.sh` (URL fixa + `sha256sum -c`), `tools/ffmpeg/` no `.gitignore`,
  `extraResources` no `desktop/package.json`, `construir-instaladores.sh` chamando o download.
- **Aceite:** `desktop/dist/admin/win-unpacked/resources/ffmpeg/ffmpeg.exe` existe e
  `./resources/ffmpeg/ffmpeg.exe -version` responde; `app.asar` **não** cresceu 138 MB.
- **Custo:** 1 sessão.

### Fase 2 — P0 · O sistema usa o embutido
- `caminho_ffmpeg()` + troca dos 13 pontos; `desktop/servidor.js` injeta `LECSOR_FFMPEG` e o `PATH`.
- **Aceite:** `tests/test-ffmpeg-embutido.py` prova que, com `LECSOR_FFMPEG` apontando para um ffmpeg
  de mentira, a enumeração usa **esse** caminho (argv[0]); sem a variável e sem PATH, `listar_dispositivos()`
  volta com `erro` claro e `padrao` vazio (comportamento já provado em `test-dispositivos-honesto.py`).
- **Custo:** 1 sessão.

### Fase 3 — P1 · O estado diz de onde vem o ffmpeg
- *Ver estado do servidor* mostra `ffmpeg: embutido (<versão>) — <caminho>` / `do PATH` /
  `NAO ENCONTRADO`; `GET /api/dispositivos` ganha `ffmpeg: {origem, caminho, versao}`.
- **Aceite:** harness jsdom com as três respostas.
- **Custo:** meia sessão.

### Fase 4 — P1 · Prova no pacote, não só no código
- Além do teste da Fase 2: conferir no `dist` que o `.exe` está em `resources/` e que
  `app.asar` não engordou; rodar `python tests/test-dispositivos-honesto.py` (não pode ter regredido).
- **Aceite:** `node ...`/script de verificação imprimindo os três tamanhos (app.asar, resources/ffmpeg,
  instalador) e o `-version` do binário embutido.
- **Custo:** meia sessão.

### Fase 5 — P2 · Instalador e release
- Bump **0.1.4**, build, **medir o instalador novo** (o de hoje tem 81,7 MB; a estimativa com 138 MB
  de ffmpeg comprimido é de 160 a 220 MB — **não sei o número até buildar**), publicar release e
  atualizar `README.md`/`INSTALAR-PC-DE-CAPTURA.md` (ffmpeg deixa de ser exigência manual no PC).
- **Aceite:** release 0.1.4 com os dois `.exe`, tamanhos medidos, e o texto do passo a passo sem o
  item "instale o ffmpeg".
- **Custo:** 1 sessão.

## 4. Decisões que preciso do dono

1. **Binário grande ou pequeno?** O ffmpeg que já existe nesta bancada tem 138 MB (build "full", com
   tudo). Uma build **essentials** (só o necessário, mesmo `dshow`) tem ~80–90 MB e faz o instalador
   ficar ~40 MB menor. **Recomendo a essentials.**
2. **Os dois instaladores levam o binário?** Cliente e Admin hoje são o mesmo app com telas
   diferentes. Se o Cliente nunca for lado terra/captura, ele pode continuar sem o ffmpeg (~82 MB).
   **Recomendo embutir nos dois** (o dono já usou o app do cliente para capturar na bancada).
3. Sem rede no momento do build, o script usa o `.exe` que já estiver em `tools/ffmpeg/`; se não
   houver nenhum, o build **para** com mensagem clara (nunca gera instalador sem o binário).

## 5. Limites declarados
- Não sei o tamanho exato do instalador novo até rodar o build (medirei e reportarei o número real).
- Embutir o binário resolve a máquina que **não tem** ffmpeg; se a câmera não aparecer **nem** pelo
  ffmpeg embutido, aí é driver/DirectShow da câmera, não o app — o `.exe` embutido permite provar isso
  na própria máquina do cliente (o estado mostra a versão e o caminho usados).


## Fechamento da rodada (13/11/2026, depois do build): o download do binário

O build 0.1.4 saiu com os binários do essentials, mas a rodada de verificação mostrou que **o download
automático não era confiável** e o script foi refeito:

| o que foi medido | resultado |
|---|---|
| `curl` 8.18 (MSYS) baixando o zip de ~114/194 MB | `curl: (23) client returned ERROR on write` **sem criar o arquivo**, em qualquer fonte, com ou sem `-C -`, com `--retry-all-errors --retry 8`, na pasta do repo e no `/tmp` |
| o MESMO arquivo pelo `urllib` do Python | 194.055.132 B inteiros, SHA-256 `096d0596…6a91c` = o pinado |
| `unzip` no pacote | falhava porque o script fazia `rm -rf "$DEST"` com o zip **dentro** de `tools/ffmpeg` (o arquivo era apagado no meio do caminho) |
| fonte alternativa | BtbN/FFmpeg-Builds, tag fixa `autobuild-2026-11-13-12-43`, asset `ffmpeg-n8.1.3-35-gf1acb0a266-win64-gpl-8.1.zip` (binários de 165.442.048 / 165.236.224 B) |
| fonte 1 com o override apontando para host inexistente | caiu para a fonte 2, hash conferido, binários extraídos, `ffmpeg version n8.1.3-35-gf1acb0a266-20261113` |
| fonte 1 normal (gyan.dev) pelo Python | 105.423.872 / 105.221.120 B, `ffmpeg version 9.0.2-essentials_build` — **os mesmos binários do 0.1.4 publicado** |
| suíte + `tests/test-ffmpeg-embutido.py` | OK (o teste ganhou a seção 5: 2 hash pinados, Python antes do curl, `cygpath`, zip fora de `tools/ffmpeg`, reserva entre fontes) |

Script final: `desktop/baixar-ffmpeg.sh` — duas fontes com SHA-256 pinado, download e extração pelo
Python (`cygpath -m` para o caminho nativo), curl+unzip só como reserva, 4 tentativas por fonte e
reserva para a fonte seguinte; pasta de trabalho em `tools/.baixando/` (fora do Git). **Nada do 0.1.4
publicado mudou**: os binários embutidos no instalador são exatamente os do essentials.
