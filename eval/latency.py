"""Latency of the reference check on curl.

1. Cold index: index one curl tag into an empty cache and time it.
2. Warm checks: check every held-out report against an already indexed ref,
   one at a time, and report p50 and p95 of the per-report wall time.

    uv run python eval/latency.py --tag curl-8_17_0 --out bench/results/latency-<date>.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import tempfile
import time
from datetime import date
from pathlib import Path

REPO = "https://github.com/curl/curl"


def cold_index(tag: str) -> float:
    from sloptriage.index import IndexSet
    from sloptriage.index.gitobj import open_repo

    repo = open_repo(REPO)  # the clone itself is reused; only the index cache is empty
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("XDG_CACHE_HOME")
        clone = repo.path
        os.environ["XDG_CACHE_HOME"] = tmp
        try:
            from sloptriage.index.gitobj import GitRepo

            iset = IndexSet(GitRepo(clone), REPO)
            sha = iset.repo.resolve_commit(tag)
            assert sha, tag
            t = time.perf_counter()
            iset.get(sha)
            seconds = time.perf_counter() - t
            iset.close()
        finally:
            if old is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = old
    return seconds


def warm_checks(split: str) -> list[float]:
    from sloptriage.bench.manifest import ids_for_split
    from sloptriage.bench.run import _load, curl_config, prepare_indexes
    from sloptriage.index import IndexSet
    from sloptriage.index.gitobj import open_repo
    from sloptriage.ingest import report_from_hackerone
    from sloptriage.verdict import run_reference_check

    cfg = curl_config()
    ids = ids_for_split(split)
    prepare_indexes(ids, REPO, cfg, lambda _m: None)
    repo = open_repo(REPO)
    iset = IndexSet(repo, REPO, cfg.paths_ignore)
    times = []
    for rid in ids:
        doc = _load(rid)
        if doc is None:
            continue
        t = time.perf_counter()
        run_reference_check(report_from_hackerone(doc), repo, iset, cfg)
        times.append(time.perf_counter() - t)
    return times


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="curl-8_17_0")
    ap.add_argument("--split", default="heldout")
    ap.add_argument("--hardware", default=platform.machine())
    ap.add_argument("--out")
    args = ap.parse_args()
    cold = cold_index(args.tag)
    times = sorted(warm_checks(args.split))
    p95 = times[max(0, int(round(0.95 * len(times))) - 1)]
    doc = {
        "date": date.today().isoformat(),
        "hardware": args.hardware,
        "cold_index": {"tag": args.tag, "seconds": round(cold, 2)},
        "warm_check": {
            "split": args.split,
            "reports": len(times),
            "p50_seconds": round(statistics.median(times), 3),
            "p95_seconds": round(p95, 3),
            "max_seconds": round(times[-1], 3),
        },
    }
    text = json.dumps(doc, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
