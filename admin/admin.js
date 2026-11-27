/* Admin do projeto e do sistema: acompanhamento (§6) + administracao (clientes, embarcacoes,
   cameras, usuarios, analises, auditoria, saude). Le e escreve tudo pela API do produto. */
const A = { usuario: null, resumo: null, clientes: [], usuarios: [], verificarCredencial: false, sistema: null, cameras: [], embarcacoes: [], licencas: [], tela: 'empresas', timer: null, chaveRevelada: null, marca: null, radarForm: null, radarAviso: null, prontidao: null, config: null, empresaId: null, arvore: null, hd: null, teto: {}, mudancaNova: false };
const $ = (id) => document.getElementById(id);
const limpar = (el) => { while (el.firstChild) el.removeChild(el.firstChild); };
const esc = (s) => String(s === null || s === undefined ? '' : s);

/* LISTA FECHADA de qualidade de envio — UMA fonte so (dono, 26/11/2026). E' o espelho de
   `VALORES_DE_ALVO` em `ground/api.py`: o servidor RECUSA valor fora dela, entao as duas listas tem
   de andar juntas — o teste `tests/test-lista-de-alvos-igual-ao-servidor.py` compara as duas.
   Ordem: do MAIOR para o MENOR (3,0 / 2,5 / 2,0 Mbps entraram nesta rodada). */
const ALVOS_DE_ENVIO = ['3000', '2500', '2000', '1500', '1200', '1000', '800', '500', '300'];
const ALVOS_DE_ENVIO_K = ALVOS_DE_ENVIO.map((v) => v + 'k');

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
  if (!A.timer) A.timer = setInterval(() => { if (!digitandoNaTela()) atualizarDoRelogio(); }, 15000);
}

function digitandoNaTela() {
  const a = document.activeElement;
  return !!(a && a.closest && a.closest('#tela') && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
}

/* Telas em que o usuario esta' TRABALHANDO (formulario): se a tela for reconstruida no meio, o que ele
   digitou/escolheu se perde. O auto-refresh de 15 s NAO repinta estas telas — ele so' AVISA
   (dono, 26/11/2026: "eu estou fazendo algo e do nada a pagina 'pisca' e eu perco o que estou fazendo").
   Quem repinta e' o usuario, pelo botao "Atualizar" (ou trocando de tela). */
const TELAS_DE_FORMULARIO = { empresas: 1, envios: 1, usuarios: 1, licencas: 1,
  medicoes: 1, decisoes: 1, evidencias: 1, documentos: 1 };

/* Le tudo que as telas mostram, SEM desenhar. Separado de `atualizar()` porque o cartao da camera
   recarrega SO' ele depois de uma acao: o resto da tela do usuario fica exatamente como estava. */
async function atualizarDados() {
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
    // LICENCAS do PC de captura (dono, 19/11/2026): a chave que se digita no app de captura.
    const lc = await api('/api/licencas'); A.licencas = (lc.corpo && lc.corpo.licencas) || [];
  } else {
    const cl = await api('/api/clientes'); A.clientes = (cl.corpo && cl.corpo.clientes) || [];
  }
}

/* AÇÃO DO USUÁRIO (salvar, publicar, cadastrar): pode repintar — ele acabou de pedir. Só não repinta
   quando o que a tela mostra não mudou (antes isto desenhava a cada 15 s por causa de campos que
   mudam sozinhos — `gerado_em` do resumo, `uptime_s` do sistema — e a tela era limpa no meio da
   leitura do operador). */
async function atualizar() {
  await atualizarDados();
  const marca = assinaturaTelas();
  if (marca === A.marca) { statusAtualizar('sem mudan\u00e7as desde ' + agora()); return; }
  A.marca = marca; A.mudancaNova = false;
  desenhar();
  statusAtualizar('atualizado ' + agora());
}

/* O AUTO-REFRESH (o timer de 15 s): NUNCA repinta a tela em que o usu\u00e1rio est\u00e1 trabalhando. Chegou
   coisa nova? S\u00f3 avisa — quem repinta \u00e9 ele, pelo bot\u00e3o "Atualizar". */
async function atualizarDoRelogio() {
  await atualizarDados();
  const marca = assinaturaTelas();
  if (marca === A.marca) { statusAtualizar('sem mudan\u00e7as desde ' + agora()); return; }
  if (TELAS_DE_FORMULARIO[A.tela]) {
    A.mudancaNova = true;
    statusAtualizar('h\u00e1 mudan\u00e7a nova \u2014 clique em Atualizar');
    return;
  }
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
const RUIDO_TELA = { gerado_em: 1, uptime_s: 1, idade_s: 1, atualizado_em: 1, lido_em: 1, agora: 1,
  /* Campos que mudam SOZINHOS e nao sao "novidade" para o operador (plano 26/11/2026): o uso da
     licenca, a hora da ultima varredura e o carimbo dos dispositivos. Sem isto a assinatura mudava a
     cada leitura e o timer achava que havia mudanca nova toda vez. */
  ultimo_uso_em: 1, ultimo_em: 1, quando: 1, ultima_varredura: 1, primeira_em: 1 };
function assinaturaTelas() {
  try {
    return JSON.stringify([A.resumo, A.embarcacoes, A.cameras, A.clientes, A.usuarios, A.sistema, A.camerasInterno,
      A.prontidao, A.licencas],
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
  frota: ['Monitoramento da frota', 'Cada embarcação numa linha, com o pior estado primeiro: CPU, memória, disco e rede do computador de captura (o retrato que ele manda sozinho), quando ele falou por último — se está sendo gravado a bordo e o VÍDEO ao vivo, para acompanhar, ligar e parar a câmera (fechando a janela, o que você ligou para).'],
  empresas: ['Empresas e configuração', 'Uma área só: o cliente na raiz, as embarcações vinculadas a ele e, em cada embarcação, as câmeras que a varredura achou — com nome, ligar/desligar, ativar e a qualidade de envio. A chave da licença nasce na embarcação.'],
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
  usuarios: ['Usuários', 'Só o administrador cadastra. Papéis: cliente (vê a empresa; o escopo por embarcação é definido em "escopo de acesso"), operador, administrador, técnico (captura a bordo) e observador (vê todas as empresas, só leitura).'],
  analises: ['Análises de vídeo', 'Contagem e eventos sobem de bordo (Fase 5) — sem agente a bordo a tela fica vazia.'],
  auditoria: ['Auditoria', 'Quem viu qual câmera, quando — e o que foi negado.'],
  marcas: ['Marcas e zonas', 'A linha de contagem e as zonas de risco que o agente de bordo usa, desenhadas aqui.'],
  envios: ['Enviar vídeo', 'Escolhe a fonte (arquivo, link ou câmera desta máquina) e a qualidade por câmera: o sistema codifica, publica em SRT e mede o corte de banda.'],
  saude: ['Saúde do sistema', 'Estado da API, do lado terra e das contagens do banco.'],
  saude_bordo: ['Saúde do bordo', 'O computador de captura reporta sozinho: CPU, memória, disco (e o anel do HD do radar), ffmpeg, captura viva, mediamtx, erros. Semáforo com o limiar e o que fazer.'],
  licencas: ['Licenças do PC de captura', 'A chave que se digita no app de captura: ela liga aquela máquina à empresa e à embarcação. Vale por tempo ou sem prazo, e quantos PCs usam a mesma licença é ajustável.']
};

/* --------------------------------------------------------- telas */
function envioEmAndamento() {
  /* Ha' algo escolhido/digitado na tela de envio que o redesenho apagaria? */
  /* Idem na area unica: se o operador esta' DIGITANDO o nome de uma camera, o redesenho do timer
     devolveria o nome antigo no meio da digitacao (0.12.0). */
  if (A.tela === 'empresas') {
    const foco = document.activeElement;
    return !!(foco && foco.classList && foco.classList.contains('nome-camera'));
  }
  if (A.tela !== 'envios') return false;
  const arq = document.getElementById('env-arquivo');
  if (arq && arq.files && arq.files.length) return true;
  for (const id of ['env-rotulo', 'env-url']) {
    const e = document.getElementById(id);
    if (e && (e.value || '').trim()) return true;
  }
  return false;
}

/* O que o usuário estava vendo, para devolver depois do redesenho: a rolagem da área e o campo em foco
   (com a posição do cursor). Sem isto um redesenho no meio do trabalho "pisca" e joga o usuário para o
   topo da tela (dono, 26/11/2026). A chave do campo vem do dono mais próximo com marcador estável
   (`[data-cam]`/`[data-emb]`) — sem isso, dez cartões com `[data-papel="tipo"]` apontariam para o 1º. */
function chaveDoCampo(a, tela) {
  const partes = [];
  let no = a;
  while (no && no !== tela && no.dataset) {
    if (no.dataset.cam) partes.unshift('[data-cam="' + no.dataset.cam + '"]');
    else if (no.dataset.emb) partes.unshift('[data-emb="' + no.dataset.emb + '"]');
    no = no.parentElement;
  }
  if (a.id) partes.push('#' + a.id);
  else if (a.dataset && a.dataset.papel) partes.push('[data-papel="' + a.dataset.papel + '"]');
  else if (a.className && String(a.className).trim()) partes.push('.' + String(a.className).trim().split(/\s+/)[0]);
  else return '';
  return partes.join(' ');
}

function guardarOLhar(tela) {
  const m = { topo: tela.scrollTop || 0, foco: '', inicio: null, fim: null };
  const a = document.activeElement;
  if (a && a !== document.body && tela.contains(a)) {
    m.foco = chaveDoCampo(a, tela);
    try { m.inicio = a.selectionStart; m.fim = a.selectionEnd; } catch (e) {}
  }
  return m;
}

function devolverOLhar(tela, m) {
  if (!m) return;
  tela.scrollTop = m.topo;
  if (!m.foco) return;
  let alvo = null;
  try { alvo = tela.querySelector(m.foco); } catch (e) { alvo = null; }
  if (!alvo || !alvo.focus) return;
  alvo.focus();
  if (m.inicio !== null && m.inicio !== undefined && alvo.setSelectionRange) {
    try { alvo.setSelectionRange(m.inicio, m.fim); } catch (e) {}
  }
}

function desenhar(forcado) {
  /* NAO repinta a tela de envio enquanto o operador esta' preenchendo: o redesenho recria os campos e
     o que ele digitou/escolheu se perde (medido 18/11/2026: o rotulo digitado sumia e o "Comprimir e
     medir" respondia "escolha o arquivo de video" com o arquivo ja' escolhido). As listas continuam
     se atualizando sozinhas pelo timer delas. Trocar de tela pelo menu manda `forcado` e passa. */
  if (!forcado && envioEmAndamento()) { statusAtualizar('segurando a tela: você está preenchendo o envio'); return; }
  const [titulo, sub] = SUBS[A.tela] || SUBS.painel;
  $('titulo-tela').textContent = titulo; $('sub-tela').textContent = sub;
  const tela = $('tela');
  // O redesenho continua recriando a tela, mas o que o usuario estava vendo volta (rolagem e foco).
  const olhar = guardarOLhar(tela);
  limpar(tela);
  if (timerEnvios) { clearInterval(timerEnvios); timerEnvios = null; }
  if (timerTempo) { clearInterval(timerTempo); timerTempo = null; }
  if (timerProducao) { clearInterval(timerProducao); timerProducao = null; }
  /* Menu e despacho são a MESMA lista (dono, 25/11/2026: nada de tela sem função): as telas antigas
     (clientes/embarcacoes/cameras/producao/tempo/analises/marcas) saíram — o que elas faziam vive
     dentro de "Empresas e configuração" e do "Monitoramento (frota)". */
  const despacho = { empresas: telaEmpresas, frota: telaFrota,
    painel: telaPainel, fases: telaFases, medicoes: telaMedicoes, decisoes: telaDecisoes,
    evidencias: telaEvidencias, documentos: telaDocumentos,
    licencas: telaLicencas, usuarios: telaUsuarios, auditoria: telaAuditoria, envios: telaEnvios,
    saude_bordo: telaSaudeDoBordo, saude: telaSaude };
  const construida = (despacho[A.tela] || telaPainel)(tela);
  // Telas que buscam dados são assíncronas: a olhada só volta depois que os cartões existem na tela.
  if (construida && typeof construida.then === 'function') construida.then(() => devolverOLhar(tela, olhar));
  else devolverOLhar(tela, olhar);
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

/* ------------------------------------------- LICENÇAS DO PC DE CAPTURA (dono, 19/11/2026)
   "quero apenas instalar o app no computador de captura, inserir a chave da licença e assim fazer a
   conexão com a empresa e embarcação cadastradas, e a licença pode ser configurável por tempo ou
   indeterminado". Aqui o admin gera a chave de UMA embarcação, vê e copia de novo (pedido do dono),
   muda o prazo e o número de PCs (ajustável) e revoga. O computador de captura só digita a chave. */
function telaLicencas(t) {
  const nota = document.createElement('p'); nota.className = 'nota';
  nota.appendChild(Object.assign(document.createElement('b'), { textContent: 'Como funciona: ' }));
  nota.appendChild(document.createTextNode('no computador de captura, abra o app e digite a chave — '
    + 'ele passa a capturar as câmeras daquela embarcação, sem gerar instalador próprio. A licença vale '
    + 'por tempo (com data) ou sem prazo (indeterminada). Quantos PCs podem usar a mesma licença é '
    + 'ajustável. Sem internet por dias o bordo continua funcionando normalmente: o corte é só por '
    + 'vencimento ou revogação.'));
  t.appendChild(nota);

  // A CHAVE e' do admin (dono, 19/11/2026): quem nao e' admin nao gera, nao ve' e nao copia — a rota
  // tambem recusa, esta tela so' nao mente para o operador.
  if (A.usuario.papel !== 'admin') {
    t.appendChild(recado('Somente o administrador do sistema gera e vê as licenças do PC de captura.', true));
    return;
  }

  {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Nova licença' }));
    const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);

    const dEmb = document.createElement('div');
    const lEmb = document.createElement('label'); lEmb.textContent = 'Embarcação';
    const sel = document.createElement('select');
    for (const e of A.embarcacoes) {
      const o = document.createElement('option'); o.value = e.id;
      o.textContent = (e.nome || e.id) + ' — ' + e.id; sel.appendChild(o);
    }
    dEmb.appendChild(lEmb); dEmb.appendChild(sel); linha.appendChild(dEmb);

    const dTipo = document.createElement('div');
    const lTipo = document.createElement('label'); lTipo.textContent = 'Validade';
    const tipo = document.createElement('select');
    for (const [v, txt] of [['indeterminada', 'sem prazo (indeterminada)'], ['ate', 'até uma data']]) {
      const o = document.createElement('option'); o.value = v; o.textContent = txt; tipo.appendChild(o);
    }
    dTipo.appendChild(lTipo); dTipo.appendChild(tipo); linha.appendChild(dTipo);

    const dData = document.createElement('div');
    const lData = document.createElement('label'); lData.textContent = 'Vence em';
    const data = document.createElement('input'); data.type = 'date'; data.disabled = true;
    dData.appendChild(lData); dData.appendChild(data); linha.appendChild(dData);
    tipo.addEventListener('change', () => { data.disabled = tipo.value !== 'ate'; });

    const maquinas = campo(linha, 'lic-maquinas', 'Quantos PCs usam esta licença', '1');
    maquinas.type = 'number'; maquinas.min = '1';

    caixa.appendChild(botao('Gerar chave', 'marca', async () => {
      const corpo = { embarcacao_id: sel.value, validade_tipo: tipo.value,
        validade_em: tipo.value === 'ate' ? data.value : '', maquinas_max: Number(maquinas.value || 1) };
      const r = await api('/api/licencas', { method: 'POST', body: JSON.stringify(corpo) });
      await atualizar();
      if (r.ok) mostrarRecado('licença criada para ' + r.corpo.embarcacao_id + ' — chave: ' + r.corpo.chave
        + ' (digite esta chave no computador de captura)', false);
      else mostrarRecado('recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), true);
    }));
    t.appendChild(caixa);
  }

  if (!A.licencas.length) {
    const vazio = document.createElement('p'); vazio.className = 'nota';
    vazio.textContent = 'Nenhuma licença gerada ainda. O computador de captura só entra no sistema depois de digitar uma chave daqui.';
    t.appendChild(vazio);
    return;
  }
  for (const l of A.licencas) t.appendChild(cartaoLicenca(l));
}

function cartaoLicenca(l) {
  const caixa = document.createElement('div'); caixa.className = 'caixa-form';
  const h = document.createElement('h2');
  h.textContent = (l.embarcacao_nome || l.embarcacao_id) + (l.cliente_nome ? ' · ' + l.cliente_nome : '')
    + ' — ' + l.embarcacao_id;
  caixa.appendChild(h);

  const linha = document.createElement('div'); linha.className = 'linha-form';
  const codigo = document.createElement('code');
  codigo.textContent = l.chave; codigo.style.cssText = 'font-size:15px;letter-spacing:1px;user-select:all';
  linha.appendChild(codigo);
  linha.appendChild(botao('copiar chave', 'mini', async () => {
    try { await navigator.clipboard.writeText(l.chave); mostrarRecado('chave copiada: ' + l.chave, false); }
    catch (e) { mostrarRecado('não consegui copiar — selecione a chave e copie na mão', true); }
  }));
  caixa.appendChild(linha);

  const ficha = document.createElement('p'); ficha.className = 'nota';
  ficha.textContent = 'Validade: ' + (l.validade_tipo === 'ate' ? 'até ' + l.validade_em : 'indeterminada (sem prazo)')
    + ' · estado: ' + (l.texto || l.estado) + ' · PCs: ' + l.maquinas_em_uso + '/' + l.maquinas_max + ' usados'
    + (l.maquinas_usadas.length ? ' (' + l.maquinas_usadas.map((m) => m.maquina).join(', ') + ')' : '')
    + (l.ultimo_uso_em ? ' · último uso em ' + l.ultimo_uso_em : ' · ainda não foi usada')
    + (l.criada_por ? ' · criada por ' + l.criada_por : '');
  caixa.appendChild(ficha);

  const acoes = document.createElement('div'); acoes.className = 'linha-form';
  acoes.appendChild(botao('prazo e nº de PCs', 'mini', () => editarLicenca(caixa, l)));
  if (l.status === 'revogada') acoes.appendChild(botao('reativar', 'mini', () => agirLicenca('reativar', l, {})));
  else acoes.appendChild(botao('revogar', 'mini', () => agirLicenca('revogar', l, { motivo: 'revogada pelo admin' })));
  acoes.appendChild(botao('gerar outra chave', 'mini', () => agirLicenca('reemitir', l, {})));
  caixa.appendChild(acoes);
  return caixa;
}

async function agirLicenca(acao, l, corpo) {
  const r = await api('/api/licencas/' + l.id + '/' + acao, { method: 'POST', body: JSON.stringify(corpo || {}) });
  await atualizar();
  const nova = (r.corpo && r.corpo.chave) ? (' — chave nova: ' + r.corpo.chave) : '';
  mostrarRecado(acao + ': ' + (r.ok ? 'ok' + nova : ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo))), !r.ok);
}

function editarLicenca(caixa, l) {
  const antigo = caixa.querySelector('.form-licenca'); if (antigo) antigo.remove();
  const f = document.createElement('div'); f.className = 'form-licenca';
  const linha = document.createElement('div'); linha.className = 'linha-form'; f.appendChild(linha);
  const tipo = document.createElement('select');
  for (const [v, txt] of [['indeterminada', 'sem prazo (indeterminada)'], ['ate', 'até uma data']]) {
    const o = document.createElement('option'); o.value = v; o.textContent = txt;
    if ((l.validade_tipo || 'indeterminada') === v) o.selected = true; tipo.appendChild(o);
  }
  linha.appendChild(tipo);
  const data = document.createElement('input'); data.type = 'date'; data.value = l.validade_em || '';
  data.disabled = tipo.value !== 'ate'; linha.appendChild(data);
  tipo.addEventListener('change', () => { data.disabled = tipo.value !== 'ate'; });
  const n = document.createElement('input'); n.type = 'number'; n.min = '1'; n.value = String(l.maquinas_max || 1);
  n.title = 'quantos PCs podem usar esta licença'; linha.appendChild(n);
  f.appendChild(botao('salvar', 'mini', async () => {
    const r = await api('/api/licencas/' + l.id + '/atualizar', { method: 'POST',
      body: JSON.stringify({ validade_tipo: tipo.value, validade_em: data.value, maquinas_max: Number(n.value || 1) }) });
    await atualizar();
    mostrarRecado(r.ok ? 'licença atualizada (prazo: ' + tipo.value + ' ' + data.value + ', PCs: ' + n.value + ')'
      : 'recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), !r.ok);
  }));
  caixa.appendChild(f);
}

function telaCameras(t) {
  const fmt = (v, casas) => (v === null || v === undefined) ? '—'
    : Number(v).toLocaleString('pt-BR', { maximumFractionDigits: casas === undefined ? 2 : casas });
  if (A.usuario.papel === 'admin' || A.usuario.papel === 'operador') {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Câmera: onde ela está e por onde entra' }));
    const aviso = document.createElement('div'); aviso.className = 'nota';
    /* D1 do dono (25/11/2026): "não vamos poder inserir nem o ip no admin, o cadastro das câmeras ip
       terão que ser no app de captura". Aqui NÃO há mais campo de IP: o endereço da câmera de rede é
       cadastrado no painel do bordo, e a senha vive no arquivo de segredo daquela máquina. O lado
       terra nunca recebe nem o IP nem a senha. */
    aviso.textContent = 'O endereço (IP) de uma câmera de rede é cadastrado NO PC DE CAPTURA, no painel ' +
      'do bordo — nunca aqui: nem o IP nem a senha sobem para o lado terra. As câmeras de HDMI/USB ' +
      'aparecem sozinhas pela varredura.';
    caixa.appendChild(aviso);
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
        for (const op of ['', ...ALVOS_DE_ENVIO_K]) {
          sel.appendChild(Object.assign(document.createElement('option'), {
            value: op, textContent: op ? op.replace('k', ' kbps') : 'padrão da tela',
            selected: (c.alvo || '') === op }));
        }
        // um alvo antigo (ex.: 2500k de antes da lista) continua visível, para não parecer "voltou ao padrão"
        if (c.alvo && !['', ...ALVOS_DE_ENVIO_K].includes(c.alvo)) {
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
        /* Editar EM OPERAÇÃO: muda só o RÓTULO. O endereço (IP/porta/canal) NÃO é editável aqui — o
           dono (25/11/2026): "não vamos poder inserir nem o ip no admin"; o endereço da câmera de rede
           é cadastrado no painel do bordo. */
        cx.appendChild(botao('editar', 'mini', async () => {
          const rot = prompt('Rótulo desta câmera (Enter mantém "' + l.rotulo + '"):', l.rotulo);
          if (rot === null) return;
          const corpo = {};
          if (rot.trim() && rot.trim() !== l.rotulo) corpo.rotulo = rot.trim();
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
  const papel = campo(linha, 'u-papel', 'Papel (cliente | operador | admin | tecnico | observador)', 'cliente');
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
        if (l.papel === 'cliente' || l.papel === 'observador') {
          c.appendChild(botao('escopo de acesso', 'mini', () => abrirEscopo(l)));
        }
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
  const painel = document.createElement('div');
  painel.id = 'escopo-de-acesso';
  t.appendChild(painel);
}

// ESCOPO DE ACESSO do cliente (dono, 19/11/2026: os quatro tipos). O banco guarda o vinculo explicito
// (`usuario_embarcacoes`); sem vinculo nenhum o cliente ve todas as embarcacoes da propria empresa.
// O papel `observador` (Petrobras) nao recebe vinculo: ele ve todas as empresas, so leitura.
async function abrirEscopo(u) {
  const alvo = document.getElementById('escopo-de-acesso');
  if (!alvo) return;
  const r = await api('/api/usuarios/' + encodeURIComponent(u.id) + '/embarcacoes');
  if (!r.ok) { mostrarRecado('não deu para ler o escopo: ' + JSON.stringify(r.corpo || {}), true); return; }
  const d = r.corpo || {};
  alvo.innerHTML = '';
  const cx = document.createElement('div');
  cx.className = 'caixa-form';
  cx.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Escopo de acesso — ' + u.email }));
  if (d.escopo === 'todas_as_empresas') {
    cx.appendChild(recado('Este usuário é o OBSERVADOR (tipo 4): vê todas as embarcações de todas as empresas, '
      + 'e SOMENTE LEITURA — não configura, não cadastra e não opera.', false));
  } else {
    const marcas = [];
    for (const e of (d.embarcacoes || [])) {
      const lab = document.createElement('label');
      lab.style.display = 'block';
      const ck = document.createElement('input');
      ck.type = 'checkbox';
      ck.checked = !!e.concedida;
      ck.dataset.emb = e.id;
      lab.appendChild(ck);
      lab.appendChild(document.createTextNode(' ' + e.nome + ' (' + e.id + ')'));
      cx.appendChild(lab);
      marcas.push(ck);
    }
    if (!(d.embarcacoes || []).length) cx.appendChild(recado('Esta empresa ainda não tem embarcação cadastrada.', true));
    cx.appendChild(botao('Salvar escopo', 'marca', async () => {
      const ids = marcas.filter((c) => c.checked).map((c) => c.dataset.emb);
      const s = await api('/api/usuarios/' + encodeURIComponent(u.id) + '/embarcacoes',
        { method: 'POST', body: JSON.stringify({ embarcacao_ids: ids }) });
      if (!s.ok) return mostrarRecado('recusado: ' + JSON.stringify(s.corpo), true);
      mostrarRecado('escopo salvo: ' + (s.corpo.vinculos
        ? s.corpo.vinculos + ' embarcação(ões) concedida(s) a este cliente'
        : 'sem vínculo — o cliente vê todas as embarcações da própria empresa'), false);
      abrirEscopo(u);
    }));
    cx.appendChild(recado('Nenhuma marcada = TODAS as embarcações da empresa (tipo 3). Uma marcada = uma '
      + 'embarcação (tipo 1). Algumas marcadas = algumas (tipo 2).', false));
  }
  alvo.appendChild(cx);
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
  const LISTA_ALVO = ['', ...ALVOS_DE_ENVIO_K];

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
  for (const v of ALVOS_DE_ENVIO_K) {
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


/* --------------------------------------------------- saude do bordo (0.8.0, Fase 5)
   O bordo ENVIA o retrato; terra guarda e classifica. A tela nao sabe regra nenhuma: mostra o estado e o
   "o que fazer" que vieram prontos — e trata o SILENCIO como problema, nunca como "ok". */
const CORES_DE_SAUDE = { ok: '#22c55e', atencao: '#eab308', problema: '#ef4444' };

function seloDeSaude(estado) {
  const s = document.createElement('span');
  s.className = 'pill';
  s.textContent = ({ ok: 'tudo ok', atencao: 'atenção', problema: 'problema' })[estado] || estado;
  s.style.background = (CORES_DE_SAUDE[estado] || '#64748b') + '22';
  s.style.borderColor = CORES_DE_SAUDE[estado] || '#64748b';
  s.style.color = CORES_DE_SAUDE[estado] || '#94a3b8';
  return s;
}

/* ================================================================ FROTA (dashboard do admin)
   Dono (24/11/2026): "preciso de um dashboard também pro admin para monitoramento" e "preciso também
   que os videos sejam transmitidos no admin para eu acompanhar e monitorar". Uma tela só: cada
   embarcação numa linha, com o pior estado primeiro, os QUATRO números que o computador de captura
   manda sozinho (CPU, memória, disco e rede), quando ele falou por último, a camada POR CÂMERA — e o
   vídeo ao vivo, no MESMO player do cliente (`/fronts/video.js`). Aqui não se liga, não se para e não
   se grava: o admin ACOMPANHA (D3 do dono: "só quem visualiza é o cliente"). */
const PESO_DE_SAUDE = { problema: 0, alerta: 1, ok: 2, '': 3 };

function piorEstadoDo(s) {
  const sinais = (s && s.sinais) || [];
  if (sinais.some((x) => x.estado === 'problema')) return 'problema';
  if (sinais.some((x) => x.estado === 'alerta')) return 'alerta';
  if (sinais.length) return 'ok';
  return (s && s.estado) || '';
}

function tomDoNumero(v, atencao, problema) {
  if (v === null || v === undefined || v === '' || !isFinite(Number(v))) return 'neutro';
  const x = Number(v);
  return x >= problema ? 'ruim' : (x >= atencao ? 'atencao' : 'ok');
}

function numeroDaFrota(v, sufixo, casas) {
  if (v === null || v === undefined || v === '') return '—';
  return Number(v).toFixed(casas === undefined ? 1 : casas) + (sufixo || '');
}

/* O DISCO DA GRAVAÇÃO E A REDE, NA LINHA DO CARTÃO (dono, 27/11/2026: "note que não tem disco e nem
   rede"). A régua é o retrato do PC de captura: disco = onde a gravação do radar está (livre de total,
   com a cota escolhida quando existe); rede = o que a máquina movimentou no último intervalo. Nada de
   traço mudo: o que não foi medido diz "não medido". */
function linhaDoDisco(e) {
  /* Duas telas, dois nomes para a MESMA medida: o item do dashboard da frota usa `disco_*` e o cartão da
     embarcação usa `hd_radar_*`. A régua é uma só (o retrato do bordo) — aqui se aceita os dois nomes. */
  const livre = e.disco_livre_gb !== undefined ? e.disco_livre_gb : e.hd_radar_livre_gb;
  const total = e.disco_total_gb !== undefined ? e.disco_total_gb : e.hd_radar_total_gb;
  const pct = e.disco_usado_pct !== undefined ? e.disco_usado_pct : e.hd_radar_usado_pct;
  const nome = (e.disco_nome ? (e.disco_nome + ' ') : '');
  if (livre === null || livre === undefined || total === null || total === undefined) {
    return 'disco do radar: não medido';
  }
  return 'disco do radar ' + nome + numeroDaFrota(livre) + ' GB livres de ' + numeroDaFrota(total) +
    ' GB' + (pct === null || pct === undefined ? '' : ' (' + numeroDaFrota(pct) + '% usado)') +
    (e.hd_escolha_cota_gb ? ' · cota ' + numeroDaFrota(e.hd_escolha_cota_gb, ' GB', 0) +
      (e.hd_escolha_origem === 'admin' ? ' (escolha do admin)' : ' (padrão)') : '');
}

function linhaDaRede(e) {
  const tot = e.rede || {};
  const sub = e.rede_envio_mbps !== undefined ? e.rede_envio_mbps : tot.enviado_mbps;
  const des = e.rede_recebimento_mbps !== undefined ? e.rede_recebimento_mbps : tot.recebido_mbps;
  const motivo = (e.nao_medido || {}).rede || '';
  if ((sub === null || sub === undefined) && (des === null || des === undefined)) {
    return 'rede: não medida' + (motivo ? ' (' + motivo + ')' : '');
  }
  return 'rede ↑' + numeroDaFrota(sub) + ' / ↓' + numeroDaFrota(des) + ' Mbps agora';
}

function tileDaFrota(rot, valor, pe, tom) {
  const d = document.createElement('div');
  d.className = 'frota-num ' + (tom || 'neutro');
  const r = document.createElement('div'); r.className = 'rot'; r.textContent = rot;
  const v = document.createElement('div'); v.className = 'val'; v.textContent = valor;
  const p = document.createElement('div'); p.className = 'pe'; p.textContent = pe || '';
  d.append(r, v, p);
  return d;
}

/* --------------------------------------------------- AO VIVO do admin: ligar, parar e "gravando a bordo"
   Dono (26/11/2026): "eu devo poder ligar e parar a câmera também" e "só preciso no monitoramento saber
   se está sendo gravado a bordo, não preciso ver as imagens".

   COMO LIGA (2.A, escolhido por ele): o admin abre a MESMA sessão que o cliente abre. Ele é a plateia —
   enquanto esta janela estiver aberta a sessão vive (`batimento`); fechando a janela (ou a aba), a câmera
   PARA. A regra de ouro continua: sem plateia o bordo não transmite. Nada de "ligar" que fica no ar sem
   ninguém olhando — e a Auditoria registra QUAL admin ligou.

   PARAR: se a sessão é deste admin, encerra ela (a câmera para porque ninguém está assistindo). Se a
   câmera está no ar por causa de OUTRO (cliente assistindo), o "parar" usa o desligamento na mão da
   operação (`/api/cameras/desligar`) — o mesmo stand-by que já existe no cartão da câmera.

   O SELO "gravando a bordo" vem do que o BORDO conta (`estado.gravando` + `gravando_medido`). Sem
   medida a tela escreve "não medido" — nunca um zero com cara de saúde. */

const SESSAO_AO_VIVO = {};        // camera_id -> id da transmissão que ESTE admin abriu
let tiqueAoVivo = null;           // o "estou aqui" (é o que mantém a sessão viva)
let tiqueDaGrade = null;          // releitura do estado (repinta SÓ quando muda de verdade)

function seloDaGravacao(c) {
  const e = c.estado || {};
  if (!Number(e.gravando_medido || 0)) return 'gravando a bordo: não medido';
  return Number(e.gravando || 0) ? 'gravando a bordo' : 'sem gravação a bordo';
}

function encerrarSessoesDoAdmin() {
  const ids = Object.values(SESSAO_AO_VIVO);
  for (const cam of Object.keys(SESSAO_AO_VIVO)) delete SESSAO_AO_VIVO[cam];
  for (const tid of ids) {
    try {
      const bolo = new Blob([JSON.stringify({ pendente: true })], { type: 'application/json' });
      const url = '/api/transmissao/' + tid + '/encerrar';
      if (!(navigator.sendBeacon && navigator.sendBeacon(url, bolo))) {
        fetch(url, { method: 'POST', body: '{"pendente":true}', keepalive: true,
                     headers: { 'Content-Type': 'application/json' } });
      }
    } catch (e) { /* sem beacon: a varredura do lado terra encerra depois do prazo */ }
  }
}

function fecharAoVivo() {
  const caixa = document.getElementById('ao-vivo');
  encerrarSessoesDoAdmin();                      /* fechou a janela: a câmera que EU liguei para */
  if (tiqueAoVivo) { clearInterval(tiqueAoVivo); tiqueAoVivo = null; }
  if (tiqueDaGrade) { clearInterval(tiqueDaGrade); tiqueDaGrade = null; }
  if (!caixa) return;
  for (const v of Array.from(caixa.querySelectorAll('video'))) {
    if (v.dataset.admId) { try { window.Video.parar(v.dataset.admId); } catch (e) { /* sem player */ } }
  }
  caixa.remove();
}

async function ligarCameraNoAdmin(camId, botao, pintar) {
  if (botao) { botao.disabled = true; botao.textContent = 'ligando…'; }
  const r = await api('/api/transmissao/iniciar', { method: 'POST',
    body: JSON.stringify({ camera_id: camId }) });
  if (!r.ok) {
    if (botao) { botao.disabled = false; botao.textContent = '▶ ligar'; }
    mostrarRecado('não deu para ligar esta câmera: ' + ((r.corpo && r.corpo.erro) || 'sem resposta do servidor'), true);
    return;
  }
  const t = (r.corpo || {}).transmissao || {};
  if (t.id) SESSAO_AO_VIVO[camId] = t.id;
  mostrarRecado('câmera pedida à máquina de captura: a imagem sobe em alguns segundos ' +
                '(a câmera para quando você fechar esta janela)', false);
  if (botao) botao.textContent = 'aguardando o bordo…';
  if (pintar) pintar();
}

async function pararCameraNoAdmin(camId, botao, pintar) {
  if (botao) { botao.disabled = true; botao.textContent = 'parando…'; }
  const tid = SESSAO_AO_VIVO[camId];
  if (tid) {
    delete SESSAO_AO_VIVO[camId];
    await api('/api/transmissao/' + tid + '/encerrar', { method: 'POST', body: '{}' });
    mostrarRecado('câmera parada: a sua sessão foi encerrada', false);
    if (pintar) pintar();
    return;
  }
  /* No ar por causa de outro: o desligamento na mão da operação (o cliente que está assistindo é
     interrompido — é a decisão de quem opera). */
  const r = await api('/api/cameras/desligar', { method: 'POST', body: JSON.stringify({ camera_id: camId }) });
  mostrarRecado(r.ok ? 'câmera desligada na mão: o bordo vai parar a transmissão'
                     : 'não deu para desligar: ' + ((r.corpo && r.corpo.erro) || 'sem resposta do servidor'),
                !r.ok);
  if (pintar) pintar();
}

/* O VÍDEO AO VIVO no admin: o MESMO player do cliente, com empresa → embarcação → câmeras e, agora, o
   ligar/parar e o selo de gravação em cada janela.
   O SELETOR DENTRO DA JANELA (plano único, 25/11/2026 — dono: "como escolho quais câmeras e de quais
   empresas ou embarcações quero acompanhar?"): empresa → embarcação → câmeras (uma caixa por câmera). */
function abrirAoVivo(frota, embInicial) {
  if (document.getElementById('ao-vivo')) { fecharAoVivo(); return; }
  const empresas = [];
  for (const l of frota) if (!empresas.includes(l.empresa)) empresas.push(l.empresa);
  const linhaInicial = frota.find((l) => embInicial && l.emb.id === embInicial.id) || frota[0] || {};
  const idInicial = (linhaInicial.emb || {}).id || '';

  const caixa = document.createElement('div'); caixa.id = 'ao-vivo';
  const topo = document.createElement('div'); topo.className = 'ao-vivo-topo';
  const titulo = document.createElement('strong'); titulo.id = 'av-titulo'; titulo.textContent = 'Ao vivo';
  const dica = document.createElement('span'); dica.className = 'nota';
  dica.textContent = 'aqui você liga e para a câmera — você é a plateia: fechando esta janela, '
    + 'as câmeras que você ligou param';
  const bFechar = document.createElement('button'); bFechar.className = 'pil';
  bFechar.textContent = 'Fechar'; bFechar.onclick = fecharAoVivo;
  topo.append(titulo, dica, bFechar);
  caixa.appendChild(topo);

  const escolha = document.createElement('div'); escolha.className = 'ao-vivo-escolha';
  const selE = document.createElement('select'); selE.id = 'av-empresa';
  empresas.forEach((nome) => selE.appendChild(Object.assign(document.createElement('option'),
    { value: nome, textContent: nome, selected: nome === linhaInicial.empresa })));
  const selB = document.createElement('select'); selB.id = 'av-emb';
  const camsBox = document.createElement('span'); camsBox.id = 'av-cameras'; camsBox.className = 'nota';
  escolha.append(Object.assign(document.createElement('label'), { textContent: 'Empresa' }), selE,
                 Object.assign(document.createElement('label'), { textContent: 'Embarcação' }), selB);
  caixa.appendChild(escolha);
  const linhaDeCams = document.createElement('div'); linhaDeCams.className = 'ao-vivo-escolha';
  linhaDeCams.appendChild(camsBox);
  caixa.appendChild(linhaDeCams);

  const grade = document.createElement('div'); grade.className = 'grade-adm';
  caixa.appendChild(grade);
  document.body.appendChild(caixa);

  const embsDaEmpresa = () => frota.filter((l) => l.empresa === selE.value);
  const embEscolhida = () => (embsDaEmpresa().find((l) => l.emb.id === selB.value) || embsDaEmpresa()[0] || {}).emb;
  let marcadas = null;                      /* quais câmeras estão marcadas (sobrevive ao repintar) */

  function pintaGrade(cams) {
    for (const v of Array.from(grade.querySelectorAll('video'))) {
      if (v.dataset.admId) { try { window.Video.parar(v.dataset.admId); } catch (e) { /* sem player */ } }
    }
    limpar(grade);
    const emb = embEscolhida() || {};
    const gravando = cams.filter((c) => Number((c.estado || {}).gravando || 0)
      && Number((c.estado || {}).gravando_medido || 0)).length;
    titulo.textContent = 'Ao vivo — ' + (emb.nome || emb.id || '') + '  (' + cams.filter((c) => c.no_ar).length
      + ' de ' + cams.length + ' no ar · gravando a bordo: ' + gravando + ')';
    if (!cams.length) {
      const p = document.createElement('p'); p.className = 'nota';
      p.textContent = 'nenhuma câmera marcada — marque acima as que quer acompanhar';
      grade.appendChild(p); return;
    }
    for (const c of cams) {
      const jan = document.createElement('div'); jan.className = 'janela-adm'; jan.dataset.cam = c.id;
      // o TIPO vai no rótulo: radar de óleo e FLIR são o que o observador (Petrobras/IBAMA) vê
      const tipo = (c.tipo && c.tipo !== 'camera') ? '  · ' + String(c.tipo).toUpperCase() : '';
      const v = document.createElement('video');
      v.muted = true; v.autoplay = true; v.playsInline = true;
      const rot = document.createElement('div'); rot.className = 'rotulo-adm';
      rot.textContent = (c.rotulo || c.id) + tipo + (c.no_ar ? '' : '  · fora do ar');
      const selo = document.createElement('div');
      selo.className = 'nota selo-gravacao' + (Number((c.estado || {}).gravando || 0) ? ' no-ar' : '');
      selo.textContent = seloDaGravacao(c);
      const acoes = document.createElement('div'); acoes.className = 'acoes-da-janela';
      const repintar = () => pintaGrade(camerasMarcadas((embEscolhida() || {}).cameras || []));
      // A SESSÃO DESTE ADMIN CONTA: se ele já pediu e o bordo ainda não abriu o fluxo, o botão tem de
      // continuar sendo "parar" — senão um repintar da releitura oferece "ligar" de novo e abre uma
      // SEGUNDA sessão para a mesma câmera (achado na prova de tela de 26/11/2026).
      const nossa = !!SESSAO_AO_VIVO[c.id];
      if (c.no_ar || nossa) {
        acoes.appendChild(botao('■ parar', 'mini', () => pararCameraNoAdmin(c.id, acoes.firstChild, repintar)));
        jan.append(v, rot, acoes, selo);
        grade.appendChild(jan);
        if (c.no_ar) {
          const id = 'admin-' + c.id;
          v.dataset.admId = id;
          try { window.Video.ligar(id, c.id, v); } catch (e) { /* sem player: fica o rótulo */ }
        } else {
          const espera = document.createElement('div'); espera.className = 'rotulo-adm';
          espera.textContent = 'aguardando o bordo ligar a câmera — você já pediu '
            + '(a câmera para quando você fechar esta janela)';
          jan.insertBefore(espera, acoes);
        }
      } else {
        // sem plateia o bordo não transmite — e agora QUEM liga é você, aqui (2.A).
        const nota = document.createElement('div'); nota.className = 'rotulo-adm';
        nota.textContent = 'sem imagem: o bordo só transmite com alguém assistindo';
        acoes.appendChild(botao('▶ ligar', 'mini', () => ligarCameraNoAdmin(c.id, acoes.firstChild, repintar)));
        jan.append(rot, nota, acoes, selo);
        grade.appendChild(jan);
      }
    }
  }

  function camerasMarcadas(cams) {
    if (!marcadas) return cams;
    return cams.filter((c) => marcadas.has(c.id));
  }

  function pintaCameras() {
    const emb = embEscolhida() || {};
    const cams = emb.cameras || [];
    limpar(camsBox);
    if (!cams.length) {
      camsBox.textContent = 'esta embarcação não tem câmera cadastrada ainda';
      pintaGrade([]);
      return;
    }
    if (!marcadas) marcadas = new Set(cams.map((c) => c.id));
    const caixas = [];
    for (const c of cams) {
      const l = document.createElement('label'); l.className = 'av-cam';
      const k = document.createElement('input'); k.type = 'checkbox'; k.checked = marcadas.has(c.id);
      k.dataset.cam = c.id;
      l.appendChild(k);
      l.appendChild(document.createTextNode(' ' + c.rotulo
        + (c.no_ar ? ' (no ar)' : ' (fora do ar)')
        + (Number((c.estado || {}).gravando_medido || 0)
            ? (Number((c.estado || {}).gravando || 0) ? ' · gravando a bordo' : '')
            : ' · gravação não medida')));
      camsBox.appendChild(l);
      caixas.push(k);
    }
    const pintar = () => {
      for (const k of caixas) { if (k.checked) marcadas.add(k.dataset.cam); else marcadas.delete(k.dataset.cam); }
      pintaGrade(camerasMarcadas(cams));
    };
    for (const k of caixas) k.onchange = pintar;
    pintaGrade(camerasMarcadas(cams));
  }

  /* A releitura: o bordo leva alguns segundos para ligar a câmera. Em vez de remontar a janela inteira
     (o que derrubaria o vídeo e as suas marcações), só repinta quando a ASSINATURA das câmeras muda. */
  function assinatura(cams) {
    return cams.map((c) => [c.id, c.no_ar ? 1 : 0, (c.estado || {}).gravando || 0,
                            (c.estado || {}).gravando_medido || 0].join(':')).join('|');
  }
  async function relerGrade() {
    if (!document.getElementById('ao-vivo')) return;
    const r = await api('/api/empresas');
    if (!r.ok) return;
    const novo = [];
    const corpo = r.corpo || {};
    for (const e of (corpo.empresas || [])) for (const b of (e.embarcacoes || [])) novo.push({ empresa: e.nome, emb: b });
    for (const b of (corpo.embarcacoes_sem_empresa || [])) novo.push({ empresa: 'sem empresa', emb: b });
    const cams = (embEscolhida() || {}).cameras || [];
    const antes = assinatura(cams);
    frota.length = 0;
    for (const l of novo) frota.push(l);
    const agora = assinatura((embEscolhida() || {}).cameras || []);
    if (agora !== antes) pintaGrade(camerasMarcadas((embEscolhida() || {}).cameras || []));
  }
  /* marca a saída sem clique (fechou a aba/desligou o computador): o `/encerrar` por sessão, na saída */
  window.addEventListener('pagehide', encerrarSessoesDoAdmin);

  function pintaEmbarques() {
    const lista = embsDaEmpresa();
    const anterior = selB.value;
    limpar(selB);
    for (const l of lista) selB.appendChild(Object.assign(document.createElement('option'),
      { value: l.emb.id, textContent: (l.emb.nome || l.emb.id) }));
    selB.value = lista.some((l) => l.emb.id === anterior) ? anterior : ((lista[0] || {}).emb || {}).id || '';
    marcadas = null;                        /* trocou de embarcação: as marcações são dela */
    pintaCameras();
  }

  selE.onchange = pintaEmbarques;
  selB.onchange = pintaCameras;
  if (idInicial) { const l = frota.find((x) => x.emb.id === idInicial); if (l) selE.value = l.empresa; }
  pintaEmbarques();
  tiqueAoVivo = setInterval(() => {
    for (const cam of Object.keys(SESSAO_AO_VIVO)) {
      api('/api/transmissao/' + SESSAO_AO_VIVO[cam] + '/batimento', { method: 'POST', body: '{}' })
        .catch(() => { /* volta no próximo */ });
    }
  }, 10000);
  tiqueDaGrade = setInterval(relerGrade, 5000);
}
/* ============================================================================ DASHBOARD DO ADMIN
   Padrão Dock Check (plano único 0.20.0, 25/11/2026). Dono: "tanto o dashboard do admin quanto o do
   app de captura continuam horríveis, precisa ser algo mais próximo desse do Dock Check".

   Uma leitura só (`GET /api/frota-resumo`, admin): cabeçalho com a bolinha de saúde que pulsa,
   fileira de KPI com barra, câmeras por embarcação, rosca da distribuição geral, DISPONIBILIDADE
   MEDIDA de 7 dias, diagnóstico de conexões, lista com os selos Crítico/Atenção/Operacional e os
   alertas. O que não foi medido sai como "não medido" — nunca um zero que parece saudável.
   As classes `dash-*` moram em `fronts/dashboard.css` (o mesmo arquivo do painel do bordo). */

function dashTomDoEstado(estado) {
  /* '' (sem retrato nenhum) é problema: silêncio do computador de captura não pode parecer saúde.
     O vocabulário do semáforo é ok / atencao / problema (o campo do dia da disponibilidade é 'alerta'). */
  if (estado === 'ok') return 'ok';
  if (estado === 'atencao' || estado === 'alerta') return 'atencao';
  return 'problema';
}

function dashTextoDoEstado(estado) {
  if (estado === 'ok') return 'Operacional';
  if (estado === 'atencao' || estado === 'alerta') return 'Atenção';
  if (estado === 'problema') return 'Crítico';
  return 'Sem dado';
}

function dashSelo(estado) {
  const s = document.createElement('span');
  const tom = dashTomDoEstado(estado);
  s.className = 'dash-selo ' + (estado ? tom : 'neutro');
  s.textContent = dashTextoDoEstado(estado);
  return s;
}

function dashPonto(estado) {
  const p = document.createElement('span');
  p.className = 'dash-ponto ' + (estado ? dashTomDoEstado(estado) : 'neutro');
  if (!estado) p.style.background = '#64748b';
  return p;
}

function dashQuando(iso) {
  /* "há 12 s" a partir do carimbo ISO do servidor. Sem carimbo, "sem notícia". */
  if (!iso) return 'sem notícia';
  const t = Date.parse(iso);
  if (!isFinite(t)) return 'sem notícia';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return 'há ' + s + ' s';
  if (s < 3600) return 'há ' + Math.round(s / 60) + ' min';
  if (s < 86400) return 'há ' + (s / 3600).toFixed(1) + ' h';
  return 'há ' + (s / 86400).toFixed(1) + ' dias';
}

function dashKpi(icone, rotulo, valor, nota, pct, tom) {
  /* O cartão de KPI do Dock Check: ícone em círculo, rótulo, número grande e a barra de progresso. */
  const d = document.createElement('div');
  d.className = 'dash-kpi' + (tom === 'problema' ? ' ruim' : '');
  const i = document.createElement('div'); i.className = 'ico'; i.textContent = icone;
  i.style.background = ({ ok: '#0f2a1a', atencao: '#2a2310', problema: '#2a1214' })[tom] || '#0d1420';
  const corpo = document.createElement('div'); corpo.className = 'corpo';
  const r = document.createElement('div'); r.className = 'rot'; r.textContent = rotulo;
  const v = document.createElement('div'); v.className = 'num'; v.textContent = valor;
  corpo.append(r, v);
  if (pct !== null && pct !== undefined && isFinite(Number(pct))) {
    const b = document.createElement('div'); b.className = 'dash-barra';
    const f = document.createElement('i');
    f.style.width = Math.max(0, Math.min(100, Number(pct))) + '%';
    f.style.background = ({ ok: '#22c55e', atencao: '#f59e0b', problema: '#ef4444' })[tom] || '#3b82f6';
    b.appendChild(f); corpo.appendChild(b);
  }
  if (nota) { const n = document.createElement('div'); n.className = 'rot'; n.textContent = nota; corpo.appendChild(n); }
  d.append(i, corpo);
  return d;
}

function dashCard(titulo, de) {
  const c = document.createElement('div'); c.className = 'dash-card';
  const h = document.createElement('h3'); h.textContent = titulo;
  if (de) { const s = document.createElement('span'); s.className = 'de'; s.textContent = de; h.appendChild(s); }
  c.appendChild(h);
  return c;
}

function dashBarraItem(nome, conta, noAr, total) {
  const g = document.createElement('div'); g.className = 'dash-barra-item';
  const n = document.createElement('span'); n.className = 'nome'; n.textContent = nome;
  const c = document.createElement('span'); c.className = 'conta'; c.textContent = conta;
  const t = document.createElement('div'); t.className = 'trilha';
  const verdes = total ? Math.round(100 * noAr / total) : 0;
  const on = document.createElement('i'); on.style.width = verdes + '%'; on.style.background = '#22c55e';
  const off = document.createElement('i'); off.style.width = (total ? (100 - verdes) : 100) + '%';
  off.style.background = total ? '#334155' : '#1b2434';
  t.append(on, off);
  g.append(n, c, t);
  return g;
}

function dashRosca(partes) {
  /* A rosca de "Distribuição Geral": conic-gradient montado das partes reais, com o total no centro. */
  const total = partes.reduce((a, p) => a + Number(p.quantos || 0), 0);
  const caixa = document.createElement('div'); caixa.className = 'dash-rosca';
  const anel = document.createElement('div'); anel.className = 'anel';
  const disco = document.createElement('div');
  disco.style.cssText = 'width:124px;height:124px;border-radius:99px;position:relative';
  let acc = 0;
  const paradas = [];
  for (const p of partes) {
    const q = Number(p.quantos || 0);
    if (!q || !total) continue;
    const de = 100 * acc / total, ate = 100 * (acc + q) / total;
    paradas.push(p.cor + ' ' + de.toFixed(2) + '% ' + ate.toFixed(2) + '%');
    acc += q;
  }
  disco.style.background = paradas.length
    ? ('conic-gradient(' + paradas.join(',') + ')')
    : 'conic-gradient(#1b2434 0% 100%)';
  const miolo = document.createElement('div');
  miolo.style.cssText = 'position:absolute;inset:14px;border-radius:99px;background:var(--painel)';
  const centro = document.createElement('div'); centro.className = 'centro';
  const b = document.createElement('b'); b.textContent = total ? Math.round(100 * (partes[0].quantos || 0) / total) + '%' : '—';
  const s = document.createElement('span'); s.textContent = total ? 'operacionais' : 'sem dado';
  centro.append(b, s);
  disco.append(miolo, centro);
  anel.appendChild(disco);
  const legenda = document.createElement('div'); legenda.className = 'legenda';
  for (const p of partes) {
    const l = document.createElement('span');
    const i = document.createElement('i'); i.style.background = p.cor;
    const q = document.createElement('span'); q.className = 'qtd';
    q.textContent = p.quantos + ' ' + p.rotulo;
    l.append(i, q);
    legenda.appendChild(l);
  }
  if (!total) legenda.appendChild(notaDe('nenhuma embarcação com retrato do bordo'));
  caixa.append(anel, legenda);
  return caixa;
}

function dashConexao(qual, estado, detalhe) {
  const c = document.createElement('div'); c.className = 'dash-conexao';
  c.style.borderLeftColor = ({ ok: '#22c55e', atencao: '#f59e0b', problema: '#ef4444' })[estado] || '#243044';
  const q = document.createElement('div'); q.className = 'qual';
  const pt = document.createElement('span'); pt.className = 'pt';
  pt.style.background = ({ ok: '#22c55e', atencao: '#f59e0b', problema: '#ef4444' })[estado] || '#64748b';
  q.append(pt, document.createTextNode(qual));
  const d = document.createElement('div'); d.className = 'detalhe'; d.textContent = detalhe || '';
  c.append(q, d);
  return c;
}

function dashItemDaEmbarcacao(e, linhas) {
  const item = document.createElement('div');
  item.className = 'dash-item ' + (e.estado ? dashTomDoEstado(e.estado) : '');
  const nome = document.createElement('div'); nome.className = 'nome';
  nome.textContent = (e.nome || e.id) + '  ' + e.empresa;
  const selo = document.createElement('div'); selo.appendChild(dashSelo(e.estado));
  const emb = document.createElement('div'); emb.className = 'emb';
  emb.textContent = dashQuando(e.em) + (e.maquina ? ' · ' + e.maquina : '')
    + (e.versao_app ? ' · v' + e.versao_app : '');
  const nums = document.createElement('div'); nums.className = 'numeros';
  nums.textContent = 'CPU ' + numeroDaFrota(e.cpu_pct, '%') + ' · memória ' +
    numeroDaFrota(e.memoria_pct, '%') + ' · câmeras no ar ' + e.no_ar + ' de ' + e.cameras;
  /* A TELEMETRIA EVIDENTE (dono, 27/11/2026): o disco da gravação e a rede da máquina entram na linha do
     cartão — antes só havia CPU, memória e "HD do radar" (que saía "—" porque a régua olhava uma variável
     de ambiente que ninguém define). O que o bordo não mediu diz "não medido". */
  const tel = document.createElement('div'); tel.className = 'numeros';
  tel.textContent = linhaDoDisco(e) + ' · ' + linhaDaRede(e);
  if (!e.disco_total_gb) tel.classList.add('nota');
  /* GRAVANDO A BORDO (dono, 26/11/2026): "só preciso no monitoramento saber se está sendo gravado a
     bordo, não preciso ver as imagens". A medida é do BORDO; sem retrato dele a tela diz "não medido" —
     nunca um zero com cara de saúde. */
  const grav = document.createElement('div'); grav.className = 'emb';
  grav.textContent = e.gravacao_medida
    ? (e.gravando_a_bordo ? 'gravando a bordo: ' + e.gravando_a_bordo + ' câmera(s)' : 'gravando a bordo: não')
    : 'gravando a bordo: não medido';
  if (!e.gravacao_medida) grav.classList.add('nota');
  const disp = document.createElement('div'); disp.className = 'emb';
  disp.textContent = 'disponibilidade (7 dias): cobertura ' +
    ((e.disponibilidade || {}).cobertura_pct === undefined ? '—' : (e.disponibilidade.cobertura_pct + '%')) +
    ' dos dias com retrato · ' + ((e.disponibilidade || {}).incidentes === undefined ? '—' : e.disponibilidade.incidentes)
    + ' dia(s) com problema';
  const acoes = document.createElement('div'); acoes.className = 'acoes';
  const alvo = (linhas || []).find((l) => l.emb && l.emb.id === e.id);
  if (alvo) {
    acoes.appendChild(botao('Ver ao vivo (' + e.no_ar + ' no ar)', 'mini', () => abrirAoVivo(linhas, alvo.emb)));
  }
  /* A TELEMETRIA POR CÂMERA/ENCODER (dono, 24/11/2026: "informações de telemetria do computador") NA
     GAVETA: o dashboard fica limpo e o número continua a um clique — sem tabela solta e sem duplicar. */
  const individuais = e.individual || [];
  let gaveta = null;
  if (individuais.length) {
    gaveta = document.createElement('details');
    gaveta.className = 'dash-gaveta';
    const resumo = document.createElement('summary');
    resumo.textContent = 'Telemetria por câmera/encoder (' + individuais.length + ')';
    gaveta.appendChild(resumo);
    gaveta.appendChild(tabela([
      { rotulo: 'Câmera/encoder', valor: (l) => l.rotulo || l.camera_id || 'fluxo' },
      { rotulo: 'Estado', valor: (l) => l.estado || (l.processo ? 'sem processo (' + l.processo + ')' : '—') },
      { rotulo: 'kbps', valor: (l) => (l.kbps === null || l.kbps === undefined ? '—' : Number(l.kbps).toFixed(0)) },
      { rotulo: 'fps', valor: (l) => (l.fps === null || l.fps === undefined ? '—' : Number(l.fps).toFixed(1)) },
      { rotulo: 'CPU', valor: (l) => (l.cpu_pct === null || l.cpu_pct === undefined ? '—' : Number(l.cpu_pct).toFixed(1) + '%') },
      { rotulo: 'Memória', valor: (l) => (l.memoria_mb === null || l.memoria_mb === undefined ? '—' : Number(l.memoria_mb).toFixed(0) + ' MB') },
    ], individuais, 'nenhum fluxo no ar agora'));
  }
  const partes = [nome, selo, emb, nums, tel, grav, disp];
  if (gaveta) partes.push(gaveta);
  partes.push(acoes);
  item.append(...partes);
  return item;
}

async function telaFrota(t) {
  /* Duas leituras: o resumo do dashboard (números medidos) e a árvore da área (para o "Ver ao vivo",
     que abre o MESMO player do cliente com o seletor empresa → embarcação → câmeras). */
  const r = await api('/api/frota-resumo');
  if (!r.ok) { t.appendChild(recado('não consegui ler o dashboard: ' + JSON.stringify(r.corpo), true)); return; }
  const d = r.corpo || {};
  const k = d.kpis || {};
  const embs = d.embarcacoes || [];
  const alertas = d.alertas || [];
  const arv = await api('/api/empresas');
  const linhas = [];
  if (arv.ok) {
    const corpo = arv.corpo || {};
    for (const e of (corpo.empresas || [])) for (const b of (e.embarcacoes || [])) linhas.push({ empresa: e.nome, emb: b });
    for (const b of (corpo.embarcacoes_sem_empresa || [])) linhas.push({ empresa: 'sem empresa', emb: b });
  }
  const pior = alertas.some((a) => a.estado === 'problema') || embs.some((e) => e.estado === 'problema')
    ? 'problema' : (alertas.length || embs.some((e) => e.estado === 'alerta') ? 'alerta' : (embs.length && !embs.some((e) => !e.estado) ? 'ok' : ''));

  /* ------------------------------------------------ cabeçalho (bolinha + atualizar/minimizar) */
  const topo = document.createElement('div'); topo.className = 'dash-topo';
  const tit = document.createElement('div'); tit.className = 'titulo';
  tit.appendChild(dashPonto(pior));
  const bloco = document.createElement('div');
  const h2 = document.createElement('h2');
  h2.textContent = pior === 'problema' ? 'Frota com problema'
    : (pior === 'alerta' ? 'Frota em atenção' : (pior === 'ok' ? 'Frota operacional' : 'Frota sem dado do bordo'));
  const quando = document.createElement('p'); quando.className = 'quando';
  quando.textContent = 'atualizado ' + dashQuando(d.agora) + ' · auto-refresh 30 s' +
    ' · o bordo reportou ' + dashQuando((d.conexoes || {}).ultimo_retrato_em);
  bloco.append(h2, quando);
  tit.appendChild(bloco);
  const acoes = document.createElement('div'); acoes.className = 'acoes';
  acoes.appendChild(botao('⟳ Atualizar', 'mini', () => desenhar(true)));
  const bMin = botao('Minimizar', 'mini', () => {
    const mim = document.body.classList.toggle('dash-min');
    bMin.textContent = mim ? 'Expandir' : 'Minimizar';
  });
  acoes.appendChild(bMin);
  topo.append(tit, acoes);
  t.appendChild(topo);

  /* ------------------------------------------------ KPI */
  const fila = document.createElement('div'); fila.className = 'dash-fila';
  fila.appendChild(dashKpi('⚓', 'Embarcações', String(k.embarcacoes || 0),
                           (k.ok || 0) + ' ok · ' + (k.atencao || 0) + ' atenção · ' + (k.problema || 0) + ' crítico',
                           null, pior));
  fila.appendChild(dashKpi('🎥', 'Câmeras no ar', (k.cameras_no_ar || 0) + ' / ' + (k.cameras || 0),
                           'das câmeras cadastradas', k.cameras ? 100 * (k.cameras_no_ar || 0) / k.cameras : 0,
                           k.cameras && k.cameras_no_ar === k.cameras ? 'ok' : 'atencao'));
  fila.appendChild(dashKpi('🖥', 'Computadores de captura', (k.bordo_reportando || 0) + ' / ' + (k.embarcacoes || 0),
                           'com retrato recebido', k.embarcacoes ? 100 * (k.bordo_reportando || 0) / k.embarcacoes : 0,
                           (k.bordo_reportando || 0) === (k.embarcacoes || 0) ? 'ok' : 'problema'));
  fila.appendChild(dashKpi('📡', 'Fluxos no mediamtx', String(k.fluxos_no_ar || 0), 'prontos no lado terra', null, 'neutro'));
  fila.appendChild(dashKpi((k.alertas ? '⛔' : '✅'), 'Alertas', String(k.alertas || 0),
                           'sinais fora do limiar', null, k.alertas ? 'problema' : 'ok'));
  t.appendChild(fila);

  /* ------------------------------------------------ câmeras por embarcação + distribuição geral */
  const grade = document.createElement('div'); grade.className = 'dash-grade';
  const cardCam = dashCard('Câmeras por embarcação', 'no ar / total');
  const barras = document.createElement('div'); barras.className = 'dash-barras';
  if (embs.length) {
    for (const e of embs) {
      barras.appendChild(dashBarraItem(e.nome, e.no_ar + ' / ' + e.cameras, e.no_ar, e.cameras));
    }
  } else barras.appendChild(notaDe('nenhuma embarcação cadastrada ainda'));
  cardCam.appendChild(barras);
  const cardDist = dashCard('Distribuição geral', 'pelo último retrato de cada bordo');
  cardDist.appendChild(dashRosca([
    { rotulo: 'ok', quantos: k.ok || 0, cor: '#22c55e' },
    { rotulo: 'em atenção', quantos: k.atencao || 0, cor: '#f59e0b' },
    { rotulo: 'crítico', quantos: k.problema || 0, cor: '#ef4444' },
  ]));
  grade.append(cardCam, cardDist);
  t.appendChild(grade);

  /* ------------------------------------------------ disponibilidade (7 dias) — MEDIDA */
  const cardDisp = dashCard('Disponibilidade (7 dias)',
                            'medida pelo retrato que o bordo mandou (nada estimado)');
  const somas = { retratos: 0, problema: 0, alerta: 0, ok: 0 };
  const porDia = [];
  for (const e of embs) {
    const dd = (e.disponibilidade || {}).dias || [];
    for (const dia of dd) {
      let alvo = porDia.find((x) => x.dia === dia.dia);
      if (!alvo) { alvo = { dia: dia.dia, retratos: 0, problema: 0, alerta: 0, ok: 0 }; porDia.push(alvo); }
      for (const campo of ['retratos', 'problema', 'alerta', 'ok']) {
        alvo[campo] += Number(dia[campo] || 0);
        somas[campo] += Number(dia[campo] || 0);
      }
    }
  }
  porDia.sort((a, b) => (a.dia < b.dia ? -1 : 1));
  cardDisp.appendChild(metricasDaDisponibilidade(embs, porDia, somas));
  cardDisp.appendChild(barrasDosDias(porDia));
  cardDisp.appendChild(notaDe('Cada retrato é classificado pelo mesmo semáforo do painel. Cobertura = ' +
    'dias com pelo menos um retrato ÷ 7; incidente = dia com retrato classificado como problema ' +
    '(o silêncio do bordo conta como problema).'));
  t.appendChild(cardDisp);

  /* ------------------------------------------------ diagnóstico de conexões */
  const cardConc = dashCard('Diagnóstico de conexões', 'o terra nunca abre conexão para o bordo');
  const diag = document.createElement('div'); diag.className = 'dash-diag';
  const cx = d.conexoes || {};
  const idadeRetrato = cx.ultimo_retrato_em ? (Date.now() - Date.parse(cx.ultimo_retrato_em)) / 1000 : null;
  diag.appendChild(dashConexao('Bordo → terra (retrato)', idadeRetrato === null ? 'problema'
    : (idadeRetrato < 180 ? 'ok' : (idadeRetrato < 600 ? 'atencao' : 'problema')),
    'último retrato ' + dashQuando(cx.ultimo_retrato_em)));
  diag.appendChild(dashConexao('Bordo → terra (vídeo)', (cx.fluxos_no_ar || 0) > 0 ? 'ok' : 'atencao',
    (cx.fluxos_no_ar || 0) + ' fluxo(s) no ar · última ingestão ' + dashQuando(cx.ultima_ingestao_em)));
  diag.appendChild(dashConexao('Terra → bordo', 'ok',
    'sem porta aberta no bordo: o terra só responde o que o bordo pergunta'));
  diag.appendChild(dashConexao('Câmeras (todas as embarcações)', k.cameras && k.cameras_no_ar === k.cameras ? 'ok' : 'atencao',
    (k.cameras_no_ar || 0) + ' de ' + (k.cameras || 0) + ' no ar'));
  cardConc.appendChild(diag);
  t.appendChild(cardConc);

  /* ------------------------------------------------ embarcações e alertas */
  const grade2 = document.createElement('div'); grade2.className = 'dash-grade dash-detalhe';
  const cardEmbs = dashCard('Embarcações (' + embs.length + ')', 'pior estado primeiro');
  const lista = document.createElement('div'); lista.className = 'dash-lista';
  if (embs.length) for (const e of embs) lista.appendChild(dashItemDaEmbarcacao(e, linhas));
  else lista.appendChild(notaDe('nenhuma embarcação cadastrada ainda'));
  cardEmbs.appendChild(lista);
  const cardAl = dashCard('Alertas (' + alertas.length + ')',
                          alertas.length ? 'o que fazer está em cada linha' : 'nada fora do limiar');
  cardAl.className += ' dash-alertas';
  const listaAl = document.createElement('div'); listaAl.className = 'dash-lista';
  if (alertas.length) {
    for (const a of alertas.slice(0, 12)) {
      const item = document.createElement('div');
      item.className = 'dash-item ' + (a.estado === 'problema' ? 'problema' : 'alerta');
      const nome = document.createElement('div'); nome.className = 'nome';
      nome.textContent = (a.embarcacao || '') + ' · ' + (a.sinal || '');
      const selo = document.createElement('div'); selo.appendChild(dashSelo(a.estado));
      const det = document.createElement('div'); det.className = 'numeros';
      det.textContent = (a.valor === null || a.valor === undefined ? 'não medido' : (a.valor + (a.unidade ? ' ' + a.unidade : '')))
        + (a.o_que_fazer ? ' — ' + a.o_que_fazer : '');
      const emb = document.createElement('div'); emb.className = 'emb';
      emb.textContent = (a.empresa || '') + ' · ' + dashQuando(a.em);
      item.append(nome, selo, det, emb);
      listaAl.appendChild(item);
    }
  } else {
    const vazio = document.createElement('div'); vazio.className = 'dash-vazio';
    vazio.textContent = 'Nenhum alerta ativo — todos os sinais medidos estão dentro do limiar.';
    listaAl.appendChild(vazio);
  }
  cardAl.appendChild(listaAl);
  grade2.append(cardEmbs, cardAl);
  t.appendChild(grade2);
}

function metricasDaDisponibilidade(embs, porDia, somas) {
  const box = document.createElement('div'); box.className = 'dash-metricas';
  const dias = porDia.length || 7;
  const cobertura = dias ? Math.round(100 * porDia.filter((x) => x.retratos > 0).length / dias) : 0;
  const incidentes = porDia.filter((x) => x.problema > 0).length;
  for (const [rot, val] of [['Cobertura', cobertura + '%'], ['Incidentes', String(incidentes)],
                            ['Retratos', String(somas.retratos)], ['Bordos', String(embs.length)]]) {
    const m = document.createElement('div'); m.className = 'dash-metrica';
    const b = document.createElement('b'); b.textContent = val;
    const s = document.createElement('span'); s.textContent = rot;
    m.append(b, s); box.appendChild(m);
  }
  return box;
}

function barrasDosDias(porDia) {
  const caixa = document.createElement('div'); caixa.className = 'dash-dias';
  const max = porDia.reduce((a, x) => Math.max(a, Number(x.retratos || 0)), 0) || 1;
  if (!porDia.length) { caixa.appendChild(notaDe('nenhum retrato do bordo nos últimos 7 dias')); return caixa; }
  for (const dia of porDia) {
    const d = document.createElement('div'); d.className = 'dia';
    const torre = document.createElement('div'); torre.className = 'torre';
    const b = document.createElement('i');
    const altura = Math.max(3, Math.round(52 * Number(dia.retratos || 0) / max));
    b.style.height = altura + 'px';
    b.style.background = dia.problema ? '#ef4444' : (dia.alerta ? '#f59e0b' : (dia.retratos ? '#22c55e' : '#334155'));
    d.title = dia.dia + ' · ' + dia.retratos + ' retrato(s) — ' + dia.problema + ' problema, ' +
      dia.alerta + ' atenção, ' + dia.ok + ' ok';
    torre.appendChild(b);
    const rot = document.createElement('b'); rot.textContent = dia.dia.slice(8, 10) + '/' + dia.dia.slice(5, 7);
    const qtd = document.createElement('span'); qtd.className = 'qtd'; qtd.textContent = String(dia.retratos || 0);
    d.append(torre, rot, qtd);
    caixa.appendChild(d);
  }
  return caixa;
}

async function telaSaudeDoBordo(t) {
  const r = await api('/api/saude-do-bordo');
  if (!r.ok) { t.appendChild(recado('não consegui ler a saúde do bordo: ' + JSON.stringify(r.corpo), true)); return; }
  const lista = (r.corpo && r.corpo.embarcacoes) || [];
  if (!lista.length) { t.appendChild(recado('nenhuma embarcação cadastrada ainda', true)); return; }
  lista.forEach((e) => {
    const atual = e.atual || {};
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    const h = document.createElement('h2');
    h.appendChild(document.createTextNode((e.nome || e.embarcacao_id) + '  '));
    h.appendChild(seloDeSaude(atual.estado || 'problema'));
    caixa.appendChild(h);
    const sub = document.createElement('p'); sub.className = 'sub';
    sub.textContent = atual.recebido_em
      ? ('último retrato: ' + atual.recebido_em + (atual.maquina ? ' · máquina ' + atual.maquina : '')
         + (atual.versao_app ? ' · versão ' + atual.versao_app : ''))
      : 'este computador de captura nunca reportou';
    caixa.appendChild(sub);
    caixa.appendChild(tabela([{ rotulo: 'Sinal', campo: 'sinal' },
      { rotulo: 'Estado', valor: (l) => seloDeSaude(l.estado) },
      { rotulo: 'Valor', campo: 'valor' }, { rotulo: 'Limiar', campo: 'limiar' },
      { rotulo: 'O que fazer', campo: 'o_que_fazer' }], atual.sinais || [], 'sem sinais'));
    caixa.appendChild(botao('Atualizar agora', 'mini', () => { desenhar(true); }));
    t.appendChild(caixa);
  });
}

/* ==================================== A ÁREA ÚNICA (0.12.0): EMPRESA → EMBARCAÇÃO → CÂMERAS
   Pedido do dono (23/11/2026): "preciso poder configurar cada cliente/embarcação/câmeras de forma
   unificada e simples... hoje eu tenho muitas páginas: clientes/embarcações/câmeras/licenças/produção/
   tempo real/enviar vídeos/usuários/configurações do bordo, tudo isso poderia ser uma área só, de
   configuração por cliente e de embarcações pra baixo tudo vinculado ao cliente"; "tempo real,
   produção e câmeras é a mesma coisa, não precisa dividir"; "as câmeras não aparecem do lado do admin
   ... e não consigo configurar e ligar as câmeras". Ou seja: o cliente na raiz, a embarcação abaixo e
   as câmeras (as achadas pela varredura inclusive) em CARTÃO — cada uma com ligar/desligar,
   ativar/desativar, nome que desce ao bordo e qualidade de envio. As telas antigas continuam
   alcançáveis pelo grupo "Avançado" do menu, para nenhum link salvo quebrar. */
function seloDe(tom, texto) {
  const s = document.createElement('span');
  s.className = 'pill';
  s.textContent = texto;
  const cor = ({ ok: '#22c55e', alerta: '#eab308', ruim: '#ef4444' })[tom] || '#64748b';
  s.style.background = cor + '22'; s.style.borderColor = cor; s.style.color = cor;
  return s;
}

function notaDe(texto) { const p = document.createElement('p'); p.className = 'nota'; p.textContent = texto; return p; }

/* EDITAR O CADASTRO no lugar (dono, 25/11/2026: "não vejo onde editar as câmeras, embarcações e
   clientes"). O formulário abre DENTRO do próprio cartão, com os valores atuais. D3: o IDENTIFICADOR é
   renomeável (não só o nome); D4: só o admin — o backend recusa o resto. */
function formularioDeEdicao(caixa, campos, aoSalvar) {
  const antigo = caixa.querySelector('.form-edicao'); if (antigo) { antigo.remove(); return null; }
  const f = document.createElement('div'); f.className = 'form-edicao';
  const linha = document.createElement('div'); linha.className = 'linha-form'; f.appendChild(linha);
  const entradas = {};
  for (const c of campos) {
    const inp = campo(linha, 'ed-' + c.chave + '-' + Math.random().toString(36).slice(2, 7), c.rotulo, c.valor || '');
    if (c.max) inp.maxLength = c.max;
    if (c.dica) inp.title = c.dica;
    entradas[c.chave] = inp;
  }
  const acoes = document.createElement('div'); acoes.className = 'linha-form';
  acoes.appendChild(botao('salvar', 'marca', async () => {
    const corpo = {};
    for (const c of campos) corpo[c.chave] = entradas[c.chave].value.trim();
    await aoSalvar(corpo, f);
  }));
  acoes.appendChild(botao('cancelar', 'mini', () => f.remove()));
  f.appendChild(acoes);
  caixa.appendChild(f);
  return f;
}

async function telaEmpresas(t) {
  const r = await api('/api/empresas');
  if (!r.ok) { t.appendChild(recado('não consegui ler a área do cliente: ' + JSON.stringify(r.corpo), true)); return; }
  A.arvore = r.corpo || { empresas: [], embarcacoes_sem_empresa: [] };
  const empresas = A.arvore.empresas || [];
  const escolhida = empresas.find((e) => e.id === A.empresaId);
  if (escolhida) { await areaDaEmpresa(t, escolhida); return; }
  areaDasEmpresas(t, empresas, A.arvore.embarcacoes_sem_empresa || []);
}

function areaDasEmpresas(t, empresas, semEmpresa) {
  t.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Empresas (clientes)' }));
  if (A.usuario.papel === 'admin') {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
    const id = campo(linha, 'em-id', 'Identificador (ex.: petrobras)', '');
    const nome = campo(linha, 'em-nome', 'Nome da empresa', '');
    caixa.appendChild(botao('Cadastrar empresa', 'marca', async () => {
      const r = await api('/api/clientes', { method: 'POST', body: JSON.stringify({ id: id.value.trim(), nome: nome.value }) });
      if (r.ok) A.empresaId = id.value.trim();
      await atualizar();
      mostrarRecado(r.ok ? 'empresa cadastrada: ' + r.corpo.id : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
    }));
    t.appendChild(caixa);
  }
  if (!empresas.length) {
    t.appendChild(recado('Nenhuma empresa cadastrada ainda. Comece criando a empresa — depois a '
      + 'embarcação vinculada, a chave na embarcação e as câmeras que a varredura encontrar.', true));
  }
  for (const e of empresas) {
    const caixa = document.createElement('div'); caixa.className = 'cartao-empresa';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: e.nome + ' — ' + e.id }));
    caixa.appendChild(notaDe(e.resumo.embarcacoes + ' embarcação(ões) · ' + e.resumo.cameras + ' câmera(s) · '
      + e.resumo.no_ar + ' no ar'
      + (e.resumo.achadas_pela_varredura ? ' · ' + e.resumo.achadas_pela_varredura + ' achada(s) pela varredura' : '')));
    const acoes = document.createElement('div'); acoes.className = 'linha-form';
    acoes.appendChild(botao('Abrir', 'marca', () => { A.empresaId = e.id; desenhar(true); }));
    if (A.usuario.papel === 'admin') {
      acoes.appendChild(botao('editar', 'mini', () => formularioDeEdicao(caixa, [
        { chave: 'nome', rotulo: 'Nome da empresa', valor: e.nome, max: 120 },
        { chave: 'id_novo', rotulo: 'Identificador (renomeável)', valor: e.id, max: 64,
          dica: 'D3: o identificador é renomeável — a troca é transacional nos vínculos' },
      ], async (corpo) => {
        const r = await api('/api/clientes/' + encodeURIComponent(e.id) + '/editar',
                            { method: 'POST', body: JSON.stringify(corpo) });
        if (r.ok && r.corpo && r.corpo.id) A.empresaId = r.corpo.id;
        await atualizar();
        mostrarRecado(r.ok ? ('empresa atualizada: ' + ((r.corpo && r.corpo.id) || e.id) +
          (((r.corpo || {}).mudou || []).length ? ' (' + r.corpo.mudou.join(', ') + ')' : ' (nada a mudar)'))
          : 'recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), !r.ok);
      })));
    }
    caixa.appendChild(acoes);
    t.appendChild(caixa);
  }
  if (semEmpresa.length) {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Embarcações sem empresa' }));
    caixa.appendChild(notaDe('Estas embarcações não estão vinculadas a nenhuma empresa — elas não '
      + 'aparecem na área de nenhum cliente. (É o caso típico da bancada de testes.)'));
    caixa.appendChild(tabela([{ rotulo: 'Embarcação', campo: 'nome' }, { rotulo: 'Identificador', campo: 'id' },
      { rotulo: 'Câmeras', valor: (l) => String((l.resumo || {}).cameras || 0) }], semEmpresa, 'nenhuma'));
    t.appendChild(caixa);
  }
}

async function areaDaEmpresa(t, empresa) {
  const barra = document.createElement('div'); barra.className = 'linha-form';
  barra.appendChild(botao('← todas as empresas', 'mini', () => { A.empresaId = null; desenhar(true); }));
  if (A.usuario.papel === 'admin') {
    barra.appendChild(botao('editar empresa', 'mini', () => formularioDeEdicao(t, [
      { chave: 'nome', rotulo: 'Nome da empresa', valor: empresa.nome, max: 120 },
      { chave: 'id_novo', rotulo: 'Identificador (renomeável)', valor: empresa.id, max: 64 },
    ], async (corpo) => {
      const r = await api('/api/clientes/' + encodeURIComponent(empresa.id) + '/editar',
                          { method: 'POST', body: JSON.stringify(corpo) });
      if (r.ok && r.corpo && r.corpo.id) A.empresaId = r.corpo.id;
      await atualizar();
      mostrarRecado(r.ok ? ('empresa atualizada: ' + ((r.corpo && r.corpo.id) || empresa.id))
        : 'recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), !r.ok);
    })));
  }
  t.appendChild(barra);
  t.appendChild(Object.assign(document.createElement('h2'), { textContent: empresa.nome + ' — ' + empresa.id }));
  t.appendChild(notaDe(empresa.resumo.embarcacoes + ' embarcação(ões) · ' + empresa.resumo.cameras
    + ' câmera(s) · ' + empresa.resumo.no_ar + ' no ar'));

  if (A.usuario.papel === 'admin') {
    const caixa = document.createElement('div'); caixa.className = 'caixa-form';
    caixa.appendChild(Object.assign(document.createElement('h2'), { textContent: 'Nova embarcação nesta empresa' }));
    const linha = document.createElement('div'); linha.className = 'linha-form'; caixa.appendChild(linha);
    const id = campo(linha, 'eb-id', 'Identificador (ex.: psv-01)', '');
    const nome = campo(linha, 'eb-nome', 'Nome da embarcação', '');
    const imo = campo(linha, 'eb-imo', 'IMO (opcional)', '');
    caixa.appendChild(botao('Cadastrar embarcação', 'marca', async () => {
      const r = await api('/api/embarcacoes', { method: 'POST',
        body: JSON.stringify({ id: id.value.trim(), cliente_id: empresa.id, nome: nome.value, imo: imo.value }) });
      await atualizar();
      mostrarRecado(r.ok ? 'embarcação cadastrada: ' + r.corpo.id : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
    }));
    t.appendChild(caixa);
  }
  if (!empresa.embarcacoes.length) {
    t.appendChild(recado('Nenhuma embarcação nesta empresa ainda. Crie a primeira acima — a chave se '
      + 'gera ali e as câmeras da varredura aparecem depois que o PC de captura entrar com ela.', true));
  }
  /* TETO de transmissão da embarcação (dono, 26/11/2026: "precisamos deixar tudo mais simples"): é o
     que sobrava da tela "Configuração do bordo", que saiu. Uma leitura por embarcação — o cartão mostra
     o que foi publicado em terra e o que o bordo confirmou. */
  A.teto = {};
  for (const emb of empresa.embarcacoes) {
    const rc = await api('/api/config?embarcacao_id=' + encodeURIComponent(emb.id));
    A.teto[emb.id] = (rc.ok && rc.corpo) || { chaves: [], aplicadas: [] };
  }
  for (const emb of empresa.embarcacoes) t.appendChild(cartaoDaEmbarcacao(emb));
}

/* SAUDE E DESEMPENHO NA EMBARCACAO (24/11/2026). O dono: "nao tenho nenhuma informacao de saude e
   desempenho". Antes so' havia o estado e a hora; agora vai o NUMERO de cada sinal, com o limiar e o
   "o que fazer" do proprio bordo (`sinais` do `classificar_saude`) — e "sem medida" quando o bordo nao
   conseguiu medir, nunca "ok" por omissao. */
function tomDaSaude(estado) { return ({ ok: 'ok', atencao: 'alerta', problema: 'ruim' })[estado] || 'neutro'; }

function painelDeSaude(emb, cfg) {
  const s = emb.saude || {};
  const cx = document.createElement('div'); cx.className = 'saude-emb';
  if (!s.estado) {
    cx.appendChild(notaDe('Este PC de captura ainda não reportou saúde (sem retrato). Sem dado fresco o '
      + 'estado é "sem retorno" — confira o app aberto no barco e a conexão.'));
    return cx;
  }
  const num = (v, suf) => (v === null || v === undefined || v === '') ? 'sem medida' : (v + (suf || ''));
  const linha = document.createElement('div'); linha.className = 'linha-selos';
  linha.appendChild(seloDe(tomDaSaude(s.estado), 'saúde: ' + s.estado));
  linha.appendChild(seloDe('neutro', 'CPU ' + num(s.cpu_pct, '%')));
  linha.appendChild(seloDe('neutro', 'memória ' + num(s.memoria_pct, '%')));
  linha.appendChild(seloDe('neutro', 'HD do radar ' + num(s.hd_radar_usado_pct, '% usado')));
  linha.appendChild(seloDe(s.ffmpeg === false ? 'ruim' : (s.ffmpeg ? 'ok' : 'neutro'),
    'ffmpeg ' + (s.ffmpeg === false ? 'ausente' : (s.ffmpeg ? 'presente' : 'sem medida'))));
  linha.appendChild(seloDe(s.mediamtx ? 'ok' : 'alerta', 'mediamtx ' + (s.mediamtx ? 'ativo' : 'sem medição')));
  linha.appendChild(seloDe('neutro', 'dispositivos de vídeo ' + num(s.dispositivos)));
  linha.appendChild(seloDe(s.varredura_ok === false ? 'alerta' : 'neutro', 'varredura ' + num(s.varredura)));
  cx.appendChild(linha);
  /* A TELEMETRIA EVIDENTE NO CARTÃO (dono, 27/11/2026: "note que não tem disco e nem rede"): a linha do
     disco da gravação e da rede medida, na mesma régua do item do dashboard. Sem medida, diz que não
     mediu — nunca um traço mudo. */
  const teln = document.createElement('div'); teln.className = 'numeros';
  teln.textContent = linhaDoDisco(s) + ' · ' + linhaDaRede(s);
  if (s.hd_radar_total_gb === null || s.hd_radar_total_gb === undefined) teln.classList.add('nota');
  cx.appendChild(teln);
  const horas = (s.uptime_s || s.uptime_s === 0) ? Math.round(s.uptime_s / 3600) + ' h no ar' : 'tempo no ar sem medida';
  cx.appendChild(notaDe('PC ' + (s.maquina || '?') + ' · app ' + (s.versao_app || 'versão não informada')
    + (s.so ? ' · ' + s.so : '') + ' · ' + horas
    + ' · último retrato ' + (s.em || '—')
    + (emb.maquinas && emb.maquinas.length ? ' · PC(s) com esta licença: ' + emb.maquinas.map((m) => m.maquina).join(', ') : '')
    + avisoDeVersao(cfg)));
  const fora = (s.sinais || []).filter((x) => x.estado && x.estado !== 'ok');
  if (fora.length) {
    const ul = document.createElement('ul'); ul.className = 'sinais';
    for (const x of fora) {
      const li = document.createElement('li');
      li.textContent = x.sinal + ' = ' + (x.valor === null || x.valor === undefined ? 'sem medida' : x.valor)
        + ' — ' + (x.o_que_fazer || '') + (x.limiar ? '  (' + x.limiar + ')' : '');
      ul.appendChild(li);
    }
    cx.appendChild(ul);
  } else if ((s.sinais || []).length) {
    cx.appendChild(notaDe('todos os sinais medidos estão dentro do limite (verde).'));
  }
  const nm = Object.keys(s.nao_medido || {});
  if (nm.length) cx.appendChild(notaDe('o bordo não conseguiu medir: ' + nm.join(', ')
    + ' — sem essa medida não dá para afirmar que está tudo bem.'));
  return cx;
}

/* A VERSAO DO APP DO PC DE CAPTURA (dono, 26/11/2026). Sem isto o admin ve "publicada LIGADA" e, no
   bordo, um "nada sera' gravado" que PARECE defeito do produto — quando o caso e' o app de captura
   estar velho. `bordo_desatualizado === null` e' "nao se sabe" (o bordo nao informou a versao, ou nao
   deu para comparar): isso NUNCA vira "esta tudo certo". */
function avisoDeVersao(cfg) {
  const c = cfg || {};
  if (c.bordo_desatualizado === true) {
    return ' — ⚠ ' + (c.motivo_da_versao || 'o app do PC de captura está desatualizado');
  }
  if (c.bordo_desatualizado === false) {
    return ' · app do PC de captura v' + (c.versao_do_bordo || '?') + ' (em dia)';
  }
  if (c.lado === 'terra' && c.versao_do_bordo) {
    return ' · ' + (c.motivo_da_versao || 'não deu para comparar as versões');
  }
  return '';
}

function cartaoDaEmbarcacao(emb) {
  const caixa = document.createElement('div'); caixa.className = 'cartao-embarcacao';
  caixa.dataset.emb = emb.id;
  const h = document.createElement('h2');
  h.appendChild(document.createTextNode(emb.nome + ' — ' + emb.id + '  '));
  const se = emb.saude && emb.saude.estado;
  h.appendChild(seloDe(tomDaSaude(se), se === 'ok' ? 'saúde ok' : (se === 'atencao' ? 'atenção'
    : (se ? 'problema' : 'sem retorno do bordo'))));
  caixa.appendChild(h);
  /* EDITAR a embarcação (dono, 25/11/2026): nome e IDENTIFICADOR (D3, renomeável). D4: só admin. */
  if (A.usuario.papel === 'admin') {
    const ae = document.createElement('div'); ae.className = 'linha-form';
    ae.appendChild(botao('editar embarcação', 'mini', () => formularioDeEdicao(caixa, [
      { chave: 'nome', rotulo: 'Nome da embarcação', valor: emb.nome, max: 120 },
      { chave: 'id_novo', rotulo: 'Identificador (renomeável)', valor: emb.id, max: 64 },
    ], async (corpo) => {
      const r = await api('/api/embarcacoes/' + encodeURIComponent(emb.id) + '/editar',
                          { method: 'POST', body: JSON.stringify(corpo) });
      await atualizar();
      mostrarRecado(r.ok ? ('embarcação atualizada: ' + ((r.corpo && r.corpo.id) || emb.id))
        : 'recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), !r.ok);
    })));
    caixa.appendChild(ae);
    /* TETO de transmissão da embarcação: veio da tela "Configuração do bordo" (dono, 26/11/2026:
       "se eu consigo editar empresa, embarcação e câmeras em 'Empresas e configuração'... precisamos
       deixar tudo mais simples"). Mesma chave (`teto_s`, `camera_id=''`) e mesma rota de antes. */
    const ct = document.createElement('div'); ct.className = 'linha-form';
    const cfgTeto = (A.teto || {})[emb.id] || { chaves: [], aplicadas: [] };
    const tetoDesejado = (cfgTeto.chaves || []).find((x) => x.camera_id === '' && x.chave === 'teto_s');
    const tetoAplic = (cfgTeto.aplicadas || []).find((x) => x.camera_id === '' && x.chave === 'teto_s');
    const inpTeto = campo(ct, 'cfg-teto-' + emb.id, 'Teto de transmissão (minutos)',
      tetoDesejado ? String(Math.round(Number(tetoDesejado.valor) / 60)) : '');
    ct.appendChild(botao('Publicar teto', 'mini', async () => {
      const r = await api('/api/config', { method: 'POST', body: JSON.stringify({
        embarcacao_id: emb.id, camera_id: '', chave: 'teto_s', valor: String(Math.round(Number(inpTeto.value) * 60)) }) });
      await atualizar();
      mostrarRecado(r.ok ? ('teto publicado (v' + (((r.corpo || {}).versao) || '?') + '): o bordo corta sozinho depois disso')
        : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
    }));
    const notaTeto = document.createElement('span'); notaTeto.className = 'nota';
    notaTeto.textContent = tetoDesejado
      ? ('publicado: ' + Math.round(Number(tetoDesejado.valor) / 60) + ' min — '
         + (tetoAplic && tetoAplic.versao >= tetoDesejado.versao ? 'aplicado (v' + tetoAplic.versao + ')' : 'aguardando o bordo'))
      : 'nada publicado';
    ct.appendChild(notaTeto);
    caixa.appendChild(ct);

    /* REFAZER VARREDURA (dono, 26/11/2026): "nesta tela preciso também de um botão para refazer
       varredura, para que caso tenha sido removida uma câmera por engano, ou não estão aparecendo
       câmeras novas, o app de captura precisa refazer a varredura das câmeras, mas apenas inclui as
       que não estão aparecendo, não remonta tudo pra não perder as configurações já feitas".
       O pedido viaja pela CONFIGURAÇÃO publicada (o terra não abre conexão para o bordo): o bordo olha,
       varre e confirma. A varredura SÓ ACRESCENTA — não duplica, não apaga e não mexe em alvo/ativo. */
    const cv = document.createElement('div'); cv.className = 'linha-form';
    const cfgVarrer = (A.teto || {})[emb.id] || { chaves: [], aplicadas: [] };
    const pedidoVarrer = (cfgVarrer.chaves || []).filter((x) => x.camera_id === '' && x.chave === 'varrer').pop();
    const aplicVarrer = (cfgVarrer.aplicadas || []).filter((x) => x.camera_id === '' && x.chave === 'varrer').pop();
    const btVarrer = botao('refazer varredura', 'mini', async () => {
      const r = await api('/api/config', { method: 'POST', body: JSON.stringify({
        embarcacao_id: emb.id, camera_id: '', chave: 'varrer', valor: '' }) });
      await refazerCartaoDaEmbarcacao(emb.id);
      mostrarRecado(r.ok ? ('varredura pedida ao PC de captura (v' + (((r.corpo || {}).versao) || '?')
        + '): ele inclui só as câmeras que faltam') : 'recusado: ' + JSON.stringify(r.corpo), !r.ok);
    });
    /* O que o botão faz, nas palavras do dono — para ninguém achar que ele "remonta" a configuração. */
    btVarrer.title = 'só entram as câmeras que ainda não aparecem; nada já configurado é mexido';
    cv.appendChild(btVarrer);
    cv.appendChild(notaDe('só entram as câmeras que ainda não aparecem; nada já configurado é mexido.'));
    const notaVarrer = document.createElement('span'); notaVarrer.className = 'nota';
    notaVarrer.textContent = pedidoVarrer
      ? ('pedido: ' + pedidoVarrer.valor + (aplicVarrer && aplicVarrer.versao >= pedidoVarrer.versao
          ? ' — o bordo: ' + (aplicVarrer.motivo || 'aplicado') : ' — aguardando o bordo'))
      : 'nunca pedido';
    cv.appendChild(notaVarrer);
    caixa.appendChild(cv);

    /* GRAVAÇÃO CONTÍNUA DO RADAR (dono, 26/11/2026: "sim, botão ligar/desligar + indicador"). A chave é da
       EMBARCAÇÃO (quem grava é o PC de captura dela) e o valor é 0/1; o bordo OLHA, aplica e confirma. O
       radar grava o tempo todo no HD do bordo (anel: o bloco mais antigo sai quando o disco enche) — e é
       isso que alimenta o HD pesquisável. Aqui não se vê imagem nenhuma: o indicador está no monitoramento. */
    const cg = document.createElement('div'); cg.className = 'linha-form';
    const cfgGrav = (A.teto || {})[emb.id] || { chaves: [], aplicadas: [] };
    const desejaGrav = (cfgGrav.chaves || []).filter((x) => x.camera_id === '' && x.chave === 'gravacao_continua').pop();
    const aplicGrav = (cfgGrav.aplicadas || []).filter((x) => x.camera_id === '' && x.chave === 'gravacao_continua').pop();
    const gravLigada = !!desejaGrav && String(desejaGrav.valor) === '1';
    const btGrav = botao(gravLigada ? 'desligar a gravação contínua do radar' : 'ligar a gravação contínua do radar',
      'mini', async () => {
        const r = await api('/api/config', { method: 'POST', body: JSON.stringify({
          embarcacao_id: emb.id, camera_id: '', chave: 'gravacao_continua', valor: gravLigada ? '0' : '1' }) });
        await refazerCartaoDaEmbarcacao(emb.id);
        mostrarRecado(r.ok ? ((gravLigada ? 'desligamento' : 'ligação') + ' da gravação contínua publicado (v'
          + (((r.corpo || {}).versao) || '?') + '): o bordo aplica no HD dele')
          : 'recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), !r.ok);
      });
    btGrav.title = 'o radar grava o tempo todo no HD do PC de captura; quando o disco enche, o bloco mais antigo sai';
    cg.appendChild(btGrav);
    const notaGrav = document.createElement('span'); notaGrav.className = 'nota';
    notaGrav.textContent = desejaGrav
      ? ((gravLigada ? 'gravação contínua: publicada LIGADA' : 'gravação contínua: publicada DESLIGADA') + ' — '
        + (aplicGrav && aplicGrav.versao >= desejaGrav.versao
            ? 'o bordo: ' + (String(aplicGrav.valor) === '1' ? 'ligada' : 'desligada')
              + (aplicGrav.motivo ? ' (' + aplicGrav.motivo + ')' : '')
            : 'aguardando o bordo')
        + avisoDeVersao(cfgGrav))
      : 'gravação contínua do radar: nada publicado (nasce DESLIGADA)';
    cg.appendChild(notaGrav);
    caixa.appendChild(cg);

    /* QUAL DISCO E QUANTO DELE (dono, 27/11/2026: "precisamos definir qual disco e quanto dele será
       utilizado para gravação" / "o PC mede e propõe" / cota em GB / "um disco só fica nele, com dois ou
       mais escolhe"). O PC de captura MEDE os discos e manda no retrato; aqui o admin ESCOLHE. Com UM
       disco só não há o que escolher (a tela diz isso). A escolha viaja pela config publicada — o mesmo
       caminho da gravação contínua: o bordo olha, aplica e reinicia o gravador. Nada gravado é movido. */
    const sHd = emb.saude || {};
    const discosDoBordo = (sHd.discos || []).filter((d) => d && d.caminho);
    const cfgHd = (A.teto || {})[emb.id] || { chaves: [], aplicadas: [] };
    const desejaHd = (cfgHd.chaves || []).filter((x) => x.camera_id === '' && x.chave === 'hd_disco').pop();
    const desejaCota = (cfgHd.chaves || []).filter((x) => x.camera_id === '' && x.chave === 'hd_cota_gb').pop();
    const aplicHd = (cfgHd.aplicadas || []).filter((x) => x.camera_id === '' && x.chave === 'hd_disco').pop();
    const aplicCota = (cfgHd.aplicadas || []).filter((x) => x.camera_id === '' && x.chave === 'hd_cota_gb').pop();
    const emUso = discosDoBordo.find((d) => d.gravando) || discosDoBordo[0] || null;
    const cd = document.createElement('div'); cd.className = 'linha-form';
    const rotHd = document.createElement('span'); rotHd.className = 'nota';
    rotHd.textContent = discosDoBordo.length
      ? ('HD do radar: ' + (emUso ? (emUso.caminho + ' (' + numeroDaFrota(emUso.livre_gb) + ' GB livres de '
            + numeroDaFrota(emUso.total_gb) + ' GB)') : '—')
         + (sHd.hd_escolha_cota_gb ? ' · cota ' + numeroDaFrota(sHd.hd_escolha_cota_gb, ' GB', 0) : ' · sem cota escolhida')
         + ' · ' + (sHd.hd_escolha_origem === 'admin' ? 'escolha do admin' : 'padrão da instalação'))
      : 'HD do radar: o PC de captura ainda não mediu os discos desta máquina (sem retrato de saúde).';
    cd.appendChild(rotHd);
    if (discosDoBordo.length <= 1) {
      cd.appendChild(notaDe(discosDoBordo.length === 1
        ? 'esta máquina tem um disco só: a gravação fica nele — não há disco para escolher.'
        : 'o seletor de disco aparece quando o PC de captura medir os discos (retrato de saúde).'));
    } else if (A.usuario.papel === 'admin') {
      const sel = document.createElement('select'); sel.className = 'campo'; sel.id = 'hd-disco-' + emb.id;
      sel.title = 'os discos abaixo foram MEDIDOS pelo próprio PC de captura';
      for (const d of discosDoBordo) {
        const o = document.createElement('option'); o.value = d.caminho;
        o.textContent = d.caminho + ' — ' + numeroDaFrota(d.livre_gb) + '/' + numeroDaFrota(d.total_gb)
          + ' GB livres' + (d.gravando ? ' (gravando agora)' : '');
        sel.appendChild(o);
      }
      const oPadrao = document.createElement('option'); oPadrao.value = '';
      oPadrao.textContent = 'padrão da instalação (pasta do aplicativo)';
      sel.appendChild(oPadrao);
      sel.value = (desejaHd && String(desejaHd.valor || '')) || (emUso ? emUso.caminho : '');
      const cota = document.createElement('input'); cota.className = 'campo'; cota.type = 'number';
      cota.min = '0.1'; cota.step = '0.1'; cota.id = 'hd-cota-' + emb.id;
      cota.placeholder = 'cota em GB (vazio = sem cota)';
      cota.title = 'quanto do disco a gravação pode usar; ao bater, o trecho mais antigo sai';
      cota.value = (desejaCota && String(desejaCota.valor || '')) || (sHd.hd_escolha_cota_gb || '');
      const btHd = botao('aplicar no PC de captura', 'mini', async () => {
        const rr = await api('/api/hd/escolher', { method: 'POST', body: JSON.stringify({
          embarcacao_id: emb.id, disco: sel.value, cota_gb: cota.value }) });
        await refazerCartaoDaEmbarcacao(emb.id);
        mostrarRecado(rr.ok ? ('escolha do HD publicada (v' + (((rr.corpo || {}).versao) || '?')
          + '): o PC de captura aplica e reinicia a gravação')
          : 'recusado: ' + (((rr.corpo || {}).erro) || JSON.stringify(rr.corpo)), !rr.ok);
      });
      btHd.title = 'o PC grava no disco escolhido usando no máximo a cota; o que já foi gravado não é movido nem apagado';
      cd.append(sel, cota, btHd);
      const notaHd = document.createElement('span'); notaHd.className = 'nota';
      notaHd.textContent = desejaHd
        ? ('escolha publicada: ' + (desejaHd.valor || 'padrão')
           + (desejaCota && desejaCota.valor ? ' · ' + desejaCota.valor + ' GB' : ' · sem cota')
           + (aplicHd && aplicHd.versao >= desejaHd.versao
               ? ' — o bordo aplicou' + (aplicHd.motivo ? ' (' + aplicHd.motivo + ')' : '')
                 + (aplicCota && aplicCota.motivo ? ' [' + aplicCota.motivo + ']' : '')
               : ' — aguardando o bordo')
           + avisoDeVersao(cfgHd))
        : 'o disco da gravação ainda não foi escolhido: vale o padrão da instalação (pasta do aplicativo).';
      cd.appendChild(notaHd);
    }
    caixa.appendChild(cd);
  }
  caixa.appendChild(notaDe('Câmeras: ' + emb.resumo.cameras + ' · no ar: ' + emb.resumo.no_ar
    + ' · ativas: ' + emb.resumo.ativas
    + (emb.resumo.achadas_pela_varredura ? ' · achadas pela varredura: ' + emb.resumo.achadas_pela_varredura : '')));
  /* A config publicada desta embarcação (a MESMA que o bloco da gravação contínua leu lá dentro): o painel
     de saúde usa ela para ACUSAR o app de captura velho (o dono, 26/11/2026). `cfgGrav` nasce dentro do
     bloco do admin, então aqui se lê de novo de A.teto — a fonte é a mesma. */
  caixa.appendChild(painelDeSaude(emb, (A.teto || {})[emb.id] || { chaves: [], aplicadas: [] }));
  caixa.appendChild(fichaLicenca(emb));
  const cams = document.createElement('div'); cams.className = 'cartes-cameras';
  for (const c of emb.cameras) cams.appendChild(cartaoDaCamera(c, emb));
  if (!emb.cameras.length) {
    cams.appendChild(notaDe('Nenhuma câmera nesta embarcação ainda. No PC de captura, a varredura '
      + 'manda as câmeras encontradas com o nome do dispositivo — elas aparecem aqui, com o nome, para '
      + 'você configurar e ligar.'));
  }
  caixa.appendChild(cams);
  return caixa;
}

/* A chave da licença NA EMBARCAÇÃO (dono, 19/11/2026: "inserir a chave da licença e assim fazer a
   conexão com a empresa e embarcação cadastradas"). Aqui é onde ela nasce: o admin gera, vê/copia e
   revoga — no mesmo lugar de tudo. A chave só aparece para o admin (a rota recusa o resto). */
function fichaLicenca(emb) {
  const caixa = document.createElement('div'); caixa.className = 'ficha-licenca';
  const l = emb.licenca || {};
  caixa.appendChild(notaDe(l.id
    ? ('Licença desta embarcação: ' + (l.validade_tipo === 'ate' ? 'até ' + l.validade_em : 'sem prazo')
       + ' · ' + (l.status || '?') + ' · até ' + (l.maquinas_max || 1) + ' PC(s)'
       + (l.ultimo_uso_em ? ' · último uso em ' + l.ultimo_uso_em : ' · ainda não usada'))
    : 'Sem licença para esta embarcação — o PC de captura só entra no sistema depois de digitar uma chave gerada aqui.'));
  if (A.usuario.papel !== 'admin') return caixa;
  const acoes = document.createElement('div'); acoes.className = 'linha-form';
  if (!l.id) {
    acoes.appendChild(botao('Gerar chave', 'marca', () => gerarChave(emb, caixa)));
  } else {
    acoes.appendChild(botao('ver / copiar chave', 'mini', () => revelarChave(emb, caixa)));
    acoes.appendChild(botao('gerar outra chave', 'mini', async () => {
      if (!confirm('Gerar OUTRA chave para ' + emb.nome + '? A anterior deixa de valer.')) return;
      const r = await api('/api/licencas/' + l.id + '/reemitir', { method: 'POST', body: JSON.stringify({}) });
      if (r.ok && r.corpo.chave) { mostrarChave(emb.id, caixa, r.corpo.chave); } else { mostrarRecado('recusado: ' + JSON.stringify(r.corpo), true); }
      await atualizar();
    }));
    acoes.appendChild(botao('prazo e nº de PCs', 'mini', () => editarLicenca(caixa, { id: l.id, validade_tipo: l.validade_tipo, validade_em: l.validade_em, maquinas_max: l.maquinas_max })));
    if (l.status === 'revogada') acoes.appendChild(botao('reativar', 'mini', () => agirLicenca('reativar', l, {})));
    else acoes.appendChild(botao('revogar', 'mini', () => agirLicenca('revogar', l, { motivo: 'revogada pelo admin' })));
  }
  caixa.appendChild(acoes);
  /* A chave JA' revelada volta a aparecer depois de qualquer redesenho (o timer do painel redesenha
     sozinho — sem isto ela aparecia por um instante e sumia na cara do admin). */
  if (A.chaveRevelada && A.chaveRevelada.emb === emb.id) caixa.appendChild(caixaDaChave(A.chaveRevelada.chave));
  return caixa;
}

async function gerarChave(emb, caixa) {
  const r = await api('/api/licencas', { method: 'POST', body: JSON.stringify({ embarcacao_id: emb.id,
    validade_tipo: 'indeterminada', validade_em: '', maquinas_max: 1 }) });
  if (r.ok && r.corpo.chave) { mostrarChave(emb.id, caixa, r.corpo.chave); }
  else { mostrarRecado('recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), true); }
  await atualizar();
}

async function revelarChave(emb, caixa) {
  const r = await api('/api/licencas');
  const l = ((r.corpo && r.corpo.licencas) || []).find((x) => x.embarcacao_id === emb.id);
  if (l && l.chave) mostrarChave(emb.id, caixa, l.chave);
  else mostrarRecado('não achei a chave desta embarcação (só o administrador vê a chave)', true);
}

function mostrarChave(embId, caixa, chave) {
  A.chaveRevelada = { emb: embId, chave: chave };
  const antigo = caixa.querySelector('.chave-revelada'); if (antigo) antigo.remove();
  caixa.appendChild(caixaDaChave(chave));
}

function caixaDaChave(chave) {
  const d = document.createElement('div'); d.className = 'chave-revelada';
  const c = document.createElement('code'); c.textContent = chave;
  c.style.cssText = 'font-size:15px;letter-spacing:1px;user-select:all';
  d.appendChild(c);
  d.appendChild(botao('copiar chave', 'mini', async () => {
    try { await navigator.clipboard.writeText(chave); mostrarRecado('chave copiada: ' + chave, false); }
    catch (e) { mostrarRecado('não consegui copiar — selecione a chave e copie na mão', true); }
  }));
  d.appendChild(notaDe('Digite esta chave no aplicativo do PC de captura. Ela não circula por e-mail nem por chat.'));
  return d;
}

function cartaoDaCamera(c, emb) {
  const caixa = document.createElement('div'); caixa.className = 'cartao-camera' + (c.no_ar ? ' no-ar' : '');
  /* Marcador ESTÁVEL do cartão: é o que deixa recarregar SÓ este cartão depois de uma ação (e devolver
     o foco no campo certo depois de um redesenho). Sem ele, dez cartões seriam indistinguíveis. */
  caixa.dataset.cam = c.id; caixa.dataset.emb = emb.id;
  const topo = document.createElement('div'); topo.className = 'linha-form linha-nome';
  const nome = document.createElement('input');
  nome.type = 'text'; nome.value = c.rotulo || ''; nome.maxLength = 120; nome.className = 'nome-camera';
  nome.title = 'nome da câmera — ele desce para o PC de captura';
  topo.appendChild(nome);
  topo.appendChild(botao('salvar nome', 'mini', async () => {
    const r = await api('/api/cameras/' + encodeURIComponent(c.id) + '/nome',
      { method: 'POST', body: JSON.stringify({ rotulo: nome.value.trim() }) });
    // REFAZ SO' ESTE CARTAO: o recado vive dentro da tela e o redesenho o apagaria, e a tela do
    // usuario (a rolagem, os outros cartoes) nao pode ser remontada por baixo dele.
    await refazerCartao(c.id);
    if (r.ok) mostrarRecado('nome salvo e publicado para o PC de captura: ' + r.corpo.rotulo, false);
    else mostrarRecado('recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), true);
  }));
  caixa.appendChild(topo);

  const selos = document.createElement('div'); selos.className = 'linha-selos';
  selos.appendChild(seloDe(c.no_ar ? 'ok' : 'neutro', c.no_ar ? 'no ar' : 'fora do ar'));
  selos.appendChild(seloDe(c.ativo ? 'ok' : 'neutro', c.ativo ? 'ativa' : 'desativada'));
  if (c.achada_pela_varredura) selos.appendChild(seloDe('neutro', 'achada pela varredura'));
  if (c.local) selos.appendChild(seloDe('neutro', c.local));
  if (c.leitores) selos.appendChild(seloDe('neutro', c.leitores + ' assistindo'));
  /* O TIPO no selo (plano único, 25/11/2026): é o que o observador (Petrobras/IBAMA) vê de todas as
     empresas — radar de óleo e FLIR. O selo deixa o admin conferir num relance o que ele declarou. */
  if (c.tipo === 'radar') selos.appendChild(seloDe('alerta', 'radar de óleo'));
  else if (c.tipo === 'flir') selos.appendChild(seloDe('alerta', 'FLIR (térmica)'));
  caixa.appendChild(selos);

  const enc = c.encoder || {};
  const alvo = String(c.alvo || '').replace(/k$/i, '');
  caixa.appendChild(notaDe('fluxo ' + c.fluxo_id + ' · qualidade de envio ' + (alvo || '—') + ' kbps'
    + (enc.codec ? ' · ' + enc.codec + (enc.resolucao ? ' ' + enc.resolucao : '') + (enc.fps ? ' ' + enc.fps + ' fps' : '') : '')
    + ' · ' + (c.estado && c.estado.estado ? c.estado.estado
        + (Number(c.estado.gravando_medido || 0) ? (Number(c.estado.gravando || 0) ? ' (gravando a bordo)' : '') : '') : 'sem retorno do bordo')
    + (c.estado && c.estado.motivo ? ' — ' + c.estado.motivo : '')
    // DESEMPENHO (24/11/2026): o que a captura mediu (espectadores) e desde quando esta' no ar.
    + (c.no_ar && c.estado && c.estado.desde ? ' · no ar desde ' + c.estado.desde : '')
    + (c.leitores ? ' · ' + c.leitores + ' espectador(es) aqui' : '')));
  const des = (c.config.desejada || []).map((x) => x.chave + '=' + x.valor + ' (v' + x.versao + ')').join(' · ');
  const apl = (c.config.aplicada || []).map((x) => x.chave + '=' + x.valor + (x.motivo ? ' [' + x.motivo + ']' : '')).join(' · ');
  caixa.appendChild(notaDe('publicado ao bordo: ' + (des || 'nada ainda') + (apl ? '  |  o bordo aplicou: ' + apl : '')));

  const acoes = document.createElement('div'); acoes.className = 'linha-form';
  acoes.appendChild(botao(c.ativo ? 'desativar' : 'ativar', 'mini', async () => {
    if (c.ativo && !confirm('Desativar "' + (c.rotulo || c.id) + '"? Ela sai da tela do cliente; o histórico fica guardado.')) return;
    const r = await api('/api/cameras/' + encodeURIComponent(c.id) + '/ativo', { method: 'POST', body: JSON.stringify({ ativo: !c.ativo }) });
    await refazerCartao(c.id);
    if (!r.ok) mostrarRecado('recusado: ' + JSON.stringify(r.corpo), true);
  }));
  const sel = document.createElement('select');
  /* `data-papel`: a prova de tela acha o menu da QUALIDADE sem confundir com o do TIPO (o cartão tem os
     dois desde a 0.20.0). */
  sel.dataset.papel = 'alvo';
  sel.title = 'qualidade de envio desta câmera (kbps) — desce para o PC de captura';
  /* DE ONDE VEM O VALOR MOSTRADO (defeito do dono, 3a vez, 27/11/2026 — "altero a qualidade e ela
     volta para a anterior"): `cameras.alvo` e' do LADO TERRA e chega VAZIO (quem escreve esse campo e'
     o PC de captura, em `aplicar_config_local`; o lado terra so' tem o que o bordo anuncia, e o anuncio
     nao levava o alvo). Com o campo vazio o menu caía no 1o item ("3000 kbps (padrão do produto)") e
     parecia que a escolha nao tinha sido guardada. A verdade do que foi mandado esta' na config
     PUBLICADA (a mesma que a linha "publicado ao bordo" mostra); `cameras.alvo` fica como reforco. */
  const alvoPublicado = ((c.config || {}).desejada || []).find((x) => x.chave === 'alvo_kbps');
  const alvoAtual = String(c.alvo || (alvoPublicado ? alvoPublicado.valor : '') || '').replace(/k$/i, '');
  /* O menu NAO pode ficar em branco (defeito visto no print do dono em 26/11/2026): sem `alvo`
     publicado, `sel.value = ''` nao casa com opcao nenhuma e o navegador mostra o campo vazio — parece
     que nao ha escolha. Com valor vazio a primeira opcao (a que o produto usa hoje) fica escolhida. */
  for (const a of ALVOS_DE_ENVIO) {
    const o = document.createElement('option');
    o.value = a;
    o.textContent = a + ' kbps' + (!alvoAtual && a === ALVOS_DE_ENVIO[0] ? ' (padrão do produto)' : '');
    sel.appendChild(o);
  }
  if (alvoAtual && !ALVOS_DE_ENVIO.includes(alvoAtual)) {   // alvo antigo/fora da lista nao some do menu
    const o = document.createElement('option'); o.value = alvoAtual; o.textContent = alvoAtual + ' (fora da lista)';
    sel.appendChild(o);
  }
  sel.value = alvoAtual || ALVOS_DE_ENVIO[0];   // `cameras.alvo` guarda "800k"; o menu e' "800"
  acoes.appendChild(sel);
  acoes.appendChild(botao('aplicar qualidade', 'mini', async () => {
    const r = await api('/api/config', { method: 'POST', body: JSON.stringify({
      embarcacao_id: emb.id, camera_id: c.id, chave: 'alvo_kbps', valor: sel.value }) });
    await refazerCartao(c.id);
    if (r.ok) mostrarRecado('qualidade publicada para o PC de captura: ' + sel.value + ' kbps', false);
    else mostrarRecado('recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), true);
  }));
  /* TIPO da câmera (plano único, 25/11/2026 — "quando eu puder renomear, o sistema saberá qual imagem é
     do radar de óleo e/ou câmera flir para que petrobrás/ibama possam acessar"). É o que decide o que o
     observador vê de TODAS as empresas. O bordo PROPÕE o tipo no anúncio; escolher aqui faz o admin
     MANDAR: a partir da escolha, o anúncio do bordo não sobrescreve mais (`tipo_definido_pelo_admin`). */
  const tipo = document.createElement('select');
  tipo.dataset.papel = 'tipo';
  for (const par of [['camera', 'câmera comum'], ['radar', 'radar de óleo'], ['flir', 'FLIR (térmica)']]) {
    const o = document.createElement('option'); o.value = par[0]; o.textContent = par[1]; tipo.appendChild(o);
  }
  tipo.value = ['camera', 'radar', 'flir'].includes(c.tipo) ? c.tipo : 'camera';
  tipo.title = 'o tipo desta câmera: é o que o observador (Petrobras/IBAMA) vê de todas as empresas';
  acoes.appendChild(tipo);
  acoes.appendChild(botao('aplicar tipo', 'mini', async () => {
    const r = await api('/api/cameras/' + encodeURIComponent(c.id) + '/editar',
      { method: 'POST', body: JSON.stringify({ tipo: tipo.value }) });
    await refazerCartao(c.id);
    if (r.ok) mostrarRecado('tipo gravado: ' + tipo.value + ' — o anúncio do bordo não sobrescreve mais', false);
    else mostrarRecado('recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), true);
  }));
  // D3 do dono (24/11/2026): "nao tem ligar agora do admin, so quem visualiza e' o cliente". O admin NAO
  // liga camera — quem liga e' a sessao de quem esta' assistindo. Fica so' o DESLIGAR (o stand-by da
  // operacao), e so' quando ha envio no ar.
  if (c.no_ar) {
    acoes.appendChild(botao('desligar o envio', 'mini', async () => {
      const r = await api('/api/cameras/desligar', { method: 'POST', body: JSON.stringify({ camera_id: c.id }) });
      await refazerCartao(c.id);
      if (r.ok) mostrarRecado('ordem de parar enviada ao PC de captura', false);
      else mostrarRecado('recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), true);
    }));
  }
  /* REMOVER o cadastro (dono, 25/11/2026: "não vejo onde editar as câmeras"). Some daqui E da tela do
     cliente; os trechos gravados e a auditoria continuam. O ENDEREÇO (IP) não se edita aqui — o
     apontamento é do app de captura (D1). D4: só o admin. */
  if (A.usuario.papel === 'admin') {
    acoes.appendChild(botao('remover', 'mini', async () => {
      if (!confirm('Remover "' + (c.rotulo || c.id) + '" de vez? Ela sai desta lista e da tela do ' +
                   'cliente. Os trechos gravados e a auditoria continuam.')) return;
      const r = await api('/api/cameras/' + encodeURIComponent(c.id) + '/remover',
                          { method: 'POST', body: JSON.stringify({}) });
      await refazerCartao(c.id);
      mostrarRecado(r.ok ? ('câmera ' + (c.rotulo || c.id) + ' removida do cadastro')
        : 'recusado: ' + ((r.corpo && r.corpo.erro) || JSON.stringify(r.corpo)), !r.ok);
    }));
  }
  caixa.appendChild(acoes);
  return caixa;
}

/* ACHA a câmera na árvore que a tela já tem (o cartão é desenhado a partir dela). */
function acharNaArvore(camId) {
  const arv = A.arvore || {};
  const filas = [].concat((arv.empresas || []).map((e) => e.embarcacoes || []), [arv.embarcacoes_sem_empresa || []]);
  for (const embs of filas) for (const emb of (embs || [])) for (const c of (emb.cameras || [])) {
    if (c.id === camId) return { camera: c, emb };
  }
  return null;
}

/* REFAZ SÓ O CARTÃO DAQUELA CÂMERA. O resto da tela (a rolagem do usuário, os outros cartões, o
   formulário aberto) fica exatamente como estava — é o pedido do dono (26/11/2026: re-varrer e
   configurar "não remonta tudo pra não perder as configurações já feitas"). Devolve `false` quando o
   cartão não está na tela (aí quem chamou redesenha). */
async function recarregarCartao(camId) {
  const alvo = '.cartao-camera[data-cam="' + (window.CSS && CSS.escape ? CSS.escape(camId) : camId) + '"]';
  const no = document.querySelector(alvo);
  if (!no) return false;
  await atualizarDados();
  const r = await api('/api/empresas');
  if (r.ok) A.arvore = r.corpo || { empresas: [], embarcacoes_sem_empresa: [] };
  const achado = acharNaArvore(camId);
  if (!achado) return false;
  const novo = cartaoDaCamera(achado.camera, achado.emb);
  no.replaceWith(novo);
  A.marca = assinaturaTelas();   // a tela já reflete o que acabou de ser lido: o timer não precisa avisar
  return true;
}

/* Depois de uma ação no cartão: atualiza o cartão em cima do lugar; se ele não está na tela (a câmera
   foi removida, por exemplo), aí sim redesenha tudo. */
async function refazerCartao(camId) { if (!(await recarregarCartao(camId))) await atualizar(); }

/* ACHA a embarcação na árvore que a tela já tem. */
function acharEmbarcacao(embId) {
  const arv = A.arvore || {};
  for (const e of (arv.empresas || [])) for (const emb of (e.embarcacoes || [])) if (emb.id === embId) return emb;
  for (const emb of (arv.embarcacoes_sem_empresa || [])) if (emb.id === embId) return emb;
  return null;
}

/* Refaz SÓ o cartão daquela embarcação (o teto e o pedido de varredura são lidos POR embarcação: a
   leitura de `/api/config` é uma por embarcação). O resto da tela do usuário não é tocado. */
async function recarregarCartaoDaEmbarcacao(embId) {
  const alvo = '.cartao-embarcacao[data-emb="' + (window.CSS && CSS.escape ? CSS.escape(embId) : embId) + '"]';
  const no = document.querySelector(alvo);
  if (!no) return false;
  const rc = await api('/api/config?embarcacao_id=' + encodeURIComponent(embId));
  if (rc.ok) { A.teto = A.teto || {}; A.teto[embId] = rc.corpo || { chaves: [], aplicadas: [] }; }
  const r = await api('/api/empresas');
  if (r.ok) A.arvore = r.corpo || { empresas: [], embarcacoes_sem_empresa: [] };
  const emb = acharEmbarcacao(embId);
  if (!emb) return false;
  no.replaceWith(cartaoDaEmbarcacao(emb));
  A.marca = assinaturaTelas();
  return true;
}

async function refazerCartaoDaEmbarcacao(embId) {
  if (!(await recarregarCartaoDaEmbarcacao(embId))) await atualizar();
}

/* --------------------------------------------------------- interface */
$('form-entrar').addEventListener('submit', entrar);
$('form-primeiro').addEventListener('submit', primeiroAcesso);
$('btn-sair').addEventListener('click', async () => { await api('/api/sair', { method: 'POST' }); location.reload(); });
$('btn-atualizar').addEventListener('click', atualizar);
document.querySelectorAll('.item[data-tela]').forEach((b) => b.addEventListener('click', () => {
  A.tela = b.dataset.tela;
  A.empresaId = null;   // clicar no menu volta para a LISTA de empresas (sai de dentro do cliente)
  A.chaveRevelada = null;   // e a chave revelada nao fica pendurada na tela
  document.querySelectorAll('.item[data-tela]').forEach((x) => x.classList.toggle('on', x === b));
  desenhar(true);   // troca de tela pelo menu sempre redesenha
}));
function relogio() { const d = new Date(); const p = (n) => String(n).padStart(2, '0');
  $('relogio-servidor').textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; }
setInterval(relogio, 1000); relogio();
abrir();


