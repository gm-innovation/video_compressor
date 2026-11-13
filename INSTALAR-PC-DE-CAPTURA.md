# Instalar o PC de captura (câmeras ligadas direto na máquina) — 0.2.0, plug & play

O PC de captura é a máquina onde as câmeras estão plugadas (USB/HDMI-captura). Ele **captura e
comprime local** e o vídeo comprimido sobe para o **lado terra** (a VPS da LECSOR ou outro computador
da rede), que descomprime e mostra.

A partir da **0.2.0** o instalador do PC de captura é **plug & play**: ele leva dentro do pacote o
servidor (API + `ground/`), o **ffmpeg**, o **mediamtx** e o **Python portátil**, e **já nasce
configurado** para esta máquina. Não se instala Python, não se copia repositório e não se edita JSON.

## 1. O que precisa na máquina

| item | de onde vem |
|---|---|
| instalador **`LECSOR-Captura-0.2.0-x64.exe`** | página de *Releases* do repositório |
| as **câmeras** | USB, ligadas direto na máquina |

Nada mais: Python, ffmpeg, mediamtx e o código do servidor viajam no instalador
(`resources\servidor\`, `resources\ffmpeg\`).

## 2. Instalar (sem configuração)

1. Rode o `LECSOR-Captura-0.2.0-x64.exe` (usuário comum basta; a instalação é por usuário).
2. Abra o app. Ele já vem com:
   - `base = http://127.0.0.1:8765` → a tela desta máquina (é aqui que estão as câmeras);
   - servidor local **ligado**, subindo sozinho a cada abertura;
   - repasse para o lado terra (`destinoSrt = 187.127.60.250:8890`);
   - *abrir junto com o Windows* marcado.
3. Confira no menu **Servidor local → Ver estado do servidor**. O esperado:

```
servidor local no ar (2 processos)
esta maquina: <nome-do-pc>
endereco em uso (base): http://127.0.0.1:8765
servidor: C:\...\resources\servidor (embutido no aplicativo)
python: C:\...\resources\servidor\python\python.exe
mediamtx: pid 12345
api: pid 12346
servidor: analise local: desligada (o Python em uso não tem numpy/onnxruntime) — captura e repasse seguem normais
ffmpeg: embutido no app — C:\...\resources\ffmpeg\ffmpeg.exe (ffmpeg version ...)
repasse para o lado terra: 187.127.60.250:8890
```

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

## 4. Conferir do outro lado (lado terra)

No computador/VPS que descomprime:

```bash
curl -s http://127.0.0.1:9997/v3/paths/list   # os fluxos desta máquina devem aparecer aqui
```

No app do lado terra (instalador **`LECSOR-Terra-0.2.0-x64.exe`**, `base` = `http://187.127.60.250:8085`),
a câmera aparece **no ar** e a tela do cliente mostra a janela.

## 5. Se algo não subir

| sintoma | onde olhar |
|---|---|
| caixa "Servidor local NAO subiu" | a mensagem diz o que falta (ex.: `faltando no servidor: tools/mediamtx/mediamtx.exe`) — normalmente instalador incompleto: reinstale o `LECSOR-Captura` |
| nenhuma câmera na lista | veja a lista de dispositivos: `curl -s http://127.0.0.1:8765/api/dispositivos`; se `video` vier vazio com motivo de driver/USB, é o Windows que não está vendo a câmera (Gerenciador de Dispositivos / porta USB) |
| a lista vem do outro lado | o `base` do app foi trocado: menu **Ajuda → Endereço do lado terra...**; o PC de captura tem de apontar para `http://127.0.0.1:8765` |
| o fluxo aparece aqui mas não no lado terra | `destinoSrt` vazio/errado ou sem saída de rede: veja `ground\envios\log\repasse-<fluxo>.log` |
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

## 7. Regra que não muda

Credencial de câmera/DVR **nunca** entra no app, no repositório ou no navegador; o navegador do
cliente nunca recebe endereço interno. Câmera por IP só entra pela VPN/por dentro da operação.
