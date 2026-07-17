const CACHE = 'guha-static-v1';

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(cache) {
      return cache.addAll([
        '/static/css/styles.css?v=56',
        '/static/js/app.js?v=6',
        '/static/images/logo.png'
      ]);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.filter(function(k) { return k !== CACHE; }).map(function(k) { return caches.delete(k); }));
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  var url = new URL(e.request.url);
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(e.request).then(function(r) { return r || fetch(e.request); })
    );
  }
});
