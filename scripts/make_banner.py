"""Write the README banner in a light and a dark variant (docs/img/banner-*.svg).

    uv run python scripts/make_banner.py

Plain SVG text with a font stack, so nothing is embedded and the files stay small.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = {
    "light": {"accent": "#2a78d6", "text": "#0b0b0b", "muted": "#52514e", "edge": "#d3d2cc"},
    "dark": {"accent": "#3987e5", "text": "#f0efec", "muted": "#a9a89f", "edge": "#3a3a36"},
}
CHIPS = ("no LLM", "CLI + GitHub Action", "optional sandboxed PoC rerun")
SANS = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def banner(theme: dict[str, str]) -> str:
    chips = []
    x = 94.0
    for label in CHIPS:
        width = len(label) * 7.9 + 26
        chips.append(
            f'<rect x="{x:.1f}" y="136" width="{width:.1f}" height="28" rx="14" fill="none" '
            f'stroke="{theme["edge"]}" stroke-width="1.5"/>'
            f'<text x="{x + 13:.1f}" y="155" font-family="{MONO}" font-size="13" '
            f'fill="{theme["muted"]}">{label}</text>'
        )
        x += width + 10
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="880" height="190" viewBox="0 0 880 190" \
role="img" aria-label="sloptriage: check bug and security reports against the code before you read them">
<g transform="translate(0,24) scale(1.125)">
<rect width="64" height="64" rx="14" fill="{theme["accent"]}"/>
<rect x="13" y="16" width="30" height="6" rx="3" fill="#fff"/>
<rect x="13" y="28" width="22" height="6" rx="3" fill="#fff"/>
<rect x="13" y="40" width="14" height="6" rx="3" fill="#fff"/>
<circle cx="45" cy="44" r="13" fill="#fff" stroke="{theme["accent"]}" stroke-width="2.5"/>
<path d="M39.5 44.5 L43.5 48.5 L51 39.5" fill="none" stroke="{theme["accent"]}" stroke-width="3.4" \
stroke-linecap="round" stroke-linejoin="round"/>
</g>
<text x="92" y="76" font-family="{SANS}" font-size="54" font-weight="700" letter-spacing="-1" \
fill="{theme["text"]}">sloptriage</text>
<text x="94" y="112" font-family="{SANS}" font-size="20" fill="{theme["muted"]}">Check bug and security \
reports against the code before you read them.</text>
{"".join(chips)}
</svg>
"""


def main() -> int:
    out = ROOT / "docs" / "img"
    out.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        path = out / f"banner-{name}.svg"
        path.write_text(banner(theme), encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
