// The lab panel (T37; s25, s26, s27; A7, A13, A16, A21, A37, A62, A64, A67, A81): it renders the recorded snapshot
// pair (lab.fixture.json, produced by the real services), each control dispatches its API call (a fetch double),
// and a refusal's message is shown verbatim.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { FakeDocument, FakeElement } from '../../../_apc64_host/presentation/static/fake_dom.js';
import { helpButton as hostHelpButton } from '../../../_apc64_host/presentation/static/help.js';
import {
  FLIP_KEY, HARMONY_ADDRESS, HARMONY_HELP, HARMONY_VIEW, LAB_HELP, MAIN_KEY, PERFORMER_HELP, SLOTS, UNIT_HINT,
  changedGlobals, createLab, globalsView, harmonyFullPart, harmonySectionView, helpButton, labApi, memoryView,
  clockStatus, mountPanel, performerView, rememberedFlip, rememberedMain, resultView, statusView, unitHint,
} from './lab.js';
import { byClass, byData, findAll, hasClass, mount, textOf } from './lab_dom.js';
import { markPlayhead } from './performer_editor.js';

const FIXTURE = JSON.parse(readFileSync(new URL('./lab.fixture.json', import.meta.url)));
// the performer's state as the real service answered it (a guitar layout playing the waltz at step 2; and idle)
const PERFORMER = JSON.parse(readFileSync(new URL('./performer.fixture.json', import.meta.url)));
const BUSY = 'busy: push to slot 5 in progress';

// The host's createApi answers {ok, status, data} or {ok: false, status, data, problem}.
function fakeApi(answers = {}) {
  const calls = [];
  return {
    calls,
    async call(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      const answer = answers[`${method} ${path}`];
      if (typeof answer === 'function') return answer(body);
      if (answer) return answer;
      const data = {
        'GET /api/lab': FIXTURE.lab, 'GET /api/lab/harmony': FIXTURE.harmony,
        'GET /api/lab/backups': FIXTURE.backups, 'GET /api/lab/library': FIXTURE.library,
        'GET /api/lab/globals': FIXTURE.globals, 'GET /api/lab/performer': PERFORMER.idle,
        'GET /api/lab/harmony/inputs': { apc64: ['APC64 Custom', 'APC64 Notes'], inputs: [] },
        'GET /api/ports': [{ name: 'Keystation 49 MIDI 1', direction: 'input', present: true },
          { name: 'APC64 Notes', direction: 'input', present: true },
          { name: 'MPC Live III MIDI 1', direction: 'both', present: true }],
      }[`${method} ${path}`];
      return { ok: true, status: 200, data: data ?? { result: 'unchanged', backup: null, message: 'done' } };
    },
  };
}

const refused = (status, problem, extra = {}) => ({ ok: false, status, problem, data: { problem, ...extra } });
const model = (topics = {}) => ({ topics: { lab: topics }, state: { controls: {} } });

async function loaded(answers) {
  const api = fakeApi(answers);
  const lab = createLab({ api });
  await lab.actions.load();
  api.calls.length = 0;
  return { api, lab, view: lab.view, actions: lab.actions };
}

const clicks = (tree, action) => findAll(tree, (n) => n.tag === 'button' && n.props?.data?.action === action);

// --- what the panel shows (A81) ---------------------------------------------------------------------------
test('without documentation the panel shows generators, the active layout with its window and the unit hint, backups, the 24 slots and the globals (A81)', async () => {
  const { view, actions } = await loaded();
  const status = statusView(model({ lab: FIXTURE.lab }), view, actions);
  const text = textOf(status);
  assert.deepEqual(byData(status, 'generator', 'tonnetz').map(textOf), ['tonnetz base 0–127 (default 48), channel 1–16 (default 1)']);
  assert.ok(byData(status, 'generator', 'isomorphic').length === 1);
  assert.deepEqual(findAll(status, (n) => n.props?.data?.scheme).map((n) => n.props.data.scheme), ['fifths', 'root-highlight', 'scale']);
  assert.match(text, /Tonnetz C/);
  assert.equal(textOf(byData(status, 'window', '')[0]).startsWith('Oct +0'), true);
  assert.ok(byClass(status, 'unit-hint').some((n) => textOf(n) === UNIT_HINT));
  assert.equal(UNIT_HINT, 'encoder: shift · Tempo: interval');
  assert.match(text, /notes → notes are only shown: no default target and no layout target/);   // §2.7 q2
  const memory = memoryView(model(), view, actions);
  const tiles = findAll(memory, (n) => n.props?.data?.slot !== undefined && hasClass(n, 'slot-tile'));
  assert.deepEqual(tiles.map((t) => t.props.data.slot), [0, ...SLOTS]);
  assert.equal(SLOTS.length, 24);
  assert.equal(textOf(tiles[7]).startsWith('7'), true);
  assert.match(textOf(memory), /slot0-2026-10-24T20-15/);   // the session backup is listed
  assert.match(text, /session backup slot0-2026-10-24T20-15/);
  const globals = globalsView(model(), view, actions);
  const led = byData(globals, 'global', 'led_level')[0];
  assert.equal(textOf(led.children[1]), '75%');   // A62
  assert.ok(byData(globals, 'global', 'device_mode')[0] && byData(globals, 'global', 'cv8_channel')[0]
    && byData(globals, 'global', 'drum16_note')[0]);
  assert.match(textOf(byData(globals, 'global', 'cv1_source')[0]), /\[TBD\]/);
  assert.equal(byClass(byData(globals, 'global', 'device_mode')[0], 'hazard').length, 1);
});

test('pad r1c1 shows #FFFFFF, the colour written to the unit, without an approximate mark (A21)', async () => {
  const { view, actions } = await loaded();
  const section = harmonySectionView(model({ lab: FIXTURE.lab, harmony: FIXTURE.harmony }), view, actions);
  const r1c1 = byData(section, 'pad', 'r1c1')[0];
  assert.equal(r1c1.props.data.rgb, '#FFFFFF');
  assert.equal(hasClass(r1c1, 'approx'), false);
  assert.equal(textOf(byClass(section, 'chord')[0]), 'C');   // the harmony half of the pair
});

test('the topic data wins over what was fetched, so updates show in the order published (s25)', async () => {
  const { view, actions } = await loaded();
  const later = { ...FIXTURE.lab, active: { ...FIXTURE.lab.active, interval: '5th', offset: 1, oled: ['Tonnetz C', '5th +1'] } };
  const status = statusView(model({ lab: later }), view, actions);
  assert.equal(textOf(byData(status, 'window', '')[0]).startsWith('5th +1'), true);
  const harmony = harmonySectionView(model({ harmony: { ...FIXTURE.harmony, chord: 'Am' } }), view, actions);
  assert.equal(textOf(byClass(harmony, 'chord')[0]), 'Am');
});

// --- each control sends its request (s26, s27) --------------------------------------------------------------
test('activating a layout, the unit controls and the tweaks send their requests (A13, A16, A37)', async () => {
  const layouts = [...FIXTURE.lab.layouts, { name: 'Tonnetz C copy', layout: 'tonnetz-c-copy', generator: 'tonnetz', valid: true }];
  const { api, view, actions } = await loaded();
  const status = statusView(model({ lab: { ...FIXTURE.lab, layouts } }), view, actions);
  const [copy] = clicks(status, 'activate').filter((b) => b.props.data.layout === 'Tonnetz C copy');
  await copy.props.onclick();
  await clicks(status, 'turn-right')[0].props.onclick();
  await clicks(status, 'tempo')[0].props.onclick();
  actions.draftBase('D2');
  await clicks(status, 'save-base')[0].props.onclick();
  await clicks(status, 'leave')[0].props.onclick();
  const posts = api.calls.filter(([m]) => m === 'POST');
  assert.deepEqual(posts, [
    ['POST', '/api/lab/activate', { layout: 'Tonnetz C copy' }],
    ['POST', '/api/control/encoder/move', { value: 1 }],
    ['POST', '/api/control/tempo/press', {}], ['POST', '/api/control/tempo/release', {}],
    ['POST', '/api/lab/tweak', { field: 'base', value: 'D2' }],
    ['POST', '/api/lab/leave', {}],
  ]);
});

test('project memory controls send their requests', async () => {
  const { api, view, actions } = await loaded();
  actions.selectSlot(7);
  let memory = memoryView(model(), view, actions);
  await clicks(memory, 'backup-all')[0].props.onclick();
  await clicks(memory, 'backup-slot')[0].props.onclick();
  await clicks(memory, 'push')[0].props.onclick();
  await clicks(memory, 'restore')[0].props.onclick();
  actions.draftCapture('Live set B');
  await clicks(memory, 'capture')[0].props.onclick();
  await clicks(memory, 'read-slot')[0].props.onclick();
  const posts = api.calls.filter(([m, p]) => m === 'POST' || p.startsWith('/api/lab/slots'));
  assert.deepEqual(posts, [
    ['POST', '/api/lab/backup', { all: true }],
    ['POST', '/api/lab/backup', { slot: 7 }],
    ['POST', '/api/lab/push', { entry: 'Tonnetz C', slot: 7 }],
    ['POST', '/api/lab/restore', { backup: 'slot7-2026-10-24T20-15', slot: 7 }],
    ['POST', '/api/lab/library/capture', { slot: 7, name: 'Live set B' }],
    ['GET', '/api/lab/slots/7'],
  ]);
  memory = memoryView(model(), view, actions);
  assert.equal(clicks(memoryView(model(), { ...view, slot: 0 }, actions), 'push').length, 0);   // slot 0: activate instead
});

test('importing a .APC64 file sends it as base64 under its name', async () => {
  const api = fakeApi();
  const lab = createLab({ api, readFile: async () => 'AwAAAA==' });
  await lab.actions.importFile({ name: 'Boss RC-600.APC64' });
  assert.deepEqual(api.calls.at(0), ['POST', '/api/lab/import', { name: 'Boss RC-600', file: 'Boss RC-600.APC64', data_base64: 'AwAAAA==' }]);
});

test('a library entry can be previewed, and the harmony inputs chosen (§2.7 q4, q7)', async () => {
  const library = [{ name: 'Live set B', kind: 'captured', source: 'slot 12', pads: 64, strips: 8 }];
  const { api, view, actions } = await loaded({ 'GET /api/lab/library': { ok: true, status: 200, data: library },
    'POST /api/lab/harmony/inputs': (body) => ({ ok: true, status: 200, data: { apc64: [], inputs: body.inputs, message: 'harmony follows the APC64 and Keystation 49 MIDI 1' } }) });
  await clicks(memoryView(model(), view, actions), 'preview')[0].props.onclick();
  const section = harmonySectionView(model({ harmony: FIXTURE.harmony }), view, actions);
  const boxes = findAll(section, (n) => n.tag === 'input' && n.props?.data?.input);
  assert.deepEqual(boxes.map((b) => b.props.data.input), ['Keystation 49 MIDI 1', 'MPC Live III MIDI 1']);   // never the APC64
  await boxes[0].props.onchange({ target: { checked: true } });
  assert.deepEqual(api.calls.filter(([m]) => m === 'POST'), [
    ['POST', '/api/lab/preview', { entry: 'Live set B' }],
    ['POST', '/api/lab/harmony/inputs', { inputs: ['Keystation 49 MIDI 1'] }]]);
  assert.deepEqual(view.inputs.inputs, ['Keystation 49 MIDI 1']);
});

// --- globals: one write, unchanged, and the confirmation (A62–A67) ----------------------------------------
test('changed globals go in one request; unchanged ones are not sent (A65)', async () => {
  const { api, view, actions } = await loaded();
  actions.draftGlobal('led_level', '100');
  actions.draftGlobal('cv2_channel', '4');
  actions.draftGlobal('cv3_channel', '1');   // already 1
  assert.deepEqual(changedGlobals(view), { led_level: 100, cv2_channel: 4 });
  await clicks(globalsView(model(), view, actions), 'apply-globals')[0].props.onclick();
  assert.deepEqual(api.calls.find(([m]) => m === 'POST'), ['POST', '/api/lab/globals', { changes: { led_level: 100, cv2_channel: 4 } }]);
});

test('a device-mode change asks for the confirmation with the service\'s own words, then sends it (A64)', async () => {
  const problem = 'device mode change needs confirmation: it changes how the unit starts; repeat the command with confirm';
  const { api, view, actions } = await loaded({
    'POST /api/lab/globals': (body) => (body.confirm ? { ok: true, status: 200, data: { message: 'set Device mode Standalone' } }
      : refused(400, problem, { field: 'device_mode' })) });
  actions.draftGlobal('device_mode', '1');
  await actions.applyGlobals();
  const globals = globalsView(model(), view, actions);
  assert.equal(textOf(byData(globals, 'part', 'confirm')[0].children[0]), problem);
  assert.equal(textOf(resultView(view)), problem);
  await clicks(globals, 'confirm-globals')[0].props.onclick();
  assert.deepEqual(api.calls.filter(([m]) => m === 'POST'), [
    ['POST', '/api/lab/globals', { changes: { device_mode: 1 } }],
    ['POST', '/api/lab/globals', { changes: { device_mode: 1 }, confirm: true }]]);
  assert.equal(textOf(resultView(view)), 'set Device mode Standalone');
  assert.equal(view.confirm, null);
});

test('the service\'s unchanged message is shown as it is (A67)', async () => {
  const { view, actions } = await loaded({ 'POST /api/lab/globals': { ok: true, status: 200, data: {
    result: 'unchanged', backup: null, message: 'LED level unchanged; nothing written' } } });
  actions.draftGlobal('led_level', '100');
  await actions.applyGlobals();
  assert.equal(textOf(resultView(view)), 'LED level unchanged; nothing written');
});

test('a 409 is shown verbatim (A7)', async () => {
  const { view, actions } = await loaded({ 'POST /api/lab/push': refused(409, BUSY) });
  actions.selectSlot(7);
  await actions.push();
  const result = resultView(view);
  assert.equal(textOf(result), BUSY);
  assert.equal(hasClass(result, 'bad'), true);
});

test('without the unit the globals say why, in the service\'s words', async () => {
  const { view, actions } = await loaded({ 'GET /api/lab/globals': refused(409, 'take control of the APC64 first; nothing read or written') });
  await actions.readGlobals(true);
  assert.equal(textOf(byData(globalsView(model(), view, actions), 'problem', '')[0]),
    'take control of the APC64 first; nothing read or written');
});

test('a pending recovery offers restore and dismiss (a8)', async () => {
  const recovery = { backup: 'slot0-2026-10-24T20-15', message: 'the last lab session did not end cleanly; …' };
  const { api, view, actions } = await loaded();
  const status = statusView(model({ lab: { ...FIXTURE.lab, recovery } }), view, actions);
  await clicks(status, 'restore-recovery')[0].props.onclick();
  await clicks(status, 'dismiss-recovery')[0].props.onclick();
  assert.deepEqual(api.calls.filter(([m]) => m === 'POST'), [
    ['POST', '/api/lab/restore', { backup: 'slot0-2026-10-24T20-15', slot: 0 }],
    ['POST', '/api/lab/recovery/dismiss', {}]]);
});

test('the routes the panel calls are the lab API\'s', () => {
  const api = fakeApi();
  const lab = labApi(api);
  lab.dismissRecovery(); lab.selectInputs([]); lab.changeGlobals({ led_level: 100 }, true);
  assert.deepEqual(api.calls, [['POST', '/api/lab/recovery/dismiss', {}], ['POST', '/api/lab/harmony/inputs', { inputs: [] }],
    ['POST', '/api/lab/globals', { changes: { led_level: 100 }, confirm: true }]]);
});

// --- mounting into the page shell ------------------------------------------------------------------------
class SvgDocument extends FakeDocument {
  constructor() {
    super();
    this.head = new FakeElement('head');
    this.body = new FakeElement('body');
    this.ns = [];
  }
  createElementNS(ns, tag) { this.ns.push(tag); const el = new FakeElement(tag); el.namespaceURI = ns; return el; }
  getElementById(id) { return this.head.all((e) => e.attributes.id === id || e.id === id)[0] ?? null; }
}

test('mountPanel renders its parts, draws the lattice as SVG, links its styles once and follows the store', async () => {
  const doc = new SvgDocument();
  let current = model({ lab: FIXTURE.lab, harmony: FIXTURE.harmony });
  const listeners = [];
  const store = { get model() { return current; }, subscribe: (fn) => listeners.push(fn) };
  const element = new FakeElement('section');
  const queue = [];
  const mounted = mountPanel(element, { store, api: fakeApi(), panel: { name: 'lab', entry: '/modules/lab/lab.js' } },
    { doc, schedule: (fn) => queue.push(fn) });
  await mounted.ready;
  while (queue.length) queue.shift()();
  assert.equal(doc.head.children.length, 1);
  assert.equal(doc.head.children[0].href, '/modules/lab/lab.css');
  assert.ok(doc.ns.includes('svg') && doc.ns.includes('polygon'));
  assert.match(mounted.containers.status.textContent, /encoder: shift · Tempo: interval/);
  assert.match(mounted.containers.harmony.textContent, /C/);
  current = model({ lab: FIXTURE.lab, harmony: { ...FIXTURE.harmony, chord: 'Am' } });
  listeners.forEach((fn) => fn(current));
  while (queue.length) queue.shift()();
  assert.equal(mounted.containers.harmony.byClass('chord')[0].textContent, 'Am');
  mountPanel(new FakeElement('section'), { store, api: fakeApi() }, { doc, schedule: () => {} });
  assert.equal(doc.head.children.length, 1);   // the stylesheet is linked once
});

// --- live session 2026-10-26 ----------------------------------------------------------------------------------
test('the Lab and Harmony "?" open their topics in the host page\'s overlay (handlers.help)', async () => {
  const opened = [];
  const doc = new SvgDocument();
  const store = { model: model({ lab: FIXTURE.lab, harmony: FIXTURE.harmony }), subscribe: () => {} };
  const mounted = mountPanel(new FakeElement('section'), { store, api: fakeApi(), handlers: { help: (t) => opened.push(t) } },
    { doc, schedule: () => {} });
  await mounted.ready;
  const { view, actions } = mounted.controller;
  const helpOf = (tree) => findAll(tree, (n) => n.tag === 'button' && hasClass(n, 'help-btn'));
  helpOf(statusView(store.model, view, actions)).forEach((b) => b.props.onclick());
  helpOf(harmonySectionView(store.model, view, actions)).forEach((b) => b.props.onclick());
  assert.deepEqual(opened, [LAB_HELP, HARMONY_HELP]);
  const terms = LAB_HELP.items.filter(Array.isArray).map(([term]) => term);
  assert.deepEqual(terms, ['Generated layouts', 'Window', 'base, tuning, scheme', 'Leave', 'Project memory']);
  assert.match(HARMONY_HELP.items.flat().join(' '), /Tick another input/);
  // the panel's button is the host's: same element, class, label and topic
  const ours = helpButton(LAB_HELP, actions);
  const host = hostHelpButton(LAB_HELP, {});
  assert.equal(ours.tag, host.tag);
  for (const key of ['class', 'title', 'aria-label', 'aria-haspopup', 'type']) assert.equal(ours.props[key], host.props[key], key);
  assert.equal(textOf(ours), textOf(host));
  assert.equal(createLab({ api: fakeApi() }).actions.help(LAB_HELP), undefined);   // without the host: nothing happens
});

test('the answer line is always there, so an answer appearing moves nothing below it', async () => {
  const { view, actions } = await loaded();
  const idle = resultView(view);
  assert.ok(hasClass(idle, 'lab-result') && hasClass(idle, 'idle'));
  assert.match(textOf(idle), /answer to the last button/);
  await actions.turn(1);
  const answer = resultView(view);
  assert.ok(hasClass(answer, 'lab-result') && hasClass(answer, 'ok') && !hasClass(answer, 'idle'));
  assert.equal(textOf(answer), 'encoder +1');
});

// --- the harmony full view (?view=harmony, or Full screen) ----------------------------------------------------
const inView = (topics, ui = {}) => ({ ...model(topics), connected: true,
  ui: { view: { name: HARMONY_VIEW, pinned: false }, fullscreen: false, ...ui } });
const clicksOf = (tree) => findAll(tree, (n) => n.tag === 'button');
const links = (tree, action) => findAll(tree, (n) => n.tag === 'a' && n.props?.data?.action === action);

test('the Harmony heading has Full screen (the host page\'s openView) and New tab (?view=harmony in a new tab)', async () => {
  const opened = [];
  const page = { openView: (name, options) => opened.push([name, options]) };
  const lab = createLab({ api: fakeApi(), page });
  await lab.actions.load();
  const section = harmonySectionView(model({ harmony: FIXTURE.harmony }), lab.view, lab.actions);
  const heading = section[0];
  assert.equal(heading.tag, 'h2');
  clicks(heading, 'harmony-fullscreen')[0].props.onclick();
  assert.deepEqual(opened, [['harmony', { fullscreen: true }]]);
  const [tab] = links(heading, 'harmony-tab');
  assert.deepEqual([tab.props.href, tab.props.target, tab.props.rel], [HARMONY_ADDRESS, '_blank', 'noopener']);
  assert.equal(new URL(HARMONY_ADDRESS, 'http://192.168.1.20:5058/').href, 'http://192.168.1.20:5058/?view=harmony');
  assert.match(HARMONY_HELP.items.flat().join(' '), /Full screen.*New tab.*\?view=harmony/);
});

test('the full view: nothing until it is the page\'s view; then the heading, the inputs, the toggle and Leave', async () => {
  const calls = [];
  const page = { closeView: () => calls.push('close'), toggleFullscreen: () => calls.push('toggle') };
  const lab = createLab({ api: fakeApi(), page });
  await lab.actions.load();
  assert.deepEqual(harmonyFullPart(model({ harmony: FIXTURE.harmony }), lab.view, lab.actions), []);
  const full = harmonyFullPart(inView({ harmony: FIXTURE.harmony, lab: FIXTURE.lab }), lab.view, lab.actions);
  assert.equal(byData(full, 'part', 'inputs').length, 1);
  assert.ok(byData(full, 'input', 'Keystation 49 MIDI 1').length);
  assert.equal(findAll(full, (n) => hasClass(n, 'help-btn')).length, 1);
  assert.equal(textOf(clicks(full, 'toggle-fullscreen')[0]), 'Full screen');
  clicks(full, 'toggle-fullscreen')[0].props.onclick();
  clicks(full, 'leave-full')[0].props.onclick();
  assert.deepEqual(calls, ['toggle', 'close']);
  assert.ok(hasClass(byClass(full, 'full-conn')[0], 'live'));
  // full screen on: the toggle says so; the address's tab has no Leave but a link to the whole page
  const pinned = harmonyFullPart(inView({ harmony: FIXTURE.harmony }, { fullscreen: true, view: { name: 'harmony', pinned: true } }),
    lab.view, lab.actions);
  assert.equal(textOf(clicks(pinned, 'toggle-fullscreen')[0]), 'Exit full screen');
  assert.deepEqual([clicks(pinned, 'leave-full').length, links(pinned, 'whole-page')[0].props.href], [0, './']);
  // the panel's own copy steps aside meanwhile
  const panel = harmonySectionView(inView({ harmony: FIXTURE.harmony }), lab.view, lab.actions);
  assert.equal(findAll(panel, (n) => n.tag === 'svg').length, 0);
  assert.match(textOf(panel), /Shown in the full view/);
});

test('mountPanel draws the full view into its own element in <body>, shown only while it is the page\'s view', async () => {
  const doc = new SvgDocument();
  let current = model({ lab: FIXTURE.lab, harmony: FIXTURE.harmony });
  const listeners = [];
  const store = { get model() { return current; }, subscribe: (fn) => listeners.push(fn) };
  const queue = [];
  const flush = () => { while (queue.length) queue.shift()(); };
  const element = new FakeElement('section');
  const mounted = mountPanel(element, { store, api: fakeApi(), handlers: {} }, { doc, schedule: (fn) => queue.push(fn) });
  await mounted.ready;
  flush();
  const full = mounted.containers.full;
  assert.equal(doc.body.children[0], full);
  assert.ok(!element.children.includes(full));
  assert.deepEqual([full.classList.contains('module-view'), full.classList.contains('current'), full.dataset.view],
    [true, false, 'harmony']);
  assert.equal(full.children.length, 0);
  current = inView({ lab: FIXTURE.lab, harmony: FIXTURE.harmony });
  listeners.forEach((fn) => fn(current));
  flush();
  assert.ok(full.classList.contains('current'));
  assert.equal(full.byClass('chord')[0].textContent, 'C');
  assert.equal(mounted.containers.harmony.byClass('chord').length, 0);
  current = inView({ lab: FIXTURE.lab, harmony: { ...FIXTURE.harmony, chord: 'Am' } });
  listeners.forEach((fn) => fn(current));
  flush();
  assert.equal(full.byClass('chord')[0].textContent, 'Am');   // live: the same topic feed as the panel
  current = model({ lab: FIXTURE.lab, harmony: FIXTURE.harmony });
  listeners.forEach((fn) => fn(current));
  flush();
  assert.deepEqual([full.classList.contains('current'), full.children.length], [false, 0]);
  assert.equal(mounted.containers.harmony.byClass('chord')[0].textContent, 'C');
});

test('the full view\'s styles: every area placed, the wide layout fits one screen, the SVGs fill their areas', () => {
  const css = readFileSync(new URL('./lab.css', import.meta.url), 'utf8');
  for (const area of ['chord', 'pads', 'main', 'circle', 'hints']) {
    assert.match(css, new RegExp(`\\.full-views > \\[data-area="${area}"\\] \\{ grid-area: ${area}; \\}`));
  }
  assert.match(css, /grid-template-areas: "chord pads" "main circle" "hints hints"/);   // wide, the Tonnetz: side by side
  assert.match(css, /grid-template-areas: "chord chord" "main circle" "hints hints"/);   // wide, the pad grid
  assert.match(css, /grid-template-areas: "chord chord" "main main" "circle pads" "hints hints"/);   // tall
  assert.match(css, /grid-template-areas: "chord" "main" "hints" "circle" "pads"/);   // a phone
  assert.match(css, /grid-template-areas: "chord chord chord" "main main main" "hints circle pads"/);   // wide, the neck
  // the reserved rows scale with their own font size (em heights), so they stay steady at any size
  assert.match(css, /\.full-views \.chord-row \{ font-size: var\(--chord-size\); height: 1\.2em;/);
});

// --- the main view follows the layout; the full view's Main choice ------------------------------------------
const FOURTHS_LAB = { ...FIXTURE.lab, active: { ...FIXTURE.lab.active, name: 'Fourths', layout: 'fourths',
  definition: { generator: 'isomorphic', params: { base: 36, column: 1, row: 5, channel: 1 }, scheme: 'fifths' },
  pads: FIXTURE.lab.active.pads.map((p, i) => ({ ...p, note: 36 + (i % 8) + 5 * Math.floor(i / 8), silent: false })) } };

test('the Harmony section shows the Tonnetz for a Tonnetz layout and the pad grid for any other', async () => {
  const lab = createLab({ api: fakeApi() });
  await lab.actions.load();
  const tonnetz = harmonySectionView(model({ lab: FIXTURE.lab, harmony: FIXTURE.harmony }), lab.view, lab.actions);
  assert.equal(byClass(tonnetz, 'lattice').length, 1);
  assert.equal(byClass(tonnetz, 'lab-pad').length, 64);          // the small replica beside it
  const fourths = harmonySectionView(model({ lab: FOURTHS_LAB, harmony: FIXTURE.harmony }), lab.view, lab.actions);
  assert.equal(byClass(fourths, 'lattice').length, 0);
  assert.equal(byClass(fourths, 'grid-pad').length, 64);
  assert.equal(byClass(fourths, 'lab-pad').length, 0);
  assert.equal(byClass(fourths, 'circle').length, 1);             // the circle always
});

test('the full view\'s Main: Auto / Tonnetz / Pads overrides the main view there and is remembered', async () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const saved = globalThis.localStorage;
  globalThis.localStorage = storage;
  try {
    const lab = createLab({ api: fakeApi() });
    await lab.actions.load();
    assert.equal(lab.view.mainView, 'auto');
    const full = () => harmonyFullPart(inView({ lab: FOURTHS_LAB, harmony: FIXTURE.harmony }), lab.view, lab.actions);
    assert.equal(byClass(full(), 'grid-pad').length, 64);
    const choice = byData(full(), 'part', 'main-choice')[0];
    assert.deepEqual(clicksOf(choice).map((b) => b.props.data.main), ['auto', 'tonnetz', 'pads']);
    clicksOf(choice).find((b) => b.props.data.main === 'tonnetz').props.onclick();
    assert.equal(store.get(MAIN_KEY), 'tonnetz');
    assert.equal(byClass(full(), 'lattice').length, 1);
    assert.equal(byClass(full(), 'grid-pad').length, 0);
    assert.equal(byData(full(), 'main', 'tonnetz').find((n) => n.tag === 'button').props['aria-pressed'], 'true');
    // the panel keeps deciding by the layout
    assert.equal(byClass(harmonySectionView(model({ lab: FOURTHS_LAB, harmony: FIXTURE.harmony }), lab.view, lab.actions),
      'grid-pad').length, 64);
    assert.equal(createLab({ api: fakeApi() }).view.mainView, 'tonnetz');   // a new page remembers it
  } finally {
    globalThis.localStorage = saved;
  }
  // storage that refuses (a private window, blocked site data): the choice is auto, nothing throws
  assert.equal(rememberedMain({ getItem: () => { throw new Error('denied'); } }), 'auto');
  assert.equal(rememberedMain(undefined), 'auto');
  assert.equal(rememberedMain({ getItem: () => 'sideways' }), 'auto');
});


// --- a guitar layout (the guitar amendment): its window, its tuning, its neck -------------------------------------
const GUITAR = FIXTURE.guitar;

test('a guitar layout shows its own window steps, its unit hint and a tuning choice instead of base', async () => {
  const { api, view, actions } = await loaded();
  const status = statusView(model({ lab: GUITAR.lab }), view, actions);
  const window = byData(status, 'window', '')[0];
  assert.match(textOf(window), /^Fret 3-10 · steps Fret \/ Page · 0–24 \(8 on the pads\)$/);
  assert.equal(unitHint(GUITAR.lab.active), 'encoder: one fret · Tempo: Fret ↔ Page');
  assert.equal(unitHint(FIXTURE.lab.active), UNIT_HINT);
  assert.ok(textOf(status).includes('encoder: one fret · Tempo: Fret ↔ Page'));
  assert.equal(clicks(status, 'tempo')[0].props.title, 'next step kind: Fret → Page');
  assert.equal(byData(status, 'field', 'base').length, 0);              // the guitar has no base
  const tuning = byData(status, 'field', 'tuning')[0];
  const options = findAll(tuning, (n) => n.tag === 'option');
  assert.equal(options.find((o) => o.props.selected).props.value, 'e-standard');
  assert.ok(options.some((o) => o.props.value === 'drop-d') && options.some((o) => o.props.value === 'bass-5'));
  await tuning.props.onchange({ target: { value: 'drop-d' } });
  assert.deepEqual(api.calls.filter(([m]) => m === 'POST'), [['POST', '/api/lab/tweak', { field: 'tuning', value: 'drop-d' }]]);
  // a tuning written as a list shows as custom until a preset is chosen
  const custom = { ...GUITAR.lab, active: { ...GUITAR.lab.active, definition: { ...GUITAR.lab.active.definition,
    params: { tuning: [38, 45, 50, 55, 59, 64], frets: 24 } } } };
  const select = byData(statusView(model({ lab: custom }), view, actions), 'field', 'tuning')[0];
  assert.equal(findAll(select, (n) => n.tag === 'option' && n.props.selected)[0].props.text, 'custom: 38 45 50 55 59 64');
  // a Tonnetz layout keeps base and no tuning
  const tonnetz = statusView(model({ lab: FIXTURE.lab }), view, actions);
  assert.equal(byData(tonnetz, 'field', 'base').length, 1);
  assert.equal(byData(tonnetz, 'field', 'tuning').length, 0);
});

test('the Harmony section shows a guitar layout\'s neck with the box at the window', async () => {
  const lab = createLab({ api: fakeApi() });
  await lab.actions.load();
  const section = harmonySectionView(model({ lab: GUITAR.lab, harmony: GUITAR.harmony }), lab.view, lab.actions);
  const neck = byClass(section, 'neck')[0];
  assert.ok(neck);
  assert.deepEqual([byClass(neck, 'window-box')[0].props.data.first, byClass(neck, 'window-box')[0].props.data.last], [3, 10]);
  assert.equal(byClass(neck, 'played').length, 2);
});

test('the full view offers Neck and a remembered left-handed flip for a guitar layout', async () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const saved = globalThis.localStorage;
  globalThis.localStorage = storage;
  try {
    const lab = createLab({ api: fakeApi() });
    await lab.actions.load();
    const full = (lab_ = GUITAR.lab) => harmonyFullPart(inView({ lab: lab_, harmony: GUITAR.harmony }), lab.view, lab.actions);
    assert.deepEqual(clicksOf(byData(full(), 'part', 'main-choice')[0]).map((b) => b.props.data.main),
      ['auto', 'tonnetz', 'pads', 'neck']);
    assert.equal(byClass(full(), 'neck').length, 1);
    const flip = clicks(full(), 'left-handed')[0];
    assert.equal(flip.props['aria-pressed'], 'false');
    flip.props.onclick();
    assert.equal(store.get(FLIP_KEY), 'on');
    assert.ok(hasClass(byClass(full(), 'neck')[0], 'flipped'));
    assert.equal(createLab({ api: fakeApi() }).view.leftHanded, true);    // a new page remembers it
    clicksOf(byData(full(), 'part', 'main-choice')[0]).find((b) => b.props.data.main === 'neck').props.onclick();
    assert.equal(store.get(MAIN_KEY), 'neck');
    // a Tonnetz layout: no Neck choice, no flip, and the remembered Neck reads as Auto
    const tonnetz = full(FIXTURE.lab);
    assert.equal(byClass(tonnetz, 'lattice').length, 1);
    assert.equal(clicks(tonnetz, 'left-handed').length, 0);
    assert.equal(byData(tonnetz, 'main', 'auto').find((n) => n.tag === 'button').props['aria-pressed'], 'true');
  } finally {
    globalThis.localStorage = saved;
  }
  assert.equal(rememberedFlip({ getItem: () => { throw new Error('denied'); } }), false);
  assert.equal(rememberedFlip(undefined), false);
});

// --- after the guitar live test (2026-10-27) -----------------------------------------------------------------
test('the trail has a Clear button that empties it through the API, and says what it holds', async () => {
  const { api, view, actions } = await loaded();
  const harmony = { ...FIXTURE.harmony, trail: ['C', 'Am', 'Dsus4'] };
  const section = harmonySectionView(model({ lab: FIXTURE.lab, harmony }), view, actions);
  const clear = clicks(section, 'clear-trail')[0];
  assert.ok(clear && !clear.props.disabled);
  await clear.props.onclick();
  assert.deepEqual(api.calls, [['POST', '/api/lab/harmony/trail/clear', {}]]);
  const row = byClass(section, 'trail-row')[0];
  assert.match(row.props.title, /last 8 chords/);
  const empty = harmonySectionView(model({ lab: FIXTURE.lab, harmony: { ...harmony, trail: [] } }), view, actions);
  assert.ok(clicks(empty, 'clear-trail')[0].props.disabled);
  assert.match(textOf(byClass(empty, 'trail-row')), /the last 8 chords you hold show here/);
  view.result = null;
  const full = harmonyFullPart({ ...model({ lab: FIXTURE.lab, harmony }), ui: { view: { name: HARMONY_VIEW } } }, view, actions);
  assert.equal(clicks(full, 'clear-trail').length, 1);   // the full view has it too
});

test('the inputs ticked follow a choice pushed from elsewhere (the ws kind inputs)', async () => {
  const { view, actions } = await loaded();
  const pushed = { kind: 'inputs', apc64: ['APC64 Custom', 'APC64 Notes'], inputs: ['Keystation 49 MIDI 1'] };
  const section = harmonySectionView(model({ lab: FIXTURE.lab, harmony: FIXTURE.harmony, inputs: pushed }), view, actions);
  const box = findAll(section, (n) => n.tag === 'input' && n.props?.data?.input === 'Keystation 49 MIDI 1')[0];
  assert.equal(box.props.checked, true);
});

test('a generated layout whose section is invalid is listed with its reason, without Activate', async () => {
  const { view, actions } = await loaded();
  const layouts = [{ layout: 'tonnetz-c', name: 'Tonnetz C', generator: 'tonnetz', valid: true },
    { layout: 'banjo', name: 'banjo', valid: false, error: 'banjo.yaml line 3, generator: no generator "banjo"; available: guitar' }];
  const status = statusView(model({ lab: { ...FIXTURE.lab, layouts } }), view, actions);
  const invalid = byData(status, 'layout', 'banjo')[0];
  assert.ok(hasClass(invalid, 'invalid') && /no generator "banjo"/.test(textOf(invalid)));
  assert.equal(clicks(invalid, 'activate').length, 0);
  assert.equal(clicks(byData(status, 'layout', 'tonnetz-c')[0], 'activate').length, 1);
});

test('a pending recovery is said once, not again as the message line', async () => {
  const { view, actions } = await loaded();
  const text = 'the last lab session did not end cleanly; slot 0 may still hold a generated layout: restore x';
  const status = statusView(model({ lab: { ...FIXTURE.lab, message: text, recovery: { backup: 'x', message: text } } }), view, actions);
  assert.equal(textOf(status).split('did not end cleanly').length - 1, 1);
});

test('after the WebSocket reconnects the panel fetches its lists again; a changed layout set refreshes them', async () => {
  const doc = new SvgDocument();
  let current = { ...model({ lab: FIXTURE.lab, harmony: FIXTURE.harmony }), connected: true };
  const listeners = [];
  const store = { get model() { return current; }, subscribe: (fn) => listeners.push(fn) };
  const api = fakeApi();
  const mounted = mountPanel(new FakeElement('section'), { store, api }, { doc, schedule: () => {} });
  await mounted.ready;
  const fetched = () => api.calls.filter(([, path]) => path === '/api/lab/library').length;
  assert.equal(fetched(), 1);
  current = { ...current, connected: false };
  listeners.forEach((fn) => fn());
  current = { ...current, connected: true };
  listeners.forEach((fn) => fn());
  await mounted.reloaded();
  assert.equal(fetched(), 2);
  current = { ...current, topics: { lab: { lab: { ...FIXTURE.lab, layouts: [{ layout: 'guitar', name: 'Guitar', valid: true }] },
    harmony: FIXTURE.harmony } } };
  listeners.forEach((fn) => fn());
  await mounted.reloaded();
  assert.equal(fetched(), 3);
});

// --- the performer (§2.10) ------------------------------------------------------------------------------------
test('the performer shows its controls and the pattern as a grid with the playing step lit', async () => {
  const { view, actions } = await loaded();
  const tree = performerView(model({ performer: PERFORMER.playing }), view, actions);
  const grid = byData(tree, 'part', 'pattern-grid')[0];
  const rows = findAll(grid, (n) => n.tag === 'tr' && n.props?.data?.lane && n.props.data.lane !== 'strum');
  assert.deepEqual(rows.map((r) => textOf(findAll(r, (n) => n.tag === 'th')[0])),
    ['1 E', '2 B', '3 G', '4 D', '5 A', '6 E', 'R root', 'A alt bass']);
  assert.deepEqual(findAll(rows[0], (n) => n.tag === 'td').map((c) => c.props.data.cell), ['.', 'x', 'x', '.', 'x', 'x']);
  assert.ok(findAll(grid, (n) => hasClass(n, 'bar')).length > 0);                 // 3/4 in 1/4: a bar line at step 4
  assert.equal(findAll(grid, (n) => hasClass(n, 'now')).length, 0);              // the playhead is not drawn …
  const doc = new FakeDocument();
  const drawn = doc.createElement('div');
  mount(drawn, tree, doc);
  markPlayhead(drawn, PERFORMER.playing);                                          // … but marked on the drawn cells
  const lit = drawn.all((e) => e.classList.contains('now'));
  assert.ok(lit.length > 0 && lit.every((e) => e.dataset.step === '1' && !e.classList.contains('bar')));
  assert.match(textOf(byData(tree, 'part', 'performer-status')[0]), /playing · step 2\/6 · a lane per string · Play: latch/);
  assert.match(textOf(findAll(grid, (n) => n.tag === 'tr' && hasClass(n, 'strum'))[0]), /↓/);
  const idle = performerView(model({ performer: PERFORMER.idle }), view, actions);
  assert.match(textOf(idle), /Activate a generated layout to play a pattern over what you hold/);
});

test('each performer control sends its change, and Stop stops', async () => {
  const { api, view, actions } = await loaded({ 'POST /api/lab/performer': (body) => ({ ok: true, status: 200,
    data: { ...PERFORMER.playing, message: 'done' } }) });
  view.ports = [{ name: 'MPC Live III MIDI 1', direction: 'both', present: true }];
  const tree = performerView(model({ performer: PERFORMER.playing }), view, actions);
  clicks(tree, 'performer-on')[0].props.onclick();
  clicks(tree, 'performer-latch')[0].props.onclick();
  byData(tree, 'field', 'performer-pattern')[0].props.onchange({ target: { value: 'travis' } });
  byData(tree, 'field', 'performer-play')[0].props.onchange({ target: { value: '' } });
  byData(tree, 'field', 'performer-bpm')[0].props.oninput({ target: { value: '90' } });
  byData(tree, 'field', 'performer-bpm')[0].props.onkeydown({ key: 'Enter' });       // no Set button: Enter applies
  assert.equal(clicks(tree, 'performer-bpm').length, 0);
  byData(tree, 'field', 'performer-clock')[0].props.onchange({ target: { value: 'MPC Live III MIDI 1' } });
  clicks(tree, 'performer-stop')[0].props.onclick();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(api.calls, [
    ['POST', '/api/lab/performer', { enabled: false }], ['POST', '/api/lab/performer', { latch: true }],
    ['POST', '/api/lab/performer', { pattern: 'travis' }], ['POST', '/api/lab/performer', { play: null }],
    ['POST', '/api/lab/performer', { bpm: 90 }], ['POST', '/api/lab/performer', { clock: 'MPC Live III MIDI 1' }],
    ['POST', '/api/lab/performer/stop', {}]]);
});

test('the tempo applies as it changes: once after a pause in typing, at once on leaving it; a refusal is shown', async () => {
  const pending = [];
  const timers = { set: (fn) => { pending.push(fn); return pending.length; }, clear: (id) => { if (id) pending[id - 1] = null; } };
  const api = fakeApi({ 'POST /api/lab/performer': (body) => (body.bpm >= 20 && body.bpm <= 300
    ? { ok: true, status: 200, data: { ...PERFORMER.playing, tempo: { ...PERFORMER.playing.tempo, bpm: body.bpm },
      message: `tempo ${body.bpm} BPM` } }
    : refused(400, `'${body.bpm}' is not a tempo; write a BPM 20–300 (quarter notes a minute)`)) });
  const lab = createLab({ api, timers });
  const field = () => byData(performerView(model({ performer: PERFORMER.playing }), lab.view, lab.actions), 'field',
    'performer-bpm')[0];
  field().props.oninput({ target: { value: '1' } });
  field().props.oninput({ target: { value: '12' } });
  field().props.oninput({ target: { value: '120' } });                             // typing (or the arrows)
  assert.equal(api.calls.length, 0);
  await Promise.all(pending.filter(Boolean).map((fn) => fn()));                    // the pause: one change
  assert.deepEqual(api.calls, [['POST', '/api/lab/performer', { bpm: 120 }]]);
  assert.equal(lab.view.bpm, null);
  field().props.oninput({ target: { value: '400' } });
  await field().props.onchange();                                                  // leaving the field: at once
  assert.deepEqual(api.calls.at(-1), ['POST', '/api/lab/performer', { bpm: 400 }]);
  assert.equal(lab.view.result.text, "'400' is not a tempo; write a BPM 20–300 (quarter notes a minute)");
  assert.equal(lab.view.bpm, '400');                                               // not applied: still shown as typed
  const clocked = { ...PERFORMER.playing, tempo: { source: 'clock', bpm: 98, clock: 'auto', measured: 98.04,
    following: 'MPC Live III MIDI 1', stopped: false, heard: ['MPC Live III MIDI 1'] } };
  const tree = performerView(model({ performer: clocked }), lab.view, lab.actions);
  const bpm = byData(tree, 'field', 'performer-bpm')[0];
  assert.equal(bpm.props.disabled, true);
  assert.equal(bpm.props.value, '98');
  assert.equal(textOf(byData(tree, 'part', 'performer-clock-status')[0]), 'following MPC Live III MIDI 1: 98.0 BPM');
});

test('the clock says plainly what it is doing', () => {
  const base = { source: 'clock', bpm: 98, measured: null, stopped: false, heard: [] };
  assert.equal(clockStatus({ ...base, clock: 'MPC Live III MIDI 1', following: 'MPC Live III MIDI 1' }),
    'no clock heard from MPC Live III MIDI 1 yet — the MPC sends its clock while its sequencer plays, to the outputs '
    + 'its sync settings send clock to');
  assert.match(clockStatus({ ...base, clock: 'auto', following: null }), /^no clock heard from any input yet/);
  assert.equal(clockStatus({ ...base, clock: 'auto', following: 'MPC Live III MIDI 1', stopped: true,
    heard: ['MPC Live III MIDI 2'] }), 'the clock stopped; keeping 98.0 BPM · a clock was heard lately from MPC Live III MIDI 2');
});

test('the performer\'s "?" opens its topic, and its state comes from the topic first', async () => {
  const opened = [];
  const lab = createLab({ api: fakeApi(), help: (t) => opened.push(t) });
  await lab.actions.load();
  assert.deepEqual(lab.view.performer, PERFORMER.idle);                            // fetched at load
  const tree = performerView(model({ performer: PERFORMER.playing }), lab.view, lab.actions);
  findAll(tree, (n) => n.tag === 'button' && hasClass(n, 'help-btn'))[0].props.onclick();
  assert.deepEqual(opened, [PERFORMER_HELP]);
  assert.deepEqual(PERFORMER_HELP.items.filter(Array.isArray).map(([term]) => term),
    ['What it does', 'Strings and lanes', 'Play', 'Latch, Stop', 'Tempo', 'Key', 'Chord types', 'Slots', 'R and A', 'Editing']);
});
