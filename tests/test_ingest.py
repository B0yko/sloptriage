from __future__ import annotations

import json
from pathlib import Path

import pytest

from sloptriage.ingest import IngestError, load_report
from sloptriage.ingest.github import load_event_payload, parse_issue_ref
from sloptriage.ingest.html import html_to_text

EML = b"""From: reporter@example.com
To: security@example.com
Subject: Heap overflow in parse_header
Date: Tue, 01 Oct 2024 10:00:00 +0000
Message-ID: <abc123@example.com>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="XX"

--XX
Content-Type: text/plain

The bug is in `lib/a.c:12` in parse_header().
--XX
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="../../crash.bin"
Content-Transfer-Encoding: base64

AAEC
--XX--
"""


def test_markdown_file(tmp_path: Path) -> None:
    p = tmp_path / "r.md"
    p.write_text("# Overflow in `foo()`\n\nbody text\n")
    rep = load_report(str(p))
    assert rep.source == "file"
    assert rep.title == "Overflow in `foo()`"
    assert rep.text.startswith("# Overflow")


def test_eml_parts_and_attachments(tmp_path: Path) -> None:
    p = tmp_path / "r.eml"
    p.write_bytes(EML)
    rep = load_report(str(p))
    assert rep.source == "eml"
    assert rep.title == "Heap overflow in parse_header"
    assert "lib/a.c:12" in rep.body_markdown
    assert rep.attachments[0].name == ".._.._crash.bin"
    assert rep.attachments[0].content == b"\x00\x01\x02"
    assert rep.created_at is not None and rep.created_at.startswith("2024-10-01")


def test_hackerone_json(tmp_path: Path) -> None:
    p = tmp_path / "1.json"
    p.write_text(
        json.dumps(
            {
                "id": 1,
                "title": "t",
                "vulnerability_information": "body",
                "submitted_at": "2024-01-02T00:00:00Z",
            }
        )
    )
    rep = load_report(str(p))
    assert (rep.source, rep.id, rep.body_markdown, rep.created_at) == (
        "hackerone",
        "1",
        "body",
        "2024-01-02T00:00:00Z",
    )


def test_github_event_payload(tmp_path: Path) -> None:
    event = {
        "action": "opened",
        "issue": {"number": 7, "title": "x", "body": "y", "created_at": "2024-05-01T00:00:00Z"},
        "repository": {"full_name": "o/r"},
    }
    rep = load_event_payload(event)
    assert (rep.id, rep.title, rep.body_markdown) == ("o/r#7", "x", "y")
    p = tmp_path / "event.json"
    p.write_text(json.dumps(event))
    assert load_report(str(p)).source == "github-event"


def test_issue_ref_parsing() -> None:
    assert parse_issue_ref("B0yko/sloptriage#12") == ("B0yko", "sloptriage", 12)
    with pytest.raises(ValueError):
        parse_issue_ref("not a ref")


def test_html_is_converted_without_rendering() -> None:
    text = html_to_text(
        '<p>See <code>foo()</code><img src="http://example.com/x.png"></p><script>alert(1)</script><pre>a\nb</pre>'
    )
    assert "`foo()`" in text
    assert "alert" not in text and "example.com" not in text
    assert "```\na\nb\n```" in text


def test_unknown_json_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text('{"hello": 1}')
    with pytest.raises(IngestError):
        load_report(str(p))
