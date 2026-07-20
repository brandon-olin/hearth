/**
 * Hearth service worker — app-shell caching + offline fallback.
 *
 * Privacy invariant: authenticated household data is NEVER written to the cache.
 * Requests to /api/* and /uploads/* go straight to the network and are not stored,
 * so a shared device can't serve one member's data to another from disk.
 *
 * Bump CACHE_VERSION whenever the precached shell changes.
 */

const CACHE_VERSION = "hearth-v2";
const OFFLINE_URL = "/offline";

// Shell resources fetched up-front so the installed app opens instantly.
const PRECACHE_URLS = [
  OFFLINE_URL,
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

/**
 * The offline page is useless without the CSS and JS chunks it references, and
 * those filenames are content-hashed at build time so they can't be listed
 * here. Fetch the page and read its own asset URLs out of the markup instead —
 * that stays correct across every rebuild with no build-step integration.
 */
async function precacheOfflineAssets(cache) {
  const html = await fetch(OFFLINE_URL, { cache: "reload" }).then((r) => r.text());

  const urls = new Set();
  const attrPattern = /(?:href|src)="(\/_next\/[^"]+)"/g;
  let match;
  while ((match = attrPattern.exec(html)) !== null) {
    urls.add(match[1]);
  }

  await Promise.all(
    [...urls].map((url) =>
      cache.add(url).catch(() => {
        /* one missing chunk shouldn't sink the whole install */
      }),
    ),
  );
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      .then(async (cache) => {
        // addAll() is atomic — one 404 would reject the whole install and leave
        // the SW unregistered, so each URL is added independently.
        await Promise.all(
          PRECACHE_URLS.map((url) =>
            cache.add(url).catch(() => {
              /* a missing shell asset must not block activation */
            }),
          ),
        );
        await precacheOfflineAssets(cache).catch(() => {
          /* offline page still renders unstyled if this fails */
        });
      })
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  );
});

/** Requests that must never touch the cache. */
function isPrivate(url) {
  return url.pathname.startsWith("/api/") || url.pathname.startsWith("/uploads/");
}

/** Content-hashed build output — safe to serve cache-first and cache forever. */
function isImmutableAsset(url) {
  return url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/");
}

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Only GETs are cacheable; mutations always go to the network untouched.
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Cross-origin (e.g. the Tauri sidecar API) and private paths bypass the SW.
  if (url.origin !== self.location.origin || isPrivate(url)) return;

  if (isImmutableAsset(url)) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ??
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  // Navigations: network-first so the user sees fresh content when online,
  // falling back to the last-seen copy and finally the offline page.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(async () => {
          const cache = await caches.open(CACHE_VERSION);
          return (
            (await cache.match(request)) ??
            (await cache.match(OFFLINE_URL)) ??
            new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } })
          );
        }),
    );
  }
});
