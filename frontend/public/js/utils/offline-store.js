// frontend/public/js/utils/offline-store.js

/**
 * The phone's offline data (Phase 14), in IndexedDB:
 * - answers: the last loaded API answer for each GET the Crop Calendar and Farm Expenses
 *   use, per account, kept until a newer answer replaces it or until logout;
 * - queue: changes made offline (adding an expense, adding a custom task, task updates),
 *   sent in order when the phone is online again (js/utils/sync.js).
 * The session token is never stored here. Every call fails soft: without IndexedDB
 * (private mode, blocked storage) nothing is saved and the app works online only.
 */

const DB_NAME = 'ariseto-offline';
const DB_VERSION = 1;
const ANSWERS = 'answers';
const QUEUE = 'queue';

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (!('indexedDB' in globalThis)) {
      reject(new Error('IndexedDB is not available'));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(ANSWERS)) db.createObjectStore(ANSWERS, { keyPath: 'key' });
      if (!db.objectStoreNames.contains(QUEUE)) db.createObjectStore(QUEUE, { keyPath: 'id', autoIncrement: true });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  }).catch((err) => {
    dbPromise = null;
    throw err;
  });
  return dbPromise;
}

/** Runs fn(store) in one transaction and resolves with the value of the request it returns. */
async function withStore(name, mode, fn) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(name, mode);
    const request = fn(tx.objectStore(name));
    let result;
    if (request) request.onsuccess = () => { result = request.result; };
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function answerKey(userId, path) {
  return `${userId}|${path}`;
}

/* ---------- Saved answers ---------- */

export async function saveAnswer(userId, path, data) {
  try {
    await withStore(ANSWERS, 'readwrite', (store) =>
      store.put({ key: answerKey(userId, path), userId, data, savedAt: Date.now() }));
  } catch {
    /* nothing saved; the app still works online */
  }
}

/** { data, savedAt } or null. */
export async function readAnswer(userId, path) {
  try {
    const row = await withStore(ANSWERS, 'readonly', (store) => store.get(answerKey(userId, path)));
    return row ? { data: row.data, savedAt: row.savedAt } : null;
  } catch {
    return null;
  }
}

/** Removes the saved answers of every account except userId (another member logged in). */
export async function dropOtherAnswers(userId) {
  try {
    const rows = await withStore(ANSWERS, 'readonly', (store) => store.getAll());
    const others = (rows ?? []).filter((row) => row.userId !== userId);
    if (!others.length) return;
    await withStore(ANSWERS, 'readwrite', (store) => {
      for (const row of others) store.delete(row.key);
    });
  } catch {
    /* nothing to drop */
  }
}

/* ---------- Offline queue ---------- */

/**
 * item: { userId, kind: 'expense' | 'task' | 'task-update', method, path, body, label,
 *         display } where label names the item in messages and display holds what the
 *         screens need to show it before it syncs. Resolves with the stored item.
 */
export async function enqueue(item) {
  const row = { ...item, createdAt: Date.now() };
  const id = await withStore(QUEUE, 'readwrite', (store) => store.add(row));
  const stored = { ...row, id };
  notifyQueueChanged();
  return stored;
}

/** Every queued item, oldest first. */
export async function queuedItems() {
  try {
    const rows = await withStore(QUEUE, 'readonly', (store) => store.getAll());
    return (rows ?? []).sort((a, b) => a.id - b.id);
  } catch {
    return [];
  }
}

/** Removes one item; the caller announces the change once it is done (see sync.js). */
export async function removeQueued(id) {
  await withStore(QUEUE, 'readwrite', (store) => store.delete(id));
}

/** Logout: the queue and every saved answer are cleared. */
export async function clearOfflineData() {
  try {
    await withStore(QUEUE, 'readwrite', (store) => store.clear());
    await withStore(ANSWERS, 'readwrite', (store) => store.clear());
  } catch {
    /* nothing stored */
  }
  notifyQueueChanged();
}

/** Screens listen for this to show or hide "Waiting to sync" items. */
export function notifyQueueChanged() {
  window.dispatchEvent(new CustomEvent('ariseto:queue-changed'));
}
