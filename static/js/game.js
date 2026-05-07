// ═══════════════════════════════════════
//  game.js  —  usado em game.html
// ═══════════════════════════════════════
let waiting = false;
let maxRPD = parseInt(localStorage.getItem('rpg_max_rpd') || '500');
let sessionRequests = parseInt(localStorage.getItem('rpg_daily_reqs') || '0');
let sessionTokens = parseInt(localStorage.getItem('rpg_total_tokens') || '0');

// ── Ferramentas que mudam estado visível na sidebar/HUD (HP, mana, turno) ──
// Um refreshMemory() é disparado imediatamente ao receber o tool_result delas,
// sem esperar o evento 'done', para que barras e turn-tracker reajam na hora.
const STATE_TOOLS = new Set([
  'modify_hp', 'modify_mana', 'attack_roll', 'use_ability',
  'next_turn', 'roll_initiative', 'end_combat',
  'apply_condition', 'remove_condition', 'short_rest', 'long_rest',
  'roll_death_save', 'equip_item', 'unequip_item', 'set_stat',
  'modify_currency', 'grant_xp',
]);

// ── D&D: ferramentas que envolvem dados — tratadas de forma especial ──
const DICE_TOOL_NAMES = new Set([
  'roll_dice', 'attack_roll', 'make_skill_check', 'use_ability',
  'roll_death_save', 'grant_xp', 'short_rest', 'long_rest',
  'modify_hp', 'modify_mana',
]);

// Flag para saber se o turno corrente usou ferramentas de dado
let _pendingDiceTools = [];

// ── Bandeja de dados do jogador ──
let _diceTrayOpen = false;

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
  
  clearTokens();
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
          if (DICE_TOOL_NAMES.has(ev.tool.name)) {
            // Ferramentas de dado: mostrar bloco de "dado em mesa" separado
            _pendingDiceTools.push(ev.tool);
          } else {
            pendingTools.push(ev.tool);
          }

          // ── REFRESH ANTECIPADO ───────────────────────────────────────────
          // Para ferramentas de estado, agenda um refresh leve com delay curto
          // (300 ms) — tempo suficiente para o backend processar e salvar.
          // Isso garante que HUD e barras atualizem mesmo se tool_result não
          // for emitido pelo servidor.
          if (STATE_TOOLS.has(ev.tool.name)) {
            setTimeout(() => refreshMemory(), 400);
          }
        }
        // Resultado bruto de ferramenta de dado, emitido pelo server.py
        // (requer: yield sse_event('tool_result', {tool_name, content, is_dice_tool: True}))
        else if (ev.type === 'tool_result') {
          removeTyping(typId);
          appendDiceResultLog(ev.tool_name, ev.content);

          // ── ATUALIZAÇÃO REATIVA ──────────────────────────────────────────
          // Se a ferramenta muda estado visível (HP, mana, turno), atualiza
          // a sidebar e o HUD imediatamente, sem esperar o evento 'done'.
          if (STATE_TOOLS.has(ev.tool_name)) {
            refreshMemory();
          }
        }
        else if (ev.type === 'text') {
          // Esvazia chips de ferramentas narrativas
          if (pendingTools.length) {
            appendToolLog(pendingTools);
            pendingTools = [];
          }
          // Esvazia ferramentas de dado: extrai o resultado matemático do texto
          // e exibe numa caixa "Resultado Bruto" antes da narrativa
          if (_pendingDiceTools.length) {
            const diceNames = _pendingDiceTools.map(t => t.name);
            _pendingDiceTools = [];
            removeTyping(typId);
            renderDiceFromResponse(ev.content, diceNames);
            return; // appendMaster é chamado dentro de renderDiceFromResponse
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
 * Atualiza o painel visual de métricas na sidebar.
 */
function updateQuotaUI() {
  const reqEl = document.getElementById('stat-req');
  const tokEl = document.getElementById('stat-tokens');
  const barEl = document.getElementById('rpm-bar');

  if (reqEl) reqEl.textContent = `${sessionRequests} / ${maxRPD}`;
  if (tokEl) tokEl.textContent = sessionTokens.toLocaleString();

  if (barEl) {
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
    const isDnd = window._lastMem
      ? (window._lastMem.dnd_mode === true || window._lastMem.campaign_type === 'dnd')
      : false;
    const dndText = isDnd
      ? '\n---\n### ⚔️ Comandos D&D (zero tokens)\n' +
        '* **`/ficha [nome]`** · Atributos, CA e equipamentos\n' +
        '* **`/inventario [nome]`** · Itens e moedas\n' +
        '* **`/habilidades [nome]`** · Magias e poderes\n' +
        '* **`/status`** · HP e Mana rápido do grupo\n' +
        '* **`/condicoes [nome]`** · Condições ativas\n' +
        '* **`/combate`** · Iniciativa e turno atual\n' +
        '* **`/rolar <XdY+Z>`** · Rola dado local (ex: `/rolar 2d6+3`)'
      : '';

    appendSystem(
      '## 📜 Comandos\n---\n' +
      '* **`/personagens`** · NPCs e status\n* **`/locais`** · Locais registrados\n' +
      '* **`/grupo`** · Companheiros\n* **`/flags`** · Decisões e estados\n' +
      '* **`/contexto`** · Memória completa\n* **`/diario`** · Crônicas\n' +
      '* **`/resumo`** · Recapitulação\n* **`/exportar`** · Exportar .md\n---\n' +
      '* **`/salvar local <nome>`**\n* **`/salvar personagem <nome>`**\n* **`/salvar evento <desc>`**' +
      dndText
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

  // ─────────────────────────────────────────────────────────────
  //  Comandos D&D — processados localmente, zero tokens de LLM
  // ─────────────────────────────────────────────────────────────

  // Auxiliar: busca personagens alvo ou todo o grupo com ficha
  // Auxiliar: busca personagens alvo ou todo o grupo com ficha
  async function _getDndChars(targetName) {
    const mem = await (await authFetch(`${API}/api/memory`)).json();
    if (!(mem.dnd_mode === true || mem.campaign_type === 'dnd')) return { mem, chars: null };
    
    // Junta as duas listas para a busca: heróis e NPCs
    const allChars = [...mem.party, ...mem.characters];
    let chars;
    
    if (targetName) {
      const c = allChars.find(ch => ch.name.toLowerCase() === targetName && ch.sheet);
      chars = c ? [c] : [];
    } else {
      // Se não passar nome, retorna apenas o grupo de aventureiros (party)
      chars = mem.party.filter(c => c.sheet);
    }
    return { mem, chars };
  }

  // Helper: modificador de atributo D&D
  function _mod(val) { const m = Math.floor((val - 10) / 2); return (m >= 0 ? '+' : '') + m; }

  // /ficha [nome]
  if (cmd.startsWith('/ficha')) {
    const target = raw.trim().split(' ').slice(1).join(' ').toLowerCase();
    const { mem, chars } = await _getDndChars(target);
    if (!chars) { appendSystem('Comando exclusivo do modo D&D.'); return true; }
    if (!chars.length) { appendSystem(target ? `Nenhuma ficha D&D encontrada para '${target}'.` : 'Nenhum membro do grupo possui ficha D&D.'); return true; }

    const text = chars.map(c => {
      const s = c.sheet; const eq = s.equipamentos || {};
      const conds = s.condicoes?.length ? s.condicoes.map(cd => cd.nome || cd).join(', ') : 'Nenhuma';
      const hpBar = s.vida_max > 0 ? Math.round((s.vida_atual / s.vida_max) * 10) : 0;
      const hpVis = '█'.repeat(hpBar) + '░'.repeat(10 - hpBar);
      return (
        `### 🛡️ Ficha — ${c.name}\n` +
        `**Nível ${s.nivel} ${s.classe} (${s.raca})** · XP: ${s.xp}/${s.xp_proximo}\n\n` +
        `❤️ \`${hpVis}\` ${s.vida_atual}/${s.vida_max} HP  ✨ ${s.mana_atual}/${s.mana_max} Mana  🛡️ CA ${s.ca}\n\n` +
        `| FOR | DES | CON | INT | SAB | CAR |\n|-----|-----|-----|-----|-----|-----|\n` +
        `| ${s.forca}(${_mod(s.forca)}) | ${s.destreza}(${_mod(s.destreza)}) | ${s.constituicao}(${_mod(s.constituicao)}) | ${s.inteligencia}(${_mod(s.inteligencia)}) | ${s.sabedoria}(${_mod(s.sabedoria)}) | ${s.carisma}(${_mod(s.carisma)}) |\n\n` +
        `**Equipado:** Arma: ${eq.arma_principal || '—'} · Armadura: ${eq.armadura || '—'} · Escudo: ${eq.escudo || '—'} · Amuleto: ${eq.amuleto || '—'}\n\n` +
        `**Condições:** ${conds}  |  **Saves de morte:** ✅ ${s.death_saves_sucessos || 0} / ❌ ${s.death_saves_falhas || 0}`
      );
    }).join('\n\n---\n\n');
    appendSystem(text); return true;
  }

  // /inventario [nome]
  if (cmd.startsWith('/inventario')) {
    const target = raw.trim().split(' ').slice(1).join(' ').toLowerCase();
    const { mem, chars } = await _getDndChars(target);
    if (!chars) { appendSystem('Comando exclusivo do modo D&D.'); return true; }
    if (!chars.length) { appendSystem(target ? `Nenhuma ficha encontrada para '${target}'.` : 'Nenhum membro do grupo possui ficha D&D.'); return true; }

    const text = chars.map(c => {
      const s = c.sheet; const inv = c.inventario || [];
      const items = inv.length
        ? inv.map(i => `* **${i.nome}** ×${i.qtd}${i.descricao ? ` — *${i.descricao}*` : ''}`).join('\n')
        : '* Bolsa vazia';
      return (
        `### 🎒 Inventário — ${c.name}\n\n` +
        `🪙 **${s.ouro || 0}** Ouro · 🥈 **${s.prata || 0}** Prata · 🟤 **${s.cobre || 0}** Cobre\n\n` +
        `**Itens:**\n${items}`
      );
    }).join('\n\n---\n\n');
    appendSystem(text); return true;
  }

  // /habilidades [nome]
  if (cmd.startsWith('/habilidades')) {
    const target = raw.trim().split(' ').slice(1).join(' ').toLowerCase();
    const { mem, chars } = await _getDndChars(target);
    if (!chars) { appendSystem('Comando exclusivo do modo D&D.'); return true; }
    if (!chars.length) { appendSystem(target ? `Nenhuma ficha encontrada para '${target}'.` : 'Nenhum membro do grupo possui ficha D&D.'); return true; }

    const text = chars.map(c => {
      const habs = c.habilidades || [];
      const list = habs.length
        ? habs.map(h => `* **${h.nome}** · Dado: \`${h.dado}\` · Custo: ${h.custo_mana} mana\n  > *${h.descricao}*`).join('\n\n')
        : '* Nenhuma habilidade aprendida.';
      const mana = c.sheet ? `✨ Mana: **${c.sheet.mana_atual}/${c.sheet.mana_max}**` : '';
      return `### ⚡ Habilidades — ${c.name}  ${mana}\n\n${list}`;
    }).join('\n\n---\n\n');
    appendSystem(text); return true;
  }

  // /status — HP e Mana de todo o grupo em uma linha por personagem
  if (cmd === '/status') {
    const { mem, chars } = await _getDndChars('');
    if (!chars) { appendSystem('Comando exclusivo do modo D&D.'); return true; }
    if (!chars.length) { appendSystem('Nenhum membro do grupo possui ficha D&D.'); return true; }

    const lines = chars.map(c => {
      const s = c.sheet;
      const hpPct = s.vida_max > 0 ? Math.round((s.vida_atual / s.vida_max) * 100) : 0;
      const hpIcon = hpPct > 60 ? '🟢' : hpPct > 30 ? '🟡' : '🔴';
      const conds = s.condicoes?.length ? ` ⚠️ *${s.condicoes.map(cd => cd.nome || cd).join(', ')}*` : '';
      return `${hpIcon} **${c.name}** — ❤️ ${s.vida_atual}/${s.vida_max} HP · ✨ ${s.mana_atual}/${s.mana_max} Mana · 🛡️ CA ${s.ca}${conds}`;
    });
    appendSystem(`### ⚔️ Status do Grupo\n\n${lines.join('\n')}`); return true;
  }

  // /condicoes [nome]
  if (cmd.startsWith('/condicoes')) {
    const target = raw.trim().split(' ').slice(1).join(' ').toLowerCase();
    const { mem, chars } = await _getDndChars(target);
    if (!chars) { appendSystem('Comando exclusivo do modo D&D.'); return true; }
    if (!chars.length) { appendSystem(target ? `Nenhuma ficha encontrada para '${target}'.` : 'Nenhum membro do grupo possui ficha D&D.'); return true; }

    const lines = chars.map(c => {
      const conds = c.sheet?.condicoes || [];
      if (!conds.length) return `**${c.name}** — ✅ Sem condições ativas`;
      return `**${c.name}** — ${conds.map(cd => {
        const nome = cd.nome || cd;
        const dur  = cd.duracao !== undefined ? ` (${cd.duracao} turnos)` : '';
        return `🔴 ${nome}${dur}`;
      }).join(' · ')}`;
    });
    appendSystem(`### 🔴 Condições Ativas\n\n${lines.join('\n')}`); return true;
  }

  // /combate — estado da iniciativa sem chamar a IA
  if (cmd === '/combate') {
    const mem = window._lastMem || await (await authFetch(`${API}/api/memory`)).json();
    const cs = mem.combat_state;
    if (!cs || !cs.is_active) {
      appendSystem('### ⚔️ Combate\n\n*Nenhum combate em andamento.*\nUse `/iniciar combate` ou aguarde o Mestre rolar iniciativa.');
      return true;
    }
    const order = cs.initiative_order || [];
    const idx   = cs.current_turn_index ?? 0;
    const list  = order.map((n, i) => {
      const arrow = i === idx ? ' **◀ VEZ ATUAL**' : i < idx ? ' ~~(já agiu)~~' : '';
      return `${i + 1}. ${n}${arrow}`;
    }).join('\n');
    appendSystem(`### ⚔️ Combate em Andamento — Rodada ${cs.round}\n\n**Vez de:** ${order[idx] || '?'}\n\n**Ordem de iniciativa:**\n${list}`);
    return true;
  }

  // /rolar <XdY+Z> — rola localmente sem gastar tokens
  const mRolar = raw.match(/^\/rolar\s+(.+)/i);
  if (mRolar) {
    const formula = mRolar[1].trim();
    // Suporta: 1d20, 2d6+3, d8-1, 4d4, 1d20+5
    const rollRe = /^(\d*)d(\d+)([+-]\d+)?$/i;
    const match  = formula.replace(/\s+/g, '').match(rollRe);
    if (!match) {
      appendSystem(`⚠️ Fórmula inválida: \`${formula}\`\nFormato: \`XdY\` ou \`XdY+Z\`  (ex: \`2d6+3\`, \`1d20\`, \`d8-1\`)`);
      return true;
    }
    const numDice = parseInt(match[1] || '1');
    const sides   = parseInt(match[2]);
    const bonus   = parseInt(match[3] || '0');
    if (numDice < 1 || numDice > 20 || sides < 2 || sides > 100) {
      appendSystem('⚠️ Limites: 1–20 dados, d2–d100.'); return true;
    }
    const rolls  = Array.from({ length: numDice }, () => Math.floor(Math.random() * sides) + 1);
    const rawSum = rolls.reduce((a, b) => a + b, 0);
    const total  = rawSum + bonus;
    const bonStr = bonus !== 0 ? ` ${bonus >= 0 ? '+' : ''}${bonus}` : '';
    const rollStr = numDice > 1 ? `[${rolls.join(' + ')}]` : `${rolls[0]}`;
    const isCrit   = sides === 20 && numDice === 1 && rolls[0] === 20;
    const isFumble = sides === 20 && numDice === 1 && rolls[0] === 1;
    const tag = isCrit ? ' 🌟 CRÍTICO NATURAL' : isFumble ? ' 💀 FALHA CRÍTICA' : '';
    appendSystem(
      `### 🎲 /rolar ${formula}\n\n` +
      `Resultado: ${rollStr}${bonStr} = **${total}**${tag}\n\n` +
      `*Rolado localmente — não enviado ao Mestre.*`
    );
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

  if (mLocal) { appendSystem(`Registrando local "${mLocal[1]}"...`); await sendToAgent(`Salve o local "${mLocal[1]}" usando save_location com todos os detalhes mencionados. Confirme o que foi registrado.`, true); return true; }
  if (mPerson) { appendSystem(`Registrando "${mPerson[1]}"...`); await sendToAgent(`Salve o personagem "${mPerson[1]}" usando save_character com todos os detalhes. Confirme o que foi registrado.`, true); return true; }
  if (mEvento) { appendSystem(`Registrando evento...`); await sendToAgent(`Salve o evento "${mEvento[1]}" usando save_event. Confirme o que foi registrado.`, true); return true; }

  return false;
}

// ═══════════════════════════════════════
//  Renderização de mensagens
// ═══════════════════════════════════════
const TOOL_META = {
  // Narrativa
  get_character: '👤', get_location: '📍', get_scene_context: '🧭', get_full_context: '📚',
  get_recent_events: '📜', get_flag: '🚩', get_diary: '📖', list_characters: '👥',
  list_locations: '🗺️', list_party: '🫂', list_flags: '🚩', save_character: '💾',
  save_location: '💾', save_event: '💾', set_flag: '🔖', add_diary_entry: '✍️',
  update_character_status: '🔄', update_story_summary: '🔄', update_world_state: '🔄',
  add_party_member: '➕', remove_party_member: '➖', clear_flag: '🗑️',
  // D&D — mecânica de dados
  roll_dice: '🎲', attack_roll: '⚔️', make_skill_check: '🎯', use_ability: '⚡',
  roll_death_save: '💀', modify_hp: '❤️', modify_mana: '✨', grant_xp: '⭐',
  short_rest: '🛌', long_rest: '🌙',
  // D&D — fichas e inventário
  create_character_sheet: '📋', get_character_sheet: '📋', get_combat_status: '⚔️',
  add_item: '📦', remove_item: '🗑️', list_inventory: '📦', learn_ability: '📖',
  set_stat: '🔧',
  // D&D v2
  equip_item: '🗡️', unequip_item: '🗡️', apply_condition: '🔴',
  remove_condition: '🟢', modify_currency: '💰',
};

const TOOL_LABEL = {
  // Narrativa
  get_character: 'lendo personagem', get_location: 'lendo local', get_scene_context: 'verificando cena',
  get_full_context: 'carregando contexto', get_recent_events: 'consultando eventos', get_flag: 'verificando flag',
  get_diary: 'lendo diário', list_characters: 'listando personagens', list_locations: 'listando locais',
  list_party: 'listando grupo', list_flags: 'listando flags', save_character: 'salvando personagem',
  save_location: 'salvando local', save_event: 'salvando evento', set_flag: 'definindo flag',
  add_diary_entry: 'escrevendo no diário', update_character_status: 'atualizando personagem',
  update_story_summary: 'atualizando resumo', update_world_state: 'atualizando mundo',
  add_party_member: 'adicionando ao grupo', remove_party_member: 'removendo do grupo', clear_flag: 'removendo flag',
  // D&D — mecânica de dados
  roll_dice: 'rolando dado', attack_roll: 'resolvendo ataque', make_skill_check: 'teste de habilidade',
  use_ability: 'usando habilidade', roll_death_save: 'teste de morte',
  modify_hp: 'atualizando vida', modify_mana: 'atualizando mana', grant_xp: 'concedendo XP',
  short_rest: 'descanso curto', long_rest: 'descanso longo',
  // D&D — fichas e inventário
  create_character_sheet: 'criando ficha', get_character_sheet: 'lendo ficha',
  get_combat_status: 'status de combate', add_item: 'adicionando item',
  remove_item: 'removendo item', list_inventory: 'listando inventário',
  learn_ability: 'aprendendo habilidade', set_stat: 'ajustando atributo',
  // D&D v2
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

// ═══════════════════════════════════════
//  Fix 2 — Transparência dos dados do Mestre
// ═══════════════════════════════════════

/**
 * Padrões que identificam linhas de resultado matemático puro
 * emitidas pelas ferramentas D&D (tools_dnd.py).
 * Exemplos:
 *   ⚔️  Aldric ataca Goblin com espada!
 *   🎲 Teste de Destreza — CD 15
 *      d20=14 +3(mod) = **17**
 *   ❤️  Vida: 20 → 12/20
 *   ✨ Mana: 10 → 8/10
 */
const DICE_RESULT_RE = /(?:🎲|⚔️|✨|❤️|⚡|💀|🌙|🛌|⭐)[^\n]*/g;

/**
 * Extrai linhas de resultado bruto do texto do Mestre e devolve
 * { raw: string, narrative: string }.
 * As linhas de dado ficam no topo como "Resultado Bruto".
 */
function splitDiceAndNarrative(text) {
  const lines = text.split('\n');
  const raw = [], narrative = [];

  // Heurística: as primeiras linhas com emoji de mecânica D&D são resultado bruto.
  // Assim que encontrar uma linha sem emoji mecânico após o bloco inicial, para.
  let inRawBlock = true;
  for (const line of lines) {
    if (inRawBlock && /^[\s]*(?:🎲|⚔️|✨|❤️|⚡|💀|🌙|🛌|⭐|\s+d20=|\s+Dano:|\s+Custo:|\s+Cura:|\s+Vida:|[✅❌🌟💀⚠️])/.test(line)) {
      raw.push(line);
    } else {
      inRawBlock = false;
      narrative.push(line);
    }
  }
  return {
    raw: raw.join('\n').trim(),
    narrative: narrative.join('\n').trim(),
  };
}

/**
 * Exibe bloco "Resultado Bruto" + narrativa separada.
 * Chamado quando sabemos que uma ferramenta de dado foi usada.
 */
function renderDiceFromResponse(text, diceToolNames) {
  const { raw, narrative } = splitDiceAndNarrative(text);

  if (raw) {
    // Mostra o resultado mecânico numa caixa "mesa pública"
    appendDiceResultLog(diceToolNames[0] || 'roll_dice', raw);
  }

  // Narrativa restante
  if (narrative) {
    appendMaster(narrative);
  } else if (!raw) {
    // Fallback: texto não separável, exibe tudo como narrativa normal
    appendMaster(text);
  }
}

/**
 * Caixa de "Resultado Bruto" — emitido pelo server ou extraído do texto.
 * Simula a sensação de ver o dado cair na mesa.
 */
function appendDiceResultLog(toolName, content) {
  const labels = {
    attack_roll:      '⚔️ Ataque — Resultado da Mesa',
    make_skill_check: '🎯 Teste de Habilidade — Mesa Pública',
    roll_dice:        '🎲 Rolagem de Dado — Mesa Pública',
    use_ability:      '⚡ Habilidade — Resultado da Mesa',
    roll_death_save:  '💀 Teste de Morte — Mesa Pública',
    modify_hp:        '❤️ Variação de Vida',
    modify_mana:      '✨ Variação de Mana',
    grant_xp:         '⭐ XP Concedido',
    short_rest:       '🛌 Descanso Curto',
    long_rest:        '🌙 Descanso Longo',
  };
  const label = labels[toolName] || '🎲 Resultado da Mesa';

  const row = document.createElement('div');
  row.className = 'msg-row dice-result-row';
  row.innerHTML = `
    <div class="dice-result-log">
      <div class="drl-header">
        <span class="drl-label">${label}</span>
        <span class="drl-badge">resultado bruto</span>
      </div>
      <div class="drl-content">${processDiceRolls(escapeHtml(content))}</div>
    </div>`;
  document.getElementById('chat-history').appendChild(row);
  scrollDown();
}

// ═══════════════════════════════════════
//  Fix 1 — Bandeja de Dados do Jogador
// ═══════════════════════════════════════

function toggleDiceTray() {
  if (waiting) return;
  _diceTrayOpen = !_diceTrayOpen;
  const tray = document.getElementById('dice-tray');
  const btn  = document.getElementById('dice-tray-btn');
  tray.classList.toggle('hidden', !_diceTrayOpen);
  btn.classList.toggle('active', _diceTrayOpen);
}

/**
 * Rola um dado do lado do cliente (Math.random — não editável pelo jogador)
 * e envia o resultado ao agente como mensagem travada.
 */
function rollPlayerDie(sides) {
  if (waiting) return;

  const modifier = parseInt(document.getElementById('dice-modifier')?.value) || 0;
  const rawRoll  = Math.floor(Math.random() * sides) + 1;
  const total    = rawRoll + modifier;

  const isCrit   = sides === 20 && rawRoll === 20;
  const isFumble = sides === 20 && rawRoll === 1;

  // Fecha a bandeja
  if (_diceTrayOpen) toggleDiceTray();

  // Renderiza o resultado visualmente (não editável)
  appendPlayerRoll(sides, rawRoll, modifier, total, isCrit, isFumble);

  // Monta mensagem para o agente — clara e não ambígua
  const modText  = modifier !== 0 ? ` ${modifier >= 0 ? '+' : ''}${modifier} (modificador)` : '';
  const critText = isCrit ? ' — CRÍTICO NATURAL!' : isFumble ? ' — FALHA CRÍTICA!' : '';
  const msg = `[DADO DO JOGADOR — rolado pelo sistema, não editável] 1d${sides}${modText}: rolei ${rawRoll}, total ${total}${critText}`;

  // Envia ao agente mas NÃO mostra como mensagem de usuário (já foi renderizado)
  sendToAgent(msg, true);
}

/**
 * Renderiza o resultado do dado do jogador como um card visual distinto
 * que não pode ser confundido com texto digitado.
 */
function appendPlayerRoll(sides, rawRoll, modifier, total, isCrit, isFumble) {
  const modStr = modifier !== 0
    ? `<span class="pr-mod">${modifier >= 0 ? '+' : ''}${modifier}</span>`
    : '';
  const statusCls = isCrit ? 'pr-crit' : isFumble ? 'pr-fumble' : total >= Math.ceil(sides * 0.75) ? 'pr-high' : total <= Math.ceil(sides * 0.25) ? 'pr-low' : '';
  const statusLabel = isCrit ? '🌟 CRÍTICO NATURAL' : isFumble ? '💀 FALHA CRÍTICA' : '';

  const row = document.createElement('div');
  row.className = 'msg-row player-roll-row';
  row.innerHTML = `
    <div class="player-roll-box ${statusCls}">
      <div class="pr-die-face">d${sides}</div>
      <div class="pr-center">
        <div class="pr-eyebrow">🎲 Você rolou</div>
        <div class="pr-total">${total}</div>
        ${modifier !== 0 ? `<div class="pr-breakdown">dado ${rawRoll} ${modStr}</div>` : ''}
      </div>
      ${statusLabel ? `<div class="pr-status">${statusLabel}</div>` : ''}
      <div class="pr-lock" title="Resultado gerado pelo sistema — não editável">🔒</div>
    </div>`;
  document.getElementById('chat-history').appendChild(row);
  scrollDown();
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

// ═══════════════════════════════════════
//  Dado Visual — pré-processamento de texto
// ═══════════════════════════════════════

/**
 * Transforma linhas contendo 🎲 em blocos HTML estilizados.
 * Deve ser chamado ANTES de marked.parse().
 * Suporta formatos como:
 *   🎲 1d20 + 3 = **18**
 *   🎲 2d6: [4 + 2] = **6**
 *   🎲 1d20 = **20** 🌟 CRÍTICO NATURAL
 *   🎲 1d20 = **1** 💀 FALHA CRÍTICA
 */
function processDiceRolls(text) {
  return text.replace(/(🎲[^\n]+)/g, (match) => {
    // Detecta crítico / fumble — inclui variações com e sem espaço
    const isCrit   = /CRÍTICO\s*NATURAL|🌟\s*CRÍTICO|🌟/.test(match);
    const isFumble = /FALHA\s*CRÍTICA|💀\s*FALHA|💀/.test(match);
    const resClass = isCrit ? 'dice-crit' : isFumble ? 'dice-fumble' : '';

    // Extrai o número do resultado: = **N**
    const numMatch = match.match(/=\s*\*\*(\d+)\*\*/);
    if (!numMatch) return match; // sem resultado formatado → mantém original

    const num = numMatch[1];

    // Fórmula: tudo entre 🎲 e = **N**
    const formulaMatch = match.match(/🎲\s*(.+?)\s*=\s*\*\*\d+\*\*/);
    const formula = formulaMatch ? formulaMatch[1].trim() : '';

    // Sufixo após = **N**
    // 1. Captura tudo após o número
    // 2. Remove espaços, vírgulas, pontos e pontos-e-vírgulas soltos
    //    que não carregam sentido (ex: "= **17**," → suffix vazio)
    // 3. Só renderiza se restar pelo menos um caractere alfanumérico ou emoji
    const rawSuffix   = (match.match(/=\s*\*\*\d+\*\*\s*(.*)/) || [])[1] ?? '';
    const suffix      = rawSuffix.trim().replace(/^[\s,;.]+|[\s,;.]+$/g, '');
    const hasMeaning  = /[\p{L}\p{N}\p{Emoji_Presentation}]/u.test(suffix);

    return (
      `<div class="dice-roll-box">` +
        `<span class="dice-formula">🎲 ${formula} =</span>` +
        `<span class="dice-result ${resClass}">${num}</span>` +
        (hasMeaning ? `<span class="dice-suffix">${suffix}</span>` : '') +
      `</div>`
    );
  });
}

async function typewriter(el, text) {
  // Pré-processa rolagens de dado antes do Markdown
  el.innerHTML = marked.parse(processDiceRolls(text));
  el.style.opacity = '0';
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
  const s = document.getElementById('sidebar');
  const o = document.getElementById('sidebar-overlay');

  if (forceClose || s.classList.contains('active')) {
    s.classList.remove('active');
    o.classList.remove('active');
    document.body.style.overflow = '';
  } else {
    s.classList.add('active');
    o.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
}

function applyCampaignConfig(cfg) {
  if (!cfg) return;
  window._campaignConfig = cfg;
  const pt = document.getElementById('sb-party-title'); if (pt) pt.textContent = cfg.party_label || 'Grupo';
}

// ═══════════════════════════════════════
//  D&D — Card de Personagem com Barras
// ═══════════════════════════════════════

/**
 * Constrói o HTML de um card de personagem no modo D&D.
 * Exibe barras de HP (colorida por % de vida) e Mana (azul),
 * badge de CA (Classe de Armadura) e badges de condições.
 *
 * @param {object} c    - objeto do personagem (com c.sheet opcional)
 * @param {number} idx  - índice no array (para referência em window._lastMem)
 * @param {string} type - 'party' | 'character'
 */
function buildDndCharCard(c, idx, type) {
  const sheet = c.sheet || null;

  // ── Dados da ficha ──
  const hpCur  = sheet?.vida_atual  !== undefined ? sheet.vida_atual  : '?';
  const hpMax  = sheet?.vida_max    !== undefined ? sheet.vida_max    : '?';
  const manaCur = sheet?.mana_atual !== undefined ? sheet.mana_atual  : null;
  const manaMax = sheet?.mana_max   !== undefined ? sheet.mana_max    : null;
  const ca      = sheet?.ca !== undefined ? sheet.ca : null;
  const condicoes = Array.isArray(sheet?.condicoes) ? sheet.condicoes : [];

  // ── Porcentagens para largura das barras ──
  const hpPct = (typeof hpMax === 'number' && hpMax > 0 && typeof hpCur === 'number')
    ? Math.min(100, Math.max(0, (hpCur / hpMax) * 100))
    : 0;
  const manaPct = (typeof manaMax === 'number' && manaMax > 0 && typeof manaCur === 'number')
    ? Math.min(100, Math.max(0, (manaCur / manaMax) * 100))
    : 0;

  // ── Cor da barra de HP: verde → dourado → vermelho conforme % ──
  const hpGradient = hpPct > 60
    ? 'linear-gradient(90deg,#2a6b48,#4aaa80)'   // saudável
    : hpPct > 30
      ? 'linear-gradient(90deg,#7a5f10,#c8a84b)' // ferido
      : 'linear-gradient(90deg,#8b2222,#c44444)'; // crítico
  const hpGlow = hpPct > 60
    ? 'rgba(74,170,128,0.4)'
    : hpPct > 30
      ? 'rgba(200,168,75,0.4)'
      : 'rgba(196,68,68,0.4)';

  // ── Status badge ──
  const st = (c.status || '').toLowerCase();
  const stCls = st.includes('mort') ? 'dead' : st.includes('desapar') ? 'missing' : '';

  // ── Referências para o modal de edição ──
  const nameEsc = (c.name || '').replace(/'/g, "\\'");
  const keyEsc  = type === 'party'
    ? nameEsc
    : (c.name || '').toLowerCase().replace(/'/g, "\\'");
  const dataRef = type === 'party'
    ? `window._lastMem.party[${idx}]`
    : `window._lastMem.characters[${idx}]`;

  // ── Monta o HTML ──
  let html = `<div class="char-card editable dnd-char-card" onclick="openEditModal('${type}','${keyEsc}',${dataRef})">`;

  // Cabeçalho: nome + status + CA
  html += `<div class="char-name">${escapeHtml(c.name || '')}`;
  if (c.status) html += `<span class="char-status ${stCls}">${escapeHtml(c.status)}</span>`;
  if (ca !== null) html += `<span class="dnd-ca">🛡️ ${ca}</span>`;
  html += `</div>`;

  if (sheet) {
    // Barra de HP
    html += `
      <div class="stat-bar-wrap">
        <div class="stat-bar-label">
          <span>❤️ HP</span>
          <span>${hpCur}/${hpMax}</span>
        </div>
        <div class="stat-bar-track">
          <div class="stat-bar-fill" style="width:${hpPct}%;background:${hpGradient};box-shadow:0 0 8px ${hpGlow};"></div>
        </div>
      </div>`;

    // Barra de Mana (só se o personagem tiver mana definida)
    if (manaMax !== null && manaMax > 0) {
      html += `
        <div class="stat-bar-wrap">
          <div class="stat-bar-label">
            <span>✨ Mana</span>
            <span>${manaCur}/${manaMax}</span>
          </div>
          <div class="stat-bar-track">
            <div class="stat-bar-fill mana-bar" style="width:${manaPct}%;"></div>
          </div>
        </div>`;
    }

    // Condições ativas
    if (condicoes.length) {
      html += `<div class="condition-badges">`;
      condicoes.forEach(cd => {
        html += `<span class="condition-badge">${escapeHtml(String(cd))}</span>`;
      });
      html += `</div>`;
    }
  } else {
    // Fallback sem ficha: mostra notas ou descrição resumida
    const desc = c.notes || c.description || '';
    if (desc) {
      html += `<div class="char-desc">${escapeHtml(desc.substring(0, 90))}${desc.length > 90 ? '…' : ''}</div>`;
    }
  }

  html += `</div>`;
  return html;
}

// ═══════════════════════════════════════
//  Memória — refresh e render
// ═══════════════════════════════════════

// ═══════════════════════════════════════
//  Turn Tracker — Rastreador de Turnos D&D
// ═══════════════════════════════════════

/**
 * Renderiza o rastreador de turnos de iniciativa.
 * Visível apenas durante combate ativo (combat_state.is_active === true).
 * @param {object|null} cs - combat_state da memória
 */
function renderTurnTracker(cs) {
  const tracker = document.getElementById('turn-tracker');
  if (!tracker) return;

  if (!cs || !cs.is_active || !cs.initiative_order || !cs.initiative_order.length) {
    tracker.classList.add('hidden');
    return;
  }

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
      ${isActive ? '<span class="tt-turn-arrow">▶</span>' : ''}
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
  window._lastMem = mem;
  document.getElementById('sb-location').textContent = mem.current_location || '—';
  document.getElementById('ws-chapter').textContent = mem.chapter || 1;
  document.getElementById('ws-location').textContent = mem.current_location || '—';
  document.getElementById('sb-summary').textContent = mem.story_summary || 'Nenhum resumo ainda.';

  // ── Turn Tracker ──────────────────────────────────────────────────────────
  renderTurnTracker(mem.combat_state);

  // Flags
  const fEl = document.getElementById('sb-flags');
  fEl.innerHTML = !Object.keys(mem.quest_flags).length ? '<span class="empty-state">Nenhuma flag ainda.</span>' :
    Object.entries(mem.quest_flags).map(([k, v]) => `<div class="flag-item editable" onclick="openEditModal('flag','${k}',{key:'${k}',value:'${v.replace(/'/g, "\\'")}'})"><span class="flag-key">${k}</span><span class="flag-val">${v}</span></div>`).join('');

  // Detecta modo D&D
  const isDnd = mem.dnd_mode === true || mem.campaign_type === 'dnd';

  // Injeta os comandos D&D no autocomplete de forma dinâmica, evitando duplicatas
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

  // ── Grupo (party) ──
  const pEl = document.getElementById('sb-party');
  pEl.innerHTML = !mem.party.length
    ? '<span class="empty-state">Nenhum membro ainda.</span>'
    : mem.party.map((p, i) => {
        if (isDnd) return buildDndCharCard(p, i, 'party');
        return `<div class="char-card editable" onclick="openEditModal('party','${p.name.replace(/'/g, "\\'")}',window._lastMem.party[${i}])">` +
          `<div class="char-name">${p.name} <span class="char-status">${p.role || ''}</span></div>` +
          `<div class="char-desc">${p.notes || ''}</div>` +
          `</div>`;
      }).join('');

  // ── Personagens ──
  const cEl = document.getElementById('sb-chars');
  cEl.innerHTML = !mem.characters.length
    ? '<span class="empty-state">Nenhum personagem ainda.</span>'
    : mem.characters.map((c, i) => {
        if (isDnd) return buildDndCharCard(c, i, 'character');
        const st = c.status?.toLowerCase() || 'vivo';
        const cls = st.includes('mort') ? 'dead' : st.includes('desapar') ? 'missing' : '';
        return `<div class="char-card editable" onclick="openEditModal('character','${c.name.toLowerCase().replace(/'/g, "\\'")}',window._lastMem.characters[${i}])">` +
          `<div class="char-name">${c.name}<span class="char-status ${cls}">${c.status}</span></div>` +
          `<div class="char-desc">${(c.description || '').substring(0, 100)}${(c.description || '').length > 100 ? '…' : ''}</div>` +
          `</div>`;
      }).join('');

  // ── Diário ──
  const dEl = document.getElementById('sb-diary');
  dEl.innerHTML = !mem.diary.length ? '<span class="empty-state">Diário vazio.</span>' :
    [...mem.diary].reverse().slice(0, 8).map((d, i) => {
      const ri = mem.diary.length - 1 - i;
      return `<div class="diary-entry editable" onclick="openEditModal('diary',null,window._lastMem.diary[${ri}],${ri})"><div class="diary-entry-title">Cap.${d.chapter} — ${d.title}</div><div class="diary-entry-content">${(d.content || '').substring(0, 160)}${(d.content || '').length > 160 ? '…' : ''}</div></div>`;
    }).join('');

  // ── Locais ──
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
    case 'character': {
      let html = field('name', 'Nome', data.name)
        + field('description', 'Descrição', data.description, 'textarea')
        + field('traits', 'Traços', data.traits, 'textarea', { rows: 2 })
        + field('status', 'Status', data.status, 'select', { options: ['vivo', 'morto', 'ferido', 'desaparecido', 'preso', 'aliado', 'inimigo', 'exilado'] })
        + field('notes', 'Notas', data.notes, 'textarea', { rows: 2 });
      if (data.sheet) {
        const s = data.sheet;
        html += `
          <div style="border-top:1px solid var(--border);margin:12px 0 16px;padding-top:14px;">
            <div style="font-family:'Cinzel',serif;font-size:10px;letter-spacing:0.15em;text-transform:uppercase;color:var(--gold-dim);margin-bottom:12px;">⚔️ Ficha D&D</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              ${field('sheet_vida_atual',  'HP Atual',      s.vida_atual  ?? 0)}
              ${field('sheet_vida_max',    'HP Máximo',     s.vida_max    ?? 0)}
              ${field('sheet_mana_atual',  'Mana Atual',    s.mana_atual  ?? 0)}
              ${field('sheet_mana_max',    'Mana Máx',      s.mana_max    ?? 0)}
              ${field('sheet_ca',          'CA (Armadura)', s.ca          ?? 0)}
              ${field('sheet_xp',          'XP',            s.xp          ?? 0)}
              ${field('sheet_ouro',        'Ouro',          s.ouro        ?? 0)}
              ${field('sheet_prata',       'Prata',         s.prata       ?? 0)}
            </div>
          </div>`;
      }
      return html;
    }
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
    case 'character': {
      const base = { name: v('name'), description: v('description'), traits: v('traits'), status: v('status'), notes: v('notes') };
      if (_editCtx.data.sheet) {
        const numField = id => parseFloat(document.getElementById(`ef-${id}`)?.value) || 0;
        base.sheet = {
          ..._editCtx.data.sheet,
          vida_atual: numField('sheet_vida_atual'),
          vida_max:   numField('sheet_vida_max'),
          mana_atual: numField('sheet_mana_atual'),
          mana_max:   numField('sheet_mana_max'),
          ca:         numField('sheet_ca'),
          xp:         numField('sheet_xp'),
          ouro:       numField('sheet_ouro'),
          prata:      numField('sheet_prata'),
        };
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

function clearAllViolations() {
  const violationsDiv = document.getElementById('sb-violations');
  if (violationsDiv) {
    violationsDiv.innerHTML = '<span class="empty-state">Nenhuma violação detectada.</span>';
  }
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