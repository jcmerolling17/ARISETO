// frontend/public/js/pages/yield.js

import { sampleFarm, emptyFarm } from '../data/sample-farm.js';
import { sampleYield, emptyYield } from '../data/sample-yield.js';
import { sampleExpenses, emptyExpenses } from '../data/sample-expenses.js';
import { pickDemo } from '../utils/demo.js';
import { currentCycle, fieldLabel, formatPeso, formatPesoShort, latestEstimate } from '../utils/farm.js';
import { formatShortDate } from '../utils/dates.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const CHART = { width: 320, height: 180, left: 36, right: 16, top: 24, bottom: 30 };

const MESSAGES = {
  noFarm: 'No fields yet. Set up your farm to estimate its yield.',
  noEstimate: 'No yield estimate for this field yet.',
};

const SEED_TYPES = { hybrid: 'Hybrid', certified: 'Certified seed', inbred: 'Inbred' };
const HEALTH = {
  healthy: { value: 'Healthy', note: 'No pests or disease found', warn: false },
  leaf_blight: { value: 'Leaf blight', note: 'Early signs found in a scan', warn: true },
};

/** Rain since planting, as mm per week: under 20 is low, over 80 is heavy. */
function rainLabel(rainfallMm, days) {
  if (!days) return 'No data yet';
  const perWeek = rainfallMm / (days / 7);
  if (perWeek < 20) return 'Low rain';
  if (perWeek > 80) return 'Heavy rain';
  return 'Adequate rain';
}

function formatTons(value) {
  return value.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function svg(name, attrs, text) {
  const el = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
  if (text != null) el.textContent = text;
  return el;
}

export function mountYieldPage(router) {
  const view = document.querySelector('[data-view="yield"]');
  const picker = view.querySelector('[data-yield-field]');
  const content = view.querySelector('[data-content]');
  const empty = view.querySelector('[data-empty]');
  const chart = view.querySelector('[data-history-chart]');
  const tpl = view.querySelector('template[data-factor-tpl]').content.firstElementChild;
  let fieldId = null;

  function data() {
    return {
      farm: pickDemo(sampleFarm, emptyFarm),
      yields: pickDemo(sampleYield, emptyYield),
      money: pickDemo(sampleExpenses, emptyExpenses),
    };
  }

  function showEmpty(message, setup) {
    content.hidden = true;
    empty.hidden = false;
    view.querySelector('[data-empty-text]').textContent = message;
    view.querySelector('[data-empty-setup]').hidden = !setup;
  }

  function renderFactors(estimate, money) {
    const f = estimate.input_features;
    const spent = money.expenses.filter((e) => e.cycle_id === estimate.cycle_id).reduce((sum, e) => sum + e.amount_php, 0);
    const health = HEALTH[f.crop_health] ?? HEALTH.healthy;
    const factors = [
      { icon: 'icon-seeds', name: 'Seeds', value: `${f.seed_kg} kg`, note: SEED_TYPES[f.seed_type] ?? f.seed_type },
      { icon: 'icon-fertilizer', name: 'Fertilizer', value: `${f.fertilizer_sacks} sacks`, note: f.fertilizer_sacks ? 'Applied so far' : 'Not applied yet' },
      { icon: 'icon-weather', name: 'Weather', value: rainLabel(f.rainfall_mm, f.days_after_planting), note: `${f.rainfall_mm} mm since planting` },
      { icon: 'icon-leaf', name: 'Health', value: health.value, note: health.note, warn: health.warn },
      { icon: 'icon-soil', name: 'Soil', value: f.soil_type[0].toUpperCase() + f.soil_type.slice(1), note: 'Soil type' },
      { icon: 'icon-wallet', name: 'Expenses', value: formatPeso(spent), note: 'This season so far' },
    ];
    view.querySelector('[data-factors]').replaceChildren(...factors.map((factor) => {
      const item = tpl.cloneNode(true);
      item.classList.toggle('factor--warn', Boolean(factor.warn));
      item.querySelector('[data-icon]').setAttribute('href', `#${factor.icon}`);
      item.querySelector('[data-name]').textContent = factor.name;
      item.querySelector('[data-value]').textContent = factor.value;
      item.querySelector('[data-note]').textContent = factor.note;
      return item;
    }));
  }

  /** Line chart of predicted_total_t, one point per estimate, x by date. */
  function renderHistory(estimates) {
    const rows = [...estimates].sort((a, b) => a.created_at.localeCompare(b.created_at));
    const times = rows.map((r) => new Date(r.created_at).getTime());
    const values = rows.map((r) => r.predicted_total_t);
    const top = Math.max(1, Math.ceil(Math.max(...values) * 1.25));
    const plotW = CHART.width - CHART.left - CHART.right;
    const plotH = CHART.height - CHART.top - CHART.bottom;
    const span = times[times.length - 1] - times[0];
    const x = (t) => CHART.left + (span ? ((t - times[0]) / span) * plotW : plotW / 2);
    const y = (v) => CHART.top + plotH - (v / top) * plotH;

    const parts = [];
    for (let i = 0; i <= 4; i += 1) {
      const v = (top / 4) * i;
      parts.push(svg('line', { x1: CHART.left, x2: CHART.width - CHART.right, y1: y(v), y2: y(v), class: 'history-chart__grid' }));
      parts.push(svg('text', { x: CHART.left - 6, y: y(v) + 4, 'text-anchor': 'end', class: 'history-chart__axis' }, Number(v.toFixed(1))));
    }
    const points = rows.map((r, i) => `${x(times[i])},${y(values[i])}`).join(' ');
    parts.push(svg('polyline', { points, class: 'history-chart__line' }));
    // Edge date labels hug the chart sides so they are not cut off.
    const anchorFor = (i) => {
      if (rows.length === 1) return 'middle';
      if (i === 0) return 'start';
      return i === rows.length - 1 ? 'end' : 'middle';
    };
    rows.forEach((r, i) => {
      const cx = x(times[i]);
      const anchor = anchorFor(i);
      parts.push(svg('circle', { cx, cy: y(values[i]), r: 4.5, class: 'history-chart__dot' }));
      parts.push(svg('text', { x: cx, y: y(values[i]) - 10, 'text-anchor': 'middle', class: 'history-chart__value' }, `${formatTons(values[i])} t`));
      parts.push(svg('text', { x: cx, y: CHART.height - 8, 'text-anchor': anchor, class: 'history-chart__axis' }, formatShortDate(new Date(r.created_at))));
    });
    chart.replaceChildren(...parts);
    chart.setAttribute('aria-label', `Estimated total harvest: ${rows.map((r) => `${formatShortDate(new Date(r.created_at))}, ${formatTons(r.predicted_total_t)} tons`).join('; ')}`);
  }

  function render() {
    const { farm, yields, money } = data();
    const fields = farm.fields.filter((f) => currentCycle(farm, f.field_id));
    picker.replaceChildren(...fields.map((f) => new Option(fieldLabel(farm, f), String(f.field_id))));
    picker.disabled = fields.length === 0;
    picker.closest('.field-picker').hidden = fields.length === 0;
    if (!fields.some((f) => f.field_id === fieldId)) fieldId = fields[0]?.field_id ?? null;
    if (!fields.length) return showEmpty(MESSAGES.noFarm, true);
    picker.value = String(fieldId);

    const cycle = currentCycle(farm, fieldId);
    const estimate = latestEstimate(yields, cycle);
    if (!estimate) return showEmpty(MESSAGES.noEstimate, false);
    content.hidden = false;
    empty.hidden = true;

    const at = new Date(estimate.created_at);
    view.querySelector('[data-total]').textContent = formatTons(estimate.predicted_total_t);
    view.querySelector('[data-per-ha]').textContent = `${estimate.predicted_yield_t_ha.toFixed(1)} t/ha`;
    view.querySelector('[data-value]').textContent = estimate.expected_value_php == null ? '—' : formatPesoShort(estimate.expected_value_php);
    view.querySelector('[data-estimated-at]').textContent = `Estimated ${formatShortDate(at)}, ${at.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' })} · for ${cycle.area_planted_ha} ha of ${cycle.crop_name.toLowerCase()}`;
    renderFactors(estimate, money);
    renderHistory(yields.estimates.filter((e) => e.cycle_id === cycle.cycle_id));
  }

  picker.addEventListener('change', () => {
    fieldId = Number(picker.value);
    render();
  });

  router.route('yield', { onEnter: render });
}
