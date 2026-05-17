// ═══════════════════════════════════════
//  API base (same host)
// ═══════════════════════════════════════
const API = '';

// ═══════════════════════════════════════
//  Altura real do app (fix mobile)
//  position:fixed usa o LAYOUT viewport, que no iOS Safari se
//  estende por trás da barra de URL inferior e no Android pode ir
//  por baixo da barra de sistema. visualViewport.height devolve
//  apenas a área realmente visível. Fixamos --app-height nela.
// ═══════════════════════════════════════
(function () {
  var docEl = document.documentElement;
  function setAppHeight() {
    var vv = window.visualViewport;
    var h = vv ? vv.height : window.innerHeight;
    docEl.style.setProperty('--app-height', Math.round(h) + 'px');
  }
  setAppHeight();
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', setAppHeight);
    window.visualViewport.addEventListener('scroll', setAppHeight);
  }
  window.addEventListener('resize', setAppHeight);
  window.addEventListener('orientationchange', function () {
    setAppHeight();
    setTimeout(setAppHeight, 300);
  });
  window.addEventListener('load', setAppHeight);
})();


// ═══════════════════════════════════════
//  Auth token helpers
// ═══════════════════════════════════════
function getTokens() {
  return {
    access:  localStorage.getItem('rpg_access_token'),
    refresh: localStorage.getItem('rpg_refresh_token')
  };
}

function setTokens(access, refresh) {
  localStorage.setItem('rpg_access_token', access);
  if (refresh) localStorage.setItem('rpg_refresh_token', refresh);
}

function clearTokens() {
  localStorage.removeItem('rpg_access_token');
  localStorage.removeItem('rpg_refresh_token');
  localStorage.removeItem('rpg_token'); // Limpa o antigo por precaução
}

function requireAuth() {
  const tokens = getTokens();
  if (!tokens.access) { 
    window.location.href = '/login.html'; 
    return false; 
  } 
  return true; 
}

async function authFetch(url, opts = {}) {
  const tokens = getTokens();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  
  if (tokens.access) headers['Authorization'] = `Bearer ${tokens.access}`;

  let response = await fetch(url, { ...opts, headers });

  // Se o token expirou (erro 401) e temos um refresh token, tenta renovar silenciosamente
  if (response.status === 401 && tokens.refresh) {
    const refreshRes = await fetch(`${API}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokens.refresh })
    });

    if (refreshRes.ok) {
      const newData = await refreshRes.json();
      
      // Atualiza as chaves no navegador
      setTokens(newData.access_token, newData.refresh_token);
      
      // Refaz a requisição original com a nova chave de acesso válida
      headers['Authorization'] = `Bearer ${newData.access_token}`;
      response = await fetch(url, { ...opts, headers });
    } else {
      // Se o refresh falhar (ex: ficou dias sem jogar e expirou tudo), desloga o usuário
      clearTokens();
      window.location.href = '/login.html';
    }
  }

  return response;
}

// ═══════════════════════════════════════
//  Toast
// ═══════════════════════════════════════
function showToast(msg) {
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}

// ═══════════════════════════════════════
//  Escape HTML
// ═══════════════════════════════════════
function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ═══════════════════════════════════════
//  Dialog system (replaces alert/confirm)
// ═══════════════════════════════════════
let _dlgResolve = null;

const DLG = {
  info:    { icon:'ℹ', ibg:'rgba(68,136,204,0.15)',  ic:'var(--blue)',      accent:'linear-gradient(90deg,transparent,var(--blue),transparent)' },
  warning: { icon:'⚠', ibg:'rgba(200,168,75,0.12)',  ic:'var(--gold)',      accent:'linear-gradient(90deg,transparent,var(--gold-dim),transparent)' },
  danger:  { icon:'✕', ibg:'rgba(196,68,68,0.15)',   ic:'var(--red)',       accent:'linear-gradient(90deg,transparent,var(--red),transparent)' },
  success: { icon:'✓', ibg:'rgba(74,170,128,0.15)',  ic:'var(--green)',     accent:'linear-gradient(90deg,transparent,var(--green),transparent)' },
};

function showAlert(title, msg, type = 'info') {
  return new Promise(r => { _dlgResolve = r; _openDlg(title, msg, type, [{label:'OK', primary:true, value:true}]); });
}
function showConfirm(title, msg, type = 'warning', confirmLabel = 'Confirmar') {
  return new Promise(r => { _dlgResolve = r; _openDlg(title, msg, type, [{label:'Cancelar',primary:false,value:false},{label:confirmLabel,primary:true,value:true}]); });
}

function _openDlg(title, msg, type, buttons) {
  const cfg = DLG[type] || DLG.info;
  document.getElementById('dialog-accent').style.background  = cfg.accent;
  document.getElementById('dialog-icon').textContent         = cfg.icon;
  document.getElementById('dialog-icon').style.background    = cfg.ibg;
  document.getElementById('dialog-icon').style.color         = cfg.ic;
  document.getElementById('dialog-icon').style.border        = `1px solid ${cfg.ic}`;
  document.getElementById('dialog-title').textContent        = title;
  document.getElementById('dialog-message').innerHTML        = msg;

  const btnsEl = document.getElementById('dialog-buttons');
  btnsEl.innerHTML = '';
  buttons.forEach(btn => {
    const el = document.createElement('button');
    el.textContent = btn.label;
    if (btn.primary && type === 'danger') {
      el.className = 'btn-danger'; el.style.background = 'var(--red)'; el.style.color = '#fff';
    } else if (btn.primary) {
      el.className = 'btn-save';
    } else {
      el.className = 'btn-ghost';
    }
    el.addEventListener('click', () => _closeDlg(btn.value));
    btnsEl.appendChild(el);
  });

  document.getElementById('dialog-overlay').classList.remove('hidden');
  // Trava scroll do body (evita que overlay fixed fique desalinhado no mobile)
  if (!document.body.classList.contains('game-page')) {
    document.body.style.overflow = 'hidden';
  }
  setTimeout(() => btnsEl.querySelector('button:last-child')?.focus(), 50);
}

function _closeDlg(val) {
  document.getElementById('dialog-overlay').classList.add('hidden');
  // Restaura scroll do body
  if (!document.body.classList.contains('game-page')) {
    document.body.style.overflow = '';
  }
  if (_dlgResolve) { _dlgResolve(val); _dlgResolve = null; }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('dialog-overlay')?.addEventListener('click', function(e) {
    if (e.target === this) _closeDlg(false);
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !document.getElementById('dialog-overlay')?.classList.contains('hidden'))
      _closeDlg(false);
  });
});

// ═══════════════════════════════════════
//  Sistema de Temas
// ═══════════════════════════════════════
const THEMES = [
  { id: 'pergaminho',    label: 'Pergaminho',       desc: 'Claro e acolhedor',      swatchTop: '#2b303a', swatchBot: '#f5f3eb' },
  { id: 'noite-tinta',  label: 'Noite de Tinta',   desc: 'Escuro e misterioso',    swatchTop: '#16213e', swatchBot: '#1e1e30' },
  { id: 'ardosia',      label: 'Ardósia',           desc: 'Cinza frio e austero',   swatchTop: '#2d3142', swatchBot: '#e8eaf2' },
  { id: 'floresta',     label: 'Floresta Antiga',   desc: 'Verde musgo e terra',    swatchTop: '#1e3020', swatchBot: '#eaf2e8' },
  { id: 'oceano',       label: 'Profundezas',       desc: 'Azul do mar profundo',   swatchTop: '#0d2845', swatchBot: '#e8f2fc' },
  { id: 'sangue-dragao',label: 'Sangue de Dragão',  desc: 'Carmim e trevas',        swatchTop: '#200808', swatchBot: '#1e0e0e' },
  { id: 'poeira-ouro',  label: 'Poeira de Ouro',    desc: 'Sépia e nostalgia',      swatchTop: '#2e2010', swatchBot: '#f0e8d0' },
];

function applyTheme(id) {
  document.documentElement.setAttribute('data-theme', id);
  localStorage.setItem('rpg_theme', id);
  document.querySelectorAll('.settings-theme-option').forEach(el => {
    el.classList.toggle('active', el.dataset.theme === id);
  });
}

function loadTheme() {
  const saved = localStorage.getItem('rpg_theme') || 'pergaminho';
  document.documentElement.setAttribute('data-theme', saved);
}

// ═══════════════════════════════════════
//  Sistema de Fontes
// ═══════════════════════════════════════
const FONT_CATEGORIES = [
  {
    id: 'master', label: 'Mestre', cssVar: '--font-master',
    storageKey: 'rpg_font_master', default: 'Lora',
    options: [
      { id: 'Lora',              label: 'Lora',              desc: 'Atual — serifa clássica',  stack: "'Lora', serif" },
      { id: 'Crimson Text',      label: 'Crimson Text',      desc: 'Serifa elegante',           stack: "'Crimson Text', serif" },
      { id: 'EB Garamond',       label: 'EB Garamond',       desc: 'Serifa histórica',          stack: "'EB Garamond', serif" },
      { id: 'Libre Baskerville', label: 'Libre Baskerville', desc: 'Serifa legível',            stack: "'Libre Baskerville', serif" },
      { id: 'Merriweather',      label: 'Merriweather',      desc: 'Serifa moderna',            stack: "'Merriweather', serif" },
    ],
  },
  {
    id: 'user', label: 'Jogador', cssVar: '--font-user',
    storageKey: 'rpg_font_user', default: 'Caveat',
    options: [
      { id: 'Caveat',          label: 'Caveat',          desc: 'Caligrafia cursiva',        stack: "'Caveat', cursive" },
      { id: 'Kalam',           label: 'Kalam',           desc: 'Escrita à mão limpa',       stack: "'Kalam', cursive" },
      { id: 'Patrick Hand',    label: 'Patrick Hand',    desc: 'Manuscrito casual',          stack: "'Patrick Hand', cursive" },
      { id: 'Dancing Script',  label: 'Dancing Script',  desc: 'Cursiva elegante',           stack: "'Dancing Script', cursive" },
      { id: 'Lora',            label: 'Lora',            desc: 'Serifa — estilo do Mestre',  stack: "'Lora', serif" },
      { id: 'Crimson Text',    label: 'Crimson Text',    desc: 'Serifa elegante formal',     stack: "'Crimson Text', serif" },
      { id: 'EB Garamond',     label: 'EB Garamond',     desc: 'Serifa histórica formal',    stack: "'EB Garamond', serif" },
      { id: 'Raleway',         label: 'Raleway',         desc: 'Sem serifa moderno',         stack: "'Raleway', sans-serif" },
    ],
  },
  {
    id: 'menu', label: 'Títulos', cssVar: '--font-menu',
    storageKey: 'rpg_font_menu', default: 'Playfair Display',
    options: [
      { id: 'Playfair Display',   label: 'Playfair Display',   desc: 'Atual — display serifa',   stack: "'Playfair Display', serif" },
      { id: 'Cinzel',             label: 'Cinzel',             desc: 'Estilo romano clássico',   stack: "'Cinzel', serif" },
      { id: 'Cormorant Garamond', label: 'Cormorant Garamond', desc: 'Display elegante',         stack: "'Cormorant Garamond', serif" },
      { id: 'IM Fell English SC', label: 'IM Fell English',    desc: 'Estilo antigo manuscrito', stack: "'IM Fell English SC', serif" },
    ],
  },
];

function applyFont(catId, fontId) {
  const cat = FONT_CATEGORIES.find(c => c.id === catId);
  if (!cat) return;
  const opt = cat.options.find(o => o.id === fontId) || cat.options[0];
  document.documentElement.style.setProperty(cat.cssVar, opt.stack);
  localStorage.setItem(cat.storageKey, fontId);
  document.querySelectorAll(`.settings-font-option[data-cat="${catId}"]`).forEach(el => {
    el.classList.toggle('active', el.dataset.font === fontId);
  });
}

function loadFonts() {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = 'https://fonts.googleapis.com/css2?family=Kalam:wght@400;700&family=Patrick+Hand&family=Dancing+Script:wght@400;600&family=Raleway:wght@400;500;600&family=Crimson+Text:ital,wght@0,400;0,600;1,400&family=EB+Garamond:ital,wght@0,400;0,500;1,400&family=Libre+Baskerville:ital,wght@0,400;1,400&family=Merriweather:ital,wght@0,400;0,700;1,400&family=Cinzel:wght@400;600&family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&family=IM+Fell+English+SC&display=swap';
  document.head.appendChild(link);
  FONT_CATEGORIES.forEach(cat => {
    const savedId = localStorage.getItem(cat.storageKey) || cat.default;
    const opt = cat.options.find(o => o.id === savedId) || cat.options[0];
    document.documentElement.style.setProperty(cat.cssVar, opt.stack);
  });
}

// ═══════════════════════════════════════
//  Painel de Configurações Unificado
// ═══════════════════════════════════════
const _GEAR = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l-.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;

function toggleSettingsPanel() {
  const panel    = document.getElementById('settings-panel');
  const backdrop = document.getElementById('settings-backdrop');
  if (!panel) return;

  if (panel.classList.contains('open')) {
    // Fechar: remove classe, espera a transição e então esconde via display:none
    panel.classList.remove('open');
    backdrop.classList.remove('open');
    setTimeout(() => {
      panel.style.display    = 'none';
      backdrop.style.display = 'none';
    }, 290);
  } else {
    // Abrir: torna visível primeiro, depois anima na próxima frame
    panel.style.display    = 'flex';
    backdrop.style.display = 'block';
    requestAnimationFrame(() => requestAnimationFrame(() => {
      panel.classList.add('open');
      backdrop.classList.add('open');
    }));
  }
}

function switchSettingsFontTab(catId) {
  document.querySelectorAll('.settings-font-tab').forEach(el =>
    el.classList.toggle('active', el.dataset.cat === catId));
  document.querySelectorAll('.settings-font-list').forEach(el =>
    el.classList.toggle('active', el.dataset.cat === catId));
}

function _injectSettingsPanel() {
  if (document.getElementById('settings-panel')) return;

  const savedTheme = localStorage.getItem('rpg_theme') || 'pergaminho';

  const themesHtml = THEMES.map(t => `
    <button class="settings-theme-option${t.id === savedTheme ? ' active' : ''}"
            data-theme="${t.id}" onclick="applyTheme('${t.id}')" title="${t.desc}">
      <span class="settings-theme-swatch" style="background:linear-gradient(135deg,${t.swatchTop} 45%,${t.swatchBot} 45%)"></span>
      <span class="settings-theme-label">${t.label}</span>
      <span class="settings-theme-check">✓</span>
    </button>`).join('');

  const fontTabsHtml = FONT_CATEGORIES.map((cat, i) =>
    `<button class="settings-font-tab${i === 0 ? ' active' : ''}" data-cat="${cat.id}" onclick="switchSettingsFontTab('${cat.id}')">${cat.label}</button>`
  ).join('');

  const fontListsHtml = FONT_CATEGORIES.map((cat, i) => {
    const savedId = localStorage.getItem(cat.storageKey) || cat.default;
    const optsHtml = cat.options.map(opt => `
      <button class="settings-font-option${opt.id === savedId ? ' active' : ''}"
              data-cat="${cat.id}" data-font="${opt.id}"
              onclick="applyFont('${cat.id}','${opt.id}')" title="${opt.desc}">
        <span class="settings-font-name" style="font-family:${opt.stack}">${opt.label}</span>
        <span class="settings-font-desc">${opt.desc}</span>
      </button>`).join('');
    return `<div class="settings-font-list${i === 0 ? ' active' : ''}" data-cat="${cat.id}">${optsHtml}</div>`;
  }).join('');

  // Backdrop
  const backdrop = document.createElement('div');
  backdrop.id = 'settings-backdrop';
  backdrop.addEventListener('click', toggleSettingsPanel);
  document.body.appendChild(backdrop);

  // Painel
  const panel = document.createElement('div');
  panel.id = 'settings-panel';
  panel.innerHTML = `
    <div class="settings-panel-header">
      <span class="settings-panel-title">Configurações</span>
      <button class="settings-close-btn" onclick="toggleSettingsPanel()" aria-label="Fechar">✕</button>
    </div>
    <div class="settings-body">
      <div class="settings-section">
        <div class="settings-section-title">Aparência</div>
        ${themesHtml}
      </div>
      <div class="settings-section">
        <div class="settings-section-title">Tipografia</div>
        <div class="settings-font-tabs">${fontTabsHtml}</div>
        ${fontListsHtml}
      </div>
    </div>`;
  document.body.appendChild(panel);

  // Botão desktop: fixed no topo-direito, visível apenas em telas largas
  // (não é adicionado ao #chat-area para não interferir no scroll)
  if (document.getElementById('chat-area')) {
    const wrapper = document.createElement('div');
    wrapper.id = 'settings-desktop-wrapper';
    const btn = document.createElement('button');
    btn.className = 'settings-trigger-btn settings-desktop-btn';
    btn.setAttribute('aria-label', 'Configurações');
    btn.innerHTML = _GEAR;
    btn.addEventListener('click', toggleSettingsPanel);
    wrapper.appendChild(btn);
    document.body.appendChild(wrapper);
  }

  // Botão fixo para páginas sem mobile-header (menu, login)
  if (!document.getElementById('mobile-header')) {
    const wrapper = document.createElement('div');
    wrapper.id = 'settings-fixed-wrapper';
    const btn = document.createElement('button');
    btn.className = 'settings-trigger-btn settings-fixed-btn';
    btn.setAttribute('aria-label', 'Configurações');
    btn.innerHTML = _GEAR;
    btn.addEventListener('click', toggleSettingsPanel);
    wrapper.appendChild(btn);
    document.body.appendChild(wrapper);
  }

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && document.getElementById('settings-panel')?.classList.contains('open'))
      toggleSettingsPanel();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  loadTheme();
  loadFonts();
  _injectSettingsPanel();
});