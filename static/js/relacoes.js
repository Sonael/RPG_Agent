// ═══════════════════════════════════════════════════════════════════
//  relacoes.js — As relações do romance ("Relações")
//
//  No romance o atalho do grupo abre esta tela: como cada pessoa se sente em
//  relação ao protagonista. Dois eixos por pessoa, AFETO e CONFIANÇA, porque o
//  drama mora na diferença entre eles (dá para amar quem não se confia), o
//  VÍNCULO (interesse romântico, amizade, ex, rival) e o porquê das últimas
//  mudanças, com o capítulo.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra aqui. As faixas
//  ("devoção", "com um pé atrás"), a ordem e quem entra na lista vêm do motor
//  (rpg/relacoes.py via /api/relacoes). A moldura e as classes são as das
//  fichas (lcl-*), e as barras são as da atitude na ficha do personagem.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _last = {};

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");
  const sinal = (n) => `${n >= 0 ? '+' : ''}${n}`;
  const EIXO = { afeto: 'afeto', confianca: 'confiança' };

  function ensureDom() {
    if (q('relacoes-overlay')) return;
    const o = document.createElement('div');
    o.id = 'relacoes-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="rel-frame" role="dialog" aria-modal="true" aria-labelledby="rel-titulo">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Relacoes._fechar()" aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="lcl-title" id="rel-titulo">Relações</h1>
          <p id="rel-sub" class="lcl-desc"></p>
        </header>
        <div class="rel-corpo">
          <div id="rel-lista" class="rel-lista"></div>
        </div>
        <div class="lcl-rodape">
          <div id="rel-msg" class="lcl-msg" aria-live="polite"></div>
          <button class="lcl-fechar" onclick="window.Relacoes._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  async function getState() {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}/api/relacoes`);
    return r.json();
  }

  // ---- Render ------------------------------------------------------
  // -100..100 vira 0..100% na barra; o traço do meio é o neutro.
  function medidor(id, rotulo, eixo, pontas) {
    const pos = Math.max(0, Math.min(100, (eixo.valor + 100) / 2));
    return `
      <div class="rel-medidor rel-${id}${eixo.valor < 0 ? ' rel-negativo' : ''}">
        <div class="rel-medidor-topo">
          <span class="rel-eixo">${rotulo}</span>
          <span class="rel-faixa">${esc(eixo.rotulo)}</span>
          <span class="rel-valor">${sinal(eixo.valor)}</span>
        </div>
        <div class="psn-barra rel-barra" role="img" aria-label="${rotulo} ${eixo.valor} de -100 a 100">
          <div class="psn-barra-meio"></div>
          <div class="psn-barra-marca" style="left:${pos}%"></div>
        </div>
        <div class="psn-barra-pontas"><span>${pontas[0]}</span><span>${pontas[1]}</span></div>
      </div>`;
  }

  function historico(p) {
    if (!(p.historico || []).length) return '<p class="rel-sem-historia">Nada mudou entre vocês ainda.</p>';
    const resto = p.mudancas > p.historico.length ? `<p class="psn-cenas-total">As ${p.historico.length} mais recentes de ${p.mudancas}.</p>` : '';
    return `<ul class="psn-historico rel-historico">${p.historico.map(h => `
      <li><span class="psn-delta ${h.delta >= 0 ? 'psn-sobe' : 'psn-desce'}">${sinal(h.delta)}</span>
          <span class="rel-historico-eixo">${EIXO[h.eixo] || esc(h.eixo)}</span>
          ${esc(h.motivo)}${h.capitulo ? ` <small>cap. ${esc(h.capitulo)}</small>` : ''}</li>`).join('')}</ul>${resto}`;
  }

  function cartao(p) {
    const status = (p.status || '').toLowerCase();
    const marcas = [
      p.vinculo ? `<span class="lcl-marca rel-vinculo">${esc(p.vinculo)}</span>` : '',
      p.proximo ? '<span class="lcl-marca lcl-marca-grupo">próxima</span>' : '',
      status && status !== 'vivo' ? `<span class="lcl-marca">${esc(p.status)}</span>` : '',
    ].join('');
    return `
      <article class="lcl-item rel-cartao" data-nome="${esc(p.nome)}">
        <div class="lcl-item-cabeca">
          <button class="rel-nome" type="button" onclick="window.Relacoes._ver('${aspas(p.nome)}')"
                  title="Abrir a ficha de ${esc(p.nome)}">${esc(p.nome)}</button>${marcas}
        </div>
        ${medidor('afeto', 'Afeto', p.afeto, ['aversão', 'devoção'])}
        ${medidor('confianca', 'Confiança', p.confianca, ['desconfia', 'confia'])}
        ${historico(p)}
      </article>`;
  }

  function render(d) {
    _last = d || {};
    ensureDom();
    const quem = _last.protagonista;
    q('rel-sub').textContent = quem
      ? `Como cada pessoa se sente em relação a ${quem}.`
      : 'Como cada pessoa se sente em relação a você.';
    const pessoas = _last.pessoas || [];
    q('rel-lista').innerHTML = pessoas.length
      ? pessoas.map(cartao).join('')
      : `<div class="lcl-vazio">Ninguém marcou você ainda. Quando algo mudar entre você e alguém,
           o mestre registra aqui, com o porquê.</div>`;
  }

  function mensagem(txt, erro) {
    const el = q('rel-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  // ---- Abrir / fechar ----------------------------------------------
  async function abrir() {
    ensureDom();
    if (!_open) {
      q('relacoes-overlay').classList.remove('hidden');
      document.body.classList.add('relacoes-on');
      _open = true;
    }
    mensagem('Carregando…');
    try {
      render(await getState());
      mensagem('');
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  function fechar() {
    const el = q('relacoes-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('relacoes-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  // Depois de cada turno: o mestre pode ter acabado de mexer numa relação.
  async function sync() {
    if (!_open) return;
    try { render(await getState()); } catch (_) { /* nunca derruba o turno */ }
  }

  function ver(nome) {
    fechar();
    if (window.Personagens) window.Personagens._abrir(nome);
  }

  window.Relacoes = {
    sync,
    _abrir: abrir,
    _fechar: fechar,
    _ver: ver,
    _estado: () => _last,
  };
})();
