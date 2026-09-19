// ═══════════════════════════════════════════════════════════════════
//  mapa.js — Mapa do mundo ("O Mapa")
//
//  A árvore de lugares da campanha: o que fica dentro de quê, onde o grupo
//  está (com o caminho até lá aberto), quem está em cada lugar e o que está a
//  um passo, com "Ir até lá". Busca por lugar ou pessoa.
//
//  Não é um mapa desenhado: o motor não tem distância nem direção, e pôr os
//  lugares num plano inventaria uma geografia que a campanha não tem.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo aqui. A
//  árvore, o alcance e quem está onde vêm do motor (rpg/mapa.py via
//  /api/map/state). Clicar num lugar abre a ficha do local; numa pessoa, a
//  ficha do personagem. "Ir até lá" manda a fala do jogador ao mestre.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _last = {};
  let _abertos = new Set();
  let _busca = '';
  let _foco = '';

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");
  const norm = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

  const ALCANCE = { aqui: 'grupo aqui', dentro: 'aqui dentro', vizinho: 'ao lado', acima: 'saída' };

  function ensureDom() {
    if (q('mapa-overlay')) return;
    const o = document.createElement('div');
    o.id = 'mapa-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="map-frame" role="dialog" aria-modal="true" aria-labelledby="map-titulo">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Mapa._fechar()" aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="lcl-title" id="map-titulo">O Mapa</h1>
          <div id="map-onde" class="map-onde"></div>
          <input id="map-busca" class="map-busca" type="search" autocomplete="off"
                 placeholder="Buscar lugar ou pessoa" aria-label="Buscar lugar ou pessoa"
                 oninput="window.Mapa._buscar(this.value)">
        </header>
        <div class="lcl-corpo">
          <section class="lcl-corpo-pessoas map-arvore-secao" aria-label="Lugares">
            <h2 class="lcl-secao">Lugares</h2>
            <div id="map-arvore" class="map-arvore" role="tree"></div>
          </section>
          <section class="lcl-corpo-dentro" aria-label="A um passo">
            <h2 class="lcl-secao">A um passo</h2>
            <div id="map-alcance" class="lcl-lista"></div>
            <div id="map-sem-bloco">
              <h2 class="lcl-secao map-secao-sem">Paradeiro desconhecido</h2>
              <div id="map-sem" class="map-pessoas"></div>
            </div>
          </section>
        </div>
        <div class="lcl-rodape">
          <div id="map-msg" class="lcl-msg" aria-live="polite"></div>
          <button id="map-novo" class="lcl-btn lcl-btn-sec" onclick="window.Mapa._novo()"
                  title="Registrar um lugar novo">Novo local</button>
          <button class="lcl-fechar" onclick="window.Mapa._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  async function getState() {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}/api/map/state`);
    return r.json();
  }

  // ---- Busca -------------------------------------------------------
  // Um nó aparece se ele, uma pessoa dele ou algum descendente casa com a
  // busca. Com busca, tudo que casa fica aberto.
  function casa(no) {
    if (!_busca) return true;
    if (norm(no.nome).includes(_busca)) return true;
    if ((no.pessoas || []).some(p => norm(p.nome).includes(_busca))) return true;
    return (no.filhos || []).some(casa);
  }

  // ---- Render ------------------------------------------------------
  function pessoa(p) {
    return `<button class="map-pessoa${p.fora ? ' map-pessoa-fora' : ''}${
      _busca && norm(p.nome).includes(_busca) ? ' map-casou' : ''}"
      title="${p.fora ? esc(p.status) + ' · ' : ''}Ver a ficha de ${esc(p.nome)}"
      onclick="window.Mapa._verPessoa('${aspas(p.nome)}')">${esc(p.nome)}${
      p.fora ? ` <small>${esc(p.status)}</small>` : ''}</button>`;
  }

  function no(n) {
    if (!casa(n)) return '';
    const temFilhos = (n.filhos || []).length > 0;
    const temPessoas = (n.pessoas || []).length > 0;
    const expansivel = temFilhos || temPessoas;
    const aberto = expansivel && (_busca ? true : _abertos.has(n.nome));
    const marcas = [
      n.grupo_aqui ? `<span class="lcl-marca lcl-marca-grupo">${esc(window.frase('grupo_aqui', 'grupo aqui'))}</span>` : '',
      !n.grupo_aqui && ALCANCE[n.alcance] ? `<span class="lcl-marca map-marca-alcance">${ALCANCE[n.alcance]}</span>` : '',
      n.tipo === 'loja' ? '<span class="lcl-marca lcl-marca-loja">loja</span>' : '',
      n.tipo === 'sem_registro' ? '<span class="lcl-marca map-marca-sem" title="Citado na campanha, mas nunca registrado como local">sem registro</span>' : '',
      n.pessoas_total ? `<span class="map-contagem" title="Pessoas aqui e nos lugares de dentro">${n.pessoas_total} ${n.pessoas_total === 1 ? 'pessoa' : 'pessoas'}</span>` : '',
    ].join('');
    const ir = n.alcance && n.alcance !== 'aqui'
      ? `<button class="lcl-btn lcl-btn-ir map-ir" onclick="window.Mapa._ir('${aspas(n.nome)}')"
           title="Manda ao mestre: Vamos até ${esc(n.nome)}.">Ir até lá</button>` : '';
    const casou = _busca && norm(n.nome).includes(_busca);
    return `
      <div class="map-no${n.grupo_aqui ? ' map-no-grupo' : ''}${n.no_caminho_do_grupo ? ' map-no-caminho' : ''}${
        _foco === n.nome ? ' map-foco' : ''}" role="treeitem" aria-expanded="${aberto}"
           data-nome="${esc(n.nome)}">
        <div class="map-linha">
          ${expansivel
            ? `<button class="map-seta${aberto ? ' map-seta-aberta' : ''}" aria-label="${aberto ? 'Fechar' : 'Abrir'} ${esc(n.nome)}"
                 onclick="window.Mapa._alternar('${aspas(n.nome)}')"></button>`
            : '<span class="map-seta-vazia"></span>'}
          <button class="map-nome${casou ? ' map-casou' : ''}" title="Ver a ficha do local"
                  onclick="window.Mapa._verLocal('${aspas(n.nome)}')">${esc(n.nome)}</button>
          <span class="map-marcas">${marcas}</span>
          ${ir}
        </div>
        ${aberto ? `
          ${temPessoas ? `<div class="map-pessoas">${n.pessoas.filter(p => !_busca || casa({ nome: n.nome, pessoas: [p], filhos: [] }) || norm(n.nome).includes(_busca)).map(pessoa).join('')}</div>` : ''}
          ${temFilhos ? `<div class="map-filhos" role="group">${n.filhos.map(no).join('')}</div>` : ''}` : ''}
      </div>`;
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();
    const caminho = _last.caminho_atual || [];
    q('map-onde').innerHTML = _last.local_atual
      ? `<span class="map-onde-rotulo">${esc(window.frase('esta_em', 'O grupo está em'))}</span> ${caminho.map(esc).join('<span class="lcl-sep">›</span>')}`
      : '<span class="map-onde-rotulo">Local atual não definido</span>';

    const arvore = _last.arvore || [];
    const html = arvore.map(no).join('');
    q('map-arvore').innerHTML = arvore.length
      ? (html || '<div class="lcl-vazio">Nada encontrado.</div>')
      : '<div class="lcl-vazio">Nenhum lugar registrado ainda.</div>';

    const alcance = _last.ao_alcance || [];
    q('map-alcance').innerHTML = alcance.length
      ? alcance.map(a => `
          <div class="lcl-item" data-nome="${esc(a.nome)}">
            <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(a.nome)}</span>
              <span class="lcl-marca map-marca-alcance">${ALCANCE[a.alcance] || ''}</span>
              ${a.tipo === 'loja' ? '<span class="lcl-marca lcl-marca-loja">loja</span>' : ''}</div>
            <div class="lcl-item-acoes">
              <button class="lcl-btn lcl-btn-sec" onclick="window.Mapa._verLocal('${aspas(a.nome)}')">Ver</button>
              <button class="lcl-btn lcl-btn-ir" onclick="window.Mapa._ir('${aspas(a.nome)}')">Ir até lá</button>
            </div>
          </div>`).join('')
      : '<div class="lcl-vazio">Nenhum lugar registrado a um passo daqui.</div>';

    const sem = _last.sem_paradeiro || [];
    q('map-sem-bloco').classList.toggle('hidden', !sem.length);
    q('map-sem').innerHTML = sem.map(p => pessoa({ ...p, fora: false })).join('');
  }

  function mensagem(txt, erro) {
    const el = q('map-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  // ---- Abrir / fechar ----------------------------------------------
  function abrirCaminhoPadrao(arvore) {
    const visitar = (n) => {
      if (n.no_caminho_do_grupo || n.profundidade === 0) _abertos.add(n.nome);
      (n.filhos || []).forEach(visitar);
    };
    (arvore || []).forEach(visitar);
  }

  async function abrir(foco) {
    ensureDom();
    q('map-titulo').textContent = window.nomeDaTela('titulo_mapa', 'O Mapa');
    _foco = foco || '';
    if (!_open) {
      q('mapa-overlay').classList.remove('hidden');
      document.body.classList.add('mapa-on');
      _open = true;
      _busca = '';
      const busca = q('map-busca');
      if (busca) busca.value = '';
    }
    mensagem('Carregando…');
    try {
      const snap = await getState();
      _abertos = new Set();
      abrirCaminhoPadrao(snap.arvore);
      if (_foco) abrirAte(snap.arvore, _foco);
      render(snap);
      mensagem('');
      if (_foco) {
        const el = [...document.querySelectorAll('#map-arvore .map-no')].find(x => x.dataset.nome === _foco);
        if (el) try { el.scrollIntoView({ block: 'nearest' }); } catch (_) { /* sem rolagem */ }
      }
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  // Abre os ancestrais de um lugar para ele aparecer na árvore.
  function abrirAte(arvore, nome) {
    const achar = (lista, trilha) => {
      for (const n of lista || []) {
        if (n.nome === nome) { trilha.forEach(t => _abertos.add(t)); return true; }
        if (achar(n.filhos, [...trilha, n.nome])) return true;
      }
      return false;
    };
    achar(arvore, []);
  }

  function fechar() {
    const el = q('mapa-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('mapa-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  function enviar(texto) {
    if (typeof waiting !== 'undefined' && waiting) {
      mensagem('Aguarde o mestre terminar de responder.', true);
      return;
    }
    if (typeof window.sendToAgent !== 'function' || typeof window.appendUser !== 'function') return;
    fechar();
    window.appendUser(texto);
    window.sendToAgent(texto, true);
  }

  window.Mapa = {
    _abrir: abrir,
    _fechar: fechar,
    _alternar: (nome) => {
      if (_abertos.has(nome)) _abertos.delete(nome); else _abertos.add(nome);
      render(_last);
    },
    _buscar: (texto) => { _busca = norm(texto); render(_last); },
    _ir: (nome) => enviar(`Vamos até ${nome}.`),
    _verLocal: (nome) => { fechar(); if (window.Locais) window.Locais._abrir(nome); },
    // A lista de locais saiu da barra lateral; criar um lugar é aqui.
    _novo: () => { fechar(); if (typeof window.addNewLocation === 'function') window.addNewLocation(); },
    _verPessoa: (nome) => { fechar(); if (window.Personagens) window.Personagens._abrir(nome); },
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
