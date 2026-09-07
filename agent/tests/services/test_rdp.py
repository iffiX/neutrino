"""The rdp service: sharing this desktop, and reaching one that is shared.

The flow's whole point is what it refuses and what it never says. Sharing
takes the privileged scope and the rustdesk module, the access password
enters the declaration nowhere, a share is declared only once the direct
port answers, and macOS says it is waiting for a person rather than
claiming a desktop nobody can see yet.
"""

import os

import pytest

from neutrino_agent.modules import rustdesk
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.services import rdp as rdp_module
from neutrino_agent.services.rdp import RdpServiceHandler, connect_peer
from neutrino_agent.services.store import MachineServiceStore

INSTALLED = {"rustdesk": {"state": "installed"}}
ABSENT = {"rustdesk": {"state": "absent"}}

ENTRY = {
    "id": "rdp_s9",
    "type": "rdp",
    "title": "studio",
    "payload": {"protocol": "rustdesk", "host": "192.168.100.6", "port": 21118},
    "is_healthy": True,
    "modules": ["rustdesk"],
}


class _Platform(AgentPlatform):
    def account_home(self, account):
        return f"/home/{account}"


@pytest.fixture()
def handler(tmp_path, monkeypatch):
    """A handler whose writes, service control and probe are all replaced."""
    store = MachineServiceStore(path=str(tmp_path / "services.json"))
    made = RdpServiceHandler(
        platform=_Platform(),
        store=store,
        credentials_dir=str(tmp_path / "credentials"),
        accounts=lambda: ["pat", "sam"],
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
    monkeypatch.setattr(RdpServiceHandler, "_answers", lambda self: True)
    monkeypatch.setattr(rdp_module, "has_desktop_session", lambda: True)
    # The machine cannot say who is at the screen, so the account named on
    # the body — or the caller — only has to exist; the seat tests below
    # answer with a real seat instead.
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: None)
    return made


def share(handler, password="hunter2", account="pat", is_privileged=True):
    return handler.act(
        entries=[],
        account=account,
        is_privileged=is_privileged,
        body={"action": "share", "password": password},
    )


# --- who may share, and what must be there first ---


def test_an_ordinary_account_shares_its_own_seat(handler):
    """One share per machine, and a person owns their own: sharing yourself
    takes no privilege, the root daemon does the mechanics either way."""
    outcome = share(handler, is_privileged=False)

    assert outcome == {}
    assert handler.state()["rdp"]["account"] == "pat"


def test_an_ordinary_account_may_not_share_someone_else(handler):
    refusal = handler.act(
        entries=[],
        account="pat",
        is_privileged=False,
        body={"action": "share", "password": "hunter2", "account": "sam"},
    )

    assert refusal == {"code": "control_scope_refused", "params": {}}
    assert handler.written == {}


def test_an_ordinary_account_may_not_replace_anothers_share(handler):
    share(handler, account="sam")

    refusal = handler.act(
        entries=[],
        account="pat",
        is_privileged=False,
        body={"action": "share", "password": "hunter2"},
    )

    assert refusal == {"code": "control_scope_refused", "params": {}}
    assert handler.state()["rdp"]["account"] == "sam"


def test_the_privileged_scope_replaces_anyones_share(handler):
    share(handler, account="sam")

    outcome = handler.act(
        entries=[],
        account="root",
        is_privileged=True,
        body={"action": "share", "password": "hunter2", "account": "pat"},
    )

    assert outcome == {}
    assert handler.state()["rdp"]["account"] == "pat"


def test_sharing_without_the_module_is_refused_before_anything_is_written(handler):
    handler.bind_modules(lambda: dict(ABSENT))

    refusal = share(handler)

    assert refusal == {"code": "module_missing", "params": {"module": "rustdesk"}}
    assert handler.written == {}
    assert handler.services == []


def test_sharing_without_a_password_is_refused(handler):
    refusal = share(handler, password="")

    assert refusal == {"code": "rdp_password_missing", "params": {}}
    assert handler.written == {}


def test_a_machine_with_no_desktop_is_refused_before_rustdesk_is_touched(
    handler, monkeypatch
):
    """RustDesk on a machine with no graphical session refuses the connection
    its own configuration goes over, and the raw errno says nothing a person
    can act on."""
    monkeypatch.setattr(rdp_module, "has_desktop_session", lambda: False)

    refusal = share(handler)

    assert refusal == {"code": "rdp_no_desktop", "params": {}}
    assert handler.written == {}
    assert handler.services == []
    assert handler.passwords == []


# --- what counts as a desktop to share ---


def _loginctl_answering(monkeypatch, listed: str, types: str):
    """A loginctl that lists those sessions and reports those types."""

    def loginctl(arguments):
        return listed if arguments[0] == "list-sessions" else types

    monkeypatch.setattr(rdp_module, "_loginctl", loginctl)


def test_a_graphical_session_is_a_desktop(monkeypatch):
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "3 1000 pat seat0\n", "Type=wayland\n")

    assert rdp_module.has_desktop_session() is True


def test_only_tty_sessions_are_no_desktop(monkeypatch):
    """The headless box: it has sessions, all of them terminals."""
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "5 0 root\n7 1000 pat\n", "Type=tty\n\nType=tty\n")

    assert rdp_module.has_desktop_session() is False


def test_no_sessions_at_all_is_no_desktop(monkeypatch):
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "\n", "")

    assert rdp_module.has_desktop_session() is False


def test_a_machine_that_cannot_be_asked_is_not_refused(monkeypatch):
    """A machine without loginctl is one this cannot tell about, and a guess
    that refuses is worse than the raw refusal it replaced."""
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module.os, "environ", {})
    monkeypatch.setattr(rdp_module, "_loginctl", lambda arguments: None)

    assert rdp_module.has_desktop_session() is True


def test_a_session_this_process_can_see_is_a_desktop(monkeypatch):
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module.os, "environ", {"DISPLAY": ":0"})

    assert rdp_module.has_desktop_session() is True


def test_windows_and_macos_are_never_refused_for_this(monkeypatch):
    monkeypatch.setattr(rdp_module.os, "name", "nt")

    assert rdp_module.has_desktop_session() is True

    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: True)

    assert rdp_module.has_desktop_session() is True


def test_the_loginctl_probe_asks_for_the_session_types(monkeypatch):
    asked = []

    def run(command, **kwargs):
        asked.append(command)

        class _Result:
            returncode = 0
            stdout = "3 1000 pat seat0\n"

        return _Result()

    monkeypatch.setattr(rdp_module.subprocess, "run", run)

    assert rdp_module._loginctl(["list-sessions", "--no-legend"]) == (
        "3 1000 pat seat0\n"
    )
    assert asked == [["loginctl", "list-sessions", "--no-legend"]]


def test_a_loginctl_that_exits_nonzero_answers_nothing(monkeypatch):
    def run(command, **kwargs):
        class _Result:
            returncode = 1
            stdout = "everything is fine"

        return _Result()

    monkeypatch.setattr(rdp_module.subprocess, "run", run)

    assert rdp_module._loginctl(["list-sessions"]) is None


# --- what sharing actually does ---


def test_sharing_writes_the_direct_configuration_everywhere_it_is_read(handler):
    assert share(handler) == {}

    assert set(handler.written) == {
        "/root/.config/rustdesk/RustDesk2.toml",
        "/home/pat/.config/rustdesk/RustDesk2.toml",
    }
    for options in handler.written.values():
        assert options["direct-server"] == "Y"
        assert options["custom-rendezvous-server"] == ""
        assert options["direct-access-port"] == "21118"


def test_the_service_is_stopped_around_the_write_and_started_after(handler):
    share(handler)

    # A write underneath a running service is one it overwrites as it exits.
    assert handler.services == ["stop", "start"]


def test_the_password_is_set_into_rustdesk_and_kept_only_for_root(handler, tmp_path):
    share(handler, password="hunter2")

    assert handler.passwords == ["hunter2"]
    kept = tmp_path / "credentials" / "rdp_access_password"
    assert kept.read_text() == "hunter2"
    assert oct(kept.stat().st_mode & 0o777) == "0o600"


def test_the_password_never_enters_the_service_store(handler, tmp_path):
    share(handler, password="hunter2")

    assert "hunter2" not in (tmp_path / "services.json").read_text()


def test_the_declaration_carries_no_password_at_all(handler):
    share(handler, password="hunter2")

    declaration = handler.declaration()

    assert set(declaration) == {"is_shared", "share_id", "port", "attention"}
    assert "hunter2" not in repr(declaration)


def test_a_shared_machine_declares_itself_with_its_own_share_id(handler):
    share(handler)

    declaration = handler.declaration()

    assert declaration["is_shared"] is True
    assert declaration["port"] == 21118
    assert declaration["share_id"] != ""


def test_sharing_again_keeps_the_share_id_the_fleet_already_knows(handler):
    share(handler)
    first = handler.declaration()["share_id"]

    share(handler, password="other")

    assert handler.declaration()["share_id"] == first


def test_a_configure_that_fails_is_typed_and_declares_nothing(handler, monkeypatch):
    def explode(path, options):
        raise InstallError("read-only file system")

    monkeypatch.setattr(rustdesk, "write_config", explode)

    refusal = share(handler)

    assert refusal["code"] == "rdp_configure_failed"
    assert handler.declaration()["is_shared"] is False


# --- a share is only declared once it answers ---


def test_a_configured_share_that_does_not_answer_is_starting_not_shared(
    handler, monkeypatch
):
    share(handler)
    monkeypatch.setattr(RdpServiceHandler, "_answers", lambda self: False)
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)

    assert handler.state()["rdp"]["state"] == "starting"
    # And the fleet is not offered a desktop that cannot be reached.
    assert handler.declaration()["is_shared"] is False


def test_macos_says_it_is_waiting_for_a_person_rather_than_starting(
    handler, monkeypatch
):
    share(handler)
    monkeypatch.setattr(RdpServiceHandler, "_answers", lambda self: False)
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: True)

    # Screen recording there is one allowance in System Settings, and no
    # amount of configuration stands in for it.
    assert handler.state()["rdp"]["state"] == "waiting_for_approval"
    assert handler.declaration()["is_shared"] is False


def test_an_answering_share_reads_as_shared(handler):
    share(handler)

    assert handler.state()["rdp"]["state"] == "sharing"
    assert handler.declaration()["is_shared"] is True


def test_a_machine_that_never_shared_reads_not_shared(handler):
    assert handler.state()["rdp"]["state"] == "not_shared"
    assert handler.declaration()["is_shared"] is False


def test_the_state_carries_the_id_a_peer_connects_by(handler):
    share(handler)

    assert handler.state()["rdp"]["rustdesk_id"] == "123456789"


# --- unshare reverses it ---


def test_unsharing_closes_the_direct_server_and_stops_declaring(handler):
    share(handler)
    handler.written.clear()
    handler.services.clear()

    assert (
        handler.act(
            entries=[], account="pat", is_privileged=True, body={"action": "unshare"}
        )
        == {}
    )

    # Every file sharing opened is closed, not only the service's own.
    assert set(handler.written) == {
        "/root/.config/rustdesk/RustDesk2.toml",
        "/home/pat/.config/rustdesk/RustDesk2.toml",
    }
    for options in handler.written.values():
        assert options["direct-server"] == "N"
    # Stopped and left stopped: nothing answers on the direct port after.
    assert handler.services == ["stop"]
    assert handler.declaration()["is_shared"] is False
    assert handler.state()["rdp"]["state"] == "not_shared"


def test_unsharing_forgets_the_access_password(handler, tmp_path):
    share(handler, password="hunter2")

    handler.act(
        entries=[], account="pat", is_privileged=True, body={"action": "unshare"}
    )

    assert not (tmp_path / "credentials" / "rdp_access_password").exists()
    assert handler.reveal_password(account="", is_privileged=True) == ""


def test_the_shares_own_account_stops_it_and_nobody_else_ordinary_does(handler):
    share(handler, account="pat")

    refusal = handler.act(
        entries=[], account="sam", is_privileged=False, body={"action": "unshare"}
    )
    assert refusal == {"code": "control_scope_refused", "params": {}}

    outcome = handler.act(
        entries=[], account="pat", is_privileged=False, body={"action": "unshare"}
    )
    assert outcome == {}
    assert handler.state()["rdp"]["is_shared"] is False


# --- the password is read back only by the scope that set it ---


def test_the_password_reads_back_to_root_and_the_shares_own_account(handler):
    share(handler, password="hunter2", account="pat")

    assert handler.reveal_password(account="", is_privileged=True) == "hunter2"
    assert handler.reveal_password(account="pat", is_privileged=False) == "hunter2"
    assert handler.reveal_password(account="sam", is_privileged=False) == ""


# --- connecting to somebody else's desktop ---


def test_connect_launches_the_local_client_at_the_published_address(
    handler, monkeypatch
):
    monkeypatch.setattr(rdp_module.os, "environ", {"DISPLAY": ":0"})
    launched = []
    monkeypatch.setattr(
        rdp_module.subprocess,
        "Popen",
        lambda command, **kwargs: launched.append(command),
    )

    outcome = handler.act(
        entries=[ENTRY],
        account="pat",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_s9"},
    )

    assert outcome == {}
    assert launched == [["/usr/bin/rustdesk", "--connect", "192.168.100.6"]]


def test_connecting_is_open_to_an_ordinary_account(handler, monkeypatch):
    monkeypatch.setattr(rdp_module.os, "environ", {"DISPLAY": ":0"})
    monkeypatch.setattr(rdp_module.subprocess, "Popen", lambda command, **kwargs: None)

    outcome = handler.act(
        entries=[ENTRY],
        account="pat",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_s9"},
    )

    assert outcome == {}


def test_connecting_without_the_client_is_a_module_refusal(handler, monkeypatch):
    monkeypatch.setattr(rustdesk, "binary_path", lambda: "")

    refusal = handler.act(
        entries=[ENTRY],
        account="pat",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_s9"},
    )

    assert refusal == {"code": "module_missing", "params": {"module": "rustdesk"}}


def test_connecting_to_an_entry_nobody_published_is_refused(handler):
    refusal = handler.act(
        entries=[ENTRY],
        account="pat",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_nothing"},
    )

    assert refusal == {"code": "unknown_request", "params": {}}


def test_a_client_that_will_not_start_is_typed(handler, monkeypatch):
    monkeypatch.setattr(rdp_module.os, "environ", {"DISPLAY": ":0"})

    def explode(command, **kwargs):
        raise OSError("no such binary")

    monkeypatch.setattr(rdp_module.subprocess, "Popen", explode)

    refusal = handler.act(
        entries=[ENTRY],
        account="pat",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_s9"},
    )

    assert refusal["code"] == "rdp_launch_failed"


# --- what the client is told to dial ---


def test_the_default_port_is_dialled_by_bare_address():
    # RustDesk resolves a bare address to its own direct port, which is the
    # one path that needs no rendezvous server at all.
    assert connect_peer("192.168.100.6", 21118) == "192.168.100.6"


def test_any_other_port_is_spelled_out():
    assert connect_peer("192.168.100.6", 25000) == "192.168.100.6:25000"


def test_no_address_is_no_peer():
    assert connect_peer("", 21118) == ""


def test_an_entry_with_no_address_is_refused_rather_than_dialled(handler, monkeypatch):
    monkeypatch.setattr(rdp_module.subprocess, "Popen", lambda command, **kwargs: None)
    entry = {**ENTRY, "payload": {"protocol": "rustdesk", "host": "", "port": 21118}}

    refusal = handler.act(
        entries=[entry],
        account="pat",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_s9"},
    )

    assert refusal == {"code": "rdp_no_address", "params": {}}


def test_an_action_the_handler_does_not_know_is_typed(handler):
    refusal = handler.act(
        entries=[], account="pat", is_privileged=True, body={"action": "reboot"}
    )

    assert refusal == {"code": "unknown_request", "params": {}}


# --- whose desktop a share means: the seat decides, the body declares ---


def test_a_share_names_an_account_and_the_seat_must_agree(handler, monkeypatch):
    """RustDesk spawns its screen server into the signed-in session whoever
    asked, so naming anyone else would promise a desktop the peer will not
    be shown."""
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["sam"])

    refusal = handler.act(
        entries=[],
        account="root",
        is_privileged=True,
        body={"action": "share", "password": "hunter2", "account": "pat"},
    )

    assert refusal == {"code": "rdp_wrong_seat", "params": {"account": "pat"}}
    assert handler.written == {}


def test_a_share_naming_the_seated_account_goes_through_as_them(handler, monkeypatch):
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["sam"])

    outcome = handler.act(
        entries=[],
        account="root",
        is_privileged=True,
        body={"action": "share", "password": "hunter2", "account": "sam"},
    )

    assert outcome == {}
    assert "/home/sam/.config/rustdesk/RustDesk2.toml" in handler.written
    assert handler.state()["rdp"]["account"] == "sam"


def test_a_share_naming_nobody_defaults_to_the_one_seated_account(handler, monkeypatch):
    """`share` from a root shell means the person at the screen; the machine
    knows who that is, so nobody has to spell it."""
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["sam"])

    outcome = handler.act(
        entries=[],
        account="root",
        is_privileged=True,
        body={"action": "share", "password": "hunter2"},
    )

    assert outcome == {}
    assert handler.state()["rdp"]["account"] == "sam"


def test_where_the_seat_cannot_be_read_the_account_only_has_to_exist(handler):
    refusal = handler.act(
        entries=[],
        account="root",
        is_privileged=True,
        body={"action": "share", "password": "hunter2", "account": "nobody"},
    )

    assert refusal == {"code": "no_target_user", "params": {}}
    assert handler.written == {}


def test_the_state_says_who_is_at_the_screen(handler, monkeypatch):
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["sam", "pat"])

    assert handler.state()["rdp"]["desktop_accounts"] == ["sam", "pat"]


def test_the_seat_owners_are_read_with_their_sessions(monkeypatch):
    """Two sessions, one graphical: the owner of the graphical one is the
    answer, matched to its own type and not the tty's."""
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    _loginctl_answering(
        monkeypatch,
        "1 1000 sam seat0 tty1\n3 1001 pat seat0 tty2\n",
        "Type=tty\nType=x11\n",
    )

    assert rdp_module.graphical_accounts() == ["pat"]


def test_a_machine_without_loginctl_cannot_say_who_is_seated(monkeypatch):
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module, "_loginctl", lambda arguments: None)

    assert rdp_module.graphical_accounts() is None


# --- the client opens on the seat's screen, not in the daemon's void ---


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
    monkeypatch.setattr(rdp_module, "RDP_PROC_DIR", str(proc))
    real_stat = os.stat
    monkeypatch.setattr(
        rdp_module.os,
        "stat",
        lambda path, **kw: (
            type("S", (), {"st_uid": uid})()
            if str(path).endswith("4242")
            else real_stat(path, **kw)
        ),
    )
    monkeypatch.setattr(rdp_module, "pwd", _FakePwd)


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

    assert rdp_module.session_environment("sam") == {
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
        "XAUTHORITY": "/run/user/1000/.mutter",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    }


def test_a_process_without_a_display_is_no_environment_source(tmp_path, monkeypatch):
    _fake_proc(tmp_path, monkeypatch, environ=b"HOME=/home/sam\0TERM=xterm\0")

    assert rdp_module.session_environment("sam") is None


def test_the_daemon_steps_the_client_into_the_seat_session(tmp_path, monkeypatch):
    """A window spawned by a displayless root daemon is a process nobody
    sees; the seat session's own environment is what makes it a window."""
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module.os, "environ", {})
    monkeypatch.setattr(rdp_module.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(rdp_module, "pwd", _FakePwd)
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["sam"])
    monkeypatch.setattr(
        rdp_module, "session_environment", lambda account: {"DISPLAY": ":0"}
    )

    invocation, environment = rdp_module.client_invocation(
        "/usr/bin/rustdesk", "192.168.100.2"
    )

    assert invocation == [
        "runuser",
        "-u",
        "sam",
        "--",
        "/usr/bin/rustdesk",
        "--connect",
        "192.168.100.2",
    ]
    assert environment["DISPLAY"] == ":0"
    assert environment["HOME"] == "/home/sam"
    assert environment["USER"] == "sam"


def test_a_connect_with_no_seat_is_refused_not_silently_lost(handler, monkeypatch):
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module.os, "environ", {})
    monkeypatch.setattr(rdp_module.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: [])

    refusal = handler.act(
        entries=[
            {
                "id": "rdp_x",
                "type": "rdp",
                "payload": {"host": "192.168.100.2", "port": 21118},
            }
        ],
        account="sam",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_x"},
    )

    assert refusal == {"code": "rdp_no_desktop", "params": {}}


def test_a_caller_with_its_own_display_spawns_plainly(monkeypatch):
    """`nagent service rdp connect` from a desktop terminal already owns a
    display; nothing needs borrowing."""
    monkeypatch.setattr(rdp_module.os, "name", "posix")
    monkeypatch.setattr(rdp_module, "_is_darwin", lambda: False)
    monkeypatch.setattr(rdp_module.os, "environ", {"DISPLAY": ":0"})

    invocation, environment = rdp_module.client_invocation(
        "/usr/bin/rustdesk", "192.168.100.2"
    )

    assert invocation == ["/usr/bin/rustdesk", "--connect", "192.168.100.2"]
    assert environment is None


# --- what a peer would wait on, said before it dials ---


def test_a_wayland_seat_without_the_permission_says_so(handler, monkeypatch):
    """RustDesk hands the screen out through a dialog on this machine's own
    screen. A peer that dials before somebody answers it waits in
    "connecting" forever, so the fleet is told first."""
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["pat"])
    monkeypatch.setattr(RdpServiceHandler, "_is_wayland_seat", lambda self: True)
    monkeypatch.setattr(
        RdpServiceHandler, "_has_wayland_permission", staticmethod(lambda home: False)
    )

    assert handler.attention("pat") == "rdp_screen_not_allowed"


def test_a_seat_that_already_granted_it_says_nothing(handler, monkeypatch):
    """Once per person, not once per connection: RustDesk keeps the answer."""
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["pat"])
    monkeypatch.setattr(RdpServiceHandler, "_is_wayland_seat", lambda self: True)
    monkeypatch.setattr(
        RdpServiceHandler, "_has_wayland_permission", staticmethod(lambda home: True)
    )

    assert handler.attention("pat") == ""


def test_an_x11_seat_needs_no_permission(handler, monkeypatch):
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["pat"])
    monkeypatch.setattr(RdpServiceHandler, "_is_wayland_seat", lambda self: False)

    assert handler.attention("pat") == ""


def test_nobody_at_the_screen_is_its_own_answer(handler, monkeypatch):
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: [])

    assert handler.attention("pat") == "rdp_nobody_seated"


def test_a_greeters_session_holds_no_permission_it_could_keep(handler, monkeypatch):
    """Its home is a tmpfs, so the answer could never be remembered there."""
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: ["gdm-greeter"])

    assert handler.attention("gdm-greeter") == "rdp_nobody_seated"


def test_the_declaration_carries_what_a_peer_would_wait_on(handler, monkeypatch):
    share(handler)
    # Asked after the share, because only a sharing machine pays for it.
    monkeypatch.setattr(rdp_module, "graphical_accounts", lambda: [])

    assert handler.declaration()["attention"] == "rdp_nobody_seated"


def test_a_machine_that_shares_nothing_asks_the_seat_nothing(handler, monkeypatch):
    """The heartbeat runs this every few seconds on every machine; a machine
    with no share has nothing for a peer to wait on and reads no session
    table to say so."""

    def refuse():
        raise AssertionError("a machine that shares nothing must not ask")

    monkeypatch.setattr(rdp_module, "graphical_accounts", refuse)

    assert handler.declaration()["attention"] == ""


def test_connect_on_windows_goes_through_the_platforms_own_screen(handler, monkeypatch):
    """The service lives in session 0, where a Popen opens a window nobody
    sees. Found on a laptop: Connect did nothing visible."""
    started = []
    handler._platform.start_on_screen = lambda argv: started.append(list(argv))
    monkeypatch.setattr(rdp_module.os, "name", "nt")
    monkeypatch.setattr(
        rdp_module.subprocess,
        "Popen",
        lambda command, **kwargs: (_ for _ in ()).throw(AssertionError("Popen used")),
    )

    outcome = handler.act(
        entries=[ENTRY],
        account="pat",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_s9"},
    )

    assert outcome == {}
    assert started == [["/usr/bin/rustdesk", "--connect", "192.168.100.6"]]


def test_connect_on_windows_carries_the_platforms_refusal(handler, monkeypatch):
    handler._platform.start_on_screen = lambda argv: {
        "code": "rdp_no_desktop",
        "params": {},
    }
    monkeypatch.setattr(rdp_module.os, "name", "nt")

    outcome = handler.act(
        entries=[ENTRY],
        account="pat",
        is_privileged=False,
        body={"action": "connect", "id": "rdp_s9"},
    )

    assert outcome == {"code": "rdp_no_desktop", "params": {}}
