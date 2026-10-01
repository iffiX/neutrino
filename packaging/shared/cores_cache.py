"""The cache of the cores the phone apps carry, built once per pinned commit.

Each core lands in
``~/.cache/neutrino/cores/<core>-<commit>-<abi>-<recipe>/``: the core's name,
the upstream commit its source archive names, the Android ABI the files are
for, and eight hex digits of the SHA-256 over the script that builds it and
its patch. The same names make the key the workflows give actions/cache, so
a machine and a runner hold the same thing under the same name, and a new
pin or a changed recipe is a new directory.

Not pure: reads and writes the cache directory.
"""

import hashlib
import shutil
from pathlib import Path

CORES_CACHE_DIR = Path.home() / ".cache" / "neutrino" / "cores"


# How many hex digits of the recipe's digest a cache name carries.
RECIPE_DIGITS = 8


def recipe(*paths: Path) -> str:
    """The short digest of what builds a core: its script and its patch.

    Args:
        *paths: The files, in a fixed order.

    Returns:
        :data:`RECIPE_DIGITS` hex digits of the SHA-256 over their bytes.

    Raises:
        FileNotFoundError: When one of them is missing.
    """
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:RECIPE_DIGITS]


def cache_key(core: str, commit: str, abi: str, recipe_digest: str) -> str:
    """The name one core's files are cached under.

    Args:
        core: The core, ``netbird``, ``easytier`` or ``rustdesk``.
        commit: The upstream commit the pinned source names.
        abi: The Android ABI the files are for.
        recipe_digest: What :func:`recipe` returned for the core's script.

    Returns:
        ``<core>-<commit>-<abi>-<recipe>``.
    """
    return f"{core}-{commit}-{abi}-{recipe_digest}"


def cache_dir(core: str, commit: str, abi: str, recipe_digest: str) -> Path:
    """The directory one core's files are cached in.

    Args:
        core: The core, ``netbird``, ``easytier`` or ``rustdesk``.
        commit: The upstream commit the pinned source names.
        abi: The Android ABI the files are for.
        recipe_digest: What :func:`recipe` returned for the core's script.

    Returns:
        The directory, which exists only once the core is cached.
    """
    return CORES_CACHE_DIR / cache_key(core, commit, abi, recipe_digest)


def is_cached(directory: Path) -> bool:
    """Whether a cache directory holds a finished build.

    Args:
        directory: What :func:`cache_dir` returned.

    Returns:
        True when it exists and holds at least one file.
    """
    return directory.is_dir() and any(path.is_file() for path in directory.iterdir())


def store(built: Path, directory: Path) -> None:
    """Put a finished build into the cache, replacing what was there.

    Args:
        built: A directory holding the files, which is moved.
        directory: What :func:`cache_dir` returned.
    """
    if directory.exists():
        shutil.rmtree(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(built), str(directory))


def install(directory: Path, destination: Path) -> None:
    """Copy every file of a cached core into the app's tree.

    Args:
        directory: What :func:`cache_dir` returned.
        destination: The directory in the app the files go to.

    Raises:
        FileNotFoundError: When the core is not cached.
    """
    if not is_cached(directory):
        raise FileNotFoundError(f"{directory} holds no build")
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(directory.iterdir()):
        if path.is_file():
            shutil.copy2(path, destination / path.name)
            print(f"  {path.name} -> {destination}")
