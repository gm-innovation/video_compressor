"""Publica as releases 0.2.8 / 0.2.9 / 0.3.0 / 0.4.0 / 0.4.1 / 0.5.0 no GitHub com os 4 instaladores cada.

O repositorio e' gm-innovation/video_compressor; a ultima release que existia era a v0.2.7.
O token sai do arquivo normalizado (~/.hermes/vps-deploy/gh-token.txt.norm) e NUNCA e' impresso.
"""
import json
import os
import pathlib
import re
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
# A 0.8.0 nunca chegou a virar release: o que ela trazia (config do bordo vinda de terra e saude do
# bordo no admin) entrou inteiro na 0.9.0, que e' quem publica. A nota dela fica em NOTAS abaixo.
VERSOES_PUBLICADAS = ("0.24.0", "0.23.0", "0.22.0", "0.21.0", "0.20.0", "0.19.0", "0.18.0", "0.17.0", "0.16.0", "0.15.0", "0.14.0", "0.13.2", "0.13.1", "0.13.0", "0.12.0", "0.11.1", "0.11.0", "0.10.1", "0.10.0", "0.9.1", "0.9.0", "0.7.0", "0.6.10", "0.6.9", "0.6.8", "0.6.7", "0.6.6", "0.6.5", "0.6.4", "0.6.3", "0.6.2", "0.6.1", "0.6.0", "0.5.0", "0.4.1", "0.4.0", "0.3.0", "0.2.9", "0.2.8")


def instaladores(versao: str) -> list:
    """Os arquivos .exe daquela versao.

    Da 0.6.0 em diante e' UM aplicativo so' (`dist/unico/LECSOR-<versao>-x64.exe`): o pacote nasce no
    papel `unico` e a tela que abre e' a do papel de quem entra (dono, 17/11/2026). As versoes antigas
    seguem com um instalador por papel, que e' como elas foram publicadas.
    """
    # Comparacao por NUMERO, nao por texto: "0.10.0" >= "0.6.0" e' FALSO em texto ("1" < "6") e a 0.10.0
    # caiu no ramo antigo — a release foi criada VAZIA (4 instaladores por papel que nao existem mais).
    def _numeros(v: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", v)[:3]) or (0,)

    if _numeros(versao) >= (0, 6, 0):
        return [a for a in sorted((DIST / "unico").glob(f"*{versao}*.exe")) if "ninstaller" not in a.name]
    return [DIST / papel.lower() / f"LECSOR-{papel}-{versao}-x64.exe" for papel in PAPEIS]

NOTAS = {
    "0.24.0": "**\"Gravações\" é uma página só (o gravado a bordo em cima, o gravado em terra embaixo) e os quatro tipos de cliente viram usuários de teste na VPS.**\n\nPedido do dono (26/11/2026): \"as telas 'Gravações' e 'Radar de óleo (HD)' podem ser uma página apenas 'Gravações'\" · \"preciso de usuários de todos os tipos de clientes para testar, essa que estamos utilizando aparentemente é de clientes que têm acesso a apenas uma embarcação\". Decisões dele: **D1** dois blocos na mesma página · **D2** criar os dados/usuários na VPS (onde ele testa) · **D3** sim, com \"TESTE\" no nome · **D4** senha só pelo painel (nada passa por chat).\n\n**1. Uma página, dois blocos.** O cliente tinha dois itens de menu ([2] \"Gravações\" = o que já chegou em terra; [3] \"Radar de óleo (HD)\" = o HD do computador de captura). Viraram UM item: \"Gravações\" abre com a faixa de filtro (data e hora) valendo para os dois, o bloco do bordo em cima (título \"Gravado a bordo · Radar de óleo (HD)\" quando a embarcação tem radar) e o bloco de terra embaixo. O observador (Petrobras/IBAMA) vê SÓ o bloco do bordo — o gravado em terra é do cliente. Nada de rota nova: as mesmas `/api/hd/*` e `/api/gravacoes/*`. A tela não pisca: o ciclo de 5 s redesenha os blocos no lugar, sem remontar o palco.\n\n**2. Os quatro tipos de cliente.** O tipo NÃO é um campo: é DERIVADO dos vínculos (`escopo_do_cliente`). Sem vínculo = todas as embarcações da empresa; 1 vínculo = uma; 2+ = algumas; papel observador = todas as empresas. O que faltava era ESTRUTURA, não código — a instalação tinha uma embarcação por empresa e ZERO vínculos, então os quatro tipos davam no mesmo. Agora existe uma semente idempotente (`tools/seed-usuarios-de-teste.py`, com `--limpar`) que cria, na VPS, tudo com \"TESTE\" no nome: uma segunda e uma terceira embarcação na empresa de exemplo, radar de óleo em duas delas, uma embarcação de teste na outra empresa (para o observador ter duas empresas de verdade), blocos no catálogo do HD, uma gravação em terra e os quatro usuários — `cliente-1-embarcacao@demo.test` (uma), `cliente-2-embarcacoes@demo.test` (algumas), `cliente-todas-da-empresa@demo.test` (todas da empresa) e `observador@demo.test` (todas as empresas). A senha é redefinida no painel, uma vez, na tela do admin.\n\n**3. Achado e corrigido na prova dos quatro tipos:** o catálogo do HD (`GET /api/hd/catalogo`) para o papel `cliente` filtrava só pelo `cliente_id` — um usuário de UMA embarcação enxergava o HD das OUTRAS embarcações da mesma empresa. Passou a usar a regra única `pode_ver_embarcacao`, a mesma que vale para câmeras e transmissões.\n\n**4. O que não muda:** o lado terra continua sem saber IP nem senha de câmera; o bordo só detecta/comprime/envia; as rotas `/api/hd/*` seguem iguais para cliente e observador; a regra de encerramento continua valendo.\n\nProvas: `tests/e2e-pagina-unica-de-gravacoes.py` (**novo** — tela: um item de menu, dois blocos, filtro nos dois, o palco sobrevive ao ciclo de 5 s, PEDIR cria o pedido no lado terra, BAIXAR entrega o arquivo inteiro, as outras telas seguem funcionando, sem erro de javascript) e `tests/test-os-4-tipos-de-cliente.py` (**novo** — servidor de verdade: cada um dos 4 usuários entra e o que ele enxerga é medido — 1 / 2 / 3 embarcações, o observador com as embarcações de duas empresas e só radar/FLIR, e o HD do bordo escopado pelo vínculo), mais `tests/e2e-observador-do-radar.py`, `tests/e2e-tela-do-radar-hd-do-cliente.py`, `tools/regressao-0130.py` e `python -m unittest discover -s tests -p \"test_*.py\"`.",
    "0.23.0": "**O admin liga e para a câmera no ao vivo, e o monitoramento diz se está sendo gravado a bordo.**\n\nPedido do dono (26/11/2026): \"eu devo poder ligar e parar a câmera também, 'imagens gravadas a bordo' não faz sentido, só preciso no monitoramento saber se está sendo gravado a bordo, não preciso ver as imagens\" · \"mas não são as imagens gravadas, é ao vivo, preciso poder selecionar a empresa>embarcação>câmera\". Decisões dele para esta rodada: **2.A** (o admin é plateia da MESMA sessão do cliente) e **botão ligar/desligar + indicador** para a gravação contínua do radar.\n\n**1. A tela \"Imagens gravadas a bordo\" saiu da área do admin.** Ela não fazia sentido ali: o admin não precisa ver o arquivo, precisa saber se o bordo está gravando. A tela e o item de menu saíram do admin — e as ROTAS continuam no ar (`/api/hd/catalogo|pedir|baixar`), que são as que servem o cliente (Radar de óleo (HD)) e o observador Petrobras/IBAMA.\n\n**2. O admin liga e para a câmera no ao vivo (2.A).** O \"Ver ao vivo\" do monitoramento deixou de ser só leitura: a operação (admin/operador/técnico) abre a MESMA sessão que o cliente abre, com a empresa, a embarcação e as câmeras daquela embarcação. Enquanto a janela estiver aberta a sessão vive (batimento); ao fechar a tela, a câmera PARA — nada fica no ar sem plateia — e o botão \"parar\" encerra na hora. A Auditoria registra que quem ligou foi a OPERAÇÃO (\"transmissao_pedida ... — operacao\"), com o e-mail. Papel sem permissão (observador) continua recusado.\n\n**3. \"Gravando a bordo\" no monitoramento — ou \"não medido\".** Faltava a medida: a coluna existia no banco, mas o computador de captura não contava no retrato de estado, então terra mostrava zero com cara de saúde. Agora o bordo conta `gravando` por câmera e a tela separa os três casos de verdade: \"gravando a bordo: N câmera(s)\", \"gravando a bordo: não\" e **\"não medido\"** (quando o bordo não contou — nunca um \"desligado\" inventado).\n\n**4. Botão da gravação contínua do radar.** O cartão da embarcação ganhou ligar/desligar a gravação contínua do radar (o radar grava o tempo todo no HD do bordo; quando o disco enche, o bloco mais antigo sai). É da EMBARCAÇÃO (recusa `camera_id`), valor 0/1, e nasce DESLIGADA. O lado terra continua NUNCA abrindo conexão para bordo: o admin PUBLICA a configuração e o bordo OLHA e aplica, escrevendo o desejo no HD. Sem dispositivo de vídeo na máquina, o bordo responde que não há o que gravar — nunca finge um \"ligado\" que não grava.\n\n**5. O que não muda:** o cliente continua ligando a transmissão dele como sempre; as rotas de HD do cliente e do observador continuam iguais; o lado terra segue sem saber IP nem senha de câmera; e a regra do encerramento segue valendo.\n\nProvas: `tests/test-ao-vivo-do-admin-ligar-parar-e-gravando-a-bordo.py` (**novo** — servidor de verdade: a tela saiu e as rotas ficam; o admin liga (201) e o desejo vira `ligar` pela plateia dele; a Auditoria guarda `— operacao`; PARAR volta a `parar`; observador segue 403; o bordo conta `gravando` e o monitoramento diz N câmeras ou **não medido**; o botão publica `gravacao_continua` e o bordo aplica no HD, desligando também; valor fora de 0/1 e pedido com `camera_id` são recusados), mais `tests/e2e-admin-unificado.py`, `tools/regressao-0130.py` e `python -m unittest discover -s tests -p \"test_*.py\"`.",
    "0.22.0": "**O tipo da câmera volta a aparecer na tela, a tela para de piscar e a varredura vira um botão.**\n\nPedido do dono (26/11/2026): \"eu aplico novo tipo à câmera, mas não está persistindo\" · \"quando a página atualiza, parece que remonta toda a página, isso é horrível, eu estou fazendo algo e do nada a página 'pisca' e eu perco o que estou fazendo\" · \"nesta tela preciso também de um botão para refazer varredura ... o app de captura precisa refazer a varredura das câmeras, mas apenas inclui as que não estão aparecendo, não remonta tudo pra não perder as configurações já feitas\".\n\n**1. O tipo nunca deixou de ser gravado — quem mentia era a LEITURA.** A gravação sempre esteve certa; a rota que monta a árvore do painel (`/api/empresas`) lia as câmeras SEM a coluna `tipo`, e o cartão caía no palpite pelo nome — por isso a câmera que o admin marcava como radar voltava a \"câmera comum\" ao repintar. O `SELECT` do painel passou a trazer o `tipo` e o cartão mostra exatamente o que foi escolhido. A varredura do bordo continua podendo PROPÔR o nome, mas o tipo definido pelo admin nunca é sobrescrito.\n\n**2. A tela para de piscar.** A ação do usuário (aplicar tipo, aplicar qualidade, salvar nome, ativar/desativar, desligar, remover) passou a refazer SÓ o cartão afetado — os outros cartões e o resto da tela continuam sendo os mesmos elementos. E o auto-refresh de 15 s não repinta mais a tela de trabalho: quando chega novidade, ele avisa (\"há mudança nova — clique em Atualizar\"); o botão \"Atualizar\" continua sendo o único jeito de repintar de propósito. Campos que mudam sozinhos (uso da licença, hora da última varredura) saíram da impressão digital que decide se \"mudou\".\n\n**3. A varredura vira botão.** O cartão da embarcação ganhou \"refazer varredura\": só entram as câmeras que ainda não aparecem; nada já configurado é mexido (o nome, o tipo e a qualidade ficam). O pedido viaja como configuração publicada (chave `varrer`, da embarcação) — o lado terra continua NUNCA abrindo conexão para o bordo: o bordo olha a configuração, roda a varredura e confirma. Cada pedido é uma versão nova, para o bordo não confundir pedido velho com novo, e o cartão mostra a hora do pedido esperando o bordo.\n\n**4. O que não muda:** a varredura automática continua com o intervalo dela (o botão é um pedido EXTRA), a câmera que sumiu NÃO é apagada (some da lista, o cadastro fica), o histórico de quem pediu o quê fica registrado, e o lado terra segue sem saber IP nem senha de câmera.\n\nProvas: `tests/test-tipo-lido-do-banco.py` (**novo** — o tipo aplicado pelo admin volta IGUAL na área única, vale para radar/FLIR, um tipo fora da lista é recusado, e `/api/cameras` e `/api/empresas` concordam), `tests/test-varredura-a-pedido.py` (**novo** — o pedido é da embarcação, cada pedido é uma versão nova, a câmera que já existia mantém nome/tipo/alvo, a que sumiu não é apagada e pedir de novo não duplica), `tests/test-tela-sem-piscar-e-varredura.py` (**novo** — navegador de verdade: o cartão é marcado no DOM, a ação e o timer de 15 s NÃO trocam os outros cartões, e o botão publica o pedido), mais `tests/e2e-admin-unificado.py`, `tools/regressao-0130.py` e `python -m unittest discover -s tests -p \"test_*.py\"`.",
    "0.21.0": "**Qualidade de envio com 3,0 / 2,5 / 2,0 Mbps de verdade, e a tela \"Configuração do bordo\" sai do caminho: o teto da embarcação vai para o cartão da embarcação e a qualidade de envio mora no cartão da câmera.**\n\nPedido do dono (26/11/2026): \"inclua no plano mais possibilidades de qualidade de envio, 2mbps, 2,5mbps e 3mbps\" · \"o bloco de seleção de qualidade de envio sumiu da tela de configuração de bordo\" · \"se eu consigo editar empresa, embarcação e câmeras em 'Empresas e configuração', é necessário 'Configuração do bordo'?\" · \"não daria pra mudar para essa outra tela e remover configuração do bordo? precisamos deixar tudo mais simples\".\n\n**1. A lista de qualidade ganhou 3,0 / 2,5 / 2,0 Mbps** — passou de 6 para 9 níveis, exibidos do maior para o menor (3000 / 2500 / 2000 / 1500 / 1200 / 1000 / 800 / 500 / 300 kbps). A lista continua FECHADA — o servidor recusa qualquer valor fora dela — e agora é UMA fonte só: o admin deriva de uma constante única e `tests/test-lista-de-alvos-igual-ao-servidor.py` compara as duas listas. A escada de sugestão de qualidade, que estava copiada à mão e parava em 1500k, passa a sair da própria lista do produto.\n\n**2. O TETO de transmissão da embarcação foi para o cartão da embarcação**, em \"Empresas e configuração\" → \"Abrir\" na empresa, ao lado de \"editar embarcação\": campo em minutos, botão \"Publicar teto\" e o estado (publicado / aplicado pelo bordo). Mesma chave (`teto_s`, `camera_id` vazio), mesma rota (`POST /api/config`) e mesmo comportamento do bordo.\n\n**3. A tela \"Configuração do bordo\" saiu do menu.** Ela era só do admin e o que tinha de único era o teto; o ajuste por câmera (qualidade de envio, tipo, ligar/desligar) já morava no cartão da câmera desde a 0.20.0. Com isso o defeito que a tabela dela mostrava — chamar de \"RECUSADO\" o que o bordo confirmou — desaparece junto, e a tabela de configuração e as rotas continuam as mesmas para o bordo.\n\n**4. O menu da qualidade nunca mais abre em branco.** O seletor de qualidade do cartão da câmera era o único campo do cartão que aparecia vazio quando a câmera não tinha qualidade publicada (era o que o dono via no print): agora a primeira opção (o padrão do produto) fica escolhida, e um valor fora da lista continua visível como \"(fora da lista)\".\n\n**5. O que continua igual:** a lista é fechada no servidor (`VALORES_DE_ALVO` / `ALVOS_DE_QUALIDADE`), o bordo recebe a configuração por publicação do admin e confirma o que aplicou, o lado terra nunca abre conexão para o bordo, e nome/tipo da câmera seguem no cartão dela.\n\n**Ficou fora, esperando a sua decisão:** botão para EXCLUIR câmera. A rota existe e é testada (`POST /api/cameras/<id>/remover`, só admin, tira da operação sem apagar histórico) — o que não existe é o botão no cartão da câmera. Falta escolher se \"excluir\" é desativar (o que já existe) ou remover de verdade.\n\nProvas: `tests/test-lista-de-alvos-igual-ao-servidor.py` (**novo** — as duas listas idênticas, ordem do maior para o menor, nenhuma cópia antiga de volta e a tela removida que não volta) e `tests/e2e-qualidade-e-teto-em-empresas.py` (**novo** — navegador de verdade: o menu sem \"Configuração do bordo\", o teto no cartão da embarcação, os 9 níveis no cartão da câmera, publicar 3,0 Mbps e o teto gravando no banco, e o servidor aceitando 3000k e recusando 4000k), mais `tools/regressao-0130.py` (39 provas) e `python -m unittest discover -s tests -p \"test_*.py\"`.",
    "0.20.0": "**O cliente e o admin ficam organizados — a EMBARCAÇÃO aparece na tela do cliente, o teto de tempo é do ADMIN (e o servidor recusa o do cliente), o admin edita/renomeia a câmera COM TIPO e acessa o gravado a bordo, e os DOIS dashboards passam a falar a língua do Dock Check.**\n\nPedido do dono (25/11/2026), depois do levantamento total das telas: \"preciso que você faça um smoke test de ponta a ponta com todos os usuários\" · \"tela 'Transmitir' também sem utilidade\" · \"pra que serve esse relatório? não serve pra nada\" · \"e essa, qual a embarcação? não está aparecendo lá\" · \"ainda não consigo acessar as imagens na área do admin, precisa resolver isso\" · \"estou com o admin aberto e não vejo onde editar as câmeras, embarcações e clientes\" · \"tanto o dashboard do admin quanto o do app de captura continuam horríveis, precisa ser algo mais próximo desse do Dock Check\".\n\n**1. A tela do cliente perde o que não servia e ganha o que faltava.** Saíram \"Relatórios\", \"Transmitir\" e \"Tempo de transmissão\". O nome da EMBARCAÇÃO passou a aparecer no subtítulo e no cartão de cada câmera, junto do tipo (RADAR/FLIR) e da resolução; e a tela mostra o ESCOPO daquele login (uma embarcação da empresa, algumas, todas da empresa, ou todas as empresas — Petrobras/IBAMA). O controle de transmissão continua no quadro de cada câmera (iniciar, gravar, parar, estado).\n\n**2. O tempo máximo é do ADMIN, e quem recusa o do cliente é o SERVIDOR.** `POST /api/transmissao/config` responde **403** para o papel `cliente`; a tela do cliente nem oferece o campo. Não é regra de tela — é regra de servidor (provada em `tests/e2e-transmissao-na-tela.py`, seção 7).\n\n**3. O admin edita a câmera COM TIPO — e o bordo propõe, o admin decide.** O cartão da câmera no admin ganhou Editar/Renomear e o seletor de TIPO (Câmera comum / Radar de óleo / FLIR). A partir do primeiro ajuste do admin, uma coluna nova (`tipo_definido_pelo_admin`) impede o anúncio do bordo de sobrescrever o tipo e o rótulo — era o que apagava a escolha do admin a cada varredura. É esse tipo que libera o radar de óleo e a FLIR para o observador.\n\n**4. O admin vê o GRAVADO A BORDO.** Nova tela \"Imagens gravadas a bordo\" no menu do admin: escolhe a EMBARCAÇÃO, vê os trechos que o PC de captura publicou (câmera, quando, tamanho), PEDE um trecho (o pedido fica na fila do bordo — o lado terra nunca abre conexão para o bordo) e BAIXA o que já chegou em terra. Sem catálogo, a tela diz o MOTIVO (a gravação contínua a bordo nasce desligada) em vez de uma lista vazia sem explicação.\n\n**5. \"Ver ao vivo\" com seletor.** O botão subiu para o topo da frota e abre a escolha empresa → embarcação → câmeras; a câmera que não está no ar diz \"sem imagem: o bordo só transmite com alguém assistindo — nenhum cliente na sala\" (o admin não liga transmissão: quem liga é o cliente). A janela segue somente-leitura.\n\n**6. Os DOIS dashboards na linguagem do Dock Check.** Um arquivo só (`fronts/dashboard.css`) veste o dashboard do admin e o painel do app de captura: cabeçalho com o estado da frota, fileira de KPI com ícone/rótulo/número/barra, câmeras por embarcação (barras + rosca), DISPONIBILIDADE (7 dias) MEDIDA retrato a retrato do que o bordo mandou, DIAGNÓSTICO DE CONEXÕES e alertas com \"o que fazer\". O semáforo tem três nomes — ok / atenção / problema — e uma regra dura: **o que não foi medido sai como \"—\" / \"não medido\", nunca um zero que parece saudável** (um bordo que nunca reportou nunca aparece \"ok\"). A telemetria por câmera/encoder ficou numa gaveta para o painel não virar parede de números.\n\n**7. Ferramenta:** `GET /api/frota-resumo` (só ADMIN — sem sessão, ou com cliente, devolve 401) entrega KPIs, embarcações, alertas e o estado das conexões; é o que a tela do admin lê.\n\nProvas: `tests/test-dashboard-frota.py` (**novo** — 401 sem sessão e com cliente, 200 com admin; os KPIs; a disponibilidade medida; o MESMO semáforo dizendo \"problema\" para CPU 93, \"atenção\" para CPU 78 e um bordo MUDO que não vira \"ok\") e `tests/e2e-hd-do-admin.py` (**novo** — o admin escolhe a embarcação, vê o catálogo do bordo, pede o trecho, baixa inteiro, e a segunda embarcação sem catálogo mostra o motivo), mais `tools/regressao-0130.py` e `python -m unittest discover -s tests -p \"test_*.py\"`.",
    "0.19.0": "**O observador (Petrobras/IBAMA) passa a ver por TIPO — o radar de óleo e a câmera FLIR (se houver) — e não mais pelo nome; o menu do admin e do cliente perde as telas sem função.**\n\nPedido do dono (25/11/2026): \"petrobrás ou ibama pode acessar todas as embarcações de todas as empresas, mas apenas do radar de óleo e câmera flir se tiver. já falei, você precisa fazer uma varredura completa nas páginas, tem muita redundância, telas inúteis ou que não funcionam\". E antes: \"preciso que você faça um levantamento total das áreas dos clientes e do admin, só precisamos organizar isso para finalizar o sistema\".\n\n**1. A câmera ganha o TIPO (`camera` | `radar` | `flir`).** O critério do observador deixou de ser procurar a palavra \"radar\" no nome e passou a ser o campo `tipo`, gravado no cadastro da câmera (feito no bordo). Uma câmera chamada \"Radar de antena\" que é câmera comum não aparece mais para o observador; e o radar de óleo aparece mesmo que não tenha \"radar\" no nome. A câmera FLIR (térmica) entrou no produto: é cadastrada com o tipo 'flir' e o observador a enxerga junto com o radar.\n\n**2. A migração corre sozinha.** Ao subir, um banco instalado ganha a coluna `tipo` e o backfill marca como 'radar' quem tem \"radar\" no nome (e 'flir' quem tem \"flir\"); o resto fica 'camera'. Sem passo manual no cliente — o cadastro que já existe continua funcionando.\n\n**3. O cadastro da câmera de rede ganha o Tipo.** No painel do bordo (`/bordo`), o cadastro da câmera IP ganhou o seletor de tipo (Câmera comum / Radar de óleo / FLIR). O IP e a senha continuam saindo SÓ do PC de captura.\n\n**4. O menu do admin fica enxuto (três grupos).** Configuração (Empresas e configuração · Monitoramento (frota)), Operação (Licenças · Usuários · Auditoria · Configuração do bordo · Saúde do bordo · Saúde do sistema · Enviar vídeo) e Projeto LECSOR (Painel · Fases · Medições · Decisões · Evidências · Documentos). Saíram do menu (e do despacho) as telas repetidas e sem função: Clientes, Embarcações, Câmeras, Produção, Tempo real, Análises e Marcas — câmera e embarcação se editam DENTRO de \"Empresas e configuração\".\n\n**5. O menu do cliente perde as telas sem função.** Saíram \"Pessoas\" (tabela vazia) e \"Avisos\" (só guardava no navegador). A tela \"Câmeras\" ganhou a coluna Tipo (Radar de óleo / FLIR / Câmera). E o item \"Radar de óleo (HD)\" só aparece quando a embarcação TEM radar.\n\nProvas: `tests/test-observador-por-tipo.py` (novo — sobe a `ground/api.py` de verdade e prova: radar pelo TIPO aparece mesmo sem \"radar\" no nome, a FLIR aparece, a câmera com \"radar\" no nome mas tipo 'camera' NÃO aparece, a resposta traz o tipo, e um banco ANTIGO ganha a coluna e o backfill) mais `tools/regressao-0130.py` (**35 provas, tudo verde**) e `python -m unittest discover -s tests -p \"test_*.py\"` (**22 OK**).\n",
    "0.18.0": "**O cadastro da câmera IP vai para o PC de captura: o endereço e a senha nunca saem do bordo — e o admin ganha a edição de empresa, embarcação e câmera.**\n\nPedido do dono (25/11/2026): \"preciso poder cadastrar câmeras ip, e como diz a regra, o app de captura precisa visualizar esse ip e fazer o apontamento, outra coisa, estou com o admin aberto e não vejo onde editar as câmeras, embarcações e clientes\". E a correção do desenho, no mesmo dia: \"não entendo nada disso, senha não pode vazar, então tem que tudo ficar no bordo, então não vamos poder inserir nem o ip no admin, o cadastro das câmeras ip terão que ser no app de captura\".\n\n**1. O endereço (IP) e a senha da câmera de rede vivem SÓ no PC de captura.** O admin deixou de ter campo de IP: o cadastro da câmera de rede é feito no painel do bordo (`/bordo`), que é servido pela própria máquina de captura e não pede login. O lado terra continua recebendo o cadastro (nome, estado, o que está publicado) — **nunca** o endereço nem a senha. Um cadastro vindo de fora da máquina de captura é recusado com **401**.\n\n**2. A senha não circula.** O cadastro guarda só o identificador; a senha vive num arquivo local com permissão restrita (`%PROGRAMDATA%\\LECSOR\\segredos\\cam-<id>.txt` no Windows, `~/.lecsor/segredos/` no Linux), com `LECSOR_CAM_<ID>_SEGREDO` tendo precedência (cofre/serviço do Windows). A tela mostra apenas **\"segredo configurado: sim/não\"**; a API **nunca** devolve a senha; e o log do ffmpeg é **redigido** (a senha não aparece na linha). Limite honesto: o ffmpeg ainda recebe a URL com a credencial na linha de comando — visível a um admin local daquela máquina; a mitigação registrada é a redação do log e o proxy local (mediamtx) como opção futura.\n\n**3. A câmera de rede convive com a de HDMI/split (D2).** O tipo \"rede\" entra no mesmo caminho de captura (RTSP), e as duas (a de rede e a do split) aparecem na mesma grade pela mesma regra de rótulo. Sem segredo configurado a captura **recusa** subir e diz o caminho do arquivo, em vez de pintar \"sem sinal\" na tela.\n\n**4. Editar no admin.** Empresa (nome e identificador), embarcação (nome e identificador) e câmera (rótulo e endereço de operação) passaram a ter edição de verdade — um formulário no próprio cartão, no lugar do `prompt()` que existia. O identificador é renomeável (D3), com transação nos filhos e trilha de auditoria de→para. Administrar continua **só do admin** (D4); a operação (ligar/desligar, gravar, escolher a qualidade do que está no ar, enviar vídeo) segue com operador e admin.\n\nProvas: `tests/test-camera-ip-no-bordo.py` (novo — sobe a `ground/api.py` de verdade com a máquina de captura declarada e prova: cadastro da câmera de rede **201**, o **estado** do segredo (nunca o valor), a recusa de campo de senha, a recusa de cadastro remoto (**401**) e o detalhe com o apontamento sem credencial) e `tools/regressao-0130.py` (**34 provas, tudo verde**).\n",
    "0.17.0": "**A contagem regressiva e o botao \"Continuar conectado\" aparecem na TELA CHEIA; RECARREGAR a pagina nao derruba mais a transmissao; e a camera PARADA nao encolhe mais a grade.**\n\nTestes do dono (25/11/2026): \"quando o video esta' em tela cheia, a contagem regressiva e o botao para permanecer conectado nao aparecem e quando o tempo se esgota, a transmissao e' interrompida\" · \"quando as transmissoes estao pausadas, a tela diminui, e quando recarrego a pagina, a transmissao e' interrompida\".\n\n**1. A tela cheia leva a contagem e o botao junto.** Causa medida no codigo: a tela cheia era pedida no proprio `<video>` (`v.requestFullscreen()`), e nessa tela o navegador renderiza SO' o video — o card (com a contagem, o \"Continuar conectado\" e o \"Reconectar\") e o aviso do ultimo minuto sao IRMAOS dele e desapareciam. Era por isso que a sessao morria sem o cliente ter onde clicar. Agora a tela cheia e' pedida na JANELA (`.janela`), com uma regra so' (`alternarTelaCheia`) usada pelo duplo clique, pelo destaque e pelo botao do cabecalho, e o CSS tem `.janela:fullscreen` (a janela ocupa a tela inteira e o card fica no rodape dela). O DESTAQUE tambem passou a montar o MESMO controle da grade (uma funcao, dois lugares): contagem, aviso do ultimo minuto, \"Continuar conectado\", \"Reconectar\" e os botoes de transmissao. O relogio de 1 s que repinta a contagem agora alcanca as janelas do destaque — antes so' a grade tinha contagem viva.\n\n**2. Recarregar a pagina nao interrompe mais a transmissao.** Causa: `pagehide` dispara IGUAL em F5 e em fechar a aba, e o lado terra tratava os dois como saida. Agora o pedido de saida sai marcado `pendente` e o lado terra o SEGURA por uma carencia de **8 s**: se a pagina volta (a recarga), o batimento cancela o pedido e a sessao continua; se nao volta, o vigia executa a saida. A saida PEDIDA pelo cliente (botao \"Parar transmissao\"/\"Sair\") continua valendo NA HORA, sem carencia — e o silencio de sempre segue mandando: quem recarrega e nao volta em 60 s (o batimento) tem a sessao encerrada como antes. Recarregar deixou de ser um caso especial de saida; nao virou perdao.\n\n**3. A camera parada nao encolhe a grade.** Causa medida: a proporcao da grade era a **MENOR** das conhecidas, e uma camera parada reporta um quadro que nao e' o do fluxo (um quadro de \"sem sinal\") — com 4 cameras 16:9 e uma delas parada, a proporcao da grade caia e TODAS as celulas encolhiam junto. A conta fechou com o print do dono: as 4 celulas com \"parada\" mediram **347x347 = 1,00:1** (um quadrado), nao os 16:9 do fluxo. Agora: (a) a proporcao **declarada** (a resolucao do encoder, que o lado terra ja' conhece) entra ANTES de qualquer imagem; (b) um quadro abaixo de 90 px de altura (1x1, 16x16) nao sobrescreve a proporcao conhecida; e (c) a proporcao da grade e' a **MEDIANA** das conhecidas, nao a menor — a maioria manda. Medido no app de verdade, com um fluxo 16:9: com a proporcao errada (1:1) a celula media 582x582 e a imagem pintada 582x327 (**190.532 px2**); com a proporcao do fluxo a celula mede 1028x578 e a imagem 1028x578 (**594.441 px2**) — **+212% de area de imagem (3,12x)**. Com tres cameras 16:9 e uma de retrato, a grade vale 16:9 (a MENOR daria 0,56:1) — provado no e2e.\n\n**4. Uma correcao de coerencia no mesmo caminho.** `baterPonto()` passou a ser chamado tambem no arranque da tela: e' ele que cancela um pedido de saida pendente. Sem isso, uma recarga que chegasse durante a carencia e nao batesse ponto em 8 s ainda derrubaria a sessao.\n\nProvas: `tests/e2e-tela-cheia-e-pausa.py` (**novo** — em Chromium de verdade: a tela cheia entra na JANELA com o card e o controle dentro, conferido por `document.fullscreenElement`; o destaque carrega o mesmo controle da grade, com o estado pintado, o botao de parar visivel e a CONTAGEM ANDANDO de segundo em segundo; a proporcao da grade e' a mediana (3x 16:9 + 1 retrato = 16:9, e a MENOR daria 0,56:1); um quadro 1x1 nao sobrescreve a proporcao conhecida; e a MEDICAO da imagem pintada com a proporcao errada x a do fluxo, com os numeros acima) e `tests/e2e-recarga-nao-derruba.py` (**novo** — o encerrar `pendente` nao fecha a sessao e responde a carencia, o batimento cancela o pedido, sem ninguem voltar o vigia fecha sozinho, a saida PEDIDA fecha na hora, e num Chromium de verdade um F5 com a transmissao no ar mantem a sessao aberta e o botao \"Parar transmissao\"), mais `tools/regressao-0130.py` (**33 provas**, tudo verde) e `python -m unittest discover -s tests` OK.\n",
    "0.16.0": (
        "**A imagem perde as faixas pretas laterais e fica MAIOR (sem cortar), e a entrada/cadastro deixam de aceitar origem de fora.**\n\nTeste do dono (24/11/2026, com print de 1908x841): \"deve haver outra forma de exibir as imagens sem ficar com essas faixas laterais pretas, sem cortar as imagens e sem deixar os videos pequenos na tela\".\n\n**1. A faixa preta lateral acaba — a celula passa a ter a FORMA do video.** Causa medida com sonda (4 cameras, menu recolhido, janela 1908x841): quem decide a largura da imagem e' a ALTURA da linha — a imagem entrava com 328 px de altura numa celula de 934 px de largura, e como o video e' 16:9 e a celula era 2,57:1 sobravam **176 px de preto de CADA lado (38% da celula)**. Foi efeito colateral da 0.15.0 (a grade passou a ocupar o palco inteiro e a sobra da largura virou tarja DENTRO de cada celula). Agora a celula mede exatamente a imagem: **zero faixa preta** dentro dela.\n\n**2. O card sai de baixo da imagem e vai SOBRE ela.** O card (nome, estado, botoes) ficava abaixo do video dentro da celula e comia **34 px de altura x 1,78 = 60 px de largura** — era a maior parte do \"video pequeno\". Agora ele flutua no rodape da imagem e a imagem usa a altura cheia da linha.\n\n**3. A grade CENTRALIZA o painel e a imagem cresce.** A sobra do palco deixou de ser tarja em cada celula e virou **margem simetrica do palco** — o conjunto parece um painel de video. Medido no print do dono: a imagem saiu de **582x328 para 643x362** (**+21,8%** de area) e a celula, que era 934x364, virou **646x364** (a forma do video); sem cortar. Nas outras duas janelas medidas o ganho foi +28,1% (1536x700) e +15,8% (1920x1080). Dito com todas as letras (nao se promete o que a geometria nao da'): com 4 videos 16:9 num palco 2,56:1, **nenhum** arranjo sem cortar usa 100% da largura — o que muda e' que o preto sai de dentro das celulas e a imagem fica maior.\n\n**4. A celula segue o FLUXO (nao so' 16:9).** A forma sai da proporcao real que cada camera publica — camera **4:3** e radar entram com a celula 4:3, sem tarja e sem esticar (provado no e2e com um video 4:3 de verdade). Sem metadado ainda (primeiro quadro), vale a ultima forma conhecida e ela e' corrigida quando o fluxo abre — nada de piscar.\n\n**5. Entrada e cadastro NAO aceitam mais origem de fora (correcao de seguranca).** Achado da suite: a lista que decide \"de quem e' a rota\" (roteamento) era a MESMA que decidia \"quem pode chamar pelo navegador\" (CORS) — e como `/api/entrar`, `/api/eu` e `/api/cameras` viraram rotas DESTA maquina (dono, 19/11: \"quem esta' sentado nesta maquina entra AQUI\"), elas passaram a responder `Access-Control-Allow-Origin` para a origem do lado terra e o pre-voo devolvia 204. Agora sao **duas listas**: a entrada/cadastro/licenca e' DESTA maquina (roteamento) e **nao** leva CORS; so' a tela \"Enviar video\" (o que a pagina do lado terra chama aqui) leva. Medido por `tests/test_captura_no_admin.py`, que voltou a provar as provas 04 e 05.\n\nProvas: `tests/e2e-imagem-sem-faixa-preta.py` (**novo** — 4 cameras em Chromium de verdade, nas 3 janelas (1908x841 = o print do dono, 1536x700, 1920x1080), exigindo faixa de cada lado <= 2 px, proporcao da imagem = a do video (+/-0,02), imagem MAIOR que a da versao anterior em cada janela, painel centrado e card sobre a imagem — mais um video **4:3** provando que a celula segue o fluxo — e, no fim, **DUAS cameras no ar** com o aviso do ultimo minuto nas duas e o \"Continuar conectado\" clicado nas DUAS: \"nao da pra clicar no botao para continuar conectado nas duas cameras\" era a queixa da 0.15.0), `tests/e2e-grade-usa-todo-o-palco-e-menu.py`, `tests/e2e-imagem-da-grade-nao-corta.py` e `tests/e2e-janela-ao-sair-da-tela.py` (ajustados: o card agora e' medido SOBRE a imagem, contrato trocado de proposito e justificado em `.hermes/plans/2026-11-24-imagem-sem-faixas-pretas.md`), `tests/test_captura_no_admin.py` e `tools/regressao-0130.py` (**31 provas**, tudo verde).\n"
    ),
    "0.15.0": (
        "**As telas param de encolher ao reconectar, a GRADE passa a usar a tela inteira (com botao de recolher o menu), o app de captura ganha um DASHBOARD de verdade, e a transmissao nao fica mais no ar com o bordo desligado.**\n\n"
        "Teste do dono (24/11/2026): \"continua diminuindo as telas quando reconecta principalmente, e as telas ainda estao pequenas, elas precisam ser mais responsivas e utilizar o maior espaco possivel\" · \"acabei de desinstalar o app de captura para instalar a v0.14.0 e a transmissao continua, como continua transmitindo se eu desinstalei o app?\" · \"voce chama aquilo que voce fez de dashboard? preciso de um dashboard real no pc de captura, so tem um monte de cards, mas eu quero um dashboard de verdade!\".\n\n"
        "**1. A imagem para de encolher (e o card vira UMA linha de 34 px).** Causa medida com sonda na tela: quem manda no tamanho da imagem e' a ALTURA, e quem comia a altura era o card do controle embaixo do video. Com o card em 2-3 linhas (rotulos longos) a imagem caia de 558x314 para ~460x230, e sobravam ~227 px de largura sem uso. \"Diminui ao reconectar\" era a MESMA raiz: o texto do botao mudava (\"Iniciar\" -> \"Reconectar\") -> o card mudava de altura -> a proxima medida encolhia a imagem. Agora o card tem ALTURA FIXA (34 px, sem quebra de linha) e os botoes sao ICONES (play, gravar, parar, reconectar, baixar 1 minuto, destaque) com o nome completo sempre em `title` e `aria-label` — o rotulo acessivel continua inteiro. O aviso do ultimo minuto saiu do fluxo do card e passou a FLUTUAR sobre a imagem.\n\n"
        "**2. A grade aproveita o espaco e e' responsiva de verdade.** O calculo do encaixe passou a descontar a altura do card e a usar a largura E a altura disponiveis; quem dispara o recalculo agora e' um `ResizeObserver` no palco (nao so' o `resize` da janela) — recolher a barra lateral, entrar em Destaque/tela cheia ou mudar o zoom tambem remede a imagem.\n\n"
        "**3. Bordo MUDO encerra a transmissao.** Era a pergunta do dono (\"como continua transmitindo se eu desinstalei o app?\"): medido no banco, a sessao seguia `no_ar` porque quem batia ponto era o NAVEGADOR do cliente, nao o computador de captura — o silencio do bordo so' virava saude \"atencao\". Agora ha' um relogio proprio do bordo: se o computador de captura nao da' sinal (nem saude, nem estado) por 180 s, as sessoes abertas daquela embarcacao sao ENCERRADAS no lado terra com o motivo \"o computador de captura a bordo ficou mudo\", e o cliente ve esse motivo na janela em vez de \"no ar agora\" com a imagem parada.\n\n"
        "**4. Dashboard de verdade no PC de captura.** A maquina passou a guardar um ponto de saude a cada 60 s (anel local de 2 dias, `saude/historico-da-saude.jsonl`) e a tela `/bordo` deixou de ser uma pilha de cards: agora desenha as CURVAS de CPU, memoria, disco e rede no tempo, com o valor de agora, minimo e maximo, a origem da serie declarada e o botao de **Modo TV** (tela grande, so' o painel — o monitor do PC de captura fica ligado o dia todo). Sem serie ainda, a tela DIZ \"sem serie\": nunca inventa curva. O endpoint e' `GET /api/bordo/serie`.\n\n"
        "**5. A grade usa TODO o espaco do palco.** Causa medida na tela do dono (1820x900): o espaco da grade tem ~1500 px e a grade usava 917 px — **39% de margem morta**, porque a celula estava travada na proporcao do video e a grade ficava centralizada. Agora a CELULA ocupa a area da grade (`repeat(N,1fr)` + altura cheia) e quem tem a forma do video e' a IMAGEM (o `<video>` e' `contain`): ela entra inteira, do MAIOR tamanho que cabe, sem cortar. Medido: a grade passou a usar **100%** do palco e a imagem do print do dono saiu de **460x259** para **635x357** por camera.\n\n"
        "**6. Botao para recolher o menu lateral.** O cabecalho ganhou o botao `«`/`»`: com ele a barra lateral vai a zero, o palco (e a grade) cresce na hora e a escolha e' lembrada na proxima abertura da tela. A barra recolhida sai do foco e do leitor de tela (`aria-hidden`/`inert`).\n\n"
        "**7. O lado terra sai limpo das cameras de teste.** \"Voce deixou aquele monte de cameras de teste novamente\" (dono, 24/11/2026): sairam as 4 cameras de PROVA (`vivo-*`) e a linha largada homonima de `AFN-USB` (sem nenhuma transmissao; a homonima e' instancia de aparelho diferente, o identificador vem do `@device_pnp_...`) — a embarcacao de bancada foi de **11 para 6 cameras**. A trilha de auditoria **nao** foi tocada (`transmissoes` 107 -> 107): \"o 'nada e' apagado' refere-se a logs de historico\". Backup consistente do banco antes, e o procedimento ficou em `tools/limpar-cameras-teste.py` (ensaio por padrao, `--aplicar` para valer).\n\n"
        "Provas: `tests/e2e-dashboard-de-verdade-e-card-compacto.py` (novo — mede o card e a caixa da imagem na camera parada e COM a sessao no ar e exige a MESMA medida, confere o aproveitamento da celula, redimensiona a janela para provar a responsividade, forca o bordo mudo no banco e espera o lado terra encerrar a sessao sozinho, e abre o `/bordo` conferindo as QUATRO curvas desenhadas), `tests/e2e-grade-usa-todo-o-palco-e-menu.py` (novo — 4 cameras em 1820x900: a grade usa 100% da largura util do palco, a imagem entra inteira e MAIOR que a da versao anterior, o menu recolhe devolvendo a largura e o estado volta depois de recarregar) mais `tools/regressao-0130.py` (30 provas, tudo verde).\n"
    ),
    "0.14.0": (
        "**O tamanho da imagem para de mudar, o botao \"Parar transmissao\" volta a funcionar, e o admin ganha dashboard e video ao vivo.**\n\n"
        "\n\n"
        "Teste do dono (24/11/2026): \"nao ficou legal o tamanho das imagens e outra coisa, elas ficam mudando o tamanho, diminuem nao entendo o porque. quando eu paro a transmissao e depois reinicio, o botao de parar transmissao fica desativado. preciso tambem que os videos sejam transmitidos no admin para eu acompanhar e monitorar. mais uma, preciso que o computador de captura envie tambem as informacoes de telemetria do computador com cpu, memoria, disco e rede, individual e global\" e \"inclua no plano um dashboard no app de captura, os cards estao horriveis, e tambem confirme se realmente as informacoes estao corretas, e preciso de um dashboard tambem pro admin para monitoramento\".\n\n"
        "\n\n"
        "**1. A imagem nao muda mais de tamanho.** Causa medida: a cada redesenho (a cada 5 s, quando algo muda) o `desenharVisualizar()` fazia `limpar(palco)` e RECRIAVA o `<video>`; no elemento novo o `proporcaoDaImagem()` saia cedo (`if (S.proporcao[c.id] === r) return;`) antes de gravar a proporcao, e a area voltava ao 16/9 do CSS — a imagem encolhia. Agora a janela que ja esta na tela e' APROVEITADA (o mesmo `<video>`, sem piscar), a proporcao ja conhecida entra no elemento na hora e so' ha redimensionamento quando a proporcao muda de verdade. A altura da grade passou a usar as LINHAS REAIS (`ceil(cameras/colunas)`): com 2 cameras a imagem usa a altura inteira, nao metade.\n\n"
        "\n\n"
        "**2. \"Parar transmissao\" sempre clicavel.** O botao e' desativado enquanto a requisicao corre, mas o MESMO botao voltava a ser usado na sessao seguinte e ninguem devolvia `disabled = false` (so' o \"Iniciar\" era religado). Agora cada passagem do `atualizarControle()` religa \"Parar transmissao\" e \"Gravar\".\n\n"
        "\n\n"
        "**3. Dashboard no app de captura.** O painel do bordo (`/bordo`) ganhou a primeira dobra com quatro numeros grandes — CPU, memoria, disco e rede — com o MESMO semaforo do lado terra (cpu 75/90, memoria 80/92, disco 88/95), a barra de cada um, a camada INDIVIDUAL por camera/encoder (kbps, fps, CPU e memoria do processo) e o que nao foi medido declarado com o motivo.\n\n"
        "\n\n"
        "**4. Dashboard do admin para monitoramento.** Tela nova \"Monitoramento (frota)\": cada embarcacao numa linha com o pior estado primeiro, CPU/memoria/disco/rede, quando o computador falou por ultimo, a camada individual por camera e o VIDEO AO VIVO — o mesmo player do cliente (WHEP/HLS), somente leitura: aqui nao se liga, nao se para e nao se grava.\n\n"
        "\n\n"
        "**5. Telemetria do computador de captura com REDE.** O retrato do bordo ganhou `rede` (bytes acumulados e taxa por interface + o total da maquina), `individual` (uma linha por camera/encoder) e `global` (a maquina inteira num lugar so'). O campo de memoria passou a ser rotulado como DISPONIVEL — e' o `available` do psutil, ~5 % maior que o \"livre\" do Windows (conferido na maquina: 11132 MB no painel contra 10592 MB no sistema; a porcentagem bate, 66,9 % contra 67 %).\n\n"
        "\n\n"
        "Provas: `tests/e2e-tamanho-fixo-dashboards-e-telemetria.py` (novo — mede a caixa da imagem duas vezes com um redesenho no meio e exige a MESMA medida, para e reinicia a transmissao conferindo o botao, abre os dois dashboards e o video ao vivo, e confere a telemetria) e `tools/regressao-0130.py` (28 provas).\n"
    ),
    "0.13.2": (
        "**A imagem da grade entra INTEIRA (sem corte e sem faixa preta) e o rodape baixou para uma linha.**\n\n"
        "\n\n"
        "Teste do dono (24/11/2026): \"agora com o card abaixo das imagens e a remoção das faixas pretas laterais, as imagens estão sendo cortadas\" e \"não cortar, diminua o rodapé para dar mais espaço na tela, mantenha apenas 'Lecsor - Todos os direitos reservados - 20##'. preciso das imagens inteiras\".\n\n"
        "\n\n"
        "**1. A causa medida.** A area da imagem era `1fr` da TELA (`.grade-vms{height:100%}` + `repeat(N,1fr)`): nunca tinha a proporcao da camera, e o `object-fit:cover` preenchia essa area **cortando** a sobra. Acabaram as faixas pretas porque a imagem passou a ser cortada — efeito colateral direto do D-D.\n\n"
        "\n\n"
        "**2. A correcao.** A area da imagem recebe a **proporcao REAL do video** (`videoWidth/videoHeight`, lida no `loadedmetadata`; 16:9 so' ate o metadado chegar) e a grade e' dimensionada por ela: `.img-cam` com `aspect-ratio`, `.janela video` com `object-fit:contain`, e a coluna calculada para o conjunto (imagem + card em N linhas) caber na altura disponivel. A imagem entra inteira, sem corte e sem barra; a sobra da tela vira margem. Vale na grade e no destaque; recalcula ao redimensionar a janela.\n\n"
        "\n\n"
        "**3. Rodape baixo, so' a linha de direitos.** O `<footer>` perdeu \"Ver todos os alertas\", \"Relatorios\" e \"Limpar selecao\" e ficou com uma linha centrada: \"Lecsor - Todos os direitos reservados - <ano>\" (o ano vem do relogio da maquina). A altura caiu de ~50 px para ~22 px — o espaco vai para as imagens. As telas de alertas e relatorios continuam na lateral esquerda.\n\n"
        "\n\n"
        "Provas: `tests/e2e-imagem-da-grade-nao-corta.py` (novo, com DOIS videos gerados dentro do teste — 640x480 e 1280x720: a area da imagem acompanha a camera em 1,333 e 1,778 e o quadro entra inteiro) e `tools/regressao-0130.py` (27 provas).\n"
    ),
    "0.13.1": (
        "**A transmissao so' vive enquanto a tela do video esta' aberta: sair e voltar em ate' 60 s nao derruba a sessao — e a grade ficou com a imagem limpa.**\n\n"
        "\n\n"
        "Teste do dono (24/11/2026): \"eu saio da pagina de transmissao ao vivo, retorno a ela e a transmissao continua ativa, tem algum espaco de tempo para encerrar a transmissao? seria bom determinarmos, talvez, 60s apos sairmos da pagina, encerrar a transmissao, assim, se o cliente precisar ver outras coisas enquanto acompanha o video do radar, ele nao tem que ficar reconectando\".\n\n"
        "\n\n"
        "**1. A janela de 60 s ao sair da tela.** O \"estou aqui\" (batimento) passou a valer SO' na tela das cameras: sair para outra tela e VOLTAR dentro de 60 s mantem a sessao de pe (nada de reconectar, o botao segue em \"Parar transmissao\"); passando de 60 s fora, o lado terra encerra a sessao sozinho e o bordo para. Medido na tela: 13 s fora NAO adiantam o batimento; a volta bate o batimento na hora; e o vigia do lado terra encerra a sessao sem ninguem clicar (motivo no historico: \"voce saiu da tela ao vivo por mais de 60 s\").\n\n"
        "\n\n"
        "**2. A grade: card ABAIXO da imagem e imagem ocupando o espaco.** O nome/estado da camera e os botoes (energia, baixar 1 minuto, destaque, iniciar/gravar/parar) sairam de cima da imagem e foram para um CARTAO logo abaixo dela; sobre o video ficaram so' a marca d'agua e as caixas da IA. A imagem passou a entrar com `object-fit: cover`, ocupando toda a area e acabando com as faixas pretas laterais.\n\n"
        "\n\n"
        "**3. Limpeza das cameras de teste.** Saem 23 cameras de campanha das duas embarcacoes de teste (\"Bancada de testes\" e \"PSV Exemplo (demo)\") e o cliente \"Armador E2E (criado pela tela)\". A TRILHA DE AUDITORIA fica (transmissoes e ordens do bordo nao sao tocadas). Continuam na bancada os 2 dispositivos reais do PC de captura, que estavam no ar — a varredura do bordo os recadastra sozinha, por desenho.\n"
    ),
    "0.13.0": (
        "**A transmissao ao vivo passa a ser do CLIENTE: contagem, aviso, reconectar e gravar — e a "
        "saude do bordo na area unica.**\n\n"
        "Teste do dono na tela do cliente (24/11/2026): \"sai da tela de transmissao ao vivo do cliente e "
        "continuou transmitindo, isso precisa ser flag para o app de captura enxergar e parar a transmissao, "
        "a nao ser que esteja sendo visualizado em outro computador\" · \"nao tenho nenhuma informacao de "
        "saude e desempenho\" · \"precisa de um timer de contagem regressiva... e antes de desconectar, uma "
        "mensagem perguntando se quer continuar conectado... aí aparece um botao 'reconectar'... e precisa "
        "tambem de um botao para iniciar gravacao\".\n\n"
        "**1. A transmissao se sustenta em quem ASSISTE (D3).** Decisao do dono: \"nao tem ligar agora do "
        "admin, so' quem visualiza e' o cliente\". O botao \"ligar agora\" do admin **saiu**. Agora quem "
        "sustenta a flag de transmissao de cada camera e' a **sessao de quem esta' assistindo** — o lado "
        "terra manda `desejo=ligar` enquanto ha' pelo menos um espectador com batimento vivo, e vira "
        "`desejo=parar` quando o ultimo sai. O admin so' mantem o **desligar** (stand-by da operacao), que "
        "**vence** o pedido do cliente. Antes o `manual='ligar'` do admin vencia o \"ninguem assistindo\" e "
        "a transmissao seguia sozinha (medido: 2 cameras com `manual='ligar'` e `transmissoes` vazio).\n\n"
        "**2. Contagem, aviso de 1 minuto e \"Reconectar\" (D1/D2).** Na **grade** do cliente (a tela que "
        "ele realmente usa, \"Transmissoes ao vivo\"), cada camera passou a mostrar um **contador mm:ss** do "
        "tempo restante da sessao, os botoes **gravar/parar** e, no **ultimo minuto**, o aviso *\"quer "
        "continuar conectado?\"* com o botao **Continuar**. \"Silencio\" (D2) = o cliente nao responde ao "
        "aviso => **desliga**; para continuar ele clica em **Continuar** (rota `POST "
        "/api/transmissao/<id>/continuar`, que renova a **mesma janela**, nunca tempo infinito). Depois do "
        "fim aparece **Reconectar** (antes \"reconectar\" nao existia em lugar nenhum).\n\n"
        "**3. Gravar no lado terra, so' o que chegou (D4).** O cliente ganhou o botao **Gravar**, na grade: "
        "grava o video que **ja' chegou** em terra (`-c copy`, sem reencodar), nunca uma gravacao nova "
        "pedida ao barco. Enquanto grava, o corte por tempo nao acontece; ao parar, o **mp4 fica no disco**. "
        "Medido: 262 KB gravados de um fluxo real de bancada.\n\n"
        "**4. Saude e desempenho na area unica.** O cartao da embarcacao passou a mostrar CPU, memoria, "
        "disco, ffmpeg, mediamtx, dispositivos e a ultima varredura, com **semaforo e os motivos** (limiar e "
        "\"o que fazer\") — era o \"nao tenho nenhuma informacao de saude e desempenho\" do dono. O cartao "
        "da camera ganhou \"no ar desde <hh:mm>\" e \"N espectador(es)\".\n\n"
        "**5. Seguranca (P0 medido e corrigido).** `GET /api/empresas` devolvia a **chave da licenca "
        "inteira** e o papel `observador` (Petrobras) enxergava a rota. Agora ela sai so' nos **ultimos 4** "
        "digitos; a chave completa fica so' na rota de licencas, do admin. **O `versao_app` tambem parou de "
        "subir vazio**: o pacote agora escreve `LECSOR_VERSAO_APP` no boot (`desktop/main.js`) e o retrato "
        "de saude le' essa variavel.\n\n"
        "**Provas:** `tools/regressao-0130.py` (**25 provas, tudo verde**) — as novas "
        "`tests/e2e-flag-de-audiencia.py` (a flag so' na sessao de quem assiste), "
        "`tests/e2e-saude-e-desempenho-na-area.py` (saude + a chave nunca inteira), "
        "`tests/e2e-contagem-aviso-e-reconectar.py` (contagem, aviso e reconectar na grade) e "
        "`tests/e2e-gravacao-no-cliente.py` (gravacao de ponta a ponta com mediamtx + ffmpeg reais), "
        "mais toda a suite do `regressao-0100`; `node --check` e `py_compile`.\n"
    ),
    "0.12.0": (
        "**O admin ficou numa area so: empresa -> embarcacao -> cameras.**\n\n"
        "Pedido do dono (23/11/2026): \"preciso poder configurar cada cliente/embarcacao/cameras de forma "
        "unificada e simples, hoje eu tenho muitas paginas: clientes/embarcacoes/cameras/licencas/producao/"
        "tempo real/enviar videos/usuarios/configuracoes do bordo, tudo isso poderia ser uma area so, de "
        "configuracao por cliente e de embarcacoes pra baixo tudo vinculado ao cliente... e esta ainda "
        "truncado, parece que esta tudo funcionando do lado da captura mas as cameras nao aparecem do lado "
        "do admin, pelo menos nao com o nome que a varredura pegou, e nao consigo configurar e ligar as "
        "cameras\". E o fluxo que ele mandou seguir: \"o correto e' eu criar a empresa caso ainda nao tenha "
        "sido criada, depois embarcacao vinculada a aquela empresa, gero a chave na embarcacao, na "
        "embarcacao aparecem as cameras encontradas na varredura, configuro as cameras e a captura pega as "
        "informacoes e replica no app de captura, inclusive os nomes das cameras\".\n\n"
        "**Uma tela so'** (`Empresas e configuracao`, agora a tela de entrada do admin): o cliente na "
        "raiz, as embarcacoes vinculadas a ele e, em cada embarcacao, as cameras. As paginas antigas viram "
        "abas DENTRO do cliente/embarcacao — \"tempo real, producao e cameras e' a mesma coisa, nao precisa "
        "dividir\" — e continuam alcancaveis pelo grupo **Avancado (telas antigas)**: nada de link salvo "
        "quebrando.\n\n"
        "**Cada camera e' um CARTAO** (fim da tabela de 12 colunas que cortava a informacao): o nome num "
        "campo, o estado (no ar / fora do ar / desativada, e \"achada pela varredura\"), a situacao que o "
        "bordo conta, o que foi publicado e o que o bordo aplicou, mais as acoes na mesma linha — "
        "**ligar/desligar**, **ativar/desativar**, **a qualidade de envio** (1500 a 300 kbps) e o "
        "**salvar nome**.\n\n"
        "**O nome da camera desce para o PC de captura** (pedido literal do dono: \"a captura pega as "
        "informacoes e replica no app de captura, inclusive os nomes das cameras\"): o nome que o admin "
        "escreve em terra vira a chave `rotulo` da configuracao, o bordo aplica no cadastro local dele e a "
        "varredura **passa a respeitar o nome escolhido** em vez de reescreve-lo com o nome do dispositivo "
        "a cada rodada.\n\n"
        "**A chave da licenca se gera na embarcacao** (\"gero a chave na embarcacao\"), no mesmo lugar de "
        "tudo: gerar, ver/copiar, prazo e numero de PCs, revogar e reativar — e ela continua aparecendo "
        "depois de qualquer redesenho da tela.\n\n"
        "**Provas:** `tests/e2e-admin-unificado.py` (tela nova de ponta a ponta: a area unica abre na "
        "empresa, as cameras da varredura aparecem COM o nome do dispositivo sem truncar, dar nome publica "
        "o `rotulo`, a qualidade publica o `alvo_kbps`, ativar/desativar muda o estado, ligar/desligar "
        "responde na tela, a chave se gera na embarcacao e as telas antigas seguem alcancaveis), "
        "`tests/e2e-varredura-do-bordo.py` (novo bloco 4b: o nome do admin sobrevive a varredura), "
        "`tools/regressao-0100.py` (21 provas, tudo verde), `node --check` e `py_compile`.\n"
    ),
    "0.11.1": (
        "**O painel do bordo mostra o que esta acontecendo: os processos e o desempenho medido.**\n\n"
        "Pedido do dono (23/11/2026): \"apos a validacao da chave de acesso, o app inicia a sua "
        "configuracao local autonoma e exibe as informacoes de saude e desempenho na tela, bem como os "
        "processos em andamento, como stremming, salvando video, ambos, etc...\"\n\n"
        "A tela do PC de captura (`/bordo`, sem login) ganhou tres cartoes:\n\n"
        "**1. O que esta acontecendo agora** — processo por fluxo, com o nome certo: "
        "**transmitindo**, **gravando** (a gravacao full-time do radar no HD local), "
        "**transmitindo e gravando** (o \"ambos\" que o dono pediu) ou **parado**, com o desde-quando, a "
        "origem da ordem (cliente/admin) e o HD (blocos, espaco ocupado e livre, tamanho do bloco).\n\n"
        "**2. Saude e desempenho** — a saude que ja' existia (CPU, memoria, disco, erros) mais o "
        "**desempenho medido pelo proprio bordo**: entrada x saida em kbps por fluxo com a **reducao de "
        "banda** em %, MB enviados e segundos no ar no ultimo minuto fechado, e o link (RTT, capacidade, "
        "taxa de envio, perda, buffer e latencia de internet). O que NAO tem fonte nao vira numero: o "
        "**fps nao e' medido nesta maquina e a tela diz \"sem medida\"** — nada e' inventado.\n\n"
        "**3. Como esta maquina se configurou sozinha** — a configuracao local autonoma, na ordem da "
        "vida real: chave de licenca, varredura das cameras e entradas de video locais, publicacao do "
        "cadastro ao lado terra e o olhar para as flags do lado terra (com quando e o que deu).\n\n"
        "O link custa uma medicao de verdade (ping + mediamtx, ~5 s): ele e' guardado em cache curto e o "
        "campo diz ha' quanto tempo foi lido, em vez de repetir a medicao a cada 10 s.\n\n"
        "**Provas:** `tests/test-bordo-sem-login-e-autonomo.py` (55 provas, novo bloco 2b: \"transmitindo e "
        "gravando\" para o radar que grava, \"transmitindo\" para a camera com ordem do cliente, a gravacao "
        "com os blocos do HD, o desempenho 4512 -> 812 kbps com 82 % de reducao lido do banco, a "
        "\"sem medida\" com motivo quando nao ha medicao — e o cache do link), "
        "`tools/regressao-0100.py` (20 provas), `node --check` e `py_compile`.\n"
    ),
    "0.11.0": (
        "**O PC de captura ficou autonomo: chave, painel do bordo e mais nada.**\n\n"
        "Relato do dono (23/11/2026): \"inseri a chave de acesso no app no computador de captura, depois me "
        "pede email e senha, mas nao aceita nenhum que ja tenho. apos o reconhecimento da licenca nao deveria "
        "precisar fazer mais nada no app de captura, ele ja deveria fazer a varredura e enviar as informacoes\" "
        "e, depois, \"no pc de captura ninguem precisa abrir nada, tudo deve ser feito no admin e cliente, o "
        "app de captura deve ser autonomo, faz as varreduras locais e fica verificando as flags de terra e "
        "enviando as respostas e fazendo as atuacoes\".\n\n"
        "**1. O que estava errado.** Ativada a chave, o app mandava a pessoa para o LOGIN (a mesma tela do "
        "lado terra) e o login do servidor local daquela maquina so' aceita quem esta' no cadastro DELA: "
        "aparecia \"esta conta nao esta cadastrada nesta instalacao\" — dava \"nao aceita nenhum que ja tenho\". "
        "O desenho do produto nunca foi pedir login no PC de captura.\n\n"
        "**2. Como fica agora.** Com a chave digitada, a entrada do app passa a ser o **Painel do Bordo** "
        "(`/bordo`, servido pelo proprio bordo, **sem login**): embarcacao e empresa da chave, situacao da "
        "licenca, **token do instalador presente/ausente**, lado terra, **agente de ordens no ar** (com a "
        "ultima batida), o que esta' no ar por ordem do cliente/admin, a **ultima varredura** (o que viu, o "
        "que cadastrou, o que publicou e o que falhou) e a **saude do bordo**. Ela so' INFORMA: quem "
        "configura e' o admin, no painel do lado terra, e quem assiste e' o cliente, na tela dele. Nada de "
        "segredo aparece: a chave vai so' nos ultimos 4 digitos e o token como presente/ausente.\n\n"
        "**3. O bordo publica sozinho.** A varredura local ja roda sozinha (no boot e de tempo em tempo) e "
        "o cadastro das cameras e' publicado ao lado terra com reenvio enquanto falhar — nao depende de "
        "ninguem clicar nada. Depois de digitar a chave, a propria tela da chave pede a varredura e vai para "
        "o painel: a camera desta maquina entra cadastrada e publicada.\n\n"
        "**4. O agente de ordens nao morre mais sem chave.** A embarcacao vem da LICENCA (o token continua "
        "vindo no instalador): sem chave ele **espera** a chave em vez de sair, e o pacote de captura sobe "
        "junto com o Windows. A varredura sem sessao vale SO' para a propria maquina (loopback + o app "
        "declarando a captura + licenca) — de fora nada mudou, e o cliente continua sem poder varrer.\n\n"
        "**Provas:** `tests/test-bordo-sem-login-e-autonomo.py` (novo: painel sem login, estado sem segredo, "
        "sinal do agente, o que esta' no ar, varredura so' pela propria maquina), "
        "`tests/e2e-app-ativado-por-licenca.py` (depois da chave o app segue para o painel, nao para o login), "
        "`tests/e2e-varredura-do-bordo.py`, `tests/test-config-endereco.py`, "
        "`tests/test-app-unico-por-papel.py`, `tests/test_captura_liberada_no_app.py`, "
        "`tests/test-instalador-plug-and-play.py`, `tests/test-agente-de-ordens.py` e "
        "`tools/regressao-0100.py` (20 provas).\n"
    ),
    "0.10.1": (
        "**Os consertos que os testes de ponta a ponta acharam DENTRO do produto.**\n\n"
        "Depois dos testes de ponta a ponta da bancada (10 jornadas, J1 a J10, com acao de usuario de verdade e "
        "medida de verdade), dois defeitos de verdade do produto apareceram e vao corrigidos nesta versao — os "
        "dois estavam no caminho do PC de captura.\n\n"
        "**1. O alvo de banda que o admin publica chegava ao ffmpeg com a unidade errada.** O campo `alvo` das "
        "cameras e' o valor cru do `-b:v` e a convencao do produto e' `NNNNk` (milhares de bits): o admin "
        "publicava `800` e o **ffmpeg lia 800 BITS/s** (0,0 Mbps, 0 quadro) — a camera nao subia. Agora o valor "
        "publicado carrega o `k` e a validacao aceita `800` ou `800k` (os testes antigos exigiam \"800\" e deixavam "
        "o defeito passar; foram atualizados).\n\n"
        "**2. A licenca revogada nao cortava sozinha.** O agente de ordens so' conferia a licenca quando alguem "
        "abria a tela no barco, e a memoria do agente dizia que a camera estava no ar — revogar nao cortava. "
        "Agora o agente confere a licenca **antes** de ler a flag, a pergunta \"esta ligado?\" e' respondida pelo "
        "**estado gravado** (nao pela memoria) e a unica porta que liga camera (`ligar_camera`) respeita "
        "`licenca_bloqueia_captura()` — o pedido do cliente nao desfaz o que a licenca proibiu. **Medido: a "
        "transmissao morre em 2,3 s**, sem ninguem abrir tela no barco.\n\n"
        "**Correcao que entrou junto:** a trilha de auditoria escrevia a mesma linha `captura_parada_por_licenca` "
        "8 vezes em ~40 s (o corte era auditado a cada ciclo). Agora a auditoria e' escrita **na transicao** — a "
        "trilha registra o que aconteceu.\n\n"
        "**Provas:** `python tools/smoke/ponta-a-ponta.py --jornadas 7,8,9,10` (J8 = o admin manda e o bordo "
        "obedece; J10 = a licenca revogada corta o que esta' no ar) e `--jornadas 9` (o defeito de verdade no "
        "bordo e a saude que o denuncia), `tools/regressao-smoke.py --completo` (J1 a J10), "
        "`tests/test-licenca-do-bordo.py`, `tools/regressao-0100.py` (20 provas) e os e2e "
        "`tests/e2e-admin-configura-e-bordo-obedece.py` / `tests/e2e-config-do-bordo-vinda-de-terra.py` "
        "(atualizados para o `800k`).\n"
    ),
    "0.10.0": (
        "**A chave de licenca: instalar o app no PC de captura e digitar a chave.**\n\n"
        "Pedido do dono (19/11/2026): \"quero apenas instalar o app no computador de captura, inserir a chave "
        "da licenca e assim fazer a conexao com a empresa e embarcacao cadastradas, e a licenca pode ser "
        "configuravel por tempo ou indeterminado\".\n\n"
        "**1. Como fica no campo (PC de captura novo):** instale o app. Na primeira abertura ele nao pede "
        "login: abre a **tela da chave**. Digite a chave `XXXX-XXXX-XXXX-XXXX` (pode digitar em minusculas e "
        "sem os tracos — o campo arruma) e o app passa a ser daquele **barco**, daquela **empresa**. Da "
        "segunda abertura em diante ele abre normal, com as cameras do barco. Nao existe mais build por "
        "barco nem arquivo de ambiente para o cliente editar.\n"
        "**2. Quem gera a chave:** o **admin**, no painel, na tela **Licencas**: escolhe a embarcacao, se a "
        "licenca vale por **tempo** ou e' **indeterminada**, e quantos PCs a licenca cobre. Ele **ve e copia "
        "a chave inteira** quantas vezes quiser (a chave fica guardada para isso).\n"
        "**3. O que a licenca decide (e o que NAO decide):** ela decide **o barco**. O **token de ingestao "
        "continua unico**, como sempre foi — a licenca nao substitui o token.\n"
        "**4. Revogar/reemitir:** revogar corta na hora o que aquele PC estava transmitindo; \"gerar outra "
        "chave\" troca a chave e a antiga morre.\n"
        "**5. Sem internet:** o PC de captura **continua capturando, gravando e enviando** normalmente. Nao "
        "existe prazo de tolerancia nem corte por falta de rede: o corte e' so' por **vencimento** ou "
        "**revogacao**, e so' acontece quando o PC consegue falar com o lado terra.\n"
        "**6. Quem pode ver a chave:** so' o **admin**. Operador/cliente nem veem a tela (a rota responde "
        "que e' so' do admin). A chave **nunca** vai para log nem para a trilha de auditoria — a auditoria "
        "guarda so' a **pegada** (um resumo) da chave, para se saber o que aconteceu sem guardar o segredo.\n"
        "**7. Instalacao antiga continua funcionando:** quem ja' tem o `ambiente.json` do barco segue "
        "capturando sem ativar nada (nada e' apagado).\n\n"
        "**Correcao que entrou junto:** o agente de ordens escreve o estado dele em `<raiz>\\ordens\\` e o "
        "modulo de saude do bordo lia `<raiz>\\ground\\agente-vivo.json` — a tela \"Saude do bordo\" do admin "
        "podia dizer \"o agente nunca escreveu o estado\" numa maquina que estava trabalhando. Agora a saude "
        "pergunta o caminho ao proprio agente.\n\n"
        "**Provas:** `tests/test-licenca-de-ativacao.py` (lado terra por HTTP), `tests/test-licenca-do-bordo.py` "
        "(2 servidores: digitar a chave e o vinculo), `tests/test-licenca-nao-vaza.py` (a chave nao aparece em "
        "log nem na auditoria), `tests/test-licenca-isola-embarcacao.py` (a licenca do barco A nao enxerga "
        "camera do barco B), `tests/e2e-licenca-no-admin.py` e `tests/e2e-app-ativado-por-licenca.py` (telas "
        "em Chromium de verdade), `tests/prova-viva-licenca-no-terra.py` (roda na VPS, contra o lado terra de "
        "producao) e a regressao `tools/regressao-0100.py`.\n"
    ),
    "0.9.1": (
        "**Correcao que faz o aplicativo ABRIR.**\n\n"
        "* **O que estava acontecendo:** o aplicativo instalado nao abria janela nenhuma. Causa medida no "
        "proprio pacote: em `desktop/servidor.js`, a funcao que sobe o servidor local devolvia o campo `hd` "
        "(gravacao continua do radar) mas declarava essa variavel **dentro** do `try` — "
        "`ReferenceError: hd is not defined` em **toda** chamada. Como o unico chamador e' o arranque do "
        "aplicativo (`app.whenReady()`), a promessa quebrava e nada depois dela rodava: sem servidor local, "
        "sem janela. `node --check` nao pega (erro de escopo, nao de sintaxe) e a prova de tela em modo de "
        "bancada tambem nao pegava, porque nela o servidor local nao e' ligado.\n"
        "* **Conserto:** `hd` passou a nascer fora do `try`, junto de `analise` e `ordens`.\n"
        "* **Prova nova (que pega o defeito e nao volta):** `tests/test-app-sobe-o-servidor-local.py` monta um "
        "repositorio minimo, chama `subir()` como o pacote chama (servidor local LIGADO) e exige `ok` + o "
        "campo `hd`; a mesma prova roda contra a versao anterior (do git) e tem de falhar com "
        "`hd is not defined` — e' o que ela mostra.\n"
        "* **Como conferir no campo:** o app instalado abre a tela de entrada; o log do servidor local fica em "
        "`<pasta do servidor>\\desktop-logs\\` ao lado dos processos que o app sobe.\n"),
    "0.9.0": (
        "**Os 4 escopos de cliente, o app de captura que se cadastra sozinho e a visão da Petrobras.**\n\n"
        "**1. Os 4 tipos de cliente** (dono, 19/11/2026): (1) uma embarcação da empresa, (2) algumas, "
        "(3) a empresa inteira, (4) **Petrobras — todas as embarcações de todas as empresas**. Os tipos 1 e 2 "
        "viraram **vínculo explícito** (`usuario_embarcacoes`, concedido pelo **admin**, com trilha na "
        "auditoria); sem vínculo nenhum o cliente continua vendo **todas as da própria empresa** (tipo 3, como "
        "sempre foi — nada muda para quem já usava). O tipo 4 é o papel **`observador`**: vê o **radar de óleo "
        "de todas as embarcações, de todas as empresas**, e **mais nada** — sem câmera comum, sem analytics, "
        "sem botão de operação.\n\n"
        "**2. O app do PC de captura se cadastra sozinho.** No boot — e de tempo em tempo — o app **varre os "
        "dispositivos desta máquina** e cadastra o que achar, publicando em terra. **Nenhum endereço de câmera "
        "e nenhuma credencial passam por essa tela**: o id nasce do **seletor único do dispositivo** "
        "(`@device_pnp_…`), que é o que separa **duas câmeras de mesmo nome**; a **placa de captura de radar "
        "(HDMI) não é cadastrada como câmera** (radar é por embarcação). Terra **não manda lista de câmeras** — "
        "terra só **decide depois** (`transmitir`, alvo, teto). A varredura **não sobrescreve** o que o admin "
        "configurou.\n\n"
        "**3. O cadastro do bordo não se perde** (defeito medido em 19/11/2026 e corrigido). Antes, "
        "`POST /api/cameras` na máquina de captura era **encaminhado para terra** e o bordo ficava sem a câmera "
        "que ele mesmo cadastrou. Agora o cadastro feito **na própria máquina** nasce **no banco do bordo** "
        "(com o dispositivo em `config_local`) e é **publicado**; a sessão do usuário de captura é atendida "
        "**no bordo** (`/api/entrar`, `/api/eu`, `/api/sair` passaram a ser locais).\n\n"
        "**4. Saúde do bordo** (vem da 0.8.0, agora com a varredura no retrato): o bordo envia CPU, memória, "
        "disco, dispositivos e **o que a varredura achou** — sempre **sem segredo**; o admin vê semáforo por "
        "embarcação e **bordo mudo é tratado como problema**, com retenção de 30 dias auditada.\n\n"
        "**5. Configuração do bordo** (0.8.0): terra **publica** o desejo (`config_bordo`, com versão), o bordo "
        "**olha**, aplica só a diferença e **confirma**; aplicar é **local** (`POST /api/config/aplicar`).\n\n"
        "* **Provas:** `tests/test-escopos-de-acesso.py` (matriz HTTP dos 4 tipos + conceder/revogar), "
        "`tests/e2e-escopo-no-admin.py` (tela do admin), `tests/e2e-varredura-do-bordo.py` (duas APIs reais, "
        "duas câmeras de MESMO NOME e uma placa de radar), `tests/test-fluxo-no-lado-terra.py` (a câmera nasce "
        "no bordo **e** em terra) e `tests/e2e-observador-do-radar.py` (Chromium: o observador vê o radar de "
        "duas empresas e **nenhuma** câmera). Regressão curada: `tools/regressao-090.py`, todos rc=0.\n"),
    "0.8.0": (
        "**A configuração do bordo vem de terra e a saúde do bordo chega ao admin.**\n\n"
        "* **Um app só, a tela vem da role**: o usuário de captura cadastra as câmeras desta máquina; a "
        "qualidade, o tempo de transmissão e o que transmitir são publicados pelo **administrador**.\n"
        "* **Config publicada, bordo obedece**: terra publica (`config_bordo` com versão), o bordo olha, aplica "
        "só a diferença e confirma; a recusa volta com motivo.\n"
        "* **Saúde do bordo**: CPU, memória, disco, dispositivos e erros das últimas 24 h (sem segredo), com "
        "semáforo no painel do admin; **bordo mudo = problema**; retenção de 30 dias auditada.\n"
        "* **Cadastro espelhado**: o cadastro da câmera também vai para o banco do dono (Supabase) pelo lado "
        "terra; `ip` e `porta` **nunca** sobem.\n"
        "* **Provas:** `tests/e2e-cadastro-de-camera-salva-no-banco.py`, "
        "`tests/e2e-config-do-bordo-vinda-de-terra.py`, `tests/test-papeis-de-config.py`, "
        "`tests/e2e-tela-do-captura-so-cadastra.py`, `tests/e2e-admin-configura-e-bordo-obedece.py`, "
        "`tests/e2e-saude-do-bordo-no-admin.py`.\n"),
    "0.7.0": (
        "**Terra publica o desejo, o PC de captura obedece — e o radar de óleo fica gravado o tempo "
        "todo, no disco do barco.**\n\n"
        "Arquitetura (dono, 19/11/2026): *o computador de captura a bordo não tem porta aberta para "
        "receber comandos; a única certeza é que ele pode enviar*. A informação **não sai de terra para o "
        "bordo**: **terra publica o desejo** por câmera (com versão), o **bordo olha** e age só na "
        "diferença, e o **bordo conta o real** — é assim que a tela sabe que a câmera subiu.\n\n"
        "* **Para quando não há ninguém assistindo** — e só então. Fechou a tela, desligou o computador "
        "ou caiu a conexão, o lado terra derruba **só a sessão de quem saiu**; se outro cliente está "
        "acompanhando, a transmissão continua para ele (batimento de 60 s, sem-resposta de 30 s).\n"
        "* **HD do radar de óleo gravando full time** no PC de captura: as imagens que chegam **por HDMI, "
        "como qualquer câmera**, são comprimidas e fatiadas em **blocos de 60 s** com índice por horário. "
        "O disco funciona como **anel**: quando o espaço acaba, o bloco **mais antigo** é sobreposto e a "
        "gravação **nunca para** (cada sobreposição entra na trilha). Nasce **desligada** e quem liga é o "
        "administrador (`LECSOR_GRAVACAO_CONTINUA=1` + o dispositivo HDMI + a pasta do HD).\n"
        "* **O cliente acessa as imagens quando quiser:** tela nova **Radar de óleo (HD)** no cliente, com "
        "**filtro por data e hora**; ele escolhe o trecho e clica **PEDIR** — o PC de captura lê o pedido "
        "e **envia** o bloco (pedido que já saiu do anel volta como *indisponível*), e o cliente **BAIXA** "
        "em terra. Nenhum vídeo sobe sem pedido.\n"
        "* **Todas as configurações são do administrador.** Com o tempo de transmissão fixado pelo admin, "
        "o cliente não escolhe mais nada (a caixa sai da tela e a API recusa a mudança).\n"
        "* **Provas:** flag ligando a câmera de verdade em repouso; dois clientes com um saindo; gravação "
        "em blocos com o anel sobrepondo o mais antigo; o cliente pedindo e baixando o trecho; e a TELA do "
        "cliente aberta de verdade (Chromium) mostrando, filtrando, pedindo e baixando.\n"),
    "0.6.10": (
        "**As câmeras ficam em stand-by no PC de captura e só transmitem quando o cliente ativa.**\n\n"
        "Arquitetura (dono, 19/11/2026): o sinal de cada câmera é **dividido por um split** e chega à nossa "
        "máquina de captura; o DVR grava por conta dele. O nosso sistema **não abre câmera em repouso** — "
        "abre quando o cliente ativa o canal no painel e fecha quando ele sai.\n\n"
        "* **A captura nunca mais é pedida na máquina errada.** O clique de ligar/desligar é da **máquina de "
        "captura**: no lado terra ele virou **ordem** (`iniciar`/`parar`) que o bordo obedece (o agente de "
        "ordens agora sobe junto com o servidor local, com reinício automático). Antes o clique era "
        "encaminhado ao lado terra, que tentava abrir a câmera com `-f dshow` no Linux e devolvia "
        "`ffmpeg saiu com codigo 234: Error opening input files: Invalid argument` / "
        "`Unknown input format: 'dshow'` (medido na base do lado terra: `ingestoes` 186-191).\n"
        "* **Stand-by de verdade:** em repouso **nenhum ffmpeg roda** e o dispositivo de captura não fica "
        "aberto. A tela do admin mostra, por câmera, **pronta (stand-by)**, **no ar**, **em uso por outro "
        "envio** ou **AUSENTE (cabo/USB fora do split)** — sempre dita pela máquina de captura; onde a "
        "captura não é dela, a tela diz \"a bordo (quem informa é o PC de captura)\" em vez de mentir.\n"
        "* **Motivo que aponta a máquina certa:** quando o log traz `Unknown input format: 'dshow'`, a tela "
        "diz que aquela máquina não é a de captura e que a captura abre no PC de bordo.\n\n"
        "* **Provas novas:** `tests/test-lado-terra-nao-captura.py` (lado terra manda ordem, **nenhum "
        "ffmpeg** e **nenhum envio** nascem nele; o bordo continua capturando) · "
        "`tests/test-stand-by-do-captura.py` (por **processo**: zero ffmpeg em stand-by, um depois de "
        "ativar, zero depois de sair — com a câmera de verdade desta máquina e mediamtx de teste) · "
        "`tests/test-motivo-maquina-errada.py` (tradução do erro medido, sem mexer no que já funcionava).\n"
    ),
    "0.6.9": (
        "**A linha de cima da grade do cliente não é mais cortada.**\n\n"
        "Queixa: \"na tela do cliente está cortando as câmeras de cima\" (print de 18/11/2026, grade de 3 "
        "com a moldura azul da primeira fileira sem o traço de cima). Medido em navegador de verdade "
        "(1920x1080, 6 câmeras, grade 3): o `padding` do palco era `0px 18px 8px` — **zero em cima**, 8 px "
        "embaixo — então a primeira fileira de janelas ficava com **0,4 px** de folga sob o cabeçalho e o "
        "`overflow:hidden` do palco comia **2,6 px** do contorno da janela selecionada (`outline:2px` + "
        "`outline-offset:1px`, que ficam 3 px acima do topo da janela). Não era o vídeo cortado: o "
        "`<video>` usa `object-fit:contain`.\n\n"
        "* **Correção:** o palco passa a ter a mesma folga em cima e embaixo (`padding:12px 18px 8px`) — e "
        "o mesmo na tela do telefone (12px no topo). A folga fica comentada no CSS para não ser removida "
        "depois: sem ela o contorno da seleção volta a ser decapitado.\n"
        "* **Prova nova:** `tests/test-grade-do-cliente-nao-corta-o-topo.py` mede o `padding-top` do palco, "
        "a folga da primeira fileira e o contorno da janela **inteiro** dentro do palco, em 3 tamanhos de "
        "janela (1920x1080, 1536x780, 1366x768) x grades 2x2, 3x3 e 4x4 — **9/9 verde**. Com o CSS antigo o "
        "mesmo teste acusa **36 falhas** (\"contorno da janela cortado em 3.0 px\", \"padding-top do palco "
        "= 0\"), ou seja: a prova pega o defeito, não só acompanha.\n"
    ),
    "0.6.8": (
        "**O cadastro das câmeras chega ao lado terra — e as telas passam a mostrar o que está no ar, "
        "com ou sem cadastro.**\n\n"
        "Queixa: \"cadastrei as câmeras com seleção de qualidade e tudo mais, está no ar, mas elas não "
        "aparecem na tela Tempo real, Produção e na transmissão ao vivo do cliente\". Medido (18/11/2026): "
        "o lado terra recebia **três fluxos no ar sem cadastro** (`comp-1`, `vivo-cam1-11-18`, "
        "`vivo-cam2-11-18`) e a Produção vinha **vazia**; o log do repasse dizia *\"sem lado terra/token de "
        "ingestão\"*.\n\n"
        "* **Causa:** o servidor do PC de captura subia **sem** `LECSOR_TOKEN_INGESTAO`/`LECSOR_EMBARCACAO` "
        "porque o Python lia o `ambiente.json` na raiz e o instalador grava em `ground/ambiente.json` — sem "
        "token, o anúncio do cadastro nem saía, e em silêncio. Agora o **próprio Python lê o ambiente nas "
        "duas posições**, sem sobrepor o que já veio por variável de ambiente.\n"
        "* **O build passa a FALHAR** se o pacote do PC de captura nascer sem ambiente (antes só avisava no "
        "log): pacote sem ambiente é pacote que não anuncia, e ninguém percebia.\n"
        "* **O anúncio ficou visível:** `/api/saude` responde `anuncio` (tem token? tem lado terra? qual "
        "embarcação? qual o último erro) e há `/api/publicacao` (ver e republicar), com o resultado **por "
        "câmera** — publicado/não e o motivo escrito. No Admin > Câmeras há a caixa \"Lado terra\".\n"
        "* **República no boot e continua tentando** (antes fazia 5 tentativas e silenciava para sempre).\n"
        "* **\"Tempo real\" e \"Produção\" mostram o fluxo que está no ar mesmo sem cadastro**, marcado com "
        "⚠ **sem cadastro** em vez de sumir da tela — era isso que dava a tela vazia com o vídeo chegando. "
        "Fluxo sem medida não derruba mais a tela (a conta usa 0, não vazio).\n"
        "* **O lado terra não encaminha mais para si mesmo:** o teste de \"é esta máquina?\" passa a olhar "
        "**IP e porta** (o `/admin/` do lado terra respondia 502 depois de ligar a leitura do ambiente).\n"
        "* **Provas novas:** `tests/test-anuncio-do-cadastro.py` — **12/12 verde**; "
        "`tests/test-fluxo-sem-cadastro-na-tela.py` — **11/11 verde**; `tests/test-ponte-do-lado-terra.py` "
        "continua **8/8**; `tests/e2e-envios.py` **72 ok / 0 falhas**.\n"
    ),
    "0.6.7": (
        "**A tela do app passa a ser servida pela própria máquina: é isso que faz o Admin listar as câmeras "
        "no PC de captura.**\n\n"
        "A queixa era \"continua não listando as câmeras no app admin no computador de captura\". Medido "
        "(18/11/2026): a câmera aparecia no `curl` do servidor local, a ponte do app entregava o endereço "
        "certo, o CORS estava certo — e a página, vinda do lado terra (IP público), **não conseguia falar com "
        "`http://127.0.0.1:8765`**: o Chromium do app bloqueia pedido de página pública para endereço de "
        "loopback (`Failed to fetch`). Numa página servida pelo **próprio servidor local** o mesmo pedido "
        "responde 200 com a câmera.\n\n"
        "* **O servidor local passa a servir a TELA do app** (mesma origem das rotas de captura) e **encaminha "
        "ao lado terra** tudo o que não é captura: páginas, css, login, cadastro, usuários, gravações. "
        "Caminho, método, cookies, corpo e status voltam como vieram; download de vídeo não passa pela "
        "memória.\n"
        "* **`/api/eu` volta do lado terra com `local: true`** — o pedido veio pela ponte desta máquina, e é "
        "isso que mantém os botões de câmera liberados para quem está no PC de captura.\n"
        "* **Se o servidor local não responder, as telas abrem no lado terra** (nunca em endereço que não "
        "atende).\n"
        "* **`tests/test-ponte-do-lado-terra.py`** (novo): sobe um lado terra falso e o servidor local de "
        "verdade e prova as 8 checagens — **8/8 verde**."
    ),
    "0.6.6": (
        "**O redesenho da tela não apaga mais o que o operador escolheu ou digitou, e o teste de ponta a "
        "ponta do envio passou a rodar sozinho (verde).**\n\n"
        "A tela do admin se repinta sozinha quando os dados mudam. Ao repintar, ela recriava os campos do "
        "formulário de envio — e o arquivo já escolhido e o texto digitado se perdiam. Medido 18/11/2026: o "
        "botão \"Comprimir e medir\" respondia *\"escolha o arquivo de vídeo\"* com o arquivo já escolhido, e a "
        "tabela de compressões da operação aparecia sem as colunas.\n\n"
        "* **A tela de envio não é mais repintada enquanto você está preenchendo** (arquivo escolhido ou texto "
        "digitado). As listas continuam se atualizando pelo timer delas; trocar de tela pelo menu sempre "
        "funciona.\n"
        "* **Falha ao montar a tabela de compressões agora diz o motivo na tela** em vez de deixar a área "
        "vazia — o operador vê que algo deu errado.\n"
        "* **`tests/e2e-envios.py` roda sem depender da máquina**: sobe a própria bancada (`api.py "
        "--semear-demo`, banco temporário), o servidor de mídia local e lê a senha de bancada de uma fonte só "
        "(`ground/.env.local`) — medido: **72 checagens ok, 0 falhas**."
    ),
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
