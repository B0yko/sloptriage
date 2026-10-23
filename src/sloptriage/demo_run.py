"""``sloptriage demo``: the checks on the bundled projects and reports, offline."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from sloptriage import demo
from sloptriage.config import load_config
from sloptriage.index import IndexSet
from sloptriage.index.gitobj import GitRepo
from sloptriage.ingest import load_report
from sloptriage.render import build_verdict, render_text
from sloptriage.verdict import run_reference_check


def check_all() -> list[tuple[demo.DemoReport, dict[str, Any]]]:
    setups = {}
    for project in demo.PROJECTS:
        path = demo.materialize(project)
        repo = GitRepo(path)
        cfg = load_config(demo.config_path(project))
        setups[project] = (repo, IndexSet(repo, str(path), cfg.paths_ignore), cfg)
    out = []
    for rep in demo.reports():
        repo, iset, cfg = setups[rep.project]
        result = run_reference_check(load_report(str(rep.path)), repo, iset, cfg)
        out.append((rep, build_verdict(result, cfg)))
    return out


def run_demo(*, show: str | None = None) -> int:
    started = time.perf_counter()
    print("sloptriage demo: two small projects with known bugs (parsekit in C, kvconf in Python)")
    print("and 60 reports against them, 20 valid and 40 low-quality. No network is used.\n")
    rows = check_all()
    if show:
        match = [v for r, v in rows if r.file.startswith(show.zfill(2)) or r.file == show]
        if not match:
            print(f"no demo report {show!r}")
            return 2
        print(render_text(match[0]))
        return 0
    counts: Counter[tuple[str, str]] = Counter((r.label, v["references"]["class"]) for r, v in rows)
    classes = ["refs_failed", "refs_mixed", "refs_thin", "refs_verified", "refs_none"]
    print(f"{'':10}" + "".join(f"{c:>15}" for c in classes))
    for label in ("valid", "invalid"):
        print(f"{label:10}" + "".join(f"{counts[(label, c)]:>15}" for c in classes))
    flagged_invalid = counts[("invalid", "refs_failed")]
    flagged_valid = counts[("valid", "refs_failed")]
    print(
        f"\nrefs_failed on {flagged_invalid} of 40 low-quality reports and {flagged_valid} of 20 valid ones."
    )
    print(
        "The other low-quality reports cite code that exists: the reference check verifies citations,"
    )
    print("not whether an issue is real.\n")
    example = next((v for r, v in rows if "frame_mismatch" in r.failure_modes), rows[0][1])
    name = next(r.file for r, v in rows if v is example)
    print(f"Example: demo report {name}\n")
    print(render_text(example))
    print(f"\nDone in {time.perf_counter() - started:.1f}s. Try: sloptriage demo --show 32")
    return 0
