"""``sloptriage bench fetch|run|report``."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sloptriage import __version__
from sloptriage.paths import cache_dir

FREEZE_COMMIT = "c33cdd95c06913bb2bbf6c90dede70e91726b5a6"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def bench_fetch(split: str) -> int:
    from sloptriage.bench.fetch import body_sha256, fetch_reports
    from sloptriage.bench.manifest import ids_for_split, load_reports
    from sloptriage.bench.run import report_cache

    meta = {r["id"]: r for r in load_reports()}
    ids = ids_for_split(split)
    print(
        f"Fetching {len(ids)} public report JSON files into {report_cache()} (1 request per second)."
    )
    res = fetch_reports(ids, report_cache(), log=_log)
    edited = 0
    for rid in ids:
        path = report_cache() / f"{rid}.json"
        if (
            path.exists()
            and body_sha256(json.loads(path.read_text(encoding="utf-8")))
            != meta[rid]["body_sha256"]
        ):
            edited += 1
    print(
        f"fetched {len(res.fetched)}, already cached {len(res.cached)}, failed {len(res.failed)}, "
        f"edited since the freeze {edited}"
    )
    return 3 if res.stopped_early else 0


def bench_run(args: argparse.Namespace) -> int:
    from collections import Counter

    from sloptriage.bench.report import summarise
    from sloptriage.bench.run import run_split

    rows = run_split(args.split, args.repo, jobs=args.jobs, log=_log)
    out = (
        Path(args.out)
        if args.out
        else cache_dir("bench") / f"rows-{args.split}-{date.today().isoformat()}.json"
    )
    out.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    counts = Counter((r.get("label"), r.get("class")) for r in rows)
    for key in sorted(counts, key=str):
        print(f"{key[0]:8} {key[1]:14} {counts[key]}")
    s = summarise(rows)
    ff, rec = s["false_flag_rate_valid"], s["recall_invalid"]
    print(f"false flags on valid: {ff['k']}/{ff['n']}  recall on invalid: {rec['k']}/{rec['n']}")
    print(f"rows written to {out}")
    return 0


def bench_repro(args: argparse.Namespace) -> int:
    from sloptriage.bench.manifest import ids_for_split, load_reports
    from sloptriage.bench.repro import run_selected, select_subset, summarise_repro
    from sloptriage.bench.run import _load, curl_config
    from sloptriage.index.gitobj import open_repo
    from sloptriage.repro.recipes import recipe_from_config
    from sloptriage.repro.runtime import detect_runtime
    from sloptriage.repro.sandbox import ContainerSandbox

    cfg = curl_config()
    repo = open_repo(args.repo)
    runtime = detect_runtime(cfg.repro.runtime)
    chosen = select_subset(
        load_reports(),
        _load,
        repo,
        cfg,
        valid_ids=set(ids_for_split(args.split)),
        subset=args.subset,
    )
    if args.limit:
        chosen = chosen[: args.limit]
    _log(
        f"{len(chosen)} reports selected "
        f"({sum(1 for s in chosen if s.group == 'valid')} valid, "
        f"{sum(1 for s in chosen if s.group == 'slop')} listed); building curl in {runtime.name}"
    )
    sandbox = ContainerSandbox(
        runtime,
        repo,
        recipe_from_config(cfg.repro, cfg.project),
        cfg.project,
        cfg.repro.limits,
        _log,
    )
    rows = run_selected(chosen, repo, cfg, sandbox, split=args.split, log=_log)
    doc = {
        "schema": "sloptriage-bench-repro/1",
        "date": date.today().isoformat(),
        "tool_version": __version__,
        "hardware": args.hardware,
        "project": "curl",
        "freeze_commit": FREEZE_COMMIT,
        "valid_split": args.split,
        "subset": args.subset,
        "summary": summarise_repro(rows),
        "rows": rows,
    }
    out = Path(args.out) if args.out else Path("bench/results") / f"repro-{doc['date']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    for group, s in doc["summary"].items():
        print(f"{group}: {s['reproduced']['k']} of {s['attempted']} reproduced; {s['by_verdict']}")
    print(f"wrote {out}")
    return 0


def bench_report(args: argparse.Namespace) -> int:
    from sloptriage.bench.report import summarise
    from sloptriage.config import Thresholds

    splits: dict[str, Any] = {}
    for path in args.rows:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        name = (
            "heldout"
            if "heldout" in Path(path).name
            else "dev"
            if "dev" in Path(path).name
            else Path(path).stem
        )
        splits[name] = summarise(rows)
    doc = {
        "schema": "sloptriage-bench-results/1",
        "date": date.today().isoformat(),
        "tool_version": __version__,
        "hardware": args.hardware,
        "project": "curl",
        "freeze_commit": FREEZE_COMMIT,
        "thresholds": vars(Thresholds()),
        "splits": splits,
    }
    out = Path(args.out) if args.out else Path("bench/results") / f"{doc['date']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def bench_main(args: argparse.Namespace) -> int:
    if args.bench_command == "fetch":
        return bench_fetch(args.split)
    if args.bench_command == "run":
        return bench_run(args)
    if args.bench_command == "repro":
        return bench_repro(args)
    return bench_report(args)
