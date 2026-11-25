# Organizar as telas do admin e do cliente (e o escopo do observador)

Data: 25/11/2026 · Repo: `lecsor-pipeline-video` · Base medida: `main` = `564ded1` (v0.18.0)
Status: **AGUARDANDO APROVAÇÃO** (só implementa com "aprovado")

## 1. O que foi medido (varredura de 25/11/2026)

Varredura feita por leitura de código nas 32 telas: **22 do admin** (`admin/index.html` `data-tela` + `SUBS` de `admin/admin.js`) e **10 do cliente** (`app/index.html` + `TELAS`/`desenharTela` de `app/app.js`), mais o filtro do observador (`eh_camera_de_radar` em `ground/api.py`) e o `abrirObservador()`.

Sem função efetiva (5): `pessoas` (tabela vazia + texto fixo), `avisos` (só `localStorage`), `analises` (admin: tabela `analytics_agentes` vazia), `marcas` (nenhum bordo/agente lê `marcas`/`zonas`), `alertas`/`relatorios` (cliente: mesma tabela vazia).

Redundantes (7 + 6): `clientes`/`embarcacoes`/`cameras` repetem `empresas`; `tempo`/`producao` repetem `frota`; `painel`/`fases`/`medicoes`/`decisoes`/`evidencias`/`documentos` são 6 telas de **projeto** (não do produto); `envios` é ferramenta de bancada.

Cobertura/não coberto: o observador (Petrobrás/IBAMA) só vê `visualizar` ("Radar ao vivo") + `radar_hd`; o filtro é **por nome** (`"radar" in id/rotulo/fluxo_id/local/alvo`). A **câmera FLIR não existe** no repo (`flir`/`termic`/`infraverm` = 0 arquivos).

## 2. Objetivo

Deixar o admin com duas áreas de operação (a área única do cliente + o monitoramento da frota), tirar do menu o que não funciona ou não pertence ao produto, e fazer o observador ver **por tipo** — radar de óleo e FLIR (se houver) —, não por nome.

## 3. Fases

### Fase 1 — Admin: consolidar em duas áreas (P0)
- P0: `empresas` passa a ser a área única (empresa → embarcação → câmera, com licença, ligar/desligar, ativar, qualidade) e absorve o que ainda é útil de `clientes`/`embarcacoes`/`cameras`; as três saem do menu.
- P0: `frota` passa a ser a área de acompanhamento (CPU/memória/disco/rede + vídeo ao vivo) e absorve `tempo` e `producao`; as duas saem do menu.
- P1: redirecionar as rotas antigas do front para as duas áreas (nada de tela órfã); manter o `despacho` sem tela morta.
- P2: rótulos/SUBS das duas áreas escritos para o leigo (o que o dono lê no primeiro olhar).

### Fase 2 — Tirar o que não funciona (P0)
- P0: `pessoas` (cliente) sai do menu e do `desenharTela` (é um texto fixo de LGPD; enquanto o reconhecimento não existir, não é tela).
- P0: `avisos` (cliente) sai do menu ou vira um item dentro de `configuracao` (hoje não chama nenhuma rota).
- P1: `analises` (admin) e `alertas`/`relatorios` (cliente) ficam anunciadas como "depende do agente de bordo (Fase 5)" **ou** saem do menu até existir o agente — decisão do dono.
- P1: `marcas` (admin) sai do menu até existir quem consuma as marcas/zonas no bordo.

### Fase 3 — Área de projeto (P1)
- P1: as 6 telas de projeto (`painel`/`fases`/`medicoes`/`decisoes`/`evidencias`/`documentos`) saem do menu do produto e ficam num grupo próprio ("Projeto LECSOR", só admin) — não são operação do cliente.
- P2: `db/fases-seed.json` (parado em 09/11/2026) atualizado ou a área congelada explicitamente.

### Fase 4 — Observador por tipo: radar e FLIR (P0 na decisão, P1 na obra)
- P0 (decisão): adotar `tipo` de câmera no cadastro (`camera` | `radar` | `flir`), gravado pelo bordo; o filtro do observador passa a ser `tipo in ("radar","flir")` e não o nome.
- P0: migração das câmeras existentes (o nome atual entra como `tipo` quando contém "radar"; caso contrário `camera`).
- P1: `eh_camera_de_radar` → `pode_o_observador_ver` (lê `tipo`); `POST /api/cameras` (bordo) e a tela de cadastro do bordo ganham o `tipo`.
- P1: tela do cliente ganha o agrupamento "Radar de óleo" e "FLIR" quando houver câmera FLIR; o observador recebe as duas.
- P2: rótulo "Radar de óleo (HD)" só aparece quando houver radar na embarcação.

### Fase 5 — Verificação (P0)
- P0: suíte `tools/regressao-0130.py` verde (34 provas) + `python -m unittest discover -s tests -p "test_*.py"`.
- P0: prova nova: `tests/test-observador-por-tipo.py` (observador vê radar e FLIR de qualquer empresa; não vê `camera`).
- P0: smoke de ponta a ponta (`tools/regressao-smoke.py --completo`) sem regressão nova; a J5/J10 seguem com a falha de saída já registrada (correção à parte).
- P1: print das duas áreas do admin e da tela do observador (antes/depois) anexado ao resultado.

## 4. Fora de escopo (registrado)

- Corrigir a saída da tela do cliente (J5/J10) — outro plano.
- Ligar a gravação a bordo pelo admin (`gravacao_continua`) — outro plano.
- Agente de bordo (analytics/marcas) — Fase 5 do produto, não é "organizar telas".

## 5. Critério de pronto

Menu do admin com **duas** áreas de operação + o grupo de projeto; menu do cliente sem tela sem função; observador filtrando por `tipo`; 34+ provas verdes; smoke sem regressão nova; print anexado.
