// Page bootstrap: loads /api/surface, opens /ws (reconnecting, a fresh snapshot each time), and wires every
// gesture to exactly one API call whose answer is shown (s8). Replica input (press, release, strip moves,
// encoder turns, Shift) goes out in order, one call at a time, with strip moves coalesced to the latest value.
// The page never asks the browser for MIDI access: it holds nothing that Bitwig could need (d24, A11).
import { createApi, socketUrl } from './api.js';
import { mount } from './dom.js';
import { activityView } from './activity.js';
import { bannerView, headerView } from './banner.js';
import { cardView } from './card.js';
import { helpView } from './help.js';
import { learnCardView, toolbarView } from './learn.js';
import {
  NAV_KEY, SIDE_KEY, capital, navFoldedByDefault, navView, remember, remembered, rememberedSide, sideByDefault,
} from './nav.js';
import { overviewView } from './overview.js';
import { buildReplica, playedView } from './replica.js';
import {
  createStore, currentModulePanel, modulePanels, ownedByUnit, sidePanels, unitView, viewOfAddress,
} from './state.js';
import { tweakKey, tweakView } from './tweak.js';

// --- gestures → API calls ------------------------------------------------------------------------------------
export function createHandlers(api, store, { onWindowPointerUp, remember: keep, fullscreen: screen } = {}) {
  let chain = Promise.resolve();
  let pendingMove = null;
  let moveQueued = false;
  const serial = (fn) => {
    const run = chain.then(fn, fn);
    chain = run.catch(() => {});
    return run;
  };
  const show = (answer, notice) => {
    if (!answer.ok) store.dispatch({ type: 'problem', problem: answer.problem, issues: answer.issues ?? [] });
    else if (notice) store.dispatch({ type: 'notice', text: notice });
    return answer;
  };
  const inspecting = () => store.model.ui.mode === 'inspect';
  // Inspect is for looking at cards: selecting a control there shows the card column (not remembered)
  const reveal = () => { if (store.model.ui.side !== 'card') store.dispatch({ type: 'side', panel: 'card' }); };
  // What the unit owns in its view is never pressed from the page; a press that went out is still let go
  const live = new Set();
  const owned = (id) => {
    if (!ownedByUnit(store.model, id)) return false;
    const view = capital(unitView(store.model));
    store.dispatch({ type: 'notice', text: /^pad /.test(id)
      ? `${view} view: the APC64 plays its pads itself; nothing was sent`
      : `${view} view: ${id} stays on the APC64; nothing was sent` });
    return true;
  };

  const handlers = {
    async select(id) {
      store.dispatch({ type: 'select', id });
      return handlers.refreshCard();
    },
    async refreshCard() {
      const id = store.model.ui.selected;
      if (!id) return null;
      const answer = await api.card(id);
      if (answer.ok) store.dispatch({ type: 'card', id, data: answer.data });
      else store.dispatch({ type: 'card_problem', problem: answer.problem });
      return answer;
    },
    // a view button (2026-10-27): Play asks the unit for that view, as pressing it on the unit would; Inspect looks
    view(id) {
      handlers.select(id);
      if (inspecting()) { reveal(); return Promise.resolve(null); }
      return serial(() => api.press(id)).then((a) => show(a));
    },
    // replica input: the same path as the unit's own (A70)
    down(id) {
      handlers.select(id);
      if (inspecting()) { reveal(); return Promise.resolve(null); }
      if (owned(id)) return Promise.resolve(null);
      live.add(id);
      return serial(() => api.press(id)).then((a) => show(a));
    },
    up(id) {
      if (inspecting() || !live.delete(id)) return Promise.resolve(null);
      return serial(() => api.unpress(id)).then((a) => show(a));
    },
    stripDown(id, value) {
      handlers.select(id);
      if (inspecting()) { reveal(); return Promise.resolve(null); }
      if (owned(id)) return Promise.resolve(null);
      live.add(id);
      serial(() => api.press(id)).then((a) => show(a));
      return handlers.stripMove(id, value);
    },
    stripMove(id, value) {
      if (inspecting() || !live.has(id)) return Promise.resolve(null);
      pendingMove = { id, value };
      if (moveQueued) return chain;
      moveQueued = true;
      return serial(() => {
        moveQueued = false;
        const move = pendingMove;
        return api.move(move.id, move.value);
      }).then((a) => show(a));
    },
    stripUp(id) {
      if (inspecting() || !live.delete(id)) return Promise.resolve(null);
      return serial(() => api.unpress(id)).then((a) => show(a));
    },
    turn(steps) {
      if (inspecting()) { handlers.select('encoder'); reveal(); return Promise.resolve(null); }
      if (owned('encoder')) return Promise.resolve(null);
      return serial(() => api.move('encoder', steps)).then((a) => show(a));
    },
    shift(held) {
      store.dispatch({ type: 'preview_shift', held });
      return serial(() => api.shift(held)).then((a) => show(a));
    },
    shiftHold() {
      handlers.shift(true);
      onWindowPointerUp?.(() => handlers.shift(false));
    },
    // navigation (A130, A142)
    page: (n) => api.page(n).then((a) => show(a)),
    bank: (n) => api.bank(n).then((a) => show(a)),
    layout: (name) => api.load(name).then((a) => show(a)),
    // the unit (A2, A4, A25, A29)
    take: () => api.take().then((a) => show(a)),
    decline: () => api.decline().then((a) => show(a)),
    release: () => api.release().then((a) => show(a)),
    // learn and calibration (A132–A134, A121)
    learnTouch: (on) => api.learn(on ? 'touch' : 'off').then((a) => show(a)),
    learnMidi: (control, port) => api.learn('midi', port, control).then((a) => show(a)),
    learnOff: () => api.learn('off').then((a) => show(a)),
    calibrate: (step) => api.calibrate(step).then((a) => show(a)),
    async loadPorts() {
      const answer = await api.ports();
      if (answer.ok) store.dispatch({ type: 'ports', data: answer.data });
      return answer;
    },
    // single-control tweak (A135–A139)
    async saveTweak(card, layer, field, value) {
      const request = {
        layout: card.layout, control: card.control, layer, field,
        value: value === '' || value === undefined ? null : value, base_hash: card.base_hash,
      };
      if (/^strip \d/.test(card.control)) request.bank = card.bank; else request.page = card.page;
      const answer = await api.tweak(request);
      if (answer.ok) {
        store.dispatch({ type: 'tweak_answer', answer: { tone: 'ok', text: `Saved: ${card.control} ${field}` } });
        await handlers.refreshCard();
      } else {
        store.dispatch({ type: 'tweak_answer', answer: {
          tone: answer.status === 409 ? 'stale' : 'bad', text: answer.problem,
          issues: (answer.issues ?? []).slice(1) } });
      }
      return answer;
    },
    tweakLayer: (layer) => store.dispatch({ type: 'tweak_layer', layer }),
    // page-only; the bar and column choices are remembered per viewer
    mode: (mode) => store.dispatch({ type: 'mode', mode }),
    navCollapse(collapsed) {
      store.dispatch({ type: 'nav_collapsed', collapsed });
      keep?.(NAV_KEY, collapsed);
    },
    side(panel) {
      store.dispatch({ type: 'side', panel });
      keep?.(SIDE_KEY, store.model.ui.side);
    },
    dismiss: () => store.dispatch({ type: 'dismiss' }),
    // help overlays (help.js): the page's own topics and the ones module panels bring
    help: (topic) => store.dispatch({ type: 'help', topic }),
    closeHelp: () => store.dispatch({ type: 'help_close' }),
    // a module's view across the whole page (?view=<name>, or its Full screen button); `screen` is the browser's
    // Fullscreen API. Where it is refused or missing the view still fills the window, and Esc or Leave ends it.
    openView(name, { fullscreen = false } = {}) {
      store.dispatch({ type: 'view', name });
      return fullscreen && screen && !screen.active() ? Promise.resolve().then(() => screen.enter()).catch(() => {}) : Promise.resolve();
    },
    closeView() {
      store.dispatch({ type: 'view', name: null });
      return screen?.active() ? Promise.resolve().then(() => screen.exit()).catch(() => {}) : Promise.resolve();
    },
    toggleFullscreen() {
      if (!screen) return Promise.resolve();
      return Promise.resolve().then(() => (screen.active() ? screen.exit() : screen.enter())).catch(() => {});
    },
    // leaving full screen (Esc, the browser's own control) also ends a view that a button opened
    fullscreenChanged(on) {
      store.dispatch({ type: 'fullscreen', on });
      if (!on && store.model.ui.view && !store.model.ui.view.pinned) store.dispatch({ type: 'view', name: null });
    },
    overviewLayer: (layer) => store.dispatch({ type: 'overview_layer', layer }),
    async loadOverview() {
      const answer = await api.overview();
      if (answer.ok) store.dispatch({ type: 'overview', data: answer.data });
      return answer;
    },
    flush: () => chain,
  };
  return handlers;
}

// --- module panels (contract 2, a13) --------------------------------------------------------------------------
// Each registered module's panel script (state.modules: {name, title, entry}) is imported once and mounted into
// its own section beside the surface: mountPanel(element, {store, api, handlers, panel}). The section shows when
// the column beside the surface is set to that panel. With no modules nothing is created.
export function createPanelLoader({ importer = (url) => import(url), container, context = {} } = {}) {
  const loaded = new Map();
  return {
    loaded,
    sync(model) {
      for (const panel of modulePanels(model)) {
        if (loaded.has(panel.name)) continue;
        const entry = { element: container.create(panel), module: null, problem: null };
        loaded.set(panel.name, entry);
        entry.ready = Promise.resolve()
          .then(() => importer(panel.entry))
          .then((module) => {
            entry.module = module;
            module.mountPanel?.(entry.element, { ...context, panel });
          })
          .catch((error) => {
            entry.problem = `${panel.title} panel could not load: ${error?.message ?? error}`;
            container.problem?.(entry.element, entry.problem);
          });
      }
      for (const [name, entry] of loaded) container.show?.(entry.element, model.ui.side === name);
      return loaded;
    },
  };
}

// --- the socket ---------------------------------------------------------------------------------------------
export function connect(store, { WebSocketImpl = globalThis.WebSocket, url = socketUrl('/ws'), setTimer = setTimeout } = {}) {
  let delay = 500;
  let socket = null;
  const open = () => {
    socket = new WebSocketImpl(url);
    socket.onopen = () => { delay = 500; };
    socket.onmessage = (event) => {
      try { store.dispatch(JSON.parse(event.data)); } catch { /* a malformed message is ignored */ }
    };
    socket.onclose = () => {
      store.dispatch({ type: 'disconnected' });
      setTimer(open, delay);
      delay = Math.min(delay * 2, 5000);
    };
  };
  open();
  return { get socket() { return socket; } };
}

// --- what to refresh when the state changes --------------------------------------------------------------------
export function needsCardRefresh(previous, next) {
  const id = next.ui.selected;
  if (!id || !next.state) return false;
  if (!next.ui.card && !next.ui.cardProblem) return true; // newly selected (e.g. by learn)
  const a = previous.state;
  const b = next.state;
  if (!a) return true;
  return a.controls?.[id] !== b.controls?.[id] || a.layout !== b.layout || a.page?.n !== b.page?.n
    || a.bank?.n !== b.bank?.n || a.shift !== b.shift || a.learn !== b.learn;
}

export function needsOverviewRefresh(previous, next) {
  const a = previous.state;
  const b = next.state;
  if (!b) return false;
  if (!a || !next.ui.overview) return true;
  return a.layout !== b.layout || a.controls !== b.controls || a.pages !== b.pages || a.banks !== b.banks
    || a.page?.n !== b.page?.n || a.bank?.n !== b.bank?.n;
}

// --- the page --------------------------------------------------------------------------------------------------
// The page shell hides while a module's view fills the page (style.css: body.page-view); the tab names the view.
export function showView(body, doc, view, title = 'APC64 Host') {
  body.classList.toggle('page-view', Boolean(view));
  body.dataset.view = view?.name ?? '';
  if (doc) doc.title = view ? `${capital(view.name)} · APC64` : title;
}

// The browser's Fullscreen API on the whole page, so the help overlay still shows over a full-screen view.
export function pageFullscreen(doc = globalThis.document) {
  const root = doc?.documentElement;
  return {
    active: () => Boolean(doc?.fullscreenElement),
    enter: () => (root?.requestFullscreen ? root.requestFullscreen() : Promise.reject(new Error('no Fullscreen API'))),
    exit: () => (doc?.fullscreenElement && doc.exitFullscreen ? doc.exitFullscreen() : Promise.resolve()),
  };
}

function debounce(fn, ms) {
  let timer = null;
  return () => { clearTimeout(timer); timer = setTimeout(fn, ms); };
}

async function boot() {
  const api = createApi();
  const store = createStore();
  const $ = (id) => document.getElementById(id);
  let storage = null;
  try { storage = window.localStorage; } catch { /* blocked: the choices are not kept */ }
  const handlers = createHandlers(api, store, {
    onWindowPointerUp: (fn) => window.addEventListener('pointerup', fn, { once: true }),
    remember: (key, on) => remember(storage, key, on),
    fullscreen: pageFullscreen(document),
  });
  // http://host:5058/?view=harmony: only that module view, from the first paint (no flash of the whole page)
  const title = document.title;
  const addressed = viewOfAddress(location.search);
  if (addressed) store.dispatch({ type: 'view', name: addressed, pinned: true });
  showView(document.body, document, store.model.ui.view, title);
  document.addEventListener('fullscreenchange', () => handlers.fullscreenChanged(Boolean(document.fullscreenElement)));
  store.dispatch({ type: 'nav_collapsed', collapsed: remembered(storage, NAV_KEY, navFoldedByDefault(window.innerHeight)) });
  store.dispatch({ type: 'side', panel: rememberedSide(storage, sideByDefault(window.innerWidth, window.innerHeight)) });
  let storedSide = null;
  try { storedSide = storage?.getItem(SIDE_KEY) ?? null; } catch { /* blocked */ }
  if (storedSide && !['overview', 'card', 'none'].includes(storedSide)) {
    store.dispatch({ type: 'side', panel: storedSide }); // a module panel: shown once the state lists it
  }
  let surface = null;
  while (!surface) {
    const answer = await api.surface();
    if (answer.ok) surface = answer.data;
    else {
      mount($('banners'), bannerView({ ...store.model, ui: { ...store.model.ui, problem: answer.problem } }));
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  const palette = surface.palette ?? [];
  if (surface.palette_note) $('palette-note').textContent = `Colours are ${surface.palette_note}.`;
  const replica = buildReplica($('replica'), surface, handlers);
  const side = document.querySelector('aside.side');
  const panels = createPanelLoader({
    container: {
      create(panel) {
        const section = document.createElement('section');
        section.id = `module-${panel.name}`;
        section.className = 'panel module-panel';
        section.setAttribute('aria-label', panel.title);
        side.appendChild(section);
        return section;
      },
      show(element, on) { element.classList.toggle('current', on); },
      problem(element, text) { element.textContent = text; },
    },
    context: { store, api, handlers },
  });
  const memo = new Map();
  const renderPart = (id, key, view) => {
    if (memo.get(id) === key) return;
    memo.set(id, key);
    mount($(id), view());
  };
  let frame = null;
  let latest = store.model;
  const render = () => {
    frame = null;
    const m = latest;
    const s = m.state;
    renderPart('unit', JSON.stringify([s?.unit, m.connected]), () => headerView(m, handlers));
    $('conn').classList.toggle('live', m.connected);
    $('conn').title = m.connected ? 'Live' : 'Reconnecting…';
    renderPart('banners', JSON.stringify([s?.unit, s?.errors, s?.warnings, s?.file_deleted, m.ui.problem, m.ui.issues,
      m.ui.notice, m.connected]), () => bannerView(m, handlers));
    renderPart('nav', JSON.stringify([s?.layout, s?.layout_name, s?.layouts, s?.pages, s?.banks, s?.page, s?.bank,
      s?.unit?.view, s?.file_deleted, m.ui.navCollapsed]), () => navView(m, handlers));
    $('nav').classList.toggle('collapsed', m.ui.navCollapsed);
    for (const panel of sidePanels(m)) document.body.classList.toggle(`side-${panel}`, m.ui.side === panel);
    document.body.classList.toggle('side-module', Boolean(currentModulePanel(m)));
    showView(document.body, document, m.ui.view, title);
    panels.sync(m);
    renderPart('toolbar', JSON.stringify([m.ui.mode, s?.learn, s?.calibration_step, s?.calibration_label, s?.unit?.view,
      m.ui.side, s?.modules]), () => toolbarView(m, handlers));
    replica.update(m);
    renderPart('played', JSON.stringify([s?.played, s?.routing]), () => playedView(m));
    renderPart('card-info', JSON.stringify([m.ui.selected, m.ui.card, m.ui.cardProblem, s?.shift, m.ui.previewShift]),
      () => cardView(m, handlers));
    renderPart('card-learn', JSON.stringify([m.ui.card?.control, m.ui.card?.port_status, m.ui.card?.layer, s?.learn,
      m.ui.ports]), () => learnCardView(m, handlers));
    renderPart('card-tweak', tweakKey(m), () => tweakView(m, handlers, palette));
    renderPart('activity', m.activity, () => activityView(m));
    renderPart('overview', JSON.stringify([m.ui.overview, m.ui.overviewLayer]), () => overviewView(m, handlers));
    const helpWasOpen = memo.get('help') !== undefined && memo.get('help') !== 'null';
    renderPart('help', JSON.stringify(m.ui.help), () => helpView(m, handlers));
    $('help').hidden = !m.ui.help;
    if (m.ui.help && !helpWasOpen) $('help').querySelector('.help-close')?.focus();
  };
  const refreshCard = debounce(() => handlers.refreshCard(), 120);
  const refreshOverview = debounce(() => handlers.loadOverview(), 400);
  let clearNotice = null;
  store.subscribe((next, previous, action) => {
    latest = next;
    if (!frame) frame = requestAnimationFrame(render);
    if (needsCardRefresh(previous, next)) refreshCard();
    if (needsOverviewRefresh(previous, next)) refreshOverview();
    if (action.type === 'snapshot') handlers.loadPorts();
    if (action.type === 'notice') {
      clearTimeout(clearNotice);
      clearNotice = setTimeout(() => store.model.ui.notice && handlers.dismiss(), 4000);
    }
  });
  window.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (store.model.ui.help) handlers.closeHelp();
    else if (store.model.ui.view && !store.model.ui.view.pinned) handlers.closeView();
    else handlers.dismiss();
  });
  render();
  connect(store);
  // a link to one control opens its card: http://host:5058/#pad%20r1c1
  const linked = decodeURIComponent((location.hash || '').slice(1));
  if (linked) handlers.select(linked);
  window.addEventListener('hashchange', () => {
    const id = decodeURIComponent((location.hash || '').slice(1));
    if (id) handlers.select(id);
  });
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') boot();
