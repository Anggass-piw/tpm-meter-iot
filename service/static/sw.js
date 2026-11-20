'use strict';

const CACHE_NAME = 'tpm-meter-shell-v1';
const SHELL_URL = '/';
const STATIC_ASSETS = new Set([
  '/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-192-maskable.png',
  '/static/icons/icon-512-maskable.png'
]);

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    try {
      const response = await fetch(SHELL_URL, { cache: 'no-store' });
      if (response.ok && response.headers.get('content-type')?.includes('text/html')) {
        await cache.put(SHELL_URL, response.clone());
      }
    } catch (_) {
      // Do not invent an offline data view if the shell could not be obtained.
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith('tpm-meter-shell-') && name !== CACHE_NAME).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API is always network-only: never store readings, auth headers, tokens, or errors.
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate' && (url.pathname === '/' || url.pathname === '/index.html')) {
    event.respondWith((async () => {
      try {
        const response = await fetch(request, { cache: 'no-store' });
        if (response.ok && response.headers.get('content-type')?.includes('text/html')) {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(SHELL_URL, response.clone());
        }
        return response;
      } catch (_) {
        const cachedShell = await caches.match(SHELL_URL);
        if (cachedShell) return cachedShell;
        return new Response('Dashboard offline. Buka kembali saat koneksi tersedia.', {
          status: 503,
          headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' }
        });
      }
    })());
    return;
  }

  if (STATIC_ASSETS.has(url.pathname)) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(request);
      if (cached) return cached;
      try {
        const response = await fetch(request, { cache: 'no-store' });
        if (response.ok && url.origin === self.location.origin) await cache.put(request, response.clone());
        return response;
      } catch (_) {
        return new Response('', { status: 503, headers: { 'Cache-Control': 'no-store' } });
      }
    })());
  }
});
