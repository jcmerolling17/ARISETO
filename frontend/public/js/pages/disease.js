// frontend/public/js/pages/disease.js

/**
 * Disease detection (DFD 3.1-3.8; POST and GET /diagnoses).
 * Diagnosis Entries: pick the field (its current crop cycle gives the crop) or, with no planted
 * field, the crop; take or upload a photo, which is resized to at most 1024 px as JPEG and
 * scanned online. Recent Scans lists the member's scans, 20 at a time.
 * Detection Results: the saved result with its photo, fetched with the token.
 */
import { ApiError, crops, diagnoses, farms, users } from '../api/client.js';
import { TIME_ZONE } from '../api/weather.js';
import { savedFarm } from '../utils/saved-farm.js';

const PAGE_SIZE = 20;
const MAX_SIDE = 1024; // longest side sent to the server
const JPEG_QUALITY = 0.9;

const MESSAGES = {
  checking: 'Checking the leaf…',
  offline: 'Scanning needs an internet connection. Connect and try again.',
  unavailable: 'Disease detection isn’t available yet. Please try again later.',
  unreadable: 'This photo can’t be read. Choose a JPG or PNG photo.',
  tooLarge: 'This photo is too large. Choose a smaller one.',
  tooSmall: 'This photo is too small. Take a closer photo of the leaf.',
  fieldGone: 'That field is no longer available. Choose another one.',
  noCrop: 'Choose the crop first.',
  loadFailed: 'Your scans could not be loaded. Check your connection and try again.',
  resultFailed: 'This scan could not be loaded. Check your connection and try again.',
  noScans: 'No scans yet. Your scans will appear here.',
  pickerFailed: 'Your fields could not be loaded. Check your connection and try again.',
};

const SCAN_ERRORS = {
  model_unavailable: MESSAGES.unavailable,
  image_too_large: MESSAGES.tooLarge,
  unsupported_image_type: MESSAGES.unreadable,
  image_unreadable: MESSAGES.unreadable,
  image_too_small: MESSAGES.tooSmall,
  cycle_not_found: MESSAGES.fieldGone,
  crop_required: MESSAGES.noCrop,
  crop_not_found: MESSAGES.noCrop,
  crop_mismatch: MESSAGES.fieldGone,
};

const STATUS_TEXT = {
  diseased: 'Infection Detected',
  healthy: 'Healthy',
  unrecognized: 'Not recognized',
};

const TITLES = { healthy: 'Healthy Leaf', unrecognized: 'Leaf Not Recognized' };

// Photo instructions for a retake (not farming advice).
const RETAKE_TIPS = [
  'Take the photo in daylight, out of harsh direct sun.',
  'Fill the frame with one leaf and keep the affected spots in view.',
  'Hold the phone steady so the photo is not blurry.',
  'Only rice, corn, and onion leaves can be checked.',
];

/** The member's preferred language, looked up once ('en' when it can't be read). */
let languagePromise = null;
function preferredLanguage() {
  languagePromise ??= users.me().then((me) => me?.preferred_language ?? 'en', () => {
    languagePromise = null;
    return 'en';
  });
  return languagePromise;
}

/** Filipino text when the member chose Filipino and it is filled in; English otherwise. */
function localized(lang, fil, en) {
  return lang === 'fil' && fil?.trim() ? fil : en;
}

function isSessionEnd(err) {
  return err instanceof ApiError && err.sessionEnded;
}

/** "Today, 10:45 AM", "Yesterday, 4:05 PM" or "Nov 5, 8:00 AM", in Philippine time. */
function scanTime(iso) {
  const when = new Date(iso);
  const day = (date) => date.toLocaleDateString('en-CA', { timeZone: TIME_ZONE });
  const yesterday = new Date(Date.now() - 86400000);
  const time = when.toLocaleTimeString('en-PH', { timeZone: TIME_ZONE, hour: 'numeric', minute: '2-digit' });
  let label = when.toLocaleDateString('en-PH', { timeZone: TIME_ZONE, month: 'short', day: 'numeric' });
  if (day(when) === day(new Date())) label = 'Today';
  else if (day(when) === day(yesterday)) label = 'Yesterday';
  return `${label}, ${time}`;
}

/** The photo as a JPEG of at most 1024 px on its longest side (never enlarged). */
async function resizedJpeg(file) {
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  try {
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY));
    if (!blob) throw new Error('JPEG encoding failed');
    return blob;
  } finally {
    bitmap.close();
  }
}

/** The last result shown, so Detection Results can be reopened after leaving it. */
let lastResult = null;

/* ---------- Diagnosis Entries ---------- */

function mountHub(router) {
  const view = document.querySelector('[data-view="scan"]');
  const fieldPick = view.querySelector('[data-pick="field"]');
  const cropPick = view.querySelector('[data-pick="crop"]');
  const fieldSelect = view.querySelector('[data-scan-field]');
  const cropSelect = view.querySelector('[data-scan-crop]');
  const inputs = view.querySelectorAll('[data-camera], [data-upload]');
  const status = view.querySelector('[data-scan-status]');
  const list = view.querySelector('[data-scan-list]');
  const more = view.querySelector('[data-more]');
  const historyStatus = view.querySelector('[data-history-status]');
  const tpl = view.querySelector('template[data-scan-tpl]').content.firstElementChild;

  let fields = []; // planted fields: { field_id, field_name, current_cycle }
  let mode = 'field'; // 'field' or 'crop'
  let lastFieldId = null;
  let busy = false;
  let items = [];
  let thumbUrls = [];
  let generation = 0; // bumped on every load and on leave, so stale work is dropped

  function setStatus(message, tone = '') {
    status.textContent = message;
    status.dataset.tone = tone;
  }

  function setBusy(value) {
    busy = value;
    inputs.forEach((input) => { input.disabled = value; });
    fieldSelect.disabled = value;
    cropSelect.disabled = value;
  }

  async function loadPicker(gen) {
    fieldPick.hidden = true;
    cropPick.hidden = true;
    try {
      const farm = await savedFarm();
      const all = farm ? (await farms.fields(farm.farm_id)) ?? [] : [];
      if (gen !== generation) return;
      fields = all.filter((f) => f.current_cycle);
      if (fields.length) {
        mode = 'field';
        fieldSelect.replaceChildren(...fields.map((f) => new Option(
          `${f.field_name} (${f.current_cycle.crop_name})`, String(f.field_id),
        )));
        if (fields.some((f) => f.field_id === lastFieldId)) fieldSelect.value = String(lastFieldId);
        fieldPick.hidden = false;
        return;
      }
      const cropList = (await crops.list()) ?? [];
      if (gen !== generation) return;
      mode = 'crop';
      cropSelect.replaceChildren(...cropList.map((c) => new Option(c.crop_name, String(c.crop_id))));
      cropPick.hidden = false;
    } catch (err) {
      if (gen === generation && !isSessionEnd(err)) setStatus(MESSAGES.pickerFailed, 'error');
    }
  }

  function selectedField() {
    return fields.find((f) => f.field_id === Number(fieldSelect.value)) ?? null;
  }

  function revokeThumbs() {
    thumbUrls.forEach((url) => URL.revokeObjectURL(url));
    thumbUrls = [];
  }

  function renderItem(item) {
    const li = tpl.cloneNode(true);
    const outcome = item.result_status;
    li.dataset.id = String(item.diagnosis_id);
    li.querySelector('[data-tag]').textContent = item.field_name ?? item.crop_name;
    li.querySelector('[data-time]').textContent = scanTime(item.created_at);
    li.querySelector('[data-title]').textContent = outcome === 'diseased' ? item.disease_name : TITLES[outcome];
    li.querySelector('[data-status]').textContent = STATUS_TEXT[outcome];
    li.querySelector('.scan-card').dataset.result = outcome;
    li.querySelector('[data-open]').addEventListener('click', () => {
      router.navigate('scan-result', { state: { diagnosisId: item.diagnosis_id, fieldName: item.field_name } });
    });
    return li;
  }

  /** Thumbnails for the first page only, one at a time; the leaf icon stays if one fails. */
  async function loadThumbs(page, gen) {
    for (const item of page) {
      try {
        const blob = await diagnoses.image(item.diagnosis_id);
        if (gen !== generation) return;
        const url = URL.createObjectURL(blob);
        thumbUrls.push(url);
        const li = list.querySelector(`[data-id="${item.diagnosis_id}"]`);
        const img = li?.querySelector('[data-thumb]');
        if (!img) continue;
        img.onload = () => {
          img.hidden = false;
          li.querySelector('[data-thumb-icon]').hidden = true;
        };
        img.src = url;
      } catch (err) {
        if (gen !== generation || isSessionEnd(err)) return;
      }
    }
  }

  async function loadHistory({ append = false } = {}) {
    const gen = generation;
    more.disabled = true;
    historyStatus.textContent = '';
    try {
      const page = (await diagnoses.list({ limit: PAGE_SIZE, offset: append ? items.length : 0 })) ?? [];
      if (gen !== generation) return;
      items = append ? [...items, ...page] : page;
      if (append) list.append(...page.map(renderItem));
      else list.replaceChildren(...page.map(renderItem));
      more.hidden = page.length < PAGE_SIZE;
      if (!items.length) historyStatus.textContent = MESSAGES.noScans;
      if (!append) loadThumbs(page, gen);
    } catch (err) {
      if (gen === generation && !isSessionEnd(err)) historyStatus.textContent = MESSAGES.loadFailed;
    } finally {
      more.disabled = false;
    }
  }

  async function onPhoto(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || busy) return;
    if (navigator.onLine === false) return setStatus(MESSAGES.offline, 'error');

    const field = mode === 'field' ? selectedField() : null;
    const cropId = mode === 'crop' ? Number(cropSelect.value) || null : null;
    if (!field && !cropId) return setStatus(MESSAGES.noCrop, 'error');

    setBusy(true);
    setStatus(MESSAGES.checking);
    let image;
    try {
      image = await resizedJpeg(file);
    } catch {
      setBusy(false);
      return setStatus(MESSAGES.unreadable, 'error');
    }
    try {
      const result = await diagnoses.create({ image, cycleId: field?.current_cycle.cycle_id ?? null, cropId });
      lastFieldId = field?.field_id ?? lastFieldId;
      setStatus('');
      router.navigate('scan-result', {
        state: { result, photo: image, fieldName: field?.field_name ?? null },
      });
    } catch (err) {
      if (isSessionEnd(err)) return;
      const message = navigator.onLine === false ? MESSAGES.offline : SCAN_ERRORS[err.code] ?? err.message;
      setStatus(message, 'error');
      if (err.code === 'cycle_not_found') loadPicker(generation);
    } finally {
      setBusy(false);
    }
  }

  inputs.forEach((input) => input.addEventListener('change', onPhoto));
  fieldSelect.addEventListener('change', () => { lastFieldId = Number(fieldSelect.value); });
  more.addEventListener('click', () => loadHistory({ append: true }));

  router.route('scan', {
    onEnter() {
      generation += 1;
      revokeThumbs();
      items = [];
      list.replaceChildren();
      more.hidden = true;
      setBusy(false);
      setStatus('');
      preferredLanguage();
      loadPicker(generation);
      loadHistory();
    },
    onLeave() {
      generation += 1;
      revokeThumbs();
    },
  });
}

/* ---------- Detection Results ---------- */

function mountResults(router) {
  const view = document.querySelector('[data-view="scan-result"]');
  const field = (name) => view.querySelector(`[data-${name}]`);
  const block = (name) => view.querySelector(`[data-block="${name}"]`);
  const img = field('result-img');
  let photoUrl = null;
  let generation = 0;

  function setPhoto(blob) {
    if (photoUrl) URL.revokeObjectURL(photoUrl);
    photoUrl = blob ? URL.createObjectURL(blob) : null;
    img.hidden = !photoUrl;
    field('result-placeholder').hidden = Boolean(photoUrl);
    if (photoUrl) img.src = photoUrl;
    else img.removeAttribute('src');
  }

  function showEmpty(message) {
    field('empty').hidden = false;
    field('empty-text').textContent = message;
    field('content').hidden = true;
  }

  function fillList(el, entries) {
    el.replaceChildren(...entries.map(({ text, source }) => {
      const li = document.createElement('li');
      li.textContent = text;
      if (source) {
        const cite = document.createElement('span');
        cite.className = 'result-step-source';
        cite.textContent = `Source: ${source}`;
        li.append(cite);
      }
      return li;
    }));
  }

  function render({ result, fieldName }, lang) {
    const status = result.result_status;
    const disease = result.disease;
    view.dataset.result = status;
    field('empty').hidden = true;
    field('content').hidden = false;

    field('result-title').textContent = status === 'diseased' ? disease.disease_name : TITLES[status];
    const local = status === 'diseased' ? disease.local_name?.trim() : '';
    field('result-local').hidden = !local;
    field('result-local').textContent = local ? `Local name: ${local}` : '';
    // No percentage for "Not recognized": it was below the model team's threshold.
    field('result-confidence').hidden = status === 'unrecognized';
    field('result-confidence').textContent = `${Math.round(result.confidence * 100)}% confidence`;
    field('result-for').textContent = [result.crop_name, fieldName, scanTime(result.created_at)]
      .filter(Boolean).join(' · ');
    field('retake').hidden = status !== 'unrecognized';

    let description = '';
    let signs = [];
    let actions = [];
    let why = '';
    if (status === 'diseased') {
      description = localized(lang, disease.description_fil, disease.description_en) ?? '';
      signs = (disease.symptoms ?? '').split('\n').map((s) => s.trim()).filter(Boolean).map((text) => ({ text }));
      actions = disease.treatments.map((t) => ({
        text: localized(lang, t.instruction_fil, t.instruction_en),
        source: t.source_reference,
      }));
      why = localized(lang, disease.impact_fil, disease.impact_en) ?? '';
      field('actions-title').textContent = 'Recommended Actions';
    } else if (status === 'healthy') {
      description = `No disease was found on this ${result.crop_name.toLowerCase()} leaf.`;
    } else {
      description = 'ARISETO could not identify a disease in this photo. It may be blurry or dark, '
        + 'or show a condition the model was not trained on.';
      actions = RETAKE_TIPS.map((text) => ({ text }));
      field('actions-title').textContent = 'Retake tips';
    }

    field('description').textContent = description;
    fillList(field('signs'), signs);
    fillList(field('actions'), actions);
    field('why').textContent = why;
    block('description').hidden = !description.trim();
    block('signs').hidden = signs.length === 0;
    block('actions').hidden = actions.length === 0;
    block('why').hidden = !why.trim();
  }

  async function show(state) {
    const gen = (generation += 1);
    const lang = await preferredLanguage();
    if (gen !== generation) return;

    if (state?.result) {
      lastResult = { result: state.result, fieldName: state.fieldName ?? null };
      setPhoto(state.photo ?? null);
      render(lastResult, lang);
      if (!state.photo) loadPhoto(state.result.diagnosis_id, gen);
      return;
    }

    const diagnosisId = state?.diagnosisId ?? lastResult?.result.diagnosis_id;
    if (!diagnosisId) {
      setPhoto(null);
      return showEmpty('No scan yet. Take a photo of a leaf to check it.');
    }
    setPhoto(null);
    field('content').hidden = true;
    field('empty').hidden = true;
    try {
      const result = await diagnoses.get(diagnosisId);
      if (gen !== generation) return;
      const fieldName = state?.diagnosisId ? state.fieldName ?? null : lastResult?.fieldName ?? null;
      lastResult = { result, fieldName };
      render(lastResult, lang);
      loadPhoto(diagnosisId, gen);
    } catch (err) {
      if (gen !== generation || isSessionEnd(err)) return;
      showEmpty(err.code === 'diagnosis_not_found' ? 'This scan could not be found.' : MESSAGES.resultFailed);
    }
  }

  async function loadPhoto(diagnosisId, gen) {
    try {
      const blob = await diagnoses.image(diagnosisId);
      if (gen === generation) setPhoto(blob);
    } catch {
      // The leaf placeholder stays when the photo can't be loaded.
    }
  }

  router.route('scan-result', {
    onEnter({ state }) {
      show(state);
    },
    onLeave() {
      generation += 1;
      setPhoto(null);
    },
  });
}

export function mountDiseasePages(router) {
  mountHub(router);
  mountResults(router);
}
