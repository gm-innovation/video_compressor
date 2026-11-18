# Instalação — transmissão a pedido do cliente

Rodada de 17/11/2026: o **cliente** abre a transmissão pela **web** e a ordem **vai de terra para bordo**.
Este documento diz o que muda na máquina de captura e o que o cliente faz (nada a instalar).

## 1. O que o CLIENTE faz (sem instalar nada)

1. Abre o navegador (computador ou **telefone**) no endereço do lado terra: `http://<lado-terra>/app`.
2. Entra com o acesso da empresa (usuário criado pelo administrador; não existe cadastro livre).
3. Menu **Transmitir** → acha a embarcação e a câmera → **Iniciar transmissão**.
   A tela responde na hora: *"pedido enviado à máquina de captura…"* e, quando o bordo atende,
   vira **no ar** com o **tempo restante**.
4. **Tempo de transmissão** → escolhe o tempo máximo → **Gravar tempo**.
   Ao estourar, a transmissão **para**; o cliente **reinicia** se quiser (nada reinicia sozinho).
   **Exceção:** se estiver **gravando**, o corte não acontece.
5. **Gravações** → histórico do que já foi transmitido, com o **tempo** e o **download** do arquivo.
   Nada é apagado do histórico.
6. **Fechar a tela ou desligar o computador derruba só a sessão de quem fechou.**
   Se outro cliente da mesma empresa estiver vendo, continua vendo; quando ninguém mais está vendo,
   a câmera para no bordo.

A tela do cliente foi medida num telefone de 390 px de largura (iPhone 14 / Android médio):
cabe sem beliscar a tela, e os botões têm 40 px de altura (alvo de dedo).

O agente guarda em disco o que ele ligou (`ground/ordens/ligados.json`): se a máquina de captura
reiniciar, ele ainda sabe o que estava no ar e corta sozinho o envio que passar do **teto do bordo**
(`LECSOR_TETO_DO_BORDO`, padrão 2 h) sem ordem viva — é a rede de segurança do envio órfão.

## 2. O que instala na MÁQUINA DE CAPTURA (uma vez, no cliente)

Duas peças, as duas no computador onde as câmeras estão ligadas:

| Peça | Arquivo | Para que serve |
|---|---|---|
| Sistema de captura | `ground/api.py` | liga/desliga as câmeras, comprime e envia para o lado terra |
| **Agente de ordens** | `ground/agente_de_ordens.py` | **recebe a ordem do cliente** e liga/desliga a câmera |

O agente é a peça nova: **o bordo não abre porta nenhuma** — ele **pergunta** ao lado terra se há ordem
(`GET /api/ordens`) e devolve o resultado (`POST /api/ordens/<id>/resultado`). Não há técnico a bordo:
ninguém confirma nada, a máquina obedece direto.

Variáveis de ambiente do agente (arquivo de ambiente do serviço — **nunca** no repositório):

| Variável | O que é |
|---|---|
| `LECSOR_LADO_TERRA_API` | endereço do lado terra (ex.: `http://<lado-terra>:8085`) |
| `LECSOR_TOKEN_INGESTAO` | token de ingestão da embarcação (**segredo**, ver §4) |
| `LECSOR_EMBARCACAO` | qual embarcação este computador serve (ex.: `bancada`) |
| `LECSOR_PORTA_LOCAL` | porta da API local do sistema de captura (padrão `8085`) |

Rodar como serviço para voltar depois de reiniciar a máquina:

```
# Linux (systemd) — arquivo lecsor-agente.service
ExecStart=/usr/bin/python3 /opt/lecsor/ground/agente_de_ordens.py
EnvironmentFile=/etc/lecsor/agente.env
Restart=always
```

Se a API local estiver fora do ar, o agente **avisa** ("nao alcancei a API local") e **não** marca a ordem
como atendida — ele nunca inventa sucesso.

## 3. Onde ficam as gravações

No **lado terra** (variável `LECSOR_GRAVACOES_DIR`), do vídeo que **já chegou** pela rede: gravar no bordo
gastaria o link duas vezes. A cópia é `-c copy` (sem recodificar). O arquivo em andamento fica `.parcial.mp4`
fragmentado (sobrevive a queda) e vira `.mp4` ao parar. O download exige a sessão do dono da transmissão.

## 4. Regra de credencial (não é opcional)

- **Credencial de câmera/DVR nunca circula** em chat, e-mail ou repositório, e **não se digita senha em
  formulário**: usuário dedicado **somente-leitura e temporário**, entrega por cofre ou variável de ambiente
  no servidor de captura, **autorização escrita do cliente anexa ao plano**, revogação no fim da fase.
- O vídeo é adquirido **por dentro da VPN** — a porta RTSP **nunca** publicada na internet.
- O token de ingestão é segredo do servidor: só em arquivo de ambiente, nunca em linha de comando visível.

## 5. Como saber, na hora, que está funcionando

| O que se olha | Certo | Se estiver errado |
|---|---|---|
| A tela do cliente, depois de clicar em Iniciar | "pedido enviado à máquina de captura…" | o pedido nem saiu: a sessão caiu ou falta permissão de cliente |
| O log do agente no bordo | "ordem recebida" / "atendeu" | "o lado terra recusou… (401 token…)" → token errado |
| A câmera na captura | ligou (status no sistema de captura) | "nao alcancei a API local" → o sistema de captura está parado |
| A tela do cliente, alguns segundos depois | **no ar**, com tempo restante | passou de 90 s sem resposta: a tela avisa e a sessão morre sozinha |

## 6. Quem mais mexe (operação e administrador)

- **Operação (tela `/admin`, menu "Enviar vídeo")**: em **"Transmissões pedidas pelos clientes"** a
  operação vê os pedidos abertos de todas as embarcações (embarcação, câmera, quem pediu, tempo,
  estado, quanto resta) e **cancela** o pedido de um cliente. Cancelar encerra **aquela** sessão e,
  se ninguém mais estiver vendo, o bordo recebe a ordem de parar. O histórico guarda
  "cancelada pela operação (e-mail)" — nada apagado.
- **Administrador (mesma tela, mesmo menu)**: define o **teto do produto** — o maior tempo que
  **qualquer** cliente pode escolher (5/15/30/60/120 min ou sem teto). O cliente vê a lista dele já
  cortada pelo teto e o servidor corta de novo no pedido (pedido acima do teto sai com o teto).
- **Endereço do cliente**: a tela **Clientes** mostra o endereço da tela do cliente
  (`http://<lado-terra>/app/`) com o botão de copiar — vai junto com o acesso, sem manual.

## 7. O que o cliente NÃO precisa

- **Não** instala aplicativo (é web, inclusive no telefone).
- **Não** precisa de técnico a bordo para iniciar a transmissão.
- **Não** abre porta no bordo (nenhum acesso de fora para dentro da captura).
