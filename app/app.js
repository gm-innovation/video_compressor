/* Front do cliente no formato VMS: grade ao vivo com paginacao, selecao, alertas, gravacoes,
   relatorios e cadastros. Fala somente com a API do produto. */
const S = {
  usuario: null, embarcacoes: [], cameras: [], embarcacaoId: null,
  tela: 'visualizar', layout: 3, auto: true, pagina: 1, selecionadas: new Set(), ia: false,
  podeCamera: false,
  eventos: [], contagens: [], relatorios: null, timer: null,
  analises: { agentes: [], contagens: [], eventos: [] }, agentesPorCamera: {}
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
  // ligar/desligar a CAMERA so faz sentido onde a camera esta plugada: a propria maquina de
  // captura (local) ou a operacao. O cliente remoto nunca ve esses botoes.
  S.podeCamera = !!(eu.corpo.local || eu.corpo.papel !== 'cliente');
  $('entrada').classList.add('oculto'); $('sistema').classList.remove('oculto');
  $('conta-email').textContent = eu.corpo.email;
  $('conta-papel').textContent = eu.corpo.papel === 'cliente' ? 'Cliente' : 'Operação LECSOR';
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
  if (S.tela === 'visualizar') {
    if (mudouLista || !$('palco').dataset.montado) desenharVisualizar();
    else { pintarEstados(); S.cameras.forEach((c) => desenharCaixas(c.id)); }
    atualizarSeloIA();
  }
  else {
    /* Nas telas de tabela a tela é atualizada no lugar (tabelaEmPalco só troca a célula que mudou),
       então repintar a cada 5 s não apaga mais nada; a marca evita trabalho quando nada mudou. */
    const marca = assinaturaTelas();
    if (marca !== marcaTela) { marcaTela = marca; desenharTela(); }
  }
  atualizarRodape();
}

/* Impressão digital do que a tela mostra. Campos que mudam sozinhos (relógio do resumo, idade da
   detecção) ficam fora: sozinhos não justificam repintar a tela. */
let marcaTela = '';
function assinaturaTelas() {
  try {
    return JSON.stringify([S.tela, S.cameras, S.eventos, S.contagens, S.relatorios, S.analises],
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
    jan.appendChild(v);
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
      jan.appendChild(ctrl);
    }
    // aviso no lugar da tela preta: sem isso o operador nao sabe se a camera caiu, foi desligada
    // ou falhou. Fica sempre no DOM e o pintarEstados() atualiza o texto a cada 5 s.
    const aviso = document.createElement('div'); aviso.className = 'aviso-cam';
    aviso.style.cssText = 'position:absolute;left:8%;right:8%;top:34%;text-align:center;padding:0 6px;' +
      'color:#ffb4b4;font-size:12px;line-height:1.3;pointer-events:none;text-shadow:0 1px 2px #000;' +
      'max-height:3.9em;overflow:hidden';
    jan.appendChild(aviso);
    pintarAviso(c, jan);
    jan.appendChild(marca); jan.appendChild(caixas); jan.appendChild(rot);
    grade.appendChild(jan);
    window.Video.ligar(c.id, c.id, v);
    desenharCaixas(c.id);
  }
  montarPaginacao();
  pintarEstados();
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
  relatorios: ['Relatórios', 'Indicadores medidos pelo sistema: disponibilidade, contagens e qualidade do link.'],
  pessoas: ['Pessoas', 'Cadastro usado pelas análises de vídeo — só liga com a autorização registrada.'],
  cameras: ['Câmeras', 'Câmeras liberadas para a sua empresa e o estado de cada uma.'],
  avisos: ['Avisos', 'Preferências de notificação deste usuário.']
};

function desenharTela() {
  const [titulo, sub] = TELAS[S.tela] || TELAS.visualizar;
  $('titulo-tela').textContent = titulo; $('sub-tela').textContent = sub;
  $('controles').classList.toggle('oculto', S.tela !== 'visualizar');
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
    tabelaEmPalco([{ rotulo: 'Trecho', campo: 'inicio' }, { rotulo: 'Câmera', campo: 'camera_id' }], [],
      'Gravação ainda não habilitada nesta embarcação (Fase 3, P1 do plano).');
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
  }
}

/* ---------------------------------------------------------------- rodape e utilidades */
function atualizarRodape() {
  const total = S.cameras.length, sel = S.selecionadas.size;
  const inicio = total ? 1 : 0;
  const fim = Math.min(porPagina() * porPagina() * (S.pagina - 1) + porPagina() * porPagina(), sel);
  $('contagem-selecao').textContent = `Mostrando ${inicio}-${fim} de ${sel} câmeras selecionadas (total ${total})`;
}
function relogios() {
  const d = new Date();
  const sela = `${d.getFullYear()}-${dois(d.getMonth() + 1)}-${dois(d.getDate())} ${dois(d.getHours())}:${dois(d.getMinutes())}:${dois(d.getSeconds())}`;
  document.querySelectorAll('[data-relogio]').forEach((e) => { e.textContent = sela; });
}

function trocarTela(tela) {
  S.tela = tela; S.pagina = 1;
  document.querySelectorAll('.item[data-tela]').forEach((b) => b.classList.toggle('on', b.dataset.tela === tela));
  if (tela === 'visualizar') { desenharVisualizar(); }
  else if (S.eventos.length === 0) dadosExtras().then(desenharTela);
  else desenharTela();
  desenharTela();
  atualizarRodape();
}

/* ---------------------------------------------------------------- eventos de interface */
$('form-entrar').addEventListener('submit', entrar);
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
$('btn-cheia').addEventListener('click', () => {
  const alvo = $('palco');
  if (document.fullscreenElement) document.exitFullscreen(); else if (alvo.requestFullscreen) alvo.requestFullscreen();
});
$('btn-sair').addEventListener('click', async () => { await api('/api/sair', { method: 'POST' }); location.reload(); });
$('embarcacao').addEventListener('change', (ev) => {
  S.embarcacaoId = ev.target.value; S.cameras = []; S.selecionadas = new Set(); S.pagina = 1;
  atualizar();
});
$('limpar').addEventListener('click', () => { S.selecionadas = new Set(); S.pagina = 1; desenharVisualizar(); atualizarRodape(); });
$('todos-alertas').addEventListener('click', () => trocarTela('alertas'));
$('ir-relatorios').addEventListener('click', () => trocarTela('relatorios'));
setInterval(relogios, 1000); setInterval(() => { if (S.tela === 'visualizar') pintarEstados(); }, 2000);
abrir();
