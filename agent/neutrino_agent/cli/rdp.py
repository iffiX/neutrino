"""``nagent rdp``: sharing this machine's desktop, from a terminal.

The access password is read from the terminal and travels only in the one
request that sends it, never on argv. Which desktop is shared is the seat's:
with no account named, the one that invoked sudo, else the one account at
the screen.

The agent reports refusals as ``{"code", "params"}``; the wording lives in
``wording.py``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import sys

from neutrino_agent.cli import wording
from neutrino_agent.rdp.host import graphical_accounts

RDP_NOT_SHARED = "this machine's desktop is not shared"
RDP_ID_LABEL = "RustDesk ID"


def main_start(*, user: str = "") -> int:
    """Share this machine's desktop behind an access password.

    Args:
        user: Whose desktop; empty resolves the seat.

    Returns:
        Process exit status.
    """
    account = user or _seat_account()
    if not account:
        print(wording.word_code("rdp_no_seat", {}), file=sys.stderr)
        return 2
    password = wording.ask_secret("Access password: ")
    if not password:
        print(wording.word_code("rdp_password_missing", {}), file=sys.stderr)
        return 2
    reply = wording.act(
        "/api/rdp/start", {"user": account, "password": password}  # scan: allow
    )
    if reply is None:
        return 1
    print(share_line(reply))
    return 0


def main_stop() -> int:
    """Stop sharing this machine's desktop.

    Returns:
        Process exit status.
    """
    state = wording.read_state()
    if state is None:
        return 1
    if not (state.get("rdp") or {}).get("is_shared"):
        print(RDP_NOT_SHARED)
        return 0
    if wording.act("/api/rdp/stop", {}) is None:
        return 1
    print(RDP_NOT_SHARED)
    return 0


def share_line(state: dict) -> str:
    """This machine's own share, as one line.

    Args:
        state: The state payload.

    Returns:
        The line to print.
    """
    share = state.get("rdp") or {}
    standing = wording.word_state(str(share.get("state", "unknown")))
    if not share.get("is_shared"):
        return standing
    where = f"{state.get('hostname', '')}:{share.get('port', '')}"
    identifier = str(share.get("rustdesk_id", ""))
    tail = f"  {RDP_ID_LABEL} {identifier}" if identifier else ""
    return f"{where} — {standing}{tail}"


def _seat_account() -> str:
    """Whose desktop a share means when nobody named one.

    Returns:
        The account that invoked sudo, else the one account at the screen,
        empty when neither answers.
    """
    invoker = os.environ.get("SUDO_USER", "")
    if invoker:
        return invoker
    seated = graphical_accounts()
    return seated[0] if seated is not None and len(seated) == 1 else ""
