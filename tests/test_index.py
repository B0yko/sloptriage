from __future__ import annotations

from pathlib import Path

from conftest import make_repo
from sloptriage.index import IndexSet
from sloptriage.index.defs import comment_or_blank_lines, definitions
from sloptriage.index.gitobj import GitRepo

C_SRC = """#include <stdio.h>
#define MAX_LEN 64
#define SQUARE(x) \\
    ((x) * (x))

struct buf { char *data; int len; };
typedef struct buf buf_t;
enum mode { MODE_A, MODE_B };

/* parse a header line */
static int parse_header(const char *line)
{
    int n = 0;
    while (line[n]) n++;
    return n;
}

int read_chunk(buf_t *b, int *out)
{
    // comment only
    *out = b->len;

    return parse_header(b->data);
}

int (*callback)(int);
int exported_fn(int a);
"""

PY_SRC = """import os

LIMIT = 3

class Parser:
    def feed(self, data):
        return data

def top(x):
    def inner():
        return x
    return inner
"""


def test_c_definitions_and_spans() -> None:
    found = {(d.name, d.kind): (d.start, d.end) for d in definitions("c", C_SRC.encode())}
    assert found[("parse_header", "function")] == (11, 16)
    assert found[("read_chunk", "function")] == (18, 24)
    assert found[("MAX_LEN", "macro")] == (2, 2)
    assert found[("SQUARE", "macro")] == (3, 4)
    assert ("buf", "type") in found
    assert ("buf_t", "type") in found
    assert ("MODE_A", "constant") in found
    assert ("exported_fn", "declaration") in found


def test_python_definitions() -> None:
    found = {(d.name, d.kind, d.qual) for d in definitions("python", PY_SRC.encode())}
    assert ("Parser", "type", "Parser") in found
    assert ("feed", "method", "Parser.feed") in found
    assert ("top", "function", "top") in found
    assert ("inner", "function", "inner") in found
    assert ("LIMIT", "variable", "") in found


def test_comment_and_blank_lines() -> None:
    lines = comment_or_blank_lines("c", C_SRC.encode())
    assert 5 in lines  # blank
    assert 10 in lines  # /* parse a header line */
    assert 20 in lines  # // comment only
    assert 22 in lines  # blank inside function
    assert 21 not in lines


def test_index_commit_without_checkout(tmp_path: Path) -> None:
    src = make_repo(
        tmp_path / "proj",
        [
            ("v1.0.0", {"lib/a.c": C_SRC, "README.md": "hello parse_header\n"}),
            ("v1.1.0", {"lib/b.c": C_SRC, "pkg/mod.py": PY_SRC}),
        ],
    )
    bare = tmp_path / "bare.git"
    import subprocess

    subprocess.run(["git", "clone", "--bare", "-q", str(src), str(bare)], check=True)
    repo = GitRepo(bare)
    sha1 = repo.resolve_commit("v1.0.0")
    sha2 = repo.resolve_commit("v1.1.0")
    assert sha1 and sha2
    iset = IndexSet(repo, str(bare))
    one = iset.get(sha1)
    two = iset.get(sha2)
    assert one.file("lib/a.c") is not None
    assert one.file("lib/a.c").lines == C_SRC.count("\n")  # type: ignore[union-attr]
    assert two.file("lib/a.c") is None
    assert two.paths_with_basename("b.c") == ["lib/b.c"]
    assert [loc.path for loc in two.definitions("parse_header")] == ["lib/b.c"]
    assert two.definitions("Parser")[0].path == "pkg/mod.py"
    assert one.is_referenced("parse_header")
    assert not one.is_referenced("nonexistent_symbol_xyz")
    assert [d.name for d in one.functions_at("lib/a.c", 13)] == ["parse_header"]
    assert one.resolve_path("/home/user/proj/lib/a.c") == ["lib/a.c"]
    assert one.resolve_path("x/y/a.c") == []
    assert one.read("lib/a.c") == C_SRC.encode()
    assert iset.is_cached(sha1)
    # the blob shared between commits is analysed once
    assert iset.store.db.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] == 3
