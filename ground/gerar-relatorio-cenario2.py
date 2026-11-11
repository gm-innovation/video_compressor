# -*- coding: utf-8 -*-
"""Relatório Cenário 2 (TV de terra para bordo) — PDF na marca LECSOR. v2: acentuação e tabela 4.1 corrigidas."""
import base64, pathlib, re, subprocess
import markdown

BASE = pathlib.Path(r"C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video\ground\relatorio-cenario2")
BASE.mkdir(parents=True, exist_ok=True)
LOGO = pathlib.Path(r"C:\Users\EngenhariaGoogleMari\lecsor-site\src\assets\logo-lecsor-white.png")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

SEC = 90 * 60
def gb(kbps):
    return kbps * 1000 * SEC / 8 / 1e9
def red(base, nosso):
    return 100.0 * (1 - nosso / base)
def br(x, c):
    """Número no formato brasileiro: vírgula decimal."""
    return f"{x:.{c}f}".replace(".", ",")

# ---- medido na bancada: fonte já comprimida -> HD 720p30 (x264), 12 s ----
MED = [("1080p (5.782 kbps)", 1000, 968, 5782, 0.9904),
       ("1080p (5.782 kbps)", 1500, 1467, 5782, 0.9928),
       ("1080p (5.782 kbps)", 3000, 3006, 5782, 0.9955),
       ("4K (19.813 kbps)", 1000, 985, 19813, 0.9970),
       ("4K (19.813 kbps)", 1500, 1507, 19813, 0.9979),
       ("4K (19.813 kbps)", 3000, 3069, 19813, 0.9989)]
linhas_med = "\n".join(
    f"| {f} | {a} kbps | {o} kbps | {br(100*(1-o/e),1)}% | {br(s,4)} |" for f, a, o, e, s in MED)

# ---- consumo em 90 min: origens externas x nosso HD ----
ORIGENS = [("IPTV 4K SDR HEVC (15 Mbps)", 15000, "Cloudje"),
           ("IPTV 4K SDR HEVC (20 Mbps)", 20000, "Cloudje"),
           ("IPTV 4K HDR10 (25 Mbps)", 25000, "Cloudje"),
           ("IPTV 4K esporte (50 Mbps)", 50000, "Cloudje"),
           ("IPTV 1080p (8 Mbps)", 8000, "IPTV.domains"),
           ("IPTV 1080p (15 Mbps)", 15000, "IPTV.domains"),
           ("Netflix 4K (cerca de 7 GB/h)", 10400, "Netflix"),
           ("Câmera IP 4K H.265 (8 Mbps)", 8000, "CCTV Database")]
linhas_90 = "\n".join(
    f"| {n} | {br(b/1000,1)} Mbps | {br(gb(b),2)} GB | {br(gb(968),2)} GB | {br(red(b,968),1)}% | "
    f"{br(gb(3069),2)} GB | {br(red(b,3069),1)}% |" for n, b, _ in ORIGENS)

# ---- gráfico de barras (SVG inline) ----
GRAF = [("IPTV 4K esporte 50 Mbps", 50000, False),
        ("IPTV 4K HDR10 25 Mbps", 25000, False),
        ("IPTV 4K SDR 20 Mbps", 20000, False),
        ("IPTV 1080p 8 Mbps", 8000, False),
        ("Nosso HD 3.069 kbps", 3069, True),
        ("Nosso HD 968 kbps", 968, True)]
W, LINHA, TXT = 660, 30, 210
ALT = 34 + LINHA * len(GRAF) + 10
maior = max(b for _, b, _ in GRAF)
barras = []
for i, (nome, b, nosso) in enumerate(GRAF):
    y = 26 + i * LINHA
    largura = max(2, (b / maior) * (W - TXT - 78))
    cor = "#ff6b57" if nosso else "#0f172a"
    barras.append(
        f'<text x="0" y="{y+13}" font-size="11.5" fill="#22304a">{nome}</text>'
        f'<rect x="{TXT}" y="{y}" width="{largura:.1f}" height="17" rx="2" fill="{cor}"/>'
        f'<text x="{TXT+largura+7:.1f}" y="{y+13}" font-size="11.5" fill="#0f172a">'
        f'{br(gb(b),2)} GB</text>')
grafico = (f'<svg viewBox="0 0 {W} {ALT}" width="100%" height="{ALT}" '
           f'xmlns="http://www.w3.org/2000/svg">{"".join(barras)}</svg>')

corpo = f"""
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
{linhas_med}

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

{grafico}

| Origem | Banda | 90 min (original) | Nosso HD 968 kbps | Redução | Nosso HD 3.069 kbps | Redução |
|---|---|---|---|---|---|---|
{linhas_90}

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
"""

corpo = re.sub(r"(?m)^(\*\*[^\n]+\*\*)\r?\n(?=[-\d])", r"\1\n\n", corpo.strip())
html_corpo = markdown.markdown(corpo, extensions=["tables", "fenced_code", "sane_lists"])
logo_b64 = base64.b64encode(LOGO.read_bytes()).decode()

CSS = """
@page { size: A4; margin: 13mm 13mm 11mm 13mm; }
* { box-sizing: border-box; }
body { margin:0; color:#0f172a; background:#fff; line-height:1.42;
  font-family:'Space Grotesk','DM Sans',system-ui,Segoe UI,sans-serif; font-size:10.6pt; }
.capa { background:#0f172a; color:#e8edf5; padding:24mm 14mm 16mm 14mm; margin:-13mm -13mm 8mm -13mm; }
.capa img { height:46px; }
.capa h1 { font-size:23pt; line-height:1.18; margin:14mm 0 4mm 0; color:#fff; }
.capa .sub { font-size:11.5pt; color:#9fb0c9; margin:0; }
.capa .faixa { margin-top:13mm; display:flex; gap:8mm; font-size:9.6pt; color:#c9d5e6; }
.capa .faixa div { border-left:2px solid #ff6b57; padding-left:3mm; }
.capa .acento { color:#ff6b57; }
h2 { font-size:13pt; color:#0f172a; margin:7mm 0 2.5mm 0; padding-bottom:1.2mm;
  border-bottom:1.4pt solid #0f172a; }
h3 { font-size:11pt; margin:5mm 0 2mm 0; color:#22304a; }
p { margin:0 0 2.6mm 0; }
table { width:100%; border-collapse:collapse; margin:2mm 0 4mm 0; font-size:9.2pt; }
th { background:#0f172a; color:#fff; text-align:left; padding:1.7mm 2mm; font-weight:600; }
td { border-bottom:0.5pt solid #d8dfea; padding:1.5mm 2mm; vertical-align:top; }
tr:nth-child(even) td { background:#f4f7fb; }
ul { margin:0 0 2.6mm 0; padding-left:5mm; }
li { margin-bottom:1.2mm; }
svg { margin:2mm 0 3mm 0; }
pre { background:#0f172a; color:#e8edf5; padding:3mm; border-radius:2mm; font-size:8.4pt;
  line-height:1.35; white-space:pre-wrap; }
pre code { background:transparent; color:inherit; padding:0; border-radius:0; }
code { font-family:'Cascadia Mono',Consolas,monospace; }
.rodape { margin-top:6mm; border-top:0.8pt solid #d8dfea; padding-top:2mm; font-size:8.4pt; color:#5b6b83; }
h1,h2,h3,h4 { break-after:avoid-page; page-break-after:avoid; }
ul,ol { break-inside:avoid; page-break-inside:avoid; }
tr,li { break-inside:avoid; page-break-inside:avoid; }
p,li { orphans:3; widows:3; }
"""

html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>Cenário 2 - TV de terra para bordo</title>
<style>{CSS}</style></head><body>
<div class="capa">
  <img src="data:image/png;base64,{logo_b64}" alt="LECSOR">
  <h1>Cenário 2 — TV de terra para bordo:<br>consumo de banda e compressão</h1>
  <p class="sub">IPTV próprio (box por ponto na base + equipamento LECSOR na embarcação)</p>
  <div class="faixa">
    <div>Documento técnico<br><span class="acento">11/11/2026</span></div>
    <div>Base<br><span class="acento">medições de bancada</span></div>
    <div>Escopo<br><span class="acento">apenas técnico</span></div>
  </div>
</div>
{html_corpo}
<div class="rodape">LECSOR Technology &middot; relatório interno &middot; valores medidos na bancada e fontes externas citadas na seção 9.</div>
</body></html>
"""

fonte = BASE / "_relatorio.html"
fonte.write_text(html, encoding="utf-8")
(BASE / "RELATORIO-cenario2-terra-bordo.md").write_text(corpo + "\n", encoding="utf-8")
pdf = BASE / "RELATORIO-Cenario2-TV-terra-para-bordo.pdf"
subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                f"--print-to-pdf={pdf}", fonte.as_uri()], check=True, timeout=180)
print("PDF:", pdf, pdf.stat().st_size)
