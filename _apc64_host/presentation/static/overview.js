// The overview (5a.9): every page as a mini grid and every bank as a strip set, with names and colours, on the
// base or Shift layer. Clicking one navigates there. It sits beside the surface and scales to that column
// (style.css: .ov-body).
import { h } from './dom.js';

const ROWS = [8, 7, 6, 5, 4, 3, 2, 1];
const COLS = [1, 2, 3, 4, 5, 6, 7, 8];

export function overviewView(model, handlers = {}) {
  const o = model.ui.overview;
  const layer = model.ui.overviewLayer ?? 'base';
  const head = h('h2', {},
    h('span', { class: 'grow', text: o?.layout_name ? `Overview · ${o.layout_name}` : 'Overview' }),
    h('span', { class: 'seg' },
      ['base', 'shift'].map((l) => h('button', {
        'aria-pressed': l === layer ? 'true' : 'false', onclick: () => handlers.overviewLayer?.(l),
        text: l === 'base' ? 'Base' : 'Shift',
      }))));
  if (!o || !o.pages?.length) return [head, h('p', { class: 'placeholder', text: 'No layout is live.' })];
  const pages = o.pages.map((p) => {
    const cells = p[layer] ?? {};
    const buttons = Object.entries(cells).filter(([id]) => !id.startsWith('pad '));
    return h('button', {
      class: ['ov-page', p.n === o.page ? 'current' : null, p.defined ? null : 'empty'],
      title: p.defined ? `Page ${p.n}${p.name ? ` ${p.name}` : ''}: go there` : `Page ${p.n} is empty`,
      data: { page: p.n }, disabled: !p.defined,
      onclick: () => p.defined && handlers.page?.(p.n),
    },
    h('span', { class: 'head', text: `${p.n} ${p.name ?? (p.defined ? `Page ${p.n}` : 'empty')}` }),
    h('span', { class: 'ov-grid' }, ROWS.flatMap((r) => COLS.map((c) => {
      const cell = cells[`pad r${r}c${c}`];
      return h('span', {
        class: ['ov-cell', cell ? 'bound' : null, cell && !cell.rgb ? 'nocolour' : null],
        style: cell?.rgb ? { '--c': cell.rgb } : undefined,
        title: cell ? `pad r${r}c${c}: ${cell.label}` : `pad r${r}c${c}: empty`,
      });
    }))),
    h('span', { class: 'ov-buttons', text: buttons.length ? buttons.map(([id, cell]) => `${id}: ${cell.label}`).join(' · ') : ' ' }));
  });
  const banks = o.banks.map((b) => {
    const cells = b[layer] ?? {};
    return h('button', {
      class: ['ov-bank', b.n === o.bank ? 'current' : null, b.defined ? null : 'empty'],
      title: b.defined ? `Bank ${b.n}${b.name ? ` ${b.name}` : ''}: go there` : `Bank ${b.n} is empty`,
      data: { bank: b.n }, disabled: !b.defined,
      onclick: () => b.defined && handlers.bank?.(b.n),
    },
    h('span', { class: 'head', text: `Bank ${b.n} ${b.name ?? (b.defined ? '' : 'empty')}`.trim() }),
    h('span', { class: 'ov-strips' }, COLS.map((n) => {
      const cell = cells[`strip ${n}`];
      return h('span', { class: 'ov-strip', style: cell?.rgb ? { '--c': cell.rgb } : undefined,
        title: cell ? `strip ${n}: ${cell.label}` : `strip ${n}: empty`, text: cell ? cell.label : '—' });
    })));
  });
  return [head, h('div', { class: 'ov-body' }, h('div', { class: 'ov-pages' }, pages), h('div', { class: 'ov-banks' }, banks))];
}
