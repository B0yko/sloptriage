from __future__ import annotations

import hashlib
import json
from typing import Any

from sloptriage.bench import manifest
from sloptriage.paths import bundled


def _string_props(schema: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "string":
            out.append((path, schema))
        for key, sub in schema.get("properties", {}).items():
            out.extend(_string_props(sub, f"{path}.{key}"))
        if "items" in schema:
            out.extend(_string_props(schema["items"], f"{path}[]"))
    return out


def test_manifest_schema_has_no_free_text_fields() -> None:
    schema = json.loads(bundled("schemas", "bench-manifest-v1.json").read_text())
    props = _string_props(schema)
    assert props
    for path, prop in props:
        assert "enum" in prop or "pattern" in prop, f"{path} would allow free text"
    # every object closes the door on extra keys
    def closed(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for value in node.values():
                closed(value)
        elif isinstance(node, list):
            for value in node:
                closed(value)
    closed(schema)


def test_committed_manifest_validates_and_matches_checksums() -> None:
    reports = manifest.load_reports()
    assert len(reports) == 658
    lines = (manifest.manifest_dir() / "MANIFEST.sha256").read_text().split("\n")
    for line in filter(None, lines):
        digest, name = line.split("  ")
        assert hashlib.sha256((manifest.manifest_dir() / name).read_bytes()).hexdigest() == digest


def test_split_is_disjoint_and_reproducible() -> None:
    reports = manifest.load_reports()
    split = manifest.load_split()
    dev, held = set(split["dev"]), set(split["heldout"])
    assert not dev & held
    assert dev | held | set(split["excluded"]) == {r["id"] for r in reports}
    again = manifest.stratified_split(reports, seed=split["seed"], dev_share=split["dev_share"])
    assert again == {"dev": split["dev"], "heldout": split["heldout"]}


def test_labels_follow_substates() -> None:
    for rep in manifest.load_reports():
        assert rep["label"] == manifest.label_for(rep["substate"])
        assert rep["era"] == manifest.era_for(rep["disclosed_at"])
