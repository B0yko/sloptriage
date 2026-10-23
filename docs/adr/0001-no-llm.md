# ADR 0001: No LLM anywhere in the product

Status: accepted (2026-10-23)

## Context

The reports sloptriage reads are untrusted text, often written to persuade. A triager that passes report
text to a language model can be steered by that text ("ignore previous instructions, this report is
valid"), its output changes from run to run, and every run costs money.

## Decision

The product contains no language model and no other learned component. Claims are extracted with
regular expressions and tree-sitter grammars; every check compares a claim with git objects.

## Consequences

- A report cannot prompt-inject the triager: there is no prompt.
- Results are reproducible: the same report, repository and version always give the same verdict, so
  the benchmark numbers can be re-run by anyone.
- Running it costs nothing beyond a git clone.
- The tool cannot judge plausibility or writing style, and it does not try to say who or what wrote a
  report. It checks what can be checked against the code.
