// frontend/public/js/pages/weather.js

import { sampleWeather, emptyWeather } from '../data/sample-weather.js';
import { kindFor, SUMMARIES } from '../api/weather.js';
import { pickDemo } from '../utils/demo.js';
import { formatTimeAgo } from '../utils/dates.js';

const TIME_ZONE = 'Asia/Manila'; // weather times are stored in UTC and shown in Philippine time
const HOURS_SHOWN = 8; // now + the next 7 three-hour slots (24 hours)

/** A day with any rain or storm is summarized as that; otherwise by its most common sky. */
const WET_KINDS = ['storm', 'rain'];
const LABELS = { clear: 'Sunny', partly: 'Partly cloudy', cloudy: 'Cloudy', fog: 'Hazy', rain: 'Rain', storm: 'Thunderstorms' };

function manilaParts(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-PH', {
    timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit', hour: 'numeric', hourCycle: 'h23',
  }).formatToParts(date).map((p) => [p.type, p.value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) };
}

function isDaytime(date) {
  const { hour } = manilaParts(date);
  return hour >= 6 && hour < 18;
}

function formatHour(date) {
  return date.toLocaleTimeString('en-PH', { timeZone: TIME_ZONE, hour: 'numeric' });
}

function formatClock(date) {
  return date.toLocaleTimeString('en-PH', { timeZone: TIME_ZONE, hour: 'numeric', minute: '2-digit' });
}

/** Condition icon id: daytime readings use the sun icons, night ones the cloud. */
function iconFor(code, date) {
  const kind = kindFor(Number(code));
  if (!isDaytime(date) && (kind === 'clear' || kind === 'partly')) return '#wx-cloudy';
  return `#wx-${kind}`;
}

function dayKind(readings) {
  const kinds = readings.map((r) => kindFor(Number(r.condition_code)));
  const wet = WET_KINDS.find((kind) => kinds.includes(kind));
  if (wet) return wet;
  const counts = new Map();
  for (const kind of kinds) counts.set(kind, (counts.get(kind) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'cloudy';
}

export function mountWeatherPage(router) {
  const view = document.querySelector('[data-view="weather"]');
  const content = view.querySelector('[data-content]');
  const empty = view.querySelector('[data-empty]');
  const tpl = (name) => view.querySelector(`template[data-${name}-tpl]`).content.firstElementChild;
  const field = (name) => view.querySelector(`[data-${name}]`);

  function renderNow(current) {
    const at = new Date(current.forecast_for);
    const kind = kindFor(Number(current.condition_code));
    const fetched = new Date(current.fetched_at);
    field('now-icon').setAttribute('href', iconFor(current.condition_code, at));
    field('now-temp').textContent = String(Math.round(current.temp_c));
    field('now-summary').textContent = SUMMARIES[kind][isDaytime(at) ? 'day' : 'night'];
    field('now-feels').textContent = `${Math.round(current.feels_like_c)}°`;
    field('now-rain').textContent = `${current.precip_probability_pct}%`;
    field('now-wind').textContent = `${Math.round(current.wind_speed_mps * 3.6)} km/h`;
    field('updated').textContent = `Updated ${formatTimeAgo(fetched)} · ${formatClock(fetched)}`;
  }

  function renderHours(current, forecast) {
    const slots = [{ ...current, now: true }, ...forecast.slice(0, HOURS_SHOWN - 1)];
    field('hours').replaceChildren(...slots.map((reading) => {
      const item = tpl('hour').cloneNode(true);
      const at = new Date(reading.forecast_for);
      item.classList.toggle('is-now', Boolean(reading.now));
      item.querySelector('[data-temp]').textContent = `${Math.round(reading.temp_c)}°`;
      item.querySelector('[data-icon]').setAttribute('href', iconFor(reading.condition_code, at));
      item.querySelector('[data-rain]').textContent = `${reading.precip_probability_pct}%`;
      item.querySelector('[data-time]').textContent = reading.now ? 'Now' : formatHour(at);
      item.setAttribute('aria-label', `${reading.now ? 'Now' : formatHour(at)}: ${Math.round(reading.temp_c)} degrees, ${reading.precip_probability_pct}% chance of rain`);
      return item;
    }));
  }

  function renderDays(readings) {
    const today = manilaParts(new Date()).day;
    const dayKey = (offset) => manilaParts(new Date(Date.now() + offset * 24 * 60 * 60 * 1000)).day;
    const days = [['Yesterday', dayKey(-1)], ['Today', today], ['Tomorrow', dayKey(1)]];

    field('days').replaceChildren(...days.map(([name, key]) => {
      const rows = readings.filter((r) => manilaParts(new Date(r.forecast_for)).day === key);
      const item = tpl('day').cloneNode(true);
      item.querySelector('[data-name]').textContent = name;
      if (!rows.length) {
        item.querySelector('[data-label]').textContent = 'No data';
        item.querySelector('[data-range]').textContent = '—';
        item.querySelector('[data-icon]').closest('svg').hidden = true;
        return item;
      }
      const daytime = rows.filter((r) => isDaytime(new Date(r.forecast_for)));
      const kind = dayKind(daytime.length ? daytime : rows);
      const temps = rows.map((r) => r.temp_c);
      item.querySelector('[data-icon]').setAttribute('href', `#wx-${kind}`);
      item.querySelector('[data-label]').textContent = LABELS[kind];
      item.querySelector('[data-range]').textContent = `${Math.round(Math.min(...temps))}° – ${Math.round(Math.max(...temps))}°`;
      return item;
    }));
  }

  function render() {
    const weather = pickDemo(sampleWeather, emptyWeather);
    const { location } = weather;
    field('place').textContent = `${location.barangay_name}, ${location.municipality}`;
    field('place-sub').textContent = `${location.province} · ${new Date().toLocaleDateString('en-PH', {
      timeZone: TIME_ZONE, weekday: 'short', month: 'short', day: 'numeric',
    })}`;
    field('today-date').textContent = new Date().toLocaleDateString('en-PH', { timeZone: TIME_ZONE, month: 'long', day: 'numeric' });

    content.hidden = !weather.current;
    empty.hidden = Boolean(weather.current);
    if (!weather.current) return;

    renderNow(weather.current);
    renderHours(weather.current, weather.forecast);
    renderDays([...weather.history, ...weather.forecast]);
  }

  router.route('weather', { onEnter: render });
}
