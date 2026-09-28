"""The Linux seat: loginctl's sessions, /proc, and the Wayland permission.

A desktop is a graphical session loginctl lists, or a display this process
can see; the seat's owners are read with their sessions; the connected
peers are counted off the kernel's own table; a seated account's display
comes off its own processes; and on Wayland a peer waits on the screen
permission until RustDesk holds it.
"""

import os

from neutrino_agent.rdp import linux_seat as seat_module
from neutrino_agent.rdp.linux_seat import LinuxSeat

# --- what counts as a desktop to share ---


def _loginctl_answering(monkeypatch, listed: str, types: str):
    """A loginctl that lists those sessions and reports those types."""

    def loginctl(arguments):
        return listed if arguments[0] == "list-sessions" else types

    monkeypatch.setattr(seat_module, "_loginctl", loginctl)


def test_a_graphical_session_is_a_desktop(monkeypatch):
    monkeypatch.setattr(seat_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "3 1000 pat seat0\n", "Type=wayland\n")

    assert seat_module.has_desktop_session() is True


def test_only_tty_sessions_are_no_desktop(monkeypatch):
    """The headless box: it has sessions, all of them terminals."""
    monkeypatch.setattr(seat_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "5 0 root\n7 1000 pat\n", "Type=tty\n\nType=tty\n")

    assert seat_module.has_desktop_session() is False


def test_no_sessions_at_all_is_no_desktop(monkeypatch):
    monkeypatch.setattr(seat_module.os, "environ", {})
    _loginctl_answering(monkeypatch, "\n", "")

    assert seat_module.has_desktop_session() is False


def test_a_machine_that_cannot_be_asked_is_not_refused(monkeypatch):
    """A machine without loginctl is one this cannot tell about, and a guess
    that refuses is worse than the raw refusal it replaced."""
    monkeypatch.setattr(seat_module.os, "environ", {})
    monkeypatch.setattr(seat_module, "_loginctl", lambda arguments: None)

    assert seat_module.has_desktop_session() is True


def test_a_session_this_process_can_see_is_a_desktop(monkeypatch):
    monkeypatch.setattr(seat_module.os, "environ", {"DISPLAY": ":0"})

    assert seat_module.has_desktop_session() is True


def test_the_loginctl_probe_asks_for_the_session_types(monkeypatch):
    asked = []

    def run(command, **kwargs):
        asked.append(command)

        class _Result:
            returncode = 0
            stdout = "3 1000 pat seat0\n"

        return _Result()

    monkeypatch.setattr(seat_module.subprocess, "run", run)

    assert seat_module._loginctl(["list-sessions", "--no-legend"]) == (
        "3 1000 pat seat0\n"
    )
    assert asked == [["loginctl", "list-sessions", "--no-legend"]]


def test_a_loginctl_that_exits_nonzero_answers_nothing(monkeypatch):
    def run(command, **kwargs):
        class _Result:
            returncode = 1
            stdout = "everything is fine"

        return _Result()

    monkeypatch.setattr(seat_module.subprocess, "run", run)

    assert seat_module._loginctl(["list-sessions"]) is None


def test_the_seat_owners_are_read_with_their_sessions(monkeypatch):
    """Two sessions, one graphical: the owner of the graphical one is the
    answer, matched to its own type and not the tty's."""
    _loginctl_answering(
        monkeypatch,
        "1 1000 sam seat0 tty1\n3 1001 pat seat0 tty2\n",
        "Type=tty\nType=x11\n",
    )

    assert seat_module.graphical_accounts() == ["pat"]


def test_a_machine_without_loginctl_cannot_say_who_is_seated(monkeypatch):
    monkeypatch.setattr(seat_module, "_loginctl", lambda arguments: None)

    assert seat_module.graphical_accounts() is None


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
    monkeypatch.setattr(seat_module, "RDP_PROC_TCP_PATHS", (str(table), str(table6)))


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

    assert seat_module.connected_count(21118) == 3
    assert seat_module.connected_count(22) == 1


def test_a_machine_whose_table_cannot_be_read_counts_nobody(monkeypatch):
    monkeypatch.setattr(seat_module, "RDP_PROC_TCP_PATHS", ("/nowhere/tcp",))

    assert seat_module.connected_count(21118) == 0


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
    monkeypatch.setattr(seat_module, "RDP_PROC_DIR", str(proc))
    real_stat = os.stat
    monkeypatch.setattr(
        seat_module.os,
        "stat",
        lambda path, **kw: (
            type("S", (), {"st_uid": uid})()
            if str(path).endswith("4242")
            else real_stat(path, **kw)
        ),
    )
    monkeypatch.setattr(seat_module, "pwd", _FakePwd)


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

    assert seat_module.session_environment("sam") == {
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
        "XAUTHORITY": "/run/user/1000/.mutter",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    }


def test_a_process_without_a_display_is_no_environment_source(tmp_path, monkeypatch):
    _fake_proc(tmp_path, monkeypatch, environ=b"HOME=/home/sam\0TERM=xterm\0")

    assert seat_module.session_environment("sam") is None


def test_an_account_the_machine_does_not_have_has_no_session(monkeypatch):
    monkeypatch.setattr(seat_module, "pwd", _FakePwd)

    assert seat_module.session_environment("nobody") is None


# --- what a peer would wait on at a seated screen ---


def test_a_wayland_seat_without_the_permission_says_so(monkeypatch):
    """RustDesk hands the screen out through a dialog on this machine's own
    screen. A peer that dials before somebody answers it waits in
    "connecting" forever, so the fleet is told first."""
    monkeypatch.setattr(seat_module, "is_wayland_seat", lambda: True)
    monkeypatch.setattr(seat_module, "has_screen_permission", lambda home: False)

    assert LinuxSeat().screen_attention("/home/pat") == "rdp_screen_not_allowed"


def test_a_seat_that_already_granted_it_says_nothing(monkeypatch):
    """Once per person, not once per connection: RustDesk keeps the answer."""
    homes = []
    monkeypatch.setattr(seat_module, "is_wayland_seat", lambda: True)
    monkeypatch.setattr(
        seat_module, "has_screen_permission", lambda home: homes.append(home) or True
    )

    assert LinuxSeat().screen_attention("/home/pat") == ""
    assert homes == ["/home/pat"]


def test_an_x11_seat_needs_no_permission(monkeypatch):
    monkeypatch.setattr(seat_module, "is_wayland_seat", lambda: False)

    assert LinuxSeat().screen_attention("/home/pat") == ""


def test_the_permission_is_the_token_rustdesk_wrote_into_its_config(
    tmp_path, monkeypatch
):
    home = tmp_path / "pat"
    config = home / ".config" / "rustdesk" / "RustDesk2.toml"
    config.parent.mkdir(parents=True)
    monkeypatch.setattr(seat_module.rustdesk, "RUSTDESK_ROOT_CONFIG", str(tmp_path))

    config.write_text("[options]\ndirect-server = 'Y'\n")
    assert seat_module.has_screen_permission(str(home)) is False

    config.write_text("[options]\nwayland-restore-token = 'abc'\n")
    assert seat_module.has_screen_permission(str(home)) is True
