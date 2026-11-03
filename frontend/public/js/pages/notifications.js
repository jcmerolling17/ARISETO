// frontend/public/js/pages/notifications.js

/**
 * Notifications (GET /notifications, PATCH /notifications/{id}/read, POST /notifications/read-all).
 * Tabs: All, Unread, and Farm Alerts (weather alerts). Tapping a notification marks it read.
 * The icon colour follows the type; the left edge follows the severity.
 */
import { notifications as api, ApiError } from '../api/client.js';
import { TIME_ZONE } from '../api/weather.js';
import { formatTimeAgo } from '../utils/dates.js';
import { setStatus } from '../utils/form.js';

const PAGE_SIZE = 20;

/** Filters sent for each tab. */
const TABS = {
  all: {},
  unread: { unread_only: true },
  alerts: { type: 'weather_alert' },
};

/** Icon and colour for each notification type (Table 24). */
const KINDS = {
  weather_alert: { icon: 'icon-rain', tone: 'blue' },
  task_reminder: { icon: 'icon-calendar', tone: 'orange' },
  yield_update: { icon: 'icon-chart', tone: 'teal' },
  disease_detected: { icon: 'icon-scan', tone: 'green' },
  growth_stage: { icon: 'icon-seeds', tone: 'red' },
};

/** Weather alerts pick their icon from the rule they came from (the title is the rule name). */
const WEATHER_ICONS = [
  ['Heavy rain', 'icon-rain'],
  ['Heat index', 'icon-thermometer'],
  ['Strong wind', 'icon-wind'],
];

const MESSAGES = {
  empty: {
    all: 'No notifications yet.',
    unread: 'You’re all caught up. No unread notifications.',
    alerts: 'No weather alerts for your farm.',
  },
  loadFailed: 'Notifications could not be loaded. Check your connection and try again.',
  markFailed: 'This notification could not be marked as read. Try again.',
  readAllFailed: 'Notifications could not be marked as read. Try again.',
};

function iconFor(n) {
  if (n.type === 'weather_alert') {
    const match = WEATHER_ICONS.find(([prefix]) => n.title.startsWith(prefix));
    if (match) return match[1];
  }
  return (KINDS[n.type] ?? KINDS.weather_alert).icon;
}

function isSessionEnd(err) {
  return err instanceof ApiError && err.sessionEnded;
}

export function mountNotificationsPage(router) {
  const view = document.querySelector('[data-view="notifications"]');
  const list = view.querySelector('[data-notice-list]');
  const empty = view.querySelector('[data-empty]');
  const tabs = view.querySelectorAll('[data-tab]');
  const readAll = view.querySelector('[data-read-all]');
  const more = view.querySelector('[data-more]');
  const tpl = view.querySelector('template[data-notice-tpl]').content.firstElementChild;

  let tab = 'all';
  let items = [];
  let unreadCount = 0;
  let hasMore = false;
  let loaded = false;
  let requestId = 0;

  function renderItem(n) {
    const item = tpl.cloneNode(true);
    const button = item.querySelector('[data-notice]');
    const kind = KINDS[n.type] ?? KINDS.weather_alert;
    const created = new Date(n.created_at);
    const unread = !n.read_at;
    item.querySelector('[data-icon]').setAttribute('href', `#${iconFor(n)}`);
    item.querySelector('[data-icon-box]').dataset.tone = kind.tone;
    item.querySelector('[data-title]').textContent = n.title;
    item.querySelector('[data-message]').textContent = n.body;
    item.querySelector('[data-time]').textContent = formatTimeAgo(created);
    item.querySelector('[data-time]').title = created.toLocaleString('en-PH', { timeZone: TIME_ZONE });
    item.querySelector('[data-dot]').hidden = !unread;
    button.classList.toggle('is-unread', unread);
    if (n.severity) button.dataset.severity = n.severity;
    button.dataset.id = String(n.notification_id);
    button.setAttribute('aria-label', `${unread ? 'Unread. ' : ''}${n.title}. ${n.body} ${formatTimeAgo(created)}`);
    button.addEventListener('click', () => markRead(n));
    return item;
  }

  function render(focusId) {
    tabs.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.tab === tab)));
    view.querySelector('[data-unread-count]').textContent = unreadCount ? `(${unreadCount})` : '';
    readAll.hidden = unreadCount === 0;
    more.hidden = !hasMore;

    list.replaceChildren(...items.map(renderItem));
    empty.hidden = !loaded || items.length > 0;
    view.querySelector('[data-empty-text]').textContent = MESSAGES.empty[tab];

    // Keep focus on the tapped item; on the Unread tab it disappears, so focus the next one.
    if (focusId != null) {
      const target = list.querySelector(`[data-id="${focusId}"]`) ?? list.querySelector('[data-notice]') ?? tabs[1];
      target.focus();
    }
  }

  async function load({ append = false } = {}) {
    const id = ++requestId;
    setStatus(view, '');
    if (!append) {
      items = [];
      loaded = false;
      hasMore = false;
      render();
    }
    try {
      const page = await api.list({ ...TABS[tab], limit: PAGE_SIZE, offset: append ? items.length : 0 });
      if (id !== requestId) return;
      items = append ? [...items, ...page.items] : page.items;
      unreadCount = page.unread_count;
      hasMore = page.items.length === PAGE_SIZE;
      loaded = true;
      render();
    } catch (err) {
      if (id !== requestId || isSessionEnd(err)) return;
      setStatus(view, MESSAGES.loadFailed, 'error');
    }
  }

  async function markRead(n) {
    if (n.read_at) return;
    setStatus(view, '');
    try {
      const saved = await api.markRead(n.notification_id);
      n.read_at = saved.read_at;
      unreadCount = Math.max(0, unreadCount - 1);
    } catch (err) {
      if (isSessionEnd(err)) return;
      if (!(err instanceof ApiError && err.code === 'notification_not_found')) {
        setStatus(view, MESSAGES.markFailed, 'error');
        return;
      }
      // Gone from the server: drop it from the list.
      items = items.filter((item) => item !== n);
    }
    if (tab === 'unread') items = items.filter((item) => !item.read_at);
    render(n.notification_id);
  }

  readAll.addEventListener('click', async () => {
    readAll.disabled = true;
    setStatus(view, '');
    try {
      await api.markAllRead();
      const now = new Date().toISOString();
      items.forEach((n) => { n.read_at ??= now; });
      unreadCount = 0;
      if (tab === 'unread') {
        items = [];
        hasMore = false;
      }
      render();
      tabs[0].focus();
    } catch (err) {
      if (!isSessionEnd(err)) setStatus(view, MESSAGES.readAllFailed, 'error');
    } finally {
      readAll.disabled = false;
    }
  });

  more.addEventListener('click', () => load({ append: true }));

  tabs.forEach((button) => button.addEventListener('click', () => {
    if (button.dataset.tab === tab) return;
    tab = button.dataset.tab;
    load();
  }));

  router.route('notifications', {
    onEnter() {
      tab = 'all';
      load();
    },
  });
}
