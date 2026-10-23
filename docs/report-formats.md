# Report formats

Every input becomes one `Report`:
`source, id, title, body_markdown, attachments[], claimed_version?, created_at?`.

| Input | How it is recognised | Body | Notes |
|---|---|---|---|
| Markdown or text file | any other file | the file | the first non-empty line is the title |
| stdin | `-` | stdin | |
| E-mail | `.eml` or RFC 822 headers | `text/plain` and `text/markdown` parts; HTML parts converted to text when there is no plain part | attachments (up to 2 MB each) become artefacts; their names are flattened so they cannot point outside a directory |
| GitHub issue | `OWNER/REPO#N` argument | `body` | read through the REST API with `GITHUB_TOKEN` if set |
| GitHub Actions event | JSON with an `issue` object | `issue.body` | `id` is `owner/repo#N`; `created_at` is the issue's |
| HackerOne report | JSON with `vulnerability_information` | `vulnerability_information` | see below |
| Draft security advisory | `--advisory OWNER/REPO/GHSA-…` | `summary` + `description` | needs a PAT with "Repository security advisories: read"; output goes to the terminal |

HTML is converted with Python's `html.parser`: scripts, styles and frames are dropped, `<pre>` becomes a
fenced block, `<code>` becomes inline code. Nothing is rendered and no URL is fetched.

## HackerOne public report JSON

Pinned on 2026-10-23 from `https://hackerone.com/reports/2298307.json` (a disclosed curl report). The
fields sloptriage reads:

| Field | Type | Use |
|---|---|---|
| `id` | integer | report id |
| `title` | string | title |
| `vulnerability_information` | string (Markdown) | the body |
| `submitted_at`, `created_at` | ISO 8601 string | the report date (`submitted_at`, else `created_at`), used to pick the default branch commit when no version is given |
| `substate` | `resolved`, `not-applicable`, `informative`, `spam`, `duplicate`, … | benchmark label (only in the manifest) |
| `disclosed_at` | ISO 8601 string | benchmark era (only in the manifest) |

Other fields present in that file and not used: `global_id`, `url`, `state`, `severity_rating`,
`readable_substate`, `reporter`, `team`, `weakness`, `severity`, `structured_scope`, `attachments`,
`cve_ids`, `vote_count`, `summaries` and a set of viewer-permission flags. The JSON carries no comment
thread. Attachments are never downloaded.
