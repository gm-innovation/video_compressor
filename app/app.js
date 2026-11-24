/* Front do cliente no formato VMS: grade ao vivo com paginacao, selecao, alertas, gravacoes,
   relatorios e cadastros. Fala somente com a API do produto. */
const S = {
  usuario: null, embarcacoes: [], cameras: [], embarcacaoId: null,
  tela: 'visualizar', layout: 3, auto: true, pagina: 1, selecionadas: new Set(), ia: false, destaque: [],
  podeCamera: false, trechoEmCurso: false,
  /* a PROPORCAO real de cada camera (videoWidth/videoHeight, lida do video): e' ela que dimensiona a
     area da imagem e a grade — o dono exige a imagem INTEIRA, sem corte e sem faixa preta (24/11/2026) */
  proporcao: {},
  eventos: [], contagens: [], relatorios: null, timer: null,
  analises: { agentes: [], contagens: [], eventos: [] }, agentesPorCamera: {},
  /* transmissao a pedido do cliente: o que esta' no ar, o historico e o tempo configurado */
  transmissao: { abertas: [], historico: [], tempos: [], tempo_maximo_s: 900 }, minhas: [],
    /* HD do radar de oleo: o catalogo do que existe no PC de captura (nada de video sem pedido) */
    hd: null
  };
const $ = (id) => document.getElementById(id);
const limpar = (el) => { while (el.firstChild) el.removeChild(el.firstChild); };
const esc = (s) => String(s === null || s === undefined ? '' : s);
const dois = (n) => String(n).padStart(2, '0');
const rotuloDe = (id) => { const achou = (S.cameras || []).find((c) => c.id === id); return achou ? achou.rotulo : id; };

async function api(rota, opcoes) {
  const r = await fetch(rota, Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } }, opcoes));
  const texto = await r.text();
  let corpo = null;
  try { corpo = texto ? JSON.parse(texto) : null; } catch (e) { corpo = { bruto: texto }; }
  return { ok: r.ok, status: r.status, corpo };
}

/* ---------------------------------------------------------------- entrada */
async function entrar(ev) {
  ev.preventDefault();
  const d = await api('/api/entrar', { method: 'POST', body: JSON.stringify({ email: $('email').value, senha: $('senha').value }) });
  if (!d.ok) { const e = $('entrada-erro'); e.textContent = (d.corpo && d.corpo.erro) || 'não foi possível entrar'; e.classList.remove('oculto'); return; }
  await abrir();
}

async function abrir() {
  const eu = await api('/api/eu');
  if (!eu.corpo || !eu.corpo.autenticado) return;
  S.usuario = eu.corpo;
  S.papel = eu.corpo.papel;
  // ligar/desligar a CAMERA so faz sentido onde a camera esta plugada: a propria maquina de
  // captura (local) ou a operacao. O cliente remoto nunca ve esses botoes.
  S.podeCamera = !!((eu.corpo.local || eu.corpo.papel !== 'cliente')
                    && !['cliente', 'observador'].includes(eu.corpo.papel));
  $('entrada').classList.add('oculto'); $('sistema').classList.remove('oculto');
  $('conta-email').textContent = eu.corpo.email;
  $('conta-papel').textContent = eu.corpo.papel === 'cliente' ? 'Cliente'
    : (eu.corpo.papel === 'observador' ? 'Observador (Petrobras)' : 'Operação LECSOR');
  if (eu.corpo.papel === 'observador') return abrirObservador();
  $('iniciais').textContent = eu.corpo.nome.split(/\s+/).filter((p) => p.length > 2).slice(0, 2).map((p) => p[0]).join('').toUpperCase() || 'LC';
  const em = await api('/api/embarcacoes');
  S.embarcacoes = (em.corpo && em.corpo.embarcacoes) || [];
  limpar($('embarcacao'));
  for (const e of S.embarcacoes) {
    const o = document.createElement('option'); o.value = e.id; o.textContent = e.nome + (e.imo ? ` (IMO ${e.imo})` : '');
    $('embarcacao').appendChild(o);
  }
  if (S.embarcacoes.length) S.embarcacaoId = S.embarcacoes[0].id;
  await atualizar();
  if (!S.timer) S.timer = setInterval(atualizar, 5000);
  // RELOGIO DE 1 s DA CONTAGEM (dono, 24/11/2026): o contador da transmissao anda a cada segundo na
  // propria tela, sem depender do ciclo de 5 s do servidor — o cliente ve o tempo correndo de fato.
  if (!S.tick) S.tick = setInterval(tickDaContagem, 1000);
}

/* Observador (tipo 4 — Petrobras, plano de 19/11/2026, Fase 4): o radar de oleo de todas as
   embarcacoes, de todas as empresas, e nada mais. Sem cadastro, sem transmissao, sem analytics —
   o servidor ja' devolve so' radar para este papel; aqui a tela apenas esconde o que nao existe. */
async function abrirObservador() {
  for (const b of document.querySelectorAll('.lateral .item')) {
    if (!['visualizar', 'radar_hd'].includes(b.dataset.tela)) b.classList.add('oculto');
  }
  for (const g of document.querySelectorAll('.lateral .grupo')) g.classList.add('oculto');
  const ia = $('btn-ia'); if (ia) ia.classList.add('oculto');
  const bAuto = $('btn-auto'); if (bAuto) bAuto.textContent = 'Radar ao vivo';
  for (const b of document.querySelectorAll('#controles button[data-layout]')) b.classList.add('oculto');
  const bDest = $('btn-destaque'); if (bDest) bDest.classList.add('oculto');
  const itVis = document.querySelector('.lateral .item[data-tela="visualizar"]');
  if (itVis) itVis.innerHTML = '<span class="ic">🛰</span>Radar ao vivo';
  const em = await api('/api/embarcacoes');
  S.embarcacoes = (em.corpo && em.corpo.embarcacoes) || [];
  limpar($('embarcacao'));
  for (const e of S.embarcacoes) {
    const o = document.createElement('option'); o.value = e.id; o.textContent = e.nome;
    $('embarcacao').appendChild(o);
  }
  /* Abre na primeira embarcacao que TENHA radar: o observador entra para ver radar, e cair numa
     embarcacao sem radar seria uma tela vazia sem motivo. */
  const todas = await api('/api/cameras');
  const comRadar = new Set(((todas.corpo || {}).cameras || []).map((c) => c.embarcacao_id));
  const primeira = S.embarcacoes.find((e) => comRadar.has(e.id));
  S.embarcacaoId = (primeira || S.embarcacoes[0] || {}).id || null;
  /* Abre no RADAR AO VIVO: e' nele que o seletor de embarcacao (todo o grupo, de todas as empresas)
     fica a mao. O HD do radar e' a outra aba, e la' a tabela ja' diz de qual embarcacao e' cada
     trecho — nao precisa de seletor. */
  await trocarTela('visualizar');
  await atualizar();
  if (!S.timer) S.timer = setInterval(atualizar, 5000);
  // RELOGIO DE 1 s DA CONTAGEM (dono, 24/11/2026): o contador da transmissao anda a cada segundo na
  // propria tela, sem depender do ciclo de 5 s do servidor — o cliente ve o tempo correndo de fato.
  if (!S.tick) S.tick = setInterval(tickDaContagem, 1000);
}

async function atualizar() {
  if (!S.embarcacaoId) return;
  const d = await api('/api/cameras?embarcacao=' + encodeURIComponent(S.embarcacaoId));
  const novas = (d.corpo && d.corpo.cameras) || [];
  /* Compara o que a tela usa de verdade (id, estado, motivo, resolução). Sem isto, um bitrate
     novo ou uma câmera mudar de lugar na lista derrubava e remontava todas as janelas de vídeo. */
  const chaveCam = (c) => c.id + '|' + (c.no_ar ? 1 : 0) + '|' + (c.motivo || '') + '|' + ((c.encoder || {}).resolucao || '');
  const mudouLista = novas.map(chaveCam).sort().join('#') !== S.cameras.map(chaveCam).sort().join('#');
  S.cameras = novas;
  if (S.selecionadas.size === 0) S.cameras.forEach((c) => S.selecionadas.add(c.id));
  for (const id of Array.from(S.selecionadas)) if (!S.cameras.some((c) => c.id === id)) S.selecionadas.delete(id);
  const an = await api('/api/analises');
  if (an.ok && an.corpo) {
    S.analises = an.corpo;
    S.agentesPorCamera = {};
    for (const ag of (an.corpo.agentes || [])) S.agentesPorCamera[ag.camera_id] = ag;
  }
  if (S.tela === 'alertas' || S.tela === 'relatorios') await dadosExtras();
  // a GRADE tambem precisa das transmissoes abertas: e' nela que o cliente inicia/para a transmissao,
  // ve a contagem e o "Reconectar" (dono, 24/11/2026 — os controles sairam da tela "Transmitir").
  if (S.tela === 'transmissao' || S.tela === 'configuracao' || S.tela === 'gravacoes'
      || S.tela === 'visualizar') await carregarTransmissao();
  if (S.tela === 'radar_hd') await carregarHd();
  if (S.tela === 'visualizar') {
    if (mudouLista || !$('palco').dataset.montado) desenharVisualizar();
    else { pintarEstados(); S.cameras.forEach((c) => desenharCaixas(c.id)); }
    atualizarSeloIA();
  }
  else {
    /* Nas telas de tabela a tela é atualizada no lugar (tabelaEmPalco só troca a célula que mudou),
       então repintar a cada 5 s não apaga mais nada; a marca evita trabalho quando nada mudou. */
    // Na tela de TEMPO a unica coisa que muda por fora e' o valor gravado: redesenhar a cada 5 s
    // recriava o <select> e apagava a escolha do cliente (mandava o valor antigo ao gravar — o
    // defeito que a prova de tela pegou). Aqui so' redesenha quando o valor GRAVADO muda.
    const marca = (S.tela === 'configuracao')
      ? 'config|' + S.transmissao.tempo_maximo_s
      : assinaturaTelas();
    if (marca !== marcaTela) { marcaTela = marca; desenharTela(); }
  }
  atualizarRodape();
}

/* Impressão digital do que a tela mostra. Campos que mudam sozinhos (relógio do resumo, idade da
   detecção) ficam fora: sozinhos não justificam repintar a tela. */
let marcaTela = '';
function assinaturaTelas() {
  try {
    return JSON.stringify([S.tela, S.cameras, S.eventos, S.contagens, S.relatorios, S.analises, S.transmissao, S.hd],
      (k, v) => ((k === 'gerado_em' || k === 'caixas_idade' || k === 'agora' || k === 'atualizado_em') ? undefined : v));
  } catch (e) { return 'erro:' + Math.random(); }
}

async function dadosExtras() {
  const ev = await api('/api/eventos');
  S.eventos = (ev.corpo && ev.corpo.eventos) || [];
  const rs = await api('/api/resumo');
  S.contagens = (rs.corpo && rs.corpo.contagens) || [];
  S.relatorios = rs.corpo;
}

/* ---------------------------------------------------------------- visualizar */
function porPagina() {
  if (S.auto) return S.cameras.length <= 4 ? 2 : S.cameras.length <= 9 ? 3 : 4;
  return S.layout;
}
function paginas() { return Math.max(1, Math.ceil(S.selecionadas.size / (porPagina() * porPagina()))); }
function camerasDaPagina() {
  const n = porPagina();
  const lista = S.cameras.filter((c) => S.selecionadas.has(c.id));
  const inicio = (S.pagina - 1) * n * n;
  return lista.slice(inicio, inicio + n * n);
}

/* ------------------------------------------------- a imagem INTEIRA na grade (dono, 24/11/2026)
   "não cortar ... preciso das imagens inteiras". Com o card abaixo e a célula esticada, o `cover`
   cortava a imagem (a área nunca tinha a proporção da câmera). Aqui a área da imagem recebe a
   proporção REAL do vídeo (`videoWidth/videoHeight`) e a grade é dimensionada por ela: a imagem
   entra inteira, sem corte e sem faixa preta; a sobra da tela vira margem do painel. */
const LACO_DA_GRADE = 5;

function proporcaoDaImagem(img, v, c) {
  const aplicar = () => {
    if (!v.videoWidth || !v.videoHeight) return;
    const r = v.videoWidth / v.videoHeight;
    if (S.proporcao[c.id] === r) return;
    S.proporcao[c.id] = r;
    img.style.aspectRatio = v.videoWidth + ' / ' + v.videoHeight;
    ajustarGrade();
  };
  v.addEventListener('loadedmetadata', aplicar);
  v.addEventListener('resize', aplicar);
  aplicar();
}

/* A proporção da grade é a MENOR das conhecidas: assim nenhuma linha fica mais alta que o cálculo. */
function proporcaoDaGrade(grade) {
  const vistas = Array.from(grade.querySelectorAll('.janela'))
    .map((j) => S.proporcao[j.dataset.cam])
    .filter((r) => r > 0);
  return vistas.length ? Math.min.apply(null, vistas) : 16 / 9;
}

/* Dimensiona a grade para a imagem caber INTEIRA: a coluna é a largura que cabe na tela E que faz a
   altura da célula (imagem + card, em `linhas` linhas) caber na altura disponível. */
function ajustarGrade() {
  for (const grade of document.querySelectorAll('.grade-vms')) {
    const janelas = grade.querySelectorAll('.janela');
    const alvo = grade.parentElement;
    if (!janelas.length || !alvo) continue;
    const cols = Number(grade.dataset.cols || 0) || janelas.length;
    const linhas = Number(grade.dataset.linhas || 0) || cols;
    const est = getComputedStyle(alvo);
    const aw = alvo.clientWidth - (parseFloat(est.paddingLeft) || 0) - (parseFloat(est.paddingRight) || 0);
    let ah = alvo.clientHeight - (parseFloat(est.paddingTop) || 0) - (parseFloat(est.paddingBottom) || 0);
    /* o que divide a altura com a grade (o topo do destaque, a tarja de vazio) sai da conta */
    for (const irmao of alvo.children) if (irmao !== grade && irmao.offsetHeight) ah -= irmao.offsetHeight;
    const card = grade.querySelector('.card-cam');
    const cardH = card ? card.offsetHeight : 0;
    const r = proporcaoDaGrade(grade);
    const porLargura = (aw - (cols - 1) * LACO_DA_GRADE) / cols;
    const porAltura = r * (ah - (linhas - 1) * LACO_DA_GRADE - linhas * cardH) / linhas;
    const largura = Math.floor(Math.min(porLargura, porAltura));
    if (!(largura > 40)) continue;   // sem espaço: não mexe (a janela é pequena demais para calcular)
    grade.style.gridTemplateColumns = 'repeat(' + cols + ', ' + largura + 'px)';
    grade.style.gridTemplateRows = 'auto';
    grade.style.justifyContent = 'center';
    grade.style.alignContent = 'center';
    for (const j of janelas) {
      const img = j.querySelector('.img-cam');
      if (img && !S.proporcao[j.dataset.cam]) {   // sem metadado ainda: assume a proporção da grade
        img.style.aspectRatio = String(r);
      }
    }
  }
}

function desenharVisualizar() {
  const palco = $('palco');
  const n = porPagina();
  const lista = camerasDaPagina();
  const ids = lista.map((c) => c.id);
  for (const antigo of Array.from(palco.querySelectorAll('.janela'))) {
    if (!ids.includes(antigo.dataset.cam)) { window.Video.parar(antigo.dataset.cam); antigo.remove(); }
  }
  limpar(palco);
  palco.dataset.montado = '1';
  const grade = document.createElement('div');
  grade.className = 'grade-vms ' + (n === 1 ? 'g1' : n === 2 ? 'g2' : n === 3 ? 'g3' : 'g4');
  grade.dataset.cols = String(n); grade.dataset.linhas = String(n);
  palco.appendChild(grade);
  const vazio = document.createElement('div');
  vazio.className = 'vazio oculto';
  palco.appendChild(vazio);
  if (!lista.length) {
    vazio.classList.remove('oculto');
    vazio.textContent = S.cameras.length
      ? 'Nenhuma câmera selecionada — use "Limpar seleção" para voltar a todas.'
      : 'Esta embarcação ainda não tem câmera publicando.';
    montarPaginacao(); return;
  }
  for (const c of lista) {
    const jan = document.createElement('div');
    jan.className = 'janela' + (S.selecionadas.has(c.id) ? ' selecionada' : '');
    jan.dataset.cam = c.id;
    jan.dataset.noAr = c.no_ar ? '1' : '0';
    const v = document.createElement('video');
    v.id = 'v-' + c.id; v.muted = true; v.autoplay = true; v.playsInline = true;
    v.onclick = () => selecionar(c.id);
    v.ondblclick = () => (v.requestFullscreen ? v.requestFullscreen() : null);
    const marca = document.createElement('span'); marca.className = 'marca-dagua'; marca.dataset.relogio = '1';
    const rot = document.createElement('span'); rot.className = 'rotulo-cam';
    const ponto = document.createElement('span'); ponto.className = 'ponto' + (c.no_ar ? '' : ' ruim');
    const nome = document.createElement('span');
    // o rotulo carrega so o essencial; o motivo completo aparece no aviso dentro da janela
    nome.dataset.base = c.rotulo + (c.encoder && c.encoder.resolucao ? ' · ' + c.encoder.resolucao : '');
    nome.textContent = nome.dataset.base + (c.no_ar ? '' : ' · fora do ar');
    rot.appendChild(ponto); rot.appendChild(nome);
    const caixas = document.createElement('div'); caixas.className = 'caixas'; caixas.id = 'caixas-' + c.id;
    /* CARD ABAIXO DA IMAGEM (dono, 24/11/2026): nome/estado e TODOS os botoes moram aqui, nao mais por
       cima do video. A imagem fica limpa; sobre ela so' a marca d'agua e as caixas da IA. */
    const card = document.createElement('div'); card.className = 'card-cam';
    /* a imagem e seus avisos (marca d'agua, caixas da IA, tarja de "fora do ar") vivem na area da
       imagem; o card fica FORA dela, abaixo. */
    const img = document.createElement('div'); img.className = 'img-cam';
    img.appendChild(v);
    proporcaoDaImagem(img, v, c);   // a área da imagem recebe a proporção REAL da câmera
    if (S.podeCamera) {
      // botao de energia da camera: desligar solta o dispositivo de captura (a camera "desliga"),
      // ligar reabre com o ultimo ajuste. Sem precisar desconectar nada fisicamente.
      const ctrl = document.createElement('span');
      ctrl.className = 'controle-cam';
      const b = document.createElement('button');
      b.className = 'botao-cam';
      b.textContent = c.no_ar ? 'Desligar' : 'Ligar';
      b.title = c.no_ar ? 'Desliga a câmera (solta o dispositivo de captura)'
                        : 'Liga a câmera de novo com o último ajuste';
      b.onclick = (ev) => { ev.stopPropagation(); energia(c.id, !c.no_ar); };
      ctrl.appendChild(b);
      card.appendChild(ctrl);
    }
    // aviso no lugar da tela preta: sem isso o operador nao sabe se a camera caiu, foi desligada
    // ou falhou. Fica sempre no DOM e o pintarEstados() atualiza o texto a cada 5 s.
    const aviso = document.createElement('div'); aviso.className = 'aviso-cam';
    aviso.style.cssText = 'position:absolute;left:8%;right:8%;top:34%;text-align:center;padding:0 6px;' +
      'color:#ffb4b4;font-size:12px;line-height:1.3;pointer-events:none;text-shadow:0 1px 2px #000;' +
      'max-height:3.9em;overflow:hidden';
    img.appendChild(aviso);
    pintarAviso(c, jan);
    // ---- Baixar 1 minuto: baixa 60 s do vídeo COMO ELE CHEGA no lado terra (o servidor grava em
    // -c copy, sem reencodar) para conferir o TAMANHO do arquivo. O comparativo de Mbps (declarado
    // x medido) saiu daqui a pedido do dono (16/11/2026): "vamos fazer um teste cego" — o tamanho
    // do arquivo se compara à mão com o Mbps que o admin/captura exibe.
    const ctrlT = document.createElement('span');
    ctrlT.className = 'controle-trecho';
    const bT = document.createElement('button');
    bT.className = 'botao-trecho';
    bT.textContent = 'Baixar 1 minuto';
    bT.title = 'Baixa 60 s do vídeo como ele chega no lado terra, sem reencodar, para conferir o tamanho';
    bT.onclick = (ev) => { ev.stopPropagation(); baixarTrecho(c, bT); };
    ctrlT.appendChild(bT);
    // ver ESTA câmera em destaque (1 clique) — o duplo clique na janela faz o mesmo
    const bD = document.createElement('button');
    bD.className = 'botao-trecho';
    bD.textContent = 'Destaque';
    bD.title = 'Ver esta câmera em destaque (tela cheia)';
    bD.onclick = (ev) => { ev.stopPropagation(); abrirDestaque([c.id]); };
    ctrlT.appendChild(bD);
    jan.ondblclick = (ev) => { ev.stopPropagation(); abrirDestaque([c.id]); };
    card.appendChild(ctrlT);
    /* TRANSMISSAO NO PROPRIO QUADRO (dono, 24/11/2026): o cliente inicia/para a transmissao AQUI,
       ve a contagem regressiva, recebe o aviso do ultimo minuto ("quer continuar conectado?"), tem o
       botao de gravar e o "Reconectar" quando a sessao cai. Antes isso so' existia na tela
       "Transmitir" — que o dono nao usava; agora vale na tela em que ele esta'. */
    const ctrlS = document.createElement('span');
    ctrlS.className = 'controle-transmissao';
    ctrlS.dataset.st = c.id;
    card.appendChild(ctrlS);
    montarControle(c, ctrlS, jan);
    const linhaT = document.createElement('div'); linhaT.className = 'trecho-linha'; linhaT.style.display = 'none';
    img.appendChild(linhaT);
    card.appendChild(rot);
    img.appendChild(marca); img.appendChild(caixas);
    jan.appendChild(img); jan.appendChild(card);
    grade.appendChild(jan);
    window.Video.ligar(c.id, c.id, v);
    desenharCaixas(c.id);
  }
  montarPaginacao();
  pintarEstados();
  ajustarGrade();   // a grade é dimensionada depois de montada (imagem inteira, sem corte)
}

function selecionar(id) {
  if (S.selecionadas.has(id) && S.selecionadas.size > 1) S.selecionadas.delete(id); else S.selecionadas.add(id);
  S.pagina = 1;
  desenharVisualizar(); atualizarRodape();
}

/* Liga/desliga a CAMERA pela tela: desligar solta o dispositivo de captura (ninguem precisa
   desconectar nada fisicamente); ligar reabre a camera com o ultimo ajuste dela. */
async function energia(cameraId, ligar) {
  const d = await api(ligar ? '/api/cameras/ligar' : '/api/cameras/desligar',
                      { method: 'POST', body: JSON.stringify({ camera_id: cameraId }) });
  if (!d.ok) { alert((d.corpo && d.corpo.erro) || 'não foi possível ligar/desligar a câmera'); return; }
  await atualizar();
}

/* ------------------------------------------------------------------ Baixar 1 minuto (teste cego)
   Baixa 60 s do vídeo COMO ELE CHEGA no lado terra e mostra só o que é do ARQUIVO: nome, MB e
   duração. O Mbps do arquivo (MB x 8 / segundos) se compara à mão com o que o admin/captura exibe —
   nenhum comparativo, veredito ou compressão aparece aqui (dono, 16/11/2026). A gravação é feita
   pelo servidor em -c copy (bits que chegaram, sem reencodar) e a tela mostra os MB subindo. */
function janelaDa(cameraId) {
  return document.querySelector('.janela[data-cam="' + String(cameraId).replace(/"/g, '\\"') + '"]');
}

/* ------------------------------------------------------------------ destaque (1 a 4 câmeras)
   Ver uma câmera em tela cheia, ou 2 a 4 em destaque, sem mexer na grade do palco. Cada janela do
   destaque abre a SUA propria sessão (`destaque-<id>`), então o mesmo fluxo pode estar na grade e no
   destaque ao mesmo tempo. Nada aqui muda banda, resolução ou o que o servidor envia — isso é a
   seleção de qualidade por câmera, que é da operação. */
function cameraPorId(id) { return S.cameras.find((c) => c.id === id) || null; }

function abrirDestaque(ids) {
  const lista = (ids || []).map(cameraPorId).filter(Boolean).slice(0, 4);
  if (!lista.length) { alert('selecione de 1 a 4 câmeras para destacar'); return; }
  fecharDestaque(true);
  const caixa = document.createElement('div');
  caixa.className = 'destaque'; caixa.id = 'destaque';
  const topo = document.createElement('div'); topo.className = 'destaque-topo';
  const titulo = document.createElement('span'); titulo.className = 'destaque-titulo';
  titulo.textContent = lista.length === 1
    ? 'Em destaque: ' + lista[0].rotulo
    : lista.length + ' câmeras em destaque: ' + lista.map((c) => c.rotulo).join(' · ');
  topo.appendChild(titulo);
  const bCheia = document.createElement('button'); bCheia.className = 'pil'; bCheia.textContent = 'Tela cheia do destaque';
  bCheia.onclick = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (caixa.requestFullscreen) caixa.requestFullscreen();
  };
  const bVoltar = document.createElement('button'); bVoltar.className = 'pil'; bVoltar.textContent = 'Voltar à grade';
  bVoltar.onclick = () => fecharDestaque();
  topo.appendChild(bCheia); topo.appendChild(bVoltar);
  caixa.appendChild(topo);
  const grade = document.createElement('div');
  grade.className = 'grade-vms g' + (lista.length === 1 ? '1' : lista.length === 2 ? '2' : lista.length === 3 ? '3' : '4');
  grade.dataset.cols = String(lista.length === 1 ? 1 : lista.length === 2 ? 2 : lista.length === 3 ? 3 : 4);
  grade.dataset.linhas = grade.dataset.cols;
  caixa.appendChild(grade);
  for (const c of lista) {
    const jan = document.createElement('div');
    jan.className = 'janela'; jan.dataset.camDestaque = c.id;
    const v = document.createElement('video');
    v.id = 'vdestaque-' + c.id; v.muted = true; v.autoplay = true; v.playsInline = true;
    const img = document.createElement('div'); img.className = 'img-cam'; img.appendChild(v);
    proporcaoDaImagem(img, v, c);   // a área da imagem recebe a proporção REAL da câmera
    const card = document.createElement('div'); card.className = 'card-cam';
    const rot = document.createElement('div'); rot.className = 'rotulo-cam';
    rot.textContent = c.rotulo;
    card.appendChild(rot);
    jan.appendChild(img); jan.appendChild(card);
    grade.appendChild(jan);
    window.Video.ligar('destaque-' + c.id, c.id, v);
  }
  document.body.appendChild(caixa);
  S.destaque = lista.map((c) => c.id);
  ajustarGrade();
}

function fecharDestaque(silencioso) {
  const antigo = document.getElementById('destaque');
  if (antigo) {
    for (const jan of Array.from(antigo.querySelectorAll('.janela'))) {
      window.Video.parar('destaque-' + jan.dataset.camDestaque);
    }
    if (document.fullscreenElement === antigo) document.exitFullscreen();
    antigo.remove();
  }
  S.destaque = [];
  return !silencioso;
}

function linhaTrecho(jan, texto) {
  const linha = jan && jan.querySelector('.trecho-linha');
  if (!linha) return;
  linha.style.display = 'block';
  linha.textContent = texto;
}

async function baixarTrecho(camera, botao) {
  const jan = janelaDa(camera.id);
  if (S.trechoEmCurso) { linhaTrecho(jan, 'já existe um trecho sendo gravado nesta tela — espere terminar'); return; }
  S.trechoEmCurso = true;
  let timer = null;
  botao.disabled = true;
  linhaTrecho(jan, 'gravando 60 s…');
  try {
    timer = setInterval(async () => {
      const e = await api('/api/cameras/' + encodeURIComponent(camera.id) + '/trecho/estado');
      const c = e.corpo || {};
      if (c.gravando) {
        linhaTrecho(jan, 'gravando ' + Math.round(c.segundos || 0) + ' s… ' + (c.mb || 0).toFixed(1) +
          ' MB recebidos (' + (c.kbps_agora || 0) + ' kbps agora)');
      }
    }, 1000);
    const r = await fetch('/api/cameras/' + encodeURIComponent(camera.id) + '/trecho?segundos=60',
                          { credentials: 'same-origin' });
    if (!r.ok) {
      let j = {};
      try { j = JSON.parse(await r.text()); } catch (e) { j = {}; }
      throw new Error(j.erro || ('HTTP ' + r.status));
    }
    const bytes = Number(r.headers.get('X-Lecsor-Bytes') || 0);
    const dur = Number(r.headers.get('X-Lecsor-Duracao-S') || 0);
    const id = r.headers.get('X-Lecsor-Trecho-Id') || '';
    const cd = r.headers.get('Content-Disposition') || '';
    const nome = (cd.split('filename="')[1] || 'trecho.mp4').replace('"', '');
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = nome;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 120000);
    camera.trecho = { id, bytes, duracao: dur, nome, mb: bytes / 1e6 };
    // o tamanho do arquivo é o que se compara com o Mbps do admin/captura — nada de comparativo aqui
    linhaTrecho(jan, 'baixado: ' + nome + ' · ' + (bytes / 1e6).toFixed(1) + ' MB em ' + Math.round(dur) +
      ' s (confira o tamanho do arquivo com o Mbps do admin)');
  } catch (e) {
    linhaTrecho(jan, 'não foi possível baixar o trecho: ' + (e && e.message ? e.message : e));
  } finally {
    if (timer) clearInterval(timer);
    botao.disabled = false;
    S.trechoEmCurso = false;
  }
}

/* O comparativo de Mbps (medido no arquivo x declarado, compressao recalculada, veredito `bate`,
   sha256) SAIU da tela do cliente a pedido do dono (16/11/2026, teste cego do Mbps): o
   `/api/trechos/<id>/atestado` continua existindo, mas so' a operacao/admin alcanca. Aqui a tela
   entrega o ARQUIVO e o tamanho dele e' a prova. */

function pintarAviso(c, jan) {
  const aviso = jan.querySelector('.aviso-cam');
  if (!aviso) return;
  if (!c.no_ar && c.motivo) { aviso.textContent = '⚠ ' + c.motivo; aviso.style.display = 'block'; }
  else { aviso.textContent = ''; aviso.style.display = 'none'; }
}

function pintarEstados() {
  for (const c of S.cameras) {
    const jan = $('palco').querySelector(`[data-cam="${c.id}"]`);
    if (!jan) continue;
    const ponto = jan.querySelector('.rotulo-cam .ponto');
    if (ponto) ponto.className = 'ponto' + (c.no_ar ? '' : ' ruim');
    // o botao de energia e o aviso seguem o estado FRESCO da camera: sem isso o rotulo ficava
    // preso no estado antigo e o segundo clique repetia a acao errada.
    const b = jan.querySelector('.botao-cam');
    if (b) {
      b.textContent = c.no_ar ? 'Desligar' : 'Ligar';
      b.title = c.no_ar ? 'Desliga a câmera (solta o dispositivo de captura)'
                        : 'Liga a câmera de novo com o último ajuste';
      b.onclick = (ev) => { ev.stopPropagation(); energia(c.id, !c.no_ar); };
    }
    pintarAviso(c, jan);
    // o rotulo tambem segue o estado: o motivo entra quando a camera cai e sai quando ela volta
    const nome = jan.querySelector('.rotulo-cam span:last-child');
    if (nome && nome.dataset.base) nome.textContent = nome.dataset.base + (c.no_ar ? '' : ' · fora do ar');
    // a camera voltou depois de desligada/caida: rearma o player, senao a janela fica preta
    // mesmo com o fluxo no ar (o player sozinho pode demorar ou desistir depois de varios erros).
    const v = jan.querySelector('video');
    if (v && c.no_ar && jan.dataset.noAr === '0') window.Video.ligar(c.id, c.id, v);
    jan.dataset.noAr = c.no_ar ? '1' : '0';
    jan.classList.toggle('selecionada', S.selecionadas.has(c.id));
  }
}

/* Analises de video (Fase 5): a caixa vem do agente (metadado), nunca do video do cliente.
   O que a tela recebe e o resultado (caixa, contagem, linha), nao o video analisado nem credencial. */
function desenharCaixas(cameraId) {
  const alvo = $('caixas-' + cameraId);
  if (!alvo) return;
  limpar(alvo);
  if (!S.ia) return;
  const ag = S.agentesPorCamera[cameraId];
  if (!ag) return;
  const jan = $('palco').querySelector(`[data-cam="${cameraId}"]`);
  /* Linha e zonas vêm em fração do quadro (0..1) desenhadas pelo operador: o SVG estica junto
     com a janela, então a marca aparece exatamente onde foi desenhada. */
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 100 56.25');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('class', 'camada-ia');
  const criar = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  for (const z of (ag.zonas || [])) {
    svg.appendChild(criar('rect', { x: z.x * 100, y: z.y * 56.25, width: z.l * 100, height: z.a * 56.25,
                                    fill: 'rgba(239,68,68,.14)', stroke: '#ef4444', 'stroke-width': .35 }));
  }
  for (const l of (ag.linhas || [])) {
    if (!l || !l.a || !l.b) continue;
    const e = criar('line', { x1: l.a[0] * 100, y1: l.a[1] * 56.25, x2: l.b[0] * 100, y2: l.b[1] * 56.25,
                              stroke: '#38bdf8', 'stroke-width': .5, 'stroke-dasharray': '2 1.5', 'class': 'linha-ia' });
    svg.appendChild(e);
  }
  alvo.appendChild(svg);
  /* Deteccao velha nao fica desenhada: sem leitura nova, a caixa sai da tela (evita
     moldura congelada fingindo deteccao ao vivo). Linha e zonas do operador continuam. */
  const idade = Number(ag.caixas_idade || 0);
  const fresca = idade <= 3;
  for (const c of (fresca ? (ag.caixas || []) : [])) {
    const d = document.createElement('div');
    d.className = 'caixa';
    d.style.left = (c.caixa[0] * 100) + '%'; d.style.top = (c.caixa[1] * 100) + '%';
    d.style.width = ((c.caixa[2] - c.caixa[0]) * 100) + '%'; d.style.height = ((c.caixa[3] - c.caixa[1]) * 100) + '%';
    const s = document.createElement('span'); s.textContent = `${esc(c.classe)} ${Math.round((c.confianca || 0) * 100)}%`;
    d.appendChild(s); alvo.appendChild(d);
  }
  const ultima = (S.analises.contagens || []).find((x) => x.camera_id === cameraId);
  if (ultima && jan) {
    const selo = document.createElement('span');
    selo.className = 'selo-ia';
    const quando = idade >= 2 ? `há ${idade.toFixed(0)}s` : 'agora';
    const n = (ag.caixas || []).length;
    selo.innerHTML = fresca
      ? `👤 <b>${n}</b> ${quando} · entrou <b>${ultima.entrou}</b> · saiu <b>${ultima.saiu}</b>`
      : (n ? `✨ sem detecção nova há ${idade.toFixed(0)}s (última: ${n}) · entrou <b>${ultima.entrou}</b> · saiu <b>${ultima.saiu}</b>`
           : `✨ nenhuma pessoa detectada · entrou <b>${ultima.entrou}</b> · saiu <b>${ultima.saiu}</b>`);
    if (!fresca) selo.classList.add('ia-velha');   // leitura antiga: o selo explica, a caixa sai
    jan.appendChild(selo);
  }
}

function atualizarSeloIA() {
  const b = $('btn-ia');
  if (!b) return;
  const ags = S.analises.agentes || [];
  const noar = ags.filter((a) => a.estado === 'no ar').length;
  b.classList.toggle('on', S.ia);
  b.textContent = S.ia ? `IA · Análises (${noar} câmera${noar === 1 ? '' : 's'})` : 'IA · Análises';
}

function montarPaginacao() {
  const p = $('paginacao');
  const total = paginas();
  if (S.tela !== 'visualizar' || total <= 1) { p.classList.add('oculto'); limpar(p); return; }
  p.classList.remove('oculto'); limpar(p);
  const botao = (texto, pagina, ativo) => {
    const b = document.createElement('button'); b.textContent = texto;
    if (ativo) b.classList.add('on');
    b.onclick = () => { S.pagina = pagina; desenharVisualizar(); };
    return b;
  };
  p.appendChild(botao('«', 1));
  p.appendChild(botao('‹', Math.max(1, S.pagina - 1)));
  for (let i = 1; i <= total; i++) p.appendChild(botao(String(i), i, i === S.pagina));
  p.appendChild(botao('›', Math.min(total, S.pagina + 1)));
  const fim = document.createElement('span'); fim.style.marginLeft = '8px';
  fim.textContent = `Página ${S.pagina} de ${total}`;
  p.appendChild(fim);
}

/* ---------------------------------------------------------------- outras telas */
function tabelaEmPalco(colunas, linhas, vazio) {
  const palco = $('palco');
  const assinaturaCols = colunas.map((c) => c.rotulo).join('|');
  /* Mesma tabela com a mesma quantidade de linhas: troca somente a célula que mudou de texto.
     Sem isso, cada ciclo apagava a tabela inteira e repintava — o "recarregamento" que a tela
     mostrava a cada poucos segundos. */
  const atual = palco.querySelector('table');
  if (atual && linhas.length && palco.dataset.colunas === assinaturaCols && Number(palco.dataset.linhas) === linhas.length) {
    atualizarTabela(atual, colunas, linhas);
    return;
  }
  limpar(palco); palco.dataset.montado = '';
  const t = document.createElement('table'); t.style.width = '100%'; t.style.borderCollapse = 'collapse';
  t.style.fontSize = '13px'; t.style.background = 'var(--painel)';
  const th = document.createElement('thead'); const tr = document.createElement('tr');
  for (const c of colunas) { const e = document.createElement('th'); e.textContent = c.rotulo;
    e.style.cssText = 'text-align:left;padding:8px 10px;border-bottom:1px solid #1e293b;color:#94a3b8;font-weight:600'; tr.appendChild(e); }
  th.appendChild(tr); t.appendChild(th);
  const tb = document.createElement('tbody');
  if (!linhas.length) {
    const tr2 = document.createElement('tr'); const td = document.createElement('td');
    td.colSpan = colunas.length; td.textContent = vazio; td.style.cssText = 'padding:16px 10px;color:#94a3b8';
    tr2.appendChild(td); tb.appendChild(tr2);
  }
  for (const l of linhas) {
    const tr2 = document.createElement('tr');
    for (const c of colunas) { const td = document.createElement('td');
      td.style.cssText = 'padding:8px 10px;border-bottom:1px solid #16202f';
      const v = c.valor ? c.valor(l) : l[c.campo];
      if (v instanceof Node) td.appendChild(v); else td.textContent = esc(v);
      tr2.appendChild(td); }
    tb.appendChild(tr2);
  }
  t.appendChild(tb); palco.appendChild(t);
  palco.dataset.colunas = assinaturaCols; palco.dataset.linhas = String(linhas.length);
}

/* Troca no lugar só as células cujo texto mudou: nada de apagar e remontar a tabela. */
function atualizarTabela(t, colunas, linhas) {
  const trs = t.querySelectorAll('tbody tr');
  for (let i = 0; i < linhas.length; i++) {
    const tds = trs[i] ? trs[i].children : [];
    for (let j = 0; j < colunas.length; j++) {
      const td = tds[j];
      if (!td) continue;
      const v = colunas[j].valor ? colunas[j].valor(linhas[i]) : linhas[i][colunas[j].campo];
      if (v instanceof Node) continue;
      const texto = esc(v);
      if (td.textContent !== texto) td.textContent = texto;
    }
  }
}

const TELAS = {
  visualizar: ['Transmissões ao vivo', 'Monitoramento em tempo real das câmeras selecionadas.'],
  alertas: ['Alertas', 'Queda de câmera, perda de sinal e eventos das análises de vídeo.'],
  gravacoes: ['Gravações', 'Trechos gravados pela operação (depende da retenção da embarcação).'],
  radar_hd: ['Radar de óleo (HD)', 'As imagens do radar ficam gravadas o tempo todo no computador de captura. Procure por data e hora e peça o trecho que quiser ver.'],
  relatorios: ['Relatórios', 'Indicadores medidos pelo sistema: disponibilidade, contagens e qualidade do link.'],
  pessoas: ['Pessoas', 'Cadastro usado pelas análises de vídeo — só liga com a autorização registrada.'],
  cameras: ['Câmeras', 'Câmeras liberadas para a sua empresa e o estado de cada uma.'],
  avisos: ['Avisos', 'Preferências de notificação deste usuário.'],
  transmissao: ['Transmitir', 'Você abre a transmissão da câmera: a ordem vai até a máquina de captura da embarcação.'],
  configuracao: ['Tempo de transmissão', 'Quanto tempo cada transmissão pode durar antes de parar.']
};

function desenharTela() {
  const [titulo, sub] = TELAS[S.tela] || TELAS.visualizar;
  $('titulo-tela').textContent = titulo; $('sub-tela').textContent = sub;
  $('controles').classList.toggle('oculto', S.tela !== 'visualizar');
  $('hd-filtro').classList.toggle('oculto', S.tela !== 'radar_hd');
  $('paginacao').classList.add('oculto');
  const t = S.tela;
  if (t === 'alertas') {
    const caidas = S.cameras.filter((c) => !c.no_ar).map((c) => ({ tipo: 'camera_fora_do_ar', camera_id: c.rotulo, inicio: 'agora', confianca: '', clipe: '' }));
    const rotulos = {};
    for (const c of S.cameras) rotulos[c.id] = c.rotulo;
    const daAnalise = (S.analises.eventos || []).map((e) => ({
      tipo: e.tipo === 'entrada' ? 'contagem · entrada' : e.tipo === 'saida' ? 'contagem · saída' : e.tipo,
      camera_id: rotulos[e.camera_id] || e.camera_id, inicio: e.inicio,
      confianca: e.confianca ? Math.round(e.confianca * 100) + '%' : '', clipe: e.clipe }));
    const ev = S.eventos.map((e) => ({ tipo: e.tipo, camera_id: rotulos[e.camera_id] || e.camera_id, inicio: e.inicio, confianca: e.confianca, clipe: e.clipe }));
    tabelaEmPalco([{ rotulo: 'Quando', campo: 'inicio' }, { rotulo: 'Tipo', campo: 'tipo' },
                   { rotulo: 'Câmera', campo: 'camera_id' }, { rotulo: 'Confiança', campo: 'confianca' },
                   { rotulo: 'Clipe', campo: 'clipe' }], caidas.concat(daAnalise).concat(ev),
      'Nenhum alerta: todas as câmeras da sua embarcação estão no ar.');
  } else if (t === 'gravacoes') {
    /* A gravação fica no LADO TERRA (o vídeo que já chegou pela rede). Aqui o cliente vê o que ficou
       gravado nas transmissões da embarcação dele e baixa — nada é apagado do histórico. */
    const feitas = (S.transmissao.historico || []).filter((x) => x.gravacao && x.gravacao.tem);
    tabelaEmPalco([
      { rotulo: 'Quando', campo: 'quando' },
      { rotulo: 'Câmera', campo: 'camera' },
      { rotulo: 'Quem', campo: 'quem' },
      { rotulo: 'Durou', campo: 'durou' },
      { rotulo: 'Tamanho', campo: 'tamanho' },
      { rotulo: 'Gravação', valor: (l) => l.baixar },
    ], feitas.map((x) => ({
      quando: (x.criada_em || '').replace('T', ' ').slice(0, 19),
      camera: rotuloDe(x.camera_id),
      quem: x.usuario_email || '',
      durou: duracaoDa(x),
      tamanho: emMB((x.gravacao || {}).bytes),
      baixar: (() => {
        const a = document.createElement('a');
        a.href = '/api/gravacoes/' + encodeURIComponent(x.id);
        a.textContent = 'baixar';
        return a;
      })(),
    })), 'Nenhuma gravação ainda. Grave pela tela Transmitir — a gravação fica no lado terra e não é apagada.');
  } else if (t === 'radar_hd') {
    /* O HD do radar fica no PC de captura gravando o tempo todo; aqui o cliente procura por data e hora,
       PEDE o trecho e baixa quando chegar (dono, 19/11/2026). Nada sobe de video sem pedido. */
    const cat = S.hd || { catalogos: [], pedidos: [] };
    const blocos = [];
    for (const c of (cat.catalogos || [])) {
      for (const b of (c.blocos || [])) {
        blocos.push({ camera_id: c.camera_id, arquivo: b.arquivo, inicio: String(b.inicio || ''),
                      bytes: b.bytes || 0, embarcacao: c.embarcacao_nome || c.embarcacao_id || '' });
      }
    }
    blocos.sort((a, b) => String(b.inicio).localeCompare(String(a.inicio)));
    const de = ($('hd-de') || {}).value || '';
    const ate = ($('hd-ate') || {}).value || '';
    const mostrados = blocos.filter((b) => (!de || b.inicio >= de) && (!ate || b.inicio <= ate + ':59'));
    const resumo = $('hd-resumo');
    if (resumo) {
      const total = blocos.reduce((s, b) => s + (b.bytes || 0), 0);
      resumo.textContent = blocos.length
        ? `${blocos.length} trecho(s) · ${emMB(total)} · de ${blocos[blocos.length - 1].inicio.replace('T', ' ').slice(0, 16)} até ${blocos[0].inicio.replace('T', ' ').slice(0, 16)}`
        : 'o computador de captura ainda não publicou imagens do radar';
    }
    const jaPedido = {};
    for (const p of (cat.pedidos || [])) jaPedido[p.camera_id + '|' + p.arquivo] = p;
    const colunasHd = [];
    if (S.papel === 'observador') colunasHd.push({ rotulo: 'Embarcação', campo: 'embarcacao' });
    colunasHd.push({ rotulo: 'Quando (início do trecho)', campo: 'quando' },
                   { rotulo: 'Tamanho', campo: 'tamanho' },
                   { rotulo: 'Situação', campo: 'situacao' },
                   { rotulo: 'Trecho', valor: (l) => l.acao });
    tabelaEmPalco(colunasHd, mostrados.slice(0, 300).map((b) => {
      const p = jaPedido[b.camera_id + '|' + b.arquivo];
      let acao;
      let situacao = 'no HD do barco';
      if (p && p.estado === 'enviado') {
        acao = document.createElement('a');
        acao.href = '/api/hd/baixar?id=' + encodeURIComponent(p.id);
        acao.textContent = 'baixar';
        situacao = 'pronto em terra';
      } else if (p && p.estado === 'pedido') {
        acao = document.createElement('button'); acao.className = 'pil'; acao.disabled = true;
        acao.textContent = 'chegando…'; situacao = 'pedido enviado ao barco';
      } else if (p && p.estado === 'erro') {
        acao = document.createElement('button'); acao.className = 'pil'; acao.disabled = true;
        acao.textContent = 'indisponível'; situacao = 'saiu do HD (' + (p.motivo || 'erro') + ')';
      } else {
        acao = document.createElement('button'); acao.className = 'pil'; acao.textContent = 'pedir';
        acao.addEventListener('click', () => pedirTrechoDoHd(b.camera_id, b.arquivo, acao));
      }
      return { embarcacao: b.embarcacao, quando: b.inicio.replace('T', ' ').slice(0, 19),
               tamanho: emMB(b.bytes), situacao, acao };
    }), S.hd ? 'Nenhum trecho neste horário — tente um intervalo maior (as imagens ficam guardadas no computador de captura e o mais antigo gira quando o disco enche).'
      : 'Carregando as imagens do radar…');
  } else if (t === 'relatorios') {
    const linhas = S.cameras.map((c) => ({ camera: c.rotulo, estado: c.no_ar ? 'no ar' : 'fora do ar',
      encoder: c.encoder && c.encoder.bitrate ? c.encoder.bitrate : '', leitores: c.leitores }));
    const contagens = (S.analises.contagens || []).map((x) => ({ camera: rotuloDe(x.camera_id), entrou: x.entrou, saiu: x.saiu,
      pico: x.pico, fonte: x.fonte, quando: (x.janela_fim || '').replace('T', ' ').slice(0, 19) }));
    tabelaEmPalco([{ rotulo: 'Câmera', campo: 'camera' }, { rotulo: 'Estado', campo: 'estado' },
                   { rotulo: 'Bitrate', campo: 'encoder' }, { rotulo: 'Espectadores', campo: 'leitores' }], linhas,
      'Sem dado de relatório.');
    const p = $('palco');
    const ags = S.analises.agentes || [];
    /* Estas linhas ficam fora da tabela: só são remontadas quando o texto delas muda de verdade. */
    const textoExtras = ags.map((ag) => `${ag.camera_id}|${ag.estado}|${ag.modelo}|${ag.fps}|${ag.quadros}`).join('§')
      + '||' + contagens.map((x) => `${x.camera}|${x.entrou}|${x.saiu}|${x.pico}`).join('§');
    let cx = p.querySelector('.extras-relatorio');
    if (!cx) { cx = document.createElement('div'); cx.className = 'extras-relatorio'; p.appendChild(cx); }
    if (cx.dataset.marca !== textoExtras) {
      cx.dataset.marca = textoExtras;
      limpar(cx);
      for (const ag of ags) {
        const h2 = document.createElement('div'); h2.className = 'agente-linha';
        const sinal = document.createElement('span'); sinal.className = 'sinal' + (ag.estado === 'no ar' ? ' noar' : '');
        h2.appendChild(sinal);
        const txt = document.createElement('span');
        txt.textContent = `Agente de análise em ${rotuloDe(ag.camera_id)}: ${ag.estado} · modelo ${ag.modelo} · ${ag.fps} quadros/s · ${ag.quadros} quadros analisados`;
        h2.appendChild(txt); cx.appendChild(h2);
      }
      if (contagens.length) {
        const h = document.createElement('div'); h.className = 'vazio';
        h.textContent = 'Contagens de pessoas: ' + contagens.slice(0, 4).map((c) => `${c.camera}: ${c.entrou} entrada(s) / ${c.saiu} saída(s) · pico ${c.pico}`).join(' · ');
        cx.appendChild(h);
      }
    }
  } else if (t === 'pessoas') {
    tabelaEmPalco([{ rotulo: 'Pessoa', campo: 'nome' }, { rotulo: 'Cadastrada em', campo: 'data' }], [],
      'Reconhecimento de pessoas está desligado: dado sensível (LGPD) — só liga com a autorização registrada pelo responsável.');
  } else if (t === 'cameras') {
    tabelaEmPalco([{ rotulo: 'Câmera', campo: 'rotulo' }, { rotulo: 'Local', campo: 'local' },
                   { rotulo: 'Estado', valor: (l) => (l.no_ar ? 'no ar' : 'fora do ar') },
                   { rotulo: 'Resolução', valor: (l) => (l.encoder && l.encoder.resolucao) || '—' },
                   { rotulo: 'Bitrate', valor: (l) => (l.encoder && l.encoder.bitrate) || '—' }], S.cameras, 'Nenhuma câmera liberada.');
  } else if (t === 'avisos') {
    const p = $('palco');
    const salvo = localStorage.getItem('lecsor-avisos') || 'queda de câmera';
    /* A caixa só é remontada quando a preferência muda (antes era refeita a cada ciclo de 5 s). */
    let cx = p.querySelector('.avisos-caixa');
    if (!cx) { limpar(p); p.dataset.montado = ''; cx = document.createElement('div'); cx.className = 'avisos-caixa'; p.appendChild(cx); }
    if (cx.dataset.marca !== salvo) {
      cx.dataset.marca = salvo;
      limpar(cx);
      const d = document.createElement('div'); d.className = 'vazio';
      d.innerHTML = 'Notificações ativas: <b>' + salvo + '</b>.';
      const b = document.createElement('button'); b.className = 'acao'; b.textContent = 'Alternar alerta de queda de câmera';
      b.style.cssText = 'margin-top:10px;background:#1b2330;border:1px solid #243044;border-radius:9px;padding:9px 14px';
      b.onclick = () => { const novo = salvo.includes('queda de câmera') ? 'nenhum aviso' : 'queda de câmera';
        localStorage.setItem('lecsor-avisos', novo); desenharTela(); };
      cx.appendChild(d); cx.appendChild(b);
    }
  } else if (t === 'transmissao') {
    desenharTransmissao();
  } else if (t === 'configuracao') {
    desenharConfiguracao();
  }
}

/* Redesenha a TELA que esta' aberta depois de mexer numa transmissao. Na GRADE nao se remonta o palco
   (remontar recria os <video> e a imagem pisca): so' o quadro de controle de cada janela e' repintado
   (dono, 24/11/2026 — sem isto o botao ficava "pedindo…" para sempre na grade). */
function redesenharTransmissao() {
  if (S.tela !== 'visualizar') { desenharTela(); return; }
  const palco = $('palco');
  for (const c of (S.cameras || [])) {
    const el = palco.querySelector(`[data-st="${c.id}"]`);
    if (el) atualizarControle(c, el);
  }
}

/* ---------------------------------------------- transmissao a pedido do cliente (17/11/2026)
   O CLIENTE abre a transmissao pela web; a ordem nasce no lado terra e vai ate' a maquina de captura
   da embarcacao. A tela bate um "estou aqui" enquanto esta' aberta: fechou a tela ou desligou o
   computador, o lado terra derruba SO' a sessao de quem fechou — se outro cliente esta' vendo, a
   transmissao continua para ele. */
/* ===================== transmissao NO QUADRO (dono, 24/11/2026) =====================
   O que o dono fixou: (a) a transmissao vive so' enquanto ALGUEM assiste — saiu o cliente e
   ninguem mais esta' vendo, para (ele testou: "sai da tela e continuou transmitindo"); (b) a tela
   mostra o tempo que falta, avisa no ULTIMO MINUTO perguntando se quer continuar (D1=1 minuto),
   e se nao houver resposta DESLIGA (D2= "silencio desliga"); (c) depois de cair aparece "Reconectar";
   (d) um botao para gravar (so' o que ja' chegou no lado terra — D4). Tudo na tela que ele usa. */

/* Qual sessao MINHA existe nesta camera agora, e se ja' houve alguma (para "Iniciar" x "Reconectar"). */
function sessaoDaCamera(camId) {
  const t = S.transmissao || {};
  const meu = (S.usuario || {}).email;
  const abertas = (t.abertas || []).filter((x) => x.camera_id === camId);
  const minha = abertas.find((x) => x.usuario_email === meu) || null;
  const quantos = new Set(abertas.map((x) => x.usuario_email)).size;
  const jaViu = !!minha || (t.historico || []).some((x) => x.camera_id === camId && x.usuario_email === meu);
  return { minha, quantos, jaViu };
}

function _bt(papel, texto, classe) {
  const b = document.createElement('button');
  b.dataset.papel = papel; b.className = (classe || 'botao-st'); b.textContent = texto;
  return b;
}

/* Monta o quadro de controle UMA vez; o criador de texto fica em atualizarControle (roda a cada 1 s). */
function montarControle(c, el, jan) {
  el.innerHTML = '';
  const est = document.createElement('span'); est.dataset.papel = 'estado'; est.className = 'st-estado';
  const cont = document.createElement('span'); cont.dataset.papel = 'contagem'; cont.className = 'st-contagem';
  const aviso = document.createElement('div'); aviso.dataset.papel = 'aviso'; aviso.className = 'st-aviso';
  el.append(est, cont, _bt('iniciar', 'Iniciar transmissão'), _bt('gravar', 'Gravar (no lado terra)'),
            _bt('parar', 'Parar transmissão'), aviso);
  atualizarControle(c, el);
}

/* Reconstrói o estado do controle a partir da sessao ATUAL. Roda a cada 1 s (relogio) e a cada
   atualizacao de 5 s — por isso so' troca TEXTO; os botoes do aviso sao montados uma vez por sessao
   (senao o clique do cliente era engolido pela reconstrucao do botao no meio do segundo). */
function atualizarControle(c, el) {
  const { minha, quantos, jaViu } = sessaoDaCamera(c.id);
  const q = (p) => el.querySelector(`[data-papel="${p}"]`);
  const est = q('estado'), cont = q('contagem'), aviso = q('aviso');
  const bIni = q('iniciar'), bGrav = q('gravar'), bPar = q('parar');
  const avisoSeg = (S.transmissao && S.transmissao.aviso_segundos) || 60;
  const restante = minha && minha.termina_em
    ? Math.round((new Date(minha.termina_em).getTime() - Date.now()) / 1000) : 0;
  est.textContent = ''; cont.textContent = '';
  aviso.classList.remove('mostra');
  bIni.style.display = 'none'; bGrav.style.display = 'none'; bPar.style.display = 'none';

  if (!minha) {
    aviso.dataset.sig = '';
    if (quantos > 0) { est.className = 'st-estado ok'; est.textContent = 'no ar — outro cliente assistindo'; }
    else { est.className = 'st-estado' + (c.no_ar ? ' ok' : ''); est.textContent = c.no_ar ? 'no ar agora' : 'parada'; }
    bIni.style.display = ''; bIni.disabled = false;
    bIni.textContent = jaViu ? 'Reconectar' : 'Iniciar transmissão';
    /* a janela de fora-da-tela vem do servidor: se voce sair da tela e voltar dentro dela, a sessao
       continua de pe — sem precisar reconectar. */
    const jan = (S.transmissao && S.transmissao.janela_sem_tela) || 60;
    bIni.title = 'A transmissão segue no ar por ' + jan + ' s se você sair desta tela e voltar';
    bIni.onclick = (ev) => { ev.stopPropagation(); pedirTransmissao(c.id, bIni); };
    return;
  }
  const vivo = minha.estado === 'no_ar' || minha.estado === 'pedida';
  est.className = 'st-estado ok';
  est.textContent = minha.estado === 'no_ar' ? 'no ar' : 'conectando…';
  if (quantos > 1) est.textContent += ' (' + quantos + ' assistindo)';
  cont.textContent = vivo ? '· ' + mmss(Math.max(0, restante)) : '';
  if (!vivo) { aviso.dataset.sig = ''; return; }

  const gravando = !!minha.gravando || !!(minha.gravacao && minha.gravacao.gravando);
  bGrav.style.display = ''; bGrav.classList.toggle('on', gravando);
  bGrav.textContent = gravando ? 'Parar gravação' : 'Gravar (no lado terra)';
  bGrav.onclick = (ev) => { ev.stopPropagation(); marcarGravando(minha.id, !gravando, bGrav); };
  bPar.style.display = ''; bPar.textContent = 'Parar transmissão';
  bPar.onclick = (ev) => { ev.stopPropagation(); pararTransmissao(minha.id, bPar); };

  /* AVISO DO ULTIMO MINUTO (D1/D2): pergunta se quer continuar. Nao ha resposta "automatica": se o
     cliente nao clicar, a sessao expira no prazo sozinha e o botao vira "Reconectar" — que e' o que
     o dono pediu ("silencio desliga"). */
  if (restante <= avisoSeg) {
    const sig = 'aviso|' + minha.id;
    if (aviso.dataset.sig !== sig) {
      aviso.dataset.sig = sig; aviso.innerHTML = '';
      const t = document.createElement('span'); t.className = 'st-aviso-txt'; t.dataset.papel = 'aviso-txt';
      const bc = _bt('continuar', 'Continuar conectado', 'botao-st ok');
      bc.onclick = (ev) => { ev.stopPropagation(); continuarTransmissao(minha.id, bc); };
      const bn = _bt('nao', 'Não, encerrar', 'botao-st');
      bn.onclick = (ev) => { ev.stopPropagation(); pararTransmissao(minha.id, bn); };
      aviso.append(t, bc, bn);
    }
    aviso.classList.add('mostra');
    const txt = aviso.querySelector('[data-papel="aviso-txt"]');
    if (txt) txt.textContent = 'Sua transmissão será encerrada em ' + mmss(Math.max(0, restante)) + '. Continuar conectado?';
  } else { aviso.dataset.sig = ''; aviso.innerHTML = ''; }
}

function tickDaContagem() {
  if (S.tela !== 'visualizar') return;
  const palco = $('palco');
  for (const c of (S.cameras || [])) {
    const el = palco.querySelector(`[data-st="${c.id}"]`);
    if (el) atualizarControle(c, el);
  }
}

async function continuarTransmissao(tid, botao) {
  if (botao) { botao.disabled = true; botao.textContent = 'continuando…'; }
  const d = await api('/api/transmissao/' + tid + '/continuar', { method: 'POST', body: '{}' });
  if (!d.ok) alert((d.corpo && d.corpo.erro) || 'não deu para continuar a transmissão');
  await carregarTransmissao();
  redesenharTransmissao();
}

async function carregarTransmissao() {
  if (!S.embarcacaoId) return;
  const d = await api('/api/transmissao?embarcacao=' + encodeURIComponent(S.embarcacaoId));
  if (d.ok && d.corpo) S.transmissao = d.corpo;
  // gravacoes prontas esperando o cliente baixar (o aviso da tela sai daqui)
  S.gravacoesProntas = (S.transmissao && S.transmissao.gravacoes_prontas) || [];
  const meu = (S.usuario || {}).email;
  S.minhas = (S.transmissao.abertas || []).filter((t) => t.usuario_email === meu).map((t) => t.id);
}

/* --------------------------------------------------------------------------------------------
   GRAVACAO: aviso para baixar e apagamento quando o cliente sai (dono, 18/11/2026).

   O que o dono fixou: ao fim da gravacao o cliente E' AVISADO para baixar; quando ele sair da tela
   (ou desligar o sistema) o ARQUIVO e' apagado — o que fica e' o historico. Aqui fica o aviso, o
   botao de baixar, o "ja' baixei" (que apaga na hora) e o aviso do navegador antes de sair.
   -------------------------------------------------------------------------------------------- */
function baixadosLocal() {
  try { return JSON.parse(localStorage.getItem('lecsor-baixei') || '[]'); } catch (e) { return []; }
}

function marcarBaixado(id) {
  const l = baixadosLocal();
  if (!l.includes(id)) l.push(id);
  try { localStorage.setItem('lecsor-baixei', JSON.stringify(l)); } catch (e) { /* sem memoria local */ }
}

function gravacoesNaoBaixadas() {
  const feitas = baixadosLocal();
  return (S.gravacoesProntas || []).filter((g) => !feitas.includes(g.transmissao_id));
}

async function jaBaixei(g, botao) {
  if (botao) { botao.disabled = true; botao.textContent = 'apagando…'; }
  const d = await api('/api/gravacoes/' + encodeURIComponent(g.transmissao_id) + '/pronto',
                      { method: 'POST', body: '{}' });
  if (!d.ok) {
    alert((d.corpo && d.corpo.erro) || 'não deu para apagar agora');
    if (botao) { botao.disabled = false; botao.textContent = 'Já baixei — pode apagar'; }
    return;
  }
  marcarBaixado(g.transmissao_id);
  await carregarTransmissao();
  redesenharTransmissao();
}

function minutosAte(carimbo) {
  if (!carimbo) return null;
  const resta = Math.round((new Date(carimbo) - new Date()) / 60000);
  return resta > 0 ? resta : 0;
}

/* A faixa fica no alto da tela de transmissão enquanto houver gravacao pronta para baixar. */
function avisoDeGravacao(p) {
  const prontas = S.gravacoesProntas || [];
  if (!prontas.length || (S.usuario || {}).papel !== 'cliente') return;
  const cx = document.createElement('div'); cx.className = 'aviso-gravacao'; cx.id = 'aviso-gravacao';
  const t = document.createElement('div'); t.className = 'aviso-titulo';
  t.textContent = prontas.length === 1 ? 'Gravação pronta — baixe agora'
                                       : prontas.length + ' gravações prontas — baixe agora';
  cx.appendChild(t);
  const explica = document.createElement('div'); explica.className = 'aviso-explica';
  explica.textContent = 'O arquivo é apagado quando você sair da tela ou desligar o computador.';
  cx.appendChild(explica);
  for (const g of prontas) {
    const l = document.createElement('div'); l.className = 'aviso-linha'; l.dataset.gravacao = g.transmissao_id;
    const nome = document.createElement('span'); nome.className = 'aviso-nome';
    nome.textContent = rotuloDe(g.camera_id) + ' · ' + emMB(g.bytes) + ' · ' + mmss(g.segundos || 0);
    const resta = minutosAte(g.baixar_ate);
    if (resta !== null) nome.textContent += ' · restam ' + resta + ' min para baixar';
    l.appendChild(nome);
    const baixar = document.createElement('a'); baixar.className = 'pil'; baixar.id = 'baixar-' + g.transmissao_id;
    baixar.href = '/api/gravacoes/' + encodeURIComponent(g.transmissao_id);
    baixar.textContent = 'Baixar';
    baixar.addEventListener('click', () => marcarBaixado(g.transmissao_id));
    l.appendChild(baixar);
    const pronto = document.createElement('button'); pronto.className = 'pil';
    pronto.id = 'ja-baixei-' + g.transmissao_id;
    pronto.textContent = 'Já baixei — pode apagar';
    pronto.onclick = () => jaBaixei(g, pronto);
    l.appendChild(pronto);
    cx.appendChild(l);
  }
  p.appendChild(cx);
}

function mmss(seg) {
  const total = Math.max(0, Math.round(seg));
  return dois(Math.floor(total / 60)) + ':' + dois(total % 60);
}

function duracaoDa(t) {
  if (!t.criada_em) return '—';
  const fim = t.encerrada_em ? new Date(t.encerrada_em) : new Date();
  const seg = Math.max(0, Math.round((fim - new Date(t.criada_em)) / 1000));
  return mmss(seg);
}

function textoDaSessao(t, meu) {
  if (t.estado === 'no_ar') {
    return 'no ar' + (t.usuario_email === meu ? ' — a sua transmissão' : ' — outro cliente assistindo');
  }
  if (t.estado === 'pedida') return 'pedido enviado à máquina de captura…';
  if (t.estado === 'expirada') return 'parada: o tempo acabou — inicie de novo';
  if (t.estado === 'sem_sinal') return 'sem resposta da máquina de captura';
  return (t.estado || '') + (t.motivo ? ' — ' + t.motivo : '');
}

async function pedirTransmissao(cameraId, botao) {
  if (botao) { botao.disabled = true; botao.textContent = 'pedindo…'; }
  const d = await api('/api/transmissao/iniciar', { method: 'POST', body: JSON.stringify({ camera_id: cameraId }) });
  if (!d.ok) {
    alert((d.corpo && d.corpo.erro) || 'não deu para pedir a transmissão');
    if (botao) { botao.disabled = false; botao.textContent = 'Iniciar transmissão'; }
    return;
  }
  await carregarTransmissao();
  redesenharTransmissao();
}

function emMB(bytes) { return (Math.max(0, bytes || 0) / 1048576).toFixed(1) + ' MB'; }

/* Gravação no lado terra: o cliente liga e desliga; enquanto grava, o corte por tempo não acontece. */
async function marcarGravando(tid, ligado, botao) {
  if (botao) { botao.disabled = true; botao.textContent = ligado ? 'gravando…' : 'parando…'; }
  const d = await api('/api/transmissao/' + tid + '/gravando',
    { method: 'POST', body: JSON.stringify({ gravando: !!ligado }) });
  await carregarTransmissao();
  redesenharTransmissao();
  if (!d.ok) alert((d.corpo && d.corpo.erro) || 'não deu para gravar');
}

async function pararTransmissao(tid, botao) {
  if (botao) { botao.disabled = true; botao.textContent = 'parando…'; }
  await api('/api/transmissao/' + tid + '/encerrar', { method: 'POST', body: '{}' });
  await carregarTransmissao();
  redesenharTransmissao();
}

/* O "estou aqui": enquanto esta' tela estiver aberta a sessao vive. E' o que faz fechar a tela (ou
   desligar o computador) interromper a transmissao sem ninguem precisar clicar em nada.

   SAIDA DA TELA (dono, 24/11/2026): o batimento vale SO' na tela das cameras e com a aba visivel. Antes
   ele corria em qualquer tela, entao a sessao nunca expirava. Agora, saindo da tela, o lado terra deixa
   de receber o "estou aqui" e encerra a sessao depois da janela (SEGUNDOS_SEM_BATIMENTO = 60 s) — o
   cliente pode sair, ver outras coisas e VOLTAR dentro de 60 s sem precisar reconectar. */
async function baterPonto() {
  if (S.tela !== 'visualizar' || document.visibilityState !== 'visible') return;
  const minhas = S.minhas || [];
  for (const id of minhas) {
    try { await api('/api/transmissao/' + id + '/batimento', { method: 'POST', body: '{}' }); } catch (e) { /* volta na proxima */ }
  }
}

function desenharTransmissao() {
  const p = $('palco');
  limpar(p); p.dataset.montado = '';
  avisoDeGravacao(p);
  const meu = (S.usuario || {}).email;
  const cams = S.cameras || [];
  if (!cams.length) {
    const d = document.createElement('div'); d.className = 'vazio';
    d.textContent = 'Nenhuma câmera liberada para esta embarcação.';
    p.appendChild(d); return;
  }
  const cx = document.createElement('div'); cx.className = 'transmissao-caixa';
  for (const cam of cams) {
    const abertas = (S.transmissao.abertas || []).filter((t) => t.camera_id === cam.id);
    const minha = abertas.find((t) => t.usuario_email === meu);
    const quantos = new Set(abertas.map((t) => t.usuario_email)).size;
    const l = document.createElement('div'); l.className = 'transmissao-linha'; l.dataset.camera = cam.id;

    const nome = document.createElement('div'); nome.className = 'nome'; nome.textContent = cam.rotulo;
    const est = document.createElement('div');
    est.className = 'estado' + (minha && minha.estado === 'no_ar' ? ' noar' : '');
    est.dataset.estado = cam.id;
    if (minha) {
      est.textContent = textoDaSessao(minha, meu);
      if (minha.termina_em && minha.estado !== 'encerrada' && minha.estado !== 'expirada') {
        est.textContent += ' · tempo restante ' + mmss(minha.segundos_restantes || 0);
      }
    } else if (abertas.length) {
      est.textContent = 'no ar — outro cliente da sua empresa está assistindo';
    } else {
      est.textContent = cam.no_ar ? 'no ar agora' : 'parada';
    }
    if (quantos > 1) est.textContent += ' · ' + quantos + ' clientes assistindo';

    const acoes = document.createElement('div'); acoes.className = 'acoes-transmissao';
    const b = document.createElement('button');
    if (minha) {
      /* a gravacao mora no LADO TERRA (o vídeo que já chegou); enquanto grava, o tempo não corta */
      if ((minha.estado === 'no_ar' || minha.estado === 'pedida')) {
        const gravando = !!minha.gravando || !!(minha.gravacao && minha.gravacao.gravando);
        const g = document.createElement('button');
        g.className = 'pil' + (gravando ? ' on' : ''); g.id = 'gravar-' + cam.id;
        g.textContent = gravando ? 'Parar gravação' : 'Gravar (no lado terra)';
        g.onclick = () => marcarGravando(minha.id, !gravando, g);
        acoes.appendChild(g);
      }
      b.className = 'pil'; b.textContent = 'Parar transmissão'; b.id = 'parar-' + cam.id;
      b.onclick = () => pararTransmissao(minha.id, b);
    } else {
      b.className = 'pil on'; b.textContent = 'Iniciar transmissão'; b.id = 'iniciar-' + cam.id;
      b.onclick = () => pedirTransmissao(cam.id, b);
    }
    acoes.appendChild(b);
    l.appendChild(nome); l.appendChild(est); l.appendChild(acoes);
    cx.appendChild(l);
  }
  p.appendChild(cx);

  const h = document.createElement('div'); h.className = 'grupo-historico';
  h.textContent = 'Histórico das transmissões desta embarcação';
  p.appendChild(h);
  const hist = S.transmissao.historico || [];
  if (!hist.length) {
    const d = document.createElement('div'); d.className = 'vazio';
    d.textContent = 'Ainda não houve transmissão nesta embarcação.';
    p.appendChild(d); return;
  }
  const tb = document.createElement('table'); tb.className = 'historico';
  const th = document.createElement('thead');
  const trh = document.createElement('tr');
  for (const titulo of ['Quando', 'Câmera', 'Quem', 'Durou', 'Como terminou', 'Gravação']) {
    const c = document.createElement('th'); c.textContent = titulo; trh.appendChild(c);
  }
  th.appendChild(trh); tb.appendChild(th);
  const corpo = document.createElement('tbody');
  for (const t of hist.slice(0, 20)) {
    const tr = document.createElement('tr');
    for (const valor of [(t.criada_em || '').replace('T', ' ').slice(0, 19), rotuloDe(t.camera_id),
                         t.usuario_email || '', duracaoDa(t), textoDaSessao(t, meu)]) {
      const td = document.createElement('td'); td.textContent = valor; tr.appendChild(td);
    }
    const tdG = document.createElement('td');
    if (t.gravacao && t.gravacao.tem) {
      const a = document.createElement('a');
      a.href = '/api/gravacoes/' + encodeURIComponent(t.id);
      a.textContent = 'baixar (' + emMB(t.gravacao.bytes) + ')';
      tdG.appendChild(a);
    } else { tdG.textContent = '—'; }
    tr.appendChild(tdG);
    corpo.appendChild(tr);
  }
  tb.appendChild(corpo);
  p.appendChild(tb);
}

/* O que o cliente escolheu nesta tela. E' o que VENCE o valor do servidor: o redesenho nao pode
   apagar a escolha dele (mesmo defeito que a prova de tela pegou na tela do tempo). */
let tempoEscolhido = null;

function desenharConfiguracao() {
  const p = $('palco');
  limpar(p); p.dataset.montado = '';
  const cx = document.createElement('div'); cx.className = 'config-caixa';
  const d = document.createElement('div'); d.className = 'vazio';
  /* Dono (19/11/2026): "todas as configuracoes serao feitas por mim (admin), nada sera configurado pelo
     cliente". Com o tempo FIXADO pelo administrador, o cliente so' LE — a caixa de escolher sai. */
  const fixado = (S.transmissao || {}).teto_do_produto_s || 0;
  if (fixado) {
    d.textContent = 'O tempo de cada transmissão é definido pelo administrador da LECSOR '
      + `(${Math.round(fixado / 60)} min). Você não precisa configurar nada. Ao estourar o tempo a `
      + 'transmissão para e você inicia de novo — a menos que esteja gravando. Tudo fica no histórico.';
    cx.appendChild(d);
    p.appendChild(cx);
    return;
  }
  d.textContent = 'Tempo máximo de cada transmissão. Ao estourar, a transmissão para e você inicia de '
    + 'novo — a menos que esteja gravando. Tudo o que for feito fica no histórico.';
  cx.appendChild(d);
  const linha = document.createElement('div'); linha.className = 'transmissao-linha';
  const nome = document.createElement('div'); nome.className = 'nome'; nome.textContent = 'Tempo máximo';
  const atual = tempoEscolhido === null ? S.transmissao.tempo_maximo_s : tempoEscolhido;
  const sel = document.createElement('select'); sel.className = 'pil'; sel.id = 'tempo-maximo';
  for (const s of (S.transmissao.tempos || [900])) {
    const o = document.createElement('option'); o.value = s; o.textContent = (s / 60) + ' min';
    if (s === atual) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => { tempoEscolhido = parseInt(sel.value, 10); };
  const b = document.createElement('button'); b.className = 'pil on'; b.id = 'gravar-tempo';
  b.textContent = 'Gravar';
  b.onclick = async () => {
    b.disabled = true;
    const escolhido = tempoEscolhido === null ? parseInt(sel.value, 10) : tempoEscolhido;
    const r = await api('/api/transmissao/config',
      { method: 'POST', body: JSON.stringify({ tempo_maximo_s: escolhido }) });
    b.disabled = false;
    if (!r.ok) { alert((r.corpo && r.corpo.erro) || 'não deu para gravar'); return; }
    tempoEscolhido = null;          // gravou: o servidor passa a ser a verdade
    await carregarTransmissao();
    redesenharTransmissao();
  };
  const acoes = document.createElement('div'); acoes.className = 'acoes-transmissao';
  acoes.appendChild(b);
  linha.appendChild(nome); linha.appendChild(sel); linha.appendChild(acoes);
  cx.appendChild(linha);
  p.appendChild(cx);
}

/* ---------------------------------------------------------------- rodape e utilidades */
function atualizarRodape() {
  const total = S.cameras.length, sel = S.selecionadas.size;
  const inicio = total ? 1 : 0;
  const fim = Math.min(porPagina() * porPagina() * (S.pagina - 1) + porPagina() * porPagina(), sel);
  /* o rodape agora e' so' a linha de direitos (dono, 24/11/2026): a contagem so' existe se o elemento
     estiver na tela — sem ele, nada quebra. */
  const alvo = $('contagem-selecao');
  if (alvo) alvo.textContent = `Mostrando ${inicio}-${fim} de ${sel} câmeras selecionadas (total ${total})`;
}
function relogios() {
  const d = new Date();
  const sela = `${d.getFullYear()}-${dois(d.getMonth() + 1)}-${dois(d.getDate())} ${dois(d.getHours())}:${dois(d.getMinutes())}:${dois(d.getSeconds())}`;
  document.querySelectorAll('[data-relogio]').forEach((e) => { e.textContent = sela; });
}

function trocarTela(tela) {
  S.tela = tela; S.pagina = 1;
  document.querySelectorAll('.item[data-tela]').forEach((b) => b.classList.toggle('on', b.dataset.tela === tela));
  if (tela === 'transmissao' || tela === 'configuracao' || tela === 'gravacoes') { carregarTransmissao().then(desenharTela); }
  if (tela === 'visualizar') {
    desenharVisualizar();
    /* voltou para a tela do video: bate o "estou aqui" NA HORA (nao espera o tick de 10 s) — assim o
       retorno dentro da janela de 60 s nunca perde a sessao por atraso. */
    baterPonto();
  }
  else if (S.eventos.length === 0) dadosExtras().then(desenharTela);
  else desenharTela();
  desenharTela();
  atualizarRodape();
}

/* ---------------------------------------------------------------- eventos de interface */
$('form-entrar').addEventListener('submit', entrar);

/* O ENDERECO da tela do cliente (plano, Fase 1 P1): quem recebe o acesso recebe tambem o link — o
   cliente so' abre o endereco, sem manual e sem instalar nada. */
(function mostrarEndereco() {
  const url = location.origin + '/app/';
  const alvo = document.getElementById('endereco-texto');
  if (alvo) alvo.textContent = url;
  const b = document.getElementById('copiar-endereco');
  if (b) b.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(url); b.textContent = 'copiado'; }
    catch (e) { b.textContent = 'selecione e copie'; }
  });
})();
document.querySelectorAll('.item[data-tela]').forEach((b) => b.addEventListener('click', () => trocarTela(b.dataset.tela)));
document.querySelectorAll('#controles button[data-layout]').forEach((b) => b.addEventListener('click', () => {
  S.auto = false; S.layout = parseInt(b.dataset.layout, 10); S.pagina = 1;
  document.querySelectorAll('#controles button[data-layout]').forEach((x) => x.classList.remove('on'));
  b.classList.add('on'); $('btn-auto').classList.remove('on');
  S.selecionadas = new Set(S.cameras.map((c) => c.id));
  desenharVisualizar(); atualizarRodape();
}));
$('btn-auto').addEventListener('click', () => {
  S.auto = true; S.pagina = 1;
  document.querySelectorAll('#controles button[data-layout]').forEach((x) => x.classList.remove('on'));
  $('btn-auto').classList.add('on'); desenharVisualizar();
});
$('btn-ia').addEventListener('click', () => {
  S.ia = !S.ia;
  $('palco').querySelectorAll('.selo-ia').forEach((s) => s.remove());
  S.cameras.forEach((c) => desenharCaixas(c.id));
  atualizarSeloIA();
});
$('btn-destaque').addEventListener('click', () => {
  // o que estiver selecionado (a seleção nasce com todas); se não houver seleção, as da página
  const ids = Array.from(S.selecionadas);
  const alvos = ids.length ? ids : camerasDaPagina().map((c) => c.id);
  if (alvos.length > 4) {
    if (!confirm('Destacar apenas as 4 primeiras de ' + alvos.length + ' selecionadas?')) return;
  }
  abrirDestaque(alvos.slice(0, 4));
});
$('btn-cheia').addEventListener('click', () => {
  const alvo = $('palco');
  if (document.fullscreenElement) document.exitFullscreen(); else if (alvo.requestFullscreen) alvo.requestFullscreen();
});
/* O cliente saiu da tela (fechou, desligou o computador): avisa o lado terra na hora — e' o que faz o
   arquivo da gravacao ser apagado. Sem isto, a varredura do lado terra apaga sozinha depois do prazo. */
function avisarQueSaio() {
  try {
    const corpo = JSON.stringify({ embarcacao_id: S.embarcacaoId || '' });
    const bolo = new Blob([corpo], { type: 'application/json' });
    if (!(navigator.sendBeacon && navigator.sendBeacon('/api/transmissao/sair', bolo))) {
      fetch('/api/transmissao/sair', { method: 'POST', body: corpo, keepalive: true });
    }
  } catch (e) { /* a varredura do lado terra apaga depois do prazo */ }
}

/* Gravacao pronta e ainda NAO baixada: o navegador avisa antes de a tela sumir. */
window.addEventListener('beforeunload', (ev) => {
  if (gravacoesNaoBaixadas().length) {
    ev.preventDefault();
    ev.returnValue = 'Há gravação para baixar: ela é apagada quando você sair da tela.';
    return ev.returnValue;
  }
});

window.addEventListener('pagehide', avisarQueSaio);
/* a janela mudou de tamanho: a grade é recalculada (a imagem da câmera continua inteira, sem corte) */
window.addEventListener('resize', () => ajustarGrade());

$('btn-sair').addEventListener('click', async () => {
  avisarQueSaio();                                        /* apaga o que foi gravado para ele */
  await api('/api/sair', { method: 'POST' });
  location.reload();
});
$('embarcacao').addEventListener('change', (ev) => {
  S.embarcacaoId = ev.target.value; S.cameras = []; S.selecionadas = new Set(); S.pagina = 1;
  atualizar();
});
/* Os botoes do rodape SAIRAM na 0.13.2 (dono, 24/11/2026: "diminua o rodape ... mantenha apenas
   'Lecsor - Todos os direitos reservados'"): os listeners ficam ligados SO' se o elemento existir,
   para o app nao quebrar no boot com um rodape enxuto. */
const bLimpar = $('limpar');
if (bLimpar) bLimpar.addEventListener('click', () => { S.selecionadas = new Set(); S.pagina = 1; desenharVisualizar(); atualizarRodape(); });
const bAlertas = $('todos-alertas');
if (bAlertas) bAlertas.addEventListener('click', () => trocarTela('alertas'));
const bRelat = $('ir-relatorios');
if (bRelat) bRelat.addEventListener('click', () => trocarTela('relatorios'));
/* o ano da linha de direitos vem do relogio da maquina (nunca fica velho na tela) */
const elAno = $('ano'); if (elAno) elAno.textContent = String(new Date().getFullYear());
$('hd-filtrar').addEventListener('click', () => desenharTela());
$('hd-tudo').addEventListener('click', () => { $('hd-de').value = ''; $('hd-ate').value = ''; desenharTela(); });

/* HD do radar: o cliente ve o catalogo, pede o trecho e baixa (o bordo e' quem envia). */
async function carregarHd() {
  const r = await api('/api/hd/catalogo');
  S.hd = (r.ok && r.corpo) || { catalogos: [], pedidos: [] };
  return S.hd;
}
async function pedirTrechoDoHd(cameraId, arquivo, botao) {
  if (botao) { botao.disabled = true; botao.textContent = 'pedindo…'; }
  const r = await api('/api/hd/pedir', { method: 'POST', body: JSON.stringify({ camera_id: cameraId, arquivo }) });
  if (r.ok) { await carregarHd(); desenharTela(); return; }
  if (botao) { botao.disabled = false; botao.textContent = 'pedir'; }
  alert((r.corpo && r.corpo.erro) || 'não consegui pedir este trecho');
}
setInterval(relogios, 1000); setInterval(() => { if (S.tela === 'visualizar') pintarEstados(); }, 2000);
/* "estou aqui" da transmissao (10 s): e' o que mantem viva a sessao aberta nesta tela */
setInterval(baterPonto, 10000);
/* fechou a aba/navegador: avisa na hora; desligar o computador fica por conta do batimento */
window.addEventListener('pagehide', () => {
  for (const id of (S.minhas || [])) navigator.sendBeacon('/api/transmissao/' + id + '/encerrar');
});
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') baterPonto(); });
abrir();
