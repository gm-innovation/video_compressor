**Status:** aprovado (2026-11-13) — implementado na 0.2.7

## Resultado medido por fase (2026-11-13, versão 0.2.7)

- **Fase 1 — P0 feito.** A causa real de "não tenho medição de SSIM" foi medida: a medição do envio ao vivo rodava **antes** de o fluxo existir em `ingestoes` e respondia *"fluxo nao encontrado"* — nunca media nada. Agora a fonte vai junto da medição e o número sobe ao lado terra por `POST /api/qualidade/anuncio` (token de ingestão); `GET /api/qualidade` devolve o último SSIM por fluxo com `idade_s`, `passa`, `alvo_atual` e `alvo_sugerido`. Medido em bancada no mesmo minuto: **cam-02 0,9844 a 2500k** e **cam-01 0,9759 a 1500k** — mais alvo, mais SSIM, como esperado.
- **Fase 2 — P0 feito.** O perfil do envio saiu de `ultrafast` (que desliga o CABAC e joga o fluxo para **Baseline**, medido no ar nas duas câmeras) para `veryfast -profile:v high -bf 0`, com o ajuste num lugar só (`ingestao.ajuste_encode`), usado pelo envio **e** pela medição. Alvo passou a ser **por câmera** (`cameras.alvo`, coluna nova com `ALTER TABLE` no boot); teste mede as duas câmeras saindo com alvos diferentes (2500k e 1500k) e a câmera sem alvo caindo no padrão de antes (sem regressão).
- **Fase 3 — P1 feito.** `qualidade.comparar_alvos` grava a **mesma cena** em 3 alvos + 1 ramo sem perda (referência do SSIM) e devolve clipes + CSV. Medido em bancada: **1500k SSIM 0,9847 / blur 5,45 · 2500k 0,9919 / 5,03 · 4000k 0,9967 / 4,76**. Na tela do admin: coluna "Qualidade (SSIM)" com a idade, coluna "Alvo (só desta câmera)" com o sugerido quando fica abaixo do piso, e o botão "Comparar 1.500k / 2.500k / 4.000k".
- **Fase 4 — P1 medida, não concluída.** `nvenc` existe no ffmpeg do produto mas **não funciona nesta bancada**: *"Driver does not support the required nvenc API version. Required: 13.1 Found: 12.2 — the minimum required Nvidia driver for nvenc is 610.00 or newer"* (driver local 551.76, RTX 4050). CPU medida: **9,2× tempo real** em 1080p30 no preset `veryfast` (≈9 canais) — subir alvo em N canais **não** é limitado por CPU hoje. **ROI por mapa de QP não existe** no libx264 nem no h264_nvenc deste ffmpeg (o que existe é zona por **tempo**, `-x264-params zones=`, aceita) — ROI espacial fica pendente de um encoder que aceite o mapa.
- **Fase 5 — P2 não medida.** Sem enlace de campo (Starlink Maritime, N canais, RTT, cena real) e sem câmera do cliente: continua fora do que foi medido.



# Qualidade da cam-02 e medição de SSIM do fluxo ao vivo — plano de correção

**Projeto:** pipeline de vídeo bordo → terra (`gm-innovation/video_compressor`)
**Pedido do dono (2026-11-13):** *"a cam02 está perdendo bastante qualidade, e ainda não tenho medição de SSIM"*.
**Ordem de execução:** Fase 1 (evidência que falta) → Fase 2 (alvo/perfil por câmera) → Fase 3 (medição lado a lado com o dono) → Fase 4 (eficiência no mesmo bitrate) → Fase 5 (enlace real).

---

## Evidência levantada (medida, não relatada)

| fato | como foi verificado |
|---|---|
| cam-01 chega a **1.485 kbps**, cam-02 a **1.500 kbps** — alvos praticamente iguais | `/v3/paths/list` do mediamtx no lado terra, duas leituras de `bytesReceived` com 12 s de intervalo |
| as duas chegam **1920×1080 H.264 Baseline**, `inboundFramesInError=0`, ~30 fps (355 e 346 quadros em 12 s) | mesma medição no lado terra |
| **nitidez (sem referência)**: cam-01 **4,6028** × cam-02 **5,7672** de blur médio — cam-02 chega ~25% mais borrada com o **mesmo** bitrate/resolução/fps | `ffmpeg -rtsp_transport tcp -i rtsp://127.0.0.1:8554/<fluxo> -t 12 -vf blurdetect -f null -` no lado terra |
| o fluxo de bancada da VPS (`vps-sintetica`) chega em **High**; os dois do PC de captura chegam em **Baseline** | mesma leitura do mediamtx |
| `medicoes_qualidade` **do lado terra tem 0 linhas** (colunas `fluxo_id, ssim, ajuste, resolucao, fps, fonte, medido_em`) | `sqlite3` no `/opt/pipeline/app/db/pipeline.db` |
| `ingestoes` no lado terra tem **0 linhas** | idem |
| a medição de SSIM do produto roda **na máquina de captura** (`ingestao.ao_vivo` → `qualidade.medir_se_preciso`), gravando no banco local; o lado terra nunca a recebe | `ground/ingestao.py:670-679`, `ground/qualidade.py` |
| o alvo de fábrica do envio ao vivo de câmera é **3000k**, mas o medido no ar é ~1500 kbps nas duas | `ground/ingestao.py:666` × medição do mediamtx |

**Conclusão da evidência:** o transporte está limpo (0 erro, 30 fps). O que se mede é (a) **somente a cam-02 tem nitidez pior**, com o mesmo alvo; (b) as duas usam perfil **Baseline** (menos eficiente que High para o mesmo bitrate); (c) o **SSIM não existe no lado terra por construção** — ele é medido na fonte, na máquina de captura, e nunca sobe. Não há como calcular SSIM desses fluxos a partir do lado terra: falta a referência (a fonte crua vive na máquina de captura).

---

## Fase 1 — A medição que falta: SSIM do fluxo ao vivo chega ao lado terra — P0

**Objetivo:** acabar com o "não tenho medição de SSIM" sem depender de alguém olhar a tela da máquina de captura.

- **P0 — diagnóstico na máquina de captura (10 min, precisa do dono):** abrir o app, subir a cam-02 e ler a linha de qualidade já existente na tela/registro local (SSIM e ajuste do envio). Se a medição local não aparecer, é defeito do caminho de medição do envio ao vivo e o conserto entra nesta fase.
- **P0 — subir a medição junto com o envio:** o cadastro já sobe (0.2.5/0.2.6); a medição passa a subir pelo mesmo caminho autenticado — `POST /api/qualidade/anuncio` (token de ingestão, `hmac.compare_digest`) gravando em `medicoes_qualidade` do lado terra, com `fluxo_id`, `ssim`, `ajuste`, `resolucao`, `fps`, `fonte`, `medido_em`. Só a operação vê; o cliente nunca recebe métrica interna.
- **P1 — a tela do lado terra mostra o SSIM por câmera** (admin e lado terra), com a hora da medição, para o dono ler sem abrir a máquina de captura.
- **P1 — o `ajuste` fica registrado junto do SSIM**, para comparar "alvo 1500k → SSIM x" contra "alvo 3000k → SSIM y" com o **mesmo** número de referência.

**Critério de aceite (comando):**
`python tests/test-qualidade-chega-ao-lado-terra.py` — prova, com duas APIs de verdade, que a medição do bordo aparece em `GET /api/qualidade` no lado terra com o fluxo certo, que sem token é 401 e que o cliente não vê a métrica. Mais: no lado terra, `SELECT count(*) FROM medicoes_qualidade` deixa de ser 0 depois de um envio do app.

**Custo:** baixo (uma rota, um cliente de envio, um teste). **Dependência:** a leitura do número local na máquina de captura (P0) precisa do dono rodar um envio.

---

## Fase 2 — Alvo e perfil POR CÂMERA (a causa provável do "cam-02 pior") — P0

**Objetivo:** a cam-02 hoje usa o mesmo alvo e o mesmo perfil da cam-01; igualar alvo entre cenas diferentes é o que produz nitidez diferente no mesmo número de banda.

- **P0 — perfil de codificação:** trocar o perfil de saída do envio ao vivo de **Baseline** para **High** (o medido hoje é Baseline nas duas; a bancada entrega High no mesmo caminho). Mesmo alvo, mais qualidade por bit.
- **P0 — alvo por câmera, não por tela:** o alvo do envio ao vivo passa a ser gravado por câmera (campo no cadastro) e reaplicado ao reenviar, em vez de um default único (3000k) que hoje chega ao ar como ~1500 kbps sem explicação medida.
- **P1 — o alvo sugerido pela própria medição:** se o SSIM da cam-02 ficar abaixo do piso já travado pelo dono (`PISO_QUALIDADE_SSIM=0.9733`), a tela sugere o próximo alvo (ex.: 2.000k, 3.000k) e o dono decide no clique.
- **P2 — registrar qual ajuste entrou no ar** por fluxo, para a medição não ficar órfã ("SSIM de qual alvo?").

**Critério de aceite (comando):**
`python tests/test-alvo-e-perfil-por-camera.py` — duas câmeras no mesmo lado terra, cada uma com seu alvo; o comando gerado para cada fluxo tem o perfil configurado e o alvo dela (não o default). No lado terra, medir os dois fluxos com `ffmpeg … -vf blurdetect` e exigir **perfil High** e `in_bytes` coerente com o alvo pedido.

**Custo:** médio (comando de ffmpeg + campo no cadastro + tela). **Dependência:** nenhuma externa.

---

## Fase 3 — O dono julga a imagem (teste que ele executa) — P1

**Objetivo:** transformar "está perdendo qualidade" em número aceito pelo dono, com o olho dele no mesmo enquadramento.

- **P1 — mesmo enquadramento, 3 alvos:** o app grava 3 clipes curtos da **mesma cena** da cam-02 (ex.: 1.500k / 2.500k / 4.000k) e o dono vê lado a lado com a fonte crua, dizendo em qual delas "ainda serve".
- **P1 — o número medido acompanha cada clipe:** SSIM e blur de cada alvo, registrados na mesma linha do ajuste; o alvo aprovado no olho vira o **padrão daquela câmera**.
- **P2 — a mesma prova para a cam-01**, para não haver duas réguas.

**Critério de aceite (comando):** `python tests/test-comparacao-3-alvos.py` gera os 3 clipes + o CSV de SSIM/blur de cada um (a validação final é o dono apontar o alvo aprovado, e isso fica gravado no cadastro da câmera).

**Custo:** médio. **Dependência:** o dono dizer o alvo aprovado (é a decisão dele, não uma escolha técnica).

---

## Fase 4 — Mais qualidade com a MESMA banda (eficiência) — P1

- **P1 — `nvenc`/aceleração de hardware:** hoje marcado como quebrado na bancada; sem ele o custo de CPU limita subir alvo em N canais. Medir de novo, com o resultado registrado (funciona/não funciona), antes de contar com ele.
- **P1 — ROI por mapa de QP:** gastar bits onde há movimento/detalhe e não no céu/água parados; é o caminho para a cam-02 ficar nítida sem subir banda. Medir com o mesmo SSIM e o mesmo alvo de antes.
- **P2 — comparar Baseline × High × ROI** no mesmo alvo, na mesma cena, com o número na mão.

**Critério de aceite (comando):** `python tests/medir-roi-qp.py` — SSIM e blur por variante, com o alvo fixo e a banda medida no lado terra; exigir uma variante que seja **≥ SSIM da Baseline no mesmo alvo** e banda igual ou menor.

**Custo:** alto. **Dependência:** cenário 1 da bancada (arquivo/4K) para a medida ser comparável ao que já está publicado.

---

## Fase 5 — O número no enlace real — P2

- **P2 — medir no enlace de campo** (Starlink Maritime, N canais, RTT e cena real) com o SSIM subindo ao lado terra (Fase 1) — é a única medição que vale como prova do produto.
- **P2 — registro por câmera do que foi medido e do que ficou fora**, para o fecho não declarar mais qualidade do que foi medido.

**Critério de aceite (comando):** `python tests/medir-no-enlace.py --canais 4 --segundos 300` com saída de SSIM/latência/banda por canal, gravada no lado terra.

**Custo:** alto. **Dependência:** enlace e câmeras do cliente (externo).

---

## Arquivos provavelmente afetados

- `ground/qualidade.py` — publicar o resultado da medição (rota de envio + cliente).
- `ground/ingestao.py` — perfil do encoder, alvo por câmera, envio da medição junto do cadastro.
- `ground/api.py` — `POST /api/qualidade/anuncio` (token) e `GET /api/qualidade` (operação).
- `admin/admin.js` — SSIM por câmera, hora da medição e o alvo sugerido.
- `db/schema-fase4.sql` (+ migração no boot, como na 0.2.5) — coluna de alvo por câmera.
- `tests/test-qualidade-chega-ao-lado-terra.py`, `tests/test-alvo-e-perfil-por-camera.py`, `tests/test-comparacao-3-alvos.py`, `tests/medir-roi-qp.py` — novos.
- `tests/test-instalador-plug-and-play.py` — seção nova rodando o primeiro.
- Release nova (0.2.7) com os 4 instaladores; lado terra da VPS atualizado e reiniciado (`-o ControlMaster=no -o ControlPath=none`, ~60 s).

## Riscos e limites (declarados)

- **SSIM exige a referência (a fonte crua).** Sem ela não existe SSIM do fluxo recebido — por isso a medição passa a ser feita na fonte (bordo) e enviada; o lado terra nunca vai calcular SSIM sozinho.
- **Subir o alvo deixa o produto mais caro de banda**, e o dono travou ≥80% de redução na 0.2.x — o alvo aprovado no olho (Fase 3) tem que caber nesse piso, senão o piso é que muda (decisão dele).
- **`nvenc` pode continuar não funcionando** — então CPU por canal limita quantos canais sobem de alvo.
- **A cena da cam-02 não é medida como "difícil"**: nenhuma medição feita até aqui comparou a **mesma** cena em alvos diferentes; sem a Fase 3, "está pior" continua sendo juízo de imagem, não número.
- **Continuam não-medidos** (declarados desde antes): cenário 2 completo (Starlink, N canais, RTT, cena real), qualidade ao vivo de ponta a ponta e o ROI por mapa de QP.
