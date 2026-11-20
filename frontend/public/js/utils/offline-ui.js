// frontend/public/js/utils/offline-ui.js

/**
 * Offline wording and the "Offline · showing what was loaded {time}." banner (Phase 14),
 * shared by the Crop Calendar and Farm Expenses screens and the screens that need internet.
 */
import { ApiError, offlineSince } from '../api/client.js';

export const OFFLINE_MESSAGES = {
  banner: (time) => `Offline · showing what was loaded ${time}.`,
  waiting: 'Waiting to sync',
  savedOffline: "Saved on this phone. It will sync when you're back online.",
  deleteExpense: 'You need internet to delete this expense.',
  deleteTask: 'You need internet to delete this task.',
  recordHarvest: 'You need internet to record a harvest.',
  renameTask: 'You need internet to rename this task or change its stage.',
  screen: "You're offline. This screen needs internet.",
  queuedTask: "This task is waiting to sync. You can change it once it's saved.",
};

/** 'Nov 20, 1:05 PM' in Philippine time. */
export function formatSavedTime(ms) {
  return new Date(ms).toLocaleString('en-PH', {
    timeZone: 'Asia/Manila',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** True when there is no connection, or a request got no answer at all. */
export function isOffline(err) {
  return navigator.onLine === false || (err instanceof ApiError && err.network);
}

/**
 * Shows the view's offline banner when any of the answers came from the phone, with the
 * time of the oldest one; hides it otherwise.
 */
export function showOfflineBanner(view, ...answers) {
  const banner = view.querySelector('[data-offline-banner]');
  if (!banner) return;
  const times = answers.map(offlineSince).filter((t) => t != null);
  banner.hidden = times.length === 0;
  banner.textContent = times.length ? OFFLINE_MESSAGES.banner(formatSavedTime(Math.min(...times))) : '';
}

export function hideOfflineBanner(view) {
  const banner = view.querySelector('[data-offline-banner]');
  if (banner) banner.hidden = true;
}

/** The "Waiting to sync" tag shown on a queued item. */
export function waitingTag() {
  const tag = document.createElement('span');
  tag.className = 'sync-tag';
  tag.textContent = OFFLINE_MESSAGES.waiting;
  return tag;
}
