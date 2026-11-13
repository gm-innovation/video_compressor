# 0.2.1 — Corrigir o que a instalação no PC de captura do cliente revelou

**Status:** aguardando aprovação do dono (nada implementado)
**Pedido:** "então você precisa corrigir isso tudo, não?"
**Base:** release publicada **v0.2.0** (commit `b794700`) · testes atuais verdes
**Relato do dono (computador das câmeras, `LECSOR Admin 0.2.0` e `LECSOR Captura 0.2.0`):**
"o captura continua sem css, o admin subiu o servidor, mas ainda não encontra as câmeras.
endereço em uso: http://187.127.60.250:8085 ... exceto a última: repasse para o lado terra: (nada —
só esta máquina)" · "clico em subir servidor e ... nada acontece, nem um aviso de erro" · "assim como
o botão de atualizar no canto superior direito"

---

## 1. Defeitos conferidos nesta bancada (evidência, não suposição)

| # | defeito | evidência medida |
|---|---|---|
| D1 | **Telas sem CSS (e sem `video.js`)** — o pacote não leva `fronts/` | `fronts/` tem `admin.css`, `estilo.css`, `vms.css`, `video.js`; `admin/index.html` pede `/fronts/vms.css` + `/fronts/admin.css` + `/admin/admin.js`; `app/index.html` pede `/fronts/vms.css` + `/fronts/video.js` + `/app/app.js`; `api.py:554-555` mapeia `/fronts/<arquivo>` para `RAIZ/fronts`. Na instalação 0.2.0 desta bancada: `/admin` 200 mas `/fronts/vms.css` **404** e `/fronts/admin.css` **404**. O `extraResources` empacota `ground admin app portal board db analytics tools python` — **sem `fronts`**. |
| D2 | **Câmera não aparece sem nenhuma mensagem** | `admin/admin.js:837-839`: `const r = await fetch('/api/dispositivos'); if (!r.ok) return;` — no papel **terra** (`base = http://187.127.60.250:8085`) e sem sessão, o lado terra responde `{"erro":"so operacao e administrador veem os dispositivos de captura"}` (medido agora de fora da VPS) → a função **volta calada**, a lista fica vazia e nenhum aviso é mostrado. O texto que explicaria a situação (`d.pedido_de === 'outra_maquina'`, `admin.js:849-855`) só existe no caminho de resposta 200. |
| D3 | **`subir()` diz "no ar" mesmo com processo morto** | Com as portas 8765/8890 já ocupadas por outra instância, `servidor.subir()` respondeu em 0,1 s `{"ok":true,"subiu":2,...}` e `estado()` = "servidor local no ar (2 processos)" enquanto `desktop-logs/mediamtx-erro.log` registrava `[app] mediamtx saiu (codigo 1) — subindo de novo (1/3)`. `subir()` conta sucesso por ter disparado o processo, sem conferir porta/sobrevivência. |
| D4 | **`base` e `destinoSrt` não têm caminho pela tela** | `desktop/main.js:157-166`: os itens "Destino do repasse (lado terra)..." e "Ajuda → Endereco do lado terra..." só mostram o valor e mandam editar `config.json`. |
| D5 | **Botão "Atualizar" parece morto** | `admin.js:1063` liga o clique a `atualizar()`, que repinta **só se a assinatura das telas mudar** (`admin.js:62` `if (marca === A.marca) return;`) e **não tem indicador de carregando** — com dados iguais não há mudança visível. |
| D6 | **`portal/` vai no pacote mas não é servido** | `api.py` não tem rota `/portal` nem `/board` (busca por `"/board|"/portal` em `api.py`: nenhuma ocorrência) — pasta é peso morto no instalador. |

Papéis (`desktop/papeis.json`) — confirma o relato do dono: `terra` = `base http://187.127.60.250:8085`,
`destinoSrt ""`, `servidorLocal.ligado false`; `captura` = `base http://127.0.0.1:8765`,
`destinoSrt 187.127.60.250:8890`, `ligado true`. O lado terra (VPS `srv1918673`) **não tem dispositivo
de vídeo** (`ls /dev/video*` → não existe).

---

## 2. Fases (prioridade marcada dentro de cada uma)

### Fase 1 — P0 — O pacote leva as telas inteiras (D1)
1. `extraResources` += `../fronts` → `servidor/fronts` (os 4 arquivos: `admin.css`, `estilo.css`,
   `vms.css`, `video.js`).
2. O build **para** se `fronts/{vms.css,admin.css,video.js}` não existirem (mesma regra do ffmpeg).
3. Teste: no pacote, `servidor/fronts` com os 4 arquivos; e **execução real** — subir o servidor
   empacotado e conferir `200` em `/fronts/vms.css`, `/fronts/admin.css`, `/fronts/video.js`.
4. Bump para **0.2.1** (o 0.2.0 publicado continua como está; quem já instalou recebe o 0.2.1).

### Fase 2 — P0 — A tela diz por que não tem câmera (D2)
1. `preencherDispositivos()` não pode voltar calada: em resposta não-ok, mostrar no
   `#env-dispositivo-aviso` o que a API respondeu (status + `erro`) e de quem é a lista (campo
   `maquina`/`pedido_de` quando houver).
2. Aviso fixo quando o `base` **não** é `127.0.0.1:8765`: "esta lista vem de `<maquina>`; câmera ligada
   nesta máquina só aparece com o Servidor local no ar e endereço http://127.0.0.1:8765".
3. Novo item de menu **"Testar câmeras desta máquina"**: pergunta a `http://127.0.0.1:8765/api/dispositivos`
   (loopback, independente do `base`) e mostra a lista ou o motivo em caixa — o operador não precisa
   deduzir de qual máquina veio a lista.

### Fase 3 — P0 — "Subir servidor" fala a verdade (D3)
1. `subir()` passa a **conferir** depois de subir: espera até ~3 s e checa (a) processos vivos
   (`p.exitCode === null`), (b) portas/rotas respondendo (`8765 /api/sistema` ou `/api/eu`, `9997 /v3/paths/list`).
2. `estado()`/`detalhe()` só dizem "no ar" com os processos vivos e as portas respondendo; senão
   dizem qual morreu e o motivo (porta ocupada, binário ausente), lendo a última linha do log de erro.
3. O menu mostra a caixa com esse veredito (progresso curto é aceitável porque a checagem é de segundos).

### Fase 4 — P1 — Endereço e repasse pela tela (D4)
1. "Endereco do lado terra..." e "Destino do repasse (lado terra)..." passam a **pedir o valor**
   (janela de entrada) e gravar com `gravarConfig` (validando `http://host:porta` e `host:porta`).
2. Presets de um clique: "esta máquina (captura)" = `127.0.0.1:8765` + servidor local ligado;
   "lado terra" = endereço informado + servidor local desligado — assim uma máquina vira captura ou
   terra sem reinstalar.

### Fase 5 — P1/P2 — Feedback, limpeza e prova
1. (P1) Botão "Atualizar" com feedback: estado "atualizando…" e, quando nada mudou, "sem mudanças desde
   HH:MM" (§D5) — sem repintar a tela no meio da leitura do operador (regra atual preservada).
2. (P1) `portal/` sai do `extraResources` (§D6) e o pacote volta a ficar menor.
3. (P1) Prova de instalação limpa de novo (sem Python/ffmpeg/repo): captura sobe, telas **estilizadas**,
   câmera listada, repasse no ar.
4. (P2) Reinstalação por cima (config preservado) e desinstalação.

---

## 3. Critério de aceite (o que será provado, não afirmado)
- `/fronts/vms.css`, `/fronts/admin.css` e `/fronts/video.js` respondem **200** no servidor empacotado
  (comando + saída registrados).
- Na tela, sem câmera, aparece **texto** dizendo de quem é a lista e o que fazer — nunca lista vazia muda.
- `subir()` com porta ocupada **não** diz "no ar": diz o que morreu, com a linha do log.
- `base` e `destinoSrt` alteráveis pela tela, gravados no config, com o estado refletindo a mudança.
- `tests/suite.py` e `tests/test-instalador-plug-and-play.py` (novas seções) **OK**.

## 4. Riscos
- `fronts/` no pacote: +~40 KB (irrelevante).
- Presets de papel mexem em config já gravado: só por ação explícita no menu, nunca em boot.
- Checagem de portas no `subir()`: se for agressiva, pode dizer "parado" em máquina lenta — limite de
  espera de 3 s e verificação do log antes de concluir.
