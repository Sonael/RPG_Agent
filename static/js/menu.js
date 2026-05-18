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
        <div style="display:flex;gap:5px;flex-shrink:0;">
          <button class="campaign-item-edit" onclick="openEditCampaign(event,'${c.name}')" title="Editar campanha">✎</button>
          <button class="campaign-item-del" onclick="deleteCampaign(event,'${c.name}')" title="Deletar">✕</button>
        </div>
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
  }
  document.getElementById('start-btn').disabled = false;
}

function toggleNewCampaign() {
  openWizard();
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
    campaign_type: 'fantasia',
    is_new:        false,
    story_mode:    'existing',
    story_input:   '',
    genre:         '',
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

    // Anima a virada de página antes de navegar
    const cover = document.querySelector('.tome-cover');
    if (cover) {
      cover.classList.remove('animate-open');
      void cover.offsetWidth;
      cover.classList.add('animate-close');
      setTimeout(() => { window.location.href = '/game.html'; }, 900);
    } else {
      window.location.href = '/game.html';
    }

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
  prompt += `  "protagonist": "<nome exato do personagem principal do jogador>",
  "chapter": <número do capítulo atual>,\n`;
  prompt += `  "current_location": "<nome exato do local onde a história está agora>",\n`;
  prompt += `  "current_scene": "<detalhamento vívido da cena atual>",\n`;
  prompt += `  "story_summary": "<resumo denso de 10 a 15 linhas>",\n`;

  if (isDnd) {
    prompt += `  "combat_state": { "is_active": false, "initiative_order": [], "current_turn_index": 0, "round": 1, "turn_resolved": false },\n`;
  }

  prompt += `  "characters": {\n    "<Nome Exato Maiusculo e Minusculo>": {\n      "name": "<Nome Exato Maiusculo e Minusculo>",\n     "description": "<descrição física minuciosa>",\n      "traits": "<análise psicológica profunda>",\n      "status": "<vivo|morto|desaparecido|preso|inconsciente|outro>",\n      "notes": "<objetivos pessoais ocultos>"`;

  if (isDnd) {
    prompt += `,\n      "sheet": {\n        "classe": "<classe>", "raca": "<raça>", "nivel": 1, "xp": 0, "xp_proximo": 300,\n        "forca": 10, "destreza": 10, "constituicao": 10, "inteligencia": 10, "sabedoria": 10, "carisma": 10,\n        "vida_atual": 10, "vida_max": 10, "mana_atual": 0, "mana_max": 0, "ca": 10, "proficiencia": 2, "hit_die": 8,\n        "ouro": 0, "prata": 0, "cobre": 0,\n        "equipamentos": {"armadura": null, "escudo": null, "arma_principal": null, "amuleto": null},\n        "condicoes": [],\n        "death_saves_sucessos": 0, "death_saves_falhas": 0\n      },\n      "inventario": [\n        {"nome": "<nome_item>", "qtd": 1, "descricao": "<efeito>", "custom": false}\n      ],\n      "habilidades": [\n        {"nome": "<nome_hab>", "descricao": "<efeito>", "custo_mana": 0, "dado": "1d6"}\n      ]`;
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

// ═══════════════════════════════════════════════════════════
//  WIZARD DE CRIAÇÃO DE CAMPANHA
// ═══════════════════════════════════════════════════════════

// ── Tabelas D&D ──────────────────────────────────────────
// ── Equipamentos iniciais por classe (D&D 5e) ────────────────────────────
const CLASS_EQUIPMENT_WZ = {
  bárbaro:     { arm:'armadura de peles',   arma:'machado de mão',     esc:null,              inv:[
    {nome:'Machado de Mão',    qtd:1,  descricao:'Dano: 1d6 cortante. Arma leve, versátil.'},
    {nome:'Adaga',             qtd:2,  descricao:'Dano: 1d4 perfurante. Leve, jogável (6m).'},
    {nome:'Mochila de Aventureiro', qtd:1, descricao:'Suprimentos básicos para exploração.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida. Ação para usar.'},
  ]},
  guerreiro:   { arm:'cota de malha',        arma:'espada longa',       esc:'escudo',          inv:[
    {nome:'Espada Longa',      qtd:1,  descricao:'Dano: 1d8 (1d10 com 2 mãos) cortante. Versátil.'},
    {nome:'Escudo',            qtd:1,  descricao:'+2 CA quando equipado.'},
    {nome:'Besta de Mão',      qtd:1,  descricao:'Dano: 1d6 perfurante. Alcance 9m.'},
    {nome:'Virotes',           qtd:20, descricao:'Munição para besta leve.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  paladino:    { arm:'cota de malha',        arma:'espada longa',       esc:'escudo sagrado',  inv:[
    {nome:'Espada Longa',      qtd:1,  descricao:'Dano: 1d8 cortante. Versátil.'},
    {nome:'Escudo Sagrado',    qtd:1,  descricao:'+2 CA. Gravado com símbolo divino.'},
    {nome:'Símbolo Sagrado',   qtd:1,  descricao:'Foco divino para conjuração.'},
    {nome:'Kit de Cura',       qtd:1,  descricao:'10 usos. Estabiliza criaturas em 0 HP.'},
    {nome:'Poção de Cura',     qtd:2,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  mago:        { arm:'robes de mago',        arma:'cajado arcano',      esc:null,              inv:[
    {nome:'Cajado Arcano',     qtd:1,  descricao:'Foco arcano e arma. Dano: 1d6 concussão.'},
    {nome:'Grimório',          qtd:1,  descricao:'Livro de magias com feitiços aprendidos.'},
    {nome:'Bolsa de Componentes', qtd:1, descricao:'Componentes materiais para magias.'},
    {nome:'Adaga',             qtd:1,  descricao:'Dano: 1d4 perfurante. Arma de emergência.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  ladino:      { arm:'armadura de couro',    arma:'adaga dupla',        esc:null,              inv:[
    {nome:'Adaga',             qtd:2,  descricao:'Dano: 1d4 perfurante. Leve, jogável (6m).'},
    {nome:'Arco Curto',        qtd:1,  descricao:'Dano: 1d6 perfurante. Alcance 24m.'},
    {nome:'Flechas',           qtd:20, descricao:'Munição para arco curto.'},
    {nome:'Ferramentas de Ladrão', qtd:1, descricao:'Para abrir fechaduras e armadilhas.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  clérigo:     { arm:'cota de malha',        arma:'maça',               esc:'escudo',          inv:[
    {nome:'Maça',              qtd:1,  descricao:'Dano: 1d6 concussão. Arma contundente.'},
    {nome:'Escudo',            qtd:1,  descricao:'+2 CA quando equipado.'},
    {nome:'Símbolo Sagrado',   qtd:1,  descricao:'Foco divino para conjuração.'},
    {nome:'Kit de Cura',       qtd:2,  descricao:'10 usos cada. Estabiliza criaturas em 0 HP.'},
    {nome:'Poção de Cura',     qtd:2,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  bardo:       { arm:'armadura de couro',    arma:'espada curta',       esc:null,              inv:[
    {nome:'Espada Curta',      qtd:1,  descricao:'Dano: 1d6 perfurante. Arma leve.'},
    {nome:'Adaga',             qtd:1,  descricao:'Dano: 1d4 perfurante. Leve.'},
    {nome:'Instrumento Musical', qtd:1, descricao:'Foco bárdico. Ex: alaúde, flauta, tambor.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  druida:      { arm:'armadura de couro',    arma:'bastão druídico',    esc:'escudo de madeira', inv:[
    {nome:'Bastão Druídico',   qtd:1,  descricao:'Foco druídico e arma. Dano: 1d6 concussão.'},
    {nome:'Escudo de Madeira', qtd:1,  descricao:'+2 CA. Símbolos naturais entalhados.'},
    {nome:'Bolsa de Componentes', qtd:1, descricao:'Ervas, pedras e componentes naturais.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  monge:       { arm:null,                   arma:'bastão',             esc:null,              inv:[
    {nome:'Bastão',            qtd:1,  descricao:'Dano: 1d6 (1d8 com 2 mãos) concussão. Versátil.'},
    {nome:'Dardos',            qtd:10, descricao:'Dano: 1d4 perfurante. Arremesso (6/18m).'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  bruxo:       { arm:'armadura de couro',    arma:'foco arcano',        esc:null,              inv:[
    {nome:'Foco Arcano',       qtd:1,  descricao:'Orbe, varinha ou bastão para conjuração.'},
    {nome:'Adaga',             qtd:1,  descricao:'Dano: 1d4 perfurante. Arma de emergência.'},
    {nome:'Besta Leve',        qtd:1,  descricao:'Dano: 1d8 perfurante. Alcance 24m.'},
    {nome:'Virotes',           qtd:20, descricao:'Munição para besta leve.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  feiticeiro:  { arm:'armadura de couro',    arma:'adaga',              esc:null,              inv:[
    {nome:'Adaga',             qtd:2,  descricao:'Dano: 1d4 perfurante. Arma leve.'},
    {nome:'Bolsa de Componentes', qtd:1, descricao:'Componentes para magia inata.'},
    {nome:'Besta Leve',        qtd:1,  descricao:'Dano: 1d8 perfurante. Alcance 24m.'},
    {nome:'Virotes',           qtd:20, descricao:'Munição para besta leve.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  patrulheiro: { arm:'armadura de escamas',  arma:'espada curta dupla', esc:null,              inv:[
    {nome:'Espada Curta',      qtd:2,  descricao:'Dano: 1d6 perfurante. Arma leve.'},
    {nome:'Arco Longo',        qtd:1,  descricao:'Dano: 1d8 perfurante. Alcance 45m.'},
    {nome:'Flechas',           qtd:20, descricao:'Munição para arco longo.'},
    {nome:'Kit de Explorador', qtd:1,  descricao:'Ferramentas de rastreamento e sobrevivência.'},
    {nome:'Poção de Cura',     qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
  ]},
  npc: { arm:null, arma:'arma simples', esc:null, inv:[] },
};

// ── Habilidades iniciais D&D 5e — nível 1 por classe ─────────────────────
const CLASS_ABILITIES_WZ = {
  bárbaro: [
    {nome:'Fúria', descricao:'Ação bônus: vantagem em FOR, resistência a dano físico e +2 dano. 2 usos por descanso longo.', custo_mana:0, dado:''},
    {nome:'Defesa Sem Armadura', descricao:'Passivo: sem armadura, CA = 10 + mod.DEX + mod.CON.', custo_mana:0, dado:''},
  ],
  guerreiro: [
    {nome:'Segunda Fôlego', descricao:'Ação bônus: recupera 1d10 + nível de PV. 1 uso por descanso curto.', custo_mana:0, dado:'1d10'},
    {nome:'Estilo de Combate', descricao:'Passivo: bônus baseado no estilo escolhido (Duelo, Arqueiro, Defesa, etc.).', custo_mana:0, dado:''},
  ],
  paladino: [
    {nome:'Sentido Divino', descricao:'Ação: detecta celestiais, demônios e mortos-vivos em 18m. 1+CAR usos por descanso longo.', custo_mana:0, dado:''},
    {nome:'Imposição de Mãos', descricao:'Ação: cura de um pool de PV igual a nível×5. Recupera no descanso longo.', custo_mana:0, dado:''},
    {nome:'Bênção', descricao:'Magia: até 3 criaturas em 9m adicionam 1d4 nos ataques e resistências. Concentração, 1 min.', custo_mana:4, dado:'1d4'},
    {nome:'Proteção Divina', descricao:'Reação: impõe desvantagem num ataque contra aliado adjacente (requer escudo).', custo_mana:4, dado:''},
  ],
  mago: [
    {nome:'Recuperação Arcana', descricao:'Descanso curto: recupera espaços de magia com nível ≤ metade do nível do mago. 1 uso por descanso longo.', custo_mana:0, dado:''},
    {nome:'Prestidigitação', descricao:'Cantrip: truques mágicos menores — acende chamas, cria sons, muda cores. Alcance 3m.', custo_mana:0, dado:''},
    {nome:'Raio de Gelo', descricao:'Cantrip: disparo congelante (alcance 18m). Acerto: 1d8 frio e velocidade do alvo −3m.', custo_mana:0, dado:'1d8'},
    {nome:'Míssil Mágico', descricao:'Magia nível 1: 3 dardos de força automáticos, 1d4+1 cada.', custo_mana:4, dado:'3d4'},
    {nome:'Sono', descricao:'Magia nível 1: adormece criaturas num total de 5d8 PV (menores primeiro).', custo_mana:4, dado:'5d8'},
    {nome:'Mãos Ardentes', descricao:'Magia nível 1: cone de 4,5m, 3d6 de fogo. Resistência DEX CD12 para metade.', custo_mana:4, dado:'3d6'},
  ],
  ladino: [
    {nome:'Ataque Furtivo', descricao:'Causa 1d6 extra com vantagem ou aliado adjacente ao alvo. 1× por turno.', custo_mana:0, dado:'1d6'},
    {nome:'Ação Ardilosa', descricao:'Ação bônus: Esconder ou Disparar (recuar sem ataque de oportunidade).', custo_mana:0, dado:''},
    {nome:'Linguagem dos Ladrões', descricao:'Passivo: compreende o cant dos ladrões e pode deixar mensagens ocultas.', custo_mana:0, dado:''},
    {nome:'Especialização', descricao:'Passivo: proficiência dobrada em 2 perícias escolhidas.', custo_mana:0, dado:''},
  ],
  clérigo: [
    {nome:'Luz', descricao:'Cantrip: objeto irradia luz brilhante 6m e fraca mais 6m por 1 hora.', custo_mana:0, dado:''},
    {nome:'Punho Sagrado', descricao:'Cantrip: energia divina (alcance 18m). Acerto: 1d8 radiante vs mortos-vivos.', custo_mana:0, dado:'1d8'},
    {nome:'Cura Ferimentos', descricao:'Magia nível 1: toque cura 1d8 + mod.SAB de PV.', custo_mana:4, dado:'1d8'},
    {nome:'Bênção', descricao:'Magia nível 1: até 3 criaturas somam 1d4 em ataques e resistências. Concentração.', custo_mana:4, dado:'1d4'},
    {nome:'Escudo da Fé', descricao:'Magia nível 1: uma criatura ganha +2 CA por 10 minutos. Concentração.', custo_mana:4, dado:''},
  ],
  bardo: [
    {nome:'Inspiração Bárdica', descricao:'Ação bônus: aliado em 18m ganha 1d6 para adicionar a um teste. Mod.CAR usos/descanso longo.', custo_mana:0, dado:'1d6'},
    {nome:'Insulto Afiado', descricao:'Cantrip: resistência CAR ou 1d4 psíquico e desvantagem no próximo ataque.', custo_mana:0, dado:'1d4'},
    {nome:'Cura por Palavra', descricao:'Magia nível 1: cura 1d4 + mod.CAR de PV em criatura a 18m (sem toque).', custo_mana:4, dado:'1d4'},
    {nome:'Sono', descricao:'Magia nível 1: adormece até 5d8 PV de criaturas (menores primeiro).', custo_mana:4, dado:'5d8'},
  ],
  druida: [
    {nome:'Bola de Fogo Natural', descricao:'Cantrip: projétil de chamas (alcance 36m). Acerto: 1d8 fogo.', custo_mana:0, dado:'1d8'},
    {nome:'Guia', descricao:'Cantrip: toque — criatura ganha +1d4 no próximo teste de habilidade.', custo_mana:0, dado:'1d4'},
    {nome:'Cura Ferimentos', descricao:'Magia nível 1: toque cura 1d8 + mod.SAB de PV.', custo_mana:4, dado:'1d8'},
    {nome:'Emaranhar', descricao:'Magia nível 1: plantas contêm criaturas em 6m. Resistência FOR CD13 ou contido. Concentração.', custo_mana:4, dado:''},
    {nome:'Névoa', descricao:'Magia nível 1: nevoeiro espesso em raio 6m. Fortemente obscurecido. Concentração 1h.', custo_mana:4, dado:''},
  ],
  monge: [
    {nome:'Artes Marciais', descricao:'Passivo: ataques desarmados usam DEX ou FOR, dano 1d4. Bônus: ataque desarmado extra após atacar.', custo_mana:0, dado:'1d4'},
    {nome:'Defesa Sem Armadura', descricao:'Passivo: sem armadura e escudo, CA = 10 + mod.DEX + mod.SAB.', custo_mana:0, dado:''},
    {nome:'Golpe Rápido', descricao:'Ação bônus: ataque desarmado adicional após atacar com arma monástica. Dano: 1d4 + mod.DEX.', custo_mana:0, dado:'1d4'},
  ],
  bruxo: [
    {nome:'Arcanismo das Trevas', descricao:'Cantrip: projétil do patrono (alcance 36m). Acerto: 1d10 de força.', custo_mana:0, dado:'1d10'},
    {nome:'Toque do Gélido', descricao:'Cantrip: mão espectral (alcance 36m). Acerto: 1d8 necrótico; alvo não recupera PV no próximo turno.', custo_mana:0, dado:'1d8'},
    {nome:'Armadura de Ágath', descricao:'Magia nível 1: CA = 13 + mod.DEX sem armadura. Dura até ser dispelida.', custo_mana:4, dado:''},
    {nome:'Hex', descricao:'Magia nível 1: alvo recebe +1d6 necrótico por ataque e desvantagem num atributo. Concentração 1h.', custo_mana:4, dado:'1d6'},
    {nome:'Feitiçaria do Caos', descricao:'Magia nível 1: resistência CAR CD13 ou 1d10 força e desvantagem no próximo ataque.', custo_mana:4, dado:'1d10'},
  ],
  feiticeiro: [
    {nome:'Pulso de Choque', descricao:'Cantrip: descarga elétrica (alcance 18m). Acerto: 1d8 de raio.', custo_mana:0, dado:'1d8'},
    {nome:'Chamas Sagradas', descricao:'Cantrip: fogo divino — resistência DEX CD13 ou 1d8 radiante (ignora cobertura).', custo_mana:0, dado:'1d8'},
    {nome:'Míssil Mágico', descricao:'Magia nível 1: 3 dardos de força automáticos, 1d4+1 cada.', custo_mana:4, dado:'3d4'},
    {nome:'Queimar', descricao:'Magia nível 1: alvo a 45m — resistência DEX CD13 ou 2d6 de fogo.', custo_mana:4, dado:'2d6'},
    {nome:'Metamagia — Magia Sutil', descricao:'Gasta 1 Ponto de Feitiçaria: conjura sem componentes gestuais nem verbais.', custo_mana:0, dado:''},
  ],
  patrulheiro: [
    {nome:'Inimigo Favorecido', descricao:'Passivo: vantagem em rastrear e +2 dano contra o tipo de inimigo escolhido.', custo_mana:0, dado:''},
    {nome:'Explorador Natural', descricao:'Passivo: em terreno favorecido, não se perde, dobra velocidade e vantagem em Iniciativa.', custo_mana:0, dado:''},
    {nome:'Tiro Certeiro', descricao:'Ação bônus: ataque adicional à distância usando só o bônus de proficiência (sem mod. atributo) no dano.', custo_mana:0, dado:''},
  ],
  npc: [],
};

// ── Equipamentos iniciais com escolhas — D&D 5e por classe ───────────────────
// Cada entrada tem: arm (armadura fixada), esc (escudo fixado), fixed (itens
// sempre incluídos) e choices (grupos de escolha, cada opção pode sobrescrever
// arm/esc/arma e adicionar itens ao inventário).
const CLASS_EQUIP_CHOICES_WZ = {
  bárbaro: {
    arm:'armadura de peles', esc:null,
    fixed:[
      {nome:'Javelin',       qtd:4, descricao:'Arremesso (9/36m). 1d6 perfurante.'},
      {nome:'Poção de Cura', qtd:1, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma principal', options:[
        {label:'Machado Grande',    arma:'machado grande',  items:[{nome:'Machado Grande',   qtd:1, descricao:'1d12 cortante. Pesado, requer 2 mãos.'}]},
        {label:'2× Machado de Mão', arma:'machado de mão',  items:[{nome:'Machado de Mão',   qtd:2, descricao:'1d6 cortante. Leve, arremesso (6/18m).'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Explorador', items:[{nome:'Pacote de Explorador', qtd:1, descricao:'Mochila, corda, archote×10, ração×10, cantil.'}]},
        {label:'Pacote de Masmorra',   items:[{nome:'Pacote de Masmorra',   qtd:1, descricao:'Pé-de-cabra, martelo, estacas×10, archote.'}]},
      ]},
    ],
  },
  bardo: {
    arm:'armadura de couro', esc:null,
    fixed:[
      {nome:'Armadura de Couro', qtd:1, descricao:'CA 11 + mod.DEX.'},
      {nome:'Adaga',             qtd:1, descricao:'1d4 perfurante. Leve.'},
      {nome:'Poção de Cura',     qtd:1, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma principal', options:[
        {label:'Rapieira',    arma:'rapieira',    items:[{nome:'Rapieira',    qtd:1, descricao:'1d8 perfurante. Finesse.'}]},
        {label:'Espada Longa', arma:'espada longa', items:[{nome:'Espada Longa', qtd:1, descricao:'1d8 (1d10 com 2 mãos) cortante. Versátil.'}]},
        {label:'Adaga extra', arma:'adaga',        items:[{nome:'Adaga',       qtd:1, descricao:'1d4 perfurante. Leve.'}]},
      ]},
      {label:'Instrumento musical', options:[
        {label:'Alaúde', items:[{nome:'Alaúde', qtd:1, descricao:'Foco bárdico. Instrumento de cordas.'}]},
        {label:'Flauta', items:[{nome:'Flauta', qtd:1, descricao:'Foco bárdico. Instrumento de sopro.'}]},
        {label:'Tambor', items:[{nome:'Tambor', qtd:1, descricao:'Foco bárdico. Instrumento de percussão.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Diplomata', items:[{nome:'Pacote de Diplomata', qtd:1, descricao:'Roupas finas, tinta, pena, pergaminhos, malas.'}]},
        {label:'Pacote de Artista',   items:[{nome:'Pacote de Artista',   qtd:1, descricao:'Mochila, colchão, roupas fantasiosas, velas.'}]},
      ]},
    ],
  },
  clérigo: {
    arm:'cota de malha', esc:'escudo',
    fixed:[
      {nome:'Símbolo Sagrado', qtd:1, descricao:'Foco divino para conjuração.'},
      {nome:'Poção de Cura',   qtd:2, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma principal', options:[
        {label:'Maça',             arma:'maça',             items:[{nome:'Maça',             qtd:1, descricao:'1d6 concussão.'}]},
        {label:'Martelo de Guerra', arma:'martelo de guerra', items:[{nome:'Martelo de Guerra', qtd:1, descricao:'1d8 (1d10 com 2 mãos) concussão. Versátil.'}]},
      ]},
      {label:'Armadura', options:[
        {label:'Cota de Malha',      arm:'cota de malha',     esc:'escudo', items:[{nome:'Escudo', qtd:1, descricao:'+2 CA.'}]},
        {label:'Armadura de Couro',  arm:'armadura de couro', esc:null,     items:[]},
        {label:'Cota de Anéis',      arm:'cota de anéis',     esc:'escudo', items:[{nome:'Escudo', qtd:1, descricao:'+2 CA.'}]},
      ]},
      {label:'Arma de apoio', options:[
        {label:'Besta Leve + Virotes', arma_sec:'besta leve', items:[{nome:'Besta Leve', qtd:1, descricao:'1d8 perfurante. 24m.'},{nome:'Virotes', qtd:20, descricao:'Munição.'}]},
        {label:'Escudo extra',                                 items:[{nome:'Escudo',     qtd:1, descricao:'+2 CA.'}]},
      ]},
    ],
  },
  druida: {
    arm:'armadura de couro', esc:'escudo de madeira',
    fixed:[
      {nome:'Armadura de Couro',    qtd:1, descricao:'CA 11 + mod.DEX.'},
      {nome:'Bolsa de Componentes', qtd:1, descricao:'Ervas, pedras e componentes naturais.'},
      {nome:'Poção de Cura',        qtd:1, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Escudo ou arma', options:[
        {label:'Escudo de Madeira', esc:'escudo de madeira', items:[{nome:'Escudo de Madeira', qtd:1, descricao:'+2 CA. Símbolos naturais entalhados.'}]},
        {label:'Arma simples extra', esc:null,               items:[{nome:'Adaga', qtd:1, descricao:'1d4 perfurante. Leve.'}]},
      ]},
      {label:'Arma principal', options:[
        {label:'Cimitarra',      arma:'cimitarra',      items:[{nome:'Cimitarra',      qtd:1, descricao:'1d6 cortante. Finesse, leve.'}]},
        {label:'Bastão Druídico', arma:'bastão druídico', items:[{nome:'Bastão Druídico', qtd:1, descricao:'Foco druídico. 1d6 (1d8) concussão. Versátil.'}]},
      ]},
    ],
  },
  guerreiro: {
    arm:'cota de malha', esc:'escudo',
    fixed:[
      {nome:'Poção de Cura', qtd:1, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Armadura', options:[
        {label:'Cota de Malha',       arm:'cota de malha',     esc:null, items:[{nome:'Cota de Malha',      qtd:1, descricao:'CA 16. Armadura pesada.'}]},
        {label:'Couro + Arco Curto',  arm:'armadura de couro', esc:null, arma_sec:'arco curto', items:[{nome:'Armadura de Couro', qtd:1, descricao:'CA 11 + DEX.'},{nome:'Arco Curto', qtd:1, descricao:'1d6 perfurante. 24m.'},{nome:'Flechas', qtd:20, descricao:'Munição.'}]},
      ]},
      {label:'Arma principal', options:[
        {label:'Espada Longa + Escudo', arma:'espada longa', esc:'escudo', items:[{nome:'Espada Longa', qtd:1, descricao:'1d8 cortante. Versátil.'},{nome:'Escudo', qtd:1, descricao:'+2 CA.'}]},
        {label:'2× Arma Marcial',       arma:'espada longa', esc:null,    items:[{nome:'Espada Longa', qtd:2, descricao:'1d8 cortante. Versátil.'}]},
      ]},
      {label:'Arma de distância', options:[
        {label:'Besta Leve + Virotes', arma_sec:'besta leve', items:[{nome:'Besta Leve', qtd:1, descricao:'1d8 perfurante. 24m.'},{nome:'Virotes', qtd:20, descricao:'Munição.'}]},
        {label:'2× Machadinha',                               items:[{nome:'Machadinha',  qtd:2, descricao:'1d6 cortante. Leve, arremesso.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Masmorra',   items:[{nome:'Pacote de Masmorra',   qtd:1, descricao:'Pé-de-cabra, martelo, estacas, archote.'}]},
        {label:'Pacote de Explorador', items:[{nome:'Pacote de Explorador', qtd:1, descricao:'Mochila, corda, archote×10, ração×10.'}]},
      ]},
    ],
  },
  ladino: {
    arm:'armadura de couro', esc:null,
    fixed:[
      {nome:'Armadura de Couro',     qtd:1, descricao:'CA 11 + mod.DEX.'},
      {nome:'Adaga',                 qtd:2, descricao:'1d4 perfurante. Leve.'},
      {nome:'Ferramentas de Ladrão', qtd:1, descricao:'Para abrir fechaduras e desarmar armadilhas.'},
      {nome:'Poção de Cura',         qtd:1, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma principal', options:[
        {label:'Rapieira',    arma:'rapieira',    items:[{nome:'Rapieira',    qtd:1, descricao:'1d8 perfurante. Finesse.'}]},
        {label:'Espada Curta', arma:'espada curta', items:[{nome:'Espada Curta', qtd:1, descricao:'1d6 perfurante. Leve.'}]},
      ]},
      {label:'Arma de distância', options:[
        {label:'Arco Curto + Flechas', arma_sec:'arco curto', items:[{nome:'Arco Curto', qtd:1, descricao:'1d6 perfurante. 24m.'},{nome:'Flechas', qtd:20, descricao:'Munição.'}]},
        {label:'Espada Curta extra',                          items:[{nome:'Espada Curta', qtd:1, descricao:'1d6 perfurante. Leve.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Arrombador', items:[{nome:'Pacote de Arrombador', qtd:1, descricao:'Pé-de-cabra, archote, farinha, arame.'}]},
        {label:'Pacote de Explorador', items:[{nome:'Pacote de Explorador', qtd:1, descricao:'Mochila, corda, archote×10, ração×10.'}]},
      ]},
    ],
  },
  mago: {
    arm:'robes de mago', esc:null,
    fixed:[
      {nome:'Grimório',     qtd:1, descricao:'Livro de magias com feitiços aprendidos.'},
      {nome:'Adaga',        qtd:1, descricao:'1d4 perfurante. Arma de emergência.'},
      {nome:'Poção de Cura', qtd:1, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma principal', options:[
        {label:'Cajado Arcano', arma:'cajado arcano', items:[{nome:'Cajado Arcano', qtd:1, descricao:'Foco arcano e arma. 1d6 concussão.'}]},
        {label:'Adaga extra',   arma:'adaga',         items:[{nome:'Adaga',        qtd:1, descricao:'1d4 perfurante. Leve.'}]},
      ]},
      {label:'Foco arcano', options:[
        {label:'Bolsa de Componentes', items:[{nome:'Bolsa de Componentes', qtd:1, descricao:'Componentes materiais para magias.'}]},
        {label:'Orbe Arcano',          items:[{nome:'Orbe Arcano',          qtd:1, descricao:'Foco arcano esférico.'}]},
        {label:'Varinha Arcana',       items:[{nome:'Varinha Arcana',       qtd:1, descricao:'Foco arcano em forma de varinha.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Estudioso',  items:[{nome:'Pacote de Estudioso',  qtd:1, descricao:'Livro, tinta, pena, pergaminhos, areia secante.'}]},
        {label:'Pacote de Explorador', items:[{nome:'Pacote de Explorador', qtd:1, descricao:'Mochila, corda, archote×10, ração×10, cantil.'}]},
      ]},
    ],
  },
  monge: {
    arm:null, esc:null,
    fixed:[
      {nome:'Dardos',        qtd:10, descricao:'1d4 perfurante. Arremesso (6/18m).'},
      {nome:'Poção de Cura', qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma principal', options:[
        {label:'Espada Curta', arma:'espada curta', items:[{nome:'Espada Curta', qtd:1, descricao:'1d6 perfurante. Leve.'}]},
        {label:'Bastão',       arma:'bastão',       items:[{nome:'Bastão',       qtd:1, descricao:'1d6 (1d8 com 2 mãos) concussão. Versátil.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Masmorra',   items:[{nome:'Pacote de Masmorra',   qtd:1, descricao:'Pé-de-cabra, martelo, estacas, archote.'}]},
        {label:'Pacote de Explorador', items:[{nome:'Pacote de Explorador', qtd:1, descricao:'Mochila, corda, archote×10, ração×10.'}]},
      ]},
    ],
  },
  paladino: {
    arm:'cota de malha', esc:'escudo sagrado',
    fixed:[
      {nome:'Cota de Malha',   qtd:1, descricao:'CA 16. Armadura pesada.'},
      {nome:'Símbolo Sagrado', qtd:1, descricao:'Foco divino para conjuração.'},
      {nome:'Poção de Cura',   qtd:2, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma principal', options:[
        {label:'Espada Longa + Escudo', arma:'espada longa', esc:'escudo sagrado', items:[{nome:'Espada Longa', qtd:1, descricao:'1d8 cortante. Versátil.'},{nome:'Escudo Sagrado', qtd:1, descricao:'+2 CA. Símbolo divino.'}]},
        {label:'2× Arma Marcial',       arma:'espada longa', esc:null,             items:[{nome:'Espada Longa', qtd:2, descricao:'1d8 cortante. Versátil.'}]},
      ]},
      {label:'Arma de distância', options:[
        {label:'5 Javelins', arma_sec:'javelin', items:[{nome:'Javelin', qtd:5, descricao:'1d6 perfurante. Arremesso (9/36m).'}]},
        {label:'Adaga',                          items:[{nome:'Adaga',   qtd:1, descricao:'1d4 perfurante. Leve.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote Sacerdotal',      items:[{nome:'Pacote Sacerdotal',      qtd:1, descricao:'Cobertor, velas×10, incenso, caixa de estanho.'}]},
        {label:'Pacote de Aventureiro',  items:[{nome:'Pacote de Aventureiro',  qtd:1, descricao:'Mochila, corda, archote×10, kit de primeiros socorros.'}]},
      ]},
    ],
  },
  patrulheiro: {
    arm:'armadura de escamas', esc:null, arma_sec:'arco longo',
    fixed:[
      {nome:'Arco Longo',    qtd:1,  descricao:'1d8 perfurante. Alcance 45m.'},
      {nome:'Flechas',       qtd:20, descricao:'Munição para arco longo.'},
      {nome:'Poção de Cura', qtd:1,  descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Armadura', options:[
        {label:'Armadura de Escamas', arm:'armadura de escamas', items:[{nome:'Armadura de Escamas', qtd:1, descricao:'CA 14 + DEX (máx +2).'}]},
        {label:'Armadura de Couro',   arm:'armadura de couro',   items:[{nome:'Armadura de Couro',   qtd:1, descricao:'CA 11 + mod.DEX.'}]},
      ]},
      {label:'Arma principal', options:[
        {label:'2× Espada Curta',    arma:'espada curta dupla', items:[{nome:'Espada Curta', qtd:2, descricao:'1d6 perfurante. Leve.'}]},
        {label:'Espada Curta + Adaga', arma:'espada curta',     items:[{nome:'Espada Curta', qtd:1, descricao:'1d6 perfurante.'},{nome:'Adaga', qtd:1, descricao:'1d4 perfurante.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Masmorra',   items:[{nome:'Pacote de Masmorra',   qtd:1, descricao:'Pé-de-cabra, martelo, estacas, archote.'}]},
        {label:'Pacote de Explorador', items:[{nome:'Pacote de Explorador', qtd:1, descricao:'Mochila, corda, archote×10, ração×10.'}]},
      ]},
    ],
  },
  bruxo: {
    arm:'armadura de couro', esc:null,
    fixed:[
      {nome:'Armadura de Couro', qtd:1, descricao:'CA 11 + mod.DEX.'},
      {nome:'Adaga',             qtd:2, descricao:'1d4 perfurante. Leve.'},
      {nome:'Poção de Cura',     qtd:1, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma de distância', options:[
        {label:'Besta Leve + Virotes', arma_sec:'besta leve', items:[{nome:'Besta Leve', qtd:1, descricao:'1d8 perfurante. 24m.'},{nome:'Virotes', qtd:20, descricao:'Munição.'}]},
        {label:'Adaga extra',                                 items:[{nome:'Adaga',      qtd:1, descricao:'1d4 perfurante.'}]},
      ]},
      {label:'Foco arcano', options:[
        {label:'Bolsa de Componentes', items:[{nome:'Bolsa de Componentes', qtd:1, descricao:'Componentes materiais.'}]},
        {label:'Orbe Arcano',          items:[{nome:'Orbe Arcano',          qtd:1, descricao:'Foco arcano esférico.'}]},
        {label:'Varinha Arcana',       items:[{nome:'Varinha Arcana',       qtd:1, descricao:'Foco arcano em varinha.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Estudioso',  items:[{nome:'Pacote de Estudioso',  qtd:1, descricao:'Livro, tinta, pena, pergaminhos.'}]},
        {label:'Pacote de Masmorra',   items:[{nome:'Pacote de Masmorra',   qtd:1, descricao:'Pé-de-cabra, martelo, estacas, archote.'}]},
      ]},
    ],
  },
  feiticeiro: {
    arm:'armadura de couro', esc:null,
    fixed:[
      {nome:'Adaga',         qtd:2, descricao:'1d4 perfurante. Leve.'},
      {nome:'Poção de Cura', qtd:1, descricao:'Restaura 1d8+2 de vida.'},
    ],
    choices:[
      {label:'Arma de distância', options:[
        {label:'Besta Leve + Virotes', arma_sec:'besta leve', items:[{nome:'Besta Leve', qtd:1, descricao:'1d8 perfurante. 24m.'},{nome:'Virotes', qtd:20, descricao:'Munição.'}]},
        {label:'Adaga extra',                                 items:[{nome:'Adaga',      qtd:1, descricao:'1d4 perfurante.'}]},
      ]},
      {label:'Foco arcano', options:[
        {label:'Bolsa de Componentes', items:[{nome:'Bolsa de Componentes', qtd:1, descricao:'Componentes materiais.'}]},
        {label:'Orbe Arcano',          items:[{nome:'Orbe Arcano',          qtd:1, descricao:'Foco arcano esférico.'}]},
      ]},
      {label:'Pacote', options:[
        {label:'Pacote de Explorador', items:[{nome:'Pacote de Explorador', qtd:1, descricao:'Mochila, corda, archote×10, ração×10.'}]},
        {label:'Pacote de Masmorra',   items:[{nome:'Pacote de Masmorra',   qtd:1, descricao:'Pé-de-cabra, martelo, estacas, archote.'}]},
      ]},
    ],
  },
  npc: {arm:null, esc:null, fixed:[], choices:[]},
};

// Resolve equipamento final com base nas escolhas do personagem
function wzGetResolvedEquip(char) {
  const def      = CLASS_EQUIP_CHOICES_WZ[char.classe] || CLASS_EQUIP_CHOICES_WZ['npc'];
  const choices  = char._equipChoices || {};
  let arm      = def.arm;
  let esc      = def.esc;
  let arma     = '';
  let arma_sec = def.arma_sec || '';   // arma de distância fixa da classe (ex: arco longo do patrulheiro)
  const inv    = (def.fixed || []).map(it => ({...it}));

  (def.choices || []).forEach((group, g) => {
    const oIdx   = choices[g] ?? 0;
    const option = group.options[Math.min(oIdx, group.options.length - 1)];
    if (!option) return;
    if (option.arm      !== undefined) arm      = option.arm;
    if (option.esc      !== undefined) esc      = option.esc;
    if (option.arma     !== undefined) arma     = option.arma;
    if (option.arma_sec !== undefined) arma_sec = option.arma_sec;
    (option.items || []).forEach(it => inv.push({...it}));
  });

  // fallback arma principal: primeiro choice com arma definida
  if (!arma) {
    for (const [g, group] of (def.choices || []).entries()) {
      const oIdx = choices[g] ?? 0;
      const opt  = group.options[Math.min(oIdx, group.options.length - 1)];
      if (opt?.arma) { arma = opt.arma; break; }
    }
  }
  return { arm, arma, arma_sec, esc, inv };
}

// Renderiza o painel de escolha de equipamentos para o wizard
function wzRenderEquipChoices(i) {
  const char = wzChars[i];
  if (!char) return '';
  const def     = CLASS_EQUIP_CHOICES_WZ[char.classe] || CLASS_EQUIP_CHOICES_WZ['npc'];
  const choices = char._equipChoices || {};

  // ── Grupos de escolha ──────────────────────────────────────────────────
  const groupsHtml = (def.choices || []).map((group, g) => {
    const sel = choices[g] ?? 0;
    const btns = group.options.map((opt, o) => {
      const active = sel === o;
      return `<button onclick="wzSetEquipChoice(${i},${g},${o})" style="`+
        `padding:4px 10px;border-radius:4px;border:1px solid ${active?'var(--ink-user)':'var(--page-edge)'};`+
        `background:${active?'rgba(38,75,130,0.10)':'transparent'};color:${active?'var(--ink-user)':'var(--text-muted)'};`+
        `cursor:pointer;font-size:11px;font-weight:${active?'700':'400'};white-space:nowrap;`+
        `">${escHtml(opt.label)}</button>`;
    }).join('');
    return `<div style="margin-bottom:8px;">`+
      `<div style="font-size:10px;color:var(--text-dim);margin-bottom:4px;font-weight:600;letter-spacing:0.05em;">${escHtml(group.label).toUpperCase()}</div>`+
      `<div style="display:flex;gap:6px;flex-wrap:wrap;">${btns}</div>`+
      `</div>`;
  }).join('');

  const fixedNames = (def.fixed || [])
    .map(it => `${it.nome}${it.qtd > 1 ? ` ×${it.qtd}` : ''}`)
    .join(', ');

  const equipSection = (def.choices || []).length > 0
    ? `<div style="border-top:1px solid var(--page-edge);padding-top:14px;margin-top:6px;">`+
      `<span class="cwc-label" style="margin-bottom:10px;">⚔️ Equipamentos Iniciais</span>`+
      groupsHtml+
      (fixedNames ? `<div style="font-size:10px;color:var(--text-dim);margin-top:2px;">+ fixos: ${fixedNames}</div>` : '')+
      `</div>`
    : '';

  return equipSection;
}

// Atualiza escolha de um grupo de equipamento e re-renderiza só esse painel
function wzSetEquipChoice(i, g, o) {
  const char = wzChars[i];
  if (!char) return;
  if (!char._equipChoices) char._equipChoices = {};
  char._equipChoices[g] = o;
  const el = document.getElementById(`wz-equip-choices-${i}`);
  if (el) el.innerHTML = wzRenderEquipChoices(i);
}

/**
 * CA baseada no tipo de armadura (D&D 5e).
 * Leve: base + DEX. Média: base + DEX (máx +2). Pesada: fixo.
 */
function wzArmorCA(armorName, dexMod) {
  const light  = {'robes de mago':10, 'armadura de couro':11, 'armadura de couro tachado':12};
  const medium = {'armadura de peles':12, 'armadura de escamas':14};
  const heavy  = {'cota de malha':16, 'cota de anéis':14, 'cota de placas':18};
  const n = (armorName || '').toLowerCase();
  if (n in light)  return light[n]  + dexMod;
  if (n in medium) return medium[n] + Math.min(dexMod, 2);
  if (n in heavy)  return heavy[n];
  return 10 + dexMod;
}

// ── Bônus de atributo por raça (D&D 5e SRD) — usado no wizard ───────────────
// Fallback offline; Open5e é consultado no backend ao criar a ficha final.
const RACE_BONUSES_WZ = {
  'humano':    { forca:1, destreza:1, constituicao:1, inteligencia:1, sabedoria:1, carisma:1 },
  'elfo':      { destreza:2 },
  'anão':      { constituicao:2 },
  'halfling':  { destreza:2 },
  'draconato': { forca:2, carisma:1 },
  'gnomo':     { inteligencia:2 },
  'meio-elfo': { carisma:2 },   // +1 em dois outros à escolha do jogador — simplificado
  'meio-orc':  { forca:2, constituicao:1 },
  'tiferino':  { inteligencia:1, carisma:2 },
};

// ── Antecedentes D&D 5e SRD — lista para o wizard ────────────────────────────
const BACKGROUND_LIST_WZ = {
  'acólito':          { skills: ['Perspicácia','Religião'],          items: ['Símbolo sagrado','Livro de orações'] },
  'charlatão':        { skills: ['Enganação','Prestidigitação'],      items: ['Roupas finas','Kit de disfarce'] },
  'criminoso':        { skills: ['Enganação','Furtividade'],          items: ['Pé-de-cabra','Roupas escuras'] },
  'artista':          { skills: ['Acrobacia','Atuação'],              items: ['Instrumento musical','Fantasia'] },
  'artesão de guilda':{ skills: ['Perspicácia','Persuasão'],          items: ['Ferramentas de artesão','Carta de apresentação'] },
  'eremita':          { skills: ['Medicina','Religião'],              items: ['Estojo de pergaminhos','Cobertor'] },
  'herói do povo':    { skills: ['Adestramento de Animais','Sobrevivência'], items: ['Pá','Panela de ferro'] },
  'forasteiro':       { skills: ['Atletismo','Sobrevivência'],        items: ['Cajado','Armadilha de caça'] },
  'nobre':            { skills: ['História','Persuasão'],             items: ['Roupas finas','Anel de sinete'] },
  'sábio':            { skills: ['Arcanismo','História'],             items: ['Tinta e pena','Canivete pequeno'] },
  'marinheiro':       { skills: ['Atletismo','Percepção'],            items: ['Corda de seda 15m','Amuleto da sorte'] },
  'soldado':          { skills: ['Atletismo','Intimidação'],          items: ['Insígnia de patente','Troféu de batalha'] },
  'pivete':           { skills: ['Prestidigitação','Furtividade'],    items: ['Canivete pequeno','Mapa da cidade'] },
};

// Retorna string de info do antecedente para exibir no card
function wzBgInfo(bg) {
  const d = BACKGROUND_LIST_WZ[bg];
  if (!d) return '';
  const skills = d.skills ? `Perícias: ${d.skills.join(', ')}` : '';
  const items  = d.items  ? `Itens: ${d.items.join(', ')}`     : '';
  return [skills, items].filter(Boolean).join(' · ');
}

// Chamado quando o usuário troca o antecedente no select
function wzOnBackgroundChange(i, bg) {
  const char = wzChars[i];
  if (!char) return;
  char.background = bg || '';
  // Atualiza o info box sem re-renderizar o card todo
  const infoEl = document.getElementById(`wz-bg-info-${i}`);
  if (infoEl) {
    infoEl.textContent = bg ? wzBgInfo(bg) : '';
  } else if (bg) {
    // Re-renderiza o card para mostrar o info box pela primeira vez
    const list = document.getElementById('wz-chars-list');
    if (list) list.innerHTML = wzChars.map((c, idx) => wzRenderCharCard(c, idx)).join('');
  }
}


// ── Magias iniciais por classe — objetos completos espelhando DEFAULT_SPELLS_BY_CLASS (Python) ──
// Mantido em sincronismo com tools_dnd.py → DEFAULT_SPELLS_BY_CLASS
// Nomes em inglês para coincidir com os nomes retornados pela API Open5e,
// evitando duplicatas ao buscar magias.
const INITIAL_SPELLS_WZ = {
  mago: [
    // 3 cantrips
    {nome:'Prestidigitation', descricao:'[Truque] Efeitos mágicos menores: acender velas, limpar objetos, sons.',  custo_mana:0, dado:''},
    {nome:'Light',            descricao:'[Truque] Objeto tocado emite luz como tocha por 1 hora.',                 custo_mana:0, dado:''},
    {nome:'Ray of Frost',     descricao:'[Truque] Ataque mágico à distância: 1d8 dano de frio + velocidade -3m.', custo_mana:0, dado:'1d8'},
    // 6 magias no Livro de Magias (nível 1)
    {nome:'Magic Missile',    descricao:'[Evocação] 3 dardos de força, 1d4+1 dano cada. Automático.',             custo_mana:4, dado:'1d4'},
    {nome:'Burning Hands',    descricao:'[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.',           custo_mana:4, dado:'3d6'},
    {nome:'Sleep',            descricao:'[Encantamento] Afeta 5d8 PV de criaturas, começando pelas mais fracas.',  custo_mana:4, dado:'5d8'},
    {nome:'Shield',           descricao:'[Abjuração] Reação: +5 CA e imune a Magic Missile até o próximo turno.', custo_mana:4, dado:''},
    {nome:'Mage Armor',       descricao:'[Abjuração] CA base = 13 + Mod. Destreza enquanto não usar armadura.',   custo_mana:4, dado:''},
    {nome:'Identify',         descricao:'[Adivinhação] Ritual: revela propriedades mágicas de um item ou magia.', custo_mana:4, dado:''},
  ],
  feiticeiro: [
    // 4 cantrips
    {nome:'Sacred Flame',     descricao:'[Truque] Ataque de magia: 1d8 dano radiante (DEX não conta para CA).',   custo_mana:0, dado:'1d8'},
    {nome:'Light',            descricao:'[Truque] Objeto emite luz como tocha por 1 hora.',                        custo_mana:0, dado:''},
    {nome:'Ray of Frost',     descricao:'[Truque] Ataque mágico à distância: 1d8 dano de frio.',                  custo_mana:0, dado:'1d8'},
    {nome:'Prestidigitation', descricao:'[Truque] Efeitos mágicos menores: criar sons, luzes ou odores sutis.',   custo_mana:0, dado:''},
    // 2 magias conhecidas (nível 1)
    {nome:'Magic Missile',    descricao:'[Evocação] 3 dardos de força, 1d4+1 dano cada. Automático.',             custo_mana:4, dado:'1d4'},
    {nome:'Burning Hands',    descricao:'[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.',           custo_mana:4, dado:'3d6'},
  ],
  bruxo: [
    // 2 cantrips
    {nome:'Eldritch Blast',   descricao:'[Truque] Ataque mágico à distância: 1d10 dano de força.',                custo_mana:0, dado:'1d10'},
    {nome:'Minor Illusion',   descricao:'[Truque] Cria som ou imagem ilusória por 1 minuto.',                     custo_mana:0, dado:''},
    // 2 magias conhecidas (nível 1)
    {nome:'Hex',              descricao:'[Encantamento] Amaldiçoa alvo: +1d6 dano necrótico nos ataques. Concentração.', custo_mana:4, dado:'1d6'},
    {nome:'Armor of Agathys', descricao:'[Abjuração] Ganha 5 PV temporários; atacante leva 5 dano de frio.',     custo_mana:4, dado:''},
  ],
  clérigo: [
    // 3 cantrips
    {nome:'Sacred Flame',  descricao:'[Truque] Ataque de magia: 1d8 dano radiante (DEX não conta para CA).',               custo_mana:0, dado:'1d8'},
    {nome:'Guidance',      descricao:'[Truque] Toque: criatura ganha +1d4 em um teste de atributo.',                       custo_mana:0, dado:'1d4'},
    {nome:'Thaumaturgy',   descricao:'[Truque] Manifesta um prodígio sobrenatural menor: vozes, luzes, tremores.',          custo_mana:0, dado:''},
    // Magias preparadas (SAB mod + nível do clérigo)
    {nome:'Cure Wounds',   descricao:'[Evocação] Cura 1d8 + modificador de SAB de PV.',                                    custo_mana:4, dado:'1d8'},
    {nome:'Bless',         descricao:'[Encantamento] Até 3 criaturas ganham +1d4 em ataques e salvaguardas. Concentração.', custo_mana:4, dado:'1d4'},
    {nome:'Guiding Bolt',  descricao:'[Evocação] Ataque mágico à distância: 4d6 dano radiante. Vantagem contra alvos.',    custo_mana:4, dado:'4d6'},
  ],
  druida: [
    // 2 cantrips
    {nome:'Produce Flame', descricao:'[Truque] Chama na mão: ilumina 3m ou ataca à distância, 1d8 dano de fogo.', custo_mana:0, dado:'1d8'},
    {nome:'Guidance',      descricao:'[Truque] Toque: criatura ganha +1d4 em um teste de atributo.',               custo_mana:0, dado:'1d4'},
    // Magias preparadas (SAB mod + nível do druida)
    {nome:'Entangle',      descricao:'[Conjuração] Área de 6m quadrada emaranha criaturas. Concentração 1 min.',   custo_mana:4, dado:''},
    {nome:'Cure Wounds',   descricao:'[Evocação] Cura 1d8 + modificador de SAB de PV.',                            custo_mana:4, dado:'1d8'},
    {nome:'Fog Cloud',     descricao:'[Conjuração] Nuvem de névoa 6m de raio, bloqueia visão. Concentração.',      custo_mana:4, dado:''},
  ],
  bardo: [
    // 2 cantrips
    {nome:'Vicious Mockery', descricao:'[Truque] Ataque psíquico verbal: 1d4 dano psíquico + desvantagem no próximo ataque.', custo_mana:0, dado:'1d4'},
    {nome:'Light',           descricao:'[Truque] Objeto emite luz como tocha por 1 hora.',                                    custo_mana:0, dado:''},
    // 4 magias conhecidas (nível 1)
    {nome:'Healing Word',    descricao:'[Evocação] Ação bônus: cura 1d4 + modificador de CAR de PV.',                         custo_mana:4, dado:'1d4'},
    {nome:'Charm Person',    descricao:'[Encantamento] Enfeitiça uma criatura humanóide por 1 hora. Concentração.',            custo_mana:4, dado:''},
    {nome:'Sleep',           descricao:'[Encantamento] Afeta 5d8 PV de criaturas, começando pelas mais fracas.',              custo_mana:4, dado:'5d8'},
    {nome:'Thunderwave',     descricao:'[Evocação] Cubo de 4,5m: 2d8 dano trovejante + empurra 3m. CON salva metade.',       custo_mana:4, dado:'2d8'},
  ],
  // Paladino e Patrulheiro: magias começam no nível 2. Sem magias iniciais no nível 1.
  // O painel de magias ainda aparece para que o jogador possa adicionar manualmente.
  paladino:    [],
  patrulheiro: [],
};

// Classes que têm painel de magias no wizard
const CASTER_CLASSES_WZ = new Set(Object.keys(INITIAL_SPELLS_WZ));

// ── Wizard: busca de magias Open5e (mesma barra do editor de campanha) ───────
// Modo livre: sem filtro de classe e até nível 9 (qualquer magia).
// Modo normal: filtra pela classe; o nível de magia acompanha o nível do PJ.
const wzSpellTimers = {};
function wzSpellQueryParams(char) {
  const freeMode = !!char.freeMode;
  return {
    classe:   freeMode ? '' : (char.classe || 'mago'),
    maxLevel: freeMode ? 9  : edMaxSpellLevel(char.nivel || 1),
  };
}
function wzTriggerSpellSearch(i) {
  clearTimeout(wzSpellTimers[i]);
  wzSpellTimers[i] = setTimeout(() => wzDoSpellSearch(i), 420);
}
async function wzDoSpellSearch(i) {
  const char = wzChars[i];
  if (!char) return;
  char._spellLoading = true;
  wzRefreshSpellPanel(i);
  try {
    const { classe, maxLevel } = wzSpellQueryParams(char);
    const params = new URLSearchParams({ max_level: maxLevel });
    if (classe) params.set('class', classe);
    const q = (char._spellQuery || '').trim();
    if (q) params.set('q', q);
    // Filtro de nível exato (sobrepõe max_level na API)
    const lvlF = char._spellLevelFilter;
    if (lvlF !== null && lvlF !== undefined) params.set('spell_level', lvlF);
    const res  = await authFetch(`${API}/api/dnd/class-spells?${params}`);
    const data = await res.json();
    char._spellResults = data.spells || [];
  } catch (_) {
    char._spellResults = [];
  }
  char._spellLoading = false;
  wzRefreshSpellPanel(i);
}
function wzRefreshSpellPanel(i) {
  const el = document.getElementById(`wz-spell-panel-${i}`);
  if (el) el.innerHTML = wzBuildSpellPanel(i);
}
function wzBuildSpellPanel(i) {
  const char     = wzChars[i];
  if (!char) return '';
  const loading   = char._spellLoading;
  const results   = char._spellResults || [];
  const query     = escHtml(char._spellQuery || '');
  const rawQuery  = (char._spellQuery || '').trim();
  const selected  = char._selectedSpells || [];
  const lvlF      = char._spellLevelFilter;          // null | 0–9
  const { classe, maxLevel } = wzSpellQueryParams(char);
  const scopeMsg  = classe
    ? `Magias de <strong>${escHtml(classe)}</strong> até Nv.${maxLevel}`
    : `Modo livre — qualquer magia até Nv.${maxLevel}`;

  // ── Botões de filtro por nível ──────────────────────────────────────────
  const lvlBtnStyle = (active) =>
    `padding:3px 8px;border-radius:3px;border:1px solid ${active?'var(--ink-user)':'var(--page-edge)'};`+
    `background:${active?'rgba(38,75,130,0.12)':'transparent'};color:${active?'var(--ink-user)':'var(--text-muted)'};`+
    `cursor:pointer;font-size:10px;font-family:monospace;font-weight:${active?'700':'400'};`;
  const allActive  = lvlF === null;
  let levelBtns = `<button style="${lvlBtnStyle(allActive)}" `+
    `onclick="wzChars[${i}]._spellLevelFilter=null;wzChars[${i}]._spellResults=[];wzDoSpellSearch(${i})">Todos</button>`;
  levelBtns += `<button style="${lvlBtnStyle(lvlF===0)}" `+
    `onclick="wzChars[${i}]._spellLevelFilter=0;wzChars[${i}]._spellResults=[];wzDoSpellSearch(${i})">C</button>`;
  for (let n = 1; n <= maxLevel; n++) {
    levelBtns += `<button style="${lvlBtnStyle(lvlF===n)}" `+
      `onclick="wzChars[${i}]._spellLevelFilter=${n};wzChars[${i}]._spellResults=[];wzDoSpellSearch(${i})">${n}</button>`;
  }

  // ── Contagens e limites de magias (modo livre = sem limite) ───────────────
  const _wzLimit       = char.freeMode ? null : getSpellLimit(char.classe, char.nivel, char.stats);
  const _wzCantripCnt  = selected.filter(s => s.nivel_magia === 0).length;
  const _wzLeveledCnt  = selected.filter(s => s.nivel_magia > 0).length;

  // ── Lista de resultados (agrupada por nível quando sem filtro e sem query) ──
  const renderSpellRow = (sp) => {
    const badge   = sp.nivel_magia === 0 ? 'C' : `${sp.nivel_magia}`;
    const manaTag = sp.custo_mana > 0 ? ` · ${sp.custo_mana} mana` : '';
    const has     = selected.some(s => s.nome.toLowerCase() === sp.nome.toLowerCase());
    const isCantrip = sp.nivel_magia === 0;
    const limitReached = !has && _wzLimit && (isCantrip ? _wzCantripCnt >= _wzLimit.maxCantrips : _wzLeveledCnt >= _wzLimit.maxSpells);
    const regIdx  = _habInfoRegistry.length;
    _habInfoRegistry.push((has || limitReached) ? null : () => { wzAddSpell(i, sp); document.getElementById('hab-info-popup')?.remove(); });
    const spJson  = JSON.stringify(sp).replace(/"/g,'&quot;');
    return `<div class="ed-search-result ${has?'ed-search-result-added':''}" onclick="showHabInfo(event,${spJson},${regIdx},${has},${limitReached})" style="cursor:pointer;">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <span class="ed-spell-badge" style="min-width:22px;text-align:center;">${badge}</span>
        <strong style="font-size:13px;">${escHtml(sp.nome)}</strong>
        ${sp.dado?`<span style="font-family:monospace;font-size:10px;color:var(--text-muted);">${escHtml(sp.dado)}</span>`:''}
        ${manaTag?`<span style="font-size:10px;color:var(--ink-user);">${manaTag}</span>`:''}
        ${sp.concentracao?`<span style="font-size:9px;color:var(--text-muted);border:1px solid var(--page-edge);border-radius:2px;padding:0 3px;">conc.</span>`:''}
        ${sp.ritual?`<span style="font-size:9px;color:var(--text-muted);border:1px solid var(--page-edge);border-radius:2px;padding:0 3px;">ritual</span>`:''}
        ${has?`<span style="font-size:10px;color:var(--green);">✓</span>`:''}
        ${limitReached&&!has?`<span style="font-size:9px;color:var(--ink-sys);border:1px solid currentColor;border-radius:2px;padding:0 3px;opacity:0.7;">limite</span>`:''}
      </div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:3px;">${escHtml((sp.descricao||'').slice(0,100))}${(sp.descricao||'').length>100?'…':''}</div>
    </div>`;
  };

  let listHtml;
  if (loading) {
    listHtml = '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">A carregar magias...</div>';
  } else if (results.length === 0) {
    listHtml = `<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">
      Nenhuma magia encontrada. Tente buscar pelo nome em inglês (ex: "fireball", "shield").
    </div>`;
  } else if (!rawQuery && lvlF === null) {
    // Agrupa por nível quando navegando sem filtro
    const groups = {};
    results.forEach(sp => {
      const k = sp.nivel_magia;
      if (!groups[k]) groups[k] = [];
      groups[k].push(sp);
    });
    const groupLabels = { 0: 'Cantrips (Nv. 0)' };
    listHtml = Object.keys(groups).sort((a,b) => a-b).map(lvl => {
      const label = groupLabels[lvl] || `Nível ${lvl}`;
      return `<div style="margin-bottom:8px;">
        <div style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;padding:4px 0 4px 2px;border-bottom:1px solid var(--page-edge);margin-bottom:4px;">${label}</div>
        ${groups[lvl].map(renderSpellRow).join('')}
      </div>`;
    }).join('');
    if (results.length >= 100) {
      listHtml += `<div style="font-size:11px;color:var(--text-dim);font-style:italic;padding:6px 0;">
        Mostrando ${results.length} magias — filtre por nível ou pesquise para ver mais.
      </div>`;
    }
  } else {
    listHtml = results.map(renderSpellRow).join('');
  }

  return `
    <div>
      <div style="font-size:11px;color:var(--ink-user);margin-bottom:8px;">${scopeMsg} · SRD Open5e${_wzLimit ? `<span style="font-size:10px;font-family:monospace;color:var(--text-muted);margin-left:8px;">| C: ${_wzCantripCnt}/${_wzLimit.maxCantrips} ✨ ${_wzLeveledCnt}/${_wzLimit.maxSpells}</span>` : ''}</div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px;">${levelBtns}</div>
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <input id="wz-spell-q-${i}" value="${query}" placeholder="Buscar magia (ex: fireball)..."
          oninput="wzChars[${i}]._spellQuery=this.value;wzTriggerSpellSearch(${i})" style="flex:1;font-size:13px;">
        <button class="clean-button" style="width:auto;padding:4px 10px;margin:0;font-size:12px;" onclick="wzDoSpellSearch(${i})">🔍</button>
      </div>
      <div class="ed-search-results-list" style="max-height:300px;">${listHtml}</div>
      ${selected.length ? `<div style="font-size:11px;color:var(--text-muted);margin-top:10px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
        <strong>Selecionadas (${selected.length}):</strong>
        ${selected.map(s => {
          const safe = s.nome.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
          return `<span class="ed-spell-badge" style="display:inline-flex;align-items:center;gap:3px;">${escHtml(s.nome)}<button onclick="wzRemoveSpell(${i},'${safe}')" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:11px;padding:0;line-height:1;">✕</button></span>`;
        }).join('')}
      </div>` : ''}
    </div>`;
}
function wzAddSpell(i, spell) {
  const char = wzChars[i];
  if (!char) return;
  char._selectedSpells = char._selectedSpells || [];
  if (!char._selectedSpells.some(s => s.nome.toLowerCase() === spell.nome.toLowerCase())) {
    char._selectedSpells.push({
      nome:       spell.nome,
      descricao:  [
        spell.escola ? `[${spell.escola}${spell.ritual?' (ritual)':''}${spell.concentracao?' (conc.)':''}]` : '',
        spell.descricao || '',
      ].filter(Boolean).join(' '),
      custo_mana:  spell.custo_mana ?? 0,
      dado:        spell.dado || '',
      nivel_magia: spell.nivel_magia ?? 0,
    });
  }
  // Atualiza o painel de magias (chips de selecionadas + marcador ✓) e o contador da aba
  wzRefreshSpellPanel(i);
  const tabEl = document.getElementById(`wz-hab-tab-spells-${i}`);
  if (tabEl) tabEl.textContent = `✨ Magias (${char._selectedSpells.length})`;
}
function wzRemoveSpell(i, nome) {
  const char = wzChars[i];
  if (!char) return;
  char._selectedSpells = (char._selectedSpells || []).filter(s => s.nome.toLowerCase() !== nome.toLowerCase());
  wzRefreshSpellPanel(i);
  const tabEl = document.getElementById(`wz-hab-tab-spells-${i}`);
  if (tabEl) tabEl.textContent = char._selectedSpells.length
    ? `✨ Magias (${char._selectedSpells.length})` : '✨ Magias';
}

const CLASS_DATA_WZ = {
  bárbaro:     { hit_die: 12, mana_per_level: 0,  mana_stat: null,          label: 'Bárbaro' },
  guerreiro:   { hit_die: 10, mana_per_level: 2,  mana_stat: 'forca',       label: 'Guerreiro' },
  paladino:    { hit_die: 10, mana_per_level: 5,  mana_stat: 'carisma',     label: 'Paladino' },
  patrulheiro: { hit_die: 8,  mana_per_level: 4,  mana_stat: 'sabedoria',   label: 'Patrulheiro' },
  bardo:       { hit_die: 8,  mana_per_level: 6,  mana_stat: 'carisma',     label: 'Bardo' },
  clérigo:     { hit_die: 8,  mana_per_level: 8,  mana_stat: 'sabedoria',   label: 'Clérigo' },
  druida:      { hit_die: 8,  mana_per_level: 8,  mana_stat: 'sabedoria',   label: 'Druida' },
  monge:       { hit_die: 8,  mana_per_level: 4,  mana_stat: 'sabedoria',   label: 'Monge' },
  ladino:      { hit_die: 8,  mana_per_level: 2,  mana_stat: 'destreza',    label: 'Ladino' },
  mago:        { hit_die: 6,  mana_per_level: 10, mana_stat: 'inteligencia', label: 'Mago' },
  feiticeiro:  { hit_die: 6,  mana_per_level: 10, mana_stat: 'carisma',     label: 'Feiticeiro' },
  bruxo:       { hit_die: 8,  mana_per_level: 8,  mana_stat: 'carisma',     label: 'Bruxo' },
  npc:         { hit_die: 8,  mana_per_level: 0,  mana_stat: null,          label: 'NPC' },
};

// Point Buy costs: stat value → point cost
const PB_COST = { 8:0, 9:1, 10:2, 11:3, 12:4, 13:5, 14:7, 15:9 };
const PB_BUDGET = 27;
const STATS_WZ = ['forca','destreza','constituicao','inteligencia','sabedoria','carisma'];
const STAT_ABBR = { forca:'FOR', destreza:'DES', constituicao:'CON', inteligencia:'INT', sabedoria:'SAB', carisma:'CAR' };
const STAT_LABEL = { forca:'Força', destreza:'Destreza', constituicao:'Constituição', inteligencia:'Inteligência', sabedoria:'Sabedoria', carisma:'Carisma' };

// ── Estado do wizard ──────────────────────────────────────
let wzStep = 1;
let wzChars = [];    // [{name,desc,traits,status,notes,role,isParty,isDnd,freeMode,classe,raca,stats:{...}}]
let wzLocs  = [];    // [{name,description,details,notes}]
let wzEvts  = [];    // [{summary,location,consequence}]
let wzSelectedModel = '';

// ── Abrir / fechar ─────────────────────────────────────────
function openWizard() {
  wzStep = 1;
  wzChars = [];
  wzLocs  = [];
  wzEvts  = [];
  // reset fields
  ['wz-name','wz-summary','wz-scene','wz-location'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  document.getElementById('wz-type').value = 'dnd';
  document.getElementById('wz-ai-toggle').checked = false;
  document.getElementById('wz-ai-section').classList.add('hidden');
  document.getElementById('wz-ai-hint').classList.remove('hidden');
  document.getElementById('wz-locations-list').innerHTML = '';
  document.getElementById('wz-events-list').innerHTML = '';
  document.getElementById('wz-chars-list').innerHTML = '';
  wzRenderStep();
  document.getElementById('wizard-overlay').classList.remove('hidden');
  document.getElementById('wizard-scroll').scrollTop = 0;
}

function closeWizard() {
  document.getElementById('wizard-overlay').classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('wizard-overlay')?.addEventListener('click', e => {
    if (e.target === document.getElementById('wizard-overlay')) closeWizard();
  });
});

// ── Navegação ─────────────────────────────────────────────
function wizardGoTo(step) {
  if (step === 2 && wzStep === 1) { if (!wzValidateStep1()) return; }
  wzStep = step;
  wzRenderStep();
}

function wizardNext() {
  if (wzStep === 1) {
    if (!wzValidateStep1()) return;
    wzStep = 2;
    wzRenderStep();
  }
}

function wizardBack() {
  if (wzStep === 2) { wzStep = 1; wzRenderStep(); }
}

function wzRenderStep() {
  document.getElementById('wz-panel-1').classList.toggle('hidden', wzStep !== 1);
  document.getElementById('wz-panel-2').classList.toggle('hidden', wzStep !== 2);
  document.getElementById('wz-back-btn').classList.toggle('hidden', wzStep === 1);
  document.getElementById('wz-next-btn').classList.toggle('hidden', wzStep === 2);
  document.getElementById('wz-create-btn').classList.toggle('hidden', wzStep === 1);
  document.getElementById('wz-err').textContent = '';

  // Step dots
  ['1','2'].forEach(n => {
    const dot = document.getElementById(`wz-dot-${n}`);
    dot.classList.remove('active','done');
    const s = parseInt(n);
    if (s === wzStep) dot.classList.add('active');
    else if (s < wzStep) dot.classList.add('done');
  });

  if (wzStep === 2) {
    const isDnd = document.getElementById('wz-type').value === 'dnd';
    document.getElementById('wz-char-mode-hint').textContent =
      isDnd ? 'Modo D&D: campos de ficha completa disponíveis.' : 'Modo narrativo: campos básicos.';
    wzRenderChars();
  }
  document.getElementById('wizard-scroll').scrollTop = 0;
}

function wzValidateStep1() {
  const name = document.getElementById('wz-name').value.trim();
  if (!name) { document.getElementById('wz-err').textContent = 'Nome da campanha é obrigatório.'; return false; }
  document.getElementById('wz-err').textContent = '';
  return true;
}

function wizardValidate() { wzValidateStep1(); }

// ── IA: gerar lore ─────────────────────────────────────────
function toggleAiCreate(on) {
  document.getElementById('wz-ai-section').classList.toggle('hidden', !on);
  document.getElementById('wz-ai-hint').classList.toggle('hidden', on);
}

async function generateLore() {
  const prompt = document.getElementById('wz-ai-prompt').value.trim();
  if (!prompt) { document.getElementById('wz-ai-status').textContent = 'Escreva uma ideia antes.'; return; }
  const btn = document.getElementById('wz-ai-btn');
  const status = document.getElementById('wz-ai-status');
  btn.disabled = true;
  btn.textContent = '⏳ Gerando...';
  status.textContent = '';
  try {
    const keys  = typeof window.getApiKeys === 'function' ? window.getApiKeys() : {};
    const model = document.getElementById('model-select')?.value || 'gemini-2.0-flash';
    const campaignType = document.getElementById('wz-type')?.value || 'fantasia';
    const res = await authFetch(`${API}/api/campaigns/generate-lore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        model,
        campaign_type:    campaignType,
        google_api_key:   keys.google_api_key   || '',
        deepseek_api_key: keys.deepseek_api_key  || '',
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'Erro desconhecido');
    const lore = data.lore;
    if (lore.story_summary)    document.getElementById('wz-summary').value  = lore.story_summary;
    if (lore.current_scene)    document.getElementById('wz-scene').value    = lore.current_scene;
    if (lore.current_location) document.getElementById('wz-location').value = lore.current_location;
    if (Array.isArray(lore.locations)) {
      wzLocs = lore.locations.map(l => ({
        name: l.name || '', description: l.description || '', details: l.details || '', notes: l.notes || '',
      }));
      wzRenderLocs();
    }
    // Pré-popula personagens gerados pela IA na etapa 2
    if (Array.isArray(lore.characters) && lore.characters.length) {
      wzChars = lore.characters.map((c, idx) => ({
        name:        c.name        || '',
        description: c.description || '',
        traits:      c.traits      || '',
        status:      'vivo',
        notes:       c.notes       || '',
        role:        c.role        || '',
        isParty:     true,
        classe:      (c.classe || 'guerreiro').toLowerCase().trim(),
        raca:        (c.raca   || 'humano').toLowerCase().trim(),
        freeMode:    false,
        stats: { forca:10, destreza:10, constituicao:10, inteligencia:10, sabedoria:10, carisma:10 },
        extras:      {},
        _asiBonus: {}, _habTab: 'feats',
        _spellLevelFilter: null, _spellQuery: '', _spellResults: [], _spellLoading: false,
        _classFeatures: [], _featLoading: false,
        _selectedSpells: [], _selectedFeats: [],
        _equipChoices: {},
        _open:       idx === 0,
      }));
      const n = wzChars.length;
      status.style.color = 'var(--green)';
      status.textContent = `✓ Lore gerado com ${n} personagem${n > 1 ? 's' : ''}! Revise os campos.`;
    } else {
      status.style.color = 'var(--green)';
      status.textContent = '✓ Lore gerado! Revise os campos.';
    }
  } catch (e) {
    status.style.color = 'var(--red)';
    status.textContent = `✕ ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = '✨ Gerar com IA';
  }
}

// ── Locais ─────────────────────────────────────────────────
function addWzLocation() {
  wzLocs.push({ name:'', description:'', details:'', notes:'' });
  wzRenderLocs();
}
function removeWzLocation(i) {
  wzLocs.splice(i, 1);
  wzRenderLocs();
}
function wzRenderLocs() {
  const container = document.getElementById('wz-locations-list');
  if (!wzLocs.length) { container.innerHTML = ''; return; }
  container.innerHTML = wzLocs.map((loc, i) => `
    <div class="wz-loc-card">
      <button onclick="removeWzLocation(${i})" style="position:absolute;top:8px;right:8px;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:14px;">✕</button>
      <div class="cwc-row2" style="margin-bottom:8px;">
        <div>
          <span class="cwc-label">Nome</span>
          <input value="${escHtml(loc.name)}" onchange="wzLocs[${i}].name=this.value" placeholder="Nome do local">
        </div>
        <div>
          <span class="cwc-label">Detalhes geográficos</span>
          <input value="${escHtml(loc.details)}" onchange="wzLocs[${i}].details=this.value" placeholder="Pontos específicos...">
        </div>
      </div>
      <span class="cwc-label">Descrição</span>
      <textarea rows="2" onchange="wzLocs[${i}].description=this.value" placeholder="Descrição sensorial...">${escHtml(loc.description)}</textarea>
    </div>`).join('');
}

// ── Eventos ────────────────────────────────────────────────
function addWzEvent() {
  wzEvts.push({ summary:'', location:'', consequence:'' });
  wzRenderEvts();
}
function removeWzEvent(i) {
  wzEvts.splice(i, 1);
  wzRenderEvts();
}
function wzRenderEvts() {
  const container = document.getElementById('wz-events-list');
  if (!wzEvts.length) { container.innerHTML = ''; return; }
  container.innerHTML = wzEvts.map((ev, i) => `
    <div class="wz-evt-card">
      <button onclick="removeWzEvent(${i})" style="position:absolute;top:8px;right:8px;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:14px;">✕</button>
      <span class="cwc-label">Resumo do evento</span>
      <textarea rows="2" onchange="wzEvts[${i}].summary=this.value" placeholder="O que aconteceu?">${escHtml(ev.summary)}</textarea>
      <div class="cwc-row2" style="margin-top:8px;">
        <div>
          <span class="cwc-label">Local</span>
          <input value="${escHtml(ev.location)}" onchange="wzEvts[${i}].location=this.value" placeholder="Onde ocorreu?">
        </div>
        <div>
          <span class="cwc-label">Consequência</span>
          <input value="${escHtml(ev.consequence)}" onchange="wzEvts[${i}].consequence=this.value" placeholder="O que mudou?">
        </div>
      </div>
    </div>`).join('');
}

// ── Personagens ────────────────────────────────────────────
function onWizardTypeChange() {
  if (wzStep === 2) {
    const isDnd = document.getElementById('wz-type').value === 'dnd';
    document.getElementById('wz-char-mode-hint').textContent =
      isDnd ? 'Modo D&D: campos de ficha completa disponíveis.' : 'Modo narrativo: campos básicos.';
    wzRenderChars();
  }
}

function addWzChar() {
  wzChars.push({
    name:'', description:'', traits:'', status:'vivo', notes:'', role:'',
    isParty: true,
    classe: 'guerreiro', raca: 'humano', freeMode: false, background: '',
    nivel: 1,
    stats: { forca:10, destreza:10, constituicao:10, inteligencia:10, sabedoria:10, carisma:10 },
    extras: {},
    // search panel state (not persisted)
    _asiBonus: {},
    _habTab: 'feats',              // aba ativa: 'feats' | 'spells'
    _spellLevelFilter: null,       // null = todos; 0–9 = nível exato
    _spellQuery: '', _spellResults: [], _spellLoading: false,
    _classFeatures: [], _featLoading: false,
    _selectedSpells: [], _selectedFeats: [],
    _equipChoices: {},
    _open: true,
  });
  wzRenderChars();
  // Scroll to new card
  setTimeout(() => {
    const cards = document.querySelectorAll('.cwc');
    if (cards.length) cards[cards.length-1].scrollIntoView({ behavior:'smooth', block:'nearest' });
  }, 50);
}

function removeWzChar(i) {
  wzChars.splice(i, 1);
  wzRenderChars();
}

function toggleWzChar(i) {
  wzChars[i]._open = !wzChars[i]._open;
  const body = document.getElementById(`cwc-body-${i}`);
  if (body) body.classList.toggle('hidden', !wzChars[i]._open);
  const arrow = document.getElementById(`cwc-arrow-${i}`);
  if (arrow) arrow.textContent = wzChars[i]._open ? '▾' : '▸';
}

function wzStatMod(v) {
  const m = Math.floor((parseInt(v) - 10) / 2);
  return (m >= 0 ? '+' : '') + m;
}

function wzPointsUsed(stats) {
  return STATS_WZ.reduce((s, k) => {
    const v = Math.max(8, Math.min(15, parseInt(stats[k]) || 8));
    return s + (PB_COST[v] || 0);
  }, 0);
}

function wzCalcSheet(char) {
  const isDnd = document.getElementById('wz-type').value === 'dnd';
  if (!isDnd) return null;
  const cls    = CLASS_DATA_WZ[char.classe] || CLASS_DATA_WZ['guerreiro'];
  const stats  = char.stats;
  const nivel  = Math.max(1, parseInt(char.nivel) || 1);
  const conMod = Math.floor((parseInt(stats.constituicao) - 10) / 2);
  const dexMod = Math.floor((parseInt(stats.destreza) - 10) / 2);
  // HP: nível 1 = hit_die + CON; cada nível seguinte = avg(die) + CON
  const avgDie = Math.floor(cls.hit_die / 2) + 1;
  const hp     = Math.max(nivel, (cls.hit_die + conMod) + (nivel - 1) * Math.max(1, avgDie + conMod));
  const ca     = 10 + dexMod;
  let mana = 0;
  if (cls.mana_stat && cls.mana_per_level > 0) {
    const mStatMod = Math.floor((parseInt(stats[cls.mana_stat]) - 10) / 2);
    mana = Math.max(0, (cls.mana_per_level + mStatMod) * nivel);
  }
  return { hp, ca, mana, hit_die: cls.hit_die };
}

// ── Troca de raça no wizard ───────────────────────────────────────────────────
// Remove os bônus da raça anterior, aplica os da nova raça,
// re-renderiza o grid de atributos e recalcula HP/CA/Mana.
function wzOnRaceChange(i, newRace) {
  const char = wzChars[i];
  if (!char) return;

  const oldBonuses = RACE_BONUSES_WZ[char.raca] || {};
  const newBonuses = RACE_BONUSES_WZ[newRace]   || {};

  // Remove bônus antigo e aplica novo em cada atributo
  Object.keys({ ...oldBonuses, ...newBonuses }).forEach(stat => {
    const rem = oldBonuses[stat] || 0;
    const add = newBonuses[stat] || 0;
    // Base = valor atual - bônus antigo + bônus novo
    char.stats[stat] = Math.max(1, (char.stats[stat] || 8) - rem + add);
    // Atualiza exibição do modificador
    const modEl = document.getElementById(`wz-mod-${i}-${stat}`);
    if (modEl) modEl.textContent = wzStatMod(char.stats[stat]);
  });

  char.raca = newRace;

  // Re-renderiza o grid para refletir os novos valores
  const gridEl = document.getElementById(`wz-stat-grid-${i}`);
  if (gridEl) gridEl.innerHTML = wzRenderStatGrid(i);

  // Recalcula HP, CA, Mana
  const calc = wzCalcSheet(char);
  if (calc) {
    const hp = document.getElementById(`wz-hp-${i}`);
    const ca = document.getElementById(`wz-ca-${i}`);
    const mn = document.getElementById(`wz-mana-${i}`);
    if (hp) hp.textContent = calc.hp;
    if (ca) ca.textContent = calc.ca;
    if (mn) mn.textContent = calc.mana;
  }
}


function wzOnStatChange(i, stat, val) {
  const char = wzChars[i];
  if (!char) return;
  const num = parseInt(val);
  // Modo livre: sem limites (qualquer inteiro positivo). Modo normal: 8-15 Point Buy.
  const clamped = char.freeMode
    ? (isNaN(num) ? 1 : Math.max(1, num))
    : Math.max(8, Math.min(15, isNaN(num) ? 8 : num));
  char.stats[stat] = clamped;
  // Em modo livre, reflete o clamped no input (garante pelo menos 1)
  if (char.freeMode) {
    const inp = document.getElementById(`wz-stat-${i}-${stat}`);
    if (inp && inp.tagName === 'INPUT' && parseInt(inp.value) !== clamped) inp.value = clamped;
  }
  // Atualiza modificador
  const modEl = document.getElementById(`wz-mod-${i}-${stat}`);
  if (modEl) modEl.textContent = wzStatMod(char.stats[stat]);
  if (!char.freeMode) wzRefreshPbDisplay(i);
  // Recalc derived stats
  const calc = wzCalcSheet(char);
  if (calc) {
    const hpEl = document.getElementById(`wz-hp-${i}`);
    const caEl = document.getElementById(`wz-ca-${i}`);
    const mnEl = document.getElementById(`wz-mn-${i}`);
    if (hpEl) hpEl.textContent = calc.hp;
    if (caEl) caEl.textContent = calc.ca;
    if (mnEl) mnEl.textContent = calc.mana;
  }
}

function wzOnClassChange(i, val) {
  wzChars[i].classe = val;
  // reset spell/feat state on class change
  wzChars[i]._selectedSpells   = [];
  wzChars[i]._selectedFeats    = [];
  wzChars[i]._spellResults     = [];
  wzChars[i]._classFeatures    = [];
  wzChars[i]._spellLevelFilter = null;
  wzChars[i]._spellsInitialized = false;  // força re-inicialização do kit ao re-renderizar
  // Casters abrem na aba de magias por padrão; outros na de habilidades
  wzChars[i]._habTab = CASTER_CLASSES_WZ.has(val) ? 'spells' : 'feats';
  wzOnStatChange(i, 'forca', wzChars[i].stats.forca);
  wzRefreshDndSection(i);
}

function wzOnFreeMode(i, checked) {
  wzChars[i].freeMode = checked;
  if (!checked) {
    // ao voltar para Point Buy, clampamos e resetamos bônus ASI
    STATS_WZ.forEach(stat => {
      wzChars[i].stats[stat] = Math.max(8, Math.min(15, wzChars[i].stats[stat] || 8));
    });
    wzChars[i]._asiBonus = {};
  }
  // O escopo da busca de magias muda com o modo livre — refaz se aba de magias ativa.
  wzChars[i]._spellResults     = [];
  wzChars[i]._spellLevelFilter = null;
  // Modo livre dá acesso a magias para qualquer classe; ajusta aba padrão
  if (checked) wzChars[i]._habTab = 'spells';
  else wzChars[i]._habTab = CASTER_CLASSES_WZ.has(wzChars[i].classe) ? 'spells' : 'feats';
  wzRefreshDndSection(i);
  if (wzChars[i]._habTab === 'spells') wzDoSpellSearch(i);
}

function wzApplyStdArray(i) {
  const vals = [15,14,13,12,10,8];
  wzChars[i]._asiBonus = {};
  STATS_WZ.forEach((stat, j) => {
    wzChars[i].stats[stat] = vals[j];
    wzOnStatChange(i, stat, vals[j]);
  });
  const gridEl = document.getElementById(`wz-stat-grid-${i}`);
  if (gridEl) gridEl.innerHTML = wzRenderStatGrid(i);
  wzRefreshPbDisplay(i);
}
// ── Stepper de atributo no modo Point Buy ─────────────────────────────────
// Incrementa ou decrementa 1 ponto. Respeita os limites 8–15 e o budget.
function wzStatStep(i, stat, delta) {
  const char = wzChars[i];
  if (!char || char.freeMode) return;
  const next = Math.max(8, Math.min(15, (char.stats[stat] || 8) + delta));
  char.stats[stat] = next;
  wzOnStatChange(i, stat, next);
  // Re-renderiza o grid para atualizar os botões disabled
  const gridEl = document.getElementById(`wz-stat-grid-${i}`);
  if (gridEl) gridEl.innerHTML = wzRenderStatGrid(i);
}

// ── Wizard: PB+ASI budget (espelha lógica do editor) ─────────────────────────
function wzInitAsiBonus(char) {
  if (char._asiBonus && Object.keys(char._asiBonus).length) return;
  char._asiBonus = {};
  for (const stat of STATS_WZ) {
    const val = parseInt(char.stats?.[stat]) || 8;
    char._asiBonus[stat] = Math.max(0, val - 15);
  }
}

function wzStatBudgetFull(i) {
  const char = wzChars[i];
  if (!char) return { pbBudget:27, pbUsed:0, asiTotal:0, asiUsed:0, pbRemain:27, asiRemain:0 };
  wzInitAsiBonus(char);
  const nivel    = Math.max(1, parseInt(char.nivel) || 1);
  const asiTotal = edAsiCount(nivel) * 2;
  const bonus    = char._asiBonus;
  let pbUsed = 0;
  for (const stat of STATS_WZ) {
    const val  = parseInt(char.stats[stat]) || 8;
    const base = Math.max(8, val - (bonus[stat] || 0));
    pbUsed += PB_COST[Math.min(base, 15)] ?? 9;
  }
  const asiUsed = Object.values(bonus).reduce((a, b) => a + b, 0);
  return { pbBudget: PB_BUDGET, pbUsed, asiTotal, asiUsed,
           pbRemain: PB_BUDGET - pbUsed, asiRemain: asiTotal - asiUsed };
}

function wzStatStepFull(i, stat, delta) {
  const char = wzChars[i];
  if (!char || char.freeMode) return;
  wzInitAsiBonus(char);
  const cur  = parseInt(char.stats[stat]) || 8;
  const next = cur + delta;
  if (next < 8 || next > 20) return;
  if (delta > 0) {
    const bud    = wzStatBudgetFull(i);
    const base   = Math.max(8, cur - (char._asiBonus[stat] || 0));
    const pbDelta = (PB_COST[Math.min(base+1,15)]??9) - (PB_COST[Math.min(base,15)]??9);
    const canUsePb = (char._asiBonus[stat]||0) === 0 && next <= 15 && bud.pbRemain >= pbDelta;
    if (canUsePb) { /* usa PB */ }
    else if (bud.asiRemain > 0) { char._asiBonus[stat] = (char._asiBonus[stat]||0) + 1; }
    else return;
  } else {
    if ((char._asiBonus[stat]||0) > 0) char._asiBonus[stat]--;
  }
  char.stats[stat] = next;
  wzOnStatChange(i, stat, next);
  const gridEl = document.getElementById(`wz-stat-grid-${i}`);
  if (gridEl) gridEl.innerHTML = wzRenderStatGrid(i);
  wzRefreshPbDisplay(i);
}

function wzRefreshPbDisplay(i) {
  const char = wzChars[i];
  if (!char || char.freeMode) return;
  const bud   = wzStatBudgetFull(i);
  const nivel = parseInt(char.nivel) || 1;
  const pbEl  = document.getElementById(`wz-pb-${i}`);
  const asiEl = document.getElementById(`wz-asi-${i}`);
  if (pbEl) {
    pbEl.textContent = `Point Buy: ${bud.pbUsed}/${bud.pbBudget}`;
    pbEl.style.color = bud.pbUsed > bud.pbBudget ? 'var(--red)' : 'var(--text-muted)';
  }
  if (asiEl) {
    asiEl.textContent = `ASI (Nv.${nivel}): ${bud.asiUsed}/${bud.asiTotal}`;
    asiEl.style.color = bud.asiRemain <= 0 ? 'var(--text-muted)' : 'var(--ink-user)';
  }
}

function wzOnLevelChange(i, val) {
  const char = wzChars[i];
  if (!char) return;
  char.nivel = Math.min(20, Math.max(1, parseInt(val) || 1));
  const profEl = document.getElementById(`wz-prof-${i}`);
  if (profEl) profEl.textContent = `+${edProfForLevel(char.nivel)}`;
  wzRefreshPbDisplay(i);
  const gridEl = document.getElementById(`wz-stat-grid-${i}`);
  if (gridEl) gridEl.innerHTML = wzRenderStatGrid(i);
  // recalc derived stats
  wzOnStatChange(i, 'forca', char.stats.forca);
  // O nível de magia e as habilidades de classe mudam com o nível — refaz.
  char._spellResults  = [];
  char._classFeatures = [];   // recarrega habilidades pelo novo nível
  if (char._habTab === 'spells') {
    wzDoSpellSearch(i);
  } else if (char._habTab === 'feats') {
    char._featLoading = true;
    wzRefreshFeatPanel(i);    // mostra "A carregar..." imediatamente
    wzLoadClassFeatures(i);
  }
}

function wzRefreshDndSection(i) {
  const el = document.getElementById(`wz-dnd-${i}`);
  if (el) el.innerHTML = wzBuildDndSectionHtml(i);
}
// Troca de aba e auto-carrega conteúdo se ainda não foi carregado
function wzSetHabTab(i, tab) {
  const char = wzChars[i];
  if (!char) return;
  char._habTab = tab;
  if (tab === 'feats' && !char._classFeatures?.length && !char._featLoading) {
    char._featLoading = true;
    wzLoadClassFeatures(i);   // async; wzRefreshFeatPanel será chamado quando terminar
  }
  if (tab === 'spells' && !char._spellResults?.length && !char._spellLoading) {
    wzDoSpellSearch(i);       // async; wzRefreshSpellPanel será chamado quando terminar
  }
  wzRefreshDndSection(i);
}

// ── Wizard: class feature search ──────────────────────────────────────────────
async function wzLoadClassFeatures(i) {
  const char = wzChars[i];
  if (!char) return;
  char._featLoading = true;
  wzRefreshFeatPanel(i);
  try {
    const url = `${API}/api/dnd/class-features?class=${encodeURIComponent(char.classe||'guerreiro')}&level=${char.nivel||1}`;
    const res  = await authFetch(url);
    const data = await res.json();
    char._classFeatures = data.features || [];
  } catch { char._classFeatures = []; }
  char._featLoading = false;
  wzRefreshFeatPanel(i);
}
function wzRefreshFeatPanel(i) {
  const el = document.getElementById(`wz-feat-panel-${i}`);
  if (el) el.innerHTML = wzBuildFeatPanel(i);
}
function wzBuildFeatPanel(i) {
  const char = wzChars[i];
  if (!char) return '';
  if (char._featLoading) return '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">A carregar habilidades de classe...</div>';
  const feats    = char._classFeatures || [];
  const selected = char._selectedFeats || [];
  const listHtml = feats.length === 0
    ? `<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">Nenhuma habilidade encontrada para ${escHtml(char.classe||'esta classe')} nível ${char.nivel||1}.</div>`
    : feats.map(feat => {
        const has    = selected.some(f => f.nome.toLowerCase() === feat.nome.toLowerCase());
        const regIdx = _habInfoRegistry.length;
        _habInfoRegistry.push(has ? null : () => { wzAddClassFeature(i, feat); document.getElementById('hab-info-popup')?.remove(); });
        const featJson = JSON.stringify(feat).replace(/"/g,'&quot;');
        return `<div class="ed-search-result ${has?'ed-search-result-added':''}" onclick="showHabInfo(event,${featJson},${regIdx})" style="cursor:pointer;">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span class="ed-spell-badge" style="min-width:28px;text-align:center;">Nv.${feat.nivel}</span>
            <strong style="font-size:13px;">${escHtml(feat.nome)}</strong>
            ${has?`<span style="font-size:10px;color:var(--green);">✓</span>`:''}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">${escHtml((feat.descricao||'').slice(0,120))}${(feat.descricao||'').length>120?'…':''}</div>
        </div>`;
      }).join('');
  return `
    <div>
      <div style="font-size:11px;color:var(--ink-user);margin-bottom:8px;">
        Habilidades de <strong>${escHtml(char.classe||'')}</strong> disponíveis até nível ${char.nivel||1}
      </div>
      <div class="ed-search-results-list" style="max-height:300px;">${listHtml}</div>
      ${selected.length ? `<div style="font-size:11px;color:var(--text-muted);margin-top:10px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
        <strong>Selecionadas (${selected.length}):</strong>
        ${selected.map(f => {
          const safe = f.nome.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
          return `<span class="ed-spell-badge" style="display:inline-flex;align-items:center;gap:3px;">${escHtml(f.nome)}<button onclick="wzRemoveFeat(${i},'${safe}')" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:11px;padding:0;line-height:1;">✕</button></span>`;
        }).join('')}
      </div>` : ''}
    </div>`;
}
function wzAddClassFeature(i, feat) {
  const char = wzChars[i];
  if (!char) return;
  char._selectedFeats = char._selectedFeats || [];
  if (!char._selectedFeats.some(f => f.nome.toLowerCase() === feat.nome.toLowerCase()))
    char._selectedFeats.push(feat);
  wzRefreshFeatPanel(i);   // atualiza a lista dentro do painel (chips de selecionadas)
  // Atualiza o contador na aba sem re-renderizar o painel inteiro
  const tabEl = document.getElementById(`wz-hab-tab-feats-${i}`);
  if (tabEl) tabEl.textContent = `📜 Habilidades (${char._selectedFeats.length})`;
}
function wzRemoveFeat(i, nome) {
  const char = wzChars[i];
  if (!char) return;
  char._selectedFeats = (char._selectedFeats||[]).filter(f => f.nome !== nome);
  wzRefreshFeatPanel(i);
  const tabEl = document.getElementById(`wz-hab-tab-feats-${i}`);
  if (tabEl) tabEl.textContent = char._selectedFeats.length
    ? `📜 Habilidades (${char._selectedFeats.length})` : '📜 Habilidades';
}

// ── Wizard: seção D&D completa (refrescável parcialmente) ────────────────────
function wzBuildDndSectionHtml(i) {
  const isDnd = document.getElementById('wz-type').value === 'dnd';
  const char  = wzChars[i];
  if (!isDnd || !char) return '';
  const nivel  = Math.max(1, parseInt(char.nivel) || 1);
  const calc   = wzCalcSheet(char);
  const bud    = char.freeMode ? null : wzStatBudgetFull(i);
  const asiCnt = edAsiCount(nivel);

  const basicHtml = `
    <div class="cwc-row2">
      <div><span class="cwc-label">Classe</span>
        <select onchange="wzOnClassChange(${i},this.value)">
          ${Object.entries(CLASS_DATA_WZ).map(([k,v])=>`<option value="${k}" ${char.classe===k?'selected':''}>${v.label}</option>`).join('')}
        </select>
      </div>
      <div><span class="cwc-label">Raça</span>
        <select onchange="wzOnRaceChange(${i},this.value)">
          ${['humano','elfo','anão','halfling','draconato','gnomo','meio-elfo','meio-orc','tiferino'].map(r => {
            const bon = RACE_BONUSES_WZ[r] || {};
            const str = Object.entries(bon).map(([k,v])=>`${k.slice(0,3).toUpperCase()} +${v}`).join(', ');
            return `<option value="${r}" ${char.raca===r?'selected':''}>${r.charAt(0).toUpperCase()+r.slice(1)}${str?` (${str})`:''}</option>`;
          }).join('')}
        </select>
      </div>
    </div>
    <div><span class="cwc-label">Antecedente <span style="color:var(--text-muted);font-size:9px;">(opcional)</span></span>
      <select onchange="wzOnBackgroundChange(${i},this.value)">
        <option value="" ${!char.background?'selected':''}>— Nenhum —</option>
        ${Object.keys(BACKGROUND_LIST_WZ).map(b=>`<option value="${b}" ${char.background===b?'selected':''}>${b.charAt(0).toUpperCase()+b.slice(1)}</option>`).join('')}
      </select>
      ${char.background?`<div style="font-family:monospace;font-size:9px;color:var(--text-muted);margin-top:4px;">${wzBgInfo(char.background)}</div>`:''}
    </div>
    <div class="cwc-row2">
      <div><span class="cwc-label">Nível Inicial</span>
        <input type="number" min="1" max="20" value="${nivel}"
          onchange="wzOnLevelChange(${i},this.value)"
          style="font-size:20px;font-weight:700;text-align:center;">
      </div>
      <div><span class="cwc-label">Bônus de Proficiência</span>
        <div id="wz-prof-${i}" style="font-size:22px;font-weight:700;color:var(--ink-user);padding:4px 0;">
          +${edProfForLevel(nivel)}
        </div>
      </div>
    </div>`;

  const budgetRow = char.freeMode ? '' : `
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;font-size:12px;">
      <div style="padding:6px 10px;border-radius:4px;background:rgba(0,0,0,0.03);">
        <span id="wz-pb-${i}" style="color:var(--text-muted);">Point Buy: ${bud.pbUsed}/${bud.pbBudget}</span>
        <span style="color:var(--text-dim);"> · min 8, max 15</span>
      </div>
      ${bud.asiTotal > 0 ? `<div style="padding:6px 10px;border-radius:4px;background:rgba(38,75,130,0.06);">
        <span id="wz-asi-${i}" style="color:${bud.asiRemain<=0?'var(--text-muted)':'var(--ink-user)'};">ASI (Nv.${nivel}): ${bud.asiUsed}/${bud.asiTotal}</span>
        <span style="color:var(--text-dim);"> · ${asiCnt} ASI${asiCnt!==1?'s':''} · qualquer atributo, até 20</span>
      </div>` : ''}
    </div>`;

  const statsHtml = `
    <div>
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
        <span class="cwc-label" style="margin:0;">Atributos</span>
        <div style="display:flex;gap:6px;align-items:center;">
          <button onclick="wzApplyStdArray(${i})" style="background:none;border:1px solid var(--page-edge);border-radius:3px;color:var(--text-muted);font-size:9px;padding:3px 8px;cursor:pointer;letter-spacing:0.06em;">ARRAY PADRÃO</button>
          <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:10px;color:var(--text-muted);">
            <input type="checkbox" ${char.freeMode?'checked':''} onchange="wzOnFreeMode(${i},this.checked)">
            Modo Livre
          </label>
        </div>
      </div>
      ${budgetRow}
      <div class="stat-grid" id="wz-stat-grid-${i}">${wzRenderStatGrid(i)}</div>
    </div>
    ${calc ? `
    <div class="dnd-calc-row">
      <div class="dnd-calc-item">❤️ HP <span id="wz-hp-${i}">${calc.hp}</span></div>
      <div class="dnd-calc-item">🛡️ CA <span id="wz-ca-${i}">${calc.ca}</span></div>
      ${calc.mana > 0 ? `<div class="dnd-calc-item">✨ Mana <span id="wz-mn-${i}">${calc.mana}</span></div>` : ''}
      <div class="dnd-calc-item">d${calc.hit_die} hit die · Prof +${edProfForLevel(nivel)}</div>
    </div>` : ''}`;

  // ── Habilidades & Magias (interface com abas) ──────────────────────────────
  const isCaster   = CASTER_CLASSES_WZ.has(char.classe);

  // Pré-popula _selectedSpells com o kit inicial na primeira renderização.
  // Infere nivel_magia (ausente em INITIAL_SPELLS_WZ) a partir do custo_mana:
  //   0 mana → truque (nivel 0) | 4 mana → nivel 1 | 8 → 2 | 12 → 3 …
  if (isCaster && !char._spellsInitialized) {
    char._selectedSpells = (INITIAL_SPELLS_WZ[char.classe] || []).map(s => ({
      ...s,
      nivel_magia: s.nivel_magia ?? (s.custo_mana === 0 ? 0 : Math.max(1, Math.round((s.custo_mana || 4) / 4))),
    }));
    char._spellsInitialized = true;
  }

  const selFeats   = char._selectedFeats  || [];
  const selSpells  = char._selectedSpells || [];
  const showFeatTab  = !char.freeMode;                  // habilidades de classe (Open5e)
  const showSpellTab = char.freeMode || isCaster;       // magias (qualquer classe em modo livre)

  let habHtml = '';
  if (showFeatTab || showSpellTab) {
    // Aba ativa — garante valor válido
    let habTab = char._habTab || 'feats';
    if (habTab === 'feats'  && !showFeatTab)  habTab = 'spells';
    if (habTab === 'spells' && !showSpellTab) habTab = 'feats';

    // Auto-carrega o conteúdo da aba ativa na primeira renderização
    if (habTab === 'feats' && showFeatTab && !char._classFeatures?.length && !char._featLoading) {
      char._featLoading = true;
      setTimeout(() => wzLoadClassFeatures(i), 20);
    }
    if (habTab === 'spells' && showSpellTab && !char._spellResults?.length && !char._spellLoading) {
      char._spellLoading = true;
      setTimeout(() => wzDoSpellSearch(i), 20);
    }

    // ── Estilo das abas ────────────────────────────────────────────────────
    const tabStyle = (active) =>
      `padding:7px 16px;border:none;border-bottom:2px solid ${active?'var(--ink-user)':'transparent'};`+
      `background:none;cursor:pointer;font-family:'Lora',serif;font-size:12px;margin-bottom:-1px;`+
      `color:${active?'var(--ink-user)':'var(--text-muted)'};font-weight:${active?'700':'400'};`+
      `transition:color 0.15s,border-color 0.15s;`;

    const featLabel  = selFeats.length  ? `📜 Habilidades (${selFeats.length})`  : '📜 Habilidades';
    const spellLabel = selSpells.length ? `✨ Magias (${selSpells.length})` : '✨ Magias';

    const tabBar = `<div style="display:flex;border-bottom:1px solid var(--page-edge);margin-bottom:12px;">
      ${showFeatTab  ? `<button id="wz-hab-tab-feats-${i}"  style="${tabStyle(habTab==='feats')}"  onclick="wzSetHabTab(${i},'feats')">${featLabel}</button>`  : ''}
      ${showSpellTab ? `<button id="wz-hab-tab-spells-${i}" style="${tabStyle(habTab==='spells')}" onclick="wzSetHabTab(${i},'spells')">${spellLabel}</button>` : ''}
    </div>`;

    // ── Conteúdo da aba ativa ──────────────────────────────────────────────
    let tabContent = '';
    if (habTab === 'feats' && showFeatTab) {
      tabContent = `<div id="wz-feat-panel-${i}">${wzBuildFeatPanel(i)}</div>`;
    } else if (habTab === 'spells' && showSpellTab) {
      tabContent = `<div id="wz-spell-panel-${i}">${wzBuildSpellPanel(i)}</div>`;
    }

    // Dica quando nada foi selecionado ainda
    const emptyHint = (!selFeats.length && !selSpells.length)
      ? `<div style="font-size:11px;color:var(--text-dim);font-style:italic;margin-top:10px;">
           Nenhuma selecionada — o kit inicial da classe será aplicado automaticamente.
         </div>`
      : '';

    habHtml = `
      <div style="border-top:1px solid var(--page-edge);padding-top:14px;margin-top:6px;">
        <span class="cwc-label" style="margin-bottom:10px;">✨ Habilidades & Magias</span>
        ${tabBar}
        ${tabContent}
        ${emptyHint}
      </div>`;
  }

  const equipHtml = `<div id="wz-equip-choices-${i}">${wzRenderEquipChoices(i)}</div>`;

  return basicHtml + statsHtml + equipHtml + habHtml;
}

// ── Renderiza o grid de atributos de um personagem ────────────────────────
// Modo normal: stepper −/+ com PB+ASI. Modo livre: input numérico sem limites.
function wzRenderStatGrid(i) {
  const char = wzChars[i];
  if (!char) return '';
  return STATS_WZ.map(stat => {
    const val  = char.stats[stat] || 8;
    const mod  = wzStatMod(val);
    const name = STAT_ABBR[stat] || stat.slice(0,3).toUpperCase();
    if (char.freeMode) {
      return `<div class="stat-cell">
        <span class="stat-cell-name">${name}</span>
        <input type="number" id="wz-stat-${i}-${stat}" value="${val}" min="1"
          oninput="wzOnStatChange(${i},'${stat}',this.value)">
        <span class="stat-cell-mod" id="wz-mod-${i}-${stat}">${mod}</span>
      </div>`;
    } else {
      wzInitAsiBonus(char);
      const bud      = wzStatBudgetFull(i);
      const asiBonus = char._asiBonus?.[stat] || 0;
      const base     = Math.max(8, val - asiBonus);
      const pbDelta  = (PB_COST[Math.min(base+1,15)]??9) - (PB_COST[Math.min(base,15)]??9);
      const canUsePb = asiBonus === 0 && val < 15 && bud.pbRemain >= pbDelta;
      const atMin    = val <= 8;
      const canUp    = val >= 20 ? false : canUsePb ? true : bud.asiRemain > 0;
      return `<div class="stat-cell">
        <span class="stat-cell-name">${name}</span>
        <div class="stat-stepper">
          <button class="stat-btn" onclick="wzStatStepFull(${i},'${stat}',-1)" ${atMin?'disabled':''}>−</button>
          <span class="stat-val" id="wz-stat-${i}-${stat}">${val}</span>
          <button class="stat-btn" onclick="wzStatStepFull(${i},'${stat}',+1)" ${canUp?'':'disabled'}>+</button>
        </div>
        <span class="stat-cell-mod" id="wz-mod-${i}-${stat}">${mod}</span>
      </div>`;
    }
  }).join('');
}




// ── Campos específicos por tema narrativo ────────────────────────────────
const THEME_CHAR_FIELDS = {
  fantasia: {
    icon: '⚔️', label: 'Fantasia — Arquétipo & Poderes',
    color: 'rgba(200,168,75,0.08)', border: 'rgba(200,168,75,0.22)',
    primary: 'arquetipo',
    fields: [
      {id:'arquetipo', label:'Arquétipo Heroico', type:'select', options:['Guerreiro','Mago','Ladino','Arqueiro','Curandeiro','Bardo','Patrulheiro','Nobre','Paladino','Druida','Outro']},
      {id:'raca', label:'Raça / Origem', type:'select', options:['Humano','Elfo','Anão','Halfling','Draconato','Gnomo','Meio-Elfo','Meio-Orc','Tiferino','Outra']},
      {id:'habilidade', label:'Habilidade Especial', type:'text', hint:'Ex: Invocar tempestades, Falar com animais'},
      {id:'vinculo', label:'Vínculo com o Grupo', type:'textarea', hint:'Como e por que se juntou ao grupo?'},
    ],
  },
  romance: {
    icon: '💌', label: 'Romance — Emoções & Segredos',
    color: 'rgba(200,80,120,0.08)', border: 'rgba(200,80,120,0.22)',
    primary: 'papel',
    fields: [
      {id:'papel', label:'Papel na Dinâmica', type:'select', options:['Protagonista','Interesse Romântico','Melhor Amigo/a','Rival Amoroso','Ex-parceiro/a','Mentor/a','Obstáculo','Apoio Emocional']},
      {id:'estado_emocional', label:'Estado Emocional Atual', type:'select', options:['Apaixonado','Magoado','Esperançoso','Desconfiado','Indiferente','Ciumento','Confuso','Resignado','Reprimido']},
      {id:'segredo', label:'Segredo Guardado', type:'text', hint:'O que esconde, e de quem?'},
      {id:'desejo', label:'Desejo Não Confessado', type:'text', hint:'O que quer mas não admite nem a si mesmo?'},
      {id:'historico', label:'Histórico Afetivo', type:'textarea', hint:'Relacionamentos passados que ainda ecoam. Traumas amorosos.'},
    ],
  },
  horror: {
    icon: '🕯️', label: 'Horror — Psique & Sobrevivência',
    color: 'rgba(180,40,40,0.08)', border: 'rgba(180,40,40,0.25)',
    primary: 'tipo',
    fields: [
      {id:'tipo', label:'Papel na História', type:'select', options:['Sobrevivente','Investigador','Cético','Crente','Vítima Designada','Entidade','Protetor','Sacrifício']},
      {id:'sanidade', label:'Sanidade Atual (0–10)', type:'number', min:0, max:10, hint:'10 = íntegro · 0 = completamente partido'},
      {id:'medo', label:'Maior Medo Específico', type:'text', hint:'Ex: O que vive dentro dos espelhos. Ser esquecido por todos.'},
      {id:'trauma', label:'Trauma Anterior', type:'textarea', hint:'O que o quebrou antes desta história começar?'},
      {id:'ancora', label:'Âncora de Sanidade', type:'text', hint:'O que ainda o mantém conectado à realidade?'},
    ],
  },
  misterio: {
    icon: '🔍', label: 'Mistério — Posição & Informações',
    color: 'rgba(60,120,180,0.08)', border: 'rgba(60,120,180,0.22)',
    primary: 'papel',
    fields: [
      {id:'papel', label:'Papel na Investigação', type:'select', options:['Detetive','Suspeito Principal','Suspeito Secundário','Testemunha Chave','Informante','Vítima','Cúmplice','Inocente Inconveniente']},
      {id:'alibi', label:'Álibi Declarado', type:'text', hint:'Onde afirma estar no momento do crime?'},
      {id:'motivo', label:'Motivo Oculto', type:'text', hint:'O que tem a ganhar — ou perder — com o desfecho?'},
      {id:'sabe_mas_cala', label:'Informação Ocultada', type:'textarea', hint:'O que sabe mas não revelou ainda, e por quê?'},
    ],
  },
  scifi: {
    icon: '🚀', label: 'Sci-Fi — Especialidade & Facção',
    color: 'rgba(40,140,200,0.08)', border: 'rgba(40,140,200,0.22)',
    primary: 'especialidade',
    fields: [
      {id:'especialidade', label:'Especialidade', type:'select', options:['Hacker','Soldado','Piloto','Engenheiro','Médico de Campo','Político','Mercenário','Agente Infiltrado','IA Sintética','Contrabandista','Cientista']},
      {id:'faccao', label:'Facção / Corporação', type:'text', hint:'A quem serve — ou a quem deveria servir?'},
      {id:'implantes', label:'Implantes & Modificações', type:'text', hint:'Ex: Olho cibernético grau 3, exoesqueleto neural parcial'},
      {id:'creditos', label:'Créditos Iniciais', type:'number', min:0, hint:'Recursos financeiros disponíveis'},
      {id:'segredo_tecno', label:'Segredo Tecnológico', type:'textarea', hint:'Acesso ilegal, identidade falsa, experimento não registrado?'},
    ],
  },
  faroeste: {
    icon: '🤠', label: 'Faroeste — Reputação & Lei',
    color: 'rgba(160,100,40,0.08)', border: 'rgba(160,100,40,0.25)',
    primary: 'arquetipo',
    fields: [
      {id:'arquetipo', label:'Arquétipo', type:'select', options:['Pistoleiro','Xerife','Foragido','Pistoleiro de Aluguel','Comerciante','Curandeiro','Pastor','Nativo','Estrangeiro','Mineiro','Ladrão de Bancos']},
      {id:'lado_lei', label:'Relação com a Lei', type:'select', options:['Dentro da lei','Fora da lei — com recompensa pública','Fora da lei — identidade desconhecida','Agente secreto','Neutro / acima da lei']},
      {id:'reputacao', label:'Reputação na Região', type:'text', hint:'O que dizem quando o nome é mencionado no saloon?'},
      {id:'recompensa', label:'Valor da Recompensa ($)', type:'number', min:0, hint:'0 se não é procurado'},
      {id:'codigo', label:'Linha que Não Cruza', type:'text', hint:'O que nunca faria, mesmo pela sobrevivência?'},
    ],
  },
};

function wzExtraBadge(char, theme) {
  const cfg = THEME_CHAR_FIELDS[theme];
  if (!cfg || !char.extras) return '';
  const val = char.extras[cfg.primary];
  if (!val) return '';
  return `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;background:${cfg.color};border:1px solid ${cfg.border};border-radius:3px;padding:2px 6px;color:var(--text-dim);">${val}</span>`;
}

function wzRenderThemeExtras(i, theme, char) {
  const cfg = THEME_CHAR_FIELDS[theme];
  if (!cfg) return '';
  const extras = char.extras || {};

  let html = `<div style="border-top:1px solid var(--border);margin-top:4px;padding-top:14px;">
    <div style="font-family:'Cinzel',serif;font-size:10px;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:14px;display:flex;align-items:center;gap:6px;">
      <span>${cfg.icon}</span>
      <span style="color:var(--gold-dim);">${cfg.label}</span>
    </div>`;

  cfg.fields.forEach(f => {
    const val = extras[f.id];
    const onChange = `wzChars[${i}].extras=wzChars[${i}].extras||{};wzChars[${i}].extras['${f.id}']=this.${f.type === 'number' ? 'valueAsNumber||0' : 'value'}`;
    html += `<div style="margin-bottom:10px;"><span class="cwc-label">${f.label}</span>`;

    if (f.type === 'select') {
      html += `<select onchange="${onChange}">`;
      f.options.forEach(opt => {
        html += `<option${val === opt || (!val && f.options[0] === opt) ? ' selected' : ''}>${escHtml(opt)}</option>`;
      });
      html += `</select>`;
    } else if (f.type === 'textarea') {
      html += `<textarea rows="2" placeholder="${escHtml(f.hint||'')}" onchange="${onChange}">${escHtml(val||'')}</textarea>`;
    } else if (f.type === 'number') {
      html += `<input type="number" min="${f.min||0}"${f.max!==undefined?` max="${f.max}"`:''}
        value="${val !== undefined ? val : (f.min||0)}"
        placeholder="${escHtml(f.hint||'')}" onchange="${onChange}">`;
    } else {
      html += `<input type="text" value="${escHtml(val||'')}" placeholder="${escHtml(f.hint||'')}" onchange="${onChange}">`;
    }
    html += `</div>`;
  });

  html += `</div>`;
  return html;
}

function wzRenderChars() {
  const isDnd   = document.getElementById('wz-type').value === 'dnd';
  const list    = document.getElementById('wz-chars-list');
  const empty   = document.getElementById('wz-chars-empty');
  empty.classList.toggle('hidden', wzChars.length > 0);

  list.innerHTML = wzChars.map((char, i) => {
    const open = char._open !== false;
    return `
    <div class="cwc" id="cwc-${i}">
      <div class="cwc-header" onclick="toggleWzChar(${i})">
        <div style="display:flex;align-items:center;gap:10px;">
          <span id="cwc-arrow-${i}" style="color:var(--gold-dim);font-size:12px;">${open?'▾':'▸'}</span>
          <span style="font-family:'Cinzel',serif;font-size:13px;color:var(--text);">
            ${char.name || `Personagem ${i+1}`}
          </span>
          ${char.isParty ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;background:rgba(200,168,75,0.15);border:1px solid var(--gold-dim);border-radius:3px;padding:2px 6px;color:var(--gold-dim);">GRUPO</span>` : ''}
          ${isDnd && char.classe ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--text-muted);">${CLASS_DATA_WZ[char.classe]?.label||''}${char.nivel>1?` Nv.${char.nivel}`:''}</span>` : wzExtraBadge(char, document.getElementById('wz-type').value)}
        </div>
        <button onclick="event.stopPropagation();removeWzChar(${i})" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;padding:2px 6px;">✕</button>
      </div>
      <div class="cwc-body ${open?'':'hidden'}" id="cwc-body-${i}">
        <div class="cwc-row2">
          <div>
            <span class="cwc-label">Nome *</span>
            <input value="${escHtml(char.name)}" onchange="wzChars[${i}].name=this.value;document.querySelector('#cwc-${i} .cwc-header span:nth-child(2)').textContent=this.value||'Personagem ${i+1}'" placeholder="Nome do personagem">
          </div>
          <div>
            <span class="cwc-label">Status</span>
            <select onchange="wzChars[${i}].status=this.value">
              ${['vivo','morto','desaparecido','preso','inconsciente','inimigo'].map(s =>`<option ${char.status===s?'selected':''}>${s}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="cwc-row2">
          <div>
            <span class="cwc-label">Papel / Função no Grupo</span>
            <input value="${escHtml(char.role)}" onchange="wzChars[${i}].role=this.value" placeholder="Ex: Guerreira, Aliada, Rival...">
          </div>
          <div style="display:flex;align-items:center;gap:8px;padding-top:20px;">
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;color:var(--text-dim);">
              <input type="checkbox" ${char.isParty?'checked':''} onchange="wzChars[${i}].isParty=this.checked" style="accent-color:var(--gold);">
              Membro do Grupo (party)
            </label>
          </div>
        </div>
        <div>
          <span class="cwc-label">Descrição</span>
          <textarea rows="2" onchange="wzChars[${i}].description=this.value" placeholder="Aparência física, voz, forma de se vestir...">${escHtml(char.description)}</textarea>
        </div>
        <div>
          <span class="cwc-label">Traços de Personalidade</span>
          <textarea rows="2" onchange="wzChars[${i}].traits=this.value" placeholder="Motivações, medos, maneirismo...">${escHtml(char.traits)}</textarea>
        </div>
        <div>
          <span class="cwc-label">Notas</span>
          <textarea rows="2" onchange="wzChars[${i}].notes=this.value" placeholder="Informações adicionais, objetivos secretos...">${escHtml(char.notes)}</textarea>
        </div>
        ${wzRenderThemeExtras(i, document.getElementById('wz-type').value, char)}
        <div id="wz-dnd-${i}">${wzBuildDndSectionHtml(i)}</div>
      </div>
    </div>`;
  }).join('');
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Tabelas de limites de magias D&D 5e ──────────────────────────────────────
const SPELL_CANTRIPS_TABLE = {
  bardo:[2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,4,4,4,4,4],
  clérigo:[3,3,3,4,4,4,4,4,4,5,5,5,5,5,5,5,5,5,5,5],
  druida:[2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,4,4,4,4,4],
  feiticeiro:[4,4,4,5,5,5,6,6,6,6,6,6,6,6,6,6,6,6,6,6],
  bruxo:[2,2,2,3,3,3,4,4,4,4,4,4,4,4,4,4,4,4,4,4],
  mago:[3,3,3,4,4,4,4,4,4,5,5,5,5,5,5,5,5,5,5,5],
};
const SPELL_KNOWN_TABLE = {
  // Mago — Livro de Magias: 6 no nível 1, +2 por nível
  mago:       [6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44],
  // Clérigo / Druida — preparados: SAB 14 (+2) + nível (representativo de build típica)
  clérigo:    [3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22],
  druida:     [3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22],
  // Paladino — half-caster: sem magias no nível 1, CAR 14 (+2) + metade do nível
  paladino:   [0,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12],
  // Magias conhecidas fixas
  bardo:      [4,5,6,7,8,9,10,11,12,14,15,15,16,18,19,19,20,22,22,22],
  feiticeiro: [2,3,4,5,6,7,8,9,10,11,12,12,13,13,14,14,15,15,15,15],
  bruxo:      [2,3,4,5,6,7,8,9,10,10,11,11,12,12,13,13,14,14,14,15],
  patrulheiro:[0,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11],
};
function getSpellLimit(classe, nivel, sheet) {
  const nv=Math.min(Math.max(parseInt(nivel)||1,1),20), idx=nv-1;
  const maxCantrips = SPELL_CANTRIPS_TABLE[classe]?.[idx] ?? 0;
  if (SPELL_KNOWN_TABLE[classe]===undefined) return null;
  const maxSpells = SPELL_KNOWN_TABLE[classe][idx] ?? 0;
  return {maxCantrips, maxSpells};
}

// ── Popup de detalhes de magia / habilidade ───────────────────────────────────
// Registry: cada row registra seu callback de "Adicionar" aqui.
// O popup lê pelo índice para evitar serializar closures em atributos HTML.
const _habInfoRegistry = [];

function showHabInfo(event, sp, regIdx, alreadyHas, limitReached) {
  event.stopPropagation();
  document.getElementById('hab-info-popup')?.remove();

  const addFn = (typeof regIdx === 'number') ? _habInfoRegistry[regIdx] : null;
  if (alreadyHas === undefined) alreadyHas = !addFn;
  if (limitReached === undefined) limitReached = false;

  const nivel = sp.nivel_magia === 0 ? 'Cantrip'
              : sp.nivel_magia > 0   ? `Nível ${sp.nivel_magia}`
              : sp.nivel > 0         ? `Nível ${sp.nivel}` : '';

  const popup = document.createElement('div');
  popup.id = 'hab-info-popup';

  // Posicionamento próximo ao clique mas dentro do viewport
  let left = event.clientX + 10;
  let top  = event.clientY + 10;
  if (left + 348 > window.innerWidth)   left = event.clientX - 358;
  if (top  + 340 > window.innerHeight)  top  = event.clientY - 350;
  left = Math.max(8, left);
  top  = Math.max(8, top);

  popup.style.cssText =
    `position:fixed;z-index:10000;left:${left}px;top:${top}px;` +
    `background:var(--page-bg,#fff);border:1px solid var(--page-edge,#ccc);border-radius:10px;` +
    `box-shadow:0 12px 40px rgba(0,0,0,0.22);padding:18px;` +
    `max-width:340px;width:min(340px,calc(100vw - 16px));font-family:'Lora',serif;`;

  const badges = [
    nivel       ? `<span style="font-size:11px;background:rgba(38,75,130,0.1);color:var(--ink-user);padding:2px 8px;border-radius:10px;">${escHtml(nivel)}</span>` : '',
    sp.escola   ? `<span style="font-size:11px;color:var(--text-muted);">${escHtml(sp.escola)}</span>` : '',
    sp.ritual   ? `<span style="font-size:10px;border:1px solid var(--page-edge);border-radius:3px;padding:1px 5px;color:var(--text-muted);">ritual</span>` : '',
    sp.concentracao ? `<span style="font-size:10px;border:1px solid var(--page-edge);border-radius:3px;padding:1px 5px;color:var(--text-muted);">conc.</span>` : '',
  ].filter(Boolean).join(' ');

  popup.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:15px;font-weight:700;color:var(--text-main);margin-bottom:5px;">${escHtml(sp.nome||'')}</div>
        <div style="display:flex;flex-wrap:wrap;gap:5px;align-items:center;">${badges}</div>
      </div>
      <button onclick="document.getElementById('hab-info-popup').remove()"
        style="background:none;border:none;cursor:pointer;font-size:18px;color:var(--text-muted);padding:0 0 0 10px;line-height:1;flex-shrink:0;">✕</button>
    </div>
    ${(sp.dado || sp.custo_mana > 0) ? `
    <div style="display:flex;gap:20px;margin-bottom:10px;padding:8px 10px;background:rgba(0,0,0,0.03);border-radius:6px;">
      ${sp.dado       ? `<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-muted);margin-bottom:2px;">Dado</div><div style="font-family:monospace;font-size:16px;font-weight:700;">${escHtml(sp.dado)}</div></div>` : ''}
      ${sp.custo_mana > 0 ? `<div><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--text-muted);margin-bottom:2px;">Mana</div><div style="font-size:16px;font-weight:700;color:var(--ink-user);">${sp.custo_mana}</div></div>` : ''}
    </div>` : ''}
    ${sp.descricao ? `<div style="font-size:12px;line-height:1.65;color:var(--text-dim);max-height:160px;overflow-y:auto;border-top:1px solid var(--page-edge);padding-top:8px;margin-bottom:14px;">${escHtml(sp.descricao)}</div>` : ''}
    ${alreadyHas
      ? `<div style="text-align:center;font-size:12px;color:var(--green,#2d8a4e);padding:6px 0;">✓ Já adicionada</div>`
      : limitReached
        ? `<div style="text-align:center;font-size:12px;color:var(--ink-sys,#8b3a3a);padding:6px 0;">⚠️ Limite de cantrips/magias atingido (use a aba de habilidades)</div>`
        : `<button onclick="_habInfoRegistry[${regIdx}]()"
             style="width:100%;padding:9px;background:var(--ink-user,#264b82);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-family:'Lora',serif;font-weight:600;letter-spacing:0.02em;">
             + Adicionar
           </button>`
    }`;

  document.body.appendChild(popup);

  // Fecha ao clicar fora
  setTimeout(() => {
    function outsideClick(e) {
      if (!popup.contains(e.target)) {
        popup.remove();
        document.removeEventListener('click', outsideClick);
      }
    }
    document.addEventListener('click', outsideClick);
  }, 50);
}

// ── Montar payload e criar campanha ────────────────────────
async function createCampaignFromWizard() {
  if (!wzValidateStep1()) { document.getElementById('wz-err').textContent = 'Verifique o nome da campanha.'; return; }

  const name         = document.getElementById('wz-name').value.trim();
  const campaign_type = document.getElementById('wz-type').value;
  const isDnd        = campaign_type === 'dnd';

  // Monta characters dict e party array
  const characters = {};
  const party      = [];

  for (const char of wzChars) {
    if (!char.name.trim()) continue;
    const key = char.name.toLowerCase().trim().replace(/_/g, ' ');

    const charObj = {
      name:        char.name,
      description: char.description,
      traits:      char.traits,
      status:      char.status || 'vivo',
      notes:       char.notes,
      sheet:       null,
      inventario:  [],
      habilidades: [],
    };

    // Processa campos específicos do tema e mescla nos campos padrão
    const ext = char.extras || {};
    const theme = campaign_type;
    if (theme !== 'dnd') {
      // role: usa o campo primário do tema (arquetipo, papel, especialidade, tipo)
      const THEME_PRIMARY = {fantasia:'arquetipo',romance:'papel',horror:'tipo',misterio:'papel',scifi:'especialidade',faroeste:'arquetipo'};
      const primary = ext[THEME_PRIMARY[theme]];
      if (primary && !charObj.role) charObj.role = primary;

      // traits: prepende dados psicológicos/estado do tema
      const traitPrefixes = [];
      if (theme === 'horror' && ext.sanidade !== undefined) traitPrefixes.push(`Sanidade: ${ext.sanidade}/10.`);
      if (theme === 'horror' && ext.medo) traitPrefixes.push(`Maior medo: ${ext.medo}.`);
      if (theme === 'romance' && ext.estado_emocional) traitPrefixes.push(`Estado emocional: ${ext.estado_emocional}.`);
      if (theme === 'faroeste' && ext.lado_lei) traitPrefixes.push(`Lei: ${ext.lado_lei}.`);
      if (theme === 'faroeste' && ext.codigo) traitPrefixes.push(`Linha que não cruza: ${ext.codigo}.`);
      if (traitPrefixes.length) charObj.traits = traitPrefixes.join(' ') + (charObj.traits ? ' ' + charObj.traits : '');

      // notes: agrega segredos, motivações, informações ocultas
      const noteParts = [];
      if (ext.segredo) noteParts.push(`Segredo: ${ext.segredo}`);
      if (ext.desejo) noteParts.push(`Desejo não confessado: ${ext.desejo}`);
      if (ext.historico) noteParts.push(`Histórico afetivo: ${ext.historico}`);
      if (ext.trauma) noteParts.push(`Trauma: ${ext.trauma}`);
      if (ext.ancora) noteParts.push(`Âncora de sanidade: ${ext.ancora}`);
      if (ext.alibi) noteParts.push(`Álibi: ${ext.alibi}`);
      if (ext.motivo) noteParts.push(`Motivo oculto: ${ext.motivo}`);
      if (ext.sabe_mas_cala) noteParts.push(`Sabe mas cala: ${ext.sabe_mas_cala}`);
      if (ext.faccao) noteParts.push(`Facção: ${ext.faccao}`);
      if (ext.segredo_tecno) noteParts.push(`Segredo: ${ext.segredo_tecno}`);
      if (ext.reputacao) noteParts.push(`Reputação: ${ext.reputacao}`);
      if (ext.vinculo) noteParts.push(`Vínculo com o grupo: ${ext.vinculo}`);
      if (charObj.notes) noteParts.push(charObj.notes);
      charObj.notes = noteParts.join(' | ');

      // inventario: itens físicos específicos do tema
      if (theme === 'fantasia' && ext.habilidade) {
        charObj.habilidades = [{nome: ext.habilidade, descricao: 'Habilidade especial do personagem.', custo_mana: 0, dado: ''}];
      }
      if (theme === 'scifi' && ext.implantes) {
        charObj.inventario.push({nome: ext.implantes, qtd: 1, descricao: 'Modificação cibernética ou implante neural.'});
      }
      if (theme === 'scifi' && ext.creditos && ext.creditos > 0) {
        charObj.inventario.push({nome: 'Créditos', qtd: ext.creditos, descricao: 'Moeda corrente do cenário.'});
      }
      if (theme === 'faroeste' && ext.recompensa && ext.recompensa > 0) {
        charObj.inventario.push({nome: 'Ficha de Procurado', qtd: 1, descricao: `Recompensa: $${ext.recompensa}. ${ext.lado_lei || ''}`});
      }
      if (theme === 'fantasia' && ext.raca) {
        charObj.description = `[${ext.raca}] ` + (charObj.description || '');
      }
    }

    if (isDnd) {
      const cls     = CLASS_DATA_WZ[char.classe] || CLASS_DATA_WZ['guerreiro'];
      const stats   = char.stats;
      const nivel   = Math.max(1, parseInt(char.nivel) || 1);
      const conMod  = Math.floor((parseInt(stats.constituicao) - 10) / 2);
      const dexMod  = Math.floor((parseInt(stats.destreza) - 10) / 2);
      // HP escalado por nível
      const avgDie  = Math.floor(cls.hit_die / 2) + 1;
      const hp_max  = Math.max(nivel, (cls.hit_die + conMod) + (nivel - 1) * Math.max(1, avgDie + conMod));
      let mana_max  = 0;
      if (cls.mana_stat && cls.mana_per_level > 0) {
        const mStatMod = Math.floor((parseInt(stats[cls.mana_stat]) - 10) / 2);
        mana_max = Math.max(0, (cls.mana_per_level + mStatMod) * nivel);
      }

      // Equipamentos: resolve com base nas escolhas feitas no wizard
      const startEquip  = wzGetResolvedEquip(char);
      const armorDexMod = Math.floor((parseInt(stats.destreza) - 10) / 2);
      const caFinal     = wzArmorCA(startEquip.arm, armorDexMod);

      charObj.sheet = {
        classe:      char.classe,
        raca:        char.raca,
        nivel,
        xp:          0,
        xp_proximo:  edXpForNextLevel(nivel),
        forca:       parseInt(stats.forca)        || 10,
        destreza:    parseInt(stats.destreza)     || 10,
        constituicao:parseInt(stats.constituicao) || 10,
        inteligencia:parseInt(stats.inteligencia) || 10,
        sabedoria:   parseInt(stats.sabedoria)    || 10,
        carisma:     parseInt(stats.carisma)      || 10,
        vida_atual:  hp_max,
        vida_max:    hp_max,
        mana_atual:  mana_max,
        mana_max:    mana_max,
        ca:          caFinal,
        proficiencia: edProfForLevel(nivel),
        hit_die:     cls.hit_die,
        ouro:        10, prata: 5, cobre: 0,
        equipamentos:{
          armadura:        startEquip.arm,
          escudo:          startEquip.esc,
          arma_principal:  startEquip.arma,
          arma_secundaria: startEquip.arma_sec || null,
          amuleto:         null,
        },
        condicoes:   [],
        death_saves_sucessos: 0,
        death_saves_falhas:   0,
      };
      // Inventário montado a partir das escolhas + itens fixos
      charObj.inventario = startEquip.inv;

      // Habilidades: feats e magias vêm das seleções Open5e do wizard.
      const selFeats  = char._selectedFeats  || [];
      const selSpells = char._selectedSpells || [];

      // Magias aplicadas: o que o usuário escolheu; se nada foi escolhido,
      // a lista curada padrão da classe (kit inicial sensato).
      let spellList = selSpells;
      if (CASTER_CLASSES_WZ.has(char.classe) && spellList.length === 0) {
        spellList = INITIAL_SPELLS_WZ[char.classe] || [];
      }

      const hasSelections = !char.freeMode && (selFeats.length || selSpells.length);

      if (hasSelections) {
        charObj.habilidades = [
          ...selFeats.map(f => ({ nome: f.nome, descricao: f.descricao || '', custo_mana: 0, dado: '' })),
          ...spellList.map(s => ({ nome: s.nome, descricao: s.descricao || '', custo_mana: s.custo_mana || 0, dado: s.dado || '' })),
        ];
      } else {
        // Sem seleção: usa habilidades padrão da classe + magias curadas
        charObj.habilidades = (CLASS_ABILITIES_WZ[char.classe] || []).map(h => ({...h}));

        if (CASTER_CLASSES_WZ.has(char.classe)) {
          const existingNames = new Set(charObj.habilidades.map(h => h.nome.toLowerCase()));
          spellList.forEach(s => {
            const lc = s.nome.toLowerCase();
            if (!existingNames.has(lc)) {
              charObj.habilidades.push({ nome: s.nome, descricao: s.descricao || 'Magia da classe.', custo_mana: s.custo_mana || 0, dado: s.dado || '' });
              existingNames.add(lc);
            }
          });
        }
      }

      // Aplica antecedente: proficiências como habilidades + itens no inventário
      if (char.background && BACKGROUND_LIST_WZ[char.background]) {
        const bg = BACKGROUND_LIST_WZ[char.background];
        // Adiciona proficiências de perícia como habilidades passivas
        (bg.skills || []).forEach(skill => {
          charObj.habilidades.push({
            nome:       `Proficiência: ${skill}`,
            descricao:  `Proficiência de perícia concedida pelo antecedente ${char.background}.`,
            custo_mana: 0,
            dado:       '',
          });
        });
        // Adiciona itens do antecedente ao inventário
        (bg.items || []).forEach(itemName => {
          charObj.inventario.push({ nome: itemName, qtd: 1, descricao: `(Antecedente: ${char.background})` });
        });
      }
    }

    characters[key] = charObj;

    if (char.isParty) {
      party.push({ name: char.name, role: char.role || '', notes: char.notes || '' });
    }
  }

  // Monta locations dict
  const locations = {};
  for (const loc of wzLocs) {
    if (!loc.name.trim()) continue;
    const key = loc.name.toLowerCase().trim().replace(/\s+/g, '_');
    locations[key] = { name: loc.name, description: loc.description, details: loc.details, notes: loc.notes };
  }

  // Monta events array
  const events = wzEvts.filter(e => e.summary.trim()).map((e, i) => ({
    index:                i + 1,
    summary:              e.summary,
    characters_involved:  party.map(p => p.name).join(', '),
    location:             e.location,
    consequence:          e.consequence,
  }));

  const campaignPayload = {
    campaign_type,
    dnd_mode:         isDnd,
    story_summary:    document.getElementById('wz-summary').value.trim(),
    current_scene:    document.getElementById('wz-scene').value.trim(),
    current_location: document.getElementById('wz-location').value.trim(),
    characters,
    party,
    locations,
    events,
    quest_flags:      {},
    diary:            [],
  };

  const btn = document.getElementById('wz-create-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Criando...';
  document.getElementById('wz-err').textContent = '';

  try {
    // 1. Cria a campanha no banco
    const createRes = await authFetch(`${API}/api/campaigns`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, campaign: campaignPayload }),
    });
    const createData = await createRes.json();
    if (!createRes.ok) throw new Error(createData.error || 'Erro ao criar campanha');

    // 2. Fecha wizard e inicia sessão diretamente
    closeWizard();
    selectedCampaign = name;
    isNewCampaign    = false; // campanha já criada, trata como existente

    // Inicia sessão com o modelo selecionado
    const sessionPayload = {
      campaign:      name,
      model:         document.getElementById('model-select').value,
      campaign_type,
      is_new:        false,
      story_mode:    'existing',
      story_input:   '',
      genre:         '',
    };
    btn.textContent = '⏳ Iniciando...';
    const keys = typeof window.getApiKeys === 'function' ? window.getApiKeys() : {};
    if (keys.google_api_key)   sessionPayload.google_api_key   = keys.google_api_key;
    if (keys.deepseek_api_key) sessionPayload.deepseek_api_key = keys.deepseek_api_key;

    const sesRes  = await authFetch(`${API}/api/session/start`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(sessionPayload),
    });
    const sesData = await sesRes.json();
    if (!sesData.ok) throw new Error(sesData.error || 'Erro ao iniciar sessão');

    localStorage.setItem('rpg_session', JSON.stringify({
      campaign:        sesData.campaign,
      model:           sesData.model_label,
      campaign_type,
      has_history:     sesData.has_history,
      opening:         sesData.opening,
      campaign_config: sesData.campaign_config || null,
      model_limits:    sesData.model_limits,
      conversation_history: sesData.conversation_history || [],
    }));
    window.location.href = '/game.html';

  } catch (e) {
    document.getElementById('wz-err').textContent = e.message;
    btn.disabled = false;
    btn.textContent = '⚔️ Criar e Iniciar';
  }
}

// ═══════════════════════════════════════════════════════════════════
//  EDITAR CAMPANHA
// ═══════════════════════════════════════════════════════════════════
let edStep = 1;
let edOriginalName = '';
let edChars = [];
let edLocs  = [];
let edEvts  = [];

function edIsDnd() { return document.getElementById('ed-type')?.value === 'dnd'; }

function edBlankSheet() {
  return {
    classe:'guerreiro', raca:'humano', background:'', nivel:1, xp:0, xp_proximo:300,
    forca:10, destreza:10, constituicao:10, inteligencia:10, sabedoria:10, carisma:10,
    vida_atual:10, vida_max:10, mana_atual:0, mana_max:0, ca:10, proficiencia:2, hit_die:8,
    ouro:0, prata:0, cobre:0,
    equipamentos:{ armadura:'', escudo:'', arma_principal:'', arma_secundaria:'', amuleto:'' },
    condicoes:[],
    death_saves_sucessos:0, death_saves_falhas:0,
  };
}

// ── D&D: Point Buy + ASI budget helpers ──────────────────────────────────────
const ED_PB_COST  = { 8:0, 9:1, 10:2, 11:3, 12:4, 13:5, 14:7, 15:9 };
const ED_PB_MAX   = 27;
const ED_STATS    = ['forca','destreza','constituicao','inteligencia','sabedoria','carisma'];
const ED_STAT_ABBR = { forca:'FOR', destreza:'DES', constituicao:'CON', inteligencia:'INT', sabedoria:'SAB', carisma:'CAR' };

function edAsiCount(nivel) {
  // Progressão padrão D&D 5e: ASI nos níveis 4, 8, 12, 16, 19
  return [4,8,12,16,19].filter(t => nivel >= t).length;
}

// Garante que ch._asiBonus existe com valores iniciais razoáveis
function edInitAsiBonus(ch) {
  if (ch._asiBonus) return;
  ch._asiBonus = {};
  for (const stat of ED_STATS) {
    // assume que qualquer valor acima de 15 veio de ASI
    const val = parseInt(ch.sheet?.[stat]) || 8;
    ch._asiBonus[stat] = Math.max(0, val - 15);
  }
}

function edStatBudget(i) {
  const ch       = edChars[i];
  const s        = ch?.sheet || {};
  const nivel    = parseInt(s.nivel) || 1;
  const asiTotal = edAsiCount(nivel) * 2;
  edInitAsiBonus(ch);
  const bonus = ch._asiBonus;

  // PB usa apenas o valor "base" (sem bônus de ASI), cap em 15
  let pbUsed = 0;
  for (const stat of ED_STATS) {
    const val  = parseInt(s[stat]) || 8;
    const base = Math.max(8, val - (bonus[stat] || 0));
    pbUsed += ED_PB_COST[Math.min(base, 15)] ?? 9;
  }
  // ASI usado = soma de todos os bônus (1 ponto ASI por +1, flat)
  const asiUsed = Object.values(bonus).reduce((a, b) => a + b, 0);

  return { pbBudget: ED_PB_MAX, pbUsed, asiTotal, asiUsed,
           pbRemain: ED_PB_MAX - pbUsed, asiRemain: asiTotal - asiUsed };
}

function edStatStep(i, stat, delta) {
  const ch = edChars[i];
  if (!ch?.sheet) return;
  edInitAsiBonus(ch);
  const cur   = parseInt(ch.sheet[stat]) || 8;
  const next  = cur + delta;
  if (next < 8 || next > 20) return;

  if (delta > 0) {
    const bud   = edStatBudget(i);
    const base  = Math.max(8, cur - (ch._asiBonus[stat] || 0));
    const pbDelta = (ED_PB_COST[Math.min(base + 1, 15)] ?? 9) - (ED_PB_COST[Math.min(base, 15)] ?? 9);
    const canUsePb = (ch._asiBonus[stat] || 0) === 0 && next <= 15 && bud.pbRemain >= pbDelta;

    if (canUsePb) {
      // aumenta via PB — nenhum bônus ASI alterado
    } else if (bud.asiRemain > 0) {
      // aumenta via ASI: sempre 1 ponto flat, independente do custo PB
      ch._asiBonus[stat] = (ch._asiBonus[stat] || 0) + 1;
    } else {
      return; // sem orçamento
    }
  } else {
    // ao diminuir: devolve ASI primeiro, depois PB
    if ((ch._asiBonus[stat] || 0) > 0) {
      ch._asiBonus[stat]--;
    }
    // se bonus === 0, a redução devolve PB automaticamente (base diminui)
  }

  ch.sheet[stat] = next;
  edRefreshDndSections(i);
}

// ── D&D: max spell level by character level ───────────────────────────────────
function edMaxSpellLevel(nivel) {
  return Math.min(9, Math.max(1, Math.ceil((parseInt(nivel)||1) / 2)));
}

// XP total necessário para atingir o próximo nível (tabela D&D 5e)
const ED_XP_THRESHOLDS = [0, 300, 900, 2700, 6500, 14000, 23000, 34000,
                           48000, 64000, 85000, 100000, 120000, 140000,
                           165000, 195000, 225000, 265000, 305000, 355000];
function edXpForNextLevel(nivel) {
  const n = Math.min(Math.max(parseInt(nivel) || 1, 1), 19);
  return ED_XP_THRESHOLDS[n];
}

// Bônus de proficiência padrão D&D 5e por nível
const ED_PROF_BY_LEVEL = [2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,6,6,6,6];
function edProfForLevel(nivel) {
  const n = Math.min(Math.max(parseInt(nivel) || 1, 1), 20);
  return ED_PROF_BY_LEVEL[n - 1];
}

// ── D&D: spell / item search state (per-character) ───────────────────────────
const edSpellTimer = {};
const edItemTimer  = {};

function edTriggerSpellSearch(i) {
  clearTimeout(edSpellTimer[i]);
  edSpellTimer[i] = setTimeout(() => edDoSpellSearch(i), 420);
}
function edTriggerItemSearch(i) {
  clearTimeout(edItemTimer[i]);
  edItemTimer[i] = setTimeout(() => edDoItemSearch(i), 420);
}

async function edDoSpellSearch(i) {
  const ch       = edChars[i];
  if (!ch) return;
  const freeMode = ch.freeMode === true;
  const classe   = ch.sheet?.classe || 'mago';
  const nivel    = ch.sheet?.nivel  || 1;
  const maxLevel = freeMode ? 9 : edMaxSpellLevel(nivel);
  const q        = (ch._spellQuery || '').trim();
  ch._spellLoading = true;
  edRefreshSpellPanel(i);
  try {
    const params = new URLSearchParams({ max_level: maxLevel });
    if (!freeMode) params.set('class', classe);
    if (q) params.set('q', q);
    // Filtro de nível exato
    const lvlF = ch._spellLevelFilter;
    if (lvlF !== null && lvlF !== undefined) params.set('spell_level', lvlF);
    const res  = await authFetch(`${API}/api/dnd/class-spells?${params}`);
    const data = await res.json();
    ch._spellResults  = data.spells || [];
    ch._spellLoading  = false;
  } catch(_) {
    ch._spellResults = [];
    ch._spellLoading = false;
  }
  edRefreshSpellPanel(i);
}

async function edDoItemSearch(i) {
  const ch = edChars[i];
  if (!ch) return;
  const q = (ch._itemQuery || '').trim();
  if (q.length < 2) { ch._itemResults = []; edRefreshItemPanel(i); return; }
  ch._itemLoading = true;
  edRefreshItemPanel(i);
  try {
    const res  = await authFetch(`${API}/api/dnd/items/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    ch._itemResults = data.items || [];
    ch._itemLoading = false;
  } catch(_) {
    ch._itemResults = [];
    ch._itemLoading = false;
  }
  edRefreshItemPanel(i);
}

async function edLoadClassFeatures(i) {
  const ch = edChars[i];
  if (!ch) return;
  const classe = ch.sheet?.classe || 'guerreiro';
  const nivel  = ch.sheet?.nivel  || 1;
  try {
    const res  = await authFetch(`${API}/api/dnd/class-features?class=${encodeURIComponent(classe)}&level=${nivel}`);
    const data = await res.json();
    ch._classFeatures  = data.features || [];
    ch._featLoading    = false;
  } catch(_) {
    ch._classFeatures = [];
  }
  edRefreshHabilidadesPanel(i);
}

function edAddSpell(i, spell) {
  const ch = edChars[i];
  if (!ch) return;
  const alreadyHas = ch.habilidades.some(h => h.nome.toLowerCase() === spell.nome.toLowerCase());
  if (!alreadyHas) {
    ch.habilidades.push({
      nome:        spell.nome,
      descricao:   [
        spell.escola ? `[${spell.escola}${spell.ritual?' (ritual)':''}${spell.concentracao?' (conc.)':''}]` : '',
        spell.descricao || '',
      ].filter(Boolean).join(' '),
      custo_mana:  spell.custo_mana ?? 0,
      dado:        spell.dado || '',
      nivel_magia: spell.nivel_magia ?? 0,
    });
  }
  // Mantém a aba de magias aberta; re-renderiza seção (atualiza ✓ na lista + habilidades abaixo)
  edRefreshDndSections(i);
}

function edAddClassFeature(i, feat) {
  const ch = edChars[i];
  if (!ch) return;
  if (!ch.habilidades.some(h => h.nome.toLowerCase() === feat.nome.toLowerCase())) {
    ch.habilidades.push({ nome:feat.nome, descricao:feat.descricao, custo_mana:feat.custo_mana||0, dado:feat.dado||'' });
  }
  // Mantém a aba aberta; atualiza ✓ nos resultados + lista de habilidades abaixo
  edRefreshHabilidadesPanel(i);
  edRefreshDndSections(i);
}

function edAddItem(i, item) {
  const ch = edChars[i];
  if (!ch) return;
  ch.inventario.push({ nome:item.nome, qtd:item.qtd||1, descricao:item.descricao||'' });
  ch._showItemSearch = false;
  edRefreshDndSections(i);
}

function edRefreshSpellPanel(i) {
  const el = document.getElementById(`ed-spell-panel-${i}`);
  if (el) el.innerHTML = edBuildSpellPanel(i);
}
function edRefreshItemPanel(i) {
  const el = document.getElementById(`ed-item-panel-${i}`);
  if (el) el.innerHTML = edBuildItemPanel(i);
}
function edRefreshHabilidadesPanel(i) {
  const el = document.getElementById(`ed-feat-panel-${i}`);
  if (el) el.innerHTML = edBuildFeatPanel(i);
}

// ── Abrir overlay ──────────────────────────────────────────────────
async function openEditCampaign(e, name) {
  e.stopPropagation();
  edOriginalName = name;
  edStep = 1;

  const overlay = document.getElementById('edit-overlay');
  overlay.classList.remove('hidden');

  ['ed-name','ed-summary','ed-scene','ed-location','ed-protagonist'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  document.getElementById('ed-err').textContent = '';
  document.getElementById('ed-chars-list').innerHTML = '<div style="padding:10px;font-style:italic;color:var(--text-muted);">A carregar...</div>';
  document.getElementById('ed-locs-list').innerHTML = '';
  document.getElementById('ed-evts-list').innerHTML = '';
  edRenderStep();

  try {
    const res  = await authFetch(`${API}/api/campaigns/${encodeURIComponent(name)}`);
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'Erro ao carregar campanha');

    const c = data.campaign;
    document.getElementById('ed-name').value        = c.name             || name;
    document.getElementById('ed-type').value        = c.campaign_type    || 'fantasia';
    document.getElementById('ed-summary').value     = c.story_summary    || '';
    document.getElementById('ed-scene').value       = c.current_scene    || '';
    document.getElementById('ed-location').value    = c.current_location || '';
    document.getElementById('ed-protagonist').value = c.protagonist      || '';

    // Personagens — carrega todos os campos incluindo ficha D&D
    edChars = Object.entries(c.characters || {}).map(([key, ch]) => ({
      key,
      name:        ch.name        || key,
      description: ch.description || '',
      traits:      ch.traits      || '',
      status:      ch.status      || 'vivo',
      notes:       ch.notes       || '',
      role:        ch.role        || '',
      isParty:     (c.party||[]).some(p => p.name?.toLowerCase() === (ch.name||key).toLowerCase()),
      sheet:       ch.sheet ? Object.assign(edBlankSheet(), ch.sheet) : edBlankSheet(),
      inventario:  Array.isArray(ch.inventario)  ? ch.inventario.map(it => ({...it}))  : [],
      habilidades: Array.isArray(ch.habilidades) ? ch.habilidades.map(h  => ({...h})) : [],
      _open:       false,
    }));
    edRenderChars();

    // Locais
    edLocs = Object.entries(c.locations || {}).map(([key, loc]) => ({
      key,
      name:        loc.name        || key,
      description: loc.description || '',
      details:     loc.details     || '',
      notes:       loc.notes       || '',
    }));
    edRenderLocs();

    // Eventos
    edEvts = (c.events || []).map(ev => ({
      summary:             ev.summary             || '',
      characters_involved: ev.characters_involved || '',
      location:            ev.location            || '',
      consequence:         ev.consequence         || '',
    }));
    edRenderEvts();

  } catch (err) {
    await showAlert('Erro', err.message, 'danger');
    closeEditOverlay();
  }
}

// ── Fechar overlay ─────────────────────────────────────────────────
function closeEditOverlay() {
  document.getElementById('edit-overlay').classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('edit-overlay')?.addEventListener('click', e => {
    if (e.target === document.getElementById('edit-overlay')) closeEditOverlay();
  });
});

// ── Navegação entre passos ─────────────────────────────────────────
function editGoTo(step) {
  if (step > edStep && edStep === 1 && !edValidateStep1()) return;
  edStep = step;
  edRenderStep();
}

function editNext() {
  if (edStep === 1) { if (!edValidateStep1()) return; edStep = 2; }
  else if (edStep === 2) { edStep = 3; }
  edRenderStep();
}

function editBack() {
  if (edStep > 1) { edStep--; edRenderStep(); }
}

function edRenderStep() {
  [1,2,3].forEach(n => {
    document.getElementById(`ed-panel-${n}`).classList.toggle('hidden', edStep !== n);
    const dot = document.getElementById(`ed-dot-${n}`);
    dot.classList.remove('active','done');
    if (n === edStep) dot.classList.add('active');
    else if (n < edStep) dot.classList.add('done');
  });
  document.getElementById('ed-back-btn').classList.toggle('hidden', edStep === 1);
  document.getElementById('ed-next-btn').classList.toggle('hidden', edStep === 3);
  document.getElementById('ed-save-btn').classList.toggle('hidden', edStep !== 3);
  document.getElementById('ed-err').textContent = '';
  document.getElementById('edit-scroll').scrollTop = 0;
}

function edValidateStep1() {
  const name = document.getElementById('ed-name').value.trim();
  if (!name) { document.getElementById('ed-err').textContent = 'Nome da campanha é obrigatório.'; return false; }
  return true;
}

// ── Personagens ────────────────────────────────────────────────────
function addEditChar() {
  const isDnd = edIsDnd();
  edChars.push({
    key:'', name:'', description:'', traits:'', status:'vivo',
    notes:'', role:'', isParty:true,
    sheet: isDnd ? edBlankSheet() : null,
    inventario: [], habilidades: [],
    _open: true,
  });
  edRenderChars();
  setTimeout(() => {
    const cards = document.querySelectorAll('#ed-chars-list .cwc');
    if (cards.length) cards[cards.length-1].scrollIntoView({ behavior:'smooth', block:'nearest' });
  }, 50);
}

function removeEditChar(i) { edChars.splice(i, 1); edRenderChars(); }

function toggleEditChar(i) {
  edChars[i]._open = !edChars[i]._open;
  const body  = document.getElementById(`ed-cb-${i}`);
  const arrow = document.getElementById(`ed-ca-${i}`);
  if (body)  body.classList.toggle('hidden', !edChars[i]._open);
  if (arrow) arrow.textContent = edChars[i]._open ? '▾' : '▸';
}

// ── D&D: atributos ─────────────────────────────────────────────────
function edSheetChange(i, field, value) {
  if (!edChars[i]) return;
  if (!edChars[i].sheet) edChars[i].sheet = edBlankSheet();
  const num = ['nivel','xp','xp_proximo','forca','destreza','constituicao','inteligencia','sabedoria','carisma',
                'vida_atual','vida_max','mana_atual','mana_max','ca','proficiencia','hit_die',
                'ouro','prata','cobre','death_saves_sucessos','death_saves_falhas'];
  edChars[i].sheet[field] = num.includes(field) ? (parseInt(value)||0) : value;
}

function edEquipChange(i, slot, value) {
  if (!edChars[i]?.sheet) return;
  if (!edChars[i].sheet.equipamentos) edChars[i].sheet.equipamentos = {};
  edChars[i].sheet.equipamentos[slot] = value;
}

// ── D&D: inventário ────────────────────────────────────────────────
function addEdItem(i) {
  edChars[i].inventario.push({ nome:'', qtd:1, descricao:'' });
  edRefreshDndSections(i);
}
function removeEdItem(i, j) {
  edChars[i].inventario.splice(j, 1);
  edRefreshDndSections(i);
}
function edItemChange(i, j, field, value) {
  if (!edChars[i]?.inventario[j]) return;
  edChars[i].inventario[j][field] = field === 'qtd' ? (parseInt(value)||1) : value;
}

// ── D&D: habilidades ───────────────────────────────────────────────
function addEdAbility(i) {
  edChars[i].habilidades.push({ nome:'', descricao:'', custo_mana:0, dado:'' });
  edRefreshDndSections(i);
}
function removeEdAbility(i, j) {
  edChars[i].habilidades.splice(j, 1);
  edRefreshDndSections(i);
}
function edAbilityChange(i, j, field, value) {
  if (!edChars[i]?.habilidades[j]) return;
  edChars[i].habilidades[j][field] = field === 'custo_mana' ? (parseInt(value)||0) : value;
}

// Atualiza só as seções D&D de um card sem re-renderizar tudo
function edRefreshDndSections(i) {
  const el = document.getElementById(`ed-dnd-sections-${i}`);
  if (el) el.innerHTML = edBuildDndSections(i);
}
// Troca de aba e auto-carrega conteúdo se necessário
function edSetHabTab(i, tab) {
  const ch = edChars[i];
  if (!ch) return;
  ch._habTab = tab;
  if (tab === 'feats' && !ch._classFeatures?.length && !ch._featLoading) {
    ch._featLoading = true;
    edLoadClassFeatures(i);
  }
  if (tab === 'spells' && !ch._spellResults?.length && !ch._spellLoading) {
    edDoSpellSearch(i);
  }
  edRefreshDndSections(i);
}

// ═══════════════════════════════════════════════════════════════════
//  Painéis de busca (spell / item / feat) — renderizados inline
// ═══════════════════════════════════════════════════════════════════
function edBuildSpellPanel(i) {
  const ch       = edChars[i];
  if (!ch) return '';
  const freeMode = ch.freeMode === true;
  const loading  = ch._spellLoading;
  const results  = ch._spellResults || [];
  const query    = escHtml(ch._spellQuery || '');
  const rawQuery = (ch._spellQuery || '').trim();
  const nivel    = ch.sheet?.nivel || 1;
  const maxSl    = freeMode ? 9 : edMaxSpellLevel(nivel);
  const lvlF     = ch._spellLevelFilter;   // null | 0–9
  const classe   = ch.sheet?.classe || '';
  const scopeMsg = freeMode
    ? `Modo livre — qualquer magia até Nv.${maxSl}`
    : `Magias de <strong>${escHtml(classe)}</strong> até Nv.${maxSl}`;

  // ── Botões de filtro por nível ──────────────────────────────────────
  const lvlBtnStyle = (active) =>
    `padding:3px 8px;border-radius:3px;border:1px solid ${active?'var(--ink-user)':'var(--page-edge)'};`+
    `background:${active?'rgba(38,75,130,0.12)':'transparent'};color:${active?'var(--ink-user)':'var(--text-muted)'};`+
    `cursor:pointer;font-size:10px;font-family:monospace;font-weight:${active?'700':'400'};`;
  let levelBtns = `<button style="${lvlBtnStyle(lvlF===null)}" `+
    `onclick="edChars[${i}]._spellLevelFilter=null;edChars[${i}]._spellResults=[];edDoSpellSearch(${i})">Todos</button>`;
  levelBtns += `<button style="${lvlBtnStyle(lvlF===0)}" `+
    `onclick="edChars[${i}]._spellLevelFilter=0;edChars[${i}]._spellResults=[];edDoSpellSearch(${i})">C</button>`;
  for (let n = 1; n <= maxSl; n++) {
    levelBtns += `<button style="${lvlBtnStyle(lvlF===n)}" `+
      `onclick="edChars[${i}]._spellLevelFilter=${n};edChars[${i}]._spellResults=[];edDoSpellSearch(${i})">${n}</button>`;
  }

  // ── Contagens e limites de magias (modo livre = sem limite) ───────────────
  const _edLimit      = freeMode ? null : getSpellLimit(classe, nivel, ch.sheet);
  const _edCantripCnt = ch.habilidades.filter(h => typeof h.nivel_magia === 'number' && h.nivel_magia === 0).length;
  const _edLeveledCnt = ch.habilidades.filter(h => typeof h.nivel_magia === 'number' && h.nivel_magia > 0).length;

  // ── Linha de resultado ──────────────────────────────────────────────
  const renderRow = (sp) => {
    const badge      = sp.nivel_magia === 0 ? 'C' : `${sp.nivel_magia}`;
    const manaTag    = sp.custo_mana > 0 ? ` · ${sp.custo_mana} mana` : '';
    const alreadyHas = ch.habilidades.some(h => h.nome.toLowerCase() === sp.nome.toLowerCase());
    const isCantrip  = sp.nivel_magia === 0;
    const limitReached = !alreadyHas && _edLimit && (isCantrip ? _edCantripCnt >= _edLimit.maxCantrips : _edLeveledCnt >= _edLimit.maxSpells);
    const regIdx     = _habInfoRegistry.length;
    _habInfoRegistry.push((alreadyHas || limitReached) ? null : () => { edAddSpell(i, sp); document.getElementById('hab-info-popup')?.remove(); });
    const spJson     = JSON.stringify(sp).replace(/"/g,'&quot;');
    return `<div class="ed-search-result ${alreadyHas?'ed-search-result-added':''}" onclick="showHabInfo(event,${spJson},${regIdx},${alreadyHas},${limitReached})" style="cursor:pointer;">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <span class="ed-spell-badge" style="min-width:22px;text-align:center;">${badge}</span>
        <strong style="font-size:13px;">${escHtml(sp.nome)}</strong>
        ${sp.dado?`<span style="font-family:monospace;font-size:10px;color:var(--text-muted);">${escHtml(sp.dado)}</span>`:''}
        ${manaTag?`<span style="font-size:10px;color:var(--ink-user);">${manaTag}</span>`:''}
        ${sp.concentracao?`<span style="font-size:9px;color:var(--text-muted);border:1px solid var(--page-edge);border-radius:2px;padding:0 3px;">conc.</span>`:''}
        ${sp.ritual?`<span style="font-size:9px;color:var(--text-muted);border:1px solid var(--page-edge);border-radius:2px;padding:0 3px;">ritual</span>`:''}
        ${alreadyHas?`<span style="font-size:10px;color:var(--green);">✓ já tem</span>`:''}
        ${limitReached&&!alreadyHas?`<span style="font-size:9px;color:var(--ink-sys);border:1px solid currentColor;border-radius:2px;padding:0 3px;opacity:0.7;">limite</span>`:''}
      </div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:3px;line-height:1.4;">${escHtml((sp.descricao||'').slice(0,100))}${(sp.descricao||'').length>100?'…':''}</div>
    </div>`;
  };

  // ── Conteúdo da lista ───────────────────────────────────────────────
  let listHtml;
  if (loading) {
    listHtml = '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">A carregar magias...</div>';
  } else if (results.length === 0) {
    listHtml = `<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">
      Nenhuma magia encontrada. Tente buscar pelo nome em inglês (ex: "fireball", "shield").
    </div>`;
  } else if (!rawQuery && lvlF === null) {
    // Agrupa por nível quando navegando sem filtro
    const groups = {};
    results.forEach(sp => { const k = sp.nivel_magia; if (!groups[k]) groups[k] = []; groups[k].push(sp); });
    const groupLabels = { 0: 'Cantrips (Nv. 0)' };
    listHtml = Object.keys(groups).sort((a,b) => a-b).map(lvl => {
      const label = groupLabels[lvl] || `Nível ${lvl}`;
      return `<div style="margin-bottom:8px;">
        <div style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;padding:4px 0 4px 2px;border-bottom:1px solid var(--page-edge);margin-bottom:4px;">${label}</div>
        ${groups[lvl].map(renderRow).join('')}
      </div>`;
    }).join('');
    if (results.length >= 100) {
      listHtml += `<div style="font-size:11px;color:var(--text-dim);font-style:italic;padding:6px 0;">Mostrando ${results.length} magias — filtre por nível ou pesquise para ver mais.</div>`;
    }
  } else {
    listHtml = results.map(renderRow).join('');
  }

  return `
    <div>
      <div style="font-size:11px;color:var(--ink-user);margin-bottom:8px;">${scopeMsg} · SRD Open5e${_edLimit ? `<span style="font-size:10px;font-family:monospace;color:var(--text-muted);margin-left:8px;">| C: ${_edCantripCnt}/${_edLimit.maxCantrips} ✨ ${_edLeveledCnt}/${_edLimit.maxSpells}</span>` : ''}</div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px;">${levelBtns}</div>
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <input id="ed-spell-q-${i}" value="${query}" placeholder="Buscar magia (ex: fireball)..."
          oninput="edChars[${i}]._spellQuery=this.value;edTriggerSpellSearch(${i})" style="flex:1;font-size:13px;">
        <button class="clean-button" style="width:auto;padding:4px 10px;margin:0;font-size:12px;"
          onclick="edDoSpellSearch(${i})">🔍</button>
      </div>
      <div class="ed-search-results-list" style="max-height:300px;" id="ed-spell-results-${i}">${listHtml}</div>
    </div>`;
}

function edBuildFeatPanel(i) {
  const ch      = edChars[i];
  if (!ch) return '';
  const feats   = ch._classFeatures || [];
  const loading = ch._featLoading;

  if (loading) return '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">A carregar habilidades de classe...</div>';

  const listHtml = feats.length === 0
    ? `<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:8px 0;">Nenhuma habilidade de classe encontrada para ${escHtml(ch.sheet?.classe||'esta classe')} nível ${ch.sheet?.nivel||1}.</div>`
    : feats.map(feat => {
        const alreadyHas = ch.habilidades.some(h => h.nome.toLowerCase() === feat.nome.toLowerCase());
        const regIdx     = _habInfoRegistry.length;
        _habInfoRegistry.push(alreadyHas ? null : () => { edAddClassFeature(i, feat); document.getElementById('hab-info-popup')?.remove(); });
        const featJson   = JSON.stringify(feat).replace(/"/g,'&quot;');
        return `<div class="ed-search-result ${alreadyHas?'ed-search-result-added':''}" onclick="showHabInfo(event,${featJson},${regIdx})" style="cursor:pointer;">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span class="ed-spell-badge" style="min-width:28px;text-align:center;">Nv.${feat.nivel}</span>
            <strong style="font-size:13px;">${escHtml(feat.nome)}</strong>
            ${alreadyHas?`<span style="font-size:10px;color:var(--green);">✓ já tem</span>`:''}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:4px;line-height:1.4;">${escHtml((feat.descricao||'').slice(0,120))}${(feat.descricao||'').length>120?'…':''}</div>
        </div>`;
      }).join('');

  return `
    <div>
      <div style="font-size:11px;color:var(--ink-user);margin-bottom:8px;">
        Habilidades de <strong>${escHtml(ch.sheet?.classe||'')}</strong> desbloqueadas até nível ${ch.sheet?.nivel||1}
      </div>
      <div class="ed-search-results-list" style="max-height:300px;">${listHtml}</div>
    </div>`;
}

function edBuildItemPanel(i) {
  const ch = edChars[i];
  if (!ch) return '';
  const loading = ch._itemLoading;
  const results = ch._itemResults || [];
  const query   = escHtml(ch._itemQuery || '');
  const TYPE_COLOR = { arma:'var(--ink-sys)', armadura:'var(--ink-user)', 'mágico':'var(--green)' };

  return `
    <div style="border:1px solid rgba(38,75,130,0.3);border-radius:6px;padding:12px;background:rgba(38,75,130,0.04);">
      <div style="display:flex;gap:8px;margin-bottom:10px;">
        <input id="ed-item-q-${i}" value="${query}" placeholder="Buscar item... (nome em inglês ou português)"
          oninput="edChars[${i}]._itemQuery=this.value;edTriggerItemSearch(${i})"
          style="flex:1;">
        <button style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:18px;padding:0 4px;"
          onclick="edChars[${i}]._showItemSearch=false;edRefreshDndSections(${i})">✕</button>
      </div>
      <div class="ed-search-results-list">
        ${loading ? '<div style="font-size:12px;color:var(--text-muted);font-style:italic;">A procurar...</div>' :
          results.length === 0 && query.length >= 2 ? '<div style="font-size:12px;color:var(--text-muted);font-style:italic;">Nenhum item encontrado.</div>' :
          results.length === 0 ? '<div style="font-size:12px;color:var(--text-muted);font-style:italic;">Digite pelo menos 2 caracteres para pesquisar.</div>' :
          results.map(it => `
            <div class="ed-search-result" onclick="edAddItem(${i},${JSON.stringify(it).replace(/"/g,'&quot;')})">
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="font-family:monospace;font-size:10px;font-weight:700;color:${TYPE_COLOR[it.tipo]||'var(--text-muted)'};">${(it.tipo||'').toUpperCase()}</span>
                <strong style="font-size:13px;">${escHtml(it.nome)}</strong>
              </div>
              ${it.descricao ? `<div style="font-size:11px;color:var(--text-dim);margin-top:4px;">${escHtml(it.descricao.slice(0,160))}</div>` : ''}
            </div>`).join('')}
      </div>
    </div>`;
}

// ── Gera HTML das seções D&D de um personagem ─────────────────────
function edBuildDndSections(i) {
  const ch = edChars[i];
  if (!ch || !ch.sheet) return '';
  const s        = ch.sheet;
  const eq       = s.equipamentos || {};
  const freeMode = ch.freeMode === true;

  const statMod = v => { const m = Math.floor((parseInt(v)-10)/2); return (m>=0?'+':'')+m; };

  // ─── Toggle Modo Livre ───────────────────────────────────────────
  const modeToggle = `
    <div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:10px 0 6px 0;border-bottom:1px solid var(--page-edge);margin-bottom:14px;">
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;color:var(--text-muted);">
        <input type="checkbox" ${freeMode?'checked':''} onchange="edChars[${i}].freeMode=this.checked;edRefreshDndSections(${i})">
        Modo Livre (sem restrições de regras)
      </label>
    </div>`;

  // ─── Ficha Principal (sempre livre) ─────────────────────────────
  const fichaHtml = `
    <div class="ed-dnd-section">
      <div class="ed-dnd-section-title">⚔️ Ficha D&D</div>
      <div class="cwc-row2">
        <div><span class="cwc-label">Classe</span>
          <select onchange="edSheetChange(${i},'classe',this.value);edChars[${i}]._classFeatures=[];edChars[${i}]._spellResults=[];edChars[${i}]._spellLevelFilter=null;edChars[${i}]._habTab=CASTER_CLASSES_WZ.has(this.value)?'spells':'feats';if(!edChars[${i}].freeMode){edChars[${i}]._featLoading=true;edLoadClassFeatures(${i});}edRefreshDndSections(${i})">
            ${Object.entries(CLASS_DATA_WZ).map(([k,v])=>`<option value="${k}" ${s.classe===k?'selected':''}>${v.label}</option>`).join('')}
          </select>
        </div>
        <div><span class="cwc-label">Raça</span>
          <select onchange="edSheetChange(${i},'raca',this.value)">
            ${['humano','elfo','anão','halfling','draconato','gnomo','meio-elfo','meio-orc','tiferino'].map(r=>
              `<option value="${r}" ${s.raca===r?'selected':''}>${r.charAt(0).toUpperCase()+r.slice(1)}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="cwc-row2" style="margin-top:10px;">
        <div><span class="cwc-label">Antecedente</span>
          <select onchange="edSheetChange(${i},'background',this.value)">
            <option value="" ${!s.background?'selected':''}>— Nenhum —</option>
            ${Object.keys(BACKGROUND_LIST_WZ).map(b=>
              `<option value="${b}" ${s.background===b?'selected':''}>${b.charAt(0).toUpperCase()+b.slice(1)}</option>`).join('')}
          </select>
        </div>
        <div class="cwc-row2" style="gap:8px;">
          <div><span class="cwc-label">Nível</span>
            <input type="number" min="1" max="20" value="${s.nivel||1}"
              onchange="
                const _nv=parseInt(this.value)||1;
                edChars[${i}].sheet.nivel=_nv;
                edChars[${i}].sheet.xp_proximo=edXpForNextLevel(_nv);
                edChars[${i}].sheet.proficiencia=edProfForLevel(_nv);
                edChars[${i}]._spellResults=[];
                edChars[${i}]._classFeatures=[];
                edRefreshDndSections(${i})">
          </div>
          <div><span class="cwc-label">Prof.</span>
            <input type="number" min="2" max="6" value="${s.proficiencia||edProfForLevel(s.nivel||1)}" onchange="edSheetChange(${i},'proficiencia',this.value)">
          </div>
        </div>
      </div>
      <div class="cwc-row2" style="margin-top:10px;">
        <div><span class="cwc-label">XP Atual</span>
          <input type="number" min="0" value="${s.xp||0}" onchange="edSheetChange(${i},'xp',this.value)">
        </div>
        <div><span class="cwc-label">XP Próximo Nível</span>
          <input type="number" min="0" value="${s.xp_proximo||300}" onchange="edSheetChange(${i},'xp_proximo',this.value)">
        </div>
      </div>
    </div>`;

  // ─── Atributos ───────────────────────────────────────────────────
  let statsHtml;
  if (freeMode) {
    statsHtml = `
      <div class="ed-dnd-section">
        <div class="ed-dnd-section-title">🎲 Atributos — Modo Livre</div>
        <div class="stat-grid">
          ${ED_STATS.map(stat => `
            <div class="stat-cell">
              <span class="stat-cell-name">${ED_STAT_ABBR[stat]}</span>
              <input type="number" min="1" max="30" value="${s[stat]||10}"
                oninput="edChars[${i}].sheet['${stat}']=parseInt(this.value)||8;document.getElementById('ed-mod-${i}-${stat}').textContent='${statMod(s[stat]||10)}'"
                onchange="edSheetChange(${i},'${stat}',this.value)"
                style="width:100%;text-align:center;font-size:18px;font-weight:700;padding:4px;border:1px solid var(--page-edge);border-radius:3px;background:transparent;">
              <span class="stat-cell-mod" id="ed-mod-${i}-${stat}">${statMod(s[stat]||10)}</span>
            </div>`).join('')}
        </div>
      </div>`;
  } else {
    // Modo estruturado: Point Buy (8-15) + ASI (qualquer atributo, até 20)
    const bud    = edStatBudget(i);
    const nivel  = parseInt(s.nivel) || 1;
    const asiCnt = edAsiCount(nivel);
    statsHtml = `
      <div class="ed-dnd-section">
        <div class="ed-dnd-section-title">🎲 Atributos — Point Buy + ASI</div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;font-size:12px;">
          <div class="pb-budget" style="padding:6px 10px;border-radius:4px;background:rgba(0,0,0,0.03);">
            <span style="color:var(--text-muted);">Point Buy: ${bud.pbUsed}/${bud.pbBudget}</span>
            <span style="color:var(--text-dim);"> · min 8, max 15</span>
          </div>
          <div class="pb-budget" style="padding:6px 10px;border-radius:4px;background:${bud.asiRemain<0?'rgba(180,40,40,0.08)':'rgba(38,75,130,0.06)'};">
            <span style="color:${bud.asiRemain<0?'var(--red)':bud.asiRemain===0?'var(--text-muted)':'var(--ink-user)'};">ASI (Nv.${nivel}): ${bud.asiUsed}/${bud.asiTotal}</span>
            <span style="color:var(--text-dim);"> · ${asiCnt} ASI${asiCnt!==1?'s':''} · qualquer atributo, até 20</span>
          </div>
        </div>
        <div class="stat-grid" id="ed-stat-grid-${i}">
          ${edRenderStatGridEdit(i)}
        </div>
      </div>`;
  }

  // ─── Combate (sempre livre) ───────────────────────────────────────
  const combateHtml = `
    <div class="ed-dnd-section">
      <div class="ed-dnd-section-title">❤️ Combate & Recursos</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">
        <div><span class="cwc-label">Vida Atual</span><input type="number" min="0" value="${s.vida_atual??10}" onchange="edSheetChange(${i},'vida_atual',this.value)"></div>
        <div><span class="cwc-label">Vida Máxima</span><input type="number" min="1" value="${s.vida_max??10}" onchange="edSheetChange(${i},'vida_max',this.value)"></div>
        <div><span class="cwc-label">CA</span><input type="number" min="1" value="${s.ca??10}" onchange="edSheetChange(${i},'ca',this.value)"></div>
        <div><span class="cwc-label">Mana Atual</span><input type="number" min="0" value="${s.mana_atual??0}" onchange="edSheetChange(${i},'mana_atual',this.value)"></div>
        <div><span class="cwc-label">Mana Máxima</span><input type="number" min="0" value="${s.mana_max??0}" onchange="edSheetChange(${i},'mana_max',this.value)"></div>
        <div><span class="cwc-label">Hit Die</span><input type="number" min="4" max="12" value="${s.hit_die??8}" onchange="edSheetChange(${i},'hit_die',this.value)"></div>
      </div>
      <div class="cwc-row2" style="margin-top:10px;">
        <div><span class="cwc-label">Death Saves ✓</span><input type="number" min="0" max="3" value="${s.death_saves_sucessos??0}" onchange="edSheetChange(${i},'death_saves_sucessos',this.value)"></div>
        <div><span class="cwc-label">Death Saves ✗</span><input type="number" min="0" max="3" value="${s.death_saves_falhas??0}" onchange="edSheetChange(${i},'death_saves_falhas',this.value)"></div>
      </div>
    </div>`;

  // ─── Riqueza & Equipamento ────────────────────────────────────────
  const equipHtml = `
    <div class="ed-dnd-section">
      <div class="ed-dnd-section-title">💰 Riqueza & Equipamentos</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;">
        <div><span class="cwc-label">Ouro</span><input type="number" min="0" value="${s.ouro??0}" onchange="edSheetChange(${i},'ouro',this.value)"></div>
        <div><span class="cwc-label">Prata</span><input type="number" min="0" value="${s.prata??0}" onchange="edSheetChange(${i},'prata',this.value)"></div>
        <div><span class="cwc-label">Cobre</span><input type="number" min="0" value="${s.cobre??0}" onchange="edSheetChange(${i},'cobre',this.value)"></div>
      </div>
      <div class="cwc-row2">
        <div><span class="cwc-label">Armadura</span><input value="${escHtml(eq.armadura||'')}" onchange="edEquipChange(${i},'armadura',this.value)" placeholder="Ex: Cota de malha"></div>
        <div><span class="cwc-label">Escudo</span><input value="${escHtml(eq.escudo||'')}" onchange="edEquipChange(${i},'escudo',this.value)" placeholder="Ex: Escudo de madeira"></div>
      </div>
      <div class="cwc-row2" style="margin-top:10px;">
        <div><span class="cwc-label">Arma Principal</span><input value="${escHtml(eq.arma_principal||'')}" onchange="edEquipChange(${i},'arma_principal',this.value)" placeholder="Ex: Espada longa"></div>
        <div><span class="cwc-label">Arma Secundária / Distância</span><input value="${escHtml(eq.arma_secundaria||'')}" onchange="edEquipChange(${i},'arma_secundaria',this.value)" placeholder="Ex: Arco curto, Besta leve"></div>
      </div>
      <div class="cwc-row2" style="margin-top:10px;">
        <div><span class="cwc-label">Amuleto</span><input value="${escHtml(eq.amuleto||'')}" onchange="edEquipChange(${i},'amuleto',this.value)" placeholder="Ex: Amuleto da proteção"></div>
        <div></div>
      </div>
    </div>`;

  // ─── Inventário ───────────────────────────────────────────────────
  const invBtns = freeMode
    ? `<button class="clean-button" style="width:auto;padding:3px 10px;margin:0;font-size:12px;" onclick="addEdItem(${i})">+ Item manual</button>`
    : `<div style="display:flex;gap:6px;">
        <button class="clean-button" style="width:auto;padding:3px 10px;margin:0;font-size:12px;" onclick="edChars[${i}]._showItemSearch=!edChars[${i}]._showItemSearch;edRefreshDndSections(${i})">+ Buscar Item (Open5e)</button>
        <button class="clean-button" style="width:auto;padding:3px 10px;margin:0;font-size:12px;" onclick="addEdItem(${i})">+ Item manual</button>
      </div>`;

  const invHtml = `
    <div class="ed-dnd-section">
      <div class="ed-dnd-section-title" style="display:flex;justify-content:space-between;align-items:center;">
        <span>🎒 Inventário</span>
        ${invBtns}
      </div>
      ${!freeMode && ch._showItemSearch ? `<div id="ed-item-panel-${i}" style="margin-bottom:10px;">${edBuildItemPanel(i)}</div>` : ''}
      ${ch.inventario.length ? ch.inventario.map((it, j) => `
        <div style="display:grid;grid-template-columns:1fr 60px 1fr auto;gap:8px;align-items:start;margin-bottom:8px;padding:8px;background:rgba(0,0,0,0.02);border-radius:4px;border:1px solid var(--page-edge);">
          <div><span class="cwc-label">Nome</span><input value="${escHtml(it.nome||'')}" onchange="edItemChange(${i},${j},'nome',this.value)" placeholder="Item"></div>
          <div><span class="cwc-label">Qtd</span><input type="number" min="0" value="${it.qtd??1}" onchange="edItemChange(${i},${j},'qtd',this.value)"></div>
          <div><span class="cwc-label">Descrição</span><input value="${escHtml(it.descricao||'')}" onchange="edItemChange(${i},${j},'descricao',this.value)" placeholder="Efeito / detalhes"></div>
          <div style="padding-top:20px;"><button onclick="removeEdItem(${i},${j})" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;">✕</button></div>
        </div>`).join('') : '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:6px 0;">Inventário vazio.</div>'}
    </div>`;

  // ─── Habilidades & Magias (interface com abas) ───────────────────────────
  const isCasterEd  = CASTER_CLASSES_WZ.has(s.classe);
  const showFeatTab = !freeMode;                        // habilidades de classe (não no modo livre)
  const showSpellTab = freeMode || isCasterEd;          // magias ou modo livre

  // Aba ativa — garante valor válido
  let edHabTab = ch._habTab || (isCasterEd ? 'spells' : 'feats');
  if (edHabTab === 'feats'  && !showFeatTab)  edHabTab = 'spells';
  if (edHabTab === 'spells' && !showSpellTab) edHabTab = 'feats';

  // Auto-carrega conteúdo da aba na primeira renderização
  if (edHabTab === 'feats' && showFeatTab && !ch._classFeatures?.length && !ch._featLoading) {
    ch._featLoading = true;
    setTimeout(() => edLoadClassFeatures(i), 20);
  }
  if (edHabTab === 'spells' && showSpellTab && !ch._spellResults?.length && !ch._spellLoading) {
    ch._spellLoading = true;
    setTimeout(() => edDoSpellSearch(i), 20);
  }

  // Estilo das abas
  const edTabStyle = (active) =>
    `padding:7px 16px;border:none;border-bottom:2px solid ${active?'var(--ink-user)':'transparent'};`+
    `background:none;cursor:pointer;font-family:'Lora',serif;font-size:12px;margin-bottom:-1px;`+
    `color:${active?'var(--ink-user)':'var(--text-muted)'};font-weight:${active?'700':'400'};`+
    `transition:color 0.15s,border-color 0.15s;`;

  const edTabBar = (showFeatTab || showSpellTab) ? `
    <div style="display:flex;border-bottom:1px solid var(--page-edge);margin-bottom:12px;">
      ${showFeatTab  ? `<button id="ed-hab-tab-feats-${i}"  style="${edTabStyle(edHabTab==='feats')}"  onclick="edSetHabTab(${i},'feats')">📜 Habilidades</button>`  : ''}
      ${showSpellTab ? `<button id="ed-hab-tab-spells-${i}" style="${edTabStyle(edHabTab==='spells')}" onclick="edSetHabTab(${i},'spells')">✨ Magias</button>` : ''}
      <button class="clean-button" style="width:auto;padding:3px 10px;margin:0 0 4px auto;font-size:11px;" onclick="addEdAbility(${i})">+ Manual</button>
    </div>` : `
    <div style="display:flex;justify-content:flex-end;margin-bottom:10px;">
      <button class="clean-button" style="width:auto;padding:3px 10px;margin:0;font-size:12px;" onclick="addEdAbility(${i})">+ Habilidade manual</button>
    </div>`;

  let edTabContent = '';
  if (edHabTab === 'feats' && showFeatTab) {
    edTabContent = `<div id="ed-feat-panel-${i}" style="margin-bottom:12px;">${edBuildFeatPanel(i)}</div>`;
  } else if (edHabTab === 'spells' && showSpellTab) {
    edTabContent = `<div id="ed-spell-panel-${i}" style="margin-bottom:12px;">${edBuildSpellPanel(i)}</div>`;
  }

  const habHtml = `
    <div class="ed-dnd-section">
      <div class="ed-dnd-section-title">✨ Habilidades & Magias</div>
      ${edTabBar}
      ${edTabContent}
      ${ch.habilidades.length ? ch.habilidades.map((h, j) => `
        <div style="padding:10px;background:rgba(0,0,0,0.02);border-radius:4px;border:1px solid var(--page-edge);margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:8px;">
            <div style="flex:1;"><span class="cwc-label">Nome</span><input value="${escHtml(h.nome||'')}" onchange="edAbilityChange(${i},${j},'nome',this.value)" placeholder="Nome"></div>
            <div style="width:90px;"><span class="cwc-label">Dado</span><input value="${escHtml(h.dado||'')}" onchange="edAbilityChange(${i},${j},'dado',this.value)" placeholder="1d6"></div>
            <div style="width:80px;"><span class="cwc-label">Mana</span><input type="number" min="0" value="${h.custo_mana??0}" onchange="edAbilityChange(${i},${j},'custo_mana',this.value)"></div>
            <div style="padding-top:20px;"><button onclick="removeEdAbility(${i},${j})" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;">✕</button></div>
          </div>
          <div><span class="cwc-label">Descrição / Efeito</span>
            <textarea rows="2" onchange="edAbilityChange(${i},${j},'descricao',this.value)" placeholder="Efeito, alcance, duração...">${escHtml(h.descricao||'')}</textarea>
          </div>
        </div>`).join('') : '<div style="font-size:12px;color:var(--text-muted);font-style:italic;padding:6px 0;">Nenhuma habilidade.</div>'}
    </div>`;

  return modeToggle + fichaHtml + statsHtml + combateHtml + equipHtml + invHtml + habHtml;
}

// ── Stat grid para modo estruturado do editor ──────────────────────
function edRenderStatGridEdit(i) {
  const ch  = edChars[i];
  const s   = ch?.sheet || {};
  const bud = edStatBudget(i);

  return ED_STATS.map(stat => {
    const val   = parseInt(s[stat]) || 8;
    const m     = Math.floor((val - 10) / 2);
    const mod   = (m >= 0 ? '+' : '') + m;
    const atMin    = val <= 8;
    const asiBonus = (ch._asiBonus?.[stat] || 0);
    const base     = Math.max(8, val - asiBonus);
    const pbDelta  = (ED_PB_COST[Math.min(base+1,15)]??9) - (ED_PB_COST[Math.min(base,15)]??9);
    const canUsePb = asiBonus === 0 && val < 15 && bud.pbRemain >= pbDelta;
    const canUp = val >= 20 ? false
                : canUsePb  ? true
                : /* usa ASI */ bud.asiRemain > 0;
    return `<div class="stat-cell">
      <span class="stat-cell-name">${ED_STAT_ABBR[stat]}</span>
      <div class="stat-stepper">
        <button class="stat-btn" onclick="edStatStep(${i},'${stat}',-1)" ${atMin?'disabled':''}>−</button>
        <span class="stat-val" id="ed-stat-${i}-${stat}">${val}</span>
        <button class="stat-btn" onclick="edStatStep(${i},'${stat}',+1)" ${canUp?'':'disabled'}>+</button>
      </div>
      <span class="stat-cell-mod" id="ed-mod-${i}-${stat}">${mod}</span>
    </div>`;
  }).join('');
}

// ── Renderiza lista de personagens ────────────────────────────────
function edRenderChars() {
  const container = document.getElementById('ed-chars-list');
  const empty     = document.getElementById('ed-chars-empty');
  if (!edChars.length) {
    container.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  const isDnd = edIsDnd();
  container.innerHTML = edChars.map((ch, i) => {
    const sh = ch.sheet;
    const classeLabel = isDnd && sh ? (CLASS_DATA_WZ[sh.classe]?.label || sh.classe || '') : '';
    return `
    <div class="cwc" id="ed-cc-${i}">
      <div class="cwc-header" onclick="toggleEditChar(${i})">
        <div style="display:flex;align-items:center;gap:10px;">
          <span id="ed-ca-${i}" style="color:var(--text-muted);font-size:12px;">${ch._open?'▾':'▸'}</span>
          <span style="font-family:'Playfair Display',serif;font-size:14px;" id="ed-cname-${i}">${escHtml(ch.name) || `Personagem ${i+1}`}</span>
          ${classeLabel ? `<span style="font-family:monospace;font-size:10px;color:var(--text-muted);">${classeLabel}</span>` : ''}
          ${ch.isParty ? `<span style="font-family:monospace;font-size:9px;background:rgba(38,75,130,0.08);border:1px solid rgba(38,75,130,0.25);border-radius:3px;padding:2px 6px;color:var(--ink-user);">GRUPO</span>` : ''}
        </div>
        <button onclick="event.stopPropagation();removeEditChar(${i})" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;padding:2px 6px;">✕</button>
      </div>
      <div class="cwc-body ${ch._open?'':'hidden'}" id="ed-cb-${i}">
        <div class="cwc-row2">
          <div>
            <span class="cwc-label">Nome *</span>
            <input value="${escHtml(ch.name)}" placeholder="Nome do personagem"
              onchange="edChars[${i}].name=this.value;document.getElementById('ed-cname-${i}').textContent=this.value||'Personagem ${i+1}'">
          </div>
          <div>
            <span class="cwc-label">Status</span>
            <select onchange="edChars[${i}].status=this.value">
              ${['vivo','morto','desaparecido','preso','inconsciente','inimigo'].map(s=>`<option ${ch.status===s?'selected':''}>${s}</option>`).join('')}
            </select>
          </div>
        </div>
        <div>
          <span class="cwc-label">Papel / Função</span>
          <input value="${escHtml(ch.role)}" onchange="edChars[${i}].role=this.value" placeholder="Ex: Guerreira, Aliada, Antagonista...">
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-top:4px;">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px;color:var(--text-muted);">
            <input type="checkbox" ${ch.isParty?'checked':''} onchange="edChars[${i}].isParty=this.checked">
            Membro do Grupo (party)
          </label>
        </div>
        <div>
          <span class="cwc-label">Descrição</span>
          <textarea rows="2" onchange="edChars[${i}].description=this.value" placeholder="Aparência física...">${escHtml(ch.description)}</textarea>
        </div>
        <div>
          <span class="cwc-label">Traços de Personalidade</span>
          <textarea rows="2" onchange="edChars[${i}].traits=this.value" placeholder="Motivações, medos...">${escHtml(ch.traits)}</textarea>
        </div>
        <div>
          <span class="cwc-label">Notas</span>
          <textarea rows="2" onchange="edChars[${i}].notes=this.value" placeholder="Informações adicionais...">${escHtml(ch.notes)}</textarea>
        </div>
        ${isDnd ? `<div id="ed-dnd-sections-${i}">${edBuildDndSections(i)}</div>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ── Locais ─────────────────────────────────────────────────────────
function addEditLoc() {
  edLocs.push({ key:'', name:'', description:'', details:'', notes:'' });
  edRenderLocs();
}
function removeEditLoc(i) { edLocs.splice(i,1); edRenderLocs(); }

function edRenderLocs() {
  const container = document.getElementById('ed-locs-list');
  if (!edLocs.length) {
    container.innerHTML = '<div style="font-size:13px;color:var(--text-muted);font-style:italic;padding:8px 0;">Nenhum local. Clique em + Local para adicionar.</div>';
    return;
  }
  container.innerHTML = edLocs.map((loc, i) => `
    <div class="wz-loc-card">
      <button onclick="removeEditLoc(${i})" style="position:absolute;top:8px;right:8px;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:14px;">✕</button>
      <div class="cwc-row2" style="margin-bottom:8px;">
        <div><span class="cwc-label">Nome</span>
          <input value="${escHtml(loc.name)}" onchange="edLocs[${i}].name=this.value" placeholder="Nome do local">
        </div>
        <div><span class="cwc-label">Detalhes</span>
          <input value="${escHtml(loc.details)}" onchange="edLocs[${i}].details=this.value" placeholder="Pontos específicos...">
        </div>
      </div>
      <span class="cwc-label">Descrição</span>
      <textarea rows="2" onchange="edLocs[${i}].description=this.value" placeholder="Descrição sensorial...">${escHtml(loc.description)}</textarea>
    </div>`).join('');
}

// ── Eventos ────────────────────────────────────────────────────────
function addEditEvt() {
  edEvts.push({ summary:'', characters_involved:'', location:'', consequence:'' });
  edRenderEvts();
}
function removeEditEvt(i) { edEvts.splice(i,1); edRenderEvts(); }

function edRenderEvts() {
  const container = document.getElementById('ed-evts-list');
  if (!edEvts.length) {
    container.innerHTML = '<div style="font-size:13px;color:var(--text-muted);font-style:italic;padding:8px 0;">Nenhum evento. Clique em + Evento para adicionar.</div>';
    return;
  }
  container.innerHTML = edEvts.map((ev, i) => `
    <div class="wz-evt-card">
      <button onclick="removeEditEvt(${i})" style="position:absolute;top:8px;right:8px;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:14px;">✕</button>
      <span class="cwc-label">Resumo do Evento</span>
      <textarea rows="2" onchange="edEvts[${i}].summary=this.value" placeholder="O que aconteceu?">${escHtml(ev.summary)}</textarea>
      <div class="cwc-row2" style="margin-top:8px;">
        <div><span class="cwc-label">Personagens Envolvidos</span>
          <input value="${escHtml(ev.characters_involved)}" onchange="edEvts[${i}].characters_involved=this.value" placeholder="Quem estava lá?">
        </div>
        <div><span class="cwc-label">Local</span>
          <input value="${escHtml(ev.location)}" onchange="edEvts[${i}].location=this.value" placeholder="Onde ocorreu?">
        </div>
      </div>
      <div style="margin-top:8px;"><span class="cwc-label">Consequência</span>
        <input value="${escHtml(ev.consequence)}" onchange="edEvts[${i}].consequence=this.value" placeholder="O que mudou?">
      </div>
    </div>`).join('');
}

// ── Salvar ─────────────────────────────────────────────────────────
async function saveEditedCampaign() {
  if (!edValidateStep1()) { edStep = 1; edRenderStep(); return; }

  const btn = document.getElementById('ed-save-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Salvando...';

  const newName = document.getElementById('ed-name').value.trim();
  const isDnd   = edIsDnd();

  // Reconstrói characters dict
  const characters = {};
  const party      = [];
  for (const ch of edChars) {
    if (!ch.name.trim()) continue;
    const key = ch.name.toLowerCase().trim().replace(/_/g, ' ');
    const charObj = {
      name:        ch.name,
      description: ch.description,
      traits:      ch.traits,
      status:      ch.status || 'vivo',
      notes:       ch.notes,
      role:        ch.role,
      sheet:       isDnd && ch.sheet ? ch.sheet : null,
      inventario:  isDnd ? (ch.inventario || []) : [],
      habilidades: isDnd ? (ch.habilidades || []) : [],
    };
    characters[key] = charObj;
    if (ch.isParty) party.push({ name: ch.name, role: ch.role||'', notes: ch.notes||'' });
  }

  // Reconstrói locations dict
  const locations = {};
  for (const loc of edLocs) {
    if (!loc.name.trim()) continue;
    const key = loc.name.toLowerCase().trim().replace(/ /g, '_');
    locations[key] = { name:loc.name, description:loc.description, details:loc.details, notes:loc.notes };
  }

  // Eventos com índice
  const events = edEvts
    .filter(ev => ev.summary.trim())
    .map((ev, idx) => ({
      index:               idx,
      summary:             ev.summary,
      characters_involved: ev.characters_involved,
      location:            ev.location,
      consequence:         ev.consequence,
    }));

  const payload = {
    campaign: {
      name:             newName,
      campaign_type:    document.getElementById('ed-type').value,
      dnd_mode:         isDnd,
      story_summary:    document.getElementById('ed-summary').value,
      current_scene:    document.getElementById('ed-scene').value,
      current_location: document.getElementById('ed-location').value,
      protagonist:      document.getElementById('ed-protagonist').value,
      characters,
      locations,
      events,
      party,
    }
  };

  try {
    const res  = await authFetch(`${API}/api/campaigns/${encodeURIComponent(edOriginalName)}`, {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'Erro ao salvar campanha');

    closeEditOverlay();
    await loadCampaigns();
    if (selectedCampaign === edOriginalName && data.name !== edOriginalName) {
      selectedCampaign = data.name;
    }
    await showAlert('Campanha atualizada', `"${data.name}" foi salva com sucesso.`, 'success');
  } catch (err) {
    document.getElementById('ed-err').textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Salvar Alterações';
  }
}