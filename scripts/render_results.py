"""Render the README result tables from the committed benchmark files.

    uv run python scripts/render_results.py          # rewrite the README section
    uv run python scripts/render_results.py --check  # fail when the README is out of date

Sources: bench/results/<date>.json (from `sloptriage bench report`),
bench/results/latency-<date>.json (from eval/latency.py) and the bundled
synthetic set (checked live; it is deterministic and offline).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
START, END = "<!-- results:start -->", "<!-- results:end -->"
HEAD_START, HEAD_END = "<!-- headline:start -->", "<!-- headline:end -->"
CHECK_NAMES = {
    "symbol_not_found": "a function, macro or type that is not defined",
    "path_not_found": "a file that does not exist",
    "out_of_range": "a line past the end of its file",
    "frame_inconsistent": "a stack frame whose line is outside the named function",
    "quote_not_found": "quoted code that does not appear in the project",
}


def pct(p: dict[str, Any]) -> str:
    if not p["n"]:
        return "n/a"
    lo, hi = p["ci95"]
    return f"{p['k']}/{p['n']} ({100 * p['rate']:.1f}%, {100 * lo:.1f}–{100 * hi:.1f}%)"


def latest(pattern: str) -> Path:
    files = sorted((ROOT / "bench" / "results").glob(pattern))
    if not files:
        raise SystemExit(f"no {pattern} in bench/results")
    return files[-1]


def synthetic() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "src"))
    from sloptriage.demo_run import check_all

    per_mode: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    valid = [0, 0]
    for rep, verdict in check_all():
        flagged = verdict["references"]["class"] == "refs_failed"
        if rep.label == "valid":
            valid[0] += flagged
            valid[1] += 1
            continue
        for mode in rep.failure_modes or ("none",):
            per_mode[mode][0] += flagged
            per_mode[mode][1] += 1
    return {"valid": valid, "modes": dict(sorted(per_mode.items()))}


def headline(res: dict[str, Any]) -> str:
    h = res["splits"]["heldout"]
    rec, ff, prec = h["recall_invalid"], h["false_flag_rate_valid"], h["precision_invalid"]
    return (
        f"On {rec['n']} held-out curl reports that were closed as not applicable, informative or spam, sloptriage "
        f"found cited references that do not exist at the stated version in {rec['k']} "
        f"({100 * rec['rate']:.1f}%, 95% CI {100 * rec['ci95'][0]:.1f}–{100 * rec['ci95'][1]:.1f}%); it flagged "
        f"{ff['k']} of {ff['n']} resolved reports. When it flags a report, the report was closed as not valid "
        f"{prec['k']} times out of {prec['n']}."
    )


def section(res: dict[str, Any], lat: dict[str, Any], syn: dict[str, Any]) -> str:
    h = res["splits"]["heldout"]
    d = res["splits"]["dev"]
    era = h["by_era"]
    lines = [
        f"Measured on {res['date']} on a {res['hardware']} with `sloptriage {res['tool_version']}`; split frozen in "
        f"commit `{res['freeze_commit'][:7]}`; thresholds `hard_fail_min = {res['thresholds']['hard_fail_min']}`, "
        f"`min_verified_share = {res['thresholds']['min_verified_share']}` (chosen on the dev split only). "
        "Intervals are Wilson 95% intervals.",
        "",
        "**Held-out split: reports classed `refs_failed`**",
        "",
        "| Group | Classed `refs_failed` |",
        "|---|---|",
        f"| Resolved (valid) | {pct(h['false_flag_rate_valid'])} |",
        f"| Not applicable, informative or spam (invalid) | {pct(h['recall_invalid'])} |",
        f"| Invalid, listed in the curl slop gist | {pct(h['recall_invalid_slop_listed'])} |",
        f"| Invalid, not listed | {pct(h['recall_invalid_not_slop_listed'])} |",
        f"| Valid, disclosed before 2023 | {pct(era['pre2023']['false_flag_rate_valid'])} |",
        f"| Invalid, disclosed before 2023 | {pct(era['pre2023']['recall_invalid'])} |",
        f"| Valid, disclosed 2023 or later | {pct(era['post2023']['false_flag_rate_valid'])} |",
        f"| Invalid, disclosed 2023 or later | {pct(era['post2023']['recall_invalid'])} |",
        "",
        f"Precision for invalid: {pct(h['precision_invalid'])}. Coverage (at least one checkable high-confidence "
        f"claim): {pct(h['coverage']['invalid'])} of invalid and {pct(h['coverage']['valid'])} of valid reports. "
        f"Dev split for comparison: {pct(d['false_flag_rate_valid'])} valid and {pct(d['recall_invalid'])} invalid "
        "reports classed `refs_failed`.",
        "",
        "**Per check, held-out split: share of reports with at least one high-confidence citation of**",
        "",
        "| Citation | Invalid reports | Valid reports |",
        "|---|---|---|",
    ]
    for key, name in CHECK_NAMES.items():
        pc = h["per_check"][key]
        lines.append(f"| {name} | {pct(pc['invalid'])} | {pct(pc['valid'])} |")
    lines += [
        "",
        "**Synthetic set (consistency with the specification, not a measure of real-world accuracy)**",
        "",
        "| Failure mode | Reports | Classed `refs_failed` |",
        "|---|---|---|",
    ]
    for mode, (k, n) in syn["modes"].items():
        lines.append(f"| `{mode}` | {n} | {k} |")
    lines.append(f"| valid reports | {syn['valid'][1]} | {syn['valid'][0]} |")
    lines += [
        "",
        "PoC-only failure modes (a PoC that overflows its own buffer, never calls the library, does not compile or",
        "uses a normal input) cite code that exists, so the reference check does not flag them.",
        "",
        "**Latency**",
        "",
        f"Cold index of `{lat['cold_index']['tag']}`: {lat['cold_index']['seconds']:.1f} s. Checking each of the "
        f"{lat['warm_check']['reports']} held-out reports against an indexed ref: p50 "
        f"{lat['warm_check']['p50_seconds']:.2f} s, p95 {lat['warm_check']['p95_seconds']:.2f} s "
        f"({lat['hardware']}, {lat['date']}).",
        "",
        "**Every valid held-out report classed `refs_failed`**",
        "",
    ]
    if not h["false_flags"]:
        lines.append("None.")
    for ff in h["false_flags"]:
        what = ", ".join(f"{n} × {CHECK_NAMES.get(k, k)}" for k, n in ff["flags"].items())
        lines.append(
            f"- [#{ff['id']}]({ff['url']}), checked at `{ff['ref']}`: {ff['hard']} hard failures "
            f"({what}) against {ff['verified']} verified of {ff['checked']} checked."
        )
    return "\n".join(lines)


def splice(text: str, start: str, end: str, body: str) -> str:
    a, b = text.index(start) + len(start), text.index(end)
    return text[:a] + "\n" + body + "\n" + text[b:]


def main() -> int:
    res = json.loads(latest("2*.json").read_text())
    lat = json.loads(latest("latency-*.json").read_text())
    syn = synthetic()
    text = README.read_text(encoding="utf-8")
    new = splice(text, START, END, section(res, lat, syn))
    new = splice(new, HEAD_START, HEAD_END, headline(res))
    if "--check" in sys.argv:
        if new != text:
            print("README results are out of date: run scripts/render_results.py", file=sys.stderr)
            return 1
        print("README results match bench/results")
        return 0
    README.write_text(new, encoding="utf-8")
    print("README results updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
