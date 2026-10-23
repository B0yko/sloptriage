"""Aggregate per-report rows into the published benchmark results."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sloptriage.bench.stats import proportion

FLAGGED = "refs_failed"
PER_CHECK = (
    "symbol_not_found",
    "out_of_range",
    "frame_inconsistent",
    "quote_not_found",
    "path_not_found",
)


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r["label"] == "valid"]
    invalid = [r for r in rows if r["label"] == "invalid"]
    slop = [r for r in invalid if r["slop_list"]]
    not_slop = [r for r in invalid if not r["slop_list"]]
    flagged = [r for r in rows if r["class"] == FLAGGED]

    def k(group: list[dict[str, Any]]) -> int:
        return sum(1 for r in group if r["class"] == FLAGGED)

    per_check = {}
    for name in PER_CHECK:
        per_check[name] = {
            "invalid": proportion(sum(1 for r in invalid if r["flags"].get(name)), len(invalid)),
            "valid": proportion(sum(1 for r in valid if r["flags"].get(name)), len(valid)),
        }
    classes: dict[str, dict[str, int]] = {}
    for label, group in (("valid", valid), ("invalid", invalid)):
        classes[label] = dict(Counter(r["class"] for r in group))
    return {
        "n": len(rows),
        "valid": len(valid),
        "invalid": len(invalid),
        "slop_listed": len(slop),
        "false_flag_rate_valid": proportion(k(valid), len(valid)),
        "precision_invalid": proportion(
            sum(1 for r in flagged if r["label"] == "invalid"), len(flagged)
        ),
        "recall_invalid": proportion(k(invalid), len(invalid)),
        "recall_invalid_slop_listed": proportion(k(slop), len(slop)),
        "recall_invalid_not_slop_listed": proportion(k(not_slop), len(not_slop)),
        "coverage": {
            "valid": proportion(sum(1 for r in valid if r["checked"] > 0), len(valid)),
            "invalid": proportion(sum(1 for r in invalid if r["checked"] > 0), len(invalid)),
        },
        "per_check": per_check,
        "classes": classes,
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in rows if "error" not in r and r["label"] in ("valid", "invalid")]
    out = _metrics(rows)
    out["by_era"] = {
        era: _metrics([r for r in rows if r["era"] == era]) for era in ("pre2023", "post2023")
    }
    out["false_flags"] = [
        {
            "id": r["id"],
            "url": f"https://hackerone.com/reports/{r['id']}",
            "ref": r["ref"],
            "hard": r["hard"],
            "verified": r["verified"],
            "checked": r["checked"],
            "flags": {name: n for name, n in r["flags"].items() if n},
        }
        for r in rows
        if r["label"] == "valid" and r["class"] == FLAGGED
    ]
    return out
