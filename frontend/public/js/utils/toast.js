// frontend/public/js/utils/toast.js

const TOAST_MS = 2600;

let toastEl = null;
let timer = 0;

/** Shows message for TOAST_MS, or for durationMs when a longer message needs more time. */
export function showToast(message, durationMs = TOAST_MS) {
  if (!toastEl) return;
  clearTimeout(timer);
  toastEl.textContent = message;
  toastEl.hidden = false;
  timer = setTimeout(() => { toastEl.hidden = true; }, durationMs);
}

export function hideToast() {
  if (!toastEl) return;
  clearTimeout(timer);
  toastEl.hidden = true;
}

/**
 * One toast for the whole app. Any element with data-soon="Feature" shows
 * "Feature is coming soon." when tapped; the toast hides on every screen change.
 */
export function mountToast(router) {
  toastEl = document.querySelector('[data-app-toast]');

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-soon]');
    if (trigger) showToast(`${trigger.dataset.soon} is coming soon.`);
  });

  router.onChange(hideToast);
}
