// Servidor local dentro do aplicativo: quando a maquina for o lado terra, o proprio app
// sobe API + mediamtx + agente de analise. Fora dos arquivos do app nao roda nada.
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

let filhos = [];
function subir(config) {
  const repo = (config.servidorLocal && config.servidorLocal.repo) || process.env.LECSOR_REPO || '';
  if (!repo || !fs.existsSync(repo)) {
    return { erro: 'informe a pasta do repositorio (config.json: servidorLocal.repo)' };
  }
  parar();
  const logs = path.join(repo, 'desktop-logs');
  fs.mkdirSync(logs, { recursive: true });
  const item = (nome, comando, args, cwd) => {
    const p = spawn(comando, args, { cwd, env: process.env, shell: false });
    p.stdout.pipe(fs.createWriteStream(path.join(logs, nome + '.log'), { flags: 'a' }));
    p.stderr.pipe(fs.createWriteStream(path.join(logs, nome + '-erro.log'), { flags: 'a' }));
    filhos.push({ nome, p });
  };
  try {
    item('mediamtx', path.join(repo, 'tools', 'mediamtx', 'mediamtx.exe'), [path.join(repo, 'ground', 'mediamtx.yml')], repo);
    item('api', 'python', [path.join(repo, 'ground', 'api.py'), String((config.servidorLocal || {}).portaApi || 8765)], repo);
    item('agente-analise', path.join(repo, '.venv', 'Scripts', 'python.exe'),
         ['-u', path.join(repo, 'analytics', 'agente.py'), '--perfil', path.join(repo, 'analytics', 'perfis', 'cam-03.json')], repo);
  } catch (e) { return { erro: e.message }; }
  return { ok: true, subiu: filhos.length };
}
function parar() { for (const { p } of filhos) { try { p.kill(); } catch (e) {} } filhos = []; }
function estado() { return filhos.length ? `servidor local no ar (${filhos.length} processos)` : 'servidor local parado'; }
function detalhe() { return filhos.map((f) => `${f.nome}: pid ${f.p.pid}`).join('\n') || 'nada rodando pelo aplicativo'; }
module.exports = { subir, parar, estado, detalhe };
