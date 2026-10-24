"""Reproduction on the benchmark's real reports: which reports are tried, and what is stored."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import make_repo
from sloptriage.bench.repro import (
    ROW_KEYS,
    run_selected,
    select_subset,
    summarise_repro,
)
from sloptriage.config import Config, parse_config
from sloptriage.index.gitobj import GitRepo
from sloptriage.repro.runtime import Limits, RunResult

C_POC = (
    "PoC:\n\n```c\n#include <curl/curl.h>\nint main(void) { curl_global_init(0); return 0; }\n```\n"
)
SH_POC = "PoC:\n\n```sh\ncurl --version\n```\n"
PY_POC = "PoC:\n\n```python\nimport curl\nprint(1)\n```\n"
ASAN = (
    "==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1\n"
    "    #0 0x1 in Curl_parse /build/src/lib/a.c:2:3\n"
)


def meta(rid: int, label: str, *, slop: bool = False, era: str = "post2023") -> dict[str, Any]:
    return {"id": rid, "label": label, "slop_list": slop, "era": era, "substate": "x"}


@pytest.fixture
def project(tmp_path: Path) -> tuple[GitRepo, Config]:
    root = make_repo(
        tmp_path / "curl",
        [
            ("curl-8_1_0", {"lib/a.c": "int Curl_parse(void)\n{\n  return 0;\n}\n"}),
            ("curl-8_2_0", {"lib/a.c": "int Curl_parse(void)\n{\n  return 1;\n}\n"}),
        ],
    )
    cfg = parse_config(
        {
            "version": 1,
            "project": {"name": "curl", "binaries": ["curl"]},
            "version_tags": ["curl"],
            "languages": ["c"],
            "repro": {"build": {"preset": "autotools-asan"}},
        },
        "c.yml",
    )
    return GitRepo(root), cfg


def doc(rid: int, body: str) -> dict[str, Any]:
    return {
        "id": rid,
        "title": "t",
        "vulnerability_information": body,
        "submitted_at": "2024-06-01",
    }


def pick(project, items, split_ids, subset="both"):  # noqa: ANN001, ANN201
    repo, cfg = project
    docs = {m["id"]: doc(m["id"], body) for m, body in items}
    return select_subset(
        [m for m, _ in items],
        docs.get,
        repo,
        cfg,
        valid_ids=set(split_ids),
        subset=subset,
    )


def test_a_valid_report_with_a_c_or_shell_poc_and_a_known_version_is_selected(project) -> None:  # noqa: ANN001
    items = [
        (meta(1, "valid"), "curl 8.1.0 crashes.\n\n" + C_POC),
        (meta(2, "valid"), "curl 8.2.0 crashes.\n\n" + SH_POC),
    ]
    got = pick(project, items, [1, 2])
    assert [(s.meta["id"], s.group, s.resolution.ref_label) for s in got] == [
        (1, "valid", "curl-8_1_0"),
        (2, "valid", "curl-8_2_0"),
    ]


def test_valid_reports_without_a_poc_a_version_or_a_c_or_shell_poc_are_left_out(project) -> None:  # noqa: ANN001
    items = [
        (meta(1, "valid"), "curl 8.1.0 crashes in `Curl_parse()`."),
        (meta(2, "valid"), "It crashes.\n\n" + C_POC),
        (meta(3, "valid"), "curl 8.1.0.\n\n" + PY_POC),
        (meta(4, "valid"), "curl 9.9.9 never existed.\n\n" + C_POC),
    ]
    assert pick(project, items, [1, 2, 3, 4]) == []


def test_only_valid_reports_of_the_chosen_split_are_tried(project) -> None:  # noqa: ANN001
    items = [
        (meta(1, "valid"), "curl 8.1.0.\n\n" + C_POC),
        (meta(2, "valid"), "curl 8.1.0.\n\n" + C_POC),
        (meta(3, "invalid"), "curl 8.1.0.\n\n" + C_POC),
    ]
    got = pick(project, items, [1])
    assert [s.meta["id"] for s in got] == [1]


def test_listed_reports_with_a_poc_are_tried_whatever_the_split_or_version(project) -> None:  # noqa: ANN001
    items = [
        (meta(10, "invalid", slop=True), "No version given.\n\n" + SH_POC),
        (meta(11, "invalid", slop=True), "curl 8.2.0.\n\n" + C_POC),
        (meta(12, "invalid", slop=True), "curl 8.2.0, no PoC."),
        (meta(13, "invalid"), "curl 8.2.0.\n\n" + C_POC),
    ]
    got = pick(project, items, [])
    assert [(s.meta["id"], s.group) for s in got] == [(10, "slop"), (11, "slop")]


def test_the_subset_option_limits_the_groups(project) -> None:  # noqa: ANN001
    items = [
        (meta(1, "valid"), "curl 8.1.0.\n\n" + C_POC),
        (meta(10, "invalid", slop=True), "curl 8.1.0.\n\n" + C_POC),
    ]
    assert [s.group for s in pick(project, items, [1], "valid")] == ["valid"]
    assert [s.group for s in pick(project, items, [1], "slop")] == ["slop"]


class Scripted:
    def __init__(self, stderr: str, exit_code: int) -> None:
        self.stderr, self.exit_code = stderr, exit_code
        self.discarded: list[str] = []
        self.built: list[str] = []

    def ensure_image(self, commit: str, label: str) -> tuple[str | None, str | None]:
        self.built.append(commit)
        return "img", None

    def run(self, image: str, plan: object, limits: Limits) -> RunResult:
        marker = getattr(plan, "marker", "")
        return RunResult("", f"sloptriage-started:{marker}\n{self.stderr}", self.exit_code, 0.1)

    def discard(self, commit: str) -> None:
        self.discarded.append(commit)


def test_rows_hold_only_fixed_fields_and_images_are_dropped_per_version(project) -> None:  # noqa: ANN001
    repo, cfg = project
    items = [
        (meta(1, "valid"), "curl 8.1.0 crashes.\n\n`Curl_parse()` in lib/a.c\n\n" + C_POC),
        (meta(2, "valid"), "curl 8.1.0 crashes.\n\n" + SH_POC),
        (meta(3, "valid"), "curl 8.2.0 crashes.\n\n" + SH_POC),
    ]
    chosen = pick(project, items, [1, 2, 3])
    sb = Scripted(ASAN, 1)
    rows = run_selected(chosen, repo, cfg, sb, log=lambda _m: None)
    assert len(rows) == 3
    for row in rows:
        assert set(row) <= ROW_KEYS
        for key, value in row.items():
            assert isinstance(value, (int, bool, type(None))) or key in {
                "group",
                "split",
                "era",
                "ref",
                "verdict",
                "runner",
                "match",
                "error",
            }, key
    assert rows[0]["verdict"] == "reproduced"
    assert len(set(sb.built)) == 2 and len(sb.discarded) == 2  # one image per version, then removed


def test_a_failed_reproduction_is_recorded_not_raised(project) -> None:  # noqa: ANN001
    repo, cfg = project

    class Broken(Scripted):
        def ensure_image(self, commit: str, label: str) -> tuple[str | None, str | None]:
            return None, "make: *** error"

    chosen = pick(project, [(meta(1, "valid"), "curl 8.1.0.\n\n" + SH_POC)], [1])
    rows = run_selected(chosen, repo, cfg, Broken("", 0), log=lambda _m: None)
    assert rows[0]["verdict"] == "build_failed"
    assert "make" not in json.dumps(rows)  # no build log text is stored


def test_the_summary_counts_reproductions_and_lists_false_ones() -> None:
    rows = [
        {"id": 1, "group": "valid", "verdict": "reproduced"},
        {"id": 2, "group": "valid", "verdict": "not_reproduced"},
        {"id": 3, "group": "valid", "verdict": "build_failed"},
        {"id": 4, "group": "slop", "verdict": "not_reproduced"},
        {"id": 5, "group": "slop", "verdict": "reproduced"},
    ]
    s = summarise_repro(rows)
    assert s["valid"]["attempted"] == 3
    assert s["valid"]["reproduced"]["k"] == 1 and s["valid"]["reproduced"]["n"] == 3
    assert s["valid"]["by_verdict"] == {"reproduced": 1, "not_reproduced": 1, "build_failed": 1}
    assert s["slop"]["reproduced"]["k"] == 1
    assert s["slop"]["false_reproductions"] == [5]
    assert s["valid"]["buildable"]["n"] == 2  # build failures are not the report's fault


def test_the_command_is_available_with_its_options() -> None:
    from sloptriage.cli import build_parser

    args = build_parser().parse_args(
        ["bench", "repro", "--split", "all", "--subset", "slop", "--repo", "x", "--limit", "3"]
    )
    assert (args.bench_command, args.split, args.subset, args.limit) == ("repro", "all", "slop", 3)


def test_committed_results_hold_only_fixed_fields() -> None:
    from sloptriage.paths import bundled

    root = bundled("bench", "results")
    for path in sorted(root.glob("repro-*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["schema"] == "sloptriage-bench-repro/1"
        for row in doc["rows"]:
            assert set(row) <= ROW_KEYS, (path.name, set(row) - ROW_KEYS)
            assert isinstance(row["id"], int)
            assert row["verdict"] in {
                "reproduced",
                "crashed_elsewhere",
                "not_reproduced",
                "flaky",
                "timeout",
                "poc_build_failed",
                "poc_missing",
                "poc_unsupported",
                "build_failed",
                "infrastructure_error",
            }
