// frontend/public/js/utils/store.js

/**
 * Small per-device preferences (farm location, first name) kept in localStorage.
 * Every access is guarded: storage can be blocked or unavailable in private mode.
 */
const PREFIX = 'ariseto.';

export function loadJSON(key, fallback = null) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function saveJSON(key, value) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    /* storage unavailable; the value lasts for this page only */
  }
}
