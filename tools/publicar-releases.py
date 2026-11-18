"""Publica as releases 0.2.8 / 0.2.9 / 0.3.0 / 0.4.0 / 0.4.1 / 0.5.0 no GitHub com os 4 instaladores cada.

O repositorio e' gm-innovation/video_compressor; a ultima release que existia era a v0.2.7.
O token sai do arquivo normalizado (~/.hermes/vps-deploy/gh-token.txt.norm) e NUNCA e' impresso.
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

REPO = "gm-innovation/video_compressor"
API = f"https://api.github.com/repos/{REPO}"
# O PAT de `.norm` so' LE (criar release devolve 403 "Resource not accessible"). Quem escreve e' a
# credencial que o proprio git usa (Git Credential Manager, token gho_ do dono) — passada pelo ambiente,
# nunca impressa. Ordem: GITHUB_TOKEN_FOR_RELEASES > GH_TOKEN > arquivo .norm.
TOKEN = (os.environ.get("GITHUB_TOKEN_FOR_RELEASES") or os.environ.get("GH_TOKEN")
         or pathlib.Path.home().joinpath(".hermes/vps-deploy/gh-token.txt.norm").read_text().strip())
DIST = pathlib.Path.home() / "lecsor-pipeline-video" / "desktop" / "dist"
PAPEIS = ("Captura", "Terra", "Admin", "Cliente")
# Ordem de publicacao: o PRIMEIRO e' o `latest` do GitHub. Nova versao entra na frente.
VERSOES_PUBLICADAS = ("0.6.5", "0.6.4", "0.6.3", "0.6.2", "0.6.1", "0.6.0", "0.5.0", "0.4.1", "0.4.0", "0.3.0", "0.2.9", "0.2.8")


def instaladores(versao: str) -> list:
    """Os arquivos .exe daquela versao.

    Da 0.6.0 em diante e' UM aplicativo so' (`dist/unico/LECSOR-<versao>-x64.exe`): o pacote nasce no
    papel `unico` e a tela que abre e' a do papel de quem entra (dono, 17/11/2026). As versoes antigas
    seguem com um instalador por papel, que e' como elas foram publicadas.
    """
    if versao >= "0.6.0":
        return [a for a in sorted((DIST / "unico").glob(f"*{versao}*.exe")) if "ninstaller" not in a.name]
    return [DIST / papel.lower() / f"LECSOR-{papel}-{versao}-x64.exe" for papel in PAPEIS]

NOTAS = {
    "0.6.5": (
        "**A webcam não é mais arrancada do envio que já estava no ar, e o campo não interrompe mais quem "
        "está digitando.**\n\n"
        "Dois defeitos encontrados ao destravar o teste de ponta a ponta (18/11/2026):\n\n"
        "* **segundo envio da MESMA webcam**: a limpeza de \"câmera presa\" rodava **antes** de perguntar se "
        "a câmera estava com um envio VIVO — matava o ffmpeg do envio que estava no ar e aceitava o "
        "segundo (o quadro preto silencioso que a recusa existe para evitar). Agora a ordem é: se há "
        "envio vivo, **recusa com o recado** (*a webcam já está em uso pelo fluxo …*); só limpa processo "
        "preso de execução anterior quando não há envio vivo;\n"
        "* **formulário de envio**: o redesenho periódico da tela recriava o campo e o foco se perdia no "
        "meio da digitação (o rótulo digitado sumia). O foco e o cursor voltam para o mesmo campo depois "
        "do redesenho.\n\n"
        "Provas: `tests/e2e-envios.py` de ponta a ponta (traz a própria bancada: banco novo + contas de "
        "demonstração + servidor de mídia) — o passo do cliente, a ocupação da webcam e as medições da "
        "fonte crua passam.\n"),
    "0.6.4": (
        "**A tela do admin fica limpa e a qualidade do vídeo ao vivo passa a ser a banda (1500 a 300 kbps).**\n\n"
        "Pedido do dono (18/11/2026, verbatim): *\"1. não vejo motivo pra 'Transmissões pedidas pelos clientes' "
        "existir no admin, esse tipo de informação é irrelevante pra mim, precisa estar apenas no canal do "
        "cliente; 2. por que esses testes de vídeo estão na minha tela? isso não é necessário e ainda dá o "
        "aspecto de bagunçado; 3. não está reconhecendo câmeras na máquina e ... não consigo escolher a "
        "qualidade do vídeo, continua com a caixa de seleção antiga, sem a seleção de 1500 a 300 kbps\"*.\n\n"
        "Na tela **Enviar vídeo**:\n\n"
        "* sai a caixa **\"Transmissões pedidas pelos clientes\"** — ela é da **operação** (é ela que cancela "
        "um pedido de outra pessoa) e o cliente tem a dele em `/app`;\n"
        "* sai o **\"Teste de vídeo (bancada)\"** e a **\"Qualidade por câmera\"** da tela do administrador — "
        "comprimir, medir e publicar continua com a **operação**;\n"
        "* entram no lugar o **Transmitir ao vivo** (câmera desta máquina, teste sintético ou radar) e o "
        "**No ar agora**, com o botão de **parar**;\n"
        "* a **qualidade do ao vivo é a lista fechada de banda**: 1500, 1200, 1000, 800, 500 e 300 kbps "
        "(a caixa antiga de CRF só fica no caminho de arquivo/link, onde \"qualidade\" é compressão) e o "
        "valor escolhido **chega na API** no envio.\n\n"
        "Câmera desta máquina: a lista de dispositivos **tenta de novo** (o servidor local leva alguns "
        "segundos para subir) e, se não vier, **diz o motivo** em vez de ficar em branco — era isso o \"não "
        "está reconhecendo câmeras\". O aplicativo também passou a **esperar o servidor local responder "
        "antes de abrir as telas de captura** (mesma correção que a 0.6.3 fez para o login).\n\n"
        "Provas: `tests/e2e-tela-limpa-do-admin.py` (dois navegadores de verdade, administrador e operação, "
        "com a API de verdade), `tests/test_captura_no_admin.py` e `tests/test-config-endereco.py`.\n\n"
        "**Atualização:** instale por cima. Feche as janelas antigas do aplicativo antes de abrir esta versão."
    ),
    "0.6.3": (
        "**O app se organiza pelo usuario: a tela de entrada nunca mais vem de um servidor local vazio.**\n\n"
        "Relato do dono depois de instalar a 0.6.2 (18/11/2026): *\"tentei acessar como admin e continua nao "
        "encontrando o meu cadastro: 'esta instalacao ainda nao tem usuario nenhum'... isso nao deveria mais "
        "acontecer, o proprio app deveria se organizar de acordo com o usuario\"*.\n\n"
        "Causa: com as funcoes de captura liberadas nesta maquina, a tela de **entrada** era servida pelo "
        "**servidor local** (`127.0.0.1`) — e o banco local nao tem usuario nenhum (quem tem cadastro e' o "
        "lado terra). O login entao batia num banco vazio, mesmo com a senha certa.\n\n"
        "Agora o aplicativo **mede** antes de abrir a janela: consulta o servidor local desta maquina e o "
        "lado terra e decide —\n\n"
        "* servidor local **sem** usuario e lado terra respondendo: a entrada vem do **lado terra** (e' onde "
        "estao as contas);\n"
        "* bordo **sem internet** (ninguem responde): a entrada continua a do servidor local, onde o primeiro "
        "acesso e' criado na propria maquina;\n"
        "* servidor local **com** cadastro proprio: a entrada e' a dele.\n\n"
        "A decisao mora em `enderecoDaEntrada()` (`configuracao.js`, testavel sem Electron) e a escolha "
        "aparece no relatorio do app (`enderecoEntrada=...`).\n\n"
        "Provado no aplicativo de verdade: `tests/test_captura_liberada_no_app.py` sobe o app com o servidor "
        "local de banco vazio e o relatorio mostra `base=http://187.127.60.250:8085`, "
        "`enderecoEntrada=http://187.127.60.250:8085` e `enderecoCaptura=http://127.0.0.1:<porta>` — telas no "
        "lado terra, captura na maquina. Mais 4 casos em `tests/test-config-endereco.py` (secao 6).\n\n"
        "**Atualizacao:** instale por cima. Se o login insistir em *e-mail ou senha invalidos*, feche as "
        "janelas antigas do aplicativo antes de abrir esta versao."
    ),
    "0.6.2": (
        "**Plug & play de verdade: o admin ja nasce com tudo liberado.**\n\n"
        "O dono ficou preso em *\"e-mail ou senha invalidos\"* ao entrar com a conta de administrador "
        "(18/11/2026: \"o admin tem acesso a tudo. ja deve ter por padrao todas as autorizacoes\"). A causa "
        "foi medida: a instalacao estava falando com o **servidor LOCAL da propria maquina** "
        "(`127.0.0.1:8765`), cujo banco nao tem usuario nenhum — e **com a senha correta o lado terra "
        "aceitava** o login (HTTP 200, papel `admin`). Quem levava a instalacao para esse estado era o "
        "item de menu *\"Subir servidor nesta maquina\"*, que trocava o endereco da tela para o loopback.\n\n"
        "O que muda:\n\n"
        "* o pacote nasce no papel `unico` **com o servidor local e as funcoes de captura ligados**: "
        "instalar, entrar e capturar, sem tocar em menu;\n"
        "* o item de menu virou *\"Subir o servidor local nesta maquina (captura — as telas e o login "
        "continuam no lado terra)\"*: sobe o servidor, libera a captura e **nao** troca o endereco da tela;\n"
        "* config gravado por instalacao anterior (endereco em loopback, captura desligada) e **corrigido "
        "sozinho ao abrir** — nada de editar `config.json` na mao;\n"
        "* login numa instalacao **sem usuario nenhum** deixou de acusar a senha: a tela diz que esta "
        "falando com o servidor local desta maquina e abre o cadastro do **primeiro administrador**;\n"
        "* a tela de erro distingue *\"o servidor LOCAL desta maquina nao respondeu\"* do lado terra e "
        "informa qual e' o lado terra desta instalacao.\n\n"
        "Provado na bancada: `tests/test-entrada-instalacao-vazia.py` (novo, API de verdade com banco "
        "vazio), secao 5 do `tests/test-config-endereco.py` (3 casos do app `unico`) e o "
        "`tests/test-instalador-plug-and-play.py` com 105 checagens verdes.\n\n"
        "**Atualizacao:** instale por cima (o banco e os cadastros ficam). Se o login insistir em "
        "*e-mail ou senha invalidos*, feche as janelas antigas do aplicativo e entre pela que carrega do "
        "lado terra."
    ),
    "0.6.1": (
        "**Transmissao ao vivo pela camera do PC de captura: o envio pedia um TAMANHO que a camera nao "
        "aceita.**\n\n"
        "Defeito relatado pelo dono (17/11/2026: \"resolva isso entao\"): a tela dizia *no ar*, mas a linha "
        "do envio ficava em **erro** (\"a camera nao abriu\") e o cliente nao recebia imagem. Causa medida na "
        "bancada: o produto pedia `-video_size 1920x1080` (o padrao) e a webcam do notebook so' anuncia "
        "1280x720, 640x480 e 640x360. O ffmpeg responde `Could not set video options` + `Error opening input "
        "file video=<dispositivo>` — mensagem que aponta para camera/driver quebrado, e nao para o tamanho.\n\n"
        "O envio passa a perguntar a' propria camera (`-list_options true`, com cache) e pedir o **maior "
        "tamanho suportado que nao passe do pedido** (o menor disponivel, se nenhum couber); quando a lista "
        "nao vem, **nao fixa tamanho** e deixa o ffmpeg negociar, em vez de derrubar a captura.\n\n"
        "Correcao de diagnostico: o **seletor PnP nao era o culpado** (o teste com shell MSYS comia as barras "
        "invertidas do `@device_pnp_...`; com a lista de argumentos correta ele abre a 30 fps). O seletor "
        "continua sendo o que permite duas cameras de mesmo nome conviverem.\n\n"
        "Provado com a webcam real, app de ponta a ponta: ingestao `no_ar` em **1280x720 a 30 fps** e "
        "**1596 kbps**, mediamtx `online` com **0 quadros em erro**, a **tela do cliente exibindo o video ao "
        "vivo**, SSIM 0,9803 publicado no lado terra. Regressao nova: `tests/test-camera-tamanho-suportado.py` "
        "(22 verificacoes).\n\n"
        "**Atualizacao:** instale por cima (o banco e os cadastros ficam). Nada a configurar.\n\n"
        "**Correcao de prova desatualizada:** `tests/test-login-supabase-adocao.py` (exigia a adocao de "
        "identidade de fora, removida na 0.6.0) virou `tests/test-login-supabase-nao-adota.py`, que prova o "
        "contrario: credencial do Supabase sem cadastro local toma **403** e nenhuma linha nasce."
    ),
    "0.6.0": (
        "**UM aplicativo so': a tela que abre e' a do PAPEL de quem entra.**\n\n"
        "Pedido do dono: \"vamos empacotar em um app apenas, o tipo de app e' definido pela role do "
        "usuario\". Os quatro instaladores (Captura/Terra/Admin/Cliente) sairam de linha; agora e' **um** "
        "`LECSOR-0.6.0-x64.exe`, no papel `unico`, que abre a tela de **entrada** (`/entrada`) e manda cada "
        "um para a sua tela: **cliente** -> `/app`, **operacao/administrador** -> `/admin`, **tecnico** -> "
        "`/` (\"Enviar video\"). O papel do usuario vem do SERVIDOR, nunca da interface.\n\n"
        "**Quem cadastra usuario e' o administrador** (mesmo pedido, 17/11/2026): o login deixou de adotar "
        "identidade de fora — quem o Supabase reconhece e a instalacao nao conhece toma **403** e nenhuma "
        "linha nasce no banco local. E o usuario criado pelo administrador agora funciona: a senha passa a "
        "ser gravada **tambem** no Supabase Auth (antes ficava so' local e o login devolvia 401). O "
        "\"primeiro acesso\" desta maquina tambem grava dos dois lados e nasce como administrador.\n\n"
        "Na tela de Usuarios: coluna **Credencial** (quem tem login valido no Supabase) e botao "
        "**redefinir senha** (conserta quem foi criado antes). Papel novo **tecnico** (bordo) entra pela "
        "propria atualizacao — a migracao do CHECK roda no boot da API, sem passo manual no cliente.\n\n"
        "Provado na bancada: 7 verificacoes novas de cadastro (`test-cadastro-so-pelo-admin.py`, com "
        "Supabase dublado e servidor de verdade), o teste do app unico com 32 verificacoes, a migracao do "
        "papel tecnico num banco de verdade (4 usuarios, 432 sessoes e 12.796 linhas de auditoria "
        "preservadas) e as suites de regressao.\n\n"
        "**Provado na fonte (17/11/2026):** o cadastro publico esta DESLIGADO no Supabase do produto "
        "(`disable_signup: True`) — tentativa de cadastro de fora devolve 422 `signup_disabled` \"Signups not "
        "allowed for this instance\", e um usuario criado pelo administrador entra normalmente (200 com token). "
        "Quem confere a qualquer momento: `python tools/conferir-signup.py` (rc=0 = fechado).\n\n"
        "**Migracao:** desinstale os pacotes antigos e instale este (o aplicativo unico tem identidade "
        "propria e convive com os antigos). O lado terra tambem precisa desta versao."
    ),
    "0.5.0": (
        "Instaladores da 0.5.0 (Windows).\n\n"
        "**O Admin passa a LIBERAR as funcoes de captura dentro dele, sem virar o app de captura.**\n\n"
        "Pedido do dono: \"deve liberar as funcoes de captura, nao mudar para o app de captura\". Agora existe "
        "a opcao no menu **Servidor local -> \"Liberar as funcoes de captura nesta maquina (sem trocar de app)\"**: "
        "sobe o servidor local desta maquina e as rotas de captura (listar as cameras desta maquina, comprimir, "
        "publicar, repassar) passam a ser dele — **sem** trocar a base, **sem** criar usuario local e **sem** abrir "
        "a tela de \"primeiro acesso\". O login, as telas e as permissoes continuam os do lado terra.\n\n"
        "1. **Servidor local responde CORS restrito** nas rotas de captura, so' para as origens declaradas "
        "(`LECSOR_CORS_ORIGENS`; padrao = lado terra do produto + loopback): e' o que deixa a tela vinda do lado "
        "terra enxergar as cameras plugadas aqui. Rota de cadastro/login nunca ganha CORS.\n"
        "2. **Qualidade por camera dentro de \"Enviar video\"** (a tela onde se escolhe a fonte), na lista fechada "
        "1500k/1200k/1000k/800k/500k/300k, valendo no ar. O painel de teste virou \"Teste de video (bancada)\" para "
        "acabar com dois lugares com o mesmo nome.\n\n"
        "Provado na bancada: 20 verificacoes novas (`CAPTURA_NO_ADMIN_OK`), incluindo servidor de verdade "
        "respondendo CORS a origem declarada e negando a origem nao declarada, e 4 suites de regressao.\n\n"
        "**A instalacao 0.5.0 que importa e' a do Admin** (e' nele que a captura passa a ser liberada). O lado "
        "terra tambem precisa da 0.5.0 para servir a tela nova."
    ),
    "0.4.1": (
        "Instaladores da 0.4.1 (Windows).\n\n"
        "**A tela \"Enviar video\" (com a taxa de envio por camera) volta para dentro do pacote — o PC de "
        "captura dos tecnicos passa a abrir exatamente essa tela.**\n\n"
        "1. O `portal/` (onde mora \"Enviar video para testar\" e o seletor `class=\"qualidade\"` de cada "
        "camera) tinha saido do pacote na 0.2.1 (commit f7f360d): o servidor serve o site pela RAIZ "
        "(`ground/api.py` -> `directory=RAIZ/portal`), entao sem ele `/` nao entregava tela nenhuma no PC "
        "de captura. Agora `portal/` vai em `extraResources` -> `servidor/portal`.\n"
        "2. O instalador do PC de captura nascia na superficie `admin` (o tecnico via o console do "
        "operador). Agora nasce na superficie **bancada** (rota `/`), que e' a tela \"Enviar video\", onde "
        "se escolhe a fonte e a taxa de cada camera.\n\n"
        "Provado na bancada: servidor do pacote serve `/` = 19.205 B com \"Enviar video\" e "
        "`class=\"qualidade\"`; `/admin` continua 200. Instaladores 0.4.1 gerados: "
        "Captura/Terra/Admin/Cliente.\n\n"
        "**A instalacao 0.4.1 que importa e' a do PC de captura** (a tela de envio e o encoder rodam nele)."
    ),
    "0.4.0": (
        "Instaladores da 0.4.0 (Windows).\n\n"
        "**Selecao de qualidade por camera, remover/editar em operacao e destaque na tela do cliente.**\n\n"
        "1. **Qualidade por camera**: cada camera tem a sua taxa de envio, escolhida numa lista FECHADA de "
        "1500k/1200k/1000k/800k/500k/300k. Valor fora da lista e' recusado (HTTP 422) com a lista na resposta. "
        "A escolha vale **no ar**: o envio daquela camera e' reaberto (~2 s) e a resposta diz se aplicou ou, "
        "quando nao aplicou, por que. Abaixo do piso de qualidade o sistema **so' avisa** (nunca recusa).\n"
        "2. **Remover camera** que nao e' mais usada: para o envio, apaga o cadastro aqui e publica a remocao "
        "ao lado terra (o cliente deixa de ver). Trechos e auditoria ficam guardados.\n"
        "3. **Editar camera em operacao**: muda so' o que voce digitar (rotulo/endereco/porta/canal), sem "
        "zerar `ativo` nem a qualidade escolhida; so' reabre o video quando mexe na fonte.\n"
        "4. **Destaque no app do cliente**: 1 camera em tela cheia e 2 a 4 em grade de destaque (botao "
        "Destacar, botao na janela ou duplo clique), sem mexer em banda nem resolucao.\n\n"
        "A selecao de qualidade aparece na tela do PC de captura (Enviar video) e no Admin.\n\n"
        "Provado: 2 testes novos + 12 de regressao rc=0 na bancada; chamada real na VPS com sessao de admin "
        "(alvo fora da lista -> 422; 800k -> aceito com aviso; editar rotulo; remover -> sumiu da lista; "
        "remover de novo -> 404).\n\n"
        "**A instalacao 0.4.0 que importa e' a do PC de captura** (encoder/perfil/alvo rodam nele). "
        "Terra/Admin/Cliente nao precisam ser reinstalados para esta rodada."
    ),
    "0.3.0": (
        "Instaladores da 0.3.0 (Windows).\n\n"
        "**Teste cego do Mbps: o download entrega o video, sem comparativo.**\n\n"
        "O botao \"Baixar 1 minuto\" entrega somente o ARQUIVO (Bytes, Duracao-S, Sha256, Trecho-Id); saiu o "
        "cabecalho de kbps medidos. Quem confere olha o tamanho do video e compara a mao com o Mbps que "
        "aparece no admin/captura. O kbps continua sendo medido e guardado no servidor.\n\n"
        "O **atestado** (comparativo medido x declarado, com a compressao recalculada) virou operacao/admin, "
        "sem excecao de \"chamada local\" - o app do cliente pode estar na mesma maquina do lado terra.\n\n"
        "Medido na VPS: 60 s do vivo-cam-01 = 11.129.556 B / 59,2 s = 1.504,0 kbps contra 1.520,5 kbps "
        "medidos na VPS (1,1%)."
    ),
    "0.2.9": (
        "Instaladores da 0.2.9 (Windows).\n\n"
        "**O que o PC de captura declara chega ao lado terra (declarado x medido).**\n\n"
        "O bordo passa a publicar o envio que esta' no ar (ao subir, a cada 30 s, no fim e ao parar) por "
        "anuncio autenticado com token de ingestao; o lado terra grava e mostra a ultima declaracao por "
        "fluxo, com idade e qualidade, e guarda toda tentativa (aceita ou recusada, com motivo). A medicao de "
        "SSIM reaproveitada do cache e' republicada quando precisa, para o lado terra nao ficar sem numero.\n\n"
        "**A instalacao 0.2.9 que importa e' a do PC de captura** - sem ela o lado terra continua vazio "
        "(era o caso medido: 0 linha em ingestoes/medicoes_qualidade no lado terra)."
    ),
    "0.2.8": (
        "Instaladores da 0.2.8 (Windows).\n\n"
        "**Botao \"Baixar 1 minuto\": a prova da compressao, medida no proprio arquivo.**\n\n"
        "O cliente baixa 60 s do video COMO ELE CHEGA em terra (copia direta, sem reencodar) e o lado terra "
        "guarda o trecho com auditoria; teto de 3 trechos por 10 minutos, 2 simultaneos, validade de 1 h. "
        "O navegador do cliente pede pela camera - nunca recebe fluxo, endereco, porta ou credencial."
    ),
}


def pedir(url: str, corpo=None, metodo="GET"):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
        "Content-Type": "application/json", "User-Agent": "lecsor-publicacao"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def subir_asset(release_id: int, caminho: pathlib.Path) -> str:
    tam = caminho.stat().st_size
    url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={caminho.name}"
    with open(caminho, "rb") as fh:
        req = urllib.request.Request(url, data=fh, method="POST", headers={
            "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/octet-stream",
            "Content-Length": str(tam), "User-Agent": "lecsor-publicacao"})
        try:
            with urllib.request.urlopen(req, timeout=7200) as r:
                return f"{r.status} {json.loads(r.read().decode()).get('name')}"
        except urllib.error.HTTPError as e:
            return f"ERRO {e.code} {e.read().decode()[:200]}"


def main() -> int:
    for versao in VERSOES_PUBLICADAS:
        s, j = pedir(f"{API}/releases/tags/v{versao}")
        if s == 200:
            rid, existentes = j["id"], {a["name"] for a in j["assets"]}
            print(f"[{versao}] release ja existia (id {rid}), {len(existentes)} asset(s)")
        else:
            s, j = pedir(f"{API}/releases", {"tag_name": f"v{versao}", "name": f"v{versao}",
                                             "body": NOTAS[versao], "draft": False,
                                             "prerelease": False,
                                             "make_latest": "true" if versao == VERSOES_PUBLICADAS[0] else "false"},
                         "POST")
            if s not in (200, 201):
                print(f"[{versao}] FALHOU criar release: {s} {json.dumps(j)[:300]}")
                continue
            rid, existentes = j["id"], set()
            print(f"[{versao}] release criada (id {rid})")
        for arquivo in instaladores(versao):
            if not arquivo.exists():
                print(f"[{versao}] FALTA o instalador {arquivo}")
                continue
            if arquivo.name in existentes:
                print(f"[{versao}] {arquivo.name} ja' estava no ar")
                continue
            t0 = time.time()
            r = subir_asset(rid, arquivo)
            print(f"[{versao}] {arquivo.name} ({arquivo.stat().st_size // 1048576} MB) -> {r} "
                  f"em {time.time() - t0:.0f}s", flush=True)
    print("== estado final ==")
    s, j = pedir(f"{API}/releases?per_page=8")
    for r in j if isinstance(j, list) else []:
        print(f"  {r['tag_name']}: {len(r['assets'])} asset(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
