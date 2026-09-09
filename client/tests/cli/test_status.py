"""``nclient status``: three lines that never lie about the machine.

The matrix is walked as the person types it: bound and unbound, the
resident alive and dead. The running resident is asked first over its
socket; the binding file answers only when nothing does.
"""

import pytest

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import status as status_cli
from neutrino_client.cli import wording
from neutrino_client.control.server import ControlServer
from tests.conftest import FakeClientPlatform, FakeSession, bind, discard

GATEWAY_URL = "https://hub.lan:8443"


@pytest.fixture
def platform(monkeypatch):
    platform = FakeClientPlatform()
    monkeypatch.setattr(status_cli, "detect_platform", lambda: platform)
    return platform


@pytest.fixture
def resident(platform):
    """A live resident on this person's socket, scripted through its session."""
    session = FakeSession()
    server = ControlServer(
        session=session,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    yield session
    server.stop()


def test_bound_and_running_reads_from_the_resident(resident, config_path, capsys):
    bind(config_path, url=GATEWAY_URL)

    assert status_cli.main() == 0

    out = capsys.readouterr().out
    assert f"neutrino-client {CLIENT_VERSION}" in out
    assert f"hub        {GATEWAY_URL}   connected" in out
    assert "resident   running" in out
    assert f"poll       {status_cli.POLL_OK}" in out


def test_bound_and_dead_reads_the_binding_file(platform, config_path, capsys):
    bind(config_path, url=GATEWAY_URL)

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert f"hub        {GATEWAY_URL}   connected" in out
    assert f"resident   {status_cli.RESIDENT_NOT_RUNNING}" in out
    assert f"poll       {status_cli.POLL_NOT_POLLED}" in out


def test_unbound_and_running_says_joined_nothing(resident, capsys):
    resident.is_bound = False

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert f"hub        {wording.NOT_JOINED}" in out
    assert "resident   running" in out
    assert "poll" not in out


def test_unbound_and_dead_says_both(platform, capsys):
    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert f"hub        {wording.NOT_JOINED}" in out
    assert f"resident   {status_cli.RESIDENT_NOT_RUNNING}" in out
    assert "poll" not in out


@pytest.mark.parametrize(
    "error, fragment",
    [
        ({"code": "hub_refused", "params": {}}, "refused this client's token"),
        ({"code": "hub_untrusted", "params": {}}, "not the hub this link pins"),
        ({"code": "hub_unreachable", "params": {"detail": "no route"}}, "no route"),
        (
            {
                "code": "client_newer_than_hub",
                "params": {"hub_version": "0.1.0", "client_version": "0.2.0"},
            },
            "this client (0.2.0) is newer than the hub (0.1.0)",
        ),
        (
            {"code": "self_unbound", "params": {"cause": "hub_untrusted"}},
            "the hub's identity changed",
        ),
        ({"code": "client_disabled", "params": {}}, "switched this client off"),
    ],
)
def test_every_poll_refusal_is_worded(resident, config_path, capsys, error, fragment):
    bind(config_path, url=GATEWAY_URL)
    resident.error_payload = error

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert f"poll       " in out
    assert fragment in out
    assert error["code"] not in out.split("poll")[1]


def test_a_resident_of_another_account_reads_as_none(platform, config_path, capsys):
    bind(config_path, url=GATEWAY_URL)
    platform.peer = {"account": "bob", "uid": 1001, "is_same_user": False}
    server = ControlServer(
        session=FakeSession(),
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    try:
        assert status_cli.main() == 1
    finally:
        server.stop()

    assert f"resident   {status_cli.RESIDENT_NOT_RUNNING}" in capsys.readouterr().out
