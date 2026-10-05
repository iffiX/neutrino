"""The relay's supervisor against a fake controller and a fake ssh.

The applier writes the key file root-only from the vault, hands the start
line to the controller and starts the process only when something changed;
a locked vault leaves no key file; turning the relay off stops it and
deletes the key. The monitor turns the process and the self-check into
the states of network.md, and only the hub's own certificate at the public
address is ``connected``.
"""

import base64
import hashlib
import json
import socket
import ssl
import stat
import threading

import asyncssh
import pytest

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.devices.key_registry import KeyRegistry
from neutrino_hub.modules.overlay import relay_ops
from neutrino_hub.modules.overlay.relay_config import OverlayRelayConfig, write_relay
from neutrino_hub.modules.overlay.relay_ops import (
    OverlayRelayApplier,
    OverlayRelayMonitor,
    check_public_address,
    host_key_fingerprint,
)
from neutrino_hub.system.process_control import ServiceStatus
from neutrino_hub.system.systemd_ctl import start_line_dropin
from tests.conftest import FakeClock, self_signed_pair, unlock_vault

PASSPHRASE = "opens-the-key"
OWN_FINGERPRINT = "a" * 64


class FakeController:
    """The process controller, recording each verb on the relay."""

    def __init__(self):
        self.calls: list = []
        self.is_running = False
        self.is_on = False
        self.process_ids: list = []
        self.output: list = []
        self.start_line = None

    def status(self, name):
        return ServiceStatus(name, name, True, self.is_running, self.is_on)

    def is_active(self, name):
        return self.is_running

    def is_enabled(self, name):
        return self.is_on

    def set_start_line(self, name, argv, env, cwd):
        self.calls.append(("start_line", argv))
        self.start_line = argv

    def enable(self, name):
        self.calls.append(("enable",))
        self.is_on = True
        self.is_running = True

    def disable(self, name):
        self.calls.append(("disable",))
        self.is_on = False
        self.is_running = False

    def restart(self, name):
        self.calls.append(("restart",))
        self.is_running = True

    def stop(self, name):
        self.calls.append(("stop",))
        self.is_running = False

    def reload(self):
        self.calls.append(("reload",))

    def process_id(self, name):
        return self.process_ids.pop(0) if self.process_ids else 0

    def run_output(self, name, *, line_count):
        return list(self.output)


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A Linux hub with an unlocked vault holding one key."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    state = tmp_path / "state"
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    monkeypatch.setattr(relay_ops, "UTILS_STATE_ROOT", state)
    monkeypatch.setattr(relay_ops, "SYSTEM_SYSTEMD_DIR", systemd)
    monkeypatch.setattr(relay_ops, "SYSTEM_SERVICES_STATE_PATH", state / "s.json")
    monkeypatch.setattr(relay_ops, "is_linux", lambda: True)
    monkeypatch.setattr(relay_ops, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(relay_ops, "ssh_path", lambda: "/usr/bin/ssh")
    key = asyncssh.generate_private_key("ssh-ed25519")
    record = KeyRegistry().add(
        name="relay", private_key=key.export_private_key().decode()
    )
    relay = OverlayRelayConfig(
        is_enabled=True,
        host="203.0.113.5",
        account="relay",
        key_id=record.id,
        public_port=18443,
    )
    write_relay(relay)
    return {
        "relay": relay,
        "key": key,
        "state": state,
        "systemd": systemd,
        "controller": FakeController(),
    }


def applier(box) -> OverlayRelayApplier:
    return OverlayRelayApplier(controller=box["controller"], agent_port=8443)


# --- the applier --------------------------------------------------------------


def test_the_key_file_is_written_root_only_without_its_passphrase(box):
    key = asyncssh.generate_private_key("ssh-ed25519")
    record = KeyRegistry().add(
        name="encrypted",
        private_key=key.export_private_key(passphrase=PASSPHRASE).decode(),
        passphrase=PASSPHRASE,
    )
    box["key"] = key
    applier(box).apply(
        OverlayRelayConfig(**{**vars(box["relay"]), "key_id": record.id})
    )

    path = box["state"] / "relay" / "key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    loaded = asyncssh.import_private_key(path.read_text())
    assert loaded.get_fingerprint() == box["key"].get_fingerprint()


def test_the_start_line_reaches_the_unit_and_the_relay_starts(box):
    change = applier(box).apply(box["relay"])

    controller = box["controller"]
    argv = controller.start_line
    assert change == "relay_started"
    assert argv[0] == "/usr/bin/ssh"
    assert argv[-2:] == ["0.0.0.0:18443:127.0.0.1:8443", "relay@203.0.113.5"]
    assert f"UserKnownHostsFile={box['state'] / 'relay' / 'known_hosts'}" in argv
    assert [call[0] for call in controller.calls] == [
        "reload",
        "start_line",
        "enable",
        "restart",
    ]
    unit = (box["systemd"] / "neutrino_hub_relay.service").read_text()
    assert "RestartSec=10" in unit


def test_an_apply_with_nothing_changed_restarts_nothing(box):
    controller = box["controller"]
    applier(box).apply(box["relay"])
    dropin = box["systemd"] / "neutrino_hub_relay.service.d" / "arguments.conf"
    dropin.parent.mkdir()
    dropin.write_text(start_line_dropin(controller.start_line, {}, None))
    controller.calls.clear()

    assert applier(box).apply(box["relay"]) == ""
    assert controller.calls == []


def test_a_restart_asked_for_starts_the_relay_again(box):
    controller = box["controller"]
    applier(box).apply(box["relay"])
    dropin = box["systemd"] / "neutrino_hub_relay.service.d" / "arguments.conf"
    dropin.parent.mkdir()
    dropin.write_text(start_line_dropin(controller.start_line, {}, None))
    controller.calls.clear()

    assert applier(box).apply(box["relay"], is_restarted=True) == "relay_started"
    assert ("restart",) in controller.calls


def test_turning_the_relay_off_stops_it_and_deletes_the_key(box):
    controller = box["controller"]
    applier(box).apply(box["relay"])
    controller.calls.clear()

    off = OverlayRelayConfig(**{**vars(box["relay"]), "is_enabled": False})

    assert applier(box).apply(off) == "relay_stopped"
    assert ("stop",) in controller.calls and ("disable",) in controller.calls
    assert ("start_line", None) in controller.calls
    assert not (box["state"] / "relay" / "key").exists()


def test_a_key_gone_from_the_vault_stops_the_relay(box):
    applier(box).apply(box["relay"])
    KeyRegistry().delete(box["relay"].key_id)

    assert applier(box).apply(box["relay"]) == "relay_stopped"
    assert not (box["state"] / "relay" / "key").exists()


def test_a_machine_with_no_ssh_runs_no_relay(box, monkeypatch):
    monkeypatch.setattr(relay_ops, "ssh_path", lambda: "")

    assert applier(box).apply(box["relay"]) == ""
    assert box["controller"].calls == []


def test_a_locked_vault_writes_no_key_and_starts_nothing(box, monkeypatch):
    def locked(key_id):
        raise VaultLockedError()

    monkeypatch.setattr(relay_ops, "openssh_key_text", locked)

    assert applier(box).apply(box["relay"]) == ""
    assert not (box["state"] / "relay" / "key").exists()
    assert box["controller"].calls == []


def test_a_locked_vault_leaves_a_running_relay_alone(box, monkeypatch):
    applier(box).apply(box["relay"])
    box["controller"].calls.clear()

    def locked(key_id):
        raise VaultLockedError()

    monkeypatch.setattr(relay_ops, "openssh_key_text", locked)

    assert applier(box).apply(box["relay"]) == ""
    assert (box["state"] / "relay" / "key").exists()
    assert box["controller"].calls == []


def test_a_development_root_on_linux_drives_no_unit(box, monkeypatch):
    monkeypatch.setattr(relay_ops, "is_dev_root_set", lambda: True)

    assert applier(box).apply(box["relay"]) == ""
    assert box["controller"].calls == []
    assert (box["state"] / "relay" / "key").exists()


def test_outside_linux_the_start_line_is_held_by_the_service(box, monkeypatch):
    monkeypatch.setattr(relay_ops, "is_linux", lambda: False)
    controller = box["controller"]

    assert applier(box).apply(box["relay"]) == "relay_started"
    assert [call[0] for call in controller.calls] == ["start_line", "enable"]

    (box["state"] / "s.json").write_text(
        json.dumps({"start_lines": {"relay": {"argv": controller.start_line}}})
    )
    controller.calls.clear()
    assert applier(box).apply(box["relay"]) == ""


# --- the monitor --------------------------------------------------------------


class Checks:
    """The self-check, answering what a test set."""

    def __init__(self, answer: str = OWN_FINGERPRINT):
        self.answer = answer
        self.asked: list = []

    def __call__(self, host, port, *, timeout_s):
        self.asked.append((host, port))
        return self.answer


def monitor(box, checks, clock) -> OverlayRelayMonitor:
    return OverlayRelayMonitor(
        controller=box["controller"],
        fingerprint_of=lambda: OWN_FINGERPRINT,
        check=checks,
        clock=clock,
    )


def running(box, process_id: int = 501) -> None:
    """The relay runs as one process from here on."""
    box["controller"].process_ids = [process_id] * 1000
    (box["state"] / "relay").mkdir(parents=True, exist_ok=True)
    (box["state"] / "relay" / "key").write_text("key")


def test_a_relay_that_is_off_is_disabled(box):
    write_relay(OverlayRelayConfig())

    assert monitor(box, Checks(), FakeClock()).view()["state"] == "disabled"


def test_a_relay_with_no_key_in_the_vault_is_not_configured(box):
    KeyRegistry().delete(box["relay"].key_id)

    assert monitor(box, Checks(), FakeClock()).view()["state"] == "not_configured"


def test_a_locked_vault_with_no_key_file_is_vault_locked(box, monkeypatch):
    class LockedVault:
        def is_locked(self):
            return True

    monkeypatch.setattr(relay_ops, "SecretVault", LockedVault)

    assert monitor(box, Checks(), FakeClock()).view()["state"] == "vault_locked"


def test_a_new_process_is_connecting_until_its_first_check(box):
    running(box)
    clock = FakeClock()
    checks = Checks()
    watched = monitor(box, checks, clock)

    watched.tick()
    clock.now += 4
    watched.tick()

    assert watched.view()["state"] == "connecting"
    assert checks.asked == []


def test_the_hubs_own_certificate_at_the_public_address_is_connected(box):
    running(box)
    clock = FakeClock()
    checks = Checks()
    watched = monitor(box, checks, clock)

    watched.tick()
    clock.now += 5
    watched.tick()

    view = watched.view()
    assert checks.asked == [("203.0.113.5", 18443)]
    assert view["state"] == "connected"
    assert view["last_error"] == ""
    assert view["checked_at"] != ""


def test_a_foreign_certificate_is_port_closed(box):
    running(box)
    clock = FakeClock()
    watched = monitor(box, Checks("b" * 64), clock)

    watched.tick()
    clock.now += 5
    watched.tick()

    view = watched.view()
    assert view["state"] == "port_closed"
    assert view["last_error"] == "another certificate at 203.0.113.5:18443"


def test_no_answer_at_the_public_address_is_port_closed(box):
    running(box)
    clock = FakeClock()
    watched = monitor(box, Checks(""), clock)

    watched.tick()
    clock.now += 5
    watched.tick()

    assert watched.view()["state"] == "port_closed"
    assert watched.view()["last_error"] == "no answer at 203.0.113.5:18443"


def test_the_check_runs_again_each_interval_and_not_between(box):
    running(box)
    clock = FakeClock()
    checks = Checks()
    watched = monitor(box, checks, clock)
    watched.tick()
    clock.now += 5
    watched.tick()

    clock.now += 59
    watched.tick()
    assert len(checks.asked) == 1
    clock.now += 1
    watched.tick()
    assert len(checks.asked) == 2


def test_a_restarted_process_is_connecting_again(box):
    running(box, 501)
    clock = FakeClock()
    watched = monitor(box, Checks(), clock)
    watched.tick()
    clock.now += 5
    watched.tick()
    assert watched.view()["state"] == "connected"

    running(box, 777)
    watched.tick()

    assert watched.view()["state"] == "connecting"


@pytest.mark.parametrize(
    ("line", "state"),
    [
        ("relay@203.0.113.5: Permission denied (publickey).", "auth_failed"),
        ("Host key verification failed.", "host_key_changed"),
        (
            "Error: remote port forwarding failed for listen port 18443",
            "forward_refused",
        ),
        ("ssh: connect to host 203.0.113.5 port 22: No route to host", "unreachable"),
    ],
)
def test_an_ended_ssh_is_judged_by_what_it_wrote(box, line, state):
    (box["state"] / "relay").mkdir(parents=True)
    (box["state"] / "relay" / "key").write_text("key")
    box["controller"].output = ["Warning: Permanently added", line]

    view = monitor(box, Checks(), FakeClock()).view()

    assert view["state"] == state
    assert view["last_error"] == line


def test_a_relay_that_never_ran_is_connecting(box):
    (box["state"] / "relay").mkdir(parents=True)
    (box["state"] / "relay" / "key").write_text("key")

    assert monitor(box, Checks(), FakeClock()).view()["state"] == "connecting"


# --- the host key and the check ----------------------------------------------


def test_the_recorded_host_key_reads_in_openssh_form(box):
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    blob = host_key.export_public_key("openssh").decode().split()[1]
    (box["state"] / "relay").mkdir(parents=True)
    (box["state"] / "relay" / "known_hosts").write_text(
        f"[203.0.113.5]:22 ssh-ed25519 {blob}\n"
    )

    fingerprint = host_key_fingerprint()

    digest = base64.b64encode(hashlib.sha256(base64.b64decode(blob)).digest())
    assert fingerprint == f"SHA256:{digest.decode().rstrip('=')}"
    assert fingerprint == host_key.get_fingerprint("sha256")


def test_no_recorded_host_key_reads_empty(box):
    assert host_key_fingerprint() == ""


def test_the_check_reads_the_certificate_at_the_address(tmp_path):
    certificate, key, fingerprint = self_signed_pair(tmp_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve_once():
        connection, _ = listener.accept()
        try:
            with context.wrap_socket(connection, server_side=True):
                pass
        except (OSError, ssl.SSLError):
            pass

    server = threading.Thread(target=serve_once, daemon=True)
    server.start()
    try:
        assert check_public_address("127.0.0.1", port, timeout_s=5) == fingerprint
    finally:
        server.join(timeout=5)
        listener.close()


def test_a_closed_address_answers_with_no_certificate():
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()

    assert check_public_address("127.0.0.1", port, timeout_s=2) == ""


def test_the_known_hosts_file_is_root_only_before_ssh_first_runs(box):
    applier(box).apply(box["relay"])

    path = box["state"] / "relay" / "known_hosts"
    assert path.read_text() == ""
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_known_hosts_file_ssh_left_readable_is_made_root_only(box):
    path = box["state"] / "relay" / "known_hosts"
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text("203.0.113.5 ssh-ed25519 AAAA\n")
    path.chmod(0o644)

    applier(box).apply(box["relay"])

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text() == "203.0.113.5 ssh-ed25519 AAAA\n"
