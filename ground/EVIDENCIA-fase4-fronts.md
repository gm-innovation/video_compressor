# Evidência — Fase 4: fronts do cliente (`app/`) e do admin (`admin/`)

Data: 2026-11-06 · bancada (mesmo computador), servidor de terra = `mediamtx` v1.21.3 + SQLite
Autor: Hermes (Marina) · tudo abaixo foi executado, não descrito de memória.

## O que passou a existir

| Peça | Arquivo | O que faz |
|---|---|---|
| Front do cliente | `app/index.html` + `app/app.js` | entrar, escolher embarcação, grade ao vivo 1/2/4/9 por WebRTC, estado por câmera |
| Front do admin | `admin/index.html` + `admin/admin.js` | módulo §6 (fases, medições, decisões, evidências, documentos com exportação PDF), frota, análises, auditoria |
| Player resiliente | `fronts/video.js` | sessão WebRTC com reconexão automática e HLS de reserva, tudo pela API |
| API do produto | `ground/api.py` | sessão por usuário (cookie HttpOnly), papéis, porta única do vídeo, auditoria de acesso |
| Schema | `db/schema-fase4.sql` | `clientes`, `embarcacoes`, `cameras`, `usuarios`, `sessoes`, `auditoria_acesso`, `documentos`, `decisoes`, `analytics_eventos`, `analytics_contagens` |

## Verificações executadas (comando → resultado)

1. **Porta única do vídeo**: `curl -b cookies -H 'Content-Type: application/sdp' --data-binary <oferta> /whep/cam-01-demo`
   → resposta SDP real do `mediamtx` (200) e sessão criada com `peerConnectionEstablished: true`.
2. **Isolamento por cliente (multi-inquilino)**: cliente do armador pedindo câmera da LECSOR
   → `403 {"erro": "voce nao tem acesso a esta camera"}` e registro `acesso_negado` em `auditoria_acesso`.
3. **Sem sessão**: `GET /api/cameras` → `401 {"erro": "entre no sistema"}`.
4. **Nada de infraestrutura no navegador**: o JSON de `/api/cameras` não contém nenhum de
   `credencial, senha, password, rtsp, srt, 127.0.0.1, 8888, 8889, 8890, 9997` (varredura automática: nenhum termo).
5. **Banco manda no número**: `POST /api/medicoes` sem campos → `422` com `campos_faltando`;
   com os cinco campos → `201`. `POST /api/decisoes` incompleto → `422`.
6. **Papel**: cliente tentando gravar medição → `403 {"erro": "so operador/admin grava medicao"}` (defeito achado por teste e corrigido);
   cliente tentando gravar decisão → `401`; operador → `201`.
7. **Exportação PDF pelo sistema**: `GET /api/relatorios/pipeline.pdf` (operador) → `200`, `application/pdf`, 542.010 bytes, 13 páginas;
   mesmo pedido pelo cliente → `401`.
8. **Front do cliente na tela**: login `cliente@armador-demo.test` → aparece "PSV Exemplo (demo) (IMO 9123456)",
   duas câmeras com vídeo (relógio queimado visível no quadro), rodapé com dado real do encoder
   (`libx264 · 1280x720 · 30 fps · encode 1500k` e `800k`).
9. **Front do admin na tela**: login `operacao@lecsor.test` → cartões (fases 1/9 concluídas, 46 medições, 1 decisão,
   4 evidências, 4/4 câmeras no ar), tabela de fases, evidências, abas de frota, análises, documentos e auditoria.

## Defeitos encontrados e corrigidos nesta rodada

- `<script src="/app.js">` resolvia para a raiz e dava 404 (a página não logava) → caminho absoluto `/app/app.js` e `/admin/admin.js`.
- O cliente conseguia gravar medição porque a exceção de loopback (bancada) valia para qualquer requisição:
  agora, **com sessão de cliente, a escrita é recusada**; a exceção de loopback só vale **sem sessão**.
- Pílula de estado ficava presa em "conectando…" mesmo com vídeo (o `connectionState` volta a `connected`):
  passou a marcar "no ar (WebRTC)" no `connected`, e o rodapé de dados é sempre atualizado pelo ciclo de 5 s.
- `encoder` vinha vazio para a câmera do cliente demo: a busca do perfil usava o id da câmera em vez do `fluxo_id`.

## Ainda não feito (não confundir com pronto)

- Fase 4-C/4-D do plano: histórico com linha do tempo, alertas, indicadores no front do cliente e tela de RBAC.
- Fase 5: as tabelas e as rotas de evento/contagem existem, mas **nenhum agente de análise está a bordo** — a tela de análises mostra o vazio.
- Login sem limite de tentativas; contas de demonstração são de bancada (senha gerada na hora, só o hash no banco).
- Papéis exercitados: `cliente` e `operador`. O papel `admin` não foi exercitado em tela nesta rodada.

## Revisão do front do cliente no formato VMS (06/11/2026)

O dono mostrou uma referência de VMS e pediu o front do cliente "dessa forma". Refeito:

- **Casca escura com barra lateral**: marca LECSOR, grupos EVENTOS (Visualizar, Alertas, Gravações, Relatórios),
  CADASTROS (Pessoas, Câmeras) e CONFIGURAÇÃO (Avisos), com o usuário logado no rodapé da barra.
- **Cabeçalho**: título "Transmissões ao vivo", subtítulo, seletor de embarcação, `Automático`, `2×2`, `3×3`, `4×4`,
  pílula `IA · Análises`, `Tela cheia` e `sair`.
- **Grade**: janelas 16:9 que preenchem o espaço (sem tarja), relógio do navegador no canto superior direito de cada
  janela e nome da câmera com indicador de estado no canto inferior esquerdo; clique na janela tira/põe a câmera na
  seleção, duplo clique abre em tela cheia.
- **Paginação** por página de câmeras (só aparece com mais de uma página) e **rodapé** com "Ver todos os alertas",
  "Relatórios", "Mostrando 1-N de M câmeras selecionadas" e "Limpar seleção".
- **Telas ligadas a dado real**: Alertas (câmera fora do ar + eventos da Fase 5), Relatórios (estado, bitrate e
  espectadores por câmera + contagens), Câmeras (inventário liberado), Pessoas (explica que o reconhecimento está
  desligado por LGPD), Gravações (explica que a retenção é Fase 3, P1) e Avisos (preferência do usuário no navegador).
- **Caixas de detecção** só são desenhadas quando existe evento real com caixa nos metadados (nada inventado na tela).
