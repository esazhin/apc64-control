// The harmony views (T37; inv15, inv16, inv17; A21, A68, A71–A77, A80), rendered from the recorded snapshot pair
// (lab.fixture.json: 'Tonnetz C' active, C3 E3 G3 held — 48 52 55) and from hand-made HarmonyState JSON.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  CIRCLE_KEYS, HINT_ROWS, NO_PADS_TEXT, NOTE_NAMES, chordView, circleView, fretWidths, fullAreas, harmonyFullView,
  harmonyView, inkFor, keyPosition, latticeModel, latticeView, mainChoices, mainViewKind, nearestTriangle, neckMarks,
  neckModel, neckView, padGridModel, padGridView, padReplicaView, placeHarmony,
} from './harmony_views.js';
import { byClass, byData, findAll, hasClass, textOf } from './lab_dom.js';

const FIXTURE = JSON.parse(readFileSync(new URL('./lab.fixture.json', import.meta.url)));
const C_MAJOR = FIXTURE.harmony;
const PADS = FIXTURE.lab.active.pads;
const GRID = padGridModel(FIXTURE.lab);
const withPads = (pads, extra = {}) => padGridModel({ active: { ...FIXTURE.lab.active, pads, ...extra } });
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
});

test('the circle names the major keys outside and their relative minors inside, spelled in key', () => {
  const circle = circleView(EMPTY);
  const names = (cls) => findAll(circle, (n) => n.tag === 'text' && hasClass(n, cls)).map(textOf);
  assert.deepEqual(names('key-name'), ['C', 'G', 'D', 'A', 'E', 'B', 'F♯', 'G♭', 'D♭', 'A♭', 'E♭', 'B♭', 'F']);
  assert.deepEqual(names('minor-name'), ['Am', 'Em', 'Bm', 'F♯m', 'C♯m', 'G♯m', 'D♯m', 'E♭m', 'B♭m', 'Fm', 'Cm', 'Gm', 'Dm']);
  assert.ok(CIRCLE_KEYS.every((k) => k.minorPc === (k.pc + 9) % 12));
  // each relative minor sits inside its major key, on the same spoke
  const a = keyPosition(triad(9, 'minor'));
  const c = keyPosition(triad(0, 'major'));
  assert.ok(Math.abs(Math.atan2(a.y, a.x) - Math.atan2(c.y, c.x)) < 1e-9 && Math.hypot(a.x, a.y) < Math.hypot(c.x, c.y));
});

test('a held major triad lights its key outside, a minor triad its key inside; the trail runs through the keys', () => {
  const lit = (tree) => byClass(tree, 'lit').map((n) => `${n.props.data.pc}:${n.props.data.key}`);
  assert.deepEqual(lit(circleView(C_MAJOR)), ['0:major']);
  const aMinor = { ...EMPTY, held: held(57, 60, 64), chord: 'Am', triads: [triad(9, 'minor')], circle: ['C', 'E', 'A'] };
  assert.deepEqual(lit(circleView(aMinor)), ['9:minor']);
  assert.equal(byClass(circleView(aMinor), 'held').every((n) => hasClass(n, 'fifth')), true);   // notes: the outer ring
  const g = triad(7, 'major');
  const trail = circleView({ ...C_MAJOR, trail_triads: [triad(0, 'major'), triad(9, 'minor'), g] });
  const [line] = findAll(trail, (n) => n.tag === 'polyline' && hasClass(n, 'trail'));
  assert.equal(line.props.points.split(' ').length, 3);
  assert.deepEqual(byClass(trail, 'trail-newest').map((n) => `${n.props.data.pc}:${n.props.data.key}`), ['7:major']);
  assert.deepEqual(byClass(trail, 'in-trail').map((n) => n.props.data.key).sort(), ['major', 'major', 'minor']);
});

test('the main view follows the layout: the Tonnetz for a Tonnetz layout, the pads for any other', () => {
  const withGenerator = (generator) => ({ active: { definition: { generator, params: {}, scheme: 'fifths' } } });
  assert.equal(mainViewKind(FIXTURE.lab), 'tonnetz');
  assert.equal(mainViewKind(withGenerator('isomorphic')), 'pads');
  assert.equal(mainViewKind(withGenerator('modes')), 'pads');
  assert.equal(mainViewKind({ active: { definition: null, preview: true } }), 'pads');   // a library preview
  assert.equal(mainViewKind(null), 'pads');                                               // a host layout, or none
  assert.equal(mainViewKind(withGenerator('isomorphic'), 'tonnetz'), 'tonnetz');          // the full view's override
  assert.equal(mainViewKind(FIXTURE.lab, 'pads'), 'pads');
  assert.equal(mainViewKind(FIXTURE.lab, 'auto'), 'tonnetz');
});

// The Custom port reports notes, not pads, so every pad playing a held note lights: r8c2 plays G (55) as r1c3 does.
test('the pad replica shows the written RGB without an approximate mark and lights the held pads (A21, A68)', () => {
  const replica = padReplicaView(GRID, C_MAJOR);
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
  const controls = { 'pad r1c1': { label_base: '', led: { rgb: '#ff0000', off: false } } };
  const replica = padReplicaView(padGridModel(null, controls), EMPTY);
  assert.equal(byData(replica, 'pad', 'r1c1')[0].props.data.rgb, '#ff0000');
  assert.equal(byClass(replica, 'approx').length, 64);
  assert.match(textOf(byClass(replica, 'legend')[0]), /approximate/);
});

test('two pads playing one note both light while it is held (A80)', () => {
  const pads = PADS.map((p) => ({ ...p }));
  pads.find((p) => p.pad === 'r1c3').note = 48;
  const replica = padReplicaView(withPads(pads), { ...EMPTY, held: held(48) });
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

test('the full view lays out the panel\'s own views by area; its SVGs scale by their viewBox; rows stay reserved', () => {
  const parts = { kind: 'tonnetz', grid: GRID };
  const full = harmonyFullView(C_MAJOR, parts);
  const areas = full.children.map((c) => c.props.data.area);
  assert.deepEqual(areas, fullAreas('tonnetz'));
  const panel = harmonyView(C_MAJOR, parts);
  // the same trees as the panel's (no copy of the view code): lattice, circle, pads, chord rows and hint rows
  const svgs = (tree) => findAll(tree, (n) => n.tag === 'svg');
  assert.deepEqual(svgs(full).map((s) => s.props.viewBox).sort(), svgs(panel).map((s) => s.props.viewBox).sort());
  assert.ok(svgs(full).every((s) => /^-?[\d.]+ -?[\d.]+ [\d.]+ [\d.]+$/.test(s.props.viewBox) && !s.props.width && !s.props.height));
  assert.deepEqual(JSON.stringify(byClass(full, 'lattice')), JSON.stringify(byClass(panel, 'lattice')));
  assert.equal(byClass(full, 'lab-pad').length, 64);
  assert.deepEqual(textOf(byData(full, 'area', 'chord')), textOf(byClass(panel, 'chord-block')[0].children.slice(0, 2)));
  // nothing held: the chord, trail and every hint row are still there, so nothing moves when notes come
  const idle = harmonyFullView(EMPTY, parts);
  assert.equal(byClass(idle, 'chord-row').length, 1);
  assert.equal(byClass(idle, 'trail-row').length, 1);
  assert.deepEqual(byClass(idle, 'hint-line').map((n) => n.props.data.hint), HINT_ROWS.map(([key]) => key));
  assert.ok(byClass(idle, 'hint-line').every((n) => hasClass(n, 'idle')));
});

// --- the pad grid: the main view of every layout but the Tonnetz -------------------------------------------------
const FOURTHS = Array.from({ length: 64 }, (_, i) => {
  const row = Math.floor(i / 8) + 1;
  const column = (i % 8) + 1;
  const note = 36 + (column - 1) + 5 * (row - 1);
  return { pad: `r${row}c${column}`, note, rest: note % 12 === 0 ? '#FFFFFF' : '#004080', silent: false, name: NOTE_NAMES[note % 12] };
});

test('the pad grid draws the layout in its own geometry: names, held pads, the chord tones and root', () => {
  const grid = withPads(FOURTHS, { definition: { generator: 'isomorphic', params: {}, scheme: 'fifths' }, rows: null, scale: null });
  const c = { ...EMPTY, held: held(48, 52, 55), chord: 'C', triads: [triad(0, 'major')], chord_root: 0, chord_tones: [0, 4, 7] };
  const view = padGridView(grid, c);
  const pads = byClass(view, 'grid-pad');
  assert.equal(pads.length, 64);
  assert.deepEqual(pads.slice(0, 2).map((p) => p.props.data.pad), ['r8c1', 'r8c2']);   // top row first, as on the unit
  const r1c1 = byData(view, 'pad', 'r1c1')[0];
  assert.deepEqual([textOf(r1c1.children[0]), textOf(r1c1.children[1]), r1c1.props.style.background], ['C', '1', '#FFFFFF']);
  assert.ok(hasClass(r1c1, 'ink-dark') && hasClass(byData(view, 'pad', 'r1c2')[0], 'ink-light'));
  // every pad playing a held note lights (48 is r3c3 and r4c8 … each a note number); the tones ring in every octave
  const heldPads = byClass(view, 'held').map((p) => p.props.data.note);
  assert.ok(heldPads.length >= 3 && heldPads.every((n) => [48, 52, 55].includes(n)));
  assert.ok(byClass(view, 'chord-tone').every((p) => [0, 4, 7].includes(p.props.data.pc)));
  assert.ok(byClass(view, 'chord-root').length > 0 && byClass(view, 'chord-root').every((p) => p.props.data.pc === 0));
  assert.equal(byClass(view, 'out-of-scale').length, 0);
  assert.equal(byClass(view, 'approx').length, 0);
  assert.match(textOf(byClass(view, 'legend')[0]), /colours as written to the unit/);
});

test('with a scale overlay the notes outside it are dimmed; the modes explorer names its rows', () => {
  const rows = ['Ionian', 'Dorian', 'Phrygian', 'Lydian', 'Mixolydian', 'Aeolian', 'Locrian', ''];
  const scale = { key: 'dorian', name: 'Dorian', root: 2, root_name: 'D', pcs: [0, 2, 4, 5, 7, 9, 11], names: {} };
  const view = padGridView(withPads(FOURTHS, { rows, scale }), EMPTY);
  const outside = new Set(byClass(view, 'out-of-scale').map((p) => p.props.data.pc));
  assert.deepEqual([...outside].sort((a, b) => a - b), [1, 3, 6, 8, 10]);
  assert.deepEqual(byClass(view, 'row-label').map(textOf), [...rows].reverse());     // top row first
  assert.ok(hasClass(byClass(view, 'pad-grid')[0], 'with-rows'));
  assert.match(textOf(byClass(view, 'legend')[0]), /D Dorian overlay: outside notes dimmed/);
});

test('a host layout shows the pads it binds to notes, approximate; with none the grid says so', () => {
  const controls = {
    'pad r1c1': { label_base: 'Note 36 → mpc', led: { rgb: '#ff0000', off: false } },
    'pad r1c2': { label_base: 'Note 37 → mpc +1', led: { rgb: '#00ff00', off: false } },
    'pad r2c1': { label_base: 'CC20 → mpc', led: { rgb: '#000000', off: true } },
  };
  const grid = padGridModel(null, controls);
  assert.equal(grid.source, 'host');
  const view = padGridView(grid, { ...EMPTY, held: held(36) });
  assert.deepEqual(byClass(view, 'held').map((p) => p.props.data.pad), ['r1c1']);
  assert.equal(byData(view, 'pad', 'r1c2')[0].props.data.note, 37);
  assert.ok(hasClass(byData(view, 'pad', 'r2c1')[0], 'silent'));
  assert.ok(byClass(view, 'grid-pad').every((p) => hasClass(p, 'approx')));
  const none = padGridView(padGridModel(null, {}), EMPTY);
  assert.equal(textOf(none), NO_PADS_TEXT);
  assert.equal(byClass(none, 'grid-pad').length, 0);
});

test('the panel and the full view show the pad grid as the main view, without a second small replica', () => {
  const parts = { kind: 'pads', grid: withPads(FOURTHS) };
  const panel = harmonyView(C_MAJOR, parts);
  assert.equal(byClass(panel, 'grid-pad').length, 64);
  assert.equal(byClass(panel, 'lab-pad').length, 0);
  assert.equal(byClass(panel, 'lattice').length, 0);
  const full = harmonyFullView(C_MAJOR, parts);
  assert.deepEqual(full.children.map((c) => c.props.data.area), fullAreas('pads'));
  assert.equal(full.props.data.main, 'pads');
  assert.equal(byClass(full, 'circle').length, 1);
  // beside the Tonnetz the small replica stays
  const tonnetz = harmonyView(C_MAJOR, { kind: 'tonnetz', grid: GRID });
  assert.equal(byClass(tonnetz, 'lattice').length, 1);
  assert.equal(byClass(tonnetz, 'lab-pad').length, 64);
  assert.equal(inkFor('#000000'), 'ink-light');
});


// --- the neck (the guitar amendment): 'Guitar' (E standard) at Fret 3-10, low E fret 5 and the open high E played
// on their strings, a G from a keyboard (lab.fixture.json 'guitar', produced by the services) -----------------
const GUITAR = FIXTURE.guitar;
const NECK_GRID = padGridModel(GUITAR.lab);
const NECK_DATA = NECK_GRID.neck;
const at = (tree, string, fret) => findAll(tree, (n) => n.props?.data && String(n.props.data.string) === String(string)
  && String(n.props.data.fret) === String(fret));

test('a guitar layout\'s main view is its neck; Neck is offered only for it', () => {
  assert.equal(mainViewKind(GUITAR.lab), 'neck');
  assert.equal(mainViewKind(GUITAR.lab, 'pads'), 'pads');
  assert.equal(mainViewKind(FIXTURE.lab, 'neck'), 'tonnetz');           // no neck: Neck reads as Auto
  assert.deepEqual(mainChoices(GUITAR.lab).map(([k]) => k), ['auto', 'tonnetz', 'pads', 'neck']);
  assert.deepEqual(mainChoices(FIXTURE.lab).map(([k]) => k), ['auto', 'tonnetz', 'pads']);
  const panel = harmonyView(GUITAR.harmony, { grid: NECK_GRID, kind: 'neck' });
  assert.equal(byClass(panel, 'neck').length, 1);
  assert.equal(byClass(panel, 'lab-pad').length, 64);                    // the small pad replica beside it
  assert.deepEqual(fullAreas('neck'), ['chord', 'pads', 'main', 'circle', 'hints']);
});

test('the neck: nut on the left, frets narrowing toward the body with a floor, inlays, strings thicker going down', () => {
  const widths = fretWidths(24);
  assert.ok(widths[1] < widths[0] && widths[5] < widths[4]);
  assert.ok(Math.min(...widths) >= 0.55 * widths[0] - 1e-9 && Math.min(...widths) <= 0.56 * widths[0]);
  const m = neckModel(NECK_DATA);
  assert.ok(m.slots[0].cx < m.nut && m.nut < m.slots[1].cx && m.slots[1].cx < m.slots[24].cx);
  assert.deepEqual(m.inlays.map((d) => d.fret), [3, 5, 7, 9, 15, 17, 19, 21, 12, 12, 24, 24]);
  assert.deepEqual(m.lines.map((s) => s.name), ['E', 'B', 'G', 'D', 'A', 'E']);   // highest on top, as on the unit
  assert.ok(m.lines.every((s, k) => k === 0 || s.weight > m.lines[k - 1].weight));
  const tree = neckView(NECK_DATA, GUITAR.harmony);
  assert.deepEqual(byClass(tree, 'string-name').map(textOf), ['E', 'B', 'G', 'D', 'A', 'E']);
  assert.match(tree.props.viewBox, /^0 0 [\d.]+ [\d.]+$/);
  assert.ok(!tree.props.width && !tree.props.height);
});

test('the box marks the frets the unit shows and follows the window', () => {
  const box = (first) => byClass(neckView({ ...NECK_DATA, first }, GUITAR.harmony), 'window-box')[0];
  assert.deepEqual([box(3).props.data.first, box(3).props.data.last], [3, 10]);
  assert.deepEqual([box(17).props.data.first, box(17).props.data.last], [17, 24]);
  const m = neckModel({ ...NECK_DATA, first: 3 });
  assert.ok(m.box.x0 === m.slots[3].x0 && m.box.x1 === m.slots[10].x1);
  assert.notEqual(box(0).props.x, box(8).props.x);
});

test('a note played on a string is a dot there; every other place of its pitch, and a note with no string, a ring', () => {
  const { dots, rings } = neckMarks(NECK_DATA, GUITAR.harmony);
  assert.deepEqual(dots.map((d) => [d.k, d.fret, d.note]), [[5, 5, 45], [0, 0, 64]]);   // low E fret 5; open high E
  assert.ok(rings.some((r) => r.k === 4 && r.fret === 0 && r.note === 45));            // the open A: the same pitch
  assert.ok(!rings.some((r) => r.k === 5 && r.fret === 5));                             // not a ring where the dot is
  assert.deepEqual(rings.filter((r) => r.note === 55).map((r) => [r.k, r.fret]),        // G from the keyboard: all places
    [[2, 0], [3, 5], [4, 10], [5, 15]]);
  const tree = neckView(NECK_DATA, GUITAR.harmony);
  const dot = at(tree, 6, 5).find((n) => hasClass(n, 'played'));
  assert.ok(dot && textOf(byClass(dot, 'dot-name')) === 'A');
  assert.ok(at(tree, 5, 0).some((n) => hasClass(n, 'ring')));
});

test('the neck keeps its size whatever is held, and flips for a left-handed player', () => {
  const empty = neckView(NECK_DATA, EMPTY);
  assert.equal(empty.props.viewBox, neckView(NECK_DATA, GUITAR.harmony).props.viewBox);
  assert.equal(byClass(empty, 'played').length + byClass(empty, 'ring').length, 0);
  const flipped = neckModel(NECK_DATA, { flip: true });
  assert.ok(flipped.slots[0].cx > flipped.nut && flipped.nut > flipped.slots[1].cx);    // the nut on the right
  assert.ok(flipped.labelX > flipped.nut);
  assert.ok(hasClass(neckView(NECK_DATA, EMPTY, { flip: true }), 'flipped'));
  // without string identity (an older service, or held notes only) every place is a ring
  assert.equal(neckMarks(NECK_DATA, { held: held(45) }).dots.length, 0);
  assert.equal(neckMarks(NECK_DATA, { held: held(45) }).rings.length, 2);
});

// --- spelling from context (2026-10-27) ---------------------------------------------------------------------------
test('the intervals hint and the neck name notes as the core spells them (names), not by the fixed table', () => {
  const names = Object.fromEntries(['C', 'F', 'F♯', 'G', 'G♯', 'A', 'B♭', 'B', 'C', 'C♯', 'D', 'D♯'].map((n, k) => [String((k + 4) % 12), n]));
  names['4'] = 'E';
  const hint = textOf(chordView({ ...E_ONLY, names }));
  assert.match(hint, /G♯ 3/);
  assert.doesNotMatch(hint, /A♭ 3/);
  const harmony = { ...GUITAR.harmony, names: { ...GUITAR.harmony.names, 9: 'B𝄫' } };
  const dot = byClass(neckView(NECK_DATA, harmony), 'played').find((n) => n.props.data.note === 45);
  assert.equal(textOf(byClass(dot, 'dot-name')), 'B𝄫');
});

test('displayed names use the context spelling; lookups keep the fixed names (E major: G♯m, the circle\'s G♯)', () => {
  const names = { 0: 'C', 1: 'C♯', 2: 'D', 3: 'D♯', 4: 'E', 5: 'F', 6: 'F♯', 7: 'G', 8: 'G♯', 9: 'A', 10: 'B♭', 11: 'B' };
  const e = { ...EMPTY, held: held(52, 56, 59), chord: 'E', names, circle: ['E', 'B', 'A♭'],
    triads: [{ root: 4, quality: 'major', label: 'E', display: 'E' }],
    neighbours: [{ root: 4, quality: 'minor', label: 'Em', display: 'Em' }, { root: 1, quality: 'minor', label: 'C♯m', display: 'C♯m' },
      { root: 8, quality: 'minor', label: 'A♭m', display: 'G♯m' }] };
  assert.match(textOf(chordView(e)), /Em, C♯m, G♯m$/);
  const lattice = latticeView(e);
  const labels = byClass(lattice, 'tri-label').map((n) => n.props.text);
  assert.ok(labels.includes('G♯m') && !labels.includes('A♭m'));
  assert.ok(byClass(lattice, 'node-name').some((n) => n.props.text === 'G♯'));
  const circle = circleView(e);
  const key = byData(circle, 'key', 'major').find((n) => n.props.data.pc === 8);
  assert.equal(textOf(key), 'G♯');                                   // held: as spelled now
  assert.ok(hasClass(key, 'held'));                                  // found through the fixed name A♭
  assert.equal(textOf(byData(circle, 'key', 'major').find((n) => n.props.data.pc === 1)), 'D♭');   // not held: the key's
});

test('the performer\'s control pads show their names, never a note, an octave or a chord ring', () => {
  const pads = Array.from({ length: 64 }, (_, i) => ({ pad: `r${Math.floor(i / 8) + 1}c${(i % 8) + 1}`, note: 40 + (i % 8),
    rest: '#00FF00', silent: false, name: 'E' }));
  pads[56] = { pad: 'r8c1', note: 0, rest: '#FFAA00', silent: false, name: 'maj', control: true };
  const grid = padGridModel({ active: { pads } });
  const tree = padGridView(grid, { held: [{ note: 0 }], chord_tones: [0], chord_root: 0 });
  const control = findAll(tree, (n) => n.props?.data?.pad === 'r8c1')[0];
  assert.ok(hasClass(control, 'control') && !hasClass(control, 'chord-tone') && !hasClass(control, 'held'));
  assert.equal(textOf(control), 'maj');
});
