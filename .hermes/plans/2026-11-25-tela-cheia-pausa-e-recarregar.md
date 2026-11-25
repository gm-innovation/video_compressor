# Plano — tela cheia sem contagem, pausa que encolhe a grade e recarregar que derruba a transmissão — 0.17.0

**Pedido do dono (verbatim, 25/11/2026, os três):**

> quando o vídeo está em tela cheia, a contagem regressiva e o botão para permanecer conectado não aparecem e
> quando o tempo se esgota, a transmissão é interrompida

> outra coisa que deve entrar no plano: quando as transmissões estão pausadas, a tela diminui, e quando
> recarrego a página, a transmissão é interrompida

Print que acompanha o 2º pedido: `image_59e027.png` (2026-11-25 08:33:28) — 4 células, **as quatro com
"parada"** no card; as duas de cima mostram o último quadro, as duas de baixo só o aviso
("⚠ O envio caiu quando o serviço foi reiniciado" / "⚠ nenhum envio registrado para esta câmera").

Status: **aguardando "aprovado"** (nada implementado ainda).

---

## 1. O que já está verificado no código (não é hipótese)

| # | Sintoma | Onde está no código | O que isso significa |
|---|---|---|---|
| 1 | Tela cheia sem contagem/aviso/botão | `abrirDestaque()` monta a janela do destaque (app/app.js:463-477) com `img` + `card`/`rotulo` **apenas** — não chama `montarControle()` nem cria `[data-papel="aviso"]` | O destaque **nunca teve** contagem, aviso do último minuto, "Continuar conectado", "Reconectar" nem os botões de transmissão: eles nascem no card da **grade** (app/app.js:387-391) |
| 1b | O mesmo pela via do duplo clique | `v.ondblclick = () => v.requestFullscreen()` (app/app.js:324) | Em tela cheia o navegador renderiza **só** o `<video>`; o card e o aviso são **irmãos** dele → somem |
| 2 | Recarregar a página interrompe a transmissão | `window.addEventListener('pagehide', () => { … sendBeacon('/api/transmissao/'+id+'/encerrar') })` (app/app.js:1570-1572) **e** `window.addEventListener('pagehide', avisarQueSaio)` (app/app.js:1518) | Recarregar dispara `pagehide` igual a fechar → o lado terra faz `fechar_transmissao(id,'encerrada',…)` + `parar_se_ninguem_vendo(…)` (ground/api.py:4422-4440) e o `/api/transmissao/sair` (ground/api.py:4518+) ainda apaga o que foi gravado para ele |
| 3 | Pausa que encolhe a grade | `proporcaoDaGrade()` = **a menor** das proporções conhecidas (app/app.js:206-212), e `ajustarGrade()` (app/app.js:221-260) dimensiona **todas** as trilhas por esse `r`; a proporção de cada câmera só é aprendida no `loadedmetadata`/`resize` do `<video>` (app/app.js:187-204) | **Hipótese** (a medir): sem fluxo o `<video>` pode **nunca** entregar `videoWidth` → a câmera entra (ou não) na conta com um valor que não é o do vídeo dela, e como a grade usa **uma** proporção para todas, uma câmera fora distorce o tamanho de todas |

O que **não** está verificado: a geometria exata do print (as células parecem ~1,1:1 com a imagem 16:9
dentro). **Sem medir, isto vira opinião** — é a Fase 1.

---

## 2. Fases (P0/P1/P2 dentro de cada fase)

### Fase 1 — Medir antes de mexer (P0)

1. **(P0)** Estender a sonda de geometria (`scripts/grade-do-cliente.py`) para **dois estados**: todas as
   câmeras **no ar** e todas **paradas** — medir, por célula: caixa da célula, imagem desenhada, faixa
   interna (preto) e a proporção usada no cálculo. Rodar em 1908x841 (o print), 1536x700 e 1920x1080.
2. **(P0)** Medir o que a sonda **não** vê: qual `S.proporcao[c.id]` fica em cada câmera **parada** e de
   onde ele veio (metadado, valor antigo ou ausente) — é o que decide a Fase 4.
3. **(P1)** Medir o recarregar: com uma sessão no ar, recarregar (`page.reload()`) e ler no banco
   (`transmissoes`) qual foi o estado final e **quem** o provocou (a trilha de auditoria diz).
4. **(P1)** Medir a tela cheia: abrir o destaque em tela cheia, forçar o aviso do último minuto e conferir
   **por seletor** o que existe/não existe dentro do elemento em tela cheia.

### Fase 2 — Recarregar a página não pode interromper a transmissão (P0)

1. **(P0)** Distinguir **recarregar** de **sair** na própria tela: `pagehide` de recarga
   (`performance.getEntriesByType('navigation')[0].type === 'reload'` **ou** uma janela de carência de
   poucos segundos após o `load`) **não** chama `encerrar`/`sair`; fechar a aba, desligar a máquina e
   clicar em "Sair" continuam encerrando como hoje.
2. **(P0)** O silêncio continua mandando: quem recarrega e **não** volta dentro da janela do batimento
   (`SEGUNDOS_SEM_BATIMENTO = 60` s) tem a sessão encerrada pelo lado terra, como já é hoje — recarregar
   deixa de ser um caso especial de saída, não um perdão para sempre.
3. **(P0)** A gravação em andamento segue a mesma regra da saída? **Decisão do dono** (uma linha no plano):
   ao recarregar com gravação em curso, a gravação **continua** (é a única leitura compatível com "a
   gravação não é picada") — confirmar.

### Fase 3 — Tela cheia com a contagem e o botão (P0)

1. **(P0)** `abrirDestaque()` passa a montar, no card do destaque, o **mesmo** `montarControle()` + o
   `[data-papel="aviso"]` da grade (uma função, os dois lugares — nada de copiar a lógica).
2. **(P0)** O duplo clique no vídeo deixa de pedir tela cheia no `<video>` (app/app.js:324) e passa a pedir
   na **janela** (`.janela`) — assim o card e o aviso são renderizados dentro da tela cheia. O mesmo no
   destaque (`caixa.requestFullscreen()`, app/app.js:452).
3. **(P1)** Sem mouse: em tela cheia os botões têm de continuar acessíveis por teclado (foco visível, `Esc`
   sai) e o aviso não pode cobrir a imagem inteira.
4. **(P1)** O relógio da tela cheia continua batendo ponto: conferir que `baterPonto()` (10 s) e a
   repintura de 2 s (`pintarEstados`) alcançam as janelas do destaque.

### Fase 4 — A pausa não pode encolher a grade (P1)

1. **(P0)** A proporção de cada câmera passa a ser a do **fluxo declarado** (a resolução do encoder, que o
   lado terra já conhece) quando o `<video>` não entregar metadado — nunca "a última que apareceu" nem
   "some da conta" sem mais. Uma câmera parada **não pode** mudar o tamanho das outras.
2. **(P0)** A célula parada guarda o **lugar**: sem imagem, o aviso ("caiu quando o serviço foi
   reiniciado" / "nenhum envio registrado") fica no mesmo retângulo da imagem — a grade **não** se
   redimensiona ao parar nem ao voltar.
3. **(P1)** Se a grade tiver mesmo de se adaptar (ex.: câmeras de formas muito diferentes), que seja pela
   **média/mediana** das proporções conhecidas e com o caso medido na Fase 1 — sem prometer tamanho que
   não caiba.
4. **(P2)** O aviso dentro da célula parada ganha o nome da câmera e a hora da última imagem (hoje o card
   diz "parada" e a tarja diz o motivo, separados).

### Fase 5 — Provar e publicar (P0)

1. **(P0)** Prova e2e nova (`tests/e2e-tela-cheia-e-recarregar.py`): (a) destaque em tela cheia **com** a
   contagem e o botão visíveis e clicáveis; (b) `page.reload()` **não** encerra a sessão (a transmissão
   continua no ar depois do reload, medida no banco e na tela).
2. **(P0)** Prova de geometria parada × no ar (Fase 1) anexada ao painel de resultado deste plano, com
   antes/depois em números — a média/mediana do "antes" e do "depois".
3. **(P0)** `tools/regressao-0130.py` verde (31 provas) + `python -m unittest discover -s tests` OK.
4. **(P0)** Build do instalador, release no GitHub, deploy do lado terra (VPS) com backup por arquivo e
   prova pela porta pública — o rito das rodadas anteriores.
5. **(P1)** Nota no vault (`20-runbooks/2026-11-25-…-0.17.0.md`) + linha no índice.

---

## 3. O que este plano NÃO faz (dito de propósito)

- **Não mexe no batimento de 60 s** nem no aviso de 1 minuto: as decisões D1-D4 do dono (24/11/2026)
  continuam valendo. Recarregar **não** vira uma sessão eterna.
- **Não** mexe na banda, na qualidade por câmera nem no `SEGUNDOS_SEM_BORDO` (180 s).
- **Não** promete que a grade fica maior que o palco: a Fase 4 padroniza o tamanho, não inventa espaço.

## 4. Aceite

1. Em tela cheia (destaque ou duplo clique) **aparecem** a contagem regressiva, o aviso do último minuto e o
   botão "Continuar conectado"; clicar renova a sessão e a transmissão **não** cai.
2. Recarregar a página **não** interrompe a transmissão; fechar a aba/sair/desligar continua interrompendo
   dentro da janela de 60 s do batimento.
3. Com qualquer câmera parada, o tamanho das **outras** e a posição das imagens **não** mudam (medido
   antes/depois).
4. Suíte verde, release publicada, lado terra com os arquivos novos provados pela porta pública.
