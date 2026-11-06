# Evidência — latência ponta a ponta (bordo → terra → leitor)

Data: 06/11/2026 · bancada (mesmo computador para codificar, servir e ler) · mediamtx v1.21.3 · ffmpeg 9.0.1

## Como o número é obtido

1. O agente de bordo queima no quadro o relógio de parede com milissegundos
   (`"relogio": true` no perfil → `%{localtime\:%T}.%{eif\:mod(t*1000\,1000)\:d\:3}`).
2. `bench/medir-latencia.py` abre UMA conexão contínua no fluxo do lado terra e
   carimba a hora de chegada de cada quadro (linha do `showinfo` do ffmpeg).
3. O mesmo puxão salva o quadro pedido como imagem; o relógio queimado é lido nela.
4. Latência = hora de chegada − relógio queimado.

Erro típico: ±0,1 s (relógio queimado tem passo de 1/30 s e o carimbo da linha tem
resolução de ms). O leitor é um ffmpeg simples: o número inclui o buffer do próprio
leitor, então ele é o **limite superior** do caminho.

## Resultado medido

| transporte | amostras | relógio queimado | chegada | latência |
|---|---|---|---|---|
| RTSP (caminho ao vivo) | n=150 | 15:58:33.000 | 15:58:34.568 | **1,568 s** |
| RTSP (caminho ao vivo) | n=300 | 15:58:46.000 | 15:58:47.568 | **1,568 s** |
| HLS (pull por segmento) | n=150 | 15:58:50.000 | 15:58:53.087 | **3,087 s** |
| HLS (pull por segmento) | n=300 | 15:59:00.000 | 15:59:02.596 | **2,596 s** |

Leitura: o caminho ao vivo (o mesmo transporte que o WebRTC do portal usa, sem o
fracionamento em segmentos do HLS) fica em **~1,6 s** — dentro do alvo de ≤3 s —
enquanto o HLS sozinho já consome 2,6–3,1 s. Por isso o portal entrega o vídeo por
**WebRTC/WHEP** e mantém o HLS só como alternativa.

Confirmado na tela: na mesma captura da janela, o relógio da página do portal marcava
`15:44:44.196` e o quadro exibido no player WebRTC marcava `15:44:44`, ou seja, o
WebRTC do navegador ficou **abaixo de 1,2 s**.

## Registro no sistema

As duas medições acima estão no banco do próprio sistema (tabela `medicoes`, fase 2),
com valor, fonte, data, hardware/versão e comando — nada digitado à mão:

- id 51 — latência RTSP/near-live: 1,568 s (n=2)
- id 52 — latência HLS: 2,596 a 3,087 s (n=2)

## O que ainda não está medido

- Latência com o link real (Starlink/4G): o RTT do link entra na conta do SRT.
- Latência fim-a-fim incluindo o encode: medida aqui no mesmo computador, sem salto de rede.
- Buffers do lado do jogador WebRTC com várias câmeras na mesma tela.
