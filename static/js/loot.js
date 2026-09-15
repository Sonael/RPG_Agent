// ═══════════════════════════════════════════════════════════════════
//  loot.js — Tela de saque ("O Espólio")
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo mora aqui.
//  O que caiu, quanto pesa, a carga prevista de cada um, como as moedas se
//  dividem: tudo vem do motor (rpg/saque.py via /api/loot/*).
//
//  A tela existe porque o peso só faz o saque virar escolha se quem escolhe
//  é o jogador: levar a cota de malha deixa o guerreiro sobrecarregado na
//  próxima luta. Antes, o mestre punha tudo direto na ficha de alguém.
//
//  Quem ABRE o saque é o mestre (offer_loot), como no descanso. A tela abre
//  sozinha pela fila; fechada no ✕, vira pílula. Concluir põe os itens nos
//  inventários e manda [SAQUE RESOLVIDO NA TELA] ao mestre.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _busy = false;
  let _last = {};

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");

  // ---- Memória de "já abri por este saque" -----------------------------
  function campanhaAtual() {
    try { return (JSON.parse(localStorage.getItem('rpg_session') || '{}').campaign) || ''; }
    catch (_) { return ''; }
  }
  const CHAVE_MEMORIA = () => `rpg_telas::${campanhaAtual()}::saque_visto`;
  function idVisto() {
    try { return localStorage.getItem(CHAVE_MEMORIA()) || ''; } catch (_) { return ''; }
  }
  function marcarVisto(id) {
    try { localStorage.setItem(CHAVE_MEMORIA(), String(id)); } catch (_) { /* sem storage */ }
  }

  // Nenhuma tela abre sozinha por cima de outra.
  const OUTRAS_TELAS = ['combat-on', 'levelup-on', 'grimoire-on', 'rest-on', 'shop-on',
                        'inventory-on', 'local-on', 'pessoa-on', 'heroi-on'];
  const outraTelaAberta = () => OUTRAS_TELAS.some(c => document.body.classList.contains(c));

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (q('loot-overlay')) return;
    const o = document.createElement('div');
    o.id = 'loot-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="lot-frame" role="dialog" aria-modal="true" aria-labelledby="lot-titulo">
        <header class="lot-header">
          <button class="lot-close" onclick="window.Loot._close()"
                  aria-label="Fechar" title="Fechar — o saque continua no chão">✕</button>
          <h1 class="lot-title" id="lot-titulo">O Espólio <span id="lot-origem"></span></h1>
          <div id="lot-sub" class="lot-sub"></div>
        </header>

        <div class="lot-corpo">
          <section class="lot-chao" aria-label="No chão">
            <h2 class="lot-secao">No chão</h2>
            <div id="lot-itens" class="lot-itens"></div>
            <div id="lot-moedas" class="lot-moedas"></div>
          </section>
          <section class="lot-grupo" aria-label="Quem leva">
            <h2 class="lot-secao">Quem leva</h2>
            <div id="lot-cartoes" class="lot-cartoes"></div>
          </section>
        </div>

        <div class="lot-rodape">
          <div id="lot-msg" class="lot-msg" aria-live="polite"></div>
          <button id="lot-deixar" class="lot-deixar"
                  onclick="window.Loot._deixar()">Deixar tudo para trás</button>
          <button id="lot-concluir" class="lot-concluir"
                  onclick="window.Loot._concluir()">Concluir divisão</button>
        </div>
      </div>`;
    document.body.appendChild(o);

    if (!q('lot-reopen')) {
      const pill = document.createElement('button');
      pill.id = 'lot-reopen';
      pill.className = 'hidden';
      pill.textContent = 'Saque para dividir';
      pill.onclick = () => window.Loot._abrir();
      document.body.appendChild(pill);
    }
  }

  // ---- Rede --------------------------------------------------------
  async function api(path, opts) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}${path}`, opts || {});
    return r.json();
  }
  const getState = () => api('/api/loot/state');
  function doAction(p) {
    return api('/api/loot/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }

  // ---- Render ------------------------------------------------------
  const kg = (n) => `${Number(n).toFixed(n % 1 ? 2 : 0).replace(/\.?0+$/, '') || 0} kg`;
  const ROTULO_CARGA = { livre: 'livre', sobrecarregado: 'sobrecarregado', imovel: 'imóvel' };

  function itemNoChao(it, grupo) {
    const vivos = grupo.filter(p => !p.morto);
    const botoes = it.sobra > 0
      ? vivos.map(p => `<button class="lot-btn lot-btn-dar" data-para="${esc(p.nome)}"
                          onclick="window.Loot._dar('${aspas(it.id)}','${aspas(p.nome)}')">${esc(p.nome)}</button>`).join('')
      : '<span class="lot-tudo-dado">tudo distribuído</span>';
    return `
      <div class="lot-item${it.sobra > 0 ? '' : ' lot-item-dado'}" data-id="${esc(it.id)}" data-nome="${esc(it.nome)}">
        <div class="lot-item-cabeca">
          <span class="lot-item-nome">${esc(it.nome)}</span>
          <span class="lot-item-qtd">${it.sobra} de ${it.qtd} no chão</span>
          <span class="lot-item-peso">${kg(it.peso)} cada</span>
        </div>
        ${it.custom ? '<span class="lot-marca" title="Fora do SRD — item próprio da campanha">próprio da campanha</span>' : ''}
        ${it.descricao ? `<p class="lot-item-desc">${esc(it.descricao)}</p>` : ''}
        <div class="lot-item-acoes">${it.sobra > 0 ? '<span class="lot-para">Dar para:</span>' : ''}${botoes}</div>
      </div>`;
  }

  function moedas(s, grupo) {
    const m = s.moedas || {};
    const total = [['ouro', 'po'], ['prata', 'pp'], ['cobre', 'pc']]
      .filter(([k]) => m[k]).map(([k, a]) => `<b>${m[k]}</b> ${a}`).join(' · ');
    if (!total) return '';
    const vivos = grupo.filter(p => !p.morto);
    const opcoes = [`<option value="igual" ${s.moedas_para === 'igual' ? 'selected' : ''}>Dividir por igual</option>`]
      .concat(vivos.map(p => `<option value="${esc(p.nome)}" ${s.moedas_para === p.nome ? 'selected' : ''}>Tudo para ${esc(p.nome)}</option>`))
      .join('');
    return `
      <div class="lot-moedas-linha">
        <span class="lot-moedas-total">Moedas: ${total}</span>
        <select id="lot-moedas-sel" class="lot-moedas-sel" aria-label="Como dividir as moedas"
                onchange="window.Loot._moedas(this.value)">${opcoes}</select>
      </div>`;
  }

  function cartao(p) {
    const c = p.carga;
    const pct = (v) => (c.capacidade > 0 ? Math.max(0, Math.min(100, (v / c.capacidade) * 100)) : 0);
    const muda = c.kg_previsto !== c.kg;
    const cls = c.estado_previsto === 'imovel' ? ' lot-carga-imovel'
              : (c.estado_previsto === 'sobrecarregado' ? ' lot-carga-cheia' : '');
    const piora = c.estado_previsto !== c.estado;
    const moedasTxt = [['ouro', 'po'], ['prata', 'pp'], ['cobre', 'pc']]
      .filter(([k]) => (p.moedas_recebe || {})[k]).map(([k, a]) => `${p.moedas_recebe[k]} ${a}`).join(' ');
    const recebe = p.recebe.map(r => `
        <li><span>${r.qtd > 1 ? `${r.qtd}x ` : ''}${esc(r.nome)}</span>
          <button class="lot-btn lot-btn-devolver" title="Devolver uma unidade ao chão"
                  onclick="window.Loot._devolver('${aspas(r.id)}','${aspas(p.nome)}')">Devolver</button></li>`).join('');
    return `
      <div class="lot-cartao${p.morto ? ' lot-cartao-fora' : ''}" data-nome="${esc(p.nome)}">
        <div class="lot-cartao-cabeca">
          <span class="lot-nome">${esc(p.nome)}</span>
          <span class="lot-classe">${esc(p.classe)} · FOR ${p.forca}</span>
        </div>
        ${p.morto ? '<div class="lot-fora">Morto</div>' : `
        <div class="lot-carga">
          <div class="lot-carga-topo">
            <span>Carga</span>
            <span class="lot-num">${muda ? `${kg(c.kg)} → <b>${kg(c.kg_previsto)}</b>` : kg(c.kg)} / ${kg(c.capacidade)}</span>
          </div>
          <div class="lot-carga-barra">
            <div class="lot-carga-atual" style="width:${pct(c.kg)}%"></div>
            <div class="lot-carga-prevista${cls}" style="left:${pct(c.kg)}%;width:${Math.max(0, pct(c.kg_previsto) - pct(c.kg))}%"></div>
            <div class="lot-carga-meio" style="left:50%" title="Metade da capacidade (${kg(c.metade)}): acima daqui, desvantagem"></div>
          </div>
          <div class="lot-estado${piora ? ' lot-estado-piora' : ''}">${piora
            ? `${ROTULO_CARGA[c.estado]} → ${ROTULO_CARGA[c.estado_previsto]}`
            : ROTULO_CARGA[c.estado]}</div>
        </div>
        ${recebe ? `<ul class="lot-recebe">${recebe}</ul>` : '<div class="lot-nada">Não leva nada ainda.</div>'}
        ${moedasTxt ? `<div class="lot-moedas-recebe">+ ${esc(moedasTxt)}</div>` : ''}`}
      </div>`;
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();
    const s = _last.saque;
    const grupo = _last.grupo || [];
    if (!s) {
      q('lot-origem').textContent = '';
      q('lot-sub').textContent = '';
      q('lot-itens').innerHTML = '<div class="lot-vazio">Nenhum saque aberto.</div>';
      q('lot-moedas').innerHTML = '';
      q('lot-cartoes').innerHTML = '';
      q('lot-concluir').disabled = true;
      q('lot-deixar').disabled = true;
      return;
    }
    q('lot-origem').textContent = s.origem ? `— ${s.origem}` : '';
    q('lot-sub').textContent = s.sobrando
      ? `${s.sobrando} ${s.sobrando === 1 ? 'item ainda no chão' : 'itens ainda no chão'}`
      : 'Tudo distribuído';
    q('lot-itens').innerHTML = s.itens.length
      ? s.itens.map(it => itemNoChao(it, grupo)).join('')
      : '<div class="lot-vazio">Nenhum item, só moedas.</div>';
    q('lot-moedas').innerHTML = moedas(s, grupo);
    q('lot-cartoes').innerHTML = grupo.map(cartao).join('');
    const concluir = q('lot-concluir');
    concluir.disabled = _busy || !!_last.em_combate;
    concluir.textContent = s.sobrando
      ? `Concluir (${s.sobrando} ${s.sobrando === 1 ? 'fica' : 'ficam'} para trás)`
      : 'Concluir divisão';
    q('lot-deixar').disabled = _busy;
  }

  // ---- Sincronia ---------------------------------------------------
  async function sync() {
    try {
      const snap = await getState();
      if (!snap) return;
      const s = snap.saque;
      if (!s) {
        if (_open) fechar();
        _last = snap;
        atualizarPilula(snap);
        return;
      }
      if (String(s.id) !== idVisto() && !_open && !outraTelaAberta() && !snap.em_combate) {
        marcarVisto(s.id);
        abrir();
        return;
      }
      atualizarPilula(snap);
      if (_open) render(snap); else _last = snap;
    } catch (_) { /* a tela de saque nunca derruba o turno */ }
  }

  function atualizarPilula(snap) {
    const pill = q('lot-reopen');
    if (!pill) return;
    pill.classList.toggle('hidden', !(snap.saque && !_open));
  }

  // ---- Abrir / fechar ----------------------------------------------
  function abrir() {
    ensureDom();
    q('loot-overlay').classList.remove('hidden');
    document.body.classList.add('loot-on');
    _open = true;
    const pill = q('lot-reopen');
    if (pill) pill.classList.add('hidden');
    mensagem('', true);
    getState().then(render).catch(() => mensagem('Falha de conexão.', false));
  }

  function fechar() {
    const el = q('loot-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('loot-on');
    _open = false;
    atualizarPilula(_last || {});
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  function mensagem(txt, ok) {
    const el = q('lot-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lot-msg-erro', !ok);
  }

  // ---- Ações --------------------------------------------------------
  async function agir(payload) {
    if (_busy) return null;
    _busy = true;
    try {
      const res = await doAction(payload);
      _busy = false;
      if (res) {
        mensagem((res.message || '').split('\n')[0], res.ok !== false);
        if (res.snapshot) render(res.snapshot);
      }
      return res;
    } catch (_) {
      _busy = false;
      mensagem('Falha de conexão.', false);
      return null;
    }
  }

  async function avisarMestre(txt) {
    try {
      if (typeof window.sendToAgent === 'function') await window.sendToAgent(txt, true, 'tela');
    } catch (_) { /* fechar já é o essencial */ }
  }

  async function concluir() {
    const res = await agir({ action: 'concluir' });
    if (!res || res.ok === false) return;
    fechar();
    if (typeof window.refreshMemory === 'function') window.refreshMemory();
    await avisarMestre(
      `[SAQUE RESOLVIDO NA TELA] ${res.message} Os itens e as moedas JÁ ESTÃO nas `
      + `fichas: narre em uma ou duas frases o grupo recolhendo o espólio, sem `
      + `chamar add_item, modify_currency nem offer_loot de novo.`);
  }

  async function deixar() {
    const res = await agir({ action: 'deixar' });
    if (!res || res.ok === false) return;
    fechar();
    await avisarMestre(
      '[SAQUE DEIXADO NA TELA] O grupo deixou o saque para trás, sem levar nada. '
      + 'Siga a cena sem dar esses itens a ninguém.');
  }

  window.Loot = {
    sync,
    _abrir: abrir,
    _close: fechar,
    _concluir: concluir,
    _deixar: deixar,
    _dar: (item, char) => agir({ action: 'dar', item, char }),
    _devolver: (item, char) => agir({ action: 'devolver', item, char }),
    _moedas: (para) => agir({ action: 'moedas', coins_to: para }),
    _estado: () => _last,
  };

  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
