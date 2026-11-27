#!/usr/bin/env python3
"""Regressao curada da rodada 0.13.0 (flag de audiencia / saude-desempenho / contagem+aviso+reconectar / gravacao).

Roda cada prova num processo proprio e imprime `rc` por prova — o que o dono le' e' a lista. As 4
primeiras sao as NOVAS desta rodada; o resto e' o que a 0.12.0 ja' provava e passa pelas MESMAS rotas
que esta rodada encostou (`ground/api.py`, `ground/saude_do_bordo.py`, `admin/admin.js`, `app/app.js`,
`desktop/main.js`, `fronts/*.css`).

    python tools/regressao-0130.py
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# Toda prova sobe servidor proprio: sem isto ela herdaria o lado terra (VPS), o token e o Supabase do
# `ambiente.json` que esta' no repositorio, e passaria a falar com a producao em vez de responder em casa.
os.environ["LECSOR_SEM_AMBIENTE"] = "1"
PROVAS = (
    # RODADA 0.27.1 — O GRAVADOR DO HD VOLTA A LER O CADASTRO NO PYTHON EMBUTIDO (dono, 27/11/2026:
    # "no sistema do admin: 'o hd de bordo continua nao gravando as imagens do radar de oleo'" e "no app
    # de bordo: 'radar - gravando - 0 bloco(s) no HD'"). O log do gravador entregou a causa:
    # "nao consegui ler o cadastro desta maquina (ModuleNotFoundError: No module named 'api')". O
    # `python312._pth` do Python embutido do pacote nao poe a pasta do script no `sys.path`, entao o
    # `import api` do laco explodia e o gravador saia na primeira linha (0 blocos, sem `gravador.log`).
    # A mesma rodada faz a TELA parar de mentir: "gravando" agora e' a MEDIDA (`gravando_agora()`), nao
    # o desejo do admin — no bordo, no `/api/bordo` e no catalogo que vai para terra.
    "tests/test-o-gravador-fala-com-o-cadastro-no-python-embutido.py",
    "tests/e2e-dashboard-de-verdade-e-card-compacto.py",
    # RODADA 0.27.0 — O APP DO PC DE CAPTURA ANTIGO E O PSUTIL DENTRO DO PACOTE (dono, 26/11/2026:
    # "gravação contínua: publicada LIGADA — o bordo: ligada (ligada, mas esta maquina nao tem dispositivo
    # de video configurado (LECSOR_HD_DISPOSITIVO): nada sera' gravado) ... precisamos resolver isso" e
    # "para termos as informações de cpu, memória e rede, precisamos instalar o psutil"). Medido: o PC de
    # captura (DESKTOP-78DSH57) reporta `versao_app: 0.25.0` e `nao_medido` = "sem psutil neste Windows".
    # O produto passou a DENUNCIAR o app antigo (nomeando as duas versoes) e o psutil viaja DENTRO do
    # pacote — o python que o cliente recebe mede CPU, memoria e rede.
    "tests/test-psutil-no-portatil.py",
    "tests/test-versao-do-bordo-e-publicada.py",
    # RODADA 0.26.0 — o HD full-time do radar acha o dispositivo pelo TIPO/NOME do admin e diz o motivo
    # nas duas telas. (A prova existia desde a 0.26.0 mas nao estava na lista — entrou aqui.)
    "tests/test-o-hd-acha-o-dispositivo-do-radar.py",
    # RODADA 0.23.0 — O AO VIVO DO ADMIN LIGA E PARA, E O MONITORAMENTO DIZ SE ESTA' GRAVANDO A BORDO
    # (dono, 26/11/2026: "eu devo poder ligar e parar a camera tambem, 'imagens gravadas a bordo' nao faz
    # sentido, so' preciso no monitoramento saber se esta' sendo gravado a bordo, nao preciso ver as
    # imagens" — decisoes "2.A" e "sim, botao ligar/desligar + indicador"). A tela "Imagens gravadas a
    # bordo" SAIU do admin (as rotas `/api/hd/*` ficam: sao as do cliente e do observador), o admin abre a
    # MESMA sessao do cliente no ao vivo (ele e' a plateia: fechando, a camera para) e a gravacao continua
    # do radar ganhou botao no cartao da embarcacao (o admin publica, o BORDO aplica no HD dele).
    "tests/test-ao-vivo-do-admin-ligar-parar-e-gravando-a-bordo.py",
    "tests/e2e-ao-vivo-do-admin-liga-e-para.py",
    # RODADA 0.22.0 — O TIPO LIDO A TELA, A TELA SEM PISCAR E A VARREDURA A PEDIDO (dono, 26/11/2026:
    # "eu aplico novo tipo a camera, mas nao esta persistindo" · "quando a pagina atualiza, parece que
    # remonta toda a pagina ... a pagina 'pisca' e eu perco o que estou fazendo" · "nesta tela preciso
    # tambem de um botao para refazer varredura ... apenas inclui as que nao estao aparecendo, nao
    # remonta tudo pra nao perder as configuracoes ja feitas"). O tipo NUNCA deixou de gravar: quem
    # mentia era a LEITURA (`arvore_do_painel` lia as cameras sem a coluna `tipo`). A acao do usuario
    # atualiza so' o cartao afetado e o auto-refresh nao repinta a tela de trabalho.
    "tests/test-tipo-lido-do-banco.py",
    "tests/test-varredura-a-pedido.py",
    "tests/test-tela-sem-piscar-e-varredura.py",
    # RODADA 0.21.0 — MAIS QUALIDADE DE ENVIO E MENOS TELA (dono, 26/11/2026: "inclua no plano mais
    # possibilidades de qualidade de envio, 2mbps, 2,5mbps e 3mbps" · "o bloco de seleção de qualidade
    # de envio sumiu da tela de configuração de bordo" · "se eu consigo editar empresa, embarcação e
    # câmeras em 'Empresas e configuração', é necessário 'Configuração do bordo'?" · "precisamos deixar
    # tudo mais simples"): a lista FECHADA passou a ter 3,0 / 2,5 / 2,0 Mbps e virou UMA fonte so' (o
    # servidor na frente, o admin derivando dela), o TETO da embarcação foi para o cartão da embarcação
    # e a tela "Configuração do bordo" saiu do menu.
    "tests/test-lista-de-alvos-igual-ao-servidor.py",
    "tests/e2e-qualidade-e-teto-em-empresas.py",
    # RODADA 0.20.0 — DASHBOARDS NO PADRAO DOCK CHECK (dono, 25/11/2026: "tanto o dashboard do admin
    # quanto o do app de captura continuam horriveis, precisa ser algo mais proximo desse do Dock
    # Check"): a leitura unica do admin (`/api/frota-resumo`, SO' ADMIN) com fileira de KPI, a
    # disponibilidade MEDIDA de 7 dias (retrato a retrato), o diagnostico de conexoes e os alertas com
    # "o que fazer" — e o painel do bordo vestindo a MESMA linguagem (`fronts/dashboard.css`).
    "tests/test-dashboard-frota.py",
    # (A TELA "Imagens gravadas a bordo" do admin, da 0.20.0, SAIU na 0.23.0 — por decisao do dono. As
    # ROTAS `/api/hd/*` seguem no ar: sao as do cliente "Radar de oleo (HD)" e do observador
    # Petrobras/IBAMA. A prova da rodada cobra isso.)
    # RODADA 0.18.0 — CAMERA IP: o ENDERECO (IP) e o SEGREDO da camera de rede vivem NO PC DE CAPTURA
    # (dono, 25/11/2026: "senha nao pode vazar, tem que tudo ficar no bordo, entao nao vamos poder
    # inserir nem o ip no admin"). A maquina de captura cadastra/edita/remove a camera de rede; o admin
    # (lado terra) ve so' o nome. Cadastro remoto (sem a maquina se declarar) continua recusado.
    "tests/test-camera-ip-no-bordo.py",
    # RODADA 0.17.0 — a TELA CHEIA leva a contagem e o botao junto (era pedida no <video>, e o card e o
    # aviso sao IRMAOS dele: a sessao morria sem o cliente ter onde clicar); RECARREGAR a pagina nao
    # derruba mais a transmissao (`pendente` + carencia de 8 s, cancelada pelo batimento de volta); e a
    # proporcao da grade passa a ser a MEDIANA (a MENOR encolhia todas as celulas com uma camera parada)
    "tests/e2e-tela-cheia-e-pausa.py",
    "tests/e2e-recarga-nao-derruba.py",
    # RODADA 0.15.0 — o card do controle vira UMA linha de 34 px e a imagem para de encolher (inclusive ao
    # reconectar), a grade passa a aproveitar o espaco e a remedir sozinha (ResizeObserver), o BORDO MUDO
    # (> 180 s sem sinal) encerra a sessao no lado terra, e o /bordo ganha o DASHBOARD DE VERDADE (as 4
    # curvas: cpu, memoria, disco e rede)
    "tests/e2e-dashboard-de-verdade-e-card-compacto.py",
    "tests/e2e-grade-usa-todo-o-palco-e-menu.py",
    "tests/e2e-imagem-sem-faixa-preta.py",
    # RODADA 0.14.0 — a imagem nao muda de tamanho no redesenho, "Parar transmissao" volta clicavel, os
    # dois dashboards (bordo e admin) e a telemetria do PC de captura (cpu/memoria/disco/rede, individual
    # e global)
    "tests/e2e-tamanho-fixo-dashboards-e-telemetria.py",
    # RODADA 0.13.2 — a imagem da grade nao pode ser cortada (o dono: "preciso das imagens inteiras") e o
    # rodape baixou para so' a linha de direitos
    "tests/e2e-imagem-da-grade-nao-corta.py",
    # RODADA 0.13.1 (ja' entra na suite)
    # a janela de 60 s ao sair da tela ao vivo (o batimento so' vale na GRADE) + o card ABAIXO da imagem
    "tests/e2e-janela-ao-sair-da-tela.py",
    # AS NOVAS DA 0.13.0
    # D3 do dono: a flag de transmissao se sustenta so' na sessao de quem assiste (nao ha "ligar" do admin)
    "tests/e2e-flag-de-audiencia.py",
    # saude e desempenho na area unica, e a chave da licenca NUNCA sai inteira (P0 de seguranca)
    "tests/e2e-saude-e-desempenho-na-area.py",
    # contagem regressiva, aviso do ultimo minuto, silencio-desliga (D2) e o botao "Reconectar"
    "tests/e2e-contagem-aviso-e-reconectar.py",
    # o botao de gravar na GRADE do cliente: grava o que JA' CHEGOU (D4) e o mp4 fica no disco
    "tests/e2e-gravacao-no-cliente.py",
    # O QUE A 0.12.0 JA' PROVAVA (mesmas rotas)
    "tests/e2e-admin-unificado.py",
    # CHAVE DE LICENCA (rodada 0.10.0)
    "tests/test-licenca-de-ativacao.py",
    "tests/test-licenca-do-bordo.py",
    "tests/e2e-licenca-no-admin.py",
    "tests/e2e-app-ativado-por-licenca.py",
    "tests/test-licenca-nao-vaza.py",
    "tests/test-licenca-isola-embarcacao.py",
    # escopos de cliente (Fase 1)
    "tests/test-escopos-de-acesso.py",
    "tests/e2e-escopo-no-admin.py",
    # varredura / cadastro automatico (Fase 2)
    "tests/e2e-varredura-do-bordo.py",
    # cadastro do bordo nao se perde (Fase 3)
    "tests/test-fluxo-no-lado-terra.py",
    # observador / Petrobras (Fase 4)
    "tests/e2e-observador-do-radar.py",
    # RODADA 0.24.0 — "as telas 'Gravacoes' e 'Radar de oleo (HD)' podem ser uma pagina apenas
    # 'Gravacoes'" (dono, 26/11/2026): a pagina unica (bloco do bordo + bloco de terra), o filtro por
    # data e hora valendo nos dois, e o pedido/baixar do bordo seguindo na mesma tela.
    "tests/e2e-pagina-unica-de-gravacoes.py",
    "tests/e2e-tela-do-radar-hd-do-cliente.py",
    # RODADA 0.24.0 — os QUATRO TIPOS DE CLIENTE: o tipo e' DERIVADO dos vinculos (`escopo_do_cliente`)
    # e a prova mede, contra o servidor, o que cada um dos 4 usuarios enxerga (1 embarcacao / algumas /
    # todas da empresa / todas as empresas) — inclusive o HD do bordo e o historico de terra.
    "tests/test-os-4-tipos-de-cliente.py",
    # RODADA 0.25.0 — O PEDIDO DE TRECHO QUE O BORDO NAO RESPONDE (dono, 26/11/2026: "esse 'chegando...'
    # parece que está travado"). O pedido vencido vira `sem_resposta` com motivo (nao fica pendurado nem
    # e' apagado: historico + auditoria), a tela mostra a idade e oferece pedir de novo, e o painel do
    # bordo ocupa a largura toda, diz "nao medido" com o motivo e mostra o boot no Windows.
    "tests/test-pedido-do-hd-sem-resposta.py",
    # RODADA 0.19.0 — O OBSERVADOR FILTRA POR TIPO, NAO POR NOME (dono, 25/11/2026: "petrobras ou ibama
    # pode acessar ... mas apenas do radar de oleo e camera flir se tiver"). A camera ganha a coluna
    # `tipo` (camera|radar|flir); o radar pelo TIPO aparece mesmo sem "radar" no nome; a FLIR aparece; a
    # camera com "radar" no NOME mas tipo 'camera' NAO aparece. A migracao faz o backfill pelo nome.
    "tests/test-observador-por-tipo.py",
    # o que a 0.8.0 ja' provava e passa por estas rotas
    "tests/test-papeis-de-config.py",
    "tests/test-cadastro-so-pelo-admin.py",
    "tests/test-app-unico-por-papel.py",
    "tests/e2e-cadastro-de-camera-salva-no-banco.py",
    "tests/e2e-config-do-bordo-vinda-de-terra.py",
    "tests/e2e-tela-do-captura-so-cadastra.py",
    "tests/e2e-admin-configura-e-bordo-obedece.py",
    "tests/e2e-saude-do-bordo-no-admin.py",
    "tests/e2e-flag-de-estado-liga-a-camera.py",
)


def main() -> int:
    ruins = []
    for prova in PROVAS:
        caminho = RAIZ / prova
        if not caminho.exists():
            print(f"PULOU (nao existe) {prova}")
            continue
        proc = subprocess.run([sys.executable, str(caminho)], cwd=str(RAIZ),
                              capture_output=True, text=True, timeout=900, errors="replace")
        ultima = ""
        for linha in reversed((proc.stdout or "").splitlines()):
            if linha.strip():
                ultima = linha.strip()
                break
        print(f"rc={proc.returncode:<3} {prova} — {ultima[:120]}")
        if proc.returncode != 0:
            ruins.append(prova)
    print()
    if ruins:
        print("FALHARAM: " + ", ".join(ruins))
        return 1
    print(f"TUDO VERDE ({len(PROVAS)} provas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
