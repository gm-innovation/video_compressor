# Smoke de ponta a ponta (bordo → terra → tela)

Responde, com **número medido**, se o produto funciona como esperado — não se "a tela abre e não quebra".
Cada jornada tem ação de usuário real, comando real de mídia (ffmpeg/SRT/mediamtx), efeito medido e
evidência em disco.

```bash
export LECSOR_SENHA_DEMO=...          # a senha dos usuários de demonstração do lado terra
python tools/smoke/ponta-a-ponta.py --rapido          # J1+J2 (o que roda antes de cada commit)
python tools/smoke/ponta-a-ponta.py --jornadas 1,2,3,4,5,6
python tools/smoke/ponta-a-ponta.py --jornadas 7,8,9,10
python tools/smoke/ponta-a-ponta.py --modo producao --terra https://... --bordo http://... --jornadas 1,2
```

Estado: **J1–J6 fechadas** (`SMOKE: 6/6 OK`) e **J7–J10 fechadas** (`SMOKE: 4/4 OK`, 23/11/2026). Faltam as
fases 4 e 5 do plano (os números do produto no PC de captura real e a produção controlada).

## O que cada jornada prova

| # | Jornada | Ação | Medida que fecha o "OK" |
|---|---|---|---|
| J1 | Instalar e vincular | o admin gera a chave; o PC de captura digita | a embarcação do vínculo, a câmera no lado terra, a trilha (e a chave **não** vaza) |
| J2 | O cliente pede e a câmera sobe | o cliente clica "Iniciar transmissão" | fps, Mbps, latência, tempo de subida e a **imagem decodificada no navegador** |
| J3 | O cliente sai e a banda volta | o cliente fecha a tela | o tempo de parada, o processo morto, a banda de volta a ~0 |
| J4 | Dois clientes, um sai | A e B assistem; A sai; depois B | com 1 cliente a câmera **continua**; o envio morre só quando o último sai |
| J5 | O cliente grava, baixa e o arquivo some | o cliente põe a transmissão no ar, clica em **gravar**, depois em **parar**, e sai da tela | os **bytes e segundos gravados**, o vídeo que ele baixou (quem lê é o **ffprobe**), o aviso "baixe agora / apagado quando você sair", o **arquivo apagado no disco** e a **linha + a trilha de auditoria preservadas** |
| J6 | O radar de óleo e o HD | o cliente abre **Radar de óleo (HD)** e pede um trecho | o HD gravou **sem ninguém pedir**, o catálogo chegou ao cliente, o **bordo enviou** o bloco (ele olha a fila do terra) e o cliente **baixou** o arquivo |
| J7 | Quem vê o quê | entram os clientes tipo 1, 2 e 3 e o observador | o painel diz o escopo de cada um e cada um vê **só** os barcos dele — o do vizinho é negado nos **dois** sentidos (HTTP e tela) |
| J8 | O admin manda, o bordo obedece | o admin publica banda, teto e liga/desliga a câmera | o bordo grava no **formato que o ffmpeg usa** (`500k`), confirma no terra, a banda **cai de verdade** com o vídeo de pé, e o cliente que tentar mandar leva **403** |
| J9 | O defeito de verdade no bordo | (o defeito é injetado) o ffmpeg sai do computador de captura | o painel do admin vira **problema em 1,0 s** dizendo o que fazer; o bordo mudo vira **atenção** no limiar do produto (180 s); o retrato **não inventa** o que não mediu (`nao_medido`) |
| J10 | Licença revogada corta | o admin revoga a chave do barco | o bordo **consulta o terra sozinho** (ninguém abre tela no barco) e a transmissão **morre em 2,3 s**; a tela diz o motivo; a trilha registra **1** corte; o vínculo **não** é apagado; a reativação devolve o barco ao ar |

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
- a latência **percebida na tela** num cliente externo de verdade;
- **a imagem do HD do radar** (J6): o radar de verdade entra por HDMI. Nesta bancada o dispositivo de
  vídeo abre mas **não entrega quadro** (`ffmpeg -f dshow -i "ACER HD User Facing" -t 3` = 0 quadro), então
  o que a J6 prova é a **cadeia** (gravou sozinho → catálogo → pedido → o bordo enviou → o cliente baixou);
  o **quadro** do radar só se prova com o radar no HDMI.

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
