// Learn and calibration (5a.11 q3, d164–d168, d147): the replica toolbar (Play / Inspect, learn by touch,
// Note-view calibration, what the column beside the surface shows) and the card's MIDI-learn section (bind the selected control to the next message on a
// chosen input port). Under the toolbar one line, always there so the surface keeps its size: what a click does
// in the current mode, or the learn / calibration step while one runs.
import { h } from './dom.js';
import { TOOLBAR_HELP, helpButton, modeHint } from './help.js';
import { modulePanels } from './state.js';

// What the column beside the surface shows: the overview (the default), the card + activity (a debugging aid),
// or nothing, so the surface takes the width.
const SIDE_CHOICES = [
  ['overview', 'Overview', 'Every page and bank beside the surface; click one to go there'],
  ['card', 'Card & activity', 'The selected control\'s card and the activity list beside the surface'],
  ['none', 'Hide', 'Nothing beside the surface: it takes the width'],
];

// The host's choices, each registered module panel (contract 2), then 'Hide'.
export function sideChoices(model) {
  const modules = modulePanels(model).map((m) => [m.name, m.title, `The ${m.title} panel beside the surface`]);
  return [...SIDE_CHOICES.slice(0, 2), ...modules, SIDE_CHOICES[2]];
}

export function toolbarView(model, handlers = {}) {
  const state = model.state;
  const learn = state?.learn ?? { mode: 'off' };
  const mode = model.ui.mode;
  const step = state?.calibration_step ?? 'idle';
  const calibrating = step === 'waiting for bottom-left' || step === 'waiting for top-right';
  const status = [];
  if (learn.mode === 'touch') status.push(h('span', { class: 'learn-on', text: 'Learn: touch a control on the unit to select it (nothing is sent)' }));
  if (learn.mode === 'midi') status.push(h('span', { class: 'learn-on', text: `MIDI-learn: listening on ${learn.port} for ${learn.selected ?? 'the selected control'}` }));
  if (learn.last) status.push(h('span', { class: 'status', text: learn.last }));
  if (calibrating) status.push(h('span', { class: 'learn-on', text: `Calibration: in Note view, ${step === 'waiting for bottom-left' ? 'press the bottom-left pad' : 'now press the top-right pad'}` }));
  return [
    h('span', { class: 'seg', role: 'group', 'aria-label': 'What a click does' },
      h('button', { 'aria-pressed': mode === 'play' ? 'true' : 'false',
        title: 'Play: a click presses the control as if on the unit; its MIDI goes out',
        onclick: () => handlers.mode?.('play'), text: 'Play' }),
      h('button', { 'aria-pressed': mode === 'inspect' ? 'true' : 'false',
        title: 'Inspect: a click only opens the control\'s card; nothing is sent',
        onclick: () => handlers.mode?.('inspect'), text: 'Inspect' })),
    h('button', { 'aria-pressed': learn.mode === 'off' ? 'false' : 'true',
      title: 'Touch a control on the unit to select it here; its action is not sent while learning',
      onclick: () => handlers.learnTouch?.(learn.mode === 'off'), text: learn.mode === 'off' ? 'Learn by touch' : 'Stop learning' }),
    calibrating
      ? h('button', { onclick: () => handlers.calibrate?.('cancel'), text: 'Cancel calibration' })
      : h('button', { title: `Note-view pad positions: ${state?.calibration_label ?? 'pad position unknown'}`,
        onclick: () => handlers.calibrate?.('start'), text: 'Calibrate Note view' }),
    helpButton(TOOLBAR_HELP, handlers),
    h('span', { class: 'spacer' }),
    h('span', { class: 'seg side-choice', role: 'group', 'aria-label': 'Beside the surface' },
      sideChoices(model).map(([panel, text, title]) => h('button', {
        'aria-pressed': model.ui.side === panel ? 'true' : 'false', title, data: { side: panel },
        onclick: () => handlers.side?.(panel), text }))),
    toolbarLine(mode, status),
  ];
}

// The one line under the toolbar: a running learn or calibration step (it is what a click is about then), else
// the mode's hint; the last learn result after either. Cut with an ellipsis, the whole text in its title.
export function toolbarLine(mode, status) {
  const running = status.filter((s) => s.props.class === 'learn-on');
  const rest = status.filter((s) => s.props.class !== 'learn-on');
  const parts = [...(running.length ? running : [h('span', { class: 'mode-hint', text: modeHint(mode) })]), ...rest];
  const joined = parts.flatMap((p, k) => (k ? [h('span', { class: 'sep', text: ' · ' }), p] : [p]));
  return h('div', { class: 'toolbar-line', data: { line: running.length ? 'status' : mode },
    title: parts.map((p) => p.props.text).join(' · ') }, joined);
}

// The input ports MIDI-learn can listen on: present ports that can be read, the control's own device first.
export function learnPorts(model, card) {
  const ports = (model.ui.ports ?? []).filter((p) => p.present && p.direction !== 'output').map((p) => p.name);
  const devices = (card?.port_status ?? []).map((s) => s.split(' ')[0]);
  return [...new Set([...devices, ...ports])];
}

export function learnCardView(model, handlers = {}) {
  const card = model.ui.card;
  if (!card || card.role !== 'bindable') return [];
  const learn = model.state?.learn ?? { mode: 'off' };
  const listening = learn.mode === 'midi' && learn.selected === card.control;
  const ports = learnPorts(model, card);
  if (listening) {
    return [h('section', {}, h('h2', { text: 'MIDI-learn' }),
      h('div', { class: 'form' },
        h('div', { class: 'answer', text: `Listening on ${learn.port}: the next note, CC, program change or pitch bend becomes ${card.control}'s binding on this ${card.layer ?? 'base'} layer.` }),
        h('div', { class: 'line' }, h('button', { onclick: () => handlers.learnOff?.(), text: 'Stop listening' }))))];
  }
  let chosen = ports[0] ?? '';
  return [h('section', {}, h('h2', { text: 'MIDI-learn' }),
    h('div', { class: 'form' },
      h('div', { class: 'line' },
        h('label', { text: 'From' }),
        ports.length
          ? h('select', { 'aria-label': 'Input port', onchange: (event) => { chosen = event.target.value; } },
            ports.map((p) => h('option', { value: p, text: p })))
          : h('input', { type: 'text', placeholder: 'device or port name', oninput: (event) => { chosen = event.target.value; } }),
        h('button', { onclick: () => handlers.learnMidi?.(card.control, chosen), text: 'Listen' })),
      learn.last ? h('div', { class: 'hint', text: learn.last } ) : null))];
}
