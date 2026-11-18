// frontend/public/js/pages/farm-report.js

/**
 * Farm Report (DFD 7.5; GET /farms/{farm_id}/report): the farm owner's season report, one
 * card per crop cycle of the season and the season totals, which match Farm Expenses.
 * Only the owner sees it; another member of the farm gets the not_farm_owner message.
 */
import { ApiError, farms } from '../api/client.js';
import { formatPeso } from '../utils/farm.js';
import { setStatus } from '../utils/form.js';
import { seasonChoices } from './expenses.js';

const MESSAGES = {
  subtitle: (farmName) => `${farmName}: yield, costs and crop health per field.`,
  noFarm: 'Set up your farm first.',
  notOwner: 'Only the farm owner can see the farm report.',
  noHarvest: 'No harvest yet',
  none: 'None',
  wholeFarm: (amount) => `includes ${amount} whole-farm expenses`,
  current: (short) => `${short} (current)`,
};

const STATUS_LABELS = { planned: 'Planned', active: 'Active', harvested: 'Harvested', failed: 'Failed' };

function formatNumber(value, digits = 2) {
  return Number(value).toLocaleString('en-PH', { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

function formatKg(value) {
  return `${formatNumber(value)} kg`;
}

/** Appends label/value pairs to a <dl>; a pair may carry a note under its value. */
function fillRows(list, rows) {
  list.replaceChildren(...rows.flatMap(({ label, value, note, tone }) => {
    const term = document.createElement('dt');
    term.textContent = label;
    const detail = document.createElement('dd');
    detail.textContent = value;
    if (tone) detail.dataset.tone = tone;
    if (note) {
      const small = document.createElement('small');
      small.textContent = note;
      detail.append(small);
    }
    return [term, detail];
  }));
}

function profitTone(value) {
  return value < 0 ? 'negative' : undefined;
}

export function mountFarmReportPage(router) {
  const view = document.querySelector('[data-view="farm-report"]');
  const subtitle = view.querySelector('[data-report-subtitle]');
  const seasonPicker = view.querySelector('[data-season-picker]');
  const empty = view.querySelector('[data-empty]');
  const emptyText = view.querySelector('[data-empty-text]');
  const emptySetup = view.querySelector('[data-empty-setup]');
  const content = view.querySelector('[data-content]');
  const totals = view.querySelector('[data-totals]');
  const fieldList = view.querySelector('[data-field-list]');
  const noCycles = view.querySelector('[data-no-cycles]');
  const tpl = view.querySelector('template[data-field-tpl]').content.firstElementChild;

  let farm = null;
  let requestId = 0;

  function showEmpty(message, { setup = false } = {}) {
    content.hidden = true;
    empty.hidden = false;
    emptyText.textContent = message;
    emptySetup.hidden = !setup;
  }

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

  function fieldCard(entry) {
    const card = tpl.cloneNode(true);
    card.querySelector('[data-field-name]').textContent = entry.field_name;
    card.querySelector('[data-crop]').textContent = `${entry.crop_name} · ${entry.variety_name}`;
    const status = card.querySelector('[data-status]');
    status.textContent = STATUS_LABELS[entry.status] ?? entry.status;
    status.dataset.status = entry.status;
    const scans = entry.scans;
    fillRows(card.querySelector('[data-rows]'), [
      { label: 'Area (ha)', value: formatNumber(entry.area_ha, 4) },
      { label: 'Expenses', value: formatPeso(entry.expenses_php) },
      { label: 'Harvest (kg)', value: formatNumber(entry.harvest_kg) },
      { label: 'Income', value: formatPeso(entry.gross_income_php) },
      { label: 'Net profit', value: formatPeso(entry.net_profit_php), tone: profitTone(entry.net_profit_php) },
      {
        label: 'Yield (t/ha)',
        value: entry.actual_yield_t_ha == null ? MESSAGES.noHarvest : formatNumber(entry.actual_yield_t_ha),
      },
      { label: 'Tasks done (%)', value: `${entry.task_completion_pct}%` },
      { label: 'Scans', value: `${scans.diseased} / ${scans.healthy} / ${scans.unrecognized}` },
      { label: 'Most found', value: entry.top_disease ?? MESSAGES.none },
    ]);
    return card;
  }

  function render(report) {
    subtitle.textContent = MESSAGES.subtitle(report.farm_name);
    const t = report.totals;
    fillRows(totals, [
      { label: 'Area', value: `${formatNumber(t.area_ha, 4)} ha` },
      {
        label: 'Expenses',
        value: formatPeso(t.expenses_php),
        note: t.whole_farm_expenses_php > 0 ? MESSAGES.wholeFarm(formatPeso(t.whole_farm_expenses_php)) : '',
      },
      { label: 'Harvest', value: formatKg(t.harvest_kg) },
      { label: 'Income', value: formatPeso(t.gross_income_php) },
      { label: 'Net profit', value: formatPeso(t.net_profit_php), tone: profitTone(t.net_profit_php) },
    ]);
    fieldList.replaceChildren(...report.fields.map(fieldCard));
    noCycles.hidden = report.fields.length > 0;
    empty.hidden = true;
    content.hidden = false;
  }

  async function load() {
    const id = (requestId += 1);
    setStatus(view, '');
    const [season, year] = seasonPicker.value.split('-');
    try {
      if (!farm) {
        const list = await farms.list();
        if (id !== requestId) return;
        farm = Array.isArray(list) ? list[0] ?? null : null;
      }
      if (!farm) {
        subtitle.textContent = '';
        showEmpty(MESSAGES.noFarm, { setup: true });
        return;
      }
      subtitle.textContent = MESSAGES.subtitle(farm.farm_name);
      const report = await farms.report(farm.farm_id, { season, season_year: year });
      if (id !== requestId) return;
      render(report);
    } catch (err) {
      if (id !== requestId || (err instanceof ApiError && err.sessionEnded)) return;
      if (err instanceof ApiError && err.code === 'not_farm_owner') showEmpty(MESSAGES.notOwner);
      else {
        content.hidden = true;
        setStatus(view, err.message, 'error');
      }
    }
  }

  seasonPicker.addEventListener('change', load);

  router.route('farm-report', {
    onEnter() {
      farm = null; // the farm or its owner may have changed since the last visit
      fillSeasonPicker();
      load();
    },
    onLeave() {
      requestId += 1;
    },
  });
}
