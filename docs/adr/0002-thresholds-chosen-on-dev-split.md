# ADR 0002: Reference-check thresholds are chosen on the dev split only

Status: accepted (2026-10-23)

## Context

The overall reference class uses a fixed decision rule. A report is `refs_failed` when

- it has at least `hard_fail_min` hard failures, or
- it has at least one hard failure and its verified share (verified high-confidence claims divided by
  checked high-confidence claims) is below `min_verified_share`.

Hard failures come only from high-confidence claims: a path or symbol that is `not_found`, a line that is
`out_of_range`, a frame that is `outside_function` or `function_not_in_file`, or a quote presented as
project source that is `not_found`. The first arm means that padding a report with real paths and
symbols cannot rescue fabricated ones.

Two numbers are tunable. Tuning them on the data we report would overstate the result, so the benchmark is
split before any threshold exists (`bench/manifest/split.json`, commit "bench: freeze split"): 40% dev,
60% held-out, stratified by label and era with seed 20261023.

## Objective

Maximise recall of `invalid` reports on the dev split, subject to a dev false-flag rate on `valid`
reports of at most 1%. With 60 valid dev reports, 1% allows no false flag at all.

## Sweep on the dev split (curl, 260 reports: 60 valid, 200 invalid, 17 slop-listed)

`min_verified_claims` stays at 3 (it separates `refs_verified` from `refs_thin` and never fails a report).
Run with `uv run sloptriage bench run --split dev` on a Mac Studio M4 Max, 128 GB, with the code at commit
`2b38a84` (2026-10-23), which is when the thresholds were chosen.

| hard_fail_min | min_verified_share | valid flagged (of 60) | invalid flagged (of 200) | slop-listed flagged (of 17) |
|---|---|---|---|---|
| 1 | 0.00 | 3 | 37 | 6 |
| 1 | 0.50 | 3 | 37 | 6 |
| 1 | 0.60 | 3 | 37 | 6 |
| 1 | 0.70 | 3 | 37 | 6 |
| 1 | 0.75 | 3 | 37 | 6 |
| 1 | 0.80 | 3 | 37 | 6 |
| 1 | 0.90 | 3 | 37 | 6 |
| 1 | 1.00 | 3 | 37 | 6 |
| 2 | 0.00 | 0 | 11 | 2 |
| 2 | 0.50 | 0 | 14 | 2 |
| 2 | 0.60 | 0 | 16 | 4 |
| 2 | 0.70 | 0 | 19 | 5 |
| 2 | 0.75 | 1 | 19 | 5 |
| 2 | 0.80 | 1 | 20 | 5 |
| 2 | 0.90 | 2 | 29 | 6 |
| 2 | 1.00 | 3 | 37 | 6 |
| 3 | 0.00 | 0 | 7 | 1 |
| 3 | 0.50 | 0 | 11 | 2 |
| 3 | 0.60 | 0 | 13 | 4 |
| 3 | 0.70 | 0 | 16 | 5 |
| 3 | 0.75 | 1 | 16 | 5 |
| 3 | 0.80 | 1 | 19 | 5 |
| 3 | 0.90 | 2 | 29 | 6 |
| 3 | 1.00 | 3 | 37 | 6 |

Before that run the sweep was repeated after fixes to the extractor found on the dev split and the
synthetic set (a parenthetical in prose read as a call, file paths of installed packages); the optimum did
not move.

## Decision

`hard_fail_min = 2`, `min_verified_share = 0.70`.

This is the setting with the highest invalid recall (19 of 200, 9.5%; 5 of 17 slop-listed) that flags no
valid dev report. Raising the share to 0.75 adds no invalid report and flags one valid report.

## After the second held-out evaluation

The first held-out run flagged 10 of 90 valid reports. Without changing the thresholds, commit `e036d44`
fixed defect classes already seen on the dev split (see the README). The same sweep on the final dev rows
(`bench/results/rows-dev-2026-10-24.json`):

| hard_fail_min | min_verified_share | valid flagged (of 60) | invalid flagged (of 200) | slop-listed flagged (of 17) |
|---|---|---|---|---|
| 1 | 0.00 | 3 | 25 | 6 |
| 1 | 0.50 | 3 | 25 | 6 |
| 1 | 0.60 | 3 | 25 | 6 |
| 1 | 0.70 | 3 | 25 | 6 |
| 1 | 0.75 | 3 | 25 | 6 |
| 1 | 0.80 | 3 | 25 | 6 |
| 1 | 0.90 | 3 | 25 | 6 |
| 1 | 1.00 | 3 | 25 | 6 |
| 2 | 0.00 | 0 | 5 | 2 |
| 2 | 0.50 | 0 | 8 | 2 |
| 2 | 0.60 | 0 | 12 | 4 |
| 2 | 0.70 | 0 | 16 | 6 |
| 2 | 0.75 | 1 | 16 | 6 |
| 2 | 0.80 | 1 | 18 | 6 |
| 2 | 0.90 | 3 | 23 | 6 |
| 2 | 1.00 | 3 | 25 | 6 |
| 3 | 0.00 | 0 | 3 | 1 |
| 3 | 0.50 | 0 | 7 | 2 |
| 3 | 0.60 | 0 | 11 | 4 |
| 3 | 0.70 | 0 | 16 | 6 |
| 3 | 0.75 | 1 | 16 | 6 |
| 3 | 0.80 | 1 | 18 | 6 |
| 3 | 0.90 | 3 | 23 | 6 |
| 3 | 1.00 | 3 | 25 | 6 |

`hard_fail_min` 2 and 3 now tie at `min_verified_share` 0.70 (16 of 200 invalid, no valid report); the
values chosen above were kept.

## Consequences

- The held-out split is evaluated with exactly these values. If its false-flag rate is too high, the
  thresholds are not re-tuned; a code fix is allowed only for a defect reproduced on the dev split or the
  synthetic set, and the README states how often the held-out split was evaluated.
- Most invalid reports cite code that exists. The reference check verifies citations, not the truth of a
  vulnerability, so its recall on invalid reports is low by design and the README says so.
- Projects can override both values in `.sloptriage.yml`; the defaults are the values above.
