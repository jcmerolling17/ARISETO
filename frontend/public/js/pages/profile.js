// frontend/public/js/pages/profile.js

import { CROPS } from '../data/farm-options.js';
import { auth, farms, users, ApiError } from '../api/client.js';
import { setStatus } from '../utils/form.js';
import { removeJSON, saveJSON } from '../utils/store.js';
import { showToast } from '../utils/toast.js';

const MESSAGES = {
  online: 'Online',
  offline: 'Offline',
  loadFailed: 'Your profile could not be loaded. Check your connection and try again.',
  loggedOut: 'You have logged out.',
  deletionHint: 'An MPMPC administrator removes your personal details',
  deletionRequested: (day) => `Requested on ${day}. An MPMPC administrator will process it.`,
  deletionConfirm:
    'Request account deletion?\n\nAn MPMPC administrator will deactivate your account and remove your personal details. Your farm records are kept for cooperative reports.',
  deletionSent: 'Deletion requested. An MPMPC administrator will process it.',
  deletionFailed: 'Your request could not be sent. Check your connection and try again.',
};

/** '+63 917 123 4567' from '+639171234567'. */
function formatMobile(mobile) {
  const match = /^\+63(\d{3})(\d{3})(\d{4})$/.exec(mobile ?? '');
  return match ? `+63 ${match[1]} ${match[2]} ${match[3]}` : mobile ?? '';
}

function formatHectares(value) {
  return `${Number(value).toLocaleString('en-PH', { maximumFractionDigits: 4 })} ha`;
}

/** 'October 28, 2026' in Philippine time, whatever the phone's time zone. */
function formatDay(value) {
  return new Date(value).toLocaleDateString('en-PH', {
    month: 'long', day: 'numeric', year: 'numeric', timeZone: 'Asia/Manila',
  });
}

export function mountProfilePage(router) {
  const view = document.querySelector('[data-view="profile"]');
  const plotList = view.querySelector('[data-plot-list]');
  const plotsEmpty = view.querySelector('[data-plots-empty]');
  const addPlot = view.querySelector('[data-add-plot]');
  const deletionRow = view.querySelector('[data-request-deletion]');
  const deletionHint = view.querySelector('[data-deletion-hint]');
  const tpl = view.querySelector('template[data-plot-tpl]').content.firstElementChild;

  let firstFarm = null;
  let requestId = 0;

  function renderOnline() {
    const offline = navigator.onLine === false;
    const status = view.querySelector('[data-online]');
    status.classList.toggle('is-offline', offline);
    status.querySelector('[data-online-title]').textContent = offline ? MESSAGES.offline : MESSAGES.online;
  }

  function renderDeletion(requestedAt) {
    deletionHint.textContent = requestedAt ? MESSAGES.deletionRequested(formatDay(requestedAt)) : MESSAGES.deletionHint;
    deletionRow.setAttribute('aria-disabled', String(Boolean(requestedAt)));
  }

  function renderUser(user) {
    view.querySelector('[data-initials]').textContent = `${user.first_name[0] ?? ''}${user.last_name[0] ?? ''}`.toUpperCase();
    view.querySelector('[data-full-name]').textContent = `${user.first_name} ${user.last_name}`;
    view.querySelectorAll('[data-mobile]').forEach((el) => { el.textContent = formatMobile(user.mobile_no); });
    renderDeletion(user.deletion_requested_at);
  }

  /** The first farm (GET /farms, oldest first) and its fields from GET /farms/{farm_id}/fields. */
  function renderPlots(farm, fields) {
    const active = fields.filter((field) => field.current_cycle?.status === 'active').length;
    const plotCount = view.querySelector('[data-plot-count]');
    plotCount.textContent = `${active} active ${active === 1 ? 'plot' : 'plots'}`;
    plotCount.hidden = active === 0;
    addPlot.hidden = farm?.role_on_farm !== 'owner';

    plotList.replaceChildren(...fields.map((field) => {
      const card = tpl.cloneNode(true);
      const cycle = field.current_cycle;
      const crop = CROPS.find((c) => c.label === cycle?.crop_name);
      card.querySelector('[data-crop-icon]').setAttribute('href', `#${crop?.icon ?? 'icon-seeds'}`);
      card.querySelector('[data-name]').textContent = field.field_name;
      card.querySelector('[data-meta]').textContent = [cycle?.crop_name ?? 'Not planted', formatHectares(field.area_ha)].join(' · ');
      card.querySelector('[data-place]').textContent = farm.barangay_name;
      card.querySelector('[data-edit]').setAttribute('aria-label', `Edit ${field.field_name}`);
      card.querySelector('[data-remove]').setAttribute('aria-label', `Remove ${field.field_name}`);
      return card;
    }));
    plotsEmpty.hidden = fields.length > 0;
  }

  async function render() {
    const id = ++requestId;
    setStatus(view, '');
    renderOnline();
    try {
      const [user, farmList] = await Promise.all([users.me(), farms.list()]);
      const farm = Array.isArray(farmList) ? farmList[0] ?? null : null;
      const fields = farm ? await farms.fields(farm.farm_id) : [];
      if (id !== requestId) return;
      firstFarm = farm;
      saveJSON('user', { first_name: user.first_name });
      renderUser(user);
      renderPlots(farm, fields ?? []);
    } catch (err) {
      if (id !== requestId || (err instanceof ApiError && err.sessionEnded)) return;
      setStatus(view, MESSAGES.loadFailed, 'error');
    }
  }

  addPlot.addEventListener('click', () => {
    if (firstFarm) router.navigate('add-plot', { state: { farm: firstFarm } });
  });

  // The admin deactivates the account and removes personal details; farm records are kept.
  deletionRow.addEventListener('click', async () => {
    if (deletionRow.getAttribute('aria-disabled') === 'true') return;
    if (!window.confirm(MESSAGES.deletionConfirm)) return;
    try {
      const result = await users.requestDeletion();
      renderDeletion(result.deletion_requested_at);
      showToast(MESSAGES.deletionSent);
    } catch (err) {
      if (!(err instanceof ApiError && err.sessionEnded)) setStatus(view, MESSAGES.deletionFailed, 'error');
    }
  });

  // Log out for real: forget the session token and the saved user and farm, then go to Login.
  view.querySelector('[data-logout]').addEventListener('click', () => {
    auth.logout();
    removeJSON('user');
    removeJSON('farm');
    router.navigate('login', { replace: true, state: { message: MESSAGES.loggedOut, tone: 'success' } });
  });

  window.addEventListener('online', () => { if (!view.hidden) renderOnline(); });
  window.addEventListener('offline', () => { if (!view.hidden) renderOnline(); });

  router.route('profile', {
    onEnter({ state } = {}) {
      render();
      // A message from Edit Profile, Change Password, or Add Plot.
      if (state?.message) setStatus(view, state.message, 'success');
    },
  });
}
