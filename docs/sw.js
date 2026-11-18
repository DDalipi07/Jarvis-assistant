// Lets Jarvis open instantly and install as an app. Only this site's own files are cached:
// nothing you type, and no AI or Google calls, are ever stored here.
const CACHE = "jarvis-mobile-v1";
const FILES = ["./", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png", "./apple-touch-icon.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(FILES)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (req.mode === "navigate") {
    // Always try for the newest version first; fall back to the saved copy when offline.
    e.respondWith(fetch(req).then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put("./", copy)); return r; })
      .catch(() => caches.match("./")));
    return;
  }
  e.respondWith(caches.match(req).then(hit => hit || fetch(req)));
});
