# ADR 0005: tree-sitter grammar wheels instead of universal-ctags

Status: accepted (2026-10-23)

## Context

The index needs definitions with line spans for C, C++, Python, JavaScript, TypeScript, Go and Rust,
installed with `pip` or `uvx` on macOS and Linux and working offline.

## Options

- **universal-ctags:** broad language support, but GPL-2.0, a native binary with no Python wheels, and
  spans need extra flags per language.
- **`tree-sitter-language-pack`:** one package, but on 2026-10-23 its README said it downloads grammars on
  first use, which breaks offline runs and CI caches.
- **`tree-sitter` plus one pinned grammar wheel per language:** abi3 wheels for macOS and Linux, no
  network at run time, permissive licences.

## Decision

`tree-sitter==0.26.0` with pinned `tree-sitter-c`, `-cpp`, `-python`, `-javascript`, `-typescript`, `-go`
and `-rust` wheels. Definitions come from walking the syntax tree (no query language), which is stable
across binding versions. For C and C++, a brace-matching pass recovers functions that tree-sitter
cannot parse without a preprocessor; both span sets are kept.

## Consequences

Offline after install, Apache-compatible licensing, and precise spans for the frame checks.
