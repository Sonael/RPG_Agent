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
  {
    id: 'pergaminho',
    label: 'Pergaminho',
    desc: 'Claro e acolhedor',
    swatchTop: '#2b303a',
    swatchBot: '#f5f3eb',
  },
  {
    id: 'noite-tinta',
    label: 'Noite de Tinta',
    desc: 'Escuro e misterioso',
    swatchTop: '#16213e',
    swatchBot: '#1e1e30',
  },
  {
    id: 'ardosia',
    label: 'Ardósia',
    desc: 'Cinza frio e austero',
    swatchTop: '#2d3142',
    swatchBot: '#e8eaf2',
  },
  {
    id: 'floresta',
    label: 'Floresta Antiga',
    desc: 'Verde musgo e terra',
    swatchTop: '#1e3020',
    swatchBot: '#eaf2e8',
  },
  {
    id: 'oceano',
    label: 'Profundezas',
    desc: 'Azul do mar profundo',
    swatchTop: '#0d2845',
    swatchBot: '#e8f2fc',
  },
  {
    id: 'sangue-dragao',
    label: 'Sangue de Dragão',
    desc: 'Carmim e trevas',
    swatchTop: '#200808',
    swatchBot: '#1e0e0e',
  },
  {
    id: 'poeira-ouro',
    label: 'Poeira de Ouro',
    desc: 'Sépia e nostalgia',
    swatchTop: '#2e2010',
    swatchBot: '#f0e8d0',
  },
];

/** Aplica um tema e salva no localStorage */
function applyTheme(id) {
  document.documentElement.setAttribute('data-theme', id);
  localStorage.setItem('rpg_theme', id);
  document.querySelectorAll('.theme-option').forEach(el => {
    el.classList.toggle('active', el.dataset.theme === id);
  });
}

/** Carrega o tema salvo e injeta o picker na página */
function loadTheme() {
  const saved = localStorage.getItem('rpg_theme') || 'pergaminho';
  document.documentElement.setAttribute('data-theme', saved);
  _injectThemePicker(saved);
}

function _injectThemePicker(activeId) {
  if (document.getElementById('theme-picker-wrapper')) return; // já injetado

  const wrapper = document.createElement('div');
  wrapper.id = 'theme-picker-wrapper';

  const optionsHtml = THEMES.map(t => `
    <button class="theme-option${t.id === activeId ? ' active' : ''}"
            data-theme="${t.id}"
            onclick="applyTheme('${t.id}')"
            title="${t.desc}">
      <span class="theme-swatch"
            style="background:linear-gradient(135deg,${t.swatchTop} 45%,${t.swatchBot} 45%)"></span>
      <span class="theme-label">${t.label}</span>
      <span class="theme-check">✓</span>
    </button>
  `).join('');

  wrapper.innerHTML = `
    <button id="theme-toggle-btn" title="Selecionar tema" aria-label="Selecionar tema">
      <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24"
           fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10
                 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
        <line x1="2" y1="12" x2="22" y2="12"/>
      </svg>
      Tema
    </button>
    <div id="theme-panel" class="hidden">
      <div class="theme-panel-header">Aparência</div>
      ${optionsHtml}
    </div>
  `;

  document.body.appendChild(wrapper);

  // Toggle do painel
  document.getElementById('theme-toggle-btn').addEventListener('click', e => {
    e.stopPropagation();
    document.getElementById('theme-panel').classList.toggle('hidden');
  });

  // Fechar ao clicar fora
  document.addEventListener('click', e => {
    const panel = document.getElementById('theme-panel');
    if (panel && !wrapper.contains(e.target)) {
      panel.classList.add('hidden');
    }
  });

  // Fechar com Escape
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.getElementById('theme-panel')?.classList.add('hidden');
    }
  });
}

document.addEventListener('DOMContentLoaded', loadTheme);