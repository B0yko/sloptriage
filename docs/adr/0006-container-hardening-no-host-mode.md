# ADR 0006: PoCs run only in a hardened container; there is no host mode

Status: accepted (2026-10-24)

## Context

Running a report's proof of concept shows whether the claimed crash happens, which is evidence a
reference check cannot give. It also means executing code written by a stranger, after building a
project the stranger chose a version of, on a maintainer's machine or a CI runner. A report can contain
anything: a fork bomb, a memory bomb, an endless loop, a flood of output, symlink tricks, a build
script, a request to a network host, a counterfeit sanitizer report.

## Decision

1. **Containers only.** Reproduction detects a Docker or Podman CLI whose daemon answers, and refuses
   to run anything without one. There is no flag, environment variable or configuration key that runs a
   PoC on the host. Reproduction is opt-in (`--repro` or `repro.enabled: true`).
2. **One fresh container per attempt**, started with all of these, each asserted by a test:
   `--network none` (loopback still works); `--read-only` with size-limited tmpfs mounts at `/work` and `/tmp`; a
   non-root user; `--cap-drop ALL`; `--security-opt no-new-privileges` with the runtime's default
   seccomp filter left on; `--pids-limit`; `--memory` with swap switched off; `--cpus`; `--ulimit core=0`
   and `nofile`; an init process to reap children; a wall-clock timeout that kills the container; and a
   cap on captured output, with the container killed when a run floods it.
3. **Nothing from the host is shared.** There are no mounts, no devices, no Docker socket, no
   `--env-file` and no inherited variables. The environment is exactly the `-e KEY=VALUE` pairs the tool
   passes (sanitizer options and a few paths). Artefacts reach the container as a tar stream on stdin
   that the tool builds itself from plain, flat file names: no links, no directories, no special bits.
4. **Three build steps with different network rights.** The image stage (toolchain, build
   dependencies; for Python, wheels of the dependencies the project's manifests declare) has network and
   takes its inputs only from the recipe and those manifests, read as data, never from the report. The
   project stage copies the source of one commit into the image and builds it with sanitizers under
   `docker build --network none`. The PoC stage is the hardened run above. Images are cached per
   project, commit and recipe hash.
5. **Only trusted commits are built.** A commit is built only if it is reachable from a release tag or
   from the default branch of the checked repository. Any other SHA (a fork, a pull request) gets
   `poc_unsupported` with the reason, so a build script from outside the project never runs.
6. **Leak detection is off** (`ASAN_OPTIONS=detect_leaks=0`): LeakSanitizer needs `ptrace`, which
   dropping all capabilities removes. Leak reports are out of scope.
7. **A sanitizer report is believed only together with a crash.** The report text must come with a
   non-zero exit status. A PoC that merely prints a report and exits 0 is a clean run. The exception is
   a recipe that leaves UndefinedBehaviorSanitizer able to report and carry on; the default recipes pass
   `-fno-sanitize-recover=undefined`, so a UBSan error stops the program.
8. **The tool is not the only thing that stops a run.** A watchdog inside the container's script ends
   everything the sandbox user owns shortly after the wall-clock limit, so a tool that was killed
   leaves no endless loop behind; `SIGTERM` makes the tool remove its container before it exits; the
   runtime never pulls an image while running.
9. **The tool's own markers are random per run** and written before any PoC code runs, so a PoC that
   exits 125, 252 or 253 is not mistaken for a runtime failure or a compile failure.

## Consequences

- The container runtime is the trust boundary. A kernel or runtime escape would defeat it. Keep the
  runtime patched; for reports from unknown people use a dedicated machine or an ephemeral CI runner,
  and rootless Podman where you can (it is not covered by the tests). In the Action the `repro` job runs on a GitHub-hosted runner with no token
  permissions.
- Access to a Docker daemon is itself powerful. The tool never mounts the socket into anything, so the
  published CLI image cannot run reproduction; install the CLI on a host that has Docker.
- A PoC can still print a counterfeit report and exit non-zero. The runs are repeated, the crash must
  match the report's claim, and the card shows the output, but a determined author can fake a crash;
  reproduction is evidence for a maintainer to read, not proof.
- PoCs that need the real network, hardware or a display are reported as `poc_unsupported` rather than as
  clean runs; the tool recognises them by the failures they produce (name resolution, unreachable
  network, no display).
- The project stage runs the project's own build scripts as root inside the build container, with no
  network. That is why
  only release tags and the default branch are eligible.
- A build that fails is reported as `build_failed` and worded as a limit of the recipe, never as the
  reporter's fault.
