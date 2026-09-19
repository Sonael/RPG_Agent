// ═══════════════════════════════════════════════════════════════════
//  missoes.js — Tela de missões ("O Livro de Missões")
//
//  Abre pelo clique nas missões da barra lateral. Mostra todas: as ativas
//  com objetivos marcáveis, quem encomendou (com a ficha do personagem a um
//  clique) e a recompensa; as concluídas, falhadas e abandonadas com o
//  desfecho.
//
//  REGRA DE OURO, a mesma das outras telas: nenhuma regra de jogo aqui. O que
//  conta como pronta para entregar, o que foi mudado e o aviso ao mestre vêm
//  do motor (rpg/missoes.py via /api/quests/*).
//
//  Marcar objetivo é a lista de tarefas do jogador; quem decide o que aconteceu
//  na história é o mestre. Por isso, ao fechar, se algo mudou, a tela manda UM
//  aviso [MISSÕES ATUALIZADAS NA TELA]. Concluir e falhar ficam com o mestre;
//  abandonar é decisão do grupo e fica aqui.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';

  let _open = false;
  let _busy = false;
  let _last = {};
  let _aba = 'ativa';
  let _confirmandoAbandono = '';

  const esc = (s) => (window.escapeHtml ? window.escapeHtml(s) : String(s == null ? '' : s));
  const q = (id) => document.getElementById(id);
  const aspas = (s) => esc(s).replace(/'/g, "\\'");

  const ABAS = [
    ['ativa', 'Ativas', ['ativa']],
    ['concluida', 'Concluídas', ['concluida']],
    ['encerrada', 'Falhadas e abandonadas', ['falhou', 'abandonada']],
  ];
  const ROTULO_STATUS = { ativa: 'ativa', concluida: 'concluída', falhou: 'falhou', abandonada: 'abandonada' };

  function ensureDom() {
    if (q('missoes-overlay')) return;
    const o = document.createElement('div');
    o.id = 'missoes-overlay';
    o.className = 'hidden';
    o.innerHTML = `
      <div id="msn-frame" role="dialog" aria-modal="true" aria-labelledby="msn-titulo">
        <header class="lcl-header">
          <button class="lcl-close" onclick="window.Missoes._fechar()"
                  aria-label="Fechar" title="Fechar">✕</button>
          <h1 class="lcl-title" id="msn-titulo">O Livro de Missões</h1>
          <div id="msn-abas" class="msn-abas" role="tablist"></div>
        </header>
        <div id="msn-lista" class="msn-lista"></div>
        <div class="lcl-rodape">
          <div id="msn-msg" class="lcl-msg" aria-live="polite"></div>
          <button class="lcl-fechar" onclick="window.Missoes._fechar()">Fechar</button>
        </div>
      </div>`;
    o.addEventListener('click', (e) => { if (e.target === o) fechar(); });
    document.body.appendChild(o);
  }

  async function api(path, opts) {
    const f = (window.authFetch || fetch);
    const r = await f(`${window.API || ''}${path}`, opts || {});
    return r.json();
  }
  const getState = () => api('/api/quests/state');
  const doAction = (p) => api('/api/quests/action', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p),
  });

  // ---- Render ------------------------------------------------------
  function abas() {
    const c = _last.contagem || {};
    return ABAS.map(([id, rotulo, status]) => {
      const n = status.reduce((s, k) => s + (c[k] || 0), 0);
      return `<button class="msn-aba${_aba === id ? ' msn-aba-on' : ''}" role="tab"
                      aria-selected="${_aba === id}" data-aba="${id}"
                      onclick="window.Missoes._aba('${id}')">${rotulo} <span class="msn-aba-n">${n}</span></button>`;
    }).join('');
  }

  function quemDeu(m) {
    const quem = m.quem_deu;
    if (!quem) return '';
    const nome = quem.existe && window.Personagens
      ? `<a href="#" class="lcl-migalha" onclick="event.preventDefault();window.Missoes._verPessoa('${aspas(quem.nome)}')">${esc(quem.nome)}</a>`
      : esc(quem.nome);
    return `<div class="msn-linha"><span class="msn-rotulo">Encomendada por</span> ${nome}</div>`;
  }

  function objetivos(m) {
    if (!m.objetivos.length) return '';
    const ativa = m.status === 'ativa';
    return `<ul class="msn-objetivos">${m.objetivos.map(o => `
      <li class="msn-objetivo${o.feito ? ' msn-feito' : ''}">
        <label>
          <input type="checkbox" ${o.feito ? 'checked' : ''} ${ativa ? '' : 'disabled'}
                 onchange="window.Missoes._marcar('${aspas(m.titulo)}', ${o.indice}, this.checked)">
          <span>${esc(o.texto)}</span>
        </label>
      </li>`).join('')}</ul>`;
  }

  function cartao(m) {
    const ativa = m.status === 'ativa';
    const cap = m.cap_inicio
      ? `cap. ${esc(m.cap_inicio)}${m.cap_fim ? ` a ${esc(m.cap_fim)}` : ''}` : '';
    const acoes = [];
    if (ativa && m.pronta_para_entregar && m.quem_deu) {
      acoes.push(`<button class="lcl-btn lcl-btn-ir"
        title="Manda ao mestre: Quero falar com ${esc(m.quem_deu.nome)} sobre a missão."
        onclick="window.Missoes._entregar('${aspas(m.titulo)}','${aspas(m.quem_deu.nome)}')">Falar com ${esc(m.quem_deu.nome)}</button>`);
    }
    if (ativa) {
      const confirmando = _confirmandoAbandono === m.titulo;
      acoes.push(`<button class="lcl-btn lcl-btn-sec msn-abandonar${confirmando ? ' msn-confirmar' : ''}"
        onclick="window.Missoes._abandonar('${aspas(m.titulo)}')">${confirmando ? 'Confirmar abandono' : 'Abandonar'}</button>`);
    }
    return `
      <article class="lcl-item msn-cartao msn-${esc(m.status)}" data-titulo="${esc(m.titulo)}">
        <div class="lcl-item-cabeca">
          <span class="lcl-item-nome msn-nome">${esc(m.titulo)}</span>
          ${m.total ? `<span class="lcl-marca">${m.feitos}/${m.total}</span>` : ''}
          ${ativa ? '' : `<span class="lcl-marca msn-status">${esc(ROTULO_STATUS[m.status] || m.status)}</span>`}
          ${m.pronta_para_entregar ? '<span class="lcl-marca lcl-marca-grupo">pronta para entregar</span>' : ''}
          ${cap ? `<span class="msn-cap">${cap}</span>` : ''}
        </div>
        ${m.descricao ? `<p class="lcl-item-desc">${esc(m.descricao)}</p>` : ''}
        ${quemDeu(m)}
        ${m.recompensa ? `<div class="msn-linha"><span class="msn-rotulo">Recompensa</span> ${esc(m.recompensa)}</div>` : ''}
        ${objetivos(m)}
        ${m.desfecho ? `<div class="msn-linha msn-desfecho"><span class="msn-rotulo">Desfecho</span> ${esc(m.desfecho)}</div>` : ''}
        ${acoes.length ? `<div class="lcl-item-acoes">${acoes.join('')}</div>` : ''}
      </article>`;
  }

  function render(snap) {
    _last = snap || {};
    ensureDom();
    q('msn-abas').innerHTML = abas();
    const status = (ABAS.find(a => a[0] === _aba) || ABAS[0])[2];
    const lista = (_last.missoes || []).filter(m => status.includes(m.status));
    const vazio = { ativa: 'Nenhuma missão ativa.', concluida: 'Nenhuma missão concluída ainda.',
                    encerrada: 'Nenhuma missão falhada ou abandonada.' }[_aba];
    q('msn-lista').innerHTML = lista.length
      ? lista.map(cartao).join('')
      : `<div class="lcl-vazio msn-vazio">${vazio}</div>`;
  }

  function mensagem(txt, erro) {
    const el = q('msn-msg');
    if (!el) return;
    el.textContent = txt || '';
    el.classList.toggle('lcl-msg-erro', !!erro);
  }

  // ---- Abrir / fechar ----------------------------------------------
  async function abrir(titulo) {
    ensureDom();
    q('msn-titulo').textContent = window.nomeDaTela('titulo_missoes', 'O Livro de Missões');
    _confirmandoAbandono = '';
    if (!_open) {
      q('missoes-overlay').classList.remove('hidden');
      document.body.classList.add('missoes-on');
      _open = true;
    }
    mensagem('Carregando…');
    try {
      const snap = await getState();
      if (titulo) {
        const m = (snap.missoes || []).find(x => x.titulo === titulo);
        if (m) _aba = (ABAS.find(a => a[2].includes(m.status)) || ABAS[0])[0];
      }
      render(snap);
      mensagem('');
      if (titulo) destacar(titulo);
    } catch (_) {
      mensagem('Falha de conexão.', true);
    }
  }

  function destacar(titulo) {
    const el = [...document.querySelectorAll('#msn-lista .msn-cartao')].find(x => x.dataset.titulo === titulo);
    if (!el) return;
    el.classList.add('msn-destaque');
    try { el.scrollIntoView({ block: 'nearest' }); } catch (_) { /* sem rolagem */ }
    setTimeout(() => el.classList.remove('msn-destaque'), 2400);
  }

  // Fechar manda ao mestre o que o jogador mudou, se mudou, numa mensagem só.
  async function fechar(semAviso) {
    const el = q('missoes-overlay');
    if (el) el.classList.add('hidden');
    document.body.classList.remove('missoes-on');
    const estavaAberta = _open;
    _open = false;
    window.dispatchEvent(new Event('rpg:tela-fechou'));
    if (!estavaAberta || !(_last.mudancas_pendentes > 0)) return;
    try {
      const res = await doAction({ action: 'fechar' });
      if (typeof window.refreshMemory === 'function') window.refreshMemory();
      if (!semAviso && res && res.recap && typeof window.sendToAgent === 'function') {
        await window.sendToAgent(res.recap, true, 'tela');
      }
    } catch (_) { /* fechar já é o essencial */ }
  }

  // ---- Ações --------------------------------------------------------
  async function agir(payload) {
    if (_busy) return null;
    _busy = true;
    try {
      const res = await doAction(payload);
      _busy = false;
      if (res) {
        mensagem(res.message || '', res.ok === false);
        if (res.snapshot) render(res.snapshot);
      }
      return res;
    } catch (_) {
      _busy = false;
      mensagem('Falha de conexão.', true);
      return null;
    }
  }

  async function marcar(titulo, indice, feito) {
    const res = await agir({ action: feito ? 'marcar' : 'desmarcar', quest: titulo, objective: indice });
    if (res && res.ok !== false && typeof window.refreshMemory === 'function') window.refreshMemory();
  }

  async function abandonar(titulo) {
    // Dois cliques: abandonar não tem volta pela tela.
    if (_confirmandoAbandono !== titulo) {
      _confirmandoAbandono = titulo;
      render(_last);
      mensagem(`Clique de novo para abandonar "${titulo}".`);
      return;
    }
    _confirmandoAbandono = '';
    const res = await agir({ action: 'abandonar', quest: titulo });
    if (res && res.ok !== false && typeof window.refreshMemory === 'function') window.refreshMemory();
  }

  // A fala vai ao mestre como a da ficha do local: quem decide é ele.
  async function entregar(titulo, quem) {
    if (typeof waiting !== 'undefined' && waiting) {
      mensagem('Aguarde o mestre terminar de responder.', true);
      return;
    }
    if (typeof window.sendToAgent !== 'function' || typeof window.appendUser !== 'function') return;
    // O aviso das marcações vai antes da fala, para o mestre saber o que o
    // jogador considera feito quando ele chegar para entregar.
    const texto = `Quero falar com ${quem} sobre a missão "${titulo}".`;
    let recap = '';
    if (_last.mudancas_pendentes > 0) {
      try {
        const res = await doAction({ action: 'fechar' });
        recap = (res && res.recap) || '';
        _last.mudancas_pendentes = 0;       // já recolhido: fechar não pede de novo
      } catch (_) { /* segue para a fala */ }
    }
    await fechar(true);
    if (recap) await window.sendToAgent(recap, true, 'tela');
    window.appendUser(texto);
    window.sendToAgent(texto, true);
  }

  window.Missoes = {
    _abrir: abrir,
    _fechar: () => fechar(false),
    _aba: (id) => { _aba = id; _confirmandoAbandono = ''; render(_last); mensagem(''); },
    _marcar: marcar,
    _abandonar: abandonar,
    _entregar: entregar,
    _verPessoa: (nome) => { fechar(false); if (window.Personagens) window.Personagens._abrir(nome); },
    _estado: () => _last,
  };

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) fechar(false); });
  document.addEventListener('DOMContentLoaded', () => { ensureDom(); });
})();
