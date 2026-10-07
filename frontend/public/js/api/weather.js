// frontend/public/js/api/weather.js

import { farms } from './client.js';

/**
 * Maps an OpenWeatherMap condition ID (WEATHER_LOG.condition_code) to an illustration kind.
 * https://openweathermap.org/weather-conditions
 */
function kindFor(code) {
  if (code >= 200 && code < 300) return 'storm';
  if ((code >= 300 && code < 400) || (code >= 500 && code < 600)) return 'rain';
  if (code >= 700 && code < 800) return 'fog';
  if (code === 800) return 'clear';
  if (code === 801 || code === 802) return 'partly';
  return 'cloudy';
}

const SUMMARIES = {
  clear: { day: 'Today is a sunny day!', night: 'Clear skies tonight.' },
  partly: { day: 'Today is a partly sunny day!', night: 'Partly cloudy tonight.' },
  cloudy: { day: 'Today is a cloudy day.', night: 'Cloudy tonight.' },
  fog: { day: 'It is hazy or foggy today.', night: 'Hazy or foggy tonight.' },
  rain: { day: 'Expect rain today.', night: 'Expect rain tonight.' },
  storm: { day: 'Thunderstorms expected. Stay safe!', night: 'Thunderstorms tonight. Stay safe!' },
};

function isDaytime(date) {
  const hour = date.getHours();
  return hour >= 6 && hour < 18;
}

/**
 * Latest weather for a farm from GET /farms/{farm_id}/weather (WEATHER_LOG, refreshed by the scheduler).
 * Resolves to { temp, feelsLike, rainChance, wind, kind, summary, isDay, fetchedAt };
 * feelsLike is OpenWeatherMap's feels_like_c, wind is converted from m/s to km/h.
 */
export async function getFarmWeather(farmId) {
  const data = await farms.weather(farmId);
  const reading = data?.current ?? data;
  if (!reading || reading.temp_c == null) throw new Error('No weather reading yet.');

  const tempC = Number(reading.temp_c);
  const kind = kindFor(Number(reading.condition_code));
  const isDay = isDaytime(new Date());
  const fetchedAt = reading.fetched_at ? new Date(reading.fetched_at) : null;

  return {
    temp: Math.round(tempC),
    feelsLike: reading.feels_like_c == null ? null : Math.round(Number(reading.feels_like_c)),
    rainChance: reading.precip_probability_pct == null ? null : Math.round(Number(reading.precip_probability_pct)),
    wind: reading.wind_speed_mps == null ? null : Math.round(Number(reading.wind_speed_mps) * 3.6),
    kind,
    isDay,
    summary: SUMMARIES[kind][isDay ? 'day' : 'night'],
    fetchedAt: fetchedAt && !Number.isNaN(fetchedAt.getTime()) ? fetchedAt : null,
  };
}
