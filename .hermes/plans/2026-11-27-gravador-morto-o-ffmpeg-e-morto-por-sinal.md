# 2026-11-27 — Gravador de bordo: o ffmpeg é morto por sinal (5x) e o laço morre em seguida

Status: **diagnóstico fechado; correção NÃO implementada** (aguarda decisão do dono).
Dono: incidente de 27/11/2026 — app de captura: *"radar - parado - 5 bloco(s) no HD - a gravação
full-time está ligada (desejo do admin), mas o gravador NÃO está de pé - nada está sendo gravado"*.

## 1. O que os arquivos do dono mostram (medido, não deduzido)

Fonte: `D:\gravador.log`, `D:\gravacao-continua.log`, `D:\gravador.pid`, `D:\ligada.txt` e os
5 blocos `D:\bloco-20261127-1320{11,15,19,25,29}.mp4` — todos conferidos por leitura direta.

- `gravador.log` (162 linhas) = **5 execuções do ffmpeg**, e **todas** as 5 terminam com
  `Exiting normally, received signal 15.` (linhas 34, 66, 98, 130, 162). **Nenhum** erro de
  dispositivo, de encoder ou de disco. Ou seja: ninguém "falhou" — **o ffmpeg foi morto**.
- Cada execução grava ~1 s (`frame= 32 ... time=00:00:01.06`) e morre; a seguinte abre a MESMA
  câmera (`video=@device_pnp_\\?\usb#vid_345f&pid_2131...`, 1280x720@30, mjpeg→h264,
  1500 kbps, `-f segment` para `...\ground\hd\bloco-*.mp4`).
- `gravacao-continua.log` (7 linhas, completo): o laço sobe às **13:20:08** (pid 12096), publica o
  "no ar" às 13:20:09 e **reergue o ffmpeg 5 vezes** — 13:20:10 (pid 12456), :14 (11388), :18
  (12360), :24 (968), :28 (9824). O laço estava funcionando.
- O laço morre em seguida, e **morreu calado**: não há a linha `DESLIGADA pelo desejo da tela:
  saindo` (que o `rodar()` escreve ao sair pelo desejo) nem `gravador parado a pedido` (do
  `_parar_gravador()`), e o **`gravador.pid` não foi removido** (`_parar_gravador()` remove).
  Hoje o pid 12096 **não existe mais** e não há nenhum ffmpeg rodando: **nada está gravando.**
- `ligada.txt` = `"1"` → o desejo do admin está LIGADO (o lado terra não desligou nada).
- Soma dos 5 blocos = **1 749 888 B** (350 KB cada, ~1 s de vídeo) — exatamente o que o retrato
  do bordo publicou. `gravando_agora()` = "não está de pé" está **correto**: a MEDIDA está certa;
  o que morreu foi a gravação.

## 2. Causa (código, verificado no repositório)

Gravador e transmissão ao vivo disputam **a mesma câmera** (a do radar, `vid_345f&pid_2131`), e é
o próprio app que tira a câmera do gravador:

1. `ground/ingestao.py:1119-1127` (`iniciar()`, tipo `camera`): antes de abrir a câmera, pergunta
   `_camera_em_uso()` — que **só olha a tabela `ingestoes`** — e, como não há envio vivo, chama
   `liberar_camera(dispositivo)`. Essa função (linha 1179) mata **qualquer** processo cuja linha de
   comando contenha `video=<câmera>`: o ffmpeg do gravador usa **exatamente esse dispositivo**.
   O comentário da própria função diz que ela existe para soltar "processo preso" — o gravador é
   tratado como processo preso.
2. `ground/ingestao.py:583` (`parar()`): `os.kill(pid, signal.SIGTERM)` — **é o "signal 15"** que
   aparece no `gravador.log`.
3. `ground/gravacao.py:92` e `ground/gravacao_continua.py:153` também matam por pid (taskkill).
4. As 5 mortes são **16:20:11Z→16:20:31Z**, e a **primeira ordem do cliente é 16:20:44Z** (seq 531,
   `iniciar` da câmera `vid_345f&pid_2131`). Logo, as 5 mortes **não** vieram de clique do cliente:
   o app já estava tentando subir a câmera sozinho (vigia/retry) e matando o gravador em cada
   tentativa. As ingestações daquela máquina ficaram em `erro` com `processo: NoSuchProcess`
   (inclusive a do radar `vid_345f&pid_2131`) — o vivo e o gravador se derrubando um ao outro.

Resumo: **não é problema de HD, de cota, de disco escolhido nem de encoder** (a 0.28.1 está
instalada e a telemetria está certa). É conflito de **dono da câmera**: o vivo abre a câmera e,
para isso, mata o gravador.

## 3. Correção proposta (por fases; nada implementado até "aprovado")

- **Fase 1 (P0, a causa) — o gravador não pode ser morto pelo app.** `liberar_camera()` passa a
  **excluir o processo do gravador** (casar a linha de comando do gravador/laço e nunca matá-lo) e
  `_camera_em_uso()` passa a enxergar o gravador (não só a tabela `ingestoes`). Aceite: com o vivo
  do radar ligado, o `gravador.log` fica **sem nenhum `signal 15`** por 1 h e os blocos continuam
  fechando de 60 em 60 s.
- **Fase 2 (P0, o desenho) — dono único da câmera.** A câmera do radar pertence ao gravador
  (é ele quem grava full-time, por decisão do dono). O vivo do radar passa a ser servido **pelo
  próprio gravador** (relay local — o caminho já estudado do proxy/mediamtx), em vez de abrir a
  câmera do zero. Aceite: cliente assistindo o radar e gravador fechando blocos **ao mesmo tempo**.
- **Fase 3 (P1) — supervisor do laço.** Hoje o app só sobe o laço quando o desejo é ligado; se o
  laço morre (foi o que aconteceu às 13:20:29), ninguém o reergue. O app passa a reerguer o
  gravador ao menos uma vez por varredura. Aceite: matar o pid do laço à mão e vê-lo voltar sozinho
  em ≤ 1 varredura.
- **Fase 4 (P2) — rastro no log.** Toda morte de ffmpeg provocada pelo app deve deixar linha no
  `gravador.log` (hoje o kill é invisível: só sobrou o `signal 15` do lado do ffmpeg).

## 4. O que ainda falta para fechar 100% do diagnóstico

- O log do **próprio app** de captura (stdout/stderr da instalação) na janela de 13:20 — é onde o
  `iniciar()` imprime `[envios] liberei a webcam "...": N processo(s) parado(s)`; essa linha
  identifica o matador sem inferência.
- Confirmar se o app foi fechado/reiniciado por volta de 13:20:31 (o laço morreu calado e o pid
  não foi removido — ninguém saiu pelo caminho normal do produto).

---

# SEGUNDO ITEM (pedido do dono, 27/11/2026) — "admin > empresas e configuração: altero a qualidade, aplico e ela não persiste, volta a anterior" (3ª vez que é pedido)

Status: **causa MEDIDA no banco de produção; correção NÃO implementada** (aguarda decisão).

## 5. O que a medição mostra (banco real da VPS, 27/11/2026)

- `config_bordo` (o que o admin **publicou**): `bancada` / radar `cam-...vid-345f-pid-2131...` =
  `alvo_kbps 1500` **v4** (25/11 19:15Z); `cam-...vid-534d-pid-2109-...-37f` e `...-253` =
  `alvo_kbps 500` **v7** (27/11 16:42Z). Ou seja: **a publicação do admin GRAVA**.
- `config_aplicada_bordo` (o que o **bordo confirmou**): `500` **v7** para as duas `534d`
  (16:42:33Z) e `1500` **v5** para o radar — **o bordo aplica e confirma**.
- `cameras` (lado terra): **`alvo` = `''` em TODAS as 9 câmeras** — inclusive no radar e nas duas
  `534d` cujo `alvo_kbps` está publicado e aplicado em v7.
- `admin/admin.js:3442-3456`: o menu da qualidade é preenchido com `c.alvo` (o campo da tabela
  `cameras` do lado terra) e, quando ele está vazio, o `sel.value` cai na **primeira opção**
  (`ALVOS_DE_ENVIO[0]` = "3000 kbps (padrão do produto)"). Depois do `aplicar qualidade`
  (`POST /api/config`), a tela refaz o cartão (`refazerCartao`) lendo de novo `cameras.alvo` —
  que continua `''` → **o menu volta para "3000 kbps"**: é exatamente o "retorna a anterior".
- `ground/api.py:1395` — quem escreve `cameras.alvo` é o `aplicar_config_local()`, que roda **na
  máquina de captura** (rota local `/api/config/aplicar`, chamada pelo agente do bordo): o `alvo`
  que a tela do admin lê é o **anunciado pelo bordo**, e ele chega **vazio** ao lado terra.

**Conclusão medida:** o valor não se perde no servidor — ele está publicado (v7/500) e aplicado
(v7/500). Quem está errado é a **tela do admin**, que monta o menu a partir de `cameras.alvo`
(vazio) em vez da **configuração publicada**, e o **anúncio do bordo**, que não leva o `alvo`
efetivo para o lado terra.

## 6. Correção proposta (por fases; nada implementado até "aprovado")

- **Fase 1 (P0) — a tela lê a config PUBLICADA.** O menu de qualidade do cartão da câmera passa a ser
  preenchido com o valor de `alvo_kbps` publicado (`/api/config?embarcacao_id=...`, a MESMA fonte
  que o painel de teto já usa — `recarregarCartaoDaEmbarcacao`), e não com `cameras.alvo`. Quando
  publicado ≠ aplicado, o cartão mostra o publicado com a marca "aguardando o bordo" (nada de
  mostrar valor velho como se fosse o escolhido). Aceite: aplicar 500 numa câmera e o menu
  **continuar mostrando 500 kbps** depois do redesenho (hoje volta a "3000 kbps").
- **Fase 2 (P0) — o bordo anuncia o `alvo` efetivo.** O `alvo` que o bordo aplica
  (`aplicar_config_local` → `cameras.alvo` no banco DESTA máquina) tem de viajar no anúncio/estado
  do bordo, para o lado terra parar de ver `cameras.alvo = ''`. Aceite: depois de aplicar, o
  `cameras.alvo` do lado terra fica `500k` para aquela câmera.
- **Fase 3 (P1) — prova de regressão.** Teste e2e que falha hoje: publicar `alvo_kbps`, recarregar a
  tela do admin e exigir que o menu da câmera continue com o valor publicado; e um teste de API que
  exige `cameras.alvo` do lado terra preenchido depois do anúncio do bordo.
- **Fase 4 (P2) — mesma verificação para as outras chaves por câmera** (`rotulo`, `tipo`) para não
  sobrar nenhuma tela lendo o campo "aplicado" como se fosse o desejado.
