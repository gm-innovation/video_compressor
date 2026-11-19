# Flag em terra, gravação full-time do radar e configuração só do admin

**Status:** APROVADO pelo dono em 19/11/2026 · **Data:** 19/11/2026 · **Base:** 0.6.10 (`8fc7544`)
**Alvo:** 0.7.0 (mudança de modelo: sai fila de ordens, entra flag de estado; entra gravação contínua do radar)

**Situação (19/11/2026):** implementado, provado e publicado na **0.7.0** (`9ca021d`). Fases 1–5 no código;
provado por `tests/e2e-flag-de-estado-liga-a-camera.py`, `tests/e2e-dois-clientes-um-sai.py`,
`tests/test-gravacao-continua-do-radar.py`, `tests/e2e-hd-do-radar-cliente-pede-trecho.py`,
`tests/e2e-tela-do-radar-hd-do-cliente.py` (tela real) e a regressão da 0.6.10 (11/11).
Falta só a **medição em bancada** (30 fps / ≤3 s / ≥80%) na cadeia nova.

## O que o dono pediu (palavras dele)

> "não podemos contar que o computador de captura a bordo terá porta aberta para receber comandos ou
> informações, a única certeza é de que ele poderá enviar"

> "quando o cliente quiser iniciar o streaming, a informação não poderá sair de terra para bordo, o
> computador de captura a bordo precisa ficar olhando para terra e sempre que a flag mudar, ele inicia ou
> para a transmissão, essa flag pode ser acionada pelo usuário ou automática de acordo com o temporizador,
> desligamento ou desconexão"

> "terra (vps) precisa saber se a tela foi fechada, computador desligado ou falta de conexão no computador
> do usuário para interromper a transmissão, a menos que haja outro usuário conectado e acompanhando"

> "no computador de captura precisamos preparar o app para que em determinados casos termos um hd salvando
> full time as imagens do radar de óleo, as imagens devem ser comprimidas e guardadas para eventuais
> pesquisas, ou seja, mesmo que o cliente não acione o streaming do radar de óleo, as imagens estarão sendo
> comprimidas e gravadas full time, o cliente pode acessar as imagens a qualquer momento"

> "não precisaremos mais fazer o trabalho de conversão dos dados do radar de óleo em vídeo, receberemos as
> imagens já compiladas via hdmi, elas seguem o mesmo protocolo das câmeras, recebemos as imagens,
> comprimimos, e enviamos (no caso do radar de óleo, gravamos também)"

> "todas as configurações serão feitas por mim (admin), nada será configurado pelo cliente"

## O que já existe hoje (medido no código, 0.6.10)

- **O bordo só sai, nunca recebe:** o `ground/agente_de_ordens.py` é quem **pergunta** ao lado terra
  (`GET /api/ordens?embarcacao_id=…&espera=…`) e obedece. Nada conecta de terra para o bordo. A base da
  regra do dono **já vale** — falta trocar o modelo de *fila de ordens* por *flag de estado*.
- **Batimento:** `ground/api.py` fecha a sessão sem "estou aqui" (`SEGUNDOS_SEM_BATIMENTO = 60`) e
  `parar_se_ninguem_vendo()` só manda `parar` quando **não há mais sessão viva** na câmera — o caso "outro
  usuário ainda assistindo" já está coberto. Falta tratar os três eventos como **fatos explícitos**
  (tela fechada / computador desligado / sem conexão), com registro próprio.
- **Radar:** hoje entra por **arquivo `.drq` ou `tcp://`** e é **convertido em imagem** por
  `ground/radar_drq.py` / `radar_tcp.py` (config `radar_fonte`/`radar_modo`/`radar_taxa`/`radar_alvo` na
  embarcação). Com o HDMI isso deixa de existir: vira entrada de vídeo comum (`dshow:<dispositivo>`).
- **Gravação:** `ground/gravacao.py` grava **no lado terra**, amarrada a uma transmissão, e o arquivo é
  **apagado quando o cliente sai** (regra de 18/11). É o oposto do pedido agora: aqui é **no PC de captura**,
  **contínua**, e **não** some quando o cliente sai.
- **Config:** o radar por embarcação já é configurável pela tela; o dono quer isso **só para o admin**, com
  o cliente sem nenhuma configuração.

## Regra de arquitetura que passa a valer (corrige o modelo)

1. **O bordo nunca é alcançado.** Terra não abre conexão para o bordo em caso nenhum. O bordo puxa e reporta.
2. **Terra publica o DESEJO; o bordo é a autoridade do REAL.** Terra diz "esta câmera deve estar no ar, por
   causa X" (flag com número de versão). O bordo aplica a diferença e conta o que conseguiu — nunca
   inventando sucesso.
3. **Quem quer ver é a sessão do usuário.** A flag vira `ligar` por consequência de existir sessão viva; vira
   `parar` quando não existe nenhuma (fim de tempo, tela fechada, PC desligado, sem conexão, operador).
4. **Gravação contínua do radar é local ao bordo** e independente do streaming (não depende de flag, de
   sessão nem de internet).

---

## Fase 1 — Flag de estado em terra, lida pelo bordo (P0)

**F1-P0.1** Terra: novo `GET /api/estado-desejado?embarcacao_id=…` (autorizado pelo token de ingestão,
igual ao `/api/ordens`), devolvendo por câmera: `{camera_id, fluxo_id, desejo: "ligar"|"parar", versao, motivo,
transmissao_id}`. `desejo` é calculado a cada leitura por `sessoes_vivas()` + teto do tempo — **não** é uma
fila que se consome. Cada mudança de versão é auditada (`desejo_camera_mudou`).
**F1-P0.2** Bordo: o agente deixa de consumir ordens e passa a **comparar** o desejo com o que ele tem no ar
(`ligados.json`), ligando/desligando só a diferença. Nada de "ordem entregue" que ninguém confirmou.
**F1-P0.3** Bordo: `POST /api/estado-real` (periódico + a cada mudança) com `{camera_id, no_ar|parado|erro,
motivo, fluxo_id, desde, gravando}` — é assim que a tela do cliente e do operador mostram a verdade (hoje o
`no_ar` só aparece quando o resultado da ordem volta).
**F1-P0.4** Compatibilidade: a fila `ordens_do_bordo` continua sendo escrita e atendida por uma versão, para
que a 0.6.10 instalada no PC de captura não pare de funcionar durante a troca; sai na versão seguinte.
**F1-P2** A tela do admin mostra, por câmera, `desejo` × `real` lado a lado (onde a divergência aparecer).

**Prova da fase:** dois lados de pé + agente real; a flag vira "ligar" sem nenhum pedido chegar ao bordo,
a câmera sobe, o `estado-real` chega, a flag volta a "parar" e a câmera desce — medido por processo.

## Fase 2 — Quem assiste manda: tela fechada, PC desligado, sem conexão (P0)

**F2-P0.1** Registrar os três eventos como fatos na trilha: `cliente_saiu`, `tela_fechada`
(`navigator.sendBeacon` no `pagehide`/`beforeunload`), `sem_batimento` (o watchdog de 60 s de hoje) e
`operador_desligou`. Cada um fecha **apenas** a sessão daquele usuário.
**F2-P0.2** A câmera só para quando `sessoes_vivas() == 0` (já é a regra) — provar com **dois usuários**: um
sai (ou perde conexão) e a transmissão **continua** por causa do outro; o segundo sai e aí para.
**F2-P0.3** Teto do tempo passa a ser **da sessão do usuário**, **fixado pelo admin** (não é o cliente que
escolhe): o segundo usuário tem o próprio relógio e a câmera não cai na cara dele.
**F2-P1** Recado claro na tela do operador/admin: "no ar por causa de N sessões · a última morre em X".
**F2-P2** Sem conexão de internet no PC do usuário: o batimento já cobre; falta o aviso na tela dele
("a transmissão foi encerrada por queda de conexão") quando ele voltar.

**Prova da fase:** dois navegadores reais; medir a flag e o processo ffmpeg a cada saída; e o teste do
`pagehide` com sonda de navegador de verdade.

## Fase 3 — Radar de óleo: gravação full-time no PC de captura (P0)

**F3-P0.1** Novo módulo `ground/gravacao_continua.py` no bordo: abre a entrada do radar
(`dshow:<dispositivo>`), comprime com o mesmo perfil dos envios e **fatia em blocos de 60 s** num
diretório local (`LECSOR_HD_DIR`, junto ao PC de captura), com um **índice** (`indice.sqlite`) por bloco:
início, fim, bytes, resolução, fps. Bloco curto é o que faz a **linha do tempo** responder rápido.
**F3-P0.2** O serviço sobe junto com o servidor local (como o agente de ordens) e **reinicia sozinho**;
não depende de internet, de sessão nem de flag. **Retenção = anel de disco**: espaço esgotado → grava por
cima do bloco **mais antigo** (nunca para de gravar); cada sobreposição entra na trilha
(`bloco_sobreposto`).
**F3-P0.3** O bordo publica o catálogo de blocos para terra (`POST /api/hd/catalogo`, token do bordo) sem
subir vídeo: terra lista "o que existe no HD da embarcação" (início/fim/tamanho) e o cliente vê
(`GET /api/hd/catalogo?camera_id=`). O cliente **pede o trecho** (`POST /api/hd/pedir` → fila `hd_pedidos`),
o bordo **lê o pedido na flag** e **envia o bloco** (`POST /api/hd/trecho`, bytes crus; bloco que já saiu do
anel volta como `motivo`), e o cliente **baixa** (`GET /api/hd/baixar?id=`) — upload puxado pelo bordo,
nunca conexão de terra para o bordo.
**F3-P0.4** Segurança: o HD é do **radar de óleo**, não das câmeras — a gravação contínua nasce
**desligada** por padrão e o admin liga por embarcação/dispositivo.
**F3-P1** Tela: **linha do tempo** arrastável + filtro por data/hora (o índice por bloco de 60 s responde
"o que existe entre 14:03 e 14:37" sem abrir arquivo), listar blocos, baixar; o mesmo aviso de "baixar antes
de sair" que já existe para as gravações de transmissão, **sem** apagar o bloco do HD (o HD tem retenção
própria, em anel).
**F3-P2** Verificação de integridade do bloco (fechou direito? ffprobe) e marca de "bloco perdido" quando
o app caiu no meio.

**Prova da fase:** sonda com a câmera real; medir o bloco fechado no disco, o índice, a retenção por
espaço (apagar o mais antigo) e o pedido de trecho chegando ao bordo e voltando.

## Fase 4 — Radar por HDMI deixa de ser conversão (P1)

**F4-P1.1** A ingestão do radar passa a `tipo=camera` com `dshow:<dispositivo do HDMI>` — o mesmo caminho das
câmeras (comprime, manda) e, quando a gravação contínua está ligada, **também grava**.
**F4-P1.2** O cadastro por embarcação deixa de pedir `.drq`/`tcp://` e passa a pedir **o dispositivo de vídeo**
(HDMI, **1 por embarcação**) + perfil de compressão; `radar_drq.py`/`radar_tcp.py` saem do fluxo novo (ficam
no repositório como legado, com aviso, até o dono decidir removê-los).
**F4-P1.3** Migração: se houver embarcação com `radar_fonte` antigo gravado, a tela mostra o aviso
"esta configuração era de conversão e não vale mais — escolha o dispositivo HDMI".
**F4-P2** Rótulo/qualidade próprios do radar (área de interesse, taxa) — só o que o dono pedir.

**Prova da fase:** HDMI de bancada (ou a webcam como dublê) ligado como o radar: comprime, aparece na tela
como qualquer câmera e grava em bloco contínuo; a config antiga é recusada com recado claro.

## Fase 5 — Configuração só do admin (P1) + fechamento (P2)

**F5-P1.1** Varredura de tudo que o **cliente** pode configurar hoje (perfil de compressão, qualidade,
temporizador, alvo por câmera, radar) e **retirar da tela do cliente**: ele só vê, aciona a transmissão
dentro do que o admin liberou e baixa o que é dele.
**F5-P1.2** Toda mudança de configuração e toda mudança de flag entram na trilha com quem fez
(`config_alterada`, `desejo_camera_mudou`).
**F5-P2** Runbook no vault + versão 0.7.0 + release + medição final das metas do produto (30 fps, ≤3 s,
≥80% de redução) **nesta** cadeia nova.

**Prova da fase:** teste que tenta configurar como cliente e recebe 403, e a auditoria com os dois eventos.

---

## Armadilhas que o plano já assume (medidas hoje)

- **O lado terra precisa do mesmo `LECSOR_TOKEN_INGESTAO`** do bordo, senão `/api/estado-desejado` responde
  401 e nenhuma flag chega (medido na Fase 0/e2e da 0.6.10).
- **Assinatura/`make_latest`:** release exige `"true"`/`"false"` como string.
- **O app instalado na máquina de teste não representa o PC de captura:** prova sempre pelo build/sonda.
- **`ligados.json` é a memória do bordo:** reiniciar o app não pode "esquecer" o que estava no ar.

## Decisões do dono (19/11/2026)

1. **Retenção: anel de disco (ring buffer).** Grava sempre e, quando o espaço acaba, **sobrepõe o mais
   antigo**. Nada de apagar tudo nem de parar de gravar por falta de espaço — a trilha registra quando um
   bloco antigo é sobreposto.
2. **Blocos curtos** (decisão técnica, confirmada pelo dono): **60 s** por bloco, porque o cliente procura no
   **tempo por data/hora — filtro ou linha do tempo arrastável**. O índice tem de responder "o que existe
   entre 14:03 e 14:37" sem abrir bloco.
3. **O HD fica junto ao computador de captura** (disco local; caminho definido na instalação, `LECSOR_HD_DIR`).
4. **1 radar por embarcação** (um dispositivo HDMI).
5. **O admin fixa o teto** por sessão (não é o cliente que escolhe).

