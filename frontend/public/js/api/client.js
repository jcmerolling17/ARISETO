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
      throw new ApiError(errorMessage(data, response.status), { status: response.status, details: data });
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
   *            municipality, barangay_id (optional), preferred_language (optional) }
   * 201 { user_id, account_status: 'pending' }: the account awaits coop_admin approval.
   * 409 mobile_taken | email_taken | member_no_taken
   */
  register(payload) {
    return request('/auth/register', { method: 'POST', body: payload, auth: false });
  },

  oauthUrl(provider) {
    return `${API_BASE}/auth/oauth/${encodeURIComponent(provider)}`;
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
   * payload: { farm_name, barangay_id, latitude, longitude, total_area_ha }
   * 201 { farm_id }: the caller is saved as the farm's 'owner' in FARM_ASSIGNMENT.
   * 422 coordinates_outside_province (latitude/longitude outside Occidental Mindoro)
   */
  create(payload) {
    return request('/farms', { method: 'POST', body: payload });
  },

  /**
   * Opens a crop cycle on a farm (owner only).
   * payload: { variety_id, season: 'wet'|'dry', planting_date: 'YYYY-MM-DD', area_planted_ha,
   *            target_yield_t_ha (optional) }
   * 201 { cycle_id, expected_harvest_date }: the backend also generates the crop calendar.
   * 403 not_farm_owner; 422 area_exceeds_farm
   */
  createCycle(farmId, payload) {
    return request(`/farms/${encodeURIComponent(farmId)}/cycles`, { method: 'POST', body: payload });
  },

  /**
   * Weather for the farm, served from WEATHER_LOG (never fetched live per request):
   * 200 { current: { temp_c, feels_like_c, humidity_pct, wind_speed_mps, precip_probability_pct,
   *                  rain_mm, condition_code, fetched_at },
   *       forecast: [...same fields with forecast_for], alerts: [...] }
   * 403 not_farm_member
   */
  weather(farmId) {
    return request(`/farms/${encodeURIComponent(farmId)}/weather`);
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

export const crops = {
  /**
   * Crops in scope with their varieties:
   * [{ crop_id, crop_name, varieties: [{ variety_id, variety_name, maturity_class, maturity_days }] }]
   */
  list() {
    return request('/crops');
  },
};
