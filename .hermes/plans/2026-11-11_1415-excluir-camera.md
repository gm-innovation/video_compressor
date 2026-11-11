# Excluir câmera pela tela — e limpar as câmeras de teste que não funcionam

**Status:** executado em 11/11/2026 (commit "Camera que nao funciona sai da tela sem perder o historico", `admin.js` publicado na VPS)

**Resultado:** bancada 14 → **5 câmeras** (as 4 demo do PSV + a Webcam bancada bordo→VPS); VPS 15 → **6**
( as mesmas + a Fonte da VPS, agora **desativada**); histórico órfão de 41 fluxos fora nos dois bancos
(bancada: 849 minutos; VPS: 129 ingestaões + 849 minutos). O cliente vê **1 janela** na bancada.
**Data:** 11/11/2026 · **Repo:** `C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video` (branch `main`) · **Escopo:** admin (tela Câmeras) + API + banco da bancada e da VPS

**Goal:** poder excluir pela tela do admin uma câmera que não funciona, e tirar da tela do cliente o
entulho de teste que hoje aparece como "nenhum envio registrado".

## O que existe hoje (evidência, não proposta)

| Fato | Onde |
|---|---|
| 14 câmeras cadastradas: 6 na bancada, 4 no "PSV Exemplo (demo)", 4 criadas por envios de teste | `db/pipeline.db` tabela `cameras` |
| A tela **Câmeras** do admin só tem **ativar/desativar** — não existe botão de excluir | `admin/admin.js:321` → `POST /api/cameras/<id>/ativo` (`ground/api.py:1144`) |
| O único caminho de remoção é `POST /api/ingestao/parar {id, remover:true}`, que só apaga câmera criada por um envio de teste | `ground/api.py:985` |
| O cliente vê toda câmera `ativo=1` da embarcação escolhida (6 janelas hoje; 5 sem envio registrado) | `GET /api/cameras?embarcacao=` |
| Das câmeras da bancada, só a `vps-webcam-bancada` tem envio (`no_ar`, 14:04) | tabela `ingestoes` |

## Decisões do dono (11/11/2026)

| Pergunta | Resposta |
|---|---|
| Botão da tela Câmeras | **só desativar** (some da tela do cliente, histórico fica) — não haverá botão de excluir na tela |
| Câmeras da bancada | manter só `vps-webcam-bancada` (a que funciona) e **excluir as 5** de teste |
| Câmeras demo (PSV Exemplo) e envios de teste | **manter as 4 demo**, excluir só os **4 envios de teste** |
| Onde aplicar | **bancada e VPS** |

## Fase 1 (P0) — desativar resolve, e fica claro na tela

- **P0** A tela Câmeras passa a mostrar a coluna **Situação** (no ar / fora do ar / desativada) e o
  botão diz o que faz ("desativar" quando ativa, "ativar" quando desativada), com confirmação —
  hoje o botão é um "ativar/desativar" sem estado visível (`admin/admin.js:321`).
- **P0** Conferir, com teste, que câmera `ativo=0` **não aparece** para o cliente e não conta no
  "Câmeras no ar" (`GET /api/cameras` já filtra `ativo=1`).
- **P0** Teste `tests/test-camera-desativar.py`: desativa → some da lista do cliente → auditoria
  gravada → cliente não pode desativar (403).
- **P0 (só onde o dono mandou excluir)** Exclusão de verdade continua existindo **por script/API
  interna** (`ground/limpar-cameras-teste.py`, com `--simular`), apagando numa transação a câmera e
  o que é dela: `ingestoes`, `ingestoes_amostras`, `telemetria_minuto`, `compressoes`,
  `medicoes_qualidade`, `latencia_medicoes`, `analytics_eventos`, `analytics_contagens`,
  `analytics_agentes`, `analytics_marcas`.

## Fase 2 (P0) — limpar o entulho que está na tela

- **P0** Bancada: excluir `cam-01`, `cam-02`, `cam-conves`, `cam-teste-ip`, `vivo-webcam`. Manter
  `vps-webcam-bancada`.
- **P0** Excluir só os 4 fluxos de envio de teste: `envio-clipe-do-dono-mp4`, `envio-clipe-do-youtube`,
  `envio-youtube-link-de-p-gina`, `teste-latencia`. As 4 câmeras demo do PSV Exemplo ficam.
- **P0** Repetir a limpeza no banco da VPS (`/opt/pipeline/app/db/pipeline.db`) — depois de a bancada
  passar e sem tocar no que estiver no ar.
- **P0** Prova: listar `cameras` antes/depois nos dois bancos e a tela do cliente com 1 janela.

## Fase 3 (P1) — não recriar entulho

- **P1** Desativar vira o caminho padrão para câmera só parada (some da tela do cliente, histórico fica).
- **P1** Envio de teste não cria câmera nova quando já existe fluxo igual.
- **P1** Conferir que câmera desativada não aparece para o cliente.

## Riscos

- Exclusão é irreversível (o histórico daquele fluxo vai junto) → confirmação na tela + linha na auditoria.
- A VPS só entra depois de a bancada passar; antes de excluir, conferir `ingestoes` no ar.
