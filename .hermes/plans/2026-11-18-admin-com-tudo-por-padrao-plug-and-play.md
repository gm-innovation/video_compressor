# Admin com tudo por padrão (plug & play) — 18/11/2026

## O que o dono disse (VERBATIM)

- "mas não é pra ser assim, não devo precisar ficar fazendo essas alterações. o admin tem acesso a
  tudo. já deve ter por padrão todas as autorizações".
- (anteriores, mesma linha) "quando formos instalar isso no cliente, ele precisa instalar por completo,
  precisa ser plug & play... isso que você falou já deve ir configurado no instalador!".

## O que aconteceu hoje (verificado, não suposto)

- `%APPDATA%\LECSOR\config.json` ficou com `base: http://127.0.0.1:8765` (loopback) e
  `capturaLocal: false`; o banco local `%APPDATA%\LECSOR\pipeline.db` tem a tabela `usuarios` com
  **0 linhas** → a tela de entrada responde **"e-mail ou senha invalidos"** para `admin@lecsor.test`
  (a conta existe só na base do lado terra).
- O item de menu **"Subir servidor nesta maquina"** é o único jeito de fazer o servidor local subir e,
  quando `capturaLocal` é falso, ele **troca a base** para o loopback (código: `desktop/configuracao.js`,
  `if (config.servidorLocal.ligado) { ... else if (config.base !== local) config.base = local }`).
- O item que faz o certo — **"Liberar as funcoes de captura nesta maquina (sem trocar de app)"**
  (`desktop/main.js`, `capturaLocal`) — é um *checkbox* que o admin tem de descobrir.
- A máquina **tem** câmera e o servidor local a enxerga (`ACER HD User Facing` + microfone, máquina
  `Engenharia01`, resposta de `http://127.0.0.1:8765/api/dispositivos`).
- Estado de fábrica do papel `unico` (`desktop/papeis.json`): `servidorLocal.ligado: false`, **sem**
  `capturaLocal` → é exatamente o caso que gera a confusão.

## Fase 1 — O papel `unico` já nasce com a captura liberada · P0

1. `desktop/papeis.json` (papel `unico`) → `servidorLocal.ligado: true` e `capturaLocal: true`.
2. `desktop/configuracao.js` (PADRAO) → aceitar `capturaLocal` do papel, e no `resolver`:
   `capturaLocal` verdadeiro **nunca** deixa a base virar loopback (já é o comportamento; vira regra
   explícita e testada).
3. Efeito no cliente: instala o app, entra com o admin, e as funções de captura **já estão** liberadas
   (o servidor local sobe junto com o app); nenhum menu precisa ser tocado.

## Fase 2 — Nenhum item de menu troca a base por acidente · P0

1. O item que sobe o servidor local passa a **subir com `capturaLocal`**, com rótulo explícito:
   *"Subir o servidor local nesta maquina (captura — as telas e o login continuam no lado terra)"*.
2. Se por qualquer caminho o servidor local subir com `capturaLocal` falso, a caixa de aviso diz, em
   letras grandes, que **a base mudou para esta maquina** e que o login passa a vir do banco local
   (com o botão "voltar para o lado terra").
3. O item de checkbox "Liberar as funcoes de captura nesta maquina" continua existindo para quem quer
   ligar/desligar depois — mas deixa de ser obrigatório.

## Fase 3 — Login impossível não pode parecer senha errada · P1

1. Quando a base for loopback e o banco local **não tiver usuários**, a tela de entrada diz o que é:
   *"esta instalacao esta falando com o servidor LOCAL desta maquina (127.0.0.1:8765), que nao tem
   usuarios cadastrados"*, com o botão **"voltar para o lado terra"** (grava `base` de fábrica).
2. O mesmo aviso quando a base loopback não responde (hoje: "O lado terra nao respondeu" tentando
   `127.0.0.1:8765`, que é confuso — o lado terra é a VPS).
3. Auditoria local: grava o evento (data, base tentada) para dar para ver depois.

## Fase 4 — Config antiga se corrige sozinha · P1

1. No boot, config com `base` loopback + `servidorLocal.ligado: false` (ou `capturaLocal` ausente)
   volta para o padrão do papel, com registro no log do app (hoje o `resolver` só corrige quando o
   servidor local está ligado).
2. Nada de "primeiro acesso" nem de criar usuário local em instalação já existente.

## Fase 5 — Provas · P0

1. Teste de unidade do `resolver` com as 4 combinações (`ligado` × `capturaLocal`) provando que a base
   só vira loopback no caso antigo, e que o padrão novo mantém a base no lado terra.
2. Prova de tela no Electron real com config de fábrica: abre o app → entra com o admin → a captura
   já funciona sem tocar em menu (mesmo caminho do `test-camera-tamanho-suportado.py` para o vídeo).
3. `python tests/test-app-no-celular.py` e a suíte completa verdes antes de publicar.

## Estado da implementação (18/11/2026 — autorizado pelo dono: "corrija esse negócio no código")

- **Fase 1 — FEITA.** `desktop/papeis.json` (papel `unico`): `servidorLocal.ligado: true` +
  `capturaLocal: true`. `desktop/configuracao.js`: o PADRAO/papel decide `capturaLocal`, e o papel que
  declara captura **força** `capturaLocal`/`servidorLocal.ligado` mesmo contra config velha da máquina
  (item 7 e 8 do resolver).
- **Fase 2 — FEITA.** O item de menu virou *"Subir o servidor local nesta maquina (captura — as telas e
  o login continuam no lado terra)"*: ele **libera a captura e não troca a base**; se a base estiver em
  loopback, volta para a do papel. A troca de base continua existindo só como preset explícito
  (*"Papel desta instalacao → Usar como PC de captura"*).
- **Fase 3 — FEITA (parcial no item 3).** `ground/api.py`: 401 de `/api/entrar` numa instalação local
  **sem usuário nenhum** diz o que falta e devolve `primeiro_acesso`/`base_local` (não acusa a senha);
  `entrada/entrada.js` abre o formulário do primeiro administrador nesse caso; `desktop/main.js`
  (`paginaDeErro`) distingue **"O servidor LOCAL desta maquina nao respondeu"** do lado terra e diz
  qual é o lado terra desta instalação. O item 3 (auditoria com a base tentada) já existia como
  `entrada_falha` na auditoria — nada novo a fazer.
- **Fase 4 — FEITA.** O resolver corrige no boot: base loopback com `servidorLocal.ligado: false` (ou
  `capturaLocal` ausente/falso) volta para a base de fábrica do papel, com `corrigido: true` (é o que o
  `main.js` usa para regravar o config).
- **Fase 5 — FEITA (provas).** `tests/test-config-endereco.py` ganhou a seção 5 (3 casos do app `unico`
  + o `papeis.json` real) e trocou a checagem do menu; `tests/test-entrada-instalacao-vazia.py` (novo)
  prova a API de verdade com banco temporário vazio; `tests/test-app-unico-por-papel.py` e
  `tests/test_captura_no_admin.py` foram atualizados (codificavam a decisão antiga: "o pacote único
  NÃO nasce subindo servidor local" — o dono revogou isso em 18/11/2026).
- **Falta (não bloqueia):** a prova de tela no Electron real (Fase 5.2) e a suíte completa antes de
  publicar o instalador.

## Fora de escopo (não pedido)

- Simplificar a tela "Enviar vídeo" (o dono só perguntou o que é cada bloco; não pediu para mexer).
- PWA do cliente.
