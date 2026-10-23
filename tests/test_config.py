from __future__ import annotations

from pathlib import Path

import pytest

from sloptriage.config import ConfigError, load_config, parse_config
from sloptriage.paths import bundled


def test_unknown_keys_and_types_name_file_and_path() -> None:
    with pytest.raises(ConfigError) as exc:
        parse_config(
            {"version": 1, "project": {"nmae": "x"}, "thresholds": {"hard_fail_min": "2"}},
            "cfg.yml",
        )
    errors = exc.value.errors
    assert "cfg.yml: project.nmae: unknown key" in errors
    assert "cfg.yml: thresholds.hard_fail_min: expected an integer" in errors


def test_value_checks() -> None:
    with pytest.raises(ConfigError) as exc:
        parse_config(
            {
                "languages": ["cobol"],
                "version_tags": ["release"],
                "thresholds": {"min_verified_share": 1.5},
            },
            "c.yml",
        )
    text = "\n".join(exc.value.errors)
    assert "languages[0]" in text and "min_verified_share" in text


def test_presets_and_defaults() -> None:
    cfg = parse_config({"version": 1, "project": {"name": "curl"}, "version_tags": ["curl"]})
    assert cfg.version_tags == ["curl-{major}_{minor}_{patch}"]
    assert cfg.thresholds.hard_fail_min == 2 and cfg.thresholds.min_verified_share == 0.7
    assert cfg.labels["refs_failed"] == "triage:refs-failed"


def test_bundled_examples_load() -> None:
    for name in ("curl", "parsekit", "kvconf"):
        cfg = load_config(bundled("examples", name, ".sloptriage.yml"))
        assert cfg.project == name


def test_invalid_yaml(tmp_path: Path) -> None:
    p = tmp_path / ".sloptriage.yml"
    p.write_text("version: [1\n")
    with pytest.raises(ConfigError):
        load_config(p)
