// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Static math rendering and symbol tagging.
//
// Maxima tags the symbols in its own outputs (see maxbook-init.lisp):
//   \class{mbk-sym mbk-KIND mbk-n-HEX}{...}
// For formulas the user types we tag symbols here, following the same
// conventions as the LaTeX-to-Maxima translator: e, \pi, \imaginaryI and
// \infty are constants; a plain i is a variable.

import { convertLatexToMarkup } from "../vendor/mathlive/mathlive.min.mjs";

export function renderMath(latex, display = false) {
  try {
    return convertLatexToMarkup(latex, { defaultMode: display ? "math" : "inline-math" });
  } catch {
    const code = document.createElement("code");
    code.textContent = latex;
    return code.outerHTML;
  }
}

// --------------------------------------------------------------- names
export const hexName = (name) =>
  [...name].map((c) => c.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")).join("");

export function nameFromClass(el) {
  for (const c of el.classList) {
    if (c.startsWith("mbk-n-")) {
      const hex = c.slice(6);
      let s = "";
      for (let i = 0; i < hex.length; i += 4) s += String.fromCodePoint(parseInt(hex.slice(i, i + 4), 16));
      return s;
    }
  }
  return null;
}

export function kindFromClass(el) {
  for (const k of ["constant", "function", "variable", "free"]) if (el.classList.contains(`mbk-${k}`)) return k;
  return "free";
}

/** Strip \class wrappers (for copying LaTeX or exporting). */
export function stripClasses(latex) {
  let out = latex;
  for (let guard = 0; guard < 1000 && out.includes("\\class{"); guard++) {
    const i = out.indexOf("\\class{");
    const a = matchBrace(out, i + 6);
    if (a < 0 || out[a + 1] !== "{") break;
    const b = matchBrace(out, a + 1);
    if (b < 0) break;
    out = out.slice(0, i) + out.slice(a + 2, b) + out.slice(b + 1);
  }
  return out;
}

function matchBrace(s, i) {
  let depth = 0;
  for (let j = i; j < s.length; j++) {
    const c = s[j];
    if (c === "\\") { j++; continue; }
    if (c === "{") depth++;
    else if (c === "}" && --depth === 0) return j;
  }
  return -1;
}

// --------------------------------------------------------------- tagging
const CONSTANT_COMMANDS = { "\\pi": "%pi", "\\infty": "inf", "\\exponentialE": "%e", "\\imaginaryI": "%i" };
const GREEK = new Set(["alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta",
  "iota", "kappa", "lambda", "mu", "nu", "xi", "rho", "varrho", "sigma", "varsigma", "tau", "upsilon", "phi",
  "varphi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi",
  "Psi", "Omega"]);
const SKIP_GROUP = new Set(["\\text", "\\textrm", "\\textit", "\\begin", "\\end", "\\placeholder"]);
const NAME_GROUP = new Set(["\\operatorname", "\\mathrm", "\\mathit"]);

function wrap(name, kind, inner = name) {
  return `\\class{mbk-sym mbk-${kind} mbk-n-${hexName(name)}}{${inner}}`;
}

/**
 * Tag the symbols in a formula the user typed.  ``kindOf(name)`` returns the
 * kind Maxima reported (variable/function/constant) or undefined.
 */
export function tagLatex(latex, kindOf = () => undefined) {
  let out = "";
  let i = 0;
  const kind = (name, fallback = "free") => kindOf(name) || fallback;
  while (i < latex.length) {
    const c = latex[i];
    if (c === "\\") {
      const m = latex.slice(i).match(/^\\([A-Za-z]+)/);
      if (!m) { out += latex.slice(i, i + 2); i += 2; continue; }
      const cmd = "\\" + m[1];
      i += m[0].length;
      if (CONSTANT_COMMANDS[cmd]) { out += wrap(CONSTANT_COMMANDS[cmd], "constant", cmd); continue; }
      if (GREEK.has(m[1])) { out += wrap(m[1], kind(m[1]), cmd); continue; }
      if ((SKIP_GROUP.has(cmd) || NAME_GROUP.has(cmd)) && latex[i] === "{") {
        const end = matchBrace(latex, i);
        const inner = latex.slice(i + 1, end < 0 ? latex.length : end);
        const group = latex.slice(i, end < 0 ? latex.length : end + 1);
        i = end < 0 ? latex.length : end + 1;
        if (NAME_GROUP.has(cmd) && /^[A-Za-z_%][A-Za-z0-9_%]*$/.test(inner) && inner !== "d") {
          const name = inner === "e" ? "%e" : inner === "i" ? "%i" : inner;
          const k = name.startsWith("%") ? "constant" : kind(name, latex[i] === "(" || latex.startsWith("\\left(", i) ? "function" : "free");
          out += wrap(name, k, cmd + group);
        } else {
          out += cmd + group;
        }
        continue;
      }
      out += cmd;
      continue;
    }
    if (/[A-Za-z]/.test(c)) {
      // a differential "d x" inside an integral is not a symbol
      if (c === "d" && /^d\s*[A-Za-z]/.test(latex.slice(i)) && /\\[,!;]\s*$|\\int.*$/.test(out)) {
        out += c; i++; continue;
      }
      if (c === "e") out += wrap("%e", "constant", "e");
      else out += wrap(c, kind(c));
      i++;
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

// --------------------------------------------------------------- colours
const PALETTE = ["#3b5bdb", "#0c8599", "#2f9e44", "#e8590c", "#ae3ec9", "#c2255c", "#1971c2", "#5c940d",
  "#d6336c", "#7048e8", "#0ca678", "#f08c00"];

function hash(s) {
  let h = 2166136261;
  for (const ch of s) { h ^= ch.codePointAt(0); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

export const colourFor = (name) => PALETTE[hash(name) % PALETTE.length];

const styled = new Set();
let styleEl = null;
/** Make sure every symbol class in ``root`` has its colour rule. */
export function ensureSymbolColours(root) {
  const rules = [];
  root.querySelectorAll(".mbk-sym").forEach((el) => {
    const name = nameFromClass(el);
    if (!name || styled.has(name)) return;
    styled.add(name);
    rules.push(`.mbk-n-${hexName(name)}{--sym:${colourFor(name)}}`);
  });
  if (!rules.length) return;
  if (!styleEl) { styleEl = document.createElement("style"); document.head.append(styleEl); }
  styleEl.textContent += rules.join("\n") + "\n";
}
