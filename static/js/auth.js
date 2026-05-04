// ═══════════════════════════════════════
//  auth.js  —  usado em login.html
// ═══════════════════════════════════════
let _authMode = 'login';

function switchTab(mode) {
  _authMode = mode;
  const isLogin = mode === 'login';
  document.getElementById('tab-login').classList.toggle('active', isLogin);
  document.getElementById('tab-register').classList.toggle('active', !isLogin);
  document.getElementById('auth-submit-btn').textContent = isLogin ? 'Entrar' : 'Criar conta';
  document.getElementById('auth-error').textContent = '';
}

async function submitAuth() {
  const email    = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  const errorEl  = document.getElementById('auth-error');
  const btn      = document.getElementById('auth-submit-btn');

  if (!email || !password) { errorEl.textContent = 'Preencha email e senha.'; return; }

  btn.disabled    = true;
  btn.textContent = 'Aguarde...';
  errorEl.textContent = '';

  try {
    const endpoint = _authMode === 'login' ? '/api/auth/login' : '/api/auth/register';
    const res  = await fetch(`${API}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      // Supabase retorna erro específico para email não confirmado
      const msg = data.error || '';
      if (msg.toLowerCase().includes('confirm') || msg.toLowerCase().includes('verificad') || msg.toLowerCase().includes('email')) {
        errorEl.innerHTML = `${msg}<br><span style="color:var(--text-dim);font-size:11px;">Verifique sua caixa de entrada e clique no link de confirmação.</span>`;
      } else {
        errorEl.textContent = msg || 'Erro desconhecido.';
      }
      btn.disabled    = false;
      btn.textContent = _authMode === 'login' ? 'Entrar' : 'Criar conta';
      return;
    }

    // Registro bem-sucedido mas aguarda confirmação
    if (data.needs_confirmation) {
      showPendingConfirmation(email);
      return;
    }

    setToken(data.access_token);
    window.location.href = '/menu.html';

  } catch (e) {
    errorEl.textContent  = 'Erro de conexão. Verifique se o servidor está rodando.';
    btn.disabled    = false;
    btn.textContent = _authMode === 'login' ? 'Entrar' : 'Criar conta';
  }
}

// ═══════════════════════════════════════
//  Tela de confirmação pendente
// ═══════════════════════════════════════
function showPendingConfirmation(email) {
  document.querySelector('.login-card').innerHTML = `
    <div class="login-accent"></div>
    <div class="login-header">
      <div class="login-title">RPG AGENT</div>
    </div>
    <div style="padding:0 32px 36px;text-align:center;">
      <div style="font-size:48px;margin-bottom:16px;">📬</div>
      <div style="font-family:'Cinzel',serif;font-size:16px;color:var(--gold);letter-spacing:0.06em;margin-bottom:12px;">
        Confirme seu email
      </div>
      <p style="font-size:14px;color:var(--text-dim);line-height:1.7;margin-bottom:8px;">
        Enviamos um link de confirmação para:
      </p>
      <div style="font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--gold-bright);background:var(--bg3);border:1px solid var(--border2);border-radius:3px;padding:8px 14px;margin-bottom:20px;word-break:break-all;">
        ${email}
      </div>
      <p style="font-size:13px;color:var(--text-muted);line-height:1.6;margin-bottom:24px;">
        Clique no link do email para ativar sua conta.<br>
        Depois retorne aqui para entrar.
      </p>
      <button class="btn-ghost" onclick="location.reload()" style="width:100%;">
        ← Voltar ao login
      </button>
    </div>
  `;
}

// ═══════════════════════════════════════
//  Confirmação de email via hash do Supabase
//  Supabase redireciona para: /#access_token=...&type=signup
// ═══════════════════════════════════════
function parseHash() {
  return Object.fromEntries(new URLSearchParams(window.location.hash.replace(/^#/, '')));
}

async function handleEmailConfirmation() {
  const params = parseHash();
  if (!params.access_token || params.type !== 'signup') return false;

  showConfirmingScreen();

  try {
    // Tenta registrar no backend
    const res  = await fetch(`${API}/api/auth/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        access_token:  params.access_token,
        refresh_token: params.refresh_token || '',
        token_type:    params.token_type    || 'bearer',
      }),
    });
    const data = await res.json();
    const token = (res.ok && data.ok && data.access_token) ? data.access_token : params.access_token;
    setToken(token);
  } catch (_) {
    // Backend sem rota /confirm → usa token do hash diretamente
    setToken(params.access_token);
  }

  history.replaceState(null, '', window.location.pathname);
  showConfirmSuccess();
  setTimeout(() => { window.location.href = '/menu.html'; }, 2200);
  return true;
}

function showConfirmingScreen() {
  document.querySelector('.login-card').innerHTML = `
    <div class="login-accent"></div>
    <div class="login-header" style="padding-bottom:36px;">
      <div class="login-title">RPG AGENT</div>
      <div style="margin-top:32px;text-align:center;" id="confirm-msg">
        <div style="font-size:40px;margin-bottom:14px;">⏳</div>
        <div style="font-family:'Cinzel',serif;font-size:14px;color:var(--gold);letter-spacing:0.08em;">Confirmando email...</div>
        <div style="font-size:12px;color:var(--text-muted);margin-top:8px;font-family:'JetBrains Mono',monospace;">Aguarde um momento</div>
      </div>
    </div>
  `;
}

function showConfirmSuccess() {
  const msg = document.getElementById('confirm-msg');
  if (!msg) return;
  msg.innerHTML = `
    <div style="font-size:40px;margin-bottom:14px;">✅</div>
    <div style="font-family:'Cinzel',serif;font-size:15px;color:var(--green);letter-spacing:0.06em;">Email confirmado!</div>
    <div style="font-size:12px;color:var(--text-muted);margin-top:10px;font-family:'JetBrains Mono',monospace;">Redirecionando para o menu...</div>
  `;
}

// ═══════════════════════════════════════
//  Init
// ═══════════════════════════════════════
document.addEventListener('DOMContentLoaded', async () => {
  // 1. Chegou via link de confirmação do Supabase?
  const confirmed = await handleEmailConfirmation();
  if (confirmed) return;

  // 2. Já tem sessão salva → vai direto ao menu
  if (getToken()) { window.location.href = '/menu.html'; return; }

  // 3. Tela de login normal
  document.getElementById('auth-email')?.addEventListener('keydown',    e => { if (e.key === 'Enter') document.getElementById('auth-password').focus(); });
  document.getElementById('auth-password')?.addEventListener('keydown', e => { if (e.key === 'Enter') submitAuth(); });
});
