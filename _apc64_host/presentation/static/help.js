// Help (live session 2026-10-26): small "?" buttons that open one short overlay. A topic is plain data,
// {title, items: [[term, text] | text]}, so a module panel can bring its own (the lab passes its topics to
// handlers.help). The overlay closes on its × button, a click outside the card, or Esc; never a browser dialog.
import { h } from './dom.js';

// The "?" button: opens `topic` through handlers.help. Module panels draw the same button (class help-btn).
export function helpButton(topic, handlers = {}) {
  return h('button', {
    type: 'button', class: 'help-btn', title: `Help: ${topic.title}`, 'aria-label': `Help: ${topic.title}`,
    'aria-haspopup': 'dialog', data: { help: topic.id ?? topic.title }, onclick: () => handlers.help?.(topic),
    text: '?',
  });
}

// The overlay for the open topic (model.ui.help), or nothing.
export function helpView(model, handlers = {}) {
  const topic = model.ui.help;
  if (!topic) return [];
  const close = () => handlers.closeHelp?.();
  return [
    h('div', { class: 'help-backdrop', data: { help: 'backdrop' }, onclick: close }),
    h('div', { class: 'help-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'help-title' },
      h('div', { class: 'help-head' },
        h('h2', { id: 'help-title', text: topic.title }),
        h('button', { type: 'button', class: 'help-close', 'aria-label': 'Close help', title: 'Close (Esc)',
          data: { help: 'close' }, onclick: close, text: '×' })),
      h('dl', { class: 'help-items' }, (topic.items ?? []).map((item) => (Array.isArray(item)
        ? [h('dt', { text: item[0] }), h('dd', { text: item[1] })]
        : h('dd', { class: 'plain', text: item })))),
      topic.more ? h('div', { class: 'help-more', text: topic.more }) : null),
  ];
}

// --- the host page's topics (what nav.js, learn.js, replica.js and app.js actually do) ------------------------
export const LAYOUT_HELP = {
  id: 'layout',
  title: 'Layouts, pages and strip banks',
  items: [
    ['Layout', 'A layout file (layouts/*.yaml) says what every control sends. Choose it in this bar, or on the '
      + 'unit: hold Shift and turn the encoder to browse the names on the OLED, then press the encoder (Shift '
      + 'still held) to load the one shown.'],
    ['Page', 'One set of pad and button assignments; a layout has up to 8. On the unit the 8 scene buttons '
      + '(the column right of the pads) choose the page; here, click a page in this bar or in the Overview. '
      + 'An empty page keeps the current one. Scene LEDs: bright = current page, dim = defined, off = empty.'],
    ['Strip bank', 'One set of assignments for the 8 touch strips; a layout has up to 6. On the unit the 6 '
      + 'strip-mode buttons (Device, Volume, Pan, Sends, Channel, Off, left of the pads) choose the bank; here, '
      + 'click a bank in this bar or in the Overview. Their LEDs show the same as the scene buttons.'],
    'Pages and banks are independent: switching one keeps the other. The OLED shows the new name for a moment.',
    ['View', 'The unit\'s mode (Session, Note, Chord, Step, Custom…). Pages drive the pads in Session view; '
      + 'in the other views the APC64 plays its pads itself. The view buttons on the surface switch the unit (Play '
      + 'mode, while the host holds it), as pressing them on the unit does; Project stays on the unit.'],
    ['Fold', '“Fold ▴” shrinks this bar to one line; “Layouts, pages, banks ▾” opens it again (remembered in '
      + 'this browser).'],
  ],
};

export const TOOLBAR_HELP = {
  id: 'toolbar',
  title: 'What a click on the surface does',
  items: [
    ['Play', 'A click on a control presses it exactly like the hardware (it sends its MIDI, or a scene or '
      + 'strip-mode button switches page or bank) and lets go when you release. Drag a strip to move it; ◀ ▶ (or the wheel on “push”) turn the encoder. In the unit\'s '
      + 'Note, Chord, Step, Drum and Custom views the pads are the unit\'s, so clicking them sends nothing.'],
    ['Inspect', 'A click only selects the control and opens its card beside the surface: both layers, where '
      + 'else it is bound, MIDI-learn and a one-control edit. Nothing is sent. Shift still works, to show the '
      + 'Shift labels.'],
    ['Learn by touch', 'Touch a control on the unit and it is selected here with its card open. While learning, '
      + 'the touched control\'s action is not sent.'],
    ['Calibrate Note view', 'The unit\'s Note-view settings cannot be read, so show it: start, then on the unit '
      + 'in Note view press the bottom-left pad, then the top-right pad. Notes played in Note view then light '
      + 'their pads here (always marked “assumed”).'],
    ['Beside the surface', 'Overview: every page and bank, click one to go there. Card & activity: the selected '
      + 'control and the last 200 actions. Lab: the lab panel. Hide: the surface takes the width.'],
  ],
};

// The one-line hint under the toolbar (verified against createHandlers in app.js).
export const MODE_HINTS = {
  play: 'Play: a click on the surface presses that control as if on the unit; its MIDI goes out.',
  inspect: 'Inspect: a click on the surface opens that control\'s card; nothing is sent.',
};

export function modeHint(mode) {
  return MODE_HINTS[mode] ?? MODE_HINTS.play;
}
