"""Which account's client holds the machine, as the EasyTier daemon keeps it.

Pinned here: the first resident to ask holds; another account is refused
``client_held`` with the holder's account while the holder runs; the same
account, in either case of its name, takes the hold in the first one's
place; a holder whose process has ended frees the machine at the next ask;
``holder`` tells anyone who holds and whether it is them; a peer the socket
could not read never holds.
"""

from neutrino_client.core.client_hold import ClientHold
from neutrino_client.core.easytier_daemon import EasytierDaemon
from tests.conftest import discard

LAB = {"account": "lab", "pid": 4100}
OTHER = {"account": "second", "pid": 5200}


class Watches:
    """Stands in for the platform's process watch."""

    def __init__(self):
        self.ended = set()
        self.closed = []

    def __call__(self, pid):
        watches = self

        class Watch:
            def is_running(self):
                return pid not in watches.ended

            def close(self):
                watches.closed.append(pid)

        return Watch()


def make_hold():
    watches = Watches()
    return ClientHold(watch_process=watches, log=discard), watches


def test_the_first_resident_holds_and_is_told_so():
    hold, _watches = make_hold()

    assert hold.handle("hold", LAB) == {"holder": "lab", "is_holder": True}
    assert hold.handle("holder", OTHER) == {"holder": "lab", "is_holder": False}


def test_another_account_is_refused_with_the_holders_account():
    hold, _watches = make_hold()
    hold.handle("hold", LAB)

    assert hold.handle("hold", OTHER) == {
        "code": "client_held",
        "params": {"account": "lab"},
    }
    assert hold.handle("holder", LAB) == {"holder": "lab", "is_holder": True}


def test_the_same_account_takes_the_first_ones_place():
    hold, watches = make_hold()
    hold.handle("hold", LAB)

    answer = hold.handle("hold", {"account": "LAB", "pid": 4200})

    assert answer == {"holder": "LAB", "is_holder": True}
    assert watches.closed == [4100]


def test_a_holder_that_ended_frees_the_machine():
    hold, watches = make_hold()
    hold.handle("hold", LAB)
    watches.ended.add(4100)

    assert hold.handle("holder", OTHER) == {"holder": "", "is_holder": False}
    assert hold.handle("hold", OTHER) == {"holder": "second", "is_holder": True}


def test_a_peer_the_socket_could_not_read_never_holds():
    hold, _watches = make_hold()

    assert hold.handle("hold", None) == {"holder": "", "is_holder": False}
    hold.handle("hold", LAB)
    assert hold.handle("hold", None) == {"holder": "lab", "is_holder": False}


def test_a_holder_that_cannot_be_watched_still_holds():
    def refuse(pid):
        raise OSError("no such process")

    hold = ClientHold(watch_process=refuse, log=discard)

    assert hold.handle("hold", LAB)["is_holder"] is True
    assert hold.handle("hold", OTHER)["code"] == "client_held"


def test_the_easytier_daemon_answers_the_hold_with_the_peer(tmp_path):
    daemon = EasytierDaemon(
        state_dir=str(tmp_path / "state"),
        core_path="",
        log=discard,
        watch_process=Watches(),
    )

    assert daemon.handle({"verb": "hold"}, peer=LAB) == {
        "holder": "lab",
        "is_holder": True,
    }
    assert daemon.handle({"verb": "hold"}, peer=OTHER)["code"] == "client_held"
    assert daemon.handle({"verb": "holder"}) == {"holder": "lab", "is_holder": False}
