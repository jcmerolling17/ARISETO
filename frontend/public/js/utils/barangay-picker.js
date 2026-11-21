// frontend/public/js/utils/barangay-picker.js

import { barangays } from '../api/client.js';
import { messages, t } from '../i18n/i18n.js';

const cache = new Map();

const TEXT = messages('barangay');

/** Barangays of a municipality from GET /barangays, cached per municipality. */
function loadBarangays(municipality) {
  if (!cache.has(municipality)) {
    const pending = barangays.list(municipality).then((list) => (Array.isArray(list) ? list : []));
    pending.catch(() => cache.delete(municipality));
    cache.set(municipality, pending);
  }
  return cache.get(municipality);
}

/**
 * Fills a barangay <select> from the chosen municipality (BARANGAY lookup).
 * The select's value is barangay_id; selected() returns the full row, including
 * center_latitude/center_longitude used as the farm location fallback.
 *
 * options: { placeholder, emptyPlaceholder (strings keys), onChange }
 */
export function mountBarangayPicker(municipalitySelect, barangaySelect, {
  placeholder = 'h.barangay',
  emptyPlaceholder = 'h.choose_municipality_first',
  onChange,
} = {}) {
  const hint = barangaySelect.closest('.field')?.querySelector('[data-barangay-hint]');
  let rows = [];
  let requestId = 0;

  function setHint(message) {
    if (hint) hint.textContent = message;
  }

  function showPlaceholder(text) {
    barangaySelect.replaceChildren(new Option(text, ''));
  }

  // The first option reads "Choose barangay" in the current language.
  window.addEventListener('ariseto:language', () => {
    const first = barangaySelect.options[0];
    if (!first || first.value) return;
    first.text = municipalitySelect.value && rows.length ? t(placeholder) : t(emptyPlaceholder);
  });

  async function refresh() {
    const municipality = municipalitySelect.value;
    const id = (requestId += 1);
    rows = [];
    barangaySelect.disabled = true;
    setHint('');

    if (!municipality) {
      showPlaceholder(t(emptyPlaceholder));
      onChange?.();
      return;
    }

    showPlaceholder(TEXT.loading);
    try {
      const list = await loadBarangays(municipality);
      if (id !== requestId) return;
      rows = list;
      showPlaceholder(list.length ? t(placeholder) : TEXT.empty);
      for (const row of list) barangaySelect.add(new Option(row.barangay_name, String(row.barangay_id)));
      barangaySelect.disabled = !list.length;
    } catch {
      if (id !== requestId) return;
      showPlaceholder(t(emptyPlaceholder));
      setHint(TEXT.failed);
    }
    onChange?.();
  }

  municipalitySelect.addEventListener('change', refresh);
  barangaySelect.addEventListener('change', () => onChange?.());

  return {
    /** The selected BARANGAY row, or null. */
    selected() {
      return rows.find((row) => String(row.barangay_id) === barangaySelect.value) ?? null;
    },
    reset() {
      requestId += 1;
      rows = [];
      barangaySelect.disabled = true;
      showPlaceholder(t(emptyPlaceholder));
      setHint('');
    },
  };
}
