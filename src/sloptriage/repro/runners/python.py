"""Python PoCs: run with the project installed in the image."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sloptriage.repro.runners import Prepared


def prepare(name: str, data: bytes) -> Prepared:
    from sloptriage.repro.runners import Prepared

    return Prepared({name: data}, "", f"python3 -X faulthandler {name}")
