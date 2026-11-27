// A minimal DOM stand-in so the web UI's ES modules can render under `node --test` without a browser.
// Only the surface the pages actually use is implemented; it is not a DOM and not a test of one.

class Node {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this._class = new Set();
    this._text = null;
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.selected = false;
    this.type = "";
    this.min = undefined;
    this.max = undefined;
    this.step = undefined;
    this.readOnly = false;
    this.htmlFor = null;
    this._parent = null;
  }

  get firstChild() {
    return this.children[0] || null;
  }

  get textContent() {
    if (this._text !== null) return this._text;
    return this.children.map((c) => c.textContent).join("");
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  get className() {
    return [...this._class].join(" ");
  }

  set className(value) {
    this._class = new Set(String(value).split(/\s+/).filter(Boolean));
  }

  setAttribute(name, value) {
    this.attributes[name] = value === true ? "" : String(value);
    if (name === "class") this.className = value;
  }

  appendChild(kid) {
    kid._parent = this;
    this.children.push(kid);
    return kid;
  }

  removeChild(kid) {
    const i = this.children.indexOf(kid);
    if (i !== -1) this.children.splice(i, 1);
    return kid;
  }

  addEventListener(type, fn) {
    this.listeners[type] = fn;
  }

  dispatch(type, event = { preventDefault: () => {} }) {
    const fn = this.listeners[type];
    if (fn) fn(event);
  }

  remove() {
    if (this._parent) this._parent.removeChild(this);
  }

  get classList() {
    return {
      add: (name) => this._class.add(name),
      remove: (name) => this._class.delete(name),
      contains: (name) => this._class.has(name),
    };
  }
}

class CustomEvent {
  constructor(type) {
    this.type = type;
  }
}

const document = {
  createElement: (tag) => new Node(tag),
  createElementNS: (_ns, tag) => new Node(tag),
  createTextNode: (text) => {
    const n = new Node("#text");
    n._text = String(text);
    return n;
  },
  getElementById: () => null,
};

const window = {
  dispatchEvent: () => {},
  confirm: () => false,
};

globalThis.Node = Node;
globalThis.document = document;
globalThis.window = window;
globalThis.CustomEvent = CustomEvent;

export { Node };
