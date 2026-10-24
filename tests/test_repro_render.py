"""The reproduction part of the card, the labels, the comment policy and the CLI flags."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from conftest_docker import FakeContainerCli, make_fake_cli
from sloptriage import demo
from sloptriage.cli import main
from sloptriage.config import parse_config
from sloptriage.demo_run import check_all
from sloptriage.render import (
    labels_for,
    render_markdown,
    render_preflight,
    render_text,
    should_comment,
    validate_verdict,
)

FORBIDDEN = re.compile(r"\b(slop|ai|llm|fake|hallucinated|spam|invalid)\b", re.I)
VERDICTS = [
    "reproduced",
    "crashed_elsewhere",
    "not_reproduced",
    "flaky",
    "timeout",
    "poc_build_failed",
    "poc_missing",
    "poc_unsupported",
    "build_failed",
]
ASAN = (
    "==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1\n"
    "    #0 0x1 in pk_header_join /build/src/src/header.c:175:12\n"
)


def run_entry(outcome: str = "crash", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "candidate": 0,
        "outcome": outcome,
        "error_type": "heap-buffer-overflow" if outcome == "crash" else None,
        "top_frame": "pk_header_join" if outcome == "crash" else None,
        "top_path": "src/header.c" if outcome == "crash" else None,
        "exit_code": 1 if outcome == "crash" else 0,
        "signal": None,
        "seconds": 0.5,
    }
    return base | kw


def repro_obj(verdict: str, **kw: Any) -> dict[str, Any]:
    crash = verdict in ("reproduced", "crashed_elsewhere")
    runs = [run_entry("crash" if crash else "clean") for _ in range(3)]
    if verdict == "flaky":
        runs = [run_entry("crash"), run_entry("clean"), run_entry("crash")]
    if verdict == "timeout":
        runs = [run_entry("timeout", exit_code=None)]
    if verdict == "poc_build_failed":
        runs = [run_entry("compile_failed", exit_code=253)]
    if verdict in ("poc_missing", "poc_unsupported", "build_failed"):
        runs = []
    obj: dict[str, Any] = {
        "verdict": verdict,
        "reason": "The claimed crash occurred in 3 of 3 runs.",
        "runner": "c",
        "runs": runs,
        "output_excerpt": ASAN if crash else "ok\n",
        "image": "sloptriage/parsekit:abc-def",
    }
    return obj | kw


@pytest.fixture(scope="module")
def base_verdict() -> dict[str, Any]:
    rows = check_all()
    return next(v for r, v in rows if r.file.startswith("03-"))


def with_repro(base: dict[str, Any], obj: dict[str, Any] | None) -> dict[str, Any]:
    v = copy.deepcopy(base)
    v["reproduction"] = obj
    return v


# -- the card -------------------------------------------------------------------------------------
@pytest.mark.parametrize("verdict", VERDICTS)
def test_every_verdict_renders_a_neutral_valid_section(
    base_verdict: dict[str, Any], verdict: str
) -> None:
    v = with_repro(base_verdict, repro_obj(verdict))
    validate_verdict(v)
    md = render_markdown(v)
    assert "**Reproduction**" in md
    text = md.replace("sloptriage", " ")
    text = re.sub(r"https?://\S+", " ", text)
    assert not FORBIDDEN.search(text), FORBIDDEN.search(text)
    assert len(md) < 60_000
    plain = render_text(v)
    assert "Reproduction:" in plain
    assert "Reproduction" in render_preflight(v) or verdict in ("poc_missing",)


def test_no_section_when_nothing_was_run(base_verdict: dict[str, Any]) -> None:
    md = render_markdown(with_repro(base_verdict, None))
    assert "**Reproduction**" not in md


def test_reproduced_sentence_names_where_and_how_often(base_verdict: dict[str, Any]) -> None:
    md = render_markdown(with_repro(base_verdict, repro_obj("reproduced")))
    line = next(ln for ln in md.splitlines() if ln.startswith("**Reproduction**"))
    assert "`heap-buffer-overflow`" in line
    assert "`pk_header_join()`" in line and "`src/header.c`" in line
    assert "3 of 3 runs" in line


def test_not_reproduced_says_what_it_does_not_show(base_verdict: dict[str, Any]) -> None:
    md = render_markdown(with_repro(base_verdict, repro_obj("not_reproduced")))
    assert "does not show" in md


def test_build_failure_is_worded_as_not_the_reporters_fault(base_verdict: dict[str, Any]) -> None:
    obj = repro_obj("build_failed", reason="cmake: command not found")
    md = render_markdown(with_repro(base_verdict, obj))
    assert "not from the report" in md or "not of the report" in md


def test_hostile_output_cannot_inject_markup_mentions_or_links(
    base_verdict: dict[str, Any],
) -> None:
    hostile = (
        "@everyone please look\n```\n<script>alert(1)</script>\n![x](http://evil.example/p.png)\n"
        "[click](http://evil.example)\n‮evil\n" + "\n".join(f"line {i}" for i in range(500))
    )
    obj = repro_obj(
        "reproduced",
        output_excerpt=hostile,
        runs=[
            run_entry(
                top_frame="@octocat`<img src=x onerror=1>", top_path="[a](http://evil.example)"
            )
        ]
        * 3,
    )
    md = render_markdown(with_repro(base_verdict, obj))
    assert "<script" not in md and "<img" not in md
    assert "![" not in md.split("**Reproduction**", 1)[1]
    assert "http://evil.example" not in md
    assert "‮" not in md
    assert not re.search(r"(?<!​)@(?:everyone|octocat)", md)
    excerpt_block = md.split("**Reproduction**", 1)[1]
    assert excerpt_block.count("\nline ") <= 30  # at most 30 lines of output
    fence = re.search(r"^(`{3,})text$", excerpt_block, re.M)
    assert fence is not None and len(fence.group(1)) >= 4  # longer than any run in the output


def test_the_sentence_describes_the_candidate_that_decided_the_verdict(
    base_verdict: dict[str, Any],
) -> None:
    segv = run_entry("crash", candidate=0, error_type="SEGV", top_frame="other_fn")
    good = run_entry("crash", candidate=1)
    obj = repro_obj("reproduced", runs=[segv, segv, segv, good, good, good], candidate=1)
    line = next(
        ln
        for ln in render_markdown(with_repro(base_verdict, obj)).splitlines()
        if ln.startswith("**Reproduction**")
    )
    assert "SEGV" not in line and "`heap-buffer-overflow`" in line and "3 of 3 runs" in line


def test_a_function_match_with_another_error_type_is_not_called_a_match(
    base_verdict: dict[str, Any],
) -> None:
    obj = repro_obj("reproduced", match="function_type_differs", reason="differs")
    line = next(
        ln
        for ln in render_markdown(with_repro(base_verdict, obj)).splitlines()
        if ln.startswith("**Reproduction**")
    )
    assert "matches what the report describes" not in line
    assert "different error type" in line


# -- labels and comments --------------------------------------------------------------------------------
def test_labels_follow_the_reproduction_verdict(base_verdict: dict[str, Any]) -> None:
    cfg = parse_config({"version": 1, "project": {"name": "parsekit"}}, "c.yml")
    names = {v: labels_for(with_repro(base_verdict, repro_obj(v)), cfg) for v in VERDICTS}
    assert "triage:reproduced" in names["reproduced"]
    assert "triage:not-reproduced" in names["not_reproduced"]
    for other in ("crashed_elsewhere", "flaky", "timeout", "poc_build_failed", "poc_missing"):
        assert not any(label.endswith("reproduced") for label in names[other]), other
    assert not any("reproduced" in label for label in labels_for(base_verdict, cfg))


def test_label_names_are_configurable_and_listed_as_managed() -> None:
    cfg = parse_config(
        {"version": 1, "labels": {"reproduced": "sloptriage/repro", "not_reproduced": "n/r"}},
        "c.yml",
    )
    assert cfg.labels["reproduced"] == "sloptriage/repro"
    assert cfg.labels["not_reproduced"] == "n/r"


def test_comment_policy_can_include_reproduction_results(base_verdict: dict[str, Any]) -> None:
    quiet = parse_config({"version": 1, "comment": {"when": ["refs_failed"]}}, "c.yml")
    loud = parse_config({"version": 1, "comment": {"when": ["reproduced"]}}, "c.yml")
    verified = copy.deepcopy(base_verdict)
    verified["references"]["class"] = "refs_verified"
    verified["needs"] = []
    v = with_repro(verified, repro_obj("reproduced"))
    assert should_comment(v, quiet) is False
    assert should_comment(v, loud) is True
    assert should_comment(with_repro(verified, repro_obj("flaky")), loud) is False


# -- the command line ----------------------------------------------------------------------------------------
@pytest.fixture
def parsekit_repo() -> Path:
    return demo.materialize("parsekit")


def run_cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_repro_flag_without_a_runtime_exits_3_and_runs_nothing(
    parsekit_repo: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sloptriage.repro.runtime.shutil.which", lambda _name: None)
    report = demo.reports()[2].path
    code, out, err = run_cli(
        capsys,
        "check",
        str(report),
        "--repo",
        str(parsekit_repo),
        "--config",
        str(demo.config_path("parsekit")),
        "--repro",
    )
    assert code == 3
    assert "Docker or Podman" in err
    assert out == ""


def test_without_the_flag_the_reproduction_field_is_null(
    parsekit_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = demo.reports()[2].path
    code, out, _ = run_cli(
        capsys,
        "check",
        str(report),
        "--repo",
        str(parsekit_repo),
        "--config",
        str(demo.config_path("parsekit")),
        "--format",
        "json",
    )
    assert code == 0
    assert json.loads(out)["reproduction"] is None


def test_repro_flag_runs_the_poc_and_labels_the_verdict(
    parsekit_repo: Path,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake: FakeContainerCli = make_fake_cli(tmp_path / "fake")
    fake.set(stderr=ASAN, exit_code=1)
    monkeypatch.setenv("PATH", f"{fake.exe.parent}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
    report = demo.reports()[2].path  # 03: a C PoC against 1.2.0
    code, out, _ = run_cli(
        capsys,
        "check",
        str(report),
        "--repo",
        str(parsekit_repo),
        "--config",
        str(demo.config_path("parsekit")),
        "--repro",
        "--format",
        "json",
    )
    assert code == 0
    verdict = json.loads(out)
    assert verdict["reproduction"]["verdict"] == "reproduced"
    assert "triage:reproduced" in verdict["labels"]
    validate_verdict(verdict)
    run_args = json.loads((fake.state / "run_args.json").read_text())
    assert "--network" in run_args and run_args[run_args.index("--network") + 1] == "none"


def test_no_repro_overrides_the_config(
    parsekit_repo: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cfg = tmp_path / "c.yml"
    cfg.write_text(
        demo.config_path("parsekit").read_text().replace("repro:\n", "repro:\n  enabled: true\n")
    )
    report = demo.reports()[2].path
    code, out, _ = run_cli(
        capsys,
        "check",
        str(report),
        "--repo",
        str(parsekit_repo),
        "--config",
        str(cfg),
        "--no-repro",
        "--format",
        "json",
    )
    assert code == 0 and json.loads(out)["reproduction"] is None


def test_demo_says_when_reproduction_is_not_available(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sloptriage.repro.runtime.shutil.which", lambda _name: None)
    code, out, _ = run_cli(capsys, "demo")
    assert code == 0
    assert "Reproduction needs Docker or Podman" in out
    code, out, err = run_cli(capsys, "demo", "--repro")
    assert code == 3
    assert "Docker or Podman" in err
