"""
Tk GUI: edit LaTeX templates, build PDFs into ``gui_pdf_out/`` (unique name per build), preview, copy TikZ.

Clipboard autoload: if the clipboard starts with ``graph:`` followed by the same
pipe-separated fields as :func:`make_graph.make_graph_from_delimited_latex`
(optional 8th ``display_height``, 9th ``max_height_px``, 10th ``max_width_px`` for PDF), the form is filled,
a PDF is generated, and it is opened.

Requires ``pdflatex`` on PATH. For a **live preview** in the window, install
``pymupdf`` and ``pillow`` into the **same** Python the GUI uses
(``python -m pip install pymupdf pillow``). The repo pins that interpreter in
``.vscode/settings.json``; pick it in Cursor (Python: Select Interpreter) or run
``run_graph_gui.ps1``. You can also turn on **Open PDF after generate** to view
the file in your default PDF app.
"""

from __future__ import annotations

import hashlib
import io
import os
import secrets
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from make_graph import (
    extract_tikz_fragment,
    make_graph_from_latex_spec,
    write_tikz_pdf,
)

ROOT = Path(__file__).resolve().parent
PDF_OUT = ROOT / "gui_pdf_out"
CLIPBOARD_PREFIXES = ("graph:", "GRAPH:")


class GraphGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Recursion tree → PDF / TikZ")
        self.geometry("920x780")
        self._last_tikz = ""
        self._last_pdf: Path | None = None
        self._preview_fail_reason = ""

        pad = {"padx": 6, "pady": 4}
        row = 0

        ttk.Label(
            self,
            text="func_row",
        ).grid(
            row=row, column=0, sticky="w", **pad
        )
        self.txt_row = scrolledtext.ScrolledText(self, width=52, height=2, wrap=tk.WORD)
        self.txt_row.grid(row=row, column=1, columnspan=2, sticky="ew", **pad)
        self.txt_row.insert(tk.END, r"n^{{row}}")
        row += 1

        ttk.Label(self, text="func_sum").grid(row=row, column=0, sticky="nw", **pad)
        self.txt_sum = scrolledtext.ScrolledText(self, width=52, height=2, wrap=tk.WORD)
        self.txt_sum.grid(row=row, column=1, columnspan=2, sticky="ew", **pad)
        self.txt_sum.insert(tk.END, r"\frac{n^{{row}}}{2^{{row}}}")
        row += 1

        def add_labeled_entry(label: str, default: str, r: int) -> ttk.Entry:
            ttk.Label(self, text=label).grid(row=r, column=0, sticky="w", **pad)
            e = ttk.Entry(self, width=56)
            e.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
            e.insert(0, default)
            return e

        self.ent_exp = add_labeled_entry("expansion", "2", row)
        row += 1
        self.ent_dh = add_labeled_entry("display_height", "3", row)
        row += 1
        self.ent_hpx = add_labeled_entry("PDF max height (px, optional)", "", row)
        row += 1
        self.ent_wpx = add_labeled_entry("PDF max width (px, optional)", "", row)
        row += 1
        self.ent_h = add_labeled_entry("height label (optional)", r"O(\log_{2} n)", row)
        row += 1
        self.ent_w = add_labeled_entry("width label (optional)", r"O(n)", row)
        row += 1
        self.ent_bv = add_labeled_entry("bottom value", "1", row)
        row += 1
        self.ent_bs = add_labeled_entry("bottom sum", "n", row)
        row += 1

        opt = ttk.Frame(self)
        opt.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        self.var_copy_tikz_after = tk.BooleanVar(value=True)
        self.var_open_pdf_after = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt,
            text="Copy TikZ to clipboard after successful Generate PDF",
            variable=self.var_copy_tikz_after,
        ).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Checkbutton(
            opt,
            text="Open PDF after generate (system viewer; good preview if no pymupdf)",
            variable=self.var_open_pdf_after,
        ).pack(side=tk.LEFT)
        row += 1

        bf = ttk.Frame(self)
        bf.grid(row=row, column=0, columnspan=3, **pad)
        ttk.Button(bf, text="Generate PDF", command=self._generate).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="Copy TikZ", command=self._copy_tikz).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="Copy graph: line", command=self._copy_graph_line).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="Open PDFs folder", command=self._open_pdf_folder).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="Open last PDF", command=self._open_pdf).pack(side=tk.LEFT, padx=4)
        row += 1

        self.status = ttk.Label(self, text="Ready. PDFs go to gui_pdf_out/")
        self.status.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        row += 1

        self.preview = ttk.Label(
            self,
            text=(
                "Preview: install pymupdf + pillow (pip install pymupdf pillow), "
                "then Generate PDF. Or use “Open PDF after generate” / Open last PDF."
            ),
            wraplength=880,
            justify=tk.LEFT,
        )
        self.preview.grid(row=row, column=0, columnspan=3, sticky="nsew", **pad)
        self.rowconfigure(row, weight=1)
        self.columnconfigure(1, weight=1)

        self.after(120, self._try_clipboard_autorun)

    def _spec_string(self) -> str:
        parts = [
            self.txt_row.get("1.0", tk.END).strip(),
            self.ent_exp.get().strip(),
            self.txt_sum.get("1.0", tk.END).strip(),
            self.ent_h.get().strip(),
            self.ent_w.get().strip(),
            self.ent_bv.get().strip(),
            self.ent_bs.get().strip(),
            self.ent_dh.get().strip(),
            self.ent_hpx.get().strip(),
            self.ent_wpx.get().strip(),
        ]
        return "|".join(parts)

    def _apply_pipe_body(self, body: str) -> None:
        parts = [p.strip() for p in body.split("|")]
        if len(parts) < 7:
            raise ValueError("need at least 7 | fields")
        self.txt_row.delete("1.0", tk.END)
        self.txt_row.insert(tk.END, parts[0])
        self.ent_exp.delete(0, tk.END)
        self.ent_exp.insert(0, parts[1])
        self.txt_sum.delete("1.0", tk.END)
        self.txt_sum.insert(tk.END, parts[2])
        self.ent_h.delete(0, tk.END)
        self.ent_h.insert(0, parts[3])
        self.ent_w.delete(0, tk.END)
        self.ent_w.insert(0, parts[4])
        self.ent_bv.delete(0, tk.END)
        self.ent_bv.insert(0, parts[5])
        self.ent_bs.delete(0, tk.END)
        self.ent_bs.insert(0, parts[6])
        if len(parts) >= 8 and parts[7].strip():
            self.ent_dh.delete(0, tk.END)
            self.ent_dh.insert(0, parts[7])
        if len(parts) >= 9 and parts[8].strip():
            self.ent_hpx.delete(0, tk.END)
            self.ent_hpx.insert(0, parts[8])
        if len(parts) >= 10 and parts[9].strip():
            self.ent_wpx.delete(0, tk.END)
            self.ent_wpx.insert(0, parts[9])

    def _gather(self) -> str:
        exp = int(self.ent_exp.get().strip())
        dh = int(self.ent_dh.get().strip())
        h = self.ent_h.get().strip()
        w = self.ent_w.get().strip()
        fr = self.txt_row.get("1.0", tk.END).strip()
        fs = self.txt_sum.get("1.0", tk.END).strip()
        bv = self.ent_bv.get().strip() or "1"
        bs = self.ent_bs.get().strip()
        return make_graph_from_latex_spec(
            fr,
            exp,
            fs,
            h if h else None,
            w if w else None,
            bottom_value=bv,
            bottom_sum=bs,
            display_height=dh,
        )

    def _pdf_size_kw(self) -> dict[str, float]:
        out: dict[str, float] = {}
        hs = self.ent_hpx.get().strip()
        ws = self.ent_wpx.get().strip()
        if hs:
            out["max_height_px"] = float(hs)
        if ws:
            out["max_width_px"] = float(ws)
        return out

    def _output_pdf_path(self) -> Path:
        PDF_OUT.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(self._spec_string().encode("utf-8")).hexdigest()[:14]
        # Unique suffix so each build uses a new filename; avoids pdflatex
        # "can't write on file" when the previous PDF with the same hash is open.
        u = secrets.token_hex(3)
        return PDF_OUT / f"g_{h}_{u}.pdf"

    def _generate(self) -> None:
        try:
            tikz = self._gather()
        except Exception as e:
            messagebox.showerror("Build failed", str(e))
            return
        try:
            pdf_kw = self._pdf_size_kw()
        except ValueError as e:
            messagebox.showerror("PDF size", f"Height/width in px must be numbers: {e}")
            return
        self._last_tikz = extract_tikz_fragment(tikz)
        out = self._output_pdf_path()
        stem = out.with_suffix("")
        try:
            write_tikz_pdf(stem, tikz, **pdf_kw)
        except FileNotFoundError as e:
            messagebox.showerror("LaTeX", str(e))
            return
        except RuntimeError as e:
            messagebox.showerror("pdflatex", str(e))
            return
        self._last_pdf = out.resolve()
        status_bits = [f"PDF: {self._last_pdf}"]
        inline = self._show_preview_png()
        if self.var_copy_tikz_after.get() and self._last_tikz:
            self._push_tikz_clipboard()
            status_bits.append("TikZ copied to clipboard")
        if self.var_open_pdf_after.get() and self._last_pdf.is_file():
            try:
                os.startfile(self._last_pdf)  # type: ignore[attr-defined]
                status_bits.append("opened PDF")
            except OSError as e:
                status_bits.append(f"could not open PDF ({e})")
        elif (
            not inline
            and self._last_pdf.is_file()
            and not self.var_open_pdf_after.get()
        ):
            hint = (
                "No inline preview. "
                + (
                    self._preview_fail_reason
                    if self._preview_fail_reason
                    else "Install pymupdf + pillow for this Python, or use “Open PDF after generate” / Open last PDF."
                )
            )
            self.preview.config(
                image="",
                text=hint,
                wraplength=880,
                justify=tk.LEFT,
            )
        self.status.config(text=" · ".join(status_bits))

    def _show_preview_png(self) -> bool:
        """Render first PDF page in the preview label. Returns True if inline preview was shown."""
        self._preview_fail_reason = ""
        if self._last_pdf is None or not self._last_pdf.is_file():
            self._preview_fail_reason = "Internal error: PDF path missing."
            return False
        try:
            import fitz  # PyMuPDF  (pip package name: pymupdf)
            from PIL import Image, ImageTk
        except ImportError as e:
            self._preview_fail_reason = (
                f"Could not import preview libraries ({e}).\n\n"
                f"This window is using Python:\n{sys.executable}\n\n"
                "Install into that interpreter:\n"
                f'  "{sys.executable}" -m pip install pymupdf pillow'
            )
            return False

        pdf = str(self._last_pdf.resolve())
        try:
            doc = fitz.open(pdf)
            try:
                page = doc[0]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
                png = pix.tobytes("png")
            finally:
                doc.close()
            im = Image.open(io.BytesIO(png))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            w, h = im.size
            max_w = 880
            if w > max_w:
                ratio = max_w / w
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = Image.LANCZOS  # type: ignore[attr-defined]
                im = im.resize((int(w * ratio), int(h * ratio)), resample)
            photo = ImageTk.PhotoImage(im, master=self)
            self.preview.config(image=photo, text="")
            self.preview.image = photo
        except Exception as e:
            self._preview_fail_reason = (
                f"Preview render failed ({type(e).__name__}: {e}).\n\n"
                f"Python: {sys.executable}"
            )
            return False
        return True

    def _push_tikz_clipboard(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._last_tikz)
        self.update()

    def _copy_tikz(self) -> None:
        if not self._last_tikz:
            try:
                tikz = self._gather()
                self._last_tikz = extract_tikz_fragment(tikz)
            except Exception as e:
                messagebox.showerror("Copy", str(e))
                return
        self._push_tikz_clipboard()
        self.status.config(text="TikZ fragment copied.")

    def _copy_graph_line(self) -> None:
        line = "graph:" + self._spec_string()
        self.clipboard_clear()
        self.clipboard_append(line)
        self.update()
        self.status.config(text="Copied graph: line for clipboard autoload.")

    def _open_pdf(self) -> None:
        if self._last_pdf is None or not self._last_pdf.is_file():
            messagebox.showinfo("PDF", "Generate a PDF first.")
            return
        try:
            os.startfile(self._last_pdf)  # type: ignore[attr-defined]
        except OSError as e:
            messagebox.showerror("Open PDF", str(e))

    def _open_pdf_folder(self) -> None:
        PDF_OUT.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(PDF_OUT)  # type: ignore[attr-defined]
        except OSError:
            messagebox.showinfo("Folder", str(PDF_OUT))

    def _try_clipboard_autorun(self) -> None:
        try:
            data = self.clipboard_get()
        except tk.TclError:
            return
        if not isinstance(data, str):
            return
        s = data.strip()
        body = None
        for p in CLIPBOARD_PREFIXES:
            if s.startswith(p):
                body = s[len(p) :].strip()
                break
        if body is None:
            return
        try:
            self._apply_pipe_body(body)
        except ValueError as e:
            messagebox.showwarning("Clipboard", str(e))
            return
        self._generate()
        self._open_pdf()


def main() -> None:
    GraphGui().mainloop()


if __name__ == "__main__":
    main()
