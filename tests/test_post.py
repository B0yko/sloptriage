from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sloptriage.config import Config
from sloptriage.demo_run import check_all
from sloptriage.post import post_verdict
from sloptriage.render import MARKER


@pytest.fixture(scope="module")
def verdict() -> dict[str, Any]:
    return next(v for r, v in check_all() if v["references"]["class"] == "refs_failed")


def _client(
    comments: list[dict[str, Any]], labels: list[str], calls: list[httpx.Request]
) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET" and request.url.path.endswith("/comments"):
            return httpx.Response(200, json=comments)
        if request.method == "GET" and request.url.path.endswith("/labels"):
            return httpx.Response(200, json=[{"name": n} for n in labels])
        return httpx.Response(200, json={})

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://api.github.com")


def test_updates_own_comment_and_swaps_labels(
    verdict: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    calls: list[httpx.Request] = []
    comments = [
        {"id": 1, "user": {"login": "someone"}, "body": MARKER + " copied marker"},
        {"id": 2, "user": {"login": "github-actions[bot]"}, "body": MARKER + "\nold card"},
    ]
    client = _client(comments, ["bug", "triage:refs-verified"], calls)
    post_verdict(verdict, "o/r#5", Config(), client=client)
    writes = [(c.method, c.url.path) for c in calls if c.method != "GET"]
    assert ("PATCH", "/repos/o/r/issues/comments/2") in writes
    assert not any(path.endswith("/comments/1") for _, path in writes)
    assert ("DELETE", "/repos/o/r/issues/5/labels/triage:refs-verified") in writes
    added = json.loads(
        next(c for c in calls if c.method == "POST" and c.url.path.endswith("/labels")).content
    )
    assert "triage:refs-failed" in added["labels"]


def test_creates_comment_when_none_exists(
    verdict: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    calls: list[httpx.Request] = []
    post_verdict(verdict, "o/r#5", Config(), client=_client([], [], calls))
    post = next(c for c in calls if c.method == "POST" and c.url.path.endswith("/comments"))
    assert json.loads(post.content)["body"].startswith(MARKER)


def test_label_only_mode_never_comments(
    verdict: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    cfg = Config()
    cfg.comment.mode = "label"
    calls: list[httpx.Request] = []
    post_verdict(verdict, "o/r#5", cfg, client=_client([], [], calls))
    assert not any(c.method == "POST" and c.url.path.endswith("/comments") for c in calls)
