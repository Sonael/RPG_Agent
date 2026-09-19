// ═══════════════════════════════════════════════════════════════════
//  personagens.js — Ficha do personagem
//
//  Abre ao clicar num personagem da Enciclopédia ou em "Quem está aqui" na
//  ficha do local. Mostra quem é, onde está, a relação com o grupo (a
//  atitude e o porquê de cada mudança), o que o grupo sabe sobre ele e as
//  ligações com a história (missões que deu, eventos em que aparece, a loja
//  onde trabalha).
//
//  As notas do mestre NÃO aparecem aqui: são o caderno dele, com segredos.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo aqui. A
//  faixa da atitude, o alcance e o que conta como ligação vêm do motor
//  (rpg/personagens.py via /api/characters/sheet). A moldura e as classes são
//  as da ficha do local (lcl-*), para as duas fichas lerem igual.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _last = {};

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");

  function ensureDom() {
    if (q('pessoa-overlay')) return;
    const o = document.createElement('div');
    o.id = 'pessoa-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="psn-frame" role="dialog" aria-modal="true" aria-labelledby="psn-nome">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Personagens._fechar()"
                  aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="lcl-title"><span id="psn-nome">—</span> <span id="psn-status" class="lcl-tipo"></span></h1>
          <div id="psn-onde" class="lcl-selo"></div>
          <p id="psn-desc" class="lcl-desc"></p>
          <p id="psn-tracos" class="lcl-desc psn-tracos"></p>
        </header>

        <div class="lcl-corpo">
          <section class="lcl-corpo-pessoas" aria-label="Relação e o que o grupo sabe">
            <div id="psn-relacao-bloco">
              <h2 class="lcl-secao" id="psn-relacao-titulo">Relação com o grupo</h2>
              <div id="psn-relacao"></div>
            </div>
            <h2 class="lcl-secao psn-secao-sabe">O que o grupo sabe</h2>
            <div id="psn-sabe" class="lcl-lista"></div>
            <h2 class="lcl-secao psn-secao-sabe" id="psn-cenas-titulo">Últimas cenas com ele</h2>
            <div id="psn-cenas" class="lcl-lista"></div>
          </section>
          <section class="lcl-corpo-dentro" aria-label="Ligações">
            <h2 class="lcl-secao">Ligações</h2>
            <div id="psn-ligacoes" class="lcl-lista"></div>
          </section>
        </div>

        <div class="lcl-rodape">
          <div id="psn-msg" class="lcl-msg" aria-live="polite"></div>
          <button id="psn-editar" class="lcl-btn lcl-btn-sec hidden"
                  onclick="window.Personagens._editar()">Editar personagem</button>
          <button class="lcl-fechar" onclick="window.Personagens._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  async function getState(nome) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}/api/characters/sheet?nome=${encodeURIComponent(nome || '')}`);
    return r.json();
  }

  // ---- Render ------------------------------------------------------
  function onde(f) {
    const partes = [];
    if (f.do_grupo) partes.push('<span class="lcl-selo-texto lcl-alcance-aqui">Do grupo</span>');
    if (f.local && f.local.nome) {
      partes.push(`<span class="psn-em">Em <a href="#" class="lcl-migalha"
        onclick="event.preventDefault();window.Personagens._verLocal('${aspas(f.local.nome)}')">${esc(f.local.nome)}</a></span>`);
      if (!f.do_grupo && f.local.alcance && f.local.alcance !== 'aqui') {
        partes.push(`<button class="lcl-btn lcl-btn-ir" onclick="window.Personagens._ir('${aspas(f.local.nome)}')"
          title="Manda ao mestre: Vamos até ${esc(f.local.nome)}.">Ir até onde está</button>`);
      }
    } else if (!f.do_grupo) {
      partes.push('<span class="psn-em">Paradeiro desconhecido</span>');
    }
    if (!f.do_grupo) {
      partes.push(f.pode_falar
        ? `<button class="lcl-btn lcl-btn-ir" onclick="window.Personagens._falar('${aspas(f.nome)}')"
            title="Manda ao mestre: Quero falar com ${esc(f.nome)}.">Falar com</button>`
        : `<button class="lcl-btn" disabled title="${(f.status || '').toLowerCase() === 'morto'
            ? 'Não está mais entre os vivos' : 'Longe do grupo: vá até lá primeiro'}">Falar com</button>`);
    }
    return partes.join('');
  }

  function relacao(a) {
    if (!a) return '';
    // -100..100 vira 0..100% na barra; o marcador do meio é o neutro.
    const pos = Math.max(0, Math.min(100, (a.valor + 100) / 2));
    const hist = (a.historico || []).length
      ? `<ul class="psn-historico">${a.historico.map(h => `
          <li><span class="psn-delta ${h.delta >= 0 ? 'psn-sobe' : 'psn-desce'}">${h.delta >= 0 ? '+' : ''}${h.delta}</span>
              ${esc(h.motivo)}${h.capitulo ? ` <small>cap. ${esc(h.capitulo)}</small>` : ''}</li>`).join('')}</ul>`
      : '<div class="lcl-vazio">Nenhuma mudança registrada ainda.</div>';
    return `
      <div class="psn-atitude psn-faixa-${esc(a.rotulo)}">
        <div class="psn-atitude-topo">
          <span class="psn-atitude-rotulo">${esc(a.rotulo)}</span>
          <span class="psn-atitude-valor">${a.valor >= 0 ? '+' : ''}${a.valor}</span>
        </div>
        <div class="psn-barra" role="img" aria-label="Atitude ${a.valor} de -100 a 100">
          <div class="psn-barra-meio"></div>
          <div class="psn-barra-marca" style="left:${pos}%"></div>
        </div>
        <div class="psn-barra-pontas"><span>hostil</span><span>leal</span></div>
        <p class="psn-conduta">${esc(a.conduta)}.</p>
        ${(a.efeitos || []).length ? `<ul class="psn-efeitos">${
          a.efeitos.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : ''}
      </div>
      ${hist}`;
  }

  // No romance: afeto e confiança, o vínculo e o porquê das últimas mudanças,
  // com as mesmas barras da atitude. Vale também para quem é do grupo.
  function relacaoDoRomance(r) {
    const barra = (rotulo, eixo, pontas) => {
      const pos = Math.max(0, Math.min(100, (eixo.valor + 100) / 2));
      return `
        <div class="psn-atitude psn-romance${eixo.valor < 0 ? ' psn-romance-negativo' : ''}">
          <div class="psn-atitude-topo">
            <span class="psn-atitude-rotulo">${rotulo}: ${esc(eixo.rotulo)}</span>
            <span class="psn-atitude-valor">${eixo.valor >= 0 ? '+' : ''}${eixo.valor}</span>
          </div>
          <div class="psn-barra" role="img" aria-label="${rotulo} ${eixo.valor} de -100 a 100">
            <div class="psn-barra-meio"></div>
            <div class="psn-barra-marca" style="left:${pos}%"></div>
          </div>
          <div class="psn-barra-pontas"><span>${pontas[0]}</span><span>${pontas[1]}</span></div>
        </div>`;
    };
    const eixo = { afeto: 'afeto', confianca: 'confiança' };
    const hist = (r.historico || []).length
      ? `<ul class="psn-historico">${r.historico.map(h => `
          <li><span class="psn-delta ${h.delta >= 0 ? 'psn-sobe' : 'psn-desce'}">${h.delta >= 0 ? '+' : ''}${h.delta}</span>
              <span class="rel-historico-eixo">${eixo[h.eixo] || esc(h.eixo)}</span>
              ${esc(h.motivo)}${h.capitulo ? ` <small>cap. ${esc(h.capitulo)}</small>` : ''}</li>`).join('')}</ul>`
      : '<div class="lcl-vazio">Nada mudou entre vocês ainda.</div>';
    return `${r.vinculo ? `<p class="psn-vinculo">${esc(r.vinculo)}</p>` : ''}
      ${barra('Afeto', r.afeto, ['aversão', 'devoção'])}
      ${barra('Confiança', r.confianca, ['desconfia', 'confia'])}
      ${hist}`;
  }

  // As cenas em que ele aparece, da mais recente para trás: é o que o jogador
  // quer lembrar antes de falar com alguém ("o que a gente fez com ele mesmo?").
  function cenas(f) {
    const lista = f.eventos || [];
    if (!lista.length) return '<div class="lcl-vazio">Nenhuma cena registrada ainda.</div>';
    const total = f.encontros || lista.length;
    const rodape = total > lista.length
      ? `<p class="psn-cenas-total">As ${lista.length} mais recentes de ${total}.</p>` : '';
    return `<ul class="psn-cenas-lista">${lista.map(e => `
      <li>
        <div class="psn-cena-topo">
          ${e.capitulo ? `<span class="psn-cena-cap">cap. ${esc(e.capitulo)}</span>` : ''}
          ${e.local ? `<span class="psn-cena-local">${esc(e.local)}</span>` : ''}
        </div>
        <p class="psn-cena-resumo">${esc(e.resumo)}</p>
        ${e.consequencia ? `<p class="psn-cena-conseq">${esc(e.consequencia)}</p>` : ''}
      </li>`).join('')}</ul>${rodape}`;
  }

  function ligacoes(f) {
    const itens = [];
    if (f.loja) {
      const l = f.loja;
      // O estoque aqui evita a viagem até a tela da loja, que só abre no
      // local dela. O preço já é o que ele vai cobrar deste grupo.
      const estoque = (l.estoque || []).length
        ? `<ul class="psn-estoque">${l.estoque.map(i => `
            <li><span class="psn-estoque-nome">${esc(i.nome)}</span>
                <span class="psn-estoque-preco">${i.preco} po${
                  i.preco !== i.tabela ? ` <small>(tabela ${i.tabela})</small>` : ''}</span>
                ${i.qtd < 99 ? `<span class="psn-estoque-qtd">${i.qtd}x</span>` : ''}</li>`).join('')}</ul>`
        : '<p class="lcl-item-desc">Sem estoque aberto.</p>';
      itens.push(`<div class="lcl-item"><div class="lcl-item-cabeca"><span class="lcl-marca lcl-marca-loja">loja</span>
        <span class="lcl-item-nome">${l.dono ? 'Atende em' : 'Trabalha em'} ${esc(l.nome)}</span></div>
        ${estoque}
        <div class="lcl-item-acoes"><button class="lcl-btn lcl-btn-sec"
          onclick="window.Personagens._verLocal('${aspas(l.local || l.nome)}')">Ver o lugar</button></div></div>`);
    }
    (f.missoes || []).forEach(m => itens.push(`
      <div class="lcl-item"><div class="lcl-item-cabeca"><span class="lcl-marca">missão</span>
        <span class="lcl-item-nome">${esc(m.titulo)}</span>
        ${m.status ? `<span class="lcl-marca">${esc(m.status)}</span>` : ''}</div>
        <p class="lcl-item-desc">Encomendada por ${esc(f.nome)}.</p></div>`));
    return itens.length ? itens.join('') : '<div class="lcl-vazio">Nenhuma ligação registrada ainda.</div>';
  }

  function render(f) {
    _last = f || {};
    ensureDom();
    if (!_last.existe) {
      q('psn-nome').textContent = _last.nome || 'Personagem';
      q('psn-status').textContent = '';
      q('psn-onde').innerHTML = '';
      q('psn-desc').textContent = 'Este personagem ainda não foi registrado pelo mestre.';
      q('psn-tracos').textContent = '';
      q('psn-relacao-bloco').classList.add('hidden');
      q('psn-sabe').innerHTML = '';
      q('psn-cenas').innerHTML = '';
      q('psn-ligacoes').innerHTML = '';
      q('psn-editar').classList.add('hidden');
      return;
    }
    q('psn-nome').textContent = _last.nome;
    const status = (_last.status || '').toLowerCase();
    q('psn-status').textContent = status && status !== 'vivo' ? `— ${_last.status}` : '';
    q('psn-onde').innerHTML = onde(_last);
    q('psn-desc').textContent = _last.descricao || '';
    q('psn-tracos').textContent = _last.tracos ? `Traços: ${_last.tracos}` : '';
    q('psn-relacao-bloco').classList.toggle('hidden', !_last.atitude && !_last.relacao);
    q('psn-relacao-titulo').textContent = _last.relacao ? 'Relação com você' : 'Relação com o grupo';
    q('psn-relacao').innerHTML = _last.relacao ? relacaoDoRomance(_last.relacao) : relacao(_last.atitude);
    const sabe = _last.conhecido || [];
    q('psn-sabe').innerHTML = sabe.length
      ? `<ul class="psn-sabe-lista">${sabe.map(s => `<li>${esc(s)}</li>`).join('')}</ul>`
      : '<div class="lcl-vazio">Nada registrado ainda.</div>';
    q('psn-cenas').innerHTML = cenas(_last);
    q('psn-ligacoes').innerHTML = ligacoes(_last);
    q('psn-editar').classList.remove('hidden');
    mensagem('');
  }

  function mensagem(txt, erro) {
    const el = q('psn-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  async function abrir(nome) {
    ensureDom();
    if (window.Locais && typeof window.Locais._fechar === 'function'
        && document.body.classList.contains('local-on')) {
      window.Locais._fechar();
    }
    if (!_open) {
      q('pessoa-overlay').classList.remove('hidden');
      document.body.classList.add('pessoa-on');
      _open = true;
    }
    mensagem('Carregando…');
    try {
      render(await getState(nome));
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  function fechar() {
    const el = q('pessoa-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('pessoa-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  // Mesma fala comum do jogador da ficha do local: quem decide é o mestre.
  function enviar(texto) {
    if (typeof waiting !== 'undefined' && waiting) {
      mensagem('Aguarde o mestre terminar de responder.', true);
      return;
    }
    if (typeof window.sendToAgent !== 'function' || typeof window.appendUser !== 'function') return;
    fechar();
    window.appendUser(texto);
    window.sendToAgent(texto, true);
  }

  function editar() {
    const mem = window._lastMem || {};
    const alvo = (_last.nome || '').toLowerCase();
    const lista = _last.do_grupo ? (mem.party || []) : (mem.characters || []);
    const i = lista.findIndex(c => (c.name || '').toLowerCase() === alvo);
    if (i < 0 || typeof window.openEditModal !== 'function') return;
    fechar();
    window.openEditModal('character', alvo, lista[i]);
  }

  window.Personagens = {
    _abrir: abrir,
    _fechar: fechar,
    _ir: (lugar) => enviar(`Vamos até ${lugar}.`),
    _falar: (nome) => enviar(`Quero falar com ${nome}.`),
    _verLocal: (lugar) => { fechar(); if (window.Locais) window.Locais._abrir(lugar); },
    _editar: editar,
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
