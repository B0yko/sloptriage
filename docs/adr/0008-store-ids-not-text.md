# ADR 0008: Store report IDs and derived features, not report text

Status: accepted (2026-10-23)

## Context

The benchmark uses publicly disclosed HackerOne reports. Their text belongs to the reporters, and no
licence to redistribute it was found.

## Decision

The repository stores report IDs and URLs, the HackerOne substate, slop-list membership, the disclosure
date, SHA-256 hashes of each fetched JSON and of its body, and derived counts and classes. `bench fetch`
downloads the public JSON to the user's own cache. A test asserts that every string field of the
manifest schema is an enum or a pattern, so free text cannot be added by accident.

## Consequences

Anyone can rebuild the corpus from the manifest and detect reports edited since the freeze; the
repository and the README never quote a report.
