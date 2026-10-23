"""GitHub issues: by ``owner/repo#N`` through the REST API, or from an Actions event payload."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sloptriage.models import Report

ISSUE_REF_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9-]{1,39})/(?P<repo>[A-Za-z0-9._-]{1,100})#(?P<number>\d{1,9})$"
)
API = "https://api.github.com"


def parse_issue_ref(ref: str) -> tuple[str, str, int]:
    m = ISSUE_REF_RE.match(ref.strip())
    if not m:
        raise ValueError(f"{ref!r} is not OWNER/REPO#NUMBER")
    return m.group("owner"), m.group("repo"), int(m.group("number"))


def report_from_issue(
    issue: dict[str, Any], *, source: str, repo_slug: str | None = None
) -> Report:
    number = issue.get("number")
    body = issue.get("body")
    url = issue.get("html_url")
    return Report(
        source=source,
        id=f"{repo_slug}#{number}" if repo_slug else str(number),
        title=str(issue.get("title") or ""),
        body_markdown=body if isinstance(body, str) else "",
        created_at=str(issue["created_at"]) if issue.get("created_at") else None,
        url=str(url) if isinstance(url, str) else None,
    )


def load_event_payload(doc: dict[str, Any] | str | Path) -> Report:
    """Read the issue from a workflow's ``$GITHUB_EVENT_PATH`` payload."""
    if not isinstance(doc, dict):
        doc = json.loads(Path(doc).read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    issue = doc.get("issue")
    if not isinstance(issue, dict):
        raise ValueError("event payload has no issue")
    repo = doc.get("repository") or {}
    slug = repo.get("full_name") if isinstance(repo, dict) else None
    return report_from_issue(
        issue, source="github-event", repo_slug=slug if isinstance(slug, str) else None
    )


def github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def fetch_issue(ref: str) -> Report:
    import httpx

    from sloptriage import __version__

    owner, repo, number = parse_issue_ref(ref)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"sloptriage/{__version__}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.get(f"{API}/repos/{owner}/{repo}/issues/{number}", headers=headers, timeout=30.0)
    resp.raise_for_status()
    return report_from_issue(resp.json(), source="github", repo_slug=f"{owner}/{repo}")


def fetch_advisory(ref: str) -> Report:
    """Read one (draft) repository security advisory with a PAT from the environment.

    ``ref`` is ``OWNER/REPO/GHSA-xxxx-xxxx-xxxx``. The token needs the fine-grained
    permission "Repository security advisories: read". Output stays in the terminal.
    """
    import httpx

    from sloptriage import __version__

    m = re.match(
        r"^(?P<owner>[\w-]+)/(?P<repo>[\w.-]+)/(?P<ghsa>GHSA(?:-[0-9a-z]{4}){3})$",
        ref.strip(),
        re.I,
    )
    if not m:
        raise ValueError(f"{ref!r} is not OWNER/REPO/GHSA-xxxx-xxxx-xxxx")
    token = github_token()
    if not token:
        raise ValueError(
            "set GITHUB_TOKEN (fine-grained PAT with 'Repository security advisories: read')"
        )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"sloptriage/{__version__}",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{API}/repos/{m.group('owner')}/{m.group('repo')}/security-advisories/{m.group('ghsa')}"
    resp = httpx.get(url, headers=headers, timeout=30.0)
    resp.raise_for_status()
    doc = resp.json()
    body = "\n\n".join(x for x in (doc.get("summary") or "", doc.get("description") or "") if x)
    return Report(
        source="advisory",
        id=str(doc.get("ghsa_id") or m.group("ghsa")),
        title=str(doc.get("summary") or ""),
        body_markdown=body,
        created_at=doc.get("created_at"),
    )
