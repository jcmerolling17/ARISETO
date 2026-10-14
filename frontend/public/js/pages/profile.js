// frontend/public/js/pages/profile.js

import { sampleProfile, emptyProfile } from '../data/sample-profile.js';
import { sampleFarm, emptyFarm } from '../data/sample-farm.js';
import { CROPS } from '../data/farm-options.js';
import { auth } from '../api/client.js';
import { pickDemo } from '../utils/demo.js';
import { currentCycle } from '../utils/farm.js';
import { removeJSON } from '../utils/store.js';
import { showToast } from '../utils/toast.js';

const MESSAGES = {
  online: ['Online', 'Connected to ARISETO'],
  offline: ['Offline', 'Calendar and expenses still work offline'],
  filipinoOn: 'Language set to Filipino. The app shows English until the Filipino text is added.',
  filipinoOff: 'Language set to English.',
  loggedOut: 'You have logged out.',
};

/** '+63 917 123 4567' from '+639171234567'. */
function formatMobile(mobile) {
  const match = /^\+63(\d{3})(\d{3})(\d{4})$/.exec(mobile ?? '');
  return match ? `+63 ${match[1]} ${match[2]} ${match[3]}` : mobile ?? '';
}

function formatHectares(value) {
  return `${Number(value).toLocaleString('en-PH', { maximumFractionDigits: 4 })} ha`;
}

export function mountProfilePage(router) {
  const view = document.querySelector('[data-view="profile"]');
  const plotList = view.querySelector('[data-plot-list]');
  const plotsEmpty = view.querySelector('[data-plots-empty]');
  const languageSwitch = view.querySelector('[data-language-switch]');
  const tpl = view.querySelector('template[data-plot-tpl]').content.firstElementChild;

  function data() {
    return { user: pickDemo(sampleProfile, emptyProfile).user, farm: pickDemo(sampleFarm, emptyFarm) };
  }

  function renderOnline() {
    const [title, text] = navigator.onLine === false ? MESSAGES.offline : MESSAGES.online;
    const status = view.querySelector('[data-online]');
    status.classList.toggle('is-offline', navigator.onLine === false);
    status.querySelector('[data-online-title]').textContent = title;
    status.querySelector('[data-online-text]').textContent = text;
  }

  function render() {
    const { user, farm } = data();
    const planted = farm.fields.filter((f) => currentCycle(farm, f.field_id));

    view.querySelector('[data-initials]').textContent = `${user.first_name[0] ?? ''}${user.last_name[0] ?? ''}`.toUpperCase();
    view.querySelector('[data-full-name]').textContent = `${user.first_name} ${user.last_name}`;
    view.querySelectorAll('[data-mobile]').forEach((el) => { el.textContent = formatMobile(user.mobile_no); });
    const plotCount = view.querySelector('[data-plot-count]');
    plotCount.textContent = `${planted.length} active ${planted.length === 1 ? 'plot' : 'plots'}`;
    plotCount.hidden = planted.length === 0;
    languageSwitch.checked = user.preferred_language === 'fil';
    renderOnline();

    plotList.replaceChildren(...farm.fields.map((field) => {
      const card = tpl.cloneNode(true);
      const cycle = currentCycle(farm, field.field_id);
      const crop = CROPS.find((c) => c.label === cycle?.crop_name);
      card.querySelector('[data-crop-icon]').setAttribute('href', `#${crop?.icon ?? 'icon-seeds'}`);
      card.querySelector('[data-name]').textContent = field.field_name;
      card.querySelector('[data-meta]').textContent = [cycle?.crop_name ?? 'Not planted', formatHectares(field.area_ha)].join(' · ');
      card.querySelector('[data-place]').textContent = farm.farm?.barangay_name ?? '';
      card.querySelector('[data-edit]').setAttribute('aria-label', `Edit ${field.field_name}`);
      card.querySelector('[data-remove]').setAttribute('aria-label', `Remove ${field.field_name}`);
      return card;
    }));
    plotsEmpty.hidden = farm.fields.length > 0;
  }

  languageSwitch.addEventListener('change', () => {
    const { user } = data();
    user.preferred_language = languageSwitch.checked ? 'fil' : 'en';
    showToast(languageSwitch.checked ? MESSAGES.filipinoOn : MESSAGES.filipinoOff);
  });

  // Log out for real: forget the session token and the saved user and farm, then go to Login.
  view.querySelector('[data-logout]').addEventListener('click', () => {
    auth.logout();
    removeJSON('user');
    removeJSON('farm');
    router.navigate('login', { replace: true, state: { message: MESSAGES.loggedOut, tone: 'success' } });
  });

  window.addEventListener('online', () => { if (!view.hidden) renderOnline(); });
  window.addEventListener('offline', () => { if (!view.hidden) renderOnline(); });

  router.route('profile', { onEnter: render });
}
