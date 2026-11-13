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
    abrirAoIniciar: (PADRAO.abrirAoIniciar || []).slice(),
    modoQuiosque: !!PADRAO.modoQuiosque,
    abrirComWindows: !!papel.abrirComWindows,
    servidorLocal: Object.assign({ ligado: false, repo: '', portaApi: 8765 },
      PADRAO.servidorLocal || {}, papel.servidorLocal || {})
  };
  const herdado = !!doUsuario && doUsuario.papel !== PAPEL && !doUsuario.ajuste_manual;
  if (herdado) {
    delete doUsuario.base; delete doUsuario.destinoSrt; delete doUsuario.servidorLocal;
  }
  const config = doUsuario
    ? Object.assign({}, fabrica, doUsuario,
        { servidorLocal: Object.assign({}, fabrica.servidorLocal, doUsuario.servidorLocal || {}) })
    : fabrica;

  let corrigido = false;
  const porta = config.servidorLocal.portaApi || 8765;
  const local = `http://127.0.0.1:${porta}`;
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
    if (config.base !== local) { config.base = local; corrigido = true; }
  } else if (ehLoopback(config.base)) {
    // Incoerência papel x endereço: quem NÃO sobe servidor local não escuta em loopback.
    config.base = fabrica.base;
    corrigido = true;
  }
  return { config, herdado, corrigido };
}

module.exports = { resolver, ehLoopback };
