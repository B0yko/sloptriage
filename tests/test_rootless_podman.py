"""Set SLOPTRIAGE_PODMAN_IMAGE to a local Alpine image to run the live check."""

import os
import subprocess

import pytest

from sloptriage.repro.runtime import (
    SANDBOX_UID,
    Limits,
    Runtime,
    build_run_argv,
    detect_runtime,
    run_sandboxed,
)


def test_podman_uses_the_same_sandbox_flags_as_docker() -> None:
    def argv(name: str) -> list[str]:
        return build_run_argv(Runtime(name, name), "fixture", "control", Limits(), "id", {})

    docker, podman = argv("docker"), argv("podman")
    assert podman == ["podman", *docker[1:]]


def test_live_rootless_podman_controls() -> None:
    image = os.environ.get("SLOPTRIAGE_PODMAN_IMAGE")
    if not image:
        pytest.skip("set SLOPTRIAGE_PODMAN_IMAGE to a local Alpine image for the live check")
    rt = detect_runtime("podman")  # never fall back to Docker or a fake CLI
    rootless = subprocess.run(
        [rt.exe, "info", "--format", "{{.Host.Security.Rootless}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout.strip()
    assert rootless == "true", "this check requires a rootless Podman server"

    # Read kernel settings; write one short file in the designated workspace.
    script = """set -eu
id -u
id -g
awk '/^NoNewPrivs:|^CapEff:/ {print $1, $2}' /proc/self/status
awk '$2 == "/" {print $4}' /proc/mounts
printf '%s\\n' /sys/class/net/*
printf 'fixture-ok\\n' > /work/control
cat /work/control
"""
    result = run_sandboxed(rt, image, script, b"", Limits(timeout=20, output_bytes=4096), {})
    assert result.exit_code == 0, result.stderr
    assert not (result.timed_out or result.truncated or result.flooded or result.oom)
    uid, gid, caps, nnp, mount, interface, marker = result.stdout.splitlines()
    assert int(uid) == int(gid) == SANDBOX_UID != 0
    assert caps.split() == ["CapEff:", "0000000000000000"]
    assert nnp.split() == ["NoNewPrivs:", "1"]
    assert "ro" in mount.split(",")
    assert interface == "/sys/class/net/lo"
    assert marker == "fixture-ok"
