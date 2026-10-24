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

```bash
uv run sloptriage bench repro --split heldout --subset both \
  --repo https://github.com/curl/curl --hardware "your machine"   # needs Docker or Podman
```

`bench repro` builds curl with sanitizers at each version the selected reports name and runs their PoCs in
the sandbox ([reproduction](repro.md)). Two groups are tried: resolved reports of the chosen split that
carry an inline C, C++ or shell PoC and name a version that maps to a release tag (`valid`), and reports on
the curl maintainers' public list that carry such a PoC, in either split and with or without a version
(`slop`; no version means the default branch as of the report date). The project image of each version is
removed once its reports are done. `bench/results/repro-<date>.json` keeps, per report, only these fields:
`id`, `group` (`valid` or `slop`), `split` (the report's own split in the manifest, `dev` or `heldout`),
`era`, `slop_list`, `ref` (what was built), `ref_assumed` (the version was not named), `runner`, `verdict`,
`match` (how a crash related to the report's claim) and `runs`: no text, output, function names or build
logs. (The first files wrote the command's `--split` option into `split`; it was corrected from the
manifest.)

`bench run` first resolves every report's version and indexes the commits it needs plus one tag per minor
release, then checks the reports in parallel.

## Reproduction runs

`bench repro` was run three times on the same 38 reports (17 resolved held-out with an inline C, C++ or shell
PoC and a named version, 21 on the public list with a PoC), plus once on the 12 resolved dev reports.
The three runs are in `bench/results/repro-run1-2026-10-24.json`, `repro-run2-2026-10-24.json` and
`repro-2026-10-24.json` (the published one); the dev run is `repro-dev-2026-10-24.json`.

| Run (code at) | Code change before it | Resolved held-out (17) | Listed (21) |
|---|---|---|---|
| 1 (`0e86d3d`) | none | 0 reproduced; 14 `not_reproduced`, 1 `crashed_elsewhere`, 1 `poc_build_failed`, 1 `build_failed` | 0 reproduced; 20 `not_reproduced`, 1 `crashed_elsewhere` |
| dev (`fe22243`; 12 resolved dev reports) | `/tmp` and `python3` in the sandbox, missing tools reported as `poc_unsupported` | 0 reproduced; 8 `not_reproduced`, 1 `crashed_elsewhere`, 1 `build_failed`, 1 `poc_build_failed`, 1 `timeout` | not run |
| 2 (`d52d4a8`) | reasons for PoCs that cannot run as given (file, service, syntax, tools) | 0 reproduced; 7 `poc_unsupported`, 5 `not_reproduced`, 2 `crashed_elsewhere`, 1 each `timeout`, `poc_build_failed`, `build_failed` | 0 reproduced; 9 `not_reproduced`, 5 `crashed_elsewhere`, 3 `poc_unsupported`, 3 `timeout`, 1 `poc_build_failed` |
| 3 (`f04fc8a`, published) | frames of installed shared libraries, a PoC's own missing file or module, missing executables and features | 0 reproduced; 10 `poc_unsupported`, 3 `not_reproduced`, 1 `crashed_elsewhere`, 1 each `timeout`, `poc_build_failed`, `build_failed` | 0 reproduced; 9 `not_reproduced`, 5 `poc_unsupported`, 3 `crashed_elsewhere`, 3 `timeout`, 1 `poc_build_failed` |

Run 1 was the only run before any change. The changes were chosen after looking at what happened to
individual reports, held-out ones included, so the published numbers are not a blind first look. They did
not change which reports reproduced (none did in any run); they changed how the failures are described.

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
