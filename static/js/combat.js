// ═══════════════════════════════════════════════════════════════════
//  combat.js — Tela de combate tática (estilo "Pergaminho Épico")
//
//  REGRA DE OURO: este módulo NÃO tem nenhuma regra de jogo.
//  Toda mecânica vive no motor já fuzzado (tools_dnd via /api/combat/*).
//  Aqui só: (1) renderiza o snapshot, (2) envia intenções, (3) reabre/
//  fecha a tela e dispara a narração final pela LLM.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open      = false;   // overlay visível
  let _busy      = false;   // requisição em voo (trava de clique duplo)
  let _ending    = false;   // recap em andamento (evita disparo duplo)
  let _mode      = 'narrado';
  let _autoTimer = null;
  let _autoGuard = 0;       // teto de segurança p/ turnos de IA encadeados
  let _pick      = null;    // {kind:'attack'|'ability', ability?}
  let _userClosed = false;  // usuário fechou a tela de propósito (combate segue)

  const OUT = ['morto', 'inconsciente', 'estabilizado', 'fugiu', 'exilado'];
  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const isOut = (st) => OUT.includes((st || '').toLowerCase());

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (document.getElementById('combat-overlay')) return;
    const o = document.createElement('div');
    o.id = 'combat-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="cbt-frame">
        <header class="cbt-header">
          <button class="cbt-close" onclick="window.Combat._dismiss()"
                  aria-label="Fechar tela de combate"
                  title="Fechar — o combate continua e pode ser retomado">✕</button>
          <h1 class="cbt-title">O Confronto <span id="cbt-round">— Rodada 1</span></h1>
          <div id="cbt-order" class="cbt-initiative"></div>
        </header>

        <div class="cbt-battlefield">
          <div id="cbt-party"   class="cbt-team"></div>
          <div id="cbt-stage"   class="cbt-vs">Vs.</div>
          <div id="cbt-enemies" class="cbt-team"></div>
        </div>

        <div class="cbt-lower">
          <div id="cbt-actionbar" class="cbt-action-panel">
            <div id="cbt-action-title" class="cbt-action-title">Aguardando…</div>
            <div id="cbt-prompt" class="cbt-economy"></div>
            <div id="cbt-buttons" class="cbt-btn-grid"></div>
            <div id="cbt-targets" class="cbt-picker hidden"></div>
          </div>
          <div class="cbt-log-panel">
            <div class="cbt-log-title">Diário de Combate</div>
            <div id="cbt-log" class="cbt-log-content"></div>
          </div>
        </div>

        <div id="cbt-end-overlay" class="cbt-end-overlay hidden"></div>
      </div>`;
    document.body.appendChild(o);

    // Pílula flutuante para RETOMAR o combate depois que o usuário fechou
    // a tela. Fica fora do #combat-overlay (que some quando fechado).
    if (!document.getElementById('cbt-reopen')) {
      const pill = document.createElement('button');
      pill.id = 'cbt-reopen';
      pill.className = 'hidden';
      pill.textContent = '⚔️ Retomar combate';
      pill.onclick = () => window.Combat._reopen();
      document.body.appendChild(pill);
    }
  }

  // ---- Rede --------------------------------------------------------
  async function api(path, opts) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}${path}`, opts || {});
    return r.json();
  }
  function getState()  { return api('/api/combat/state'); }
  function doAction(p) {
    return api('/api/combat/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }

  // ---- Render ------------------------------------------------------
  function bar(label, cur, max, cls) {
    const m = max > 0 ? Math.max(0, Math.min(100, (cur / max) * 100)) : 0;
    return `<div class="cbt-bar-row">
      <span class="cbt-bar-label">${label}</span>
      <div class="cbt-bar"><div class="cbt-bar-fill ${cls}" style="width:${m}%"></div></div>
      <span class="cbt-bar-num">${cur}/${max}</span>
    </div>`;
  }

  function card(c) {
    const out    = isOut(c.status);
    // "dormindo" (Sleep): esmaece o card e mostra a tag, MAS continua
    // alvejável (não entra em isOut, então o picker de alvo o inclui).
    const asleep = (c.status || '').toLowerCase() === 'dormindo';
    const dim    = out || asleep;
    const conds  = (c.condicoes || []).map(x => `<span class="cbt-cond">${esc(x)}</span>`).join('');
    const meta   = `${esc(c.classe || '')}${c.nivel ? ' Nv.' + c.nivel : ''}`.trim();
    return `<div class="cbt-card ${c.is_current ? 'cbt-cur' : ''} ${
      out ? 'cbt-out' : (asleep ? 'cbt-asleep' : '')}">
      <div class="cbt-c-header">
        <span class="cbt-name">${esc(c.name)}</span>
        ${c.is_current ? '<span class="cbt-arrow">▶</span>' : ''}
      </div>
      <div class="cbt-meta">
        <span>${meta || '—'}</span>
        <span class="cbt-ca">🛡️ ${c.ca}</span>
      </div>
      <div class="cbt-bars">
        ${bar('HP', c.hp, c.hp_max, 'hp')}
        ${c.mp_max > 0 ? bar('MP', c.mp, c.mp_max, 'mp') : ''}
      </div>
      ${(conds || dim) ? `<div class="cbt-conds">${conds}${
        dim ? `<span class="cbt-cond cbt-cond-out">${esc(c.status)}</span>` : ''
      }</div>` : ''}
    </div>`;
  }

  function render(snap) {
    ensureDom();
    document.getElementById('cbt-end-overlay').classList.add('hidden');

    const enemies = (snap.combatants || []).filter(c => !c.is_party);
    const party   = (snap.combatants || []).filter(c => c.is_party);

    document.getElementById('cbt-round').textContent = `— Rodada ${snap.round || 1}`;

    document.getElementById('cbt-order').innerHTML = (snap.order || [])
      .map((n, i) => {
        const ch   = (snap.combatants || []).find(c => c.name === n);
        const dead = ch && isOut(ch.status);
        return `<span class="cbt-ord ${i === snap.turn_index ? 'on' : ''} ${dead ? 'cbt-ord-dead' : ''}">${esc(n)}</span>`;
      })
      .join('<span class="cbt-ord-sep">›</span>');

    document.getElementById('cbt-enemies').innerHTML = enemies.map(card).join('') || '<div class="cbt-empty">—</div>';
    document.getElementById('cbt-party').innerHTML   = party.map(card).join('')   || '<div class="cbt-empty">—</div>';

    const log = (snap.log || []).slice(-12).map(e =>
      `<div class="cbt-logline">[R${e.round}] ${esc(e.msg || e.type || '')}</div>`).join('');
    const lg = document.getElementById('cbt-log');
    lg.innerHTML = log;
    lg.scrollTop = lg.scrollHeight;

    renderActionBar(snap);
  }

  function renderActionBar(snap) {
    const titleEl  = document.getElementById('cbt-action-title');
    const promptEl = document.getElementById('cbt-prompt');
    const btnEl    = document.getElementById('cbt-buttons');
    const tgtEl    = document.getElementById('cbt-targets');
    tgtEl.classList.add('hidden'); tgtEl.innerHTML = ''; _pick = null;

    const cur = (snap.combatants || []).find(c => c.is_current);
    if (!cur) {
      titleEl.textContent = 'Aguardando…';
      promptEl.textContent = ''; btnEl.innerHTML = '';
      return;
    }

    if (!snap.current_is_party) {
      titleEl.textContent = 'Turno do Inimigo';
      promptEl.innerHTML  = `<span class="cbt-enemy-msg">“${esc(snap.current)} avança nas sombras…”</span>`;
      btnEl.innerHTML = '';
      return;
    }

    titleEl.textContent = `O que fará ${esc(cur.name)}?`;

    // Economia 5e (Ação + Bônus) do turno atual.
    const eco       = snap.turn_economy || {};
    const acaoUsed  = !!eco.acao_usada;
    const bonusUsed = !!eco.bonus_usada;
    promptEl.innerHTML =
      `Ação <span class="cbt-pip ${acaoUsed ? 'used' : ''}">${acaoUsed ? '●' : '○'}</span>`
      + ` <span class="cbt-econ-sep">|</span> `
      + `Bônus <span class="cbt-pip ${bonusUsed ? 'used' : ''}">${bonusUsed ? '●' : '○'}</span>`;

    const dis      = _busy ? 'disabled' : '';
    const actorEsc = esc(cur.name).replace(/'/g, "\\'");
    const acaoDis  = (acaoUsed || _busy) ? 'disabled' : '';

    const hasAcaoAbil  = (cur.habilidades || []).some(h => h.tipo_acao !== 'bonus');
    const hasBonusAbil = (cur.habilidades || []).some(h => h.tipo_acao === 'bonus');
    const hasAcaoItem  = (cur.itens_combate || []).some(i => i.tipo_acao !== 'bonus');
    const hasBonusItem = (cur.itens_combate || []).some(i => i.tipo_acao === 'bonus');
    const habUsable  = (hasAcaoAbil && !acaoUsed) || (hasBonusAbil && !bonusUsed);
    const itemUsable = (hasAcaoItem && !acaoUsed) || (hasBonusItem && !bonusUsed);

    let html =
      `<button class="cbt-btn" ${acaoDis} onclick="window.Combat._sel('attack')">⚔️ Atacar <small>(Ação)</small></button>`;
    if ((cur.habilidades || []).length) {
      const d = (habUsable && !_busy) ? '' : 'disabled';
      html += `<button class="cbt-btn" ${d} onclick="window.Combat._sel('ability')">✨ Habilidade</button>`;
    }
    if ((cur.itens_combate || []).length) {
      const d = (itemUsable && !_busy) ? '' : 'disabled';
      html += `<button class="cbt-btn" ${d} onclick="window.Combat._sel('item')">🧪 Item</button>`;
    }
    html +=
      `<button class="cbt-btn" ${acaoDis} onclick="window.Combat._act({action:'defend',actor:'${actorEsc}'})">🛡️ Defender <small>(Ação)</small></button>` +
      `<button class="cbt-btn" ${acaoDis} onclick="window.Combat._act({action:'flee',actor:'${actorEsc}'})">💨 Fugir <small>(Ação)</small></button>` +
      `<button class="cbt-btn" ${dis} onclick="window.Combat._free()">💬 Ação Livre</button>` +
      `<button class="cbt-btn cbt-primary" ${dis} onclick="window.Combat._act({action:'end_turn',actor:'${actorEsc}'})">⏭️ Encerrar Turno</button>`;
    btnEl.innerHTML = html;
  }

  function showTargets(kind, opts) {
    const snap = _last;
    if (!snap) return;
    _pick = Object.assign({ kind }, opts || {});
    const tgtEl = document.getElementById('cbt-targets');
    const cur = (snap.combatants || []).find(c => c.is_current);
    const live = (snap.combatants || []).filter(c =>
      !isOut(c.status) && c.name !== (cur && cur.name));
    const titulo = kind === 'attack'
      ? `Alvo de ${esc(_pick.weapon || 'ataque')}:`
      : (kind === 'ability' ? `Alvo de ${esc(_pick.ability || 'habilidade')}:` : 'Alvo:');
    tgtEl.innerHTML =
      `<div class="cbt-tgt-title">${titulo}</div>`
      + `<div class="cbt-picker-btns">`
      + live.map(c =>
          `<button class="cbt-btn" onclick="window.Combat._target('${esc(c.name).replace(/'/g,"\\'")}')">${esc(c.name)}</button>`
        ).join('')
      + `<button class="cbt-btn cbt-cancel" onclick="window.Combat._cancel()">✕ Cancelar</button>`
      + `</div>`;
    tgtEl.classList.remove('hidden');
  }

  // ---- Loop / sincronização ---------------------------------------
  let _last = null;

  function _pill() { return document.getElementById('cbt-reopen'); }

  async function refresh(snap) {
    _last = snap;
    _mode = snap.combat_mode || 'narrado';
    updateModeUI();
    const pill = _pill();

    if (snap.combat_mode !== 'tela') {
      if (_open) close(false);
      if (pill) pill.classList.add('hidden');
      _userClosed = false;
      return;
    }

    if (snap.is_active) {
      // Reabre sozinho — exceto se o usuário fechou a tela de propósito.
      if (!_open && !_userClosed) openOverlay();
      if (_open) {
        if (pill) pill.classList.add('hidden');
        render(snap);
        if (!snap.current_is_party && !_busy) {
          clearTimeout(_autoTimer);
          if (_autoGuard++ < 80) {
            _autoTimer = setTimeout(() => act({ action: 'enemy' }), 650);
          }
        } else {
          _autoGuard = 0;
        }
      } else if (_userClosed && pill) {
        // Tela fechada pelo usuário, mas o combate segue ativo → pílula.
        pill.classList.remove('hidden');
      }
    } else if (snap.result && _open) {
      clearTimeout(_autoTimer); _autoGuard = 0;
      render(snap);
      renderResult(snap.result);
    } else if (_open) {
      close(true);
    } else {
      // Combate inativo e a tela já fechada — limpa o estado.
      _userClosed = false;
      if (pill) pill.classList.add('hidden');
    }
  }

  function renderResult(res) {
    const tgtEl = document.getElementById('cbt-targets');
    tgtEl.classList.add('hidden'); tgtEl.innerHTML = '';

    const isWin = res.outcome === 'vitoria';
    const lista = (arr, fallen) => (arr || []).map(c =>
      `<li><span>${esc(c.name)}</span>`
      + `<span>${fallen ? esc(c.status) : (c.hp + '/' + c.hp_max)}</span></li>`
    ).join('') || '<li class="cbt-empty">—</li>';

    const ov = document.getElementById('cbt-end-overlay');
    ov.innerHTML = `
      <div class="cbt-end-modal">
        <h2 class="cbt-result-title ${isWin ? 'win' : 'lose'}">
          ${isWin ? '🏆 ' : '💀 '}${esc(res.title || (isWin ? 'Vitória!' : 'Fim do combate'))}
        </h2>
        <div class="cbt-result-cols">
          <div class="cbt-end-col">
            <h3>De pé</h3>
            <ul class="cbt-end-list">${lista(res.sobreviventes, false)}</ul>
          </div>
          <div class="cbt-end-col cbt-end-col-foe">
            <h3>Caídos</h3>
            <ul class="cbt-end-list">${lista(res.caidos, true)}</ul>
          </div>
        </div>
        <div class="cbt-end-actions">
          <button class="cbt-btn" onclick="window.Combat._closeOnly()">Apenas fechar</button>
          <button class="cbt-btn cbt-primary" onclick="window.Combat._continue()">Continuar a história ▶</button>
        </div>
      </div>`;
    ov.classList.remove('hidden');
  }

  async function sync() {
    if (_busy) return;
    try {
      const snap = await getState();
      if (snap && typeof snap === 'object') await refresh(snap);
    } catch (_) { /* silencioso — tenta de novo no próximo refreshMemory */ }
  }

  async function act(payload) {
    if (_busy) return;
    _busy = true;
    clearTimeout(_autoTimer);
    try {
      renderActionBar(_last || {});
      const res = await doAction(payload);
      if (res && !res.ok && res.message) {
        const first = String(res.message).split('\n')[0].slice(0, 110);
        if (window.showToast) window.showToast(first);
      }
      _busy = false;
      if (res && res.snapshot) await refresh(res.snapshot);
      else await sync();
    } catch (e) {
      _busy = false;
      if (window.showToast) window.showToast('Falha de conexão no combate.');
    }
  }

  // ---- Abrir / fechar ---------------------------------------------
  function openOverlay() {
    ensureDom();
    document.getElementById('combat-overlay').classList.remove('hidden');
    document.body.classList.add('combat-on');
    _open = true; _autoGuard = 0;
  }

  function close(triggerRecap) {
    clearTimeout(_autoTimer);
    const el = document.getElementById('combat-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('combat-on');
    _open = false;
    if (triggerRecap && !_ending) {
      _ending = true;
      finishWithNarration().finally(() => { _ending = false; });
    }
  }

  async function finishWithNarration() {
    try {
      const r = await api('/api/combat/recap');
      const txt = (r && r.text) ? r.text : '[COMBATE RESOLVIDO NA TELA TÁTICA] Narre a luta e o saque.';
      if (typeof window.sendToAgent === 'function') {
        await window.sendToAgent(txt, true);
      }
    } catch (_) {
      if (window.showToast) window.showToast('Combate encerrado.');
    }
  }

  // ---- Ações expostas aos botões ----------------------------------
  function _sel(kind) {
    if (_busy) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    const tgtEl = document.getElementById('cbt-targets');

    if (kind === 'attack') {
      const armas = (cur && cur.armas) || [];
      if (!armas.length) return showTargets('attack', { weapon: 'Ataque desarmado' });
      tgtEl.innerHTML =
        `<div class="cbt-tgt-title">Arma:</div>`
        + `<div class="cbt-picker-btns">`
        + armas.map(w =>
            `<button class="cbt-btn" title="${esc(w.origem)}" onclick="window.Combat._selWeapon('${esc(w.nome).replace(/'/g,"\\'")}')">`
            + `⚔️ ${esc(w.nome)}<small> · ${esc(w.origem)}</small></button>`
          ).join('')
        + `<button class="cbt-btn cbt-cancel" onclick="window.Combat._cancel()">✕ Cancelar</button>`
        + `</div>`;
      tgtEl.classList.remove('hidden');
      return;
    }

    const eco = (_last || {}).turn_economy || {};
    const dis = slot => (slot === 'bonus' ? eco.bonus_usada : eco.acao_usada) ? 'disabled' : '';
    const tag = slot => slot === 'bonus' ? 'Bônus' : 'Ação';

    if (kind === 'item') {
      const itens = (cur && cur.itens_combate) || [];
      if (!itens.length) {
        if (window.showToast) window.showToast('Nenhum item utilizável no combate.');
        return;
      }
      tgtEl.innerHTML =
        `<div class="cbt-tgt-title">Item:</div>`
        + `<div class="cbt-picker-btns">`
        + itens.map(it =>
            `<button class="cbt-btn" ${dis(it.tipo_acao)} title="${esc(it.descricao)}" `
            + `onclick="window.Combat._selItem('${esc(it.nome).replace(/'/g,"\\'")}','${esc(it.kind)}')">`
            + `🧪 ${esc(it.nome)} <small>×${it.qtd}${it.dice ? ' · ' + esc(it.dice) : ''}</small>`
            + ` <em class="cbt-eco-tag eco-${it.tipo_acao}">${tag(it.tipo_acao)}</em></button>`
          ).join('')
        + `<button class="cbt-btn cbt-cancel" onclick="window.Combat._cancel()">✕ Cancelar</button>`
        + `</div>`;
      tgtEl.classList.remove('hidden');
      return;
    }

    // Habilidade: escolhe qual, depois alvo
    const habs = (cur && cur.habilidades) || [];
    if (!habs.length) {
      if (window.showToast) window.showToast('Nenhuma habilidade ativa disponível.');
      return;
    }
    tgtEl.innerHTML =
      `<div class="cbt-tgt-title">Habilidade:</div>`
      + `<div class="cbt-picker-btns">`
      + habs.map(h => {
          const mode = h.target_mode || 'single';
          const modeTag = mode === 'self' ? ' <small>· em si</small>'
                        : mode === 'pool' ? ' <small>· área</small>' : '';
          return `<button class="cbt-btn" ${dis(h.tipo_acao)} title="${esc(h.descricao)}" `
            + `onclick="window.Combat._selHab('${esc(h.nome).replace(/'/g,"\\'")}','${mode}')">`
            + `✨ ${esc(h.nome)}${h.custo_mana ? ` <small>(${h.custo_mana}✨)</small>` : ''}`
            + `${h.dado ? ` <small>· ${esc(h.dado)}</small>` : ''}`
            + `${modeTag}`
            + ` <em class="cbt-eco-tag eco-${h.tipo_acao}">${tag(h.tipo_acao)}</em></button>`;
        }).join('')
      + `<button class="cbt-btn cbt-cancel" onclick="window.Combat._cancel()">✕ Cancelar</button>`
      + `</div>`;
    tgtEl.classList.remove('hidden');
  }

  function _selItem(name, kind) {
    if (_busy) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    if (kind === 'heal') {
      _pick = { kind: 'item', item: name };
      const tgtEl = document.getElementById('cbt-targets');
      const alvos = (_last.combatants || []).filter(c =>
        c.is_party && (c.status || '').toLowerCase() !== 'morto');
      const lista = alvos.length
        ? alvos.map(c =>
            `<button class="cbt-btn" onclick="window.Combat._target('${esc(c.name).replace(/'/g,"\\'")}')">`
            + `${esc(c.name)} <small>${c.hp}/${c.hp_max}</small></button>`).join('')
        : `<button class="cbt-btn" onclick="window.Combat._target('${esc(cur.name).replace(/'/g,"\\'")}')">${esc(cur.name)} (em si)</button>`;
      tgtEl.innerHTML =
        `<div class="cbt-tgt-title">Curar quem:</div>`
        + `<div class="cbt-picker-btns">${lista}`
        + `<button class="cbt-btn cbt-cancel" onclick="window.Combat._cancel()">✕ Cancelar</button>`
        + `</div>`;
      tgtEl.classList.remove('hidden');
    } else {
      act({ action: 'item', actor: cur.name, item: name });
    }
  }
  function _selWeapon(name) { showTargets('attack',  { weapon: name }); }
  function _selHab(name, mode) {
    if (_busy) return;
    const cur = (_last && _last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    if (mode === 'self') {
      act({ action: 'ability', actor: cur.name, ability: name, target: cur.name });
      return;
    }
    if (mode === 'pool') {
      act({ action: 'ability', actor: cur.name, ability: name, target: '' });
      return;
    }
    showTargets('ability', { ability: name });
  }
  function _target(name) {
    if (_busy || !_pick) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    if (_pick.kind === 'attack')
      act({ action: 'attack', actor: cur.name, target: name, weapon: _pick.weapon || '' });
    else if (_pick.kind === 'item')
      act({ action: 'item', actor: cur.name, item: _pick.item, target: name });
    else
      act({ action: 'ability', actor: cur.name, ability: _pick.ability, target: name });
  }
  function _continue() { close(true); }   // dispara recap + narração
  function _closeOnly() { close(false); } // apenas fecha

  function _dismiss() {
    // Fecha a tela SEM encerrar o combate — libera o acesso ao menu/sair
    // do jogo. O combate fica pausado e pode ser retomado pela pílula.
    _userClosed = true;
    clearTimeout(_autoTimer);
    close(false);
    const pill = _pill();
    if (pill && _last && _last.is_active && _last.combat_mode === 'tela') {
      pill.classList.remove('hidden');
    }
  }
  function _reopen() {
    _userClosed = false;
    const pill = _pill();
    if (pill) pill.classList.add('hidden');
    sync();   // reabre e re-renderiza o estado atual
  }
  function _cancel() {
    const t = document.getElementById('cbt-targets');
    if (t) { t.classList.add('hidden'); t.innerHTML = ''; }
    _pick = null;
  }
  function _free() {
    close(false);
    const inp = document.getElementById('chat-input');
    if (inp) { inp.focus(); }
    if (window.showToast)
      window.showToast('Descreva sua ação livre no chat — o Mestre vai arbitrar.');
  }

  // ---- Toggle de modo (sidebar) -----------------------------------
  function updateModeUI() {
    document.querySelectorAll('#combat-mode-toggle .cm-opt').forEach(b =>
      b.classList.toggle('active', b.dataset.mode === _mode));
    const hint = document.getElementById('combat-mode-hint');
    if (hint) hint.textContent = _mode === 'tela'
      ? 'As lutas abrem a tela tática; a IA narra o resultado no fim.'
      : 'A IA narra cada turno da luta no chat (padrão).';
  }

  window.setCombatMode = async function (mode) {
    try {
      const r = await api('/api/combat/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      if (r && r.ok) {
        _mode = r.mode;
        updateModeUI();
        if (window.showToast)
          window.showToast(mode === 'tela' ? 'Combate: tela tática' : 'Combate: narrado pela IA');
        sync();
      }
    } catch (_) {
      if (window.showToast) window.showToast('Não foi possível mudar o modo.');
    }
  };

  // ---- API pública -------------------------------------------------
  window.Combat = {
    sync,
    _sel, _selHab, _selWeapon, _selItem, _target, _cancel, _free,
    _act: act,
    _continue, _closeOnly, _dismiss, _reopen,
    _close: () => close(false),
  };

  document.addEventListener('DOMContentLoaded', () => { ensureDom(); sync(); });
})();
