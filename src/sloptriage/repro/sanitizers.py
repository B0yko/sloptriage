"""Parse what a sanitized or crashing process printed.

Supported: AddressSanitizer, MemorySanitizer, ThreadSanitizer, UndefinedBehaviorSanitizer and
Python tracebacks, plus the exit codes that mean a fatal signal. Frames are returned innermost
first, whatever order the tool printed them in. The first reported stack is the one kept.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Collection
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Frame:
    index: int
    function: str | None
    path: str | None
    line: int | None
    module: str | None = None


@dataclass
class Crash:
    tool: str  # "AddressSanitizer", "MemorySanitizer", "ThreadSanitizer", ..., "python"
    error_type: str
    frames: list[Frame] = field(default_factory=list)
    summary: str | None = None


_SAN_RE = re.compile(
    r"(?:==\d+==)?(?:ERROR|WARNING):\s+(?P<tool>AddressSanitizer|MemorySanitizer|ThreadSanitizer|"
    r"LeakSanitizer|HWAddressSanitizer):\s*(?P<rest>[^\n]+)"
)
_UBSAN_RE = re.compile(
    r"^(?P<path>[^\s:][^\n:]*):(?P<line>\d+):(?P<col>\d+):\s+runtime error:\s+(?P<msg>[^\n]+)",
    re.M,
)
_PY_TB_RE = re.compile(r"^Traceback \(most recent call last\):\s*$", re.M)
_PY_FRAME_RE = re.compile(r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<func>.+?)\s*$')
_PY_EXC_RE = re.compile(r"^(?P<exc>[A-Za-z_][\w.]*)(?::\s.*|:)?$")

_FRAME_RE = re.compile(
    r"^\s*#(?P<idx>\d+)\s+(?:0x[0-9a-fA-F]+\s+)?(?:in\s+)?(?P<func>[^\s(]+(?:\([^)]*\))?)?\s*"
    r"(?P<loc>[^\s()]+)?\s*(?:\((?P<mod>[^)]*)\))?\s*$"
)
_LOC_RE = re.compile(r"^(?P<path>.+?)(?::(?P<line>\d+))?(?::(?P<col>\d+))?$")
_STACK_BREAK = re.compile(r"^(?:allocated|freed|previously|SUMMARY|Location|Shadow)", re.I)
_MAX_LINE = 1000
_MAX_TEXT = 1_000_000
_SIGNALS = {
    132: "SIGILL",
    133: "SIGTRAP",
    134: "SIGABRT",
    135: "SIGBUS",
    136: "SIGFPE",
    137: "SIGKILL",
    139: "SIGSEGV",
}


def signal_name(exit_code: int | None) -> str | None:
    """The signal a shell-style exit status (128 + n) stands for."""
    if exit_code is None:
        return None
    return _SIGNALS.get(exit_code)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _san_type(tool: str, rest: str) -> str:
    rest = rest.strip()
    low = rest.lower()
    if low.startswith("attempting double-free"):
        return "double-free"
    if low.startswith("attempting free on address which was not malloc"):
        return "bad-free"
    if low.startswith("segv") or low.startswith("sigsegv"):
        return "SEGV"
    if tool == "LeakSanitizer":
        return "memory-leak"
    if tool == "ThreadSanitizer" and low.startswith("data race"):
        return "data-race"
    first = rest.split()[0].rstrip(":,(") if rest.split() else "unknown"
    return _slug(first) or "unknown"


_UBSAN_TYPES = (
    (re.compile(r"insufficient space for an object|index \S+ out of bounds"), "out-of-bounds"),
    (re.compile(r"null pointer"), "null-dereference"),
    (re.compile(r"misaligned address"), "misaligned-access"),
    (re.compile(r"division by zero"), "division-by-zero"),
    (re.compile(r"shift exponent|left shift of|shift of"), "shift-out-of-bounds"),
    (re.compile(r"^load of value"), "invalid-value"),
    (re.compile(r"incorrect function type"), "function-type-mismatch"),
    (re.compile(r"variable length array bound"), "vla-bound"),
)


def _ubsan_type(msg: str) -> str:
    low = msg.lower()
    for pattern, name in _UBSAN_TYPES:
        if pattern.search(low):
            return name
    head = low.split(":", 1)[0]
    words = re.findall(r"[a-z]+", head)[:4]
    return _slug(" ".join(words)) or "undefined-behavior"


_BUILD_ID_RE = re.compile(r"\s*\(BuildId: [0-9a-fA-F]+\)\s*$")


def _parse_frame(line: str) -> Frame | None:
    m = _FRAME_RE.match(_BUILD_ID_RE.sub("", line))
    if not m:
        return None
    func, loc, mod = m.group("func"), m.group("loc"), m.group("mod")
    if func and "(" in func:  # a C++ signature such as free_(void*)
        func = func.split("(", 1)[0] or None
    path: str | None = None
    lineno: int | None = None
    if func and func.startswith("("):  # "#3 0x... (/lib/x.so+0x1)" has no function name
        func = None
    if loc and loc != "<null>":
        lm = _LOC_RE.match(loc)
        if lm and ("/" in lm.group("path") or "." in lm.group("path")):
            path = lm.group("path")
            lineno = int(lm.group("line")) if lm.group("line") else None
        elif lm:
            func = func or loc
    return Frame(int(m.group("idx")), func, path, lineno, mod)


def _first_stack(lines: list[str], start: int) -> list[Frame]:
    frames: list[Frame] = []
    skipped = 0
    for raw in lines[start:]:
        if not raw.strip():
            if frames:
                break
            skipped += 1
            if skipped > 6:
                break
            continue
        frame = _parse_frame(raw)
        if frame is None:
            if frames or _STACK_BREAK.match(raw.strip()):
                break
            skipped += 1
            if skipped > 6:
                break
            continue
        if frames and frame.index == 0:
            break
        frames.append(frame)
    return frames


def _python(text: str, at: int) -> Crash | None:
    lines = text[at:].splitlines()
    frames: list[Frame] = []
    exc: str | None = None
    for raw in lines[1:]:
        fm = _PY_FRAME_RE.match(raw)
        if fm:
            frames.append(Frame(0, fm.group("func"), fm.group("path"), int(fm.group("line"))))
            continue
        if raw.startswith(("    ", "\t")) or "Previous line repeated" in raw or not raw.strip():
            continue
        em = _PY_EXC_RE.match(raw.strip())
        if em:
            exc = em.group("exc").rsplit(".", 1)[-1]
        break
    if exc is None:
        return None
    ordered = [
        Frame(i, f.function, f.path, f.line, f.module) for i, f in enumerate(reversed(frames))
    ]
    return Crash("python", exc, ordered, exc)


def parse_output(text: str) -> Crash | None:
    """The first sanitizer report or Python traceback in ``text``, or None."""
    if not text:
        return None
    # A PoC controls its output. Bound what the patterns see so that no line can make them slow.
    text = "\n".join(line[:_MAX_LINE] for line in text[:_MAX_TEXT].split("\n"))
    found: list[tuple[int, str]] = []
    san = _SAN_RE.search(text)
    if san:
        found.append((san.start(), "san"))
    ub = _UBSAN_RE.search(text)
    if ub:
        found.append((ub.start(), "ub"))
    tb = _PY_TB_RE.search(text)
    if tb:
        found.append((tb.start(), "py"))
    for _pos, kind in sorted(found):
        if kind == "py":
            assert tb is not None
            crash = _python(text, tb.start())
            if crash:
                return crash
        elif kind == "san":
            assert san is not None
            lines = text[san.end() :].splitlines()
            tool = san.group("tool")
            return Crash(
                tool,
                _san_type(tool, san.group("rest")),
                _first_stack(lines, 1 if lines and lines[0].strip() == "" else 0),
                san.group("rest").strip()[:200],
            )
        else:
            assert ub is not None
            lines = text[ub.end() :].splitlines()
            frames = _first_stack(lines, 1 if lines and lines[0].strip() == "" else 0)
            if not frames:
                frames = [Frame(0, None, ub.group("path"), int(ub.group("line")))]
            return Crash(
                "UndefinedBehaviorSanitizer",
                _ubsan_type(ub.group("msg")),
                frames,
                ub.group("msg").strip()[:200],
            )
    return None


# -- relating a crash to the report ------------------------------------------------------------
_BOUNDS = {
    "heap-buffer-overflow",
    "stack-buffer-overflow",
    "global-buffer-overflow",
    "dynamic-stack-buffer-overflow",
    "container-overflow",
    "heap-buffer-underflow",
    "stack-buffer-underflow",
    "global-buffer-underflow",
}
_GENERIC_BOUNDS = {"buffer-overflow", "out-of-bounds", "buffer-overrun"}


def error_types_match(found: str, claimed: str) -> bool:
    """Does the sanitizer's error type fit the type a report claims?"""
    if found == claimed:
        return True
    if found in _BOUNDS and claimed in _GENERIC_BOUNDS:
        return True
    if found == "out-of-bounds" and claimed in _GENERIC_BOUNDS | _BOUNDS:
        return True
    if found == "SEGV" and claimed == "null-dereference":
        return True
    if found == "null-dereference" and claimed == "SEGV":
        return True
    if found.endswith("-use-after-free") and claimed == "use-after-free":
        return True
    if found.endswith("integer-overflow") and claimed == "integer-overflow":
        return True
    return (
        claimed == "undefined-behavior"
        and found not in _BOUNDS
        and "-" in found
        and (found.startswith(("signed", "unsigned", "shift", "division", "null", "misaligned")))
    )


_NOT_PROJECT = ("/work/", "/usr/", "/lib/", "/lib64/", "/opt/project/include/", "/proc/")
_SITE = re.compile(r"(?:site|dist)-packages/(?P<rel>.+)$")


def repo_path(
    path: str | None, files: Collection[str], build_root: str = "/build/src/"
) -> str | None:
    """Map a path printed inside the container to a file of the checked-out commit."""
    if not path:
        return None
    if path.startswith(build_root):
        rel = posixpath.normpath(path[len(build_root) :])
        return rel if rel in files else None
    if not path.startswith("/") or path.startswith("/work/"):
        return None
    site = _SITE.search(path)
    if site:
        rel = posixpath.normpath(site.group("rel"))
        hits = sorted((f for f in files if f == rel or f.endswith("/" + rel)), key=len)
        return hits[0] if hits else None
    if path.startswith(_NOT_PROJECT):
        return None
    hits = sorted((f for f in files if path.endswith("/" + f)), key=len, reverse=True)
    return hits[0] if hits else None


INSTALL_PREFIX = "/opt/project/"


def top_project_frame(
    crash: Crash, files: Collection[str], prefix: str = INSTALL_PREFIX
) -> tuple[Frame, str] | None:
    """The innermost frame that sits in the project, with its repository path.

    A frame inside a shared library the project installed carries a function name but no source
    line; it counts as the project's, with an empty path.
    """
    for frame in crash.frames:
        mapped = repo_path(frame.path, files)
        if mapped:
            return frame, mapped
        module = (frame.module or "").split("+", 1)[0]
        if frame.function and module.startswith(prefix):
            return frame, ""
    return None
