// frontend/public/js/utils/demo.js

/**
 * Prototype screens read sample data (js/data/sample-*.js) until the backend serves it.
 * Add ?demo=empty to a screen's address (e.g. #/calendar?demo=empty) to see its empty state.
 */
export function isEmptyDemo() {
  const query = location.hash.split('?')[1] ?? '';
  return new URLSearchParams(query).get('demo') === 'empty';
}

/** The full sample data, or its empty version when ?demo=empty is set. */
export function pickDemo(sample, empty) {
  return isEmptyDemo() ? empty : sample;
}
