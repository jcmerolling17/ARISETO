// frontend/public/js/pages/disease.js

import { sampleFarm, emptyFarm } from '../data/sample-farm.js';
import { sampleDisease, emptyDisease } from '../data/sample-disease.js';
import { DIAGNOSIS_CONFIDENCE_THRESHOLD } from '../data/farm-options.js';
import { pickDemo } from '../utils/demo.js';
import { currentCycle, fieldLabel } from '../utils/farm.js';

const MAX_PHOTO_BYTES = 15 * 1024 * 1024;
const ANALYZE_MS = 900; // a short pause so the prototype reads like a real check

const MESSAGES = {
  checking: 'Checking the leaf…',
  offline: 'Disease detection needs an internet connection. Connect and try again.',
  notImage: 'Choose a photo (JPG or PNG).',
  tooLarge: 'This photo is too large. Choose one under 15 MB.',
  diseasedOnlyCorn: 'The sample disease is for corn; pick a corn field to see it.',
};

/** The last photo taken or uploaded, and which sample result the prototype shows for it. */
const lastScan = { photoUrl: null, fieldId: null, status: 'diseased', scannedAt: null };

function data() {
  return { farm: pickDemo(sampleFarm, emptyFarm), disease: pickDemo(sampleDisease, emptyDisease) };
}

function plantedFields(farm) {
  return farm.fields.filter((field) => currentCycle(farm, field.field_id));
}

/* ---------- Capture ---------- */

function mountCapture(router) {
  const view = document.querySelector('[data-view="scan"]');
  const picker = view.querySelector('[data-scan-field]');
  const cropLine = view.querySelector('[data-scan-crop]');
  const preview = view.querySelector('[data-preview]');
  const hint = view.querySelector('[data-frame-hint]');
  const status = view.querySelector('[data-scan-status]');
  const inputs = view.querySelectorAll('[data-camera], [data-upload]');
  const diseasedOption = view.querySelector('[data-demo-diseased]');
  let timer = 0;

  function setStatus(message, tone = '') {
    status.textContent = message;
    status.dataset.tone = tone;
  }

  function syncCrop() {
    const { farm } = data();
    const cycle = currentCycle(farm, Number(picker.value));
    cropLine.textContent = cycle ? `Crop: ${cycle.crop_name}` : '';
    const isCorn = cycle?.crop_name === 'Corn';
    diseasedOption.disabled = !isCorn;
    diseasedOption.closest('label').title = isCorn ? '' : MESSAGES.diseasedOnlyCorn;
    if (!isCorn && diseasedOption.checked) view.querySelector('input[name="demo-result"][value="healthy"]').checked = true;
  }

  function onPhoto(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (navigator.onLine === false) return setStatus(MESSAGES.offline, 'error');
    if (!file.type.startsWith('image/')) return setStatus(MESSAGES.notImage, 'error');
    if (file.size > MAX_PHOTO_BYTES) return setStatus(MESSAGES.tooLarge, 'error');

    if (lastScan.photoUrl) URL.revokeObjectURL(lastScan.photoUrl);
    lastScan.photoUrl = URL.createObjectURL(file);
    lastScan.fieldId = Number(picker.value);
    lastScan.status = view.querySelector('input[name="demo-result"]:checked').value;
    lastScan.scannedAt = new Date();
    preview.src = lastScan.photoUrl;
    preview.hidden = false;
    hint.hidden = true;
    setStatus(MESSAGES.checking);
    inputs.forEach((input) => { input.disabled = true; });
    timer = setTimeout(() => router.navigate('scan-result'), ANALYZE_MS);
  }

  inputs.forEach((input) => input.addEventListener('change', onPhoto));
  picker.addEventListener('change', syncCrop);

  router.route('scan', {
    onEnter() {
      const { farm } = data();
      const fields = plantedFields(farm);
      view.querySelector('[data-empty]').hidden = fields.length > 0;
      view.querySelector('[data-content]').hidden = fields.length === 0;
      picker.replaceChildren(...fields.map((f) => new Option(fieldLabel(farm, f), String(f.field_id))));
      picker.disabled = fields.length === 0;
      picker.closest('.field-picker').hidden = fields.length === 0;
      if (fields.some((f) => f.field_id === lastScan.fieldId)) picker.value = String(lastScan.fieldId);
      preview.hidden = true;
      preview.removeAttribute('src');
      hint.hidden = false;
      inputs.forEach((input) => { input.disabled = false; });
      setStatus('');
      syncCrop();
    },
    onLeave() {
      clearTimeout(timer);
    },
  });
}

/* ---------- Results ---------- */

function mountResults(router) {
  const view = document.querySelector('[data-view="scan-result"]');
  const field = (name) => view.querySelector(`[data-${name}]`);
  const block = (name) => view.querySelector(`[data-block="${name}"]`);

  function list(el, items) {
    el.replaceChildren(...items.map((text) => {
      const li = document.createElement('li');
      li.textContent = text;
      return li;
    }));
  }

  function render() {
    const { farm, disease } = data();
    const statusKey = lastScan.photoUrl ? lastScan.status : 'diseased';
    const result = disease.results[statusKey];
    const fields = plantedFields(farm);
    const scanned = fields.find((f) => f.field_id === lastScan.fieldId)
      ?? fields.find((f) => currentCycle(farm, f.field_id).crop_name === 'Corn');

    view.querySelector('[data-empty]').hidden = Boolean(result && scanned);
    view.querySelector('[data-content]').hidden = !(result && scanned);
    field('result-img').hidden = !lastScan.photoUrl;
    if (lastScan.photoUrl) field('result-img').src = lastScan.photoUrl;
    field('result-placeholder').hidden = Boolean(lastScan.photoUrl);
    if (!result || !scanned) return;

    const crop = currentCycle(farm, scanned.field_id).crop_name;
    const percent = Math.round(result.confidence * 100);
    const when = lastScan.scannedAt ?? new Date();
    field('result-for').textContent = `${fieldLabel(farm, scanned)} · scanned ${when.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' })}`;
    field('retake').hidden = result.result_status !== 'unrecognized';
    view.dataset.result = result.result_status;

    if (result.result_status === 'diseased') {
      const info = disease.diseases.find((d) => d.disease_id === result.disease_id);
      field('result-title').textContent = info.disease_name;
      field('result-confidence').textContent = `${percent}% confidence`;
      field('description').textContent = info.description;
      field('signs-title').textContent = 'Warning Signs';
      list(field('signs'), info.symptoms);
      field('actions-title').textContent = 'Recommended Actions';
      list(field('actions'), [...info.treatments].sort((a, b) => a.step_no - b.step_no).map((t) => t.instruction_en));
      field('source').textContent = `Source: ${info.treatments[0]?.source_reference ?? ''}`;
      field('why').textContent = info.why_it_matters;
    } else if (result.result_status === 'healthy') {
      field('result-title').textContent = 'Healthy Leaf';
      field('result-confidence').textContent = `${percent}% confidence`;
      field('description').textContent = `No disease was found on this ${crop.toLowerCase()} leaf.`;
      field('actions-title').textContent = 'Keep it healthy';
      list(field('actions'), disease.healthy_tips);
    } else {
      field('result-title').textContent = 'Leaf Not Recognized';
      field('result-confidence').textContent = `${percent}% confidence, below the ${Math.round(DIAGNOSIS_CONFIDENCE_THRESHOLD * 100)}% needed for a diagnosis`;
      field('description').textContent = 'ARISETO could not identify a disease in this photo. It may be blurry or dark, '
        + 'or show a condition the model was not trained on.';
      field('actions-title').textContent = 'Retake tips';
      list(field('actions'), disease.retake_tips);
    }

    const diseased = result.result_status === 'diseased';
    block('signs').hidden = !diseased;
    block('why').hidden = !diseased;
    field('source').hidden = !diseased;
  }

  router.route('scan-result', { onEnter: render });
}

export function mountDiseasePages(router) {
  mountCapture(router);
  mountResults(router);
}
