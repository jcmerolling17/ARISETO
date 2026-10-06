// frontend/public/js/pages/login.js

import { auth, ApiError } from '../api/client.js';

const MOBILE_RE = /^\+639\d{9}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const MIN_PASSWORD_LENGTH = 8;

const MESSAGES = {
  identifierRequired: 'Enter your mobile number or email.',
  mobileRequired: 'Enter your mobile number.',
  mobileInvalid: 'Enter a valid PH mobile number, e.g. +639171234567.',
  emailInvalid: 'Enter a valid email address.',
  passwordRequired: 'Enter your password.',
  passwordShort: `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`,
  firstNameRequired: 'Enter your first name.',
  lastNameRequired: 'Enter your last name.',
  loginFailed: 'Incorrect mobile number/email or password.',
  loginSuccess: "Welcome back! You're now signed in.",
  accountExists: 'An account with this mobile number or email already exists.',
  signupSuccess: 'Account created. Log in with your mobile number.',
  oauthRedirect: 'Redirecting to sign in…',
  oauthUnavailable: 'This sign-in option is not available right now. Please use your mobile number instead.',
};

/* ---------- Validation ---------- */

/** Accepts +639XXXXXXXXX, 639XXXXXXXXX, 09XXXXXXXXX or 9XXXXXXXXX (spaces/dashes allowed). */
export function normalizeMobile(raw) {
  const compact = String(raw).trim().replace(/[\s().-]/g, '');
  if (/^09\d{9}$/.test(compact)) return `+63${compact.slice(1)}`;
  if (/^639\d{9}$/.test(compact)) return `+${compact}`;
  if (/^9\d{9}$/.test(compact)) return `+63${compact}`;
  return compact;
}

export function isValidMobile(value) {
  return MOBILE_RE.test(value);
}

export function isValidEmail(value) {
  return EMAIL_RE.test(value);
}

/** Resolves the login identifier into the backend field it maps to. */
export function parseIdentifier(raw) {
  const value = String(raw).trim();
  if (!value) return { error: MESSAGES.identifierRequired };

  if (value.includes('@')) {
    const email = value.toLowerCase();
    return isValidEmail(email) ? { field: 'email', value: email } : { error: MESSAGES.emailInvalid };
  }

  const mobile = normalizeMobile(value);
  return isValidMobile(mobile) ? { field: 'mobile_no', value: mobile } : { error: MESSAGES.mobileInvalid };
}

function cleanName(raw) {
  return String(raw).trim().replace(/\s+/g, ' ');
}

/* ---------- Form helpers ---------- */

function setFieldError(input, message) {
  const errorEl = document.getElementById(`${input.id}-error`);
  if (message) {
    input.setAttribute('aria-invalid', 'true');
  } else {
    input.removeAttribute('aria-invalid');
  }
  if (errorEl) errorEl.textContent = message || '';
}

function clearFieldErrors(form) {
  form.querySelectorAll('.input').forEach((input) => setFieldError(input, ''));
}

function setStatus(container, message, tone = 'error') {
  const statusEl = container.querySelector('[data-form-status]');
  if (!statusEl) return;
  statusEl.textContent = message || '';
  if (message) statusEl.dataset.tone = tone;
  else delete statusEl.dataset.tone;
}

function setBusy(form, busy) {
  const submit = form.querySelector('[type="submit"]');
  form.setAttribute('aria-busy', String(busy));
  if (submit) {
    submit.disabled = busy;
    submit.classList.toggle('is-loading', busy);
  }
}

function focusFirstInvalid(form) {
  form.querySelector('[aria-invalid="true"]')?.focus();
}

function bindLiveErrorClearing(form) {
  form.addEventListener('input', (event) => {
    if (event.target.matches('.input[aria-invalid="true"]')) setFieldError(event.target, '');
  });
}

function bindPasswordToggles(root) {
  root.querySelectorAll('[data-toggle-password]').forEach((toggle) => {
    const input = document.getElementById(toggle.getAttribute('aria-controls'));
    if (!input) return;
    toggle.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      toggle.setAttribute('aria-pressed', String(show));
      toggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      input.focus({ preventScroll: true });
    });
  });
}

function resetPasswordVisibility(form) {
  form.querySelectorAll('[data-toggle-password]').forEach((toggle) => {
    const input = document.getElementById(toggle.getAttribute('aria-controls'));
    if (input) input.type = 'password';
    toggle.setAttribute('aria-pressed', 'false');
    toggle.setAttribute('aria-label', 'Show password');
  });
}

/**
 * Checks the OAuth start endpoint before leaving the app, so a missing or failing
 * backend shows an inline message instead of a bare browser error page.
 * A working endpoint answers with a redirect to the provider (opaqueredirect).
 */
async function isOAuthAvailable(url) {
  try {
    const response = await fetch(url, { redirect: 'manual', credentials: 'same-origin' });
    return response.type === 'opaqueredirect' || response.ok;
  } catch {
    return false;
  }
}

function bindOAuthButtons(root) {
  const buttons = root.querySelectorAll('[data-oauth]');

  buttons.forEach((button) => {
    button.addEventListener('click', async () => {
      const view = button.closest('[data-view]');
      const url = auth.oauthUrl(button.dataset.oauth);
      buttons.forEach((b) => { b.disabled = true; });
      if (view) setStatus(view, MESSAGES.oauthRedirect, 'success');

      if (await isOAuthAvailable(url)) {
        window.location.assign(url);
        return;
      }

      buttons.forEach((b) => { b.disabled = false; });
      if (view) setStatus(view, MESSAGES.oauthUnavailable, 'error');
    });
  });

  // Re-enable buttons if the user returns via the back/forward cache.
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    root.querySelectorAll('[data-oauth]').forEach((b) => { b.disabled = false; });
    root.querySelectorAll('[data-form-status]').forEach((s) => { s.textContent = ''; delete s.dataset.tone; });
  });
}

/* ---------- Login ---------- */

function mountLogin(router) {
  const view = document.querySelector('[data-view="login"]');
  const form = document.getElementById('login-form');
  const identifier = form.elements.identifier;
  const password = form.elements.password;

  bindLiveErrorClearing(form);

  // Show normalized +639 format once the user leaves the field.
  identifier.addEventListener('blur', () => {
    const value = identifier.value.trim();
    if (value && !value.includes('@')) {
      const mobile = normalizeMobile(value);
      if (isValidMobile(mobile)) identifier.value = mobile;
    }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;

    clearFieldErrors(form);
    setStatus(view, '');

    const id = parseIdentifier(identifier.value);
    if (id.error) setFieldError(identifier, id.error);
    if (!password.value) setFieldError(password, MESSAGES.passwordRequired);
    if (id.error || !password.value) {
      focusFirstInvalid(form);
      return;
    }

    identifier.value = id.value;
    setBusy(form, true);

    try {
      const session = await auth.login({ [id.field]: id.value, password: password.value });
      password.value = '';
      resetPasswordVisibility(form);
      setStatus(view, MESSAGES.loginSuccess, 'success');
      window.dispatchEvent(new CustomEvent('ariseto:authenticated', { detail: session }));
    } catch (err) {
      const message = err instanceof ApiError && (err.status === 401 || err.status === 400)
        ? MESSAGES.loginFailed
        : err.message;
      setStatus(view, message, 'error');
      password.select();
    } finally {
      setBusy(form, false);
    }
  });

  router.route('login', {
    onEnter({ state } = {}) {
      if (state?.identifier) identifier.value = state.identifier;
      if (state?.message) setStatus(view, state.message, state.tone || 'success');
    },
    onLeave() {
      password.value = '';
      resetPasswordVisibility(form);
      clearFieldErrors(form);
      setStatus(view, '');
    },
  });
}

/* ---------- Sign up (Email / Mobile) ---------- */

function mountSignup(router) {
  const view = document.querySelector('[data-view="signup"]');
  const form = document.getElementById('signup-form');
  const { first_name: firstName, last_name: lastName, mobile_no: mobile, email, password } = form.elements;

  bindLiveErrorClearing(form);

  mobile.addEventListener('blur', () => {
    const normalized = normalizeMobile(mobile.value);
    if (isValidMobile(normalized)) mobile.value = normalized;
  });

  function validate() {
    const first = cleanName(firstName.value);
    const last = cleanName(lastName.value);
    const mobileNo = normalizeMobile(mobile.value);
    const emailValue = email.value.trim().toLowerCase();

    if (!first) setFieldError(firstName, MESSAGES.firstNameRequired);
    if (!last) setFieldError(lastName, MESSAGES.lastNameRequired);
    if (!mobile.value.trim()) setFieldError(mobile, MESSAGES.mobileRequired);
    else if (!isValidMobile(mobileNo)) setFieldError(mobile, MESSAGES.mobileInvalid);
    if (emailValue && !isValidEmail(emailValue)) setFieldError(email, MESSAGES.emailInvalid);
    if (!password.value) setFieldError(password, MESSAGES.passwordRequired);
    else if (password.value.length < MIN_PASSWORD_LENGTH) setFieldError(password, MESSAGES.passwordShort);

    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      first_name: first,
      last_name: last,
      mobile_no: mobileNo,
      email: emailValue || null,
      password: password.value,
    };
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;

    clearFieldErrors(form);
    setStatus(view, '');

    const payload = validate();
    if (!payload) {
      focusFirstInvalid(form);
      return;
    }

    mobile.value = payload.mobile_no;
    setBusy(form, true);

    try {
      await auth.register(payload);
      form.reset();
      resetPasswordVisibility(form);
      router.navigate('login', {
        state: { identifier: payload.mobile_no, message: MESSAGES.signupSuccess, tone: 'success' },
      });
    } catch (err) {
      const message = err instanceof ApiError && err.status === 409 ? MESSAGES.accountExists : err.message;
      setStatus(view, message, 'error');
    } finally {
      setBusy(form, false);
    }
  });

  router.route('signup', {
    onLeave() {
      password.value = '';
      resetPasswordVisibility(form);
      clearFieldErrors(form);
      setStatus(view, '');
    },
  });
}

/* ---------- Public entry ---------- */

export function mountAuthPages(router, root = document) {
  bindPasswordToggles(root);
  bindOAuthButtons(root);
  mountLogin(router);
  mountSignup(router);
}
