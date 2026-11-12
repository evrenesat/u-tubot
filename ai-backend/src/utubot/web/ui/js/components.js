import { clear, h, icon } from "./dom.js";
import { ApiError } from "./api.js";

// ---- formatting --------------------------------------------------------------------------

export function fmtTime(seconds) {
  if (!seconds) return "never";
  return new Date(seconds * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function fmtAgo(seconds) {
  if (!seconds) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - seconds));
  if (s < 60) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " d ago";
}

export function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  if (m >= 60) return Math.floor(m / 60) + " h " + (m % 60) + " min";
  return m + ":" + String(s % 60).padStart(2, "0");
}

export function fmtNumber(n) {
  return Number(n || 0).toLocaleString();
}

// ---- toasts ------------------------------------------------------------------------------

export function toast(message, kind = "ok") {
  const host = document.getElementById("toasts");
  if (!host) return;
  const el = h("div", { class: "toast " + kind, text: message });
  host.appendChild(el);
  setTimeout(() => el.remove(), kind === "bad" ? 7000 : 3200);
}

export function errorText(err) {
  if (err instanceof ApiError) return err.message;
  return err && err.message ? err.message : "Something went wrong";
}

// ---- building blocks ---------------------------------------------------------------------

export function card(title, ...kids) {
  return h("section", { class: "card" }, title ? h("h2", { text: title }) : null, ...kids);
}

export function note(text, kind = "muted") {
  return h("p", { class: kind, text });
}

export function pill(text, kind = "") {
  return h("span", { class: "pill " + kind, text });
}

export function button(label, onClick, { kind = "", full = false, type = "button" } = {}) {
  const btn = h("button", { type, class: ["btn", kind, full ? "full" : ""].join(" ").trim() }, label);
  if (onClick) {
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      if (btn.disabled) return;
      btn.disabled = true;
      btn.classList.add("busy");
      try {
        await onClick(event);
      } catch (err) {
        toast(errorText(err), "bad");
      } finally {
        btn.disabled = false;
        btn.classList.remove("busy");
      }
    });
  }
  return btn;
}

export function field(label, control, hint) {
  const id = "f" + Math.random().toString(36).slice(2, 8);
  control.id = id;
  return h("div", { class: "field" }, h("label", { for: id, text: label }), control, hint ? h("small", { class: "muted", text: hint }) : null);
}

export function textInput(value, { placeholder = "", type = "text", autocomplete = "off", maxlength } = {}) {
  return h("input", { type, value: value ?? "", placeholder, autocomplete, maxlength, spellcheck: "false", autocapitalize: "off" });
}

export function numberInput(value, { min, max, step = 1 } = {}) {
  return h("input", { type: "number", value: value ?? "", min, max, step, inputmode: "numeric" });
}

export function switchRow(label, hint, checked, onChange) {
  const input = h("input", { type: "checkbox", checked: !!checked, role: "switch" });
  input.addEventListener("change", () => onChange && onChange(input.checked));
  const row = h(
    "label",
    { class: "switch-row" },
    h("span", { class: "switch-text" }, h("span", { text: label }), hint ? h("small", { class: "muted", text: hint }) : null),
    input,
    h("span", { class: "switch-ui", "aria-hidden": "true" }),
  );
  row.input = input;
  return row;
}

export function segmented(options, value, onChange) {
  const wrap = h("div", { class: "segmented", role: "radiogroup" });
  const name = "seg" + Math.random().toString(36).slice(2, 8);
  for (const [val, label] of options) {
    const input = h("input", { type: "radio", checked: val === value });
    input.name = name;
    input.value = val;
    input.addEventListener("change", () => input.checked && onChange(val));
    wrap.appendChild(h("label", {}, input, h("span", { text: label })));
  }
  return wrap;
}

export function select(options, value, onChange) {
  const sel = h("select", {});
  for (const opt of options) {
    const o = h("option", { value: opt.value, text: opt.label });
    if (opt.value === value) o.selected = true;
    sel.appendChild(o);
  }
  if (onChange) sel.addEventListener("change", () => onChange(sel.value));
  return sel;
}

export function slider({ label, value, min = 0, max = 1, step = 0.05, format = String, hint, onChange }) {
  const out = h("output", { class: "slider-value", text: format(value) });
  const input = h("input", { type: "range", min, max, step, value });
  input.addEventListener("input", () => {
    out.textContent = format(Number(input.value));
    onChange && onChange(Number(input.value));
  });
  const wrap = h(
    "div",
    { class: "slider" },
    h("div", { class: "slider-head" }, h("span", { text: label }), out),
    input,
    hint ? h("small", { class: "muted", text: hint }) : null,
  );
  wrap.set = (v) => {
    input.value = v;
    out.textContent = format(v);
  };
  return wrap;
}

// Editable list of short strings as removable chips.
export function chipEditor(initial, { placeholder, onChange, max = 50 }) {
  let items = [...initial];
  const list = h("div", { class: "chips" });
  const input = h("input", { type: "text", placeholder, maxlength: 80, enterkeyhint: "done", autocomplete: "off", spellcheck: "false" });
  const wrap = h("div", { class: "chip-editor" }, list);
  function draw() {
    clear(list);
    if (!items.length) list.appendChild(h("span", { class: "muted", text: "None yet" }));
    items.forEach((text, i) => {
      const remove = h("button", { type: "button", class: "chip-x", "aria-label": "Remove " + text }, icon("close"));
      remove.addEventListener("click", () => {
        items.splice(i, 1);
        draw();
        onChange(items);
      });
      list.appendChild(h("span", { class: "chip" }, h("span", { class: "chip-text", text }), remove));
    });
  }
  function add() {
    const text = input.value.trim().replace(/\s+/g, " ");
    input.value = "";
    if (!text || items.includes(text) || items.length >= max) return;
    items.push(text);
    draw();
    onChange(items);
  }
  const addBtn = h("button", { type: "button", class: "btn sec" }, "Add");
  addBtn.addEventListener("click", add);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      add();
    }
  });
  wrap.appendChild(h("div", { class: "row nowrap" }, input, addBtn));
  wrap.set = (next) => {
    items = [...next];
    draw();
  };
  wrap.get = () => items;
  draw();
  return wrap;
}

export function progressBar(fraction) {
  return h("progress", { max: 1, value: Math.min(1, Math.max(0, fraction || 0)) });
}

export function statRow(label, value, kind = "") {
  return h("div", { class: "stat" }, h("span", { class: "muted", text: label }), h("strong", { class: kind, text: String(value) }));
}

export function empty(text) {
  return h("p", { class: "empty", text });
}

export function loading() {
  return h("p", { class: "muted pad", text: "Loading..." });
}

export function failure(err, retry) {
  return h(
    "div",
    { class: "card" },
    h("p", { class: "bad", text: errorText(err) }),
    retry ? button("Try again", retry, { kind: "sec" }) : null,
  );
}

export async function confirmAction(text) {
  return window.confirm(text);
}

// Re-run `fn` every `ms` while the page is shown; returns a stop function.
export function every(ms, fn) {
  const id = setInterval(() => {
    if (!document.hidden) fn();
  }, ms);
  return () => clearInterval(id);
}

export function bigCode(code) {
  const text = String(code);
  const half = Math.ceil(text.length / 2);
  return h("div", { class: "bigcode", text: text.slice(0, half) + " " + text.slice(half), "aria-label": "Pairing code " + text });
}
