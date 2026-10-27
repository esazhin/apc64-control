// The header status and the banners: the consent question (Take control of APC64? Yes / No), Busy, No
// permission, maybe still in DAW mode, firmware and port notices, Release; validation errors and warnings shown
// plainly (inv19, d115); the last refused request; a lost connection.
import { h } from './dom.js';
import { unitPill } from './state.js';

export function headerView(model, handlers = {}) {
  const state = model.state;
  const pill = unitPill(state);
  const unit = state?.unit;
  let action = null;
  if (unit?.held) action = h('button', { class: 'danger', onclick: () => handlers.release?.(), text: 'Release' });
  else if (unit && unit.status !== 'absent' && unit.status !== 'unplugged') {
    action = h('button', { class: 'primary', onclick: () => handlers.take?.(), text: 'Take control' });
  }
  return [
    h('span', { class: ['pill', pill.tone], text: pill.text }),
    pill.detail ? h('span', { class: 'unit-detail', title: pill.detail, text: pill.detail }) : null,
    action,
  ];
}

function banner(tone, say, actions = [], extra = []) {
  return h('div', { class: ['banner', tone], role: tone === 'bad' ? 'alert' : null },
    h('div', { class: 'say' }, say, ...extra),
    actions.length ? h('div', { class: 'actions' }, actions) : null);
}

const hint = (text) => h('div', { class: 'hint', text });

export function unitBanner(state, handlers = {}) {
  const unit = state.unit;
  const notices = (unit.notices ?? []).map(hint);
  const take = (label = 'Yes') => h('button', { class: 'primary', onclick: () => handlers.take?.(), text: label });
  switch (unit.status) {
    case 'asking':
      return banner('ask', unit.text, [take('Yes'), h('button', { onclick: () => handlers.decline?.(), text: 'No' })],
        [...notices, hint('While the host holds the APC64, Bitwig cannot use it; Release hands it back.')]);
    case 'maybe_stuck':
      return banner('warn', unit.text, [take('Take to reset')], notices);
    case 'busy':
      return banner('warn', unit.text, [], [...notices,
        hint('The host never takes the APC64 from another program. It asks again when the port is free.')]);
    case 'no_permission':
      return banner('warn', unit.text, [take('Try again')], [...notices,
        hint('Someone must be logged in at the desktop for the APC64 to be opened.')]);
    case 'absent':
      return banner('info', unit.text, [], [...notices,
        hint('Layouts still load and the replica still sends its actions to their ports.')]);
    case 'unplugged':
      return banner('warn', unit.text, [], notices);
    case 'declined':
      return banner('info', 'Not held', [take('Take control')], notices);
    case 'held': {
      const lines = [...(unit.warnings ?? []), ...(unit.notices ?? [])];
      if (!lines.length) return null; // the header pill already says Held
      return banner('warn', unit.text, [], lines.map(hint));
    }
    default:
      return null;
  }
}

export function bannerView(model, handlers = {}) {
  const state = model.state;
  const out = [];
  if (state && !model.connected) {
    out.push(banner('warn', 'Connection to the host lost — reconnecting…'));
  }
  if (model.ui.problem) {
    out.push(banner('bad', model.ui.problem,
      [h('button', { onclick: () => handlers.dismiss?.(), text: 'Dismiss' })],
      model.ui.issues?.length ? [h('ul', { class: 'issues' }, model.ui.issues.map((i) => h('li', { text: i.text ?? String(i) })))] : []));
  } else if (model.ui.notice) {
    out.push(banner('ok', model.ui.notice));
  }
  if (!state) return out;
  const unit = unitBanner(state, handlers);
  if (unit) out.push(unit);
  if (state.errors?.length) {
    out.push(banner('bad', `Layout problems (${state.errors.length}) — these files are not live; fix them and they load at once`, [],
      [h('ul', { class: 'issues' }, state.errors.map((e) => h('li', { text: e.text })))]));
  }
  const layoutWarnings = (state.warnings ?? []).filter((w) => !(state.unit.warnings ?? []).includes(w));
  if (layoutWarnings.length) {
    out.push(banner('warn', 'Warnings for the live layout (it is live; these are hints)', [],
      [h('ul', { class: 'issues' }, layoutWarnings.map((w) => h('li', { text: w })))]));
  }
  if (state.file_deleted && state.layout) {
    out.push(banner('info', `${state.layout}.yaml: file deleted, still active`));
  }
  return out;
}
