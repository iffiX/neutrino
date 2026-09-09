"""The Neutrino client: one person's window onto what a hub publishes."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _checkout_version() -> str:
    """The version from the checkout's pyproject, for an uninstalled tree.

    Returns:
        The declared version with a ``+dev`` suffix, or ``0.0.0+dev``.
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return "0.0.0+dev"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return f"{line.split(chr(34))[1]}+dev"
    return "0.0.0+dev"


try:  # Written into the tree when a package is built.
    from neutrino_client._version import CLIENT_VERSION
except ImportError:
    try:
        CLIENT_VERSION = version("neutrino-client")
    except PackageNotFoundError:
        CLIENT_VERSION = _checkout_version()
