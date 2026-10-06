// frontend/public/js/app.js

import { Router } from './router.js';
import { mountAuthPages } from './pages/login.js';

function bootstrap() {
  const router = new Router({
    root: document.getElementById('app'),
    defaultRoute: 'welcome',
    routes: {
      welcome: { title: 'Welcome' },
      register: { title: 'Create an Account' },
      signup: { title: 'Sign Up' },
      login: { title: 'Login' },
    },
  });

  mountAuthPages(router);
  router.start();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
