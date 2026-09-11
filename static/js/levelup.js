// ═══════════════════════════════════════════════════════════════════
//  levelup.js — Tela de subida de nível ("A Ascensão")
//
//  REGRA DE OURO, a mesma do combat.js e do shop.js: nenhuma regra de jogo
//  mora aqui. Quais escolhas estão pendentes, quais opções existem, o teto
//  de 20 no atributo e o que cada escolha concede — tudo vem do motor
//  (tools_dnd via /api/levelup/*).
//
//  Esta tela existe por um motivo DIFERENTE das outras duas. Combate e loja
//  são laços: muitas decisões pequenas, e a tela tira a LLM do caminho.
//  Subir de nível acontece umas dez vezes numa campanha inteira — não há
//  laço nenhum. O que há é um conjunto de escolhas que o modelo inventaria:
//  estilo de combate, arquétipo, para onde vão os pontos de atributo. Aqui
//  a tela não economiza tempo, ela impede invenção.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open  = false;
  let _busy  = false;
  let _last  = {};
  let _quem  = '';
  let _visto = '';     // assinatura das pendências que já abriram a tela

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q   = (id) => document.getElementById(id);

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (q('levelup-overlay')) return;
    const o = document.createElement('div');
    o.id = 'levelup-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="lvl-frame">
        <header class="lvl-header">
          <button class="lvl-close" onclick="window.LevelUp._close()"
                  aria-label="Fechar"
                  title="Fechar — as escolhas continuam pendentes">✕</button>
          <h1 class="lvl-title">A Ascensão <span id="lvl-quem">—</span></h1>
          <div id="lvl-sub" class="lvl-sub"></div>
          <div class="lvl-xp">
            <div class="lvl-xp-barra"><div id="lvl-xp-fill" class="lvl-xp-fill"></div></div>
            <div id="lvl-xp-num" class="lvl-xp-num"></div>
          </div>
        </header>

        <div id="lvl-atributos" class="lvl-atributos"></div>
        <div id="lvl-corpo" class="lvl-corpo"></div>

        <div class="lvl-rodape">
          <div id="lvl-msg" class="lvl-msg"></div>
          <button id="lvl-concluir" class="lvl-concluir"
                  onclick="window.LevelUp._concluir()">Concluir</button>
        </div>
      </div>`;
    document.body.appendChild(o);

    if (!q('lvl-reopen')) {
      const pill = document.createElement('button');
      pill.id = 'lvl-reopen';
      pill.className = 'hidden';
      pill.onclick = () => window.LevelUp._abrir();
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
    return api('/api/levelup/state' + (_quem ? `?personagem=${encodeURIComponent(_quem)}` : ''));
  }
  function doAction(p) {
    return api('/api/levelup/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }

  // ---- Render ------------------------------------------------------
  function atributos(p) {
    q('lvl-atributos').innerHTML = (p.atributos || []).map(a => `
      <div class="lvl-attr">
        <span class="lvl-attr-nome">${esc(a.nome)}</span>
        <span class="lvl-attr-sigla">${esc(a.sigla || a.nome)}</span>
        <span class="lvl-attr-valor">${a.valor}</span>
        <span class="lvl-attr-mod">${a.mod >= 0 ? '+' : ''}${a.mod}</span>
      </div>`).join('');
  }

  function cartaoVariante(pd) {
    const jaTem = (pd.escolhidos || []).length
      ? `<div class="lvl-ja">Já escolhido: ${pd.escolhidos.map(esc).join(', ')}</div>`
      : '';
    const quantos = pd.pick > 1
      ? `<span class="lvl-contagem">${(pd.escolhidos || []).length}/${pd.pick}</span>` : '';
    return `
      <section class="lvl-bloco">
        <h2 class="lvl-bloco-titulo">${esc(pd.rotulo)} ${quantos}</h2>
        ${pd.descricao ? `<p class="lvl-bloco-desc">${esc(pd.descricao)}</p>` : ''}
        ${jaTem}
        <div class="lvl-opcoes">
          ${(pd.opcoes || []).map(o => `
            <button class="lvl-opcao"
                    onclick="window.LevelUp._variante('${esc(pd.feature).replace(/'/g, "\\'")}','${esc(o.nome).replace(/'/g, "\\'")}')">
              <span class="lvl-opcao-nome">${esc(o.nome)}</span>
              <span class="lvl-opcao-desc">${esc(o.descricao)}</span>
            </button>`).join('')}
        </div>
      </section>`;
  }

  function cartaoAsi(pd) {
    // Cada botão gasta UM ponto. Dois cliques no mesmo atributo dão o +2, e
    // em dois atributos diferentes dão o +1/+1 — sem precisar de um seletor
    // de modo que o jogador teria que entender antes de escolher.
    const botoes = (pd.opcoes || []).map(o => `
      <button class="lvl-attr-btn${o.no_teto ? ' lvl-attr-topo' : ''}"
              ${o.no_teto ? 'disabled' : ''}
              title="${o.no_teto ? 'Já está no teto de 20' : '+1 ponto'}"
              onclick="window.LevelUp._asi('${esc(o.chave)}')">
        <span class="lvl-attr-btn-nome">${esc(o.nome)}</span>
        <span class="lvl-attr-btn-valor">${o.valor} → ${Math.min(20, o.valor + 1)}</span>
        <span class="lvl-attr-btn-mod">mod ${o.mod >= 0 ? '+' : ''}${o.mod}</span>
      </button>`).join('');

    return `
      <section class="lvl-bloco lvl-bloco-asi">
        <h2 class="lvl-bloco-titulo">
          Incremento de Atributo
          <span class="lvl-contagem">${pd.faltam} ponto${pd.faltam > 1 ? 's' : ''}</span>
        </h2>
        <p class="lvl-bloco-desc">${esc(pd.descricao)}</p>
        <div class="lvl-attr-grid">${botoes}</div>
        <div class="lvl-talento">
          <label for="lvl-talento-nome">…ou troque o incremento por um
            <b>talento</b> (consome os 2 pontos):</label>
          <div class="lvl-talento-linha">
            <input id="lvl-talento-nome" type="text" autocomplete="off"
                   placeholder="nome do talento em inglês, como no SRD (ex: Alert)">
            <button class="lvl-opcao lvl-talento-btn"
                    onclick="window.LevelUp._talento()">Escolher talento</button>
          </div>
        </div>
      </section>`;
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();

    const p = _last.personagem;
    if (!p) {
      q('lvl-quem').textContent = '';
      q('lvl-corpo').innerHTML =
        '<div class="lvl-vazio">Nenhum personagem com ficha no grupo.</div>';
      return;
    }

    const grupo = _last.grupo || [];
    q('lvl-quem').textContent = `— ${p.nome}`;
    q('lvl-sub').innerHTML =
      (grupo.length > 1
        ? `<select class="lvl-quem-sel" aria-label="Personagem"
                   onchange="window.LevelUp._trocar(this.value)">`
          + grupo.map(n => `<option value="${esc(n)}" ${n === p.nome ? 'selected' : ''}>`
                         + `${esc(n)}${(_last.devendo || []).includes(n) ? ' ⏳' : ''}</option>`).join('')
          + `</select>`
        : '')
      + `<span class="lvl-classe">${esc(p.classe)} · nível <b>${p.nivel}</b>`
      + ` · CA ${p.ca} · PV ${p.vida_max} · prof. +${p.proficiencia}</span>`;

    q('lvl-xp-fill').style.width = `${p.xp_pct}%`;
    q('lvl-xp-num').textContent =
      p.nivel >= 20 ? `${p.xp} XP — nível máximo`
                    : `${p.xp} / ${p.xp_proximo} XP`;

    atributos(p);

    const pend = _last.pendencias || [];
    if (!pend.length) {
      q('lvl-corpo').innerHTML = `
        <div class="lvl-vazio">
          <div class="lvl-ok">✓</div>
          Nada pendente para ${esc(p.nome)}.
          <small>As escolhas aparecem aqui quando um nível novo as concede.</small>
        </div>`;
    } else {
      q('lvl-corpo').innerHTML = pend
        .map(pd => pd.tipo === 'asi' ? cartaoAsi(pd) : cartaoVariante(pd))
        .join('');
    }

    // O rodapé muda de FUNÇÃO conforme o que falta, não só de rótulo:
    //   • este personagem ainda deve algo  → desabilitado (sair devendo é o
    //     que a tela existe para impedir; o ✕ continua fechando);
    //   • outro do grupo deve             → vira atalho para ele, porque um
    //     botão que diz "falta escolher: Helena" e conclui a cena seria
    //     mentira;
    //   • ninguém deve                    → conclui e manda narrar.
    const outros = (_last.devendo || []).filter(n => n !== p.nome);
    const btn = q('lvl-concluir');
    btn.disabled = pend.length > 0;
    if (pend.length) {
      btn.textContent = 'Escolha acima para continuar';
      btn.dataset.proximo = '';
    } else if (outros.length) {
      btn.textContent = `Agora ${outros[0]} →`;
      btn.dataset.proximo = outros[0];
    } else {
      btn.textContent = 'Concluir';
      btn.dataset.proximo = '';
    }
  }

  // ---- Sincronia ---------------------------------------------------
  async function sync() {
    try {
      const snap = await getState();
      if (!snap) return;

      // Assinatura do que está pendente. A tela abre sozinha quando ela MUDA
      // — ou seja, quando um nível novo criou escolha. Abrir toda vez que
      // houvesse pendência prenderia o jogador que decidiu deixar para
      // depois numa tela que reabre a cada turno.
      const assinatura = (snap.devendo || []).join('|') + '::' +
        (snap.pendencias || []).map(p => `${p.rotulo}:${p.faltam}`).join(',');

      atualizarPilula(snap);
      if ((snap.pendencias || []).length && assinatura !== _visto && !_open) {
        _visto = assinatura;
        abrir();
      }
      if (_open) render(snap); else _last = snap;
    } catch (_) { /* a tela de nível nunca derruba o turno */ }
  }

  function atualizarPilula(snap) {
    const pill = q('lvl-reopen');
    if (!pill) return;
    const devendo = snap.devendo || [];
    if (devendo.length && !_open) {
      pill.textContent = devendo.length === 1
        ? `⭐ ${devendo[0]}: escolha pendente`
        : `⭐ ${devendo.length} escolhas pendentes`;
      pill.classList.remove('hidden');
    } else {
      pill.classList.add('hidden');
    }
  }

  // ---- Abrir / fechar ----------------------------------------------
  function abrir() {
    ensureDom();
    q('levelup-overlay').classList.remove('hidden');
    document.body.classList.add('levelup-on');
    const pill = q('lvl-reopen');
    if (pill) pill.classList.add('hidden');
    _open = true;
    getState().then(render).catch(() => {});
  }

  function fechar() {
    const el = q('levelup-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('levelup-on');
    _open = false;
    atualizarPilula(_last || {});
  }

  function mensagem(txt, ok) {
    const el = q('lvl-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lvl-msg-erro', !ok);
  }

  // ---- Ações --------------------------------------------------------
  async function agir(payload) {
    if (_busy) return;
    const p = (_last.personagem || {});
    if (!p.nome) return;
    _busy = true;
    try {
      const res = await doAction({ char: p.nome, ...payload });
      _busy = false;
      if (res) {
        mensagem((res.message || '').split('\n')[0], res.ok !== false);
        if (res.snapshot) render(res.snapshot);
      }
    } catch (_) {
      _busy = false;
      mensagem('Falha de conexão.', false);
    }
  }

  async function concluir() {
    const btn = q('lvl-concluir');
    const proximo = btn && btn.dataset.proximo;
    if (proximo) { window.LevelUp._trocar(proximo); return; }

    const p = (_last.personagem || {});
    fechar();
    const txt = `[NÍVEL RESOLVIDO NA TELA] ${p.nome || 'O personagem'} chegou ao `
              + `nível ${p.nivel} e o jogador já fez todas as escolhas. Narre a `
              + `virada em uma ou duas frases, usando o que está na ficha — não `
              + `invente habilidade nem atributo que não esteja lá.`;
    try {
      if (typeof window.sendToAgent === 'function') await window.sendToAgent(txt, true);
    } catch (_) { /* fechar já é o essencial */ }
  }

  // ---- API pública ---------------------------------------------------
  window.LevelUp = {
    sync,
    _abrir: abrir,
    _close: fechar,
    _concluir: concluir,
    _trocar: (n) => { _quem = n; getState().then(render).catch(() => {}); },
    _variante: (feature, choice) => agir({ action: 'variante', feature, choice }),
    _asi: (chave) => agir({ action: 'asi', choice: chave, points: 1 }),
    _talento: () => {
      const el = q('lvl-talento-nome');
      const nome = (el && el.value || '').trim();
      if (!nome) { mensagem('Escreva o nome do talento.', false); return; }
      agir({ action: 'talento', choice: nome });
    },
  };

  document.addEventListener('DOMContentLoaded', () => { ensureDom(); sync(); });
})();
