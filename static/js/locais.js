// ═══════════════════════════════════════════════════════════════════
//  locais.js — Ficha do local
//
//  Abre ao clicar num local da Enciclopédia ou no "Local:" da barra lateral.
//  Mostra o caminho até o lugar (Cliviate › Forja de Cliviate), o que fica
//  dentro dele, quem está lá e, com um clique, manda ao mestre "Vamos até
//  a Forja de Cliviate." ou "Quero falar com Brom." como fala do jogador.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo aqui. O
//  que fica dentro de quê, quem está onde e o que está ao alcance de um
//  passo vêm do motor (rpg/locais.py via /api/locations/state). A tela não
//  move o grupo: quem narra a ida e muda o local atual é o mestre.
//
//  Como a Mochila, não abre sozinha e não entra na fila de telas.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _last = {};

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");

  const ROTULO_ALCANCE = {
    aqui: 'O grupo está aqui',
    dentro: 'Fica dentro do local do grupo',
    acima: 'É onde o local do grupo fica',
    vizinho: 'Ao lado do local do grupo',
  };

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (q('local-overlay')) return;
    const o = document.createElement('div');
    o.id = 'local-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="lcl-frame" role="dialog" aria-modal="true" aria-labelledby="lcl-nome">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Locais._fechar()"
                  aria-label="Fechar" title="Fechar">✕</button>
          <nav id="lcl-caminho" class="lcl-caminho" aria-label="Onde fica"></nav>
          <h1 class="lcl-title"><span id="lcl-nome">—</span> <span id="lcl-tipo" class="lcl-tipo"></span></h1>
          <div id="lcl-selo" class="lcl-selo"></div>
          <p id="lcl-desc" class="lcl-desc"></p>
        </header>

        <div class="lcl-corpo">
          <section class="lcl-corpo-pessoas" aria-label="Quem está aqui">
            <h2 class="lcl-secao">Quem está aqui</h2>
            <div id="lcl-grupo" class="lcl-grupo"></div>
            <div id="lcl-pessoas" class="lcl-lista"></div>
          </section>
          <section class="lcl-corpo-dentro" aria-label="Aqui dentro">
            <h2 class="lcl-secao">Aqui dentro</h2>
            <div id="lcl-dentro" class="lcl-lista"></div>
          </section>
        </div>

        <div class="lcl-rodape">
          <div id="lcl-msg" class="lcl-msg" aria-live="polite"></div>
          <button id="lcl-onde" class="lcl-btn lcl-btn-sec hidden"
                  onclick="window.Locais._abrir('')">Onde o grupo está</button>
          <button id="lcl-editar" class="lcl-btn lcl-btn-sec hidden"
                  onclick="window.Locais._editar()">Editar local</button>
          <button class="lcl-fechar" onclick="window.Locais._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  // ---- Rede --------------------------------------------------------
  async function getState(nome) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}/api/locations/state?local=${encodeURIComponent(nome || '')}`);
    return r.json();
  }

  // ---- Render ------------------------------------------------------
  function caminho(f) {
    const trilha = f.caminho || [];
    if (trilha.length < 2) return '';
    return trilha.slice(0, -1).map(n =>
      `<a href="#" class="lcl-migalha" onclick="event.preventDefault();window.Locais._abrir('${aspas(n)}')">${esc(n)}</a>`
    ).join('<span class="lcl-sep">›</span>') + '<span class="lcl-sep">›</span>';
  }

  function botaoIr(nome, alcance, rotulo) {
    if (!alcance || alcance === 'aqui') return '';
    return `<button class="lcl-btn lcl-btn-ir" onclick="window.Locais._ir('${aspas(nome)}')"
                    title="Manda ao mestre: Vamos até ${esc(nome)}.">${rotulo || 'Ir até lá'}</button>`;
  }

  function pessoa(p) {
    const status = (p.status || '').toLowerCase();
    const marca = status && status !== 'vivo'
      ? `<span class="lcl-marca">${esc(p.status)}</span>` : '';
    const falar = p.pode_falar
      ? `<button class="lcl-btn lcl-btn-ir" onclick="window.Locais._falar('${aspas(p.nome)}')"
                 title="Manda ao mestre: Quero falar com ${esc(p.nome)}.">Falar com</button>`
      : `<button class="lcl-btn" disabled
                 title="${status === 'morto' ? 'Não está mais entre os vivos' : 'Longe do grupo: vá até lá primeiro'}">Falar com</button>`;
    return `
      <div class="lcl-item" data-nome="${esc(p.nome)}">
        <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(p.nome)}</span>${marca}</div>
        ${p.descricao ? `<p class="lcl-item-desc">${esc(p.descricao)}</p>` : ''}
        <div class="lcl-item-acoes">${falar}</div>
      </div>`;
  }

  function lugarDentro(d) {
    const marcas = [
      d.alcance === 'aqui' ? '<span class="lcl-marca lcl-marca-grupo">grupo aqui</span>' : '',
      d.tipo === 'loja' ? '<span class="lcl-marca lcl-marca-loja">loja</span>' : '',
      d.pessoas ? `<span class="lcl-marca">${d.pessoas} ${d.pessoas === 1 ? 'pessoa' : 'pessoas'}</span>` : '',
    ].join('');
    return `
      <div class="lcl-item" data-nome="${esc(d.nome)}">
        <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(d.nome)}</span>${marcas}</div>
        ${d.descricao ? `<p class="lcl-item-desc">${esc(d.descricao.length > 180 ? d.descricao.slice(0, 180) + '…' : d.descricao)}</p>` : ''}
        <div class="lcl-item-acoes">
          <button class="lcl-btn lcl-btn-sec" onclick="window.Locais._abrir('${aspas(d.nome)}')">Ver</button>
          ${botaoIr(d.nome, d.alcance)}
        </div>
      </div>`;
  }

  function render(f) {
    _last = f || {};
    ensureDom();
    q('lcl-caminho').innerHTML = caminho(_last);
    q('lcl-nome').textContent = _last.nome || 'Local desconhecido';
    q('lcl-tipo').textContent = _last.tipo === 'loja' ? '— loja' : '';

    const selo = ROTULO_ALCANCE[_last.alcance] || (_last.nome ? 'Longe do grupo' : '');
    const pai = _last.pai;
    q('lcl-selo').innerHTML =
      (selo ? `<span class="lcl-selo-texto lcl-alcance-${esc(_last.alcance || 'longe')}">${esc(selo)}</span>` : '')
      + (!_last.e_o_local_atual && _last.alcance ? botaoIr(_last.nome, _last.alcance) : '')
      + (_last.e_o_local_atual && pai && pai.alcance === 'acima'
          ? botaoIr(pai.nome, pai.alcance, `Sair para ${esc(pai.nome)}`) : '');

    const desc = _last.descricao || (_last.tipo === 'loja' && pai ? `Loja em ${pai.nome}.` : '');
    q('lcl-desc').textContent = desc || (_last.existe ? '' : 'Este lugar ainda não foi registrado pelo mestre.');

    const grupo = _last.grupo_aqui || [];
    q('lcl-grupo').innerHTML = grupo.length
      ? `<span class="lcl-grupo-rotulo">Grupo</span>${grupo.map(n => `<span class="lcl-grupo-nome">${esc(n)}</span>`).join('')}`
      : '';
    const pessoas = _last.pessoas || [];
    q('lcl-pessoas').innerHTML = pessoas.length
      ? pessoas.map(pessoa).join('')
      : `<div class="lcl-vazio">${grupo.length ? 'Mais ninguém registrado aqui.' : 'Ninguém registrado aqui.'}</div>`;

    const dentro = _last.dentro || [];
    q('lcl-dentro').innerHTML = dentro.length
      ? dentro.map(lugarDentro).join('')
      : '<div class="lcl-vazio">Nenhum lugar registrado aqui dentro.</div>';

    q('lcl-onde').classList.toggle('hidden', !!_last.e_o_local_atual || !_last.local_atual);
    q('lcl-editar').classList.toggle('hidden', !(_last.existe && _last.tipo === 'local'));
    mensagem('');
  }

  function mensagem(txt, erro) {
    const el = q('lcl-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  // ---- Abrir / fechar ----------------------------------------------
  async function abrir(nome) {
    ensureDom();
    if (!_open) {
      q('local-overlay').classList.remove('hidden');
      document.body.classList.add('local-on');
      _open = true;
    }
    mensagem('Carregando…');
    try {
      render(await getState(nome));
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  function fechar() {
    const el = q('local-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('local-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  // A fala vai ao mestre como se o jogador a tivesse digitado: é intenção
  // dele, e aparece no chat como tal. Quem decide o que acontece é o mestre.
  function enviar(texto) {
    // `waiting` é do game.js: um let no escopo global dos scripts da página.
    if (typeof waiting !== 'undefined' && waiting) {
      mensagem('Aguarde o mestre terminar de responder.', true);
      return;
    }
    if (typeof window.sendToAgent !== 'function' || typeof window.appendUser !== 'function') return;
    fechar();
    window.appendUser(texto);
    window.sendToAgent(texto, true);
  }

  function editar() {
    const f = _last || {};
    const mem = window._lastMem || {};
    const i = (mem.locations || []).findIndex(l => (l.name || '').toLowerCase() === (f.nome || '').toLowerCase());
    if (i < 0 || typeof window.openEditModal !== 'function') return;
    fechar();
    window.openEditModal('location', mem.locations[i].name.toLowerCase(), mem.locations[i]);
  }

  window.Locais = {
    _abrir: abrir,
    _fechar: fechar,
    _ir: (nome) => enviar(`Vamos até ${nome}.`),
    _falar: (nome) => enviar(`Quero falar com ${nome}.`),
    _editar: editar,
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
