// Servidor local dentro do aplicativo: o próprio app sobe API + mediamtx (+ agente de análise) a
// partir do código QUE VAI NO PACOTE (`resources/servidor`). Fora dos arquivos do app não roda nada.
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

let filhos = [];
let querendo = false;      // true enquanto o servidor DEVE estar no ar (liga o reinício automático)
let configAtual = null;

function raizRecursos() { return process.resourcesPath || path.join(__dirname, '..'); }

// O código do servidor embutido no instalador (extraResources -> resources/servidor).
function servidorEmbutido() {
  const pasta = path.join(raizRecursos(), 'servidor');
  return fs.existsSync(path.join(pasta, 'ground', 'api.py')) ? pasta : '';
}

// O repositório em uso: o do config.json (bancada/engenharia) ou o embutido no pacote (cliente).
function repoDe(config) {
  const pedido = String(((config || {}).servidorLocal || {}).repo || '').trim() || String(process.env.LECSOR_REPO || '').trim();
  if (pedido && fs.existsSync(path.join(pedido, 'ground', 'api.py'))) return pedido;
  return servidorEmbutido();
}

// O mesmo interpretador roda a API e o repasse do mediamtx (`runOnAvailable: python ground/repasse.py`).
function pythonDe(repo) {
  const candidatos = [
    process.env.LECSOR_PYTHON,
    repo ? path.join(repo, '.venv', 'Scripts', 'python.exe') : '',
    path.join(raizRecursos(), 'servidor', 'python', 'python.exe'),   // embutido no instalador
    path.join(__dirname, '..', 'tools', 'python', 'python.exe')      // bancada
  ];
  for (const c of candidatos) if (c && fs.existsSync(c)) return c;
  return 'python';
}

// O ffmpeg embutido no instalador (resources/ffmpeg/ffmpeg.exe). É ele que faz a máquina listar e
// capturar câmera SEM depender de instalação manual.
function ffmpegDe() {
  const exe = path.join(raizRecursos(), 'ffmpeg', process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg');
  return fs.existsSync(exe) ? exe : '';
}

// Ambiente gravado no pacote (perfil do papel): Supabase, token de ingestao e embarcacao. Fica
// FORA do git e DENTRO do instalador — e' o que faz o PC nascer configurado (plug & play), sem
// ninguem digitar chave nem endereco. Nenhum valor de segredo entra em log.
function ambienteDoPacote(repo) {
  try {
    const p = path.join(repo || '', 'ambiente.json');
    if (!repo || !fs.existsSync(p)) return {};
    const d = JSON.parse(fs.readFileSync(p, 'utf8'));
    return (d && typeof d === 'object' && !Array.isArray(d)) ? d : {};
  } catch (e) {
    return {};
  }
}

// Ambiente dos processos filhos: destino do repasse, ffmpeg e python embutidos (o mediamtx chama
// `python ground/repasse.py`, então a pasta do python precisa estar no PATH dele também).
function amb(env, config, python) {
  // o que veio no pacote primeiro; o ambiente de quem já está rodando por cima (bancada manda)
  const saida = Object.assign({}, ambienteDoPacote(repoDe(config)), env || {});
  const destino = String(((config || {}).destinoSrt) || '').trim();
  if (destino) saida.LECSOR_DESTINO_SRT = destino;
  else delete saida.LECSOR_DESTINO_SRT;
  const sep = process.platform === 'win32' ? ';' : ':';
  const ff = ffmpegDe();
  if (ff) {
    saida.LECSOR_FFMPEG = ff;
    saida.LECSOR_FFPROBE = path.join(path.dirname(ff), 'ffprobe' + path.extname(ff));
    saida.PATH = path.dirname(ff) + sep + (saida.PATH || '');
  }
  if (python && python !== 'python') {
    saida.LECSOR_PYTHON = python;
    saida.PATH = path.dirname(python) + sep + (saida.PATH || '');
  }
  return saida;
}

// A analise local (detector ONNX) precisa de numpy/onnxruntime, que o Python embutido NAO traz.
// Sem eles o agente morre no import — melhor nao subir e dizer, do que reiniciar em loop.
function temAnalise(python) {
  const r = spawnSync(python, ['-c', 'import numpy, onnxruntime'], { encoding: 'utf8', timeout: 60000 });
  return !r.error && r.status === 0;
}

function faltando(repo, python) {
  const precisos = [
    ['ground/api.py', path.join(repo, 'ground', 'api.py')],
    ['ground/mediamtx.yml', path.join(repo, 'ground', 'mediamtx.yml')],
    ['ground/repasse.py', path.join(repo, 'ground', 'repasse.py')],
    ['tools/mediamtx/mediamtx.exe', path.join(repo, 'tools', 'mediamtx', 'mediamtx.exe')]
  ];
  const falta = precisos.filter(([, p]) => !fs.existsSync(p)).map(([n]) => n);
  if (python === 'python') falta.push('python (nem embutido no app, nem no PATH)');
  return falta;
}

let analiseAtual = '';

function subir(config) {
  configAtual = config || configAtual || {};
  const repo = repoDe(configAtual);
  if (!repo) {
    return { erro: 'não achei o código do servidor: nem a pasta embutida no aplicativo (resources/servidor) nem a pasta indicada em servidorLocal.repo' };
  }
  const python = pythonDe(repo);
  const falta = faltando(repo, python);
  if (falta.length) return { erro: 'faltando no servidor: ' + falta.join(', ') };
  parar();
  const logs = path.join(repo, 'desktop-logs');
  fs.mkdirSync(logs, { recursive: true });
  const env = amb(process.env, configAtual, python);
  analiseAtual = '';
  const item = (nome, comando, args, cwd) => {
    const p = spawn(comando, args, { cwd, env, shell: false });
    p.stdout.pipe(fs.createWriteStream(path.join(logs, nome + '.log'), { flags: 'a' }));
    p.stderr.pipe(fs.createWriteStream(path.join(logs, nome + '-erro.log'), { flags: 'a' }));
    const registro = { nome, comando, args, cwd, p, tentativas: 0 };
    filhos.push(registro);
    // Reinício automático: o servidor do PC de captura não pode morrer sozinho no meio do turno.
    // Com limite: processo que morre sempre (dependência ausente, porta tomada) para de ser
    // ressuscitado e fica registrado no log, em vez de girar para sempre.
    p.on('exit', (codigo) => {
      if (!querendo || !filhos.includes(registro)) return;
      if (registro.tentativas >= 3) {
        fs.appendFileSync(path.join(logs, nome + '-erro.log'),
          `[app] ${nome} desligado depois de 3 tentativas (codigo ${codigo})\n`);
        return;
      }
      registro.tentativas += 1;
      fs.appendFileSync(path.join(logs, nome + '-erro.log'),
        `[app] ${nome} saiu (codigo ${codigo}) — subindo de novo (${registro.tentativas}/3)\n`);
      setTimeout(() => {
        if (!querendo || !filhos.includes(registro)) return;
        const novo = spawn(comando, args, { cwd, env, shell: false });
        novo.stdout.pipe(fs.createWriteStream(path.join(logs, nome + '.log'), { flags: 'a' }));
        novo.stderr.pipe(fs.createWriteStream(path.join(logs, nome + '-erro.log'), { flags: 'a' }));
        registro.p = novo;
      }, 3000);
    });
  };
  let analise = '';
  try {
    item('mediamtx', path.join(repo, 'tools', 'mediamtx', process.platform === 'win32' ? 'mediamtx.exe' : 'mediamtx'),
         [path.join(repo, 'ground', 'mediamtx.yml')], repo);
    item('api', python, [path.join(repo, 'ground', 'api.py'), String((configAtual.servidorLocal || {}).portaApi || 8765)], repo);
    // A captura e o repasse NAO dependem da analise local: ela so entra se o Python tiver as
    // dependencias (numpy/onnxruntime). Fica escrito no log o que foi decidido e por que.
    const agente = path.join(repo, 'analytics', 'agente.py');
    if (!fs.existsSync(agente)) {
      analise = 'analise local: não vem neste pacote';
    } else if (temAnalise(python)) {
      item('agente-analise', python, ['-u', agente, '--perfil', path.join(repo, 'analytics', 'perfis', 'cam-03.json')], repo);
      analise = 'analise local: no ar';
    } else {
      analise = 'analise local: desligada (o Python em uso não tem numpy/onnxruntime) — captura e repasse seguem normais';
    }
    if (analise) fs.appendFileSync(path.join(logs, 'agente-analise.log'), `[app] ${analise}\n`);
  } catch (e) { querendo = false; return { erro: e.message }; }
  querendo = true;
  analiseAtual = analise ? 'servidor: ' + analise : '';
  return { ok: true, subiu: filhos.length, repo, python, analise };
}

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

function parar() {
  querendo = false;
  analiseAtual = '';
  for (const { p } of filhos) { try { p.kill(); } catch (e) {} }
  filhos = [];
}
// Vivo = processo disparado que ainda nao saiu. Contar processo "subido" nao basta: com a porta
// ocupada o mediamtx morre logo depois e a tela dizia "no ar" enquanto nada servia.
function vivos() { return filhos.filter((f) => f.p && f.p.exitCode === null && !f.p.killed); }
function estado() {
  if (!filhos.length) return 'servidor local parado';
  const v = vivos();
  if (!v.length) return 'servidor local PARADO (os processos morreram — veja desktop-logs/*-erro.log)';
  return `servidor local no ar (${v.length} de ${filhos.length} processos)`;
}
// Sonda as portas do servidor local: contar processo vivo nao basta (no Windows duas instancias
// conseguem subir na mesma porta e uma serve nada). Isto diz o que REALMENTE responde.
function sondar(url, ms = 1500) {
  return new Promise((resolve) => {
    const req = http.get(url, (r) => { r.resume(); resolve(r.statusCode || 0); });
    req.on('error', () => resolve(0));
    req.setTimeout(ms, () => { req.destroy(); resolve(0); });
  });
}
async function sondagem(config) {
  const c = config || configAtual || {};
  const porta = (c.servidorLocal || {}).portaApi || 8765;
  const api = await sondar(`http://127.0.0.1:${porta}/api/eu`);
  const mtx = await sondar('http://127.0.0.1:9997/v3/paths/list');
  const linhas = [
    `API local (127.0.0.1:${porta}): ${api ? 'respondeu HTTP ' + api : 'NAO respondeu'}`,
    `mediamtx (127.0.0.1:9997): ${mtx ? 'respondeu HTTP ' + mtx : 'NAO respondeu'}`,
  ];
  const mortos = filhos.filter((f) => !(f.p && f.p.exitCode === null && !f.p.killed));
  if ((api || mtx) && mortos.length) {
    linhas.push('atencao: algo ja responde nessas portas enquanto ' + mortos.map((f) => f.nome).join('/') +
      ' morreu — provavelmente OUTRA instancia deste servidor ja esta rodando nesta maquina.');
  }
  if (!api && !mtx && mortos.length) linhas.push('o servidor NAO subiu de verdade: veja o motivo acima.');
  return { api, mtx, linhas };
}

// Ultima linha de erro do processo — para o estado dizer O MOTIVO, nao so que morreu.
function ultimaLinhaErro(nome, repo) {
  try {
    const linhas = fs.readFileSync(path.join(repo, 'desktop-logs', nome + '-erro.log'), 'utf8')
      .split('\n').filter((l) => l.trim());
    return linhas.length ? linhas[linhas.length - 1].slice(0, 200) : '';
  } catch (e) { return ''; }
}
function detalhe(config) {
  const c = config || configAtual || {};
  const destino = String(c.destinoSrt || '').trim();
  const repo = repoDe(c);
  const python = repo ? pythonDe(repo) : '(sem repo)';
  const linhas = [
    `esta maquina: ${require('os').hostname()}`,
    `endereco em uso (base): ${c.base || '(nao definido)'}`,
    `servidor: ${repo ? repo + (repo === servidorEmbutido() ? ' (embutido no aplicativo)' : ' (do config.json)') : 'NAO ENCONTRADO'}`,
    `python: ${python}`
  ];
  for (const f of filhos) {
    const vivo = f.p && f.p.exitCode === null && !f.p.killed;
    if (vivo) { linhas.push(`${f.nome}: pid ${f.p.pid} (vivo)`); continue; }
    const motivo = ultimaLinhaErro(f.nome, repo) || 'sem linha no log de erro';
    linhas.push(`${f.nome}: MORREU (codigo ${f.p && f.p.exitCode}) — ${motivo}`);
  }
  linhas.push(ffmpegInfo());
  linhas.push(`repasse para o lado terra: ${destino || '(nada — so esta maquina)'}`);
  return linhas.join('\n');
}

module.exports = { subir, parar, estado, detalhe, vivos, sondagem, sondar, amb, pythonDe, ffmpegDe, repoDe, servidorEmbutido, raizRecursos };
