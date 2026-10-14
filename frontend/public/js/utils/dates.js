// frontend/public/js/utils/dates.js

const DAY_MS = 24 * 60 * 60 * 1000;

/** Local calendar date with the time cleared. */
export function startOfDay(date = new Date()) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

/** 'YYYY-MM-DD' for a local date. */
export function toISODate(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Local date from 'YYYY-MM-DD'; null when invalid. */
export function parseISODate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '');
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

/** 'YYYY-MM-DD' that is `offset` days from today; sample data uses it so dates stay current. */
export function isoDateFromToday(offset) {
  return toISODate(addDays(startOfDay(), offset));
}

/** Whole days from a to b (both local dates). */
export function daysBetween(a, b) {
  return Math.round((startOfDay(b) - startOfDay(a)) / DAY_MS);
}

/** Sunday that starts the week of `date`. */
export function startOfWeek(date) {
  return addDays(startOfDay(date), -date.getDay());
}

export function formatShortDate(date) {
  return date.toLocaleDateString('en-PH', { month: 'short', day: 'numeric' });
}

export function formatNumericDate(date) {
  return date.toLocaleDateString('en-PH', { month: '2-digit', day: '2-digit', year: '2-digit' });
}

/** 'Oct 4 – 10' or 'Sep 28 – Oct 4'. */
export function formatRange(start, end) {
  const sameMonth = start.getMonth() === end.getMonth();
  const endText = sameMonth ? String(end.getDate()) : formatShortDate(end);
  return `${formatShortDate(start)} – ${endText}`;
}

/** 'Just now', '20m ago', '5h ago', '3d ago', '2w ago', or 'Mar 4' for older times. */
export function formatTimeAgo(date, now = new Date()) {
  const minutes = Math.max(0, Math.floor((now - date) / 60000));
  if (minutes < 2) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  if (days < 35) return `${Math.floor(days / 7)}w ago`;
  return formatShortDate(date);
}

/** '7:30 AM' from 'HH:MM'. */
export function formatClock(value) {
  const match = /^(\d{2}):(\d{2})$/.exec(value ?? '');
  if (!match) return '';
  const date = new Date(2000, 0, 1, Number(match[1]), Number(match[2]));
  return date.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' });
}
