// The harmony views (contract pi7; inv15, inv16, inv17; A68–A80): pure functions from the service's HarmonyState
// (GET /api/lab/harmony, the ws 'lab' topic kind 'harmony') to h() trees. Every name, chord and hint comes from
// the server's harmony core (its spelling, §2.7 a25); this file only places them: the pad replica, the
// Tonnetz lattice with its triads, the chord and its trail, the interval and neighbour hints, the circle of fifths.
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
  const hintLabels = new Map((harmony?.hints ?? []).map((t) => [triadKey(t), t.label]));
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
    text: (litIds.has(t.id) ? (harmony.triads.find((x) => triadKey(x) === t.key)?.label)
      : neighbourIds.has(t.id) ? harmony.neighbours.find((x) => triadKey(x) === t.key)?.label
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
      h('text', { x: fixed(n.x), y: fixed(degree ? n.y - 2.5 : n.y), class: 'node-name', text: NOTE_NAMES[n.pc] }),
      degree ? h('text', { x: fixed(n.x), y: fixed(n.y + 4.5), class: 'node-degree', text: degree }) : null);
  })));
}

// --- the circle of fifths (d60): C at the top, held pitch classes joined in circle order ----------------------
export function circlePosition(pc, radius = 92) {
  const a = ((fifthsIndex(pc) * 30 - 90) * Math.PI) / 180;
  return { x: radius * Math.cos(a), y: radius * Math.sin(a) };
}

export function circleView(harmony) {
  const pcs = heldPcs(harmony);
  const order = (harmony?.circle ?? []).map(pcOfName).filter((pc) => pc >= 0);
  const ring = order.map((pc) => circlePosition(pc));
  return h('svg', { class: 'circle', viewBox: '-112 -112 224 224', role: 'img', 'aria-label': 'Circle of fifths' },
    h('circle', { cx: 0, cy: 0, r: 92, class: 'ring' }),
    ring.length > 1 ? h('polygon', { class: 'joined', points: pointsOf(ring) }) : null,
    Array.from({ length: 12 }, (_, k) => {
      const pc = mod(k * 7, 12);
      const p = circlePosition(pc);
      return h('g', { class: ['fifth', pcs.has(pc) && 'held'], data: { pc } },
        h('circle', { cx: fixed(p.x), cy: fixed(p.y), r: 14, fill: pcColour(pc) }),
        h('text', { x: fixed(p.x), y: fixed(p.y), text: NOTE_NAMES[pc] }));
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
    const from = NOTE_NAMES[pc];
    const intervals = Object.entries(harmony.degrees).filter(([name]) => name !== from)
      .map(([name, label]) => `${name} ${label}`);
    hints.intervals = [`intervals from ${from}: `, intervals.join(' · ')];
    if ((harmony.hints ?? []).length) hints.contains = [`chords with ${from}: `, harmony.hints.map((t) => t.label).join(', ')];
  }
  if ((harmony?.neighbours ?? []).length) {
    hints.neighbours = ['neighbouring triads (P, R, L): ', harmony.neighbours.map((t) => t.label).join(', ')];
  }
  return hints;
}

export function chordView(harmony) {
  const held = harmony?.held ?? [];
  const hints = hintTexts(harmony);
  const names = held.map((n) => n.name).join(' ');
  return h('div', { class: 'chord-block' },
    h('div', { class: 'chord-row' },
      h('span', { class: 'chord', data: { chord: harmony?.chord ?? NO_CHORD }, text: harmony?.chord || NO_CHORD }),
      h('span', { class: 'held-names', title: names, text: names })),
    h('div', { class: 'trail-row' }, h('span', { class: 'muted', text: 'trail: ' }),
      (harmony?.trail ?? []).length ? harmony.trail.map((label, k) => h('span', {
        class: ['trail-chord', k === harmony.trail.length - 1 && 'newest'], text: label })) : h('span', { class: 'muted', text: 'empty' })),
    HINT_ROWS.map(([key, idle]) => {
      const hint = hints[key];
      return h('div', { class: ['hint-line', !hint && 'idle'], data: { hint: key }, title: hint ? hint.join('') : idle },
        hint ? [h('span', { class: 'muted', text: hint[0] }), hint[1]] : idle);
    }));
}

// --- the pad replica: the 64 pads as written to the unit, the held notes lit (A21, A68, A80) ----------------
// `pads` is LabState.active.pads ([{pad: 'r1c1', note, rest, silent}]): exact RGB as written, no approximate mark.
// Without a generated layout, `fallback` gives the host replica's palette colours, marked approximate (inv17).
export function padReplicaView(pads, harmony, fallback = null) {
  const notes = heldNotes(harmony);
  const exact = Array.isArray(pads) && pads.length === 64;
  const byPad = new Map((exact ? pads : []).map((p) => [p.pad, p]));
  const rows = [];
  for (let row = 8; row >= 1; row--) {
    for (let column = 1; column <= 8; column++) {
      const id = `r${row}c${column}`;
      if (exact) {
        const pad = byPad.get(id);
        const silent = !pad || pad.silent;
        rows.push(h('div', {
          class: ['lab-pad', silent && 'silent', !silent && notes.has(pad.note) && 'held'],
          data: { pad: id, note: silent ? '' : pad.note, rgb: silent ? '' : pad.rest },
          style: silent ? {} : { background: pad.rest },
          title: silent ? `${id}: silent` : `${id}: note ${pad.note}, ${pad.rest}`,
        }));
      } else {
        const rgb = fallback?.(`pad ${id}`) ?? null;
        rows.push(h('div', { class: ['lab-pad', 'approx', !rgb && 'silent'], data: { pad: id, rgb: rgb ?? '' },
          style: rgb ? { background: rgb } : {}, title: rgb ? `${id}: ${rgb} (approximate palette colour)` : id }));
      }
    }
  }
  return h('div', { class: 'replica-block' },
    h('div', { class: 'lab-pads' }, rows),
    h('div', { class: 'legend muted', text: exact ? 'colours as written to the unit'
      : '≈ approximate colours (Ableton palette): no generated layout is active' }));
}

export function harmonyView(harmony, pads, fallback) {
  return h('div', { class: 'harmony' },
    chordView(harmony),
    h('div', { class: 'harmony-grid' },
      h('figure', { class: 'view replica-view' }, h('figcaption', { text: 'Pads' }), padReplicaView(pads, harmony, fallback)),
      h('figure', { class: 'view circle-view' }, h('figcaption', { text: 'Circle of fifths' }), circleView(harmony))),
    h('figure', { class: 'view lattice-view' },
      h('figcaption', { text: 'Tonnetz: → fifths · ↗ major thirds · ↖ minor thirds; ▲ major · ▼ minor' }),
      latticeView(harmony)));
}
