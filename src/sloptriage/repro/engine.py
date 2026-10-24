"""Run a report's PoCs and produce the ``reproduction`` object of the verdict."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from sloptriage.config import Config
from sloptriage.extract import Extraction
from sloptriage.index.gitobj import GitError, GitRepo
from sloptriage.models import Report
from sloptriage.repro.errors import ReproError
from sloptriage.repro.outcome import ClaimsView, Decision, RunOutcome, classify_run, decide
from sloptriage.repro.recipes import recipe_from_config
from sloptriage.repro.runners import (
    Candidate,
    RunPlan,
    attachment_files,
    candidates_from_report,
    script_for,
    split_roles,
)
from sloptriage.repro.runtime import RuntimeUnavailable, detect_runtime
from sloptriage.repro.sandbox import ContainerSandbox, Sandbox
from sloptriage.versions import Resolution, VersionResolver

MAX_EXCERPT_CHARS = 8000
MAX_EXCERPT_LINES = 60
_STARTS = ("ERROR: ", "WARNING: ", "runtime error:", "Traceback (most recent call last)")


def commit_is_buildable(
    repo: GitRepo, commit: str, release_tags: Iterable[str]
) -> tuple[bool, str]:
    """Only commits reachable from a release tag or the default branch are ever built.

    A build script from a fork or a pull request is code an unknown party wrote; it never runs.
    """
    try:
        if set(repo.tags_containing(commit)) & set(release_tags):
            return True, ""
        if repo.is_ancestor(commit, repo.default_branch()):
            return True, ""
    except GitError:
        pass
    return False, (
        f"Commit {commit[:12]} is not reachable from a release tag or the default branch of the "
        "repository, so it is not built. Builds from forks and pull requests are never run."
    )


def _excerpt(out: RunOutcome | None) -> str:
    if out is None:
        return ""
    text = out.output
    if out.kind == "crash":
        cut = min((i for i in (text.find(s) for s in _STARTS) if i >= 0), default=0)
        text = text[text.rfind("\n", 0, cut) + 1 :] if cut else text
    lines = text.strip().splitlines()[:MAX_EXCERPT_LINES]
    return "\n".join(lines)[:MAX_EXCERPT_CHARS]


def _cut(text: str | None, limit: int) -> str | None:
    return None if text is None else text[:limit]


def _run_json(out: RunOutcome) -> dict[str, Any]:
    # These strings come out of the PoC's own output, so each is cut to the schema's limit.
    return {
        "candidate": out.candidate,
        "outcome": out.kind,
        "error_type": _cut(out.error_type, 80),
        "top_frame": _cut(out.top_function, 200),
        "top_path": _cut(out.top_path, 300),
        "exit_code": out.exit_code,
        "signal": _cut(out.signal, 20),
        "seconds": round(out.seconds, 3),
    }


def _result(
    verdict: str,
    reason: str,
    *,
    runner: str | None = None,
    runs: list[RunOutcome] | None = None,
    excerpt: str = "",
    image: str | None = None,
    candidate: int | None = None,
    match: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"verdict": verdict, "reason": reason[:300]}
    if runner:
        out["runner"] = runner[:20]
    if candidate is not None:
        out["candidate"] = candidate
    if match:
        out["match"] = match
    out["runs"] = [_run_json(r) for r in (runs or [])][:30]
    if excerpt:
        out["output_excerpt"] = excerpt[:MAX_EXCERPT_CHARS]
    if image:
        out["image"] = image[:200]
    return out


def _representative(decision: Decision) -> RunOutcome | None:
    pick = {"compile_failed": "poc_build_failed"}
    for out in decision.outcomes:
        if out.kind == "crash" or out.kind == "oom":
            return out
        if pick.get(out.kind) == decision.verdict:
            return out
    return decision.outcomes[0] if decision.outcomes else None


def run_reproduction(
    report: Report,
    extraction: Extraction,
    resolution: Resolution,
    repo: GitRepo,
    cfg: Config,
    sandbox: Sandbox | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run up to ``limits.candidates`` PoCs from the report, ``limits.runs`` times each."""
    conf = cfg.repro
    names = [cfg.project, *cfg.aliases]
    cands = candidates_from_report(report, extraction, conf, names)
    if not cands:
        return _result("poc_missing", "No PoC was found in the report text or attachments.")
    runnable = [c for c in cands if not c.unsupported]
    skipped = [c for c in cands if c.unsupported]
    if not runnable:
        return _result("poc_unsupported", skipped[0].unsupported or "No PoC could be run.")
    release = VersionResolver(repo, cfg.version_tags, cfg.project).tags
    ok, why = commit_is_buildable(repo, resolution.commit, release)
    if not ok:
        return _result("poc_unsupported", why)
    recipe = recipe_from_config(conf, cfg.project)
    if sandbox is None:
        try:
            runtime = detect_runtime(conf.runtime)
        except RuntimeUnavailable as exc:
            raise ReproError(str(exc)) from exc
        sandbox = ContainerSandbox(runtime, repo, recipe, cfg.project, conf.limits, progress)
    image, error = sandbox.ensure_image(resolution.commit, resolution.ref_label)
    if image is None:
        return _result(
            "build_failed",
            "The project could not be built in the sandbox. This is a limit of the build recipe, "
            "not of the report: " + (error or "")[-180:].replace("\n", " "),
            excerpt=(error or "")[-MAX_EXCERPT_CHARS:],
        )
    files = {e.path for e in repo.ls_tree(resolution.commit)}
    view = ClaimsView.of(extraction.claims)
    extras = attachment_files(report)
    mains, companion, extra_servers = split_roles(runnable)
    skipped = [*skipped, *extra_servers]
    ran: list[tuple[Candidate, list[RunOutcome]]] = []
    plan_of: dict[int, RunPlan] = {}
    for cand in mains:
        plan = script_for(cand, companion, recipe, conf, cfg.project)
        plan.files = {**extras, **plan.files}
        plan_of[cand.index] = plan
        outcomes: list[RunOutcome] = []
        for _ in range(conf.limits.runs):
            result = sandbox.run(image, plan, conf.limits)
            outcome = classify_run(result, plan, files, cand.index)
            outcomes.append(outcome)
            if outcome.kind in ("compile_failed", "timeout", "flood"):
                break
        ran.append((cand, outcomes))
    decision = decide(ran, skipped, view)
    runs = [o for _, outs in ran for o in outs]
    chosen = decision.candidate
    chosen_plan = plan_of.get(chosen.index) if chosen else None
    return _result(
        decision.verdict,
        decision.reason,
        runner=chosen_plan.label if chosen_plan else (chosen.kind if chosen else None),
        runs=runs,
        excerpt=_excerpt(_representative(decision)),
        image=image,
        candidate=chosen.index if chosen else None,
        match=decision.match,
    )
