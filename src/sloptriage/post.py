"""Post or update the verdict comment and labels on a GitHub issue.

Works only from a schema-validated verdict file: nothing from the issue is
checked out, run or re-read. One comment per issue, found by its marker, is
updated in place so edits to the report never create duplicates.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sloptriage import __version__
from sloptriage.ingest.github import API, github_token, parse_issue_ref
from sloptriage.render import MARKER, render_markdown, validate_verdict


class PostError(RuntimeError):
    pass


@dataclass
class Request:
    method: str
    path: str
    body: dict[str, Any] | None = None


Sender = Callable[[Request], Any]


def plan(
    verdict: dict[str, Any], existing_comment: int | None, current_labels: list[str]
) -> list[Request]:
    """The REST calls that bring the issue in line with the verdict (owner/repo are filled in later)."""
    reqs: list[Request] = []
    policy = verdict["policy"]
    mode = policy["mode"]
    body = render_markdown(verdict)
    want_comment = verdict.get("comment", False) and mode in ("comment", "both")
    if existing_comment is not None:
        reqs.append(Request("PATCH", f"/issues/comments/{existing_comment}", {"body": body}))
    elif want_comment:
        reqs.append(Request("POST", "/issues/{number}/comments", {"body": body}))
    if mode in ("label", "both"):
        ours = set(policy["managed_labels"])
        wanted = [lab for lab in verdict.get("labels", []) if lab in ours]
        for stale in sorted(set(current_labels) & ours - set(wanted)):
            reqs.append(Request("DELETE", "/issues/{number}/labels/" + _quote(stale)))
        missing = [lab for lab in wanted if lab not in current_labels]
        if missing:
            reqs.append(Request("POST", "/issues/{number}/labels", {"labels": missing}))
    return reqs


def _quote(label: str) -> str:
    from urllib.parse import quote

    return quote(label, safe="")


def issue_from_event(path: str) -> str:
    """``OWNER/REPO#N`` from a workflow event payload (only the number and repository name are read)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    number = (doc.get("issue") or {}).get("number")
    repo = (doc.get("repository") or {}).get("full_name")
    if not isinstance(number, int) or not isinstance(repo, str):
        raise ValueError(f"{path}: not an issues event payload")
    return f"{repo}#{number}"


def post_verdict(
    verdict: dict[str, Any],
    issue: str,
    *,
    dry_run: bool = False,
    out: Callable[[str], None] = lambda s: print(s, file=sys.stdout),
    client: Any = None,
) -> list[Request]:
    validate_verdict(verdict)
    owner, repo, number = parse_issue_ref(issue)
    base = f"/repos/{owner}/{repo}"
    if dry_run:
        reqs = plan(verdict, None, [])
        for r in reqs:
            path = base + r.path.replace("{number}", str(number))
            out(json.dumps({"method": r.method, "path": path, "body": r.body}, ensure_ascii=False))
        return reqs
    token = github_token()
    if not token:
        raise PostError("set GITHUB_TOKEN (issues: write) to post")
    import httpx

    own = client is None
    http = client or httpx.Client(
        base_url=API,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"sloptriage/{__version__}",
        },
        timeout=30.0,
    )
    try:
        existing = _find_comment(http, base, number)
        labels_resp = http.get(f"{base}/issues/{number}/labels", params={"per_page": 100})
        labels_resp.raise_for_status()
        current = [item["name"] for item in labels_resp.json()]
        reqs = plan(verdict, existing, current)
        for r in reqs:
            path = base + r.path.replace("{number}", str(number))
            resp = (
                http.request(r.method, path, json=r.body)
                if r.body is not None
                else http.request(r.method, path)
            )
            if resp.status_code >= 400 and not (r.method == "DELETE" and resp.status_code == 404):
                raise PostError(f"{r.method} {path}: HTTP {resp.status_code}")
        return reqs
    finally:
        if own:
            http.close()


def _authors() -> set[str]:
    """Only our own earlier comment is updated, never one that merely copies the marker."""
    import os

    extra = os.environ.get("SLOPTRIAGE_COMMENT_AUTHOR", "")
    return {"github-actions[bot]", *(x.strip() for x in extra.split(",") if x.strip())}


def _find_comment(http: Any, base: str, number: int) -> int | None:
    page = 1
    while page <= 30:
        resp = http.get(f"{base}/issues/{number}/comments", params={"per_page": 100, "page": page})
        resp.raise_for_status()
        items = resp.json()
        for item in items:
            author = (item.get("user") or {}).get("login", "")
            if (
                author in _authors()
                and isinstance(item.get("body"), str)
                and item["body"].startswith(MARKER)
            ):
                return int(item["id"])
        if len(items) < 100:
            return None
        page += 1
    return None
