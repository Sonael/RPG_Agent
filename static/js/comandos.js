// ═══════════════════════════════════════════════════════════════════
//  comandos.js — Os comandos "/" do chat
//
//  Os comandos nasceram antes das telas. Quando as telas chegaram (ficha,
//  mochila, grimório, grupo, elenco, diário, missões, mapa, mundo), eles
//  continuaram despejando no chat uma cópia pior do mesmo conteúdo: texto
//  parado, campos crus da ficha ("Dado: undefined"), inimigos misturados ao
//  "Status do Grupo", e dois deles (/flags, /contexto) mostrando ao jogador as
//  anotações internas do Mestre — onde moram os segredos da história.
//
//  Agora:
//    • quem tem tela ABRE a tela; no chat ficam só o que é rápido de ler
//      (/status) ou não tem tela (/rolar);
//    • uma lista só alimenta o menu, a /ajuda e a execução — a /ajuda era
//      escrita à mão e já tinha esquecido a /eventos;
//    • cada gênero fala a própria língua: no romance a tela do grupo é
//      /proximos (ou /relacoes), as missões são /tramas, o mapa é /lugares;
//      no faroeste, /comparsas e /servicos. O nome de sempre (/grupo,
//      /missoes, /mapa) continua valendo como apelido;
//    • nomes são achados sem acento e pelo começo ("/ficha hel" abre a
//      Helena), e o menu sugere os nomes depois do comando;
//    • comando errado não vai mais para o Mestre como se fosse fala — gastava
//      uma requisição e entrava na história.
//
//  REGRA DE OURO, a mesma das telas: nenhuma regra de jogo aqui.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const norm = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
  const slug = (s) => norm(s).replace(/[^a-z0-9]+/g, '');
  const W = window;

  // ---- A campanha, como os comandos a enxergam --------------------------
  function ctx() {
    const mem = W._lastMem || {};
    const cfg = mem.campaign_config || W._campaignConfig || {};
    const telas = cfg.telas || {};
    return {
      mem, telas,
      dnd: mem.dnd_mode === true || mem.campaign_type === 'dnd',
      romance: telas.tela_do_grupo === 'relacoes',
      mundo: !!telas.mundo,
    };
  }

  // ---- Saída no chat -----------------------------------------------------
  function nota(html) { if (W.appendSystem) W.appendSystem(`<p>${html}</p>`); }
  function caixa(titulo, corpo) {
    if (W.appendSystem) W.appendSystem(`<div class="cmd-list-box"><div class="cmd-list-title">${esc(titulo)}</div>${corpo}</div>`);
  }

  // ---- Achar pelo nome ----------------------------------------------------
  // Exato, depois o começo do nome, depois o começo de qualquer palavra,
  // depois em qualquer lugar. Tudo sem acento e sem caixa.
  function achar(busca, nomes) {
    const b = norm(busca);
    if (!b) return [];
    const unicos = [...new Set(nomes.filter(Boolean))];
    const exato = unicos.filter(n => norm(n) === b);
    if (exato.length) return exato;
    for (const teste of [
      n => norm(n).startsWith(b),
      n => norm(n).split(/\s+/).some(p => p.startsWith(b)),
      n => norm(n).includes(b),
    ]) {
      const r = unicos.filter(teste);
      if (r.length) return r;
    }
    return [];
  }

  const pessoas = (c) => [
    ...(c.mem.party || []).map(p => p.name),
    ...(c.mem.characters || []).map(p => p.name),
    c.mem.protagonist,
  ].filter(Boolean);
  // Herói: membro do grupo com ficha de regras (o que mochila e grimório abrem).
  const herois = (c) => (c.mem.party || []).filter(p => p.sheet).map(p => p.name);
  const lugares = (c) => (c.mem.locations || []).map(l => l.name);
  const missoes = (c) => (c.mem.quests || []).filter(Boolean).map(m => m.titulo);

  // Resolve o argumento de nome. Devolve o nome, ou null depois de avisar.
  // `oQue`: 'pessoa' | 'lugar' | 'missao' — muda só a frase do aviso.
  function resolver(busca, nomes, oQue, padrao) {
    if (!String(busca || '').trim()) return padrao || '';
    const r = achar(busca, nomes);
    if (r.length === 1) return r[0];
    // "missão", "trama", "caso", "contrato": o gênero da palavra muda com a
    // campanha, então a frase não usa artigo ("nenhuma caso").
    const livro = (W.nomeDaTela ? W.nomeDaTela('missoes', 'Missões') : 'Missões');
    const nenhum = { pessoa: 'ninguém', lugar: 'nenhum lugar', missao: `nada em ${livro}` }[oQue] || 'nada';
    const mais = { pessoa: 'uma pessoa', lugar: 'um lugar', missao: `um título em ${livro}` }[oQue] || 'um resultado';
    if (!r.length) {
      nota(`Aviso: ${nenhum} com o nome <b>${esc(busca)}</b>.`);
      return null;
    }
    nota(`Aviso: mais de ${mais} combina com <b>${esc(busca)}</b>: `
      + `${r.slice(0, 6).map(esc).join(', ')}${r.length > 6 ? '…' : ''}. Escreva mais do nome.`);
    return null;
  }

  function quemSouEu(c, lista) {
    const prot = c.mem.protagonist;
    if (prot && lista.some(n => norm(n) === norm(prot))) return lista.find(n => norm(n) === norm(prot));
    return lista[0] || '';
  }

  function abrirPessoa(nome, c) {
    const heroi = c.dnd && herois(c).some(n => norm(n) === norm(nome));
    if (heroi && W.Herois) W.Herois._abrir(nome);
    else if (W.Personagens) W.Personagens._abrir(nome);
  }

  // ---- Os comandos --------------------------------------------------------
  // nomes(c): o primeiro é o que aparece; os outros são apelidos.
  // arg: o que vem depois, como aparece no menu. sugere: de onde vêm as
  // sugestões de nome para o argumento.
  const COMANDOS = [
    // Telas — todos os gêneros
    {
      id: 'grupo', secao: 'telas',
      nomes: c => [slug(c.telas.grupo || 'grupo'), 'grupo', ...(c.romance ? ['relacoes'] : [])],
      desc: c => (c.romance ? 'Como cada pessoa se sente por você' : `${c.telas.grupo || 'O grupo'} lado a lado`),
      run: () => W.Barra && W.Barra.abrir('grupo'),
    },
    {
      id: 'ficha', secao: 'telas', arg: '[nome]', sugere: pessoas,
      nomes: () => ['ficha', 'pessoa'],
      desc: c => (c.dnd ? 'A ficha de alguém (sem nome: a sua)'
        : (c.romance ? 'Tudo o que você sabe de alguém' : 'A ficha de alguém (sem nome: a sua)')),
      run: (arg, c) => {
        const lista = pessoas(c);
        const nome = resolver(arg, lista, 'pessoa', quemSouEu(c, c.dnd ? herois(c).concat(lista) : lista));
        if (nome === null) return;
        if (!nome) { nota('Aviso: ainda não há ninguém registrado na história.'); return; }
        abrirPessoa(nome, c);
      },
    },
    {
      id: 'personagens', secao: 'telas', arg: '[nome]', sugere: pessoas,
      nomes: () => ['personagens', 'elenco'],
      desc: () => 'Todos os personagens, com busca',
      run: (arg, c) => {
        if (!String(arg || '').trim()) { if (W.Elenco) W.Elenco._abrir('todos'); return; }
        const nome = resolver(arg, pessoas(c), 'pessoa');
        if (nome) abrirPessoa(nome, c);
      },
    },
    {
      id: 'missoes', secao: 'telas', arg: '[título]', sugere: missoes,
      nomes: c => [slug(c.telas.missoes || 'missoes'), 'missoes'],
      desc: c => c.telas.titulo_missoes || 'O livro de missões',
      run: (arg, c) => {
        const titulo = resolver(arg, missoes(c), 'missao', '');
        if (titulo !== null && W.Missoes) W.Missoes._abrir(titulo || '');
      },
    },
    {
      id: 'mapa', secao: 'telas', arg: '[lugar]', sugere: lugares,
      nomes: c => [slug(c.telas.mapa || 'mapa'), 'mapa', 'locais', 'lugares'],
      desc: c => (c.romance ? 'Os lugares e quem está onde' : 'Os lugares e quem está em cada um'),
      run: (arg, c) => {
        const lugar = resolver(arg, lugares(c), 'lugar', '');
        if (lugar !== null && W.Mapa) W.Mapa._abrir(lugar || '');
      },
    },
    {
      id: 'diario', secao: 'telas', arg: '[capítulo]',
      nomes: () => ['diario'],
      desc: () => 'A história, capítulo a capítulo',
      run: (arg) => {
        const n = parseInt(String(arg || '').replace(/\D+/g, ''), 10);
        if (W.Diario) W.Diario._abrir(Number.isFinite(n) && n > 0 ? n : null);
      },
    },
    {
      id: 'resumo', secao: 'telas',
      nomes: () => ['resumo'],
      desc: () => 'O resumo da história e onde você está',
      run: () => W.Diario && W.Diario._abrir('resumo'),
    },
    {
      id: 'mundo', secao: 'telas', quando: c => c.mundo,
      nomes: () => ['mundo'],
      desc: () => 'Renome, companheiros, lendas e bestiário',
      run: () => W.Mundo && W.Mundo._abrir(),
    },

    // Romance
    {
      id: 'segredos', secao: 'romance', quando: c => c.romance,
      nomes: () => ['segredos'],
      desc: () => 'Os seus segredos e os que já vieram à tona',
      run: () => W.Relacoes && W.Relacoes._abrir('segredos'),
    },
    {
      id: 'tensoes', secao: 'romance', quando: c => c.romance,
      nomes: () => ['tensoes', 'conflitos'],
      desc: () => 'O que está mal resolvido entre as pessoas',
      run: () => W.Relacoes && W.Relacoes._abrir('tensoes'),
    },
    {
      id: 'encontro', secao: 'romance', quando: c => c.romance,
      nomes: () => ['encontro'],
      desc: () => 'O próximo encontro marcado e quanto falta',
      run: (arg, c) => {
        const e = c.mem.encontro;
        if (!e) { nota('Nota: nenhum encontro marcado.'); return; }
        if (W.Barra && W.Barra.abrirEncontro) W.Barra.abrirEncontro();
        nota(`${esc(e.o_que)} com <b>${esc(e.com)}</b>: ${esc(e.quando)}${e.onde ? ` · ${esc(e.onde)}` : ''} · <b>${esc(e.falta)}</b>`);
      },
    },

    // Regras de D&D
    {
      id: 'status', secao: 'regras', quando: c => c.dnd,
      nomes: () => ['status', 'vida'],
      desc: () => 'Vida, mana, CA e condições do grupo, numa linha cada',
      run: () => status(),
    },
    {
      id: 'mochila', secao: 'regras', quando: c => c.dnd, arg: '[nome]', sugere: herois,
      nomes: () => ['mochila', 'inventario', 'itens'],
      desc: () => 'Itens, moedas e carga (sem nome: a sua)',
      run: (arg, c) => {
        const nome = resolver(arg, herois(c), 'pessoa', quemSouEu(c, herois(c)));
        if (nome === null) return;
        if (!nome) { nota('Aviso: ninguém do grupo tem ficha de regras ainda.'); return; }
        if (W.Inventory) W.Inventory._abrir(nome);
      },
    },
    {
      id: 'magias', secao: 'regras', quando: c => c.dnd, arg: '[nome]', sugere: herois,
      nomes: () => ['magias', 'habilidades', 'grimorio'],
      desc: () => 'Magias e habilidades, com o que cada uma faz (sem nome: as suas)',
      run: (arg, c) => {
        const nome = resolver(arg, herois(c), 'pessoa', quemSouEu(c, herois(c)));
        if (nome === null) return;
        if (!nome) { nota('Aviso: ninguém do grupo tem ficha de regras ainda.'); return; }
        if (W.Grimoire) W.Grimoire._abrir(nome);
      },
    },
    {
      id: 'combate', secao: 'regras', quando: c => c.dnd,
      nomes: () => ['combate', 'iniciativa'],
      desc: () => 'Volta à luta em andamento, ou mostra a ordem dos turnos',
      run: () => combate(),
    },
    {
      id: 'rolar', secao: 'regras', quando: c => c.dnd, arg: '[fórmula]',
      nomes: () => ['rolar', 'dado'],
      desc: () => 'Rola aqui, sem o Mestre: d20, 2d6+3, 1d8+1d6, d20 vantagem',
      run: (arg) => rolar(arg),
    },

    // Conversa com o Mestre
    {
      id: 'recapitular', secao: 'mestre',
      nomes: () => ['recapitular', 'recap'],
      desc: () => 'O Mestre narra o que aconteceu até aqui (usa uma requisição)',
      run: async () => {
        nota('Pedindo ao Mestre uma recapitulação…');
        await W.sendToAgent('Faça uma recapitulação dramática e imersiva dos acontecimentos importantes '
          + 'da história até aqui, conferindo o contexto completo da campanha para não errar nenhum fato. '
          + 'Não avance a história nem narre uma cena nova.', false);
      },
    },
    {
      id: 'lembrar', secao: 'mestre', arg: '<o que guardar>',
      nomes: () => ['lembrar', 'anotar'],
      desc: () => 'Pede ao Mestre para guardar algo na memória da história',
      run: async (arg) => {
        const texto = String(arg || '').trim();
        if (!texto) { nota('Aviso: diga o que guardar. Ex.: <b>/lembrar a taverneira mentiu sobre o irmão</b>'); return; }
        nota(`Pedindo ao Mestre para guardar: <i>${esc(texto)}</i>`);
        await W.sendToAgent(`O jogador pediu para você guardar na memória da campanha: "${texto}". `
          + 'Registre isso no lugar certo (personagem, local, acontecimento ou diário) e confirme em '
          + 'uma frase curta, sem narrar uma cena nova.', true, 'comando');
      },
    },
    {
      id: 'exportar', secao: 'mestre',
      nomes: () => ['exportar'],
      desc: () => 'Baixa o diário da campanha em .md',
      run: async () => {
        if (typeof W.exportDiary === 'function') await W.exportDiary();
        else nota('Erro: a exportação não está disponível nesta página.');
      },
    },
    {
      id: 'ajuda', secao: 'mestre',
      nomes: () => ['ajuda', 'comandos'],
      desc: () => 'Todos os comandos desta campanha',
      run: () => ajuda(),
    },
  ];

  // Comandos que saíram, com para onde o jogador deve ir agora. Sem isto quem
  // tinha o hábito de digitar /flags receberia só "não é um comando".
  const SAIRAM = {
    flags: 'Nota: as anotações internas do Mestre não aparecem mais no chat (era por ali que os segredos vazavam). O resumo da história está em /resumo.',
    contexto: 'Nota: as anotações internas do Mestre não aparecem mais no chat. O resumo da história está em /resumo.',
    eventos: 'Nota: os acontecimentos estão no diário, capítulo a capítulo: /diario.',
    condicoes: 'Nota: as condições aparecem no /status e na ficha de cada um (/ficha).',
    salvar: 'Nota: o Mestre já registra pessoas, lugares e acontecimentos sozinho. Para pedir que ele guarde algo, use /lembrar.',
  };

  // ---- Lista do momento ---------------------------------------------------
  function disponiveis(c) {
    c = c || ctx();
    return COMANDOS.filter(k => !k.quando || k.quando(c)).map(k => {
      const nomes = [...new Set(k.nomes(c).filter(Boolean))];
      return { ...k, nome: nomes[0], apelidos: nomes.slice(1), descricao: k.desc(c) };
    });
  }

  function encontrar(nome, lista) {
    const n = norm(nome);
    return lista.find(k => k.nome === n || k.apelidos.includes(n)) || null;
  }

  // Distância de edição, para o "você quis dizer".
  function distancia(a, b) {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) {
      for (let j = 1; j <= b.length; j++) {
        d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1,
          d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
    }
    return d[a.length][b.length];
  }

  function parecido(nome, lista) {
    const n = norm(nome);
    let melhor = null;
    for (const k of lista) {
      for (const cand of [k.nome, ...k.apelidos]) {
        const dist = cand.startsWith(n) ? 0 : distancia(n, cand);
        if (dist <= 2 && (!melhor || dist < melhor.dist)) melhor = { k, dist };
      }
    }
    return melhor ? melhor.k : null;
  }

  // ---- Executar -----------------------------------------------------------
  // Devolve true quando a mensagem era comando (tratado aqui, certo ou
  // errado). Só "/" seguido de letra é comando: "/ olho em volta" é fala.
  async function executar(raw) {
    const m = String(raw || '').trim().match(/^\/([^\s/]+)\s*([\s\S]*)$/);
    if (!m || !/^[a-zà-ú]/i.test(m[1])) return false;
    const c = ctx();
    const lista = disponiveis(c);
    const k = encontrar(m[1], lista);
    if (k) {
      try { await k.run(m[2], c); }
      catch (_) { nota('Erro: o comando não pôde ser concluído. Tente de novo.'); }
      return true;
    }
    const nome = norm(m[1]);
    if (SAIRAM[nome]) { nota(esc(SAIRAM[nome])); return true; }
    // Existe, mas não nesta campanha.
    const deOutro = COMANDOS.find(x => x.quando && !x.quando(c)
      && x.nomes(c).map(norm).includes(nome));
    if (deOutro) {
      nota(esc(deOutro.secao === 'romance'
        ? `Nota: /${nome} só existe nas campanhas de romance.`
        : `Nota: /${nome} só existe em campanhas com as regras de D&D ligadas.`));
      return true;
    }
    const sugestao = parecido(nome, lista);
    nota(`Aviso: <b>/${esc(m[1])}</b> não é um comando.`
      + (sugestao ? ` Você quis dizer <b>/${esc(sugestao.nome)}</b>?` : '')
      + ' Digite <b>/ajuda</b> para ver todos.');
    return true;
  }

  // ---- Sugestões para o menu ----------------------------------------------
  // Item: {valor, rotulo, arg, desc, completo}. `completo`: escolher já envia.
  function sugestoes(texto) {
    const c = ctx();
    const lista = disponiveis(c);
    const s = String(texto || '');
    const soComando = s.match(/^\/(\S*)$/);
    if (soComando) {
      const b = norm(soComando[1]);
      return lista
        .filter(k => !b || k.nome.startsWith(b) || k.apelidos.some(a => a.startsWith(b)))
        .map(k => ({ valor: `/${k.nome}`, rotulo: `/${k.nome}`, arg: k.arg || '',
                     desc: k.descricao, completo: !k.arg }));
    }
    const comArg = s.match(/^\/(\S+)\s+(.*)$/);
    if (comArg) {
      const k = encontrar(comArg[1], lista);
      if (!k || !k.sugere) return [];
      const b = comArg[2];
      const nomes = [...new Set(k.sugere(c).filter(Boolean))];
      const casam = b.trim() ? achar(b, nomes) : nomes;
      return casam.slice(0, 8).map(n => ({ valor: `/${k.nome} ${n}`, rotulo: n, arg: '', desc: '', completo: true }));
    }
    return [];
  }

  // ---- /ajuda -------------------------------------------------------------
  const SECOES = [
    ['telas', 'Telas'],
    ['romance', 'Romance'],
    ['regras', 'Regras de D&D'],
    ['mestre', 'Com o Mestre'],
  ];

  function ajuda() {
    const lista = disponiveis();
    const corpo = SECOES.map(([id, titulo]) => {
      const desta = lista.filter(k => k.secao === id);
      if (!desta.length) return '';
      return `<div class="cmd-list-secao">${esc(titulo)}</div>` + desta.map(k =>
        `<div class="cmd-list-item"><b>/${esc(k.nome)}${k.arg ? ` ${esc(k.arg)}` : ''}</b> · ${esc(k.descricao)}`
        + (k.apelidos.length ? ` <span class="cmd-apelidos">também ${k.apelidos.map(a => `/${esc(a)}`).join(', ')}</span>` : '')
        + '</div>').join('');
    }).join('');
    caixa('Comandos', corpo
      + '<div class="cmd-list-rodape">Nomes podem ir sem acento e pela metade: <b>/ficha hel</b>.</div>');
  }

  // ---- /status ------------------------------------------------------------
  // Só o grupo. Antes listava todo mundo com ficha — inimigos e os mortos de
  // lutas antigas inclusive — sob o título "Status do Grupo".
  async function status() {
    let d;
    try { d = await (await (W.authFetch || fetch)(`${W.API || ''}/api/party/overview`)).json(); }
    catch (_) { nota('Erro: não foi possível ler o grupo agora.'); return; }
    const hs = (d && d.herois) || [];
    if (!hs.length) { nota('Nota: ninguém do grupo tem ficha de regras ainda.'); return; }
    const linhas = hs.map(h => {
      const pct = h.vida.max > 0 ? (h.vida.atual / h.vida.max) * 100 : 0;
      const nivel = h.morto || h.vida.atual === 0 ? 'baixo' : (pct > 60 ? 'ok' : (pct > 30 ? 'atencao' : 'baixo'));
      const marcas = [
        h.morto ? 'morto' : (h.vida.atual === 0 ? 'caído' : ''),
        ...(h.condicoes || []).map(cd => `${cd.nome}${cd.duracao ? ` (${cd.duracao}t)` : ''}`),
        h.nivel_pendente && !h.morto ? 'nível pendente' : '',
      ].filter(Boolean);
      return `<div class="cmd-status-linha">
        <span><span class="hp-ponto hp-ponto-${nivel}" aria-hidden="true"></span><b>${esc(h.nome)}</b>`
        + `${marcas.length ? ` <span class="cmd-status-marcas">${marcas.map(esc).join(' · ')}</span>` : ''}</span>
        <span class="cmd-status-nums">${h.vida.atual}/${h.vida.max} vida${h.vida.temp ? ` +${h.vida.temp}` : ''}`
        + `${h.mana && h.mana.max ? ` · ${h.mana.atual}/${h.mana.max} mana` : ''} · CA ${esc(h.ca)}</span>
      </div>`;
    });
    const semFicha = ((d && d.sem_ficha) || []).filter(p => !p.morto)
      .map(p => `<div class="cmd-status-linha"><span><b>${esc(p.nome)}</b> <span class="cmd-status-marcas">sem ficha de regras</span></span></div>`);
    const descanso = d && d.resumo && d.resumo.descanso
      ? `<div class="cmd-list-rodape">${esc(d.resumo.descanso)}</div>` : '';
    caixa(`Status — ${(ctx().telas.grupo) || 'Grupo'}`, linhas.concat(semFicha).join('') + descanso);
  }

  // ---- /combate -----------------------------------------------------------
  async function combate() {
    let s;
    try { s = await (await (W.authFetch || fetch)(`${W.API || ''}/api/combat/state`)).json(); }
    catch (_) { nota('Erro: não foi possível ler o combate agora.'); return; }
    if (!s || !s.is_active) { nota('Nota: nenhum combate em andamento.'); return; }
    if (s.combat_mode === 'tela' && W.Combat && W.Combat._reopen) { W.Combat._reopen(); return; }
    // Combate narrado: a ordem no chat. O "(já agiu)" de antes era só a
    // posição na lista, e marcava quem tinha caído antes de agir.
    const fora = new Set((s.combatants || [])
      .filter(x => ['morto', 'inconsciente', 'estabilizado', 'fugiu', 'exilado'].includes((x.status || '').toLowerCase()))
      .map(x => x.name));
    const ordem = s.order || [];
    const i = s.turn_index || 0;
    let proximo = '';
    for (let k = 1; k < ordem.length; k++) {
      const n = ordem[(i + k) % ordem.length];
      if (!fora.has(n)) { proximo = n; break; }
    }
    const lista = ordem.map((n, j) =>
      `<div class="cmd-list-item${fora.has(n) ? ' cmd-fora' : ''}">${j + 1}. ${esc(n)}`
      + `${j === i ? ' <b class="cmd-vez">vez</b>' : ''}${fora.has(n) ? ' <span class="cmd-status-marcas">fora da luta</span>' : ''}</div>`).join('');
    caixa(`Combate — Rodada ${s.round || 1}`,
      `<div class="cmd-list-item">Agora: <b>${esc(ordem[i] || '?')}</b>${proximo ? ` · Próximo: ${esc(proximo)}` : ''}</div>${lista}`);
  }

  // ---- /rolar -------------------------------------------------------------
  // Fórmula: termos somados ou subtraídos (2d6, d20, d%, 3), e "vantagem" ou
  // "desvantagem" para um único d20. Sem fórmula, um d20.
  const MAX_DADOS = 50;

  function interpretar(texto) {
    let t = norm(texto);
    let modo = '';
    t = t.replace(/\b(vantagem|vant|adv)\b/, () => { modo = 'vantagem'; return ''; })
         .replace(/\b(desvantagem|desv|dis)\b/, () => { modo = 'desvantagem'; return ''; })
         .replace(/\s+/g, '');
    if (!t) t = 'd20';
    if (!/^[+-]?(\d*d(\d+|%)|\d+)([+-](\d*d(\d+|%)|\d+))*$/.test(t)) return { erro: 'formula' };
    const termos = [];
    let total = 0;
    for (const m of t.matchAll(/([+-]?)(\d*)d(\d+|%)|([+-]?)(\d+)/g)) {
      if (m[3] !== undefined) {
        const qtd = parseInt(m[2] || '1', 10);
        const lados = m[3] === '%' ? 100 : parseInt(m[3], 10);
        if (qtd < 1 || lados < 2 || lados > 1000) return { erro: 'limite' };
        total += qtd;
        termos.push({ sinal: m[1] === '-' ? -1 : 1, qtd, lados });
      } else {
        termos.push({ sinal: m[4] === '-' ? -1 : 1, fixo: parseInt(m[5], 10) });
      }
    }
    if (total > MAX_DADOS) return { erro: 'limite' };
    const dados = termos.filter(x => x.lados);
    if (modo && !(dados.length === 1 && dados[0].qtd === 1 && dados[0].lados === 20)) return { erro: 'modo' };
    return { termos, modo };
  }

  function lancar(f, aleatorio) {
    const r = aleatorio || Math.random;
    const d = (lados) => Math.floor(r() * lados) + 1;
    let total = 0;
    const partes = f.termos.map(x => {
      if (x.fixo !== undefined) { total += x.sinal * x.fixo; return { ...x, texto: String(x.fixo) }; }
      let rolagens = Array.from({ length: x.qtd }, () => d(x.lados));
      let descartada = null;
      if (f.modo) {
        const outra = d(20);
        const fica = f.modo === 'vantagem' ? Math.max(rolagens[0], outra) : Math.min(rolagens[0], outra);
        descartada = fica === rolagens[0] ? outra : rolagens[0];
        rolagens = [fica];
      }
      const soma = rolagens.reduce((a, b) => a + b, 0);
      total += x.sinal * soma;
      return { ...x, rolagens, descartada, soma };
    });
    return { partes, total };
  }

  function rolar(arg) {
    const formula = String(arg || '').trim() || 'd20';
    const f = interpretar(formula);
    if (f.erro) {
      nota(f.erro === 'limite'
        ? 'Aviso: no máximo 50 dados por rolagem, de d2 a d1000.'
        : f.erro === 'modo'
          ? 'Aviso: vantagem e desvantagem valem para um único d20. Ex.: <b>/rolar d20 vantagem</b>'
          : `Aviso: não entendi a fórmula <b>${esc(formula)}</b>. Ex.: <b>/rolar 2d6+3</b>, <b>/rolar 1d8+1d6</b>, <b>/rolar d20 vantagem</b>`);
      return;
    }
    const r = lancar(f);
    const texto = r.partes.map((p, i) => {
      const sinal = i === 0 ? (p.sinal < 0 ? '−' : '') : (p.sinal < 0 ? ' − ' : ' + ');
      if (p.fixo !== undefined) return `${sinal}${p.fixo}`;
      const valores = p.rolagens.length > 1 ? `[${p.rolagens.join(' + ')}]` : String(p.rolagens[0]);
      const desc = p.descartada !== null ? ` <span class="cmd-descartado" title="Descartado">${p.descartada}</span>` : '';
      return `${sinal}<span class="sys-number">${valores}</span>${desc}`;
    }).join('');
    const unico = r.partes.filter(p => p.lados).length === 1 && r.partes.find(p => p.lados);
    const natural = unico && unico.lados === 20 && unico.rolagens.length === 1 ? unico.rolagens[0] : null;
    const tag = natural === 20 ? '<br><span class="sys-highlight">CRÍTICO NATURAL</span>'
      : natural === 1 ? '<br><span class="sys-highlight">FALHA CRÍTICA</span>' : '';
    const titulo = `Rolagem: ${formula}${f.modo && !/vant|desv|adv|dis/i.test(formula) ? ` (${f.modo})` : ''}`;
    const row = document.createElement('div');
    row.className = 'msg-row system';
    row.innerHTML = `
      <div class="sys-card cmd-rolagem">
        <div class="sys-card-badge cmd-rolagem-badge">${esc(titulo)}</div>
        <div class="sys-card-body">${texto} = <strong>${r.total}</strong>${tag}</div>
        <div class="cmd-rolagem-nota">Só para você: o Mestre não vê esta rolagem.</div>
      </div>`;
    const hist = document.getElementById('chat-history');
    if (hist) { hist.appendChild(row); if (W.scrollDown) W.scrollDown(); }
  }

  W.Comandos = {
    executar, sugestoes, disponiveis,
    // Para os testes: a fórmula e a rolagem sem tocar no chat.
    _interpretar: interpretar, _lancar: lancar, _achar: achar,
  };
})();
