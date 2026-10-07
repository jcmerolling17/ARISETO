// frontend/public/js/pages/setup.js

import { farms, crops, ApiError } from '../api/client.js';
import { MUNICIPALITIES, SEASONS, AREA_UNITS, PROVINCE_BOUNDS } from '../data/farm-options.js';
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

const MAX_AREA_HA = 999999.9999; // NUMERIC(10,4)
const MAX_TARGET_YIELD = 9999.99; // NUMERIC(6,2)
const PLANTING_WINDOW_DAYS = 730;
const DAY_MS = 24 * 60 * 60 * 1000;

const MESSAGES = {
  farmNameRequired: 'Enter your farm name.',
  municipalityRequired: 'Choose the municipality where your farm is.',
  barangayRequired: 'Choose the barangay where your farm is.',
  notFarmOwner: 'Only the owner of this farm can add crops to it.',
  coordinatesOutsideProvince: 'Your farm location is outside Occidental Mindoro. Go back to the previous step and capture it again while at the farm, or skip it to use your barangay’s center point.',
  areaRequired: 'Enter your farm area.',
  areaInvalid: 'Enter an area greater than 0.',
  areaTooSmall: 'This area is too small. Enter at least 1 m².',
  areaTooLarge: 'This area is too large. Check the number and the unit.',
  cropRequired: 'Choose a crop.',
  varietyRequired: 'Choose a variety.',
  seasonRequired: 'Choose the season.',
  plantingDateRequired: 'Enter the planting date.',
  plantingDateInvalid: 'Enter a planting date within two years of today.',
  areaPlantedRequired: 'Enter the area planted.',
  areaPlantedTooLarge: 'Area planted cannot be more than the farm area.',
  targetYieldInvalid: 'Enter a target yield greater than 0, in tons per hectare.',
  cropsLoading: 'Loading crops…',
  cropsFailed: 'Could not load the crop list.',
  sessionExpired: 'Your session has expired. Please log in again.',
  unexpected: 'The server returned an unexpected response. Please try again.',
  farmSavedRetry: 'Your farm was saved. Press Finish setup again to add your crop.',
  geoDefault: 'Not set. We’ll use your barangay’s center point.',
  geoLocating: 'Getting your location…',
  geoUnsupported: 'This browser cannot share your location. We’ll use your barangay’s center point.',
  geoDenied: 'Location permission was denied. We’ll use your barangay’s center point.',
  geoFailed: 'Could not get a GPS fix. Try again outdoors, or skip this to use your barangay’s center point.',
  geoOutside: 'That location is outside Occidental Mindoro. Try again while at the farm, or skip this to use your barangay’s center point.',
};

/**
 * farm:        step 1 answers (POST /farms body), not yet sent
 * place:       municipality and barangay names, kept for display only
 * createdFarm: farm returned by POST /farms (kept so a failed crop-cycle request is retried
 *              without creating the farm twice)
 * result:      the finished farm shown on the success screen
 */
const draft = { farm: null, place: null, createdFarm: null, result: null };

/* ---------- Helpers ---------- */

function fillSelect(select, options) {
  for (const option of options) {
    select.add(typeof option === 'string' ? new Option(option, option) : new Option(option.label, option.value));
  }
}

function cleanText(raw) {
  return String(raw).trim().replace(/\s+/g, ' ');
}

/** Converts an area typed in ha or m² to hectares with 4 decimals; null when not a positive number. */
function toHectares(raw, unit) {
  const value = Number(raw);
  if (!String(raw).trim() || !Number.isFinite(value) || value <= 0) return null;
  const hectares = unit === 'sqm' ? value / 10000 : value;
  return Math.round(hectares * 10000) / 10000;
}

function validateArea(input, unit, { required, tooLarge = MAX_AREA_HA, tooLargeMessage = MESSAGES.areaTooLarge }) {
  if (!input.value.trim()) {
    setFieldError(input, required);
    return null;
  }
  const hectares = toHectares(input.value, unit);
  if (hectares === null) setFieldError(input, MESSAGES.areaInvalid);
  else if (hectares === 0) setFieldError(input, MESSAGES.areaTooSmall);
  else if (hectares > tooLarge) setFieldError(input, tooLargeMessage);
  else return hectares;
  return null;
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

/** Philippine wet season runs roughly June to November. */
function seasonFor(date) {
  const month = date.getMonth() + 1;
  return month >= 6 && month <= 11 ? 'wet' : 'dry';
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

/* ---------- Step 1: farm (FARM) ---------- */

function mountGeo(form) {
  const box = form.querySelector('[data-geo]');
  const text = box.querySelector('[data-geo-text]');
  const button = box.querySelector('[data-geo-capture]');
  let coords = null;

  function show(message, state = '') {
    text.textContent = message;
    box.dataset.state = state;
  }

  button.addEventListener('click', () => {
    if (!('geolocation' in navigator)) {
      show(MESSAGES.geoUnsupported, 'warn');
      return;
    }
    button.disabled = true;
    show(MESSAGES.geoLocating);

    navigator.geolocation.getCurrentPosition(
      ({ coords: { latitude, longitude, accuracy } }) => {
        button.disabled = false;
        const { minLat, maxLat, minLon, maxLon } = PROVINCE_BOUNDS;
        if (latitude < minLat || latitude > maxLat || longitude < minLon || longitude > maxLon) {
          coords = null;
          show(MESSAGES.geoOutside, 'warn');
          return;
        }
        coords = { latitude: Number(latitude.toFixed(6)), longitude: Number(longitude.toFixed(6)) };
        show(`Saved: ${latitude.toFixed(5)}, ${longitude.toFixed(5)} (±${Math.round(accuracy)} m)`, 'ok');
        button.textContent = 'Update';
      },
      (error) => {
        button.disabled = false;
        coords = null;
        show(error.code === error.PERMISSION_DENIED ? MESSAGES.geoDenied : MESSAGES.geoFailed, 'warn');
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 60000 },
    );
  });

  return {
    get coords() {
      return coords;
    },
    reset() {
      coords = null;
      button.disabled = false;
      button.textContent = 'Use my location';
      show(MESSAGES.geoDefault);
    },
  };
}

function mountFarmStep(router) {
  const form = document.getElementById('setup-farm-form');
  const { farm_name: farmName, municipality, barangay_id: barangay, area, area_unit: areaUnit } = form.elements;
  const geo = mountGeo(form);
  const barangayPicker = mountBarangayPicker(municipality, barangay, {
    onChange: () => setFieldError(barangay, ''),
  });

  fillSelect(municipality, MUNICIPALITIES);
  fillSelect(areaUnit, AREA_UNITS);
  bindLiveErrorClearing(form);

  function validate() {
    const name = cleanText(farmName.value);
    const place = barangayPicker.selected();

    if (!name) setFieldError(farmName, MESSAGES.farmNameRequired);
    if (!municipality.value) setFieldError(municipality, MESSAGES.municipalityRequired);
    else if (!place) setFieldError(barangay, MESSAGES.barangayRequired);
    const totalAreaHa = validateArea(area, areaUnit.value, { required: MESSAGES.areaRequired });

    if (form.querySelector('[aria-invalid="true"]')) return null;
    // Without a GPS fix the farm is placed at its barangay's center point (FARM.latitude/longitude fallback).
    return {
      farm: {
        farm_name: name,
        barangay_id: place.barangay_id,
        latitude: geo.coords?.latitude ?? Number(place.center_latitude),
        longitude: geo.coords?.longitude ?? Number(place.center_longitude),
        total_area_ha: totalAreaHa,
      },
      place: { municipality: municipality.value, barangay_name: place.barangay_name },
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
    draft.farm = answers.farm;
    draft.place = answers.place;
    router.navigate('setup-cycle');
  });

  router.route('setup-farm', {
    // Once the farm exists on the server it can no longer be edited from setup.
    guard: () => (draft.createdFarm ? 'setup-cycle' : null),
    onLeave() {
      clearFieldErrors(form);
    },
  });

  return {
    reset() {
      form.reset();
      geo.reset();
      barangayPicker.reset();
    },
  };
}

/* ---------- Step 2: first crop cycle (CROP_CYCLE) ---------- */

function mountCycleStep(router, farmStep) {
  const view = document.querySelector('[data-view="setup-cycle"]');
  const form = document.getElementById('setup-cycle-form');
  const backLink = view.querySelector('[data-cycle-back]');
  const retryButton = view.querySelector('[data-retry-crops]');
  const harvestHint = view.querySelector('[data-harvest-hint]');
  const {
    crop_id: crop,
    variety_id: variety,
    season,
    planting_date: plantingDate,
    area_planted: areaPlanted,
    area_planted_unit: areaPlantedUnit,
    target_yield_t_ha: targetYield,
  } = form.elements;

  let cropList = null;
  let loading = null;
  let seasonTouched = false;

  fillSelect(season, SEASONS);
  fillSelect(areaPlantedUnit, AREA_UNITS);
  bindLiveErrorClearing(form);

  const farmAreaHa = () => (draft.createdFarm ?? draft.farm)?.total_area_ha ?? MAX_AREA_HA;

  function selectedVariety() {
    const current = cropList?.find((c) => String(c.crop_id) === crop.value);
    return current?.varieties?.find((v) => String(v.variety_id) === variety.value) ?? null;
  }

  function renderVarieties() {
    const current = cropList?.find((c) => String(c.crop_id) === crop.value);
    variety.replaceChildren(new Option(current ? 'Choose variety' : 'Choose a crop first', ''));
    for (const v of current?.varieties ?? []) {
      const maturity = v.maturity_days ? ` · ${v.maturity_days} days` : '';
      variety.add(new Option(`${v.variety_name}${maturity}`, String(v.variety_id)));
    }
    variety.disabled = !current;
    renderHarvestHint();
  }

  function renderHarvestHint() {
    const v = selectedVariety();
    const date = parseDate(plantingDate.value);
    if (!v?.maturity_days || !date) {
      harvestHint.textContent = '';
      return;
    }
    const harvest = new Date(date.getTime() + v.maturity_days * DAY_MS);
    harvestHint.textContent = `Expected harvest around ${formatDate(harvest)} (${v.maturity_days} days after planting).`;
  }

  async function loadCrops() {
    if (cropList || loading) return loading;
    retryButton.hidden = true;
    setStatus(view, MESSAGES.cropsLoading, 'success');
    crop.disabled = true;

    loading = crops.list()
      .then((list) => {
        cropList = Array.isArray(list) ? list : [];
        crop.replaceChildren(new Option('Choose crop', ''));
        for (const c of cropList) crop.add(new Option(c.crop_name, String(c.crop_id)));
        crop.disabled = false;
        setStatus(view, '');
      })
      .catch((err) => {
        crop.replaceChildren(new Option('Crops unavailable', ''));
        setStatus(view, `${MESSAGES.cropsFailed} ${err.message}`, 'error');
        retryButton.hidden = false;
      })
      .finally(() => {
        loading = null;
      });
    return loading;
  }

  crop.addEventListener('change', renderVarieties);
  variety.addEventListener('change', renderHarvestHint);
  season.addEventListener('change', () => { seasonTouched = true; });
  plantingDate.addEventListener('change', () => {
    const date = parseDate(plantingDate.value);
    if (date && !seasonTouched) {
      season.value = seasonFor(date);
      setFieldError(season, '');
    }
    renderHarvestHint();
  });
  retryButton.addEventListener('click', loadCrops);

  function validate() {
    if (!crop.value) setFieldError(crop, MESSAGES.cropRequired);
    if (!variety.value) setFieldError(variety, MESSAGES.varietyRequired);
    if (!season.value) setFieldError(season, MESSAGES.seasonRequired);

    const date = parseDate(plantingDate.value);
    if (!plantingDate.value) setFieldError(plantingDate, MESSAGES.plantingDateRequired);
    else if (!date || Math.abs(date.getTime() - Date.now()) > PLANTING_WINDOW_DAYS * DAY_MS) {
      setFieldError(plantingDate, MESSAGES.plantingDateInvalid);
    }

    const areaPlantedHa = validateArea(areaPlanted, areaPlantedUnit.value, {
      required: MESSAGES.areaPlantedRequired,
      tooLarge: farmAreaHa(),
      tooLargeMessage: MESSAGES.areaPlantedTooLarge,
    });

    let target = null;
    if (targetYield.value.trim()) {
      target = Number(targetYield.value);
      if (!Number.isFinite(target) || target <= 0 || target > MAX_TARGET_YIELD) {
        setFieldError(targetYield, MESSAGES.targetYieldInvalid);
      } else {
        target = Math.round(target * 100) / 100;
      }
    }

    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      variety_id: Number(variety.value),
      season: season.value,
      area_planted_ha: areaPlantedHa,
      planting_date: plantingDate.value,
      target_yield_t_ha: target,
    };
  }

  function reset() {
    form.reset();
    seasonTouched = false;
    renderVarieties();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;

    clearFieldErrors(form);
    setStatus(view, '');

    const cycle = validate();
    if (!cycle) {
      focusFirstInvalid(form);
      return;
    }

    setBusy(form, true);
    try {
      if (!draft.createdFarm) {
        const created = await farms.create(draft.farm);
        const farmId = created?.farm_id ?? created?.id;
        if (farmId == null) throw new Error(MESSAGES.unexpected);
        draft.createdFarm = { ...draft.farm, ...draft.place, ...created, farm_id: farmId };
        saveJSON('farm', {
          farm_id: farmId,
          farm_name: draft.createdFarm.farm_name,
          municipality: draft.createdFarm.municipality,
        });
        backLink.hidden = true;
      }

      const createdCycle = await farms.createCycle(draft.createdFarm.farm_id, cycle);

      draft.result = { ...draft.createdFarm, expected_harvest_date: createdCycle?.expected_harvest_date ?? null };
      draft.farm = null;
      draft.place = null;
      draft.createdFarm = null;
      farmStep.reset();
      reset();
      router.navigate('setup-done', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.navigate('login', { state: { message: MESSAGES.sessionExpired, tone: 'error' } });
        return;
      }
      if (err instanceof ApiError && err.code === 'area_exceeds_farm') {
        setFieldError(areaPlanted, MESSAGES.areaPlantedTooLarge);
        focusFirstInvalid(form);
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

  router.route('setup-cycle', {
    guard: () => (draft.farm || draft.createdFarm ? null : 'setup-farm'),
    onEnter() {
      backLink.hidden = Boolean(draft.createdFarm);
      loadCrops();
    },
    onLeave() {
      clearFieldErrors(form);
      if (cropList) setStatus(view, '');
    },
  });
}

/* ---------- Done ---------- */

function mountDone(router) {
  const view = document.querySelector('[data-view="setup-done"]');
  const farmNameEl = view.querySelector('[data-farm-name]');
  const harvestEl = view.querySelector('[data-expected-harvest]');

  bindHomeButtons(view, router);

  router.route('setup-done', {
    guard: () => (draft.result ? null : 'setup'),
    onEnter() {
      farmNameEl.textContent = draft.result.farm_name;
      // expected_harvest_date comes from POST /farms/{farm_id}/cycles (planting_date + maturity_days).
      const harvest = parseDate(draft.result.expected_harvest_date ?? '');
      harvestEl.textContent = harvest ? `Expected harvest: ${formatDate(harvest)}` : '';
      harvestEl.hidden = !harvest;
    },
  });
}

/* ---------- Public entry ---------- */

export function mountSetupPages(router) {
  mountStart(router);
  const farmStep = mountFarmStep(router);
  mountCycleStep(router, farmStep);
  mountDone(router);
}
