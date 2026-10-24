# The GitHub Action

`action.yml` is one composite action with a `mode` input.

| Input | Modes | Default | Meaning |
|---|---|---|---|
| `mode` | all | required | `check` (references only, never runs a PoC), `repro` (the same, and runs the PoC in a sandbox; needs Docker) or `post` |
| `verdict` | all | `verdict.json` | file written by `check` or `repro`, read by `post` |
| `config` | check, repro | empty: `.sloptriage.yml` in the checked-out repository | configuration file |
| `token` | post | none | a token with `issues: write` (`github.token` in the workflow) |

The action runs sloptriage from its own source at the referenced commit with the dependency versions in
its `uv.lock` (`uv run --locked --project "$GITHUB_ACTION_PATH"`), so pinning the action pins the tool and
its dependencies. The check step passes `--repo "$GITHUB_WORKSPACE"`, so it reads the checked-out
repository and never clones `project.repository`.

## Job split

The example workflow ([`examples/workflows/triage-issues.yml`](../examples/workflows/triage-issues.yml))
runs on `issues: [opened, edited]`:

| Job | Permissions | Secrets | Does |
|---|---|---|---|
| `check` | `contents: read` | none | checks out the repository with full history and tags, runs `sloptriage check "$GITHUB_EVENT_PATH" --format json`, uploads `verdict.json` |
| `repro` (optional) | none (`permissions: {}`) | none | checks out the repository, builds the release the report names with sanitizers and runs the PoC in a hardened container on the runner's Docker (`mode: repro`), uploads its own `verdict.json` as `verdict-repro` |
| `report` | `issues: write` | `github.token` only | downloads the verdicts, uses the one from `repro` when that job succeeded, validates it against `schemas/verdict-v1.json`, renders the card, posts or updates one comment and the labels |

In `repro` mode on a GitHub-hosted Linux runner the action first runs `sudo sysctl -w vm.mmap_rnd_bits=28`,
which leaves room for AddressSanitizer's shadow memory; on a self-hosted runner it changes nothing, so set
that value on the host if the card says the sanitizer could not start.

The `check` job always passes `--no-repro`, so a project whose `.sloptriage.yml` sets `repro.enabled` still
runs no PoC there. The `repro` job needs a build recipe in the configuration ([Reproduction](repro.md)) and
takes a few minutes on a cold cache; delete the job (and `repro` from `needs:` in `report`) to check
references only. The `report` job runs even when `repro` fails, using the reference verdict. On a private
repository give `repro` `contents: read` so that it can check out the code.

Why it is safe with hostile issue text:

- No workflow expression with event data appears in any `run:` block; the issue is read from the
  event payload file. A test parses `action.yml` and every workflow, and `zizmor` and `actionlint` run
  in CI.
- The check job holds no write permission and no secret; the report job never checks out or runs code
  from the issue and only reads the verdict's structured fields.
- The comment is found by its `<!-- sloptriage -->` marker and author (`github-actions[bot]`, plus any
  logins listed in the `SLOPTRIAGE_COMMENT_AUTHOR` environment variable, for example when `post` runs
  locally with a personal token), so a user comment that copies the marker is never overwritten.
- Tests feed issues with `$(touch …)`, backticks, literal `${{ }}`, `"; curl … | sh`, Unicode bidi
  controls and a 1 MB body through the action's own shell steps and assert a correct verdict and no
  canary file.

To run only on some issues, add `if: contains(github.event.issue.labels.*.name, 'bug')` to the `check`
job, or filter on an issue-form field in the same way.

## Private vulnerability reports

There is deliberately no workflow for them:

- GitHub cannot trigger a workflow from a private vulnerability report (only webhooks fire).
- `GITHUB_TOKEN` has no permission for repository security advisories; the REST endpoint
  `GET /repos/{owner}/{repo}/security-advisories/{ghsa_id}` needs a fine-grained PAT with
  "Repository security advisories: read".
- Logs, job summaries and artifacts of a public repository are world-readable and would leak embargoed
  details.

Instead, on your own machine:

```bash
GITHUB_TOKEN=<fine-grained PAT> sloptriage check --advisory OWNER/REPO/GHSA-xxxx-xxxx-xxxx --repo .
```

The result is printed to the terminal only.
