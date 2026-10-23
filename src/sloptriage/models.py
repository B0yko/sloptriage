"""Core data types shared across ingestion, checks and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Attachment:
    name: str
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass
class Report:
    source: str  # "file", "stdin", "eml", "github", "github-event", "hackerone", "advisory"
    id: str
    title: str
    body_markdown: str
    attachments: list[Attachment] = field(default_factory=list)
    claimed_version: str | None = None
    created_at: str | None = None
    url: str | None = None

    @property
    def text(self) -> str:
        """Title and body: both may cite code."""
        if not self.title or self.title in self.body_markdown[: len(self.title) + 16]:
            return self.body_markdown
        return f"{self.title}\n\n{self.body_markdown}"
