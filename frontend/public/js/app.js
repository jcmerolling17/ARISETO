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
import { mountYieldPage } from './pages/yield.js';
import { mountChatbotPage } from './pages/chatbot.js';
import { mountFarmReportPage } from './pages/farm-report.js';
import { mountAdminPages } from './pages/admin.js';
import { ADMIN_ROUTES, redirectForRole } from './utils/session.js';
import { loadJSON } from './utils/store.js';
import { mountBottomNavs } from './utils/bottom-nav.js';
import { mountToast } from './utils/toast.js';

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
      welcome: { title: 'Welcome' },
      signup: { title: 'Sign Up' },
      terms: { title: 'Terms and Conditions' },
      privacy: { title: 'Privacy Policy' },
      login: { title: 'Login' },
      setup: { title: 'Set Up Your Farm' },
      'setup-farm': { title: 'Set up your farm' },
      'setup-field': { title: 'Farm Details' },
      'setup-fields': { title: 'Field Setup' },
      'setup-review': { title: 'Review Your Farm' },
      'setup-done': { title: 'Farm Set Up' },
      home: { title: 'Home' },
      calendar: { title: 'Crop Calendar' },
      tasks: { title: 'Manage All Tasks' },
      'task-new': { title: 'New Farm Task' },
      expenses: { title: 'Farm Expenses' },
      'expense-new': { title: 'Add Expense' },
      'harvest-new': { title: 'Harvest Entry' },
      notifications: { title: 'Notifications' },
      profile: { title: 'Profile' },
      'edit-profile': { title: 'Edit Profile' },
      'change-password': { title: 'Change Password' },
      'add-plot': { title: 'Add Plot' },
      weather: { title: 'Weather Tracker' },
      scan: { title: 'Disease Diagnosis Entries' },
      'scan-result': { title: 'Detection Results' },
      yield: { title: 'Yield Estimation' },
      chatbot: { title: 'Chatbot' },
      'farm-report': { title: 'Farm Report' },
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
    router.navigate(route, { replace: true, state: { message, tone: 'error' } });
  });

  // The Admin Portal and its login use the full window width on a desktop.
  const wide = new Set([...ADMIN_ROUTES, 'admin-login']);
  router.onChange((name) => document.body.classList.toggle('is-wide', wide.has(name)));

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
  mountYieldPage(router);
  mountChatbotPage(router);
  mountFarmReportPage(router);
  mountAdminPages(router);
  router.start();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
