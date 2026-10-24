# Security model

**Threats considered:** a report author who wants to run code on the maintainer's machine or CI, inject
into the triager, ping or impersonate people through the comment, or leak data out of CI.

| Concern | Design |
|---|---|
| Prompt injection | There is no model. The report is parsed by regular expressions and compared with git objects. |
| Shell injection in CI | Issue text is read from `$GITHUB_EVENT_PATH`, never interpolated into `run:` blocks. Tested with hostile fixtures; `zizmor` and `actionlint` in CI. |
| Token exposure | The job that reads the issue has `contents: read` and no secrets; the job with `issues: write` reads only a schema-validated verdict. |
| Markdown or HTML injection in the comment | Report-derived strings appear only as cleaned inline code, or, for the output of a PoC, as a code fence (control and bidi characters removed, backticks and pipes replaced, length capped). The only links are permalinks into the project's own repository. `@mentions` get a zero-width space. Comments are capped at 60,000 characters. |
| Comment hijacking | Only a comment that starts with the marker and was written by `github-actions[bot]` (or a login listed in `SLOPTRIAGE_COMMENT_AUTHOR`) is updated. |
| Fetching attacker URLs | Nothing in a report is fetched or cloned. `--repo URL` comes from the user or the config. HTML is converted without loading resources. |
| Running report code | The reference check never runs anything from a report. Reproduction is opt-in and runs a PoC only inside a hardened container; there is no host mode (see below and [ADR 0006](adr/0006-container-hardening-no-host-mode.md)). |
| Path tricks in attachments | Attachment names are flattened (`../../x` becomes `.._.._x`); attachments are never written to disk by the reference check. |
| Large inputs | Reports over 5 MB are rejected; files over 2 MB are listed but not analysed; quotes are not searched in files over 3 MB. |

## Reproduction (`--repro`)

A PoC is code written by a stranger. It is run only when you ask, and only in a container.

| Concern | Design |
|---|---|
| Running on the host | Not possible: without a Docker or Podman CLI whose daemon answers, `--repro` exits with code 3. No flag or variable switches this off. |
| Network | `--network none`. The image stage is the only step with network; its inputs are the recipe and the dependency names the project's own manifests declare, never the report. The project stage builds under `--network none`. |
| Filesystem | Read-only root; size-limited tmpfs mounts at `/work` and `/tmp` (and the runtime's default 64 MB `/dev/shm`). No mounts, no devices, no Docker socket. Files reach the container as a tar stream of plain, flat file names that the tool builds. |
| Privileges | Non-root user, `--cap-drop ALL`, `no-new-privileges`, the runtime's default seccomp filter, no host namespaces. |
| Resource abuse | Limits on processes, memory (swap off), CPU, open files, wall-clock time and captured output; a run that floods its output is killed. Each limit has a test, and the ones that can be read from inside a container have a probe. |
| Host secrets | The environment is only the explicit `-e KEY=VALUE` pairs. Nothing is inherited. |
| Build scripts | Only commits reachable from a release tag or the default branch are built, so a script from a fork or a pull request never runs. The project stage has no network. |
| Hostile output | Output is decoded leniently, stripped of control and bidi characters and capped before it is parsed; the parsers cut every line at 1,000 characters, so a PoC cannot make them slow. In the card it appears only in a code fence with links, images, tags and `@mentions` made inert, at most 30 lines. |
| Counterfeit crashes | A sanitizer report counts only together with a non-zero exit status, runs are repeated and the crash must match the report's claim. A PoC can still fake both; the card shows the output so a person reads it. |
| Escape | The container runtime and the kernel are the boundary. Keep them patched; for reports from unknown people use a dedicated machine or an ephemeral CI runner, and rootless Podman where you can (it is not covered by the tests). In the Action the `repro` job has no token permissions. |

Images are named `sloptriage/…` and `sloptriage-base/…` and labelled `sloptriage=1`. List them with
`docker images 'sloptriage*'` and remove them with `docker image prune -a --filter label=sloptriage=1`.

## What is stored, and where

| Data | Where | Content |
|---|---|---|
| Repository clones | `${XDG_CACHE_HOME:-~/.cache}/sloptriage/repos/` | bare clones of repositories you named |
| Index | `~/.cache/sloptriage/index/<repo>.sqlite` | file lists, line counts, definitions and identifiers of your code |
| Demo repositories | `~/.cache/sloptriage/demo/` | built from the bundled snapshots |
| Reproduction images | the container runtime's image store | toolchain and sanitizer builds of the commits you reproduced, labelled `sloptriage=1` |
| Benchmark reports | `~/.cache/sloptriage/bench/hackerone/` | public report JSON fetched by `bench fetch`, on your machine only |
| This repository | `bench/manifest/`, `bench/results/` | report IDs, URLs, substates, slop-list flags, disclosure dates, hashes, derived counts and classes; no report text, titles, reporter names or excerpts |

To report a vulnerability in sloptriage itself, see [SECURITY.md](../SECURITY.md).
