"""The bundled demo: two small projects with known bugs and 60 labelled reports.

Each project ships as version snapshots (``demo/projects/<name>/v<version>/``).
``materialize`` turns them into a git repository with one commit and one tag
per version, in the user cache, with fixed authors and dates so the commit
SHAs are the same on every machine.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sloptriage.paths import bundled, cache_dir

PROJECTS = ("parsekit", "kvconf")
_DATES = [
    "2025-03-01T10:00:00Z",
    "2025-06-01T10:00:00Z",
    "2025-09-01T10:00:00Z",
    "2025-12-01T10:00:00Z",
]


@dataclass(frozen=True)
class DemoReport:
    file: str
    path: Path
    label: str
    project: str
    claimed_version: str | None
    failure_modes: tuple[str, ...]
    poc: str
    poc_reproduces: bool
    bug: str | None


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(x) for x in name.lstrip("v").split("."))


def project_versions(project: str) -> list[Path]:
    root = bundled("demo", "projects", project)
    return sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name.startswith("v")),
        key=lambda p: _version_key(p.name),
    )


def _content_hash(project: str) -> str:
    h = hashlib.sha256()
    for version in project_versions(project):
        for path in sorted(version.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                h.update(str(path.relative_to(version.parent)).encode())
                h.update(path.read_bytes())
    return h.hexdigest()


def _git(repo: Path, *args: str, date: str | None = None) -> None:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(repo),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "demo maintainers",
        "GIT_AUTHOR_EMAIL": "maintainers@example.com",
        "GIT_COMMITTER_NAME": "demo maintainers",
        "GIT_COMMITTER_EMAIL": "maintainers@example.com",
    }
    if date:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "init.defaultBranch=main",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        check=True,
        capture_output=True,
        env=env,
    )


def materialize(project: str) -> Path:
    """Return the path of the demo project's git repository, building it when needed."""
    if project not in PROJECTS:
        raise ValueError(f"unknown demo project {project!r}")
    target = cache_dir("demo") / project
    stamp = target / ".git" / "sloptriage-demo-hash"
    digest = _content_hash(project)
    if stamp.exists() and stamp.read_text() == digest:
        return target
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    _git(target, "init", "-q")
    for i, version in enumerate(project_versions(project)):
        for child in target.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        for src in sorted(version.rglob("*")):
            if src.is_file() and "__pycache__" not in src.parts:
                dest = target / src.relative_to(version)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
        date = _DATES[min(i, len(_DATES) - 1)]
        _git(target, "add", "-A")
        _git(target, "commit", "-q", "-m", f"Release {version.name}", date=date)
        _git(target, "tag", version.name)
    stamp.write_text(digest)
    return target


def reports() -> list[DemoReport]:
    root = bundled("demo", "reports")
    doc: dict[str, Any] = json.loads((root / "labels.json").read_text(encoding="utf-8"))
    out = []
    for item in doc["reports"]:
        out.append(
            DemoReport(
                file=item["file"],
                path=root / item["file"],
                label=item["label"],
                project=item["project"],
                claimed_version=item.get("claimed_version"),
                failure_modes=tuple(item.get("failure_modes", [])),
                poc=item.get("poc", "none"),
                poc_reproduces=bool(item.get("poc_reproduces")),
                bug=item.get("bug"),
            )
        )
    return out


def config_path(project: str) -> Path:
    return bundled("examples", project, ".sloptriage.yml")
