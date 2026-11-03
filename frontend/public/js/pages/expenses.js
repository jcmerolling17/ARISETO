// frontend/public/js/pages/expenses.js

import { farms, expenses as expensesApi, ApiError } from '../api/client.js';
import { EXPENSE_CATEGORIES, QUANTITY_UNITS } from '../data/farm-options.js';
import { showToast } from '../utils/toast.js';
import { formatPeso, seasonForDate, seasonOf, shiftSeason } from '../utils/farm.js';
import { formatShortDate, parseISODate, philippineToday, toISODate } from '../utils/dates.js';
import {
  setFieldError,
  clearFieldErrors,
  setStatus,
  setBusy,
  focusFirstInvalid,
  bindLiveErrorClearing,
} from '../utils/form.js';

const PAGE_SIZE = 5;
const MAX_AMOUNT = 99999999.99; // EXPENSE.amount_php and quantity NUMERIC(10,2)
const WHOLE_FARM = 'farm';
const ALL_FIELDS = '';

const MESSAGES = {
  noFarm: 'No fields yet. Set up your farm to track its expenses.',
  loadFailed: 'Your expenses could not be loaded. Check your connection and try again.',
  noIncomeYet: 'No harvest income yet this season.',
  categoryRequired: 'Choose an expense category.',
  amountRequired: 'Enter the amount.',
  amountInvalid: 'Enter an amount greater than 0, with up to 2 decimals.',
  amountTooLarge: 'This amount is too large. Check the number.',
  dateRequired: 'Enter the date.',
  dateFuture: 'The date cannot be after today.',
  quantityInvalid: 'Enter a quantity greater than 0, with up to 2 decimals.',
  plotRequired: 'Choose the plot this expense is for.',
  seasonRequired: 'Choose the season for this whole-farm expense.',
  saved: 'Expense saved.',
  deleteConfirm: (title) => `Delete "${title}"? This cannot be undone.`,
  deleted: 'Expense deleted.',
  deleteFailed: 'The expense could not be deleted. Check your connection and try again.',
  // POST /farms/{farm_id}/expenses error codes, as short plain messages.
  category_not_found: 'This category is no longer available. Choose another one.',
  cycle_not_in_farm: 'This field is no longer on your farm. Choose the plot again.',
  season_required: 'Choose the season for this whole-farm expense.',
  season_mismatch: 'The season does not match the field’s crop. Choose the plot again.',
  unit_required: 'Choose a unit for the quantity.',
  quantity_required: 'Enter the quantity for this unit.',
  expense_date_in_future: 'The date cannot be after today.',
  client_uuid_taken: 'This entry could not be saved. Please press Save Expense again.',
  not_farm_member: 'You are no longer a member of this farm.',
  not_allowed: 'Only the member who recorded this expense or the farm owner can delete it.',
  expense_not_found: 'This expense was already deleted.',
};

/** Season and field shown on Farm Expenses; saving an expense or harvest returns to its season. */
const filters = { seasonKey: null, fieldId: ALL_FIELDS };

/** Show this season on Farm Expenses next time it opens (after saving an expense or harvest). */
export function showSeasonNext(season) {
  filters.seasonKey = season.key;
  filters.fieldId = ALL_FIELDS;
}

/**
 * The member's first farm (GET /farms, oldest first) and its fields with their current
 * cycles (GET /farms/{farm_id}/fields); farm is null before farm setup.
 */
export async function loadFirstFarm() {
  const list = await farms.list();
  const farm = Array.isArray(list) ? list[0] ?? null : null;
  const fields = farm ? (await farms.fields(farm.farm_id)) ?? [] : [];
  return { farm, fields };
}

/** The next season, the current one, and each season back two years, newest first. */
export function seasonChoices(today = philippineToday()) {
  const current = seasonForDate(today);
  return [shiftSeason(current, 1), current, ...[1, 2, 3, 4].map((n) => shiftSeason(current, -n))];
}

function fillSeasons(select, seasons, current) {
  select.replaceChildren(...seasons.map((s) => {
    const option = new Option(s.key === current?.key ? `${s.short} (current)` : s.short, s.key);
    option.setAttribute('aria-label', s.label);
    return option;
  }));
}

function seasonFromKey(key) {
  const [season, year] = key.split('-');
  return seasonOf(season, Number(year));
}

/** Icon and chart color for a category, kept in farm-options.js by category name. */
function categoryStyle(name) {
  return EXPENSE_CATEGORIES.find((c) => c.category_name === name) ?? EXPENSE_CATEGORIES[EXPENSE_CATEGORIES.length - 1];
}

/** A v4 UUID made on the phone, so a resent expense is never saved twice. */
function newClientUuid() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function isSessionEnd(err) {
  return err instanceof ApiError && err.sessionEnded;
}

function showEmpty(view, message) {
  view.querySelector('[data-empty]').hidden = false;
  view.querySelector('[data-empty-text]').textContent = message;
}

/* ---------- Farm Expenses ---------- */

function mountExpenses(router) {
  const view = document.querySelector('[data-view="expenses"]');
  const content = view.querySelector('[data-content]');
  const seasonPicker = view.querySelector('[data-season-picker]');
  const plotPicker = view.querySelector('[data-field-filter]');
  const search = view.querySelector('[data-tx-search]');
  const txList = view.querySelector('[data-tx-list]');
  const txEmpty = view.querySelector('[data-tx-empty]');
  const txMore = view.querySelector('[data-tx-more]');
  const recordHarvest = view.querySelector('[data-record-harvest]');
  const tpl = (name) => view.querySelector(`template[data-${name}-tpl]`).content.firstElementChild;
  let visible = PAGE_SIZE;
  let farm = null;
  let rows = [];
  let requestId = 0;

  function renderPickers(fields) {
    const seasons = seasonChoices();
    const current = seasons[1];
    // A saved expense may belong to an older season; keep it pickable.
    const chosen = filters.seasonKey ? seasonFromKey(filters.seasonKey) : current;
    if (!seasons.some((s) => s.key === chosen.key)) seasons.push(chosen);
    fillSeasons(seasonPicker, seasons, current);
    filters.seasonKey = chosen.key;
    seasonPicker.value = chosen.key;

    plotPicker.replaceChildren(
      new Option('All fields', ALL_FIELDS),
      ...fields.map((f) => new Option(
        f.current_cycle ? `${f.field_name} · ${f.current_cycle.crop_name}` : f.field_name,
        String(f.field_id),
      )),
    );
    if (![...plotPicker.options].some((o) => o.value === filters.fieldId)) filters.fieldId = ALL_FIELDS;
    plotPicker.value = filters.fieldId;
  }

  function renderTotals(summary) {
    const total = (name) => view.querySelector(`[data-total="${name}"]`);
    total('expense').textContent = formatPeso(summary.total_expenses_php);
    total('income').textContent = formatPeso(summary.gross_income_php);
    total('net').textContent = formatPeso(summary.net_profit_php);
    total('net').classList.toggle('is-negative', summary.net_profit_php < 0);
    const isCurrent = filters.seasonKey === seasonForDate(philippineToday()).key;
    view.querySelector('[data-net-note]').textContent =
      isCurrent && summary.gross_income_php === 0 ? MESSAGES.noIncomeYet : '';
    view.querySelector('[data-donut-value]').textContent = formatPeso(summary.net_profit_php);

    // With "All fields", whole-farm expenses also get their own line.
    const wholeFarm = view.querySelector('[data-whole-farm]');
    wholeFarm.hidden = filters.fieldId !== ALL_FIELDS;
    view.querySelector('[data-whole-farm-amount]').textContent = formatPeso(summary.whole_farm_expenses_php);
  }

  function renderCategories(summary) {
    const spent = summary.total_expenses_php;
    const categories = summary.by_category.map((c) => ({
      ...categoryStyle(c.category_name),
      category_name: c.category_name,
      amount: c.amount_php,
    }));

    view.querySelector('[data-category-list]').replaceChildren(...categories.map((category) => {
      const row = tpl('category').cloneNode(true);
      row.querySelector('[data-icon]').setAttribute('href', `#${category.icon}`);
      row.querySelector('[data-name]').textContent = category.category_name;
      row.querySelector('[data-amount]').textContent = formatPeso(category.amount);
      row.style.setProperty('--category-color', category.color);
      return row;
    }));

    // Donut: one arc per category on a circle whose circumference is 100, starting at 12 o'clock.
    const svgNS = 'http://www.w3.org/2000/svg';
    const ring = (color, dash, offset) => {
      const circle = document.createElementNS(svgNS, 'circle');
      circle.setAttribute('cx', '21');
      circle.setAttribute('cy', '21');
      circle.setAttribute('r', '15.9155');
      circle.setAttribute('fill', 'none');
      circle.setAttribute('stroke', color);
      circle.setAttribute('stroke-width', '6');
      circle.setAttribute('stroke-dasharray', dash);
      circle.setAttribute('stroke-dashoffset', String(offset));
      return circle;
    };
    const arcs = [ring('#e3e8e4', '100 0', 0)];
    let done = 0;
    for (const category of categories) {
      const share = spent ? (category.amount / spent) * 100 : 0;
      if (share > 0) arcs.push(ring(category.color, `${share} ${100 - share}`, 25 - done));
      done += share;
    }
    view.querySelector('[data-donut]').replaceChildren(...arcs);

    view.querySelector('[data-legend]').replaceChildren(...categories.map((category) => {
      const item = tpl('legend').cloneNode(true);
      const share = spent ? Math.round((category.amount / spent) * 100) : 0;
      item.querySelector('[data-swatch]').style.background = category.color;
      item.querySelector('[data-name]').textContent = `${category.category_name} ${share}%`;
      return item;
    }));
  }

  /** The expense list from the API (already newest first), filtered by the search box. */
  function renderTransactions() {
    const query = search.value.trim().toLowerCase();
    const shown = rows.filter((e) => !query || `${e.description ?? ''} ${e.category_name}`.toLowerCase().includes(query));

    txList.replaceChildren(...shown.slice(0, visible).map((e) => {
      const row = tpl('tx').cloneNode(true);
      const quantity = e.quantity ? ` · ${e.quantity} ${e.unit}` : '';
      const title = e.description || e.category_name;
      row.querySelector('[data-title]').textContent = title;
      row.querySelector('[data-date]').textContent = formatShortDate(parseISODate(e.expense_date));
      row.querySelector('[data-category]').textContent = e.category_name;
      row.querySelector('[data-plot]').textContent = `${e.field_name ?? 'Whole farm'}${quantity} · ${e.recorded_by_name}`;
      row.querySelector('[data-amount]').textContent = formatPeso(-e.amount_php);
      const remove = row.querySelector('[data-delete]');
      remove.hidden = !e.can_delete;
      remove.setAttribute('aria-label', `Delete ${title}`);
      remove.addEventListener('click', () => deleteExpense(e, title));
      return row;
    }));
    txEmpty.hidden = shown.length > 0;
    txMore.hidden = shown.length <= visible;
  }

  async function deleteExpense(expense, title) {
    if (!window.confirm(MESSAGES.deleteConfirm(title))) return;
    try {
      await expensesApi.remove(expense.expense_id);
      showToast(MESSAGES.deleted);
    } catch (err) {
      if (isSessionEnd(err)) return;
      const code = err instanceof ApiError ? err.code : null;
      setStatus(view, MESSAGES[code] ?? MESSAGES.deleteFailed, 'error');
    }
    load();
  }

  function seasonFilters() {
    const season = seasonFromKey(filters.seasonKey);
    return { season: season.season, season_year: season.year, field_id: filters.fieldId || null };
  }

  /** Summary and list for the chosen season and field. */
  async function load() {
    const id = ++requestId;
    const params = seasonFilters();
    try {
      const [summary, list] = await Promise.all([
        expensesApi.summary(farm.farm_id, params),
        expensesApi.list(farm.farm_id, params),
      ]);
      if (id !== requestId) return;
      rows = list ?? [];
      content.hidden = false;
      renderTotals(summary);
      renderCategories(summary);
      renderTransactions();
    } catch (err) {
      if (id !== requestId || isSessionEnd(err)) return;
      setStatus(view, MESSAGES.loadFailed, 'error');
    }
  }

  async function enter({ state } = {}) {
    const id = ++requestId;
    visible = PAGE_SIZE;
    search.value = '';
    setStatus(view, '');
    view.querySelector('[data-empty]').hidden = true;
    try {
      const loaded = await loadFirstFarm();
      if (id !== requestId) return;
      farm = loaded.farm;
      const hasFields = Boolean(farm) && loaded.fields.length > 0;
      view.querySelector('.picker-row').hidden = !hasFields;
      recordHarvest.hidden = farm?.role_on_farm !== 'owner';
      if (!hasFields) {
        content.hidden = true;
        showEmpty(view, MESSAGES.noFarm);
        return;
      }
      renderPickers(loaded.fields);
      // A message from Add Expense or Harvest Entry.
      if (state?.message) setStatus(view, state.message, 'success');
      await load();
    } catch (err) {
      if (id !== requestId || isSessionEnd(err)) return;
      content.hidden = true;
      setStatus(view, MESSAGES.loadFailed, 'error');
    }
  }

  seasonPicker.addEventListener('change', () => {
    filters.seasonKey = seasonPicker.value;
    visible = PAGE_SIZE;
    setStatus(view, '');
    load();
  });
  plotPicker.addEventListener('change', () => {
    filters.fieldId = plotPicker.value;
    visible = PAGE_SIZE;
    setStatus(view, '');
    load();
  });
  search.addEventListener('input', () => {
    visible = PAGE_SIZE;
    renderTransactions();
  });
  txMore.addEventListener('click', () => {
    visible += PAGE_SIZE;
    renderTransactions();
  });
  view.querySelector('[data-view-all]').addEventListener('click', () => {
    visible = Infinity;
    renderTransactions();
    txList.closest('section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  router.route('expenses', { onEnter: enter });
}

/* ---------- Add expense ---------- */

function mountExpenseForm(router) {
  const view = document.querySelector('[data-view="expense-new"]');
  const form = document.getElementById('expense-form');
  const categoryBox = view.querySelector('[data-category-options]');
  const categoryError = view.querySelector('[data-category-error]');
  const {
    amount_php: amount,
    description,
    expense_date: date,
    quantity,
    unit,
    plot,
    season_key: seasonSelect,
  } = form.elements;
  const seasonField = view.querySelector('[data-season-field]');
  let farm = null;
  let clientUuid = null;
  let seasonTouched = false;
  let categoriesRequest = null;

  /** Category tiles from GET /expense-categories, loaded once; icons come from farm-options.js. */
  async function renderCategories() {
    categoriesRequest ??= expensesApi.categories().catch((err) => {
      categoriesRequest = null;
      throw err;
    });
    const categories = await categoriesRequest;
    categoryBox.replaceChildren(...categories.map((category) => {
      const option = document.createElement('label');
      option.className = 'crop-option';
      const input = Object.assign(document.createElement('input'), {
        className: 'crop-option__input',
        type: 'radio',
        name: 'category_id',
        value: String(category.category_id),
      });
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      icon.setAttribute('class', 'crop-option__icon');
      icon.setAttribute('aria-hidden', 'true');
      const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
      use.setAttribute('href', `#${categoryStyle(category.category_name).icon}`);
      icon.append(use);
      const label = Object.assign(document.createElement('span'), {
        className: 'crop-option__label',
        textContent: category.category_name,
      });
      option.append(input, icon, label);
      return option;
    }));
  }

  for (const option of QUANTITY_UNITS) unit.add(new Option(option.label, option.value));

  /** A whole-farm expense picks its season, suggested from the date until changed by hand. */
  function syncSeason() {
    seasonField.hidden = plot.value !== WHOLE_FARM;
    const day = parseISODate(date.value) ?? philippineToday();
    const suggested = seasonForDate(day);
    const seasons = seasonChoices();
    if (!seasons.some((s) => s.key === suggested.key)) seasons.push(suggested);
    const keep = seasonTouched ? seasonSelect.value : suggested.key;
    fillSeasons(seasonSelect, seasons, seasons[1]);
    seasonSelect.value = seasons.some((s) => s.key === keep) ? keep : suggested.key;
  }
  plot.addEventListener('change', syncSeason);
  date.addEventListener('change', syncSeason);
  seasonSelect.addEventListener('change', () => { seasonTouched = true; });
  const categoryRadios = () => [...form.querySelectorAll('input[name="category_id"]')];
  bindLiveErrorClearing(form);

  // The category is a radio group, so its error is set on every radio and shown once.
  function setCategoryError(message) {
    for (const radio of categoryRadios()) {
      if (message) radio.setAttribute('aria-invalid', 'true');
      else radio.removeAttribute('aria-invalid');
    }
    categoryError.textContent = message;
  }
  categoryBox.addEventListener('change', () => setCategoryError(''));

  function validate() {
    const categoryId = Number(form.elements.category_id.value);
    const rawAmount = amount.value.trim().replace(/,/g, '');
    const value = Number(rawAmount);
    const day = parseISODate(date.value);
    const qty = quantity.value.trim() ? Number(quantity.value) : null;

    if (!categoryId) setCategoryError(MESSAGES.categoryRequired);
    if (!rawAmount) setFieldError(amount, MESSAGES.amountRequired);
    else if (!/^\d+(\.\d{1,2})?$/.test(rawAmount) || value <= 0) setFieldError(amount, MESSAGES.amountInvalid);
    else if (value > MAX_AMOUNT) setFieldError(amount, MESSAGES.amountTooLarge);
    if (!day) setFieldError(date, MESSAGES.dateRequired);
    else if (day > philippineToday()) setFieldError(date, MESSAGES.dateFuture);
    const rawQty = quantity.value.trim();
    if (rawQty && (!/^\d+(\.\d{1,2})?$/.test(rawQty) || !(qty > 0) || qty > MAX_AMOUNT)) {
      setFieldError(quantity, MESSAGES.quantityInvalid);
    }
    if (!plot.value) setFieldError(plot, MESSAGES.plotRequired);
    else if (plot.value === WHOLE_FARM && !seasonSelect.value) setFieldError(seasonSelect, MESSAGES.seasonRequired);

    if (form.querySelector('[aria-invalid="true"]')) return null;
    const payload = {
      category_id: categoryId,
      amount_php: Math.round(value * 100) / 100,
      expense_date: date.value,
      description: description.value.trim().replace(/\s+/g, ' ') || null,
      quantity: qty,
      unit: qty === null ? null : unit.value,
      client_uuid: clientUuid,
    };
    if (plot.value === WHOLE_FARM) {
      const season = seasonFromKey(seasonSelect.value);
      Object.assign(payload, { season: season.season, season_year: season.year });
    } else {
      payload.cycle_id = Number(plot.value);
    }
    return payload;
  }

  // Each POST error code is shown under the field it is about, or above the button.
  function showSaveError(err) {
    const code = err instanceof ApiError ? err.code : null;
    const targets = {
      cycle_not_in_farm: plot,
      season_mismatch: plot,
      season_required: seasonSelect,
      unit_required: quantity,
      quantity_required: quantity,
      expense_date_in_future: date,
    };
    if (code === 'category_not_found') {
      categoriesRequest = null;
      setCategoryError(MESSAGES.category_not_found);
      renderCategories().catch(() => {});
    } else if (targets[code]) {
      setFieldError(targets[code], MESSAGES[code]);
      focusFirstInvalid(form);
    } else if (code === 'client_uuid_taken') {
      // The phone's id was used elsewhere; a fresh one lets the next press save it.
      clientUuid = newClientUuid();
      setStatus(view, MESSAGES.client_uuid_taken, 'error');
    } else {
      setStatus(view, MESSAGES[code] ?? err.message, 'error');
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true' || !farm) return;
    clearFieldErrors(form);
    setCategoryError('');
    setStatus(view, '');
    const payload = validate();
    if (!payload) {
      focusFirstInvalid(form);
      return;
    }

    setBusy(form, true);
    try {
      // A retry after a lost connection resends the same client_uuid, so it is saved once.
      const saved = await expensesApi.create(farm.farm_id, payload);
      clientUuid = null;
      showSeasonNext(seasonOf(saved.season, saved.season_year));
      router.navigate('expenses', { replace: true, state: { message: MESSAGES.saved } });
    } catch (err) {
      if (!isSessionEnd(err)) showSaveError(err);
    } finally {
      setBusy(form, false);
    }
  });

  view.querySelector('[data-cancel]').addEventListener('click', () => router.back('expenses'));

  router.route('expense-new', {
    async onEnter() {
      form.reset();
      clearFieldErrors(form);
      setCategoryError('');
      setStatus(view, '');
      clientUuid = newClientUuid();
      seasonTouched = false;
      date.value = toISODate(philippineToday());
      date.max = date.value;
      unit.value = 'kg';
      try {
        const [loaded] = await Promise.all([loadFirstFarm(), renderCategories()]);
        farm = loaded.farm;
        // Plots: each field's current crop cycle, plus the whole farm.
        const fields = loaded.fields.filter((f) => f.current_cycle);
        view.querySelector('[data-empty]').hidden = Boolean(farm && loaded.fields.length);
        form.hidden = !farm || !loaded.fields.length;
        plot.replaceChildren(
          new Option('Select a field', ''),
          ...fields.map((f) => new Option(
            `${f.field_name} · ${f.current_cycle.crop_name}`,
            String(f.current_cycle.cycle_id),
          )),
          new Option('Whole farm', WHOLE_FARM),
        );
        syncSeason();
      } catch (err) {
        if (!isSessionEnd(err)) setStatus(view, MESSAGES.loadFailed, 'error');
      }
    },
  });
}

/* ---------- Public entry ---------- */

export function mountExpensePages(router) {
  mountExpenses(router);
  mountExpenseForm(router);
}
