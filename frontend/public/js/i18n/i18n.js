// frontend/public/js/i18n/i18n.js

import { EN } from './en.js';
import { FIL } from './fil.js';

/**
 * Interface language for farmer screens (Phase 15): English (default) or Filipino.
 * The choice is kept on the phone, so it works offline and before signing in.
 * A string missing from fil.js falls back to English. The Admin Portal stays English.
 */
export const LANGUAGES = ['en', 'fil'];
const STORAGE_KEY = 'ariseto.language';
const TABLES = { en: EN, fil: FIL };

function readSaved() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return LANGUAGES.includes(saved) ? saved : 'en';
  } catch {
    return 'en';
  }
}

let current = readSaved();

export function getLanguage() {
  return current;
}

/** Fills {name} placeholders from vars; unknown names are left as they are. */
function format(text, vars) {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match));
}

/** The text for key in the current language, English when it has no Filipino text. */
export function t(key, vars) {
  const text = TABLES[current][key] ?? EN[key];
  if (text === undefined) return key;
  return format(text, vars);
}

/** The English text for key, for screens that stay in English (the Admin Portal). */
export function tEn(key, vars) {
  return key in EN ? format(EN[key], vars) : key;
}

/** True when key has text (in English, which every key has). */
export function hasText(key) {
  return key in EN;
}

/**
 * A page's message table read through t(): MESSAGES.saved is t('ns.saved'), and an entry
 * whose English text has {0}, {1}… placeholders is a function of those values. An unknown
 * entry is undefined, so lookups like MESSAGES[err.code] keep working.
 */
export function messages(ns) {
  return new Proxy({}, {
    get(target, prop) {
      if (typeof prop !== 'string') return undefined;
      const key = `${ns}.${prop}`;
      if (!(key in EN)) return undefined;
      if (/\{\d+\}/.test(EN[key])) {
        return (...args) => t(key, Object.fromEntries(args.map((value, i) => [i, value])));
      }
      return t(key);
    },
    has(target, prop) {
      return typeof prop === 'string' && `${ns}.${prop}` in EN;
    },
  });
}

/**
 * Applies the current language to static markup: data-i18n sets the text, and
 * data-i18n-attr="placeholder:key;aria-label:key" sets attributes.
 */
export function applyI18n(root = document) {
  const scope = root.querySelectorAll ? root : document;
  // Templates are cloned by the screens, so their markup is labelled too.
  scope.querySelectorAll('template').forEach((tpl) => applyI18n(tpl.content));
  scope.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  scope.querySelectorAll('[data-i18n-attr]').forEach((el) => {
    el.dataset.i18nAttr.split(';').forEach((pair) => {
      const [attr, key] = pair.split(':');
      if (attr && key) el.setAttribute(attr, t(key));
    });
  });
  if (root === document) document.documentElement.lang = current === 'fil' ? 'fil' : 'en';
}

/**
 * Adds options ({ value, label }) to a select and re-labels them when the language changes
 * (labels are read through getters, see data/farm-options.js).
 */
export function addOptions(select, options) {
  for (const option of options) select.add(new Option(option.label, option.value));
  window.addEventListener('ariseto:language', () => {
    for (const option of options) {
      const el = [...select.options].find((o) => o.value === option.value);
      if (el) el.text = option.label;
    }
  });
}

/**
 * Switches the language at once: saves it, re-labels the static markup and tells the
 * screens (event "ariseto:language") so they redraw their own text.
 */
export function setLanguage(lang) {
  if (!LANGUAGES.includes(lang) || lang === current) return;
  current = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* storage unavailable; the choice lasts for this page only */
  }
  applyI18n(document);
  window.dispatchEvent(new CustomEvent('ariseto:language', { detail: { lang } }));
}
