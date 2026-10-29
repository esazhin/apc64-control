// The pattern editor (contract 2 §2.10, Phase 2): the draft as plain data, the edits, the editor's calls and the
// playhead marked without a redraw. Runs under node --test, no browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { FakeDocument, FakeElement } from '../../../_apc64_host/presentation/static/fake_dom.js';
import { SEQUENCER_ADDRESS, SEQUENCER_VIEW, createLab, mountPanel, performerView, sequencerFullPart } from './lab.js';
import { byData, findAll, hasClass, textOf } from './lab_dom.js';
import {
  barSteps, beatSteps, blankDraft, cycleCell, cycleStrum, draftData, draftOf, durationText, idFor, markPlayhead, setField,
  toggleManual,
} from './performer_editor.js';

// the performer's state as the real service answered it: the waltz playing at step 2, idle, and an Am7 voiced
const PERFORMER = JSON.parse(readFileSync(new URL('./performer.fixture.json', import.meta.url)));
const WALTZ = PERFORMER.playing.pattern;

function fakeApi(answers = {}) {
  const calls = [];
  let revision = PERFORMER.playing.pattern_revision;
  return {
    calls,
    async call(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      const answer = answers[`${method} ${path}`];
      if (typeof answer === 'function') return answer(body);
      if (answer) return answer;
      if (method === 'GET' && path === '/api/ports') return { ok: true, status: 200, data: [] };
      if (method === 'GET' && path !== '/api/lab/performer') return { ok: false, status: 404, problem: 'n/a', data: {} };
      if (body?.pattern_data) {                                   // the service keeps the edit: the state says so
        revision += 1;
        return { ok: true, status: 200, data: { ...PERFORMER.playing, pattern_revision: revision,
          pattern: { ...WALTZ, edited: true }, edits: [{ id: body.edits, name: body.pattern_data.name, new: body.edits === null }],
          message: 'done' } };
      }
      return { ok: true, status: 200, data: { ...PERFORMER.playing, message: 'done' } };
    },
  };
}

const model = (performer) => ({ topics: { lab: { performer } }, state: { controls: {} } });
const clicks = (tree, action) => findAll(tree, (n) => n.tag === 'button' && n.props?.data?.action === action);
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test('a pattern\'s data becomes a draft and back again, the bars and beats from its meter', () => {
  const draft = draftOf(WALTZ);
  assert.equal(draft.id, 'waltz');
  assert.equal(draft.base, WALTZ.hash);
  assert.deepEqual(draft.lanes['6'], ['X', '.', '.', '.', '.', '.']);
  assert.deepEqual(draft.strum, ['.', 'd', 'd', '.', 'd', 'd']);
  assert.deepEqual(draftData(draft), WALTZ.data);
  assert.deepEqual([barSteps(draft), beatSteps(draft)], [3, 1]);                  // 3/4 in quarters
  assert.deepEqual([barSteps({ meter: '4/4', step: '1/8' }), beatSteps({ meter: '4/4', step: '1/8' })], [8, 2]);
  assert.deepEqual([barSteps({ meter: '6/8', step: '1/16' }), beatSteps({ meter: '4/4', step: '1/8t' })], [12, 3]);
  assert.equal(barSteps({ meter: '5/8', step: '1/4' }), null);
  assert.equal(idFor('Travis pick 2!'), 'travis-pick-2');
  assert.equal(blankDraft().dirty, true);
});

test('the edits cycle cells and strums, make a string manual and fit every row to a new length', () => {
  let d = draftOf(WALTZ);
  d = cycleCell(d, 4, 0);
  assert.equal(d.lanes['4'][0], 'x');
  d = cycleCell(cycleCell(d, 4, 0), 4, 0);
  assert.equal(d.lanes['4'][0], '.');                                            // . → x → X → .
  d = cycleStrum(cycleStrum(d, 0), 0);
  assert.equal(d.strum[0], 'u');                                                 // . → d → u
  d = toggleManual(d, 6);
  assert.deepEqual([d.manual, d.lanes['6']], [[6], undefined]);
  assert.equal(draftData(d).lanes['6'], undefined);
  d = setField(d, 'length', 9);
  assert.deepEqual(d.lanes['1'].length, 9);
  assert.equal(draftData(d).lanes['1'], '. x x | . x x | . . .');
  d = cycleCell(d, 'R', 8);
  assert.equal(draftData(d).lanes.R, '. . . | . . . | . . x');
  assert.equal(d.dirty, true);
  assert.equal(setField(d, 'length', 99).length, 32);
});

test('a click on a cell plays the edited pattern at once and marks it unsaved; Save writes it on its base', async () => {
  const api = fakeApi();
  const lab = createLab({ api });
  const tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  const cell = findAll(tree, (n) => n.tag === 'td' && n.props?.data?.cell === '.' && n.props.data.step === 0)[0];
  await cell.props.onclick();
  const [method, path, body] = api.calls[0];
  assert.deepEqual([method, path], ['POST', '/api/lab/performer']);
  assert.equal(body.pattern_data.lanes['1'], 'x x x | . x x');
  assert.equal(body.edits, 'waltz');                                               // the pattern it edits
  assert.equal(lab.view.draft.dirty, true);
  const edited = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  assert.match(textOf(byData(edited, 'part', 'pattern-state')[0]), /● unsaved · waltz\.yaml/);
  await clicks(edited, 'pattern-save')[0].props.onclick();
  assert.deepEqual(api.calls[1], ['POST', '/api/lab/patterns/save', { id: 'waltz', data: body.pattern_data, base: WALTZ.hash,
    edits: 'waltz' }]);
  assert.equal(lab.view.draft, null);
});

test('a refused edit or save shows its issues inline, by row and by field', async () => {
  const issue = (field, text) => ({ field, text, severity: 'error' });
  const api = fakeApi({
    'POST /api/lab/performer': { ok: false, status: 400, problem: 'x', data: { issues: [issue('lane 2', 'lane 2: no')] } },
    'POST /api/lab/patterns/save': { ok: false, status: 409, problem: 'patterns/waltz.yaml changed on disk since it was read',
      data: { issues: [], fix: 'reload it, then make the change again' } },
  });
  const lab = createLab({ api });
  await lab.actions.editPattern(WALTZ, (d) => cycleCell(d, 2, 0));
  let tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  assert.equal(textOf(byData(tree, 'part', 'pattern-issues')[0]), 'lane 2: no');
  assert.ok(hasClass(byData(tree, 'lane', '2')[0], 'bad'));
  await lab.actions.savePattern(WALTZ);
  tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  assert.equal(textOf(byData(tree, 'part', 'pattern-issues')[0]),
    'patterns/waltz.yaml changed on disk since it was read; reload it, then make the change again');
});

test('New, Duplicate and Save as make new files; Delete and leaving unsaved changes ask in the overlay', async () => {
  const api = fakeApi();
  const lab = createLab({ api });
  await lab.actions.duplicatePattern(WALTZ);
  assert.equal(api.calls[0][2].pattern_data.name, 'Waltz 3/4 copy');
  let tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  clicks(tree, 'pattern-save')[0].props.onclick();                                // no file yet: asks for a name
  tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  byData(tree, 'field', 'pattern-file')[0].props.oninput({ target: { value: 'waltz-two' } });
  await clicks(tree, 'pattern-save-as-ok')[0].props.onclick();
  assert.deepEqual(api.calls.at(-1).slice(0, 2), ['POST', '/api/lab/patterns/save']);
  assert.deepEqual([api.calls.at(-1)[2].id, api.calls.at(-1)[2].create, api.calls.at(-1)[2].edits], ['waltz-two', true, null]);
  // a pattern chosen with unsaved changes: no question, the service keeps them
  await lab.actions.editPattern(WALTZ, (d) => cycleCell(d, 1, 0));
  tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  await byData(tree, 'field', 'performer-pattern')[0].props.onchange({ target: { value: 'travis' } });
  assert.deepEqual(api.calls.at(-1), ['POST', '/api/lab/performer', { pattern: 'travis' }]);
  assert.equal(lab.view.draft, null);
  assert.equal(lab.view.patternConfirm, null);
  // New while the session keeps a new pattern: asked, since the service keeps one
  const keeping = { ...PERFORMER.playing, edits: [{ id: null, name: 'My pick', new: true }] };
  tree = performerView(model(keeping), lab.view, lab.actions);
  clicks(tree, 'pattern-new')[0].props.onclick();
  tree = performerView(model(keeping), lab.view, lab.actions);
  const card = byData(tree, 'part', 'pattern-confirm')[0];
  assert.ok(hasClass(card, 'help-card') && /“My pick” is a new pattern, not saved yet/.test(textOf(card)));
  await clicks(tree, 'pattern-confirm-ok')[0].props.onclick();
  assert.equal(lab.view.draft.name, 'New pattern');
  lab.actions.cancelSaveAs();
  lab.view.draft = null;
  // Delete: asked first
  tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  clicks(tree, 'pattern-delete')[0].props.onclick();
  tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  assert.match(textOf(byData(tree, 'part', 'pattern-confirm')[0]), /Delete patterns\/waltz\.yaml \(Waltz 3\/4\)\?/);
  await clicks(tree, 'pattern-confirm-ok')[0].props.onclick();
  assert.deepEqual(api.calls.at(-1), ['POST', '/api/lab/patterns/delete', { id: 'waltz', base: WALTZ.hash }]);
  // New: a blank draft, nothing sent until its first edit
  const before = api.calls.length;
  lab.actions.newPattern();
  assert.equal(lab.view.draft.name, 'New pattern');
  assert.equal(api.calls.length, before);
});

test('the chord types and the slots show the selection and send it', async () => {
  const api = fakeApi();
  const lab = createLab({ api });
  const tree = performerView(model(PERFORMER.voiced), lab.view, lab.actions);
  const on = findAll(tree, (n) => n.tag === 'button' && hasClass(n, 'type-btn') && hasClass(n, 'on'));
  assert.deepEqual(on.map(textOf), ['m7']);
  assert.equal(textOf(byData(tree, 'part', 'voicing')[0]), 'Am7 x02010');
  assert.deepEqual(findAll(tree, (n) => hasClass(n, 'slot-btn')).map(textOf), ['1 1-2-3 + bass', '2 Travis pick', '4 Strum d-u']);
  await findAll(tree, (n) => n.props?.data?.type === 'm7')[0].props.onclick();      // the same type again: off
  await findAll(tree, (n) => n.props?.data?.slot === 4)[0].props.onclick();
  assert.deepEqual(api.calls, [['POST', '/api/lab/performer', { chord_type: null }],
    ['POST', '/api/lab/performer', { slot: 4 }]]);
});

test('a step moves the lit column on the drawn grid and redraws nothing', async () => {
  const doc = new FakeDocument();
  let performer = PERFORMER.playing;
  const store = { model: { topics: { lab: { performer } }, state: { controls: {} } }, subscribe() {} };
  const element = new FakeElement('section');
  const mounted = mountPanel(element, { store, api: fakeApi() }, { doc, schedule: () => {} });
  await mounted.ready;
  mounted.render();
  const part = mounted.containers.performer;
  const grid = part.byData('part', 'pattern-grid');
  const lit = () => [...new Set(part.all((e) => e.classList.contains('now')).map((e) => e.dataset.step))];
  assert.deepEqual(lit(), ['1']);
  performer = { ...performer, step: 3 };
  store.model = { ...store.model, topics: { lab: { performer } } };
  mounted.render();
  assert.equal(part.byData('part', 'pattern-grid'), grid);                       // the same table, not a new one
  assert.deepEqual(lit(), ['2']);
  assert.match(part.byData('part', 'performer-status').textContent, /step 3\/6/);
  markPlayhead(part, { ...performer, running: false });
  assert.deepEqual(lit(), []);
  await tick();
});

test('the draft follows the service: a pattern chosen elsewhere rebuilds it, this page\'s own edits do not', async () => {
  const api = fakeApi();
  const lab = createLab({ api });
  const doc = new FakeDocument();
  let performer = PERFORMER.playing;
  const store = { model: model(performer), subscribe() {} };
  const mounted = mountPanel(new FakeElement('section'), { store, api }, { doc, schedule: () => {} });
  await mounted.ready;
  mounted.render();
  const { view, actions } = mounted.controller;
  await actions.editPattern(WALTZ, (d) => cycleCell(d, 4, 0));
  const own = view.draftRevision;
  assert.ok(own > PERFORMER.playing.pattern_revision && view.draft.dirty);
  mounted.render();                                                                // a push that lags behind: kept
  assert.ok(view.draft);
  store.model = model({ ...performer, pattern_revision: own, pattern: { ...WALTZ, edited: true } });
  mounted.render();                                                                // the push of this page's edit
  assert.ok(view.draft);
  const travis = { ...WALTZ, id: 'travis', name: 'Travis pick', edited: true, data: { ...WALTZ.data, name: 'Travis pick' } };
  performer = { ...performer, pattern_revision: own + 1, pattern: travis, edits: [{ id: 'travis', name: 'Travis pick', new: false }],
    patterns: performer.patterns.map((row) => ({ ...row, edited: row.id === 'travis' })),
    slots: performer.slots.map((slot) => (slot && slot.id === 'travis' ? { ...slot, edited: true } : slot)) };
  store.model = model(performer);                                                  // the unit's slot pad: Travis
  mounted.render();
  assert.equal(view.draft, null);
  const tree = performerView(store.model, view, actions);
  assert.match(textOf(byData(tree, 'part', 'pattern-state')[0]), /● unsaved · travis\.yaml/);   // its kept edit shows
  const options = findAll(byData(tree, 'field', 'performer-pattern')[0], (n) => n.tag === 'option').map(textOf);
  assert.ok(options.includes('● Travis pick'));
  assert.ok(findAll(tree, (n) => hasClass(n, 'slot-btn')).map(textOf).includes('2 Travis pick ●'));
  await tick();
});

test('an edit the service refuses as stale gives way to what plays now', async () => {
  const api = fakeApi({ 'POST /api/lab/performer': { ok: false, status: 409,
    problem: 'this edit is of "waltz", but "travis" plays now; the editor shows what plays now: make the edit there again',
    data: { code: 'stale', issues: [] } } });
  const lab = createLab({ api });
  await lab.actions.editPattern(WALTZ, (d) => cycleCell(d, 4, 0));
  assert.equal(lab.view.draft, null);
  assert.match(lab.view.result.text, /plays now/);
});

test('the session\'s new pattern is listed and chosen again; Revert drops an edit', async () => {
  const api = fakeApi();
  const lab = createLab({ api });
  const keeping = { ...PERFORMER.playing, edits: [{ id: null, name: 'My pick', new: true }] };
  const tree = performerView(model(keeping), lab.view, lab.actions);
  const select = byData(tree, 'field', 'performer-pattern')[0];
  assert.equal(textOf(findAll(select, (n) => n.tag === 'option').at(-1)), '● My pick (new)');
  await select.props.onchange({ target: { value: '*new' } });
  assert.deepEqual(api.calls.at(-1), ['POST', '/api/lab/performer', { new_pattern: true }]);
  assert.equal(draftOf({ ...WALTZ, edited: true }).dirty, true);                     // an edited state: unsaved
  await lab.actions.revertPattern('waltz');
  assert.deepEqual(api.calls.at(-1), ['POST', '/api/lab/performer', { revert: 'waltz' }]);
});

// --- the sequencer: the editor alone across the page (?view=sequencer) ------------------------------------------
const inSequencer = (performer, ui = {}) => ({ ...model(performer), connected: true,
  ui: { view: { name: SEQUENCER_VIEW, pinned: false }, fullscreen: false, ...ui } });

test('the Performer heading opens the sequencer on the page or in a tab of its own', async () => {
  const opened = [];
  const lab = createLab({ api: fakeApi(), page: { openView: (name, options) => opened.push([name, options]) } });
  const tree = performerView(model(PERFORMER.playing), lab.view, lab.actions);
  clicks(tree, 'sequencer-open')[0].props.onclick();
  assert.deepEqual(opened, [['sequencer', undefined]]);
  const tab = findAll(tree, (n) => n.tag === 'a' && n.props?.data?.action === 'sequencer-tab')[0];
  assert.deepEqual([tab.props.href, tab.props.target], [SEQUENCER_ADDRESS, '_blank']);
  assert.equal(new URL(SEQUENCER_ADDRESS, 'http://192.168.1.20:5058/').href, 'http://192.168.1.20:5058/?view=sequencer');
});

test('the sequencer shows the large grid with every control needed while playing; the panel steps aside', async () => {
  const calls = [];
  const lab = createLab({ api: fakeApi(), page: { closeView: () => calls.push('close'), toggleFullscreen: () => calls.push('toggle') } });
  assert.deepEqual(sequencerFullPart(model(PERFORMER.voiced), lab.view, lab.actions), []);
  const full = sequencerFullPart(inSequencer(PERFORMER.voiced), lab.view, lab.actions);
  const grid = byData(full, 'part', 'pattern-grid')[0];
  assert.ok(hasClass(grid, 'large') && grid.props.style['--steps'] === String(PERFORMER.voiced.pattern.length));
  for (const field of ['performer-pattern', 'performer-play', 'performer-bpm', 'performer-clock', 'pattern-name', 'pattern-step']) {
    assert.equal(byData(full, 'field', field).length, 1, field);
  }
  for (const action of ['performer-latch', 'performer-stop', 'pattern-save', 'pattern-new', 'toggle-fullscreen', 'leave-full']) {
    assert.equal(clicks(full, action).length, 1, action);
  }
  assert.ok(findAll(full, (n) => hasClass(n, 'slot-btn')).length && findAll(full, (n) => hasClass(n, 'type-btn')).length);
  assert.match(textOf(byData(full, 'part', 'sequencer-name')[0]), /Travis pick · Guitar picker/);
  clicks(full, 'toggle-fullscreen')[0].props.onclick();
  clicks(full, 'leave-full')[0].props.onclick();
  assert.deepEqual(calls, ['toggle', 'close']);
  const panel = performerView(inSequencer(PERFORMER.voiced), lab.view, lab.actions);
  assert.equal(byData(panel, 'part', 'pattern-grid').length, 0);
  assert.match(textOf(panel), /Shown in the sequencer view/);
});

test('mountPanel draws the sequencer into its own element; an edit there is the panel\'s draft too', async () => {
  const doc = new FakeDocument();
  const api = fakeApi();
  let current = inSequencer(PERFORMER.playing);
  const store = { get model() { return current; }, subscribe() {} };
  const mounted = mountPanel(new FakeElement('section'), { store, api }, { doc, schedule: () => {} });
  await mounted.ready;
  mounted.render();
  const part = mounted.containers.sequencer;
  assert.deepEqual([part.classList.contains('module-view'), part.classList.contains('current'), part.dataset.view],
    [true, true, 'sequencer']);
  assert.ok(part.byData('part', 'pattern-grid'));
  assert.deepEqual([...new Set(part.all((e) => e.classList.contains('now')).map((e) => e.dataset.step))], ['1']);
  await mounted.controller.actions.editPattern(WALTZ, (d) => cycleCell(d, 4, 0));     // a click in the sequencer
  current = model(PERFORMER.playing);                                                // Leave: the panel again
  mounted.render();
  assert.equal(part.classList.contains('current'), false);
  const state = mounted.containers.performer.byData('part', 'pattern-state');
  assert.match(state.textContent, /● unsaved · waltz\.yaml/);                        // the same draft
  await tick();
});

// --- the key (2026-10-29) -------------------------------------------------------------------------------------
test('the Key control shows the key, changes it for the session and goes back to the file\'s', async () => {
  const api = fakeApi({ 'POST /api/lab/key': (body) => ({ ok: true, status: 200, data: { message: 'key', active: null } }) });
  const lab = createLab({ api });
  const keyed = { ...PERFORMER.voiced, key: { tonic: 'C', scale: 'major', name: 'Major (Ionian)', pcs: [0, 2, 4, 5, 7, 9, 11],
    chords: true }, chords: { ...PERFORMER.voiced.chords, types: ['key', 'key 7', 'maj'], selected: null } };
  const withLab = (active) => ({ ...model(keyed), topics: { lab: { performer: keyed, lab: { active } } } });
  let tree = performerView(withLab({ key: { tonic: 'C', scale: 'major', session: false, file: 'C major' } }), lab.view, lab.actions);
  const tonic = byData(tree, 'field', 'key-tonic')[0];
  assert.equal(findAll(tonic, (n) => n.tag === 'option' && n.props.selected)[0].props.value, 'C');
  assert.equal(textOf(byData(tree, 'part', 'key-source')[0]), 'the layout\'s');
  const keyButtons = findAll(tree, (n) => hasClass(n, 'key-type'));
  assert.deepEqual(keyButtons.map((b) => [textOf(b), Boolean(b.props.disabled)]), [['key', false], ['key 7', false]]);
  await byData(tree, 'field', 'key-scale')[0].props.onchange({ target: { value: 'dorian' } });
  await tonic.props.onchange({ target: { value: '' } });
  tree = performerView(withLab({ key: { tonic: 'D', scale: 'dorian', session: true, file: 'C major' } }), lab.view, lab.actions);
  assert.equal(textOf(byData(tree, 'part', 'key-source')[0]), 'for the session · the file: C major');
  await clicks(tree, 'key-reset')[0].props.onclick();
  assert.deepEqual(api.calls.filter(([, path]) => path === '/api/lab/key').map(([, , body]) => body),
    [{ tonic: 'C', scale: 'dorian' }, { tonic: null }, { layout: true }]);
  const none = { ...keyed, key: null };
  tree = performerView({ ...model(none), topics: { lab: { performer: none } } }, lab.view, lab.actions);
  assert.ok(findAll(tree, (n) => hasClass(n, 'key-type')).every((b) => b.props.disabled));   // no key: not offered
});

// --- changing the step re-grids the pattern: its duration and every hit's time kept (FL-style) ------------------
const grid = (rows, extra = {}) => ({ ...draftOf(null), name: 'G', meter: '4/4', step: '1/8',
  length: Object.values(rows)[0].length, lanes: Object.fromEntries(Object.entries(rows).map(([k, r]) => [k, [...r]])),
  strum: null, ...extra });
const cells = (d, lane) => d.lanes[lane].join('');

test('a finer step doubles the cells and moves each hit to its time: 1/8 → 1/16', () => {
  const d = setField(grid({ 1: 'x..X....', R: 'X...x...' }, { strum: [...'d...u...'] }), 'step', '1/16');
  assert.equal(d.length, 16);
  assert.equal(cells(d, 1), 'x.....X.........');
  assert.equal(cells(d, 'R'), 'X.......x.......');
  assert.equal(d.strum.join(''), 'd.......u.......');
  assert.equal(d.notice, null);
  assert.equal(durationText(d), '16 steps = 1 bar');
});

test('a coarser step halves them; a hit between new steps snaps to the nearest (ties earlier), hits on one cell merge', () => {
  const d = setField(grid({ 1: 'x.x.X.x.x.x.x.x.', 2: '.x.X....x.......' }, { step: '1/16' }), 'step', '1/8');
  assert.equal(d.length, 8);
  assert.equal(cells(d, 1), 'xxXxxxxx');
  assert.equal(cells(d, 2), 'xX..x...');                     // 1 → 0 (a tie: earlier), 3 (accent) → 1
  assert.equal(d.notice, '2 hits between the new steps moved to the nearest step');
  const merged = setField(grid({ 1: 'xX..............' }, { step: '1/16' }), 'step', '1/8');
  assert.equal(cells(merged, 1), 'X.......');
  assert.equal(merged.notice, '1 hit between the new steps moved to the nearest step; 1 cell kept one of two hits '
    + '(an accent wins)');
});

test('a triplet step re-grids by time, and a duration that does not divide is rounded and said', () => {
  const t = setField(grid({ 1: 'x...x...' }), 'step', '1/8t');             // 1 bar of 1/8 = 12 eighth-triplets
  assert.equal(t.length, 12);
  assert.equal(cells(t, 1), 'x.....x.....');
  assert.equal(durationText(t), '12 steps = 1 bar');
  const back = setField(grid({ 1: 'x..x..x..x.x' }, { step: '1/8t' }), 'step', '1/8');
  assert.equal(back.length, 8);
  assert.equal(cells(back, 1), 'x.x.x.xx');                  // 0→0, 3→2, 6→4, 9→6, 11→7.33→7
  const odd = setField(grid({ 1: 'x.x' }), 'step', '1/8t');  // 3 eighths = 4.5 eighth-triplets
  assert.equal(odd.length, 5);
  assert.equal(cells(odd, 1), 'x..x.');
  assert.equal(odd.notice, '3 steps of 1/8 (⅜ bar) are not a whole number of 1/8t steps: now 5 (5/12 bar)');
});

test('past 32 steps the pattern is cut and the editor says what was dropped', () => {
  const d = setField(grid({ 1: 'x.x.x.x.|x.x.x.x.|x...x...'.replace(/\|/g, '') }, { length: 24 }), 'step', '1/16');
  assert.equal(d.length, 32);
  assert.equal(cells(d, 1), 'x...x...x...x...x...x...x...x...');
  assert.equal(d.notice, 'cut to 32 steps: 2 bars of 1/16; 2 hits after them were dropped');
  assert.equal(durationText({ ...d, length: 12, step: '1/8' }), '12 steps = 1 ½ bars');
  assert.equal(cycleCell(d, 1, 1).notice, null);                       // the next edit clears the notice
});
