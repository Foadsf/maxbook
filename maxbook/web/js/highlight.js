// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Maxima syntax highlighting for the code editor overlay.

const KEYWORDS = new Set([
  "if", "then", "else", "elseif", "for", "thru", "step", "while", "unless", "do", "in", "from",
  "next", "block", "lambda", "and", "or", "not", "return", "go", "catch", "throw", "local",
]);
const CONSTANTS = new Set([
  "%pi", "%e", "%i", "%phi", "%gamma", "inf", "minf", "infinity", "true", "false", "und", "ind", "zeroa", "zerob",
]);

const TOKEN = new RegExp([
  String.raw`(\/\*[\s\S]*?(?:\*\/|$))`,            // 1 comment (possibly unterminated)
  String.raw`("(?:[^"\\]|\\[\s\S])*"?)`,           // 2 string
  String.raw`(\b\d+(?:\.\d*)?(?:[eEbB][+-]?\d+)?\b|\.\d+(?:[eE][+-]?\d+)?)`, // 3 number
  String.raw`(%?[A-Za-z_][A-Za-z0-9_%]*|\?[A-Za-z_\\-][A-Za-z0-9_\\-]*)`,   // 4 identifier
  String.raw`(:=|::=|::|:|\$|;|\^\^|\*\*|[-+*/^=#<>!'.,])`,          // 5 operator
].join("|"), "g");

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function highlightMaxima(src) {
  let out = "";
  let last = 0;
  TOKEN.lastIndex = 0;
  let m;
  while ((m = TOKEN.exec(src))) {
    if (m.index > last) out += esc(src.slice(last, m.index));
    const [tok, comment, string, number, ident, op] = m;
    if (comment) out += `<span class="hl-c">${esc(comment)}</span>`;
    else if (string) out += `<span class="hl-s">${esc(string)}</span>`;
    else if (number) out += `<span class="hl-n">${esc(number)}</span>`;
    else if (ident) {
      const after = src.slice(m.index + tok.length).match(/^\s*\(/);
      if (KEYWORDS.has(ident)) out += `<span class="hl-k">${esc(ident)}</span>`;
      else if (CONSTANTS.has(ident)) out += `<span class="hl-k2">${esc(ident)}</span>`;
      else if (after) out += `<span class="hl-f">${esc(ident)}</span>`;
      else out += esc(ident);
    } else if (op) out += `<span class="hl-o">${esc(op)}</span>`;
    else out += esc(tok);
    last = m.index + tok.length;
    if (tok.length === 0) TOKEN.lastIndex++;
  }
  out += esc(src.slice(last));
  return out;
}
