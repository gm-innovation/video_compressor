# Evidência — Fase 3 (lado terra + grade) e Fase 4 (fronts) provadas por navegador de verdade

**Data:** 09/11/2026 · **Bancada:** mediamtx (SRT→WebRTC/WHEP) + API `ground/api.py` :8765 + `board/agent.py` (4 câmeras sintéticas)
**Teste:** `python tests/e2e-fase3-4.py` (Playwright com o Chrome da máquina) — **tudo passou**

## Fase 3 — quantas câmeras a tela do cliente mostra

| Checagem | Resultado |
|---|---|
| Janelas de vídeo no front do cliente | **4** (`cam-01`..`cam-04`) |
| Janelas recebendo imagem (`srcObject` + `readyState>=2`) | **4 de 4** |
| Sinal de vida por câmera (relógio do vídeo andando) | OK em todas |

## Fase 4 — o que acontece quando a fonte cai

| Checagem | Resultado |
|---|---|
| Relógio do vídeo andando antes da queda | OK |
| Player reage à perda da fonte (congela ou reinicia, sem fingir "ao vivo") | OK |
| **Imagem volta sozinha** depois de o publicador voltar | **1,9 s** (limite de aceite: ≤10 s) |
| Pedido do navegador com endereço interno (`rtsp://`, `:8554`, `:8890`, `:9997`, `:8889`) | **0** |
| Corpo de pedido com senha/credencial na lista proibida | **0** |
| Resposta de `/api/analises` com endereço de câmera | **0** |

## Conclusão

- **Fase 3: concluída** na bancada — recepção SRT, grade de 4 fluxos no navegador e o portal/módulo §6 sobre a mesma API. Falta da fase (P1/P2): gravação/retenção em terra.
- **Fase 4: 4-A, 4-B e 4-E concluídos** (grade com reconexão, API como porta única, admin com Projeto §6 + Sistema). Falta: 4-C histórico (depende da gravação), 4-F operação assistida; 4-G PWA foi substituído pelo aplicativo Windows (Fase 7).
- O que o teste **não** prova: comportamento em rede do cliente (fora da bancada) e gravação — declarado aqui para não virar promessa.
