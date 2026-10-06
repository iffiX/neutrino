"""Sharing this machine's desktop as the hub's switch orders.

The switch on takes RustDesk over in a fixed order and writes the settings
with nothing running; off, it gives back what was there, settings files
included. A share is declared only while the agent's copy listens, read
from the socket table, and the seat password enters no report. The
system's registration is a fake applier here; each system's own is pinned
in its own file.
"""

import os
import socket

import pytest

from neutrino_agent.core.store import MachineStateStore
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.rdp.host import RdpShareHost

COPY = "/opt/agent/rustdesk/rustdesk"


class FakeSeat:
    """A seat saying exactly what a test wants it to."""

    def __init__(self):
        self.seated = ["pat"]
        self.connected = 0
        self.attention = ""
        self.attention_homes = []
        self.asked = []

    def ask_for_permissions(self, account):
        self.asked.append(account)

    def graphical_accounts(self):
        return self.seated

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
