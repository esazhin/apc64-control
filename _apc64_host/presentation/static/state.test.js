// s30 collaboration: the reducer over a fake socket's snapshot, diffs, activity, a drop and a new snapshot (T34).
import test from 'node:test';
import assert from 'node:assert/strict';
import { ACTIVITY_LIMIT, createStore, initialModel, labelOf, layerOf, ownedByUnit, reduce, unitPill, unitView } from './state.js';
import { snapshot } from './page_fixtures.js';

function fakeSocket(store) {
  // what app.js does with each /ws message
  return { deliver: (message) => store.dispatch(message), drop: () => store.dispatch({ type: 'disconnected' }) };
}

test('snapshot, diffs and activity build the page model; a reconnect resets it to the new snapshot', () => {
  const store = createStore();
  const socket = fakeSocket(store);
  socket.deliver({ type: 'snapshot', data: snapshot() });
  socket.deliver({ type: 'activity_list', data: [{ id: 1, text: 'pad r1c1 → note 36 ch 10 → mpc: sent' }] });
  assert.equal(store.model.connected, true);
  socket.deliver({ type: 'diff', data: { changed: { page: { n: 2, display: 'Keys' } },
    controls: { 'pad r1c1': { ...snapshot().controls['pad r1c1'], label_base: 'Note 50 → mpc' } } } });
  assert.equal(store.model.state.page.n, 2);
  assert.equal(store.model.state.controls['pad r1c1'].label_base, 'Note 50 → mpc');
  assert.equal(store.model.state.controls['pad r8c8'].empty, true);   // untouched controls stay
  socket.deliver({ type: 'activity', data: { id: 2, text: 'track 1 → cc 20 → mpc: sent' } });
  assert.deepEqual(store.model.activity.map((r) => r.id), [2, 1]);
  // A131: the connection drops while the bank changes elsewhere; the new snapshot replaces everything
  socket.drop();
  assert.equal(store.model.connected, false);
  socket.deliver({ type: 'snapshot', data: snapshot({ bank: { n: 3, display: 'FX' } }) });
  socket.deliver({ type: 'activity_list', data: [{ id: 3, text: 'x' }] });
  assert.equal(store.model.connected, true);
  assert.equal(store.model.state.bank.n, 3);
  assert.equal(store.model.state.page.n, 1);
  assert.deepEqual(store.model.activity.map((r) => r.id), [3]);
});

test('a folded aftertouch updates its entry in place; the list keeps the newest 200', () => {
  let model = reduce(initialModel(), { type: 'snapshot', data: snapshot() });
  model = reduce(model, { type: 'activity', data: { id: 7, text: 'F2 (53) → note 53 → mpc: sent' } });
  model = reduce(model, { type: 'activity', data: { id: 8, text: 'pad r1c1' } });
  model = reduce(model, { type: 'activity', data: { id: 7, folded: true, aftertouch: 40, text: 'F2 … (aftertouch 40)' } });
  assert.deepEqual(model.activity.map((r) => r.id), [8, 7]);
  assert.equal(model.activity[1].aftertouch, 40);
  for (let i = 100; i < 600; i += 1) model = reduce(model, { type: 'activity', data: { id: i } });
  assert.equal(model.activity.length, ACTIVITY_LIMIT);
  assert.equal(model.activity[0].id, 599);
});

test('the Shift preview swaps every label to its Shift meaning; empty stays empty', () => {
  let model = reduce(initialModel(), { type: 'snapshot', data: snapshot() });
  assert.equal(layerOf(model), 'base');
  assert.equal(labelOf(model, 'pad r1c1'), 'Note 36 → mpc');
  model = reduce(model, { type: 'preview_shift', held: true });
  assert.equal(layerOf(model), 'shift');
  assert.equal(labelOf(model, 'pad r1c1'), 'Note 48 → mpc');
  assert.equal(labelOf(model, 'pad r8c8'), '');
  model = reduce(model, { type: 'preview_shift', held: false });
  model = reduce(model, { type: 'diff', data: { changed: { shift: true }, controls: {} } });   // Shift on the unit
  assert.equal(labelOf(model, 'pad r1c1'), 'Note 48 → mpc');
});

test('learn by touch selects the touched control and opens its card', () => {
  let model = reduce(initialModel(), { type: 'snapshot', data: snapshot() });
  model = reduce(model, { type: 'diff', data: { changed: { learn: { mode: 'touch', selected: 'track 3' } }, controls: {} } });
  assert.equal(model.ui.selected, 'track 3');
  model = reduce(model, { type: 'select', id: 'pad r1c1' });
  model = reduce(model, { type: 'diff', data: { changed: { page: { n: 2 } }, controls: {} } });
  assert.equal(model.ui.selected, 'pad r1c1');   // an unrelated diff does not steal the selection
});

test('page actions: selection, card, problems and modes', () => {
  let model = reduce(initialModel(), { type: 'select', id: 'pad r1c1' });
  model = reduce(model, { type: 'card', id: 'pad r1c1', data: { base: 'Note 36 → mpc ch 10, momentary' } });
  assert.equal(model.ui.card.base, 'Note 36 → mpc ch 10, momentary');
  model = reduce(model, { type: 'card', id: 'track 1', data: {} });                // a late answer for another control
  assert.equal(model.ui.card.base, 'Note 36 → mpc ch 10, momentary');
  model = reduce(model, { type: 'problem', problem: 'already held' });
  assert.equal(model.ui.problem, 'already held');
  model = reduce(model, { type: 'notice', text: 'Saved' });
  assert.equal(model.ui.problem, null);
  model = reduce(model, { type: 'mode', mode: 'inspect' });
  assert.equal(model.ui.mode, 'inspect');
  assert.equal(reduce(model, { type: 'unknown' }), model);
});

test('the unit pill says Held, or Not held with the reason', () => {
  assert.deepEqual(unitPill(snapshot()), { text: 'Held', detail: '', tone: 'ok' });
  const busy = snapshot({ unit: { ...snapshot().unit, status: 'busy', held: false, text: 'Busy: held by Bitwig Studio' } });
  assert.deepEqual(unitPill(busy), { text: 'Not held', detail: 'Busy: held by Bitwig Studio', tone: 'warn' });
  const declined = snapshot({ unit: { ...snapshot().unit, status: 'declined', held: false, text: 'Not held' } });
  assert.deepEqual(unitPill(declined), { text: 'Not held', detail: '', tone: 'muted' });
  assert.equal(unitPill(null).text, 'Connecting…');
});

test('the unit\'s view decides what the page may press: the grid outside Session, almost all in Custom', () => {
  const inView = (view) => reduce(initialModel(), { type: 'snapshot', data: snapshot({ unit: { ...snapshot().unit, view } }) });
  assert.equal(unitView(initialModel()), 'session');
  assert.equal(ownedByUnit(inView('session'), 'pad r1c1'), false);
  for (const view of ['note', 'chord', 'step', 'project', 'custom']) assert.equal(ownedByUnit(inView(view), 'pad r4c4'), true, view);
  assert.equal(ownedByUnit(inView('note'), 'strip 1'), false);
  assert.equal(ownedByUnit(inView('custom'), 'strip 1'), true);
  assert.equal(ownedByUnit(inView('custom'), 'scene 3'), true);
  assert.equal(ownedByUnit(inView('custom'), 'shift'), false);
  assert.equal(ownedByUnit(inView('custom'), 'tempo'), false);    // note 72 still reaches the host
});

test('the folded bar and the hidden column are page state', () => {
  let model = initialModel();
  assert.equal(model.ui.navCollapsed, false);
  model = reduce(model, { type: 'nav_collapsed', collapsed: true });
  assert.equal(model.ui.side, 'overview');
  model = reduce(model, { type: 'side', panel: 'card' });
  assert.deepEqual([model.ui.navCollapsed, model.ui.side], [true, 'card']);
  assert.equal(reduce(model, { type: 'side', panel: 'bogus' }).ui.side, 'overview');
});
