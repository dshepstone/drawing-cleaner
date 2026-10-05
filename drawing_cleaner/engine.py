"""The cleaning engine. No GUI code here, so it can be tested and scripted.

How it works
  1. Estimate the blank paper (lighting falloff, shadows, paper tone) by
     erasing the lines from a shrunken copy of the photo and blurring it.
  2. Divide the photo by that estimate, which flattens the lighting.
  3. Whatever is darker than the paper is the drawing. Its darkness becomes
     the alpha channel, so soft pencil edges stay soft.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image, ImageFilter, ImageOps

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class Settings:
    """What the two sliders and the options in the window control."""

    paper_cleanup: int = 40      # 0-100: higher removes more paper grain and smudges
    line_darkness: int = 60      # 0-100: higher makes lines bolder and darker
    despeckle: bool = True       # remove isolated specks
    color: tuple = (0, 0, 0)     # line colour, RGB

    @property
    def lo(self) -> float:       # darkness that still counts as paper
        return 0.01 + 0.10 * self.paper_cleanup / 100.0

    @property
    def hi(self) -> float:       # darkness that becomes a fully solid line
        return max(self.lo + 0.02, 0.46 - 0.40 * self.line_darkness / 100.0)

    gamma = 0.8                  # < 1 lifts faint lines a little


def find_images(folder: Path, include_subfolders: bool = True, skip: Path | None = None) -> list[Path]:
    """Image files in a folder, sorted by name (so frame order is kept)."""
    folder = Path(folder)
    it: Iterable[Path] = folder.rglob("*") if include_subfolders else folder.glob("*")
    out = []
    for f in it:
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS:
            continue
        if skip is not None and (skip == f.parent or skip in f.parents):
            continue
        out.append(f)
    return sorted(out, key=lambda p: str(p).lower())


def load_image(path: Path) -> Image.Image:
    """Open a drawing, honouring phone-camera rotation and flattening alpha onto white."""
    im = Image.open(path)
    im.load()
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        im = im.convert("RGBA")
        white = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(white, im)
    return im.convert("L")


def _paper_estimate(gray: Image.Image) -> Image.Image:
    """A smooth picture of the paper with the drawing removed."""
    w, h = gray.size
    line_px = max(24, round(max(w, h) * 0.05))      # wider than any pencil line
    scale = max(1, round(max(w, h) / 320))          # work small: it is fast and smooth
    small = gray.resize((max(1, w // scale), max(1, h // scale)), Image.BILINEAR)
    k = max(3, (line_px // scale) | 1)              # odd kernel size
    pad = 2 * k                                     # extend the edges so borders stay clean
    arr = np.pad(np.asarray(small), pad, mode="edge")
    closed = Image.fromarray(arr).filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    closed = closed.filter(ImageFilter.GaussianBlur(k / 2))
    closed = closed.crop((pad, pad, pad + small.size[0], pad + small.size[1]))
    return closed.resize((w, h), Image.BICUBIC)


def darkness_map(gray: Image.Image) -> np.ndarray:
    """0.0 where there is only paper, up to 1.0 where the drawing is black.

    This is the slow step. The window keeps the result so that moving a
    slider only has to redo the fast step below.
    """
    g = np.asarray(gray, dtype=np.float32)
    paper = np.asarray(_paper_estimate(gray), dtype=np.float32)
    return 1.0 - np.clip(g / np.maximum(paper, 1.0), 0.0, 1.0)


def render(dark: np.ndarray, s: Settings) -> Image.Image:
    """Turn a darkness map into a transparent RGBA drawing."""
    a = np.clip((dark - s.lo) / (s.hi - s.lo), 0.0, 1.0) ** s.gamma
    alpha = Image.fromarray((a * 255 + 0.5).astype(np.uint8), "L")
    if s.despeckle:
        keep = alpha.filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.MaxFilter(3))
        alpha = Image.fromarray(np.minimum(np.asarray(alpha), np.asarray(keep)), "L")
    out = Image.new("RGBA", alpha.size, tuple(s.color) + (0,))
    out.putalpha(alpha)
    return out


def clean_file(src: Path, dst: Path, s: Settings) -> None:
    """Clean one drawing and save it as a PNG of the same pixel size."""
    with Image.open(src) as probe:
        dpi = probe.info.get("dpi")
    result = render(darkness_map(load_image(src)), s)
    dst.parent.mkdir(parents=True, exist_ok=True)
    result.save(dst, **({"dpi": dpi} if dpi else {}))


def default_output_folder(folder: Path) -> Path:
    folder = Path(folder)
    return folder.with_name(folder.name + "_clean")


def clean_folder(
    folder: Path,
    out_folder: Path | None = None,
    s: Settings | None = None,
    include_subfolders: bool = True,
    progress: Callable[[int, int, Path], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, list[tuple[Path, str]]]:
    """Clean every drawing in a folder. Originals are never changed.

    Returns (number cleaned, [(file, error message), ...]).
    """
    folder = Path(folder)
    out_folder = Path(out_folder) if out_folder else default_output_folder(folder)
    s = s or Settings()
    files = find_images(folder, include_subfolders, skip=out_folder)
    done, errors = 0, []
    for i, f in enumerate(files, 1):
        if should_stop and should_stop():
            break
        try:
            clean_file(f, (out_folder / f.relative_to(folder)).with_suffix(".png"), s)
            done += 1
        except Exception as e:  # keep going: one bad file should not stop a whole shot
            errors.append((f, str(e)))
        if progress:
            progress(i, len(files), f)
    return done, errors
