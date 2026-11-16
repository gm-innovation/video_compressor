# Seleção de qualidade por câmera: 1500k / 1200k / 1000k / 800k / 500k / 300k

**Status:** aprovado ("aprovado", 16/11/2026) — **IMPLEMENTADO na 0.4.0** em 16/11/2026: as 9 fases no ar na VPS (187.127.60.250:8085), 4 instaladores 0.4.0 em `desktop/dist/`, provado por `test-selecao-de-qualidade.py` e `test-remover-e-editar-camera.py` (rc=0) e por chamada real na VPS (422 para alvo fora da lista, 800k aceito, editar rótulo, remover -> sumiu, remover de novo -> 404).
**Autor:** Hermes (a pedido de Alexandre) · **Data:** 16/11/2026 10:50
**Pedido (verbatim):** *"vamos fazer um sistema de seleção de qualidade, as imagens de cada câmera podem ser
enviadas a 1500k/1200k/1000k/800k/500k/300k, a seleção deve ser individual, cada câmera pode ter uma taxa de
envio selecionável"*
**Repo:** `C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video` (branch `main`, base **0.3.0**)

## O que JÁ existe (medido no código, 0.3.0)

- O alvo é **por câmera**: coluna `cameras.alvo`, gravada no cadastro e usada no encode
  (`alvo_da_camera`; **o alvo da câmera tem prioridade sobre o último envio** — `ingestao.py:529`).
- Existe `POST /api/cameras/<id>/alvo` (operação/admin; 403 para o cliente) e a tela do Admin já tem
  um campo **Alvo** por câmera (`admin/admin.js:435`) que grava esse número.
- **O que falta:** (a) o campo é **texto livre** (`^[0-9]{2,6}k?$`) — qualquer número passa, não a lista
  fechada dos 6 níveis; (b) gravar o alvo **não reabre o encode daquela câmera** — só vale no próximo
  envio (a tela parece que mudou e o vídeo continua no alvo antigo); (c) não há a "seleção" como escolha
  (lista/controle), só um campo de digitação; (d) o valor medido abaixo do piso hoje dispara *sugestão de
  subir* (`alvo_sugerido` = 1,5×), o que briga com a ideia de o dono poder **escolher** cair.

## Fase 1 — P0: a lista fechada e por câmera

1. Lista fixa e única no servidor: `1500k`, `1200k`, `1000k`, `800k`, `500k`, `300k` (whitelist em
   `POST /api/cameras/<id>/alvo`); fora da lista → **422** com a lista na mensagem. Nada de texto livre.
2. Seleção **individual**: cada câmera tem o seu alvo; mudar uma não toca nas outras (o `UPDATE` é por
   `WHERE id=?`, já é assim — o que muda é a validação e a aplicação).
3. A lista também é o que a tela mostra: 6 opções por câmera, com o alvo atual marcado.

## Fase 2 — P0: a escolha tem de valer NO AR (é o furo de hoje)

4. Ao gravar o alvo, **reabrir o encode daquela câmera** com o novo alvo (mesmo caminho do
   desligar/ligar câmera, sem mexer na fonte): interrupção de ~2 s só naquela câmera, o resto segue.
5. A resposta da API diz o que aconteceu: alvo aplicado, se reabriu e o que ficou no ar; e o atestado/
   declarado passam a refletir o novo número (a declaração já sobe a cada 30 s).
6. Se a câmera estiver parada, só grava (aplica quando subir) — e a tela diz isso.

## Fase 3 — P1: onde se escolhe

7. **Captura** (PC do barco, que é quem comprime): seletor por câmera, com o efeito explicado na tela
   (quantos kbps vão sair e que a imagem reinicia por ~2 s).
8. **Admin/operação**: a mesma seleção, para ajustar sem subir no barco; se o caminho terra→bordo pedir
   o ciclo de declaração, a mudança chega em **até 30 s** (o bordo já anuncia nesse intervalo).
9. **Cliente continua sem ver nem escolher alvo** — o cadastro publicado leva só id/rótulo/fluxo/ativo
   (regra que já vale; nada de endereço, porta ou taxa).

## Fase 4 — P1: o piso deixa de brigar com a escolha

10. Abaixo de 1500k o sistema **mede e avisa** ("SSIM abaixo do piso: 0,87 em 300k") em vez de só sugerir
    subir; a escolha é do dono e fica registrada na auditoria (`definir_alvo_camera` já existe).
11. O medido que já temos vira a régua da tela: 1500k → SSIM ~0,98; 1200k ~0,97; 1000k ~0,95;
    800k ~0,93; 500k ~0,90 (0,8950 cam-01 / 0,9248 cam-02); 300k ~0,87/0,89 — tudo isso **contra a fonte
    já comprimida**, então a tela deve dizer de onde vem o número.

## Fase 5 — P1: provas e entrega

12. Teste novo `tests/test-selecao-de-qualidade.py`: as 6 opções aceitas, qualquer outro valor → 422;
    duas câmeras com alvos diferentes continuam diferentes; o cliente não muda alvo (403); a mudança
    **reabre** o encode daquela câmera e o kbps que chega ao lado terra acompanha o alvo novo.
13. Seção nova no plug-and-play; deploy do lado terra na VPS; release **0.4.0** (4 instaladores; a
    Captura precisa ser reinstalada no barco porque quem reabre o encode é ela).

## Respostas do dono (16/11/2026)

- **A) "captura e admin"** — a seleção de qualidade vale nos DOIS: na Captura aplica na hora, no Admin
  remoto chega em até 30 s (o bordo já anuncia nesse intervalo).
- **B) "só avisa"** — abaixo do piso de qualidade o sistema **só avisa**; nunca recusa o nível escolhido.

## Fase 6 — P0: remover câmera que não é mais usada

14. Hoje **não existe remoção**: só `/api/cameras/<id>/ativo` (desativar/reativar), que tira a câmera da
    tela do cliente mas mantém o cadastro. Entra `POST /api/cameras/<id>/remover` (operação/admin):
    apaga o cadastro **e** publica a remoção no lado terra (`repasse.publicar_cadastro` — a câmera some da
    tela do cliente na hora, sem depender de o bordo anunciar de novo).
15. Se a câmera estiver no ar, a remoção **para o envio** dela antes de apagar (mesmo caminho do
    desligar) — nada de processo órfão segurando a fonte.
16. Remoção **não apaga histórico**: trechos e auditoria continuam; quem removeu fica na auditoria. A
    câmera removida não volta sozinha no próximo anúncio do bordo.
17. Guarda contra acidente: confirmação na tela e a câmera sai da lista sem levar os trechos já gravados.

## Fase 7 — P0: editar câmera em operação

18. Hoje `POST /api/cameras` é `INSERT OR REPLACE` (recria a linha e **zera `ativo`**) — serve para criar,
    não para editar com segurança. Entra `POST /api/cameras/<id>/editar` (operação/admin) que altera **só
    os campos enviados** (rótulo, embarcação, endereço/porta/canal quando for o caso) e **não reseta**
    `ativo`, `alvo` nem a publicação no lado terra.
19. Se a edição mexer na fonte/endereço da câmera, o envio dela é reaberto (mesmo caminho da troca de
    alvo): a edição tem de valer no ar, não só na lista.
20. Auditoria campo a campo (`editar_camera`) e recado na tela dizendo o que mudou e o que foi reaberto.

## Fase 8 — P1: uma ou várias câmeras em destaque (tela do cliente)

21. Hoje só existe **tela cheia do palco inteiro** (`btn-cheia`); a seleção por câmera (`S.selecionadas`)
    não abre destaque. Entra: **tela cheia de UMA câmera** e **modal com 2–4 câmeras em destaque**, com
    botão de voltar à grade.
22. Só quem tem a câmera no contrato pode destacá-la (mesma regra de `pode_ver_camera`); nenhuma tela
    mostra endereço, porta ou credencial.
23. O destaque é **só de tela**: não muda banda nem resolução — isso é a seleção de qualidade por câmera
    (Fases 1–2) e é da operação.

## Fase 9 — P1: provas

24. `tests/test-remover-e-editar-camera.py`: remover tira a câmera do lado terra e **não** apaga trechos;
    editar preserva `ativo` e `alvo`; cliente não remove nem edita (403); remover câmera no ar para o envio.
25. Teste do destaque (1 e 4 câmeras) + seção no plug-and-play; deploy do lado terra na VPS; release
    **0.4.0** (4 instaladores).
