// ═══════════════════════════════════════════════════════════════════
//  combat.js — Tela de combate tática (estilo JRPG)
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

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (document.getElementById('combat-overlay')) return;
    const o = document.createElement('div');
    o.id = 'combat-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="cbt-frame">
        <div id="cbt-top">
          <div id="cbt-round">Rodada 1</div>
          <div id="cbt-order"></div>
        </div>
        <div id="cbt-enemies"></div>
        <div id="cbt-stage"><div id="cbt-vs">⚔️</div></div>
        <div id="cbt-party"></div>
        <div id="cbt-log"></div>
        <div id="cbt-actionbar">
          <div id="cbt-prompt">Aguardando…</div>
          <div id="cbt-buttons"></div>
          <div id="cbt-targets" class="hidden"></div>
        </div>
      </div>`;
    document.body.appendChild(o);
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
  function bar(cur, max, cls) {
    const m = max > 0 ? Math.max(0, Math.min(100, (cur / max) * 100)) : 0;
    return `<div class="cbt-bar"><div class="cbt-bar-fill ${cls}" style="width:${m}%"></div></div>`;
  }
  function card(c) {
    const out = ['morto', 'inconsciente', 'estabilizado', 'fugiu', 'exilado']
      .includes((c.status || '').toLowerCase());
    const conds = (c.condicoes || []).map(x => `<span class="cbt-cond">${esc(x)}</span>`).join('');
    return `<div class="cbt-card ${c.is_current ? 'cbt-cur' : ''} ${out ? 'cbt-out' : ''}">
      <div class="cbt-name">${esc(c.name)} ${c.is_current ? '<span class="cbt-arrow">▶</span>' : ''}</div>
      <div class="cbt-meta">${esc(c.classe || '')}${c.nivel ? ' Nv.' + c.nivel : ''} · 🛡️${c.ca}</div>
      <div class="cbt-hpline">❤️ ${c.hp}/${c.hp_max}</div>
      ${bar(c.hp, c.hp_max, 'hp')}
      ${c.mp_max > 0 ? `<div class="cbt-hpline">✨ ${c.mp}/${c.mp_max}</div>${bar(c.mp, c.mp_max, 'mp')}` : ''}
      ${conds ? `<div class="cbt-conds">${conds}</div>` : ''}
      ${out ? `<div class="cbt-status-tag">${esc(c.status)}</div>` : ''}
    </div>`;
  }

  function render(snap) {
    ensureDom();
    const enemies = (snap.combatants || []).filter(c => !c.is_party);
    const party   = (snap.combatants || []).filter(c => c.is_party);

    document.getElementById('cbt-round').textContent = `Rodada ${snap.round || 1}`;
    document.getElementById('cbt-order').innerHTML = (snap.order || [])
      .map((n, i) => `<span class="cbt-ord ${i === snap.turn_index ? 'on' : ''}">${esc(n)}</span>`)
      .join('<span class="cbt-ord-sep">›</span>');
    document.getElementById('cbt-enemies').innerHTML = enemies.map(card).join('') || '<div class="cbt-empty">—</div>';
    document.getElementById('cbt-party').innerHTML   = party.map(card).join('')   || '<div class="cbt-empty">—</div>';

    const log = (snap.log || []).slice(-8).map(e =>
      `<div class="cbt-logline">[R${e.round}] ${esc(e.msg || e.type || '')}</div>`).join('');
    const lg = document.getElementById('cbt-log');
    lg.innerHTML = log;
    lg.scrollTop = lg.scrollHeight;

    renderActionBar(snap);
  }

  function renderActionBar(snap) {
    const promptEl = document.getElementById('cbt-prompt');
    const btnEl    = document.getElementById('cbt-buttons');
    const tgtEl    = document.getElementById('cbt-targets');
    tgtEl.classList.add('hidden'); tgtEl.innerHTML = ''; _pick = null;

    const cur = (snap.combatants || []).find(c => c.is_current);
    if (!cur) { promptEl.textContent = '…'; btnEl.innerHTML = ''; return; }

    if (!snap.current_is_party) {
      promptEl.innerHTML = `Turno de <b>${esc(snap.current)}</b> (inimigo)…`;
      btnEl.innerHTML = '';
      return;
    }

    // Economia 5e (Ação + Bônus) do turno atual.
    const eco       = snap.turn_economy || {};
    const acaoUsed  = !!eco.acao_usada;
    const bonusUsed = !!eco.bonus_usada;
    const econHtml =
      `<span class="cbt-econ">`
      + `<span class="cbt-slot ${acaoUsed ? 'used' : ''}">Ação ${acaoUsed ? '●' : '○'}</span>`
      + `<span class="cbt-slot ${bonusUsed ? 'used' : ''}">Bônus ${bonusUsed ? '●' : '○'}</span>`
      + `</span>`;
    promptEl.innerHTML =
      `Sua vez: <b>${esc(snap.current)}</b> — ${econHtml}`;

    const dis = _busy ? 'disabled' : '';
    const actorEsc = esc(cur.name).replace(/'/g, "\\'");
    // Atacar / Defender / Fugir são AÇÃO → só se ação livre.
    const acaoDis = (acaoUsed || _busy) ? 'disabled' : '';

    const hasAcaoAbil  = (cur.habilidades || []).some(h => h.tipo_acao !== 'bonus');
    const hasBonusAbil = (cur.habilidades || []).some(h => h.tipo_acao === 'bonus');
    const hasAcaoItem  = (cur.itens_combate || []).some(i => i.tipo_acao !== 'bonus');
    const hasBonusItem = (cur.itens_combate || []).some(i => i.tipo_acao === 'bonus');
    // O botão "Habilidade"/"Item" só faz sentido se houver opção compatível
    // com algum slot AINDA disponível.
    const habUsable  = (hasAcaoAbil && !acaoUsed) || (hasBonusAbil && !bonusUsed);
    const itemUsable = (hasAcaoItem && !acaoUsed) || (hasBonusItem && !bonusUsed);

    let html =
      `<button ${acaoDis} onclick="window.Combat._sel('attack')">⚔️ Atacar <small>(Ação)</small></button>`;
    if ((cur.habilidades || []).length) {
      const d = (habUsable && !_busy) ? '' : 'disabled';
      html += `<button ${d} onclick="window.Combat._sel('ability')">✨ Habilidade</button>`;
    }
    if ((cur.itens_combate || []).length) {
      const d = (itemUsable && !_busy) ? '' : 'disabled';
      html += `<button ${d} onclick="window.Combat._sel('item')">🧪 Item</button>`;
    }
    html +=
      `<button ${acaoDis} onclick="window.Combat._act({action:'defend',actor:'${actorEsc}'})">🛡️ Defender <small>(Ação)</small></button>` +
      `<button ${acaoDis} onclick="window.Combat._act({action:'flee',actor:'${actorEsc}'})">💨 Fugir <small>(Ação)</small></button>` +
      `<button ${dis} onclick="window.Combat._free()">💬 Ação Livre</button>` +
      `<button ${dis} class="cbt-primary" onclick="window.Combat._act({action:'end_turn',actor:'${actorEsc}'})">⏭️ Encerrar Turno</button>`;
    btnEl.innerHTML = html;
  }

  function showTargets(kind, opts) {
    const snap = _last;
    if (!snap) return;
    _pick = Object.assign({ kind }, opts || {});
    const tgtEl = document.getElementById('cbt-targets');
    const cur = (snap.combatants || []).find(c => c.is_current);
    // Alvos = combatentes vivos diferentes do atual
    const live = (snap.combatants || []).filter(c =>
      !['morto', 'inconsciente', 'estabilizado', 'fugiu', 'exilado'].includes((c.status || '').toLowerCase())
      && c.name !== (cur && cur.name));
    const titulo = kind === 'attack'
      ? `Alvo de ${esc(_pick.weapon || 'ataque')}:`
      : (kind === 'ability' ? `Alvo de ${esc(_pick.ability || 'habilidade')}:` : 'Alvo:');
    tgtEl.innerHTML = `<div class="cbt-tgt-title">${titulo}</div>` + live.map(c =>
      `<button onclick="window.Combat._target('${esc(c.name).replace(/'/g,"\\'")}')">${esc(c.name)}</button>`
    ).join('') + `<button class="cbt-cancel" onclick="window.Combat._cancel()">✕</button>`;
    tgtEl.classList.remove('hidden');
  }

  // ---- Loop / sincronização ---------------------------------------
  let _last = null;

  async function refresh(snap) {
    _last = snap;
    _mode = snap.combat_mode || 'narrado';
    updateModeUI();

    if (snap.combat_mode !== 'tela') { if (_open) close(false); return; }

    if (snap.is_active) {
      if (!_open) openOverlay();
      render(snap);
      // Turno de inimigo → resolve sozinho (sem LLM), com teto de segurança.
      if (_open && !snap.current_is_party && !_busy) {
        clearTimeout(_autoTimer);
        if (_autoGuard++ < 80) {
          _autoTimer = setTimeout(() => act({ action: 'enemy' }), 650);
        }
      } else {
        _autoGuard = 0;
      }
    } else if (snap.result && _open) {
      // Combate acabou e há um resultado capturado → NÃO fecha bruscamente.
      // Mostra o painel de fim com botão "Continuar" (o usuário decide
      // quando voltar à narrativa).
      clearTimeout(_autoTimer); _autoGuard = 0;
      render(snap);
      renderResult(snap.result);
    } else if (_open) {
      // Fim sem resultado capturado (edge raro): fecha + dispara recap.
      close(true);
    }
  }

  function renderResult(res) {
    const promptEl = document.getElementById('cbt-prompt');
    const btnEl    = document.getElementById('cbt-buttons');
    const tgtEl    = document.getElementById('cbt-targets');
    tgtEl.classList.add('hidden'); tgtEl.innerHTML = '';

    const isWin = res.outcome === 'vitoria';
    const lista = (arr, kind) => (arr || []).map(c => {
      const lado = c.is_party
        ? '<span class="cbt-res-lado cbt-res-grp">grupo</span>'
        : '<span class="cbt-res-lado cbt-res-foe">inimigo</span>';
      return `<li>${lado} <b>${esc(c.name)}</b>`
           + ` <span class="cbt-res-st">${esc(c.status)}</span>`
           + ` <span class="cbt-res-hp">${c.hp}/${c.hp_max} HP</span></li>`;
    }).join('') || '<li class="cbt-empty">—</li>';

    promptEl.innerHTML =
      `<div class="cbt-result-title ${isWin ? 'win' : 'lose'}">`
      + (isWin ? '🏆 ' : '💀 ')
      + esc(res.title || (isWin ? 'Vitória!' : 'Fim do combate'))
      + `</div>`
      + `<div class="cbt-result-cols">`
      +   `<div><div class="cbt-res-h">De pé</div><ul>${lista(res.sobreviventes)}</ul></div>`
      +   `<div><div class="cbt-res-h">Caídos</div><ul>${lista(res.caidos)}</ul></div>`
      + `</div>`;

    btnEl.innerHTML =
      `<button class="cbt-primary" onclick="window.Combat._continue()">Continuar a história ▶</button>`
      + `<button onclick="window.Combat._closeOnly()">Apenas fechar</button>`;
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
        // Recusa real (turno errado, slot já usado, alvo inválido…).
        // Mostra a primeira linha amigável.
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
      // Submenu de ARMAS: lista o que o personagem pode usar agora.
      const armas = (cur && cur.armas) || [];
      if (!armas.length) return showTargets('attack', { weapon: 'Ataque desarmado' });
      tgtEl.innerHTML = `<div class="cbt-tgt-title">Arma:</div>`
        + armas.map(w =>
            `<button title="${esc(w.origem)}" onclick="window.Combat._selWeapon('${esc(w.nome).replace(/'/g,"\\'")}')">`
            + `⚔️ ${esc(w.nome)}<small> · ${esc(w.origem)}</small></button>`
          ).join('')
        + `<button class="cbt-cancel" onclick="window.Combat._cancel()">✕</button>`;
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
      tgtEl.innerHTML = `<div class="cbt-tgt-title">Item:</div>` + itens.map(it =>
        `<button ${dis(it.tipo_acao)} title="${esc(it.descricao)}" `
        + `onclick="window.Combat._selItem('${esc(it.nome).replace(/'/g,"\\'")}','${esc(it.kind)}')">`
        + `🧪 ${esc(it.nome)} <small>×${it.qtd}${it.dice ? ' · ' + esc(it.dice) : ''}</small>`
        + ` <em class="cbt-eco-tag eco-${it.tipo_acao}">${tag(it.tipo_acao)}</em></button>`
      ).join('') + `<button class="cbt-cancel" onclick="window.Combat._cancel()">✕</button>`;
      tgtEl.classList.remove('hidden');
      return;
    }

    // Habilidade: escolhe qual, depois alvo
    const habs = (cur && cur.habilidades) || [];
    if (!habs.length) {
      if (window.showToast) window.showToast('Nenhuma habilidade ativa disponível.');
      return;
    }
    tgtEl.innerHTML = `<div class="cbt-tgt-title">Habilidade:</div>` + habs.map(h =>
      `<button ${dis(h.tipo_acao)} title="${esc(h.descricao)}" `
      + `onclick="window.Combat._selHab('${esc(h.nome).replace(/'/g,"\\'")}')">`
      + `✨ ${esc(h.nome)}${h.custo_mana ? ` <small>(${h.custo_mana}✨)</small>` : ''}`
      + `${h.dado ? ` <small>· ${esc(h.dado)}</small>` : ''}`
      + ` <em class="cbt-eco-tag eco-${h.tipo_acao}">${tag(h.tipo_acao)}</em></button>`
    ).join('') + `<button class="cbt-cancel" onclick="window.Combat._cancel()">✕</button>`;
    tgtEl.classList.remove('hidden');
  }

  function _selItem(name, kind) {
    if (_busy) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    if (kind === 'heal') {
      // Escolhe quem recebe a cura (grupo, incluindo inconscientes).
      _pick = { kind: 'item', item: name };
      const tgtEl = document.getElementById('cbt-targets');
      const alvos = (_last.combatants || []).filter(c =>
        c.is_party && (c.status || '').toLowerCase() !== 'morto');
      const lista = alvos.length
        ? alvos.map(c =>
            `<button onclick="window.Combat._target('${esc(c.name).replace(/'/g,"\\'")}')">`
            + `${esc(c.name)} <small>${c.hp}/${c.hp_max}</small></button>`).join('')
        : `<button onclick="window.Combat._target('${esc(cur.name).replace(/'/g,"\\'")}')">${esc(cur.name)} (em si)</button>`;
      tgtEl.innerHTML = `<div class="cbt-tgt-title">Curar quem:</div>` + lista
        + `<button class="cbt-cancel" onclick="window.Combat._cancel()">✕</button>`;
      tgtEl.classList.remove('hidden');
    } else {
      // Item genérico: aplica no próprio usuário, sem picker.
      act({ action: 'item', actor: cur.name, item: name });
    }
  }
  function _selWeapon(name) { showTargets('attack',  { weapon: name }); }
  function _selHab(name)    { showTargets('ability', { ability: name }); }
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
  function _cancel() {
    const t = document.getElementById('cbt-targets');
    if (t) { t.classList.add('hidden'); t.innerHTML = ''; }
    _pick = null;
  }
  function _free() {
    // Ação criativa → volta ao chat narrado; a LLM arbitra (make_skill_check).
    // A tela reabre sozinha no próximo sync se o combate seguir ativo.
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
    _continue, _closeOnly,
    _close: () => close(false),
  };

  document.addEventListener('DOMContentLoaded', () => { ensureDom(); sync(); });
})();
