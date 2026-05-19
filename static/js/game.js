// ═══════════════════════════════════════
//  game.js  —  usado em game.html
// ═══════════════════════════════════════
let waiting = false;
let maxRPD = parseInt(localStorage.getItem('rpg_max_rpd') || '500');

// Reseta contadores se o dia mudou (meia-noite no timezone do utilizador)
(function resetQuotaIfNewDay() {
  const today = new Date().toLocaleDateString('sv'); // "YYYY-MM-DD" sem depender de locale
  const stored = localStorage.getItem('rpg_quota_date');
  if (stored !== today) {
    localStorage.setItem('rpg_quota_date', today);
    localStorage.setItem('rpg_daily_reqs', '0');
    localStorage.setItem('rpg_total_tokens', '0');
  }
})();

let sessionRequests = parseInt(localStorage.getItem('rpg_daily_reqs') || '0');
let sessionTokens = parseInt(localStorage.getItem('rpg_total_tokens') || '0');

// ── D&D: ferramentas que envolvem dados — tratadas de forma especial ──
const DICE_TOOL_NAMES = new Set([
  'roll_dice', 'attack_roll', 'make_skill_check', 'use_ability',
  'roll_death_save', 'grant_xp', 'short_rest', 'long_rest',
  'modify_hp', 'modify_mana',
]);

const STATE_TOOLS = new Set([
  'modify_hp', 'modify_mana', 'attack_roll', 'use_ability',
  'next_turn', 'roll_initiative', 'end_combat',
  'apply_condition', 'remove_condition', 'short_rest', 'long_rest',
  'roll_death_save', 'equip_item', 'unequip_item', 'set_stat',
  'modify_currency', 'grant_xp',
  // Faltavam: mudam turno/HP/status mas não atualizavam a barra/sidebar
  'execute_npc_turn', 'spawn_monster', 'recruit_character',
  'resolve_saving_throw',
]);

const COND_ICONS = {
  'cego': '👁️', 'envenenado': '🟢', 'amedrontado': '😨',
  'paralisado': '⚡', 'atordoado': '💫', 'inconsciente': '💀',
  'enfeitiçado': '🔮', 'exausto': '😓', 'deitado': '⬇️',
  'invisível': '👻', 'petrificado': '🪨', 'amaldiçoado': '🖤',
  'restrito': '🔗', 'em chamas': '🔥', 'sangrando': '🩸',
};

function _condInfo(cd) {
  if (typeof cd === 'object' && cd !== null) return { nome: cd.nome || '?', dur: cd.duracao };
  return { nome: String(cd), dur: undefined };
}

let _pendingDiceTools = [];
let _diceTrayOpen = false;

document.addEventListener('DOMContentLoaded', async () => {
  if (!requireAuth()) return;

  const raw = localStorage.getItem('rpg_session');
  if (!raw) { window.location.href = '/menu.html'; return; }

  let session;
  try { session = JSON.parse(raw); } catch (_) { window.location.href = '/menu.html'; return; }

  document.getElementById('sb-campaign').textContent = session.campaign || '—';
  document.getElementById('sb-model').textContent = session.model || '—';
  document.getElementById('mobile-title').textContent = session.campaign || '—';

  if (session.campaign_config) applyCampaignConfig(session.campaign_config);

  if (session.model_limits) {
    maxRPD = session.model_limits.rpd;
    localStorage.setItem('rpg_max_rpd', maxRPD);
  }
  updateQuotaUI();

  if (session.has_history && session.conversation_history?.length) {
    renderHistory(session.conversation_history);
    appendSystem('<p>Sessão retomada — a recordar os eventos anteriores...</p>');
  } else {
    appendSystem('<p>Nova sessão iniciada.</p>');
  }

  document.getElementById('sidebar-overlay').addEventListener('click', () => toggleSidebar(true));
  document.getElementById('edit-overlay').addEventListener('click', function (e) { if (e.target === this) closeEditModal(); });
  document.addEventListener('click', e => {
    if (!e.target.closest('#cmd-menu') && !e.target.closest('#chat-input')) closeCmdMenu();
  });

  refreshMemory();
  document.getElementById('chat-input').focus();

  if (session.opening) {
    await sendToAgent(session.opening, false);
  }
});

function showLoadingScreen(message) {
  const overlay = document.createElement('div');
  overlay.id = 'loading-overlay';
  overlay.style.cssText = `
    position: fixed; inset: 0; background: rgba(26, 26, 26, 0.9); z-index: 99999;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    backdrop-filter: blur(4px); color: var(--ink-user); font-family: 'Playfair Display', serif; font-size: 20px;
  `;
  overlay.innerHTML = `<div>${message}</div>`;
  document.body.appendChild(overlay);
}

// ═══════════════════════════════════════
//  Autocomplete de comandos /
// ═══════════════════════════════════════
const COMMANDS = [
  { cmd: '/ajuda', arg: '', desc: 'Exibe todos os comandos' },
  { cmd: '/personagens', arg: '', desc: 'Lista personagens na memória' },
  { cmd: '/locais', arg: '', desc: 'Lista locais registrados' },
  { cmd: '/grupo', arg: '', desc: 'Lista membros do grupo' },
  { cmd: '/eventos', arg: '', desc: 'Mostra os últimos 5 eventos' },
  { cmd: '/flags', arg: '', desc: 'Variáveis de estado da campanha' },
  { cmd: '/contexto', arg: '', desc: 'Dump completo da memória' },
  { cmd: '/diario', arg: '', desc: 'Entradas do diário' },
  { cmd: '/resumo', arg: '', desc: 'Recapitulação da história' },
  { cmd: '/exportar', arg: '', desc: 'Exporta diário como .md' },
  { cmd: '/salvar local', arg: '<nome>', desc: 'Registra um local' },
  { cmd: '/salvar personagem', arg: '<nome>', desc: 'Registra um personagem' },
  { cmd: '/salvar evento', arg: '<desc>', desc: 'Registra um evento' },
];

let _cmdIdx = -1, _menuOpen = false;

function openCmdMenu(filter = '') {
  const norm = filter.toLowerCase();
  const matches = COMMANDS.filter(c => c.cmd.startsWith(norm) || norm === '/');
  if (!matches.length) { closeCmdMenu(); return; }

  const menu = document.getElementById('cmd-menu');
  const items = document.getElementById('cmd-menu-items');
  items.innerHTML = matches.map((c, i) => `
    <div class="cmd-item" data-i="${i}" onclick="selectCmd(${i})" onmouseenter="hlCmd(${i})">
      <span class="cmd-item-name">${c.cmd}</span>
      ${c.arg ? `<span class="cmd-item-arg">${c.arg}</span>` : ''}
      <span class="cmd-item-desc">${c.desc}</span>
    </div>
  `).join('');
  menu.classList.remove('hidden'); menu.style.display = 'block';
  _menuOpen = true; _cmdIdx = -1; menu._matches = matches;
}

function closeCmdMenu() {
  const m = document.getElementById('cmd-menu');
  if (m) { m.style.display = 'none'; } _menuOpen = false; _cmdIdx = -1;
}

function hlCmd(i) {
  _cmdIdx = i;
  document.querySelectorAll('.cmd-item').forEach((el, j) => el.classList.toggle('active', j === i));
}

function selectCmd(i) {
  const matches = document.getElementById('cmd-menu')._matches || [];
  if (i < 0 || i >= matches.length) return;
  const c = matches[i], input = document.getElementById('chat-input');
  if (c.arg) { input.value = c.cmd + ' '; closeCmdMenu(); input.focus(); autoResize(input); }
  else { input.value = c.cmd; closeCmdMenu(); sendMessage(); }
}

function onInputChange(el) {
  autoResize(el);
  if (el.value.startsWith('/')) openCmdMenu(el.value);
  else closeCmdMenu();
}

function autoResize(el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 140) + 'px'; }

function handleKey(e) {
  if (_menuOpen) {
    const items = document.querySelectorAll('.cmd-item');
    if (e.key === 'ArrowDown') { e.preventDefault(); hlCmd(Math.min(_cmdIdx + 1, items.length - 1)); items[_cmdIdx]?.scrollIntoView({ block: 'nearest' }); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); hlCmd(Math.max(_cmdIdx - 1, 0)); items[_cmdIdx]?.scrollIntoView({ block: 'nearest' }); return; }
    if (e.key === 'Tab' || (e.key === 'Enter' && _cmdIdx >= 0)) { e.preventDefault(); selectCmd(_cmdIdx >= 0 ? _cmdIdx : 0); return; }
    if (e.key === 'Escape') { e.preventDefault(); closeCmdMenu(); return; }
  }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

// ═══════════════════════════════════════
//  Chat — envio
// ═══════════════════════════════════════
async function sendMessage() {
  if (waiting) return;
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = ''; autoResize(input);
  if (text.startsWith('/')) { const handled = await handleSlash(text); if (handled) return; }
  appendUser(text);
  await sendToAgent(text, true);
}

async function sendToAgent(text, registrar) {
  if (waiting) return;

  waiting = true;
  setInputDisabled(true);

  const typId = appendTyping();
  let pendingTools = [];

  try {
    const res = await authFetch(`${API}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, registrar })
    });

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    const processLine = (line) => {
      if (!line.startsWith('data: ')) return;
      let ev;
      try {
        ev = JSON.parse(line.slice(6));
      } catch (_) {
        // Linha SSE truncada/malformada — ignora e continua o stream
        // em vez de abortar toda a resposta com "Erro de conexão".
        return;
      }
      handleEvent(ev);
    };

    const handleEvent = (ev) => {

        if (ev.type === 'quota') {
          // Verifica se passou a meia-noite durante a sessão
          const today = new Date().toLocaleDateString('sv');
          if (localStorage.getItem('rpg_quota_date') !== today) {
            localStorage.setItem('rpg_quota_date', today);
            sessionRequests = 0;
            sessionTokens = 0;
          }
          sessionRequests++;
          sessionTokens += (ev.content.total_tokens || 0);
          localStorage.setItem('rpg_daily_reqs', sessionRequests);
          localStorage.setItem('rpg_total_tokens', sessionTokens);
          updateQuotaUI();
        }
        else if (ev.type === 'tool_call') {
          if (DICE_TOOL_NAMES.has(ev.tool.name)) _pendingDiceTools.push(ev.tool);
          else pendingTools.push(ev.tool);
        }
        else if (ev.type === 'tool_result') {
          removeTyping(typId);
          appendDiceResultLog(ev.tool_name, ev.content);
          if (STATE_TOOLS.has(ev.tool_name)) refreshMemory();
        }
        else if (ev.type === 'correction') {
          const n = ev.violations?.length || 1;
          const corrId = appendTyping();
          updateTyping(corrId, `🔄 Verificador: ${n} violação(ões) detectada(s) — corrigindo...`);
          window._correctionTypId = corrId;
        }
        else if (ev.type === 'text') {
          if (window._correctionTypId) { removeTyping(window._correctionTypId); window._correctionTypId = null; }
          if (pendingTools.length) { appendToolLog(pendingTools); pendingTools = []; }
          if (_pendingDiceTools.length) {
            const diceNames = _pendingDiceTools.map(t => t.name);
            _pendingDiceTools = [];
            removeTyping(typId);
            renderDiceFromResponse(ev.content, diceNames);
            return;
          }
          removeTyping(typId);
          appendMaster(ev.content);
        }
        else if (ev.type === 'retrying') {
          updateTyping(typId, ev.content);
        }
        else if (ev.type === 'violations') {
          renderViolations(ev.violations);
        }
        else if (ev.type === 'level_up') {
          const list = (ev.characters || []).join(', ');
          if (list) {
            appendSystem(`<div class="cmd-list-box" style="text-align:center;">`
              + `<div class="cmd-list-title" style="border:none;margin:0;">⬆️ Subiu de Nível</div>`
              + `<div style="font-size:13px;color:var(--ink-user);">${escapeHtml(list)}</div></div>`);
            if (typeof showToast === 'function') showToast('⬆️ ' + list);
          }
        }
        else if (ev.type === 'error') {
          removeTyping(typId);
          appendSystem(`<p>Erro: ${ev.content}</p>`);
        }
        else if (ev.type === 'done') {
          removeTyping(typId);
          refreshMemory();
        }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();   // mantém a última linha (possivelmente parcial)

      for (const line of lines) processLine(line);
    }

    // Processa o que sobrou no buffer (último evento sem '\n' final)
    const tail = buf + dec.decode();
    if (tail.trim()) {
      for (const line of tail.split('\n')) processLine(line);
    }
  } catch (e) {
    removeTyping(typId);
    appendSystem(`<p>Erro de conexão: ${e.message}</p>`);
  } finally {
    removeTyping(typId);
    waiting = false;
    setInputDisabled(false);
    document.getElementById('chat-input').focus();
  }
}

function updateQuotaUI() {
  const reqEl = document.getElementById('stat-req');
  const tokEl = document.getElementById('stat-tokens');
  const tokElSb = document.getElementById('sb-stat-tokens');
  const barEl = document.getElementById('rpm-bar');

  if (reqEl) reqEl.textContent = `${sessionRequests} / ${maxRPD}`;
  const tokStr = sessionTokens.toLocaleString();
  if (tokEl) tokEl.textContent = tokStr;
  if (tokElSb) tokElSb.textContent = tokStr;

  if (barEl) {
    const dailyPercent = Math.min((sessionRequests / maxRPD) * 100, 100);
    barEl.style.width = dailyPercent + '%';
    barEl.style.backgroundColor = dailyPercent > 85 ? 'var(--red)' : 'var(--ink-user)';
  }
}

// ═══════════════════════════════════════
//  Comandos
// ═══════════════════════════════════════
async function handleSlash(raw) {
  const cmd = raw.trim().toLowerCase();

  if (cmd === '/ajuda') {
    const isDnd = window._lastMem ? (window._lastMem.dnd_mode === true || window._lastMem.campaign_type === 'dnd') : false;
    const dndText = isDnd ? `
      <div class="cmd-list-item" style="margin-top:10px;"><b style="font-family:'Playfair Display',serif;">⚔️ Comandos D&D</b></div>
      <div class="cmd-list-item"><b>/ficha [nome]</b> · Atributos, CA e equipamentos</div>
      <div class="cmd-list-item"><b>/inventario [nome]</b> · Itens e moedas</div>
      <div class="cmd-list-item"><b>/habilidades [nome]</b> · Magias e poderes</div>
      <div class="cmd-list-item"><b>/status</b> · HP e Mana rápido do grupo</div>
      <div class="cmd-list-item"><b>/condicoes [nome]</b> · Condições ativas</div>
      <div class="cmd-list-item"><b>/combate</b> · Iniciativa e turno atual</div>
      <div class="cmd-list-item"><b>/rolar &lt;XdY+Z&gt;</b> · Rola dado local (ex: /rolar 2d6+3)</div>` : '';

    const html = `
    <div class="cmd-list-box">
      <div class="cmd-list-title">📜 Comandos Disponíveis</div>
      <div class="cmd-list-item"><b>/personagens</b> · NPCs e status</div>
      <div class="cmd-list-item"><b>/locais</b> · Locais registrados</div>
      <div class="cmd-list-item"><b>/grupo</b> · Companheiros</div>
      <div class="cmd-list-item"><b>/flags</b> · Decisões e estados</div>
      <div class="cmd-list-item"><b>/contexto</b> · Memória completa</div>
      <div class="cmd-list-item"><b>/diario</b> · Crônicas</div>
      <div class="cmd-list-item"><b>/resumo</b> · Recapitulação</div>
      <div class="cmd-list-item"><b>/exportar</b> · Exportar .md</div>
      <hr style="border:none;border-top:1px solid var(--page-edge);margin:10px 0;">
      <div class="cmd-list-item"><b>/salvar local &lt;nome&gt;</b></div>
      <div class="cmd-list-item"><b>/salvar personagem &lt;nome&gt;</b></div>
      <div class="cmd-list-item"><b>/salvar evento &lt;desc&gt;</b></div>
      ${dndText}
    </div>`;
    appendSystem(html); return true;
  }

  if (['/personagens', '/locais', '/flags', '/grupo', '/eventos', '/contexto'].includes(cmd)) {
    const mem = await (await authFetch(`${API}/api/memory`)).json(); let html = '';
    mem.quest_flags = mem.quest_flags || {};
    mem.party = mem.party || []; mem.characters = mem.characters || [];
    mem.events = mem.events || []; mem.locations = mem.locations || [];
    
    if (cmd === '/personagens') {
      const sep = '<hr style="border:none;border-top:1px dashed var(--page-edge);margin:8px 0;">';
      const renderChar = c => `<div class="cmd-list-item"><b>${c.name}</b> (${c.status || 'vivo'})<br><span style="color:var(--text-muted);font-size:13px;">${c.description || ''}</span></div>`;
      const partyList  = (mem.party || []).map(renderChar).join(sep);
      const npcList    = (mem.characters || []).map(renderChar).join(sep);
      const partyHtml  = partyList ? `<div class="cmd-list-title" style="font-size:11px;margin-top:10px;border:none;padding:0 0 4px;">🫂 GRUPO</div>${partyList}` : '';
      const npcHtml    = npcList   ? `<div class="cmd-list-title" style="font-size:11px;margin-top:${partyList?'14px':'0'};border:none;padding:0 0 4px;">👤 OUTROS</div>${npcList}` : '';
      html = `<div class="cmd-list-box"><div class="cmd-list-title">👥 Personagens na Memória</div>${partyHtml || ''}${npcHtml || ''}${!partyList && !npcList ? 'Nenhum personagem.' : ''}</div>`;
    }
    else if (cmd === '/locais') {
      const list = (mem.locations || []).map(l => `<div class="cmd-list-item"><b>${l.name}</b><br><span style="color:var(--text-muted);font-size:13px;">${l.description}</span></div>`).join('<hr style="border:none;border-top:1px dashed var(--page-edge);margin:8px 0;">');
      html = `<div class="cmd-list-box"><div class="cmd-list-title">📍 Locais Registrados</div>${list || 'Nenhum local.'}</div>`;
    }
    else if (cmd === '/flags') {
      const fl = Object.entries(mem.quest_flags);
      const list = fl.map(([k, v]) => `<div class="cmd-list-item"><b>${k}</b> ➜ ${v}</div>`).join('');
      html = `<div class="cmd-list-box"><div class="cmd-list-title">🚩 Flags de História</div>${list || 'Nenhuma flag.'}</div>`;
    }
    else if (cmd === '/grupo') {
      const list = mem.party.map(p => `<div class="cmd-list-item"><b>${p.name}</b> (${p.role})<br><span style="color:var(--text-muted);font-size:13px;">${p.notes || ''}</span></div>`).join('<hr style="border:none;border-top:1px dashed var(--page-edge);margin:8px 0;">');
      html = `<div class="cmd-list-box"><div class="cmd-list-title">🫂 Grupo de Aventureiros</div>${list || 'Grupo vazio.'}</div>`;
    }
    else if (cmd === '/eventos') {
      const list = mem.events.slice(-5).map(e => `<div class="cmd-list-item"><b>#${e.index} — ${e.location}</b><br><span style="color:var(--text-muted);font-size:13px;">${e.summary}</span></div>`).join('<hr style="border:none;border-top:1px dashed var(--page-edge);margin:8px 0;">');
      html = `<div class="cmd-list-box"><div class="cmd-list-title">📜 Últimos 5 Eventos</div>${list || 'Nenhum evento.'}</div>`;
    }
    else if (cmd === '/contexto') {
      html = `<div class="cmd-list-box"><div class="cmd-list-title">📖 Memória Completa</div><div class="cmd-list-item"><b>Capítulo:</b> ${mem.chapter} · <b>Local:</b> ${mem.current_location}</div><div class="cmd-list-item" style="margin-top:10px;">${mem.story_summary}</div></div>`;
    }
    appendSystem(html); return true;
  }

  if (cmd === '/diario') {
    const mem = await (await authFetch(`${API}/api/memory`)).json();
    mem.diary = mem.diary || [];
    const list = [...mem.diary].reverse().slice(0, 5).map(d => `<div class="cmd-list-item"><b>Cap.${d.chapter} — ${d.title}</b><br><span style="color:var(--text-muted);font-size:13px;">${d.content}</span></div>`).join('<hr style="border:none;border-top:1px dashed var(--page-edge);margin:8px 0;">');
    appendSystem(`<div class="cmd-list-box"><div class="cmd-list-title">🔖 Diário (Últimas Entradas)</div>${list || 'Diário vazio.'}</div>`);
    return true;
  }

  if (cmd === '/exportar') {
    const d = await (await authFetch(`${API}/api/diary/export`, { method: 'POST' })).json();
    appendSystem(`<div class="cmd-list-box" style="text-align:center;"><div class="cmd-list-title" style="border:none;margin:0;">✅ Diário Exportado</div><div style="font-size:13px;color:var(--ink-main);">Ficheiro: <b>${d.path.split('/').pop()}</b></div></div>`); 
    return true;
  }

  async function _getDndChars(targetName) {
    const mem = await (await authFetch(`${API}/api/memory`)).json();
    if (!(mem.dnd_mode === true || mem.campaign_type === 'dnd')) return { mem, chars: null };
    const allChars = [...(mem.party || []), ...(mem.characters || [])];
    let chars;
    if (targetName) {
      // Busca por nome em todos os personagens (grupo + NPCs), com ou sem sheet
      const c = allChars.find(ch => ch.name?.toLowerCase() === targetName);
      chars = c ? [c] : [];
    } else {
      // Sem argumento: mostra todos com ficha D&D completa (grupo + inimigos)
      chars = allChars.filter(c => c.sheet);
    }
    return { mem, chars };
  }

  function _mod(val) { const m = Math.floor((val - 10) / 2); return (m >= 0 ? '+' : '') + m; }

  if (cmd.startsWith('/ficha')) {
    const target = raw.trim().split(' ').slice(1).join(' ').toLowerCase();
    const { mem, chars } = await _getDndChars(target);
    if (!chars) { appendSystem('<p>Comando exclusivo do modo D&D.</p>'); return true; }
    if (!chars.length) { appendSystem(`<p>${target ? `Nenhuma ficha encontrada para '${target}'.` : 'Nenhum membro possui ficha D&D.'}</p>`); return true; }

    const text = chars.map(c => {
      // Personagem sem ficha D&D completa (NPC simples registrado no combate)
      if (!c.sheet) {
        const hpAtual = c.vida_atual ?? c.hp ?? '?';
        const hpMax   = c.vida_max  ?? c.hp_max ?? '?';
        return `<div class="cmd-sheet">
          <div class="cmd-sheet-title">👤 ${c.name}</div>
          <div class="cmd-sheet-sub">${c.description || 'NPC'} · Status: ${c.status || 'vivo'}</div>
          <div class="cmd-sheet-bars"><span>❤️ ${hpAtual}/${hpMax} HP</span></div>
        </div>`;
      }
      const s = c.sheet; const eq = s.equipamentos || {};
      const conds = s.condicoes?.length ? s.condicoes.map(cd => cd.nome || cd).join(', ') : 'Nenhuma';
      const hpBar = s.vida_max > 0 ? Math.round((s.vida_atual / s.vida_max) * 10) : 0;
      const hpVis = `<span class="bar-fill">${'█'.repeat(hpBar)}</span><span class="bar-empty">${'█'.repeat(10-hpBar)}</span>`;

      return `<div class="cmd-sheet">
        <div class="cmd-sheet-title">🛡️ Ficha — ${c.name}</div>
        <div class="cmd-sheet-sub">${s.classe === 'npc'
          ? `${s.raca ? s.raca.charAt(0).toUpperCase()+s.raca.slice(1) : 'NPC'} · CR ${s.cr ?? '—'} · HP ${s.vida_max}`
          : `Nível ${s.nivel} ${s.classe} (${s.raca}) · XP: ${s.xp}/${s.xp_proximo}`}</div>
        <div class="cmd-sheet-bars">
          <span>❤️ ${hpVis} ${s.vida_atual}/${s.vida_max} HP</span>
          <span>✨ ${s.mana_atual}/${s.mana_max} Mana</span>
          <span>🛡️ CA ${s.ca}</span>
        </div>
        <div class="cmd-sheet-stats">
          <div><span class="cmd-label">FOR</span><br>${s.forca}(${_mod(s.forca)})</div>
          <div><span class="cmd-label">DES</span><br>${s.destreza}(${_mod(s.destreza)})</div>
          <div><span class="cmd-label">CON</span><br>${s.constituicao}(${_mod(s.constituicao)})</div>
          <div><span class="cmd-label">INT</span><br>${s.inteligencia}(${_mod(s.inteligencia)})</div>
          <div><span class="cmd-label">SAB</span><br>${s.sabedoria}(${_mod(s.sabedoria)})</div>
          <div><span class="cmd-label">CAR</span><br>${s.carisma}(${_mod(s.carisma)})</div>
        </div>
        <div class="cmd-sheet-details">
          <span class="cmd-label">Equipado:</span> Arma: ${eq.arma_principal || '—'} · Armadura: ${eq.armadura || '—'} · Escudo: ${eq.escudo || '—'} · Amuleto: ${eq.amuleto || '—'}<br>
          <span class="cmd-label">Condições:</span> ${conds} | <span class="cmd-label">Saves de morte:</span> ✅ ${s.death_saves_sucessos || 0} / ❌ ${s.death_saves_falhas || 0}
        </div>
      </div>`;
    }).join('<hr style="border:none;border-top:1px dashed var(--page-edge);margin:15px 0;">');
    appendSystem(`<div class="cmd-list-box">${text}</div>`); return true;
  }

  if (cmd.startsWith('/inventario')) {
    const target = raw.trim().split(' ').slice(1).join(' ').toLowerCase();
    const { mem, chars } = await _getDndChars(target);
    if (!chars) { appendSystem('<p>Comando exclusivo do modo D&D.</p>'); return true; }
    if (!chars.length) { appendSystem(`<p>${target ? `Nenhuma ficha encontrada para '${target}'.` : 'Nenhum membro possui ficha D&D.'}</p>`); return true; }

    const text = chars.map(c => {
      const s = c.sheet; const inv = c.inventario || [];
      const items = inv.length ? inv.map(i => `<li><b>${i.nome}</b> ×${i.qtd} <span style="color:var(--text-muted);font-size:12px;">${i.descricao ? `— ${i.descricao}` : ''}</span></li>`).join('') : '<li>Bolsa vazia</li>';
      return `<div class="cmd-sheet" style="padding-bottom:0;border:none;">
        <div class="cmd-sheet-title">🎒 Inventário — ${c.name}</div>
        <div class="cmd-sheet-bars" style="margin-bottom:10px;">🪙 <b>${s.ouro||0}</b> Ouro · 🥈 <b>${s.prata||0}</b> Prata · 🟤 <b>${s.cobre||0}</b> Cobre</div>
        <ul class="cmd-sheet-list">${items}</ul>
      </div>`;
    }).join('<hr style="border:none;border-top:1px dashed var(--page-edge);margin:15px 0;">');
    appendSystem(`<div class="cmd-list-box">${text}</div>`); return true;
  }

  if (cmd.startsWith('/habilidades')) {
    const target = raw.trim().split(' ').slice(1).join(' ').toLowerCase();
    const { mem, chars } = await _getDndChars(target);
    if (!chars) { appendSystem('<p>Comando exclusivo do modo D&D.</p>'); return true; }
    if (!chars.length) { appendSystem(`<p>${target ? `Nenhuma ficha encontrada para '${target}'.` : 'Nenhum membro possui ficha D&D.'}</p>`); return true; }

    const text = chars.map(c => {
      const habs = c.habilidades || [];
      const list = habs.length ? habs.map(h => `<div class="cmd-list-item"><b>${h.nome}</b> <span style="font-size:12px;color:var(--text-muted);">(Dado: ${h.dado} · ${h.custo_mana} mana)</span><br><span style="font-size:13px;color:var(--text-muted);">${h.descricao}</span></div>`).join('') : '<div class="cmd-list-item">Nenhuma habilidade aprendida.</div>';
      const mana = c.sheet ? ` — ✨ Mana: <b>${c.sheet.mana_atual}/${c.sheet.mana_max}</b>` : '';
      return `<div class="cmd-sheet-title" style="margin-bottom:10px;">⚡ Habilidades — ${c.name}${mana}</div>${list}`;
    }).join('<hr style="border:none;border-top:1px dashed var(--page-edge);margin:15px 0;">');
    appendSystem(`<div class="cmd-list-box">${text}</div>`); return true;
  }

  if (cmd === '/status') {
    const { mem, chars } = await _getDndChars('');
    if (!chars) { appendSystem('<p>Comando exclusivo do modo D&D.</p>'); return true; }
    if (!chars.length) { appendSystem('<p>Nenhum membro possui ficha D&D.</p>'); return true; }

    const lines = chars.map(c => {
      const s = c.sheet;
      const hpPct = s.vida_max > 0 ? Math.round((s.vida_atual / s.vida_max) * 100) : 0;
      const hpIcon = hpPct > 60 ? '🟢' : hpPct > 30 ? '🟡' : '🔴';
      const conds = s.condicoes?.length ? ` <span style="color:var(--text-dim);font-size:12px;">⚠️ ${s.condicoes.map(cd => cd.nome || cd).join(', ')}</span>` : '';
      return `<div class="cmd-list-item" style="display:flex;justify-content:space-between;border-bottom:1px dashed var(--page-edge);padding-bottom:5px;margin-bottom:8px;">
        <span>${hpIcon} <b>${c.name}</b>${conds}</span>
        <span style="font-size:13px;">❤️ ${s.vida_atual}/${s.vida_max} HP &nbsp; ✨ ${s.mana_atual}/${s.mana_max} Mana &nbsp; 🛡️ CA ${s.ca}</span>
      </div>`;
    });
    appendSystem(`<div class="cmd-list-box"><div class="cmd-list-title">⚔️ Status do Grupo</div>${lines.join('')}</div>`); return true;
  }

  if (cmd.startsWith('/condicoes')) {
    const target = raw.trim().split(' ').slice(1).join(' ').toLowerCase();
    const { mem, chars } = await _getDndChars(target);
    if (!chars) { appendSystem('<p>Comando exclusivo do modo D&D.</p>'); return true; }
    if (!chars.length) { appendSystem(`<p>${target ? `Nenhuma ficha encontrada para '${target}'.` : 'Nenhum membro possui ficha D&D.'}</p>`); return true; }

    const lines = chars.map(c => {
      const conds = c.sheet?.condicoes || [];
      if (!conds.length) return `<div class="cmd-list-item"><b>${c.name}</b> — ✅ Sem condições ativas</div>`;
      return `<div class="cmd-list-item"><b>${c.name}</b> — ${conds.map(cd => `<span style="color:var(--ink-sys);">🔴 ${cd.nome || cd}${cd.duracao !== undefined ? ` (${cd.duracao}t)` : ''}</span>`).join(' · ')}</div>`;
    });
    appendSystem(`<div class="cmd-list-box"><div class="cmd-list-title">🔴 Condições Ativas</div>${lines.join('')}</div>`); return true;
  }

  if (cmd === '/combate') {
    const mem = window._lastMem || await (await authFetch(`${API}/api/memory`)).json();
    const cs = mem.combat_state;
    if (!cs || !cs.is_active) {
      appendSystem('<div class="cmd-list-box"><div class="cmd-list-title">⚔️ Combate</div><div style="text-align:center;">Nenhum combate em andamento.</div></div>');
      return true;
    }
    const order = cs.initiative_order || [];
    const idx   = cs.current_turn_index ?? 0;
    const list  = order.map((n, i) => {
      const arrow = i === idx ? ' <b style="color:var(--ink-sys);">◀ VEZ ATUAL</b>' : i < idx ? ' <span style="text-decoration:line-through;color:var(--text-muted);">(já agiu)</span>' : '';
      return `<div class="cmd-list-item" style="padding-left:15px;">${i + 1}. ${n}${arrow}</div>`;
    }).join('');
    appendSystem(`<div class="cmd-list-box"><div class="cmd-list-title">⚔️ Ordem de Iniciativa — Rodada ${cs.round}</div><div style="margin-bottom:10px;font-size:14px;text-align:center;"><b>Vez de:</b> <span style="color:var(--ink-user);">${order[idx] || '?'}</span></div>${list}</div>`);
    return true;
  }

  const mRolar = raw.match(/^\/rolar\s+(.+)/i);
  if (mRolar) {
    const formula = mRolar[1].trim();
    const rollRe = /^(\d*)d(\d+)([+-]\d+)?$/i;
    const match  = formula.replace(/\s+/g, '').match(rollRe);
    if (!match) { appendSystem(`<p>⚠️ Fórmula inválida: <b>${formula}</b></p>`); return true; }
    
    const numDice = parseInt(match[1] || '1');
    const sides   = parseInt(match[2]);
    const bonus   = parseInt(match[3] || '0');
    if (numDice < 1 || numDice > 20 || sides < 2 || sides > 100) { appendSystem('<p>⚠️ Limites: 1–20 dados, d2–d100.</p>'); return true; }
    
    const rolls  = Array.from({ length: numDice }, () => Math.floor(Math.random() * sides) + 1);
    const rawSum = rolls.reduce((a, b) => a + b, 0);
    const total  = rawSum + bonus;
    const bonStr = bonus !== 0 ? ` ${bonus >= 0 ? '+' : ''}${bonus}` : '';
    const rollStr = numDice > 1 ? `[${rolls.join(' + ')}]` : `${rolls[0]}`;
    const isCrit   = sides === 20 && numDice === 1 && rolls[0] === 20;
    const isFumble = sides === 20 && numDice === 1 && rolls[0] === 1;
    const tag = isCrit ? '<br><span class="sys-highlight">CRÍTICO NATURAL</span>' : isFumble ? '<br><span class="sys-highlight">FALHA CRÍTICA</span>' : '';
    const row = document.createElement('div'); row.className = 'msg-row system';
    row.innerHTML = `
      <div class="sys-card">
        <div class="sys-card-badge" style="color:var(--ink-user); border-color:var(--ink-user);">🎲 Rolagem Local: ${formula}</div>
        <div class="sys-card-body">
          Resultado: <span class="sys-number">${rollStr}</span>${bonStr} = <strong>${total}</strong>${tag}
        </div>
        <div style="font-family:'Lora',serif; font-size:11px; color:var(--text-dim); margin-top:10px; text-align:center; font-style:italic;">
          Não enviado ao Mestre.
        </div>
      </div>`;
    document.getElementById('chat-history').appendChild(row); scrollDown();
    return true;
  }

  if (cmd === '/resumo') {
    appendUser('📜 Solicitando recapitulação...');
    await sendToAgent('Faça um resumo dramático e imersivo de todos os eventos importantes. Use get_full_context para garantir precisão.', false);
    return true;
  }

  const mLocal = raw.match(/^\/salvar\s+local\s+(.+)/i);
  const mPerson = raw.match(/^\/salvar\s+personagem\s+(.+)/i);
  const mEvento = raw.match(/^\/salvar\s+evento\s+(.+)/i);

  if (mLocal) { appendSystem(`<p>Registrando local "${mLocal[1]}"...</p>`); await sendToAgent(`Salve o local "${mLocal[1]}" usando save_location com todos os detalhes mencionados. Confirme o que foi registrado.`, true); return true; }
  if (mPerson) { appendSystem(`<p>Registrando "${mPerson[1]}"...</p>`); await sendToAgent(`Salve o personagem "${mPerson[1]}" usando save_character com todos os detalhes. Confirme o que foi registrado.`, true); return true; }
  if (mEvento) { appendSystem(`<p>Registrando evento...</p>`); await sendToAgent(`Salve o evento "${mEvento[1]}" usando save_event. Confirme o que foi registrado.`, true); return true; }

  return false;
}

// ═══════════════════════════════════════
//  UI de Ferramentas / Combate (Onde a Mágica RPG Acontece)
// ═══════════════════════════════════════

const TOOL_META = {
  get_character: '👤', get_location: '📍', get_scene_context: '🧭', get_full_context: '📚',
  get_recent_events: '📜', get_flag: '🚩', get_diary: '📖', list_characters: '👥',
  list_locations: '🗺️', list_party: '🫂', list_flags: '🚩', save_character: '💾',
  save_location: '💾', save_event: '💾', set_flag: '🔖', add_diary_entry: '✍️',
  update_character_status: '🔄', update_story_summary: '🔄', update_world_state: '🔄',
  add_party_member: '➕', remove_party_member: '➖', clear_flag: '🗑️',
  roll_dice: '🎲', attack_roll: '⚔️', make_skill_check: '🎯', use_ability: '⚡',
  roll_death_save: '💀', modify_hp: '❤️', modify_mana: '✨', grant_xp: '⭐',
  short_rest: '🛌', long_rest: '🌙',
  create_character_sheet: '📋', get_character_sheet: '📋', get_combat_status: '⚔️',
  add_item: '📦', remove_item: '🗑️', list_inventory: '📦', learn_ability: '📖',
  set_stat: '🔧', equip_item: '🗡️', unequip_item: '🗡️', apply_condition: '🔴',
  remove_condition: '🟢', modify_currency: '💰',
};

const TOOL_LABEL = {
  get_character: 'lendo personagem', get_location: 'lendo local', get_scene_context: 'verificando cena',
  get_full_context: 'carregando contexto', get_recent_events: 'consultando eventos', get_flag: 'verificando flag',
  get_diary: 'lendo diário', list_characters: 'listando personagens', list_locations: 'listando locais',
  list_party: 'listando grupo', list_flags: 'listando flags', save_character: 'salvando personagem',
  save_location: 'salvando local', save_event: 'salvando evento', set_flag: 'definindo flag',
  add_diary_entry: 'escrevendo no diário', update_character_status: 'atualizando personagem',
  update_story_summary: 'atualizando resumo', update_world_state: 'atualizando mundo',
  add_party_member: 'adicionando ao grupo', remove_party_member: 'removendo do grupo', clear_flag: 'removendo flag',
  roll_dice: 'rolando dado', attack_roll: 'resolvendo ataque', make_skill_check: 'teste de habilidade',
  use_ability: 'usando habilidade', roll_death_save: 'teste de morte',
  modify_hp: 'atualizando vida', modify_mana: 'atualizando mana', grant_xp: 'concedendo XP',
  short_rest: 'descanso curto', long_rest: 'descanso longo',
  create_character_sheet: 'criando ficha', get_character_sheet: 'lendo ficha',
  get_combat_status: 'status de combate', add_item: 'adicionando item',
  remove_item: 'removendo item', list_inventory: 'listando inventário',
  learn_ability: 'aprendendo habilidade', set_stat: 'ajustando atributo',
  equip_item: 'equipando item', unequip_item: 'desequipando item',
  apply_condition: 'aplicando condição', remove_condition: 'removendo condição',
  modify_currency: 'atualizando moedas',
};

function appendToolLog(tools) {
  if (!tools.length) return;
  const c = document.getElementById('chat-history'); const w = document.createElement('div'); w.className = 'tool-log';
  tools.forEach(t => {
    const icon = TOOL_META[t.name] || '⚙️'; const label = TOOL_LABEL[t.name] || t.name;
    const arg = t.args && Object.keys(t.args).length ? `"${String(Object.values(t.args)[0]).substring(0, 40)}"` : '';
    const el = document.createElement('div'); el.className = `tool-item ${t.kind}`;
    el.title = JSON.stringify(t.args, null, 2);
    el.innerHTML = `<span class="tool-item-icon">${icon}</span><span>${label}</span>${arg ? `<span class="tool-item-args">${arg}</span>` : ''}`;
    w.appendChild(el);
  });
  c.appendChild(w); scrollDown();
}

function splitDiceAndNarrative(text) {
  const lines = text.split('\n');
  const raw = [], narrative = [];
  let inRawBlock = true;
  for (const line of lines) {
    if (inRawBlock && /^[\s]*(?:🎲|⚔️|✨|❤️|⚡|💀|🌙|🛌|⭐|\s+d20=|\s+Dano:|\s+Custo:|\s+Cura:|\s+Vida:|[✅❌🌟💀⚠️])/.test(line)) {
      raw.push(line);
    } else {
      inRawBlock = false;
      narrative.push(line);
    }
  }
  return { raw: raw.join('\n').trim(), narrative: narrative.join('\n').trim() };
}

function renderDiceFromResponse(text, diceToolNames) {
  const { raw, narrative } = splitDiceAndNarrative(text);
  
  if (raw) {
    appendDiceResultLog(diceToolNames[0] || 'roll_dice', raw);
    if (narrative) appendMaster(narrative);
  } else if (text && text.trim()) {
    // CORREÇÃO APLICADA: Se a IA não mandou o formato de dados no começo, é apenas a narração fluida do Mestre!
    appendMaster(text.trim());
  }
}

// Converte markdown básico em HTML (bold, italic, code, listas simples)
function _parseMd(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/gs, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/gs, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>');
}

function appendDiceResultLog(toolName, content) {
  const labels = {
    attack_roll:      { badge: '⚔️ Ação de Combate',              color: 'var(--ink-sys)' },
    make_skill_check: { badge: '🎯 Teste de Habilidade',           color: 'var(--ink-user)' },
    roll_dice:        { badge: '🎲 Rolagem de Dados',              color: 'var(--ink-user)' },
    use_ability:      { badge: '⚡ Magia / Habilidade',            color: '#7b5ea7' },
    roll_death_save:  { badge: '💀 Resistência à Morte',           color: 'var(--ink-sys)' },
    modify_hp:        { badge: '❤️ Pontos de Vida',                color: '#c05858' },
    modify_mana:      { badge: '✨ Mana',                          color: '#4a6bbf' },
    grant_xp:         { badge: '⭐ Experiência',                   color: '#a07828' },
    short_rest:       { badge: '🛌 Descanso Curto',                color: 'var(--green)' },
    long_rest:        { badge: '🌙 Descanso Longo',                color: 'var(--green)' },
    advance_turn:     { badge: '⏩ Turno Avançado',                color: 'var(--ink-sys)' },
  };
  const cfg = labels[toolName] || { badge: '⚙️ Sistema', color: 'var(--text-muted)' };

  // Parse markdown + destacar padrões RPG
  let body = _parseMd(content.trim())
    .replace(/(d\d+=|Dano:|Cura:|Custo:|Vida:|CA:|Total:|XP:|Mana:)\s*([+\-]?\d+)/gi,
      '<strong>$1</strong> <span class="sys-number">$2</span>')
    .replace(/(\d+d\d+(?:[+\-]\d+)?\s*[:=]\s*\[?[^\]<br>]+\]?)/gi,
      '<span class="sys-number" style="font-size:18px;">$1</span>')
    .replace(/(CRÍTICO NATURAL|FALHA CRÍTICA|Com Vantagem|Com Desvantagem)/gi,
      '<span class="sys-highlight">$1</span>');

  const row = document.createElement('div');
  row.className = 'msg-row system';
  row.innerHTML = `
    <div class="sys-card">
      <div class="sys-card-badge" style="color:${cfg.color}; border-color:${cfg.color};">
        ${cfg.badge}
      </div>
      <div class="sys-card-body">${body}</div>
    </div>`;

  document.getElementById('chat-history').appendChild(row);
  scrollDown();
}

function toggleDiceTray() {
  if (waiting) return;
  _diceTrayOpen = !_diceTrayOpen;
  const tray = document.getElementById('dice-tray');
  const btn  = document.getElementById('dice-tray-btn');
  tray.classList.toggle('hidden', !_diceTrayOpen);
}

function rollPlayerDie(sides) {
  if (waiting) return;
  const modifier = parseInt(document.getElementById('dice-modifier')?.value) || 0;
  const rawRoll  = Math.floor(Math.random() * sides) + 1;
  const total    = rawRoll + modifier;
  const isCrit   = sides === 20 && rawRoll === 20;
  const isFumble = sides === 20 && rawRoll === 1;

  if (_diceTrayOpen) toggleDiceTray();

  const modStr = modifier !== 0 ? ` ${modifier >= 0 ? '+' : ''}${modifier}` : '';
  const statusLabel = isCrit ? '<br><span class="sys-highlight">CRÍTICO NATURAL</span>' : isFumble ? '<br><span class="sys-highlight">FALHA CRÍTICA</span>' : '';

  const row = document.createElement('div');
  row.className = 'msg-row system';
  row.innerHTML = `
    <div class="sys-card">
      <div class="sys-card-badge" style="color:var(--ink-user); border-color:var(--ink-user);">🎲 Sua Rolagem: 1d${sides}${modStr}</div>
      <div class="sys-card-body">
        <span class="sys-number">${rawRoll}</span>${modStr ? ` <em>(${modStr})</em>` : ''} = <strong>${total}</strong>${statusLabel}
      </div>
      <div style="font-family:'Lora',serif; font-size:11px; color:var(--text-dim); margin-top:10px; text-align:center; font-style:italic;">
        Enviado ao Oráculo 🔒
      </div>
    </div>`;
  document.getElementById('chat-history').appendChild(row); scrollDown();

  const msg = `[DADO DO JOGADOR — rolado pelo sistema, não editável] 1d${sides}${modStr}: rolei ${rawRoll}, total ${total}`;
  sendToAgent(msg, true);
}

function renderHistory(history) {
  history.forEach(e => {
    if (e.role === 'user') appendUser(e.text);
    else if (e.role === 'assistant') {
      const row = document.createElement('div'); row.className = 'msg-row master';
      const b = document.createElement('div'); b.className = 'msg-bubble'; b.style.opacity = '0.75';
      b.innerHTML = marked.parse(processDiceRolls(e.text || ''));
      row.innerHTML = '<div class="msg-label">Mestre</div>'; row.appendChild(b);
      document.getElementById('chat-history').appendChild(row);
    }
  });
  scrollDown();
}

function appendUser(text) {
  const row = document.createElement('div'); row.className = 'msg-row user';
  row.innerHTML = `<div class="msg-label">Você</div><div class="msg-bubble">${escapeHtml(text).replace(/\n/g, '<br>')}</div>`;
  document.getElementById('chat-history').appendChild(row); scrollDown(); return row;
}

function appendMaster(text) {
  if (!text || !text.trim()) return null;
  const row = document.createElement('div'); row.className = 'msg-row master';
  const b = document.createElement('div'); b.className = 'msg-bubble';
  row.innerHTML = '<div class="msg-label">Mestre</div>'; row.appendChild(b);
  document.getElementById('chat-history').appendChild(row);
  typewriter(b, text); return row;
}

function appendSystem(text) {
  const row = document.createElement('div'); row.className = 'msg-row system';
  const b = document.createElement('div'); b.className = 'msg-bubble';
  // Se já for HTML (começa com '<'), usa direto; senão, parseia markdown básico
  b.innerHTML = text.trimStart().startsWith('<') ? text : _parseMd(text);
  row.appendChild(b);
  document.getElementById('chat-history').appendChild(row); scrollDown(); return row;
}

function appendTyping() {
  const id = 'typ-' + Date.now(); const row = document.createElement('div'); row.className = 'msg-row master'; row.id = id;
  row.innerHTML = `<div class="msg-label">Mestre</div><div class="typing-dots"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
  document.getElementById('chat-history').appendChild(row); scrollDown(); return id;
}

function updateTyping(id, msg) {
  const el = document.getElementById(id); if (!el) return;
  el.innerHTML = `<div class="msg-label">Mestre</div><div class="typing-dots"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div><span style="font-size:11px;color:var(--text-muted);margin-left:4px;">${msg}</span></div>`;
  scrollDown();
}

function removeTyping(id) { document.getElementById(id)?.remove(); }

function processDiceRolls(text) {
  if(!text) return '';
  return text.replace(/(🎲[^\n]+)/g, (match) => {
    const isCrit   = /CRÍTICO\s*NATURAL|🌟\s*CRÍTICO|🌟/.test(match);
    const isFumble = /FALHA\s*CRÍTICA|💀\s*FALHA|💀/.test(match);
    const color = isCrit ? 'var(--green)' : isFumble ? 'var(--red)' : 'var(--ink-user)';
    return `<span style="font-weight:600;color:${color};">${match}</span>`;
  });
}

async function typewriter(el, text) {
  el.innerHTML = marked.parse(processDiceRolls(text));
  el.style.opacity = '0';
  let op = 0;
  const t = setInterval(() => { op = Math.min(1, op + 0.08); el.style.opacity = op; scrollDown(); if (op >= 1) clearInterval(t); }, 20);
}

function renderViolations(violations) {
  const el = document.getElementById('sb-violations');
  if (!violations || !violations.length) { 
    el.innerHTML = '<span class="empty-state">Nenhuma violação detetada.</span>'; 
    return; 
  }
  
  if (el.querySelector('.empty-state')) el.innerHTML = '';
  if (el.querySelectorAll('.violation-item').length >= 9) el.innerHTML = '';
  
  const newHtml = violations.map((v, i) => {
    const uid = `viol-${Date.now()}-${i}`;
    return `<div class="violation-item ${v.severity}" id="${uid}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:6px;">
        <div class="violation-rule">${v.rule}</div>
        <button onclick="document.getElementById('${uid}').remove();cleanViolations();" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:14px;padding:0;line-height:1;transition:color 0.15s;" onmouseover="this.style.color='var(--text-main)'" onmouseout="this.style.color='var(--text-muted)'">✕</button>
      </div>
      <div class="violation-msg">${v.message}</div>
      ${v.detail ? `<div class="violation-detail">${v.detail}</div>` : ''}
    </div>`;
  }).join('');
  
  el.innerHTML = newHtml + el.innerHTML;
  if (violations.some(v => v.severity === 'erro')) switchTab('mundo');
}

function cleanViolations() {
  const el = document.getElementById('sb-violations');
  if (!el.querySelector('.violation-item')) {
    el.innerHTML = '<span class="empty-state">Nenhuma violação detetada.</span>';
  }
}

function scrollDown() { const h = document.getElementById('chat-history'); h.scrollTop = h.scrollHeight; }
function setInputDisabled(d) { document.getElementById('chat-input').disabled = d; document.getElementById('send-btn').disabled = d; }

// ═══════════════════════════════════════
//  Sidebar
// ═══════════════════════════════════════
function switchTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`tab-${name}`)?.classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b => { if (b.dataset.tab === name) b.classList.add('active'); });
}

function applyCampaignConfig(cfg) {
  if (!cfg) return;
  window._campaignConfig = cfg;
  const pt = document.getElementById('sb-party-title'); if (pt) pt.textContent = cfg.party_label || 'GRUPO DE AVENTUREIROS';
}

function buildDndCharCard(c, idx, type) {
  const sheet = c.sheet || null;
  const hpCur  = sheet?.vida_atual  !== undefined ? sheet.vida_atual  : '?';
  const hpMax  = sheet?.vida_max    !== undefined ? sheet.vida_max    : '?';
  const manaCur = sheet?.mana_atual !== undefined ? sheet.mana_atual  : null;
  const manaMax = sheet?.mana_max   !== undefined ? sheet.mana_max    : null;
  const ca      = sheet?.ca !== undefined ? sheet.ca : null;
  const condicoes = Array.isArray(sheet?.condicoes) ? sheet.condicoes : [];

  const hpPct = (typeof hpMax === 'number' && hpMax > 0 && typeof hpCur === 'number') ? Math.min(100, Math.max(0, (hpCur / hpMax) * 100)) : 0;
  const manaPct = (typeof manaMax === 'number' && manaMax > 0 && typeof manaCur === 'number') ? Math.min(100, Math.max(0, (manaCur / manaMax) * 100)) : 0;

  const st = (c.status || '').toLowerCase();
  const stCls = st.includes('mort') ? 'dead' : st.includes('desapar') ? 'missing' : '';

  const nameEsc = (c.name || '').replace(/'/g, "\\'");
  const keyEsc  = (c.name || '').toLowerCase().trim().replace(/'/g, "\\'");
  const dataRef = type === 'party' ? `window._lastMem.party[${idx}]` : `window._lastMem.characters[${idx}]`;
  const modalType = (type === 'party' && sheet) ? 'character' : type;

  // Detecta se o personagem tem XP suficiente para upar de nível
  const canLevelUp = sheet
    && typeof sheet.xp === 'number'
    && typeof sheet.xp_proximo === 'number'
    && sheet.xp >= sheet.xp_proximo
    && (sheet.nivel || 1) < 20;

  let html = `<div class="char-card editable" onclick="openEditModal('${modalType}','${keyEsc}',${dataRef})">`;
  html += `<div class="char-name">${escapeHtml(c.name || '')}`;
  html += `<div style="display:flex;align-items:center;gap:6px;">`;
  if (canLevelUp) html += `<span class="levelup-badge" onclick="gameLevelUpClick(event,'${keyEsc}','${type}',${idx})" title="XP suficiente para upar!">⬆️ NÍVEL!</span>`;
  if (c.status) html += `<span class="char-status ${stCls}">${escapeHtml(c.status)}</span>`;
  if (ca !== null) html += `<span class="dnd-ca">🛡️ ${ca}</span>`;
  html += `</div></div>`;

  if (sheet) {
    html += `<div class="stat-bar-wrap"><div class="stat-bar-label"><span>❤️ HP</span><span>${hpCur}/${hpMax}</span></div><div class="stat-bar-track"><div class="stat-bar-fill" style="width:${hpPct}%;background:var(--ink-sys);"></div></div></div>`;
    if (manaMax !== null && manaMax > 0) html += `<div class="stat-bar-wrap"><div class="stat-bar-label"><span>✨ Mana</span><span>${manaCur}/${manaMax}</span></div><div class="stat-bar-track"><div class="stat-bar-fill" style="width:${manaPct}%;background:var(--ink-user);"></div></div></div>`;
    if (condicoes.length) {
      html += `<div class="condition-badges">`;
      condicoes.forEach(cd => {
        const { nome, dur } = _condInfo(cd);
        html += `<span class="condition-badge" style="background:rgba(139,58,58,0.1);color:var(--ink-sys);">${escapeHtml(nome)}${dur !== undefined ? ` (${dur}t)` : ''}</span>`;
      });
      html += `</div>`;
    }
  } else {
    const desc = c.notes || c.description || '';
    if (desc) html += `<div class="char-desc">${escapeHtml(desc.substring(0, 90))}${desc.length > 90 ? '…' : ''}</div>`;
  }
  html += `</div>`;
  return html;
}

function renderTurnTracker(cs) {
  const tracker = document.getElementById('turn-tracker');
  if (!tracker) return;
  if (!cs || !cs.is_active || !cs.initiative_order || !cs.initiative_order.length) { tracker.classList.add('hidden'); return; }

  tracker.classList.remove('hidden');
  const roundEl = document.getElementById('tt-round');
  if (roundEl) roundEl.textContent = `Rodada ${cs.round || 1}`;

  const cards = document.getElementById('tt-cards');
  if (!cards) return;

  const order = cs.initiative_order;
  const idx   = cs.current_turn_index ?? 0;

  cards.innerHTML = order.map((name, i) => {
    const isActive = i === idx;
    const isPast   = i < idx;
    return `<div class="tt-card ${isActive ? 'tt-active' : ''} ${isPast ? 'tt-past' : ''}" title="${escapeHtml(name)}">
      <span class="tt-card-name">${escapeHtml(name)}</span>
      ${isActive ? '<span style="color:var(--ink-sys);margin-left:5px;">▶</span>' : ''}
    </div>`;
  }).join('');
}

async function refreshMemory() {
  try {
    const res = await authFetch(`${API}/api/memory`);
    if (res.status === 401) { clearTokens(); window.location.href = '/login.html'; return; }
    const mem = await res.json();
    if (mem.campaign_config) applyCampaignConfig(mem.campaign_config);
    renderMemory(mem);
  } catch (_) { }
}

function renderMemory(mem) {
  // Normaliza campos que podem faltar em dados antigos/parciais — sem isso,
  // um Object.keys(undefined) abortaria toda a renderização da sidebar.
  mem.quest_flags = mem.quest_flags || {};
  mem.party       = mem.party       || [];
  mem.characters  = mem.characters  || [];
  mem.diary       = mem.diary       || [];
  mem.locations   = mem.locations   || [];
  mem.events      = mem.events      || [];
  window._lastMem = mem;
  document.getElementById('sb-location').textContent = mem.current_location || '—';
  document.getElementById('ws-chapter').textContent = mem.chapter || 1;
  document.getElementById('ws-location').textContent = mem.current_location || '—';
  document.getElementById('sb-summary').textContent = mem.story_summary || 'Nenhum resumo ainda.';

  renderTurnTracker(mem.combat_state);

  const fEl = document.getElementById('sb-flags');
  fEl.innerHTML = !Object.keys(mem.quest_flags).length ? '<span class="empty-state">Nenhuma observação.</span>' :
    Object.entries(mem.quest_flags).map(([k, v]) => `<div class="flag-item editable" onclick="openEditModal('flag','${k}',{key:'${k}',value:'${v.replace(/'/g, "\\'")}'})"><span class="flag-key">${k}</span><span class="flag-val">${v}</span></div>`).join('');

  const isDnd = mem.dnd_mode === true || mem.campaign_type === 'dnd';
  const diceTrayBtn = document.getElementById('dice-tray-btn');
  if (diceTrayBtn) {
    diceTrayBtn.style.display = isDnd ? '' : 'none';
    if (!isDnd) { const tray = document.getElementById('dice-tray'); if (tray && !tray.classList.contains('hidden')) tray.classList.add('hidden'); }
  }

  const dndCmds = ['/ficha', '/inventario', '/habilidades', '/status', '/condicoes', '/combate', '/rolar'];
  COMMANDS.splice(0, COMMANDS.length, ...COMMANDS.filter(c => !dndCmds.includes(c.cmd)));
  if (isDnd) {
    COMMANDS.push(
      { cmd: '/ficha',       arg: '[nome]',  desc: 'Atributos, CA e equipamentos' },
      { cmd: '/inventario',  arg: '[nome]',  desc: 'Itens e moedas do alvo ou grupo' },
      { cmd: '/habilidades', arg: '[nome]',  desc: 'Magias e poderes do alvo ou grupo' },
      { cmd: '/status',      arg: '',        desc: 'HP e Mana rápido de todo o grupo' },
      { cmd: '/condicoes',   arg: '[nome]',  desc: 'Condições ativas no alvo ou grupo' },
      { cmd: '/combate',     arg: '',        desc: 'Ordem de iniciativa e turno atual' },
      { cmd: '/rolar',       arg: '<XdY+Z>', desc: 'Rola uma fórmula local' },
    );
  }

  const pEl = document.getElementById('sb-party');
  pEl.innerHTML = !mem.party.length ? '<span class="empty-state">Nenhum membro ainda.</span>' : mem.party.map((p, i) => {
    if (isDnd) return buildDndCharCard(p, i, 'party');
    return `<div class="char-card editable" onclick="openEditModal('party','${p.name.replace(/'/g, "\\'")}',window._lastMem.party[${i}])"><div class="char-name">${p.name} <span class="char-status">${p.role}</span></div><div class="char-desc">${p.notes || ''}</div></div>`;
  }).join('');

  const cEl = document.getElementById('sb-chars');
  cEl.innerHTML = !mem.characters.length ? '<span class="empty-state">Nenhum personagem ainda.</span>' : mem.characters.map((c, i) => {
    if (isDnd) return buildDndCharCard(c, i, 'character');
    const st = c.status?.toLowerCase() || 'vivo';
    const cls = st.includes('mort') ? 'dead' : st.includes('desapar') ? 'missing' : '';
    return `<div class="char-card editable" onclick="openEditModal('character','${c.name.toLowerCase().replace(/'/g, "\\'")}',window._lastMem.characters[${i}])"><div class="char-name">${c.name}<span class="char-status ${cls}">${c.status}</span></div><div class="char-desc">${(c.description || '').substring(0, 100)}${(c.description || '').length > 100 ? '…' : ''}</div></div>`;
  }).join('');

  const dEl = document.getElementById('sb-diary');
  dEl.innerHTML = !mem.diary.length ? '<span class="empty-state">Diário vazio.</span>' : [...mem.diary].reverse().slice(0, 8).map((d, i) => {
    const ri = mem.diary.length - 1 - i;
    return `<div class="diary-entry editable" onclick="openEditModal('diary',null,window._lastMem.diary[${ri}],${ri})"><div class="diary-entry-title">Cap.${d.chapter} — ${d.title}</div><div class="diary-entry-content">${(d.content || '').substring(0, 160)}${(d.content || '').length > 160 ? '…' : ''}</div></div>`;
  }).join('');

  const lEl = document.getElementById('sb-locs');
  if (lEl) {
    const locs = mem.locations || [];
    lEl.innerHTML = !locs.length ? '<span class="empty-state">Nenhum local ainda.</span>' : locs.map((l, i) => `<div class="char-card editable" onclick="openEditModal('location','${l.name.toLowerCase().replace(/'/g, "\\'")}',window._lastMem.locations[${i}])"><div class="char-name">${l.name}</div><div class="char-desc">${(l.description || '').substring(0, 100)}${(l.description || '').length > 100 ? '…' : ''}</div></div>`).join('');
  }
}

async function openSummaryEdit() {
  const t = document.getElementById('sb-summary').textContent;
  if (t === 'Nenhum resumo ainda.') return;
  openEditModal('world', 'story_summary', { story_summary: t });
}

async function exportDiary() {
  const d = await (await authFetch(`${API}/api/diary/export`, { method: 'POST' })).json();
  showToast('Exportado: ' + d.path);
}

// ═══════════════════════════════════════
//  Dados D&D — replicados de menu.js para uso exclusivo em game.html
// ═══════════════════════════════════════
const GAME_CLASS_DATA = {
  bárbaro:     { hit_die:12, label:'Bárbaro' },
  guerreiro:   { hit_die:10, label:'Guerreiro' },
  paladino:    { hit_die:10, label:'Paladino' },
  patrulheiro: { hit_die:8,  label:'Patrulheiro' },
  bardo:       { hit_die:8,  label:'Bardo' },
  clérigo:     { hit_die:8,  label:'Clérigo' },
  druida:      { hit_die:8,  label:'Druida' },
  monge:       { hit_die:8,  label:'Monge' },
  ladino:      { hit_die:8,  label:'Ladino' },
  mago:        { hit_die:6,  label:'Mago' },
  feiticeiro:  { hit_die:6,  label:'Feiticeiro' },
  bruxo:       { hit_die:8,  label:'Bruxo' },
  npc:         { hit_die:8,  label:'NPC' },
};

const GAME_RACES = [
  'humano','elfo','anão','halfling','draconato','gnomo','meio-elfo','meio-orc','tiferino'
];

// ── Tabelas de limites de magias D&D 5e ──────────────────────────────────────
const SPELL_CANTRIPS_TABLE = {
  bardo:[2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,4,4,4,4,4],
  clérigo:[3,3,3,4,4,4,4,4,4,5,5,5,5,5,5,5,5,5,5,5],
  druida:[2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,4,4,4,4,4],
  feiticeiro:[4,4,4,5,5,5,6,6,6,6,6,6,6,6,6,6,6,6,6,6],
  bruxo:[2,2,2,3,3,3,4,4,4,4,4,4,4,4,4,4,4,4,4,4],
  mago:[3,3,3,4,4,4,4,4,4,5,5,5,5,5,5,5,5,5,5,5],
};
const SPELL_KNOWN_TABLE = {
  mago:       [6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44],
  clérigo:    [3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22],
  druida:     [3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22],
  paladino:   [0,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12],
  bardo:      [4,5,6,7,8,9,10,11,12,14,15,15,16,18,19,19,20,22,22,22],
  feiticeiro: [2,3,4,5,6,7,8,9,10,11,12,12,13,13,14,14,15,15,15,15],
  bruxo:      [2,3,4,5,6,7,8,9,10,10,11,11,12,12,13,13,14,14,14,15],
  patrulheiro:[0,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11],
};
function getSpellLimit(classe, nivel, sheet) {
  const nv=Math.min(Math.max(parseInt(nivel)||1,1),20), idx=nv-1;
  const maxCantrips = SPELL_CANTRIPS_TABLE[classe]?.[idx] ?? 0;
  if (SPELL_KNOWN_TABLE[classe]===undefined) return null;
  const maxSpells = SPELL_KNOWN_TABLE[classe][idx] ?? 0;
  return {maxCantrips, maxSpells};
}

// XP total necessário para atingir o próximo nível (D&D 5e)
const GAME_XP_THRESHOLDS = [0, 300, 900, 2700, 6500, 14000, 23000, 34000,
                             48000, 64000, 85000, 100000, 120000, 140000,
                             165000, 195000, 225000, 265000, 305000, 355000];
function gameXpForNextLevel(nivel) {
  const n = Math.min(Math.max(parseInt(nivel)||1, 1), 19);
  return GAME_XP_THRESHOLDS[n];
}

// Níveis com ASI (Ability Score Improvement) — padrão para todas as classes
const GAME_ASI_LEVELS = new Set([4, 8, 12, 16, 19]);

// Bônus de proficiência D&D 5e por nível (índice 0 = nível 1)
const GAME_PROF_BY_LEVEL = [2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,6,6,6,6];
function gameProfForLevel(nivel) {
  const n = Math.min(Math.max(parseInt(nivel)||1, 1), 20);
  return GAME_PROF_BY_LEVEL[n - 1];
}
// Constrói os botões de filtro de nível refletindo o filtro atual
function gameBuildLvlBtnsHtml(maxSl, lvlF) {
  const s = (active) =>
    `padding:3px 8px;border-radius:3px;border:1px solid ${active?'var(--ink-user)':'var(--page-edge)'};`+
    `background:${active?'rgba(38,75,130,0.12)':'transparent'};color:${active?'var(--ink-user)':'var(--text-muted)'};`+
    `cursor:pointer;font-size:10px;font-family:monospace;font-weight:${active?'700':'400'};`;
  let html = `<button style="${s(lvlF===null)}" onclick="gameSetSpellLvlFilter(null)">Todos</button>`;
  html    += `<button style="${s(lvlF===0)}"    onclick="gameSetSpellLvlFilter(0)">C</button>`;
  for (let n = 1; n <= maxSl; n++)
    html  += `<button style="${s(lvlF===n)}"    onclick="gameSetSpellLvlFilter(${n})">${n}</button>`;
  return html;
}

// Troca o filtro de nível, atualiza os botões visualmente e busca
function gameSetSpellLvlFilter(val) {
  if (!_gameHabState) return;
  _gameHabState._spellLevelFilter = val;
  _gameHabState._spellResults     = [];
  // Atualiza só os botões de filtro imediatamente (sem re-renderizar tudo)
  const { nivel } = _gameGetSheet();
  const maxSl = gameMaxSpellLevel(nivel);
  const btnsEl = document.getElementById('game-lvl-btns');
  if (btnsEl) btnsEl.innerHTML = gameBuildLvlBtnsHtml(maxSl, val);
  gameDoSpellSearch();
}

function gameOnLevelChange(val) {
  const prof = gameProfForLevel(val);
  const profEl = document.getElementById('ef-sheet_proficiencia');
  if (profEl) profEl.value = String(prof);
  // Atualiza nível nas buscas e recarrega habilidades/magias
  if (_gameHabState) {
    _gameHabState._classFeatures = [];
    _gameHabState._spellResults  = [];
    _gameHabState._featLoading   = false;
    _gameHabState._spellLoading  = false;
    gameRefreshHabSection();
  }
}

function gameOnClassChange(val) {
  if (!_gameHabState) return;
  const isCaster = GAME_CASTER_CLASSES.has((val || '').toLowerCase().trim());
  _gameHabState._isCaster        = isCaster;
  _gameHabState._habTab          = isCaster ? 'spells' : 'feats';
  _gameHabState._classFeatures   = [];
  _gameHabState._spellResults    = [];
  _gameHabState._spellLevelFilter = null;
  _gameHabState._spellQuery      = '';
  _gameHabState._featLoading     = false;
  _gameHabState._spellLoading    = false;
  gameRefreshHabSection();
}

// ── Level-Up ─────────────────────────────────────────────────────────────────

function gameLevelUpClick(event, charKey, type, idx) {
  event.stopPropagation();
  document.getElementById('levelup-popup')?.remove();

  const data = type === 'party'
    ? window._lastMem?.party?.[idx]
    : window._lastMem?.characters?.[idx];
  if (!data?.sheet) return;

  const sheet     = data.sheet;
  const novoNivel = (sheet.nivel || 1) + 1;
  const classeKey = (sheet.classe || 'guerreiro').toLowerCase();
  const cls       = GAME_CLASS_DATA[classeKey] || { hit_die: 8, label: sheet.classe };
  const conMod    = Math.floor(((sheet.constituicao || 10) - 10) / 2);
  const hpGain    = Math.max(1, Math.floor(cls.hit_die / 2) + 1 + conMod);
  const novaProf  = gameProfForLevel(novoNivel);
  const profMudou = novaProf !== gameProfForLevel(sheet.nivel || 1);
  const temASI    = GAME_ASI_LEVELS.has(novoNivel);
  const isCaster  = GAME_CASTER_CLASSES.has(classeKey);
  const maxSpell  = gameMaxSpellLevel(novoNivel);

  const popup = document.createElement('div');
  popup.id = 'levelup-popup';
  popup.style.cssText =
    'position:fixed;z-index:10001;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.45);';

  popup.innerHTML = `
    <div style="background:var(--page-bg);border:2px solid #f0c030;border-radius:14px;
                box-shadow:0 20px 60px rgba(0,0,0,0.35);padding:28px;max-width:380px;
                width:calc(100vw - 32px);font-family:'Lora',serif;position:relative;">
      <div style="text-align:center;margin-bottom:20px;">
        <div style="font-size:36px;margin-bottom:6px;">⬆️</div>
        <div style="font-family:'Playfair Display',serif;font-size:20px;font-weight:700;color:var(--text-main);">
          ${escapeHtml(data.name)} sobe para<br>Nível ${novoNivel}!
        </div>
      </div>

      <div style="background:rgba(255,243,196,0.5);border:1px solid #f0c030;border-radius:8px;padding:14px;margin-bottom:18px;">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:#7a4f00;margin-bottom:10px;">Ganhos automáticos</div>
        <div style="display:flex;flex-direction:column;gap:7px;">
          <div style="font-size:13px;">❤️ <strong>+${hpGain} HP máximo</strong>
            <span style="font-size:11px;color:var(--text-muted);">(${cls.hit_die/2|0}+1 + CON ${conMod>=0?'+':''}${conMod})</span></div>
          ${profMudou ? `<div style="font-size:13px;">🛡️ <strong>Proficiência: +${novaProf}</strong> <span style="font-size:11px;color:var(--text-muted);">(era +${gameProfForLevel(sheet.nivel||1)})</span></div>` : ''}
        </div>
      </div>

      ${(temASI || isCaster) ? `
      <div style="background:rgba(38,75,130,0.06);border:1px solid rgba(38,75,130,0.2);border-radius:8px;padding:14px;margin-bottom:18px;">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.07em;color:var(--ink-user);margin-bottom:10px;">Requer sua escolha</div>
        <div style="display:flex;flex-direction:column;gap:7px;font-size:13px;">
          ${temASI ? `<div>🎯 <strong>Melhoria de Atributo (ASI)</strong> — aumente 2 atributos em +1, ou um em +2</div>` : ''}
          ${isCaster ? `<div>✨ <strong>Novos slots de magia</strong> até Nível ${maxSpell} — escolha novas magias na aba Magias</div>` : ''}
          <div>📜 <strong>Novas habilidades de classe</strong> — veja na aba Habilidades</div>
        </div>
      </div>` : ''}

      <div style="display:flex;flex-direction:column;gap:10px;">
        <button onclick="gameConfirmLevelUp('${charKey}','${type}',${idx},${novoNivel},${hpGain},${novaProf})"
          style="width:100%;padding:11px;background:#f0c030;color:#3a2800;border:none;border-radius:7px;
                 cursor:pointer;font-size:14px;font-family:'Lora',serif;font-weight:700;letter-spacing:0.02em;">
          ✅ Confirmar Nível ${novoNivel}
        </button>
        <button onclick="document.getElementById('levelup-popup').remove();openEditModal('${type === 'party' ? 'character' : type}','${charKey}',window._lastMem.${type === 'party' ? 'party' : 'characters'}[${idx}])"
          style="width:100%;padding:9px;background:none;color:var(--ink-user);border:1px solid var(--page-edge);
                 border-radius:7px;cursor:pointer;font-size:13px;font-family:'Lora',serif;">
          📝 Editar Ficha Completa
        </button>
        <button onclick="document.getElementById('levelup-popup').remove()"
          style="width:100%;padding:7px;background:none;color:var(--text-muted);border:none;cursor:pointer;font-size:12px;">
          Cancelar
        </button>
      </div>
    </div>`;

  document.body.appendChild(popup);
  popup.addEventListener('click', e => { if (e.target === popup) popup.remove(); });
}

async function gameConfirmLevelUp(charKey, type, idx, novoNivel, hpGain, novaProf) {
  document.getElementById('levelup-popup')?.remove();

  const data = type === 'party'
    ? window._lastMem?.party?.[idx]
    : window._lastMem?.characters?.[idx];
  if (!data?.sheet) return;

  const sheet = data.sheet;
  const newSheet = {
    ...sheet,
    nivel:        novoNivel,
    vida_max:     (sheet.vida_max  || 0) + hpGain,
    vida_atual:   (sheet.vida_atual || 0) + hpGain,
    proficiencia: novaProf,
    xp_proximo:   gameXpForNextLevel(novoNivel),
  };

  const url = `${API}/api/memory/characters/${encodeURIComponent(charKey)}`;
  try {
    const res = await authFetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...data, sheet: newSheet }),
    });
    if (res.ok) {
      showToast(`⬆️ ${data.name} agora é nível ${novoNivel}! +${hpGain} HP`);
      await refreshMemory();
      // Abre modal para o usuário escolher magias / ASI
      const newIdx = type === 'party'
        ? window._lastMem.party.findIndex(p => p.name.toLowerCase() === charKey)
        : window._lastMem.characters.findIndex(c => c.name.toLowerCase() === charKey);
      if (newIdx !== -1) {
        const newData = type === 'party' ? window._lastMem.party[newIdx] : window._lastMem.characters[newIdx];
        openEditModal('character', charKey, newData);
      }
    } else {
      const e = await res.json();
      await showAlert('Erro', e.error || 'Não foi possível salvar.', 'danger');
    }
  } catch (_) {
    await showAlert('Erro', 'Falha de conexão ao salvar.', 'danger');
  }
}

const GAME_STATUS_OPTS = [
  'vivo','morto','ferido','desaparecido','preso','aliado','inimigo','exilado'
];

// ── Popup de detalhes de magia / habilidade (in-game) ────────────────────────
const _habInfoRegistry = [];

function showHabInfo(event, sp, regIdx, alreadyHas, limitReached) {
  event.stopPropagation();
  document.getElementById('hab-info-popup')?.remove();

  const addFn = (typeof regIdx === 'number') ? _habInfoRegistry[regIdx] : null;
  if (alreadyHas === undefined) alreadyHas = !addFn;
  if (limitReached === undefined) limitReached = false;

  const nivel = sp.nivel_magia === 0 ? 'Cantrip'
              : sp.nivel_magia > 0   ? `Nível ${sp.nivel_magia}`
              : sp.nivel > 0         ? `Nível ${sp.nivel}` : '';

  const popup = document.createElement('div');
  popup.id = 'hab-info-popup';

  let left = event.clientX + 10;
  let top  = event.clientY + 10;
  if (left + 348 > window.innerWidth)  left = event.clientX - 358;
  if (top  + 340 > window.innerHeight) top  = event.clientY - 350;
  left = Math.max(8, left);
  top  = Math.max(8, top);

  popup.style.cssText =
    `position:fixed;z-index:10000;left:${left}px;top:${top}px;` +
    `background:var(--page-bg,#fff);border:1px solid var(--page-edge,#ccc);border-radius:10px;` +
    `box-shadow:0 12px 40px rgba(0,0,0,0.22);padding:18px;` +
    `max-width:340px;width:min(340px,calc(100vw - 16px));font-family:'Lora',serif;`;

  const badges = [
    nivel           ? `<span style="font-size:11px;background:rgba(38,75,130,0.1);color:var(--ink-user);padding:2px 8px;border-radius:10px;">${escapeHtml(nivel)}</span>` : '',
    sp.escola       ? `<span style="font-size:11px;color:var(--text-muted);">${escapeHtml(sp.escola)}</span>` : '',
    sp.ritual       ? `<span style="font-size:10px;border:1px solid var(--page-edge);border-radius:3px;padding:1px 5px;color:var(--text-muted);">ritual</span>` : '',
    sp.concentracao ? `<span style="font-size:10px;border:1px solid var(--page-edge);border-radius:3px;padding:1px 5px;color:var(--text-muted);">conc.</span>` : '',
  ].filter(Boolean).join(' ');

  popup.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:15px;font-weight:700;color:var(--text-main);margin-bottom:5px;">${escapeHtml(sp.nome||'')}</div>
        <div style="display:flex;flex-wrap:wrap;gap:5px;align-items:center;">${badges}</div>
      </div>
      <button onclick="document.getElementById('hab-info-popup').remove()"
        style="background:none;border:none;cursor:pointer;font-size:18px;color:var(--text-muted);padding:0 0 0 10px;line-height:1;flex-shrink:0;">✕</button>
    </div>
    ${(sp.dado || sp.custo_mana > 0) ? `
    <div style="display:flex;gap:20px;margin-bottom:10px;padding:8px 10px;background:rgba(0,0,0,0.03);border-radius:6px;">
      ${sp.dado           ? `<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-muted);margin-bottom:2px;">Dado</div><div style="font-family:monospace;font-size:16px;font-weight:700;">${escapeHtml(sp.dado)}</div></div>` : ''}
      ${sp.custo_mana > 0 ? `<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-muted);margin-bottom:2px;">Mana</div><div style="font-size:16px;font-weight:700;color:var(--ink-user);">${sp.custo_mana}</div></div>` : ''}
    </div>` : ''}
    ${sp.descricao ? `<div style="font-size:12px;line-height:1.65;color:var(--text-dim);max-height:160px;overflow-y:auto;border-top:1px solid var(--page-edge);padding-top:8px;margin-bottom:14px;">${escapeHtml(sp.descricao)}</div>` : ''}
    ${alreadyHas
      ? `<div style="text-align:center;font-size:12px;color:var(--green,#2d8a4e);padding:6px 0;">✓ Já adicionada</div>`
      : limitReached
        ? `<div style="text-align:center;font-size:12px;color:var(--ink-sys,#8b3a3a);padding:6px 0;">⚠️ Limite de cantrips/magias atingido (use a aba de habilidades)</div>`
        : `<button onclick="_habInfoRegistry[${regIdx}]()"
             style="width:100%;padding:9px;background:var(--ink-user,#264b82);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-family:'Lora',serif;font-weight:600;letter-spacing:0.02em;">
             + Adicionar
           </button>`
    }`;

  document.body.appendChild(popup);

  setTimeout(() => {
    function outsideClick(e) {
      if (!popup.contains(e.target)) {
        popup.remove();
        document.removeEventListener('click', outsideClick);
      }
    }
    document.addEventListener('click', outsideClick);
  }, 50);
}

// ═══════════════════════════════════════
//  Modal de edição — Habilidades & Magias
// ═══════════════════════════════════════
const GAME_CASTER_CLASSES = new Set([
  'mago','feiticeiro','bruxo','clérigo','druida','bardo','paladino','patrulheiro'
]);

function gameMaxSpellLevel(nivel) {
  return Math.min(9, Math.max(1, Math.ceil((parseInt(nivel)||1) / 2)));
}

let _gameHabState = null;

// Lê classe e nível do formulário (pode ter sido alterado pelo user antes de buscar)
function _gameGetSheet() {
  const classeEl = document.getElementById('ef-sheet_classe');
  const nivelEl  = document.getElementById('ef-sheet_nivel');
  const classe   = (classeEl?.value || _editCtx?.data?.sheet?.classe || 'guerreiro').toLowerCase().trim();
  const nivel    = parseInt(nivelEl?.value) || parseInt(_editCtx?.data?.sheet?.nivel) || 1;
  return { classe, nivel };
}

function gameRefreshHabSection() {
  const el = document.getElementById('game-hab-section');
  if (el) el.innerHTML = gameBuildHabSection();
}

function gameSetHabTab(tab) {
  if (!_gameHabState) return;
  _gameHabState._habTab = tab;
  if (tab === 'feats' && !_gameHabState._classFeatures?.length && !_gameHabState._featLoading) {
    _gameHabState._featLoading = true;
    gameLoadClassFeatures();
  }
  if (tab === 'spells' && !_gameHabState._spellResults?.length && !_gameHabState._spellLoading) {
    gameDoSpellSearch();
  }
  gameRefreshHabSection();
}

const _gameSpellTimer = {};
function gameTriggerSpellSearch() {
  clearTimeout(_gameSpellTimer[0]);
  _gameSpellTimer[0] = setTimeout(() => gameDoSpellSearch(), 420);
}

async function gameDoSpellSearch() {
  if (!_gameHabState) return;
  const { classe, nivel } = _gameGetSheet();
  const maxLevel = gameMaxSpellLevel(nivel);
  const q = (_gameHabState._spellQuery || '').trim();
  _gameHabState._spellLoading = true;
  const panelEl = document.getElementById('game-spell-panel');
  if (panelEl) panelEl.innerHTML = '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">A carregar magias...</div>';
  else gameRefreshHabSection();
  try {
    const params = new URLSearchParams({ class: classe, max_level: maxLevel });
    if (q) params.set('q', q);
    const lvlF = _gameHabState._spellLevelFilter;
    if (lvlF !== null && lvlF !== undefined) params.set('spell_level', lvlF);
    const res  = await authFetch(`${API}/api/dnd/class-spells?${params}`);
    const data = await res.json();
    _gameHabState._spellResults = data.spells || [];
  } catch(_) {
    _gameHabState._spellResults = [];
  }
  _gameHabState._spellLoading = false;
  const el2 = document.getElementById('game-spell-panel');
  if (el2) el2.innerHTML = gameBuildSpellPanelList();
  else gameRefreshHabSection();
}

async function gameLoadClassFeatures() {
  if (!_gameHabState) return;
  const { classe, nivel } = _gameGetSheet();
  _gameHabState._featLoading = true;
  const el = document.getElementById('game-feat-panel');
  if (el) el.innerHTML = '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">A carregar habilidades de classe...</div>';
  else gameRefreshHabSection();
  try {
    const res  = await authFetch(`${API}/api/dnd/class-features?class=${encodeURIComponent(classe)}&level=${nivel}`);
    const data = await res.json();
    _gameHabState._classFeatures = data.features || [];
  } catch(_) { _gameHabState._classFeatures = []; }
  _gameHabState._featLoading = false;
  const el2 = document.getElementById('game-feat-panel');
  if (el2) el2.innerHTML = gameBuildFeatPanelList();
  else gameRefreshHabSection();
}

function gameAddSpell(spell) {
  if (!_editCtx?.data) return;
  _editCtx.data.habilidades = _editCtx.data.habilidades || [];
  if (!_editCtx.data.habilidades.some(h => h.nome.toLowerCase() === spell.nome.toLowerCase())) {
    _editCtx.data.habilidades.push({
      nome:        spell.nome,
      descricao:   [spell.escola?`[${spell.escola}${spell.ritual?' (ritual)':''}${spell.concentracao?' (conc.)':''}]`:'', spell.descricao||''].filter(Boolean).join(' '),
      custo_mana:  spell.custo_mana ?? 0,
      dado:        spell.dado || '',
      nivel_magia: spell.nivel_magia ?? 0,
    });
  }
  gameRefreshHabSection();
}

function gameAddFeat(feat) {
  if (!_editCtx?.data) return;
  _editCtx.data.habilidades = _editCtx.data.habilidades || [];
  if (!_editCtx.data.habilidades.some(h => h.nome.toLowerCase() === feat.nome.toLowerCase())) {
    _editCtx.data.habilidades.push({ nome: feat.nome, descricao: feat.descricao||'', custo_mana: feat.custo_mana||0, dado: feat.dado||'' });
  }
  gameRefreshHabSection();
}

function gameRemoveAbility(j) {
  if (!_editCtx?.data?.habilidades) return;
  _editCtx.data.habilidades.splice(j, 1);
  gameRefreshHabSection();
}

// Renderiza apenas a lista de resultados do painel de magias (atualização parcial)
function gameBuildSpellPanelList() {
  if (!_gameHabState) return '';
  const results  = _gameHabState._spellResults || [];
  const rawQuery = (_gameHabState._spellQuery || '').trim();
  const lvlF     = _gameHabState._spellLevelFilter;
  const habs     = _editCtx?.data?.habilidades || [];
  const { classe, nivel } = _gameGetSheet();
  const _gameLimit      = _editCtx?.data?.freeMode ? null : getSpellLimit(classe, nivel, _editCtx?.data?.sheet);
  const _gameCantripCnt = habs.filter(h => typeof h.nivel_magia === 'number' && h.nivel_magia === 0).length;
  const _gameLeveledCnt = habs.filter(h => typeof h.nivel_magia === 'number' && h.nivel_magia > 0).length;
  const renderRow = (sp) => {
    const badge      = sp.nivel_magia === 0 ? 'C' : `${sp.nivel_magia}`;
    const manaTag    = sp.custo_mana > 0 ? ` · ${sp.custo_mana} mana` : '';
    const alreadyHas = habs.some(h => h.nome.toLowerCase() === sp.nome.toLowerCase());
    const isCantrip  = sp.nivel_magia === 0;
    const limitReached = !alreadyHas && _gameLimit && (isCantrip ? _gameCantripCnt >= _gameLimit.maxCantrips : _gameLeveledCnt >= _gameLimit.maxSpells);
    const regIdx     = _habInfoRegistry.length;
    _habInfoRegistry.push((alreadyHas || limitReached) ? null : () => { gameAddSpell(sp); document.getElementById('hab-info-popup')?.remove(); });
    const spJson     = JSON.stringify(sp).replace(/"/g,'&quot;');
    return `<div class="ed-search-result ${alreadyHas?'ed-search-result-added':''}" onclick="showHabInfo(event,${spJson},${regIdx},${alreadyHas},${limitReached})" style="cursor:pointer;">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <span class="ed-spell-badge" style="min-width:22px;text-align:center;">${badge}</span>
        <strong style="font-size:13px;">${escapeHtml(sp.nome)}</strong>
        ${sp.dado?`<span style="font-family:monospace;font-size:10px;color:var(--text-muted);">${escapeHtml(sp.dado)}</span>`:''}
        ${manaTag?`<span style="font-size:10px;color:var(--ink-user);">${manaTag}</span>`:''}
        ${sp.concentracao?`<span style="font-size:9px;color:var(--text-muted);border:1px solid var(--page-edge);border-radius:2px;padding:0 3px;">conc.</span>`:''}
        ${sp.ritual?`<span style="font-size:9px;color:var(--text-muted);border:1px solid var(--page-edge);border-radius:2px;padding:0 3px;">ritual</span>`:''}
        ${alreadyHas?`<span style="font-size:10px;color:var(--green);">✓ já tem</span>`:''}
        ${limitReached&&!alreadyHas?`<span style="font-size:9px;color:var(--ink-sys);border:1px solid currentColor;border-radius:2px;padding:0 3px;opacity:0.7;">limite</span>`:''}
      </div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:3px;">${escapeHtml((sp.descricao||'').slice(0,100))}${(sp.descricao||'').length>100?'…':''}</div>
    </div>`;
  };
  if (results.length === 0) return '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">Nenhuma magia encontrada. Busque pelo nome em inglês (ex: "fireball").</div>';
  if (!rawQuery && lvlF === null) {
    const groups = {};
    results.forEach(sp => { const k = sp.nivel_magia; if (!groups[k]) groups[k] = []; groups[k].push(sp); });
    let html = Object.keys(groups).sort((a,b)=>a-b).map(lvl => {
      const label = lvl == 0 ? 'Cantrips (Nv. 0)' : `Nível ${lvl}`;
      return `<div style="margin-bottom:8px;"><div style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;padding:4px 0 4px 2px;border-bottom:1px solid var(--page-edge);margin-bottom:4px;">${label}</div>${groups[lvl].map(renderRow).join('')}</div>`;
    }).join('');
    if (results.length >= 100) html += `<div style="font-size:11px;color:var(--text-dim);font-style:italic;padding:6px 0;">Mostrando ${results.length} magias — filtre por nível ou pesquise para ver mais.</div>`;
    return html;
  }
  return results.map(renderRow).join('');
}

// Renderiza apenas a lista de resultados do painel de feats
function gameBuildFeatPanelList() {
  if (!_gameHabState) return '';
  const feats = _gameHabState._classFeatures || [];
  const habs  = _editCtx?.data?.habilidades || [];
  const { classe, nivel } = _gameGetSheet();
  if (feats.length === 0) return `<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">Nenhuma habilidade encontrada para ${escapeHtml(classe)} nível ${nivel}.</div>`;
  return feats.map(feat => {
    const alreadyHas = habs.some(h => h.nome.toLowerCase() === feat.nome.toLowerCase());
    const regIdx     = _habInfoRegistry.length;
    _habInfoRegistry.push(alreadyHas ? null : () => { gameAddFeat(feat); document.getElementById('hab-info-popup')?.remove(); });
    const featJson   = JSON.stringify(feat).replace(/"/g,'&quot;');
    return `<div class="ed-search-result ${alreadyHas?'ed-search-result-added':''}" onclick="showHabInfo(event,${featJson},${regIdx})" style="cursor:pointer;">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <span class="ed-spell-badge" style="min-width:28px;text-align:center;">Nv.${feat.nivel}</span>
        <strong style="font-size:13px;">${escapeHtml(feat.nome)}</strong>
        ${alreadyHas?`<span style="font-size:10px;color:var(--green);">✓ já tem</span>`:''}
      </div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">${escapeHtml((feat.descricao||'').slice(0,120))}${(feat.descricao||'').length>120?'…':''}</div>
    </div>`;
  }).join('');
}

function gameBuildHabSection() {
  if (!_gameHabState || !_editCtx?.data?.sheet) return '';
  const habs = _editCtx.data.habilidades || [];
  const { classe, nivel } = _gameGetSheet();
  // Usa _isCaster fixo (definido na inicialização) para que a aba Magias
  // apareça corretamente no primeiro render, antes do DOM estar disponível.
  // Quando a classe muda via select, gameOnClassChange() atualiza _isCaster.
  const showSpellTab = _gameHabState._isCaster ?? GAME_CASTER_CLASSES.has(classe);
  let habTab = _gameHabState._habTab || 'feats';
  if (habTab === 'spells' && !showSpellTab) habTab = 'feats';

  // Auto-carrega a aba ativa na primeira renderização
  if (habTab === 'feats' && !_gameHabState._classFeatures?.length && !_gameHabState._featLoading) {
    _gameHabState._featLoading = true;
    setTimeout(() => gameLoadClassFeatures(), 20);
  }
  if (habTab === 'spells' && showSpellTab && !_gameHabState._spellResults?.length && !_gameHabState._spellLoading) {
    _gameHabState._spellLoading = true;
    setTimeout(() => gameDoSpellSearch(), 20);
  }

  // ── Abas ────────────────────────────────────────────────────────────
  const tabStyle = (active) =>
    `padding:7px 16px;border:none;border-bottom:2px solid ${active?'var(--ink-user)':'transparent'};`+
    `background:none;cursor:pointer;font-family:'Lora',serif;font-size:12px;margin-bottom:-1px;`+
    `color:${active?'var(--ink-user)':'var(--text-muted)'};font-weight:${active?'700':'400'};`+
    `transition:color 0.15s,border-color 0.15s;`;

  const tabBar = `
    <div style="display:flex;border-bottom:1px solid var(--page-edge);margin-bottom:12px;">
      <button style="${tabStyle(habTab==='feats')}"  onclick="gameSetHabTab('feats')">📜 Habilidades</button>
      ${showSpellTab ? `<button style="${tabStyle(habTab==='spells')}" onclick="gameSetHabTab('spells')">✨ Magias</button>` : ''}
    </div>`;

  // ── Conteúdo da aba ──────────────────────────────────────────────────
  let tabContent = '';
  if (habTab === 'feats') {
    tabContent = `
      <div style="margin-bottom:12px;">
        <div style="font-size:11px;color:var(--ink-user);margin-bottom:8px;">
          Habilidades de <strong>${escapeHtml(classe)}</strong> disponíveis até nível ${nivel}
        </div>
        <div class="ed-search-results-list" style="max-height:260px;" id="game-feat-panel">${gameBuildFeatPanelList()}</div>
      </div>`;
  } else {
    const maxSl = gameMaxSpellLevel(nivel);
    const lvlF  = _gameHabState._spellLevelFilter;
    const lvlBtnStyle = (active) =>
      `padding:3px 8px;border-radius:3px;border:1px solid ${active?'var(--ink-user)':'var(--page-edge)'};`+
      `background:${active?'rgba(38,75,130,0.12)':'transparent'};color:${active?'var(--ink-user)':'var(--text-muted)'};`+
      `cursor:pointer;font-size:10px;font-family:monospace;font-weight:${active?'700':'400'};`;
    let levelBtns = `<button style="${lvlBtnStyle(lvlF===null)}" onclick="gameSetSpellLvlFilter(null)">Todos</button>`;
    levelBtns += `<button style="${lvlBtnStyle(lvlF===0)}" onclick="gameSetSpellLvlFilter(0)">C</button>`;
    for (let n = 1; n <= maxSl; n++) {
      levelBtns += `<button style="${lvlBtnStyle(lvlF===n)}" onclick="gameSetSpellLvlFilter(${n})">${n}</button>`;
    }
    const query = escapeHtml(_gameHabState._spellQuery || '');
    const _gHabLimit      = getSpellLimit(classe, nivel, _editCtx?.data?.sheet);
    const _gHabCantripCnt = (_editCtx?.data?.habilidades||[]).filter(h => typeof h.nivel_magia === 'number' && h.nivel_magia === 0).length;
    const _gHabLeveledCnt = (_editCtx?.data?.habilidades||[]).filter(h => typeof h.nivel_magia === 'number' && h.nivel_magia > 0).length;
    tabContent = `
      <div style="margin-bottom:12px;">
        <div style="font-size:11px;color:var(--ink-user);margin-bottom:8px;">
          Magias de <strong>${escapeHtml(classe)}</strong> até Nv.${maxSl} · SRD Open5e${_gHabLimit ? `<span style="font-size:10px;font-family:monospace;color:var(--text-muted);margin-left:8px;">| C: ${_gHabCantripCnt}/${_gHabLimit.maxCantrips} ✨ ${_gHabLeveledCnt}/${_gHabLimit.maxSpells}</span>` : ''}
        </div>
        <div id="game-lvl-btns" style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px;">${levelBtns}</div>
        <div style="display:flex;gap:8px;margin-bottom:8px;">
          <input value="${query}" placeholder="Buscar magia (ex: fireball)..."
            oninput="_gameHabState._spellQuery=this.value;gameTriggerSpellSearch()" style="flex:1;font-size:13px;">
          <button class="clean-button" style="width:auto;padding:4px 10px;margin:0;font-size:12px;" onclick="gameDoSpellSearch()">🔍</button>
        </div>
        <div class="ed-search-results-list" style="max-height:260px;" id="game-spell-panel">${gameBuildSpellPanelList()}</div>
      </div>`;
  }

  // ── Lista de habilidades já adicionadas ──────────────────────────────
  const habList = habs.length
    ? habs.map((h, j) => `
        <div style="display:flex;align-items:center;gap:8px;padding:7px 10px;background:rgba(0,0,0,0.02);border:1px solid var(--page-edge);border-radius:4px;margin-bottom:4px;">
          <div style="flex:1;min-width:0;">
            <span style="font-size:13px;font-weight:600;">${escapeHtml(h.nome||'')}</span>
            ${h.dado?`<span style="font-family:monospace;font-size:10px;color:var(--text-muted);margin-left:6px;">${escapeHtml(h.dado)}</span>`:''}
            ${h.custo_mana>0?`<span style="font-size:10px;color:var(--ink-user);margin-left:6px;">${h.custo_mana} mana</span>`:''}
          </div>
          <button onclick="gameRemoveAbility(${j})" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:15px;padding:2px 4px;flex-shrink:0;" title="Remover">✕</button>
        </div>`).join('')
    : '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:4px 0;">Nenhuma habilidade adicionada.</div>';

  return `
    <div style="border-top:1px solid var(--page-edge);margin-top:16px;padding-top:16px;">
      <div style="font-family:'Playfair Display',serif;font-size:14px;font-weight:700;color:var(--text-main);margin-bottom:10px;">✨ HABILIDADES & MAGIAS</div>
      ${tabBar}
      ${tabContent}
      <div style="margin-top:4px;">${habList}</div>
    </div>`;
}

// ═══════════════════════════════════════
//  Modal de edição
// ═══════════════════════════════════════
let _editCtx = null;
// Estado de busca de monstro no modal de edição do jogo
let _gameMonsterState = { query: '', results: [], loading: false };
let _gameMonsterTimer = null;

function gameSearchMonster(query) {
  _gameMonsterState.query = query;
  clearTimeout(_gameMonsterTimer);
  if (!query || query.length < 2) {
    _gameMonsterState.results = [];
    gameRefreshMonsterSearch();
    return;
  }
  _gameMonsterState.loading = true;
  gameRefreshMonsterSearch();
  _gameMonsterTimer = setTimeout(async () => {
    try {
      const res  = await authFetch(`${API}/api/dnd/monsters/search?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      _gameMonsterState.results = data.ok ? (data.monsters || []) : [];
    } catch { _gameMonsterState.results = []; }
    _gameMonsterState.loading = false;
    gameRefreshMonsterSearch();
  }, 400);
}

function gameRefreshMonsterSearch() {
  const el = document.getElementById('game-monster-results');
  if (!el) return;
  if (_gameMonsterState.loading) {
    el.innerHTML = '<div style="padding:6px;color:var(--text-muted);font-size:12px;">⏳ Buscando…</div>';
    return;
  }
  if (!_gameMonsterState.results?.length) { el.innerHTML = ''; return; }
  el.innerHTML = _gameMonsterState.results.map(m => {
    const mJson = JSON.stringify(m).replace(/"/g, '&quot;');
    return `<div class="ed-search-result" onclick="gameApplyMonster(${mJson})" style="cursor:pointer;padding:6px 8px;">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <strong style="font-size:13px;">${(m.nome||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')}</strong>
        <span style="font-size:10px;color:var(--text-muted);">${(m.tipo||'')} · CR ${m.cr}</span>
      </div>
      <div style="font-size:10px;font-family:monospace;color:var(--text-muted);margin-top:2px;">
        FOR ${m.forca} DES ${m.destreza} CON ${m.constituicao} INT ${m.inteligencia} SAB ${m.sabedoria} CAR ${m.carisma} · CA ${m.ca} · HP ${m.vida}${m.arma_principal ? ` · ⚔️ ${(m.arma_principal).replace(/&/g,'&amp;').replace(/</g,'&lt;')}` : ''}
      </div>
    </div>`;
  }).join('');
}

function gameApplyMonster(monster) {
  if (!_editCtx?.data?.sheet) return;
  const s = _editCtx.data.sheet;
  s.forca        = monster.forca;
  s.destreza     = monster.destreza;
  s.constituicao = monster.constituicao;
  s.inteligencia = monster.inteligencia;
  s.sabedoria    = monster.sabedoria;
  s.carisma      = monster.carisma;
  s.vida_atual   = monster.vida;
  s.vida_max     = monster.vida;
  s.ca           = monster.ca;
  s.cr           = monster.cr;
  s.raca         = monster.nome.toLowerCase();
  if (!s.equipamentos) s.equipamentos = {};
  s.equipamentos.arma_principal  = monster.arma_principal  || '';
  s.equipamentos.arma_secundaria = monster.arma_secundaria || null;
  // Limpa busca e re-renderiza o formulário
  _gameMonsterState = { query: '', results: [], loading: false };
  document.getElementById('edit-body').innerHTML = buildEditFields('character', _editCtx.data);
}

function openEditModal(type, key, data, index = null) {
  if (window.innerWidth <= 900) toggleSidebar(true);
  _editCtx = { type, key, data, index };
  // Reinicia estado de busca de monstro
  _gameMonsterState = { query: '', results: [], loading: false };
  // Inicializa estado das abas de habilidades para personagens D&D
  if (type === 'character' && data.sheet) {
    const isCaster = GAME_CASTER_CLASSES.has((data.sheet.classe || '').toLowerCase());
    _gameHabState = {
      _isCaster:         isCaster,          // fixo na inicialização, não depende do DOM
      _habTab:           isCaster ? 'spells' : 'feats',
      _spellLevelFilter: null,
      _spellQuery:       '',
      _spellResults:     [],
      _spellLoading:     false,
      _classFeatures:    [],
      _featLoading:      false,
    };
  } else {
    _gameHabState = null;
  }
  const labels = { character: 'Personagem', party: 'Grupo', location: 'Local', flag: 'Flag', event: 'Evento', diary: 'Diário', world: 'Resumo' };
  document.getElementById('edit-type').textContent = labels[type] || type;
  document.getElementById('edit-name').textContent = data.name || data.title || data.summary || key || '—';
  document.getElementById('edit-body').innerHTML = buildEditFields(type, data);
  document.getElementById('edit-del-btn').style.display = type === 'world' ? 'none' : '';
  document.getElementById('edit-overlay').classList.remove('hidden');
}

function closeEditModal() { document.getElementById('edit-overlay').classList.add('hidden'); _editCtx = null; }

function field(id, label, value, type = 'input', opts = {}) {
  const v = (value || '').toString().replace(/"/g, '&quot;');
  if (type === 'select') {
    const options = (opts.options || []).map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${o}</option>`).join('');
    return `<div class="field-group"><label>${label}</label><select id="ef-${id}">${options}</select></div>`;
  }
  if (type === 'textarea') return `<div class="field-group"><label>${label}</label><textarea id="ef-${id}" rows="${opts.rows || 3}">${(value || '').replace(/</g, '&lt;')}</textarea></div>`;
  return `<div class="field-group"><label>${label}</label><input id="ef-${id}" type="text" value="${v}"></div>`;
}

// Select com entries {value, label} ou strings simples
function selField(id, label, value, entries, opts = {}) {
  const style    = opts.style    || '';
  const onchange = opts.onchange ? ` onchange="${opts.onchange}"` : '';
  const options = entries.map(e => {
    const v = typeof e === 'string' ? e : e.value;
    const l = typeof e === 'string' ? (e.charAt(0).toUpperCase() + e.slice(1)) : e.label;
    return `<option value="${v}" ${v === String(value) ? 'selected' : ''}>${l}</option>`;
  }).join('');
  return `<div class="field-group" ${style ? `style="${style}"` : ''}><label>${label}</label><select id="ef-${id}"${onchange}>${options}</select></div>`;
}

// Input numérico com min/max e estilo compacto
function numField(id, label, value, min, max, opts = {}) {
  const style = opts.style || '';
  return `<div class="field-group" ${style ? `style="${style}"` : ''}><label>${label}</label>`+
    `<input id="ef-${id}" type="number" min="${min}" max="${max}" value="${parseInt(value)||0}" `+
    `style="text-align:center;font-size:16px;font-weight:700;"></div>`;
}

function buildEditFields(type, data) {
  switch (type) {
    case 'character': {
      let html = field('name', 'Nome', data.name);
      if (data.role !== undefined) html += field('role', 'Função no Grupo', data.role);
      html += field('description', 'Descrição', data.description, 'textarea')
        + field('traits', 'Traços', data.traits, 'textarea', { rows: 2 })
        + field('status', 'Status', data.status, 'select', { options: ['vivo', 'morto', 'ferido', 'desaparecido', 'preso', 'aliado', 'inimigo', 'exilado'] })
        + field('notes', 'Notas', data.notes, 'textarea', { rows: 2 });
      if (data.sheet) {
        const s = data.sheet;
        const classeVal = (s.classe || 'guerreiro').toLowerCase().trim();
        const racaVal   = (s.raca   || '').toLowerCase().trim();
        const isNpc     = classeVal === 'npc';

        // ── Classe & Raça / Monstro (selects / inputs) ──────────────────
        const classeOpts = Object.entries(GAME_CLASS_DATA).map(([k,v]) => ({ value: k, label: v.label }));
        const racaOpts   = GAME_RACES;
        const levelOpts  = Array.from({length:20}, (_,i) => ({ value: String(i+1), label: `Nível ${i+1}` }));
        const profOpts   = [2,3,4,5,6].map(n => ({ value: String(n), label: `+${n}` }));

        // Campo raça: select para PCs, busca Open5e para NPCs/monstros
        const racaEsc = racaVal.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
        const racaCapitalized = racaEsc ? racaEsc.charAt(0).toUpperCase()+racaEsc.slice(1) : '';
        const racaField = isNpc
          ? `<div class="field-group">
               <label>Monstro / Criatura <span style="font-size:10px;color:var(--text-muted);font-weight:400;">(Open5e)</span></label>
               <input type="hidden" id="ef-sheet_raca" value="${racaEsc}">
               ${racaVal ? `<div style="font-size:11px;color:var(--ink-user);margin-bottom:4px;">✓ ${racaCapitalized}</div>` : ''}
               <input type="text"
                 placeholder="Buscar monstro… (ex: goblin, zombie)"
                 oninput="gameSearchMonster(this.value)"
                 style="text-align:left;font-size:14px;font-weight:400;width:100%;box-sizing:border-box;background:transparent;border:none;border-bottom:1px solid var(--page-edge);padding:4px 0;">
               <div id="game-monster-results" style="max-height:200px;overflow-y:auto;border:1px solid var(--page-edge);border-top:none;border-radius:0 0 6px 6px;"></div>
             </div>`
          : selField('sheet_raca', 'Raça', racaVal || 'humano', racaOpts);

        html += `<div style="border-top:1px solid var(--page-edge);margin:12px 0 8px;padding-top:14px;">
          <div style="font-family:'Playfair Display',serif;font-size:14px;color:var(--text-main);margin-bottom:12px;font-weight:700;">⚔️ FICHA D&D</div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
            ${selField('sheet_classe','Classe', classeVal, classeOpts, { onchange: 'gameOnClassChange(this.value)' })}
            ${racaField}
          </div>
          ${isNpc
            ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                <div class="field-group"><label>Challenge Rating (CR)</label>
                  <input id="ef-sheet_cr" type="text" value="${(s.cr ?? '').toString().replace(/"/g,'&quot;')}"
                    placeholder="ex: 1/4, 1, 5…"
                    style="text-align:left;font-size:14px;font-weight:700;color:var(--ink-user);">
                </div>
              </div>`
            : `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px;">
                ${selField('sheet_nivel','Nível', String(s.nivel??1), levelOpts, { onchange: 'gameOnLevelChange(this.value)' })}
                ${numField('sheet_xp','XP', s.xp??0, 0, 999999)}
                ${selField('sheet_proficiencia','Proficiência', String(s.proficiencia??2), profOpts)}
              </div>`
          }

          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">Pontos de Vida & Defesa</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:10px;">
            ${numField('sheet_vida_atual','HP Atual', s.vida_atual??0, 0, 999)}
            ${numField('sheet_vida_max','HP Máx', s.vida_max??0, 1, 999)}
            ${numField('sheet_mana_atual','Mana Atual', s.mana_atual??0, 0, 999)}
            ${numField('sheet_mana_max','Mana Máx', s.mana_max??0, 0, 999)}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
            ${numField('sheet_ca','CA (Classe de Armadura)', s.ca??10, 1, 30)}
            <div class="field-group"><label>Morte (Suc. / Falh.)</label>
              <div style="display:flex;gap:6px;">
                <input id="ef-sheet_ds_suc" type="number" min="0" max="3" value="${s.death_saves_sucessos??0}" style="text-align:center;font-size:16px;font-weight:700;">
                <input id="ef-sheet_ds_fail" type="number" min="0" max="3" value="${s.death_saves_falhas??0}" style="text-align:center;font-size:16px;font-weight:700;">
              </div>
            </div>
          </div>

          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">Atributos</div>
          <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-bottom:12px;">
            ${numField('sheet_forca','FOR', s.forca??10, 1, 30)}
            ${numField('sheet_destreza','DES', s.destreza??10, 1, 30)}
            ${numField('sheet_constituicao','CON', s.constituicao??10, 1, 30)}
            ${numField('sheet_inteligencia','INT', s.inteligencia??10, 1, 30)}
            ${numField('sheet_sabedoria','SAB', s.sabedoria??10, 1, 30)}
            ${numField('sheet_carisma','CAR', s.carisma??10, 1, 30)}
          </div>

          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">Moedas</div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">
            ${numField('sheet_ouro','🟡 Ouro', s.ouro??0, 0, 999999)}
            ${numField('sheet_prata','⚪ Prata', s.prata??0, 0, 999999)}
            ${numField('sheet_cobre','🟤 Cobre', s.cobre??0, 0, 999999)}
          </div>

          <div style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">Equipamentos</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            ${field('sheet_eq_armadura','Armadura', s.equipamentos?.armadura??'')}
            ${field('sheet_eq_escudo','Escudo', s.equipamentos?.escudo??'')}
            ${field('sheet_eq_arma','Arma Principal', s.equipamentos?.arma_principal??'')}
            ${field('sheet_eq_arma_sec','Arma Secundária / Distância', s.equipamentos?.arma_secundaria??'')}
            ${field('sheet_eq_amuleto','Amuleto', s.equipamentos?.amuleto??'')}
          </div>
        </div>`;
        html += `<div id="game-hab-section">${gameBuildHabSection()}</div>`;
      }
      return html;
    }
    case 'party': return field('name', 'Nome', data.name) + field('role', 'Função', data.role) + field('notes', 'Notas', data.notes, 'textarea', { rows: 2 });
    case 'location': return field('name', 'Nome', data.name) + field('description', 'Descrição', data.description, 'textarea') + field('details', 'Detalhes', data.details, 'textarea', { rows: 2 }) + field('notes', 'Notas', data.notes, 'textarea', { rows: 2 });
    case 'flag': return field('flag_key', 'Nome da Observação', data.key) + field('flag_value', 'Valor', data.value);
    case 'event': return field('summary', 'Resumo', data.summary, 'textarea', { rows: 2 }) + field('characters_involved', 'Personagens', data.characters_involved) + field('location', 'Local', data.location) + field('consequence', 'Consequência', data.consequence, 'textarea', { rows: 2 });
    case 'diary': return field('title', 'Título', data.title) + field('chapter', 'Capítulo', data.chapter) + field('content', 'Conteúdo', data.content, 'textarea', { rows: 5 });
    case 'world': return field('story_summary', 'Resumo', data.story_summary, 'textarea', { rows: 8 });
    default: return '';
  }
}

function getEditValues() {
  const v = id => (document.getElementById(`ef-${id}`)?.value || '').trim();
  switch (_editCtx.type) {
    case 'character': {
      const base = { name: v('name'), description: v('description'), traits: v('traits'), status: v('status'), notes: v('notes') };
      if (_editCtx.data.role !== undefined) base.role = v('role');
      if (_editCtx.data.sheet) {
        const orig = _editCtx.data.sheet;
        // n(): lê número do input; se o elemento não existir (ex: campos omitidos p/ NPC), preserva o valor original
        const n = (id, fallback) => { const el = document.getElementById(`ef-${id}`); return el ? (parseInt(el.value) || 0) : (fallback ?? 0); };
        const f = id => (document.getElementById(`ef-${id}`)?.value || '').trim();
        // CR: campo de texto para NPCs (pode ser "1/4", "1", etc.); preserva original se elemento não existir
        const crEl  = document.getElementById('ef-sheet_cr');
        const crVal = crEl ? (crEl.value.trim() || null) : (orig.cr ?? null);
        base.sheet = { ...orig, classe: f('sheet_classe').toLowerCase() || orig.classe, raca: f('sheet_raca').toLowerCase() || orig.raca, cr: crVal, nivel: n('sheet_nivel', orig.nivel), xp: n('sheet_xp', orig.xp), vida_atual: n('sheet_vida_atual'), vida_max: n('sheet_vida_max'), mana_atual: n('sheet_mana_atual'), mana_max: n('sheet_mana_max'), ca: n('sheet_ca'), proficiencia: n('sheet_proficiencia', orig.proficiencia), forca: n('sheet_forca'), destreza: n('sheet_destreza'), constituicao: n('sheet_constituicao'), inteligencia: n('sheet_inteligencia'), sabedoria: n('sheet_sabedoria'), carisma: n('sheet_carisma'), ouro: n('sheet_ouro'), prata: n('sheet_prata'), cobre: n('sheet_cobre'), equipamentos: { armadura: f('sheet_eq_armadura') || null, escudo: f('sheet_eq_escudo') || null, arma_principal: f('sheet_eq_arma') || null, arma_secundaria: f('sheet_eq_arma_sec') || null, amuleto: f('sheet_eq_amuleto') || null }, death_saves_sucessos: n('sheet_ds_suc'), death_saves_falhas: n('sheet_ds_fail') };
        base.habilidades = _editCtx.data.habilidades || [];
      }
      return base;
    }
    case 'party': return { name: v('name'), role: v('role'), notes: v('notes') };
    case 'location': return { name: v('name'), description: v('description'), details: v('details'), notes: v('notes') };
    case 'flag': return { key: v('flag_key'), value: v('flag_value') };
    case 'event': return { summary: v('summary'), characters_involved: v('characters_involved'), location: v('location'), consequence: v('consequence') };
    case 'diary': return { title: v('title'), chapter: parseInt(v('chapter')) || 1, content: v('content') };
    case 'world': return { story_summary: v('story_summary') };
    default: return {};
  }
}

function addNewFlag() { openEditModal('flag', 'nova', { key: '', value: '' }); }
function addNewCharacter() {
  const isDnd = window._lastMem?.dnd_mode === true || window._lastMem?.campaign_type === 'dnd';
  const base = { name: '', description: '', traits: '', status: 'vivo', notes: '' };
  if (isDnd) base.sheet = { classe: '', raca: '', nivel: 1, xp: 0, forca: 10, destreza: 10, constituicao: 10, inteligencia: 10, sabedoria: 10, carisma: 10, vida_atual: 10, vida_max: 10, mana_atual: 0, mana_max: 0, ca: 10, proficiencia: 2, hit_die: 8, ouro: 0, prata: 0, cobre: 0, equipamentos: { armadura: null, escudo: null, arma_principal: null, arma_secundaria: null, amuleto: null }, condicoes: [], death_saves_sucessos: 0, death_saves_falhas: 0 };
  openEditModal('character', '__novo__', base);
}
function addNewPartyMember() { openEditModal('party', '__novo__', { name: '', role: '', notes: '' }); }
function addNewLocation() { openEditModal('location', '__novo__', { name: '', description: '', details: '', notes: '' }); }
function addNewDiaryEntry() { const chapter = window._lastMem?.chapter || 1; openEditModal('diary', null, { chapter, title: '', content: '' }, -1); }

async function saveCurrentItem() {
  if (!_editCtx) return;
  const { type, key, index } = _editCtx; const values = getEditValues();
  const resolvedKey = (key === '__novo__' && values.name) ? values.name.toLowerCase().trim().replace(/\s+/g, ' ') : key;
  const ep = { character: `/api/memory/characters/${encodeURIComponent(resolvedKey)}`, party: `/api/memory/party/${encodeURIComponent(resolvedKey)}`, location: `/api/memory/locations/${encodeURIComponent(resolvedKey)}`, event: `/api/memory/events/${index}`, diary: index === -1 ? `/api/memory/diary/${(window._lastMem?.diary || []).length}` : `/api/memory/diary/${index}`, world: `/api/memory/world` };
  let url = API + (ep[type] || ''); let body = values;
  if (type === 'flag') {
    if (values.key !== key) await authFetch(`${API}/api/memory/flags/${encodeURIComponent(key)}`, { method: 'DELETE' });
    url = `${API}/api/memory/flags/${encodeURIComponent(values.key)}`; body = { value: values.value };
  }
  if (!url) return;
  const res = await authFetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (res.ok) {
    if (type === 'character' && values.role !== undefined) {
      const isParty = (window._lastMem?.party || []).some(p => (p.name || '').toLowerCase().trim() === key);
      if (isParty) await authFetch(`${API}/api/memory/party/${encodeURIComponent(key)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: values.name, role: values.role || '', notes: values.notes || '' }) });
    }
    closeEditModal(); refreshMemory(); showToast('Salvo com sucesso.');
  }
  else { const e = await res.json(); await showAlert('Erro ao salvar', e.error || 'Erro desconhecido.', 'danger'); }
}

async function deleteCurrentItem() {
  if (!_editCtx) return;
  const { type, key, index } = _editCtx;
  const label = document.getElementById('edit-name').textContent;
  const ok = await showConfirm('Deletar', `<strong>"${label}"</strong> será removido da memória.`, 'danger', 'Deletar');
  if (!ok) return;
  const ep = { character: `/api/memory/characters/${encodeURIComponent(key)}`, party: `/api/memory/party/${encodeURIComponent(key)}`, location: `/api/memory/locations/${encodeURIComponent(key)}`, flag: `/api/memory/flags/${encodeURIComponent(key)}`, event: `/api/memory/events/${index}`, diary: `/api/memory/diary/${index}` };
  const url = API + (ep[type] || ''); if (!url) return;
  const res = await authFetch(url, { method: 'DELETE' });
  if (res.ok) { closeEditModal(); refreshMemory(); showToast('Deletado.'); }
  else await showAlert('Erro', 'Não foi possível remover.', 'danger');
}

window.clearAllViolations = function() {
  const violationsDiv = document.getElementById('sb-violations');
  if (violationsDiv) violationsDiv.innerHTML = '<span class="empty-state">Nenhuma violação detetada.</span>';
};