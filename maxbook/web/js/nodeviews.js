// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Interactive nodes inside the document: Maxima blocks, display formulas and
// inline formulas.  They keep their own editors (a code textarea or a
// MathLive field) and write changes back to the document as attribute steps.

import { MathfieldElement } from "../vendor/mathlive/mathlive.min.mjs";
import { state as pmState } from "../vendor/prosemirror/prosemirror.mjs";
import { highlightMaxima } from "./highlight.js";
import { renderMath, tagLatex, stripClasses, ensureSymbolColours } from "./mathrender.js";

const { Selection, NodeSelection } = pmState;
MathfieldElement.soundsDirectory = null;

export function el(tag, attrs = {}, ...children) {
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

const icon = (path) => {
  const s = document.createElement("span");
  s.innerHTML = `<svg viewBox="0 0 24 24">${path}</svg>`;
  return s.firstChild;
};

// ------------------------------------------------------------ helpers
function setAttrs(view, getPos, attrs, history = false) {
  const pos = getPos();
  if (pos == null) return;
  const tr = view.state.tr;
  for (const [k, v] of Object.entries(attrs)) tr.setNodeAttribute(pos, k, v);
  if (!history) tr.setMeta("addToHistory", false);
  view.dispatch(tr);
}

/** Put the text cursor just before (dir < 0) or after (dir > 0) the node. */
export function exitNode(view, getPos, dir) {
  const pos = getPos();
  if (pos == null) return;
  const node = view.state.doc.nodeAt(pos);
  const target = dir < 0 ? pos : pos + (node ? node.nodeSize : 1);
  const $pos = view.state.doc.resolve(target);
  // Prefer a text position; fall back to whatever is next (a gap cursor or a node).
  const sel = Selection.findFrom($pos, dir, true) || Selection.near($pos, dir);
  view.dispatch(view.state.tr.setSelection(sel).scrollIntoView());
  view.focus();
}

function selectSelf(view, getPos) {
  const pos = getPos();
  if (pos == null) return;
  view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc, pos)));
  view.focus();
}

function deleteSelf(view, getPos) {
  const pos = getPos();
  if (pos == null) return;
  const node = view.state.doc.nodeAt(pos);
  if (!node) return;
  view.dispatch(view.state.tr.delete(pos, pos + node.nodeSize));
  view.focus();
}

function inLabel(inputs) {
  if (!inputs || !inputs.length) return "";
  return inputs.length === 1 ? `(%i${inputs[0]})` : `(%i${inputs[0]}–${inputs[inputs.length - 1]})`;
}

// ------------------------------------------------------------ outputs
export function renderOutputs(box, outputs, ctx, { running = false } = {}) {
  box.replaceChildren();
  (outputs || []).forEach((o, i) => {
    if (o.kind === "result") {
      const math = el("div", { class: "out-math" });
      if (o.latex) math.innerHTML = renderMath(o.semantic || o.latex, true);
      else math.textContent = o.text;
      box.append(el("div", { class: "out out-result" },
        o.label ? el("span", { class: "out-label", text: `(${o.label})` }) : null,
        math,
        el("div", { class: "out-actions" },
          el("button", { text: "LaTeX", title: "Copy as LaTeX", onclick: () => ctx.copy(stripClasses(o.latex), "LaTeX") }),
          el("button", { text: "Maxima", title: "Copy as Maxima input", onclick: () => ctx.copy(o.text, "Maxima expression") }))));
    } else if (o.kind === "text") {
      box.append(el("pre", { class: "out out-text", text: o.text }));
    } else if (o.kind === "error") {
      box.append(el("pre", { class: "out " + (o.interrupted ? "out-interrupted" : "out-error"), text: o.text }));
    } else if (o.kind === "image") {
      const src = o.mime === "image/svg+xml"
        ? "data:image/svg+xml;charset=utf-8," + encodeURIComponent(o.data)
        : `data:${o.mime};base64,${o.data}`;
      box.append(el("div", { class: "out out-image" }, el("img", { src, alt: "plot", loading: "lazy" })));
    } else if (o.kind === "question") {
      box.append(questionCard(o, i < outputs.length - 1 || !running, ctx));
    }
  });
  ensureSymbolColours(box);
}

function questionCard(q, answered, ctx) {
  const text = el("div", { class: "q" });
  if (q.parts && q.parts.length) text.innerHTML = q.parts.map((p) => renderMath(p.latex || p.text)).join(" ");
  else text.textContent = q.text;
  const card = el("div", { class: "out out-question" }, text);
  if (answered || !ctx.isHost) return card;
  const input = el("input", { type: "text", placeholder: "Your answer, e.g. positive", "aria-label": "Answer" });
  const send = (t) => { if (t.trim()) ctx.answer(t); };
  const full = (q.text + " " + (q.parts || []).map((p) => p.text).join(" ")).toLowerCase();
  const quick = /positive|negative/.test(full) ? ["positive", "negative", "zero"] : /\?/.test(full) ? ["yes", "no"] : [];
  card.append(el("form", { onsubmit: (e) => { e.preventDefault(); send(input.value); } }, input,
    ...quick.map((a) => el("button", { type: "button", text: a, onclick: () => send(a) })),
    el("button", { type: "submit", class: "primary", text: "Answer" })));
  setTimeout(() => input.focus(), 30);
  return card;
}

// ------------------------------------------------------------ code editor
export function codeEditor(initial, { onChange, onKey, placeholder }) {
  const pre = el("pre", { "aria-hidden": "true" });
  const ta = el("textarea", { spellcheck: "false", autocapitalize: "off", autocomplete: "off",
                              placeholder, rows: "1", "aria-label": "Maxima input" });
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
  return {
    box: el("div", { class: "code-editor" }, pre, ta), ta, paint,
    setValue(v) { ta.value = v; paint(); },
    insert(text) {
      const caret = text.indexOf("|");
      const clean = text.replace("|", "");
      const { selectionStart: s, selectionEnd: t, value } = ta;
      ta.value = value.slice(0, s) + clean + value.slice(t);
      ta.focus();
      ta.selectionStart = ta.selectionEnd = s + (caret >= 0 ? caret : clean.length);
      paint();
      onChange(ta.value);
    },
  };
}

// ------------------------------------------------------------ block chrome
function blockChrome(kind, ctx, node, getPos, view, body, extraTools = []) {
  const label = el("span", { class: "in-label" });
  const run = ctx.isHost ? el("button", {
    class: "run", title: "Run (Shift+Enter)", html: '<svg viewBox="0 0 24 24"><path d="M7 4l13 8-13 8z"/></svg>',
    onmousedown: (e) => e.preventDefault(),
    onclick: () => ctx.runNode(node.attrs.id),
  }) : null;
  const gutter = el("div", { class: "gutter", contenteditable: "false", title: "Drag to move; click to select" },
    label, run);
  const tools = el("div", { class: "cell-tools", contenteditable: "false" }, ...extraTools,
    el("button", { title: "Delete block", onclick: () => deleteSelf(view, getPos) },
      icon('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>')));
  const dom = el("section", { class: `mbk-block mbk-${kind}`, "data-id": node.attrs.id || "" }, gutter, body, tools);
  gutter.addEventListener("mousedown", (e) => {
    if (e.target.closest("button")) return;
    e.preventDefault();
    selectSelf(view, getPos);
  });
  return { dom, label, gutter, tools };
}

// ------------------------------------------------------------ Maxima block
export class MaximaView {
  constructor(node, view, getPos, ctx) {
    Object.assign(this, { node, view, getPos, ctx });
    this.outputs = el("div", { class: "outputs" });
    this.editor = codeEditor(node.attrs.source, {
      placeholder: "Maxima input, e.g. integrate(sin(x)^2, x);",
      onChange: (v) => setAttrs(view, getPos, { source: v }),
      onKey: (e) => this.key(e),
    });
    this.editor.ta.addEventListener("focus", () => ctx.setActive(this));
    this.editor.ta.addEventListener("blur", () => ctx.clearActive(this));
    const body = el("div", { class: "body" }, this.editor.box, this.outputs);
    const toMath = el("button", { title: "Copy into a formula block (keeps this block)", text: "∑",
      onclick: () => ctx.insertFormulaAfter(getPos()) });
    Object.assign(this, blockChrome("maxima", ctx, node, getPos, view, body, [toMath]));
    this.refresh(null);
    if (ctx.consumeAutoEdit(node.attrs.id)) requestAnimationFrame(() => this.focus());
  }

  key(e) {
    const ta = this.editor.ta;
    if (e.key === "Enter" && (e.shiftKey || e.ctrlKey || e.altKey) && !(e.shiftKey && e.ctrlKey)) {
      e.preventDefault();
      this.ctx.runNode(this.node.attrs.id, { advance: e.shiftKey, insertAfter: e.altKey, from: this.getPos });
      return true;
    }
    if (e.key === "Escape") { e.preventDefault(); selectSelf(this.view, this.getPos); return true; }
    const atStart = ta.selectionStart === 0 && ta.selectionEnd === 0;
    const atEnd = ta.selectionStart === ta.value.length;
    if ((e.key === "ArrowUp" && !ta.value.slice(0, ta.selectionStart).includes("\n")) || (e.key === "ArrowLeft" && atStart)) {
      e.preventDefault(); exitNode(this.view, this.getPos, -1); return true;
    }
    if ((e.key === "ArrowDown" && !ta.value.slice(ta.selectionEnd).includes("\n")) || (e.key === "ArrowRight" && atEnd)) {
      e.preventDefault(); exitNode(this.view, this.getPos, 1); return true;
    }
    if (e.key === "Backspace" && ta.value === "") { e.preventDefault(); deleteSelf(this.view, this.getPos); return true; }
    return false;
  }

  refresh(old) {
    const a = this.node.attrs;
    if (a.source !== this.editor.ta.value && document.activeElement !== this.editor.ta) this.editor.setValue(a.source);
    const running = this.ctx.isRunning(a.id);
    this.dom.classList.toggle("running", running);
    this.label.textContent = running ? "[*]" : inLabel(a.inputs);
    if (!old || old.attrs.outputs !== a.outputs || running !== this._running) {
      renderOutputs(this.outputs, a.outputs, this.ctx, { running });
    }
    this._running = running;
    this.dom.dataset.id = a.id || "";
  }

  update(node) {
    if (node.type !== this.node.type) return false;
    const old = this.node;
    this.node = node;
    this.refresh(old);
    return true;
  }

  focus() { this.editor.ta.focus(); }
  insert(text) { this.editor.insert(text); }
  selectNode() { this.dom.classList.add("selected"); }
  deselectNode() { this.dom.classList.remove("selected"); }
  stopEvent(e) {
    if (e.type.startsWith("drag") || e.type === "drop") return false;
    if (this.gutter.contains(e.target)) return e.type !== "mousedown";
    return this.dom.contains(e.target);
  }
  ignoreMutation() { return true; }
}

// ------------------------------------------------------------ formulas
/** Shared editing behaviour of inline and display formulas. */
class FormulaBase {
  init(node, view, getPos, ctx) {
    Object.assign(this, { node, view, getPos, ctx });
    this.mf = null;
  }

  staticHTML() {
    const a = this.node.attrs;
    const tagged = tagLatex(a.latex, (n) => this.ctx.kindOf(n));
    let html = a.latex ? renderMath(tagged, this.display) : "";
    const r = a.result;
    if (r && r.error) {
      html += `<span class="mbk-result mbk-result-error" title="${escapeAttr(r.error)}">⚠</span>`;
    } else if (r && (r.semantic || r.latex) && /=\s*$/.test(a.latex)) {
      html += `<span class="mbk-result">${renderMath(r.semantic || r.latex, this.display)}</span>`;
    } else if (r && r.text === "defined") {
      html += `<span class="mbk-result mbk-defined" title="Defined in Maxima">✓</span>`;
    }
    return html || `<span class="mbk-empty-math">${this.display ? "empty formula — click to write" : "∎"}</span>`;
  }

  startEdit() {
    if (this.mf) { this.mf.focus(); return; }
    const mf = new MathfieldElement();
    mf.setAttribute("math-virtual-keyboard-policy", "manual");
    mf.smartFence = true;
    // MathLive leaves an exponent after its first digit by default, so typing
    // 2^10 would give 2¹·0.  Exponents end with → or a non-digit instead.
    mf.smartSuperscript = false;
    mf.value = this.node.attrs.latex || "";
    this.mf = mf;
    this.mountEditor(mf);
    mf.addEventListener("input", () => {
      setAttrs(this.view, this.getPos, { latex: mf.value, result: null });
      this.ctx.mathSearch.onInput(mf);
      this.onLatexChanged?.(mf.value);
    });
    mf.addEventListener("keydown", (e) => this.key(e), { capture: true });
    mf.addEventListener("move-out", (e) => {
      const dir = e.detail?.direction;
      if (dir === "backward" || dir === "upward") { e.preventDefault(); this.stopEdit(); exitNode(this.view, this.getPos, -1); }
      if (dir === "forward" || dir === "downward") { e.preventDefault(); this.stopEdit(); exitNode(this.view, this.getPos, 1); }
    });
    mf.addEventListener("focusout", () => setTimeout(() => {
      if (this.mf && !this.mf.hasFocus?.() && document.activeElement !== this.mf) this.stopEdit();
    }, 0));
    this.ctx.mathSearch.reset();
    this.ctx.setActive(this);
    // ProseMirror may take the focus back while it finishes the transaction
    // that created this node, so focus again once it has settled.
    const focus = () => { if (this.mf === mf && document.activeElement !== mf) mf.focus(); };
    requestAnimationFrame(focus);
    setTimeout(focus, 80);
    this.dom.classList.add("editing");
  }

  stopEdit() {
    if (!this.mf) return;
    const latex = this.mf.value;
    this.ctx.mathSearch.close();
    this.ctx.clearActive(this);
    this.mf.remove();
    this.mf = null;
    this.dom.classList.remove("editing");
    this.unmountEditor();
    if (!latex.trim() && !this.keepEmpty) deleteSelf(this.view, this.getPos);
    else this.render();
  }

  key(e) {
    if (this.ctx.mathSearch.onKey(e, this.mf)) return;
    if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      e.stopPropagation();
      const latex = this.mf.value;
      if (/=\s*$/.test(latex) || /\\coloneq|:=/.test(latex)) {
        if (!this.ctx.isHost) { this.ctx.toast("Only the host can compute"); return; }
        this.ctx.computeInPlace(this.node.attrs.id).then((ok) => {
          if (!ok || !this.mf) return;
          this.stopEdit();
          exitNode(this.view, this.getPos, 1);
        });
      } else {
        this.stopEdit();
        exitNode(this.view, this.getPos, 1);
      }
      return;
    }
    if (e.key === "Escape" || (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !this.display)) {
      e.preventDefault();
      e.stopPropagation();
      this.stopEdit();
      exitNode(this.view, this.getPos, 1);
      return;
    }
    this.extraKey?.(e);
  }

  update(node) {
    if (node.type !== this.node.type) return false;
    const old = this.node;
    this.node = node;
    if (this.mf) {
      if (node.attrs.latex !== this.mf.value && !this.mf.hasFocus?.()) this.mf.value = node.attrs.latex;
      if (old.attrs.result !== node.attrs.result) this.renderResultWhileEditing?.();
    } else if (old.attrs.latex !== node.attrs.latex || old.attrs.result !== node.attrs.result) {
      this.render();
    }
    this.updateExtra?.(old);
    return true;
  }

  insert(latex) {
    if (!this.mf) this.startEdit();
    requestAnimationFrame(() => {
      this.mf.focus();
      this.mf.insert(latex, { selectionMode: "placeholder", format: "latex" });
      this.mf.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  focus() { this.startEdit(); }
  ignoreMutation() { return true; }
  destroy() { this.ctx.mathSearch.close(); }
}

const escapeAttr = (s) => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

export class MathInlineView extends FormulaBase {
  constructor(node, view, getPos, ctx) {
    super();
    this.init(node, view, getPos, ctx);
    this.display = false;
    this.dom = el("span", { class: "mbk-math-inline" });
    this.view_ = el("span", { class: "math-static" });
    this.dom.append(this.view_);
    this.dom.addEventListener("mousedown", (e) => {
      if (this.mf) return;
      e.preventDefault();
      this.startEdit();
    });
    this.render();
    if (!node.attrs.latex && ctx.consumeAutoEdit(node.attrs.id)) setTimeout(() => this.startEdit(), 0);
  }
  render() {
    this.view_.innerHTML = this.staticHTML();
    ensureSymbolColours(this.view_);
  }
  mountEditor(mf) { this.view_.hidden = true; this.dom.append(mf); }
  unmountEditor() { this.view_.hidden = false; }
  extraKey(e) {
    // "$" in an empty inline formula that is alone in its paragraph: make it a display formula
    if (e.key === "$" && !this.mf.value) {
      e.preventDefault();
      this.ctx.promoteToBlock(this.getPos());
    }
  }
  selectNode() { this.dom.classList.add("selected"); }
  deselectNode() { this.dom.classList.remove("selected"); }
  stopEvent(e) { return Boolean(this.mf) && this.dom.contains(e.target); }
}

export class MathBlockView extends FormulaBase {
  constructor(node, view, getPos, ctx) {
    super();
    this.init(node, view, getPos, ctx);
    this.display = true;
    this.keepEmpty = false;
    this.static_ = el("div", { class: "math-static math-display-view", title: "Click to edit" });
    this.host = el("div", { class: "math-box" });
    this.line = el("div", { class: "math-maxima" });
    this.outputs = el("div", { class: "outputs" });
    this.static_.addEventListener("mousedown", (e) => { e.preventDefault(); this.startEdit(); });
    const body = el("div", { class: "body" }, this.static_, this.host, this.line, this.outputs);
    this.evalBtn = el("button", { title: "Evaluate this formula with Maxima when running the notebook",
      onclick: () => {
        setAttrs(view, getPos, { run: !this.node.attrs.run }, true);
      } });
    Object.assign(this, blockChrome("mathblock", ctx, node, getPos, view, body, [this.evalBtn]));
    this.host.hidden = true;
    this.render();
    this.updateExtra(null);
    if (!node.attrs.latex && ctx.consumeAutoEdit(node.attrs.id)) setTimeout(() => this.startEdit(), 0);
  }
  render() {
    this.static_.innerHTML = this.staticHTML();
    ensureSymbolColours(this.static_);
  }
  mountEditor(mf) {
    this.static_.hidden = true;
    this.host.hidden = false;
    this.host.append(mf);
    this.showLine(this.node.attrs.source || "", false);
    this.onLatexChanged(mf.value);
  }
  unmountEditor() {
    this.host.hidden = true;
    this.static_.hidden = false;
    this.updateExtra(null);
  }
  showLine(text, err, tag = "Maxima") {
    this.line.classList.toggle("err", !!err);
    this.line.replaceChildren(el("span", { class: "tag", text: err ? "⚠" : tag }), el("span", { text }));
    this.line.hidden = !text;
  }
  onLatexChanged(latex) {
    clearTimeout(this._t);
    this._t = setTimeout(async () => {
      const expr = latex.trim().replace(/=\s*$/, "");
      if (!expr) { this.showLine("type math — try “int”, “frac”, “matrix”; = then Tab computes", false, "Tip"); return; }
      const r = await this.ctx.convert(expr);
      if (r.error) this.showLine(r.error, true);
      else { this.showLine(r.maxima, false); if (r.maxima !== this.node.attrs.source) setAttrs(this.view, this.getPos, { source: r.maxima }); }
    }, 250);
  }
  extraKey(e) {
    if (e.key === "Enter" && (e.shiftKey || e.ctrlKey || e.altKey) && !(e.shiftKey && e.ctrlKey)) {
      e.preventDefault();
      e.stopPropagation();
      if (!this.ctx.isHost) { this.ctx.toast("Only the host can run Maxima"); return; }
      setAttrs(this.view, this.getPos, { run: true }, true);
      this.ctx.runNode(this.node.attrs.id, { advance: e.shiftKey, insertAfter: e.altKey, from: this.getPos });
    }
  }
  updateExtra(old) {
    const a = this.node.attrs;
    const running = this.ctx.isRunning(a.id);
    this.dom.classList.toggle("running", running);
    this.dom.classList.toggle("evaluated", !!a.run);
    this.label.textContent = running ? "[*]" : a.run ? inLabel(a.inputs) : "";
    this.evalBtn.textContent = a.run ? "Evaluated" : "Display only";
    this.evalBtn.classList.toggle("on", !!a.run);
    if (!this.mf) this.line.hidden = true;
    if (!old || old.attrs.outputs !== a.outputs || running !== this._running) {
      renderOutputs(this.outputs, a.outputs, this.ctx, { running });
    }
    this._running = running;
  }
  selectNode() { this.dom.classList.add("selected"); }
  deselectNode() { this.dom.classList.remove("selected"); }
  stopEvent(e) {
    if (e.type.startsWith("drag") || e.type === "drop") return false;
    if (this.gutter.contains(e.target)) return e.type !== "mousedown";
    return this.dom.contains(e.target);
  }
}

export function nodeViews(ctx) {
  const reg = (v) => { ctx.instances.set(v.dom, v); return v; };
  return {
    maxima: (node, view, getPos) => reg(new MaximaView(node, view, getPos, ctx)),
    math_block: (node, view, getPos) => reg(new MathBlockView(node, view, getPos, ctx)),
    math_inline: (node, view, getPos) => reg(new MathInlineView(node, view, getPos, ctx)),
  };
}
