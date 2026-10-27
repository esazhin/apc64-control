// The replica (T35): every control labelled or visibly empty, Shift preview, LEDs, strips, OLED, played notes,
// and gestures → handlers. Uses the real surface catalog (surface.fixture.json, kept equal to /api/surface).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { FakeDocument } from './fake_dom.js';
import {
  FIXTURES, PANEL, SILK, shortLabel, buildReplica, controlView, groupSurface, inkFor, ledMix, placeOf, playedPads,
  playedView, silkPlace, splitLabel, stripValue, stripView, viewCaption,
} from './replica.js';
import { initialModel, reduce } from './state.js';
import { snapshot } from './page_fixtures.js';
import { textOf } from './dom.js';

const surface = JSON.parse(readFileSync(new URL('./surface.fixture.json', import.meta.url)));
const entry = (id) => surface.controls.find((c) => c.id === id);

function modelWith(overrides = {}, ui = {}) {
  let model = reduce(initialModel(), { type: 'snapshot', data: snapshot(overrides) });
  for (const [type, value] of Object.entries(ui)) model = reduce(model, value);
  return model;
}

function withControls(extra) {
  return { controls: { ...snapshot().controls, ...extra } };
}

test('the surface groups into the whole unit: 64 pads top row first, 8 scenes, tracks, strips, banks, buttons', () => {
  const g = groupSurface(surface);
  assert.equal(g.rows.length, 8);
  assert.equal(g.rows[0][0].id, 'pad r8c1');          // top-left as you look at the unit
  assert.equal(g.rows[7][0].id, 'pad r1c1');          // bottom-left (A69)
  assert.equal(g.scenes.length, 8);
  assert.equal(g.tracks.length, 8);
  assert.equal(g.trackctls.length, 8);
  assert.equal(g.strips.length, 8);
  assert.equal(g.strips[2].touch.id, 'strip 3 touch');
  assert.deepEqual(g.stripmodes.map((c) => c.display), ['Device', 'Volume', 'Pan', 'Sends', 'Channel', 'Off']);
  assert.equal(g.views.length, 6);
  assert.equal(g.shift.id, 'shift');
  const rowIds = g.buttonRows.map((row) => row.map((c) => c.id));
  assert.deepEqual(rowIds[0], ['tempo', 'clear', 'duplicate', 'quantize', 'fixed', 'undo']);
  assert.ok(rowIds.flat().includes('play') && rowIds.flat().includes('clipstop'));
  const placed = new Set([...g.rows.flat(), ...g.scenes, ...g.tracks, ...g.trackctls, ...g.strips,
    ...g.strips.map((s) => s.touch), ...g.stripmodes, ...g.views, g.encoder, g.encoderPress, g.shift,
    ...g.buttonRows.flat()].map((c) => c.id));
  assert.equal(placed.size, surface.controls.length);   // nothing of the unit is left out
});

test('every control shows its current label or is visibly empty (inv1, inv2)', () => {
  const model = modelWith();
  const bound = controlView(entry('pad r1c1'), model);
  assert.equal(bound.main, 'Note 36');
  assert.equal(bound.sub, 'mpc');
  assert.ok(!bound.classes.includes('empty'));
  assert.match(bound.title, /Pad r1c1: Note 36 → mpc\nShift: Note 48 → mpc/);
  const empty = controlView(entry('pad r8c8'), model);
  assert.equal(empty.main, '—');
  assert.ok(empty.classes.includes('empty'));
  const unknown = controlView(entry('track 5'), model);     // not in the state: still drawn, empty
  assert.ok(unknown.classes.includes('empty'));
});

test('holding Shift swaps every label to its Shift meaning (A88) and empty Shift slots stay empty (A87)', () => {
  const model = modelWith(withControls({ 'track 2': { label_base: 'CC21 → mpc', label_shift: '', empty: false,
    missing: [], toggle: null, led: null, bar: null, role: 'bindable' } }), { a: { type: 'preview_shift', held: true } });
  assert.equal(controlView(entry('pad r1c1'), model).main, 'Note 48');
  const track2 = controlView(entry('track 2'), model);
  assert.equal(track2.main, '—');
  assert.ok(track2.classes.includes('empty'));
  assert.ok(controlView(entry('shift'), model).classes.includes('held'));
});

test('a missing device is marked and its sends will say why (A83)', () => {
  const model = modelWith(withControls({ 'pad r1c1': { ...snapshot().controls['pad r1c1'],
    label_base: 'Note 36 → mpc (missing)', missing: ['mpc'] } }));
  const v = controlView(entry('pad r1c1'), model);
  assert.equal(v.sub, 'mpc (missing)');
  assert.ok(v.classes.includes('missing'));
});

test('scene and strip-mode buttons show pages and banks: current, defined, empty; printed names with bank names (A66, A89)', () => {
  const model = modelWith();
  const scene1 = controlView(entry('scene 1'), model);
  assert.equal(scene1.main, 'Drums');
  assert.ok(scene1.classes.includes('current'));
  const scene5 = controlView(entry('scene 5'), model);
  assert.ok(scene5.classes.includes('undefined'));
  assert.equal(scene5.title, 'Page 5 is empty');
  const bank1 = controlView(entry('stripmode 1'), model);
  assert.equal(bank1.main, 'Device');
  assert.equal(bank1.sub, 'Mix');
  assert.equal(controlView(entry('stripmode 5'), model).sub, '—');
  const view = controlView(entry('view session'), model);
  assert.ok(view.classes.includes('unit-own') && view.classes.includes('current-view'));   // A65
});

test('LED colour, brightness and readable ink', () => {
  assert.equal(ledMix({ brightness: 0.25, off: false }), 63);
  assert.equal(ledMix({ brightness: 1, off: false }), 100);
  assert.equal(ledMix({ brightness: 0, off: true }), 0);
  assert.equal(inkFor('#ffff00', 100), 'ink-dark');
  assert.equal(inkFor('#0000ff', 100), 'ink-light');
  assert.equal(inkFor(null, 0), 'ink-light');
  const v = controlView(entry('pad r1c1'), modelWith());
  assert.equal(v.rgb, '#ff0000');
  assert.equal(v.mix, 63);
  assert.deepEqual(splitLabel('Kick'), { main: 'Kick', sub: '' });
  assert.deepEqual(['Note 36', 'Prog 5', 'CC20', 'Kick'].map(shortLabel), ['36', 'P5', 'CC20', 'Kick']);
});

test('strips draw their bar from the value (A92) and map a pointer height to 0–16383', () => {
  const strip = { ...entry('strip 1'), touch: entry('strip 1 touch') };
  const model = modelWith(withControls({ 'strip 1': { label_base: 'CC20 → mpc', label_shift: '', empty: false,
    missing: [], toggle: null, led: null, bar: { value: 4000, colour: 3, rgb: '#ffffff', style: 'bar', lit: true },
    role: 'bindable' } }));
  const v = stripView(strip, model);
  assert.equal(v.label, 'CC20 → mpc');
  assert.equal(v.fill.height, `${(4000 / 16383) * 100}%`);
  assert.equal(stripView({ ...entry('strip 2'), touch: entry('strip 2 touch') }, model).label, '—');
  assert.equal(stripValue(0, { top: 0, height: 100 }), 16383);
  assert.equal(stripValue(100, { top: 0, height: 100 }), 0);
  assert.equal(stripValue(50, { top: 0, height: 100 }), 8192);
  assert.equal(stripValue(-20, { top: 0, height: 100 }), 16383);
});

test('played notes: chips with their position label, and pads lit only with a calibration (A121, A122)', () => {
  const played = [{ role: 'notes', note: 53, label: 'F2 (53)', velocity: 56, aftertouch: 0, routed: true, pad: null,
    position: 'pad position unknown', text: 'F2 (53) vel 56 · pad position unknown' }];
  assert.equal(textOf(playedView(modelWith({ played }))), 'Played:F2 (53) vel 56 · pad position unknown');
  const unrouted = modelWith({ played, routing: { notes: null, custom: null, status: 'expressive pads not routed in this layout' } });
  assert.match(textOf(playedView(unrouted)), /^expressive pads not routed in this layout/);   // A115
});

test('the built replica updates in place and turns gestures into handler calls', () => {
  const doc = new FakeDocument();
  const container = doc.createElement('div');
  const calls = [];
  const handlers = {
    down: (id) => calls.push(['down', id]), up: (id) => calls.push(['up', id]), shift: (held) => calls.push(['shift', held]),
    stripDown: (id, v) => calls.push(['stripDown', id, v]), stripMove: (id, v) => calls.push(['stripMove', id, v]),
    stripUp: (id) => calls.push(['stripUp', id]), turn: (steps) => calls.push(['turn', steps]),
    select: (id) => calls.push(['select', id]),
  };
  const replica = buildReplica(container, surface, handlers, doc);
  let model = modelWith({ played: [{ note: 36, velocity: 100, pad: 'pad r1c1', text: 'C1 (36) vel 100', routed: true }],
    calibration_label: 'calibrated 14:02 (assumed)' });
  replica.update(model);
  const pad = replica.controls.get('pad r1c1');
  assert.equal(pad.children[1].textContent, 'Note 36');
  assert.ok(pad.classList.contains('played'));
  assert.ok(pad.classList.contains('pad') && pad.classList.contains('ctl'));      // its kind survives updates
  assert.ok(replica.controls.get('scene 1').classList.contains('scene'));
  assert.equal(pad.style.getPropertyValue('--led'), '#ff0000');
  assert.equal(replica.controls.get('pad r8c8').children[1].textContent, '—');
  assert.match(container.textContent, /Pad positions: calibrated 14:02 \(assumed\)/);   // inv9
  assert.match(container.textContent, /Jam\nP1 Drums \| B1/);                          // the OLED
  // press and release a pad (A70); the same element keeps its listeners across updates
  pad.dispatch('pointerdown');
  assert.ok(pad.classList.contains('pressed'));
  model = reduce(model, { type: 'diff', data: { changed: { page: { n: 2 } }, controls: {} } });
  replica.update(model);
  pad.dispatch('pointerup');
  assert.ok(!pad.classList.contains('pressed'));
  // Shift on the replica holds the page Shift; the unit's own view buttons only select
  replica.controls.get('shift').dispatch('pointerdown');
  replica.controls.get('shift').dispatch('pointerup');
  replica.controls.get('view note').dispatch('click');
  // drag strip 3
  const track = replica.controls.get('strip 3').children[1];
  track.dispatch('pointerdown', { clientY: 0 });
  track.dispatch('pointermove', { clientY: 80 });
  track.dispatch('pointerup');
  track.dispatch('pointermove', { clientY: 10 });                                 // after release: nothing
  // the encoder
  const turns = container.all((e) => e.dataset.turn !== undefined);
  turns.forEach((b) => b.dispatch('click'));
  replica.controls.get('encoder press').dispatch('pointerdown');
  replica.controls.get('encoder press').dispatch('pointerup');
  assert.deepEqual(calls, [
    ['down', 'pad r1c1'], ['up', 'pad r1c1'], ['shift', true], ['shift', false], ['select', 'view note'],
    ['stripDown', 'strip 3', 16383], ['stripMove', 'strip 3', 8192], ['stripUp', 'strip 3'],
    ['turn', -1], ['turn', 1], ['down', 'encoder press'], ['up', 'encoder press'],
  ]);
});

test('every control has its place on the panel as on the unit (user guide §3.1), inside it, none overlapping', () => {
  const shared = new Set(['encoder', 'encoder press']);          // in the encoder's bezel
  const places = surface.controls.filter((c) => !/ touch$/.test(c.id) && !shared.has(c.id))
    .map((c) => ({ id: c.id, at: placeOf(c.id) }));
  assert.deepEqual(places.filter((p) => !p.at).map((p) => p.id), []);
  const all = [...places,
    ...Object.keys(SILK).map((id) => ({ id: `silk ${id}`, at: silkPlace(id) })),
    ...Object.entries(FIXTURES).map(([id, at]) => ({ id, at }))];
  for (const { id, at } of all) {
    assert.ok(at.x >= 0 && at.y >= 0 && at.x + at.w <= PANEL.width && at.y + at.h <= PANEL.height, `${id} inside`);
  }
  const overlaps = [];
  for (let i = 0; i < all.length; i++) {
    for (let j = i + 1; j < all.length; j++) {
      const a = all[i].at;
      const b = all[j].at;
      if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlaps.push(`${all[i].id} × ${all[j].id}`);
    }
  }
  assert.deepEqual(overlaps, []);
  // the unit's arrangement: pads square with row 1 at the bottom; strips in corner pairs; the side column
  // between the left strips and the grid; scenes right of the grid; track then control row under it
  const pad = (r, c) => placeOf(`pad r${r}c${c}`);
  assert.equal(pad(1, 1).w, pad(1, 1).h);
  assert.ok(pad(1, 1).y > pad(8, 1).y && pad(1, 8).x > pad(1, 1).x);
  assert.ok(placeOf('strip 1').y === placeOf('strip 2').y && placeOf('strip 3').y > placeOf('strip 1').y);
  assert.ok(placeOf('strip 5').x > placeOf('scene 1').x && placeOf('strip 1').x < placeOf('stripmode 1').x);
  assert.ok(placeOf('stripmode 1').x + placeOf('stripmode 1').w < pad(8, 1).x);
  const column = ['stripmode 1', 'stripmode 6', 'tempo', 'clear', 'duplicate', 'fixed', 'quantize', 'undo', 'shift',
    'recarm', 'mute', 'solo', 'clipstop'].map((id) => placeOf(id));
  assert.ok(column.every((at, i) => at.x === column[0].x && (i === 0 || at.y > column[i - 1].y)));
  assert.ok(placeOf('scene 1').x > pad(8, 8).x + pad(8, 8).w);
  assert.ok(placeOf('track 1').y > pad(1, 1).y && placeOf('trackctl 1').y > placeOf('track 1').y);
  assert.ok(['view session', 'view custom', 'play', 'stop', 'rec'].every((id) => placeOf(id).y < pad(8, 1).y));
  assert.ok(placeOf('play').x < placeOf('stop').x && placeOf('stop').x < placeOf('rec').x);
  assert.ok(placeOf('left').y > placeOf('strip 3').y + placeOf('strip 3').h);
  assert.ok(FIXTURES.oled.x < placeOf('view session').x && FIXTURES.bezel.y > placeOf('scene 8').y);
});

const inView = (view, extra = {}) => modelWith({ unit: { ...snapshot().unit, view }, ...extra });

test('outside Session view the grid is the unit\'s: no layout bindings or colours on the pads, buttons stay live', () => {
  const model = inView('chord');
  const pad = controlView(entry('pad r1c1'), model);
  assert.equal(pad.main, '');
  assert.equal(pad.mix, 0);
  assert.equal(pad.rgb, null);
  assert.ok(pad.classes.includes('by-unit'));
  assert.match(pad.title, /Chord view — the APC64 plays this pad itself/);
  const track = controlView(entry('scene 1'), model);
  assert.ok(!track.classes.includes('by-unit'));                 // Note/Chord/Step: buttons reach the host
  const strip = stripView({ ...entry('strip 1'), touch: entry('strip 1 touch') }, model);
  assert.ok(!strip.classes.includes('by-unit'));
  assert.ok(controlView(entry('view chord'), model).classes.includes('current-view'));
  assert.ok(!controlView(entry('view session'), model).classes.includes('current-view'));
  assert.equal(controlView(entry('pad r1c1'), inView('session')).main, 'Note 36');
});

test('the caption says whose pads these are and where their playing goes (routing, or not routed)', () => {
  assert.equal(viewCaption(inView('session')), null);
  const chord = viewCaption(inView('chord'));
  assert.equal(chord.title, 'Chord view — the APC64 plays these pads itself');
  assert.equal(chord.route, '→ mpc ch 2, velocity + aftertouch');
  assert.match(chord.notes, /Play the pads on the unit/);
  assert.equal(viewCaption(inView('step')).route, '→ mpc ch 2, velocity');
  const unrouted = viewCaption(inView('note', { routing: { notes: null, custom: null, status: 'expressive pads not routed in this layout' } }));
  assert.equal(unrouted.route, 'not routed: this layout has no routing for the Notes port');
  const custom = viewCaption(inView('custom'));
  assert.match(custom.route, /no routing for the Custom port/);
  assert.match(custom.extra, /only Shift and Tempo reach the host/);
  assert.match(viewCaption(inView('project')).title, /Project view — the APC64 uses these pads itself/);
  // without a usable calibration the sounding notes are listed; Note view with one lights the pads instead
  const played = [{ role: 'notes', note: 60, label: 'C3 (60)', velocity: 96, pad: 'pad r2c1', routed: true, text: '' },
    { role: 'notes', note: 64, label: 'E3 (64)', velocity: 90, pad: null, routed: true, text: '' }];
  assert.equal(viewCaption(inView('chord', { played })).notes, 'Playing: C3 (60) vel 96 · E3 (64) vel 90');
  assert.equal(playedPads(inView('chord', { played })).size, 0);  // a chord is not one pad
  assert.deepEqual([...playedPads(inView('note', { played })).keys()], ['pad r2c1']);
  assert.equal(viewCaption(inView('note', { played })).notes, '');
});

test('in Custom view the side buttons, strips and encoder are the unit\'s too; Shift and Tempo still reach the host', () => {
  const model = inView('custom', withControls({ 'track 1': { label_base: 'CC21 → mpc', label_shift: '', empty: false,
    missing: [], toggle: null, led: { colour: 5, rgb: '#ff0000', brightness: 1, animation: null, off: false }, bar: null,
    role: 'bindable' } }));
  const track = controlView(entry('track 1'), model);
  assert.ok(track.classes.includes('by-unit'));
  assert.equal(track.main, 'CC21');                               // the label stays, dimmed; the LED does not
  assert.equal(track.mix, 0);
  assert.match(track.title, /Custom view — this stays on the APC64/);
  for (const id of ['scene 2', 'stripmode 2', 'play', 'encoder', 'encoder press']) {
    assert.ok(controlView(entry(id), model).classes.includes('by-unit'), id);
  }
  for (const id of ['shift', 'tempo', 'view custom']) assert.ok(!controlView(entry(id), model).classes.includes('by-unit'), id);
  const strip = stripView({ ...entry('strip 1'), touch: entry('strip 1 touch') }, model);
  assert.ok(strip.classes.includes('by-unit'));
  assert.equal(strip.fill.height, '0%');
});

test('the built replica places every control and shows the unit\'s view over the grid', () => {
  const doc = new FakeDocument();
  const container = doc.createElement('div');
  const replica = buildReplica(container, surface, {}, doc);
  const pad = replica.controls.get('pad r8c1');
  assert.equal(pad.style.getPropertyValue('--x'), '3.75');       // top-left pad: the grid's corner
  assert.equal(pad.style.getPropertyValue('--y'), '1.27');
  assert.ok(replica.controls.get('shift').classList.contains('sidebtn'));
  assert.match(container.textContent, /OVERVIEW.*SWING|SWING.*OVERVIEW/s);  // the unit's printing
  const caption = container.all((e) => e.dataset.caption === 'box')[0];
  replica.update(inView('session'));
  assert.ok(!caption.classList.contains('shown'));
  replica.update(inView('chord'));
  assert.ok(caption.classList.contains('shown'));
  assert.match(caption.textContent, /Chord view — the APC64 plays these pads itself\n→ mpc ch 2, velocity \+ aftertouch/);
  const r1c1 = replica.controls.get('pad r1c1');
  assert.equal(r1c1.children[1].textContent, '');
  assert.ok(r1c1.classList.contains('by-unit') && r1c1.classList.contains('pad'));
  assert.equal(r1c1.style.getPropertyValue('--mix'), '0%');
  replica.update(inView('session'));
  assert.equal(r1c1.children[1].textContent, 'Note 36');
  assert.ok(!r1c1.classList.contains('by-unit'));
});
