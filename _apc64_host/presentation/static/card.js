// The detail card (5a.9, A129): one control on both layers — messages, ports, momentary/toggle and toggle
// state, feedback rule, port availability — and where else in the layout it is bound differently (each
// entry navigates there). One step from selecting a control (d185).
import { h } from './dom.js';
import { layerOf } from './state.js';

const ROLE_TEXT = {
  bindable: null,
  navigation: 'Navigation: selects a page or strip bank, never sends MIDI',
  modifier: 'Modifier: hold for every control\'s Shift layer',
  device_local: 'A view button: pressed on the unit it never reaches the host. Session, Note, Chord, Step and Custom '
    + 'pressed here (Play) ask the unit for that view while the host holds it; Project stays the unit\'s own.',
};

export function cardView(model, handlers = {}) {
  const id = model.ui.selected;
  if (!id) {
    return [h('h2', { text: 'Control' }),
      h('p', { class: 'placeholder', text: 'Select a control to see what it does on both layers, where else it is bound, and to change it. In Play mode a click also presses it; switch to Inspect to only look.' })];
  }
  const card = model.ui.card;
  if (model.ui.cardProblem) return [h('h2', { text: id }), h('p', { class: 'placeholder', text: model.ui.cardProblem })];
  if (!card) return [h('h2', { text: id }), h('p', { class: 'placeholder', text: 'Loading…' })];
  const layer = layerOf(model);
  const swatch = card.led && !card.led.off
    ? h('span', { class: 'swatch', style: { background: card.led.rgb }, title: `palette ${card.led.colour} (approximate)` }) : null;
  const rows = [];
  const add = (term, text, cls) => rows.push(h('dt', { text: term }), h('dd', { class: cls, text: text ?? '' }));
  if (card.role === 'bindable') {
    add('Base', card.base ?? 'empty', [card.base ? null : 'empty', layer === 'base' ? 'current' : null]);
    add('Shift', card.shift ?? 'empty', [card.shift ? null : 'empty', layer === 'shift' ? 'current' : null]);
    if (card.mode) add('Mode', card.mode + (card.toggle === null || card.toggle === undefined ? '' : `, ${card.toggle ? 'on' : 'off'}`));
    if (card.feedback) add('Feedback', card.feedback);
    if (card.port_status?.length) add('Ports', card.port_status.join(' · '));
    if (card.led && !card.led.off) rows.push(h('dt', { text: 'LED' }), h('dd', {}, swatch, `colour ${card.led.colour} (approximate)`));
    if (card.reachable && card.reachable !== 'verified') add('Shift layer', card.reachable);
  }
  const where = card.page ? `Page ${card.page}${card.bank ? ` · bank ${card.bank}` : ''} · ${card.layer ?? layer}` : '';
  return [
    h('h2', {}, h('span', { class: 'grow', text: 'Control' }), where ? h('span', { text: where }) : null),
    h('div', { class: 'title', text: card.display }),
    h('div', { class: 'role', text: ROLE_TEXT[card.role] ?? `In layouts and the CLI: ${card.control}` }),
    rows.length ? h('dl', {}, rows) : null,
    card.elsewhere?.length ? h('section', {},
      h('h2', { text: 'Elsewhere in this layout' }),
      h('ul', { class: 'elsewhere' }, card.elsewhere.map((e) => h('li', {},
        h('button', {
          title: e.page ? `Go to page ${e.page}` : `Go to bank ${e.bank}`,
          onclick: () => (e.page ? handlers.page?.(e.page) : handlers.bank?.(e.bank)),
          text: e.text,
        }))))) : null,
  ];
}
