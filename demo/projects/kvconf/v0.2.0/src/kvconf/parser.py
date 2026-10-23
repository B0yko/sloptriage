"""Parse kvconf text into a flat mapping of dotted keys."""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from kvconf.interp import interpolate

MAX_INCLUDE_DEPTH = 8


class ConfigError(ValueError):
    """Raised for malformed configuration text."""

    def __init__(self, message: str, source: str = "<string>", line: int = 0) -> None:
        super().__init__(f"{source}:{line}: {message}")
        self.source = source
        self.line = line


def _strip_comment(line: str) -> str:
    out = []
    quote = None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "#;":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _join_continuations(lines: List[str]) -> List[str]:
    joined: List[str] = []
    buf = ""
    for line in lines:
        if line.endswith("\\"):
            buf += line[:-1]
            continue
        joined.append(buf + line)
        buf = ""
    if buf:
        joined.append(buf)
    return joined


def parse_lines(
    text: str,
    source: str = "<string>",
    base_dir: Optional[str] = None,
    depth: int = 0,
) -> Dict[str, str]:
    if depth > MAX_INCLUDE_DEPTH:
        raise ConfigError("includes nested too deeply", source)
    values: Dict[str, str] = {}
    section = ""
    for number, raw in enumerate(_join_continuations(text.splitlines()), start=1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section:
                raise ConfigError("empty section name", source, number)
            continue
        if line.startswith("@include "):
            target = _unquote(line[len("@include ") :].strip())
            path = os.path.join(base_dir or ".", target)
            with open(path, encoding="utf-8") as handle:
                values.update(parse_lines(handle.read(), path, os.path.dirname(path), depth + 1))
            continue
        if "=" not in line:
            raise ConfigError(f"expected key = value, got {line!r}", source, number)
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError("empty key", source, number)
        full = f"{section}.{key}" if section else key
        values[full] = _unquote(value.strip())
    return values


def loads(text: str, source: str = "<string>", base_dir: Optional[str] = None) -> Dict[str, str]:
    """Parse configuration text and resolve ${name} references."""
    return interpolate(parse_lines(text, source, base_dir))


def load(path: str) -> Dict[str, str]:
    with open(path, encoding="utf-8") as handle:
        return loads(handle.read(), path, os.path.dirname(os.path.abspath(path)))
