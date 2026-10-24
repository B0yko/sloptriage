"""The ``repro:`` section of ``.sloptriage.yml``.

Shape and unknown keys are checked by the generic validator in :mod:`sloptriage.config`; this
module adds the value checks and builds the dataclasses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sloptriage.repro.recipes.presets import PRESET_NAMES
from sloptriage.repro.runtime import Limits

RUNNERS = ("c", "cpp", "shell", "python", "input")
RUNTIMES = ("auto", "docker", "podman")

SCHEMA: dict[str, Any] = {
    "enabled": bool,
    "runtime": str,
    "runners": [str],
    "harness": str,
    "limits": {
        "timeout": int,
        "build_timeout": int,
        "memory": str,
        "cpus": float,
        "pids": int,
        "tmpfs": str,
        "output_bytes": int,
        "runs": int,
        "candidates": int,
    },
    "build": {
        "preset": str,
        "base_image": str,
        "packages": [str],
        "configure": [str],
        "build": [str],
        "install": [str],
        "link": [str],
        "env": {"*": str},
        "sanitizer_flags": [str],
        "requirements": [str],
    },
}


@dataclass
class BuildConfig:
    preset: str | None = None
    base_image: str | None = None
    packages: list[str] = field(default_factory=list)
    configure: list[str] | None = None
    build: list[str] | None = None
    install: list[str] | None = None
    link: list[str] | None = None
    env: dict[str, str] = field(default_factory=dict)
    sanitizer_flags: list[str] | None = None
    requirements: list[str] | None = None


@dataclass
class ReproConfig:
    enabled: bool = False
    runtime: str = "auto"
    runners: list[str] = field(default_factory=lambda: list(RUNNERS))
    harness: str | None = None
    limits: Limits = field(default_factory=Limits)
    build: BuildConfig = field(default_factory=BuildConfig)


_MEMORY_RE = re.compile(r"^[1-9]\d*[kmg]$", re.I)
_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/:@-]{0,200}$")
_PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,100}(=[\w.+:~-]+)?$")
_LINK_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,60}$")
_ENV_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,60}$")
_FLAG_RE = re.compile(r"^-[A-Za-z0-9_=,.+/:-]{1,100}$")


def parse_repro(doc: dict[str, Any], source: str, errors: list[str]) -> ReproConfig:
    """Build a :class:`ReproConfig` from an already shape-checked mapping."""
    cfg = ReproConfig()
    if not doc:
        return cfg
    cfg.enabled = bool(doc.get("enabled", False))
    cfg.runtime = doc.get("runtime", "auto")
    if cfg.runtime not in RUNTIMES:
        errors.append(f"{source}: repro.runtime: expected one of {', '.join(RUNTIMES)}")
    if "runners" in doc:
        cfg.runners = list(doc["runners"])
        for i, name in enumerate(cfg.runners):
            if name not in RUNNERS:
                errors.append(
                    f"{source}: repro.runners[{i}]: {name!r} is not one of {', '.join(RUNNERS)}"
                )
    cfg.harness = doc.get("harness")
    if cfg.harness is not None and "{input}" not in cfg.harness:
        errors.append(f"{source}: repro.harness: must contain the {{input}} placeholder")
    lim = doc.get("limits", {})
    limits = Limits()
    for key in ("timeout", "build_timeout", "pids", "output_bytes", "runs", "candidates"):
        if key in lim:
            value = lim[key]
            if value < 1:
                errors.append(f"{source}: repro.limits.{key}: must be at least 1")
            setattr(limits, key, value)
    if "cpus" in lim:
        if lim["cpus"] <= 0 or lim["cpus"] > 16:
            errors.append(f"{source}: repro.limits.cpus: must be above 0 and at most 16")
        limits.cpus = float(lim["cpus"])
    for key in ("memory", "tmpfs"):
        if key in lim:
            if not _MEMORY_RE.fullmatch(lim[key]):
                errors.append(f"{source}: repro.limits.{key}: expected a size like 512m or 2g")
            setattr(limits, key, lim[key].lower())
    if limits.runs > 10:
        errors.append(f"{source}: repro.limits.runs: at most 10")
    if limits.candidates > 10:
        errors.append(f"{source}: repro.limits.candidates: at most 10")
    cfg.limits = limits
    b = doc.get("build", {})
    build = BuildConfig(
        preset=b.get("preset"),
        base_image=b.get("base_image"),
        packages=list(b.get("packages", [])),
        configure=list(b["configure"]) if "configure" in b else None,
        build=list(b["build"]) if "build" in b else None,
        install=list(b["install"]) if "install" in b else None,
        link=list(b["link"]) if "link" in b else None,
        env=dict(b.get("env", {})),
        sanitizer_flags=list(b["sanitizer_flags"]) if "sanitizer_flags" in b else None,
        requirements=list(b["requirements"]) if "requirements" in b else None,
    )
    if build.preset is not None and build.preset not in PRESET_NAMES:
        errors.append(
            f"{source}: repro.build.preset: {build.preset!r} is not one of {', '.join(PRESET_NAMES)}"
        )
    if build.base_image is not None and not _IMAGE_RE.fullmatch(build.base_image):
        errors.append(f"{source}: repro.build.base_image: not a valid image reference")
    for i, pkg in enumerate(build.packages):
        if not _PACKAGE_RE.fullmatch(pkg):
            errors.append(f"{source}: repro.build.packages[{i}]: {pkg!r} is not a package name")
    for i, lib in enumerate(build.link or []):
        if not _LINK_RE.fullmatch(lib):
            errors.append(f"{source}: repro.build.link[{i}]: {lib!r} is not a library name")
    for key in build.env:
        if not _ENV_KEY_RE.fullmatch(key):
            errors.append(f"{source}: repro.build.env.{key}: not an environment variable name")
    for i, flag in enumerate(build.sanitizer_flags or []):
        if not _FLAG_RE.fullmatch(flag):
            errors.append(f"{source}: repro.build.sanitizer_flags[{i}]: {flag!r} is not a flag")
    for key, items in (
        ("configure", build.configure),
        ("build", build.build),
        ("install", build.install),
    ):
        for i, cmd in enumerate(items or []):
            if "\n" in cmd or "\r" in cmd:
                errors.append(f"{source}: repro.build.{key}[{i}]: a command must be a single line")
    for key, value in build.env.items():
        if "\n" in value or "\r" in value:
            errors.append(f"{source}: repro.build.env.{key}: must be a single line")
    cfg.build = build
    return cfg
