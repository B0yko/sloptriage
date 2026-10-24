"""Reproduction against a real container runtime.

Skipped when neither Docker nor Podman answers. The sandbox probes run hostile-looking PoC
behaviour (network, writes outside ``/work``, host environment, process and memory bombs,
endless loops, floods of output, symlink tricks) and assert that each one fails safely. Every
probe is bounded, so none can harm the host even if a limit were missing.

Set ``SLOPTRIAGE_TEST_IMAGE`` to use another small Python image.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from collections.abc import Iterator

import pytest

from sloptriage import demo
from sloptriage.demo_run import check_all
from sloptriage.repro.runners import artefact_tar, preamble, sandbox_env
from sloptriage.repro.runtime import (
    LABEL,
    Limits,
    RunResult,
    Runtime,
    RuntimeUnavailable,
    detect_runtime,
    run_sandboxed,
)

pytestmark = pytest.mark.docker

IMAGE = os.environ.get("SLOPTRIAGE_TEST_IMAGE", "python:3.12-slim")


@pytest.fixture(scope="module")
def runtime() -> Runtime:
    try:
        rt = detect_runtime()
    except RuntimeUnavailable as exc:
        pytest.skip(str(exc))
    if subprocess.run([rt.exe, "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        pulled = subprocess.run([rt.exe, "pull", "-q", IMAGE], capture_output=True)
        if pulled.returncode != 0:
            pytest.skip(f"cannot pull {IMAGE}")
    return rt


def probe(
    rt: Runtime, script: str, files: dict[str, bytes] | None = None, **limits: object
) -> RunResult:
    lim = Limits(timeout=30, **limits)  # type: ignore[arg-type]
    return run_sandboxed(
        rt, IMAGE, textwrap.dedent(script), artefact_tar(files or {}), lim, sandbox_env()
    )


def py(code: str) -> str:
    return "python3 - <<'PY'\n" + textwrap.dedent(code) + "\nPY\n"


@pytest.fixture(autouse=True)
def _no_leftover_containers(runtime: Runtime) -> Iterator[None]:
    yield
    left = subprocess.run(
        [runtime.exe, "ps", "-aq", "--filter", f"label={LABEL}"], capture_output=True, text=True
    ).stdout.split()
    assert not left, f"containers left behind: {left}"


# -- the hardening, read from inside ---------------------------------------------------------------
def test_process_runs_as_an_unprivileged_user_without_capabilities(runtime: Runtime) -> None:
    out = probe(
        runtime,
        """
        id -u
        grep -E '^(CapEff|CapBnd|NoNewPrivs|Seccomp):' /proc/self/status
        """,
    )
    assert out.exit_code == 0, out.stderr
    assert out.stdout.splitlines()[0] == "10001"
    status = dict(line.split(":\t") for line in out.stdout.splitlines()[1:])
    assert int(status["CapEff"], 16) == 0
    assert int(status["CapBnd"], 16) == 0
    assert status["NoNewPrivs"].strip() == "1"
    assert status["Seccomp"].strip() == "2"  # the runtime's default filter stays on


def test_resource_limits_reach_the_cgroup(runtime: Runtime) -> None:
    out = probe(
        runtime,
        "cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/pids.max /sys/fs/cgroup/cpu.max 2>/dev/null",
        memory="128m",
        pids=32,
        cpus=1.0,
    )
    lines = out.stdout.split("\n")
    if len(lines) < 3 or not lines[0].strip().isdigit():
        pytest.skip("cgroup v2 limits are not readable here")
    assert int(lines[0]) == 128 * 1024 * 1024
    assert lines[1].strip() == "32"
    assert lines[2].split()[0] == "100000"


def test_open_files_core_dumps_and_swap_are_limited(runtime: Runtime) -> None:
    out = probe(
        runtime,
        "ulimit -n; ulimit -c; cat /sys/fs/cgroup/memory.swap.max 2>/dev/null || echo unreadable",
        memory="128m",
    )
    lines = out.stdout.split()
    assert lines[0] == "1024" and lines[1] == "0"
    if lines[2] != "unreadable":
        assert lines[2] == "0"  # swap is off


def test_dev_shm_is_the_one_other_writable_place_and_it_is_small_and_not_executable(
    runtime: Runtime,
) -> None:
    out = probe(
        runtime,
        py(
            """
            import os
            open("/dev/shm/x", "w").write("1")
            print("SHM_WRITABLE")
            try:
                with open("/dev/shm/big", "wb") as fh:
                    for _ in range(200):
                        fh.write(b"0" * 1024 * 1024); fh.flush()
                print("SHM_UNLIMITED")
            except OSError:
                print("SHM_FULL")
            print("SHM_NOEXEC", bool(os.statvfs("/dev/shm").f_flag & os.ST_NOEXEC))
            """
        ),
    )
    assert "SHM_WRITABLE" in out.stdout and "SHM_FULL" in out.stdout
    assert "SHM_NOEXEC True" in out.stdout


def test_the_in_container_watchdog_ends_a_run_even_if_the_tool_is_gone(runtime: Runtime) -> None:
    from sloptriage.repro.runners import watchdog

    started = time.monotonic()
    out = run_sandboxed(
        runtime,
        IMAGE,
        watchdog(2) + "\nwhile :; do :; done",
        artefact_tar({}),
        Limits(timeout=60),
        sandbox_env(),
    )
    assert out.timed_out is False  # it ended by itself, long before the tool's 60 s
    assert time.monotonic() - started < 30
    assert out.exit_code == 137


def test_loopback_works_but_nothing_else_is_reachable(runtime: Runtime) -> None:
    out = probe(
        runtime,
        py(
            """
            import socket
            srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
            cli = socket.create_connection(srv.getsockname(), timeout=2)
            print("LOOPBACK_OK")
            for host, port in (("1.1.1.1", 53), ("8.8.8.8", 443), ("169.254.169.254", 80)):
                try:
                    socket.create_connection((host, port), timeout=2)
                    print("REACHED", host)
                except OSError as exc:
                    print("BLOCKED", host, type(exc).__name__)
            try:
                socket.getaddrinfo("example.com", 80)
                print("RESOLVED")
            except OSError:
                print("NO_DNS")
            """
        ),
    )
    assert "LOOPBACK_OK" in out.stdout
    assert "REACHED" not in out.stdout and "RESOLVED" not in out.stdout
    assert out.stdout.count("BLOCKED") == 3 and "NO_DNS" in out.stdout


def test_only_the_scratch_directories_are_writable(runtime: Runtime) -> None:
    out = probe(
        runtime,
        py(
            """
            import os
            for path in ("/etc/x", "/usr/x", "/tmp/x", "/x", "/var/tmp/x", "/opt/x", "/work/x"):
                try:
                    open(path, "w").write("1")
                    print("WROTE", path)
                except OSError as exc:
                    print("DENIED", path, exc.errno)
            print("WORK_TMP", os.access("/work/tmp", os.W_OK))
            """
        ),
    )
    wrote = [line.split()[1] for line in out.stdout.splitlines() if line.startswith("WROTE")]
    assert wrote == ["/tmp/x", "/work/x"]  # the two size-limited tmpfs mounts, nothing else


def test_the_work_space_has_a_size_limit(runtime: Runtime) -> None:
    out = probe(
        runtime,
        py(
            """
            written = 0
            try:
                with open("/work/big", "wb") as fh:
                    while written < 200 * 1024 * 1024:
                        fh.write(b"0" * 1024 * 1024); fh.flush(); written += 1024 * 1024
                print("NO_LIMIT")
            except OSError as exc:
                print("FULL", exc.errno, written // (1024 * 1024))
            """
        ),
        tmpfs="32m",
    )
    assert "FULL" in out.stdout and "NO_LIMIT" not in out.stdout
    assert int(out.stdout.split()[-1]) <= 32


def test_host_environment_and_docker_socket_are_invisible(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLOPTRIAGE_CANARY", "host-secret-value")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_host_token_value")
    out = probe(runtime, "env; ls -la /var/run /run 2>&1; ls / 2>&1; id -un 2>&1")
    assert "host-secret-value" not in out.output and "ghp_host_token_value" not in out.output
    assert "SLOPTRIAGE_CANARY" not in out.output and "GITHUB_TOKEN" not in out.output
    assert "docker.sock" not in out.output and "podman.sock" not in out.output
    user = os.environ.get("USER", "")
    assert not user or f"USER={user}" not in out.output
    assert "ASAN_OPTIONS=detect_leaks=0" in out.stdout


def test_fork_bomb_is_stopped_by_the_process_limit(runtime: Runtime) -> None:
    out = probe(
        runtime,
        py(
            """
            import subprocess
            started, failed = 0, 0
            kids = []
            for _ in range(2000):
                try:
                    kids.append(subprocess.Popen(["sleep", "5"]))
                    started += 1
                except OSError:
                    failed += 1
                    break
            print("STARTED", started, "FAILED", failed)
            for k in kids:
                k.kill()
            """
        ),
        pids=24,
    )
    words = out.stdout.split()
    started, failed = int(words[1]), int(words[3])
    assert failed == 1 and 0 < started < 24


def test_memory_bomb_is_killed_and_recorded(runtime: Runtime) -> None:
    out = probe(
        runtime,
        py(
            """
            chunks = []
            for _ in range(64):  # 64 x 64 MiB at most, far above the 96 MiB limit
                chunks.append(bytearray(64 * 1024 * 1024))
                for i in range(0, len(chunks[-1]), 4096):
                    chunks[-1][i] = 1
            print("SURVIVED")
            """
        ),
        memory="96m",
    )
    assert "SURVIVED" not in out.stdout
    assert out.oom or out.exit_code == 137
    assert out.timed_out is False


def test_endless_loop_hits_the_wall_clock_and_the_container_is_killed(runtime: Runtime) -> None:
    started = time.monotonic()
    rt_limits = Limits(timeout=3)
    out = run_sandboxed(
        runtime, IMAGE, "while :; do :; done", artefact_tar({}), rt_limits, sandbox_env()
    )
    assert out.timed_out is True
    assert time.monotonic() - started < 25


def test_endless_output_is_cut_off_and_the_run_is_stopped(runtime: Runtime) -> None:
    out = run_sandboxed(
        runtime,
        IMAGE,
        "yes sloptriage-flood",
        artefact_tar({}),
        Limits(timeout=30, output_bytes=50_000, output_kill_bytes=2 * 1024 * 1024),
        sandbox_env(),
    )
    assert out.truncated is True and out.flooded is True
    assert len(out.stdout.encode()) < 50_000 + 200
    assert "truncated" in out.stdout
    assert out.timed_out is False


def test_symlinks_in_the_work_directory_lead_nowhere_useful(runtime: Runtime) -> None:
    out = probe(
        runtime,
        py(
            """
            import os
            os.symlink("/etc/passwd", "/work/to_passwd")
            os.symlink("/", "/work/to_root")
            os.symlink("/proc/1/environ", "/work/to_environ")
            for target in ("/work/to_passwd", "/work/to_root/etc/hostname", "/work/to_root/work/via"):
                try:
                    open(target, "a").write("x")
                    print("WROTE", target)
                except OSError as exc:
                    print("DENIED", target, exc.errno)
            print("HOST_USERS_VISIBLE", os.path.exists("/Users"), os.path.exists("/home/runner"))
            try:
                print("ENVIRON_BYTES", len(open("/work/to_environ", "rb").read()))
            except OSError as exc:
                print("ENVIRON_DENIED", exc.errno)
            """
        ),
    )
    wrote = [line for line in out.stdout.splitlines() if line.startswith("WROTE")]
    assert wrote == ["WROTE /work/to_root/work/via"]  # inside the same tmpfs, nowhere else
    assert "HOST_USERS_VISIBLE False False" in out.stdout


def test_hostile_artefact_names_cannot_escape_the_work_directory(runtime: Runtime) -> None:
    from sloptriage.models import Attachment, Report
    from sloptriage.repro.runners import attachment_files

    report = Report(
        "eml",
        "r",
        "t",
        "b",
        attachments=[Attachment("../../etc/cron.d/x", b"1"), Attachment("/abs/evil", b"2")],
    )
    files = attachment_files(report)
    assert set(files) == {"x", "evil"}
    out = probe(
        runtime, "\n".join(preamble()) + "\nls -la /work/poc 2>&1; ls /etc/cron.d 2>&1", files
    )
    assert "x" in out.stdout and "evil" in out.stdout
    assert "/etc/cron.d/x" not in out.stdout


# -- two-part PoCs ----------------------------------------------------------------------------------------
SERVER = """\
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 8099)); s.listen(1)
c, _ = s.accept(); c.sendall(b"hello from server"); c.close()
print("server done")
sys.exit(EXIT)
"""
CLIENT = "python3 -c 'import socket; print(socket.create_connection((\"127.0.0.1\", 8099), timeout=5).recv(32))'\n"


def two_part(runtime: Runtime, server_exit: int) -> RunResult:
    from sloptriage.config import parse_config
    from sloptriage.repro.recipes import recipe_from_config
    from sloptriage.repro.runners import Candidate, script_for

    cfg = parse_config(
        {"version": 1, "project": {"name": "p"}, "repro": {"build": {"preset": "python-pip"}}},
        "t.yml",
    )
    recipe = recipe_from_config(cfg.repro, "p")
    server = Candidate(
        0,
        "python",
        "inline",
        "server.py",
        SERVER.replace("EXIT", str(server_exit)).encode(),
        None,
        "server",
        0,
    )
    client = Candidate(1, "shell", "inline", "poc.sh", CLIENT.encode(), None, "main", 1)
    plan = script_for(client, server, recipe, cfg.repro, "p")
    return run_sandboxed(
        runtime, IMAGE, plan.script, artefact_tar(plan.files), Limits(timeout=30), sandbox_env()
    )


def test_a_local_server_and_its_client_run_together_over_loopback(runtime: Runtime) -> None:
    out = two_part(runtime, 0)
    assert out.exit_code == 0, out.stderr
    assert "hello from server" in out.stdout
    assert "server done" in out.stderr  # the server's own output is kept


def test_a_server_that_dies_after_serving_decides_the_exit_status(runtime: Runtime) -> None:
    assert two_part(runtime, 3).exit_code == 3


# -- the synthetic set, end to end ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def synthetic(runtime: Runtime) -> list[tuple[demo.DemoReport, dict[str, object]]]:
    return check_all(repro=True)


def test_every_working_poc_reproduces_and_no_low_quality_poc_does(
    synthetic: list[tuple[demo.DemoReport, dict[str, object]]],
) -> None:
    wrong = []
    for rep, verdict in synthetic:
        if rep.poc == "none":
            continue
        got = (verdict["reproduction"] or {}).get("verdict")  # type: ignore[attr-defined]
        if (got == "reproduced") != rep.poc_reproduces:
            wrong.append((rep.file, rep.poc_reproduces, got))
    assert not wrong, wrong


def test_low_quality_pocs_end_in_the_expected_non_reproduced_verdicts(
    synthetic: list[tuple[demo.DemoReport, dict[str, object]]],
) -> None:
    expected = {
        "35-fabricated-trace-chunked.md": "not_reproduced",
        "41-own-buffer-host.md": "crashed_elsewhere",
        "42-own-buffer-strerror.md": "crashed_elsewhere",
        "43-no-lib-double-free.md": "crashed_elsewhere",
        "44-no-lib-array.md": "crashed_elsewhere",
        "45-no-compile-set-raw.md": "poc_build_failed",
        "46-no-compile-url-new.md": "poc_build_failed",
        "48-version-200.md": "not_reproduced",
        "58-stale-concat.md": "not_reproduced",
        "59-benign-poc-normal-url.md": "not_reproduced",
    }
    got = {
        rep.file: (v["reproduction"] or {}).get("verdict")  # type: ignore[attr-defined]
        for rep, v in synthetic
        if rep.file in expected
    }
    assert got == expected
