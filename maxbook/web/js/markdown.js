// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Markdown with $inline$ and $$display$$ math.  Math is cut out before the
// Markdown pass (so "_" and "*" inside formulas are not treated as emphasis)
// and rendered with MathLive afterwards.

import { marked } from "../vendor/marked/marked.esm.js";
import { convertLatexToMarkup } from "../vendor/mathlive/mathlive.min.mjs";

marked.setOptions({ gfm: true, breaks: false });

export function renderLatex(latex, display = false) {
  try {
    return convertLatexToMarkup(latex, { defaultMode: display ? "math" : "inline-math" });
  } catch {
    const span = document.createElement("code");
    span.textContent = latex;
    return span.outerHTML;
  }
}

export function renderMarkdown(src) {
  const math = [];
  const stash = (latex, display) => {
    math.push({ latex, display });
    return `\u0000M${math.length - 1}\u0000`;
  };
  // Leave code spans and fences alone.
  const protectedParts = [];
  let text = src.replace(/```[\s\S]*?```|`[^`\n]+`/g, (m) => {
    protectedParts.push(m);
    return `\u0000P${protectedParts.length - 1}\u0000`;
  });
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, l) => stash(l.trim(), true));
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (_, l) => stash(l.trim(), true));
  text = text.replace(/(^|[^\\$])\$([^\s$](?:[^$\n]*?[^\s\\$])?)\$(?!\d)/g, (_, pre, l) => pre + stash(l, false));
  text = text.replace(/\\\((.+?)\\\)/g, (_, l) => stash(l, false));
  text = text.replace(/\u0000P(\d+)\u0000/g, (_, i) => protectedParts[+i]);
  let html = marked.parse(text);
  html = html.replace(/\u0000M(\d+)\u0000/g, (_, i) => {
    const { latex, display } = math[+i];
    const inner = renderLatex(latex, display);
    return display ? `<span class="math-display">${inner}</span>` : inner;
  });
  return html;
}

export function headingsOf(src) {
  const out = [];
  let inFence = false;
  for (const line of src.split("\n")) {
    if (line.trim().startsWith("```")) inFence = !inFence;
    if (inFence) continue;
    const m = line.match(/^(#{1,3})\s+(.+?)\s*#*\s*$/);
    if (m) out.push({ level: m[1].length, text: m[2].replace(/\$[^$]*\$/g, (s) => s.slice(1, -1)) });
  }
  return out;
}
