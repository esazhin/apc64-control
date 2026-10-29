// The lab panel (contract pi7, A21, A81; s25, s26, s27): the column beside the host page's surface when 'Lab' is
// chosen. It shows, each with its current state: the generated layouts, generators and colour schemes; the active
// layout with its window and what the encoder and Tempo do there; the harmony views; the backups, the
// 24 slots and the library; the global settings. Every control calls the same /api/lab route as `apc64 lab`, and
// every answer's message (or problem) is shown verbatim. Bulk edits are the agent's: the page shows their results
// (a slot read, the library) but has no multi-select editor (§2.5, §2.7 q1).
//
// The host page imports this module once and calls mountPanel(element, {store, api, handlers, panel}). The lab
// state and the harmony arrive on the /ws 'lab' topic (kinds 'lab' and 'harmony'); the panel reads them from the
// host store's topics, and fetches them once at mount for a page that connected before anything was published.
// Its "?" buttons open the host page's one help overlay (handlers.help, the host's help.js) with the topics below.
// The harmony views also have a full view across the whole page (HARMONY_VIEW): the host page shows it alone when
// its address says ?view=harmony (a new tab, a bookmark, another device), or when Full screen is pressed
// (handlers.openView); the panel draws it into its own element at the end of <body> (.module-view). The performer's
// pattern editor has one too, the sequencer (SEQUENCER_VIEW, ?view=sequencer): the same editor, draft and state as
// the panel's, the grid large across the page with the controls needed while playing.
import { h, mount } from './lab_dom.js';
import { MAIN_CHOICES, harmonyFullView, harmonyView, mainChoices, mainViewKind, padGridModel } from './harmony_views.js';
import { blankDraft, draftData, draftOf, idFor, markPlayhead, patternConfirmView, patternEditor } from './performer_editor.js';

export const UNIT_HINT = 'encoder: shift · Tempo: interval';
export const SLOTS = Array.from({ length: 24 }, (_, k) => k + 1);
const STYLE_ID = 'lab-panel-style';
export const HARMONY_VIEW = 'harmony';
// relative to the page: the host page at the same address, showing only the harmony full view
export const HARMONY_ADDRESS = `?view=${HARMONY_VIEW}`;
// the performer's sequencer: the pattern editor alone across the page, at ?view=sequencer (a tab of its own)
export const SEQUENCER_VIEW = 'sequencer';
export const SEQUENCER_ADDRESS = `?view=${SEQUENCER_VIEW}`;
// the full view's Main choice (auto / tonnetz / pads / neck), remembered per browser
export const MAIN_KEY = 'apc64-lab.harmony-main';
// the neck drawn for a left-handed player (the nut on the right), remembered per browser
export const FLIP_KEY = 'apc64-lab.neck-left-handed';

// --- help (the host's overlay shows them: {title, items: [[term, text] | text]}) ----------------------------
export const LAB_HELP = {
  id: 'lab',
  title: 'The lab',
  items: [
    ['Generated layouts', 'Layout files with a lab: section. A generator lays out the 64 pads and a colour scheme '
      + 'lights them. Activate backs up the unit\'s live edit buffer (slot 0), writes the pads there and you play '
      + 'them in the unit\'s own Custom view, with velocity and aftertouch.'],
    ['Window', 'The encoder (on the unit, or ◀ ▶ here) moves every pad one step of the current kind; Tempo switches '
      + 'the kind. The steps are the layout\'s own: most layouts move by octave → fifth → third (“oct / 5th / 3rd” '
      + 'count the steps taken in each; the OLED shows e.g. “5th +2”); a guitar layout moves by Fret (one semitone) '
      + 'or Page (0–7, 8–15, 16–23, then the end of the neck), the OLED always showing the frets on the pads, e.g. '
      + '“Frets 3-10”; Tempo flashes the kind (“Step: Page”) for a second. A step past either end is refused: the OLED '
      + 'adds “edge” (“Neck end” for a second on a guitar). Its pads mark the inlay frets 3, 5, 7, 9, 12… (fret_marks). '
      + 'Shift + encoder still browses host layouts.'],
    ['base, tuning, scheme', 'base is the note on the bottom-left pad (a number or a name like C2: Enter or Save); a '
      + 'guitar layout\'s tuning is a preset (a list of notes is written in the file); scheme picks the colours. Each '
      + 'changes one line of the layout file, which reloads at the same window.'],
    ['Leave', 'Ends the generated layout and restores slot 0 from the session backup taken before the first write.'],
    ['Project memory', 'Back up, read, push to and restore the unit\'s 24 project slots, and keep projects in the '
      + 'library. Every write backs up what it replaces first.'],
    'Each button\'s answer shows in the line just above Harmony.',
  ],
};

export const HARMONY_HELP = {
  id: 'harmony',
  title: 'Harmony',
  items: [
    ['Follows', 'The notes played on the APC64 (its Custom and Notes ports). Tick another input, e.g. a keyboard, '
      + 'to follow it too. These views only show; nothing is sent.'],
    ['Chord', 'The name of the held notes, spelled from what you hold: in the chord when they form one (E major: '
      + 'G♯), else in the layout\'s key (a scale colour scheme), else as intervals above the lowest note.'],
    ['Trail', 'The last 8 chords you held, newest last: any chord with a name (a triad, a seventh, sus, °, +); one '
      + 'note or two is not a chord. The same chord again adds nothing, and a chord that grows while you hold it '
      + 'replaces its own entry (C, then + B: Cmaj7). Clear empties it. On the Tonnetz and the circle the trail runs '
      + 'through each chord\'s major or minor triad; a chord without one (sus, °) is in the text only.'],
    ['Hints', 'Hold one note: its interval to every other note, and the triads that contain it. Hold a major or '
      + 'minor triad: its neighbours P, R and L (parallel, relative, leading-tone), the triads sharing two of its notes.'],
    ['Main view', 'The large view follows the active layout: the Tonnetz for a Tonnetz layout, otherwise the pads '
      + 'in the layout\'s own 8×8 shape, in the colours written to the unit, each with its note. Held notes light up, '
      + 'the chord\'s tones are ringed and its root dotted, notes outside a scale overlay are dimmed, and the modes '
      + 'explorer names its rows. A host layout shows the pads it binds to notes (approximate colours). A guitar layout '
      + 'shows its neck: strings as on the unit, the box is the frets on the pads, a dot is a note played on that '
      + 'string and a ring the same pitch elsewhere. In the full view, Main: Auto / Tonnetz / Pads (/ Neck) overrides '
      + 'the choice in this browser, and Left-handed puts the nut on the right.'],
    ['Circle, Tonnetz', 'The circle of fifths has the major keys outside and their relative minors inside; the held '
      + 'notes light and are joined, a held major triad lights its key outside and a minor one its key inside, and '
      + 'the trail runs through the keys. On the Tonnetz fifths go right, major thirds up-right and minor thirds '
      + 'up-left; every triangle is a triad, ▲ major and ▼ minor; beside it the small pad replica.'],
    ['Full view', 'Full screen shows these views alone, large, across the screen; Esc or Leave goes back. New tab '
      + 'opens them alone in a tab of their own: its address (the page\'s, ending in ?view=harmony) can be bookmarked '
      + 'or opened on a tablet or a second screen on the network. Everything stays live there, with the same inputs.'],
  ],
};

export const PERFORMER_HELP = {
  id: 'performer',
  title: 'Performer',
  items: [
    ['What it does', 'Plays a pattern over the notes you hold: strumming and fingerpicking. It starts at step 1 the '
      + 'moment you press a note, and a chord change does not restart it: the next hits play the new notes. Release '
      + 'everything and it stops one step later. The notes go to the layout\'s note target, like the pads.'],
    ['Strings and lanes', 'A pattern has a row (lane) per string, 1 the highest. On a guitar layout each string is '
      + 'its own lane; on other layouts lane 1 is the highest note you hold, lane 2 the next (voices). Manual strings '
      + 'are yours: what you press there passes straight through, so you can play a bass by hand under the pattern.'],
    ['Play', 'All: every string plays at its hits, one you do not press rings open, as on a guitar. Pressed: only '
      + 'the strings you press play. A missing note leaves its step silent; the timing never moves.'],
    ['Latch, Stop', 'Latch on: the last chord keeps playing after you let go, until Stop or a new chord. On the unit, '
      + 'Play toggles the latch and Stop stops the pattern (for a layout with a performer: block; the OLED says so).'],
    ['Tempo', 'In BPM (quarter notes a minute; a change applies as you type or click the arrows), or from the MIDI '
      + 'clock of an input, e.g. the MPC, or auto: the first input that sends one. The MPC sends its clock only while '
      + 'its sequencer plays, and only to the outputs its sync settings send clock to. The clock sets the speed; the '
      + 'pattern still starts when you press. The grid below is the pattern; the lit column is the step playing.'],
    ['Key', 'The layout\'s scale is the key (scheme: scale, its scale and root): the pads light in key, the notes out '
      + 'of it dark. Key here changes it for the session (not the file): a tonic and a scale, or none (chromatic); '
      + '"file" goes back to the layout\'s. The chord types key and key 7 play the key\'s own chord on the note you '
      + 'press (in C major: D is Dm, Dm7; B is Bdim, Bm7b5); a note out of key plays nothing.'],
    ['Chord types', 'Choose a type (maj, m7 …: the top row of pads on a guitar layout with a performer, or here); it '
      + 'stays chosen until another or the same one again (off). Then one note you press is the root: the chord is '
      + 'voiced on the strings from it (the A string\'s C as maj: x32010) and the pattern plays it. Two notes or more '
      + 'play as fretted. On 7 or 8 strings: Shift + a pad in the type\'s column.'],
    ['Slots', 'The bottom row of pads (the top row on 7 strings, Shift + the top row on 8) chooses one of the '
      + 'layout\'s patterns (its performer: block\'s slots); the OLED names it.'],
    ['R and A', 'Rows R and A follow the chord you hold: R is its root string, A the alternate bass (root on 6 or 5: '
      + 'string 4; on 4: string 3). A string you do not press below the root stays silent, so a C never rings the '
      + 'open low E.'],
    ['Editing', 'Click a cell: · → ● hit → ◉ accent; the strum row: ↓ down → ↑ up; a string\'s box makes it manual. '
      + 'Meter, step, length, swing, spread, play, name and description beside it. Every edit plays from the next '
      + 'step. Unsaved edits are kept per pattern (● marks them) while you choose others, until Save, Revert or '
      + 'Delete; a restart of the service drops them. Save writes patterns/<name>.yaml (checked first; the old text '
      + 'is kept), Save as under another name, New, Duplicate, Delete (asked first). Sequencer opens the editor '
      + 'alone across the page, the grid large (New tab: ?view=sequencer, a tab of its own); it is the same editor.'],
    'Changes here last for the session; the layout file\'s performer: block sets them at activation. Patterns are '
      + 'files in patterns/ (docs/performer-format.md).',
  ],
};

// --- the lab's routes (docs/lab-api.md) ----------------------------------------------------------------------
export function labApi(api) {
  const call = (method, path, body) => api.call(method, path, body);
  return {
    state: () => call('GET', '/api/lab'),
    harmony: () => call('GET', '/api/lab/harmony'),
    inputs: () => call('GET', '/api/lab/harmony/inputs'),
    selectInputs: (inputs) => call('POST', '/api/lab/harmony/inputs', { inputs }),
    clearTrail: () => call('POST', '/api/lab/harmony/trail/clear', {}),
    ports: () => call('GET', '/api/ports'),
    activate: (layout) => call('POST', '/api/lab/activate', { layout }),
    leave: () => call('POST', '/api/lab/leave', {}),
    tweak: (field, value) => call('POST', '/api/lab/tweak', { field, value }),
    key: (body) => call('POST', '/api/lab/key', body),
    turn: (steps) => call('POST', '/api/control/encoder/move', { value: steps }),
    tempo: async () => {
      const pressed = await call('POST', '/api/control/tempo/press', {});
      await call('POST', '/api/control/tempo/release', {});
      return pressed;
    },
    backups: () => call('GET', '/api/lab/backups'),
    library: () => call('GET', '/api/lab/library'),
    backupAll: () => call('POST', '/api/lab/backup', { all: true }),
    backup: (slot) => call('POST', '/api/lab/backup', { slot }),
    restore: (backup, slot) => call('POST', '/api/lab/restore', { backup, slot }),
    push: (entry, slot) => call('POST', '/api/lab/push', { entry, slot }),
    preview: (entry) => call('POST', '/api/lab/preview', { entry }),
    capture: (slot, name) => call('POST', '/api/lab/library/capture', { slot, name }),
    importPreset: (name, file, data) => call('POST', '/api/lab/import', { name, file, data_base64: data }),
    slot: (n) => call('GET', `/api/lab/slots/${n}`),
    globals: () => call('GET', '/api/lab/globals'),
    changeGlobals: (changes, confirm) => call('POST', '/api/lab/globals', confirm ? { changes, confirm: true } : { changes }),
    dismissRecovery: () => call('POST', '/api/lab/recovery/dismiss', {}),
    performer: () => call('GET', '/api/lab/performer'),
    changePerformer: (changes) => call('POST', '/api/lab/performer', changes),
    stopPerformer: () => call('POST', '/api/lab/performer/stop', {}),
    savePattern: (body) => call('POST', '/api/lab/patterns/save', body),
    deletePattern: (id, base) => call('POST', '/api/lab/patterns/delete', base ? { id, base } : { id }),
  };
}

// --- the panel's own state and actions -----------------------------------------------------------------------
export function initialView() {
  return {
    lab: null, harmony: null, backups: null, library: null, globals: null, globalsProblem: null, ports: null,
    inputs: null, slot: 1, entry: '', restoreBackup: null, base: null, slotView: null, captureName: '', importName: '',
    globalsDraft: {}, confirm: null, result: null, mainView: rememberedMain(), leftHanded: rememberedFlip(),
    performer: null, bpm: null, draft: null, typing: {}, saveAs: null, patternConfirm: null,
    editing: 0, draftRevision: 0, seenRevision: 0,
  };
}

// localStorage may be missing or refuse (a private window, blocked site data): the choice is then 'auto'.
export function rememberedMain(storage = globalThis.localStorage) {
  try {
    const value = storage?.getItem?.(MAIN_KEY);
    return MAIN_CHOICES.some(([key]) => key === value) ? value : 'auto';
  } catch {
    return 'auto';
  }
}

function rememberMain(value, storage = globalThis.localStorage) {
  try {
    storage?.setItem?.(MAIN_KEY, value);
  } catch {
    // not remembered; the choice still holds in this page
  }
}

// The left-handed neck, likewise: off unless this browser remembers it on.
export function rememberedFlip(storage = globalThis.localStorage) {
  try {
    return storage?.getItem?.(FLIP_KEY) === 'on';
  } catch {
    return false;
  }
}

function rememberFlip(on, storage = globalThis.localStorage) {
  try {
    storage?.setItem?.(FLIP_KEY, on ? 'on' : 'off');
  } catch {
    // not remembered; the choice still holds in this page
  }
}

const answerText = (answer) => (answer.ok ? (answer.data?.message ?? 'done') : answer.problem);
// the tempo field applies this long after the last keystroke or arrow click (at once on Enter or on leaving it)
export const BPM_DELAY = 250;
// the pattern select's value for the session's new, never-saved pattern
export const NEW_PATTERN = '*new';
const TIMERS = { set: (fn, ms) => setTimeout(fn, ms), clear: (id) => clearTimeout(id) };

// The editor's draft follows the service: when the pattern playing changed elsewhere (a slot pad, another page, the
// CLI) since the draft was made, the draft goes and the editor shows the state again; never while this page's own
// edit is on its way (its answer says which change it made). Called before each render.
export function followPerformer(view, p) {
  if (!p) return false;
  const revision = p.pattern_revision ?? 0;
  if (!view.draft) {
    view.seenRevision = revision;
    return false;
  }
  if (view.editing || revision <= (view.draftRevision ?? 0)) return false;
  Object.assign(view, { draft: null, typing: {}, saveAs: null, seenRevision: revision });
  return true;
}

export function createLab({ api, onChange = () => {}, readFile = null, help = null, page = null, timers = TIMERS } = {}) {
  const lab = labApi(api);
  const view = initialView();
  const set = (patch) => { Object.assign(view, patch); onChange(view); };
  const show = (answer) => { set({ result: { ok: answer.ok, text: answerText(answer) } }); return answer; };
  const refreshLists = async () => {
    const [backups, library] = await Promise.all([lab.backups(), lab.library()]);
    set({ backups: backups.ok ? backups.data : view.backups, library: library.ok ? library.data : view.library });
  };
  const refreshLab = async () => {
    const state = await lab.state();
    if (state.ok) set({ lab: state.data });
  };
  const act = async (call, after = refreshLists) => {
    const answer = await call();
    show(answer);
    await after?.();
    return answer;
  };

  const actions = {
    help: (topic) => help?.(topic),
    // the harmony full view (the host page's handlers: openView, closeView, toggleFullscreen)
    fullScreen: () => page?.openView?.(HARMONY_VIEW, { fullscreen: true }),
    leaveFullView: () => page?.closeView?.(),
    openSequencer: () => page?.openView?.(SEQUENCER_VIEW),
    toggleFullscreen: () => page?.toggleFullscreen?.(),
    setMainView: (value) => {
      const choice = MAIN_CHOICES.some(([key]) => key === value) ? value : 'auto';
      rememberMain(choice);
      set({ mainView: choice });
    },
    toggleLeftHanded: () => {
      rememberFlip(!view.leftHanded);
      set({ leftHanded: !view.leftHanded });
    },
    async load() {
      const [state, harmony, inputs, ports, performer] = await Promise.all([lab.state(), lab.harmony(), lab.inputs(),
        lab.ports(), lab.performer()]);
      set({ lab: state.ok ? state.data : null, harmony: harmony.ok ? harmony.data : null,
        inputs: inputs.ok ? inputs.data : null, ports: ports.ok ? ports.data : null,
        performer: performer.ok ? performer.data : null });
      await refreshLists();
      await actions.readGlobals(true);
    },
    refreshLists,
    // the active layout (s26.c1)
    activate: (layout) => act(() => lab.activate(layout), refreshLab),
    leave: () => act(() => lab.leave(), refreshLab),
    turn: (steps) => act(() => lab.turn(steps), null).then((answer) => {
      if (answer.ok) set({ result: { ok: true, text: `encoder ${steps > 0 ? '+' : ''}${steps}` } });
      return answer;
    }),
    tempo: () => act(() => lab.tempo(), null).then((answer) => {
      if (answer.ok) set({ result: { ok: true, text: 'Tempo: next step kind' } });
      return answer;
    }),
    draftBase: (value) => { view.base = value; },
    saveBase: () => act(() => lab.tweak('base', numberOrText(view.base ?? '')), refreshLab),
    setScheme: (scheme) => act(() => lab.tweak('scheme', scheme), refreshLab),
    setParam: (name, value) => act(() => lab.tweak(name, value), refreshLab),
    dismissRecovery: () => act(() => lab.dismissRecovery(), refreshLab),
    restoreRecovery: (backup) => act(() => lab.restore(backup, 0), async () => { await refreshLab(); await refreshLists(); }),
    clearTrail: () => act(() => lab.clearTrail(), null),
    // harmony inputs (§2.7 q7)
    toggleInput: async (port, on, current = view.inputs?.inputs ?? []) => {
      const next = on ? [...new Set([...current, port])] : current.filter((p) => p !== port);
      const answer = await lab.selectInputs(next);
      if (answer.ok) set({ inputs: answer.data });
      return show(answer);
    },
    // project memory (pi5)
    selectSlot: (n) => set({ slot: n, slotView: null, restoreBackup: null }),
    chooseBackup: (id) => { view.restoreBackup = id; },
    chooseEntry: (entry) => { view.entry = entry; },
    backupAll: () => act(() => lab.backupAll()),
    backupSlot: () => act(() => lab.backup(view.slot)),
    readSlot: async () => {
      const answer = await lab.slot(view.slot);
      set({ slotView: answer.ok ? answer.data : null });
      if (!answer.ok) show(answer);
      return answer;
    },
    push: () => act(() => lab.push(view.entry || firstEntry(view), view.slot)),
    restore: (backup) => act(() => lab.restore(backup, view.slot), async () => { await refreshLists(); await refreshLab(); }),
    draftCapture: (name) => { view.captureName = name; },
    capture: () => act(() => lab.capture(view.slot, view.captureName)),
    preview: (entry) => act(() => lab.preview(entry), refreshLab),
    draftImportName: (name) => { view.importName = name; },
    importFile: async (file) => {
      if (!file) return null;
      const data = await (readFile ?? readAsBase64)(file);
      const name = view.importName || String(file.name ?? '').replace(/\.apc64$/i, '');
      return act(() => lab.importPreset(name, file.name, data));
    },
    // global settings (pi6)
    readGlobals: async (quiet = false) => {
      const answer = await lab.globals();
      set({ globals: answer.ok ? answer.data : null, globalsProblem: answer.ok ? null : answer.problem,
        globalsDraft: {}, confirm: null });
      if (!quiet && !answer.ok) show(answer);
      return answer;
    },
    draftGlobal: (field, value) => { view.globalsDraft[field] = value; },
    applyGlobals: async (confirm = false) => {
      const changes = confirm && view.confirm ? view.confirm.changes : changedGlobals(view);
      if (!Object.keys(changes).length) return show({ ok: true, data: { message: 'nothing changed on the page' } });
      const answer = await lab.changeGlobals(changes, confirm);
      show(answer);
      const hazard = !answer.ok && hazardFields(view).includes(answer.data?.field);
      if (hazard) { set({ confirm: { changes, problem: answer.problem } }); return answer; }
      await actions.readGlobals(true);
      await refreshLists();
      return answer;
    },
    cancelConfirm: () => set({ confirm: null }),
    // the performer (§2.10): each change for the session, its answer in the result line
    setPerformer: async (changes) => {
      const answer = await lab.changePerformer(changes);
      show(answer);
      if (answer.ok) set({ performer: answer.data, bpm: null });
      return answer;
    },
    stopPerformer: async () => {
      const answer = await lab.stopPerformer();
      show(answer);
      if (answer.ok) set({ performer: answer.data });
      return answer;
    },
    // the tempo applies as it changes: after a pause in typing (or the arrows), at once on Enter or on leaving it
    draftBpm: (value) => {
      view.bpm = value;
      timers.clear(bpmTimer);
      bpmTimer = timers.set(() => actions.applyBpm(), BPM_DELAY);
    },
    applyBpm: async () => {
      timers.clear(bpmTimer);
      const value = view.bpm;
      if (value === null || value === undefined || String(value).trim() === '') return null;
      const bpm = Number(value);
      const answer = await lab.changePerformer({ bpm: Number.isFinite(bpm) ? bpm : String(value) });
      show(answer);
      if (answer.ok) set({ performer: answer.data, ...(view.bpm === value ? { bpm: null } : {}) });
      return answer;
    },
    // chord types and pattern slots (Phase 2)
    chooseType: (name) => actions.setPerformer({ chord_type: name }),
    // the key for the session (the layout's scale; not the file): a tonic and a scale, none, or the file's again
    setKey: async (tonic, scale) => {
      const answer = await lab.key(tonic ? { tonic, scale: scale || 'major' } : { tonic: null });
      show(answer);
      if (answer.ok) set({ lab: answer.data });
      return answer;
    },
    resetKey: async () => {
      const answer = await lab.key({ layout: true });
      show(answer);
      if (answer.ok) set({ lab: answer.data });
      return answer;
    },
    chooseSlot: (slot) => {
      set({ draft: null, saveAs: null, typing: {} });                  // the slot's pattern (its kept edit) shows
      return actions.setPerformer({ slot });
    },
    // the pattern editor (Phase 2): every edit plays at once and is kept (unsaved) by the service, Save writes it
    choosePattern: (id) => {
      set({ draft: null, saveAs: null, typing: {} });
      return actions.setPerformer(id === NEW_PATTERN ? { new_pattern: true } : { pattern: id });
    },
    typePattern: (field, value) => { view.typing = { ...view.typing, [field]: value }; },
    editPattern: async (pattern, change) => {
      const typing = { ...view.typing };
      const fresh = !view.draft;
      let draft = view.draft ?? draftOf(pattern);
      for (const [field, value] of Object.entries(typing)) if (value !== draft[field]) draft = { ...draft, [field]: value, dirty: true };
      draft = change(draft);
      const seq = (editSeq += 1);
      set({ draft, typing: {}, editing: view.editing + 1, ...(fresh ? { draftRevision: view.seenRevision } : {}) });
      let answer;
      try {
        answer = await lab.changePerformer({ pattern_data: draftData(draft), edits: draft.id ?? null });
      } finally {
        view.editing -= 1;
      }
      if (answer.ok) view.draftRevision = Math.max(view.draftRevision, answer.data?.pattern_revision ?? 0);
      if (seq !== editSeq || !view.draft) {                             // a newer edit is on its way
        if (answer.ok) set({ performer: answer.data });
        return answer;
      }
      if (!answer.ok && answer.data?.code === 'stale') {                 // another pattern plays now: show it
        show(answer);
        set({ draft: null, saveAs: null, typing: {} });
        return answer;
      }
      const dirty = answer.ok ? Boolean(answer.data?.pattern?.edited) : view.draft.dirty;
      set({ draft: { ...view.draft, dirty, issues: answer.ok ? [] : (answer.data?.issues ?? [{ text: answer.problem }]) },
        ...(answer.ok ? { performer: answer.data } : {}) });
      return answer;
    },
    // New and Duplicate make the session's one new pattern: when one is kept already, asked first
    newPattern: (p = null) => {
      const kept = keptNew(p);
      if (kept) return set({ patternConfirm: { kind: 'new', name: kept.name } });
      return set({ draft: blankDraft(), saveAs: null, typing: {}, draftRevision: view.seenRevision });
    },
    duplicatePattern: (pattern, p = null) => {
      const kept = keptNew(p);
      if (kept) return set({ patternConfirm: { kind: 'duplicate', name: kept.name, pattern } });
      const from = view.draft ?? draftOf(pattern);
      return actions.editPattern(pattern, () => ({ ...from, id: null, base: null, name: `${from.name} copy`.slice(0, 40),
        dirty: true, issues: [] }));
    },
    savePattern: async (pattern) => {
      const draft = view.draft ?? draftOf(pattern);
      if (!draft.id) return actions.saveAsPattern(pattern);
      return writePattern({ id: draft.id, data: draftData(withTyping(draft)), base: draft.base, edits: draft.id });
    },
    saveAsPattern: (pattern) => {
      const draft = view.draft ?? draftOf(pattern);
      return set({ draft: { ...draft }, saveAs: { id: draft.id ? `${draft.id}-2` : idFor(draft.name) } });
    },
    typeSaveAs: (value) => { if (view.saveAs) view.saveAs = { ...view.saveAs, id: value }; },
    confirmSaveAs: () => {
      const draft = view.draft;
      if (!draft || !view.saveAs) return null;
      return writePattern({ id: String(view.saveAs.id).trim(), data: draftData(withTyping(draft)), create: true,
        edits: draft.id ?? null });
    },
    cancelSaveAs: () => set({ saveAs: null }),
    revertPattern: (id) => {
      set({ draft: null, saveAs: null, typing: {} });
      return actions.setPerformer({ revert: id });
    },
    deletePattern: (pattern) => {
      const draft = view.draft ?? draftOf(pattern);
      if (!draft.id) return null;
      return set({ patternConfirm: { kind: 'delete', id: draft.id, name: draft.name, base: draft.dirty ? null : draft.base } });
    },
    confirmPattern: async () => {
      const c = view.patternConfirm;
      set({ patternConfirm: null });
      if (!c) return null;
      if (c.kind === 'delete') {
        const answer = await lab.deletePattern(c.id, c.base);
        show(answer);
        if (answer.ok) set({ draft: null, saveAs: null, typing: {} });
        return answer;
      }
      set({ draft: null, saveAs: null, typing: {} });
      if (c.kind === 'duplicate') return actions.duplicatePattern(c.pattern);
      return set({ draft: blankDraft(), draftRevision: view.seenRevision });
    },
    cancelPatternConfirm: () => set({ patternConfirm: null }),
  };
  let editSeq = 0;
  let bpmTimer = null;
  // the session's kept new pattern ({id: null, name, new: true}), unless it is the draft being replaced already
  const keptNew = (p) => (p?.edits ?? []).find((e) => e.new) ?? null;
  const withTyping = (draft) => Object.entries(view.typing).reduce((d, [field, value]) => ({ ...d, [field]: value }), draft);
  async function writePattern(body) {
    const answer = await lab.savePattern(body);
    show(answer);
    if (answer.ok) set({ draft: null, saveAs: null, typing: {} });
    else if (view.draft) set({ draft: { ...view.draft, issues: answer.data?.issues?.length ? answer.data.issues
      : [{ text: answer.problem + (answer.data?.fix ? `; ${answer.data.fix}` : '') }] } });
    return answer;
  }
  return { view, actions, api: lab };
}

function numberOrText(value) {
  const text = String(value).trim();
  return /^-?\d+$/.test(text) ? Number(text) : text;
}

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function entriesOf(view) {
  return (view.library ?? []).filter((e) => e.kind !== 'corrupt').map((e) => e.name);
}

function firstEntry(view) {
  return entriesOf(view)[0] ?? '';
}

function hazardFields(view) {
  return (view.globals?.fields ?? []).filter((f) => f.hazard).map((f) => f.field);
}

export function changedGlobals(view) {
  const changes = {};
  for (const f of view.globals?.fields ?? []) {
    if (!(f.field in view.globalsDraft)) continue;
    const drafted = view.globalsDraft[f.field];
    const current = f.options ? currentOption(f)?.[0] : f.value;
    if (String(drafted) !== String(current)) changes[f.field] = numberOrText(drafted);
  }
  return changes;
}

function currentOption(field) {
  return (field.options ?? []).find(([, text]) => text === field.text) ?? null;
}

// --- what the panel shows (pure: model + view → h trees) ------------------------------------------------------
export function topic(model, kind) {
  return model?.topics?.lab?.[kind] ?? null;
}

export function labOf(model, view) {
  return topic(model, 'lab') ?? view.lab;
}

export function harmonyOf(model, view) {
  return topic(model, 'harmony') ?? view.harmony;
}

// The performer: as last pushed (every change and every step while it plays), else as fetched.
export function performerOf(model, view) {
  return topic(model, 'performer') ?? view.performer;
}

// The inputs harmony follows: as last pushed (a choice made in another tab or through the API), else as fetched.
export function inputsOf(model, view) {
  return topic(model, 'inputs') ?? view.inputs;
}

// The generated layouts: the lab state's list (pushed whenever the layout files change; an invalid one carries its
// reason), else the library's definitions as fetched.
export function layoutsOf(lab, view) {
  if (Array.isArray(lab?.layouts)) return lab.layouts;
  return (view.library ?? []).filter((e) => e.kind === 'definition').map((e) => ({ ...e, valid: true }));
}

const button = (text, onclick, extra = {}) => h('button', { type: 'button', onclick, ...extra }, text);

// The host page's "?" button (its help.js helpButton, class help-btn): the panel is served apart, so it draws the
// same small button and the host's overlay does the rest.
export function helpButton(topic, actions) {
  return button('?', () => actions.help?.(topic), { class: 'help-btn', title: `Help: ${topic.title}`,
    'aria-label': `Help: ${topic.title}`, 'aria-haspopup': 'dialog', data: { help: topic.id } });
}

function paramText(p) {
  return `${p.name} ${p.min}–${p.max} (default ${p.default})`;
}

// The panel's top: the heading, the messages and the active layout (then the performer, then the lists).
export function statusView(model, view, actions) {
  const head = statusHeadView(model, view, actions);
  return labOf(model, view) ? [...head, ...listsView(model, view, actions)] : head;
}

export function statusHeadView(model, view, actions) {
  const lab = labOf(model, view);
  if (!lab) return [h('div', { class: 'lab-loading muted', text: 'Loading the lab…' })];
  const target = lab.target ?? {};
  // a pending recovery says it once (its own box); the message line would repeat the same text
  const message = lab.message && lab.message !== lab.recovery?.message ? lab.message : null;
  return [
    h('h2', {}, 'Lab', helpButton(LAB_HELP, actions), h('span', { class: 'grow' }),
      h('span', { class: ['lab-target', target.routed === false && 'warn'], data: { target: '' },
        text: target.text ? `notes → ${target.text}` : target.default ? `default note target: ${target.default}`
          : 'notes are only shown: no default target' })),
    message ? h('div', { class: 'lab-message', data: { message: '' }, text: message }) : null,
    lab.recovery ? h('div', { class: 'lab-recovery' }, h('div', { text: lab.recovery.message }),
      button(`Restore slot 0 from ${lab.recovery.backup}`, () => actions.restoreRecovery(lab.recovery.backup),
        { class: 'primary', data: { action: 'restore-recovery' } }),
      button('Dismiss', () => actions.dismissRecovery(), { data: { action: 'dismiss-recovery' } })) : null,
    (lab.warnings ?? []).map((w) => h('div', { class: 'lab-warning', text: `start-up: ${w}` })),
    activeView(lab, view, actions),
  ];
}

// The generated layouts (Activate), the generators and the colour schemes.
export function listsView(model, view, actions) {
  const lab = labOf(model, view);
  if (!lab) return [];
  const active = lab.active;
  const layouts = layoutsOf(lab, view);
  return [
    h('section', { class: 'lab-sub', data: { part: 'layouts' } },
      h('h3', { text: 'Generated layouts' }),
      layouts.length ? h('ul', { class: 'lab-list' }, layouts.map((e) => (e.valid === false
        ? h('li', { class: 'invalid', data: { layout: e.layout, invalid: '' } },
          h('span', { class: 'name', text: e.name }), h('span', { class: 'muted', text: ` invalid · ${e.layout}.yaml` }),
          h('span', { class: 'bad', text: e.error }))
        : h('li', { class: active && active.layout === e.layout && 'current', data: { layout: e.layout } },
          h('span', { class: 'name', text: e.name }), h('span', { class: 'muted', text: ` ${e.generator} · ${e.layout}.yaml` }),
          button(active && active.layout === e.layout ? 'Active' : 'Activate', () => actions.activate(e.name),
            { data: { action: 'activate', layout: e.name }, disabled: active && active.layout === e.layout })))))
        : h('div', { class: 'muted', text: 'No generated layout yet: add a layout file with a lab: section (docs/lab-guide.md).' })),
    h('section', { class: 'lab-sub', data: { part: 'generators' } },
      h('h3', { text: 'Generators' }),
      h('ul', { class: 'lab-list' }, (lab.generators ?? []).map((g) => h('li', {
        class: g.broken && 'broken', data: { generator: g.name } },
      h('span', { class: 'name', text: g.name }),
      g.broken ? h('span', { class: 'bad', text: ` broken: ${g.error}` })
        : h('span', { class: 'muted', text: ` ${(g.params ?? []).map(paramText).join(', ')}` })))),
      h('div', { class: 'schemes' }, h('span', { class: 'muted', text: 'colour schemes: ' }),
        (lab.schemes ?? []).map((s, k) => h('span', { class: ['scheme', s.broken && 'broken'], data: { scheme: s.name },
          text: (k ? ', ' : '') + s.name + (s.broken ? ` (broken: ${s.error})` : '') })))),
  ];
}

function activeView(lab, view, actions) {
  const active = lab.active;
  if (!active) {
    return h('section', { class: 'lab-active none', data: { part: 'active' } },
      h('div', { class: 'muted', text: 'No generated layout is active. Activate one below, or load it with Shift + encoder.' }),
      h('div', { class: 'unit-hint', text: UNIT_HINT }));
  }
  const counts = active.counts ?? {};
  const [row1, row2] = active.oled ?? [active.name, ''];
  const definition = active.definition;
  const schemes = (lab.schemes ?? []).filter((s) => !s.broken);
  const own = ownSteps(active);
  const steps = own ? active.window.steps : ['octave', 'fifth', 'third'];
  return h('section', { class: 'lab-active', data: { part: 'active' } },
    h('div', { class: 'active-head' },
      h('div', { class: 'oled', title: 'the unit\'s OLED' }, h('div', { text: row1 }), h('div', { text: row2 })),
      h('div', { class: 'active-what' },
        h('div', { class: 'active-name', text: active.preview ? `${active.name} (preview)` : active.name }),
        h('div', { class: 'window', data: { window: '' } }, own
          ? [h('span', { class: 'interval', text: active.window.label }),
            h('span', { class: 'muted', text: ` · steps ${steps.join(' / ')} · ${rangeText(active.window)}` })]
          : [h('span', { class: 'interval', text: `${active.interval} ${signed(active.offset)}` }),
            h('span', { class: 'muted', text: ` · oct ${signed(counts.octave)} · 5th ${signed(counts.fifth)} · 3rd ${signed(counts.third)}` })]),
        h('div', { class: 'unit-hint', text: unitHint(active) }),
        h('div', { class: 'muted small', text: `view ${active.unit_view ?? 'unknown'} · session backup ${active.session_backup ?? 'pending'}` }))),
    h('div', { class: 'active-controls' },
      button('◀ encoder', () => actions.turn(-1), { data: { action: 'turn-left' }, title: 'one step of the current kind down' }),
      button('encoder ▶', () => actions.turn(1), { data: { action: 'turn-right' }, title: 'one step of the current kind up' }),
      button('Tempo', () => actions.tempo(), { data: { action: 'tempo' }, title: `next step kind: ${steps.join(' → ')}` }),
      button('Leave', () => actions.leave(), { class: 'danger', data: { action: 'leave' },
        title: 'restore slot 0 from the session backup' })),
    definition ? h('div', { class: 'active-tweaks' },
      'base' in (definition.params ?? {}) ? [
        h('label', {}, 'base ', h('input', { type: 'text', size: 5, value: view.base ?? String(definition.params?.base ?? ''),
          data: { field: 'base' }, oninput: (e) => actions.draftBase(e.target.value),
          onkeydown: (e) => { if (e.key === 'Enter') actions.saveBase(); } })),
        button('Save', () => actions.saveBase(), { data: { action: 'save-base' } })] : null,
      choiceTweaks(lab, definition, actions),
      h('label', {}, ' scheme ', h('select', { data: { field: 'scheme' }, onchange: (e) => actions.setScheme(e.target.value) },
        schemes.map((s) => h('option', { value: s.name, selected: s.name === definition.scheme, text: s.name }))))) : null);
}

// A generator that declares its own window steps (the guitar: Fret and Page) rather than octave / fifth / third.
export function ownSteps(active) {
  return Boolean(active?.window?.steps?.length) && !('octave' in (active.counts ?? {}));
}

export function unitHint(active) {
  if (!ownSteps(active)) return UNIT_HINT;
  const { step, steps } = active.window;
  return `encoder: one ${String(step).toLowerCase()} · Tempo: ${steps.join(' ↔ ')}`;
}

function rangeText(window) {
  const end = window.highest + Math.max((window.shown ?? 0) - 1, 0);
  return window.shown ? `${window.lowest}–${end} (${window.shown} on the pads)` : `${window.lowest}–${end}`;
}

// The generator's named-choice parameters (the guitar's tuning): a select of its presets, saved like base and scheme
// as one line of the file. A tuning written as a list of notes shows as 'custom' until a preset is chosen.
export function choiceTweaks(lab, definition, actions) {
  const generator = (lab.generators ?? []).find((g) => g.name === definition.generator);
  return (generator?.params ?? []).filter((p) => (p.kind === 'notes' || p.kind === 'choice') && p.choices?.length)
    .map((p) => {
      const value = definition.params?.[p.name] ?? p.default;
      const custom = Array.isArray(value);
      return h('label', {}, ` ${p.name} `, h('select', { data: { field: p.name }, title: p.doc,
        onchange: (e) => { if (e.target.value) actions.setParam(p.name, e.target.value); } },
      custom ? h('option', { value: '', selected: true, text: `custom: ${value.join(' ')}` }) : null,
      p.choices.map((c) => h('option', { value: c, selected: !custom && c === value, text: c }))));
    });
}

function signed(n) {
  const value = Number(n ?? 0);
  return value >= 0 ? `+${value}` : String(value);
}

// The harmony full view is the page's current view (the host model's ui.view), so the panel's copy steps aside.
export function fullViewShown(model) {
  return model?.ui?.view?.name === HARMONY_VIEW;
}

// The harmony views' data: the harmony state, the active layout's pads as a grid model, and which main view.
// The panel decides automatically; the full view applies its Main choice (`override`).
function harmonyParts(model, view, override = 'auto') {
  const lab = labOf(model, view);
  return {
    harmony: harmonyOf(model, view),
    grid: padGridModel(lab, model?.state?.controls ?? {}),
    kind: mainViewKind(lab, override),
    flip: Boolean(view.leftHanded),
  };
}

// The full view's Main choice: Auto (by the layout), Tonnetz, Pads, or Neck for a guitar layout; remembered in
// this browser. A remembered Neck reads as Auto while the layout has no neck.
export function mainChoiceView(view, actions, lab = null) {
  const choices = mainChoices(lab);
  const current = choices.some(([key]) => key === view.mainView) ? view.mainView : 'auto';
  return h('span', { class: 'main-choice', role: 'group', 'aria-label': 'Main view', data: { part: 'main-choice' } },
    h('span', { class: 'muted', text: 'Main: ' }),
    choices.map(([key, label]) => button(label, () => actions.setMainView(key), {
      class: ['view-btn', current === key && 'on'], data: { main: key }, 'aria-pressed': current === key ? 'true' : 'false',
      title: key === 'auto' ? 'the neck for a guitar layout, the Tonnetz for a Tonnetz layout, the pads for any other'
        : `always the ${label}` })));
}

// The neck for a left-handed player (the nut on the right); page-only, remembered in this browser.
export function flipView(view, actions) {
  const on = Boolean(view.leftHanded);
  return button('Left-handed', () => actions.toggleLeftHanded(), { class: ['view-btn', on && 'on'],
    data: { action: 'left-handed' }, 'aria-pressed': on ? 'true' : 'false',
    title: 'Draw the neck with the nut on the right (this page only; the unit is unchanged)' });
}

// The inputs harmony follows: the APC64 always, any other MIDI input by its tick (§2.7 q7).
export function inputsView(view, actions, model = null) {
  const following = inputsOf(model, view)?.inputs ?? [];
  const candidates = (view.ports ?? []).filter((p) => p.present !== false && p.direction !== 'output'
    && p.direction !== 'declared' && !/apc64/i.test(p.name)).map((p) => p.name);
  const ports = [...new Set([...candidates, ...following])];
  return h('div', { class: 'inputs', data: { part: 'inputs' } },
    h('span', { class: 'muted', text: 'follows: APC64 Custom + Notes' }),
    ports.map((port) => h('label', { class: 'input-choice' },
      h('input', { type: 'checkbox', checked: following.includes(port), data: { input: port },
        onchange: (e) => actions.toggleInput(port, e.target.checked, following) }), ` ${port}`)));
}

// The small buttons beside the Harmony "?": in the panel, Full screen and New tab; in the full view, the full-screen
// toggle and Leave (or, in the tab the address opened, a link to the whole page).
export function fullViewButtons(model, actions, where = 'panel') {
  const newTab = h('a', { class: 'view-btn', href: HARMONY_ADDRESS, target: '_blank', rel: 'noopener',
    data: { action: 'harmony-tab' }, title: 'The harmony views alone in a new tab: bookmark it, or open the same '
      + 'address on a tablet or a second screen', text: 'New tab ↗' });
  if (where === 'panel') {
    return h('span', { class: 'view-btns' },
      button('Full screen', () => actions.fullScreen(), { class: 'view-btn', data: { action: 'harmony-fullscreen' },
        title: 'The harmony views alone, large, full screen (Esc leaves)' }),
      newTab);
  }
  const on = Boolean(model?.ui?.fullscreen);
  const pinned = Boolean(model?.ui?.view?.pinned);
  return h('span', { class: 'view-btns' },
    button(on ? 'Exit full screen' : 'Full screen', () => actions.toggleFullscreen(), { class: 'view-btn',
      data: { action: 'toggle-fullscreen' }, 'aria-pressed': on ? 'true' : 'false' }),
    pinned ? h('a', { class: 'view-btn', href: './', data: { action: 'whole-page' }, title: 'The whole page: surface, '
      + 'overview and lab', text: 'Whole page' })
      : button('Leave', () => actions.leaveFullView(), { class: 'view-btn', data: { action: 'leave-full' },
        title: 'Back to the page (Esc)' }));
}

export function harmonySectionView(model, view, actions) {
  const heading = h('h2', {}, 'Harmony', helpButton(HARMONY_HELP, actions), h('span', { class: 'grow' }),
    fullViewButtons(model, actions, 'panel'));
  if (fullViewShown(model)) return [heading, h('div', { class: 'muted', text: 'Shown in the full view.' })];
  const { harmony, grid, kind, flip } = harmonyParts(model, view);
  return [
    heading,
    inputsView(view, actions, model),
    harmony ? harmonyView(harmony, { grid, kind, flip, onClearTrail: actions.clearTrail }) : h('div', { class: 'muted', text: 'Waiting for the play stream…' }),
  ];
}

// The full view: the heading with the inputs and the buttons, then the views across the page; nothing while the
// page shows something else.
export function harmonyFullPart(model, view, actions) {
  if (!fullViewShown(model)) return [];
  const { harmony, grid, kind, flip } = harmonyParts(model, view, view.mainView);
  return [
    h('header', { class: 'full-head' },
      h('h2', {}, h('span', { class: ['full-conn', model.connected && 'live'], title: model.connected ? 'Live' : 'Reconnecting…' }),
        'Harmony', helpButton(HARMONY_HELP, actions)),
      inputsView(view, actions, model),
      h('span', { class: 'grow' }),
      kind === 'neck' ? flipView(view, actions) : null,
      mainChoiceView(view, actions, labOf(model, view)),
      fullViewButtons(model, actions, 'full')),
    harmony ? harmonyFullView(harmony, { grid, kind, flip, onClearTrail: actions.clearTrail }) : h('div', { class: 'muted full-waiting', text: 'Waiting for the play stream…' }),
  ];
}

function latestBackups(view) {
  const latest = new Map();
  for (const b of view.backups?.backups ?? []) {
    const known = latest.get(b.target);
    if (!known || b.taken_at > known.taken_at) latest.set(b.target, b);
  }
  return latest;
}

// newest first; equal times keep the service's order (stable sort)
const newestFirst = (a, b) => (a.taken_at === b.taken_at ? 0 : a.taken_at < b.taken_at ? 1 : -1);
const shortTime = (iso) => (iso ? iso.slice(5, 16).replace('T', ' ') : '');

export function memoryView(model, view, actions) {
  const latest = latestBackups(view);
  const slot = view.slot;
  const ofSlot = (view.backups?.backups ?? []).filter((b) => b.target === `slot${slot}`)
    .sort(newestFirst);
  const entries = entriesOf(view);
  const lastSet = (view.backups?.sets ?? []).filter((s) => s.kind === 'all').sort(newestFirst)[0];
  const tile = (n) => {
    const b = latest.get(`slot${n}`);
    return h('button', { type: 'button', class: ['slot-tile', n === slot && 'selected', !b && 'unbacked'],
      data: { slot: n }, onclick: () => actions.selectSlot(n), title: b ? `newest backup ${b.id}` : 'no backup yet' },
    h('span', { class: 'n', text: n === 0 ? '0 edit' : String(n) }), h('span', { class: 'when', text: b ? shortTime(b.taken_at) : '—' }));
  };
  return [
    h('h2', {}, 'Project memory', h('span', { class: 'grow' }),
      button('Back up all', () => actions.backupAll(), { class: 'primary', data: { action: 'backup-all' },
        title: 'slots 0–24 and the global settings as one dated set' })),
    h('div', { class: 'muted small', text: lastSet ? `last full set: ${lastSet.id}` : 'no full backup set yet' }),
    h('div', { class: 'slot-grid', data: { part: 'slots' } }, tile(0), SLOTS.map(tile)),
    h('div', { class: 'slot-actions', data: { part: 'slot' } },
      h('div', { class: 'slot-title' }, h('strong', { text: slot === 0 ? 'Slot 0 (the live edit buffer)' : `Slot ${slot}` }),
        h('span', { class: 'muted', text: latest.get(`slot${slot}`) ? ` · newest backup ${latest.get(`slot${slot}`).id}` : ' · no backup yet' })),
      h('div', { class: 'row' },
        button('Back up', () => actions.backupSlot(), { data: { action: 'backup-slot' } }),
        button('Read', () => actions.readSlot(), { data: { action: 'read-slot' } })),
      slot === 0 ? h('div', { class: 'muted small', text: 'Slot 0 is the live edit buffer: activate a layout to play it there.' })
        : h('div', { class: 'row' },
          h('select', { data: { field: 'entry' }, onchange: (e) => actions.chooseEntry(e.target.value) },
            entries.map((name) => h('option', { value: name, selected: name === (view.entry || entries[0]), text: name }))),
          button(`Push to slot ${slot}`, () => actions.push(), { data: { action: 'push' }, disabled: !entries.length })),
      ofSlot.length ? h('div', { class: 'row' },
        h('select', { data: { field: 'backup' }, onchange: (e) => actions.chooseBackup(e.target.value) },
          ofSlot.map((b) => h('option', { value: b.id, selected: b.id === view.restoreBackup, text: b.id }))),
        button('Restore', () => actions.restore(ofSlot.some((b) => b.id === view.restoreBackup) ? view.restoreBackup : ofSlot[0].id),
          { data: { action: 'restore' }, title: `restore to slot ${slot}; its content is backed up first` })) : null,
      h('div', { class: 'row' },
        h('input', { type: 'text', placeholder: 'library name', value: view.captureName, data: { field: 'capture-name' },
          oninput: (e) => actions.draftCapture(e.target.value) }),
        button('Save to library', () => actions.capture(), { data: { action: 'capture' } })),
      view.slotView ? slotRecordView(view.slotView) : null),
    h('section', { class: 'lab-sub', data: { part: 'library' } },
      h('h3', { text: 'Library' }),
      h('ul', { class: 'lab-list' }, (view.library ?? []).map((e) => h('li', { data: { entry: e.name } },
        h('span', { class: 'name', text: e.name }),
        h('span', { class: 'muted', text: e.kind === 'definition' ? ` generated (${e.generator})`
          : e.kind === 'corrupt' ? ` corrupt: ${e.error}` : ` ${e.kind} from ${e.source ?? '?'}, ${e.pads} pads, ${e.strips} strips` }),
        e.kind === 'captured' || e.kind === 'imported'
          ? button('Preview', () => actions.preview(e.name), { data: { action: 'preview', entry: e.name },
            title: 'play it live in slot 0; Leave restores slot 0' }) : null))),
      h('div', { class: 'row' },
        h('input', { type: 'text', placeholder: 'name (default: the file name)', value: view.importName,
          data: { field: 'import-name' }, oninput: (e) => actions.draftImportName(e.target.value) }),
        h('label', { class: 'file-pick' }, 'Import .APC64 ', h('input', { type: 'file', accept: '.APC64,.apc64',
          data: { field: 'import-file' }, onchange: (e) => actions.importFile(e.target.files?.[0]) })))),
    h('section', { class: 'lab-sub', data: { part: 'backups' } },
      h('h3', { text: 'Backups' }),
      backupList(view)),
  ];
}

function backupList(view) {
  const all = [...(view.backups?.backups ?? [])].sort(newestFirst);
  if (!all.length) return h('div', { class: 'muted', text: 'No backups yet: every write backs up first.' });
  const shown = all.slice(0, 12);
  return h('div', {},
    h('ul', { class: 'lab-list backups' }, shown.map((b) => h('li', { data: { backup: b.id } },
      h('code', { text: b.id }), h('span', { class: 'muted', text: ` ${b.size} bytes` })))),
    all.length > shown.length ? h('div', { class: 'muted small', text: `${all.length - shown.length} older (apc64 lab backups)` }) : null);
}

export function slotRecordView(slot) {
  const rows = [];
  for (let row = 8; row >= 1; row--) {
    for (let column = 1; column <= 8; column++) {
      const pad = (slot.pads ?? [])[(row - 1) * 8 + (column - 1)];
      const off = !pad || (pad.rest === '#000000' && !pad.outputs);
      rows.push(h('div', { class: ['lab-pad', 'small', off && 'silent'], data: { pad: `r${row}c${column}`, rgb: pad?.rest ?? '' },
        style: off ? {} : { background: pad.rest },
        title: pad ? `r${row}c${column}: note ${pad.note} ch ${pad.channel} rest ${pad.rest} pressed ${pad.pressed}${pad.aftertouch ? ' aftertouch' : ''}` : '' }));
    }
  }
  return h('div', { class: 'slot-record', data: { part: 'slot-record' } },
    h('div', { class: 'muted small', text: `slot ${slot.slot} as read from the unit (colours as stored)` }),
    h('div', { class: 'lab-pads small' }, rows),
    h('div', { class: 'strips muted small', text: (slot.strips ?? []).map((s, k) => `strip ${k + 1}: cc ${s.cc} ch ${s.channel}`).join(' · ') }));
}

export function globalsView(model, view, actions) {
  const fields = view.globals?.fields ?? [];
  const control = (f) => {
    if (f.options) {
      const current = currentOption(f);
      const drafted = view.globalsDraft[f.field];
      return h('select', { data: { field: f.field }, onchange: (e) => actions.draftGlobal(f.field, e.target.value) },
        current ? null : h('option', { value: '', text: f.text, selected: drafted === undefined }),
        f.options.map(([value, text]) => h('option', { value: String(value), text,
          selected: drafted !== undefined ? String(drafted) === String(value) : current?.[0] === value })));
    }
    return h('input', { type: 'number', min: f.min, max: f.max, value: view.globalsDraft[f.field] ?? f.value,
      data: { field: f.field }, oninput: (e) => actions.draftGlobal(f.field, e.target.value) });
  };
  return [
    h('h2', {}, 'Global settings', h('span', { class: 'grow' }),
      button('Read', () => actions.readGlobals(), { data: { action: 'read-globals' } })),
    view.globalsProblem ? h('div', { class: 'muted', data: { problem: '' }, text: view.globalsProblem }) : null,
    fields.length ? h('table', { class: 'globals' }, fields.map((f) => h('tr', { data: { global: f.field } },
      h('th', {}, f.label, f.hazard ? h('span', { class: 'hazard', title: 'changing it needs a confirmation', text: ' ⚠' }) : null),
      h('td', { class: 'shown', text: f.text }),
      h('td', {}, control(f))))) : null,
    fields.length ? h('div', { class: 'row' },
      button('Apply changes', () => actions.applyGlobals(), { class: 'primary', data: { action: 'apply-globals' },
        title: 'one backup of the global block, then one write' })) : null,
    view.confirm ? h('div', { class: 'lab-confirm', data: { part: 'confirm' } },
      h('div', { text: view.confirm.problem }),
      button('Confirm and apply', () => actions.applyGlobals(true), { class: 'danger', data: { action: 'confirm-globals' } }),
      button('Cancel', () => actions.cancelConfirm(), { data: { action: 'cancel-confirm' } })) : null,
  ];
}

// Always there (two lines kept), so an answer appearing does not push the harmony views down.
export function resultView(view) {
  if (!view.result) {
    return h('div', { class: 'lab-result idle', data: { result: '' }, role: 'status',
      text: 'The answer to the last button shows here.' });
  }
  return h('div', { class: ['lab-result', view.result.ok ? 'ok' : 'bad'], data: { result: '' }, role: 'status',
    text: view.result.text });
}

// --- the performer (§2.10): on/off, pattern, play mode, latch, tempo or clock, Stop; the pattern as a grid --------
const PLAY_CHOICES = [['', 'pattern\'s'], ['all', 'all'], ['pressed', 'pressed']];

export function performerView(model, view, actions) {
  const p = performerOf(model, view);
  const heading = h('h2', {}, 'Performer', helpButton(PERFORMER_HELP, actions), h('span', { class: 'grow' }),
    sequencerButtons(actions));
  if (!p) return [heading, h('div', { class: 'muted', text: 'Loading the performer…' })];
  if (!p.available) return [heading, performerIdle()];
  if (sequencerShown(model)) return [heading, h('div', { class: 'muted', text: 'Shown in the sequencer view.' })];
  return [heading, ...performerBody(p, view, actions, { layoutKey: labOf(model, view)?.active?.key })];
}

const performerIdle = () => h('div', { class: 'muted', data: { performer: 'idle' },
  text: 'Activate a generated layout to play a pattern over what you hold.' });

// The sequencer is the page's current view (the host model's ui.view): the panel's editor steps aside meanwhile.
export function sequencerShown(model) {
  return model?.ui?.view?.name === SEQUENCER_VIEW;
}

// Beside the Performer "?": the sequencer view on this page, or in a tab of its own.
function sequencerButtons(actions) {
  return h('span', { class: 'view-btns' },
    button('Sequencer', () => actions.openSequencer(), { class: 'view-btn', data: { action: 'sequencer-open' },
      title: 'The pattern editor alone across the page, the grid large (Esc leaves)' }),
    h('a', { class: 'view-btn', href: SEQUENCER_ADDRESS, target: '_blank', rel: 'noopener', data: { action: 'sequencer-tab' },
      title: 'The sequencer in a tab of its own: bookmark it, or open the same address on a tablet', text: 'New tab ↗' }));
}

// The sequencer view: its heading (live, the pattern, the full-screen toggle and Leave), then the performer's controls
// and the editor with the grid large, the same parts as the panel's; nothing while the page shows something else.
export function sequencerFullPart(model, view, actions) {
  if (!sequencerShown(model)) return [];
  const p = performerOf(model, view);
  const head = h('header', { class: 'full-head' },
    h('h2', {}, h('span', { class: ['full-conn', model.connected && 'live'], title: model.connected ? 'Live' : 'Reconnecting…' }),
      'Sequencer', helpButton(PERFORMER_HELP, actions)),
    p?.available ? h('span', { class: 'seq-name', data: { part: 'sequencer-name' },
      text: `${p.pattern?.name ?? 'no pattern'}${p.pattern?.edited ? ' ●' : ''} · ${p.name}` }) : null,
    h('span', { class: 'grow' }),
    fullViewButtons(model, actions, 'full'));
  if (!p) return [head, h('div', { class: 'muted full-waiting', text: 'Loading the performer…' })];
  if (!p.available) return [head, performerIdle()];
  return [head, h('div', { class: 'seq-body' }, performerBody(p, view, actions,
    { large: true, layoutKey: labOf(model, view)?.active?.key }))];
}

// The performer's controls, chord types and slots, status and editor (the panel's and the sequencer's).
function performerBody(p, view, actions, { large = false, layoutKey = null } = {}) {
  const tempo = p.tempo ?? {};
  const valid = (p.patterns ?? []).filter((row) => row.valid);
  const inputs = (view.ports ?? []).filter((port) => port.present !== false && port.direction !== 'output'
    && port.direction !== 'declared' && !/apc64/i.test(port.name)).map((port) => port.name);
  const clocks = [...new Set([...inputs, ...(tempo.clock && tempo.clock !== 'auto' ? [tempo.clock] : [])])];
  const kept = (p.edits ?? []).find((e) => e.new);
  const following = tempo.source === 'clock';
  return [
    h('div', { class: 'performer-controls row', data: { part: 'performer-controls' } },
      button(p.enabled ? 'On' : 'Off', () => actions.setPerformer({ enabled: !p.enabled }), {
        class: ['view-btn', p.enabled && 'on'], 'aria-pressed': p.enabled ? 'true' : 'false', data: { action: 'performer-on' },
        title: p.enabled ? 'the performer plays a pattern over what you hold: click to play the pads as they are'
          : 'play the pads as they are: click to play a pattern over what you hold' }),
      h('label', {}, 'pattern ', h('select', { data: { field: 'performer-pattern' },
        title: '● an unsaved edit, kept until Save or Revert (while the service runs)',
        onchange: (e) => actions.choosePattern(e.target.value) },
      valid.map((row) => h('option', { value: row.id, selected: row.id === p.pattern?.id,
        text: row.edited ? `● ${row.name}` : row.name })),
      kept ? h('option', { value: NEW_PATTERN, selected: Boolean(p.pattern?.new), text: `● ${kept.name} (new)` }) : null)),
      h('label', {}, ' play ', h('select', { data: { field: 'performer-play' },
        title: 'all: an unpressed string rings open; pressed: only the strings you press play',
        onchange: (e) => actions.setPerformer({ play: e.target.value || null }) },
      PLAY_CHOICES.map(([value, label]) => h('option', { value, selected: (p.play_override ?? '') === value,
        text: value ? label : `${label} (${p.pattern?.play ?? 'all'})` })))),
      button(p.latch ? 'Latch on' : 'Latch off', () => actions.setPerformer({ latch: !p.latch }), {
        class: ['view-btn', p.latch && 'on'], 'aria-pressed': p.latch ? 'true' : 'false', data: { action: 'performer-latch' },
        title: 'on: the last chord keeps playing after you let go (the unit\'s Play)' }),
      button('Stop', () => actions.stopPerformer(), { data: { action: 'performer-stop' },
        title: 'stop the pattern now, its notes off (the unit\'s Stop)' })),
    h('div', { class: 'performer-tempo row', data: { part: 'performer-tempo' } },
      h('label', {}, 'tempo ', h('input', { type: 'number', min: 20, max: 300, step: 1, size: 4,
        value: following ? bpmText(tempo.measured ?? tempo.bpm) : (view.bpm ?? bpmText(tempo.bpm ?? 100)),
        data: { field: 'performer-bpm' }, disabled: following,
        title: following ? 'the clock sets the tempo' : 'applies as you change it (20–300)',
        oninput: (e) => actions.draftBpm(e.target.value), onchange: () => actions.applyBpm(),
        onkeydown: (e) => { if (e.key === 'Enter') actions.applyBpm(); } }), ' BPM'),
      h('label', {}, ' clock ', h('select', { data: { field: 'performer-clock' },
        title: 'follow the MIDI clock of an input (the MPC sends it while its sequencer plays); internal: the BPM here',
        onchange: (e) => actions.setPerformer(e.target.value ? { clock: e.target.value } : { bpm: tempo.bpm ?? 100 }) },
      h('option', { value: '', selected: !following, text: 'internal' }),
      h('option', { value: 'auto', selected: following && tempo.clock === 'auto', text: 'auto (the first input with a clock)' }),
      clocks.map((port) => h('option', { value: port, selected: following && tempo.clock === port, text: port }))))),
    following ? h('div', { class: ['muted', 'small', tempo.measured ? 'clock-ok' : 'clock-wait'],
      data: { part: 'performer-clock-status' }, text: clockStatus(tempo) }) : null,
    chordsView(p, actions, layoutKey),
    h('div', { class: 'muted small', data: { part: 'performer-status' }, text: performerStatus(p) }),
    p.message ? h('div', { class: 'lab-message', text: p.message }) : null,
    p.pattern || view.draft ? patternEditor(p, view, actions, { large }) : null,
    patternConfirmView(view, actions),
  ];
}

// The key (the layout's scale, for the session), chord types (a single note held is the root of the chord chosen; key
// and key 7 the key's own) and the layout's pattern slots (Phase 2).
export const KEY_TONICS = ['C', 'D♭', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];
export const KEY_SCALES = [['major', 'major'], ['dorian', 'dorian'], ['phrygian', 'phrygian'], ['lydian', 'lydian'],
  ['mixolydian', 'mixolydian'], ['aeolian', 'minor'], ['locrian', 'locrian'], ['harmonic-minor', 'harmonic minor'],
  ['melodic-minor', 'melodic minor']];
const KEY_TYPES = ['key', 'key 7'];

export function keyView(p, actions, layoutKey = null) {
  const key = p.key;
  const tonic = key ? KEY_TONICS.find((t) => t.replace('♭', 'b').replace('♯', '#') === key.tonic
    || t === key.tonic) ?? key.tonic : '';
  const scale = key?.scale ?? 'major';
  const scales = KEY_SCALES.some(([k]) => k === scale) ? KEY_SCALES : [...KEY_SCALES, [scale, scale.replace(/-/g, ' ')]];
  const session = Boolean(layoutKey?.session);
  return h('div', { class: 'row key-choice', role: 'group', 'aria-label': 'key', data: { part: 'performer-key' } },
    h('span', { class: 'muted small', text: 'key' }),
    h('select', { data: { field: 'key-tonic' }, title: 'the key for the session (the layout\'s scale; not its file)',
      onchange: (e) => actions.setKey(e.target.value || null, scale) },
    h('option', { value: '', selected: !key, text: 'none' }),
    KEY_TONICS.map((t) => h('option', { value: t, selected: t === tonic, text: t }))),
    h('select', { data: { field: 'key-scale' }, disabled: !key,
      onchange: (e) => actions.setKey(tonic, e.target.value) },
    scales.map(([k, label]) => h('option', { value: k, selected: k === scale, text: label }))),
    h('span', { class: 'muted small', data: { part: 'key-source' }, text: session
      ? `for the session · the file: ${layoutKey.file ?? 'none'}` : (key ? 'the layout\'s' : 'chromatic: no key') }),
    session ? button('file', () => actions.resetKey(), { class: 'link', data: { action: 'key-reset' },
      title: 'the layout\'s key, as its file says' }) : null,
    key && !key.chords ? h('span', { class: 'muted small', text: '· key chords need a seven-note scale' }) : null);
}

export function chordsView(p, actions, layoutKey = null) {
  const chords = p.chords ?? {};
  const slots = (p.slots ?? []).filter(Boolean);
  if (!chords.available && !slots.length) return null;
  const voicing = p.voicing;
  const keyed = Boolean(p.key?.chords);
  return h('div', { class: 'performer-chords', data: { part: 'performer-chords' } },
    chords.available ? keyView(p, actions, layoutKey) : null,
    chords.available ? h('div', { class: 'row chord-types', role: 'group', 'aria-label': 'chord type' },
      h('span', { class: 'muted small', text: 'chord' }),
      (chords.types ?? []).map((name) => button(name, () => actions.chooseType(chords.selected === name ? null : name), {
        class: ['view-btn', 'type-btn', chords.selected === name && 'on', KEY_TYPES.includes(name) && 'key-type'],
        'aria-pressed': chords.selected === name ? 'true' : 'false',
        data: { type: name }, disabled: KEY_TYPES.includes(name) && !keyed && chords.selected !== name,
        title: chords.selected === name ? `${name}: click for off (fretted)`
          : KEY_TYPES.includes(name) ? (keyed ? `${name}: the key's own ${name === 'key' ? 'triad' : 'seventh'} on the note `
            + 'you press; a note out of key plays nothing' : `${name}: choose a key of seven notes first`)
            : `${name}: one note you press is the root of this chord` })),
      button('off', () => actions.chooseType(null), { class: ['view-btn', 'type-btn', !chords.selected && 'on'],
        'aria-pressed': chords.selected ? 'false' : 'true', data: { type: 'off' }, title: 'off: what you fret plays' }),
      h('span', { class: 'voicing small', data: { part: 'voicing' },
        text: voicing ? `${voicing.symbol} ${voicing.shape}` : (chords.selected ? 'press one note: the root' : '') })) : null,
    slots.length ? h('div', { class: 'row pattern-slots', role: 'group', 'aria-label': 'pattern slot' },
      h('span', { class: 'muted small', text: 'slots' }),
      slots.map((slot) => button(`${slot.slot} ${slot.name}${slot.edited ? ' ●' : ''}`, () => actions.chooseSlot(slot.slot), {
        class: ['view-btn', 'slot-btn', p.slot === slot.slot && 'on', !slot.valid && 'bad'],
        'aria-pressed': p.slot === slot.slot ? 'true' : 'false', data: { slot: slot.slot }, disabled: !slot.valid,
        title: slot.valid ? `slot ${slot.slot}: ${slot.name}` : `slot ${slot.slot}: no pattern "${slot.pattern}"` }))) : null,
    p.pads ? h('div', { class: 'muted small', text: `pads: ${p.pads}` }) : null);
}

const bpmText = (bpm) => String(Math.round((bpm ?? 100) * 10) / 10);

// What the clock followed is doing, plainly: waiting for it (and where the MPC sends it), following it, or stopped.
export function clockStatus(tempo) {
  const following = tempo.following;
  const heard = (tempo.heard ?? []).filter((port) => port !== following);
  const also = heard.length ? ` · a clock was heard lately from ${heard.join(', ')}` : '';
  if (tempo.measured) return `following ${following}: ${Number(tempo.measured).toFixed(1)} BPM${also}`;
  if (tempo.stopped) return `the clock stopped; keeping ${Number(tempo.bpm).toFixed(1)} BPM${also}`;
  const from = following ?? (tempo.clock === 'auto' ? 'any input' : tempo.clock);
  return `no clock heard from ${from} yet — the MPC sends its clock while its sequencer plays, to the outputs its `
    + `sync settings send clock to${also}`;
}

export function performerStatus(p) {
  const parts = [p.enabled ? (p.running ? `playing · step ${p.step}/${p.length}` : 'waiting for a press') : 'off',
    p.addressing === 'voices' ? 'lanes are the held notes from the top' : 'a lane per string'];
  if (p.controls) parts.push(p.controls);
  return parts.join(' · ');
}

// The pattern, read-only: a row per lane (the string's name, or the voice), a column per step, the bars marked, the
// playing step lit; manual lanes say so. (The panel draws the editor, performer_editor.js; this stays for a page
// that only shows a pattern.)
export function patternGrid(p) {
  const pattern = p.pattern;
  const labels = new Map((p.lanes ?? []).map((lane) => [lane.lane, lane.label]));
  const steps = Array.from({ length: pattern.length }, (_, k) => k);
  const playing = p.running ? (p.step ?? 0) - 1 : -1;
  const cellClass = (k) => [k === playing && 'now', pattern.bar && k && k % pattern.bar === 0 && 'bar'];
  const mark = { '.': '', x: '●', X: '◉', d: '↓', u: '↑' };
  return h('table', { class: 'pattern-grid', data: { part: 'pattern-grid' },
    'aria-label': `${pattern.name}: ${pattern.meter}, ${pattern.step} steps` },
  h('caption', { class: 'muted small', text: `${pattern.name} · ${pattern.meter} · ${pattern.step} · ${pattern.length} steps`
    + (pattern.description ? ` · ${pattern.description}` : '') }),
  h('tr', {}, h('th', {}), steps.map((k) => h('th', { class: cellClass(k), text: String(k + 1) }))),
  pattern.lanes.map((lane) => h('tr', { class: lane.manual && 'manual', data: { lane: lane.lane } },
    h('th', { text: labels.get(lane.lane) ?? `lane ${lane.lane}` }),
    lane.manual ? h('td', { class: 'manual-note', colspan: pattern.length, text: 'manual: played as you press' })
      : steps.map((k) => h('td', { class: [...cellClass(k), lane.cells[k] === 'X' && 'accent', lane.cells[k] === 'x' && 'hit'],
        data: { cell: lane.cells[k] }, text: mark[lane.cells[k]] ?? '' })))),
  pattern.strum ? h('tr', { class: 'strum' }, h('th', { text: 'strum' }),
    steps.map((k) => h('td', { class: cellClass(k), text: mark[pattern.strum[k]] ?? '' }))) : null);
}

// --- mounting into the host page -------------------------------------------------------------------------------
const harmonyKey = (m, v) => [harmonyOf(m, v), labOf(m, v)?.active?.pads, labOf(m, v)?.active?.definition,
  labOf(m, v)?.active?.rows, labOf(m, v)?.active?.scale, labOf(m, v)?.active?.neck, v.leftHanded, inputsOf(m, v), v.ports,
  labOf(m, v)?.active ? null : m?.state?.controls];

const performerKey = (m, v) => [steady(performerOf(m, v)), labOf(m, v)?.active?.key, v.ports, v.bpm, v.draft, v.saveAs,
  v.patternConfirm];

const PARTS = [
  ['status', (m, v, a) => statusHeadView(m, v, a), (m, v) => [labOf(m, v), v.base]],
  // the playhead and the status line are marked on the drawn part (markPlayhead), so a step redraws nothing
  ['performer', (m, v, a) => performerView(m, v, a), (m, v) => [sequencerShown(m), ...(sequencerShown(m) ? []
    : performerKey(m, v))]],
  ['lists', (m, v, a) => listsView(m, v, a), (m, v) => [labOf(m, v)?.layouts, labOf(m, v)?.active?.layout,
    labOf(m, v)?.generators, labOf(m, v)?.schemes, v.library]],
  ['result', (m, v) => resultView(v), (m, v) => [v.result]],
  ['harmony', (m, v, a) => harmonySectionView(m, v, a), (m, v) => [fullViewShown(m), ...(fullViewShown(m) ? [] : harmonyKey(m, v))]],
  ['memory', (m, v, a) => memoryView(m, v, a), (m, v) => [v.backups, v.library, v.slot, v.slotView]],
  ['globals', (m, v, a) => globalsView(m, v, a), (m, v) => [v.globals, v.globalsProblem, v.confirm]],
  // the full views: each its own element at the end of <body>, drawn only while it is shown
  ['full', (m, v, a) => harmonyFullPart(m, v, a), (m, v) => (fullViewShown(m)
    ? [m.ui.view, m.ui.fullscreen, m.connected, v.mainView, ...harmonyKey(m, v)] : null)],
  ['sequencer', (m, v, a) => sequencerFullPart(m, v, a), (m, v) => (sequencerShown(m)
    ? [m.ui.view, m.ui.fullscreen, m.connected, ...performerKey(m, v)] : null)],
];

export function renderParts(containers, model, controller, memo, doc = globalThis.document) {
  followPerformer(controller.view, performerOf(model, controller.view));
  for (const [name, view, key] of PARTS) {
    if (!containers[name]) continue;
    const k = JSON.stringify(key(model, controller.view));
    if (memo.get(name) === k) continue;
    memo.set(name, k);
    const focused = focusedField(containers[name], doc);
    mount(containers[name], view(model, controller.view, controller.actions) ?? [], doc);
    if (focused) refocus(containers[name], focused);
  }
  const performer = performerOf(model, controller.view);
  if (performer?.available) {
    markPlayhead(sequencerShown(model) ? containers.sequencer : containers.performer, performer, performerStatus(performer));
  }
  containers.full?.classList?.toggle('current', fullViewShown(model));
  containers.sequencer?.classList?.toggle('current', sequencerShown(model));
}

// A redraw keeps the focus on the field that had it (the tempo while its arrows are clicked, a pattern field).
function focusedField(container, doc) {
  const active = doc?.activeElement;
  const field = active?.dataset?.field;
  if (!field || !container?.contains?.(active)) return null;
  return { field, start: active.selectionStart ?? null, end: active.selectionEnd ?? null };
}

function refocus(container, { field, start, end }) {
  const el = container.querySelector?.(`[data-field="${field}"]`);
  if (!el?.focus) return;
  el.focus();
  try {
    if (start !== null && el.setSelectionRange) el.setSelectionRange(start, end);
  } catch {
    // a number input has no selection; the focus is enough
  }
}

// The performer's state without what changes at every step (the playhead, the running flag, the timer's lateness).
function steady(p) {
  if (!p) return p;
  const { step, running, timing, ...rest } = p;
  return rest;
}

function ensureStyles(doc, href) {
  if (!doc?.head || doc.getElementById?.(STYLE_ID)) return;
  const link = doc.createElement('link');
  link.id = STYLE_ID;
  link.rel = 'stylesheet';
  link.href = href;
  doc.head.appendChild(link);
}

export function mountPanel(element, { store, api, handlers, panel } = {}, { doc = globalThis.document, schedule } = {}) {
  const base = String(panel?.entry ?? '/modules/lab/lab.js').replace(/[^/]*$/, '');
  ensureStyles(doc, `${base}lab.css`);
  element.classList?.add('lab-panel');
  const containers = {};
  for (const [name] of PARTS) {
    const part = doc.createElement('div');
    if (name === 'full' || name === 'sequencer') {
      // outside the side column, so it shows whichever panel is chosen beside the surface
      const harmony = name === 'full';
      part.className = `module-view lab-panel ${harmony ? 'harmony-full' : 'sequencer-full'}`;
      part.setAttribute?.('aria-label', harmony ? 'Harmony full view' : 'Sequencer');
      part.dataset.view = harmony ? HARMONY_VIEW : SEQUENCER_VIEW;
      (doc.body ?? element).appendChild(part);
    } else {
      part.className = `lab-part lab-${name}`;
      element.appendChild(part);
    }
    containers[name] = part;
  }
  const memo = new Map();
  let queued = false;
  const later = schedule ?? ((fn) => (globalThis.requestAnimationFrame ? globalThis.requestAnimationFrame(fn) : setTimeout(fn, 0)));
  const render = () => { queued = false; renderParts(containers, store.model, controller, memo, doc); };
  const request = () => { if (!queued) { queued = true; later(render); } };
  const controller = createLab({ api, onChange: request, help: handlers?.help, page: handlers });
  // after the WebSocket reconnects (a service restart), fetch everything again: the lists the panel fetched at
  // mount may be stale (the hub greets the page with the pushed state, not with the backups or the library)
  // likewise the library's list when the generated layouts change (a file added, removed or fixed)
  let connected = store?.model?.connected;
  let layouts = JSON.stringify(topic(store?.model, 'lab')?.layouts ?? null);
  let reloads = Promise.resolve();
  store?.subscribe?.(() => {
    const now = store.model?.connected;
    const listed = JSON.stringify(topic(store.model, 'lab')?.layouts ?? null);
    if (now && connected === false) reloads = controller.actions.load().catch(() => {}).then(request);
    else if (listed !== layouts) reloads = controller.actions.refreshLists().catch(() => {}).then(request);
    connected = now;
    layouts = listed;
    request();
  });
  render();
  const ready = controller.actions.load().catch(() => {}).then(request);
  return { controller, render, ready, containers, reloaded: () => reloads };
}
