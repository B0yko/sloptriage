"""List disclosed reports of one HackerOne programme (IDs, substate, disclosure date).

Uses the public hacktivity search that hackerone.com's own pages use. It returns
identifiers and outcome fields only; report text is fetched later, on the user's
machine, by ``sloptriage bench fetch``. One request per second.

    uv run python scripts/enumerate_hackerone.py curl > enumeration.json
"""

from __future__ import annotations

import json
import sys
import time

import httpx

from sloptriage.bench.fetch import USER_AGENT

QUERY = """query Hacktivity($q: String!, $from: Int, $size: Int, $sort: SortInput!) {
  search(index: CompleteHacktivityReportIndex, query_string: $q, from: $from, size: $size, sort: $sort) {
    total_count
    nodes { ... on HacktivityDocument { report { _id substate disclosed_at } } }
  }
}"""


def main(team: str) -> None:
    out: dict[int, dict[str, str]] = {}
    total = None
    offset = 0
    size = 100
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0) as client:
        while total is None or offset < total:
            body = {
                "operationName": "Hacktivity",
                "query": QUERY,
                "variables": {
                    "q": f'team:("{team}") AND disclosed:true',
                    "from": offset,
                    "size": size,
                    "sort": {"field": "disclosed_at", "direction": "ASC"},
                },
            }
            resp = client.post("https://hackerone.com/graphql", json=body)
            resp.raise_for_status()
            search = resp.json()["data"]["search"]
            total = int(search["total_count"])
            for node in search["nodes"]:
                rep = node["report"]
                out[int(rep["_id"])] = {
                    "substate": rep["substate"],
                    "disclosed_at": rep["disclosed_at"][:10],
                }
            offset += size
            time.sleep(1.0)
    json.dump(
        {
            "team": team,
            "total_count": total,
            "reports": {str(k): v for k, v in sorted(out.items())},
        },
        sys.stdout,
        indent=1,
    )
    print(f"{len(out)} of {total} reports", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "curl")
