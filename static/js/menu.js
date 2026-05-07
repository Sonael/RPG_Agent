// ═══════════════════════════════════════
//  menu.js  —  usado em menu.html
// ═══════════════════════════════════════
let selectedCampaign = null;
let isNewCampaign    = false;
let storyMode        = 'custom';

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  if (!requireAuth()) return;
  loadCampaigns();
  loadOllamaModels();

  document.getElementById('new-campaign-name')?.addEventListener('input', function() {
    const val = this.value.trim();
    if (val) selectCampaign(val, true);
    else     { selectedCampaign = null; document.getElementById('start-btn').disabled = true; }
  });

  document.getElementById('import-overlay')?.addEventListener('click', function(e) {
    if (e.target === this) closeImportModal();
  });
});

// ── Logout ──
async function logout() {
  const ok = await showConfirm('Sair da conta', 'Você será desconectado.', 'warning', 'Sair');
  if (!ok) return;
  try { await authFetch(`${API}/api/session/end`, { method: 'POST' }); } catch (_) {}
  clearTokens();
  localStorage.removeItem('rpg_session');
  window.location.href = '/login.html';
}

// ═══════════════════════════════════════
//  Campanhas
// ═══════════════════════════════════════
async function loadCampaigns() {
  const list = document.getElementById('campaign-list');
  try {
    const res  = await authFetch(`${API}/api/campaigns`);
    if (res.status === 401) { clearTokens(); window.location.href = '/login.html'; return; }
    const data = await res.json();

    if (!data.length) {
      list.innerHTML = '<div style="padding:12px 14px;font-size:12px;color:var(--text-muted);font-style:italic;">Nenhuma campanha salva.</div>';
      return;
    }

    list.innerHTML = data.map(c => `
      <div class="campaign-item" onclick="selectCampaign('${c.name}', false)" id="ci-${CSS.escape(c.name)}">
        <div>
          <div class="campaign-item-name">${c.name}</div>
          <div class="campaign-item-meta">Cap.${c.chapter||1} · ${c.characters||0} personagens · ${c.events||0} eventos</div>
        </div>
        <button class="campaign-item-del" onclick="deleteCampaign(event,'${c.name}')" title="Deletar">✕</button>
      </div>
    `).join('');

  } catch (e) {
    list.innerHTML = '<div style="padding:12px;color:var(--red);font-size:12px;">Erro ao conectar com o servidor.</div>';
  }
}

function selectCampaign(name, isNew) {
  selectedCampaign = name;
  isNewCampaign    = isNew;
  document.querySelectorAll('.campaign-item').forEach(el => el.classList.remove('selected'));
  if (!isNew) {
    document.getElementById(`ci-${CSS.escape(name)}`)?.classList.add('selected');
    document.getElementById('new-campaign-form').classList.remove('visible');
  }
  document.getElementById('start-btn').disabled = false;
}

function toggleNewCampaign() {
  const form   = document.getElementById('new-campaign-form');
  const typeSection = document.getElementById('campaign-type-section');
  const visible = form.classList.toggle('visible');
  typeSection.style.display = visible ? 'block' : 'none';
  if (visible) {
    document.querySelectorAll('.campaign-item').forEach(el => el.classList.remove('selected'));
    selectedCampaign = null;
    document.getElementById('start-btn').disabled = true;
    document.getElementById('new-campaign-name').focus();
  }
}

async function deleteCampaign(e, name) {
  e.stopPropagation();
  const ok = await showConfirm(
    'Deletar Campanha',
    `<strong style="color:var(--text)">"${name}"</strong> será permanentemente apagada.`,
    'danger', 'Deletar'
  );
  if (!ok) return;
  await authFetch(`${API}/api/campaigns/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (selectedCampaign === name) { selectedCampaign = null; document.getElementById('start-btn').disabled = true; }
  loadCampaigns();
}

function setStoryMode(mode) {
  storyMode = mode;
  document.getElementById('mode-custom').classList.toggle('selected', mode === 'custom');
  document.getElementById('mode-random').classList.toggle('selected', mode === 'random');
  document.getElementById('story-custom-input').classList.toggle('hidden', mode !== 'custom');
  document.getElementById('story-random-input').classList.toggle('hidden', mode !== 'random');
}

// ═══════════════════════════════════════
//  Iniciar sessão → redireciona para game.html
// ═══════════════════════════════════════
async function startSession() {
  if (!selectedCampaign) return;
  const btn = document.getElementById('start-btn');
  btn.disabled    = true;
  btn.textContent = 'Iniciando...';

  const payload = {
    campaign:      selectedCampaign,
    model:         document.getElementById('model-select').value,
    campaign_type: isNewCampaign ? document.getElementById('campaign-type-select').value : 'fantasia',
    is_new:        isNewCampaign,
    story_mode:    isNewCampaign ? storyMode : 'existing',
    story_input:   document.getElementById('story-input').value.trim(),
    genre:         document.getElementById('genre-input').value.trim(),
  };

  try {
    const res  = await authFetch(`${API}/api/session/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Erro ao iniciar sessão');

    // Salva contexto da sessão para game.html usar
    localStorage.setItem('rpg_session', JSON.stringify({
      campaign:      data.campaign,
      model:         data.model_label,
      campaign_type: payload.campaign_type,
      has_history:   data.has_history,
      opening:       data.opening,
      campaign_config: data.campaign_config || null,
      model_limits:  data.model_limits,
      conversation_history: data.conversation_history || [],
    }));

    window.location.href = '/game.html';

  } catch (e) {
    btn.disabled    = false;
    btn.textContent = 'Iniciar Sessão';
    await showAlert('Erro ao iniciar sessão', e.message, 'danger');
  }
}

// ═══════════════════════════════════════
//  Ollama
// ═══════════════════════════════════════
async function loadOllamaModels() {
  const group  = document.getElementById('ollama-optgroup');
  const status = document.getElementById('ollama-status');
  try {
    const res  = await fetch(`${API}/api/ollama/models`);
    const data = await res.json();
    if (!data.ok || !data.models.length) {
      group.innerHTML    = '<option value="" disabled>Nenhum modelo encontrado</option>';
      status.style.color = 'var(--text-muted)';
      status.textContent = data.ok ? 'Ollama conectado, sem modelos. Use: ollama pull <modelo>' : 'Ollama não encontrado (ollama serve).';
      return;
    }
    group.innerHTML    = data.models.map(m => `<option value="ollama:${m}">${m}</option>`).join('');
    status.style.color = 'var(--green)';
    status.textContent = `${data.models.length} modelo${data.models.length>1?'s':''} disponível${data.models.length>1?'is':''} no Ollama.`;
  } catch (_) {
    group.innerHTML    = '<option value="" disabled>Erro ao consultar Ollama</option>';
    status.style.color = 'var(--text-muted)';
    status.textContent = 'Não foi possível conectar ao Ollama.';
  }
}

function onModelChange() {
  const val    = document.getElementById('model-select').value;
  const status = document.getElementById('ollama-status');
  if (val.startsWith('ollama:')) {
    const name   = val.replace('ollama:','').split(':')[0];
    const good   = ['qwen2.5','llama3.2','mistral','qwen3','deepseek'].some(g => name.toLowerCase().includes(g));
    status.style.color = good ? 'var(--green)' : 'var(--gold-dim)';
    status.textContent = good ? `"${name}" tem bom suporte a tool calling.` : `Aviso: "${name}" pode ter suporte limitado.`;
  } else if (val.startsWith('deepseek:')) {
    status.style.color = 'var(--blue)';
    status.textContent = 'Requer DEEPSEEK_API_KEY no servidor.';
  }
}

// ═══════════════════════════════════════
//  Modal de importação
// ═══════════════════════════════════════
let currentImportTheme = 'dnd';

function getImportPrompt(theme) {
  const isDnd = theme === 'dnd';
  const themeFocus = {
    dnd:      "focando nas mecânicas de combate, itens, magias e progressão de aventura",
    fantasia: "focando na magia do mundo, facções e feitos heroicos",
    romance:  "focando intensamente nos sentimentos, intimidade, segredos e no estado atual dos relacionamentos",
    horror:   "focando na tensão, nos traumas adquiridos, na sanidade e nos medos",
    misterio: "focando nas pistas coletadas, suspeitos, álibis e na linha investigativa",
    scifi:    "focando na tecnologia, implantes cibernéticos, corporações e recursos",
    faroeste: "focando na reputação, alianças, recompensas e na moralidade crua",
  };

  let prompt = `Analise meticulosamente toda a nossa conversa até agora. Você deve agir como um Arquivista de Mundos, extraindo não apenas fatos, mas a atmosfera, as nuances psicológicas e as ramificações de cada escolha. Extraia o máximo de detalhes possível para garantir a continuidade perfeita da narrativa, ${themeFocus[theme]}.\n\nGere um JSON com EXATAMENTE esta estrutura:\n\n{\n`;
  prompt += `  "campaign_type": "${theme}",\n`;
  prompt += `  "dnd_mode": ${isDnd},\n`;
  prompt += `  "chapter": <número do capítulo atual>,\n`;
  prompt += `  "current_location": "<nome exato do local onde a história está agora>",\n`;
  prompt += `  "current_scene": "<detalhamento vívido da cena atual>",\n`;
  prompt += `  "story_summary": "<resumo denso de 10 a 15 linhas>",\n`;

  if (isDnd) {
    prompt += `  "combat_state": { "is_active": false, "initiative_order": [], "current_turn_index": 0, "round": 1 },\n`;
  }

  prompt += `  "characters": {\n    "<Nome Exato Maiusculo e Minusculo>": {\n      "name": "<Nome Exato Maiusculo e Minusculo>",\n     "description": "<descrição física minuciosa>",\n      "traits": "<análise psicológica profunda>",\n      "status": "<vivo|morto|desaparecido|preso|inconsciente|outro>",\n      "notes": "<objetivos pessoais ocultos>"`;

  if (isDnd) {
    prompt += `,\n      "sheet": {\n        "classe": "<classe>", "raca": "<raça>", "nivel": 1, "xp": 0, "xp_proximo": 300,\n        "forca": 10, "destreza": 10, "constituicao": 10, "inteligencia": 10, "sabedoria": 10, "carisma": 10,\n        "vida_atual": 10, "vida_max": 10, "mana_atual": 0, "mana_max": 0, "ca": 10, "proficiencia": 2, "hit_die": 8,\n        "ouro": 0, "prata": 0, "cobre": 0,\n        "equipamentos": {"armadura": null, "escudo": null, "arma_principal": null, "amuleto": null},\n        "condicoes": [],\n        "death_saves_sucessos": 0, "death_saves_falhas": 0\n      },\n      "inventario": [\n        {"nome": "<nome_item>", "qtd": 1, "descricao": "<efeito>"}\n      ],\n      "habilidades": [\n        {"nome": "<nome_hab>", "descricao": "<efeito>", "custo_mana": 0, "dado": "1d6"}\n      ]`;
  }

  prompt += `\n    }\n  },\n  "locations": {\n    "<nome_em_lowercase>": {\n      "name": "<Nome do Local>",\n      "description": "<descrição sensorial completa>",\n      "details": "<pontos geográficos específicos>",\n      "notes": "<eventos passados ocorridos aqui>"\n    }\n  },\n  "events": [\n    {\n      "index": 1,\n      "summary": "<narração detalhada>",\n      "characters_involved": "<nomes separados por vírgula>",\n      "location": "<onde ocorreu>",\n      "consequence": "<consequência imediata e ramificações>"\n    }\n  ],\n  "party": [\n    {\n      "name": "<nome>",\n      "role": "<função ou classe>",\n      "notes": "<fatos marcantes>"\n    }\n  ],\n  "quest_flags": {\n    "<nome_da_flag>": "<valor detalhado>"\n  },\n  "diary": [\n    {\n      "chapter": <numero>,\n      "title": "<título evocativo>",\n      "content": "<narração em terceira pessoa com estilo literário>"\n    }\n  ]\n}\n\nResponda APENAS com o JSON, sem explicações, sem blocos de código markdown.`;

  return prompt;
}

function setImportTheme(theme) {
  currentImportTheme = theme;
  document.querySelectorAll('.import-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.theme === theme);
  });
  document.getElementById('import-prompt-text').textContent = getImportPrompt(theme);
  // Reseta feedback de cópia
  const copyBtn = document.getElementById('copy-prompt-btn');
  if (copyBtn) { copyBtn.textContent = 'Copiar'; copyBtn.style.color = ''; copyBtn.style.borderColor = ''; }
}

function openImportModal() {
  document.getElementById('import-json-input').value        = '';
  document.getElementById('import-campaign-name').value     = '';
  document.getElementById('import-json-status').textContent = '';
  document.getElementById('import-confirm-btn').disabled    = true;
  document.getElementById('import-confirm-btn').style.opacity = '0.4';
  document.getElementById('import-overlay').classList.remove('hidden');
  // Preenche prompt com o tema padrão (D&D) e reseta abas
  setImportTheme('dnd');
}

function closeImportModal() {
  document.getElementById('import-overlay').classList.add('hidden');
}

function copyImportPrompt() {
  const text = getImportPrompt(currentImportTheme);
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('copy-prompt-btn');
    const old = btn.textContent;
    btn.textContent       = 'Copiado!';
    btn.style.color       = 'var(--green)';
    btn.style.borderColor = 'var(--green)';
    setTimeout(() => { btn.textContent = old; btn.style.color = ''; btn.style.borderColor = ''; }, 2000);
  });
}

function onImportJsonChange() {
  const raw    = document.getElementById('import-json-input').value.trim();
  const status = document.getElementById('import-json-status');
  const btn    = document.getElementById('import-confirm-btn');
  if (!raw) { status.textContent = ''; btn.disabled = true; btn.style.opacity = '0.4'; return; }

  const cleaned = raw.replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/i,'').trim();
  try {
    const parsed   = JSON.parse(cleaned);
    const required = ['characters','locations','events','story_summary'];
    const missing  = required.filter(k => !(k in parsed));
    if (missing.length) {
      status.style.color = 'var(--gold-dim)';
      status.textContent = `⚠ JSON válido mas faltam campos: ${missing.join(', ')}`;
    } else {
      const chars = Object.keys(parsed.characters||{}).length;
      const locs  = Object.keys(parsed.locations||{}).length;
      const evts  = (parsed.events||[]).length;
      status.style.color = 'var(--green)';
      status.textContent = `✓ JSON válido — ${chars} personagens, ${locs} locais, ${evts} eventos`;
    }
    btn.disabled = false; btn.style.opacity = '1';
    document.getElementById('import-json-input').dataset.cleaned = cleaned;
  } catch (e) {
    status.style.color = 'var(--red)';
    status.textContent = `✕ JSON inválido: ${e.message}`;
    btn.disabled = true; btn.style.opacity = '0.4';
  }
}

async function confirmImport() {
  const cleaned = document.getElementById('import-json-input').dataset.cleaned;
  const name    = document.getElementById('import-campaign-name').value.trim();
  if (!cleaned) { await showAlert('Erro','Cole o JSON antes de importar.','danger'); return; }
  if (!name)    { await showAlert('Erro','Digite um nome para a campanha.','danger'); return; }

  const btn = document.getElementById('import-confirm-btn');
  btn.textContent = 'Importando...'; btn.disabled = true;

  try {
    const parsed = JSON.parse(cleaned);
    const res    = await authFetch(`${API}/api/campaigns/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, campaign: parsed }),
    });
    const data = await res.json();
    if (!res.ok) { await showAlert('Erro ao importar', data.error||'Erro desconhecido.','danger'); btn.textContent='Importar'; btn.disabled=false; return; }
    closeImportModal();
    loadCampaigns();
    showToast(`Campanha "${data.name}" importada.`);
  } catch (e) {
    await showAlert('Erro ao importar', e.message, 'danger');
    btn.textContent = 'Importar Campanha'; btn.disabled = false;
  }
}
