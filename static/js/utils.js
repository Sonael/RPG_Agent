// ═══════════════════════════════════════
//  API base (same host)
// ═══════════════════════════════════════
const API = '';

// ═══════════════════════════════════════
//  Auth token helpers
// ═══════════════════════════════════════
function getToken()       { return localStorage.getItem('rpg_token'); }
function setToken(t)      { localStorage.setItem('rpg_token', t); }
function clearToken()     { localStorage.removeItem('rpg_token'); }
function requireAuth()    { if (!getToken()) { window.location.href = '/login.html'; return false; } return true; }

function authFetch(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const tok = getToken();
  if (tok) headers['Authorization'] = `Bearer ${tok}`;
  return fetch(url, { ...opts, headers });
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
  setTimeout(() => btnsEl.querySelector('button:last-child')?.focus(), 50);
}

function _closeDlg(val) {
  document.getElementById('dialog-overlay').classList.add('hidden');
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
