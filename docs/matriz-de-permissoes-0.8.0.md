# Matriz de permissões — escopos de cliente, captura e observador (plano de 19/11/2026)

Provado por HTTP em `tests/test-papeis-de-config.py`, `tests/test-escopos-de-acesso.py` e
`tests/test-fluxo-no-lado-terra.py` (rc=0), e por tela em `tests/e2e-tela-do-captura-so-cadastra.py`,
`tests/e2e-escopo-no-admin.py` e `tests/e2e-observador-do-radar.py` (rc=0). Não é leitura de código: a
API sobe de verdade e responde 401/403/201.

| Ação | cliente | observador (Petrobras) | técnico/captura | operador | admin |
|---|---|---|---|---|---|
| Cadastrar usuário | não | não | não | não | **sim** |
| Conceder/revogar embarcação por usuário | não | não | não | não | **sim** |
| Cadastrar câmera **remoto** | não | não | não | **sim** | **sim** |
| Cadastrar câmera **na própria máquina de captura** | não | não | **sim** | **sim** | **sim** |
| Varrer os dispositivos desta máquina (`POST /api/varredura`) | não | não | **sim** (local) | **sim** | **sim** |
| Publicar configuração do bordo (`/api/config`) | não | não | não | **sim** | **sim** |
| Ver desejada × aplicada (`GET /api/config`) | não | não | não | **sim** | **sim** |
| Ler o que terra publicou (`/api/config-desejada`) | não | não | **só com o token do bordo** | não | não |
| Ver o próprio vídeo | **sim** (o escopo dele) | não | não | sim | sim |
| Ver **só uma/algumas** embarcações da empresa (tipos 1 e 2) | **sim** (com vínculo) | não | não | sim | sim |
| Ver **todas** as embarcações da empresa (tipo 3) | **sim** (sem vínculo) | não | não | sim | sim |
| Ver o **radar de óleo de todas as empresas** (tipo 4) | não | **sim** | não | não | **sim** |
| Ver câmera comum de outra empresa | não | **não** | não | não | sim |
| Ver analytics/agentes | sim (da empresa dele) | **não** | não | sim | sim |
| Operar (ligar/desligar, transmitir, publicar) | não | **não** | só nesta máquina | sim | sim |
| Exportar relatório PDF | não | não | não | não | **sim** |
| Ler a auditoria | não | não | não | não | **sim** |

## Os 4 escopos de cliente (dono, 19/11/2026)

| Tipo | Quem é | Como fica no banco | O que vê |
|---|---|---|---|
| 1 | cliente de **uma** embarcação | 1 linha em `usuario_embarcacoes` | exatamente aquela |
| 2 | cliente de **algumas** embarcações | N linhas em `usuario_embarcacoes` | exatamente aquelas |
| 3 | cliente da empresa inteira | **zero** linhas (o padrão de sempre) | todas as da empresa dele |
| 4 | Petrobras | papel `observador`, sem vínculo | o **radar de óleo** de todas as embarcações, de todas as empresas — só leitura |

Regras que sustentam a matriz:

- **Um app só, a tela vem da role** (dono, 17/11/2026): `cliente → /app`, `observador → /app` (visão de
  radar), `operador|admin → /admin`, `técnico|captura → /`. A interface não decide permissão — o servidor
  decide, a tela só obedece.
- **A regra de visão é uma só** (`pode_ver_embarcacao`): operador/admin veem tudo, o `observador` vê tudo e
  não opera (as rotas de escrita checam `admin`, não a função de visão), e o cliente vê o que tem vínculo —
  ou, sem vínculo nenhum, todas as da própria empresa (tipo 3, retrocompatível).
- **"Local" é o pedido que vem da própria máquina de captura** (`127.0.0.1`/`::1`). É isso que libera o
  cadastro e a varredura para o usuário de captura: a captura só existe onde a câmera está plugada.
  Técnico falando de outro IP **não** cadastra. A sessão do usuário de captura é atendida **no bordo**
  (`/api/entrar`, `/api/eu`, `/api/sair` são locais): sem isso, o bordo cadastrava e a câmera ia só para
  terra (defeito medido em 19/11/2026, corrigido na Fase 3).
- **O cadastro automático é do bordo** (plano, Fase 2): o app varre os dispositivos desta máquina e publica
  o que achou. Terra não manda lista de câmeras — terra só decide depois (`transmitir`, alvo, teto). O radar
  de óleo **não** é cadastrado como câmera: ele é por embarcação.
- **Configuração nasce em terra, nunca no bordo** (dono, 19/11/2026): o bordo não tem porta aberta, só
  envia. Quem publica é operação/admin; o bordo busca pelo próprio token e confirma o que aplicou.
- **O que não vem de terra, por fato físico** (declarado, não prometido): o `dshow:<dispositivo>` da
  máquina, a pasta do HD (`LECSOR_HD_DIR`) e o endereço de rede local. Isso é cadastrado pelo usuário de
  captura, porque terra não conhece e não alcança.
