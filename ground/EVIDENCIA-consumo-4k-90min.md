# Consumo de 90 minutos de vídeo 4K — números reais da web x nossa medição

| cenário (valor de origem, com fonte) | bitrate | consumo em 90 min |
|---|---|---|
| Netflix 4K UHD — "up to 7 GB per hour" (Netflix Help Center) | ≈10,4 Mbps | **10,50 GB** |
| YouTube — upload 4K SDR H.264 recomendado "35–45 Mbps" (YouTube Help) | 35–45 Mbps | **23,6–30,4 GB** |
| Câmera IP 4K em H.265 — "4 to 8 Mbps" (cctv-database) | 4–8 Mbps | **2,70–5,40 GB** |
| Câmera IP 4K em H.264 — "8 to 16 Mbps" (cctv-database) | 8–16 Mbps | **5,40–10,80 GB** |
| UHD Blu-ray — máximo de **vídeo** 82 Mbps (especificação) | 82 Mbps | **55,35 GB** |
| UHD Blu-ray — taxa do disco "92, 123, or 144 Mbit/s" (Wikipedia) | 92–144 Mbit/s | **62,10–97,20 GB** |
| **nosso HD 720p30 a 1000k** (medido nesta bancada) | 968 kbps | **0,65 GB** |
| **nosso HD 720p30 a 1500k** (medido) | 1.507 kbps | **1,02 GB** |
| **nosso HD 720p30 a 3000k** (medido) | 3.069 kbps | **2,07 GB** |

Contra os 10,50 GB de um 4K da Netflix em 90 minutos, a nossa saída fica 93,8% menor em 1000k, 90,3% em 1500k e 80,3% em 3000k (e contra o bitrate de upload 4K do YouTube, de 35 Mbps, a redução vai de 97,2% a 91,2%). Os números do nosso lado são medições desta bancada (SSIM 0,9904 em 1000k, 0,9928 em 1500k e 0,9955 em 3000k contra a fonte reduzida a 720p), enquanto Netflix/YouTube/Blu-ray/câmera IP são valores declarados por cada fonte — não os medi.

Fontes: [Netflix Help Center](https://help.netflix.com/en/node/87) · [YouTube Help — recommended upload encoding settings](https://support.google.com/youtube/answer/1722171/?hl=en) · [cctv-database — IP camera bandwidth](https://www.cctv-database.com/articles/ip-camera-bandwidth/) · [Wikipedia — Ultra HD Blu-ray](https://en.wikipedia.org/wiki/Ultra_HD_Blu-ray) · [Pocket-lint — limite de vídeo 82 Mbps](https://www.pocket-lint.com/tv-settings-for-the-best-4k-uhd-experience/)
