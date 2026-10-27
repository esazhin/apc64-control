// s8 supplier: each gesture issues exactly its API call and shows the answer (T36; A11, A29, A132–A139).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { connect, createHandlers, needsCardRefresh, needsOverviewRefresh } from './app.js';
import { bannerView, headerView, unitBanner } from './banner.js';
import { byClass, findAll, textOf } from './dom.js';
import { learnCardView, learnPorts, toolbarView } from './learn.js';
import { snapshot } from './page_fixtures.js';
import { createStore, initialModel, reduce } from './state.js';
import { tweakDefaults, tweakKey, tweakRequest, tweakView } from './tweak.js';

function recordingApi(answers = {}) {
  const calls = [];
  const api = new Proxy({}, {
    get(_, name) {
      return async (...args) => {
        calls.push([name, ...args]);
        const answer = answers[name];
        return typeof answer === 'function' ? answer(...args) : (answer ?? { ok: true, status: 200, data: {} });
      };
    },
  });
  return { api, calls };
}

function storeWith(overrides = {}) {
  const store = createStore();
  store.dispatch({ type: 'snapshot', data: snapshot(overrides) });
  return store;
}

const CARD = {
  control: 'pad r1c3', display: 'Pad r1c3', role: 'bindable', base: 'Note 38 → mpc ch 10, momentary', shift: null,
  mode: 'momentary', toggle: null, port_status: ['mpc connected'], elsewhere: [], reachable: 'verified',
  forms: { base: { assignment: 'note 38 on mpc ch 10', label: null, colour: { index: 5, name: 'red', rgb: '#ff0000' }, mode: 'momentary' },
    shift: null },
  layout: 'jam', page: 1, bank: 1, layer: 'base', base_hash: 'h1',
};

test('Yes, No and Release each make their one call; a refusal is shown plainly (A29)', async () => {
  const { api, calls } = recordingApi({ release: { ok: false, status: 409, problem: 'APC64 is not held', issues: [] } });
  const store = storeWith();
  const h = createHandlers(api, store);
  await h.take();
  await h.decline();
  await h.release();
  assert.deepEqual(calls, [['take'], ['decline'], ['release']]);
  assert.equal(store.model.ui.problem, 'APC64 is not held');
  const shown = bannerView(store.model, h);
  assert.match(textOf(shown), /APC64 is not held/);
});

test('press and release on the replica go out in order; Inspect only selects (A70)', async () => {
  const { api, calls } = recordingApi();
  const store = storeWith();
  const h = createHandlers(api, store);
  h.down('pad r1c1');
  h.up('pad r1c1');
  await h.flush();
  assert.deepEqual(calls.filter((c) => c[0] !== 'card'), [['press', 'pad r1c1'], ['unpress', 'pad r1c1']]);
  assert.equal(store.model.ui.selected, 'pad r1c1');
  calls.length = 0;
  h.mode('inspect');
  h.down('pad r1c2');
  h.up('pad r1c2');
  await h.flush();
  assert.deepEqual(calls, [['card', 'pad r1c2']]);
});

test('a strip drag touches, moves (coalesced to the latest value) and lets go', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const { api, calls } = recordingApi({ press: async () => { await gate; return { ok: true, status: 200, data: {} }; } });
  const store = storeWith();
  const h = createHandlers(api, store);
  h.stripDown('strip 3', 1000);
  h.stripMove('strip 3', 2000);
  h.stripMove('strip 3', 3000);                       // queued behind the press: only the latest is sent
  h.stripUp('strip 3');
  release();
  await h.flush();
  assert.deepEqual(calls.filter((c) => c[0] !== 'card'),
    [['press', 'strip 3'], ['move', 'strip 3', 3000], ['unpress', 'strip 3']]);
});

test('encoder, Shift, page, bank and layout clicks', async () => {
  const { api, calls } = recordingApi();
  const store = storeWith();
  let up = null;
  const h = createHandlers(api, store, { onWindowPointerUp: (fn) => { up = fn; } });
  h.turn(1);
  h.shiftHold();
  assert.equal(store.model.ui.previewShift, true);     // labels swap at once (A88)
  up();
  await h.flush();
  await h.page(2);
  await h.bank(3);
  await h.layout('tonnetz');
  assert.deepEqual(calls, [['move', 'encoder', 1], ['shift', true], ['shift', false], ['page', 2], ['bank', 3], ['load', 'tonnetz']]);
  assert.equal(store.model.ui.previewShift, false);
});

test('what the unit owns in its view is never pressed from the page; a press already sent is still let go', async () => {
  const { api, calls } = recordingApi();
  const chord = { unit: { ...snapshot().unit, view: 'chord' } };
  const store = storeWith(chord);
  const h = createHandlers(api, store);
  h.down('pad r1c1');                                   // Chord view: the unit plays its pads itself
  h.up('pad r1c1');
  h.down('track 1');                                    // buttons still reach the host in Chord view
  h.up('track 1');
  await h.flush();
  assert.deepEqual(calls.filter((c) => c[0] !== 'card'), [['press', 'track 1'], ['unpress', 'track 1']]);
  assert.equal(store.model.ui.notice, 'Chord view: the APC64 plays its pads itself; nothing was sent');
  assert.equal(store.model.ui.selected, 'track 1');
  // Custom view: strips, side buttons and the encoder stay on the unit; Shift and Tempo do not
  calls.length = 0;
  store.dispatch({ type: 'diff', data: { changed: { unit: { ...snapshot().unit, view: 'custom' } }, controls: {} } });
  h.stripDown('strip 2', 100);
  h.stripMove('strip 2', 200);
  h.stripUp('strip 2');
  h.down('mute');
  h.up('mute');
  h.turn(1);
  h.down('tempo');
  h.up('tempo');
  await h.flush();
  assert.deepEqual(calls.filter((c) => c[0] !== 'card'), [['press', 'tempo'], ['unpress', 'tempo']]);
  assert.equal(store.model.ui.notice, 'Custom view: encoder stays on the APC64; nothing was sent');
  // a pad pressed in Session view is released even if the unit has switched view meanwhile
  calls.length = 0;
  store.dispatch({ type: 'diff', data: { changed: { unit: { ...snapshot().unit, view: 'session' } }, controls: {} } });
  h.down('pad r1c1');
  store.dispatch({ type: 'diff', data: { changed: { unit: { ...snapshot().unit, view: 'note' } }, controls: {} } });
  h.up('pad r1c1');
  await h.flush();
  assert.deepEqual(calls.filter((c) => c[0] !== 'card'), [['press', 'pad r1c1'], ['unpress', 'pad r1c1']]);
});

test('the folded bar and the column beside the surface are remembered; Inspect shows the card', async () => {
  const { api } = recordingApi();
  const store = storeWith();
  const kept = [];
  const h = createHandlers(api, store, { remember: (key, value) => kept.push([key, value]) });
  assert.equal(store.model.ui.side, 'overview');                // the overview by default
  h.navCollapse(true);
  h.side('none');
  assert.equal(store.model.ui.navCollapsed, true);
  assert.equal(store.model.ui.side, 'none');
  assert.deepEqual(kept, [['apc64.nav', true], ['apc64.side', 'none']]);
  h.down('pad r1c1');                                   // Play: the column stays as chosen
  h.up('pad r1c1');
  assert.equal(store.model.ui.side, 'none');
  h.mode('inspect');
  h.down('pad r1c2');                                   // Inspect: looking at a card shows the card column
  assert.equal(store.model.ui.side, 'card');
  assert.equal(kept.length, 2);                         // … without changing the remembered choice
  await h.flush();
  const toolbar = toolbarView(reduce(store.model, { type: 'side', panel: 'overview' }), h);
  const choice = (side) => findAll(toolbar, (n) => n.tag === 'button' && n.props.data?.side === side)[0];
  assert.deepEqual(['overview', 'card', 'none'].map((s) => textOf(choice(s))), ['Overview', 'Card & activity', 'Hide']);
  assert.equal(choice('overview').props['aria-pressed'], 'true');
  choice('card').props.onclick();
  assert.equal(store.model.ui.side, 'card');
  assert.deepEqual(kept.at(-1), ['apc64.side', 'card']);
});

test('learn toggles, MIDI-learn and calibration make their calls (A132–A134)', async () => {
  const { api, calls } = recordingApi();
  const h = createHandlers(api, storeWith());
  await h.learnTouch(true);
  await h.learnMidi('pad r2c1', 'MPC Live III MIDI 1');
  await h.learnOff();
  await h.learnTouch(false);
  await h.calibrate('start');
  await h.calibrate('cancel');
  assert.deepEqual(calls, [['learn', 'touch'], ['learn', 'midi', 'MPC Live III MIDI 1', 'pad r2c1'], ['learn', 'off'],
    ['learn', 'off'], ['calibrate', 'start'], ['calibrate', 'cancel']]);
});

test('a tweak save sends one request against the card hash; stale and invalid answers are shown (A136, A139)', async () => {
  const answers = [
    { ok: true, status: 200, data: { ok: true } },
    { ok: false, status: 409, problem: 'layout changed, reload', issues: [] },
    { ok: false, status: 400, problem: 'jam.yaml line 7, pad r1c3: channel must be 1–16', issues: [{ text: 'a' }] },
  ];
  const { api, calls } = recordingApi({ tweak: () => answers.shift(), card: { ok: true, status: 200, data: CARD } });
  const store = storeWith();
  const h = createHandlers(api, store);
  await h.select('pad r1c3');
  await h.saveTweak(store.model.ui.card, 'base', 'colour', 'blue');
  assert.deepEqual(calls.filter((c) => c[0] === 'tweak')[0][1], { layout: 'jam', control: 'pad r1c3', layer: 'base',
    field: 'colour', value: 'blue', base_hash: 'h1', page: 1 });
  assert.equal(store.model.ui.tweakAnswer.text, 'Saved: pad r1c3 colour');
  await h.saveTweak(store.model.ui.card, 'base', 'colour', 'green');
  assert.deepEqual(store.model.ui.tweakAnswer, { tone: 'stale', text: 'layout changed, reload', issues: [] });
  assert.match(textOf(tweakView(store.model, h, [])), /layout changed, reload.*Reload/);
  await h.saveTweak(store.model.ui.card, 'base', 'assignment', 'note 38 on mpc ch 17');
  assert.equal(store.model.ui.tweakAnswer.text, 'jam.yaml line 7, pad r1c3: channel must be 1–16');
  const strip = { ...CARD, control: 'strip 2', bank: 2 };
  assert.deepEqual(tweakRequest(strip, 'shift', 'label', ''), { layout: 'jam', control: 'strip 2', layer: 'shift',
    field: 'label', value: null, base_hash: 'h1', bank: 2 });
});

test('the tweak form offers assignment, label, colour and mode, prefilled from the card', () => {
  let model = reduce(reduce(reduce(initialModel(), { type: 'snapshot', data: snapshot() }), { type: 'select', id: 'pad r1c3' }),
    { type: 'card', id: 'pad r1c3', data: CARD });
  const saved = [];
  const palette = [{ index: 5, name: 'red', rgb: '#ff0000' }, { index: 45, name: 'blue', rgb: '#0000ff' }, { index: 6, name: null, rgb: '#ff0000' }];
  const tree = tweakView(model, { saveTweak: (...args) => saved.push(args.slice(1)) }, palette);
  const inputs = findAll(tree, (n) => n.tag === 'input');
  assert.equal(inputs[0].props.value, 'note 38 on mpc ch 10');
  const colour = findAll(tree, (n) => n.tag === 'select' && n.props['aria-label'] === 'Colour')[0];
  assert.ok(findAll(colour, (n) => n.tag === 'option' && n.props.selected)[0].props.text.startsWith('red'));
  colour.props.onchange({ target: { value: '45' } });
  findAll(tree, (n) => n.tag === 'button' && n.props['data-field'] === 'colour')[0].props.onclick();
  inputs[0].props.oninput({ target: { value: 'cc 74 on mpc ch 1' } });
  findAll(tree, (n) => n.tag === 'button' && n.props['data-field'] === 'assignment')[0].props.onclick();
  assert.deepEqual(saved, [['base', 'colour', '45'], ['base', 'assignment', 'cc 74 on mpc ch 1']]);
  assert.deepEqual(tweakDefaults(CARD, 'shift'), { assignment: '', label: '', colour: '', mode: 'momentary', bound: false });
  const before = tweakKey(model);
  model = reduce(model, { type: 'tweak_layer', layer: 'shift' });
  assert.notEqual(tweakKey(model), before);
  const navigation = reduce(reduce(initialModel(), { type: 'select', id: 'scene 1' }),
    { type: 'card', id: 'scene 1', data: { control: 'scene 1', role: 'navigation' } });
  assert.match(textOf(tweakView(navigation)), /not bindable/);
});

test('the banners: the question, Busy, maybe stuck, firmware, errors and a lost connection', () => {
  const calls = [];
  const handlers = { take: () => calls.push('take'), decline: () => calls.push('decline') };
  const asking = snapshot({ unit: { ...snapshot().unit, status: 'asking', held: false, text: 'Take control of APC64?',
    notices: ['Released after an internal error'] } });
  const ask = unitBanner(asking, handlers);
  assert.match(textOf(ask), /Take control of APC64\?.*Released after an internal error/);   // A8, A28
  findAll(ask, (n) => n.tag === 'button').forEach((b) => b.props.onclick());
  assert.deepEqual(calls, ['take', 'decline']);
  const busy = snapshot({ unit: { ...snapshot().unit, status: 'busy', held: false, text: 'Busy: held by Bitwig Studio' } });
  assert.match(textOf(unitBanner(busy)), /Busy: held by Bitwig Studio/);                       // A9
  const stuck = snapshot({ unit: { ...snapshot().unit, status: 'maybe_stuck', held: false,
    text: 'APC64 may still be in DAW mode: Take to reset, or replug it' } });
  assert.match(textOf(unitBanner(stuck)), /Take to reset/);                                     // A20
  const firmware = snapshot({ unit: { ...snapshot().unit, warnings: ['untested firmware 1.2.2.0'] },
    warnings: ['untested firmware 1.2.2.0'] });
  assert.equal((textOf(bannerView(reduce(initialModel(), { type: 'snapshot', data: firmware }))).match(/untested firmware/g) ?? []).length, 1);
  const errors = snapshot({ errors: [{ text: 'jam.yaml line 7, pad r9c1: no such pad, pads are r1c1–r8c8' }] });
  let model = reduce(initialModel(), { type: 'snapshot', data: errors });
  assert.match(textOf(bannerView(model)), /jam\.yaml line 7, pad r9c1: no such pad/);          // A57
  model = reduce(model, { type: 'disconnected' });
  assert.match(textOf(bannerView(model)), /reconnecting/);
  const header = headerView(reduce(initialModel(), { type: 'snapshot', data: busy }), {});
  assert.equal(textOf(header[0]), 'Not held');                                                   // A4
});

test('toolbar and MIDI-learn section', () => {
  const calls = [];
  let model = reduce(initialModel(), { type: 'snapshot', data: snapshot() });
  const tree = toolbarView(model, { learnTouch: (on) => calls.push(['touch', on]), calibrate: (s) => calls.push(['cal', s]),
    mode: (m) => calls.push(['mode', m]) });
  findAll(tree, (n) => n.tag === 'button').forEach((b) => b.props.onclick());
  assert.deepEqual(calls, [['mode', 'play'], ['mode', 'inspect'], ['touch', true], ['cal', 'start']]);
  assert.doesNotMatch(textOf(tree), /View:/);            // the view is in the bar and on the surface
  model = reduce(model, { type: 'ports', data: [{ name: 'MPC Live III MIDI 1', direction: 'both', present: true },
    { name: 'Out Only', direction: 'output', present: true }] });
  model = reduce(reduce(model, { type: 'select', id: 'pad r1c3' }), { type: 'card', id: 'pad r1c3', data: CARD });
  assert.deepEqual(learnPorts(model, CARD), ['mpc', 'MPC Live III MIDI 1']);
  const listened = [];
  const section = learnCardView(model, { learnMidi: (c, p) => listened.push([c, p]) });
  findAll(section, (n) => n.tag === 'button')[0].props.onclick();
  assert.deepEqual(listened, [['pad r1c3', 'mpc']]);
  model = reduce(model, { type: 'diff', data: { changed: { learn: { mode: 'midi', selected: 'pad r1c3', port: 'MPC Live III MIDI 1' } }, controls: {} } });
  assert.match(textOf(learnCardView(model)), /Listening on MPC Live III MIDI 1/);
});

test('the socket feeds the store, and a drop reconnects to a fresh snapshot (A131)', () => {
  const sockets = [];
  class FakeWebSocket { constructor(url) { this.url = url; sockets.push(this); } }
  const timers = [];
  const store = createStore();
  connect(store, { WebSocketImpl: FakeWebSocket, url: 'ws://x/ws', setTimer: (fn) => timers.push(fn) });
  sockets[0].onmessage({ data: JSON.stringify({ type: 'snapshot', data: snapshot() }) });
  assert.equal(store.model.connected, true);
  sockets[0].onclose();
  assert.equal(store.model.connected, false);
  timers.shift()();
  sockets[1].onmessage({ data: JSON.stringify({ type: 'snapshot', data: snapshot({ bank: { n: 3, display: 'FX' } }) }) });
  assert.equal(store.model.state.bank.n, 3);
  sockets[1].onmessage({ data: 'not json' });
  assert.equal(sockets.length, 2);
});

test('card and overview refresh when what they show changed', () => {
  const a = reduce(reduce(initialModel(), { type: 'snapshot', data: snapshot() }), { type: 'select', id: 'pad r1c1' });
  const withCard = reduce(a, { type: 'card', id: 'pad r1c1', data: {} });
  assert.equal(needsCardRefresh(a, a), true);
  const moved = reduce(withCard, { type: 'diff', data: { changed: { page: { n: 2 } }, controls: {} } });
  assert.equal(needsCardRefresh(withCard, moved), true);
  const other = reduce(withCard, { type: 'diff', data: { changed: { oled: ['x', 'y'] }, controls: {} } });
  assert.equal(needsCardRefresh(withCard, other), false);
  assert.equal(needsOverviewRefresh(initialModel(), a), true);
  const shown = reduce(a, { type: 'overview', data: {} });
  assert.equal(needsOverviewRefresh(shown, reduce(shown, { type: 'diff', data: { changed: { oled: ['a', 'b'] }, controls: {} } })), false);
});

test('no page module asks the browser for MIDI access (A11)', () => {
  const offenders = readdirSync(new URL('.', import.meta.url))
    .filter((f) => f.endsWith('.js') && !f.endsWith('.test.js'))
    .filter((f) => readFileSync(new URL(f, import.meta.url), 'utf8').includes('requestMIDI' + 'Access'));
  assert.deepEqual(offenders, []);
});
