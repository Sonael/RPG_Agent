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
  let _ajustando = '';      // '', 'atitude', 'lealdade', 'entre:Nome', 'entre:novo'

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
          <section class="lcl-corpo-pessoas" aria-label="Relação e o que se sabe">
            <div id="psn-laco"></div>
            <div id="psn-relacao-bloco">
              <h2 class="lcl-secao" id="psn-relacao-titulo">Relação com o grupo</h2>
              <div id="psn-relacao"></div>
            </div>
            <div id="psn-entre-bloco">
              <h2 class="lcl-secao" id="psn-entre-titulo">Com quem convive</h2>
              <div id="psn-entre"></div>
            </div>
            <h2 class="lcl-secao psn-secao-sabe" id="psn-sabe-titulo">O que o grupo sabe</h2>
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
          <button id="psn-apagar" class="lcl-btn lcl-btn-apagar hidden"
                  onclick="window.Personagens._apagar()"
                  title="Tira este personagem da memória da campanha">Apagar</button>
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
    if (f.do_grupo) partes.push(`<span class="lcl-selo-texto lcl-alcance-aqui">${esc(window.frase('do_grupo', 'Do grupo'))}</span>`);
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
            ? 'Não está mais entre os vivos' : `${window.frase('longe', 'Longe do grupo')}: vá até lá primeiro`}">Falar com</button>`);
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
      ${hist}
      ${_ajustando === 'atitude'
        ? painel('atitude', a.valor, 'Atitude com o grupo')
        : botaoAjustar('atitude')}`;
  }

  // ---- Ajuste pelo jogador -----------------------------------------
  // Uma edição por vez, guardada aqui: quem desenha é o render, então não há
  // DOM costurado à mão nem tela que discorda de si mesma.
  //
  // Por que o jogador edita isto: na partida medida, o mestre pôs a
  // companheira em "neutro" por causa de uma briga com OUTRA pessoa, com a
  // lealdade dela em 90. Quem sabe o que aconteceu na mesa é quem jogou.
  function painel(alvo, valor, rotulo) {
    return `
      <div class="psn-ajuste" data-alvo="${esc(alvo)}">
        <label class="psn-ajuste-linha">${esc(rotulo)}
          <input type="number" class="psn-ajuste-valor" min="-100" max="100" step="5" value="${valor}">
        </label>
        <input type="text" class="psn-ajuste-motivo" maxlength="120"
               placeholder="Por quê? (fica no histórico)">
        <div class="psn-ajuste-botoes">
          <button class="lcl-btn lcl-btn-sec" onclick="window.Personagens._salvarAjuste()">Salvar</button>
          <button class="lcl-btn" onclick="window.Personagens._fecharAjuste()">Cancelar</button>
        </div>
      </div>`;
  }

  function botaoAjustar(alvo) {
    return `<button class="lcl-btn lcl-btn-sec psn-ajustar"
                    onclick="window.Personagens._ajustar('${aspas(alvo)}')">Ajustar</button>`;
  }

  // ---- Relação com cada um -----------------------------------------
  // O que ele sente por OUTRA pessoa, não pelo grupo. Cada linha abre a
  // edição: o número, o porquê, e apagar. Quem manda na mesa é o jogador —
  // o mestre escreve pelo fechamento do turno, e erra às vezes.
  function entre(f) {
    const lista = f.entre || [];
    const nomes = (_nomesDaCampanha() || []).filter(
      n => n.toLowerCase() !== (f.nome || '').toLowerCase());
    const linhas = lista.map(r => {
      const pos = Math.max(0, Math.min(100, (r.valor + 100) / 2));
      return `
      <div class="psn-entre-item" data-com="${esc(r.nome)}">
        <div class="psn-atitude-topo">
          <button class="psn-entre-nome" type="button"
                  onclick="window.Personagens._abrir('${aspas(r.nome)}')"
                  title="Abrir a ficha de ${esc(r.nome)}">${esc(r.nome)}</button>
          <span class="psn-atitude-rotulo">${esc(r.rotulo)}</span>
          <span class="psn-atitude-valor">${r.valor >= 0 ? '+' : ''}${r.valor}</span>
        </div>
        <div class="psn-barra" role="img" aria-label="Relação ${r.valor} de -100 a 100">
          <div class="psn-barra-meio"></div>
          <div class="psn-barra-marca" style="left:${pos}%"></div>
        </div>
        ${r.motivo ? `<p class="psn-conduta">${esc(r.motivo)}</p>` : ''}
        ${(r.historico || []).length ? `<ul class="psn-historico">${r.historico.map(h => `
          <li><span class="psn-delta ${h.delta >= 0 ? 'psn-sobe' : 'psn-desce'}">${h.delta >= 0 ? '+' : ''}${h.delta}</span>
              ${esc(h.motivo)}${h.capitulo ? ` <small>cap. ${esc(h.capitulo)}</small>` : ''}</li>`).join('')}</ul>` : ''}
        ${_ajustando === `entre:${r.nome}`
          ? painel(`entre:${r.nome}`, r.valor, `O que ${f.nome} sente por ${r.nome}`)
          : `<div class="psn-entre-acoes">
               ${botaoAjustar(`entre:${r.nome}`)}
               <button class="lcl-btn lcl-btn-apagar"
                       onclick="window.Personagens._apagarEntre('${aspas(r.nome)}')">Tirar</button>
             </div>`}
      </div>`;
    }).join('');

    const novo = !nomes.length ? '' : (_ajustando === 'entre:novo' ? `
      <div class="psn-entre-novo">
        <label class="psn-ajuste-linha">Com
          <select id="psn-entre-quem" aria-label="Com quem">
            ${nomes.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('')}
          </select>
        </label>
        ${painel('entre:novo', 0, 'Quanto')}
      </div>` : `
      <div class="psn-entre-novo">
        <button class="lcl-btn lcl-btn-sec"
                onclick="window.Personagens._ajustar('entre:novo')">Registrar uma relação</button>
      </div>`);

    return (linhas || `<div class="lcl-vazio">Nada registrado entre ${esc(f.nome)} e o resto do elenco.</div>`) + novo;
  }

  // Os nomes que a tela já tem em mãos, sem ir ao servidor de novo.
  function _nomesDaCampanha() {
    const mem = window._lastMem || {};
    const nomes = []
      .concat((mem.party || []).map(p => p.name || ''))
      .concat((mem.characters || []).map(c => c.name || ''))
      .filter(Boolean);
    return Array.from(new Set(nomes)).sort((a, b) => a.localeCompare(b, 'pt-BR'));
  }

  // No romance: afeto e confiança, o vínculo e o porquê das últimas mudanças,
  // com as mesmas barras da atitude. Vale também para quem é do grupo.
  function relacaoDoRomance(r, acoes) {
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
    const momentos = (r.momentos || []).length
      ? `<h3 class="psn-subsecao">Momentos</h3>${window.linhaDoTempo(r.momentos)}`
      : '';
    return `${r.vinculo ? `<p class="psn-vinculo">${esc(r.vinculo)}</p>` : ''}
      ${acoes || ''}
      <div class="psn-atitude psn-romance">${window.escadaDaRelacao(r.estagio)}</div>
      ${window.encontrosDaPessoa(r.encontros)}
      ${window.tensoesDaPessoa(r.tensoes)}
      ${barra('Afeto', r.afeto, ['aversão', 'devoção'])}
      ${barra('Confiança', r.confianca, ['desconfia', 'confia'])}
      ${window.segredosDaPessoa(r.segredos) ? `<h3 class="psn-subsecao">Segredos</h3>${window.segredosDaPessoa(r.segredos)}` : ''}
      ${momentos}
      <h3 class="psn-subsecao">Mudanças</h3>
      ${hist}`;
  }

  // Gestos do romance: atalhos para falas comuns ao mestre, como o "Falar com".
  // Quem decide o que acontece é ele — nem todo convite é aceito. Só com a
  // pessoa por perto (do grupo, ou alcançável) e viva.
  function gestos(f) {
    const r = f.relacao;
    if (!r) return '';
    const nome = f.nome;
    const vivo = (f.status || '').toLowerCase() !== 'morto';
    const perto = vivo && (f.do_grupo || f.pode_falar);
    const falas = [
      ['Convidar para sair', `Quero convidar ${nome} para sair.`],
      ['Marcar um encontro', `Quero marcar um encontro com ${nome}.`],
      ['Dar um presente', `Quero dar um presente para ${nome}.`],
      ['Pedir desculpas', `Quero pedir desculpas a ${nome}.`],
      ['Declarar-se', `Quero me declarar para ${nome}.`],
      ...((r.segredos && r.segredos.voce_esconde) || []).map(t => [`Contar: ${t}`, `Quero contar a ${nome} sobre ${t}.`]),
    ];
    if (!vivo) return '';
    const botoes = falas.map(([rotulo, fala]) => `
      <button class="lcl-btn${perto ? ' lcl-btn-ir' : ''}" ${perto ? '' : 'disabled'}
              title="${perto ? `Manda ao mestre: ${esc(fala)}` : 'Longe: vá até onde está primeiro'}"
              onclick="window.Personagens._dizer('${aspas(fala)}')">${esc(rotulo)}</button>`).join('');
    return `<div class="psn-gestos">
      <h3 class="psn-subsecao">Gestos</h3>
      <div class="psn-gestos-botoes">${botoes}</div>
      ${perto ? '' : '<p class="psn-gestos-longe">Longe de você: os gestos ficam para quando estiverem juntos.</p>'}
    </div>`;
  }

  // Fantasia: o laço do companheiro e os títulos que o mundo deu a ele.
  function laco(f) {
    const titulos = (f.titulos || []).map(t => `
      <li class="rel-seg"><span>Título</span> <strong>${esc(t.titulo)}</strong>${t.motivo ? ` — ${esc(t.motivo)}` : ''}</li>`).join('');
    const l = f.laco;
    if (!l && !titulos) return '';
    const pos = l ? Math.max(0, Math.min(100, (l.lealdade.valor + 100) / 2)) : 0;
    const arco = l && l.arco ? `
      <p class="rel-seg-linha"><span>Arco</span> ${esc(l.arco.titulo)} <em>(${esc(l.arco.estado)})</em></p>
      ${l.arco.passos.length ? `<ol class="rel-momentos">${l.arco.passos.map(p => `
        <li class="rel-momento"><span class="rel-momento-titulo">${esc(p.texto)}</span>${
          p.capitulo ? ` <small class="rel-momento-cap">cap. ${esc(p.capitulo)}</small>` : ''}</li>`).join('')}</ol>` : ''}` : '';
    return `
      <h2 class="lcl-secao">${l ? 'Laço' : 'Títulos'}</h2>
      ${l ? `<div class="psn-atitude psn-romance${l.lealdade.valor < 0 ? ' psn-romance-negativo' : ''}">
        <div class="psn-atitude-topo"><span class="psn-atitude-rotulo">Lealdade: ${esc(l.lealdade.faixa)}</span>
          <span class="psn-atitude-valor">${l.lealdade.valor >= 0 ? '+' : ''}${l.lealdade.valor}</span></div>
        <div class="psn-barra" role="img" aria-label="Lealdade ${l.lealdade.valor} de -100 a 100">
          <div class="psn-barra-meio"></div><div class="psn-barra-marca" style="left:${pos}%"></div></div>
        <div class="psn-barra-pontas"><span>partir</span><span>até o fim</span></div></div>
        ${l.objetivo ? `<p class="rel-seg-linha"><span>Quer</span> ${esc(l.objetivo)}</p>` : ''}
        ${_ajustando === 'lealdade'
          ? painel('lealdade', l.lealdade.valor, 'Lealdade')
          : botaoAjustar('lealdade')}
        ${arco}` : ''}
      ${titulos ? `<ul class="rel-segs psn-titulos">${titulos}</ul>` : ''}`;
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
      q('psn-entre-bloco').classList.add('hidden');
      q('psn-sabe').innerHTML = '';
      q('psn-cenas').innerHTML = '';
      q('psn-ligacoes').innerHTML = '';
      q('psn-editar').classList.add('hidden');
      q('psn-apagar').classList.add('hidden');
      return;
    }
    q('psn-nome').textContent = _last.nome;
    const status = (_last.status || '').toLowerCase();
    q('psn-status').textContent = status && status !== 'vivo' ? `— ${_last.status}` : '';
    q('psn-onde').innerHTML = onde(_last);
    q('psn-desc').textContent = _last.descricao || '';
    q('psn-tracos').textContent = _last.tracos ? `Traços: ${_last.tracos}` : '';
    q('psn-relacao-bloco').classList.toggle('hidden', !_last.atitude && !_last.relacao);
    q('psn-entre-bloco').classList.remove('hidden');
    q('psn-relacao-titulo').textContent = _last.relacao ? 'Relação com você' : 'Relação com o grupo';
    q('psn-laco').innerHTML = laco(_last);
    q('psn-sabe-titulo').textContent = window.frase('sabe', 'O que o grupo sabe');
    // Pelo nome: "com ele" supunha o gênero de todo personagem.
    q('psn-cenas-titulo').textContent = `Últimas cenas com ${_last.nome}`;
    q('psn-relacao').innerHTML = _last.relacao
      ? relacaoDoRomance(_last.relacao, gestos(_last)) : relacao(_last.atitude);
    q('psn-entre-titulo').textContent = `Como ${_last.nome} se dá com os outros`;
    q('psn-entre').innerHTML = entre(_last);
    const sabe = _last.conhecido || [];
    q('psn-sabe').innerHTML = sabe.length
      ? `<ul class="psn-sabe-lista">${sabe.map(s => `<li>${esc(s)}</li>`).join('')}</ul>`
      : '<div class="lcl-vazio">Nada registrado ainda.</div>';
    q('psn-cenas').innerHTML = cenas(_last);
    q('psn-ligacoes').innerHTML = ligacoes(_last);
    q('psn-editar').classList.remove('hidden');
    // Apagar é para a figuração que o combate deixa para trás — o inimigo
    // morto que continua na lista. Quem é do grupo não some por um clique:
    // para isso existe o editor.
    q('psn-apagar').classList.toggle('hidden', !!_last.do_grupo);
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
    _ajustando = '';
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

  // O inimigo morto ficava na lista até o jogador abrir o editor de ficha e
  // achar o botão lá dentro. Aqui é um clique, com pergunta antes: apagar é
  // sem volta, e o mestre não tem como desfazer.
  async function apagar() {
    const nome = _last.nome || '';
    if (!nome || _last.do_grupo) return;
    if (typeof window.showConfirm === 'function') {
      const ok = await window.showConfirm(
        `Apagar ${nome}?`,
        'Ele sai da memória da campanha: some da lista, do mapa e do que o mestre lembra. Não dá para desfazer.',
        'danger', 'Apagar');
      if (!ok) return;
    } else if (!confirm(`Apagar ${nome}? Não dá para desfazer.`)) {
      return;
    }
    mensagem('Apagando…');
    try {
      const f = (window.authFetch || fetch);
      const r = await f(`${window.API || ''}/api/memory/characters/${encodeURIComponent(nome)}`,
                        { method: 'DELETE' });
      if (!r.ok) { mensagem('O servidor não apagou. Tente de novo.', true); return; }
      fechar();
      if (typeof window.refreshMemory === 'function') window.refreshMemory();
      if (window.Elenco && typeof window.Elenco.sync === 'function') window.Elenco.sync();
      if (typeof window.showToast === 'function') window.showToast(`${nome} foi apagado.`);
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  async function enviarRelacao(corpo) {
    mensagem('Salvando…');
    try {
      const f = (window.authFetch || fetch);
      const r = await f(`${window.API || ''}/api/characters/relacao`, {
        method: 'POST',
        body: JSON.stringify({ nome: _last.nome, ...corpo }),
      });
      const d = await r.json();
      if (!r.ok || d.erro) { mensagem(d.erro || 'Não deu para salvar.', true); return; }
      _ajustando = '';
      render(d);
      if (typeof window.refreshMemory === 'function') window.refreshMemory();
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  function salvarAjuste() {
    const painelEl = document.querySelector('#pessoa-overlay .psn-ajuste');
    if (!painelEl) return;
    const alvo = painelEl.getAttribute('data-alvo') || '';
    const valor = Number(painelEl.querySelector('.psn-ajuste-valor').value);
    const motivo = painelEl.querySelector('.psn-ajuste-motivo').value || '';
    if (!Number.isFinite(valor)) { mensagem('Escreva um número de -100 a 100.', true); return; }

    if (alvo === 'atitude') return enviarRelacao({ atitude: valor, motivo });
    if (alvo === 'lealdade') return enviarRelacao({ lealdade: valor, motivo });
    if (alvo === 'entre:novo') {
      const sel = q('psn-entre-quem');
      if (!sel || !sel.value) { mensagem('Escolha com quem.', true); return; }
      return enviarRelacao({ para: sel.value, valor, motivo });
    }
    if (alvo.indexOf('entre:') === 0) {
      return enviarRelacao({ para: alvo.slice(6), valor, motivo });
    }
  }

  async function apagarEntre(com) {
    if (typeof window.showConfirm === 'function') {
      const ok = await window.showConfirm(
        `Tirar a relação com ${com}?`,
        `O que ${_last.nome} sentia por ${com} sai da memória, com o histórico.`,
        'warning', 'Tirar');
      if (!ok) return;
    }
    enviarRelacao({ para: com, apagar: true });
  }

  window.Personagens = {
    _abrir: abrir,
    _fechar: fechar,
    _apagar: apagar,
    _ajustar: (alvo) => { _ajustando = alvo; render(_last); },
    _fecharAjuste: () => { _ajustando = ''; render(_last); },
    _salvarAjuste: salvarAjuste,
    _apagarEntre: apagarEntre,
    _ir: (lugar) => enviar(`Vamos até ${lugar}.`),
    _falar: (nome) => enviar(`Quero falar com ${nome}.`),
    _dizer: (fala) => enviar(fala),
    _verLocal: (lugar) => { fechar(); if (window.Locais) window.Locais._abrir(lugar); },
    _editar: editar,
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
