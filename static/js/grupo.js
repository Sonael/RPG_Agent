// ═══════════════════════════════════════════════════════════════════
//  grupo.js — Visão geral do grupo ("O Grupo")
//
//  Os heróis lado a lado: vida, mana, dados de vida, condições, carga e quem
//  tem escolha de nível pendente. É a tela para decidir descanso e divisão de
//  itens sem abrir a ficha de cada um.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo aqui. Quem
//  o descanso curto ajuda, quem já pode dormir, a folga de carga antes de
//  ficar sobrecarregado e o resumo vêm prontos do motor (rpg/grupo.py via
//  /api/party/overview). "Pedir descanso" manda a fala do jogador ao mestre,
//  que decide se a ficção permite e abre a tela de descanso.
//
//  Não abre sozinha; aberta, a fila de telas a redesenha.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _last = {};

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");
  const maiuscula = (s) => { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); };

  function ensureDom() {
    if (q('grupo-overlay')) return;
    const o = document.createElement('div');
    o.id = 'grupo-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="grp-frame" role="dialog" aria-modal="true" aria-labelledby="grp-titulo">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Grupo._fechar()" aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="lcl-title" id="grp-titulo">O Grupo</h1>
          <div id="grp-hora" class="grp-hora"></div>
        </header>

        <section id="grp-resumo" class="grp-resumo" aria-label="Resumo do grupo"></section>

        <div class="grp-corpo">
          <div id="grp-cartoes" class="grp-cartoes"></div>
        </div>

        <div class="lcl-rodape">
          <div id="grp-msg" class="lcl-msg" aria-live="polite"></div>
          <button class="lcl-fechar" onclick="window.Grupo._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  async function getState() {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}/api/party/overview`);
    return r.json();
  }

  // ---- Render ------------------------------------------------------
  function barra(rotulo, atual, max, pct, cls, extra, marcador) {
    return `
      <div class="grp-barra ${cls || ''}">
        <div class="grp-barra-rotulo"><span>${rotulo}</span><span>${atual}/${max}${extra || ''}</span></div>
        <div class="grp-barra-trilho">
          <div class="grp-barra-fill" style="width:${pct}%"></div>
          ${marcador != null ? `<span class="grp-barra-marca" style="left:${marcador}%"
               title="A partir daqui fica sobrecarregado"></span>` : ''}
        </div>
      </div>`;
  }

  function marcas(h) {
    const m = [];
    if (h.morto) m.push('<span class="hro-marca hro-marca-perigo">Morto</span>');
    if (h.testes_de_morte) {
      m.push(`<span class="hro-marca hro-marca-perigo">Caído: ${h.testes_de_morte.sucessos}S ${h.testes_de_morte.falhas}F</span>`);
    }
    (h.condicoes || []).forEach(c => m.push(
      `<span class="hro-marca hro-marca-perigo">${esc(maiuscula(c.nome))}${c.duracao ? ` (${c.duracao}t)` : ''}</span>`));
    if (h.exaustao) m.push(`<span class="hro-marca hro-marca-perigo">Exaustão ${h.exaustao}</span>`);
    if (h.concentracao) m.push(`<span class="hro-marca">Concentrado: ${esc(h.concentracao)}</span>`);
    (h.efeitos || []).forEach(e => m.push(`<span class="hro-marca hro-marca-efeito">${esc(e)}</span>`));
    return m.join('');
  }

  function carga(h) {
    const c = h.carga;
    const estado = c.estado === 'imovel' ? 'imóvel'
      : c.estado === 'sobrecarregado' ? 'sobrecarregado'
      : c.perto_do_limite ? `perto do limite · folga ${c.folga_kg} kg`
      : `folga ${c.folga_kg} kg`;
    const cls = c.estado !== 'livre' ? 'grp-barra-perigo' : (c.perto_do_limite ? 'grp-barra-alerta' : 'grp-barra-carga');
    return barra('Carga', c.kg, `${c.capacidade} kg`, c.pct, cls, '', c.pct_limite)
      + `<p class="grp-linha grp-carga-estado">${esc(estado)}</p>`;
  }

  function descanso(h) {
    if (h.morto) return '';
    const d = h.descanso;
    const partes = [
      d.curto_ajuda ? '<span class="grp-ok">curto ajuda</span>' : '',
      d.pode_longo ? '<span class="grp-ok">pode dormir</span>'
        : `<span class="grp-espera">longo em ${d.faltam_horas}h</span>`,
    ].filter(Boolean);
    return `<p class="grp-linha grp-descanso">${partes.join(' · ')}</p>`;
  }

  function cartao(h) {
    const v = h.vida;
    const nome = aspas(h.nome);
    const nivel = h.nivel_pendente
      ? `<button class="grp-nivel" onclick="window.Grupo._tela('${nome}','nivel')"
                 title="${h.pode_subir ? 'XP suficiente para subir de nível' : 'Há escolha de nível por fazer'}">
           ${h.pode_subir ? 'Subir de nível' : 'Escolha de nível'}</button>`
      : '';
    const vidaCls = v.atual === 0 ? 'grp-barra-perigo' : (v.pct <= 50 ? 'grp-barra-alerta' : 'grp-barra-vida');
    return `
      <article class="grp-cartao${h.morto ? ' grp-cartao-morto' : ''}${h.precisa.length ? ' grp-cartao-precisa' : ''}"
               data-nome="${esc(h.nome)}">
        <header class="grp-cartao-cabeca">
          <button class="grp-nome" onclick="window.Grupo._tela('${nome}','ficha')" title="Abrir a ficha">${esc(h.nome)}</button>
          <span class="grp-sub">${esc(maiuscula(h.classe))} · nível ${h.nivel} · CA ${h.ca}</span>
          ${nivel}
        </header>
        <div class="grp-marcas">${marcas(h)}</div>
        ${barra('Vida', v.atual, v.max, v.pct, vidaCls, v.temp ? ` <small>+${v.temp}</small>` : '')}
        ${h.mana.max ? barra('Mana', h.mana.atual, h.mana.max, h.mana.pct, 'grp-barra-mana') : ''}
        <p class="grp-linha"><span>Dados de vida</span>
          <span><b>${h.dados_de_vida.restantes}/${h.dados_de_vida.max}</b> ${esc(h.dados_de_vida.dado)}</span></p>
        ${descanso(h)}
        ${carga(h)}
        <p class="grp-linha"><span>${h.itens} ${h.itens === 1 ? 'item' : 'itens'}</span>
          <span>${h.moedas.ouro} po · ${h.moedas.prata} pp</span></p>
        ${h.precisa.length ? `<p class="grp-precisa">Precisa: ${h.precisa.map(esc).join(', ')}</p>` : ''}
        <footer class="grp-acoes">
          <button class="lcl-btn lcl-btn-sec" onclick="window.Grupo._tela('${nome}','mochila')">Mochila</button>
          ${h.conjura ? `<button class="lcl-btn lcl-btn-sec" onclick="window.Grupo._tela('${nome}','grimorio')">Grimório</button>` : ''}
        </footer>
      </article>`;
  }

  function resumo(d) {
    const r = d.resumo || {};
    const combate = !!d.em_combate;
    const nivel = (r.nivel_pendente || []).length
      ? `<p class="grp-resumo-linha"><b>Nível:</b> ${esc(r.nivel_pendente.join(', '))} com escolha pendente.</p>`
      : '';
    const semFeridos = !(r.feridos || []).length;
    const tituloCurto = combate ? 'Em combate' : (!(r.curto_ajuda || []).length ? 'Ninguém ganha com o descanso curto' : 'Manda ao mestre: Vamos fazer um descanso curto.');
    const tituloLongo = combate ? 'Em combate' : (!r.longo_disponivel ? 'Ninguém pode fazer o descanso longo ainda' : 'Manda ao mestre: Vamos acampar para um descanso longo.');
    return `
      <p class="grp-resumo-linha"><b>Descanso:</b> ${esc(r.descanso || '')}</p>
      ${r.carga ? `<p class="grp-resumo-linha"><b>Itens:</b> ${esc(r.carga)}</p>` : ''}
      ${nivel}
      <div class="grp-resumo-acoes">
        <button id="grp-curto" class="lcl-btn lcl-btn-ir" onclick="window.Grupo._descanso('curto')"
                ${combate || semFeridos || !(r.curto_ajuda || []).length ? 'disabled' : ''}
                title="${esc(tituloCurto)}">Pedir descanso curto</button>
        <button id="grp-longo" class="lcl-btn lcl-btn-ir" onclick="window.Grupo._descanso('longo')"
                ${combate || semFeridos || !r.longo_disponivel ? 'disabled' : ''}
                title="${esc(tituloLongo)}">Pedir descanso longo</button>
      </div>`;
  }

  function render(d) {
    _last = d || {};
    ensureDom();
    const herois = _last.herois || [];
    q('grp-hora').textContent = [_last.hora, _last.em_combate ? 'em combate' : ''].filter(Boolean).join(' · ');
    q('grp-resumo').innerHTML = herois.length ? resumo(_last) : '';
    q('grp-cartoes').innerHTML = herois.length
      ? herois.map(cartao).join('')
      : '<div class="lcl-vazio">Ninguém do grupo tem ficha ainda.</div>';
    mensagem('');
  }

  function mensagem(txt, erro) {
    const el = q('grp-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  // ---- Abrir / fechar ----------------------------------------------
  async function abrir() {
    ensureDom();
    if (!_open) {
      q('grupo-overlay').classList.remove('hidden');
      document.body.classList.add('grupo-on');
      _open = true;
    }
    mensagem('Carregando…');
    try {
      render(await getState());
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  function fechar() {
    const el = q('grupo-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('grupo-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  // Aberta, redesenha com o que o mestre mudou no chat (dano, item, XP).
  async function sync() {
    if (!_open) return;
    try { render(await getState()); } catch (_) { /* nunca derruba o turno */ }
  }

  function tela(nome, qual) {
    fechar();
    if (qual === 'ficha' && window.Herois) window.Herois._abrir(nome);
    if (qual === 'mochila' && window.Inventory) window.Inventory._abrir(nome);
    if (qual === 'grimorio' && window.Grimoire) window.Grimoire._abrir(nome);
    if (qual === 'nivel' && window.LevelUp) { window.LevelUp._trocar(nome); window.LevelUp._abrir(); }
  }

  // A fala vai ao mestre como se o jogador a tivesse digitado; ele decide se
  // a ficção permite e abre a tela de descanso com offer_rest.
  function pedirDescanso(tipo) {
    if (typeof waiting !== 'undefined' && waiting) {
      mensagem('Aguarde o mestre terminar de responder.', true);
      return;
    }
    if (typeof window.sendToAgent !== 'function' || typeof window.appendUser !== 'function') return;
    const texto = tipo === 'longo'
      ? 'Vamos acampar para um descanso longo.'
      : 'Vamos fazer um descanso curto.';
    fechar();
    window.appendUser(texto);
    window.sendToAgent(texto, true);
  }

  window.Grupo = {
    sync,
    _abrir: abrir,
    _fechar: fechar,
    _tela: tela,
    _descanso: pedirDescanso,
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
