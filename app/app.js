/* Front do cliente: entrar, escolher embarcacao, acompanhar as cameras ao vivo. */
const estado = { usuario: null, embarcacoes: [], cameras: [], embarcacaoId: null, layout: 4, temporizador: null };

const $ = (id) => document.getElementById(id);
const limpar = (el) => { while (el.firstChild) el.removeChild(el.firstChild); };

function relogio() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  $('relogio').textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

async function api(rota, opcoes) {
  const r = await fetch(rota, Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } }, opcoes));
  const texto = await r.text();
  let corpo = null;
  try { corpo = texto ? JSON.parse(texto) : null; } catch (e) { corpo = { bruto: texto }; }
  return { ok: r.ok, status: r.status, corpo };
}

async function entrar(ev) {
  ev.preventDefault();
  const d = await api('/api/entrar', { method: 'POST', body: JSON.stringify({ email: $('email').value, senha: $('senha').value }) });
  if (!d.ok) {
    const e = $('entrada-erro'); e.textContent = (d.corpo && d.corpo.erro) || 'não foi possível entrar'; e.classList.remove('oculto');
    return;
  }
  await abrirPainel();
}

async function abrirPainel() {
  const eu = await api('/api/eu');
  if (!eu.corpo || !eu.corpo.autenticado) return;
  estado.usuario = eu.corpo;
  $('entrada').classList.add('oculto');
  $('painel').classList.remove('oculto');
  $('sair').classList.remove('oculto');
  $('quem').textContent = `${eu.corpo.nome} · ${eu.corpo.papel}`;
  const em = await api('/api/embarcacoes');
  estado.embarcacoes = (em.corpo && em.corpo.embarcacoes) || [];
  limpar($('embarcacao'));
  for (const e of estado.embarcacoes) {
    const o = document.createElement('option');
    o.value = e.id; o.textContent = e.nome + (e.imo ? ` (IMO ${e.imo})` : '');
    $('embarcacao').appendChild(o);
  }
  if (estado.embarcacoes.length) {
    estado.embarcacaoId = estado.embarcacoes[0].id;
    await carregarCameras();
  }
  if (!estado.temporizador) estado.temporizador = setInterval(carregarCameras, 5000);
}

async function carregarCameras() {
  if (!estado.embarcacaoId) return;
  const d = await api('/api/cameras?embarcacao=' + encodeURIComponent(estado.embarcacaoId));
  const cameras = (d.corpo && d.corpo.cameras) || [];
  const iguais = cameras.length === estado.cameras.length &&
    cameras.every((c, i) => estado.cameras[i] && estado.cameras[i].id === c.id);
  const nomes = estado.embarcacoes.find((e) => e.id === estado.embarcacaoId);
  $('emb-nome').textContent = nomes ? nomes.nome : '';
  const noAr = cameras.filter((c) => c.no_ar).length;
  $('resumo-topo').textContent = `${cameras.length} câmera(s) · ${noAr} no ar · atualizado ${new Date().toLocaleTimeString('pt-BR')}`;
  estado.cameras = cameras;
  $('sem-camera').classList.toggle('oculto', cameras.length > 0);
  if (iguais) { pintarEstados(); return; }
  montarGrade();
}

function pintarEstados() {
  for (const c of estado.cameras) {
    const el = $('estado-' + c.id);
    // o player manda no texto enquanto negocia; o rodape de dados é sempre atualizado
    if (el && !/^(no ar|reconectando|conectando|reserva)/.test(el.textContent)) {
      el.textContent = c.no_ar ? 'no ar (WebRTC)' : 'fora do ar';
      el.className = 'pill ' + (c.no_ar ? 'no-ar' : 'queda');
    }
    const pe = $('pe-' + c.id);
    if (pe) pe.textContent = descrever(c);
  }
}

function descrever(c) {
  const e = c.encoder || {};
  const partes = [];
  if (e.codec) partes.push(e.codec);
  if (e.resolucao) partes.push(e.resolucao);
  if (e.fps) partes.push(e.fps + ' fps');
  if (e.bitrate) partes.push('encode ' + e.bitrate);
  if (c.tracks && c.tracks.length) partes.push(c.tracks.join('/'));
  partes.push((c.leitores || 0) + ' leitor(es)');
  return partes.join(' · ');
}

function montarGrade() {
  const g = $('grade');
  const visiveis = estado.cameras.slice(0, estado.layout);
  const ids = visiveis.map((c) => c.id);
  for (const antigo of Array.from(g.children)) {
    const idAntigo = antigo.getAttribute('data-cam');
    if (!ids.includes(idAntigo)) { window.Video.parar(idAntigo); antigo.remove(); }
  }
  g.className = 'grade cols-' + (estado.layout === 1 ? '1' : estado.layout === 2 ? '2' : estado.layout === 4 ? '2' : '3');
  visiveis.forEach((c, i) => {
    let cartao = g.querySelector(`[data-cam="${c.id}"]`);
    if (!cartao) {
      cartao = document.createElement('div');
      cartao.className = 'cam'; cartao.setAttribute('data-cam', c.id);
      const barra = document.createElement('div'); barra.className = 'barra';
      const nome = document.createElement('span'); nome.className = 'nome'; nome.textContent = c.rotulo;
      const dir = document.createElement('span'); dir.className = 'dir';
      const estadoPill = document.createElement('span');
      estadoPill.id = 'estado-' + c.id; estadoPill.className = 'pill ' + (c.no_ar ? 'no-ar' : 'queda');
      estadoPill.textContent = c.no_ar ? 'no ar (WebRTC)' : 'fora do ar';
      const tela = document.createElement('button'); tela.className = 'secundaria'; tela.textContent = 'tela cheia';
      dir.appendChild(estadoPill); dir.appendChild(tela);
      barra.appendChild(nome); barra.appendChild(dir);
      const v = document.createElement('video');
      v.id = 'v-' + c.id; v.muted = true; v.autoplay = true; v.playsInline = true; v.controls = true;
      tela.onclick = () => (v.requestFullscreen ? v.requestFullscreen() : v.webkitEnterFullscreen());
      const pe = document.createElement('div'); pe.className = 'pe'; pe.id = 'pe-' + c.id; pe.textContent = descrever(c);
      cartao.appendChild(barra); cartao.appendChild(v); cartao.appendChild(pe);
      g.appendChild(cartao);
      window.Video.ligar(c.id, c.id, v);
    } else {
      g.appendChild(cartao);  // so reordena; o player NAO e recriado
    }
  });
}

$('form-entrar').addEventListener('submit', entrar);
$('embarcacao').addEventListener('change', (ev) => { estado.embarcacaoId = ev.target.value; estado.cameras = []; carregarCameras(); });
document.querySelectorAll('nav.abas button[data-layout]').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('nav.abas button[data-layout]').forEach((x) => x.classList.remove('on'));
  b.classList.add('on'); estado.layout = parseInt(b.dataset.layout, 10); montarGrade();
}));
$('sair').addEventListener('click', async () => { await api('/api/sair', { method: 'POST' }); location.reload(); });
setInterval(relogio, 1000); relogio();
abrirPainel();
