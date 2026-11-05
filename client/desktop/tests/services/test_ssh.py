"""SSH for other programs: the forward of every ``ssh`` entry, and the keys.

Pinned here: each ``ssh`` entry of a hub with a number is forwarded at it,
an entry with no number and an entry of another kind are not, and a
forward that cannot listen answers its code, ``port_taken`` among them. An
account's key is read once for a list that did not change, and read again
and written over when the entry's ``account_key_fingerprint`` changes. Many
rewrites at once all finish and leave the newest list and its keys alone, a
rewrite held by a slow hub never replaces a newer list, a clear during a
rewrite leaves no file behind, a stop waits for a rewrite running and none
runs after it, and many Include edits at once all finish and keep the
person's lines. Each account's instance key is kept under that account's
alias alone, which a ``Match`` block after the machine's ``Host`` block
names, and the system's ``ssh -G`` resolves each account and the default to
its own alias and a name of no account to none.
"""

import os
import shutil
import subprocess
import threading

import pytest

from neutrino_client.exceptions import LocalPortTakenError
from neutrino_client.services.ssh import (
    SshConfigWriter,
    host_key_alias,
    keep_forwards,
)

MATERIAL = {"private_key": "key", "host_key": "ssh-ed25519 AAAA"}  # scan: allow
REWRITES_AT_ONCE = 64
INCLUDE_EDITS_AT_ONCE = 16
INCLUDE_EDITS_EACH = 50
# How long a test blocks a rewrite while another thread works.
HELD_REWRITE_WAIT_S = 0.2


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


def machine(name: str) -> dict:
    """The arguments of a refresh that lists one machine."""
    return {
        "entries": [
            dict(
                ssh_entry("SHA256:one"),
                id=f"ssh_server_{name}_lab",
                app_id=f"ssh_server_{name}",
            )
        ],
        "apps": [
            {
                "hub_id": "h1",
                "id": f"ssh_server_{name}",
                "local_name": f"ssh.{name}.localhost",
            }
        ],
        "hub_names": {},
    }


class Rewrites:
    """A ``start_thread`` that runs each rewrite on a thread and keeps what it raises."""

    def __init__(self):
        self.failures = []
        self._threads = []

    def __call__(self, target) -> None:
        thread = threading.Thread(target=self._run, args=(target,))
        self._threads.append(thread)
        thread.start()

    def join(self) -> None:
        for thread in self._threads:
            thread.join(timeout=30)

    def _run(self, target) -> None:
        try:
            target()
        except OSError as error:
            self.failures.append(error)


def test_many_rewrites_at_once_all_finish_and_the_newest_list_stays(tmp_path):
    rewrites = Rewrites()
    writer = SshConfigWriter(
        home=str(tmp_path),
        open_service=lambda hub_id, entry_id: MATERIAL,
        log=str,
        start_thread=rewrites,
    )

    for number in range(REWRITES_AT_ONCE):
        writer.refresh(**machine(f"m{number}"))
    rewrites.join()

    newest = f"m{REWRITES_AT_ONCE - 1}"
    assert rewrites.failures == []
    assert writer.config_text()["text"].startswith(f"Host {newest}.nt\n")
    assert sorted(os.listdir(writer.keys_dir)) == ["known_hosts", f"{newest}_lab"]
    assert sorted(os.listdir(os.path.dirname(writer.config_path))) == [
        "neutrino",
        "neutrino_config",
    ]


def test_a_rewrite_held_by_a_slow_hub_never_replaces_a_newer_list(tmp_path):
    rewrites = Rewrites()
    newer_is_written = threading.Event()

    def open_service(hub_id, entry_id):
        if entry_id == "ssh_server_old_lab":
            newer_is_written.wait(timeout=HELD_REWRITE_WAIT_S)
        return MATERIAL

    writer = SshConfigWriter(
        home=str(tmp_path),
        open_service=open_service,
        log=str,
        on_change=newer_is_written.set,
        start_thread=rewrites,
    )

    writer.refresh(**machine("old"))
    writer.refresh(**machine("new"))
    rewrites.join()

    assert rewrites.failures == []
    assert writer.config_text()["text"].startswith("Host new.nt\n")
    assert sorted(os.listdir(writer.keys_dir)) == ["known_hosts", "new_lab"]


def test_a_clear_during_a_rewrite_leaves_no_file_behind(tmp_path):
    rewrites = Rewrites()
    is_reading = threading.Event()
    is_cleared = threading.Event()

    def open_service(hub_id, entry_id):
        is_reading.set()
        is_cleared.wait(timeout=HELD_REWRITE_WAIT_S)
        return MATERIAL

    writer = SshConfigWriter(
        home=str(tmp_path),
        open_service=open_service,
        log=str,
        start_thread=rewrites,
    )

    def clear() -> None:
        writer.clear()
        is_cleared.set()

    writer.refresh(**machine("lab"))
    is_reading.wait(timeout=5)
    clearing = threading.Thread(target=clear)
    clearing.start()
    rewrites.join()
    clearing.join(timeout=30)

    assert rewrites.failures == []
    assert not os.path.exists(writer.config_path)
    assert not os.path.exists(writer.keys_dir)


def test_a_stop_waits_for_a_rewrite_running(tmp_path):
    rewrites = Rewrites()
    is_reading = threading.Event()
    may_answer = threading.Event()

    def open_service(hub_id, entry_id):
        is_reading.set()
        may_answer.wait(timeout=5)
        return MATERIAL

    writer = SshConfigWriter(
        home=str(tmp_path),
        open_service=open_service,
        log=str,
        start_thread=rewrites,
    )

    writer.refresh(**machine("lab"))
    assert is_reading.wait(timeout=5)
    stopping = threading.Thread(target=writer.stop)
    stopping.start()
    stopping.join(timeout=HELD_REWRITE_WAIT_S)
    assert stopping.is_alive()

    may_answer.set()
    stopping.join(timeout=5)
    assert not stopping.is_alive()
    assert os.path.exists(writer.config_path)
    rewrites.join()
    assert rewrites.failures == []


def test_a_rewrite_waiting_at_a_stop_and_a_refresh_after_it_write_nothing(tmp_path):
    started = []
    writer = SshConfigWriter(
        home=str(tmp_path),
        open_service=lambda hub_id, entry_id: MATERIAL,
        log=str,
        start_thread=started.append,
    )

    writer.refresh(**machine("waiting"))
    writer.stop()
    writer.stop()
    writer.refresh(**machine("after"))
    for rewrite in started:
        rewrite()

    assert len(started) == 1
    assert not os.path.exists(os.path.dirname(writer.config_path))


def test_many_include_edits_at_once_all_finish_and_keep_the_persons_lines(tmp_path):
    writer = SshConfigWriter(home=str(tmp_path), log=str)
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh/config").write_text("Host mine\n    User me\n")
    barrier = threading.Barrier(INCLUDE_EDITS_AT_ONCE)
    failures = []

    def edit(is_installed: bool) -> None:
        barrier.wait(timeout=30)
        try:
            for _ in range(INCLUDE_EDITS_EACH):
                writer.set_include(is_installed)
        except OSError as error:
            failures.append(error)

    threads = [
        threading.Thread(target=edit, args=(number % 2 == 0,))
        for number in range(INCLUDE_EDITS_AT_ONCE)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert failures == []
    assert os.listdir(tmp_path / ".ssh") == ["config"]
    assert (tmp_path / ".ssh/config").read_text().endswith("Host mine\n    User me\n")


def two_accounts() -> dict:
    """The arguments of a refresh that lists one machine with the accounts lab and Iffi."""
    return {
        "entries": [
            dict(ssh_entry("SHA256:one")),
            dict(
                ssh_entry("SHA256:one"),
                id="ssh_server_d1_Iffi",
                payload={
                    "account": "Iffi",
                    "host_key_fingerprint": "SHA256:iffi",
                    "account_key_fingerprint": "SHA256:one",
                },
            ),
        ],
        "apps": [
            {"hub_id": "h1", "id": "ssh_server_d1", "local_name": "ssh.lab.localhost"}
        ],
        "hub_names": {},
    }


def instance_keys(hub_id, entry_id):
    """Each account's own key and its instance's own host key."""
    account = entry_id.rsplit("_", 1)[-1]
    return {"private_key": f"key-{account}", "host_key": f"ssh-ed25519 HOST{account}"}


def written_two_accounts(tmp_path) -> SshConfigWriter:
    writer = SshConfigWriter(
        home=str(tmp_path),
        open_service=instance_keys,
        log=str,
        start_thread=run_inline,
    )
    writer.refresh(**two_accounts())
    return writer


def test_an_alias_writes_each_capital_after_a_mark():
    assert host_key_alias("lab", "lab") == "lab@lab.nt"
    assert host_key_alias("lab.home", "Iffi") == "+iffi@lab.home.nt"
    assert host_key_alias("lab", "iffi") != host_key_alias("lab", "Iffi")


def test_each_account_key_is_kept_under_that_account_alias_alone(tmp_path):
    writer = written_two_accounts(tmp_path)

    with open(os.path.join(writer.keys_dir, "known_hosts"), encoding="utf-8") as file:
        known = file.read()
    text = writer.config_text()["text"]

    assert known == (
        "lab@lab.nt ssh-ed25519 HOSTlab\n" "+iffi@lab.nt ssh-ed25519 HOSTIffi\n"
    )
    host_block, *match_blocks = text.strip().split("\n\n")
    assert host_block.startswith("Host lab.nt\n    User lab\n")
    assert "HostKeyAlias" not in host_block
    assert match_blocks == [
        'Match originalhost lab.nt user "lab"\n    HostKeyAlias lab@lab.nt',
        'Match originalhost lab.nt user "Iffi"\n    HostKeyAlias +iffi@lab.nt',
    ]


def resolved_alias(config_path: str, target: str) -> str:
    """The ``hostkeyalias`` the system's ``ssh -G`` resolves for a target."""
    printed = subprocess.run(
        ["ssh", "-G", "-F", config_path, target],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    for line in printed.splitlines():
        key, _, value = line.partition(" ")
        if key == "hostkeyalias":
            return value
    return ""


@pytest.mark.skipif(shutil.which("ssh") is None, reason="no ssh on this machine")
def test_ssh_resolves_each_account_to_its_own_alias(tmp_path):
    writer = written_two_accounts(tmp_path)

    assert resolved_alias(writer.config_path, "lab@lab.nt") == "lab@lab.nt"
    assert resolved_alias(writer.config_path, "Iffi@lab.nt") == "+iffi@lab.nt"
    assert resolved_alias(writer.config_path, "lab.nt") == "lab@lab.nt"
    assert resolved_alias(writer.config_path, "carol@lab.nt") == ""
