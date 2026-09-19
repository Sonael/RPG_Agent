// ═══════════════════════════════════════════════════════════════════
//  mundo.js — O Mundo (fantasia e dark fantasy)
//
//  O que a fantasia tem e o D&D não mede: o mundo reagindo ao que os heróis
//  fazem e os companheiros como pessoas. Cinco abas:
//
//  • RENOME: a fama do grupo, as facções (reinos, guildas, ordens) com a
//    reputação e o porquê, e os títulos que o mundo deu a cada um;
//  • COMPANHEIROS: lealdade, objetivo e o arco pessoal de cada um;
//  • LENDAS: profecias, artefatos perdidos e mistérios, em fragmentos;
//  • BESTIÁRIO: o que o grupo sabe de cada criatura, fraquezas à parte;
//  • MUDANÇAS: como os lugares mudaram pelo que o grupo fez.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra aqui. As faixas, a
//  ordem e o que o grupo já sabe vêm do motor (rpg/mundo.py via
//  /api/mundo). A verdade das lendas e a facção que o grupo não conhece
//  nunca chegam aqui.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _last = {};
  let _aba = 'renome';

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");
  const sinal = (n) => `${n >= 0 ? '+' : ''}${n}`;
  const cap = (c) => (c ? ` <small>cap. ${esc(c)}</small>` : '');

  const ABAS = [
    ['renome', 'Renome'], ['companheiros', 'Companheiros'], ['lendas', 'Lendas'],
    ['bestiario', 'Bestiário'], ['mudancas', 'Mudanças'],
  ];

  function ensureDom() {
    if (q('mundo-overlay')) return;
    const o = document.createElement('div');
    o.id = 'mundo-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="mnd-frame" role="dialog" aria-modal="true" aria-labelledby="mnd-titulo">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Mundo._fechar()" aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="lcl-title" id="mnd-titulo">O Mundo</h1>
          <p class="lcl-desc">O que o mundo sabe do grupo, e o que o grupo sabe do mundo.</p>
          <div id="mnd-abas" class="elc-filtros" role="tablist" aria-label="O Mundo"></div>
        </header>
        <div class="rel-corpo">
          <div id="mnd-lista" class="mnd-lista"></div>
        </div>
        <div class="lcl-rodape">
          <div id="mnd-msg" class="lcl-msg" aria-live="polite"></div>
          <button class="lcl-fechar" onclick="window.Mundo._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  async function getState() {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}/api/mundo`);
    return r.json();
  }

  // ---- Peças -------------------------------------------------------
  // -100..100 vira 0..100% na barra; o traço do meio é o neutro.
  // `chave` liga a marca a animarNumeros (utils.js): ela desliza de onde estava.
  function barraCentrada(valor, rotulo, pontas, chave) {
    const pos = Math.max(0, Math.min(100, (valor + 100) / 2));
    return `
      <div class="psn-barra" role="img" aria-label="${rotulo} ${valor} de -100 a 100">
        <div class="psn-barra-meio"></div><div class="psn-barra-marca" data-barra="${esc(chave)}" data-prop="left"
             style="left:${pos}%"></div></div>
      <div class="psn-barra-pontas"><span>${pontas[0]}</span><span>${pontas[1]}</span></div>`;
  }

  function historico(lista) {
    if (!(lista || []).length) return '';
    return `<ul class="psn-historico rel-historico">${lista.map(h => `
      <li><span class="psn-delta ${h.delta >= 0 ? 'psn-sobe' : 'psn-desce'}">${sinal(h.delta)}</span>
        ${esc(h.motivo)}${cap(h.capitulo)}</li>`).join('')}</ul>`;
  }

  const vazio = (txt) => `<div class="lcl-vazio">${txt}</div>`;
  const grade = (html) => `<div class="rel-segredos-lista">${html}</div>`;
  const secao = (titulo, html) => `<section class="rel-segredos-grupo"><h2 class="lcl-secao">${titulo}</h2>${html}</section>`;

  // ---- Renome ------------------------------------------------------
  function abaRenome() {
    const r = _last.renome || { valor: 0, faixa: 'desconhecidos', historico: [] };
    const fama = `
      <article class="lcl-item mnd-renome">
        <div class="rel-medidor-topo"><span class="rel-eixo">Renome</span>
          <span class="rel-faixa">${esc(r.faixa)}</span><span class="rel-valor" data-num="mnd:renome">${r.valor}</span></div>
        <div class="rel-intensidade mnd-fama" role="img" aria-label="Renome ${r.valor} de 100">
          <span data-barra="mnd:renome" style="width:${Math.max(0, Math.min(100, r.valor))}%"></span></div>
        ${historico(r.historico)}
      </article>`;
    const faccoes = (_last.faccoes || []).map(f => `
      <article class="lcl-item mnd-faccao${f.reputacao < 0 ? ' mnd-negativa' : ''}" data-nome="${esc(f.nome)}">
        <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(f.nome)}</span>
          <span class="lcl-marca">${esc(f.tipo)}</span></div>
        ${f.descricao ? `<p class="lcl-item-desc">${esc(f.descricao)}</p>` : ''}
        <div class="rel-medidor-topo"><span class="rel-faixa">${esc(f.faixa)}</span>
          <span class="rel-valor" data-num="${esc(`mnd:fac:${f.nome}`)}">${sinal(f.reputacao)}</span></div>
        ${barraCentrada(f.reputacao, 'Reputação', ['inimigos', 'heróis'], `mnd:fac:${f.nome}`)}
        ${historico(f.historico)}
      </article>`).join('');
    const titulos = (_last.titulos || []).map(t => `
      <article class="lcl-item mnd-titulo-item" data-titulo="${esc(t.titulo)}" data-novo="${esc(`tit:${t.quem}:${t.titulo}`)}">
        <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(t.titulo)}</span>
          <span class="lcl-marca">${esc(t.quem)}</span></div>
        ${t.motivo ? `<p class="lcl-item-desc">${esc(t.motivo)}${cap(t.capitulo)}</p>` : ''}
        ${t.efeito ? `<p class="rel-seg-linha"><span>Efeito</span> ${esc(t.efeito)}</p>` : ''}
      </article>`).join('');
    return secao('A fama do grupo', grade(fama))
      + secao('Facções', faccoes ? grade(faccoes) : vazio('Nenhuma facção conhece o grupo ainda.'))
      + secao('Títulos', titulos ? grade(titulos) : vazio('O mundo ainda não deu nenhum título a vocês.'));
  }

  // ---- Companheiros -----------------------------------------------
  function abaCompanheiros() {
    const lista = _last.companheiros || [];
    if (!lista.length) return vazio('Nenhum companheiro com laço registrado ainda.');
    return grade(lista.map(c => {
      const arco = c.arco ? `
        <div class="mnd-arco${c.arco.estado !== 'em curso' ? ' mnd-arco-fim' : ''}">
          <p class="rel-seg-linha"><span>Arco</span> ${esc(c.arco.titulo)} <em>(${esc(c.arco.estado)})</em></p>
          ${c.arco.passos.length ? `<ol class="rel-momentos">${c.arco.passos.map(p => `
            <li class="rel-momento"><span class="rel-momento-titulo">${esc(p.texto)}</span>${cap(p.capitulo)}</li>`).join('')}</ol>` : ''}
        </div>` : '';
      return `
        <article class="lcl-item mnd-companheiro${c.lealdade.valor <= -50 ? ' mnd-negativa' : ''}" data-nome="${esc(c.nome)}">
          <div class="lcl-item-cabeca"><button class="rel-nome" type="button"
            onclick="window.Mundo._ver('${aspas(c.nome)}')">${esc(c.nome)}</button></div>
          <div class="rel-medidor-topo"><span class="rel-eixo">Lealdade</span>
            <span class="rel-faixa">${esc(c.lealdade.faixa)}</span><span class="rel-valor" data-num="${esc(`mnd:leal:${c.nome}`)}">${sinal(c.lealdade.valor)}</span></div>
          ${barraCentrada(c.lealdade.valor, 'Lealdade', ['partir', 'até o fim'], `mnd:leal:${c.nome}`)}
          ${c.objetivo ? `<p class="rel-seg-linha"><span>Quer</span> ${esc(c.objetivo)}</p>` : ''}
          ${arco}
          ${historico(c.historico)}
        </article>`;
    }).join(''));
  }

  // ---- Lendas ------------------------------------------------------
  function abaLendas() {
    const lista = _last.lendas || [];
    if (!lista.length) return vazio('O grupo ainda não ouviu nenhuma lenda.');
    return grade(lista.map(l => `
      <article class="lcl-item mnd-lenda${l.desfecho ? ' mnd-lenda-resolvida' : ''}" data-titulo="${esc(l.titulo)}"
               data-novo="${esc(`lenda:${l.titulo}`)}">
        <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(l.titulo)}</span>
          <span class="lcl-marca">${esc(l.tipo)}</span>
          ${l.desfecho ? '<span class="lcl-marca lcl-marca-grupo">resolvida</span>' : ''}</div>
        ${l.fragmentos.length ? `<ol class="rel-momentos">${l.fragmentos.map(f => `
          <li class="rel-momento" data-novo="${esc(`frag:${l.titulo}:${f.texto}`)}"><span class="rel-momento-desc">${esc(f.texto)}</span>
            ${f.fonte ? `<small class="rel-momento-cap">${esc(f.fonte)}</small>` : ''}${cap(f.capitulo)}</li>`).join('')}</ol>` : ''}
        ${l.desfecho ? `<p class="rel-seg-linha mnd-desfecho"><span>Desfecho</span> ${esc(l.desfecho)}${cap(l.capitulo_desfecho)}</p>` : ''}
      </article>`).join(''));
  }

  // ---- Bestiário ---------------------------------------------------
  function abaBestiario() {
    const lista = _last.bestiario || [];
    if (!lista.length) return vazio('Nenhuma criatura no bestiário ainda.');
    return grade(lista.map(c => `
      <article class="lcl-item mnd-criatura" data-nome="${esc(c.nome)}">
        <div class="lcl-item-cabeca"><span class="lcl-item-nome">${esc(c.nome)}</span>
          ${c.tipo ? `<span class="lcl-marca">${esc(c.tipo)}</span>` : ''}</div>
        ${c.descricao ? `<p class="lcl-item-desc">${esc(c.descricao)}</p>` : ''}
        <p class="rel-seg-linha"><span>Encontros</span> ${c.encontros} · <span>derrotadas</span> ${c.derrotadas}</p>
        ${c.fraquezas.length ? `<ul class="rel-segs">${c.fraquezas.map(f =>
          `<li class="rel-seg rel-seg-sabe"><span>Fraqueza</span> ${esc(f)}</li>`).join('')}</ul>` : ''}
        ${c.fatos.length ? `<ul class="rel-segs">${c.fatos.map(f =>
          `<li class="rel-seg"><span>Sabe-se</span> ${esc(f)}</li>`).join('')}</ul>` : ''}
      </article>`).join(''));
  }

  // ---- Mudanças ----------------------------------------------------
  function abaMudancas() {
    const lista = _last.mudancas || [];
    if (!lista.length) return vazio('O mundo ainda não mudou pelo que vocês fizeram. Ainda.');
    return grade(lista.map(m => `
      <article class="lcl-item mnd-mudanca">
        <div class="lcl-item-cabeca"><button class="rel-nome" type="button"
          onclick="window.Mundo._verLugar('${aspas(m.lugar)}')">${esc(m.lugar)}</button>${cap(m.capitulo)}</div>
        <p class="lcl-item-desc">${esc(m.texto)}</p>
        ${m.causa ? `<p class="rel-seg-linha"><span>Porque</span> ${esc(m.causa)}</p>` : ''}
      </article>`).join(''));
  }

  const ABA_HTML = { renome: abaRenome, companheiros: abaCompanheiros, lendas: abaLendas,
                     bestiario: abaBestiario, mudancas: abaMudancas };

  function contagem(id) {
    return { renome: (_last.faccoes || []).length + (_last.titulos || []).length,
             companheiros: (_last.companheiros || []).length, lendas: (_last.lendas || []).length,
             bestiario: (_last.bestiario || []).length, mudancas: (_last.mudancas || []).length }[id];
  }

  function render(d) {
    _last = d || {};
    ensureDom();
    q('mnd-abas').innerHTML = ABAS.map(([id, rotulo]) => `
      <button class="elc-filtro${id === _aba ? ' elc-filtro-ativo' : ''}" data-aba="${id}" role="tab"
              aria-selected="${id === _aba}" onclick="window.Mundo._aba('${id}')">
        ${rotulo} <span class="elc-filtro-conta" data-num="mnd:aba:${id}">${contagem(id)}</span></button>`).join('');
    q('mnd-lista').innerHTML = ABA_HTML[_aba]();
    // O que mudou desde o último desenho (utils.js): renome e reputação
    // contam e deslizam; título novo cai como selo, fragmento se encaixa.
    if (window.animarNumeros) window.animarNumeros(q('mundo-overlay'));
    if (window.marcarNovos) window.marcarNovos(q('mnd-lista'), `mnd:${_aba}`);
  }

  function mensagem(txt, erro) {
    const el = q('mnd-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  async function abrir(aba) {
    ensureDom();
    _aba = ABA_HTML[aba] ? aba : 'renome';
    if (!_open) {
      q('mundo-overlay').classList.remove('hidden');
      document.body.classList.add('mundo-on');
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
    const el = q('mundo-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('mundo-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  async function sync() {
    if (!_open) return;
    try { render(await getState()); } catch (_) { /* nunca derruba o turno */ }
  }

  window.Mundo = {
    sync,
    _abrir: abrir,
    _fechar: fechar,
    _aba: (aba) => { _aba = aba; render(_last); },
    _ver: (nome) => { fechar(); if (window.Personagens) window.Personagens._abrir(nome); },
    _verLugar: (lugar) => { fechar(); if (window.Locais) window.Locais._abrir(lugar); },
    _estado: () => _last,
  };
})();
