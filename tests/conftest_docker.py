"""Helpers shared by the container tests: a scriptable fake container CLI."""

from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

FAKE_SCRIPT = r"""#!{python}
import json, os, sys, time
from pathlib import Path

state = Path(os.environ["FAKE_CONTAINER_STATE"])
args = sys.argv[1:]
behaviour = json.loads((state / "behaviour.json").read_text()) if (state / "behaviour.json").exists() else {{}}
with (state / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps(args) + "\n")
verb = args[0] if args else ""
if verb == "version":
    if behaviour.get("daemon_down"):
        sys.stderr.write("Cannot connect to the Docker daemon\n")
        sys.exit(1)
    print("29.0.0")
elif verb == "info":
    sys.exit(1 if behaviour.get("daemon_down") else 0)
elif verb == "run":
    data = sys.stdin.buffer.read()
    (state / "stdin.bin").write_bytes(data)
    (state / "run_args.json").write_text(json.dumps(args))
    out = behaviour.get("stdout", "")
    err = behaviour.get("stderr", "")
    flood = behaviour.get("flood_bytes", 0)
    sys.stdout.write(out)
    sys.stdout.flush()
    sys.stderr.write(err)
    sys.stderr.flush()
    sent = 0
    chunk = "A" * 4096 + "\n"
    while sent < flood:
        try:
            sys.stdout.write(chunk)
            sys.stdout.flush()
        except BrokenPipeError:
            break
        sent += len(chunk)
        if (state / "killed").exists():
            sys.exit(137)
    if behaviour.get("hang"):
        deadline = time.time() + 60
        while time.time() < deadline and not (state / "killed").exists():
            time.sleep(0.05)
        sys.exit(137)
    sys.exit(behaviour.get("exit_code", 0))
elif verb == "inspect":
    print(json.dumps({{"OOMKilled": bool(behaviour.get("oom")), "ExitCode": behaviour.get("exit_code", 0)}}))
elif verb == "kill":
    (state / "killed").write_text("1")
elif verb in ("rm", "image", "build"):
    if verb == "image" and behaviour.get("missing_image"):
        sys.exit(1)
    if verb == "build":
        (state / "build_args.json").write_text(json.dumps(args))
        (state / "build_stdin.bin").write_bytes(sys.stdin.buffer.read())
        sys.exit(behaviour.get("build_exit", 0))
"""


@dataclass
class FakeContainerCli:
    exe: Path
    state: Path

    def set(self, **behaviour: object) -> None:
        (self.state / "behaviour.json").write_text(json.dumps(behaviour))

    def calls(self) -> list[list[str]]:
        path = self.state / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def verbs(self) -> list[str]:
        return [c[0] for c in self.calls()]

    def stdin(self) -> bytes:
        return (self.state / "stdin.bin").read_bytes()


def make_fake_cli(root: Path, name: str = "docker") -> FakeContainerCli:
    bindir = root / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    state = root / "state"
    state.mkdir(exist_ok=True)
    exe = bindir / name
    exe.write_text(FAKE_SCRIPT.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    os.environ["FAKE_CONTAINER_STATE"] = str(state)
    return FakeContainerCli(exe=exe, state=state)
