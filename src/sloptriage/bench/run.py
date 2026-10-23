"""Evaluate the reference check on a split of the frozen benchmark."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from sloptriage.bench.fetch import body_sha256
from sloptriage.bench.manifest import ids_for_split, load_reports
from sloptriage.config import Config, Thresholds, load_config
from sloptriage.extract import extract
from sloptriage.index import IndexSet
from sloptriage.index.gitobj import open_repo
from sloptriage.ingest import report_from_hackerone
from sloptriage.paths import bundled, cache_dir
from sloptriage.verdict import aggregate, extract_context, run_reference_check
from sloptriage.versions import VersionResolver, history_sample

FLAG_STATUSES = {
    "symbol_not_found": {"symbol:not_found"},
    "out_of_range": {"line:out_of_range"},
    "frame_inconsistent": {"frame:outside_function", "frame:function_not_in_file"},
    "quote_not_found": {"quote:not_found"},
    "path_not_found": {"path:not_found"},
}


def curl_config() -> Config:
    return load_config(bundled("examples", "curl", ".sloptriage.yml"))


def report_cache() -> Path:
    return cache_dir("bench", "hackerone")


def _load(rid: int) -> dict[str, Any] | None:
    path = report_cache() / f"{rid}.json"
    if not path.exists():
        return None
    doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return doc


def prepare_indexes(
    ids: list[int], repo_location: str, cfg: Config, log: Callable[[str], None]
) -> dict[str, float]:
    """Resolve every report's version and index the commits it needs (serially)."""
    repo = open_repo(repo_location)
    iset = IndexSet(repo, repo_location, cfg.paths_ignore)
    resolver = VersionResolver(repo, cfg.version_tags, cfg.project)
    needed: dict[str, None] = {}
    for rid in ids:
        doc = _load(rid)
        if doc is None:
            continue
        rep = report_from_hackerone(doc)
        claims = extract(rep.text, extract_context(cfg)).claims
        res = resolver.resolve(claims, rep.created_at)
        needed[res.commit] = None
        for sha, _ in res.alternates:
            needed[sha] = None
    for tag in history_sample(resolver.tags):
        tag_sha = repo.resolve_commit(tag)
        if tag_sha:
            needed.setdefault(tag_sha, None)
    timings: dict[str, float] = {}
    for i, sha in enumerate(needed):
        if iset.is_cached(sha):
            continue
        t = time.perf_counter()
        iset.get(sha)
        timings[sha] = time.perf_counter() - t
        log(f"indexed {sha[:12]} ({i + 1}/{len(needed)}) in {timings[sha]:.1f}s")
    iset.close()
    return timings


def _evaluate_one(args: tuple[int, str, dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    rid, repo_location, meta, th = args
    cfg = curl_config()
    cfg.thresholds = Thresholds(**th)
    doc = _load(rid)
    base = {k: meta[k] for k in ("id", "label", "era", "slop_list", "substate")}
    if doc is None:
        return {**base, "error": "not fetched"}
    edited = body_sha256(doc) != meta["body_sha256"]
    repo = open_repo(repo_location)
    iset = IndexSet(repo, repo_location, cfg.paths_ignore)
    try:
        result = run_reference_check(report_from_hackerone(doc), repo, iset, cfg)
    finally:
        iset.close()
    statuses: dict[str, int] = {}
    for f in result.findings:
        if f.claim.confidence != "high":
            continue
        key = f"{f.check}:{f.status}"
        statuses[key] = statuses.get(key, 0) + 1
    flags = {name: sum(statuses.get(s, 0) for s in keys) for name, keys in FLAG_STATUSES.items()}
    high_kinds: dict[str, int] = {}
    for c in result.extraction.claims:
        if c.confidence == "high":
            high_kinds[c.kind] = high_kinds.get(c.kind, 0) + 1
    agg = result.aggregate
    return {
        **base,
        "edited_since_freeze": edited,
        "ref": result.resolution.ref_label,
        "ref_assumed": result.resolution.assumed,
        "ref_reason": result.resolution.reason,
        "class": agg.cls,
        "hard": agg.hard,
        "soft": agg.soft,
        "verified": agg.verified,
        "checked": agg.checked,
        "claims_high": high_kinds,
        "statuses_high": statuses,
        "flags": flags,
        "seconds": round(result.timings["total"], 4),
        "index_cached": result.index_cached,
    }


def run_split(
    split: str,
    repo_location: str,
    *,
    jobs: int = 0,
    thresholds: Thresholds | None = None,
    log: Callable[[str], None] = lambda m: print(m, file=sys.stderr),
) -> list[dict[str, Any]]:
    cfg = curl_config()
    th = thresholds or cfg.thresholds
    meta = {r["id"]: r for r in load_reports()}
    ids = ids_for_split(split)
    prepare_indexes(ids, repo_location, cfg, log)
    work = [(rid, repo_location, meta[rid], vars(th)) for rid in ids]
    jobs = jobs or min(8, os.cpu_count() or 2)
    if jobs == 1:
        rows = [_evaluate_one(w) for w in work]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            rows = list(pool.map(_evaluate_one, work, chunksize=4))
    return rows


def reclassify(rows: list[dict[str, Any]], th: Thresholds) -> list[dict[str, Any]]:
    """Apply other thresholds to stored per-report counts (for the dev-split sweep)."""
    out = []
    for row in rows:
        if "error" in row:
            out.append(row)
            continue
        hard, verified, checked, soft = row["hard"], row["verified"], row["checked"], row["soft"]
        share = verified / checked if checked else None
        if checked == 0:
            cls = "refs_none"
        elif hard >= th.hard_fail_min or (
            hard >= 1 and share is not None and share < th.min_verified_share
        ):
            cls = "refs_failed"
        elif hard == 0 and soft == 0:
            cls = "refs_verified" if verified >= th.min_verified_claims else "refs_thin"
        else:
            cls = "refs_mixed"
        out.append({**row, "class": cls})
    return out


__all__ = ["run_split", "reclassify", "aggregate", "replace"]
