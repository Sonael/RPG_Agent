/* RPG Agent — Service Worker
 *
 * Dois objetivos:
 *  1. Cache de assets estáticos (carregamento instantâneo, sem mexer em
 *     auth nem no streaming do /api/chat).
 *  2. Suavizar o cold start do Render (free tier): em vez de a navegação
 *     ficar pendurada 30–60s enquanto o servidor acorda, mostramos
 *     rapidamente a tela "offline.html" (A despertar…), que faz polling e
 *     recarrega sozinha quando o backend responde.
 *
 * Regras:
 *  - Navegações (mode === "navigate"): network-first com TIMEOUT curto.
 *    Servidor quente → página fresca (respeita o no-store do menu).
 *    Servidor frio/sem rede → tela de despertar.
 *  - GET de /static/*: stale-while-revalidate (responde do cache na hora).
 *  - Tudo o resto (/api/*, /healthz, terceiros, métodos não-GET): passa
 *    direto para a rede, sem cache.
 */
const CACHE = "rpg-agent-v2";

// Quanto esperar pela rede numa navegação antes de mostrar a tela de
// despertar. O servidor quente devolve o HTML em <1s; 4.5s evita falsos
// positivos sem deixar o utilizador preso.
const NAV_TIMEOUT_MS = 4500;

// "Casco" pré-cacheado (gravado quando o servidor está quente). Os dados
// continuam a precisar de rede.
const PRECACHE = [
  "/offline.html",
  "/static/css/style.css",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// fetch com timeout: rejeita se a rede não responder a tempo.
function fetchWithTimeout(req, ms) {
  return new Promise((resolve, reject) => {
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      ctrl.abort();
      reject(new Error("timeout"));
    }, ms);
    fetch(req, { signal: ctrl.signal }).then(
      (res) => { clearTimeout(t); resolve(res); },
      (err) => { clearTimeout(t); reject(err); }
    );
  });
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  // 1) Navegações de página → network-first com timeout → tela de despertar.
  if (req.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          // Servidor quente devolve o HTML fresco (respeita o no-store do
          // menu — não guardamos cópia da página).
          return await fetchWithTimeout(req, NAV_TIMEOUT_MS);
        } catch (_) {
          // Servidor a dormir ou sem rede: mostra a tela de despertar.
          // A própria página recarrega a URL original quando o backend acordar.
          const waking = await caches.match("/offline.html");
          if (waking) return waking;
          // Sem tela em cache (1.º acesso de sempre): tenta a rede sem timeout.
          return fetch(req);
        }
      })()
    );
    return;
  }

  const url = new URL(req.url);

  // 2) Assets estáticos do mesmo domínio → stale-while-revalidate.
  const isStatic =
    url.origin === self.location.origin && url.pathname.startsWith("/static/");
  if (isStatic) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        const network = fetch(req)
          .then((res) => {
            if (res && res.status === 200) cache.put(req, res.clone());
            return res;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  // 3) Resto (/api/*, /healthz, terceiros): rede direta, sem intervir.
});
