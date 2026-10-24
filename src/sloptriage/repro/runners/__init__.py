"""PoC candidates: what to run, in which file, and the container script that runs it.

A candidate comes from the report text (a fenced block the extractor classified as a PoC) or from
an attachment. The PoC bytes are passed to the container unchanged; this module never edits,
completes or repairs a PoC. The only transformations are decoding a declared data block and, for a
terminal transcript, keeping the lines that start with a ``$`` prompt (without the prompt).
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import secrets
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from sloptriage.extract import Extraction, unsupported_poc_fences
from sloptriage.models import Report
from sloptriage.repro.config import ReproConfig
from sloptriage.repro.recipes import Recipe
from sloptriage.repro.runners import c as c_runner
from sloptriage.repro.runners import input as input_runner
from sloptriage.repro.runners import python as python_runner
from sloptriage.repro.runners import shell as shell_runner

WORK_DIR = "/work/poc"
COMPILE_FAILED = 253
SETUP_FAILED = 252
MAX_ARTEFACT = 2 * 1024 * 1024
MAX_ARTEFACT_TOTAL = 8 * 1024 * 1024
MAX_ARTEFACT_COUNT = 50
MAX_INPUT = 1024 * 1024
KINDS = ("c", "cpp", "python", "shell", "input")
_SUFFIX_KIND = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".py": "python",
    ".sh": "shell",
    ".bash": "shell",
}
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SERVER_RE = re.compile(r"\b(?:server|listener|daemon)\b", re.I)
_CLIENT_RE = re.compile(r"\b(?:client|poc|exploit|trigger|reproducer|payload)\b", re.I)


WATCHDOG_MARGIN = 15  # seconds the in-container watchdog allows beyond the tool's own limit


def watchdog(seconds: int) -> str:
    """Kill everything the sandbox user owns after ``seconds``, whether or not the tool is alive.

    The tool kills the container itself at its wall-clock limit. This is the backstop for a tool that
    was killed (a cancelled CI job): the container's main process dies and the container exits.
    """
    return f"( sleep {seconds}; kill -9 -1 ) >/dev/null 2>&1 &"


def preamble(marker: str = "0" * 16, timeout: int = 20) -> list[str]:
    """Start-up lines of every script. The markers are per-run random and go to stderr.

    ``started`` is written before any PoC code runs, so a runtime failure can be told from a PoC's
    exit status. ``setup-failed`` and ``compile-failed`` are written before the PoC starts as well.
    """
    fail = f'{{ echo "sloptriage-setup-failed:{marker}" >&2; exit {SETUP_FAILED}; }}'
    return [
        "set -u",
        f'echo "sloptriage-started:{marker}" >&2',
        watchdog(timeout + WATCHDOG_MARGIN),
        f"mkdir -p /work/tmp /work/poc && cd /work/poc || {fail}",
        f"tar -xf - -C /work/poc || {fail}",
    ]


@dataclass(frozen=True)
class Candidate:
    index: int
    kind: str  # c, cpp, python, shell, input, or unsupported
    source: str  # "inline" or "attachment"
    name: str  # file name inside the container's work directory
    data: bytes | None
    unsupported: str | None
    role: str  # "main" or "server"
    position: int  # offset in the report, for ordering


@dataclass
class RunPlan:
    files: dict[str, bytes]
    script: str
    label: str
    compile_failed_code: int | None = None
    marker: str = ""
    ubsan_fatal: bool = True  # does a UBSan report stop the program (-fno-sanitize-recover)?
    extra: dict[str, str] = field(default_factory=dict)


# -- names and archives ---------------------------------------------------------------------------
def safe_artefact_name(raw: str) -> str:
    base = re.split(r"[\\/]", raw.strip())[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    base = re.sub(r"^[^A-Za-z0-9]+", "", base)  # never an option, a dotfile or an empty stem
    if not base:
        return "artefact"
    stem, dot, ext = base.rpartition(".")
    if not dot or len(ext) > 8 or not stem:
        return base[:96]
    return stem[:96] + "." + ext


def artefact_tar(files: Mapping[str, bytes]) -> bytes:
    """A tar stream of plain files, flat, owned by root, with no links and no special bits."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for name in sorted(files):
            data = files[name]
            if not _NAME_RE.fullmatch(name):
                raise ValueError(f"invalid artefact name {name!r}")
            if data is not None and len(data) > MAX_ARTEFACT:
                raise ValueError(f"artefact {name!r} is too large ({len(data)} bytes)")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            info.type = tarfile.REGTYPE
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def attachment_files(report: Report) -> dict[str, bytes]:
    """Report attachments under plain names; oversized ones are left out."""
    out: dict[str, bytes] = {}
    total = 0
    for att in report.attachments:
        if len(att.content) > MAX_ARTEFACT or total + len(att.content) > MAX_ARTEFACT_TOTAL:
            continue
        if len(out) >= MAX_ARTEFACT_COUNT:
            break
        total += len(att.content)
        name = safe_artefact_name(att.name)
        stem, dot, ext = name.rpartition(".")
        n = 2
        while name in out:
            name = f"{stem}-{n}.{ext}" if dot else f"{name}-{n}"
            n += 1
        out[name] = att.content
    return out


# -- decoding ---------------------------------------------------------------------------------
def decode_data_block(text: str, lang: str) -> bytes | None:
    """The bytes a base64 or hex block declares, or None when it is not valid."""
    compact = re.sub(r"\s+", "", text)
    data: bytes | None
    if lang == "hex" or (lang != "base64" and re.fullmatch(r"(?:0x)?[0-9a-fA-F,:]+", compact)):
        digits = re.sub(r"0x|[,:]", "", re.sub(r"\s+", " ", text)).replace(" ", "")
        try:
            data = bytes.fromhex(digits)
        except ValueError:
            return None
    else:
        try:
            data = base64.b64decode(compact, validate=True)
        except (binascii.Error, ValueError):
            return None
    return data if 0 < len(data) <= MAX_INPUT else None


# -- candidates ------------------------------------------------------------------------------
def _file_name(kind: str, role: str) -> str:
    stem = "server" if role == "server" else "poc"
    return {
        "c": f"{stem}.c",
        "cpp": f"{stem}.cpp",
        "python": f"{stem}.py",
        "shell": f"{stem}.sh",
        "input": "input.bin",
    }.get(kind, f"{stem}.txt")


def _role(report_text: str, start: int, info: str, kind: str) -> str:
    if kind not in ("c", "cpp", "python", "shell"):
        return "main"
    before = report_text[max(0, start - 200) : start].rstrip()
    last = before.rsplit("\n", 1)[-1]
    label = f"{last} {info}"
    return "server" if _SERVER_RE.search(label) and not _CLIENT_RE.search(label) else "main"


_TOP_LEVEL_STATEMENT = re.compile(r"^(?!\s|#|def |class |import |from |@|$)\S", re.M)


def _python_scripts_using_the_project(
    text: str, extraction: Extraction, names: Sequence[str]
) -> list[tuple[int, str]]:
    """Unlabelled Python blocks that import the project and then do something: scripts, not quotes."""
    claimed = {b.fence.start for b in extraction.poc_blocks}
    claimed |= {c.start for c in extraction.by_kind("quote")}
    modules = {re.sub(r"[^A-Za-z0-9_]", "_", n.lower()) for n in names if n}
    if not modules:
        return []
    pattern = re.compile(rf"^\s*(?:import|from)\s+(?:{'|'.join(sorted(modules))})\b", re.M)
    out = []
    for fence in extraction.fences:
        tag = fence.info.split()[0].lower() if fence.info.split() else ""
        if fence.start in claimed or tag not in ("python", "py", "python3"):
            continue
        if pattern.search(fence.body) and _TOP_LEVEL_STATEMENT.search(fence.body):
            out.append((fence.start, fence.body))
    return out


def candidates_from_report(
    report: Report,
    extraction: Extraction,
    conf: ReproConfig,
    project_names: Sequence[str] = (),
) -> list[Candidate]:
    text = report.text.replace("\r\n", "\n").replace("\r", "\n")  # the extractor's offsets
    found: list[Candidate] = []
    seen: set[tuple[str, bytes]] = set()
    for block in sorted(extraction.poc_blocks, key=lambda b: b.fence.start):
        kind, body = block.kind, block.fence.body
        reason: str | None = None
        data: bytes | None = body.encode("utf-8")
        if data is not None and len(data) > MAX_ARTEFACT:
            reason = "the PoC is larger than 2 MiB"
        elif kind not in KINDS:
            reason = f"{kind or 'this'} PoCs are not supported (C, C++, Python and shell only)"
            kind = "unsupported"
        elif kind == "input":
            data = decode_data_block(body, block.lang)
            if data is None:
                reason = "the data block could not be decoded as base64 or hex"
            elif not conf.harness:
                reason = "an input file needs repro.harness in .sloptriage.yml (no harness is configured)"
        if reason is None and kind not in conf.runners:
            reason = f"the {kind} runner is not enabled in repro.runners"
        if data is not None and (kind, data) in seen:
            continue  # the same PoC pasted twice
        if data is not None:
            seen.add((kind, data))
        role = _role(text, block.fence.start, block.fence.info, kind)
        found.append(
            Candidate(
                0, kind, "inline", _file_name(kind, role), data, reason, role, block.fence.start
            )
        )
    if not found:
        for start, body in _python_scripts_using_the_project(text, extraction, project_names):
            reason = (
                None
                if "python" in conf.runners
                else "the python runner is not enabled in repro.runners"
            )
            found.append(
                Candidate(0, "python", "inline", "poc.py", body.encode(), reason, "main", start)
            )
    for fence, lang in unsupported_poc_fences(text, extraction):
        found.append(
            Candidate(
                0,
                "unsupported",
                "inline",
                "poc.txt",
                None,
                f"{lang} PoCs are not supported (C, C++, Python and shell only)",
                "main",
                fence.start,
            )
        )
    for att in report.attachments:
        suffix = "." + att.name.rsplit(".", 1)[-1].lower() if "." in att.name else ""
        kind = _SUFFIX_KIND.get(suffix, "")
        if not kind or len(att.content) > MAX_ARTEFACT:
            continue
        reason = (
            None if kind in conf.runners else f"the {kind} runner is not enabled in repro.runners"
        )
        found.append(
            Candidate(
                0,
                kind,
                "attachment",
                safe_artefact_name(att.name),
                att.content,
                reason,
                "main",
                len(text) + len(found),
            )
        )
    found.sort(key=lambda c: c.position)
    limit = conf.limits.candidates
    return [
        Candidate(i, c.kind, c.source, c.name, c.data, c.unsupported, c.role, c.position)
        for i, c in enumerate(found[:limit])
    ]


# -- environment and scripts ------------------------------------------------------------------------------
def sandbox_env() -> dict[str, str]:
    """The whole environment of a PoC run. Nothing is inherited from the host."""
    return {
        "ASAN_OPTIONS": "detect_leaks=0:symbolize=1:print_summary=1:handle_segv=1",
        "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1",
        "HOME": "/work",
        "TMPDIR": "/work/tmp",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }


@dataclass
class Prepared:
    files: dict[str, bytes]
    compile: str  # shell lines that build the PoC (may be empty)
    run: str  # the command that starts it


def _prepare(
    cand: Candidate, recipe: Recipe, conf: ReproConfig, project: str, marker: str
) -> Prepared:
    data = cand.data or b""
    if cand.kind in ("c", "cpp"):
        return c_runner.prepare(cand.name, data, cand.kind, recipe, marker)
    if cand.kind == "python":
        return python_runner.prepare(cand.name, data)
    if cand.kind == "shell":
        return shell_runner.prepare(cand.name, data)
    if cand.kind == "input":
        return input_runner.prepare(cand.name, data, conf.harness or "")
    raise ValueError(f"cannot run a {cand.kind} candidate")


def script_for(
    cand: Candidate,
    companion: Candidate | None,
    recipe: Recipe,
    conf: ReproConfig,
    project: str,
) -> RunPlan:
    marker = secrets.token_hex(8)
    main = _prepare(cand, recipe, conf, project, marker)
    files = dict(main.files)
    lines = preamble(marker, conf.limits.timeout)
    ubsan_fatal = any(f.startswith("-fno-sanitize-recover") for f in recipe.sanitizer_flags)
    compiles = bool(main.compile)
    if companion is None:
        if main.compile:
            lines.append(main.compile)
        lines.append(f"exec {main.run} < /dev/null")
        return RunPlan(
            files,
            "\n".join(lines) + "\n",
            cand.kind,
            COMPILE_FAILED if compiles else None,
            marker,
            ubsan_fatal,
        )
    server = _prepare(companion, recipe, conf, project, marker)
    files.update(server.files)
    compiles = compiles or bool(server.compile)
    for part in (server.compile, main.compile):
        if part:
            lines.append(part)
    lines += [
        f"{server.run} > /work/server.log 2>&1 < /dev/null &",
        "srv=$!",
        # wait (at most 5 s) for the server to listen instead of guessing a pause
        "i=0",
        'while [ "$i" -lt 50 ]; do',
        "  grep -q ' 0A ' /proc/net/tcp /proc/net/tcp6 2>/dev/null && break",
        "  sleep 0.1; i=$((i+1))",
        "done",
        f"{main.run} < /dev/null",
        "rc=$?",
        "sleep 0.3",
        'if kill -0 "$srv" 2>/dev/null; then srv_rc=0; kill "$srv" 2>/dev/null; wait "$srv" 2>/dev/null;'
        ' else wait "$srv"; srv_rc=$?; fi',
        "cat /work/server.log >&2",
        'if [ "$rc" -ne 0 ]; then exit "$rc"; fi',
        'exit "$srv_rc"',
    ]
    return RunPlan(
        files,
        "\n".join(lines) + "\n",
        f"{companion.kind}+{cand.kind}",
        COMPILE_FAILED if compiles else None,
        marker,
        ubsan_fatal,
    )


def split_roles(
    cands: Sequence[Candidate],
) -> tuple[list[Candidate], Candidate | None, list[Candidate]]:
    """(candidates to run, the server started beside each, candidates left out with the reason)."""
    servers = [c for c in cands if c.role == "server"]
    others = [c for c in cands if c.role != "server"]
    if not servers or not others:
        return list(cands), None, []
    skipped = [
        replace(c, unsupported="only the first server block is started") for c in servers[1:]
    ]
    return others, servers[0], skipped
