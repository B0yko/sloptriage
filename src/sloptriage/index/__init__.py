"""Per-commit code index: files, line counts, definitions and identifier occurrences."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sloptriage.index import defs as defs_mod
from sloptriage.index.defs import FUNCTION_KINDS, Definition
from sloptriage.index.gitobj import GitRepo, repo_key
from sloptriage.index.store import Store
from sloptriage.paths import cache_dir

__all__ = ["Index", "IndexSet", "Located", "FileInfo", "Definition"]


@dataclass(frozen=True)
class FileInfo:
    path: str
    blob: str
    lines: int
    lang: str | None
    is_text: bool


@dataclass(frozen=True)
class Located:
    """A definition together with the file it lives in."""

    path: str
    definition: Definition


class Index:
    """Read-only view of one indexed commit."""

    def __init__(self, store: Store, repo: GitRepo, commit: str, commit_id: int) -> None:
        self.store = store
        self.repo = repo
        self.commit = commit
        self._cid = commit_id
        self._db = store.db

    # -- files ---------------------------------------------------------------
    def file(self, path: str) -> FileInfo | None:
        row = self._db.execute(
            "SELECT b.sha, b.lines, b.lang, b.is_text FROM tree t JOIN paths p ON p.id=t.path_id "
            "JOIN blobs b ON b.id=t.blob_id WHERE t.commit_id=? AND p.path=?",
            (self._cid, path),
        ).fetchone()
        if not row:
            return None
        return FileInfo(path, row[0], int(row[1]), row[2], bool(row[3]))

    def paths_with_basename(self, base: str) -> list[str]:
        rows = self._db.execute(
            "SELECT p.path FROM paths p JOIN tree t ON t.path_id=p.id AND t.commit_id=? WHERE p.base=?",
            (self._cid, base),
        ).fetchall()
        return sorted(r[0] for r in rows)

    def resolve_path(self, cited: str) -> list[str]:
        """Map a cited path (possibly absolute or with a build prefix) to repo paths."""
        cited = cited.strip().lstrip("./")
        if not cited:
            return []
        if self.file(cited) is not None:
            return [cited]
        parts = cited.split("/")
        base = parts[-1]
        candidates = self.paths_with_basename(base)
        if not candidates or len(parts) == 1:
            return candidates
        # longest matching suffix wins (handles /home/user/proj/lib/x.c)
        best: list[str] = []
        best_len = 0
        for cand in candidates:
            cparts = cand.split("/")
            n = 0
            while n < min(len(cparts), len(parts)) and cparts[-1 - n] == parts[-1 - n]:
                n += 1
            if n < 2 and n != len(cparts):
                continue
            if n > best_len:
                best, best_len = [cand], n
            elif n == best_len:
                best.append(cand)
        return best

    def file_count(self) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) FROM tree WHERE commit_id=?", (self._cid,)
        ).fetchone()
        return int(row[0])

    # -- definitions ---------------------------------------------------------
    def definitions(self, name: str) -> list[Located]:
        rows = self._db.execute(
            "SELECT p.path, d.name, d.kind, d.start, d.end, d.qual FROM defs d "
            "JOIN tree t ON t.blob_id=d.blob_id AND t.commit_id=? JOIN paths p ON p.id=t.path_id "
            "WHERE d.name=?",
            (self._cid, name),
        ).fetchall()
        return [Located(r[0], Definition(r[1], r[2], int(r[3]), int(r[4]), r[5])) for r in rows]

    def defs_in_file(self, path: str) -> list[Definition]:
        info = self.file(path)
        if info is None:
            return []
        return _defs_for_blob(self.store, info.blob)

    def functions_at(self, path: str, line: int) -> list[Definition]:
        """Functions whose span contains ``line``, innermost first."""
        found = [
            d
            for d in self.defs_in_file(path)
            if d.kind in FUNCTION_KINDS and d.start <= line <= d.end
        ]
        return sorted(found, key=lambda d: d.end - d.start)

    def macros_at(self, path: str, line: int) -> list[Definition]:
        return [
            d for d in self.defs_in_file(path) if d.kind == "macro" and d.start <= line <= d.end
        ]

    # -- other indexed versions ---------------------------------------------------
    def any_version_definition(self, name: str) -> tuple[str, str] | None:
        """(commit, path) of a definition of ``name`` in any indexed commit."""
        row = self._db.execute(
            "SELECT c.sha, p.path FROM defs d JOIN tree t ON t.blob_id=d.blob_id "
            "JOIN commits c ON c.id=t.commit_id JOIN paths p ON p.id=t.path_id "
            "WHERE d.name=? ORDER BY c.id DESC LIMIT 1",
            (name,),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def any_version_path(self, path: str) -> str | None:
        """Commit of any indexed version that has ``path``."""
        row = self._db.execute(
            "SELECT c.sha FROM paths p JOIN tree t ON t.path_id=p.id JOIN commits c ON c.id=t.commit_id "
            "WHERE p.path=? ORDER BY c.id DESC LIMIT 1",
            (path,),
        ).fetchone()
        return row[0] if row else None

    # -- identifier occurrences ------------------------------------------------
    def is_referenced(self, word: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM words w JOIN blob_words bw ON bw.word_id=w.id "
            "JOIN tree t ON t.blob_id=bw.blob_id AND t.commit_id=? WHERE w.word=? LIMIT 1",
            (self._cid, word),
        ).fetchone()
        return row is not None

    def files_referencing(self, word: str, limit: int = 50) -> list[str]:
        rows = self._db.execute(
            "SELECT p.path FROM words w JOIN blob_words bw ON bw.word_id=w.id "
            "JOIN tree t ON t.blob_id=bw.blob_id AND t.commit_id=? JOIN paths p ON p.id=t.path_id "
            "WHERE w.word=? LIMIT ?",
            (self._cid, word, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def candidate_files(self, words: Iterable[str], limit: int = 25) -> list[str]:
        """Files that mention most of ``words`` (for locating a quoted snippet)."""
        uniq = sorted(set(words))
        if not uniq:
            return []
        marks = ",".join("?" * len(uniq))
        rows = self._db.execute(
            "SELECT p.path, COUNT(*) AS hits FROM words w JOIN blob_words bw ON bw.word_id=w.id "  # noqa: S608
            "JOIN tree t ON t.blob_id=bw.blob_id AND t.commit_id=? JOIN paths p ON p.id=t.path_id "
            f"WHERE w.word IN ({marks}) GROUP BY p.path ORDER BY hits DESC, p.path LIMIT ?",
            (self._cid, *uniq, limit),
        ).fetchall()
        return [r[0] for r in rows]

    # -- content ---------------------------------------------------------------
    def read(self, path: str) -> bytes | None:
        info = self.file(path)
        if info is None:
            return None
        return _read_blob(self.repo.git_dir, info.blob)

    def comment_or_blank(self, path: str) -> set[int]:
        info = self.file(path)
        if info is None:
            return set()
        content = self.read(path) or b""
        return defs_mod.comment_or_blank_lines(info.lang, content)


def _defs_for_blob(store: Store, blob: str) -> list[Definition]:
    rows = store.db.execute(
        "SELECT d.name, d.kind, d.start, d.end, d.qual FROM defs d JOIN blobs b ON b.id=d.blob_id "
        "WHERE b.sha=?",
        (blob,),
    ).fetchall()
    return [Definition(r[0], r[1], int(r[2]), int(r[3]), r[4]) for r in rows]


@lru_cache(maxsize=512)
def _read_blob(git_dir: Path, blob: str) -> bytes:
    import subprocess

    from sloptriage.index.gitobj import _git_env

    proc = subprocess.run(
        ["git", f"--git-dir={git_dir}", "cat-file", "blob", blob],
        capture_output=True,
        env=_git_env(),
    )
    return proc.stdout if proc.returncode == 0 else b""


class IndexSet:
    """Opens indexes for any number of commits of one repository, sharing one store."""

    def __init__(self, repo: GitRepo, location: str, ignore: Iterable[str] = ()) -> None:
        self.repo = repo
        self.ignore = tuple(ignore)
        self.store = Store(cache_dir("index") / f"{repo_key(location)}.sqlite")
        self._open: dict[str, Index] = {}

    def get(self, commit: str) -> Index:
        idx = self._open.get(commit)
        if idx is None:
            cid = self.store.index_commit(self.repo, commit, self.ignore)
            idx = Index(self.store, self.repo, commit, cid)
            self._open[commit] = idx
        return idx

    def is_cached(self, commit: str) -> bool:
        return self.store.commit_id(commit) is not None

    def close(self) -> None:
        self.store.close()
