// Live session 2026-10-26: the "?" help overlays, and the one line under the toolbar saying what a click does.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createHandlers } from './app.js';
import { byClass, byData, findAll, hasClass, textOf } from './dom.js';
import { LAYOUT_HELP, MODE_HINTS, TOOLBAR_HELP, helpButton, helpView, modeHint } from './help.js';
import { toolbarLine, toolbarView } from './learn.js';
import { navView } from './nav.js';
import { snapshot } from './page_fixtures.js';
import { createStore, initialModel, reduce } from './state.js';

const TOPIC = { id: 't', title: 'A topic', items: [['Term', 'what it is'], 'a plain line'], more: 'and more' };
const model0 = (overrides) => reduce(initialModel(), { type: 'snapshot', data: snapshot(overrides) });
const helpButtons = (tree) => findAll(tree, (n) => n.tag === 'button' && hasClass(n, 'help-btn'));

function recordingApi() {
  const calls = [];
  const api = new Proxy({}, { get: (_, name) => async (...args) => { calls.push([name, ...args]); return { ok: true, status: 200, data: {} }; } });
  return { api, calls };
}

test('a "?" opens its topic in the one overlay; × and a click outside close it, nothing else changes', () => {
  const store = createStore(model0());
  const handlers = createHandlers(recordingApi().api, store);
  assert.deepEqual(helpView(store.model, handlers), []);                       // closed: nothing drawn
  const button = helpButton(TOPIC, handlers);
  assert.equal(textOf(button), '?');
  assert.equal(button.props['aria-label'], 'Help: A topic');
  button.props.onclick();
  assert.equal(store.model.ui.help, TOPIC);
  const shown = helpView(store.model, handlers);
  assert.equal(textOf(byClass(shown, 'help-card')[0].children[0]), 'A topic×');
  assert.deepEqual(findAll(shown, (n) => n.tag === 'dt').map(textOf), ['Term']);
  assert.deepEqual(findAll(shown, (n) => n.tag === 'dd').map(textOf), ['what it is', 'a plain line']);
  assert.equal(textOf(byClass(shown, 'help-more')[0]), 'and more');
  assert.equal(byClass(shown, 'help-card')[0].props.role, 'dialog');
  byData(shown, 'help', 'backdrop')[0].props.onclick();                      // a click outside the card
  assert.equal(store.model.ui.help, null);
  handlers.help(TOPIC);
  byData(helpView(store.model, handlers), 'help', 'close')[0].props.onclick();
  assert.equal(store.model.ui.help, null);
  assert.equal(reduce(store.model, { type: 'help', topic: {} }), store.model);   // a topic needs a title
  assert.equal(reduce(store.model, { type: 'help_close' }), store.model);
  handlers.help(TOPIC);
  handlers.dismiss();                                                          // dismissing a notice keeps help open
  assert.equal(store.model.ui.help, TOPIC);
});

test('the layout bar has a "?" for layouts, pages and strip banks, open or folded', () => {
  const opened = [];
  const handlers = { help: (topic) => opened.push(topic.id) };
  const model = model0();
  helpButtons(navView(model, handlers)).forEach((b) => b.props.onclick());
  helpButtons(navView(reduce(model, { type: 'nav_collapsed', collapsed: true }), handlers)).forEach((b) => b.props.onclick());
  assert.deepEqual(opened, ['layout', 'layout']);
  const text = LAYOUT_HELP.items.flat().join(' ');
  assert.match(text, /8 scene buttons/);
  assert.match(text, /6 strip-mode buttons \(Device, Volume, Pan, Sends, Channel, Off/);
  assert.match(text, /Shift and turn the encoder/);
});

test('the toolbar has a "?" for Play, Inspect, Learn by touch and Calibrate Note view', () => {
  const opened = [];
  const tree = toolbarView(model0(), { help: (topic) => opened.push(topic) });
  helpButtons(tree).forEach((b) => b.props.onclick());
  assert.deepEqual(opened, [TOOLBAR_HELP]);
  assert.deepEqual(TOOLBAR_HELP.items.map(([term]) => term),
    ['Play', 'Inspect', 'Learn by touch', 'Calibrate Note view', 'Beside the surface']);
});

test('the line under the toolbar says what a click does in each mode, and the buttons say it too', () => {
  const play = model0();
  const inspect = reduce(play, { type: 'mode', mode: 'inspect' });
  const lineOf = (model) => byClass(toolbarView(model, {}), 'toolbar-line');
  assert.equal(lineOf(play).length, 1);
  assert.equal(textOf(lineOf(play)[0]), MODE_HINTS.play);
  assert.equal(textOf(lineOf(inspect)[0]), MODE_HINTS.inspect);
  assert.match(modeHint('play'), /presses that control as if on the unit; its MIDI goes out/);
  assert.match(modeHint('inspect'), /opens that control's card; nothing is sent/);
  const [playButton, inspectButton] = findAll(toolbarView(play, {}), (n) => n.tag === 'button').slice(0, 2);
  assert.match(playButton.props.title, /^Play: .*MIDI goes out/);
  assert.match(inspectButton.props.title, /^Inspect: .*nothing is sent/);
});

test('the hints say what createHandlers does: Play presses, Inspect only selects', async () => {
  const { api, calls } = recordingApi();
  const store = createStore(model0());
  const h = createHandlers(api, store);
  await h.down('pad r1c1');
  await h.up('pad r1c1');
  h.mode('inspect');
  await h.down('pad r1c2');
  await h.up('pad r1c2');
  await h.flush();
  assert.deepEqual(calls.filter(([name]) => name === 'press' || name === 'unpress'),
    [['press', 'pad r1c1'], ['unpress', 'pad r1c1']]);
  assert.equal(store.model.ui.selected, 'pad r1c2');
});

test('a running calibration or learn takes the same one line; the toolbar never grows a second', () => {
  const calibrating = model0({ calibration_step: 'waiting for bottom-left' });
  const tree = toolbarView(calibrating, {});
  const lines = byClass(tree, 'toolbar-line');
  assert.equal(lines.length, 1);
  assert.equal(lines[0].props.data.line, 'status');
  assert.equal(textOf(lines[0]), 'Calibration: in Note view, press the bottom-left pad');
  const learning = model0({ learn: { mode: 'touch', selected: null, port: null, device: null, last: 'pad r1c1: Note 36 sent' } });
  const both = byClass(toolbarView(learning, {}), 'toolbar-line');
  assert.equal(both.length, 1);
  assert.equal(textOf(both[0]), 'Learn: touch a control on the unit to select it (nothing is sent) · pad r1c1: Note 36 sent');
  assert.equal(both[0].props.title, textOf(both[0]));
  const after = model0({ learn: { mode: 'off', selected: null, port: null, device: null, last: 'pad r1c1: Note 36 sent' } });
  assert.equal(textOf(byClass(toolbarView(after, {}), 'toolbar-line')[0]), `${MODE_HINTS.play} · pad r1c1: Note 36 sent`);
  assert.equal(findAll(tree, (n) => n.props?.style?.flexBasis).length, 0);     // no extra status rows
  assert.equal(textOf(toolbarLine('inspect', [])), MODE_HINTS.inspect);
});
