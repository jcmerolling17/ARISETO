// frontend/public/js/api/client.js

import { enqueue, queuedItems, readAnswer, saveAnswer } from '../utils/offline-store.js';

const API_BASE = (
  document.querySelector('meta[name="ariseto-api-base"]')?.content || '/api/v1'
).replace(/\/+$/, '');

const TOKEN_KEY = 'ariseto.access_token';
const DEFAULT_TIMEOUT_MS = 15000;

export class ApiError extends Error {
  constructor(message, { status = 0, details = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
    this.code = errorCode(details);
    /** True when this response ended the session; the app is already on its way to Login. */
    this.sessionEnded = false;
    /** True when no answer came back at all (offline, unreachable, or timed out). */
    this.network = false;
  }
}

/** The signed-in account's user_id, read from the token's payload. */
export function currentUserId() {
  const token = tokenStore.get();
  if (!token) return null;
  try {
    const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = part.padEnd(part.length + ((4 - (part.length % 4)) % 4), '=');
    const sub = JSON.parse(atob(padded)).sub;
    return sub == null ? null : String(sub);
  } catch {
    return null;
  }
}

/* ---------- Offline reading and the offline queue (Phase 14) ---------- */

const NOT_LOADED_MESSAGE =
  "You're offline, and this hasn't been opened on this phone yet. Connect once to use it offline.";

// Answers served from the phone instead of the network, mapped to the time they were saved.
const savedAnswerTimes = new WeakMap();

/** When data came from the phone's saved answers, the time it was saved (ms); otherwise null. */
export function offlineSince(data) {
  return data && typeof data === 'object' ? savedAnswerTimes.get(data) ?? null : null;
}

const SYNC_TAG = 'ariseto-sync';

/** Asks the service worker to wake the app when the phone is online again (Background Sync). */
function requestBackgroundSync() {
  navigator.serviceWorker?.ready
    ?.then((registration) => registration.sync?.register(SYNC_TAG))
    .catch(() => { /* not supported: the app sends the queue when it opens or goes online */ });
}

async function enqueueWrite(userId, path, method, body, queue) {
  const item = await enqueue({
    userId,
    kind: queue.kind,
    method,
    path,
    body,
    label: queue.label,
    display: queue.display ?? null,
  });
  requestBackgroundSync();
  return { queued: true, queue_id: item.id };
}

/** Business error code, e.g. 'account_pending', from the API's { "detail": { "code": "<error_code>" } } shape. */
function errorCode(data) {
  if (!data || typeof data !== 'object') return null;
  const detail = data.detail;
  return (detail && typeof detail === 'object' && !Array.isArray(detail) ? detail.code : null)
    ?? data.code
    ?? null;
}

export const tokenStore = {
  get() {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable (private mode / blocked); session lasts for this page only */
    }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing stored */
    }
  },
};

// A protected call answered with one of these ends the session (Section 6): the saved token
// is cleared and the app goes to Login with the message.
const SESSION_END_MESSAGES = {
  '401:not_authenticated': 'Please log in again.',
  '403:account_deactivated': 'Your account has been deactivated. Contact MPMPC.',
};

let sessionEndHandler = null;

/** Registers the one handler for an ended session; app.js uses it to go to Login. */
export function onSessionEnd(handler) {
  sessionEndHandler = handler;
}

function endSession(message, sentToken) {
  // Only the session the request was sent with ends: a newer login keeps its token, and
  // several calls failing together lead to Login once.
  if (tokenStore.get() !== sentToken) return;
  tokenStore.clear();
  sessionEndHandler?.(message);
}

async function parseBody(response) {
  if (response.status === 204) return null;
  const type = response.headers.get('content-type') || '';
  if (type.includes('application/json')) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }
  const text = await response.text();
  return text || null;
}

// FastAPI returns { detail: "..." } for HTTPException and { detail: [{ loc, msg }] } for 422s.
function errorMessage(data, status) {
  const detail = data && typeof data === 'object' ? data.detail ?? data.message : null;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((item) => item?.msg).filter(Boolean).join(' ') || 'Some fields are invalid.';
  }
  if (status >= 500) return 'Something went wrong on our side. Please try again shortly.';
  if (status === 429) return 'Too many attempts. Please wait a moment and try again.';
  return 'Request failed. Please try again.';
}

/**
 * body: a JSON-serializable value, or FormData for a file upload (the browser sets the
 * multipart Content-Type). blob: true returns a successful response as a Blob (e.g. a photo).
 */
/**
 * offline: true saves each successful GET answer on the phone and, when no answer comes back,
 * returns the saved one instead (see offlineSince). queue: { kind, label, display } lets a
 * write wait in the offline queue when the phone is offline, when the request gets no
 * answer, or when earlier changes are still waiting (so changes keep their order). A queued
 * write resolves with { queued: true, queue_id }.
 */
export async function request(path, { offline = false, queue = null, ...options } = {}) {
  const method = (options.method ?? 'GET').toUpperCase();
  const userId = options.auth === false ? null : currentUserId();

  if (queue && userId) {
    const waiting = (await queuedItems()).some((item) => item.userId === userId);
    if (navigator.onLine === false || waiting) {
      return enqueueWrite(userId, path, method, options.body, queue);
    }
  }
  try {
    const data = await send(path, options);
    if (offline && method === 'GET' && userId && data !== null && typeof data === 'object') {
      saveAnswer(userId, path, data);
    }
    return data;
  } catch (err) {
    if (!(err instanceof ApiError) || !err.network) throw err;
    if (offline && method === 'GET' && userId) {
      const saved = await readAnswer(userId, path);
      if (saved) {
        savedAnswerTimes.set(saved.data, saved.savedAt);
        return saved.data;
      }
      const notLoaded = new ApiError(NOT_LOADED_MESSAGE, {
        details: { detail: { code: 'offline_not_loaded' } },
      });
      notLoaded.network = true;
      throw notLoaded;
    }
    if (queue && userId) return enqueueWrite(userId, path, method, options.body, queue);
    throw err;
  }
}

async function send(path, { method = 'GET', body, headers = {}, auth = true, timeout = DEFAULT_TIMEOUT_MS, blob = false } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const token = auth ? tokenStore.get() : null;
  const isForm = body instanceof FormData;

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined && !isForm && { 'Content-Type': 'application/json' }),
        ...(token && { Authorization: `Bearer ${token}` }),
        ...headers,
      },
      body: body === undefined || isForm ? body : JSON.stringify(body),
      credentials: 'same-origin',
      signal: controller.signal,
    });

    if (blob && response.ok) return await response.blob();
    const data = await parseBody(response);
    if (!response.ok) {
      const error = new ApiError(errorMessage(data, response.status), { status: response.status, details: data });
      // Login and sign-up (auth: false) show their own 401/403 messages instead.
      const sessionMessage = auth ? SESSION_END_MESSAGES[`${error.status}:${error.code}`] : undefined;
      if (sessionMessage) {
        error.sessionEnded = true;
        endSession(sessionMessage, token);
      }
      throw error;
    }
    return data;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    let message = 'Unable to reach ARISETO right now. Please try again.';
    if (err.name === 'AbortError') message = 'The server took too long to respond. Please try again.';
    else if (navigator.onLine === false) message = 'You appear to be offline. Check your connection and try again.';
    const failure = new ApiError(message);
    failure.network = true;
    throw failure;
  } finally {
    clearTimeout(timer);
  }
}

export const auth = {
  /**
   * credentials: { mobile_no, password } or { email, password }
   * 200 { access_token, token_type: 'bearer', user: { user_id, first_name, role } }
   * 401 invalid_credentials; 403 account_pending | account_deactivated
   */
  async login(credentials) {
    const data = await request('/auth/login', { method: 'POST', body: credentials, auth: false });
    if (data?.access_token) tokenStore.set(data.access_token);
    return data;
  },

  /**
   * payload: { first_name, last_name, mobile_no, email (optional), password, member_no,
   *            municipality, barangay_id (optional), preferred_language (optional),
   *            accepted_terms (must be true) }
   * 201 { user_id, account_status: 'pending' }: the account awaits coop_admin approval.
   * 409 mobile_taken | email_taken | member_no_taken;
   * 422 barangay_municipality_mismatch | terms_not_accepted
   */
  register(payload) {
    return request('/auth/register', { method: 'POST', body: payload, auth: false });
  },

  logout() {
    tokenStore.clear();
  },

  isAuthenticated() {
    return Boolean(tokenStore.get());
  },
};

export const farms = {
  /**
   * Saves the farm, its fields, each field's first crop cycle, and their calendars in one
   * transaction; the caller becomes the owner. The backend sets the location from the barangay
   * center and the total area from the fields.
   * payload: { farm_name, barangay_id, season: 'wet'|'dry',
   *            fields: [{ field_name, area_ha, variety_id, planting_date: 'YYYY-MM-DD' (sowing) }] }
   * 201 { farm_id, total_area_ha, fields: [{ field_id, cycle_id, expected_harvest_date }] }
   * 422 no_fields | field_name_taken | barangay_not_found | planting_date_out_of_range |
   *     variety_not_found
   */
  create(payload) {
    return request('/farms', { method: 'POST', body: payload });
  },

  /**
   * Farms the caller owns or works on, oldest first ([] before farm setup):
   * 200 [{ farm_id, farm_name, barangay_id, barangay_name, municipality, latitude, longitude,
   *        total_area_ha, role_on_farm }]
   */
  list() {
    return request('/farms', { offline: true });
  },

  /**
   * Adds a field to a farm after setup and opens its first crop cycle (owner only).
   * payload: { field_name, area_ha, variety_id, season: 'wet'|'dry',
   *            planting_date: 'YYYY-MM-DD' (sowing), target_yield_t_ha (optional) }
   * 201 { field_id, cycle_id, expected_harvest_date, total_area_ha }
   * 403 not_farm_owner; 404 farm_not_found; 409 field_name_taken;
   * 422 planting_date_out_of_range | variety_not_found
   */
  addField(farmId, payload) {
    return request(`/farms/${encodeURIComponent(farmId)}/fields`, { method: 'POST', body: payload });
  },

  /**
   * The farm's fields in the order they were added (any member of the farm):
   * 200 [{ field_id, field_name, area_ha,
   *        current_cycle: { cycle_id, crop_name, variety_name, season, planting_date,
   *                         expected_harvest_date, status } or null }]
   * current_cycle is the latest planned or active cycle.
   * 403 not_farm_member (also for a farm that does not exist)
   */
  fields(farmId) {
    return request(`/farms/${encodeURIComponent(farmId)}/fields`, { offline: true });
  },

  /**
   * Weather for the farm, served from WEATHER_LOG (never fetched live per request):
   * 200 { current: { temp_c, feels_like_c, humidity_pct, wind_speed_mps, precip_probability_pct,
   *                  rain_mm, condition_code, fetched_at },
   *       forecast: [...same fields with forecast_for],
   *       daily: [{ date: 'YYYY-MM-DD', temp_min_c, temp_max_c }], alerts: [] }
   * current is null and the lists are empty until the farm's weather has been fetched;
   * daily covers yesterday, today, and tomorrow in Philippine dates, leaving out days
   * without readings.
   * 403 not_farm_member (also for a farm that does not exist)
   */
  weather(farmId) {
    return request(`/farms/${encodeURIComponent(farmId)}/weather`);
  },

  /**
   * The owner's farm report for one season (DFD 7.5); filters: { season, season_year }
   * (sent together; without them, the current season).
   * 200 { farm_name, season, season_year, fields: [{ field_name, crop_name, variety_name,
   *       area_ha, planting_date, status, expenses_php, harvest_kg, gross_income_php,
   *       net_profit_php, actual_yield_t_ha (null before the first harvest),
   *       task_completion_pct, scans: { diseased, healthy, unrecognized }, top_disease }],
   *       totals: { area_ha, expenses_php, whole_farm_expenses_php, harvest_kg,
   *       gross_income_php, net_profit_php } }; the totals match summary().
   * 403 not_farm_owner, not_farm_member; 422 season_incomplete
   */
  report(farmId, filters) {
    return request(`/farms/${encodeURIComponent(farmId)}/report${queryString(filters)}`);
  },
};

/** '?a=1&b=2' from the set (non-null, non-empty) values; '' when there are none. */
function queryString(params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : '';
}

export const expenses = {
  /** 200 [{ category_id, category_name }]: the seven categories in their documented order. */
  categories() {
    return request('/expense-categories', { offline: true });
  },

  /**
   * filters: { season, season_year (sent together; default the current season), field_id }
   * 200 [{ expense_id, category_id, category_name, amount_php, expense_date, description,
   *        quantity, unit, cycle_id, field_name (null for whole farm), season, season_year,
   *        recorded_by_name, can_delete }], newest expense_date first
   * 403 not_farm_member; 422 season_incomplete | field_not_in_farm
   */
  list(farmId, filters) {
    return request(`/farms/${encodeURIComponent(farmId)}/expenses${queryString(filters)}`, { offline: true });
  },

  /**
   * payload: { category_id, amount_php, expense_date, description, cycle_id (left out for a
   *            whole-farm expense, which then needs season and season_year), quantity, unit,
   *            client_uuid }
   * 201 { expense_id, season, season_year }; 200 with the same body when client_uuid was
   * already saved by this member on this farm (a retry)
   * 403 not_farm_member; 409 client_uuid_taken; 422 category_not_found | cycle_not_in_farm |
   * season_required | season_mismatch | unit_required | quantity_required |
   * expense_date_in_future
   * queue: { label, display } lets it wait in the offline queue ({ queued: true } is returned).
   */
  create(farmId, payload, queue = null) {
    return request(`/farms/${encodeURIComponent(farmId)}/expenses`, {
      method: 'POST',
      body: payload,
      queue: queue && { kind: 'expense', ...queue },
    });
  },

  /** 204; allowed for the member who recorded it and the farm owner. 403 not_allowed; 404 expense_not_found */
  remove(expenseId) {
    return request(`/expenses/${encodeURIComponent(expenseId)}`, { method: 'DELETE' });
  },

  /**
   * Same filters as list().
   * 200 { season, season_year, total_expenses_php, whole_farm_expenses_php,
   *       by_category: [{ category_name, amount_php }], gross_income_php, net_profit_php }
   * With field_id, whole-farm expenses are left out.
   */
  summary(farmId, filters) {
    return request(`/farms/${encodeURIComponent(farmId)}/summary${queryString(filters)}`, { offline: true });
  },
};

export const harvests = {
  /**
   * payload: { harvest_date, quantity_kg, unit_price_php, final_harvest (true or false) }
   * 201 { harvest_id, gross_income_php, cycle_status }; a final harvest closes the cycle.
   * 403 not_farm_owner; 404 cycle_not_found; 409 cycle_closed; 422 harvest_date_out_of_range
   */
  record(cycleId, payload) {
    return request(`/cycles/${encodeURIComponent(cycleId)}/harvests`, { method: 'POST', body: payload });
  },

  /** Same filters as expenses.list(); 200 [{ harvest_id, cycle_id, field_name, crop_name, ... }] */
  list(farmId, filters) {
    return request(`/farms/${encodeURIComponent(farmId)}/harvests${queryString(filters)}`, { offline: true });
  },
};

export const activities = {
  /**
   * filters: { status, from, to } (dates YYYY-MM-DD; a task matches when any day of its range
   * falls between them)
   * 200 { cycle: { cycle_id, field_name, crop_name, variety_name, season, planting_date,
   *       expected_harvest_date, status, completion_pct }, items: [activity] }, where an activity
   * is { activity_id, title, description, source_reference, task_type, growth_stage,
   * scheduled_date, end_date, scheduled_time, reminder, notes, status, completed_at,
   * is_weather_sensitive, is_custom }; by date, then time (untimed last)
   * 404 cycle_not_found
   */
  forCycle(cycleId, filters) {
    return request(`/cycles/${encodeURIComponent(cycleId)}/activities${queryString(filters)}`, { offline: true });
  },

  /**
   * filters: { field_id, status, q, from, to, limit (default 50, at most 200), offset }
   * 200 { items: [activity plus cycle_id and field_name] } for each field's current cycle
   * 403 not_farm_member; 422 field_not_in_farm
   */
  forFarm(farmId, filters) {
    return request(`/farms/${encodeURIComponent(farmId)}/activities${queryString(filters)}`, { offline: true });
  },

  /**
   * payload: { title, scheduled_date, scheduled_time, reminder, notes, growth_stage, client_uuid }
   * 201 the custom task; 200 with the same body when client_uuid was already saved on this cycle
   * 404 cycle_not_found; 409 cycle_closed | client_uuid_taken; 422 date_out_of_range
   * queue: { label, display } lets it wait in the offline queue ({ queued: true } is returned).
   */
  create(cycleId, payload, queue = null) {
    return request(`/cycles/${encodeURIComponent(cycleId)}/activities`, {
      method: 'POST',
      body: payload,
      queue: queue && { kind: 'task', ...queue },
    });
  },

  /**
   * payload: any of { status ('pending' | 'done' | 'skipped'), scheduled_date, scheduled_time,
   *   reminder, notes, title and growth_stage (custom tasks only) }
   * 200 the task. A new date or time is a reschedule.
   * 404 activity_not_found; 409 cycle_closed; 422 not_editable | date_out_of_range
   * queue: { label, display } lets it wait in the offline queue ({ queued: true } is returned).
   */
  update(activityId, payload, queue = null) {
    return request(`/activities/${encodeURIComponent(activityId)}`, {
      method: 'PATCH',
      body: payload,
      queue: queue && { kind: 'task-update', ...queue },
    });
  },

  /** 204; custom tasks only. 404 activity_not_found; 409 generated_task | cycle_closed */
  remove(activityId) {
    return request(`/activities/${encodeURIComponent(activityId)}`, { method: 'DELETE' });
  },
};

export const notifications = {
  /**
   * filters: { unread_only (true or false), type (e.g. 'weather_alert'), limit (default 20,
   *            at most 100), offset }
   * 200 { unread_count, items: [{ notification_id, type, title, body, severity, farm_id,
   *       created_at, read_at }] }: the caller's own, newest first. unread_count counts all
   * of the caller's unread notifications, whatever the filters.
   */
  list(filters) {
    return request(`/notifications${queryString(filters)}`);
  },

  /** 200 { notification_id, read_at }; marking again keeps the first read_at. 404 notification_not_found */
  markRead(notificationId) {
    return request(`/notifications/${encodeURIComponent(notificationId)}/read`, { method: 'PATCH' });
  },

  /** 200 { updated }: how many unread notifications were marked read. */
  markAllRead() {
    return request('/notifications/read-all', { method: 'POST' });
  },
};

export const users = {
  /**
   * The signed-in account:
   * 200 { user_id, first_name, last_name, mobile_no, email, member_no, municipality,
   *       barangay_id, barangay_name, preferred_language, role, account_status, created_at,
   *       deletion_requested_at }
   */
  me() {
    return request('/users/me');
  },

  /**
   * changes: any of { first_name, last_name, email (null clears it), mobile_no,
   *                   preferred_language }, plus current_password when mobile_no or email changes.
   * 200 the same body as me()
   * 403 invalid_current_password; 409 mobile_taken | email_taken; 422 current_password_required
   */
  update(changes) {
    return request('/users/me', { method: 'PATCH', body: changes });
  },

  /**
   * body: { current_password, new_password (8 to 128 characters) }
   * 200 { access_token, token_type: 'bearer' }; tokens issued earlier stop working, so the
   * new one is saved at once.
   * 403 invalid_current_password; 422 password_unchanged
   */
  async changePassword(body) {
    const data = await request('/users/me/password', { method: 'POST', body });
    if (data?.access_token) tokenStore.set(data.access_token);
    return data;
  },

  /**
   * Asks a coop_admin to delete the account; asking again keeps the first time.
   * 200 { deletion_requested_at }
   */
  requestDeletion() {
    return request('/users/me/deletion-request', { method: 'POST' });
  },
};

export const crops = {
  /**
   * Crops with their varieties (any logged-in user):
   * 200 [{ crop_id, crop_name, varieties: [{ variety_id, variety_name, maturity_class, maturity_days }] }]
   */
  list() {
    return request('/crops');
  },
};

const SCAN_TIMEOUT_MS = 60000; // a photo upload plus the model run, on a slow connection

export const diagnoses = {
  /**
   * Scans a leaf photo (JPEG or PNG, at most 5 MB, at least 224 x 224 px). Send cycleId (the
   * chosen field's current crop cycle) or cropId when no field is chosen.
   * 201 { diagnosis_id, result_status: 'diseased'|'healthy'|'unrecognized', confidence,
   *       crop_name, disease: { disease_id, disease_name, local_name, pathogen_type, symptoms,
   *       description_en, description_fil, impact_en, impact_fil,
   *       treatments: [{ step_no, treatment_type, instruction_en, instruction_fil,
   *                      source_reference }] } or null, model_version, created_at }
   * 404 cycle_not_found; 413 image_too_large; 415 unsupported_image_type;
   * 422 crop_required | crop_not_found | crop_mismatch | image_too_small | image_unreadable;
   * 503 model_unavailable
   */
  create({ image, cycleId = null, cropId = null }) {
    const form = new FormData();
    form.append('image', image, 'leaf.jpg');
    if (cycleId != null) form.append('cycle_id', String(cycleId));
    if (cropId != null) form.append('crop_id', String(cropId));
    return request('/diagnoses', { method: 'POST', body: form, timeout: SCAN_TIMEOUT_MS });
  },

  /**
   * The caller's own scans, newest first (limit 1 to 100, default 20):
   * 200 [{ diagnosis_id, created_at, crop_name, field_name (null when no field was chosen),
   *        result_status, disease_name, local_name, confidence }]
   */
  list({ limit = 20, offset = 0 } = {}) {
    return request(`/diagnoses${queryString({ limit, offset })}`);
  },

  /** One of the caller's scans, as POST returns it. 404 diagnosis_not_found */
  get(diagnosisId) {
    return request(`/diagnoses/${encodeURIComponent(diagnosisId)}`);
  },

  /** The scan's photo as a Blob, fetched with the token. 404 diagnosis_not_found | image_missing */
  image(diagnosisId) {
    return request(`/diagnoses/${encodeURIComponent(diagnosisId)}/image`, { blob: true });
  },
};

export const diseases = {
  /**
   * The disease knowledge base (any logged-in user; empty until it is imported):
   * 200 [{ disease_id, crop_name, disease_name, local_name, model_class_label, pathogen_type,
   *        treatment_count }]
   * 422 crop_not_found
   */
  list(cropId = null) {
    return request(`/diseases${queryString({ crop_id: cropId })}`);
  },
};

export const chat = {
  /**
   * Asks the chatbot. Leave out sessionId to start a new conversation; farmId is the farm
   * used for the farm-data answers (weather check, today's tasks).
   * 201 { session_id, user_message: { message_id, message_text, created_at },
   *       reply: { message_id, message_text, intent_tag (null for the fallback), confidence,
   *                source_reference, created_at } }
   * 403 not_farm_member; 404 session_not_found; 422 message_empty | message_too_long;
   * 503 model_unavailable
   */
  send({ message, sessionId = null, farmId = null }) {
    const body = { message };
    if (sessionId != null) body.session_id = sessionId;
    if (farmId != null) body.farm_id = farmId;
    return request('/chat/messages', { method: 'POST', body });
  },

  /** The caller's conversations, latest activity first (limit 1 to 50, default 10):
   * 200 [{ session_id, started_at, last_message_at, last_message_text }] */
  sessions({ limit = 10 } = {}) {
    return request(`/chat/sessions${queryString({ limit })}`);
  },

  /**
   * A conversation's messages, oldest first (limit 1 to 200, default 50):
   * 200 [{ message_id, sender: 'user'|'bot', message_text, intent_tag, confidence,
   *        source_reference, created_at }]
   * 404 session_not_found
   */
  messages(sessionId, { limit = 50, offset = 0 } = {}) {
    return request(`/chat/sessions/${encodeURIComponent(sessionId)}/messages${queryString({ limit, offset })}`);
  },
};

export const barangays = {
  /**
   * Barangays of one Occidental Mindoro municipality (public; needed during sign-up):
   * 200 [{ barangay_id, barangay_name, center_latitude, center_longitude }]
   * 422 unknown municipality
   */
  list(municipality) {
    return request(`/barangays?municipality=${encodeURIComponent(municipality)}`, { auth: false });
  },
};

export const admin = {
  /**
   * Accounts newest first; filters: { status ('pending' | 'active' | 'deactivated'),
   * deletion_requested (true: requests not yet processed), role ('member' | 'coop_admin'),
   * q (name, mobile or member number), limit (default 50, at most 200), offset }.
   * 200 [{ user_id, first_name, last_name, mobile_no, email, member_no, municipality,
   *        barangay_name, role, account_status, created_at, deletion_requested_at }]
   * 403 not_admin
   */
  users(filters) {
    return request(`/admin/users${queryString(filters)}`);
  },

  /** 200 { pending, active, deactivated, deletion_requested }: member accounts. 403 not_admin */
  counts() {
    return request('/admin/users/counts');
  },

  /**
   * Approve ('active') or reject or deactivate ('deactivated') an account.
   * 200 { user_id, account_status }
   * 403 not_admin; 404 user_not_found; 409 cannot_deactivate_self | last_active_admin
   */
  setStatus(userId, accountStatus) {
    return request(`/admin/users/${encodeURIComponent(userId)}/status`, {
      method: 'PATCH',
      body: { account_status: accountStatus },
    });
  },

  /**
   * Process a deletion request: deactivates the account and removes its personal details;
   * farm records stay. Processing again changes nothing.
   * 200 { user_id, account_status: 'deactivated' }
   * 403 not_admin; 404 user_not_found;
   * 409 no_deletion_request | cannot_deactivate_self | last_active_admin
   */
  processDeletion(userId) {
    return request(`/admin/users/${encodeURIComponent(userId)}/process-deletion`, { method: 'POST' });
  },

  /**
   * The cooperative report (DFD 7.6); filters: { season, season_year, municipality }.
   * 200 { season, season_year, active_members, farms, by_crop: [{ crop_name, cycles, area_ha,
   *       harvested_cycles, harvest_kg, avg_yield_t_ha }], diseases: [{ crop_name,
   *       disease_name, scans }], scans: { diseased, healthy, unrecognized } }
   * 403 not_admin; 422 season_incomplete | unknown_municipality
   */
  cooperativeReport(filters) {
    return request(`/admin/reports/cooperative${queryString(filters)}`);
  },
};
