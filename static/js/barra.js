// ═══════════════════════════════════════════════════════════════════
//  barra.js — A barra lateral do jogo
//
//  A barra era um livro de listas em três abas (Mundo, Enciclopédia,
//  Diário), espremido numa coluna com rolagem própria. As telas cresceram
//  (grupo, missões, mapa, diário, personagens, mochila) e a barra ficou
//  repetindo, pior, o que elas mostram. Agora ela tem duas partes:
//
//  • O RELANCE, sempre à vista e sem rolagem: onde o grupo está, o capítulo e
//    a hora; uma linha por herói com a vida e as marcas que pedem atenção
//    (condição, nível pendente, carga); a missão principal com o progresso; e
//    os avisos do verificador, só quando houver algum.
//  • Os ATALHOS para as telas, com um contador quando ele diz algo.
//
//  No desktop a barra recolhe numa coluna de ícones. No celular ela vira uma
//  faixa fina sob o título (local, hora e a vida do grupo) e uma barra
//  inferior com Grupo, Missões, Mapa, Diário e Mais; "Mais" abre a gaveta com
//  o relance inteiro e todos os atalhos.
//
//  REGRA DE OURO, a mesma das telas: nenhuma regra aqui. A vida, o nível
//  pendente e a carga dos heróis vêm do motor (rpg/grupo.py via
//  /api/party/overview); o resto vem de /api/memory.
//
//  O que saiu da barra e para onde foi: Uso do modelo, modo de combate, Menu
//  principal e Sair foram para a engrenagem (montarConfiguracoes); o Resumo
//  para a página "Até aqui" do diário; as Observações para o editor da
//  campanha; a lista de locais para o mapa; a de personagens para o índice.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");
  const maiuscula = (s) => { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); };

  const CHAVE_RECOLHIDA = 'rpg_barra_recolhida';
  const MAX_AVISOS = 9;

  let _mem = {};
  let _grupo = null;          // /api/party/overview, só em campanha D&D
  let _pedido = 0;            // descarta a resposta de um pedido antigo
  let _avisos = [];
  let _avisosAbertos = false;

  // ---- Ícones (traço, cor do texto) -----------------------------------
  const svg = (corpo, tam = 20) =>
    `<svg class="sb-icone" width="${tam}" height="${tam}" viewBox="0 0 24 24" fill="none" stroke="currentColor"`
    + ` stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${corpo}</svg>`;
  const ICONES = {
    grupo: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
      + '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    missoes: '<path d="M8 21h12a2 2 0 0 0 2-2v-2H10v2a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v3h4"/>'
      + '<path d="M19 17V5a2 2 0 0 0-2-2H4"/>',
    mapa: '<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/>'
      + '<line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>',
    diario: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    personagens: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/>'
      + '<path d="M15 8h2"/><path d="M15 12h2"/><path d="M7 16h10"/>',
    mochila: '<path d="M4 10a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/>'
      + '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M8 21v-5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v5"/>',
    mundo: '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>'
      + '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    relacoes: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 0 0 0-7.8z"/>',
    mais: '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
    local: '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    capitulo: '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    hora: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    recolher: '<polyline points="11 17 6 12 11 7"/><polyline points="18 17 13 12 18 7"/>',
    aviso: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>'
      + '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    sol: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
      + 'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    lua: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  };

  const ehDnd = () => _mem.dnd_mode === true || _mem.campaign_type === 'dnd';
  // No romance o atalho do grupo abre as Relações (campaign_config.telas).
  const grupoSaoRelacoes = () => ((_mem.campaign_config || window._campaignConfig || {}).telas || {})
    .tela_do_grupo === 'relacoes';

  // ---- Atalhos -------------------------------------------------------
  const TELAS = [
    { id: 'grupo', rotulo: 'Grupo', dica: 'Os heróis lado a lado' },
    { id: 'missoes', rotulo: 'Missões', dica: 'O livro de missões' },
    { id: 'mapa', rotulo: 'Mapa', dica: 'Os lugares e quem está onde' },
    { id: 'diario', rotulo: 'Diário', dica: 'A história, capítulo a capítulo' },
    { id: 'personagens', rotulo: 'Personagens', dica: 'Todos os personagens, com busca' },
    { id: 'mochila', rotulo: 'Mochila', dica: 'O equipamento do grupo', soDnd: true },
    // Fantasia e dark fantasy: renome, companheiros, lendas, bestiário, mudanças.
    { id: 'mundo', rotulo: 'Mundo', dica: 'Renome, companheiros, lendas e bestiário', soTela: 'mundo' },
  ];

  // O nome e a dica de cada atalho no gênero da campanha.
  function atalho(t) {
    const nome = (chave, padrao) => (window.nomeDaTela ? window.nomeDaTela(chave, padrao) : padrao);
    if (t.id === 'grupo' && grupoSaoRelacoes()) {
      return { ...t, rotulo: 'Relações', dica: 'Como cada pessoa se sente', icone: 'relacoes' };
    }
    if (t.id === 'grupo') return { ...t, rotulo: nome('grupo', t.rotulo), dica: `${nome('grupo', t.rotulo)} lado a lado` };
    if (t.id === 'missoes') return { ...t, rotulo: nome('missoes', t.rotulo), dica: nome('titulo_missoes', t.dica) };
    if (t.id === 'mapa') return { ...t, rotulo: nome('mapa', t.rotulo) };
    return t;
  }

  function abrir(tela) {
    // No celular a gaveta fecha antes: a tela abre por cima do jogo, não dela.
    if (document.getElementById('sidebar')?.classList.contains('active') && typeof window.toggleSidebar === 'function') {
      window.toggleSidebar(true);
    }
    const W = window;
    if (tela === 'grupo') {
      if (grupoSaoRelacoes() && W.Relacoes) W.Relacoes._abrir();
      else if (ehDnd() && W.Grupo) W.Grupo._abrir();
      else if (W.Elenco) W.Elenco._abrir('grupo');
    } else if (tela === 'missoes' && W.Missoes) W.Missoes._abrir('');
    else if (tela === 'mapa' && W.Mapa) W.Mapa._abrir('');
    else if (tela === 'diario' && W.Diario) W.Diario._abrir();
    else if (tela === 'personagens' && W.Elenco) W.Elenco._abrir('todos');
    else if (tela === 'mundo' && W.Mundo) W.Mundo._abrir();
    else if (tela === 'mochila' && W.Inventory) {
      const heroi = ((_grupo && _grupo.herois) || []).find(h => !h.morto);
      W.Inventory._abrir(heroi ? heroi.nome : (_mem.protagonist || ''));
    }
  }

  function contadores() {
    const quests = (_mem.quests || []).filter(Boolean);
    const ativas = quests.filter(m => m.status === 'ativa').length;
    const alertas = ((_grupo && _grupo.herois) || [])
      .filter(h => !h.morto && (h.nivel_pendente || h.vida.atual === 0)).length;
    const outros = (_mem.characters || []).length;
    return {
      grupo: alertas ? { n: alertas, alerta: true, dica: `${alertas} ${alertas === 1 ? 'herói pede' : 'heróis pedem'} atenção` } : null,
      missoes: ativas ? { n: ativas, dica: `${ativas} ${ativas === 1 ? 'missão ativa' : 'missões ativas'}` } : null,
      personagens: outros ? { n: outros, dica: `${outros} ${window.frase ? window.frase('fora', 'fora do grupo') : 'fora do grupo'}` } : null,
    };
  }

  function renderAtalhos() {
    const nav = q('sb-atalhos');
    if (!nav) return;
    const conta = contadores();
    const dnd = ehDnd();
    const telas = ((_mem.campaign_config || window._campaignConfig || {}).telas) || {};
    nav.innerHTML = TELAS.filter(t => (!t.soDnd || dnd) && (!t.soTela || telas[t.soTela]))
      .map(atalho).map(t => {
      const c = conta[t.id];
      return `<button id="sb-atalho-${t.id}" class="sb-atalho${c ? ' sb-atalho-com-conta' : ''}" type="button" data-tela="${t.id}"
                      onclick="window.Barra.abrir('${t.id}')" title="${esc(c ? `${t.rotulo}: ${c.dica}` : t.dica)}"
                      aria-label="${esc(c ? `${t.rotulo}, ${c.dica}` : t.rotulo)}">
        ${svg(ICONES[t.icone || t.id])}<span class="sb-atalho-rotulo">${esc(t.rotulo)}</span>
        ${c ? `<span class="sb-atalho-conta${c.alerta ? ' sb-atalho-alerta' : ''}" data-num="sb:conta:${t.id}">${c.n}</span>` : ''}
      </button>`;
    }).join('');

    // Barra inferior do celular: as quatro telas mais usadas e "Mais".
    const inferior = q('barra-inferior');
    if (inferior) {
      inferior.innerHTML = ['grupo', 'missoes', 'mapa', 'diario'].map(id => {
        const t = atalho(TELAS.find(x => x.id === id));
        const c = conta[id];
        return `<button class="bi-botao" type="button" data-tela="${id}" onclick="window.Barra.abrir('${id}')"
                        aria-label="${esc(c ? `${t.rotulo}, ${c.dica}` : t.rotulo)}">
          <span class="bi-icone">${svg(ICONES[t.icone || id], 22)}${c ? `<span class="bi-conta${c.alerta ? ' sb-atalho-alerta' : ''}" data-num="bi:conta:${id}">${c.n}</span>` : ''}</span>
          <span class="bi-rotulo">${esc(t.rotulo)}</span></button>`;
      }).join('') + `
        <button id="bi-mais" class="bi-botao" type="button" data-tela="mais" aria-label="Mais: o painel da campanha"
                onclick="window.toggleSidebar && window.toggleSidebar()">
          <span class="bi-icone">${svg(ICONES.mais, 22)}</span><span class="bi-rotulo">Mais</span></button>`;
    }
  }

  // ---- Relance: onde, heróis, missão ---------------------------------
  const PERIODOS = [[0, 6, 'madrugada'], [6, 12, 'manhã'], [12, 18, 'tarde'], [18, 24, 'noite']];

  // "Dia 4, 19h" na linha; o período ("noite") vai na dica, que a linha é curta.
  function textoDaHora(relogio) {
    if (!relogio || relogio.dia === undefined) return '';
    return `Dia ${relogio.dia}, ${String(Number(relogio.hora || 0)).padStart(2, '0')}h`;
  }

  function periodoDaHora(relogio) {
    const h = Number((relogio || {}).hora || 0);
    return (PERIODOS.find(([a, b]) => h >= a && h < b) || [0, 0, ''])[2];
  }

  // O que a barra mostrou da última vez: o que mudar ganha um destaque breve.
  // undefined é "ainda não desenhou" (a primeira carga não destaca nada).
  let _ondeAntes;

  // O dia virou: um sol (de manhã à tarde) ou uma lua (à noite) cruza o
  // relógio em arco e some.
  function astro(tempo, hora) {
    const dia = hora >= 6 && hora < 18;
    const el = document.createElement('span');
    el.className = `sb-astro ${dia ? 'sb-astro-sol' : 'sb-astro-lua'}`;
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = svg(ICONES[dia ? "sol" : "lua"], 20);
    el.addEventListener('animationend', () => el.remove());
    tempo.querySelectorAll('.sb-astro').forEach(a => a.remove());
    tempo.appendChild(el);
  }

  function renderOnde() {
    const local = _mem.current_location || '';
    const nome = q('sb-location-nome');
    if (nome) nome.textContent = local || 'Local não definido';
    const botaoLocal = q('sb-location');
    if (botaoLocal) botaoLocal.title = local ? `Ver o local: ${local}` : 'Ver o local';
    const cap = q('ws-chapter-num');
    if (cap) cap.textContent = _mem.chapter || 1;
    const hora = textoDaHora(_mem.relogio);
    const tempo = q('sb-tempo');
    if (tempo) {
      tempo.classList.toggle('hidden', !hora);
      q('sb-tempo-texto').textContent = hora;
      tempo.title = hora ? `${hora} (${periodoDaHora(_mem.relogio)}): veja quem pode descansar` : '';
    }
    const r = _mem.relogio || {};
    const agora = { local, capitulo: _mem.chapter || 1, hora, dia: r.dia, h: Number(r.hora || 0) };
    const antes = _ondeAntes;
    _ondeAntes = agora;
    if (!antes || !window.destacar) return;
    if (local !== antes.local) window.destacar(botaoLocal, 'sb-mudou');
    if (agora.capitulo !== antes.capitulo) window.destacar(cap && cap.closest('button'), 'sb-mudou');
    if (hora && antes.hora && hora !== antes.hora) {
      window.destacar(q('sb-tempo-texto'), 'sb-hora-mudou');
      if (agora.dia !== antes.dia && window.animacoesLigadas && window.animacoesLigadas()) astro(tempo, agora.h);
    }
  }

  function classeDaVida(h) {
    if (h.vida.atual === 0) return 'sb-vida-perigo';
    return h.vida.pct <= 50 ? 'sb-vida-alerta' : '';
  }

  function marcasDoHeroi(h) {
    const marcas = [];
    if (h.morto) marcas.push('<span class="sb-marca sb-marca-perigo">morto</span>');
    else if (h.vida.atual === 0) marcas.push('<span class="sb-marca sb-marca-perigo">caído</span>');
    const conds = h.condicoes || [];
    if (conds.length) {
      const nomes = conds.map(c => maiuscula(c.nome) + (c.duracao ? ` (${c.duracao}t)` : ''));
      marcas.push(`<span class="sb-marca sb-marca-perigo" title="${esc(nomes.join(', '))}">`
        + `${esc(maiuscula(conds[0].nome))}${conds.length > 1 ? ` +${conds.length - 1}` : ''}</span>`);
    }
    if (h.carga && h.carga.estado !== 'livre') {
      marcas.push(`<span class="sb-marca sb-marca-perigo" title="Carga ${h.carga.kg}/${h.carga.capacidade} kg">`
        + `${h.carga.estado === 'imovel' ? 'imóvel' : 'sobrecarregado'}</span>`);
    }
    if (h.nivel_pendente && !h.morto) {
      if (h.pode_subir) {
        // O mesmo selo e o mesmo aviso de antes (gameLevelUpClick): quem sobe
        // o nível é o motor, e as escolhas abrem na tela de nível.
        const i = (_mem.party || []).findIndex(p => (p.name || '') === h.nome);
        const chave = aspas(h.nome.toLowerCase().trim());
        marcas.push(`<span class="levelup-badge sb-marca sb-marca-nivel" role="button" tabindex="0"`
          + ` title="XP suficiente para subir de nível"`
          + ` onclick="gameLevelUpClick(event,'${chave}','party',${i})">nível</span>`);
      } else {
        marcas.push(`<span class="sb-marca sb-marca-nivel" role="button" tabindex="0" title="Há escolha de nível por fazer"`
          + ` onclick="event.stopPropagation(); window.Barra.nivel('${aspas(h.nome)}')">escolha de nível</span>`);
      }
    }
    return marcas.join('');
  }

  function renderHerois() {
    const alvo = q('sb-herois');
    if (!alvo) return;
    let linhas;
    if (ehDnd()) {
      const herois = (_grupo && _grupo.herois) || null;
      if (!herois) {
        // Primeira resposta ainda não chegou: nomes do grupo, sem números.
        linhas = (_mem.party || []).map(p => `
          <div class="sb-heroi" data-nome="${esc(p.name)}">
            <button class="sb-heroi-nome" type="button" onclick="window.Barra.verHeroi('${aspas(p.name)}')">${esc(p.name)}</button>
          </div>`);
      } else {
        // Companheiro sem ficha de regras entra na lista como entra o resto
        // do grupo: sem números, porque não há de onde tirá-los, e abrindo a
        // ficha do personagem. Antes ele sumia da barra.
        const semFicha = ((_grupo && _grupo.sem_ficha) || []).map(p => `
          <div class="sb-heroi sb-heroi-sem-ficha" data-nome="${esc(p.nome)}">
            <button class="sb-heroi-nome" type="button" onclick="window.Barra.verHeroi('${aspas(p.nome)}')"
                    title="Abrir a ficha de ${esc(p.nome)}">${esc(p.nome)}</button>
            ${p.papel ? `<span class="sb-heroi-papel">${esc(p.papel)}</span>` : ''}
          </div>`);
        // Quem conjura mostra mana embaixo da vida, na mesma linha do herói:
        // a mana estava só na ficha, e quem joga mago precisa dela a cada
        // magia, não a cada abertura de tela. Quem não conjura não ganha
        // barra vazia.
        linhas = herois.map(h => `
          <div class="sb-heroi${h.morto ? ' sb-heroi-morto' : ''}" data-nome="${esc(h.nome)}">
            <button class="sb-heroi-nome" type="button" onclick="window.Barra.verHeroi('${aspas(h.nome)}')"
                    title="Abrir a ficha de ${esc(h.nome)}">${esc(h.nome)}</button>
            <span class="sb-heroi-barras">
              <span class="sb-heroi-vida ${classeDaVida(h)}" role="img"
                    aria-label="Vida ${h.vida.atual} de ${h.vida.max}"><span data-barra="${esc(`sb:${h.nome}:vida`)}"
                    style="width:${h.vida.pct}%"></span></span>
              ${h.mana && h.mana.max ? `<span class="sb-heroi-mana" role="img"
                    aria-label="Mana ${h.mana.atual} de ${h.mana.max}"><span data-barra="${esc(`sb:${h.nome}:mana`)}"
                    style="width:${h.mana.pct}%"></span></span>` : ''}
            </span>
            <span class="sb-heroi-nums">
              <span class="sb-heroi-num" data-num="${esc(`sb:${h.nome}:vida`)}" data-valor="${h.vida.atual}">${h.vida.atual}/${h.vida.max}${h.vida.temp ? `<small>+${h.vida.temp}</small>` : ''}</span>
              ${h.mana && h.mana.max ? `<span class="sb-heroi-num sb-heroi-num-mana" title="Mana"
                    data-num="${esc(`sb:${h.nome}:mana`)}" data-valor="${h.mana.atual}">${h.mana.atual}/${h.mana.max}</span>` : ''}
            </span>
            ${marcasDoHeroi(h) ? `<span class="sb-heroi-marcas">${marcasDoHeroi(h)}</span>` : ''}
          </div>`).concat(semFicha);
      }
    } else {
      linhas = (_mem.party || []).map(p => `
        <div class="sb-heroi sb-heroi-sem-ficha" data-nome="${esc(p.name)}">
          <button class="sb-heroi-nome" type="button" onclick="window.Barra.verHeroi('${aspas(p.name)}')">${esc(p.name)}</button>
          ${p.role ? `<span class="sb-heroi-papel">${esc(p.role)}</span>` : ''}
        </div>`);
    }
    alvo.innerHTML = linhas.length ? linhas.join('')
      : `<span class="empty-state sb-vazio">${esc(window.frase ? window.frase('ninguem', 'Ninguém no grupo ainda.') : 'Ninguém no grupo ainda.')}</span>`;
  }

  // Qual missão mostrar: a ativa do capítulo mais recente; no empate, a mais
  // adiantada, e depois o título. Não dá para usar a ordem da lista: o banco
  // guarda as missões num objeto, e a ordem das chaves não é a de criação.
  function missaoPrincipal() {
    const ativas = (_mem.quests || []).filter(m => m && m.status === 'ativa');
    const progresso = (m) => {
      const objs = m.objetivos || [];
      return objs.length ? objs.filter(o => o.feito).length / objs.length : 0;
    };
    ativas.sort((a, b) => (Number(b.cap_inicio) || 0) - (Number(a.cap_inicio) || 0)
      || progresso(b) - progresso(a)
      || String(a.titulo || '').localeCompare(String(b.titulo || ''), 'pt'));
    return ativas[0] || null;
  }

  let _missaoAntes;
  function renderMissao() {
    const botao = q('sb-missao');
    if (!botao) return;
    const m = missaoPrincipal();
    botao.classList.toggle('hidden', !m);
    if (!m) { botao.innerHTML = ''; return; }
    const objs = m.objetivos || [];
    const feitos = objs.filter(o => o.feito).length;
    const pct = objs.length ? Math.round((feitos / objs.length) * 100) : 0;
    botao.dataset.titulo = m.titulo || '';
    botao.title = `Abrir a missão: ${m.titulo || ''}`;
    botao.innerHTML = `
      <span class="sb-missao-rotulo">${svg(ICONES.missoes, 16)} Missão</span>
      <span class="sb-missao-titulo">${esc(m.titulo || '')}</span>
      ${objs.length ? `<span class="sb-missao-progresso"><span class="sb-missao-trilho"><span data-barra="${esc(`sb:missao:${m.titulo}`)}" style="width:${pct}%"></span></span>`
        + `<span class="sb-missao-conta" data-num="${esc(`sb:missao:${m.titulo}`)}" data-valor="${feitos}">${feitos}/${objs.length}</span></span>` : ''}`;
    // Outra missão passou a ser a principal: a barra destaca a troca.
    if (_missaoAntes !== undefined && _missaoAntes !== m.titulo && window.destacar) window.destacar(botao, 'sb-mudou');
    _missaoAntes = m.titulo;
  }

  // Romance: o próximo encontro marcado, com quanto falta. Avisa (cor) quando
  // está perto ou passou da hora. O motor diz tudo (/api/memory "encontro").
  let _encontroAntes;             // undefined: a barra ainda não desenhou nenhum
  function renderEncontro() {
    const botao = q('sb-encontro');
    if (!botao) return;
    const e = _mem.encontro;
    botao.classList.toggle('hidden', !e);
    if (!e) { botao.innerHTML = ''; _encontroAntes = null; return; }
    const alerta = !!(e.em_breve || e.atrasado);
    botao.classList.toggle('sb-encontro-alerta', alerta);
    // O encontro pulsa quando fica perto (ou já está perto ao chegar); um
    // encontro novo entra deslizando. Só na mudança, não a cada turno.
    const qual = `${e.com}|${e.o_que}|${e.quando}`;
    if (window.destacar) {
      if (alerta && !(_encontroAntes && _encontroAntes.alerta && _encontroAntes.qual === qual)) {
        window.destacar(botao, 'sb-encontro-chegando');
      } else if (_encontroAntes !== undefined && (!_encontroAntes || _encontroAntes.qual !== qual)) {
        window.destacar(botao, 'sb-encontro-novo');
      }
    }
    _encontroAntes = { qual, alerta };
    botao.dataset.com = e.com;
    botao.title = `Abrir a ficha de ${e.com}`;
    botao.innerHTML = `
      <span class="sb-missao-rotulo">${svg(ICONES.relacoes, 16)} Encontro</span>
      <span class="sb-missao-titulo">${esc(e.o_que)} com ${esc(e.com)}</span>
      <span class="sb-encontro-quando">${esc(e.quando)}${e.onde ? ` · ${esc(e.onde)}` : ''} · <strong>${esc(e.falta)}</strong></span>`;
  }

  // Celular: a faixa sob o título, com local, hora e a vida do grupo.
  function renderFaixa() {
    const faixa = q('faixa-relance');
    if (!faixa) return;
    const hora = textoDaHora(_mem.relogio);
    const herois = (_grupo && _grupo.herois) || [];
    const vidas = ehDnd() ? herois.filter(h => !h.morto).map(h => `
      <span class="faixa-heroi" title="${esc(h.nome)}: ${h.vida.atual}/${h.vida.max}">
        <span class="faixa-inicial">${esc(h.nome.charAt(0))}</span>
        <span class="sb-heroi-vida ${classeDaVida(h)}"><span data-barra="${esc(`faixa:${h.nome}:vida`)}" style="width:${h.vida.pct}%"></span></span>
      </span>`).join('') : '';
    // A hora fica fora do texto do local: dentro dele, um nome longo a cortava
    // nas reticências.
    faixa.innerHTML = `
      <span class="faixa-onde">${esc(_mem.current_location || 'Local não definido')}</span>
      ${hora ? `<span class="faixa-hora">${esc(hora)}</span>` : ''}
      ${vidas ? `<span class="faixa-vidas">${vidas}</span>` : ''}`;
  }

  // ---- Avisos do verificador ------------------------------------------
  function renderAvisos() {
    const caixa = q('sb-avisos');
    if (!caixa) return;
    caixa.classList.toggle('hidden', !_avisos.length);
    if (!_avisos.length) { caixa.innerHTML = ''; _avisosAbertos = false; return; }
    const erro = _avisos.some(v => v.severity === 'erro');
    caixa.innerHTML = `
      <button id="sb-avisos-botao" class="sb-avisos-botao${erro ? ' sb-avisos-erro' : ''}" type="button"
              aria-expanded="${_avisosAbertos}" onclick="window.Barra.alternarAvisos()">
        ${svg(ICONES.aviso, 16)} ${_avisos.length} ${_avisos.length === 1 ? 'aviso' : 'avisos'} sobre a história</button>
      ${_avisosAbertos ? `<div class="sb-avisos-lista">
        ${_avisos.map((v, i) => `
          <div class="violation-item ${esc(v.severity)}">
            <div class="sb-aviso-cabeca"><span class="violation-rule">${esc(v.titulo || v.rule)}</span>
              <button class="sb-aviso-fechar" type="button" aria-label="Dispensar aviso"
                      onclick="window.Barra.dispensarAviso(${i})">✕</button></div>
            <div class="violation-msg">${esc(v.message)}</div>
            ${v.detail ? `<div class="violation-detail">${esc(v.detail)}</div>` : ''}
          </div>`).join('')}
        <button class="clean-button btn-texto btn-texto-mini" type="button" onclick="window.Barra.limparAvisos()">Limpar todos</button>
      </div>` : ''}`;
  }

  // ---- Engrenagem: o que é da campanha e não do jogador ----------------
  function montarConfiguracoes() {
    const corpo = document.querySelector('#settings-panel .settings-body');
    if (!corpo || q('settings-campanha')) return;
    const secao = document.createElement('div');
    secao.id = 'settings-campanha';
    secao.className = 'settings-section';
    secao.innerHTML = `
      <div class="settings-section-title">Esta campanha</div>
      <!-- Combate só existe onde há regras. No romance, "Tela tática" era um
           botão que o jogador não tinha como usar. A visibilidade é decidida
           no render, e não aqui: este painel é montado no início da sessão,
           antes de a memória (e com ela o gênero) ter chegado. -->
      <div id="settings-combate" class="hidden">
        <div class="settings-subtitulo">Modo de combate</div>
        <div id="combat-mode-toggle" class="combat-mode-toggle">
          <button type="button" data-mode="narrado" class="cm-opt active" onclick="setCombatMode('narrado')">Narrado pela IA</button>
          <button type="button" data-mode="tela" class="cm-opt" onclick="setCombatMode('tela')">Tela tática</button>
        </div>
        <div id="combat-mode-hint" class="settings-nota"></div>
      </div>
      <div class="settings-subtitulo">Uso do modelo</div>
      <div class="quota-panel settings-quota">
        <div class="quota-linha"><div>Modelo: <span id="sb-model">—</span></div></div>
        <div class="quota-linha">
          <div title="Requisições feitas nesta sessão, do limite diário do seu modelo">Requisições: <span id="stat-req">0</span></div>
          <div title="Tokens consumidos nesta sessão">Tokens: <span id="stat-tokens">0</span></div>
        </div>
        <div class="quota-barra"><div id="rpm-bar" style="width:0%;height:100%;background:var(--ink-user);transition:width .4s;"></div></div>
      </div>
      <div class="settings-acoes-campanha">
        <button id="settings-menu-principal" class="clean-button" type="button" onclick="customBackToMenu()">Menu principal</button>
        <button id="settings-sair" class="clean-button settings-sair" type="button" onclick="customLogout()">Sair do sistema</button>
      </div>`;
    corpo.insertBefore(secao, corpo.firstChild);
  }

  // ---- Recolher (desktop) ---------------------------------------------
  function aplicarRecolhida(recolhida) {
    document.body.classList.toggle('barra-recolhida', recolhida);
    const b = q('sb-recolher');
    if (b) {
      b.setAttribute('aria-expanded', String(!recolhida));
      b.setAttribute('aria-label', recolhida ? 'Abrir a barra' : 'Recolher a barra');
      b.title = recolhida ? 'Abrir a barra' : 'Recolher a barra';
    }
  }

  function alternar() {
    const recolhida = !document.body.classList.contains('barra-recolhida');
    aplicarRecolhida(recolhida);
    try { localStorage.setItem(CHAVE_RECOLHIDA, recolhida ? '1' : '0'); } catch (_) { /* sem armazenamento */ }
  }

  // ---- Render ---------------------------------------------------------
  async function carregarGrupo() {
    if (!ehDnd()) { _grupo = null; return; }
    const meu = ++_pedido;
    try {
      const f = window.authFetch || fetch;
      const r = await f(`${window.API || ''}/api/party/overview`);
      const dados = await r.json();
      if (meu !== _pedido) return;
      _grupo = dados;
      renderHerois();
      renderAtalhos();
      renderFaixa();
      animar();
    } catch (_) { /* a barra nunca derruba o turno */ }
  }

  // Vida dos heróis, progresso da missão e contagens dos atalhos: o que
  // mudou desliza, conta ou pulsa (utils.js, animarNumeros).
  function animar() {
    if (!window.animarNumeros) return;
    ['sidebar', 'faixa-relance', 'barra-inferior'].forEach(id => window.animarNumeros(q(id)));
  }

  function render(mem) {
    _mem = mem || {};
    q('settings-combate')?.classList.toggle('hidden', !ehDnd());
    renderOnde();
    renderHerois();
    renderMissao();
    renderEncontro();
    renderAtalhos();
    renderFaixa();
    renderAvisos();
    animar();
    carregarGrupo();
  }

  function avisos(lista) {
    if (!lista || !lista.length) return;
    _avisos = lista.concat(_avisos).slice(0, MAX_AVISOS);
    renderAvisos();
  }

  window.Barra = {
    render,
    abrir,
    alternar,
    avisos,
    montarConfiguracoes,
    limparAvisos: () => { _avisos = []; renderAvisos(); },
    dispensarAviso: (i) => { _avisos.splice(i, 1); renderAvisos(); },
    alternarAvisos: () => { _avisosAbertos = !_avisosAbertos; renderAvisos(); },
    verHeroi: (nome) => {
      if (document.getElementById('sidebar')?.classList.contains('active') && window.toggleSidebar) window.toggleSidebar(true);
      const h = ((_grupo && _grupo.herois) || []).find(x => x.nome === nome);
      if (h && window.Herois) window.Herois._abrir(nome);
      else if (window.Personagens) window.Personagens._abrir(nome);
    },
    nivel: (nome) => {
      if (document.getElementById('sidebar')?.classList.contains('active') && window.toggleSidebar) window.toggleSidebar(true);
      if (window.LevelUp) { window.LevelUp._trocar(nome); window.LevelUp._abrir(); }
    },
    abrirEncontro: () => {
      const e = _mem.encontro;
      if (e && window.Personagens) window.Personagens._abrir(e.com);
    },
    abrirMissao: () => {
      const m = missaoPrincipal();
      if (document.getElementById('sidebar')?.classList.contains('active') && window.toggleSidebar) window.toggleSidebar(true);
      if (m && window.Missoes) window.Missoes._abrir(m.titulo || '');
    },
    _estado: () => ({ grupo: _grupo, avisos: _avisos.slice() }),
  };

  document.addEventListener('DOMContentLoaded', () => {
    let recolhida = false;
    try { recolhida = localStorage.getItem(CHAVE_RECOLHIDA) === '1'; } catch (_) { /* sem armazenamento */ }
    aplicarRecolhida(recolhida);
    const s = q('sb-recolher');
    if (s) s.innerHTML = svg(ICONES.recolher, 18);
    const icones = { 'sb-icone-local': 'local', 'sb-icone-capitulo': 'capitulo', 'sb-icone-hora': 'hora' };
    Object.entries(icones).forEach(([id, nome]) => { const el = q(id); if (el) el.innerHTML = svg(ICONES[nome], 15); });
  });
})();
