"""SSH for other programs: the forward of every ``ssh`` entry.

Pinned here: each ``ssh`` entry of a hub with a number is forwarded at it,
an entry with no number and an entry of another kind are not, and a
forward that cannot listen answers its code, ``port_taken`` among them.
"""

from neutrino_client.exceptions import LocalPortTakenError
from neutrino_client.services.ssh import keep_forwards


class Forwards:
    """A registry that records every forward asked of it."""

    def __init__(self, taken=()):
        self.asked = []
        self._taken = set(taken)

    def ensure(self, *, hub_id, entry_id, kind, own_port=0, protocol="tcp"):
        if own_port in self._taken:
            raise LocalPortTakenError(own_port)
        self.asked.append((hub_id, entry_id, kind, own_port))
        return own_port


def shell(entry_id: str, port) -> dict:
    return {
        "id": entry_id,
        "type": "ssh",
        "app_id": "ssh_server_d1",
        "local_port": port,
    }


def test_each_ssh_entry_with_a_number_is_forwarded_at_it():
    forwards = Forwards()
    page = {"id": "gitea_d1_web", "type": "web", "local_port": 25000}

    outcomes = keep_forwards(
        forwards,
        hub_id="h1",
        entries=[
            shell("ssh_server_d1_iffi", 26001),
            page,
            shell("ssh_server_d1_lab", None),
        ],
    )

    assert forwards.asked == [("h1", "ssh_server_d1_iffi", "ssh", 26001)]
    assert outcomes == {"ssh_server_d1_iffi": {}}


def test_a_taken_number_answers_port_taken():
    forwards = Forwards(taken={26001})

    outcomes = keep_forwards(
        forwards, hub_id="h1", entries=[shell("ssh_server_d1_iffi", 26001)]
    )

    assert forwards.asked == []
    assert outcomes == {
        "ssh_server_d1_iffi": {"code": "port_taken", "params": {"port": 26001}}
    }
