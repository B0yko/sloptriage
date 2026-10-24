"""Shell PoCs: command lines that invoke the project's binaries."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sloptriage.repro.runners import Prepared

_PROMPT_RE = re.compile(r"^\s*\$ (.*)$")


def transcript_commands(text: str) -> str:
    """A terminal transcript (its first line starts with ``$ ``) keeps only the prompted lines.

    Anything else, including a script that has ``$`` at the start of some line, is unchanged.
    """
    lines = text.splitlines()
    first = next((ln for ln in lines if ln.strip()), "")
    if not _PROMPT_RE.match(first):
        return text
    prompted = [m.group(1) for ln in lines if (m := _PROMPT_RE.match(ln))]
    return "\n".join(prompted) + "\n"


def prepare(name: str, data: bytes) -> Prepared:
    from sloptriage.repro.runners import Prepared

    text = data.decode("utf-8", errors="replace")
    body = transcript_commands(text)
    payload = data if body == text else body.encode("utf-8")
    return Prepared({name: payload}, "", f"bash -e -o pipefail ./{name}")
