// Ponte minima: o site NAO ganha Node. Ele so descobre o endereco do lado terra, que ja e publico.
const { contextBridge } = require('electron');
contextBridge.exposeInMainWorld('lecsorApp', {
  enderecoDoLadoTerra: () => process.env.LECSOR_BASE || null,
  versao: () => process.versions.electron
});
