# ADR 0003: Neutral, specific wording

Status: accepted (2026-10-23)

## Context

The card is posted on a public issue, often to a first-time contributor. Many reports with broken
references are honest mistakes: wrong version, a typo, code read from a fork. Calling a report fake or
machine-written would be a guess about intent, and sloptriage cannot know it.

## Decision

- The card states what was checked and what was found, with the version and a permalink: "`foo()` is not
  defined anywhere in curl at `curl-8_10_1`", "line 812 is past the end of `lib/http.c` (640 lines)".
- It never uses the words "slop", "AI", "LLM", "fake", "hallucinated", "spam" or "invalid". A test
  renders every fixture card and checks this, ignoring the product name and URLs.
- It always says that verified references do not mean the issue is real, and it offers what would help:
  a version, a reproducer, a short template.
- The tool never closes, locks or deletes anything and never contacts reporters.

## Consequences

Maintainers get a fact sheet, reporters get actionable corrections, and `preflight` lets reporters run
the same checks before sending.
