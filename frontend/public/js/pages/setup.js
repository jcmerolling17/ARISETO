// frontend/public/js/pages/setup.js

import { farms, crops, ApiError } from '../api/client.js';
import { MUNICIPALITIES, SEASONS, CROPS, suggestedSeason } from '../data/farm-options.js';
import {
  setFieldError,
  clearFieldErrors,
  setStatus,
  setBusy,
  focusFirstInvalid,
  bindLiveErrorClearing,
} from '../utils/form.js';
import { saveJSON } from '../utils/store.js';
import { mountBarangayPicker } from '../utils/barangay-picker.js';

const MAX_AREA_HA = 999999.9999; // FARM.total_area_ha NUMERIC(10,4)
const MAX_FIELDS = 20;
const PLANTING_WINDOW_YEARS = 2; // CROP_CYCLE.planting_date: within 2 years of today

const MESSAGES = {
  farmNameRequired: 'Enter your farm name.',
  municipalityRequired: 'Choose the municipality where your farm is.',
  barangayRequired: 'Choose the barangay where your farm is.',
  fieldCountRequired: 'Enter how many fields your farm has.',
  fieldCountInvalid: `Enter a whole number from 1 to ${MAX_FIELDS}.`,
  seasonRequired: 'Choose the season.',
  fieldNameRequired: 'Enter a name for this field.',
  fieldNameTaken: 'You already have a field with this name.',
  cropRequired: 'Choose what you are planting.',
  varietyRequired: 'Choose the variety.',
  varietiesLoading: 'Loading varieties…',
  varietiesWait: 'Wait for the varieties to load, then choose one.',
  varietiesNone: 'No varieties for this crop yet',
  varietiesNoneError: 'There are no varieties for this crop yet. Please contact the MPMPC office.',
  varietiesFailed: 'Could not load the varieties. Check your connection, then choose the crop again.',
  sizeRequired: 'Enter the field size in hectares.',
  sizeInvalid: 'Enter a size greater than 0.',
  sizeTooSmall: 'This size is too small. Enter at least 0.0001 ha (1 m²).',
  sizeTooLarge: 'Your fields add up to more than ARISETO can store. Check the size.',
  plantingDateRequired: 'Enter the sowing date.',
  plantingDateInvalid: 'Enter a sowing date within two years of today.',
  removeConfirm: (name) => `Remove ${name} from your farm?`,
  fieldsNone: 'Add at least one field.',
  fieldsTooFew: (added, expected) =>
    `You said your farm has ${plural(expected, 'field')}, but you added ${added}. Add ${plural(expected - added, 'more field')}, or go back and change the number.`,
  fieldsTooMany: (added, expected) =>
    `You said your farm has ${plural(expected, 'field')}, but you added ${added}. Remove ${plural(added - expected, 'field')}, or go back and change the number.`,
  sessionExpired: 'Your session has expired. Please log in again.',
  accountDeactivated: 'Your account has been deactivated. Please contact the MPMPC office.',
  unexpected: 'The server returned an unexpected response. Please try again.',
};

/** Messages for the POST /farms error codes (Section 6). Nothing is saved when one occurs. */
const SAVE_ERRORS = {
  no_fields: 'Add at least one field before saving your farm.',
  field_name_taken: 'Two of your fields have the same name. Edit one so each field has its own name.',
  barangay_not_found: 'We could not find your barangay. Edit your farm details and choose your barangay again.',
  planting_date_out_of_range: 'A sowing date is more than two years from today. Edit the field and check its sowing date.',
  variety_not_found: 'A variety you chose is no longer on the list. Edit the field and choose its variety again.',
};

/**
 * farm:        step 1 answers { farm_name, barangay_id }, not yet sent
 * place:       municipality and barangay names, kept for display only
 * fieldCount:  how many fields the farmer said the farm has
 * season:      season shared by every field in this setup
 * fields:      fields added in steps 2–3:
 *              { key, field_name, crop, variety_id, variety_name, area_ha, planting_date }
 * editing:     key of the field open in step 2, or null when adding a new one
 * result:      the finished farm shown on the success screen
 */
const draft = {
  farm: null,
  place: null,
  fieldCount: 0,
  season: null,
  fields: [],
  editing: null,
  result: null,
};
let nextFieldKey = 1;

/* ---------- Helpers ---------- */

function fillSelect(select, options) {
  for (const option of options) {
    select.add(typeof option === 'string' ? new Option(option, option) : new Option(option.label, option.value));
  }
}

function cleanText(raw) {
  return String(raw).trim().replace(/\s+/g, ' ');
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

function roundHectares(value) {
  return Math.round(value * 10000) / 10000;
}

/** Hectares with 4 decimals; null when not a positive number. */
function toHectares(raw) {
  const value = Number(raw);
  if (!String(raw).trim() || !Number.isFinite(value) || value <= 0) return null;
  return roundHectares(value);
}

function formatHectares(value, { long = false } = {}) {
  const amount = roundHectares(value).toLocaleString('en-PH', { maximumFractionDigits: 4 });
  if (!long) return `${amount} ha`;
  return `${amount} ${value === 1 ? 'hectare' : 'hectares'}`;
}

function totalAreaHa() {
  return roundHectares(draft.fields.reduce((sum, field) => sum + field.area_ha, 0));
}

function cropOf(value) {
  return CROPS.find((crop) => crop.value === value);
}

function labelOf(options, value) {
  return options.find((option) => option.value === value)?.label ?? value;
}

function parseDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(date) {
  return date.toLocaleDateString('en-PH', { month: 'short', day: 'numeric', year: 'numeric' });
}

function toISODate(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** The same day `years` later or earlier; Feb 29 becomes Feb 28 in a common year. */
function yearsFrom(day, years) {
  const year = day.getFullYear() + years;
  const lastDay = new Date(year, day.getMonth() + 1, 0).getDate();
  return new Date(year, day.getMonth(), Math.min(day.getDate(), lastDay));
}

/** First and last allowed sowing dates, matching the backend's planting window. */
function plantingWindow(today = new Date()) {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return [yearsFrom(start, -PLANTING_WINDOW_YEARS), yearsFrom(start, PLANTING_WINDOW_YEARS)];
}

/**
 * Varieties per crop value ('rice', 'corn', 'onion') from GET /crops, loaded once.
 * A failed load is forgotten so the next call tries again.
 */
let varietiesRequest = null;
function loadVarieties() {
  varietiesRequest ??= crops.list().then((list) => {
    const byCrop = new Map();
    for (const crop of list ?? []) byCrop.set(String(crop.crop_name).toLowerCase(), crop.varieties ?? []);
    return byCrop;
  });
  varietiesRequest.catch(() => {
    varietiesRequest = null;
  });
  return varietiesRequest;
}

function forgetVarieties() {
  varietiesRequest = null;
}

function bindHomeButtons(view, router) {
  view.querySelectorAll('[data-go-home], [data-open-farm]').forEach((button) => {
    button.addEventListener('click', () => router.navigate('home'));
  });
}

/* ---------- Start ---------- */

function mountStart(router) {
  const view = document.querySelector('[data-view="setup"]');
  const nameEl = view.querySelector('[data-user-name]');

  bindHomeButtons(view, router);

  router.route('setup', {
    onEnter({ state } = {}) {
      const firstName = state?.user?.first_name;
      if (firstName) {
        nameEl.textContent = firstName;
        saveJSON('user', { first_name: firstName });
      }
    },
  });
}

/* ---------- Step 1: farm ---------- */

function mountFarmStep(router) {
  const form = document.getElementById('setup-farm-form');
  const { farm_name: farmName, municipality, barangay_id: barangay, field_count: fieldCount, season } = form.elements;
  const barangayPicker = mountBarangayPicker(municipality, barangay, {
    onChange: () => setFieldError(barangay, ''),
  });

  fillSelect(municipality, MUNICIPALITIES);
  fillSelect(season, SEASONS);
  // Suggested from today's date; the farmer can change it.
  season.value = suggestedSeason();
  bindLiveErrorClearing(form);

  function validate() {
    const name = cleanText(farmName.value);
    const place = barangayPicker.selected();
    const count = Number(fieldCount.value);

    if (!name) setFieldError(farmName, MESSAGES.farmNameRequired);
    if (!municipality.value) setFieldError(municipality, MESSAGES.municipalityRequired);
    else if (!place) setFieldError(barangay, MESSAGES.barangayRequired);
    if (!fieldCount.value.trim()) setFieldError(fieldCount, MESSAGES.fieldCountRequired);
    else if (!Number.isInteger(count) || count < 1 || count > MAX_FIELDS) {
      setFieldError(fieldCount, MESSAGES.fieldCountInvalid);
    }
    if (!season.value) setFieldError(season, MESSAGES.seasonRequired);

    if (form.querySelector('[aria-invalid="true"]')) return null;
    // The backend places the farm at its barangay's center point.
    return {
      farm: { farm_name: name, barangay_id: place.barangay_id },
      place: { municipality: municipality.value, barangay_name: place.barangay_name },
      fieldCount: count,
      season: season.value,
    };
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    clearFieldErrors(form);

    const answers = validate();
    if (!answers) {
      focusFirstInvalid(form);
      return;
    }

    farmName.value = answers.farm.farm_name;
    Object.assign(draft, answers);
    router.navigate(draft.fields.length ? 'setup-fields' : 'setup-field');
  });

  router.route('setup-farm', {
    onLeave() {
      clearFieldErrors(form);
    },
  });

  return {
    reset() {
      form.reset();
      barangayPicker.reset();
      season.value = suggestedSeason();
    },
  };
}

/** Steps 2 and 3 need step 1's answers. */
function fieldStepsGuard() {
  return draft.farm ? null : 'setup-farm';
}

/* ---------- Step 2: add or edit one field ---------- */

function mountFieldStep(router) {
  const view = document.querySelector('[data-view="setup-field"]');
  const form = document.getElementById('setup-field-form');
  const heading = view.querySelector('[data-field-heading]');
  const backLink = view.querySelector('[data-field-back]');
  const cropOptions = view.querySelector('[data-crop-options]');
  const cropError = view.querySelector('[data-crop-error]');
  const {
    field_name: fieldName,
    variety_id: variety,
    area_ha: size,
    planting_date: plantingDate,
  } = form.elements;

  for (const crop of CROPS) {
    const option = document.createElement('label');
    option.className = 'crop-option';
    option.innerHTML = `
      <input class="crop-option__input" type="radio" name="crop" value="${crop.value}">
      <svg class="crop-option__icon" aria-hidden="true"><use href="#${crop.icon}"/></svg>
      <span class="crop-option__label">${crop.label}</span>`;
    cropOptions.append(option);
  }
  const cropRadios = () => [...form.querySelectorAll('input[name="crop"]')];

  bindLiveErrorClearing(form);

  // The crop is a radio group, so its error is set on every radio and shown once.
  function setCropError(message) {
    for (const radio of cropRadios()) {
      if (message) radio.setAttribute('aria-invalid', 'true');
      else radio.removeAttribute('aria-invalid');
    }
    cropError.textContent = message;
  }

  // 'empty' (no crop), 'loading', 'none' (crop has no varieties), 'failed', or 'ready'.
  let varietyState = 'empty';
  const VARIETY_ERRORS = {
    loading: MESSAGES.varietiesWait,
    none: MESSAGES.varietiesNoneError,
    failed: MESSAGES.varietiesFailed,
    ready: MESSAGES.varietyRequired,
  };

  function setVarietyPlaceholder(text, state) {
    variety.replaceChildren(new Option(text, ''));
    variety.disabled = true;
    varietyState = state;
  }

  /** Fills the variety list for a crop from GET /crops, keeping selectedId if it is listed. */
  let varietyRequest = 0;
  async function fillVarieties(crop, selectedId = null) {
    const id = (varietyRequest += 1);
    if (!crop) {
      setVarietyPlaceholder('Choose a crop first', 'empty');
      return;
    }
    setVarietyPlaceholder(MESSAGES.varietiesLoading, 'loading');
    try {
      const varieties = (await loadVarieties()).get(crop) ?? [];
      if (id !== varietyRequest) return;
      if (!varieties.length) {
        setVarietyPlaceholder(MESSAGES.varietiesNone, 'none');
        return;
      }
      variety.replaceChildren(new Option('Choose variety', ''));
      for (const item of varieties) {
        const option = new Option(`${item.variety_name} · ${item.maturity_days} days`, String(item.variety_id));
        option.dataset.name = item.variety_name;
        variety.add(option);
      }
      variety.disabled = false;
      varietyState = 'ready';
      if (selectedId != null && varieties.some((item) => item.variety_id === selectedId)) {
        variety.value = String(selectedId);
      }
    } catch (err) {
      if (id !== varietyRequest) return;
      if (err instanceof ApiError && err.status === 401) {
        router.navigate('login', { state: { message: MESSAGES.sessionExpired, tone: 'error' } });
        return;
      }
      setVarietyPlaceholder('Choose a crop first', 'failed');
      setFieldError(variety, MESSAGES.varietiesFailed);
    }
  }

  cropOptions.addEventListener('change', () => {
    setCropError('');
    setFieldError(variety, '');
    fillVarieties(form.elements.crop.value);
  });

  // Keep the date picker inside the allowed sowing window.
  function limitPlantingDate() {
    const [first, last] = plantingWindow();
    plantingDate.min = toISODate(first);
    plantingDate.max = toISODate(last);
  }

  function clearErrors() {
    clearFieldErrors(form);
    setCropError('');
  }

  function validate() {
    const name = cleanText(fieldName.value);
    const crop = form.elements.crop.value;
    const varietyOption = variety.value ? variety.selectedOptions[0] : null;
    const others = draft.fields.filter((field) => field.key !== draft.editing);

    if (!name) setFieldError(fieldName, MESSAGES.fieldNameRequired);
    else if (others.some((field) => field.field_name.toLowerCase() === name.toLowerCase())) {
      setFieldError(fieldName, MESSAGES.fieldNameTaken);
    }
    if (!crop) setCropError(MESSAGES.cropRequired);
    else if (!varietyOption) setFieldError(variety, VARIETY_ERRORS[varietyState] ?? MESSAGES.varietyRequired);

    const areaHa = toHectares(size.value);
    const othersHa = others.reduce((sum, field) => sum + field.area_ha, 0);
    if (!size.value.trim()) setFieldError(size, MESSAGES.sizeRequired);
    else if (areaHa === null) setFieldError(size, MESSAGES.sizeInvalid);
    else if (areaHa === 0) setFieldError(size, MESSAGES.sizeTooSmall);
    else if (othersHa + areaHa > MAX_AREA_HA) setFieldError(size, MESSAGES.sizeTooLarge);

    const date = parseDate(plantingDate.value);
    const [first, last] = plantingWindow();
    if (!plantingDate.value) setFieldError(plantingDate, MESSAGES.plantingDateRequired);
    else if (!date || date < first || date > last) {
      setFieldError(plantingDate, MESSAGES.plantingDateInvalid);
    }

    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      field_name: name,
      crop,
      variety_id: Number(variety.value),
      variety_name: varietyOption.dataset.name,
      area_ha: areaHa,
      planting_date: plantingDate.value,
    };
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    clearErrors();

    const field = validate();
    if (!field) {
      focusFirstInvalid(form);
      return;
    }

    const index = draft.fields.findIndex((f) => f.key === draft.editing);
    if (index >= 0) draft.fields[index] = { ...draft.fields[index], ...field };
    else draft.fields.push({ key: nextFieldKey++, ...field });
    open(null);
    router.navigate('setup-fields');
  });

  /** Prepares the form for a new field (key null) or fills it with an existing one. */
  function open(key) {
    const field = draft.fields.find((f) => f.key === key) ?? null;
    draft.editing = field?.key ?? null;
    form.reset();
    clearErrors();
    if (!field) {
      fillVarieties(null);
      return;
    }
    fieldName.value = field.field_name;
    for (const radio of cropRadios()) radio.checked = radio.value === field.crop;
    fillVarieties(field.crop, field.variety_id);
    size.value = String(field.area_ha);
    plantingDate.value = field.planting_date;
  }

  router.route('setup-field', {
    guard: fieldStepsGuard,
    onEnter() {
      limitPlantingDate();
      heading.textContent = draft.editing === null ? 'Add your Field' : 'Edit your Field';
      backLink.setAttribute('href', draft.fields.length ? '#/setup-fields' : '#/setup-farm');
    },
    onLeave() {
      clearErrors();
    },
  });

  return {
    open,
    reset() {
      open(null);
    },
  };
}

/* ---------- Step 3: list of fields ---------- */

function mountFieldsStep(router, fieldStep) {
  const view = document.querySelector('[data-view="setup-fields"]');
  const list = view.querySelector('[data-field-list]');
  const template = view.querySelector('template[data-field-card]');
  const countEl = view.querySelector('[data-field-count]');
  const addButton = view.querySelector('[data-add-field]');
  const continueButton = view.querySelector('[data-fields-continue]');

  function card(field) {
    const item = template.content.firstElementChild.cloneNode(true);
    const crop = cropOf(field.crop);
    const q = (selector) => item.querySelector(selector);

    q('[data-crop-icon]').setAttribute('href', `#${crop.icon}`);
    q('[data-name]').textContent = field.field_name;
    q('[data-meta]').textContent = `${crop.label} · ${formatHectares(field.area_ha)}`;
    q('[data-place]').textContent = draft.place.barangay_name;
    q('[data-variety]').textContent = field.variety_name;
    q('[data-planted]').textContent = formatDate(parseDate(field.planting_date));

    const edit = q('[data-edit]');
    edit.setAttribute('aria-label', `Edit ${field.field_name}`);
    edit.addEventListener('click', () => {
      fieldStep.open(field.key);
      router.navigate('setup-field');
    });

    const remove = q('[data-remove]');
    remove.setAttribute('aria-label', `Remove ${field.field_name}`);
    remove.addEventListener('click', () => {
      if (!window.confirm(MESSAGES.removeConfirm(field.field_name))) return;
      draft.fields = draft.fields.filter((f) => f.key !== field.key);
      setStatus(view, '');
      render();
      addButton.focus();
    });

    const toggle = q('[data-toggle]');
    const more = q('[data-more]');
    toggle.addEventListener('click', () => {
      more.hidden = !more.hidden;
      toggle.setAttribute('aria-expanded', String(!more.hidden));
      toggle.querySelector('span').textContent = more.hidden ? 'View details' : 'Hide details';
    });

    return item;
  }

  function render() {
    list.replaceChildren(...draft.fields.map(card));
    countEl.textContent = `${draft.fields.length} of ${plural(draft.fieldCount, 'field')} added`;
  }

  addButton.addEventListener('click', () => {
    fieldStep.open(null);
    router.navigate('setup-field');
  });

  continueButton.addEventListener('click', () => {
    const added = draft.fields.length;
    const expected = draft.fieldCount;
    if (!added) setStatus(view, MESSAGES.fieldsNone, 'error');
    else if (added < expected) setStatus(view, MESSAGES.fieldsTooFew(added, expected), 'error');
    else if (added > expected) setStatus(view, MESSAGES.fieldsTooMany(added, expected), 'error');
    else router.navigate('setup-review');
  });

  router.route('setup-fields', {
    guard: () => fieldStepsGuard() ?? (draft.fields.length ? null : 'setup-field'),
    onEnter() {
      render();
    },
    onLeave() {
      setStatus(view, '');
    },
  });
}

/* ---------- Step 4: review and save ---------- */

function mountReviewStep(router, farmStep, fieldStep) {
  const view = document.querySelector('[data-view="setup-review"]');
  const form = view.querySelector('[data-review-form]');
  const list = view.querySelector('[data-review-fields]');
  const template = view.querySelector('template[data-review-card]');
  const value = (name) => view.querySelector(`[data-review="${name}"]`);

  function card(field) {
    const item = template.content.firstElementChild.cloneNode(true);
    const crop = cropOf(field.crop);
    const q = (selector) => item.querySelector(selector);

    q('[data-crop-icon]').setAttribute('href', `#${crop.icon}`);
    q('[data-name]').textContent = field.field_name;
    q('[data-crop]').textContent = `${crop.label} (${field.variety_name})`;
    q('[data-area]').textContent = formatHectares(field.area_ha);
    q('[data-planted]').textContent = formatDate(parseDate(field.planting_date));
    return item;
  }

  function render() {
    value('farm_name').textContent = draft.farm.farm_name;
    value('location').textContent = `${draft.place.barangay_name}, ${draft.place.municipality}, Occidental Mindoro`;
    value('total_area').textContent = formatHectares(totalAreaHa(), { long: true });
    value('season').textContent = labelOf(SEASONS, draft.season);
    list.replaceChildren(...draft.fields.map(card));
  }

  function clearDraft() {
    Object.assign(draft, {
      farm: null,
      place: null,
      fieldCount: 0,
      season: null,
      fields: [],
      editing: null,
    });
    farmStep.reset();
    fieldStep.reset();
  }

  /** POST /farms body: the whole farm, saved in one transaction (Section 6). */
  function payload() {
    return {
      ...draft.farm,
      season: draft.season,
      fields: draft.fields.map((field) => ({
        field_name: field.field_name,
        area_ha: field.area_ha,
        variety_id: field.variety_id,
        planting_date: field.planting_date,
      })),
    };
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;

    setStatus(view, '');
    setBusy(form, true);
    try {
      const created = await farms.create(payload());
      if (created?.farm_id == null) throw new Error(MESSAGES.unexpected);
      saveJSON('farm', {
        farm_id: created.farm_id,
        farm_name: draft.farm.farm_name,
        barangay_name: draft.place.barangay_name,
        municipality: draft.place.municipality,
      });
      draft.result = { farm_name: draft.farm.farm_name };
      clearDraft();
      router.navigate('setup-done', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.navigate('login', { state: { message: MESSAGES.sessionExpired, tone: 'error' } });
        return;
      }
      if (err instanceof ApiError && err.code === 'account_deactivated') {
        setStatus(view, MESSAGES.accountDeactivated, 'error');
        return;
      }
      if (err instanceof ApiError && SAVE_ERRORS[err.code]) {
        // The variety list may be out of date; load it again when a field is edited.
        if (err.code === 'variety_not_found') forgetVarieties();
        setStatus(view, SAVE_ERRORS[err.code], 'error');
        return;
      }
      setStatus(view, err.message, 'error');
    } finally {
      setBusy(form, false);
    }
  });

  router.route('setup-review', {
    guard: () => {
      if (!draft.farm) return 'setup-farm';
      if (!draft.fields.length) return 'setup-field';
      return null;
    },
    onEnter() {
      render();
    },
    onLeave() {
      setStatus(view, '');
    },
  });
}

/* ---------- Done ---------- */

function mountDone(router) {
  const view = document.querySelector('[data-view="setup-done"]');
  const farmNameEl = view.querySelector('[data-farm-name]');

  bindHomeButtons(view, router);

  router.route('setup-done', {
    guard: () => (draft.result ? null : 'setup'),
    onEnter() {
      farmNameEl.textContent = draft.result.farm_name;
    },
  });
}

/* ---------- Public entry ---------- */

export function mountSetupPages(router) {
  mountStart(router);
  const farmStep = mountFarmStep(router);
  const fieldStep = mountFieldStep(router);
  mountFieldsStep(router, fieldStep);
  mountReviewStep(router, farmStep, fieldStep);
  mountDone(router);
}
