// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Maxbook front end: one continuous document (prose, formulas, Maxima),
// computed by Maxima, saved as .maxbook, shared through the collaboration hub.

import { model, commands, schemaList } from "../vendor/prosemirror/prosemirror.mjs";
import { get, post, initToken, ApiError } from "./api.js";
import { schema, newId } from "./schema.js";
import { cellsToDoc, markdownToNodes } from "./markdown.js";
import { createEditor, insertBlock, insertInlineMath, insertMathBlock, insertMaxima, NodeSelection, TextSelection } from "./editor.js";
import { el } from "./nodeviews.js";
import { renderMath } from "./mathrender.js";
import { MATH_TEMPLATES, CODE_TEMPLATES, searchTemplates } from "./templates.js";
import { buildHtmlExport, rasterizeImages } from "./export.js";
import { CollabClient } from "./collab.js";
import { SymbolRegistry, installHover, renderObjectsPanel } from "./symbols.js";
import { MENUS, dialogForm } from "./dialogs.js";

const { Fragment, Slice } = model;
const { toggleMark, setBlockType, wrapIn } = commands;
const { wrapInList } = schemaList;
const N = schema.nodes;

// ------------------------------------------------------------------ state
const S = {
  view: null,
  collab: null,
  role: "host",
  path: null,
  suggested: null,
  dirty: false,
  running: new Set(),
  busy: false,
  stopRequested: false,
  recent: [],
  cwd: "",
  kernel: {},
  ai: { enabled: false },
  share: { enabled: false },
  active: null,
  autoEdit: new Set(),
};

const $ = (sel) => document.querySelector(sel);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const debounce = (fn, ms) => { let t = 0; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const isHost = () => S.role === "host";

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

function title() { return S.view?.state.doc.attrs.title || "Untitled"; }

function setDirty(d = true) {
  S.dirty = d;
  $("#dirty").hidden = !d;
  document.title = `${d ? "• " : ""}${title()} — Maxbook`;
}

// ------------------------------------------------------------------ document helpers
function findById(id) {
  let found = null;
  S.view?.state.doc.descendants((node, pos) => {
    if (found) return false;
    if (node.attrs && node.attrs.id === id) { found = { node, pos }; return false; }
    return true;
  });
  return found;
}

function updateNode(id, attrs, { history = false } = {}) {
  const f = findById(id);
  if (!f) return false;
  const tr = S.view.state.tr;
  for (const [k, v] of Object.entries(attrs)) tr.setNodeAttribute(f.pos, k, v);
  if (!history) tr.setMeta("addToHistory", false);
  S.view.dispatch(tr);
  return true;
}

function setDocAttr(name, value) {
  const tr = S.view.state.tr.setDocAttribute(name, value);
  S.view.dispatch(tr);
}

function knownSources() {
  const out = [];
  S.view?.state.doc.descendants((n) => {
    if (n.attrs?.source) out.push(n.attrs.source);
  });
  return out;
}

function notebookJSON() {
  const doc = S.view.state.doc.toJSON();
  return { format: "maxbook", version: 2, title: title(), doc, metadata: {} };
}

// ------------------------------------------------------------------ kernel
function shortVersion(v) {
  const m = String(v || "").match(/(\d+)[._](\d+)(?:[._](\d+))?/);
  return m ? `${m[1]}.${m[2]}${m[3] && !/branch/.test(v) ? "." + m[3] : ""}` : v || "";
}

function renderKernel() {
  const k = S.kernel;
  const pill = $("#kernel");
  const st = k.status || "stopped";
  pill.dataset.status = st;
  const name = k.version ? `Maxima ${shortVersion(k.version)}` : "Maxima";
  const label = { idle: "ready", busy: "computing…", asking: "waiting for your answer", starting: "starting…",
                  missing: "not found", dead: "stopped", stopped: "stopped" }[st] || st;
  pill.lastChild.textContent = `${name} · ${label}`;
  pill.title = [k.maxima_path, k.lisp, k.error].filter(Boolean).join("\n");
}

async function pollKernel() {
  try { S.kernel = await get("/api/kernel"); } catch (e) { S.kernel = { status: "dead", error: e.message }; }
  renderKernel();
}

async function convert(latex) {
  try {
    return await post("/api/convert", { latex, sources: knownSources() });
  } catch (e) {
    return { error: e.message };
  }
}

/** Run Maxima source through a job; streams outputs to onOutput(all). */
async function runSource(source, onOutput) {
  const { job } = await post("/api/run", { source });
  let next = 0;
  const outputs = [];
  for (;;) {
    const st = await get(`/api/job?id=${job}&since=${next}`);
    const status = st.state === "done" ? "idle" : st.question ? "asking" : "busy";
    if (S.kernel.status !== status) { S.kernel = { ...S.kernel, status }; renderKernel(); }
    if (st.outputs.length) {
      outputs.push(...st.outputs);
      next = st.next;
      onOutput?.(outputs.slice());
    }
    if (st.state === "done") return { outputs, error: st.error, inputs: st.inputs };
    await sleep(st.question ? 300 : 90);
  }
}

async function runNode(id, { advance = false, insertAfter = false, quiet = false } = {}) {
  if (!isHost()) { toast("Only the host can run Maxima"); return false; }
  if (S.busy) { toast("Maxima is busy — wait or press Stop"); return false; }
  const f = findById(id);
  if (!f) return false;
  let source = f.node.attrs.source;
  if (f.node.type === N.math_block) {
    const latex = f.node.attrs.latex.trim().replace(/=\s*$/, "");
    if (!latex) return true;
    const r = await convert(latex);
    if (r.error) {
      updateNode(id, { outputs: [{ kind: "error", text: `Cannot translate this formula: ${r.error}` }], run: true });
      return false;
    }
    source = r.maxima;
    updateNode(id, { source, run: true });
  }
  if (!source || !source.trim()) { if (advance || insertAfter) afterRun(id, { advance, insertAfter }); return true; }
  S.busy = true;
  S.running.add(id);
  updateNode(id, { outputs: [] });
  let ok = false;
  let interrupted = false;
  try {
    const res = await runSource(source, (outs) => updateNode(id, { outputs: outs }));
    ok = !res.error;
    interrupted = res.outputs.some((o) => o.interrupted);
    S.running.delete(id);
    updateNode(id, { outputs: res.outputs, inputs: res.inputs || [] });
  } catch (e) {
    S.running.delete(id);
    updateNode(id, { outputs: [{ kind: "error", text: e.message }] });
  } finally {
    S.running.delete(id);
    S.busy = false;
    pollKernel();
    registry.refresh();
  }
  if (!ok && !quiet) toast(interrupted ? "Stopped" : "Stopped with an error");
  if (advance || insertAfter) afterRun(id, { advance, insertAfter });
  return ok;
}

function afterRun(id, { advance, insertAfter }) {
  const f = findById(id);
  if (!f) return;
  const end = f.pos + f.node.nodeSize;
  const state = S.view.state;
  if (insertAfter) {
    const nid = newId();
    S.autoEdit.add(nid);
    let tr = state.tr.insert(end, N.maxima.create({ id: nid }));
    if (!tr.doc.resolve(end + 1).nodeAfter) tr = tr.insert(end + 1, N.paragraph.create());
    S.view.dispatch(tr.scrollIntoView());
    return;
  }
  if (advance) {
    const next = state.doc.resolve(end).nodeAfter;
    if (next && (next.type === N.maxima || next.type === N.math_block)) {
      focusNodeAt(end);
      return;
    }
    let tr = state.tr;
    if (!next || next.type !== N.paragraph) tr = tr.insert(end, N.paragraph.create());
    S.view.dispatch(tr.setSelection(TextSelection.create(tr.doc, end + 1)).scrollIntoView());
    S.view.focus();
  }
}

/** "= then Tab" (compute) and ":= then Tab" (define) for any formula. */
async function computeInPlace(id) {
  if (S.busy) { toast("Maxima is busy"); return false; }
  const f = findById(id);
  if (!f) return false;
  const latex = f.node.attrs.latex.trim();
  let mode;
  let expr;
  if (/=\s*$/.test(latex)) { mode = "value"; expr = latex.replace(/=\s*$/, ""); }
  else if (/\\coloneq|:=/.test(latex)) { mode = "define"; expr = latex; }
  else return false;
  if (!expr.trim()) return false;
  const r = await convert(expr);
  if (r.error) {
    updateNode(id, { result: { error: r.error } });
    toast(`Cannot translate: ${r.error}`, 4000);
    return false;
  }
  // Asking for a value means "work it out": evaluate noun forms such as an
  // unevaluated integral and simplify symbolic sums (Maxima leaves both alone).
  const body = r.maxima.trim().replace(/[;$]$/, "");
  const run = mode === "value" && !/[;$]/.test(body) ? `ev(${body}, nouns, simpsum);` : r.maxima;
  S.busy = true;
  let result;
  try {
    const res = await runSource(run);
    const errs = res.outputs.filter((o) => o.kind === "error");
    const last = [...res.outputs].reverse().find((o) => o.kind === "result");
    if (res.error || errs.length) result = { error: errs.map((o) => o.text).join("\n") || "Maxima reported an error" };
    else if (mode === "define") result = { text: "defined" };
    else if (last) result = { latex: last.latex, semantic: last.semantic || last.latex, text: last.text };
    else result = { error: "Maxima returned no value" };
  } catch (e) {
    result = { error: e.message };
  } finally {
    S.busy = false;
    pollKernel();
  }
  updateNode(id, { source: r.maxima, result });
  registry.refresh();
  if (result.error) toast(result.error.split("\n")[0], 5000);
  return !result.error;
}

async function runAll() {
  if (!isHost()) return;
  if (S.busy) { toast("Maxima is busy"); return; }
  S.stopRequested = false;
  const items = [];
  S.view.state.doc.descendants((node) => {
    const a = node.attrs || {};
    if (node.type === N.maxima) items.push({ id: a.id, kind: "run" });
    else if (node.type === N.math_block && a.run) items.push({ id: a.id, kind: "run" });
    else if ((node.type === N.math_block || node.type === N.math_inline) &&
             (/=\s*$/.test(a.latex) || /\\coloneq|:=/.test(a.latex))) {
      items.push({ id: a.id, kind: "compute" });
    }
  });
  let n = 0;
  for (const it of items) {
    if (S.stopRequested) break;
    const ok = it.kind === "run" ? await runNode(it.id, { quiet: true }) : await computeInPlace(it.id);
    n++;
    if (!ok) {
      const f = findById(it.id);
      if (f) S.view.nodeDOM(f.pos)?.scrollIntoView?.({ block: "center", behavior: "smooth" });
      toast("Stopped at the first error");
      return;
    }
  }
  if (!S.stopRequested) toast(`Computed ${n} item${n === 1 ? "" : "s"}`);
}

async function interrupt() {
  S.stopRequested = true;
  await post("/api/interrupt");
  toast("Stopping…");
  setTimeout(pollKernel, 400);
}

async function restart() {
  if (!confirm("Restart Maxima? All definitions and variables are cleared.")) return;
  S.stopRequested = true;
  await post("/api/restart");
  toast("Maxima is restarting");
  setTimeout(() => { pollKernel(); registry.refresh(); }, 1500);
}

// ------------------------------------------------------------------ editor context for node views
function focusNodeAt(pos) {
  const dom = S.view.nodeDOM(pos);
  const inst = dom && ctx.instances.get(dom);
  if (!inst) return false;
  inst.focus();
  return true;
}

const ctx = {
  instances: new WeakMap(),
  get isHost() { return isHost(); },
  isRunning: (id) => S.running.has(id),
  runNode,
  computeInPlace,
  convert,
  kindOf: (name) => registry.kindOf(name),
  toast,
  copy(text, what) {
    navigator.clipboard?.writeText(text).then(() => toast(`Copied ${what}`), () => toast("Clipboard not available"));
  },
  answer: (text) => post("/api/answer", { text }).catch((e) => toast(e.message)),
  markAutoEdit: (id) => S.autoEdit.add(id),
  consumeAutoEdit: (id) => S.autoEdit.delete(id),
  setActive: (inst) => { S.active = inst; },
  clearActive: (inst) => { if (S.active === inst) S.active = null; },
  focusNodeAt,
  promoteToBlock(pos) {
    const state = S.view.state;
    const $pos = state.doc.resolve(pos);
    const para = $pos.parent;
    const id = newId();
    S.autoEdit.add(id);
    if (para.type === N.paragraph && para.childCount === 1 && $pos.depth >= 1) {
      const from = $pos.before($pos.depth);
      let tr = state.tr.replaceWith(from, $pos.after($pos.depth), N.math_block.create({ id }));
      if (!tr.doc.resolve(from + 1).nodeAfter) tr = tr.insert(from + 1, N.paragraph.create());
      S.view.dispatch(tr);
    } else {
      const tr = state.tr.delete(pos, pos + 1);
      S.view.dispatch(tr);
      insertMathBlock(S.view.state, S.view.dispatch, ctx);
    }
  },
  insertFormulaAfter(pos) {
    const node = S.view.state.doc.nodeAt(pos);
    if (!node) return;
    toast("Write the formula; the Maxima block stays as it is");
    const id = newId();
    S.autoEdit.add(id);
    S.view.dispatch(S.view.state.tr.insert(pos + node.nodeSize, N.math_block.create({ id, run: true })));
  },
  clipboardTextParser(text, $context, plain) {
    if (plain || $context.parent.type.spec.code) return null;
    if (!/[$#*`_>\-]|^\s*\d+\./m.test(text)) return null;
    const nodes = markdownToNodes(text);
    if (nodes.length === 1 && nodes[0].type === N.paragraph) {
      return new Slice(Fragment.from(nodes[0]), 1, 1);
    }
    return new Slice(Fragment.from(nodes), 0, 0);
  },
  mathSearch: null,
};

// ------------------------------------------------------------------ math search popup
ctx.mathSearch = (() => {
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
      el("span", { class: "glyph", html: renderMath(it.latex.replace(/#[0?]/g, "\\placeholder{}")) }),
      el("div", {}, el("div", { class: "t", text: it.t }), el("div", { class: "d", text: it.k })),
      el("kbd", { text: i === 0 ? "↵" : "" })))));
    let r;
    try { r = mf.caretPoint ? { left: mf.caretPoint.x, bottom: mf.caretPoint.y + 18 } : null; } catch { r = null; }
    const box = mf.getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(window.innerWidth - 430, (r?.left ?? box.left) - 20)) + "px";
    pop.style.top = Math.max(8, Math.min(window.innerHeight - 330, (r?.bottom ?? box.bottom) + 8)) + "px";
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
      if (!pop) return false;
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

// ------------------------------------------------------------------ symbols
const registry = new SymbolRegistry({
  getDescriptions: () => S.view?.state.doc.attrs.symbols || {},
  setDescription: (name, description) => {
    const cur = { ...(S.view.state.doc.attrs.symbols || {}) };
    if (description) cur[name] = { description }; else delete cur[name];
    setDocAttr("symbols", cur);
  },
  onChange: () => { refreshObjects(); rerenderFormulas(); },
});

function rerenderFormulas() {
  // re-tag typed formulas so their colours follow what Maxima now knows
  document.querySelectorAll(".mbk-math-inline, .mbk-mathblock").forEach((dom) => {
    const inst = ctx.instances.get(dom);
    if (inst && !inst.mf) inst.render?.();
  });
}

const refreshObjects = debounce(() => {
  if (!S.view || $("#layout").classList.contains("no-objects")) return;
  const used = new Set();
  S.view.state.doc.descendants((n) => {
    for (const m of (n.attrs?.source || "").matchAll(/[%A-Za-z_][A-Za-z0-9_%]*/g)) used.add(m[0]);
  });
  renderObjectsPanel($("#objects-list"), registry, $("#editor"), {
    used,
    onEditDescription: (name, current) => {
      const v = prompt(`Describe “${name}” (shown when hovering it; saved in the notebook):`, current || "");
      if (v !== null) registry.setDescription(name, v.trim());
    },
  });
}, 300);

// ------------------------------------------------------------------ outline
const renderOutline = debounce(() => {
  if (!S.view) return;
  const items = [];
  S.view.state.doc.descendants((node, pos) => {
    if (node.type === N.heading) items.push({ level: node.attrs.level, text: node.textContent, pos });
    return node.isBlock && node.type !== N.maxima;
  });
  $("#outline").replaceChildren(...(items.length ? items.map((h) => el("a", {
    href: "#", class: `l${Math.min(h.level, 3)}`, text: h.text || "(untitled)",
    onclick: (e) => {
      e.preventDefault();
      S.view.nodeDOM(h.pos)?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
  })) : [el("div", { class: "empty", text: "Headings appear here (type # and a space)" })]));
}, 250);

// ------------------------------------------------------------------ the editor lifecycle
function makeCollab() {
  return new CollabClient({
    name: localName(), color: localColour(), role: S.role,
    onReset: () => rejoin(),
    onUsers: renderUsers,
    onPath: (p) => { if (p !== undefined && isHost()) S.path = p; },
    onError: () => {},
  });
}

async function mountDocument(doc, { path = null, suggested = null, note = "", publish = true, version = 0 } = {}) {
  if (publish) version = await S.collab.start(doc, path);
  S.view?.destroy();
  $("#editor").replaceChildren();
  S.view = createEditor({
    mount: $("#editor"), doc, ctx,
    extraPlugins: [S.collab.plugin(version)],
    onTransaction(tr) {
      if (tr.docChanged) {
        const t = S.view.state.doc.attrs.title || "Untitled";
        if (document.activeElement !== $("#title") && $("#title").value !== t) $("#title").value = t;
        setDirty(true);
        renderOutline();
        refreshObjects();
        S.collab.changed();
      }
      if (tr.getMeta?.("collab$")) refreshObjects();
    },
  });
  S.collab.attach(S.view);
  S.path = path;
  S.suggested = suggested;
  $("#title").value = doc.attrs.title || "Untitled";
  setDirty(false);
  renderOutline();
  refreshObjects();
  banner(note);
  try { sessionStorage.setItem("maxbook-path", path || ""); } catch { /* ignore */ }
}

async function rejoin() {
  const joined = await S.collab.join().catch(() => null);
  if (!joined) return;
  await mountDocument(joined.doc, { path: joined.path, publish: false, version: joined.version });
}

function docFromNotebook(nb) {
  if (nb.version >= 2 && nb.doc) {
    const doc = schema.nodeFromJSON(nb.doc);
    return doc.attrs.title ? doc : schema.nodes.doc.create({ ...doc.attrs, title: nb.title }, doc.content);
  }
  return cellsToDoc(nb);
}

// ------------------------------------------------------------------ files
function dirname(p) {
  const i = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return i > 0 ? p.slice(0, i) : p;
}
const joinPath = (dir, name) => dir.replace(/[\\/]+$/, "") + (dir.includes("\\") ? "\\" : "/") + name;
const slug = (s) => (s || "notebook").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "notebook";
const confirmDiscard = () => !S.dirty || confirm("Discard unsaved changes?");

function modal(children, { onClose, wide = false } = {}) {
  const back = el("div", { class: "modal-back" });
  const box = el("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true" }, ...children);
  back.append(box);
  const close = () => { back.remove(); document.removeEventListener("keydown", esc, true); onClose?.(); };
  const esc = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } };
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
  document.addEventListener("keydown", esc, true);
  document.body.append(back);
  return { box, close };
}

function fileDialog({ title: heading, mode, defaultName = "", startDir, okLabel }) {
  return new Promise((resolve) => {
    let dir = startDir || S.cwd;
    let selected = null;
    let existing = new Set();
    const pathInput = el("input", { type: "text", "aria-label": "Folder" });
    const drives = el("select", { "aria-label": "Drive", hidden: true });
    const list = el("ul", { class: "files" });
    const nameInput = el("input", { type: "text", placeholder: "File name", value: defaultName, "aria-label": "File name" });
    const ok = el("button", { class: "btn primary", text: okLabel || (mode === "open" ? "Open" : "Save") });
    const cancel = el("button", { class: "btn", text: "Cancel" });
    const sub = el("div", { class: "sub", text: mode === "open"
      ? "Maxbook notebooks, or import wxMaxima (.wxm, .wxmx), Maxima (.mac), Markdown (.md) and LaTeX (.tex) files." : "" });
    const { close } = modal([el("header", { text: heading }), sub,
      el("div", { class: "crumbs" }, drives, pathInput, el("button", { class: "btn", text: "Up", onclick: () => load(dirname(dir)) })),
      list,
      el("footer", {}, mode === "open" ? el("span", { class: "grow" }) : el("div", { class: "grow" }, nameInput), cancel, ok)],
    { onClose: () => resolve(null) });
    const finish = (value) => { resolve(value); close(); };
    async function load(target) {
      try {
        const r = await get(`/api/fs?path=${encodeURIComponent(target || "")}`);
        dir = r.path;
        pathInput.value = dir;
        existing = new Set(r.entries.filter((ent) => !ent.dir).map((ent) => ent.path.toLowerCase()));
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
      } catch (e) { toast(e.message); }
    }
    pathInput.addEventListener("keydown", (e) => { if (e.key === "Enter") load(pathInput.value); });
    drives.addEventListener("change", () => load(drives.value));
    cancel.addEventListener("click", () => finish(null));
    ok.addEventListener("click", () => {
      if (mode === "open") { if (selected) finish(selected); else toast("Choose a file"); return; }
      const name = nameInput.value.trim();
      if (!name) { toast("Enter a file name"); return; }
      const target = /^([A-Za-z]:)?[\\/]/.test(name) ? name : joinPath(dir, name);
      // only files in the listed folder are known here; the server writes the rest
      if (existing.has(target.toLowerCase()) && target !== S.path
          && !confirm(`${name.split(/[\\/]/).pop()} already exists. Replace it?`)) return;
      finish(target);
    });
    nameInput.addEventListener("keydown", (e) => { if (e.key === "Enter") ok.click(); });
    load(dir);
    (mode === "open" ? pathInput : nameInput).focus();
  });
}

async function newNotebook() {
  if (!confirmDiscard()) return;
  const r = await post("/api/new", { title: "Untitled" });
  await mountDocument(docFromNotebook(r.notebook));
}

async function openPath(p) {
  if (!confirmDiscard()) return;
  try {
    const r = await post("/api/open", { path: p });
    await mountDocument(docFromNotebook(r.notebook), { path: r.path, suggested: r.suggested, note: r.note });
    if (r.path) { S.recent = [r.path, ...S.recent.filter((x) => x !== r.path)]; renderRecent(); }
    toast(`Opened ${p.split(/[\\/]/).pop()}`);
  } catch (e) { toast(e.message, 5000); }
}

async function openDialog() {
  const p = await fileDialog({ title: "Open notebook", mode: "open", startDir: S.path ? dirname(S.path) : S.cwd });
  if (p) openPath(p);
}

async function save(asNew = false) {
  if (!isHost()) return false;
  let p = S.path;
  if (!p || asNew) {
    const base = S.suggested || S.path || joinPath(S.cwd, `${slug(title())}.maxbook`);
    p = await fileDialog({ title: "Save notebook", mode: "save", defaultName: base.split(/[\\/]/).pop(), startDir: dirname(base) });
    if (!p) return false;
  }
  try {
    const r = await post("/api/save", { path: p, notebook: notebookJSON() });
    S.path = r.path;
    S.suggested = null;
    setDirty(false);
    S.recent = [r.path, ...S.recent.filter((x) => x !== r.path)];
    renderRecent();
    try { sessionStorage.setItem("maxbook-path", r.path); } catch { /* ignore */ }
    toast(`Saved ${r.path.split(/[\\/]/).pop()}`);
    return true;
  } catch (e) { toast(e.message, 5000); return false; }
}

const EXPORTS = [
  { fmt: "tex", ext: ".tex", t: "LaTeX document", d: "Compilable .tex with figures as PNG" },
  { fmt: "html", ext: ".html", t: "HTML page", d: "Single self-contained file, rendered math, works offline" },
  { fmt: "md", ext: ".md", t: "Markdown", d: "Text with $math$, ```maxima blocks and results" },
  { fmt: "mac", ext: ".mac", t: "Maxima batch file", d: "All computations in order; text as comments" },
  { fmt: "wxmx", ext: ".wxmx", t: "wxMaxima document", d: "Opens in wxMaxima (outputs are recomputed there)" },
  { fmt: "wxm", ext: ".wxm", t: "wxMaxima text file", d: "Plain-text wxMaxima format, good for version control" },
];

async function exportDialog() {
  const choice = await new Promise((resolve) => {
    let picked = null;
    const ul = el("ul", { class: "palette-list" }, ...EXPORTS.map((x) => el("li", { onclick: () => { picked = x; close(); } },
      el("div", {}, el("div", { text: x.t }), el("div", { class: "k", text: x.d })), el("span", { class: "k", text: x.ext }))));
    const { close } = modal([el("header", { text: "Export" }), ul], { onClose: () => resolve(picked) });
  });
  if (!choice) return;
  const base = (S.path || S.suggested || joinPath(S.cwd, slug(title()) + ".maxbook")).replace(/\.[^.\\/]+$/, "");
  const p = await fileDialog({ title: `Export as ${choice.t}`, mode: "save", defaultName: base.split(/[\\/]/).pop() + choice.ext,
    startDir: dirname(base), okLabel: "Export" });
  if (!p) return;
  try {
    const nb = notebookJSON();
    const body = { format: choice.fmt, path: p, notebook: nb };
    if (choice.fmt === "html") body.html = await buildHtmlExport(nb.doc, title());
    if (choice.fmt === "tex") body.figures = await rasterizeImages(nb.doc);
    const r = await post("/api/export", body);
    toast(`Exported ${r.written.length} file${r.written.length > 1 ? "s" : ""}: ${r.written[0].split(/[\\/]/).pop()}`, 4000);
  } catch (e) { toast(e.message, 6000); }
}

function renderRecent() {
  $("#recent").replaceChildren(...(S.recent.length ? S.recent.slice(0, 8).map((p) => el("a", {
    href: "#", text: p.split(/[\\/]/).pop(), title: p, onclick: (e) => { e.preventDefault(); openPath(p); },
  })) : [el("div", { class: "empty", text: "No recent notebooks" })]));
}

// ------------------------------------------------------------------ insertion & formatting
function run(cmd) {
  S.view.focus();
  return cmd(S.view.state, S.view.dispatch, S.view);
}

const FORMAT = {
  strong: () => run(toggleMark(schema.marks.strong)),
  em: () => run(toggleMark(schema.marks.em)),
  code: () => run(toggleMark(schema.marks.code)),
  h1: () => run(setBlockType(N.heading, { level: 1 })),
  h2: () => run(setBlockType(N.heading, { level: 2 })),
  h3: () => run(setBlockType(N.heading, { level: 3 })),
  p: () => run(setBlockType(N.paragraph)),
  ul: () => run(wrapInList(N.bullet_list)),
  ol: () => run(wrapInList(N.ordered_list)),
  quote: () => run(wrapIn(N.blockquote)),
  "inline-math": () => { if (!run((s, d) => insertInlineMath(s, d, ctx))) run((s, d) => insertMathBlock(s, d, ctx)); },
  "block-math": () => run((s, d) => insertMathBlock(s, d, ctx)),
  maxima: () => run((s, d) => insertMaxima(s, d, ctx)),
  objects: () => { $("#layout").classList.toggle("no-objects"); refreshObjects(); },
};

/** Insert Maxima code as a new block after the current position (and optionally run it). */
async function insertCode(code, runIt = false) {
  if (S.active && S.active.insert && S.active.editor) { S.active.insert(code); return; }
  const id = newId();
  S.view.focus();
  insertBlock(S.view.state, S.view.dispatch, N.maxima.create({ id, source: code.replace("|", "") }));
  if (runIt) await runNode(id);
}

function insertTemplate(item) {
  if (item.latex !== undefined) {
    if (S.active && !S.active.editor && S.active.insert) { S.active.insert(item.latex); return; }
    const id = newId();
    S.view.focus();
    const state = S.view.state;
    if (state.selection.$from.parent.inlineContent) {
      S.view.dispatch(state.tr.replaceSelectionWith(N.math_inline.create({ id }), false));
    } else {
      insertBlock(state, S.view.dispatch, N.math_block.create({ id }));
    }
    setTimeout(() => {
      const f = findById(id);
      const inst = f && ctx.instances.get(S.view.nodeDOM(f.pos));
      inst?.insert(item.latex);
    }, 30);
  } else {
    insertCode(item.code);
  }
}

// ------------------------------------------------------------------ menus (wxMaxima-style commands, AI)
function buildMenus() {
  const box = $("#menus");
  const menus = isHost() ? [...MENUS, aiMenu()] : [];
  box.replaceChildren(...menus.map((m) => {
    const btn = el("button", { class: "fb menu-btn", text: m.title + " ▾", "aria-haspopup": "true" });
    btn.addEventListener("click", (e) => { e.stopPropagation(); openMenu(btn, m); });
    return btn;
  }));
}

function openMenu(anchor, menu) {
  document.querySelector(".menu-pop")?.remove();
  const pop = el("div", { class: "menu-pop", role: "menu" }, ...menu.items.map((it) => el("button", {
    class: "menu-item" + (it.disabled ? " disabled" : ""), role: "menuitem", text: it.t, title: it.hint || "",
    onclick: () => { pop.remove(); if (!it.disabled) (it.action ? it.action() : commandDialog(it)); },
  })));
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.left = Math.min(window.innerWidth - pop.offsetWidth - 8, r.left) + "px";
  pop.style.top = r.bottom + 4 + "px";
  setTimeout(() => document.addEventListener("click", () => pop.remove(), { once: true }), 0);
}

function commandDialog(item) {
  const form = dialogForm(item, el);
  const insert = el("button", { class: "btn", text: "Insert" });
  const insertRun = el("button", { class: "btn primary", text: "Insert and run" });
  const { close } = modal([el("header", { text: item.t }),
    el("div", { class: "sub", text: "Use % for the last result. The code is inserted as a Maxima block you can edit." }),
    form.node, el("footer", {}, el("span", { class: "grow" }), insert, insertRun)]);
  const go = (runIt) => {
    const code = form.value();
    if (!code) { toast("Fill in the required fields"); return; }
    close();
    insertCode(code, runIt);
  };
  insert.addEventListener("click", () => go(false));
  insertRun.addEventListener("click", () => go(true));
  form.node.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(true); } });
  setTimeout(() => form.first().select(), 20);
}

// -- AI helper --------------------------------------------------------------
function aiMenu() {
  const off = !S.ai.enabled;
  const hint = off ? `AI helper is off: ${S.ai.reason || "not configured"}` : `Uses ${S.ai.model}; sends the selection to Anthropic`;
  const item = (t, action) => ({ t, action, disabled: off, hint });
  return { title: "AI", items: [
    item("Explain the selection", () => aiTask("explain")),
    item("Show the steps", () => aiTask("steps")),
    item("Simplify and check", () => aiTask("simplify")),
    item("Write Maxima code…", () => aiPrompt("maxima", "Describe what the code should do")),
    item("Ask a question…", () => aiPrompt("ask", "Your question about this notebook")),
    item("Transcribe an image of math…", () => aiImage()),
  ] };
}

function aiConsent() {
  let ok = false;
  try { ok = localStorage.getItem("maxbook-ai-consent") === "yes"; } catch { /* ignore */ }
  if (ok) return true;
  ok = confirm(`The AI helper sends the selected content (and, for questions, nearby Maxima definitions) to Anthropic's API (model ${S.ai.model}). Continue?`);
  if (ok) try { localStorage.setItem("maxbook-ai-consent", "yes"); } catch { /* ignore */ }
  return ok;
}

function selectionContent() {
  const { state } = S.view;
  const sel = state.selection;
  const toText = (frag) => {
    let s = "";
    frag.descendants((n) => {
      if (n.isText) s += n.text;
      else if (n.type === N.math_inline) s += `$${n.attrs.latex}$`;
      else if (n.type === N.math_block) s += `\n$$${n.attrs.latex}$$\n`;
      else if (n.type === N.maxima) s += `\n\`\`\`maxima\n${n.attrs.source}\n\`\`\`\n`;
      else if (n.isBlock && s && !s.endsWith("\n")) s += "\n";
      return true;
    });
    return s.trim();
  };
  if (sel instanceof NodeSelection) return toText(Fragment.from(sel.node));
  if (!sel.empty) return toText(state.doc.slice(sel.from, sel.to).content);
  if (S.active) return toText(Fragment.from(S.active.node));
  return toText(Fragment.from(sel.$from.node(Math.min(1, sel.$from.depth))));
}

function insertMarkdownAfterSelection(markdown) {
  const nodes = markdownToNodes(markdown);
  const state = S.view.state;
  const $to = state.selection.$to;
  const pos = $to.depth >= 1 ? $to.after(1) : state.doc.content.size;
  S.view.dispatch(state.tr.insert(pos, Fragment.from(nodes)).scrollIntoView());
}

async function withBusyToast(label, fn) {
  toast(label, 60000);
  try { await fn(); } catch (e) { toast(e.message, 6000); return; }
  toast("Inserted below — undo with Ctrl+Z");
}

async function aiTask(task, content = null) {
  if (!aiConsent()) return;
  const text = content ?? selectionContent();
  if (!text) { toast("Select some text or a formula first"); return; }
  await withBusyToast("Asking the AI helper…", async () => {
    const r = await post("/api/ai/ask", { task, content: text, context: knownSources().join("\n").slice(-6000) });
    insertMarkdownAfterSelection(r.markdown);
  });
}

function aiPrompt(task, placeholder) {
  const input = el("textarea", { class: "ai-input", rows: "4", placeholder });
  const ok = el("button", { class: "btn primary", text: "Ask" });
  const { close } = modal([el("header", { text: task === "maxima" ? "Write Maxima code" : "Ask the AI helper" }),
    el("div", { class: "sub", text: `Sent to Anthropic (${S.ai.model}). The answer is inserted into the notebook.` }),
    el("div", { class: "pad" }, input), el("footer", {}, el("span", { class: "grow" }), ok)]);
  ok.addEventListener("click", () => { const v = input.value.trim(); if (!v) return; close(); aiTask(task, v); });
  setTimeout(() => input.focus(), 20);
}

function aiImage() {
  if (!aiConsent()) return;
  const input = el("input", { type: "file", accept: "image/png,image/jpeg,image/gif,image/webp" });
  input.addEventListener("change", () => {
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => withBusyToast("Transcribing the image…", async () => {
      const r = await post("/api/ai/image", { image: reader.result });
      insertMarkdownAfterSelection(r.markdown);
    });
    reader.readAsDataURL(file);
  });
  input.click();
}

// ------------------------------------------------------------------ palette
const COMMANDS = [
  { t: "Run everything", k: "run all execute compute", run: () => runAll(), key: "Ctrl+Shift+Enter", host: true },
  { t: "Stop computation", k: "interrupt stop abort", run: () => interrupt(), host: true },
  { t: "Restart Maxima", k: "restart kernel reset", run: () => restart(), host: true },
  { t: "New notebook", k: "new", run: () => newNotebook(), key: "Ctrl+Alt+N", host: true },
  { t: "Open…", k: "open import wxm wxmx tex latex", run: () => openDialog(), key: "Ctrl+O", host: true },
  { t: "Save", k: "save", run: () => save(), key: "Ctrl+S", host: true },
  { t: "Save as…", k: "save as", run: () => save(true), key: "Ctrl+Shift+S", host: true },
  { t: "Export…", k: "export latex html markdown wxm wxmx mac pdf", run: () => exportDialog(), host: true },
  { t: "Insert formula in the text", k: "inline math formula $", run: () => FORMAT["inline-math"](), key: "Ctrl+M" },
  { t: "Insert display formula", k: "display math equation block", run: () => FORMAT["block-math"](), key: "Ctrl+Shift+M" },
  { t: "Insert Maxima block", k: "code maxima block input", run: () => FORMAT.maxima(), key: "Ctrl+Alt+M" },
  { t: "Edit together (share)", k: "share collaborate network", run: () => shareDialog(), host: true },
  { t: "Toggle outline", k: "outline sidebar", run: () => $("#layout").classList.toggle("no-side") },
  { t: "Toggle symbols panel", k: "objects symbols variables panel", run: () => FORMAT.objects() },
  { t: "Toggle symbol colours", k: "colour color symbols semantic", run: () => toggleColours() },
  { t: "Toggle light/dark", k: "theme dark light", run: () => toggleTheme() },
  { t: "Print / save as PDF", k: "print pdf", run: () => window.print() },
  { t: "Keyboard and tips", k: "help keys", run: () => showHelp(), key: "F1" },
  { t: "Quit Maxbook", k: "quit exit close", run: () => quit(), host: true },
];

function openPalette() {
  const prefer = S.active?.editor ? CODE_TEMPLATES : MATH_TEMPLATES;
  const other = prefer === CODE_TEMPLATES ? MATH_TEMPLATES : CODE_TEMPLATES;
  const input = el("input", { class: "palette-input", type: "text", placeholder: "Search commands and templates…", "aria-label": "Search" });
  const ul = el("ul", { class: "palette-list" });
  let items = [];
  let sel = 0;
  const { close } = modal([input, ul]);
  const pick = (it) => { close(); if (it.run) it.run(); else insertTemplate(it); };
  const commandsVisible = COMMANDS.filter((c) => !c.host || isHost());
  const render = () => {
    const q = input.value;
    const cmds = searchTemplates(commandsVisible, q).map((x) => ({ ...x, grp: "Command" }));
    const t1 = searchTemplates(prefer, q).map((x) => ({ ...x, grp: x.latex !== undefined ? "Math" : "Maxima" }));
    const t2 = q ? searchTemplates(other, q).map((x) => ({ ...x, grp: x.latex !== undefined ? "Math" : "Maxima" })) : [];
    const dlg = q && isHost() ? MENUS.flatMap((m) => searchTemplates(m.items.map((i) => ({ ...i, k: m.title.toLowerCase() })), q)
      .map((i) => ({ t: `${i.t}…`, k: i.k, run: () => commandDialog(i), grp: i.k }))) : [];
    items = [...cmds, ...dlg, ...t1, ...t2].slice(0, 60);
    sel = Math.min(sel, Math.max(0, items.length - 1));
    ul.replaceChildren(...items.map((it, i) => el("li", { class: i === sel ? "sel" : "", onclick: () => pick(it) },
      el("div", {}, el("div", { text: it.t }), it.latex ? el("div", { class: "k", html: renderMath(it.latex.replace(/#[0?]/g, "\\placeholder{}")) })
        : it.code ? el("div", { class: "k", text: it.code.replace("|", "…") }) : null),
      el("span", { class: "grp", text: it.key || it.grp }))));
  };
  input.addEventListener("input", () => { sel = 0; render(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); render(); ul.children[sel]?.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); render(); ul.children[sel]?.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[sel]) pick(items[sel]); }
  });
  render();
  input.focus();
}

// ------------------------------------------------------------------ sharing & presence
function localName() {
  try { return localStorage.getItem("maxbook-name") || (isHost() ? "Host" : "Guest"); } catch { return "Guest"; }
}
function localColour() {
  const colours = ["#3b5bdb", "#0c8599", "#2f9e44", "#e8590c", "#ae3ec9", "#c2255c"];
  return colours[Math.floor(Math.random() * colours.length)];
}

function renderUsers(users) {
  $("#users").replaceChildren(...users.slice(0, 6).map((u) => el("span", {
    class: "avatar", style: `background:${u.color || "#888"}`, title: `${u.name} (${u.role})`,
    text: (u.name || "?").slice(0, 1).toUpperCase(),
  })));
}

function shareDialog() {
  const urls = S.share.urls || [];
  const body = S.share.enabled
    ? el("div", { class: "pad" },
      el("p", { text: "Anyone on your network with this link can read and edit this notebook with you. They cannot run Maxima, open or save files." }),
      ...urls.map((u) => el("div", { class: "share-row" }, el("code", { text: u }),
        el("button", { class: "btn", text: "Copy", onclick: () => ctx.copy(u, "link") }))),
      urls.length ? null : el("p", { text: "No network address was found." }))
    : el("div", { class: "pad" },
      el("p", { text: "Sharing is off. Start Maxbook with --share to edit a notebook together with others on your network:" }),
      el("pre", { class: "dlg-preview", text: "python -m maxbook --share notebook.maxbook" }),
      el("p", { text: "Other windows on this computer already stay in sync — open the same address twice." }));
  modal([el("header", { text: "Edit together" }), body]);
}

// ------------------------------------------------------------------ misc ui
function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("maxbook-theme", root.dataset.theme); } catch { /* ignore */ }
}

function toggleColours() {
  document.body.classList.toggle("plain-symbols");
  try { localStorage.setItem("maxbook-plain-symbols", document.body.classList.contains("plain-symbols") ? "1" : ""); } catch { /* ignore */ }
}

function showHelp() {
  const rows = [
    ["$", "Formula in the text; type $ again in an empty formula for a display formula"],
    ["= then Tab", "Compute in place: the result appears right after the formula"],
    [":= then Tab", "Define a variable or function in Maxima (a := 3, f(x) := x^2)"],
    [">> and space", "Maxima block (also ``` and space, or Ctrl+Alt+M)"],
    ["Shift+Enter", "Run a Maxima block or evaluate a display formula, then move on"],
    ["Alt+Enter", "Run and insert a new Maxima block below"],
    ["Ctrl+Shift+Enter", "Run everything in order"],
    ["# and space", "Heading (##, ### for smaller); - or 1. for lists; > for a quote"],
    ["In a formula: a word", "int, frac, sum, matrix, lim, sqrt… then Enter or Tab"],
    ["Ctrl+K", "Search commands, dialogs and templates"],
    ["Ctrl+S / Ctrl+O", "Save / open or import"],
    ["Hover a symbol", "See what Maxima knows about it; describe it in the Objects panel"],
    ["Menus", "Equations, Algebra, Calculus, Matrix, Plot: forms that write Maxima code"],
  ];
  modal([el("header", { text: "Keyboard and tips" }),
    el("div", { class: "sub" }, el("table", { class: "kbd-help" }, ...rows.map(([k, d]) => el("tr", {}, el("td", { text: k }), el("td", { text: d })))))]);
}

async function quit() {
  if (S.dirty && !confirm("Quit without saving?")) return;
  S.collab?.stop();
  try { await post("/api/shutdown"); } catch { /* already gone */ }
  document.body.replaceChildren(el("div", { class: "banner", text: "Maxbook has stopped. You can close this window." }));
}

function bindChrome() {
  const cmds = { new: newNotebook, open: openDialog, save: () => save(), export: exportDialog, "run-all": runAll,
                 interrupt, restart, palette: openPalette, theme: toggleTheme, help: showHelp, share: shareDialog };
  document.querySelectorAll("[data-cmd]").forEach((b) => b.addEventListener("click", () => cmds[b.dataset.cmd]()));
  document.querySelectorAll("[data-fmt]").forEach((b) => {
    b.addEventListener("mousedown", (e) => e.preventDefault());
    b.addEventListener("click", () => FORMAT[b.dataset.fmt]());
  });
  $("#title").addEventListener("change", (e) => setDocAttr("title", e.target.value.trim() || "Untitled"));
  $("#title").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.target.blur(); S.view.focus(); } });
  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key.toLowerCase();
    if (mod && k === "s") { e.preventDefault(); save(e.shiftKey); }
    else if (mod && k === "o") { e.preventDefault(); if (isHost()) openDialog(); }
    else if (mod && k === "k") { e.preventDefault(); openPalette(); }
    else if (mod && e.altKey && k === "n") { e.preventDefault(); if (isHost()) newNotebook(); }
    else if (mod && e.shiftKey && e.key === "Enter") { e.preventDefault(); runAll(); }
    else if (e.key === "F1") { e.preventDefault(); showHelp(); }
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty && isHost()) { e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("pagehide", () => S.collab?.stop());
  // Pasting a LaTeX document or fragment: convert it on the server, insert as document content.
  $("#editor").addEventListener("paste", async (e) => {
    const text = e.clipboardData?.getData("text/plain") || "";
    if (!/\\(begin\{(document|equation|align|itemize)|section\{|subsection\{)/.test(text)) return;
    e.preventDefault();
    e.stopPropagation();
    try {
      const cells = await post("/api/convert-latex", { text });
      const doc = cellsToDoc(cells);
      const state = S.view.state;
      S.view.dispatch(state.tr.replaceSelection(new Slice(doc.content, 0, 0)).scrollIntoView());
      toast("Pasted LaTeX as document content");
    } catch (err) { toast(err.message); }
  }, true);
}

// ------------------------------------------------------------------ boot
async function boot() {
  try {
    const t = localStorage.getItem("maxbook-theme");
    if (t) document.documentElement.dataset.theme = t;
    if (localStorage.getItem("maxbook-plain-symbols")) document.body.classList.add("plain-symbols");
  } catch { /* storage unavailable */ }
  if (!initToken()) {
    banner("This page needs the link printed by Maxbook (it carries a session key). Start it with: python -m maxbook", "err");
    return;
  }
  bindChrome();
  installHover($("#editor"), registry);
  installHover($("#objects"), registry);
  let session;
  try {
    session = await get("/api/session");
  } catch (e) {
    banner(e instanceof ApiError && e.status === 403
      ? "Session key rejected — open the link printed by the current Maxbook process." : e.message, "err");
    return;
  }
  S.role = session.role || "host";
  S.kernel = session.kernel;
  S.ai = session.ai || { enabled: false };
  S.share = session.share || { enabled: false };
  renderKernel();
  document.body.classList.toggle("guest", !isHost());
  $("#role").hidden = isHost();
  $("#share-btn").hidden = !isHost();
  buildMenus();
  if (!isHost()) {
    try {
      const name = localStorage.getItem("maxbook-name") || prompt("Your name (shown to others editing this notebook):", "");
      if (name) localStorage.setItem("maxbook-name", name);
    } catch { /* ignore */ }
  }
  S.collab = makeCollab();
  // Another window (or a reload of this one) may already be editing a
  // document: join it rather than replacing it, unless a file was named on
  // the command line.
  const shared = session.initial ? null : await S.collab.join().catch(() => null);
  if (shared) {
    await mountDocument(shared.doc, { path: shared.path, publish: false, version: shared.version,
      note: isHost() ? "" : "You are editing as a guest. Only the host can run Maxima and save." });
  }
  if (isHost()) {
    S.recent = session.recent || [];
    S.cwd = session.cwd;
    renderRecent();
    let reopen = "";
    try { reopen = sessionStorage.getItem("maxbook-path") || ""; } catch { /* ignore */ }
    if (shared) {
      // joined above
    } else if (!session.initial && reopen) {
      try {
        const r = await post("/api/open", { path: reopen });
        await mountDocument(docFromNotebook(r.notebook), { path: r.path, note: r.note });
      } catch {
        await mountDocument(docFromNotebook(session.notebook), { path: session.path, note: session.note });
      }
    } else {
      await mountDocument(docFromNotebook(session.notebook),
        { path: session.path, suggested: session.suggested, note: session.note });
    }
    if (S.kernel.status === "missing") banner(S.kernel.error, "err");
  } else if (!shared) {
    banner("The host has not opened a notebook yet. Reload in a moment.", "err");
    return;
  }
  registry.refresh();
  setInterval(() => { if (!S.busy) pollKernel(); }, 2500);
}

boot();
