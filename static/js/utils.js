// ═══════════════════════════════════════
//  API base (same host)
// ═══════════════════════════════════════
const API = '';

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