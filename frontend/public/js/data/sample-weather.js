// frontend/public/js/data/sample-weather.js

/**
 * Sample weather for the farm, shaped like GET /farms/{farm_id}/weather (WEATHER_LOG rows):
 * { location, current, forecast } plus `history`, past readings used for the "Yesterday" summary
 * (not in the API contract yet). Readings sit on OpenWeatherMap's 3-hour slots (00:00, 03:00…
 * UTC = 2 AM, 5 AM… in Philippine time) and are rebuilt around the current time.
 *
 * The farm is placed at its barangay center (Tangkalan, Mamburao). Tomorrow from 2 PM to 5 PM
 * has heavy rain (rain_mm ≥ 10 per slot), matching the sample "Heavy Rain Expected" alert.
 */

const HOUR = 60 * 60 * 1000;
const MANILA_OFFSET = 8 * HOUR; // UTC+8, no daylight saving

// Per day, one row per 3-hour slot (2 AM … 11 PM Philippine time):
// [temp_c, feels_like_c, humidity_pct, precip_probability_pct, rain_mm, wind_speed_mps, condition_code]
const DAYS = {
  yesterday: [
    [24, 25, 92, 20, 0, 1.5, 803], [24, 25, 94, 15, 0, 1.4, 803], [27, 28, 84, 20, 0, 2.2, 802], [29, 30, 74, 45, 0.4, 3.0, 500],
    [29, 30, 76, 60, 1.2, 3.4, 500], [27, 28, 84, 40, 0.3, 2.6, 500], [25, 25, 90, 15, 0, 1.8, 803], [25, 25, 92, 10, 0, 1.5, 802],
  ],
  today: [
    [24, 24, 93, 10, 0, 1.4, 802], [24, 24, 94, 10, 0, 1.3, 801], [28, 29, 80, 10, 0, 2.4, 801], [30, 31, 68, 15, 0, 3.2, 802],
    [31, 32, 64, 20, 0, 3.4, 802], [29, 30, 72, 25, 0, 3.0, 803], [26, 26, 86, 20, 0, 2.0, 803], [25, 25, 90, 15, 0, 1.6, 802],
  ],
  tomorrow: [
    [25, 25, 92, 20, 0, 1.6, 803], [24, 24, 94, 25, 0, 1.5, 804], [27, 28, 85, 40, 0, 2.6, 804], [28, 29, 82, 70, 1.5, 3.8, 500],
    [26, 26, 92, 90, 14.2, 5.2, 502], [25, 25, 94, 85, 10.5, 4.8, 502], [24, 24, 95, 60, 2.1, 3.0, 501], [24, 24, 95, 35, 0.4, 2.2, 500],
  ],
  dayAfter: [
    [24, 24, 94, 30, 0.2, 1.8, 500], [23, 23, 95, 25, 0, 1.6, 804], [26, 27, 88, 25, 0, 2.4, 803], [29, 30, 78, 20, 0, 3.0, 802],
    [30, 31, 70, 20, 0, 3.3, 802], [28, 29, 76, 25, 0, 2.8, 803], [25, 25, 88, 15, 0, 1.9, 802], [24, 24, 92, 10, 0, 1.5, 801],
  ],
};

/** UTC time of Philippine midnight `dayOffset` days from today. */
function manilaMidnight(now, dayOffset) {
  const local = new Date(now.getTime() + MANILA_OFFSET);
  return Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate() + dayOffset) - MANILA_OFFSET;
}

function readingsFor(now, dayOffset, rows, fetchedAt) {
  const midnight = manilaMidnight(now, dayOffset);
  return rows.map(([temp, feels, humidity, pop, rain, wind, code], slot) => ({
    forecast_for: new Date(midnight + (2 + slot * 3) * HOUR).toISOString(),
    temp_c: temp,
    feels_like_c: feels,
    humidity_pct: humidity,
    precip_probability_pct: pop,
    rain_mm: rain,
    wind_speed_mps: wind,
    condition_code: code,
    is_forecast: true,
    fetched_at: fetchedAt,
  }));
}

function buildSample(now = new Date()) {
  // The scheduler fetches every 3 hours; the last fetch was 25 minutes ago.
  const fetchedAt = new Date(now.getTime() - 25 * 60 * 1000).toISOString();
  const slots = [
    ...readingsFor(now, -1, DAYS.yesterday, fetchedAt),
    ...readingsFor(now, 0, DAYS.today, fetchedAt),
    ...readingsFor(now, 1, DAYS.tomorrow, fetchedAt),
    ...readingsFor(now, 2, DAYS.dayAfter, fetchedAt),
  ];
  const past = slots.filter((r) => new Date(r.forecast_for) <= now);
  const forecast = slots.filter((r) => new Date(r.forecast_for) > now);
  const latest = past[past.length - 1];

  return {
    location: { barangay_name: 'Tangkalan', municipality: 'Mamburao', province: 'Occidental Mindoro' },
    // Current reading; its chance of rain comes from the nearest forecast slot (OpenWeatherMap's
    // current weather has none), as the data dictionary describes.
    current: {
      ...latest,
      forecast_for: fetchedAt,
      precip_probability_pct: forecast[0].precip_probability_pct,
      is_forecast: false,
    },
    forecast,
    history: past,
  };
}

export const sampleWeather = buildSample();

export const emptyWeather = {
  location: { barangay_name: 'Tangkalan', municipality: 'Mamburao', province: 'Occidental Mindoro' },
  current: null,
  forecast: [],
  history: [],
};
