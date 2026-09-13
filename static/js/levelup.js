// ═══════════════════════════════════════════════════════════════════
//  levelup.js — Tela de subida de nível ("A Ascensão")
//
//  REGRA DE OURO, a mesma do combat.js e do shop.js: nenhuma regra de jogo
//  mora aqui. Quais escolhas estão pendentes, quais opções existem, o teto
//  de 20 no atributo e o que cada escolha concede — tudo vem do motor
//  (tools_dnd via /api/levelup/*).
//
//  Esta tela existe por um motivo DIFERENTE das outras duas. Combate e loja
//  são laços: muitas decisões pequenas, e a tela tira a LLM do caminho.
//  Subir de nível acontece umas dez vezes numa campanha inteira — não há
//  laço nenhum. O que há é um conjunto de escolhas que o modelo inventaria:
//  estilo de combate, arquétipo, para onde vão os pontos de atributo. Aqui
//  a tela não economiza tempo, ela impede invenção.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open  = false;
  let _busy  = false;
  let _last  = {};
  let _quem  = '';

  // ---- Memória de "já abriu por estas pendências" -----------------------
  // A assinatura (calculada no servidor, sobre o grupo todo) do que abriu a
  // tela da última vez. Ficava numa variável: fechar no ✕ e dar F5 reabria.
  // Agora fica no localStorage, por campanha.
  function campanhaAtual() {
    try { return (JSON.parse(localStorage.getItem('rpg_session') || '{}').campaign) || ''; }
    catch (_) { return ''; }
  }
  const CHAVE_MEMORIA = () => `rpg_telas::${campanhaAtual()}::nivel_visto`;
  function assinaturaVista() {
    try { return localStorage.getItem(CHAVE_MEMORIA()) || ''; } catch (_) { return ''; }
  }
  function marcarVista(assinatura) {
    try {
      if (assinatura) localStorage.setItem(CHAVE_MEMORIA(), assinatura);
      else localStorage.removeItem(CHAVE_MEMORIA());
    } catch (_) { /* sem storage, só perde a memória entre recargas */ }
  }

  // Nenhuma tela abre sozinha por cima de outra. A de nível tem prioridade
  // sobre a loja na fila, mas se a loja JÁ estiver aberta (o jogador está
  // comprando) e um grant_xp chegar, esta espera a loja fechar.
  const OUTRAS_TELAS = ['combat-on', 'shop-on'];
  const outraTelaAberta = () => OUTRAS_TELAS.some(c => document.body.classList.contains(c));

  // Rascunho do incremento de atributo, igual ao wizard de criação: o jogador
  // sobe e desce com + e − e NADA vai ao servidor até "Confirmar". Vive aqui e
  // não no DOM porque sync() redesenha a tela a cada turno.
  //   dono/faltam: de quem é e para qual pool foi feito. Se qualquer um mudar
  //   (confirmou, subiu outro nível, trocou de personagem), o rascunho é
  //   descartado em vez de ser reaproveitado sobre uma ficha diferente.
  let _rascunho = { dono: '', faltam: 0, pontos: {} };

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q   = (id) => document.getElementById(id);

  // ---- DOM ---------------------------------------------------------
  function ensureDom() {
    if (q('levelup-overlay')) return;
    const o = document.createElement('div');
    o.id = 'levelup-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="lvl-frame">
        <header class="lvl-header">
          <button class="lvl-close" onclick="window.LevelUp._close()"
                  aria-label="Fechar"
                  title="Fechar — as escolhas continuam pendentes">✕</button>
          <h1 class="lvl-title">A Ascensão <span id="lvl-quem">—</span></h1>
          <div id="lvl-sub" class="lvl-sub"></div>
          <div class="lvl-xp">
            <div class="lvl-xp-barra"><div id="lvl-xp-fill" class="lvl-xp-fill"></div></div>
            <div id="lvl-xp-num" class="lvl-xp-num"></div>
          </div>
        </header>

        <div id="lvl-atributos" class="lvl-atributos"></div>
        <div id="lvl-corpo" class="lvl-corpo"></div>

        <div class="lvl-rodape">
          <div id="lvl-msg" class="lvl-msg"></div>
          <button id="lvl-concluir" class="lvl-concluir"
                  onclick="window.LevelUp._concluir()">Concluir</button>
        </div>
      </div>`;
    document.body.appendChild(o);

    if (!q('lvl-reopen')) {
      const pill = document.createElement('button');
      pill.id = 'lvl-reopen';
      pill.className = 'hidden';
      pill.onclick = () => window.LevelUp._abrir();
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
    return api('/api/levelup/state' + (_quem ? `?personagem=${encodeURIComponent(_quem)}` : ''));
  }
  function doAction(p) {
    return api('/api/levelup/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(p),
    });
  }

  // ---- Render ------------------------------------------------------
  function atributos(p) {
    q('lvl-atributos').innerHTML = (p.atributos || []).map(a => `
      <div class="lvl-attr">
        <span class="lvl-attr-nome">${esc(a.nome)}</span>
        <span class="lvl-attr-sigla">${esc(a.sigla || a.nome)}</span>
        <span class="lvl-attr-valor">${a.valor}</span>
        <span class="lvl-attr-mod">${a.mod >= 0 ? '+' : ''}${a.mod}</span>
      </div>`).join('');
  }

  function cartaoVariante(pd) {
    const jaTem = (pd.escolhidos || []).length
      ? `<div class="lvl-ja">Já escolhido: ${pd.escolhidos.map(esc).join(', ')}</div>`
      : '';
    const quantos = pd.pick > 1
      ? `<span class="lvl-contagem">${(pd.escolhidos || []).length}/${pd.pick}</span>` : '';
    return `
      <section class="lvl-bloco">
        <h2 class="lvl-bloco-titulo">${esc(pd.rotulo)} ${quantos}</h2>
        ${pd.descricao ? `<p class="lvl-bloco-desc">${esc(pd.descricao)}</p>` : ''}
        ${jaTem}
        <div class="lvl-opcoes">
          ${(pd.opcoes || []).map(o => `
            <button class="lvl-opcao"
                    onclick="window.LevelUp._variante('${esc(pd.feature).replace(/'/g, "\\'")}','${esc(o.nome).replace(/'/g, "\\'")}')">
              <span class="lvl-opcao-nome">${esc(o.nome)}</span>
              <span class="lvl-opcao-desc">${esc(o.descricao)}</span>
            </button>`).join('')}
        </div>
      </section>`;
  }

  // Teto do 5e. O motor é quem manda (recusa acima disso), mas o botão + tem
  // que saber onde parar para não oferecer um clique que vai ser recusado.
  const TETO = 20;
  const modDe = (v) => Math.floor((v - 10) / 2);
  const sinal = (n) => (n >= 0 ? '+' : '') + n;

  function rascunhoPara(p, pd) {
    if (_rascunho.dono !== p.nome || _rascunho.faltam !== pd.faltam) {
      _rascunho = { dono: p.nome, faltam: pd.faltam, pontos: {} };
    }
    // Se a ficha mudou por fora (o mestre ajustou um atributo), um ponto do
    // rascunho pode ter passado do teto: esse ponto sai em vez de travar.
    for (const o of (pd.opcoes || [])) {
      const n = _rascunho.pontos[o.chave] || 0;
      if (n && o.valor + n > TETO) _rascunho.pontos[o.chave] = Math.max(0, TETO - o.valor);
    }
    return _rascunho;
  }

  const totalDistribuido = () =>
    Object.values(_rascunho.pontos).reduce((a, b) => a + b, 0);

  function cartaoAsi(pd, p) {
    const r      = rascunhoPara(p, pd);
    const usados = totalDistribuido();
    const sobram = pd.faltam - usados;

    // Cada atributo é um stepper − valor +, como no wizard de criação. A
    // diferença está no piso: no wizard o − desce até o mínimo da criação;
    // aqui ele só retira os pontos que o jogador pôs AGORA. O valor que a
    // ficha já tinha não é negociável — incremento não é redistribuição.
    const celulas = (pd.opcoes || []).map(o => {
      const extra  = r.pontos[o.chave] || 0;
      const valor  = o.valor + extra;
      const podeMenos = extra > 0;
      const podeMais  = sobram > 0 && valor < TETO;
      const dicaMais  = valor >= TETO ? 'Teto de 20'
                      : sobram <= 0   ? 'Todos os pontos já foram distribuídos'
                      : '+1 ponto';
      return `
        <div class="lvl-step${extra ? ' lvl-step-alterado' : ''}" data-attr="${esc(o.chave)}">
          <span class="lvl-step-nome">${esc(o.nome)}</span>
          <div class="lvl-step-controle">
            <button class="lvl-step-btn lvl-step-menos" ${podeMenos ? '' : 'disabled'}
                    aria-label="Retirar 1 ponto de ${esc(o.nome)}"
                    title="${podeMenos ? 'Retirar 1 ponto' : 'Não desce abaixo do que a ficha já tinha'}"
                    onclick="window.LevelUp._passo('${esc(o.chave)}', -1)">−</button>
            <span class="lvl-step-valor">${valor}</span>
            <button class="lvl-step-btn lvl-step-mais" ${podeMais ? '' : 'disabled'}
                    aria-label="Somar 1 ponto em ${esc(o.nome)}"
                    title="${dicaMais}"
                    onclick="window.LevelUp._passo('${esc(o.chave)}', 1)">+</button>
          </div>
          <span class="lvl-step-mod">mod ${sinal(modDe(valor))}</span>
          <span class="lvl-step-extra">${extra ? `${o.valor} +${extra}` : '&nbsp;'}</span>
        </div>`;
    }).join('');

    // Confirmar exige TODOS os pontos distribuídos — deixar um sobrando por
    // descuido criaria uma pendência que o jogador não entenderia. A única
    // exceção é não haver mais onde pôr (tudo no teto), que libera o que já
    // foi distribuído.
    const semEspaco  = (pd.opcoes || []).every(o => o.valor + (r.pontos[o.chave] || 0) >= TETO);
    const confirmavel = usados > 0 && (sobram === 0 || semEspaco);
    const rotuloConfirmar = sobram > 0 && !semEspaco
      ? `Distribua mais ${sobram} ponto${sobram > 1 ? 's' : ''}`
      : `Confirmar incremento (+${usados})`;

    // O talento substitui um incremento INTEIRO e não se mistura com pontos
    // em rascunho: com +1 já distribuído, "trocar por talento" seria ambíguo
    // sobre o que acontece com esse ponto.
    const talentoLivre = usados === 0 && pd.faltam >= 2;

    return `
      <section class="lvl-bloco lvl-bloco-asi">
        <h2 class="lvl-bloco-titulo">
          Incremento de Atributo
          <span class="lvl-contagem" id="lvl-asi-contagem">${usados} / ${pd.faltam} pontos</span>
        </h2>
        <p class="lvl-bloco-desc">${esc(pd.descricao)}</p>
        <div class="lvl-step-grid">${celulas}</div>
        <div class="lvl-asi-acoes">
          <button class="lvl-asi-desfazer" ${usados ? '' : 'disabled'}
                  onclick="window.LevelUp._desfazer()">Desfazer</button>
          <button class="lvl-asi-confirmar" ${confirmavel ? '' : 'disabled'}
                  onclick="window.LevelUp._confirmarAsi()">${rotuloConfirmar}</button>
        </div>
        <div class="lvl-talento">
          <label for="lvl-talento-nome">…ou troque o incremento por um
            <b>talento</b> (consome os 2 pontos):</label>
          <div class="lvl-talento-linha">
            <input id="lvl-talento-nome" type="text" autocomplete="off"
                   ${talentoLivre ? '' : 'disabled'}
                   placeholder="${talentoLivre
                     ? 'nome do talento em inglês, como no SRD (ex: Alert)'
                     : 'desfaça os pontos para escolher talento'}">
            <button class="lvl-opcao lvl-talento-btn" ${talentoLivre ? '' : 'disabled'}
                    onclick="window.LevelUp._talento()">Escolher talento</button>
          </div>
        </div>
      </section>`;
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();

    const p = _last.personagem;
    if (!p) {
      q('lvl-quem').textContent = '';
      q('lvl-corpo').innerHTML =
        '<div class="lvl-vazio">Nenhum personagem com ficha no grupo.</div>';
      return;
    }

    const grupo = _last.grupo || [];
    q('lvl-quem').textContent = `— ${p.nome}`;
    q('lvl-sub').innerHTML =
      (grupo.length > 1
        ? `<select class="lvl-quem-sel" aria-label="Personagem"
                   onchange="window.LevelUp._trocar(this.value)">`
          + grupo.map(n => `<option value="${esc(n)}" ${n === p.nome ? 'selected' : ''}>`
                         + `${esc(n)}${(_last.devendo || []).includes(n) ? ' (pendente)' : ''}</option>`).join('')
          + `</select>`
        : '')
      + `<span class="lvl-classe">${esc(p.classe)} · nível <b>${p.nivel}</b>`
      + ` · CA ${p.ca} · PV ${p.vida_max} · prof. +${p.proficiencia}</span>`;

    q('lvl-xp-fill').style.width = `${p.xp_pct}%`;
    q('lvl-xp-num').textContent =
      p.nivel >= 20 ? `${p.xp} XP — nível máximo`
                    : `${p.xp} / ${p.xp_proximo} XP`;

    atributos(p);

    const pend = _last.pendencias || [];

    // Sem incremento pendente, o rascunho não pode sobreviver. Depois de
    // confirmar, o bloco some e rascunhoPara() não roda mais — sem esta linha
    // os pontos antigos ficariam guardados e reapareceriam no PRÓXIMO
    // incremento do mesmo personagem, que também tem 2 pontos.
    if (!pend.some(x => x.tipo === 'asi')) {
      _rascunho = { dono: '', faltam: 0, pontos: {} };
    }

    if (!pend.length) {
      q('lvl-corpo').innerHTML = `
        <div class="lvl-vazio">
          <div class="lvl-ok">✓</div>
          Nada pendente para ${esc(p.nome)}.
          <small>As escolhas aparecem aqui quando um nível novo as concede.</small>
        </div>`;
    } else {
      q('lvl-corpo').innerHTML = pend
        .map(pd => pd.tipo === 'asi' ? cartaoAsi(pd, p) : cartaoVariante(pd))
        .join('');
    }

    // O rodapé muda de FUNÇÃO conforme o que falta, não só de rótulo:
    //   • este personagem ainda deve algo  → desabilitado (sair devendo é o
    //     que a tela existe para impedir; o ✕ continua fechando);
    //   • outro do grupo deve             → vira atalho para ele, porque um
    //     botão que diz "falta escolher: Helena" e conclui a cena seria
    //     mentira;
    //   • ninguém deve                    → conclui e manda narrar.
    const outros = (_last.devendo || []).filter(n => n !== p.nome);
    const btn = q('lvl-concluir');
    btn.disabled = pend.length > 0;
    if (pend.length) {
      btn.textContent = 'Escolha acima para continuar';
      btn.dataset.proximo = '';
    } else if (outros.length) {
      btn.textContent = `Agora ${outros[0]} →`;
      btn.dataset.proximo = outros[0];
    } else {
      btn.textContent = 'Concluir';
      btn.dataset.proximo = '';
    }
  }

  // ---- Sincronia ---------------------------------------------------
  async function sync() {
    try {
      const snap = await getState();
      if (!snap) return;

      // A tela abre sozinha quando a assinatura das pendências MUDA — quando um
      // nível novo criou escolha. Abrir sempre que houvesse pendência prenderia
      // quem decidiu deixar para depois numa tela que reabre a cada turno.
      const assinatura = snap.assinatura || '';

      if (!assinatura) {
        // Nada pendente: esquece. Sem isto, uma pendência que voltasse IGUAL
        // à anterior (o incremento de 2 pontos do nível 8 depois do do nível
        // 4, com a mesma assinatura) nunca mais abriria a tela.
        if (assinaturaVista()) marcarVista('');
      } else if (assinatura !== assinaturaVista() && !_open && !outraTelaAberta()) {
        // Se outra tela estiver aberta, NÃO marca como vista: a fila tenta de
        // novo quando ela fechar.
        marcarVista(assinatura);
        abrir();
        atualizarPilula(snap);
        return;
      }

      atualizarPilula(snap);
      if (_open) render(snap); else _last = snap;
    } catch (_) { /* a tela de nível nunca derruba o turno */ }
  }

  function atualizarPilula(snap) {
    const pill = q('lvl-reopen');
    if (!pill) return;
    const devendo = snap.devendo || [];
    if (devendo.length && !_open) {
      pill.textContent = devendo.length === 1
        ? `${devendo[0]}: escolha pendente`
        : `${devendo.length} escolhas pendentes`;
      pill.classList.remove('hidden');
    } else {
      pill.classList.add('hidden');
    }
  }

  // ---- Abrir / fechar ----------------------------------------------
  function abrir() {
    ensureDom();
    q('levelup-overlay').classList.remove('hidden');
    document.body.classList.add('levelup-on');
    const pill = q('lvl-reopen');
    if (pill) pill.classList.add('hidden');
    _open = true;
    getState().then(render).catch(() => {});
  }

  function fechar() {
    const el = q('levelup-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('levelup-on');
    _open = false;
    atualizarPilula(_last || {});
    // Avisa a fila: a loja que esperava esta tela fechar pode abrir agora.
    window.dispatchEvent(new Event('rpg:tela-fechou'));
  }

  function mensagem(txt, ok) {
    const el = q('lvl-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lvl-msg-erro', !ok);
  }

  // ---- Ações --------------------------------------------------------
  async function agir(payload) {
    if (_busy) return;
    const p = (_last.personagem || {});
    if (!p.nome) return;
    _busy = true;
    try {
      const res = await doAction({ char: p.nome, ...payload });
      _busy = false;
      if (res) {
        mensagem((res.message || '').split('\n')[0], res.ok !== false);
        if (res.snapshot) render(res.snapshot);
      }
    } catch (_) {
      _busy = false;
      mensagem('Falha de conexão.', false);
    }
  }

  async function concluir() {
    const btn = q('lvl-concluir');
    const proximo = btn && btn.dataset.proximo;
    if (proximo) { window.LevelUp._trocar(proximo); return; }

    const p = (_last.personagem || {});
    fechar();
    const txt = `[NÍVEL RESOLVIDO NA TELA] ${p.nome || 'O personagem'} chegou ao `
              + `nível ${p.nivel} e o jogador já fez todas as escolhas. Narre a `
              + `virada em uma ou duas frases, usando o que está na ficha — não `
              + `invente habilidade nem atributo que não esteja lá.`;
    try {
      if (typeof window.sendToAgent === 'function') await window.sendToAgent(txt, true);
    } catch (_) { /* fechar já é o essencial */ }
  }

  // ---- API pública ---------------------------------------------------
  window.LevelUp = {
    sync,
    _abrir: abrir,
    _close: fechar,
    _concluir: concluir,
    _trocar: (n) => { _quem = n; getState().then(render).catch(() => {}); },
    _variante: (feature, choice) => agir({ action: 'variante', feature, choice }),
    // + e − só mexem no rascunho e redesenham com o snapshot que já está em
    // mãos: nenhuma ida ao servidor por clique, como no wizard.
    _passo: (chave, delta) => {
      const pd = (_last.pendencias || []).find(x => x.tipo === 'asi');
      const o  = pd && (pd.opcoes || []).find(x => x.chave === chave);
      if (!o) return;
      const atual = _rascunho.pontos[chave] || 0;
      if (delta < 0) {
        if (atual <= 0) return;                       // piso: o que a ficha já tinha
        _rascunho.pontos[chave] = atual - 1;
      } else {
        if (pd.faltam - totalDistribuido() <= 0) return;
        if (o.valor + atual >= TETO) return;
        _rascunho.pontos[chave] = atual + 1;
      }
      mensagem('', true);
      render(_last);
    },
    _desfazer: () => {
      _rascunho.pontos = {};
      mensagem('', true);
      render(_last);
    },
    _confirmarAsi: () => {
      const distribution = {};
      for (const [k, n] of Object.entries(_rascunho.pontos)) if (n > 0) distribution[k] = n;
      if (!Object.keys(distribution).length) return;
      // O rascunho só é descartado quando o servidor devolve o pool novo
      // (faltam muda em rascunhoPara). Se a confirmação for recusada, os
      // pontos continuam onde o jogador pôs.
      agir({ action: 'asi_lote', distribution });
    },
    _asi: (chave) => agir({ action: 'asi', choice: chave, points: 1 }),
    // Selo "Subir de nível" da ficha. Sobe pelo motor (grant_xp) e abre a tela no
    // personagem que subiu — mesmo sem escolha pendente, para o jogador ver o
    // nível novo e concluir a cena.
    _subir: async (nome) => {
      if (_busy) return;
      _busy = true;
      try {
        const res = await doAction({ action: 'subir', char: nome });
        _busy = false;
        if (!res) return;
        const primeira = (res.message || '').split('\n').find(l => l.includes('LEVEL UP'))
                      || (res.message || '').split('\n')[0];
        if (window.showToast) window.showToast(primeira);
        if (res.ok === false) return;
        _quem = nome;
        // A tela abre AGORA, pelo clique; a fila não deve reabri-la por conta
        // da mesma pendência logo em seguida.
        marcarVista((res.snapshot || {}).assinatura || '');
        if (!_open) abrir(); else if (res.snapshot) render(res.snapshot);
        if (typeof window.refreshMemory === 'function') window.refreshMemory();
      } catch (_) {
        _busy = false;
        if (window.showToast) window.showToast('Falha de conexão ao subir de nível.');
      }
    },
    _talento: () => {
      const el = q('lvl-talento-nome');
      const nome = (el && el.value || '').trim();
      if (!nome) { mensagem('Escreva o nome do talento.', false); return; }
      agir({ action: 'talento', choice: nome });
    },
  };

  // Só monta o DOM; quem chama sync() é a fila de telas do game.js.
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
