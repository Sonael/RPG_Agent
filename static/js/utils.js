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
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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

// ═══════════════════════════════════════
//  Guia "Como Jogar" (injetado em game e menu)
// ═══════════════════════════════════════
const _HELP_ICON = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;

const _GUIDE_HTML = `
  <div class="guide-box">
    <div class="guide-header">
      <div>
        <div class="guide-subtitle">Guia do Aventureiro</div>
        <div class="guide-title">Como Jogar</div>
      </div>
      <button onclick="closeGuide()" class="close-btn" aria-label="Fechar">✕</button>
    </div>

    <div class="guide-body scroll-area">
      <p class="guide-intro">
        Aqui <b>você é o protagonista</b>. A inteligência artificial é o seu
        <b>Mestre</b>: ela narra o mundo, dá voz aos personagens, controla os
        inimigos e reage a tudo o que você decidir. Para jogar, basta
        <b>escrever o que o seu personagem faz ou diz</b>, em linguagem
        natural — como se contasse uma história junto com um amigo.
      </p>

      <div id="guide-mode-banner" class="guide-banner"></div>

      <details class="guide-sec guide-install-block" id="guide-install-sec">
        <summary>📲 Instalar como aplicativo</summary>
        <div class="guide-sec-body">
          <p id="guide-install-status" class="guide-tip" style="display:none;"></p>
          <p>
            Dá para instalar o RPG Agent como um <b>aplicativo de verdade</b>:
            ele ganha um ícone na tela inicial e abre em <b>tela cheia</b>, sem
            a barra do navegador — igual a um app baixado de loja, mas sem
            ocupar espaço nem passar por loja nenhuma.
          </p>
          <button type="button" id="guide-install-btn" class="guide-install-btn" style="display:none;">
            📲 Instalar agora
          </button>
          <div id="guide-install-android">
            <h4 class="guide-h4">🤖 Android (Chrome)</h4>
            <ul>
              <li>Toque no menu <b>⋮</b> no canto superior direito.</li>
              <li>Escolha <b>«Instalar aplicativo»</b> (ou «Adicionar à tela inicial»).</li>
              <li>Confirme — o ícone ⚔️ aparece na sua tela inicial.</li>
            </ul>
          </div>
          <div id="guide-install-ios">
            <h4 class="guide-h4">🍎 iPhone / iPad (Safari)</h4>
            <ul>
              <li>Abra o site no <b>Safari</b> (só funciona pelo Safari).</li>
              <li>Toque no botão <b>Compartilhar</b> (o quadrado com a seta ↑).</li>
              <li>Role a lista e escolha <b>«Adicionar à Tela de Início»</b>.</li>
              <li>Toque em <b>Adicionar</b> — o ícone ⚔️ aparece na tela inicial.</li>
            </ul>
          </div>
          <p class="guide-tip">
            Na primeira vez após um tempo parado, o app pode levar até cerca de
            1 minuto para acordar. É normal — ele entra sozinho assim que o
            servidor estiver pronto.
          </p>
        </div>
      </details>

      <details class="guide-sec" open>
        <summary>🗣️ Conversando com o Mestre</summary>
        <div class="guide-sec-body">
          <p>Não existe forma "certa" de escrever. Diga o que quiser fazer:</p>
          <ul>
            <li>«Pergunto ao taberneiro sobre os rumores na estrada.»</li>
            <li>«Examino a porta com cuidado antes de a abrir.»</li>
            <li>«Tento convencer o guarda a me deixar passar.»</li>
          </ul>
          <p>
            O Mestre responde narrando o que acontece. Use <b>Enter</b> para
            enviar e <b>Shift+Enter</b> para pular uma linha.
          </p>
          <p class="guide-tip">
            Diferente de um chatbot comum, este Mestre <b>não esquece</b>: tudo
            o que importa (quem você conheceu, onde esteve, o que aconteceu)
            fica guardado numa memória à parte e volta sempre, mesmo depois de
            muitas horas de jogo.
          </p>
        </div>
      </details>

      <details class="guide-sec">
        <summary>✋ Você manda na história — corrigindo o Mestre</summary>
        <div class="guide-sec-body">
          <p>
            Esta é talvez a parte mais importante: <b>se você não gostar de
            como uma cena foi narrada, é só dizer</b>. O Mestre aceita
            correções e reescreve. Você é coautor, não um espectador.
          </p>
          <ul>
            <li>«Na verdade, meu personagem nunca concordaria com isso. Refaça a cena.»</li>
            <li>«Espera — eu nunca disse que larguei a espada.»</li>
            <li>«Prefiro que o NPC reaja com medo, não com raiva.»</li>
            <li>«Você trocou o nome do ferreiro; ele se chama Doran.»</li>
          </ul>
          <p>Também dá para ajustar o <b>tom e o ritmo</b> a qualquer momento:</p>
          <ul>
            <li>«Deixa a atmosfera mais sombria.»</li>
            <li>«Menos descrição, mais ação.»</li>
            <li>«Vá mais devagar, quero explorar este lugar.»</li>
          </ul>
          <p class="guide-tip">
            Se o Mestre inventar um detalhe errado (um item que você não tem,
            um lugar onde você nunca esteve), basta apontar e ele corrige.
          </p>
        </div>
      </details>

      <details class="guide-sec">
        <summary>📖 A barra lateral: Mundo, Enciclopédia e Diário</summary>
        <div class="guide-sec-body">
          <p>
            Durante o jogo, a barra lateral mostra o "estado" da sua aventura.
            No computador ela fica à esquerda; no celular, toque no botão
            <b>☰</b> no topo para abri-la. Ela tem três abas:
          </p>
          <ul>
            <li><b>Mundo</b> — o capítulo e o local atuais, avisos de
              Validação, o Resumo da história e as Observações (flags).</li>
            <li><b>Enciclopédia</b> — o seu grupo, os personagens (NPCs) que
              você conheceu e os locais registrados.</li>
            <li><b>Diário</b> — as crônicas da aventura, capítulo a capítulo.
              Pode ser exportado como arquivo <b>.md</b>.</li>
          </ul>
        </div>
      </details>

      <details class="guide-sec">
        <summary>🧩 Os conceitos do jogo</summary>
        <div class="guide-sec-body">
          <p>Tudo o que o Mestre "lembra" é organizado nestes registros:</p>
          <dl class="guide-dl">
            <dt>Personagens</dt>
            <dd>As pessoas que você encontra (NPCs) e os companheiros do seu
              grupo. Cada um tem nome, descrição e um <i>status</i> (vivo,
              ferido, aliado, morto…).</dd>

            <dt>Locais</dt>
            <dd>Os lugares que você visita ou ouve falar. Ajudam o Mestre a
              manter o mapa do mundo coerente.</dd>

            <dt>Eventos</dt>
            <dd>Os marcos importantes da história — aquilo que aconteceu e que
              vale a pena lembrar mais tarde.</dd>

            <dt>Resumo</dt>
            <dd>Uma recapitulação curta de tudo até agora. Você pode editá-la
              clicando em <i>(editar)</i> na aba Mundo.</dd>

            <dt>Observações (Flags)</dt>
            <dd>
              Uma <b>flag</b> é uma anotação que o mundo guarda: uma
              <b>decisão, um segredo ou um estado</b> que tem consequências
              mais tarde. Por exemplo: <code>portão_norte = aberto</code>,
              <code>rei_confia_em_você = sim</code>,
              <code>veneno_no_vinho = verdadeiro</code>. Servem para a
              história ser <b>coerente no longo prazo</b>: se você abriu um
              portão no capítulo 1, ele continua aberto no capítulo 5; se um
              NPC desconfia de você, isso pesa nas próximas conversas.
            </dd>

            <dt>Diário</dt>
            <dd>A narrativa escrita da aventura, dividida por capítulos.</dd>

            <dt>Validação</dt>
            <dd>Avisos automáticos (não são erros) que aparecem quando algo
              parece inconsistente — por exemplo, um personagem dado como
              morto sendo narrado como ativo. Você pode limpá-los quando
              quiser.</dd>
          </dl>
        </div>
      </details>

      <details class="guide-sec">
        <summary>⌨️ Quando o Mestre esquece de salvar algo — comandos /</summary>
        <div class="guide-sec-body">
          <p>
            Dentro do jogo, digite <b>/</b> no campo de mensagem para abrir o
            menu de comandos. Use as setas e <b>Enter</b> (ou <b>Tab</b>) para
            escolher. Os comandos servem para <b>consultar</b> e
            <b>corrigir</b> a memória.
          </p>
          <p><b>Para consultar (em qualquer campanha):</b></p>
          <ul class="guide-cmds">
            <li><code>/personagens</code> — lista os NPCs e seus status</li>
            <li><code>/locais</code> — locais registrados</li>
            <li><code>/grupo</code> — companheiros do grupo</li>
            <li><code>/eventos</code> — os últimos acontecimentos</li>
            <li><code>/flags</code> — as observações/decisões guardadas</li>
            <li><code>/diario</code> — entradas do diário</li>
            <li><code>/resumo</code> — recapitulação da história</li>
            <li><code>/contexto</code> — a memória completa</li>
            <li><code>/exportar</code> — baixa o diário em .md</li>
            <li><code>/ajuda</code> — mostra todos os comandos</li>
          </ul>
          <p>
            <b>Esqueceu de salvar?</b> Se o Mestre não registrou um personagem,
            local ou evento que você considera importante, salve você mesmo:
          </p>
          <ul class="guide-cmds">
            <li><code>/salvar personagem &lt;nome&gt;</code></li>
            <li><code>/salvar local &lt;nome&gt;</code></li>
            <li><code>/salvar evento &lt;descrição&gt;</code></li>
          </ul>
          <p class="guide-tip">
            Você também pode simplesmente <b>pedir ao Mestre</b>: «Registre o
            ferreiro Doran como personagem» ou «Salve que descobrimos a caverna
            escondida». Ele guarda na memória para você.
          </p>
        </div>
      </details>

      <details class="guide-sec">
        <summary>✏️ Editando e corrigindo à mão</summary>
        <div class="guide-sec-body">
          <p>
            Durante o jogo, tudo na barra lateral pode ser ajustado
            diretamente — útil quando o Mestre erra um detalhe ou esquece algo:
          </p>
          <ul>
            <li><b>Clique em qualquer registro</b> (personagem, local, flag…)
              para abrir o editor.</li>
            <li>Use os botões <b>+ Adicionar / + Personagem / + Local /
              + Entrada</b> para criar algo novo.</li>
            <li>Dentro do editor, <b>Deletar Registro</b> remove o item.</li>
            <li><b>Limpar Todas</b> apaga os avisos de Validação.</li>
          </ul>
        </div>
      </details>

      <details id="guide-dnd-sec" class="guide-sec guide-dnd-block">
        <summary>🎲 Modo D&amp;D — regras de verdade</summary>
        <div class="guide-sec-body">
          <p class="guide-dnd-note">
            <b>Atenção:</b> esta seção só vale para campanhas de
            <b>Regras D&amp;D</b>. Nos modos puramente narrativos (Fantasia,
            Romance, Horror…) nada disto aparece — lá a história é livre, sem
            fichas nem combate por turnos.
          </p>
          <p>
            No modo D&amp;D, além da narrativa, valem as <b>regras de D&amp;D
            5e</b>. A grande diferença: <b>os números são decididos por
            dados, não pela vontade do Mestre</b>. Ele não pode "decidir" que
            você acertou um golpe — ele <b>rola</b> e narra o resultado.
          </p>

          <dl class="guide-dl">
            <dt>A Ficha</dt>
            <dd>Cada personagem tem atributos (Força, Destreza, Constituição,
              Inteligência, Sabedoria, Carisma), Vida (HP), Mana (MP) para
              magias, Classe de Armadura (CA), nível, classe e raça.</dd>

            <dt>O botão de dados 🎲</dt>
            <dd>Quando o jogo pede um teste, você rola o seu próprio dado (d20
              e companhia) pelo botão 🎲 ao lado do campo de mensagem. O
              resultado <b>real</b> que você tirou é o que conta.</dd>

            <dt>Inventário e moedas</dt>
            <dd>Itens, equipamentos e moedas (ouro, prata, cobre). Equipar uma
              armadura ou escudo muda a sua CA automaticamente.</dd>

            <dt>Habilidades e magias</dt>
            <dd>Poderes e feitiços que normalmente custam Mana para usar.</dd>

            <dt>Condições</dt>
            <dd>Estados como Envenenado, Cego ou Atordoado, com efeitos
              mecânicos reais durante o combate.</dd>

            <dt>XP e subir de nível</dt>
            <dd>Você ganha experiência ao vencer desafios e sobe de nível
              automaticamente, ganhando vida, perícias e poderes.</dd>

            <dt>Descansos</dt>
            <dd>Descanso curto e descanso longo recuperam Vida, Mana e
              recursos.</dd>
          </dl>

          <p><b>Comandos exclusivos do D&amp;D:</b></p>
          <ul class="guide-cmds">
            <li><code>/ficha [nome]</code> — atributos, CA e equipamentos</li>
            <li><code>/inventario [nome]</code> — itens e moedas</li>
            <li><code>/habilidades [nome]</code> — magias e poderes</li>
            <li><code>/status</code> — Vida e Mana de todo o grupo</li>
            <li><code>/condicoes [nome]</code> — condições ativas</li>
            <li><code>/combate</code> — ordem de iniciativa e turno atual</li>
            <li><code>/rolar &lt;XdY+Z&gt;</code> — rola uma fórmula (ex.: /rolar 2d6+3)</li>
          </ul>

          <h4 class="guide-h4">⚔️ O combate: dois modos</h4>
          <p>
            O combate acontece por <b>turnos</b>, seguindo uma ordem de
            iniciativa. Você escolhe como quer vivê-lo (na barra lateral →
            aba <b>Mundo</b> → <b>Modo de Combate</b>):
          </p>
          <ul>
            <li><b>📖 Narrado pela IA</b> — o Mestre descreve cada turno no
              próprio chat, como o resto da história.</li>
            <li><b>⚔️ Tela tática</b> — abre uma tela dedicada (o "Pergaminho
              Épico") com cards de Vida/Mana e botões: <b>Atacar, Habilidade,
              Item, Defender, Fugir</b> e <b>Encerrar Turno</b>. Os inimigos
              agem sozinhos. No fim da luta, o Mestre narra a batalha inteira
              de uma vez.</li>
          </ul>
          <p class="guide-tip">
            Na tela tática você pode fechar a tela no meio da luta (botão ✕) e
            <b>retomar depois</b> de onde parou — o combate fica pausado e
            salvo.
          </p>
        </div>
      </details>

      <details class="guide-sec">
        <summary>💡 Dicas rápidas</summary>
        <div class="guide-sec-body">
          <ul>
            <li>Seja específico: quanto mais detalhe na sua ação, melhor a narração.</li>
            <li>Não gostou de uma cena? <b>Corrija</b> — você é coautor.</li>
            <li>Confira a barra lateral para acompanhar o estado do mundo.</li>
            <li>Se o Mestre esquecer algo importante, salve à mão ou peça para ele salvar.</li>
            <li>Sua jornada é <b>salva automaticamente</b> quando você volta ao menu.</li>
          </ul>
        </div>
      </details>
    </div>`;

function openGuide() {
  const ov = document.getElementById('guide-overlay');
  if (!ov) return;
  // No jogo, fecha a sidebar no mobile para não sobrepor
  if (typeof toggleSidebar === 'function') toggleSidebar(true);

  const mem = (typeof window !== 'undefined') ? window._lastMem : null;
  const banner = document.getElementById('guide-mode-banner');
  const STYLE_LABELS = {
    dnd: 'Regras D&D', fantasia: 'Fantasia', romance: 'Romance',
    horror: 'Horror', misterio: 'Mistério', scifi: 'Ficção Científica',
    faroeste: 'Faroeste'
  };

  if (banner) {
    if (!mem) {
      // Fora de uma campanha (ex.: menu): guia genérico, sem aviso de modo
      banner.className = 'guide-banner';
      banner.style.display = 'none';
    } else {
      banner.style.display = '';
      const isDnd = mem.dnd_mode === true || mem.campaign_type === 'dnd';
      const label = STYLE_LABELS[mem.campaign_type] || (isDnd ? 'Regras D&D' : 'Narrativo');
      if (isDnd) {
        banner.className = 'guide-banner is-dnd';
        banner.innerHTML = `Esta é uma campanha de <b>${label}</b>. Tudo abaixo se aplica, <b>incluindo a seção do Modo D&D</b> (fichas, dados e combate por turnos).`;
      } else {
        banner.className = 'guide-banner is-narrative';
        banner.innerHTML = `Esta é uma campanha <b>narrativa (${label})</b>. A história é livre e com memória — a seção <b>«Modo D&D»</b> no fim <b>não se aplica</b> a esta campanha.`;
      }
    }
  }

  _refreshInstallSection();

  ov.classList.remove('hidden');
  const body = ov.querySelector('.guide-body');
  if (body) body.scrollTop = 0;
}

function closeGuide() {
  const ov = document.getElementById('guide-overlay');
  if (ov) ov.classList.add('hidden');
}

function _makeHelpBtn(extraClass) {
  const btn = document.createElement('button');
  btn.className = 'help-trigger-btn' + (extraClass ? ' ' + extraClass : '');
  btn.setAttribute('aria-label', 'Como Jogar');
  btn.setAttribute('title', 'Como Jogar');
  btn.innerHTML = _HELP_ICON;
  btn.addEventListener('click', openGuide);
  return btn;
}

function _injectGuide() {
  // Só nas páginas de jogo e menu (não no login)
  const isGame = !!document.getElementById('chat-area');
  const isMenu = !!document.getElementById('campaign-list');
  if (!isGame && !isMenu) return;
  if (document.getElementById('guide-overlay')) return;

  // Overlay
  const ov = document.createElement('div');
  ov.id = 'guide-overlay';
  ov.className = 'hidden';
  ov.innerHTML = _GUIDE_HTML;
  document.body.appendChild(ov);
  ov.addEventListener('click', e => { if (e.target === ov) closeGuide(); });

  // Botão no header mobile do jogo (antes da engrenagem)
  const mh = document.getElementById('mobile-header');
  if (mh) {
    const gear = mh.querySelector('.settings-trigger-btn');
    const btn = _makeHelpBtn();
    if (gear) mh.insertBefore(btn, gear); else mh.appendChild(btn);
  }

  // Botão flutuante de desktop (jogo), à esquerda da engrenagem
  if (isGame) {
    const wrapper = document.createElement('div');
    wrapper.id = 'guide-desktop-wrapper';
    wrapper.appendChild(_makeHelpBtn('help-desktop-btn'));
    document.body.appendChild(wrapper);
  }

  // Botão fixo para páginas sem header mobile (menu), à esquerda da engrenagem
  if (!mh) {
    const wrapper = document.createElement('div');
    wrapper.id = 'guide-fixed-wrapper';
    wrapper.appendChild(_makeHelpBtn('help-fixed-btn'));
    document.body.appendChild(wrapper);
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeGuide();
});

// ═══════════════════════════════════════
//  PWA: seção "Instalar como aplicativo" do guia
// ═══════════════════════════════════════
// Guarda o evento do Chrome/Android para acionar o instalador nativo a partir
// do nosso botão (em vez de depender do mini-banner padrão do navegador).
let _deferredInstallPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  _deferredInstallPrompt = e;
  _refreshInstallSection();
});

window.addEventListener('appinstalled', () => {
  _deferredInstallPrompt = null;
  _refreshInstallSection();
});

// true se já está rodando como app instalado (tela cheia, sem navegador).
function _isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches ||
         window.navigator.standalone === true;
}

// iPhone/iPad (inclui iPad recente que se identifica como "MacIntel").
function _isIOSDevice() {
  const ua = navigator.userAgent || '';
  return /iphone|ipad|ipod/i.test(ua) ||
         (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

// Adapta a seção de instalação ao aparelho/estado atual.
function _refreshInstallSection() {
  const status = document.getElementById('guide-install-status');
  if (!status) return;  // guia ainda não injetado nesta página
  const btn     = document.getElementById('guide-install-btn');
  const android = document.getElementById('guide-install-android');
  const ios     = document.getElementById('guide-install-ios');

  // Já instalado: mostra confirmação e esconde instruções/botão.
  if (_isStandalone()) {
    status.style.display = '';
    status.textContent = '✅ Você já está usando o RPG Agent instalado como aplicativo.';
    if (btn) btn.style.display = 'none';
    if (android) android.style.display = 'none';
    if (ios) ios.style.display = 'none';
    return;
  }
  status.style.display = 'none';

  // Botão nativo: só aparece quando o navegador disponibiliza o prompt
  // (Chrome/Edge no Android e no desktop). iOS/Safari não expõe essa API.
  if (btn) {
    if (_deferredInstallPrompt) {
      btn.style.display = '';
      btn.onclick = async () => {
        const ev = _deferredInstallPrompt;
        if (!ev) return;
        _deferredInstallPrompt = null;
        btn.style.display = 'none';
        ev.prompt();
        try { await ev.userChoice; } catch (_) {}
        _refreshInstallSection();
      };
    } else {
      btn.style.display = 'none';
    }
  }

  // Mostra apenas as instruções relevantes ao aparelho.
  const isIOS = _isIOSDevice();
  if (android) android.style.display = isIOS ? 'none' : '';
  if (ios)     ios.style.display     = isIOS ? '' : 'none';
}

document.addEventListener('DOMContentLoaded', () => {
  loadTheme();
  loadFonts();
  _injectSettingsPanel();
  _injectGuide();
});