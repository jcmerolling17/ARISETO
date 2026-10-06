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
  }
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
  /** credentials: { mobile_no, password } or { email, password } */
  async login(credentials) {
    const data = await request('/auth/login', { method: 'POST', body: credentials, auth: false });
    if (data?.access_token) tokenStore.set(data.access_token);
    return data;
  },

  /** payload: { first_name, last_name, mobile_no, email|null, password } */
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
