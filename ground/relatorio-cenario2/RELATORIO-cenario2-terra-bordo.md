## 1. Objetivo

Medir e documentar o **Cenário 2** do sistema LECSOR: TV vinda de terra para a embarcação no modelo
IPTV próprio (box por ponto na base + equipamento LECSOR a bordo). O número que decide o projeto é
**quanta banda um canal consome por 90 minutos** e quanto a nossa compressão retira disso.

## 2. Explicação leiga

- **Como o canal chega hoje:** o sinal IPTV já chega comprimido — 1080p entre 8 e 15 Mbps e 4K entre
  15 e 25 Mbps (números de mercado na seção 5). Em terra, a box recebe o canal; o nosso servidor
  reencoda para cerca de 1 Mbps e envia por satélite para a embarcação; o equipamento de bordo devolve
  o comando do controle remoto para a box em terra trocar de canal.
- **O que a compressão faz:** mantém a imagem em HD, com 30 quadros por segundo, e reduz o tamanho
  transmitido. Não é só "tirar quadros": o codificador descarta o que se repete entre quadros e gasta
  bits onde a imagem realmente muda.

- **O que isso muda na prática:** um filme de 90 minutos em 4K que consome 13,50 GB num canal de
  20 Mbps passa a consumir cerca de 0,65 GB no nosso HD a 1 Mbps — **95,2% menos**. O mesmo filme em
  1080p de 8 Mbps (5,40 GB) cai para 2,07 GB no nosso ajuste de 3 Mbps — **61,6% menos**.
- **O que ainda não está medido:** o caminho terra→bordo ponta a ponta, o tempo de troca de canal e o
  canal de retorno do controle remoto.

## 3. O fluxo (terra → bordo)

```
[Fornecedor IPTV white-label]
        |
        v
[Box por ponto na base]  ->  [Servidor de compressao LECSOR (terra)]
                                          |
                              enlace satelite (Starlink / VSAT)
                                          |
                                          v
                        [Equipamento LECSOR a bordo] -> TV do usuario
                                          ^
                    controle remoto do usuario  |
                    (canal de retorno: troca de canal na box em terra)
```

| Etapa | Situação |
|---|---|
| Recepção do canal na box, em terra | existe no modelo; nada medido por nós |
| Reencodar o canal para ~1 Mbps | medido na bancada (tabela 4.1) |
| Envio terra→bordo por satélite | não medido nesta direção |
| Entrega a bordo e exibição | não medido por nós |
| Canal de retorno do controle remoto | não medido por nós |

## 4. O que já medimos na bancada

### 4.1 Compressão de fonte já comprimida para HD (720p30, x264, 12 s)

| Fonte | Alvo | Saída | Redução | SSIM |
|---|---|---|---|---|
| 1080p (5.782 kbps) | 1000 kbps | 968 kbps | 83,3% | 0,9904 |
| 1080p (5.782 kbps) | 1500 kbps | 1467 kbps | 74,6% | 0,9928 |
| 1080p (5.782 kbps) | 3000 kbps | 3006 kbps | 48,0% | 0,9955 |
| 4K (19.813 kbps) | 1000 kbps | 985 kbps | 95,0% | 0,9970 |
| 4K (19.813 kbps) | 1500 kbps | 1507 kbps | 92,4% | 0,9979 |
| 4K (19.813 kbps) | 3000 kbps | 3069 kbps | 84,5% | 0,9989 |

O SSIM é comparado com uma referência HD sem compressão, de mesma duração. Script: `ground/medir-hd-4k.py`.

### 4.2 Transporte, latência e capacidade

| Item | Medido |
|---|---|
| Vídeo que chegou ao servidor (VPS) | 3,0 a 3,1 Mbps (3.128 kbps) |
| Leitores simultâneos no mesmo fluxo | 6 a 8 |
| RTT do enlace SRT (link 4G) | 56,8 a 67,8 ms |
| Atraso bruto ponta a ponta | abaixo de 1 s (parâmetro de latência 200 ms) |
| Quadros por segundo do fluxo | 30 |
| Qualidade do fluxo ao vivo (webcam 720p30, 8 s) | SSIM 0,9739 no ajuste de 3000k |
| Caminho validado | bancada → SRT → servidor → WHEP/HLS → app remoto (1280×720) |

## 5. Dados externos coletados

| Origem | Valor | Fonte |
|---|---|---|
| IPTV 4K SDR HEVC | 15 a 20 Mbps | Cloudje |
| IPTV 4K HDR10 | 20 a 25 Mbps | Cloudje |
| IPTV 4K Dolby Vision | 25 a 35 Mbps | Cloudje |
| IPTV 4K esporte (alta movimentação) | 30 a 50 Mbps | Cloudje |
| IPTV 1080p / SD | 8 a 15 Mbps / 2 a 5 Mbps | IPTV.domains |
| Netflix 4K | até 7 GB por hora (10,4 Mbps) | Netflix |
| YouTube, upload 4K SDR H.264 | 35 a 45 Mbps | Google |
| Câmera IP 4K H.265 / H.264 | 4 a 8 Mbps / 8 a 16 Mbps | CCTV Database |
| TVRO (antena de satélite) em embarcação offshore no Brasil | VSAT + TVRO Cobham instalados em 6 embarcações offshore novas (Companhia Brasileira de Offshore) | The Digital Ship |

O TVRO é um caminho **alternativo** por radiodifusão: o sinal chega pela antena e **não consome** o
link de dados da embarcação. A compressão descrita aqui vale para o caminho por IP.

## 6. Consumo em 90 minutos

<svg viewBox="0 0 660 224" width="100%" height="224" xmlns="http://www.w3.org/2000/svg"><text x="0" y="39" font-size="11.5" fill="#22304a">IPTV 4K esporte 50 Mbps</text><rect x="210" y="26" width="372.0" height="17" rx="2" fill="#0f172a"/><text x="589.0" y="39" font-size="11.5" fill="#0f172a">33,75 GB</text><text x="0" y="69" font-size="11.5" fill="#22304a">IPTV 4K HDR10 25 Mbps</text><rect x="210" y="56" width="186.0" height="17" rx="2" fill="#0f172a"/><text x="403.0" y="69" font-size="11.5" fill="#0f172a">16,88 GB</text><text x="0" y="99" font-size="11.5" fill="#22304a">IPTV 4K SDR 20 Mbps</text><rect x="210" y="86" width="148.8" height="17" rx="2" fill="#0f172a"/><text x="365.8" y="99" font-size="11.5" fill="#0f172a">13,50 GB</text><text x="0" y="129" font-size="11.5" fill="#22304a">IPTV 1080p 8 Mbps</text><rect x="210" y="116" width="59.5" height="17" rx="2" fill="#0f172a"/><text x="276.5" y="129" font-size="11.5" fill="#0f172a">5,40 GB</text><text x="0" y="159" font-size="11.5" fill="#22304a">Nosso HD 3.069 kbps</text><rect x="210" y="146" width="22.8" height="17" rx="2" fill="#ff6b57"/><text x="239.8" y="159" font-size="11.5" fill="#0f172a">2,07 GB</text><text x="0" y="189" font-size="11.5" fill="#22304a">Nosso HD 968 kbps</text><rect x="210" y="176" width="7.2" height="17" rx="2" fill="#ff6b57"/><text x="224.2" y="189" font-size="11.5" fill="#0f172a">0,65 GB</text></svg>

| Origem | Banda | 90 min (original) | Nosso HD 968 kbps | Redução | Nosso HD 3.069 kbps | Redução |
|---|---|---|---|---|---|---|
| IPTV 4K SDR HEVC (15 Mbps) | 15,0 Mbps | 10,12 GB | 0,65 GB | 93,5% | 2,07 GB | 79,5% |
| IPTV 4K SDR HEVC (20 Mbps) | 20,0 Mbps | 13,50 GB | 0,65 GB | 95,2% | 2,07 GB | 84,7% |
| IPTV 4K HDR10 (25 Mbps) | 25,0 Mbps | 16,88 GB | 0,65 GB | 96,1% | 2,07 GB | 87,7% |
| IPTV 4K esporte (50 Mbps) | 50,0 Mbps | 33,75 GB | 0,65 GB | 98,1% | 2,07 GB | 93,9% |
| IPTV 1080p (8 Mbps) | 8,0 Mbps | 5,40 GB | 0,65 GB | 87,9% | 2,07 GB | 61,6% |
| IPTV 1080p (15 Mbps) | 15,0 Mbps | 10,12 GB | 0,65 GB | 93,5% | 2,07 GB | 79,5% |
| Netflix 4K (cerca de 7 GB/h) | 10,4 Mbps | 7,02 GB | 0,65 GB | 90,7% | 2,07 GB | 70,5% |
| Câmera IP 4K H.265 (8 Mbps) | 8,0 Mbps | 5,40 GB | 0,65 GB | 87,9% | 2,07 GB | 61,6% |

Leitura: um 4K esportivo de 50 Mbps consome 33,75 GB em 90 minutos; o mesmo conteúdo no nosso alvo de
1 Mbps cabe em 0,65 GB.

## 7. Resumo técnico

- **Compressão de canal já comprimido:** medida entre **48,0%** (1080p → HD num alvo de 3 Mbps, SSIM
  0,9955) e **95,0%** (4K → HD num alvo de 1 Mbps, SSIM 0,9970).
- **Ajuste recomendado de borda:** 3.000 kbps, onde o fluxo ao vivo mediu SSIM **0,9739**; o alvo de
  1.000 kbps fica em cerca de 0,99 de SSIM em conteúdo de clipe, mas a medição ao vivo foi feita em
  3.000 kbps.
- **Banda entregue por fluxo:** 3,0 a 3,1 Mbps, com 6 a 8 leitores servidos pelo mesmo caminho.
- **Atraso:** RTT do enlace SRT entre 56,8 e 67,8 ms e atraso bruto abaixo de 1 segundo.
- **Codificação medida em CPU (x264).** O codificador por GPU (NVENC) não foi medido.
- **Estimativa para canais reais de IPTV:** pela proporção medida, um canal 1080p de 8 a 15 Mbps cai
  para 0,97 a 3,07 Mbps (redução de 61,6% a 87,9%); nenhum canal de IPTV real foi capturado e medido
  por nós.

## 8. O que ainda não foi medido (limites deste relatório)

- O caminho **terra → bordo** ponta a ponta: não há medição nesta direção.
- O **canal de retorno** e o tempo de **troca de canal** pelo controle remoto: não medidos.
- Quantos **canais simultâneos** uma máquina aguenta reencodar: não medido (os testes foram de um canal).
- **Limite real do enlace Starlink Maritime** a bordo: não medido.
- **Cobertura do feixe de satélite sobre o mar** (relevante para TVRO): não verifiquei.
- **NVENC / codificação por GPU**: não medido (o driver atual não habilitou o codificador).

## 9. Fontes

- Cloudje, bitrates de IPTV 4K: https://cloudje.eu/en/4k-iptv-streaming/
- IPTV.domains, requisitos de banda: https://iptv.domains/guides/iptv-internet-speed-requirements
- Netflix, uso de dados por qualidade: https://help.netflix.com/en/node/87
- Google, bitrates recomendados de upload: https://support.google.com/youtube/answer/1722171
- CCTV Database, banda de câmera IP 4K: https://www.cctv-database.com/articles/ip-camera-bandwidth/
- The Digital Ship, VSAT + TVRO em embarcações offshore: https://thedigitalship.com/news/maritime-satellite-communications/cbo-osvs-deploy-vsat-and-tvro-systems/

Medições de bancada: repositório `gm-innovation/video_compressor`, arquivos `ground/medir-hd-4k.py`,
`ground/medir-fundo-roi.py`, `ground/EVIDENCIA-consumo-4k-90min.md` e `ground/EVIDENCIA-latencia-ponta-a-ponta.md`.
