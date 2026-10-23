# The GitHub Action

`action.yml` is one composite action with a `mode` input.

| Input | Modes | Default | Meaning |
|---|---|---|---|
| `mode` | all | required | `check` or `post` |
| `verdict` | all | `verdict.json` | file written by `check`, read by `post` |
| `config` | check | `.sloptriage.yml` | configuration file |
| `token` | post | none | a token with `issues: write` (`github.token` in the workflow) |

The action installs sloptriage from its own source at the referenced commit (`uvx --from
"$GITHUB_ACTION_PATH"`), so pinning the action pins the tool.

## Job split

The example workflow ([`examples/workflows/triage-issues.yml`](../examples/workflows/triage-issues.yml))
runs on `issues: [opened, edited]`:

| Job | Permissions | Secrets | Does |
|---|---|---|---|
| `check` | `contents: read` | none | checks out the repository with full history and tags, runs `sloptriage check "$GITHUB_EVENT_PATH" --format json`, uploads `verdict.json` |
| `report` | `issues: write` | `github.token` only | downloads `verdict.json`, validates it against `schemas/verdict-v1.json`, renders the card, posts or updates one comment and the labels |

Why it is safe with hostile issue text:

- No workflow expression with event data appears in any `run:` block; the issue is read from the
  event payload file. A test parses `action.yml` and every workflow, and `zizmor` and `actionlint` run
  in CI.
- The check job holds no write permission and no secret; the report job never checks out or runs code
  from the issue and only reads the verdict's structured fields.
- The comment is found by its `<!-- sloptriage -->` marker and author (`github-actions[bot]`), so a
  user comment that copies the marker is never overwritten.
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
