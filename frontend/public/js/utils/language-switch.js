// frontend/public/js/utils/language-switch.js

import { getLanguage, setLanguage } from '../i18n/i18n.js';

/**
 * Binds every language switch ([data-lang-switch] with [data-lang] buttons): EN | FIL on
 * Welcome and English | Filipino on Profile. A tap applies the language at once.
 */
export function mountLanguageSwitches(root = document) {
  const buttons = [...root.querySelectorAll('[data-lang-switch] [data-lang]')];

  function mark() {
    const lang = getLanguage();
    buttons.forEach((btn) => btn.setAttribute('aria-pressed', String(btn.dataset.lang === lang)));
  }

  buttons.forEach((btn) => btn.addEventListener('click', () => setLanguage(btn.dataset.lang)));
  window.addEventListener('ariseto:language', mark);
  mark();
}
