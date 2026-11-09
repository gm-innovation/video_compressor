/* Admin do projeto e do sistema: acompanhamento (§6) + administracao (clientes, embarcacoes,
   cameras, usuarios, analises, auditoria, saude). Le e escreve tudo pela API do produto. */
const A = { usuario: null, resumo: null, clientes: [], usuarios: [], sistema: null, cameras: [], embarcacoes: [], tela: 'painel', timer: null };
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

/* --------------------------------------------------------- entrada */
async function entrar(ev) {
  ev.preventDefault();
  const d = await api('/api/entrar', { method: 'POST', body: JSON.stringify({ email: $('email').value, senha: $('senha').value }) });
  if (!d.ok) { const e = $('entrada-erro'); e.textContent = (d.corpo && d.corpo.erro) || 'não foi possível entrar'; e.classList.remove('oculto'); return; }
  if (d.corpo.papel === 'cliente') { const e = $('entrada-erro'); e.textContent = 'esta conta é de cliente: use a tela do cliente (/app)'; e.classList.remove('oculto'); return; }
  await abrir();
}

async function abrir() {
  const eu = await api('/api/eu');
  if (!eu.corpo || !eu.corpo.autenticado || eu.corpo.papel === 'cliente') return;
  A.usuario = eu.corpo;
  $('entrada').classList.add('oculto'); $('sistema').classList.remove('oculto');
  $('conta-email').textContent = eu.corpo.email;
  $('conta-papel').textContent = eu.corpo.papel === 'admin' ? 'Administrador do sistema' : 'Operação';
  $('iniciais').textContent = (eu.corpo.nome.split(/\s+/).filter((p) => p.length > 2).slice(0, 2).map((p) => p[0]).join('') || 'LC').toUpperCase();
  await atualizar();
  // Nao redesenhar por cima do que o usuario esta digitando: era isso que apagava o formulario de
  // envio (link + rotulo) a cada 15 s e parecia que o app "voltava ao estado anterior".
  if (!A.timer) A.timer = setInterval(() => { if (!digitandoNaTela()) atualizar(); }, 15000);
}

function digitandoNaTela() {
  const a = document.activeElement;
  return !!(a && a.closest && a.closest('#tela') && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
}

async function atualizar() {
  const rs = await api('/api/resumo'); if (rs.ok) A.resumo = rs.corpo;
  const em = await api('/api/embarcacoes'); A.embarcacoes = (em.corpo && em.corpo.embarcacoes) || [];
  const cm = await api('/api/cameras'); A.cameras = (cm.corpo && cm.corpo.cameras) || [];
  if (A.usuario && A.usuario.papel === 'admin') {
    const cl = await api('/api/clientes'); A.clientes = (cl.corpo && cl.corpo.clientes) || [];
    const us = await api('/api/usuarios'); A.usuarios = (us.corpo && us.corpo.usuarios) || [];
    const si = await api('/api/sistema'); if (si.ok) A.sistema = si.corpo.sistema;
  } else {
    const cl = await api('/api/clientes'); A.clientes = (cl.corpo && cl.corpo.clientes) || [];
  }
  desenhar();
}

/* --------------------------------------------------------- utilidades de tela */
function tabela(colunas, linhas, vazio) {
  const rolagem = document.createElement('div'); rolagem.className = 'rolagem';
  const t = document.createElement('table'); t.className = 'tabela';
  const th = document.createElement('thead'); const tr = document.createElement('tr');
  for (const c of colunas) { const e = document.createElement('th'); e.textContent = c.rotulo; tr.appendChild(e); }
  th.appendChild(tr); t.appendChild(th);
  const tb = document.createElement('tbody');
  if (!linhas.length) {
    const tr2 = document.createElement('tr'); const td = document.createElement('td');
    td.colSpan = colunas.length; td.textContent = vazio; td.style.color = 'var(--texto2)'; tr2.appendChild(td); tb.appendChild(tr2);
  }
  for (const l of linhas) {
    const tr2 = document.createElement('tr');
    for (const c of colunas) {
      const td = document.createElement('td');
      const v = c.valor ? c.valor(l) : l[c.campo];
      if (v instanceof Node) td.appendChild(v); else td.textContent = esc(v);
      tr2.appendChild(td);
    }
    tb.appendChild(tr2);
  }
  t.appendChild(tb); rolagem.appendChild(t); return rolagem;
}

function cartao(rot, val, nota) {
  const d = document.createElement('div'); d.className = 'cartao-dado';
  const r = document.createElement('div'); r.className = 'rot'; r.textContent = rot;
  const v = document.createElement('div'); v.className = 'val'; v.textContent = val;
  const n = document.createElement('div'); n.className = 'nota'; n.textContent = nota || '';
  d.appendChild(r); d.appendChild(v); d.appendChild(n); return d;
}

function campo(pai, id, rotulo, valor) {
  const d = document.createElement('div');
  const l = document.createElement('label'); l.textContent = rotulo; l.setAttribute('for', id);
  const i = document.createElement('input'); i.id = id; i.value = valor || '';
  d.appendChild(l); d.appendChild(i); pai.appendChild(d); return i;
}

function botao(texto, classe, aoClicar) {
  const b = document.createElement('button'); b.className = 'acao ' + (classe || ''); b.textContent = texto;
  b.onclick = aoClicar; return b;
}

/* O recado precisa sobreviver ao re-render da tela (a escrita atualiza os dados e redesenha):
   por isso ele e inserido DEPOIS do redesenho, no topo da area da tela. */
function mostrarRecado(texto, erro, senha) {
  const tela = $('tela');
  const d = recado(texto, erro);
  tela.insertBefore(d, tela.firstChild);
  if (senha) {
    const s = document.createElement('div'); s.className = 'senha-once';
    s.textContent = 'senha inicial (aparece uma única vez): ' + senha;
    d.insertAdjacentElement('afterend', s);
  }
}

function recado(texto, erro) {
  const d = document.createElement('div'); d.className = 'recado ' + (erro ? 'ruim' : 'ok'); d.textContent = texto;
  return d;
}

const SUBS = {
  painel: ['Painel do projeto', 'Fases, medições, decisões e estado do link, tudo lido do banco.'],
  fases: ['Fases do projeto', 'Cada fase só fecha com evidência anexada.'],
  medicoes: ['Medições', 'Medição sem valor + fonte + data + hardware/versão + comando é recusada pelo banco.'],
  decisoes: ['Decisões (ADR)', 'O registro vive no sistema, não em arquivo paralelo.'],
  evidencias: ['Evidências', 'Arquivo que sustenta o fechamento de uma fase.'],
  documentos: ['Documentos do projeto', 'O PDF é gerado pelo próprio sistema a partir do documento vigente.'],
  clientes: ['Clientes', 'Empresas (armadores) atendidas pelo sistema.'],
  embarcacoes: ['Embarcações', 'Cada embarcação pertence a um cliente.'],
  cameras: ['Câmeras', 'Câmera do produto aponta para um fluxo publicado; nunca guarda credencial de câmera.'],
  usuarios: ['Usuários', 'Papéis: cliente (vê a própria empresa), operador e administrador.'],
  analises: ['Análises de vídeo', 'Contagem e eventos sobem de bordo (Fase 5) — sem agente a bordo a tela fica vazia.'],
  auditoria: ['Auditoria', 'Quem viu qual câmera, quando — e o que foi negado.'],
  marcas: ['Marcas e zonas', 'A linha de contagem e as zonas de risco que o agente de bordo usa, desenhadas aqui.'],
  envios: ['Enviar vídeo para teste', 'Manda um arquivo ou um link, o sistema codifica, publica em SRT e mede o corte de banda.'],
  saude: ['Saúde do sistema', 'Estado da API, do lado terra e das contagens do banco.']
};

/* --------------------------------------------------------- telas */
function desenhar() {
  const [titulo, sub] = SUBS[A.tela] || SUBS.painel;
  $('titulo-tela').textContent = titulo; $('sub-tela').textContent = sub;
  const tela = $('tela'); limpar(tela);
  if (timerEnvios) { clearInterval(timerEnvios); timerEnvios = null; }
  const despacho = { painel: telaPainel, fases: telaFases, medicoes: telaMedicoes, decisoes: telaDecisoes,
    evidencias: telaEvidencias, documentos: telaDocumentos, clientes: telaClientes, embarcacoes: telaEmbarcacoes,
    cameras: telaCameras, usuarios: telaUsuarios, analises: telaAnalises, marcas: telaMarcas, envios: telaEnvios,
    auditoria: telaAuditoria, saude: telaSaude };
  (despacho[A.tela] || telaPainel)(tela);
}

function telaPainel(t) {
  const d = A.resumo || {};
  const fases = d.fases || [];
  const cartoes = document.createElement('div'); cartoes.className = 'cartoes';
  cartoes.appendChild(cartao('Fases concluídas', `${fases.filter((f) => f.status === 'concluida').length}/${fases.length}`, 'só fecha com evidência'));
  cartoes.appendChild(cartao('Em andamento', fases.filter((f) => f.status === 'em andamento').length, 'fases ativas'));
  cartoes.appendChild(cartao('Medições', (d.medicoes || []).length, 'com fonte e comando'));
  cartoes.appendChild(cartao('Decisões', (d.decisoes || []).length, 'registro do sistema'));
  cartoes.appendChild(cartao('Câmeras no ar', `${A.cameras.filter((c) => c.no_ar).length}/${A.cameras.length}`, 'estado do lado terra'));
  cartoes.appendChild(cartao('Eventos de análise', (d.eventos || []).length, 'Fase 5'));
  t.appendChild(cartoes);
  t.appendChild(tabela([{ rotulo: 'Fase', campo: 'nome' }, { rotulo: 'Prio', campo: 'prioridade' },
    { rotulo: 'Status', campo: 'status' }, { rotulo: 'Critério de aceite', campo: 'criterio_aceite' },
    { rotulo: 'Evidência', campo: 'evidencia' }], fases, 'nenhuma fase cadastrada'));
}

function telaFases(t) {
  const d = A.resumo || {};
  t.appendChild(tabela([{ rotulo: '#', campo: 'numero' }, { rotulo: 'Fase', campo: 'nome' }, { rotulo: 'Prioridade', campo: 'prioridade' },
    { rotulo: 'Status', campo: 'status' }, { rotulo: 'Critério de aceite', campo: 'criterio_aceite' }], d.fases || [], 'nenhuma fase'));
}

function telaMedicoes(t) {
  const caixa = document.createElement('div'); caixa.className = 'caixa-form';
  const h = document.createElement('h2'); h.textContent = 'Registrar medição'; caixa.appendChild(h);
  const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
  const v = campo(linha, 'm-valor', 'Valor', '');
  const f = campo(linha, 'm-fonte', 'Fonte', '');
  const dt_ = campo(linha, 'm-data', 'Data', new Date().toISOString().slice(0, 10));
  const hw = campo(linha, 'm-hw', 'Hardware/versão', 'bancada');
  const cmd = campo(linha, 'm-comando', 'Comando', '');
  const onde = document.createElement('div'); caixa.appendChild(onde);
  caixa.appendChild(botao('Gravar medição', 'marca', async () => {
    const r = await api('/api/medicoes', { method: 'POST', body: JSON.stringify({ valor: v.value, fonte: f.value, data: dt_.value,
      hardware_versao: hw.value, comando: cmd.value, fase_id: 'fase-1a' }) });
    await atualizar();
    mostrarRecado(r.ok ? 'medição gravada (id ' + r.corpo.id + ')' : 'recusada: ' + JSON.stringify(r.corpo), !r.ok);
  }));
  t.appendChild(caixa);
  t.appendChild(tabela([{ rotulo: 'Valor', campo: 'valor' }, { rotulo: 'Fonte', campo: 'fonte' }, { rotulo: 'Data', campo: 'data' },
    { rotulo: 'Hardware/versão', campo: 'hardware_versao' }, { rotulo: 'Comando', campo: 'comando' }], (A.resumo || {}).medicoes || []));
}

function telaDecisoes(t) {
  const caixa = document.createElement('div'); caixa.className = 'caixa-form';
  const h = document.createElement('h2'); h.textContent = 'Registrar decisão (ADR)'; caixa.appendChild(h);
  const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
  const ti = campo(linha, 'd-titulo', 'Título', '');
  const da = campo(linha, 'd-data', 'Data', new Date().toISOString().slice(0, 10));
  const tx = campo(linha, 'd-texto', 'Decisão', '');
  const onde = document.createElement('div'); caixa.appendChild(onde);
  caixa.appendChild(botao('Registrar decisão', 'marca', async () => {
    const r = await api('/api/decisoes', { method: 'POST', body: JSON.stringify({ titulo: ti.value, data: da.value, texto: tx.value }) });
    await atualizar();
    mostrarRecado(r.ok ? 'decisão registrada (id ' + r.corpo.id + ')' : 'recusada: ' + JSON.stringify(r.corpo), !r.ok);
  }));
  t.appendChild(caixa);
  t.appendChild(tabela([{ rotulo: 'Data', campo: 'data' }, { rotulo: 'Título', campo: 'titulo' },
    { rotulo: 'Decisão', campo: 'texto' }, { rotulo: 'Autor', campo: 'autor' }], (A.resumo || {}).decisoes || [], 'nenhuma decisão registrada'));
}

function telaEvidencias(t) {
  t.appendChild(tabela([{ rotulo: 'Fase', campo: 'fase_id' }, { rotulo: 'Caminho', campo: 'caminho' },
    { rotulo: 'Descrição', campo: 'descricao' }, { rotulo: 'Data', campo: 'data' }], (A.resumo || {}).evidencias || []));
}

function telaDocumentos(t) {
  t.appendChild(tabela([{ rotulo: 'Documento', campo: 'titulo' }, { rotulo: 'Versão', campo: 'versao' },
    { rotulo: 'Status', campo: 'status' }, { rotulo: 'Atualizado', campo: 'atualizado_em' },
    { rotulo: 'PDF', valor: (l) => { const a = document.createElement('a'); a.href = '/api/relatorios/' + l.slug + '.pdf';
      a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'exportar PDF'; return a; } }], (A.resumo || {}).documentos || []));
}

function telaClientes(t) {
  if (A.usuario.papel === 'admin') {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Novo cliente (armador)' }));
    const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
    const id = campo(linha, 'c-id', 'Identificador (ex.: armador-x)', '');
    const nome = campo(linha, 'c-nome', 'Nome', '');
    const onde = document.createElement('div'); caixa.appendChild(onde);
    caixa.appendChild(botao('Cadastrar cliente', 'marca', async () => {
      const r = await api('/api/clientes', { method: 'POST', body: JSON.stringify({ id: id.value.trim(), nome: nome.value }) });
      await atualizar();
      mostrarRecado(r.ok ? 'cliente cadastrado: ' + r.corpo.id : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
    }));
    t.appendChild(caixa);
  }
  t.appendChild(tabela([{ rotulo: 'Cliente', campo: 'nome' }, { rotulo: 'Identificador', campo: 'id' },
    { rotulo: 'Embarcações', campo: 'embarcacoes' }, { rotulo: 'Usuários', campo: 'usuarios' },
    { rotulo: 'Ativo', valor: (l) => (l.ativo ? 'sim' : 'não') }], A.clientes, 'nenhum cliente cadastrado'));
}

function telaEmbarcacoes(t) {
  if (A.usuario.papel === 'admin') {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Nova embarcação' }));
    const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
    const id = campo(linha, 'e-id', 'Identificador (ex.: psv-01)', '');
    const cli = campo(linha, 'e-cliente', 'Cliente (identificador)', '');
    const nome = campo(linha, 'e-nome', 'Nome da embarcação', '');
    const imo = campo(linha, 'e-imo', 'IMO', '');
    const onde = document.createElement('div'); caixa.appendChild(onde);
    caixa.appendChild(botao('Cadastrar embarcação', 'marca', async () => {
      const r = await api('/api/embarcacoes', { method: 'POST', body: JSON.stringify({ id: id.value.trim(), cliente_id: cli.value.trim(), nome: nome.value, imo: imo.value }) });
      await atualizar();
      mostrarRecado(r.ok ? 'embarcação cadastrada: ' + r.corpo.id : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
    }));
    t.appendChild(caixa);
  }
  t.appendChild(tabela([{ rotulo: 'Embarcação', campo: 'nome' }, { rotulo: 'Identificador', campo: 'id' },
    { rotulo: 'Cliente', campo: 'cliente_id' }, { rotulo: 'IMO', campo: 'imo' }, { rotulo: 'Estado', campo: 'estado' }],
    A.embarcacoes, 'nenhuma embarcação'));
}

function telaCameras(t) {
  if (A.usuario.papel === 'admin') {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Nova câmera do produto' }));
    const aviso = document.createElement('div'); aviso.className = 'nota'; aviso.style.color = 'var(--texto2)'; aviso.style.fontSize = '12px';
    aviso.textContent = 'A câmera aponta para um fluxo publicado pelo agente de bordo. Credencial de câmera não entra aqui.';
    caixa.appendChild(aviso);
    const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
    const id = campo(linha, 'k-id', 'Identificador da câmera', '');
    const emb = campo(linha, 'k-emb', 'Embarcação (identificador)', '');
    const rot = campo(linha, 'k-rot', 'Rótulo na tela', '');
    const flu = campo(linha, 'k-fluxo', 'Fluxo publicado (ex.: cam-01)', '');
    const loc = campo(linha, 'k-local', 'Local', '');
    const onde = document.createElement('div'); caixa.appendChild(onde);
    caixa.appendChild(botao('Cadastrar câmera', 'marca', async () => {
      const r = await api('/api/cameras', { method: 'POST', body: JSON.stringify({ id: id.value.trim(), embarcacao_id: emb.value.trim(),
        rotulo: rot.value, fluxo_id: flu.value.trim(), local: loc.value }) });
      await atualizar();
      mostrarRecado(r.ok ? 'câmera cadastrada: ' + r.corpo.id : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
    }));
    t.appendChild(caixa);
  }
  t.appendChild(tabela([{ rotulo: 'Câmera', campo: 'rotulo' }, { rotulo: 'Identificador', campo: 'id' },
    { rotulo: 'Embarcação', campo: 'embarcacao_id' }, { rotulo: 'No ar', valor: (l) => (l.no_ar ? 'sim' : 'não') },
    { rotulo: 'Encoder', valor: (l) => { const e = l.encoder || {}; return [e.codec, e.resolucao, e.fps ? e.fps + ' fps' : '', e.bitrate].filter(Boolean).join(' · '); } },
    { rotulo: 'Espectadores', campo: 'leitores' },
    { rotulo: 'Ação', valor: (l) => botao('ativar/desativar', 'mini', async () => {
        const r = await api('/api/cameras/' + encodeURIComponent(l.id) + '/ativo', { method: 'POST', body: JSON.stringify({ ativo: !l.ativo }) });
        if (!r.ok) alert(JSON.stringify(r.corpo)); await atualizar();
      }) }], A.cameras, 'nenhuma câmera cadastrada'));
}

function telaUsuarios(t) {
  if (A.usuario.papel !== 'admin') { t.appendChild(recado('Somente o administrador do sistema vê e cria usuários.', true)); return; }
  const caixa = document.createElement('div'); caixa.className = 'caixa-form';
  caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Novo usuário' }));
  const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
  const email = campo(linha, 'u-email', 'E-mail', '');
  const nome = campo(linha, 'u-nome', 'Nome', '');
  const papel = campo(linha, 'u-papel', 'Papel (cliente | operador | admin)', 'cliente');
  const cli = campo(linha, 'u-cliente', 'Cliente (só para papel cliente)', '');
  const onde = document.createElement('div'); caixa.appendChild(onde);
  caixa.appendChild(botao('Criar usuário', 'marca', async () => {
    const r = await api('/api/usuarios', { method: 'POST', body: JSON.stringify({ email: email.value.trim(), nome: nome.value,
      papel: papel.value.trim(), cliente_id: cli.value.trim() || null }) });
    await atualizar();
    if (r.ok) mostrarRecado('usuário criado: ' + r.corpo.email, false, r.corpo.senha_inicial);
    else mostrarRecado('recusado: ' + JSON.stringify(r.corpo), true);
  }));
  t.appendChild(caixa);
  t.appendChild(tabela([{ rotulo: 'E-mail', campo: 'email' }, { rotulo: 'Nome', campo: 'nome' }, { rotulo: 'Papel', campo: 'papel' },
    { rotulo: 'Cliente', campo: 'cliente_id' }, { rotulo: 'Ativo', valor: (l) => (l.ativo ? 'sim' : 'não') },
    { rotulo: 'Sessões', campo: 'sessoes' }, { rotulo: 'Criado', campo: 'criado_em' },
    { rotulo: 'Ação', valor: (l) => botao(l.ativo ? 'desativar' : 'ativar', 'mini', async () => {
        const r = await api('/api/usuarios/' + encodeURIComponent(l.id) + '/ativo', { method: 'POST', body: JSON.stringify({ ativo: !l.ativo }) });
        if (!r.ok) alert(JSON.stringify(r.corpo)); await atualizar();
      }) }], A.usuarios, 'nenhum usuário'));
}

function telaAnalises(t) {
  const d = A.resumo || {};
  const agentes = d.agentes || [];
  const cart = document.createElement('div'); cart.className = 'cartoes';
  cart.appendChild(cartao('Agentes a bordo', agentes.length, 'um por câmera analisada'));
  cart.appendChild(cartao('No ar agora', agentes.filter((a) => a.estado === 'no ar').length, 'estado do agente'));
  cart.appendChild(cartao('Quadros analisados', agentes.reduce((s, a) => s + (a.quadros || 0), 0), 'soma dos agentes'));
  cart.appendChild(cartao('Quadros por segundo', agentes.length ? (agentes.reduce((s, a) => s + (a.fps || 0), 0) / agentes.length).toFixed(1) : '0', 'média por câmera'));
  cart.appendChild(cartao('Eventos', (d.eventos || []).length, 'últimos 60'));
  t.appendChild(cart);
  t.appendChild(tabela([{ rotulo: 'Câmera', campo: 'camera_id' }, { rotulo: 'Agente', campo: 'nome' },
    { rotulo: 'Modelo', campo: 'modelo' }, { rotulo: 'Estado', campo: 'estado' },
    { rotulo: 'Quadros/s', campo: 'fps' }, { rotulo: 'Quadros', campo: 'quadros' },
    { rotulo: 'Erros', campo: 'erros' }, { rotulo: 'Última mensagem', campo: 'ultimo_visto' }],
    agentes, 'nenhum agente a bordo: o módulo de análise (Fase 5) ainda não está publicado na embarcação'));
  t.appendChild(tabela([{ rotulo: 'Câmera', campo: 'camera_id' }, { rotulo: 'Entrou', campo: 'entrou' },
    { rotulo: 'Saiu', campo: 'saiu' }, { rotulo: 'Pico', campo: 'pico' },
    { rotulo: 'Janela (fim)', campo: 'janela_fim' }, { rotulo: 'Fonte', campo: 'fonte' }],
    d.contagens || [], 'sem contagem registrada'));
  t.appendChild(tabela([{ rotulo: 'Câmera', campo: 'camera_id' }, { rotulo: 'Tipo', campo: 'tipo' },
    { rotulo: 'Início', campo: 'inicio' }, { rotulo: 'Confiança', campo: 'confianca' },
    { rotulo: 'Metadados', campo: 'metadados' }],
    d.eventos || [], 'sem evento registrado'));
}

/* Marcas e zonas: o operador desenha a linha de contagem e a zona de risco; o agente de bordo
   le daqui ao iniciar. Tudo em fracao do quadro (0..1) — nada de endereco nem credencial. */
function telaMarcas(t) {
  if (!(A.usuario.papel === 'admin' || A.usuario.papel === 'operador')) {
    t.appendChild(recado('Só a operação e o administrador desenham as marcas.', true)); return;
  }
  const caixa = document.createElement('div'); caixa.className = 'caixa-form';
  caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Linha de contagem e zona de risco' }));
  const seletor = document.createElement('div'); seletor.className = 'linha-form'; caixa.appendChild(seletor);
  const sel = document.createElement('select'); sel.id = 'mk-camera';
  for (const c of A.cameras) { const o = document.createElement('option'); o.value = c.id; o.textContent = c.rotulo; sel.appendChild(o); }
  const rotSel = document.createElement('div'); rotSel.appendChild(Object.assign(document.createElement('label'), { textContent: 'Câmera' }));
  rotSel.appendChild(sel); seletor.appendChild(rotSel);

  const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
  const vazios = { 'mk-ax': '0.4', 'mk-ay': '0', 'mk-bx': '0.4', 'mk-by': '1', 'mk-znome': 'área de risco', 'mk-zx': '0.1', 'mk-zy': '0.6', 'mk-zl': '0.8', 'mk-za': '0.3', 'mk-zs': '2' };
  const campos = {};
  for (const [id, rot, valor] of [['mk-ax', 'linha A x', vazios['mk-ax']], ['mk-ay', 'linha A y', vazios['mk-ay']],
                                  ['mk-bx', 'linha B x', vazios['mk-bx']], ['mk-by', 'linha B y', vazios['mk-by']],
                                  ['mk-znome', 'zona (nome)', vazios['mk-znome']], ['mk-zx', 'zona x', vazios['mk-zx']],
                                  ['mk-zy', 'zona y', vazios['mk-zy']], ['mk-zl', 'zona largura', vazios['mk-zl']],
                                  ['mk-za', 'zona altura', vazios['mk-za']], ['mk-zs', 'zona segundos', vazios['mk-zs']]]) {
    campos[id] = campo(linha, id, rot, valor);
  }
  const vista = document.createElement('div'); vista.id = 'mk-vista';
  vista.style.cssText = 'position:relative;width:100%;max-width:520px;aspect-ratio:16/9;background:#0b1220;border:1px solid var(--borda2);border-radius:10px;margin:12px 0';
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 100 56.25'); svg.setAttribute('width', '100%'); svg.setAttribute('height', '100%');
  svg.id = 'mk-svg'; vista.appendChild(svg); caixa.appendChild(vista);
  const onde = document.createElement('div'); caixa.appendChild(onde);

  const desenharVista = () => {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const num = (id) => parseFloat(String(campos[id].value).replace(',', '.'));
    const mk = (tag, attrs) => { const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
    const wz = (id) => { const z = A.marcasAbertas || {}; const cz = (z.zonas || [])[0] || {}; return cz; };
    const linhaAberta = (A.marcasAbertas || {}).linha;
    const l = [Number.isFinite(num('mk-ax')) ? num('mk-ax') : (linhaAberta ? linhaAberta.a[0] : 0.4),
               Number.isFinite(num('mk-ay')) ? num('mk-ay') : (linhaAberta ? linhaAberta.a[1] : 0),
               Number.isFinite(num('mk-bx')) ? num('mk-bx') : (linhaAberta ? linhaAberta.b[0] : 0.4),
               Number.isFinite(num('mk-by')) ? num('mk-by') : (linhaAberta ? linhaAberta.b[1] : 1)];
    svg.appendChild(mk('line', { x1: l[0] * 100, y1: l[1] * 56.25, x2: l[2] * 100, y2: l[3] * 56.25,
                                 stroke: '#38bdf8', 'stroke-width': 0.8, 'stroke-dasharray': '2 1.5' }));
    const z = [num('mk-zx'), num('mk-zy'), num('mk-zl'), num('mk-za')];
    if (z.every(Number.isFinite)) svg.appendChild(mk('rect', { x: z[0] * 100, y: z[1] * 56.25, width: z[2] * 100,
      height: z[3] * 56.25, fill: 'rgba(56,189,248,.18)', stroke: '#38bdf8', 'stroke-width': 0.4 }));
  };

  const carregar = async () => {
    const r = await api('/api/analytics/marcas?camera_id=' + encodeURIComponent(sel.value));
    A.marcasAbertas = (r.ok && r.corpo) ? r.corpo : { linha: null, zonas: [] };
    const l = A.marcasAbertas.linha;
    if (l) { campos['mk-ax'].value = l.a[0]; campos['mk-ay'].value = l.a[1]; campos['mk-bx'].value = l.b[0]; campos['mk-by'].value = l.b[1]; }
    const z = (A.marcasAbertas.zonas || [])[0];
    if (z) { campos['mk-znome'].value = z.nome; campos['mk-zx'].value = z.x; campos['mk-zy'].value = z.y;
             campos['mk-zl'].value = z.l; campos['mk-za'].value = z.a; campos['mk-zs'].value = z.segundos; }
    desenharVista();
  };
  sel.addEventListener('change', carregar);
  for (const k in campos) campos[k].addEventListener('input', desenharVista);

  const botoes = document.createElement('div'); botoes.style.display = 'flex'; botoes.style.gap = '8px';
  botoes.appendChild(botao('Salvar marcas', 'marca', async () => {
    const num = (id) => parseFloat(String(campos[id].value).replace(',', '.'));
    const corpo = { camera_id: sel.value, linha: { a: [num('mk-ax'), num('mk-ay')], b: [num('mk-bx'), num('mk-by')] },
      zonas: [{ nome: campos['mk-znome'].value, x: num('mk-zx'), y: num('mk-zy'), l: num('mk-zl'),
                a: num('mk-za'), segundos: num('mk-zs') }] };
    const r = await api('/api/analytics/marcas', { method: 'POST', body: JSON.stringify(corpo) });
    await carregar();
    mostrarRecado(r.ok ? `marcas gravadas em ${sel.value} (o agente lê ao iniciar)` : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
  }));
  botoes.appendChild(botao('Limpar marca', '', async () => {
    const r = await api('/api/analytics/marcas', { method: 'POST', body: JSON.stringify({ camera_id: sel.value, linha: null, zonas: [] }) });
    await carregar();
    mostrarRecado(r.ok ? 'marca removida' : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
  }));
  caixa.appendChild(botoes);
  t.appendChild(caixa);
  caixa.appendChild(onde);
  carregar();
}

/* Envio de video de teste (Fase 5/7): arquivo do computador ou link http(s).
   O encode roda no servidor (ffmpeg libx264 -> SRT no mediamtx); a tela so mostra
   o que a API mede: bitrate de entrada, bitrate de saida, corte, fps e tempo no ar. */
let timerEnvios = null;
const mbps = (k) => (k === null || k === undefined || k === '' ? '—' : (k / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 2 }) + ' Mbps');
const numOu = (v, u) => (v === null || v === undefined || v === '' ? '—' : (Math.round(v * 10) / 10).toLocaleString('pt-BR') + ' ' + (u || ''));

function telaEnvios(t) {
  if (!(A.usuario.papel === 'admin' || A.usuario.papel === 'operador')) {
    t.appendChild(recado('Só a operação e o administrador enviam vídeo de teste.', true)); return;
  }
  const guardado = A.envioForm || {};
  const caixa = document.createElement('div'); caixa.className = 'caixa-form';
  caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Vídeo de teste: comprimir, medir e publicar' }));

  const linha1 = document.createElement('div'); linha1.className = 'linha-form'; caixa.appendChild(linha1);
  const rm = document.createElement('div'); rm.appendChild(Object.assign(document.createElement('label'), { textContent: 'De onde vem o vídeo' }));
  const modo = document.createElement('select'); modo.id = 'env-modo';
  for (const [v, r] of [['arquivo', 'arquivo do computador'], ['url', 'link (http ou YouTube)']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = r; modo.appendChild(o);
  }
  rm.appendChild(modo); linha1.appendChild(rm);
  const ra = document.createElement('div'); ra.appendChild(Object.assign(document.createElement('label'), { textContent: 'Arquivo de vídeo' }));
  const arquivo = document.createElement('input'); arquivo.type = 'file'; arquivo.accept = 'video/*'; arquivo.id = 'env-arquivo';
  ra.appendChild(arquivo); linha1.appendChild(ra);
  const url = campo(linha1, 'env-url', 'Link do vídeo', '');

  const linha2 = document.createElement('div'); linha2.className = 'linha-form'; caixa.appendChild(linha2);
  const rotulo = campo(linha2, 'env-rotulo', 'Rótulo na tela', '');
  const rq = document.createElement('div'); rq.appendChild(Object.assign(document.createElement('label'), { textContent: 'Qualidade (quanto comprimir)' }));
  const qualidade = document.createElement('select'); qualidade.id = 'env-qualidade';
  const ops = [['auto', 'automático — maior compressão sem perder qualidade (recomendado)'],
               ['crf26', 'melhor imagem (comprime menos)'], ['crf30', 'equilibrado'],
               ['crf34', 'máxima compressão (imagem mais simples)']];
  for (const [v, r] of ops) { const o = document.createElement('option'); o.value = v; o.textContent = r; qualidade.appendChild(o); }
  rq.appendChild(qualidade); linha2.appendChild(rq);
  const rf = document.createElement('div'); rf.appendChild(Object.assign(document.createElement('label'), { textContent: 'Quadros por segundo' }));
  const fps = document.createElement('select'); fps.id = 'env-fps';
  for (const [v, r] of [['30', '30 (padrão)'], ['25', '25'], ['60', '60 (gasta mais banda)']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = r; fps.appendChild(o);
  }
  rf.appendChild(fps); linha2.appendChild(rf);
  const rr = document.createElement('div'); rr.appendChild(Object.assign(document.createElement('label'), { textContent: 'Áudio' }));
  const audio = document.createElement('select'); audio.id = 'env-audio';
  for (const [v, r] of [['0', 'sem áudio'], ['1', 'manter (48 kbps)']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = r; audio.appendChild(o);
  }
  rr.appendChild(audio); linha2.appendChild(rr);
  const cy = document.createElement('div'); cy.appendChild(Object.assign(document.createElement('label'), { textContent: 'Repetir em laço ao publicar' }));
  const repetir = document.createElement('select'); repetir.id = 'env-repetir';
  for (const [v, r] of [['1', 'sim (parece ao vivo)'], ['0', 'não']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = r; repetir.appendChild(o);
  }
  cy.appendChild(repetir); linha2.appendChild(cy);

  const linha3 = document.createElement('div'); linha3.className = 'linha-form'; caixa.appendChild(linha3);
  const btnComprimir = botao('1) Comprimir e medir', 'principal', () => {});
  linha3.appendChild(btnComprimir);
  const btnPublicar = botao('2) Publicar no ar (a última compressão)', '', () => {});
  linha3.appendChild(btnPublicar);
  const progresso = document.createElement('div'); progresso.className = 'sub'; progresso.id = 'env-progresso';
  linha3.appendChild(progresso);
  const dizer = (txt) => { A.envioProgresso = txt; progresso.textContent = txt; };
  if (A.envioProgresso) progresso.textContent = A.envioProgresso;
  t.appendChild(caixa);

  const legenda = document.createElement('div'); legenda.className = 'sub';
  legenda.textContent = 'Entrada = tamanho do seu vídeo original · Saída = tamanho depois de comprimir · ' +
    'Compressão = quanta banda foi economizada · Tempo = quanto a compressão levou · Qualidade = semelhança com o ' +
    'original (1,000 = idêntico) · No ar = desde quando o vídeo comprimido está publicado.';
  t.appendChild(legenda);

  const guardar = () => { A.envioForm = { modo: modo.value, url: url.value, rotulo: rotulo.value,
    qualidade: qualidade.value, fps: fps.value, audio: audio.value, repetir: repetir.value }; };
  for (const el of [modo, url, rotulo, qualidade, fps, audio, repetir]) {
    el.addEventListener('input', guardar); el.addEventListener('change', guardar);
  }
  if (guardado.modo) {
    modo.value = guardado.modo; url.value = guardado.url || ''; rotulo.value = guardado.rotulo || '';
    qualidade.value = guardado.qualidade || 'auto'; fps.value = guardado.fps || '30';
    audio.value = guardado.audio || '0'; repetir.value = guardado.repetir || '1';
  }
  const trocarModo = () => {
    const ehArquivo = modo.value === 'arquivo';
    arquivo.parentElement.style.display = ehArquivo ? '' : 'none';
    url.parentElement.style.display = ehArquivo ? 'none' : '';
  };
  modo.onchange = () => { trocarModo(); guardar(); };
  trocarModo();

  const lista = document.createElement('div'); t.appendChild(lista);
  let ultimos = [];

  const montarTabela = (linhas, ingestoes) => {
    const porFluxo = {};
    for (const g of ingestoes || []) {
      const atual = porFluxo[g.fluxo_id];
      if (!atual) porFluxo[g.fluxo_id] = g;
      else if ((atual.estado !== 'no ar' || atual.estado === 'encerrado') && g.estado === 'no ar') porFluxo[g.fluxo_id] = g;
      else if (g.id > atual.id && atual.estado !== 'no ar') porFluxo[g.fluxo_id] = g;
    }
    return tabela([
      { rotulo: '#', campo: 'id' },
      { rotulo: 'Rótulo', campo: 'rotulo' },
      { rotulo: 'Entrada (original)', valor: (l) => (l.mb_entrada === null ? '—' : l.mb_entrada + ' MB') +
          (l.bitrate_entrada_kbps ? ' · ' + Math.round(l.bitrate_entrada_kbps) + ' kbps' : '') },
      { rotulo: 'Saída (comprimido)', valor: (l) => (l.mb_saida === null ? '—' : l.mb_saida + ' MB') +
          (l.bitrate_saida_kbps ? ' · ' + Math.round(l.bitrate_saida_kbps) + ' kbps' : '') },
      { rotulo: 'Compressão', valor: (l) => (l.compressao_pct === null || l.compressao_pct === undefined) ? '—'
          : (l.compressao_pct > 0 ? '↓ ' : '↑ ') + Math.abs(l.compressao_pct).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + '%' },
      { rotulo: 'Tempo da compressão', valor: (l) => (l.segundos_encode === null || l.segundos_encode === undefined) ? '—'
          : l.segundos_encode.toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + ' s' +
            (l.velocidade_x ? ' (' + l.velocidade_x + '× o tempo real)' : '') },
      { rotulo: 'Qualidade', valor: (l) => (l.ssim === null || l.ssim === undefined) ? '—' : Number(l.ssim).toFixed(4).replace('.', ',') },
      { rotulo: 'fps', valor: (l) => (l.fps || '—') + (l.crf ? ' · CRF ' + l.crf : '') },
      { rotulo: 'No ar', valor: (l) => {
          if (!l.publicado) return '—';
          const g = l.fluxo_id ? porFluxo[l.fluxo_id] : null;
          if (!g) return 'publicado';
          return (g.duracao_s ? Math.round(g.duracao_s) + ' s' : 'publicado') +
                 (g.fps ? ' · ' + numOu(g.fps) + ' fps' : '') + (g.estado ? ' · ' + g.estado : '');
        } },
      { rotulo: 'Ações', valor: (l) => {
          const cx = document.createElement('div'); cx.className = 'linha-acoes';
          if (l.existe) {
            const a = document.createElement('a'); a.className = 'botao'; a.href = l.baixar;
            a.textContent = 'baixar'; a.setAttribute('download', ''); cx.appendChild(a);
          }
          if (!l.publicado) cx.appendChild(botao('publicar', '', () => publicar(l.id)));
          else cx.appendChild(botao('parar', '', () => pararFluxo(l)));
          cx.appendChild(botao('remover', '', () => remover(l.id)));
          return cx;
        } }
    ], linhas, 'Nenhuma compressão ainda: escolha o vídeo e clique em "Comprimir e medir".');
  };

  const carregar = async () => {
    const r = await fetch('/api/compressoes');
    if (!r.ok) { limpar(lista); lista.appendChild(recado('Sem permissão para ver as compressões.', true)); return; }
    const d = await r.json();
    const ri = await fetch('/api/ingestoes');
    const ing = ri.ok ? ((await ri.json()).ingestoes || []) : [];
    ultimos = d.compressoes || [];
    limpar(lista);
    lista.appendChild(montarTabela(ultimos, ing));
  };
  const publicar = async (id) => {
    dizer('publicando no ar…');
    const r = await fetch('/api/compressao/publicar', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id }) });
    const j = await r.json();
    dizer(r.status === 201 ? ('no ar como "' + j.fluxo_id + '"') : ('falhou: ' + (j.erro || r.status)));
    if (r.status === 201) A.ultimaCompressao = id;
    carregar();
  };
  const pararFluxo = async (l) => {
    const ri = await fetch('/api/ingestoes');
    const ing = ri.ok ? ((await ri.json()).ingestoes || []) : [];
    const g = ing.filter((x) => x.fluxo_id === l.fluxo_id).pop();
    if (!g) { dizer('não achei o fluxo para parar'); return; }
    await fetch('/api/ingestao/parar', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: g.id, remover: false }) });
    dizer('parei "' + l.fluxo_id + '"');
    carregar();
  };
  const remover = async (id) => {
    await fetch('/api/compressao/remover', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id }) });
    carregar();
  };
  const resumo = (j) => 'comprimido: ' + j.entrada.mb + ' MB → ' + j.comprimido.mb + ' MB · ' +
    (j.corte_pct > 0 ? '↓ ' : '↑ ') + Math.abs(j.corte_pct) + '% · qualidade ' + (j.ssim === null ? '—' : j.ssim) +
    ' · ' + j.tempo_encode_s + ' s' + (j.crf ? ' · CRF ' + j.crf : '') + '. Agora clique em "Publicar no ar".';

  btnComprimir.onclick = () => {
    const r = (rotulo.value || '').trim(), b = qualidade.value, qf = fps.value, aud = audio.value;
    if (modo.value === 'arquivo') {
      const f = arquivo.files && arquivo.files[0];
      if (!f) { dizer('escolha o arquivo de vídeo'); return; }
      const q = new URLSearchParams({ nome: f.name, qualidade: b, fps: qf, audio: aud });
      const x = new XMLHttpRequest();
      x.open('POST', '/api/ingestao/comprimir?' + q.toString());
      x.upload.onprogress = (e) => { if (e.lengthComputable) dizer('enviando o original… ' + Math.round(e.loaded / e.total * 100) + '%'); };
      x.onload = () => {
        let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {}
        if (x.status !== 201) { dizer('falhou: ' + (j.erro || x.status)); return; }
        A.ultimaCompressao = j.id;
        dizer(resumo(j));
        carregar();
      };
      dizer('comprimindo ' + f.name + '… (a busca da melhor compressão leva alguns segundos)');
      x.send(f);
    } else {
      const u = (url.value || '').trim();
      if (!/^https?:\/\//.test(u)) { dizer('cole um link http(s) válido'); return; }
      dizer('baixando e comprimindo o link…');
      fetch('/api/ingestao/comprimir', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: u, rotulo: r, qualidade: b, fps: qf, audio: aud }) })
        .then(async (x) => ({ s: x.status, j: await x.json() }))
        .then(({ s, j }) => {
          if (s !== 201) { dizer('falhou: ' + (j.erro || s)); return; }
          A.ultimaCompressao = j.id;
          dizer(resumo(j));
          carregar();
        });
    }
  };
  btnPublicar.onclick = () => {
    const id = A.ultimaCompressao || (ultimos[0] || {}).id;
    if (!id) { dizer('comprima um vídeo primeiro'); return; }
    publicar(id);
  };

  carregar();
  if (timerEnvios) { clearInterval(timerEnvios); timerEnvios = null; }
  timerEnvios = setInterval(() => { if (A.tela === 'envios') carregar(); }, 5000);
}

function telaAuditoria(t) {
  t.appendChild(tabela([{ rotulo: 'Quando', campo: 'em' }, { rotulo: 'Quem', valor: (l) => l.usuario_nome || l.email },
    { rotulo: 'Ação', campo: 'acao' }, { rotulo: 'Alvo', campo: 'alvo' }, { rotulo: 'IP', campo: 'ip' }],
    (A.resumo || {}).auditoria || [], 'sem registro'));
}

function telaSaude(t) {
  if (A.usuario.papel !== 'admin') { t.appendChild(recado('Somente o administrador do sistema vê esta área.', true)); return; }
  const s = A.sistema || {};
  const c = document.createElement('div'); c.className = 'cartoes';
  c.appendChild(cartao('API', s.api || '—', 'versão da API'));
  c.appendChild(cartao('Python', s.python || '—', 'runtime'));
  c.appendChild(cartao('Lado terra', s.mediamtx ? 'ativo' : 'fora', 'mediamtx'));
  c.appendChild(cartao('Chave de análise', s.chave_analytics_configurada ? 'configurada' : 'não configurada', 'agente de bordo (Fase 5)'));
  c.appendChild(cartao('Retenção', String(s.retencao_dias || '—'), 'política de gravação'));
  c.appendChild(cartao('Sessões abertas', (s.contagens && s.contagens.sessoes) || 0, 'usuários logados'));
  c.appendChild(cartao('Uptime', (s.uptime_s || 0) + ' s', 'desde ' + (s.iniciado_em || '—')));
  t.appendChild(c);
  const cont = s.contagens || {};
  t.appendChild(tabela([{ rotulo: 'Tabela', campo: 't' }, { rotulo: 'Linhas', campo: 'n' }],
    Object.keys(cont).map((k) => ({ t: k, n: cont[k] })), 'sem contagem'));
  const d = document.createElement('div'); d.className = 'recado ok';
  d.textContent = 'banco: ' + (s.banco || '—');
  t.appendChild(d);
}

/* --------------------------------------------------------- interface */
$('form-entrar').addEventListener('submit', entrar);
$('btn-sair').addEventListener('click', async () => { await api('/api/sair', { method: 'POST' }); location.reload(); });
$('btn-atualizar').addEventListener('click', atualizar);
document.querySelectorAll('.item[data-tela]').forEach((b) => b.addEventListener('click', () => {
  A.tela = b.dataset.tela;
  document.querySelectorAll('.item[data-tela]').forEach((x) => x.classList.toggle('on', x === b));
  desenhar();
}));
function relogio() { const d = new Date(); const p = (n) => String(n).padStart(2, '0');
  $('relogio-servidor').textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; }
setInterval(relogio, 1000); relogio();
abrir();
