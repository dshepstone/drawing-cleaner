"""The Drawing Cleaner window (Tkinter, so it needs nothing beyond Python itself)."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageTk
from PIL import _tkinter_finder  # noqa: F401  (named here so the packaged .exe includes it)

from . import __version__
from .engine import Settings, clean_folder, darkness_map, default_output_folder, find_images, load_image, render

PREVIEW_MAX = 1100            # longest side used for the live preview, in pixels
ACCENT = "#2563eb"
INK = "#1f2937"
MUTED = "#6b7280"
PANEL = "#f3f4f6"
LINE_COLORS = [("Black", (0, 0, 0)), ("Blue", (40, 80, 200)), ("Red", (200, 45, 45))]
BACKDROPS = {"Checker": None, "White": (255, 255, 255), "Blue": (120, 170, 230), "Dark": (45, 45, 50)}


def _settings_file() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "DrawingCleaner" / "settings.json"


def _resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


def _checker(size, cell=12):
    w, h = size
    tile = Image.new("RGB", (cell * 2, cell * 2), (255, 255, 255))
    grey = Image.new("RGB", (cell, cell), (222, 222, 222))
    tile.paste(grey, (0, 0))
    tile.paste(grey, (cell, cell))
    out = Image.new("RGB", (w, h))
    for y in range(0, h, cell * 2):
        for x in range(0, w, cell * 2):
            out.paste(tile, (x, y))
    return out


class App(tk.Tk):
    def __init__(self, start_folder: str | None = None):
        super().__init__()
        self.title("Drawing Cleaner")
        self.geometry("1180x720")
        self.minsize(960, 640)
        self.configure(bg="white")
        try:
            self.iconbitmap(_resource("icon.ico"))
        except Exception:
            pass

        self.folder: Path | None = None
        self.files: list[Path] = []
        self.dark = None                 # cached darkness map of the previewed drawing
        self.original = None             # preview-sized original
        self.photo = None
        self.worker = None
        self.stop_flag = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self._pending = None

        saved = self._load_saved()
        self.v_paper = tk.IntVar(value=saved.get("paper_cleanup", Settings.paper_cleanup))
        self.v_dark = tk.IntVar(value=saved.get("line_darkness", Settings.line_darkness))
        self.v_speck = tk.BooleanVar(value=saved.get("despeckle", True))
        self.v_sub = tk.BooleanVar(value=saved.get("include_subfolders", True))
        self.color = tuple(saved.get("color", (0, 0, 0)))
        self.v_view = tk.StringVar(value="Cleaned")
        self.v_back = tk.StringVar(value=saved.get("backdrop", "Checker"))
        self.v_frame = tk.IntVar(value=0)

        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll)

        first = start_folder or saved.get("folder")
        if first and Path(first).is_dir():
            self.after(50, lambda: self.set_folder(Path(first)))

    # ------------------------------------------------------------------ layout
    def _style(self):
        st = ttk.Style(self)
        if "vista" not in st.theme_names():
            st.theme_use("clam")
        for name in ("TFrame", "TLabel", "TCheckbutton", "TRadiobutton"):
            st.configure(name, background=PANEL)
        st.configure("White.TFrame", background="white")
        st.configure("White.TLabel", background="white", foreground=INK)
        st.configure("White.TRadiobutton", background="white")
        st.configure("Step.TLabel", background=PANEL, foreground=INK, font=("Segoe UI", 11, "bold"))
        st.configure("Hint.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        st.configure("WhiteHint.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9))
        st.configure("TLabel", font=("Segoe UI", 10), foreground=INK)
        st.configure("TButton", font=("Segoe UI", 10))
        st.configure("TScale", background=PANEL)

    def _build(self):
        side = ttk.Frame(self, padding=(18, 16), width=340)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        tk.Label(side, text="Drawing Cleaner", bg=PANEL, fg=INK, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(side, text="Pencil drawings to clean lines on a transparent\nbackground, ready for OpenToonz.",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 14))

        # Step 3 (built first and pinned to the bottom so it is always on screen)
        step3 = ttk.Frame(side)
        step3.pack(side="bottom", fill="x")
        ttk.Label(step3, text="3   Clean them", style="Step.TLabel").pack(anchor="w")
        self.b_go = tk.Button(step3, text="Clean all drawings", command=self._go, bg=ACCENT, fg="white",
                              activebackground="#1d4ed8", activeforeground="white", relief="flat", bd=0,
                              font=("Segoe UI", 12, "bold"), pady=8, cursor="hand2",
                              disabledforeground="#dbeafe")
        self.b_go.pack(fill="x", pady=(6, 6))
        self.bar = ttk.Progressbar(step3, mode="determinate")
        self.bar.pack(fill="x")
        self.l_status = ttk.Label(step3, text="Your original drawings are never changed.", style="Hint.TLabel",
                                  wraplength=300, justify="left")
        self.l_status.pack(anchor="w", pady=(6, 4))
        self.b_open = ttk.Button(step3, text="Open the cleaned folder", command=self._open_output)
        ttk.Label(step3, text=f"v{__version__}", style="Hint.TLabel").pack(side="bottom", anchor="e")

        # Step 1
        ttk.Label(side, text="1   Choose your drawings", style="Step.TLabel").pack(anchor="w")
        ttk.Button(side, text="Choose folder...", command=self.choose_folder).pack(fill="x", pady=(6, 4))
        self.l_folder = ttk.Label(side, text="No folder chosen yet", style="Hint.TLabel", wraplength=300, justify="left")
        self.l_folder.pack(anchor="w")
        ttk.Checkbutton(side, text="Include folders inside it", variable=self.v_sub,
                        command=self._rescan).pack(anchor="w", pady=(4, 14))

        # Step 2
        head = ttk.Frame(side)
        head.pack(fill="x")
        ttk.Label(head, text="2   Adjust if needed", style="Step.TLabel").pack(side="left")
        reset = tk.Label(head, text="Reset", bg=PANEL, fg=ACCENT, cursor="hand2", font=("Segoe UI", 9, "underline"))
        reset.pack(side="right")
        reset.bind("<Button-1>", lambda e: self._reset())
        self._slider(side, "Paper cleanup", self.v_paper, "Raise it if grey haze or smudges are left behind.")
        self._slider(side, "Line darkness", self.v_dark, "Raise it if your lines look too faint.")
        ttk.Checkbutton(side, text="Remove tiny specks", variable=self.v_speck,
                        command=self._refresh_soon).pack(anchor="w", pady=(8, 6))
        row = ttk.Frame(side)
        row.pack(fill="x")
        ttk.Label(row, text="Colour").pack(side="left")
        self.swatches = []
        for name, rgb in LINE_COLORS:
            self._swatch(row, rgb)
        ttk.Button(row, text="Other...", command=self._pick_color).pack(side="left", padx=(8, 0))

        # Preview
        main = ttk.Frame(self, style="White.TFrame", padding=(16, 14))
        main.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(main, style="White.TFrame")
        top.pack(fill="x")
        for v in ("Cleaned", "Original"):
            ttk.Radiobutton(top, text=v, value=v, variable=self.v_view, style="White.TRadiobutton",
                            command=self._refresh_soon).pack(side="left", padx=(0, 12))
        ttk.Label(top, text="(hold Space to compare)", style="WhiteHint.TLabel").pack(side="left")
        back = ttk.Combobox(top, values=list(BACKDROPS), textvariable=self.v_back, state="readonly", width=9)
        back.pack(side="right")
        back.bind("<<ComboboxSelected>>", lambda e: self._refresh_soon())
        ttk.Label(top, text="Show over", style="White.TLabel").pack(side="right", padx=(0, 6))

        self.canvas = tk.Canvas(main, bg="#e5e7eb", highlightthickness=1, highlightbackground="#d1d5db", cursor="hand2")
        self.canvas.pack(fill="both", expand=True, pady=10)
        self.canvas.bind("<Configure>", lambda e: self._refresh_soon())
        self.canvas.bind("<Button-1>", lambda e: self.choose_folder() if not self.files else None)

        bottom = ttk.Frame(main, style="White.TFrame")
        bottom.pack(fill="x")
        ttk.Button(bottom, text="<", width=3, command=lambda: self._step(-1)).pack(side="left")
        self.scrub = ttk.Scale(bottom, from_=0, to=0, orient="horizontal", command=self._on_scrub)
        self.scrub.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(bottom, text=">", width=3, command=lambda: self._step(1)).pack(side="left")
        self.l_file = ttk.Label(main, text="", style="WhiteHint.TLabel")
        self.l_file.pack(anchor="w", pady=(6, 0))

        self.bind("<KeyPress-space>", lambda e: self._peek(True))
        self.bind("<KeyRelease-space>", lambda e: self._peek(False))
        self.bind("<Left>", lambda e: self._step(-1))
        self.bind("<Right>", lambda e: self._step(1))
        self._mark_swatch()
        self._update_go()

    def _slider(self, parent, title, var, hint):
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(8, 0))
        ttk.Label(head, text=title).pack(side="left")
        value = ttk.Label(head, text=str(var.get()), style="Hint.TLabel")
        value.pack(side="right")

        def moved(v):
            var.set(int(float(v)))
            value.configure(text=str(var.get()))
            self._refresh_soon()

        scale = ttk.Scale(parent, from_=0, to=100, orient="horizontal", command=moved)
        scale.set(var.get())
        scale.pack(fill="x")
        ttk.Label(parent, text=hint, style="Hint.TLabel", wraplength=300, justify="left").pack(anchor="w")
        var._scale, var._label = scale, value       # so Reset can move them

    def _swatch(self, parent, rgb):
        b = tk.Button(parent, width=2, bg="#%02x%02x%02x" % rgb, activebackground="#%02x%02x%02x" % rgb,
                      relief="flat", bd=0, highlightthickness=2, cursor="hand2",
                      command=lambda: self._set_color(rgb))
        b.pack(side="left", padx=(8, 0))
        self.swatches.append((b, rgb))

    # ------------------------------------------------------------------ state
    def settings(self) -> Settings:
        return Settings(self.v_paper.get(), self.v_dark.get(), self.v_speck.get(), tuple(self.color))

    def _load_saved(self) -> dict:
        try:
            return json.loads(_settings_file().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self):
        data = dict(paper_cleanup=self.v_paper.get(), line_darkness=self.v_dark.get(), despeckle=self.v_speck.get(),
                    include_subfolders=self.v_sub.get(), color=list(self.color), backdrop=self.v_back.get(),
                    folder=str(self.folder) if self.folder else None)
        try:
            f = _settings_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Drawing Cleaner", "Cleaning is still running. Stop and close?"):
                return
            self.stop_flag.set()
        self._save()
        self.destroy()

    def _set_color(self, rgb):
        self.color = tuple(rgb)
        self._mark_swatch()
        self._refresh_soon()

    def _pick_color(self):
        rgb, _ = colorchooser.askcolor(color="#%02x%02x%02x" % tuple(self.color), parent=self, title="Line colour")
        if rgb:
            self._set_color(tuple(int(c) for c in rgb))

    def _mark_swatch(self):
        for b, rgb in self.swatches:
            b.configure(highlightbackground=ACCENT if rgb == tuple(self.color) else PANEL,
                        highlightcolor=ACCENT if rgb == tuple(self.color) else PANEL)

    def _reset(self):
        for var, default in ((self.v_paper, Settings.paper_cleanup), (self.v_dark, Settings.line_darkness)):
            var.set(default)
            var._scale.set(default)
            var._label.configure(text=str(default))
        self.v_speck.set(True)
        self._set_color((0, 0, 0))

    # ------------------------------------------------------------------ folder
    def choose_folder(self):
        if self.worker and self.worker.is_alive():
            return
        start = str(self.folder) if self.folder else str(Path.home())
        chosen = filedialog.askdirectory(parent=self, title="Choose the folder that holds your drawings",
                                         initialdir=start, mustexist=True)
        if chosen:
            self.set_folder(Path(chosen))

    def set_folder(self, folder: Path):
        self.folder = folder
        self.b_open.pack_forget()
        self.bar.configure(value=0)
        self._rescan()

    def _rescan(self):
        if not self.folder:
            return
        out = default_output_folder(self.folder)
        self.files = find_images(self.folder, self.v_sub.get(), skip=out)
        n = len(self.files)
        self.l_folder.configure(text=f"{self.folder.name}  -  {n} drawing{'s' if n != 1 else ''} found")
        self.l_status.configure(
            text=(f"Cleaned copies will be saved in a new folder named \"{out.name}\" beside it. "
                  "Your original drawings are never changed.") if n else
                 "No pictures found there. Choose the folder that holds your PNG or JPG drawings.")
        self.scrub.configure(to=max(0, n - 1))
        self.scrub.set(0)
        self.v_frame.set(0)
        self.dark = self.original = None
        self._load_preview()
        self._update_go()

    def _update_go(self):
        busy = bool(self.worker and self.worker.is_alive())
        n = len(self.files)
        if busy:
            self.b_go.configure(text="Stop", state="normal", bg="#b91c1c", activebackground="#991b1b")
        else:
            label = f"Clean all {n} drawings" if n > 1 else "Clean this drawing" if n == 1 else "Clean all drawings"
            self.b_go.configure(text=label, state="normal" if n else "disabled",
                                bg=ACCENT if n else "#93c5fd", activebackground="#1d4ed8")

    # ------------------------------------------------------------------ preview
    def _on_scrub(self, v):
        i = int(round(float(v)))
        if i != self.v_frame.get():
            self.v_frame.set(i)
            self._load_preview()

    def _step(self, d):
        if self.files:
            self.scrub.set(min(len(self.files) - 1, max(0, self.v_frame.get() + d)))

    def _peek(self, down):
        want = "Original" if down else "Cleaned"
        if self.files and self.v_view.get() != want:
            self.v_view.set(want)
            self._refresh()

    def _load_preview(self):
        self.dark = self.original = None
        if self.files:
            f = self.files[self.v_frame.get()]
            try:
                gray = load_image(f)
                gray.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
                self.original, self.dark = gray, darkness_map(gray)
                rel = f.relative_to(self.folder)
                self.l_file.configure(text=f"{rel}     ({self.v_frame.get() + 1} of {len(self.files)})")
            except Exception as e:
                self.l_file.configure(text=f"Could not open {f.name}: {e}")
        else:
            self.l_file.configure(text="")
        self._refresh()

    def _refresh_soon(self):
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(25, self._refresh)

    def _refresh(self):
        self._pending = None
        c = self.canvas
        c.delete("all")
        cw, ch = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        if self.original is None:
            c.configure(cursor="hand2")
            msg = "Click here to choose a folder of drawings" if not self.files else "This picture could not be opened"
            c.create_text(cw // 2, ch // 2, text=msg, fill=MUTED, font=("Segoe UI", 13))
            return
        c.configure(cursor="")
        if self.v_view.get() == "Original":
            img = self.original.convert("RGB")
        else:
            cut = render(self.dark, self.settings())
            rgb = BACKDROPS.get(self.v_back.get())
            base = _checker(cut.size) if rgb is None else Image.new("RGB", cut.size, rgb)
            base.paste(cut, (0, 0), cut)
            img = base
        scale = min((cw - 8) / img.width, (ch - 8) / img.height)
        size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        self.photo = ImageTk.PhotoImage(img.resize(size, Image.LANCZOS if scale < 1 else Image.BICUBIC))
        c.create_image(cw // 2, ch // 2, image=self.photo)

    # ------------------------------------------------------------------ batch
    def _go(self):
        if self.worker and self.worker.is_alive():
            self.stop_flag.set()
            self.l_status.configure(text="Stopping after this drawing...")
            return
        if not self.files:
            return
        folder, out, s, sub = self.folder, default_output_folder(self.folder), self.settings(), self.v_sub.get()
        self.stop_flag.clear()
        self.b_open.pack_forget()
        self.bar.configure(value=0, maximum=len(self.files))

        def run():
            try:
                done, errors = clean_folder(folder, out, s, sub,
                                            progress=lambda i, n, f: self.events.put(("step", i, n, f.name)),
                                            should_stop=self.stop_flag.is_set)
                self.events.put(("done", done, errors, out))
            except Exception as e:
                self.events.put(("failed", str(e)))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        self._update_go()

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "step":
                    _, i, n, name = ev
                    self.bar.configure(value=i)
                    self.l_status.configure(text=f"Cleaning {i} of {n}:  {name}")
                elif ev[0] == "done":
                    _, done, errors, out = ev
                    stopped = self.stop_flag.is_set()
                    text = f"{'Stopped. ' if stopped else 'Done! '}{done} drawing{'s' if done != 1 else ''} saved in \"{out.name}\"."
                    if errors:
                        text += f" {len(errors)} could not be read: " + ", ".join(f.name for f, _ in errors[:3])
                        text += "..." if len(errors) > 3 else ""
                    self.l_status.configure(text=text)
                    self.out_folder = out
                    if done:
                        self.b_open.pack(fill="x")
                    self._update_go()
                elif ev[0] == "failed":
                    self.l_status.configure(text="Something went wrong: " + ev[1])
                    self._update_go()
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _open_output(self):
        path = str(getattr(self, "out_folder", ""))
        try:
            if sys.platform == "win32":
                os.startfile(path)                   # noqa: S606 - opens Explorer
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showinfo("Drawing Cleaner", f"The cleaned drawings are in:\n{path}\n\n({e})")


def main():
    if sys.platform == "win32":                      # crisp text on high-DPI laptops
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    start = sys.argv[1] if len(sys.argv) > 1 else None   # a folder dropped onto the .exe
    App(start).mainloop()


if __name__ == "__main__":
    main()
