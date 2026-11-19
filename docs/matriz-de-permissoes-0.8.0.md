# Matriz de permissões — 0.8.0 (Fase 3)

Provado por HTTP em `tests/test-papeis-de-config.py` (rc=0) e por tela em
`tests/e2e-tela-do-captura-so-cadastra.py` (rc=0). Não é leitura de código: a API sobe de verdade e
responde 401/403/201.

| Ação | cliente | técnico/captura | operador | admin |
|---|---|---|---|---|
| Cadastrar usuário | não | não | não | **sim** |
| Cadastrar câmera **remoto** | não | não | **sim** | **sim** |
| Cadastrar câmera **na própria máquina de captura** | não | **sim** | **sim** | **sim** |
| Publicar configuração do bordo (`/api/config`) | não | não | **sim** | **sim** |
| Ver desejada × aplicada (`GET /api/config`) | não | não | **sim** | **sim** |
| Ler o que terra publicou (`/api/config-desejada`) | não | **só com o token do bordo** | não | não |
| Ver o próprio vídeo | **sim** (a empresa dele) | não | sim | sim |

Regras que sustentam a matriz:

- **Um app só, a tela vem da role** (dono, 17/11/2026): `cliente → /app`, `operador|admin → /admin`,
  `técnico|captura → /`. A interface não decide permissão — o servidor decide, a tela só obedece.
- **"Local" é o pedido que vem da própria máquina de captura** (`127.0.0.1`/`::1`). É isso que libera o
  cadastro para o usuário de captura: a captura só existe onde a câmera está plugada. Técnico falando de
  outro IP **não** cadastra.
- **Configuração nasce em terra, nunca no bordo** (dono, 19/11/2026): o bordo não tem porta aberta, só
  envia. Quem publica é operação/admin; o bordo busca pelo próprio token e confirma o que aplicou.
- **O que não vem de terra, por fato físico** (declarado, não prometido): o `dshow:<dispositivo>` da
  máquina, a pasta do HD (`LECSOR_HD_DIR`) e o endereço de rede local. Isso é cadastrado pelo usuário de
  captura, porque terra não conhece e não alcança.
