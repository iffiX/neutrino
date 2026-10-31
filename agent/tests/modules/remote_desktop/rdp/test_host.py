"""Sharing this machine's desktop as the hub's switch orders.

The switch on takes RustDesk over in a fixed order and writes the settings
with nothing running; off, it gives back what was there, settings files
included. A share is declared only while the agent's copy listens, read
from the socket table, and the seat password enters no report. The
system's registration is a fake applier here; each system's own is pinned
in its own file.
"""

import ast
import os
import shutil
import socket

import pytest

from neutrino_agent.core.store import MachineStateStore
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.modules.remote_desktop.rdp.host import RdpShareHost

COPY = "/opt/agent/rustdesk/rustdesk"


class FakeSeat:
    """A seat saying exactly what a test wants it to."""

    def __init__(self):
        self.seated = ["pat"]
        self.connected = 0
        self.attention = ""
        self.attention_homes = []
        self.asked = []
        self.homes = []

    def ask_for_permissions(self, account):
        self.asked.append(account)

    def graphical_accounts(self):
        return self.seated

    def account_homes(self):
        return list(self.homes)

    def has_desktop_session(self):
        return True

    def connected_count(self, port):
        return self.connected

    def screen_attention(self, account_home):
        self.attention_homes.append(account_home)
        return self.attention


class FakeApplier:
    """A system's registration that records what it was asked, in order."""

    def __init__(self, root):
        self.program = COPY
        self.root = root
        self.calls = []
        self.is_present = True
        self.is_own = False
        self.pids = []
        self.listeners = []
        self.failing = ""
        self.seen_at_register = {}
        self.stale = []
        self.service = True

    def _step(self, name):
        self.calls.append(name)
        if self.failing == name:
            raise OSError(f"{name} refused")

    def is_copy_present(self):
        return self.is_present

    def settings_dirs(self, seat_home):
        dirs = [os.path.join(self.root, "root_settings")]
        if seat_home:
            dirs.append(os.path.join(seat_home, ".config", "rustdesk"))
        return dirs

    def is_registered(self):
        return self.is_own

    def keep_aside(self):
        self._step("keep")
        return {}

    def stop_hosts(self):
        self._step("stop")
        self.pids = []

    def register(self):
        self._step("register")
        for directory in self.settings_dirs(os.path.join(self.root, "home", "pat")):
            for name in ("RustDesk2.toml", "RustDesk.toml"):
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    with open(path, encoding="utf-8") as stream:
                        self.seen_at_register[path] = stream.read()
        self.is_own = True

    def start(self, seat_uid):
        self._step("start")
        self.pids = [41]
        self.listeners = [COPY]

    def unregister(self):
        self._step("unregister")
        self.is_own = False
        self.pids = []
        self.listeners = []

    def restore(self):
        self._step("restore")

    def copy_pids(self):
        return list(self.pids)

    def stale_pids(self):
        return list(self.stale)

    def is_service_running(self):
        return self.service

    def listening_programs(self, port):
        self.calls.append(("listening", port))
        return list(self.listeners)


class _Platform(AgentPlatform):
    def __init__(self, root):
        super().__init__()
        self.root = root

    def account_home(self, account):
        return os.path.join(self.root, "home", account)


@pytest.fixture()
def host(tmp_path):
    store = MachineStateStore(path=str(tmp_path / "state.json"))
    applier = FakeApplier(str(tmp_path))
    made = RdpShareHost(
        platform=_Platform(str(tmp_path)),
        store=store,
        credentials_dir=str(tmp_path / "credentials"),
        state_dir=str(tmp_path / "var"),
        log=lambda message: None,
        seat=FakeSeat(),
        applier=applier,
    )
    made.applier = applier
    made.seat = made._seat
    made.store = store
    made.root = tmp_path
    return made


def _steps(applier):
    return [call for call in applier.calls if isinstance(call, str)]


def _root_file(host, name):
    return host.root / "root_settings" / name


def _seat_file(host, name):
    return host.root / "home" / "pat" / ".config" / "rustdesk" / name


# --- the switch on ---


def test_the_switch_on_takes_rustdesk_over_in_order(host):
    host.take_seat_password("seat-pass")

    host.set_switch(True)

    assert _steps(host.applier) == ["keep", "stop", "register", "start"]


def test_the_settings_are_written_before_the_copy_is_registered(host):
    """A running host writes back what it holds as it exits, so the files
    are written with nothing running."""
    host.take_seat_password("seat-pass")

    host.set_switch(True)

    options = host.applier.seen_at_register[str(_root_file(host, "RustDesk2.toml"))]
    assert "custom-rendezvous-server = '127.0.0.1'" in options
    assert "relay-server = '127.0.0.1'" in options
    assert "direct-server = 'Y'" in options
    password = host.applier.seen_at_register[str(_root_file(host, "RustDesk.toml"))]
    assert "password = 'seat-pass'" in password


def test_the_seat_gets_the_options_and_the_password_goes_to_the_service_alone(host):
    """The session's host takes the password from the service and stores it
    in its own form, so a plain copy there would read as changed forever."""
    host.take_seat_password("seat-pass")

    host.set_switch(True)

    assert "direct-server = 'Y'" in _seat_file(host, "RustDesk2.toml").read_text()
    assert not _seat_file(host, "RustDesk.toml").exists()


def test_the_seats_own_password_form_does_not_restart_the_host(host):
    host.take_seat_password("seat-pass")
    host.set_switch(True)
    rewritten = "password = '00encrypted'\n"  # scan: allow
    _seat_file(host, "RustDesk.toml").write_text(rewritten)
    host.applier.calls.clear()

    host.set_switch(True)

    assert _steps(host.applier) == []


def test_with_no_seat_password_no_password_file_is_written(host):
    host.set_switch(True)

    assert _root_file(host, "RustDesk2.toml").exists()
    assert not _root_file(host, "RustDesk.toml").exists()


def test_a_switch_on_that_stands_already_touches_nothing(host):
    host.take_seat_password("seat-pass")
    host.set_switch(True)
    host.applier.calls.clear()

    host.set_switch(True)

    assert _steps(host.applier) == []


def test_a_new_seat_password_is_written_with_the_host_stopped(host):
    host.take_seat_password("first")
    host.set_switch(True)
    host.applier.calls.clear()

    host.take_seat_password("second")
    host.set_switch(True)

    # Taking aside happens once; the second pass stops, writes and starts.
    assert _steps(host.applier) == ["stop", "register", "start"]
    written = _root_file(host, "RustDesk.toml").read_text()
    assert "password = 'second'" in written  # scan: allow


def test_a_copy_that_stopped_is_started_again(host):
    host.set_switch(True)
    host.applier.calls.clear()
    host.applier.pids = []

    host.set_switch(True)

    assert _steps(host.applier) == ["stop", "register", "start"]


def test_a_missing_copy_is_refused_before_anything_is_touched(host):
    host.applier.is_present = False

    with pytest.raises(ModuleApplyError) as raised:
        host.set_switch(True)

    assert raised.value.code == "rdp_takeover_failed"
    assert raised.value.params["step"] == "copy"
    assert COPY in raised.value.params["detail"]
    assert _steps(host.applier) == []


@pytest.mark.parametrize("step", ["keep", "stop", "register", "start"])
def test_a_failed_step_on_the_way_on_is_named(host, step):
    host.applier.failing = step

    with pytest.raises(ModuleApplyError) as raised:
        host.set_switch(True)

    assert raised.value.code == "rdp_takeover_failed"
    assert raised.value.params == {"step": step, "detail": f"{step} refused"}


def test_the_seated_person_is_asked_for_permissions_once(host):
    host.set_switch(True)
    host.applier.pids = []
    host.set_switch(True)

    assert host.seat.asked == ["pat"]


def test_nobody_at_the_screen_is_asked_nothing(host):
    host.seat.seated = []

    host.set_switch(True)

    assert host.seat.asked == []
    assert not _seat_file(host, "RustDesk2.toml").exists()


# --- the switch off ---


def test_the_switch_off_gives_rustdesk_back_in_order(host):
    host.set_switch(True)
    host.applier.calls.clear()

    host.set_switch(False)

    assert _steps(host.applier) == ["unregister", "restore"]
    assert not (host.root / "var" / "remote_desktop" / "registered.json").exists()
    assert not (host.root / "var" / "remote_desktop" / "kept").exists()


def test_settings_files_a_person_had_are_put_back_as_they_were(host):
    original = "[options]\ncustom-rendezvous-server = 'rs.example'\n"
    path = _root_file(host, "RustDesk2.toml")
    path.parent.mkdir(parents=True)
    path.write_text(original)
    host.take_seat_password("seat-pass")

    host.set_switch(True)
    assert "127.0.0.1" in path.read_text()
    host.set_switch(False)

    assert path.read_text() == original


def test_settings_files_nobody_had_are_taken_away(host):
    host.take_seat_password("seat-pass")
    host.set_switch(True)

    host.set_switch(False)

    assert not _root_file(host, "RustDesk2.toml").exists()
    assert not _root_file(host, "RustDesk.toml").exists()


def test_a_switch_off_with_nothing_registered_touches_nothing(host):
    host.set_switch(False)

    assert _steps(host.applier) == []


@pytest.mark.parametrize("step", ["unregister", "restore"])
def test_a_failed_step_on_the_way_off_is_named(host, step):
    host.set_switch(True)
    host.applier.failing = step

    with pytest.raises(ModuleApplyError) as raised:
        host.set_switch(False)

    assert raised.value.code == "rdp_restore_failed"
    assert raised.value.params["step"] == {"unregister": "stop"}.get(step, step)


def test_a_failed_switch_off_is_tried_again_by_the_same_press(host):
    host.set_switch(True)
    host.applier.failing = "restore"
    with pytest.raises(ModuleApplyError):
        host.set_switch(False)
    host.applier.failing = ""
    host.applier.calls.clear()

    host.set_switch(False)

    assert "restore" in _steps(host.applier)
    assert not (host.root / "var" / "remote_desktop" / "registered.json").exists()


def test_turning_off_for_the_agents_removal_gives_rustdesk_back(host):
    host.set_switch(True)
    host.applier.calls.clear()

    host.turn_off()

    assert _steps(host.applier) == ["unregister", "restore"]


# --- what is declared ---


def test_a_share_is_declared_once_the_copy_listens(host):
    host.set_switch(True)

    declared = host.declaration()

    assert declared["is_shared"] is True
    assert declared["port"] == 21118
    assert declared["account"] == "pat"
    assert declared["share_id"]


def test_a_share_whose_copy_does_not_listen_is_starting(host):
    host.set_switch(True)
    host.applier.listeners = []
    host._listened_at = 0.0

    assert host.declaration()["is_shared"] is False
    assert host.state()["state"] == "starting"


def test_another_program_on_the_port_is_not_the_share(host):
    host.set_switch(True)
    host.applier.listeners = ["/usr/bin/rustdesk"]
    host._listened_at = 0.0

    assert host.declaration()["is_shared"] is False


def test_the_listener_is_read_from_the_socket_table_and_no_connection_opened(
    host, monkeypatch
):
    def refuse(*args, **kwargs):
        raise AssertionError("the host dialed its own port")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    host.set_switch(True)

    assert host.declaration()["is_shared"] is True
    assert ("listening", 21118) in host.applier.calls


def test_the_share_id_holds_across_a_new_password(host):
    host.take_seat_password("first")
    host.set_switch(True)
    first = host.declaration()["share_id"]
    host.take_seat_password("second")
    host.set_switch(True)

    assert host.declaration()["share_id"] == first


def test_a_switch_off_declares_nothing(host):
    host.set_switch(True)
    host.set_switch(False)

    declared = host.declaration()
    assert declared["is_shared"] is False
    assert declared["share_id"] == ""
    assert host.state()["state"] == "not_shared"


def test_the_seat_password_is_in_no_report_and_not_in_the_store(host):
    host.take_seat_password("seat-pass")
    host.set_switch(True)

    assert "seat-pass" not in repr(host.declaration())
    assert "seat-pass" not in repr(host.state())
    assert "seat-pass" not in (host.root / "state.json").read_text()
    assert host.state()["has_password"] is True


def test_the_seat_password_is_kept_where_only_root_reads_it(host):
    host.take_seat_password("seat-pass")
    host.set_switch(True)

    kept = host.root / "credentials" / "rdp_access_password"
    assert kept.read_text() == "seat-pass"
    assert kept.stat().st_mode & 0o777 == 0o600


# --- a share the old command made ---


def _old_share(host):
    host.store.set_rdp_share(
        {"share_id": "old-id", "is_shared": True, "port": 21118, "account": "pat"}
    )


def test_an_old_share_is_taken_over_when_the_agent_starts(host):
    _old_share(host)

    host.resume_old_share()

    assert _steps(host.applier) == ["keep", "stop", "register", "start"]
    declared = host.declaration()
    assert declared["is_shared"] is True
    assert declared["share_id"] == "old-id"


def test_an_old_share_is_reported_until_the_first_state_names_the_module(host):
    _old_share(host)
    host.resume_old_share()

    host.set_switch(False)

    assert host.declaration()["is_shared"] is False
    assert host.store.rdp_share()["is_ordered"] is True


def test_the_first_state_switching_on_keeps_the_old_share_id(host):
    _old_share(host)
    host.resume_old_share()

    host.set_switch(True)

    assert host.declaration()["share_id"] == "old-id"


def test_without_an_old_share_nothing_is_taken_over_at_start(host):
    host.resume_old_share()

    assert _steps(host.applier) == []


def test_once_the_switch_decides_an_old_record_is_not_resumed(host):
    host.set_switch(False)

    host.resume_old_share()

    assert _steps(host.applier) == []


def test_an_old_share_that_cannot_be_taken_over_is_logged_not_raised(host):
    _old_share(host)
    host.applier.is_present = False

    host.resume_old_share()

    assert _steps(host.applier) == []


# --- what a peer would wait on ---


def test_a_seated_screen_answers_with_the_seats_own_attention(host):
    host.seat.attention = "rdp_screen_not_allowed"
    host.set_switch(True)

    assert host.declaration()["attention"] == "rdp_screen_not_allowed"
    assert host.seat.attention_homes == [str(host.root / "home" / "pat")]


def test_nobody_at_the_screen_is_its_own_answer(host):
    host.set_switch(True)
    host.seat.seated = []
    host._attention_at = 0.0

    assert host.declaration()["attention"] == "rdp_nobody_seated"


def test_a_greeters_session_holds_no_permission_it_could_keep(host):
    host.seat.seated = ["gdm"]
    host.set_switch(True)

    assert host.declaration()["attention"] == "rdp_nobody_seated"


def test_a_machine_that_shares_nothing_asks_the_seat_nothing(host):
    host.seat.connected = 3

    declared = host.declaration()

    assert declared["attention"] == ""
    assert declared["connected_count"] == 0
    assert host.seat.attention_homes == []


# --- an upgrade replaced the copy under a running host ---


def test_a_host_running_a_replaced_copy_is_started_again(host):
    host.set_switch(True)
    host.applier.calls.clear()
    host.applier.stale = [41]

    host.renew_if_replaced()

    assert _steps(host.applier) == ["stop", "start"]


def test_a_host_running_the_copy_on_disk_is_left_alone(host):
    host.set_switch(True)
    host.applier.calls.clear()
    host.applier.stale = []

    host.renew_if_replaced()

    assert _steps(host.applier) == []


def test_with_the_switch_off_nothing_is_started(host):
    host.applier.stale = [41]

    host.renew_if_replaced()

    assert _steps(host.applier) == []


def test_the_start_up_check_keeps_the_mark_and_the_settings(host):
    host.take_seat_password("seat-pass")
    host.set_switch(True)
    before = _root_file(host, "RustDesk2.toml").read_text()
    host.applier.stale = [41]

    host.settle_at_start()

    assert _root_file(host, "RustDesk2.toml").read_text() == before
    assert "register" not in _steps(host.applier)[-2:]


# --- leaving the hub, and where a share came from ---


def test_leaving_the_hub_cuts_the_share_off_and_gives_rustdesk_back(host):
    host.set_switch(True)
    host.applier.calls.clear()

    host.leave_hub()

    assert _steps(host.applier) == ["unregister", "restore"]
    assert host.declaration()["is_shared"] is False
    assert host.declaration()["origin"] == ""


def test_leaving_the_hub_ends_an_old_commands_record(host):
    _old_share(host)
    host.resume_old_share()

    host.leave_hub()
    host.resume_old_share()

    assert host.store.rdp_share() == {"is_ordered": True}
    assert host.declaration()["is_shared"] is False


def test_a_share_the_switch_made_names_the_switch(host):
    host.set_switch(True)

    assert host.declaration()["origin"] == "switch"


def test_a_share_an_old_commands_record_keeps_names_the_command(host):
    _old_share(host)
    host.resume_old_share()

    assert host.declaration()["origin"] == "command"


def test_the_service_runs_with_the_switch_on_whoever_is_at_the_screen(host):
    host.applier.service = True
    assert host.is_service_running() is False

    host.set_switch(True)
    host.seat.seated = []

    assert host.is_service_running() is True


def test_two_processes_giving_rustdesk_back_take_turns(host, tmp_path):
    """nagent leave in its own process and the service answering the hub's
    binding_unknown both give RustDesk back; the second finds it done."""
    import threading

    from neutrino_agent.modules.remote_desktop.records import held

    host.set_switch(True)
    lock = str(tmp_path / "var" / "remote_desktop" / ".lock")
    order = []

    def other_process():
        with held(lock):
            order.append("other")

    with held(lock):
        waiter = threading.Thread(target=other_process)
        waiter.start()
        waiter.join(0.5)
        assert order == []
        order.append("first")
    waiter.join(5)

    assert order == ["first", "other"]
    host.leave_hub()
    host.applier.calls.clear()
    host.leave_hub()
    assert _steps(host.applier) == []


# --- the seat's settings folders ---


def test_the_seats_settings_folders_are_made_as_the_seats_own(host, monkeypatch):
    """RustDesk running as the person at the screen cannot store its
    configuration in a folder left to root."""
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk

    home = host.root / "home" / "pat"
    home.mkdir(parents=True)
    real_stat = rustdesk._stat
    chowned = []

    class _Pat:
        st_uid = 4242
        st_gid = 4343
        st_mode = 0o755

    def stat(target):
        return _Pat() if target == str(home) else real_stat(target)

    def chown(target, uid, gid):
        chowned.append((target, uid, gid))

    monkeypatch.setattr(rustdesk, "_stat", stat)
    monkeypatch.setattr(rustdesk.os, "chown", chown)

    host.set_switch(True)

    folders = [entry for entry in chowned if not entry[0].endswith(".tmp")]
    assert folders == [
        (str(home / ".config"), 4242, 4343),
        (str(home / ".config" / "rustdesk"), 4242, 4343),
    ]


def _seat_folders_root_owns(host, monkeypatch):
    """The seat's settings folders there, reported as root's, under a home
    that reads as uid 4242; returns the ``chown`` calls."""
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk

    home = host.root / "home" / "pat"
    settings = home / ".config" / "rustdesk"
    settings.mkdir(parents=True, exist_ok=True)
    rooted = {str(home / ".config"), str(settings)}
    real_stat = rustdesk._stat
    real_lstat = rustdesk._lstat
    chowned = []

    class _Owned:
        def __init__(self, uid, mode):
            self.st_uid = uid
            self.st_gid = uid + 101
            self.st_mode = mode

    def stat(target):
        found = real_stat(target)
        if target == str(home) and found is not None:
            return _Owned(4242, found.st_mode)
        return found

    def lstat(target):
        found = real_lstat(target)
        if target in rooted and found is not None:
            return _Owned(0, found.st_mode)
        return found

    def chown(target, uid, gid):
        chowned.append((target, uid, gid))
        rooted.discard(target)

    monkeypatch.setattr(rustdesk, "_stat", stat)
    monkeypatch.setattr(rustdesk, "_lstat", lstat)
    monkeypatch.setattr(rustdesk.os, "chown", chown)
    return chowned


def test_a_standing_share_gives_the_seats_folders_root_owns_back(host, monkeypatch):
    host.set_switch(True)
    host.applier.calls.clear()
    chowned = _seat_folders_root_owns(host, monkeypatch)

    host.set_switch(True)

    home = host.root / "home" / "pat"
    assert _steps(host.applier) == []
    assert chowned == [
        (str(home / ".config"), 4242, 4343),
        (str(home / ".config" / "rustdesk"), 4242, 4343),
    ]


def test_the_agent_at_start_gives_the_seats_folders_root_owns_back(host, monkeypatch):
    """An unchanged state applies nothing after an upgrade, so the start
    does it."""
    host.set_switch(True)
    chowned = _seat_folders_root_owns(host, monkeypatch)

    host.settle_at_start()

    assert [target for target, _, _ in chowned] == [
        str(host.root / "home" / "pat" / ".config"),
        str(host.root / "home" / "pat" / ".config" / "rustdesk"),
    ]


def test_with_the_switch_off_the_seats_folders_are_left_alone(host, monkeypatch):
    chowned = _seat_folders_root_owns(host, monkeypatch)

    host.settle_at_start()

    assert chowned == []


# --- RustDesk's own settings over root's ---

# Sealed by libsodium as RustDesk 1.4.9 seals a password, keyed by
# MACHINE_ID; each is pinned against its text in test_rustdesk.py.
MACHINE_ID = "0123456789abcdef0123456789abcdef"
SEALED_SEAT_PASS = "00AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGG2fyudFFP3NcbnInbL1TKs2qvqEDMktoUs="  # scan: allow
SEALED_SOMEBODY_ELSE = "00AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGBSElnFzz9I+Uc3wfcpDZGI2oPaVQ9YoqxVyJktV"  # scan: allow


class _LinuxPlatform(_Platform):
    os_name = "linux"

    def __init__(self, root):
        super().__init__(root)
        self.machine_id_reads = 0

    def read_machine_id(self):
        self.machine_id_reads += 1
        return MACHINE_ID


@pytest.fixture()
def linux_host(tmp_path):
    store = MachineStateStore(path=str(tmp_path / "state.json"))
    applier = FakeApplier(str(tmp_path))
    platform = _LinuxPlatform(str(tmp_path))
    lines = []
    made = RdpShareHost(
        platform=platform,
        store=store,
        credentials_dir=str(tmp_path / "credentials"),
        state_dir=str(tmp_path / "var"),
        log=lines.append,
        seat=FakeSeat(),
        applier=applier,
    )
    made.applier = applier
    made.seat = made._seat
    made.root = tmp_path
    made.platform = platform
    made.lines = lines
    return made


def _rustdesk_wrote(host, password, *, has_key_pair=True):
    """Root's RustDesk.toml as RustDesk writes it: a sealed id, the password,
    the salt and the key pair, each array item on its own line."""
    pair = ["    [", "        12,", "        34,", "    ],", "    [", "        56,"]
    pair += ["    ],"] if has_key_pair else []
    lines = ["enc_id = '00AQIDBAUGBwgJCgsMDQ4PEBES'", f"password = '{password}'"]
    lines += ["salt = 'abc'", "key_pair = ["]
    lines += pair if has_key_pair else ["    [],", "    [],"]
    lines += ["]", "key_confirmed = false", "", "[keys_confirmed]", ""]
    path = _root_file(host, "RustDesk.toml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def _shared(host):
    """The switch on, on a machine where RustDesk wrote its id, its key pair
    and the sealed seat password before."""
    _rustdesk_wrote(host, SEALED_SEAT_PASS)
    host.take_seat_password("seat-pass")
    host.set_switch(True)
    _rustdesk_wrote(host, SEALED_SEAT_PASS)
    host.applier.calls.clear()


def _stored_password(host):
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk

    path = str(_root_file(host, "RustDesk.toml"))
    return rustdesk.stored_password(path, lambda: MACHINE_ID)


def test_a_password_rustdesk_emptied_later_is_written_again(linux_host):
    host = linux_host
    _shared(host)
    _rustdesk_wrote(host, "")

    host.repair_settings()

    assert _steps(host.applier) == ["stop", "start"]
    assert _stored_password(host) == "seat-pass"
    assert "56," in _root_file(host, "RustDesk.toml").read_text()
    assert any("the service's settings" in line for line in host.lines)


def test_a_password_of_somebody_elses_is_replaced_too(linux_host):
    """A person's own RustDesk sends the password it holds."""
    host = linux_host
    _shared(host)
    _rustdesk_wrote(host, SEALED_SOMEBODY_ELSE)

    host.repair_settings()

    assert _steps(host.applier) == ["stop", "start"]
    assert _stored_password(host) == "seat-pass"


@pytest.mark.parametrize("stored", [SEALED_SEAT_PASS, "seat-pass"])
def test_an_intact_password_is_a_file_read_and_no_command(
    linux_host, monkeypatch, stored
):
    import subprocess

    def refuse(*args, **kwargs):
        raise AssertionError("a command ran")

    host = linux_host
    _shared(host)
    _rustdesk_wrote(host, stored)
    before = _root_file(host, "RustDesk.toml").read_text()
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "check_output", refuse)

    host.repair_settings()
    host.repair_settings()

    assert host.applier.calls == []
    assert _root_file(host, "RustDesk.toml").read_text() == before
    assert host.platform.machine_id_reads <= 1


def test_a_sealed_password_that_does_not_open_here_is_left_alone(linux_host):
    host = linux_host
    _shared(host)
    host.platform.read_machine_id = lambda: "another-machine-id"
    host._machine_id_read = ""

    host.repair_settings()

    assert _steps(host.applier) == []


def test_with_the_switch_off_nothing_is_repaired(linux_host):
    host = linux_host
    _shared(host)
    host.set_switch(False)
    host.applier.calls.clear()
    _rustdesk_wrote(host, "")

    host.repair_settings()

    assert _steps(host.applier) == []


def test_a_repair_skips_the_turn_while_another_change_holds_the_lock(linux_host):
    host = linux_host
    _shared(host)
    _rustdesk_wrote(host, "")

    with host._lock:
        host.repair_settings()

    assert _steps(host.applier) == []


def test_a_failed_repair_is_logged_and_tried_at_the_next_report(linux_host):
    host = linux_host
    _shared(host)
    _rustdesk_wrote(host, "")
    host.applier.failing = "start"

    host.repair_settings()

    assert any("rdp_takeover_failed step=start" in line for line in host.lines)
    host.applier.failing = ""
    host.applier.calls.clear()
    _rustdesk_wrote(host, "")
    host.repair_settings()
    assert _steps(host.applier) == ["stop", "start"]


def test_the_same_password_sealed_restarts_nothing_at_a_state_push(linux_host):
    """RustDesk seals the plain password the agent wrote; the next state
    finds the share standing and drops no viewer."""
    host = linux_host
    _shared(host)

    host.set_switch(True)

    assert _steps(host.applier) == []
    assert "password = '00" in _root_file(host, "RustDesk.toml").read_text()


def test_a_state_push_over_another_sealed_password_writes_the_seat_one(linux_host):
    host = linux_host
    _shared(host)
    _rustdesk_wrote(host, SEALED_SOMEBODY_ELSE)

    host.set_switch(True)

    assert _steps(host.applier) == ["stop", "register", "start"]
    assert _stored_password(host) == "seat-pass"


def test_a_state_push_over_a_seal_that_does_not_open_here_writes_it_again(
    linux_host,
):
    host = linux_host
    _shared(host)
    host.platform.read_machine_id = lambda: "another-machine-id"
    host._machine_id_read = ""

    host.set_switch(True)

    assert _steps(host.applier) == ["stop", "register", "start"]
    assert "password = 'seat-pass'" in _root_file(host, "RustDesk.toml").read_text()


def test_on_windows_the_service_password_is_not_watched(linux_host):
    """The session's host there writes no settings over the service's."""
    host = linux_host
    host.platform.os_name = "windows"
    host.take_seat_password("seat-pass")

    host.set_switch(True)
    host.applier.calls.clear()
    _rustdesk_wrote(host, "")
    host.repair_settings()

    assert _steps(host.applier) == []


# --- a session's host that starts after the switch ---


def _session_host_options(host, seat_home):
    """The options a session's host of RustDesk 1.4.9 runs with.

    ``sync_and_watch_config_dir`` in its ``src/server.rs``: it asks the service
    for its settings before it dials anything, and takes them when the
    service's ``RustDesk.toml`` holds an id and a key pair. Otherwise the host
    keeps its own file, and no ``custom-rendezvous-server`` there means
    upstream's public server.
    """
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk

    if rustdesk.has_identity(str(_root_file(host, "RustDesk.toml"))):
        return rustdesk.read_options(str(_root_file(host, "RustDesk2.toml")))
    return rustdesk.read_options(
        os.path.join(seat_home, ".config", "rustdesk", "RustDesk2.toml")
    )


def test_a_session_that_appears_after_the_switch_takes_the_loopback(linux_host):
    """A display manager or a login that arrives after the switch: the agent
    wrote nothing for that account, and the host must not reach the public
    server."""
    host = linux_host
    host.seat.seated = []
    host.take_seat_password("seat-pass")

    host.set_switch(True)

    late = str(host.root / "home" / "late")
    assert _session_host_options(host, late)["custom-rendezvous-server"] == "127.0.0.1"
    assert _session_host_options(host, late)["relay-server"] == "127.0.0.1"
    assert _session_host_options(host, late)["direct-server"] == "Y"


def test_the_service_holds_a_real_id_and_key_pair_before_it_starts(linux_host):
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk
    from neutrino_agent.modules.remote_desktop.rdp.ed25519 import public_key

    host = linux_host
    host.seat.seated = []

    host.set_switch(True)

    path = str(_root_file(host, "RustDesk.toml"))
    assert path in host.applier.seen_at_register
    assert rustdesk.has_identity(path)
    secret, public = ast.literal_eval(rustdesk.read_values(path)["key_pair"])
    assert len(secret) == 64
    assert bytes(public) == bytes(secret[32:]) == public_key(bytes(secret[:32]))


def test_an_id_and_key_pair_rustdesk_made_are_kept(linux_host):
    host = linux_host
    _shared(host)
    before = _root_file(host, "RustDesk.toml").read_text()

    host.take_seat_password("second")
    host.set_switch(True)

    after = _root_file(host, "RustDesk.toml").read_text()
    assert "enc_id = '00AQIDBAUGBwgJCgsMDQ4PEBES'" in after
    assert before.split("key_pair")[1] == after.split("key_pair")[1]


def test_a_service_with_no_key_pair_is_given_one_with_the_host_stopped(linux_host):
    """The state of a machine a former agent switched on with nobody there."""
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk

    host = linux_host
    _shared(host)
    _rustdesk_wrote(host, "seat-pass", has_key_pair=False)

    host.set_switch(True)

    assert _steps(host.applier) == ["stop", "register", "start"]
    path = str(_root_file(host, "RustDesk.toml"))
    assert rustdesk.has_identity(path)
    assert "enc_id = '00AQIDBAUGBwgJCgsMDQ4PEBES'" in (
        _root_file(host, "RustDesk.toml").read_text()
    )


def test_the_seat_is_written_no_id_and_no_key_pair(linux_host):
    host = linux_host
    host.take_seat_password("seat-pass")

    host.set_switch(True)

    assert not _seat_file(host, "RustDesk.toml").exists()


def test_on_windows_the_service_is_given_no_id_and_no_key_pair(linux_host):
    host = linux_host
    host.platform.os_name = "windows"

    host.set_switch(True)

    assert not _root_file(host, "RustDesk.toml").exists()


def test_nothing_waits_for_rustdesk_after_a_start(linux_host):
    host = linux_host
    host.take_seat_password("seat-pass")

    host.set_switch(True)

    assert _steps(host.applier) == ["keep", "stop", "register", "start"]
    assert "password = 'seat-pass'" in _root_file(host, "RustDesk.toml").read_text()


# --- every account that can come to the screen ---


def _account(host, name, *files):
    """One account's home, holding the given settings files."""
    home = host.root / "home" / name
    settings = home / ".config" / "rustdesk"
    home.mkdir(parents=True, exist_ok=True)
    for file_name, text in files:
        settings.mkdir(parents=True, exist_ok=True)
        (settings / file_name).write_text(text)
    host.seat.homes.append(str(home))
    return settings


def test_every_account_gets_the_options_and_no_password(linux_host):
    host = linux_host
    host.seat.seated = []
    _account(host, "sam")
    settings = host.root / "home" / "sam" / ".config" / "rustdesk"
    host.take_seat_password("seat-pass")

    host.set_switch(True)

    options = (settings / "RustDesk2.toml").read_text()
    assert "custom-rendezvous-server = '127.0.0.1'" in options
    assert not (settings / "RustDesk.toml").exists()


def test_the_switch_off_takes_away_what_an_account_came_to_hold(linux_host):
    """A session's host writes both files once it took the service's."""
    host = linux_host
    host.seat.seated = []
    _account(host, "sam")
    settings = host.root / "home" / "sam" / ".config" / "rustdesk"
    host.set_switch(True)
    (settings / "RustDesk.toml").write_text("key_pair = [[1], [2]]\n")

    host.set_switch(False)

    assert not (settings / "RustDesk2.toml").exists()
    assert not (settings / "RustDesk.toml").exists()
    assert not settings.exists()


def test_the_switch_off_puts_back_an_accounts_own_settings(linux_host):
    host = linux_host
    host.seat.seated = []
    settings = _account(
        host,
        "sam",
        ("RustDesk2.toml", "[options]\ndirect-server = 'N'\n"),
        ("RustDesk.toml", "id = 'hers'\n"),
    )
    host.set_switch(True)
    (settings / "RustDesk.toml").write_text("id = 'overwritten by the host'\n")

    host.set_switch(False)

    assert (settings / "RustDesk2.toml").read_text() == (
        "[options]\ndirect-server = 'N'\n"
    )
    assert (settings / "RustDesk.toml").read_text() == "id = 'hers'\n"


def test_an_account_whose_home_refuses_is_logged_and_the_share_goes_on(
    linux_host, monkeypatch
):
    from neutrino_agent.exceptions import InstallError
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk

    host = linux_host
    host.seat.seated = []
    _account(host, "sam")
    written = rustdesk.write_settings

    def refuse(path, render, home=""):
        if os.sep + "sam" + os.sep in path:
            raise InstallError(f"could not write {path}")
        return written(path, render, home)

    monkeypatch.setattr(rustdesk, "write_settings", refuse)

    host.set_switch(True)

    assert _steps(host.applier) == ["keep", "stop", "register", "start"]
    assert any("could not write" in line for line in host.lines)


def test_an_account_removed_during_the_share_leaves_the_switch_off_working(linux_host):
    host = linux_host
    host.seat.seated = []
    _account(host, "sam", ("RustDesk2.toml", "[options]\n"))
    host.set_switch(True)
    shutil.rmtree(host.root / "home" / "sam")

    host.set_switch(False)

    assert not (host.root / "home" / "sam").exists()
    assert "restore" in _steps(host.applier)


def test_a_home_that_refuses_a_removal_is_logged_and_the_switch_goes_off(
    linux_host, monkeypatch
):
    host = linux_host
    host.seat.seated = []
    _account(host, "sam")
    host.set_switch(True)
    unlink = os.unlink

    def refuse(path, *args, **kwargs):
        if os.sep + "sam" + os.sep in str(path):
            raise PermissionError(f"refused {path}")
        unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", refuse)

    host.set_switch(False)

    assert "restore" in _steps(host.applier)
    assert any("could not delete" in line for line in host.lines)


def test_a_settings_folder_behind_a_link_is_left_alone(linux_host):
    host = linux_host
    host.seat.seated = []
    _account(host, "sam")
    elsewhere = host.root / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "RustDesk2.toml").write_text("not settings\n")
    config = host.root / "home" / "sam" / ".config"
    config.mkdir()
    (config / "rustdesk").symlink_to(elsewhere)

    host.set_switch(True)
    host.set_switch(False)

    assert (elsewhere / "RustDesk2.toml").read_text() == "not settings\n"


def test_a_link_planted_after_the_switch_is_not_written_through(linux_host):
    host = linux_host
    host.seat.seated = []
    settings = _account(host, "sam", ("RustDesk2.toml", "[options]\n"))
    host.set_switch(True)
    target = host.root / "target"
    target.write_text("not settings\n")
    (settings / "RustDesk2.toml").unlink()
    (settings / "RustDesk2.toml").symlink_to(target)

    host.set_switch(False)

    assert target.read_text() == "not settings\n"
    assert not (settings / "RustDesk2.toml").is_symlink()


# --- the service's settings at each report ---


def _options_rustdesk_wrote(host, text):
    _root_file(host, "RustDesk2.toml").write_text(text)


EMPTY_OPTIONS = "rendezvous_server = ''\nnat_type = 1\nserial = 0\n\n[options]\n"
OPTIONS_IN_ITS_ORDER = (
    "rendezvous_server = ''\n\n[options]\ndirect-server = 'Y'\n"
    "relay-server = '127.0.0.1'\ncustom-rendezvous-server = '127.0.0.1'\n"
)


def test_servers_a_session_wiped_from_the_service_are_written_again(linux_host):
    """A session's host that kept its own empty options sends them to the
    service, and the next host starts from there."""
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk

    host = linux_host
    _shared(host)
    _options_rustdesk_wrote(host, EMPTY_OPTIONS)

    host.repair_settings()

    assert _steps(host.applier) == ["stop", "start"]
    options = rustdesk.read_options(str(_root_file(host, "RustDesk2.toml")))
    assert options["custom-rendezvous-server"] == "127.0.0.1"
    assert options["relay-server"] == "127.0.0.1"
    assert options["direct-server"] == "Y"
    assert any("the service's settings" in line for line in host.lines)


def test_a_service_with_no_key_pair_gets_one_at_the_next_report(linux_host):
    """The state a former agent left on a machine nobody sat at yet."""
    from neutrino_agent.modules.remote_desktop.rdp import rustdesk

    host = linux_host
    _shared(host)
    _rustdesk_wrote(host, SEALED_SEAT_PASS, has_key_pair=False)

    host.repair_settings()

    assert _steps(host.applier) == ["stop", "start"]
    assert rustdesk.has_identity(str(_root_file(host, "RustDesk.toml")))
    assert _stored_password(host) == "seat-pass"


def test_options_in_rustdesks_own_order_are_not_repaired(linux_host):
    host = linux_host
    _shared(host)
    _options_rustdesk_wrote(host, OPTIONS_IN_ITS_ORDER)

    host.repair_settings()

    assert _steps(host.applier) == []


def test_a_settings_file_being_written_is_read_again_at_the_next_report(linux_host):
    """RustDesk truncates a file before it writes it."""
    host = linux_host
    _shared(host)

    _options_rustdesk_wrote(host, "")
    host.repair_settings()
    assert _steps(host.applier) == []

    _options_rustdesk_wrote(host, OPTIONS_IN_ITS_ORDER)
    _root_file(host, "RustDesk.toml").write_text("")
    host.repair_settings()
    assert _steps(host.applier) == []


def test_a_missing_settings_file_is_written_again(linux_host):
    host = linux_host
    _shared(host)
    _root_file(host, "RustDesk2.toml").unlink()

    host.repair_settings()

    assert _steps(host.applier) == ["stop", "start"]
    assert _root_file(host, "RustDesk2.toml").exists()


def test_the_agent_at_start_writes_lost_settings_before_any_host_starts(linux_host):
    """An upgrade over a machine in that state: the new program must not start
    from options a session wiped."""
    host = linux_host
    _shared(host)
    _options_rustdesk_wrote(host, EMPTY_OPTIONS)
    seen = []
    start = host.applier.start

    def seen_at_start(uid):
        seen.append(_root_file(host, "RustDesk2.toml").read_text())
        start(uid)

    host.applier.start = seen_at_start

    host.settle_at_start()

    assert _steps(host.applier) == ["stop", "start"]
    assert "custom-rendezvous-server = '127.0.0.1'" in seen[0]
