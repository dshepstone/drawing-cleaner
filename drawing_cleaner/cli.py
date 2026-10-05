"""Command line use:  python -m drawing_cleaner.cli <folder> [output_folder]"""
import argparse
from pathlib import Path

from .engine import Settings, clean_folder, default_output_folder


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="drawing-cleaner", description="Pencil drawings to transparent line art.")
    p.add_argument("folder", type=Path)
    p.add_argument("output", type=Path, nargs="?", help="default: <folder>_clean")
    p.add_argument("--paper-cleanup", type=int, default=Settings.paper_cleanup, help="0-100 [%(default)s]")
    p.add_argument("--line-darkness", type=int, default=Settings.line_darkness, help="0-100 [%(default)s]")
    p.add_argument("--keep-specks", action="store_true")
    p.add_argument("--color", default="000000", help="line colour as hex [%(default)s]")
    p.add_argument("--no-subfolders", action="store_true")
    a = p.parse_args(argv)
    hexc = a.color.lstrip("#")
    s = Settings(a.paper_cleanup, a.line_darkness, not a.keep_specks, tuple(int(hexc[i:i + 2], 16) for i in (0, 2, 4)))
    out = a.output or default_output_folder(a.folder)
    done, errors = clean_folder(a.folder, out, s, not a.no_subfolders,
                                progress=lambda i, n, f: print(f"[{i}/{n}] {f.name}"))
    for f, msg in errors:
        print(f"SKIPPED {f}: {msg}")
    print(f"{done} drawings written to {out}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
