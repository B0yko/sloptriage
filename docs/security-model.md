# Security model

**Threats considered:** a report author who wants to run code on the maintainer's machine or CI, inject
into the triager, ping or impersonate people through the comment, or leak data out of CI.

| Concern | Design |
|---|---|
| Prompt injection | There is no model. The report is parsed by regular expressions and compared with git objects. |
| Shell injection in CI | Issue text is read from `$GITHUB_EVENT_PATH`, never interpolated into `run:` blocks. Tested with hostile fixtures; `zizmor` and `actionlint` in CI. |
| Token exposure | The job that reads the issue has `contents: read` and no secrets; the job with `issues: write` reads only a schema-validated verdict. |
| Markdown or HTML injection in the comment | Report-derived strings appear only as cleaned inline code (control and bidi characters removed, backticks and pipes replaced, length capped). The only links are permalinks into the project's own repository. `@mentions` get a zero-width space. Comments are capped at 60,000 characters. |
| Comment hijacking | Only a comment that starts with the marker and was written by `github-actions[bot]` is updated. |
| Fetching attacker URLs | Nothing in a report is fetched or cloned. `--repo URL` comes from the user or the config. HTML is converted without loading resources. |
| Running report code | v0.1.0 never runs a PoC or any code from a report. |
| Path tricks in attachments | Attachment names are flattened (`../../x` becomes `.._.._x`); attachments are never written to disk by the reference check. |
| Large inputs | Reports over 5 MB are rejected; files over 2 MB are listed but not analysed; quotes are not searched in files over 3 MB. |

## What is stored, and where

| Data | Where | Content |
|---|---|---|
| Repository clones | `${XDG_CACHE_HOME:-~/.cache}/sloptriage/repos/` | bare clones of repositories you named |
| Index | `~/.cache/sloptriage/index/<repo>.sqlite` | file lists, line counts, definitions and identifiers of your code |
| Demo repositories | `~/.cache/sloptriage/demo/` | built from the bundled snapshots |
| Benchmark reports | `~/.cache/sloptriage/bench/hackerone/` | public report JSON fetched by `bench fetch`, on your machine only |
| This repository | `bench/manifest/`, `bench/results/` | report IDs, URLs, substates, slop-list flags, disclosure dates, hashes, derived counts and classes; no report text, titles, reporter names or excerpts |

To report a vulnerability in sloptriage itself, see [SECURITY.md](../SECURITY.md).
