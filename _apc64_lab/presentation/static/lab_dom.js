// The lab panel's element trees, in the host page's idiom (static/dom.js): views are pure functions returning
// h() trees, testable under node without a DOM; toDom() turns a tree into elements. Unlike the host's helper it
// creates <svg> and everything inside it in the SVG namespace, which the Tonnetz lattice and the circle need.
// (The panel is served from /modules/lab/, so it keeps its own copy rather than importing the host's file.)

export const SVG_NS = 'http://www.w3.org/2000/svg';

export function h(tag, props = {}, ...children) {
  return { tag, props: props ?? {}, children: children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false) };
}

export function toDom(node, doc = globalThis.document, inSvg = false) {
  if (typeof node === 'string' || typeof node === 'number') return doc.createTextNode(String(node));
  const svg = inSvg || node.tag === 'svg';
  const el = svg && doc.createElementNS ? doc.createElementNS(SVG_NS, node.tag) : doc.createElement(node.tag);
  for (const [key, value] of Object.entries(node.props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') {
      const text = Array.isArray(value) ? value.filter(Boolean).join(' ') : value;
      if (svg) el.setAttribute('class', text); else el.className = text;
    } else if (key === 'text') el.textContent = String(value);
    else if (key === 'style') {
      for (const [k, v] of Object.entries(value)) {
        if (k.startsWith('--') || svg) el.style.setProperty(k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`), v);
        else el.style[k] = v;
      }
    } else if (key === 'data') for (const [k, v] of Object.entries(value)) el.dataset[k] = String(v);
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else if (key === 'value' && !svg) el.value = value;
    else if ((key === 'checked' || key === 'disabled' || key === 'selected' || key === 'open') && !svg) el[key] = Boolean(value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of node.children) el.appendChild(toDom(child, doc, svg));
  return el;
}

export function mount(container, node, doc = globalThis.document) {
  const nodes = (Array.isArray(node) ? node.flat(Infinity) : [node]).filter(Boolean).map((n) => toDom(n, doc));
  container.replaceChildren(...nodes);
  return nodes;
}

// --- reading trees (tests and small lookups) ---------------------------------------------------------
export function textOf(node) {
  if (node === null || node === undefined || node === false) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  return (node.props.text !== undefined ? String(node.props.text) : '') + node.children.map(textOf).join('');
}

export function findAll(node, predicate, found = []) {
  if (!node || typeof node !== 'object') return found;
  if (Array.isArray(node)) { node.forEach((n) => findAll(n, predicate, found)); return found; }
  if (predicate(node)) found.push(node);
  node.children.forEach((c) => findAll(c, predicate, found));
  return found;
}

export function hasClass(node, name) {
  const cls = node.props?.class;
  const list = Array.isArray(cls) ? cls : String(cls ?? '').split(/\s+/);
  return list.includes(name);
}

export function byClass(node, name) {
  return findAll(node, (n) => hasClass(n, name));
}

export function byData(node, key, value) {
  return findAll(node, (n) => n.props?.data && String(n.props.data[key]) === String(value));
}
