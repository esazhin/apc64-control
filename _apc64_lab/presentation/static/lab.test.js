// The lab panel (T37; s25, s26, s27; A7, A13, A16, A21, A37, A62, A64, A67, A81): it renders the recorded snapshot
// pair (lab.fixture.json, produced by the real services), each control dispatches its API call (a fetch double),
// and a refusal's message is shown verbatim.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { FakeDocument, FakeElement } from '../../../_apc64_host/presentation/static/fake_dom.js';
import { helpButton as hostHelpButton } from '../../../_apc64_host/presentation/static/help.js';
import {
  HARMONY_HELP, LAB_HELP, SLOTS, UNIT_HINT, changedGlobals, createLab, globalsView, harmonySectionView, helpButton,
  labApi, memoryView, mountPanel, resultView, statusView,
} from './lab.js';
import { byClass, byData, findAll, hasClass, textOf } from './lab_dom.js';

const FIXTURE = JSON.parse(readFileSync(new URL('./lab.fixture.json', import.meta.url)));
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
        'GET /api/lab/globals': FIXTURE.globals,
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
  assert.deepEqual(findAll(status, (n) => n.props?.data?.scheme).map((n) => n.props.data.scheme), ['fifths', 'root-highlight']);
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
  const library = [...FIXTURE.library, { name: 'Tonnetz C copy', kind: 'definition', layout: 'tonnetz-c-copy', generator: 'tonnetz' }];
  const { api, view, actions } = await loaded({ 'GET /api/lab/library': { ok: true, status: 200, data: library } });
  const status = statusView(model({ lab: FIXTURE.lab }), view, actions);
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
  assert.deepEqual(terms, ['Generated layouts', 'Window', 'base, scheme', 'Leave', 'Project memory']);
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
