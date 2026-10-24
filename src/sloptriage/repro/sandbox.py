"""The real sandbox: builds the images for a commit and runs PoC plans in hardened containers."""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
from collections.abc import Callable
from typing import Protocol

from sloptriage.index.gitobj import GitRepo
from sloptriage.repro.errors import ReproError
from sloptriage.repro.recipes import (
    DOCKERFILE,
    Recipe,
    base_dockerfile,
    declared_requirements,
    project_dockerfile,
    recipe_hash,
)
from sloptriage.repro.runners import RunPlan, artefact_tar, sandbox_env
from sloptriage.repro.runtime import (
    Limits,
    RunResult,
    Runtime,
    build_image,
    image_exists,
    run_sandboxed,
)

MAX_SOURCE_BYTES = 512 * 1024 * 1024


class Sandbox(Protocol):
    def ensure_image(self, commit: str, label: str) -> tuple[str | None, str | None]:
        """(image tag, None) when ready, or (None, why the build failed)."""
        ...

    def run(self, image: str, plan: RunPlan, limits: Limits) -> RunResult: ...


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-.") or "project"


def _append(context: bytes, name: str, data: bytes) -> bytes:
    buf = io.BytesIO(context)
    with tarfile.open(fileobj=buf, mode="a") as tf:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = 0o644
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def source_archive(repo: GitRepo, commit: str) -> bytes:
    """The tree of ``commit`` as git archive writes it (what a release tarball contains)."""
    proc = subprocess.run(
        ["git", "-C", str(repo.path), "archive", "--format=tar", commit],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ReproError(
            f"cannot export {commit[:12]}: {proc.stderr.decode(errors='replace')[:200]}"
        )
    if len(proc.stdout) > MAX_SOURCE_BYTES:
        raise ReproError("the source tree is too large to build in the sandbox")
    return proc.stdout


def project_context(repo: GitRepo, commit: str, dockerfile: str) -> bytes:
    """The build context of the project stage: the commit's tree and our Dockerfile.

    The empty ``Dockerfile.sloptriage.dockerignore`` takes precedence over a ``.dockerignore`` that
    the project ships, which would otherwise drop files from the build.
    """
    context = _append(source_archive(repo, commit), DOCKERFILE, dockerfile.encode())
    return _append(context, f"{DOCKERFILE}.dockerignore", b"")


class ContainerSandbox:
    def __init__(
        self,
        runtime: Runtime,
        repo: GitRepo,
        recipe: Recipe,
        project: str,
        limits: Limits,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.runtime, self.repo, self.recipe = runtime, repo, recipe
        self.project, self.limits = _slug(project), limits
        self.progress = progress or (lambda _msg: None)

    def _manifests(self, commit: str) -> list[str]:
        if not self.recipe.python:
            return []
        wanted = {}
        for entry in self.repo.ls_tree(commit):
            if "/" not in entry.path and entry.size < 1_000_000:
                wanted[entry.path] = self.repo.cat_blob(entry.blob)
        return declared_requirements(wanted, self.recipe)

    def ensure_image(self, commit: str, label: str) -> tuple[str | None, str | None]:
        rhash = recipe_hash(self.recipe)
        tag = f"sloptriage/{self.project}:{commit[:12]}-{rhash}"
        if image_exists(self.runtime, tag):
            return tag, None
        requirements = self._manifests(commit)
        base_key = rhash
        if self.recipe.python:
            import hashlib

            base_key += "-" + hashlib.sha256("\n".join(requirements).encode()).hexdigest()[:8]
        base_tag = f"sloptriage-base/{self.project}:{base_key}"
        if not image_exists(self.runtime, base_tag):
            self.progress(f"building the toolchain image {base_tag} (needs network, once)")
            context = artefact_context(
                {DOCKERFILE: base_dockerfile(self.recipe, requirements).encode()}
                | (
                    {"requirements.txt": ("\n".join(requirements) + "\n").encode()}
                    if self.recipe.python
                    else {}
                )
            )
            ok, log = build_image(
                self.runtime,
                base_tag,
                DOCKERFILE,
                context,
                network=True,
                timeout=self.limits.build_timeout,
            )
            if not ok:
                return None, f"the toolchain image could not be built: {log}"
        self.progress(f"building {self.project} at {label} with sanitizers (no network)")
        context = project_context(
            self.repo, commit, project_dockerfile(self.recipe, base_tag, self.project)
        )
        ok, log = build_image(
            self.runtime, tag, DOCKERFILE, context, network=False, timeout=self.limits.build_timeout
        )
        if not ok:
            return None, log
        return tag, None

    def run(self, image: str, plan: RunPlan, limits: Limits) -> RunResult:
        return run_sandboxed(
            self.runtime, image, plan.script, artefact_tar(plan.files), limits, sandbox_env()
        )


def artefact_context(files: dict[str, bytes]) -> bytes:
    """A build context holding only the generated files (Dockerfile and requirements)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()
