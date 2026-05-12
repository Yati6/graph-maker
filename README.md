# Recursion tree → TikZ / PDF

Small Python helpers and a **tkinter GUI** to draw a complete expansion tree (with optional row sums, brackets, and abbreviated bottom row), export **TikZ**, and compile **PDF** with `pdflatex`.

---

## Quick use (pick one)

### A. Run the GUI and type values

1. Install **MiKTeX** or **TeX Live** so `pdflatex` is on your `PATH`.
2. Use the **same** Python for the app and for packages (see `.vscode/settings.json` or run `run_graph_gui.ps1`).
3. Optional preview: `python -m pip install pymupdf pillow`
4. Start the app:
   - `python graph_gui.py`, or  
   - `.\run_graph_gui.ps1` (Windows)
5. Edit **func_row**, **func_sum**, **expansion**, **display_height**, optional labels / bottom row / PDF pixel bounds, then **Generate PDF**.  
   PDFs go to `gui_pdf_out/`. Use **Copy TikZ** or enable auto-copy after generate.
6. After pressing **Copy TikZ** you have the latex code for the graph, to use it in lyx press ctrl+L and in the box paste the code when processing the latex into a pdf it should be a graph.


### B. Copy a `graph:` line and run

1. In the GUI, click **Copy graph: line** (or build the string yourself).
2. Clipboard looks like:  
   `graph:` *then* seven `|`-separated fields (do **not** put extra `|` inside the LaTeX), same order as the form:

   | # | Field | What you paste |
   |---|--------|------------------|
   | 1 | **`func_row`** | LaTeX **math body** for each node on rows `0 … display_height−1` (no outer `$…$`; the app wraps it). Use `{row}` or `{r}` for the row index. Example: `n^{{row}}`, `x^{{r}}`. |
   | 2 | **`expansion`** | Integer branching factor (e.g. `2`). |
   | 3 | **`func_sum`** | LaTeX math body for the **right-hand sum column** on each row; same placeholders and `ev(...)` rules as `func_row`. Example: `\frac{n^{{row}}}{2^{{row}}}`, `\frac{n}{ev(2^{{2r}})}`. |
   | 4 | **height label** | Optional LaTeX for the left bracket annotation (or empty). Example: `O(\log n)`. |
   | 5 | **width label** | Optional LaTeX for the bottom bracket (or empty). Example: `O(n)`. |
   | 6 | **`bottom_value`** | LaTeX for each **drawn leaf** token (often `1`). |
   | 7 | **`bottom_sum`** | LaTeX for the sum aligned with the leaf row (or empty to reuse `func_sum` at the leaf depth). |
   | 8 | *(optional)* **`display_height`** | Number of full tree rows before `\vdots` / leaves. |
   | 9 | *(optional)* PDF **max height** (px, 96 dpi) | Scales the figure when compiling. |
   | 10 | *(optional)* PDF **max width** (px) | Scales the figure when compiling. |

3. **Example** — copy this entire line to the clipboard, then **start the GUI** (autoload fills the form, builds a PDF, and can open it):

   ```
   graph:\frac{n}{ev(2^{2r})}|3|n^{2}|O(logn)|O(n)|1|n^{2}
   ```
make sure to not copy the math block itself and only the contants starting with graph:

**Programmatic use:** `make_graph_from_latex_spec(...)` and `make_graph_from_delimited_latex(spec)` in `make_graph.py` — the latter returns `(tikz, pdf_size_dict)` for `write_tikz_pdf(..., **pdf_size_dict)`.

---

## LaTeX templates: `{row}`, `{r}`, and `ev(...)`

- **`{row}`** and **`{r}`** in `func_row` / `func_sum` / bottom fields are replaced by the **current row index** (same value; pick one style).
- In Python strings you often write **`{{row}}`** so the final LaTeX shows `{row}`; the same doubled braces work **inside** `ev(...)` powers (e.g. `ev(2^{{row}})`).

### `ev(...)` (numeric snippets only)

Inside templates, `ev(…)` is evaluated **per row** before `{row}`/`{r}` substitution. It is **not** full LaTeX—only a tiny calculator.

Supported forms:

| Form | Meaning (current row = `row`) |
|------|-------------------------------|
| `row` or `r` | Row index |
| `row*k`, `r*k`, `k*row`, `k*r` | Multiply / divide row by an integer |
| `row/k`, `r/k` | Integer divide when exact, else a short decimal |
| `p/q` | Integer division or decimal |
| plain integer | e.g. `ev(1)` → `1` (pairs with cleanup below) |
| `a^{exponent}` | Integer power; exponent can be digits, `row` / `r`, `kr` / `k r` / `krow` (meaning `k × row`), or `k*row`-style |

Examples: `ev(2^{{row}})` → `2^row`; `ev(2^{{2r}})` → `2^(2*row)`; `\frac{n}{ev(2^{{2r}})}` for a decaying denominator. After substitution, the pipeline removes `\frac{·}{1}`, turns `x^{0}` / `x^0` (single-letter base) into `1`, unwraps `(n)^{2}` → `n^{2}`, and strips redundant `*1`, `\cdot 1`, `/1`, etc. (e.g. `n * ev(1)` → `n`, `\frac{n}{ev(1)}` → `n`).

---

## Credits

**All credit To - Itay Levy**

Email: itay3.8.2010@gmail.com

---

## Requirements

- Python 3.10+ (typical)
- `pdflatex`
- Optional: `pymupdf`, `pillow` (inline PDF preview in the GUI)
