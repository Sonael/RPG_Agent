// ═══════════════════════════════════════════════════════════════════
//  relacoes.js — As relações do romance ("Relações")
//
//  No romance o atalho do grupo abre esta tela: como cada pessoa se sente em
//  relação ao protagonista. Dois eixos por pessoa, AFETO e CONFIANÇA, porque o
//  drama mora na diferença entre eles (dá para amar quem não se confia), o
//  VÍNCULO (interesse romântico, amizade, ex, rival) e o porquê das últimas
//  mudanças, com o capítulo. E o ESTÁGIO (conhecidos, amizade, flerte,
//  namoro, compromisso, ou o rompimento) e o último MOMENTO marcante; a linha
//  do tempo inteira fica na ficha, que o nome abre.
//
//  A aba SEGREDOS lista os do protagonista (de quem ele esconde, quem já sabe
//  e como cada um ficou sabendo) e os dos outros que ele já descobriu. Os que
//  ele ainda não sabe nunca chegam aqui: o motor não manda.
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
  let _aba = 'pessoas';

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
          <div id="rel-abas" class="elc-filtros" role="tablist" aria-label="Relações"></div>
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
    return `<span class="rel-ultimo-rotulo">Mudanças</span>
      <ul class="psn-historico rel-historico">${p.historico.map(h => `
      <li><span class="psn-delta ${h.delta >= 0 ? 'psn-sobe' : 'psn-desce'}">${sinal(h.delta)}</span>
          <span class="rel-historico-eixo">${EIXO[h.eixo] || esc(h.eixo)}</span>
          ${esc(h.motivo)}${h.capitulo ? ` <small>cap. ${esc(h.capitulo)}</small>` : ''}</li>`).join('')}</ul>${resto}`;
  }

  function cartao(p) {
    const status = (p.status || '').toLowerCase();
    const marcas = [
      p.vinculo ? `<span class="lcl-marca rel-vinculo">${esc(p.vinculo)}</span>` : '',
      // "próxima" supunha o gênero de todo mundo; o círculo é de todos.
      p.proximo ? '<span class="lcl-marca lcl-marca-grupo">seu círculo</span>' : '',
      status && status !== 'vivo' ? `<span class="lcl-marca">${esc(p.status)}</span>` : '',
    ].join('');
    return `
      <article class="lcl-item rel-cartao" data-nome="${esc(p.nome)}">
        <div class="lcl-item-cabeca">
          <button class="rel-nome" type="button" onclick="window.Relacoes._ver('${aspas(p.nome)}')"
                  title="Abrir a ficha de ${esc(p.nome)}">${esc(p.nome)}</button>${marcas}
        </div>
        ${window.escadaDaRelacao(p.estagio)}
        ${window.encontrosDaPessoa(p.encontros)}
        ${medidor('afeto', 'Afeto', p.afeto, ['aversão', 'devoção'])}
        ${medidor('confianca', 'Confiança', p.confianca, ['desconfia', 'confia'])}
        ${(p.momentos || []).length ? `
          <div class="rel-ultimo">
            <span class="rel-ultimo-rotulo">Último momento${p.momentos.length > 1 ? ` de ${p.momentos.length}` : ''}</span>
            ${window.linhaDoTempo(p.momentos, 1)}
          </div>` : ''}
        ${window.segredosDaPessoa(p.segredos)}
        ${historico(p)}
      </article>`;
  }

  // ---- Segredos ----------------------------------------------------
  const COMO = { contou: 'contou', descobriu: 'descobriu' };

  function segredoSeu(s) {
    const hist = (s.historico || []).map(h => `
      <li>${esc(h.quem)} ${h.acao === 'contou' ? '— você contou' : 'descobriu'}${
        h.capitulo ? ` <small>cap. ${esc(h.capitulo)}</small>` : ''}</li>`).join('');
    return `
      <article class="lcl-item rel-segredo${s.escondido_de.length ? ' rel-segredo-escondido' : ''}" data-titulo="${esc(s.titulo)}">
        <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(s.titulo)}</span></div>
        ${s.descricao ? `<p class="lcl-item-desc">${esc(s.descricao)}</p>` : ''}
        ${s.escondido_de.length ? `<p class="rel-seg-linha rel-seg-esconde"><span>Escondido de</span> ${esc(s.escondido_de.join(', '))}</p>` : ''}
        <p class="rel-seg-linha"><span>Sabem</span> ${s.sabem.length ? esc(s.sabem.join(', ')) : 'ninguém além de você'}</p>
        ${hist ? `<ul class="rel-seg-historico">${hist}</ul>` : ''}
      </article>`;
  }

  function segredoDeOutro(s) {
    const como = s.como === 'contou'
      ? `${esc(s.dono)} contou a você`
      : `você descobriu${s.dono_sabe ? '' : ` — ${esc(s.dono)} não sabe que você sabe`}`;
    return `
      <article class="lcl-item rel-segredo" data-titulo="${esc(s.titulo)}">
        <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(s.titulo)}</span>
          <span class="lcl-marca">de ${esc(s.dono)}</span></div>
        ${s.descricao ? `<p class="lcl-item-desc">${esc(s.descricao)}</p>` : ''}
        <p class="rel-seg-linha${s.dono_sabe ? '' : ' rel-seg-esconde'}">${como}${
          s.capitulo ? ` <small>cap. ${esc(s.capitulo)}</small>` : ''}</p>
      </article>`;
  }

  function listaDeSegredos() {
    const sg = _last.segredos || { seus: [], dos_outros: [] };
    const seus = sg.seus.length ? sg.seus.map(segredoSeu).join('')
      : '<div class="lcl-vazio">Você não guarda nenhum segredo. Ainda.</div>';
    const outros = sg.dos_outros.length ? sg.dos_outros.map(segredoDeOutro).join('')
      : '<div class="lcl-vazio">Você não descobriu o segredo de ninguém.</div>';
    return `
      <section class="rel-segredos-grupo"><h2 class="lcl-secao">Os seus</h2><div class="rel-segredos-lista">${seus}</div></section>
      <section class="rel-segredos-grupo"><h2 class="lcl-secao">Os dos outros, que você já sabe</h2><div class="rel-segredos-lista">${outros}</div></section>`;
  }

  function render(d) {
    _last = d || {};
    ensureDom();
    const quem = _last.protagonista;
    q('rel-sub').textContent = quem
      ? `Como cada pessoa se sente em relação a ${quem}.`
      : 'Como cada pessoa se sente em relação a você.';
    const pessoas = _last.pessoas || [];
    const sg = _last.segredos || { seus: [], dos_outros: [] };
    const nSegredos = sg.seus.length + sg.dos_outros.length;
    q('rel-abas').innerHTML = [['pessoas', 'Pessoas', pessoas.length], ['segredos', 'Segredos', nSegredos]]
      .map(([id, rotulo, n]) => `
        <button class="elc-filtro${id === _aba ? ' elc-filtro-ativo' : ''}" data-aba="${id}" role="tab"
                aria-selected="${id === _aba}" onclick="window.Relacoes._aba('${id}')">
          ${rotulo} <span class="elc-filtro-conta">${n}</span></button>`).join('');
    q('rel-lista').classList.toggle('rel-lista-segredos', _aba === 'segredos');
    if (_aba === 'segredos') {
      q('rel-lista').innerHTML = listaDeSegredos();
      return;
    }
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
  async function abrir(aba) {
    ensureDom();
    _aba = aba === 'segredos' ? 'segredos' : 'pessoas';
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
    _aba: (aba) => { _aba = aba; render(_last); },
    _estado: () => _last,
  };
})();
