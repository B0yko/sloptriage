"""Read git objects directly, without a checkout, so bare clones work."""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from sloptriage.paths import cache_dir


class GitError(RuntimeError):
    """A git command failed in a way the caller cannot recover from."""


@dataclass(frozen=True)
class TreeEntry:
    path: str
    blob: str
    size: int


_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_URL_RE = re.compile(r"^(https://|git@|ssh://|git://|file://)")


def is_url(value: str) -> bool:
    return bool(_URL_RE.match(value))


class GitRepo:
    """Thin wrapper around the git CLI for one repository (bare or not)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        out = self._run("rev-parse", "--git-dir", check=False)
        if out is None:
            raise GitError(f"{path} is not a git repository")
        git_dir = Path(out.strip())
        self.git_dir = git_dir if git_dir.is_absolute() else (path / git_dir).resolve()

    # -- plumbing ---------------------------------------------------------
    def _run(self, *args: str, check: bool = True, input_text: str | None = None) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            input=input_text,
            env=_git_env(),
        )
        if proc.returncode != 0:
            if check:
                raise GitError(f"git {' '.join(args[:3])} failed: {proc.stderr.strip()[:300]}")
            return None
        return proc.stdout

    def run(self, *args: str) -> str:
        out = self._run(*args)
        assert out is not None
        return out

    def try_run(self, *args: str) -> str | None:
        return self._run(*args, check=False)

    # -- refs ---------------------------------------------------------------
    def resolve_commit(self, ref: str) -> str | None:
        """Return the full commit SHA for a ref, tag or (abbreviated) SHA."""
        if ref.startswith("-"):
            return None
        out = self.try_run(
            "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"
        )
        return out.strip() if out else None

    def tags(self) -> list[str]:
        out = self.try_run("for-each-ref", "--format=%(refname:short)", "refs/tags")
        return [t for t in (out or "").splitlines() if t]

    def tag_dates(self) -> dict[str, str]:
        """Tag name -> ISO committer date of the tagged commit."""
        out = self.try_run(
            "for-each-ref",
            "--format=%(refname:short)%09%(*committerdate:iso-strict)%09%(committerdate:iso-strict)",
            "refs/tags",
        )
        result: dict[str, str] = {}
        for line in (out or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                result[parts[0]] = parts[1] or parts[2]
        return result

    def tag_commits(self) -> dict[str, str]:
        """Commit SHA -> tag name (first tag wins), peeling annotated tags."""
        out = self.try_run(
            "for-each-ref", "--format=%(objectname) %(*objectname) %(refname:short)", "refs/tags"
        )
        result: dict[str, str] = {}
        for line in (out or "").splitlines():
            parts = line.split(" ")
            if len(parts) == 3:
                sha = parts[1] or parts[0]
                result.setdefault(sha, parts[2])
        return result

    def default_branch(self) -> str:
        out = self.try_run("symbolic-ref", "--quiet", "--short", "HEAD")
        if out and out.strip():
            return out.strip()
        return "HEAD"

    def commit_before(self, ref: str, iso_date: str) -> str | None:
        out = self.try_run("rev-list", "-1", f"--before={iso_date}", ref, "--")
        return out.strip() if out and out.strip() else None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        proc = subprocess.run(
            ["git", "-C", str(self.path), "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
            env=_git_env(),
        )
        return proc.returncode == 0

    def tags_containing(self, commit: str) -> list[str]:
        out = self.try_run("tag", "--contains", commit)
        return [t for t in (out or "").splitlines() if t]

    def commit_date(self, commit: str) -> str:
        return self.run("show", "-s", "--format=%cI", commit).strip()

    def remote_url(self) -> str | None:
        out = self.try_run("config", "--get", "remote.origin.url")
        return out.strip() if out and out.strip() else None

    # -- trees and blobs ------------------------------------------------------
    def ls_tree(self, commit: str) -> list[TreeEntry]:
        out = self.run("ls-tree", "-r", "-l", "-z", "--full-tree", commit)
        entries: list[TreeEntry] = []
        for record in out.split("\0"):
            if not record:
                continue
            meta, _, path = record.partition("\t")
            parts = meta.split()
            if len(parts) != 4 or parts[1] != "blob":
                continue  # submodules (commit) and symlinks are kept out
            if parts[0] == "120000":
                continue
            size = int(parts[3]) if parts[3].isdigit() else 0
            entries.append(TreeEntry(path=path, blob=parts[2], size=size))
        return entries

    def cat_blob(self, blob: str) -> bytes:
        proc = subprocess.run(
            ["git", "-C", str(self.path), "cat-file", "blob", blob],
            capture_output=True,
            env=_git_env(),
        )
        if proc.returncode != 0:
            raise GitError(f"cannot read blob {blob}")
        return proc.stdout

    def batch_reader(self) -> BlobReader:
        return BlobReader(self)

    def grep_files(self, commit: str, word: str, limit: int = 20) -> list[str]:
        """Paths at ``commit`` that contain ``word`` as a whole word."""
        out = self.try_run("grep", "-l", "-w", "-F", "-I", "-e", word, commit, "--")
        if not out:
            return []
        prefix = f"{commit}:"
        files = [
            line[len(prefix) :] if line.startswith(prefix) else line for line in out.splitlines()
        ]
        return files[:limit]

    def path_history(self, path: str, limit: int = 1) -> list[str]:
        out = self.try_run("log", "--all", f"-{limit}", "--format=%H", "--", path)
        return [x for x in (out or "").split() if x]


class BlobReader:
    """One long-lived ``git cat-file --batch`` process for fast blob reads."""

    def __init__(self, repo: GitRepo) -> None:
        self._proc = subprocess.Popen(
            ["git", "-C", str(repo.path), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=_git_env(),
        )
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._in: IO[bytes] = self._proc.stdin
        self._out: IO[bytes] = self._proc.stdout

    def read(self, blob: str) -> bytes | None:
        self._in.write(blob.encode("ascii") + b"\n")
        self._in.flush()
        header = self._out.readline().decode("ascii", "replace").split()
        if len(header) != 3 or header[1] != "blob":
            return None
        size = int(header[2])
        data = self._out.read(size)
        self._out.read(1)  # trailing newline
        return data

    def close(self) -> None:
        if self._proc.poll() is None:
            self._in.close()
            self._proc.wait(timeout=10)

    def __enter__(self) -> BlobReader:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def iter_blobs(self, blobs: list[str]) -> Iterator[tuple[str, bytes | None]]:
        for blob in blobs:
            yield blob, self.read(blob)


def _git_env() -> dict[str, str]:
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["LC_ALL"] = "C"
    return env


def repo_key(location: str) -> str:
    """Stable cache key for a repository path or URL."""
    norm = location.rstrip("/")
    if norm.endswith(".git"):
        norm = norm[:-4]
    tail = re.sub(r"[^A-Za-z0-9._-]+", "_", norm.split("/")[-1])[:40] or "repo"
    return f"{tail}-{hashlib.sha256(norm.encode()).hexdigest()[:12]}"


def open_repo(location: str, *, update: bool = False) -> GitRepo:
    """Open a local repository, or make/refresh a bare clone of a URL in the cache.

    Only URLs given by the user (CLI flag or config) reach this function; nothing
    is ever cloned from a URL found inside a report.
    """
    if not is_url(location):
        path = Path(location).expanduser().resolve()
        if not path.exists():
            raise GitError(f"repository path {path} does not exist")
        return GitRepo(path)
    target = cache_dir("repos") / f"{repo_key(location)}.git"
    if not (target / "HEAD").exists():
        proc = subprocess.run(
            ["git", "clone", "--bare", "--quiet", "--", location, str(target)],
            capture_output=True,
            text=True,
            env=_git_env(),
        )
        if proc.returncode != 0:
            raise GitError(f"cannot clone {location}: {proc.stderr.strip()[:300]}")
        update = False
    repo = GitRepo(target)
    if update:
        repo.try_run(
            "fetch", "--quiet", "--tags", "--prune", "origin", "+refs/heads/*:refs/heads/*"
        )
    return repo


def looks_like_sha(value: str) -> bool:
    return bool(_SHA_RE.match(value))
