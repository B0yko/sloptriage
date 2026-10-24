"""``sloptriage demo``: the checks on the bundled projects and reports, offline."""

from __future__ import annotations

import sys
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from sloptriage import demo
from sloptriage.config import load_config
from sloptriage.index import IndexSet
from sloptriage.index.gitobj import GitRepo
from sloptriage.ingest import load_report
from sloptriage.render import build_verdict, render_text
from sloptriage.repro import run_reproduction
from sloptriage.repro.errors import ReproError
from sloptriage.repro.runtime import RuntimeUnavailable, detect_runtime
from sloptriage.verdict import run_reference_check


def check_all(
    *, repro: bool = False, only: str | None = None, progress: Callable[[str], None] | None = None
) -> list[tuple[demo.DemoReport, dict[str, Any]]]:
    """Reference-check the demo reports; with ``repro``, also run the PoCs of those that have one."""
    setups = {}
    for project in demo.PROJECTS:
        path = demo.materialize(project)
        repo = GitRepo(path)
        cfg = load_config(demo.config_path(project))
        setups[project] = (repo, IndexSet(repo, str(path), cfg.paths_ignore), cfg)
    out = []
    for rep in demo.reports():
        if only and not (rep.file.startswith(only.zfill(2)) or rep.file == only):
            continue
        repo, iset, cfg = setups[rep.project]
        result = run_reference_check(load_report(str(rep.path)), repo, iset, cfg)
        reproduction = None
        if repro and rep.poc != "none":
            if progress:
                progress(f"{rep.file}: running the PoC")
            reproduction = run_reproduction(
                result.report, result.extraction, result.resolution, repo, cfg, progress=progress
            )
        out.append((rep, build_verdict(result, cfg, reproduction)))
    return out


def _say(msg: str) -> None:
    print(f"sloptriage: {msg}", file=sys.stderr)


def reproduction_summary(
    rows: list[tuple[demo.DemoReport, dict[str, Any]]],
) -> tuple[list[str], bool]:
    """Lines for the terminal and whether every result matches the labels."""
    lines = [f"{'report':44}{'expected':>12}  {'result':<20}"]
    good = True
    valid_ok = valid_n = bad_hits = bad_n = 0
    for rep, verdict in rows:
        got = (verdict["reproduction"] or {}).get("verdict", "-")
        if rep.poc == "none":
            continue
        want = "reproduces" if rep.poc_reproduces else "does not"
        hit = got == "reproduced"
        if rep.poc_reproduces:
            valid_n += 1
            valid_ok += hit
        else:
            bad_n += 1
            bad_hits += hit
        mark = "" if hit == rep.poc_reproduces else "   <-- differs from the label"
        good = good and hit == rep.poc_reproduces
        lines.append(f"{rep.file:44}{want:>12}  {got:<20}{mark}")
    lines.append("")
    lines.append(f"Reports with a working PoC: {valid_ok} of {valid_n} reproduced.")
    lines.append(f"Low-quality reports with a PoC: {bad_hits} of {bad_n} reproduced (expected 0).")
    return lines, good


def run_demo(*, show: str | None = None, repro: bool = False) -> int:
    started = time.perf_counter()
    if repro:
        try:
            runtime = detect_runtime()
        except RuntimeUnavailable as exc:
            raise ReproError(str(exc)) from exc
        print(f"sloptriage demo --repro: PoCs run in {runtime.name} containers (no network).")
        print("The first run builds one image per demo release; later runs reuse them.\n")
        rows = check_all(repro=True, only=show, progress=_say)
        lines, good = reproduction_summary(rows)
        print("\n".join(lines))
        print(f"\nDone in {time.perf_counter() - started:.0f}s.")
        return 0 if good else 1
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
    try:
        runtime = detect_runtime()
        print(
            f"\nReproduction is available ({runtime.name} found). `sloptriage demo --repro` builds the demo"
            " projects and runs the 30 PoCs in locked-down containers; the first run takes a few minutes."
        )
    except RuntimeUnavailable:
        print(
            "\nReproduction needs Docker or Podman, and neither is available here. The reference check"
            " above did not need it."
        )
    print(f"\nDone in {time.perf_counter() - started:.1f}s. Try: sloptriage demo --show 32")
    return 0
