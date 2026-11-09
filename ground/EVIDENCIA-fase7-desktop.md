# Evidência — Fase 7: aplicativo Windows (Electron) com as três superfícies

**Data:** 09/11/2026 · **Pasta:** `desktop/` (Electron 33.4.11, `electron-builder` 25.1.8)
**Teste:** `python tests/e2e-desktop.py` (roda o app em modo `--verificar`) — **9 checagens, tudo passou**

## O que o aplicativo é

Um casco Electron único (`desktop/main.js`) com **três superfícies** em janelas separadas: **cliente** (`/app`), **admin/operação**
(`/admin`) e **bancada** (`/`), cada uma em **partição de sessão própria** (`persist:cliente`, `persist:admin`, `persist:bancada`) —
entrar como cliente não vira admin por engano. Menu para pular de superfície (`Ctrl+1/2/3`) e modo **janela** ou **quiosque**.
`desktop/servidor.js` sobe e supervisiona API + `mediamtx` + agente de análise quando a máquina for o lado terra (menu *Servidor local*).

## Fronteira de segurança (medida, não prometida)

| Checagem | Resultado |
|---|---|
| `require` na interface | **undefined** em todas as janelas |
| `process` na interface | **undefined** em todas as janelas |
| `nodeIntegration` / `contextIsolation` | desligado / ligado (`sandbox: true`, preload mínimo) |
| Endereço do lado terra exposto à interface | **null** (a ponte só devolve o que vier de variável de ambiente do dono) |
| Navegação fora da instalação | bloqueada e mandada ao navegador do sistema |
| Credencial de câmera ou chave de API no aplicativo | **nenhuma** (a credencial usada no teste veio do ambiente do teste, não do app) |

## O aplicativo abrindo as três superfícies

| Checagem | Resultado |
|---|---|
| As três janelas abrem | OK — cliente, admin, bancada |
| URLs corretas | `/app`, `/admin`, `/` |
| Janelas visíveis | OK nas três |
| Título real da página em cada superfície | OK (cliente, admin e bancada) |
| **O cliente vê as câmeras ao vivo DENTRO do aplicativo** | **4 janelas de vídeo, 4 tocando** |
| Node na interface | ausente (ver acima) |

## Empacotamento

| Passo | Resultado |
|---|---|
| Build de pasta (`npm run empacotar:pasta`) | OK — `desktop/dist/win-unpacked/LECSOR Pipeline de Video.exe` |
| Instalador NSIS (`npm run empacotar`) | OK — `desktop/dist/LECSOR-Pipeline-Video-0.1.0-x64.exe` (**78 MB**) |
| App **empacotado** abrindo as três superfícies | OK — relatório do próprio app: 3 janelas, **4 vídeos tocando** no cliente, sem Node |
| Assinatura de código | **não feita** — `signing info not identified, signing is skipped`; o `.exe` sai sem assinatura (P1 da fase) |
| Instalação executada nesta máquina | **não** — de propósito: instalar altera o sistema; o instalador fica pronto para o dono rodar |

## Limites declarados (o que este teste não prova)

- O aplicativo ainda **aponta para o endereço da bancada** (`config.json`: `http://127.0.0.1:8765`); apontar para a VPS é trocar essa linha.
- **Sem ícone próprio** (o builder usou o ícone padrão do Electron) e **sem assinatura** — P1.
- Serviços do Windows, bandeja e início automático (7-F/7-G) **não** existem ainda.
- Não foi instalado em máquina limpa de terceiro — o teste foi na bancada.

## Instaladores por superfície e atalhos (09/11/2026)

| App instalado (Menu Iniciar e Área de Trabalho) | Superfície | Instalação | Prova de vida |
|---|---|---|---|
| **LECSOR Cliente** | `/app` | `%LOCALAPPDATA%\Programs\LECSOR Cliente` | relatório do app: `/app`, título do cliente, **4 vídeos tocando**, sem Node na interface |
| **LECSOR Operacao** | `/admin` | `%LOCALAPPDATA%\Programs\LECSOR Operacao` | relatório do app: `/admin` |
| **LECSOR Admin** | `/admin` | `%LOCALAPPDATA%\Programs\LECSOR Admin` | relatório do app: `/admin` |
| **LECSOR Pipeline de Video** (bancada/engenharia) | `/`, `/app` e `/admin` no menu | `%LOCALAPPDATA%\Programs\LECSOR Pipeline de Video` | três janelas em modo verificação |

- Instalação feita com o instalador NSIS em modo silencioso (`/S`), **por usuário** (`perMachine=false`), com atalho no Menu Iniciar **e** na Área de Trabalho em cada app.
- Cada instalador carrega **uma superfície** (`extraMetadata.superficie`), tem **sessão própria** (`partition`) e **configuração própria** (`%APPDATA%\<app>\config.json`, semeada do `config.json` do pacote) — trocar o endereço do lado terra não exige reinstalar.
- Script de construção: `desktop/construir-instaladores.sh` (`npm run instaladores`) gera os três `.exe` em `desktop/dist/{cliente,operacao,admin}/`.
- **Sem assinatura de código e com ícone padrão do Electron** — continua pendência P1.
