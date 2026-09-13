// ═══════════════════════════════════════════════════════════════════
//  inventory.js — Tela de equipamento ("A Mochila")
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo mora
//  aqui. Onde cada item pode ir, que CA ele daria, quanto pesa, o que está a
//  identificar — tudo vem do motor (tools_dnd via /api/inventory/*). Os
//  botões chamam equip_item, unequip_item, remove_item e identify_item.
//
//  Diferente das outras, esta tela NÃO abre sozinha: nada no mundo pede
//  "agora arrume a mochila". Ela abre pelo atalho no cartão do personagem.
//  E fechar não manda nada ao mestre: vestir uma armadura não é cena.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _busy = false;
  let _last = {};
  let _quem = '';

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q   = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (q('inventory-overlay')) return;
    const o = document.createElement('div');
    o.id = 'inventory-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="inv-frame">
        <header class="inv-header">
          <button class="inv-close" onclick="window.Inventory._close()"
                  aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="inv-title">A Mochila <span id="inv-quem"></span></h1>
          <div id="inv-sub" class="inv-sub"></div>
          <div id="inv-resumo" class="inv-resumo"></div>
        </header>

        <div class="inv-corpo">
          <section class="inv-corpo-equip" aria-label="Equipado">
            <h2 class="inv-secao">No corpo</h2>
            <div id="inv-slots" class="inv-slots"></div>
          </section>
          <section class="inv-corpo-itens" aria-label="Mochila">
            <h2 class="inv-secao">Na mochila</h2>
            <div id="inv-itens" class="inv-itens"></div>
          </section>
        </div>

        <div class="inv-rodape">
          <div id="inv-msg" class="inv-msg" aria-live="polite"></div>
          <button class="inv-fechar" onclick="window.Inventory._close()">Fechar</button>
        </div>
      </div>`;
    document.body.appendChild(o);
  }

  // ---- Rede --------------------------------------------------------
  async function api(path, opts) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}${path}`, opts || {});
    return r.json();
  }
  const getState = () =>
    api('/api/inventory/state' + (_quem ? `?personagem=${encodeURIComponent(_quem)}` : ''));
  function doAction(p) {
    return api('/api/inventory/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }

  // ---- Render ------------------------------------------------------
  function moedas(m) {
    const p = [];
    if (m.ouro)  p.push(`<b>${m.ouro}</b> po`);
    if (m.prata) p.push(`<b>${m.prata}</b> pp`);
    if (m.cobre) p.push(`<b>${m.cobre}</b> pc`);
    return p.length ? p.join(' · ') : '<b>0</b> po';
  }

  function resumo(p) {
    // A barra de carga com a marca da metade, como na loja: acima da marca o
    // personagem luta com desvantagem, e é isso que faz o peso ser escolha.
    const c = p.carga;
    const pct = c.capacidade > 0 ? Math.max(0, Math.min(100, (c.kg / c.capacidade) * 100)) : 0;
    const cls = c.estado === 'imovel' ? ' inv-carga-imovel'
              : (c.estado === 'sobrecarregado' ? ' inv-carga-cheia' : '');
    return `
      <div class="inv-ca" title="Classe de Armadura">
        <span class="inv-ca-num" id="inv-ca-num">${p.ca}</span><span class="inv-ca-rotulo">CA</span>
      </div>
      <div class="inv-carga">
        <div class="inv-carga-topo">
          <span>Carga</span>
          <span class="inv-num">${c.kg} / ${c.capacidade} kg — ${esc(c.estado)}</span>
        </div>
        <div class="inv-carga-barra">
          <div class="inv-carga-fill${cls}" style="width:${pct}%"></div>
          <div class="inv-carga-meio" style="left:50%"
               title="Metade da capacidade (${c.metade} kg): acima daqui, desvantagem"></div>
        </div>
      </div>
      <div class="inv-moedas">${moedas(p.moedas)}</div>`;
  }

  function slot(e) {
    const ocupado = !!e.item;
    return `
      <div class="inv-slot${ocupado ? '' : ' inv-slot-vazio'}" data-slot="${esc(e.slot)}">
        <span class="inv-slot-rotulo">${esc(e.rotulo)}</span>
        <span class="inv-slot-item">${ocupado ? esc(e.item) : 'vazio'}</span>
        ${e.detalhe ? `<span class="inv-slot-detalhe">${esc(e.detalhe)}</span>` : ''}
        ${e.fora_da_mochila ? '<span class="inv-slot-aviso" title="Equipado na ficha, mas não está no inventário">fora da mochila</span>' : ''}
        ${ocupado ? `<button class="inv-btn inv-btn-tirar"
                            onclick="window.Inventory._desequipar('${aspas(e.slot)}')">Tirar</button>` : ''}
      </div>`;
  }

  function item(i, ca) {
    const marcas = [
      i.equipado_em.length ? `<span class="inv-marca inv-marca-equip">${i.equipado_em.map(esc).join(', ')}</span>` : '',
      i.custom ? '<span class="inv-marca" title="Fora do SRD — item próprio da campanha">próprio da campanha</span>' : '',
      i.a_identificar ? '<span class="inv-marca inv-marca-identificar">a identificar</span>' : '',
    ].join('');
    const botoes = i.opcoes_de_equipar.map(o => {
      // A prévia é o que torna a troca uma decisão: "CA 12 → 16" ao lado do
      // botão, antes de vestir.
      const previa = o.ca_previa != null && o.ca_previa !== ca
        ? ` <small class="inv-previa">CA ${ca} → ${o.ca_previa}</small>` : '';
      const troca = o.substitui ? ` title="Substitui ${esc(o.substitui)}"` : '';
      return `<button class="inv-btn inv-btn-equipar" data-slot="${esc(o.slot)}"${troca}
                      onclick="window.Inventory._equipar('${aspas(i.nome)}','${aspas(o.slot)}')">`
           + `${esc(o.rotulo)}${previa}</button>`;
    }).join('');
    return `
      <div class="inv-item" data-nome="${esc(i.nome)}">
        <div class="inv-item-cabeca">
          <span class="inv-item-nome">${esc(i.nome)}${i.qtd > 1 ? ` <small>×${i.qtd}</small>` : ''}</span>
          <span class="inv-item-peso">${i.peso_total} kg</span>
        </div>
        ${marcas ? `<div class="inv-marcas">${marcas}</div>` : ''}
        ${i.descricao ? `<p class="inv-item-desc">${esc(i.descricao)}</p>` : ''}
        <div class="inv-item-acoes">
          ${botoes}
          ${i.a_identificar ? `<button class="inv-btn inv-btn-identificar"
                                       onclick="window.Inventory._identificar('${aspas(i.nome)}')">Identificar</button>` : ''}
          <button class="inv-btn inv-btn-largar" title="Largar uma unidade"
                  onclick="window.Inventory._largar('${aspas(i.nome)}')">Largar 1</button>
        </div>
      </div>`;
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();
    const p = _last.personagem;
    if (!p) {
      q('inv-quem').textContent = '';
      q('inv-sub').textContent = '';
      q('inv-resumo').innerHTML = '';
      q('inv-slots').innerHTML = '';
      q('inv-itens').innerHTML = '<div class="inv-vazio">Nenhum personagem com ficha no grupo.</div>';
      return;
    }
    const grupo = _last.grupo || [];
    q('inv-quem').textContent = `— ${p.nome}`;
    q('inv-sub').innerHTML =
      (grupo.length > 1
        ? `<select class="inv-quem-sel" aria-label="Personagem"
                   onchange="window.Inventory._trocar(this.value)">`
          + grupo.map(n => `<option value="${esc(n)}" ${n === p.nome ? 'selected' : ''}>${esc(n)}</option>`).join('')
          + '</select>'
        : '')
      + `<span><span class="inv-classe">${esc(p.classe)}</span> · nível ${p.nivel} · FOR ${p.forca}</span>`;
    q('inv-resumo').innerHTML = resumo(p);
    q('inv-slots').innerHTML = p.equipados.map(slot).join('');
    q('inv-itens').innerHTML = p.itens.length
      ? p.itens.map(i => item(i, p.ca)).join('')
      : '<div class="inv-vazio">Mochila vazia.</div>';
  }

  // ---- Sincronia ---------------------------------------------------
  // Não abre sozinha. A fila só a redesenha enquanto aberta, para o que o
  // mestre mudar no chat (saque, compra) aparecer na hora.
  async function sync() {
    if (!_open) return;
    try { render(await getState()); } catch (_) { /* nunca derruba o turno */ }
  }

  function abrir(nome) {
    ensureDom();
    if (nome) _quem = nome;
    q('inventory-overlay').classList.remove('hidden');
    document.body.classList.add('inventory-on');
    _open = true;
    mensagem('', true);
    getState().then(render).catch(() => mensagem('Falha de conexão.', false));
  }

  function fechar() {
    const el = q('inventory-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('inventory-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  function mensagem(txt, ok) {
    const el = q('inv-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('inv-msg-erro', !ok);
  }

  async function agir(payload) {
    if (_busy) return;
    const p = _last.personagem || {};
    if (!p.nome) return;
    _busy = true;
    try {
      const res = await doAction({ char: p.nome, ...payload });
      _busy = false;
      if (!res) return;
      const texto = (res.message || '').replace(/\*\*/g, '').split('\n').filter(Boolean);
      // A primeira linha diz o que aconteceu; a da CA, quando houver, é a
      // que o jogador quer ver.
      const linhaCa = texto.find(l => /CA:?\s*\d+\s*→/.test(l));
      mensagem([texto[0], linhaCa && linhaCa !== texto[0] ? linhaCa.trim() : ''].filter(Boolean).join(' '),
               res.ok !== false);
      if (res.snapshot) render(res.snapshot);
      if (res.ok !== false && typeof window.refreshMemory === 'function') window.refreshMemory();
    } catch (_) {
      _busy = false;
      mensagem('Falha de conexão.', false);
    }
  }

  window.Inventory = {
    sync,
    _abrir: abrir,
    _close: fechar,
    _trocar: (n) => { _quem = n; getState().then(render).catch(() => {}); },
    _equipar: (item, slot) => agir({ action: 'equipar', item, slot }),
    _desequipar: (slot) => agir({ action: 'desequipar', slot }),
    _largar: (item) => agir({ action: 'largar', item }),
    _identificar: (item) => agir({ action: 'identificar', item }),
  };

  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
