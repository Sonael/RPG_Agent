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

  Uso:  node tests/js/authfetch_refresh.mjs [caminho/para/utils.js] [--json=arq]
        saída 0 = passou;  1 = falhou;  2 = não achei o bloco de auth
*/
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const RAIZ = path.resolve(import.meta.dirname, '..', '..');
const alvoArg = process.argv.slice(2).find(a => !a.startsWith('--'));
const ALVO = alvoArg || path.join(RAIZ, 'static', 'js', 'utils.js');

// Recorta só o bloco de auth: o resto do utils.js mexe em DOM.
const fonte = fs.readFileSync(ALVO, 'utf8');
const ini = fonte.indexOf('function getTokens()');
const fim = fonte.indexOf('//  Toast');
if (ini < 0 || fim < 0) {
  console.error('Não achei o bloco de auth em ' + ALVO);
  process.exit(2);
}
const bloco = fonte.slice(ini, fonte.lastIndexOf('}', fim) + 1);

function bancada() {
  const est = { validos: new Set(['A1']), refreshVivo: 'R1', usados: new Set(), n: 1,
                postsRefresh: 0, deslogou: false };
  const store = new Map([['rpg_access_token', 'A1'], ['rpg_refresh_token', 'R1']]);

  const ctx = {
    API: '', console, setTimeout, clearTimeout, Response,
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
    async fetch(url, opts = {}) {
      const u = String(url);
      const bearer = ((opts.headers || {})['Authorization'] || '').replace('Bearer ', '');
      if (u.includes('/api/auth/refresh')) {
        est.postsRefresh++;
        const t = JSON.parse(opts.body).refresh_token;
        await new Promise(r => setTimeout(r, 40));          // latência da rede
        if (est.usados.has(t)) {
          return new Response(JSON.stringify({ error: 'Invalid Refresh Token: Already Used' }),
                              { status: 401 });
        }
        if (t !== est.refreshVivo) {
          return new Response(JSON.stringify({ error: 'Invalid Refresh Token' }), { status: 401 });
        }
        est.usados.add(t); est.n++;
        est.validos.add('A' + est.n); est.refreshVivo = 'R' + est.n;
        return new Response(
          JSON.stringify({ ok: true, access_token: 'A' + est.n, refresh_token: 'R' + est.n }),
          { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      await new Promise(r => setTimeout(r, 15));
      if (bearer === 'A1') {                                // A1 venceu no servidor
        return new Response(JSON.stringify({ error: 'token is expired' }), { status: 401 });
      }
      if (!est.validos.has(bearer)) {
        return new Response(JSON.stringify({ error: 'invalid' }), { status: 401 });
      }
      return new Response(JSON.stringify({ ok: true, quem: bearer }),
                          { status: 200, headers: { 'Content-Type': 'application/json' } });
    },
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(bloco, ctx);
  return { ctx, est };
}

const resultados = [];
function checar(label, passou, obtido, esperado) {
  resultados.push({ label, passed: passou, got: String(obtido), expected: String(esperado) });
}

async function corrida(n) {
  const { ctx, est } = bancada();
  const rs = await Promise.all(
    Array.from({ length: n }, (_, i) => ctx.authFetch(`/api/x${i}`)));
  const status = rs.map(r => r.status);
  checar(`${n} chamadas simultâneas gastam 1 refresh token`,
         est.postsRefresh === 1, `${est.postsRefresh} POSTs`, '1 POST');
  checar(`${n} chamadas simultâneas terminam todas em 200`,
         status.every(s => s === 200), status.join(','), Array(n).fill(200).join(','));
  checar(`${n} chamadas simultâneas não deslogam o jogador`,
         !est.deslogou, est.deslogou ? 'deslogou' : 'seguiu logado', 'seguiu logado');
}

async function sessaoMorta() {
  const { ctx, est } = bancada();
  est.refreshVivo = 'OUTRO';                 // R1 não vale mais nada
  const r = await ctx.authFetch('/api/x');
  checar('sessão realmente expirada devolve 401', r.status === 401, r.status, 401);
  checar('sessão realmente expirada desloga', est.deslogou,
         est.deslogou ? 'deslogou' : 'seguiu logado', 'deslogou');
}

async function tokenTrocadoNoMeio() {
  const { ctx, est } = bancada();
  const p = ctx.authFetch('/api/lenta');               // sai com A1, que já venceu
  await new Promise(r => setTimeout(r, 5));
  ctx.localStorage.setItem('rpg_access_token', 'A9');  // outra chamada renovou
  est.validos.add('A9');
  const r = await p;
  checar('quem perde a corrida repete com o token novo, sem renovar de novo',
         r.status === 200 && est.postsRefresh === 0,
         `status ${r.status}, ${est.postsRefresh} POSTs`, 'status 200, 0 POSTs');
}

await corrida(2);
await corrida(5);
await corrida(12);
await sessaoMorta();
await tokenTrocadoNoMeio();

const arg = process.argv.find(a => a.startsWith('--json='));
if (arg) fs.writeFileSync(arg.slice(7), JSON.stringify(resultados), 'utf8');

let falhou = 0;
for (const r of resultados) {
  if (!r.passed) falhou++;
  console.log(`${r.passed ? 'ok   ' : 'FALHA'}  ${r.label}`
              + (r.passed ? '' : `\n        obtido:   ${r.got}\n        esperado: ${r.expected}`));
}
console.log(`\n${resultados.length - falhou}/${resultados.length} passaram`);
process.exit(falhou ? 1 : 0);
