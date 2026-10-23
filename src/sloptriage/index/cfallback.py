"""Brace-matching recovery of C/C++ function definitions.

tree-sitter parses C without running the preprocessor, so a function whose
signature or braces sit inside ``#if`` branches can come out as an ERROR node.
This pass blanks comments, literals and the non-first branches of conditionals,
then finds ``name(...) {`` at the start of a line and matches braces to get
the span. It only fills in functions tree-sitter missed or mis-spanned.
"""

from __future__ import annotations

import re

from sloptriage.index.defs import Definition

_KEYWORDS = frozenset(
    [
        "if",
        "while",
        "for",
        "switch",
        "return",
        "sizeof",
        "else",
        "do",
        "case",
        "defined",
        "__attribute__",
        "catch",
    ]
)
_DEF_RE = re.compile(
    r"^(?P<prefix>[A-Za-z_][\w\s\*\(\),]*?[\s\*]|)(?P<name>[A-Za-z_]\w*(?:::~?[A-Za-z_]\w*)*)"
    r"\s*\((?P<params>[^;{}]*?)\)\s*(?:const\s*)?(?:noexcept\s*)?(?:[A-Z_]{3,}(?:\([^)]*\))?\s*)?\{",
    re.M,
)


def _blank(text: str) -> str:
    """Replace comments and string/char literals with spaces, keeping newlines."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            for k in range(i + 1, j - 1):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def _strip_preprocessor(text: str) -> str:
    """Blank directive lines and every #else/#elif branch (keep the first branch)."""
    lines = text.split("\n")
    depth_skip: list[bool] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith("#"):
            directive = stripped[1:].lstrip().split(" ", 1)[0].split("(")[0]
            j = i
            while lines[j].rstrip().endswith("\\") and j + 1 < len(lines):
                j += 1
            if directive in ("if", "ifdef", "ifndef"):
                depth_skip.append(False)
            elif directive in ("else", "elif", "elifdef", "elifndef") and depth_skip:
                depth_skip[-1] = True
            elif directive == "endif" and depth_skip:
                depth_skip.pop()
            for k in range(i, j + 1):
                lines[k] = ""
            i = j + 1
            continue
        if any(depth_skip):
            lines[i] = ""
        i += 1
    return "\n".join(lines)


def functions(content: bytes) -> list[Definition]:
    text = content.decode("utf-8", "replace")
    clean = _strip_preprocessor(_blank(text))
    found: list[Definition] = []
    for m in _DEF_RE.finditer(clean):
        if clean[m.start()] in " \t\n":
            continue  # definitions start at column 0; indented matches are statements
        name = m.group("name")
        short = name.split("::")[-1].lstrip("~")
        if short in _KEYWORDS or (
            m.group("prefix").strip() == "" and m.start() > 0 and clean[m.start() - 1] != "\n"
        ):
            continue
        prefix = m.group("prefix")
        if re.search(r"[=;]", prefix) or "return" in prefix.split():
            continue
        brace = m.end() - 1
        end = _match_brace(clean, brace)
        if end is None:
            continue
        start_line = clean.count("\n", 0, m.start("name")) + 1
        # the definition starts where its declaration starts (return type may be on the previous line)
        line_start = clean.rfind("\n", 0, m.start()) + 1
        start_line = clean.count("\n", 0, line_start) + 1 if prefix else start_line
        end_line = clean.count("\n", 0, end) + 1
        kind = "method" if "::" in name else "function"
        found.append(Definition(short, kind, start_line, end_line, name))
    return found


def _match_brace(text: str, open_at: int) -> int | None:
    depth = 0
    for i in range(open_at, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def merge(ts_defs: list[Definition], content: bytes) -> list[Definition]:
    """Union of tree-sitter definitions and brace-matched functions.

    Both passes can be right at once: a function defined in two ``#if`` branches
    has two spans, and keeping both only makes span checks more lenient.
    """
    out = list(ts_defs)
    have = {(d.name, d.start, d.end) for d in ts_defs if d.kind in ("function", "method")}
    for d in functions(content):
        if any((d.name, d.start + k, d.end) in have for k in (-2, -1, 0, 1, 2)):
            continue
        out.append(d)
    return out
