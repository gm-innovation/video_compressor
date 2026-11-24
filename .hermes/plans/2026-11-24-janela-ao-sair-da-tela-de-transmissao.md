**Status:** APROVADO E IMPLEMENTADO em 0.13.1 (2026-11-24) — D-A = a janela vale tambem gravando; D-B = so' a tela `visualizar` conta como assistindo; D-C = saem as 23 cameras de teste + o cliente `armador-e2e` (ficam os 2 dispositivos do bordo que estavam no ar); D-D = `object-fit:cover`.

# Janela de 60 s ao sair da tela + grade do cliente (card abaixo, imagem cheia) + limpeza das câmeras de teste

**Goal:** (1) quando o cliente sai da tela **Transmissões ao vivo** e volta em até **60 s**, a transmissão
continua de pé (nada de reconectar); se ele ficar fora mais de 60 s, a sessão encerra sozinha e o bordo para.
(2) A grade do cliente perde as informações/botões de cima da imagem, ganha um **card abaixo** dela e a imagem
**ocupa todo o espaço** da janela (fim das faixas pretas laterais). (3) O banco do terra fica **sem as câmeras
de teste** criadas nas rodadas de campanha.

**Data:** 2026-11-24 · **Produto:** [[pipeline-video]] · **Ponto de partida:** `main` = `827aec8` (0.13.0)

## O que o dono pediu (verbatim)

> eu saio da página de transmissão ao vivo, retorno a ela e a transmissão continua ativa, tem algum espaço de
> tempo para encerrar a transmissão? seria bom determinarmos, talvez, 60s após sairmos da página, encerrar a
> transmissão, assim, se o cliente precisar ver outras coisas enquanto acompanha o vídeo do radar, ele não tem
> que ficar reconectando

> inclua também no plano: remover câmeras de teste criadas por você · remover as informações e botões de cima da
> imagem, criar card abaixo da imagem da câmera · a imagem da câmera deve ocupar todo o espaço destinado a ela,
> removendo as faixas pretas laterais

## Evidência — a janela de 60 s (levantada no código, fato | como foi verificado)

| Fato | Como foi verificado |
|---|---|
| O batimento roda **global**, a cada 10 s, fora da tela | `app.js:1320` `setInterval(baterPonto, 10000)` no topo do arquivo |
| Ele bate para **todas** as sessões abertas (`S.minhas`), sem olhar a tela | `app.js:1041-1046` |
| A sessão só morre depois de **60 s sem batimento** | `api.py:379` `SEGUNDOS_SEM_BATIMENTO = 60`; `api.py:1263-1288` `_vigiar_uma_vez` fecha com "a tela foi fechada ou o computador foi desligado" e chama `parar_se_ninguem_vendo` |
| Fechar a aba já encerra **na hora** (não é isso o defeito) | `app.js:1322-1324` `pagehide` → `sendBeacon('/api/transmissao/<id>/encerrar')` |
| Trocar de tela **não** recarrega a página (SPA) | `app.js:1210` `trocarTela` só faz `S.tela = tela` e redesenha |
| A única tela com o **vídeo** é a `visualizar` | `app.js:600` `TELAS.visualizar = ['Transmissões ao vivo', …]`; a `transmissao` (Transmitir) é uma **lista** de câmeras com botões, sem vídeo (`app.js:1048-1104`) |
| A expiração por **tempo** já respeita a gravação; a de batimento **não** | `api.py:1276` tem `AND gravando=0`; o `SELECT` de `sem_batimento` (`api.py:1273`) **não** tem |

**Consequência (o defeito):** como o batimento é global e roda a cada 10 s, **enquanto o app estiver aberto a
sessão nunca expira** — em qualquer tela. Foi exatamente o que o dono viu: saiu, voltou, tudo no ar.

**Correção de fundo:** a mudança é uma só — amarrar o batimento à **tela que mostra o vídeo**. A janela de
60 s já existe (`SEGUNDOS_SEM_BATIMENTO`); hoje ela só dispara se a aba travar/cair.

## Evidência — a grade do cliente (fato | como foi verificado)

| Fato | Como foi verificado |
|---|---|
| O controle da transmissão fica **sobre a imagem**, no topo | `fronts/vms.css:91` `.controle-transmissao{position:absolute;top:7px;left:7px;right:7px}` |
| O nome/estado da câmera também é um selo **sobre a imagem** | `fronts/vms.css:65-67` `.rotulo-cam{position:absolute;…}` |
| Há botões sobre a imagem (energia, "Baixar 1 minuto", "Destaque") | `app.js:219-232` (`.controle-cam`) e `app.js:245-254+` (`.controle-trecho`) |
| A janela tem **16:9 fixo** e o vídeo entra com `contain` | `fronts/vms.css:60-61` `.janela{…aspect-ratio:16/9…}` e `:63` `.janela video{…object-fit:contain…}` |
| A janela é montada juntando o `<video>` + os selos/botões dentro dela | `app/app.js:200-300` (`desenharVisualizar`) e `:339+` (destaque) |

**Consequência:** com `contain` dentro de uma janela 16:9, um fluxo que **não é 16:9** (as USB da bancada são
4:3) é centralizado e sobram **faixas pretas nas laterais**; e tudo o que é informação/ação está **em cima** do
vídeo, tapando a imagem.

## Evidência — câmeras de teste no banco do terra (fato | como foi verificado)

Medido na VPS em 2026-11-24 (`SELECT id, embarcacao_id, rotulo, fluxo_id, ativo FROM cameras`, via `ssh` em
`/opt/pipeline/app/db/pipeline.db`) — **26 câmeras em 2 embarcações de teste** + 1 cliente de teste:

- **`bancada` — "Bancada de testes (propria)" — 20 câmeras:** `cam-01`, `cam-02`, `cam-09`, os 7
  `cam-device-pnp-usb-vid-*` (ACER/AFN/USB Video…), os 8 `vivo-*` (`vivo-cam-01`, `vivo-cam-02`,
  `vivo-cam01-1811`, `vivo-cam02-1811`, `vivo-cam1-11-18`, `vivo-cam2-11-18`, `vivo-usb-video`,
  `vivo-webcam-da-bancada-prova`) e os 2 `vps-*` (`vps-sintetica`, `vps-webcam-bancada`);
- **`psv-exemplo` — "PSV Exemplo (demo)" — 6 câmeras:** `cam-01-demo`, `cam-02-demo`, `cam-03-analitico`,
  `cam-04-demo`, `envio-envio-pela-tela-teste`, `envio-envio-por-link-teste`;
- **cliente `armador-e2e` — "Armador E2E (criado pela tela)"** (nasceu no `tests/e2e-fronts.py:118`).

Já existe a ferramenta de limpeza: `ground/limpar-cameras-teste.py` (dry-run por padrão, `--aplicar` numa
transação, `--orfaos` para o histórico de fluxo que não é câmera) — mas a lista dela é de **11/11/2026**
(`CAMERAS_ALVO`, l. 27-29) e **não cobre** os ids desta campanha.

## Decisões (uma linha cada; o dono confirma ou troca)

- **D-A — gravação em andamento:** a janela de 60 s vale **também gravando** (recomendado). O batimento é
  "estou com o vídeo na frente"; ao alinhar, o fechamento por batimento passa a olhar `gravando` como a
  expiração por tempo já olha. *(Alternativa: enquanto grava, a sessão não expira por saída de tela.)*
- **D-B — a tela `transmissao` (Transmitir) conta como "assistindo"?** Recomendado **não** (ela não tem
  vídeo); "assistindo" = `visualizar` + aba visível. *(Alternativa: as duas telas.)*
- **D-C — o que sai na limpeza:** recomendado remover as **26 câmeras** das duas embarcações de teste e o
  cliente `armador-e2e`; a **Bancada de testes** e o **PSV Exemplo (demo)** ficam de pé (só as câmeras saem).
- **D-D — a imagem:** `object-fit:cover` faz a imagem **preencher** a janela e **cortar** as bordas (é o que
  "ocupar todo o espaço" pede); alternativa é a janela adotar o **ratio do próprio vídeo** (não corta, mas a
  grade fica irregular). Recomendado **cover**.

## Fase 1 — a janela de 60 s ao sair da tela (P0 + P1)

**P0 — o batimento passa a valer só na tela do vídeo**
- `app/app.js`
  - `baterPonto()` (l. 1041) ganha a guarda: `if (S.tela !== 'visualizar' || document.visibilityState !== 'visible') return;`
    (a lista de telas extras, se D-B for "sim", entra aqui).
  - `trocarTela` (l. 1210) chama `baterPonto()` **na hora** ao entrar em `visualizar` (o retorno dentro dos
    60 s não pode depender do próximo tick de 10 s).
  - `visibilitychange` (l. 1325) mantém o `baterPonto()` já existente ao ficar visível.
- `ground/api.py`
  - A janela continua **60 s** (`SEGUNDOS_SEM_BATIMENTO = 60`, l. 379) — sem novo número; só o **comentário**
    da constante passa a citar "saiu da tela ao vivo" além de "tela fechada/computador desligado".
  - Se **D-A = sim**, o `SELECT` de `sem_batimento` (l. 1272-1274) ganha `AND gravando=0` — igual à expiração
    por tempo (l. 1276) — e o motivo do fechamento cita "saiu da tela ao vivo por mais de 60 s".

**P1 — a janela aparece para o app**
- `ground/api.py`: o payload de estado da transmissão (o mesmo do `aviso_segundos`, l. ~2137) ganha
  `"janela_sem_tela": SEGUNDOS_SEM_BATIMENTO`, para a tela poder dizer "você tem 60 s" sem número fixo no front.

**Critério de aceite (Fase 1):** `grep -n "S.tela !== 'visualizar'" app/app.js` mostra a guarda em
`baterPonto`, e `node --check app/app.js && python -m py_compile ground/api.py` limpos.

## Fase 2 — a grade do cliente: card abaixo e imagem preenchendo (P0 + P1)

**P0 — tirar informação/ação de cima da imagem e pôr num card abaixo**
- `fronts/vms.css`
  - `.janela` (l. 60-61) vira contêiner em coluna (`display:flex; flex-direction:column`): o `<video>` em cima e
    um **`.card-cam`** logo abaixo, **fora** da área da imagem (fim do `position:absolute` sobre o vídeo).
  - `.controle-transmissao` (l. 91), `.rotulo-cam` (l. 65-67), `.controle-cam` e `.controle-trecho` deixam de
    ser `position:absolute` sobre o vídeo e passam a morar dentro do `.card-cam`.
- `app/app.js`
  - Em `desenharVisualizar()` (l. 200-300) e no destaque (l. 339+): o `.rotulo-cam`, o `.controle-cam`, o
    `.controle-trecho` e o `.controle-transmissao` (via `montarControle`) passam a ser anexados ao `.card-cam`,
    não à `.janela`.
  - Sobre a imagem ficam só o `<video>` e o `.marca-dagua`; o `.aviso-cam` (tarja "fora do ar") continua no
    centro da imagem — é aviso, não controle.

**P1 — a imagem ocupa o espaço (fim das faixas pretas)**
- `fronts/vms.css:63`: `.janela video{object-fit:cover}` (D-D) — a imagem preenche a janela e as faixas
  laterais somem; a janela mantém o 16:9 da grade.

**Critério de aceite (Fase 2):** `grep -n "position:absolute" fronts/vms.css` **não** aponta mais
`.controle-transmissao`/`.rotulo-cam`; `grep -n "object-fit" fronts/vms.css` mostra `cover`; a tela abre sem
erro de JS (o teste da Fase 4 cobre).

## Fase 3 — limpeza das câmeras de teste no banco do terra (P0)

**P0 — atualizar a lista e aplicar**
- `ground/limpar-cameras-teste.py`: `CAMERAS_ALVO` (l. 27-29) passa a ser a lista **desta campanha** — os 20 ids
  da `bancada` e os 6 da `psv-exemplo` (a lista completa sai do `SELECT` acima) — e o cliente `armador-e2e`
  entra no mesmo `--aplicar` (com os vínculos).
- Rodar na VPS: **backup** de `db/pipeline.db`, `--db db/pipeline.db` (dry-run) para o relatório, depois
  `--aplicar`; conferir a contagem por embarcação antes e depois.

**P1 — não sobrar órfão**
- Rodar também `--orfaos --aplicar` (histórico de fluxo que não é mais câmera — o que aparece como "câmera
  fantasma" na tela Produção).

**Critério de aceite (Fase 3):** o dry-run lista as 26 câmeras e o cliente `armador-e2e`; depois do `--aplicar`,
`SELECT count(*) FROM cameras` cai para o que **não** é teste e a tela do cliente de `bancada`/`psv-exemplo` não
mostra nenhuma câmera de campanha.

## Fase 4 — prova e regressão (P0 + P1)

**P0 — `tests/e2e-janela-ao-sair-da-tela.py` (novo, Playwright + mediamtx/ffmpeg como no `e2e-gravacao-no-cliente`)**
1. cliente entra, abre a sessão na grade → `desejo=ligar`;
2. **sai da tela** `visualizar` (clica em outra aba do menu) e **volta em menos de 60 s** → a sessão
   **continua aberta** e o vídeo volta **sem** passar por "Reconectar";
3. **sai de novo** e, no banco, adianta `batimento_em` para mais de 60 s atrás + roda uma passada do vigia →
   a sessão vira `encerrada`, o `desejo` da câmera vira `parar` e a grade mostra **Reconectar**;
4. (se **D-A = sim**) repetir 3 **gravando**: a sessão também encerra e o mp4 final fica no disco com
   tamanho > 0;
5. **grade**: a janela tem o `.card-cam` **abaixo** do `<video>` (nenhum `.controle-transmissao`/`.rotulo-cam`
   filho direto da `.janela` sobre a imagem) e o `<video>` calcula `object-fit:cover`.

**P1 — regressão**
- `tools/regressao-0130.py` roda de novo **inteiro** (25 provas) — é a suíte que já cobre a flag de
  audiência (D3), a contagem/aviso/reconectar e a gravação, que são o que esta rodada toca.

**Critério de aceite (Fase 4):** `python tests/e2e-janela-ao-sair-da-tela.py` → **RC=0**;
`python tools/regressao-0130.py` → **TUDO VERDE**.

## Fase 5 — deploy, release e nota no vault (P0)

- `desktop/package.json` → **0.13.1**; `tools/publicar-releases.py` ganha a nota `0.13.1` e entra na frente de
  `VERSOES_PUBLICADAS`.
- Build do instalador (`desktop/construir-instaladores.sh` → `dist/unico/LECSOR-0.13.1-x64.exe`), sha256
  registrado.
- **Deploy do terra** na VPS (`/opt/pipeline/app`): `ground/api.py`, `app/app.js`, `fronts/vms.css` (e o que
  mais mudar) via `git show HEAD:<f>` + `scp`/`cat`, backup em `.antes-0131/`, `py_compile`, `chown 4096:4096`,
  restart do `pipeline-api.service`; conferir **md5 local = md5 da VPS**.
- Release `v0.13.1` no GitHub (asset `uploaded`, `make_latest`), e nota no vault
  (`~/.hermes/vault-arrow/20-runbooks/`) + bullet no `index.md` pelo script autorizado do vault.

**Critério de aceite (Fase 5):** `main` empurrado; release `v0.13.1` = `latest` com o asset; `/api/saude` 200 e
`/admin` 200 na VPS; md5 dos arquivos do terra = git HEAD; nota no `master` do vault.

## Arquivos que vão mudar

- `app/app.js` (a guarda do `baterPonto` + a batida ao entrar em `visualizar`; o `.card-cam` com os controles);
- `fronts/vms.css` (`.janela` em coluna + `.card-cam`; `object-fit:cover`);
- `ground/api.py` (comentário da janela, `gravando` no `sem_batimento` se D-A=sim, `janela_sem_tela` no payload);
- `ground/limpar-cameras-teste.py` (lista fechada nova + o cliente `armador-e2e`);
- `tests/e2e-janela-ao-sair-da-tela.py` (novo);
- `tools/regressao-0130.py` (aponta para a nova prova);
- `desktop/package.json` + `tools/publicar-releases.py` (0.13.1).

## Riscos e limites (declarados)

- **Aba em segundo plano:** o navegador estrangula timers; por isso a guarda inclui
  `document.visibilityState === 'visible'`. A prova mede a **troca de tela dentro do app**, não "aba oculta por
  60 s" (isso já é coberto pelo `sem_batimento` de hoje).
- **`object-fit:cover` corta as bordas** da imagem (D-D). Se o dono quiser o quadro inteiro sem corte, a saída
  é a janela adotar o ratio do vídeo — e a grade fica irregular.
- **D-B aberta:** se a tela `transmissao` **não** contar como assistindo e o cliente abrir a sessão por lá sem
  ir para `visualizar`, a sessão morre em 60 s. É decisão do dono, não escolha técnica.
- **Limpeza é destrutiva** no banco de **produção** (VPS): roda com backup antes e é o `--aplicar` que apaga (o
  dry-run é o padrão do script).
- **Outros espectadores:** o "outro computador assistindo" continua valendo — o batimento é por sessão, e
  `parar_se_ninguem_vendo` só para quando **todas** as sessões daquela câmera caíram (D3 mantido).
- **Não medido aqui:** as fases do smoke que dependem do **PC de captura real** (4 câmeras + radar, rodada
  longa 2 h/8 h) seguem **NÃO MEDIDAS** — esta rodada não as toca.
