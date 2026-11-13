/* Prova do estado honesto do servidor local: com as portas ocupadas (a instalação que já está
   rodando nesta máquina), o `subir` não pode dizer "no ar". Espera-se: processos morrem e o estado
   diz PARADO com o motivo, lido do log de erro. */
const servidor = require('C:/Users/EngenhariaGoogleMari/lecsor-pipeline-video/desktop/servidor.js');
const cfg = {
  base: 'http://127.0.0.1:8765',
  destinoSrt: '',
  servidorLocal: { ligado: true, portaApi: 8765, repo: 'C:/Users/EngenhariaGoogleMari/lecsor-pipeline-video' },
};
process.env.LECSOR_BANCO = process.env.TMPDIR + '/estado-honesto.db';
const r = servidor.subir(cfg);
console.log('subir() =>', JSON.stringify(r).slice(0, 200));
console.log('estado() logo apos subir =>', servidor.estado());
setTimeout(() => {
  console.log('vivos() =>', servidor.vivos().length);
  console.log('estado() depois de 6s =>', servidor.estado());
  console.log('--- detalhe():');
  console.log(servidor.detalhe(cfg));
  servidor.sondagem(cfg).then((s) => {
    console.log('--- sondagem das portas:');
    console.log(s.linhas.join('\n'));
    servidor.parar();
    process.exit(0);
  });
}, 6000);
