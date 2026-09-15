// ═══════════════════════════════════════════════════════════════════
//  herois.js — Ficha do herói (leitura)
//
//  Abre ao clicar no cartão de um membro do grupo. Mostra tudo o que o
//  jogador precisa para decidir e rolar: vida, CA, iniciativa, atributos e
//  salvaguardas, perícias, ataques, habilidades, equipamento e estado.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo aqui. Todo
//  bônus vem pronto do motor (tools_dnd.hero_snapshot via /api/heroes/sheet),
//  com as mesmas contas de attack_roll e make_skill_check. A tela não soma nem
//  grava nada: nível e escolhas mudam na tela de nível, itens na Mochila,
//  magias no Grimório, e erro de ficha no editor ("Corrigir ficha").
//
//  Como a Mochila, não abre sozinha; aberta, a fila de telas a redesenha.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _quem = '';
  let _last = {};

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");
  const maiuscula = (s) => { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); };

  function ensureDom() {
    if (q('heroi-overlay')) return;
    const o = document.createElement('div');
    o.id = 'heroi-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="hro-frame" role="dialog" aria-modal="true" aria-labelledby="hro-nome">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Herois._fechar()"
                  aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="lcl-title"><span id="hro-nome">—</span></h1>
          <div id="hro-sub" class="hro-sub"></div>
          <div id="hro-xp" class="hro-xp"></div>
          <div id="hro-estado" class="hro-estado"></div>
        </header>

        <div id="hro-recursos" class="hro-recursos" aria-label="Recursos"></div>

        <div class="lcl-corpo hro-corpo">
          <section class="lcl-corpo-pessoas" aria-label="Atributos e perícias">
            <h2 class="lcl-secao">Atributos e salvaguardas</h2>
            <div id="hro-atributos" class="hro-atributos"></div>
            <h2 class="lcl-secao">Perícias</h2>
            <div id="hro-pericias" class="hro-pericias"></div>
          </section>
          <section class="lcl-corpo-dentro" aria-label="Combate e equipamento">
            <h2 class="lcl-secao">Ataques</h2>
            <div id="hro-ataques" class="lcl-lista"></div>
            <h2 class="lcl-secao">Habilidades</h2>
            <div id="hro-habilidades" class="lcl-lista"></div>
            <h2 class="lcl-secao">Equipamento</h2>
            <div id="hro-equipamento"></div>
            <div id="hro-quem-bloco">
              <h2 class="lcl-secao">Quem é</h2>
              <div id="hro-quem"></div>
            </div>
          </section>
        </div>

        <div class="lcl-rodape">
          <div id="hro-msg" class="lcl-msg" aria-live="polite"></div>
          <button id="hro-nivel" class="lcl-btn lcl-btn-ir hidden"
                  onclick="window.Herois._tela('nivel')">Subir de nível</button>
          <button id="hro-grimorio" class="lcl-btn lcl-btn-sec hidden"
                  onclick="window.Herois._tela('grimorio')">Grimório</button>
          <button id="hro-mochila" class="lcl-btn lcl-btn-sec"
                  onclick="window.Herois._tela('mochila')">Mochila</button>
          <button id="hro-corrigir" class="lcl-btn lcl-btn-sec"
                  onclick="window.Herois._corrigir()"
                  title="Abre o editor da ficha, para corrigir um erro">Corrigir ficha</button>
          <button class="lcl-fechar" onclick="window.Herois._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  async function getState() {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}/api/heroes/sheet?personagem=${encodeURIComponent(_quem || '')}`);
    return r.json();
  }

  // ---- Render ------------------------------------------------------
  function estado(p) {
    const marcas = [];
    if (p.testes_de_morte) {
      marcas.push(`<span class="hro-marca hro-marca-perigo">Caído: ${p.testes_de_morte.sucessos} sucesso(s),`
        + ` ${p.testes_de_morte.falhas} falha(s) nos testes de morte</span>`);
    }
    (p.condicoes || []).forEach(c => marcas.push(
      `<span class="hro-marca hro-marca-perigo">${esc(maiuscula(c.nome))}${c.duracao ? ` (${c.duracao} turnos)` : ''}</span>`));
    if (p.exaustao) marcas.push(`<span class="hro-marca hro-marca-perigo">Exaustão ${p.exaustao}</span>`);
    if (p.concentracao) marcas.push(`<span class="hro-marca">Concentrado em ${esc(p.concentracao)}</span>`);
    if (p.carga && p.carga.estado !== 'livre') {
      marcas.push(`<span class="hro-marca hro-marca-perigo">${p.carga.estado === 'imovel' ? 'Imóvel' : 'Sobrecarregado'}</span>`);
    }
    return marcas.join('');
  }

  function recurso(rotulo, valor, detalhe, cls) {
    return `<div class="hro-recurso ${cls || ''}">
      <span class="hro-recurso-rotulo">${rotulo}</span>
      <span class="hro-recurso-valor">${valor}</span>
      ${detalhe ? `<span class="hro-recurso-detalhe">${detalhe}</span>` : ''}
    </div>`;
  }

  function recursos(p) {
    const v = p.vida;
    const detalheVida = [
      v.temp ? `+${v.temp} temporários` : '',
      v.teto < v.max ? `teto ${v.teto} pela exaustão` : '',
    ].filter(Boolean).join(' · ');
    return [
      recurso('Vida', `${v.atual}/${v.max}`, detalheVida, v.atual === 0 ? 'hro-recurso-perigo' : ''),
      p.mana.max ? recurso('Mana', `${p.mana.atual}/${p.mana.max}`) : '',
      recurso('CA', p.ca),
      recurso('Iniciativa', p.iniciativa),
      recurso('Proficiência', p.proficiencia),
      recurso('Percepção passiva', p.percepcao_passiva),
      recurso('Dados de vida', `${p.dados_de_vida.restantes}/${p.dados_de_vida.max}`, p.dados_de_vida.dado),
    ].join('');
  }

  function atributos(p) {
    return p.atributos.map(a => `
      <div class="hro-atributo" data-sigla="${esc(a.sigla)}">
        <span class="hro-atributo-sigla" title="${esc(a.nome)}">${esc(a.sigla)}</span>
        <span class="hro-atributo-mod">${esc(a.mod)}</span>
        <span class="hro-atributo-valor">${a.valor}</span>
        <span class="hro-atributo-save ${a.salvaguarda_proficiente ? 'hro-prof' : ''}"
              title="${a.salvaguarda_proficiente ? 'Salvaguarda da classe: soma a proficiência' : 'Salvaguarda'}">
          salv. ${esc(a.salvaguarda)}</span>
      </div>`).join('');
  }

  function pericias(p) {
    return p.pericias.map(x => `
      <div class="hro-pericia ${x.proficiente ? 'hro-prof' : ''}" data-pericia="${esc(x.nome)}">
        <span class="hro-pericia-bonus">${esc(x.bonus)}</span>
        <span class="hro-pericia-nome">${esc(maiuscula(x.nome))}</span>
        <span class="hro-pericia-sigla">${esc(x.sigla)}</span>
      </div>`).join('')
      + '<p class="hro-legenda"><span class="hro-ponto"></span> proficiente (soma a proficiência)</p>';
  }

  function ataques(p) {
    if (!p.ataques.length) return '<div class="lcl-vazio">Nenhuma arma equipada.</div>';
    return p.ataques.map(a => `
      <div class="lcl-item hro-ataque">
        <div class="lcl-item-cabeca">
          <span class="lcl-item-nome">${esc(maiuscula(a.arma))}</span>
          <span class="lcl-marca">${esc(a.alcance)}</span>
        </div>
        <div class="hro-ataque-numeros">
          <span><small>acerto</small> <b>${esc(a.acerto)}</b></span>
          <span><small>dano</small> ${a.dano ? `<b>${esc(a.dano)}</b>${a.tipo ? ` ${esc(a.tipo)}` : ''}`
            : `${a.tipo ? esc(a.tipo) : '—'} <small title="O dado desta arma não está no SRD: o mestre informa na hora">(dado do mestre)</small>`}</span>
          <span><small>atributo</small> ${esc(a.atributo)}</span>
        </div>
        ${a.notas.length ? `<p class="lcl-item-desc">${a.notas.map(esc).join(' · ')}</p>` : ''}
      </div>`).join('');
  }

  function habilidades(p) {
    if (!p.habilidades.length) return '<div class="lcl-vazio">Nenhuma habilidade.</div>';
    return p.habilidades.map(h => `
      <details class="lcl-item hro-habilidade">
        <summary class="lcl-item-cabeca">
          <span class="lcl-item-nome">${esc(h.nome)}</span>
          ${h.custo_mana ? `<span class="lcl-marca">${h.custo_mana} mana</span>` : ''}
          ${h.dado ? `<span class="lcl-marca">${esc(h.dado)}</span>` : ''}
        </summary>
        ${h.descricao ? `<p class="lcl-item-desc">${esc(h.descricao)}</p>` : ''}
      </details>`).join('');
  }

  function equipamento(p) {
    const slots = p.equipados.map(e => `
      <div class="hro-slot"><span class="hro-slot-rotulo">${esc(e.rotulo)}</span>
        <span class="hro-slot-item">${e.item ? esc(maiuscula(e.item)) : '<i>vazio</i>'}</span></div>`).join('');
    const m = p.moedas;
    const d = p.defesas;
    const defesas = [
      d.resistencias.length ? `Resistência: ${d.resistencias.map(esc).join(', ')}` : '',
      d.imunidades.length ? `Imunidade: ${d.imunidades.map(esc).join(', ')}` : '',
      d.vulnerabilidades.length ? `Vulnerabilidade: ${d.vulnerabilidades.map(esc).join(', ')}` : '',
    ].filter(Boolean);
    return `<div class="hro-slots">${slots}</div>
      <p class="hro-linha">${m.ouro} po · ${m.prata} pp · ${m.cobre} pc
        · ${p.itens} ${p.itens === 1 ? 'item' : 'itens'} na mochila
        · carga ${p.carga.kg}/${p.carga.capacidade} kg</p>
      ${defesas.length ? `<p class="hro-linha">${defesas.join(' · ')}</p>` : ''}`;
  }

  function render(d) {
    _last = d || {};
    ensureDom();
    const p = _last.personagem;
    if (!p) {
      q('hro-nome').textContent = _quem || 'Herói';
      ['hro-sub', 'hro-xp', 'hro-estado', 'hro-recursos', 'hro-atributos', 'hro-pericias',
       'hro-ataques', 'hro-habilidades', 'hro-equipamento', 'hro-quem'].forEach(id => { q(id).innerHTML = ''; });
      mensagem('Este personagem não é do grupo ou não tem ficha.', true);
      return;
    }
    _quem = p.nome;
    const grupo = _last.grupo || [];
    q('hro-nome').textContent = p.nome;
    q('hro-sub').innerHTML =
      (grupo.length > 1
        ? `<select class="hro-quem-sel" aria-label="Personagem" onchange="window.Herois._trocar(this.value)">`
          + grupo.map(n => `<option value="${esc(n)}" ${n === p.nome ? 'selected' : ''}>${esc(n)}</option>`).join('')
          + '</select>'
        : '')
      + `<span>${esc(maiuscula(p.classe))} · ${esc(maiuscula(p.raca))} · nível <b>${p.nivel}</b></span>`;
    q('hro-xp').innerHTML = `
      <div class="hro-xp-trilho"><div class="hro-xp-fill" style="width:${p.xp_pct}%"></div></div>
      <span>${p.nivel >= 20 ? `${p.xp} XP · nível máximo` : `${p.xp} / ${p.xp_proximo} XP`}</span>`;
    q('hro-estado').innerHTML = estado(p);
    q('hro-recursos').innerHTML = recursos(p);
    q('hro-atributos').innerHTML = atributos(p);
    q('hro-pericias').innerHTML = pericias(p);
    q('hro-ataques').innerHTML = ataques(p);
    q('hro-habilidades').innerHTML = habilidades(p);
    q('hro-equipamento').innerHTML = equipamento(p);
    const quem = [p.descricao, p.tracos ? `Traços: ${p.tracos}` : ''].filter(Boolean);
    q('hro-quem-bloco').classList.toggle('hidden', !quem.length);
    q('hro-quem').innerHTML = quem.map(t => `<p class="lcl-desc">${esc(t)}</p>`).join('');

    const nivel = q('hro-nivel');
    nivel.classList.toggle('hidden', !(p.pode_subir || p.escolhas_pendentes));
    nivel.textContent = p.pode_subir ? 'Subir de nível' : 'Escolhas de nível';
    q('hro-grimorio').classList.toggle('hidden', !p.conjura);
    mensagem('');
  }

  function mensagem(txt, erro) {
    const el = q('hro-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  // ---- Abrir / fechar ----------------------------------------------
  async function abrir(nome) {
    ensureDom();
    if (nome) _quem = nome;
    if (!_open) {
      q('heroi-overlay').classList.remove('hidden');
      document.body.classList.add('heroi-on');
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
    const el = q('heroi-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('heroi-on');
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  // Aberta, redesenha com o que o mestre mudou no chat (dano, XP, item).
  async function sync() {
    if (!_open) return;
    try { render(await getState()); } catch (_) { /* nunca derruba o turno */ }
  }

  function tela(qual) {
    const nome = _quem;
    fechar();
    if (qual === 'mochila' && window.Inventory) window.Inventory._abrir(nome);
    if (qual === 'grimorio' && window.Grimoire) window.Grimoire._abrir(nome);
    if (qual === 'nivel' && window.LevelUp) { window.LevelUp._trocar(nome); window.LevelUp._abrir(); }
  }

  function corrigir() {
    const mem = window._lastMem || {};
    const alvo = (_quem || '').toLowerCase();
    const lista = mem.party || [];
    const i = lista.findIndex(c => (c.name || '').toLowerCase() === alvo);
    if (i < 0 || typeof window.openEditModal !== 'function') return;
    fechar();
    window.openEditModal('character', alvo, lista[i]);
  }

  window.Herois = {
    sync,
    _abrir: abrir,
    _fechar: fechar,
    _trocar: (n) => { _quem = n; getState().then(render).catch(() => {}); },
    _tela: tela,
    _corrigir: corrigir,
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
