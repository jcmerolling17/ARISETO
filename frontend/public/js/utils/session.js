// frontend/public/js/utils/session.js

import { auth } from '../api/client.js';
import { loadJSON, saveJSON } from './store.js';

/** Screens only a cooperative administrator uses (the Admin Portal). */
export const ADMIN_ROUTES = new Set(['admin', 'admin-report']);

/** Screens anyone may open, signed in or not. */
const OPEN_ROUTES = new Set(['welcome', 'signup', 'terms', 'privacy', 'login', 'admin-login']);

/**
 * Remember the signed-in user's first name and role on this device. The role decides where
 * the app opens; the API still checks it on every admin call.
 */
export function rememberUser({ first_name: firstName, role } = {}) {
  const saved = loadJSON('user') ?? {};
  saveJSON('user', {
    first_name: firstName ?? saved.first_name,
    role: role ?? saved.role ?? 'member',
  });
}

export function isAdminSession() {
  return auth.isAuthenticated() && loadJSON('user')?.role === 'coop_admin';
}

/**
 * Where a signed-in user may not go: an administrator is sent from member screens to the
 * Admin Portal, and a member from admin screens to Home. Null when the route is fine.
 */
export function redirectForRole(route) {
  if (OPEN_ROUTES.has(route)) return null;
  if (!auth.isAuthenticated()) return ADMIN_ROUTES.has(route) ? 'admin-login' : null;
  if (isAdminSession()) return ADMIN_ROUTES.has(route) ? null : 'admin';
  return ADMIN_ROUTES.has(route) ? 'home' : null;
}
