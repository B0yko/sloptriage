"""Sandboxed reproduction of a report's PoC (opt-in: ``--repro`` or ``repro.enabled``).

The public names load lazily, so importing the configuration does not pull in the whole module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sloptriage.repro.engine import commit_is_buildable, run_reproduction
    from sloptriage.repro.errors import ReproError

__all__ = ["ReproError", "commit_is_buildable", "run_reproduction"]


def __getattr__(name: str) -> Any:
    if name in ("commit_is_buildable", "run_reproduction"):
        from sloptriage.repro import engine

        return getattr(engine, name)
    if name == "ReproError":
        from sloptriage.repro.errors import ReproError

        return ReproError
    raise AttributeError(name)
