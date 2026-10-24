# Reproduction

Opt-in. `sloptriage check REPORT --repro` builds the project at the version the report names, with
AddressSanitizer and UndefinedBehaviorSanitizer, and runs the report's PoC in a locked-down container.
It records whether a crash happens and whether it happens where the report says.

It needs Docker or Podman. Without one, `--repro` exits with code 3 and nothing runs; there is no mode
that runs a PoC on the host. `--no-repro` overrides `repro.enabled: true` in the configuration.

```bash
sloptriage demo --repro                      # the 30 demo PoCs; builds 5 images the first time (2 toolchains, 3 builds)
sloptriage check report.md --repo . --repro  # your own project (needs repro.build in .sloptriage.yml)
```

## What a run does

1. **Candidates.** The extractor's PoC blocks (and text attachments `.c .cc .cpp .cxx .py .sh .bash`)
   become candidates, at most `repro.limits.candidates` (5) per report, in report order. A PoC is passed
   to the container byte for byte; sloptriage never edits, completes or repairs one. Only a terminal
   transcript (a block whose first line starts with `$ `) is trimmed to the prompted lines, and a base64 or
   hex block is decoded.
2. **Eligibility.** The commit the report resolves to must be reachable from a release tag or from the
   default branch. Any other SHA gets `poc_unsupported` with that reason.
3. **Images.** Built once per (project, commit, recipe) and cached by the container runtime:
   - *image stage*, with network: toolchain and build dependencies from the recipe. For Python it also
     resolves the dependency names the project's `requirements.txt` and `pyproject.toml` declare
     (`[project].dependencies` and `[build-system].requires`, read as data) into wheels inside the image;
     nothing the report contains enters this stage; its version only chooses which commit's manifests
     are read.
   - *project stage*, `docker build --network none`: the source of that commit (as `git archive` writes
     it) is built with sanitizers into `/opt/project`; the source stays at `/build/src`.
4. **Runs.** Each candidate runs up to `repro.limits.runs` (3) times, each in a fresh container with the
   hardening below. A compile failure, a timeout or an output flood stops the repetitions. Output is parsed for sanitizer
   reports (AddressSanitizer, UndefinedBehaviorSanitizer, MemorySanitizer, ThreadSanitizer), Python
   tracebacks, fatal signals and exit codes.

## Verdicts

| Verdict | Meaning |
|---|---|
| `reproduced` | every run crashed the same way, and the top frame inside the project is a function the report names, or the error type matches the type the report claims and the crash is in a file the report names (or the report names no function or file at all) |
| `crashed_elsewhere` | every run crashed, but not where or how the report says: inside the PoC's own code, in another function or file, or by exceeding the memory limit |
| `not_reproduced` | no run crashed |
| `flaky` | some runs crashed and some did not, or the crashes differed |
| `poc_build_failed` | the C or C++ PoC did not compile against the project; the compiler output is in the card |
| `poc_missing` | no PoC in the report text or attachments |
| `poc_unsupported` | an unsupported language, a disabled runner, an input file with no harness, a commit that is not eligible, or a PoC that needs the real network, a display or a command that is not installed in the image (recognised from name-resolution, unreachable-network, no-display and "command not found" failures) |
| `build_failed` | the project could not be built in the sandbox: a limit of the build recipe, never the reporter's fault |
| `timeout` | the PoC did not finish within `repro.limits.timeout`, or printed more output than the limit and was stopped |

A report text that only contains a sanitizer report is not a crash. A PoC that prints one and exits 0 is a
clean run: a sanitizer report counts only together with a non-zero exit status. The exception is a recipe
whose sanitizer flags leave UndefinedBehaviorSanitizer able to report and carry on (the defaults pass
`-fno-sanitize-recover=undefined`, so a UBSan error stops the program). Exit statuses that mean a broken
pipe or a termination request are not crashes, and a plain `SIGKILL` is a crash outside the project;
"exceeded the memory limit" is said only when the runtime reports an out-of-memory kill.

In the JSON, `reproduction.candidate` is the PoC that decided the verdict and `reproduction.match` says how
the crash related to the report: `function_and_type` and `type_and_file` agree with everything it says,
`function` means the report claims no error type, `function_type_differs` is a function the report names
with another error type than it claims (still `reproduced`, and worded that way), and `type_only` means the
type fits and the report names no function or file.

`not_reproduced` does not show the problem is absent. The PoC may need another build, input or environment.

## Runners

| PoC | How it runs |
|---|---|
| `c`, `cpp` | compiled in the container against `/opt/project` with the recipe's sanitizer flags and `-O0` (the project is built with the recipe's own optimisation level; the compiler would otherwise delete stores nothing reads, and the crash with them), then run |
| `shell` | `bash -e -o pipefail` with the project's binaries on `PATH` |
| `python` | `python3 -X faulthandler` with the project installed; a fenced Python block that imports the project and does something is also taken as a PoC when the report has no labelled one |
| `input` | a base64 or hex block is decoded to a file and fed to `repro.harness`, where `{input}` stands for its path |
| two parts | a block introduced as a server or listener starts in the background in the same container; the client PoC runs once something listens (up to 5 s), and both outputs are kept; with several server blocks only the first is started and the others are reported as skipped |

## Configuration

```yaml
repro:
  enabled: false            # true makes `check` run PoCs without --repro; --no-repro overrides
  runtime: auto             # auto, docker or podman
  runners: [c, cpp, shell, python, input]
  harness: "parsekit header --file {input}"
  limits:                   # per container run unless stated
    timeout: 20             # seconds, wall clock
    build_timeout: 1800     # seconds per image build
    memory: 512m            # swap off
    cpus: 1.0
    pids: 128
    tmpfs: 64m              # size of each of /work and /tmp, the writable places
    output_bytes: 200000    # captured per stream; a run printing far more is stopped
    runs: 3                 # repetitions per PoC
    candidates: 5           # PoCs tried per report
  build:
    preset: cmake-asan      # autotools-asan, cmake-asan, meson-asan or python-pip
    base_image: debian:trixie-slim
    packages: [libssl-dev]  # added to the preset's apt packages
    configure: [...]        # each replaces the preset's commands when given
    build: [...]
    install: [...]
    link: [parsekit]        # libraries C and C++ PoCs link with; default: the project name
    env: {KEY: value}       # build-time variables
    sanitizer_flags: [...]  # default: -fsanitize=address,undefined -fno-sanitize-recover=undefined
                            #          -fno-omit-frame-pointer -g -O1
    requirements: [requirements.txt]  # Python: manifests whose dependency names are resolved
```

Build commands run in a Debian or Ubuntu based image, installing into `/opt/project`. Commands use the
variable `SAN_FLAGS`, which holds the sanitizer flags (`CFLAGS`, `CXXFLAGS` and `LDFLAGS` are set to it).
If you replace `configure`, `build` and `install`, replace all three together.

Presets:

| Preset | Base image | Configure and build |
|---|---|---|
| `cmake-asan` | `debian:trixie-slim` | `cmake -G Ninja` with the flags in `CMAKE_C_FLAGS` and the linker flags, then `cmake --build` and `--install` |
| `autotools-asan` | `debian:trixie-slim` | `autoreconf -fi` when there is no `configure`, `./configure --prefix=/opt/project`, `make`, `make install` |
| `meson-asan` | `debian:trixie-slim` | `meson setup -Db_sanitize=address,undefined`, `meson compile`, `meson install` |
| `python-pip` | `python:3.12-slim` | `pip install --no-index --no-build-isolation --no-deps` of the checked-out source, from wheels built in the image stage |

Examples: [`examples/parsekit`](../examples/parsekit/.sloptriage.yml) (CMake, C),
[`examples/kvconf`](../examples/kvconf/.sloptriage.yml) (Python package) and
[`examples/curl`](../examples/curl/.sloptriage.yml) (autotools).

## Hardening

Each property is asserted by a test on the command line (`tests/test_repro_runtime.py`), by a probe from
inside a container (`tests/test_repro_docker.py`, run where Docker is available), or both.

| Property | Flag or mechanism | Probe |
|---|---|---|
| no network (loopback works) | `--network none` | connections to public and metadata addresses fail, name resolution fails, loopback succeeds |
| nothing writable but `/work`, `/tmp` and `/dev/shm` | `--read-only`; tmpfs mounts at `/work` and `/tmp` with `size=` (PoCs write to `/tmp` as a matter of course); the runtime's default `/dev/shm` (64 MB, not executable); all of it counts against the memory limit | writes to `/etc`, `/usr`, `/`, `/opt`, `/var/tmp` are refused; filling `/work` or `/dev/shm` stops at its size |
| non-root | `--user 10001:10001` | `id -u` is 10001 |
| no capabilities, no privilege gain, seccomp on | `--cap-drop ALL`, `--security-opt no-new-privileges` | `CapEff` and `CapBnd` are 0, `NoNewPrivs` is 1, `Seccomp` is 2 |
| process limit | `--pids-limit` | a bounded spawn loop is refused at the limit |
| memory limit, swap off | `--memory`, `--memory-swap` | a memory bomb is killed and recorded; the cgroup shows no swap |
| open files, core dumps | `--ulimit nofile`, `--ulimit core=0` | `ulimit -n` is 1024 and `ulimit -c` is 0 |
| CPU limit | `--cpus` | the cgroup shows the quota |
| wall-clock limit | the tool kills the container; a watchdog inside the script also ends it 15 s after the limit if the tool is gone; a cancelled job (`SIGTERM`) removes the container before the tool exits | an endless loop is stopped and the container removed; the watchdog ends a loop by itself |
| output cap | the start and the end of each stream are kept; a flood kills the container | endless output is truncated and the run stopped |
| no host data | no mounts, devices, socket or `--env-file`; only explicit `-e KEY=VALUE` | host variables, the Docker socket and host paths are not visible |
| symlink tricks | artefacts are plain files in a tar built by the tool | links in `/work` lead nowhere useful |
| clean-up | every container is inspected, then removed with its volumes (`rm -f -v`) | no labelled container is left behind |
| no pulls while running | `--pull never` | images come only from the build steps |

Containers carry the label `sloptriage=1`. `ASAN_OPTIONS=detect_leaks=0` is set because LeakSanitizer needs
`ptrace`, which dropping all capabilities removes; leak reports are out of scope.

## Measured

On the synthetic set (`sloptriage demo --repro`, 2026-10-24, Mac Studio M4 Max, 128 GB, Docker 29.5.2 in a
Colima VM, arm64; `debian:trixie-slim` with GCC 14 and `python:3.12-slim`): 20 of the 20 reports with a
working PoC reproduce, and 0 of the 10 low-quality reports with a PoC do. Of those 10, four end in
`crashed_elsewhere` (the PoC overflows its own buffer or never calls the library), two in
`poc_build_failed` (it calls functions that do not exist) and four in `not_reproduced`. The demo took 30
seconds once the images existed; the first run, which built them, took 58 seconds on that machine (the
base images were partly present already, so a fresh machine also pays for pulling them). These labels come from how the reports
were written, so this checks that the tool agrees with the construction; it is not an accuracy figure for
real reports, which were not run. curl 8.10.1 builds with OpenSSL under AddressSanitizer and
UndefinedBehaviorSanitizer in the sandbox, and `curl --version` and a small libcurl program run in it.

## Limits

- The container runtime is the trust boundary (rootless Podman is a good choice where you can use it, but it
  is not covered by the tests). See [ADR 0006](adr/0006-container-hardening-no-host-mode.md)
  and the [security model](security-model.md).
- C, C++, Python and shell only. PoCs that need the real network, hardware, a GUI or a service other than
  a loopback server are `poc_unsupported`.
- A PoC controls what it prints. A fabricated report with a non-zero exit status would pass the exit-status
  check; the card shows the output so a person can read it.
- The first build of a project is slow (a toolchain image, then the project with sanitizers). Later runs on
  the same commit reuse the images.
- On a Linux host whose kernel randomises memory mappings very widely (`vm.mmap_rnd_bits` above 28 on x86-64,
  the default on recent GitHub-hosted runners), the sanitizer runtime can fail to start inside any container,
  because containers share the host kernel. The result is `build_failed` with the fix in its reason:
  `sudo sysctl -w vm.mmap_rnd_bits=28`. The Action's `repro` mode does this on GitHub-hosted runners.
- An out-of-memory kill is always `crashed_elsewhere`, even when the report claims memory exhaustion.
- If the tool is killed abruptly, a container can outlive it for at most the time limit plus 15 s (the
  watchdog inside it). Leftovers carry the label: `docker rm -f -v $(docker ps -aq --filter label=sloptriage=1)`.
- A build that exceeds `build_timeout` stops the client; the daemon may finish the build in the background.
  Build contexts and logs are held in memory, so very large repositories need that much RAM.
- Docker is tested; Podman receives the same flags and is not covered by the tests.
- With Docker on macOS (Colima, Docker Desktop) nothing is shared with the host, so no directory needs to
  be mounted.
