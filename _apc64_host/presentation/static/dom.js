// A tiny element description and its DOM counterpart: views are pure functions returning h() trees (testable
// under node without a DOM); mount() turns a tree into elements. Props: class, text, title, style (object),
// data (object → data-*), on<event> handlers, and any other attribute.

export function h(tag, props = {}, ...children) {
  return { tag, props: props ?? {}, children: children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false) };
}

export function toDom(node, doc = globalThis.document) {
  if (typeof node === 'string' || typeof node === 'number') return doc.createTextNode(String(node));
  const el = doc.createElement(node.tag);
  for (const [key, value] of Object.entries(node.props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = Array.isArray(value) ? value.filter(Boolean).join(' ') : value;
    else if (key === 'text') el.textContent = String(value);
    else if (key === 'style') {
      for (const [k, v] of Object.entries(value)) {
        if (k.startsWith('--')) el.style.setProperty(k, v);
        else el.style[k] = v;
      }
    }
    else if (key === 'data') for (const [k, v] of Object.entries(value)) el.dataset[k] = String(v);
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else if (key === 'value') el.value = value;
    else if (key === 'checked' || key === 'disabled' || key === 'selected') el[key] = Boolean(value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of node.children) el.appendChild(toDom(child, doc));
  return el;
}

export function mount(container, node, doc = globalThis.document) {
  const nodes = (Array.isArray(node) ? node : [node]).filter(Boolean).map((n) => toDom(n, doc));
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
