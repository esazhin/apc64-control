// The nav bar (5a.9): layout, pages 1–8 and banks 1–6 with their names, and the unit's current view. It mirrors
// the unit's scene and strip-mode LEDs: current, defined and empty. Clicking switches layout, page or bank
// (A130, A142). It folds to one slim line (layout, page, bank, view) so the surface keeps the height; Shift is
// on the surface itself. Its "?" explains layouts, pages and strip banks (help.js).
import { h } from './dom.js';
import { LAYOUT_HELP, helpButton } from './help.js';
import { SIDE_PANELS } from './state.js';

export function navView(model, handlers = {}) {
  const state = model.state;
  if (!state) return [];
  const view = h('span', { class: 'viewtag', text: `View: ${capital(state.unit?.view ?? 'session')}` });
  if (model.ui.navCollapsed) return navLine(model, handlers, view);
  const layouts = state.layouts ?? [];
  const layoutSelect = h('select', {
    'aria-label': 'Layout',
    onchange: (event) => handlers.layout?.(event.target.value),
  },
  state.layout ? null : h('option', { value: '', text: 'No layout', selected: true }),
  layouts.map((x) => h('option', {
    value: x.id, selected: x.id === state.layout, disabled: !x.valid && x.id !== state.layout,
    text: `${x.name}${x.valid ? '' : ' — invalid'}${x.deleted ? ' — file deleted' : ''}`,
  })));

  const slot = (s, word, onclick) => h('button', {
    class: ['slot', s.current ? 'current' : null, s.defined ? 'defined' : 'empty'],
    title: s.defined ? `${word} ${s.n}: ${s.display}` : `${word} ${s.n} is empty`,
    'aria-pressed': s.current ? 'true' : 'false',
    data: { [word.toLowerCase()]: s.n },
    onclick: () => onclick?.(s.n),
  }, h('span', { class: 'n', text: String(s.n) }), h('span', { class: 'name', text: s.display || 'empty' }));

  return [
    h('div', { class: 'group' }, h('span', { class: 'caption', text: 'Layout' }), layoutSelect,
      state.file_deleted ? h('span', { class: 'hint', text: 'file deleted, still active' }) : null),
    h('div', { class: 'navrow' },
      h('div', { class: 'group' }, h('span', { class: 'caption', text: 'Page (scene buttons)' }),
        h('div', { class: 'slots pages' }, (state.pages ?? []).map((s) => slot(s, 'Page', handlers.page)))),
      h('div', { class: 'group' }, h('span', { class: 'caption', text: 'Strip bank (strip-mode buttons)' }),
        h('div', { class: 'slots banks' }, (state.banks ?? []).map((s) => slot(s, 'Bank', handlers.bank))))),
    h('div', { class: 'foldbox' }, h('div', { class: 'foldtop' }, helpButton(LAYOUT_HELP, handlers), foldButton(false, handlers)),
      view),
  ];
}

// The folded bar: one line, the layout's name, the current page and bank, the view and the unfold button.
function navLine(model, handlers, view) {
  const state = model.state;
  const where = (word, s) => `${word} ${s?.n ?? '–'}${s?.display ? ` ${s.display}` : s?.n ? ' (empty)' : ''}`;
  return [h('div', { class: 'navline' },
    h('span', { class: 'caption', text: 'Layout' }),
    h('strong', { class: 'name', text: state.layout_name || state.layout || 'none' }),
    state.file_deleted ? h('span', { class: 'hint', text: 'file deleted' }) : null,
    h('span', { class: 'where', text: where('Page', state.page) }),
    h('span', { class: 'where', text: where('Bank', state.bank) }),
    view,
    h('span', { class: 'spacer' }),
    helpButton(LAYOUT_HELP, handlers),
    foldButton(true, handlers))];
}

function foldButton(collapsed, handlers) {
  return h('button', {
    class: 'fold', 'aria-expanded': collapsed ? 'false' : 'true',
    title: collapsed ? 'Show the layout, page and strip-bank choices' : 'Fold this bar to one line',
    onclick: () => handlers.navCollapse?.(!collapsed),
    text: collapsed ? 'Layouts, pages, banks ▾' : 'Fold ▴',
  });
}

// --- per-viewer choices (localStorage; the page works without it) -------------------------------------------
export const NAV_KEY = 'apc64.nav';
export const SIDE_KEY = 'apc64.side';

// The stored choice ('on'/'off') as a boolean, or the fallback when nothing is stored or storage is blocked.
export function remembered(storage, key, fallback) {
  const value = read(storage, key);
  return value === 'on' ? true : value === 'off' ? false : fallback;
}

// The stored column choice ('overview', 'card', 'none'), or the fallback.
export function rememberedSide(storage, fallback) {
  const value = read(storage, SIDE_KEY);
  return SIDE_PANELS.includes(value) ? value : fallback;
}

// Keeps a choice: true/false as 'on'/'off', a word as it is.
export function remember(storage, key, value) {
  try { storage?.setItem(key, typeof value === 'boolean' ? (value ? 'on' : 'off') : String(value)); } catch { /* not kept: fine */ }
}

function read(storage, key) {
  try { return storage?.getItem(key) ?? null; } catch { return null; } // private window, blocked site data
}

// Defaults: the bar folds on a short screen; the column beside the surface shows the overview, or nothing when
// the surface, at the height it gets, and the column would sit side by side but not fit (style.css: .unit is 15.4 × 11.2 P,
// the column at least 340px).
export function navFoldedByDefault(height) {
  return height < 900;
}

export function sideFits(width, height) {
  const surfaceHeight = Math.max(0, height - 200);
  const surfaceWidth = surfaceHeight * (15.4 / 11.2) + 56;
  return width > 1100 && width >= surfaceWidth + 352;
}

// Narrow screens stack the column under the surface, where it costs the surface nothing.
export function sideByDefault(width, height) {
  return width <= 1100 || sideFits(width, height) ? 'overview' : 'none';
}

export function capital(word) {
  return word ? word[0].toUpperCase() + word.slice(1) : '';
}
