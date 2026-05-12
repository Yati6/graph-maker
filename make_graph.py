r"""
Build TikZ for a complete expansion-ary tree with optional vertical compression.

Rows are ``0 .. display_height - 1`` are drawn in full. The conceptual leaf row
(level ``display_height``) has ``expansion ** display_height`` leaves; layout and
brackets use that width. With at least three conceptual leaves, the bottom row
is drawn as ``s`` leaves, ``$\\cdots$``, then ``s`` more (``1 \\cdots 1`` style),
where ``s`` comes from ``leaf_row_side_nodes`` or, when that is ``None``, from a
default cap of ``1.5 × expansion^{display_height - 1}`` (the node count one row
above the leaf row), and ``s`` is also capped so the drawn bottom row does not
use more tokens per side than that parent row (``expansion^{display_height-1}`` nodes).
Bottom-row nodes may use a smaller ``bottom_row_font`` (default ``\\tiny``).
With one or two conceptual leaves, every leaf is drawn with no middle dots.

A centered ``$\\vdots$`` separates the last prefix row from the leaf row (no
edges across that gap). Use :func:`expression_from_latex` for per-row LaTeX
templates using the ``{row}`` or ``{r}`` placeholder and small ``ev(...)`` helpers
(``row*k``, ``k*row``, ``r*k``, ``k*r``, ``row/k``, ``p/q``, and powers ``a^{exponent}`` where
``exponent`` can be digits, ``row`` or ``r`` (same row index), ``kr`` / ``k r`` or ``krow``
for ``k*row``, or ``k*row`` / ``row*k`` / ``k*r`` / ``r*k``).

Use :func:`write_tikz_pdf` / :func:`export_make_graph_pdf` to emit PDFs (optional
``max_width_px`` / ``max_height_px`` scale the page via ``adjustbox``).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _format_ev_val(v: float | int) -> str:
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        v = int(round(v))
    if isinstance(v, int):
        return str(v)
    return f"{v:.6g}"


def _substitute_row_placeholders(s: str, row_idx: int, *, alt_placeholder: str = "{row}") -> str:
    """Replace ``{row}``, ``{r}``, and optionally a custom ``alt_placeholder`` with ``row_idx``."""
    t = s.replace("{row}", str(row_idx)).replace("{r}", str(row_idx))
    if alt_placeholder not in ("{row}", "{r}") and alt_placeholder in t:
        t = t.replace(alt_placeholder, str(row_idx))
    return t


def _unwrap_latex_brace_groups(fragment: str) -> str:
    """Strip redundant outer ``{...}`` wrappers (``{{row}}`` → ``row``)."""
    t = fragment.strip()
    while len(t) >= 2 and t[0] == "{" and t[-1] == "}":
        t = t[1:-1].strip()
    return t


def _tex_brace_group(s: str, open_idx: int) -> tuple[str, int] | None:
    """
    If ``s[open_idx] == '{'``, return ``(inner, index_after_closing_brace)``.
    ``inner`` is the substring between the matching outer braces (may contain ``{`` / ``}``).
    """
    if open_idx >= len(s) or s[open_idx] != "{":
        return None
    depth = 0
    for j in range(open_idx, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1 : j], j + 1
    return None


def _try_parse_ev_latex_power(s: str) -> tuple[int, str] | None:
    """
    If ``s`` is ``base^{...}`` with balanced braces after ``^``, return ``(base, exponent_raw)``.
    Otherwise return ``None``. Ignores trailing whitespace only.
    """
    t = s.strip()
    m = re.match(r"(\d+)\s*\^\s*", t)
    if not m:
        return None
    base = int(m.group(1))
    j = m.end()
    got = _tex_brace_group(t, j)
    if got is None:
        return None
    exp_raw, end = got
    if t[end:].strip():
        return None
    return base, exp_raw


def _latex_exponent_to_int(exp: str, row: int) -> int:
    """
    Parse the inside of LaTeX ``^{...}`` for ``ev(a^{...})``.

    Accepts: ``row`` or ``r`` (alias of the row index), a non-negative integer, ``kr`` /
    ``k r`` / ``krow`` meaning ``k * row``, and ``k*row`` / ``row*k`` / ``k*r`` / ``r*k``
    with integer ``k``.
    ``{{row}}`` / ``{{r}}`` (extra brace layer for LaTeX output) normalize to ``row`` / ``r``.
    """
    e = _unwrap_latex_brace_groups(exp)
    if not e:
        raise ValueError("empty exponent inside ^{...}")
    if e == "row" or e == "r":
        return row
    if re.fullmatch(r"\d+", e):
        return int(e)
    m = re.fullmatch(r"(\d+)\s*\*\s*(?:row|r)", e)
    if m:
        return int(m.group(1)) * row
    m = re.fullmatch(r"(?:row|r)\s*\*\s*(\d+)", e)
    if m:
        return row * int(m.group(1))
    m = re.fullmatch(r"(\d+)\s*r\s*", e)
    if m:
        return int(m.group(1)) * row
    m = re.fullmatch(r"(\d+)\s*row\s*", e)
    if m:
        return int(m.group(1)) * row
    raise ValueError(
        f"exponent {exp!r} not understood (use row, r, digits, kr, krow, k*row, row*k, k*r, r*k)"
    )


def _eval_ev_inner(inner: str, row: int) -> str:
    """
    Small ``ev(...)`` language:

    - ``row`` or ``r`` (row index), ``row*k`` / ``r*k``, ``k*row`` / ``k*r``, ``row/k`` / ``r/k``
      (``k`` a non-negative integer).
    - ``p/q`` (integer division when exact, else decimal).
    - ``a^{exponent}`` — LaTeX-style power; ``exponent`` is parsed by
      :func:`_latex_exponent_to_int` (``2^{{row}}``, ``2^{{2r}}``, ``2^{{2row}}`` all work).
    """
    s = inner.strip()

    if re.fullmatch(r"row|r", s):
        return str(row)

    m = re.fullmatch(r"(?:row|r)\s*\*\s*(\d+)", s)
    if m:
        return str(row * int(m.group(1)))

    m = re.fullmatch(r"(\d+)\s*\*\s*(?:row|r)", s)
    if m:
        return str(row * int(m.group(1)))

    m = re.fullmatch(r"(?:row|r)\s*/\s*(\d+)", s)
    if m:
        d = int(m.group(1))
        if d == 0:
            raise ZeroDivisionError("ev(row/0)")
        if row % d == 0:
            return str(row // d)
        return _format_ev_val(row / d)

    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b == 0:
            raise ZeroDivisionError("ev(…/0)")
        if a % b == 0:
            return str(a // b)
        return _format_ev_val(a / b)

    pow_parts = _try_parse_ev_latex_power(s)
    if pow_parts is not None:
        base, exp_raw = pow_parts
        exp_i = _latex_exponent_to_int(exp_raw, row)
        return str(int(base) ** int(exp_i))

    raise ValueError(
        "ev(...) only supports: row, r, row*k, k*row, row/k, p/q, or a^{exponent} "
        f"(LaTeX exponent: row, r, digits, kr, krow, k*row, …) — got {inner!r}"
    )


def substitute_ev(template: str, row: int) -> str:
    """Replace each balanced ``ev(...)`` using :func:`_eval_ev_inner`."""
    out: list[str] = []
    i = 0
    while True:
        j = template.find("ev(", i)
        if j == -1:
            out.append(template[i:])
            break
        out.append(template[i:j])
        start = j + 3
        depth = 1
        k = start
        while k < len(template):
            if template[k] == "(":
                depth += 1
            elif template[k] == ")":
                depth -= 1
                if depth == 0:
                    inner = template[start:k].strip()
                    out.append(_eval_ev_inner(inner, row))
                    i = k + 1
                    break
            k += 1
        else:
            raise ValueError("unclosed ev(")
    return "".join(out)


def expression_from_latex(template: str, *, placeholder: str = "{row}") -> Callable[[int], str]:
    """
    Build ``row ->`` LaTeX math *body* from a template string.

    **``ev(...)``** only understands:

    - ``row`` or ``r``, ``row*k`` / ``r*k``, ``k*row`` / ``k*r``, ``row/k`` / ``r/k`` (``k`` integer),
    - ``p/q`` (integer division when exact, else a short decimal),
    - ``a^{exponent}`` — LaTeX power: ``exponent`` may be digits, ``row`` or ``r``,
      ``kr`` / ``k r`` / ``krow`` meaning ``k*row``, or ``k*row`` / ``row*k`` / ``k*r`` / ``r*k``.
      Use the same doubled braces as elsewhere (``2^{{row}}``) so ``^{{...}}`` parses correctly.

    **``{row}``** and **``{r}``** are then replaced by the row index string.

    Example: ``r"n^{ev(2^{row})}"`` or ``r"n^{ev(2^{{row}})}"`` → ``n^{1}``, ``n^{2}``, ``n^{4}``, …
    For ``\frac{n}{ev(2^{2r})}`` or ``ev(2^{2row})``, the exponent is read as ``2*row``.
    """
    needs_subst = "{row}" in template or "{r}" in template or placeholder in template

    if needs_subst:

        def f(row: int) -> str:
            t = substitute_ev(template, row)
            return _substitute_row_placeholders(t, row, alt_placeholder=placeholder)

        return f

    def const_row(row: int) -> str:
        return substitute_ev(template, row)

    return const_row


def _node_name(row: int, index: int) -> str:
    return f"n{row}x{index}"


def _leaf_depth(display_height: int) -> int:
    """Row index used for leaf-aligned coordinates (one past last drawn row)."""
    return display_height


def _x_center(row: int, index: int, expansion: int, leaf_depth: int, unit: float) -> float:
    n_leaves = expansion**leaf_depth
    span = expansion ** (leaf_depth - row)
    lo = index * span
    hi = (index + 1) * span - 1
    return (lo + hi - (n_leaves - 1)) / 2.0 * unit


def _tree_x_bounds(
    expansion: int,
    display_height: int,
    x_unit: float,
) -> tuple[float, float]:
    d = _leaf_depth(display_height)
    xs: list[float] = []
    for r in range(display_height):
        for i in range(expansion**r):
            xs.append(_x_center(r, i, expansion, d, x_unit))
    for i in range(expansion**d):
        xs.append(_x_center(d, i, expansion, d, x_unit))
    return min(xs), max(xs)


def _default_max_bottom_nodes(expansion: int, display_height: int) -> int:
    """Cap on drawn bottom-row symbols: ``1.5 ×`` nodes in the row above the leaf row."""
    if display_height < 1:
        return 3
    parent_m = expansion ** (display_height - 1)
    return max(3, int(round(1.5 * parent_m)))


def _auto_leaf_sides(n: int, max_bottom_nodes: int) -> int:
    """Largest ``sides`` so that ``2*sides + 1 <= max_bottom_nodes`` when abbreviated."""
    cap = max(3, max_bottom_nodes)
    if n <= cap:
        return n
    return max(1, (cap - 1) // 2)


def _leaf_row_layout(
    expansion: int,
    display_height: int,
    x_unit: float,
    leaf_row_side_nodes: int | None,
    max_bottom_nodes: int,
) -> tuple[list[int], list[int] | None, float]:
    """
    Return ``(left_indices, right_indices_or_none, x_cdots)``.

    If not abbreviated, ``right_indices_or_none`` is ``None`` and ``left_indices``
    is ``0 .. n-1``. Otherwise ``left`` / ``right`` blocks and ``x_cdots`` for
    horizontal ``$\\cdots$`` between them.

    When ``n >= 3``, a middle ``$\\cdots$`` is always used (``1 \\cdots 1`` style):
    the effective ``sides`` count is capped so ``2 * sides < n``.
    """
    d = _leaf_depth(display_height)
    n = expansion**d
    sides = (
        leaf_row_side_nodes
        if leaf_row_side_nodes is not None
        else _auto_leaf_sides(n, max_bottom_nodes)
    )
    sides = max(1, min(sides, n))
    if n < 3:
        return list(range(n)), None, 0.0
    if display_height >= 1:
        parent_m = expansion ** (display_height - 1)
        max_sides_by_parent = max(1, (parent_m - 1) // 2)
        sides = min(sides, max_sides_by_parent)
    sides = min(sides, (n - 1) // 2)
    while sides > 1 and 2 * sides >= n:
        sides -= 1
    if n <= 2 * sides:
        return list(range(n)), None, 0.0
    left = list(range(sides))
    right = list(range(n - sides, n))
    x_ll = _x_center(d, sides - 1, expansion, d, x_unit)
    x_fr = _x_center(d, n - sides, expansion, d, x_unit)
    x_mid = (x_ll + x_fr) / 2.0
    return left, right, x_mid


def latex_document_from_tikz(
    tikz_fragment: str,
    *,
    border: str = "12pt",
    max_width_px: float | None = None,
    max_height_px: float | None = None,
) -> str:
    """
    Wrap a TikZ picture fragment in a minimal standalone LaTeX document.

    When ``max_width_px`` and/or ``max_height_px`` are set (positive), the picture
    is wrapped in an ``adjustbox`` environment using CSS‑style pixels at 96 dpi (``px × 72/96`` pt).
    Both may be set together with ``keepaspectratio`` so the figure fits inside the box.
    """
    px_to_pt = 72.0 / 96.0
    w_pt = (
        max_width_px * px_to_pt
        if max_width_px is not None and max_width_px > 0
        else None
    )
    h_pt = (
        max_height_px * px_to_pt
        if max_height_px is not None and max_height_px > 0
        else None
    )
    core = tikz_fragment.rstrip() + "\n"
    use_box = w_pt is not None or h_pt is not None
    if use_box:
        opts: list[str] = []
        if w_pt is not None:
            opts.append(f"width={w_pt:.4f}pt")
        if h_pt is not None:
            opts.append(f"height={h_pt:.4f}pt")
        opts.append("keepaspectratio")
        opts.append("center")
        opts_str = ",".join(opts)
        body = "\\begin{adjustbox}{" + opts_str + "}\n" + core + "\\end{adjustbox}\n"
    else:
        body = core

    lines = [
        rf"\documentclass[border={border}]{{standalone}}",
        r"\usepackage{tikz}",
        r"\usepackage{amsmath}",
    ]
    if use_box:
        lines.append(r"\usepackage{adjustbox}")
    lines.append(r"\begin{document}")
    lines.append(body.rstrip())
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def write_tikz_pdf(
    output: str | Path,
    tikz_fragment: str,
    *,
    border: str = "12pt",
    max_width_px: float | None = None,
    max_height_px: float | None = None,
    compiler: str = "pdflatex",
    cleanup_aux: bool = True,
) -> Path:
    """
    Write ``output`` as ``.tex`` (standalone + TikZ) and compile to PDF.

    ``output`` may be a path ending in ``.tex``, ``.pdf``, or a stem without
    suffix (then ``stem.tex`` / ``stem.pdf`` are used).

    Optional ``max_width_px`` / ``max_height_px`` (96 dpi CSS pixels) wrap the
    picture in ``adjustbox`` so the PDF page fits those bounds.

    Returns the path to the generated PDF. Raises ``FileNotFoundError`` if
    ``compiler`` is not on ``PATH``, and ``RuntimeError`` if LaTeX fails.
    """
    out = Path(output)
    if out.suffix.lower() == ".pdf":
        tex_path = out.with_suffix(".tex")
        pdf_path = out
    elif out.suffix.lower() == ".tex":
        tex_path = out
        pdf_path = out.with_suffix(".pdf")
    else:
        tex_path = out.with_suffix(".tex")
        pdf_path = out.with_suffix(".pdf")

    tex_path.parent.mkdir(parents=True, exist_ok=True)
    body = latex_document_from_tikz(
        tikz_fragment,
        border=border,
        max_width_px=max_width_px,
        max_height_px=max_height_px,
    )
    tex_path.write_text(body, encoding="utf-8")

    exe = shutil.which(compiler)
    if exe is None:
        raise FileNotFoundError(
            f"LaTeX compiler {compiler!r} not found on PATH; install TeX Live or MiKTeX."
        )

    workdir = tex_path.parent.resolve()
    args = [
        exe,
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={workdir}",
        tex_path.name,
    ]
    proc = subprocess.run(
        args,
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        log_path = tex_path.with_suffix(".log")
        tail = ""
        if log_path.is_file():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-40:])
        msg = f"{compiler} failed with exit code {proc.returncode}."
        if proc.stderr.strip():
            msg += f"\n--- stderr ---\n{proc.stderr.strip()}"
        if tail:
            msg += f"\n--- log tail ---\n{tail}"
        low = (tail + (proc.stderr or "")).lower()
        if "can't write on file" in low or "cannot write on file" in low:
            msg += (
                "\n\n(Hint: the output PDF is probably open in another program; "
                "close it or use a new output path, then compile again.)"
            )
        raise RuntimeError(msg)

    if not pdf_path.is_file():
        raise RuntimeError(f"Expected PDF at {pdf_path} after successful {compiler} run.")

    if cleanup_aux:
        stem = tex_path.with_suffix("")
        for suffix in (".aux", ".log", ".out", ".synctex.gz"):
            p = stem.with_suffix(suffix)
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass

    return pdf_path.resolve()


def export_make_graph_pdf(
    output: str | Path,
    graph_fn: Callable[[int], str],
    expansion: int,
    display_height: int,
    *,
    border: str = "12pt",
    max_width_px: float | None = None,
    max_height_px: float | None = None,
    compiler: str = "pdflatex",
    cleanup_aux: bool = True,
    **make_graph_kw: Any,
) -> Path:
    """
    Call :func:`makeGraph`, write a ``.tex`` file, and compile to PDF.

    Extra keyword arguments are forwarded to :func:`makeGraph`.
    """
    tikz = makeGraph(graph_fn, expansion, display_height, **make_graph_kw)
    return write_tikz_pdf(
        output,
        tikz,
        border=border,
        max_width_px=max_width_px,
        max_height_px=max_height_px,
        compiler=compiler,
        cleanup_aux=cleanup_aux,
    )


def make_graph_from_latex_spec(
    func_row: str,
    expansion: int,
    func_sum: str,
    height: str | None,
    width: str | None,
    bottom_value: str = "1",
    bottom_sum: str = "",
    *,
    display_height: int = 3,
    placeholder: str = "{row}",
    **make_graph_kw: Any,
) -> str:
    """
    Convenience wrapper: build ``graph_fn`` / ``row_sum_fn`` via
    :func:`expression_from_latex`, then return :func:`makeGraph` TikZ.

    ``func_row`` / ``func_sum`` are LaTeX math bodies with ``{row}`` or ``{r}`` for the row
    index (``0 .. display_height - 1``). ``bottom_sum`` overrides the leaf-row
    sum on the right; if empty, ``func_sum`` is evaluated at ``row ==
    display_height``.
    """
    graph_fn = expression_from_latex(func_row, placeholder=placeholder)
    sum_fn_base = expression_from_latex(func_sum, placeholder=placeholder)
    d = display_height

    def row_sum_fn(r: int) -> str:
        if r == d and bottom_sum.strip() != "":
            t = substitute_ev(bottom_sum, r)
            return _substitute_row_placeholders(t, r, alt_placeholder=placeholder)
        return sum_fn_base(r)

    return makeGraph(
        graph_fn,
        expansion,
        display_height,
        height_label=height,
        width_label=width,
        row_sum_fn=row_sum_fn,
        bottom_value=bottom_value,
        **make_graph_kw,
    )


def make_graph_from_delimited_latex(
    spec: str,
    *,
    delimiter: str = "|",
    display_height: int = 3,
    placeholder: str = "{row}",
    **make_graph_kw: Any,
) -> tuple[str, dict[str, float]]:
    """
    Parse ``spec`` as ``|``-separated fields (at least seven)::

        func_row | expansion | func_sum | height | width | bottom_value | bottom_sum
        [| display_height [| max_height_px [| max_width_px]]]

    Empty ``height`` / ``width`` become ``None``. ``expansion`` must be a decimal
    integer. Optional 8th field overrides ``display_height``; optional 9th and
    10th set maximum figure height and width in **pixels** (96 dpi), passed to
    :func:`write_tikz_pdf` / :func:`latex_document_from_tikz` via ``adjustbox``.

    Returns ``(tikz_fragment, pdf_size_kw)`` where ``pdf_size_kw`` may contain
    ``max_height_px`` and/or ``max_width_px`` for :func:`write_tikz_pdf`.
    """
    parts = [p.strip() for p in spec.split(delimiter)]
    if len(parts) < 7:
        raise ValueError(
            f"expected at least 7 fields separated by {delimiter!r}, got {len(parts)}: {spec!r}"
        )
    fr, ex, fs, h, w, bv, bs = parts[:7]
    dh = display_height
    if len(parts) >= 8 and parts[7].strip():
        dh = int(parts[7].strip(), 10)
    pdf_opts: dict[str, float] = {}
    if len(parts) >= 9 and parts[8].strip():
        try:
            pdf_opts["max_height_px"] = float(parts[8].strip())
        except ValueError as e:
            raise ValueError(
                f"9th field (max height in px) must be a number, got {parts[8]!r}"
            ) from e
    if len(parts) >= 10 and parts[9].strip():
        try:
            pdf_opts["max_width_px"] = float(parts[9].strip())
        except ValueError as e:
            raise ValueError(
                f"10th field (max width in px) must be a number, got {parts[9]!r}"
            ) from e
    tikz = make_graph_from_latex_spec(
        fr,
        int(ex, 10),
        fs,
        h if h else None,
        w if w else None,
        bottom_value=bv if bv else "1",
        bottom_sum=bs,
        display_height=dh,
        placeholder=placeholder,
        **make_graph_kw,
    )
    return tikz, pdf_opts


def makeGraph(
    graph_fn: Callable[[int], str],
    expansion: int,
    display_height: int,
    *,
    row_step: float = 1.4,
    x_unit: float = 0.35,
    font: str | None = r"\scriptsize",
    bottom_value: str = "1",
    leaf_row_side_nodes: int | None = None,
    leaf_row_sum: str | None = None,
    bottom_row_font: str | None = r"\tiny",
    height_label: str | None = None,
    width_label: str | None = None,
    row_sum_fn: Callable[[int], str] | None = None,
    annotation_x_gap: float = 0.85,
    bracket_tick: float = 0.12,
    bracket_x_pad: float = 0.42,
    bracket_y_pad: float = 0.22,
    width_bracket_drop: float = 0.42,
    width_label_drop: float = 0.38,
    height_label_left: float = 0.35,
) -> str:
    """
    Return a LaTeX string: ``\\begin{tikzpicture} ... \\end{tikzpicture}``.

    graph_fn: maps row index to LaTeX math *body* (wrapped as ``$...$``).
    expansion: branching factor (>= 1).
    display_height: full rows drawn ``0 .. display_height - 1``; leaf row is
        level ``display_height`` with ``expansion ** display_height`` conceptual
        leaves for layout.
    bottom_value: LaTeX math body for each drawn leaf (default ``1``).
    leaf_row_side_nodes: if set, use that many leaves on left and right of
        ``$\\cdots$`` when abbreviated. If ``None``, the cap on drawn bottom symbols
        is ``1.5 × expansion^{display_height - 1}`` (rounded), and sides are derived
        from that cap.
    leaf_row_sum: when ``row_sum_fn`` is set, optional override for the right-hand
        sum aligned with the leaf row (else ``row_sum_fn(display_height)``).
    bottom_row_font: TikZ ``font=...`` for leaf-row nodes and the horizontal
        ``$\\cdots$`` (default ``\\tiny``). Use ``None`` to inherit the picture font.
    """
    if expansion < 1:
        raise ValueError("expansion must be >= 1")
    if display_height < 1:
        raise ValueError("display_height must be >= 1")

    d = _leaf_depth(display_height)
    leaf_label_body = _substitute_row_placeholders(substitute_ev(bottom_value, d), d)
    max_bottom_nodes = _default_max_bottom_nodes(expansion, display_height)
    leaf_left, leaf_right, x_gap_leaf_cdots = _leaf_row_layout(
        expansion, display_height, x_unit, leaf_row_side_nodes, max_bottom_nodes
    )
    if leaf_right is None:
        visible_leaf_indices = leaf_left
        leaf_abbreviated = False
    else:
        visible_leaf_indices = leaf_left + leaf_right
        leaf_abbreviated = True
    last_visible_leaf_index = visible_leaf_indices[-1]

    xmin, xmax = _tree_x_bounds(expansion, display_height, x_unit)
    y_bottom = -display_height * row_step
    y_top = bracket_y_pad
    y_bot = y_bottom - bracket_y_pad
    y_mid_gap = -(display_height - 0.5) * row_step

    lines: list[str] = []
    style = f"font={font}" if font else ""

    lines.append(r"\begin{tikzpicture}[")
    lines.append(
        r"  every node/.style={draw=none, inner sep=0.5pt, outer sep=0.55pt, anchor=center},"
    )
    if style:
        lines.append(f"  every node/.append style={{{style}}},")
    lines.append(r"]")

    def _leaf_row_bracket() -> str:
        parts = []
        if bottom_row_font and str(bottom_row_font).strip():
            parts.append(f"font={bottom_row_font.strip()}")
        if not parts:
            return ""
        return "[" + ",".join(parts) + "]"

    _lb = _leaf_row_bracket()

    for r in range(display_height):
        n = expansion**r
        y = -r * row_step
        for i in range(n):
            x = _x_center(r, i, expansion, d, x_unit)
            label = graph_fn(r)
            lines.append(
                rf"  \node ({_node_name(r, i)}) at ({x:.4f},{y:.4f}) {{${label}$}};"
            )

    lines.append(
        rf"  \node[draw=none] (gapvdots) at (0,{y_mid_gap:.4f}) {{$\vdots$}};"
    )

    for i in leaf_left:
        x = _x_center(d, i, expansion, d, x_unit)
        lines.append(
            rf"  \node{_lb} ({_node_name(d, i)}) at ({x:.4f},{y_bottom:.4f}) {{${leaf_label_body}$}};"
        )
    if leaf_abbreviated:
        lines.append(
            rf"  \node{_lb} (leafcdots) at ({x_gap_leaf_cdots:.4f},{y_bottom:.4f}) {{$\cdots$}};"
        )
        for i in leaf_right:
            x = _x_center(d, i, expansion, d, x_unit)
            lines.append(
                rf"  \node{_lb} ({_node_name(d, i)}) at ({x:.4f},{y_bottom:.4f}) {{${leaf_label_body}$}};"
            )

    for r in range(display_height - 1):
        n_parent = expansion**r
        for i in range(n_parent):
            for k in range(expansion):
                c = i * expansion + k
                lines.append(
                    rf"  \draw ({_node_name(r, i)}) -- ({_node_name(r + 1, c)});"
                )

    x_sum = xmax + annotation_x_gap
    x_left_brace = xmin - bracket_x_pad

    if height_label is not None:
        lines.append(
            rf"  \draw ({x_left_brace:.4f},{y_top:.4f}) -- ({x_left_brace:.4f},{y_bot:.4f});"
        )
        lines.append(
            rf"  \draw ({x_left_brace:.4f},{y_top:.4f}) -- ({x_left_brace + bracket_tick:.4f},{y_top:.4f});"
        )
        lines.append(
            rf"  \draw ({x_left_brace:.4f},{y_bot:.4f}) -- ({x_left_brace + bracket_tick:.4f},{y_bot:.4f});"
        )
        y_mid = (y_top + y_bot) / 2.0
        x_hlab = x_left_brace - height_label_left
        lines.append(
            rf"  \node[draw=none, anchor=east] at ({x_hlab:.4f},{y_mid:.4f}) {{${height_label}$}};"
        )

    if width_label is not None:
        y_bar = y_bottom - width_bracket_drop
        lines.append(rf"  \draw ({xmin:.4f},{y_bar:.4f}) -- ({xmax:.4f},{y_bar:.4f});")
        lines.append(
            rf"  \draw ({xmin:.4f},{y_bar:.4f}) -- ({xmin:.4f},{y_bar + bracket_tick:.4f});"
        )
        lines.append(
            rf"  \draw ({xmax:.4f},{y_bar:.4f}) -- ({xmax:.4f},{y_bar + bracket_tick:.4f});"
        )
        x_mid = (xmin + xmax) / 2.0
        y_wlab = y_bar - width_label_drop
        lines.append(
            rf"  \node[draw=none] at ({x_mid:.4f},{y_wlab:.4f}) {{${width_label}$}};"
        )

    if row_sum_fn is not None:
        for r in range(display_height):
            y = -r * row_step
            last = expansion**r - 1
            lines.append(
                rf"  \node[draw=none, anchor=west] (sum{r}) at ({x_sum:.4f},{y:.4f}) {{${row_sum_fn(r)}$}};"
            )
            lines.append(
                rf"  \draw[densely dashed,->, shorten >=2pt] ({_node_name(r, last)}.east) -- (sum{r}.west);"
            )
        lines.append(
            rf"  \node[draw=none, anchor=west] (sumgapvdots) at ({x_sum:.4f},{y_mid_gap:.4f}) {{$\vdots$}};"
        )
        leaf_sum_body = (
            _substitute_row_placeholders(substitute_ev(leaf_row_sum, d), d)
            if leaf_row_sum is not None
            else row_sum_fn(display_height)
        )
        lines.append(
            rf"  \node[draw=none, anchor=west] (sumleaf) at ({x_sum:.4f},{y_bottom:.4f}) {{${leaf_sum_body}$}};"
        )
        lines.append(
            rf"  \draw[densely dashed,->, shorten >=2pt] ({_node_name(d, last_visible_leaf_index)}.east) -- (sumleaf.west);"
        )

    lines.append(r"\end{tikzpicture}")
    return "\n".join(lines) + "\n"


def extract_tikz_fragment(tex: str) -> str:
    """
    Return the substring from ``\\begin{tikzpicture}`` through ``\\end{tikzpicture}``
    inclusive. If markers are missing, returns ``tex`` stripped.
    """
    start = r"\begin{tikzpicture}"
    end = r"\end{tikzpicture}"
    i = tex.find(start)
    j = tex.find(end)
    if i == -1 or j == -1:
        return tex.strip()
    j += len(end)
    return tex[i:j].strip()


if __name__ == "__main__":
    graph = expression_from_latex(r"n^{{row}}")
    row_sum = expression_from_latex(r"\frac{n^{{row}}}{2^{{row}}}")

    sample = makeGraph(
        graph,
        expansion=2,
        display_height=3,
        height_label=r"O(\log_{2} n)",
        width_label=r"O(n)",
        row_sum_fn=row_sum,
        leaf_row_sum=r"n",
    )
    print(sample)

    _, _pdf_opts = make_graph_from_delimited_latex(
        r"n^{{row}}|2|\frac{n^{{row}}}{2^{{row}}}|O(\log_{2} n)|O(n)|1|n|3",
        display_height=3,
    )

    base = Path(__file__).resolve().parent / "sample_recursion_tree"
    if shutil.which("pdflatex"):
        pdf = export_make_graph_pdf(
            base,
            graph,
            expansion=2,
            display_height=3,
            height_label=r"O(\log_{2} n)",
            width_label=r"O(n)",
            row_sum_fn=row_sum,
            leaf_row_sum=r"n",
        )
        print(f"Wrote {base.with_suffix('.tex')} and {pdf}")
    else:
        print("(pdflatex not on PATH; skipped writing PDF)")
