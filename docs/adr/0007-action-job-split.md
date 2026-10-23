# ADR 0007: Two jobs with separate permissions in the Action

Status: accepted (2026-10-23)

## Context

The issue body is attacker-controlled. Reading it and writing to the issue need different permissions,
and the classic mistakes are interpolating `${{ github.event.issue.body }}` into a shell and giving the
job that parses untrusted input a write token.

## Decision

- **`check`** (`contents: read`, no secrets): reads the issue from `$GITHUB_EVENT_PATH`, writes
  `verdict.json`, uploads it as an artifact. It renders nothing.
- **`report`** (`issues: write`): downloads the verdict, validates it against the schema, renders the card
  from its fields and posts or updates one comment. It uses the action from the repository's own commit
  (`uses: $/` in this repository) and never checks out or runs anything from the issue.
- No workflow expression with event data in any `run:` block; inputs reach scripts through `env:`.
- No workflow for private vulnerability reports (see `docs/action.md`).

## Consequences

A shell or template injection in the issue cannot reach a token with write access, and the verdict is the
only channel between the two jobs. Tests and `zizmor` enforce the rules.
