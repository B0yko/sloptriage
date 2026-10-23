"""The frozen benchmark manifest: report IDs, outcome labels, era and split.

Only identifiers, enumerated outcome fields, dates and hashes are stored.
Report text, titles and reporter names never enter the repository.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from sloptriage.paths import bundled

LABELS = {
    "resolved": "valid",
    "not-applicable": "invalid",
    "informative": "invalid",
    "spam": "invalid",
    "duplicate": "excluded",
}
ERA_CUTOFF = "2023-01-01"


def label_for(substate: str) -> str:
    return LABELS.get(substate, "excluded")


def era_for(disclosed_at: str) -> str:
    return "pre2023" if disclosed_at[:10] < ERA_CUTOFF else "post2023"


def manifest_dir() -> Path:
    return bundled("bench", "manifest")


def load_json(name: str) -> Any:
    return json.loads((manifest_dir() / name).read_text(encoding="utf-8"))


def load_reports() -> list[dict[str, Any]]:
    doc = load_json("reports.json")
    validate_manifest(doc)
    reports: list[dict[str, Any]] = doc["reports"]
    return reports


def load_split() -> dict[str, Any]:
    split: dict[str, Any] = load_json("split.json")
    return split


def validate_manifest(doc: Any) -> None:
    import jsonschema

    schema = json.loads(bundled("schemas", "bench-manifest-v1.json").read_text(encoding="utf-8"))
    jsonschema.validate(doc, schema)


def stratified_split(
    reports: list[dict[str, Any]], *, seed: int, dev_share: float
) -> dict[str, list[int]]:
    """Split labelled reports into dev and held-out, stratified by label and era."""
    strata: dict[tuple[str, str], list[int]] = defaultdict(list)
    for rep in reports:
        if rep["label"] == "excluded":
            continue
        strata[(rep["label"], rep["era"])].append(int(rep["id"]))
    rng = random.Random(seed)
    dev: list[int] = []
    heldout: list[int] = []
    for key in sorted(strata):
        ids = sorted(strata[key])
        rng.shuffle(ids)
        cut = round(len(ids) * dev_share)
        dev.extend(ids[:cut])
        heldout.extend(ids[cut:])
    return {"dev": sorted(dev), "heldout": sorted(heldout)}


def ids_for_split(name: str) -> list[int]:
    split = load_split()
    if name == "all":
        return sorted(split["dev"] + split["heldout"])
    if name not in ("dev", "heldout"):
        raise ValueError(f"unknown split {name!r} (expected dev, heldout or all)")
    return list(split[name])
