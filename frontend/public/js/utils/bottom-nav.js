// frontend/public/js/utils/bottom-nav.js

/**
 * Fills every <nav data-bottom-nav="home|yield|scan|calendar|expenses"> with the shared
 * bottom navigation from <template id="bottom-nav-template">, marking its own tab active.
 */
export function mountBottomNavs(root = document) {
  const template = root.getElementById('bottom-nav-template');

  root.querySelectorAll('[data-bottom-nav]').forEach((nav) => {
    nav.replaceChildren(template.content.cloneNode(true));
    const active = nav.querySelector(`[data-nav-item="${nav.dataset.bottomNav}"]`);
    if (!active) return;
    active.classList.add('is-active');
    active.setAttribute('aria-current', 'page');
  });
}
