// Servidor local dentro do aplicativo: quando a maquina for o lado terra (ou o PC de captura), o
// proprio app sobe API + mediamtx (+ agente de analise). Fora dos arquivos do app nao roda nada.
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

let filhos = [];

// O mesmo interpretador que roda a API e' o que o mediamtx usa para repassar o fluxo
// (`runOnAvailable: python ground/repasse.py`): sem isso o repasse nao acha o python no PATH do app.
function pythonDe(repo) {
  const venv = path.join(repo, '.venv', 'Scripts', 'python.exe');
  return fs.existsSync(venv) ? venv : 'python';
}

// O ffmpeg embutido no instalador (resources/ffmpeg/ffmpeg.exe). E' ele que faz a maquina listar e
// capturar camera SEM depender de instalacao manual: sem ffmpeg a lista de dispositivos fica vazia.
function ffmpegDe() {
  const raiz = process.resourcesPath || path.join(__dirname, '..');
  const exe = path.join(raiz, 'ffmpeg', process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg');
  return fs.existsSync(exe) ? exe : '';
}

// Ambiente dos processos filhos. O destino do repasse (PC de captura -> lado terra) entra aqui:
// vazio = nada e' repassado (o PC de captura serve so' a propria tela); preenchido, o mediamtx local
// sobe o fluxo JA COMPRIMIDO para esse host:porta.
function amb(env, config) {
  const destino = String(((config || {}).destinoSrt) || '').trim();
  const saida = Object.assign({}, env || {});
  if (destino) saida.LECSOR_DESTINO_SRT = destino;
  else delete saida.LECSOR_DESTINO_SRT;
  const ff = ffmpegDe();
  if (ff) {
    saida.LECSOR_FFMPEG = ff;                                  // caminho explicito para o Python
    saida.LECSOR_FFPROBE = path.join(path.dirname(ff), 'ffprobe' + path.extname(ff));
    // e a pasta no PATH: qualquer chamada que escape do caminho explicito continua funcionando
    const sep = process.platform === 'win32' ? ';' : ':';
    saida.PATH = path.dirname(ff) + sep + (saida.PATH || '');
  }
  return saida;
}

function subir(config) {
  const repo = (config.servidorLocal && config.servidorLocal.repo) || process.env.LECSOR_REPO || '';
  if (!repo || !fs.existsSync(repo)) {
    return { erro: 'informe a pasta do repositorio (config.json: servidorLocal.repo)' };
  }
  parar();
  const logs = path.join(repo, 'desktop-logs');
  fs.mkdirSync(logs, { recursive: true });
  const env = amb(process.env, config);
  const python = pythonDe(repo);
  const item = (nome, comando, args, cwd) => {
    const p = spawn(comando, args, { cwd, env, shell: false });
    p.stdout.pipe(fs.createWriteStream(path.join(logs, nome + '.log'), { flags: 'a' }));
    p.stderr.pipe(fs.createWriteStream(path.join(logs, nome + '-erro.log'), { flags: 'a' }));
    filhos.push({ nome, p });
  };
  try {
    item('mediamtx', path.join(repo, 'tools', 'mediamtx', 'mediamtx.exe'), [path.join(repo, 'ground', 'mediamtx.yml')], repo);
    item('api', python, [path.join(repo, 'ground', 'api.py'), String((config.servidorLocal || {}).portaApi || 8765)], repo);
    const agente = path.join(repo, 'analytics', 'agente.py');
    if (fs.existsSync(agente)) {
      item('agente-analise', python,
           ['-u', agente, '--perfil', path.join(repo, 'analytics', 'perfis', 'cam-03.json')], repo);
    }
  } catch (e) { return { erro: e.message }; }
  return { ok: true, subiu: filhos.length };
}
// A lista de cameras e a captura dependem do ffmpeg no PATH. Sem ele o app abre, mas nao existe
// dispositivo nenhum para escolher — o estado precisa dizer isso, e nao mostrar lista vazia sem causa.
function ffmpegInfo() {
  const embutido = ffmpegDe();
  const comando = embutido || 'ffmpeg';
  const r = spawnSync(comando, ['-hide_banner', '-version'], { encoding: 'utf8', timeout: 15000 });
  if (r.error || r.status !== 0) {
    return 'ffmpeg: NAO ENCONTRADO' + (embutido ? ' (o embutido nao executou)' : ' — nem embutido, nem no PATH') +
      ': sem ele a lista de cameras fica vazia e a captura nao roda';
  }
  const linha = String(r.stdout || '').split('\n')[0].trim();
  return `ffmpeg: ${embutido ? 'embutido no app' : 'do PATH da maquina'} — ${comando} (${linha})`;
}

function parar() { for (const { p } of filhos) { try { p.kill(); } catch (e) {} } filhos = []; }
function estado() {
  return filhos.length ? `servidor local no ar (${filhos.length} processos)` : 'servidor local parado';
}
function detalhe(config) {
  const destino = String(((config || {}).destinoSrt) || '').trim();
  const linhas = filhos.map((f) => `${f.nome}: pid ${f.p.pid}`);
  linhas.push(ffmpegInfo());
  linhas.push(`repasse para o lado terra: ${destino || '(nada — so esta maquina)'}`);
  return linhas.join('\n') || 'nada rodando pelo aplicativo';
}
module.exports = { subir, parar, estado, detalhe, amb, pythonDe, ffmpegDe };
