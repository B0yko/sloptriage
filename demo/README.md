# Demo projects and synthetic reports

Everything in this directory was written for sloptriage and is licensed under the Apache License 2.0.

- `projects/parsekit/` – a small C99 URL and HTTP header parser with a CLI (CMake), as three release
  snapshots. Two memory-safety bugs are planted on purpose: a one-byte heap overflow in
  `pk_header_join()` (since 1.1.0) and a use-after-free in `pk_url_normalize()` (1.2.0).
  See `projects/parsekit/HISTORY.md`.
- `projects/kvconf/` – a small Python configuration parser, two release snapshots. Version 0.2.0
  added `${name}` interpolation without cycle detection, so cyclic references raise `RecursionError`.
- `reports/` – 60 reports against these projects: 20 valid reports with correct references and
  working PoCs, and 40 low-quality reports that cover the failure modes sloptriage targets.
  `reports/labels.json` gives each report's label and failure modes. Labels hold by construction:
  `scripts/make_demo_reports.py` reads every line number, function span and quoted line of a valid
  report from the sources at the stated version.

`sloptriage demo` turns each project into a small git repository (one commit and one tag per
version, fixed author and dates) in the user cache and runs the checks on the reports.
