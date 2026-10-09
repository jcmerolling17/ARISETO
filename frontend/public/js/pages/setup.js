// frontend/public/js/pages/setup.js

import { farms, ApiError } from '../api/client.js';
import { MUNICIPALITIES, SEASONS, CROPS, PLANTING_METHODS } from '../data/farm-options.js';
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
const PLANTING_WINDOW_DAYS = 730;
const DAY_MS = 24 * 60 * 60 * 1000;

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
  varietyRequired: 'Enter the variety.',
  sizeRequired: 'Enter the field size in hectares.',
  sizeInvalid: 'Enter a size greater than 0.',
  sizeTooSmall: 'This size is too small. Enter at least 0.0001 ha (1 m²).',
  sizeTooLarge: 'Your fields add up to more than ARISETO can store. Check the size.',
  plantingDateRequired: 'Enter the planting date.',
  plantingDateInvalid: 'Enter a planting date within two years of today.',
  plantingMethodRequired: 'Choose the planting method.',
  removeConfirm: (name) => `Remove ${name} from your farm?`,
  fieldsNone: 'Add at least one field.',
  fieldsTooFew: (added, expected) =>
    `You said your farm has ${plural(expected, 'field')}, but you added ${added}. Add ${plural(expected - added, 'more field')}, or go back and change the number.`,
  fieldsTooMany: (added, expected) =>
    `You said your farm has ${plural(expected, 'field')}, but you added ${added}. Remove ${plural(added - expected, 'field')}, or go back and change the number.`,
  notFarmOwner: 'Only the owner of this farm can add fields to it.',
  coordinatesOutsideProvince: 'Your barangay’s location is outside Occidental Mindoro. Go back and choose your barangay again.',
  sessionExpired: 'Your session has expired. Please log in again.',
  unexpected: 'The server returned an unexpected response. Please try again.',
  farmSavedRetry: 'Your farm was saved. Press Continue again to finish adding your fields.',
};

/**
 * farm:        step 1 answers (POST /farms body without total_area_ha), not yet sent
 * place:       municipality and barangay names, kept for display only
 * fieldCount:  how many fields the farmer said the farm has
 * season:      season shared by every field in this setup
 * fields:      fields added in steps 2–3:
 *              { key, field_name, crop, variety, area_ha, planting_date, planting_method }
 * editing:     key of the field open in step 2, or null when adding a new one
 * createdFarm: farm returned by POST /farms, and savedKeys the fields already sent, so a failed
 *              request is retried without creating anything twice
 * result:      the finished farm shown on the success screen
 */
const draft = {
  farm: null,
  place: null,
  fieldCount: 0,
  season: null,
  fields: [],
  editing: null,
  createdFarm: null,
  savedKeys: new Set(),
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
    // The farm is placed at its barangay's center point (FARM.latitude/longitude).
    return {
      farm: {
        farm_name: name,
        barangay_id: place.barangay_id,
        latitude: Number(place.center_latitude),
        longitude: Number(place.center_longitude),
      },
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
    // Once the farm exists on the server it can no longer be edited from setup.
    guard: () => (draft.createdFarm ? 'setup-review' : null),
    onLeave() {
      clearFieldErrors(form);
    },
  });

  return {
    reset() {
      form.reset();
      barangayPicker.reset();
    },
  };
}

/** Steps 2 and 3 need step 1's answers, and are locked once the farm is saved. */
function fieldStepsGuard() {
  if (!draft.farm) return 'setup-farm';
  if (draft.createdFarm) return 'setup-review';
  return null;
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
    variety,
    area_ha: size,
    planting_date: plantingDate,
    planting_method: plantingMethod,
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

  fillSelect(plantingMethod, PLANTING_METHODS);
  bindLiveErrorClearing(form);

  // The crop is a radio group, so its error is set on every radio and shown once.
  function setCropError(message) {
    for (const radio of cropRadios()) {
      if (message) radio.setAttribute('aria-invalid', 'true');
      else radio.removeAttribute('aria-invalid');
    }
    cropError.textContent = message;
  }
  cropOptions.addEventListener('change', () => setCropError(''));

  function clearErrors() {
    clearFieldErrors(form);
    setCropError('');
  }

  function validate() {
    const name = cleanText(fieldName.value);
    const crop = form.elements.crop.value;
    const varietyName = cleanText(variety.value);
    const others = draft.fields.filter((field) => field.key !== draft.editing);

    if (!name) setFieldError(fieldName, MESSAGES.fieldNameRequired);
    else if (others.some((field) => field.field_name.toLowerCase() === name.toLowerCase())) {
      setFieldError(fieldName, MESSAGES.fieldNameTaken);
    }
    if (!crop) setCropError(MESSAGES.cropRequired);
    if (!varietyName) setFieldError(variety, MESSAGES.varietyRequired);

    const areaHa = toHectares(size.value);
    const othersHa = others.reduce((sum, field) => sum + field.area_ha, 0);
    if (!size.value.trim()) setFieldError(size, MESSAGES.sizeRequired);
    else if (areaHa === null) setFieldError(size, MESSAGES.sizeInvalid);
    else if (areaHa === 0) setFieldError(size, MESSAGES.sizeTooSmall);
    else if (othersHa + areaHa > MAX_AREA_HA) setFieldError(size, MESSAGES.sizeTooLarge);

    const date = parseDate(plantingDate.value);
    if (!plantingDate.value) setFieldError(plantingDate, MESSAGES.plantingDateRequired);
    else if (!date || Math.abs(date.getTime() - Date.now()) > PLANTING_WINDOW_DAYS * DAY_MS) {
      setFieldError(plantingDate, MESSAGES.plantingDateInvalid);
    }
    if (!plantingMethod.value) setFieldError(plantingMethod, MESSAGES.plantingMethodRequired);

    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      field_name: name,
      crop,
      variety: varietyName,
      area_ha: areaHa,
      planting_date: plantingDate.value,
      planting_method: plantingMethod.value,
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
    if (!field) return;
    fieldName.value = field.field_name;
    for (const radio of cropRadios()) radio.checked = radio.value === field.crop;
    variety.value = field.variety;
    size.value = String(field.area_ha);
    plantingDate.value = field.planting_date;
    plantingMethod.value = field.planting_method;
  }

  router.route('setup-field', {
    guard: fieldStepsGuard,
    onEnter() {
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
    q('[data-variety]').textContent = field.variety;
    q('[data-planted]').textContent = formatDate(parseDate(field.planting_date));
    q('[data-method]').textContent = labelOf(PLANTING_METHODS, field.planting_method);

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
  const backLink = view.querySelector('[data-review-back]');
  const editLinks = view.querySelectorAll('[data-review-edit]');
  const list = view.querySelector('[data-review-fields]');
  const template = view.querySelector('template[data-review-card]');
  const value = (name) => view.querySelector(`[data-review="${name}"]`);

  function card(field) {
    const item = template.content.firstElementChild.cloneNode(true);
    const crop = cropOf(field.crop);
    const q = (selector) => item.querySelector(selector);

    q('[data-crop-icon]').setAttribute('href', `#${crop.icon}`);
    q('[data-name]').textContent = field.field_name;
    q('[data-crop]').textContent = `${crop.label} (${field.variety})`;
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

    const locked = Boolean(draft.createdFarm);
    backLink.hidden = locked;
    editLinks.forEach((link) => { link.hidden = locked; });
  }

  function clearDraft() {
    Object.assign(draft, {
      farm: null,
      place: null,
      fieldCount: 0,
      season: null,
      fields: [],
      editing: null,
      createdFarm: null,
      savedKeys: new Set(),
    });
    farmStep.reset();
    fieldStep.reset();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;

    setStatus(view, '');
    setBusy(form, true);
    try {
      if (!draft.createdFarm) {
        const created = await farms.create({ ...draft.farm, total_area_ha: totalAreaHa() });
        const farmId = created?.farm_id ?? created?.id;
        if (farmId == null) throw new Error(MESSAGES.unexpected);
        draft.createdFarm = { ...draft.farm, ...draft.place, ...created, farm_id: farmId };
        saveJSON('farm', {
          farm_id: farmId,
          farm_name: draft.createdFarm.farm_name,
          municipality: draft.createdFarm.municipality,
        });
        render();
      }

      for (const field of draft.fields) {
        if (draft.savedKeys.has(field.key)) continue;
        const { key, ...payload } = field;
        await farms.addField(draft.createdFarm.farm_id, { ...payload, season: draft.season });
        draft.savedKeys.add(key);
      }

      draft.result = { farm_name: draft.createdFarm.farm_name };
      clearDraft();
      router.navigate('setup-done', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.navigate('login', { state: { message: MESSAGES.sessionExpired, tone: 'error' } });
        return;
      }
      if (err instanceof ApiError && err.code === 'coordinates_outside_province') {
        setStatus(view, MESSAGES.coordinatesOutsideProvince, 'error');
        return;
      }
      if (err instanceof ApiError && err.code === 'not_farm_owner') {
        setStatus(view, MESSAGES.notFarmOwner, 'error');
        return;
      }
      setStatus(view, draft.createdFarm ? `${err.message} ${MESSAGES.farmSavedRetry}` : err.message, 'error');
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
