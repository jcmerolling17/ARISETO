// frontend/public/js/app.js

import { Router } from './router.js';
import { mountAuthPages } from './pages/login.js';
import { mountSetupPages } from './pages/setup.js';
import { mountDashboardPage } from './pages/dashboard.js';

function bootstrap() {
  const router = new Router({
    root: document.getElementById('app'),
    defaultRoute: 'welcome',
    routes: {
      welcome: { title: 'Welcome' },
      register: { title: 'Create an Account' },
      signup: { title: 'Sign Up' },
      login: { title: 'Login' },
      setup: { title: 'Set Up Your Farm' },
      'setup-farm': { title: 'Set up your farm' },
      'setup-cycle': { title: 'Your First Crop' },
      'setup-done': { title: 'Farm Set Up' },
      home: { title: 'Home' },
    },
  });

  mountAuthPages(router);
  mountSetupPages(router);
  mountDashboardPage(router);
  router.start();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
