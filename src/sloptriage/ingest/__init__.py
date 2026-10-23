"""Turn reports from files, e-mail, GitHub and HackerOne JSON into a Report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sloptriage.ingest.eml import load_eml
from sloptriage.ingest.github import load_event_payload, report_from_issue
from sloptriage.ingest.hackerone import report_from_hackerone
from sloptriage.models import Report

__all__ = [
    "load_report",
    "load_eml",
    "load_event_payload",
    "report_from_issue",
    "report_from_hackerone",
]

MAX_REPORT_BYTES = 5_000_000


class IngestError(ValueError):
    """The input is not a report sloptriage can read."""


def load_report(location: str) -> Report:
    """Load a report from a path or ``-`` (stdin), detecting the format."""
    if location == "-":
        data = sys.stdin.buffer.read(MAX_REPORT_BYTES + 1)
        name = "stdin"
    else:
        path = Path(location)
        if not path.is_file():
            raise IngestError(f"{location}: no such file")
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise IngestError(f"{location}: larger than {MAX_REPORT_BYTES} bytes")
        data = path.read_bytes()
        name = path.name
    if len(data) > MAX_REPORT_BYTES:
        raise IngestError("report larger than 5 MB")
    lower = name.lower()
    if lower.endswith(".eml"):
        return load_eml(data, name)
    stripped = data.lstrip()
    if stripped.startswith(b"{"):
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IngestError(f"{name}: invalid JSON ({exc})") from exc
        if isinstance(doc, dict):
            if "vulnerability_information" in doc:
                return report_from_hackerone(doc)
            if isinstance(doc.get("issue"), dict):
                return load_event_payload(doc)
            if "body" in doc and "number" in doc:
                return report_from_issue(doc, source="github")
        raise IngestError(f"{name}: JSON is neither a GitHub issue/event nor a HackerOne report")
    if lower.endswith(".eml") or stripped[:200].lower().startswith(
        (b"from:", b"received:", b"mime-version:", b"return-path:")
    ):
        return load_eml(data, name)
    text = data.decode("utf-8", "replace")
    title = ""
    for line in text.splitlines():
        if line.strip():
            title = line.strip().lstrip("#").strip()[:200]
            break
    source = "stdin" if location == "-" else "file"
    return Report(source=source, id=name, title=title, body_markdown=text)
