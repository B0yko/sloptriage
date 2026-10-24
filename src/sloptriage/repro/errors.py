"""Errors raised by the reproduction module."""

from __future__ import annotations


class ReproError(RuntimeError):
    """Reproduction could not run (no container runtime, no recipe, a broken sandbox).

    These are infrastructure problems, never a statement about the report.
    """
