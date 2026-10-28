// frontend/public/js/api/client.js

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
  }
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

export async function request(path, { method = 'GET', body, headers = {}, auth = true, timeout = DEFAULT_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const token = auth ? tokenStore.get() : null;

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined && { 'Content-Type': 'application/json' }),
        ...(token && { Authorization: `Bearer ${token}` }),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
      signal: controller.signal,
    });

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
    if (err.name === 'AbortError') {
      throw new ApiError('The server took too long to respond. Please try again.');
    }
    throw new ApiError(
      navigator.onLine === false
        ? 'You appear to be offline. Check your connection and try again.'
        : 'Unable to reach ARISETO right now. Please try again.',
    );
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
    return request('/farms');
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
    return request(`/farms/${encodeURIComponent(farmId)}/fields`);
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
