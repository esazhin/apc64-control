// The harmony views (T37; inv15, inv16, inv17; A21, A68, A71–A77, A80), rendered from the recorded snapshot pair
// (lab.fixture.json: 'Tonnetz C' active, C3 E3 G3 held — 48 52 55) and from hand-made HarmonyState JSON.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  HINT_ROWS, NOTE_NAMES, chordView, circleView, latticeModel, latticeView, nearestTriangle, padReplicaView,
  placeHarmony,
} from './harmony_views.js';
import { byClass, byData, findAll, hasClass, textOf } from './lab_dom.js';

const FIXTURE = JSON.parse(readFileSync(new URL('./lab.fixture.json', import.meta.url)));
const C_MAJOR = FIXTURE.harmony;
const PADS = FIXTURE.lab.active.pads;
const triad = (root, quality) => ({ root, quality, label: NOTE_NAMES[root] + (quality === 'minor' ? 'm' : '') });
const held = (...notes) => notes.map((note) => ({ note, name: String(note), pc: note % 12 }));
const EMPTY = { kind: 'harmony', held: [], chord: '—', triads: [], degrees: {}, hints: [], neighbours: [], trail: [],
  circle: [], trail_triads: [] };
const E_ONLY = {
  ...EMPTY, held: held(52), chord: 'E',
  degrees: Object.fromEntries(NOTE_NAMES.map((name, pc) => [name, ['1', '♭2', '2', '♭3', '3', '4', '♭5', '5', '♭6', '6', '♭7', '7'][(pc - 4 + 12) % 12]])),
  hints: [triad(0, 'major'), triad(4, 'minor'), triad(4, 'major'), triad(1, 'minor'), triad(9, 'major'), triad(9, 'minor')],
  circle: ['E'],
};

const lit = (tree) => findAll(tree, (n) => n.tag === 'polygon' && hasClass(n, 'lit'));

test('C E G held: the chord is C, one C major triangle is lit and its neighbours are marked (A68, A73, A76)', () => {
  assert.equal(C_MAJOR.chord, 'C');
  const chord = chordView(C_MAJOR);
  assert.equal(textOf(byClass(chord, 'chord')[0]), 'C');
  assert.match(textOf(byData(chord, 'hint', 'neighbours')[0]), /Cm, Am, Em$/);
  const lattice = latticeView(C_MAJOR);
  assert.deepEqual(lit(lattice).map((t) => t.props.data.triad), ['0:major']);
  const neighbours = findAll(lattice, (n) => n.tag === 'polygon' && hasClass(n, 'neighbour'));
  assert.deepEqual(neighbours.map((t) => t.props.data.triad).sort(), ['0:minor', '4:minor', '9:minor']);
  const heldNodes = new Set(byClass(lattice, 'held').map((n) => n.props.data.pc));
  assert.deepEqual([...heldNodes].sort((a, b) => a - b), [0, 4, 7]);
});

test('the neighbours share an edge with the lit triangle on the lattice', () => {
  const model = latticeModel();
  const placed = placeHarmony(model, C_MAJOR);
  const edge = (a, b) => a.cells.filter(([i, j]) => b.cells.some(([x, y]) => x === i && y === j)).length;
  assert.equal(placed.lit.length, 1);
  for (const n of placed.neighbours) assert.equal(edge(placed.lit[0], n), 2);
});

test('nothing held: the chord is — and no triangle is lit (A71)', () => {
  assert.equal(textOf(byClass(chordView(EMPTY), 'chord')[0]), '—');
  assert.equal(lit(latticeView(EMPTY)).length, 0);
  assert.equal(findAll(circleView(EMPTY), (n) => n.tag === 'polygon').length, 0);
});

test('E alone: G is labelled ♭3 and B 5, and the six triads containing E are the hints (A72)', () => {
  const lattice = latticeView(E_ONLY);
  const degreeOf = (pc) => textOf(findAll(lattice, (n) => n.props?.data?.pc === pc && hasClass(n, 'node'))[0]
    .children.find((c) => hasClass(c, 'node-degree')));
  assert.equal(degreeOf(7), '♭3');
  assert.equal(degreeOf(11), '5');
  const hints = findAll(lattice, (n) => n.tag === 'polygon' && hasClass(n, 'hint')).map((t) => t.props.data.triad);
  assert.deepEqual(hints.sort(), ['0:major', '1:minor', '4:major', '4:minor', '9:major', '9:minor']);
  const labels = byClass(lattice, 'tri-label').map(textOf).sort();
  assert.deepEqual(labels, ['A', 'Am', 'C', 'C♯m', 'E', 'Em']);
  assert.match(textOf(byData(chordView(E_ONLY), 'hint', 'intervals')[0]), /G ♭3 · .*B 5$/);
  assert.equal(textOf(byData(chordView(E_ONLY), 'hint', 'contains')[0]), 'chords with E: C, Em, E, C♯m, A, Am');
});

test('the circle of fifths joins C, G and E in circle order (A68)', () => {
  const circle = circleView(C_MAJOR);
  assert.deepEqual(C_MAJOR.circle, ['C', 'G', 'E']);
  const [joined] = findAll(circle, (n) => n.tag === 'polygon');
  assert.equal(joined.props.points.split(' ').length, 3);
  assert.deepEqual(byClass(circle, 'held').map((n) => n.props.data.pc).sort((a, b) => a - b), [0, 4, 7]);
  assert.deepEqual(findAll(circle, (n) => n.tag === 'text').map(textOf),
    ['C', 'G', 'D', 'A', 'E', 'B', 'F♯', 'C♯', 'A♭', 'E♭', 'B♭', 'F']);
});

// The Custom port reports notes, not pads, so every pad playing a held note lights: r8c2 plays G (55) as r1c3 does.
test('the pad replica shows the written RGB without an approximate mark and lights the held pads (A21, A68)', () => {
  const replica = padReplicaView(PADS, C_MAJOR);
  const r1c1 = byData(replica, 'pad', 'r1c1')[0];
  assert.equal(r1c1.props.data.rgb, '#FFFFFF');
  assert.equal(r1c1.props.style.background, '#FFFFFF');
  assert.equal(hasClass(r1c1, 'approx'), false);
  assert.equal(byClass(replica, 'approx').length, 0);
  const heldPads = byClass(replica, 'held').map((p) => p.props.data.pad).sort();
  assert.deepEqual(heldPads, ['r1c1', 'r1c3', 'r2c2', 'r8c2']);
  assert.equal(hasClass(byData(replica, 'pad', 'r1c2')[0], 'silent'), true);
  assert.equal(textOf(byClass(replica, 'legend')[0]), 'colours as written to the unit');
});

test('without a generated layout the replica shows palette colours marked approximate (inv17)', () => {
  const replica = padReplicaView(null, EMPTY, (id) => (id === 'pad r1c1' ? '#ff0000' : null));
  assert.equal(byData(replica, 'pad', 'r1c1')[0].props.data.rgb, '#ff0000');
  assert.equal(byClass(replica, 'approx').length, 64);
  assert.match(textOf(byClass(replica, 'legend')[0]), /approximate/);
});

test('two pads playing one note both light while it is held (A80)', () => {
  const pads = PADS.map((p) => ({ ...p }));
  pads.find((p) => p.pad === 'r1c3').note = 48;
  const replica = padReplicaView(pads, { ...EMPTY, held: held(48) });
  assert.deepEqual(byClass(replica, 'held').map((p) => p.props.data.pad).sort(), ['r1c1', 'r1c3']);
});

test('the trail is drawn through the trail\'s triads, each placed next to the one before (A77)', () => {
  const harmony = { ...C_MAJOR, trail: ['C', 'Am', 'F'], trail_triads: [triad(0, 'major'), triad(9, 'minor'), triad(5, 'major')] };
  const model = latticeModel();
  const placed = placeHarmony(model, harmony);
  assert.deepEqual(placed.trail.map((p) => p.label), ['C', 'Am', 'F']);
  const step = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  assert.ok(step(placed.trail[0], placed.trail[1]) < 30 && step(placed.trail[1], placed.trail[2]) < 30);
  const [line] = findAll(latticeView(harmony, model), (n) => n.tag === 'polyline');
  assert.equal(line.props.points.split(' ').length, 3);
  assert.deepEqual(byClass(chordView(harmony), 'trail-chord').map(textOf), ['C', 'Am', 'F']);
});

test('each triad has one nearest triangle, by the lattice\'s own geometry', () => {
  const model = latticeModel();
  const c = nearestTriangle(model, triad(0, 'major'));
  assert.deepEqual(c.cells, [[0, 0], [1, 0], [0, 1]]);   // C at the centre, G to the right, E up-right
  assert.equal(model.nodes.find((n) => n.i === 1 && n.j === 0).pc, 7);
  assert.equal(model.nodes.find((n) => n.i === 0 && n.j === 1).pc, 4);
});

// Live session 2026-10-26: pressing and releasing notes must not move the views (no rows come or go).
test('the chord block has the same rows whatever is held; an idle hint row says what would show in it', () => {
  const classes = (n) => [n.props.class].flat().filter((c) => c && c !== 'idle').join(' ');
  const skeleton = (tree) => findAll(tree, (n) => n.tag === 'div').map((n) => `${classes(n)}|${n.props.data?.hint ?? ''}`);
  const trail = { ...C_MAJOR, trail: ['C', 'Am', 'F', 'Dm', 'G', 'C', 'Am', 'F'] };
  const shapes = [EMPTY, E_ONLY, C_MAJOR, trail].map((harmony) => skeleton(chordView(harmony)));
  for (const shape of shapes) assert.deepEqual(shape, shapes[0]);
  assert.deepEqual(byClass(chordView(EMPTY), 'hint-line').map((n) => n.props.data.hint), HINT_ROWS.map(([key]) => key));
  const idle = byClass(chordView(EMPTY), 'idle');
  assert.deepEqual(idle.map(textOf), HINT_ROWS.map(([, text]) => text));
  assert.deepEqual(byClass(chordView(E_ONLY), 'idle').map((n) => n.props.data.hint), ['neighbours']);
  assert.deepEqual(byClass(chordView(C_MAJOR), 'idle').map((n) => n.props.data.hint), ['intervals', 'contains']);
  const intervals = byData(chordView(E_ONLY), 'hint', 'intervals')[0];
  assert.equal(intervals.props.title, textOf(intervals));                     // a cut row keeps all of it in its title
});

test('the harmony rows keep a fixed height in lab.css (no row grows with its content)', () => {
  const css = readFileSync(new URL('./lab.css', import.meta.url), 'utf8');
  const rule = (selector) => css.match(new RegExp(`(^|\\n)${selector.replace(/[.[\]"=]/g, '\\$&')} \\{([^}]*)\\}`))?.[2] ?? '';
  for (const selector of ['.chord-row', '.trail-row', '.hint-line', '.hint-line[data-hint="intervals"]']) {
    assert.match(rule(selector), /(^|[ ;])height: /, selector);
    assert.match(rule(selector), /overflow: hidden|line-clamp/, selector);
  }
  assert.match(rule('.lab-result'), /min-height: /);
});
