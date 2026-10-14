// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Markdown (with $math$, $$math$$ and ```maxima blocks) -> document nodes.
// Used for imported files, old cell-based notebooks, AI answers and paste.

import { markdown, MarkdownIt, model } from "../vendor/prosemirror/prosemirror.mjs";
import { schema, newId } from "./schema.js";

// ------------------------------------------------------------ math syntax
function mathInline(state, silent) {
  const src = state.src;
  let pos = state.pos;
  if (src[pos] !== "$") return false;
  const display = src[pos + 1] === "$";
  const open = display ? 2 : 1;
  const start = pos + open;
  if (!display && (src[start] === " " || src[start] === undefined)) return false;
  let end = start;
  while (end < state.posMax) {
    if (src[end] === "\\") { end += 2; continue; }
    if (src[end] === "$" && (!display || src[end + 1] === "$")) break;
    end++;
  }
  if (end >= state.posMax || end === start) return false;
  if (!display && src[end - 1] === " ") return false;
  if (!display && /\d/.test(src[end + 1] || "")) return false; // "$5 and $6" is money
  if (!silent) {
    const tok = state.push("math_inline", "math", 0);
    tok.content = src.slice(start, end).trim();
    tok.markup = display ? "$$" : "$";
  }
  state.pos = end + open;
  return true;
}

function mathBlock(state, startLine, endLine, silent) {
  let pos = state.bMarks[startLine] + state.tShift[startLine];
  let max = state.eMarks[startLine];
  if (pos + 2 > max || state.src.slice(pos, pos + 2) !== "$$") return false;
  if (silent) return true;
  let first = state.src.slice(pos + 2, max);
  let line = startLine;
  let content;
  const closeOnFirst = first.trim().endsWith("$$") && first.trim().length >= 2;
  if (closeOnFirst) {
    content = first.trim().slice(0, -2);
  } else {
    const lines = [first];
    let found = false;
    while (++line < endLine) {
      pos = state.bMarks[line] + state.tShift[line];
      max = state.eMarks[line];
      const text = state.src.slice(pos, max);
      const k = text.indexOf("$$");
      if (k >= 0) { lines.push(text.slice(0, k)); found = true; break; }
      lines.push(text);
    }
    if (!found) return false;
    content = lines.join("\n");
  }
  state.line = line + 1;
  const tok = state.push("math_block", "math", 0);
  tok.block = true;
  tok.content = content.trim();
  tok.map = [startLine, state.line];
  return true;
}

function maximaFences(state) {
  for (const tok of state.tokens) {
    if (tok.type === "fence" && /^(maxima|mac)\b/i.test(tok.info.trim())) tok.type = "maxima_fence";
    if (tok.type === "inline" && tok.children) {
      tok.children = tok.children.map((c) => {
        if (c.type !== "image") return c;
        const t = new state.Token("text", "", 0);
        t.content = c.content ? `[image: ${c.content}]` : "[image]";
        return t;
      });
    }
  }
}

const md = MarkdownIt("commonmark", { html: false });
md.inline.ruler.before("escape", "math_inline", mathInline);
md.block.ruler.before("fence", "math_block", mathBlock, { alt: ["paragraph", "reference", "blockquote", "list"] });
md.core.ruler.push("maxima_fences", maximaFences);

const parser = new markdown.MarkdownParser(schema, md, {
  blockquote: { block: "blockquote" },
  paragraph: { block: "paragraph" },
  list_item: { block: "list_item" },
  bullet_list: { block: "bullet_list" },
  ordered_list: { block: "ordered_list", getAttrs: (tok) => ({ order: +tok.attrGet("start") || 1 }) },
  heading: { block: "heading", getAttrs: (tok) => ({ level: Math.min(4, +tok.tag.slice(1)) }) },
  code_block: { block: "code_block", noCloseToken: true },
  fence: { block: "code_block", getAttrs: (tok) => ({ language: tok.info || "" }), noCloseToken: true },
  maxima_fence: { node: "maxima", getAttrs: (tok) => ({ id: newId(), source: tok.content.replace(/\n$/, "") }) },
  hr: { node: "horizontal_rule" },
  hardbreak: { node: "hard_break" },
  em: { mark: "em" },
  strong: { mark: "strong" },
  link: { mark: "link", getAttrs: (tok) => ({ href: tok.attrGet("href") }) },
  code_inline: { mark: "code", noCloseToken: true },
  math_inline: { node: "math_inline", getAttrs: (tok) => ({ id: newId(), latex: tok.content }) },
  math_block: { node: "math_block", getAttrs: (tok) => ({ id: newId(), latex: tok.content }) },
});

/** Markdown -> array of block nodes (never throws). */
export function markdownToNodes(text) {
  try {
    const doc = parser.parse(text || "");
    const out = [];
    doc.forEach((n) => out.push(n));
    return out;
  } catch (e) {
    console.warn("markdown parse failed; inserting as plain text", e);
    return (text || "").split(/\n{2,}/).filter((p) => p.trim())
      .map((p) => schema.nodes.paragraph.create(null, schema.text(p)));
  }
}

/** Old cell-based notebooks and imports -> a document. */
export function cellsToDoc(nb) {
  const blocks = [];
  for (const cell of nb.cells || []) {
    if (cell.type === "markdown") {
      blocks.push(...markdownToNodes(cell.source));
    } else if (cell.type === "code") {
      blocks.push(schema.nodes.maxima.create({
        id: cell.id || newId(), source: cell.source || "", outputs: cell.outputs || [], inputs: cell.inputs || [],
      }));
    } else if (cell.type === "math") {
      blocks.push(schema.nodes.math_block.create({
        id: cell.id || newId(), latex: cell.latex || "", source: cell.source || "", run: true,
        outputs: cell.outputs || [], inputs: cell.inputs || [],
      }));
    }
  }
  if (!blocks.length) blocks.push(schema.nodes.paragraph.create());
  return schema.nodes.doc.create({ title: nb.title || "Untitled", symbols: {} }, blocks);
}

export const fragmentFromMarkdown = (text) => model.Fragment.from(markdownToNodes(text));
