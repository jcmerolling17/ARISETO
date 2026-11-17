// frontend/public/js/pages/chatbot.js

/**
 * Chatbot (DFD 6.0; POST /chat/messages, GET /chat/sessions and their messages).
 * On open, the newest conversation is reloaded; questions continue it, with the saved farm
 * for the farm-data answers. Each reply shows its guide in small text; the fallback reply
 * (no intent) offers the topic chips, which are also above the question bar.
 */
import { ApiError, chat } from '../api/client.js';
import { TIME_ZONE } from '../api/weather.js';
import { savedFarm } from '../utils/saved-farm.js';

// Sent as questions; the team's examples.csv includes these exact phrases.
const CHIPS = ['Weather Check', "Today's Tasks"];
const PAGE_SIZE = 200; // the most messages one history request returns
const MAX_PAGES = 5;

const MESSAGES = {
  unavailable: 'The chatbot isn’t available yet. Please try again later.',
  offline: 'The chatbot needs an internet connection. Connect and try again.',
  loadFailed: 'Your conversation could not be loaded. Check your connection and try again.',
};

function isSessionEnd(err) {
  return err instanceof ApiError && err.sessionEnded;
}

function formatClock(iso) {
  return new Date(iso).toLocaleTimeString('en-PH', { timeZone: TIME_ZONE, hour: 'numeric', minute: '2-digit' });
}

/** The saved farm's id for the farm-data answers, or null without one. */
async function farmId() {
  try {
    return (await savedFarm())?.farm_id ?? null;
  } catch {
    return null;
  }
}

export function mountChatbotPage(router) {
  const view = document.querySelector('[data-view="chatbot"]');
  const log = view.querySelector('[data-chat-log]');
  const emptyNote = view.querySelector('[data-chat-empty]');
  const status = view.querySelector('[data-chat-status]');
  const chipBar = view.querySelector('[data-chips]');
  const form = view.querySelector('[data-chat-form]');
  const input = view.querySelector('[data-chat-input]');
  const tpl = view.querySelector('template[data-message-tpl]').content.firstElementChild;

  let sessionId = null;
  let messages = [];
  let pending = null; // the question being sent, shown with "Typing…"
  let generation = 0;

  function setStatus(message, tone = '') {
    status.textContent = message;
    status.dataset.tone = tone;
  }

  function chipButton(text) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'chat-chip';
    button.textContent = text;
    button.addEventListener('click', () => send(text));
    return button;
  }

  function messageItem(message) {
    const item = tpl.cloneNode(true);
    const isBot = message.sender === 'bot';
    item.classList.add(isBot ? 'chat-msg--bot' : 'chat-msg--user');
    item.querySelector('[data-avatar]').hidden = !isBot;
    item.querySelector('[data-text]').textContent = message.message_text;
    item.querySelector('[data-time]').textContent = formatClock(message.created_at);
    const source = item.querySelector('[data-source]');
    source.hidden = !(isBot && message.source_reference);
    if (!source.hidden) source.textContent = `Source: ${message.source_reference}`;
    // The fallback reply (no intent) suggests the topics.
    if (isBot && message.intent_tag == null) {
      const chips = item.querySelector('[data-msg-chips]');
      chips.hidden = false;
      chips.replaceChildren(...CHIPS.map(chipButton));
    }
    return item;
  }

  function typingItem() {
    const dots = tpl.cloneNode(true);
    dots.classList.add('chat-msg--bot', 'chat-msg--typing');
    dots.querySelector('[data-text]').textContent = 'Typing…';
    dots.querySelector('[data-time]').hidden = true;
    return dots;
  }

  function render() {
    const items = messages.map(messageItem);
    if (pending) items.push(messageItem(pending), typingItem());
    log.replaceChildren(...items);
    emptyNote.hidden = items.length > 0;
    items[items.length - 1]?.scrollIntoView({ block: 'end' });
  }

  /** The newest conversation, all of its messages oldest first. */
  async function load() {
    const gen = (generation += 1);
    setStatus('');
    try {
      const [latest] = (await chat.sessions({ limit: 1 })) ?? [];
      let loaded = [];
      if (latest) {
        for (let page = 0; page < MAX_PAGES; page += 1) {
          const batch = (await chat.messages(latest.session_id, { limit: PAGE_SIZE, offset: loaded.length })) ?? [];
          loaded = loaded.concat(batch);
          if (batch.length < PAGE_SIZE) break;
        }
      }
      if (gen !== generation) return;
      sessionId = latest?.session_id ?? null;
      messages = loaded;
      render();
    } catch (err) {
      if (gen !== generation || isSessionEnd(err)) return;
      render();
      setStatus(navigator.onLine === false ? MESSAGES.offline : MESSAGES.loadFailed, 'error');
    }
  }

  async function ask(text, farm) {
    try {
      return await chat.send({ message: text, sessionId, farmId: farm });
    } catch (err) {
      // The conversation is gone (or belongs to someone else): start a new one.
      if (err.code !== 'session_not_found' || sessionId == null) throw err;
      sessionId = null;
      return chat.send({ message: text, farmId: farm });
    }
  }

  async function send(raw) {
    const text = raw.trim();
    if (!text || pending) return;
    if (navigator.onLine === false) {
      setStatus(MESSAGES.offline, 'error');
      return;
    }
    setStatus('');
    input.value = '';
    pending = { sender: 'user', message_text: text, created_at: new Date().toISOString() };
    render();
    try {
      const result = await ask(text, await farmId());
      sessionId = result.session_id;
      messages.push({ sender: 'user', ...result.user_message }, { sender: 'bot', ...result.reply });
      pending = null;
      render();
    } catch (err) {
      pending = null;
      render();
      if (isSessionEnd(err)) return;
      input.value = text; // nothing was saved, so the question can be sent again
      if (err.code === 'model_unavailable') setStatus(MESSAGES.unavailable, 'error');
      else setStatus(navigator.onLine === false ? MESSAGES.offline : err.message, 'error');
    }
  }

  chipBar.replaceChildren(...CHIPS.map(chipButton));

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    send(input.value);
  });

  router.route('chatbot', {
    onEnter() {
      if (!pending) load();
      else render();
    },
    onLeave() {
      generation += 1;
    },
  });
}
