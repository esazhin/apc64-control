// The page model: a pure reducer over the /ws messages (snapshot, diff, activity, activity_list) and the page's
// own actions (selection, card, problems, play/inspect mode, Shift preview, overview). A (re)connect's snapshot
// replaces the whole state at once (d160, A131). No DOM here: everything is testable under node --test.

export const ACTIVITY_LIMIT = 200;
export const SIDE_PANELS = ['overview', 'card', 'none'];
const MODULE_NAME = /^[a-z][a-z0-9_-]*$/;

// Contract 2 (a13): registered modules' panels, from the state ({name, title, entry}); none in contract 1.
export function modulePanels(model) {
  return Array.isArray(model.state?.modules) ? model.state.modules : [];
}

// Every choice for the column beside the surface: the host's own, each module panel, then 'none'.
export function sidePanels(model) {
  return ['overview', 'card', ...modulePanels(model).map((m) => m.name), 'none'];
}

// The module panel shown beside the surface, or null.
export function currentModulePanel(model) {
  return modulePanels(model).find((m) => m.name === model.ui.side) ?? null;
}

// The latest payload a module published on its topic (the hub greets a new page with them), by kind.
export function topicData(model, topic, kind = '_') {
  return model.topics?.[topic]?.[kind] ?? null;
}

function withSide(model, panel) {
  const { pendingSide, ...ui } = model.ui;
  return { ...model, ui: { ...ui, side: panel } };
}

export function initialModel() {
  return {
    connected: false,
    state: null,
    activity: [],
    ui: {
      selected: null, // the control whose card is shown
      mode: 'play', // 'play': a click presses the control (as on the unit); 'inspect': a click only selects
      previewShift: false, // the page's Shift button is held
      card: null,
      cardProblem: null,
      problem: null, // the last refusal, shown plainly until dismissed
      issues: [],
      notice: null, // the last success worth saying ('Saved')
      overview: null,
      overviewLayer: 'base',
      ports: [], // MIDI ports for MIDI-learn
      tweakLayer: null, // the layer the tweak form edits (null: the shown layer)
      tweakAnswer: null, // {tone: 'ok'|'bad'|'stale', text, issues}
      navCollapsed: false, // the layout / page / bank bar folded to one line (remembered per viewer)
      side: 'overview', // the column beside the surface: 'overview', 'card' (card + activity) or 'none' (remembered)
      help: null, // the open help topic ({title, items}; help.js), or null
    },
  };
}

function withUi(model, patch) {
  return { ...model, ui: { ...model.ui, ...patch } };
}

function followLearn(model, previous) {
  // learn by touch: a touch on the unit selects the control and opens its card (A132)
  const learn = model.state?.learn;
  if (!learn || learn.mode === 'off' || !learn.selected) return model;
  if (previous?.learn?.selected === learn.selected) return model; // nothing new was touched
  if (model.ui.selected === learn.selected) return model;
  return withUi(model, { selected: learn.selected, card: null, cardProblem: null, tweakLayer: null, tweakAnswer: null });
}

export function reduce(model, action) {
  switch (action.type) {
    case 'snapshot': {
      let next = { ...model, connected: true, state: action.data };
      // a module panel remembered from the last visit is shown once the state lists it
      if (next.ui.pendingSide && sidePanels(next).includes(next.ui.pendingSide)) next = withSide(next, next.ui.pendingSide);
      return followLearn(next, model.state);
    }
    case 'diff': {
      if (!model.state) return model;
      const { changed = {}, controls = {} } = action.data;
      const state = { ...model.state, ...changed };
      if (Object.keys(controls).length) state.controls = { ...model.state.controls, ...controls };
      return followLearn({ ...model, state }, model.state);
    }
    case 'activity_list':
      return { ...model, activity: action.data.slice(0, ACTIVITY_LIMIT) };
    case 'activity': {
      const record = action.data;
      const index = record.id === null || record.id === undefined
        ? -1 : model.activity.findIndex((r) => r.id === record.id);
      if (index >= 0) {
        const activity = model.activity.slice();
        activity[index] = record; // an aftertouch fold updates its note's entry in place (q7)
        return { ...model, activity };
      }
      return { ...model, activity: [record, ...model.activity].slice(0, ACTIVITY_LIMIT) };
    }
    case 'disconnected':
      return { ...model, connected: false };
    case 'select':
      if (action.id === model.ui.selected) return model;
      return withUi(model, { selected: action.id, card: null, cardProblem: null, tweakLayer: null, tweakAnswer: null });
    case 'card':
      if (action.id !== model.ui.selected) return model;
      return withUi(model, { card: action.data, cardProblem: null });
    case 'card_problem':
      return withUi(model, { cardProblem: action.problem });
    case 'problem':
      return withUi(model, { problem: action.problem, issues: action.issues ?? [], notice: null });
    case 'notice':
      return withUi(model, { notice: action.text, problem: null, issues: [] });
    case 'dismiss':
      return withUi(model, { problem: null, issues: [], notice: null });
    case 'mode':
      return withUi(model, { mode: action.mode === 'inspect' ? 'inspect' : 'play' });
    case 'preview_shift':
      return withUi(model, { previewShift: Boolean(action.held) });
    case 'overview':
      return withUi(model, { overview: action.data });
    case 'ports':
      return withUi(model, { ports: action.data ?? [] });
    case 'tweak_layer':
      return withUi(model, { tweakLayer: action.layer === 'shift' ? 'shift' : 'base', tweakAnswer: null });
    case 'tweak_answer':
      return withUi(model, { tweakAnswer: action.answer });
    case 'nav_collapsed':
      return withUi(model, { navCollapsed: Boolean(action.collapsed) });
    case 'side':
      if (SIDE_PANELS.includes(action.panel) || sidePanels(model).includes(action.panel)) {
        return model.ui.pendingSide === undefined ? withUi(model, { side: action.panel }) : withSide(model, action.panel);
      }
      if (!model.state && typeof action.panel === 'string' && MODULE_NAME.test(action.panel)) {
        return withUi(model, { side: 'overview', pendingSide: action.panel }); // a module panel, before the state
      }
      return withUi(model, { side: 'overview' });
    case 'topic': {
      if (typeof action.topic !== 'string') return model;
      const kind = action.data?.kind ?? '_';
      const topics = { ...(model.topics ?? {}) };
      topics[action.topic] = { ...(topics[action.topic] ?? {}), [kind]: action.data };
      return { ...model, topics };
    }
    case 'help':
      return action.topic?.title ? withUi(model, { help: action.topic }) : model;
    case 'help_close':
      return model.ui.help ? withUi(model, { help: null }) : model;
    case 'overview_layer':
      return withUi(model, { overviewLayer: action.layer === 'shift' ? 'shift' : 'base' });
    default:
      return model;
  }
}

// --- selectors ------------------------------------------------------------------------------------------
export function shiftShown(model) {
  return Boolean(model.state?.shift || model.ui.previewShift);
}

export function layerOf(model) {
  return shiftShown(model) ? 'shift' : 'base';
}

export function controlState(model, id) {
  return model.state?.controls?.[id] ?? null;
}

// The unit's current view (PROTOCOL-SPEC §4.5): 'session', 'note', 'chord', 'step', 'custom', …
export function unitView(model) {
  return model.state?.unit?.view ?? 'session';
}

// What the unit keeps to itself in its current view (PROTOCOL-SPEC §4.6, §5; NOTES-daw-mode.md): outside
// Session view the pad grid is the unit's (it draws and plays it; the host never does); in Custom view the side
// buttons, strips and encoder are too, as only Shift and Tempo (note 72) still reach the host. In Note, Chord and
// Step view every button and strip still reaches the host. The page shows these as the unit's and never presses
// them.
export function ownedByUnit(model, id) {
  const view = unitView(model);
  if (view === 'session' || !id) return false;
  if (/^pad r\dc\d$/.test(id)) return true;
  if (view !== 'custom') return false;
  // contract 2: the encoder turn does reach the host in Custom view (NOTES-daw-mode 2026-10-24); when a module
  // action binds it (a generated layout's window shift), the page's encoder turns it like the unit's (A37)
  if (id === 'encoder' && controlState(model, 'encoder')?.module_action) return false;
  return !(id === 'shift' || id === 'tempo' || id.startsWith('view '));
}

// What the control does in the shown layer: its label, or '' when empty (inv2).
export function labelOf(model, id) {
  const c = controlState(model, id);
  if (!c) return '';
  return layerOf(model) === 'shift' ? c.label_shift : c.label_base;
}

// The header pill: 'Held …' when held, else 'Not held' (A4, A30) with the unit's own sentence beside it.
export function unitPill(state) {
  if (!state) return { text: 'Connecting…', detail: '', tone: 'muted' };
  const unit = state.unit;
  if (unit.held) return { text: unit.text, detail: '', tone: 'ok' };
  const tone = { busy: 'warn', no_permission: 'warn', maybe_stuck: 'warn', unplugged: 'warn' }[unit.status] ?? 'muted';
  return { text: 'Not held', detail: unit.text === 'Not held' ? '' : unit.text, tone };
}

// The store the page renders from: dispatch(action) → listeners(model).
export function createStore(model = initialModel()) {
  let current = model;
  const listeners = new Set();
  return {
    get model() { return current; },
    dispatch(action) {
      const next = reduce(current, action);
      if (next === current) return current;
      const previous = current;
      current = next;
      for (const listener of listeners) listener(current, previous, action);
      return current;
    },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  };
}
