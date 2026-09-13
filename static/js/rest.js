// ═══════════════════════════════════════════════════════════════════
//  rest.js — Tela de descanso ("A Fogueira")
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo mora
//  aqui. Quantos dados restam, quanto cada um cura, o teto da exaustão, o
//  limite de um descanso longo por dia — tudo vem do motor
//  (tools_dnd via /api/rest/*).
//
//  A tela existe porque no 5e quem gasta os dados de vida é o JOGADOR, um de
//  cada vez, vendo quanto curou. Guardar dado para depois é a decisão que dá
//  peso à reserva; no chat, o motor rolava tudo de uma vez e ninguém decidia.
//
//  Quem ABRE o descanso é o mestre (offer_rest), porque é a ficção que diz
//  se o acampamento é seguro. A tela não tem botão de "descansar agora".
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _busy = false;
  let _last = {};

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q   = (id) => document.getElementById(id);

  // ---- Memória de "já abri por este descanso" ---------------------------
  // O id vem do servidor e não se repete entre descansos. Fica no
  // localStorage, por campanha, como nas outras telas: fechar no ✕ e dar F5
  // não reabre; um descanso novo reabre.
  function campanhaAtual() {
    try { return (JSON.parse(localStorage.getItem('rpg_session') || '{}').campaign) || ''; }
    catch (_) { return ''; }
  }
  const CHAVE_MEMORIA = () => `rpg_telas::${campanhaAtual()}::descanso_visto`;
  function idVisto() {
    try { return localStorage.getItem(CHAVE_MEMORIA()) || ''; } catch (_) { return ''; }
  }
  function marcarVisto(id) {
    try { localStorage.setItem(CHAVE_MEMORIA(), String(id)); }
    catch (_) { /* sem storage, só perde a memória entre recargas */ }
  }

  // Nenhuma tela abre sozinha por cima de outra. A fila do game.js roda
  // combate → nível → grimório → descanso → loja.
  const OUTRAS_TELAS = ['combat-on', 'levelup-on', 'shop-on', 'grimoire-on', 'inventory-on'];
  const outraTelaAberta = () => OUTRAS_TELAS.some(c => document.body.classList.contains(c));

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (q('rest-overlay')) return;
    const o = document.createElement('div');
    o.id = 'rest-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="rst-frame">
        <header class="rst-header">
          <button class="rst-close" onclick="window.Rest._close()"
                  aria-label="Fechar"
                  title="Fechar — o descanso continua aberto">✕</button>
          <h1 class="rst-title">A Fogueira <span id="rst-tipo"></span></h1>
          <div id="rst-sub" class="rst-sub"></div>
        </header>

        <div id="rst-corpo" class="rst-corpo"></div>

        <div class="rst-rodape">
          <div id="rst-msg" class="rst-msg" aria-live="polite"></div>
          <button id="rst-cancelar" class="rst-cancelar"
                  onclick="window.Rest._cancelar()">Não descansar</button>
          <button id="rst-concluir" class="rst-concluir"
                  onclick="window.Rest._concluir()">Concluir</button>
        </div>
      </div>`;
    document.body.appendChild(o);

    if (!q('rst-reopen')) {
      const pill = document.createElement('button');
      pill.id = 'rst-reopen';
      pill.className = 'hidden';
      pill.onclick = () => window.Rest._abrir();
      document.body.appendChild(pill);
    }
  }

  // ---- Rede --------------------------------------------------------
  async function api(path, opts) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}${path}`, opts || {});
    return r.json();
  }
  const getState = () => api('/api/rest/state');
  function doAction(p) {
    return api('/api/rest/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }

  // ---- Render ------------------------------------------------------
  const sinal = (n) => (n >= 0 ? '+' : '') + n;
  const pct = (a, b) => (b > 0 ? Math.max(0, Math.min(100, (a / b) * 100)) : 0);

  function barraDeVida(p) {
    // O teto da exaustão aparece como uma marca na barra: sem ela, "30/60" com
    // o botão de dado travado parece defeito.
    const marca = p.teto < p.vida_max
      ? `<div class="rst-vida-teto" style="left:${pct(p.teto, p.vida_max)}%"
              title="Teto de ${p.teto} pela exaustão"></div>` : '';
    return `
      <div class="rst-vida">
        <div class="rst-vida-topo">
          <span>Vida</span>
          <span class="rst-num">${p.vida_atual} / ${p.vida_max}${
            p.teto < p.vida_max ? ` <small>teto ${p.teto}</small>` : ''}</span>
        </div>
        <div class="rst-vida-barra">
          <div class="rst-vida-fill" style="width:${pct(p.vida_atual, p.vida_max)}%"></div>
          ${marca}
        </div>
      </div>`;
  }

  function pips(p) {
    // Um marcador por dado da reserva: cheio = disponível, vazio = gasto. É o
    // desenho que torna "guardar dado para depois" uma coisa que se vê.
    let h = '';
    for (let i = 0; i < p.dados_max; i++) {
      h += `<span class="rst-pip${i < p.dados_restantes ? ' rst-pip-cheio' : ''}"></span>`;
    }
    return `<span class="rst-pips" aria-label="${p.dados_restantes} de ${p.dados_max} dados">${h}</span>`;
  }

  const MOTIVO_BLOQUEIO = {
    'morto': 'Morto',
    'sem dados na reserva': 'Reserva vazia',
    'vida no máximo': 'Vida cheia',
  };

  function cartaoCurto(p) {
    const livre = !p.bloqueio_dado;
    return `
      <div class="rst-card${p.morto ? ' rst-card-fora' : ''}" data-nome="${esc(p.nome)}">
        <div class="rst-card-cabeca">
          <span class="rst-nome">${esc(p.nome)}</span>
          <span class="rst-classe">${esc(p.classe)} · nível ${p.nivel}</span>
        </div>
        ${barraDeVida(p)}
        <div class="rst-dados">
          <div class="rst-dados-topo">
            <span>Dados de vida</span>
            <span class="rst-num">${p.dados_restantes} / ${p.dados_max}</span>
          </div>
          ${pips(p)}
          <div class="rst-dados-regra">1d${p.dado} ${sinal(p.con_mod)} por dado</div>
        </div>
        <div class="rst-card-acao">
          <span class="rst-gastos">${p.gastos_agora
            ? `${p.gastos_agora} gasto${p.gastos_agora > 1 ? 's' : ''} agora` : ''}</span>
          <button class="rst-dado" ${livre ? '' : 'disabled'}
                  title="${livre ? 'Rolar 1 dado de vida' : esc(MOTIVO_BLOQUEIO[p.bloqueio_dado] || p.bloqueio_dado)}"
                  onclick="window.Rest._dado('${esc(p.nome).replace(/'/g, "\\'")}')">
            ${livre ? 'Gastar 1 dado' : esc(MOTIVO_BLOQUEIO[p.bloqueio_dado] || p.bloqueio_dado)}
          </button>
        </div>
      </div>`;
  }

  function cartaoLongo(p) {
    // No longo não há decisão por personagem: a tela mostra o que a noite vai
    // fazer e, mais importante, quem NÃO vai poder descansar e por quê.
    const fora = p.morto || !p.pode_longo;
    let efeito;
    if (p.morto) {
      efeito = `<div class="rst-longo-nao">Morto</div>`;
    } else if (!p.pode_longo) {
      efeito = `<div class="rst-longo-nao">Descansou há menos de 24 horas.
                  Faltam <b>${p.faltam_horas}h</b>.</div>`;
    } else {
      // Quantos voltam vem do motor (metade da reserva, no máximo o que foi
      // gasto): dizer "todos" aqui prometeria uma noite que não acontece.
      const depois = p.dados_restantes + p.dados_no_longo;
      const itens = [p.dados_no_longo
        ? `Dados de vida: +${p.dados_no_longo} (${depois} / ${p.dados_max})`
        : `Dados de vida: reserva já cheia (${p.dados_max})`];
      if (p.mana_max > 0) itens.unshift(`Mana volta a ${p.mana_max}`);
      itens.unshift('Vida volta ao máximo');
      if (p.exaustao > 0) itens.push(`Exaustão ${p.exaustao} → ${p.exaustao - 1}`);
      efeito = `<ul class="rst-longo-lista">${itens.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`;
    }
    return `
      <div class="rst-card${fora ? ' rst-card-fora' : ''}" data-nome="${esc(p.nome)}">
        <div class="rst-card-cabeca">
          <span class="rst-nome">${esc(p.nome)}</span>
          <span class="rst-classe">${esc(p.classe)} · nível ${p.nivel}</span>
        </div>
        ${barraDeVida(p)}
        ${efeito}
      </div>`;
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();

    const d = _last.descanso;
    const grupo = _last.grupo || [];

    if (!d) {
      q('rst-tipo').textContent = '';
      q('rst-sub').textContent = _last.hora || '';
      q('rst-corpo').innerHTML =
        '<div class="rst-vazio">Nenhum descanso aberto.<small>O mestre abre o descanso quando o grupo encontra um lugar seguro.</small></div>';
      q('rst-concluir').disabled = true;
      q('rst-cancelar').disabled = true;
      return;
    }

    const curto = d.tipo === 'curto';
    q('rst-tipo').textContent = curto ? '— descanso curto' : '— descanso longo';
    q('rst-sub').innerHTML =
      `<span>${curto ? '1 hora' : '8 horas'} · agora ${esc(_last.hora || '')}</span>`
      + (d.motivo ? `<span class="rst-motivo">${esc(d.motivo)}</span>` : '');

    q('rst-corpo').innerHTML = grupo.length
      ? `<div class="rst-grade">${grupo.map(curto ? cartaoCurto : cartaoLongo).join('')}</div>`
      : '<div class="rst-vazio">Nenhum personagem com ficha no grupo.</div>';

    // "Não descansar" some de uso depois do primeiro dado: a cura já
    // aconteceu e cancelar apagaria a hora que pagou por ela. O motor recusa
    // também; o botão travado só evita oferecer o clique.
    const cancelar = q('rst-cancelar');
    cancelar.disabled = !!d.com_gastos;
    cancelar.title = d.com_gastos ? 'Já há dados gastos: conclua o descanso' : '';

    const concluir = q('rst-concluir');
    if (curto) {
      concluir.disabled = false;
      concluir.textContent = 'Concluir descanso';
    } else {
      const aptos = grupo.filter(p => !p.morto && p.pode_longo).length;
      concluir.disabled = aptos === 0;
      concluir.textContent = aptos ? 'Dormir 8 horas' : 'Ninguém pode dormir ainda';
    }
  }

  // ---- Sincronia ---------------------------------------------------
  async function sync() {
    try {
      const snap = await getState();
      if (!snap) return;
      const d = snap.descanso;

      if (!d) {
        // O descanso sumiu por fora (uma emboscada rolou iniciativa): a tela
        // não pode ficar aberta oferecendo uma hora de sossego que não houve.
        if (_open) fechar();
        _last = snap;
        atualizarPilula(snap);
        return;
      }

      if (String(d.id) !== idVisto() && !_open && !outraTelaAberta()) {
        // Se outra tela estiver aberta, NÃO marca como visto: a fila tenta de
        // novo quando ela fechar.
        marcarVisto(d.id);
        abrir();
        return;
      }

      atualizarPilula(snap);
      if (_open) render(snap); else _last = snap;
    } catch (_) { /* a tela de descanso nunca derruba o turno */ }
  }

  function atualizarPilula(snap) {
    const pill = q('rst-reopen');
    if (!pill) return;
    const d = snap.descanso;
    if (d && !_open) {
      pill.textContent = d.tipo === 'curto' ? 'Descanso curto aberto' : 'Descanso longo aberto';
      pill.classList.remove('hidden');
    } else {
      pill.classList.add('hidden');
    }
  }

  // ---- Abrir / fechar ----------------------------------------------
  function abrir() {
    ensureDom();
    q('rest-overlay').classList.remove('hidden');
    document.body.classList.add('rest-on');
    const pill = q('rst-reopen');
    if (pill) pill.classList.add('hidden');
    _open = true;
    mensagem('', true);
    getState().then(render).catch(() => {});
  }

  function fechar() {
    const el = q('rest-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('rest-on');
    _open = false;
    atualizarPilula(_last || {});
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  function mensagem(txt, ok) {
    const el = q('rst-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('rst-msg-erro', !ok);
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
      if (typeof window.sendToAgent === 'function') await window.sendToAgent(txt, true);
    } catch (_) { /* fechar já é o essencial */ }
  }

  async function concluir() {
    const res = await agir({ action: 'concluir' });
    if (!res || res.ok === false) return;
    fechar();
    if (typeof window.refreshMemory === 'function') window.refreshMemory();
    await avisarMestre(
      `[DESCANSO RESOLVIDO NA TELA] ${res.message} Narre o descanso em uma ou `
      + `duas frases, usando a vida e os recursos que estão NA FICHA — não role `
      + `dado de vida nem chame ferramenta de descanso de novo.`);
  }

  async function cancelar() {
    const res = await agir({ action: 'cancelar' });
    if (!res || res.ok === false) return;
    fechar();
    await avisarMestre(
      '[DESCANSO CANCELADO NA TELA] O jogador preferiu não descansar agora. '
      + 'Siga a cena sem descanso.');
  }

  // ---- API pública ---------------------------------------------------
  window.Rest = {
    sync,
    _abrir: abrir,
    _close: fechar,
    _concluir: concluir,
    _cancelar: cancelar,
    _dado: (nome) => agir({ action: 'dado', char: nome }).then(res => {
      if (res && res.ok !== false && typeof window.refreshMemory === 'function') {
        window.refreshMemory();
      }
    }),
  };

  // Só monta o DOM; quem chama sync() é a fila de telas do game.js.
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
