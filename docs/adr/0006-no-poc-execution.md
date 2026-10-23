# ADR 0006: PoCs are not executed in v0.1.0

Status: accepted (2026-10-24)

## Context

Running a report's proof of concept would show whether a claimed crash happens. It means executing
untrusted code from a stranger, building the project at arbitrary versions and keeping that safe on
maintainers' machines and CI runners.

## Decision

v0.1.0 ships the reference check only. It never runs code from a report. The extractor still recognises
PoC blocks (C, C++, shell, Python, input files) and the verdict schema keeps a nullable `reproduction`
field, so a later version can add reproduction without changing the format.

## Consequences

- Reports whose only fault is the PoC (it overflows its own buffer, never calls the library, uses a normal
  input) cite code that exists and are not flagged; the README states this.
- Any future reproduction must run PoCs only in an isolated environment, never on the host.
