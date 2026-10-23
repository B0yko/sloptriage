from __future__ import annotations

import json
from pathlib import Path

import httpx

from sloptriage.bench.fetch import USER_AGENT, fetch_reports


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, headers={"User-Agent": USER_AGENT})


def test_fetch_rate_limit_user_agent_and_cache(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        rid = int(request.url.path.split("/")[-1].removesuffix(".json"))
        return httpx.Response(200, json={"id": rid, "vulnerability_information": "x"})

    clock = FakeClock()
    (tmp_path / "3.json").write_text("{}")
    res = fetch_reports([1, 2, 3], tmp_path, client=_client(httpx.MockTransport(handle)),
                        sleep=clock.sleep, clock=clock.clock)
    assert res.fetched == [1, 2] and res.cached == [3]
    assert all(r.headers["User-Agent"].startswith("sloptriage/") for r in seen)
    assert "github.com/B0yko/sloptriage" in seen[0].headers["User-Agent"]
    # the second request waited for the 1 s interval
    assert clock.sleeps and abs(sum(clock.sleeps) - 1.0) < 1e-6
    assert json.loads((tmp_path / "1.json").read_text())["id"] == 1


def test_fetch_honours_retry_after(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"id": 5})

    clock = FakeClock()
    res = fetch_reports([5], tmp_path, client=_client(httpx.MockTransport(handle)), sleep=clock.sleep, clock=clock.clock)
    assert res.fetched == [5]
    assert 7.0 in clock.sleeps


def test_fetch_stops_on_repeated_errors(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    clock = FakeClock()
    res = fetch_reports(range(1, 20), tmp_path, client=_client(httpx.MockTransport(handle)),
                        sleep=clock.sleep, clock=clock.clock, max_consecutive_errors=3)
    assert res.stopped_early
    assert len(res.failed) == 3


def test_fetch_rejects_unexpected_documents(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 999})

    clock = FakeClock()
    res = fetch_reports([1], tmp_path, client=_client(httpx.MockTransport(handle)), sleep=clock.sleep, clock=clock.clock)
    assert res.failed == {1: "unexpected document shape"}
    assert not (tmp_path / "1.json").exists()
