"""The synthetic set: reference classes must match the labels by construction."""

from __future__ import annotations

import pytest

from sloptriage import demo
from sloptriage.config import load_config
from sloptriage.index import IndexSet
from sloptriage.index.gitobj import GitRepo
from sloptriage.ingest import load_report
from sloptriage.verdict import run_reference_check

# failure modes the reference check alone must catch
REFERENCE_MODES = {
    "nonexistent_function",
    "nonexistent_file",
    "line_out_of_range",
    "frame_mismatch",
    "fabricated_trace",
    "fabricated_quote",
    "other_library",
    "padded",
}


@pytest.fixture(scope="module")
def results() -> list[tuple[demo.DemoReport, str]]:
    repos = {}
    for project in demo.PROJECTS:
        path = demo.materialize(project)
        repo = GitRepo(path)
        repos[project] = (repo, IndexSet(repo, str(path)), load_config(demo.config_path(project)))
    out = []
    for rep in demo.reports():
        repo, iset, cfg = repos[rep.project]
        out.append(
            (rep, run_reference_check(load_report(str(rep.path)), repo, iset, cfg).aggregate.cls)
        )
    return out


def test_sixty_reports_twenty_valid() -> None:
    reps = demo.reports()
    assert len(reps) == 60
    assert sum(r.label == "valid" for r in reps) == 20


def test_valid_reports_are_never_failed(results: list[tuple[demo.DemoReport, str]]) -> None:
    for rep, cls in results:
        if rep.label == "valid":
            assert cls in ("refs_verified", "refs_thin", "refs_none"), (rep.file, cls)


def test_reference_failure_modes_are_caught(results: list[tuple[demo.DemoReport, str]]) -> None:
    for rep, cls in results:
        if set(rep.failure_modes) & REFERENCE_MODES:
            assert cls == "refs_failed", (rep.file, cls)


def test_materialized_history_is_deterministic() -> None:
    path = demo.materialize("parsekit")
    repo = GitRepo(path)
    assert [t for t in repo.tags() if t.startswith("v")] == ["v1.0.0", "v1.1.0", "v1.2.0"]
    again = GitRepo(demo.materialize("parsekit"))
    assert again.resolve_commit("v1.2.0") == repo.resolve_commit("v1.2.0")
