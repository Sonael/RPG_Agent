/*
  authfetch_refresh.mjs
  A renovação de sessão do authFetch (static/js/utils.js).

  O Supabase GIRA o refresh token: cada uso invalida o anterior. Renovar é um
  tiro de uma bala só, e quem perde a bala cai no login — no meio da cena, que
  é o pior momento possível. O log real que motivou a segunda rodada deste
  arquivo:

      GET /api/characters/index 401       (o access token venceu enquanto a
      Falha no refresh: Invalid Refresh    tela ficou uma hora aberta)
      Token: Already Used
      POST /api/auth/refresh 401
      GET /login.html

  "Already Used" quer dizer que o papel guardado no navegador JÁ tinha sido
  gasto. Três caminhos levam até aí, e cada um tem o seu teste:

    1. Ninguém renovava antes da hora: só depois de um 401 alguém agia, e aí a
       bala era gasta sob pressão, com a tela cheia de chamadas.
    2. A trava de renovação era por ABA. Duas abas (ou a janela do aplicativo
       instalado) renovavam com o mesmo papel; o Supabase trata reuso como
       roubo e mata a sessão inteira.
    3. Qualquer tropeço — rede fora, 500 do servidor — era lido como "sessão
       morta" e deslogava o jogador.

  O teste carrega o bloco de auth REAL do utils.js num contexto isolado e o
  submete a um Supabase simulado que gira o token igual ao de verdade.

  Escrito para rodar em Node antigo (o padrão do apt no Ubuntu 22.04 é o 12):
  sem top-level await, sem import.meta.dirname (20.11+) e com uma Response
  própria em vez da global do fetch (18+). O que se testa é o utils.js, não o
  runtime — não faz sentido exigir um Node novo por causa do arame do teste.

  Uso:  node tests/js/authfetch_refresh.mjs [caminho/para/utils.js] [--json=arq]
        saída 0 = passou;  1 = falhou;  2 = não achei o bloco de auth
*/
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

const AQUI = path.dirname(url.fileURLToPath(import.meta.url));
const RAIZ = path.resolve(AQUI, '..', '..');
const alvoArg = process.argv.slice(2).find(a => !a.startsWith('--'));
const ALVO = alvoArg || path.join(RAIZ, 'static', 'js', 'utils.js');

// Resposta mínima: o authFetch só olha .status/.ok e chama .json().
function resposta(corpo, status) {
  return {
    status: status,
    ok: status >= 200 && status < 300,
    json: function () { return Promise.resolve(corpo); },
  };
}

function espera(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// Um JWT de mentira, só com o exp que o utils.js lê. A assinatura não importa:
// quem confere de verdade é o servidor; aqui só se testa a LEITURA do prazo.
function jwt(segundosRestantes) {
  const corpo = Buffer.from(JSON.stringify({
    exp: Math.floor(Date.now() / 1000) + segundosRestantes,
  })).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return 'cabeca.' + corpo + '.assinatura';
}

// O navigator.locks do navegador, na versão de bancada: uma fila só, e essa
// fila é COMPARTILHADA entre as abas do mesmo mundo — que é exatamente o que
// o Web Locks faz entre abas do mesmo site.
function criarTravas() {
  let fila = Promise.resolve();
  return {
    request: function (nome, tarefa) {
      const proxima = fila.then(() => tarefa());
      fila = proxima.then(() => {}, () => {});
      return proxima;
    },
  };
}

// O "mundo": o Supabase simulado mais o localStorage e as travas. Duas
// bancadas no mesmo mundo são duas abas do mesmo navegador.
function criarMundo(op) {
  op = op || {};
  const acesso = op.acesso || 'A1';
  const est = {
    validos: new Set([acesso]),
    vencido: op.vencido === undefined ? acesso : op.vencido,
    refreshVivo: 'R1',
    usados: new Set(),
    n: 1,
    postsRefresh: 0,
    respostas401: 0,
    deslogou: false,
    redeCaida: !!op.redeCaida,
    statusDoRefresh: op.statusDoRefresh || 0,
    mintar: op.mintar || function (n) { return 'A' + n; },
  };
  const store = new Map([['rpg_access_token', acesso]]);
  if (!op.semRefresh) store.set('rpg_refresh_token', 'R1');
  // travasPresas: a trava nunca é entregue (aba congelada segurando ela) e o
  // navegador desiste da espera. O jogo não pode pendurar por causa disso.
  const travas = op.travasPresas
    ? { request: function () { return Promise.reject(new Error('AbortError')); } }
    : criarTravas();
  return { est: est, store: store, travas: op.semTravas ? null : travas,
           storeQuebrado: !!op.storeQuebrado };
}

function bancada(bloco, mundo) {
  mundo = mundo || criarMundo();
  const est = mundo.est;
  const store = mundo.store;

  const ctx = {
    API: '', console, setTimeout, clearTimeout,
    atob: function (s) { return Buffer.from(s, 'base64').toString('binary'); },
    navigator: { locks: mundo.travas },
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => {
        // Navegador em aba anônima, cota cheia, permissão negada: gravar pode
        // simplesmente falhar.
        if (mundo.storeQuebrado) throw new Error('QuotaExceededError');
        store.set(k, v);
      },
      removeItem: k => store.delete(k),
    },
    window: {
      location: {
        pathname: '/game.html',
        set href(_) { est.deslogou = true; },
        get href() { return '/game.html'; },
      },
    },
    async fetch(alvo, opts) {
      opts = opts || {};
      const u = String(alvo);
      const bearer = ((opts.headers || {})['Authorization'] || '').replace('Bearer ', '');

      if (u.indexOf('/api/auth/refresh') !== -1) {
        est.postsRefresh++;
        await espera(40);                                   // latência da rede
        if (est.redeCaida) throw new TypeError('Failed to fetch');
        if (est.statusDoRefresh) {
          return resposta({ error: 'o servidor tropecou' }, est.statusDoRefresh);
        }
        const t = JSON.parse(opts.body).refresh_token;
        if (est.usados.has(t)) {
          return resposta({ error: 'Invalid Refresh Token: Already Used' }, 401);
        }
        if (t !== est.refreshVivo) {
          return resposta({ error: 'Invalid Refresh Token' }, 401);
        }
        est.usados.add(t); est.n++;
        const novo = est.mintar(est.n);
        est.validos.add(novo); est.refreshVivo = 'R' + est.n;
        return resposta({ ok: true, access_token: novo, refresh_token: 'R' + est.n }, 200);
      }

      await espera(15);
      if (bearer === est.vencido || !est.validos.has(bearer)) {
        est.respostas401++;
        return resposta({ error: 'token is expired' }, 401);
      }
      return resposta({ ok: true, quem: bearer }, 200);
    },
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(bloco, ctx);
  return { ctx: ctx, est: est, mundo: mundo };
}

async function principal() {
  // Recorta só o bloco de auth: o resto do utils.js mexe em DOM.
  const fonte = fs.readFileSync(ALVO, 'utf8');
  const ini = fonte.indexOf('function getTokens()');
  const fim = fonte.indexOf('//  Toast');
  if (ini < 0 || fim < 0) {
    console.error('Não achei o bloco de auth em ' + ALVO);
    return 2;
  }
  const bloco = fonte.slice(ini, fonte.lastIndexOf('}', fim) + 1);

  const resultados = [];
  function checar(label, passou, obtido, esperado) {
    resultados.push({ label, passed: passou, got: String(obtido), expected: String(esperado) });
  }

  // ── 1. Chamadas simultâneas na mesma aba ────────────────────────────────
  async function corrida(n) {
    const { ctx, est } = bancada(bloco);
    const chamadas = [];
    for (let i = 0; i < n; i++) chamadas.push(ctx.authFetch('/api/x' + i));
    const rs = await Promise.all(chamadas);
    const status = rs.map(r => r.status);
    checar(n + ' chamadas simultaneas gastam 1 refresh token',
           est.postsRefresh === 1, est.postsRefresh + ' POSTs', '1 POST');
    checar(n + ' chamadas simultaneas terminam todas em 200',
           status.every(s => s === 200), status.join(','), Array(n).fill(200).join(','));
    checar(n + ' chamadas simultaneas nao deslogam o jogador',
           !est.deslogou, est.deslogou ? 'deslogou' : 'seguiu logado', 'seguiu logado');
  }

  // Navegador antigo, sem Web Locks: sobra a promessa em voo, que sozinha já
  // dava conta das chamadas simultâneas da mesma aba. A trava é para a segunda
  // aba — não pode ser a única coisa segurando a primeira.
  async function corridaSemWebLocks(n) {
    const { ctx, est } = bancada(bloco, criarMundo({ semTravas: true }));
    const rs = await Promise.all(
      Array.from({ length: n }, (_, i) => ctx.authFetch('/api/x' + i)));
    checar(n + ' chamadas simultaneas sem Web Locks gastam 1 refresh token',
           est.postsRefresh === 1, est.postsRefresh + ' POSTs', '1 POST');
    checar(n + ' chamadas simultaneas sem Web Locks terminam em 200',
           rs.every(r => r.status === 200), rs.map(r => r.status).join(','),
           Array(n).fill(200).join(','));
  }

  // ── 2. Duas ABAS, cada uma com o seu JavaScript e o mesmo localStorage ──
  async function duasAbas() {
    const mundo = criarMundo();
    const a = bancada(bloco, mundo);
    const b = bancada(bloco, mundo);
    const rs = await Promise.all([a.ctx.authFetch('/api/x'), b.ctx.authFetch('/api/y')]);
    checar('duas abas com o mesmo token gastam 1 refresh token',
           mundo.est.postsRefresh === 1, mundo.est.postsRefresh + ' POSTs', '1 POST');
    checar('duas abas terminam as duas em 200',
           rs.every(r => r.status === 200), rs.map(r => r.status).join(','), '200,200');
    checar('duas abas nao deslogam o jogador',
           !mundo.est.deslogou, mundo.est.deslogou ? 'deslogou' : 'seguiu logado', 'seguiu logado');
  }

  // Aba congelada segurando a trava: o navegador desiste da espera e a
  // renovação tem de sair assim mesmo, sem trava.
  async function travaPresa() {
    const { ctx, est } = bancada(bloco, criarMundo({ travasPresas: true }));
    const r = await ctx.authFetch('/api/x');
    checar('trava presa nao pendura o jogo',
           r.status === 200 && est.postsRefresh === 1,
           'status ' + r.status + ', ' + est.postsRefresh + ' POSTs',
           'status 200, 1 POST');
  }

  // Se a renovação falhar DEPOIS do POST (o navegador recusou gravar), a
  // tentativa não pode recomeçar: o papel já foi gasto lá.
  async function falhaDepoisDeGastar() {
    const { ctx, est } = bancada(bloco, criarMundo({ storeQuebrado: true }));
    await ctx.authFetch('/api/x');
    checar('falha ao guardar o token nao gasta uma segunda renovacao',
           est.postsRefresh === 1, est.postsRefresh + ' POSTs', '1 POST');
  }

  // ── 3. Renovar ANTES de vencer, em vez de gastar um 401 ─────────────────
  async function renovaAntesDeVencer() {
    const mundo = criarMundo({ acesso: jwt(-5), mintar: () => jwt(3600) });
    const { ctx, est } = bancada(bloco, mundo);
    const r = await ctx.authFetch('/api/x');
    checar('token vencido renova antes de a chamada sair',
           r.status === 200 && est.respostas401 === 0 && est.postsRefresh === 1,
           'status ' + r.status + ', ' + est.respostas401 + ' respostas 401, '
             + est.postsRefresh + ' POSTs',
           'status 200, 0 respostas 401, 1 POST');
  }

  async function tokenLongeDoFimNaoRenova() {
    const mundo = criarMundo({ acesso: jwt(3600), vencido: '', mintar: () => jwt(3600) });
    const { ctx, est } = bancada(bloco, mundo);
    const r = await ctx.authFetch('/api/x');
    checar('token novo em folha nao gasta renovacao',
           r.status === 200 && est.postsRefresh === 0,
           'status ' + r.status + ', ' + est.postsRefresh + ' POSTs', 'status 200, 0 POSTs');
  }

  // ── 4. Relógio do computador errado não pode virar moedor de tokens ─────
  async function relogioErrado() {
    // Todo token que o servidor emite JÁ nasce vencido para este navegador.
    const mundo = criarMundo({ acesso: jwt(-30), mintar: n => jwt(-30 - n) });
    const { ctx, est } = bancada(bloco, mundo);
    const status = [];
    for (let i = 0; i < 5; i++) status.push((await ctx.authFetch('/api/x' + i)).status);
    checar('relogio errado nao gasta uma renovacao por chamada',
           est.postsRefresh === 1, est.postsRefresh + ' POSTs em 5 chamadas', '1 POST');
    checar('relogio errado nao impede o jogo',
           status.every(s => s === 200), status.join(','), '200,200,200,200,200');
  }

  // ── 5. Tropeço não é sessão morta ───────────────────────────────────────
  async function redeCaida() {
    const mundo = criarMundo({ redeCaida: true });
    const { ctx, est } = bancada(bloco, mundo);
    const r = await ctx.authFetch('/api/x');
    checar('rede fora no refresh nao desloga o jogador',
           !est.deslogou && r.status === 401,
           (est.deslogou ? 'deslogou' : 'seguiu logado') + ', status ' + r.status,
           'seguiu logado, status 401');
  }

  async function servidorTropecou() {
    const mundo = criarMundo({ statusDoRefresh: 500 });
    const { ctx, est } = bancada(bloco, mundo);
    await ctx.authFetch('/api/x');
    checar('500 no refresh nao desloga o jogador',
           !est.deslogou, est.deslogou ? 'deslogou' : 'seguiu logado', 'seguiu logado');
  }

  // ── 6. Sessão morta de verdade: aí sim, login ───────────────────────────
  async function sessaoMorta() {
    const mundo = criarMundo();
    const { ctx, est } = bancada(bloco, mundo);
    est.refreshVivo = 'OUTRO';                 // R1 não vale mais nada
    const r = await ctx.authFetch('/api/x');
    checar('sessao realmente expirada devolve 401', r.status === 401, r.status, 401);
    checar('sessao realmente expirada desloga', est.deslogou,
           est.deslogou ? 'deslogou' : 'seguiu logado', 'deslogou');
  }

  async function semRefreshGuardado() {
    const mundo = criarMundo({ semRefresh: true });
    const { ctx, est } = bancada(bloco, mundo);
    await ctx.authFetch('/api/x');
    checar('sem refresh token guardado, desloga sem bater no servidor',
           est.deslogou && est.postsRefresh === 0,
           (est.deslogou ? 'deslogou' : 'seguiu logado') + ', ' + est.postsRefresh + ' POSTs',
           'deslogou, 0 POSTs');
  }

  // ── 7. Quem perde a corrida não gasta uma segunda bala ──────────────────
  async function tokenTrocadoNoMeio() {
    const mundo = criarMundo();
    const { ctx, est } = bancada(bloco, mundo);
    const p = ctx.authFetch('/api/lenta');               // sai com A1, que já venceu
    await espera(5);
    ctx.localStorage.setItem('rpg_access_token', 'A9');  // outra chamada renovou
    est.validos.add('A9');
    const r = await p;
    checar('quem perde a corrida repete com o token novo, sem renovar de novo',
           r.status === 200 && est.postsRefresh === 0,
           'status ' + r.status + ', ' + est.postsRefresh + ' POSTs', 'status 200, 0 POSTs');
  }

  await corrida(2);
  await corrida(5);
  await corrida(12);
  await corridaSemWebLocks(5);
  await duasAbas();
  await travaPresa();
  await falhaDepoisDeGastar();
  await renovaAntesDeVencer();
  await tokenLongeDoFimNaoRenova();
  await relogioErrado();
  await redeCaida();
  await servidorTropecou();
  await sessaoMorta();
  await semRefreshGuardado();
  await tokenTrocadoNoMeio();

  const arg = process.argv.find(a => a.indexOf('--json=') === 0);
  if (arg) fs.writeFileSync(arg.slice(7), JSON.stringify(resultados), 'utf8');

  let falhou = 0;
  for (const r of resultados) {
    if (!r.passed) falhou++;
    console.log((r.passed ? 'ok   ' : 'FALHA') + '  ' + r.label
                + (r.passed ? '' : '\n        obtido:   ' + r.got
                                 + '\n        esperado: ' + r.expected));
  }
  console.log('\n' + (resultados.length - falhou) + '/' + resultados.length + ' passaram');
  return falhou ? 1 : 0;
}

principal().then(
  codigo => process.exit(codigo),
  erro => { console.error(erro && erro.stack || erro); process.exit(2); }
);
