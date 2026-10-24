# Changelog

## Unreleased

- `sloptriage bench repro`: runs the PoCs of real curl reports (17 resolved held-out reports and 21 on the
  public list) in the sandbox. None reproduced; ten of the 17 resolved reports could not be tested. Results
  in `bench/results/repro-*.json`.
- Sandbox: `/tmp` is a second size-limited tmpfs; a PoC that needs a file, service, tool, protocol or
  runnable script it does not have is `poc_unsupported` with that reason; frames of installed shared
  libraries and build-id suffixes are read; a sanitizer that cannot start on the host is `build_failed`.
- The Action's `repro` mode lowers `vm.mmap_rnd_bits` on GitHub-hosted runners so that the sanitizer can start.

## 0.1.0 (2026-10-24)

First release.

- Reference check: extracts every file, function, line, version, stack frame and quoted snippet a report
  cites and verifies each one at the version the report names, with permalinks as evidence.
- Inputs: Markdown or text files, stdin, `.eml`, GitHub issues and Actions event payloads, public
  HackerOne report JSON, draft security advisories (terminal only).
- Index straight from git objects with tree-sitter definitions for C, C++, Python, JavaScript, TypeScript,
  Go and Rust, cached per blob.
- Verdict JSON (`schemas/verdict-v1.json`), a neutral Markdown card, labels, and a reporter checklist
  (`preflight`).
- Reproduction (opt-in, `--repro`): builds the version a report names with AddressSanitizer and
  UndefinedBehaviorSanitizer and runs its PoC (C, C++, shell, Python, input files, local server plus
  client) up to three times in a container with no network, a read-only root, a non-root user, no
  capabilities and limits on processes, memory, CPU, time and output. No host mode. Presets
  `cmake-asan`, `autotools-asan`, `meson-asan` and `python-pip`; examples for curl, a CMake project and a
  Python package; labels `triage:reproduced` and `triage:not-reproduced`; `sloptriage demo --repro`.
- Composite GitHub Action with a read-only check job, an optional `repro` job without token
  permissions and a separate issues-write report job.
- Offline demo with two small projects and 60 labelled synthetic reports.
- Benchmark on 658 disclosed curl HackerOne reports with a frozen dev/held-out split.
