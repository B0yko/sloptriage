"""Reproduction on the benchmark's real reports.

Which reports are tried:

- ``valid``: resolved reports of the chosen split that carry an inline C, C++ or shell PoC and name a
  version that maps to a release tag;
- ``slop``: reports on the curl maintainers' public list that carry such a PoC, in either split and
  whatever version they name (a missing version means the default branch as of the report date).

Rows keep only fixed fields: the report id, group, split, era, the ref that was built, and the
verdict. No report text, PoC output, function name or build log is stored.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sloptriage.bench.stats import proportion
from sloptriage.config import Config
from sloptriage.extract import Extraction, extract
from sloptriage.index.gitobj import GitRepo
from sloptriage.ingest import report_from_hackerone
from sloptriage.models import Report
from sloptriage.repro import ReproError, run_reproduction
from sloptriage.repro.runners import candidates_from_report
from sloptriage.repro.sandbox import Sandbox
from sloptriage.verdict import extract_context
from sloptriage.versions import Resolution, VersionResolver

KINDS = ("c", "cpp", "shell")
INFRASTRUCTURE_ERROR = "infrastructure_error"
UNBUILDABLE = ("build_failed", INFRASTRUCTURE_ERROR)
ROW_KEYS = {
    "id",
    "group",
    "split",
    "era",
    "slop_list",
    "ref",
    "ref_assumed",
    "verdict",
    "runner",
    "match",
    "runs",
}


@dataclass
class Selected:
    meta: dict[str, Any]
    group: str
    report: Report
    extraction: Extraction
    resolution: Resolution


def select_subset(
    metas: list[dict[str, Any]],
    load_doc: Callable[[int], dict[str, Any] | None],
    repo: GitRepo,
    cfg: Config,
    *,
    valid_ids: set[int],
    subset: str = "both",
) -> list[Selected]:
    resolver = VersionResolver(repo, cfg.version_tags, cfg.project)
    names = [cfg.project, *cfg.aliases]
    out: list[Selected] = []
    for meta in sorted(metas, key=lambda m: int(m["id"])):
        group: str | None = None
        if meta["label"] == "valid" and meta["id"] in valid_ids and subset in ("valid", "both"):
            group = "valid"
        elif meta.get("slop_list") and subset in ("slop", "both"):
            group = "slop"
        if group is None:
            continue
        doc = load_doc(int(meta["id"]))
        if doc is None:
            continue
        report = report_from_hackerone(doc)
        extraction = extract(report.text, extract_context(cfg))
        cands = candidates_from_report(report, extraction, cfg.repro, names)
        if not any(c.kind in KINDS and not c.unsupported for c in cands):
            continue
        resolution = resolver.resolve(extraction.claims, report.created_at)
        if group == "valid" and resolution.assumed:
            continue
        out.append(Selected(meta, group, report, extraction, resolution))
    return out


def _row(sel: Selected, split: str, result: dict[str, Any] | None) -> dict[str, Any]:
    meta = sel.meta
    return {
        "id": int(meta["id"]),
        "group": sel.group,
        "split": split,
        "era": meta["era"],
        "slop_list": bool(meta.get("slop_list")),
        "ref": sel.resolution.ref_label,
        "ref_assumed": sel.resolution.assumed,
        "verdict": result["verdict"] if result else INFRASTRUCTURE_ERROR,
        "runner": result.get("runner") if result else None,
        "match": result.get("match") if result else None,
        "runs": len(result["runs"]) if result else 0,
    }


def run_selected(
    selected: list[Selected],
    repo: GitRepo,
    cfg: Config,
    sandbox: Sandbox,
    *,
    split: str = "heldout",
    log: Callable[[str], None] = lambda _m: None,
) -> list[dict[str, Any]]:
    """Run every selected report; remove each version's image once its reports are done."""
    ordered = sorted(selected, key=lambda s: (s.resolution.ref_label, int(s.meta["id"])))
    discard = getattr(sandbox, "discard", None)
    rows: list[dict[str, Any]] = []
    for i, sel in enumerate(ordered):
        try:
            result: dict[str, Any] | None = run_reproduction(
                sel.report, sel.extraction, sel.resolution, repo, cfg, sandbox
            )
        except ReproError:
            result = None
        row = _row(sel, split, result)
        rows.append(row)
        log(f"{i + 1}/{len(ordered)} report {row['id']} at {row['ref']}: {row['verdict']}")
        last_of_commit = (
            i + 1 == len(ordered) or ordered[i + 1].resolution.commit != sel.resolution.commit
        )
        if last_of_commit and callable(discard):
            discard(sel.resolution.commit)
    return rows


def summarise_repro(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for group in ("valid", "slop"):
        g = [r for r in rows if r["group"] == group]
        by = Counter(r["verdict"] for r in g)
        buildable = [r for r in g if r["verdict"] not in UNBUILDABLE]
        reproduced = sorted(int(r["id"]) for r in g if r["verdict"] == "reproduced")
        entry: dict[str, Any] = {
            "attempted": len(g),
            "by_verdict": dict(by),
            "reproduced": proportion(len(reproduced), len(g)),
            "buildable": proportion(len(reproduced), len(buildable)),
        }
        entry["reproduced_ids" if group == "valid" else "false_reproductions"] = reproduced
        out[group] = entry
    return out
