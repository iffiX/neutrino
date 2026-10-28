"""SSH for other programs: the forward of every ``ssh`` entry, and the keys.

Pinned here: each ``ssh`` entry of a hub with a number is forwarded at it,
an entry with no number and an entry of another kind are not, and a
forward that cannot listen answers its code, ``port_taken`` among them. An
account's key is read once for a list that did not change, and read again
and written over when the entry's ``account_key_fingerprint`` changes.
"""

import os

from neutrino_client.exceptions import LocalPortTakenError
from neutrino_client.services.ssh import SshConfigWriter, keep_forwards


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


def ssh_entry(fingerprint: str) -> dict:
    return {
        "hub_id": "h1",
        "id": "ssh_server_d1_lab",
        "type": "ssh",
        "app_id": "ssh_server_d1",
        "payload": {
            "account": "lab",
            "host_key_fingerprint": "SHA256:host",
            "account_key_fingerprint": fingerprint,
        },
    }


def run_inline(target) -> None:
    target()


def test_a_rotated_account_key_is_read_again_and_written_over(tmp_path):
    asked = []

    def open_service(hub_id, entry_id):
        asked.append(entry_id)
        return {"private_key": f"key-{len(asked)}", "host_key": "ssh-ed25519 AAAA"}

    writer = SshConfigWriter(
        home=str(tmp_path),
        open_service=open_service,
        log=str,
        start_thread=run_inline,
    )
    apps = [{"hub_id": "h1", "id": "ssh_server_d1", "local_name": "ssh.lab.localhost"}]

    writer.refresh(entries=[ssh_entry("SHA256:one")], apps=apps, hub_names={})
    writer.refresh(entries=[ssh_entry("SHA256:one")], apps=apps, hub_names={})
    keys = os.listdir(writer.keys_dir)
    first = [name for name in keys if name != "known_hosts"]
    writer.refresh(entries=[ssh_entry("SHA256:two")], apps=apps, hub_names={})

    assert asked == ["ssh_server_d1_lab", "ssh_server_d1_lab"]
    with open(os.path.join(writer.keys_dir, first[0]), encoding="utf-8") as stream:
        assert stream.read() == "key-2\n"
