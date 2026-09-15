// ═══════════════════════════════════════════════════════════════════
//  elenco.js — Índice de personagens ("Personagens")
//
//  Todos os personagens da campanha numa lista com busca e filtros (aqui,
//  grupo, conhecidos, inimigos, mortos). Clicar abre a ficha que já existe:
//  a do herói para quem é do grupo e tem ficha, a do personagem para os
//  demais. Substitui a Enciclopédia da barra lateral.
//
//  REGRA DE OURO, a mesma das outras telas: a categoria de cada um, quem
//  está aqui com o grupo e a contagem vêm do motor (rpg/personagens.py,
//  indice, via /api/characters/index). A busca e o filtro só escondem linhas.
//
//  Não abre sozinha; aberta, a fila de telas a redesenha.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _last = {};
  let _filtro = 'todos';
  let _busca = '';

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");
  const norm = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

  const FILTROS = [
    ['todos', 'Todos'], ['aqui', 'Aqui'], ['grupo', 'Grupo'],
    ['conhecidos', 'Conhecidos'], ['inimigos', 'Inimigos'], ['mortos', 'Mortos'],
  ];
  const CATEGORIA_DO_FILTRO = { grupo: 'grupo', conhecidos: 'conhecido', inimigos: 'inimigo', mortos: 'morto' };

  function ensureDom() {
    if (q('elenco-overlay')) return;
    const o = document.createElement('div');
    o.id = 'elenco-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="elc-frame" role="dialog" aria-modal="true" aria-labelledby="elc-titulo">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Elenco._fechar()" aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="lcl-title" id="elc-titulo">Personagens</h1>
          <input id="elc-busca" class="map-busca" type="search" autocomplete="off"
                 placeholder="Buscar pelo nome, pelo lugar ou pela descrição"
                 aria-label="Buscar personagem" oninput="window.Elenco._buscar(this.value)">
          <div id="elc-filtros" class="elc-filtros" role="tablist" aria-label="Filtros"></div>
        </header>
        <div class="elc-corpo">
          <div id="elc-lista" class="elc-lista"></div>
        </div>
        <div class="lcl-rodape">
          <div id="elc-msg" class="lcl-msg" aria-live="polite"></div>
          <button class="lcl-btn lcl-btn-sec" onclick="window.Elenco._novo('membro')">Novo membro do grupo</button>
          <button class="lcl-btn lcl-btn-sec" onclick="window.Elenco._novo('personagem')">Novo personagem</button>
          <button class="lcl-fechar" onclick="window.Elenco._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  async function getState() {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}/api/characters/index`);
    return r.json();
  }

  // ---- Render ------------------------------------------------------
  function passaNoFiltro(p) {
    if (_filtro === 'aqui') return p.aqui;
    if (CATEGORIA_DO_FILTRO[_filtro]) return p.categoria === CATEGORIA_DO_FILTRO[_filtro];
    return true;
  }

  function casaNaBusca(p) {
    if (!_busca) return true;
    return [p.nome, p.local, p.descricao, p.status].some(t => norm(t).includes(_busca));
  }

  function cartao(p) {
    const status = norm(p.status);
    const marcas = [
      p.do_grupo ? '<span class="lcl-marca lcl-marca-grupo">grupo</span>' : '',
      p.aqui && !p.do_grupo ? '<span class="lcl-marca map-marca-alcance">aqui</span>' : '',
      status && status !== 'vivo' ? `<span class="lcl-marca${p.categoria === 'morto' ? ' elc-marca-morto' : ''}">${esc(p.status)}</span>` : '',
      p.atitude ? `<span class="lcl-marca" title="Relação com o grupo">${esc(p.atitude)}</span>` : '',
    ].join('');
    return `
      <button class="lcl-item elc-cartao elc-${esc(p.categoria)}" data-nome="${esc(p.nome)}"
              onclick="window.Elenco._ver('${aspas(p.nome)}')" title="Abrir a ficha">
        <span class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(p.nome)}</span>${marcas}</span>
        ${p.descricao ? `<span class="lcl-item-desc">${esc(p.descricao)}</span>` : ''}
        ${p.local ? `<span class="elc-local">Em ${esc(p.local)}</span>` : ''}
      </button>`;
  }

  function render(d) {
    _last = d || {};
    ensureDom();
    const contagem = _last.contagem || {};
    q('elc-filtros').innerHTML = FILTROS.map(([id, rotulo]) => `
      <button class="elc-filtro${id === _filtro ? ' elc-filtro-ativo' : ''}" data-filtro="${id}" role="tab"
              aria-selected="${id === _filtro}" onclick="window.Elenco._filtrar('${id}')">
        ${rotulo} <span class="elc-filtro-conta">${contagem[id] || 0}</span></button>`).join('');

    const todos = _last.personagens || [];
    const lista = todos.filter(p => passaNoFiltro(p) && casaNaBusca(p));
    q('elc-lista').innerHTML = lista.length
      ? lista.map(cartao).join('')
      : `<div class="lcl-vazio">${todos.length
          ? 'Ninguém com esse filtro ou essa busca.'
          : 'Nenhum personagem registrado ainda.'}</div>`;
  }

  function mensagem(txt, erro) {
    const el = q('elc-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  // ---- Abrir / fechar ----------------------------------------------
  async function abrir(filtro) {
    ensureDom();
    if (filtro && FILTROS.some(([id]) => id === filtro)) _filtro = filtro;
    if (!_open) {
      q('elenco-overlay').classList.remove('hidden');
      document.body.classList.add('elenco-on');
      _open = true;
      _busca = '';
      q('elc-busca').value = '';
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
    const el = q('elenco-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('elenco-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  async function sync() {
    if (!_open) return;
    try { render(await getState()); } catch (_) { /* nunca derruba o turno */ }
  }

  function ver(nome) {
    const p = (_last.personagens || []).find(x => x.nome === nome) || {};
    fechar();
    if (p.do_grupo && p.tem_ficha && window.Herois) window.Herois._abrir(nome);
    else if (window.Personagens) window.Personagens._abrir(nome);
  }

  function novo(tipo) {
    fechar();
    if (tipo === 'membro' && typeof window.addNewPartyMember === 'function') window.addNewPartyMember();
    if (tipo === 'personagem' && typeof window.addNewCharacter === 'function') window.addNewCharacter();
  }

  window.Elenco = {
    sync,
    _abrir: abrir,
    _fechar: fechar,
    _filtrar: (id) => { _filtro = id; render(_last); },
    _buscar: (texto) => { _busca = norm(texto); render(_last); },
    _ver: ver,
    _novo: novo,
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
