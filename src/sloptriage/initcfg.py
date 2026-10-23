"""``sloptriage init``: detect languages and the release tag style, write a starter config."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

from sloptriage.index.defs import language_for


def _files(root: Path) -> list[str]:
    proc = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.splitlines()
    return [
        str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
    ][:50000]


def _tag_style(root: Path) -> str:
    proc = subprocess.run(["git", "-C", str(root), "tag", "--list"], capture_output=True, text=True)
    tags = proc.stdout.splitlines() if proc.returncode == 0 else []
    styles: Counter[str] = Counter()
    for tag in tags:
        if re.fullmatch(r"v\d+\.\d+(\.\d+)?", tag):
            styles["v{version}"] += 1
        elif re.fullmatch(r"\d+\.\d+(\.\d+)?", tag):
            styles["{version}"] += 1
        elif m := re.fullmatch(r"([A-Za-z][\w-]*?)-\d+_\d+_\d+", tag):
            styles[f"{m.group(1)}-{{major}}_{{minor}}_{{patch}}"] += 1
        elif m := re.fullmatch(r"([A-Za-z][\w-]*?)-\d+\.\d+(\.\d+)?", tag):
            styles[f"{m.group(1)}-{{version}}"] += 1
    return styles.most_common(1)[0][0] if styles else "v{version}"


def write_config(root: Path) -> str:
    root = root.resolve()
    files = _files(root)
    langs: Counter[str] = Counter()
    for f in files:
        lang = language_for(f)
        if lang:
            langs["typescript" if lang == "tsx" else lang] += 1
    top = [lang for lang, n in langs.most_common() if n >= max(3, 0.05 * sum(langs.values()))] or [
        name for name, _ in langs.most_common(1)
    ]
    name = root.name
    remote = subprocess.run(
        ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    m = re.match(
        r"^(?:https://github\.com/|git@github\.com:)([\w.-]+)/([\w.-]+?)(?:\.git)?$", remote
    )
    repo_line = f"  repository: https://github.com/{m.group(1)}/{m.group(2)}\n" if m else ""
    lines = [
        "# sloptriage configuration (see docs/config.md)",
        "version: 1",
        "project:",
        f"  name: {name}",
        "  aliases: []",
    ]
    text = "\n".join(lines) + "\n" + repo_line
    text += f"  binaries: [{name}]\n"
    text += f'version_tags: ["{_tag_style(root)}"]\n'
    text += f"languages: [{', '.join(top)}]\n"
    text += "paths:\n  ignore: []\nsymbols:\n  external: []\n"
    return text
