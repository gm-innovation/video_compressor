# Smoke de ponta a ponta (bordo → terra → tela)

Responde, com **número medido**, se o produto funciona como esperado — não se "a tela abre e não quebra".
Cada jornada tem ação de usuário real, comando real de mídia (ffmpeg/SRT/mediamtx), efeito medido e
evidência em disco.

```bash
export LECSOR_SENHA_DEMO=...          # a senha dos usuários de demonstração do lado terra
python tools/smoke/ponta-a-ponta.py --rapido          # J1+J2 (o que roda antes de cada commit)
python tools/smoke/ponta-a-ponta.py --jornadas 1,2,3,4
python tools/smoke/ponta-a-ponta.py --modo producao --terra https://... --bordo http://... --jornadas 1,2
```

## O que cada jornada prova

| # | Jornada | Ação | Medida que fecha o "OK" |
|---|---|---|---|
| J1 | Instalar e vincular | o admin gera a chave; o PC de captura digita | a embarcação do vínculo, a câmera no lado terra, a trilha (e a chave **não** vaza) |
| J2 | O cliente pede e a câmera sobe | o cliente clica "Iniciar transmissão" | fps, Mbps, latência, tempo de subida e a **imagem decodificada no navegador** |
| J3 | O cliente sai e a banda volta | o cliente fecha a tela | o tempo de parada, o processo morto, a banda de volta a ~0 |
| J4 | Dois clientes, um sai | A e B assistem; A sai; depois B | com 1 cliente a câmera **continua**; o envio morre só quando o último sai |

## Vereditos

- **OK** — tudo passou com medida.
- **OK_COM_RESSALVAS** — passou o que deu para medir, mas alguma checagem ficou **sem medida**.
- **NÃO MEDIDA** — nada pôde ser medido (sem câmera, sem mediamtx, sem o par de ponta).
- **FALHA** — alguma checagem medida falhou.

Regra dura: **sem medida, o veredito nunca é "OK"**. Um número ausente aparece no relatório com o motivo.

## Evidência

`smoke/saida/<AAAA-MM-DD>/` — `RESUMO.md` (um veredito por jornada), `resultado.json` e, por jornada,
`j<N>/qa.md` + `j<N>/resultado.json` com as checagens e as medidas.

## O que o smoke **não** mede (declarado)

- o link **Starlink Maritime** real (RTT, perda, chuva);
- o hardware definitivo (4 câmeras + o radar por HDMI) — na bancada a fonte é sintética: **na bancada
  não há câmera plugada**, então quem entrega os quadros é o gerador do produto (`testsrc2`), e o
  encode/SRT/mediamtx são os reais;
- a latência **percebida na tela** num cliente externo de verdade.

## Duas coisas que só a bancada tem

1. **O atendedor da rota local** (`tools/smoke/bordo_de_bancada.py`): a máquina de captura do cliente
   tem câmera própria; nesta bancada a fonte é o gerador do produto. O atendedor serve a rota
   `POST /api/cameras/ligar` chamando a **mesma função do produto**
   (`ingestao.ligar_camera`/`desligar_camera`), para a rodada **não depender de a webcam da bancada
   estar livre** (nem de qual máquina roda o smoke). A flag, o agente (`agente_de_ordens`), o relato de
   estado e o envio SRT são os reais. *Esta máquina tem webcam de verdade (`ACER HD User Facing`,
   `ingestao.maquina_de_captura()` = `true`), então a rodada com a câmera física é o próximo passo.*
2. **O medidor** (`tools/smoke/medidor.py`): os bytes que **chegam** são contados no cano (`-c copy -f
   mpegts pipe:1`) — `-f null` não conta byte nenhum e devolvia 0,0 Mbps. A taxa de entrega e a taxa de
   mídia são medidas **separadas**: se a fonte produz mais rápido que o tempo real, a taxa de entrega
   engana e a latência vira número negativo — o smoke denuncia isso em vez de aceitar.

A prova de que o medidor mede: `python tests/smoke-medidor-detecta-falha.py` (acha o fluxo quando há,
devolve zero quando a fonte é cortada na mão e quando o mediamtx cai).
