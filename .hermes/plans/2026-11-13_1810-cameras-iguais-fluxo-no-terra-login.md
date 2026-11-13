# Plano 0.2.2 — correções da instalação real no PC do cliente (2ª rodada)

Data: 2026-11-13 · Alvo: release **v0.2.2** · Base: `origin/main = f7f360d` (0.2.1)

## O que a instalação real mostrou (medido, não suposto)

1. **Duas câmeras USB idênticas não coexistem.** `listar_dispositivos()` (`ground/ingestao.py:530-535`) lê só o nome
   amigável do dshow e **descarta o "Alternative name"**; duas câmeras iguais viram a mesma string. Ao transmitir,
   `ao_vivo()` (`ingestao.py:614-618`) chama `_camera_em_uso(dispositivo)`, casa **pelo nome** e recusa a segunda com
   "a webcam ... ja esta em uso pelo fluxo ...".
2. **O cliente não vê o vídeo que chega.** No VPS, `vivo-usb-video` está online no mediamtx (1920x1080 H264, 203.431.133 B
   recebidos, `readers: []`), mas `fluxos()` (`api.py:310-320`) e `GET /api/cameras` (`api.py:738-770`) iteram **somente**
   linhas de `cameras` — um fluxo vivo sem linha é invisível. O banco do VPS só tem `cam-01-demo`…`cam-04-demo` e
   `vps-webcam-bancada`. Os `readers: []` provam que o app do cliente não pediu o fluxo.
3. **Login obrigatório e desvinculado do cliente.** `POST /api/entrar` (`api.py:841-858`) só entra se existir a linha em
   `usuarios` **local** (`entrou = ... and bool(alvo)`); veredito positivo do Supabase sem linha local é recusado. O
   instalador não leva `LECSOR_SUPABASE_URL/ANON_KEY` (nenhum `.env` no pacote) → o Supabase nem é consultado e o login
   é local puro. O primeiro acesso (`api.py:864-894`) grava `cliente_id=NULL`.
4. **Usuário de teste recusado em outra máquina.** Mesma regra da linha local; o banco do VPS
   (`/opt/pipeline/app/db/pipeline.db`) tem os 4 usuários e o `.env.local` com as chaves Supabase — logo aquele app não
   falava com o VPS (qual base ele usava: **não sei**).

---

## Fase 1 — Duas câmeras USB idênticas (P0)

**P0 — identidade por dispositivo, não por nome.**

- `listar_dispositivos()` passa a parear cada `"nome" (video)` com o **"Alternative name"** da mesma seção
  (`@device_pnp_...`), que é único por dispositivo; a lista `video` continua com o nome amigável para a tela, e um novo
  campo `seletores` traz, por câmera, o seletor único de `ffmpeg` (`video=@device_pnp_...`).
- `_args_fonte_viva()` (`ingestao.py:543-550`) usa o seletor único quando existir; mantém `video=<nome>` como hoje
  quando só houver um dispositivo com aquele nome.
- `_camera_em_uso()`/`liberar_camera()` passam a comparar pelo **seletor**, não pelo rótulo — duas câmeras iguais deixam
  de bloquear uma à outra.
- A tela mostra "USB Video Device (1)" / "(2)" quando os nomes repetem, para o operador distinguir.

**Prova:** teste que roda `-list_devices` sobre duas câmeras lógicas com o mesmo nome (ou fixture com a saída real
capturada) e exige **duas** entradas distintas, dois seletores distintos e dois envios simultâneos aceitos.

## Fase 2 — O fluxo que chega no lado terra aparece para o cliente (P0)

**P0 — auto-provisionamento do bordo no lado terra.**

- Nova rota (ou extensão de `POST /api/cameras`, autenticada por `LECSOR_TOKEN_INGESTAO`) para o **PC de captura
  anunciar** ao lado terra: `fluxo_id`, rótulo, embarcação. Ao publicar (`repasse.py`), o bordo anuncia uma vez.
- `GET /api/cameras` passa a **listar também** os caminhos online do mediamtx que não têm linha em `cameras`
  (`fonte = "bordo"`, rótulo = nome do fluxo) — assim um fluxo que chega aparece mesmo sem cadastro manual; a linha
  automática é promovida a câmera de verdade quando o anúncio chega.
- O painel **Tempo real** e a coluna "Espectadores" deixam de ficar em `readers: []` quando há cliente assistindo.

**Prova:** com o `vivo-usb-video` online no VPS, `GET /api/cameras` (login do cliente de teste) devolve a câmera com
`no_ar: true`; um WHEP do app cliente sobe `readers` para ≥1.

## Fase 3 — Vínculo ao cliente/embarcação (P0)

**P0 — o admin novo não pode nascer solto.**

- Primeiro acesso (`api.py:864-894`): se **houver** Supabase configurado, o primeiro acesso **valida no Supabase** e
  usa o `cliente_id` do perfil; só cria admin local quando a instalação é de bancada sem Supabase.
- Tela de primeiro acesso ganha (opcional) cliente/embarcação quando não houver perfil remoto.

**Prova:** instalação limpa com Supabase → primeiro acesso com `admin@lecsor.test` gera linha local com o mesmo
`cliente_id` do Supabase.

## Fase 4 — Login com Supabase na máquina instalada (P1)

**P1 — o instalador precisa saber com quem falar.**

- `LECSOR_SUPABASE_URL` e `LECSOR_SUPABASE_ANON_KEY` entram no pacote por **ambiente do processo do servidor** (nunca no
  cliente nem no Git), gravados em `%APPDATA%\<app>\supabase.env` na primeira execução a partir do papel do build.
- `POST /api/entrar`: veredito **positivo** do Supabase e **sem** linha local passa a **criar/atualizar** a linha local
  a partir do perfil (nome, papel, cliente_id) — hoje isso é recusado.
- Veredito **negativo** do Supabase continua caindo para a rede de proteção local (bancada sem rede).

**Prova:** em máquina instalada sem linha local para `operacao@lecsor.test`, o login entra com papel `operador` e cria
a linha local; senha errada continua 401.

## Fase 5 — Prova, empacotamento e entrega (P1/P2)

**P1 —** testes `tests/test-instalador-plug-and-play.py` (seções novas 16-18) + `tests/suite.py` verdes.
**P1 —** novo instalador 0.2.2, release no GitHub, vault atualizado com a nota da rodada.
**P2 —** `INSTALAR-PC-DE-CAPTURA.md` com o passo "duas câmeras iguais" e "por que o cliente não via o vídeo".

## Fora deste plano

- Qualidade do vídeo no PC real do cliente (mede-se com a câmera verdadeira; na bancada fica pendente).
- Escalar para N embarcações (segue o caminho depois do 1º bordo real).
