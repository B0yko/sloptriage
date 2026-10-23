# Benchmark

## Corpus

- **Source:** curl's disclosed HackerOne reports. curl's policy is to disclose every report, valid or
  not (<https://curl.se/dev/vuln-disclosure.html>).
- **Enumeration (2026-10-23):** HackerOne's public hacktivity search returned 658 disclosed curl reports:
  272 not-applicable, 219 informative, 150 resolved, 9 duplicate, 8 spam (`scripts/enumerate_hackerone.py`).
- **Fetch:** each report's public JSON, once, at most one request per second, with a User-Agent naming
  this project; 658 requests in total.
- **Labels:** resolved = valid; not-applicable, informative, spam = invalid; duplicates excluded.
  "Informative" includes real bugs that are not security issues, so the invalid label is noisy.
  Corrections go only through `bench/manifest/CHANGES.md`, with a reason.
- **Slop list:** membership in the curl maintainers' public gist (revision `95a02e1`, 49 reports).
- **Era:** disclosed before 2023-01-01 versus after.
- **Split:** stratified by label and era, seed 20261023: 40% dev (260), 60% held-out (389). Frozen in
  commit `c33cdd9` before the classifier had thresholds. `MANIFEST.sha256` checks the frozen files.

## What is stored

`bench/manifest/reports.json` holds, per report: id, URL, substate, label, slop-list flag, disclosure
date, era, SHA-256 of the fetched JSON and SHA-256 of the body. `bench fetch` compares the body hash to
detect reports edited since the freeze. `bench/results/rows-*.json` hold, per report: the id, label,
substate, era and slop-list flag from the manifest, whether the body changed since the freeze, the
resolved ref and why it was chosen, claim and status counts, flags, the class, the check time and whether
the index was already cached. No text, titles or names.

The `seconds` in the rows come from the parallel benchmark run (8 workers); the latency figures in the
README come from `eval/latency.py`, which checks the reports one at a time.

## Commands

```bash
uv run sloptriage bench fetch                     # downloads the 658 JSON files into ~/.cache (11 minutes)
uv run sloptriage bench run --split dev           # or heldout / all; clones curl on first use
uv run sloptriage bench report bench/results/rows-dev-<date>.json bench/results/rows-heldout-<date>.json \
  --hardware "your machine"
uv run python eval/latency.py --hardware "your machine" --out bench/results/latency-<date>.json
uv run python scripts/render_results.py           # README tables
uv run python scripts/make_charts.py              # README chart
```

`bench run` first resolves every report's version and indexes the commits it needs plus one tag per minor
release, then checks the reports in parallel.

## Metrics

- Positive class: invalid. Prediction: `refs_failed`.
- Primary metric: false-flag rate, valid held-out reports classed `refs_failed` / all valid held-out
  reports, with a Wilson 95% interval. Precision for invalid comes with it.
- Recall of `refs_failed` over all invalid, over slop-listed invalid, over invalid not listed, and per era.
- Coverage: share of reports with at least one checkable high-confidence claim.

## History of held-out evaluations

1. Code at `2b38a84`: 10 of 90 valid reports classed `refs_failed`
   (`bench/results/rows-heldout-run1-2026-10-24.json`). Thresholds unchanged.
2. Code at `e036d44`, after one fix for defect classes found on the dev split (bare backticked
   identifiers treated as high confidence, a system path mapped onto a project directory, frames from an
   older release): 1 of 90. These are the published numbers.
