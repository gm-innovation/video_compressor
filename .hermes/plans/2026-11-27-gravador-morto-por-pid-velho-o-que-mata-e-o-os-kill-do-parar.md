# Plano — o gravador do HD morre por `signal 15` e quem atira é o próprio app (pid velho do `parar()`)

Dono: **Alexandre**. Data: **27/11/2026**. Versão no PC de captura: **0.29.0** (instalada — o
`saude_bordo` da VPS mostra `versao_app = 0.29.0` a partir de `2026-11-27T18:03:57Z`).
Estado: **PLANO — nada implementado.**

## 1. O que o dono relatou

> "app de captura permanece da mesma forma, 4 blocos no hd e o gravador não está de pé, e agora não tem
> nenhuma câmera transmitindo"

Anexou de novo `D:\gravacao-continua.log` (615 B, 15:04) e `D:\gravador.log` (12 108 B, 15:04).

## 2. O que os dois logs dizem (medido, sem hipótese)

`D:\gravador.log` — o ffmpeg **abre a câmera certo** e o comando do relé está no ar:

```
Input #0, dshow, from 'video=@device_pnp_...vid_345f&pid_2131...'  1280x720, 30 fps
Output #0, tee, to '[f=segment:...movflags=+frag_keyframe+empty_moov+default_base_moof]C\:/.../hd/bloco-%Y%m%d-%H%M%S.mp4|[f=mpegts]srt\://127.0.0.1\:8890?...streamid=publish\:gravador-cam-device-pnp-usb-vid-345f-...'
[segment] Opening 'C:/Users/HAVOX/.../servidor/ground/hd/bloco-20261127-150342.mp4' for writing
... kb/s:1604.21
Exiting normally, received signal 15.      <-- 4ª vez na sequência
```

Quatro execuções do ffmpeg, **as quatro mortas por `signal 15`**, em 18 s:
`15:03:42`, `15:03:47`, `15:03:54`, `15:04:00` (nomes dos blocos) — e a última linha do log é a morte.

`D:\gravacao-continua.log` — o laço subiu às `15:03:39` e **acabou**:

```
15:03:39 gravador subido pelo desejo do admin (pid 11448)
15:03:39 gravacao continua no ar: camera Radar de Óleo (cam-...-345f-...) · dispositivo @device_pnp_... (origem cadastro) · blocos de 60s em C:\Users\HAVOX\...\servidor\ground\hd
15:03:40 gravador no ar (pid 10020)
15:03:46 gravador no ar (pid 12220)
15:03:52 gravador no ar (pid 12332)
15:03:58 gravador no ar (pid 12044)
```

Duas conclusões **medidas**:

- o encoder e o caminho do relé **funcionam** (o ffmpeg comprime, escreve o bloco e publica o SRT) —
  o que mata é um **SIGTERM de fora**, não o comando;
- o **laço morre às 15:04:02** (nenhuma linha depois das 15:03:58) e **nada o reergue**: não há
  "gravador subido pelo desejo do admin" depois de `15:03:39`, ou seja o `garantir()` do supervisor
  **saiu cedo** (desejo desligado **ou** `dispositivo()` vazio) — a tela diz "não está de pé" e não diz
  por quê.

Retrato do lado terra no mesmo instante (`saude_bordo`, 18:07:59Z): `discos[0]` = a pasta do pacote
com **4 blocos** e `mais_novo = 15:04:01`; `banco.ingestoes_no_ar = 14` **todas em `erro`**; a linha da
câmera do radar tem `pid 10896` **vivo** (7,2 MB medidos) com `estado = erro`.

## 3. Quem dispara o `signal 15` (a peça que falta fechar)

No produto inteiro só **três** lugares mandam sinal a um processo:

| onde | o quê | alcance |
|---|---|---|
| `ground/ingestao.py:583` `parar()` | `os.kill(r["pid"], SIGTERM)` | o **pid gravado na linha de `ingestoes`** — qualquer processo que hoje seja dono daquele pid |
| `ground/gravacao_continua.py:260-262` `_parar_gravador()` | `taskkill /F` / `os.kill(pid, 15)` | só com o desejo **desligado** |
| `ground/gravacao_continua.py:801` `proc.terminate()` | o ffmpeg do próprio laço | só com o desejo **desligado** |

O `liberar_camera()` (o `_ps_do_liberar`, PowerShell) mata por **nome do dispositivo** e usa
`Stop-Process -Force` — é o suspeito da rodada passada, **mantido** com a exclusão do gravador, mas
`-Force` não produz a mensagem "received signal 15" que o ffmpeg imprimiu.

O caminho que **explica a mensagem** é o `parar()`: `desligar_camera()` (chamada a cada rodada do
`aplicar_flag` quando a câmera está "parada") pega a **última linha** de `ingestoes` da câmera — hoje
`estado='erro'`, que **não** está na lista de saída (`parado`, `fim`) — e chama `parar(id)`, que faz
`os.kill(<pid da linha>, SIGTERM)`. O pid da linha é **velho**: o processo que o tinha já morreu e o
Windows **reciclou o pid** — e quem passou a ter aquele pid foi o ffmpeg do gravador. Aí o gravador
morre, o laço reergue com **outro** pid, e a rodada seguinte repete.

**Hipótese a medir (não é fato ainda):** conferir, no PC real, se o `pid` da linha de `ingestoes` da
câmera do radar é o pid de um processo **vivo e alheio** (o `pid 10896` do retrato é o candidato:
`libx264`, vivo) e se o `parar()` roda a cada rodada do flag.

## 4. Correção proposta (fases, com prioridade)

**FASE 1 — matar por IDENTIDADE, nunca por pid solto (P0, é a causa).**
- `parar()`: antes de qualquer `os.kill`, provar que o processo **é o ffmpeg desta ingestão** — a
  assinatura passa a ser `(pid, criado_em)`: gravar `criado_em` (hora de criação do processo) na linha
  ao subir o envio e, na hora de matar, só matar se a hora de criação do pid **bater**; pid com hora de
  criação mais nova = reciclado → **não mata nada** e registra no log (`pid reciclado, não era o nosso`).
- `parar()` também **nunca** mata quem é do gravador (mesma exclusão do `_ps_do_liberar`: laço, filhos,
  e qualquer processo cuja linha de comando tenha o bloco/`srt://` do relé).
- `_camera_em_uso()` idem (mesma classe de defeito: decide por `pid` de linha).

**FASE 2 — o laço não pode morrer calado, e o supervisor não pode achar que está tudo bem (P0).**
- `_subir_gravador()` grava `(pid, criado_em)` no `gravador.pid` e o `_pid_vivo` passa a conferir a
  **hora de criação** (hoje `os.kill(pid, 0)` só diz "existe alguém com esse pid": um pid reciclado faz
  o supervisor achar que o gravador está de pé — o oposto do que a tela mostra).
- `garantir()` **sempre escreve uma linha** dizendo por que não subiu (`sem dispositivo`, `desejo
  desligado`) e o `motivo` vai para o `resumo()` (a tela do app e o catálogo de terra passam a mostrar
  o porquê, não só "não está de pé").

**FASE 3 — a tela e o terra (P1).**
- `resumo()` publica `laco_pid`, `laco_criado_em`, `ultimo_bloco_em`, `segundos_sem_bloco` e
  `motivo_de_nao_subir`; a tela do app e o cartão do admin mostram isso em vez de só "parado".
- Com o relé ligado, a tela mostra o caminho do relé e se o mediamtx tem o caminho publicado
  (`caminhos >= 1`) — o retrato de hoje mostra `caminhos: 0` com o gravador fora do ar.

**FASE 4 — o vivo não pode depender do gravador (P1).**
- Se o gravador está fora do ar, o vivo já cai de volta no dispositivo (o `dono_da_camera()` exige
  `gravador_de_pe()`), mas a rodada provou que a lista de envios fica suja (`14` linhas em `erro`) e a
  tela diz "nenhuma câmera transmitindo". Limpar/marcar as linhas órfãs no boot e provar o vivo
  **com e sem** o gravador de pé.

**FASE 5 — prova de regressão (P1).**
- Teste da bancada: subir um ffmpeg "falso" com um pid que **depois** vira o pid de outro processo e
  provar que o `parar()` **não** mata o alheio (hoje mata).
- Teste: `garantir()` com `gravador.pid` reciclado → o supervisor **detecta** e sobe de novo.
- Regressão completa (`tools/regressao-0130.py`) + `unittest` e o deploy do lado terra.

## 5. O que eu preciso do dono (para medir, não para chutar)

1. No PC de captura, com o app aberto: `tasklist /FI "PID eq <pid da linha de ingestoes>"` — só para
   confirmar que aquele pid é um processo vivo e alheio (eu leio o pid do retrato da VPS).
2. Se der: o `hd/log/gravador.log` **da pasta do pacote** (`...\resources\servidor\ground\hd\log\`),
   além do `D:\gravador.log`, para comparar as duas cópias.
3. A tela do app de captura no estado de agora (a linha do radar/gravador), para ver o `motivo` que a
   tela mostra.

## 6. Pendências desta rodada (não mexidas no plano)

- A escolha de disco do admin (`D:\`) **não voltou** depois da atualização: o retrato mostra
  `origem_da_escolha: padrao` e a pasta do próprio pacote (`C:\...\resources\servidor\ground\hd`) — o
  `D:\` era onde estavam os blocos em 13:20.
- J5 aberta: o ramo `encerrar` fecha a sessão sem apagar a gravação nem auditar
  `gravacoes_apagadas`/`cliente_saiu_da_tela`.
