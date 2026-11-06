# Evidência — Fase 5: análises de vídeo a bordo (contagem de pessoas)

Data: 06/11/2026 · bancada LECSOR (RTX 4050, ffmpeg 9.0.1, Python do projeto em `.venv`).

## O que está no ar

| Peça | Arquivo | Função |
|---|---|---|
| Detecção | `analytics/detector.py` | YOLOv10n em ONNX (onnxruntime), letterbox 640×640, classes COCO; devolve caixa em pixel do quadro |
| Rastreio | `analytics/rastreador.py` | `Rastreador` (IoU + distância de centro, id sobrevive a quadros sem detecção) |
| Contagem | `analytics/rastreador.py` | `ContadorLinha` com histerese (3 quadros de confirmação) e espera por id; `ZonaRisco` por permanência |
| Agente | `analytics/agente.py` | Lê o fluxo publicado (RTSP), analisa, **sobe evento e contagem** para a API — o vídeo não sobe |
| Perfil | `analytics/perfis/cam-03.json` | câmera, modelo, confiança, linha de contagem, zona de risco |
| Ingestão | `ground/api.py` | `POST /api/analytics/eventos` e `POST /api/analytics/contagens` com a chave do agente (`X-Chave-Analytics`) |
| Consulta | `ground/api.py` | `GET /api/analises` (sessão ou loopback) — estado do agente, caixas, contagens e eventos |
| Tela do cliente | `app/app.js` | Pílula `IA · Análises`: caixas sobre o vídeo, linha de contagem e selo `👤 N agora · entrou X · saiu Y` |
| Tela do admin | `admin/admin.js` | Tela Análises: agentes, quadros/s, modelo, erros, contagens e eventos |

Banco: `db/schema-fase5.sql` (`analytics_agentes`, índices das tabelas da Fase 4).

## Prova executada

1. **Teste da lógica de contagem** (`tests/test-contagem.py`): 14 checagens, todas passando — cruzamento limpo conta 1; ruído de um quadro não conta (histerese); dois sentidos contam 1 e 1; espera por id suprime a travessia seguinte; pico de 3 pessoas simultâneas; id que desaparece não infla o pico; rastreio mantém um id e cria ids distintos para pessoas simultâneas; permanência em zona dispara um evento e fora da zona não dispara.
2. **Detector real**: YOLOv10n ONNX sobre o clipe de bancada (768×432, 12 fps) detecta pessoas de verdade — 69 quadros/s de decodificação+deteção na CPU.
3. **Agente ponta a ponta**: 120 s lendo o fluxo `cam-03` pelo mediamtx — 1393 quadros decodificados, 697 analisados, 5,8 quadros/s, `entrou=5`, `saiu=2`, **0 erros**, eventos gravados no banco (entrada/saída com alvo, ponto e confiança).
4. **Estado do agente no banco**: `agente-bordo-01 · yolov10n.onnx · 5.3 quadros/s · 381 quadros · estado no ar`; última contagem id 31 com fonte `fluxo cam-03 · agente-bordo-01`.
5. **Navegador de verdade** (`tests/e2e-fronts.py`, Playwright/Chrome): 28 checagens, todas passando — cliente liga `IA · Análises`, aparecem **3 caixas de detecção** sobre o vídeo, a linha de contagem e o selo `👤 0 agora · entrou 1 · saiu 0`; o admin vê o agente `agente-bordo-01`, o modelo e os quadros/s na tela Análises.

Prints: `bench/saida/_front-cliente-ia.png`, `_front-admin-analises.png`.

## Regras respeitadas

- O agente **não sobe vídeo**: sobe número e evento; o vídeo continua com o encoder (Fase 2).
- A ingestão exige chave do agente (variável de ambiente no servidor, `ground/.env.local`, fora do git); sem chave a porta responde 401.
- A tela do cliente recebe **resultado** (caixa normalizada, contagem, linha) — nunca endereço de câmera nem credencial.
- Reconhecimento de pessoas continua **desligado** (dado sensível, decisão já registrada no plano).
