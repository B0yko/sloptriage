"""The container runtime wrapper: detection, the hardened command line, limits and clean-up.

These tests use a scriptable stand-in for the container CLI, so they run everywhere. The same
properties are checked against a real container in ``test_repro_docker.py``.
"""

from __future__ import annotations

import io
import json
import tarfile
import time
from pathlib import Path

import pytest

from conftest_docker import FakeContainerCli, make_fake_cli
from sloptriage.repro.runtime import (
    Limits,
    Runtime,
    RuntimeUnavailable,
    build_image_argv,
    build_run_argv,
    detect_runtime,
    run_sandboxed,
)


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeContainerCli:
    fake = make_fake_cli(tmp_path / "fake")
    monkeypatch.setenv("PATH", str(fake.exe.parent))
    return fake


def runtime_for(cli: FakeContainerCli) -> Runtime:
    return Runtime(name="docker", exe=str(cli.exe))


def flag_values(argv: list[str], flag: str) -> list[str]:
    out = []
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            out.append(argv[i + 1])
        elif arg.startswith(flag + "="):
            out.append(arg.split("=", 1)[1])
    return out


def one(argv: list[str], flag: str) -> str:
    values = flag_values(argv, flag)
    assert len(values) == 1, f"{flag} should appear exactly once, got {values}"
    return values[0]


ENV = {"ASAN_OPTIONS": "detect_leaks=0", "HOME": "/work", "TMPDIR": "/work/tmp"}


def argv_for(limits: Limits | None = None) -> list[str]:
    return build_run_argv(
        Runtime(name="docker", exe="/usr/bin/docker"),
        image="sloptriage/proj:abc",
        name="sloptriage-test",
        limits=limits or Limits(),
        script="echo hi",
        env=ENV,
    )


# -- the hardened command line ------------------------------------------------------------
def test_no_network_and_read_only_root() -> None:
    argv = argv_for()
    assert one(argv, "--network") == "none"
    assert "--read-only" in argv


def test_writable_space_is_two_size_limited_tmpfs_at_work_and_tmp() -> None:
    argv = argv_for(Limits(tmpfs="48m"))
    mounts = {}
    for spec in flag_values(argv, "--tmpfs"):
        path, _, options = spec.partition(":")
        mounts[path] = options.split(",")
    assert set(mounts) == {"/work", "/tmp"}
    for path, opts in mounts.items():
        assert "size=48m" in opts, path
        assert {"nosuid", "nodev", "exec"} <= set(opts), path


def test_runs_as_a_non_root_user() -> None:
    uid, _, gid = one(argv_for(), "--user").partition(":")
    assert uid.isdigit() and int(uid) >= 1000
    assert gid.isdigit() and int(gid) >= 1000


def test_drops_every_capability_and_blocks_privilege_gain() -> None:
    argv = argv_for()
    assert one(argv, "--cap-drop") == "ALL"
    assert flag_values(argv, "--cap-add") == []
    assert any(v.startswith("no-new-privileges") for v in flag_values(argv, "--security-opt"))
    assert not any(v.startswith("seccomp=unconfined") for v in flag_values(argv, "--security-opt"))


def test_process_memory_and_cpu_limits_are_set_and_swap_is_off() -> None:
    argv = argv_for(Limits(pids=77, memory="300m", cpus=1.5))
    assert one(argv, "--pids-limit") == "77"
    assert one(argv, "--memory") == "300m"
    assert one(argv, "--memory-swap") == "300m"
    assert one(argv, "--cpus") == "1.5"


def test_no_host_mounts_devices_sockets_or_shared_namespaces() -> None:
    argv = argv_for()
    forbidden = {
        "-v",
        "--volume",
        "--mount",
        "--privileged",
        "--device",
        "--env-file",
        "--pid=host",
        "--network=host",
        "--ipc=host",
        "--userns=host",
        "--uts=host",
        "--volumes-from",
    }
    assert not forbidden & set(argv)
    assert not any(a.startswith(("--volume=", "--mount=", "--device=")) for a in argv)
    assert not any("docker.sock" in a or "podman.sock" in a for a in argv)
    assert "--pid" not in argv


def test_only_explicit_key_value_environment_variables_are_passed() -> None:
    argv = argv_for()
    values = flag_values(argv, "-e") + flag_values(argv, "--env")
    assert sorted(values) == sorted(f"{k}={v}" for k, v in ENV.items())
    assert all("=" in v for v in values)


def test_container_is_named_labelled_and_reaped_by_an_init_process() -> None:
    argv = argv_for()
    assert one(argv, "--name") == "sloptriage-test"
    assert "sloptriage=1" in flag_values(argv, "--label")
    assert "--init" in argv
    assert "-i" in argv  # artefacts arrive on stdin, never through a mount


def test_images_are_never_pulled_at_run_time() -> None:
    assert one(argv_for(), "--pull") == "never"


def test_image_and_script_come_last_in_a_fixed_shape() -> None:
    argv = argv_for()
    assert argv[-4:] == ["sloptriage/proj:abc", "sh", "-c", "echo hi"]


def test_core_dumps_and_open_files_are_limited() -> None:
    argv = argv_for()
    ulimits = flag_values(argv, "--ulimit")
    assert "core=0:0" in ulimits
    assert any(u.startswith("nofile=") for u in ulimits)


def test_image_stage_has_network_and_project_stage_has_none() -> None:
    rt = Runtime(name="docker", exe="/usr/bin/docker")
    base = build_image_argv(rt, "sloptriage/base:1", "Dockerfile.sloptriage", network=True)
    assert "--network" not in base
    project = build_image_argv(rt, "sloptriage/proj:1", "Dockerfile.sloptriage", network=False)
    assert one(project, "--network") == "none"
    assert one(project, "--pull") == "false"
    assert project[-1] == "-"  # the context is streamed on stdin
    assert "sloptriage=1" in flag_values(
        project, "--label"
    )  # so that images can be listed and pruned


# -- detection ----------------------------------------------------------------------------
def test_detect_prefers_docker_then_podman(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_fake_cli(tmp_path / "a", "podman")
    docker = make_fake_cli(tmp_path / "b", "docker")
    monkeypatch.setenv("PATH", f"{docker.exe.parent}:{tmp_path / 'a' / 'bin'}")
    assert detect_runtime().name == "docker"
    assert detect_runtime("podman").name == "podman"


def test_detect_refuses_when_no_runtime_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeUnavailable, match="Docker or Podman"):
        detect_runtime()


def test_detect_refuses_when_the_daemon_does_not_answer(cli: FakeContainerCli) -> None:
    cli.set(daemon_down=True)
    with pytest.raises(RuntimeUnavailable, match="daemon"):
        detect_runtime()


# -- running ------------------------------------------------------------------------------
def tar_of(**files: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_artefacts_are_streamed_on_stdin_and_output_is_captured(cli: FakeContainerCli) -> None:
    cli.set(stdout="out text\n", stderr="err text\n", exit_code=3)
    payload = tar_of(**{"poc.c": b"int main(void){return 0;}"})
    result = run_sandboxed(
        runtime_for(cli), "img:1", "echo hi", payload, Limits(), ENV, name="sloptriage-t1"
    )
    assert cli.stdin() == payload
    assert (result.exit_code, result.timed_out, result.oom) == (3, False, False)
    assert "out text" in result.stdout and "err text" in result.stderr
    run_args = json.loads((cli.state / "run_args.json").read_text())
    assert one(run_args, "--network") == "none"


def test_the_container_is_always_inspected_and_removed(cli: FakeContainerCli) -> None:
    cli.set(exit_code=0)
    run_sandboxed(runtime_for(cli), "img:1", "true", b"", Limits(), ENV, name="sloptriage-t2")
    calls = cli.calls()
    assert ["rm", "-f", "-v", "sloptriage-t2"] in calls
    assert any(c[0] == "inspect" and "sloptriage-t2" in c for c in calls)


def test_wall_clock_timeout_kills_the_container(cli: FakeContainerCli) -> None:
    cli.set(hang=True)
    started = time.monotonic()
    result = run_sandboxed(
        runtime_for(cli), "img:1", "sleep 99", b"", Limits(timeout=1), ENV, name="sloptriage-t3"
    )
    assert time.monotonic() - started < 15
    assert result.timed_out is True
    assert ["kill", "sloptriage-t3"] in cli.calls()
    assert ["rm", "-f", "-v", "sloptriage-t3"] in cli.calls()


def test_the_start_and_the_end_of_long_output_are_both_kept(cli: FakeContainerCli) -> None:
    cli.set(stdout="HEAD-LINE\n" + "m" * 50_000 + "\nTAIL-LINE\n")
    result = run_sandboxed(
        runtime_for(cli), "img:1", "x", b"", Limits(output_bytes=2_000), ENV, name="sloptriage-th"
    )
    assert "HEAD-LINE" in result.stdout and "TAIL-LINE" in result.stdout
    assert "truncated" in result.stdout and result.truncated is True


def test_a_terminate_signal_removes_the_container_before_the_tool_exits(
    cli: FakeContainerCli,
) -> None:
    import os
    import signal
    import threading

    cli.set(hang=True)
    threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()
    with pytest.raises(SystemExit):
        run_sandboxed(
            runtime_for(cli),
            "img:1",
            "sleep 99",
            b"",
            Limits(timeout=30),
            ENV,
            name="sloptriage-tt",
        )
    assert ["rm", "-f", "-v", "sloptriage-tt"] in cli.calls()


def test_output_is_truncated_at_the_cap(cli: FakeContainerCli) -> None:
    cli.set(stdout="B" * 50_000)
    result = run_sandboxed(
        runtime_for(cli),
        "img:1",
        "yes",
        b"",
        Limits(output_bytes=2_000),
        ENV,
        name="sloptriage-t4",
    )
    assert result.truncated is True
    assert len(result.stdout.encode()) <= 2_000 + 200  # cap plus the notice
    assert "truncated" in result.stdout


def test_an_output_flood_kills_the_container(cli: FakeContainerCli) -> None:
    cli.set(flood_bytes=50_000_000)
    result = run_sandboxed(
        runtime_for(cli),
        "img:1",
        "yes",
        b"",
        Limits(output_bytes=1_000, output_kill_bytes=200_000),
        ENV,
        name="sloptriage-t5",
    )
    assert result.truncated is True
    assert result.flooded is True
    assert ["kill", "sloptriage-t5"] in cli.calls()


def test_out_of_memory_kills_are_recorded(cli: FakeContainerCli) -> None:
    cli.set(exit_code=137, oom=True)
    result = run_sandboxed(runtime_for(cli), "img:1", "x", b"", Limits(), ENV, name="sloptriage-t6")
    assert result.oom is True
    assert result.exit_code == 137


def test_control_characters_in_output_are_kept_out_of_the_result(cli: FakeContainerCli) -> None:
    cli.set(stdout="ok\x1b[31mred\x00\n")
    result = run_sandboxed(runtime_for(cli), "img:1", "x", b"", Limits(), ENV, name="sloptriage-t7")
    assert "\x1b" not in result.stdout and "\x00" not in result.stdout


def test_output_beyond_the_kill_threshold_counts_as_a_flood_even_if_the_process_ended_first(
    cli: FakeContainerCli,
) -> None:
    cli.set(stdout="X" * 600_000)
    result = run_sandboxed(
        runtime_for(cli),
        "img:1",
        "x",
        b"",
        Limits(output_bytes=1_000, output_kill_bytes=200_000),
        ENV,
        name="sloptriage-tf",
    )
    assert result.flooded is True and result.truncated is True
