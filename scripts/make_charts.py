"""Render the README chart (light and dark SVG) from the committed benchmark results.

    uv run python scripts/make_charts.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = {
    "light": {"surface": "#fcfcfb", "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df", "bar": "#2a78d6"},
    "dark": {"surface": "#1a1a19", "text": "#f0efec", "muted": "#c3c2b7", "grid": "#3a3a37", "bar": "#3987e5"},
}
W, LEFT, RIGHT, TOP, ROW = 760, 250, 40, 70, 46
XMAX = 0.25


def svg(rows: list[tuple[str, dict]], theme: dict[str, str], title: str, note: str) -> str:
    h = TOP + ROW * len(rows) + 60
    plot = W - LEFT - RIGHT

    def x(v: float) -> float:
        return LEFT + plot * min(v, XMAX) / XMAX

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
        f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-label="{title}">',
        f'<rect width="{W}" height="{h}" rx="8" fill="{theme["surface"]}"/>',
        f'<text x="24" y="32" font-size="17" font-weight="600" fill="{theme["text"]}">{title}</text>',
        f'<text x="24" y="54" font-size="13" fill="{theme["muted"]}">{note}</text>',
    ]
    base = TOP + ROW * len(rows)
    for tick in (0, 0.05, 0.10, 0.15, 0.20, 0.25):
        tx = x(tick)
        out.append(f'<line x1="{tx:.1f}" y1="{TOP - 6}" x2="{tx:.1f}" y2="{base}" stroke="{theme["grid"]}" stroke-width="1"/>')
        out.append(f'<text x="{tx:.1f}" y="{base + 18}" font-size="12" text-anchor="middle" fill="{theme["muted"]}">{int(tick * 100)}%</text>')
    for i, (label, p) in enumerate(rows):
        cy = TOP + ROW * i + ROW / 2
        rate, (lo, hi) = p["rate"], p["ci95"]
        bw = max(x(rate) - LEFT, 2)
        out.append(f'<text x="{LEFT - 14}" y="{cy + 4:.1f}" font-size="13" text-anchor="end" fill="{theme["text"]}">{label}</text>')
        out.append(f'<path d="M{LEFT},{cy - 9:.1f} h{bw - 4:.1f} a4,4 0 0 1 4,4 v10 a4,4 0 0 1 -4,4 h-{bw - 4:.1f} z" fill="{theme["bar"]}"/>')
        out.append(f'<line x1="{x(lo):.1f}" y1="{cy:.1f}" x2="{x(hi):.1f}" y2="{cy:.1f}" stroke="{theme["text"]}" stroke-width="1.5"/>')
        for end in (lo, hi):
            out.append(f'<line x1="{x(end):.1f}" y1="{cy - 5:.1f}" x2="{x(end):.1f}" y2="{cy + 5:.1f}" stroke="{theme["text"]}" stroke-width="1.5"/>')
        out.append(
            f'<text x="{x(hi) + 8:.1f}" y="{cy + 4:.1f}" font-size="12" fill="{theme["muted"]}">'
            f'{100 * rate:.1f}% ({p["k"]}/{p["n"]})</text>'
        )
    out.append(f'<text x="{LEFT}" y="{h - 14}" font-size="12" fill="{theme["muted"]}">Whiskers: Wilson 95% interval</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    res = json.loads(sorted((ROOT / "bench" / "results").glob("2*.json"))[-1].read_text())
    h = res["splits"]["heldout"]
    rows = [
        ("Resolved (valid)", h["false_flag_rate_valid"]),
        ("Closed as not valid", h["recall_invalid"]),
        ("  of these, slop-listed", h["recall_invalid_slop_listed"]),
        ("  of these, not listed", h["recall_invalid_not_slop_listed"]),
    ]
    title = "Held-out curl reports classed refs_failed"
    note = f"{h['n']} reports, split frozen before thresholds existed; measured {res['date']}"
    for name, theme in THEMES.items():
        (ROOT / "docs" / "img" / f"heldout-{name}.svg").write_text(svg(rows, theme, title, note))
    print("wrote docs/img/heldout-{light,dark}.svg")


if __name__ == "__main__":
    main()
