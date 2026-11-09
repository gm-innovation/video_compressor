/* Player resiliente compartilhado pelos dois fronts.
   Fala SOMENTE com a API do produto (/whep/<fluxo> e /hls/<fluxo>/...):
   o navegador nunca recebe endereco interno nem credencial de camera. */
window.Video = (function () {
  const ligados = new Map();

  function marcar(id, texto, classe) {
    const el = document.getElementById('estado-' + id);
    if (!el) return;
    el.textContent = texto;
    el.className = 'pill ' + classe;
  }

  async function ligar(id, fluxo, video) {
    const est = ligados.get(id) || { tentativa: 0 };
    if (est.pc) { try { est.pc.close(); } catch (e) {} }
    if (est.hls) { try { est.hls.destroy(); } catch (e) {} est.hls = null; }
    ligados.set(id, est);
    const pc = new RTCPeerConnection({ iceServers: [] });
    est.pc = pc;
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.ontrack = (ev) => {
      video.srcObject = ev.streams[0] || new MediaStream([ev.track]);
      video.classList.remove('reconectando');
      video.play().catch(() => {});
      marcar(id, 'no ar (WebRTC)', 'no-ar');
    };
    pc.onconnectionstatechange = () => {
      if (['failed', 'disconnected', 'closed'].includes(pc.connectionState)) reagendar(id, fluxo, video);
      else if (pc.connectionState === 'connected') marcar(id, 'no ar (WebRTC)', 'no-ar');
      else if (pc.connectionState === 'connecting') marcar(id, 'conectando…', 'rec');
    };
    try {
      const oferta = await pc.createOffer();
      await pc.setLocalDescription(oferta);
      const r = await fetch('/whep/' + encodeURIComponent(fluxo), {
        method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: oferta.sdp
      });
      if (!r.ok) throw new Error('whep ' + r.status);
      await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() });
      est.tentativa = 0;
      est.travadas = 0;
      if (est.hls) { try { est.hls.destroy(); } catch (e) {} est.hls = null; }
    } catch (e) {
      reserva(id, fluxo, video);
    }
    vigiar(id, fluxo, video);
  }

  /* Vigia o relogio do proprio video: sessao WebRTC pode ficar "conectada" sem receber quadro
     nenhum (o publicador caiu e a ultima imagem congela). Sem isso a tela mente para o cliente. */
  function vigiar(id, fluxo, video) {
    const est = ligados.get(id) || {}; ligados.set(id, est);
    est.video = video;
    est.ultimo = video.currentTime;
    est.paradoDesde = Date.now();
    if (est.vigia) return;
    est.vigia = setInterval(() => {
      const v = est.video;
      if (!v || document.visibilityState !== 'visible') { est.paradoDesde = Date.now(); return; }
      if (!v.srcObject && !est.hls) { est.paradoDesde = Date.now(); return; }
      if (v.currentTime > est.ultimo + 0.05) { est.ultimo = v.currentTime; est.paradoDesde = Date.now(); est.travadas = 0; return; }
      if (Date.now() - est.paradoDesde < 4000) return;
      est.paradoDesde = Date.now();
      est.travadas = (est.travadas || 0) + 1;
      if (est.travadas >= 2) reserva(id, fluxo, video); else reagendar(id, fluxo, video);
    }, 1500);
  }

  function reserva(id, fluxo, video) {
    const est = ligados.get(id) || {}; ligados.set(id, est);
    if (window.Hls && window.Hls.isSupported()) {
      marcar(id, 'reserva (HLS)', 'rec');
      if (est.pc) { try { est.pc.close(); } catch (e) {} est.pc = null; }
      if (est.hls) { try { est.hls.destroy(); } catch (e) {} }
      video.classList.remove('reconectando');
      est.hls = new window.Hls({ lowLatencyMode: true });
      est.hls.loadSource('/hls/' + encodeURIComponent(fluxo) + '/index.m3u8');
      est.hls.attachMedia(video);
      ligados.set(id, est);
    } else {
      reagendar(id, fluxo, video);
    }
  }

  function reagendar(id, fluxo, video) {
    const est = ligados.get(id) || { tentativa: 0 };
    if (est.timer) return;
    est.tentativa = (est.tentativa || 0) + 1;
    est.fluxo = fluxo;
    video.classList.add('reconectando');
    marcar(id, 'reconectando…', 'rec');
    est.timer = setTimeout(() => {
      est.timer = null;
      ligados.set(id, est);
      ligar(id, fluxo, video);
    }, Math.min(1000 * est.tentativa, 8000));
    ligados.set(id, est);
  }

  function parar(id) {
    const est = ligados.get(id);
    if (!est) return;
    if (est.timer) clearTimeout(est.timer);
    if (est.vigia) clearInterval(est.vigia);
    if (est.pc) { try { est.pc.close(); } catch (e) {} }
    if (est.hls) { try { est.hls.destroy(); } catch (e) {} }
    ligados.delete(id);
  }

  return { ligar, reagendar, parar, marcar };
})();
