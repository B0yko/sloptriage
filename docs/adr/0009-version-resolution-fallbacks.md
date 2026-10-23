# ADR 0009: Version-resolution fallbacks

Status: accepted (2026-10-23)

## Context

Reports often omit the version, name a development build ("8.11.0-DEV"), name a version that was never
released, or read code at master while naming a release. A strict check at a single ref would turn every
such report into a list of failures.

## Decision

- The first high-confidence version that maps to a tag is the primary ref; a named commit SHA is used
  directly.
- No version, "latest", "master", "main" or a development version: the default branch as of the report's
  creation date, marked as assumed.
- An unknown version is a finding (`version_not_found`) with the nearest tags, and the check falls back to
  the default branch as of the report date.
- A citation that fails at the primary ref is re-checked at the default branch as of the report date,
  the newest release tag before it, the default branch head, and any other indexed release. A match
  there is "another version" (informational), never a failure.

## Consequences

Honest reports with version drift are not flagged; a citation fails only when it exists in no version
the index knows. The cost is lower recall on reports that cite code from a version they did not name.
