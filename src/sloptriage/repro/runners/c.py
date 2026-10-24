"""C and C++ PoCs: compiled against the built project with the recipe's sanitizer flags."""

from __future__ import annotations

import re
import shlex
from typing import TYPE_CHECKING

from sloptriage.repro.recipes import Recipe

if TYPE_CHECKING:
    from sloptriage.repro.runners import Prepared


def prepare(name: str, data: bytes, kind: str, recipe: Recipe, marker: str) -> Prepared:
    from sloptriage.repro.runners import COMPILE_FAILED, Prepared

    out = name.rsplit(".", 1)[0]
    compiler = recipe.cxx if kind == "cpp" else recipe.cc
    # The project is built with the recipe's flags. The PoC is the reporter's own code, so it is
    # compiled the way a reporter would: same sanitizers, no optimisation. At -O1 and above the
    # compiler deletes stores that nothing reads, and the crash can disappear with them.
    poc_flags = [f for f in recipe.sanitizer_flags if not re.fullmatch(r"-O[0-3sgz]?", f)]
    flags = " ".join(shlex.quote(f) for f in [*poc_flags, "-O0"])
    libs = " ".join(f"-l{shlex.quote(lib)}" for lib in recipe.link)
    prefix = recipe.prefix
    cmd = (
        f"{compiler} {flags} -I{prefix}/include {shlex.quote(name)} -o {shlex.quote(out)} "
        f"-L{prefix}/lib -L{prefix}/lib64 -Wl,-rpath,{prefix}/lib -Wl,-rpath,{prefix}/lib64 "
        f"{libs} -lm > compile-{out}.log 2>&1 || "
        f'{{ cat compile-{out}.log >&2; echo "sloptriage-compile-failed:{marker}" >&2; '
        f"exit {COMPILE_FAILED}; }}"
    )
    return Prepared({name: data}, cmd, f"./{out}")
