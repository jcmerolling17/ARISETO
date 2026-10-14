// frontend/public/js/pages/weather.js

import { farms, ApiError } from '../api/client.js';
import { kindFor, SUMMARIES, TIME_ZONE, manilaParts, isDaytime, formatClock, rounded } from '../api/weather.js';
import { loadJSON, saveJSON } from '../utils/store.js';
import { formatTimeAgo } from '../utils/dates.js';

const HOURS_SHOWN = 8; // now + the next 7 three-hour forecast slots (24 hours)
const DAY_MS = 24 * 60 * 60 * 1000;

const MESSAGES = {
  noFarm: 'Set up your farm to see the weather there.',
  noReading: 'No weather reading for your farm yet. Check back soon.',
  loading: 'Loading the weather…',
  offline: 'You are offline. Weather will update when you reconnect.',
  unavailable: 'Weather is unavailable right now.',
  notMember: 'You are no longer a member of this farm, so its weather is hidden.',
};

function formatHour(date) {
  return date.toLocaleTimeString('en-PH', { timeZone: TIME_ZONE, hour: 'numeric' });
}

function degrees(value) {
  return value == null ? '--°' : `${value}°`;
}

function percent(value) {
  return value == null ? '--%' : `${value}%`;
}

/** Condition icon id: daytime readings use the sun icons, night ones the cloud. */
function iconFor(code, date) {
  const kind = kindFor(Number(code));
  if (!isDaytime(date) && (kind === 'clear' || kind === 'partly')) return '#wx-cloudy';
  return `#wx-${kind}`;
}

/** "Tangkalan, Mamburao": the weather is for the barangay center, so the place is named. */
function placeName(farm) {
  if (farm?.barangay_name && farm?.municipality) return `${farm.barangay_name}, ${farm.municipality}`;
  return farm?.farm_name ?? '';
}

export function mountWeatherPage(router) {
  const view = document.querySelector('[data-view="weather"]');
  const content = view.querySelector('[data-content]');
  const empty = view.querySelector('[data-empty]');
  const tpl = (name) => view.querySelector(`template[data-${name}-tpl]`).content.firstElementChild;
  const field = (name) => view.querySelector(`[data-${name}]`);
  let requestId = 0;

  function showMessage(message) {
    content.hidden = true;
    empty.hidden = false;
    field('empty-text').textContent = message;
  }

  // current has no forecast_for (Section 6), so "Now" is judged day or night by the clock,
  // the same way as Home.
  function renderNow(current) {
    const at = new Date();
    const kind = kindFor(Number(current.condition_code));
    const fetched = new Date(current.fetched_at);
    field('now-icon').setAttribute('href', iconFor(current.condition_code, at));
    field('now-temp').textContent = String(rounded(current.temp_c) ?? '--');
    field('now-summary').textContent = SUMMARIES[kind][isDaytime(at) ? 'day' : 'night'];
    field('now-feels').textContent = degrees(rounded(current.feels_like_c));
    field('now-rain').textContent = percent(rounded(current.precip_probability_pct));
    const wind = rounded(current.wind_speed_mps, 3.6); // m/s to km/h
    field('now-wind').textContent = wind == null ? '-- km/h' : `${wind} km/h`;
    field('updated').textContent = `Updated ${formatTimeAgo(fetched)} · ${formatClock(fetched)}`;
  }

  /** "Now", then the forecast in its 3-hour steps. */
  function renderHours(current, forecast) {
    const slots = [{ ...current, now: true }, ...forecast.slice(0, HOURS_SHOWN - 1)];
    field('hours').replaceChildren(...slots.map((reading) => {
      const item = tpl('hour').cloneNode(true);
      const at = reading.now ? new Date() : new Date(reading.forecast_for);
      const time = reading.now ? 'Now' : formatHour(at);
      const temp = rounded(reading.temp_c);
      const rain = rounded(reading.precip_probability_pct);
      item.classList.toggle('is-now', Boolean(reading.now));
      item.querySelector('[data-temp]').textContent = degrees(temp);
      item.querySelector('[data-icon]').setAttribute('href', iconFor(reading.condition_code, at));
      item.querySelector('[data-rain]').textContent = percent(rain);
      item.querySelector('[data-time]').textContent = time;
      item.setAttribute('aria-label', `${time}: ${temp ?? 'unknown'} degrees, ${rain ?? 'unknown'}% chance of rain`);
      return item;
    }));
  }

  /** Yesterday, Today, and Tomorrow from daily; a day the API left out shows a dash. */
  function renderDays(daily) {
    const byDate = new Map(daily.map((day) => [day.date, day]));
    const now = Date.now();
    const days = [['Yesterday', -1], ['Today', 0], ['Tomorrow', 1]];

    field('days').replaceChildren(...days.map(([name, offset]) => {
      const day = byDate.get(manilaParts(new Date(now + offset * DAY_MS)).day);
      const item = tpl('day').cloneNode(true);
      const range = day ? `${rounded(day.temp_min_c)}° – ${rounded(day.temp_max_c)}°` : '—';
      item.querySelector('[data-name]').textContent = name;
      item.querySelector('[data-range]').textContent = range;
      item.setAttribute('aria-label', day
        ? `${name}: ${rounded(day.temp_min_c)} to ${rounded(day.temp_max_c)} degrees`
        : `${name}: no readings`);
      return item;
    }));
  }

  /** Farms saved on this phone before GET /farms named the barangay get the name once. */
  async function fillPlace(farm, id) {
    if (farm.barangay_name && farm.municipality) return;
    try {
      const match = (await farms.list())?.find((f) => f.farm_id === farm.farm_id);
      if (!match || id !== requestId) return;
      const updated = { ...farm, barangay_name: match.barangay_name, municipality: match.municipality };
      saveJSON('farm', updated);
      field('place').textContent = placeName(updated);
    } catch {
      /* keep the farm name */
    }
  }

  async function render() {
    const id = (requestId += 1);
    const farm = loadJSON('farm');
    const today = new Date();
    field('place').textContent = placeName(farm);
    field('place-sub').textContent = `Occidental Mindoro · ${today.toLocaleDateString('en-PH', {
      timeZone: TIME_ZONE, weekday: 'short', month: 'short', day: 'numeric',
    })}`;
    field('today-date').textContent = today.toLocaleDateString('en-PH', { timeZone: TIME_ZONE, month: 'long', day: 'numeric' });

    if (farm?.farm_id == null) {
      showMessage(MESSAGES.noFarm);
      return;
    }
    fillPlace(farm, id);
    showMessage(MESSAGES.loading);
    try {
      const weather = await farms.weather(farm.farm_id);
      if (id !== requestId) return;
      if (!weather?.current) {
        showMessage(MESSAGES.noReading);
        return;
      }
      content.hidden = false;
      empty.hidden = true;
      renderNow(weather.current);
      renderHours(weather.current, weather.forecast ?? []);
      renderDays(weather.daily ?? []);
    } catch (err) {
      if (id !== requestId) return;
      if (navigator.onLine === false) showMessage(MESSAGES.offline);
      else if (err instanceof ApiError && err.code === 'not_farm_member') showMessage(MESSAGES.notMember);
      else showMessage(MESSAGES.unavailable);
    }
  }

  window.addEventListener('online', () => {
    if (!view.hidden) render();
  });

  router.route('weather', { onEnter: render });
}
