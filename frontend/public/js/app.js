// frontend/public/js/app.js

import { Router } from './router.js';
import { onSessionEnd } from './api/client.js';
import { mountAuthPages } from './pages/login.js';
import { mountSetupPages } from './pages/setup.js';
import { mountDashboardPage } from './pages/dashboard.js';
import { mountCalendarPages } from './pages/calendar.js';
import { mountExpensePages } from './pages/expenses.js';
import { mountNotificationsPage } from './pages/notifications.js';
import { mountProfilePage } from './pages/profile.js';
import { mountAccountPages } from './pages/account.js';
import { mountLegalPages } from './pages/legal.js';
import { mountWeatherPage } from './pages/weather.js';
import { mountDiseasePages } from './pages/disease.js';
import { mountYieldPage } from './pages/yield.js';
import { mountChatbotPage } from './pages/chatbot.js';
import { mountBottomNavs } from './utils/bottom-nav.js';
import { mountToast } from './utils/toast.js';

function bootstrap() {
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
      notifications: { title: 'Notifications' },
      profile: { title: 'Profile' },
      'edit-profile': { title: 'Edit Profile' },
      'change-password': { title: 'Change Password' },
      'add-plot': { title: 'Add Plot' },
      weather: { title: 'Weather Tracker' },
      scan: { title: 'Disease Detection' },
      'scan-result': { title: 'Detection Results' },
      yield: { title: 'Yield Estimation' },
      chatbot: { title: 'Chatbot' },
    },
  });

  // Any API call that ends the session (token already cleared by the client) lands on Login.
  onSessionEnd((message) => {
    router.navigate('login', { replace: true, state: { message, tone: 'error' } });
  });

  mountBottomNavs();
  mountToast(router);
  mountAuthPages(router);
  mountSetupPages(router);
  mountDashboardPage(router);
  mountCalendarPages(router);
  mountExpensePages(router);
  mountNotificationsPage(router);
  mountProfilePage(router);
  mountAccountPages(router);
  mountLegalPages(router);
  mountWeatherPage(router);
  mountDiseasePages(router);
  mountYieldPage(router);
  mountChatbotPage(router);
  router.start();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
