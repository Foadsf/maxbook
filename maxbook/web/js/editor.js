// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// The document editor: ProseMirror view, input rules, keys and plugins.

import {
  state as pmState, view as pmView, keymap as pmKeymap, history as pmHistory, commands, inputrules,
  schemaList, dropcursor, gapcursor,
} from "../vendor/prosemirror/prosemirror.mjs";
import { schema, newId } from "./schema.js";
import { nodeViews } from "./nodeviews.js";

const { EditorState, Plugin, PluginKey, NodeSelection, TextSelection } = pmState;
const { EditorView, Decoration, DecorationSet } = pmView;
const { keymap } = pmKeymap;
const { undo, redo, history } = pmHistory;
const { baseKeymap, toggleMark, setBlockType, chainCommands, exitCode } = commands;
const { InputRule, inputRules, textblockTypeInputRule, wrappingInputRule } = inputrules;
const { splitListItem, liftListItem, sinkListItem } = schemaList;
const N = schema.nodes;
const ID_NODES = new Set(["maxima", "math_block", "math_inline"]);

// ------------------------------------------------------------ insertion helpers
/** Replace the current empty paragraph (or insert after the cursor's block) with a block node. */
export function insertBlock(state, dispatch, node, { replaceEmpty = true } = {}) {
  const { $from } = state.selection;
  let tr = state.tr;
  const parent = $from.parent;
  const depth = $from.depth;
  let pos;
  if (state.selection instanceof NodeSelection) {
    pos = state.selection.to;
    tr = tr.insert(pos, node);
  } else if (replaceEmpty && parent.type === N.paragraph && parent.content.size === 0 && depth >= 1) {
    pos = $from.before(depth);
    tr = tr.replaceWith(pos, $from.after(depth), node);
  } else {
    pos = depth >= 1 ? $from.after(1) : state.doc.content.size;
    tr = tr.insert(pos, node);
  }
  // keep somewhere to write after the block
  const after = pos + node.nodeSize;
  const next = tr.doc.resolve(after).nodeAfter;
  if (!next) tr = tr.insert(after, N.paragraph.create());
  tr = tr.setSelection(NodeSelection.create(tr.doc, pos));
  if (dispatch) dispatch(tr.scrollIntoView());
  return pos;
}

export function insertInlineMath(state, dispatch, ctx, latex = "") {
  const id = newId();
  const node = N.math_inline.create({ id, latex });
  if (!state.selection.$from.parent.inlineContent) return false;
  ctx.markAutoEdit(id);
  if (dispatch) dispatch(state.tr.replaceSelectionWith(node, false).scrollIntoView());
  return true;
}

export function insertMathBlock(state, dispatch, ctx, latex = "", run = false) {
  const id = newId();
  ctx.markAutoEdit(id);
  insertBlock(state, dispatch, N.math_block.create({ id, latex, run }));
  return true;
}

export function insertMaxima(state, dispatch, ctx, source = "") {
  const id = newId();
  ctx.markAutoEdit(id);
  insertBlock(state, dispatch, N.maxima.create({ id, source }));
  return true;
}

// ------------------------------------------------------------ input rules
function blockRule(re, make) {
  return new InputRule(re, (state, match, start) => {
    const $start = state.doc.resolve(start);
    if ($start.parent.type !== N.paragraph || $start.depth < 1) return null;
    const node = make(match);
    if (!node) return null;
    const from = $start.before($start.depth);
    const to = $start.after($start.depth);
    let tr = state.tr.replaceWith(from, to, node);
    if (!tr.doc.resolve(from + node.nodeSize).nodeAfter) tr = tr.insert(from + node.nodeSize, N.paragraph.create());
    return tr.setSelection(NodeSelection.create(tr.doc, from));
  });
}

function markRule(re, markType) {
  // the match is exactly the delimited text, e.g. **bold**
  return new InputRule(re, (state, match, start, end) =>
    state.tr.replaceWith(start, end, schema.text(match[1], [markType.create()])).removeStoredMark(markType));
}

function rules(ctx) {
  return inputRules({ rules: [
    textblockTypeInputRule(/^(#{1,4})\s$/, N.heading, (m) => ({ level: m[1].length })),
    wrappingInputRule(/^\s*>\s$/, N.blockquote),
    wrappingInputRule(/^\s*([-+*])\s$/, N.bullet_list),
    wrappingInputRule(/^(\d+)\.\s$/, N.ordered_list, (m) => ({ order: +m[1] }),
      (m, node) => node.childCount + node.attrs.order === +m[1]),
    blockRule(/^```([A-Za-z]*)\s$/, (m) => {
      const lang = m[1].toLowerCase();
      if (!lang || lang === "maxima" || lang === "mac") {
        const id = newId();
        ctx.markAutoEdit(id);
        return N.maxima.create({ id });
      }
      return N.code_block.create({ language: lang });
    }),
    blockRule(/^>>\s$/, () => { const id = newId(); ctx.markAutoEdit(id); return N.maxima.create({ id }); }),
    blockRule(/^---$/, () => N.horizontal_rule.create()),
    markRule(/\*\*([^*\s][^*]*)\*\*$/, schema.marks.strong),
    markRule(/`([^`\s][^`]*)`$/, schema.marks.code),
    new InputRule(/\$$/, (state, match, start, end) => {
      const $s = state.doc.resolve(start);
      if ($s.parent.type.spec.code || !$s.parent.inlineContent) return null;
      const id = newId();
      ctx.markAutoEdit(id);
      return state.tr.replaceWith(start, end, N.math_inline.create({ id }));
    }),
  ] });
}

// ------------------------------------------------------------ plugins
const uniqueIds = new Plugin({
  appendTransaction(trs, _old, state) {
    if (!trs.some((t) => t.docChanged)) return null;
    const seen = new Set();
    let tr = null;
    state.doc.descendants((node, pos) => {
      if (!ID_NODES.has(node.type.name)) return;
      let id = node.attrs.id;
      if (!id || seen.has(id)) {
        id = newId();
        tr = tr || state.tr;
        tr.setNodeAttribute(pos, "id", id);
      }
      seen.add(id);
    });
    if (tr) tr.setMeta("addToHistory", false);
    return tr;
  },
});

const placeholderKey = new PluginKey("placeholder");
const placeholder = new Plugin({
  key: placeholderKey,
  props: {
    decorations(state) {
      // only in a document that has nothing but a heading and empty paragraphs
      const doc = state.doc;
      if (doc.childCount > 3) return null;
      let content = false;
      doc.forEach((node) => { if (node.type !== N.heading && node.content.size > 0) content = true; if (node.isAtom) content = true; });
      if (content) return null;
      const decos = [];
      doc.forEach((node, offset) => {
        if (node.type === N.paragraph && node.content.size === 0 && decos.length === 0) {
          decos.push(Decoration.node(offset, offset + node.nodeSize, {
            class: "empty-hint",
            "data-hint": "Write here. $ for a formula, >> for Maxima, # for a heading, Ctrl+K for everything",
          }));
        }
      });
      return DecorationSet.create(doc, decos);
    },
  },
});

function enterSelectedBlock(ctx) {
  return (state) => {
    const sel = state.selection;
    if (!(sel instanceof NodeSelection)) return false;
    if (!["maxima", "math_block", "math_inline"].includes(sel.node.type.name)) return false;
    return ctx.focusNodeAt(sel.from);
  };
}

function keys(ctx) {
  const k = {
    "Mod-z": undo, "Mod-y": redo, "Shift-Mod-z": redo,
    "Mod-b": toggleMark(schema.marks.strong), "Mod-i": toggleMark(schema.marks.em),
    "Mod-`": toggleMark(schema.marks.code),
    Enter: chainCommands(enterSelectedBlock(ctx), splitListItem(N.list_item)),
    "Mod-[": liftListItem(N.list_item), "Mod-]": sinkListItem(N.list_item),
    "Shift-Enter": chainCommands(exitCode, (state, dispatch) => {
      if (dispatch) dispatch(state.tr.replaceSelectionWith(N.hard_break.create()).scrollIntoView());
      return true;
    }),
    "Mod-Alt-0": setBlockType(N.paragraph),
    "Mod-m": (s, d) => insertInlineMath(s, d, ctx),
    "Mod-Shift-m": (s, d) => insertMathBlock(s, d, ctx),
    "Mod-Alt-m": (s, d) => insertMaxima(s, d, ctx),
  };
  for (const level of [1, 2, 3, 4]) k[`Mod-Alt-${level}`] = setBlockType(N.heading, { level });
  return keymap(k);
}

// ------------------------------------------------------------ the view
export function createEditor({ mount, doc, ctx, extraPlugins = [], onTransaction }) {
  const state = EditorState.create({
    doc,
    plugins: [
      rules(ctx), keys(ctx), keymap(baseKeymap), history(), dropcursor.dropCursor(), gapcursor.gapCursor(),
      uniqueIds, placeholder, ...extraPlugins,
    ],
  });
  const view = new EditorView(mount, {
    state,
    nodeViews: nodeViews(ctx),
    attributes: { class: "mbk-doc", spellcheck: "true" },
    dispatchTransaction(tr) {
      const newState = view.state.apply(tr);
      view.updateState(newState);
      onTransaction?.(tr, newState);
    },
    clipboardTextParser: ctx.clipboardTextParser,
    handleDOMEvents: {
      // links open in a new window instead of being edited
      click(v, e) {
        const a = e.target.closest?.("a[href]");
        if (a && (e.ctrlKey || e.metaKey)) { window.open(a.href, "_blank", "noopener"); return true; }
        return false;
      },
    },
  });
  return view;
}

export { NodeSelection, TextSelection };
