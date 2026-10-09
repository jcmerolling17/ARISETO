// frontend/public/js/app.js

import { Router } from './router.js';
import { mountAuthPages } from './pages/login.js';
import { mountSetupPages } from './pages/setup.js';
import { mountDashboardPage } from './pages/dashboard.js';
import { mountCalendarPages } from './pages/calendar.js';
import { mountBottomNavs } from './utils/bottom-nav.js';
import { mountToast } from './utils/toast.js';

function bootstrap() {
  const router = new Router({
    root: document.getElementById('app'),
    defaultRoute: 'welcome',
    routes: {
      welcome: { title: 'Welcome' },
      signup: { title: 'Sign Up' },
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
    },
  });

  mountBottomNavs();
  mountToast(router);
  mountAuthPages(router);
  mountSetupPages(router);
  mountDashboardPage(router);
  mountCalendarPages(router);
  router.start();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
