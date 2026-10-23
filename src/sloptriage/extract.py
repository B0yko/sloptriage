"""Deterministic claim extraction from report text.

Every claim carries a character span into the report body, a kind and a
confidence. Only high-confidence claims can produce hard failures later.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace

from sloptriage.names import NameLists, load_names

KINDS = (
    "path",
    "symbol",
    "line",
    "version",
    "frame",
    "quote",
    "poc",
    "cve",
    "cwe",
    "sanitizer_claim",
)


@dataclass(frozen=True)
class Claim:
    kind: str
    value: str
    start: int
    end: int
    confidence: str  # "high" | "medium"
    source: str
    path: str | None = None
    line: int | None = None
    line_end: int | None = None
    column: int | None = None
    function: str | None = None
    ref: str | None = None
    repo: str | None = None
    frame_index: int | None = None
    trace: int | None = None
    module: str | None = None
    lang: str | None = None
    text: str | None = None
    poc_kind: str | None = None
    error_type: str | None = None

    def key(self) -> tuple[object, ...]:
        return (
            self.kind,
            self.value,
            self.path,
            self.line,
            self.line_end,
            self.function,
            self.trace,
            self.frame_index,
        )


@dataclass
class ExtractContext:
    """What the extractor knows about the project (all optional)."""

    project: str = ""
    aliases: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    binaries: tuple[str, ...] = ()
    repo_slug: str = ""  # "owner/repo" for permalinks
    defines: Callable[[str], bool] | None = None
    external: tuple[str, ...] = ()
    names: NameLists = field(default_factory=load_names)

    def project_names(self) -> list[str]:
        names = [self.project, *self.aliases]
        return [n for n in names if n]


@dataclass
class Extraction:
    claims: list[Claim]
    fences: list[Fence]
    poc_names: frozenset[str] = frozenset()

    def by_kind(self, kind: str) -> list[Claim]:
        return [c for c in self.claims if c.kind == kind]


@dataclass(frozen=True)
class Fence:
    start: int  # offset of the opening fence line
    end: int  # offset just after the closing fence line
    body_start: int
    body_end: int
    info: str
    body: str


# -- low-level helpers ------------------------------------------------------------
_FENCE_RE = re.compile(r"^(?P<indent>[ \t]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\n`]*)\n", re.M)
_INLINE_CODE_RE = re.compile(r"(?<!`)(`{1,2})(?!`)([^`\n]{1,200}?)(?<!`)\1(?!`)")
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_IDENT_RE = re.compile(rf"^{_IDENT}$")
_CODE_EXT = (
    "c|h|cc|cpp|cxx|hh|hpp|hxx|inl|py|pyi|pyx|js|mjs|cjs|jsx|ts|tsx|go|rs|java|kt|rb|php|cs|swift|m|mm|"
    "s|S|asm|pl|pm|sh|bash|lua|cmake|am|ac|in|mk|y|l|def|inc|xs|zig"
)
_PATH_CORE = rf"(?:[A-Za-z0-9_.+-]+/)*[A-Za-z0-9_.+-]+\.(?:{_CODE_EXT})"
_PATH_RE = re.compile(
    rf"(?<![\w/.:@-])(?P<path>(?:\.{{0,2}}/)?{_PATH_CORE})(?![\w/-])(?::(?P<line>\d{{1,6}})(?::(?P<col>\d{{1,4}}))?)?"
)
_SPECIAL_FILES = (
    "Makefile",
    "CMakeLists.txt",
    "configure.ac",
    "meson.build",
    "setup.py",
    "Cargo.toml",
    "go.mod",
)
_PERMALINK_RE = re.compile(
    r"https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/(?:blob|tree)/(?P<ref>[^/\s#?]+)/"
    r"(?P<path>[^\s#?)\]>\"'`]+)(?:\?[^\s#)]*)?(?:#L(?P<l1>\d+)(?:C\d+)?(?:-L(?P<l2>\d+)(?:C\d+)?)?)?"
)
_RAW_RE = re.compile(
    r"https?://raw\.githubusercontent\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/(?P<ref>[^/\s]+)/(?P<path>[^\s#?)\]>\"'`]+)"
)
_CVE_RE = re.compile(r"\bCVE-(\d{4})-(\d{4,7})\b", re.I)
_CWE_RE = re.compile(r"\bCWE-(\d{1,4})\b", re.I)
_PROSE_CALL_RE = re.compile(
    rf"(?<![\w.>:$])(?P<name>{_IDENT}(?:::{_IDENT})*)\((?P<args>[^()\n]{{0,80}})\)"
)
_CALL_RE = re.compile(
    rf"(?<![\w.>:$])(?P<name>{_IDENT}(?:::{_IDENT})*)\s?\((?P<args>[^()\n]{{0,80}})\)"
)
_LINE_OF_RE = re.compile(
    rf"\blines?\s+(?P<l1>\d{{1,6}})(?:\s*(?:-|–|to)\s*(?P<l2>\d{{1,6}}))?\s+(?:of|in|at)\s+`?(?P<path>{_PATH_CORE})`?",
    re.I,
)
_PATH_LINE_RE = re.compile(
    rf"`?(?P<path>{_PATH_CORE})`?,?\s+(?:at\s+|on\s+)?lines?\s+(?P<l1>\d{{1,6}})(?:\s*(?:-|–|to)\s*(?P<l2>\d{{1,6}}))?",
    re.I,
)
_FUNC_PHRASE_RES = [
    re.compile(
        rf"\b(?:function|method|macro|routine|callback)\s+`?(?P<name>{_IDENT})`?(?!\()", re.I
    ),
    re.compile(rf"\bthe\s+`?(?P<name>{_IDENT})`?\s+(?:function|method|macro|routine)\b", re.I),
    re.compile(rf"\b(?:struct|union|enum|typedef)\s+`?(?P<name>{_IDENT})`?", re.I),
]
_SHA_NEAR_RE = re.compile(
    r"\b(?:commit|revision|rev|sha|git)\s*[:#]?\s*`?(?P<sha>[0-9a-f]{7,40})\b", re.I
)
_TAG_LIKE_RE = re.compile(
    r"(?<![\w.-])(?P<tag>v\d+\.\d+(?:\.\d+)?(?:[-.](?:rc|beta|alpha)\.?\d*)?)\b"
)

# sanitizer and crash wording
_SAN_HEADER_RE = re.compile(
    r"(?:ERROR|WARNING|SUMMARY):\s+(?P<tool>AddressSanitizer|LeakSanitizer|MemorySanitizer|ThreadSanitizer|"
    r"UndefinedBehaviorSanitizer|HWAddressSanitizer)\s*:\s*(?P<type>[A-Za-z][\w-]*(?:\s[\w-]+){0,3})"
)
_UBSAN_RE = re.compile(
    rf"(?P<path>{_PATH_CORE}):(?P<line>\d+):(?P<col>\d+):\s+runtime error:\s+(?P<msg>[^\n]{{0,120}})"
)
_PROSE_ERROR_TYPES = [
    (
        re.compile(
            r"heap[- ]based buffer over(?:flow|read)|heap[- ]buffer[- ]over(?:flow|read)|heap overflow",
            re.I,
        ),
        "heap-buffer-overflow",
    ),
    (
        re.compile(
            r"stack[- ]based buffer overflow|stack[- ]buffer[- ]overflow|stack overflow", re.I
        ),
        "stack-buffer-overflow",
    ),
    (re.compile(r"global[- ]buffer[- ]overflow", re.I), "global-buffer-overflow"),
    (re.compile(r"use[- ]after[- ]free|\bUAF\b", re.I), "heap-use-after-free"),
    (re.compile(r"double[- ]free", re.I), "double-free"),
    (
        re.compile(r"null[- ]pointer dereference|NULL pointer dereference|null deref", re.I),
        "null-dereference",
    ),
    (
        re.compile(r"integer overflow|signed integer overflow|integer wrap", re.I),
        "integer-overflow",
    ),
    (re.compile(r"out[- ]of[- ]bounds (?:read|write|access)", re.I), "out-of-bounds"),
    (re.compile(r"buffer overflow|buffer overrun", re.I), "buffer-overflow"),
    (re.compile(r"memory leak", re.I), "memory-leak"),
    (re.compile(r"format string", re.I), "format-string"),
    (re.compile(r"data race", re.I), "data-race"),
]

# stack frames
_ASAN_FRAME_RE = re.compile(
    r"^[ \t>|]*#(?P<idx>\d{1,3})[ \t]+0x[0-9a-fA-F]+[ \t]+in[ \t]+(?P<func>[^\n]+?)[ \t]+"
    r"(?:(?P<file>[^\s()]+?):(?P<line>\d+)(?::(?P<col>\d+))?|\((?P<module>[^)\n]*)\))[ \t]*$",
    re.M,
)
_ASAN_FRAME_NOFILE_RE = re.compile(
    r"^[ \t>|]*#(?P<idx>\d{1,3})[ \t]+0x[0-9a-fA-F]+[ \t]+in[ \t]+(?P<func>[^\s(]+)(?:[ \t]+\((?P<module>[^)\n]*)\))?[ \t]*$",
    re.M,
)
_GDB_FRAME_RE = re.compile(
    r"^[ \t>|]*#(?P<idx>\d{1,3})[ \t]+(?:0x[0-9a-fA-F]+[ \t]+in[ \t]+)?(?P<func>[A-Za-z_][\w:~<>]*)[ \t]*"
    r"\((?P<args>[^)]{0,600}?)\)[ \t\n]+(?:at[ \t]+(?P<file>[^\s:]+):(?P<line>\d+)|from[ \t]+(?P<module>\S+))[ \t]*$",
    re.M,
)
_LLDB_FRAME_RE = re.compile(
    r"^[ \t*>|]*frame\s+#(?P<idx>\d{1,3}):\s+0x[0-9a-fA-F]+\s+(?P<module>[^`\s]+)`(?P<func>[^\s(]+)"
    r"(?:\([^\n]*?\))?(?:\s+\+\s+\d+)?(?:\s+at\s+(?P<file>[^\s:]+):(?P<line>\d+)(?::(?P<col>\d+))?)?",
    re.M,
)
_VALGRIND_FRAME_RE = re.compile(
    r"^==\d+==\s+(?:at|by)\s+0x[0-9A-Fa-f]+:\s+(?P<func>[^\s(]+)(?:\s+\((?:(?P<file>[^\s:()]+):(?P<line>\d+)|in\s+(?P<module>[^)]+))\))?",
    re.M,
)
_PY_FRAME_RE = re.compile(
    r'^[ \t]*File\s+"(?P<file>[^"]+)",\s+line\s+(?P<line>\d+),\s+in\s+(?P<func>[\w<>.]+)', re.M
)
_GO_FRAME_RE = re.compile(
    r"^(?P<func>[\w./*()-]+?)\((?:[^\n]*)\)\n\t(?P<file>\S+?\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-f]+)?",
    re.M,
)
_RUST_FRAME_RE = re.compile(
    r"^\s*(?P<idx>\d{1,3}):\s+(?:0x[0-9a-f]+\s+-\s+)?(?P<func>[\w:<>{}#]+?)(?:::h[0-9a-f]{16})?\n\s+at\s+(?P<file>[^\s:]+):(?P<line>\d+):(?P<col>\d+)",
    re.M,
)
_RUST_PANIC_RE = re.compile(r"panicked at\s+'?(?P<file>[^\s:']+\.rs):(?P<line>\d+):(?P<col>\d+)")

_POC_WORDS = re.compile(
    r"\b(?:poc|proof[- ]of[- ]concept|reproduc\w*|repro\b|exploit\w*|steps? to reproduce|to trigger|trigger(?:s|ing)?|demonstrat\w*|"
    r"compile (?:and run|with)|run (?:the following|this)|test case|testcase|crash(?:es|ing)? input|payload)\b",
    re.I,
)
_QUOTE_WORDS = re.compile(
    r"\b(?:vulnerable code|source code|code snippet|snippet|the code (?:in|from|at)|code from|code in|"
    r"implementation|relevant code|function body|as (?:seen|shown) in|excerpt|located in|defined in|from file|in file|"
    r"code at|following code|the code)\b",
    re.I,
)
_INPUT_WORDS = re.compile(
    r"\b(?:save (?:this|it) as|input file|test file|crash file|write (?:this|it) to|file contents?|payload file)\b",
    re.I,
)
_BASE64_BODY_RE = re.compile(r"^[A-Za-z0-9+/=\s]{16,}$")
_HEX_BODY_RE = re.compile(r"^(?:[0-9a-fA-F]{2}[\s:]*){8,}$")
_SHELL_START_RE = re.compile(r"^\s*(?:\$\s+|#\s+|sudo\s+)?(?P<cmd>[\w./-]+)(?:\s|$)")


def _mask_ranges(text: str, ranges: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in ranges:
        for i in range(start, min(end, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def find_fences(text: str) -> list[Fence]:
    fences: list[Fence] = []
    pos = 0
    while True:
        m = _FENCE_RE.search(text, pos)
        if not m:
            break
        marker = m.group("fence")
        closing = re.compile(rf"^[ \t]{{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$", re.M)
        c = closing.search(text, m.end())
        body_start = m.end()
        if c is None:
            body_end = len(text)
            end = len(text)
        else:
            body_end = c.start()
            end = min(len(text), c.end() + 1)
        fences.append(
            Fence(
                m.start(),
                end,
                body_start,
                body_end,
                m.group("info").strip(),
                text[body_start:body_end],
            )
        )
        pos = end
    return fences


def _context_before(text: str, pos: int, width: int = 300) -> str:
    start = max(0, pos - width)
    chunk = text[start:pos]
    # stop at the previous fence so a code block's own text does not label the next one
    cut = max(chunk.rfind("```"), chunk.rfind("~~~"))
    return chunk[cut + 3 :] if cut >= 0 else chunk


def _guess_lang(info: str, body: str) -> str:
    tag = info.split()[0].lower() if info.split() else ""
    aliases = {
        "c": "c",
        "h": "c",
        "cpp": "cpp",
        "c++": "cpp",
        "cc": "cpp",
        "cxx": "cpp",
        "python": "python",
        "py": "python",
        "python3": "python",
        "sh": "shell",
        "bash": "shell",
        "shell": "shell",
        "console": "shell",
        "zsh": "shell",
        "shell-session": "shell",
        "js": "javascript",
        "javascript": "javascript",
        "ts": "typescript",
        "typescript": "typescript",
        "go": "go",
        "golang": "go",
        "rust": "rust",
        "rs": "rust",
        "base64": "base64",
        "hex": "hex",
        "text": "text",
        "txt": "text",
        "plaintext": "text",
        "diff": "diff",
        "patch": "diff",
        "http": "http",
        "html": "html",
        "xml": "xml",
        "json": "json",
        "yaml": "yaml",
    }
    if tag in aliases:
        return aliases[tag]
    stripped = body.strip()
    if not stripped:
        return "text"
    if re.search(
        r"^\s*(?:#include\s*[<\"]|(?:static\s+)?(?:int|void|char|size_t|struct\s+\w+\s*\*?)\s+\**\w+\s*\()",
        stripped,
        re.M,
    ):
        return (
            "cpp"
            if re.search(r"std::|#include\s*<(?:iostream|string|vector)>|\bclass\s+\w+", stripped)
            else "c"
        )
    if re.search(r"^(?:diff --git|@@ -\d+,\d+ \+\d+,\d+ @@|--- a/)", stripped, re.M):
        return "diff"
    if re.search(
        r"^\s*(?:def |class \w+[:(]|import \w+|from \w+(?:\.\w+)* import )", stripped, re.M
    ):
        return "python"
    if stripped.startswith("#!") or re.match(r"^\s*\$\s", stripped):
        return "shell"
    if re.search(r"^\s*package \w+|func \w+\(", stripped, re.M):
        return "go"
    if re.search(r"\bfn \w+\(|\blet mut\b", stripped):
        return "rust"
    if (
        _BASE64_BODY_RE.match(stripped)
        and len(stripped.split()) <= 200
        and not re.search(r"\s\w+\s\w+\s", stripped)
    ):
        return "base64"
    if re.search(r";\s*$", stripped, re.M) and re.search(r"[{}]|->|\w+\(", stripped):
        return "c"
    return "text"


# -- the extractor ----------------------------------------------------------------
class _Builder:
    def __init__(self, text: str, ctx: ExtractContext) -> None:
        self.text = text
        self.ctx = ctx
        self.claims: list[Claim] = []
        self._seen: set[tuple[object, ...]] = set()
        self.poc_defined: set[str] = set()
        self._trace = 0

    def add(self, claim: Claim) -> None:
        key = claim.key()
        if key in self._seen:
            return
        self._seen.add(key)
        self.claims.append(claim)

    def next_trace(self) -> int:
        self._trace += 1
        return self._trace


def extract(text: str, ctx: ExtractContext | None = None) -> Extraction:
    ctx = ctx or ExtractContext()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    b = _Builder(text, ctx)
    fences = find_fences(text)
    trace_ranges = _extract_frames(b, text)
    fence_kinds = _classify_fences(b, text, fences, trace_ranges)
    code_ranges = [(f.start, f.end) for f in fences] + trace_ranges
    prose = _mask_ranges(text, code_ranges)
    _extract_links(b, text)
    _extract_inline_code(b, prose)
    _extract_prose(b, prose)
    _extract_versions(b, prose)
    _extract_ids(b, prose)
    _extract_sanitizer(b, text, prose)
    # text-only fences (shell output, logs) may still cite paths like lib/x.c:123
    for fence, kind in zip(fences, fence_kinds, strict=True):
        if kind == "other":
            _extract_paths_in(
                b, text, fence.body_start, fence.body_end, confidence="medium", source="fence"
            )
    claims = _drop_poc_names(b)
    claims.sort(key=lambda c: (c.start, c.kind))
    return Extraction(claims, fences, frozenset(b.poc_defined))


def _drop_poc_names(b: _Builder) -> list[Claim]:
    if not b.poc_defined:
        return b.claims
    out = []
    for c in b.claims:
        if c.kind == "symbol" and c.value in b.poc_defined and c.source != "frame":
            continue
        out.append(c)
    return out


# frames ---------------------------------------------------------------------------
def _frames_from(
    regex: re.Pattern[str], text: str, source: str
) -> list[tuple[int, int, dict[str, str | None]]]:
    return [(m.start(), m.end(), m.groupdict()) for m in regex.finditer(text)]


def _clean_func(func: str) -> str:
    func = func.strip()
    func = re.sub(r"\(.*\)$", "", func)  # C++ signatures in symbolized frames
    func = func.split(" ")[-1]
    if "::" in func:
        func = func.split("::")[-1] or func
    return func.strip("*&")


def _extract_frames(b: _Builder, text: str) -> list[tuple[int, int]]:
    hits: list[tuple[int, int, dict[str, str | None], str]] = []
    taken: list[tuple[int, int]] = []

    def overlaps(s: int, e: int) -> bool:
        return any(s < te and ts < e for ts, te in taken)

    for regex, source in (
        (_GDB_FRAME_RE, "frame:gdb"),
        (_ASAN_FRAME_RE, "frame:sanitizer"),
        (_ASAN_FRAME_NOFILE_RE, "frame:sanitizer"),
        (_LLDB_FRAME_RE, "frame:lldb"),
        (_VALGRIND_FRAME_RE, "frame:valgrind"),
        (_PY_FRAME_RE, "frame:python"),
        (_GO_FRAME_RE, "frame:go"),
        (_RUST_FRAME_RE, "frame:rust"),
    ):
        for s, e, groups in _frames_from(regex, text, source):
            if overlaps(s, e):
                continue
            taken.append((s, e))
            hits.append((s, e, groups, source))
    hits.sort(key=lambda h: h[0])
    ranges: list[tuple[int, int]] = []
    trace = 0
    last_end = -10_000
    last_idx = -1
    counter = 0
    for s, e, g, source in hits:
        gap = text[last_end:s] if last_end >= 0 else ""
        idx_text = g.get("idx")
        idx = int(idx_text) if idx_text is not None else None
        new_trace = (
            last_end < 0
            or gap.count("\n") > 3
            or (idx is not None and idx <= last_idx and idx == 0)
        )
        if new_trace:
            trace = b.next_trace()
            counter = 0
        if idx is None:
            idx = counter
        counter += 1
        last_idx = idx
        last_end = e
        ranges.append((s, e))
        func = _clean_func(g.get("func") or "")
        file = g.get("file")
        line_text, col_text = g.get("line"), g.get("col")
        line = int(line_text) if line_text else None
        col = int(col_text) if col_text else None
        if source == "frame:python" and func.startswith("<"):
            func = ""
        has_loc = bool(file and line)
        b.add(
            Claim(
                kind="frame",
                value=func or (file or ""),
                start=s,
                end=e,
                confidence="high" if has_loc and func else "medium",
                source=source,
                path=file,
                line=line,
                column=col,
                function=func or None,
                frame_index=idx,
                trace=trace,
                module=g.get("module"),
            )
        )
    for m in _RUST_PANIC_RE.finditer(text):
        b.add(
            Claim(
                "line",
                m.group("file"),
                m.start(),
                m.end(),
                "high",
                "panic",
                path=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col")),
            )
        )
    for m in _UBSAN_RE.finditer(text):
        b.add(
            Claim(
                "line",
                m.group("path"),
                m.start(),
                m.end(),
                "high",
                "ubsan",
                path=m.group("path"),
                line=int(m.group("line")),
                column=int(m.group("col")),
            )
        )
        ranges.append((m.start(), m.end()))
    return _merge_ranges(ranges)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


# fenced blocks -----------------------------------------------------------------
_C_DEF_NAMES_RE = re.compile(
    rf"^\s*(?:static\s+|const\s+|unsigned\s+|signed\s+|struct\s+|enum\s+)*[A-Za-z_][\w]*[\s\*]+\**(?P<name>{_IDENT})\s*(?:\(|\[|=|;)",
    re.M,
)
_PY_DEF_NAMES_RE = re.compile(
    rf"^\s*(?:def|class)\s+(?P<name>{_IDENT})|^\s*(?P<var>{_IDENT})\s*=", re.M
)
_SHELL_VAR_RE = re.compile(rf"^\s*(?:export\s+)?(?P<name>{_IDENT})=", re.M)
_DEFINE_RE = re.compile(rf"^\s*#\s*define\s+(?P<name>{_IDENT})", re.M)


def _names_defined_in(code: str, lang: str) -> set[str]:
    names: set[str] = set()
    if lang in ("c", "cpp"):
        names.update(m.group("name") for m in _C_DEF_NAMES_RE.finditer(code))
        names.update(m.group("name") for m in _DEFINE_RE.finditer(code))
    elif lang == "python":
        for m in _PY_DEF_NAMES_RE.finditer(code):
            names.add(m.group("name") or m.group("var"))
    names.update(m.group("name") for m in _SHELL_VAR_RE.finditer(code))
    return {n for n in names if n}


def _identifiers_in(code: str) -> set[str]:
    return set(re.findall(rf"\b{_IDENT}\b", code))


def _classify_fences(
    b: _Builder, text: str, fences: list[Fence], trace_ranges: list[tuple[int, int]]
) -> list[str]:
    kinds: list[str] = []
    project_langs = set(b.ctx.languages)
    binaries = {x.lower() for x in (*b.ctx.binaries, *b.ctx.project_names())}
    for f in fences:
        body = f.body
        inside_trace = sum(
            min(f.body_end, e) - max(f.body_start, s)
            for s, e in trace_ranges
            if s < f.body_end and e > f.body_start
        )
        if body.strip() and inside_trace > 0.3 * len(body.strip()):
            kinds.append("trace")
            continue
        lang = _guess_lang(f.info, body)
        before = _context_before(text, f.start)
        info_l = f.info.lower()
        poc_kind = _poc_kind(body, lang, before, info_l, binaries)
        if poc_kind:
            kinds.append("poc")
            b.add(
                Claim(
                    "poc",
                    poc_kind,
                    f.start,
                    f.end,
                    "high",
                    "fence",
                    lang=lang,
                    text=body,
                    poc_kind=poc_kind,
                )
            )
            b.poc_defined.update(_names_defined_in(body, lang))
            continue
        quote_conf = (
            _quote_confidence(b, body, lang, before, project_langs)
            if lang in ("c", "cpp", "python", "javascript", "typescript", "go", "rust")
            else None
        )
        if quote_conf:
            kinds.append("quote")
            named = _named_path(_last_paragraph(before), b.ctx.names)
            b.add(
                Claim(
                    "quote",
                    named or "",
                    f.start,
                    f.end,
                    quote_conf,
                    "fence",
                    path=named,
                    lang=lang,
                    text=body,
                )
            )
            continue
        if lang == "diff":
            kinds.append("diff")
            continue
        kinds.append("other")
    return kinds


def _poc_kind(body: str, lang: str, before: str, info: str, binaries: set[str]) -> str | None:
    stripped = body.strip()
    if not stripped:
        return None
    labelled = bool(_POC_WORDS.search(before[-200:])) or bool(_POC_WORDS.search(info))
    if lang in ("c", "cpp") and re.search(
        r"\bint\s+main\s*\(|\bvoid\s+main\s*\(|^\s*main\s*\(", stripped, re.M
    ):
        return lang
    if stripped.startswith("#!"):
        first = stripped.splitlines()[0]
        if "python" in first:
            return "python"
        return "shell"
    if lang == "python" and (
        labelled or re.search(r"^if __name__ == ['\"]__main__['\"]", stripped, re.M)
    ):
        return "python"
    is_data = lang in ("base64", "hex") or (_HEX_BODY_RE.match(stripped) and len(stripped) > 32)
    if is_data and (_INPUT_WORDS.search(before[-250:]) or labelled):
        return "input"
    if lang in ("shell", "text", "c", "http"):
        cmds = []
        for line in stripped.splitlines()[:30]:
            m = _SHELL_START_RE.match(line)
            if m:
                cmds.append(m.group("cmd").rsplit("/", 1)[-1].lower())
        invokes_project = any(c in binaries for c in cmds)
        if invokes_project and (labelled or lang == "shell" or stripped.lstrip().startswith("$")):
            return "shell"
    if labelled and lang in ("c", "cpp", "python", "shell"):
        return lang
    return None


def _named_path(before: str, names: NameLists | None = None) -> str | None:
    tail = before[-300:]
    links = list(_PERMALINK_RE.finditer(tail))
    plain = _mask_ranges(tail, [(m.start(), m.end()) for m in re.finditer(r"https?://\S+", tail)])
    found = list(_PATH_RE.finditer(plain))
    last_link = links[-1] if links else None
    last_path = found[-1] if found else None
    if last_link and (last_path is None or last_link.start() > last_path.start()):
        return last_link.group("path")
    if last_path:
        path = last_path.group("path").lstrip("./").lstrip("/")
        return path if _plausible_path(path, names) else None
    return None


_FIX_WORDS = re.compile(
    r"\b(?:fix|fixed|patch|patched|suggest\w*|propos\w*|recommend\w*|mitigat\w*|remediat\w*|should (?:be|read|look)|"
    r"instead|change (?:it |this )?to|replace\w* (?:with|by)|correct(?:ed)? (?:code|version)|after the change|workaround)\b",
    re.I,
)


def _last_paragraph(before: str) -> str:
    tail = before[-400:]
    cut = tail.rstrip().rfind("\n\n")
    return tail[cut + 2 :] if cut >= 0 else tail


def _quote_confidence(
    b: _Builder, body: str, lang: str, before: str, project_langs: set[str]
) -> str | None:
    """'high' when the text right before the block presents it as project source."""
    if re.search(r"\bint\s+main\s*\(", body):
        return None
    para = _last_paragraph(before)
    if _FIX_WORDS.search(para):
        return None  # a proposed change, not a quotation of the project
    lang_ok = (
        not project_langs
        or lang in project_langs
        or (lang in ("c", "cpp") and bool(project_langs & {"c", "cpp"}))
    )
    if lang_ok and _named_path(para) and (_QUOTE_WORDS.search(para) or para.rstrip().endswith(":")):
        return "high"
    if _QUOTE_WORDS.search(para) and lang_ok and _defined_identifier_count(b, body) >= 1:
        return "high"
    if (
        b.ctx.defines is not None
        and lang_ok
        and _defined_identifier_count(b, body) >= 2
        and len(body.strip().splitlines()) >= 2
    ):
        return "medium"
    return None


def _defined_identifier_count(b: _Builder, body: str) -> int:
    if b.ctx.defines is None:
        return 0
    names = b.ctx.names
    count = 0
    for ident in _identifiers_in(body):
        if len(ident) < 4 or names.is_common(ident):
            continue
        if b.ctx.defines(ident):
            count += 1
            if count >= 2:
                break
    return count


# links ---------------------------------------------------------------------------
def _extract_links(b: _Builder, text: str) -> None:
    for regex in (_PERMALINK_RE, _RAW_RE):
        for m in regex.finditer(text):
            owner, repo, ref, path = (
                m.group("owner"),
                m.group("repo"),
                m.group("ref"),
                m.group("path"),
            )
            path = path.rstrip(".,;:")
            slug = f"{owner}/{repo}".lower()
            b.add(
                Claim(
                    "path",
                    path,
                    m.start(),
                    m.end(),
                    "high",
                    "permalink",
                    path=path,
                    ref=ref,
                    repo=slug,
                )
            )
            l1 = m.groupdict().get("l1")
            if l1:
                l2 = m.groupdict().get("l2")
                b.add(
                    Claim(
                        "line",
                        path,
                        m.start(),
                        m.end(),
                        "high",
                        "permalink",
                        path=path,
                        line=int(l1),
                        line_end=int(l2) if l2 else None,
                        ref=ref,
                        repo=slug,
                    )
                )


# inline code ---------------------------------------------------------------------
def _symbol_confidence(name: str, has_parens: bool, names: NameLists) -> str | None:
    if names.is_ignored(name):
        return None
    if len(name) < 3:
        return None
    distinctive = (
        ("_" in name.strip("_"))
        or bool(re.search(r"[a-z][A-Z]", name))
        or (name.isupper() and len(name) >= 4)
    )
    if has_parens:
        return "high" if (distinctive or len(name) >= 5) and not names.is_common(name) else "medium"
    # a bare identifier is high only in the snake_case / MACRO_CASE shapes C projects use;
    # bare camelCase is as often a reporter's own variable name as a project symbol
    if ("_" in name.strip("_") or (name.isupper() and len(name) >= 6)) and not names.is_common(
        name
    ):
        return "high"
    return "medium"


def _extract_inline_code(b: _Builder, prose: str) -> None:
    names = b.ctx.names
    for m in _INLINE_CODE_RE.finditer(prose):
        content = m.group(2).strip()
        start, end = m.start(), m.end()
        if not content:
            continue
        path_m = _PATH_RE.fullmatch(content) or _PATH_RE.match(content)
        if path_m and path_m.end() == len(content) and ("/" in content or "." in content):
            _add_path_match(
                b,
                path_m,
                start,
                end,
                "high" if "/" in path_m.group("path") else "medium",
                "backtick",
            )
            continue
        if content in _SPECIAL_FILES:
            b.add(Claim("path", content, start, end, "medium", "backtick", path=content))
            continue
        call = re.fullmatch(rf"(?P<name>{_IDENT}(?:::{_IDENT})*)\s?\((?P<args>.*)\)\s*;?", content)
        if call:
            name = call.group("name").split("::")[-1]
            conf = _symbol_confidence(name, True, names)
            if conf:
                b.add(Claim("symbol", name, start, end, conf, "backtick-call"))
            continue
        if _IDENT_RE.match(content):
            conf = _symbol_confidence(content, False, names)
            if conf:
                b.add(Claim("symbol", content, start, end, conf, "backtick"))
            continue
        member = re.fullmatch(rf"(?:{_IDENT})(?:(?:->|\.){_IDENT})+", content)
        if member:
            continue  # struct member access: fields are not top-level definitions
        # code fragments: pick out calls inside them
        for c in _CALL_RE.finditer(content):
            name = c.group("name").split("::")[-1]
            conf = _symbol_confidence(name, True, names)
            if conf:
                b.add(Claim("symbol", name, start, end, "medium", "backtick-fragment"))


def _add_path_match(
    b: _Builder, m: re.Match[str], start: int, end: int, conf: str, source: str
) -> None:
    path = m.group("path")
    if path.startswith("./"):
        path = path[2:]
    if not _plausible_path(path, b.ctx.names):
        return
    b.add(Claim("path", path, start, end, conf, source, path=path))
    if m.group("line"):
        col = m.group("col")
        b.add(
            Claim(
                "line",
                path,
                start,
                end,
                conf,
                source,
                path=path,
                line=int(m.group("line")),
                column=int(col) if col else None,
            )
        )


def _plausible_path(path: str, names: NameLists | None = None) -> bool:
    low = path.lower()
    if names is not None and "/" not in low and names.is_common(low):
        return False
    if re.match(r"^(?:\d+\.)+\d+", low):  # version numbers like 8.4.0.c
        return False
    if low.startswith(("http:", "https:", "www.")):
        return False
    base = low.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0]
    return bool(stem) and not stem.isdigit() and base not in ("e.g", "i.e")


# prose ---------------------------------------------------------------------------
def _extract_paths_in(
    b: _Builder, text: str, lo: int, hi: int, *, confidence: str, source: str
) -> None:
    for m in _PATH_RE.finditer(text, lo, hi):
        path = m.group("path")
        conf = confidence if "/" in path else "medium"
        _add_path_match(b, m, m.start(), m.end(), conf, source)


_FUNC_AT_RE = re.compile(
    rf"\b(?:in|function|func|method)\s+`?(?P<func>{_IDENT})(?:\(\))?`?\s*(?:\(|,)?\s*(?:at|in|on)\s+`?(?P<path>{_PATH_CORE}):(?P<line>\d{{1,6}})",
    re.I,
)
_AT_FUNC_RE = re.compile(
    rf"`?(?P<path>{_PATH_CORE}):(?P<line>\d{{1,6}})`?\s*(?:\(|,)?\s*(?:in|inside)\s+(?:(?:the\s+)?function\s+)?`?(?P<func>{_IDENT})(?:\(\))?`?",
    re.I,
)
_FUNC_LINES_RE = re.compile(
    rf"^\W*(?:function|method)\W*:?\s+(?:[\w\s\*]*?[\s\*])?`?(?P<func>{_IDENT})`?\s*(?:\([^)\n]*\))?\s*"
    rf"[\(\[,]?\s*(?:lines?|L)\s*(?P<l1>\d{{1,6}})(?:\s*(?:-|–|to)\s*(?P<l2>\d{{1,6}}))?",
    re.I | re.M,
)
_LINES_LIST_RE = re.compile(
    r"\b(?:lines?|L)\s*:?\s*(?P<list>\d{1,6}(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*|\s*(?:-|–)\s*|\s+to\s+)\d{1,6}){0,8})\b",
    re.I,
)


def _paragraphs(text: str) -> list[tuple[int, int]]:
    out = []
    pos = 0
    for m in re.finditer(r"\n\s*\n", text):
        out.append((pos, m.start()))
        pos = m.end()
    out.append((pos, len(text)))
    return out


def _extract_function_lines(b: _Builder, prose: str) -> None:
    """'in X at file:line', 'file:line in X' and 'Function: X (lines a-b)' near one file."""
    for regex in (_FUNC_AT_RE, _AT_FUNC_RE):
        for m in regex.finditer(prose):
            func = m.group("func")
            if b.ctx.names.is_ignored(func):
                continue
            b.add(
                Claim(
                    "frame",
                    func,
                    m.start(),
                    m.end(),
                    "high",
                    "prose",
                    path=m.group("path"),
                    line=int(m.group("line")),
                    function=func,
                )
            )
    current: str | None = None
    since = 0
    for start, end in _paragraphs(prose):
        para = prose[start:end]
        paths = {
            pm.group("path").lstrip("./")
            for pm in _PATH_RE.finditer(para)
            if "/" in pm.group("path")
        }
        if len(paths) == 1:
            current, since = next(iter(paths)), 0
        elif len(paths) > 1 or para.lstrip().startswith("#"):
            current = None
        else:
            since += 1
            if since > 2:
                current = None
        if current is None:
            continue
        path = current
        for m in _FUNC_LINES_RE.finditer(para):
            func = m.group("func")
            if b.ctx.names.is_ignored(func):
                continue
            l1 = int(m.group("l1"))
            b.add(
                Claim(
                    "frame",
                    func,
                    start + m.start(),
                    start + m.end(),
                    "high",
                    "prose",
                    path=path,
                    line=l1,
                    function=func,
                )
            )
        for m in _LINES_LIST_RE.finditer(para):
            numbers = [int(x) for x in re.findall(r"\d+", m.group("list"))]
            if re.search(r"-|–|\bto\b", m.group("list")):
                b.add(
                    Claim(
                        "line",
                        path,
                        start + m.start(),
                        start + m.end(),
                        "high",
                        "prose-paragraph",
                        path=path,
                        line=numbers[0],
                        line_end=numbers[1] if len(numbers) > 1 else None,
                    )
                )
                continue
            for n in numbers:
                b.add(
                    Claim(
                        "line",
                        path,
                        start + m.start(),
                        start + m.end(),
                        "high",
                        "prose-paragraph",
                        path=path,
                        line=n,
                    )
                )


def _extract_prose(b: _Builder, prose: str) -> None:
    _extract_function_lines(b, prose)
    names = b.ctx.names
    no_code = _mask_ranges(prose, [(m.start(), m.end()) for m in _INLINE_CODE_RE.finditer(prose)])
    no_urls = _mask_ranges(
        no_code, [(m.start(), m.end()) for m in re.finditer(r"https?://\S+", no_code)]
    )
    _extract_paths_in(b, no_urls, 0, len(no_urls), confidence="high", source="prose")
    for m in _LINE_OF_RE.finditer(prose):
        l2 = m.group("l2")
        b.add(
            Claim(
                "line",
                m.group("path"),
                m.start(),
                m.end(),
                "high",
                "prose",
                path=m.group("path"),
                line=int(m.group("l1")),
                line_end=int(l2) if l2 else None,
            )
        )
    for m in _PATH_LINE_RE.finditer(prose):
        l2 = m.group("l2")
        b.add(
            Claim(
                "line",
                m.group("path"),
                m.start(),
                m.end(),
                "high",
                "prose",
                path=m.group("path"),
                line=int(m.group("l1")),
                line_end=int(l2) if l2 else None,
            )
        )
    for m in _PROSE_CALL_RE.finditer(no_urls):
        name = m.group("name").split("::")[-1]
        conf = _symbol_confidence(name, True, names)
        if conf is None:
            continue
        # a bare call in prose is high only when its shape is unmistakably an identifier
        if conf == "high" and not ("_" in name.strip("_") or re.search(r"[a-z][A-Z]", name)):
            conf = "medium"
        b.add(Claim("symbol", name, m.start(), m.end(), conf, "prose-call"))
    for regex in _FUNC_PHRASE_RES:
        for m in regex.finditer(no_urls):
            name = m.group("name")
            conf = _symbol_confidence(name, False, names)
            if conf is None:
                continue
            b.add(Claim("symbol", name, m.start("name"), m.end("name"), "medium", "prose-phrase"))


# versions --------------------------------------------------------------------------
def _version_regexes(ctx: ExtractContext) -> list[re.Pattern[str]]:
    names = sorted({re.escape(n) for n in ctx.project_names()}, key=len, reverse=True)
    if not names:
        return []
    alt = "|".join(names)
    num = r"(?P<version>\d+\.\d+(?:\.\d+){0,2}(?:-(?:rc|beta|alpha|DEV|dev)\.?\d*)?)"
    return [
        re.compile(
            rf"(?<![\w-])(?:{alt})(?:[ /_-]?(?:version|ver\.?|v)?\s?:?\s?){num}(?![\w.]*\d)", re.I
        ),
        re.compile(
            rf"(?<![\w-])(?:{alt})\b[^\n.]{{0,40}}?\bversions?\s*:?\s*v?{num}(?![\w.]*\d)", re.I
        ),
        re.compile(rf"\bversions?\s*:?\s*v?{num}\s+(?:of\s+)?(?:{alt})\b", re.I),
    ]


def _extract_versions(b: _Builder, prose: str) -> None:
    ctx = b.ctx
    for regex in _version_regexes(ctx):
        for m in regex.finditer(prose):
            b.add(
                Claim(
                    "version",
                    m.group("version"),
                    m.start("version"),
                    m.end("version"),
                    "high",
                    "prose",
                )
            )
    if ctx.project:
        tag_re = re.compile(
            rf"(?<![\w-]){re.escape(ctx.project)}-(?P<maj>\d+)_(?P<min>\d+)_(?P<pat>\d+)\b", re.I
        )
        for m in tag_re.finditer(prose):
            v = f"{m.group('maj')}.{m.group('min')}.{m.group('pat')}"
            b.add(Claim("version", v, m.start(), m.end(), "high", "tag", ref=m.group(0)))
    for m in _TAG_LIKE_RE.finditer(prose):
        b.add(
            Claim(
                "version",
                m.group("tag").lstrip("v"),
                m.start(),
                m.end(),
                "medium",
                "tag",
                ref=m.group("tag"),
            )
        )
    for m in _SHA_NEAR_RE.finditer(prose):
        sha = m.group("sha")
        if re.search(r"[a-f]", sha) and re.search(r"\d", sha):
            b.add(Claim("version", sha, m.start("sha"), m.end("sha"), "medium", "sha", ref=sha))


def _extract_ids(b: _Builder, prose: str) -> None:
    for m in _CVE_RE.finditer(prose):
        b.add(Claim("cve", f"CVE-{m.group(1)}-{m.group(2)}", m.start(), m.end(), "high", "prose"))
    for m in _CWE_RE.finditer(prose):
        b.add(Claim("cwe", f"CWE-{m.group(1)}", m.start(), m.end(), "high", "prose"))


def _extract_sanitizer(b: _Builder, text: str, prose: str) -> None:
    for m in _SAN_HEADER_RE.finditer(text):
        etype = m.group("type").split()[0].lower().rstrip(":")
        if m.group("tool") == "ThreadSanitizer" and "race" in m.group("type"):
            etype = "data-race"
        if m.group("tool") == "LeakSanitizer":
            etype = "memory-leak"
        b.add(
            Claim(
                "sanitizer_claim",
                etype,
                m.start(),
                m.end(),
                "high",
                m.group("tool"),
                error_type=etype,
            )
        )
    for m in _UBSAN_RE.finditer(text):
        msg = m.group("msg").lower()
        etype = "integer-overflow" if "overflow" in msg else "undefined-behavior"
        b.add(
            Claim(
                "sanitizer_claim",
                etype,
                m.start(),
                m.end(),
                "high",
                "UndefinedBehaviorSanitizer",
                error_type=etype,
            )
        )
    for regex, etype in _PROSE_ERROR_TYPES:
        hit = regex.search(prose)
        if hit:
            m = hit
            b.add(
                Claim(
                    "sanitizer_claim",
                    etype,
                    m.start(),
                    m.end(),
                    "medium",
                    "prose",
                    error_type=etype,
                )
            )


def iter_symbols(claims: Iterable[Claim]) -> Iterator[Claim]:
    return (c for c in claims if c.kind == "symbol")


def with_confidence(claim: Claim, confidence: str) -> Claim:
    return replace(claim, confidence=confidence)
