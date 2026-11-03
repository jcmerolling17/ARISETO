// frontend/public/js/pages/dashboard.js

import { getFarmWeather, formatClock } from '../api/weather.js';
import { ApiError, notifications } from '../api/client.js';
import { loadJSON } from '../utils/store.js';

const WEATHER_MESSAGES = {
  noFarm: 'Set up your farm to see the weather there.',
  noReading: 'No weather reading for your farm yet. Check back soon.',
  offline: 'You are offline. Weather will update when you reconnect.',
  unavailable: 'Weather is unavailable right now.',
  notMember: 'You are no longer a member of this farm, so its weather is hidden.',
};

function mountWeather(view) {
  const box = view.querySelector('[data-weather]');
  const art = box.querySelector('.weather__art');
  const field = (name) => box.querySelector(`[data-w="${name}"]`);
  let requestId = 0;

  function showMessage(message, state) {
    field('temp').textContent = '--';
    field('feels').textContent = '--°';
    field('humidity').textContent = '--%';
    field('rain').textContent = '--%';
    field('wind').textContent = '-- km/h';
    field('summary').textContent = message;
    box.dataset.state = state;
  }

  async function refresh() {
    const farm = loadJSON('farm');
    const id = (requestId += 1);
    field('place').textContent = farm?.farm_name
      ? [farm.farm_name, farm.municipality].filter(Boolean).join(' · ')
      : '';

    if (farm?.farm_id == null) {
      showMessage(WEATHER_MESSAGES.noFarm, 'empty');
      return;
    }

    box.dataset.state = 'loading';
    try {
      const w = await getFarmWeather(farm.farm_id);
      if (id !== requestId) return;
      art.dataset.kind = w.kind;
      art.dataset.daytime = w.isDay ? 'day' : 'night';
      field('temp').textContent = String(w.temp);
      field('summary').textContent = w.summary;
      field('feels').textContent = w.feelsLike == null ? '--°' : `${w.feelsLike}°`;
      field('humidity').textContent = w.humidity == null ? '--%' : `${w.humidity}%`;
      field('rain').textContent = w.rainChance == null ? '--%' : `${w.rainChance}%`;
      field('wind').textContent = w.wind == null ? '-- km/h' : `${w.wind} km/h`;
      // fetched_at is shown in Philippine time, whatever the phone's time zone.
      if (w.fetchedAt) field('place').textContent += ` · Updated ${formatClock(w.fetchedAt)}`;
      box.dataset.state = 'ready';
    } catch (err) {
      if (id !== requestId) return;
      let message = WEATHER_MESSAGES.unavailable;
      if (navigator.onLine === false) message = WEATHER_MESSAGES.offline;
      else if (err instanceof ApiError && err.code === 'not_farm_member') message = WEATHER_MESSAGES.notMember;
      else if (!(err instanceof ApiError) || err.status === 404) message = WEATHER_MESSAGES.noReading;
      showMessage(message, 'error');
    }
  }

  window.addEventListener('online', () => {
    if (!view.hidden) refresh();
  });

  return { refresh };
}

function renderAvatar(view) {
  const initialEl = view.querySelector('[data-avatar-initial]');
  const iconEl = view.querySelector('.avatar__icon');
  const firstName = loadJSON('user')?.first_name?.trim();
  const initial = firstName ? firstName[0].toUpperCase() : '';
  initialEl.textContent = initial;
  initialEl.hidden = !initial;
  iconEl.style.display = initial ? 'none' : '';
}

/** The bell's unread badge from GET /notifications: a number, "9+" above 9, hidden at 0.
 *  A failed request leaves the badge as it was. */
function mountBell(view) {
  const bell = view.querySelector('[data-bell]');
  const badge = view.querySelector('[data-bell-badge]');
  let requestId = 0;

  function show(unread) {
    badge.textContent = unread > 9 ? '9+' : String(unread);
    badge.hidden = unread === 0;
    bell.setAttribute('aria-label', unread ? `Notifications, ${unread} unread` : 'Notifications');
  }

  return {
    async refresh() {
      const id = ++requestId;
      try {
        const { unread_count: unread } = await notifications.list({ limit: 1 });
        if (id === requestId) show(unread);
      } catch {
        // Offline or signed out: keep the last count; the session handler shows Login.
      }
    },
  };
}

export function mountDashboardPage(router) {
  const view = document.querySelector('[data-view="home"]');
  const weather = mountWeather(view);
  const bell = mountBell(view);

  router.route('home', {
    onEnter() {
      renderAvatar(view);
      bell.refresh();
      weather.refresh();
    },
  });
}
