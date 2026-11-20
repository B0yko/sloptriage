"""Set SLOPTRIAGE_PODMAN_IMAGE to a local Alpine image to run the live checks."""

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


@pytest.fixture(scope="module")
def rootless() -> tuple[Runtime, str]:
    image = os.environ.get("SLOPTRIAGE_PODMAN_IMAGE")
    if not image:
        pytest.skip("set SLOPTRIAGE_PODMAN_IMAGE to a local Alpine image for the live checks")
    rt = detect_runtime("podman")
    info = subprocess.run(
        [rt.exe, "info", "--format", "{{.Host.Security.Rootless}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert info.stdout.strip() == "true", "this check requires a rootless Podman server"
    return rt, image


INSPECT = """set -eu
id -u
id -g
awk '/^NoNewPrivs:|^CapEff:/ {print $1, $2}' /proc/self/status
awk '$2 == "/" {print $4}' /proc/mounts
printf '%s\\n' /sys/class/net/*
"""


def check_settings(output: str) -> None:
    uid, gid, caps, nnp, mount, interface = output.splitlines()
    assert int(uid) == int(gid) == SANDBOX_UID != 0
    assert caps.split() == ["CapEff:", "0000000000000000"]
    assert nnp.split() == ["NoNewPrivs:", "1"]
    assert "ro" in mount.split(",")
    assert interface == "/sys/class/net/lo"


def test_live_rootless_read_only_fixture(rootless: tuple[Runtime, str]) -> None:
    # Independent runtime control: no workspace or test artefacts, only kernel reads.
    rt, image = rootless
    args = [
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--read-only-tmpfs=false",
        "--user",
        f"{SANDBOX_UID}:{SANDBOX_UID}",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=32",
        "--memory=64m",
        "--cpus=1",
        "--timeout=15",
    ]
    proc = subprocess.run(
        [rt.exe, "run", *args, image, "sh", "-c", INSPECT],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    check_settings(proc.stdout)


def test_live_rootless_product_workspace(rootless: tuple[Runtime, str]) -> None:
    rt, image = rootless
    script = INSPECT + "printf 'fixture-ok\\n' > /work/control\ncat /work/control"
    result = run_sandboxed(rt, image, script, b"", Limits(timeout=20, output_bytes=4096), {})
    if result.exit_code == 125 and result.stderr.strip() == (
        'Error: unknown mount option "uid=10001": invalid mount option'
    ):
        version = subprocess.check_output([rt.exe, "--version"], text=True, timeout=10).strip()
        if version == "podman version 4.9.3":
            pytest.xfail(f"{version} rejects the private workspace: {result.stderr.strip()}")
    assert result.exit_code == 0, result.stderr
    assert not (result.timed_out or result.truncated or result.flooded or result.oom)
    output, marker = result.stdout.rstrip("\n").rsplit("\n", 1)
    check_settings(output)
    assert marker == "fixture-ok"
