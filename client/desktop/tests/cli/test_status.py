"""``nclient status``: one line per hub and one for the resident, never lying.

The matrix is walked as the person types it: joined and not, connected and
reconnecting, the resident alive and dead, one hub and several with the
exit marked. The running resident is asked first over its socket; the
binding file answers only when nothing does.
"""

import pytest

from neutrino_client import CLIENT_VERSION
from neutrino_client.cli import status as status_cli
from neutrino_client.cli import wording
from neutrino_client.control.server import ControlServer
from neutrino_client.core import enrollment
from tests.conftest import (
    BINDING,
    OFFICE_BINDING,
    FakeClientPlatform,
    FakeResident,
    bind,
    discard,
)

GATEWAY_URL = "https://hub.lan:8443"


def printed(capsys) -> list:
    """The lines printed, their column padding squeezed to one space."""
    out = capsys.readouterr().out
    return [" ".join(line.split()) for line in out.strip().splitlines()]


@pytest.fixture
def platform(monkeypatch):
    platform = FakeClientPlatform()
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    return platform


@pytest.fixture
def resident(platform):
    """A live resident on this person's socket, scripted."""
    session = FakeResident()
    server = ControlServer(
        resident=session,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    yield session
    server.stop()


def test_every_hub_joined_is_a_line_and_the_exit_is_marked(resident, capsys):
    assert status_cli.main() == 0

    assert printed(capsys) == [
        f"neutrino-client {CLIENT_VERSION}",
        f"hub home {GATEWAY_URL} connected {status_cli.EXIT_MARK}",
        "hub office https://office.lan:8443 connected",
        f"resident {status_cli.RESIDENT_RUNNING}",
    ]


def test_a_reconnecting_socket_is_not_a_clean_status(resident, capsys):
    resident.hubs_value[0]["connection_state"] = "reconnecting"
    resident.hubs_value[0]["last_error"] = {
        "code": "hub_unreachable",
        "params": {"detail": "down"},
    }

    assert status_cli.main() == 1

    lines = printed(capsys)
    assert f"hub home {GATEWAY_URL} reconnecting: down {status_cli.EXIT_MARK}" in lines
    assert "hub office https://office.lan:8443 connected" in lines
    assert f"resident {status_cli.RESIDENT_RUNNING}" in lines


def test_a_replaced_socket_is_not_a_clean_status(resident, capsys):
    resident.hubs_value[0]["connection_state"] = "replaced"

    assert status_cli.main() == 1

    mark = status_cli.EXIT_MARK
    assert (
        f"hub home {GATEWAY_URL} replaced: another client took this connection {mark}"
        in printed(capsys)
    )


def test_bound_and_dead_reads_the_binding_file(platform, config_path, capsys):
    bind(
        config_path,
        bindings=[dict(BINDING, gateway_url=GATEWAY_URL), dict(OFFICE_BINDING)],
    )
    enrollment.set_exit_hub_id("h2")

    assert status_cli.main() == 1

    assert printed(capsys) == [
        f"neutrino-client {CLIENT_VERSION}",
        f"hub home {GATEWAY_URL}",
        f"hub office {OFFICE_BINDING['gateway_url']} {status_cli.EXIT_MARK}",
        f"resident {status_cli.RESIDENT_NOT_RUNNING}",
    ]


def test_unbound_and_running_says_joined_nothing(resident, capsys):
    resident.is_bound = False

    assert status_cli.main() == 1

    lines = printed(capsys)
    assert f"hub {wording.NOT_JOINED}" in lines
    assert f"resident {status_cli.RESIDENT_RUNNING}" in lines


def test_unbound_and_dead_says_both(platform, capsys):
    assert status_cli.main() == 1

    lines = printed(capsys)
    assert f"hub {wording.NOT_JOINED}" in lines
    assert f"resident {status_cli.RESIDENT_NOT_RUNNING}" in lines


@pytest.mark.parametrize(
    "error, fragment",
    [
        ({"code": "hub_refused", "params": {}}, "refused this client's token"),
        ({"code": "hub_untrusted", "params": {}}, "the hub's identity changed"),
        ({"code": "binding_unknown", "params": {}}, "no longer knows this client"),
        ({"code": "hub_unreachable", "params": {"detail": "no route"}}, "no route"),
        (
            {
                "code": "protocol_too_new",
                "params": {"peer": 2, "hub": 1, "min": 1},
            },
            "this client speaks protocol 2; the hub speaks 1",
        ),
        (
            {
                "code": "protocol_too_old",
                "params": {"peer": 1, "hub": 3, "min": 2},
            },
            "this client speaks protocol 1; the hub accepts 2 and up",
        ),
        ({"code": "client_disabled", "params": {}}, "switched this client off"),
    ],
)
def test_every_socket_refusal_is_worded(resident, capsys, error, fragment):
    resident.hubs_value[0]["connection_state"] = "reconnecting"
    resident.hubs_value[0]["last_error"] = error

    assert status_cli.main() == 1

    out = capsys.readouterr().out
    assert "hub        " in out
    assert fragment in out
    assert error["code"] not in out


def test_a_resident_of_another_account_reads_as_none(platform, config_path, capsys):
    bind(config_path, url=GATEWAY_URL)
    platform.peer = {"account": "bob", "uid": 1001, "is_same_user": False}
    server = ControlServer(
        resident=FakeResident(),
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    try:
        assert status_cli.main() == 1
    finally:
        server.stop()

    assert f"resident {status_cli.RESIDENT_NOT_RUNNING}" in printed(capsys)
