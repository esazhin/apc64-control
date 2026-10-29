// The performer's pattern editor (contract 2 §2.10, Phase 2): the Lab panel's grid made editable, FL-style. A click
// on a cell cycles . → x → X (accent) → .; the strum row . → d → u; a string's checkbox makes it manual (passed
// through as played). The pattern's meter, step, length, swing, spread, play mode, name and description are edited
// beside it. Every edit plays at once (POST /api/lab/performer {pattern_data, edits: the id it edits, null for a new
// one}, from the next step, no restart) and is kept by the service, unsaved, per pattern for the session: choosing
// another pattern (here, a slot, the unit's slot pad) and coming back plays and shows the edit again, marked ●. Save
// writes it (POST /api/lab/patterns/save, validated by the service; the base hash goes back, so a file changed on
// disk is refused), Revert drops it. New, Duplicate, Save as and Delete; Delete, and a New that would replace the
// session's kept new pattern, ask in the panel's own overlay, never a browser dialog.
//
// The draft is plain data (draftOf, draftData and the edits are pure, tested under node); the view draws it, and it
// follows the service (lab.js followPerformer: a change of the pattern playing made elsewhere rebuilds it). The
// playhead is not part of the drawing: markPlayhead lights the playing column on the drawn cells at every step, so
// a click, a focused field and the layout stay put while the pattern plays.
import { h } from './lab_dom.js';

export const STEPS = ['1/4', '1/8', '1/16', '1/8t', '1/16t'];
export const STEP_FRACTION = { '1/4': 1 / 4, '1/8': 1 / 8, '1/16': 1 / 16, '1/8t': 1 / 12, '1/16t': 1 / 24 };
export const METERS = ['2/4', '3/4', '4/4', '5/4', '6/4', '3/8', '6/8', '7/8', '9/8', '12/8'];
export const MAX_LENGTH = 32;
export const RELATIVE = ['R', 'A'];
const CELL_NEXT = { '.': 'x', x: 'X', X: '.' };
const STRUM_NEXT = { '.': 'd', d: 'u', u: '.' };
const MARK = { '.': '', x: '●', X: '◉', d: '↓', u: '↑' };
const DEFAULTS = { meter: '4/4', step: '1/8', length: 8, swing: 50, spread: 15, play: 'all', gate: 'ring',
  velocity: { hit: 100, accent: 127 }, humanize: { timing: 0, velocity: 0 } };

export const rowCells = (text) => [...String(text ?? '')].filter((c) => c.trim() && c !== '|');

function fit(cells, length, blank = '.') {
  const out = cells.slice(0, length);
  while (out.length < length) out.push(blank);
  return out;
}

// --- the draft: plain data ------------------------------------------------------------------------------------
// A pattern as the state shows it (its canonical `data`) → the draft the editor changes.
export function draftOf(pattern, extra = {}) {
  const data = pattern?.data ?? {};
  const length = Number(data.length ?? DEFAULTS.length);
  const lanes = {};
  for (const [key, row] of Object.entries(data.lanes ?? {})) lanes[key] = fit(rowCells(row), length);
  return {
    id: pattern?.id ?? null, base: pattern?.hash ?? null, name: data.name ?? 'New pattern',
    description: data.description ?? '', meter: data.meter ?? DEFAULTS.meter, step: data.step ?? DEFAULTS.step,
    length, swing: Number(data.swing ?? DEFAULTS.swing), spread: Number(data.spread ?? DEFAULTS.spread),
    play: data.play ?? DEFAULTS.play, gate: data.gate ?? DEFAULTS.gate, velocity: { ...(data.velocity ?? DEFAULTS.velocity) },
    humanize: { ...(data.humanize ?? DEFAULTS.humanize) }, manual: [...(data.manual ?? [])].map(Number),
    lanes, strum: data.strum ? fit(rowCells(data.strum).map((c) => c.toLowerCase()), length) : null,
    dirty: Boolean(pattern?.edited), issues: [], ...extra,
  };
}

export function blankDraft() {
  return draftOf(null, { name: 'New pattern', dirty: true });
}

// Steps in a bar and in a beat of the meter (null when the step does not divide them).
export function barSteps(d) { return wholeSteps(d, 'bar'); }
export function beatSteps(d) { return wholeSteps(d, 'beat'); }

function wholeSteps(d, what) {
  const [beats, unit] = String(d.meter ?? '4/4').split('/').map(Number);
  const step = STEP_FRACTION[d.step];
  if (!beats || !unit || !step) return null;
  const steps = (what === 'bar' ? beats / unit : 1 / unit) / step;
  return Math.abs(steps - Math.round(steps)) < 1e-9 && Math.round(steps) > 0 ? Math.round(steps) : null;
}

export function rowText(cells, bar) {
  return cells.map((c, k) => (k && bar && k % bar === 0 ? `| ${c}` : c)).join(' ');
}

// The draft as pattern data (docs/performer-format.md): lanes without a hit and manual lanes have no row; the strum
// row (and its spread) only when it marks a step.
export function draftData(d) {
  const bar = barSteps(d);
  const shown = bar && bar < d.length ? bar : null;
  const lanes = {};
  for (const [key, cells] of Object.entries(d.lanes)) {
    if (d.manual.includes(Number(key)) || !cells.some((c) => c !== '.')) continue;
    lanes[key] = rowText(cells, shown);
  }
  const data = { format: 1, name: d.name, meter: d.meter, step: d.step, length: d.length, lanes,
    swing: Number(d.swing), play: d.play, gate: d.gate, velocity: d.velocity, humanize: d.humanize,
    manual: [...d.manual].sort((a, b) => a - b) };
  if (d.description) data.description = d.description;
  if (d.strum?.some((c) => c !== '.')) {
    data.strum = rowText(d.strum, shown);
    data.spread = Number(d.spread);
  }
  return data;
}

// --- the edits (each answers a new draft, marked unsaved) -------------------------------------------------------
const edited = (d, patch) => ({ ...d, notice: null, ...patch, dirty: true });

export function cycleCell(d, lane, k) {
  const key = String(lane);
  const cells = fit(d.lanes[key] ?? [], d.length);
  cells[k] = CELL_NEXT[cells[k]] ?? 'x';
  return edited(d, { lanes: { ...d.lanes, [key]: cells } });
}

export function cycleStrum(d, k) {
  const strum = fit(d.strum ?? [], d.length);
  strum[k] = STRUM_NEXT[strum[k]] ?? 'd';
  return edited(d, { strum });
}

export function toggleManual(d, lane) {
  const n = Number(lane);
  if (d.manual.includes(n)) return edited(d, { manual: d.manual.filter((m) => m !== n) });
  const lanes = { ...d.lanes };
  delete lanes[String(n)];                                    // a manual string has no row
  return edited(d, { manual: [...d.manual, n].sort((a, b) => a - b), lanes });
}

// A changed step re-grids the pattern (FL-style): its duration and every hit's time are kept. The new length is the
// duration in new steps (rounded to a whole number when it does not divide, and said), cut to 32 steps (and said, with
// the hits dropped); each hit moves to the step at its time, or to the nearest one when it falls between (a tie: the
// earlier); hits landing on one step merge (an accent wins; on the strum row the first mark stays). `notice` says
// what moved, merged, was rounded or cut.
export function regrid(d, step) {
  const from = STEP_FRACTION[d.step];
  const to = STEP_FRACTION[step];
  if (!from || !to || step === d.step) return edited(d, { step });
  const exact = (d.length * from) / to;
  const whole = Math.abs(exact - Math.round(exact)) < 1e-9;
  const rounded = Math.max(1, Math.round(exact));
  const length = Math.min(MAX_LENGTH, rounded);
  let moved = 0;
  let merged = 0;
  let dropped = 0;
  const place = (row, keep) => {
    const out = Array(length).fill('.');
    row.forEach((mark, k) => {
      if (mark === '.') return;
      const at = (k * from) / to;
      const near = Math.abs(at - Math.round(at)) < 1e-9 ? Math.round(at) : Math.ceil(at - 0.5);
      if (near >= length) { dropped += 1; return; }
      if (Math.abs(at - near) > 1e-9) moved += 1;
      if (out[near] === '.') out[near] = mark;
      else { merged += 1; out[near] = keep(out[near], mark); }
    });
    return out;
  };
  const lanes = Object.fromEntries(Object.entries(d.lanes).map(([key, row]) => [key, place(fit(row, d.length),
    (a, b) => (a === 'X' || b === 'X' ? 'X' : 'x'))]));
  const strum = d.strum ? place(fit(d.strum, d.length), (a) => a) : null;
  const notes = [];
  if (moved) notes.push(`${moved} hit${moved > 1 ? 's' : ''} between the new steps moved to the nearest step`);
  if (merged) notes.push(`${merged} cell${merged > 1 ? 's' : ''} kept one of two hits (an accent wins)`);
  if (!whole) {
    notes.push(`${d.length} steps of ${d.step} (${barsText(d.length * from, d.meter)}) are not a whole number of `
      + `${step} steps: now ${rounded} (${barsText(rounded * to, d.meter)})`);
  }
  if (rounded > MAX_LENGTH) {
    notes.push(`cut to ${MAX_LENGTH} steps: ${barsText(MAX_LENGTH * to, d.meter, true)} of ${step}`
      + (dropped ? `; ${dropped} hit${dropped > 1 ? 's' : ''} after them ${dropped > 1 ? 'were' : 'was'} dropped` : ''));
  } else if (dropped) {
    notes.push(`${dropped} hit${dropped > 1 ? 's' : ''} past the new end ${dropped > 1 ? 'were' : 'was'} dropped`);
  }
  return edited(d, { step, length, lanes, strum, notice: notes.length ? notes.join('; ') : null });
}

// How long `wholes` (a duration in whole notes) is in bars of the meter: '1 bar', '1 ½ bars', '⅜ bar', '5/12 bar'.
const GLYPHS = { '1/2': '½', '1/3': '⅓', '2/3': '⅔', '1/4': '¼', '3/4': '¾', '1/6': '⅙', '5/6': '⅚', '1/8': '⅛',
  '3/8': '⅜', '5/8': '⅝', '7/8': '⅞' };
function barsText(wholes, meter = '4/4', bare = false) {
  const [beats, unit] = String(meter).split('/').map(Number);
  const bars = wholes / ((beats || 4) / (unit || 4));
  let whole = Math.floor(bars + 1e-9);
  let rest = bars - whole;
  let fraction = '';
  if (rest > 1e-9) {
    const denominator = [2, 3, 4, 6, 8, 12, 16, 24, 32].find((n) => Math.abs(rest * n - Math.round(rest * n)) < 1e-6);
    if (denominator) {
      const numerator = Math.round(rest * denominator);
      const g = gcd(numerator, denominator);
      const key = `${numerator / g}/${denominator / g}`;
      fraction = GLYPHS[key] ?? key;
    } else {
      return `${bars.toFixed(2)} bars`;
    }
  }
  const text = [whole ? String(whole) : '', fraction].filter(Boolean).join(' ');
  if (bare && !fraction) return `${whole} bar${whole === 1 ? '' : 's'}`;
  return `${text} bar${bars > 1 + 1e-9 ? 's' : ''}`;
}

function gcd(a, b) { return b ? gcd(b, a % b) : a; }

// The pattern's length and its duration in the meter: '8 steps = 1 bar', '12 steps = 1 ½ bars'.
export function durationText(d) {
  const step = STEP_FRACTION[d.step];
  return step ? `${d.length} steps = ${barsText(d.length * step, d.meter)}` : `${d.length} steps`;
}

export function setField(d, field, value) {
  if (field === 'step') return regrid(d, value);
  if (field === 'length') {
    const length = Math.max(1, Math.min(MAX_LENGTH, Math.round(Number(value) || d.length)));
    const lanes = Object.fromEntries(Object.entries(d.lanes).map(([k, cells]) => [k, fit(cells, length)]));
    return edited(d, { length, lanes, strum: d.strum ? fit(d.strum, length) : null });
  }
  if (field === 'swing' || field === 'spread') return edited(d, { [field]: Number(value) });
  if (field === 'name' || field === 'description') return edited(d, { [field]: String(value).trim() });
  return edited(d, { [field]: value });
}

// A file name for a pattern's name, as the service makes one ('Travis pick 2' → 'travis-pick-2').
export function idFor(name) {
  const slug = String(name ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)
    .replace(/-+$/g, '');
  return slug || 'pattern';
}

// --- drawing ---------------------------------------------------------------------------------------------------
const button = (text, onclick, extra = {}) => h('button', { type: 'button', onclick, ...extra }, text);

// The issue of a field ('lane 2', 'name', 'length' …) from the service's answer, if any.
function issueOf(d, field) {
  return (d.issues ?? []).find((i) => i.field === field) ?? null;
}

function lineClass(d, k) {
  const bar = barSteps(d);
  const beat = beatSteps(d);
  if (k && bar && k % bar === 0) return 'bar';
  if (k && beat && k % beat === 0) return 'beat';
  return null;
}

// The editor under the performer's controls: the toolbar, the pattern's fields, the issues and the grid.
// `large`: the sequencer view's grid, its cells filling the width (32 steps at most), readable from a distance.
export function patternEditor(p, view, actions, { large = false } = {}) {
  const pattern = p.pattern;
  const d = view.draft ?? draftOf(pattern);
  const typing = view.typing ?? {};
  const strings = p.addressing === 'strings';
  const labels = new Map((p.lanes ?? []).map((lane) => [String(lane.lane), lane.label]));
  const lanes = (p.lanes ?? []).map((lane) => String(lane.lane));
  for (const key of Object.keys(d.lanes)) if (!lanes.includes(key)) lanes.splice(lanes.length - RELATIVE.length, 0, key);
  const steps = Array.from({ length: d.length }, (_, k) => k);
  const beat = beatSteps(d) ?? 1;
  const cell = (k, extra = []) => [lineClass(d, k), ...extra];
  const field = (name, input) => h('label', { class: ['pe-field', issueOf(d, name) && 'bad'], title: issueOf(d, name)?.text },
    `${name} `, input);
  const commit = (name) => (e) => actions.editPattern(pattern, (draft) => setField(draft, name, e.target.value));
  const text = (name) => h('input', { type: 'text', value: typing[name] ?? d[name] ?? '', size: name === 'name' ? 14 : 22,
    data: { field: `pattern-${name}` }, maxlength: name === 'name' ? 40 : 200,
    oninput: (e) => actions.typePattern(name, e.target.value), onchange: commit(name),
    onkeydown: (e) => { if (e.key === 'Enter') commit(name)(e); } });
  const number = (name, min, max) => h('input', { type: 'number', min, max, step: 1, value: String(d[name]),
    data: { field: `pattern-${name}` }, onchange: commit(name), class: 'pe-number' });
  const select = (name, options) => h('select', { data: { field: `pattern-${name}` }, onchange: commit(name) },
    [...new Set([...options, d[name]])].map((o) => h('option', { value: o, selected: o === d[name], text: o })));
  const saveAs = view.saveAs;
  return h('div', { class: ['pattern-editor', large && 'large'], data: { part: 'pattern-editor' } },
    h('div', { class: 'pe-toolbar row' },
      button('New', () => actions.newPattern(p), { data: { action: 'pattern-new' }, title: 'a new, empty pattern' }),
      button('Duplicate', () => actions.duplicatePattern(pattern, p), { data: { action: 'pattern-duplicate' },
        title: 'a copy of this pattern, unsaved until Save' }),
      button('Save', () => actions.savePattern(pattern), { class: [d.dirty && 'primary'], data: { action: 'pattern-save' },
        disabled: !d.dirty, title: d.id ? `write patterns/${d.id}.yaml` : 'choose a file name and write it' }),
      button('Save as', () => actions.saveAsPattern(pattern), { data: { action: 'pattern-save-as' },
        title: 'write it under another file name' }),
      button('Delete', () => actions.deletePattern(pattern), { data: { action: 'pattern-delete' }, disabled: !d.id,
        title: d.id ? `delete patterns/${d.id}.yaml (a copy is kept)` : 'not saved yet' }),
      h('span', { class: ['pe-state', d.dirty ? 'dirty' : 'clean'], data: { part: 'pattern-state' },
        text: d.dirty ? `● unsaved${d.id ? ` · ${d.id}.yaml` : ' · new'}` : (d.id ? `${d.id}.yaml` : '') }),
      d.dirty && d.id ? button('Revert', () => actions.revertPattern(d.id), { class: 'link', data: { action: 'pattern-revert' },
        title: 'drop the unsaved edit: play the file again' }) : null),
    saveAs ? h('div', { class: 'pe-save-as row', data: { part: 'pattern-save-as' } },
      h('label', {}, 'file name ', h('input', { type: 'text', value: saveAs.id, size: 18, data: { field: 'pattern-file' },
        oninput: (e) => actions.typeSaveAs(e.target.value),
        onkeydown: (e) => { if (e.key === 'Enter') actions.confirmSaveAs(); } }), '.yaml'),
      button('Save', () => actions.confirmSaveAs(), { class: 'primary', data: { action: 'pattern-save-as-ok' } }),
      button('Cancel', () => actions.cancelSaveAs(), { data: { action: 'pattern-save-as-cancel' } })) : null,
    h('div', { class: 'pe-fields row' },
      field('name', text('name')), field('meter', select('meter', METERS)), field('step', select('step', STEPS)),
      field('length', number('length', 1, MAX_LENGTH)),
      h('span', { class: 'muted small pe-duration', data: { part: 'pattern-duration' }, text: `= ${durationText(d).split(' = ')[1] ?? ''}` }),
      field('swing', number('swing', 50, 75)),
      field('spread', number('spread', 0, 100)),
      field('play', h('select', { data: { field: 'pattern-play' }, onchange: commit('play'),
        title: 'all: an unpressed string rings open (not below the chord\'s root); pressed: only pressed strings' },
      ['all', 'pressed'].map((o) => h('option', { value: o, selected: o === d.play, text: o })))),
      field('description', text('description'))),
    d.notice ? h('div', { class: 'pe-notice small', data: { part: 'pattern-notice' }, text: d.notice }) : null,
    (d.issues ?? []).length ? h('ul', { class: 'pe-issues', data: { part: 'pattern-issues' } },
      d.issues.map((i) => h('li', { class: i.severity === 'warning' ? 'warn' : 'bad', text: i.text ?? i.problem }))) : null,
    h('div', { class: 'pe-scroll' },
      h('table', { class: ['pattern-grid', 'editable', large && 'large'], data: { part: 'pattern-grid' },
        style: large ? { '--steps': String(d.length) } : { minWidth: `calc(7em + ${d.length * 14}px)` },
        'aria-label': `${d.name}: ${d.meter}, ${d.step} steps` },
      h('tr', {}, h('th', { class: 'pe-head' }), steps.map((k) => h('th', { class: cell(k), data: { step: k },
        text: k % beat === 0 ? String(k + 1) : '' }))),
      lanes.map((key) => {
        const numbered = !RELATIVE.includes(key);
        const manual = numbered && d.manual.includes(Number(key));
        const cells = fit(d.lanes[key] ?? [], d.length);
        const bad = issueOf(d, `lane ${key}`);
        return h('tr', { class: [manual && 'manual', bad && 'bad', !numbered && 'relative'], data: { lane: key },
          title: bad?.text },
        h('th', { class: 'pe-head' },
          numbered && strings ? h('input', { type: 'checkbox', checked: manual, data: { manual: key },
            title: manual ? 'manual: played as you press; click to give it to the pattern'
              : 'click to play this string by hand (manual: passed through as played)',
            onchange: () => actions.editPattern(pattern, (draft) => toggleManual(draft, key)) }) : null,
          h('span', { text: labels.get(key) ?? (numbered ? `lane ${key}` : key) })),
        manual ? h('td', { class: 'manual-note', colspan: d.length, text: 'manual: played as you press' })
          : steps.map((k) => h('td', { class: cell(k, [cells[k] === 'X' && 'accent', cells[k] === 'x' && 'hit']),
            data: { step: k, cell: cells[k] }, onclick: () => actions.editPattern(pattern, (draft) => cycleCell(draft, key, k)),
            text: MARK[cells[k]] ?? '' })));
      }),
      h('tr', { class: ['strum', issueOf(d, 'strum') && 'bad'], data: { lane: 'strum' } },
        h('th', { class: 'pe-head', title: 'd: down (low to high strings), u: up, spread ms apart' }, h('span', { text: 'strum' })),
        steps.map((k) => {
          const mark = d.strum?.[k] ?? '.';
          return h('td', { class: cell(k), data: { step: k, strum: mark },
            onclick: () => actions.editPattern(pattern, (draft) => cycleStrum(draft, k)), text: MARK[mark] ?? '' });
        })))),
    h('div', { class: 'muted small', text: 'click a cell: · → ● hit → ◉ accent; the strum row: ↓ down → ↑ up; the box: a manual '
      + 'string. R is the chord\'s root string, A its alternate bass. A new step keeps the pattern\'s duration and every '
      + 'hit\'s time (1/8 → 1/16: twice the cells; a hit between the new steps moves to the nearest). '
      + 'Edits play from the next step and are kept, unsaved, '
      + 'per pattern while you choose others (● in the list and on the slots) until Save writes the file or Revert drops '
      + 'them; they last while the service runs (a restart drops them).' }));
}

// The panel's own overlay (the host's help-card look): Delete, and a New (or Duplicate) that would replace the
// session's kept new pattern (the one pattern without a file: its edits have nowhere else to be kept).
export function patternConfirmView(view, actions) {
  const c = view.patternConfirm;
  if (!c) return [];
  const text = c.kind === 'delete'
    ? `Delete patterns/${c.id}.yaml (${c.name})? The service keeps a copy (apc64 lab pattern-versions ${c.id}).`
    : `“${c.name}” is a new pattern, not saved yet, and the service keeps one new pattern. Start another in its place? `
      + '(Choose it in the list and Save it first to keep it.)';
  return [
    h('div', { class: 'help-backdrop', data: { confirm: 'backdrop' }, onclick: () => actions.cancelPatternConfirm() }),
    h('div', { class: 'help-card pe-confirm', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'pe-confirm-title',
      data: { part: 'pattern-confirm' } },
    h('div', { class: 'help-head' }, h('h2', { id: 'pe-confirm-title', text: c.kind === 'delete' ? 'Delete pattern' : 'Unsaved new pattern' })),
    h('p', { text }),
    h('div', { class: 'row' },
      button(c.kind === 'delete' ? 'Delete' : 'Start another', () => actions.confirmPattern(), { class: 'primary',
        data: { action: 'pattern-confirm-ok' } }),
      button(c.kind === 'delete' ? 'Cancel' : 'Keep it', () => actions.cancelPatternConfirm(),
        { data: { action: 'pattern-confirm-cancel' } }))),
  ];
}

// --- the playhead: the playing column lit on the drawn cells (no redraw) ---------------------------------------
function each(el, fn) {
  for (const child of el?.children ?? []) {
    fn(child);
    each(child, fn);
  }
}

export function markPlayhead(container, p, status = null) {
  if (!container) return;
  const playing = p?.running && p.step ? p.step - 1 : -1;
  each(container, (el) => {
    if (el.dataset?.step !== undefined) el.classList.toggle('now', Number(el.dataset.step) === playing);
    else if (status && el.dataset?.part === 'performer-status') el.textContent = status;
  });
}
