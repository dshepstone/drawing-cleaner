import numpy as np
from PIL import Image, ImageDraw

from drawing_cleaner.engine import Settings, clean_folder, darkness_map, load_image, render


def fake_drawing(w=640, h=360, pencil=90):
    """Grey paper that gets darker toward the top, with one pencil circle."""
    y = np.linspace(150, 215, h)[:, None]
    rng = np.random.default_rng(1)
    paper = np.clip(y + rng.normal(0, 1.5, (h, w)), 0, 255).astype(np.uint8)
    im = Image.fromarray(paper, "L")
    ImageDraw.Draw(im).ellipse((250, 110, 390, 250), outline=pencil, width=3)
    return im


def test_paper_becomes_transparent_and_line_stays(tmp_path):
    out = render(darkness_map(fake_drawing()), Settings())
    a = np.asarray(out)[..., 3]
    assert out.mode == "RGBA" and out.size == (640, 360)
    assert a[:40].max() == 0 and a[-40:].max() == 0          # dark top and bright bottom both clear
    assert a[180, 250:254].max() > 200                        # left edge of the circle is solid
    assert (a > 0).mean() < 0.03                              # only the line is left


def test_sliders_move_the_right_way():
    d = darkness_map(fake_drawing(pencil=150))               # a faint line
    ink = lambda **k: int(np.asarray(render(d, Settings(**k)))[..., 3].sum())
    assert ink(line_darkness=90) > ink(line_darkness=20)
    assert ink(paper_cleanup=0, despeckle=False) > ink(paper_cleanup=100, despeckle=False)


def test_folder_run_keeps_names_and_originals(tmp_path):
    src = tmp_path / "shot"
    (src / "ball").mkdir(parents=True)
    fake_drawing().save(src / "ball" / "ball.0001.jpg")
    fake_drawing().convert("RGBA").save(src / "bg.0001.png")
    (src / "notes.txt").write_text("not an image")
    before = (src / "bg.0001.png").read_bytes()
    seen = []
    done, errors = clean_folder(src, progress=lambda i, n, f: seen.append((i, n)))
    out = tmp_path / "shot_clean"
    assert (done, errors) == (2, []) and seen[-1] == (2, 2)
    assert (out / "ball" / "ball.0001.png").exists() and (out / "bg.0001.png").exists()
    assert (src / "bg.0001.png").read_bytes() == before
    assert Image.open(out / "bg.0001.png").mode == "RGBA"
    assert clean_folder(src)[0] == 2                          # second run does not re-read its own output


def test_load_flattens_transparency(tmp_path):
    p = tmp_path / "t.png"
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(p)
    assert np.asarray(load_image(p)).min() == 255
