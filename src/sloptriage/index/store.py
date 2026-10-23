"""On-disk index cache: one SQLite file per repository.

Blob analysis (line count, definitions, identifiers) is content-addressed, so a
blob shared by many commits is parsed once. Each indexed commit adds only its
tree listing, keyed by commit SHA. Indexing a second tag of the same project
therefore parses just the files that changed.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path

from sloptriage.index import defs as defs_mod
from sloptriage.index.gitobj import GitRepo, TreeEntry

SCHEMA_VERSION = 3
MAX_TEXT_BYTES = 2_000_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS blobs(
  id INTEGER PRIMARY KEY, sha TEXT UNIQUE NOT NULL, lines INTEGER NOT NULL,
  lang TEXT, is_text INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS defs(
  blob_id INTEGER NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  start INTEGER NOT NULL, end INTEGER NOT NULL, qual TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS defs_name ON defs(name);
CREATE INDEX IF NOT EXISTS defs_blob ON defs(blob_id);
CREATE TABLE IF NOT EXISTS words(id INTEGER PRIMARY KEY, word TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS blob_words(
  word_id INTEGER NOT NULL, blob_id INTEGER NOT NULL, PRIMARY KEY(word_id, blob_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS paths(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, base TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS paths_base ON paths(base);
CREATE TABLE IF NOT EXISTS commits(
  id INTEGER PRIMARY KEY, sha TEXT UNIQUE NOT NULL, indexed_at REAL NOT NULL, seconds REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tree(
  commit_id INTEGER NOT NULL, path_id INTEGER NOT NULL, blob_id INTEGER NOT NULL,
  PRIMARY KEY(commit_id, path_id)) WITHOUT ROWID;
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path), timeout=120.0)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        version = self._schema_version()
        if version not in (None, SCHEMA_VERSION):
            self.db.close()
            path.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
            self.db = sqlite3.connect(str(path), timeout=120.0)
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)
        self.db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema', ?)", (str(SCHEMA_VERSION),)
        )
        self.db.commit()

    def _schema_version(self) -> int | None:
        try:
            row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        except sqlite3.OperationalError:
            return None
        return int(row[0]) if row else None

    def close(self) -> None:
        self.db.close()

    # -- writing ---------------------------------------------------------------
    def commit_id(self, sha: str) -> int | None:
        row = self.db.execute("SELECT id FROM commits WHERE sha=?", (sha,)).fetchone()
        return int(row[0]) if row else None

    def index_commit(self, repo: GitRepo, sha: str, ignore: Iterable[str] = ()) -> int:
        """Index one commit (no-op when it is already cached). Returns its row id."""
        existing = self.commit_id(sha)
        if existing is not None:
            return existing
        started = time.perf_counter()
        entries = [e for e in repo.ls_tree(sha) if not _ignored(e.path, ignore)]
        known = self._known_blobs({e.blob for e in entries})
        todo = [e for e in entries if e.blob not in known]
        seen_new: set[str] = set()
        cur = self.db.cursor()
        with repo.batch_reader() as reader:
            for entry in todo:
                if entry.blob in seen_new:
                    continue
                seen_new.add(entry.blob)
                self._analyse_blob(
                    cur, reader.read(entry.blob) if entry.size <= MAX_TEXT_BYTES else None, entry
                )
        blob_ids = self._known_blobs({e.blob for e in entries})
        cur.execute(
            "INSERT INTO commits(sha, indexed_at, seconds) VALUES(?, ?, 0)", (sha, time.time())
        )
        cid = int(cur.lastrowid or 0)
        rows = []
        for entry in entries:
            rows.append((cid, self._path_id(cur, entry.path), blob_ids[entry.blob]))
        cur.executemany(
            "INSERT OR IGNORE INTO tree(commit_id, path_id, blob_id) VALUES(?,?,?)", rows
        )
        cur.execute("UPDATE commits SET seconds=? WHERE id=?", (time.perf_counter() - started, cid))
        self.db.commit()
        return cid

    def _known_blobs(self, shas: set[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        items = list(shas)
        for i in range(0, len(items), 500):
            chunk = items[i : i + 500]
            marks = ",".join("?" * len(chunk))
            query = f"SELECT sha, id FROM blobs WHERE sha IN ({marks})"  # noqa: S608
            for sha, bid in self.db.execute(query, chunk):
                out[sha] = int(bid)
        return out

    def _path_id(self, cur: sqlite3.Cursor, path: str) -> int:
        row = cur.execute("SELECT id FROM paths WHERE path=?", (path,)).fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO paths(path, base) VALUES(?, ?)", (path, path.rsplit("/", 1)[-1]))
        return int(cur.lastrowid or 0)

    def _word_id(self, cur: sqlite3.Cursor, word: str, cache: dict[str, int]) -> int:
        wid = cache.get(word)
        if wid is not None:
            return wid
        row = cur.execute("SELECT id FROM words WHERE word=?", (word,)).fetchone()
        if row:
            wid = int(row[0])
        else:
            cur.execute("INSERT INTO words(word) VALUES(?)", (word,))
            wid = int(cur.lastrowid or 0)
        cache[word] = wid
        return wid

    _word_cache: dict[str, int] = {}

    def _analyse_blob(self, cur: sqlite3.Cursor, content: bytes | None, entry: TreeEntry) -> None:
        is_text = content is not None and b"\0" not in content[:8192]
        lang = defs_mod.language_for(entry.path) if is_text else None
        lines = 0
        if content is not None and is_text:
            lines = content.count(b"\n") + (0 if content.endswith(b"\n") or not content else 1)
        cur.execute(
            "INSERT INTO blobs(sha, lines, lang, is_text) VALUES(?,?,?,?)",
            (entry.blob, lines, lang, int(is_text)),
        )
        bid = int(cur.lastrowid or 0)
        if not is_text or content is None:
            return
        if lang is not None:
            try:
                found = defs_mod.definitions(lang, content)
            except Exception:  # noqa: BLE001 - a grammar failure must not stop indexing
                found = []
            cur.executemany(
                "INSERT INTO defs(blob_id, name, kind, start, end, qual) VALUES(?,?,?,?,?,?)",
                [(bid, d.name, d.kind, d.start, d.end, d.qual) for d in found],
            )
        words = defs_mod.identifiers(content)
        cur.executemany(
            "INSERT OR IGNORE INTO blob_words(word_id, blob_id) VALUES(?, ?)",
            [(self._word_id(cur, w, self._word_cache), bid) for w in words],
        )


def _ignored(path: str, patterns: Iterable[str]) -> bool:
    from fnmatch import fnmatch

    return any(fnmatch(path, pat) for pat in patterns)
