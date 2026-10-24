"""The container runtime: detection, the hardened ``run`` command line and bounded execution.

There is no host-execution mode. Without a working Docker or Podman, nothing is run.

Every PoC attempt is one ``run`` of a throw-away container with: no network, a read-only root
file system, one size-limited tmpfs at ``/work``, a non-root user, no capabilities, no privilege
gain, and limits on processes, memory (swap off), CPU, open files and wall-clock time. Artefacts
arrive on stdin as a tar stream built by this tool, so nothing from the host is mounted. The
environment is exactly the ``-e`` pairs given by the caller.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import signal
import subprocess
import threading
import time
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

SANDBOX_UID = 10001
WORKDIR = "/work"
LABEL = "sloptriage=1"


class RuntimeUnavailable(RuntimeError):
    """No usable container runtime: reproduction refuses to run."""


@dataclass(frozen=True)
class Runtime:
    name: str  # "docker" or "podman"
    exe: str


@dataclass
class Limits:
    timeout: int = 20  # wall-clock seconds for one run
    build_timeout: int = 1800  # seconds for one image build
    memory: str = "512m"
    cpus: float = 1.0
    pids: int = 128
    tmpfs: str = "64m"
    output_bytes: int = 200_000  # kept per stream
    output_kill_bytes: int = 16 * 1024 * 1024  # a run that prints this much is killed
    nofile: int = 1024
    runs: int = 3  # repeated runs per PoC
    candidates: int = 5  # PoCs tried per report


@dataclass
class RunResult:
    stdout: str
    stderr: str
    exit_code: int | None
    seconds: float
    timed_out: bool = False
    oom: bool = False
    truncated: bool = False
    flooded: bool = False

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


# -- detection ---------------------------------------------------------------------------------
def _probe(name: str, exe: str) -> str | None:
    """None when the runtime answers, else a short reason."""
    args = (
        [exe, "version", "--format", "{{.Server.Version}}"] if name == "docker" else [exe, "info"]
    )
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)[:200]
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        return lines[0][:200] if lines else "no answer"
    return None


def detect_runtime(preferred: str = "auto") -> Runtime:
    """Find a Docker or Podman CLI whose daemon answers, or refuse."""
    names = ["docker", "podman"] if preferred == "auto" else [preferred]
    problems = []
    for name in names:
        exe = shutil.which(name)
        if not exe:
            continue
        why = _probe(name, exe)
        if why is None:
            return Runtime(name=name, exe=exe)
        problems.append(f"found {name} at {exe} but its daemon does not respond ({why})")
    if problems:
        raise RuntimeUnavailable("; ".join(problems))
    raise RuntimeUnavailable(
        "no container runtime found: reproduction needs Docker or Podman on PATH. "
        "sloptriage never runs a PoC on the host."
    )


# -- command lines -------------------------------------------------------------------------------
def build_run_argv(
    rt: Runtime,
    image: str,
    name: str,
    limits: Limits,
    script: str,
    env: Mapping[str, str],
) -> list[str]:
    argv = [
        rt.exe,
        "run",
        "--name",
        name,
        "--label",
        LABEL,
        "-i",
        "--init",
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        f"{WORKDIR}:rw,exec,nosuid,nodev,size={limits.tmpfs},mode=0700,"
        f"uid={SANDBOX_UID},gid={SANDBOX_UID}",
        "--user",
        f"{SANDBOX_UID}:{SANDBOX_UID}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(limits.pids),
        "--memory",
        limits.memory,
        "--memory-swap",
        limits.memory,
        "--cpus",
        str(limits.cpus),
        "--ulimit",
        "core=0:0",
        "--ulimit",
        f"nofile={limits.nofile}:{limits.nofile}",
        "--workdir",
        WORKDIR,
    ]
    for key in sorted(env):
        argv += ["-e", f"{key}={env[key]}"]
    argv += [image, "sh", "-c", script]
    return argv


def build_image_argv(rt: Runtime, tag: str, dockerfile: str, *, network: bool) -> list[str]:
    """``build`` with the context streamed on stdin. Only the image stage may use the network."""
    argv = [rt.exe, "build", "--tag", tag, "--file", dockerfile, "--label", LABEL, "--rm"]
    if not network:
        argv += ["--network", "none", "--pull=false"]
    argv.append("-")
    return argv


# -- bounded execution --------------------------------------------------------------------------------
class _Capture:
    """Keeps the start and the end of a stream; the middle of a long one is dropped."""

    def __init__(
        self, cap: int, flood_at: int, tripped: threading.Event, shared: list[int]
    ) -> None:
        self.half = max(cap // 2, 1)
        self.flood_at, self.tripped, self.shared = flood_at, tripped, shared
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0
        self.lock = threading.Lock()

    def pump(self, stream: object) -> None:
        read = stream.read1 if hasattr(stream, "read1") else stream.read  # type: ignore[attr-defined]
        while True:
            chunk = read(65536)
            if not chunk:
                return
            self.total += len(chunk)
            room = self.half - len(self.head)
            if room > 0:
                self.head += chunk[:room]
                rest = chunk[room:]
            else:
                rest = chunk
            if rest:
                self.tail += rest
                if len(self.tail) > self.half:
                    del self.tail[: len(self.tail) - self.half]
            with self.lock:
                self.shared[0] += len(chunk)
                if self.shared[0] > self.flood_at:
                    self.tripped.set()

    @property
    def omitted(self) -> int:
        return self.total - len(self.head) - len(self.tail)

    @property
    def truncated(self) -> bool:
        return self.omitted > 0

    def text(self) -> str:
        parts = [clean_output(bytes(self.head))]
        if self.omitted > 0:
            parts.append(f"\n[output truncated: {self.omitted} bytes omitted]\n")
        parts.append(clean_output(bytes(self.tail)))
        return "".join(parts)


def clean_output(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")


def _cli(rt: Runtime, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [rt.exe, *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def _terminate(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def run_sandboxed(
    rt: Runtime,
    image: str,
    script: str,
    artefacts: bytes,
    limits: Limits,
    env: Mapping[str, str],
    name: str | None = None,
) -> RunResult:
    """Run ``script`` in a fresh hardened container; always inspect and remove the container."""
    name = name or f"sloptriage-{uuid.uuid4().hex[:12]}"
    argv = build_run_argv(rt, image, name, limits, script, env)
    started = time.monotonic()
    tripped = threading.Event()
    shared = [0]
    out = _Capture(limits.output_bytes, limits.output_kill_bytes, tripped, shared)
    err = _Capture(limits.output_bytes, limits.output_kill_bytes, tripped, shared)
    timed_out = flooded = False
    # A cancelled job gets SIGTERM; turn it into an exit that runs the clean-up below.
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGTERM, _terminate)
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        assert proc.stdin and proc.stdout and proc.stderr

        def feed() -> None:
            try:
                assert proc.stdin
                proc.stdin.write(artefacts)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        threads = [
            threading.Thread(target=feed, daemon=True),
            threading.Thread(target=out.pump, args=(proc.stdout,), daemon=True),
            threading.Thread(target=err.pump, args=(proc.stderr,), daemon=True),
        ]
        for t in threads:
            t.start()
        deadline = started + limits.timeout
        killed = False
        while proc.poll() is None:
            if time.monotonic() > deadline:
                timed_out = True
            elif tripped.is_set():
                flooded = True
            if (timed_out or flooded) and not killed:
                killed = True
                try:
                    _cli(rt, "kill", name, timeout=20)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            time.sleep(0.02)
        proc.wait()
        for t in threads:
            t.join(timeout=5)
        oom = False
        try:
            info = _cli(rt, "inspect", "--format", "{{json .State}}", name, timeout=20)
            state = json.loads(info.stdout) if info.returncode == 0 and info.stdout.strip() else {}
            oom = bool(state.get("OOMKilled"))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        seconds = time.monotonic() - started
        return RunResult(
            stdout=out.text(),
            stderr=err.text(),
            exit_code=proc.returncode,
            seconds=seconds,
            timed_out=timed_out,
            oom=oom,
            truncated=out.truncated or err.truncated,
            flooded=flooded,
        )
    finally:
        if proc.poll() is None:
            proc.kill()
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            _cli(rt, "rm", "-f", "-v", name, timeout=30)
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


# -- images ------------------------------------------------------------------------------------------
def image_exists(rt: Runtime, tag: str) -> bool:
    try:
        return _cli(rt, "image", "inspect", tag, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def build_image(
    rt: Runtime, tag: str, dockerfile: str, context: bytes, *, network: bool, timeout: int
) -> tuple[bool, str]:
    """Build an image from an in-memory tar context. Returns (ok, last lines of the build log)."""
    argv = build_image_argv(rt, tag, dockerfile, network=network)
    try:
        proc = subprocess.run(
            argv, input=context, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return False, f"the image build did not finish within {timeout} s"
    except OSError as exc:
        return False, str(exc)
    log = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    tail = "\n".join(log.strip().splitlines()[-40:])
    return proc.returncode == 0, clean_output(tail.encode())[-8000:]
