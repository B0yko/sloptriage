"""Command line interface: print a configuration file as key = value lines."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from kvconf.parser import ConfigError, load


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kvconf", description="Read a kvconf file.")
    parser.add_argument("path")
    parser.add_argument("--get", metavar="KEY", help="print one value")
    args = parser.parse_args(argv)
    try:
        values = load(args.path)
    except (ConfigError, KeyError, OSError) as exc:
        print(f"kvconf: {exc}", file=sys.stderr)
        return 1
    if args.get:
        if args.get not in values:
            print(f"kvconf: no such key: {args.get}", file=sys.stderr)
            return 1
        print(values[args.get])
        return 0
    for key in sorted(values):
        print(f"{key} = {values[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
