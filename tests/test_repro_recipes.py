"""Build recipes: presets, the generated Dockerfiles, the cache key and ``repro`` config errors."""

from __future__ import annotations

import pytest

from sloptriage.config import ConfigError, parse_config
from sloptriage.repro.recipes import (
    PRESET_NAMES,
    Recipe,
    base_dockerfile,
    declared_requirements,
    project_dockerfile,
    recipe_from_config,
    recipe_hash,
)


def cfg(repro: dict[str, object]) -> object:
    return parse_config(
        {"version": 1, "project": {"name": "parsekit"}, "repro": repro}, "c.yml"
    ).repro


def recipe(preset: str, **extra: object) -> Recipe:
    conf = cfg({"build": {"preset": preset, **extra}})
    return recipe_from_config(conf, "parsekit")  # type: ignore[arg-type]


def test_the_four_presets_exist() -> None:
    assert set(PRESET_NAMES) == {"autotools-asan", "cmake-asan", "meson-asan", "python-pip"}


@pytest.mark.parametrize("preset", sorted(["autotools-asan", "cmake-asan", "meson-asan"]))
def test_native_presets_compile_with_address_and_undefined_sanitizers(preset: str) -> None:
    r = recipe(preset)
    flags = " ".join(r.sanitizer_flags)
    assert "-fsanitize=address" in flags and "undefined" in flags
    assert "-g" in r.sanitizer_flags
    text = project_dockerfile(r, "sloptriage/base:x", "parsekit")
    assert "-fsanitize=address" in text
    assert r.prefix == "/opt/project"


def test_the_image_stage_takes_only_recipe_inputs_for_native_projects() -> None:
    r = recipe("cmake-asan", packages=["libssl-dev"])
    text = base_dockerfile(r)
    assert text.startswith("FROM ")
    assert "libssl-dev" in text and "cmake" in text
    assert "COPY" not in text  # nothing from the project or the report enters this stage
    assert "ADD " not in text


def test_the_project_stage_copies_the_source_and_builds_without_network_steps() -> None:
    r = recipe("autotools-asan")
    text = project_dockerfile(r, "sloptriage/base:x", "parsekit")
    assert text.splitlines()[0] == "FROM sloptriage/base:x"
    assert "COPY . /build/src" in text
    assert "./configure" in text and "make" in text
    for forbidden in ("apt-get", "pip download", "curl ", "wget "):
        assert forbidden not in text
    assert "USER 10001" in text


def test_user_overrides_replace_preset_commands() -> None:
    r = recipe("cmake-asan", configure=["cmake -S . -B out"], build=["cmake --build out"])
    text = project_dockerfile(r, "sloptriage/base:x", "parsekit")
    assert "cmake -S . -B out" in text and "cmake --build out" in text
    assert "-B build" not in text


def test_python_recipe_resolves_dependencies_in_the_image_stage_only() -> None:
    r = recipe("python-pip")
    files = {
        "requirements.txt": b"six==1.16.0\n",
        "pyproject.toml": b'[build-system]\nrequires = ["setuptools>=61"]\n[project]\nname="k"\n'
        b'version="1"\ndependencies = ["attrs>=23"]\n',
    }
    base = base_dockerfile(r, manifests=declared_requirements(files, r))
    assert "pip wheel" in base or "pip download" in base
    assert "/deps/requirements.txt" in base
    project = project_dockerfile(r, "sloptriage/base:x", "kvconf")
    assert "--no-index" in project
    assert "pip download" not in project and "pip wheel" not in project


def test_declared_requirements_come_from_manifests_not_from_code() -> None:
    r = recipe("python-pip")
    files = {
        "requirements.txt": b"six==1.16.0\n# comment\n-r other.txt\n--index-url http://evil.example\n",
        "pyproject.toml": b'[build-system]\nrequires = ["setuptools>=61", "wheel"]\n'
        b'[project]\nname="k"\nversion="1"\ndependencies = ["attrs>=23", "idna"]\n',
        "setup.py": b"import os; os.system('echo pwned')\n",
    }
    reqs = declared_requirements(files, r)
    assert reqs == ["attrs>=23", "idna", "setuptools>=61", "six==1.16.0", "wheel"]


def test_requirements_with_urls_or_options_are_dropped() -> None:
    r = recipe("python-pip")
    files = {
        "requirements.txt": b"six==1.16.0\n--extra-index-url http://x\n"
        b"git+https://example.com/x.git\nhttps://example.com/y.whl\n-e .\n./local\n"
    }
    assert declared_requirements(files, r) == ["six==1.16.0"]


def test_recipe_hash_is_stable_and_changes_with_the_recipe() -> None:
    a, b = recipe("cmake-asan"), recipe("cmake-asan")
    assert recipe_hash(a) == recipe_hash(b)
    assert recipe_hash(recipe("cmake-asan", packages=["zlib1g-dev"])) != recipe_hash(a)
    assert recipe_hash(recipe("meson-asan")) != recipe_hash(a)
    assert len(recipe_hash(a)) == 12


def test_the_hash_changes_when_the_dockerfile_templates_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = recipe_hash(recipe("cmake-asan"))
    monkeypatch.setattr("sloptriage.repro.recipes.TEMPLATE_VERSION", 99)
    assert recipe_hash(recipe("cmake-asan")) != before


# -- configuration errors ---------------------------------------------------------------------
def errors_of(repro: object) -> list[str]:
    with pytest.raises(ConfigError) as exc:
        parse_config({"version": 1, "repro": repro}, "x.yml")
    return exc.value.errors


def test_unknown_preset_names_the_file_and_key_path() -> None:
    errs = errors_of({"build": {"preset": "bazel-asan"}})
    assert any(e.startswith("x.yml: repro.build.preset:") and "cmake-asan" in e for e in errs)


def test_unknown_keys_are_reported_with_their_path() -> None:
    errs = errors_of({"limits": {"bogus": 1}, "x": 1, "build": {"nope": []}})
    joined = "\n".join(errs)
    assert "x.yml: repro.x: unknown key" in joined
    assert "x.yml: repro.limits.bogus: unknown key" in joined
    assert "x.yml: repro.build.nope: unknown key" in joined


def test_a_trailing_newline_is_not_a_valid_value() -> None:
    errs = errors_of({"build": {"packages": ["libssl-dev\n"], "base_image": "debian:12\n"}})
    joined = "\n".join(errs)
    assert "repro.build.packages[0]" in joined and "repro.build.base_image" in joined


def test_bad_values_are_reported_with_their_path() -> None:
    errs = errors_of(
        {
            "limits": {"memory": "lots", "cpus": 0, "runs": 50},
            "runners": ["c", "fortran"],
            "harness": "parsekit header",
            "build": {"configure": ["a\nRUN evil"], "packages": ["ok", "no;pe"]},
        }
    )
    joined = "\n".join(errs)
    assert "x.yml: repro.limits.memory:" in joined
    assert "x.yml: repro.limits.cpus:" in joined
    assert "x.yml: repro.limits.runs:" in joined
    assert "x.yml: repro.runners[1]:" in joined
    assert "x.yml: repro.harness:" in joined
    assert "x.yml: repro.build.configure[0]:" in joined
    assert "x.yml: repro.build.packages[1]:" in joined


def test_defaults_are_off_and_conservative() -> None:
    conf = parse_config({"version": 1, "project": {"name": "p"}}, "d.yml").repro
    assert conf.enabled is False
    assert conf.limits.runs == 3 and conf.limits.candidates == 5
    assert conf.limits.timeout <= 60 and conf.limits.pids <= 256
    assert set(conf.runners) == {"c", "cpp", "shell", "python", "input"}
