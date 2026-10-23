# Contributing

Thanks for helping. Bug reports, false flags on real reports, new stack-trace formats and grammar
coverage are especially welcome.

## Development

```bash
git clone https://github.com/B0yko/sloptriage && cd sloptriage
uv sync
uv run pytest -q              # tests never open network connections (a fixture blocks sockets)
uv run ruff check src tests scripts eval && uv run ruff format --check src tests
uv run mypy                   # strict on src/
uv run sloptriage demo
```

## Rules of thumb

- Keep it deterministic: no models, no network at check time.
- A change to extraction or checks must keep the synthetic set (`tests/test_demo.py`) and the dev split
  free of false flags on valid reports. Never tune anything on the held-out split.
- Card wording stays neutral and specific (see `docs/adr/0003-neutral-wording.md`).
- Benchmark files hold IDs and derived fields only, never report text.
- Workflows: pin third-party actions by full commit SHA and keep `${{ }}` expressions out of `run:` blocks.

## Reporting a false flag

Open an issue with the public URL of the report (or a minimal synthetic copy), the repository and the
version, and the `sloptriage check --format json` output.
