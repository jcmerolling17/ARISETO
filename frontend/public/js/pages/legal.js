// frontend/public/js/pages/legal.js

/**
 * Terms & Conditions and Privacy Policy screens. Opened from sign-up they show Accept and
 * Decline, and the answer is handed back to the sign-up form; opened from Profile (or a link)
 * they are read-only with a back button.
 */
const DOCUMENTS = ['terms', 'privacy'];

let pendingAnswer = null;

/** The last Accept or Decline from a legal screen ({ doc, accepted }), once; null if none. */
export function takeLegalAnswer() {
  const answer = pendingAnswer;
  pendingAnswer = null;
  return answer;
}

export function mountLegalPages(router) {
  for (const doc of DOCUMENTS) {
    const view = document.querySelector(`[data-view="${doc}"]`);
    const actions = view.querySelector('[data-legal-actions]');
    let cameFrom = null;

    function leave(answer) {
      if (answer) pendingAnswer = { doc, accepted: answer === 'accept' };
      if (cameFrom) router.back(cameFrom);
      else router.navigate('welcome', { replace: true });
    }

    view.querySelector('[data-legal-back]').addEventListener('click', (event) => {
      event.preventDefault();
      leave(null);
    });
    view.querySelector('[data-legal-accept]').addEventListener('click', () => leave('accept'));
    view.querySelector('[data-legal-decline]').addEventListener('click', () => leave('decline'));

    router.route(doc, {
      onEnter({ from }) {
        cameFrom = from;
        actions.hidden = from !== 'signup';
      },
    });
  }
}
