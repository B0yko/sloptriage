from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_repo
from sloptriage.cli import main


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    return make_repo(
        tmp_path / "proj", [("v1.0.0", {"lib/a.c": "int real_fn(int x)\n{\n  return x;\n}\n"})]
    )


def _report(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "r.md"
    p.write_text(text)
    return p


def test_check_json_and_fail_on(
    tmp_path: Path, project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = _report(tmp_path, "proj 1.0.0: crash in `missing_one()` and `missing_two()` at lib/a.c:2")
    assert main(["check", str(rep), "--repo", str(project), "--format", "json"]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["references"]["class"] == "refs_failed"
    assert main(["check", str(rep), "--repo", str(project), "--fail-on", "refs_failed"]) == 1


def test_markdown_and_text_formats(
    tmp_path: Path, project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = _report(tmp_path, "proj 1.0.0: `real_fn()` in lib/a.c:2")
    assert main(["check", str(rep), "--repo", str(project), "--format", "md"]) == 0
    assert capsys.readouterr().out.startswith("<!-- sloptriage -->")
    assert main(["preflight", str(rep), "--repo", str(project)]) == 0
    assert "Before you send" in capsys.readouterr().out


def test_usage_and_config_errors_exit_2(tmp_path: Path, project: Path) -> None:
    rep = _report(tmp_path, "x")
    bad = tmp_path / "bad.yml"
    bad.write_text("version: 1\nprojcet: {}\n")
    assert main(["check", str(rep), "--repo", str(project), "--config", str(bad)]) == 2
    assert main(["check", str(tmp_path / "missing.md"), "--repo", str(project)]) == 2
    assert main(["check", str(rep), "--repo", str(project), "--ref", "no-such-ref"]) == 2
    assert main(["no-such-command"]) == 2


def test_infrastructure_errors_exit_3(tmp_path: Path) -> None:
    rep = _report(tmp_path, "x")
    assert main(["check", str(rep), "--repo", str(tmp_path / "not-a-repo")]) == 3


def test_post_dry_run_validates_and_prints(
    tmp_path: Path, project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = _report(tmp_path, "proj 1.0.0: crash in `missing_one()` and `missing_two()`")
    out = tmp_path / "verdict.json"
    assert (
        main(["check", str(rep), "--repo", str(project), "--format", "json", "-o", str(out)]) == 0
    )
    assert main(["post", "--verdict", str(out), "--issue", "example/proj#3", "--dry-run"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert (
        lines[0]["method"] == "POST" and lines[0]["path"] == "/repos/example/proj/issues/3/comments"
    )
    assert lines[1]["body"] == {"labels": ["triage:refs-failed", "triage:needs-poc"]}
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"schema": "sloptriage-verdict/1"}))
    assert main(["post", "--verdict", str(broken), "--issue", "example/proj#3", "--dry-run"]) == 2


def test_init_writes_config(tmp_path: Path, project: Path) -> None:
    assert main(["init", str(project)]) == 0
    text = (project / ".sloptriage.yml").read_text()
    assert "languages: [c]" in text and 'version_tags: ["v{version}"]' in text
    assert main(["init", str(project)]) == 2
