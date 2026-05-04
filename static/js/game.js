// ═══════════════════════════════════════
//  game.js  —  usado em game.html
// ═══════════════════════════════════════
let waiting = false;
let maxRPD = parseInt(localStorage.getItem('rpg_max_rpd') || '500');
let sessionRequests = parseInt(localStorage.getItem('rpg_daily_reqs') || '0');
let sessionTokens = parseInt(localStorage.getItem('rpg_total_tokens') || '0');

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
  if (!requireAuth()) return;

  const raw = localStorage.getItem('rpg_session');
  if (!raw) { window.location.href = '/menu.html'; return; }

  let session;
  try { session = JSON.parse(raw); } catch (_) { window.location.href = '/menu.html'; return; }

  // Preenche cabeçalho
  document.getElementById('sb-campaign').textContent = session.campaign || '—';
  document.getElementById('sb-model').textContent = session.model || '—';
  document.getElementById('mobile-title').textContent = session.campaign || '—';

  if (session.campaign_config) applyCampaignConfig(session.campaign_config);

  if (session.model_limits) {
    maxRPD = session.model_limits.rpd;
    localStorage.setItem('rpg_max_rpd', maxRPD); // Salva o limite do modelo atual
  }
  updateQuotaUI();

  // Histórico anterior
  if (session.has_history && session.conversation_history?.length) {
    renderHistory(session.conversation_history);
    appendSeparator('— sessão anterior —');
    appendSystem('Sessão retomada — o Mestre está se reancorando...');
  } else {
    appendSystem('Nova sessão iniciada.');
  }

  // 1. LISTENERS (Movidos para cima)
  // Ativa os botões e fechamento de menus antes da IA travar a execução
  document.getElementById('sidebar-overlay').addEventListener('click', () => toggleSidebar(true));
  document.getElementById('edit-overlay').addEventListener('click', function (e) { if (e.target === this) closeEditModal(); });
  document.addEventListener('click', e => {
    if (!e.target.closest('#cmd-menu') && !e.target.closest('#chat-input')) closeCmdMenu();
  });

  // 2. ATUALIZAÇÃO DE UI (Movido para cima)
  refreshMemory();
  document.getElementById('chat-input').focus();

  // 3. ABERTURA DO MESTRE (Movido para o final)
  // O 'await' agora pausa a execução apenas no final, deixando a tela totalmente interativa
  if (session.opening) {
    await sendToAgent(session.opening, false);
  }
});

function showLoadingScreen(message) {
  const overlay = document.createElement('div');
  overlay.id = 'loading-overlay';
  
  // Criamos um fundo escuro desfocado que cobre a tela toda e centraliza o conteúdo
  overlay.style.cssText = `
    position: fixed;
    inset: 0;
    background: rgba(8, 11, 17, 0.9); /* Usa o tom do seu --bg */
    z-index: 99999;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(4px);
    color: var(--gold);
    font-family: 'Cinzel', serif;
    font-size: 16px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  `;
  
  // Reutilizamos a animação 'typeBounce' do seu CSS para ficar no estilo do RPG
  overlay.innerHTML = `
    <div style="display:flex; gap:8px; margin-bottom: 24px;">
      <div class="typing-dot" style="width:10px; height:10px; background:var(--gold);"></div>
      <div class="typing-dot" style="width:10px; height:10px; background:var(--gold);"></div>
      <div class="typing-dot" style="width:10px; height:10px; background:var(--gold);"></div>
    </div>
    <div>${message}</div>
  `;
  
  document.body.appendChild(overlay);
}

// ═══════════════════════════════════════
//  Voltar ao menu
// ═══════════════════════════════════════
async function backToMenu() {
  if (waiting) { await showAlert('Aguarde', 'Espere a narração terminar.', 'warning'); return; }
  const ok = await showConfirm('Encerrar Sessão', 'Sua jornada será salva antes de sair.', 'warning', 'Salvar e Sair');
  if (!ok) return;
  
  // Exibe a tela preta no centro bloqueando qualquer outro clique
  showLoadingScreen('Salvando sua jornada...');
  
  try {
    const r = await authFetch(`${API}/api/session/end`, { method: 'POST' });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error);
  } catch (e) { 
    // Em caso de erro, removemos a tela de carregamento para ele tentar de novo
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.remove();
    await showAlert('Erro ao salvar', e.message, 'danger'); 
    return; 
  }
  
  localStorage.removeItem('rpg_session');
  window.location.href = '/menu.html';
}

async function logout() {
  const ok = await showConfirm('Sair da conta', 'Você será desconectado.', 'warning', 'Sair');
  if (!ok) return;
  
  // Exibe a tela preta no centro bloqueando qualquer outro clique
  showLoadingScreen('Desconectando...');
  
  try { await authFetch(`${API}/api/session/end`, { method: 'POST' }); } catch (_) { }
  
  clearToken();
  localStorage.removeItem('rpg_session');
  window.location.href = '/login.html';
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

// ═══════════════════════════════════════
//  Funções de Comunicação e Chat
// ═══════════════════════════════════════

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

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        const ev = JSON.parse(line.slice(6));

        // Dentro do seu loop de eventos no game.js
        if (ev.type === 'quota') {
          // 1. Incrementa os contadores da sessão atual
          sessionRequests++;
          sessionTokens += (ev.content.total_tokens || 0);

          // 2. Persiste os dados no navegador para sobreviver ao F5
          localStorage.setItem('rpg_daily_reqs', sessionRequests);
          localStorage.setItem('rpg_total_tokens', sessionTokens);

          // 3. Atualiza a interface visual (texto e barra de progresso)
          updateQuotaUI();
        }
        else if (ev.type === 'tool_call') {
          pendingTools.push(ev.tool);
        }
        else if (ev.type === 'text') {
          if (pendingTools.length) {
            appendToolLog(pendingTools);
            pendingTools = [];
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
        else if (ev.type === 'error') {
          removeTyping(typId);
          appendSystem('Erro: ' + ev.content);
        }
        else if (ev.type === 'done') {
          removeTyping(typId);
          refreshMemory();
        }
      }
    }
  } catch (e) {
    removeTyping(typId);
    appendSystem('Erro de conexão: ' + e.message);
  } finally {
    removeTyping(typId);
    waiting = false;
    setInputDisabled(false);
    document.getElementById('chat-input').focus();
  }
}

/**
 * Atualiza o painel visual de métricas na sidebar[cite: 2, 8].
 */
function updateQuotaUI() {
  const reqEl = document.getElementById('stat-req');
  const tokEl = document.getElementById('stat-tokens');
  const barEl = document.getElementById('rpm-bar');

  // Exibe o contador dinâmico (ex: 12 / 50 ou 12 / 2000)[cite: 8, 9]
  if (reqEl) reqEl.textContent = `${sessionRequests} / ${maxRPD}`;
  if (tokEl) tokEl.textContent = sessionTokens.toLocaleString();

  if (barEl) {
    // O cálculo da barra agora usa o maxRPD vindo do backend[cite: 8]
    const dailyPercent = Math.min((sessionRequests / maxRPD) * 100, 100);
    barEl.style.width = dailyPercent + '%';

    // Alerta visual de cota esgotando
    barEl.style.backgroundColor = dailyPercent > 85 ? 'var(--red)' : 'var(--gold)';
  }
}

// ═══════════════════════════════════════
//  Comandos /
// ═══════════════════════════════════════
async function handleSlash(raw) {
  const cmd = raw.trim().toLowerCase();

  if (cmd === '/ajuda') {
    appendSystem(
      '## 📜 Comandos\n---\n' +
      '* **`/personagens`** · NPCs e status\n* **`/locais`** · Locais registrados\n' +
      '* **`/grupo`** · Companheiros\n* **`/flags`** · Decisões e estados\n' +
      '* **`/contexto`** · Memória completa\n* **`/diario`** · Crônicas\n' +
      '* **`/resumo`** · Recapitulação\n* **`/exportar`** · Exportar .md\n---\n' +
      '* **`/salvar local <nome>`**\n* **`/salvar personagem <nome>`**\n* **`/salvar evento <desc>`**'
    );
    return true;
  }

  if (['/personagens', '/locais', '/flags', '/grupo', '/eventos', '/contexto'].includes(cmd)) {
    const mem = await (await authFetch(`${API}/api/memory`)).json(); let text = '';
    if (cmd === '/personagens') text = mem.characters.map(c => `### 👤 ${c.name}\n**Status:** \`${c.status}\`\n${c.description}`).join('\n\n---\n\n') || 'Nenhum personagem.';
    else if (cmd === '/locais') text = (mem.locations || []).map(l => `### 📍 ${l.name}\n${l.description}`).join('\n\n---\n\n') || 'Nenhum local.';
    else if (cmd === '/flags') { const fl = Object.entries(mem.quest_flags); text = fl.length ? `### 🚩 Flags\n${fl.map(([k, v]) => `* **\`${k}\`** ➜ ${v}`).join('\n')}` : 'Nenhuma flag.'; }
    else if (cmd === '/grupo') text = mem.party.map(p => `### 🫂 ${p.name}\n**Função:** ${p.role}\n${p.notes || ''}`).join('\n\n---\n\n') || 'Grupo vazio.';
    else if (cmd === '/eventos') text = mem.events.slice(-5).map(e => `**#${e.index}** — *${e.location}*\n> ${e.summary}`).join('\n\n---\n\n') || 'Nenhum evento.';
    else if (cmd === '/contexto') text = `## 📖 ${document.getElementById('sb-campaign').textContent}\n**Capítulo:** ${mem.chapter} · **Local:** ${mem.current_location}\n\n${mem.story_summary}`;
    appendSystem(text || '—'); return true;
  }

  if (cmd === '/diario') {
    const mem = await (await authFetch(`${API}/api/memory`)).json();
    appendSystem(!mem.diary.length ? 'Diário vazio.' : [...mem.diary].reverse().slice(0, 5).map(d => `### 🔖 Cap.${d.chapter} — ${d.title}\n> ${d.content}`).join('\n\n---\n\n'));
    return true;
  }

  if (cmd === '/exportar') {
    const d = await (await authFetch(`${API}/api/diary/export`, { method: 'POST' })).json();
    appendSystem(`### ✅ Exportado\n💾 \`${d.path.split('/').pop()}\``); return true;
  }

  if (cmd === '/resumo') {
    appendUser('📜 Solicitando recapitulação...');
    await sendToAgent('Faça um resumo dramático e imersivo de todos os eventos importantes. Use get_full_context para garantir precisão.', false);
    return true;
  }

  const mLocal = raw.match(/^\/salvar\s+local\s+(.+)/i);
  const mPerson = raw.match(/^\/salvar\s+personagem\s+(.+)/i);
  const mEvento = raw.match(/^\/salvar\s+evento\s+(.+)/i);

  if (mLocal) { appendSystem(`Registrando local "${mLocal[1]}"...`); await sendToAgent(`Salve o local "${mLocal[1]}" usando save_location com todos os detalhes mencionados. Confirme o que foi registrado.`, true); return true; }
  if (mPerson) { appendSystem(`Registrando "${mPerson[1]}"...`); await sendToAgent(`Salve o personagem "${mPerson[1]}" usando save_character com todos os detalhes. Confirme o que foi registrado.`, true); return true; }
  if (mEvento) { appendSystem(`Registrando evento...`); await sendToAgent(`Salve o evento "${mEvento[1]}" usando save_event. Confirme o que foi registrado.`, true); return true; }

  return false;
}

// ═══════════════════════════════════════
//  Renderização de mensagens
// ═══════════════════════════════════════
const TOOL_META = {
  get_character: '👤', get_location: '📍', get_scene_context: '🧭', get_full_context: '📚',
  get_recent_events: '📜', get_flag: '🚩', get_diary: '📖', list_characters: '👥',
  list_locations: '🗺️', list_party: '🫂', list_flags: '🚩', save_character: '💾',
  save_location: '💾', save_event: '💾', set_flag: '🔖', add_diary_entry: '✍️',
  update_character_status: '🔄', update_story_summary: '🔄', update_world_state: '🔄',
  add_party_member: '➕', remove_party_member: '➖', clear_flag: '🗑️',
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

function renderHistory(history) {
  history.forEach(e => {
    if (e.role === 'user') appendUser(e.text);
    else if (e.role === 'assistant') {
      const row = document.createElement('div'); row.className = 'msg-row master';
      const b = document.createElement('div'); b.className = 'msg-bubble'; b.style.opacity = '0.75';
      b.innerHTML = marked.parse(e.text || '');
      row.innerHTML = '<div class="msg-label">Mestre</div>'; row.appendChild(b);
      document.getElementById('chat-history').appendChild(row);
    }
  });
  scrollDown();
}

function appendSeparator(label) {
  const row = document.createElement('div');
  row.style.cssText = 'display:flex;align-items:center;gap:12px;padding:8px 0;animation:msgIn 0.25s ease forwards;';
  row.innerHTML = `<div style="flex:1;height:1px;background:var(--border)"></div><div style="font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:0.1em;color:var(--text-muted);white-space:nowrap;text-transform:uppercase;">${label}</div><div style="flex:1;height:1px;background:var(--border)"></div>`;
  document.getElementById('chat-history').appendChild(row);
}

function appendUser(text) {
  const row = document.createElement('div'); row.className = 'msg-row user';
  row.innerHTML = `<div class="msg-label">Você</div><div class="msg-bubble">${escapeHtml(text)}</div>`;
  document.getElementById('chat-history').appendChild(row); scrollDown(); return row;
}

function appendMaster(text) {
  const row = document.createElement('div'); row.className = 'msg-row master';
  const b = document.createElement('div'); b.className = 'msg-bubble';
  row.innerHTML = '<div class="msg-label">Mestre</div>'; row.appendChild(b);
  document.getElementById('chat-history').appendChild(row);
  typewriter(b, text); return row;
}

function appendSystem(text) {
  const row = document.createElement('div'); row.className = 'msg-row system';
  const b = document.createElement('div'); b.className = 'msg-bubble';
  b.innerHTML = marked.parse(text); row.appendChild(b);
  document.getElementById('chat-history').appendChild(row); scrollDown(); return row;
}

function appendTyping() {
  const id = 'typ-' + Date.now(); const row = document.createElement('div'); row.className = 'msg-row master'; row.id = id;
  row.innerHTML = `<div class="msg-label">Mestre</div><div class="typing-dots"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
  document.getElementById('chat-history').appendChild(row); scrollDown(); return id;
}

function updateTyping(id, msg) {
  const el = document.getElementById(id); if (!el) return;
  el.innerHTML = `<div class="msg-label">Mestre</div><div class="typing-dots" style="gap:8px;padding:12px 16px;"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div><span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--gold-bright);margin-left:4px;">${msg}</span></div>`;
  scrollDown();
}

function removeTyping(id) { document.getElementById(id)?.remove(); }

async function typewriter(el, text) {
  el.innerHTML = marked.parse(text); el.style.opacity = '0';
  let op = 0;
  const t = setInterval(() => { op = Math.min(1, op + 0.08); el.style.opacity = op; scrollDown(); if (op >= 1) clearInterval(t); }, 20);
}

function renderViolations(violations) {
  const el = document.getElementById('sb-violations');
  if (!violations || !violations.length) { el.innerHTML = '<span class="empty-state">Nenhuma violação detectada.</span>'; return; }
  if (el.querySelectorAll('.violation-item').length >= 9) el.innerHTML = '';
  el.innerHTML = violations.map((v, i) => {
    const uid = `viol-${Date.now()}-${i}`;
    return `<div class="violation-item ${v.severity}" id="${uid}">
      <div style="display:flex;justify-content:space-between;gap:6px;">
        <div class="violation-rule">${v.rule}</div>
        <button onclick="document.getElementById('${uid}').remove();cleanViolations();" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:12px;padding:0 2px;transition:color 0.15s;" onmouseover="this.style.color='var(--text)'" onmouseout="this.style.color='var(--text-muted)'">✕</button>
      </div>
      <div class="violation-msg">${v.message}</div>
      ${v.detail ? `<div class="violation-detail">${v.detail}</div>` : ''}
    </div>`;
  }).join('') + el.innerHTML;
  if (violations.some(v => v.severity === 'erro')) switchTab('mundo');
}

function cleanViolations() {
  const el = document.getElementById('sb-violations');
  if (!el.querySelector('.violation-item')) el.innerHTML = '<span class="empty-state">Nenhuma violação detectada.</span>';
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

function toggleSidebar(forceClose = false) {
  const s = document.getElementById('sidebar'); const o = document.getElementById('sidebar-overlay');
  if (forceClose || s.classList.contains('active')) { s.classList.remove('active'); o.classList.remove('active'); document.body.style.overflow = ''; }
  else { s.classList.add('active'); o.classList.add('active'); document.body.style.overflow = 'hidden'; }
}

function applyCampaignConfig(cfg) {
  if (!cfg) return;
  window._campaignConfig = cfg;
  const pt = document.getElementById('sb-party-title'); if (pt) pt.textContent = cfg.party_label || 'Grupo';
}

async function refreshMemory() {
  try {
    const res = await authFetch(`${API}/api/memory`);
    if (res.status === 401) { clearToken(); window.location.href = '/login.html'; return; }
    const mem = await res.json();
    if (mem.campaign_config) applyCampaignConfig(mem.campaign_config);
    renderMemory(mem);
  } catch (_) { }
}

function renderMemory(mem) {
  window._lastMem = mem;
  document.getElementById('sb-location').textContent = mem.current_location || '—';
  document.getElementById('ws-chapter').textContent = mem.chapter || 1;
  document.getElementById('ws-location').textContent = mem.current_location || '—';
  document.getElementById('sb-summary').textContent = mem.story_summary || 'Nenhum resumo ainda.';

  // Flags
  const fEl = document.getElementById('sb-flags');
  fEl.innerHTML = !Object.keys(mem.quest_flags).length ? '<span class="empty-state">Nenhuma flag ainda.</span>' :
    Object.entries(mem.quest_flags).map(([k, v]) => `<div class="flag-item editable" onclick="openEditModal('flag','${k}',{key:'${k}',value:'${v.replace(/'/g, "\\'")}'})"><span class="flag-key">${k}</span><span class="flag-val">${v}</span></div>`).join('');

  // Grupo
  const pEl = document.getElementById('sb-party');
  pEl.innerHTML = !mem.party.length ? '<span class="empty-state">Nenhum membro ainda.</span>' :
    mem.party.map((p, i) => `<div class="char-card editable" onclick="openEditModal('party','${p.name.replace(/'/g, "\\'")}',window._lastMem.party[${i}])"><div class="char-name">${p.name} <span class="char-status">${p.role}</span></div><div class="char-desc">${p.notes || ''}</div></div>`).join('');

  // Personagens
  const cEl = document.getElementById('sb-chars');
  cEl.innerHTML = !mem.characters.length ? '<span class="empty-state">Nenhum personagem ainda.</span>' :
    mem.characters.map((c, i) => {
      const st = c.status?.toLowerCase() || 'vivo'; const cls = st.includes('mort') ? 'dead' : st.includes('desapar') ? 'missing' : '';
      return `<div class="char-card editable" onclick="openEditModal('character','${c.name.toLowerCase().replace(/'/g, "\\'")}',window._lastMem.characters[${i}])"><div class="char-name">${c.name}<span class="char-status ${cls}">${c.status}</span></div><div class="char-desc">${(c.description || '').substring(0, 100)}${(c.description || '').length > 100 ? '…' : ''}</div></div>`;
    }).join('');

  // Diário
  const dEl = document.getElementById('sb-diary');
  dEl.innerHTML = !mem.diary.length ? '<span class="empty-state">Diário vazio.</span>' :
    [...mem.diary].reverse().slice(0, 8).map((d, i) => {
      const ri = mem.diary.length - 1 - i;
      return `<div class="diary-entry editable" onclick="openEditModal('diary',null,window._lastMem.diary[${ri}],${ri})"><div class="diary-entry-title">Cap.${d.chapter} — ${d.title}</div><div class="diary-entry-content">${(d.content || '').substring(0, 160)}${(d.content || '').length > 160 ? '…' : ''}</div></div>`;
    }).join('');

  // Locais
  const lEl = document.getElementById('sb-locs');
  if (lEl) {
    const locs = mem.locations || [];
    lEl.innerHTML = !locs.length ? '<span class="empty-state">Nenhum local ainda.</span>' :
      locs.map((l, i) => `<div class="char-card editable" onclick="openEditModal('location','${l.name.toLowerCase().replace(/'/g, "\\'")}',window._lastMem.locations[${i}])"><div class="char-name">${l.name}</div><div class="char-desc">${(l.description || '').substring(0, 100)}${(l.description || '').length > 100 ? '…' : ''}</div></div>`).join('');
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
//  Modal de edição de memória
// ═══════════════════════════════════════
let _editCtx = null;

function openEditModal(type, key, data, index = null) {
  if (window.innerWidth <= 768) toggleSidebar(true);
  _editCtx = { type, key, data, index };
  const labels = { character: 'Personagem', party: 'Grupo', location: 'Local', flag: 'Flag', event: 'Evento', diary: 'Diário', world: 'Resumo' };
  document.getElementById('edit-type').textContent = labels[type] || type;
  document.getElementById('edit-name').textContent = data.name || data.title || data.summary || key || '—';
  document.getElementById('edit-body').innerHTML = buildEditFields(type, data);
  document.getElementById('edit-del-btn').style.display = type === 'world' ? 'none' : '';
  document.getElementById('edit-overlay').classList.remove('hidden');
}

function closeEditModal() {
  document.getElementById('edit-overlay').classList.add('hidden'); _editCtx = null;
}

function field(id, label, value, type = 'input', opts = {}) {
  const v = (value || '').toString().replace(/"/g, '&quot;');
  if (type === 'select') {
    const options = (opts.options || []).map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${o}</option>`).join('');
    return `<div class="edit-field"><label>${label}</label><select id="ef-${id}">${options}</select></div>`;
  }
  if (type === 'textarea') return `<div class="edit-field"><label>${label}</label><textarea id="ef-${id}" rows="${opts.rows || 3}">${(value || '').replace(/</g, '&lt;')}</textarea></div>`;
  return `<div class="edit-field"><label>${label}</label><input id="ef-${id}" type="text" value="${v}"></div>`;
}

function buildEditFields(type, data) {
  switch (type) {
    case 'character': return field('name', 'Nome', data.name) + field('description', 'Descrição', data.description, 'textarea') + field('traits', 'Traços', data.traits, 'textarea', { rows: 2 }) + field('status', 'Status', data.status, 'select', { options: ['vivo', 'morto', 'ferido', 'desaparecido', 'preso', 'aliado', 'inimigo', 'exilado'] }) + field('notes', 'Notas', data.notes, 'textarea', { rows: 2 });
    case 'party': return field('name', 'Nome', data.name) + field('role', 'Função', data.role) + field('notes', 'Notas', data.notes, 'textarea', { rows: 2 });
    case 'location': return field('name', 'Nome', data.name) + field('description', 'Descrição', data.description, 'textarea') + field('details', 'Detalhes', data.details, 'textarea', { rows: 2 }) + field('notes', 'Notas', data.notes, 'textarea', { rows: 2 });
    case 'flag': return field('flag_key', 'Nome da Flag', data.key) + field('flag_value', 'Valor', data.value);
    case 'event': return field('summary', 'Resumo', data.summary, 'textarea', { rows: 2 }) + field('characters_involved', 'Personagens', data.characters_involved) + field('location', 'Local', data.location) + field('consequence', 'Consequência', data.consequence, 'textarea', { rows: 2 });
    case 'diary': return field('title', 'Título', data.title) + field('chapter', 'Capítulo', data.chapter) + field('content', 'Conteúdo', data.content, 'textarea', { rows: 5 });
    case 'world': return field('story_summary', 'Resumo', data.story_summary, 'textarea', { rows: 8 });
    default: return '';
  }
}

function getEditValues() {
  const v = id => (document.getElementById(`ef-${id}`)?.value || '').trim();
  switch (_editCtx.type) {
    case 'character': return { name: v('name'), description: v('description'), traits: v('traits'), status: v('status'), notes: v('notes') };
    case 'party': return { name: v('name'), role: v('role'), notes: v('notes') };
    case 'location': return { name: v('name'), description: v('description'), details: v('details'), notes: v('notes') };
    case 'flag': return { key: v('flag_key'), value: v('flag_value') };
    case 'event': return { summary: v('summary'), characters_involved: v('characters_involved'), location: v('location'), consequence: v('consequence') };
    case 'diary': return { title: v('title'), chapter: parseInt(v('chapter')) || 1, content: v('content') };
    case 'world': return { story_summary: v('story_summary') };
    default: return {};
  }
}

async function saveCurrentItem() {
  if (!_editCtx) return;
  const { type, key, index } = _editCtx; const values = getEditValues();
  const ep = { character: `/api/memory/characters/${encodeURIComponent(key)}`, party: `/api/memory/party/${encodeURIComponent(key)}`, location: `/api/memory/locations/${encodeURIComponent(key)}`, event: `/api/memory/events/${index}`, diary: `/api/memory/diary/${index}`, world: `/api/memory/world` };

  let url = API + (ep[type] || ''); let body = values;
  if (type === 'flag') {
    if (values.key !== key) await authFetch(`${API}/api/memory/flags/${encodeURIComponent(key)}`, { method: 'DELETE' });
    url = `${API}/api/memory/flags/${encodeURIComponent(values.key)}`; body = { value: values.value };
  }
  if (!url) return;

  const res = await authFetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (res.ok) { closeEditModal(); refreshMemory(); showToast('Salvo com sucesso.'); }
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
