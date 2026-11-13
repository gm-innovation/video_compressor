# Instalar o PC de captura (câmeras ligadas direto na máquina)

Vale para o **outro computador** — aquele onde as câmeras estão plugadas (USB/HDMI-captura). Ele
captura e **comprime local**, e o vídeo comprimido sobe para o **lado terra** (a VPS da LECSOR ou
outro computador da rede), que descomprime e mostra. Nada aqui é digitado à mão no repositório:
todos os passos são comandos ou menus copiáveis.

## 1. O que precisa estar na máquina

| item | de onde vem | por quê |
|---|---|---|
| aplicativo **LECSOR Admin** (ou Cliente) | página de releases do repositório (`LECSOR-Admin-0.1.3-x64.exe`) | é a tela onde você insere as câmeras |
| o **repositório** (pasta `lecsor-pipeline-video`) | `git clone` ou o pacote de código | tem o `ground/`, o `tools/mediamtx/mediamtx.exe` e os scripts |
| **Python 3.11+** | python.org — marque **"Add python.exe to PATH"** | roda a API e o repasse |
| **ffmpeg** | ffmpeg.org (build *essentials*, descompactar) — a pasta `bin` tem de estar no **PATH** | sem ele **nenhuma câmera é listada** e a captura não roda |
| as **câmeras** | USB na máquina | aparecem sozinhas na lista de dispositivos |

O `mediamtx.exe` **não** se instala: ele viaja dentro do repositório (`tools/mediamtx/`).

## 2. Configurar (uma vez)

No app instalado existe um `config.json`. Abra pelo menu **Ajuda → Endereço do lado terra...** para
ver o que está em uso; para trocar, edite o arquivo:

```
%APPDATA%\LECSOR Pipeline de Video\config.json
```

O instalador 0.1.3 já vem apontado para o lado terra da LECSOR — só a configuração do PC de captura
precisa de ajuste:

```json
{
  "base": "http://127.0.0.1:8765",
  "destinoSrt": "187.127.60.250:8890",
  "servidorLocal": { "ligado": false, "repo": "C:/caminho/do/lecsor-pipeline-video", "portaApi": 8765 }
}
```

- `base` = **onde está a API desta máquina**: no PC de captura é `127.0.0.1:8765` (a captura acontece
  aqui). Deixando o valor de fábrica (`187.127.60.250:8085`) o app abre no lado terra e **não** lista
  as câmeras desta máquina.
- `destinoSrt` = **para onde os vídeos comprimidos vão** (a VPS `187.127.60.250:8890`, ou
  `IP-do-outro-PC:8890` na rede). **Vazio = não sobe nada** (só esta máquina).
- `servidorLocal.repo` = a pasta do repositório nesta máquina (o menu *Servidor local* precisa dela).

## 3. Subir o servidor local

Menu **Servidor local → Subir servidor nesta máquina (API, mediamtx, agente)**. Ele sobe três coisas
na pasta do repositório: `mediamtx`, a API na porta 8765 e (se existir) o agente de análise.

Confira:

```bash
curl -s http://127.0.0.1:8765/api/dispositivos      # lista as câmeras DESTA máquina
curl -s http://127.0.0.1:9997/v3/paths/list         # lista os fluxos publicados aqui
```

## 4. Inserir as câmeras (por câmera)

No app: **Enviar vídeo** → *De onde vem o vídeo* = **"webcam do notebook (ao vivo)"** → em
**Webcam / dispositivo** escolha a câmera → dê um rótulo (ex.: `Câmera 1 proa`) → **transmitir**.

Repita para a segunda câmera (ela ganha a própria janela). O envio é contínuo: só para quando você
clicar em **parar**.

## 5. Conferir do outro lado (lado terra)

No computador/VPS que descomprime:

```bash
curl -s http://127.0.0.1:9997/v3/paths/list   # os fluxos desta máquina devem aparecer aqui
```

No app apontado para o lado terra (`base` = `http://187.127.60.250:8085`), a câmera aparece
**no ar** e a tela do cliente mostra a janela.

## 6. Se algo não subir

| sintoma | onde olhar |
|---|---|
| nenhuma câmera na lista | o servidor local não está no ar, `base` ainda é o lado terra, **ou o `ffmpeg` não está no PATH** (o menu *Ver estado do servidor* diz: `ffmpeg: NAO ENCONTRADO`) |
| a tela avisa "esta lista vem de ..." | você está no app apontado para o lado terra: troque `base` para `http://127.0.0.1:8765` e suba o **Servidor local** |
| a lista volta vazia com motivo sobre driver/USB | o Windows não está vendo a câmera: confira o Gerenciador de Dispositivos e a porta USB |
| o fluxo aparece na máquina mas não no lado terra | `destinoSrt` vazio/errado, ou sem saída de rede: veja `ground/envios/log/repasse-<fluxo>.log` |
| API não sobe | `desktop-logs/api-erro.log` (normalmente Python fora do PATH) |
| mediamtx não sobe | `desktop-logs/mediamtx-erro.log` (porta 8890/8554 ocupada) |

Os logs ficam na pasta do repositório: `desktop-logs/` (o que o app subiu) e `ground/envios/log/`
(os envios e o repasse).

## 7. Regra que não muda

Credencial de câmera/DVR **nunca** entra no app, no repositório ou no navegador; o navegador do
cliente nunca recebe endereço interno. Câmera por IP só entra pela VPN/por dentro da operação.
