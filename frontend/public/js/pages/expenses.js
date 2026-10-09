// frontend/public/js/pages/expenses.js

import { sampleFarm, emptyFarm } from '../data/sample-farm.js';
import { sampleExpenses, emptyExpenses } from '../data/sample-expenses.js';
import { EXPENSE_CATEGORIES, QUANTITY_UNITS } from '../data/farm-options.js';
import { pickDemo } from '../utils/demo.js';
import { showToast } from '../utils/toast.js';
import { currentCycle, cycleSeason, fieldLabel, formatPeso, seasonOf } from '../utils/farm.js';
import { formatShortDate, parseISODate, startOfDay, toISODate } from '../utils/dates.js';
import {
  setFieldError,
  clearFieldErrors,
  focusFirstInvalid,
  bindLiveErrorClearing,
} from '../utils/form.js';

const PAGE_SIZE = 5;
const MAX_AMOUNT = 99999999.99; // EXPENSE.amount_php NUMERIC(10,2)
const WHOLE_FARM = 'farm';
const ALL_FIELDS = 'all';

const MESSAGES = {
  noFarm: 'No fields yet. Set up your farm to track its expenses.',
  noIncomeYet: 'No harvest income yet this season.',
  categoryRequired: 'Choose an expense category.',
  amountRequired: 'Enter the amount.',
  amountInvalid: 'Enter an amount greater than 0, with up to 2 decimals.',
  amountTooLarge: 'This amount is too large. Check the number.',
  dateRequired: 'Enter the date.',
  dateFuture: 'The date cannot be in the future.',
  quantityInvalid: 'Enter a quantity greater than 0.',
  plotRequired: 'Choose the plot this expense is for.',
  saved: 'Expense saved.',
};

/** Season and field shown on Farm Expenses; the add form returns to its saved season. */
const filters = { seasonKey: null, plot: ALL_FIELDS };

function data() {
  return { farm: pickDemo(sampleFarm, emptyFarm), money: pickDemo(sampleExpenses, emptyExpenses) };
}

function categoryOf(id) {
  return EXPENSE_CATEGORIES.find((c) => c.category_id === id) ?? EXPENSE_CATEGORIES[EXPENSE_CATEGORIES.length - 1];
}

/** Season of an expense: its cycle's season, or the farm + season stored on a whole-farm expense. */
function expenseSeason(farm, expense) {
  if (expense.cycle_id == null) return seasonOf(expense.season, expense.season_year);
  const cycle = farm.cycles.find((c) => c.cycle_id === expense.cycle_id);
  return cycle ? cycleSeason(cycle) : null;
}

/** Seasons with cycles or expenses, newest first (wet comes after dry in the same year). */
function seasonsOf(farm, money) {
  const seasons = new Map();
  for (const cycle of farm.cycles) {
    const season = cycleSeason(cycle);
    seasons.set(season.key, season);
  }
  for (const expense of money.expenses) {
    const season = expenseSeason(farm, expense);
    if (season) seasons.set(season.key, season);
  }
  const rank = (s) => s.year * 2 + (s.season === 'wet' ? 1 : 0);
  return [...seasons.values()].sort((a, b) => rank(b) - rank(a));
}

/** Season of the crops growing now, or null when nothing is planted. */
function currentSeason(farm) {
  const cycle = farm.fields.map((f) => currentCycle(farm, f.field_id)).find(Boolean);
  return cycle ? cycleSeason(cycle) : null;
}

function plotLabel(farm, expense) {
  if (expense.cycle_id == null) return 'Whole farm';
  const cycle = farm.cycles.find((c) => c.cycle_id === expense.cycle_id);
  return farm.fields.find((f) => f.field_id === cycle?.field_id)?.field_name ?? '';
}

function inPlot(farm, cycleId) {
  if (filters.plot === ALL_FIELDS) return true;
  if (filters.plot === WHOLE_FARM) return cycleId == null;
  const cycle = farm.cycles.find((c) => c.cycle_id === cycleId);
  return cycle?.field_id === Number(filters.plot);
}

function showEmpty(view, message) {
  view.querySelector('[data-empty]').hidden = false;
  view.querySelector('[data-empty-text]').textContent = message;
}

/* ---------- Farm Expenses ---------- */

function mountExpenses() {
  const view = document.querySelector('[data-view="expenses"]');
  const content = view.querySelector('[data-content]');
  const seasonPicker = view.querySelector('[data-season-picker]');
  const plotPicker = view.querySelector('[data-field-filter]');
  const search = view.querySelector('[data-tx-search]');
  const txList = view.querySelector('[data-tx-list]');
  const txEmpty = view.querySelector('[data-tx-empty]');
  const txMore = view.querySelector('[data-tx-more]');
  const tpl = (name) => view.querySelector(`template[data-${name}-tpl]`).content.firstElementChild;
  let visible = PAGE_SIZE;

  function renderPickers(farm, seasons) {
    const current = currentSeason(farm);
    seasonPicker.replaceChildren(...seasons.map((s) => {
      const option = new Option(s.key === current?.key ? `${s.short} (current)` : s.short, s.key);
      option.setAttribute('aria-label', s.label);
      return option;
    }));
    if (!seasons.some((s) => s.key === filters.seasonKey)) filters.seasonKey = current?.key ?? seasons[0]?.key ?? null;
    seasonPicker.value = filters.seasonKey ?? '';

    plotPicker.replaceChildren(
      new Option('All fields', ALL_FIELDS),
      ...farm.fields.map((f) => new Option(fieldLabel(farm, f), String(f.field_id))),
      new Option('Whole farm', WHOLE_FARM),
    );
    if (![...plotPicker.options].some((o) => o.value === filters.plot)) filters.plot = ALL_FIELDS;
    plotPicker.value = filters.plot;
  }

  function renderTotals(expenses, income, isCurrent) {
    const spent = expenses.reduce((sum, e) => sum + e.amount_php, 0);
    const earned = income.reduce((sum, h) => sum + h.gross_income_php, 0);
    const net = earned - spent;
    const total = (name) => view.querySelector(`[data-total="${name}"]`);

    total('expense').textContent = formatPeso(spent);
    total('income').textContent = formatPeso(earned);
    total('net').textContent = formatPeso(net);
    total('net').classList.toggle('is-negative', net < 0);
    view.querySelector('[data-net-note]').textContent = isCurrent && earned === 0 ? MESSAGES.noIncomeYet : '';
    view.querySelector('[data-donut-value]').textContent = formatPeso(net);
    return spent;
  }

  function renderCategories(expenses, spent) {
    const totals = new Map(EXPENSE_CATEGORIES.map((c) => [c.category_id, 0]));
    for (const e of expenses) totals.set(e.category_id, totals.get(e.category_id) + e.amount_php);

    view.querySelector('[data-category-list]').replaceChildren(...EXPENSE_CATEGORIES.map((category) => {
      const row = tpl('category').cloneNode(true);
      row.querySelector('[data-icon]').setAttribute('href', `#${category.icon}`);
      row.querySelector('[data-name]').textContent = category.category_name;
      row.querySelector('[data-amount]').textContent = formatPeso(totals.get(category.category_id));
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
    for (const category of EXPENSE_CATEGORIES) {
      const share = spent ? (totals.get(category.category_id) / spent) * 100 : 0;
      if (share > 0) arcs.push(ring(category.color, `${share} ${100 - share}`, 25 - done));
      done += share;
    }
    view.querySelector('[data-donut]').replaceChildren(...arcs);

    view.querySelector('[data-legend]').replaceChildren(...EXPENSE_CATEGORIES.map((category) => {
      const item = tpl('legend').cloneNode(true);
      const share = spent ? Math.round((totals.get(category.category_id) / spent) * 100) : 0;
      item.querySelector('[data-swatch]').style.background = category.color;
      item.querySelector('[data-name]').textContent = `${category.category_name} ${share}%`;
      return item;
    }));
  }

  function renderTransactions(farm, expenses) {
    const query = search.value.trim().toLowerCase();
    const rows = expenses
      .filter((e) => !query || `${e.description ?? ''} ${categoryOf(e.category_id).category_name}`.toLowerCase().includes(query))
      .sort((a, b) => b.expense_date.localeCompare(a.expense_date) || b.expense_id - a.expense_id);

    txList.replaceChildren(...rows.slice(0, visible).map((e) => {
      const row = tpl('tx').cloneNode(true);
      const category = categoryOf(e.category_id);
      const quantity = e.quantity ? ` · ${e.quantity} ${e.unit}` : '';
      row.querySelector('[data-title]').textContent = e.description || category.category_name;
      row.querySelector('[data-date]').textContent = formatShortDate(parseISODate(e.expense_date));
      row.querySelector('[data-category]').textContent = category.category_name;
      row.querySelector('[data-plot]').textContent = `${plotLabel(farm, e)}${quantity}`;
      row.querySelector('[data-amount]').textContent = formatPeso(-e.amount_php);
      return row;
    }));
    txEmpty.hidden = rows.length > 0;
    txMore.hidden = rows.length <= visible;
  }

  function render() {
    const { farm, money } = data();
    view.querySelector('[data-empty]').hidden = true;
    if (!farm.fields.length) {
      content.hidden = true;
      seasonPicker.replaceChildren();
      plotPicker.replaceChildren();
      showEmpty(view, MESSAGES.noFarm);
      return;
    }
    content.hidden = false;

    const seasons = seasonsOf(farm, money);
    renderPickers(farm, seasons);
    const inSeason = (season) => season?.key === filters.seasonKey;
    const expenses = money.expenses.filter((e) => inSeason(expenseSeason(farm, e)) && inPlot(farm, e.cycle_id));
    const income = money.harvests.filter((h) => {
      const cycle = farm.cycles.find((c) => c.cycle_id === h.cycle_id);
      return cycle && inSeason(cycleSeason(cycle)) && inPlot(farm, h.cycle_id);
    });

    const spent = renderTotals(expenses, income, filters.seasonKey === currentSeason(farm)?.key);
    renderCategories(expenses, spent);
    renderTransactions(farm, expenses);
  }

  seasonPicker.addEventListener('change', () => {
    filters.seasonKey = seasonPicker.value;
    visible = PAGE_SIZE;
    render();
  });
  plotPicker.addEventListener('change', () => {
    filters.plot = plotPicker.value;
    visible = PAGE_SIZE;
    render();
  });
  search.addEventListener('input', () => {
    visible = PAGE_SIZE;
    render();
  });
  txMore.addEventListener('click', () => {
    visible += PAGE_SIZE;
    render();
  });
  view.querySelector('[data-view-all]').addEventListener('click', () => {
    visible = Infinity;
    render();
    txList.closest('section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  return {
    enter() {
      visible = PAGE_SIZE;
      search.value = '';
      render();
    },
  };
}

/* ---------- Add expense ---------- */

function mountExpenseForm(router) {
  const view = document.querySelector('[data-view="expense-new"]');
  const form = document.getElementById('expense-form');
  const categoryBox = view.querySelector('[data-category-options]');
  const categoryError = view.querySelector('[data-category-error]');
  const { amount_php: amount, description, expense_date: date, quantity, unit, plot } = form.elements;

  for (const category of EXPENSE_CATEGORIES) {
    const option = document.createElement('label');
    option.className = 'crop-option';
    option.innerHTML = `
      <input class="crop-option__input" type="radio" name="category_id" value="${category.category_id}">
      <svg class="crop-option__icon" aria-hidden="true"><use href="#${category.icon}"/></svg>
      <span class="crop-option__label">${category.category_name}</span>`;
    categoryBox.append(option);
  }
  for (const option of QUANTITY_UNITS) unit.add(new Option(option.label, option.value));
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
    else if (day > startOfDay()) setFieldError(date, MESSAGES.dateFuture);
    if (qty !== null && !(qty > 0)) setFieldError(quantity, MESSAGES.quantityInvalid);
    if (!plot.value) setFieldError(plot, MESSAGES.plotRequired);

    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      category_id: categoryId,
      amount_php: Math.round(value * 100) / 100,
      expense_date: date.value,
      description: description.value.trim().replace(/\s+/g, ' ') || null,
      quantity: qty,
      unit: qty === null ? null : unit.value,
      plot: plot.value,
    };
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    clearFieldErrors(form);
    setCategoryError('');
    const { farm, money } = data();
    const values = validate();
    if (!values) {
      focusFirstInvalid(form);
      return;
    }

    const { plot: plotValue, ...fields } = values;
    const record = {
      expense_id: Math.max(0, ...money.expenses.map((e) => e.expense_id)) + 1,
      cycle_id: null,
      recorded_by: 6,
      ...fields,
    };
    let season;
    if (plotValue === WHOLE_FARM) {
      const day = parseISODate(record.expense_date);
      season = currentSeason(farm) ?? seasonOf(seasonForDate(day), day.getFullYear());
      Object.assign(record, { farm_id: farm.farm.farm_id, season: season.season, season_year: season.year });
    } else {
      const cycle = currentCycle(farm, Number(plotValue));
      record.cycle_id = cycle.cycle_id;
      season = cycleSeason(cycle);
    }
    money.expenses.push(record);

    filters.seasonKey = season.key;
    filters.plot = ALL_FIELDS;
    showToast(MESSAGES.saved);
    router.navigate('expenses', { replace: true });
  });

  view.querySelector('[data-cancel]').addEventListener('click', () => router.back('expenses'));

  router.route('expense-new', {
    onEnter() {
      const { farm } = data();
      form.reset();
      clearFieldErrors(form);
      setCategoryError('');
      plot.replaceChildren(
        new Option('Select a field', ''),
        ...farm.fields
          .filter((f) => currentCycle(farm, f.field_id))
          .map((f) => new Option(fieldLabel(farm, f), String(f.field_id))),
        ...(farm.farm ? [new Option('Whole farm', WHOLE_FARM)] : []),
      );
      date.value = toISODate(startOfDay());
      unit.value = 'kg';
    },
  });
}

/** Philippine wet season runs June to November; used only when nothing is planted. */
function seasonForDate(day) {
  const month = day.getMonth() + 1;
  return month >= 6 && month <= 11 ? 'wet' : 'dry';
}

/* ---------- Public entry ---------- */

export function mountExpensePages(router) {
  const expenses = mountExpenses();
  mountExpenseForm(router);
  router.route('expenses', { onEnter: () => expenses.enter() });
}
