"""The Neutrino device agent: metrics, heartbeats, and remote operations."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _checkout_version() -> str:
    """The version from the checkout's pyproject, for an uninstalled tree.

    An installed package answers from its metadata. Running from a checkout
    there is none, and the version still has to match the one the packages
    will carry — the hub compares it against every agent's.

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
    from neutrino_agent._version import AGENT_VERSION
except ImportError:
    try:
        AGENT_VERSION = version("neutrino-agent")
    except PackageNotFoundError:
        AGENT_VERSION = _checkout_version()
