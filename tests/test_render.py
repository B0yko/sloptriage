from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from sloptriage.config import Config
from sloptriage.demo_run import check_all
from sloptriage.index import IndexSet
from sloptriage.index.gitobj import GitRepo
from sloptriage.models import Report
from sloptriage.render import (
    MAX_COMMENT,
    build_verdict,
    render_markdown,
    render_preflight,
    render_text,
    validate_verdict,
)
from sloptriage.verdict import run_reference_check

FORBIDDEN = re.compile(r"\b(slop|ai|llm|fake|hallucinated|spam|invalid)\b", re.I)
ALLOWED_TAGS = {"details", "/details", "summary", "/summary", "sub", "/sub"}


def _strip_allowed(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    return text.replace("sloptriage", " ")


@pytest.fixture(scope="module")
def demo_verdicts() -> list[tuple[Any, dict[str, Any]]]:
    return check_all()


def test_every_demo_card_is_neutral_and_valid(
    demo_verdicts: list[tuple[Any, dict[str, Any]]],
) -> None:
    for rep, verdict in demo_verdicts:
        validate_verdict(verdict)
        for text in (render_markdown(verdict), render_text(verdict), render_preflight(verdict)):
            assert not FORBIDDEN.search(_strip_allowed(text)), (
                rep.file,
                FORBIDDEN.search(_strip_allowed(text)),
            )
        md = render_markdown(verdict)
        assert md.startswith("<!-- sloptriage -->")
        assert len(md) < MAX_COMMENT
        outside_code = re.sub(r"(?s)```+.*?```+", "", md.split("\n", 1)[1])
        prose = re.sub(r"`[^`]*`|\]\([^)]*\)", "", outside_code)
        assert not re.search(r"(?<![\w&])#\d", prose), (rep.file, "issue cross-reference")
        for tag in re.findall(r"<(/?[a-zA-Z][\w-]*)", outside_code):
            assert tag in ALLOWED_TAGS, (rep.file, tag)


def _hostile_card(tmp_path: Path) -> str:
    from conftest import make_repo

    root = make_repo(tmp_path / "p", [("v1.0.0", {"lib/a.c": "int real_fn(void) { return 0; }\n"})])
    repo = GitRepo(root)
    cfg = Config(
        project="demo", version_tags=["v{version}"], repository="https://github.com/example/demo"
    )
    body = (
        "demo 1.0.0 crash in `evil_fn()` @octocat <img src=x onerror=alert(1)> [click](https://evil.example/x) "
        "![img](https://evil.example/i.png) `a`b`c()` ‮gnp.exe‬ and `lib/a.c:99` and `other_missing_fn()` "
        "and `$(touch /tmp/pwned)` <script>alert(1)</script> `${{ github.token }}`"
    )
    result = run_reference_check(
        Report("file", "x", "t", body), repo, IndexSet(repo, str(root)), cfg
    )
    verdict = build_verdict(result, cfg)
    validate_verdict(verdict)
    return render_markdown(verdict)


def test_report_strings_are_escaped(tmp_path: Path) -> None:
    md = _hostile_card(tmp_path)
    body = md.split("\n", 1)[1]
    assert "<img" not in body and "<script" not in body
    assert "evil.example" not in body
    assert "@octocat" not in body  # mentions are neutralised
    assert "‮" not in body
    links = re.findall(r"\]\((https?://[^)]+)\)", body)
    assert links and all(
        u.startswith(
            ("https://github.com/example/demo/blob/", "https://github.com/B0yko/sloptriage")
        )
        for u in links
    )


def test_preflight_is_a_checklist(demo_verdicts: list[tuple[Any, dict[str, Any]]]) -> None:
    text = render_preflight(demo_verdicts[30][1])
    assert text.startswith("Before you send this report:")
    assert "[ ]" in text and "cannot tell whether the issue is real" in text
