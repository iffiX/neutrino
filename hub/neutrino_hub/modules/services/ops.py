"""Asking an SMB server what it exports.

``smbclient -L <host> -N`` is samba's own enumeration, asked anonymously. A
secured server turns an anonymous session away — a denied login, or a login
that succeeds against an empty table — and that answer is *listing refused*,
never proof a share is absent: only a listing that actually shows shares can
say one is missing. The tool ships with samba, so a hub without that module
installed may not have it, and that too is its own answer.

Not pure: this runs the client. Parsing what it printed is
:func:`parse_share_names`, which is.
"""

from dataclasses import dataclass, field
from shutil import which

from neutrino_hub.modules.services.constants import (
    SERVICES_PROBE_CONNECT_FAILED,
    SERVICES_PROBE_LIST_REFUSED,
    SERVICES_PROBE_TIMEOUT_S,
    SERVICES_PROBE_TOOL_MISSING,
    SERVICES_SHARE_ADMINISTRATIVE_SUFFIX,
    SERVICES_SHARE_TABLE_HEADER,
    SERVICES_SHARE_TABLE_RULE,
    SERVICES_SMB_REFUSAL_MARKERS,
    SERVICES_SMBCLIENT_BINARY,
)
from neutrino_hub.utils.subprocess_run import CommandError, run


@dataclass
class SambaShareListing:
    """What one server answered when it was asked for its exports.

    Attributes:
        names: The share names it exports, administrative ones dropped.
        error_code: Why nothing could be listed, None when it answered.
    """

    names: list[str] = field(default_factory=list)
    error_code: str | None = None


def list_shares(
    host: str, *, timeout_s: float = SERVICES_PROBE_TIMEOUT_S
) -> SambaShareListing:
    """Ask one server for its exports.

    Args:
        host: The server to ask.
        timeout_s: How long to wait before calling it unreachable.

    Returns:
        Its share names, or the reason there are none to report:
        ``list_refused`` for a server that turns the anonymous session away
        or shows it an empty table, ``connect_failed`` for one that could
        not be reached, ``tool_missing`` with no client to ask.
    """
    if which(SERVICES_SMBCLIENT_BINARY) is None:
        return SambaShareListing(error_code=SERVICES_PROBE_TOOL_MISSING)
    try:
        result = run(
            [SERVICES_SMBCLIENT_BINARY, "-L", host, "-N"],
            timeout_s=timeout_s,
            is_checked=False,
        )
    except CommandError:
        return SambaShareListing(error_code=SERVICES_PROBE_CONNECT_FAILED)
    if not result.is_success:
        output = result.stdout + result.stderr
        if any(marker in output for marker in SERVICES_SMB_REFUSAL_MARKERS):
            return SambaShareListing(error_code=SERVICES_PROBE_LIST_REFUSED)
        return SambaShareListing(error_code=SERVICES_PROBE_CONNECT_FAILED)
    names = parse_share_names(result.stdout)
    if not names:
        # An anonymous login can succeed against a server that hides every
        # export from it; an empty table is never proof a share is absent.
        return SambaShareListing(error_code=SERVICES_PROBE_LIST_REFUSED)
    return SambaShareListing(names=names)


def parse_share_names(output: str) -> list[str]:
    """Read the share names out of an ``smbclient -L`` listing.

    The listing opens with whatever the login printed, holds an indented
    table of shares, and may go on to tables of servers and workgroups. Only
    the first table is shares, so reading stops at the blank line that closes
    it or at the first line the table does not indent.

    Args:
        output: What the client printed on standard output.

    Returns:
        The share names in the order listed. IPC$, print$ and every other
        administrative export are dropped: none of them is a share anybody
        declares.
    """
    names = []
    is_in_table = False
    for line in output.splitlines():
        stripped = line.strip()
        if not is_in_table:
            is_in_table = stripped.startswith(SERVICES_SHARE_TABLE_HEADER)
            continue
        if not stripped or not line.startswith((" ", "\t")):
            break
        if stripped.startswith(SERVICES_SHARE_TABLE_RULE):
            continue
        name = stripped.split()[0]
        if not name.endswith(SERVICES_SHARE_ADMINISTRATIVE_SUFFIX):
            names.append(name)
    return names
