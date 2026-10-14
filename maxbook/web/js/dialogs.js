// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Command menus with small dialogs that write Maxima code for common tasks,
// for people who would rather fill in a form than remember syntax.

const f = (k, label, def = "", opt = false) => ({ k, label, def, opt });
const EXPR = f("expr", "Expression", "%");
const VAR = f("var", "Variable", "x");

export const MENUS = [
  { title: "Equations", items: [
    { t: "Solve", fields: [f("eq", "Equation(s)", "%"), f("var", "Unknown(s)", "x")],
      code: (v) => `solve(${v.eq}, ${v.var});` },
    { t: "Solve numerically", fields: [f("eq", "Equation or expression", "%"), VAR, f("a", "From", "0"), f("b", "To", "1")],
      code: (v) => `find_root(${v.eq}, ${v.var}, ${v.a}, ${v.b});` },
    { t: "Linear system", fields: [f("eqs", "Equations (comma separated)", "x + y = 1, x - y = 3"), f("vars", "Unknowns", "x, y")],
      code: (v) => `linsolve([${v.eqs}], [${v.vars}]);` },
    { t: "Polynomial roots (numeric)", fields: [EXPR], code: (v) => `allroots(${v.expr});` },
    { t: "Ordinary differential equation", fields: [f("eq", "Equation", "'diff(y, x) = x*y"), f("dep", "Unknown function", "y"), f("ind", "Variable", "x")],
      code: (v) => `ode2(${v.eq}, ${v.dep}, ${v.ind});` },
    { t: "Initial condition (1st order)", fields: [f("sol", "General solution", "%"), f("x0", "At", "x = 0"), f("y0", "Value", "y = 1")],
      code: (v) => `ic1(${v.sol}, ${v.x0}, ${v.y0});` },
    { t: "Initial conditions (2nd order)", fields: [f("sol", "General solution", "%"), f("x0", "At", "x = 0"), f("y0", "Value", "y = 1"), f("dy0", "Slope", "'diff(y, x) = 0")],
      code: (v) => `ic2(${v.sol}, ${v.x0}, ${v.y0}, ${v.dy0});` },
  ] },
  { title: "Algebra", items: [
    { t: "Simplify (rational)", fields: [EXPR], code: (v) => `ratsimp(${v.expr});` },
    { t: "Expand", fields: [EXPR], code: (v) => `expand(${v.expr});` },
    { t: "Factor", fields: [EXPR], code: (v) => `factor(${v.expr});` },
    { t: "Partial fractions", fields: [EXPR, VAR], code: (v) => `partfrac(${v.expr}, ${v.var});` },
    { t: "Substitute", fields: [EXPR, f("var", "Replace", "x"), f("val", "With", "0")],
      code: (v) => `subst(${v.var} = ${v.val}, ${v.expr});` },
    { t: "Simplify trigonometry", fields: [EXPR], code: (v) => `trigsimp(${v.expr});` },
    { t: "Expand trigonometry", fields: [EXPR], code: (v) => `trigexpand(${v.expr});` },
    { t: "Reduce trigonometry", fields: [EXPR], code: (v) => `trigreduce(${v.expr});` },
    { t: "Rectangular form a + b i", fields: [EXPR], code: (v) => `rectform(${v.expr});` },
    { t: "Polar form r e^{iφ}", fields: [EXPR], code: (v) => `polarform(${v.expr});` },
    { t: "Numerical value", fields: [EXPR, f("digits", "Digits (blank: machine float)", "", true)],
      code: (v) => (v.digits ? `fpprec: ${v.digits}$ bfloat(${v.expr});` : `float(${v.expr});`) },
  ] },
  { title: "Calculus", items: [
    { t: "Integrate", fields: [EXPR, VAR, f("a", "From (blank: indefinite)", "", true), f("b", "To", "", true)],
      code: (v) => (v.a && v.b ? `integrate(${v.expr}, ${v.var}, ${v.a}, ${v.b});` : `integrate(${v.expr}, ${v.var});`) },
    { t: "Differentiate", fields: [EXPR, VAR, f("n", "Order", "1")],
      code: (v) => (v.n && v.n !== "1" ? `diff(${v.expr}, ${v.var}, ${v.n});` : `diff(${v.expr}, ${v.var});`) },
    { t: "Limit", fields: [EXPR, VAR, f("a", "Approaches", "0"), f("dir", "Side (plus, minus or blank)", "", true)],
      code: (v) => `limit(${v.expr}, ${v.var}, ${v.a}${v.dir ? ", " + v.dir : ""});` },
    { t: "Taylor series", fields: [EXPR, VAR, f("a", "Around", "0"), f("n", "Order", "5")],
      code: (v) => `taylor(${v.expr}, ${v.var}, ${v.a}, ${v.n});` },
    { t: "Sum", fields: [EXPR, f("k", "Index", "k"), f("a", "From", "1"), f("b", "To", "n")],
      code: (v) => `sum(${v.expr}, ${v.k}, ${v.a}, ${v.b}), simpsum;` },
    { t: "Product", fields: [EXPR, f("k", "Index", "k"), f("a", "From", "1"), f("b", "To", "n")],
      code: (v) => `product(${v.expr}, ${v.k}, ${v.a}, ${v.b});` },
    { t: "Laplace transform", fields: [EXPR, f("t", "Time variable", "t"), f("s", "Transform variable", "s")],
      code: (v) => `laplace(${v.expr}, ${v.t}, ${v.s});` },
    { t: "Inverse Laplace transform", fields: [EXPR, f("s", "Transform variable", "s"), f("t", "Time variable", "t")],
      code: (v) => `ilt(${v.expr}, ${v.s}, ${v.t});` },
  ] },
  { title: "Matrix", items: [
    { t: "New matrix", fields: [f("name", "Name", "A"), f("r", "Rows", "2"), f("c", "Columns", "2")],
      code: (v) => {
        const r = Math.max(1, Math.min(12, +v.r || 2));
        const c = Math.max(1, Math.min(12, +v.c || 2));
        const rows = Array.from({ length: r }, (_, i) => `[${Array.from({ length: c }, (_, j) => (i === j ? 1 : 0)).join(", ")}]`);
        return `${v.name}: matrix(${rows.join(", ")});`;
      } },
    { t: "Determinant", fields: [f("m", "Matrix", "A")], code: (v) => `determinant(${v.m});` },
    { t: "Inverse", fields: [f("m", "Matrix", "A")], code: (v) => `${v.m}^^-1;` },
    { t: "Transpose", fields: [f("m", "Matrix", "A")], code: (v) => `transpose(${v.m});` },
    { t: "Eigenvalues", fields: [f("m", "Matrix", "A")], code: (v) => `eigenvalues(${v.m});` },
    { t: "Eigenvectors", fields: [f("m", "Matrix", "A")], code: (v) => `eigenvectors(${v.m});` },
    { t: "Rank", fields: [f("m", "Matrix", "A")], code: (v) => `rank(${v.m});` },
    { t: "Characteristic polynomial", fields: [f("m", "Matrix", "A"), f("x", "Variable", "lambda")],
      code: (v) => `expand(charpoly(${v.m}, ${v.x}));` },
  ] },
  { title: "Plot", items: [
    { t: "Plot 2D", fields: [f("expr", "Expression(s), comma separated", "sin(x)"), VAR, f("a", "From", "-5"), f("b", "To", "5")],
      code: (v) => `iplot2d(${v.expr.includes(",") ? `[${v.expr}]` : v.expr}, [${v.var}, ${v.a}, ${v.b}])$` },
    { t: "Parametric curve", fields: [f("x", "x(t)", "cos(t)"), f("y", "y(t)", "sin(2*t)"), f("t", "Parameter", "t"), f("a", "From", "0"), f("b", "To", "2*%pi")],
      code: (v) => `iplot2d([parametric, ${v.x}, ${v.y}, [${v.t}, ${v.a}, ${v.b}]])$` },
    { t: "Implicit curve", fields: [f("eq", "Equation", "x^2 + y^2 = 1"), f("xr", "x range", "-2, 2"), f("yr", "y range", "-2, 2")],
      code: (v) => `idraw2d(implicit(${v.eq}, x, ${v.xr}, y, ${v.yr}))$` },
    { t: "Surface 3D", fields: [f("expr", "Expression", "sin(x)*cos(y)"), f("x", "x range", "x, -3, 3"), f("y", "y range", "y, -3, 3")],
      code: (v) => `iplot3d(${v.expr}, [${v.x}], [${v.y}])$` },
    { t: "Data points", fields: [f("pts", "Points [x, y], comma separated", "[0, 0], [1, 1], [2, 4], [3, 9]")],
      code: (v) => `iplot2d([discrete, [${v.pts}]], [style, points])$` },
  ] },
];

/** Build the dialog body; returns {node, value()} where value() gives the Maxima code or null. */
export function dialogForm(item, el) {
  const inputs = {};
  const preview = el("pre", { class: "dlg-preview" });
  const rows = item.fields.map((fd) => {
    const input = el("input", { type: "text", value: fd.def, "aria-label": fd.label, spellcheck: "false" });
    inputs[fd.k] = input;
    input.addEventListener("input", update);
    return el("label", { class: "dlg-row" }, el("span", { text: fd.label }), input);
  });
  function values() {
    const v = {};
    for (const fd of item.fields) v[fd.k] = inputs[fd.k].value.trim();
    return v;
  }
  function value() {
    const v = values();
    if (item.fields.some((fd) => !fd.opt && !v[fd.k])) return null;
    return item.code(v);
  }
  function update() {
    const code = value();
    preview.textContent = code || "Fill in every field that is not marked optional.";
    preview.classList.toggle("muted", !code);
  }
  update();
  return { node: el("div", { class: "dlg-form" }, ...rows, el("div", { class: "dlg-label", text: "Maxima" }), preview),
           value, first: () => inputs[item.fields[0].k] };
}
