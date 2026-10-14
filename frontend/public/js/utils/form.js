// frontend/public/js/utils/form.js

export function setFieldError(input, message) {
  const errorEl = document.getElementById(`${input.id}-error`);
  if (message) {
    input.setAttribute('aria-invalid', 'true');
  } else {
    input.removeAttribute('aria-invalid');
  }
  if (errorEl) errorEl.textContent = message || '';
}

export function clearFieldErrors(form) {
  form.querySelectorAll('.input').forEach((input) => setFieldError(input, ''));
}

export function setStatus(container, message, tone = 'error') {
  const statusEl = container.querySelector('[data-form-status]');
  if (!statusEl) return;
  statusEl.textContent = message || '';
  if (message) statusEl.dataset.tone = tone;
  else delete statusEl.dataset.tone;
}

export function setBusy(form, busy) {
  const submit = form.querySelector('[type="submit"]');
  form.setAttribute('aria-busy', String(busy));
  if (submit) {
    submit.disabled = busy;
    submit.classList.toggle('is-loading', busy);
  }
}

export function focusFirstInvalid(form) {
  form.querySelector('[aria-invalid="true"]')?.focus();
}

export function bindLiveErrorClearing(form) {
  form.addEventListener('input', (event) => {
    if (event.target.matches('.input[aria-invalid="true"]')) setFieldError(event.target, '');
  });
}
