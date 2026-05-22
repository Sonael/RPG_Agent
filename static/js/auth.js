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
      // O backend sinaliza email não confirmado com reason:'unconfirmed'
      // (campo estruturado — não dependemos mais de keyword na mensagem).
      const msg = data.error || '';
      if (data.reason === 'unconfirmed') {
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

    // Salvando os dois tokens na memória do navegador
    setTokens(data.access_token, data.refresh_token);
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
  document.querySelector('.page-right').innerHTML = `
    <div style="display:flex; flex-direction:column; justify-content:center; align-items:center; height:100%; text-align:center; padding: 40px;">
      <div style="font-size:56px; margin-bottom:20px;">📬</div>
      <div style="font-family:'Playfair Display',serif; font-size:22px; color:var(--text-main); margin-bottom:15px;">
        Confirme o seu email
      </div>
      <p style="font-family:'Lora',serif; font-size:15px; color:var(--text-muted); line-height:1.7; margin-bottom:12px;">
        Enviamos um link de confirmação para:
      </p>
      <div style="font-family:'Caveat',cursive; font-size:22px; color:var(--ink-user); border-bottom:1px solid var(--page-edge); padding-bottom:10px; margin-bottom:20px; word-break:break-all;">
        ${email}
      </div>
      <p style="font-family:'Lora',serif; font-size:14px; color:var(--text-muted); line-height:1.6; margin-bottom:30px;">
        Clique no link do email para ativar a sua conta.<br>
        Depois retorne aqui para entrar.
      </p>
      <button class="btn-main" onclick="location.reload()" style="max-width:280px; width:100%;">
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
    const refresh = (res.ok && data.ok && data.refresh_token) ? data.refresh_token : params.refresh_token;
    
    // Salva os dois tokens recebidos
    setTokens(token, refresh);
  } catch (_) {
    // Backend sem rota /confirm → usa token do hash diretamente
    setTokens(params.access_token, params.refresh_token);
  }

  history.replaceState(null, '', window.location.pathname);
  showConfirmSuccess();
  setTimeout(() => { window.location.href = '/menu.html'; }, 2200);
  return true;
}

function showConfirmingScreen() {
  document.querySelector('.page-right').innerHTML = `
    <div id="confirm-msg" style="display:flex; flex-direction:column; justify-content:center; align-items:center; height:100%; text-align:center; padding:40px;">
      <div style="font-size:48px; margin-bottom:18px;">⏳</div>
      <div style="font-family:'Playfair Display',serif; font-size:20px; color:var(--text-main); margin-bottom:10px;">A confirmar email...</div>
      <div style="font-family:'Lora',serif; font-size:14px; color:var(--text-muted);">Aguarde um momento</div>
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

  // 2. Já tem sessão salva → vai direto ao menu (agora usando a nova função de leitura)
  const tokens = getTokens();
  if (tokens && tokens.access) { window.location.href = '/menu.html'; return; }

  // 3. Tela de login normal
  document.getElementById('auth-email')?.addEventListener('keydown',    e => { if (e.key === 'Enter') document.getElementById('auth-password').focus(); });
  document.getElementById('auth-password')?.addEventListener('keydown', e => { if (e.key === 'Enter') submitAuth(); });
});