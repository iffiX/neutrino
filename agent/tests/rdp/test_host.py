"""Sharing this machine's desktop: what it refuses, and what it never says.

Sharing takes the rustdesk module and a seat that agrees, the access
password enters the declaration nowhere, and a share is declared only once
the direct port answers.
"""

import os

import pytest

from neutrino_agent.core.store import MachineStateStore
from neutrino_agent.modules import rustdesk
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.rdp import host as host_module
from neutrino_agent.rdp.host import RdpShareHost

INSTALLED = {"rustdesk": {"state": "installed"}}
ABSENT = {"rustdesk": {"state": "absent"}}


class _Platform(AgentPlatform):
    def account_home(self, account):
        return f"/home/{account}"

    def human_accounts(self):
        return ["pat", "sam"]


@pytest.fixture()
def share_host(tmp_path, monkeypatch):
    """A host whose writes, service control and probe are all replaced."""
    store = MachineStateStore(path=str(tmp_path / "state.json"))
    made = RdpShareHost(
        platform=_Platform(),
        store=store,
        credentials_dir=str(tmp_path / "credentials"),
        log=lambda message: None,
    )
    made.bind_modules(lambda: dict(INSTALLED))

    made.written = {}
    made.services = []
    made.passwords = []
    monkeypatch.setattr(
        rustdesk,
        "write_config",
        lambda path, options: made.written.__setitem__(path, dict(options)),
    )
    monkeypatch.setattr(rustdesk, "control_service", made.services.append)
    monkeypatch.setattr(rustdesk, "set_password", made.passwords.append)
    monkeypatch.setattr(rustdesk, "read_id", lambda: "123456789")
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "/usr/bin/rustdesk")
    monkeypatch.setattr(RdpShareHost, "_answers", lambda self: True)
    monkeypatch.setattr(host_module, "has_desktop_session", lambda: True)
    # The machine cannot say who is at the screen, so the account named only
    # has to exist; the seat tests below answer with a real seat instead.
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: None)
    return made


# --- what must be there before anything is written ---


def test_sharing_without_the_module_is_refused_before_anything_is_written(share_host):
    share_host.bind_modules(lambda: dict(ABSENT))

    refusal = share_host.share("pat")

    assert refusal == {"code": "module_missing", "params": {"module": "rustdesk"}}
    assert share_host.written == {}
    assert share_host.services == []


def test_sharing_without_an_account_is_refused(share_host):
    refusal = share_host.share("")

    assert refusal == {"code": "rdp_no_seat", "params": {}}
    assert share_host.written == {}


def test_a_machine_with_no_desktop_is_refused_before_rustdesk_is_touched(
    share_host, monkeypatch
):
    """RustDesk on a machine with no graphical session refuses the connection
    its own configuration goes over, and the raw errno says nothing a person
    can act on."""
    monkeypatch.setattr(host_module, "has_desktop_session", lambda: False)

    refusal = share_host.share("pat")

    assert refusal == {"code": "rdp_no_desktop", "params": {}}
    assert share_host.written == {}
    assert share_host.services == []
    assert share_host.passwords == []


# --- what counts as a desktop to share ---


def _loginctl_answering(monkeypatch, listed: str, types: str):
    """A loginctl that lists those sessions and reports those types."""

    def loginctl(arguments):
        return listed if arguments[0] == "list-sessions" else types

    monkeypatch.setattr(host_module, "_loginctl", loginctl)


def test_a_graphical_session_is_a_desktop(monkeypatch):
    monkeypatch.setattr(host_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "3 1000 pat seat0\n", "Type=wayland\n")

    assert host_module.has_desktop_session() is True


def test_only_tty_sessions_are_no_desktop(monkeypatch):
    """The headless box: it has sessions, all of them terminals."""
    monkeypatch.setattr(host_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "5 0 root\n7 1000 pat\n", "Type=tty\n\nType=tty\n")

    assert host_module.has_desktop_session() is False


def test_no_sessions_at_all_is_no_desktop(monkeypatch):
    monkeypatch.setattr(host_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "\n", "")

    assert host_module.has_desktop_session() is False


def test_a_machine_that_cannot_be_asked_is_not_refused(monkeypatch):
    """A machine without loginctl is one this cannot tell about, and a guess
    that refuses is worse than the raw refusal it replaced."""
    monkeypatch.setattr(host_module.os, "environ", {})
    monkeypatch.setattr(host_module, "_loginctl", lambda arguments: None)

    assert host_module.has_desktop_session() is True


def test_a_session_this_process_can_see_is_a_desktop(monkeypatch):
    monkeypatch.setattr(host_module.os, "environ", {"DISPLAY": ":0"})

    assert host_module.has_desktop_session() is True


def test_the_loginctl_probe_asks_for_the_session_types(monkeypatch):
    asked = []

    def run(command, **kwargs):
        asked.append(command)

        class _Result:
            returncode = 0
            stdout = "3 1000 pat seat0\n"

        return _Result()

    monkeypatch.setattr(host_module.subprocess, "run", run)

    assert host_module._loginctl(["list-sessions", "--no-legend"]) == (
        "3 1000 pat seat0\n"
    )
    assert asked == [["loginctl", "list-sessions", "--no-legend"]]


def test_a_loginctl_that_exits_nonzero_answers_nothing(monkeypatch):
    def run(command, **kwargs):
        class _Result:
            returncode = 1
            stdout = "everything is fine"

        return _Result()

    monkeypatch.setattr(host_module.subprocess, "run", run)

    assert host_module._loginctl(["list-sessions"]) is None


# --- what sharing actually does ---


def test_sharing_writes_the_direct_configuration_everywhere_it_is_read(share_host):
    assert share_host.share("pat") == {}

    assert set(share_host.written) == {
        "/root/.config/rustdesk/RustDesk2.toml",
        "/home/pat/.config/rustdesk/RustDesk2.toml",
    }
    for options in share_host.written.values():
        assert options["direct-server"] == "Y"
        assert options["custom-rendezvous-server"] == ""
        assert options["direct-access-port"] == "21118"


def test_the_service_is_stopped_around_the_write_and_started_after(share_host):
    share_host.share("pat")

    # A write underneath a running service is one it overwrites as it exits.
    assert share_host.services == ["stop", "start"]


def test_the_seat_password_is_the_hubs_and_is_set_into_rustdesk(share_host, tmp_path):
    """It arrives in the desired state, not from anybody at this machine."""
    assert share_host.apply_seat_password("hunter2") == {}

    assert share_host.passwords == ["hunter2"]
    kept = tmp_path / "credentials" / "rdp_access_password"
    assert kept.read_text() == "hunter2"
    assert oct(kept.stat().st_mode & 0o777) == "0o600"
    assert oct(kept.parent.stat().st_mode & 0o777) == "0o700"


def test_the_seat_password_is_set_only_when_it_changed(share_host):
    share_host.apply_seat_password("hunter2")
    share_host.apply_seat_password("hunter2")

    assert share_host.passwords == ["hunter2"]

    share_host.apply_seat_password("correcthorse")

    assert share_host.passwords == ["hunter2", "correcthorse"]


def test_a_state_carrying_no_seat_password_sets_nothing(share_host):
    assert share_host.apply_seat_password("") == {}

    assert share_host.passwords == []


def test_a_password_rustdesk_refuses_is_typed_and_not_recorded(
    share_host, tmp_path, monkeypatch
):
    """A password recorded as set while RustDesk refused it would never be
    tried again."""

    def refuse(password):
        raise InstallError("rustdesk refused the password")

    monkeypatch.setattr(rustdesk, "set_password", refuse)

    refusal = share_host.apply_seat_password("hunter2")

    assert refusal["code"] == "rdp_password_refused"
    assert not (tmp_path / "credentials" / "rdp_access_password").exists()


def test_a_share_answers_with_the_seat_password_the_hub_set(share_host):
    share_host.apply_seat_password("hunter2")
    share_host.passwords.clear()

    share_host.share("pat")

    assert share_host.passwords == ["hunter2"]


def test_the_seat_password_never_enters_the_store(share_host, tmp_path):
    share_host.apply_seat_password("hunter2")
    share_host.share("pat")

    assert "hunter2" not in (tmp_path / "state.json").read_text()


def test_the_declaration_carries_no_password_at_all(share_host):
    share_host.share("pat")

    declaration = share_host.declaration()

    assert set(declaration) == {
        "is_shared",
        "account",
        "share_id",
        "port",
        "attention",
        "connected_count",
    }
    assert declaration["account"] == "pat"
    assert "hunter2" not in repr(declaration)


def test_the_state_carries_no_password_at_all(share_host):
    share_host.apply_seat_password("hunter2")
    share_host.share("pat")

    state = share_host.state()

    assert state["has_password"] is True
    assert "hunter2" not in repr(state)


def test_a_shared_machine_declares_itself_with_its_own_share_id(share_host):
    share_host.share("pat")

    declaration = share_host.declaration()

    assert declaration["is_shared"] is True
    assert declaration["port"] == 21118
    assert declaration["share_id"] != ""


def test_sharing_again_keeps_the_share_id_the_fleet_already_knows(share_host):
    share_host.share("pat")
    first = share_host.declaration()["share_id"]

    share_host.share("pat")

    assert share_host.declaration()["share_id"] == first


def test_a_configure_that_fails_is_typed_and_declares_nothing(share_host, monkeypatch):
    def explode(path, options):
        raise InstallError("read-only file system")

    monkeypatch.setattr(rustdesk, "write_config", explode)

    refusal = share_host.share("pat")

    assert refusal["code"] == "rdp_configure_failed"
    assert share_host.declaration()["is_shared"] is False


# --- a share is only declared once it answers ---


def test_a_configured_share_that_does_not_answer_is_starting_not_shared(
    share_host, monkeypatch
):
    share_host.share("pat")
    monkeypatch.setattr(RdpShareHost, "_answers", lambda self: False)

    assert share_host.state()["state"] == "starting"
    # And the fleet is not offered a desktop that cannot be reached.
    assert share_host.declaration()["is_shared"] is False


def test_an_answering_share_reads_as_shared(share_host):
    share_host.share("pat")

    assert share_host.state()["state"] == "sharing"
    assert share_host.declaration()["is_shared"] is True


def test_a_machine_that_never_shared_reads_not_shared(share_host):
    assert share_host.state()["state"] == "not_shared"
    assert share_host.declaration()["is_shared"] is False


def test_the_state_carries_the_id_a_peer_connects_by(share_host):
    share_host.share("pat")

    assert share_host.state()["rustdesk_id"] == "123456789"


# --- unshare reverses it ---


def test_unsharing_closes_the_direct_server_and_stops_declaring(share_host):
    share_host.share("pat")
    share_host.written.clear()
    share_host.services.clear()

    assert share_host.unshare() == {}

    # Every file sharing opened is closed, not only the service's own.
    assert set(share_host.written) == {
        "/root/.config/rustdesk/RustDesk2.toml",
        "/home/pat/.config/rustdesk/RustDesk2.toml",
    }
    for options in share_host.written.values():
        assert options["direct-server"] == "N"
    # Stopped and left stopped: nothing answers on the direct port after.
    assert share_host.services == ["stop"]
    assert share_host.declaration()["is_shared"] is False
    assert share_host.state()["state"] == "not_shared"


def test_unsharing_keeps_the_seat_password_the_hub_holds(share_host, tmp_path):
    """The password is the machine's, not the share's: the hub sets it and a
    later share answers with the same one."""
    share_host.apply_seat_password("hunter2")
    share_host.share("pat")

    share_host.unshare()

    assert (tmp_path / "credentials" / "rdp_access_password").read_text() == "hunter2"
    assert share_host.state()["has_password"] is True


def test_an_unshare_that_cannot_be_written_is_typed(share_host, monkeypatch):
    share_host.share("pat")

    def explode(path, options):
        raise InstallError("read-only file system")

    monkeypatch.setattr(rustdesk, "write_config", explode)

    assert share_host.unshare()["code"] == "rdp_configure_failed"


# --- whose desktop a share means: the seat decides ---


def test_a_share_names_an_account_and_the_seat_must_agree(share_host, monkeypatch):
    """RustDesk spawns its screen server into the signed-in session whoever
    asked, so naming anyone else would promise a desktop the peer will not
    be shown."""
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: ["sam"])

    refusal = share_host.share("pat")

    assert refusal == {"code": "rdp_wrong_seat", "params": {"account": "pat"}}
    assert share_host.written == {}


def test_a_share_naming_the_seated_account_goes_through_as_them(
    share_host, monkeypatch
):
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: ["sam"])

    outcome = share_host.share("sam")

    assert outcome == {}
    assert "/home/sam/.config/rustdesk/RustDesk2.toml" in share_host.written
    assert share_host.state()["account"] == "sam"


def test_where_the_seat_cannot_be_read_the_account_only_has_to_exist(share_host):
    refusal = share_host.share("nobody")

    assert refusal == {"code": "no_target_user", "params": {}}
    assert share_host.written == {}


def test_the_seat_owners_are_read_with_their_sessions(monkeypatch):
    """Two sessions, one graphical: the owner of the graphical one is the
    answer, matched to its own type and not the tty's."""
    _loginctl_answering(
        monkeypatch,
        "1 1000 sam seat0 tty1\n3 1001 pat seat0 tty2\n",
        "Type=tty\nType=x11\n",
    )

    assert host_module.graphical_accounts() == ["pat"]


def test_a_machine_without_loginctl_cannot_say_who_is_seated(monkeypatch):
    monkeypatch.setattr(host_module, "_loginctl", lambda arguments: None)

    assert host_module.graphical_accounts() is None


def test_naming_another_account_closes_the_share_the_last_one_had(
    share_host, monkeypatch
):
    """One machine shares one seat: the copy the previous account was shared
    through is closed before the new one is written."""
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: ["pat", "sam"])
    share_host.share("pat")
    share_host.written.clear()

    assert share_host.share("sam") == {}

    assert (
        share_host.written["/home/pat/.config/rustdesk/RustDesk2.toml"]["direct-server"]
        == "N"
    )
    assert (
        share_host.written["/home/sam/.config/rustdesk/RustDesk2.toml"]["direct-server"]
        == "Y"
    )
    assert share_host.state()["account"] == "sam"


def test_sharing_the_same_account_again_closes_nothing(share_host):
    share_host.share("pat")
    share_host.written.clear()

    share_host.share("pat")

    for options in share_host.written.values():
        assert options["direct-server"] == "Y"


# --- how many peers are on it ---


def _proc_tcp(tmp_path, monkeypatch, rows: str, rows6: str = ""):
    """A connection table saying exactly what a test wants it to."""
    table = tmp_path / "tcp"
    table.write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when"
        " retrnsmt   uid  timeout inode\n" + rows
    )
    table6 = tmp_path / "tcp6"
    table6.write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when"
        " retrnsmt   uid  timeout inode\n" + rows6
    )
    monkeypatch.setattr(host_module, "RDP_PROC_TCP_PATHS", (str(table), str(table6)))


def test_the_peers_on_the_direct_port_are_counted_off_the_kernels_own_table(
    tmp_path, monkeypatch
):
    # 527E is 21118; 01 is established, 0A is a listening socket.
    _proc_tcp(
        tmp_path,
        monkeypatch,
        "   0: 0100007F:527E 00000000:0000 0A 00000000:00000000 00:00000000 0\n"
        "   1: C0A80102:527E C0A80105:E1F4 01 00000000:00000000 00:00000000 0\n"
        "   2: C0A80102:527E C0A80106:E1F5 01 00000000:00000000 00:00000000 0\n"
        "   3: C0A80102:0016 C0A80107:E1F6 01 00000000:00000000 00:00000000 0\n",
        "   0: 00000000000000000000000000000000:527E "
        "00000000000000000000000000000001:E1F7 01 00000000:00000000 00:00000000 0\n",
    )

    assert host_module.connected_count(21118) == 3
    assert host_module.connected_count(22) == 1


def test_a_machine_whose_table_cannot_be_read_counts_nobody(monkeypatch):
    monkeypatch.setattr(host_module, "RDP_PROC_TCP_PATHS", ("/nowhere/tcp",))

    assert host_module.connected_count(21118) == 0


def test_the_declaration_says_how_many_peers_are_connected(
    share_host, tmp_path, monkeypatch
):
    _proc_tcp(
        tmp_path,
        monkeypatch,
        "   0: C0A80102:527E C0A80105:E1F4 01 00000000:00000000 00:00000000 0\n",
    )
    share_host.share("pat")

    assert share_host.declaration()["connected_count"] == 1


def test_a_machine_that_shares_nothing_counts_nobody(share_host, tmp_path, monkeypatch):
    _proc_tcp(
        tmp_path,
        monkeypatch,
        "   0: C0A80102:527E C0A80105:E1F4 01 00000000:00000000 00:00000000 0\n",
    )

    assert share_host.declaration()["connected_count"] == 0


# --- the baseline every machine gets, shared or not ---


def test_the_baseline_names_no_rendezvous_and_opens_nothing(share_host):
    """A machine carrying RustDesk must not register with public
    infrastructure before anybody asked it to share."""
    share_host.apply_baseline()

    assert set(share_host.written) == {"/root/.config/rustdesk/RustDesk2.toml"}
    options = share_host.written["/root/.config/rustdesk/RustDesk2.toml"]
    assert options["custom-rendezvous-server"] == ""
    assert options["relay-server"] == ""
    assert "direct-server" not in options


def test_a_baseline_that_changed_the_file_restarts_the_service(share_host, monkeypatch):
    """A running service read its configuration once."""
    monkeypatch.setattr(rustdesk, "write_config", lambda path, options: True)

    share_host.apply_baseline()

    assert share_host.services == ["restart"]


def test_a_baseline_that_changed_nothing_restarts_nothing(share_host):
    share_host.apply_baseline()

    assert share_host.services == []


def test_a_baseline_the_machine_cannot_take_is_logged_and_not_raised(
    share_host, monkeypatch
):
    logged = []
    share_host._log = logged.append

    def refuse(path, options):
        raise InstallError("read-only file system")

    monkeypatch.setattr(rustdesk, "write_config", refuse)

    share_host.apply_baseline()

    assert logged == ["rdp: read-only file system"]


# --- the seat session's own display environment ---


class _FakePwd:
    class _Entry:
        pw_uid = 1000
        pw_dir = "/home/sam"

    @staticmethod
    def getpwnam(name):
        if name != "sam":
            raise KeyError(name)
        return _FakePwd._Entry()


def _fake_proc(tmp_path, monkeypatch, *, uid=1000, environ=b""):
    """One process of the seat user in a stand-in proc tree."""
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242" / "environ").write_bytes(environ)
    monkeypatch.setattr(host_module, "RDP_PROC_DIR", str(proc))
    real_stat = os.stat
    monkeypatch.setattr(
        host_module.os,
        "stat",
        lambda path, **kw: (
            type("S", (), {"st_uid": uid})()
            if str(path).endswith("4242")
            else real_stat(path, **kw)
        ),
    )
    monkeypatch.setattr(host_module, "pwd", _FakePwd)


def test_the_session_environment_is_read_off_the_seats_own_processes(
    tmp_path, monkeypatch
):
    _fake_proc(
        tmp_path,
        monkeypatch,
        environ=b"DISPLAY=:0\0WAYLAND_DISPLAY=wayland-0\0"
        b"XAUTHORITY=/run/user/1000/.mutter\0XDG_RUNTIME_DIR=/run/user/1000\0"
        b"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus\0HOME=/home/sam\0",
    )

    assert host_module.session_environment("sam") == {
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
        "XAUTHORITY": "/run/user/1000/.mutter",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    }


def test_a_process_without_a_display_is_no_environment_source(tmp_path, monkeypatch):
    _fake_proc(tmp_path, monkeypatch, environ=b"HOME=/home/sam\0TERM=xterm\0")

    assert host_module.session_environment("sam") is None


def test_an_account_the_machine_does_not_have_has_no_session(monkeypatch):
    monkeypatch.setattr(host_module, "pwd", _FakePwd)

    assert host_module.session_environment("nobody") is None


# --- what a peer would wait on, said before it dials ---


def test_a_wayland_seat_without_the_permission_says_so(share_host, monkeypatch):
    """RustDesk hands the screen out through a dialog on this machine's own
    screen. A peer that dials before somebody answers it waits in
    "connecting" forever, so the fleet is told first."""
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: ["pat"])
    monkeypatch.setattr(RdpShareHost, "_is_wayland_seat", staticmethod(lambda: True))
    monkeypatch.setattr(
        RdpShareHost, "_has_wayland_permission", staticmethod(lambda home: False)
    )

    assert share_host.attention("pat") == "rdp_screen_not_allowed"


def test_a_seat_that_already_granted_it_says_nothing(share_host, monkeypatch):
    """Once per person, not once per connection: RustDesk keeps the answer."""
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: ["pat"])
    monkeypatch.setattr(RdpShareHost, "_is_wayland_seat", staticmethod(lambda: True))
    monkeypatch.setattr(
        RdpShareHost, "_has_wayland_permission", staticmethod(lambda home: True)
    )

    assert share_host.attention("pat") == ""


def test_an_x11_seat_needs_no_permission(share_host, monkeypatch):
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: ["pat"])
    monkeypatch.setattr(RdpShareHost, "_is_wayland_seat", staticmethod(lambda: False))

    assert share_host.attention("pat") == ""


def test_nobody_at_the_screen_is_its_own_answer(share_host, monkeypatch):
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: [])

    assert share_host.attention("pat") == "rdp_nobody_seated"


def test_a_greeters_session_holds_no_permission_it_could_keep(share_host, monkeypatch):
    """Its home is a tmpfs, so the answer could never be remembered there."""
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: ["gdm-greeter"])

    assert share_host.attention("gdm-greeter") == "rdp_nobody_seated"


def test_the_declaration_carries_what_a_peer_would_wait_on(share_host, monkeypatch):
    share_host.share("pat")
    # Asked after the share, because only a sharing machine pays for it.
    monkeypatch.setattr(host_module, "graphical_accounts", lambda: [])

    assert share_host.declaration()["attention"] == "rdp_nobody_seated"


def test_a_machine_that_shares_nothing_asks_the_seat_nothing(share_host, monkeypatch):
    """The heartbeat runs this every few seconds on every machine; a machine
    with no share has nothing for a peer to wait on and reads no session
    table to say so."""

    def refuse():
        raise AssertionError("a machine that shares nothing must not ask")

    monkeypatch.setattr(host_module, "graphical_accounts", refuse)

    assert share_host.declaration()["attention"] == ""
