// frontend/public/js/pages/notifications.js

import { sampleNotifications, emptyNotifications } from '../data/sample-notifications.js';
import { pickDemo } from '../utils/demo.js';
import { formatTimeAgo } from '../utils/dates.js';

/** Icon and color for each kind of notification. */
const KINDS = {
  weather_alert: { icon: 'icon-rain', tone: 'blue' },
  task_reminder: { icon: 'icon-calendar', tone: 'orange' },
  yield_estimate: { icon: 'icon-chart', tone: 'teal' },
  diagnosis: { icon: 'icon-scan', tone: 'green' },
  growth_stage: { icon: 'icon-seeds', tone: 'red' },
  account: { icon: 'icon-user', tone: 'gray' },
};

/** "Farm Alerts" are things that need attention on the farm: weather alerts and disease detections. */
const FARM_ALERTS = new Set(['weather_alert', 'diagnosis']);

const EMPTY = {
  all: 'No notifications yet.',
  unread: 'You’re all caught up. No unread notifications.',
  alerts: 'No weather or disease alerts for your farm.',
};

function notifications() {
  return pickDemo(sampleNotifications, emptyNotifications).notifications;
}

export function unreadCount() {
  return notifications().filter((n) => !n.is_read).length;
}

export function mountNotificationsPage(router) {
  const view = document.querySelector('[data-view="notifications"]');
  const list = view.querySelector('[data-notice-list]');
  const empty = view.querySelector('[data-empty]');
  const tabs = view.querySelectorAll('[data-tab]');
  const tpl = view.querySelector('template[data-notice-tpl]').content.firstElementChild;
  let tab = 'all';

  function render(focusId) {
    const all = [...notifications()].sort((a, b) => b.issued_at.localeCompare(a.issued_at));
    const inTab = (n) => {
      if (tab === 'unread') return !n.is_read;
      if (tab === 'alerts') return FARM_ALERTS.has(n.type);
      return true;
    };
    const shown = all.filter(inTab);
    const unread = all.filter((n) => !n.is_read).length;

    tabs.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.tab === tab)));
    view.querySelector('[data-unread-count]').textContent = unread ? `(${unread})` : '';

    list.replaceChildren(...shown.map((n) => {
      const item = tpl.cloneNode(true);
      const button = item.querySelector('[data-notice]');
      const kind = KINDS[n.type] ?? KINDS.account;
      const issued = new Date(n.issued_at);
      item.querySelector('[data-icon]').setAttribute('href', `#${kind.icon}`);
      item.querySelector('[data-icon-box]').dataset.tone = kind.tone;
      item.querySelector('[data-title]').textContent = n.title;
      item.querySelector('[data-message]').textContent = n.message;
      item.querySelector('[data-time]').textContent = formatTimeAgo(issued);
      item.querySelector('[data-time]').title = issued.toLocaleString('en-PH');
      item.querySelector('[data-dot]').hidden = n.is_read;
      button.classList.toggle('is-unread', !n.is_read);
      button.dataset.id = String(n.notification_id);
      button.setAttribute('aria-label', `${n.is_read ? '' : 'Unread. '}${n.title}. ${n.message} ${formatTimeAgo(issued)}`);
      button.addEventListener('click', () => {
        n.is_read = true;
        render(n.notification_id);
      });
      return item;
    }));

    empty.hidden = shown.length > 0;
    view.querySelector('[data-empty-text]').textContent = EMPTY[tab];
    // Keep focus on the tapped item; on the Unread tab it disappears, so focus the list's next item.
    if (focusId != null) {
      const target = list.querySelector(`[data-id="${focusId}"]`) ?? list.querySelector('[data-notice]') ?? tabs[1];
      target.focus();
    }
  }

  tabs.forEach((button) => button.addEventListener('click', () => {
    tab = button.dataset.tab;
    render();
  }));

  router.route('notifications', {
    onEnter() {
      tab = 'all';
      render();
    },
  });
}
