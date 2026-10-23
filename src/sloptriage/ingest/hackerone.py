"""Public HackerOne report JSON (the shape served at hackerone.com/reports/<id>.json)."""

from __future__ import annotations

from typing import Any

from sloptriage.models import Report


def report_from_hackerone(doc: dict[str, Any]) -> Report:
    body = doc.get("vulnerability_information")
    if not isinstance(body, str):
        body = ""
    rid = doc.get("id")
    created = doc.get("submitted_at") or doc.get("created_at")
    return Report(
        source="hackerone",
        id=str(rid) if rid is not None else "unknown",
        title=str(doc.get("title") or ""),
        body_markdown=body,
        attachments=[],  # attachments are never downloaded
        claimed_version=None,
        created_at=str(created) if created else None,
        url=f"https://hackerone.com/reports/{rid}" if isinstance(rid, int) else None,
    )
