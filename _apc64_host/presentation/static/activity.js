// The live activity list (5a.9, d162, d163): control → message → port, sent / not sent (why) / refused /
// unbound / dropped, the latest 200, newest first.
import { h } from './dom.js';

export function clock(at) {
  if (at === null || at === undefined) return '--:--:--';
  const d = new Date(at * 1000);
  const two = (n) => String(n).padStart(2, '0');
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}

export function activityView(model) {
  const records = model.activity ?? [];
  return [
    h('h2', {}, h('span', { class: 'grow', text: 'Activity' }), h('span', { text: 'latest 200, newest first' })),
    records.length
      ? h('ol', {}, records.map((r) => h('li', { class: r.result, data: { id: r.id } },
        h('span', { class: 't', text: clock(r.at) }), h('span', { class: 'x', text: r.text }))))
      : h('p', { class: 'none', text: 'Nothing yet: press a control on the unit or in the replica.' }),
  ];
}
