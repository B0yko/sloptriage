"""Filesystem locations: the user cache and data bundled with the package."""

from __future__ import annotations

import os
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent.parent


def cache_dir(*parts: str) -> Path:
    """Return ``${XDG_CACHE_HOME:-~/.cache}/sloptriage/<parts>`` and create it."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    path = Path(base) / "sloptriage"
    for part in parts:
        path = path / part
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled(*parts: str) -> Path:
    """Locate data shipped with the package.

    In a wheel, repository-level data directories (``schemas/``, ``demo/``,
    ``bench/manifest/``) are force-included under ``sloptriage/_bundled/``.
    In a source checkout they are read from the repository root.
    """
    inside = _PKG_DIR / "_bundled"
    candidate = inside.joinpath(*parts)
    if candidate.exists():
        return candidate
    return _REPO_ROOT.joinpath(*parts)


def package_data(*parts: str) -> Path:
    """Data that lives inside the package source tree (name lists, recipes)."""
    return _PKG_DIR.joinpath("data", *parts)
