// Aplicativo Windows (Electron) com as tres superficies do pipeline de video bordo->terra.
// Regra de seguranca: o processo de interface NAO tem Node, NAO guarda credencial de camera
// nem chave de API — ele so abre as rotas servidas pela API, igual ao navegador faria.
const { app, BrowserWindow, Menu, shell, ipcMain, dialog } = require('electron');
const fs = require('fs');
const path = require('path');

const RAIZ = __dirname;
const VERIFICAR = process.argv.includes('--verificar');   // sobe, confere e sai (rodado por teste)

// Cada instalador carrega UMA superficie (gravado no pacote pelo electron-builder). Sem isso,
// o app abre as tres (uso de bancada/engenharia). A variavel LECSOR_SUPERFICIE existe para o modo de desenvolvimento.
let SUPERFICIE = '';
try { SUPERFICIE = require('./package.json').superficie || ''; } catch (e) {}
SUPERFICIE = process.env.LECSOR_SUPERFICIE || SUPERFICIE;

const PADRAO = require('./config.json');
function caminhoConfig() { return path.join(app.getPath('userData'), 'config.json'); }
function lerConfig() {
  const base = { base: PADRAO.base, abrirAoIniciar: PADRAO.abrirAoIniciar.slice(), modoQuiosque: !!PADRAO.modoQuiosque,
                 servidorLocal: Object.assign({ ligado: false, repo: '', portaApi: 8765 }, PADRAO.servidorLocal || {}) };
  try {
    const doUsuario = JSON.parse(fs.readFileSync(caminhoConfig(), 'utf8'));
    return Object.assign(base, doUsuario, { servidorLocal: Object.assign(base.servidorLocal, doUsuario.servidorLocal || {}) });
  } catch (e) { return base; }
}
function gravarConfig(c) {
  const alvo = caminhoConfig();
  fs.mkdirSync(path.dirname(alvo), { recursive: true });
  fs.writeFileSync(alvo, JSON.stringify(c, null, 2) + '\n');
}
const config = lerConfig();
if (SUPERFICIE) config.abrirAoIniciar = [SUPERFICIE];

// Cada superficie tem sessao propria (particao propria): entrar como cliente nao pode virar admin.
const SUPERFICIES = {
  cliente: { titulo: 'LECSOR — Cliente', rota: '/app', particao: 'persist:cliente', permitirSessao: true },
  admin: { titulo: 'LECSOR — Admin / Operacao', rota: '/admin', particao: 'persist:admin', permitirSessao: true },
  bancada: { titulo: 'LECSOR — Bancada', rota: '/', particao: 'persist:bancada', permitirSessao: true }
};
const janelas = new Map();
const servidor = require('./servidor');

function urlDe(nome) { return config.base.replace(/\/$/, '') + SUPERFICIES[nome].rota; }

function abrir(nome) {
  if (janelas.has(nome) && !janelas.get(nome).isDestroyed()) { janelas.get(nome).focus(); return janelas.get(nome); }
  const s = SUPERFICIES[nome];
  const janela = new BrowserWindow({
    width: 1440, height: 900, title: s.titulo, backgroundColor: '#0b1220', fullscreen: config.modoQuiosque,
    webPreferences: {
      partition: s.particao,
      contextIsolation: true,          // o preload roda isolado do site
      nodeIntegration: false,          // nada de Node na interface
      sandbox: true,
      webSecurity: true,
      preload: path.join(RAIZ, 'preload.js')
    }
  });
  // Navegacao presa a propria instalacao: link de fora abre no navegador do sistema.
  janela.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  janela.webContents.on('will-navigate', (evento, url) => {
    if (!url.startsWith(config.base)) { evento.preventDefault(); shell.openExternal(url); }
  });
  janela.loadURL(urlDe(nome));
  janelas.set(nome, janela);
  janela.on('closed', () => janelas.delete(nome));
  return janela;
}

function menu() {
  const modelo = [];
  if (!SUPERFICIE) {   // app de bancada: as tres superficies na mesma janela-menu
    modelo.push({ label: 'Superficies', submenu: Object.keys(SUPERFICIES).map((n) => ({ label: SUPERFICIES[n].titulo, accelerator: 'CmdOrCtrl+' + (n === 'cliente' ? '1' : n === 'admin' ? '2' : '3'), click: () => abrir(n) })) });
  }
  modelo.push(
    { label: 'Modo', submenu: [
      { label: 'Janela', type: 'radio', checked: !config.modoQuiosque, click: () => { config.modoQuiosque = false; gravarConfig(config); aplicar(); } },
      { label: 'Quiosque (tela cheia)', type: 'radio', checked: config.modoQuiosque, click: () => { config.modoQuiosque = true; gravarConfig(config); aplicar(); } }
    ] },
    { label: 'Servidor local', submenu: [
      { label: 'Subir servidor nesta maquina (API, mediamtx, agente)', click: () => servidor.subir(config) },
      { label: 'Parar servidor local', click: () => servidor.parar(config) },
      { label: 'Ver estado do servidor', click: () => dialog.showMessageBox({ message: servidor.estado(), detail: servidor.detalhe() }) }
    ] },
    { label: 'Ajuda', submenu: [
      { label: 'Endereco do lado terra...', click: () => dialog.showMessageBox({
          message: 'Lado terra em uso', detail: config.base + '\n\nPara trocar, edite config.json ao lado do aplicativo.' }) },
      { label: 'Sobre', click: () => dialog.showMessageBox({ message: 'LECSOR Pipeline de Video', detail: (SUPERFICIE ? 'Superficie: ' + SUPERFICIE + '. ' : 'Superficies: cliente, admin e bancada. ') + 'Interface sem acesso a credencial de camera e sem chave de API.' }) }
    ] }
  );
  if (SUPERFICIE === 'bancada') { /* servidor local ja esta no menu acima */ }
  if (process.platform === 'darwin') modelo.unshift({ label: app.name, submenu: [{ role: 'quit' }] });
  Menu.setApplicationMenu(Menu.buildFromTemplate(modelo));
}
function aplicar() { for (const [, j] of janelas) j.setFullScreen(config.modoQuiosque); }

app.whenReady().then(async () => {
  menu();
  for (const nome of config.abrirAoIniciar) abrir(nome);
  if (config.servidorLocal && config.servidorLocal.ligado) servidor.subir(config);
  if (VERIFICAR) {
    // Prova de vida para o teste: cada janela respondeu? Nada de credencial no processo?
    setTimeout(async () => {
      const linhas = [];
      const sonda = `(() => ({ node: typeof require, processo: typeof process, ponte: typeof window.lecsorApp,
                                endereco: (window.lecsorApp && window.lecsorApp.enderecoDoLadoTerra && window.lecsorApp.enderecoDoLadoTerra()) || null }))()`;
      // Prova opcional de ponta a ponta: entra como cliente e conta os videos tocando dentro do app.
      // A credencial vem do ambiente do TESTE (nunca fica no aplicativo nem no repositorio).
      const entrar = process.env.LECSOR_VERIFICAR_ENTRAR || '';
      if (entrar && janelas.has('cliente') && entrar.includes(':')) {
        const [email, senha] = entrar.split(':');
        try {
          const j = janelas.get('cliente');
          await j.webContents.executeJavaScript(`(() => { document.querySelector('#email').value = ${JSON.stringify(email)};
            document.querySelector('#senha').value = ${JSON.stringify(senha)};
            document.querySelector('form#form-entrar button[type=submit]').click(); return true; })()`);
          await new Promise((r) => setTimeout(r, 9000));
        } catch (e) { process.stdout.write('LOGIN_ERRO ' + e.message + '\n'); }
      }
      for (const [nome, j] of janelas) {
        let titulo = '', prova = '';
        try { titulo = await j.webContents.executeJavaScript('document.title'); } catch (e) { titulo = 'erro: ' + e.message; }
        try { prova = JSON.stringify(await j.webContents.executeJavaScript(sonda)); } catch (e) { prova = 'erro: ' + e.message; }
        try {
          const tv = await j.webContents.executeJavaScript(`(() => { const v = Array.from(document.querySelectorAll('.janela video'));
            return { janelas: v.length, tocando: v.filter((x) => x.readyState >= 2 && x.videoWidth > 0).length }; })()`);
          prova = prova.replace(/\}$/, `, "video_janelas": ${tv.janelas}, "video_tocando": ${tv.tocando}}`);
        } catch (e) { /* pagina sem video (ex.: bancada sem login) */ }
        linhas.push(`${nome}\t${j.webContents.getURL()}\ttitulo=${titulo}\tvisivel=${j.isVisible()}\tprova=${prova}`);
      }
      const relatorio = 'VERIFICACAO\n' + linhas.join('\n') + '\n';
      process.stdout.write(relatorio);
      // No Windows o .exe empacotado nao devolve stdout: grava o mesmo relatorio em arquivo.
      try { fs.writeFileSync(path.join(app.getPath('temp'), 'lecsor-verificacao.txt'), relatorio, 'utf8'); } catch (e) {}
      setTimeout(() => app.quit(), 500);
    }, 6000);
  }
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => abrir('cliente'));
ipcMain.handle('base', () => config.base);
