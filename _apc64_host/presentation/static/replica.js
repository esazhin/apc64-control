// The replica of the whole unit (contract 5a.9, inv1, inv2): every control where it sits on the APC64's top
// panel (user guide §3.1; the OLED takes the AKAI logo's place), labelled with what it does right now (current
// page, bank and Shift), visibly empty when unbound, LEDs and strip bars as on the unit (colours approximate),
// the view buttons, and what the unit itself owns in its current view (PROTOCOL-SPEC §4.6, §5). Since 2026-10-27
// the Session, Note, Chord, Step and Custom buttons switch the unit (the host's pad-mode request, which the unit
// obeys without reporting it back); Project stays the unit's own.
// Gestures go to handlers: pointer down/up = press/release, a strip drag = moves, the encoder's arrows/wheel =
// turns.
//
// Pure parts (grouping, placement, per-control views, colour maths) are exported for node --test;
// buildReplica() makes the elements once and update() restyles them, so a drag keeps its pointer while the
// state streams in. The page scales the whole panel from one CSS length (style.css: .unit --p).
import { h, toDom } from './dom.js';
import { capital } from './nav.js';
import { controlState, layerOf, ownedByUnit, shiftShown, unitView } from './state.js';

const MAX14 = 16383;

// --- grouping the surface catalog (/api/surface) --------------------------------------------------------
export function groupSurface(surface) {
  const all = surface.controls;
  const numbered = (re) => all.filter((c) => re.test(c.id)).sort((a, b) => num(a.id) - num(b.id));
  const pads = all.filter((c) => /^pad r\dc\d$/.test(c.id));
  const rows = [8, 7, 6, 5, 4, 3, 2, 1].map((r) => [1, 2, 3, 4, 5, 6, 7, 8].map((col) =>
    pads.find((p) => p.id === `pad r${r}c${col}`)));
  const strips = numbered(/^strip \d$/).map((s) => ({ ...s, touch: all.find((c) => c.id === `${s.id} touch`) }));
  const used = new Set([...pads, ...strips, ...strips.map((s) => s.touch)].filter(Boolean).map((c) => c.id));
  const take = (list) => { list.forEach((c) => used.add(c.id)); return list; };
  const scenes = take(numbered(/^scene \d$/));
  const tracks = take(numbered(/^track \d$/));
  const trackctls = take(numbered(/^trackctl \d$/));
  const stripmodes = take(numbered(/^stripmode \d$/));
  const views = take(all.filter((c) => c.role === 'device_local'));
  const encoder = all.find((c) => c.id === 'encoder');
  const encoderPress = all.find((c) => c.id === 'encoder press');
  const shift = all.find((c) => c.role === 'modifier');
  [encoder, encoderPress, shift].filter(Boolean).forEach((c) => used.add(c.id));
  // the remaining buttons, in panel rows by their geometry (functions; transport + arrows; modes)
  const rest = all.filter((c) => !used.has(c.id));
  const byRow = new Map();
  for (const c of rest) {
    const key = c.geometry.y;
    if (!byRow.has(key)) byRow.set(key, []);
    byRow.get(key).push(c);
  }
  const buttonRows = [...byRow.entries()].sort((a, b) => a[0] - b[0]).map(([, row]) => row.sort((a, b) => a.geometry.x - b.geometry.x));
  return { rows, scenes, tracks, trackctls, strips, stripmodes, views, encoder, encoderPress, shift, buttonRows };
}

// --- the panel: where each control sits (APC64 user guide §3.1 Top Panel) -------------------------------------
// In pad pitches P (one pad to the next): the unit is 15.4 P wide and 11.2 P tall. Strips come in pairs in the
// four corners, the strip-mode and function buttons in one column left of the grid, the scene buttons right of
// it, the track and control rows under it; the view and transport buttons along the top; cursor keys and the
// encoder's bezel in the bottom corners.
export const PANEL = { width: 15.4, height: 11.2 };
const PITCH = 0.99;
const PAD = 0.86;
const GRID_X = 3.75;
const GRID_Y = 1.27;
const SIDE_X = 2.75;
const SIDE_Y = { tempo: 4.49, clear: 5.24, duplicate: 5.78, fixed: 6.4, quantize: 6.91, undo: 7.59, shift: 8.22,
  recarm: 8.87, mute: 9.37, solo: 9.86, clipstop: 10.36 };
const TOP = { play: 9.25, stop: 10.07, rec: 10.9 };
const STRIP_X = [0.3, 1.57, 0.3, 1.57, 12.98, 14.28, 12.98, 14.28];
const ARROWS = { left: [0.33, 9.48, 0.52, 1.24], up: [0.93, 9.48, 0.8, 0.6], down: [0.93, 10.12, 0.8, 0.6],
  right: [1.8, 9.48, 0.52, 1.24] };
const VIEW_ORDER = ['session', 'note', 'chord', 'step', 'project', 'custom'];
// the view buttons the host switches the unit with (the service's SWITCHABLE_VIEWS); Project is the unit's own
export const SWITCHABLE_VIEWS = ['session', 'note', 'chord', 'step', 'custom'];
export const switchable = (id) => SWITCHABLE_VIEWS.includes(String(id).replace(/^view /, ''));
export const FIXTURES = {
  oled: { x: 0.3, y: 0.3, w: 2.15, h: 0.85 },
  wordmark: { x: 12.45, y: 0.36, w: 2.6, h: 0.6 },
  bezel: { x: 11.88, y: 9.5, w: 3.19, h: 1.18 },
};

// The printed Shift functions under the unit's buttons (the unit's own printing; the layout decides what Shift
// does here).
const BARS = ['8 BARS', '4 BARS', '2 BARS', '1 BAR', '1/4', '1/8', '1/16', '1/32'];
const SCENE_SILK = ['VELOCITY', 'PROBABILITY', 'MUTATE', '', 'SAVE', 'SAVE TO…', '', 'STOP ALL'];
export const SILK = {
  'view session': 'OVERVIEW', 'view note': 'CONFIG', 'view chord': 'CONFIG', 'view step': 'CONFIG',
  'view custom': 'GLOBAL', rec: 'MIDI OVERDUB', tempo: 'SWING', duplicate: 'DOUBLE', quantize: 'RECORD', undo: 'REDO',
  ...Object.fromEntries(BARS.map((t, i) => [`track ${i + 1}`, t])),
  ...Object.fromEntries(SCENE_SILK.map((t, i) => [`scene ${i + 1}`, t]).filter(([, t]) => t)),
};

const box = (x, y, w, h) => ({ x, y, w, h });

// Where a control sits: {x, y, w, h} in P, or null (a strip's touch and the encoder turn share their control's
// place).
export function placeOf(id) {
  let m;
  if ((m = /^pad r(\d)c(\d)$/.exec(id))) {
    return box(GRID_X + (Number(m[2]) - 1) * PITCH, GRID_Y + (8 - Number(m[1])) * PITCH, PAD, PAD);
  }
  if ((m = /^track (\d)$/.exec(id))) return box(GRID_X + (Number(m[1]) - 1) * PITCH, 9.47, PAD, 0.38);
  if ((m = /^trackctl (\d)$/.exec(id))) return box(GRID_X + (Number(m[1]) - 1) * PITCH, 10.12, PAD, 0.58);
  if ((m = /^scene (\d)$/.exec(id))) return box(11.88, 1.43 + (Number(m[1]) - 1) * PITCH, 0.7, 0.5);
  if ((m = /^stripmode (\d)$/.exec(id))) return box(SIDE_X, GRID_Y + (Number(m[1]) - 1) * 0.495, 0.7, 0.4);
  if ((m = /^strip (\d)$/.exec(id))) {
    const n = Number(m[1]);
    return box(STRIP_X[n - 1], [3, 4, 7, 8].includes(n) ? 5.57 : 1.43, 0.78, 3.37);
  }
  if ((m = /^view (\w+)$/.exec(id)) && VIEW_ORDER.includes(m[1])) {
    return box(GRID_X + VIEW_ORDER.indexOf(m[1]) * 0.83, 0.45, 0.7, 0.5);
  }
  if (id in TOP) return box(TOP[id], 0.45, 0.68, 0.5);
  if (id in SIDE_Y) return box(SIDE_X, SIDE_Y[id], 0.7, 0.4);
  if (id in ARROWS) return box(...ARROWS[id]);
  return null;
}

// The printed label under a control, centred under it (left-aligned under the side column, as printed).
export function silkPlace(id) {
  const at = placeOf(id);
  if (!at || !SILK[id]) return null;
  const w = Math.max(at.w, 0.8);
  const x = at.x === SIDE_X ? at.x : at.x + at.w / 2 - w / 2;
  return box(x, at.y + at.h + 0.04, w, 0.16);
}

function placed(at) {
  return { '--x': at.x, '--y': at.y, '--w': at.w, '--h': at.h };
}

function num(id) {
  const m = /(\d+)(?!.*\d)/.exec(id);
  return m ? Number(m[1]) : 0;
}

// --- colours --------------------------------------------------------------------------------------------
const PAD_OFF = [0x23, 0x26, 0x2c];

export function hexToRgb(hex) {
  const v = parseInt(String(hex).replace('#', ''), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

// How much of the LED colour shows over the dark pad: idle (25 %) still reads as its colour, full is full.
export function ledMix(led) {
  if (!led || led.off || !led.brightness) return 0;
  return Math.round(50 + 50 * led.brightness);
}

// Dark text on bright colours, light text otherwise (labels must stay readable on every LED colour).
export function inkFor(rgbHex, mix) {
  if (!rgbHex || !mix) return 'ink-light';
  const [r, g, b] = hexToRgb(rgbHex).map((v, i) => (v * mix + PAD_OFF[i] * (100 - mix)) / 100 / 255);
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.55 ? 'ink-dark' : 'ink-light';
}

// 'Note 36 → mpc (missing)' → main 'Note 36', sub 'mpc (missing)'; a label written in the layout stays whole.
export function splitLabel(label) {
  const m = /^(.*?) → (.+)$/.exec(label ?? '');
  return m ? { main: m[1], sub: m[2] } : { main: label ?? '', sub: '' };
}

// The printed name, short enough for a small button ('Track control 3' → 'Ctl 3'; the cursor keys as arrows).
const ARROW_GLYPH = { left: '◀', up: '▲', down: '▼', right: '▶' };
export function shortName(entry) {
  return ARROW_GLYPH[entry.id] ?? entry.display.replace(/^Track control /, 'Ctl ');
}

// The label for a narrow screen: 'Note 36' → '36', 'Prog 5' → 'P5', 'CC20' stays.
export function shortLabel(main) {
  return String(main ?? '').replace(/^Note (\d+)/, '$1').replace(/^Prog (\d+)/, 'P$1');
}

// --- one control, as the replica shows it now ---------------------------------------------------------------
export function controlView(entry, model, ui = {}) {
  const state = model.state;
  const c = controlState(model, entry.id);
  const layer = layerOf(model);
  const label = c ? (layer === 'shift' ? c.label_shift : c.label_base) : '';
  const view = {
    id: entry.id, phys: shortName(entry), main: '', sub: '', classes: ['ctl'], mix: 0, rgb: null, title: '',
    animation: null,
  };
  const led = c?.led;
  if (led && !led.off) {
    view.mix = ledMix(led);
    view.rgb = led.rgb;
    view.animation = led.animation;
  }
  if (entry.role === 'bindable') {
    if (!label) {
      view.main = '—';
      view.classes.push('empty');
      view.title = `${entry.display}: nothing bound${layer === 'shift' ? ' on the Shift layer' : ''}`;
    } else {
      const parts = splitLabel(label);
      view.main = parts.main;
      view.sub = parts.sub;
      if (c?.missing?.length) view.classes.push('missing');
      const other = layer === 'shift' ? c?.label_base : c?.label_shift;
      view.title = `${entry.display}: ${label}${other ? `\n${layer === 'shift' ? 'Base' : 'Shift'}: ${other}` : ''}`;
    }
    if (c?.toggle) view.classes.push('toggled');
  } else if (entry.role === 'navigation') {
    view.classes.push('nav-btn');
    const scene = /^scene (\d)$/.exec(entry.id);
    const slot = scene ? state?.pages?.[Number(scene[1]) - 1]
      : state?.banks?.[Number(/(\d)$/.exec(entry.id)[1]) - 1];
    const word = scene ? 'Page' : 'Bank';
    const n = scene ? Number(scene[1]) : Number(/(\d)$/.exec(entry.id)[1]);
    if (scene) {
      view.phys = String(n);
      view.main = slot?.display || '';
    } else {
      view.main = entry.display; // the name printed on the unit (Device, Volume, …)
      view.sub = slot?.display || '—';
      view.phys = '';
    }
    if (slot?.current) view.classes.push('current');
    if (!slot?.defined) view.classes.push('undefined');
    view.title = slot?.defined ? `${word} ${n}: ${slot.display}` : `${word} ${n} is empty`;
  } else if (entry.role === 'modifier') {
    view.classes.push('modifier');
    view.main = 'Shift';
    view.phys = '';
    if (shiftShown(model)) view.classes.push('held');
    view.title = 'Hold to see and play every control\'s Shift layer';
  } else if (entry.role === 'device_local') {
    view.classes.push(switchable(entry.id) ? 'view-switch' : 'unit-own');
    view.main = entry.display;
    view.phys = '';
    const current = state?.unit?.view === entry.id.replace(/^view /, '');
    if (current) view.classes.push('current-view');
    view.title = !switchable(entry.id) ? `${entry.display} view: the unit's own button (the host does not switch to it)`
      : current ? `${entry.display} view: the unit is in it`
        : `${entry.display} view: click to switch the APC64 to it (while the host holds the unit)`;
  }
  if (ownedByUnit(model, entry.id)) byUnit(view, entry, model);
  if (ui.pressed?.has(entry.id)) view.classes.push('pressed');
  if (ui.selected === entry.id || (entry.touch && ui.selected === entry.touch.id)) view.classes.push('selected');
  view.classes.push(inkFor(view.rgb, view.mix));
  if (view.animation) view.classes.push(`anim-${view.animation}`);
  return view;
}

// A control the unit keeps in its current view: no layout colour; a pad shows no layout binding at all (its
// Session-view binding is not in use), a button or strip in Custom view keeps its label, dimmed.
function byUnit(view, entry, model) {
  const name = capital(unitView(model));
  view.mix = 0;
  view.rgb = null;
  view.animation = null;
  view.classes = view.classes.filter((c) => c !== 'toggled' && c !== 'missing');
  view.classes.push('by-unit');
  if (/^pad /.test(entry.id)) {
    view.main = '';
    view.sub = '';
    view.title = `${entry.display}: ${name} view — the APC64 plays this pad itself (the layout's Session-view pads are not in use)`;
  } else {
    view.title = `${entry.display}: ${name} view — this stays on the APC64 and does not reach the host`;
  }
}

export function stripView(entry, model, ui = {}) {
  const c = controlState(model, entry.id);
  const touch = entry.touch ? controlState(model, entry.touch.id) : null;
  const layer = layerOf(model);
  const label = c ? (layer === 'shift' ? c.label_shift : c.label_base) : '';
  const touchLabel = touch ? (layer === 'shift' ? touch.label_shift : touch.label_base) : '';
  const bar = c?.bar;
  const value = bar ? bar.value : 0;
  const fraction = Math.max(0, Math.min(1, value / MAX14));
  const bipolar = bar?.style === 'bipolar';
  let fill = !bar || !bar.lit ? { height: '0%', bottom: '0%' }
    : bipolar ? { height: `${Math.abs(fraction - 0.5) * 100}%`, bottom: `${Math.min(fraction, 0.5) * 100}%` }
      : { height: `${fraction * 100}%`, bottom: '0%' };
  const owned = ownedByUnit(model, entry.id);
  const classes = ['strip'];
  if (owned) {
    fill.height = '0%';
    classes.push('by-unit');
  }
  if (!label) classes.push('empty');
  if (bipolar) classes.push('bipolar');
  if (ui.pressed?.has(entry.id)) classes.push('touched');
  if (ui.selected === entry.id || ui.selected === entry.touch?.id) classes.push('selected');
  return {
    id: entry.id, label: label || '—', classes, fill, rgb: bar?.lit && !owned ? bar.rgb : null, value,
    title: owned ? `${entry.display}: ${capital(unitView(model))} view — the strip stays on the APC64 (it sends the project's CCs on the Custom port)`
      : label ? `${entry.display}: ${label}${touchLabel ? `\ntouch: ${touchLabel}` : ''}\nposition ${value}`
        : `${entry.display}: nothing bound in this bank`,
  };
}

// Pointer height in a strip → 0–16383 (top = 16383).
export function stripValue(clientY, rect) {
  const fraction = 1 - (clientY - rect.top) / Math.max(1, rect.height);
  return Math.round(Math.max(0, Math.min(1, fraction)) * MAX14);
}

export function oledRows(model) {
  const rows = model.state?.oled ?? ['', ''];
  return [rows[0] ?? '', rows[1] ?? ''];
}

// The played-notes row: notes from the unit's own views, with their position label (inv9, A122).
export function playedView(model) {
  const state = model.state;
  if (!state) return [];
  const chips = (state.played ?? []).map((note) =>
    h('span', { class: ['chip', note.routed ? null : 'unrouted'], title: note.routed ? 'routed' : 'not routed', text: note.text }));
  const caption = state.routing?.status ? state.routing.status : (chips.length ? 'Played' : '');
  return [caption ? h('span', { class: 'caption', text: chips.length && !state.routing?.status ? 'Played:' : caption }) : null,
    ...chips];
}

// Pads lit by played notes: only where the calibration (taken in Note view) says where a note is; in Chord,
// Step or Custom view a note is not one pad, so the caption lists the notes instead.
export function playedPads(model) {
  const pads = new Map();
  if (!['session', 'note'].includes(unitView(model))) return pads;
  for (const note of model.state?.played ?? []) if (note.pad) pads.set(note.pad, note.velocity / 127);
  return pads;
}

// What each of the unit's own views plays, and on which of its ports (NOTES-daw-mode.md, PROTOCOL-SPEC §5).
const VIEW_PLAYS = {
  note: { port: 'notes', expression: 'velocity + aftertouch' },
  chord: { port: 'notes', expression: 'velocity + aftertouch' },
  drum: { port: 'notes', expression: 'velocity' },
  step: { port: 'notes', expression: 'velocity' },
  custom: { port: 'custom', expression: 'velocity, aftertouch where the project\'s pad has it' },
};

// The caption over the grid when the unit owns it: whose pads these are, where their playing goes, and the
// notes sounding now when they cannot be shown on the pads. null in Session view (the host draws the grid).
export function viewCaption(model) {
  const state = model.state;
  const view = unitView(model);
  if (!state || view === 'session') return null;
  const name = capital(view);
  const plays = VIEW_PLAYS[view];
  if (!plays) return { title: `${name} view — the APC64 uses these pads itself`, route: 'nothing is played from here', notes: '', extra: '' };
  const target = state.routing?.[plays.port];
  const port = plays.port === 'notes' ? 'Notes' : 'Custom';
  const route = target ? `→ ${target}, ${plays.expression}` : `not routed: this layout has no routing for the ${port} port`;
  const played = state.played ?? [];
  const lit = playedPads(model).size > 0;
  const notes = lit ? '' : played.length
    ? `Playing: ${played.slice(0, 6).map((n) => `${n.label} vel ${n.velocity}`).join(' · ')}`
    : 'Play the pads on the unit: the notes show here';
  const extra = view === 'custom' ? 'Side buttons, strips and the encoder stay on the unit too; only Shift and Tempo reach the host.' : '';
  return { title: `${name} view — the APC64 plays these pads itself`, route, notes, extra };
}

// --- the DOM ------------------------------------------------------------------------------------------------
function ctlNode(entry, extraClass) {
  const at = placeOf(entry.id);
  const inert = entry.role === 'device_local' && !switchable(entry.id);
  return h('div', { class: ['ctl', extraClass], data: { id: entry.id }, tabindex: inert ? null : 0,
    role: inert ? null : 'button', style: at ? placed(at) : null },
  h('span', { class: 'phys' }), h('span', { class: 'main' }), h('span', { class: 'short' }), h('span', { class: 'sub' }));
}

function silkNode(id) {
  const at = silkPlace(id);
  return at ? h('div', { class: ['silk', at.x === SIDE_X ? 'left' : null], style: placed(at), text: SILK[id] }) : null;
}

export function replicaTree(groups) {
  const g = groups;
  const stripNode = (s) => h('div', { class: 'strip', data: { id: s.id }, style: placed(placeOf(s.id)) },
    h('div', { class: 'num', text: String(num(s.id)) }),
    h('div', { class: 'track', data: { strip: s.id } }, h('div', { class: 'fill' })),
    h('div', { class: 'label' }));
  const encoder = g.encoder ? h('div', { class: 'bezel', style: placed(FIXTURES.bezel) },
    h('div', { class: 'encoder-label', data: { encoder: 'label' } }),
    h('div', { class: 'encoder' },
      h('button', { class: 'turn', data: { turn: -1 }, title: 'Turn the encoder one step counter-clockwise', text: '◀' }),
      h('button', { class: 'knob', data: { id: g.encoderPress?.id ?? 'encoder press' }, title: 'Press the encoder', text: 'push' }),
      h('button', { class: 'turn', data: { turn: 1 }, title: 'Turn the encoder one step clockwise', text: '▶' }))) : null;
  const buttons = g.buttonRows.flat();
  const kind = (e) => (e.id in ARROWS ? 'btn arrow' : e.id in TOP ? 'btn transport' : 'btn sidebtn');
  return h('div', { class: 'unit', style: { '--pw': PANEL.width, '--ph': PANEL.height } },
    h('div', { class: 'oled', data: { oled: 'rows' }, title: 'OLED', style: placed(FIXTURES.oled) }),
    h('div', { class: 'wordmark', 'aria-hidden': 'true', text: 'APC64', style: placed(FIXTURES.wordmark) }),
    g.views.map((e) => ctlNode(e, 'view')),
    g.strips.map(stripNode),
    g.stripmodes.map((e) => ctlNode(e, 'btn stripmode')),
    buttons.map((e) => ctlNode(e, kind(e))),
    g.shift ? ctlNode(g.shift, 'btn sidebtn') : null,
    g.rows.flat().filter(Boolean).map((e) => ctlNode(e, 'pad')),
    g.scenes.map((e) => ctlNode(e, 'scene')),
    g.tracks.map((e) => ctlNode(e, 'btn trackbtn')),
    g.trackctls.map((e) => ctlNode(e, 'btn trackctl')),
    Object.keys(SILK).map(silkNode),
    h('div', { class: 'grid-caption', data: { caption: 'box' }, 'aria-live': 'polite',
      style: placed(box(GRID_X, GRID_Y, 7 * PITCH + PAD, 7 * PITCH + PAD)) },
    h('div', { class: 'cap', data: { caption: 'text' } }),
    h('div', { class: 'calib', data: { calib: 'line' } })),
    encoder);
}

function collect(root, attr) {
  const found = new Map();
  const walk = (el) => {
    if (el.dataset && el.dataset[attr] !== undefined) found.set(el.dataset[attr], el);
    for (const child of el.children ?? []) walk(child);
  };
  walk(root);
  return found;
}

export function buildReplica(container, surface, handlers, doc = globalThis.document) {
  const groups = groupSurface(surface);
  const entries = new Map(surface.controls.map((c) => [c.id, c]));
  const unit = toDom(replicaTree(groups), doc);
  container.replaceChildren(unit);
  const controls = collect(unit, 'id');
  const tracks = collect(unit, 'strip');
  const oled = collect(unit, 'oled').get('rows');
  const calib = collect(unit, 'calib').get('line');
  const captions = collect(unit, 'caption');
  const encoderLabel = collect(unit, 'encoder').get('label');
  const ui = { pressed: new Set(), selected: null };
  const baseClass = new Map([...controls].map(([id, el]) => [id, el.className])); // 'ctl pad', 'ctl btn', …
  let model = null;

  const press = (id) => { ui.pressed.add(id); if (model) update(model); };
  const unpress = (id) => { ui.pressed.delete(id); if (model) update(model); };

  for (const [id, el] of controls) {
    const entry = entries.get(id);
    if (!entry || el.classList.contains('strip')) continue;
    if (entry.role === 'device_local') {
      // a view button: a click asks the unit for that view (handlers.view: Play presses, Inspect only selects)
      const choose = () => (switchable(id) && handlers.view ? handlers.view(id) : handlers.select?.(id));
      el.addEventListener('click', choose);
      if (switchable(id)) {
        el.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) choose(); });
      }
      continue;
    }
    let down = false;
    const start = (event) => {
      event.preventDefault?.();
      if (down) return;
      down = true;
      el.setPointerCapture?.(event.pointerId);
      press(id);
      if (entry.role === 'modifier') handlers.shift?.(true);
      else handlers.down?.(id);
    };
    const end = () => {
      if (!down) return;
      down = false;
      unpress(id);
      if (entry.role === 'modifier') handlers.shift?.(false);
      else handlers.up?.(id);
    };
    el.addEventListener('pointerdown', start);
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
    el.addEventListener('lostpointercapture', end);
    el.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) start(event); });
    el.addEventListener('keyup', (event) => { if (event.key === 'Enter' || event.key === ' ') end(); });
    el.addEventListener('contextmenu', (event) => event.preventDefault?.());
  }

  for (const [id, track] of tracks) {
    let dragging = false;
    const value = (event) => stripValue(event.clientY, track.getBoundingClientRect());
    track.addEventListener('pointerdown', (event) => {
      event.preventDefault?.();
      dragging = true;
      track.setPointerCapture?.(event.pointerId);
      press(id);
      handlers.stripDown?.(id, value(event));
    });
    track.addEventListener('pointermove', (event) => { if (dragging) handlers.stripMove?.(id, value(event)); });
    const stop = () => {
      if (!dragging) return;
      dragging = false;
      unpress(id);
      handlers.stripUp?.(id);
    };
    track.addEventListener('pointerup', stop);
    track.addEventListener('pointercancel', stop);
    track.addEventListener('lostpointercapture', stop);
  }

  const walkTurns = (el) => {
    if (el.dataset?.turn !== undefined) el.addEventListener('click', () => handlers.turn?.(Number(el.dataset.turn)));
    for (const child of el.children ?? []) walkTurns(child);
  };
  walkTurns(unit);
  const knob = controls.get(groups.encoderPress?.id ?? 'encoder press');
  knob?.addEventListener('wheel', (event) => {
    event.preventDefault?.();
    handlers.turn?.(event.deltaY < 0 ? 1 : -1);
  }, { passive: false });

  function update(next) {
    model = next;
    ui.selected = next.ui?.selected ?? null;
    const played = playedPads(next);
    for (const [id, el] of controls) {
      const entry = entries.get(id);
      if (!entry) continue;
      if (el.classList.contains('strip')) {
        const v = stripView({ ...entry, touch: entries.get(`${id} touch`) }, next, ui);
        el.className = v.classes.join(' ');
        el.title = v.title;
        const fill = el.children[1].children[0];
        fill.style.height = v.fill.height;
        fill.style.bottom = v.fill.bottom;
        fill.style.setProperty?.('--led', v.rgb ?? 'transparent');
        el.children[2].textContent = v.label;
        continue;
      }
      if (entry.id === (groups.encoderPress?.id ?? 'encoder press')) {
        const turn = controlView(groups.encoder ?? entry, next, ui);
        const own = turn.classes.includes('by-unit');
        encoderLabel.textContent = own ? 'encoder: on the APC64'
          : turn.main === '—' ? 'encoder: —' : `${turn.main}${turn.sub ? ` → ${turn.sub}` : ''}`;
        encoderLabel.title = turn.title;
        el.title = controlView(entry, next, ui).title;
        el.classList.toggle('by-unit', own);
        continue;
      }
      const v = controlView(entry, next, ui);
      if (played.has(id)) {
        v.classes.push('played');
        el.style.setProperty?.('--played', String(Math.max(0.25, played.get(id))));
      }
      el.className = [...new Set([...baseClass.get(id).split(' '), ...v.classes])].join(' ');
      el.title = v.title;
      el.style.setProperty?.('--led', v.rgb ?? 'transparent');
      el.style.setProperty?.('--mix', `${v.mix}%`);
      const [phys, main, short, sub] = el.children;
      phys.textContent = v.phys;
      main.textContent = v.main;
      short.textContent = shortLabel(v.main);
      sub.textContent = v.sub;
    }
    const rows = oledRows(next);
    oled.textContent = `${rows[0]}\n${rows[1]}`;
    const state = next.state;
    calib.textContent = played.size ? `Pad positions: ${state.calibration_label}` : '';
    const caption = viewCaption(next);
    captions.get('text').textContent = caption ? [caption.title, caption.route, caption.notes, caption.extra]
      .filter(Boolean).join('\n') : '';
    captions.get('box').className = ['grid-caption', caption ? 'shown' : null, played.size && !caption ? 'calib-only' : null]
      .filter(Boolean).join(' ');
  }

  return { update, controls, ui };
}
