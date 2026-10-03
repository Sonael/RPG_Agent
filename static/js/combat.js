// ═══════════════════════════════════════════════════════════════════
//  combat.js — Tela de combate tática (estilo "Pergaminho Épico")
//
//  REGRA DE OURO: este módulo NÃO tem nenhuma regra de jogo.
//  Toda mecânica vive no motor já fuzzado (tools_dnd via /api/combat/*).
//  Aqui só: (1) renderiza o snapshot, (2) envia intenções, (3) reabre/
//  fecha a tela e dispara a narração final pela LLM.
//
//  A tela foi refeita pensando primeiro no celular. Antes, cada combatente
//  era um cartão de ~150px: com quatro de cada lado o jogador rolava para ver
//  quem estava de pé, e a lista de magias só dizia o nome — dano, cura, área
//  e descrição existiam só no `title`, que o toque não mostra. Agora:
//    • cada combatente é uma LINHA compacta (nome, CA, vida, condições), e o
//      toque nela abre os detalhes ou, escolhendo alvo, escolhe o alvo;
//    • a barra de ação fica fixa no rodapé e mostra o último acontecimento;
//    • cada habilidade é um CARTÃO com custo, efeito, dado, salvaguarda,
//      área e quem ela atinge, e a descrição completa abre no toque;
//    • magia em área pergunta ao motor quem vai ser atingido e, se houver
//      aliado no caminho, pede confirmação. O fogo amigo é regra do jogo e
//      continua — o que não pode é acontecer sem aviso.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open      = false;   // overlay visível
  let _busy      = false;   // requisição em voo (trava de clique duplo)
  let _ending    = false;   // recap em andamento (evita disparo duplo)
  let _autoTimer = null;
  let _autoGuard = 0;       // teto de segurança p/ turnos de IA encadeados
  let _pick      = null;    // {kind:'attack'|'ability'|'item', ...}
  let _userClosed = false;  // usuário fechou a tela de propósito (combate segue)
  let _habs      = [];      // habilidades do turno, na ordem dos cartões
  let _confirmar = null;    // ação em área esperando o "conjurar mesmo assim"
  const _abertos = new Set();   // linhas de combatente com os detalhes abertos

  const OUT = ['morto', 'inconsciente', 'estabilizado', 'fugiu', 'exilado', 'rendido'];
  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const isOut = (st) => OUT.includes((st || '').toLowerCase());
  // Nome dentro de onclick='...': o esc não escapa o apóstrofo.
  const jsNome = (s) => esc(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (document.getElementById('combat-overlay')) return;
    const o = document.createElement('div');
    o.id = 'combat-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="cbt-frame">
        <header class="cbt-header">
          <button class="cbt-close" onclick="window.Combat._dismiss()"
                  aria-label="Fechar tela de combate"
                  title="Fechar — o combate continua e pode ser retomado">✕</button>
          <h1 class="cbt-title">O Confronto <span id="cbt-round">— Rodada 1</span></h1>
          <div id="cbt-vez" class="cbt-vez" aria-live="polite"></div>
          <div id="cbt-order" class="cbt-initiative"></div>
        </header>

        <div id="cbt-zonas" class="cbt-zonas hidden"></div>

        <div class="cbt-battlefield">
          <section class="cbt-lado cbt-lado-inimigo">
            <h2 class="cbt-lado-titulo">Inimigos <span id="cbt-n-inimigos"></span></h2>
            <div id="cbt-enemies" class="cbt-team"></div>
          </section>
          <section class="cbt-lado cbt-lado-grupo">
            <h2 class="cbt-lado-titulo">Grupo <span id="cbt-n-grupo"></span></h2>
            <div id="cbt-party" class="cbt-team"></div>
          </section>
        </div>

        <div class="cbt-lower">
          <div id="cbt-actionbar" class="cbt-action-panel">
            <div id="cbt-action-title" class="cbt-action-title">Aguardando…</div>
            <div id="cbt-ultimo" class="cbt-ultimo"></div>
            <div id="cbt-prompt" class="cbt-economy"></div>
            <div id="cbt-buttons" class="cbt-btn-grid"></div>
            <div id="cbt-targets" class="cbt-picker hidden"></div>
            <div id="cbt-livre" class="cbt-picker hidden"></div>
          </div>
          <div class="cbt-log-panel">
            <div class="cbt-log-title">Diário de Combate</div>
            <div id="cbt-log" class="cbt-log-content"></div>
          </div>
        </div>

        <div id="cbt-end-overlay" class="cbt-end-overlay hidden"></div>
      </div>`;
    document.body.appendChild(o);

    // Sombra sob o título grudado só com o painel rolado (ver CSS).
    const painel = document.getElementById('cbt-actionbar');
    painel.addEventListener('scroll', () => {
      painel.classList.toggle('cbt-rolado', painel.scrollTop > 0);
    }, { passive: true });

    // Toque na linha do combatente: escolhendo alvo, escolhe o alvo; fora
    // disso, abre e fecha os detalhes (classe, concentração, defesas). Antes
    // o alvo só podia ser escolhido numa segunda lista de botões, longe de
    // quem ele era — e no celular essa lista ficava abaixo da dobra.
    document.getElementById('cbt-frame').addEventListener('click', (ev) => {
      const linha = ev.target.closest('.cbt-card[data-nome]');
      if (!linha) return;
      const nome = linha.dataset.nome;
      if (linha.classList.contains('cbt-alvejavel')) { _target(nome); return; }
      if (_pick) return;   // escolhendo alvo: tocar em quem não pode não faz nada
      if (_abertos.has(nome)) _abertos.delete(nome); else _abertos.add(nome);
      linha.classList.toggle('cbt-aberto', _abertos.has(nome));
      linha.setAttribute('aria-expanded', _abertos.has(nome) ? 'true' : 'false');
    });
    // A linha é um botão (role="button"): Enter e Espaço fazem o mesmo que o toque.
    document.getElementById('cbt-frame').addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      const linha = ev.target.closest && ev.target.closest('.cbt-card[data-nome]');
      if (!linha || ev.target !== linha) return;
      ev.preventDefault();
      linha.click();
    });

    // Pílula flutuante para RETOMAR o combate depois que o usuário fechou
    // a tela. Fica fora do #combat-overlay (que some quando fechado).
    if (!document.getElementById('cbt-reopen')) {
      const pill = document.createElement('button');
      pill.id = 'cbt-reopen';
      pill.className = 'hidden';
      pill.textContent = 'Retomar combate';
      pill.onclick = () => window.Combat._reopen();
      document.body.appendChild(pill);
    }
  }

  // ---- Rede --------------------------------------------------------
  async function api(path, opts) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}${path}`, opts || {});
    return r.json();
  }
  function getState()  { return api('/api/combat/state'); }
  function doAction(p) {
    return api('/api/combat/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }
  function preverArea(p) {
    return api('/api/combat/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }

  // ---- Render ------------------------------------------------------
  function bar(label, cur, max, cls, extra = '') {
    const m = max > 0 ? Math.max(0, Math.min(100, (cur / max) * 100)) : 0;
    // A barra de HP muda de cor com a porcentagem. Antes era sempre vermelha,
    // cheia ou quase vazia — não dava para bater o olho e ver quem ia cair.
    const risco = cls === 'hp'
      ? (m <= 25 ? ' cbt-hp-baixo' : (m <= 50 ? ' cbt-hp-atencao' : ' cbt-hp-ok'))
      : '';
    return `<div class="cbt-bar-row cbt-bar-row-${cls}">
      <span class="cbt-bar-label">${label}</span>
      <div class="cbt-bar"><div class="cbt-bar-fill ${cls}${risco}" style="width:${m}%"></div></div>
      <span class="cbt-bar-num">${cur}/${max}${extra}</span>
    </div>`;
  }

  // Crista do painel de fim. SVG e não emoji: um troféu em emoji é desenhado pelo sistema
  // operacional e muda de forma e de cor entre Windows, Android e iOS — num
  // painel comemorativo isso aparece como remendo.
  const CRISTA_VITORIA =
    '<svg class="cbt-crista" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    + 'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4z"/>'
    + '<path d="M7 6H4.5a2.5 2.5 0 0 0 2.5 4M17 6h2.5a2.5 2.5 0 0 1-2.5 4"/></svg>';
  const CRISTA_DERROTA =
    '<svg class="cbt-crista" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    + 'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M4 6l8 14 8-14"/><path d="M4 6h16M9 6l3 5 3-5"/></svg>';

  // Tipos de dano em português, para os selos de defesa caberem no card.
  const TIPO_PT = {
    acid: 'ácido', bludgeoning: 'concussão', cold: 'frio', fire: 'fogo',
    force: 'força', lightning: 'elétrico', necrotic: 'necrótico',
    piercing: 'perfurante', poison: 'veneno', psychic: 'psíquico',
    radiant: 'radiante', slashing: 'cortante', thunder: 'trovejante',
  };
  const tipoPt = t => TIPO_PT[t] || t;

  function selosDeDefesa(c) {
    // Imunidade, resistência e vulnerabilidade: sem isto o jogador não tem
    // como saber por que o golpe dele deu metade (ou zero) do dano.
    // O marcador (0, ½, ×2) vem antes do tipo porque a diferença entre imune
    // e vulnerável não pode depender só da cor do selo.
    const grupos = [
      ['imu', '0',  'Imune a',      c.imunidades],
      ['res', '½',  'Resiste a',    c.resistencias],
      ['vul', '×2', 'Vulnerável a', c.vulnerabilidades],
    ];
    return grupos.flatMap(([cls, marca, titulo, tipos]) =>
      (tipos || []).map(t =>
        `<span class="cbt-def cbt-def-${cls}" title="${titulo} dano ${tipoPt(t)}">`
        + `<b>${marca}</b> ${esc(tipoPt(t))}</span>`)
    ).join('');
  }

  // De que lado cada um luta (memory.lado_no_combate): "grupo", "aliado" ou
  // "inimigo". O aliado fica do seu lado da tela, mas quem o joga é o motor.
  // Snapshot antigo, sem o campo, continua valendo pelos dois lados de antes.
  const lado = (c) => (c && c.lado) || (c && c.is_party ? 'grupo' : 'inimigo');
  const comOGrupo = (c) => lado(c) !== 'inimigo';

  // A linha do combatente. Tudo o que decide a jogada (nome, vez, CA, vida,
  // condições) cabe em ~56px; o que é consulta (classe, mana, concentração,
  // defesas) fica nos detalhes, que abrem no toque. No desktop há espaço e os
  // detalhes aparecem sempre.
  function card(c, posicao) {
    const out    = isOut(c.status);
    // "dormindo" (Sleep): esmaece o card e mostra a tag, MAS continua
    // alvejável (não entra em isOut, então o picker de alvo o inclui).
    const asleep = (c.status || '').toLowerCase() === 'dormindo';
    const dim    = out || asleep;
    // Turnos restantes vêm do motor, que desconta no fim de cada turno do afetado.
    const turnos = c.condicoes_turnos || {};
    const conds  = (c.condicoes || []).map(x => {
        const n = turnos[x];
        // Enfeitiçado/Dominado: por quem e até quando (rpg/encantos.py).
        const enc = /^(enfeiti|dominad)/i.test(x) && c.encanto ? ` title="${esc(c.encanto)}"` : '';
        return n
          ? `<span class="cbt-cond" title="${esc(x)}: ${n} turno${n === 1 ? '' : 's'} restante${n === 1 ? '' : 's'}">${esc(x)} <small>${n}t</small></span>`
          : `<span class="cbt-cond"${enc}>${esc(x)}</span>`;
      }).join('')
      + (c.efeitos || []).map(x => `<span class="cbt-cond cbt-efeito" title="Efeito de item até o fim do combate">${esc(x)}</span>`).join('');
    const meta   = `${esc(c.classe || '')}${c.nivel ? ' Nv.' + c.nivel : ''}`.trim();
    const temp   = Number(c.hp_temp || 0);
    const defs   = selosDeDefesa(c);
    const aberto = _abertos.has(c.name);
    const detalhes = [
      meta ? `<span class="cbt-meta">${meta}</span>` : '',
      c.concentracao ? `<div class="cbt-conc" title="Sofrer dano exige teste de Constituição para manter">Concentrado em ${esc(c.concentracao)}</div>` : '',
      c.encanto ? `<div class="cbt-conc cbt-encanto">${esc(c.encanto)}</div>` : '',
      defs ? `<div class="cbt-defs">${defs}</div>` : '',
    ].join('');
    return `<div data-nome="${esc(c.name)}" role="button" tabindex="0" aria-expanded="${aberto}" class="cbt-card ${comOGrupo(c) ? 'cbt-aliado' : 'cbt-inimigo'} ${
      lado(c) === 'aliado' ? 'cbt-npc-aliado' : ''} ${
      c.is_current ? 'cbt-cur' : ''} ${
      out ? 'cbt-out' : (asleep ? 'cbt-asleep' : '')} ${
      aberto ? 'cbt-aberto' : ''}">
      <div class="cbt-c-header">
        ${posicao ? `<span class="cbt-ini" title="Posição na iniciativa">${posicao}</span>` : ''}
        <span class="cbt-name">${esc(c.name)}</span>
        ${lado(c) === 'aliado' ? '<span class="cbt-selo-aliado" title="Luta ao seu lado, mas não é do grupo: o motor joga por ele">aliado</span>' : ''}
        ${c.is_current ? '<span class="cbt-arrow" title="É a vez dele">vez</span>' : ''}
        ${c.zona ? `<span class="cbt-zona-tag" title="Zona do campo de batalha">${esc(c.zona)}</span>` : ''}
        <span class="cbt-ca" title="Classe de Armadura">CA ${c.ca}</span>
      </div>
      <div class="cbt-bars">
        ${bar('HP', c.hp, c.hp_max, 'hp',
              temp ? ` <span class="cbt-temp" title="PV temporários — absorvem dano antes dos PV reais">+${temp}</span>` : '')}
        ${c.mp_max > 0 ? bar('MP', c.mp, c.mp_max, 'mp') : ''}
      </div>
      ${(conds || dim) ? `<div class="cbt-conds">${conds}${
        dim ? `<span class="cbt-cond cbt-cond-out">${esc(c.status)}</span>` : ''
      }</div>` : ''}
      ${detalhes ? `<div class="cbt-detalhes">${detalhes}</div>` : ''}
    </div>`;
  }

  // "Agora: X · Próximo: Y". A régua com todos os nomes não cabe no celular
  // (rolava na horizontal e o próximo ficava escondido), e o que o jogador
  // precisa saber de relance é só isso. A ordem inteira continua no número
  // de cada linha e, no desktop, na régua.
  function vezDoTurno(snap) {
    const ordem = snap.order || [];
    const por = n => (snap.combatants || []).find(c => c.name === n);
    const i = snap.turn_index || 0;
    const agora = ordem[i] || '';
    let proximo = '';
    for (let k = 1; k < ordem.length; k++) {
      const n = ordem[(i + k) % ordem.length];
      const c = por(n);
      if (c && !isOut(c.status)) { proximo = n; break; }
    }
    return { agora, proximo };
  }

  function render(snap) {
    ensureDom();
    document.getElementById('cbt-end-overlay').classList.add('hidden');

    const enemies = (snap.combatants || []).filter(c => !comOGrupo(c));
    const party   = (snap.combatants || []).filter(comOGrupo);
    const posicao = n => (snap.order || []).indexOf(n) + 1;
    const dePe    = lista => lista.filter(c => !isOut(c.status)).length;

    document.getElementById('cbt-round').textContent = `— Rodada ${snap.round || 1}`;

    const vez = vezDoTurno(snap);
    document.getElementById('cbt-vez').innerHTML = vez.agora
      ? `<span>Agora: <b>${esc(vez.agora)}</b></span>`
        + (vez.proximo ? `<span class="cbt-vez-sep">·</span><span>Próximo: ${esc(vez.proximo)}</span>` : '')
      : '';

    document.getElementById('cbt-order').innerHTML = (snap.order || [])
      .map((n, i) => {
        const ch   = (snap.combatants || []).find(c => c.name === n);
        const dead = ch && isOut(ch.status);
        return `<span class="cbt-ord ${i === snap.turn_index ? 'on' : ''} ${dead ? 'cbt-ord-dead' : ''}">${esc(n)}</span>`;
      })
      .join('<span class="cbt-ord-sep">›</span>');

    document.getElementById('cbt-n-inimigos').textContent = enemies.length ? `${dePe(enemies)}/${enemies.length}` : '';
    document.getElementById('cbt-n-grupo').textContent    = party.length ? `${dePe(party)}/${party.length}` : '';
    document.getElementById('cbt-enemies').innerHTML = enemies.map(c => card(c, posicao(c.name))).join('') || '<div class="cbt-empty">—</div>';
    document.getElementById('cbt-party').innerHTML   = party.map(c => card(c, posicao(c.name))).join('')   || '<div class="cbt-empty">—</div>';

    renderZonas(snap);

    const linhas = (snap.log || []).slice(-12);
    const log = linhas.map(e =>
      `<div class="cbt-logline">[R${e.round}] ${esc(e.msg || e.type || '')}</div>`).join('');
    const lg = document.getElementById('cbt-log');
    lg.innerHTML = log;
    lg.scrollTop = lg.scrollHeight;
    // O último acontecimento, dentro da barra de ação: no celular o diário
    // fica lá embaixo, e o jogador tocava "Atacar" sem ver o que tinha
    // acabado de acontecer.
    const ultimo = linhas.length ? linhas[linhas.length - 1] : null;
    document.getElementById('cbt-ultimo').textContent = ultimo ? (ultimo.msg || ultimo.type || '') : '';

    renderActionBar(snap);
    animarMudancas(snap);
  }

  // ---- Animações ---------------------------------------------------
  // O render redesenha os cartões do zero, então quem mudou é descoberto
  // comparando com o render anterior: o número do dano ou da cura flutua,
  // a barra de vida desliza do valor antigo ao novo (redesenhada, ela
  // perdia a transição), o cartão treme no dano, esmaece ao cair, e o de
  // quem passa a jogar pulsa. Abrir um combate novo dá um tranco na tela.
  let _antes = null;       // { nome: { hp, max, fora } } do render anterior
  let _vezAntes = null;
  let _entrando = false;
  const _anima = () => typeof window.animacoesLigadas === 'function' && window.animacoesLigadas();
  const _cartaoDe = (nome) => [...document.querySelectorAll('#combat-overlay .cbt-card[data-nome]')]
    .find(el => el.dataset.nome === nome);

  function animarMudancas(snap) {
    const agora = {};
    (snap.combatants || []).forEach(c => {
      agora[c.name] = { hp: Number(c.hp) || 0, max: Number(c.hp_max) || 0, fora: isOut(c.status) };
    });
    const vez = ((snap.combatants || []).find(c => c.is_current) || {}).name || null;
    if (_anima()) {
      const frame = document.getElementById('cbt-frame');
      if (_entrando && frame) {
        frame.classList.add('cbt-inicio');
        const tirar = (e) => { if (e.animationName === 'combateComeca') { frame.classList.remove('cbt-inicio');
                                 frame.removeEventListener('animationend', tirar); } };
        frame.addEventListener('animationend', tirar);
      }
      if (_antes) {
        for (const [nome, a] of Object.entries(agora)) {
          const b = _antes[nome];
          const cartao = b && _cartaoDe(nome);
          if (!cartao) continue;
          const delta = a.hp - b.hp;
          if (delta !== 0) {
            const fill = cartao.querySelector('.cbt-bar-fill.hp');
            if (fill && b.max > 0) {
              const alvo = fill.style.width;
              fill.style.width = `${Math.max(0, Math.min(100, (b.hp / b.max) * 100))}%`;
              requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = alvo; }));
            }
            cartao.classList.add(delta < 0 ? 'cbt-levou-dano' : 'cbt-curou');
            const num = document.createElement('span');
            num.className = `cbt-flutua ${delta < 0 ? 'dano' : 'cura'}`;
            num.textContent = delta < 0 ? String(delta) : `+${delta}`;
            num.setAttribute('aria-hidden', 'true');
            num.addEventListener('animationend', () => num.remove());
            cartao.appendChild(num);
          }
          if (a.fora && !b.fora) cartao.classList.add('cbt-caiu');
        }
        if (vez && vez !== _vezAntes) _cartaoDe(vez)?.classList.add('cbt-vez-nova');
      }
    }
    _antes = agora;
    _vezAntes = vez;
    _entrando = false;
  }

  // Faixa do campo de batalha. Fica escondida quando o combate nao usa
  // zonas: a onda 3 e opcional, e uma trilha vazia so ocuparia espaco.
  function renderZonas(snap) {
    const faixa = document.getElementById('cbt-zonas');
    if (!faixa) return;
    const zonas = snap.zonas || [];
    if (zonas.length < 2) { faixa.classList.add('hidden'); faixa.innerHTML = ''; return; }

    const desc  = snap.zona_desc || {};
    const atual = (snap.combatants || []).find(c => c.is_current);
    faixa.innerHTML = zonas.map(z => {
      const dentro = (snap.combatants || []).filter(c => c.zona === z && !isOut(c.status));
      const fichas = dentro.map(c =>
        `<span class="cbt-pin ${comOGrupo(c) ? 'cbt-pin-aliado' : 'cbt-pin-inimigo'}`
        + `${c.is_current ? ' cbt-pin-vez' : ''}">${esc(c.name)}</span>`).join('');
      const aqui = (atual && atual.zona === z) ? ' cbt-zona-aqui' : '';
      // No celular os nomes empilhados faziam a faixa ocupar um quarto da
      // tela; lá ela mostra só quantos de cada lado, e a zona de cada um vai
      // escrita na própria linha.
      const nosso = dentro.filter(comOGrupo).length;
      const deles = dentro.length - nosso;
      const conta = dentro.length
        ? [nosso ? `<span class="cbt-conta-aliado">${nosso} do grupo</span>` : '',
           deles ? `<span class="cbt-conta-inimigo">${deles} inimigo${deles === 1 ? '' : 's'}</span>` : '']
            .filter(Boolean).join(' · ')
        : '<span class="cbt-zona-vazia">vazia</span>';
      // Escuridão, Névoa, Silêncio: a área cobre a zona inteira.
      const cobre = ((snap.zonas_efeito || {})[z] || []);
      return `<div class="cbt-zona${aqui}${cobre.length ? ' cbt-zona-coberta' : ''}" title="${esc(desc[z] || '')}">`
           + `<div class="cbt-zona-nome">${esc(z)}</div>`
           + (cobre.length ? `<div class="cbt-zona-efeito">${esc(cobre.join(' · '))}</div>` : '')
           + `<div class="cbt-zona-pins">${fichas || '<span class="cbt-zona-vazia">vazia</span>'}</div>`
           + `<div class="cbt-zona-conta">${conta}</div>`
           + `</div>`;
    }).join('<span class="cbt-zona-liga">→</span>');
    faixa.classList.remove('hidden');
  }

  function renderActionBar(snap) {
    const titleEl  = document.getElementById('cbt-action-title');
    const promptEl = document.getElementById('cbt-prompt');
    const btnEl    = document.getElementById('cbt-buttons');
    const tgtEl    = document.getElementById('cbt-targets');
    tgtEl.classList.add('hidden'); tgtEl.innerHTML = '';
    _pick = null; _confirmar = null;
    marcarLinhas({}, {});
    document.getElementById('cbt-actionbar').classList.remove('cbt-escolhendo');

    const cur = (snap.combatants || []).find(c => c.is_current);
    if (!cur) {
      titleEl.textContent = 'Aguardando…';
      promptEl.textContent = ''; btnEl.innerHTML = '';
      return;
    }

    // O turno do inimigo parou: uma reação em "perguntar" espera o jogador.
    const pend = snap.reacao_pendente;
    if (pend) {
      titleEl.textContent = `Reação de ${pend.quem}`;
      promptEl.innerHTML = `<span class="cbt-reacao-pergunta" role="alert">${esc(pend.texto)}</span>`;
      btnEl.innerHTML =
        `<button class="cbt-btn cbt-primary" style="--cbt-span:2" ${_busy ? 'disabled' : ''} `
        + `onclick="window.Combat._act({action:'reagir',weapon:'sim'})">Usar ${esc(pend.nome || '')}</button>`
        + `<button class="cbt-btn" style="--cbt-span:2" ${_busy ? 'disabled' : ''} `
        + `onclick="window.Combat._act({action:'reagir',weapon:'nao'})">Não usar</button>`;
      acompanharAlturaDaBarra();
      return;
    }

    if (!snap.current_is_party) {
      const aliado = lado(cur) === 'aliado';
      titleEl.textContent = aliado ? 'Turno do Aliado' : 'Turno do Inimigo';
      promptEl.innerHTML  = `<span class="cbt-enemy-msg">${aliado
        ? `“${esc(snap.current)} entra na luta ao seu lado…”`
        : `“${esc(snap.current)} avança nas sombras…”`}</span>`;
      btnEl.innerHTML = '';
      acompanharAlturaDaBarra();
      return;
    }

    titleEl.textContent = `O que fará ${cur.name}?`;
    // Invocação do grupo (Conjurar Animais, o familiar): o turno é do jogador,
    // com um atalho para o motor jogar por ela só esta vez.
    const botaoAuto = cur.controlada
      ? `<button class="cbt-btn" ${_busy ? 'disabled' : ''} title="O motor escolhe o alvo e ataca por ${esc(cur.name)}, só neste turno" `
        + `onclick="window.Combat._act({action:'auto',actor:'${jsNome(cur.name)}'})">Motor joga</button>`
      : '';

    // Paralisado, Atordoado, Banido: não age — a tela diz por quê e só
    // oferece encerrar o turno (o motor recusaria qualquer outra coisa).
    if (cur.impedido) {
      titleEl.textContent = `${cur.name} está ${cur.impedido}`;
      promptEl.innerHTML = `<span class="cbt-enemy-msg">${esc(cur.name)} não pode agir neste turno.</span>`;
      btnEl.innerHTML = `<button class="cbt-btn cbt-primary" style="--cbt-span:4" ${_busy ? 'disabled' : ''} `
        + `onclick="window.Combat._act({action:'end_turn',actor:'${jsNome(cur.name)}'})">Encerrar Turno</button>`;
      acompanharAlturaDaBarra();
      return;
    }

    // Economia 5e do turno atual: Ação, Ação Bônus e Reação.
    // Antes eram dois "○" minúsculos sem legenda, governando o turno inteiro.
    // A Reação é do combatente (uma por rodada) e vale FORA do próprio turno —
    // por isso vem do card dele, não do turn_economy.
    const eco       = snap.turn_economy || {};
    const acaoUsed  = !!eco.acao_usada;
    const bonusUsed = !!eco.bonus_usada;
    const reacaoOk  = cur.reacao_disponivel !== false;
    const slot = (rotulo, gasto, dica) =>
      `<span class="cbt-slot ${gasto ? 'gasto' : 'livre'}" title="${dica}">`
      + `<span class="cbt-pip"></span>${rotulo}</span>`;
    // Movimento só entra na régua quando o combate tem zonas — sem campo
    // dividido não há o que mover, e um selo permanentemente apagado só
    // confundiria.
    const temZonas  = (snap.zonas || []).length > 1;
    // Disparada de bônus (Ação Ardilosa) devolve movimento: com zona extra
    // sobrando, o movimento não está gasto.
    const moveExtra = Number(eco.movimento_extra || 0);
    const moveUsed  = !!eco.movimento_usado && moveExtra <= 0;
    // Ataque Extra: golpes da mesma ação Atacar que ainda faltam.
    const golpes    = Number(eco.ataques_restantes || 0);
    promptEl.innerHTML =
      slot('Ação', acaoUsed, acaoUsed ? 'Ação já usada neste turno' : 'Ação disponível')
      + slot('Bônus', bonusUsed, bonusUsed ? 'Ação bônus já usada neste turno' : 'Ação bônus disponível')
      + (temZonas ? slot('Movimento', moveUsed, moveUsed
             ? 'Já se moveu neste turno'
             : 'Movimento disponível — não custa a Ação') : '')
      + slot('Reação', !reacaoOk, reacaoOk
             ? 'Reação disponível — usada fora do seu turno (ex.: ataque de oportunidade)'
             : 'Reação já gasta nesta rodada');

    const dis      = _busy ? 'disabled' : '';
    const actorEsc = jsNome(cur.name);
    const acaoDis  = (acaoUsed || _busy) ? 'disabled' : '';

    const hasAcaoAbil  = (cur.habilidades || []).some(h => h.tipo_acao === 'acao');
    const hasBonusAbil = (cur.habilidades || []).some(h => h.tipo_acao === 'bonus');
    const hasLivreAbil = (cur.habilidades || []).some(h => h.tipo_acao === 'livre');
    // Item sem efeito conhecido aparece na lista, mas não conta como opção.
    const itensUsaveis = (cur.itens_combate || []).filter(i => i.usavel !== false);
    const hasAcaoItem  = itensUsaveis.some(i => i.tipo_acao !== 'bonus');
    const hasBonusItem = itensUsaveis.some(i => i.tipo_acao === 'bonus');
    const habUsable  = (hasAcaoAbil && !acaoUsed) || (hasBonusAbil && !bonusUsed) || hasLivreAbil;
    const itemUsable = (hasAcaoItem && !acaoUsed) || (hasBonusItem && !bonusUsed);
    const atkDis = ((acaoUsed && golpes <= 0) || _busy) ? 'disabled' : '';

    const botoes = [
      `<button class="cbt-btn" ${atkDis} onclick="window.Combat._sel('attack')">Atacar${
        golpes > 0 ? ` <small>· mais ${golpes}</small>` : ''}</button>`,
    ];
    if ((cur.habilidades || []).length) {
      const d = (habUsable && !_busy) ? '' : 'disabled';
      botoes.push(`<button class="cbt-btn" ${d} onclick="window.Combat._sel('ability')">Habilidade</button>`);
    }
    if ((cur.itens_combate || []).length) {
      const d = (itemUsable && !_busy) ? '' : 'disabled';
      botoes.push(`<button class="cbt-btn" ${d} onclick="window.Combat._sel('item')">Item</button>`);
    }
    if (temZonas) {
      const d = (moveUsed || _busy) ? 'disabled' : '';
      botoes.push(`<button class="cbt-btn" ${d} onclick="window.Combat._sel('move')">Mover</button>`);
    }
    botoes.push(
      `<button class="cbt-btn" ${acaoDis} onclick="window.Combat._manobras()" title="Defender, Ajudar, Esconder-se, Agarrar, Empurrar, Preparar, Fugir">Manobras</button>`,
      `<button class="cbt-btn" ${dis} onclick="window.Combat._free()">Ação Livre</button>`);
    if (botaoAuto) botoes.push(botaoAuto);
    // No celular a grade tem 4 colunas: o "Encerrar Turno" ocupa o que sobra
    // da última fileira, e nunca menos de duas colunas — numa só o rótulo
    // quebrava em duas linhas.
    const sobra = botoes.length % 4;
    const vao = sobra === 0 ? 4 : (4 - sobra >= 2 ? 4 - sobra : 4);
    btnEl.innerHTML = botoes.join('')
      + `<button class="cbt-btn cbt-primary" style="--cbt-span:${vao}" ${dis} onclick="window.Combat._act({action:'end_turn',actor:'${actorEsc}'})">Encerrar Turno</button>`
      + linhaDeReacoes(cur);
    acompanharAlturaDaBarra();
  }

  // Reações no turno do inimigo (Escudo Arcano, Esquiva Sobrenatural,
  // Indomável...). Cada uma tem três modos, num toque cada: o motor usa
  // sozinho quando faz diferença ("automática"), o turno do inimigo para e
  // pergunta ("pergunta"), ou nunca ("desligada").
  const MODO_DA_REACAO = { auto: 'automática', perguntar: 'pergunta', desligada: 'desligada' };
  function modoDe(r) { return r.modo || (r.ligada ? 'auto' : 'desligada'); }
  function proximoModo(r) {
    const m = modoDe(r);
    if (m === 'auto') return r.pode_perguntar ? 'perguntar' : 'desligada';
    return m === 'perguntar' ? 'desligada' : 'auto';
  }
  function linhaDeReacoes(cur) {
    const lista = (cur && cur.reacoes) || [];
    if (!lista.length) return '';
    return `<div class="cbt-reacoes" role="group" aria-label="Reações">`
      + `<span class="cbt-reacoes-titulo" title="No turno do inimigo: automática (o motor usa quando faz diferença), pergunta (o turno para e você decide) ou desligada">Reações:</span>`
      + lista.map(r => {
          const m = modoDe(r);
          const classe = m === 'auto' ? 'ligada' : (m === 'perguntar' ? 'pergunta' : 'desligada');
          return `<button type="button" class="cbt-reacao-chip ${classe}" `
            + `aria-pressed="${m !== 'desligada' ? 'true' : 'false'}" ${_busy ? 'disabled' : ''} `
            + `onclick="window.Combat._reacao('${jsNome(cur.name)}','${jsNome(r.chave)}','${proximoModo(r)}')">`
            + `${esc(r.nome)}<small>${MODO_DA_REACAO[m]}</small></button>`;
        }).join('')
      + `</div>`;
  }

  // Golpe não letal: o corpo a corpo que derruba o inimigo nocauteia (fica
  // estável, vivo) em vez de matar. Liga e desliga sem gastar o turno. Mora
  // no seletor de arma do Atacar, que é onde a escolha importa — na barra,
  // uma linha a mais escondia o último combatente no celular.
  async function _naoLetal(ator, valor) {
    if (_busy) return;
    try {
      const res = await doAction({ action: 'nao_letal', actor: ator, weapon: valor });
      if (res && res.message && window.showToast) window.showToast(res.message);
      if (res && res.snapshot) await refresh(res.snapshot);
      _sel('attack');
    } catch (_) {
      if (window.showToast) window.showToast('Falha de conexão no combate.');
    }
  }

  function linhaNaoLetal(cur) {
    if (!cur) return '';
    const on = !!cur.nao_letal;
    return `<div class="cbt-reacoes" role="group" aria-label="Golpe não letal">`
      + `<button type="button" class="cbt-reacao-chip cbt-nao-letal ${on ? 'ligada' : 'desligada'}" `
      + `aria-pressed="${on ? 'true' : 'false'}" ${_busy ? 'disabled' : ''} `
      + `title="Golpe corpo a corpo que derruba: ${on ? 'nocauteia (estável, não morre)' : 'mata o inimigo'}" `
      + `onclick="window.Combat._naoLetal('${jsNome(cur.name)}','${on ? 'nao' : 'sim'}')">`
      + `Golpe não letal<small>${on ? 'nocauteia' : 'desligado'}</small></button></div>`;
  }

  async function _reacao(ator, chave, modo) {
    if (_busy) return;
    // Compatível com quem chama com booleano (ligada / desligada).
    if (modo === true) modo = 'auto';
    if (modo === false) modo = 'desligada';
    try {
      const res = await api('/api/combat/reacao', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor: ator, reacao: chave, ligada: modo !== 'desligada', modo }),
      });
      if (res && res.message && window.showToast) window.showToast(res.message);
      if (res && res.snapshot) await refresh(res.snapshot);
    } catch (_) {
      if (window.showToast) window.showToast('Falha de conexão no combate.');
    }
  }

  // Marca as linhas dos combatentes: `alvos` (nome → 'ok'|'fora'|...) diz
  // quem pode ser escolhido tocando a linha; `area` (nome → 'aliado'|'inimigo')
  // pinta quem a magia em área vai atingir.
  function marcarLinhas(alvos, area) {
    document.querySelectorAll('#combat-overlay .cbt-card[data-nome]').forEach(el => {
      const n = el.dataset.nome;
      const estado = alvos[n];
      el.classList.toggle('cbt-alvejavel', !!estado && estado !== 'fora' && estado !== 'sem_efeito');
      el.classList.toggle('cbt-inalcancavel', estado === 'fora' || estado === 'sem_efeito');
      el.classList.toggle('cbt-na-area', !!area[n]);
      el.classList.toggle('cbt-na-area-aliado', area[n] === 'aliado');
    });
  }

  // Abre um seletor (arma, alvo, habilidade, item, zona) no painel de ação.
  // `folha`: no celular o painel vira uma folha alta e os botões de ação
  // saem de cena — a lista de magias não cabia na barra e rolava por dentro
  // de um espaço de três linhas.
  function abrirSeletor(html, folha) {
    const tgtEl = document.getElementById('cbt-targets');
    tgtEl.innerHTML = html;
    tgtEl.classList.remove('hidden');
    tgtEl.scrollTop = 0;
    document.getElementById('cbt-actionbar').classList.toggle('cbt-escolhendo', !!folha);
    trazerParaVista(tgtEl);
  }

  const BOTAO_CANCELAR =
    `<button class="cbt-btn cbt-cancel" onclick="window.Combat._cancel()">✕ Cancelar</button>`;

  // Quem a habilidade costuma mirar. Cura e reforço vão num aliado (ou em
  // si); dano e controle, num inimigo. A tela só ORDENA e sugere — quem
  // decide se pode é o motor.
  const MIRA_ALIADO = ['Cura', 'Reforço'];

  // Quantos alvos a habilidade deixa escolher: por círculo (Imobilizar
  // Pessoa: 2 no 3º; Mísseis Mágicos: um alvo por dardo) ou, sem zonas, pelo
  // tamanho da área (Bola de Fogo: 4).
  function maxAlvos(h, modo) {
    if (!h) return 1;
    const por = h.alvos_por_modo || {};
    const chaves = Object.keys(por);
    if (chaves.length) return Number(por[modo] || por[chaves[0]] || 1);
    return Number(h.max_alvos || 1);
  }

  function showTargets(kind, opts) {
    const snap = _last;
    if (!snap) return;
    _pick = Object.assign({ kind }, opts || {});
    const cur = (snap.combatants || []).find(c => c.is_current);
    const h   = _pick.hab || null;
    // A ação de classe e a magia de efeito dizem quem miram (alvo_modo):
    // Inspiração de Bardo num aliado, Marca do Caçador num inimigo.
    const apoio = !!(h && (h.alvo_modo === 'aliado'
      || (h.alvo_modo !== 'inimigo' && MIRA_ALIADO.includes(h.rotulo))));
    let live = (snap.combatants || []).filter(c =>
      !isOut(c.status) && (apoio || c.name !== (cur && cur.name)));
    // O lado que a habilidade costuma mirar vem primeiro.
    const querAliado = apoio;
    live = live.slice().sort((a, b) =>
      (comOGrupo(b) === querAliado) - (comOGrupo(a) === querAliado));
    const titulo = kind === 'manobra'
      ? `${esc(_pick.rotulo || 'Manobra')}:`
      : kind === 'attack'
      ? `Alvo de ${esc(_pick.weapon || 'ataque')}:`
      : (kind === 'ability' ? `Alvo de ${esc((h && h.nome_exibido) || _pick.ability || 'habilidade')}:` : 'Alvo:');
    // Alcance de cada alvo para a arma escolhida, calculado pelo motor. Sem
    // isto a tela oferecia o inimigo de outra zona à espada, o motor recusava
    // e o jogador ficava sem entender o que tinha acontecido.
    const alcance = kind === 'attack'
      ? ((snap.alcance || {})[_pick.weapon || 'Ataque desarmado'] || {})
      : {};
    const estados = {};
    const circulos = (h && (h.modos || []).length && h.modos.every(m => /^c\d+$/.test(m.id)))
      ? h.modos : [];
    const chips = circulos.length
      ? `<div class="cbt-circulos" role="group" aria-label="Círculo">`
        + circulos.map(m => `<button type="button" class="cbt-circulo${(_pick.modo || circulos[0].id) === m.id ? ' ativo' : ''}" `
          + `data-modo="${esc(m.id)}" onclick="window.Combat._circulo('${jsNome(m.id)}')">`
          + `${esc(m.texto.split(':')[0])}<small>${esc(m.texto.split(':').slice(1).join(':'))}</small></button>`).join('')
        + `</div>`
      : '';
    // Vários alvos: cada toque marca ou desmarca, e o botão confirma.
    const maxN = kind === 'ability' ? maxAlvos(h, _pick.modo || (circulos[0] ? circulos[0].id : '')) : 1;
    _pick.max = maxN;
    _pick.sel = (_pick.sel || []).filter(n => live.some(c => c.name === n)).slice(0, maxN);
    const dardos = !!(h && h.projeteis);
    const quantos = (n) => (_pick.sel || []).filter(x => x === n).length;
    const sel = maxN > 1 ? _pick.sel : [];
    const html =
      `<div class="cbt-tgt-title">${titulo}${maxN > 1 ? ` <small>· até ${maxN} alvos</small>` : ''}</div>`
      + (h && h.resumo ? `<div class="cbt-tgt-resumo">${esc(h.resumo)}</div>` : '')
      + chips
      + `<div class="cbt-tgt-dica">${maxN > 1
          ? `Toque para marcar até ${maxN} alvos e confirme.`
          : 'Toque no combatente ou escolha abaixo.'}</div>`
      + `<div class="cbt-picker-btns">`
      + live.map(c => {
          const estado = alcance[c.name];
          estados[c.name] = estado || 'ok';
          const fora   = estado === 'fora';
          const nota   = fora ? ' <small>· fora de alcance</small>'
                       : (estado === 'desvantagem' ? ' <small>· desvantagem</small>' : '');
          const dica   = fora
            ? ` title="${esc(c.name)} está em ${esc(c.zona || 'outra zona')}: corpo-a-corpo só na mesma zona. Mova-se ou use uma arma à distância."`
            : '';
          const quem = c.name === (cur && cur.name) ? ' (em si)' : '';
          const marcado = sel.includes(c.name);
          const vezes = dardos ? quantos(c.name) : 0;
          const nVezes = vezes > 1 ? ` <small>×${vezes}</small>` : '';
          return `<button class="cbt-btn ${comOGrupo(c) ? 'cbt-alvo-aliado' : 'cbt-alvo-inimigo'}${fora ? ' cbt-fora' : ''}${marcado ? ' cbt-selecionado' : ''}" ${fora ? 'disabled' : ''}${dica} `
            + (maxN > 1 ? `aria-pressed="${marcado ? 'true' : 'false'}" data-vezes="${vezes}" ` : '')
            + `onclick="window.Combat._target('${jsNome(c.name)}')">${esc(c.name)}${quem}${nVezes}`
            + ` <small>${c.hp}/${c.hp_max}</small>${nota}</button>`;
        }).join('')
      + (_pick.permiteNenhum
          ? `<button class="cbt-btn" onclick="window.Combat._target('')">O primeiro que chegar</button>` : '')
      + (maxN > 1 && dardos && sel.length
          ? `<button class="cbt-btn" onclick="window.Combat._desfazerAlvo()">Desfazer o último</button>` : '')
      + (maxN > 1
          ? `<button class="cbt-btn cbt-primary" ${sel.length ? '' : 'disabled'} onclick="window.Combat._confirmarAlvos()">`
            + `Confirmar (${sel.length}/${maxN}${dardos ? ' dardos' : ''})</button>` : '')
      + BOTAO_CANCELAR
      + `</div>`;
    abrirSeletor(html, false);
    marcarLinhas(estados, {});
  }

  function _desfazerAlvo() {
    if (!_pick || !(_pick.sel || []).length) return;
    showTargets('ability', Object.assign({}, _pick, { sel: _pick.sel.slice(0, -1) }));
  }

  function _confirmarAlvos() {
    if (_busy || !_pick || !(_pick.sel || []).length) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    const nomes = _pick.sel.join(', ');
    const h = _pick.hab || { nome: _pick.ability };
    if (_pick.mode === 'area' || _pick.mode === 'area_self')
      conferirArea(cur, h, nomes, _pick.modo || '');
    else
      act({ action: 'ability', actor: cur.name, ability: _pick.ability, target: nomes,
            weapon: _pick.modo || '' });
  }

  // No mobile o painel de ação é uma barra fixa que rola por dentro: se o
  // seletor abre além da altura dela, o jogador toca e não vê nada mudar.
  // `block: 'nearest'` só rola o necessário e não mexe se já estiver visível.
  function trazerParaVista(el) {
    if (!el) return;
    // Fora do rAF de propósito: o seletor já está no DOM e visível, então a
    // barra já tem a altura nova. Dentro do rAF a reserva de espaço ficaria
    // refém do ciclo de renderização (que não roda com a aba oculta).
    acompanharAlturaDaBarra();
    requestAnimationFrame(() => {
      try { el.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
      catch (_) { el.scrollIntoView(false); }
    });
  }

  // A barra de ação do mobile é `position: fixed`, então o conteúdo do frame
  // passa por trás dela. O CSS reserva esse espaço com
  // `padding-bottom: calc(var(--cbt-bar-h) + 16px)`, mas a altura da barra
  // varia bastante — ela cresce quando um seletor (arma, alvo, item) abre.
  // Sem medir, ou sobra um vão enorme ou o diário fica inalcançável.
  let _obsBarra = null;
  function acompanharAlturaDaBarra() {
    const painel = document.querySelector('.cbt-action-panel');
    const frame  = document.getElementById('cbt-frame');
    if (!painel || !frame) return;
    const medir = () => {
      const h = painel.getBoundingClientRect().height;
      if (h > 0) frame.style.setProperty('--cbt-bar-h', h + 'px');
    };
    // Mede já: o ResizeObserver só entrega no ciclo de renderização, que fica
    // suspenso enquanto a aba está oculta. Sem esta medida direta o respiro
    // dependeria dele para existir.
    medir();
    if (_obsBarra || typeof ResizeObserver === 'undefined') return;
    _obsBarra = new ResizeObserver(medir);   // a barra cresce quando um seletor abre
    _obsBarra.observe(painel);
  }

  // ---- Loop / sincronização ---------------------------------------
  let _last = null;

  function _pill() { return document.getElementById('cbt-reopen'); }

  async function refresh(snap) {
    _last = snap;
    const pill = _pill();

    if (snap.is_active) {
      // Reabre sozinho — exceto se o usuário fechou a tela de propósito.
      if (!_open && !_userClosed) openOverlay();
      if (_open) {
        if (pill) pill.classList.add('hidden');
        render(snap);
        if (!snap.current_is_party && !snap.reacao_pendente && !_busy) {
          clearTimeout(_autoTimer);
          if (_autoGuard++ < 80) {
            _autoTimer = setTimeout(() => act({ action: 'enemy' }), 650);
          }
        } else {
          _autoGuard = 0;
        }
      } else if (_userClosed && pill) {
        // Tela fechada pelo usuário, mas o combate segue ativo → pílula.
        pill.classList.remove('hidden');
      }
    } else if (snap.result && _open) {
      clearTimeout(_autoTimer); _autoGuard = 0;
      render(snap);
      renderResult(snap.result);
    } else if (_open) {
      _antes = null;
      close(true);
    } else {
      // Combate inativo e a tela já fechada — limpa o estado.
      _antes = null;
      _userClosed = false;
      if (pill) pill.classList.add('hidden');
    }
  }

  function renderResult(res) {
    const tgtEl = document.getElementById('cbt-targets');
    tgtEl.classList.add('hidden'); tgtEl.innerHTML = '';

    const isWin = res.outcome === 'vitoria';
    const titulos = { fuga: 'Fuga', interrompido: 'Luta encerrada' };
    const lista = (arr, fallen) => (arr || []).map(c =>
      `<li><span>${esc(c.name)}</span>`
      + `<span>${fallen ? esc(c.status) : (c.hp + '/' + c.hp_max)}</span></li>`
    ).join('') || '<li class="cbt-empty">—</li>';

    const ov = document.getElementById('cbt-end-overlay');
    ov.innerHTML = `
      <div class="cbt-end-modal">
        <h2 class="cbt-result-title ${isWin ? 'win' : 'lose'}">
          ${isWin ? CRISTA_VITORIA : CRISTA_DERROTA}${esc(res.title || titulos[res.outcome] || (isWin ? 'Vitória!' : 'Fim do combate'))}
        </h2>
        <div class="cbt-result-cols">
          <div class="cbt-end-col">
            <h3>De pé</h3>
            <ul class="cbt-end-list">${lista(res.sobreviventes, false)}</ul>
          </div>
          <div class="cbt-end-col cbt-end-col-foe">
            <h3>Caídos</h3>
            <ul class="cbt-end-list">${lista(res.caidos, true)}</ul>
          </div>
          ${(res.poupados || []).length ? `<div class="cbt-end-col cbt-end-col-poupados">
            <h3>Poupados</h3>
            <ul class="cbt-end-list">${lista(res.poupados, true)}</ul>
          </div>` : ''}
        </div>
        <div class="cbt-end-actions">
          <button class="cbt-btn" onclick="window.Combat._closeOnly()">Apenas fechar</button>
          <button class="cbt-btn cbt-primary" onclick="window.Combat._continue()">Continuar a história ▶</button>
        </div>
      </div>`;
    ov.classList.remove('hidden');
    _antes = null;
    _vezAntes = null;
  }

  async function sync() {
    if (_busy) return;
    try {
      const snap = await getState();
      if (snap && typeof snap === 'object') await refresh(snap);
    } catch (_) { /* silencioso — tenta de novo no próximo refreshMemory */ }
  }

  async function act(payload) {
    if (_busy) return;
    _busy = true;
    clearTimeout(_autoTimer);
    try {
      renderActionBar(_last || {});
      const res = await doAction(payload);
      if (res && !res.ok && res.message) {
        // O motor escreve em markdown para o chat; no aviso os ** apareceriam.
        const first = String(res.message).split('\n')[0].replace(/\*\*/g, '').slice(0, 160);
        if (window.showToast) window.showToast(first);
      }
      _busy = false;
      if (res && res.snapshot) await refresh(res.snapshot);
      else await sync();
    } catch (e) {
      _busy = false;
      if (window.showToast) window.showToast('Falha de conexão no combate.');
    }
  }

  // ---- Abrir / fechar ---------------------------------------------
  function openOverlay() {
    ensureDom();
    _entrando = _antes === null;
    document.getElementById('combat-overlay').classList.remove('hidden');
    document.body.classList.add('combat-on');
    _open = true; _autoGuard = 0;
  }

  function close(triggerRecap) {
    clearTimeout(_autoTimer);
    const el = document.getElementById('combat-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('combat-on');
    _open = false;
    // A fila de telas (game.js) espera o combate: nível e loja não abrem
    // sozinhas por cima dele. Fechou, é a vez delas.
    window.dispatchEvent(new Event('rpg:tela-fechou'));
    if (triggerRecap && !_ending) {
      _ending = true;
      finishWithNarration().finally(() => { _ending = false; });
    }
  }

  async function finishWithNarration() {
    try {
      const r = await api('/api/combat/recap');
      const txt = (r && r.text) ? r.text : '[COMBATE RESOLVIDO NA TELA TÁTICA] Narre a luta e o saque.';
      if (typeof window.sendToAgent === 'function') {
        await window.sendToAgent(txt, true, 'tela');
      }
    } catch (_) {
      if (window.showToast) window.showToast('Combate encerrado.');
    }
  }

  // ---- Cartões de habilidade ---------------------------------------
  // Classe de cor por efeito: a cor diz de relance se a magia fere, cura ou
  // controla — e o rótulo escrito diz o mesmo, para não depender só da cor.
  const COR_DO_EFEITO = {
    'Dano': 'dano', 'Cura': 'cura', 'Controle': 'controle', 'Reforço': 'reforco',
    'Invocação': 'invocacao', 'Utilidade': 'util',
  };

  function travaDaHabilidade(h, cur, eco) {
    if (h.usos_max != null && h.usos <= 0) return 'sem usos até o descanso';
    if ((h.custo_mana || 0) > (cur.mp || 0)) return `mana insuficiente (${cur.mp || 0}/${h.custo_mana})`;
    if (h.tipo_acao === 'bonus' && eco.bonus_usada) return 'ação bônus já usada';
    if (h.tipo_acao === 'acao' && eco.acao_usada) return 'ação já usada';
    // Sacerdote de Guerra, Rajada de Golpes: só depois da ação Atacar.
    if (h.exige_ataque && !eco.atacou) return 'ataque primeiro (ação Atacar)';
    return '';
  }

  // O que acontece quando se usa, em uma linha (rpg/resolucao.py). É a
  // resposta para "isso faz alguma coisa no combate?" antes de gastar o turno.
  const SELO_DA_RESOLUCAO = {
    efeito: ['efeito', 'o motor aplica o efeito nos ataques, na CA ou nas salvaguardas'],
    acao_de_classe: ['regra de classe', 'o motor resolve pela regra da classe'],
    narrativa: ['o Mestre decide', 'sem regra no motor: você descreve, o Mestre narra o efeito'],
  };

  function cartaoDeHabilidade(h, i, cur, eco) {
    const cor    = COR_DO_EFEITO[h.rotulo] || 'util';
    const trava  = travaDaHabilidade(h, cur, eco);
    const resumo = String(h.resumo || '');
    // O resumo do motor começa pelo rótulo ("Dano 8d6 fogo · ..."); o rótulo
    // já vai no selo colorido, então sai do texto.
    const resto  = (h.rotulo && resumo.startsWith(h.rotulo))
      ? resumo.slice(h.rotulo.length).trim() : resumo;
    const custo = [
      h.custo_mana ? `${h.custo_mana} mana` : '',
      h.usos_max != null ? `${h.usos}/${h.usos_max} usos` : '',
    ].filter(Boolean).join(' · ') || 'sem custo';
    const fogoAmigo = h.alvos === 'todos'
      ? `<span class="cbt-hab-aviso" title="Atinge todos na área, aliados inclusive">atinge aliados</span>` : '';
    const ficha = [
      h.alcance ? ['Alcance', h.alcance] : null,
      h.area ? ['Área', h.area] : null,
      h.salvaguarda ? ['Salvaguarda', h.salvaguarda] : null,
      h.concentracao ? ['Duração', 'concentração'] : null,
      h.reacao ? ['Uso', 'reação'] : null,
    ].filter(Boolean).map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
    const nome = h.nome_exibido || h.nome;
    const selo = SELO_DA_RESOLUCAO[h.resolucao];
    const comoResolve = h.resolucao_texto && h.resolucao !== 'motor'
      ? `<span class="cbt-hab-como cbt-como-${esc(h.resolucao)}">${esc(h.resolucao_texto)}</span>`
      : (h.resolucao_texto ? `<span class="cbt-hab-como">${esc(h.resolucao_texto)}</span>` : '');
    return `<div class="cbt-hab cbt-ef-${cor}${trava ? ' cbt-hab-travada' : ''}${
      h.resolucao === 'narrativa' ? ' cbt-hab-narrativa' : ''}" data-resolucao="${esc(h.resolucao || 'motor')}">
      <div class="cbt-hab-cabeca">
      <button class="cbt-btn cbt-hab-usar" ${trava || _busy ? 'disabled' : ''}
              onclick="window.Combat._usarHab(${i})">
        <span class="cbt-hab-topo">
          <span class="cbt-hab-nome">${esc(nome)}</span>
          ${h.reacao ? '<em class="cbt-eco-tag eco-reacao" title="No jogo de mesa é uma reação, usada fora do seu turno">reação</em>' : ''}
          ${selo ? `<em class="cbt-eco-tag cbt-selo-${esc(h.resolucao)}" title="${esc(selo[1])}">${esc(selo[0])}</em>` : ''}
        </span>
        <span class="cbt-hab-linha">
          <span class="cbt-hab-efeito">${esc(h.rotulo || 'Utilidade')}</span>
          <span class="cbt-hab-resumo">${esc(resto || h.dado || '')}</span>
        </span>
        ${comoResolve}
        <span class="cbt-hab-pe">
          <span class="cbt-hab-custo">${esc(custo)}</span>${fogoAmigo}
          ${trava ? `<span class="cbt-hab-trava">${esc(trava)}</span>` : ''}
        </span>
      </button>
      <button class="cbt-hab-info" type="button" aria-expanded="false"
              aria-controls="cbt-hab-desc-${i}" onclick="window.Combat._info(${i})">Detalhes</button>
      </div>
      <div id="cbt-hab-desc-${i}" class="cbt-hab-desc hidden">
        ${ficha ? `<dl class="cbt-hab-ficha">${ficha}</dl>` : ''}
        <p>${esc(h.descricao || 'Sem descrição na ficha.')}</p>
        ${nome !== h.nome ? `<p class="cbt-hab-origem">Na ficha: ${esc(h.nome)}</p>` : ''}
      </div>
    </div>`;
  }

  function seletorDeHabilidades(cur) {
    const eco = (_last || {}).turn_economy || {};
    _habs = (cur && cur.habilidades) || [];
    // Agrupadas pelo que gastam: o jogador procura "o que ainda posso fazer
    // com a ação bônus", não a ordem em que a ficha listou.
    const grupos = [['acao', 'Ação'], ['bonus', 'Ação bônus'], ['livre', 'Sem custo de ação']];
    const html = grupos.map(([slot, titulo]) => {
      const itens = _habs
        .map((h, i) => [h, i])
        .filter(([h]) => (['bonus', 'livre'].includes(h.tipo_acao) ? h.tipo_acao : 'acao') === slot);
      if (!itens.length) return '';
      return `<div class="cbt-hab-grupo"><div class="cbt-hab-grupo-titulo">${titulo}</div>`
        + `<div class="cbt-hab-lista">${itens.map(([h, i]) => cartaoDeHabilidade(h, i, cur, eco)).join('')}</div></div>`;
    }).join('');
    abrirSeletor(
      `<div class="cbt-tgt-title cbt-folha-titulo"><span>Habilidade:</span>${BOTAO_CANCELAR}</div>` + html,
      true);
  }

  function _info(i) {
    const desc = document.getElementById(`cbt-hab-desc-${i}`);
    if (!desc) return;
    const abre = desc.classList.contains('hidden');
    desc.classList.toggle('hidden', !abre);
    const botao = desc.parentElement && desc.parentElement.querySelector('.cbt-hab-info');
    if (botao) {
      botao.setAttribute('aria-expanded', abre ? 'true' : 'false');
      botao.textContent = abre ? 'Fechar' : 'Detalhes';
    }
    // A descrição abre abaixo do cartão: no fim da lista ela nasceria fora
    // da folha, e o toque pareceria não fazer nada.
    if (abre) {
      try { desc.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
      catch (_) { desc.scrollIntoView(false); }
    }
  }

  // ---- Ações expostas aos botões ----------------------------------
  function _sel(kind) {
    if (_busy) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    // Os dois painéis dividem o mesmo espaço sob os botões: escolher arma ou
    // alvo tira da tela o pedido de Ação Livre pela metade.
    _livreFechar();
    _confirmar = null;
    marcarLinhas({}, {});

    if (kind === 'attack') {
      const armas = (cur && cur.armas) || [];
      if (!armas.length) return showTargets('attack', { weapon: 'Ataque desarmado' });
      abrirSeletor(
        `<div class="cbt-tgt-title">Arma:</div>`
        + linhaNaoLetal(cur)
        + `<div class="cbt-picker-btns">`
        + armas.map(w =>
            `<button class="cbt-btn" title="${esc(w.origem)}" onclick="window.Combat._selWeapon('${jsNome(w.nome)}')">`
            + `${esc(w.nome)}<small> · ${esc(w.origem)}</small></button>`
          ).join('')
        + BOTAO_CANCELAR
        + `</div>`, false);
      return;
    }

    const eco = (_last || {}).turn_economy || {};
    const dis = slot => (slot === 'bonus' ? eco.bonus_usada : eco.acao_usada) ? 'disabled' : '';
    const tag = slot => slot === 'bonus' ? 'Bônus' : 'Ação';

    if (kind === 'move') {
      const snap  = _last || {};
      const zonas = snap.zonas || [];
      const aqui  = (cur && cur.zona) || '';
      const i     = zonas.indexOf(aqui);
      // O movimento do turno alcança uma zona, mais as da Disparada de
      // bônus (Ação Ardilosa). Uma zona além disso exige a Disparada de
      // Ação — essas somem quando a Ação já foi gasta.
      const livres = (eco.movimento_usado ? 0 : 1) + Number(eco.movimento_extra || 0);
      const opcoes = zonas
        .map((z, j) => ({ z, passos: i < 0 ? 1 : Math.abs(j - i) }))
        .filter(o => o.passos >= 1
                  && (o.passos <= livres || (o.passos === livres + 1 && !eco.acao_usada)))
        .map(o => Object.assign(o, { dash: o.passos > livres }));
      if (!opcoes.length) {
        if (window.showToast) window.showToast('Nenhuma zona ao alcance.');
        return;
      }
      abrirSeletor(
        `<div class="cbt-tgt-title">Mover para${aqui ? ' (de ' + esc(aqui) + ')' : ''}:</div>`
        + `<div class="cbt-picker-btns">`
        + opcoes.map(o => {
            const dash = o.dash;
            // Avisa quem espera la: entrar numa zona ocupada tranca o
            // combatente, e sair depois provoca ataque de oportunidade.
            const ocupada = (snap.combatants || [])
              .filter(c => c.zona === o.z && !isOut(c.status)
                        && comOGrupo(c) !== comOGrupo(cur))
              .map(c => c.name);
            const risco = ocupada.length ? ` <small>· ${esc(ocupada.join(', '))}</small>` : '';
            return `<button class="cbt-btn" onclick="window.Combat._mover('${jsNome(o.z)}',${dash})">`
                 + `${esc(o.z)}${risco}`
                 + (dash ? ` <em class="cbt-eco-tag eco-acao">Disparada</em>` : '')
                 + `</button>`;
          }).join('')
        + BOTAO_CANCELAR
        + `</div>`, false);
      return;
    }

    if (kind === 'item') {
      const itens = (cur && cur.itens_combate) || [];
      if (!itens.length) {
        if (window.showToast) window.showToast('Nenhum item utilizável no combate.');
        return;
      }
      abrirSeletor(
        `<div class="cbt-tgt-title">Item:</div>`
        + `<div class="cbt-picker-btns">`
        + itens.map(it => {
            // O que o motor não sabe resolver fica travado e diz por quê:
            // antes era gasto sem efeito nenhum.
            const conhecido = it.usavel !== false;
            const trava = conhecido ? dis(it.tipo_acao) : 'disabled';
            const dica  = conhecido ? (it.descricao || it.dice || '') : it.motivo;
            const nota  = conhecido
              ? `×${it.qtd}${it.dice ? ' · ' + esc(it.dice) : ''}`
              : `×${it.qtd} · efeito desconhecido`;
            return `<button class="cbt-btn${conhecido ? '' : ' cbt-fora cbt-item-desconhecido'}" ${trava} title="${esc(dica)}" `
              + `onclick="window.Combat._selItem('${jsNome(it.nome)}','${esc(it.kind)}')">`
              + `${esc(it.nome)} <small>${nota}</small>`
              + ` <em class="cbt-eco-tag eco-${it.tipo_acao}">${tag(it.tipo_acao)}</em></button>`;
          }).join('')
        + BOTAO_CANCELAR
        + `</div>`, false);
      return;
    }

    // Habilidade: escolhe qual, depois alvo
    if (!((cur && cur.habilidades) || []).length) {
      if (window.showToast) window.showToast('Nenhuma habilidade ativa disponível.');
      return;
    }
    seletorDeHabilidades(cur);
  }

  function _selItem(name, kind) {
    if (_busy) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    const it = (cur.itens_combate || []).find(i => i.nome === name) || {};
    if (it.usavel === false) {
      if (window.showToast) window.showToast(it.motivo || 'Efeito desconhecido.');
      return;
    }
    if (kind === 'si') {
      act({ action: 'item', actor: cur.name, item: name, target: cur.name });
      return;
    }
    if (kind !== 'heal' && kind !== 'arremesso') {
      act({ action: 'item', actor: cur.name, item: name });
      return;
    }
    // Poção: em si ou num aliado da mesma zona. Arremesso: qualquer outro na
    // zona ou na vizinha — aliado incluído (fogo amigo). Quem alcança quem
    // vem do motor (it.alvos); a tela só trava o que ele recusaria.
    _pick = { kind: 'item', item: name };
    const alvos = it.alvos || {};
    const nomes = Object.keys(alvos);
    const porNome = n => (_last.combatants || []).find(c => c.name === n) || {};
    const NOTA = { fora: 'fora de alcance', sem_efeito: 'sem efeito' };
    const lista = nomes.length
      ? nomes.map(n => {
          const estado = alvos[n];
          const c = porNome(n);
          const trava = estado !== 'ok';
          const dica = estado === 'fora'
            ? (kind === 'heal'
                ? `${n} está em ${c.zona || 'outra zona'}: a poção só chega a quem está na mesma zona.`
                : `${n} está em ${c.zona || 'outra zona'}: o arremesso alcança a própria zona ou a vizinha.`)
            : (estado === 'sem_efeito' ? `${name} só fere mortos-vivos e infernais.` : '');
          const extra = trava ? ` <small>· ${NOTA[estado]}</small>`
            : (kind === 'heal' ? ` <small>${c.hp}/${c.hp_max}</small>` : '');
          return `<button class="cbt-btn${trava ? ' cbt-fora' : ''}" ${trava ? 'disabled' : ''}`
            + (dica ? ` title="${esc(dica)}"` : '')
            + ` onclick="window.Combat._target('${jsNome(n)}')">`
            + `${esc(n)}${n === cur.name ? ' (em si)' : ''}${extra}</button>`;
        }).join('')
      : (kind === 'heal'
          ? `<button class="cbt-btn" onclick="window.Combat._target('${jsNome(cur.name)}')">${esc(cur.name)} (em si)</button>`
          : '<div class="cbt-empty">Ninguém ao alcance.</div>');
    abrirSeletor(
      `<div class="cbt-tgt-title">${kind === 'heal'
          ? (it.efeito === 'estabilizar' ? 'Estabilizar quem:' : 'Curar quem:')
          : `Alvo de ${esc(name)}:`}</div>`
      + `<div class="cbt-tgt-dica">Toque no combatente ou escolha abaixo.</div>`
      + `<div class="cbt-picker-btns">${lista}`
      + BOTAO_CANCELAR
      + `</div>`, false);
    marcarLinhas(nomes.length ? alvos : { [cur.name]: 'ok' }, {});
  }
  function _selWeapon(name) { showTargets('attack',  { weapon: name }); }

  // Usar a habilidade pelo cartão (índice em _habs).
  function _usarHab(i) {
    const h = _habs[i];
    if (h) _selHab(h.nome, h.target_mode || 'single');
  }

  // Ação de classe com escolha (Ação Ardilosa: disparada, desengajar,
  // esconder). A escolha viaja em `weapon`, como a Disparada do movimento.
  function seletorDeModos(cur, h) {
    _pick = { kind: 'modo', ability: h.nome, hab: h };
    abrirSeletor(
      `<div class="cbt-tgt-title">${esc(h.nome_exibido || h.nome)}:</div>`
      + `<div class="cbt-picker-btns cbt-modos">`
      + (h.modos || []).map(m =>
          `<button class="cbt-btn cbt-modo" onclick="window.Combat._modo('${jsNome(m.id)}')">`
          + `${esc(m.texto.split(':')[0])}<small>${esc(m.texto.includes(':') ? ':' + m.texto.split(':').slice(1).join(':') : '')}</small></button>`
        ).join('')
      + BOTAO_CANCELAR
      + `</div>`, false);
  }

  // Ajudar, Esconder-se, Agarrar, Empurrar, Preparar (e Escapar, quando
  // agarrado): as ações do SRD que antes só existiam na Ação Livre, sem a
  // regra. Todas gastam a Ação (rpg/manobras.py).
  const MANOBRAS = [
    ['defend', 'Defender', 'Esquivar: ataques contra você têm desvantagem até o seu próximo turno'],
    ['help', 'Ajudar', 'o próximo ataque de um aliado contra o alvo tem vantagem'],
    ['hide', 'Esconder-se', 'Furtividade contra a Percepção dos inimigos; escondido, o próximo ataque tem vantagem'],
    ['grapple', 'Agarrar', 'Atletismo contra Atletismo ou Acrobacia: o alvo não sai da zona'],
    ['shove:derrubar', 'Derrubar', 'Atletismo contra Atletismo ou Acrobacia: o alvo fica Caído'],
    ['shove:afastar', 'Empurrar', 'Atletismo contra Atletismo ou Acrobacia: o alvo vai para a zona vizinha'],
    ['ready', 'Preparar ataque', 'ataca quando o alvo for agir, ou o primeiro inimigo que chegar (usa a reação)'],
    ['mount', 'Montar', 'numa montaria do seu lado na sua zona: andam juntos (usa o movimento)'],
    ['dismount', 'Desmontar', 'descer da montaria (usa o movimento)'],
    ['light', 'Acender/apagar a tocha', 'interação com objeto: a sua zona fica clara'],
    ['ready:magia', 'Preparar magia', 'conjura agora (gasta a mana, segura na concentração) e solta quando o alvo agir'],
    ['cover', 'Buscar cobertura', 'atrás do que houver: +2 de CA (ou +5) contra quem ataca de longe; usa o movimento'],
    ['offhand', 'Ataque com a outra mão', 'depois de atacar com arma leve: a outra arma leve ataca (ação bônus)'],
    ['surrender:intimidar', 'Pedir rendição (Intimidação)', 'Intimidação contra a Sabedoria dele: rendido, larga as armas e sai da luta, vivo'],
    ['surrender:persuadir', 'Pedir rendição (Persuasão)', 'Persuasão contra a Sabedoria dele; enfeitiçado por vocês, com vantagem'],
    ['escape', 'Escapar', 'Atletismo ou Acrobacia contra o Atletismo de quem agarra'],
    ['flee', 'Fugir', 'sair do combate; quem está perto ganha ataque de oportunidade'],
    ['flee_all', 'Fugir em grupo', 'o grupo inteiro larga a luta: cada um provoca ataques de oportunidade; sem XP nem saque'],
    ['end', 'Encerrar a luta', 'acaba o combate agora; o Mestre decide e narra como (trégua, rendição, fuga)'],
  ];

  function _manobras() {
    if (_busy) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    _livreFechar();
    const agarrado = (cur.condicoes || []).some(c => /agarrad/i.test(String(c)));
    const temZonas = ((_last || {}).zonas || []).length > 1;
    const eco = (_last || {}).turn_economy || {};
    const lista = MANOBRAS.filter(([id]) =>
      (id !== 'escape' || agarrado) && (id !== 'shove:afastar' || temZonas)
      && (id !== 'offhand' || (eco.ataque_leve && !eco.bonus_usada && cur.outra_mao))
      && (id !== 'mount' || (!cur.montado_em && cur.pode_montar)) && (id !== 'dismount' || cur.montado_em)
      && (id !== 'light' || cur.tem_tocha)
      && (id !== 'ready:magia' || (cur.habilidades || []).some(h => h.tipo_acao === 'acao' && (h.efeito || h.resolucao === 'efeito'))));
    abrirSeletor(
      `<div class="cbt-tgt-title">Manobras <small>· gastam a Ação</small></div>`
      + `<div class="cbt-picker-btns cbt-modos">`
      + lista.map(([id, rotulo, dica]) =>
          `<button class="cbt-btn cbt-modo" data-manobra="${esc(id)}" onclick="window.Combat._manobra('${jsNome(id)}')">`
          + `${esc(rotulo)}<small>: ${esc(dica)}</small></button>`).join('')
      + BOTAO_CANCELAR
      + `</div>`, false);
  }

  // Preparar magia: escolhe a magia (de uma Ação) e depois o alvo, como no
  // Preparar ataque.
  function _prepararMagia(cur) {
    const magias = (cur.habilidades || []).filter(h => h.tipo_acao === 'acao' && (h.efeito || h.resolucao === 'efeito'));
    abrirSeletor(
      `<div class="cbt-tgt-title">Preparar qual magia? <small>· gasta a mana agora</small></div>`
      + `<div class="cbt-picker-btns">`
      + magias.map(h => `<button class="cbt-btn" ${h.custo_mana > (cur.mp || 0) ? 'disabled' : ''} `
          + `onclick="window.Combat._prepararMagiaEm('${jsNome(h.nome)}')">${esc(h.nome_exibido || h.nome)}`
          + `<small> · ${h.custo_mana || 0} mana</small></button>`).join('')
      + BOTAO_CANCELAR + `</div>`, false);
  }

  function _prepararMagiaEm(nome) {
    showTargets('manobra', { acao: 'ready', modo: 'magia:' + nome, rotulo: 'Preparar ' + nome, permiteNenhum: true });
  }

  function _manobra(id) {
    if (_busy) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    const [acao, modo] = id.split(':');
    const rotulo = (MANOBRAS.find(m => m[0] === id) || [id, id])[1];
    if (id === 'ready:magia') { _prepararMagia(cur); return; }
    if (acao === 'flee_all' || acao === 'end') {
      const rotuloC = acao === 'end' ? 'Encerrar a luta agora?' : 'O grupo inteiro foge?';
      const dica = acao === 'end'
        ? 'Os inimigos ainda de pé não contam como derrotados: o Mestre decide como a luta termina.'
        : 'Cada um provoca os ataques de oportunidade de quem está colado nele. Sem XP nem saque.';
      abrirSeletor(`<div class="cbt-tgt-title">${rotuloC}</div><div class="cbt-tgt-dica">${dica}</div>`
        + `<div class="cbt-picker-btns"><button class="cbt-btn cbt-perigo" `
        + `onclick="window.Combat._act({action:'${acao}',actor:'${jsNome(cur.name)}'})">`
        + `${acao === 'end' ? 'Encerrar' : 'Fugir'}</button>${BOTAO_CANCELAR}</div>`, false);
      return;
    }
    if (acao === 'hide' || acao === 'escape' || acao === 'defend' || acao === 'flee' || acao === 'cover'
        || acao === 'light' || acao === 'dismount') {
      act({ action: acao, actor: cur.name });
      return;
    }
    showTargets('manobra', { acao, modo: modo || '', rotulo, permiteNenhum: acao === 'ready' });
  }

  // Troca o círculo marcado no seletor de alvo.
  function _circulo(id) {
    if (!_pick) return;
    _pick.modo = id;
    // O círculo muda quantos alvos cabem: redesenha com a marcação que cabe.
    if (_pick.kind === 'ability' && _pick.hab && Object.keys(_pick.hab.alvos_por_modo || {}).length) {
      showTargets('ability', Object.assign({}, _pick));
      return;
    }
    document.querySelectorAll('#cbt-targets .cbt-circulo').forEach(b =>
      b.classList.toggle('ativo', b.dataset.modo === id));
  }

  function _modo(id) {
    if (_busy || !_pick || _pick.kind !== 'modo') return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    const h = _pick.hab || {};
    // A escolha (círculo, zona, aumentar/reduzir) e depois o alvo, pelo
    // caminho de sempre. A escolha segue em `weapon`.
    _selHab(_pick.ability, h.target_mode || 'single', id);
  }

  function _selHab(name, mode, modo) {
    if (_busy) return;
    const cur = (_last && _last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    let h = (cur.habilidades || []).find(x => x.nome === name) || { nome: name };
    // Sem regra no motor (Taumaturgia, Luz): o jogador diz o que quer, o
    // Mestre arbitra. Antes gastava a Ação e o motor respondia "usa X no
    // Orc!" sem efeito nenhum.
    if (h.resolucao === 'narrativa') {
      _free(h);
      return;
    }
    // Só círculos (conjurar com mais mana) e a magia pede alvo: os círculos
    // viram chips no seletor de alvo, com o base marcado — sem um toque a mais
    // em toda conjuração.
    const soCirculos = (h.modos || []).length > 0 && h.modos.every(m => /^c\d+$/.test(m.id));
    const precisaAlvo = !(h.alvo_modo === 'nenhum' || h.alvo_modo === 'si' || mode === 'self'
                          || mode === 'pool' || mode === 'area_self');
    if ((h.modos || []).length && modo === undefined && !(soCirculos && precisaAlvo)) {
      seletorDeModos(cur, h);
      return;
    }
    const w = modo || (soCirculos ? h.modos[0].id : '');
    // A escolha pode mudar o alvo (Finta: inimigo; Reagrupar: aliado).
    const alvoEscolha = (modo && ((h.modos || []).find(x => x.id === modo) || {}).alvo) || '';
    if (alvoEscolha && alvoEscolha !== h.alvo_modo) {
      h = Object.assign({}, h, { alvo_modo: alvoEscolha });
      if (alvoEscolha !== 'si') mode = 'single';
    }
    if (h.alvo_modo === 'nenhum') {
      act({ action: 'ability', actor: cur.name, ability: name, target: '', weapon: w });
      return;
    }
    if (mode === 'self' || h.alvo_modo === 'si') {
      act({ action: 'ability', actor: cur.name, ability: name, target: cur.name, weapon: w });
      return;
    }
    // Pool e área-que-nasce-no-conjurador não escolhem alvo: o motor sabe
    // onde a magia cai (a zona de quem conjura, ou os inimigos do pool).
    // Sem zonas, a área que nasce no conjurador também escolhe quem pega.
    if (mode === 'area_self' && maxAlvos(h, w) > 1) {
      showTargets('ability', { ability: name, hab: h, mode, modo: w });
      return;
    }
    if (mode === 'pool' || mode === 'area_self') {
      conferirArea(cur, h, '', w);
      return;
    }
    // Área posta à distância: o picker escolhe UMA criatura e a magia pega a
    // zona dela inteira — inclusive aliados que estejam lá.
    showTargets('ability', { ability: name, hab: h, mode, modo: w });
  }

  function _target(name) {
    if (_busy || !_pick) return;
    const cur = (_last.combatants || []).find(c => c.is_current);
    if (!cur) return;
    if (_pick.kind === 'ability' && (_pick.max || 1) > 1 && name) {
      const sel = (_pick.sel || []).slice();
      const i = sel.indexOf(name);
      // Dardos (Mísseis Mágicos): cada toque é um dardo, o mesmo alvo pode
      // levar vários; "Desfazer" tira o último.
      if (_pick.hab && _pick.hab.projeteis) { if (sel.length < _pick.max) sel.push(name); }
      else if (i >= 0) sel.splice(i, 1);
      else if (sel.length < _pick.max) sel.push(name);
      showTargets('ability', Object.assign({}, _pick, { sel }));
      return;
    }
    if (_pick.kind === 'manobra')
      act({ action: _pick.acao, actor: cur.name, target: name, weapon: _pick.modo || '' });
    else if (_pick.kind === 'attack')
      act({ action: 'attack', actor: cur.name, target: name, weapon: _pick.weapon || '' });
    else if (_pick.kind === 'item')
      act({ action: 'item', actor: cur.name, item: _pick.item, target: name });
    else if (_pick.mode === 'area')
      conferirArea(cur, _pick.hab || { nome: _pick.ability }, name, _pick.modo || '');
    else
      act({ action: 'ability', actor: cur.name, ability: _pick.ability, target: name,
            weapon: _pick.modo || '' });
  }

  // Antes de uma magia em área, pergunta ao motor quem ela vai atingir. Sem
  // aliado no caminho, conjura direto — perguntar toda vez seria só atrito.
  // Com aliado, mostra quem e pede confirmação: o fogo amigo é regra e
  // continua, mas nunca mais sem aviso.
  async function conferirArea(cur, h, alvo, modo) {
    const payload = { action: 'ability', actor: cur.name, ability: h.nome, target: alvo,
                      weapon: modo || '' };
    let p = null;
    try {
      p = await preverArea({ actor: cur.name, ability: h.nome, target: alvo });
    } catch (_) { p = null; }
    const aliados = (p && p.ok && p.aliados_atingidos) || [];
    // Sem prévia (rede), a regra escrita da magia decide: "todos" pede
    // confirmação, porque pode pegar aliado.
    const semPrevia = !(p && p.ok);
    if (!aliados.length && !(semPrevia && h.alvos === 'todos')) {
      act(payload);
      return;
    }
    _confirmar = payload;
    const atingidos = (p && p.atingidos) || [];
    const area = {};
    atingidos.forEach(a => { area[a.nome] = a.aliado ? 'aliado' : 'inimigo'; });
    const nome = esc(h.nome_exibido || h.nome);
    const lista = atingidos.length
      ? `<div class="cbt-area-lista">${atingidos.map(a =>
          `<span class="cbt-area-alvo ${a.aliado ? 'aliado' : 'inimigo'}">${esc(a.nome)}${a.aliado ? ' <small>aliado</small>' : ''}</span>`
        ).join('')}</div>`
      : '';
    const aviso = aliados.length
      ? `Aviso: ${aliados.length === 1 ? 'um aliado está' : aliados.length + ' aliados estão'} na área (${esc(aliados.join(', '))}). Quem estiver lá é atingido.`
      : 'Aviso: não foi possível prever a área. Esta magia atinge todos nela, aliados inclusive.';
    abrirSeletor(
      `<div class="cbt-tgt-title">${nome}${p && p.area ? ` <small>· ${esc(p.area)}${p.zona ? ' em ' + esc(p.zona) : ''}</small>` : ''}</div>`
      + `<div class="cbt-area-aviso" role="alert">${aviso}</div>`
      + lista
      + `<div class="cbt-picker-btns">`
      + `<button class="cbt-btn cbt-perigo" onclick="window.Combat._confirmarArea()">Conjurar mesmo assim</button>`
      + BOTAO_CANCELAR
      + `</div>`, false);
    marcarLinhas({}, area);
  }

  function _confirmarArea() {
    const p = _confirmar;
    _confirmar = null;
    if (p) act(p);
  }

  function _continue() { close(true); }   // dispara recap + narração
  function _closeOnly() { close(false); } // apenas fecha

  function _dismiss() {
    // Fecha a tela SEM encerrar o combate — libera o acesso ao menu/sair
    // do jogo. O combate fica pausado e pode ser retomado pela pílula.
    _userClosed = true;
    clearTimeout(_autoTimer);
    close(false);
    const pill = _pill();
    if (pill && _last && _last.is_active) {
      pill.classList.remove('hidden');
    }
  }
  function _reopen() {
    _userClosed = false;
    const pill = _pill();
    if (pill) pill.classList.add('hidden');
    sync();   // reabre e re-renderiza o estado atual
  }
  function _mover(zona, dash) {
    const cur = (_last && (_last.combatants || []).find(c => c.is_current)) || null;
    if (!cur) return;
    _cancel();
    // O "dash" viaja em `weapon` porque esse campo ja e o qualificador da
    // intencao no dispatcher (e ele que leva a arma no ataque).
    // `act` é o nome interno; `_act` só existe em window.Combat. Chamar
    // `_act` daqui lançava ReferenceError e o clique na zona não fazia nada.
    act({ action: 'move', actor: cur.name, target: zona,
           weapon: dash ? 'dash' : '' });
  }

  function _cancel() {
    const t = document.getElementById('cbt-targets');
    if (t) { t.classList.add('hidden'); t.innerHTML = ''; }
    const l = document.getElementById('cbt-livre');
    if (l && !l.classList.contains('hidden')) { l.classList.add('hidden'); l.innerHTML = ''; }
    const painel = document.getElementById('cbt-actionbar');
    if (painel) painel.classList.remove('cbt-escolhendo');
    _pick = null; _confirmar = null;
    marcarLinhas({}, {});
    acompanharAlturaDaBarra();
  }
  // ---- Ação Livre, sem sair da luta -------------------------------
  // Antes este botão FECHAVA a tela e mandava escrever no chat: o jogador
  // perdia o campo de batalha de vista para pedir uma manobra que o motor
  // não tem botão. Agora o pedido e a arbitragem acontecem aqui dentro; o
  // chat continua recebendo os dois, que é onde a crônica mora.
  //
  // Habilidade sem regra no motor (Taumaturgia, Luz) entra por aqui também:
  // o pedido já vem com o nome dela, e enviar gasta a habilidade no motor (a
  // Ação, a mana, o uso) antes de o Mestre narrar o efeito.
  let _livreHab = null;

  function _free(hab) {
    if (_busy) return;
    _cancel();
    const el = document.getElementById('cbt-livre');
    if (!el) return;
    _livreHab = (hab && hab.nome) ? hab : null;
    const nome = _livreHab ? (_livreHab.nome_exibido || _livreHab.nome) : '';
    const gasta = _livreHab ? [
      _livreHab.tipo_acao === 'bonus' ? 'a ação bônus' : (_livreHab.tipo_acao === 'livre' ? '' : 'a Ação'),
      _livreHab.custo_mana ? `${_livreHab.custo_mana} de mana` : '',
      _livreHab.usos_max != null ? 'um uso' : '',
    ].filter(Boolean).join(', ') : '';
    el.classList.remove('hidden');
    el.innerHTML =
      (_livreHab
        ? `<div class="cbt-picker-title">${esc(nome)} — o Mestre decide o efeito:</div>`
          + `<div class="cbt-livre-nota">O motor não tem regra para ${esc(nome)}. Diga o que você quer que aconteça`
          + `${gasta ? `; enviar gasta ${esc(gasta)}` : ''}.</div>`
        : '<div class="cbt-picker-title">Ação livre — o Mestre arbitra:</div>') +
      '<textarea id="cbt-livre-texto" class="cbt-livre-texto" rows="2" ' +
      'placeholder="Ex.: empurro a mesa contra o goblin e salto por cima"></textarea>' +
      '<div class="cbt-livre-botoes">' +
      '<button class="cbt-btn" onclick="window.Combat._livreFechar()">Cancelar</button>' +
      '<button class="cbt-btn cbt-primary" id="cbt-livre-enviar" ' +
      `onclick="window.Combat._livreEnviar()">${_livreHab ? 'Usar e pedir ao Mestre' : 'Pedir ao Mestre'}</button></div>` +
      '<div id="cbt-livre-resposta" class="cbt-livre-resposta hidden"></div>';
    const ta = document.getElementById('cbt-livre-texto');
    if (_livreHab) ta.value = `Uso ${nome}: `;
    ta.addEventListener('keydown', ev => {
      // Enter envia; Shift+Enter quebra linha, como no chat.
      if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); _livreEnviar(); }
      if (ev.key === 'Escape') { ev.preventDefault(); _livreFechar(); }
    });
    ta.focus();
    acompanharAlturaDaBarra();
  }

  function _livreFechar() {
    const el = document.getElementById('cbt-livre');
    if (el) { el.classList.add('hidden'); el.innerHTML = ''; }
    _livreHab = null;
    acompanharAlturaDaBarra();
  }

  async function _livreEnviar() {
    const ta = document.getElementById('cbt-livre-texto');
    const resp = document.getElementById('cbt-livre-resposta');
    if (!ta || !resp || _busy) return;
    const texto = (ta.value || '').trim();
    if (!texto) { ta.focus(); return; }

    const botao = document.getElementById('cbt-livre-enviar');
    if (botao) botao.disabled = true;
    ta.disabled = true;
    resp.classList.remove('hidden');
    resp.textContent = 'O Mestre está arbitrando…';
    _busy = true;
    renderActionBar(_last || {});

    let ouviu = false;
    try {
      // Habilidade narrativa: primeiro o motor gasta o que ela custa (e
      // recusa se não puder: mana, usos, ação já usada). Só então o Mestre.
      if (_livreHab) {
        const cur = ((_last || {}).combatants || []).find(c => c.is_current);
        const res = await doAction({ action: 'ability', actor: cur ? cur.name : '',
                                     ability: _livreHab.nome, target: '' });
        if (!res || !res.ok) {
          const motivo = String((res && res.message) || 'Não foi possível usar a habilidade.')
            .split('\n')[0].replace(/\*\*/g, '');
          resp.textContent = motivo;
          return;
        }
        if (res.snapshot) _last = res.snapshot;
        _livreHab = null;
      }
      if (typeof window.appendUser === 'function') window.appendUser(texto);
      await window.sendToAgent(texto, true, '', fala => {
        ouviu = true;
        resp.innerHTML = (typeof window.renderMarkdown === 'function')
          ? window.renderMarkdown(fala) : esc(fala);
        acompanharAlturaDaBarra();
        // O painel de ações rola: sem isto a arbitragem nascia abaixo da
        // dobra e o jogador ficava olhando o campo de texto vazio.
        resp.scrollIntoView({ block: 'nearest' });
      });
      if (!ouviu) resp.textContent = 'O Mestre respondeu no chat.';
      ta.value = '';
    } catch (_) {
      resp.textContent = 'Não foi possível falar com o Mestre.';
    } finally {
      _busy = false;
      ta.disabled = false;
      if (botao) botao.disabled = false;
      // O Mestre pode ter mexido no combate (dano, condição, zona): a tela
      // volta do motor, não de um palpite.
      await sync();
      ta.focus();
    }
  }

  // ---- API pública -------------------------------------------------
  window.Combat = {
    sync,
    _sel, _selHab, _usarHab, _modo, _circulo, _info, _reacao, _manobras, _manobra, _selWeapon, _selItem, _target, _confirmarAlvos, _desfazerAlvo, _naoLetal, _prepararMagiaEm, _mover, _cancel, _free,
    _confirmarArea,
    _livreEnviar, _livreFechar,
    _act: act,
    _continue, _closeOnly, _dismiss, _reopen,
    _close: () => close(false),
  };

  document.addEventListener('DOMContentLoaded', () => { ensureDom(); sync(); });
})();
