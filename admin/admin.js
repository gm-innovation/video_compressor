/* Admin / operacao LECSOR: painel do projeto (modulo §6), frota, analises, documentos e auditoria. */
const estado = { dados: null, embarcacoes: [], cameras: [], timer: null };

const $ = (id) => document.getElementById(id);
const limpar = (el) => { while (el.firstChild) el.removeChild(el.firstChild); };
const esc = (s) => String(s === null || s === undefined ? '' : s);

async function api(rota, opcoes) {
  const r = await fetch(rota, Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } }, opcoes));
  const texto = await r.text();
  let corpo = null;
  try { corpo = texto ? JSON.parse(texto) : null; } catch (e) { corpo = { bruto: texto }; }
  return { ok: r.ok, status: r.status, corpo };
}

function tabela(el, colunas, linhas, vazio) {
  limpar(el);
  const thead = document.createElement('thead'); const tr = document.createElement('tr');
  for (const c of colunas) { const th = document.createElement('th'); th.textContent = c.rotulo; tr.appendChild(th); }
  thead.appendChild(tr); el.appendChild(thead);
  const tbody = document.createElement('tbody');
  if (!linhas.length) {
    const t = document.createElement('tr'); const td = document.createElement('td');
    td.colSpan = colunas.length; td.textContent = vazio || 'nada registrado ainda'; t.appendChild(td); tbody.appendChild(t);
  }
  for (const l of linhas) {
    const t = document.createElement('tr');
    for (const c of colunas) {
      const td = document.createElement('td');
      const v = c.valor ? c.valor(l) : l[c.campo];
      if (v instanceof Node) td.appendChild(v); else td.textContent = esc(v);
      t.appendChild(td);
    }
    tbody.appendChild(t);
  }
  el.appendChild(tbody);
}

function cartao(titulo, valor, nota) {
  const d = document.createElement('div'); d.className = 'cartao';
  const h = document.createElement('div'); h.style.fontSize = '12.5px'; h.style.color = '#475569'; h.textContent = titulo;
  const v = document.createElement('div'); v.style.fontSize = '26px'; v.style.fontWeight = '700'; v.textContent = valor;
  const n = document.createElement('div'); n.style.fontSize = '12px'; n.style.color = '#64748b'; n.textContent = nota || '';
  d.appendChild(h); d.appendChild(v); d.appendChild(n); return d;
}

async function entrar(ev) {
  ev.preventDefault();
  const d = await api('/api/entrar', { method: 'POST', body: JSON.stringify({ email: $('email').value, senha: $('senha').value }) });
  if (!d.ok) { const e = $('entrada-erro'); e.textContent = (d.corpo && d.corpo.erro) || 'não foi possível entrar'; e.classList.remove('oculto'); return; }
  if (d.corpo.papel === 'cliente') { const e = $('entrada-erro'); e.textContent = 'esta conta é de cliente: use a tela do cliente (/app)'; e.classList.remove('oculto'); return; }
  await abrir();
}

async function abrir() {
  const eu = await api('/api/eu');
  if (!eu.corpo || !eu.corpo.autenticado) return;
  if (eu.corpo.papel === 'cliente') return;
  $('entrada').classList.add('oculto'); $('painel').classList.remove('oculto'); $('sair').classList.remove('oculto');
  $('quem').textContent = `${eu.corpo.nome} · ${eu.corpo.papel}`;
  await atualizar();
  if (!estado.timer) estado.timer = setInterval(atualizar, 10000);
}

async function atualizar() {
  const d = await api('/api/resumo');
  if (!d.ok) return;
  estado.dados = d.corpo;
  const em = await api('/api/embarcacoes');
  estado.embarcacoes = (em.corpo && em.corpo.embarcacoes) || [];
  const cs = await api('/api/cameras');
  estado.cameras = (cs.corpo && cs.corpo.cameras) || [];
  const doc = await api('/api/documentos');
  if (doc.corpo && doc.corpo.documentos) estado.dados.documentos = doc.corpo.documentos;
  desenhar();
}

function desenhar() {
  const d = estado.dados;
  const fases = d.fases || [];
  const c = $('cartoes'); limpar(c);
  const concluidas = fases.filter((f) => f.status === 'concluida').length;
  const emAndamento = fases.filter((f) => f.status === 'em andamento').length;
  c.appendChild(cartao('Fases concluídas', `${concluidas}/${fases.length}`, 'cada fase só fecha com evidência'));
  c.appendChild(cartao('Medições registradas', (d.medicoes || []).length, 'valor + fonte + data + hardware + comando'));
  c.appendChild(cartao('Decisões (ADR)', (d.decisoes || []).length, 'registradas pelo próprio sistema'));
  c.appendChild(cartao('Evidências', (d.evidencias || []).length, 'arquivo anexado a uma fase'));
  c.appendChild(cartao('Câmeras no ar', `${estado.cameras.filter((x) => x.no_ar).length}/${estado.cameras.length}`, 'estado lido do lado terra'));
  c.appendChild(cartao('Eventos de análise', (d.eventos || []).length, 'Fase 5 — sobe evento, não vídeo'));

  tabela($('tab-fases'), [
    { rotulo: 'Fase', campo: 'nome' }, { rotulo: 'Prio', campo: 'prioridade' }, { rotulo: 'Status', campo: 'status' },
    { rotulo: 'Critério de aceite', campo: 'criterio_aceite' }, { rotulo: 'Evidência', campo: 'evidencia' }
  ], fases, 'nenhuma fase cadastrada');
  tabela($('tab-evidencias'), [{ rotulo: 'Fase', campo: 'fase_id' }, { rotulo: 'Caminho', campo: 'caminho' },
    { rotulo: 'Descrição', campo: 'descricao' }, { rotulo: 'Data', campo: 'data' }], d.evidencias || []);
  tabela($('tab-medicoes'), [{ rotulo: 'Valor', campo: 'valor' }, { rotulo: 'Fonte', campo: 'fonte' },
    { rotulo: 'Data', campo: 'data' }, { rotulo: 'Hardware/versão', campo: 'hardware_versao' },
    { rotulo: 'Comando', campo: 'comando' }], d.medicoes || []);
  tabela($('tab-decisoes'), [{ rotulo: 'Data', campo: 'data' }, { rotulo: 'Título', campo: 'titulo' },
    { rotulo: 'Decisão', campo: 'texto' }, { rotulo: 'Autor', campo: 'autor' }], d.decisoes || [], 'nenhuma decisão registrada');
  tabela($('tab-embarcacoes'), [{ rotulo: 'Embarcação', campo: 'nome' }, { rotulo: 'Cliente', campo: 'cliente_id' },
    { rotulo: 'IMO', campo: 'imo' }, { rotulo: 'Estado', campo: 'estado' }], estado.embarcacoes);
  tabela($('tab-cameras'), [{ rotulo: 'Câmera', campo: 'rotulo' }, { rotulo: 'Embarcação', campo: 'embarcacao_id' },
    { rotulo: 'No ar', valor: (l) => (l.no_ar ? 'sim' : 'não') }, { rotulo: 'Fluxo', valor: (l) => (l.tracks || []).join('/') },
    { rotulo: 'Encoder', valor: (l) => { const e = l.encoder || {}; return [e.codec, e.resolucao, e.fps ? e.fps + ' fps' : '', e.bitrate].filter(Boolean).join(' · '); } },
    { rotulo: 'Leitores', campo: 'leitores' }], estado.cameras);
  tabela($('tab-contagens'), [{ rotulo: 'Câmera', campo: 'camera_id' }, { rotulo: 'Janela', valor: (l) => esc(l.janela_inicio) + ' → ' + esc(l.janela_fim) },
    { rotulo: 'Entrou', campo: 'entrou' }, { rotulo: 'Saiu', campo: 'saiu' }, { rotulo: 'Pico', campo: 'pico' },
    { rotulo: 'Fonte', campo: 'fonte' }], d.contagens || [], 'sem contagem: o agente de análise (Fase 5) ainda não está a bordo');
  tabela($('tab-eventos'), [{ rotulo: 'Câmera', campo: 'camera_id' }, { rotulo: 'Tipo', campo: 'tipo' },
    { rotulo: 'Início', campo: 'inicio' }, { rotulo: 'Fim', campo: 'fim' }, { rotulo: 'Confiança', campo: 'confianca' },
    { rotulo: 'Clipe', campo: 'clipe' }], d.eventos || [], 'sem evento registrado');
  tabela($('tab-documentos'), [{ rotulo: 'Documento', campo: 'titulo' }, { rotulo: 'Versão', campo: 'versao' },
    { rotulo: 'Status', campo: 'status' }, { rotulo: 'Atualizado', campo: 'atualizado_em' },
    { rotulo: 'PDF', valor: (l) => { const a = document.createElement('a'); a.href = '/api/relatorios/' + l.slug + '.pdf'; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'exportar PDF'; return a; } }],
    d.documentos || []);
  tabela($('tab-auditoria'), [{ rotulo: 'Quando', campo: 'em' }, { rotulo: 'Quem', valor: (l) => l.usuario_nome || l.email },
    { rotulo: 'Ação', campo: 'acao' }, { rotulo: 'Alvo', campo: 'alvo' }, { rotulo: 'IP', campo: 'ip' }], d.auditoria || []);
  desenharOperador();
}

function desenharOperador() {
  const g = $('grade-ops');
  const visiveis = estado.cameras.slice(0, 4);
  const ids = visiveis.map((c) => c.id);
  for (const antigo of Array.from(g.children)) {
    if (!ids.includes(antigo.getAttribute('data-cam'))) { window.Video.parar(antigo.getAttribute('data-cam')); antigo.remove(); }
  }
  for (const c of visiveis) {
    if (g.querySelector(`[data-cam="${c.id}"]`)) continue;
    const cartaoEl = document.createElement('div'); cartaoEl.className = 'cam'; cartaoEl.setAttribute('data-cam', c.id);
    const barra = document.createElement('div'); barra.className = 'barra';
    const nome = document.createElement('span'); nome.className = 'nome'; nome.textContent = c.rotulo;
    const dir = document.createElement('span'); dir.className = 'dir';
    const p = document.createElement('span'); p.id = 'estado-' + c.id; p.className = 'pill ' + (c.no_ar ? 'no-ar' : 'queda');
    p.textContent = c.no_ar ? 'no ar (WebRTC)' : 'fora do ar';
    dir.appendChild(p); barra.appendChild(nome); barra.appendChild(dir);
    const v = document.createElement('video'); v.id = 'v-op-' + c.id; v.muted = true; v.autoplay = true; v.playsInline = true; v.controls = true;
    cartaoEl.appendChild(barra); cartaoEl.appendChild(v); g.appendChild(cartaoEl);
    window.Video.ligar(c.id, c.id, v);
  }
}

function recado(id, texto, erro) {
  const el = $(id); el.textContent = texto; el.className = (erro ? 'erro' : 'aviso'); el.classList.remove('oculto');
}

$('form-entrar').addEventListener('submit', entrar);
$('sair').addEventListener('click', async () => { await api('/api/sair', { method: 'POST' }); location.reload(); });
$('abas').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-aba]');
  if (!b) return;
  document.querySelectorAll('#abas button').forEach((x) => x.classList.remove('on'));
  b.classList.add('on');
  document.querySelectorAll('[data-tela]').forEach((t) => t.classList.toggle('oculto', t.dataset.tela !== b.dataset.aba));
});
$('form-medicao').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const corpo = { valor: $('m-valor').value, fonte: $('m-fonte').value, data: $('m-data').value,
                  hardware_versao: $('m-hw').value, comando: $('m-comando').value, fase_id: 'fase-1a' };
  const d = await api('/api/medicoes', { method: 'POST', body: JSON.stringify(corpo) });
  recado('medicao-recado', d.ok ? 'medição gravada (id ' + d.corpo.id + ')' : 'recusada: ' + JSON.stringify(d.corpo), !d.ok);
  await atualizar();
});
$('form-decisao').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const d = await api('/api/decisoes', { method: 'POST', body: JSON.stringify({ titulo: $('d-titulo').value, data: $('d-data').value, texto: $('d-texto').value }) });
  recado('decisao-recado', d.ok ? 'decisão registrada (id ' + d.corpo.id + ')' : 'recusada: ' + JSON.stringify(d.corpo), !d.ok);
  await atualizar();
});
function relogio() { const d = new Date(); const p = (n) => String(n).padStart(2, '0');
  $('relogio').textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; }
setInterval(relogio, 1000); relogio();
$('d-data').value = new Date().toISOString().slice(0, 10);
$('m-data').value = new Date().toISOString().slice(0, 10);
$('m-hw').value = 'bancada (GPU/driver/versao do binario)';
abrir();
