"""Build recipes: from ``repro.build`` to the two Dockerfiles that produce the sandbox image.

Stage 1 (the image stage, with network) installs the toolchain and build dependencies. Its inputs
are the recipe and, for Python, the dependency names declared in the project's manifests at the
commit being built. Nothing from the report enters it. Stage 2 (the project stage, built with
``--network none``) copies the source of that commit into the image and builds it with sanitizers.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shlex
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from sloptriage.repro.errors import ReproError
from sloptriage.repro.recipes.presets import (
    PREFIX,
    PRESET_NAMES,
    PRESETS,
    SANITIZER_FLAGS,
    SOURCE_DIR,
)

if TYPE_CHECKING:
    from sloptriage.repro.config import ReproConfig

__all__ = [
    "PRESET_NAMES",
    "Recipe",
    "base_dockerfile",
    "declared_requirements",
    "project_dockerfile",
    "recipe_from_config",
    "recipe_hash",
]

DOCKERFILE = "Dockerfile.sloptriage"
TEMPLATE_VERSION = 1  # bump when the generated Dockerfiles change, so cached images are rebuilt
UID = 10001


@dataclass(frozen=True)
class Recipe:
    preset: str
    base_image: str
    packages: tuple[str, ...]
    sanitizer_flags: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    configure: tuple[str, ...]
    build: tuple[str, ...]
    install: tuple[str, ...]
    link: tuple[str, ...]
    requirements: tuple[str, ...]
    python: bool = False
    prefix: str = PREFIX
    source_dir: str = SOURCE_DIR
    cc: str = "cc"
    cxx: str = "c++"


def recipe_from_config(conf: ReproConfig, project: str) -> Recipe:
    b = conf.build
    preset = PRESETS.get(b.preset or "")
    packages: tuple[str, ...]
    if preset is None:
        if not (b.base_image and b.install is not None):
            raise ReproError(
                "no build recipe: set repro.build.preset to one of "
                f"{', '.join(PRESET_NAMES)}, or give repro.build.base_image and repro.build.install"
            )
        configure, build, install = b.configure or [], b.build or [], b.install or []
        base, packages, python = b.base_image, (), False
    else:
        configure = b.configure if b.configure is not None else list(preset.configure)
        build = b.build if b.build is not None else list(preset.build)
        install = b.install if b.install is not None else list(preset.install)
        base, packages, python = b.base_image or preset.base_image, preset.packages, preset.python
    merged = tuple(dict.fromkeys([*packages, *b.packages]))
    flags = (
        tuple(b.sanitizer_flags)
        if b.sanitizer_flags is not None
        else (() if python else SANITIZER_FLAGS)
    )
    return Recipe(
        preset=b.preset or "custom",
        base_image=base,
        packages=merged,
        sanitizer_flags=flags,
        env=tuple(sorted(b.env.items())),
        configure=tuple(configure),
        build=tuple(build),
        install=tuple(install),
        link=tuple(b.link) if b.link is not None else (project,),
        requirements=tuple(b.requirements) if b.requirements is not None else ("requirements.txt",),
        python=python,
    )


def recipe_hash(recipe: Recipe) -> str:
    blob = json.dumps(
        {"recipe": asdict(recipe), "template": TEMPLATE_VERSION}, sort_keys=True
    ).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


# -- Dockerfiles ---------------------------------------------------------------------------------
_USER = (
    f"RUN useradd --uid {UID} --user-group --no-create-home --shell /usr/sbin/nologin sloptriage"
)


def base_dockerfile(recipe: Recipe, manifests: Sequence[str] | None = None) -> str:
    """Stage 1. ``manifests`` (Python only) are written to ``requirements.txt`` in its context."""
    lines = [f"FROM {recipe.base_image}"]
    if recipe.packages:
        lines += [
            "RUN apt-get update \\",
            " && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
            + " ".join(recipe.packages)
            + " \\",
            " && rm -rf /var/lib/apt/lists/*",
        ]
    lines.append(_USER)
    if recipe.python:
        lines += [
            "COPY requirements.txt /deps/requirements.txt",
            "RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r /deps/requirements.txt \\",
            " && python -m pip install --no-cache-dir --no-index --find-links /wheels "
            "-r /deps/requirements.txt",
        ]
    return "\n".join(lines) + "\n"


def _run(recipe: Recipe, command: str) -> str:
    if recipe.python:
        return f"RUN {command}"
    exports = [
        "ASAN_OPTIONS=detect_leaks=0",
        f"SAN_FLAGS={shlex.quote(' '.join(recipe.sanitizer_flags))}",
        'CFLAGS="$SAN_FLAGS"',
        'CXXFLAGS="$SAN_FLAGS"',
        'LDFLAGS="$SAN_FLAGS"',
        *(f"{k}={shlex.quote(v)}" for k, v in recipe.env),
    ]
    return f"RUN export {' '.join(exports)} && {command}"


def project_dockerfile(recipe: Recipe, base_tag: str, project: str) -> str:
    """Stage 2: build the checked-out source with sanitizers. Built with ``--network none``."""
    lines = [f"FROM {base_tag}", f"COPY . {recipe.source_dir}", f"WORKDIR {recipe.source_dir}"]
    lines += [_run(recipe, cmd) for cmd in (*recipe.configure, *recipe.build, *recipe.install)]
    lines.append(
        f"RUN mkdir -p {recipe.prefix} && chmod -R a+rX {recipe.source_dir} {recipe.prefix}"
    )
    if not recipe.python:
        lines.append(
            f'ENV PATH="{recipe.prefix}/bin:${{PATH}}" '
            f'LD_LIBRARY_PATH="{recipe.prefix}/lib:{recipe.prefix}/lib64"'
        )
    lines += ["WORKDIR /", f"USER {UID}:{UID}"]
    return "\n".join(lines) + "\n"


# -- declared dependencies (Python) -------------------------------------------------------------------
_REQ_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?"
    r"(?:\s*(?:===|==|>=|<=|~=|!=|<|>)\s*[A-Za-z0-9.*+!_-]+(?:\s*,\s*(?:===|==|>=|<=|~=|!=|<|>)\s*[A-Za-z0-9.*+!_-]+)*)?"
    r"(?:\s*;\s*[\w .'\"<>=!~,()-]+)?$"
)


def _clean_requirement(line: str) -> str | None:
    text = line.split(" #", 1)[0].strip()
    if not text or text.startswith(("#", "-", ".", "/")) or "://" in text or "@" in text:
        return None
    return text if _REQ_RE.match(text) else None


def declared_requirements(files: Mapping[str, bytes], recipe: Recipe) -> list[str]:
    """Dependency names declared by the manifests; no project code is run to learn them."""
    found: set[str] = set()
    for name, data in files.items():
        if any(fnmatch.fnmatch(name, pat) for pat in recipe.requirements):
            for line in data.decode("utf-8", errors="replace").splitlines():
                req = _clean_requirement(line)
                if req:
                    found.add(req)
    raw = files.get("pyproject.toml")
    if raw is not None:
        try:
            doc = tomllib.loads(raw.decode("utf-8", errors="replace"))
        except tomllib.TOMLDecodeError:
            doc = {}
        for entry in doc.get("build-system", {}).get("requires", []) or []:
            req = _clean_requirement(str(entry))
            if req:
                found.add(req)
        for entry in doc.get("project", {}).get("dependencies", []) or []:
            req = _clean_requirement(str(entry))
            if req:
                found.add(req)
    return sorted(found)
