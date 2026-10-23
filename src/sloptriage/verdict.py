"""Run the checks for one report and aggregate them into a verdict."""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sloptriage import __version__
from sloptriage.config import Config, Thresholds
from sloptriage.extract import Claim, ExtractContext, Extraction, extract
from sloptriage.index import IndexSet
from sloptriage.index.gitobj import GitRepo
from sloptriage.models import Report
from sloptriage.names import load_names
from sloptriage.refs import Finding, check_claims, make_context
from sloptriage.versions import Resolution, VersionResolver

CLASSES = ("refs_verified", "refs_thin", "refs_mixed", "refs_failed", "refs_none")
CHECKABLE = ("path", "symbol", "line", "frame", "quote")
_SEVERITY_RANK = {"hard": 3, "soft": 2, "ok": 1, "neutral": 0}


@dataclass
class ClaimOutcome:
    claim: Claim
    findings: list[Finding]

    @property
    def severity(self) -> str:
        if not self.findings:
            return "neutral"
        return max((f.severity for f in self.findings), key=lambda s: _SEVERITY_RANK[s])


@dataclass
class Aggregate:
    cls: str
    hard: int
    soft: int
    verified: int
    checked: int
    share: float | None
    outcomes: list[ClaimOutcome] = field(default_factory=list)


def outcomes_by_claim(claims: list[Claim], findings: list[Finding]) -> list[ClaimOutcome]:
    by_id: dict[int, list[Finding]] = {}
    for f in findings:
        if f.check == "frame_chain":
            continue
        by_id.setdefault(id(f.claim), []).append(f)
    return [ClaimOutcome(c, by_id.get(id(c), [])) for c in claims]


def aggregate(claims: list[Claim], findings: list[Finding], th: Thresholds) -> Aggregate:
    """The fixed decision rule; only the two thresholds are tunable.

    refs_failed iff hard >= hard_fail_min, or hard >= 1 and verified share < min_verified_share.
    Only high-confidence claims count; soft and neutral findings never decide.
    """
    outcomes = outcomes_by_claim(claims, findings)
    high = [o for o in outcomes if o.claim.confidence == "high" and o.claim.kind in CHECKABLE]
    hard = sum(1 for o in high if o.severity == "hard")
    soft = sum(1 for o in high if o.severity == "soft")
    verified = sum(1 for o in high if o.severity == "ok")
    checked = hard + soft + verified
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
    return Aggregate(cls, hard, soft, verified, checked, share, outcomes)


def extract_context(cfg: Config, defines: Any = None) -> ExtractContext:
    names = load_names().with_external(tuple(cfg.symbols_external))
    return ExtractContext(
        project=cfg.project,
        aliases=tuple(cfg.aliases),
        languages=tuple(cfg.languages),
        binaries=tuple(cfg.binaries),
        repo_slug=repo_slug(cfg.repository or ""),
        defines=defines,
        external=tuple(cfg.symbols_external),
        names=names,
    )


def repo_slug(url: str) -> str:
    m = re.match(
        r"^(?:https://github\.com/|git@github\.com:)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url.strip()
    )
    return f"{m.group(1)}/{m.group(2)}".lower() if m else ""


@dataclass
class CheckResult:
    report: Report
    extraction: Extraction
    resolution: Resolution
    findings: list[Finding]
    aggregate: Aggregate
    timings: dict[str, float]
    index_cached: bool


def run_reference_check(
    report: Report,
    repo: GitRepo,
    iset: IndexSet,
    cfg: Config,
    *,
    ref: str | None = None,
) -> CheckResult:
    t0 = time.perf_counter()
    text = report.text
    first = extract(text, extract_context(cfg))
    resolver = VersionResolver(repo, cfg.version_tags, cfg.project)
    resolution = resolver.resolve(first.claims, report.created_at, explicit_ref=ref)
    t1 = time.perf_counter()
    cached = iset.is_cached(resolution.commit)
    ctx_refs = make_context(
        iset,
        resolution.commit,
        resolution.ref_label,
        resolution.alternates,
        extract_context(cfg).names,
        repo_slug(cfg.repository or repo.remote_url() or ""),
    )
    t2 = time.perf_counter()
    primary = ctx_refs.primary

    def defines(name: str) -> bool:
        return bool(primary.definitions(name))

    extraction = extract(text, extract_context(cfg, defines))
    ctx_refs.poc_names = extraction.poc_names
    findings = check_claims(ctx_refs, extraction.claims, cfg.project_cves())
    agg = aggregate(extraction.claims, findings, cfg.thresholds)
    t3 = time.perf_counter()
    return CheckResult(
        report,
        extraction,
        resolution,
        findings,
        agg,
        {"resolve": t1 - t0, "index": t2 - t1, "check": t3 - t2, "total": t3 - t0},
        cached,
    )


def needs(result: CheckResult) -> list[str]:
    out = []
    res = result.resolution
    if res.assumed and res.reason in ("no_version", "version_not_found"):
        out.append("needs_version")
    if not result.extraction.by_kind("poc") and not result.report.attachments:
        out.append("needs_poc")
    return out


def counts(result: CheckResult) -> dict[str, Any]:
    by_kind = Counter(c.kind for c in result.extraction.claims if c.confidence == "high")
    status = Counter(f"{f.check}:{f.status}" for f in result.findings)
    return {"claims_high": dict(by_kind), "statuses": dict(status)}


def tool_version() -> str:
    return __version__
