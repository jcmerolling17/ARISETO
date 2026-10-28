// frontend/public/js/pages/account.js

/**
 * Screens opened from Profile: Edit Profile (PATCH /users/me), Change Password
 * (POST /users/me/password), and Add Plot (POST /farms/{farm_id}/fields, farm owners only).
 * Each one returns to Profile with a message when it saves.
 */
import { farms, users, ApiError } from '../api/client.js';
import { CROPS, SEASONS, suggestedSeason } from '../data/farm-options.js';
import {
  setFieldError,
  clearFieldErrors,
  setStatus,
  setBusy,
  focusFirstInvalid,
  bindLiveErrorClearing,
} from '../utils/form.js';
import { saveJSON } from '../utils/store.js';
import {
  cleanName,
  isValidEmail,
  isValidMobile,
  normalizeMobile,
  resetPasswordVisibility,
} from './login.js';
import {
  forgetVarieties,
  loadVarieties,
  parseDate,
  plantingWindow,
  toHectares,
  toISODate,
} from './setup.js';

const MIN_PASSWORD_LENGTH = 8;
const MAX_PASSWORD_LENGTH = 128;
const MAX_AREA_HA = 999999.9999; // FARM.total_area_ha NUMERIC(10,4)
const MAX_TARGET_T_HA = 9999.99; // CROP_CYCLE.target_yield_t_ha NUMERIC(6,2)

const MESSAGES = {
  loadFailed: 'Your profile could not be loaded. Check your connection and try again.',
  firstNameRequired: 'Enter your first name.',
  lastNameRequired: 'Enter your last name.',
  mobileRequired: 'Enter your mobile number.',
  mobileInvalid: 'Enter a valid PH mobile number, e.g. +639171234567.',
  emailInvalid: 'Enter a valid email address.',
  currentPasswordRequired: 'Enter your current password to change your mobile number or email.',
  currentPasswordWrong: 'Your current password is incorrect.',
  mobileTaken: 'This mobile number is already registered.',
  emailTaken: 'This email is already registered.',
  noChanges: 'No changes to save.',
  profileSaved: 'Profile updated.',
  passwordRequired: 'Enter your current password.',
  newPasswordLength: `Use ${MIN_PASSWORD_LENGTH} to ${MAX_PASSWORD_LENGTH} characters.`,
  confirmMismatch: 'The passwords do not match.',
  passwordUnchanged: 'Choose a password different from your current one.',
  passwordSaved: 'Password changed. You were logged out on your other devices.',
  fieldNameRequired: 'Enter a field name.',
  fieldNameTaken: 'A field with this name already exists on this farm.',
  cropRequired: 'Choose a crop.',
  varietyRequired: 'Choose a variety.',
  varietiesFailed: 'Varieties could not be loaded. Check your connection and choose the crop again.',
  varietyNotFound: 'This variety is no longer on the list. Choose the variety again.',
  sizeInvalid: 'Enter the field size in hectares, e.g. 1.25.',
  sizeTooLarge: 'The farm would be larger than 999,999.9999 hectares.',
  dateRequired: 'Enter the sowing date.',
  dateOutOfRange: 'Enter a sowing date within two years of today.',
  targetInvalid: 'Enter a target greater than 0, with at most 2 decimals.',
  notOwner: 'Only the farm owner can add plots.',
  farmNotFound: 'This farm could not be found. Go back to Profile and try again.',
  plotSaved: 'Plot added.',
};

/** 'October 2025' in Philippine time. */
function formatMonth(value) {
  return new Date(value).toLocaleDateString('en-PH', { month: 'long', year: 'numeric', timeZone: 'Asia/Manila' });
}

function isSessionEnd(err) {
  return err instanceof ApiError && err.sessionEnded;
}

/* ---------- Edit Profile ---------- */

function mountEditProfile(router) {
  const view = document.querySelector('[data-view="edit-profile"]');
  const form = document.getElementById('edit-profile-form');
  const {
    first_name: firstName,
    last_name: lastName,
    email,
    mobile_no: mobile,
    current_password: currentPassword,
  } = form.elements;
  const currentBox = view.querySelector('[data-current-password]');
  let loaded = null;

  bindLiveErrorClearing(form);

  function values() {
    return {
      first_name: cleanName(firstName.value),
      last_name: cleanName(lastName.value),
      email: email.value.trim().toLowerCase() || null,
      mobile_no: normalizeMobile(mobile.value),
    };
  }

  /** Mobile number and email are login IDs, so changing either needs the current password. */
  function loginIdChanged(next) {
    return Boolean(loaded) && (next.mobile_no !== loaded.mobile_no || next.email !== (loaded.email ?? null));
  }

  function syncCurrentPassword() {
    const needed = loginIdChanged(values());
    currentBox.hidden = !needed;
    if (!needed) {
      currentPassword.value = '';
      setFieldError(currentPassword, '');
    }
  }

  email.addEventListener('input', syncCurrentPassword);
  mobile.addEventListener('input', syncCurrentPassword);
  mobile.addEventListener('blur', () => {
    const normalized = normalizeMobile(mobile.value);
    if (isValidMobile(normalized)) mobile.value = normalized;
  });

  function fill(user) {
    loaded = user;
    firstName.value = user.first_name;
    lastName.value = user.last_name;
    email.value = user.email ?? '';
    mobile.value = user.mobile_no;
    view.querySelector('[data-initials]').textContent = `${user.first_name[0] ?? ''}${user.last_name[0] ?? ''}`.toUpperCase();
    view.querySelector('[data-since]').textContent = formatMonth(user.created_at);
    view.querySelector('[data-member-since]').hidden = false;
    syncCurrentPassword();
  }

  async function load() {
    loaded = null;
    clearFieldErrors(form);
    setStatus(view, '');
    currentPassword.value = '';
    currentBox.hidden = true;
    resetPasswordVisibility(form);
    try {
      fill(await users.me());
    } catch (err) {
      if (!isSessionEnd(err)) setStatus(view, MESSAGES.loadFailed, 'error');
    }
  }

  function validate(next) {
    if (!next.first_name) setFieldError(firstName, MESSAGES.firstNameRequired);
    if (!next.last_name) setFieldError(lastName, MESSAGES.lastNameRequired);
    if (!mobile.value.trim()) setFieldError(mobile, MESSAGES.mobileRequired);
    else if (!isValidMobile(next.mobile_no)) setFieldError(mobile, MESSAGES.mobileInvalid);
    if (next.email && !isValidEmail(next.email)) setFieldError(email, MESSAGES.emailInvalid);
    if (loginIdChanged(next) && !currentPassword.value) {
      setFieldError(currentPassword, MESSAGES.currentPasswordRequired);
    }
    return !form.querySelector('[aria-invalid="true"]');
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true' || !loaded) return;

    clearFieldErrors(form);
    setStatus(view, '');
    const next = values();
    if (!validate(next)) {
      focusFirstInvalid(form);
      return;
    }

    // Send only what changed; current_password only when a login ID changed.
    const changes = {};
    for (const [name, value] of Object.entries(next)) {
      if (value !== (loaded[name] ?? null)) changes[name] = value;
    }
    if (!Object.keys(changes).length) {
      setStatus(view, MESSAGES.noChanges, 'success');
      return;
    }
    if (loginIdChanged(next)) changes.current_password = currentPassword.value;

    setBusy(form, true);
    try {
      const user = await users.update(changes);
      saveJSON('user', { first_name: user.first_name });
      currentPassword.value = '';
      router.navigate('profile', { replace: true, state: { message: MESSAGES.profileSaved } });
    } catch (err) {
      if (isSessionEnd(err)) return;
      const fieldErrors = {
        invalid_current_password: [currentPassword, MESSAGES.currentPasswordWrong],
        current_password_required: [currentPassword, MESSAGES.currentPasswordRequired],
        mobile_taken: [mobile, MESSAGES.mobileTaken],
        email_taken: [email, MESSAGES.emailTaken],
      };
      const target = err instanceof ApiError ? fieldErrors[err.code] : null;
      if (target) {
        currentBox.hidden = false;
        setFieldError(...target);
        focusFirstInvalid(form);
      } else {
        setStatus(view, err.message, 'error');
      }
    } finally {
      setBusy(form, false);
    }
  });

  router.route('edit-profile', { onEnter: load });
}

/* ---------- Change Password ---------- */

function mountChangePassword(router) {
  const view = document.querySelector('[data-view="change-password"]');
  const form = document.getElementById('change-password-form');
  const {
    current_password: current,
    new_password: next,
    confirm_password: confirm,
  } = form.elements;

  bindLiveErrorClearing(form);

  function reset() {
    form.reset();
    clearFieldErrors(form);
    setStatus(view, '');
    resetPasswordVisibility(form);
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;

    clearFieldErrors(form);
    setStatus(view, '');
    if (!current.value) setFieldError(current, MESSAGES.passwordRequired);
    if (next.value.length < MIN_PASSWORD_LENGTH || next.value.length > MAX_PASSWORD_LENGTH) {
      setFieldError(next, MESSAGES.newPasswordLength);
    } else if (confirm.value !== next.value) {
      setFieldError(confirm, MESSAGES.confirmMismatch);
    }
    if (form.querySelector('[aria-invalid="true"]')) {
      focusFirstInvalid(form);
      return;
    }

    setBusy(form, true);
    try {
      // The client saves the returned token, so this device stays logged in.
      await users.changePassword({ current_password: current.value, new_password: next.value });
      reset();
      router.navigate('profile', { replace: true, state: { message: MESSAGES.passwordSaved } });
    } catch (err) {
      if (isSessionEnd(err)) return;
      if (err instanceof ApiError && err.code === 'invalid_current_password') {
        setFieldError(current, MESSAGES.currentPasswordWrong);
        focusFirstInvalid(form);
      } else if (err instanceof ApiError && err.code === 'password_unchanged') {
        setFieldError(next, MESSAGES.passwordUnchanged);
        focusFirstInvalid(form);
      } else {
        setStatus(view, err.message, 'error');
      }
    } finally {
      setBusy(form, false);
    }
  });

  router.route('change-password', { onEnter: reset, onLeave: reset });
}

/* ---------- Add Plot ---------- */

function mountAddPlot(router) {
  const view = document.querySelector('[data-view="add-plot"]');
  const form = document.getElementById('add-plot-form');
  const {
    field_name: name,
    crop,
    variety_id: variety,
    area_ha: size,
    season,
    planting_date: plantingDate,
    target_yield_t_ha: target,
  } = form.elements;
  let farm = null;
  let varietyRequest = 0;

  for (const option of CROPS) crop.add(new Option(option.label, option.value));
  for (const option of SEASONS) season.add(new Option(option.label, option.value));
  bindLiveErrorClearing(form);

  function setVarietyPlaceholder(text) {
    variety.replaceChildren(new Option(text, ''));
    variety.disabled = true;
  }

  async function fillVarieties(value) {
    const id = ++varietyRequest;
    setFieldError(variety, '');
    if (!value) {
      setVarietyPlaceholder('Choose a crop first');
      return;
    }
    setVarietyPlaceholder('Loading varieties…');
    try {
      const list = (await loadVarieties()).get(value) ?? [];
      if (id !== varietyRequest) return;
      variety.replaceChildren(new Option('Choose variety', ''));
      for (const item of list) {
        variety.add(new Option(`${item.variety_name} · ${item.maturity_days} days`, String(item.variety_id)));
      }
      variety.disabled = list.length === 0;
    } catch (err) {
      if (id !== varietyRequest || isSessionEnd(err)) return;
      setVarietyPlaceholder('Choose a crop first');
      setFieldError(variety, MESSAGES.varietiesFailed);
    }
  }

  crop.addEventListener('change', () => fillVarieties(crop.value));

  function open({ state } = {}) {
    farm = state?.farm ?? null;
    if (!farm) {
      router.navigate('profile', { replace: true });
      return;
    }
    form.reset();
    clearFieldErrors(form);
    setStatus(view, '');
    view.querySelector('[data-farm-name]').textContent = farm.farm_name;
    season.value = suggestedSeason();
    const [first, last] = plantingWindow();
    plantingDate.min = toISODate(first);
    plantingDate.max = toISODate(last);
    fillVarieties('');
  }

  function validate() {
    const fieldName = cleanName(name.value);
    const areaHa = toHectares(size.value);
    const sown = parseDate(plantingDate.value);
    const [first, last] = plantingWindow();
    const targetText = target.value.trim();
    const targetValue = Number(targetText);

    if (!fieldName) setFieldError(name, MESSAGES.fieldNameRequired);
    if (!crop.value) setFieldError(crop, MESSAGES.cropRequired);
    else if (!variety.value) setFieldError(variety, MESSAGES.varietyRequired);
    if (areaHa === null || areaHa === 0) setFieldError(size, MESSAGES.sizeInvalid);
    else if (Number(farm.total_area_ha) + areaHa > MAX_AREA_HA) setFieldError(size, MESSAGES.sizeTooLarge);
    if (!plantingDate.value) setFieldError(plantingDate, MESSAGES.dateRequired);
    else if (!sown || sown < first || sown > last) setFieldError(plantingDate, MESSAGES.dateOutOfRange);
    if (targetText && !(targetValue > 0 && targetValue <= MAX_TARGET_T_HA && /^\d+(\.\d{1,2})?$/.test(targetText))) {
      setFieldError(target, MESSAGES.targetInvalid);
    }

    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      field_name: fieldName,
      area_ha: areaHa,
      variety_id: Number(variety.value),
      season: season.value,
      planting_date: plantingDate.value,
      ...(targetText && { target_yield_t_ha: targetValue }),
    };
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true' || !farm) return;

    clearFieldErrors(form);
    setStatus(view, '');
    const payload = validate();
    if (!payload) {
      focusFirstInvalid(form);
      return;
    }

    setBusy(form, true);
    try {
      await farms.addField(farm.farm_id, payload);
      router.navigate('profile', { replace: true, state: { message: MESSAGES.plotSaved } });
    } catch (err) {
      if (isSessionEnd(err)) return;
      const code = err instanceof ApiError ? err.code : null;
      if (code === 'field_name_taken') setFieldError(name, MESSAGES.fieldNameTaken);
      else if (code === 'planting_date_out_of_range') setFieldError(plantingDate, MESSAGES.dateOutOfRange);
      else if (code === 'variety_not_found') {
        forgetVarieties();
        setFieldError(variety, MESSAGES.varietyNotFound);
        fillVarieties(crop.value);
      } else if (code === 'not_farm_owner') setStatus(view, MESSAGES.notOwner, 'error');
      else if (code === 'farm_not_found') setStatus(view, MESSAGES.farmNotFound, 'error');
      else setStatus(view, err.message, 'error');
      focusFirstInvalid(form);
    } finally {
      setBusy(form, false);
    }
  });

  router.route('add-plot', { onEnter: open });
}

export function mountAccountPages(router) {
  mountEditProfile(router);
  mountChangePassword(router);
  mountAddPlot(router);
}
