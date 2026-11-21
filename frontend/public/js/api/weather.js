// frontend/public/js/api/weather.js

import { farms } from './client.js';
import { t } from '../i18n/i18n.js';

/**
 * Maps an OpenWeatherMap condition ID (WEATHER_LOG.condition_code) to an illustration kind.
 * https://openweathermap.org/weather-conditions
 */
export function kindFor(code) {
  if (code >= 200 && code < 300) return 'storm';
  if ((code >= 300 && code < 400) || (code >= 500 && code < 600)) return 'rain';
  if (code >= 700 && code < 800) return 'fog';
  if (code === 800) return 'clear';
  if (code === 801 || code === 802) return 'partly';
  return 'cloudy';
}

/** Summary line for a weather kind, by day or night: t('weather.summary.<kind>.day|night'). */
export function summaryFor(kind, isDay) {
  return t(`weather.summary.${kind}.${isDay ? 'day' : 'night'}`);
}

/** Weather times are stored in UTC and shown in Philippine time, whatever the phone's zone. */
export const TIME_ZONE = 'Asia/Manila';

/** Hour (0–23) and date key (YYYY-MM-DD) of a moment in Philippine time. */
export function manilaParts(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-PH', {
    timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit', hour: 'numeric', hourCycle: 'h23',
  }).formatToParts(date).map((p) => [p.type, p.value]));
  return { day: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour) };
}

export function isDaytime(date) {
  const { hour } = manilaParts(date);
  return hour >= 6 && hour < 18;
}

/** e.g. "5:20 PM" in Philippine time. */
export function formatClock(date) {
  return date.toLocaleTimeString('en-PH', { timeZone: TIME_ZONE, hour: 'numeric', minute: '2-digit' });
}

/** Rounded number, or null when the API had no value. */
export function rounded(value, factor = 1) {
  return value == null ? null : Math.round(Number(value) * factor);
}

/**
 * Latest weather for a farm from GET /farms/{farm_id}/weather (WEATHER_LOG, refreshed by the scheduler).
 * Resolves to { temp, feelsLike, humidity, rainChance, wind, kind, summary, isDay, fetchedAt };
 * feelsLike is OpenWeatherMap's feels_like_c, wind is converted from m/s to km/h.
 */
export async function getFarmWeather(farmId) {
  const data = await farms.weather(farmId);
  const reading = data?.current ?? data;
  if (!reading || reading.temp_c == null) throw new Error('No weather reading yet.');

  const kind = kindFor(Number(reading.condition_code));
  const isDay = isDaytime(new Date());
  const fetchedAt = reading.fetched_at ? new Date(reading.fetched_at) : null;

  return {
    temp: rounded(reading.temp_c),
    feelsLike: rounded(reading.feels_like_c),
    humidity: rounded(reading.humidity_pct),
    rainChance: rounded(reading.precip_probability_pct),
    wind: rounded(reading.wind_speed_mps, 3.6),
    kind,
    isDay,
    summary: summaryFor(kind, isDay),
    fetchedAt: fetchedAt && !Number.isNaN(fetchedAt.getTime()) ? fetchedAt : null,
  };
}
