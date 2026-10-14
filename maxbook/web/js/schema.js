// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// The notebook document schema.  Must match maxbook/document.py.

import { model, schemaList } from "../vendor/prosemirror/prosemirror.mjs";

const { Schema } = model;

const evaluatedAttrs = {
  id: { default: null },
  source: { default: "" },
  outputs: { default: [] },
  inputs: { default: [] },
};

const nodes = {
  doc: { content: "block+", attrs: { title: { default: "" }, symbols: { default: {} } } },
  paragraph: {
    content: "inline*", group: "block",
    parseDOM: [{ tag: "p" }], toDOM: () => ["p", 0],
  },
  heading: {
    attrs: { level: { default: 1 } }, content: "inline*", group: "block", defining: true,
    parseDOM: [1, 2, 3, 4].map((level) => ({ tag: `h${level}`, attrs: { level } })),
    toDOM: (n) => [`h${n.attrs.level}`, 0],
  },
  blockquote: {
    content: "block+", group: "block", defining: true,
    parseDOM: [{ tag: "blockquote" }], toDOM: () => ["blockquote", 0],
  },
  horizontal_rule: { group: "block", parseDOM: [{ tag: "hr" }], toDOM: () => ["hr"] },
  code_block: {
    content: "text*", marks: "", group: "block", code: true, defining: true,
    attrs: { language: { default: "" } },
    parseDOM: [{ tag: "pre", preserveWhitespace: "full" }],
    toDOM: () => ["pre", ["code", 0]],
  },
  maxima: {
    group: "block", atom: true, selectable: true, draggable: true, isolating: true,
    attrs: { ...evaluatedAttrs },
    parseDOM: [{ tag: "div[data-maxima]", getAttrs: (dom) => ({ source: dom.getAttribute("data-source") || "" }) }],
    toDOM: (n) => ["div", { "data-maxima": "", "data-source": n.attrs.source }, n.attrs.source],
  },
  math_block: {
    group: "block", atom: true, selectable: true, draggable: true, isolating: true,
    attrs: { ...evaluatedAttrs, latex: { default: "" }, run: { default: false }, result: { default: null } },
    parseDOM: [{ tag: "div[data-math-block]", getAttrs: (dom) => ({ latex: dom.getAttribute("data-latex") || "" }) }],
    toDOM: (n) => ["div", { "data-math-block": "", "data-latex": n.attrs.latex }, `$$${n.attrs.latex}$$`],
  },
  text: { group: "inline" },
  hard_break: {
    inline: true, group: "inline", selectable: false,
    parseDOM: [{ tag: "br" }], toDOM: () => ["br"],
  },
  math_inline: {
    inline: true, group: "inline", atom: true, selectable: true,
    attrs: { id: { default: null }, latex: { default: "" }, source: { default: "" }, result: { default: null } },
    parseDOM: [{ tag: "span[data-math]", getAttrs: (dom) => ({ latex: dom.getAttribute("data-latex") || "" }) }],
    toDOM: (n) => ["span", { "data-math": "", "data-latex": n.attrs.latex }, `$${n.attrs.latex}$`],
  },
};

const marks = {
  strong: {
    parseDOM: [{ tag: "strong" }, { tag: "b" }, { style: "font-weight=bold" }],
    toDOM: () => ["strong", 0],
  },
  em: {
    parseDOM: [{ tag: "em" }, { tag: "i" }, { style: "font-style=italic" }],
    toDOM: () => ["em", 0],
  },
  code: { parseDOM: [{ tag: "code" }], toDOM: () => ["code", 0] },
  link: {
    attrs: { href: {} }, inclusive: false,
    parseDOM: [{ tag: "a[href]", getAttrs: (dom) => ({ href: dom.getAttribute("href") }) }],
    toDOM: (m) => ["a", { href: m.attrs.href, rel: "noopener noreferrer", target: "_blank" }, 0],
  },
};

const base = new Schema({ nodes, marks });
export const schema = new Schema({
  nodes: schemaList.addListNodes(base.spec.nodes, "paragraph block*", "block"),
  marks: base.spec.marks,
});

export const EVALUATED = new Set(["maxima", "math_block"]);
export const newId = () => Math.random().toString(16).slice(2, 14);
