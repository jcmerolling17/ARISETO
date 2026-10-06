// frontend/public/js/router.js

const HASH_PREFIX = '#/';

/**
 * Minimal hash router that toggles pre-rendered <section data-view="name"> elements.
 *
 * Routes:   { name: { title } }
 * Hooks:    router.route(name, { onEnter({ state, from, initial }), onLeave({ to }) })
 * Navigate: <a href="#/login"> or router.navigate('login', { state, replace })
 */
export class Router {
  #routes = new Map();
  #order = [];
  #defaultRoute;
  #titleSuffix;
  #current = null;
  #pendingState;
  #listeners = new Set();
  #onHashChange = () => this.#resolve();

  constructor({ root = document, routes, defaultRoute, titleSuffix = 'ARISETO' }) {
    for (const [name, config] of Object.entries(routes)) {
      const el = root.querySelector(`[data-view="${name}"]`);
      if (!el) throw new Error(`Router: no element found for view "${name}"`);
      this.#routes.set(name, { title: config.title ?? name, el, onEnter: null, onLeave: null });
      this.#order.push(name);
    }
    if (!this.#routes.has(defaultRoute)) {
      throw new Error(`Router: default route "${defaultRoute}" is not defined`);
    }
    this.#defaultRoute = defaultRoute;
    this.#titleSuffix = titleSuffix;
  }

  get current() {
    return this.#current;
  }

  route(name, { onEnter, onLeave } = {}) {
    const route = this.#routes.get(name);
    if (!route) throw new Error(`Router: cannot attach hooks to unknown route "${name}"`);
    if (onEnter) route.onEnter = onEnter;
    if (onLeave) route.onLeave = onLeave;
    return this;
  }

  start() {
    window.addEventListener('hashchange', this.#onHashChange);
    this.#resolve({ initial: true });
    return this;
  }

  stop() {
    window.removeEventListener('hashchange', this.#onHashChange);
  }

  navigate(name, { state, replace = false } = {}) {
    if (!this.#routes.has(name)) throw new Error(`Router: unknown route "${name}"`);
    const hash = HASH_PREFIX + name;
    this.#pendingState = state;

    if (replace || location.hash === hash) {
      history.replaceState(history.state, '', hash);
      this.#resolve({ force: location.hash === hash && this.#current === name });
    } else {
      location.hash = hash;
    }
  }

  back(fallback = this.#defaultRoute) {
    if (history.length > 1) history.back();
    else this.navigate(fallback, { replace: true });
  }

  onChange(listener) {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  #parse() {
    const { hash } = location;
    if (!hash.startsWith(HASH_PREFIX)) return '';
    const path = hash.slice(HASH_PREFIX.length).split('?')[0].replace(/\/+$/, '');
    try {
      return decodeURIComponent(path);
    } catch {
      return '';
    }
  }

  #resolve({ initial = false, force = false } = {}) {
    let name = this.#parse();
    if (!this.#routes.has(name)) {
      name = this.#defaultRoute;
      history.replaceState(history.state, '', HASH_PREFIX + name);
    }

    const state = this.#pendingState;
    this.#pendingState = undefined;

    if (name === this.#current && !force) return;

    const from = this.#current;
    const prev = from ? this.#routes.get(from) : null;
    const next = this.#routes.get(name);

    if (initial) {
      for (const [other, route] of this.#routes) route.el.hidden = other !== name;
    }

    if (prev && from !== name) {
      prev.onLeave?.({ to: name });
      prev.el.hidden = true;
      prev.el.classList.remove('is-entering');
    }

    const direction = from && this.#order.indexOf(name) < this.#order.indexOf(from) ? 'back' : 'forward';
    next.el.dataset.direction = direction;
    next.el.hidden = false;
    if (!initial && from !== name) {
      next.el.classList.remove('is-entering');
      void next.el.offsetWidth; // restart the entry animation
      next.el.classList.add('is-entering');
    }

    document.title = `${next.title} · ${this.#titleSuffix}`;
    this.#current = name;

    next.onEnter?.({ state, from, initial });

    if (!initial && from !== name) {
      const focusTarget = next.el.querySelector('[data-route-focus]') ?? next.el;
      focusTarget.focus({ preventScroll: true });
      next.el.closest('.viewport')?.scrollTo?.(0, 0);
      window.scrollTo(0, 0);
    }

    for (const listener of this.#listeners) listener(name, from);
  }
}
