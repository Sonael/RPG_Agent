// ═══════════════════════════════════════════════════════════════════
//  diario.js — O diário como livro ("O Diário")
//
//  Uma página por capítulo: as entradas do diário daquele capítulo, lidas
//  como texto, e o que se liga a elas — os eventos registrados no capítulo,
//  os personagens e locais citados e as missões que começaram ou terminaram
//  ali. No índice, os capítulos em ordem, o atual marcado.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra aqui. O que entra
//  em cada capítulo vem do motor (rpg/diario.py via /api/diary/book). A
//  escrita continua no editor de sempre ("Editar", "Nova entrada"); a única
//  ação própria do livro é pôr um evento antigo, gravado sem capítulo, no
//  capítulo certo.
//
//  Não abre sozinha; aberta, a fila de telas a redesenha.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _last = {};
  let _pagina = null;        // número do capítulo, ou 'sem' para eventos sem capítulo
  let _destaque = null;      // índice da entrada a destacar

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");

  function ensureDom() {
    if (q('diario-overlay')) return;
    const o = document.createElement('div');
    o.id = 'diario-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="dia-frame" role="dialog" aria-modal="true" aria-labelledby="dia-titulo">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Diario._fechar()" aria-label="Fechar" title="Fechar">✕</button>
          <div id="dia-campanha" class="lcl-caminho"></div>
          <h1 class="lcl-title" id="dia-titulo">O Diário</h1>
        </header>

        <div class="dia-corpo">
          <nav id="dia-indice" class="dia-indice" aria-label="Capítulos"></nav>
          <article id="dia-pagina" class="dia-pagina" aria-live="polite"></article>
        </div>

        <div class="lcl-rodape">
          <div id="dia-msg" class="lcl-msg" aria-live="polite"></div>
          <button id="dia-anterior" class="lcl-btn lcl-btn-sec" onclick="window.Diario._virar(-1)">Capítulo anterior</button>
          <button id="dia-proximo" class="lcl-btn lcl-btn-sec" onclick="window.Diario._virar(1)">Próximo capítulo</button>
          <button id="dia-nova" class="lcl-btn lcl-btn-sec" onclick="window.Diario._nova()">Nova entrada</button>
          <button class="lcl-fechar" onclick="window.Diario._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  const api = (window.authFetch || fetch);
  async function getState() {
    const r = await api(`${window.API || ''}/api/diary/book`);
    return r.json();
  }

  // ---- Render ------------------------------------------------------
  const capitulos = () => _last.capitulos || [];
  const capitulo = (n) => capitulos().find(c => c.numero === n);

  function paragrafos(texto) {
    return String(texto || '').split(/\n\s*\n|\n/).map(t => t.trim()).filter(Boolean)
      .map(t => `<p>${esc(t)}</p>`).join('');
  }

  function indice() {
    const itens = capitulos().map(c => `
      <button class="dia-cap-item${c.numero === _pagina ? ' dia-cap-aberto' : ''}" data-numero="${c.numero}"
              onclick="window.Diario._ir(${c.numero})">
        <span class="dia-cap-numero">Capítulo ${c.numero}${c.atual ? ' <span class="lcl-marca lcl-marca-grupo">atual</span>' : ''}</span>
        ${c.titulo ? `<span class="dia-cap-titulo">${esc(c.titulo)}</span>` : ''}
        <span class="dia-cap-contagem">${c.entradas.length} ${c.entradas.length === 1 ? 'entrada' : 'entradas'}${
          c.eventos.length ? ` · ${c.eventos.length} ${c.eventos.length === 1 ? 'evento' : 'eventos'}` : ''}</span>
      </button>`).join('');
    const sem = (_last.eventos_sem_capitulo || []).length;
    return itens + (sem ? `
      <button class="dia-cap-item dia-cap-sem${_pagina === 'sem' ? ' dia-cap-aberto' : ''}" data-numero="sem"
              onclick="window.Diario._ir('sem')">
        <span class="dia-cap-numero">Sem capítulo</span>
        <span class="dia-cap-contagem">${sem} ${sem === 1 ? 'evento' : 'eventos'} de antes do registro de capítulos</span>
      </button>` : '');
  }

  function pessoa(p) {
    return p.tem_ficha === false
      ? `<span class="dia-pessoa dia-pessoa-sem" title="Sem ficha na campanha">${esc(p.nome)}</span>`
      : `<button class="dia-pessoa" onclick="window.Diario._verPessoa('${aspas(p.nome)}')"
                 title="Ver a ficha de ${esc(p.nome)}">${esc(p.nome)}</button>`;
  }

  function evento(e, mover) {
    const opcoes = mover ? capitulos().map(c =>
      `<option value="${c.numero}" ${c.atual ? 'selected' : ''}>Capítulo ${c.numero}</option>`).join('') : '';
    return `
      <li class="dia-evento" data-index="${e.index}">
        <p class="dia-evento-resumo">${esc(e.resumo)}</p>
        ${e.local ? `<p class="dia-evento-local">em <button class="dia-link" onclick="window.Diario._verLocal('${aspas(e.local)}')">${esc(e.local)}</button></p>` : ''}
        ${e.consequencia ? `<p class="dia-evento-consequencia">${esc(e.consequencia)}</p>` : ''}
        ${e.personagens.length ? `<div class="dia-pessoas">${e.personagens.map(pessoa).join('')}</div>` : ''}
        ${mover ? `<div class="dia-mover">
            <select id="dia-mover-${e.index}" aria-label="Capítulo do evento">${opcoes}</select>
            <button class="lcl-btn lcl-btn-sec" onclick="window.Diario._mover(${e.index})">Pôr no capítulo</button>
          </div>` : ''}
      </li>`;
  }

  function paginaDoCapitulo(c) {
    const entradas = c.entradas.length
      ? c.entradas.map(x => `
          <section class="dia-entrada${x.indice === _destaque ? ' dia-destaque' : ''}" data-indice="${x.indice}">
            <header class="dia-entrada-cabeca">
              <h3>${esc(x.titulo || 'Sem título')}</h3>
              <button class="dia-editar" onclick="window.Diario._editar(${x.indice})" title="Abrir no editor">Editar</button>
            </header>
            <div class="dia-texto">${paragrafos(x.conteudo) || '<p class="lcl-vazio">Entrada sem texto.</p>'}</div>
          </section>`).join('')
      : `<p class="lcl-vazio">Nada escrito neste capítulo ainda.</p>`;

    const missoes = c.missoes.map(m => `
      <li><button class="dia-link" onclick="window.Diario._verMissao('${aspas(m.titulo)}')">${esc(m.titulo)}</button>
        <span class="lcl-marca">${esc(m.marco)}</span></li>`).join('');

    const ligacoes = [
      c.eventos.length ? `<h4 class="lcl-secao">Eventos</h4><ol class="dia-eventos">${c.eventos.map(e => evento(e)).join('')}</ol>` : '',
      c.personagens.length ? `<h4 class="lcl-secao">Personagens</h4><div class="dia-pessoas">${c.personagens.map(pessoa).join('')}</div>` : '',
      c.locais.length ? `<h4 class="lcl-secao">Locais</h4><div class="dia-locais">${c.locais.map(l =>
        `<button class="dia-link" onclick="window.Diario._verLocal('${aspas(l)}')">${esc(l)}</button>`).join('')}</div>` : '',
      missoes ? `<h4 class="lcl-secao">Missões</h4><ul class="dia-missoes">${missoes}</ul>` : '',
    ].join('');

    return `
      <header class="dia-pagina-cabeca">
        <p class="dia-pagina-numero">${c.atual ? 'o capítulo atual' : `${c.entradas.length} ${c.entradas.length === 1 ? 'entrada' : 'entradas'}`}</p>
        <h2 class="dia-pagina-titulo">Capítulo ${c.numero}</h2>
      </header>
      <div class="dia-entradas">${entradas}</div>
      ${ligacoes ? `<aside class="dia-ligacoes" aria-label="Neste capítulo"><h3 class="dia-ligacoes-titulo">Neste capítulo</h3>${ligacoes}</aside>` : ''}`;
  }

  function paginaSemCapitulo() {
    const evs = _last.eventos_sem_capitulo || [];
    return `
      <header class="dia-pagina-cabeca">
        <p class="dia-pagina-numero">Sem capítulo</p>
        <h2 class="dia-pagina-titulo">Eventos de antes do registro de capítulos</h2>
      </header>
      <p class="lcl-desc">Estes eventos foram gravados antes de o jogo guardar o capítulo de cada um.
        Escolha onde cada um aconteceu para ele aparecer na página do capítulo.</p>
      ${evs.length ? `<ol class="dia-eventos">${evs.map(e => evento(e, true)).join('')}</ol>`
        : '<p class="lcl-vazio">Nenhum evento sem capítulo.</p>'}`;
  }

  function render(d) {
    _last = d || {};
    ensureDom();
    const nums = capitulos().map(c => c.numero);
    if (_pagina !== 'sem' && !nums.includes(_pagina)) _pagina = _last.capitulo_atual;
    if (_pagina === 'sem' && !(_last.eventos_sem_capitulo || []).length) _pagina = _last.capitulo_atual;

    q('dia-campanha').textContent = _last.campanha || '';
    q('dia-indice').innerHTML = indice();
    mostrarNoIndice();
    const c = _pagina === 'sem' ? null : capitulo(_pagina);
    q('dia-pagina').innerHTML = c ? paginaDoCapitulo(c) : paginaSemCapitulo();

    const i = nums.indexOf(_pagina);
    q('dia-anterior').disabled = _pagina === 'sem' ? !nums.length : i <= 0;
    q('dia-proximo').disabled = _pagina === 'sem' || i < 0 || i >= nums.length - 1;
    q('dia-nova').classList.toggle('hidden', _pagina === 'sem');

    if (_destaque != null) {
      const el = q('dia-pagina').querySelector(`.dia-entrada[data-indice="${_destaque}"]`);
      if (el) try { el.scrollIntoView({ block: 'start' }); } catch (_) { /* sem rolagem */ }
    } else {
      q('dia-pagina').scrollTop = 0;
    }
  }

  // Rola o índice até o capítulo aberto. No celular o índice é uma faixa
  // horizontal, e a página "Sem capítulo" (a última) abria com o próprio botão
  // fora da tela, sem nada indicando que a faixa rola; no desktop, com muitos
  // capítulos, o mesmo acontecia na coluna. Só o índice rola, nunca a página.
  function mostrarNoIndice() {
    const nav = q('dia-indice');
    const ativo = nav && nav.querySelector('.dia-cap-aberto');
    if (!ativo) return;
    const n = nav.getBoundingClientRect();
    const a = ativo.getBoundingClientRect();
    if (nav.scrollWidth > nav.clientWidth) {
      if (a.left < n.left) nav.scrollLeft -= n.left - a.left + 8;
      else if (a.right > n.right) nav.scrollLeft += a.right - n.right + 8;
    }
    if (nav.scrollHeight > nav.clientHeight) {
      if (a.top < n.top) nav.scrollTop -= n.top - a.top + 8;
      else if (a.bottom > n.bottom) nav.scrollTop += a.bottom - n.bottom + 8;
    }
  }

  function mensagem(txt, erro) {
    const el = q('dia-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  // ---- Abrir / fechar ----------------------------------------------
  async function abrir(numero, indiceEntrada) {
    ensureDom();
    _pagina = numero == null || numero === '' ? null : (numero === 'sem' ? 'sem' : parseInt(numero, 10));
    _destaque = indiceEntrada == null ? null : parseInt(indiceEntrada, 10);
    if (!_open) {
      q('diario-overlay').classList.remove('hidden');
      document.body.classList.add('diario-on');
      _open = true;
    }
    mensagem('Carregando…');
    try {
      render(await getState());
      mensagem('');
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  function fechar() {
    const el = q('diario-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('diario-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  // Aberta, mostra a entrada ou o evento que o mestre acabou de registrar.
  async function sync() {
    if (!_open) return;
    try { render(await getState()); } catch (_) { /* nunca derruba o turno */ }
  }

  function ir(numero) {
    _pagina = numero === 'sem' ? 'sem' : parseInt(numero, 10);
    _destaque = null;
    render(_last);
  }

  function virar(passo) {
    const nums = capitulos().map(c => c.numero);
    if (_pagina === 'sem') { if (nums.length) ir(nums[nums.length - 1]); return; }
    const i = nums.indexOf(_pagina) + passo;
    if (i >= 0 && i < nums.length) ir(nums[i]);
  }

  // A escrita continua no editor de sempre.
  function editar(indiceEntrada) {
    const entrada = ((window._lastMem || {}).diary || [])[indiceEntrada];
    if (!entrada || typeof window.openEditModal !== 'function') return;
    fechar();
    window.openEditModal('diary', null, entrada, indiceEntrada);
  }

  function nova() {
    if (typeof window.openEditModal !== 'function') return;
    const numero = _pagina === 'sem' ? _last.capitulo_atual : _pagina;
    fechar();
    window.openEditModal('diary', null, { chapter: numero, title: '', content: '' }, -1);
  }

  async function mover(index) {
    const sel = q(`dia-mover-${index}`);
    if (!sel) return;
    mensagem('');
    try {
      const r = await api(`${window.API || ''}/api/diary/move-event`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index, chapter: parseInt(sel.value, 10) }),
      });
      const d = await r.json();
      if (d.book) render(d.book);
      mensagem(d.message || '', !d.ok);
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  window.Diario = {
    sync,
    _abrir: abrir,
    _fechar: fechar,
    _ir: ir,
    _virar: virar,
    _editar: editar,
    _nova: nova,
    _mover: mover,
    _verPessoa: (nome) => { fechar(); if (window.Personagens) window.Personagens._abrir(nome); },
    _verLocal: (nome) => { fechar(); if (window.Locais) window.Locais._abrir(nome); },
    _verMissao: (titulo) => { fechar(); if (window.Missoes) window.Missoes._abrir(titulo); },
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
