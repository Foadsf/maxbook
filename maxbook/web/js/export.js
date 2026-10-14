// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Exports that need the browser: a self-contained HTML page (math rendered,
// fonts embedded) and PNG versions of plots for the LaTeX bundle.  Both read
// the document JSON.

import { renderMath, stripClasses } from "./mathrender.js";
import { highlightMaxima } from "./highlight.js";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

async function toDataUrl(url) {
  const blob = await (await fetch(url)).blob();
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}

async function inlineFonts(css, base) {
  const urls = [...new Set([...css.matchAll(/url\((?:["']?)(fonts\/[^)"']+)(?:["']?)\)/g)].map((m) => m[1]))];
  for (const u of urls) css = css.split(u).join(await toDataUrl(base + u));
  return css;
}

function imageSrc(o) {
  return o.mime === "image/svg+xml"
    ? "data:image/svg+xml;charset=utf-8," + encodeURIComponent(o.data)
    : `data:${o.mime};base64,${o.data}`;
}

const PAGE_CSS = `
body{margin:0;background:#f4f2ee;color:#1d1c1a;font:17px/1.62 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
main{max-width:860px;margin:32px auto;background:#fffefb;border:1px solid #e4e0d7;border-radius:14px;padding:36px 44px}
h1{font-size:30px;line-height:1.2;font-weight:600}h2{font-size:23px;font-weight:600}h3{font-size:19px;font-weight:600}
pre{font:13.5px/1.5 ui-monospace,"Cascadia Code",Menlo,Consolas,monospace;white-space:pre-wrap;margin:6px 0}
pre.code{background:#f6f4ef;border:1px solid #e4e0d7;border-radius:8px;padding:9px 12px}
pre.err{background:#fff1f0;color:#c92a2a;border-radius:8px;padding:6px 10px}
blockquote{border-left:3px solid #d6d1c5;margin:8px 0;padding:2px 14px;color:#4a4843}
.out{display:flex;gap:12px;align-items:center;margin:4px 0}.lbl{font:12px ui-monospace,Menlo,Consolas,monospace;color:#8a867d;min-width:56px;text-align:right}
.m{overflow-x:auto;overflow-y:hidden;font-size:19px;padding:4px 0}.math-display{display:block;text-align:center;margin:10px 0;overflow-x:auto;overflow-y:hidden;padding:2px 0}
.res{background:#e7ecfd;border-radius:4px;padding:0 3px}
img{max-width:100%;border:1px solid #e4e0d7;border-radius:8px;background:#fff}
.hl-c{color:#8a867d;font-style:italic}.hl-s{color:#2b8a3e}.hl-n{color:#c2410c}.hl-k{color:#7048e8;font-weight:600}.hl-f{color:#1c64c8}.hl-k2{color:#b8325a}
footer{max-width:860px;margin:0 auto 32px;color:#8a867d;font:12px system-ui,sans-serif;text-align:right}
@media print{body{background:#fff}main{border:0;margin:0;padding:0}}`;

function inlineHTML(nodes) {
  return (nodes || []).map((n) => {
    if (n.type === "text") {
      let s = esc(n.text);
      for (const m of n.marks || []) {
        if (m.type === "strong") s = `<strong>${s}</strong>`;
        else if (m.type === "em") s = `<em>${s}</em>`;
        else if (m.type === "code") s = `<code>${s}</code>`;
        else if (m.type === "link") s = `<a href="${esc(m.attrs.href)}">${s}</a>`;
      }
      return s;
    }
    if (n.type === "hard_break") return "<br>";
    if (n.type === "math_inline") return formulaHTML(n.attrs, false);
    return "";
  }).join("");
}

function formulaHTML(a, display) {
  let html = renderMath(a.latex || "", display);
  const r = a.result;
  if (r && (r.latex || r.semantic) && /=\s*$/.test(a.latex || "")) {
    html += `<span class="res">${renderMath(stripClasses(r.latex || r.semantic), display)}</span>`;
  }
  return html;
}

function outputsHTML(outputs) {
  return (outputs || []).map((o) => {
    if (o.kind === "result") {
      return `<div class="out"><span class="lbl">${o.label ? "(" + esc(o.label) + ")" : ""}</span><div class="m">${o.latex ? renderMath(o.latex, true) : esc(o.text)}</div></div>`;
    }
    if (o.kind === "text") return `<pre>${esc(o.text)}</pre>`;
    if (o.kind === "error") return `<pre class="err">${esc(o.text)}</pre>`;
    if (o.kind === "image") return `<p><img alt="plot" src="${imageSrc(o)}"></p>`;
    return "";
  }).join("\n");
}

function blockHTML(n) {
  const a = n.attrs || {};
  const kids = (n.content || []).map(blockHTML).join("\n");
  switch (n.type) {
    case "paragraph": return `<p>${inlineHTML(n.content)}</p>`;
    case "heading": return `<h${a.level}>${inlineHTML(n.content)}</h${a.level}>`;
    case "blockquote": return `<blockquote>${kids}</blockquote>`;
    case "bullet_list": return `<ul>${kids}</ul>`;
    case "ordered_list": return `<ol start="${a.order || 1}">${kids}</ol>`;
    case "list_item": return `<li>${kids}</li>`;
    case "horizontal_rule": return "<hr>";
    case "code_block": return `<pre class="code">${esc((n.content || []).map((t) => t.text).join(""))}</pre>`;
    case "maxima":
      return (a.source?.trim() ? `<pre class="code">${highlightMaxima(a.source)}</pre>` : "") + outputsHTML(a.outputs);
    case "math_block":
      return `<div class="math-display">${formulaHTML(a, true)}</div>` + outputsHTML(a.outputs);
    default: return kids;
  }
}

export async function buildHtmlExport(docJSON, title) {
  const base = new URL("vendor/mathlive/", location.href).href;
  const [fontsCss, staticCss] = await Promise.all([
    fetch(base + "mathlive-fonts.css").then((r) => r.text()),
    fetch(base + "mathlive-static.css").then((r) => r.text()),
  ]);
  const css = (await inlineFonts(fontsCss, base)) + "\n" + (await inlineFonts(staticCss, base)) + PAGE_CSS;
  const body = (docJSON.content || []).map(blockHTML).join("\n");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title><style>${css}</style></head>
<body><main>
${body}
</main><footer>Exported from Maxbook</footer></body></html>
`;
}

function rasterize(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const scale = 2;
      const w = img.naturalWidth || 640;
      const h = img.naturalHeight || 480;
      const c = document.createElement("canvas");
      c.width = w * scale;
      c.height = h * scale;
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      try { resolve(c.toDataURL("image/png")); } catch { resolve(""); }
    };
    img.onerror = () => resolve("");
    img.src = src;
  });
}

/** PNG data URLs for every image output, in document order (matches the LaTeX exporter). */
export async function rasterizeImages(docJSON) {
  const out = [];
  async function walk(n) {
    if (n.type === "maxima" || n.type === "math_block") {
      for (const o of n.attrs?.outputs || []) {
        if (o.kind !== "image") continue;
        out.push(o.mime === "image/png" ? `data:image/png;base64,${o.data}` : await rasterize(imageSrc(o)));
      }
    }
    for (const c of n.content || []) await walk(c);
  }
  for (const b of docJSON.content || []) await walk(b);
  return out;
}
