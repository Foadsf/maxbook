# Math cells: what the formula means to Maxima

A math cell is edited visually. Before it runs, Maxbook translates the formula to one Maxima statement and shows that statement under the formula. The rules below are the whole contract: anything not covered is reported as an error with a hint rather than guessed.

## Names, constants, indices

| You write | Maxima | Note |
|---|---|---|
| `x`, `\alpha`, `\Omega` | `x`, `alpha`, `Omega` | Greek letters become their names |
| `xy`, `2x` | `x*y`, `2*x` | adjacent symbols multiply |
| `\pi` | `%pi` | |
| `e`, `\mathrm{e}` | `%e` | Euler's number |
| `\imaginaryI`, `\mathrm{i}` | `%i` | a plain `i` stays a variable (summation index) |
| `\infty`, `-\infty` | `inf`, `minf` | |
| `x_{1}`, `a_{i,j}` | `x[1]`, `a[i, j]` | subscripts are indices |
| `\operatorname{name}`, `\mathrm{name}` | `name` | multi-letter names |
| `\text{abc}` | `"abc"` | a string |
| `90^{\circ}` | `90*%pi/180` | degrees |

## Functions

- Built-ins written as LaTeX commands: `\sin x` → `sin(x)`, `\sin 2x` → `sin(2*x)`, `\sin x\cos x` → `sin(x)*cos(x)`, `\sin^2 x` → `sin(x)^2`, `\sin^{-1}x` → `asin(x)`, `\ln x` → `log(x)`, `\log_{b}x` → `log(x)/log(b)`, `\det(A)` → `determinant(A)`.
- Maxima commands typed letter by letter are recognised before a parenthesis: `solve(x^2=2, x)`, `factor(...)`, `expand(...)`, `ratsimp(...)`, `taylor(...)` and the other common Maxima functions.
- `f(x)` is a call when `f` is a known function: `f`, `g`, `h`, `F`, `G`, `H`, anything defined with `name(...) :=` anywhere in the notebook, or a built-in. Otherwise `u(t)` means `u*(t)`, and a call with several arguments to an unknown name is an error asking you to define it or write `\operatorname{u}`.

## Calculus

| You write | Maxima |
|---|---|
| `\int f\,dx`, `\int f\,\mathrm{d}x` | `integrate(f, x)` |
| `\int_{a}^{b} f\,dx` | `integrate(f, x, a, b)` |
| `\int_0^1\int_0^1 xy\,dx\,dy` | nested `integrate` |
| `\sum_{k=1}^{n} f`, `\prod_{k=1}^{n} f` | `sum(f, k, 1, n)`, `product(f, k, 1, n)` |
| `\lim_{x\to a} f`, `\lim_{x\to0^{+}} f` | `limit(f, x, a)`, `limit(f, x, 0, plus)` |
| `\frac{d}{dx} f`, `\frac{d^2}{dx^2} f`, `\frac{dy}{dx}` | `diff(f, x)`, `diff(f, x, 2)`, `diff(y, x)` |
| `\frac{\partial^2 f}{\partial x\,\partial y}` | `diff(f, x, 1, y, 1)` |

The body of a sum, product or limit is the product that follows it, up to the next `+` or `-`: `\sum_{i=1}^{n} i + 1` is `sum(i, i, 1, n) + 1`. An integral needs its differential (`dx`).

## Linear algebra

| You write | Maxima |
|---|---|
| `\begin{pmatrix}1&2\\3&4\end{pmatrix}` (also `bmatrix`, `matrix`) | `matrix([1, 2], [3, 4])` |
| `\begin{vmatrix}…\end{vmatrix}` | `determinant(matrix(…))` |
| matrix `\cdot` matrix, or two matrices side by side | `.` (matrix product) |
| `M^{-1}` on a written-out matrix | `M^^(-1)` (inverse) |
| `M^{T}`, `M^{\top}`, `A^T` for a capital single letter | `transpose(…)` |

For named matrices use a Maxima cell for products (`A . B`) and inverses (`A^^-1`); in a math cell `A\cdot B` means `A*B`, which Maxima applies element-wise.

## Equations and definitions

| You write | Maxima |
|---|---|
| `x^2+1=0`, `\le`, `\ge`, `\ne` | `=`, `<=`, `>=`, `#` |
| `a \coloneq 5` or `a := 5` | `a: 5` |
| `f(x) \coloneq x^2` | `f(x) := x^2` |

## Not supported (yet)

`\pm`, `\nabla`, contour integrals, primes (`f'`), norms `\|x\|`, `cases` environments and evaluation bars. Use a Maxima cell for these.
