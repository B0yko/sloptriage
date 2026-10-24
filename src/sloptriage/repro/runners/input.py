"""Input PoCs: a decoded data block fed to the harness command from the config."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sloptriage.repro.runners import Prepared

INPUT_PATH = "/work/poc/input.bin"


def prepare(name: str, data: bytes, harness: str) -> Prepared:
    from sloptriage.repro.runners import Prepared

    command = harness.replace("{input}", shlex.quote(INPUT_PATH))
    return Prepared({name: data}, "", f"sh -c {shlex.quote(command)}")
