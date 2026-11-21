// frontend/public/js/app.js

import { Router } from './router.js';
import { onSessionEnd } from './api/client.js';
import { mountAuthPages } from './pages/login.js';
import { mountSetupPages } from './pages/setup.js';
import { mountDashboardPage } from './pages/dashboard.js';
import { mountCalendarPages } from './pages/calendar.js';
import { mountExpensePages } from './pages/expenses.js';
import { mountHarvestPage } from './pages/harvest.js';
import { mountNotificationsPage } from './pages/notifications.js';
import { mountProfilePage } from './pages/profile.js';
import { mountAccountPages } from './pages/account.js';
import { mountLegalPages } from './pages/legal.js';
import { mountWeatherPage } from './pages/weather.js';
import { mountDiseasePages } from './pages/disease.js';
import { mountChatbotPage } from './pages/chatbot.js';
import { mountFarmReportPage } from './pages/farm-report.js';
import { mountAdminPages } from './pages/admin.js';
import { ADMIN_ROUTES, redirectForRole } from './utils/session.js';
import { loadJSON } from './utils/store.js';
import { mountBottomNavs } from './utils/bottom-nav.js';
import { mountToast } from './utils/toast.js';
import { applyI18n, t, tEn } from './i18n/i18n.js';
import { mountLanguageSwitches } from './utils/language-switch.js';
import { dropOtherAccounts, syncQueue } from './utils/sync.js';

/**
 * Service worker (Phase 14): caches the app so every screen opens offline. When a new
 * version has downloaded, a bar offers Reload; Reload lets it take over and reloads once.
 * Browsers run service workers only over HTTPS or on localhost.
 */
function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  const bar = document.querySelector('[data-update-bar]');
  let reloading = false;

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!reloading) return;
    window.location.reload();
  });
  // Background Sync wakes an open window to send the offline queue.
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data?.type === 'sync') syncQueue();
  });

  navigator.serviceWorker.register('sw.js').then((registration) => {
    const offerUpdate = (worker) => {
      bar.hidden = false;
      bar.querySelector('[data-update-reload]').onclick = () => {
        reloading = true;
        worker.postMessage({ type: 'skip-waiting' });
      };
    };
    // Only an update gets the bar; the first install simply starts caching.
    if (registration.waiting && navigator.serviceWorker.controller) offerUpdate(registration.waiting);
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing;
      worker?.addEventListener('statechange', () => {
        if (worker.state === 'installed' && navigator.serviceWorker.controller) offerUpdate(worker);
      });
    });
  }).catch(() => { /* not over HTTPS or localhost: the app works online only */ });
}

/** Sends the offline queue now, whenever the phone is online again, and after each login. */
function startOfflineSync() {
  window.addEventListener('online', () => syncQueue());
  window.addEventListener('ariseto:authenticated', async () => {
    await dropOtherAccounts();
    syncQueue();
  });
  syncQueue();
}

/** The route named by the current hash, without the '#/' and any query. */
function hashRoute() {
  return location.hash.startsWith('#/') ? location.hash.slice(2).split('?')[0] : '';
}

/**
 * Role-based routing, also when the app is reopened: an administrator stays in the Admin
 * Portal and a member stays out of it. Runs before the router reads the hash.
 */
function applyRoleRedirect() {
  const redirect = redirectForRole(hashRoute());
  if (redirect) history.replaceState(history.state, '', `#/${redirect}`);
}

function bootstrap() {
  applyRoleRedirect();
  window.addEventListener('hashchange', applyRoleRedirect);

  const router = new Router({
    root: document.getElementById('app'),
    defaultRoute: 'welcome',
    routes: {
      welcome: { get title() { return t('title.welcome'); } },
      signup: { get title() { return t('title.signup'); } },
      terms: { get title() { return t('title.terms'); } },
      privacy: { get title() { return t('title.privacy'); } },
      login: { get title() { return t('title.login'); } },
      setup: { get title() { return t('title.setup'); } },
      'setup-farm': { get title() { return t('title.setup-farm'); } },
      'setup-field': { get title() { return t('title.setup-field'); } },
      'setup-fields': { get title() { return t('title.setup-fields'); } },
      'setup-review': { get title() { return t('title.setup-review'); } },
      'setup-done': { get title() { return t('title.setup-done'); } },
      home: { get title() { return t('title.home'); } },
      calendar: { get title() { return t('title.calendar'); } },
      tasks: { get title() { return t('title.tasks'); } },
      'task-new': { get title() { return t('title.task-new'); } },
      expenses: { get title() { return t('title.expenses'); } },
      'expense-new': { get title() { return t('title.expense-new'); } },
      'harvest-new': { get title() { return t('title.harvest-new'); } },
      notifications: { get title() { return t('title.notifications'); } },
      profile: { get title() { return t('title.profile'); } },
      'edit-profile': { get title() { return t('title.edit-profile'); } },
      'change-password': { get title() { return t('title.change-password'); } },
      'add-plot': { get title() { return t('title.add-plot'); } },
      weather: { get title() { return t('title.weather'); } },
      scan: { get title() { return t('title.scan'); } },
      'scan-result': { get title() { return t('title.scan-result'); } },
      yield: { get title() { return t('title.yield'); } },
      chatbot: { get title() { return t('title.chatbot'); } },
      'farm-report': { get title() { return t('title.farm-report'); } },
      'admin-login': { title: 'Admin Portal' },
      admin: { title: 'Admin Approval List' },
      'admin-report': { title: 'Cooperative Report' },
    },
  });

  // Any API call that ends the session (token already cleared by the client) lands on Login.
  onSessionEnd((message) => {
    // The token is already cleared; the saved role (kept on the device) picks the login.
    const wasAdmin = ADMIN_ROUTES.has(router.current) || loadJSON('user')?.role === 'coop_admin';
    const route = wasAdmin ? 'admin-login' : 'login';
    // message is a strings key; the Admin Portal stays in English.
    const text = wasAdmin ? tEn(message) : t(message);
    router.navigate(route, { replace: true, state: { message: text, tone: 'error' } });
  });

  // The Admin Portal and its login use the full window width on a desktop.
  const wide = new Set([...ADMIN_ROUTES, 'admin-login']);
  router.onChange((name) => document.body.classList.toggle('is-wide', wide.has(name)));

  applyI18n(document);
  mountLanguageSwitches();
  mountBottomNavs();
  mountToast(router);
  mountAuthPages(router);
  mountSetupPages(router);
  mountDashboardPage(router);
  mountCalendarPages(router);
  mountExpensePages(router);
  mountHarvestPage(router);
  mountNotificationsPage(router);
  mountProfilePage(router);
  mountAccountPages(router);
  mountLegalPages(router);
  mountWeatherPage(router);
  mountDiseasePages(router);
  mountChatbotPage(router);
  mountFarmReportPage(router);
  mountAdminPages(router);
  router.start();
  // A new language redraws the screen on show; others pick it up when they open.
  window.addEventListener('ariseto:language', () => router.refresh());
  registerServiceWorker();
  startOfflineSync();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
