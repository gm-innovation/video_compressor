// Ponte minima: o site NAO ganha Node. Ele so descobre o endereco do lado terra, que ja e publico.
const { contextBridge } = require('electron');
contextBridge.exposeInMainWorld('lecsorApp', {
  enderecoDoLadoTerra: () => process.env.LECSOR_BASE || null,
  // Funcoes de captura liberadas nesta maquina (menu "Servidor local"): as rotas de captura vao para
  // o servidor LOCAL, mesmo com a tela vinda do lado terra. Sem isso o Admin no lado terra nao
  // enxerga camera nenhuma desta maquina. Ver `api()` e `urlDeCaptura()` em admin/admin.js.
  enderecoDaCaptura: () => process.env.LECSOR_CAPTURA_BASE || null,
  versao: () => process.versions.electron
});
