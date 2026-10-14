// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Symbols ("objects"): what Maxima knows about the names in the notebook.
// Colours and hover cards come from the \class tags in rendered math; the
// panel lists defined variables, functions, constants and free symbols.

import { get } from "./api.js";
import { renderMath, nameFromClass, kindFromClass, colourFor, hexName, ensureSymbolColours } from "./mathrender.js";
import { el } from "./nodeviews.js";

const BUILTIN = {
  "%pi": { label: "\\pi", description: "π, the ratio of a circle's circumference to its diameter" },
  "%e": { label: "e", description: "Euler's number, the base of the natural logarithm" },
  "%i": { label: "i", description: "The imaginary unit, i² = −1" },
  "%phi": { label: "\\phi", description: "The golden ratio" },
  "%gamma": { label: "\\gamma", description: "The Euler–Mascheroni constant" },
  inf: { label: "\\infty", description: "Positive real infinity" },
  minf: { label: "-\\infty", description: "Negative real infinity" },
};

const KIND_LABEL = { variable: "Variable", function: "Function", constant: "Constant", free: "Symbol (no value)" };

export class SymbolRegistry {
  constructor({ getDescriptions, setDescription, onChange }) {
    Object.assign(this, { getDescriptions, setDescription, onChange });
    this.table = new Map(); // name -> {kind, latex, text}
  }

  kindOf(name) { return this.table.get(name)?.kind; }

  async refresh() {
    try {
      const r = await get("/api/symbols");
      if (r.stale) return;
      this.table = new Map(r.symbols.map((s) => [s.name, s]));
      this.onChange?.();
    } catch { /* kernel not ready */ }
  }

  info(name, kind) {
    const entry = this.table.get(name);
    const builtin = BUILTIN[name];
    const desc = this.getDescriptions()[name]?.description || builtin?.description || "";
    return { name, kind: entry?.kind || kind || "free", latex: entry?.latex, text: entry?.text, description: desc,
             label: builtin?.label || labelFor(name) };
  }
}

const GREEK = /^(alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega)$/;
const labelFor = (name) => (GREEK.test(name) ? `\\${name}` : name.length > 1 ? `\\mathrm{${name.replace(/_/g, "\\_")}}` : name);

// ------------------------------------------------------------ hover card
export function installHover(root, registry) {
  let card = null;
  let current = null;
  const hide = () => { card?.remove(); card = null; current = null; };
  root.addEventListener("mouseover", (e) => {
    const sym = e.target.closest?.(".mbk-sym");
    if (!sym) { hide(); return; }
    if (sym === current) return;
    if (sym.closest("math-field")) return;
    hide();
    current = sym;
    const info = registry.info(nameFromClass(sym), kindFromClass(sym));
    card = el("div", { class: "sym-card", role: "tooltip" },
      el("div", { class: "sym-head" },
        el("span", { class: "sym-chip", style: `--sym:${colourFor(info.name)}`, html: renderMath(info.label) }),
        el("span", { class: "sym-kind", text: KIND_LABEL[info.kind] || info.kind })),
      info.description ? el("div", { class: "sym-desc", text: info.description }) : null,
      info.latex ? el("div", { class: "sym-value", html: renderMath(info.latex, true) })
        : info.text ? el("div", { class: "sym-value mono", text: info.text }) : null);
    document.body.append(card);
    ensureSymbolColours(card);
    const r = sym.getBoundingClientRect();
    const w = card.offsetWidth;
    card.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + "px";
    card.style.top = (r.top > 140 ? r.top - card.offsetHeight - 8 : r.bottom + 8) + "px";
  });
  root.addEventListener("mouseout", (e) => {
    if (!current) return;
    if (e.relatedTarget && current.contains(e.relatedTarget)) return;
    hide();
  });
  window.addEventListener("scroll", hide, true);
}

// ------------------------------------------------------------ panel
export function renderObjectsPanel(box, registry, docRoot, { onEditDescription, used }) {
  // free symbols: whatever is tagged in the document but unknown to Maxima
  const seen = new Map();
  docRoot.querySelectorAll(".mbk-sym").forEach((s) => {
    const name = nameFromClass(s);
    if (name && !seen.has(name)) seen.set(name, kindFromClass(s));
  });
  // Maxima's table also holds what packages define when they load (eigen,
  // draw...); list only the names the notebook's own code mentions.
  for (const [name, entry] of registry.table) if (!used || used.has(name)) seen.set(name, entry.kind);
  const groups = { variable: [], function: [], constant: [], free: [] };
  for (const [name, kind] of seen) (groups[kind] || groups.free).push(name);
  const counts = {};
  docRoot.querySelectorAll(".mbk-sym").forEach((s) => {
    const n = nameFromClass(s);
    counts[n] = (counts[n] || 0) + 1;
  });
  const sections = [["variable", "Variables"], ["function", "Functions"], ["constant", "Constants"],
    ["free", "Symbols without a value"]];
  const parts = [];
  for (const [kind, title] of sections) {
    const names = groups[kind].sort((a, b) => a.localeCompare(b));
    if (!names.length) continue;
    parts.push(el("h4", { text: `${title} · ${names.length}` }));
    for (const name of names) {
      const info = registry.info(name, kind);
      const row = el("div", { class: "obj-row", title: "Click to highlight every use" },
        el("span", { class: `sym-chip mbk-${kind}`, style: `--sym:${colourFor(name)}`, html: renderMath(info.label) }),
        el("div", { class: "obj-main" },
          el("div", { class: "obj-value" }, info.text ? renderShort(info) : el("span", { class: "muted", text: info.description || "—" })),
          counts[name] ? el("div", { class: "obj-meta", text: `${counts[name]} use${counts[name] === 1 ? "" : "s"} in formulas` }) : null),
        el("button", { class: "obj-edit", title: "Describe this symbol", text: "✎",
          onclick: (e) => { e.stopPropagation(); onEditDescription(name, info.description); } }));
      row.addEventListener("click", () => highlight(docRoot, name));
      parts.push(row);
    }
  }
  box.replaceChildren(...(parts.length ? parts
    : [el("div", { class: "empty", text: "Symbols appear here once you write or run formulas" })]));
  ensureSymbolColours(box);
}

function renderShort(info) {
  const span = el("span", { class: "obj-text", title: info.text });
  if (info.latex && info.latex.length < 300) span.innerHTML = renderMath(info.latex);
  else span.textContent = info.text.length > 60 ? info.text.slice(0, 60) + "…" : info.text;
  return span;
}

function highlight(root, name) {
  const cls = `.mbk-n-${hexName(name)}`;
  const hits = [...root.querySelectorAll(cls)];
  hits.forEach((h) => h.classList.add("mbk-hl"));
  hits[0]?.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => hits.forEach((h) => h.classList.remove("mbk-hl")), 2200);
}
