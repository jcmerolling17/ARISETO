// frontend/public/js/pages/chatbot.js

import { sampleChatbot, emptyChatbot } from '../data/sample-chatbot.js';
import { pickDemo } from '../utils/demo.js';

const REPLY_DELAY_MS = 700;

/**
 * Typed words matched against each intent's example phrases (whole words only, so "hi" does
 * not match "this"); the intent with the most matched text answers.
 */
function matchIntent(intents, text) {
  const words = ` ${text.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, ' ').replace(/\s+/g, ' ').trim()} `;
  let best = null;
  for (const intent of intents.filter((i) => i.is_active)) {
    const hits = intent.patterns.filter((p) => words.includes(` ${p} `));
    const score = hits.reduce((sum, p) => sum + p.length, 0);
    if (score > 0 && (!best || score > best.score)) best = { intent, score };
  }
  return best?.intent ?? null;
}

function formatClock(iso) {
  return new Date(iso).toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' });
}

export function mountChatbotPage(router) {
  const view = document.querySelector('[data-view="chatbot"]');
  const log = view.querySelector('[data-chat-log]');
  const emptyNote = view.querySelector('[data-chat-empty]');
  const chipBar = view.querySelector('[data-chips]');
  const form = view.querySelector('[data-chat-form]');
  const input = view.querySelector('[data-chat-input]');
  const tpl = view.querySelector('template[data-message-tpl]').content.firstElementChild;
  let typing = false;
  let timer = 0;

  const data = () => pickDemo(sampleChatbot, emptyChatbot);
  const chipIntents = () => data().intents.filter((i) => i.chip && i.is_active);

  function chipButton(intent) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'chat-chip';
    button.textContent = intent.chip;
    button.addEventListener('click', () => send(intent.chip));
    return button;
  }

  function messageItem(message) {
    const item = tpl.cloneNode(true);
    const isBot = message.sender === 'bot';
    item.classList.add(isBot ? 'chat-msg--bot' : 'chat-msg--user');
    item.querySelector('[data-avatar]').hidden = !isBot;
    item.querySelector('[data-text]').textContent = message.message_text;
    item.querySelector('[data-time]').textContent = formatClock(message.created_at);
    // The fallback reply (no intent) suggests the quick topics.
    if (isBot && message.intent_id == null) {
      const chips = item.querySelector('[data-msg-chips]');
      chips.hidden = false;
      chips.replaceChildren(...chipIntents().map(chipButton));
    }
    return item;
  }

  function render() {
    const { messages } = data();
    const items = messages.map(messageItem);
    if (typing) {
      const dots = tpl.cloneNode(true);
      dots.classList.add('chat-msg--bot', 'chat-msg--typing');
      dots.querySelector('[data-text]').textContent = 'Typing…';
      dots.querySelector('[data-time]').hidden = true;
      items.push(dots);
    }
    log.replaceChildren(...items);
    emptyNote.hidden = items.length > 0;
    chipBar.replaceChildren(...chipIntents().map(chipButton));
    items[items.length - 1]?.scrollIntoView({ block: 'end' });
  }

  function addMessage(sender, text, intent = null, confidence = null) {
    const chat = data();
    if (!chat.session) chat.session = { session_id: 1, user_id: 6, started_at: new Date().toISOString() };
    chat.messages.push({
      message_id: Math.max(0, ...chat.messages.map((m) => m.message_id)) + 1,
      session_id: chat.session.session_id,
      sender,
      message_text: text,
      intent_id: intent?.intent_id ?? null,
      confidence,
      created_at: new Date().toISOString(),
    });
  }

  function send(raw) {
    const text = raw.trim().replace(/\s+/g, ' ');
    if (!text || typing) return;
    addMessage('user', text);
    typing = true;
    render();
    timer = setTimeout(() => {
      reply(text);
      render();
    }, REPLY_DELAY_MS);
  }

  /** The bot's answer to `text`; sample confidences sit above the 0.70 threshold for a match, below it for the fallback. */
  function reply(text) {
    const chat = data();
    const intent = matchIntent(chat.intents, text);
    if (intent) addMessage('bot', intent.response_en, intent, 0.86);
    else addMessage('bot', chat.fallback, null, 0.32);
    typing = false;
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    send(input.value);
    input.value = '';
  });

  router.route('chatbot', {
    onEnter: render,
    onLeave() {
      // Leaving mid-reply: answer at once so the question is not left unanswered.
      clearTimeout(timer);
      if (typing) {
        const { messages } = data();
        reply(messages[messages.length - 1].message_text);
      }
    },
  });
}
