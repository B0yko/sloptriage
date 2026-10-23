"""${name} interpolation between configuration values."""

from __future__ import annotations

import os
import re
from typing import Dict

_REF = re.compile(r"\$\{([A-Za-z0-9_.:-]+)\}")


def _lookup(name: str, values: Dict[str, str]) -> str:
    if name.startswith("env:"):
        return os.environ.get(name[4:], "")
    if name not in values:
        raise KeyError(f"undefined reference ${{{name}}}")
    return values[name]


def _expand(value: str, values: Dict[str, str]) -> str:
    def replace(match: "re.Match[str]") -> str:
        return _expand(_lookup(match.group(1), values), values)

    return _REF.sub(replace, value)


def interpolate(values: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of ``values`` with every ${name} reference expanded."""
    return {key: _expand(value, values) for key, value in values.items()}
