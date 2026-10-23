"""Map the version a report claims to a git ref, with documented fallbacks."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from sloptriage.extract import Claim
from sloptriage.index.gitobj import GitRepo, looks_like_sha

PRESETS: dict[str, list[str]] = {
    "v": ["v{version}"],
    "plain": ["{version}"],
    "release": ["release-{version}", "release/{version}"],
    "curl": ["curl-{major}_{minor}_{patch}"],
    "underscore": ["{name}-{major}_{minor}_{patch}", "{name}_{major}_{minor}_{patch}"],
    "name-dash": ["{name}-{version}"],
}
DEFAULT_PATTERNS = ["v{version}", "{version}", "{name}-{version}"]
LATEST_WORDS = {"latest", "master", "main", "head", "trunk", "git", "dev", "development"}
_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-?(rc|beta|alpha|dev|DEV)\.?(\d*))?$"
)


@dataclass
class VersionFinding:
    claim: Claim
    status: str  # "found" | "not_found" | "assumed"
    ref: str | None = None
    commit: str | None = None
    nearest: list[str] = field(default_factory=list)


@dataclass
class Resolution:
    commit: str
    ref_label: str  # tag name, branch@date or SHA
    assumed: bool
    reason: str  # "claimed", "explicit", "sha", "dev_version", "no_version", "version_not_found", "latest"
    findings: list[VersionFinding] = field(default_factory=list)
    alternates: list[tuple[str, str]] = field(default_factory=list)  # (commit, label)


def parse_version(text: str) -> tuple[int, int, int, int] | None:
    m = _VERSION_RE.match(text.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), int(m.group(4) or 0))


def is_dev_version(text: str) -> bool:
    return bool(re.search(r"-?(?:dev|DEV)\b", text))


def candidate_tags(version: str, patterns: Sequence[str], name: str) -> list[str]:
    parsed = parse_version(version)
    if parsed is None:
        return []
    major, minor, patch, _ = parsed
    plain = version.lstrip("v").split("-")[0]
    variants = {plain}
    if plain.count(".") == 1:
        variants.add(f"{plain}.0")
    out: list[str] = []
    for pat in patterns:
        for v in sorted(variants):
            try:
                out.append(pat.format(version=v, major=major, minor=minor, patch=patch, name=name))
            except (KeyError, IndexError):
                continue
    return list(dict.fromkeys(out))


def release_tags(
    repo: GitRepo, patterns: Sequence[str], name: str
) -> dict[str, tuple[int, int, int, int]]:
    """Tags that match a release pattern, with their parsed version."""
    regexes: list[re.Pattern[str]] = []
    for pat in patterns:
        rx = re.escape(pat)
        rx = rx.replace(re.escape("{version}"), r"(?P<version>\d+(?:\.\d+){1,3})")
        for part in ("major", "minor", "patch"):
            rx = rx.replace(re.escape("{" + part + "}"), rf"(?P<{part}>\d+)")
        rx = rx.replace(re.escape("{name}"), re.escape(name))
        regexes.append(re.compile(f"^{rx}$"))
    out: dict[str, tuple[int, int, int, int]] = {}
    for tag in repo.tags():
        for regex in regexes:
            m = regex.match(tag)
            if not m:
                continue
            gd = m.groupdict()
            if gd.get("version"):
                parsed = parse_version(gd["version"])
            else:
                parsed = (
                    int(gd.get("major") or 0),
                    int(gd.get("minor") or 0),
                    int(gd.get("patch") or 0),
                    0,
                )
            if parsed:
                out[tag] = parsed
                break
    return out


def nearest_tags(target: str, tags: dict[str, tuple[int, int, int, int]], k: int = 3) -> list[str]:
    """Existing release tags closest to ``target``: nearest below first, then above, alternating."""
    parsed = parse_version(target)
    if parsed is None or not tags:
        return []
    ordered = sorted(tags.items(), key=lambda kv: kv[1])
    below = [t for t, v in ordered if v < parsed][::-1]
    above = [t for t, v in ordered if v > parsed]
    out: list[str] = []
    for i in range(k):
        for side in (below, above):
            if i < len(side) and len(out) < k:
                out.append(side[i])
    return out


def history_sample(tags: dict[str, tuple[int, int, int, int]]) -> list[str]:
    """The newest tag of every minor version: enough to recognise renamed or removed code."""
    best: dict[tuple[int, int], tuple[tuple[int, int, int, int], str]] = {}
    for tag, ver in tags.items():
        key = ver[:2]
        if key not in best or ver > best[key][0]:
            best[key] = (ver, tag)
    return [tag for _, (_, tag) in sorted(best.items())]


class VersionResolver:
    def __init__(self, repo: GitRepo, patterns: Sequence[str], name: str) -> None:
        self.repo = repo
        self.patterns = list(patterns) or DEFAULT_PATTERNS
        self.name = name
        self._tags: dict[str, tuple[int, int, int, int]] | None = None
        self._tag_dates: dict[str, str] | None = None

    @property
    def tags(self) -> dict[str, tuple[int, int, int, int]]:
        if self._tags is None:
            self._tags = release_tags(self.repo, self.patterns, self.name)
        return self._tags

    def tag_for(self, version: str) -> str | None:
        existing = set(self.repo.tags())
        for tag in candidate_tags(version, self.patterns, self.name):
            if tag in existing:
                return tag
        parsed = parse_version(version)
        if parsed:
            for tag, v in self.tags.items():
                if v == parsed:
                    return tag
        return None

    def latest_tag_before(self, iso_date: str | None) -> str | None:
        if self._tag_dates is None:
            self._tag_dates = self.repo.tag_dates()
        candidates = [
            (v, t)
            for t, v in self.tags.items()
            if iso_date is None or self._tag_dates.get(t, "") < iso_date
        ]
        if not candidates:
            return None
        return max(candidates)[1]

    def default_at(self, created_at: str | None) -> tuple[str, str]:
        branch = self.repo.default_branch()
        if created_at:
            sha = self.repo.commit_before(branch, created_at)
            if sha:
                return sha, f"{branch}@{created_at[:10]}"
        sha = self.repo.resolve_commit(branch) or self.repo.resolve_commit("HEAD")
        if not sha:
            raise ValueError("repository has no commits")
        return sha, branch

    def resolve(
        self, claims: Sequence[Claim], created_at: str | None, explicit_ref: str | None = None
    ) -> Resolution:
        findings: list[VersionFinding] = []
        primary: tuple[str, str, str] | None = None  # commit, label, reason
        version_claims = [c for c in claims if c.kind == "version"]
        high = [c for c in version_claims if c.confidence == "high"]
        considered = high or [c for c in version_claims if c.source in ("tag", "sha")]
        dev_seen = False
        for c in considered:
            if c.source == "sha" and looks_like_sha(c.value):
                sha = self.repo.resolve_commit(c.value)
                findings.append(VersionFinding(c, "found" if sha else "not_found", c.value, sha))
                if sha and primary is None:
                    primary = (sha, c.value[:12], "sha")
                continue
            if c.value.lower() in LATEST_WORDS:
                continue
            if is_dev_version(c.value):
                dev_seen = True
                findings.append(VersionFinding(c, "assumed"))
                continue
            tag = self.tag_for(c.value)
            if tag:
                commit = self.repo.resolve_commit(tag)
                findings.append(VersionFinding(c, "found", tag, commit))
                if commit and primary is None:
                    primary = (commit, tag, "claimed")
            elif c.confidence == "high":
                findings.append(
                    VersionFinding(c, "not_found", nearest=nearest_tags(c.value, self.tags))
                )
        if explicit_ref:
            commit = self.repo.resolve_commit(explicit_ref)
            if not commit:
                raise ValueError(f"--ref {explicit_ref!r} does not name a commit in the repository")
            primary = (commit, explicit_ref, "explicit")
        if primary is None:
            commit, label = self.default_at(created_at)
            if dev_seen:
                reason = "dev_version"
            elif any(f.status == "not_found" for f in findings):
                reason = "version_not_found"
            else:
                reason = "no_version"
            res = Resolution(commit, label, True, reason, findings)
        else:
            res = Resolution(primary[0], primary[1], False, primary[2], findings)
        res.alternates = self._alternates(res.commit, created_at)
        return res

    def _alternates(self, primary: str, created_at: str | None) -> list[tuple[str, str]]:
        """Other refs a citation may legitimately point at (checked only after a failure)."""
        out: list[tuple[str, str]] = []
        seen = {primary}
        try:
            sha, label = self.default_at(created_at)
            if sha not in seen:
                out.append((sha, label))
                seen.add(sha)
        except ValueError:
            pass
        tag = self.latest_tag_before(created_at)
        if tag:
            sha2 = self.repo.resolve_commit(tag)
            if sha2 and sha2 not in seen:
                out.append((sha2, tag))
                seen.add(sha2)
        branch = self.repo.default_branch()
        head = self.repo.resolve_commit(branch)
        if head and head not in seen:
            out.append((head, branch))
        return out
