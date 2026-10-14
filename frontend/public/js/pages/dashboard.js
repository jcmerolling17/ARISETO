// frontend/public/js/pages/dashboard.js

import { getFarmWeather } from '../api/weather.js';
import { ApiError } from '../api/client.js';
import { loadJSON } from '../utils/store.js';
import { unreadCount } from './notifications.js';

const WEATHER_MESSAGES = {
  noFarm: 'Set up your farm to see the weather there.',
  noReading: 'No weather reading for your farm yet. Check back soon.',
  offline: 'You are offline. Weather will update when you reconnect.',
  unavailable: 'Weather is unavailable right now.',
  notMember: 'You are no longer a member of this farm, so its weather is hidden.',
};

function formatTime(date) {
  return date.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' });
}

function mountWeather(view) {
  const box = view.querySelector('[data-weather]');
  const art = box.querySelector('.weather__art');
  const field = (name) => box.querySelector(`[data-w="${name}"]`);
  let requestId = 0;

  function showMessage(message, state) {
    field('temp').textContent = '--';
    field('feels').textContent = '--°';
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
      field('rain').textContent = w.rainChance == null ? '--%' : `${w.rainChance}%`;
      field('wind').textContent = w.wind == null ? '-- km/h' : `${w.wind} km/h`;
      if (w.fetchedAt) field('place').textContent += ` · updated ${formatTime(w.fetchedAt)}`;
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

export function mountDashboardPage(router) {
  const view = document.querySelector('[data-view="home"]');
  const weather = mountWeather(view);

  router.route('home', {
    onEnter() {
      renderAvatar(view);
      const unread = unreadCount();
      view.querySelector('[data-bell-dot]').hidden = unread === 0;
      view.querySelector('[data-bell]').setAttribute('aria-label', unread ? `Notifications, ${unread} unread` : 'Notifications');
      weather.refresh();
    },
  });
}
