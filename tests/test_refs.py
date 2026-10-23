from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_repo
from sloptriage.config import Config, Thresholds
from sloptriage.extract import Claim
from sloptriage.index import IndexSet
from sloptriage.index.gitobj import GitRepo
from sloptriage.models import Report
from sloptriage.names import load_names
from sloptriage.refs import (
    check_frame,
    check_line,
    check_path,
    check_quote,
    check_symbol,
    make_context,
)
from sloptriage.verdict import aggregate, run_reference_check
from sloptriage.versions import VersionResolver

A_V1 = """#include "a.h"

/* parse one header line */
static int parse_header(const char *line, int len)
{
    int n = 0;
    while(n < len && line[n] != ':')
        n++;
    return n;
}

int read_chunk(const char *buf, int len)
{
    if(len <= 0)
        return -1;
    return parse_header(buf, len);
}
"""
A_V2 = A_V1.replace("parse_header", "parse_header_line")


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> tuple[GitRepo, IndexSet, VersionResolver]:
    root = make_repo(
        tmp_path_factory.mktemp("proj") / "demo",
        [
            (
                "v1.0.0",
                {"lib/a.c": A_V1, "include/a.h": "int read_chunk(const char *buf, int len);\n"},
            ),
            (
                "v1.1.0",
                {
                    "lib/a.c": A_V2,
                    "include/a.h": "int read_chunk(const char *buf, int len);\n",
                    "lib/b.c": "int b_fn(void) { return 0; }\n",
                },
            ),
        ],
    )
    repo = GitRepo(root)
    iset = IndexSet(repo, str(root))
    return repo, iset, VersionResolver(repo, ["v{version}"], "demo")


def _ctx(project: tuple[GitRepo, IndexSet, VersionResolver], tag: str = "v1.1.0"):  # type: ignore[no-untyped-def]
    repo, iset, resolver = project
    sha = repo.resolve_commit(tag)
    assert sha
    others = [(s, t) for s, t in ((repo.resolve_commit("v1.0.0"), "v1.0.0"),) if s and s != sha]
    return make_context(iset, sha, tag, others, load_names(), "example/demo")


def C(kind: str, value: str, conf: str = "high", **kw: object) -> Claim:
    return Claim(kind, value, 0, 1, conf, "test", **kw)  # type: ignore[arg-type]


def test_symbol_statuses(project: tuple[GitRepo, IndexSet, VersionResolver]) -> None:
    ctx = _ctx(project)
    assert check_symbol(ctx, C("symbol", "read_chunk")).status == "defined"
    assert check_symbol(ctx, C("symbol", "parse_header")).status == "defined_at_other_version"
    assert check_symbol(ctx, C("symbol", "parse_header")).severity == "soft"
    missing = check_symbol(ctx, C("symbol", "pk_merge_continuation"))
    assert (missing.status, missing.severity) == ("not_found", "hard")
    assert check_symbol(ctx, C("symbol", "pk_merge_continuation", "medium")).severity == "soft"
    assert check_symbol(ctx, C("symbol", "SSL_read")).status == "external"
    ok = check_symbol(ctx, C("symbol", "read_chunk"))
    assert (
        ok.evidence[0].startswith("https://github.com/example/demo/blob/")
        and "#L12-L17" in ok.evidence[0]
    )


def test_path_statuses(project: tuple[GitRepo, IndexSet, VersionResolver]) -> None:
    ctx = _ctx(project)
    assert check_path(ctx, C("path", "lib/a.c", path="lib/a.c")).status == "found"
    assert (
        check_path(
            ctx, C("path", "/home/u/demo-1.1.0/lib/a.c", path="/home/u/demo-1.1.0/lib/a.c")
        ).status
        == "found"
    )
    assert check_path(ctx, C("path", "src/a.c", path="src/a.c")).status == "outside_project"
    moved = check_path(ctx, C("path", "include/a.c", path="include/a.c"))
    assert moved.status == "found_moved"
    assert (
        check_path(ctx, C("path", "lib/http_parser.c", path="lib/http_parser.c")).status
        == "not_found"
    )
    assert check_path(ctx, C("path", "lib/poc.c", path="lib/poc.c")).status == "outside_project"
    old = _ctx(project, "v1.0.0")
    assert check_path(old, C("path", "lib/b.c", path="lib/b.c")).status == "found_moved"


def test_line_statuses(project: tuple[GitRepo, IndexSet, VersionResolver]) -> None:
    ctx = _ctx(project)
    assert check_line(ctx, C("line", "lib/a.c", path="lib/a.c", line=7)).status == "in_range"  # type: ignore[union-attr]
    assert (
        check_line(ctx, C("line", "lib/a.c", path="lib/a.c", line=3)).status == "blank_or_comment"
    )  # type: ignore[union-attr]
    f = check_line(ctx, C("line", "lib/a.c", path="lib/a.c", line=812))
    assert f is not None and (f.status, f.severity, f.detail["lines"]) == (
        "out_of_range",
        "hard",
        17,
    )


def test_frame_statuses(project: tuple[GitRepo, IndexSet, VersionResolver]) -> None:
    ctx = _ctx(project)
    ok = check_frame(
        ctx, C("frame", "read_chunk", path="/src/demo/lib/a.c", line=15, function="read_chunk")
    )
    assert [f.status for f in ok] == ["consistent"]
    wrong = check_frame(
        ctx, C("frame", "read_chunk", path="lib/a.c", line=7, function="read_chunk")
    )
    assert (
        wrong[-1].status == "outside_function" and wrong[-1].detail["actual"] == "parse_header_line"
    )
    elsewhere = check_frame(ctx, C("frame", "b_fn", path="lib/a.c", line=7, function="b_fn"))
    assert elsewhere[-1].status == "function_not_in_file"
    runtime = check_frame(
        ctx,
        C(
            "frame",
            "__interceptor_memcpy",
            path="/src/llvm/compiler-rt/asan_interceptors.cpp",
            line=8,
            function="__interceptor_memcpy",
        ),
    )
    assert runtime[0].severity == "neutral"


def test_quote_statuses(project: tuple[GitRepo, IndexSet, VersionResolver]) -> None:
    ctx = _ctx(project)
    exact = "int read_chunk(const char *buf, int len)\n{\n    if(len <= 0)\n        return -1;\n"
    assert (
        check_quote(ctx, C("quote", "lib/a.c", path="lib/a.c", text=exact, lang="c")).status
        == "exact"
    )
    abbreviated = "int read_chunk(const char *buf, int len)\n{\n    ...\n    return parse_header_line(buf, len); // here\n"
    assert check_quote(
        ctx, C("quote", "lib/a.c", path="lib/a.c", text=abbreviated, lang="c")
    ).status in ("exact", "approximate")
    invented = "static void pk_merge(char *dst, const char *src)\n{\n    memcpy(dst, src, strlen(src) + 64);\n    dst[1024] = 0;\n}\n"
    f = check_quote(ctx, C("quote", "lib/a.c", path="lib/a.c", text=invented, lang="c"))
    assert (f.status, f.severity) == ("not_found", "hard")


def test_version_resolution(project: tuple[GitRepo, IndexSet, VersionResolver]) -> None:
    _, _, resolver = project
    res = resolver.resolve([C("version", "1.0.0")], None)
    assert (res.ref_label, res.assumed) == ("v1.0.0", False)
    res = resolver.resolve([C("version", "2.0.0")], "2024-01-15T00:00:00Z")
    assert res.assumed and res.reason == "version_not_found"
    assert res.findings[0].status == "not_found" and res.findings[0].nearest[0] == "v1.1.0"
    res = resolver.resolve([], "2024-01-15T00:00:00Z")
    assert res.assumed and res.reason == "no_version" and res.ref_label.endswith("@2024-01-15")


def test_aggregation_rule_and_padding() -> None:
    th = Thresholds(hard_fail_min=2, min_verified_share=0.7, min_verified_claims=3)
    from sloptriage.refs import Finding

    def outcome(sev: str) -> tuple[Claim, Finding]:
        c = C("symbol", f"s{len(sev)}")
        return c, Finding(
            c,
            "symbol",
            {"ok": "defined", "hard": "not_found", "soft": "defined_at_other_version"}[sev],
            sev,
        )

    def run(sevs: list[str]) -> str:
        pairs = [outcome(s) for s in sevs]
        return aggregate([p[0] for p in pairs], [p[1] for p in pairs], th).cls

    assert run([]) == "refs_none"
    assert run(["ok", "ok", "ok"]) == "refs_verified"
    assert run(["ok"]) == "refs_thin"
    assert run(["ok", "ok", "soft"]) == "refs_mixed"
    assert run(["hard", "ok", "ok", "ok"]) == "refs_mixed"
    assert run(["hard", "ok"]) == "refs_failed"  # share 0.5 < 0.7
    assert run(["hard", "hard"] + ["ok"] * 20) == "refs_failed"  # padding does not rescue


def test_end_to_end_reference_check(
    project: tuple[GitRepo, IndexSet, VersionResolver], tmp_path: Path
) -> None:
    repo, iset, _ = project
    cfg = Config(
        project="demo",
        version_tags=["v{version}"],
        languages=["c"],
        repository="https://github.com/example/demo",
        thresholds=Thresholds(2, 0.7, 3),
    )
    body = (
        "Affected: demo 1.1.0\n\nThe crash is in `pk_merge_continuation()` called from `pk_unfold_line()` "
        "at lib/a.c:812 inside `read_chunk()`."
    )
    result = run_reference_check(Report("file", "r1", "t", body), repo, iset, cfg)
    assert result.resolution.ref_label == "v1.1.0"
    assert result.aggregate.cls == "refs_failed"
    good = "demo 1.1.0: `read_chunk()` in lib/a.c line 15 calls `parse_header_line()` (lib/a.c:7)."
    assert (
        run_reference_check(Report("file", "r2", "t", good), repo, iset, cfg).aggregate.cls
        == "refs_verified"
    )
