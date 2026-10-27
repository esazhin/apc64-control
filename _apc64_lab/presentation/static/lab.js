// The lab panel (contract pi7, A21, A81; s25, s26, s27): the column beside the host page's surface when 'Lab' is
// chosen. It shows, each with its current state: the generated layouts, generators and colour schemes; the active
// layout with its interval and offset and 'encoder: shift · Tempo: interval'; the harmony views; the backups, the
// 24 slots and the library; the global settings. Every control calls the same /api/lab route as `apc64 lab`, and
// every answer's message (or problem) is shown verbatim. Bulk edits are the agent's: the page shows their results
// (a slot read, the library) but has no multi-select editor (§2.5, §2.7 q1).
//
// The host page imports this module once and calls mountPanel(element, {store, api, handlers, panel}). The lab
// state and the harmony arrive on the /ws 'lab' topic (kinds 'lab' and 'harmony'); the panel reads them from the
// host store's topics, and fetches them once at mount for a page that connected before anything was published.
// Its "?" buttons open the host page's one help overlay (handlers.help, the host's help.js) with the topics below.
import { h, mount } from './lab_dom.js';
import { harmonyView } from './harmony_views.js';

export const UNIT_HINT = 'encoder: shift · Tempo: interval';
export const SLOTS = Array.from({ length: 24 }, (_, k) => k + 1);
const STYLE_ID = 'lab-panel-style';

// --- help (the host's overlay shows them: {title, items: [[term, text] | text]}) ----------------------------
export const LAB_HELP = {
  id: 'lab',
  title: 'The lab',
  items: [
    ['Generated layouts', 'Layout files with a lab: section. A generator lays out the 64 pads and a colour scheme '
      + 'lights them. Activate backs up the unit\'s live edit buffer (slot 0), writes the pads there and you play '
      + 'them in the unit\'s own Custom view, with velocity and aftertouch.'],
    ['Window', 'The encoder (on the unit, or ◀ ▶ here) moves every pad one step of the current interval; Tempo '
      + 'switches the interval: octave → fifth → third. “oct / 5th / 3rd” count the steps taken in each; the OLED '
      + 'shows the name and the window, e.g. “5th +2”. Shift + encoder still browses host layouts.'],
    ['base, scheme', 'base is the note on the bottom-left pad (a number or a name like C2: Enter or Save); scheme '
      + 'picks the colours. Each changes one line of the layout file, which reloads at the same window.'],
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
    ['Chord', 'The name of the held notes, and the trail: the last 8 triads played.'],
    ['Hints', 'Hold one note: its interval to every other note, and the triads that contain it. Hold a major or '
      + 'minor triad: its neighbours P, R and L (parallel, relative, leading-tone), the triads sharing two of its notes.'],
    ['Pads', 'The 64 pads in the colours written to the unit (approximate ones when no generated layout is '
      + 'active); the held notes light up.'],
    ['Circle, Tonnetz', 'The circle of fifths joins the held notes. On the Tonnetz fifths go right, major thirds '
      + 'up-right and minor thirds up-left; every triangle is a triad, ▲ major and ▼ minor.'],
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
    ports: () => call('GET', '/api/ports'),
    activate: (layout) => call('POST', '/api/lab/activate', { layout }),
    leave: () => call('POST', '/api/lab/leave', {}),
    tweak: (field, value) => call('POST', '/api/lab/tweak', { field, value }),
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
  };
}

// --- the panel's own state and actions -----------------------------------------------------------------------
export function initialView() {
  return {
    lab: null, harmony: null, backups: null, library: null, globals: null, globalsProblem: null, ports: null,
    inputs: null, slot: 1, entry: '', restoreBackup: null, base: null, slotView: null, captureName: '', importName: '',
    globalsDraft: {}, confirm: null, result: null,
  };
}

const answerText = (answer) => (answer.ok ? (answer.data?.message ?? 'done') : answer.problem);

export function createLab({ api, onChange = () => {}, readFile = null, help = null } = {}) {
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
    async load() {
      const [state, harmony, inputs, ports] = await Promise.all([lab.state(), lab.harmony(), lab.inputs(), lab.ports()]);
      set({ lab: state.ok ? state.data : null, harmony: harmony.ok ? harmony.data : null,
        inputs: inputs.ok ? inputs.data : null, ports: ports.ok ? ports.data : null });
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
      if (answer.ok) set({ result: { ok: true, text: 'Tempo: next interval' } });
      return answer;
    }),
    draftBase: (value) => { view.base = value; },
    saveBase: () => act(() => lab.tweak('base', numberOrText(view.base ?? '')), refreshLab),
    setScheme: (scheme) => act(() => lab.tweak('scheme', scheme), refreshLab),
    dismissRecovery: () => act(() => lab.dismissRecovery(), refreshLab),
    restoreRecovery: (backup) => act(() => lab.restore(backup, 0), async () => { await refreshLab(); await refreshLists(); }),
    // harmony inputs (§2.7 q7)
    toggleInput: async (port, on) => {
      const current = view.inputs?.inputs ?? [];
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
  };
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

export function statusView(model, view, actions) {
  const lab = labOf(model, view);
  if (!lab) return h('div', { class: 'lab-loading muted', text: 'Loading the lab…' });
  const active = lab.active;
  const target = lab.target ?? {};
  const layouts = (view.library ?? []).filter((e) => e.kind === 'definition');
  return [
    h('h2', {}, 'Lab', helpButton(LAB_HELP, actions), h('span', { class: 'grow' }),
      h('span', { class: ['lab-target', target.routed === false && 'warn'], data: { target: '' },
        text: target.text ? `notes → ${target.text}` : target.default ? `default note target: ${target.default}`
          : 'notes are only shown: no default target' })),
    lab.message ? h('div', { class: 'lab-message', data: { message: '' }, text: lab.message }) : null,
    lab.recovery ? h('div', { class: 'lab-recovery' }, h('div', { text: lab.recovery.message }),
      button(`Restore slot 0 from ${lab.recovery.backup}`, () => actions.restoreRecovery(lab.recovery.backup),
        { class: 'primary', data: { action: 'restore-recovery' } }),
      button('Dismiss', () => actions.dismissRecovery(), { data: { action: 'dismiss-recovery' } })) : null,
    (lab.warnings ?? []).map((w) => h('div', { class: 'lab-warning', text: `start-up: ${w}` })),
    activeView(lab, view, actions),
    h('section', { class: 'lab-sub', data: { part: 'layouts' } },
      h('h3', { text: 'Generated layouts' }),
      layouts.length ? h('ul', { class: 'lab-list' }, layouts.map((e) => h('li', {
        class: active && active.layout === e.layout && 'current', data: { layout: e.layout } },
      h('span', { class: 'name', text: e.name }), h('span', { class: 'muted', text: ` ${e.generator} · ${e.layout}.yaml` }),
      button(active && active.layout === e.layout ? 'Active' : 'Activate', () => actions.activate(e.name),
        { data: { action: 'activate', layout: e.name }, disabled: active && active.layout === e.layout }))))
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
  return h('section', { class: 'lab-active', data: { part: 'active' } },
    h('div', { class: 'active-head' },
      h('div', { class: 'oled', title: 'the unit\'s OLED' }, h('div', { text: row1 }), h('div', { text: row2 })),
      h('div', { class: 'active-what' },
        h('div', { class: 'active-name', text: active.preview ? `${active.name} (preview)` : active.name }),
        h('div', { class: 'window', data: { window: '' } },
          h('span', { class: 'interval', text: `${active.interval} ${signed(active.offset)}` }),
          h('span', { class: 'muted', text: ` · oct ${signed(counts.octave)} · 5th ${signed(counts.fifth)} · 3rd ${signed(counts.third)}` })),
        h('div', { class: 'unit-hint', text: UNIT_HINT }),
        h('div', { class: 'muted small', text: `view ${active.unit_view ?? 'unknown'} · session backup ${active.session_backup ?? 'pending'}` }))),
    h('div', { class: 'active-controls' },
      button('◀ encoder', () => actions.turn(-1), { data: { action: 'turn-left' }, title: 'one step of the interval down' }),
      button('encoder ▶', () => actions.turn(1), { data: { action: 'turn-right' }, title: 'one step of the interval up' }),
      button('Tempo', () => actions.tempo(), { data: { action: 'tempo' }, title: 'next interval: octave → fifth → third' }),
      button('Leave', () => actions.leave(), { class: 'danger', data: { action: 'leave' },
        title: 'restore slot 0 from the session backup' })),
    definition ? h('div', { class: 'active-tweaks' },
      h('label', {}, 'base ', h('input', { type: 'text', size: 5, value: view.base ?? String(definition.params?.base ?? ''),
        data: { field: 'base' }, oninput: (e) => actions.draftBase(e.target.value),
        onkeydown: (e) => { if (e.key === 'Enter') actions.saveBase(); } })),
      button('Save', () => actions.saveBase(), { data: { action: 'save-base' } }),
      h('label', {}, ' scheme ', h('select', { data: { field: 'scheme' }, onchange: (e) => actions.setScheme(e.target.value) },
        schemes.map((s) => h('option', { value: s.name, selected: s.name === definition.scheme, text: s.name }))))) : null);
}

function signed(n) {
  const value = Number(n ?? 0);
  return value >= 0 ? `+${value}` : String(value);
}

export function harmonySectionView(model, view, actions) {
  const lab = labOf(model, view);
  const harmony = harmonyOf(model, view);
  const pads = lab?.active?.pads;
  const controls = model?.state?.controls ?? {};
  const fallback = (id) => controls[id]?.led && !controls[id].led.off ? controls[id].led.rgb : null;
  const following = view.inputs?.inputs ?? [];
  const candidates = (view.ports ?? []).filter((p) => p.present !== false && p.direction !== 'output'
    && p.direction !== 'declared' && !/apc64/i.test(p.name)).map((p) => p.name);
  const ports = [...new Set([...candidates, ...following])];
  return [
    h('h2', {}, 'Harmony', helpButton(HARMONY_HELP, actions)),
    h('div', { class: 'inputs', data: { part: 'inputs' } },
      h('span', { class: 'muted', text: 'follows: APC64 Custom + Notes' }),
      ports.map((port) => h('label', { class: 'input-choice' },
        h('input', { type: 'checkbox', checked: following.includes(port), data: { input: port },
          onchange: (e) => actions.toggleInput(port, e.target.checked) }), ` ${port}`))),
    harmony ? harmonyView(harmony, pads, fallback) : h('div', { class: 'muted', text: 'Waiting for the play stream…' }),
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

// --- mounting into the host page -------------------------------------------------------------------------------
const PARTS = [
  ['status', (m, v, a) => statusView(m, v, a), (m, v) => [labOf(m, v), v.library, v.base]],
  ['result', (m, v) => resultView(v), (m, v) => [v.result]],
  ['harmony', (m, v, a) => harmonySectionView(m, v, a), (m, v) => [harmonyOf(m, v), labOf(m, v)?.active?.pads,
    v.inputs, v.ports, labOf(m, v)?.active ? null : m?.state?.controls]],
  ['memory', (m, v, a) => memoryView(m, v, a), (m, v) => [v.backups, v.library, v.slot, v.slotView]],
  ['globals', (m, v, a) => globalsView(m, v, a), (m, v) => [v.globals, v.globalsProblem, v.confirm]],
];

export function renderParts(containers, model, controller, memo, doc = globalThis.document) {
  for (const [name, view, key] of PARTS) {
    const k = JSON.stringify(key(model, controller.view));
    if (memo.get(name) === k) continue;
    memo.set(name, k);
    mount(containers[name], view(model, controller.view, controller.actions) ?? [], doc);
  }
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
    part.className = `lab-part lab-${name}`;
    element.appendChild(part);
    containers[name] = part;
  }
  const memo = new Map();
  let queued = false;
  const later = schedule ?? ((fn) => (globalThis.requestAnimationFrame ? globalThis.requestAnimationFrame(fn) : setTimeout(fn, 0)));
  const render = () => { queued = false; renderParts(containers, store.model, controller, memo, doc); };
  const request = () => { if (!queued) { queued = true; later(render); } };
  const controller = createLab({ api, onChange: request, help: handlers?.help });
  store?.subscribe?.(request);
  render();
  const ready = controller.actions.load().catch(() => {}).then(request);
  return { controller, render, ready, containers };
}
