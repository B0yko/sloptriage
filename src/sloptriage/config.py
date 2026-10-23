"""``.sloptriage.yml``: loading and hand-written validation.

Every error names the file and the key path, and unknown keys are errors too,
so a typo never silently falls back to a default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sloptriage.versions import PRESETS

DEFAULT_LABELS = {
    "refs_verified": "triage:refs-verified",
    "refs_thin": "triage:refs-thin",
    "refs_mixed": "triage:refs-mixed",
    "refs_failed": "triage:refs-failed",
    "needs_version": "triage:needs-version",
    "needs_poc": "triage:needs-poc",
}
LANGUAGES = ("c", "cpp", "python", "javascript", "typescript", "go", "rust")
COMMENT_WHEN_DEFAULT = ("refs_failed", "refs_mixed", "needs_version", "needs_poc")


class ConfigError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class Thresholds:
    """Defaults chosen on the dev split only (docs/adr/0002-thresholds-chosen-on-dev-split.md)."""

    hard_fail_min: int = 2
    min_verified_share: float = 0.7
    min_verified_claims: int = 3


@dataclass
class CommentPolicy:
    mode: str = "both"  # "label", "comment", "both"
    when: list[str] = field(default_factory=lambda: list(COMMENT_WHEN_DEFAULT))


@dataclass
class Config:
    project: str = ""
    aliases: list[str] = field(default_factory=list)
    repository: str | None = None
    binaries: list[str] = field(default_factory=list)
    version_tags: list[str] = field(default_factory=lambda: ["v{version}", "{version}"])
    languages: list[str] = field(default_factory=list)
    paths_ignore: list[str] = field(default_factory=list)
    symbols_external: list[str] = field(default_factory=list)
    thresholds: Thresholds = field(default_factory=Thresholds)
    labels: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_LABELS))
    comment: CommentPolicy = field(default_factory=CommentPolicy)
    cves_file: str | None = None
    source: str = "<defaults>"
    base_dir: Path = field(default_factory=Path.cwd)

    def project_cves(self) -> set[str] | None:
        if not self.cves_file:
            return None
        path = (self.base_dir / self.cves_file).resolve()
        ids = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ids.add(line.split()[0].upper())
        return ids


_SCHEMA: dict[str, Any] = {
    "version": int,
    "project": {"name": str, "aliases": [str], "repository": str, "binaries": [str]},
    "version_tags": [str],
    "languages": [str],
    "paths": {"ignore": [str]},
    "symbols": {"external": [str]},
    "thresholds": {"hard_fail_min": int, "min_verified_share": float, "min_verified_claims": int},
    "labels": dict.fromkeys(DEFAULT_LABELS, str),
    "comment": {"mode": str, "when": [str]},
    "cves_file": str,
}


def _check(node: Any, schema: Any, path: str, errors: list[str], src: str) -> None:
    if isinstance(schema, dict):
        if not isinstance(node, dict):
            errors.append(f"{src}: {path or '<root>'}: expected a mapping")
            return
        for key, value in node.items():
            sub = f"{path}.{key}" if path else str(key)
            if "*" in schema:
                _check(value, schema["*"], sub, errors, src)
            elif key not in schema:
                errors.append(f"{src}: {sub}: unknown key")
            else:
                _check(value, schema[key], sub, errors, src)
    elif isinstance(schema, list):
        if not isinstance(node, list):
            errors.append(f"{src}: {path}: expected a list")
            return
        for i, item in enumerate(node):
            _check(item, schema[0], f"{path}[{i}]", errors, src)
    elif schema is float:
        if isinstance(node, bool) or not isinstance(node, (int, float)):
            errors.append(f"{src}: {path}: expected a number")
    elif schema is int:
        if isinstance(node, bool) or not isinstance(node, int):
            errors.append(f"{src}: {path}: expected an integer")
    elif schema is bool:
        if not isinstance(node, bool):
            errors.append(f"{src}: {path}: expected true or false")
    elif schema is str and not isinstance(node, str):
        errors.append(f"{src}: {path}: expected a string")


def expand_version_tags(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        out.extend(PRESETS.get(item, [item]))
    return out


def parse_config(doc: Any, source: str = "<config>", base_dir: Path | None = None) -> Config:
    errors: list[str] = []
    if doc is None:
        doc = {}
    _check(doc, _SCHEMA, "", errors, source)
    if errors:
        raise ConfigError(errors)
    if doc.get("version", 1) != 1:
        raise ConfigError([f"{source}: version: only version 1 is supported"])
    cfg = Config(source=source, base_dir=base_dir or Path.cwd())
    project = doc.get("project", {})
    cfg.project = project.get("name", "")
    cfg.aliases = list(project.get("aliases", []))
    cfg.repository = project.get("repository")
    cfg.binaries = list(project.get("binaries", [cfg.project] if cfg.project else []))
    if "version_tags" in doc:
        cfg.version_tags = expand_version_tags(doc["version_tags"])
        for i, pat in enumerate(cfg.version_tags):
            if not any(p in pat for p in ("{version}", "{major}")):
                errors.append(
                    f"{source}: version_tags[{i}]: {pat!r} has no {{version}} or {{major}} placeholder"
                )
    cfg.languages = list(doc.get("languages", []))
    for i, lang in enumerate(cfg.languages):
        if lang not in LANGUAGES:
            errors.append(
                f"{source}: languages[{i}]: {lang!r} is not one of {', '.join(LANGUAGES)}"
            )
    cfg.paths_ignore = list(doc.get("paths", {}).get("ignore", []))
    cfg.symbols_external = list(doc.get("symbols", {}).get("external", []))
    th = doc.get("thresholds", {})
    cfg.thresholds = Thresholds(
        hard_fail_min=th.get("hard_fail_min", Thresholds.hard_fail_min),
        min_verified_share=float(th.get("min_verified_share", Thresholds.min_verified_share)),
        min_verified_claims=th.get("min_verified_claims", Thresholds.min_verified_claims),
    )
    if cfg.thresholds.hard_fail_min < 1:
        errors.append(f"{source}: thresholds.hard_fail_min: must be at least 1")
    if not 0.0 <= cfg.thresholds.min_verified_share <= 1.0:
        errors.append(f"{source}: thresholds.min_verified_share: must be between 0 and 1")
    if cfg.thresholds.min_verified_claims < 1:
        errors.append(f"{source}: thresholds.min_verified_claims: must be at least 1")
    cfg.labels.update(doc.get("labels", {}))
    comment = doc.get("comment", {})
    cfg.comment = CommentPolicy(
        mode=comment.get("mode", "both"), when=list(comment.get("when", COMMENT_WHEN_DEFAULT))
    )
    if cfg.comment.mode not in ("label", "comment", "both"):
        errors.append(f"{source}: comment.mode: expected label, comment or both")
    for i, w in enumerate(cfg.comment.when):
        if w not in (*DEFAULT_LABELS, "always"):
            errors.append(f"{source}: comment.when[{i}]: {w!r} is not a class or label key")
    cfg.cves_file = doc.get("cves_file")
    if errors:
        raise ConfigError(errors)
    return cfg


def load_config(path: Path | None) -> Config:
    if path is None:
        return Config()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError([f"{path}: cannot read ({exc.strerror})"]) from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError([f"{path}: invalid YAML: {exc}"]) from exc
    return parse_config(doc, str(path), path.parent)


def find_config(repo_path: Path | None) -> Path | None:
    for base in (Path.cwd(), repo_path):
        if base is None:
            continue
        for name in (".sloptriage.yml", ".sloptriage.yaml"):
            candidate = base / name
            if candidate.is_file():
                return candidate
    return None
