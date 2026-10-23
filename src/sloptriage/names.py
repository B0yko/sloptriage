"""Bundled name lists: language keywords, standard libraries, known dependencies, English words."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import cache

from sloptriage.paths import package_data


def _read(name: str) -> list[str]:
    words: list[str] = []
    for line in package_data("names", name).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        words.extend(line.split())
    return words


@dataclass(frozen=True)
class NameLists:
    stdlib: frozenset[str]
    english: frozenset[str]
    dep_names: frozenset[str]
    dep_prefixes: tuple[str, ...]
    products: frozenset[str] = field(default=frozenset())
    extra_external: tuple[str, ...] = field(default=())

    def is_common(self, name: str) -> bool:
        """An ordinary English or generic programming word."""
        low = name.lower()
        if low in self.products:
            return True
        return low in self.english and (name.islower() or name.istitle())

    def is_ignored(self, name: str) -> bool:
        """Never a claim about the project (keyword, standard library, English word)."""
        return name in self.stdlib or self.is_common(name)

    def is_external(self, name: str) -> bool:
        """Known third-party or standard name: a citation of it is neutral."""
        if name in self.stdlib or name in self.dep_names:
            return True
        if any(name.startswith(p) for p in self.dep_prefixes):
            return True
        return any(fnmatchcase(name, pat) for pat in self.extra_external)

    def with_external(self, patterns: tuple[str, ...]) -> NameLists:
        return NameLists(
            self.stdlib, self.english, self.dep_names, self.dep_prefixes, self.products, patterns
        )


@cache
def load_names() -> NameLists:
    stdlib = set(_read("c.txt")) | set(_read("python.txt")) | set(_read("other.txt"))
    deps = _read("deps.txt")
    return NameLists(
        stdlib=frozenset(stdlib),
        english=frozenset(w.lower() for w in _read("english.txt")),
        dep_names=frozenset(d for d in deps if not d.endswith("*")),
        dep_prefixes=tuple(d[:-1] for d in deps if d.endswith("*")),
        products=frozenset(w.lower() for w in _read("products.txt")),
    )
