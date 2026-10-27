// A small DOM for node --test (not loaded by the page): enough elements, classes, styles, data-*, events and
// text for the page's renderers and gesture wiring.
class FakeStyle {
  constructor() { this.props = {}; }
  setProperty(name, value) { this.props[name] = String(value); }
  getPropertyValue(name) { return this.props[name] ?? ''; }
}

class FakeClassList {
  constructor(el) { this.el = el; }
  get list() { return this.el.className.split(/\s+/).filter(Boolean); }
  contains(name) { return this.list.includes(name); }
  add(...names) { this.el.className = [...new Set([...this.list, ...names])].join(' '); }
  remove(...names) { this.el.className = this.list.filter((n) => !names.includes(n)).join(' '); }
  toggle(name, force) {
    const on = force === undefined ? !this.contains(name) : Boolean(force);
    if (on) this.add(name); else this.remove(name);
    return on;
  }
}

export class FakeText {
  constructor(text) { this.nodeType = 3; this.data = String(text); this.children = []; }
  get textContent() { return this.data; }
}

export class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.nodeType = 1;
    this.childNodes = [];
    this.className = '';
    this.classList = new FakeClassList(this);
    this.style = new FakeStyle();
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.title = '';
    this.value = '';
    this.captured = null;
    this.rect = { top: 0, left: 0, width: 40, height: 160 };
  }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(text) { this.childNodes = [new FakeText(text)]; }
  appendChild(node) { this.childNodes.push(node); node.parentNode = this; return node; }
  append(...nodes) { nodes.forEach((n) => this.appendChild(typeof n === 'string' ? new FakeText(n) : n)); }
  replaceChildren(...nodes) { this.childNodes = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  dispatch(type, extra = {}) {
    const event = { type, target: this, preventDefault() { this.defaultPrevented = true; }, pointerId: 1, ...extra };
    for (const fn of this.listeners[type] ?? []) fn(event);
    return event;
  }
  setPointerCapture(id) { this.captured = id; }
  getBoundingClientRect() { return this.rect; }
  focus() {}
  // lookups for tests
  all(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.all(predicate, found);
    }
    return found;
  }
  byData(key, value) { return this.all((e) => e.dataset[key] === String(value))[0] ?? null; }
  byClass(name) { return this.all((e) => e.classList.contains(name)); }
}

export class FakeDocument {
  createElement(tag) { return new FakeElement(tag); }
  createTextNode(text) { return new FakeText(text); }
}
