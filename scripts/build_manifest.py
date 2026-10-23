"""Build the frozen benchmark manifest from an enumeration, the slop list and fetched JSON.

    uv run python scripts/build_manifest.py enumeration.json slop.md <gist-revision>

Writes bench/manifest/{reports.json, split.json, MANIFEST.sha256}. Only IDs, outcome
fields, dates and hashes are written; report text stays in the user's cache.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

from sloptriage.bench.fetch import body_sha256, file_sha256
from sloptriage.bench.manifest import era_for, label_for, stratified_split, validate_manifest
from sloptriage.paths import cache_dir

SEED = 20261023
DEV_SHARE = 0.4
GIST = "https://gist.github.com/bagder/07f7581f6e3d78ef37dfbfc81fd1d1cd"
OUT = Path(__file__).resolve().parent.parent / "bench" / "manifest"


def main(enum_path: str, gist_path: str, revision: str) -> None:
    enum = json.loads(Path(enum_path).read_text())
    slop = {int(x) for x in re.findall(r"hackerone\.com/reports/(\d+)", Path(gist_path).read_text())}
    store = cache_dir("bench", "hackerone")
    reports = []
    missing = []
    for key, meta in sorted(enum["reports"].items(), key=lambda kv: int(kv[0])):
        rid = int(key)
        path = store / f"{rid}.json"
        if not path.exists():
            missing.append(rid)
            continue
        doc = json.loads(path.read_text())
        reports.append(
            {
                "id": rid,
                "url": f"https://hackerone.com/reports/{rid}",
                "substate": meta["substate"],
                "label": label_for(meta["substate"]),
                "slop_list": rid in slop,
                "disclosed_at": meta["disclosed_at"],
                "era": era_for(meta["disclosed_at"]),
                "json_sha256": file_sha256(path),
                "body_sha256": body_sha256(doc),
            }
        )
    manifest = {
        "schema": "sloptriage-bench-manifest/1",
        "project": "curl",
        "source": "hackerone",
        "enumerated_at": date.today().isoformat(),
        "slop_list_source": {"url": GIST, "revision": revision},
        "reports": reports,
    }
    validate_manifest(manifest)
    split = stratified_split(reports, seed=SEED, dev_share=DEV_SHARE)
    split_doc = {
        "schema": "sloptriage-bench-split/1",
        "seed": SEED,
        "dev_share": DEV_SHARE,
        "strata": ["label", "era"],
        "dev": split["dev"],
        "heldout": split["heldout"],
        "excluded": sorted(r["id"] for r in reports if r["label"] == "excluded"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reports.json").write_text(json.dumps(manifest, indent=1) + "\n")
    (OUT / "split.json").write_text(json.dumps(split_doc, indent=1) + "\n")
    lines = []
    for name in ("reports.json", "split.json"):
        lines.append(f"{hashlib.sha256((OUT / name).read_bytes()).hexdigest()}  {name}")
    (OUT / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    print(f"{len(reports)} reports, {len(missing)} missing: {missing}", file=sys.stderr)
    print(f"dev {len(split['dev'])}, heldout {len(split['heldout'])}", file=sys.stderr)
    print(f"slop-listed ids not in enumeration: {sorted(slop - {r['id'] for r in reports})}", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:4])
