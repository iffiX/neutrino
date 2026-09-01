"""What the box itself resolves names with.

A box in router mode resolves where its own devices do: at the dnsmasq on its
served network, which forwards through the proxy or to the direct resolver as
the routing configuration says. Without this the gateway comes up with an
address, a route, and nothing to ask a name of — it cannot fetch its own
geodata, install a module from a vendor, or run apt.

It has to be written rather than inherited. The lease client's `resolv.conf`
hook is off, because a hook that writes the upstream network's servers into
this file is a second opinion about the one thing the whole box exists to
route; and on a machine whose resolver was `systemd-resolved`, that daemon is
stopped in router mode and the stub it answered on is gone.

Only in router mode. A machine the hub does not address keeps whatever it was
resolving with, like everything else about it.

Not pure: writes a file outside the hub's own roots.
"""

import os
from pathlib import Path

from neutrino_hub.utils.subprocess_run import run

# --- config ---
RESOLVER_PATH = Path("/etc/resolv.conf")
# Where systemd-resolved answers, and what a distribution symlinks the file
# above at when it is the resolver. Pointing back at it is how the machine's
# own arrangement is restored without anything having been backed up.
RESOLVER_RESOLVED_STUB = Path("/run/systemd/resolve/stub-resolv.conf")
RESOLVER_RESOLVED_UNIT = "systemd-resolved.service"

RESOLVER_HEADER = "# Written by neutrino. Change config/ rather than this file.\n"


def point_at(address: str) -> bool:
    """Have the box resolve at one address.

    Args:
        address: Where its dnsmasq listens, which is its own address on the
            network it serves.

    Returns:
        True when the file had to be written.
    """
    wanted = f"{RESOLVER_HEADER}nameserver {address}\n"
    if _current() == wanted:
        return False
    _replace(wanted)
    return True


def hand_back() -> bool:
    """Give name resolution back to whatever the machine had.

    A symlink to `systemd-resolved`'s stub when that is installed, which is
    what every distribution using it ships. Otherwise the file is left as it
    is: something else on this machine writes it, and guessing at servers
    would be worse than leaving what is there.

    Returns:
        True when the file was changed.
    """
    if not _is_written_here():
        return False
    is_resolved = run(
        ["systemctl", "is-enabled", "--quiet", RESOLVER_RESOLVED_UNIT],
        is_checked=False,
    ).is_success
    if not is_resolved:
        return False
    RESOLVER_PATH.unlink(missing_ok=True)
    RESOLVER_PATH.symlink_to(RESOLVER_RESOLVED_STUB)
    return True


def _is_written_here() -> bool:
    """Whether the file is one this module wrote.

    Returns:
        True when it carries our header, so nothing somebody else arranged is
        ever replaced by handing back.
    """
    return _current().startswith(RESOLVER_HEADER)


def _current() -> str:
    """What the file says now, or an empty string when it cannot be read."""
    try:
        return RESOLVER_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _replace(text: str) -> None:
    """Write the file, whatever is in its place.

    A symlink is removed rather than written through: on a machine using
    `systemd-resolved` this path is a link into `/run`, and writing through it
    would put our nameserver in a file that daemon rewrites — or, once it is
    stopped, in a file under a directory that no longer exists.

    Args:
        text: The whole file.
    """
    temporary = RESOLVER_PATH.with_suffix(".neutrino")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, 0o644)
    RESOLVER_PATH.unlink(missing_ok=True)
    os.replace(temporary, RESOLVER_PATH)
