/* Entrada unica do produto: um aplicativo so', e a TELA que abre e' a do PAPEL do usuario.
 *
 *   cliente                  -> /app    (acompanhamento das cameras)
 *   operador | admin         -> /admin  (console da operacao)
 *   tecnico  | captura       -> /       ("Enviar video" — a bancada de captura)
 *
 * O papel vem do SERVIDOR (`/api/eu` ou a resposta do `/api/entrar`); a interface nao decide
 * permissao, so' para onde ir. Quem autoriza a entrar e' o cadastro da instalacao: conta que nao
 * esta cadastrada aqui toma 403 e a mensagem diz que quem cadastra usuarios e' o administrador.
 */
const TELAS = { cliente: '/app', operador: '/admin', admin: '/admin', tecnico: '/', captura: '/' };

function telaDoPapel(papel) {
  return TELAS[String(papel || '').trim().toLowerCase()] || '/app';
}

const $ = (id) => document.getElementById(id);

async function api(caminho, o) {
  const r = await fetch(caminho, Object.assign({ headers: { 'Content-Type': 'application/json' } }, o || {}));
  const texto = await r.text();
  let corpo = null;
  try { corpo = texto ? JSON.parse(texto) : null; } catch (e) { corpo = null; }
  return { ok: r.ok, status: r.status, corpo };
}

function aviso(alvo, texto) {
  const e = $(alvo);
  if (!texto) { e.classList.add('oculto'); e.textContent = ''; return; }
  e.textContent = texto;
  e.classList.remove('oculto');
}

/// Vai para a tela do papel. `replace` (e nao `href`) para o botao "voltar" nao cair de novo na entrada.
function irParaTela(papel) { window.location.replace(telaDoPapel(papel)); }

async function entrar(ev) {
  ev.preventDefault();
  aviso('entrada-erro', '');
  const d = await api('/api/entrar', { method: 'POST',
    body: JSON.stringify({ email: $('email').value.trim(), senha: $('senha').value }) });
  if (!d.ok) {
    const c = d.corpo || {};
    aviso('entrada-erro', c.erro || 'não foi possível entrar');
    // Instalacao sem usuario nenhum (o proprio servidor respondeu assim): em vez de deixar a pessoa
    // repetindo a senha, abrir o cadastro do primeiro administrador desta maquina — o que falta nao e'
    // a senha (caso de 18/11/2026, com a base apontada para o banco local vazio).
    if (c.primeiro_acesso) {
      $('#entrada').classList.add('oculto');
      $('#primeiro').classList.remove('oculto');
      aviso('primeiro-erro', 'esta instalação ainda não tem usuário nenhum — crie o primeiro administrador desta máquina');
      $('#p-nome').focus();
    }
    return;
  }
  irParaTela(d.corpo && d.corpo.papel);
}

async function primeiroAcesso(ev) {
  ev.preventDefault();
  aviso('primeiro-erro', '');
  if ($('p-senha').value !== $('p-senha2').value) return aviso('primeiro-erro', 'as duas senhas não são iguais');
  const d = await api('/api/primeiro-acesso', { method: 'POST', body: JSON.stringify({
    nome: $('p-nome').value, email: $('p-email').value.trim(), senha: $('p-senha').value }) });
  if (!d.ok) return aviso('primeiro-erro', (d.corpo && d.corpo.erro) || 'não foi possível criar o primeiro acesso');
  irParaTela(d.corpo && d.corpo.papel);
}

(async () => {
  $('form-entrar').addEventListener('submit', entrar);
  $('form-primeiro').addEventListener('submit', primeiroAcesso);
  // Ja' logado nesta maquina (o app reabre onde o usuario parou): vai direto para a tela do papel.
  const eu = await api('/api/eu');
  if (eu.ok && eu.corpo && eu.corpo.autenticado) return irParaTela(eu.corpo.papel);
  // Instalacao nova: a API diz se ha' usuario e se quem abriu e' a propria maquina.
  const pa = await api('/api/primeiro-acesso');
  if (!(pa.ok && pa.corpo && pa.corpo.precisa)) return;
  $('#entrada').classList.add('oculto');
  $('#primeiro').classList.remove('oculto');
  if (pa.corpo.local === false) {
    aviso('primeiro-erro', 'esta lista só pode ser criada na própria máquina do servidor (' + (pa.corpo.maquina || 'servidor') + ')');
  }
  $('#p-nome').focus();
})();
