"""Workflow hygiene and injection: untrusted issue text must never reach a shell."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import make_repo
from sloptriage.cli import main

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = [
    ROOT / "action.yml",
    *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
    *sorted((ROOT / "examples" / "workflows").glob("*.yml")),
]
EVENTS = sorted((ROOT / "fixtures" / "events").glob("*.json"))


def _steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    if "runs" in doc:
        return list(doc["runs"].get("steps", []))
    out = []
    for job in (doc.get("jobs") or {}).values():
        out.extend(job.get("steps", []))
    return out


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_expressions_inside_run_blocks(path: Path) -> None:
    doc = yaml.safe_load(path.read_text())
    for step in _steps(doc):
        if "run" in step:
            assert "${{" not in step["run"], (
                f"{path.name}: expression inside run: {step.get('name')}"
            )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_third_party_actions_are_pinned(path: Path) -> None:
    doc = yaml.safe_load(path.read_text())
    for step in _steps(doc):
        uses = step.get("uses")
        if not uses or uses.startswith(("./", "$/")) or uses.startswith("B0yko/sloptriage@"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", uses), (
            f"{path.name}: {uses} is not pinned by SHA"
        )


def test_example_job_permissions() -> None:
    for path in (
        ROOT / "examples" / "workflows" / "triage-issues.yml",
        ROOT / ".github" / "workflows" / "triage-issues.yml",
    ):
        doc = yaml.safe_load(path.read_text())
        assert doc["permissions"] == {"contents": "read"}
        assert doc["jobs"]["check"]["permissions"] == {"contents": "read"}
        assert doc["jobs"]["report"]["permissions"] == {"issues": "write"}
        check_steps = doc["jobs"]["check"]["steps"]
        assert check_steps[0]["with"]["fetch-depth"] == 0
        report_uses = [s.get("uses", "") for s in doc["jobs"]["report"]["steps"]]
        assert not any(
            u.startswith("actions/checkout") for u in report_uses
        )  # the report job never checks out
        assert "secrets." not in json.dumps(doc["jobs"]["check"])


def _run_block(mode: str) -> str:
    doc = yaml.safe_load((ROOT / "action.yml").read_text())
    step = next(s for s in doc["runs"]["steps"] if s.get("if") == f"inputs.mode == '{mode}'")
    return str(step["run"]).replace(
        'uvx --from "$SLOPTRIAGE_SOURCE" sloptriage', f'"{sys.executable}" -m sloptriage.cli'
    )


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = make_repo(
        tmp_path_factory.mktemp("p") / "proj",
        [("v1.0.0", {"lib/a.c": "int real_fn(int x)\n{\n  return x;\n}\n"})],
    )
    (root / ".sloptriage.yml").write_text(
        "version: 1\nproject:\n  name: proj\nversion_tags: [v]\nlanguages: [c]\n"
    )
    return root


@pytest.mark.parametrize("event", EVENTS, ids=lambda p: p.stem)
def test_hostile_issues_through_the_action_shell(
    event: Path, project: Path, tmp_path: Path
) -> None:
    canary = tmp_path / "canary"
    payload = event.read_text().replace("{CANARY}", str(canary))
    event_path = tmp_path / "event.json"
    event_path.write_text(payload)
    env = {
        **os.environ,
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_WORKSPACE": str(project),
        "SLOPTRIAGE_VERDICT": str(tmp_path / "verdict.json"),
        "SLOPTRIAGE_CONFIG": "",
        "SLOPTRIAGE_SOURCE": str(ROOT),
        "PYTHONPATH": str(ROOT / "src"),
    }
    check = subprocess.run(
        ["bash", "-c", _run_block("check")],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert check.returncode == 0, check.stderr
    verdict = json.loads((tmp_path / "verdict.json").read_text())
    assert verdict["references"]["class"] == "refs_failed"
    assert (
        main(
            [
                "post",
                "--verdict",
                str(tmp_path / "verdict.json"),
                "--event",
                str(event_path),
                "--dry-run",
            ]
        )
        == 0
    )
    assert not canary.exists()
    assert not Path("/tmp/pwned").exists()  # noqa: S108 - the canary the fixtures try to create


def test_readme_action_snippet_matches_the_example_workflow() -> None:
    readme = (ROOT / "README.md").read_text()
    section = readme.split("## For maintainers", 1)[1]
    snippet = section.split("```yaml\n", 1)[1].split("```", 1)[0]
    example = yaml.safe_load((ROOT / "examples" / "workflows" / "triage-issues.yml").read_text())
    assert yaml.safe_load(snippet) == example
