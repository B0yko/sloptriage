"""Command line interface.

Exit codes: 0 success (or a class that ``--fail-on`` does not match), 1 when
``--fail-on`` matches, 2 for usage or configuration errors, 3 for
infrastructure errors (git or network).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sloptriage import __version__

EXIT_FAIL_ON = 1
EXIT_USAGE = 2
EXIT_INFRA = 3


class UsageError(Exception):
    pass


class InfraError(Exception):
    pass


def _err(msg: str) -> None:
    print(f"sloptriage: {msg}", file=sys.stderr)


# -- shared helpers ---------------------------------------------------------------------
def _load_cfg(args: argparse.Namespace, repo_path: Path | None) -> Any:
    from sloptriage.config import Config, ConfigError, find_config, load_config

    path = Path(args.config) if getattr(args, "config", None) else find_config(repo_path)
    try:
        cfg = load_config(path) if path else Config()
    except ConfigError as exc:
        raise UsageError(str(exc)) from exc
    return cfg


def _open_repo(location: str | None, cfg: Any) -> tuple[Any, str]:
    from sloptriage.index.gitobj import GitError, is_url, open_repo

    loc = location or cfg.repository
    if not loc:
        if (Path.cwd() / ".git").exists():
            loc = str(Path.cwd())
        else:
            raise UsageError(
                "no repository: pass --repo PATH|URL or set project.repository in .sloptriage.yml"
            )
    try:
        repo = open_repo(loc, update=is_url(loc))
    except GitError as exc:
        raise InfraError(str(exc)) from exc
    if not cfg.project:
        base = loc if is_url(loc) else str(Path(loc).expanduser().resolve())
        name = base.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
        cfg.project = name
        if not cfg.binaries:
            cfg.binaries = [name]
    return repo, loc


def _load_report(args: argparse.Namespace) -> Any:
    from sloptriage.ingest import IngestError, load_report
    from sloptriage.ingest.github import ISSUE_REF_RE, fetch_advisory, fetch_issue

    if getattr(args, "advisory", None):
        try:
            return fetch_advisory(args.advisory)
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - network or HTTP errors
            raise InfraError(f"cannot read advisory: {exc}") from exc
    if not args.report:
        raise UsageError("a REPORT argument (path, '-' or OWNER/REPO#N) is required")
    if args.report != "-" and not Path(args.report).exists() and ISSUE_REF_RE.match(args.report):
        try:
            return fetch_issue(args.report)
        except Exception as exc:  # noqa: BLE001
            raise InfraError(f"cannot read issue: {exc}") from exc
    try:
        return load_report(args.report)
    except IngestError as exc:
        raise UsageError(str(exc)) from exc


def _run_check(args: argparse.Namespace) -> tuple[dict[str, Any], Any]:
    from sloptriage.index import IndexSet
    from sloptriage.index.gitobj import GitError
    from sloptriage.render import build_verdict, validate_verdict
    from sloptriage.verdict import run_reference_check

    cfg = _load_cfg(args, Path(args.repo) if args.repo and Path(args.repo).exists() else None)
    report = _load_report(args)
    repo, loc = _open_repo(args.repo, cfg)
    iset = IndexSet(repo, loc, cfg.paths_ignore)
    try:
        result = run_reference_check(report, repo, iset, cfg, ref=args.ref)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    except GitError as exc:
        raise InfraError(str(exc)) from exc
    verdict = build_verdict(result, cfg)
    validate_verdict(verdict)
    iset.close()
    return verdict, cfg


# -- commands -------------------------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> int:
    from sloptriage.render import render_markdown, render_text

    verdict, _ = _run_check(args)
    if args.format == "json":
        text = json.dumps(verdict, indent=2, ensure_ascii=False) + "\n"
    elif args.format == "md":
        text = render_markdown(verdict)
    else:
        text = render_text(verdict)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.fail_on and verdict["references"]["class"] in args.fail_on.split(","):
        return EXIT_FAIL_ON
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from sloptriage.render import render_preflight

    args.advisory = None
    verdict, _ = _run_check(args)
    sys.stdout.write(render_preflight(verdict))
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    import jsonschema

    from sloptriage.post import PostError, issue_from_event, post_verdict

    try:
        issue = args.issue or issue_from_event(args.event)
    except (OSError, ValueError) as exc:
        raise UsageError(str(exc)) from exc
    try:
        verdict = json.loads(Path(args.verdict).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"{args.verdict}: {exc}") from exc
    try:
        post_verdict(verdict, issue, dry_run=args.dry_run)
    except jsonschema.ValidationError as exc:
        raise UsageError(f"{args.verdict}: not a valid verdict: {exc.message}") from exc
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    except PostError as exc:
        raise InfraError(str(exc)) from exc
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    import time

    from sloptriage.index import IndexSet
    from sloptriage.versions import VersionResolver, history_sample

    cfg = _load_cfg(args, None)
    repo, loc = _open_repo(args.repo, cfg)
    iset = IndexSet(repo, loc, cfg.paths_ignore)
    refs = [args.ref] if args.ref else [repo.default_branch()]
    if args.history:
        refs += history_sample(VersionResolver(repo, cfg.version_tags, cfg.project).tags)
    for ref in refs:
        sha = repo.resolve_commit(ref)
        if not sha:
            raise UsageError(f"{ref!r} is not a commit in the repository")
        cached = iset.is_cached(sha)
        t = time.perf_counter()
        idx = iset.get(sha)
        state = "cached" if cached else f"indexed in {time.perf_counter() - t:.1f}s"
        print(f"{ref} {sha[:12]} {idx.file_count()} files ({state})")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from sloptriage.initcfg import write_config

    target = Path(args.path or ".") / ".sloptriage.yml"
    if target.exists() and not args.force:
        raise UsageError(f"{target} exists (use --force to overwrite)")
    text = write_config(Path(args.path or "."))
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from sloptriage.demo_run import run_demo

    return run_demo(show=args.show)


def cmd_bench(args: argparse.Namespace) -> int:
    from sloptriage.bench.cli import bench_main

    return int(bench_main(args))


# -- parser -----------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sloptriage",
        description="Check a bug or security report against the project's code: cited files, "
        "functions, lines, stack frames and quoted code.",
    )
    p.add_argument("--version", action="version", version=f"sloptriage {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def report_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--repo", help="repository path or URL (a URL is bare-cloned into the cache)"
        )
        sp.add_argument(
            "--ref", help="check against this ref instead of the version the report names"
        )
        sp.add_argument("--config", help="path to .sloptriage.yml")

    c = sub.add_parser("check", help="check one report")
    c.add_argument("report", nargs="?", help="report file, '-' for stdin, or OWNER/REPO#N")
    report_opts(c)
    c.add_argument("--format", choices=("md", "json", "text"), default="text")
    c.add_argument("--output", "-o", help="write to a file instead of stdout")
    c.add_argument(
        "--fail-on",
        help="exit 1 when the class is one of these (comma-separated), e.g. refs_failed",
    )
    c.add_argument(
        "--advisory",
        help="read a draft repository security advisory OWNER/REPO/GHSA-... (needs a PAT)",
    )
    c.set_defaults(func=cmd_check)

    pf = sub.add_parser("preflight", help="check your own report before sending it")
    pf.add_argument("report")
    report_opts(pf)
    pf.set_defaults(func=cmd_preflight)

    po = sub.add_parser(
        "post", help="post or update the verdict comment and labels on a GitHub issue"
    )
    po.add_argument(
        "--verdict", required=True, help="verdict JSON written by 'check --format json'"
    )
    target = po.add_mutually_exclusive_group(required=True)
    target.add_argument("--issue", help="OWNER/REPO#N")
    target.add_argument(
        "--event", help="read the issue number from a workflow event payload ($GITHUB_EVENT_PATH)"
    )
    po.add_argument(
        "--dry-run", action="store_true", help="print the request bodies instead of sending them"
    )
    po.set_defaults(func=cmd_post)

    ix = sub.add_parser("index", help="prebuild the index cache")
    ix.add_argument("--repo", required=True)
    ix.add_argument("--ref")
    ix.add_argument("--config")
    ix.add_argument(
        "--history", action="store_true", help="also index the newest tag of every minor release"
    )
    ix.set_defaults(func=cmd_index)

    it = sub.add_parser("init", help="write a starter .sloptriage.yml for this repository")
    it.add_argument("path", nargs="?")
    it.add_argument("--force", action="store_true")
    it.set_defaults(func=cmd_init)

    de = sub.add_parser("demo", help="run on the bundled demo projects (no network)")
    de.add_argument("--show", help="print the full card for one demo report (number or file name)")
    de.set_defaults(func=cmd_demo)

    be = sub.add_parser("bench", help="benchmark on publicly disclosed curl reports")
    bsub = be.add_subparsers(dest="bench_command", required=True)
    bf = bsub.add_parser("fetch", help="download the report JSON files listed in the manifest")
    bf.add_argument("--split", default="all", choices=("dev", "heldout", "all"))
    br = bsub.add_parser("run", help="evaluate a split")
    br.add_argument("--split", required=True, choices=("dev", "heldout", "all"))
    br.add_argument("--repo", default="https://github.com/curl/curl")
    br.add_argument("--jobs", type=int, default=0)
    br.add_argument("--out", help="where to write the per-report rows (JSON)")
    bp = bsub.add_parser("report", help="aggregate rows into bench/results/<date>.json")
    bp.add_argument("rows", nargs="+", help="row files written by 'bench run'")
    bp.add_argument("--out", help="output path (default bench/results/<date>.json)")
    bp.add_argument("--hardware", default="unspecified")
    be.set_defaults(func=cmd_bench)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    try:
        return int(args.func(args))
    except UsageError as exc:
        _err(str(exc))
        return EXIT_USAGE
    except InfraError as exc:
        _err(str(exc))
        return EXIT_INFRA
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
