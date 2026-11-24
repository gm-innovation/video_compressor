# Plano — a flag de audiência, a saúde/desempenho na tela, a contagem regressiva com aviso/reconectar e a gravação (23/11/2026)

Pedido do dono (verbatim, 23/11/2026):

> testei aqui, saí da tela de transmissão ao vivo do cliente e continuou transmitindo, isso precisa ser flag
> para o app de captura enxergar e parar a transmissão, a não ser que esteja sendo visualizado em outro
> computador
> não tenho nenhuma informação de saúde e desempenho
> precisa de um timer de contagem regressiva de acordo com a configuração de tempo de streaming para o cliente
> saber em quanto tempo as câmeras serão desconectadas, e antes de desconectar, uma mensagem perguntando se
> quer continuar conectado, se clicar em não ou se não houver resposta dentro de um tempo determinado,
> desconecta, aí aparece um botão "reconectar" para caso o cliente queira voltar a ver as imagens, e precisa
> também de um botão para iniciar gravação

Regra que continua valendo: a arquitetura do comando é **bordo OLHA terra** (o PC de captura não recebe
conexão). Então "flag" aqui = o que terra publica em `/api/estado-desejado`, que o agente do bordo lê a cada
2 s e aplica só na diferença.

## Fase 1 — a flag de audiência: quem sustenta o "ligar" é o espectador (P0)

**Causa medida (não palpite).**
- `ground/api.py:483-494` (`_desejo_das_cameras`): a ordem de decisão é `camera desativada` → `manual=='parar'`
  → **sessão viva** → `manual=='ligar'` → `parar ("ninguem esta' assistindo")`. Ou seja: `manual=='ligar'`
  **vence** o "ninguém está assistindo".
- `ground/api.py:3631-3637` (`POST /api/cameras/ligar`, o botão "ligar agora" que entrou na área nova):
  grava `desejo_camera.manual='ligar'`. **Nada limpa esse `manual` pelo fato de o espectador ter saído** — só
  um clique em "desligar" (`manual='parar'`) ou uma sessão viva (`api.py:4184-4185` só limpa quando já há
  sessão).
- Medido agora na VPS (`db/pipeline.db`): 2 câmeras da `bancada` com `manual='ligar'`, atualizadas às
  20:15:22 e 20:15:56 UTC (durante o teste) e `transmissoes` **vazio** (nenhuma sessão viva). É exatamente o
  sintoma: sem ninguém assistindo, a transmissão continua por causa do `manual`.

**Correção (no código, sem passo manual no bordo; decisões D3 do dono).**
1. **O "ligar agora" do admin sai** (`admin/admin.js:2418`) e o `manual='ligar'` deixa de ser escrito
   (`ground/api.py:3635`): quem liga é **só o cliente que está visualizando** — o `desejo` passa a ser
   sustentado **exclusivamente** por sessão viva (qualquer computador).
2. `manual=='parar'` (o "desligar" da operação) **fica**: desligar na mão continua valendo; o que sai é o
   ligar manual.
3. O motivo publicado (`motivo`) diz quem sustenta o `ligar` (`N sessão(ões) assistindo: <e-mail>`), para a
   tela e a trilha contarem a verdade.
4. O bordo **não muda**: ele já lê a flag a cada 2 s e obedece (`agente_de_ordens.aplicar_flag`). A correção
   é só em terra (`_desejo_das_cameras` + a rota do `ligar`), e a `versao` do desejo sobe quando muda.

**Provas.** `tests/e2e-flag-de-audiencia.py` (novo): cliente A abre a tela → `desejo=ligar`; A sai → em
≤ `SEGUNDOS_SEM_BATIMENTO` (60 s) `desejo=parar`; com A e B assistindo, A sai e **continua** `ligar`; o
"ligar agora" do admin **não** sobrevive sem ninguém assistindo; o motivo publicado cita os espectadores.

## Fase 2 — saúde e desempenho na tela (P0)

**Causa medida.**
- A saúde **chega e está fresca**: `saude_bordo` com 20.241 retratos da `bancada`, o último em
  `2026-11-23T20:50:21+00:00`, `estado='atencao'`, `maquina='DESKTOP-78DSH57'`, **`versao_app` vazio**.
- O que a área nova mostra hoje de saúde é só a linha
  `Câmeras: N · no ar: M · último retrato do bordo: <hora> · PC(s): <máquina>` (`admin/admin.js:2274-2282`).
  **Os números** (CPU, memória, disco, anel do HD, ffmpeg, captura viva, mediamtx, erros) só existem na tela
  antiga `Saúde do bordo` (hoje no grupo "Avançado"), e o **desempenho** por câmera (kbps, fps, tempo no ar,
  espectadores) não aparece na área nova nem no app do cliente (o cliente tem `Bitrate` só na tela
  "Produção").

**Correção.**
1. Na embarcação, abrir a saúde do último retrato: o semáforo (`LIMIARES_DE_SAUDE`), **cada métrica com o
   número**, o que está fora do limiar e o "o que fazer" — lido do mesmo `/api/saude-do-bordo`.
2. No cartão da câmera: o desempenho do envio (kbps declarado × medido, fps, tempo no ar, espectadores) e o
   `encoder` real.
3. O bordo passa a mandar a **versão do app** no retrato (hoje `versao_app` vem vazio) — é pré-requisito de
   qualquer diagnóstico de campo.
4. **Achado de segurança medido nesta rodada (P0):** `GET /api/empresas` devolve a **chave da licença
   inteira** no bloco `maquinas[].licenca` (medido: `R8B2-78NM-C11Z-VR9U`). O papel `observador` (Petrobras) vê
   essa rota. A chave nunca deve sair inteira — só os 4 últimos dígitos, como já faz
   `_licenca_da_embarcacao` (`api.py:871-878`).

**Provas.** `tests/e2e-saude-e-desempenho-na-area.py` (novo) + a rota conferida sem a chave inteira.

## Fase 3 — contagem regressiva, aviso antes de cortar e "reconectar" (P1)

**Causa medida — CORRIGIDA em 24/11/2026 com a tela do dono na mão (print do cliente `clientes@lecsor.test`).**
O app do cliente (`app/app.js`) tem **duas telas separadas** e as coisas que o dono pediu estão na que ele
NÃO usa:

- **`Visualizar` → "Transmissões ao vivo"** (a tela do print, a que o cliente abre): a grade de câmeras, com
  `Baixar 1 minuto` e `Destaque` por janela (`app.js:168-251`). **Não tem contador, não tem botão de gravar,
  não tem começar/parar transmissão** — nada disso é desenhado aqui.
- **`Transmitir` → "Transmitir"** (`TELAS.transmissao`, `desenharTransmissao`, `app.js:908-960`): é lá que
  existem `Iniciar transmissão`, `Parar transmissão`, `Gravar (no lado terra)` e a linha
  `· tempo restante mm:ss` (`app.js:933`, de `segundos_restantes`, `api.py:2081-2088`).

Ou seja: o dono está certo — **na tela que ele usa (a grade) não existe nada disso**. Além disso, em lugar
nenhum do produto existe:
- **aviso antes de cortar** (a sessão expira e o cliente só lê "parada: o tempo acabou");
- **"reconectar"** (`grep -c reconect app/app.js` = 0);
- contador de tela (o "tempo restante" é uma linha de texto, dentro da outra tela).

**Correção (tudo na tela que o cliente usa — a `Visualizar`).**
0. As duas telas viram uma: o `Visualizar` ganha os controles de transmissão (começar/parar, gravar) e o
   painel de tempo por câmera no próprio cartão/janela; a tela `Transmitir` deixa de ser o único lugar onde a
   transmissão existe (ou some, se o dono preferir).
1. Contador visível (mm:ss grande + barra), com o tempo total e o que ele significa.
2. No **último 1 minuto** (`AVISO_SEGUNDOS = 60`, decisão D1), a mensagem "quer continuar conectado?" com
   **Continuar** e **Não**; "Não" **ou silêncio** (o cliente não agir no aviso, decisão D2) ao fim do minuto →
   encerra a sessão (a flag vira `parar` e o bordo para). Continuar exige o clique.
3. Depois de encerrar: botão **"Reconectar"**, que abre de novo o mesmo tempo configurado.
4. Nada disso muda o teto do produto: os tempos continuam a lista fechada
   `TEMPOS_DE_TRANSMISSAO = (300, 900, 1800, 3600, 7200)`.

**Provas.** `tests/e2e-contagem-aviso-e-reconectar.py` (novo), com relógio controlado: o aviso aparece;
"Continuar" renova; "Não" corta; silêncio corta no prazo; "Reconectar" põe a câmera no ar de novo.

## Fase 4 — gravação a partir do cliente (P1)

**Causa medida (mesma correção de tela da Fase 3).** O botão **existe, mas na outra tela**: "Gravar (no lado
terra)" está em `desenharTransmissao` (`app/app.js:948-951`, rota `POST /api/transmissao/<id>/gravando`), a
tela `Transmitir` — **não** na `Visualizar`, que é a tela do print e a que o cliente abre. Ele ainda só
aparece quando existe sessão **do próprio** cliente (`minha`). Escopo decidido (D4): **só o que chegou** — a
gravação do cliente é o vídeo que já está no terra; **nada** de gravar no PC de captura pelo cliente.

**Correção.** Trazer o botão para a tela que o cliente usa, junto do contador (Fase 3), com rótulo e estado
óbvios; e, se o dono quiser, abrir a gravação no PC de captura com as travas do produto (retenção é anel de
disco; nenhum vídeo sobe sem pedido).

**Provas.** `tests/e2e-gravacao-no-cliente.py` (novo): o botão aparece com a sessão, grava, o estado volta, e
o arquivo é listado para download.

## Fase 5 — provas, deploy e release (P0)

1. `tools/regressao-0100.py` verde (21 provas) + os 4 testes novos.
2. Deploy do terra (`git show HEAD:<f>` LF + `scp` + `py_compile` + `chown` + `restart`, com backup) e
   conferência de md5.
3. Release nova (0.12.1 se só correção de terra; 0.13.0 se o bordo também mudar — o item 3 da Fase 2 muda o
   bordo).
4. Nota no vault + `index.md`.

## Arquivos previstos

- `ground/api.py` (`_desejo_das_cameras`, rota `/api/cameras/ligar`, `_saude_resumida`/retrato, `arvore_do_painel`
  sem a chave inteira, `versao_app` do bordo, `AVISO_*`);
- `ground/agente_de_ordens.py` (mandar a versão do app no retrato de saúde);
- `app/app.js` (+ `app/index.html`/`fronts/vms.css` se a tela precisar): contador, aviso, reconectar, gravar;
- `admin/admin.js` (+ `fronts/admin.css`): saúde com números, desempenho no cartão, sem a chave inteira;
- `tests/e2e-flag-de-audiencia.py`, `tests/e2e-saude-e-desempenho-na-area.py`,
  `tests/e2e-contagem-aviso-e-reconectar.py`, `tests/e2e-gravacao-no-cliente.py`;
- `README.md`, `desktop/package.json`, `tools/publicar-releases.py` (a versão).

## Decisões do dono (24/11/2026, verbatim)

> D1. 1 minuto
> D2. o que é silêncio? se o cliente não tomar ação no aviso de espera? se for, desliga
> D3. não tem ligar agora do admin, só quem visualiza é o cliente
> D4. só o que chegou

- **D1 = 1 minuto de aviso** antes de cortar (o `AVISO_SEGUNDOS` = 60 s). "Silêncio" (D2) = o cliente não
  tomar ação no aviso → **desliga** ao fim do minuto (o padrão é cortar; continuar exige o clique).
- **D2 = sem resposta no aviso, desliga.** O aviso oferece "Continuar"; sem clique em 1 min → encerra.
- **D3 = o "ligar agora" do admin NÃO existe** (decisão de produto): quem liga é **só o cliente que está
  visualizando**. O botão que a área nova ganhou em 23/11/2026 (`admin/admin.js:2418`, "ligar agora") e o
  `manual='ligar'` que ele grava (`ground/api.py:3635`) **saem**; a flag passa a ser sustentada só por sessão
  viva (qualquer computador).
- **D4 = só o que chegou** — a gravação do cliente é o vídeo que já chegou no terra (como hoje em
  `POST /api/transmissao/<id>/gravando`); nada de gravar no PC de captura pelo cliente.
