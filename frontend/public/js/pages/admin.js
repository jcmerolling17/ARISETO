// frontend/public/js/pages/admin.js

/**
 * Admin Portal (coop_admin only): the Admin Approval List (DFD 1.4; GET /admin/users with
 * role=member, GET /admin/users/counts, PATCH /admin/users/{id}/status, POST
 * /admin/users/{id}/process-deletion) and the Cooperative Report (DFD 7.6; GET
 * /admin/reports/cooperative). Every call is checked by the API; a member gets not_admin.
 */
import { ApiError, admin, auth } from '../api/client.js';
import { TIME_ZONE } from '../api/weather.js';
import { MUNICIPALITIES } from '../data/farm-options.js';
import { setStatus } from '../utils/form.js';
import { removeJSON } from '../utils/store.js';
import { showToast } from '../utils/toast.js';
import { seasonChoices } from './expenses.js';

const PAGE_SIZE = 50;
const SEARCH_DELAY_MS = 300;
// A processed deletion request replaces the mobile number with D<user_id> (Phase 13).
const PROCESSED_MOBILE = /^D\d+$/;

const MESSAGES = {
  loggedOut: 'You have logged out.',
  noPending: 'No pending sign-ups.',
  noAccounts: 'No accounts found.',
  noDeletionRequests: 'No deletion requests.',
  approved: 'Account approved.',
  rejected: 'Sign-up rejected.',
  processed: 'Personal details removed.',
  rejectTitle: 'Reject this sign-up?',
  rejectText: (name) => `${name} won't be able to log in. You can approve the account later from the Rejected tab.`,
  rejectButton: 'Reject',
  processTitle: 'Process deletion request?',
  processText: (name) =>
    `This deactivates ${name}'s account, ends their sessions, changes the name to "Deleted Member", ` +
    'clears the email, and replaces the mobile and member numbers. Farm records are kept for ' +
    "cooperative reports. This can't be undone.",
  processButton: 'Remove personal details',
  noHarvest: 'No harvest yet',
  allMunicipalities: 'All municipalities',
  current: (short) => `${short} (current)`,
};

const ERRORS = {
  cannot_deactivate_self: "You can't deactivate your own account.",
  last_active_admin: "The last active administrator can't be deactivated.",
  no_deletion_request: 'This member has not asked for deletion.',
  user_not_found: 'This account no longer exists.',
  not_admin: 'Only MPMPC administrators can open the Admin Portal.',
};

const STATUS_LABELS = { pending: 'Pending', active: 'Active', deactivated: 'Deactivated' };

/** The tabs and the GET /admin/users filters each one sends. */
const TABS = {
  pending: { status: 'pending' },
  active: { status: 'active' },
  deactivated: { status: 'deactivated' },
  all: {},
  deletion: { deletion_requested: true },
};

function isSessionEnd(err) {
  return err instanceof ApiError && err.sessionEnded;
}

function errorMessage(err) {
  return (err instanceof ApiError && ERRORS[err.code]) || err.message;
}

function fullName(user) {
  return `${user.first_name} ${user.last_name}`.trim();
}

function isProcessed(user) {
  return PROCESSED_MOBILE.test(user.mobile_no);
}

/** The chip on a row: a deletion request (processed or not) shows instead of the status. */
function statusOf(user) {
  if (isProcessed(user)) return { key: 'removed', label: 'Details removed' };
  if (user.deletion_requested_at) return { key: 'deletion', label: 'Deletion requested' };
  return { key: user.account_status, label: STATUS_LABELS[user.account_status] ?? user.account_status };
}

function formatDate(iso) {
  // en-CA gives YYYY-MM-DD, as on the mockup.
  return new Date(iso).toLocaleDateString('en-CA', { timeZone: TIME_ZONE });
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('en-PH', { timeZone: TIME_ZONE, hour: '2-digit', minute: '2-digit' });
}

function formatNumber(value, digits = 2) {
  return Number(value).toLocaleString('en-PH', { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

function cell(text) {
  const span = document.createElement('span');
  span.setAttribute('role', 'cell');
  span.textContent = text;
  return span;
}

/** Asks with the shared dialog; resolves true when the admin confirms. */
function confirmDialog(dialog, { title, text, button }) {
  dialog.querySelector('[data-dialog-title]').textContent = title;
  dialog.querySelector('[data-dialog-text]').textContent = text;
  dialog.querySelector('[data-dialog-confirm]').textContent = button;
  dialog.returnValue = '';
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
    dialog.showModal();
  });
}

function mountPortalChrome(router, view, route) {
  view.querySelectorAll('[data-admin-nav]').forEach((link) => {
    const active = link.dataset.adminNav === route;
    link.classList.toggle('is-active', active);
    if (active) link.setAttribute('aria-current', 'page');
  });
  view.querySelector('[data-admin-logout]').addEventListener('click', () => {
    auth.logout();
    removeJSON('user');
    removeJSON('farm');
    router.navigate('admin-login', { replace: true, state: { message: MESSAGES.loggedOut, tone: 'success' } });
  });
}

/* ---------- Admin Approval List ---------- */

function mountApprovalList(router) {
  const view = document.querySelector('[data-view="admin"]');
  const list = view.querySelector('[data-user-list]');
  const empty = view.querySelector('[data-user-empty]');
  const more = view.querySelector('[data-load-more]');
  const search = view.querySelector('[data-admin-search]');
  const tabs = [...view.querySelectorAll('[data-tab]')];
  const dialog = view.querySelector('[data-confirm-dialog]');
  const tpl = view.querySelector('template[data-user-tpl]').content.firstElementChild;

  let tab = 'pending';
  let offset = 0;
  let requestId = 0;
  let searchTimer = 0;

  mountPortalChrome(router, view, 'admin');

  function emptyMessage() {
    if (search.value.trim()) return MESSAGES.noAccounts;
    if (tab === 'pending') return MESSAGES.noPending;
    if (tab === 'deletion') return MESSAGES.noDeletionRequests;
    return MESSAGES.noAccounts;
  }

  function row(user) {
    const item = tpl.cloneNode(true);
    const name = fullName(user);
    const processed = isProcessed(user);
    item.querySelector('[data-name]').textContent = name;
    item.querySelector('[data-member-no]').textContent = processed ? '—' : user.member_no ?? '—';
    item.querySelector('[data-mobile]').textContent = processed ? '—' : user.mobile_no;
    item.querySelector('[data-place]').textContent = user.barangay_name
      ? `Brgy. ${user.barangay_name}, ${user.municipality}`
      : user.municipality;
    item.querySelector('[data-date]').textContent = formatDate(user.created_at);
    item.querySelector('[data-time]').textContent = formatTime(user.created_at);
    const status = statusOf(user);
    const chip = item.querySelector('[data-status]');
    chip.textContent = status.label;
    chip.dataset.status = status.key;

    // A processed account ("Details removed") gets no actions; other deactivated accounts
    // keep Approve, and only pending sign-ups can be rejected.
    const actions = processed
      ? { approve: false, reject: false, process: false }
      : {
          approve: user.account_status !== 'active',
          reject: user.account_status === 'pending',
          process: Boolean(user.deletion_requested_at),
        };
    for (const [action, shown] of Object.entries(actions)) {
      const button = item.querySelector(`[data-action="${action}"]`);
      button.hidden = !shown;
      button.addEventListener('click', () => act(action, user, name, button));
    }
    return item;
  }

  async function loadCounts() {
    try {
      const counts = await admin.counts();
      for (const [key, value] of Object.entries(counts ?? {})) {
        const el = view.querySelector(`[data-count="${key}"]`);
        if (el) el.textContent = Number(value).toLocaleString('en-PH');
      }
    } catch (err) {
      if (!isSessionEnd(err)) setStatus(view, errorMessage(err), 'error');
    }
  }

  async function loadUsers({ append = false } = {}) {
    const id = (requestId += 1);
    if (!append) offset = 0;
    setStatus(view, '');
    const q = search.value.trim();
    try {
      const page = (await admin.users({ ...TABS[tab], role: 'member', q, limit: PAGE_SIZE, offset })) ?? [];
      if (id !== requestId) return;
      const rows = page.map(row);
      if (append) list.append(...rows);
      else list.replaceChildren(...rows);
      offset += page.length;
      more.hidden = page.length < PAGE_SIZE;
      empty.hidden = list.children.length > 0;
      empty.textContent = emptyMessage();
    } catch (err) {
      if (id !== requestId || isSessionEnd(err)) return;
      if (!append) list.replaceChildren();
      more.hidden = true;
      empty.hidden = true;
      setStatus(view, errorMessage(err), 'error');
    }
  }

  function refresh() {
    loadCounts();
    loadUsers();
  }

  async function act(action, user, name, button) {
    if (action === 'reject') {
      const ok = await confirmDialog(dialog, {
        title: MESSAGES.rejectTitle,
        text: MESSAGES.rejectText(name),
        button: MESSAGES.rejectButton,
      });
      if (!ok) return;
    }
    if (action === 'process') {
      const ok = await confirmDialog(dialog, {
        title: MESSAGES.processTitle,
        text: MESSAGES.processText(name),
        button: MESSAGES.processButton,
      });
      if (!ok) return;
    }
    button.disabled = true;
    setStatus(view, '');
    try {
      if (action === 'approve') await admin.setStatus(user.user_id, 'active');
      else if (action === 'reject') await admin.setStatus(user.user_id, 'deactivated');
      else await admin.processDeletion(user.user_id);
      showToast({ approve: MESSAGES.approved, reject: MESSAGES.rejected, process: MESSAGES.processed }[action]);
      refresh();
    } catch (err) {
      button.disabled = false;
      if (!isSessionEnd(err)) setStatus(view, errorMessage(err), 'error');
    }
  }

  function selectTab(name) {
    tab = name;
    tabs.forEach((button) => {
      const selected = button.dataset.tab === name;
      button.classList.toggle('is-active', selected);
      button.setAttribute('aria-selected', String(selected));
    });
  }

  tabs.forEach((button) => button.addEventListener('click', () => {
    selectTab(button.dataset.tab);
    loadUsers();
  }));
  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadUsers(), SEARCH_DELAY_MS);
  });
  more.addEventListener('click', () => loadUsers({ append: true }));

  selectTab(tab);

  router.route('admin', {
    onEnter() {
      refresh();
    },
    onLeave() {
      requestId += 1;
      clearTimeout(searchTimer);
      if (dialog.open) dialog.close();
    },
  });
}

/* ---------- Cooperative Report ---------- */

function mountCooperativeReport(router) {
  const view = document.querySelector('[data-view="admin-report"]');
  const seasonPicker = view.querySelector('[data-season-picker]');
  const municipalityPicker = view.querySelector('[data-municipality-picker]');
  const cropList = view.querySelector('[data-crop-list]');
  const cropEmpty = view.querySelector('[data-crop-empty]');
  const diseaseList = view.querySelector('[data-disease-list]');
  const diseaseEmpty = view.querySelector('[data-disease-empty]');
  const figure = (name) => view.querySelector(`[data-figure="${name}"]`);

  let requestId = 0;

  mountPortalChrome(router, view, 'admin-report');

  municipalityPicker.replaceChildren(
    new Option(MESSAGES.allMunicipalities, ''),
    ...MUNICIPALITIES.map((m) => new Option(m, m)),
  );

  function fillSeasonPicker() {
    const seasons = seasonChoices();
    const current = seasons[1];
    const chosen = seasonPicker.value || current.key;
    seasonPicker.replaceChildren(...seasons.map((s) => {
      const option = new Option(s.key === current.key ? MESSAGES.current(s.short) : s.short, s.key);
      option.setAttribute('aria-label', s.label);
      return option;
    }));
    seasonPicker.value = seasons.some((s) => s.key === chosen) ? chosen : current.key;
  }

  function clear() {
    ['active_members', 'farms', 'scans'].forEach((name) => { figure(name).textContent = '–'; });
    cropList.replaceChildren();
    diseaseList.replaceChildren();
    cropEmpty.hidden = true;
    diseaseEmpty.hidden = true;
  }

  function render(report) {
    figure('active_members').textContent = Number(report.active_members).toLocaleString('en-PH');
    figure('farms').textContent = Number(report.farms).toLocaleString('en-PH');
    const { diseased, healthy, unrecognized } = report.scans;
    figure('scans').textContent = `${diseased} / ${healthy} / ${unrecognized}`;

    cropList.replaceChildren(...report.by_crop.map((crop) => {
      const line = document.createElement('div');
      line.className = 'admin-row admin-row--crop';
      line.setAttribute('role', 'row');
      line.append(
        cell(crop.crop_name),
        cell(formatNumber(crop.cycles, 0)),
        cell(formatNumber(crop.area_ha, 4)),
        cell(formatNumber(crop.harvested_cycles, 0)),
        cell(formatNumber(crop.harvest_kg)),
        cell(crop.avg_yield_t_ha == null ? MESSAGES.noHarvest : formatNumber(crop.avg_yield_t_ha)),
      );
      line.querySelectorAll('[role="cell"]').forEach((c, i) => {
        c.dataset.label = ['Crop', 'Cycles', 'Area (ha)', 'Harvested', 'Harvest (kg)', 'Avg. yield (t/ha)'][i];
      });
      return line;
    }));
    cropEmpty.hidden = report.by_crop.length > 0;

    diseaseList.replaceChildren(...report.diseases.map((d) => {
      const item = document.createElement('li');
      item.className = 'admin-disease';
      const name = document.createElement('span');
      name.className = 'admin-disease__name';
      name.textContent = d.disease_name;
      const crop = document.createElement('span');
      crop.className = 'admin-disease__crop';
      crop.textContent = d.crop_name;
      const count = document.createElement('strong');
      count.className = 'admin-disease__count';
      count.textContent = formatNumber(d.scans, 0);
      item.append(name, crop, count);
      return item;
    }));
    diseaseEmpty.hidden = report.diseases.length > 0;
  }

  async function load() {
    const id = (requestId += 1);
    setStatus(view, '');
    const [season, year] = seasonPicker.value.split('-');
    try {
      const report = await admin.cooperativeReport({
        season,
        season_year: year,
        municipality: municipalityPicker.value,
      });
      if (id !== requestId) return;
      render(report);
    } catch (err) {
      if (id !== requestId || isSessionEnd(err)) return;
      clear();
      setStatus(view, errorMessage(err), 'error');
    }
  }

  seasonPicker.addEventListener('change', load);
  municipalityPicker.addEventListener('change', load);

  router.route('admin-report', {
    onEnter() {
      fillSeasonPicker();
      load();
    },
    onLeave() {
      requestId += 1;
    },
  });
}

export function mountAdminPages(router) {
  mountApprovalList(router);
  mountCooperativeReport(router);
}
