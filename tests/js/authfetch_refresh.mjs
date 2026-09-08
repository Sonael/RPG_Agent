/*
  authfetch_refresh.mjs
  Corrida de renovação de sessão no authFetch (static/js/utils.js).

  O Supabase GIRA o refresh token: cada uso invalida o anterior. A tela dispara
  várias chamadas ao mesmo tempo — o /api/chat, que é longo, mais um
  refreshMemory() a cada tool_result, mais o Combat.sync() que vem junto. Quando
  o access token vence, todas levam 401 quase juntas; se cada uma renovar por
  conta própria, a primeira vence e as outras recebem
  "Invalid Refresh Token: Already Used" e derrubam a sessão — inclusive a que
  acabou de ser renovada com sucesso.

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

// Resposta mínima: o authFetch só olha .status e chama .json().
function resposta(corpo, status) {
  return {
    status: status,
    ok: status >= 200 && status < 300,
    json: function () { return Promise.resolve(corpo); },
  };
}

function bancada(bloco) {
  const est = { validos: new Set(['A1']), refreshVivo: 'R1', usados: new Set(), n: 1,
                postsRefresh: 0, deslogou: false };
  const store = new Map([['rpg_access_token', 'A1'], ['rpg_refresh_token', 'R1']]);

  const ctx = {
    API: '', console, setTimeout, clearTimeout,
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, v),
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
        const t = JSON.parse(opts.body).refresh_token;
        await new Promise(r => setTimeout(r, 40));          // latência da rede
        if (est.usados.has(t)) {
          return resposta({ error: 'Invalid Refresh Token: Already Used' }, 401);
        }
        if (t !== est.refreshVivo) {
          return resposta({ error: 'Invalid Refresh Token' }, 401);
        }
        est.usados.add(t); est.n++;
        est.validos.add('A' + est.n); est.refreshVivo = 'R' + est.n;
        return resposta({ ok: true, access_token: 'A' + est.n, refresh_token: 'R' + est.n }, 200);
      }

      await new Promise(r => setTimeout(r, 15));
      if (bearer === 'A1') return resposta({ error: 'token is expired' }, 401);  // A1 venceu
      if (!est.validos.has(bearer)) return resposta({ error: 'invalid' }, 401);
      return resposta({ ok: true, quem: bearer }, 200);
    },
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(bloco, ctx);
  return { ctx, est };
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

  async function sessaoMorta() {
    const { ctx, est } = bancada(bloco);
    est.refreshVivo = 'OUTRO';                 // R1 não vale mais nada
    const r = await ctx.authFetch('/api/x');
    checar('sessao realmente expirada devolve 401', r.status === 401, r.status, 401);
    checar('sessao realmente expirada desloga', est.deslogou,
           est.deslogou ? 'deslogou' : 'seguiu logado', 'deslogou');
  }

  async function tokenTrocadoNoMeio() {
    const { ctx, est } = bancada(bloco);
    const p = ctx.authFetch('/api/lenta');               // sai com A1, que já venceu
    await new Promise(r => setTimeout(r, 5));
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
  await sessaoMorta();
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
