**Status: APROVADO E IMPLEMENTADO na 0.14.0** (dono disse "aprovado" em 24/11/2026). Implementado: Fase 1
(janela reaproveitada + proporção sempre aplicada + linhas reais), Fase 2 (`bPar`/`bGrav` religados), Fase 3
e 7 (tela "Monitoramento (frota)" com os quatro números, camada individual e vídeo ao vivo somente leitura),
Fase 4 (rede + individual/global), Fase 4-bis (rótulo "disponível" + conferência medida), Fase 6 (dashboards
do `/bordo`). Provas: `tests/e2e-tamanho-fixo-dashboards-e-telemetria.py` (novo) + `tools/regressao-0130.py`.

**Status original (histórico):** aguardando aprovação (plano dos 4 pedidos do dono de 24/11/2026, depois do teste da 0.13.2).

# Tamanho da imagem parado, "Parar transmissão" sempre clicável, vídeo no admin e telemetria do PC de captura

## O que o dono pediu (verbatim, 24/11/2026)

> não ficou legal o tamanho das imagens e outra coisa, elas ficam mudando o tamanho, diminuem não entendo o
> porquê. quando eu paro a transmissão e depois reinicio, o botão de parar transmissão fica desativado.
> preciso também que os videos sejam transmitidos no admin para eu acompanhar e monitorar. mais uma, preciso
> que o computador de captura envie também as informações de telemetria do computador com cpu, memória, disco
> e rede, individual e global

## Evidência (fato | como foi verificado)

| # | Fato | Como foi verificado |
|---|---|---|
| 1 | **A imagem muda de tamanho porque o `<video>` é RECRIADO a cada redesenho** — e, no elemento novo, a proporção da câmera **não é reaplicada** | `app/app.js`: `desenharVisualizar()` faz `limpar(palco)` (linha 185) e monta a grade do zero (janelas e `<video>` novos) a cada troca de assinatura de tela (o `atualizar()` roda a cada 5 s); `proporcaoDaImagem()` sai cedo em `if (S.proporcao[c.id] === r) return;` **antes** de gravar `img.style.aspectRatio` — então a área nova fica no 16/9 do CSS, com a imagem em `contain` **menor e com barra** |
| 2 | **O `S.proporcao` sobrevive, o layout não:** a proporção conhecida existe em `S`, mas o nó novo não a recebe; e `ajustarGrade()` só escreve a proporção em quem **não** tem valor conhecido | mesma leitura (`ajustarGrade()`, laço final `if (img && !S.proporcao[j.dataset.cam])`) |
| 3 | **A altura é calculada para `linhas = n`, não para as linhas realmente usadas** → com 2 câmeras em grade `g2` (2×2) a imagem usa **metade** da altura que poderia | `porPagina()` (2/3/4) × a `grade.dataset.linhas = String(n)`; a conta `porAltura = r*(ah - (linhas-1)*laco - linhas*cardH)/linhas` divide por 2 com 2 câmeras |
| 4 | **"Parar transmissão" fica desativado** | `app/app.js`: `pararTransmissao()` (linha 1120) faz `botao.disabled = true; botao.textContent = 'parando…'`; `atualizarControle()` **nunca** devolve `bPar.disabled = false` (só o `bIni` é religado, na linha 927). Ao reiniciar, o mesmo botão volta a ser usado — desativado |
| 5 | **O admin não tem onde ver o vídeo do cliente** | `admin/admin.js` (linha ~1433): o que existe é "Transmitir ao vivo (contínuo)", que é a tela da **bancada** (a máquina que transmite), não um **visor** das sessões abertas; a grade de vídeo só existe em `app/app.js` |
| 6 | **A telemetria do bordo não tem rede** — e o que tem é só o global da máquina | `ground/saude_do_bordo.py`: o retrato leva `cpu_pct`, `memoria_pct`, `memoria_livre_mb` e `discos` (com o HD do radar); **não há** campo de rede, nem quebra por câmera/processo |
| 7 | **O painel do bordo é uma grade de 7 blocos iguais** — sem hierarquia, sem número grande, sem indicador que se leia de longe | `bordo/index.html`: `.bloco` × 7 ("O que está acontecendo agora", "Licença desta máquina", "Envio para o lado terra", "Agente de ordens", "Varredura das câmeras", "Saúde e desempenho", "Como esta máquina se configurou sozinha"), `grid-template-columns: repeat(auto-fit, minmax(320px,1fr))`, linhas 33-98 |
| 8 | **A informação está certa, mas o rótulo do "livre" é de outra definição** — medido nesta máquina (24/11/2026): o módulo diz `memoria_livre_mb = 11132` e o SO (`Win32_OperatingSystem.FreePhysicalMemory`) diz **10592 MB** — 5 % de diferença, porque o módulo usa o "disponível" do `psutil` (inclui cache/standby) e o SO publica o "livre" | `python -c "import ground.saude_do_bordo as s; print(s.retrato())"` × `powershell Get-CimInstance Win32_OperatingSystem`. A **porcentagem** bate: 66,9 % (módulo) × 67 % (SO) |
| 9 | **O retrato já mede tudo com `psutil` nesta máquina** (`psutil 7.2.2`) e `nao_medido = {}` — nenhum número inventado | mesma execução |

## Decisões (uma linha cada; o dono confirma ou troca)

- **D-T1 — "individual e global"?** *Proposta:* **individual = por câmera/encoder** (CPU, memória, kbps e
  estado de cada fluxo no PC de captura) e **global = a máquina inteira** (CPU, memória, disco, rede). Se o
  dono quiser outro recorte (por processo, por disco, por interface), é aqui que ele troca.
- **D-T2 — rede:** `rede` no global = MB enviados/recebidos **por interface** (somatório) com a taxa atual;
  a API só entrega ao admin (mesma regra da saúde hoje).
- **D-T3 — o vídeo no admin:** o admin vê **a mesma grade do cliente** (as sessões abertas), em modo
  **assistir** (sem os botões de ligar/parar/gravar do cliente) — e o dono já fixou (D3, 24/11/2026) que
  **quem sustenta a transmissão é a sessão de quem assiste**: abrir no admin passa a contar como audiência.
  Se ele preferir que o admin **não** conte como audiência, muda a regra do lado terra.
- **D-T4 — o tamanho da imagem:** a imagem ocupa o **maior retângulo** que cabe na área disponível, sem
  corte — o "tamanho" passa a ser decidido pela tela do usuário (e para de mudar sozinho).

## Fase 1 — O tamanho da imagem para de mudar (P0 + P1)

- **P0** `app/app.js` — `proporcaoDaImagem()`: gravar `img.style.aspectRatio` **sempre** (o que já é conhecido
  entra no nó novo na hora) e só disparar `ajustarGrade()` quando a proporção **mudou**.
- **P0** `app/app.js` — `desenharVisualizar()`: **não recriar** a janela/`<video>` de câmera que já está na
  tela (aproveitar o nó existente e só atualizar rótulo/estado/controle); criar somente o que falta e remover
  somente o que saiu. Hoje o `limpar(palco)` joga tudo fora a cada 5 s — é a causa direta do "muda de tamanho".
- **P0** `app/app.js` — `ajustarGrade()`: `linhas` = **linhas realmente usadas** (`Math.ceil(cameras / cols)`),
  não `n` — com 2 câmeras a imagem passa a usar a altura inteira.
- **P1** `app/app.js` — ao ganhar/atualizar a proporção, recalcular **sem** saltar: manter a proporção
  conhecida para os nós que já existem e só redimensionar quando o conjunto muda.
- **P1** `fronts/vms.css`: conferir que a soma (imagem + card) respeita o palco com o card em 1 ou 2 linhas.

## Fase 2 — "Parar transmissão" sempre clicável (P0)

- **P0** `app/app.js` — `atualizarControle()`: devolver `bPar.disabled = false` (e `bGrav.disabled = false`)
  em **toda** passagem, como já é feito com o `bIni`; o estado "parando…/gravando…" só vale enquanto a
  requisição está em curso.
- **P0** `app/app.js` — `pararTransmissao()` / `marcarGravando()`: em caso de erro, o botão volta ao texto e
  ao estado clicável (hoje só o sucesso reconstrói).
- **P1** prova: iniciar → parar → iniciar → parar, duas vezes seguidas, com o botão clicável no fim.

## Fase 3 — O vídeo no admin para acompanhar e monitorar (P0 + P1)

- **P0** `admin/` — uma tela **"Ao vivo (acompanhar)"**: a lista das sessões abertas
  (`GET /api/transmissao?embarcacao=…`) com a **mesma grade de vídeo** do cliente, em modo somente-leitura:
  sem ligar/parar/gravar, com o rótulo da embarcação/câmera e há quanto tempo está no ar.
- **P0** reaproveitar `app/app.js` (grade, `Video.ligar`, `img-cam`/`card-cam`) numa tela do admin — o
  `fronts/vms.css` é o mesmo; o admin passa a carregar o mesmo módulo de vídeo.
- **P1** decidir e implementar **D-T3** (contar ou não como audiência) no `ground/api.py`.
- **P1** o teto/tempo e o encerramento por falta de tela continuam valendo para o admin (mesma regra do cliente).

## Fase 4 — Telemetria do PC de captura: CPU, memória, disco e rede, individual e global (P0 + P1)

- **P0** `ground/saude_do_bordo.py`: acrescentar **rede** (bytes enviados/recebidos e taxa) e a **quebra
  individual** — por câmera/encoder (CPU e kbps do processo daquele fluxo) e a marcação de o que é
  **global** da máquina. O que não der para medir continua saindo como `None` com o motivo em `nao_medido`
  (nada de número inventado).
- **P0** `ground/api.py`: guardar e servir o retrato novo (`/api/saude-do-bordo` e as rotas do admin) e
  manter a retenção de 30 dias.
- **P1** `admin/admin.js`: a área de saúde mostra **global** (CPU, memória, disco por volume, rede por
  interface) e a tabela **individual** (uma linha por câmera/encoder), com semáforo e motivo.
- **P1** o bordo deixa de exigir `psutil` para o básico: no Windows, sem `psutil`, o que não é medível fica
  explicitamente "não medido" (a tela diz, em vez de mostrar zero).

## Fase 4-bis — Conferir se a informação está certa (P0) — pedido do dono

> "confirme se realmente as informações estão corretas"

- **P0** **conferência medida, número por número**, na máquina de captura: o valor do retrato × o valor do
  próprio sistema operacional (Windows: `Win32_OperatingSystem`/`Win32_PerfFormattedData` para memória e CPU;
  `Get-PSDrive`/`Win32_LogicalDisk` para disco; `Get-NetAdapterStatistics` para rede). Cada linha do painel
  tem de bater com a fonte — e o que **não** bater entra como defeito, não como arredondamento.
- **P0** **corrigir o rótulo onde a definição é outra** (medido em 24/11/2026: o painel diz
  `memoria_livre_mb = 11132` e o SO diz 10592 — 5 % — porque um é "disponível" e o outro é "livre"): o
  painel passa a dizer **"disponível"** quando for `psutil.available`, e a mostrar a **porcentagem** ao lado
  (que bate: 66,9 % × 67 %).
- **P0** a CPU continua sendo **amostra** (`cpu_percent(interval=…)`) e o painel **diz** que é uma medida
  instantânea — nada de apresentar como média do período.
- **P1** a conferência fica registrada: tabela "campo | valor do painel | valor do sistema | veredito" na nota
  do vault, com a data e a máquina.
- **P1** onde não houver fonte (ex.: sem `psutil`), o campo aparece como **"não medido"** com o motivo — para
  nunca parecer zero.

## Fase 6 — Dashboard no app de captura (o painel do bordo) (P0 + P1) — pedido do dono

> "os cards estão horríveis"

Hoje: 7 `.bloco` iguais numa grade `auto-fit` (`bordo/index.html`), sem hierarquia. O painel vira **dashboard**:

- **P0** **faixa de cima com os números que importam**, grandes e legíveis de longe (tela do PC de captura,
  vista em pé, a metros de distância): **CPU %, memória %, disco %, rede (↑/↓)** com o **estado** (verde /
  âmbar / vermelho) — o mesmo semáforo que o lado terra já usa (`LIMIARES_DE_SAUDE`).
- **P0** **bloco de processos em andamento** legível: o que está transmitindo, o que está gravando, o que é
  os dois, contagem regressiva/duração e a câmera de cada um.
- **P0** **cartões de verdade** para licença, envio para o lado terra, agente de ordens e varredura — com
  "o que fazer quando está ruim" em uma linha (não só o estado).
- **P1** **histórico curto** dos últimos minutos (sparkline) para CPU/memória/rede — hoje só existe o valor de
  agora; a curva mostra o que subiu de repente.
- **P1** a página **não depende de internet** para pintar (o bordo se olha) e continua sem mostrar segredo.
- **P1** responsivo: a mesma página serve para o HDMI da bancada (grande) e para o celular de quem está no
  console do barco.

## Fase 7 — Dashboard do admin para monitoramento (P0 + P1) — pedido do dono

- **P0** **painel de frota**: todas as embarcações (conforme o escopo do papel: 1, algumas, todas, ou
  `observador`) numa linha cada, com CPU / memória / disco / rede, estado (verde/âmbar/vermelho), **última vez
  que falou** e o que está no ar agora — ordenado pelo pior estado primeiro.
- **P0** **drill-down** para a embarcação: as câmeras (individual), o que está transmitindo/gravando, e o
  quadro **global × individual** da Fase 4 no mesmo lugar.
- **P0** **ao vivo junto**: a grade de vídeo da Fase 3 abre neste painel (o dono vê o vídeo e a saúde da
  mesma máquina na mesma tela).
- **P1** alerta visível de "máquina muda" (sem retrato há mais que `mudo` — 180 s / 600 s conforme o caso) e
  de "sem retrato novo", na primeira dobra.
- **P1** o painel do admin **não** expõe segredo: os mesmos campos dos últimos 4 dígitos/token presente ou
  ausente que a licença já usa.

## Fase 5 — Prova, publicação e nota (P0)

- **P0** provas de tela novas: `tests/e2e-tamanho-da-imagem-nao-muda.py` (mede a caixa da imagem duas vezes,
  com um redesenho no meio, e exige **mesma medida**), `tests/e2e-parar-e-reiniciar.py` (o botão volta
  clicável), `tests/e2e-admin-assiste-ao-vivo.py`, a prova da telemetria no
  `tests/e2e-saude-do-bordo-no-admin.py`, e `tests/e2e-dashboard-do-bordo-e-do-admin.py` (os dois painéis
  pintam os 4 números com estado e **não** mostram segredo).
- **P0** a conferência da Fase 4-bis roda como prova: o teste lê o valor do painel e o valor do sistema e
  **falha** se a diferença passar da tolerância declarada (memória ≤ 5 %, CPU ≤ 10 pt, disco ≤ 1 %).
- **P0** `tools/regressao-0130.py` com as provas novas; suíte inteira verde.
- **P0** commit + push, bump **0.14.0** (mudança de tela e de contrato do retrato), release, deploy do terra
  na VPS e nota no vault + bullet no `index.md`.

## Arquivos que vão mudar

- `app/app.js` (não recriar janelas; proporção sempre aplicada; `linhas` reais; `bPar`/`bGrav` religados),
  `app/index.html` (se a tela do admin precisar de host de vídeo), `fronts/vms.css`.
- `admin/admin.js`, `admin/index.html` (tela "Ao vivo (acompanhar)" + **dashboard de frota** + telemetria
  global/individual).
- `bordo/index.html` (**dashboard do app de captura**: faixa de números, semáforo, processos em andamento,
  sparklines) — a página que o PC de captura mostra na própria tela.
- `ground/saude_do_bordo.py`, `ground/api.py` (rede + individual/global, retenção, rótulo "disponível").
- `tests/e2e-tamanho-da-imagem-nao-muda.py`, `tests/e2e-parar-e-reiniciar.py`,
  `tests/e2e-admin-assiste-ao-vivo.py`, `tests/e2e-saude-do-bordo-no-admin.py`, `tools/regressao-0130.py`.

## Riscos e limites (declarados)

- **Não dá para ter** imagem grande, sem corte e sem barra quando a proporção da câmera é diferente da área:
  a escolha do dono é **não cortar** (E-A/E-B). A Fase 1 só garante que o tamanho **pare de mudar** e que use
  o **máximo** que cabe.
- **Rede e CPU por câmera** dependem do que o sistema operacional entrega: no Windows sem `psutil` o
  por-processo pode sair como "não medido" — o painel **diz**, não inventa.
- **O admin assistindo conta como audiência** (D3 do dono). Se ele quiser o contrário, é uma linha na regra
  do lado terra — mas fica registrado que isso muda quem sustenta a transmissão.
