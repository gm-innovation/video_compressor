/* Admin do projeto e do sistema: acompanhamento (§6) + administracao (clientes, embarcacoes,
   cameras, usuarios, analises, auditoria, saude). Le e escreve tudo pela API do produto. */
const A = { usuario: null, resumo: null, clientes: [], usuarios: [], verificarCredencial: false, sistema: null, cameras: [], embarcacoes: [], tela: 'painel', timer: null, marca: null, radarForm: null, radarAviso: null, prontidao: null };
const $ = (id) => document.getElementById(id);
const limpar = (el) => { while (el.firstChild) el.removeChild(el.firstChild); };
const esc = (s) => String(s === null || s === undefined ? '' : s);

/* --------------------------------------------------- captura nesta maquina (dono, 16/11/2026)
   "deve liberar as funcoes de captura, nao mudar para o app de captura": quando o aplicativo libera
   as funcoes de captura (menu "Servidor local"), ele avisa por aqui o endereco do servidor LOCAL e
   SO' as rotas de captura passam a falar com ele — dispositivos desta maquina, ingestao (comprimir,
   publicar, ao vivo) e envios. Cadastro, usuarios, clientes e cameras continuam no lado terra, que e'
   quem guarda o cadastro; por isso a tela do Admin segue logada e completa. */
const BASE_CAPTURA = (() => {
  try { return (window.lecsorApp && window.lecsorApp.enderecoDaCaptura && window.lecsorApp.enderecoDaCaptura()) || ''; }
  catch (e) { return ''; }
})();
const ROTAS_CAPTURA = /^\/api\/(dispositivos|envios|ingestao|ingestoes|compressao|compressoes|medicoes|trecho|captura|embarcacoes|publicacao)(\/|$)/;
const ehRotaDeCaptura = (rota) => ROTAS_CAPTURA.test(String(rota));
const urlDeCaptura = (rota) => (BASE_CAPTURA && ehRotaDeCaptura(rota) ? BASE_CAPTURA + rota : rota);

async function api(rota, opcoes) {
  const alvo = urlDeCaptura(rota);
  // outra origem (o servidor local desta maquina): sem cookie — quem autoriza a captura ali e' o
  // proprio IP da maquina (a API chama isso de `local`), nunca a sessao do lado terra.
  const credenciais = alvo === rota ? 'same-origin' : 'omit';
  const r = await fetch(alvo, Object.assign({ credentials: credenciais, headers: { 'Content-Type': 'application/json' } }, opcoes));
  const texto = await r.text();
  let corpo = null;
  try { corpo = texto ? JSON.parse(texto) : null; } catch (e) { corpo = { bruto: texto }; }
  return { ok: r.ok, status: r.status, corpo };
}

/// Mesmo roteamento do `api()`, para as chamadas que a tela faz com fetch cru (upload/progresso).
function fetchCaptura(rota, opcoes) {
  const alvo = urlDeCaptura(rota);
  const o = Object.assign({ credentials: alvo === rota ? 'same-origin' : 'omit' }, opcoes || {});
  return fetch(alvo, o);
}

/* --------------------------------------------------------- entrada */
/* Primeiro acesso: instalacao nova nao tem usuario nenhum, entao o login normal nunca funcionaria.
   A tela troca para o formulario que cria o administrador desta maquina (a API so aceita isso da
   propria maquina e enquanto nao existir usuario). */
async function conferirPrimeiroAcesso() {
  const r = await api('/api/primeiro-acesso');
  if (r.ok && r.corpo && r.corpo.precisa) {
    $('entrada').classList.add('oculto');
    $('primeiro').classList.remove('oculto');
    if (r.corpo.local === false) {
      const e = $('primeiro-erro');
      e.textContent = 'esta lista só pode ser criada na própria máquina do servidor (' + (r.corpo.maquina || 'servidor') + ')';
      e.classList.remove('oculto');
    }
    $('p-nome').focus();
    return true;
  }
  return false;
}

async function primeiroAcesso(ev) {
  ev.preventDefault();
  const erro = (t) => { const e = $('primeiro-erro'); e.textContent = t; e.classList.remove('oculto'); };
  if ($('p-senha').value !== $('p-senha2').value) return erro('as duas senhas não são iguais');
  const d = await api('/api/primeiro-acesso', { method: 'POST', body: JSON.stringify({
    nome: $('p-nome').value, email: $('p-email').value, senha: $('p-senha').value }) });
  if (!d.ok) return erro((d.corpo && d.corpo.erro) || 'não foi possível criar o primeiro acesso');
  await abrir();
}

async function entrar(ev) {
  ev.preventDefault();
  const d = await api('/api/entrar', { method: 'POST', body: JSON.stringify({ email: $('email').value, senha: $('senha').value }) });
  if (!d.ok) { const e = $('entrada-erro'); e.textContent = (d.corpo && d.corpo.erro) || 'não foi possível entrar'; e.classList.remove('oculto'); return; }
  if (d.corpo.papel === 'cliente') { const e = $('entrada-erro'); e.textContent = 'esta conta é de cliente: use a tela do cliente (/app)'; e.classList.remove('oculto'); return; }
  if (d.corpo.papel === 'tecnico') { const e = $('entrada-erro'); e.textContent = 'esta conta é de técnico de captura: use a tela "Enviar vídeo" (/ — bancada)'; e.classList.remove('oculto'); return; }
  await abrir();
}

async function abrir() {
  const eu = await api('/api/eu');
  // Cliente e tecnico NAO tem console aqui: vao para a tela do proprio papel (o app unico ja manda
  // cada um para a sua — ver `entrada/entrada.js`). Papel que nao entra no console nao deve ver a
  // tela de "primeiro acesso", que convida a cadastrar administrador.
  if (!eu.corpo || !eu.corpo.autenticado) return conferirPrimeiroAcesso();
  if (eu.corpo.papel === 'cliente') { window.location.replace('/app'); return; }
  if (eu.corpo.papel === 'tecnico') { window.location.replace('/'); return; }
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
  statusAtualizar('atualizando\u2026');
  try { const rc = await fetch('/api/cameras/detalhe'); if (rc.ok) A.camerasInterno = await rc.json(); } catch (e) {}
  /* SSIM por fluxo: o número é medido no PC de captura (a máquina que tem a fonte crua) e chega
     aqui pelo anúncio autenticado do bordo. Sem esta leitura a tela ficava sem medicao nenhuma —
     era o "ainda não tenho medição de SSIM" do dono. */
  try {
    const rq = await fetch('/api/qualidade');
    const jq = rq.ok ? await rq.json() : {};
    const mapa = {};
    for (const f of (jq.fluxos || [])) mapa[f.fluxo_id] = Object.assign({ piso_aceito: jq.piso_aceito }, f);
    A.qualidadeFluxos = mapa;
  } catch (e) { A.qualidadeFluxos = A.qualidadeFluxos || {}; }
  /* O que o PC de captura DECLARA do envio (entrada, saída, corte, alvo, resolução) e a última
     tentativa de anúncio, aceita ou recusada. É o lado "declarado" do comparativo: sem isto esta
     tela só tinha o que o lado terra mede, e o dono não tinha com o que comparar. */
  try {
    const rd = await fetch('/api/declarado');
    const jd = rd.ok ? await rd.json() : {};
    const mapa = {};
    for (const f of (jd.declarado || [])) mapa[f.fluxo_id] = f;
    A.declaradoFluxos = mapa;
    A.declaradoSemFluxos = jd.sem_declaracao || [];
  } catch (e) { A.declaradoFluxos = A.declaradoFluxos || {}; A.declaradoSemFluxos = A.declaradoSemFluxos || []; }
  const rs = await api('/api/resumo'); if (rs.ok) A.resumo = rs.corpo;
  const em = await api('/api/embarcacoes'); A.embarcacoes = (em.corpo && em.corpo.embarcacoes) || [];
  const cm = await api('/api/cameras'); A.cameras = (cm.corpo && cm.corpo.cameras) || [];
  /* STAND-BY do PC de captura (dono, 19/11/2026): o sinal chega pelo split o tempo todo e nos so'
     transmitimos quando o cliente ativa. Esta leitura diz, por camera, se ela esta' PRONTA (dispositivo
     existe e nada o ocupa), NO AR, AUSENTE (cabo/USB fora) ou EM USO — sem abrir camera nenhuma. */
  try {
    const rp = await fetch('/api/cameras/prontidao');
    const jp = rp.ok ? await rp.json() : {};
    const mapa = {};
    for (const c of (jp.cameras || [])) mapa[c.id] = c;
    A.prontidao = { maquina_de_captura: !!jp.maquina_de_captura, cameras: mapa, dispositivos: jp.dispositivos || [] };
  } catch (e) { A.prontidao = A.prontidao || null; }
  if (A.usuario && A.usuario.papel === 'admin') {
    const cl = await api('/api/clientes'); A.clientes = (cl.corpo && cl.corpo.clientes) || [];
    const us = await api('/api/usuarios' + (A.verificarCredencial ? '?credencial=1' : ''));
    A.usuarios = (us.corpo && us.corpo.usuarios) || [];
    const si = await api('/api/sistema'); if (si.ok) A.sistema = si.corpo.sistema;
  } else {
    const cl = await api('/api/clientes'); A.clientes = (cl.corpo && cl.corpo.clientes) || [];
  }
  /* So apaga e repinta a tela quando o que ela mostra mudou de verdade. Antes isto desenhava a
     cada 15 s por causa de campos que mudam sozinhos (gerado_em do resumo, uptime_s do sistema):
     a tela era limpa no meio da leitura do operador. */
  const marca = assinaturaTelas();
  if (marca === A.marca) { statusAtualizar('sem mudan\u00e7as desde ' + agora()); return; }
  A.marca = marca;
  desenhar();
  statusAtualizar('atualizado ' + agora());
}

/* Feedback do botao "Atualizar": antes ele repintava so quando algo mudava e nao dizia nada, e quem
   clicava com os mesmos dados nao via reacao nenhuma ("o botao esta surdo, mudo ou cego"). */
function statusAtualizar(t) { const e = $('status-atualizar'); if (e) e.textContent = t; }
function agora() { const d = new Date(); const p = (n) => String(n).padStart(2, '0'); return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds()); }

/* Impressao digital do que as telas realmente mostram. Campos que mudam sozinhos (relogio do
   resumo, uptime, idade das medidas) ficam de fora: sozinhos nao justificam repintar. */
const RUIDO_TELA = { gerado_em: 1, uptime_s: 1, idade_s: 1, atualizado_em: 1, lido_em: 1, agora: 1 };
function assinaturaTelas() {
  try {
    return JSON.stringify([A.resumo, A.embarcacoes, A.cameras, A.clientes, A.usuarios, A.sistema, A.camerasInterno,
      A.prontidao],
      (k, v) => (RUIDO_TELA[k] ? undefined : v));
  } catch (e) { return 'erro:' + Math.random(); }
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
  tempo: ['Tempo real', 'Como está a compressão, a velocidade de envio e a banda consumida e economizada, atualizando a cada 2 segundos.'],
  producao: ['Produção', 'Cards por embarcação e câmera: enviando/parado, média de compressão, banda utilizada e economizada, horas de streaming e disponibilidade — com filtro de período.'],
  usuarios: ['Usuários', 'Só o administrador cadastra. Papéis: cliente (vê a própria empresa), operador, administrador e técnico (captura a bordo).'],
  analises: ['Análises de vídeo', 'Contagem e eventos sobem de bordo (Fase 5) — sem agente a bordo a tela fica vazia.'],
  auditoria: ['Auditoria', 'Quem viu qual câmera, quando — e o que foi negado.'],
  marcas: ['Marcas e zonas', 'A linha de contagem e as zonas de risco que o agente de bordo usa, desenhadas aqui.'],
  envios: ['Enviar vídeo', 'Escolhe a fonte (arquivo, link ou câmera desta máquina) e a qualidade por câmera: o sistema codifica, publica em SRT e mede o corte de banda.'],
  saude: ['Saúde do sistema', 'Estado da API, do lado terra e das contagens do banco.']
};

/* --------------------------------------------------------- telas */
function envioEmAndamento() {
  /* Ha' algo escolhido/digitado na tela de envio que o redesenho apagaria? */
  if (A.tela !== 'envios') return false;
  const arq = document.getElementById('env-arquivo');
  if (arq && arq.files && arq.files.length) return true;
  for (const id of ['env-rotulo', 'env-url']) {
    const e = document.getElementById(id);
    if (e && (e.value || '').trim()) return true;
  }
  return false;
}

function desenhar(forcado) {
  /* NAO repinta a tela de envio enquanto o operador esta' preenchendo: o redesenho recria os campos e
     o que ele digitou/escolheu se perde (medido 18/11/2026: o rotulo digitado sumia e o "Comprimir e
     medir" respondia "escolha o arquivo de video" com o arquivo ja' escolhido). As listas continuam
     se atualizando sozinhas pelo timer delas. Trocar de tela pelo menu manda `forcado` e passa. */
  if (!forcado && envioEmAndamento()) { statusAtualizar('segurando a tela: você está preenchendo o envio'); return; }
  const [titulo, sub] = SUBS[A.tela] || SUBS.painel;
  $('titulo-tela').textContent = titulo; $('sub-tela').textContent = sub;
  const tela = $('tela'); limpar(tela);
  if (timerEnvios) { clearInterval(timerEnvios); timerEnvios = null; }
  if (timerTempo) { clearInterval(timerTempo); timerTempo = null; }
  if (timerProducao) { clearInterval(timerProducao); timerProducao = null; }
  const despacho = { painel: telaPainel, fases: telaFases, medicoes: telaMedicoes, decisoes: telaDecisoes,
    evidencias: telaEvidencias, documentos: telaDocumentos, clientes: telaClientes, embarcacoes: telaEmbarcacoes,
    cameras: telaCameras, usuarios: telaUsuarios, tempo: telaTempoReal, producao: telaProducao, analises: telaAnalises, marcas: telaMarcas, envios: telaEnvios,
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
  /* O ENDERECO que vai junto com o acesso do cliente (plano, Fase 1 P1): quem recebe o login recebe o
     link da tela — o cliente so' abre o endereco, sem manual e sem instalar nada. */
  const endCliente = document.createElement('p'); endCliente.className = 'nota'; endCliente.id = 'end-cliente';
  const urlCliente = location.origin + '/app/';
  endCliente.appendChild(Object.assign(document.createElement('b'),
    { textContent: 'Endereço da tela do cliente (manda junto com o acesso — não instala nada): ' }));
  endCliente.appendChild(Object.assign(document.createElement('code'), { textContent: urlCliente }));
  endCliente.appendChild(document.createTextNode(' '));
  endCliente.appendChild(botao('copiar endereço', 'mini', async () => {
    try { await navigator.clipboard.writeText(urlCliente); mostrarRecado('endereço copiado: ' + urlCliente, false); }
    catch (e) { mostrarRecado('não consegui copiar — selecione o endereço e copie na mão', true); }
  }));
  t.appendChild(endCliente);
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
  const fmt = (v, casas) => (v === null || v === undefined) ? '—'
    : Number(v).toLocaleString('pt-BR', { maximumFractionDigits: casas === undefined ? 2 : casas });
  if (A.usuario.papel === 'admin' || A.usuario.papel === 'operador') {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Câmera: onde ela está e por onde entra' }));
    const aviso = document.createElement('div'); aviso.className = 'nota';
    aviso.textContent = 'IP e porta ficam só aqui (operação/LECSOR) e no servidor de captura; o app do cliente nunca recebe ' +
      'endereço de câmera nem senha. A senha entra por variável de ambiente no servidor de captura, não neste formulário.';
    caixa.appendChild(aviso);
    const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
    const rot = campo(linha, 'k-rot', 'Rótulo na tela', '');
    const flu = campo(linha, 'k-fluxo', 'Fluxo publicado (ex.: cam-01)', '');
    const ip = campo(linha, 'k-ip', 'IP da câmera ou gravador', '');
    const porta = campo(linha, 'k-porta', 'Porta', '554');
    const canal = campo(linha, 'k-canal', 'Canal do gravador (opcional)', '');
    caixa.appendChild(botao('Cadastrar câmera', 'marca', async () => {
      const r = await api('/api/cameras', { method: 'POST', body: JSON.stringify({
        rotulo: rot.value.trim() || flu.value.trim(), fluxo_id: flu.value.trim(),
        ip: ip.value.trim(), porta: (porta.value || '').trim(), canal: (canal.value || '').trim() }) });
      await atualizar();
      mostrarRecado(r.ok ? 'câmera cadastrada: ' + r.corpo.id : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
    }));
    /* O cadastro desta máquina sobe sozinho no lado terra (ao cadastrar e ao subir o servidor local).
       Este botão existe para o caso da câmera que já estava cadastrada antes disso: sem ele a linha
       fica só no banco local e o app do cliente não mostra nada ("cadastrei cam-01 e não aparece"). */
    const caixaPub = document.createElement('div'); caixaPub.className = 'caixa-form'; caixaPub.id = 'cam-publicacao';
    caixa.appendChild(caixaPub);
    /* Este quadro é o que faltava quando o dono perguntou "por que minha câmera não aparece?":
       o anúncio do cadastro ao lado terra falhava SÓ no arquivo de log repasse-<fluxo>.log. Aqui a
       tela mostra, por câmera, se o cadastro está publicado no lado terra e, quando não está, o motivo. */
    const puxarPublicacao = async () => {
      const r = await api('/api/publicacao');
      const p = (r.ok && r.corpo) || {}; const an = p.anuncio || {};
      caixaPub.innerHTML = '';
      caixaPub.appendChild(Object.assign(document.createElement('h2'),
        { textContent: 'No lado terra — é isso que o cliente e o "Tempo real" mostram' }));
      const nota = document.createElement('div'); nota.className = 'nota';
      /* No proprio lado terra nao existe "publicar": o cadastro local JA' e' o que as telas leem.
         Sem esta linha a tela acusava TODA camera como nao publicada, com motivo falso (medido na VPS). */
      nota.textContent = an.sou_o_lado_terra
        ? 'esta máquina é o lado terra: o cadastro daqui é o que a tela do cliente e o "Tempo real" já leem'
        : (an.de_pe
          ? 'anúncio de pé: lado terra ' + (an.lado_terra || '?') + ' · embarcação ' + (an.embarcacao || '—')
          : 'anúncio NÃO está de pé — falta ' + ((an.faltando || []).join(', ') || 'o ambiente do pacote')
            + '. Sem ele o cadastro da câmera não sai desta máquina e ela não aparece na tela do cliente.');
      caixaPub.appendChild(nota);
      const linhasPub = (p.cameras || []).map((c) => ({
        rotulo: c.rotulo || c.fluxo_id, publicado: c.publicado ? 'publicado' : 'não',
        motivo: c.motivo || '—', quando: c.em ? String(c.em).replace('T', ' ') : '—',
      }));
      caixaPub.appendChild(tabela([{ rotulo: 'Câmera', campo: 'rotulo' },
        { rotulo: 'No lado terra', campo: 'publicado' }, { rotulo: 'Motivo', campo: 'motivo' },
        { rotulo: 'Última tentativa', campo: 'quando' }], linhasPub, 'nenhuma câmera cadastrada'));
      caixaPub.appendChild(botao('Publicar agora (todas as câmeras)', 'mini', async () => {
        const rr = await api('/api/publicacao', { method: 'POST', body: JSON.stringify({}) });
        const pp = (rr.corpo || {});
        mostrarRecado(rr.ok ? 'publicado no lado terra: ' + (pp.publicadas ?? 0) + '/' + (pp.total ?? 0)
          : 'não publiquei: ' + JSON.stringify((pp.anuncio && pp.anuncio.faltando) || pp), !rr.ok);
        await puxarPublicacao();
      }));
    };
    puxarPublicacao();
    t.appendChild(caixa);
  }
  const interno = (A.camerasInterno && A.camerasInterno.cameras) || [];
  const porId = {};
  for (const c of interno) porId[c.id] = c;
  /* O admin vê TODAS as câmeras (inclusive as desativadas — senão não teria como religar); o
     cliente só vê as ativas, e nesse caso cai na lista dele. A tela diz a situação de cada uma. */
  const vivo = {};
  for (const c of (A.cameras || [])) vivo[c.id] = c;
  const linhas = interno.length
    ? interno.map((c) => Object.assign({}, c, { viva: vivo[c.id] || null }))
    : (A.cameras || []).map((c) => Object.assign({}, porId[c.id] || {}, { viva: c, id: c.id, rotulo: c.rotulo }));
  const situacao = (l) => (!l.ativo ? 'desativada' : (l.viva && l.viva.no_ar ? 'no ar' : 'fora do ar'));
  /* A medição de qualidade do fluxo ao vivo é feita na máquina que TEM a fonte crua (o PC de
     captura) e chega aqui pelo anúncio autenticado do bordo: a tela mostra o último número com a
     idade, porque SSIM sem "medida quando" não diz se o ajuste medido ainda é o que está no ar. */
  const qualDe = (l) => (A.qualidadeFluxos || {})[l.fluxo_id || l.id] || null;
  const horaCurta = (iso) => (iso ? String(iso).replace('T', ' ').slice(11, 19) : '—');
  /* O que a máquina de captura declarou do envio que está no ar — e, quando não declarou, o que ela
     TENTOU (declaração recusada mostra o motivo em vez de sumir na tela). */
  const declaradoDe = (l) => (A.declaradoFluxos || {})[l.fluxo_id || l.id] || null;
  const textoDeclarado = (l) => {
    const d = declaradoDe(l);
    if (!d) {
      const sem = (A.declaradoSemFluxos || []).find((x) => x.fluxo_id === (l.fluxo_id || l.id));
      const t = sem && sem.ultima_tentativa;
      if (t && !t.aceito) return 'NAO declarado · tentou ' + horaCurta(t.em) + ' e foi recusada (' + (t.motivo || 'sem motivo') + ')';
      if (t) return 'NAO declarado · ultimo anuncio ' + horaCurta(t.em) + ' chegou sem os numeros';
      return 'NAO declarado (o PC de captura nao informou)';
    }
    return fmt(d.bitrate_saida_kbps) + ' kbps declarado'
      + (d.bitrate_entrada_kbps ? ' de ' + fmt(d.bitrate_entrada_kbps) + ' kbps' : '')
      + (d.corte_pct === null || d.corte_pct === undefined ? '' : ' · corte ' + fmt(d.corte_pct) + '%')
      + (d.resolucao ? ' · ' + d.resolucao : '') + (d.fps ? ' · ' + fmt(d.fps, 0) + ' fps' : '')
      + (d.estado ? ' · ' + d.estado : '') + ' · declarado ' + horaCurta(d.declarado_em);
  };
  const textoQualidade = (l) => {
    const q = qualDe(l);
    if (!q) return '— (não medida ainda)';
    const idade = (q.idade_s === null || q.idade_s === undefined) ? ''
      : ' · medida ' + (Math.abs(q.idade_s) < 90 ? Math.round(Math.abs(q.idade_s)) + ' s atrás'
        : Math.round(Math.abs(q.idade_s) / 60) + ' min atrás');
    return fmt(q.ssim, 4) + (q.passa ? '' : ' ⚠ abaixo do piso ' + fmt(q.piso_aceito, 4))
      + ' · ajuste ' + (q.ajuste || '—') + idade
      + (q.passa === false && q.alvo_sugerido ? ' · sugerido: ' + q.alvo_sugerido : '');
  };
  /* STAND-BY (dono, 19/11/2026): o sinal chega dividido (split) o tempo todo; nosso sistema transmite
     so' quando o cliente ativa. Onde a captura NAO e' desta maquina, a coluna diz isso com todas as
     letras — mostrar "pronta" aqui seria mentira, porque quem ve' o dispositivo e' o PC de bordo. */
  const NOME_STANDBY = { pronta: 'pronta (stand-by)', no_ar: 'no ar', em_uso: 'em uso por outro envio',
    ausente: 'AUSENTE (cabo/USB fora)', sem_dispositivo: 'sem entrada de captura desta maquina',
    por_endereco: 'por endereco (RTSP)' };
  const textoStandBy = (l) => {
    const p = A.prontidao;
    if (!p || !p.maquina_de_captura) return 'a bordo (quem informa e o PC de captura)';
    const c = (p.cameras || {})[l.id];
    if (!c) return '— (a camera nao esta nesta maquina)';
    const nome = NOME_STANDBY[c.estado] || c.estado || '—';
    return nome + (c.dispositivo ? ' · ' + c.dispositivo : '') + (c.motivo ? ' · ' + c.motivo : '');
  };
  t.appendChild(tabela([{ rotulo: 'Câmera', campo: 'rotulo' }, { rotulo: 'Fluxo', campo: 'fluxo_id' },
    { rotulo: 'Situação', valor: situacao },
    { rotulo: 'Stand-by (PC de captura)', valor: textoStandBy },
    { rotulo: 'Endereço (operação)', valor: (l) => { const c = porId[l.id] || {}; return c.ip ? c.ip + ':' + (c.porta || '554') + (c.canal ? ' · canal ' + c.canal : '') : '—'; } },
    { rotulo: 'Como o agente pega', valor: (l) => { const c = porId[l.id] || {}; return c.captura || '—'; } },
    { rotulo: 'Encoder', valor: (l) => { const e = (l.viva && l.viva.encoder) || {}; return [e.codec, e.resolucao, e.fps ? e.fps + ' fps' : '', e.bitrate].filter(Boolean).join(' · '); } },
    { rotulo: 'Qualidade (SSIM)', valor: textoQualidade },
    { rotulo: 'Declarado pelo PC de captura', valor: textoDeclarado },
    { rotulo: 'Qualidade enviada (só desta câmera)', valor: (l) => {
        /* Selecao FECHADA de taxa por camera (dono, 16/11/2026): 1500k/1200k/1000k/800k/500k/300k.
           Escolher aqui vale NO AR: o servidor reabre o envio SÓ desta câmera (~2 s) com a taxa nova.
           Abaixo do piso de qualidade o sistema só AVISA (não recusa) — a decisão é da operação. */
        const c = porId[l.id] || {};
        const caixa = document.createElement('div');
        caixa.style.display = 'flex'; caixa.style.gap = '.4rem'; caixa.style.alignItems = 'center';
        const sel = document.createElement('select');
        sel.className = 'mini';
        sel.title = 'Taxa de envio só desta câmera';
        for (const op of ['', '1500k', '1200k', '1000k', '800k', '500k', '300k']) {
          sel.appendChild(Object.assign(document.createElement('option'), {
            value: op, textContent: op ? op.replace('k', ' kbps') : 'padrão da tela',
            selected: (c.alvo || '') === op }));
        }
        // um alvo antigo (ex.: 2500k de antes da lista) continua visível, para não parecer "voltou ao padrão"
        if (c.alvo && !['', '1500k', '1200k', '1000k', '800k', '500k', '300k'].includes(c.alvo)) {
          sel.appendChild(Object.assign(document.createElement('option'), { value: c.alvo, textContent: c.alvo + ' (fora da lista)', selected: true }));
        }
        caixa.appendChild(sel);
        const sug = qualDe(l);
        const dica = (sug && sug.passa === false) ? ' · abaixo do piso (⚠ ' + fmt(sug.ssim, 4) + ')' : '';
        caixa.appendChild(botao('aplicar', 'mini', async () => {
          const r = await api('/api/cameras/' + encodeURIComponent(l.id) + '/alvo',
            { method: 'POST', body: JSON.stringify({ alvo: sel.value }) });
          const d = r.corpo || {};
          mostrarRecado(r.ok ? ('qualidade de ' + l.rotulo + ' = ' + (d.alvo || 'padrão da tela')
            + ' — ' + (d.aplicado ? 'aplicada no ar (envio reaberto)' : (d.motivo || '')) + dica)
            : 'recusado: ' + JSON.stringify(d), !r.ok);
          if (r.ok) { A.camerasInterno = null; await atualizar(); }
        }));
        return caixa;
      } },
    { rotulo: 'Espectadores', valor: (l) => ((l.viva && l.viva.leitores) || 0) },
    { rotulo: 'Ação', valor: (l) => {
        const c = porId[l.id] || {};
        const cx = document.createElement('div');
        cx.style.display = 'flex'; cx.style.gap = '.4rem'; cx.style.flexWrap = 'wrap';
        cx.appendChild(botao(l.ativo ? 'desativar' : 'ativar', 'mini', async () => {
          if (l.ativo && !confirm('Desativar "' + l.rotulo + '"? Ela sai da tela do cliente; o histórico fica guardado.')) return;
          const r = await api('/api/cameras/' + encodeURIComponent(l.id) + '/ativo', { method: 'POST', body: JSON.stringify({ ativo: !l.ativo }) });
          mostrarRecado(r.ok ? (l.ativo ? 'câmera desativada — o cliente não vê mais' : 'câmera ativada de novo') : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
          if (r.ok) { A.camerasInterno = null; await atualizar(); }
        }));
        /* Editar EM OPERAÇÃO: muda só o que você digitar. Não recria a linha (isso zerava `ativo` e o
           alvo escolhido) e não toca no vídeo quando é só o rótulo. */
        cx.appendChild(botao('editar', 'mini', async () => {
          const rot = prompt('Rótulo desta câmera (Enter mantém "' + l.rotulo + '"):', l.rotulo);
          if (rot === null) return;
          const end = prompt('Endereço de operação (IP:porta ou só IP). Enter mantém "' + (c.ip || '—') + '".',
            (c.ip || '') + (c.porta ? ':' + c.porta : ''));
          if (end === null) return;
          const corpo = {};
          if (rot.trim() && rot.trim() !== l.rotulo) corpo.rotulo = rot.trim();
          if (end.trim()) {
            const m = end.trim().match(/^([^:]+)(?::(\d+))?$/);
            if (!m) { mostrarRecado('endereço inválido: use IP ou IP:porta', true); return; }
            if (m[1] !== (c.ip || '')) corpo.ip = m[1];
            if (m[2] && m[2] !== String(c.porta || '')) corpo.porta = m[2];
          }
          if (!Object.keys(corpo).length) { mostrarRecado('nada a mudar em ' + l.rotulo, true); return; }
          const r = await api('/api/cameras/' + encodeURIComponent(l.id) + '/editar',
            { method: 'POST', body: JSON.stringify(corpo) });
          const d = r.corpo || {};
          mostrarRecado(r.ok ? ('câmera ' + l.rotulo + ' editada: ' + (d.mudou || []).join(', ')
            + ' — ' + (d.aplicado ? 'fonte reaberta no ar' : (d.motivo || ''))) : 'recusado: ' + JSON.stringify(d), !r.ok);
          if (r.ok) { A.camerasInterno = null; await atualizar(); }
        }));
        /* Remover: a câmera que não é mais usada. Some daqui E da tela do cliente (o lado terra apaga
           o cadastro); os trechos e a auditoria ficam. Exige digitar "remover" para não ser engano. */
        cx.appendChild(botao('remover', 'mini', async () => {
          const conf = prompt('Remover "' + l.rotulo + '" de vez? Ela sai desta lista e da tela do cliente.\n' +
            'Os trechos já gravados e a auditoria continuam. Digite remover para confirmar:');
          if (conf === null) return;
          if (conf.trim().toLowerCase() !== 'remover') { mostrarRecado('remover cancelado (nada foi apagado)', true); return; }
          const r = await api('/api/cameras/' + encodeURIComponent(l.id) + '/remover', { method: 'POST', body: JSON.stringify({}) });
          const d = r.corpo || {};
          mostrarRecado(r.ok ? ('câmera ' + l.rotulo + ' removida — envio parado: ' + (d.envio_parado ? 'sim' : 'não estava no ar')
            + ' · lado terra: ' + (d.lado_terra && d.lado_terra.ok ? 'cadastro apagado' : JSON.stringify((d.lado_terra || {}).motivo || '')))
            : 'recusado: ' + JSON.stringify(d), !r.ok);
          if (r.ok) { A.camerasInterno = null; await atualizar(); }
        }));
        return cx;
      } }], linhas, 'nenhuma câmera cadastrada'));
  /* Comparar a MESMA cena em vários alvos: é assim que "está perdendo qualidade" vira número. A
     fonte precisa estar livre (a medição abre a câmera), então o envio tem que estar parado. */
  const caixaComp = document.createElement('div'); caixaComp.className = 'caixa-form';
  caixaComp.appendChild(Object.assign(document.createElement('h2'),
    { textContent: 'Comparar a mesma cena em 3 alvos (SSIM e nitidez)' }));
  const fluxosComp = document.createElement('select'); fluxosComp.id = 'comp-fluxo';
  for (const l of linhas) {
    fluxosComp.appendChild(Object.assign(document.createElement('option'),
      { value: l.fluxo_id || l.id, textContent: l.rotulo + ' (' + (l.fluxo_id || l.id) + ')' }));
  }
  const linhaComp = document.createElement('div'); linhaComp.className = 'linha-form';
  linhaComp.appendChild(fluxosComp);
  caixaComp.appendChild(linhaComp);
  const saidaComp = document.createElement('div'); saidaComp.className = 'sub'; saidaComp.id = 'comp-saida';
  caixaComp.appendChild(saidaComp);
  caixaComp.appendChild(botao('Comparar 1.500k / 2.500k / 4.000k', 'marca', async () => {
    saidaComp.textContent = 'gravando a mesma cena nos 3 alvos (a fonte precisa estar livre)...';
    const r = await api('/api/qualidade/comparar', { method: 'POST', body: JSON.stringify(
      { fluxo: fluxosComp.value, alvos: ['1500k', '2500k', '4000k'], segundos: 6 }) });
    const d = r.corpo || {};
    if (!r.ok) { saidaComp.textContent = 'não deu: ' + (d.erro || JSON.stringify(d)); return; }
    saidaComp.textContent = 'mesma cena, mesma fonte — clipes em ' + d.pasta + ' (CSV: ' + d.csv + ')';
    const tb = tabela([{ rotulo: 'Alvo', campo: 'alvo' },
      { rotulo: 'SSIM (vs. original sem perda)', valor: (x) => fmt(x.ssim, 4) },
      { rotulo: 'Nitidez (blur — menor é mais nítido)', valor: (x) => fmt(x.nitidez_blur, 4) },
      { rotulo: 'Tamanho', valor: (x) => fmt(x.mb) + ' MB' }], d.alvos || [], 'sem medição');
    caixaComp.appendChild(tb);
  }));
  caixaComp.appendChild(Object.assign(document.createElement('div'), { className: 'sub',
    textContent: 'O alvo escolhido aqui é o que a coluna "Alvo" grava na câmera: o número sozinho ' +
      'não decide por você — abra os clipes, veja a imagem e diga qual ainda serve.' }));
  t.appendChild(caixaComp);
}

function telaTempoReal(t) {
  const topo = document.createElement('div'); topo.className = 'caixa-form';
  topo.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Streaming agora' }));
  const linha = document.createElement('div'); linha.className = 'linha-form'; topo.appendChild(linha);
  const resumo = document.createElement('div'); resumo.className = 'sub'; resumo.id = 'tempo-resumo';
  linha.appendChild(resumo);
  const tabelaBox = document.createElement('div');
  const dizer = (txt) => { resumo.textContent = txt; };
  t.appendChild(topo); t.appendChild(tabelaBox);

  const desenharAgora = (m) => {
    const tot = m.total || {};
    const fmt = (v, casas) => (v === null || v === undefined) ? '—' : Number(v).toLocaleString('pt-BR', { maximumFractionDigits: casas === undefined ? 2 : casas });
    const lk = m.link || {}; const net = m.latencia_internet || {};
    dizer('Atualizado ' + (m.em || '').slice(11, 19) + ' · ' + (tot.fluxos || 0) + ' fluxo(s) no ar · ' +
      'compressão agora: ' + fmt(tot.compressao_pct) + '% · ' +
      'entrada ' + fmt(tot.entrada_mbps, 3) + ' Mbps → saída ' + fmt(tot.saida_mbps, 3) + ' Mbps · ' +
      'economia ' + fmt(tot.economia_mbps, 3) + ' Mbps · enviado ' + fmt(tot.mb_enviados, 2) + ' MB / ' +
      '| internet local: ' + (net.disponivel ? fmt(net.ms_medio, 0) + ' ms (' + net.fonte + ')' : 'sem resposta') + ' · ' +
      'link (SRT): RTT ' + fmt(lk.rtt_ms, 2) + ' ms · capacidade ' + fmt(lk.capacidade_link_mbps, 2) + ' Mbps · ' +
      'atraso do buffer ' + fmt(lk.atraso_buffer_ms, 0) + ' ms · perda ' + fmt(lk.perda_recebida_pct, 2) + '% · ' +
      'qualidade mínima (SSIM): ' + ((tot.qualidade_min_ssim === null || tot.qualidade_min_ssim === undefined)
        ? 'não medida' : Number(tot.qualidade_min_ssim).toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 4 }) +
          (tot.qualidade_min_ok ? '' : ' ⚠ abaixo do piso')));
    limpar(tabelaBox);
    const linhas = (m.fluxos || []).map((f) => ({
      fluxo: ((f.camera_rotulo && f.camera_rotulo !== f.fluxo_id)
        ? f.camera_rotulo + ' (' + f.fluxo_id + ')' : f.fluxo_id) +
        (f.sem_cadastro ? ' ⚠ fluxo no ar SEM CADASTRO — cadastre no PC de captura e publique no lado terra' : ''),
      vivo: !!f.vivo,
      comprimindo: f.vivo ? 'sim' : (f.erro ? 'ERRO: ' + f.erro : 'sem sinal'),
      entrada: (f.entrada_mbps === null ? '—' : fmt(f.entrada_mbps, 3) + ' Mbps' +
        ((f.entrada_fonte || '').indexOf('bruto') === 0 ? ' (bruto)' : '')),
      saida: (f.saida_mbps === null ? '—' : fmt(f.saida_mbps, 3) + ' Mbps'),
      compressao: (f.compressao_pct === null ? '—' : fmt(f.compressao_pct) + '%'),
      qualidade: (() => {
        const q = f.qualidade;
        if (!q || q.ssim === null || q.ssim === undefined) return '— (não medida)';
        const ssim = Number(q.ssim).toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
        const piso = Number(q.piso).toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
        return ssim + (q.passa ? ' ✔ (piso ' + piso + ')' : ' ⚠ abaixo do piso ' + piso) +
          (q.idade_s === null || q.idade_s === undefined ? '' : ' · medida ' +
            (q.idade_s < 90 ? Math.round(q.idade_s) + ' s atrás' : Math.round(q.idade_s / 60) + ' min atrás')) +
          ' · ajuste ' + (q.ajuste || '—');
      })(),
      economia: (f.economia_mbps === null ? '—' : fmt(f.economia_mbps, 3) + ' Mbps'),
      agora: (f.mbps_agora === null || f.mbps_agora === undefined ? '—' : fmt(f.mbps_agora, 3) + ' Mbps'),
      enviado: (f.mb_enviados === null || f.mb_enviados === undefined ? '—' : fmt(f.mb_enviados, 2) + ' MB'),
      fps: f.fps_agora === null || f.fps_agora === undefined ? '—' : fmt(f.fps_agora, 1),
      perdidos: f.perdidos === null || f.perdidos === undefined ? '—' : f.perdidos,
      leitores: f.leitores === null || f.leitores === undefined ? '—' : f.leitores,
      no_ar: (f.segundos_no_ar === null || f.segundos_no_ar === undefined ? '—' : Math.round(f.segundos_no_ar) + ' s')
    }));
    tabelaBox.appendChild(tabela([
      { rotulo: 'Fluxo', campo: 'fluxo' },
      { rotulo: 'Enviando', campo: 'comprimindo' },
      { rotulo: 'Entrada (original)', campo: 'entrada' },
      { rotulo: 'Saída (na rede)', campo: 'saida' },
      { rotulo: 'Compressão agora', campo: 'compressao' },
      { rotulo: 'Qualidade do vídeo (SSIM)', campo: 'qualidade' },
      { rotulo: 'Banda economizada', campo: 'economia' },
      { rotulo: 'Taxa agora', campo: 'agora' },
      { rotulo: 'Total enviado', campo: 'enviado' },
      { rotulo: 'fps', campo: 'fps' },
      { rotulo: 'Perdidos', campo: 'perdidos' },
      { rotulo: 'Espectadores', campo: 'leitores' },
      { rotulo: 'No ar há', campo: 'no_ar' },
      { rotulo: 'Câmera', valor: (l) => botao(l.vivo ? 'desligar' : 'ligar', 'mini', async () => {
          // desligar solta o dispositivo de captura (a camera "desliga" sem mexer em cabo);
          // ligar reabre com o ultimo ajuste dela. ONDE A CAPTURA NAO E' DESTA MAQUINA (lado terra) o
          // clique vira ORDEM para o bordo (dono, 19/11/2026): antes o lado terra tentava abrir dshow no
          // Linux e a tela respondia "Unknown input format: 'dshow'" / codigo 234.
          const r = await api('/api/cameras/' + (l.vivo ? 'desligar' : 'ligar'),
                              { method: 'POST', body: JSON.stringify({ camera_id: l.fluxo }) });
          const recado = (r.corpo && r.corpo.recado) || '';
          dizer(r.ok ? (r.corpo && r.corpo.enviado_ao_bordo ? 'ordem enviada ao bordo: '
                        : (l.vivo ? 'câmera desligada: ' : 'câmera ligada: ')) + l.fluxo
                        + (recado ? ' — ' + recado : '')
                     : 'não deu para ' + (l.vivo ? 'desligar' : 'ligar') + ': ' +
                       ((r.corpo && r.corpo.erro) || 'sem resposta'));
          carregar();
        }) },
      { rotulo: 'Qualidade', valor: (l) => botao('medir agora', 'mini', async () => {
          dizer('medindo a qualidade de ' + l.fluxo + ' (8 s, precisa da fonte livre)...');
          const r = await api('/api/qualidade/medir', { method: 'POST', body: JSON.stringify({ fluxo: l.fluxo }) });
          dizer(r.ok
            ? 'qualidade medida em ' + l.fluxo + ': SSIM ' + Number(r.corpo.ssim).toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 4 }) + ' (' + r.corpo.segundos + ' s de amostra)'
            : 'não deu para medir: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)));
          carregar();
        }) }
    ], linhas, 'nenhum fluxo no ar agora: publique um vídeo em "Enviar vídeo"'));
  };
  const carregar = async () => {
    const r = await fetch('/api/metricas');
    if (!r.ok) { dizer('sem permissão para ver as métricas'); return; }
    desenharAgora(await r.json());
  };
  carregar();
  if (timerTempo) { clearInterval(timerTempo); timerTempo = null; }
  if (timerProducao) { clearInterval(timerProducao); timerProducao = null; }
  timerTempo = setInterval(() => { if (A.tela === 'tempo') carregar(); }, 2000);
}

function telaUsuarios(t) {
  if (A.usuario.papel !== 'admin') { t.appendChild(recado('Somente o administrador do sistema vê e cria usuários.', true)); return; }
  const caixa = document.createElement('div'); caixa.className = 'caixa-form';
  caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Novo usuário' }));
  // Quem cria usuário é o administrador — não existe cadastro pelo próprio usuário (dono, 17/11/2026).
  caixa.appendChild(recado('Quem cadastra usuários é o administrador. Não existe cadastro pelo próprio usuário: '
    + 'quem não estiver aqui não entra. "técnico" é a conta de quem captura a bordo (vê "Enviar vídeo" na bancada).', false));
  const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
  const email = campo(linha, 'u-email', 'E-mail', '');
  const nome = campo(linha, 'u-nome', 'Nome', '');
  const papel = campo(linha, 'u-papel', 'Papel (cliente | operador | admin | tecnico)', 'cliente');
  const cli = campo(linha, 'u-cliente', 'Cliente (só para papel cliente)', '');
  const onde = document.createElement('div'); caixa.appendChild(onde);
  caixa.appendChild(botao('Criar usuário', 'marca', async () => {
    const r = await api('/api/usuarios', { method: 'POST', body: JSON.stringify({ email: email.value.trim(), nome: nome.value,
      papel: papel.value.trim(), cliente_id: cli.value.trim() || null }) });
    await atualizar();
    if (r.ok) mostrarRecado('usuário criado: ' + r.corpo.email
      + (r.corpo.supabase && r.corpo.supabase !== 'ok' && r.corpo.supabase !== 'atualizado'
        ? ' — ATENÇÃO: a credencial não subiu para o Supabase (' + r.corpo.supabase + '); use "redefinir senha" quando a rede voltar'
        : ''), false, r.corpo.senha_inicial);
    else mostrarRecado('recusado: ' + JSON.stringify(r.corpo), true);
  }));
  // A credencial do login é a do Supabase: quem não tem lá não consegue entrar, mesmo com senha
  // local. "verificar" pergunta ao Supabase UMA vez (é rede: só quando o operador pede).
  const verificar = botao('verificar credenciais no Supabase', 'mini', async () => {
    const r = await api('/api/usuarios?credencial=1');
    if (r.ok && r.corpo) { A.usuarios = r.corpo.usuarios || A.usuarios; A.verificarCredencial = true; }
    else mostrarRecado('não deu para verificar agora: ' + JSON.stringify(r.corpo || {}), true);
    atualizar();
  });
  onde.appendChild(verificar);
  t.appendChild(caixa);
  t.appendChild(tabela([{ rotulo: 'E-mail', campo: 'email' }, { rotulo: 'Nome', campo: 'nome' }, { rotulo: 'Papel', campo: 'papel' },
    { rotulo: 'Cliente', campo: 'cliente_id' }, { rotulo: 'Ativo', valor: (l) => (l.ativo ? 'sim' : 'não') },
    { rotulo: 'Credencial', valor: (l) => (l.supabase === true ? 'ok' : l.supabase === false ? 'NÃO (não entra)' : 'não verificado') },
    { rotulo: 'Sessões', campo: 'sessoes' }, { rotulo: 'Criado', campo: 'criado_em' },
    { rotulo: 'Ação', valor: (l) => {
        const c = document.createElement('span');
        c.appendChild(botao(l.ativo ? 'desativar' : 'ativar', 'mini', async () => {
          const r = await api('/api/usuarios/' + encodeURIComponent(l.id) + '/ativo', { method: 'POST', body: JSON.stringify({ ativo: !l.ativo }) });
          if (!r.ok) alert(JSON.stringify(r.corpo)); await atualizar();
        }));
        c.appendChild(botao('redefinir senha', 'mini', async () => {
          const r = await api('/api/usuarios/' + encodeURIComponent(l.id) + '/senha', { method: 'POST', body: JSON.stringify({}) });
          if (!r.ok) return mostrarRecado('recusado: ' + JSON.stringify(r.corpo), true);
          mostrarRecado('senha nova de ' + r.corpo.email, false, r.corpo.senha_nova);
          if (String(r.corpo.supabase || '').startsWith('falhou') || r.corpo.supabase === 'sem_chave_servico') {
            mostrarRecado('ATENÇÃO: a senha nova não subiu para o Supabase (' + r.corpo.supabase + ') — nesta rede o login do usuário pode falhar', true);
          }
          await atualizar();
        }));
        return c;
      } }], A.usuarios, 'nenhum usuário'));
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
let timerTempo = null;
let timerProducao = null;
const mbps = (k) => (k === null || k === undefined || k === '' ? '—' : (k / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 2 }) + ' Mbps');
const numOu = (v, u) => (v === null || v === undefined || v === '' ? '—' : (Math.round(v * 10) / 10).toLocaleString('pt-BR') + ' ' + (u || ''));

function telaProducao(t) {
  const topo = document.createElement('div'); topo.className = 'caixa-form';
  topo.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Produção: embarcação, câmera e os números do período' }));
  const linha = document.createElement('div'); linha.className = 'linha-form'; topo.appendChild(linha);
  const selDias = document.createElement('select'); selDias.id = 'prod-dias';
  for (const d of [1, 7, 15, 30, 90]) selDias.appendChild(Object.assign(document.createElement('option'), { value: String(d), textContent: 'últimos ' + d + ' dia(s)', selected: d === 30 }));
  const rot1 = document.createElement('div'); rot1.className = 'campo'; rot1.appendChild(Object.assign(document.createElement('label'), { textContent: 'Período' })); rot1.appendChild(selDias);
  const selEmb = document.createElement('select'); selEmb.id = 'prod-embarcacao';
  selEmb.appendChild(Object.assign(document.createElement('option'), { value: '', textContent: 'todas as embarcações' }));
  const rot2 = document.createElement('div'); rot2.className = 'campo'; rot2.appendChild(Object.assign(document.createElement('label'), { textContent: 'Embarcação' })); rot2.appendChild(selEmb);
  const selCam = document.createElement('select'); selCam.id = 'prod-camera';
  selCam.appendChild(Object.assign(document.createElement('option'), { value: '', textContent: 'todas as câmeras' }));
  const rot3 = document.createElement('div'); rot3.className = 'campo';
  rot3.appendChild(Object.assign(document.createElement('label'), { textContent: 'Câmera' })); rot3.appendChild(selCam);
  const rot4 = document.createElement('div'); rot4.className = 'campo';
  rot4.appendChild(Object.assign(document.createElement('label'), { textContent: 'Mostrar' }));
  const selEnv = document.createElement('select'); selEnv.id = 'prod-so-enviando';
  for (const [v, r] of [['0', 'todas'], ['1', 'só as que estão enviando']]) {
    selEnv.appendChild(Object.assign(document.createElement('option'), { value: v, textContent: r }));
  }
  rot4.appendChild(selEnv);
  linha.appendChild(rot1); linha.appendChild(rot2); linha.appendChild(rot3); linha.appendChild(rot4);
  const resumo = document.createElement('div'); resumo.className = 'sub'; resumo.id = 'prod-resumo';
  topo.appendChild(resumo);
  const grade = document.createElement('div'); grade.className = 'grade-cartoes'; grade.id = 'prod-cartoes';
  t.appendChild(topo); t.appendChild(grade);

  // Nuvem: os mesmos números vistos do lado do Supabase. O navegador não tem chave nenhuma — quem lê
  // é o servidor em terra, pela rota /api/supabase.
  const nuvem = document.createElement('div'); nuvem.className = 'caixa-form'; nuvem.id = 'prod-nuvem';
  nuvem.appendChild(Object.assign(document.createElement('h2'),
    { textContent: 'Supabase: produção e disponibilidade gravadas na nuvem' }));
  const nuvemSub = document.createElement('div'); nuvemSub.className = 'sub'; nuvemSub.id = 'nuvem-resumo';
  const nuvemTab = document.createElement('div'); nuvemTab.id = 'nuvem-tabela';
  nuvem.appendChild(nuvemSub); nuvem.appendChild(nuvemTab);
  t.appendChild(nuvem);
  const dizerResumo = (txt) => { resumo.textContent = txt; };
  const fmt = (v, casas) => (v === null || v === undefined) ? '—' : Number(v).toLocaleString('pt-BR', { maximumFractionDigits: casas === undefined ? 2 : casas });

  const cartao = (c) => {
    const el = document.createElement('div'); el.className = 'cartao';
    const cab = document.createElement('div'); cab.className = 'cartao-cab';
    cab.innerHTML = '<strong>' + c.embarcacao + '</strong><span class="tag ' + (c.estado === 'enviando' ? 'ok' : 'off') + '">' + c.estado + '</span>';
    el.appendChild(cab);
    const cam = document.createElement('div'); cam.className = 'cartao-camera';
    cam.textContent = '📷 ' + c.camera + (c.sem_historico ? ' · enviando agora (sem minuto fechado ainda)' : '');
    el.appendChild(cam);
    const itens = [
      ['Média de compressão', c.compressao_medio_pct === null ? '—' : fmt(c.compressao_medio_pct) + '%'],
      ['Qualidade do vídeo (SSIM)', (c.qualidade && c.qualidade.ssim !== null && c.qualidade.ssim !== undefined)
        ? fmt(c.qualidade.ssim, 4) + (c.qualidade.passa ? '' : ' ⚠ abaixo do piso ' + fmt(c.qualidade.piso, 4)) +
          (c.qualidade.idade_s === null || c.qualidade.idade_s === undefined ? ''
            : ' · medida ' + (c.qualidade.idade_s < 90 ? Math.round(c.qualidade.idade_s) + ' s atrás' : Math.round(c.qualidade.idade_s / 60) + ' min atrás')) +
          ' · ajuste ' + (c.qualidade.ajuste || '—')
        : '— (não medida ainda)'],
      ['Banda utilizada', (c.banda_utilizada_mbps === null ? '—' : fmt(c.banda_utilizada_mbps, 3) + ' Mbps')],
      ['Banda economizada', (c.banda_economizada_mbps === null ? '—' : fmt(c.banda_economizada_mbps, 3) + ' Mbps'
        + (c.entrada_mbps ? ' (entrada ' + fmt(c.entrada_mbps, 3) + ' Mbps' +
            ((c.entrada_fonte || '').indexOf('bruto') === 0 ? ', bruto teórico da captura' : '') + ')' : ''))],
      ['Horas de streaming', fmt(c.horas_streaming) + ' h'],
      ['Disponibilidade', (c.disponibilidade_pct === null || c.disponibilidade_pct === undefined)
        ? '—' : fmt(c.disponibilidade_pct, 2) + '% (' + fmt(c.minutos_no_ar, 0) + ' de ' + fmt(A.prodJanelaMin, 0) + ' min)'],
      ['Enviado no período', fmt(c.mb_enviados) + ' MB']
    ];
    const ul = document.createElement('div'); ul.className = 'cartao-numeros';
    for (const [k, v] of itens) {
      const l = document.createElement('div'); l.innerHTML = '<span>' + k + '</span><b>' + v + '</b>';
      ul.appendChild(l);
    }
    el.appendChild(ul);
    return el;
  };

  const puxar = async (forcar) => {
    const q = '?dias=' + encodeURIComponent(selDias.value) +
      (selEmb.value ? '&embarcacao=' + encodeURIComponent(selEmb.value) : '') +
      (selCam.value ? '&camera=' + encodeURIComponent(selCam.value) : '') +
      (selEnv.value === '1' ? '&so_enviando=1' : '');
    const r = await fetch('/api/producao' + q);
    if (!r.ok) { dizerResumo('sem permissão para ver a produção'); return; }
    const d = await r.json();
    /* Nada mudou no período pedido? Não remonta os cartões nem os seletores (antes a tela de
       produção era limpa e repintada a cada 30 s, mesmo sem novidade nenhuma). */
    const marcaProd = JSON.stringify(d, (k, v) => ((k === 'agora' || k === 'gerado_em' || k === 'lido_em'
      || k === 'atualizado_em' || k === 'idade_s' || k === 'em') ? undefined : v));
    if (!forcar && marcaProd === A.prodMarca) return;
    A.prodMarca = marcaProd;
    if (selEmb.options.length <= 1 && (d.embarcacoes || []).length) {
      for (const e of d.embarcacoes) selEmb.appendChild(Object.assign(document.createElement('option'), { value: e.id, textContent: e.nome || e.id }));
    }
    const tr = (d.tempo_real && d.tempo_real.total) || {};
    A.prodJanelaMin = d.janela_efetiva_min || 0;
    const antes = selCam.value;
    selCam.innerHTML = '';
    selCam.appendChild(Object.assign(document.createElement('option'), { value: '', textContent: 'todas as câmeras' }));
    for (const [idc, nomec] of (d.cameras || [])) {
      selCam.appendChild(Object.assign(document.createElement('option'), { value: idc, textContent: nomec }));
    }
    if (antes) selCam.value = antes;
    const horas = (d.janela_efetiva_min || 0) / 60;
    dizerResumo('janela pedida: ' + d.dias + ' dia(s) · o sistema já roda ' + fmt(horas, 1) + ' h (desde ' + (d.desde || '').replace('T', ' ') +
      ') — a disponibilidade usa esse período, não os ' + d.dias + ' dias cheios · ' +
      (d.so_enviando ? 'mostrando só as que estão enviando · ' : '') +
      (d.camera ? 'câmera "' + (d.cards[0] ? d.cards[0].camera : d.camera) + '" · ' : '') +
      (d.total.cards || 0) + ' câmera(s)' + (d.total.enviando ? ' (' + d.total.enviando + ' enviando)' : '') + ' · ' + fmt(d.total.horas_streaming) + ' h no ar · ' +
      'economia somada ' + fmt(d.total.banda_economizada_mbps, 3) + ' Mbps · ' +
      'agora: ' + (tr.enviando || 0) + ' enviando de ' + (tr.fluxos || 0) + ' no ar · ' +
      'qualidade mínima (SSIM): ' + ((d.total.qualidade_min_ssim === null || d.total.qualidade_min_ssim === undefined)
        ? 'não medida' : fmt(d.total.qualidade_min_ssim, 4) + (d.total.qualidade_min_ok ? '' : ' ⚠ abaixo do piso')));
    limpar(grade);
    const lista = (d.cards || []).slice().sort((a, b) => a.embarcacao.localeCompare(b.embarcacao) || a.camera.localeCompare(b.camera));
    if (!lista.length) {
      grade.appendChild(Object.assign(document.createElement('div'), { className: 'nota', textContent: 'sem histórico no período: o sistema fecha o histórico minuto a minuto enquanto há envio no ar' }));
    }
    for (const c of lista) grade.appendChild(cartao(c));
    puxarNuvem();
  };

  const puxarNuvem = async () => {
    try {
      const r = await fetch('/api/supabase');
      const d = await r.json();
      if (!r.ok) { nuvemSub.textContent = d.erro || 'sem permissão para ver os dados do Supabase'; nuvemTab.innerHTML = ''; return; }
      if (!d.configurado) { nuvemSub.textContent = 'servidor sem Supabase configurado (' + (d.erro || 'sem URL/chave') + ')'; nuvemTab.innerHTML = ''; return; }
      if (d.erro) { nuvemSub.textContent = 'a nuvem respondeu com erro: ' + d.erro; nuvemTab.innerHTML = ''; return; }
      const p = d.producao || [], porFluxo = {};
      for (const x of (d.disponibilidade || [])) porFluxo[x.fluxo_id] = x;
      nuvemSub.textContent = p.length + ' fluxo(s) na nuvem · lido ' + (d.em || '').replace('T', ' ');
      nuvemTab.innerHTML = '';
      nuvemTab.appendChild(tabela(
        ['Fluxo', 'Embarcação', 'Câmera', 'Compressão média', 'Banda utilizada', 'Enviado', 'Horas', 'Disponibilidade', 'Último minuto'],
        p.map((x) => {
          const dd = porFluxo[x.fluxo_id] || {};
          return [x.fluxo_id, x.embarcacao || '—', x.camera || '—',
            (x.compressao_medio_pct === null || x.compressao_medio_pct === undefined) ? '—' : fmt(x.compressao_medio_pct) + '%',
            (x.banda_utilizada_mbps === null || x.banda_utilizada_mbps === undefined) ? '—' : fmt(x.banda_utilizada_mbps, 3) + ' Mbps',
            fmt(x.mb_enviados) + ' MB', fmt(x.horas_streaming) + ' h',
            (dd.disponibilidade_pct === null || dd.disponibilidade_pct === undefined) ? '—' : fmt(dd.disponibilidade_pct, 2) + '%',
            (x.ultimo_minuto || '—').replace('T', ' ').replace('+00:00', ' UTC')];
        }),
        'nenhum minuto gravado no Supabase ainda'));
    } catch (e) { nuvemSub.textContent = 'não consegui falar com o servidor: ' + e.message; }
  };
  selDias.addEventListener('change', puxar);
  selEmb.addEventListener('change', puxar);
  selCam.addEventListener('change', puxar);
  selEnv.addEventListener('change', puxar);
  puxar(true);   /* primeira pintura da tela de produção: sempre desenha */
  if (timerProducao) { clearInterval(timerProducao); timerProducao = null; }
  timerProducao = setInterval(() => { if (A.tela === 'producao') puxar(); }, 30000);
}


function telaEnvios(t) {
  if (!(A.usuario.papel === 'admin' || A.usuario.papel === 'operador')) {
    t.appendChild(recado('Só a operação e o administrador enviam vídeo de teste.', true)); return;
  }
  const guardado = A.envioForm || {};

  // O REDESENHO PERIODICO RECRIA OS CAMPOS. Se o operador esta' digitando quando a tela se redesenha,
  // o campo nasce de novo, perde o foco e o resto do texto vai para lugar nenhum — era o "o app volta
  // ao estado anterior". Aqui o foco e o cursor VOLTAM para o mesmo campo depois do redesenho.
  const focoAntes = (() => {
    const a = document.activeElement;
    if (!a || !a.id || (a.tagName !== 'INPUT' && a.tagName !== 'TEXTAREA')) return null;
    try { return { id: a.id, ini: a.selectionStart, fim: a.selectionEnd }; } catch (e) { return { id: a.id }; }
  })();

  const ehOperador = A.usuario.papel === 'operador';

  /* PEDIDOS DOS CLIENTES: SO' A OPERACAO ve' e cancela (dono, 18/11/2026: "nao vejo motivo pra
     'Transmissoes pedidas pelos clientes' existir no admin, esse tipo de informacao e' irrelevante pra
     mim, precisa estar apenas no canal do cliente"). O admin nao ve' esta lista; o cliente ja' tem a
     dele (pedir/ver a transmissao) em app/app.js. Quem cancela o pedido de outra pessoa e' a operacao. */
  let caixaPedidos = null, listaPedidos = null;
  if (ehOperador) {
    caixaPedidos = document.createElement('div'); caixaPedidos.className = 'caixa-form'; caixaPedidos.id = 'env-pedidos';
    caixaPedidos.appendChild(Object.assign(document.createElement('h2'),
      { textContent: 'Transmissões pedidas pelos clientes' }));
    listaPedidos = document.createElement('div'); caixaPedidos.appendChild(listaPedidos);
    caixaPedidos.appendChild(botao('atualizar lista', 'mini', () => carregarPedidos()));
    t.appendChild(caixaPedidos);
  }

  /* TETO DO PRODUTO + TRILHA DAS GRAVACOES: caixa propria — vale para o admin e para a operacao. */
  const caixaOps = document.createElement('div'); caixaOps.className = 'caixa-form'; caixaOps.id = 'env-operacao';
  t.appendChild(caixaOps);

  /* TETO DO PRODUTO (plano, Fase 3 P2): o maximo que QUALQUER cliente pode escolher. So' o
     administrador mexe; o cliente ve a lista dele ja' cortada por este numero. */
  const linhaTeto = document.createElement('p'); linhaTeto.className = 'nota'; linhaTeto.id = 'env-teto';
  if (A.usuario.papel === 'admin') {
    linhaTeto.appendChild(Object.assign(document.createElement('b'),
      { textContent: 'Teto do produto (o máximo que qualquer cliente pode escolher): ' }));
    const selTeto = document.createElement('select'); selTeto.className = 'mini'; selTeto.id = 'teto-produto';
    const OPCOES = [['0', 'sem teto'], ['300', '5 min'], ['900', '15 min'], ['1800', '30 min'],
                    ['3600', '60 min'], ['7200', '120 min']];
    for (const [v, r] of OPCOES) {
      selTeto.appendChild(Object.assign(document.createElement('option'), { value: v, textContent: r }));
    }
    linhaTeto.appendChild(selTeto);
    linhaTeto.appendChild(document.createTextNode(' '));
    linhaTeto.appendChild(botao('gravar teto', 'mini', async () => {
      const rr = await api('/api/transmissao/teto',
                           { method: 'POST', body: JSON.stringify({ tempo_maximo_s: selTeto.value }) });
      const dd = rr.corpo || {};
      mostrarRecado(rr.ok
        ? ('teto do produto = ' + (dd.teto_do_produto_s ? (dd.teto_do_produto_s / 60) + ' min' : 'sem teto'))
        : ('recusado: ' + JSON.stringify(dd)), !rr.ok);
      carregarPedidos();
    }));
  } else {
    linhaTeto.textContent = 'só o administrador define o teto do produto.';
  }
  caixaOps.appendChild(linhaTeto);

  /* TRILHA DAS GRAVACOES (dono, 18/11/2026): a VPS guarda o arquivo so' ate' o cliente baixar e sair
     — o que FICA e' esta trilha: quem gravou, quanto tinha, se baixou e quando o arquivo foi apagado. */
  const tituloGrav = document.createElement('p'); tituloGrav.className = 'nota'; tituloGrav.id = 'env-grav-titulo';
  tituloGrav.textContent = 'Gravações (o arquivo só fica na VPS até o cliente baixar e sair da tela; '
    + 'o histórico fica):';
  caixaOps.appendChild(tituloGrav);
  const listaGravacoes = document.createElement('div'); listaGravacoes.id = 'env-gravacoes';
  caixaOps.appendChild(listaGravacoes);

  function restanteEmTexto(seg) {
    const s = Math.max(0, parseInt(seg || 0, 10));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  function tamanhoEmMB(bytes) { return (Math.max(0, bytes || 0) / 1048576).toFixed(1) + ' MB'; }

  function horaCurta(carimbo) { return carimbo ? (carimbo + '').replace('T', ' ').slice(0, 19) : '—'; }

  async function carregarPedidos() {
    if (listaPedidos) listaPedidos.textContent = 'procurando os pedidos abertos...';
    const r = await api('/api/transmissao/pedidos');
    const d = r.corpo || {};
    if (listaPedidos) limpar(listaPedidos);
    limpar(listaGravacoes);
    if (!r.ok) {
      // o admin NAO tem a lista de pedidos (so' a operacao tem): a falha aparece junto das gravacoes.
      const aviso = recado('não consegui ler os pedidos/gravações: ' + JSON.stringify(d), true);
      (listaPedidos || listaGravacoes).appendChild(aviso);
      return;
    }
    const selTeto = document.getElementById('teto-produto');
    if (selTeto) selTeto.value = String(d.teto_do_produto_s || 0);
    listaGravacoes.appendChild(tabela([
      { rotulo: 'Começou', valor: (l) => horaCurta(l.comecou_em) },
      { rotulo: 'Embarcação', valor: (l) => l.embarcacao_nome || l.embarcacao_id },
      { rotulo: 'Câmera', valor: (l) => l.camera_id },
      { rotulo: 'Quem gravou', valor: (l) => l.usuario_email },
      { rotulo: 'Tamanho', valor: (l) => tamanhoEmMB(l.bytes)
          + (l.segundos ? ' · ' + restanteEmTexto(l.segundos) : '') },
      { rotulo: 'Baixou', valor: (l) => (l.baixada_em ? 'sim — ' + horaCurta(l.baixada_em) : 'não') },
      { rotulo: 'Arquivo', valor: (l) => (l.no_disco
          ? (l.baixar_ate ? 'no disco · o cliente tem até ' + horaCurta(l.baixar_ate) : 'no disco')
          : (l.apagada_em ? 'apagado em ' + horaCurta(l.apagada_em) : 'ainda não pronto')) },
    ], (d.gravacoes || []), 'nenhuma gravação ainda'));

    if (listaPedidos) listaPedidos.appendChild(tabela([
      { rotulo: 'Embarcação', valor: (l) => l.embarcacao_nome || l.embarcacao_id },
      { rotulo: 'Câmera', valor: (l) => l.camera_rotulo || l.camera_id },
      { rotulo: 'Quem pediu', valor: (l) => l.usuario_email },
      { rotulo: 'Tempo', valor: (l) => Math.round((l.segundos_max || 0) / 60) + ' min' },
      { rotulo: 'Estado', valor: (l) => (l.estado === 'no_ar' ? 'no ar' : 'pedido enviado')
          + (l.gravando ? ' · gravando' : '') },
      { rotulo: 'Restante', valor: (l) => restanteEmTexto(l.segundos_restantes) },
      { rotulo: 'Cancelar', valor: (l) => botao('cancelar pedido', 'mini', async () => {
          const rr = await api('/api/transmissao/' + encodeURIComponent(l.id) + '/cancelar',
                               { method: 'POST', body: '{}' });
          const dd = rr.corpo || {};
          mostrarRecado(rr.ok
            ? (dd.cancelada
                ? ('pedido cancelado' + (dd.camera_mandada_parar
                    ? ' — o bordo foi mandado parar' : ' — outro cliente continua vendo'))
                : ('nada a cancelar: ' + (dd.motivo || '')))
            : ('recusado: ' + JSON.stringify(dd)), !rr.ok);
          carregarPedidos();
        }) }], (d.pedidos || []), 'nenhum pedido aberto agora'));
  }
  carregarPedidos();

  /* O QUE FICA NA TELA DO ADMIN (dono, 18/11/2026: "por que esses testes de video estao na minha tela?
     isso nao e' necessario e ainda da' o aspecto de baguncado"): transmissao ao vivo, teto do produto e a
     trilha das gravacoes. O caminho de bancada (comprimir, medir, publicar) fica so' com a OPERACAO. */
  const LISTA_ALVO = ['', '1500k', '1200k', '1000k', '800k', '500k', '300k'];

  const caixa = document.createElement('div'); caixa.className = 'caixa-form';
  caixa.appendChild(Object.assign(document.createElement('h2'),
    { textContent: ehOperador ? 'Teste de vídeo (bancada): comprimir, medir e publicar + transmissão ao vivo'
                              : 'Transmitir ao vivo (contínuo)' }));

  // Para onde vão os fluxos DESTA máquina (PC de captura -> lado terra). Endereço de serviço interno:
  // a API só entrega para a operação, e o navegador do cliente nunca recebe este dado.
  const linhaDestino = document.createElement('p'); linhaDestino.className = 'nota'; linhaDestino.id = 'env-destino';
  linhaDestino.textContent = 'procurando para onde vão os vídeos desta máquina...';
  caixa.appendChild(linhaDestino);
  fetchCaptura('/api/envios/destino').then((r) => r.json()).then((d) => {
    linhaDestino.textContent = d && d.repassa
      ? `Os vídeos desta máquina sobem, já comprimidos, para ${d.destino}.`
      : 'Nada sai desta máquina: o repasse para o lado terra não está configurado (config.json: destinoSrt).';
  }).catch((e) => { linhaDestino.textContent = 'não consegui falar com o servidor: ' + e.message; });

  /* A "Qualidade por câmera (lista fechada)" SAIU da tela (dono, 18/11/2026). A banda do que esta' no ar
     agora e' escolhida na propria transmissao ao vivo, abaixo — uma escolha, num lugar so'. */

  const linha1 = document.createElement('div'); linha1.className = 'linha-form'; caixa.appendChild(linha1);
  const rm = document.createElement('div'); rm.appendChild(Object.assign(document.createElement('label'), { textContent: 'De onde vem o vídeo' }));
  const modo = document.createElement('select'); modo.id = 'env-modo';
  const MODOS = [['arquivo', 'arquivo do computador'], ['url', 'link (http ou YouTube)'],
                 ['camera', 'câmera ligada nesta máquina (ao vivo)'],
                 ['sintetica', 'teste sintético (sem câmera nenhuma)'],
                 ['radar', 'radar da embarcação (sinal .drq ou pela rede)']];
  // bancada (arquivo/link) so' aparece para a OPERACAO: a tela do admin e' transmissao ao vivo.
  for (const [v, r] of MODOS.filter(([vv]) => ehOperador || (vv !== 'arquivo' && vv !== 'url'))) {
    const o = document.createElement('option'); o.value = v; o.textContent = r; modo.appendChild(o);
  }
  rm.appendChild(modo); linha1.appendChild(rm);
  const ra = document.createElement('div'); ra.appendChild(Object.assign(document.createElement('label'), { textContent: 'Arquivo de vídeo' }));
  const arquivo = document.createElement('input'); arquivo.type = 'file'; arquivo.accept = 'video/*'; arquivo.id = 'env-arquivo';
  ra.appendChild(arquivo); linha1.appendChild(ra);
  const url = campo(linha1, 'env-url', 'Link do vídeo', '');
  const rv = document.createElement('div');
  rv.appendChild(Object.assign(document.createElement('label'), { textContent: 'Webcam / dispositivo' }));
  const dispositivo = document.createElement('select'); dispositivo.id = 'env-dispositivo';
  const avisoDisp = document.createElement('div'); avisoDisp.id = 'env-dispositivo-aviso';
  avisoDisp.className = 'nota'; avisoDisp.style.display = 'none';
  rv.appendChild(dispositivo); rv.appendChild(avisoDisp); linha1.appendChild(rv);
  const rs = document.createElement('div');
  rs.appendChild(Object.assign(document.createElement('label'), { textContent: 'Segundos a capturar' }));
  const segundos = document.createElement('input'); segundos.type = 'number'; segundos.min = '3'; segundos.max = '120';
  segundos.value = '10'; segundos.id = 'env-segundos'; rs.appendChild(segundos); linha1.appendChild(rs);

  const linha2 = document.createElement('div'); linha2.className = 'linha-form'; caixa.appendChild(linha2);
  const rotulo = campo(linha2, 'env-rotulo', 'Rótulo na tela', '');
  /* QUALIDADE (dono, 18/11/2026: "diferente dos testes de video, nao consigo escolher a qualidade do
     video, continua com a caixa de selecao antiga, sem a selecao de 1500 a 300 kbps"). Fonte VIVA escolhe
     BANDA na lista fechada (a mesma do radar e do alvo por camera); arquivo/link (bancada) continuam
     escolhendo CRF — ali "qualidade" e' compressao, nao banda. */
  const rq = document.createElement('div');
  const rotuloQualidade = Object.assign(document.createElement('label'), { textContent: 'Qualidade (banda do vídeo)' });
  rq.appendChild(rotuloQualidade);
  const qualidade = document.createElement('select'); qualidade.id = 'env-qualidade';
  const QUALIDADE_CRF = [['auto', 'automático — maior compressão sem perder qualidade (recomendado)'],
                         ['crf26', 'melhor imagem (comprime menos)'], ['crf30', 'equilibrado'],
                         ['crf34', 'máxima compressão (imagem mais simples)']];
  const ehVivo = () => (modo.value === 'camera' || modo.value === 'sintetica' || modo.value === 'radar');
  const preencherQualidade = () => {
    const querido = qualidade.value;
    qualidade.innerHTML = '';
    const lista = ehVivo() ? LISTA_ALVO.map((v) => [v, v ? v.replace('k', ' kbps') : 'padrão da tela'])
                           : QUALIDADE_CRF;
    for (const [v, r] of lista) {
      const o = document.createElement('option'); o.value = v; o.textContent = r; qualidade.appendChild(o);
    }
    qualidade.value = lista.some(([v]) => v === querido) ? querido : (ehVivo() ? '' : 'auto');
    rotuloQualidade.textContent = ehVivo() ? 'Qualidade (banda do vídeo)' : 'Qualidade (quanto comprimir)';
  };
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
  btnComprimir.id = 'env-comprimir';

  // ---- RADAR da embarcação (Fase 6, 17/11/2026) ------------------------------------------------
  // Cada embarcação pode ter o SEU radar (fonte, modo de imagem e taxa), como o alvo por câmera:
  // a escolha fica GRAVADA na embarcação e passa a ser o padrão dos próximos envios dela.
  const linhaRadar = document.createElement('div'); linhaRadar.className = 'linha-form';
  linhaRadar.id = 'env-radar'; caixa.appendChild(linhaRadar);
  const rEmb = document.createElement('div');
  rEmb.appendChild(Object.assign(document.createElement('label'), { textContent: 'Embarcação do radar' }));
  const radarEmbarcacao = document.createElement('select'); radarEmbarcacao.id = 'env-radar-embarcacao';
  rEmb.appendChild(radarEmbarcacao); linhaRadar.appendChild(rEmb);
  const radarFonte = campo(linhaRadar, 'env-radar-fonte', 'Fonte do sinal (.drq ou tcp://host:porta)', '');
  const rModo = document.createElement('div');
  rModo.appendChild(Object.assign(document.createElement('label'), { textContent: 'Imagem do radar' }));
  const radarModo = document.createElement('select'); radarModo.id = 'env-radar-modo';
  for (const [v, r] of [['ppi', 'PPI (imagem de radar)'], ['cru', 'cru (radiais desdobrados)']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = r; radarModo.appendChild(o);
  }
  rModo.appendChild(radarModo); linhaRadar.appendChild(rModo);
  const rTaxa = document.createElement('div');
  rTaxa.appendChild(Object.assign(document.createElement('label'), { textContent: 'Taxa do radar' }));
  const radarTaxa = document.createElement('select'); radarTaxa.id = 'env-radar-taxa';
  for (const [v, r] of [['30fps', '30 imagens por segundo'], ['volta', '1 imagem por volta']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = r; radarTaxa.appendChild(o);
  }
  rTaxa.appendChild(radarTaxa); linhaRadar.appendChild(rTaxa);
  const rAlvoRadar = document.createElement('div');
  rAlvoRadar.appendChild(Object.assign(document.createElement('label'), { textContent: 'Alvo do radar (banda)' }));
  const radarAlvo = document.createElement('select'); radarAlvo.id = 'env-radar-alvo';
  for (const v of ['1500k', '1200k', '1000k', '800k', '500k', '300k']) {
    const o = document.createElement('option'); o.value = v; o.textContent = v; radarAlvo.appendChild(o);
  }
  rAlvoRadar.appendChild(radarAlvo); linhaRadar.appendChild(rAlvoRadar);
  const rGravar = document.createElement('div');
  const btnGravarRadar = botao('Gravar na embarcação', '', () => {});
  const radarAviso = document.createElement('div'); radarAviso.className = 'nota'; radarAviso.id = 'env-radar-aviso';
  rGravar.appendChild(btnGravarRadar); rGravar.appendChild(radarAviso); linhaRadar.appendChild(rGravar);
  // O recado fica guardado junto com o formulario: a tela se redesenha sozinha e o cartao novo tem de
  // mostrar de novo o que o operador acabou de ver ("gravado"/"recusado") em vez de apagar com uma leitura.
  const mostrarAvisoRadar = (texto, acao) => {
    radarAviso.textContent = texto;
    A.radarAviso = { texto: texto, em: Date.now(), acao: !!acao };
  };
  const avisoDoOperadorRecente = () =>
    !!(A.radarAviso && A.radarAviso.acao && (Date.now() - A.radarAviso.em) < 10000);
  if (A.radarAviso) radarAviso.textContent = A.radarAviso.texto;

  let radarAcao = 0;                     // numero da acao do operador (leitura velha nao apaga recado novo)
  const lerRadarDaEmbarcacao = async () => {
    // CORRIDA REAL (17/11/2026, vista na prova de tela): a leitura inicial do radar podia chegar DEPOIS do
    // operador gravar/errar e sobrescrever o aviso dele ("gravado"/"recusado" virava "ainda nao tem radar
    // gravado"). Cada leitura tira um numero e so' escreve se NINGUEM agiu no meio.
    const meu = radarAcao;
    try {
      const q = radarEmbarcacao.value ? ('?embarcacao_id=' + encodeURIComponent(radarEmbarcacao.value)) : '';
      const r = await fetchCaptura('/api/embarcacoes/radar' + q);
      const j = await r.json();
      if (radarAcao !== meu) return;      // o operador agiu enquanto isto voltava: nao apago o recado dele
      if (!r.ok) { radarAviso.textContent = j.erro || ('erro ' + r.status); return; }
      // REDESENHO NO MEIO DA DIGITACAO (17/11/2026): o que o operador JA' escolheu/digitou no radar nao
      // pode sumir quando a tela se redesenha sozinha — o que esta' na tela (A.radarForm) vence o gravado.
      const guardado = A.radarForm;
      if (radarEmbarcacao.dataset.preenchido !== '1') {
        radarEmbarcacao.innerHTML = '';
        for (const e of (j.embarcacoes || [])) {
          const o = document.createElement('option'); o.value = e.id; o.textContent = e.nome || e.id;
          radarEmbarcacao.appendChild(o);
        }
        radarEmbarcacao.dataset.preenchido = '1';
        if (j.radar && j.radar.embarcacao_id) radarEmbarcacao.value = j.radar.embarcacao_id;
      }
      if (guardado && guardado.embarcacao_id) radarEmbarcacao.value = guardado.embarcacao_id;
      const cfg = j.radar || {};
      radarFonte.value = guardado ? guardado.fonte : (cfg.fonte || '');
      radarModo.value = guardado ? guardado.modo : (cfg.modo || 'ppi');
      radarTaxa.value = guardado ? guardado.taxa : (cfg.taxa || '30fps');
      radarAlvo.value = guardado ? guardado.alvo : (cfg.alvo || '1500k');
      const aviso = cfg.fonte
        ? ('gravado nesta embarcação: ' + cfg.modo + ' / ' + cfg.taxa + (cfg.alvo ? ' / ' + cfg.alvo : ''))
        : 'esta embarcação ainda não tem radar gravado';
      // nao apago o recado do operador com uma leitura que chegou depois da acao dele
      if (!avisoDoOperadorRecente()) mostrarAvisoRadar(aviso, false);
    } catch (e) {
      radarAviso.textContent = 'não consegui ler a config do radar (' + e.message + ')';
    }
  };
  btnGravarRadar.onclick = async () => {
    radarAcao += 1;                      // marca a acao: leitura que voltar atrasada nao apaga este recado
    guardarRadarNaTela();                // o que foi gravado tambem fica guardado na tela (redesenho nao perde)
    const corpo = { embarcacao_id: radarEmbarcacao.value, fonte: radarFonte.value.trim(),
      modo: radarModo.value, taxa: radarTaxa.value, alvo: radarAlvo.value };
    const r = await fetchCaptura('/api/embarcacoes/radar', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) });
    const j = await r.json();
    mostrarAvisoRadar(r.ok
      ? ('gravado: ' + j.radar.modo + ' / ' + j.radar.taxa + (j.radar.alvo ? ' / ' + j.radar.alvo : ''))
      : ('recusado: ' + (j.erro || r.status) + (j.modos ? ' · opções: ' + j.modos.join(', ') : '')), true);
  };
  const guardarRadarNaTela = () => {
    A.radarForm = { embarcacao_id: radarEmbarcacao.value, fonte: radarFonte.value,
                    modo: radarModo.value, taxa: radarTaxa.value, alvo: radarAlvo.value };
  };
  for (const el of [radarFonte, radarModo, radarTaxa, radarAlvo]) {
    el.addEventListener('input', guardarRadarNaTela);
    el.addEventListener('change', guardarRadarNaTela);
  }
  // O que o operador ja' tinha digitado/gravado volta JUNTO com a linha (na hora, sem esperar o servidor):
  // entre a montagem e a leitura que volta da rede havia uma janela em que os campos ficavam vazios — e um
  // clique nessa janela gravava "informe a fonte do radar" (corrida vista na prova de tela, 17/11/2026).
  if (A.radarForm) {
    radarFonte.value = A.radarForm.fonte || '';
    radarModo.value = A.radarForm.modo || 'ppi';
    radarTaxa.value = A.radarForm.taxa || '30fps';
    radarAlvo.value = A.radarForm.alvo || '1500k';
  }
  radarEmbarcacao.onchange = () => { A.radarForm = null; lerRadarDaEmbarcacao(); };
  lerRadarDaEmbarcacao();

  linha3.appendChild(btnComprimir);
  const btnPublicar = botao('2) Publicar no ar (a última compressão)', '', () => {});
  if (ehOperador) linha3.appendChild(btnPublicar);   // publicar a compressão é bancada (só a operação)
  const progresso = document.createElement('div'); progresso.className = 'sub'; progresso.id = 'env-progresso';
  linha3.appendChild(progresso);
  const dizer = (txt) => { A.envioProgresso = txt; progresso.textContent = txt; };
  if (A.envioProgresso) progresso.textContent = A.envioProgresso;
  t.appendChild(caixa);

  const legenda = document.createElement('div'); legenda.className = 'sub';
  legenda.textContent = 'Fonte viva (webcam do notebook ou teste sintético) transmite CONTINUAMENTE, igual à operação: ' +
    'a imagem é a real da câmera e o envio só para quando você clicar em "parar". ' +
    'Arquivo e link continuam com o caminho de comprimir, medir e publicar. ' +
    'Entrada = tamanho do seu vídeo original · Saída = tamanho depois de comprimir · ' +
    'Compressão = quanta banda foi economizada · Tempo = quanto a compressão levou · Qualidade = semelhança com o ' +
    'original (1,000 = idêntico) · No ar = desde quando o vídeo comprimido está publicado.' +
        ' · PISO: compressão de pelo menos 73% e qualidade de pelo menos 0,9733 nominal, com margem de 0,002 ' +
    '(aceita 0,9713: 0,9720 numa compressão de 78% entra) — abaixo disso a linha fica com ✗.';
  if (ehOperador) t.appendChild(legenda);   // a legenda de medições (CRF, SSIM, pisos) é da bancada

  const guardar = () => { A.envioForm = { modo: modo.value, url: url.value, rotulo: rotulo.value,
    qualidade: qualidade.value, fps: fps.value, audio: audio.value, repetir: repetir.value,
    dispositivo: dispositivo.value, segundos: segundos.value }; };
  for (const el of [modo, url, rotulo, qualidade, fps, audio, repetir, dispositivo, segundos]) {
    el.addEventListener('input', guardar); el.addEventListener('change', guardar);
  }
  if (guardado.modo) {
    modo.value = guardado.modo; url.value = guardado.url || ''; rotulo.value = guardado.rotulo || '';
    qualidade.value = guardado.qualidade || 'auto'; fps.value = guardado.fps || '30';
    audio.value = guardado.audio || '0'; repetir.value = guardado.repetir || '1';
    if (guardado.segundos) segundos.value = guardado.segundos;
  }
  if (focoAntes) {   // devolve o foco/cursor: o redesenho nao pode interromper quem esta' digitando
    const alvo = document.getElementById(focoAntes.id);
    if (alvo && typeof alvo.focus === 'function') {
      alvo.focus();
      if (focoAntes.ini !== undefined) { try { alvo.setSelectionRange(focoAntes.ini, focoAntes.fim); } catch (e) { /* select */ } }
    }
  }
  let semCamera = false;                 // nenhuma camera nesta maquina (nunca finge uma)
  const preencherDispositivos = async (tentativa = 0) => {
    if (dispositivo.dataset.pronto) return;
    const MOTIVO = 'Câmera ligada NESTA máquina aparece com o Servidor local no ar e base http://127.0.0.1:8765 '
      + '— o menu do aplicativo tem "Testar câmeras desta máquina".';
    let r = null;
    try {
      r = await fetchCaptura('/api/dispositivos');
    } catch (e) {
      // O SERVIDOR LOCAL PODE ESTAR SUBINDO (python + banco + ffmpeg levam alguns segundos) ou ter caído.
      // Antes isto deixava a caixa VAZIA e calada — era o "não está reconhecendo câmeras" (18/11/2026).
      if (tentativa < 6) { setTimeout(() => preencherDispositivos(tentativa + 1), 1500); return; }
      dispositivo.innerHTML = '';
      const o = document.createElement('option');
      o.value = ''; o.textContent = '— lista de câmeras indisponível —'; o.disabled = true;
      dispositivo.appendChild(o);
      semCamera = true;
      avisoDisp.style.display = '';
      avisoDisp.textContent = 'não consegui falar com o servidor que lista as câmeras (' + e.message + '). ' + MOTIVO;
      btnComprimir.disabled = (modo.value === 'camera');
      return;                      // sem `pronto`: quando o servidor subir, a próxima troca de modo tenta de novo
    }
    if (!r.ok) {
      // Antes voltava calada: com o endereco apontado para o lado terra e sem sessao a API responde
      // erro, a lista ficava vazia e nada dizia o motivo (foi o "nao acha as cameras" no cliente).
      let erro = '';
      try { erro = ((await r.json()) || {}).erro || ''; } catch (e) {}
      dispositivo.innerHTML = '';
      const o = document.createElement('option');
      o.value = ''; o.textContent = '\u2014 lista de c\u00e2meras indispon\u00edvel \u2014'; o.disabled = true;
      dispositivo.appendChild(o);
      semCamera = true;
      avisoDisp.style.display = '';
      avisoDisp.textContent = 'a API em uso (' + location.origin + ') respondeu HTTP ' + r.status +
        (erro ? ' (' + erro + ')' : '') + '. C\u00e2mera ligada NESTA m\u00e1quina aparece com o Servidor local no ar e ' +
        'base http://127.0.0.1:8765 \u2014 o menu do aplicativo tem "Testar c\u00e2meras desta m\u00e1quina".';
      btnComprimir.disabled = (modo.value === 'camera');
      dispositivo.dataset.pronto = '1';
      return;
    }
    const d = await r.json();
    // `dispositivos` traz o seletor unico (@device_pnp_...) de cada camera: e' o que permite
    // DUAS cameras de mesmo nome existirem ao mesmo tempo (antes as duas viravam a mesma e a
    // segunda era recusada como ja cadastrada). `video` (nomes) fica como reserva.
    const cams = (d.dispositivos && d.dispositivos.length)
      ? d.dispositivos.map((x) => ({ valor: x.seletor || x.video, rotulo: x.rotulo || x.video }))
      : (d.video || []).map((v) => ({ valor: v, rotulo: v }));
    dispositivo.innerHTML = '';
    semCamera = !cams.length;
    if (semCamera) {
      const o = document.createElement('option');
      o.value = ''; o.textContent = '— nenhuma câmera nesta máquina —'; o.disabled = true;
      dispositivo.appendChild(o);
      avisoDisp.style.display = '';
      // quando não há câmera nenhuma, a causa mais comum é ffmpeg ausente: dizer isso, e não só "vazio"
      const ff = (d.ffmpeg || {}).ffmpeg || {};
      const sobreFfmpeg = /^nenhum/.test(ff.origem || '')
        ? 'o app não achou o ffmpeg (nem embutido, nem no PATH da máquina): sem ele nenhuma câmera é listada. '
        : '';
      avisoDisp.textContent = sobreFfmpeg + ((d.pedido_de === 'outra_maquina')
        ? 'esta tela est\u00e1 em ' + location.origin + ' e a lista vem de "' + (d.maquina || 'outra máquina') + '" (lado terra): câmera ligada NESTA máquina só ' +
          'aparece com o Servidor local no ar e base http://127.0.0.1:8765. ' + (d.motivo || '')
        : (d.motivo || d.erro || 'nenhuma câmera encontrada nesta máquina'));
      btnComprimir.disabled = (modo.value === 'camera');
      dispositivo.dataset.pronto = '1';
      return;
    }
    avisoDisp.style.display = 'none';
    for (const v of cams) {
      const o = document.createElement('option'); o.value = v.valor; o.textContent = v.rotulo; dispositivo.appendChild(o);
    }
    btnComprimir.disabled = false;
    dispositivo.dataset.pronto = '1';
  };
  const trocarModo = () => {
    const ehArquivo = modo.value === 'arquivo';
    const ehLink = modo.value === 'url';
    const ehViva = modo.value === 'camera' || modo.value === 'sintetica' || modo.value === 'radar';
    const ehRadar = modo.value === 'radar';
    arquivo.parentElement.style.display = ehArquivo ? '' : 'none';
    url.parentElement.style.display = ehLink ? '' : 'none';
    rv.style.display = modo.value === 'camera' ? '' : 'none';
    linhaRadar.style.display = ehRadar ? '' : 'none';
    rs.style.display = 'none';            // fonte viva: envio CONTÍNUO, sem tempo determinado
    cy.style.display = ehViva ? 'none' : '';   // transmissão contínua não repete em laço
    // a lista de qualidade muda com o modo: fonte viva escolhe BANDA (1500k...300k), bancada escolhe CRF
    preencherQualidade();
    // streaming não tem "comprimir e medir" nem "publicar depois": é ao vivo, direto
    btnComprimir.textContent = ehRadar ? 'Transmitir o radar ao vivo' : (ehViva ? 'Transmitir ao vivo (contínuo)' : '1) Comprimir e medir');
    btnComprimir.disabled = (modo.value === 'camera' && semCamera);
    btnPublicar.style.display = ehViva ? 'none' : '';
    if (modo.value === 'camera') preencherDispositivos();
  };
  modo.onchange = () => { trocarModo(); guardar(); };
  trocarModo();
  // O guardado volta DEPOIS do primeiro desenho: a lista de qualidade muda com o modo (banda no vivo,
  // CRF na bancada) e um valor salvo so' pode ser reposto quando as opcoes certas ja' estao na tela.
  if (LISTA_ALVO.includes(guardado.qualidade || '') && ehVivo()) qualidade.value = guardado.qualidade;

  const lista = document.createElement('div'); lista.id = 'env-compressoes'; if (ehOperador) t.appendChild(lista);
  let ultimos = [];

  /* NO AR AGORA (tela do ADMIN): a bancada sai, mas o envio contínuo que o próprio admin ligou precisa
     de um botão de PARAR — sem isto o "Transmitir ao vivo" não teria como ser encerrado. */
  const caixaNoAr = document.createElement('div'); caixaNoAr.className = 'caixa-form'; caixaNoAr.id = 'env-no-ar';
  caixaNoAr.appendChild(Object.assign(document.createElement('h2'), { textContent: 'No ar agora' }));
  const listaNoAr = document.createElement('div'); caixaNoAr.appendChild(listaNoAr);
  if (!ehOperador) t.appendChild(caixaNoAr);

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
          : (l.compressao_pct > 0 ? '↓ ' : '↑ ') + Math.abs(l.compressao_pct).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + '%' +
            (l.passa_pisos === 1 || l.passa_pisos === true ? ' ✓' : (l.passa_pisos === 0 || l.passa_pisos === false ? ' ✗ (abaixo do piso)' : '')) },
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

  const pararIngestao = async (id) => {
    await fetchCaptura('/api/ingestao/parar', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id, remover: false }) });
    carregar();
  };
  const tabelaNoAr = (ing) => tabela([
    { rotulo: 'Rótulo', valor: (l) => l.rotulo || l.fluxo_id },
    { rotulo: 'Fluxo', valor: (l) => l.fluxo_id },
    { rotulo: 'Desde', valor: (l) => horaCurta(l.criado_em) },
    { rotulo: 'Banda', valor: (l) => (l.bitrate_alvo || '—') + (l.fps ? ' · ' + numOu(l.fps) + ' fps' : '') },
    { rotulo: 'Estado', valor: (l) => (l.estado === 'no_ar' ? 'no ar' : (l.estado || '—')) },
    { rotulo: 'Parar', valor: (l) => botao('parar', 'mini', () => pararIngestao(l.id)) },
  ], (ing || []).filter((l) => l.estado === 'no_ar' || l.estado === 'iniciando'), 'nada no ar agora');

  const carregar = async () => {
    const ri = await fetchCaptura('/api/ingestoes');
    const ing = ri.ok ? ((await ri.json()).ingestoes || []) : [];
    if (!ehOperador) {
      limpar(listaNoAr);
      if (!ri.ok) { listaNoAr.appendChild(recado('não consegui ler os envios desta máquina.', true)); return; }
      listaNoAr.appendChild(tabelaNoAr(ing));
      return;
    }
    const r = await fetchCaptura('/api/compressoes');
    if (!r.ok) { limpar(lista); lista.appendChild(recado('Sem permissão para ver as compressões.', true)); return; }
    const d = await r.json();
    ultimos = d.compressoes || [];
    limpar(lista);
    // Se a montagem da tabela falhar (um campo inesperado numa linha), a tela diz o motivo em vez de
    // ficar sem tabela nenhuma — o operador precisa ver que algo deu errado, nao uma area vazia.
    try {
      lista.appendChild(montarTabela(ultimos, ing));
    } catch (e) {
      lista.appendChild(recado('não consegui montar a tabela de compressões: ' + (e && e.message ? e.message : e), true));
    }
  };
  const publicar = async (id) => {
    dizer('publicando no ar…');
    const r = await fetchCaptura('/api/compressao/publicar', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id }) });
    const j = await r.json();
    dizer(r.status === 201 ? ('no ar como "' + j.fluxo_id + '"') : ('falhou: ' + (j.erro || r.status)));
    if (r.status === 201) A.ultimaCompressao = id;
    carregar();
  };
  const pararFluxo = async (l) => {
    const ri = await fetchCaptura('/api/ingestoes');
    const ing = ri.ok ? ((await ri.json()).ingestoes || []) : [];
    const g = ing.filter((x) => x.fluxo_id === l.fluxo_id).pop();
    if (!g) { dizer('não achei o fluxo para parar'); return; }
    await fetchCaptura('/api/ingestao/parar', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: g.id, remover: false }) });
    dizer('parei "' + l.fluxo_id + '"');
    carregar();
  };
  const remover = async (id) => {
    await fetchCaptura('/api/compressao/remover', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id }) });
    carregar();
  };
  const resumo = (j) => 'comprimido: ' + j.entrada.mb + ' MB → ' + j.comprimido.mb + ' MB · ' +
    (j.corte_pct > 0 ? '↓ ' : '↑ ') + Math.abs(j.corte_pct) + '% · qualidade ' + (j.ssim === null ? '—' : j.ssim) +
    ' · ' + j.tempo_encode_s + ' s' + (j.crf ? ' · CRF ' + j.crf : '') +
    (j.passa_pisos ? ' · PISO ✓ (≥73% e ≥0,9713 · nominal 0,9733)' : ' · ATENÇÃO — ' + (j.aviso_pisos || 'abaixo do piso')) +
    '. Agora clique em "Publicar no ar".';

  btnComprimir.onclick = () => {
    const r = (rotulo.value || '').trim(), b = qualidade.value, qf = fps.value, aud = audio.value;
    if (modo.value === 'radar') {
      // RADAR (Fase 3/5/6): a fonte do sinal (.drq ou tcp://host:porta), o modo de imagem e a taxa vêm
      // da tela (o que ficou gravado na embarcação já aparece preenchido); o servidor desenha e sobe
      // pela MESMA cadeia da câmera.
      const emb = radarEmbarcacao.value;
      dizer('ligando o radar ao vivo… (envio contínuo: só para quando você mandar)');
      fetchCaptura('/api/ingestao/ao-vivo', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tipo: 'radar', fonte: radarFonte.value.trim(), modo: radarModo.value,
          taxa: radarTaxa.value, bitrate: radarAlvo.value, embarcacao_id: emb,
          rotulo: r || ('Radar de ' + emb) }) })
        .then(async (x) => ({ s: x.status, j: await x.json() }))
        .then(({ s, j }) => {
          if (s !== 201) { dizer('não deu para transmitir o radar: ' + (j.erro || s)); return; }
          dizer('NO AR: "' + (j.rotulo || 'radar') + '" (' + radarModo.value + '/' + radarTaxa.value +
            ', alvo ' + j.alvo + '). Acompanhe em Tempo real e Produção; para parar, use "parar" na linha abaixo.');
          carregar();
        });
      return;
    }
    if (modo.value === 'camera' || modo.value === 'sintetica') {
      const tipo = modo.value;
      const nomeFonte = tipo === 'camera' ? ((dispositivo.options[dispositivo.selectedIndex] || {}).textContent || 'webcam do notebook') : 'teste sintético';
      dizer('ligando o envio contínuo de ' + nomeFonte + '… (sem tempo determinado: só para quando você mandar)');
      fetchCaptura('/api/ingestao/ao-vivo', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tipo: tipo, dispositivo: dispositivo.value, fps: Number(qf) || 30,
          bitrate: (qualidade.value || 'auto'),          // banda escolhida na tela (1500k...300k)
          rotulo: r || nomeFonte }) })
        .then(async (x) => ({ s: x.status, j: await x.json() }))
        .then(({ s, j }) => {
          if (s !== 201) { dizer('falhou ao transmitir: ' + (j.erro || s)); return; }
          dizer('NO AR: "' + (j.rotulo || nomeFonte) + '" enviando sem parar (alvo ' + j.alvo + '). ' +
            'Acompanhe em Tempo real e Produção; para parar, use "parar" na linha abaixo.');
          carregar();
        });
      return;
    }
    if (modo.value === 'arquivo') {
      const f = arquivo.files && arquivo.files[0];
      if (!f) { dizer('escolha o arquivo de vídeo'); return; }
      const q = new URLSearchParams({ nome: f.name, qualidade: b, fps: qf, audio: aud });
      const x = new XMLHttpRequest();
      x.open('POST', urlDeCaptura('/api/ingestao/comprimir') + '?' + q.toString());
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
      fetchCaptura('/api/ingestao/comprimir', { method: 'POST', headers: { 'Content-Type': 'application/json' },
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
  if (timerTempo) { clearInterval(timerTempo); timerTempo = null; }
  if (timerProducao) { clearInterval(timerProducao); timerProducao = null; }
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
$('form-primeiro').addEventListener('submit', primeiroAcesso);
$('btn-sair').addEventListener('click', async () => { await api('/api/sair', { method: 'POST' }); location.reload(); });
$('btn-atualizar').addEventListener('click', atualizar);
document.querySelectorAll('.item[data-tela]').forEach((b) => b.addEventListener('click', () => {
  A.tela = b.dataset.tela;
  document.querySelectorAll('.item[data-tela]').forEach((x) => x.classList.toggle('on', x === b));
  desenhar(true);   // troca de tela pelo menu sempre redesenha
}));
function relogio() { const d = new Date(); const p = (n) => String(n).padStart(2, '0');
  $('relogio-servidor').textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; }
setInterval(relogio, 1000); relogio();
abrir();
