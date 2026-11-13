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

  // Incoerência papel x endereço: quem não sobe servidor local não escuta em loopback.
  let corrigido = false;
  if (ehLoopback(config.base) && !config.servidorLocal.ligado) {
    config.base = fabrica.base;
    corrigido = true;
  }
  return { config, herdado, corrigido };
}

module.exports = { resolver, ehLoopback };
