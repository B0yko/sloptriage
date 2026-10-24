"""Turn raw container results into outcomes, and outcomes into the reproduction verdict."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace

from sloptriage.extract import Claim
from sloptriage.repro.errors import ReproError
from sloptriage.repro.runners import Candidate, RunPlan
from sloptriage.repro.runtime import RunResult
from sloptriage.repro.sanitizers import (
    Crash,
    error_types_match,
    parse_output,
    signal_name,
    top_project_frame,
)

_NETWORK_RE = re.compile(
    r"could not resolve host|name or service not known|temporary failure in name resolution|"
    r"network is unreachable|no route to host|nodename nor servname|getaddrinfo\(\) thread failed",
    re.I,
)
_SANITIZER_START_RE = re.compile(
    r"shadow memory range interleaves|asan cannot proceed correctly|unexpected memory mapping", re.I
)
_TOOLS_RE = re.compile(r"command not found\s*$|^\S+: \d+: \S+: not found\s*$", re.M)
_DISPLAY_RE = re.compile(
    r"cannot open display|no display name and no \$display|unable to open display", re.I
)


@dataclass
class RunOutcome:
    candidate: int
    kind: str  # clean, error_exit, crash, timeout, oom, flood, compile_failed
    seconds: float
    exit_code: int | None = None
    signal: str | None = None
    tool: str | None = None
    error_type: str | None = None
    top_function: str | None = None
    top_path: str | None = None
    top_line: int | None = None
    needs: str | None = None  # "network" or "display" when the PoC tried to reach outside
    output: str = ""


def _marker_lines(marker: str) -> re.Pattern[str]:
    return re.compile(rf"^sloptriage-(started|setup-failed|compile-failed):{re.escape(marker)}\s*$")


def classify_run(
    result: RunResult, plan: RunPlan, files: Collection[str], candidate: int
) -> RunOutcome:
    """What one container run amounted to."""
    seen: set[str] = set()
    kept = []
    pattern = _marker_lines(plan.marker) if plan.marker else None
    for line in result.stderr.split("\n"):
        m = pattern.match(line) if pattern else None
        if m:
            seen.add(m.group(1))
        else:
            kept.append(line)
    result = replace(result, stderr="\n".join(kept))
    base = RunOutcome(
        candidate, "clean", result.seconds, result.exit_code, output=_combined(result)
    )
    code = result.exit_code
    if result.timed_out:
        base.kind = "timeout"
        return base
    if result.flooded:
        base.kind = "flood"
        return base
    # The start marker is written before any PoC code runs. Without it the script never began, which
    # no PoC can fake: its exit status 125 to 127 then comes from the runtime, not from the PoC.
    if "started" not in seen and code in (125, 126, 127):
        raise ReproError(f"the container could not be started: {_first_line(result.stderr)}")
    if "setup-failed" in seen:
        raise ReproError("the sandbox could not unpack the PoC files")
    if "compile-failed" in seen:
        base.kind = "compile_failed"
        return base
    if _SANITIZER_START_RE.search(base.output):
        # The kernel's address-space randomisation leaves no room for the sanitizer's shadow memory.
        # Every PoC would fail the same way, so this says nothing about the report.
        base.kind = "sanitizer_unavailable"
        return base
    if result.oom:
        base.kind = "oom"
        base.signal = "SIGKILL"
        return base
    crash = parse_output(base.output)
    sig = signal_name(code)
    # A report printed by a process that then exits 0 is text, not a crash. The exception is
    # UndefinedBehaviorSanitizer built to report and carry on (no -fno-sanitize-recover).
    if crash is not None and (
        code != 0 or (crash.tool == "UndefinedBehaviorSanitizer" and not plan.ubsan_fatal)
    ):
        _fill(base, crash, files)
        return base
    if sig is not None:
        base.kind, base.signal, base.error_type = "crash", sig, sig
        return base
    if code not in (0, None):
        base.kind = "error_exit"
    if _NETWORK_RE.search(base.output):
        base.needs = "network"
    elif _DISPLAY_RE.search(base.output):
        base.needs = "display"
    elif _TOOLS_RE.search(base.output):
        base.needs = "tools"
    return base


def _fill(out: RunOutcome, crash: Crash, files: Collection[str]) -> None:
    out.kind, out.tool, out.error_type = "crash", crash.tool, crash.error_type
    top = top_project_frame(crash, files)
    if top is not None:
        frame, path = top
        out.top_function, out.top_path, out.top_line = frame.function, path, frame.line


def _combined(result: RunResult) -> str:
    return result.stderr + ("\n" if result.stderr and result.stdout else "") + result.stdout


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return "no message"


# -- what the report says ---------------------------------------------------------------------------
def _plain(path: str) -> str:
    while path.startswith("./"):
        path = path[2:]
    return path


@dataclass
class ClaimsView:
    functions: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    error_types: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, claims: Sequence[Claim]) -> ClaimsView:
        view = cls()
        for c in claims:
            if c.kind == "symbol" and c.confidence == "high":
                view.functions.add(c.value.split("::")[-1])
            if c.kind == "frame" and c.function:
                view.functions.add(c.function.split("::")[-1])
            if c.kind in ("path", "line", "frame", "quote") and c.path:
                view.files.add(_plain(c.path))
            if c.kind == "sanitizer_claim" and c.error_type:
                view.error_types.add(c.error_type)
        return view

    def names_file(self, repo_path: str) -> bool:
        return any(
            repo_path == f or f.endswith("/" + repo_path) or repo_path.endswith("/" + f)
            for f in self.files
        )

    def match_kind(self, out: RunOutcome) -> str | None:
        """How a crash relates to the report's claim, or None when it does not match.

        ``function_and_type`` and ``type_and_file`` agree with everything the report says.
        ``function`` means the report claims no error type. ``function_type_differs`` is a function
        the report names with another error type than it claims. ``type_only`` means the type fits
        and the report names no place to compare with.
        """
        if out.top_path is None:
            return None
        type_claimed = bool(self.error_types)
        type_ok = bool(
            out.error_type and any(error_types_match(out.error_type, t) for t in self.error_types)
        )
        if out.top_function and out.top_function.split("::")[-1] in self.functions:
            if not type_claimed:
                return "function"
            return "function_and_type" if type_ok else "function_type_differs"
        if not type_ok:
            return None
        if self.names_file(out.top_path):
            return "type_and_file"
        return "type_only" if not (self.files or self.functions) else None

    def matches(self, out: RunOutcome) -> bool:
        return self.match_kind(out) is not None


# -- the verdict ------------------------------------------------------------------------------------------
@dataclass
class Decision:
    verdict: str
    reason: str
    candidate: Candidate | None
    outcomes: list[RunOutcome]
    match: str | None = None


_RANK = {
    "reproduced": 0,
    "crashed_elsewhere": 1,
    "flaky": 2,
    "timeout": 3,
    "not_reproduced": 4,
    "poc_build_failed": 5,
    "poc_unsupported": 6,
    "build_failed": 7,
}


def _signature(o: RunOutcome) -> tuple[object, ...]:
    return (o.kind, o.error_type, o.top_function, o.top_path)


def decide_candidate(
    cand: Candidate, outcomes: list[RunOutcome], view: ClaimsView
) -> tuple[str, str, str | None]:
    n = len(outcomes)
    kinds = [o.kind for o in outcomes]
    if "sanitizer_unavailable" in kinds:
        return (
            "build_failed",
            "The sanitizer runtime could not start on this host: its address-space randomisation is "
            "too high (try `sudo sysctl -w vm.mmap_rnd_bits=28`). This is a limit of the environment, "
            "not of the report.",
            None,
        )
    if all(k == "compile_failed" for k in kinds):
        return "poc_build_failed", "The PoC did not compile against the project.", None
    if "flood" in kinds:
        return "timeout", "The PoC printed more output than the limit allows and was stopped.", None
    if "timeout" in kinds:
        return "timeout", f"The PoC did not finish within the time limit ({n} run).", None
    crashes = [o for o in outcomes if o.kind in ("crash", "oom")]
    if crashes and len(crashes) < n:
        return "flaky", f"The PoC ended in a crash in {len(crashes)} of {n} runs.", None
    if crashes:
        if len({_signature(o) for o in crashes}) > 1:
            return "flaky", f"The {n} runs ended in different crashes.", None
        first = crashes[0]
        if first.kind == "oom":
            return "crashed_elsewhere", "The PoC was stopped for exceeding the memory limit.", None
        match = view.match_kind(first)
        if match == "function_type_differs":
            return (
                "reproduced",
                "The crash is in a function the report names, but its error type differs from the "
                "one the report claims.",
                match,
            )
        if match is not None:
            return "reproduced", f"The claimed crash occurred in {n} of {n} runs.", match
        if first.top_path is None:
            return "crashed_elsewhere", "The crash is outside the project's own code.", None
        return "crashed_elsewhere", "The crash is not where the report places it.", None
    return "not_reproduced", f"No crash was observed in {n} runs.", None


def decide(
    ran: Sequence[tuple[Candidate, list[RunOutcome]]],
    skipped: Sequence[Candidate],
    view: ClaimsView,
) -> Decision:
    best: Decision | None = None
    for cand, outcomes in ran:
        verdict, reason, match = decide_candidate(cand, outcomes, view)
        if verdict == "not_reproduced":
            hint = next((o.needs for o in outcomes if o.needs), None)
            if hint == "network":
                verdict, reason = (
                    "poc_unsupported",
                    ("The PoC needs network access; PoCs run with no network."),
                )
            elif hint == "display":
                verdict, reason = "poc_unsupported", "The PoC needs a display; none is available."
            elif hint == "tools":
                verdict, reason = (
                    "poc_unsupported",
                    ("The PoC uses a command that is not installed in the sandbox image."),
                )
        d = Decision(verdict, reason, cand, outcomes, match)
        if best is None or _RANK[d.verdict] < _RANK[best.verdict]:
            best = d
    if best is not None:
        return best
    first = skipped[0] if skipped else None
    return Decision(
        "poc_unsupported",
        (first.unsupported if first else None) or "No PoC could be run.",
        first,
        [],
    )
