"""Installing, removing and verifying one ``hub`` module.

Execution, and nothing else. The recipe the hub resolved for this machine
names the module's artifacts, each ``{name, kind, digest, directory}``,
whose bytes come down a ``package {module, artifact, digest}`` stream. Each
artifact lands as its kind says, the same way for every module: an archive
unpacked under ``<directory>`` in the module's own directory and sealed, or
directly in the module's directory when it names none; an installer package
or a zstd file kept as the publisher's bytes under ``<directory>``; a program
kept where its runner says and made executable. An npm artifact is installed
by its module's runner. Whether the module is there is the recipe's
``verify`` command, and nothing here decides when to install.

Not pure: runs the verify command and writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ntpath
import os
import shutil
import subprocess
import tarfile
import zipfile

from neutrino_agent.constants import (
    AGENT_ARTIFACT_ARCHIVE_KINDS,
    AGENT_ARTIFACT_KEPT_SUFFIXES,
    AGENT_ARTIFACT_KIND_NPM,
    AGENT_DIGEST_SHA256_PREFIX,
)
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.unpacked_tree import (
    remove_tree,
    unpack_beside,
    unpack_into,
)
from neutrino_agent.streams.package import CODE_DIGEST_MISMATCH

VERIFY_TIMEOUT_S = 30


def verify_passes(command: str) -> bool:
    """Whether a recipe's verify command exits zero on this machine.

    Args:
        command: The shell command the hub resolved for this platform.

    Returns:
        True when it exits zero; False when it does not, cannot run, or is
        empty.
    """
    if not command:
        return False
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, timeout=VERIFY_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def params_of(recipe) -> dict:
    """A recipe's ``params``, empty when it names none.

    Args:
        recipe: ``{runner, method, params}`` as the state carries it.

    Returns:
        The parameters.
    """
    params = recipe.get("params") if isinstance(recipe, dict) else None
    return dict(params) if isinstance(params, dict) else {}


def artifacts_of(recipe) -> list:
    """The artifacts a recipe names, each a mapping.

    Args:
        recipe: ``{runner, method, params}``.

    Returns:
        ``params.artifacts``, anything that is not a mapping left out.
    """
    held = params_of(recipe).get("artifacts")
    if not isinstance(held, list):
        return []
    return [dict(artifact) for artifact in held if isinstance(artifact, dict)]


def received_artifacts(recipe) -> list:
    """The artifacts of a recipe whose bytes come down the package stream.

    Args:
        recipe: ``{runner, method, params}``.

    Returns:
        Every artifact but the npm packages, in the recipe's order.
    """
    return [
        artifact
        for artifact in artifacts_of(recipe)
        if artifact.get("kind") != AGENT_ARTIFACT_KIND_NPM
    ]


def npm_artifact(recipe) -> dict:
    """The npm artifact a recipe names.

    Args:
        recipe: ``{runner, method, params}``.

    Returns:
        The first artifact of kind ``npm``; empty when it names none.
    """
    for artifact in artifacts_of(recipe):
        if artifact.get("kind") == AGENT_ARTIFACT_KIND_NPM:
            return artifact
    return {}


def digest_hex(digest: str) -> str:
    """The SHA-256 a ``sha256:<hex>`` digest names. Pure.

    Args:
        digest: The artifact's digest.

    Returns:
        The hex, lower case; empty for any other form.
    """
    text = str(digest or "")
    if not text.startswith(AGENT_DIGEST_SHA256_PREFIX):
        return ""
    return text[len(AGENT_DIGEST_SHA256_PREFIX) :].lower()


def check_received(artifact: dict, received: dict) -> "dict | None":
    """Whether the bytes a package stream brought are the recipe's.

    Args:
        artifact: The recipe's artifact.
        received: The stream's ``{"path", "sha256"}``.

    Returns:
        None when the digest matches; ``package_digest_mismatch
        {artifact}`` otherwise.
    """
    expected = digest_hex(str(artifact.get("digest", "") or ""))
    if expected and str(received.get("sha256", "") or "").lower() == expected:
        return None
    return {
        "code": CODE_DIGEST_MISMATCH,
        "params": {"artifact": str(artifact.get("name", "") or "")},
    }


def is_plain_name(name: str) -> bool:
    """Whether a name is one plain path component. Pure.

    Args:
        name: The name.

    Returns:
        False for an empty name, ``.``, ``..`` and anything holding a
        separator.
    """
    return (
        bool(name)
        and name not in (".", "..")
        and not any(separator in name for separator in ("/", "\\"))
    )


def unpack_artifact(artifact: dict, path: str, *, module_dir: str, join) -> str:
    """Unpack an archive artifact under its directory in the module's, sealed.

    Args:
        artifact: The recipe's artifact, of kind ``tar_gz`` or ``zip``.
        path: The archive on disk.
        module_dir: The module's directory under the state root.
        join: How the system joins a path.

    Returns:
        Where its files are: its directory, or the module's directory for
        an artifact that names none.

    Raises:
        ModuleApplyError: ``install_failed {detail}`` for a directory that is
            not a plain name or an archive that cannot be unpacked.
        OSError: When the module's directory cannot be written.
    """
    kind = str(artifact.get("kind", "") or "")
    directory = str(artifact.get("directory", "") or "")
    if directory and not is_plain_name(directory):
        raise ModuleApplyError(
            "install_failed", {"detail": f"artifact directory {directory!r}"}
        )
    try:
        if not directory:
            unpack_beside(path, kind, module_dir)
            return module_dir
        target = join(module_dir, directory)
        unpack_into(path, kind, target)
        return target
    except (ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise ModuleApplyError(
            "install_failed", {"detail": str(error)[:200]}
        ) from error


def keep_artifact(artifact: dict, path: str, *, module_dir: str, join) -> str:
    """Keep an installer package or a zstd file as the publisher's bytes.

    The file moves to ``<directory>/<name><suffix>`` under the module's
    directory, replacing what the directory held.

    Args:
        artifact: The recipe's artifact, of kind ``msi``, ``pkg``,
            ``tar_zst`` or ``raw_zst``.
        path: The received file; it is moved, not copied.
        module_dir: The module's directory under the state root.
        join: How the system joins a path.

    Returns:
        The kept file's path.

    Raises:
        ModuleApplyError: ``install_failed {detail}`` for a name, directory
            or kind the module cannot keep.
        OSError: When the file cannot be kept.
    """
    name = str(artifact.get("name", "") or "")
    directory = str(artifact.get("directory", "") or "")
    kind = str(artifact.get("kind", "") or "")
    suffix = AGENT_ARTIFACT_KEPT_SUFFIXES.get(kind)
    if suffix is None or not is_plain_name(name) or not is_plain_name(directory):
        raise ModuleApplyError(
            "install_failed",
            {"detail": f"artifact {name!r} {directory!r} {kind!r}"},
        )
    target = join(module_dir, directory)
    remove_tree(target)
    os.makedirs(target, exist_ok=True)
    kept = join(target, name + suffix)
    shutil.move(path, kept)
    return kept


def kept_artifact_path(module_dir: str, name: str, kind: str, join) -> str:
    """Where a kept artifact's file is. Pure.

    Args:
        module_dir: The module's directory under the state root.
        name: The artifact's name, which is also its directory.
        kind: Its kind.

    Returns:
        ``<module_dir>/<name>/<name><suffix>``; empty for a kind that is
        not kept.
    """
    suffix = AGENT_ARTIFACT_KEPT_SUFFIXES.get(kind)
    if suffix is None:
        return ""
    return join(module_dir, name, name + suffix)


def place_binary(path: str, target: str) -> str:
    """Keep a program as the publisher's bytes at its place, executable.

    The bytes go through a file beside the target and replace it in one
    rename.

    Args:
        path: The received program.
        target: Where the module's page puts it.

    Returns:
        The target.

    Raises:
        OSError: When the file cannot be written.
    """
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = target + ".new"
    shutil.copyfile(path, temporary)
    os.chmod(temporary, 0o755)
    os.replace(temporary, target)
    return target


def remove_received(path: str) -> None:
    """Delete a received file once it was installed, kept or refused.

    Args:
        path: The file; one already moved away is left so.
    """
    with contextlib.suppress(OSError):
        os.unlink(path)


def unpacked_paths(recipe, *, module_dir: str, join) -> list:
    """Where a recipe's archives are unpacked. Pure.

    Args:
        recipe: ``{runner, method, params}``.
        module_dir: The module's directory under the state root.
        join: How the system joins a path.

    Returns:
        Each archive artifact's directory under the module's, or the
        module's directory for one that names none, once each, in the
        recipe's order; a directory that is not a plain name is left out.
    """
    paths = []
    for artifact in artifacts_of(recipe):
        if not is_archive_kind(str(artifact.get("kind", "") or "")):
            continue
        directory = str(artifact.get("directory", "") or "")
        if directory and not is_plain_name(directory):
            continue
        path = join(module_dir, directory) if directory else module_dir
        if path not in paths:
            paths.append(path)
    return paths


def joiner(os_name: str):
    """How a system joins a path.

    Args:
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        ``ntpath.join`` on Windows, ``os.path.join`` elsewhere.
    """
    return ntpath.join if os_name == "windows" else os.path.join


def is_archive_kind(kind: str) -> bool:
    """Whether a kind is one of the archives unpacked under the module."""
    return kind in AGENT_ARTIFACT_ARCHIVE_KINDS
