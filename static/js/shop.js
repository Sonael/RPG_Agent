// ═══════════════════════════════════════════════════════════════════
//  shop.js — Tela de loja ("O Balcão")
//
//  REGRA DE OURO, a mesma do combat.js: este módulo NÃO tem nenhuma regra
//  de jogo. Preço, troco, estoque, peso e a marca de item inventado vivem
//  no motor (tools_dnd via /api/shop/*). Aqui só: (1) renderiza o
//  snapshot, (2) envia intenções, (3) abre e fecha.
//
//  A tela existe porque comprar é um LAÇO — olhar preço, conferir bolsa,
//  conferir peso, comprar, repetir — e no chat cada volta desse laço custa
//  uma ida à LLM. Também é o único lugar onde dá para ver ouro, peso e
//  estoque ao mesmo tempo, que é o que torna a compra uma escolha.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open   = false;
  let _busy   = false;
  let _last   = {};
  let _loja   = '';      // chave da loja aberta na tela
  let _quem   = '';      // comprador selecionado
  let _aba    = 'comprar';

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));

  // ---- Memória de "já abriu nesta visita" --------------------------------
  // A tela abre sozinha UMA vez por visita a um local: recarregar a página
  // parado na forja não reabre, mas sair da cidade e voltar reabre. Antes isso
  // vivia numa variável, e um F5 bastava para a loja pular na cara de novo.
  //
  // Fica no localStorage, por campanha. É conveniência de quem está jogando
  // neste navegador, não estado do mundo — não precisa ir ao servidor.
  function campanhaAtual() {
    try { return (JSON.parse(localStorage.getItem('rpg_session') || '{}').campaign) || ''; }
    catch (_) { return ''; }
  }
  const CHAVE_MEMORIA = () => `rpg_telas::${campanhaAtual()}::loja_visita`;
  function visitaVista() {
    try { return localStorage.getItem(CHAVE_MEMORIA()) || ''; } catch (_) { return ''; }
  }
  function marcarVisita(local) {
    try {
      if (local) localStorage.setItem(CHAVE_MEMORIA(), local);
      else localStorage.removeItem(CHAVE_MEMORIA());
    } catch (_) { /* sem storage, a tela só perde a memória entre recargas */ }
  }

  // Nenhuma tela abre sozinha por cima de outra. A fila em game.js já roda
  // combate → nível → loja nessa ordem; esta checagem é o que faz a loja
  // ESPERAR em vez de se empilhar sobre a de nível.
  const OUTRAS_TELAS = ['combat-on', 'levelup-on'];
  const outraTelaAberta = () => OUTRAS_TELAS.some(c => document.body.classList.contains(c));

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (document.getElementById('shop-overlay')) return;
    const o = document.createElement('div');
    o.id = 'shop-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="shp-frame">
        <header class="shp-header">
          <button class="shp-close" onclick="window.Shop._close()"
                  aria-label="Fechar a loja"
                  title="Fechar — a loja continua aberta e pode ser revisitada">✕</button>
          <h1 class="shp-title">O Balcão <span id="shp-nome">—</span></h1>
          <div id="shp-local" class="shp-local"></div>
          <div id="shp-lojas" class="shp-lojas"></div>
        </header>

        <div id="shp-bolsa" class="shp-bolsa"></div>

        <div class="shp-abas" role="tablist">
          <button id="shp-aba-comprar" class="shp-aba" role="tab"
                  onclick="window.Shop._aba('comprar')">Comprar</button>
          <button id="shp-aba-vender" class="shp-aba" role="tab"
                  onclick="window.Shop._aba('vender')">Vender</button>
        </div>

        <div id="shp-lista" class="shp-lista"></div>

        <div class="shp-rodape">
          <div id="shp-msg" class="shp-msg"></div>
          <button class="shp-sair" onclick="window.Shop._sair()">
            Encerrar as compras
          </button>
        </div>
      </div>`;
    document.body.appendChild(o);

    if (!document.getElementById('shp-reopen')) {
      const pill = document.createElement('button');
      pill.id = 'shp-reopen';
      pill.className = 'hidden';
      pill.onclick = () => window.Shop._reabrir();
      document.body.appendChild(pill);
    }
  }

  // ---- Rede --------------------------------------------------------
  async function api(path, opts) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}${path}`, opts || {});
    return r.json();
  }
  function getState() {
    const q = new URLSearchParams();
    if (_loja) q.set('loja', _loja);
    if (_quem) q.set('comprador', _quem);
    const s = q.toString();
    return api('/api/shop/state' + (s ? '?' + s : ''));
  }
  function doAction(p) {
    return api('/api/shop/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }

  // ---- Render ------------------------------------------------------
  function moedas(c) {
    const p = [];
    if (c.ouro)  p.push(`<b>${c.ouro}</b> po`);
    if (c.prata) p.push(`<b>${c.prata}</b> pp`);
    if (c.cobre) p.push(`<b>${c.cobre}</b> pc`);
    return p.length ? p.join(' · ') : '<b>0</b> po';
  }

  function bolsa(snap) {
    const c = snap.comprador;
    const el = document.getElementById('shp-bolsa');
    if (!c) { el.innerHTML = '<span class="shp-vazio">Nenhum personagem no grupo.</span>'; return; }

    const grupo = snap.grupo || [];
    const troca = grupo.length > 1
      ? `<select class="shp-quem" aria-label="Quem está comprando"
                 onchange="window.Shop._quem(this.value)">`
        + grupo.map(n =>
            `<option value="${esc(n)}" ${n === c.nome ? 'selected' : ''}>${esc(n)}</option>`
          ).join('')
        + `</select>`
      : `<span class="shp-quem-fixo">${esc(c.nome)}</span>`;

    // A barra de carga é o motivo de a tela existir: uma cota de malha pesa
    // 20 kg, e isso só vira ESCOLHA se der para ver enquanto se decide.
    const pct = c.capacidade > 0
      ? Math.max(0, Math.min(100, (c.carga / c.capacidade) * 100)) : 0;
    const meio = c.capacidade > 0 ? 50 : 0;
    const cls = c.estado_carga === 'imovel' ? ' shp-carga-imovel'
              : (c.estado_carga === 'sobrecarregado' ? ' shp-carga-cheia' : '');
    const rotulo = c.estado_carga === 'livre' ? 'livre' : c.estado_carga;

    el.innerHTML = `
      <div class="shp-bolsa-quem">${troca}</div>
      <div class="shp-bolsa-moedas">${moedas(c)}</div>
      <div class="shp-carga">
        <div class="shp-carga-topo">
          <span>Carga</span>
          <span class="shp-carga-num">${c.carga} / ${c.capacidade} kg — ${esc(rotulo)}</span>
        </div>
        <div class="shp-carga-barra">
          <div class="shp-carga-fill${cls}" style="width:${pct}%"></div>
          <div class="shp-carga-meio" style="left:${meio}%"
               title="Metade da capacidade: acima daqui, desvantagem"></div>
        </div>
      </div>`;
  }

  function cartaoCompra(i, c) {
    const caro  = c ? (c.bolsa_em_cobre < i.preco * 100) : true;
    const resta = i.ilimitado ? '' : `<span class="shp-resta">restam ${i.qtd}</span>`;
    const selo  = i.custom
      ? `<span class="shp-selo-custom" title="Fora do SRD — item próprio da campanha">próprio da campanha</span>`
      : '';
    const desc = i.descricao
      ? `<div class="shp-desc">${esc(i.descricao)}</div>` : '';
    return `
      <div class="shp-item${caro ? ' shp-item-caro' : ''}">
        <div class="shp-item-cabeca">
          <span class="shp-item-nome">${esc(i.nome)}</span>
          ${selo}${resta}
        </div>
        ${desc}
        <div class="shp-item-linha">
          <span class="shp-preco">${i.preco} po</span>
          <span class="shp-peso">${i.peso} kg</span>
          <button class="shp-btn" ${caro ? 'disabled' : ''}
                  title="${caro ? 'Ouro insuficiente' : 'Comprar 1'}"
                  onclick="window.Shop._comprar('${esc(i.nome).replace(/'/g, "\\'")}', 1)">
            Comprar
          </button>
        </div>
      </div>`;
  }

  function cartaoVenda(i) {
    const selo = i.custom
      ? `<span class="shp-selo-custom" title="Fora do SRD — item próprio da campanha">próprio da campanha</span>`
      : '';
    return `
      <div class="shp-item">
        <div class="shp-item-cabeca">
          <span class="shp-item-nome">${esc(i.nome)}</span>
          ${selo}<span class="shp-resta">você tem ${i.qtd}</span>
        </div>
        <div class="shp-item-linha">
          <span class="shp-preco">${i.ganho} po
            <small title="A loja paga metade da tabela">de ${i.tabela}</small></span>
          <span class="shp-peso">${i.peso} kg</span>
          <button class="shp-btn shp-btn-vender"
                  onclick="window.Shop._vender('${esc(i.nome).replace(/'/g, "\\'")}', 1)">
            Vender
          </button>
        </div>
      </div>`;
  }

  function lista(snap) {
    const el = document.getElementById('shp-lista');
    const c  = snap.comprador;

    if (_aba === 'comprar') {
      const itens = snap.estoque || [];
      el.innerHTML = itens.length
        ? itens.map(i => cartaoCompra(i, c)).join('')
        : `<div class="shp-vazio">A prateleira está vazia.</div>`;
      return;
    }

    const inv = snap.inventario || [];
    el.innerHTML = inv.length
      ? inv.map(cartaoVenda).join('')
      : `<div class="shp-vazio">Nada aqui tem preço de tabela.<br>
           <small>A loja só compra o que sabe avaliar — peça ao mestre para
           pôr o item à venda com um preço.</small></div>`;
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();

    const loja = _last.loja || {};
    document.getElementById('shp-nome').textContent  = loja.nome ? `— ${loja.nome}` : '';
    document.getElementById('shp-local').textContent = loja.local || '';

    // Mais de uma loja neste local: seletor. Sem ele a segunda loja da cidade
    // era inalcançável pela tela.
    const aqui = _last.lojas_aqui || [];
    document.getElementById('shp-lojas').innerHTML = aqui.length > 1
      ? `<select class="shp-loja-sel" aria-label="Loja"
                 onchange="window.Shop._trocarLoja(this.value)">`
        + aqui.map(l => `<option value="${esc(l.chave)}" ${l.chave === loja.chave ? 'selected' : ''}>`
                       + `${esc(l.nome)}</option>`).join('')
        + `</select>`
      : '';

    document.getElementById('shp-aba-comprar')
      .classList.toggle('shp-aba-on', _aba === 'comprar');
    document.getElementById('shp-aba-vender')
      .classList.toggle('shp-aba-on', _aba === 'vender');

    bolsa(_last);
    lista(_last);
  }

  // ---- Sincronia ---------------------------------------------------
  async function sync() {
    try {
      let snap = await getState();
      if (!snap) return;

      // A loja escolhida no seletor pertence ao local ANTERIOR: esquece e
      // pergunta de novo, senão a tela abriria mostrando a forja da outra
      // cidade.
      const aqui = snap.lojas_aqui || [];
      if (_loja && !aqui.some(l => l.chave === _loja)) {
        _loja = '';
        snap = await getState();
        if (!snap) return;
      }

      if (!snap.loja_aqui) {
        // Saiu do local: a próxima chegada é uma visita nova.
        if (visitaVista()) marcarVisita('');
      } else if (snap.local_chave && snap.local_chave !== visitaVista()
                 && !_open && !outraTelaAberta()) {
        // Abre SOZINHA na chegada. Loja é estado que persiste; o gatilho é a
        // VISITA a um local que tem loja, uma vez. Se outra tela estiver
        // aberta, NÃO marca a visita — a fila tenta de novo quando ela fechar.
        marcarVisita(snap.local_chave);
        abrir();
        atualizarPilula(snap);
        return;
      }

      atualizarPilula(snap);
      if (_open) render(snap); else _last = snap;
    } catch (_) { /* a tela de loja nunca derruba o turno */ }
  }

  function atualizarPilula(snap) {
    const pill = document.getElementById('shp-reopen');
    if (!pill) return;
    const loja = (snap.loja || {});
    const aqui = snap.lojas_aqui || [];
    if (snap.loja_aqui && loja.nome && !_open) {
      pill.textContent = aqui.length > 1
        ? `${aqui.length} lojas em ${snap.local_atual || loja.local}`
        : `Loja: ${loja.nome}`;
      pill.classList.remove('hidden');
    } else {
      pill.classList.add('hidden');
    }
  }

  // ---- Abrir / fechar ----------------------------------------------
  function abrir() {
    ensureDom();
    document.getElementById('shop-overlay').classList.remove('hidden');
    document.body.classList.add('shop-on');
    const pill = document.getElementById('shp-reopen');
    if (pill) pill.classList.add('hidden');
    _open = true;
    getState().then(render).catch(() => {});
  }

  function fechar() {
    const el = document.getElementById('shop-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('shop-on');
    _open = false;
    atualizarPilula(_last || {});
    // Avisa a fila: se alguma tela esperava esta fechar, é a vez dela.
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  function mensagem(txt, ok) {
    const el = document.getElementById('shp-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('shp-msg-erro', !ok);
  }

  // ---- Ações --------------------------------------------------------
  async function agir(action, item, qtd) {
    if (_busy) return;
    const c = (_last.comprador || {});
    const loja = (_last.loja || {});
    if (!c.nome || !loja.nome) return;

    _busy = true;
    try {
      const res = await doAction({
        action, shop: loja.nome, char: c.nome, item, quantity: qtd,
      });
      _busy = false;
      if (res) {
        mensagem((res.message || '').split('\n')[0], res.ok !== false);
        if (res.snapshot) render(res.snapshot);
      }
    } catch (_) {
      _busy = false;
      mensagem('Falha de conexão com a loja.', false);
    }
  }

  // Encerrar manda o resumo para a LLM narrar a cena da compra — o mesmo
  // desenho do recap de combate: a tela resolve os números, a narração
  // continua sendo da IA.
  async function sair() {
    const loja = (_last.loja || {}).nome || 'a loja';
    fechar();
    const txt = `[COMPRAS RESOLVIDAS NA TELA] O grupo terminou de negociar em `
              + `${loja}. Narre a saída da loja em uma ou duas frases, sem `
              + `repetir preços nem inventar itens que não foram comprados.`;
    try {
      if (typeof window.sendToAgent === 'function') await window.sendToAgent(txt, true);
    } catch (_) { /* fechar a tela já é o essencial */ }
  }

  // ---- API pública ---------------------------------------------------
  window.Shop = {
    sync,
    _abrir: abrir,
    _close: fechar,
    _reabrir: abrir,
    _sair: sair,
    _aba: (a) => { _aba = a; render(_last); },
    _trocarLoja: (chave) => { _loja = chave; getState().then(render).catch(() => {}); },
    _quem: (n) => { _quem = n; getState().then(render).catch(() => {}); },
    _comprar: (item, q) => agir('buy', item, q),
    _vender:  (item, q) => agir('sell', item, q),
  };

  // Só monta o DOM. Quem chama sync() é a fila de telas do game.js, na ordem
  // combate → nível → loja: um sync() próprio aqui corria em paralelo com o
  // da tela de nível e as duas podiam abrir juntas no carregamento.
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
