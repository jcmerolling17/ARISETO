// frontend/public/js/pages/harvest.js

/**
 * Harvest Entry (POST /cycles/{cycle_id}/harvests), opened from Farm Expenses by the farm owner.
 * The cycle picker lists the farm's planned or active cycles sown today or earlier; a final
 * harvest closes the cycle. Saving returns to Farm Expenses, showing the cycle's season.
 */
import { harvests, ApiError } from '../api/client.js';
import { cycleSeason, formatPeso } from '../utils/farm.js';
import { parseISODate, philippineToday, toISODate } from '../utils/dates.js';
import {
  setFieldError,
  clearFieldErrors,
  setStatus,
  setBusy,
  focusFirstInvalid,
  bindLiveErrorClearing,
} from '../utils/form.js';
import { loadFirstFarm, showSeasonNext } from './expenses.js';

const MAX_VALUE = 99999999.99; // quantity_kg and unit_price_php NUMERIC(10,2)
const MAX_GROSS = 9999999999.99; // gross_income_php NUMERIC(12,2)
const MONEY_RE = /^\d+(\.\d{1,2})?$/;

const MESSAGES = {
  noneReady: 'No crop is ready to harvest yet.',
  noFarm: 'No fields yet. Set up your farm to record harvests.',
  loadFailed: 'Your crops could not be loaded. Check your connection and try again.',
  cycleRequired: 'Choose the crop cycle.',
  dateRequired: 'Enter the harvest date.',
  dateOutOfRange: 'Enter a date between the sowing date and today.',
  quantityInvalid: 'Enter the quantity in kg, greater than 0, with up to 2 decimals.',
  priceInvalid: 'Enter the price per kg, greater than 0, with up to 2 decimals.',
  grossTooLarge: 'Quantity times price is too large. Check the numbers.',
  saved: 'Harvest saved.',
  savedFinal: 'Harvest saved. This crop cycle is now closed.',
  // POST /cycles/{cycle_id}/harvests error codes, as short plain messages.
  cycle_not_found: 'This crop cycle could not be found. Go back and try again.',
  not_farm_owner: 'Only the farm owner can record harvests.',
  cycle_closed: 'This crop cycle is already closed.',
  harvest_date_out_of_range: 'Enter a date between the sowing date and today.',
};

const SEASON_NAMES = { wet: 'Wet Season', dry: 'Dry Season' };

function isSessionEnd(err) {
  return err instanceof ApiError && err.sessionEnded;
}

/** A positive amount with up to 2 decimals and at most `max`, or null. */
function toAmount(raw, max = MAX_VALUE) {
  const text = String(raw).trim().replace(/,/g, '');
  const value = Number(text);
  return MONEY_RE.test(text) && value > 0 && value <= max ? value : null;
}

export function mountHarvestPage(router) {
  const view = document.querySelector('[data-view="harvest-new"]');
  const form = document.getElementById('harvest-form');
  const empty = view.querySelector('[data-empty]');
  const gross = view.querySelector('[data-gross]');
  const {
    cycle_id: cyclePicker,
    harvest_date: date,
    quantity_kg: quantity,
    unit_price_php: price,
    final_harvest: finalHarvest,
  } = form.elements;
  let cycles = new Map();

  bindLiveErrorClearing(form);

  function showEmpty(message) {
    empty.hidden = false;
    view.querySelector('[data-empty-text]').textContent = message;
    form.hidden = true;
  }

  // The date must fall between the chosen cycle's sowing date and today.
  function limitDate() {
    const cycle = cycles.get(Number(cyclePicker.value));
    date.min = cycle?.planting_date ?? '';
    date.max = toISODate(philippineToday());
  }

  function updateGross() {
    const kg = toAmount(quantity.value);
    const each = toAmount(price.value);
    gross.value = kg !== null && each !== null ? formatPeso(Math.round(kg * each * 100) / 100) : '';
  }

  function clear() {
    form.reset();
    clearFieldErrors(form);
    setStatus(view, '');
    date.value = toISODate(philippineToday());
    limitDate();
    updateGross();
  }

  cyclePicker.addEventListener('change', limitDate);
  quantity.addEventListener('input', updateGross);
  price.addEventListener('input', updateGross);
  view.querySelector('[data-clear]').addEventListener('click', clear);

  function validate() {
    const cycle = cycles.get(Number(cyclePicker.value));
    const day = parseISODate(date.value);
    const kg = toAmount(quantity.value);
    const each = toAmount(price.value);

    if (!cycle) setFieldError(cyclePicker, MESSAGES.cycleRequired);
    if (!day) setFieldError(date, MESSAGES.dateRequired);
    else if ((cycle && date.value < cycle.planting_date) || day > philippineToday()) {
      setFieldError(date, MESSAGES.dateOutOfRange);
    }
    if (kg === null) setFieldError(quantity, MESSAGES.quantityInvalid);
    if (each === null) setFieldError(price, MESSAGES.priceInvalid);
    else if (kg !== null && kg * each > MAX_GROSS) setFieldError(price, MESSAGES.grossTooLarge);

    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      cycle,
      body: {
        harvest_date: date.value,
        quantity_kg: kg,
        unit_price_php: each,
        final_harvest: finalHarvest.checked,
      },
    };
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;
    clearFieldErrors(form);
    setStatus(view, '');
    const values = validate();
    if (!values) {
      focusFirstInvalid(form);
      return;
    }

    setBusy(form, true);
    try {
      const saved = await harvests.record(values.cycle.cycle_id, values.body);
      showSeasonNext(cycleSeason(values.cycle));
      const message = saved.cycle_status === 'harvested' ? MESSAGES.savedFinal : MESSAGES.saved;
      router.navigate('expenses', { replace: true, state: { message } });
    } catch (err) {
      if (isSessionEnd(err)) return;
      const code = err instanceof ApiError ? err.code : null;
      if (code === 'harvest_date_out_of_range') {
        setFieldError(date, MESSAGES[code]);
        focusFirstInvalid(form);
      } else {
        setStatus(view, MESSAGES[code] ?? err.message, 'error');
      }
    } finally {
      setBusy(form, false);
    }
  });

  async function enter() {
    empty.hidden = true;
    form.hidden = true;
    setStatus(view, '');
    const loadStatus = view.querySelector('[data-load-status]');
    loadStatus.textContent = '';
    try {
      const { farm, fields } = await loadFirstFarm();
      // Only the farm owner records harvests; others go back to Farm Expenses.
      if (farm && farm.role_on_farm !== 'owner') {
        router.navigate('expenses', { replace: true });
        return;
      }
      if (!farm || !fields.length) {
        showEmpty(MESSAGES.noFarm);
        return;
      }
      const today = toISODate(philippineToday());
      const ready = fields
        .filter((f) => f.current_cycle && f.current_cycle.planting_date <= today)
        .map((f) => ({ ...f.current_cycle, field_name: f.field_name }));
      if (!ready.length) {
        showEmpty(MESSAGES.noneReady);
        return;
      }
      cycles = new Map(ready.map((c) => [c.cycle_id, c]));
      // 'Wet Season - Rice (Field A)', as in the design.
      cyclePicker.replaceChildren(
        new Option('Choose the crop cycle', ''),
        ...ready.map((c) => new Option(
          `${SEASON_NAMES[c.season]} - ${c.crop_name} (${c.field_name})`,
          String(c.cycle_id),
        )),
      );
      form.hidden = false;
      clear();
      if (ready.length === 1) {
        cyclePicker.value = String(ready[0].cycle_id);
        limitDate();
      }
    } catch (err) {
      if (!isSessionEnd(err)) {
        loadStatus.textContent = MESSAGES.loadFailed;
        loadStatus.dataset.tone = 'error';
      }
    }
  }

  router.route('harvest-new', { onEnter: enter });
}
