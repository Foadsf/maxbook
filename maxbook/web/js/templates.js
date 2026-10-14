// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Searchable insert templates.
//   math: LaTeX for math cells (#0 = first slot, #? = further slots)
//   code: Maxima text for code cells (| marks where the cursor goes)

export const MATH_TEMPLATES = [
  { t: "Integral", k: "int integral antiderivative", latex: String.raw`\int #0\,\mathrm{d}#?` },
  { t: "Definite integral", k: "int integral definite area", latex: String.raw`\int_{#?}^{#?} #0\,\mathrm{d}#?` },
  { t: "Derivative", k: "diff derivative ddx d/dx", latex: String.raw`\frac{\mathrm{d}}{\mathrm{d}#?}#0` },
  { t: "Second derivative", k: "diff derivative second", latex: String.raw`\frac{\mathrm{d}^2}{\mathrm{d}#?^2}#0` },
  { t: "Partial derivative", k: "partial diff derivative", latex: String.raw`\frac{\partial}{\partial #?}#0` },
  { t: "Mixed partial", k: "partial mixed diff", latex: String.raw`\frac{\partial^2 #0}{\partial #?\partial #?}` },
  { t: "Sum", k: "sum sigma series", latex: String.raw`\sum_{#?=#?}^{#?} #0` },
  { t: "Product", k: "prod product pi", latex: String.raw`\prod_{#?=#?}^{#?} #0` },
  { t: "Limit", k: "lim limit", latex: String.raw`\lim_{#?\to #?} #0` },
  { t: "Fraction", k: "frac fraction divide over", latex: String.raw`\frac{#0}{#?}` },
  { t: "Square root", k: "sqrt root square", latex: String.raw`\sqrt{#0}` },
  { t: "n-th root", k: "root nth cube", latex: String.raw`\sqrt[#?]{#0}` },
  { t: "Power", k: "power exponent pow", latex: String.raw`{#0}^{#?}` },
  { t: "Subscript", k: "index subscript", latex: String.raw`{#0}_{#?}` },
  { t: "Absolute value", k: "abs absolute modulus", latex: String.raw`\left|#0\right|` },
  { t: "Binomial", k: "binom binomial choose", latex: String.raw`\binom{#0}{#?}` },
  { t: "Floor", k: "floor", latex: String.raw`\lfloor #0\rfloor` },
  { t: "Ceiling", k: "ceil ceiling", latex: String.raw`\lceil #0\rceil` },
  { t: "2×2 matrix", k: "matrix mat 2x2", latex: String.raw`\begin{pmatrix}#0 & #?\\ #? & #?\end{pmatrix}` },
  { t: "3×3 matrix", k: "matrix mat 3x3", latex: String.raw`\begin{pmatrix}#0 & #? & #?\\ #? & #? & #?\\ #? & #? & #?\end{pmatrix}` },
  { t: "Column vector", k: "vector column vec", latex: String.raw`\begin{pmatrix}#0\\ #?\\ #?\end{pmatrix}` },
  { t: "Determinant", k: "det determinant", latex: String.raw`\begin{vmatrix}#0 & #?\\ #? & #?\end{vmatrix}` },
  { t: "Transpose", k: "transpose", latex: String.raw`{#0}^{\top}` },
  { t: "Define function", k: "def define function fx", latex: String.raw`f\left(x\right)\coloneq #0` },
  { t: "Assign", k: "assign let set :=", latex: String.raw`#?\coloneq #0` },
  { t: "Solve", k: "solve equation", latex: String.raw`\operatorname{solve}\left(#0, #?\right)` },
  { t: "Expand", k: "expand", latex: String.raw`\operatorname{expand}\left(#0\right)` },
  { t: "Factor", k: "factor", latex: String.raw`\operatorname{factor}\left(#0\right)` },
  { t: "Simplify (rational)", k: "simplify ratsimp", latex: String.raw`\operatorname{ratsimp}\left(#0\right)` },
  { t: "Taylor series", k: "taylor series expansion", latex: String.raw`\operatorname{taylor}\left(#0, #?, #?, #?\right)` },
  { t: "sin", k: "sin sine trig", latex: String.raw`\sin\left(#0\right)` },
  { t: "cos", k: "cos cosine trig", latex: String.raw`\cos\left(#0\right)` },
  { t: "tan", k: "tan tangent trig", latex: String.raw`\tan\left(#0\right)` },
  { t: "Natural log", k: "ln log logarithm", latex: String.raw`\ln\left(#0\right)` },
  { t: "Log base b", k: "log logarithm base", latex: String.raw`\log_{#?}\left(#0\right)` },
  { t: "Exponential", k: "exp exponential e", latex: String.raw`\mathrm{e}^{#0}` },
  { t: "π", k: "pi", latex: String.raw`\pi` },
  { t: "∞", k: "inf infinity infty", latex: String.raw`\infty` },
  { t: "Imaginary unit", k: "imag i imaginary complex", latex: String.raw`\imaginaryI` },
  ...["alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda", "mu", "sigma", "phi", "omega",
      "Gamma", "Delta", "Theta", "Lambda", "Sigma", "Phi", "Omega"].map((g) => (
    { t: g, k: `${g.toLowerCase()} greek`, latex: `\\${g}` })),
];

export const CODE_TEMPLATES = [
  { t: "integrate", k: "integral int", code: "integrate(|, x)" },
  { t: "integrate (definite)", k: "integral int definite", code: "integrate(|, x, a, b)" },
  { t: "diff", k: "derivative", code: "diff(|, x)" },
  { t: "limit", k: "lim", code: "limit(|, x, 0)" },
  { t: "sum", k: "series sigma", code: "sum(|, k, 1, n)" },
  { t: "taylor", k: "series expansion", code: "taylor(|, x, 0, 5)" },
  { t: "solve", k: "equation", code: "solve(|, x)" },
  { t: "linsolve", k: "linear system", code: "linsolve([|], [x, y])" },
  { t: "find_root", k: "numeric root", code: "find_root(|, x, 0, 1)" },
  { t: "ode2", k: "ode differential equation", code: "ode2('diff(y, x) = |, y, x)" },
  { t: "desolve", k: "ode laplace", code: "desolve(|, y(x))" },
  { t: "expand", k: "", code: "expand(|)" },
  { t: "factor", k: "", code: "factor(|)" },
  { t: "ratsimp", k: "simplify rational", code: "ratsimp(|)" },
  { t: "trigsimp", k: "simplify trig", code: "trigsimp(|)" },
  { t: "subst", k: "substitute replace", code: "subst(x = |, expr)" },
  { t: "float / numer", k: "numeric evaluate", code: "float(|)" },
  { t: "matrix", k: "mat", code: "matrix([|, 0], [0, 1])" },
  { t: "eigenvectors", k: "eigen", code: "eigenvectors(|)" },
  { t: "determinant", k: "det", code: "determinant(|)" },
  { t: "makelist", k: "list sequence", code: "makelist(|, k, 1, 10)" },
  { t: "function definition", k: "define :=", code: "f(x) := |;" },
  { t: "for loop", k: "loop do", code: "for i: 1 thru 10 do (|);" },
  { t: "block", k: "local program", code: "block([a, b], |)" },
  { t: "iplot2d (inline plot)", k: "plot graph 2d", code: "iplot2d(|, [x, -5, 5]);" },
  { t: "iplot3d (inline 3D plot)", k: "plot surface 3d", code: "iplot3d(|, [x, -2, 2], [y, -2, 2]);" },
  { t: "idraw2d (inline draw)", k: "draw plot explicit", code: "idraw2d(explicit(|, x, -5, 5));" },
  { t: "load package", k: "load", code: "load(\"|\")$" },
];

export function searchTemplates(list, query) {
  const q = query.trim().toLowerCase();
  if (!q) return list.slice(0, 40);
  const scored = [];
  for (const item of list) {
    const title = item.t.toLowerCase();
    const words = (item.k + " " + title).split(/\s+/);
    let score = 0;
    if (title === q) score = 100;
    else if (words.some((w) => w === q)) score = 80;
    else if (words.some((w) => w.startsWith(q))) score = 60;
    else if (title.includes(q) || item.k.includes(q)) score = 30;
    if (score) scored.push([score, item]);
  }
  return scored.sort((a, b) => b[0] - a[0]).map(([, item]) => item);
}
