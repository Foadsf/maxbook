// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Maxbook front end: notebook editing, running cells against Maxima, files.

import { MathfieldElement } from "../vendor/mathlive/mathlive.min.mjs";
import { api, get, post, initToken, ApiError } from "./api.js";
import { highlightMaxima } from "./highlight.js";
import { renderMarkdown, renderLatex, headingsOf } from "./markdown.js";
import { MATH_TEMPLATES, CODE_TEMPLATES, searchTemplates } from "./templates.js";
import { buildHtmlExport, rasterizeImages } from "./export.js";

MathfieldElement.soundsDirectory = null;  // fonts load from ./fonts next to the MathLive module

// ------------------------------------------------------------------ state
const S = {
  nb: null,          // notebook object (format/version/title/cells/metadata)
  path: null,        // absolute path of the .maxbook file, or null
  suggested: null,   // default path for the first save (imports)
  dirty: false,
  active: null,      // active cell id
  views: new Map(),  // cell id -> view
  running: false,
  stopRequested: false,
  recent: [],
  home: "",
  cwd: "",
};

const $ = (sel, root = document) => root.querySelector(sel);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const uid = () => Math.random().toString(16).slice(2, 14);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

function icon(path) {
  const span = document.createElement("span");
  span.innerHTML = `<svg viewBox="0 0 24 24">${path}</svg>`;
  return span.firstChild;
}

let toastTimer = 0;
function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), ms);
}

function banner(msg, kind = "") {
  const b = $("#banner");
  if (!msg) { b.hidden = true; return; }
  b.className = "banner " + kind;
  b.replaceChildren(el("span", { text: msg }), el("button", { class: "btn", text: "Dismiss", onclick: () => banner("") }));
  b.hidden = false;
}

function setDirty(d = true) {
  S.dirty = d;
  $("#dirty").hidden = !d;
  document.title = `${d ? "• " : ""}${S.nb?.title || "Untitled"} — Maxbook`;
}

function debounce(fn, ms) {
  let t = 0;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ------------------------------------------------------------------ kernel
let kernelInfo = {};
async function pollKernel() {
  try {
    kernelInfo = await get("/api/kernel");
  } catch (e) {
    kernelInfo = { status: "dead", error: e.message };
  }
  renderKernel();
}

function shortVersion(v) {
  const m = String(v || "").match(/(\d+)[._](\d+)(?:[._](\d+))?/);
  return m ? `${m[1]}.${m[2]}${m[3] && !/branch/.test(v) ? "." + m[3] : ""}` : v || "";
}

function renderKernel() {
  const pill = $("#kernel");
  const st = kernelInfo.status || "stopped";
  pill.dataset.status = st;
  const name = kernelInfo.version ? `Maxima ${shortVersion(kernelInfo.version)}` : "Maxima";
  const label = { idle: "ready", busy: "computing…", asking: "waiting for your answer", starting: "starting…",
                  missing: "not found", dead: "stopped", stopped: "stopped" }[st] || st;
  pill.lastChild.textContent = `${name} · ${label}`;
  pill.title = [kernelInfo.maxima_path, kernelInfo.lisp, kernelInfo.error].filter(Boolean).join("\n");
}

// ------------------------------------------------------------------ rendering
function knownFunctionSources() {
  return S.nb.cells.filter((c) => c.type !== "markdown").map((c) => c.source || "");
}

function renderNotebook() {
  const paper = $("#paper");
  S.views.clear();
  paper.replaceChildren();
  $("#title").value = S.nb.title;
  paper.append(inserter(0));
  S.nb.cells.forEach((cell, i) => {
    const v = makeView(cell);
    paper.append(v.root, inserter(i + 1));
  });
  paper.append(el("div", { class: "add-row" },
    el("button", { text: "+ Maxima", title: "Add a Maxima code cell", onclick: () => addCell("code", S.nb.cells.length, true) }),
    el("button", { text: "+ Math", title: "Add a structural math cell", onclick: () => addCell("math", S.nb.cells.length, true) }),
    el("button", { text: "+ Text", title: "Add a Markdown text cell", onclick: () => addCell("markdown", S.nb.cells.length, true) })));
  renderOutline();
  setDirty(S.dirty);
}

function inserter(index) {
  const mk = (type, label) => el("button", {
    text: label, onclick: (e) => {
      const idx = [...$("#paper").querySelectorAll(".inserter")].indexOf(e.target.closest(".inserter"));
      addCell(type, idx, true);
    },
  });
  return el("div", { class: "inserter" }, el("span"),
    el("div", { class: "bar" }, mk("code", "+ Maxima"), mk("math", "+ Math"), mk("markdown", "+ Text")));
}

function addCell(type, index, focus = false, init = {}) {
  const cell = { id: uid(), type, source: "", ...init };
  if (type === "math") cell.latex = init.latex || "";
  if (type !== "markdown") cell.outputs = [];
  S.nb.cells.splice(index, 0, cell);
  const v = makeView(cell);
  const paper = $("#paper");
  const ins = paper.querySelectorAll(".inserter")[index];
  ins.after(v.root, inserter(index + 1));
  setDirty();
  if (type === "markdown") v.edit?.();
  if (focus) setActive(cell.id, true);
  renderOutline();
  return cell;
}

function deleteCell(cell) {
  const i = S.nb.cells.indexOf(cell);
  if (i < 0) return;
  const v = S.views.get(cell.id);
  const next = S.nb.cells[i + 1] || S.nb.cells[i - 1];
  S.nb.cells.splice(i, 1);
  v.root.nextElementSibling?.remove(); // its inserter
  v.root.remove();
  S.views.delete(cell.id);
  if (!S.nb.cells.length) addCell("code", 0);
  setDirty();
  renderOutline();
  if (next) setActive(next.id, false);
}

function moveCell(cell, delta) {
  const i = S.nb.cells.indexOf(cell);
  const j = i + delta;
  if (j < 0 || j >= S.nb.cells.length) return;
  [S.nb.cells[i], S.nb.cells[j]] = [S.nb.cells[j], S.nb.cells[i]];
  const scroll = $("#main").scrollTop;
  renderNotebook();
  $("#main").scrollTop = scroll;
  setActive(cell.id, false);
  setDirty();
}

function changeType(cell, type) {
  if (cell.type === type) return;
  if (type === "math" && cell.type === "code" && cell.source.trim()) {
    if (!confirm("Math cells are written visually; the current Maxima text will be discarded. Continue?")) return;
    cell.source = "";
  }
  if (cell.type === "math" && type === "code") cell.source = cell.source || "";
  cell.type = type;
  if (type === "math") cell.latex = cell.latex || "";
  else delete cell.latex;
  if (type === "markdown") delete cell.outputs;
  else cell.outputs = cell.outputs || [];
  const old = S.views.get(cell.id);
  const v = makeView(cell);
  old.root.replaceWith(v.root);
  setDirty();
  setActive(cell.id, true);
  renderOutline();
}

function setActive(id, focus) {
  if (S.active && S.views.get(S.active)) S.views.get(S.active).root.classList.remove("active");
  S.active = id;
  const v = S.views.get(id);
  if (!v) return;
  v.root.classList.add("active");
  if (focus) {
    v.focus();  // now, so keys typed immediately land here
    requestAnimationFrame(() => { if (!v.root.contains(document.activeElement)) v.focus(); });
  }
  const r = v.root.getBoundingClientRect();
  const m = $("#main").getBoundingClientRect();
  if (r.top < m.top || r.top > m.bottom - 80) v.root.scrollIntoView({ block: "center", behavior: "smooth" });
}

function inLabel(cell) {
  const ins = cell.inputs || [];
  if (!ins.length) return "";
  return ins.length === 1 ? `(%i${ins[0]})` : `(%i${ins[0]}–${ins[ins.length - 1]})`;
}

function cellChrome(cell, body) {
  const label = el("span", { class: "in-label", text: cell.type === "markdown" ? "" : inLabel(cell) });
  const runBtn = cell.type === "markdown" ? null : el("button", {
    class: "run", title: "Run (Shift+Enter)", html: '<svg viewBox="0 0 24 24"><path d="M7 4l13 8-13 8z"/></svg>',
    onclick: (e) => { e.stopPropagation(); runCell(cell); },
  });
  const typeSel = el("select", { title: "Cell type", onchange: (e) => changeType(cell, e.target.value) },
    el("option", { value: "code", text: "Maxima" }),
    el("option", { value: "math", text: "Math" }),
    el("option", { value: "markdown", text: "Text" }));
  typeSel.value = cell.type;
  const tools = el("div", { class: "cell-tools" }, typeSel,
    el("button", { title: "Move up", onclick: () => moveCell(cell, -1) }, icon('<path d="M12 19V5M5 12l7-7 7 7"/>')),
    el("button", { title: "Move down", onclick: () => moveCell(cell, 1) }, icon('<path d="M12 5v14M19 12l-7 7-7-7"/>')),
    el("button", { title: "Delete cell", onclick: () => deleteCell(cell) }, icon('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>')));
  const outputs = el("div", { class: "outputs" });
  const root = el("section", { class: `cell cell-${cell.type}`, "data-id": cell.id },
    el("div", { class: "gutter" }, label, runBtn), el("div", { class: "body" }, body, outputs), tools);
  root.addEventListener("mousedown", () => { if (S.active !== cell.id) setActive(cell.id, false); });
  return { root, label, outputs };
}

function makeView(cell) {
  const v = cell.type === "markdown" ? markdownView(cell) : cell.type === "math" ? mathView(cell) : codeView(cell);
  v.cell = cell;
  v.renderOutputs = () => renderOutputs(cell, v);
  v.setRunning = (on) => {
    v.root.classList.toggle("running", on);
    v.label.textContent = on ? "[*]" : inLabel(cell);
  };
  if (cell.type !== "markdown") v.renderOutputs();
  S.views.set(cell.id, v);
  return v;
}

// -- markdown cell -----------------------------------------------------------
function markdownView(cell) {
  const view = el("div", { class: "md-view" });
  const area = el("textarea", { class: "md-edit", spellcheck: "true", placeholder: "Write Markdown. Math: $x^2$ or $$\\int f\\,dx$$" });
  area.hidden = true;
  const body = el("div", {}, view, area);
  const chrome = cellChrome(cell, body);
  const autosize = () => { area.style.height = "auto"; area.style.height = area.scrollHeight + 2 + "px"; };
  const render = () => { view.innerHTML = renderMarkdown(cell.source || ""); };
  const v = {
    ...chrome,
    edit() {
      area.value = cell.source;
      view.hidden = true;
      area.hidden = false;
      area.focus();
      requestAnimationFrame(autosize);
    },
    preview() {
      if (area.hidden) return;
      cell.source = area.value;
      area.hidden = true;
      view.hidden = false;
      render();
      renderOutline();
    },
    focus() { if (!cell.source.trim() || !area.hidden) v.edit(); },
  };
  view.addEventListener("dblclick", () => v.edit());
  area.addEventListener("input", () => { cell.source = area.value; autosize(); setDirty(); outlineSoon(); });
  area.addEventListener("blur", () => v.preview());
  area.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.shiftKey || e.ctrlKey || e.altKey)) {
      e.preventDefault();
      v.preview();
      afterRun(cell, e);
    } else if (e.key === "Escape") {
      area.blur();
    }
  });
  render();
  return v;
}

// -- code cell -------------------------------------------------------------------
function codeEditor(initial, onChange, onKey) {
  const pre = el("pre", { "aria-hidden": "true" });
  const ta = el("textarea", { spellcheck: "false", autocapitalize: "off", autocomplete: "off",
                              placeholder: "Maxima input, e.g. integrate(sin(x)^2, x);", rows: "1" });
  ta.value = initial;
  const paint = () => { pre.innerHTML = highlightMaxima(ta.value) + "\n"; };
  ta.addEventListener("input", () => { paint(); onChange(ta.value); });
  ta.addEventListener("keydown", (e) => {
    if (onKey(e)) return;
    if (e.key === "Tab" && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      const { selectionStart: s, selectionEnd: t, value } = ta;
      if (e.shiftKey) {
        const ls = value.lastIndexOf("\n", s - 1) + 1;
        if (value.startsWith("  ", ls)) {
          ta.value = value.slice(0, ls) + value.slice(ls + 2);
          ta.selectionStart = ta.selectionEnd = Math.max(ls, s - 2);
        }
      } else {
        ta.value = value.slice(0, s) + "  " + value.slice(t);
        ta.selectionStart = ta.selectionEnd = s + 2;
      }
      paint();
      onChange(ta.value);
    }
  });
  paint();
  const box = el("div", { class: "code-editor" }, pre, ta);
  return { box, ta, paint, insert(text) {
    const caret = text.indexOf("|");
    const clean = text.replace("|", "");
    const { selectionStart: s, selectionEnd: t, value } = ta;
    ta.value = value.slice(0, s) + clean + value.slice(t);
    const pos = s + (caret >= 0 ? caret : clean.length);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = pos;
    paint();
    onChange(ta.value);
  } };
}

function codeView(cell) {
  let v;
  const ed = codeEditor(cell.source || "", (val) => { cell.source = val; setDirty(); },
    (e) => cellKey(cell, e));
  const chrome = cellChrome(cell, ed.box);
  ed.ta.addEventListener("focus", () => { if (S.active !== cell.id) setActive(cell.id, false); });
  v = { ...chrome, editor: ed, focus() { ed.ta.focus(); }, insert: (t) => ed.insert(t) };
  return v;
}

// -- math cell -----------------------------------------------------------------------
function mathView(cell) {
  const mf = new MathfieldElement();
  mf.setAttribute("math-virtual-keyboard-policy", "manual");
  mf.smartFence = true;
  mf.value = cell.latex || "";
  const line = el("div", { class: "math-maxima" });
  const box = el("div", { class: "math-box" }, mf, line);
  const chrome = cellChrome(cell, box);
  const showLine = (text, err) => {
    line.classList.toggle("err", !!err);
    line.replaceChildren(el("span", { class: "tag", text: err ? "⚠" : "Maxima" }), el("span", { text }));
  };
  const convert = async () => {
    const latex = cell.latex.trim();
    if (!latex) { cell.source = ""; showLine("type math above — try “int”, “frac”, “matrix”", false); return { ok: true, empty: true }; }
    try {
      const r = await post("/api/convert", { latex, sources: knownFunctionSources() });
      if (r.error) { cell.source = ""; showLine(r.error, true); return { ok: false, error: r.error }; }
      cell.source = r.maxima;
      showLine(r.maxima, false);
      return { ok: true };
    } catch (e) {
      showLine(e.message, true);
      return { ok: false, error: e.message };
    }
  };
  const convertSoon = debounce(convert, 250);
  mf.addEventListener("input", () => {
    cell.latex = mf.value;
    setDirty();
    convertSoon();
    mathSearch.onInput(mf);
  });
  mf.addEventListener("keydown", (e) => {
    if (mathSearch.onKey(e, mf)) return;
    cellKey(cell, e);
  }, { capture: true });
  mf.addEventListener("focus", () => { mathSearch.reset(); if (S.active !== cell.id) setActive(cell.id, false); });
  mf.addEventListener("blur", () => mathSearch.close());
  // Keep MathLive's symbol shortcuts (>=, ->, ...), but let our search handle words.
  queueMicrotask(() => {
    try {
      const keep = {};
      for (const [k, val] of Object.entries(mf.inlineShortcuts || {})) {
        if (!/^[A-Za-z]{2,}$/.test(k) || /^(alpha|beta|gamma|delta|epsilon|theta|lambda|mu|pi|sigma|phi|omega|infty|sin|cos|tan|ln|log|exp)$/.test(k)) keep[k] = val;
      }
      mf.inlineShortcuts = keep;
    } catch { /* older MathLive: keep defaults */ }
  });
  const v = { ...chrome, mf, convert, focus() { mf.focus(); },
    insert(latex) { mf.focus(); mf.insert(latex, { selectionMode: "placeholder", format: "latex" }); } };
  if (cell.latex) {
    if (cell.source) showLine(cell.source, false); else convertSoon();
  } else {
    showLine("type math above — try “int”, “frac”, “matrix”", false);
  }
  return v;
}

// ------------------------------------------------------------------ outputs
function copy(text, what) {
  navigator.clipboard?.writeText(text).then(() => toast(`Copied ${what}`), () => toast("Clipboard not available"));
}

function renderOutputs(cell, v) {
  const box = v.outputs;
  box.replaceChildren();
  const outs = cell.outputs || [];
  outs.forEach((o, i) => {
    if (o.kind === "result") {
      const math = el("div", { class: "out-math" });
      math.innerHTML = o.latex ? renderLatex(o.latex, true) : "";
      if (!o.latex) math.textContent = o.text;
      box.append(el("div", { class: "out out-result" },
        o.label ? el("span", { class: "out-label", text: `(${o.label})` }) : null,
        math,
        el("div", { class: "out-actions" },
          el("button", { text: "LaTeX", title: "Copy as LaTeX", onclick: () => copy(o.latex, "LaTeX") }),
          el("button", { text: "Maxima", title: "Copy as Maxima input", onclick: () => copy(o.text, "Maxima expression") }))));
    } else if (o.kind === "text") {
      box.append(el("pre", { class: "out out-text", text: o.text }));
    } else if (o.kind === "error") {
      box.append(el("pre", { class: "out out-error", text: o.text }));
    } else if (o.kind === "image") {
      const src = o.mime === "image/svg+xml"
        ? "data:image/svg+xml;charset=utf-8," + encodeURIComponent(o.data)
        : `data:${o.mime};base64,${o.data}`;
      box.append(el("div", { class: "out out-image" }, el("img", { src, alt: "plot" })));
    } else if (o.kind === "question") {
      const answered = i < outs.length - 1 || !v.root.classList.contains("running");
      box.append(questionCard(o, answered));
    }
  });
}

function questionCard(q, answered) {
  const qText = el("div", { class: "q" });
  if (q.parts && q.parts.length) qText.innerHTML = q.parts.map((p) => renderLatex(p.latex || p.text)).join(" ");
  else qText.textContent = q.text;
  if (q.text && q.parts && q.parts.length) qText.append(el("div", { class: "d", text: q.text }));
  const card = el("div", { class: "out out-question" }, qText);
  if (answered) return card;
  const input = el("input", { type: "text", placeholder: "Your answer, e.g. positive", "aria-label": "Answer" });
  const send = async (text) => {
    if (!text.trim()) return;
    try { await post("/api/answer", { text }); } catch (e) { toast(e.message); }
  };
  const full = (q.text + " " + (q.parts || []).map((p) => p.text).join(" ")).toLowerCase();
  const quick = /positive|negative/.test(full) ? ["positive", "negative", "zero"]
    : /\?/.test(full) ? ["yes", "no"] : [];
  const form = el("form", { onsubmit: (e) => { e.preventDefault(); send(input.value); } }, input,
    ...quick.map((a) => el("button", { type: "button", text: a, onclick: () => send(a) })),
    el("button", { type: "submit", class: "primary", text: "Answer" }));
  card.append(form);
  setTimeout(() => input.focus(), 30);
  return card;
}

// ------------------------------------------------------------------ running
async function runCell(cell, { quiet = false } = {}) {
  const v = S.views.get(cell.id);
  if (!v) return true;
  if (cell.type === "markdown") { v.preview(); return true; }
  if (S.running) { toast("Another cell is running — wait or press Stop"); return false; }
  if (cell.type === "math") {
    const r = await v.convert();
    if (r.empty) return true;
    if (!r.ok) {
      cell.outputs = [{ kind: "error", text: `Cannot translate this formula: ${r.error}` }];
      v.renderOutputs();
      return false;
    }
  }
  const src = (cell.source || "").trim();
  if (!src) return true;
  S.running = true;
  cell.outputs = [];
  v.setRunning(true);
  v.renderOutputs();
  let ok = false;
  try {
    const { job } = await post("/api/run", { source: src });
    let next = 0;
    for (;;) {
      const st = await get(`/api/job?id=${job}&since=${next}`);
      const status = st.state === "done" ? "idle" : st.question ? "asking" : "busy";
      if (kernelInfo.status !== status) { kernelInfo = { ...kernelInfo, status }; renderKernel(); }
      if (st.outputs.length) {
        cell.outputs.push(...st.outputs);
        next = st.next;
        v.renderOutputs();
      }
      if (st.state === "done") {
        cell.inputs = st.inputs;
        ok = !st.error;
        break;
      }
      await sleep(st.question ? 300 : 90);
    }
  } catch (e) {
    cell.outputs.push({ kind: "error", text: e.message });
  } finally {
    S.running = false;
    v.setRunning(false);
    v.renderOutputs();
    setDirty();
    pollKernel();
  }
  if (!ok && !quiet) toast("The cell stopped with an error");
  return ok;
}

function afterRun(cell, e) {
  const i = S.nb.cells.indexOf(cell);
  if (e.altKey) {
    addCell("code", i + 1, true);
  } else if (e.shiftKey) {
    const next = S.nb.cells[i + 1];
    if (next) setActive(next.id, true);
    else addCell("code", i + 1, true);
  }
}

function cellKey(cell, e) {
  if (e.key === "Enter" && (e.shiftKey || e.ctrlKey || e.altKey) && !(e.shiftKey && e.ctrlKey)) {
    e.preventDefault();
    e.stopPropagation();
    runCell(cell);
    afterRun(cell, e);
    return true;
  }
  if (e.key === "Escape") {
    e.target.blur?.();
    return true;
  }
  return false;
}

async function runAll() {
  if (S.running) { toast("A cell is already running"); return; }
  S.stopRequested = false;
  let n = 0;
  for (const cell of [...S.nb.cells]) {
    if (S.stopRequested) break;
    if (cell.type === "markdown") continue;
    setActive(cell.id, false);
    const ok = await runCell(cell, { quiet: true });
    n++;
    if (!ok) { toast("Stopped at the first cell with an error"); return; }
  }
  if (!S.stopRequested) toast(`Ran ${n} cell${n === 1 ? "" : "s"}`);
}

async function interrupt() {
  S.stopRequested = true;
  await post("/api/interrupt");
  toast("Stopping: Maxima restarts, definitions are cleared");
  setTimeout(pollKernel, 300);
}

async function restart() {
  if (!confirm("Restart Maxima? All definitions and variables are cleared.")) return;
  await post("/api/restart");
  for (const c of S.nb.cells) { delete c.inputs; }
  toast("Maxima is restarting");
  setTimeout(pollKernel, 300);
}

// ------------------------------------------------------------------ outline
function renderOutline() {
  const box = $("#outline");
  const items = [];
  for (const cell of S.nb.cells) {
    if (cell.type !== "markdown") continue;
    for (const h of headingsOf(cell.source || "")) items.push({ ...h, id: cell.id });
  }
  box.replaceChildren(...(items.length ? items.map((h) => el("a", {
    href: "#", class: `l${h.level}`, text: h.text,
    onclick: (e) => { e.preventDefault(); const v = S.views.get(h.id); v?.root.scrollIntoView({ behavior: "smooth", block: "start" }); setActive(h.id, false); },
  })) : [el("div", { class: "empty", text: "Headings in text cells appear here" })]));
}
const outlineSoon = debounce(renderOutline, 300);

function renderRecent() {
  const box = $("#recent");
  box.replaceChildren(...(S.recent.length ? S.recent.slice(0, 8).map((p) => el("a", {
    href: "#", text: p.split(/[\\/]/).pop(), title: p, onclick: (e) => { e.preventDefault(); openPath(p); },
  })) : [el("div", { class: "empty", text: "No recent notebooks" })]));
}

// ------------------------------------------------------------------ modals
function modal(children, { onClose } = {}) {
  const back = el("div", { class: "modal-back" });
  const box = el("div", { class: "modal", role: "dialog", "aria-modal": "true" }, ...children);
  back.append(box);
  const close = () => { back.remove(); document.removeEventListener("keydown", esc, true); onClose?.(); };
  const esc = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } };
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
  document.addEventListener("keydown", esc, true);
  document.body.append(back);
  return { box, close };
}

const OPEN_EXT = [".maxbook", ".wxm", ".wxmx", ".mac", ".md", ".markdown"];

function dirname(p) {
  const i = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return i > 0 ? p.slice(0, i) : p;
}
function joinPath(dir, name) {
  const sep = dir.includes("\\") ? "\\" : "/";
  return dir.replace(/[\\/]+$/, "") + sep + name;
}

function fileDialog({ title, mode, defaultName = "", startDir, okLabel }) {
  return new Promise((resolve) => {
    let dir = startDir || S.cwd;
    let selected = null;
    const pathInput = el("input", { type: "text", "aria-label": "Folder" });
    const drives = el("select", { "aria-label": "Drive", hidden: true });
    const list = el("ul", { class: "files" });
    const nameInput = el("input", { type: "text", placeholder: "File name", value: defaultName, "aria-label": "File name" });
    const ok = el("button", { class: "btn primary", text: okLabel || (mode === "open" ? "Open" : "Save") });
    const cancel = el("button", { class: "btn", text: "Cancel" });
    const sub = el("div", { class: "sub", text: mode === "open"
      ? "Maxbook notebooks, or import wxMaxima (.wxm, .wxmx), Maxima batch (.mac) and Markdown (.md) files."
      : "" });
    const { box, close } = modal([el("header", { text: title }), sub,
      el("div", { class: "crumbs" }, drives, pathInput, el("button", { class: "btn", text: "Up", onclick: () => load(dirname(dir)) })),
      list,
      el("footer", {}, mode === "open" ? el("span", { class: "grow" }) : el("div", { class: "grow" }, nameInput), cancel, ok)]);
    const finish = (value) => { close(); resolve(value); };
    async function load(target) {
      try {
        const r = await get(`/api/fs?path=${encodeURIComponent(target || "")}`);
        dir = r.path;
        pathInput.value = dir;
        if (r.drives?.length) {
          drives.hidden = false;
          drives.replaceChildren(...r.drives.map((d) => el("option", { value: d, text: d })));
          drives.value = r.drives.find((d) => dir.toUpperCase().startsWith(d.toUpperCase())) || r.drives[0];
        }
        list.replaceChildren(...r.entries.map((ent) => {
          const li = el("li", { title: ent.path }, el("span", { class: "ic", text: ent.dir ? "▸" : "·" }), el("span", { text: ent.name }));
          li.addEventListener("click", () => {
            list.querySelectorAll(".sel").forEach((x) => x.classList.remove("sel"));
            li.classList.add("sel");
            if (ent.dir) return;
            selected = ent.path;
            if (mode !== "open") nameInput.value = ent.name;
          });
          li.addEventListener("dblclick", () => (ent.dir ? load(ent.path) : finish(ent.path)));
          return li;
        }));
        if (!r.entries.length) list.append(el("li", { text: "(empty folder)" }));
      } catch (e) {
        toast(e.message);
      }
    }
    pathInput.addEventListener("keydown", (e) => { if (e.key === "Enter") load(pathInput.value); });
    drives.addEventListener("change", () => load(drives.value));
    cancel.addEventListener("click", () => finish(null));
    ok.addEventListener("click", () => {
      if (mode === "open") { if (selected) finish(selected); else toast("Choose a file"); return; }
      const name = nameInput.value.trim();
      if (!name) { toast("Enter a file name"); return; }
      finish(/^([A-Za-z]:)?[\\/]/.test(name) ? name : joinPath(dir, name));
    });
    nameInput.addEventListener("keydown", (e) => { if (e.key === "Enter") ok.click(); });
    load(dir);
    (mode === "open" ? pathInput : nameInput).focus();
    void box;
  });
}

function confirmDiscard() {
  return !S.dirty || confirm("Discard unsaved changes?");
}

// ------------------------------------------------------------------ files
function loadNotebook(nb, path, { suggested = null, note = "" } = {}) {
  S.nb = nb;
  S.path = path;
  S.suggested = suggested;
  S.active = null;
  try { sessionStorage.setItem("maxbook-path", path || ""); } catch { /* ignore */ }
  setDirty(false);
  renderNotebook();
  banner(note);
  const first = S.nb.cells.find((c) => c.type !== "markdown") || S.nb.cells[0];
  if (first) setActive(first.id, false);
}

async function newNotebook() {
  if (!confirmDiscard()) return;
  const r = await post("/api/new", { title: "Untitled" });
  loadNotebook(r.notebook, null);
}

async function openPath(p) {
  if (!confirmDiscard()) return;
  try {
    const r = await post("/api/open", { path: p });
    loadNotebook(r.notebook, r.path, { suggested: r.suggested, note: r.note });
    if (r.path) { S.recent = [r.path, ...S.recent.filter((x) => x !== r.path)]; renderRecent(); }
    toast(`Opened ${p.split(/[\\/]/).pop()}`);
  } catch (e) { toast(e.message, 5000); }
}

async function openDialog() {
  const start = S.path ? dirname(S.path) : S.cwd;
  const p = await fileDialog({ title: "Open notebook", mode: "open", startDir: start });
  if (p) openPath(p);
}

function syncEditors() {
  for (const v of S.views.values()) if (v.cell.type === "markdown" && v.preview) v.preview();
}

async function save(asNew = false) {
  syncEditors();
  let p = S.path;
  if (!p || asNew) {
    const base = S.suggested || (S.path ? S.path : joinPath(S.cwd, `${slug(S.nb.title)}.maxbook`));
    p = await fileDialog({ title: "Save notebook", mode: "save", defaultName: base.split(/[\\/]/).pop(), startDir: dirname(base) });
    if (!p) return false;
  }
  try {
    const r = await post("/api/save", { path: p, notebook: S.nb });
    S.path = r.path;
    S.suggested = null;
    setDirty(false);
    S.recent = [r.path, ...S.recent.filter((x) => x !== r.path)];
    renderRecent();
    toast(`Saved ${r.path.split(/[\\/]/).pop()}`);
    return true;
  } catch (e) { toast(e.message, 5000); return false; }
}

function slug(s) {
  return (s || "notebook").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "notebook";
}

const EXPORTS = [
  { fmt: "tex", ext: ".tex", t: "LaTeX document", d: "Compilable .tex with figures as PNG" },
  { fmt: "html", ext: ".html", t: "HTML page", d: "Single self-contained file, rendered math, works offline" },
  { fmt: "md", ext: ".md", t: "Markdown", d: "Text, ```maxima blocks and $$ results" },
  { fmt: "mac", ext: ".mac", t: "Maxima batch file", d: "Code only, text as comments; runs with batch()" },
  { fmt: "wxm", ext: ".wxm", t: "wxMaxima document", d: "Opens in wxMaxima (outputs are recomputed there)" },
];

async function exportDialog() {
  syncEditors();
  const choice = await new Promise((resolve) => {
    const ul = el("ul", { class: "palette-list" }, ...EXPORTS.map((x) => el("li", { onclick: () => { resolve(x); close(); } },
      el("div", {}, el("div", { text: x.t }), el("div", { class: "k", text: x.d })), el("span", { class: "k", text: x.ext }))));
    const { close } = modal([el("header", { text: "Export" }), ul], { onClose: () => resolve(null) });
  });
  if (!choice) return;
  const base = (S.path || S.suggested || joinPath(S.cwd, slug(S.nb.title) + ".maxbook")).replace(/\.[^.\\/]+$/, "");
  const p = await fileDialog({ title: `Export as ${choice.t}`, mode: "save", defaultName: base.split(/[\\/]/).pop() + choice.ext, startDir: dirname(base), okLabel: "Export" });
  if (!p) return;
  try {
    const body = { format: choice.fmt, path: p, notebook: S.nb };
    if (choice.fmt === "html") body.html = await buildHtmlExport(S.nb);
    if (choice.fmt === "tex") body.figures = await rasterizeImages(S.nb);
    const r = await post("/api/export", body);
    toast(`Exported ${r.written.length} file${r.written.length > 1 ? "s" : ""}: ${r.written[0].split(/[\\/]/).pop()}`, 4000);
  } catch (e) { toast(e.message, 6000); }
}

// ------------------------------------------------------------------ palette
function activeView() { return S.active ? S.views.get(S.active) : null; }

function insertTemplate(item) {
  let v = activeView();
  if (item.latex !== undefined) {
    if (!v || v.cell.type !== "math") {
      const idx = v ? S.nb.cells.indexOf(v.cell) + 1 : S.nb.cells.length;
      addCell("math", idx, true);
      v = activeView();
    }
    setTimeout(() => v.insert(item.latex), 30);
  } else {
    if (!v || v.cell.type !== "code") {
      const idx = v ? S.nb.cells.indexOf(v.cell) + 1 : S.nb.cells.length;
      addCell("code", idx, true);
      v = activeView();
    }
    setTimeout(() => v.insert(item.code), 30);
  }
}

const COMMANDS = [
  { t: "Run all cells", k: "run all execute", run: () => runAll(), key: "Ctrl+Shift+Enter" },
  { t: "Stop computation", k: "interrupt stop abort", run: () => interrupt() },
  { t: "Restart Maxima", k: "restart kernel reset", run: () => restart() },
  { t: "New notebook", k: "new", run: () => newNotebook(), key: "Ctrl+Alt+N" },
  { t: "Open…", k: "open import wxm wxmx", run: () => openDialog(), key: "Ctrl+O" },
  { t: "Save", k: "save", run: () => save(), key: "Ctrl+S" },
  { t: "Save as…", k: "save as", run: () => save(true), key: "Ctrl+Shift+S" },
  { t: "Export…", k: "export latex html markdown wxm mac pdf", run: () => exportDialog() },
  { t: "Insert Maxima cell below", k: "add insert code cell", run: () => addCellBelow("code") },
  { t: "Insert math cell below", k: "add insert math formula cell", run: () => addCellBelow("math") },
  { t: "Insert text cell below", k: "add insert markdown text cell", run: () => addCellBelow("markdown") },
  { t: "Toggle sidebar", k: "outline sidebar", run: () => $("#layout").classList.toggle("no-side") },
  { t: "Toggle light/dark", k: "theme dark light", run: () => toggleTheme() },
  { t: "Print / save as PDF", k: "print pdf", run: () => window.print() },
  { t: "Keyboard shortcuts", k: "help keys", run: () => showHelp(), key: "F1" },
  { t: "Quit Maxbook", k: "quit exit close", run: () => quit() },
];

function addCellBelow(type) {
  const v = activeView();
  addCell(type, v ? S.nb.cells.indexOf(v.cell) + 1 : S.nb.cells.length, true);
}

function openPalette() {
  const v = activeView();
  const prefer = v?.cell.type === "code" ? CODE_TEMPLATES : MATH_TEMPLATES;
  const other = prefer === CODE_TEMPLATES ? MATH_TEMPLATES : CODE_TEMPLATES;
  const input = el("input", { class: "palette-input", type: "text", placeholder: "Search commands and templates…", "aria-label": "Search" });
  const ul = el("ul", { class: "palette-list" });
  let items = [];
  let sel = 0;
  const { close } = modal([input, ul]);
  const pick = (it) => { close(); if (it.run) it.run(); else insertTemplate(it); };
  const render = () => {
    const q = input.value;
    const cmds = searchTemplates(COMMANDS, q).map((x) => ({ ...x, grp: "Command" }));
    const t1 = searchTemplates(prefer, q).map((x) => ({ ...x, grp: x.latex !== undefined ? "Math" : "Maxima" }));
    const t2 = q ? searchTemplates(other, q).map((x) => ({ ...x, grp: x.latex !== undefined ? "Math" : "Maxima" })) : [];
    items = [...cmds, ...t1, ...t2].slice(0, 60);
    sel = Math.min(sel, Math.max(0, items.length - 1));
    ul.replaceChildren(...items.map((it, i) => {
      const li = el("li", { class: i === sel ? "sel" : "", onclick: () => pick(it) },
        el("div", {}, el("div", { text: it.t }), it.latex ? el("div", { class: "k", html: renderLatex(it.latex.replace(/#[0?]/g, "\\placeholder{}")) })
          : it.code ? el("div", { class: "k", text: it.code.replace("|", "…") }) : null),
        el("span", { class: "grp", text: it.key || it.grp }));
      return li;
    }));
  };
  input.addEventListener("input", () => { sel = 0; render(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); render(); ul.children[sel]?.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); render(); ul.children[sel]?.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[sel]) pick(items[sel]); }
  });
  render();
  input.focus();  // synchronously, so fast typing cannot land in the previous element
}

// -- search-as-you-type inside math cells --------------------------------------
const mathSearch = (() => {
  // The word is read from the formula itself (letters right before the caret),
  // so it works for keyboards, IMEs and pasted text alike.
  let word = "";
  let dismissed = "";
  let items = [];
  let sel = 0;
  let pop = null;
  const close = () => { pop?.remove(); pop = null; items = []; };
  const reset = () => { word = ""; close(); };
  const wordBeforeCaret = (mf) => {
    let before = "";
    try { before = mf.getValue(0, mf.position, "latex"); } catch { return ""; }
    const m = before.match(/(?:^|[^A-Za-z\\])([A-Za-z]{2,})$/);
    return m ? m[1] : "";
  };
  function show(mf) {
    items = word.length >= 2 ? searchTemplates(MATH_TEMPLATES, word).slice(0, 7) : [];
    if (!items.length) { close(); return; }
    sel = Math.min(sel, items.length - 1);
    if (!pop) { pop = el("div", { class: "popover" }); document.body.append(pop); }
    pop.replaceChildren(el("div", { class: "head" }, el("span", { text: `“${word}”` }), el("span", { text: "Enter/Tab insert · Space ignore" })),
      el("ul", {}, ...items.map((it, i) => el("li", { class: i === sel ? "sel" : "",
        onmousedown: (e) => { e.preventDefault(); sel = i; accept(mf); } },
      el("span", { class: "glyph", html: renderLatex(it.latex.replace(/#[0?]/g, "\\placeholder{}")) }),
      el("div", {}, el("div", { class: "t", text: it.t }), el("div", { class: "d", text: it.k })),
      el("kbd", { text: i === 0 ? "↵" : "" })))));
    let r;
    try { r = mf.caretPoint ? { left: mf.caretPoint.x, bottom: mf.caretPoint.y + 18 } : null; } catch { r = null; }
    const box = mf.getBoundingClientRect();
    const left = Math.min(window.innerWidth - 430, (r?.left ?? box.left) - 20);
    const top = Math.min(window.innerHeight - 330, (r?.bottom ?? box.bottom) + 8);
    pop.style.left = Math.max(8, left) + "px";
    pop.style.top = Math.max(8, top) + "px";
  }
  function accept(mf) {
    const it = items[sel];
    if (!it) return;
    const n = word.length;
    let tail = "";
    try { tail = mf.getValue(Math.max(0, mf.position - n), mf.position, "latex").replace(/\s+/g, ""); } catch { tail = ""; }
    if (tail === word) for (let i = 0; i < n; i++) mf.executeCommand("deleteBackward");
    mf.insert(it.latex, { selectionMode: "placeholder", format: "latex" });
    reset();
    dismissed = "";
    mf.dispatchEvent(new Event("input", { bubbles: true }));
  }
  return {
    reset, close,
    onKey(e, mf) {
      if (pop) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault(); e.stopPropagation();
          sel = (sel + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
          show(mf);
          return true;
        }
        if ((e.key === "Enter" || e.key === "Tab") && !e.shiftKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault(); e.stopPropagation();
          accept(mf);
          return true;
        }
        if (e.key === "Escape" || e.key === " ") {
          e.preventDefault(); e.stopPropagation();
          dismissed = word;
          reset();
          return true;
        }
      }
      return false;
    },
    onInput(mf) {
      const w = wordBeforeCaret(mf);
      if (w !== word) sel = 0;
      word = w;
      if (word.length >= 2 && word !== dismissed) show(mf);
      else close();
      if (!word) dismissed = "";
    },
  };
})();

// ------------------------------------------------------------------ misc ui
function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("maxbook-theme", root.dataset.theme); } catch { /* ignore */ }
}

function showHelp() {
  const rows = [
    ["Shift+Enter", "Run cell and move to the next one"], ["Ctrl+Enter", "Run cell, stay"],
    ["Alt+Enter", "Run cell and insert a new one below"], ["Ctrl+Shift+Enter", "Run all cells"],
    ["Ctrl+K", "Search commands and templates"], ["Ctrl+S / Ctrl+Shift+S", "Save / Save as"],
    ["Ctrl+O", "Open or import (.wxm, .wxmx, .mac, .md)"], ["Esc", "Leave the editor"],
    ["Math cell: type a word", "e.g. int, frac, sum, matrix, lim, sqrt — then Enter or Tab"],
    ["Math cell: Tab", "Jump to the next empty box"], ["Text cell: double-click", "Edit Markdown; $…$ for math"],
    ["iplot2d(…), idraw2d(…)", "Inline plots (wxplot2d also works)"],
  ];
  modal([el("header", { text: "Keyboard and tips" }),
    el("div", { class: "sub" }, el("table", { class: "kbd-help" }, ...rows.map(([k, d]) => el("tr", {}, el("td", { text: k }), el("td", { text: d })))))]);
}

async function quit() {
  if (S.dirty && !confirm("Quit without saving?")) return;
  try { await post("/api/shutdown"); } catch { /* already gone */ }
  document.body.replaceChildren(el("div", { class: "banner", text: "Maxbook has stopped. You can close this window." }));
}

function bindToolbar() {
  const cmds = { new: newNotebook, open: openDialog, save: () => save(), export: exportDialog, "run-all": runAll,
                 interrupt, restart, palette: openPalette, theme: toggleTheme, help: showHelp };
  document.querySelectorAll("[data-cmd]").forEach((b) => b.addEventListener("click", () => cmds[b.dataset.cmd]()));
  $("#title").addEventListener("input", (e) => { S.nb.title = e.target.value; setDirty(); });
  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(e.shiftKey); }
    else if (mod && e.key.toLowerCase() === "o") { e.preventDefault(); openDialog(); }
    else if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
    else if (mod && e.altKey && e.key.toLowerCase() === "n") { e.preventDefault(); newNotebook(); }
    else if (mod && e.shiftKey && e.key === "Enter") { e.preventDefault(); runAll(); }
    else if (e.key === "F1") { e.preventDefault(); showHelp(); }
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
}

// ------------------------------------------------------------------ boot
async function boot() {
  try {
    const t = localStorage.getItem("maxbook-theme");
    if (t) document.documentElement.dataset.theme = t;
  } catch { /* storage unavailable */ }
  if (!initToken()) {
    banner("This page needs the link printed by Maxbook (it carries a session key). Start it with: maxbook", "err");
    return;
  }
  bindToolbar();
  let session;
  try {
    session = await get("/api/session");
  } catch (e) {
    banner(e instanceof ApiError && e.status === 403
      ? "Session key rejected — open the link printed by the current Maxbook process." : e.message, "err");
    return;
  }
  S.recent = session.recent || [];
  S.home = session.home;
  S.cwd = session.cwd;
  kernelInfo = session.kernel;
  renderKernel();
  renderRecent();
  let reopen = "";
  try { reopen = sessionStorage.getItem("maxbook-path") || ""; } catch { /* ignore */ }
  if (!session.initial && reopen) {
    // A page reload: show the file this window had open, not a blank notebook.
    try {
      const r = await post("/api/open", { path: reopen });
      loadNotebook(r.notebook, r.path);
    } catch { loadNotebook(session.notebook, session.path, { note: session.note }); }
  } else {
    loadNotebook(session.notebook, session.path, { note: session.note, suggested: session.suggested });
  }
  if (kernelInfo.status === "missing") banner(kernelInfo.error, "err");
  setInterval(() => { if (!S.running) pollKernel(); }, 2000);
  void api;
}

boot();
