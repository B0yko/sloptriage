"""Polite downloader for public HackerOne report JSON files.

The repository never stores report text. ``bench fetch`` downloads the public
JSON for the IDs in the committed manifest into the user's cache, one request
per second at most, with a User-Agent that names this project.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sloptriage import __version__

if TYPE_CHECKING:
    import httpx

USER_AGENT = f"sloptriage/{__version__} (+https://github.com/B0yko/sloptriage)"
REPORT_URL = "https://hackerone.com/reports/{id}.json"


@dataclass
class FetchResult:
    fetched: list[int] = field(default_factory=list)
    cached: list[int] = field(default_factory=list)
    failed: dict[int, str] = field(default_factory=dict)
    stopped_early: bool = False

    @property
    def requests(self) -> int:
        return len(self.fetched) + len(self.failed)


def body_sha256(doc: dict[str, Any]) -> str:
    """Hash of the report body alone, stable across vote-count changes."""
    body = doc.get("vulnerability_information") or ""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _retry_after(resp: httpx.Response, default: float) -> float:
    value = resp.headers.get("Retry-After", "")
    try:
        return max(float(value), default)
    except ValueError:
        return max(default, 30.0)


def fetch_reports(
    ids: Iterable[int],
    dest: Path,
    *,
    client: httpx.Client | None = None,
    min_interval: float = 1.0,
    max_consecutive_errors: int = 5,
    max_retries_429: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = lambda _msg: None,
) -> FetchResult:
    """Download ``<id>.json`` for each id that is not cached yet."""
    import httpx

    dest.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30.0,
            follow_redirects=False,
        )
    result = FetchResult()
    consecutive_errors = 0
    last_request = -1e9
    try:
        for report_id in ids:
            target = dest / f"{report_id}.json"
            if target.exists():
                result.cached.append(report_id)
                continue
            attempts_429 = 0
            while True:
                wait = min_interval - (clock() - last_request)
                if wait > 0:
                    sleep(wait)
                last_request = clock()
                try:
                    resp = client.get(REPORT_URL.format(id=report_id))
                except httpx.HTTPError as exc:
                    result.failed[report_id] = f"transport error: {type(exc).__name__}"
                    consecutive_errors += 1
                    break
                if resp.status_code == 429 and attempts_429 < max_retries_429:
                    attempts_429 += 1
                    delay = _retry_after(resp, min_interval)
                    log(f"429 for {report_id}; waiting {delay:.0f}s")
                    sleep(delay)
                    continue
                if resp.status_code != 200:
                    result.failed[report_id] = f"HTTP {resp.status_code}"
                    consecutive_errors += 1
                    break
                try:
                    doc = resp.json()
                except json.JSONDecodeError:
                    result.failed[report_id] = "response is not JSON"
                    consecutive_errors += 1
                    break
                if not isinstance(doc, dict) or doc.get("id") != report_id:
                    result.failed[report_id] = "unexpected document shape"
                    consecutive_errors += 1
                    break
                tmp = target.with_suffix(".json.part")
                tmp.write_bytes(resp.content)
                tmp.replace(target)
                result.fetched.append(report_id)
                consecutive_errors = 0
                log(f"fetched {report_id}")
                break
            if consecutive_errors >= max_consecutive_errors:
                result.stopped_early = True
                log(f"stopping after {consecutive_errors} consecutive errors")
                break
    finally:
        if own_client:
            client.close()
    return result
