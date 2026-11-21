// frontend/public/sw.js

/**
 * ARISETO service worker (Phase 14): caches the app's own files so every screen opens
 * without internet. API calls (/api/) are never touched here; the app keeps its own saved
 * answers and offline queue in IndexedDB (js/utils/offline-store.js).
 *
 * Raise VERSION whenever any file in SHELL changes (or a file is added or removed): the
 * phone then downloads the new files into a new cache, the app offers "Reload", and the
 * old cache is deleted when the new version takes over.
 */
const VERSION = 6;
const SHELL_CACHE = `ariseto-shell-v${VERSION}`;
const FONT_CACHE = 'ariseto-fonts';
const SYNC_TAG = 'ariseto-sync';

const SHELL = [
  './',
  'index.html',
  'manifest.json',
  'css/main.css',
  'css/components.css',
  'css/screens.css',
  'js/app.js',
  'js/i18n/i18n.js',
  'js/i18n/en.js',
  'js/i18n/fil.js',
  'js/router.js',
  'js/api/client.js',
  'js/api/weather.js',
  'js/data/farm-options.js',
  'js/pages/account.js',
  'js/pages/admin.js',
  'js/pages/calendar.js',
  'js/pages/chatbot.js',
  'js/pages/dashboard.js',
  'js/pages/disease.js',
  'js/pages/expenses.js',
  'js/pages/farm-report.js',
  'js/pages/harvest.js',
  'js/pages/legal.js',
  'js/pages/login.js',
  'js/pages/notifications.js',
  'js/pages/profile.js',
  'js/pages/setup.js',
  'js/pages/weather.js',
  'js/utils/barangay-picker.js',
  'js/utils/bottom-nav.js',
  'js/utils/dates.js',
  'js/utils/farm.js',
  'js/utils/form.js',
  'js/utils/offline-store.js',
  'js/utils/offline-ui.js',
  'js/utils/language-switch.js',
  'js/utils/saved-farm.js',
  'js/utils/session.js',
  'js/utils/store.js',
  'js/utils/sync.js',
  'js/utils/toast.js',
  'assets/icons/icon-192.png',
  'assets/icons/icon-512.png',
  'assets/icons/icon-maskable.png',
  'assets/icons/logo-badge.png',
  'assets/icons/logo-horizontal.png',
  'assets/icons/logo-mark.png',
  'assets/icons/logo.png',
  'assets/images/bg-home.jpg',
  'assets/images/bg-setup.jpg',
  'assets/images/bg-welcome.jpg',
];

const FONT_HOSTS = new Set(['fonts.googleapis.com', 'fonts.gstatic.com']);

self.addEventListener('install', (event) => {
  // cache: 'reload' skips the browser's HTTP cache, so a new version never stores stale files.
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL.map((path) => new Request(path, { cache: 'reload' })))),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith('ariseto-shell-') && key !== SHELL_CACHE)
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

// The app's Reload button asks the waiting version to take over.
self.addEventListener('message', (event) => {
  if (event.data?.type === 'skip-waiting') self.skipWaiting();
});

// Background Sync only wakes an open app window: the token stays in the page's storage,
// so the window sends the queue itself. A closed app sends it the next time it opens.
self.addEventListener('sync', (event) => {
  if (event.tag !== SYNC_TAG) return;
  event.waitUntil(
    self.clients
      .matchAll({ type: 'window' })
      .then((windows) => windows.forEach((client) => client.postMessage({ type: 'sync' }))),
  );
});

/** Google Fonts: served from the font cache, refreshed from the network when online. */
async function fontResponse(request) {
  const cache = await caches.open(FONT_CACHE);
  const cached = await cache.match(request);
  const fresh = fetch(request)
    .then((response) => {
      if (response.ok || response.type === 'opaque') cache.put(request, response.clone());
      return response;
    })
    .catch(() => cached);
  return cached ?? fresh;
}

/** The app's own files: from the shell cache first, the network otherwise. */
async function shellResponse(request) {
  const cache = await caches.open(SHELL_CACHE);
  if (request.mode === 'navigate') {
    return (await cache.match('index.html')) ?? fetch(request);
  }
  return (await cache.match(request, { ignoreSearch: true })) ?? fetch(request);
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  if (FONT_HOSTS.has(url.hostname)) {
    event.respondWith(fontResponse(request));
    return;
  }
  if (url.origin !== self.location.origin) return;
  // The API, its docs, and anything outside the app's folder always go to the network.
  const scopePath = new URL(self.registration.scope).pathname;
  if (!url.pathname.startsWith(scopePath)) return;
  const relative = url.pathname.slice(scopePath.length);
  if (relative.startsWith('api/') || relative.startsWith('docs') || relative.startsWith('redoc') || relative === 'openapi.json') return;
  if (request.mode === 'navigate' || SHELL.includes(relative) || relative === '') {
    event.respondWith(shellResponse(request));
  }
});
