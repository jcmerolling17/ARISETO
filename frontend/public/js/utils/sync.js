// frontend/public/js/utils/sync.js

/**
 * Sends the offline queue (Phase 14), oldest first, when the phone is online again, when the
 * app opens, and when Background Sync wakes an open app window. client_uuid makes a resent
 * expense or custom task safe, and a resent task update sets the same values again.
 * - Success: the item leaves the queue.
 * - 401, or 403 account_deactivated: the session ended; the queue is kept until the member
 *   logs in again.
 * - Any other 4xx (e.g. 404, 409 cycle_closed): the item is dropped and named in a message.
 * - 5xx or no answer: the queue is kept and sent again later.
 */
import { ApiError, currentUserId, request } from '../api/client.js';
import { dropOtherAnswers, notifyQueueChanged, queuedItems, removeQueued } from './offline-store.js';
import { showToast } from './toast.js';

const LONG_TOAST_MS = 7000;

const MESSAGES = {
  synced: (n) => `${n} offline change(s) synced.`,
  refused: (n, names) => `${n} offline change(s) couldn't be saved. ${names}`,
};

let running = null;

function keepsQueue(err) {
  if (!(err instanceof ApiError) || err.network || err.status >= 500) return true;
  return err.status === 401 || (err.status === 403 && err.code === 'account_deactivated');
}

function report(synced, refusedLabels) {
  const parts = [];
  if (synced) parts.push(MESSAGES.synced(synced));
  if (refusedLabels.length) parts.push(MESSAGES.refused(refusedLabels.length, refusedLabels.join(', ')));
  if (!parts.length) return;
  showToast(parts.join(' '), refusedLabels.length ? LONG_TOAST_MS : undefined);
  window.dispatchEvent(new CustomEvent('ariseto:synced'));
}

async function run() {
  if (navigator.onLine === false) return;
  const userId = currentUserId();
  if (!userId) return;
  const items = (await queuedItems()).filter((item) => item.userId === userId);
  if (!items.length) return;

  let synced = 0;
  const refused = [];
  for (const item of items) {
    try {
      await request(item.path, { method: item.method, body: item.body });
      await removeQueued(item.id);
      synced += 1;
    } catch (err) {
      if (keepsQueue(err)) break;
      await removeQueued(item.id);
      refused.push(item.label);
    }
  }
  notifyQueueChanged();
  report(synced, refused);
}

/** Sends the signed-in account's queue; a second call while one runs waits for it. */
export function syncQueue() {
  running ??= run()
    .catch(() => { /* storage unavailable: nothing to send */ })
    .finally(() => { running = null; });
  return running;
}

/**
 * After a login: changes another account left in the queue are dropped (and named), and that
 * account's saved answers are removed, so one phone never mixes two members' data.
 */
export async function dropOtherAccounts() {
  const userId = currentUserId();
  if (!userId) return;
  const others = (await queuedItems()).filter((item) => item.userId !== userId);
  for (const item of others) await removeQueued(item.id);
  await dropOtherAnswers(userId);
  if (others.length) {
    notifyQueueChanged();
    report(0, others.map((item) => item.label));
  }
}

/** Queued items of the signed-in account, oldest first (for "Waiting to sync"). */
export async function myQueuedItems() {
  const userId = currentUserId();
  if (!userId) return [];
  return (await queuedItems()).filter((item) => item.userId === userId);
}
