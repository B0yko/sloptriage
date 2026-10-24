# Configuration reference: `.sloptriage.yml`

Looked up in the repository passed with `--repo`, then in the working directory; `--config FILE`
overrides both. Validation is hand-written: every error names the file and the key path, and unknown
keys are errors.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `version` | integer | `1` | schema version; only 1 exists |
| `project.name` | string | repository directory name (or the last part of the URL) | used to find versions ("curl 8.10.1") and in the card |
| `project.aliases` | list of strings | `[]` | other names versions appear next to (`libcurl`) |
| `project.repository` | URL | git remote `origin` | clone source for `--repo`-less runs and base of permalinks (GitHub only) |
| `project.binaries` | list | `[name]` | command names that mark a shell block as a PoC |
| `version_tags` | list of presets or patterns | `["v{version}", "{version}"]` | how a version maps to a tag; placeholders `{version}`, `{major}`, `{minor}`, `{patch}`, `{name}`; presets `v`, `plain`, `curl`, `release`, `underscore`, `name-dash` |
| `languages` | list | any | `c`, `cpp`, `python`, `javascript`, `typescript`, `go`, `rust`; quotes in other languages are not treated as project source |
| `paths.ignore` | list of globs | `[]` | files left out of the index |
| `symbols.external` | list of globs | `[]` | names reported as `external` (neutral) |
| `thresholds.hard_fail_min` | integer ≥ 1 | `2` | see the classification rule |
| `thresholds.min_verified_share` | number 0–1 | `0.7` | see the classification rule |
| `thresholds.min_verified_claims` | integer ≥ 1 | `3` | `refs_verified` versus `refs_thin` |
| `labels.<key>` | string | `triage:…` | label names for `refs_verified`, `refs_thin`, `refs_mixed`, `refs_failed`, `needs_version`, `needs_poc`, `reproduced`, `not_reproduced` |
| `comment.mode` | `label`, `comment`, `both` | `both` | what the Action's report job does |
| `comment.when` | list | `[refs_failed, refs_mixed, needs_version, needs_poc]` | classes, needs and reproduction results (`reproduced`, `not_reproduced`) that get a comment; `always` for every report |
| `repro.enabled` | boolean | `false` | `check` runs PoCs without `--repro` (`--no-repro` overrides) |
| `repro.runtime` | `auto`, `docker`, `podman` | `auto` | which container CLI to use |
| `repro.runners` | list | `[c, cpp, shell, python, input]` | PoC kinds that may run |
| `repro.harness` | string with `{input}` | none | command that receives a decoded input file |
| `repro.limits.*` | see [Reproduction](repro.md#configuration) | `timeout: 20`, `memory: 512m`, `cpus: 1.0`, `pids: 128`, `tmpfs: 64m`, `runs: 3`, `candidates: 5` | per-run limits |
| `repro.build.*` | see [Reproduction](repro.md#configuration) | none | `preset`, `base_image`, `packages`, `configure`, `build`, `install`, `link`, `env`, `sanitizer_flags`, `requirements` |
| `cves_file` | path | none | a text file with the project's own CVE ids, one per line |

The `repro` keys are explained in [Reproduction](repro.md).

Version presets:

| Preset | Patterns |
|---|---|
| `v` | `v{version}` |
| `plain` | `{version}` |
| `curl` | `curl-{major}_{minor}_{patch}` |
| `release` | `release-{version}`, `release/{version}` |
| `underscore` | `{name}-{major}_{minor}_{patch}`, `{name}_{major}_{minor}_{patch}` |
| `name-dash` | `{name}-{version}` |
