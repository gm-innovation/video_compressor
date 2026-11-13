# Instalar o PC de captura (câmeras ligadas direto na máquina) — 0.2.5, plug & play

O PC de captura é a máquina onde as câmeras estão plugadas (USB/HDMI-captura). Ele **captura e
comprime local** e o vídeo comprimido sobe para o **lado terra** (a VPS da LECSOR ou outro computador
da rede), que descomprime e mostra.

A partir da **0.2.0** (corrigido na **0.2.1**, **0.2.2**, **0.2.3** e **0.2.5**) o instalador do PC de captura é **plug & play**: ele leva dentro do pacote o
servidor (API + `ground/`), o **ffmpeg**, o **mediamtx** e o **Python portátil**, e **já nasce
configurado** para esta máquina. Não se instala Python, não se copia repositório e não se edita JSON.

## 1. O que precisa na máquina

| item | de onde vem |
|---|---|
| instalador **`LECSOR-Captura-0.2.5-x64.exe`** | página de *Releases* do repositório |
| as **câmeras** | USB, ligadas direto na máquina |

Nada mais: Python, ffmpeg, mediamtx e o código do servidor viajam no instalador
(`resources\servidor\`, `resources\ffmpeg\`).

## 2. Instalar (sem configuração)

1. Rode o `LECSOR-Captura-0.2.5-x64.exe` (usuário comum basta; a instalação é por usuário).
2. Abra o app. Ele já vem com:
   - `base = http://127.0.0.1:8765` → a tela desta máquina (é aqui que estão as câmeras);
   - servidor local **ligado**, subindo sozinho a cada abertura;
   - repasse para o lado terra (`destinoSrt = 187.127.60.250:8890`);
   - *abrir junto com o Windows* marcado;
   - credenciais do lado terra já no pacote (`ambiente.json`): endereço do Supabase e token de
     ingestão — é o que faz o **login ser o mesmo** do resto do sistema e o fluxo ser anunciado lá.
3. **Primeiro acesso**: numa instalação nova **não existe usuário nenhum** no banco local, então a
   tela abre no formulário **Primeiro acesso**. Se você já tem conta no sistema (o e-mail existe no
   Supabase), informe **o mesmo e-mail e a mesma senha**: a instalação **adota essa conta** (entra com
   o papel dela) em vez de criar mais um login solto. Só quando a credencial não existe no Supabase
   (bancada sem internet) é que se cria um administrador **desta máquina**, com a senha digitada
   (8 caracteres ou mais) valendo também fora da rede. Sem isso não havia como entrar: era o beco sem
   saída da instalação anterior.
4. Confira no menu **Servidor local → Ver estado do servidor**. O esperado:

```
servidor local no ar (2 de 2 processos)
esta maquina: <nome-do-pc>
endereco em uso (base): http://127.0.0.1:8765
servidor: C:\...\resources\servidor (embutido no aplicativo)
python: C:\...\resources\servidor\python\python.exe
mediamtx: pid 12345 (vivo)
api: pid 12346 (vivo)
ffmpeg: embutido no app — C:\...\resources\ffmpeg\ffmpeg.exe (ffmpeg version ...)
repasse para o lado terra: 187.127.60.250:8890
```

No topo da caixa vem a sondagem das portas (processo vivo **não** é a mesma coisa que servidor no
ar): `API local (127.0.0.1:8765): respondeu HTTP 200` e `mediamtx (127.0.0.1:9997): respondeu HTTP 200`.

Se algum processo morrer, a linha dele diz `MORREU (codigo N)` seguida da última linha do log — a
versão anterior dizia "no ar (2 processos)" mesmo com o mediamtx morto por porta ocupada.

São **dois** processos de propósito: `mediamtx` (recebe o SRT local e publica) e a `api` da máquina. A
**análise local** (detector de objetos) é opcional — ela só sobe se o Python em uso tiver
`numpy`/`onnxruntime`, que o Python portátil do pacote **não tem**; sem ela a captura e o repasse
funcionam iguais, e o motivo fica registrado em `desktop-logs\agente-analise.log`. O banco local fica
em `%APPDATA%\LECSOR Captura\pipeline.db` (sobrevive a atualizar o aplicativo).

Se algo faltar, o próprio app **avisa em uma caixa de erro** (em versão anterior a falha era
silenciosa e o servidor ficava "parado" sem explicação).

Linha de comando, se quiser conferir por fora:

```bash
curl -s http://127.0.0.1:8765/api/dispositivos      # lista as câmeras DESTA máquina
curl -s http://127.0.0.1:9997/v3/paths/list         # lista os fluxos publicados aqui
```

## 3. Inserir as câmeras (por câmera)

No app: **Enviar vídeo** → *De onde vem o vídeo* = **"webcam do notebook (ao vivo)"** → em
**Webcam / dispositivo** escolha a câmera → dê um rótulo (ex.: `Câmera 1 proa`) → **transmitir**.
Repita para a segunda câmera (ela ganha a própria janela). O envio é contínuo: só para quando você
clicar em **parar**.

**Duas câmeras iguais (mesmo nome, ex. duas "USB Video Device"):** a lista mostra
`USB Video Device (1)` e `USB Video Device (2)` e cada uma é um dispositivo **diferente** — antes as
duas entradas viravam o mesmo nome e a segunda era recusada com "já está em uso". Escolha a (1),
transmita, escolha a (2) e transmita: as duas convivem.

## 4. Conferir do outro lado (lado terra)

No computador/VPS que descomprime:

```bash
curl -s http://127.0.0.1:9997/v3/paths/list   # os fluxos desta máquina devem aparecer aqui
```

No app do lado terra (instalador **`LECSOR-Terra-0.2.5-x64.exe`**, `base` = `http://187.127.60.250:8085`),
a câmera aparece **no ar** e a tela do cliente mostra a janela.

**Como isso acontece (0.2.2):** quando o envio começa, o PC de captura **avisa o lado terra**
(`POST /api/cameras/anuncio`, autenticado pelo token de ingestão) e o lado terra **cria a câmera**
ligada à embarcação — é isso que faz o fluxo que chega **aparecer para o cliente**. Antes o fluxo
chegava no mediamtx e ninguém via nada, porque só câmera cadastrada era listada e o PC de captura não
escreve no banco do lado terra. Se o anúncio falhar, fica no log
`ground\envios\log\repasse-<fluxo>.log`; enquanto isso o operador vê o fluxo marcado
"(no ar, sem cadastro)" na tela **Câmeras**.

## 5. Se algo não subir

| sintoma | onde olhar |
|---|---|
| caixa "Servidor local NAO subiu" | a mensagem diz o que falta (ex.: `faltando no servidor: tools/mediamtx/mediamtx.exe`) — normalmente instalador incompleto: reinstale o `LECSOR-Captura` |
| nenhuma câmera na lista | veja a lista de dispositivos: `curl -s http://127.0.0.1:8765/api/dispositivos`; se `video` vier vazio com motivo de driver/USB, é o Windows que não está vendo a câmera (Gerenciador de Dispositivos / porta USB) |
| a lista vem do outro lado | o `base` do app foi trocado: menu **Ajuda → Endereço do lado terra em uso...**; o PC de captura tem de apontar para `http://127.0.0.1:8765` (ou use **Servidor local → Papel desta instalacao → Usar como PC de captura**) |
| a tela não lista câmera nenhuma | menu **Servidor local → Testar câmeras desta máquina**: consulta sempre a máquina do app (loopback) e mostra a lista, o ffmpeg e o motivo — independente do endereço em uso |
| não tenho login / esqueci a senha | instalação nova: tela **Primeiro acesso**; depois disso o admin cria/reseta usuários em **Usuários** (a rota de primeiro acesso só vale enquanto não existir usuário e só na própria máquina) |
| clico em **Atualizar** e "nada acontece" | o botão agora mostra **atualizando…** e **sem mudanças desde HH:MM:SS** quando os dados são os mesmos |
| o fluxo aparece aqui mas não no lado terra | `destinoSrt` vazio/errado ou sem saída de rede: veja `ground\envios\log\repasse-<fluxo>.log` |
| o fluxo chega no lado terra mas o cliente não vê | veja no log do repasse se apareceu `anunciei ao lado terra: ...`; se aparecer erro de token, o `resources\servidor\ground\ambiente.json` do pacote está sem `LECSOR_TOKEN_INGESTAO` (o token é o mesmo no lado terra) |
| a segunda câmera "já está cadastrada" | versão anterior à 0.2.2: atualize o instalador — a identidade da câmera passou a ser o endereço único do dispositivo, não o nome |
| o app do cliente lista as câmeras mas nenhuma delas é a que cadastrei (`cam-01`, `cam-02`) | da 0.2.5 o cadastro desta máquina sobe ao lado terra sozinho: ao cadastrar a câmera, ao ativar/desativar e ao subir o servidor local. Câmera cadastrada numa versão anterior à 0.2.5 sobe ao reinstalar (ou pelo botão **Publicar câmeras no lado terra**, na tela Câmeras do admin) |
| "o lado terra não respondeu (conexão recusada)" e o endereço tentado é `127.0.0.1:8765` | config gravado por instalação anterior em `%APPDATA%\<app>\config.json`. Da 0.2.3 em diante o app **corrige sozinho** ao abrir (endereço de loopback num papel que não sobe servidor local volta para o de fábrica); reinstale por cima. Desinstalar não limpa essa pasta e não é preciso esperar entre desinstalar e instalar |
| API não sobe | `desktop-logs\api-erro.log` (dentro de `resources\servidor\`) |
| aparece `analise local: desligada` | é o esperado no pacote: sem `numpy`/`onnxruntime` no Python portátil o detector não roda; captura e repasse não dependem dele |
| mediamtx não sobe | `desktop-logs\mediamtx-erro.log` (porta 8890/8554 ocupada) |

Os logs ficam em `resources\servidor\desktop-logs\` (o que o app subiu) e
`resources\servidor\ground\envios\log\` (os envios e o repasse). Processo que morre três vezes
seguidas **para** de ser reiniciado e fica registrado no log (não gira para sempre).

## 6. Bancada / engenharia (só quem mexe no código)

No clone do repositório o app usa o papel `bancada` e respeita o `servidorLocal.repo` do
`%APPDATA%\LECSOR Pipeline de Video\config.json` quando a pasta existe — o servidor embutido no
instalador continua valendo como padrão. Nada disso é necessário na máquina do cliente.

## 7. Trocar o papel desta máquina (sem reinstalar)

No menu **Servidor local → Papel desta instalacao**:

- **Usar como PC de captura (esta máquina)**: aponta o app para `http://127.0.0.1:8765`, liga o
  servidor local e reabre as telas;
- **Usar como lado terra (servidor na rede)**: pergunta o endereço, aponta o app para ele, desliga o
  servidor local e zera o repasse.

Os itens **Destino do repasse (lado terra)...** e **Endereço do lado terra em uso...** pedem o valor
numa janelinha e gravam no config — ninguém precisa editar JSON.

## 8. Regra que não muda

Credencial de câmera/DVR **nunca** entra no app, no repositório ou no navegador; o navegador do
cliente nunca recebe endereço interno. Câmera por IP só entra pela VPN/por dentro da operação.
