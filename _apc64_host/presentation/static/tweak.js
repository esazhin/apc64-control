// The single-control tweak form (5a.10, inv21, d169–d173): assignment, label, colour or momentary/toggle of the
// selected control on the card's page (or bank) and a chosen layer, saved back into the layout file as one
// line, against the file hash the card was read with (a stale card answers 'layout changed, reload').
import { h } from './dom.js';
import { layerOf } from './state.js';

export function tweakLayer(model) {
  return model.ui.tweakLayer ?? layerOf(model);
}

export function tweakDefaults(card, layer) {
  const form = card?.forms?.[layer] ?? null;
  return {
    assignment: form?.assignment ?? '',
    label: form?.label ?? '',
    colour: form?.colour ? String(form.colour.index) : '',
    mode: form?.mode ?? 'momentary',
    bound: Boolean(form),
  };
}

export function tweakRequest(card, layer, field, value) {
  const strip = /^strip \d/.test(card.control);
  const request = { layout: card.layout, control: card.control, layer, field, value: value === '' ? null : value,
    base_hash: card.base_hash };
  if (strip) request.bank = card.bank; else request.page = card.page;
  return request;
}

export function tweakKey(model) {
  const card = model.ui.card;
  if (!card) return `none|${model.ui.selected}`;
  return [card.control, card.base_hash, card.page, card.bank, tweakLayer(model), JSON.stringify(model.ui.tweakAnswer)].join('|');
}

export function tweakView(model, handlers = {}, palette = []) {
  const card = model.ui.card;
  if (!card) return [];
  if (card.role !== 'bindable') {
    return [h('section', {}, h('p', { class: 'hint', text: 'This control is not bindable, so it has nothing to tweak.' }))];
  }
  if (!card.layout) return [h('section', {}, h('p', { class: 'hint', text: 'No layout is live: nothing to tweak.' }))];
  const layer = tweakLayer(model);
  const d = tweakDefaults(card, layer);
  const strip = /^strip \d/.test(card.control);
  const values = { ...d };
  const save = (field) => () => handlers.saveTweak?.(card, layer, field, values[field]);
  const where = strip ? `bank ${card.bank}` : `page ${card.page}`;
  const answer = model.ui.tweakAnswer;
  const named = palette.filter((p) => p.name);
  const colourOptions = [h('option', { value: '', text: d.colour === '' ? 'no colour' : 'no colour (remove)' }),
    ...named.map((p) => h('option', { value: String(p.index), selected: String(p.index) === d.colour, text: `${p.name} (${p.index})` })),
    ...palette.filter((p) => !p.name).map((p) => h('option', { value: String(p.index), selected: String(p.index) === d.colour, text: `index ${p.index}` }))];
  const row = (label, input, field, disabled = false) => h('div', { class: 'line' },
    h('label', { text: label }), input,
    h('button', { disabled, onclick: save(field), 'data-field': field, text: 'Save' }));
  return [h('section', {},
    h('h2', {}, h('span', { class: 'grow', text: 'Change this control' }), h('span', { text: where })),
    h('div', { class: 'form' },
      h('div', { class: 'line' }, h('label', { text: 'Layer' }),
        h('span', { class: 'seg' }, ['base', 'shift'].map((l) => h('button', {
          'aria-pressed': l === layer ? 'true' : 'false', onclick: () => handlers.tweakLayer?.(l), text: l === 'base' ? 'Base' : 'Shift',
        })))),
      row('Assignment', h('input', { type: 'text', value: d.assignment, placeholder: 'e.g. note 38 on mpc ch 10, or none',
        'aria-label': 'Assignment', oninput: (event) => { values.assignment = event.target.value; } }), 'assignment'),
      row('Label', h('input', { type: 'text', value: d.label, placeholder: d.bound ? 'shown on the replica' : 'give it an assignment first',
        'aria-label': 'Label', disabled: !d.bound, oninput: (event) => { values.label = event.target.value; } }), 'label', !d.bound),
      row('Colour', h('select', { 'aria-label': 'Colour', disabled: !d.bound,
        onchange: (event) => { values.colour = event.target.value; } }, colourOptions), 'colour', !d.bound),
      strip ? null : row('Mode', h('select', { 'aria-label': 'Mode', disabled: !d.bound, onchange: (event) => { values.mode = event.target.value; } },
        ['momentary', 'toggle'].map((m) => h('option', { value: m, selected: m === d.mode, text: m }))), 'mode', !d.bound),
      answer ? h('div', { class: ['answer', answer.tone === 'ok' ? 'ok' : 'bad'] }, answer.text,
        answer.tone === 'stale' ? h('button', { onclick: () => handlers.refreshCard?.(), style: { marginLeft: '8px' }, text: 'Reload' }) : null,
        answer.issues?.length ? h('ul', {}, answer.issues.map((i) => h('li', { text: i.text }))) : null) : null,
      h('div', { class: 'hint', text: 'Saved as one line in the layout file; ranges, comments and every other line stay as written.' })))];
}
