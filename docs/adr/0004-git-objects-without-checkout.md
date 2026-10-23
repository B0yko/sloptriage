# ADR 0004: Read git objects instead of checking out

Status: accepted (2026-10-23)

## Context

A report names a version, and checking it means reading the code at that commit. Checking out a work
tree per report is slow, needs disk space per version and fails on bare clones, which are the natural
form of a cache.

## Decision

- List files with `git ls-tree -r -l -z <commit>` and read blobs through one long-lived
  `git cat-file --batch` process.
- Analyse each blob once (line count, definitions, identifiers) and key the result by blob SHA in a
  SQLite file per repository; a commit adds only its tree listing, keyed by commit SHA.

## Consequences

- Bare clones work, and the GitHub Action can use the checked-out repository as is.
- Indexing a second tag only parses changed files; curl's newest tag of every minor release (about 110
  tags) fits in one cache.
- Content is read on demand for quotes and blank-line checks, so the cache stays small.
