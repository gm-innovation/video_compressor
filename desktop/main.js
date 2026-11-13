// Aplicativo Windows (Electron) com as tres superficies do pipeline de video bordo->terra.
// Regra de seguranca: o processo de interface NAO tem Node, NAO guarda credencial de camera
// nem chave de API — ele so abre as rotas servidas pela API, igual ao navegador faria.
const { app, BrowserWindow, Menu, shell, ipcMain, dialog } = require('electron');
const fs = require('fs');
const http = require('http');
const path = require('path');

const RAIZ = __dirname;
const VERIFICAR = process.argv.includes('--verificar');   // sobe, confere e sai (rodado por teste)

// Cada instalador carrega UMA superficie (gravado no pacote pelo electron-builder). Sem isso,
// o app abre as tres (uso de bancada/engenharia). A variavel LECSOR_SUPERFICIE existe para o modo de desenvolvimento.
let SUPERFICIE = '';
try { SUPERFICIE = require('./package.json').superficie || ''; } catch (e) {}
SUPERFICIE = process.env.LECSOR_SUPERFICIE || SUPERFICIE;

// Papel desta instalação (gravado no pacote pelo electron-builder: captura | terra | bancada).
// Dele saem os valores de fábrica — o PC de captura nasce apontado para si mesmo e com o servidor
// ligado; o lado terra nasce apontado para o servidor. Ninguém edita JSON para instalar.
let PAPEL = 'bancada';
try { PAPEL = process.env.LECSOR_PAPEL || require('./package.json').papel || 'bancada'; } catch (e) {}
const PAPEIS = require('./papeis.json');
const PADRAO = require('./config.json');
const servidor = require('./servidor');
function caminhoConfig() { return path.join(app.getPath('userData'), 'config.json'); }
function lerConfig() {
  // O banco local fica na pasta do usuario: sobrevive a atualizacao do aplicativo (dentro da pasta de
  // instalacao ele seria apagado/reiniciado a cada versao nova).
  process.env.LECSOR_BANCO = process.env.LECSOR_BANCO || path.join(app.getPath('userData'), 'pipeline.db');
  const papel = PAPEIS[PAPEL] || {};
  const base = Object.assign(
    { base: PADRAO.base, destinoSrt: PADRAO.destinoSrt || '', abrirAoIniciar: PADRAO.abrirAoIniciar.slice(),
      modoQuiosque: !!PADRAO.modoQuiosque, abrirComWindows: false },
    { base: papel.base || PADRAO.base, destinoSrt: papel.destinoSrt || '', abrirComWindows: !!papel.abrirComWindows },
    { servidorLocal: Object.assign({ ligado: false, repo: '', portaApi: 8765 }, PADRAO.servidorLocal || {}, papel.servidorLocal || {}) });
  let doUsuario = null;
  try { doUsuario = JSON.parse(fs.readFileSync(caminhoConfig(), 'utf8')); } catch (e) { doUsuario = null; }
  // Config de OUTRO papel (ou das versões antigas, que não gravavam `papel`): endereço e servidor
  // local não valem para esta instalação — voltam para os de fábrica deste papel. Foi isso que fez
  // uma instalação nova de PC de captura abrir apontada para o lado terra.
  // `ajuste_manual` = o operador mudou o papel/endereco pela tela: a escolha dele manda, e o
  // papel do instalador deixa de resetar base/servidor local no proximo boot.
  const herdado = !!doUsuario && doUsuario.papel !== PAPEL && !doUsuario.ajuste_manual;
  if (herdado) {
    delete doUsuario.base; delete doUsuario.destinoSrt; delete doUsuario.servidorLocal;
  }
  const c = doUsuario
    ? Object.assign(base, doUsuario, { servidorLocal: Object.assign(base.servidorLocal, doUsuario.servidorLocal || {}) })
    : base;
  c.papel = PAPEL;
  if (!c.servidorLocal.repo) c.servidorLocal.repo = servidor.repoDe(c);   // embutido no app, quando houver
  // Primeira execução (ou config de outro papel): grava o resolvido, para o estado dizer o que está em uso.
  if (!doUsuario || herdado) { try { gravarConfig(c); } catch (e) {} }
  return c;
}
function gravarConfig(c) {
  const alvo = caminhoConfig();
  fs.mkdirSync(path.dirname(alvo), { recursive: true });
  fs.writeFileSync(alvo, JSON.stringify(c, null, 2) + '\n');
}
// --- entrada de texto (o menu do Electron nao tem campo): janela pequena que devolve o valor
// pelo titulo da pagina (sem Node na interface, sem IPC novo, sem credencial nenhuma).
function pedirTexto(titulo, valor, dica) {
  return new Promise((resolve) => {
    const j = new BrowserWindow({ width: 580, height: 215, resizable: false, minimizable: false, maximizable: false,
      title: titulo, backgroundColor: '#0b1220', alwaysOnTop: true, skipTaskbar: true,
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } });
    const html = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>
body{margin:0;padding:16px 18px;background:#0b1220;color:#e6edf7;font:14px/1.5 "Segoe UI",system-ui,sans-serif}
h1{font-size:15px;margin:0 0 6px}p{margin:0 0 10px;color:#9aa7bd;font-size:12px}
input{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #24334d;border-radius:8px;background:#111b2e;color:#e6edf7;font:14px monospace}
.d{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
button{padding:7px 14px;border-radius:8px;border:1px solid #24334d;background:#16213a;color:#e6edf7;font:14px inherit;cursor:pointer}
button.principal{background:#1d4ed8;border-color:#1d4ed8}</style></head><body>
<h1>${titulo}</h1><p>${dica || ''}</p>
<input id="v" value="${String(valor == null ? '' : valor).replace(/"/g, '&quot;')}">
<div class="d"><button id="c">Cancelar</button><button id="ok" class="principal">Salvar</button></div>
<script>
  document.getElementById('v').focus();
  const fim = (v) => { document.title = 'LECSOR_RESPOSTA:' + btoa(unescape(encodeURIComponent(v === null ? '\\u0000' : v))); };
  document.getElementById('ok').onclick = () => fim(document.getElementById('v').value.trim());
  document.getElementById('c').onclick = () => fim(null);
  document.getElementById('v').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') fim(document.getElementById('v').value.trim());
    if (e.key === 'Escape') fim(null);
  });
</script></body></html>`;
    let pronto = false;
    const fechar = (v) => { if (pronto) return; pronto = true; resolve(v); try { j.close(); } catch (e) {} };
    j.on('page-title-updated', (e, t) => {
      if (!String(t).startsWith('LECSOR_RESPOSTA:')) return;
      let v = '';
      try { v = decodeURIComponent(escape(Buffer.from(String(t).slice(16), 'base64').toString('binary'))); } catch (erro) {}
      fechar(v === '\u0000' ? null : v);
    });
    j.on('closed', () => fechar(null));
    j.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  });
}

// Le um JSON de um endereco LOCAL (loopback) do proprio aplicativo — sem base remota, sem credencial.
function buscarJson(url, ms = 6000) {
  return new Promise((resolve) => {
    const req = http.get(url, (r) => {
      let corpo = '';
      r.setEncoding('utf8');
      r.on('data', (d) => { corpo += d; });
      r.on('end', () => { let json = null; try { json = JSON.parse(corpo); } catch (e) {} resolve({ status: r.statusCode, json, corpo }); });
    });
    req.on('error', (e) => resolve({ status: 0, json: null, corpo: '', erro: e.message }));
    req.setTimeout(ms, () => { req.destroy(); resolve({ status: 0, json: null, corpo: '', erro: 'sem resposta em ' + ms + ' ms' }); });
  });
}

function recarregarTelas() {
  const abertas = Array.from(janelas.keys());
  for (const [, j] of janelas) { try { j.close(); } catch (e) {} }
  janelas.clear();
  for (const n of (abertas.length ? abertas : config.abrirAoIniciar)) abrir(n);
}

/// Subiu de verdade? Espera os processos assentarem e SONDA as portas: contar processo vivo nao
// basta — com a porta ocupada o mediamtx morre logo depois e a caixa dizia "no ar" enquanto nada
// servia (foi o que o dono viu no PC do cliente).
async function caixaServidor(motivo) {
  await new Promise((r) => setTimeout(r, 2500));
  const s = await servidor.sondagem(config);
  dialog.showMessageBox({ message: servidor.estado(),
    detail: (motivo ? motivo + '\n\n' : '') + 'checagem feita ' + new Date().toLocaleTimeString('pt-BR') +
      ', logo apos subir o servidor:\n' + s.linhas.join('\n') + '\n\n' + servidor.detalhe(config) });
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

function urlDe(nome) { return config.base.replace(/\/$/, '') + SUPERFICIES[nome].rota; }

// Tela de erro quando o lado terra nao responde: diz o endereco tentado e o motivo, em vez de
// deixar a janela vazia (parecia "nao aparece os campos de autenticacao").
function paginaDeErro(alvo, motivo) {
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Lado terra fora do ar</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0b1220;color:#e6edf7;font:15px/1.55 "Segoe UI",system-ui,sans-serif}
.caixa{max-width:620px;padding:28px 32px;border:1px solid #24334d;border-radius:14px;background:#111b2e}
h1{margin:0 0 10px;font-size:20px;color:#ffd166}p{margin:8px 0}b{color:#9fc4ff}
code{background:#0a1424;border:1px solid #24334d;border-radius:6px;padding:2px 6px}</style></head>
<body><div class="caixa">
<h1>O lado terra nao respondeu</h1>
<p>Endereco tentado: <code>${alvo}</code></p>
<p>Motivo: <b>${motivo}</b></p>
<p>O aplicativo abre a tela de autenticacao servida por esse endereco; sem ele, nao ha o que mostrar.
Confira se o servico esta rodando nessa maquina ou no servidor do lado terra, e se o endereco em
<code>config.json</code> (ao lado do aplicativo) esta certo. Depois use <b>Modo &rarr; Recarregar a tela</b>.</p>
</div></body></html>`;
}

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
    if (!url.startsWith(config.base) && !url.startsWith('data:')) { evento.preventDefault(); shell.openExternal(url); }
  });
  // Se o lado terra nao responde (API parada, endereco errado, sem rede), a janela NAO pode ficar
  // em branco com so o menu: o motivo aparece na tela. Foi assim que o dono viu "nao aparece
  // os campos de autenticacao" — a API estava fora do ar e a tela ficou vazia sem dizer nada.
  janela.webContents.on('did-fail-load', (evento, codigo, descricao, urlTentada, ehPrincipal) => {
    if (!ehPrincipal) return;
    const alvo = urlTentada || urlDe(nome);
    const motivo = codigo === -102 || codigo === -6 ? 'o servidor do lado terra nao respondeu (conexao recusada)'
                 : codigo === -105 ? 'nao foi possivel achar esse endereco (DNS)'
                 : codigo === -118 ? 'o servidor demorou demais para responder (tempo esgotado)'
                 : descricao || ('erro ' + codigo);
    janela.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(paginaDeErro(alvo, motivo)));
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
      { label: 'Recarregar a tela', accelerator: 'CmdOrCtrl+R', click: () => { for (const [, j] of janelas) j.webContents.reload(); } },
      { type: 'separator' },
      { label: 'Janela', type: 'radio', checked: !config.modoQuiosque, click: () => { config.modoQuiosque = false; gravarConfig(config); aplicar(); } },
      { label: 'Quiosque (tela cheia)', type: 'radio', checked: config.modoQuiosque, click: () => { config.modoQuiosque = true; gravarConfig(config); aplicar(); } }
    ] },
    { label: 'Servidor local', submenu: [
      { label: 'Subir servidor nesta maquina (API, mediamtx, agente)', click: () => {
          const r = servidor.subir(config);
          if (r.erro) return dialog.showErrorBox('Servidor local NAO subiu', r.erro);
          caixaServidor('Servidor disparado agora; as telas carregam em alguns segundos.');
        } },
      { label: 'Testar câmeras desta maquina', click: async () => {
          // Olha SEMPRE a maquina do aplicativo (loopback), mesmo com o endereco apontado para o
          // lado terra: era o que faltava para saber se o problema e' camera, ffmpeg ou endereco.
          const porta = (config.servidorLocal || {}).portaApi || 8765;
          const r = await buscarJson(`http://127.0.0.1:${porta}/api/dispositivos`);
          if (r.status !== 200) {
            return dialog.showMessageBox({ message: 'Nao consegui falar com o servidor local desta maquina',
              detail: `Endereco tentado: http://127.0.0.1:${porta}/api/dispositivos\n` +
                (r.erro ? 'Motivo: ' + r.erro : 'Resposta: HTTP ' + r.status) +
                '\n\nSuba o servidor local (menu Servidor local \u2192 Subir servidor nesta maquina) e tente de novo.' });
          }
          const d = r.json || {};
          const cams = Array.isArray(d.video) ? d.video : [];
          const ff = (d.ffmpeg || {}).ffmpeg || {};
          const linhas = [`maquina que respondeu: ${d.maquina || '(nao informado)'}`,
            `c\u00e2meras nesta maquina (${cams.length}): ${cams.length ? cams.join(' | ') : '(nenhuma)'}`,
            `ffmpeg: ${ff.origem || '(nao informado)'}${ff.caminho ? ' \u2014 ' + ff.caminho : ''}`];
          if (d.motivo) linhas.push('motivo: ' + d.motivo);
          if (d.sintetica) linhas.push('existe tambem uma fonte sintetica de teste (testsrc2)');
          linhas.push('', 'esta maquina: ' + require('os').hostname());
          dialog.showMessageBox({ message: cams.length ? 'C\u00e2meras encontradas nesta maquina' : 'Nenhuma c\u00e2mera encontrada nesta maquina', detail: linhas.join('\n') });
        } },
      { label: 'Parar servidor local', click: () => {
          servidor.parar(config);
          dialog.showMessageBox({ message: servidor.estado(), detail: servidor.detalhe(config) });
        } },
      { type: 'separator' },
      { label: 'Abrir junto com o Windows', type: 'checkbox', checked: !!config.abrirComWindows,
        click: (item) => {
          config.abrirComWindows = !!item.checked; gravarConfig(config);
          try { app.setLoginItemSettings({ openAtLogin: !!item.checked }); } catch (e) {}
        } },
      { label: 'Ver estado do servidor', click: async () => {
          // sondagem de verdade: porta respondendo e' diferente de processo vivo
          const s = await servidor.sondagem(config);
          dialog.showMessageBox({ message: servidor.estado(),
            detail: s.linhas.join('\n') + '\n\n' + servidor.detalhe(config) });
        } },
      { label: 'Destino do repasse (lado terra)...', click: async () => {
          const valor = await pedirTexto('Destino do repasse (lado terra)', config.destinoSrt || '',
            'host:porta do lado terra que recebe os fluxos (ex.: 187.127.60.250:8890). Vazio = nada sobe desta maquina.');
          if (valor === null) return;
          if (valor && !/^\S+:\d{2,5}$/.test(valor)) return dialog.showErrorBox('Endereco invalido', 'Informe host:porta (ex.: 187.127.60.250:8890) ou deixe vazio.');
          config.destinoSrt = valor; gravarConfig(config);
          const rodando = servidor.vivos().length > 0;
          if (rodando) { servidor.parar(); servidor.subir(config); }
          dialog.showMessageBox({ message: 'Destino do repasse salvo',
            detail: (valor || '(nada \u2014 so esta maquina)') + (rodando ? '\n\nO servidor local foi reiniciado para o novo destino valer.' : '\n\nSuba o servidor local para o repasse valer.') });
        } },
      { label: 'Papel desta instalacao', submenu: [
        { label: 'Usar como PC de captura (esta maquina)', click: () => {
            // Preset: sem reinstalar e sem editar JSON (era o que faltava no PC de captura).
            config.ajuste_manual = true;
            config.base = 'http://127.0.0.1:8765';
            config.servidorLocal = Object.assign({}, config.servidorLocal, { ligado: true, portaApi: 8765 });
            if (!config.servidorLocal.repo) config.servidorLocal.repo = servidor.repoDe(config);
            gravarConfig(config);
            // Sobe o servidor ANTES de reabrir as telas: apontadas para o loopback, elas precisam da
            // API respondendo (senao abrem na pagina de erro "o lado terra nao respondeu").
            const r = servidor.subir(config);
            if (r.erro) return dialog.showErrorBox('Servidor local NAO subiu', r.erro);
            setTimeout(recarregarTelas, 1800);
            caixaServidor('Esta instalacao agora e PC de captura: telas em ' + config.base + '.');
          } },
        { label: 'Usar como lado terra (servidor na rede)', click: async () => {
            const valor = await pedirTexto('Endereco do lado terra', String(config.base || '').replace(/^https?:\/\//, ''),
              'endereco do servidor que recebe e mostra (ex.: 187.127.60.250:8085 ou 192.168.0.10:8085).');
            if (valor === null) return;
            if (!/^\S+:\d{2,5}$/.test(valor)) return dialog.showErrorBox('Endereco invalido', 'Informe host:porta (ex.: 187.127.60.250:8085).');
            config.ajuste_manual = true;
            config.base = 'http://' + valor;
            config.destinoSrt = '';
            config.servidorLocal = Object.assign({}, config.servidorLocal, { ligado: false });
            gravarConfig(config); recarregarTelas();
            dialog.showMessageBox({ message: 'Instalacao apontada para o lado terra',
              detail: config.base + '\n\nEsta maquina nao sobe servidor local nem repassa fluxo.' });
          } }
      ] }
    ] },
    { label: 'Ajuda', submenu: [
      { label: 'Endereco do lado terra em uso...', click: async () => {
          const valor = await pedirTexto('Endereco do lado terra', String(config.base || '').replace(/^https?:\/\//, ''),
            'Hoje: ' + config.base + ' \u00b7 repasse desta maquina: ' + (config.destinoSrt || '(nada \u2014 so esta maquina)') + '\nInforme host:porta do servidor que serve as telas (ex.: 187.127.60.250:8085).');
          if (valor === null) return;
          if (!/^\S+:\d{2,5}$/.test(valor)) return dialog.showErrorBox('Endereco invalido', 'Informe host:porta (ex.: 187.127.60.250:8085).');
          config.ajuste_manual = true;
          config.base = valor.startsWith('http') ? valor : 'http://' + valor;
          gravarConfig(config); recarregarTelas();
          dialog.showMessageBox({ message: 'Endereco salvo', detail: 'As telas foram reabertas em ' + config.base });
        } },
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
  try { app.setLoginItemSettings({ openAtLogin: !!config.abrirComWindows }); } catch (e) {}
  if (config.servidorLocal && config.servidorLocal.ligado) {
    const r = servidor.subir(config);
    // Falha do servidor local não pode ser silenciosa: sem ele o PC de captura não lista câmera nenhuma.
    setTimeout(() => { if (r.erro) dialog.showErrorBox('Servidor local NAO subiu', r.erro); }, 1500);
  }
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
