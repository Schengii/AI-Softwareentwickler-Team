/**
 * EcoTrack AI - Service Worker
 * Version: v1.0.0
 * Bietet vollständige Offline-Fähigkeit, Asset-Caching und API-Fallback
 */

const CACHE_NAME = 'ecotrack-ai-v1';
const CORE_ASSETS = [
  './',
  'index.html',
  'manifest.json',
  'css/app.css',
  'js/app.js',
  'js/i18n.js',
  'js/api.js',
  'js/charts.js',
  'icons/favicon.svg',
  'icons/icon-192.svg',
  'icons/icon-512.svg',
  'icons/icons.svg'
];

// 1. Install Event: Core-Assets im Cache vorhalten
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      try {
        await cache.addAll(CORE_ASSETS);
      } catch (err) {
        // Fallback: Einzeln adden, falls ein Asset temporär fehlt
        for (const asset of CORE_ASSETS) {
          try {
            await cache.add(asset);
          } catch (singleErr) {
            console.warn(`[SW] Pre-caching failed for ${asset}:`, singleErr);
          }
        }
      }
    }).then(() => self.skipWaiting())
  );
});

// 2. Activate Event: Alte Caches säubern
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 3. Fetch Event: Cache-First für statische Dateien, Network-First mit Cache-Fallback für API
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Nicht-GET Anfragen (POST/PUT/DELETE) können nicht direkt gecacht werden
  if (request.method !== 'GET') {
    event.respondWith(
      fetch(request).catch(async () => {
        // Wenn Offline und POST an /api/v1/*, liefere strukturierte Offline-Antwort
        if (url.pathname.startsWith('/api/v1/')) {
          return new Response(
            JSON.stringify({
              offline: true,
              message: 'Gerät ist offline. Die Berechnung wird lokal im Fallback-Modus simuliert.',
              status: 'offline'
            }),
            {
              status: 200,
              headers: { 'Content-Type': 'application/json' }
            }
          );
        }
        return new Response('Netzwerkfehler: Gerät ist offline', { status: 503 });
      })
    );
    return;
  }

  // API Anfragen: Network-First mit Cache-Fallback
  if (url.pathname.startsWith('/api/v1/')) {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          if (networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return networkResponse;
        })
        .catch(async () => {
          const cachedResponse = await caches.match(request);
          if (cachedResponse) {
            return cachedResponse;
          }
          return new Response(
            JSON.stringify({
              offline: true,
              data: null,
              message: 'Offline-Modus aktiv. Keine Netzwerkverbindung zum EcoTrack Gateway.'
            }),
            {
              status: 200,
              headers: { 'Content-Type': 'application/json' }
            }
          );
        })
    );
    return;
  }

  // Statische Assets: Cache-First mit Network-Fallback und Background Update
  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      if (cachedResponse) {
        // Optional im Hintergrund aktualisieren
        fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            caches.open(CACHE_NAME).then((cache) => cache.put(request, networkResponse));
          }
        }).catch(() => {
          // Offline, Cache bleibt gültig
        });
        return cachedResponse;
      }
      return fetch(request).then((networkResponse) => {
        if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
          return networkResponse;
        }
        const responseToCache = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(request, responseToCache);
        });
        return networkResponse;
      }).catch(async () => {
        // HTML Navigation Fallback
        if (request.headers.get('accept')?.includes('text/html')) {
          const fallback = await caches.match('index.html');
          if (fallback) return fallback;
        }
        return new Response('Offline: Ressource nicht verfügbar', { status: 503 });
      });
    })
  );
});
