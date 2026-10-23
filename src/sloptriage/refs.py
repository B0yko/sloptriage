"""Check each extracted claim against the code at the resolved version.

Every finding has a status, a severity and evidence (a permalink to the exact
lines at that commit). Severities: ``ok`` (verified), ``hard`` (a high-confidence
citation that does not exist), ``soft`` (worth a look, never decisive) and
``neutral`` (not checkable or not about this project).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sloptriage.extract import Claim
from sloptriage.index import Index, IndexSet
from sloptriage.index.defs import FUNCTION_KINDS
from sloptriage.names import NameLists

HARD_STATUSES = frozenset({"not_found", "out_of_range", "outside_function", "function_not_in_file"})
OK_STATUSES = frozenset(
    {"found", "defined", "referenced_only", "in_range", "consistent", "exact", "approximate"}
)
# path prefixes that mark a cited file as outside the project (never opened)
SYSTEM_PREFIXES = (
    "/usr/",
    "/lib/x86_64",
    "/lib64/",
    "/etc/",
    "/proc/",
    "/dev/",
    "/sys/",
    "/tmp/",  # noqa: S108
    "/var/",
    "/opt/homebrew/",
    "/System/",
    "/Library/",
    "/Applications/",
    "C:\\",
    "c:\\",
)
QUOTE_SIMILARITY = 0.85
_REPORTER_FILE_RE = re.compile(
    r"(?:^|/)(?:poc|exploit|repro|reproducer|reproduce|crash|harness|fuzz(?:er)?|payload|trigger|testcase|"
    r"test_?poc|my_?test|demo|attack|evil|malicious)[\w.-]*\.\w+$",
    re.I,
)


_RUNTIME_RE = re.compile(
    r"sanitizer_common|compiler-rt|libsanitizer|/asan/|/ubsan/|/msan/|/tsan/|/lsan/|libfuzzer|FuzzerLoop|"
    r"/glibc|/libc/|/sysdeps/|/csu/|/nptl/|/malloc/|\.inc$",
    re.I,
)
_RUNTIME_FUNC_RE = re.compile(
    r"^(?:__interceptor_|__asan|__sanitizer|__ubsan|__msan|__tsan|__lsan|___interceptor_|"
    r"LLVMFuzzer|fuzzer::|_start$|__libc_)"
)


def is_runtime_frame(path: str | None, func: str | None) -> bool:
    return bool((path and _RUNTIME_RE.search(path)) or (func and _RUNTIME_FUNC_RE.match(func)))


def is_reporter_file(path: str) -> bool:
    """File names reporters give their own PoC programs and inputs."""
    return bool(_REPORTER_FILE_RE.search(path))


@dataclass
class Finding:
    claim: Claim
    check: str
    status: str
    severity: str
    detail: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)


@dataclass
class RefContext:
    iset: IndexSet
    primary: Index
    primary_label: str
    alternates: list[tuple[Index, str]]
    names: NameLists
    repo_slug: str  # "owner/repo" or "" when there is no GitHub remote
    top_dirs: frozenset[str]
    poc_names: frozenset[str] = frozenset()
    tag_of: dict[str, str] = field(default_factory=dict)

    def label_for(self, commit: str) -> str:
        return self.tag_of.get(commit, commit[:12])

    def link(
        self, index: Index, path: str, start: int | None = None, end: int | None = None
    ) -> str:
        frag = ""
        if start is not None:
            frag = f"#L{start}" if end is None or end == start else f"#L{start}-L{end}"
        if self.repo_slug:
            return f"https://github.com/{self.repo_slug}/blob/{index.commit}/{path}{frag}"
        loc = f":{start}" if start is not None else ""
        if start is not None and end not in (None, start):
            loc += f"-{end}"
        return f"{path}{loc} @ {index.commit[:12]}"


def make_context(
    iset: IndexSet,
    primary_commit: str,
    primary_label: str,
    alternates: Sequence[tuple[str, str]],
    names: NameLists,
    repo_slug: str,
) -> RefContext:
    primary = iset.get(primary_commit)
    tops = {p.split("/", 1)[0] for p in _all_paths(primary) if "/" in p}
    return RefContext(
        tag_of=iset.repo.tag_commits(),
        iset=iset,
        primary=primary,
        primary_label=primary_label,
        alternates=[(iset.get(sha), label) for sha, label in alternates],
        names=names,
        repo_slug=repo_slug,
        top_dirs=frozenset(tops),
    )


def _all_paths(index: Index) -> list[str]:
    rows = index.store.db.execute(
        "SELECT p.path FROM tree t JOIN paths p ON p.id=t.path_id WHERE t.commit_id=?",
        (index._cid,),
    ).fetchall()
    return [r[0] for r in rows]


# -- path handling -------------------------------------------------------------------
def in_tree_path(ctx: RefContext, cited: str) -> str | None:
    """Normalise a cited path to a repository-relative path, or None when it is not about the tree.

    ``/home/u/curl-8.4.0/lib/http.c`` -> ``lib/http.c``; ``exploit/poc.c`` -> None.
    """
    path = cited.strip().replace("\\", "/")
    path = re.sub(r"^(?:\./|a/|b/)+", "", path)
    if not path:
        return None
    parts = [p for p in path.split("/") if p and p != "."]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    for i, part in enumerate(parts[:-1]):
        if part in ctx.top_dirs:
            return "/".join(parts[i:])
    if ctx.primary.file("/".join(parts)) is not None:
        return "/".join(parts)
    return None


def _is_system_path(cited: str) -> bool:
    return (
        cited.startswith(SYSTEM_PREFIXES)
        or "/site-packages/" in cited
        or "/dist-packages/" in cited
    )


def _locate(index: Index, path: str) -> list[str]:
    if "/" not in path:
        return index.paths_with_basename(path)
    if index.file(path) is not None:
        return [path]
    return index.resolve_path(path)


# -- individual checks -------------------------------------------------------------
def check_path(ctx: RefContext, claim: Claim) -> Finding:
    cited = claim.path or claim.value
    if claim.repo and ctx.repo_slug and claim.repo != ctx.repo_slug.lower():
        return Finding(
            claim, "path", "other_repository", "neutral", {"path": cited, "repository": claim.repo}
        )
    if _is_system_path(cited) and in_tree_path(ctx, cited) is None:
        return Finding(claim, "path", "outside_project", "neutral", {"path": cited})
    rel = in_tree_path(ctx, cited)
    if rel is None:
        return Finding(claim, "path", "outside_project", "neutral", {"path": cited})
    hits = _locate(ctx.primary, rel)
    if hits:
        status = "found"
        if (
            "/" in rel
            and hits[0] != rel
            and not rel.endswith(hits[0])
            and not hits[0].endswith(rel)
        ):
            status = "found_moved"
        return Finding(
            claim,
            "path",
            status,
            "ok" if status == "found" else "soft",
            {"path": cited, "resolved": hits[0], "ref": ctx.primary_label},
            [ctx.link(ctx.primary, hits[0])],
        )
    base = rel.rsplit("/", 1)[-1]
    elsewhere = ctx.primary.paths_with_basename(base)
    if elsewhere and "/" in rel:
        return Finding(
            claim,
            "path",
            "found_moved",
            "soft",
            {"path": cited, "resolved": elsewhere[0], "ref": ctx.primary_label, "moved": True},
            [ctx.link(ctx.primary, elsewhere[0])],
        )
    for alt, label in ctx.alternates:
        alt_hits = _locate(alt, rel)
        if alt_hits:
            return Finding(
                claim,
                "path",
                "found_moved",
                "soft",
                {"path": cited, "resolved": alt_hits[0], "ref": label, "other_version": True},
                [ctx.link(alt, alt_hits[0])],
            )
    other = ctx.primary.any_version_path(rel) if "/" in rel else None
    if other:
        return Finding(
            claim,
            "path",
            "found_moved",
            "soft",
            {"path": cited, "resolved": rel, "ref": ctx.label_for(other), "other_version": True},
            [ctx.link(ctx.iset.get(other), rel)],
        )
    if is_reporter_file(rel):
        return Finding(
            claim, "path", "outside_project", "neutral", {"path": cited, "reporter_file": True}
        )
    severity = "hard" if claim.confidence == "high" and "/" in rel else "soft"
    return Finding(claim, "path", "not_found", severity, {"path": cited, "ref": ctx.primary_label})


def check_symbol(ctx: RefContext, claim: Claim) -> Finding:
    name = claim.value
    defs = ctx.primary.definitions(name)
    if not defs and ctx.names.is_external(name):
        return Finding(claim, "symbol", "external", "neutral", {"symbol": name})
    if defs:
        loc = _best_definition(defs)
        return Finding(
            claim,
            "symbol",
            "defined",
            "ok",
            {
                "symbol": name,
                "path": loc.path,
                "kind": loc.definition.kind,
                "ref": ctx.primary_label,
            },
            [ctx.link(ctx.primary, loc.path, loc.definition.start, loc.definition.end)],
        )
    if ctx.primary.is_referenced(name):
        files = ctx.primary.files_referencing(name, limit=3)
        return Finding(
            claim,
            "symbol",
            "referenced_only",
            "ok",
            {"symbol": name, "files": files, "ref": ctx.primary_label},
            [ctx.link(ctx.primary, f) for f in files[:1]],
        )
    for alt, label in ctx.alternates:
        alt_defs = alt.definitions(name)
        if alt_defs or alt.is_referenced(name):
            evidence = []
            detail: dict[str, Any] = {
                "symbol": name,
                "ref": label,
                "primary_ref": ctx.primary_label,
            }
            if alt_defs:
                loc = _best_definition(alt_defs)
                detail["path"] = loc.path
                evidence.append(ctx.link(alt, loc.path, loc.definition.start, loc.definition.end))
            return Finding(claim, "symbol", "defined_at_other_version", "soft", detail, evidence)
    other = ctx.primary.any_version_definition(name)
    if other:
        commit, path = other
        return Finding(
            claim,
            "symbol",
            "defined_at_other_version",
            "soft",
            {
                "symbol": name,
                "ref": ctx.label_for(commit),
                "path": path,
                "primary_ref": ctx.primary_label,
            },
            [ctx.link(ctx.iset.get(commit), path)],
        )
    if name in ctx.poc_names:
        return Finding(claim, "symbol", "defined_by_poc", "neutral", {"symbol": name})
    severity = "hard" if claim.confidence == "high" else "soft"
    return Finding(
        claim, "symbol", "not_found", severity, {"symbol": name, "ref": ctx.primary_label}
    )


def _best_definition(defs: list[Any]) -> Any:
    order = {
        "function": 0,
        "method": 0,
        "macro": 1,
        "type": 2,
        "constant": 3,
        "variable": 4,
        "declaration": 5,
        "namespace": 6,
    }
    return sorted(defs, key=lambda d: (order.get(d.definition.kind, 9), d.path))[0]


def _line_status(index: Index, path: str, line: int, end: int | None) -> tuple[str, int]:
    info = index.file(path)
    assert info is not None
    last = max(line, end or line)
    if last > info.lines or line < 1:
        return "out_of_range", info.lines
    blank = index.comment_or_blank(path)
    if all(n in blank for n in range(line, (end or line) + 1)):
        return "blank_or_comment", info.lines
    return "in_range", info.lines


def check_line(ctx: RefContext, claim: Claim) -> Finding | None:
    if claim.line is None or not claim.path:
        return None
    if claim.repo and ctx.repo_slug and claim.repo != ctx.repo_slug.lower():
        return None
    rel = in_tree_path(ctx, claim.path)
    if rel is None:
        return None
    hits = _locate(ctx.primary, rel)
    if len(hits) != 1:
        return None  # the path check reports missing or ambiguous files
    path = hits[0]
    status, total = _line_status(ctx.primary, path, claim.line, claim.line_end)
    detail = {
        "path": path,
        "line": claim.line,
        "line_end": claim.line_end,
        "lines": total,
        "ref": ctx.primary_label,
    }
    if status == "in_range":
        return Finding(
            claim,
            "line",
            status,
            "ok",
            detail,
            [ctx.link(ctx.primary, path, claim.line, claim.line_end)],
        )
    if status == "blank_or_comment":
        return Finding(
            claim,
            "line",
            status,
            "soft",
            detail,
            [ctx.link(ctx.primary, path, claim.line, claim.line_end)],
        )
    for alt, label in ctx.alternates:
        alt_hits = _locate(alt, rel)
        if len(alt_hits) == 1:
            alt_status, alt_total = _line_status(alt, alt_hits[0], claim.line, claim.line_end)
            if alt_status != "out_of_range":
                detail.update({"other_ref": label, "other_lines": alt_total})
                return Finding(
                    claim,
                    "line",
                    "in_range_at_other_version",
                    "soft",
                    detail,
                    [ctx.link(alt, alt_hits[0], claim.line, claim.line_end)],
                )
    severity = "hard" if claim.confidence == "high" else "soft"
    return Finding(claim, "line", "out_of_range", severity, detail, [ctx.link(ctx.primary, path)])


def _function_line_status(
    index: Index, path: str, function: str, line: int
) -> tuple[str, dict[str, Any]]:
    defs = [d for d in index.defs_in_file(path) if d.name == function]
    fn_defs = [d for d in defs if d.kind in FUNCTION_KINDS]
    if not fn_defs:
        if [d for d in defs if d.kind == "macro"]:
            return "consistent", {"macro": True}
        return "function_not_in_file", {}
    for d in fn_defs:
        if d.start - 1 <= line <= d.end + 1:
            return "consistent", {"span": [d.start, d.end]}
    containing = index.functions_at(path, line)
    macros = index.macros_at(path, line)
    if macros:
        return "consistent", {"macro": True}
    return "outside_function", {
        "span": [fn_defs[0].start, fn_defs[0].end],
        "actual": containing[0].name if containing else None,
    }


def check_frame(ctx: RefContext, claim: Claim) -> list[Finding]:
    findings = _check_frame(ctx, claim)
    for f in findings:
        f.claim = claim  # sub-checks (path, symbol, line) report against the frame itself
    return findings


def _check_frame(ctx: RefContext, claim: Claim) -> list[Finding]:
    func = claim.function
    findings: list[Finding] = []
    if is_runtime_frame(claim.path, func):
        return [
            Finding(
                claim,
                "frame",
                "outside_project",
                "neutral",
                {"path": claim.path, "function": func, "runtime": True},
            )
        ]
    if not claim.path or claim.line is None:
        if func and not ctx.names.is_external(func) and claim.confidence == "high":
            findings.append(check_symbol(ctx, _as_symbol(claim, func)))
        return findings
    rel = in_tree_path(ctx, claim.path)
    if rel is None or (_is_system_path(claim.path) and not _locate(ctx.primary, rel)):
        return [
            Finding(
                claim, "frame", "outside_project", "neutral", {"path": claim.path, "function": func}
            )
        ]
    hits = _locate(ctx.primary, rel)
    if not hits and (
        is_reporter_file(rel)
        or (func is not None and (ctx.names.is_external(func) or func in ctx.poc_names))
    ):
        return [
            Finding(
                claim, "frame", "outside_project", "neutral", {"path": claim.path, "function": func}
            )
        ]
    if not hits:
        alt_found = any(_locate(alt, rel) for alt, _ in ctx.alternates)
        if not alt_found and "/" not in rel and not (func and ctx.primary.definitions(func)):
            # a bare file name that the project never had: likely the reporter's own harness
            return [
                Finding(
                    claim,
                    "frame",
                    "outside_project",
                    "neutral",
                    {"path": claim.path, "function": func},
                )
            ]
        findings.append(check_path(ctx, _as_path(claim, rel)))
        if func and not ctx.names.is_external(func):
            findings.append(check_symbol(ctx, _as_symbol(claim, func)))
        return findings
    if len(hits) > 1 and func:
        with_fn = [h for h in hits if any(d.name == func for d in ctx.primary.defs_in_file(h))]
        hits = with_fn or hits
    path = hits[0]
    line_status, total = _line_status(ctx.primary, path, claim.line, None)
    if line_status == "out_of_range":
        f = check_line(
            ctx,
            Claim(
                "line",
                path,
                claim.start,
                claim.end,
                claim.confidence,
                claim.source,
                path=path,
                line=claim.line,
            ),
        )
        if f is not None:
            findings.append(f)
        if f is not None and f.severity == "hard":
            return findings
    if not func or ctx.names.is_external(func):
        return findings
    status, extra = _function_line_status(ctx.primary, path, func, claim.line)
    detail: dict[str, Any] = {
        "path": path,
        "function": func,
        "line": claim.line,
        "ref": ctx.primary_label,
        **extra,
    }
    if status == "consistent":
        findings.append(
            Finding(claim, "frame", status, "ok", detail, [ctx.link(ctx.primary, path, claim.line)])
        )
        return findings
    for alt, label in ctx.alternates:
        alt_hits = _locate(alt, rel)
        if len(alt_hits) >= 1:
            alt_status, alt_extra = _function_line_status(alt, alt_hits[0], func, claim.line)
            if alt_status == "consistent":
                detail.update({"other_ref": label})
                findings.append(
                    Finding(
                        claim,
                        "frame",
                        "consistent_at_other_version",
                        "soft",
                        detail,
                        [ctx.link(alt, alt_hits[0], claim.line)],
                    )
                )
                return findings
    if status == "function_not_in_file":
        where = ctx.primary.definitions(func)
        if not where:
            sym = check_symbol(ctx, _as_symbol(claim, func))
            if sym.status != "not_found":
                findings.append(sym)
                return findings
        detail["defined_in"] = [w.path for w in where[:3]]
    severity = "hard" if claim.confidence == "high" else "soft"
    findings.append(
        Finding(claim, "frame", status, severity, detail, [ctx.link(ctx.primary, path, claim.line)])
    )
    return findings


def _as_symbol(claim: Claim, name: str) -> Claim:
    return Claim("symbol", name, claim.start, claim.end, claim.confidence, claim.source)


def _as_path(claim: Claim, path: str) -> Claim:
    return Claim("path", path, claim.start, claim.end, claim.confidence, claim.source, path=path)


def check_frame_chain(
    ctx: RefContext, frames: list[Claim], frame_findings: dict[int, list[Finding]]
) -> list[Finding]:
    """Soft check: does each in-project caller mention its callee?"""
    out: list[Finding] = []
    by_trace: dict[int, list[Claim]] = {}
    for c in frames:
        if c.trace is not None:
            by_trace.setdefault(c.trace, []).append(c)
    for chain in by_trace.values():
        chain.sort(key=lambda c: c.frame_index or 0)
        for callee, caller in zip(chain, chain[1:], strict=False):
            f_callee = frame_findings.get(id(callee), [])
            f_caller = frame_findings.get(id(caller), [])
            if not _consistent(f_callee) or not _consistent(f_caller):
                continue
            span = next((f.detail.get("span") for f in f_caller if f.status == "consistent"), None)
            caller_path = next(
                (f.detail.get("path") for f in f_caller if f.status == "consistent"), None
            )
            if not span or not caller_path or not callee.function:
                continue
            content = ctx.primary.read(caller_path) or b""
            body = b"\n".join(content.split(b"\n")[span[0] - 1 : span[1]])
            seen = (
                re.search(rb"\b" + re.escape(callee.function.encode()) + rb"\b", body) is not None
            )
            out.append(
                Finding(
                    caller,
                    "frame_chain",
                    "call_seen" if seen else "call_not_seen",
                    "ok" if seen else "soft",
                    {"caller": caller.function, "callee": callee.function, "trace": caller.trace},
                )
            )
    return out


def _consistent(findings: list[Finding]) -> bool:
    return any(f.status == "consistent" for f in findings)


# -- quotes ---------------------------------------------------------------------------
_C_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_HASH_COMMENT_RE = re.compile(
    r"(?m)#(?!\s*(?:include|define|if|ifdef|ifndef|endif|else|elif|undef|pragma)\b)[^\n]*$"
)
_ELISION_RE = re.compile(r"^\s*(?:\.\.\.|…|/\*\s*\.\.\.\s*\*/|//\s*\.\.\.|#\s*\.\.\.)\s*;?\s*$")
_GUTTER_RE = re.compile(r"^\s*\d{1,6}\s*[:|]?\s{1,}")


def normalise_code(text: str, lang: str | None) -> list[str]:
    lines = text.replace("\r\n", "\n").split("\n")
    # drop editor line-number gutters like "  123 |" when most lines carry one
    if lines and sum(1 for ln in lines if _GUTTER_RE.match(ln)) >= max(
        2, int(0.6 * len([ln for ln in lines if ln.strip()]))
    ):
        lines = [_GUTTER_RE.sub("", ln, count=1) for ln in lines]
    joined = "\n".join(lines)
    joined = _C_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), joined)
    if lang == "python":
        joined = _HASH_COMMENT_RE.sub("", joined)
    out = []
    for line in joined.split("\n"):
        norm = re.sub(r"\s+", " ", line).strip()
        out.append(norm)
    return out


def _segments(lines: list[str], raw: list[str]) -> list[list[str]]:
    segs: list[list[str]] = [[]]
    for norm, original in zip(lines, raw, strict=False):
        if _ELISION_RE.match(original):
            segs.append([])
        elif norm:
            segs[-1].append(norm)
    return [s for s in segs if s]


_TOKEN_RE = re.compile(r"[A-Za-z_]\w*|\d+")


def _significant(line: str) -> bool:
    return len(_TOKEN_RE.findall(line)) >= 2 or len(line) >= 12


@dataclass
class _FileLines:
    lines: list[str]  # normalised, one per source line (may be empty)
    exact: dict[str, list[int]]
    tokens: dict[str, list[int]]


@lru_cache(maxsize=256)
def _file_lines(blob: str, text: str, lang: str | None) -> _FileLines:
    lines = normalise_code(text, lang)
    exact: dict[str, list[int]] = {}
    tokens: dict[str, list[int]] = {}
    for i, ln in enumerate(lines):
        if not ln:
            continue
        exact.setdefault(ln, []).append(i)
        for tok in set(_TOKEN_RE.findall(ln)):
            if len(tok) >= 4:
                tokens.setdefault(tok, []).append(i)
    return _FileLines(lines, exact, tokens)


def _line_hits(qline: str, fl: _FileLines) -> tuple[list[int], bool]:
    """File line indexes that match one quoted line; the flag says whether the match is exact."""
    if qline in fl.exact:
        return fl.exact[qline], True
    if "..." in qline or "…" in qline:
        prefix = re.split(r"\.\.\.|…", qline, maxsplit=1)[0].strip()
        if len(prefix) >= 8:
            return [i for i, ln in enumerate(fl.lines) if ln.startswith(prefix)][:50], False
    toks = sorted({t for t in _TOKEN_RE.findall(qline) if len(t) >= 4}, key=len, reverse=True)[:2]
    cands: set[int] = set()
    for t in toks:
        cands.update(fl.tokens.get(t, [])[:400])
    hits = []
    for i in sorted(cands)[:400]:
        ln = fl.lines[i]
        if abs(len(ln) - len(qline)) > max(12, len(qline) // 2):
            continue
        if difflib.SequenceMatcher(None, qline, ln, autojunk=False).ratio() >= 0.9:
            hits.append(i)
    return hits, False


def _match_segment(seg: list[str], fl: _FileLines) -> tuple[int, int, int, bool]:
    """(matched, total, first line, exact) for significant quoted lines found in order in one window."""
    sig = [ln for ln in seg if _significant(ln)] or seg
    hits: list[tuple[list[int], bool]] = [_line_hits(q, fl) for q in sig]
    width = max(len(seg) * 3, len(seg) + 12)
    best, best_at, best_exact = 0, -1, False
    starts = sorted({i for positions, _ in hits for i in positions[:100]})
    for start in starts:
        cursor, matched, all_exact = start - 1, 0, True
        for positions, is_exact in hits:
            nxt = next((p for p in positions if cursor < p < start + width), None)
            if nxt is not None:
                matched += 1
                cursor = nxt
                all_exact = all_exact and is_exact
            else:
                all_exact = False
        if matched > best:
            best, best_at, best_exact = matched, start + 1, all_exact
    return best, len(hits), best_at, best_exact and best == len(hits)


def _quote_in_index(index: Index, claim: Claim, paths: list[str]) -> tuple[str, dict[str, Any]]:
    """Share of the quote's significant lines found in the project, segment by segment.

    Reporters abbreviate with ``...`` and join excerpts; each excerpt is located
    on its own, and the quote counts as found when at least 85% of its
    significant lines are present in order.
    """
    raw = (claim.text or "").split("\n")
    norm = normalise_code(claim.text or "", claim.lang)
    segments = [s for s in _segments(norm, raw) if len(" ".join(s)) >= 12]
    if not segments:
        return "too_short", {}
    matched_total, lines_total, all_exact = 0, 0, True
    matches: list[dict[str, Any]] = []
    closest: dict[str, Any] | None = None
    for seg in segments:
        best: tuple[int, int, str | None, int, bool] = (0, 1, None, -1, False)
        path: str | None
        for path in paths:
            info = index.file(path)
            content = index.read(path)
            if info is None or not content or len(content) > 3_000_000:
                continue
            fl = _file_lines(info.blob, content.decode("utf-8", "replace"), info.lang)
            matched, total, at, exact = _match_segment(seg, fl)
            if path is not None and (best[2] is None or matched / total > best[0] / best[1]):
                best = (matched, total, path, at, exact)
            if matched == total and exact:
                break
        matched, total, found_path, at, exact = best
        path = found_path
        if path is None:
            total = len([ln for ln in seg if _significant(ln)] or seg)
        matched_total += matched
        lines_total += total
        all_exact = all_exact and exact
        if path and matched:
            matches.append({"path": path, "line": at, "lines": len(seg)})
            if closest is None:
                closest = {"path": path, "line": at}
    score = matched_total / lines_total if lines_total else 0.0
    detail: dict[str, Any] = {"similarity": round(score, 3)}
    if score >= QUOTE_SIMILARITY:
        detail["matches"] = matches
        return ("exact" if all_exact else "approximate"), detail
    detail["best_similarity"] = round(score, 3)
    if closest:
        detail["closest"] = closest
    return "not_found", detail


def _quote_candidates(ctx: RefContext, index: Index, claim: Claim) -> list[str]:
    paths: list[str] = []
    if claim.path:
        rel = in_tree_path(ctx, claim.path)
        if rel:
            paths.extend(_locate(index, rel)[:3])
    words = [
        w for w in re.findall(r"[A-Za-z_]\w{3,}", claim.text or "") if not ctx.names.is_ignored(w)
    ]
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    rare = sorted(freq, key=lambda w: (-len(w), w))[:12]
    for p in index.candidate_files(rare, limit=8):
        if p not in paths:
            paths.append(p)
    return paths


def check_quote(ctx: RefContext, claim: Claim) -> Finding:
    status, detail = _quote_in_index(ctx.primary, claim, _quote_candidates(ctx, ctx.primary, claim))
    detail.update({"path": claim.path, "ref": ctx.primary_label})
    if status == "too_short":
        return Finding(claim, "quote", "too_short", "neutral", detail)
    if status in ("exact", "approximate"):
        ev = [
            ctx.link(ctx.primary, m["path"], m["line"], m["line"] + m["lines"] - 1)
            for m in detail.get("matches", [])[:2]
        ]
        return Finding(claim, "quote", status, "ok", detail, ev)
    for alt, label in ctx.alternates:
        alt_status, alt_detail = _quote_in_index(alt, claim, _quote_candidates(ctx, alt, claim))
        if alt_status in ("exact", "approximate"):
            alt_detail.update({"path": claim.path, "ref": label, "primary_ref": ctx.primary_label})
            ev = [
                ctx.link(alt, m["path"], m["line"], m["line"] + m["lines"] - 1)
                for m in alt_detail.get("matches", [])[:2]
            ]
            return Finding(claim, "quote", "found_at_other_version", "soft", alt_detail, ev)
    severity = "hard" if claim.confidence == "high" else "soft"
    return Finding(claim, "quote", "not_found", severity, detail)


# -- PoC, CVE ---------------------------------------------------------------------------
def check_poc_reference(ctx: RefContext, claim: Claim) -> Finding:
    """Soft signal: a C/C++/Python PoC that names nothing the project defines."""
    text = claim.text or ""
    if claim.poc_kind not in ("c", "cpp", "python"):
        return Finding(claim, "poc", "not_checked", "neutral", {"poc_kind": claim.poc_kind})
    names = {w for w in re.findall(r"[A-Za-z_]\w{2,}", text) if not ctx.names.is_ignored(w)}
    project = [n for n in sorted(names) if ctx.primary.definitions(n)]
    if project:
        return Finding(
            claim, "poc", "calls_project", "ok", {"poc_kind": claim.poc_kind, "names": project[:5]}
        )
    includes = re.findall(r'#\s*include\s*[<"]([^>"]+)[>"]', text)
    for inc in includes:
        if _locate(ctx.primary, inc.split("/")[-1]) and "/" in inc:
            return Finding(
                claim, "poc", "calls_project", "ok", {"poc_kind": claim.poc_kind, "includes": [inc]}
            )
    return Finding(claim, "poc", "no_project_reference", "soft", {"poc_kind": claim.poc_kind})


def check_cve(claim: Claim, project_cves: set[str] | None) -> Finding:
    if project_cves is None:
        return Finding(claim, claim.kind, "format_ok", "neutral", {"id": claim.value})
    status = "listed" if claim.value.upper() in project_cves else "not_listed"
    return Finding(claim, claim.kind, status, "neutral", {"id": claim.value})


# -- driver -----------------------------------------------------------------------------
def check_claims(
    ctx: RefContext, claims: Iterable[Claim], project_cves: set[str] | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    frames: list[Claim] = []
    frame_findings: dict[int, list[Finding]] = {}
    for claim in claims:
        if claim.kind == "path":
            findings.append(check_path(ctx, claim))
        elif claim.kind == "symbol":
            findings.append(check_symbol(ctx, claim))
        elif claim.kind == "line":
            f = check_line(ctx, claim)
            if f is not None:
                findings.append(f)
        elif claim.kind == "frame":
            ff = check_frame(ctx, claim)
            frame_findings[id(claim)] = ff
            frames.append(claim)
            findings.extend(ff)
        elif claim.kind == "quote":
            findings.append(check_quote(ctx, claim))
        elif claim.kind == "poc":
            findings.append(check_poc_reference(ctx, claim))
        elif claim.kind == "cve" and project_cves is not None:
            findings.append(check_cve(claim, project_cves))
    _downgrade_harness_frames(frames, frame_findings)
    findings.extend(check_frame_chain(ctx, frames, frame_findings))
    return findings


def _downgrade_harness_frames(
    frames: list[Claim], frame_findings: dict[int, list[Finding]]
) -> None:
    """Frames below every resolved project frame are the reporter's harness, not claims about the code.

    A fuzzer or test driver calls into the project from its own files; when a
    trace has resolved project frames, unresolved frames further down the
    stack are callers, and a missing path or name there is expected.
    """
    by_trace: dict[int, list[Claim]] = {}
    for c in frames:
        if c.trace is not None:
            by_trace.setdefault(c.trace, []).append(c)
    for chain in by_trace.values():
        resolved = [
            c.frame_index or 0
            for c in chain
            if any(f.severity == "ok" for f in frame_findings.get(id(c), []))
        ]
        if not resolved:
            continue
        deepest_caller = max(resolved)
        for c in chain:
            if (c.frame_index or 0) <= deepest_caller:
                continue
            for f in frame_findings.get(id(c), []):
                if f.severity == "hard" and f.status in ("not_found", "function_not_in_file"):
                    f.status, f.severity = "outside_project", "neutral"
                    f.detail["harness"] = True
