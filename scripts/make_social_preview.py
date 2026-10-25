"""Render `.github/social-preview.png` (1280x640) from the committed benchmark results.

    uv run --with pillow python scripts/make_social_preview.py

The left side carries the name, the one-line value and the held-out headline number; the right side
shows a real result (three functions that do not exist, one file that does) in the shape of the
terminal output. The image is drawn at twice the size and scaled down; no metadata is written.
Fonts are the system's Helvetica and Menlo on macOS, with DejaVu as the fallback.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".github" / "social-preview.png"
W, H, S = 1280, 640, 2

BG = "#121211"
PANEL = "#1b1b19"
EDGE = "#33332f"
TEXT = "#f0efec"
MUTED = "#a9a89f"
FAINT = "#6f6e68"
BLUE = "#3987e5"
GREEN = "#3ecf8e"
RED = "#f0616d"

SANS = ["/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
SANS_BOLD = ["/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
MONO = ["/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
MONO_BOLD = ["/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]


def font(paths: list[str], size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in paths:
        if Path(path).exists():
            index = 1 if bold and path.endswith(".ttc") else 0
            return ImageFont.truetype(path, size * S, index=index)
    raise SystemExit("no usable font found")


def s(value: float) -> int:
    return round(value * S)


def text(
    d: ImageDraw.ImageDraw, xy: tuple[float, float], value: str, f: ImageFont.FreeTypeFont, fill: str
) -> float:
    d.text((s(xy[0]), s(xy[1])), value, font=f, fill=fill)
    return d.textlength(value, font=f) / S


def mark(d: ImageDraw.ImageDraw, x: float, y: float, size: float) -> None:
    """A page with three lines of text and a check in a circle: every line gets checked."""
    k = size / 64
    d.rounded_rectangle(
        [s(x), s(y), s(x + size), s(y + size)], radius=s(14 * k), fill=BLUE
    )
    for yy, length in ((19, 30), (31, 22), (43, 14)):
        d.rounded_rectangle(
            [s(x + 13 * k), s(y + (yy - 3) * k), s(x + (13 + length) * k), s(y + (yy + 3) * k)],
            radius=s(3 * k),
            fill="#ffffff",
        )
    cx, cy, r = x + 45 * k, y + 44 * k, 13 * k
    d.ellipse([s(cx - r), s(cy - r), s(cx + r), s(cy + r)], fill="#ffffff", outline=BLUE, width=s(2.5 * k))
    d.line(
        [(s(cx - 5.5 * k), s(cy + 0.5 * k)), (s(cx - 1.5 * k), s(cy + 4.5 * k)), (s(cx + 6 * k), s(cy - 4.5 * k))],
        fill=BLUE,
        width=s(3.4 * k),
        joint="curve",
    )


def badge(d: ImageDraw.ImageDraw, cx: float, cy: float, ok: bool) -> None:
    r = 15
    d.ellipse([s(cx - r), s(cy - r), s(cx + r), s(cy + r)], fill=GREEN if ok else RED)
    if ok:
        tick = [(cx - 6, cy + 0.5), (cx - 1.5, cy + 5), (cx + 7, cy - 5)]
        d.line([(s(a), s(b)) for a, b in tick], fill=BG, width=s(3.6), joint="curve")
        return
    for a, b in (((-5.5, -5.5), (5.5, 5.5)), ((-5.5, 5.5), (5.5, -5.5))):
        d.line([(s(cx + a[0]), s(cy + a[1])), (s(cx + b[0]), s(cy + b[1]))], fill=BG, width=s(3.6))


def pill(d: ImageDraw.ImageDraw, x: float, y: float, label: str, f: ImageFont.FreeTypeFont) -> float:
    width = d.textlength(label, font=f) / S + 28
    d.rounded_rectangle([s(x), s(y), s(x + width), s(y + 38)], radius=s(19), outline=EDGE, width=s(2))
    text(d, (x + 14, y + 8), label, f, MUTED)
    return x + width + 12


def headline() -> tuple[int, int, int, int, int]:
    results = sorted((ROOT / "bench" / "results").glob("2*.json"))
    h = json.loads(results[-1].read_text())["splits"]["heldout"]
    p, ff = h["precision_invalid"], h["false_flag_rate_valid"]
    return p["k"], p["n"], ff["k"], ff["n"], h["n"]


def main() -> int:
    k, n, ffk, ffn, total = headline()
    img = Image.new("RGB", (W * S, H * S), BG)
    glow = Image.new("RGB", (W * S, H * S), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([s(780), s(-260), s(1380), s(300)], fill="#1c3558")
    glow = glow.filter(ImageFilter.GaussianBlur(s(110)))
    img = Image.blend(img, glow, 0.55)
    d = ImageDraw.Draw(img)

    # left column
    mark(d, 72, 66, 60)
    text(d, (148, 66), "sloptriage", font(SANS_BOLD, 62, True), TEXT)
    tag = font(SANS, 31)
    text(d, (72, 162), "Check bug and security reports", tag, MUTED)
    text(d, (72, 204), "against the code before you read them.", tag, MUTED)
    chip = font(MONO, 18)
    x = 72
    for label in ("no LLM", "CLI + Action", "PoC sandbox"):
        x = pill(d, x, 270, label, chip)
    text(d, (72, 336), f"{k} of {n}", font(SANS_BOLD, 118, True), BLUE)
    lab = font(SANS, 27)
    text(d, (72, 468), "flagged held-out curl reports were", lab, TEXT)
    text(d, (72, 502), "closed as not valid", lab, TEXT)
    text(d, (72, 548), f"{ffk} of {ffn} resolved reports flagged · {total} held-out reports", font(SANS, 20), FAINT)
    text(d, (72, 590), "github.com/B0yko/sloptriage  ·  Apache-2.0", font(MONO, 18), FAINT)

    # right panel: a real result
    px, py, pw, ph = 664, 78, 556, 484
    d.rounded_rectangle([s(px), s(py), s(px + pw), s(py + ph)], radius=s(22), fill=PANEL, outline=EDGE, width=s(2))
    for i in range(3):
        cx = px + 30 + i * 22
        d.ellipse([s(cx - 6), s(py + 26 - 6), s(cx + 6), s(py + 26 + 6)], fill="#3a3a36")
    d.line([(s(px), s(py + 52)), (s(px + pw), s(py + 52))], fill=EDGE, width=s(2))
    text(d, (px + 100, py + 16), "$ sloptriage check report.md", font(MONO, 18), MUTED)
    rows = [
        (False, "pk_header_merge_continuation()", "no definition found at v1.2.0"),
        (False, "pk_buf_grow_exact()", "no definition found at v1.2.0"),
        (False, "pk_header_measure()", "no definition found at v1.2.0"),
        (True, "src/header.c", "exists"),
    ]
    name_f, detail_f = font(MONO_BOLD, 22, True), font(MONO, 17)
    y = py + 84
    for ok, name, detail in rows:
        badge(d, px + 42, y + 22, ok)
        text(d, (px + 72, y + 2), name, name_f, TEXT)
        text(d, (px + 72, y + 32), detail, detail_f, MUTED)
        y += 76
    d.line([(s(px + 28), s(y + 4)), (s(px + pw - 28), s(y + 4))], fill=EDGE, width=s(2))
    label_f = font(MONO_BOLD, 20, True)
    width = d.textlength("refs_failed", font=label_f) / S + 30
    d.rounded_rectangle([s(px + 28), s(y + 26), s(px + 28 + width), s(y + 64)], radius=s(19), fill="#3b1d22", outline=RED, width=s(2))
    text(d, (px + 43, y + 35), "refs_failed", label_f, RED)
    text(d, (px + 28 + width + 16, y + 37), "labels: triage:refs-failed", font(MONO, 17), FAINT)

    out = img.resize((W, H), Image.Resampling.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, "PNG", optimize=True)  # no pnginfo: nothing but pixels is written
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
