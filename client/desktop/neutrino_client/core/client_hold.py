"""Which account's client holds this machine, kept by the EasyTier daemon.

A machine runs one person's client at a time. The resident asks ``hold``
once its own control socket is bound and again on a timer; the daemon's
socket or pipe says who asks, the account and the calling process. While a
running resident of one account holds the machine, a ``hold`` from another
account is refused ``client_held``; a later resident of the same account is
served in its place. The daemon keeps a watch on the holding process and
frees the machine once it has ended. Anyone may ask ``holder``.

    {"verb": "hold"}    -> {"holder", "is_holder"} or the refusal
    {"verb": "holder"}  -> {"holder", "is_holder"}

``holder`` is the holding account, empty for none; ``is_holder`` is whether
the asking account is it. The refusal is ``{"code": "client_held",
"params": {"account"}}``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import threading

VERB_HOLD = "hold"
VERB_HOLDER = "holder"
CLIENT_HELD_CODE = "client_held"


def client_held(account: str) -> dict:
    """The refusal of a hold while another account's client runs.

    Args:
        account: The holding account.

    Returns:
        ``{"code": "client_held", "params": {"account"}}``.
    """
    return {"code": CLIENT_HELD_CODE, "params": {"account": account}}


def _account_of(peer) -> str:
    """The account a peer names, empty for none."""
    return str((peer or {}).get("account", "") or "")


def _is_same_account(one: str, other: str) -> bool:
    """Whether two account names are one account; Windows names ignore case."""
    return bool(one) and one.lower() == other.lower()


class ClientHold:
    """The one account whose client runs on this machine, and its process."""

    def __init__(self, *, watch_process=None, log=print):
        """
        Args:
            watch_process: ``watch_process(pid)`` returns a watch with
                ``is_running()`` and ``close()`` on the holding process;
                None watches nothing, and a holder then holds until a
                resident of its own account takes its place.
            log: Callable used for progress messages.
        """
        self._watch_process = watch_process
        self._log = log
        self._lock = threading.Lock()
        self._holder: "dict | None" = None
        self._watch = None

    def handle(self, verb: str, peer) -> dict:
        """Answer one ``hold`` or ``holder``.

        Args:
            verb: ``hold`` or ``holder``.
            peer: Who asks, as the socket says, ``{"account", "pid"}``;
                None where it could not tell, which never holds.

        Returns:
            ``{"holder", "is_holder"}``, or the ``client_held`` refusal.
        """
        account = _account_of(peer)
        with self._lock:
            self._free_when_ended()
            holder = _account_of(self._holder)
            if verb == VERB_HOLD and account:
                if holder and not _is_same_account(holder, account):
                    self._log(
                        f"hold from {account} refused: the client of {holder} "
                        "holds this machine"
                    )
                    return client_held(holder)
                self._hold_for(peer)
                holder = account
            return {
                "holder": holder,
                "is_holder": _is_same_account(holder, account),
            }

    def close(self) -> None:
        """Forget the holder and close its watch. Idempotent."""
        with self._lock:
            self._release()

    def _free_when_ended(self) -> None:
        """Forget a holder whose process has ended; under the lock."""
        if self._holder is None or self._is_holder_running():
            return
        self._log(
            f"the client of {_account_of(self._holder)} that held this machine "
            "has ended"
        )
        self._release()

    def _is_holder_running(self) -> bool:
        """Whether the holding process still runs; under the lock."""
        if self._watch is None:
            return True
        try:
            return bool(self._watch.is_running())
        except OSError:
            return False

    def _hold_for(self, peer: dict) -> None:
        """Make one resident the holder and watch its process; under the lock."""
        pid = peer.get("pid") or 0
        if self._holder is not None and self._holder.get("pid") == pid:
            return
        self._release()
        self._holder = {"account": _account_of(peer), "pid": pid}
        self._log(f"the client of {self._holder['account']} holds this machine")
        if self._watch_process is None or not pid:
            return
        try:
            self._watch = self._watch_process(pid)
        except (OSError, NotImplementedError) as error:
            self._log(f"the holding client cannot be watched: {error}")

    def _release(self) -> None:
        """Forget the holder and close its watch; under the lock."""
        watch = self._watch
        self._holder = None
        self._watch = None
        if watch is not None:
            try:
                watch.close()
            except OSError:
                pass
