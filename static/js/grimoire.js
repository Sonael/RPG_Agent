// ═══════════════════════════════════════════════════════════════════
//  grimoire.js — Tela de magias ("O Grimório")
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo mora
//  aqui. Quantos truques e magias cabem, até que círculo a classe chega, se
//  a magia é da lista da classe e se ela já é conhecida — tudo vem do motor
//  (tools_dnd via /api/grimoire/*). O botão "Aprender" chama learn_spell, a
//  mesma função do mestre.
//
//  A tela existe pelo mesmo motivo da de nível: escolher magia é escolha do
//  JOGADOR, e no chat quem acabava escolhendo era o modelo. Aqui ele vê a
//  lista da classe, as vagas que tem e o que cada magia faz, e decide.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _busy = false;
  let _last = {};
  let _quem = '';
  let _q = '';
  let _nivel = null;          // filtro de círculo; null = todos
  let _aprendidas = [];       // o que foi aprendido desde que a tela abriu
  let _timerBusca = null;

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q   = (id) => document.getElementById(id);

  // ---- Memória de "já vi estas vagas" -----------------------------------
  // A assinatura do motor é a lista "Nome:nível" de quem tem vaga. Aqui fica o
  // CONJUNTO de entradas já vistas, e a tela abre sozinha só quando aparece
  // uma entrada que não está nele — na prática, um conjurador que subiu de
  // nível. Entrada que SOME (a vaga foi preenchida) não abre nada.
  //
  // E a primeira vez que este navegador vê a campanha não abre: marca o que
  // existe como visto e deixa só a pílula. Quase todo conjurador de campanha
  // antiga tem vaga sobrando, e o Grimório pularia no primeiro carregamento
  // de todo mundo — por uma vaga que ninguém acabou de ganhar.
  function campanhaAtual() {
    try { return (JSON.parse(localStorage.getItem('rpg_session') || '{}').campaign) || ''; }
    catch (_) { return ''; }
  }
  const CHAVE_MEMORIA = () => `rpg_telas::${campanhaAtual()}::grimorio_visto`;
  const entradas = (assinatura) => (assinatura ? assinatura.split('|').filter(Boolean) : []);
  function lerVistas() {
    try {
      const bruto = localStorage.getItem(CHAVE_MEMORIA());
      return bruto === null ? null : new Set(JSON.parse(bruto));
    } catch (_) { return new Set(); }
  }
  function marcarVista(assinatura) {
    const vistas = lerVistas() || new Set();
    entradas(assinatura).forEach(e => vistas.add(e));
    try { localStorage.setItem(CHAVE_MEMORIA(), JSON.stringify([...vistas])); }
    catch (_) { /* sem storage, só perde a memória entre recargas */ }
  }

  // A fila do game.js roda combate → nível → grimório → descanso → loja.
  const OUTRAS_TELAS = ['combat-on', 'levelup-on', 'rest-on', 'shop-on', 'inventory-on',
                        'loot-on', 'local-on', 'pessoa-on', 'heroi-on', 'missoes-on', 'mapa-on', 'grupo-on', 'diario-on', 'elenco-on', 'relacoes-on', 'mundo-on'];
  const outraTelaAberta = () => OUTRAS_TELAS.some(c => document.body.classList.contains(c));

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (q('grimoire-overlay')) return;
    const o = document.createElement('div');
    o.id = 'grimoire-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="grm-frame">
        <header class="grm-header">
          <button class="grm-close" onclick="window.Grimoire._close()"
                  aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="grm-title">O Grimório <span id="grm-quem"></span></h1>
          <div id="grm-sub" class="grm-sub"></div>
          <div id="grm-vagas" class="grm-vagas"></div>
        </header>

        <div class="grm-corpo">
          <section class="grm-aprender" aria-label="Aprender magias">
            <div class="grm-busca-linha">
              <input id="grm-busca" type="search" autocomplete="off"
                     placeholder="Buscar magia pelo nome (ex: fireball)"
                     oninput="window.Grimoire._buscar(this.value)">
            </div>
            <div id="grm-filtros" class="grm-filtros"></div>
            <div id="grm-lista" class="grm-lista"></div>
          </section>
          <section class="grm-conhecidas" aria-label="Magias conhecidas">
            <h2 class="grm-secao">Conhecidas</h2>
            <div id="grm-conhecidas-lista"></div>
          </section>
        </div>

        <div class="grm-rodape">
          <div id="grm-msg" class="grm-msg" aria-live="polite"></div>
          <button id="grm-concluir" class="grm-concluir"
                  onclick="window.Grimoire._concluir()">Concluir</button>
        </div>
      </div>`;
    document.body.appendChild(o);

    if (!q('grm-reopen')) {
      const pill = document.createElement('button');
      pill.id = 'grm-reopen';
      pill.className = 'hidden';
      pill.onclick = () => window.Grimoire._abrir();
      document.body.appendChild(pill);
    }
  }

  // ---- Rede --------------------------------------------------------
  async function api(path, opts) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}${path}`, opts || {});
    return r.json();
  }
  function getState() {
    const p = new URLSearchParams();
    if (_quem) p.set('personagem', _quem);
    if (_q) p.set('q', _q);
    if (_nivel !== null) p.set('nivel', String(_nivel));
    const s = p.toString();
    return api('/api/grimoire/state' + (s ? '?' + s : ''));
  }
  function doAction(payload) {
    return api('/api/grimoire/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, q: _q, spell_level: _nivel }),
    });
  }

  // ---- Render ------------------------------------------------------
  const circulo = (n) => (n === 0 ? 'Truque' : `${n}º círculo`);
  const BLOQUEIO = {
    'já conhece': 'Já conhece',
    'limite de truques': 'Sem vaga de truque',
    'limite de magias': 'Sem vaga de magia',
  };

  function vagas(p) {
    const v = p.vagas;
    const chip = (rotulo, usados, max, livres) => `
      <span class="grm-vaga${livres ? ' grm-vaga-livre' : ''}">
        <span class="grm-vaga-rotulo">${rotulo}</span>
        <span class="grm-vaga-num">${usados} / ${max}</span>
        ${livres ? `<span class="grm-vaga-falta">${livres} a aprender</span>` : ''}
      </span>`;
    return (v.truques_max ? chip('Truques', v.truques_usados, v.truques_max, v.truques) : '')
         + chip('Magias', v.magias_usadas, v.magias_max, v.magias);
  }

  function filtros(p) {
    const botoes = [{ n: null, t: 'Todas' }];
    if (p.vagas.truques_max) botoes.push({ n: 0, t: 'Truques' });
    for (let i = 1; i <= p.nivel_max_magia; i++) botoes.push({ n: i, t: `${i}º` });
    return botoes.map(b => `
      <button class="grm-filtro${_nivel === b.n ? ' grm-filtro-on' : ''}"
              data-nivel="${b.n === null ? '' : b.n}"
              onclick="window.Grimoire._filtro(${b.n === null ? 'null' : b.n})">${b.t}</button>`).join('');
  }

  function cartao(sp) {
    const livre = !sp.bloqueio;
    const marcas = [
      `<span class="grm-circulo">${circulo(sp.nivel_magia)}</span>`,
      sp.escola ? `<span class="grm-escola">${esc(sp.escola)}</span>` : '',
      sp.concentracao ? '<span class="grm-marca">concentração</span>' : '',
      sp.ritual ? '<span class="grm-marca">ritual</span>' : '',
    ].join('');
    const custo = [
      sp.custo_mana ? `${sp.custo_mana} mana` : 'sem custo',
      sp.dado ? esc(sp.dado) : '',
      sp.alcance ? esc(sp.alcance) : '',
    ].filter(Boolean).join(' · ');
    return `
      <div class="grm-magia${livre ? '' : ' grm-magia-fora'}" data-nome="${esc(sp.nome)}">
        <div class="grm-magia-cabeca">
          <span class="grm-magia-nome">${esc(sp.nome)}</span>
          ${sp.nome_srd && sp.nome_srd !== sp.nome
            ? `<span class="grm-magia-srd" title="Nome no SRD">${esc(sp.nome_srd)}</span>` : ''}
          <span class="grm-magia-marcas">${marcas}</span>
        </div>
        ${sp.descricao ? `<p class="grm-magia-desc${sp.em_ingles ? ' grm-magia-desc-en' : ''}"
             ${sp.em_ingles ? 'lang="en" title="Descrição como vem do SRD, em inglês"' : ''}
             >${esc(sp.descricao)}</p>` : ''}
        <div class="grm-magia-linha">
          <span class="grm-magia-custo">${custo}</span>
          <button class="grm-aprender-btn" ${livre ? '' : 'disabled'}
                  onclick="window.Grimoire._aprender('${esc(sp.nome).replace(/'/g, "\\'")}')">
            ${livre ? 'Aprender' : esc(BLOQUEIO[sp.bloqueio] || sp.bloqueio)}
          </button>
        </div>
      </div>`;
  }

  function conhecidas(p) {
    if (!p.conhecidas.length) {
      return '<div class="grm-vazio-lado">Nenhuma magia ainda.</div>';
    }
    const grupos = {};
    p.conhecidas.forEach(m => { (grupos[m.nivel] = grupos[m.nivel] || []).push(m); });
    return Object.keys(grupos).sort((a, b) => a - b).map(n => `
      <div class="grm-conhecidas-grupo">
        <div class="grm-conhecidas-titulo">${n == 0 ? 'Truques' : `${n}º círculo`}</div>
        ${grupos[n].map(m => `
          <div class="grm-conhecida" data-nome="${esc(m.nome)}" title="${esc(m.descricao)}">
            <span class="grm-conhecida-nome">${esc(m.nome)}</span>
            <span class="grm-conhecida-custo">${m.custo_mana ? `${m.custo_mana} mana` : ''}${m.dado ? ` · ${esc(m.dado)}` : ''}</span>
          </div>`).join('')}
      </div>`).join('');
  }

  // A magia recém-aprendida e até quando ela brilha (aprender, abaixo).
  let _brilho = null;
  function brilharAprendida() {
    if (!_brilho || Date.now() > _brilho.ate || !window.destacar) return;
    const el = [...document.querySelectorAll('#grimoire-overlay .grm-conhecida')]
      .find(e => e.dataset.nome === _brilho.nome);
    if (el && !el.classList.contains('grm-aprendeu')) window.destacar(el, 'grm-aprendeu');
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();
    const p = _last.personagem;

    if (!p) {
      q('grm-quem').textContent = '';
      q('grm-sub').textContent = '';
      q('grm-vagas').innerHTML = '';
      q('grm-filtros').innerHTML = '';
      q('grm-lista').innerHTML = '<div class="grm-vazio">Ninguém no grupo conjura magias.</div>';
      q('grm-conhecidas-lista').innerHTML = '';
      q('grm-concluir').textContent = 'Fechar';
      q('grm-concluir').dataset.proximo = '';
      return;
    }

    const grupo = _last.grupo || [];
    q('grm-quem').textContent = `— ${p.nome}`;
    q('grm-sub').innerHTML =
      (grupo.length > 1
        ? `<select class="grm-quem-sel" aria-label="Personagem"
                   onchange="window.Grimoire._trocar(this.value)">`
          + grupo.map(n => `<option value="${esc(n)}" ${n === p.nome ? 'selected' : ''}>`
                         + `${esc(n)}${(_last.devendo || []).includes(n) ? ' (vagas)' : ''}</option>`).join('')
          + '</select>'
        : '')
      // Só a classe é capitalizada: com o capitalize no trecho inteiro saía
      // "Até O 2º Círculo".
      + `<span><span class="grm-classe">${esc(p.classe)}</span> · nível ${p.nivel}`
      + (p.mana_max ? ` · mana ${p.mana_atual}/${p.mana_max}` : '')
      + (p.nivel_max_magia ? ` · até o ${p.nivel_max_magia}º círculo` : ' · ainda sem magias de círculo')
      + '</span>';
    q('grm-vagas').innerHTML = vagas(p);
    q('grm-filtros').innerHTML = filtros(p);

    const busca = q('grm-busca');
    if (busca && document.activeElement !== busca) busca.value = _q;

    // O motivo da lista vazia vem do motor: "não respondeu" só quando o SRD de
    // fato não respondeu. Um patrulheiro de nível 1 via essa mensagem para
    // sempre, e a lista dele está vazia por regra.
    const cat = _last.catalogo || [];
    const motivo = _last.catalogo_motivo
      || (_q ? 'Nenhuma magia da lista da classe com esse nome.'
             : 'A lista da classe não respondeu. Tente de novo em instantes.');
    q('grm-lista').innerHTML = cat.length
      ? cat.map(cartao).join('')
      : `<div class="grm-vazio">${esc(motivo)}</div>`;
    q('grm-conhecidas-lista').innerHTML = conhecidas(p);
    brilharAprendida();

    // Mesmo desenho do rodapé da tela de nível: se outro do grupo ainda tem
    // vaga, o botão leva a ele em vez de encerrar a cena.
    const outros = (_last.devendo || []).filter(n => n !== p.nome);
    const btn = q('grm-concluir');
    if (outros.length) {
      btn.textContent = `Agora ${outros[0]} →`;
      btn.dataset.proximo = outros[0];
    } else {
      btn.textContent = 'Concluir';
      btn.dataset.proximo = '';
    }
  }

  function carregando() {
    const el = q('grm-lista');
    if (el) el.innerHTML = '<div class="grm-vazio">Consultando a lista da classe…</div>';
  }

  function recarregar() {
    carregando();
    return getState().then(render).catch(() => mensagem('Falha de conexão.', false));
  }

  // ---- Sincronia ---------------------------------------------------
  async function sync() {
    try {
      // A fila roda a cada turno; buscar o catálogo inteiro só para decidir
      // se abre seria uma ida ao SRD por turno. Fechada, a tela pede o resumo
      // (vagas e assinatura), sem catálogo.
      const snap = _open ? await getState() : await api('/api/grimoire/state?resumo=1');
      if (!snap) return;
      const assinatura = snap.assinatura || '';
      const vistas = lerVistas();

      if (vistas === null) {
        marcarVista(assinatura);             // primeira vez: só a pílula
      } else if (entradas(assinatura).some(e => !vistas.has(e)) && !_open && !outraTelaAberta()) {
        marcarVista(assinatura);
        // Abre em quem tem vaga, não no último personagem que o jogador viu.
        _quem = ''; _q = ''; _nivel = null;
        abrir();
        atualizarPilula(snap);
        return;
      }
      atualizarPilula(snap);
      if (_open) {
        // Com a tela aberta o jogador está VENDO as vagas: o que está na tela
        // é, por definição, visto. Sem isto, aprender uma magia mudava a
        // assinatura e fechar a tela a reabria na hora.
        marcarVista(assinatura);
        render(snap);
      } else {
        _last = snap;
      }
    } catch (_) { /* o grimório nunca derruba o turno */ }
  }

  function atualizarPilula(snap) {
    const pill = q('grm-reopen');
    if (!pill) return;
    const devendo = snap.devendo || [];
    if (devendo.length && !_open) {
      pill.textContent = devendo.length === 1
        ? `${devendo[0]}: magias a aprender`
        : `${devendo.length} com magias a aprender`;
      pill.classList.remove('hidden');
    } else {
      pill.classList.add('hidden');
    }
  }

  // ---- Abrir / fechar ----------------------------------------------
  function abrir(nome) {
    ensureDom();
    if (nome) _quem = nome;
    q('grimoire-overlay').classList.remove('hidden');
    document.body.classList.add('grimoire-on');
    const pill = q('grm-reopen');
    if (pill) pill.classList.add('hidden');
    _open = true;
    _aprendidas = [];
    mensagem('', true);
    recarregar();
  }

  function fechar() {
    const el = q('grimoire-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('grimoire-on');
    _open = false;
    atualizarPilula(_last || {});
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  function mensagem(txt, ok) {
    const el = q('grm-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('grm-msg-erro', !ok);
  }

  // ---- Ações --------------------------------------------------------
  async function aprender(nome) {
    if (_busy) return;
    const p = _last.personagem || {};
    if (!p.nome) return;
    _busy = true;
    try {
      const res = await doAction({ action: 'aprender', char: p.nome, spell: nome });
      _busy = false;
      if (!res) return;
      mensagem((res.message || '').split('\n')[0].replace(/\*\*/g, ''), res.ok !== false);
      if (res.ok !== false) _aprendidas.push(`${p.nome}: ${nome}`);
      if (res.snapshot) {
        // A vaga que sobrou já foi vista: é a que está na tela agora.
        marcarVista(res.snapshot.assinatura || '');
        render(res.snapshot);
      }
      // A magia aprendida brilha ao chegar à lista das conhecidas. Guardada
      // por um instante: a memória recarrega logo depois e redesenha a lista,
      // e o brilho iria embora com o elemento antigo.
      if (res.ok !== false) {
        _brilho = { nome, ate: Date.now() + 1400 };
        brilharAprendida();
      }
      if (res.ok !== false && typeof window.refreshMemory === 'function') window.refreshMemory();
    } catch (_) {
      _busy = false;
      mensagem('Falha de conexão.', false);
    }
  }

  async function concluir() {
    const btn = q('grm-concluir');
    if (btn && btn.dataset.proximo) { window.Grimoire._trocar(btn.dataset.proximo); return; }
    const aprendidas = _aprendidas.slice();
    fechar();
    // Sem magia nova não há o que narrar: fechar basta.
    if (!aprendidas.length) return;
    const txt = `[GRIMÓRIO RESOLVIDO NA TELA] Magias aprendidas: ${aprendidas.join('; ')}. `
              + 'Narre em uma ou duas frases como elas chegaram ao repertório, sem '
              + 'chamar learn_spell de novo e sem inventar efeito que não esteja na ficha.';
    try {
      if (typeof window.sendToAgent === 'function') await window.sendToAgent(txt, true, 'tela');
    } catch (_) { /* fechar já é o essencial */ }
  }

  // ---- API pública ---------------------------------------------------
  window.Grimoire = {
    sync,
    _abrir: abrir,
    _close: fechar,
    _concluir: concluir,
    _aprender: aprender,
    _trocar: (n) => { _quem = n; _nivel = null; recarregar(); },
    _filtro: (n) => { _nivel = n; recarregar(); },
    // A busca espera o jogador parar de digitar: cada tecla seria uma ida ao SRD.
    _buscar: (texto) => {
      _q = (texto || '').trim();
      clearTimeout(_timerBusca);
      _timerBusca = setTimeout(recarregar, 350);
    },
  };

  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
