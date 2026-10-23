"""RFC 822 e-mail: text parts become the body, attachments become artefacts."""

from __future__ import annotations

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from sloptriage.ingest.html import html_to_text
from sloptriage.models import Attachment, Report

MAX_ATTACHMENT_BYTES = 2_000_000


def load_eml(data: bytes, name: str = "report.eml") -> Report:
    msg = BytesParser(policy=policy.default).parsebytes(data)
    assert isinstance(msg, EmailMessage)
    texts: list[str] = []
    html_parts: list[str] = []
    attachments: list[Attachment] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if disposition == "attachment" or (
            filename and ctype not in ("text/plain", "text/markdown")
        ):
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes) and len(payload) <= MAX_ATTACHMENT_BYTES:
                safe = (filename or "attachment.bin").replace("/", "_").replace("\\", "_")[:120]
                attachments.append(Attachment(safe, payload, ctype))
            continue
        if ctype in ("text/plain", "text/markdown", "text/x-markdown"):
            texts.append(str(part.get_content()))
        elif ctype == "text/html":
            html_parts.append(html_to_text(str(part.get_content())))
    body = "\n\n".join(t.strip() for t in texts) if texts else "\n\n".join(html_parts)
    created = None
    if msg["Date"]:
        try:
            created = parsedate_to_datetime(str(msg["Date"])).isoformat()
        except (TypeError, ValueError):
            created = None
    return Report(
        source="eml",
        id=str(msg["Message-ID"] or name).strip("<>")[:200],
        title=str(msg["Subject"] or ""),
        body_markdown=body,
        attachments=attachments,
        created_at=created,
    )
