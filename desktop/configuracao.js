// Resolve o config efetivo do aplicativo: valores de FABRICA (papel do instalador) + o que o
// usuário já gravou em `%APPDATA%\<app>\config.json`.
//
// Vive fora do `main.js` para poder ser testado sem Electron (o teste roda este arquivo com node).
//
// Regras:
//  1) o papel do instalador manda no `base`, no `destinoSrt` e no servidor local;
//  2) config de OUTRO papel (ou das versões antigas, que não gravavam `papel`) é descartado nesses
//     campos: foi isso que fez uma instalação nova abrir apontada para o endereço errado;
//  3) `ajuste_manual` (o operador mudou papel/endereço pela tela) tem a palavra final — MENOS quando
//     o endereço gravado é incoerente com o próprio papel: papel que NÃO sobe servidor local não
//     tem nada escutando em 127.0.0.1, então apontar para loopback aí é sempre engano (config velho
//     gravado no MESMO papel, que o guard do item 2 não pegava). Foi o "lado terra não respondeu
//     (conexão recusada)" numa instalação que abria em 127.0.0.1:8765.
//  4) servidor local LIGADO nesta máquina => o aplicativo fala com ELE (base = 127.0.0.1:porta), e o
//     destino do repasse sai de fábrica quando o operador nunca definiu um. É o servidor local que
//     conhece as câmeras ligadas aqui e é ele que repassa o fluxo; sem isso, subir o servidor numa
//     instalação apontada para o lado terra não mudava nada (tela remota sem câmera + repasse "(nada)").
//  5) EXCEÇÃO do item 4, pedida pelo dono (16/11/2026): "deve liberar as funções de captura, não mudar
//     para o app de captura". Com `capturaLocal` ligado o servidor local sobe PARA A CAPTURA e as
//     telas continuam vindo de onde já vinham (o Admin segue no lado terra, logado). Trocar a base
//     para o loopback aí jogava o login num banco local vazio e abria a tela de "primeiro acesso".
'use strict';

const LOOPBACK = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(?::\d+)?(?:\/|$)/i;

function ehLoopback(endereco) {
  return LOOPBACK.test(String(endereco || '').trim());
}

/// Devolve `{ config, herdado, corrigido }`: o config resolvido, se houve herança de outro papel e
/// se o endereço foi corrigido por incoerência (nos dois casos o chamador regrava o arquivo).
function resolver(PADRAO, PAPEIS, PAPEL, doUsuario) {
  const papel = PAPEIS[PAPEL] || {};
  const fabrica = {
    base: papel.base || PADRAO.base,
    destinoSrt: papel.destinoSrt || '',
    // 6) O PACOTE UNICO abre a tela de ENTRADA (`papeis.json` -> unico): o papel define quais telas
    // abrem, e delas sai a tela do usuario depois do login.
    abrirAoIniciar: (papel.abrirAoIniciar || PADRAO.abrirAoIniciar || []).slice(),
    modoQuiosque: !!PADRAO.modoQuiosque,
    abrirComWindows: !!papel.abrirComWindows,
    servidorLocal: Object.assign({ ligado: false, repo: '', portaApi: 8765 },
      PADRAO.servidorLocal || {}, papel.servidorLocal || {}),
    // 7) O PAPEL manda tambem nas funcoes de captura (dono, 18/11/2026: "o admin tem acesso a tudo,
    // ja deve ter por padrao todas as autorizacoes" / "precisa ser plug & play"). O papel `unico`
    // nasce com `capturaLocal` ligado: quem instala no PC de captura ja captura, sem passar por menu
    // — e nesse modo a base NUNCA vira loopback (regra 5), entao o login continua o do lado terra.
    capturaLocal: !!(papel.capturaLocal === true || PADRAO.capturaLocal === true)
  };
  const herdado = !!doUsuario && doUsuario.papel !== PAPEL && !doUsuario.ajuste_manual;
  if (herdado) {
    delete doUsuario.base; delete doUsuario.destinoSrt; delete doUsuario.servidorLocal;
    delete doUsuario.capturaLocal;          // estado de captura também é do papel, não se herda
  }
  const config = doUsuario
    ? Object.assign({}, fabrica, doUsuario,
        { servidorLocal: Object.assign({}, fabrica.servidorLocal, doUsuario.servidorLocal || {}) })
    : fabrica;

  let corrigido = false;
  const porta = config.servidorLocal.portaApi || 8765;
  const local = `http://127.0.0.1:${porta}`;
  // 8) O PAPEL declara as funcoes de captura (item 7): config velha gravada na MAQUINA nao pode
  // desfazer isso — senao a instalacao que ja existia continuava trocando a base para o loopback no
  // "Subir servidor nesta maquina" e o login caia no banco local vazio (o caso de 18/11/2026).
  // Com a captura declarada pelo papel, o servidor local tambem sobe junto (e' ele que captura).
  if (papel.capturaLocal === true) {
    if (config.capturaLocal !== true) { config.capturaLocal = true; corrigido = true; }
    if (!config.servidorLocal.ligado) { config.servidorLocal.ligado = true; corrigido = true; }
    // A MAQUINA DE CAPTURA E' AUTONOMA (dono, 23/11/2026): "o app de captura deve ser autônomo, faz as
    // varreduras locais e fica verificando as flags de terra". Ela sobe sozinha no boot do Windows —
    // quem decidiu isso um dia foi o operador (o menu "Abrir junto com o Windows" continua mandando);
    // o que nao pode e' o pacote de captura nascer FORA do boot e o barco so' publicar quando alguem
    // abrir o aplicativo na mao. Sem `corrigido`: e' o papel, nao um conserto de arquivo torto.
    const escolheu = !!doUsuario && Object.prototype.hasOwnProperty.call(doUsuario, 'abrirComWindows');
    if (!escolheu && config.abrirComWindows !== true) config.abrirComWindows = true;
  }
  if (config.servidorLocal.ligado) {
    // Servidor local LIGADO nesta maquina: o aplicativo fala com ELE. É o servidor que conhece as
    // câmeras ligadas aqui, e é quem empacota e repassa o fluxo para o lado terra. Sem isto, ligar o
    // servidor local numa instalação apontada para o lado terra não mudava nada: a tela continuava
    // vindo do servidor remoto (sem as câmeras desta maquina) e o repasse ficava "(nada)".
    // O destino do repasse também sai de fábrica (só quando o operador nunca definiu um: quem
    // apagou o destino de propósito continua com o repasse desligado), senão o fluxo desta maquina
    // não sobe para o lado terra — era o "(nada - so esta maquina)" depois de ligar o servidor.
    const destinoProprio = !!doUsuario && Object.prototype.hasOwnProperty.call(doUsuario, 'destinoSrt');
    if (!destinoProprio && !config.destinoSrt) config.destinoSrt = fabrica.destinoSrt || PADRAO.destinoSrt || '';
    if (config.capturaLocal) {
      // Servidor local para a CAPTURA, telas no lado que já estava configurado (item 5 acima).
      if (ehLoopback(config.base)) { config.base = fabrica.base; corrigido = true; }
    } else if (config.base !== local) {
      config.base = local; corrigido = true;
    }
  } else if (ehLoopback(config.base)) {
    // Incoerência papel x endereço: quem NÃO sobe servidor local não escuta em loopback.
    config.base = fabrica.base;
    corrigido = true;
  }
  return { config, herdado, corrigido };
}

/// De onde vem a tela de ENTRADA. Regra do dono (18/11/2026): "o próprio app deveria se organizar de
/// acordo com o usuário" — a entrada NUNCA pode vir de um servidor local que ainda não tem usuário
/// nenhum quando o lado terra responde: era ali que estavam as contas, e o login caía num banco local
/// vazio ("esta instalação ainda não tem usuário nenhum"). `medido` traz o que foi MEDIDO na máquina:
///   temUsuarios         -> o servidor local desta máquina já tem cadastro próprio
///   ladoTerraResponde   -> o lado terra desta instalação respondeu
/// Sem nada medido (ou ninguém respondendo) mantém o servidor local: é o bordo sem internet, onde o
/// primeiro acesso é criado na própria máquina e "Enviar vídeo" precisa abrir mesmo assim.
function enderecoDaEntrada(config, medido) {
  const m = medido || {};
  const cfg = config || {};
  const local = `http://127.0.0.1:${(cfg.servidorLocal || {}).portaApi || 8765}`;
  if (!(cfg.capturaLocal && cfg.servidorLocal && cfg.servidorLocal.ligado)) return cfg.base;
  if (m.temUsuarios === true) return local;
  if (m.ladoTerraResponde === true) return cfg.base;
  return local;
}

module.exports = { resolver, ehLoopback, enderecoDaEntrada };
