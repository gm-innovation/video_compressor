# Câmeras do PC de captura: parar de anunciar câmera que não existe

**Status:** aprovado em 13/11/2026 · **Fases 1–4 executadas** · Fase 5 (duas câmeras reais no PC de teste) pendente — depende do PC

**Evidências de 13/11/2026:**

| o que foi provado | como |
|---|---|
| lista honesta | `python tests/test-dispositivos-honesto.py` → OK (sem câmera: `video=[]`, `padrao=""`, com `motivo`; sem ffmpeg: `erro` explícito; com duas câmeras: as duas listadas) |
| captura sem dispositivo recusada na borda | mesmo teste, item 5: `escolha a camera na lista (nenhum dispositivo de captura foi informado)` |
| nome fixo extinto | mesmo teste, item 4: `ACER HD User Facing` não existe mais em `ground/ingestao.py`; padrão só por `LECSOR_DISPOSITIVO` |
| tela não oferece câmera falsa e diz de onde vem a lista | `node harness-dispositivos.mjs novo/admin {vazio_externa,vazio_local,duas_local}` → DISPOSITIVOS OK nos três casos |
| em produção (VPS) | `GET /api/dispositivos` = `{"video": [], "padrao": "", "maquina": "srv1918673", "motivo": "o ffmpeg nao encontrou camera...", "pedido_de": "outra_maquina"}` |
| ffmpeg declarado e visível | `desktop/servidor.js` (`ffmpegInfo()` no menu *Ver estado do servidor*); `INSTALAR-PC-DE-CAPTURA.md` exige ffmpeg no PATH |
| nada quebrou | `python -m unittest discover -s tests -p 'suite.py' -t .` → OK (25,157 s) |

**Achado (12/11/2026, relato do dono):** "tem duas câmeras conectadas ao computador do teste e o
sistema não reconhece nenhuma, não aparece nenhuma para selecionar; fica aparecendo a webcam do
computador que utilizamos para desenvolvimento."

## 1. Evidência (verificada agora)

| fato | como foi verificado |
|---|---|
| O nome que aparece é **fixo no repositório** | `ground/ingestao.py:500`: `DISPOSITIVO_PADRAO = "ACER HD User Facing"` (a webcam **desta** bancada) |
| Quando a enumeração não acha nada, a API **anuncia esse nome mesmo assim** | `ground/ingestao.py:listar_dispositivos()` devolve `"padrao": video[0] if video else DISPOSITIVO_PADRAO` |
| A tela usa esse campo, então mostra a câmera inexistente | `admin/admin.js` (preencherDispositivos): se `d.video` está vazio, cria a opção com `d.padrao` |
| Uma máquina sem dshow responde exatamente o que o dono viu | `GET /api/dispositivos` na **VPS** (logado como admin) = `{"video": [], "audio": [], "padrao": "ACER HD User Facing", "sintetica": {...}}` |
| Uma máquina com câmera responde diferente | nesta bancada: `{"video": ["ACER HD User Facing"], "audio": ["Microphone Array (AMD Audio Device)"], "padrao": "ACER HD User Facing"}` |
| A lista vem sempre de quem roda a API | `ground/api.py` rota `/api/dispositivos` → `ingestao.listar_dispositivos()` (ffmpeg **local**) |

Consequência: no PC de teste a tela lista **as câmeras de quem responde aquela rota** (a VPS, ou um
lado terra sem dshow) e, quando não há nenhuma, mostra o nome do dispositivo padrão do repositório —
que não existe nessa máquina. Nada indica que as duas câmeras foram tentadas e falharam: elas
simplesmente nunca são enumeradas ali.

## 2. Fases

### Fase 1 — P0 · Enumeração honesta (nunca inventar dispositivo)
- **O que muda:** `ground/ingestao.py:listar_dispositivos()` devolve `"padrao": ""` quando não há
  vídeo, `"erro"` explícito quando o `ffmpeg` não existe no PATH, e `"motivo"` curto quando a
  enumeração falhou; `admin/admin.js` mostra "nenhuma câmera nesta máquina" e **desabilita** o
  transmitir em vez de oferecer um nome falso.
- **Critério de aceite:** `python tests/test-dispositivos-honesto.py` (novo) cobrindo: sem ffmpeg →
  erro claro e sem `padrao`; ffmpeg sem câmera → `video: []`, `padrao: ""`; com câmera → lista real.
- **Custo:** 1 sessão.

### Fase 2 — P0 · Fim do nome fixo
- **O que muda:** `DISPOSITIVO_PADRAO` deixa de ser constante de código: passa a ser
  `LECSOR_DISPOSITIVO` (variável de ambiente) ou a **primeira câmera encontrada**, ou vazio; a
  ingestão recusa iniciar sem dispositivo válido com mensagem clara ("escolha a câmera na lista").
- **Critério de aceite:** teste da Fase 1 cobre os três casos; `grep -c 'ACER HD User Facing'`
  no repositório = 0 fora de nota/evidência.
- **Custo:** 1 sessão.

### Fase 3 — P1 · Dizer de onde vem a lista
- **O que muda:** quando `/api/dispositivos` volta sem nenhuma câmera e o `base` do app **não** é
  local, a tela avisa: "esta lista vem do lado terra &lt;base&gt; — câmera ligada nesta máquina só
  aparece com o **Servidor local** ligado e `base` = `http://127.0.0.1:8765`".
- **Critério de aceite:** harness jsdom com duas respostas (`video: []` com base externa e com base
  local) mostrando os dois textos.
- **Custo:** 1 sessão.

### Fase 4 — P1 · ffmpeg é requisito declarado no PC de captura
- **O que muda:** `INSTALAR-PC-DE-CAPTURA.md` passa a listar **ffmpeg no PATH** como item obrigatório
  (hoje só cita Python) e o menu **Servidor local → Ver estado** mostra "ffmpeg: ok / não encontrado".
- **Critério de aceite:** em máquina sem ffmpeg, o estado diz "não encontrado"; com ffmpeg, mostra a versão.
- **Custo:** meia sessão.

### Fase 5 — P2 · Prova com as duas câmeras no PC de teste
- **O que muda:** nada de código.
- **Critério de aceite:** `GET http://127.0.0.1:8765/api/dispositivos` nesse PC listando as **duas**
  câmeras, cada uma transmitindo e aparecendo no lado terra.
- **Dependência:** o PC de teste com as câmeras e o Servidor local no ar.

## 3. Riscos e limites (declarados)
- Não sei, daqui, se as duas câmeras **chegam a ser vistas pelo Windows** naquele PC: se o ffmpeg dali
  não listar, o problema é driver/porta USB (ou ffmpeg ausente), não o app — o comando da Fase 5 diz.
- Câmera USB genérica pode aparecer com nome genérico ("USB Video") ou em branco; a Fase 2 resolve a
  escolha, mas quem escolhe continua sendo o operador na tela.
