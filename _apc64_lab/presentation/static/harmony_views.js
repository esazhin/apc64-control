// The harmony views (contract pi7; inv15, inv16, inv17; A68–A80): pure functions from the service's HarmonyState
// (GET /api/lab/harmony, the ws 'lab' topic kind 'harmony') to h() trees. Every name, chord and hint comes from
// the server's harmony core (its spelling, §2.7 a25); this file only places them: the main view of the active
// layout (the Tonnetz lattice with its triads for a Tonnetz layout, else the large pad grid in the layout's own
// geometry, or the neck for a guitar layout), the chord and its trail, the interval and neighbour hints, the circle
// of fifths with its relative minors, and beside the Tonnetz and the neck the small pad replica.
// Reference: prototypes/tonnetz-view/index.html (its lattice geometry and colours), minus Web MIDI.
import { h } from './lab_dom.js';

// the fixed spelling table without key context (§2.7 a25); equal to the core's NOTE_DISPLAY (a test checks it).
export const NOTE_NAMES = ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];
export const NO_CHORD = '—';
export const mod = (n, m) => ((n % m) + m) % m;
export const fifthsIndex = (pc) => mod(pc * 7, 12);
export const pcOfName = (name) => NOTE_NAMES.indexOf(name);

// Theory colours of the lattice and the circle (the default 'fifths' scheme's hues): not palette colours.
export function pcColour(pc) {
  return mod(pc, 12) === 0 ? '#ffffff' : `hsl(${fifthsIndex(pc) * 30}, 100%, 55%)`;
}

const triadKey = (t) => `${mod(t.root, 12)}:${t.quality}`;
// A pitch class as the core spells it for what is held now (HarmonyState.names: the chord's, the key's or above the
// lowest note, 2026-10-27); the fixed table when the state has no names.
export const spelledName = (harmony, pc) => harmony?.names?.[String(mod(pc, 12))] ?? NOTE_NAMES[mod(pc, 12)];
// A triad as displayed: its root spelled now ('G♯m' with E major held); `label` stays the fixed lookup name.
export const triadName = (t) => t?.display ?? t?.label ?? '';
const heldPcs = (harmony) => new Set((harmony?.held ?? []).map((n) => mod(n.pc ?? n.note, 12)));
const heldNotes = (harmony) => new Set((harmony?.held ?? []).map((n) => n.note));

// --- the Tonnetz lattice (p13): → fifths, ↗ major thirds, ↖ minor thirds ---------------------------------
export const LATTICE = { w: 30, i0: -4, i1: 4, j0: -3, j1: 3 };

export function latticeModel(spec = LATTICE) {
  const W = spec.w;
  const H = (W * Math.sqrt(3)) / 2;
  const pos = (i, j) => ({ x: i * W + (j * W) / 2, y: -j * H });
  const pcAt = (i, j) => mod(7 * i + 4 * j, 12);
  const nodes = [];
  for (let j = spec.j0; j <= spec.j1; j++) {
    for (let i = spec.i0; i <= spec.i1; i++) nodes.push({ i, j, pc: pcAt(i, j), ...pos(i, j) });
  }
  const triangles = [];
  for (let j = spec.j0; j < spec.j1; j++) {
    for (let i = spec.i0; i < spec.i1; i++) {
      // ▲ (i,j) (i+1,j) (i,j+1) = n, n+7, n+4: major on n.  ▼ (i+1,j) (i+1,j+1) (i,j+1): minor on n+4.
      const up = { root: pcAt(i, j), quality: 'major', cells: [[i, j], [i + 1, j], [i, j + 1]] };
      const down = { root: pcAt(i, j + 1), quality: 'minor', cells: [[i + 1, j], [i + 1, j + 1], [i, j + 1]] };
      for (const t of [up, down]) {
        t.points = t.cells.map(([a, b]) => pos(a, b));
        t.c = { x: t.points.reduce((s, p) => s + p.x, 0) / 3, y: t.points.reduce((s, p) => s + p.y, 0) / 3 };
        t.key = triadKey(t);
        t.id = `${t.quality === 'major' ? 'up' : 'down'}${i},${j}`;
        triangles.push(t);
      }
    }
  }
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const pad = 14;
  const box = { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad, w: Math.max(...xs) - Math.min(...xs) + 2 * pad,
    h: Math.max(...ys) - Math.min(...ys) + 2 * pad };
  return { nodes, triangles, box, pos };
}

const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

// The one lattice triangle of a triad nearest a point (a triad repeats across the lattice; one is lit, A76).
export function nearestTriangle(model, triad, near = { x: 0, y: 0 }) {
  let best = null;
  for (const t of model.triangles) {
    if (t.key !== triadKey(triad)) continue;
    if (!best || distance(t.c, near) < distance(best.c, near) - 1e-9) best = t;
  }
  return best;
}

function shares(a, b) {
  const pcs = (t) => new Set(t.quality === 'major' ? [t.root, t.root + 4, t.root + 7].map((p) => mod(p, 12))
    : [t.root, t.root + 3, t.root + 7].map((p) => mod(p, 12)));
  const x = pcs(a);
  return [...pcs(b)].filter((p) => x.has(p)).length;
}

// Where each part of a HarmonyState sits on the lattice.
export function placeHarmony(model, harmony) {
  const origin = { x: 0, y: 0 };
  const lit = (harmony?.triads ?? []).map((t) => nearestTriangle(model, t, origin)).filter(Boolean);
  const neighbourTriads = harmony?.neighbours ?? [];
  const primary = lit.find((l) => neighbourTriads.every((n) => shares(l, n) === 2)) ?? lit[0] ?? null;
  const neighbours = primary ? neighbourTriads.map((n) => nearestTriangle(model, n, primary.c)).filter(Boolean) : [];
  let hints = [];
  const pcs = heldPcs(harmony);
  if (pcs.size === 1 && (harmony?.hints ?? []).length) {
    const [pc] = pcs;
    const node = model.nodes.filter((n) => n.pc === pc).sort((a, b) => distance(a, origin) - distance(b, origin))[0];
    hints = model.triangles.filter((t) => t.cells.some(([i, j]) => i === node.i && j === node.j));
  }
  const trail = [];
  let last = origin;
  for (const t of harmony?.trail_triads ?? []) {
    const at = nearestTriangle(model, t, last);
    if (!at) continue;
    trail.push({ x: at.c.x, y: at.c.y, label: t.label });
    last = at.c;
  }
  return { lit, neighbours, hints, trail, primary };
}

const fixed = (n) => Number(n.toFixed(2));
const pointsOf = (pts) => pts.map((p) => `${fixed(p.x)},${fixed(p.y)}`).join(' ');

export function latticeView(harmony, model = latticeModel()) {
  const placed = placeHarmony(model, harmony);
  const pcs = heldPcs(harmony);
  const degrees = harmony?.degrees ?? {};
  const litIds = new Set(placed.lit.map((t) => t.id));
  const neighbourIds = new Set(placed.neighbours.map((t) => t.id));
  const hintIds = new Set(placed.hints.map((t) => t.id));
  const hintLabels = new Map((harmony?.hints ?? []).map((t) => [triadKey(t), triadName(t)]));
  const { box } = model;
  return h('svg', { class: 'lattice', viewBox: `${fixed(box.x)} ${fixed(box.y)} ${fixed(box.w)} ${fixed(box.h)}`,
    role: 'img', 'aria-label': 'Tonnetz lattice: fifths to the right, major thirds up-right, minor thirds up-left' },
  h('g', { class: 'triangles' }, model.triangles.map((t) => h('polygon', {
    points: pointsOf(t.points),
    class: ['tri', t.quality, litIds.has(t.id) && 'lit', neighbourIds.has(t.id) && 'neighbour', hintIds.has(t.id) && 'hint'],
    data: { triad: t.key },
  }))),
  h('g', { class: 'labels' }, [...placed.lit, ...placed.neighbours, ...placed.hints].map((t) => h('text', {
    x: fixed(t.c.x), y: fixed(t.c.y), class: ['tri-label', litIds.has(t.id) ? 'lit' : 'soft'],
    text: (litIds.has(t.id) ? triadName(harmony.triads.find((x) => triadKey(x) === t.key))
      : neighbourIds.has(t.id) ? triadName(harmony.neighbours.find((x) => triadKey(x) === t.key))
        : hintLabels.get(t.key)) ?? '',
  }))),
  placed.trail.length > 1 ? h('polyline', { class: 'trail', points: pointsOf(placed.trail) }) : null,
  h('g', { class: 'trail-dots' }, placed.trail.map((p, k) => h('circle', {
    cx: fixed(p.x), cy: fixed(p.y), r: fixed(2.5 + (2.5 * (k + 1)) / placed.trail.length),
    class: ['trail-dot', k === placed.trail.length - 1 && 'newest'],
  }))),
  h('g', { class: 'nodes' }, model.nodes.map((n) => {
    const degree = degrees[NOTE_NAMES[n.pc]];
    return h('g', { class: ['node', pcs.has(n.pc) && 'held'], data: { pc: n.pc } },
      h('circle', { cx: fixed(n.x), cy: fixed(n.y), r: 9, fill: pcColour(n.pc) }),
      h('text', { x: fixed(n.x), y: fixed(degree ? n.y - 2.5 : n.y), class: 'node-name', text: spelledName(harmony, n.pc) }),
      degree ? h('text', { x: fixed(n.x), y: fixed(n.y + 4.5), class: 'node-degree', text: degree }) : null);
  })));
}

// --- the circle of fifths (d60): C at the top, the major keys outside and their relative minors inside -------
// The keys as the harmony core names them (circle.circle_keys(); a test checks they are equal): MusicCat's parent
// keys outside, with F♯ beside G♭ at the bottom, and inside each relative minor spelled in its key, named as the
// chord names minor triads. The held pitch classes light on the outer ring and are joined in circle order; the
// held triads light their key (a major triad outside, a minor one inside); the trail runs through its keys.
export const CIRCLE_KEYS = [
  { pc: 0, major: ['C'], minorPc: 9, minor: ['Am'] },
  { pc: 7, major: ['G'], minorPc: 4, minor: ['Em'] },
  { pc: 2, major: ['D'], minorPc: 11, minor: ['Bm'] },
  { pc: 9, major: ['A'], minorPc: 6, minor: ['F♯m'] },
  { pc: 4, major: ['E'], minorPc: 1, minor: ['C♯m'] },
  { pc: 11, major: ['B'], minorPc: 8, minor: ['G♯m'] },
  { pc: 6, major: ['F♯', 'G♭'], minorPc: 3, minor: ['D♯m', 'E♭m'] },
  { pc: 1, major: ['D♭'], minorPc: 10, minor: ['B♭m'] },
  { pc: 8, major: ['A♭'], minorPc: 5, minor: ['Fm'] },
  { pc: 3, major: ['E♭'], minorPc: 0, minor: ['Cm'] },
  { pc: 10, major: ['B♭'], minorPc: 7, minor: ['Gm'] },
  { pc: 5, major: ['F'], minorPc: 2, minor: ['Dm'] },
];
export const CIRCLE = { outer: 90, inner: 57, outerR: 16, innerR: 13 };

export function circlePosition(pc, radius = CIRCLE.outer) {
  const a = ((fifthsIndex(pc) * 30 - 90) * Math.PI) / 180;
  return { x: radius * Math.cos(a), y: radius * Math.sin(a) };
}

// Where a triad's key sits: a major one at its root outside, a minor one inside at its relative major's place.
export function keyPosition(t) {
  const root = mod(t.root, 12);
  return t.quality === 'minor' ? circlePosition(root + 3, CIRCLE.inner) : circlePosition(root, CIRCLE.outer);
}

// One or two names, centred on a point (two lines at the enharmonic bottom).
function keyLabel(p, names, cls) {
  if (names.length === 1) return h('text', { x: fixed(p.x), y: fixed(p.y), class: cls, text: names[0] });
  return h('g', { class: cls }, names.map((name, k) => h('text', {
    x: fixed(p.x), y: fixed(p.y + (k ? 4.6 : -4.6)), class: [cls, 'two'], text: name })));
}

export function circleView(harmony) {
  const pcs = heldPcs(harmony);
  const order = (harmony?.circle ?? []).map(pcOfName).filter((pc) => pc >= 0);
  const ring = order.map((pc) => circlePosition(pc));
  const triads = new Set((harmony?.triads ?? []).map(triadKey));
  // what is held shows as spelled now (G♯ for the A♭ key while E major is held); the rest keeps the key names
  const litMinor = new Map((harmony?.triads ?? []).filter((t) => t.quality === 'minor').map((t) => [mod(t.root, 12), triadName(t)]));
  const trailTriads = harmony?.trail_triads ?? [];
  const trail = trailTriads.map(keyPosition);
  const newest = trailTriads.length ? triadKey(trailTriads.at(-1)) : null;
  const trailed = new Set(trailTriads.map(triadKey));
  const marks = (k) => [trailed.has(k) && 'in-trail', newest === k && 'trail-newest'];
  return h('svg', { class: 'circle', viewBox: '-112 -112 224 224', role: 'img',
    'aria-label': 'Circle of fifths: major keys outside, their relative minors inside' },
  h('circle', { cx: 0, cy: 0, r: CIRCLE.outer, class: 'ring' }),
  h('circle', { cx: 0, cy: 0, r: CIRCLE.inner, class: 'ring inner' }),
  ring.length > 1 ? h('polygon', { class: 'joined', points: pointsOf(ring) }) : null,
  trail.length > 1 ? h('polyline', { class: 'trail', points: pointsOf(trail) }) : null,
  CIRCLE_KEYS.map((key) => {
    const p = circlePosition(key.pc);
    const q = circlePosition(key.pc, CIRCLE.inner);
    const majorLit = triads.has(`${key.pc}:major`);
    const minorLit = triads.has(`${key.minorPc}:minor`);
    return h('g', { class: 'key', data: { pc: key.pc } },
      h('g', { class: ['fifth', pcs.has(key.pc) && 'held', majorLit && 'lit', ...marks(`${key.pc}:major`)],
        data: { pc: key.pc, key: 'major' } },
        h('circle', { cx: fixed(p.x), cy: fixed(p.y), r: CIRCLE.outerR, fill: pcColour(key.pc) }),
        keyLabel(p, pcs.has(key.pc) ? [spelledName(harmony, key.pc)] : key.major, 'key-name')),
      h('g', { class: ['minor-key', minorLit && 'lit', ...marks(`${key.minorPc}:minor`)],
        data: { pc: key.minorPc, key: 'minor' } },
        h('circle', { cx: fixed(q.x), cy: fixed(q.y), r: CIRCLE.innerR }),
        keyLabel(q, litMinor.has(key.minorPc) ? [litMinor.get(key.minorPc)] : key.minor, 'minor-name')));
  }));
}

// --- the chord, its trail and the hints (d51–d57, d61) ----------------------------------------------------
// Every row is always there at a fixed height, so the views below never move while notes come and go (live
// session 2026-10-26): the chord row and the trail (up to 8, two lines) keep their space, and each hint row
// shows what it would hold while it is idle. A hint longer than its row is cut; its title has all of it.
export const HINT_ROWS = [
  ['intervals', 'intervals: hold one note'],
  ['contains', 'chords with a note: hold one note'],
  ['neighbours', 'neighbouring triads (P, R, L): hold a major or minor triad'],
];

// The hint rows' contents: {intervals, contains, neighbours}, each [label, text] or null.
export function hintTexts(harmony) {
  const pcs = heldPcs(harmony);
  const hints = { intervals: null, contains: null, neighbours: null };
  if (pcs.size === 1 && harmony?.degrees) {
    const [pc] = pcs;
    const from = spelledName(harmony, pc);
    // degrees are keyed by the fixed table; each other note is named as spelled above the held one (E: G♯ 3)
    const intervals = Object.entries(harmony.degrees).filter(([name]) => pcOfName(name) !== pc)
      .map(([name, label]) => `${pcOfName(name) >= 0 ? spelledName(harmony, pcOfName(name)) : name} ${label}`);
    hints.intervals = [`intervals from ${from}: `, intervals.join(' · ')];
    if ((harmony.hints ?? []).length) hints.contains = [`chords with ${from}: `, harmony.hints.map(triadName).join(', ')];
  }
  if ((harmony?.neighbours ?? []).length) {
    hints.neighbours = ['neighbouring triads (P, R, L): ', harmony.neighbours.map(triadName).join(', ')];
  }
  return hints;
}

// The chord row and the trail (both reserved), then the hint rows: the panel shows them as one block, the full
// view puts the hints under the lattice and the circle. The trail (2026-10-27) is the last 8 named chords; its
// Clear button (when `onClearTrail` is given) sits at the row's end, so the row keeps its two lines.
export const TRAIL_TITLE = 'Trail: the last 8 chords you held, newest last. The same chord again adds nothing; a chord '
  + 'that grows while held replaces its entry (C, then + B: Cmaj7).';
export const TRAIL_EMPTY = 'empty: the last 8 chords you hold show here';

export function chordRows(harmony, { onClearTrail = null } = {}) {
  const held = harmony?.held ?? [];
  const names = held.map((n) => n.name).join(' ');
  const trail = harmony?.trail ?? [];
  return [
    h('div', { class: 'chord-row' },
      h('span', { class: 'chord', data: { chord: harmony?.chord ?? NO_CHORD }, text: harmony?.chord || NO_CHORD }),
      h('span', { class: 'held-names', title: names, text: names })),
    h('div', { class: 'trail-row', title: TRAIL_TITLE },
      h('span', { class: 'muted trail-label', text: 'trail: ' }),
      h('span', { class: 'trail-chords' }, trail.length ? trail.map((label, k) => h('span', {
        class: ['trail-chord', k === trail.length - 1 && 'newest'], text: label })) : h('span', { class: 'muted', text: TRAIL_EMPTY })),
      onClearTrail ? h('button', { type: 'button', class: 'view-btn trail-clear', data: { action: 'clear-trail' },
        disabled: !trail.length, title: 'Empty the trail (the views only show; nothing is sent)', onclick: onClearTrail,
        text: 'Clear' }) : null),
  ];
}

export function hintRows(harmony) {
  const hints = hintTexts(harmony);
  return HINT_ROWS.map(([key, idle]) => {
    const hint = hints[key];
    return h('div', { class: ['hint-line', !hint && 'idle'], data: { hint: key }, title: hint ? hint.join('') : idle },
      hint ? [h('span', { class: 'muted', text: hint[0] }), hint[1]] : idle);
  });
}

export function chordView(harmony, options = {}) {
  return h('div', { class: 'chord-block' }, chordRows(harmony, options), hintRows(harmony));
}

// --- the pads: what the active layout plays, as a grid model (A21, A68, A80; inv17) -----------------------------
export const PAD_IDS = [];   // r8c1 … r8c8, then down to r1c8: the order the grids draw them (top row first)
for (let row = 8; row >= 1; row--) for (let column = 1; column <= 8; column++) PAD_IDS.push({ id: `r${row}c${column}`, row, column });

const HOST_NOTE = /^Note (\d+)(?!\d)/;   // the host's generated pad label: 'Note 36 → mpc' (resolver.binding_label)
const octaveOf = (note) => Math.floor(note / 12) - 2;   // C3 = 60, as the host and the core count

// The 64 pads of the active layout, from what the lab already has: a generated layout's pads as written to the
// unit (LabState.active.pads: exact RGB, each pad's name spelled by the core, the generator's row names and the
// scheme's scale overlay); else the host layout's pads, their notes read from their labels and their colours from
// the host replica's palette (approximate); else nothing known (source 'none').
export function padGridModel(lab, controls = {}) {
  const active = lab?.active;
  if (Array.isArray(active?.pads) && active.pads.length === 64) {
    const byPad = new Map(active.pads.map((p) => [p.pad, p]));
    const cells = PAD_IDS.map(({ id, row, column }) => {
      const pad = byPad.get(id);
      const silent = !pad || pad.silent;
      return { pad: id, row, column, note: silent ? null : pad.note, rgb: silent ? null : pad.rest,
        name: silent ? null : (pad.name ?? NOTE_NAMES[mod(pad.note, 12)]) };
    });
    return { source: 'lab', exact: true, cells, rows: active.rows?.length === 8 ? active.rows : null,
      scale: active.scale ?? null, neck: active.neck ?? null };
  }
  const cells = PAD_IDS.map(({ id, row, column }) => {
    const control = controls?.[`pad ${id}`];
    const match = HOST_NOTE.exec(control?.label_base ?? '');
    const note = match ? Number(match[1]) : null;
    const rgb = control?.led && !control.led.off ? control.led.rgb : null;
    return { pad: id, row, column, note, rgb, name: note === null ? null : NOTE_NAMES[mod(note, 12)] };
  });
  const known = cells.some((c) => c.note !== null);
  return { source: known ? 'host' : 'none', exact: false, cells, rows: null, scale: null, neck: null };
}

// Which view is the large one: the neck for a layout whose generator draws one (the guitar), the Tonnetz for a
// Tonnetz-generator layout, the pad grid for every other (isomorphic, modes, a plugin, a library preview, a host
// layout, none). `override` ('tonnetz' | 'pads' | 'neck') is the full view's Main choice; Neck holds only while the
// layout has a neck; 'auto' (or anything else) decides from the layout.
export const MAIN_CHOICES = [['auto', 'Auto'], ['tonnetz', 'Tonnetz'], ['pads', 'Pads'], ['neck', 'Neck']];
export const hasNeck = (lab) => Boolean(lab?.active?.neck?.strings?.length);
export function mainChoices(lab) {
  return MAIN_CHOICES.filter(([key]) => key !== 'neck' || hasNeck(lab));
}
export function mainViewKind(lab, override = 'auto') {
  if (override === 'tonnetz' || override === 'pads') return override;
  if (hasNeck(lab)) return 'neck';
  return lab?.active?.definition?.generator === 'tonnetz' ? 'tonnetz' : 'pads';
}

// Dark ink on a light pad, light ink on a dark one (the pads take any colour the scheme writes).
export function inkFor(rgb) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(rgb ?? '');
  if (!m) return 'ink-light';
  const [r, g, b] = m.slice(1).map((x) => parseInt(x, 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 ? 'ink-dark' : 'ink-light';
}

export const NO_PADS_TEXT = 'No pad notes known for this layout. A generated layout (a lab: section) shows its pads '
  + 'here, and a host layout the pads it binds to notes; the unit\'s own Note and Chord views lay out their pads themselves.';

// The large pad grid (the main view for every layout but the Tonnetz): each pad in its colour with its note's name,
// the held notes lit, the chord's tones ringed and its root marked, the notes outside a scale overlay dimmed, and
// the generator's row names (the modes explorer's) beside the rows.
export function padGridView(grid, harmony) {
  if (!grid || grid.source === 'none') {
    return h('div', { class: 'pad-grid-empty muted', data: { empty: 'pads' }, text: NO_PADS_TEXT });
  }
  const notes = heldNotes(harmony);
  const tones = new Set(harmony?.chord_tones ?? []);
  const chordRoot = harmony?.chord_root ?? null;
  const scale = grid.scale;
  const inScale = scale ? new Set(scale.pcs) : null;
  const cells = [];
  for (const cell of grid.cells) {
    if (cell.column === 1 && grid.rows) {
      cells.push(h('div', { class: 'row-label', data: { row: cell.row }, text: grid.rows[cell.row - 1] }));
    }
    if (cell.note === null) {
      cells.push(h('div', { class: ['grid-pad', 'silent', !grid.exact && 'approx'], data: { pad: cell.pad, note: '' },
        style: cell.rgb ? { background: cell.rgb } : {}, title: `${cell.pad}: silent` }));
      continue;
    }
    const pc = mod(cell.note, 12);
    cells.push(h('div', {
      class: ['grid-pad', inkFor(cell.rgb), notes.has(cell.note) && 'held', tones.has(pc) && 'chord-tone',
        pc === chordRoot && 'chord-root', inScale && !inScale.has(pc) && 'out-of-scale', !grid.exact && 'approx'],
      data: { pad: cell.pad, note: cell.note, pc, rgb: cell.rgb ?? '' },
      style: cell.rgb ? { background: cell.rgb } : {},
      title: `${cell.pad}: ${cell.name}${octaveOf(cell.note)} (note ${cell.note})${cell.rgb ? `, ${cell.rgb}` : ''}`,
    }, h('span', { class: 'pad-name', text: cell.name }), h('span', { class: 'pad-octave', text: String(octaveOf(cell.note)) })));
  }
  const legend = [grid.exact ? 'colours as written to the unit' : '≈ approximate colours (Ableton palette): the host layout\'s pads',
    scale ? `${scale.root_name ?? NOTE_NAMES[scale.root]} ${scale.name} overlay: outside notes dimmed` : null,
    'ring: a chord tone · dot: its root'].filter(Boolean).join(' · ');
  return h('div', { class: 'pad-grid-block' },
    h('div', { class: ['pad-grid', grid.rows && 'with-rows'], data: { source: grid.source } }, cells),
    h('div', { class: 'legend muted', text: legend }));
}

// The small pad replica beside the Tonnetz: the 64 pads in their colours, the held notes lit; palette colours
// marked approximate when no generated layout is active (inv17).
export function padReplicaView(grid, harmony) {
  const notes = heldNotes(harmony);
  const exact = grid?.exact === true;
  const rows = (grid?.cells ?? PAD_IDS.map(({ id }) => ({ pad: id, note: null, rgb: null }))).map((cell) => {
    const silent = exact ? cell.note === null : !cell.rgb;
    return h('div', {
      class: ['lab-pad', silent && 'silent', !exact && 'approx', !silent && cell.note !== null && notes.has(cell.note) && 'held'],
      data: { pad: cell.pad, note: cell.note ?? '', rgb: cell.rgb ?? '' },
      style: cell.rgb ? { background: cell.rgb } : {},
      title: cell.note === null ? `${cell.pad}: ${cell.rgb ?? 'silent'}` : `${cell.pad}: note ${cell.note}, ${cell.rgb}`
        + (exact ? '' : ' (approximate palette colour)'),
    });
  });
  return h('div', { class: 'replica-block' },
    h('div', { class: 'lab-pads' }, rows),
    h('div', { class: 'legend muted', text: exact ? 'colours as written to the unit'
      : '≈ approximate colours (Ableton palette): no generated layout is active' }));
}

// --- the neck: a guitar layout's fretboard (the guitar amendment, 2026-10-27) ---------------------------------
// Horizontal, the nut on the left (on the right when flipped for a left-handed player), the highest string on top as
// on the unit. Frets narrow toward the body like a real neck (the nut-to-fret distance goes as 1 − 2^(−n/12)), but
// never below NECK.floor of the first fret, so the high frets stay readable. A box marks the frets the unit shows
// (the window: `first` … first + shown − 1). A note played on a string (the APC64's Custom port, one channel per
// string) is a solid dot with its name at that string and fret; every other place of the same pitch is a ring; a
// note without a string (another input, the Notes port) is a ring at all its places. The SVG's size depends only on
// the neck, so nothing moves while notes come and go.
export const NECK = { labelW: 24, openW: 34, fretW: 640, spacing: 20, top: 16, bottom: 26, floor: 0.55, dot: 7.5 };
export const INLAYS = [3, 5, 7, 9, 15, 17, 19, 21];
export const DOUBLE_INLAYS = [12, 24];

// Slot widths of frets 1…n: proportional to 2^(−(f−1)/12) (the real spacing), with the floor; scaled to `total`.
export function fretWidths(frets, total = NECK.fretW, floor = NECK.floor) {
  const raw = Array.from({ length: frets }, (_, k) => Math.max(2 ** (-k / 12), floor));
  const sum = raw.reduce((s, w) => s + w, 0);
  return raw.map((w) => (w * total) / sum);
}

// Where everything sits: the slot of each fret (0 = the open strings, left of the nut), each string's line, the
// box of the frets on the pads, the inlays. `flip` mirrors left and right (the text stays readable).
export function neckModel(neck, { flip = false } = {}) {
  const strings = neck?.strings ?? [];
  const frets = Number(neck?.frets ?? 0);
  const widths = fretWidths(frets);
  const width = NECK.labelW + NECK.openW + NECK.fretW + 8;
  const nut = NECK.labelW + NECK.openW;
  const left = [NECK.labelW];   // the left edge of each slot, fret 0 first
  let x = nut;
  for (let f = 1; f <= frets; f++) { left.push(x); x += widths[f - 1]; }
  const right = (f) => (f === 0 ? nut : left[f] + widths[f - 1]);
  const mirror = (v) => (flip ? width - v : v);
  const slots = Array.from({ length: frets + 1 }, (_, f) => {
    const [a, b] = [mirror(left[f]), mirror(right(f))].sort((p, q) => p - q);
    return { fret: f, x0: a, x1: b, cx: (a + b) / 2 };
  });
  const y = (k) => NECK.top + k * NECK.spacing;   // k = 0: the highest string
  const neckTop = y(0) - NECK.spacing / 2;
  const neckBottom = y(Math.max(strings.length - 1, 0)) + NECK.spacing / 2;
  const lines = strings.map((s, k) => ({ ...s, k, y: y(k),
    weight: strings.length > 1 ? 0.8 + (2.4 * k) / (strings.length - 1) : 1.2 }));
  const shown = Number(neck?.shown ?? 8);
  const first = Math.max(0, Math.min(Number(neck?.first ?? 0), frets));
  const last = Math.min(first + shown - 1, frets);
  const box = { x0: Math.min(slots[first].x0, slots[last].x0), x1: Math.max(slots[first].x1, slots[last].x1),
    y0: neckTop - 4, y1: neckBottom + 4, first, last };
  const wires = Array.from({ length: frets + 1 }, (_, f) => mirror(right(f)));
  const middle = (neckTop + neckBottom) / 2;
  const third = (neckBottom - neckTop) / 3;
  const inlays = [];
  for (const f of INLAYS) if (f <= frets) inlays.push({ fret: f, x: slots[f].cx, y: middle });
  for (const f of DOUBLE_INLAYS) if (f <= frets) inlays.push({ fret: f, x: slots[f].cx, y: neckTop + third }, { fret: f, x: slots[f].cx, y: neckBottom - third });
  const height = neckBottom + NECK.bottom;
  return { width, height, slots, lines, box, wires, inlays, nut: mirror(nut), neckTop, neckBottom, flip,
    labelX: mirror(NECK.labelW / 2), numbersY: neckBottom + 15, frets };
}

// Every place of a note on the neck: [{k, fret}] (k = 0 the highest string).
export function placesOf(neck, note) {
  const frets = Number(neck?.frets ?? 0);
  return (neck?.strings ?? []).map((s, k) => ({ k, fret: note - s.open })).filter((p) => p.fret >= 0 && p.fret <= frets);
}

// What the neck marks: dots where a note was played on a string, rings at every other place of a held pitch.
export function neckMarks(neck, harmony) {
  const strings = neck?.strings ?? [];
  const frets = Number(neck?.frets ?? 0);
  const voices = Array.isArray(harmony?.played) ? harmony.played
    : (harmony?.held ?? []).map((n) => ({ source: null, channel: null, note: n.note }));
  const dots = new Map();
  for (const v of voices) {
    if (v.source !== 'custom' || v.channel === null || v.channel === undefined) continue;
    const k = strings.findIndex((s) => s.channel === v.channel);
    const fret = k < 0 ? -1 : v.note - strings[k].open;
    if (fret >= 0 && fret <= frets) dots.set(`${k}:${fret}`, { k, fret, note: v.note });
  }
  const pitches = new Set([...voices.map((v) => v.note), ...(harmony?.held ?? []).map((n) => n.note)]);
  const rings = [];
  for (const note of [...pitches].sort((a, b) => a - b)) {
    for (const p of placesOf(neck, note)) if (!dots.has(`${p.k}:${p.fret}`)) rings.push({ ...p, note });
  }
  return { dots: [...dots.values()], rings };
}

export const NECK_FRET_NUMBERS = [0, 3, 5, 7, 9, 12, 15, 17, 19, 21, 24, 27, 29, 31, 33, 36];

export function neckView(neck, harmony, { flip = false } = {}) {
  if (!neck?.strings?.length) return h('div', { class: 'pad-grid-empty muted', text: 'No neck: this layout is not a guitar layout.' });
  const m = neckModel(neck, { flip });
  const { dots, rings } = neckMarks(neck, harmony);
  const at = (p) => ({ x: fixed(m.slots[p.fret].cx), y: fixed(m.lines[p.k].y) });
  return h('svg', { class: ['neck', flip && 'flipped'], viewBox: `0 0 ${fixed(m.width)} ${fixed(m.height)}`, role: 'img',
    'aria-label': `Guitar neck: ${neck.strings.length} strings, ${neck.frets} frets; the box is the frets on the pads`,
    data: { strings: neck.strings.length, frets: neck.frets, first: m.box.first } },
  h('rect', { class: 'neck-wood', x: fixed(Math.min(m.nut, m.wires[m.frets])), y: fixed(m.neckTop),
    width: fixed(Math.abs(m.wires[m.frets] - m.nut)), height: fixed(m.neckBottom - m.neckTop) }),
  h('g', { class: 'inlays' }, m.inlays.map((d) => h('circle', { cx: fixed(d.x), cy: fixed(d.y), r: 3.2, class: 'inlay', data: { fret: d.fret } }))),
  h('g', { class: 'frets' }, m.wires.map((x, f) => h('line', { x1: fixed(x), x2: fixed(x), y1: fixed(m.neckTop), y2: fixed(m.neckBottom),
    class: ['fret-wire', f === 0 && 'nut'], data: { fret: f } }))),
  h('g', { class: 'strings' }, m.lines.map((s) => h('g', { class: 'string', data: { string: s.string, channel: s.channel } },
    h('line', { x1: fixed(Math.min(m.slots[0].x0, m.slots[m.frets].x1)), x2: fixed(Math.max(m.slots[0].x0, m.slots[m.frets].x1)),
      y1: fixed(s.y), y2: fixed(s.y), class: 'string-line', 'stroke-width': fixed(s.weight) }),
    h('text', { x: fixed(m.labelX), y: fixed(s.y), class: 'string-name', text: s.name })))),
  h('rect', { class: 'window-box', x: fixed(m.box.x0), y: fixed(m.box.y0), width: fixed(m.box.x1 - m.box.x0),
    height: fixed(m.box.y1 - m.box.y0), rx: 3, data: { first: m.box.first, last: m.box.last } }),
  h('g', { class: 'fret-numbers' }, NECK_FRET_NUMBERS.filter((f) => f <= m.frets).map((f) => h('text', {
    x: fixed(m.slots[f].cx), y: fixed(m.numbersY), class: ['fret-number', f >= m.box.first && f <= m.box.last && 'shown'], text: String(f) }))),
  h('g', { class: 'rings' }, rings.map((p) => h('circle', { ...cxy(at(p)), r: NECK.dot - 1, class: 'ring',
    stroke: pcColour(p.note % 12), data: { string: neck.strings[p.k].string, fret: p.fret, note: p.note } },
  h('title', { text: `${spelledName(harmony, p.note)}: string ${neck.strings[p.k].string}, fret ${p.fret}` })))),
  h('g', { class: 'dots' }, dots.map((p) => h('g', { class: 'played', data: { string: neck.strings[p.k].string, fret: p.fret, note: p.note } },
    h('title', { text: `${spelledName(harmony, p.note)}: played on string ${neck.strings[p.k].string}, fret ${p.fret}` }),
    h('circle', { ...cxy(at(p)), r: NECK.dot, fill: pcColour(p.note % 12) }),
    h('text', { x: at(p).x, y: at(p).y, class: 'dot-name', text: spelledName(harmony, p.note) })))));
}

const cxy = (p) => ({ cx: p.x, cy: p.y });

export const NECK_LEGEND = 'box: the frets on the pads · dot: played on that string · ring: the same pitch elsewhere';

export const CAPTIONS = {
  pads: 'Pads',
  grid: 'Pads: the layout as played',
  circle: 'Circle of fifths · relative minors inside',
  lattice: 'Tonnetz: → fifths · ↗ major thirds · ↖ minor thirds; ▲ major · ▼ minor',
  neck: 'Neck: strings as on the unit, highest on top',
};

const figure = (area, caption, view, cls) => h('figure', { class: ['view', cls], data: { area } },
  h('figcaption', { text: CAPTIONS[caption] }), view);

// The main view of the layout: the Tonnetz, the neck or the large pad grid (mainViewKind).
export function mainView(harmony, { kind = 'pads', grid = null, flip = false } = {}) {
  if (kind === 'tonnetz') return figure('main', 'lattice', latticeView(harmony), 'lattice-view');
  if (kind === 'neck') {
    return figure('main', 'neck', [neckView(grid?.neck, harmony, { flip }),
      h('div', { class: 'legend muted', text: NECK_LEGEND })], 'neck-view');
  }
  return figure('main', 'grid', padGridView(grid, harmony), 'grid-view');
}

const withReplica = (kind) => kind === 'tonnetz' || kind === 'neck';

// The panel's Harmony section: the chord rows, the main view, then the circle (and, beside the Tonnetz and the neck,
// the small pad replica; the pad grid is the pads already).
export function harmonyView(harmony, parts = {}) {
  const kind = parts.kind ?? 'pads';
  return h('div', { class: 'harmony', data: { main: kind } },
    chordView(harmony, { onClearTrail: parts.onClearTrail }),
    mainView(harmony, { ...parts, kind }),
    h('div', { class: 'harmony-grid' },
      figure('circle', 'circle', circleView(harmony), 'circle-view'),
      withReplica(kind) ? figure('pads', 'pads', padReplicaView(parts.grid, harmony), 'replica-view') : null));
}

// The full view (?view=harmony, or Full screen): the same views, each in its own area of one grid (lab.css
// .full-views places them by data-area and by the main view's kind: wide screens put the main view and the circle
// side by side, narrow ones stack them). The SVGs keep their viewBox and scale to their area, so they stay sharp.
export function fullAreas(kind) {
  return withReplica(kind) ? ['chord', 'pads', 'main', 'circle', 'hints'] : ['chord', 'main', 'circle', 'hints'];
}

export function harmonyFullView(harmony, parts = {}) {
  const kind = parts.kind ?? 'pads';
  const areas = {
    chord: () => h('section', { class: 'chord-block full-chord', data: { area: 'chord' }, 'aria-label': 'Chord and trail' },
      chordRows(harmony, { onClearTrail: parts.onClearTrail })),
    pads: () => figure('pads', 'pads', padReplicaView(parts.grid, harmony), 'replica-view'),
    main: () => mainView(harmony, { ...parts, kind }),
    circle: () => figure('circle', 'circle', circleView(harmony), 'circle-view'),
    hints: () => h('section', { class: 'chord-block full-hints', data: { area: 'hints' }, 'aria-label': 'Hints' }, hintRows(harmony)),
  };
  return h('div', { class: 'full-views', data: { main: kind } }, fullAreas(kind).map((area) => areas[area]()));
}
