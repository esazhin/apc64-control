// Nav bar, detail card, overview and activity list (T35).
import test from 'node:test';
import assert from 'node:assert/strict';
import { byClass, byData, findAll, hasClass, textOf } from './dom.js';
import { activityView, clock } from './activity.js';
import { cardView } from './card.js';
import { NAV_KEY, SIDE_KEY, navFoldedByDefault, navView, remember, remembered, rememberedSide, sideByDefault, sideFits } from './nav.js';
import { overviewView } from './overview.js';
import { initialModel, reduce } from './state.js';
import { snapshot } from './page_fixtures.js';

const model0 = (overrides) => reduce(initialModel(), { type: 'snapshot', data: snapshot(overrides) });

test('the nav bar shows layout, pages and banks with names, current/defined/empty, and the view', () => {
  const calls = [];
  const tree = navView(model0({ layouts: [{ id: 'jam', name: 'Jam', valid: true }, { id: 'amb', name: 'Ambient', valid: false }] }),
    { page: (n) => calls.push(['page', n]), bank: (n) => calls.push(['bank', n]), layout: (v) => calls.push(['layout', v]) });
  const pages = byData(tree, 'page', 1)[0];
  assert.ok(pages.props.class.includes('current'));
  assert.equal(textOf(pages), '1Drums');
  const empty = byData(tree, 'page', 5)[0];
  assert.ok(empty.props.class.includes('empty'));
  assert.equal(empty.props.title, 'Page 5 is empty');
  assert.equal(byData(tree, 'bank', 1)[0].props.title, 'Bank 1: Mix');
  byData(tree, 'page', 2)[0].props.onclick();
  byData(tree, 'bank', 3)[0].props.onclick();
  const options = findAll(tree, (n) => n.tag === 'option');
  assert.deepEqual(options.map((o) => o.props.text), ['Jam', 'Ambient — invalid']);
  assert.ok(options[1].props.disabled);
  findAll(tree, (n) => n.tag === 'select')[0].props.onchange({ target: { value: 'amb' } });
  assert.deepEqual(calls, [['page', 2], ['bank', 3], ['layout', 'amb']]);
  assert.match(textOf(tree), /View: Session/);
  assert.doesNotMatch(textOf(tree), /Shift/);                     // Shift is on the surface now
});

test('the nav bar folds to one line with the layout, page, bank and view, and unfolds', () => {
  const calls = [];
  const handlers = { navCollapse: (c) => calls.push(c) };
  let model = model0({ unit: { ...snapshot().unit, view: 'chord' } });
  findAll(navView(model, handlers), (n) => n.tag === 'button' && hasClass(n, 'fold'))[0].props.onclick();
  model = reduce(model, { type: 'nav_collapsed', collapsed: true });
  const line = navView(model, handlers);
  assert.equal(line.length, 1);
  assert.ok(hasClass(line[0], 'navline'));
  assert.equal(textOf(line), 'LayoutJamPage 1 DrumsBank 1 MixView: Chord?Layouts, pages, banks ▾');
  assert.equal(findAll(line, (n) => n.tag === 'select' || hasClass(n, 'slot')).length, 0);
  const fold = findAll(line, (n) => n.tag === 'button' && hasClass(n, 'fold'))[0];
  assert.equal(fold.props['aria-expanded'], 'false');
  fold.props.onclick();
  assert.deepEqual(calls, [true, false]);
  const empty = model0({ page: { n: 3, name: null, display: '', defined: false, current: true } });
  assert.match(textOf(navView(reduce(empty, { type: 'nav_collapsed', collapsed: true }))), /Page 3 \(empty\)/);
});

test('the bar and column choices are remembered per viewer, and the page works without storage', () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.equal(remembered(storage, NAV_KEY, true), true);           // nothing stored: the default
  remember(storage, NAV_KEY, false);
  assert.equal(remembered(storage, NAV_KEY, true), false);
  const blocked = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } };
  assert.equal(remembered(blocked, NAV_KEY, true), true);
  assert.doesNotThrow(() => remember(blocked, NAV_KEY, true));
  assert.equal(remembered(null, NAV_KEY, false), false);
  assert.equal(rememberedSide(storage, 'overview'), 'overview');
  remember(storage, SIDE_KEY, 'card');
  assert.equal(rememberedSide(storage, 'overview'), 'card');
  store.set(SIDE_KEY, 'on');                                          // an older or foreign value: the default
  assert.equal(rememberedSide(storage, 'none'), 'none');
  assert.equal(rememberedSide(blocked, 'overview'), 'overview');
  assert.equal(navFoldedByDefault(741), true);
  assert.equal(navFoldedByDefault(1200), false);
  assert.equal(sideFits(2261, 741), true);                           // a wide, short window
  assert.equal(sideFits(1280, 720), true);
  assert.equal(sideFits(1000, 900), false);
  assert.equal(sideFits(390, 844), false);
  assert.equal(sideByDefault(2261, 741), 'overview');
  assert.equal(sideByDefault(1150, 1000), 'none');                    // side by side would shrink the surface
  assert.equal(sideByDefault(390, 844), 'overview');                  // stacked under the surface
});

test('the card shows both layers, mode, ports and where else it is bound, in one step (A129)', () => {
  let model = reduce(model0(), { type: 'select', id: 'pad r1c1' });
  assert.match(textOf(cardView(model)), /Loading/);
  const card = { control: 'pad r1c1', display: 'Pad r1c1', role: 'bindable', base: 'Note 36 → mpc ch 10, momentary',
    shift: 'Note 48 → mpc ch 10, momentary', mode: 'momentary', toggle: null, feedback: null,
    port_status: ['mpc connected'], elsewhere: [{ page: 2, bank: null, layer: 'base', text: 'Page 2: Note 50' }],
    reachable: 'unverified: live check pending', led: { colour: 5, rgb: '#ff0000', off: false }, page: 1, bank: 1, layer: 'base' };
  model = reduce(model, { type: 'card', id: 'pad r1c1', data: card });
  const calls = [];
  const tree = cardView(model, { page: (n) => calls.push(n) });
  const text = textOf(tree);
  for (const expected of ['Base', 'Note 36 → mpc ch 10, momentary', 'Shift', 'Note 48 → mpc', 'mpc connected',
    'Page 2: Note 50', 'unverified: live check pending', 'colour 5 (approximate)']) assert.ok(text.includes(expected), expected);
  findAll(tree, (n) => n.tag === 'button' && textOf(n) === 'Page 2: Note 50')[0].props.onclick();
  assert.deepEqual(calls, [2]);
  const current = findAll(tree, (n) => n.tag === 'dd' && n.props.class?.includes?.('current'));
  assert.equal(textOf(current[0]), 'Note 36 → mpc ch 10, momentary');
  assert.match(textOf(cardView(initialModel())), /Select a control/);
  const scene = reduce(reduce(model0(), { type: 'select', id: 'scene 2' }), { type: 'card', id: 'scene 2',
    data: { control: 'scene 2', display: 'Scene 2', role: 'navigation', elsewhere: [] } });
  assert.match(textOf(cardView(scene)), /Navigation: selects a page or strip bank, never sends MIDI/);
});

test('the overview shows every page as a mini grid and every bank as a strip set; clicking navigates', () => {
  const pages = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ n, name: n === 1 ? 'Drums' : n === 2 ? 'Keys' : null, defined: n <= 2,
    base: n === 1 ? { 'pad r1c1': { label: 'Note 36 → mpc', colour: 5, rgb: '#ff0000' }, play: { label: 'CC118 → mpc', colour: null, rgb: null } }
      : n === 2 ? { 'pad r1c1': { label: 'Note 50 → mpc', colour: null, rgb: null } } : {},
    shift: n === 1 ? { 'pad r1c1': { label: 'Note 48 → mpc', colour: null, rgb: null } } : {} }));
  const banks = [1, 2, 3, 4, 5, 6].map((n) => ({ n, name: n === 1 ? 'Mix' : null, defined: n === 1,
    base: n === 1 ? { 'strip 1': { label: 'CC20 → mpc', colour: 3, rgb: '#ffffff' } } : {}, shift: {} }));
  let model = reduce(model0(), { type: 'overview', data: { layout_name: 'Jam', page: 1, bank: 1, pages, banks } });
  const calls = [];
  const handlers = { page: (n) => calls.push(['page', n]), bank: (n) => calls.push(['bank', n]),
    overviewLayer: (l) => calls.push(['layer', l]) };
  let tree = overviewView(model, handlers);
  assert.equal(byClass(tree, 'ov-page').length, 8);
  assert.equal(byClass(tree, 'ov-bank').length, 6);
  assert.equal(byClass(tree, 'ov-cell').length, 8 * 64);
  const page1 = byData(tree, 'page', 1)[0];
  assert.ok(page1.props.class.includes('current'));
  const cell = findAll(page1, (n) => n.props.title === 'pad r1c1: Note 36 → mpc')[0];
  assert.equal(cell.props.style['--c'], '#ff0000');
  assert.match(textOf(page1), /play: CC118 → mpc/);
  byData(tree, 'page', 2)[0].props.onclick();
  byData(tree, 'page', 5)[0].props.onclick();        // empty: nothing
  byData(tree, 'bank', 1)[0].props.onclick();
  findAll(tree, (n) => n.tag === 'button' && textOf(n) === 'Shift')[0].props.onclick();
  assert.deepEqual(calls, [['page', 2], ['bank', 1], ['layer', 'shift']]);
  model = reduce(model, { type: 'overview_layer', layer: 'shift' });
  tree = overviewView(model, handlers);
  assert.ok(findAll(byData(tree, 'page', 1)[0], (n) => n.props.title === 'pad r1c1: Note 48 → mpc').length === 1);
  assert.match(textOf(overviewView(model0())), /No layout is live/);
});

test('the activity list shows the latest entries newest first, marked by result', () => {
  let model = model0();
  model = reduce(model, { type: 'activity', data: { id: 1, at: null, result: 'sent', text: 'pad r1c1 → note 36 ch 10 → mpc: sent' } });
  model = reduce(model, { type: 'activity', data: { id: 2, at: null, result: 'refused', text: 'refused: project write (0x14)' } });
  const tree = activityView(model);
  const items = findAll(tree, (n) => n.tag === 'li');
  assert.deepEqual(items.map((i) => i.props.class), ['refused', 'sent']);
  assert.equal(textOf(items[0]), '--:--:--refused: project write (0x14)');       // A31
  assert.match(textOf(activityView(model0())), /Nothing yet/);
  assert.match(clock(0), /^\d\d:\d\d:\d\d$/);
});
