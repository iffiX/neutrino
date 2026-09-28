"""The macOS seat: the console's owner, netstat, and the privacy database.

Commands are faked at ``subprocess.run``; the privacy database is a real
SQLite file in ``tmp_path`` with the one table the grants live in. What is
pinned is who is at the screen, that a share says ``rdp_permissions_needed``
until RustDesk holds both grants, and that a database this process cannot
read says the same rather than claiming a grant nobody saw.
"""

import sqlite3
import subprocess

import pytest

from neutrino_agent.rdp import darwin_seat as seat_module
from neutrino_agent.rdp.darwin_seat import DarwinSeat, granted_services

SCREEN = "kTCCServiceScreenCapture"
ACCESSIBILITY = "kTCCServiceAccessibility"


def printing(monkeypatch, stdout, *, returncode=0, calls=None):
    def run(command, **kwargs):
        if calls is not None:
            calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout=stdout)

    monkeypatch.setattr(seat_module.subprocess, "run", run)


def tcc_database(path, rows):
    """A privacy database holding these ``(service, client, auth_value)`` rows."""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE access (service TEXT, client TEXT, client_type INTEGER, "
        "auth_value INTEGER)"
    )
    connection.executemany(
        "INSERT INTO access VALUES (?, ?, 0, ?)",
        [(service, client, value) for service, client, value in rows],
    )
    connection.commit()
    connection.close()
    return str(path)


def test_the_consoles_owner_is_the_seat(monkeypatch):
    calls = []
    printing(monkeypatch, "pat\n", calls=calls)

    assert DarwinSeat().graphical_accounts() == ["pat"]
    assert calls == [["stat", "-f", "%Su", "/dev/console"]]


def test_the_login_window_is_nobody_seated(monkeypatch):
    printing(monkeypatch, "root\n")

    assert DarwinSeat().graphical_accounts() == []


def test_a_console_that_cannot_be_asked_cannot_say(monkeypatch):
    printing(monkeypatch, "", returncode=1)

    assert DarwinSeat().graphical_accounts() is None


def test_the_peers_are_the_established_rows_on_the_direct_port(monkeypatch):
    calls = []
    printing(
        monkeypatch,
        "tcp4  0  0  192.0.2.10.21118  192.0.2.20.50123  ESTABLISHED\n"
        "tcp4  0  0  *.21118  *.*  LISTEN\n",
        calls=calls,
    )

    assert DarwinSeat().connected_count(21118) == 1
    assert calls == [["netstat", "-an", "-p", "tcp"]]


def test_both_grants_held_is_nothing_to_wait_on(tmp_path):
    database = tcc_database(
        tmp_path / "TCC.db",
        [
            (SCREEN, "com.carriez.rustdesk", 2),
            (ACCESSIBILITY, "com.carriez.RustDesk", 2),
        ],
    )

    assert DarwinSeat(tcc_database=database).screen_attention("/Users/pat") == ""
    assert granted_services(database) == {SCREEN, ACCESSIBILITY}


@pytest.mark.parametrize(
    "rows",
    [
        [(SCREEN, "com.carriez.rustdesk", 2)],
        [
            (SCREEN, "com.carriez.rustdesk", 2),
            (ACCESSIBILITY, "com.carriez.rustdesk", 0),
        ],
        [(SCREEN, "com.other.app", 2), (ACCESSIBILITY, "com.other.app", 2)],
        [],
    ],
)
def test_a_grant_missing_or_denied_needs_the_permissions(tmp_path, rows):
    database = tcc_database(tmp_path / "TCC.db", rows)

    assert (
        DarwinSeat(tcc_database=database).screen_attention("/Users/pat")
        == "rdp_permissions_needed"
    )


def test_a_database_that_cannot_be_read_never_claims_a_grant(tmp_path):
    missing = str(tmp_path / "nowhere" / "TCC.db")
    unreadable = tmp_path / "TCC.db"
    unreadable.write_text("not a database")

    for database in (missing, str(unreadable)):
        assert granted_services(database) is None
        assert (
            DarwinSeat(tcc_database=database).screen_attention("/Users/pat")
            == "rdp_permissions_needed"
        )


def test_a_mac_screen_is_always_a_desktop():
    assert DarwinSeat().has_desktop_session() is True
