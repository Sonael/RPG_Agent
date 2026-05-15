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
const INITIAL_SPELLS_WZ = {
  mago: [
    {nome:'Míssil Mágico',   descricao:'[Evocação] 3 dardos de força, 1d4+1 dano cada. Automático.',             custo_mana:4,  dado:'1d4'},
    {nome:'Mãos Ardentes',   descricao:'[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.',           custo_mana:4,  dado:'3d6'},
    {nome:'Sono',            descricao:'[Encantamento] Afeta 5d8 PV de criaturas, começando pelas mais fracas.',  custo_mana:4,  dado:'5d8'},
    {nome:'Prestidigitação', descricao:'[Truque] Efeitos mágicos menores: acender velas, limpar objetos, sons.',  custo_mana:0,  dado:''},
    {nome:'Luz',             descricao:'[Truque de evocação] Objeto toca emite luz como tocha por 1 hora.',       custo_mana:0,  dado:''},
    {nome:'Raio de Gelo',    descricao:'[Truque] Ataque mágico à distância: 1d8 dano de frio + velocidade -3m.', custo_mana:0,  dado:'1d8'},
  ],
  feiticeiro: [
    {nome:'Míssil Mágico',   descricao:'[Evocação] 3 dardos de força, 1d4+1 dano cada. Automático.',             custo_mana:4,  dado:'1d4'},
    {nome:'Mãos Ardentes',   descricao:'[Evocação] Cone de 4,5m, 3d6 dano de fogo. DEX salva metade.',           custo_mana:4,  dado:'3d6'},
    {nome:'Bola de Fogo',    descricao:'[Evocação] Esfera de 6m de raio, 8d6 dano de fogo. DEX salva metade.',   custo_mana:12, dado:'8d6'},
    {nome:'Chamas Sagradas', descricao:'[Truque] Ataque de magia: 1d8 dano radiante (DEX não conta para CA).',   custo_mana:0,  dado:'1d8'},
    {nome:'Luz',             descricao:'[Truque] Objeto emite luz como tocha por 1 hora.',                        custo_mana:0,  dado:''},
    {nome:'Raio de Gelo',    descricao:'[Truque] Ataque mágico à distância: 1d8 dano de frio.',                  custo_mana:0,  dado:'1d8'},
  ],
  bruxo: [
    {nome:'Golpe Místico',       descricao:'[Truque] Ataque mágico à distância: 1d10 dano de força.',                          custo_mana:0, dado:'1d10'},
    {nome:'Hex',                 descricao:'[Encantamento] Amaldiçoa alvo: +1d6 dano necrótico nos ataques. Concentração.',     custo_mana:4, dado:'1d6'},
    {nome:'Armadura do Agathys', descricao:'[Abjuração] Ganha 5 PV temporários; atacante leva 5 dano de frio.',                custo_mana:4, dado:''},
    {nome:'Ilusão Menor',        descricao:'[Truque] Cria som ou imagem ilusória por 1 minuto.',                               custo_mana:0, dado:''},
  ],
  clérigo: [
    {nome:'Cura Ferimentos', descricao:'[Evocação] Cura 1d8 + modificador de SAB de PV.',                                     custo_mana:4, dado:'1d8'},
    {nome:'Bênção',          descricao:'[Encantamento] Até 3 criaturas ganham +1d4 em ataques e salvaguardas. Concentração.',  custo_mana:4, dado:'1d4'},
    {nome:'Guia Divino',     descricao:'[Evocação] Ataque mágico à distância: 4d6 dano radiante. Vantagem contra alvos.',     custo_mana:4, dado:'4d6'},
    {nome:'Chamas Sagradas', descricao:'[Truque] Ataque de magia: 1d8 dano radiante (DEX não conta para CA).',                custo_mana:0, dado:'1d8'},
    {nome:'Orientação',      descricao:'[Truque] Toque: criatura ganha +1d4 em um teste de atributo.',                        custo_mana:0, dado:'1d4'},
  ],
  druida: [
    {nome:'Emaranhar',       descricao:'[Conjuração] Área de 6m quadrada emaranha criaturas. Concentração 1 min.', custo_mana:4, dado:''},
    {nome:'Cura Ferimentos', descricao:'[Evocação] Cura 1d8 + modificador de SAB de PV.',                          custo_mana:4, dado:'1d8'},
    {nome:'Névoa',           descricao:'[Conjuração] Nuvem de névoa 6m de raio, bloqueia visão. Concentração.',    custo_mana:4, dado:''},
    {nome:'Produzir Chama',  descricao:'[Truque] Chama na mão: ilumina 3m ou ataca à distância, 1d8 dano de fogo.',custo_mana:0, dado:'1d8'},
    {nome:'Orientação',      descricao:'[Truque] Toque: criatura ganha +1d4 em um teste de atributo.',             custo_mana:0, dado:'1d4'},
  ],
  bardo: [
    {nome:'Palavra Curativa', descricao:'[Evocação] Ação bônus: cura 1d4 + modificador de CAR de PV.',                          custo_mana:4, dado:'1d4'},
    {nome:'Encantamento',     descricao:'[Encantamento] Enfeitiça uma criatura humanóide por 1 hora. Concentração.',             custo_mana:4, dado:''},
    {nome:'Sono',             descricao:'[Encantamento] Afeta 5d8 PV de criaturas, começando pelas mais fracas.',               custo_mana:4, dado:'5d8'},
    {nome:'Insulto Cruel',    descricao:'[Truque] Ataque psíquico verbal: 1d4 dano psíquico + desvantagem no próximo ataque.',  custo_mana:0, dado:'1d4'},
    {nome:'Luz',              descricao:'[Truque] Objeto emite luz como tocha por 1 hora.',                                     custo_mana:0, dado:''},
  ],
  paladino: [
    {nome:'Punição Divina', descricao:'[Evocação] Quando acerta: +2d8 dano radiante. Ação bônus. Concentração.', custo_mana:4, dado:'2d8'},
    {nome:'Escudo da Fé',   descricao:'[Abjuração] Alvo ganha +2 de CA. Concentração, 10 min.',                  custo_mana:4, dado:''},
    {nome:'Cura Ferimentos',descricao:'[Evocação] Cura 1d8 + modificador de CAR de PV.',                         custo_mana:4, dado:'1d8'},
  ],
  patrulheiro: [
    {nome:'Marca do Caçador',descricao:'[Adivinhação] Designa inimigo: +1d6 dano nos ataques contra ele. Concentração.', custo_mana:4, dado:'1d6'},
    {nome:'Névoa',           descricao:'[Conjuração] Nuvem de névoa 6m de raio, bloqueia visão. Concentração.',          custo_mana:4, dado:''},
    {nome:'Cura Ferimentos', descricao:'[Evocação] Cura 1d8 + modificador de SAB de PV.',                                custo_mana:4, dado:'1d8'},
  ],
};

// Classes que têm painel de magias no wizard
const CASTER_CLASSES_WZ = new Set(Object.keys(INITIAL_SPELLS_WZ));

// Renderiza o painel de seleção de magias para o personagem i
function wzRenderSpellPanel(i) {
  const char = wzChars[i];
  if (!char || !CASTER_CLASSES_WZ.has(char.classe)) return '';

  const spells  = INITIAL_SPELLS_WZ[char.classe] || [];
  const selected = char.selectedSpells || [];

  return `
    <div id="wz-spell-panel-${i}">
      <span class="cwc-label">Magias Iniciais
        <span style="color:var(--text-muted);font-size:9px;">— selecione as que o personagem começará com</span>
      </span>
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;">
        ${spells.map(spell => {
          const checked = selected.includes(spell.nome);
          return `<label style="display:flex;align-items:center;gap:5px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-dim);cursor:pointer;padding:3px 8px;border:1px solid ${checked?'var(--gold-dim)':'var(--border2)'};border-radius:3px;background:${checked?'rgba(200,168,75,0.1)':'transparent'};transition:all 0.15s;">
            <input type="checkbox" ${checked?'checked':''} onchange="wzToggleSpell(${i},'${spell.nome}',this.checked)"
              style="accent-color:var(--gold);cursor:pointer;">
            ${spell.nome}
          </label>`;
        }).join('')}
      </div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--text-muted);margin-top:4px;">
        ${selected.length} magia(s) selecionada(s) · Se nenhuma for selecionada, todas serão aplicadas
      </div>
    </div>`;
}

// Toggle de seleção de magia individual
function wzToggleSpell(i, spellName, checked) {
  const char = wzChars[i];
  if (!char) return;
  char.selectedSpells = char.selectedSpells || [];
  if (checked) {
    if (!char.selectedSpells.includes(spellName)) char.selectedSpells.push(spellName);
  } else {
    char.selectedSpells = char.selectedSpells.filter(s => s !== spellName);
  }
  // Re-renderiza só o painel de magias
  const panel = document.getElementById(`wz-spell-panel-${i}`);
  if (panel) panel.outerHTML = wzRenderSpellPanel(i);
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
    stats: { forca:10, destreza:10, constituicao:10, inteligencia:10, sabedoria:10, carisma:10 },
    extras: {},
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
  const cls   = CLASS_DATA_WZ[char.classe] || CLASS_DATA_WZ['guerreiro'];
  const stats = char.stats;
  const conMod = Math.floor((parseInt(stats.constituicao) - 10) / 2);
  const dexMod = Math.floor((parseInt(stats.destreza) - 10) / 2);
  const hp   = Math.max(1, cls.hit_die + conMod);
  const ca   = 10 + dexMod;
  let mana = 0;
  if (cls.mana_stat && cls.mana_per_level > 0) {
    const mStatMod = Math.floor((parseInt(stats[cls.mana_stat]) - 10) / 2);
    mana = Math.max(0, cls.mana_per_level + mStatMod);
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
  // Update point buy budget
  if (!char.freeMode) {
    const used  = wzPointsUsed(char.stats);
    const rem   = PB_BUDGET - used;
    const budEl = document.getElementById(`wz-pb-${i}`);
    if (budEl) {
      budEl.textContent = `Pontos usados: ${used}/${PB_BUDGET}`;
      budEl.style.color = rem < 0 ? 'var(--red)' : rem === 0 ? 'var(--green)' : 'var(--text-dim)';
    }
  }
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
  wzChars[i].selectedSpells = []; // Reset magias ao trocar classe
  // Recalc HP/mana
  wzOnStatChange(i, 'forca', wzChars[i].stats.forca);
  // Re-renderiza painel de magias
  const panel = document.getElementById(`wz-spell-panel-${i}`);
  const spellContainer = panel ? panel.parentElement : null;
  if (spellContainer) {
    // Remove painel antigo e insere novo
    if (panel) panel.remove();
    if (CASTER_CLASSES_WZ.has(val)) {
      spellContainer.insertAdjacentHTML('beforeend', wzRenderSpellPanel(i));
    }
  }
}

function wzOnFreeMode(i, checked) {
  wzChars[i].freeMode = checked;
  // Se voltou para Point Buy, clampamos os valores que excediam 15
  if (!checked) {
    STATS_WZ.forEach(stat => {
      wzChars[i].stats[stat] = Math.max(8, Math.min(15, wzChars[i].stats[stat] || 8));
    });
  }
  const pbEl = document.getElementById(`wz-pb-wrap-${i}`);
  if (pbEl) pbEl.classList.toggle('hidden', checked);
  // Re-renderiza o grid de atributos para alternar entre stepper e input
  const gridEl = document.getElementById(`wz-stat-grid-${i}`);
  if (gridEl) gridEl.innerHTML = wzRenderStatGrid(i);
}

function wzApplyStdArray(i) {
  const vals = [15,14,13,12,10,8];
  STATS_WZ.forEach((stat, j) => {
    wzChars[i].stats[stat] = vals[j];
    wzOnStatChange(i, stat, vals[j]);
  });
  // Re-renderiza o grid para refletir os novos valores nos steppers
  const gridEl = document.getElementById(`wz-stat-grid-${i}`);
  if (gridEl) gridEl.innerHTML = wzRenderStatGrid(i);
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

// ── Renderiza o grid de atributos de um personagem ────────────────────────
// Modo normal: stepper −/+ com botões (funciona no mobile).
// Modo livre: input numérico sem limites.
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
      const atMin = val <= 8;
      const atMax = val >= 15;
      return `<div class="stat-cell">
        <span class="stat-cell-name">${name}</span>
        <div class="stat-stepper">
          <button class="stat-btn" onclick="wzStatStep(${i},'${stat}',-1)"
            ${atMin ? 'disabled' : ''}>−</button>
          <span class="stat-val" id="wz-stat-${i}-${stat}">${val}</span>
          <button class="stat-btn" onclick="wzStatStep(${i},'${stat}',+1)"
            ${atMax ? 'disabled' : ''}>+</button>
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
    const calc = isDnd ? wzCalcSheet(char) : null;
    const used = isDnd && !char.freeMode ? wzPointsUsed(char.stats) : 0;

    const statsHtml = isDnd ? `
      <div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
          <span class="cwc-label" style="margin:0;">Atributos</span>
          <div style="display:flex;gap:6px;align-items:center;">
            <button onclick="wzApplyStdArray(${i})" style="background:none;border:1px solid var(--border2);border-radius:3px;color:var(--text-muted);font-size:9px;padding:3px 8px;cursor:pointer;letter-spacing:0.06em;">ARRAY PADRÃO</button>
            <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:10px;color:var(--text-muted);">
              <input type="checkbox" ${char.freeMode?'checked':''} onchange="wzOnFreeMode(${i},this.checked)" style="accent-color:var(--gold);">
              Modo Livre
            </label>
          </div>
        </div>
        <div id="wz-pb-wrap-${i}" class="${char.freeMode?'hidden':''}">
          <div class="pb-budget" style="margin-bottom:8px;">
            <span id="wz-pb-${i}" style="color:${(PB_BUDGET-used)<0?'var(--red)':'var(--text-dim)'};">Pontos usados: ${used}/${PB_BUDGET}</span>
            <span style="color:var(--text-muted);">· Min 8 · Max 15 · Point Buy D&D 5e</span>
          </div>
        </div>
        <div class="stat-grid" id="wz-stat-grid-${i}">
          ${wzRenderStatGrid(i)}
        </div>
      </div>
      ${calc ? `
      <div class="dnd-calc-row">
        <div class="dnd-calc-item">❤️ HP <span id="wz-hp-${i}">${calc.hp}</span></div>
        <div class="dnd-calc-item">🛡️ CA <span id="wz-ca-${i}">${calc.ca}</span></div>
        ${calc.mana > 0 ? `<div class="dnd-calc-item">✨ Mana <span id="wz-mn-${i}">${calc.mana}</span></div>` : ''}
        <div class="dnd-calc-item">d${calc.hit_die} hit die · Prof +2</div>
      </div>` : ''}
    ` : '';

    const dndBasicHtml = isDnd ? `
      <div class="cwc-row2">
        <div>
          <span class="cwc-label">Classe</span>
          <select onchange="wzOnClassChange(${i},this.value)">
            ${Object.entries(CLASS_DATA_WZ).map(([k,v]) =>
              `<option value="${k}" ${char.classe===k?'selected':''}>${v.label}</option>`
            ).join('')}
          </select>
        </div>
        <div>
          <span class="cwc-label">Raça</span>
          <select onchange="wzOnRaceChange(${i}, this.value)">
            ${['humano','elfo','anão','halfling','draconato','gnomo','meio-elfo','meio-orc','tiferino'].map(r => {
              const bonuses = RACE_BONUSES_WZ[r] || {};
              const bonusStr = Object.entries(bonuses).map(([k,v]) => `${k.slice(0,3).toUpperCase()} +${v}`).join(', ');
              const label = r.charAt(0).toUpperCase() + r.slice(1) + (bonusStr ? ` (${bonusStr})` : '');
              return `<option value="${r}" ${char.raca===r?'selected':''}>${label}</option>`;
            }).join('')}
          </select>
        </div>
      </div>
      <div>
        <span class="cwc-label">Antecedente <span style="color:var(--text-muted);font-size:9px;">(opcional — concede proficiências e itens iniciais)</span></span>
        <select onchange="wzOnBackgroundChange(${i}, this.value)">
          <option value="" ${!char.background?'selected':''}>— Nenhum —</option>
          ${Object.keys(BACKGROUND_LIST_WZ).map(b =>
            `<option value="${b}" ${char.background===b?'selected':''}>${b.charAt(0).toUpperCase()+b.slice(1)}</option>`
          ).join('')}
        </select>
        ${char.background ? `<div id="wz-bg-info-${i}" style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--text-muted);margin-top:4px;line-height:1.5;">${wzBgInfo(char.background)}</div>` : ''}
      </div>
      ${CASTER_CLASSES_WZ.has(char.classe) ? wzRenderSpellPanel(i) : ''}` : '';


    return `
    <div class="cwc" id="cwc-${i}">
      <div class="cwc-header" onclick="toggleWzChar(${i})">
        <div style="display:flex;align-items:center;gap:10px;">
          <span id="cwc-arrow-${i}" style="color:var(--gold-dim);font-size:12px;">${open?'▾':'▸'}</span>
          <span style="font-family:'Cinzel',serif;font-size:13px;color:var(--text);">
            ${char.name || `Personagem ${i+1}`}
          </span>
          ${char.isParty ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;background:rgba(200,168,75,0.15);border:1px solid var(--gold-dim);border-radius:3px;padding:2px 6px;color:var(--gold-dim);">GRUPO</span>` : ''}
          ${isDnd && char.classe ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--text-muted);">${CLASS_DATA_WZ[char.classe]?.label||''}</span>` : wzExtraBadge(char, document.getElementById('wz-type').value)}
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
              ${['vivo','morto','desaparecido','preso','inconsciente','inimigo'].map(s =>
                `<option ${char.status===s?'selected':''}>${s}</option>`).join('')}
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
        ${dndBasicHtml}
        ${statsHtml}
      </div>
    </div>`;
  }).join('');
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
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
      const conMod  = Math.floor((parseInt(stats.constituicao) - 10) / 2);
      const dexMod  = Math.floor((parseInt(stats.destreza) - 10) / 2);
      const hp_max  = Math.max(1, cls.hit_die + conMod);
      const ca      = 10 + dexMod;
      let mana_max  = 0;
      if (cls.mana_stat && cls.mana_per_level > 0) {
        const mStatMod = Math.floor((parseInt(stats[cls.mana_stat]) - 10) / 2);
        mana_max = Math.max(0, cls.mana_per_level + mStatMod);
      }

      // Equipamentos e habilidades iniciais da classe
      const startEquip  = CLASS_EQUIPMENT_WZ[char.classe] || CLASS_EQUIPMENT_WZ['npc'];
      const armorDexMod = Math.floor((parseInt(stats.destreza) - 10) / 2);
      const caFinal     = wzArmorCA(startEquip.arm, armorDexMod);

      charObj.sheet = {
        classe:      char.classe,
        raca:        char.raca,
        nivel:       1,
        xp:          0,
        xp_proximo:  300,
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
        proficiencia: 2,
        hit_die:     cls.hit_die,
        ouro:        10, prata: 5, cobre: 0,
        equipamentos:{
          armadura:       startEquip.arm,
          escudo:         startEquip.esc,
          arma_principal: startEquip.arma,
          amuleto:        null,
        },
        condicoes:   [],
        death_saves_sucessos: 0,
        death_saves_falhas:   0,
      };
      // Inventário e habilidades iniciais da classe
      charObj.inventario  = startEquip.inv.map(i => ({...i}));
      charObj.habilidades = (CLASS_ABILITIES_WZ[char.classe] || []).map(h => ({...h}));

      // Magias iniciais selecionadas no wizard
      if (CASTER_CLASSES_WZ.has(char.classe)) {
        const spellPool = INITIAL_SPELLS_WZ[char.classe] || [];
        // Mapa rápido de nome (lowercase) → objeto completo da magia
        const spellDataMap = {};
        spellPool.forEach(s => { spellDataMap[s.nome.toLowerCase()] = s; });

        // selectedSpells guarda nomes (strings); se vazio usa todas as magias do pool
        const chosenNames = char.selectedSpells && char.selectedSpells.length > 0
                            ? char.selectedSpells
                            : spellPool.map(s => s.nome);

        const existingNames = new Set(charObj.habilidades.map(h => h.nome.toLowerCase()));
        chosenNames.forEach(spellName => {
          const lc   = spellName.toLowerCase();
          const data = spellDataMap[lc];
          if (!existingNames.has(lc)) {
            charObj.habilidades.push({
              nome:       data ? data.nome       : spellName,
              descricao:  data ? data.descricao  : 'Magia inicial da classe.',
              custo_mana: data ? data.custo_mana : 4,
              dado:       data ? data.dado       : '',
            });
            existingNames.add(lc);
          }
        });
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