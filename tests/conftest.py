from __future__ import annotations

import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


class _BlockedSocket(socket.socket):
    def connect(self, address: object) -> None:  # type: ignore[override]
        if self.family == socket.AF_UNIX:
            return super().connect(address)  # type: ignore[arg-type]
        raise RuntimeError(f"network access blocked in tests (connect to {address!r}); mark the test 'network'")

    def connect_ex(self, address: object) -> int:  # type: ignore[override]
        if self.family == socket.AF_UNIX:
            return super().connect_ex(address)  # type: ignore[arg-type]
        raise RuntimeError(f"network access blocked in tests (connect to {address!r}); mark the test 'network'")


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if request.node.get_closest_marker("network") is None:
        monkeypatch.setattr(socket, "socket", _BlockedSocket)
        monkeypatch.setattr(
            socket,
            "create_connection",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network access blocked in tests")),
        )
    yield


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path_factory.getbasetemp() / "xdg-cache"))


def git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": "2024-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2024-01-01T00:00:00Z",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(repo),
    }
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True, env=env,
    ).stdout


def make_repo(root: Path, versions: list[tuple[str, dict[str, str]]], dates: list[str] | None = None) -> Path:
    """Create a git repo with one commit + tag per (tag, files) snapshot."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    for i, (tag, files) in enumerate(versions):
        for existing in [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]:
            existing.unlink()
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        git(root, "add", "-A")
        date = (dates or [])[i] if dates and i < len(dates) else f"2024-0{i + 1}-01T00:00:00Z"
        subprocess.run(
            ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-q", "-m", f"release {tag}"],
            check=True, capture_output=True,
            env={"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T",
                 "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
                 "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(root)},
        )
        if tag:
            git(root, "tag", tag)
    return root
