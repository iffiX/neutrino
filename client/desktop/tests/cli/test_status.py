"""``nclient status``: one line per hub and one for the resident, never lying.

The matrix is walked as the person types it: joined and not, connected and
connecting, the resident alive and dead, one hub and several with the
exit marked. The running resident is asked first over its socket; the
binding file answers only when nothing does.
"""

import json
import time

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
        f"hub home {GATEWAY_URL} Connected {status_cli.EXIT_MARK}",
        "hub office https://office.lan:8443 Connected",
        f"resident {status_cli.RESIDENT_RUNNING}",
    ]


def test_a_connecting_socket_is_not_a_clean_status(resident, capsys):
    resident.hubs_value[0]["connection"] = "connecting"

    assert status_cli.main() == 1

    lines = printed(capsys)
    assert f"hub home {GATEWAY_URL} Connecting… {status_cli.EXIT_MARK}" in lines
    assert "hub office https://office.lan:8443 Connected" in lines
    assert f"resident {status_cli.RESIDENT_RUNNING}" in lines


def test_a_replaced_socket_is_not_a_clean_status(resident, capsys):
    resident.hubs_value[0]["connection"] = "replaced"

    assert status_cli.main() == 1

    mark = status_cli.EXIT_MARK
    assert (
        f"hub home {GATEWAY_URL} Replaced by another client · Reconnect {mark}"
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
    "reason, seconds, line",
    [
        ("hub_silent", 30, "The hub did not answer · retrying in 30 s"),
        (
            "hub_off_overlay",
            5,
            "The hub is not on the virtual network · retrying in 5 s",
        ),
        ("no_network", None, "No network"),
        ("untrusted", 60, "Certificate mismatch · retrying in 60 s"),
        ("admission_paused", 42, "The hub pauses new devices · retrying in 42 s"),
        ("unknown_device", None, "The hub does not know this device"),
        ("too_old", None, "Version too old"),
    ],
)
def test_every_waiting_reason_prints_its_state_line(
    resident, capsys, reason, seconds, line
):
    resident.hubs_value[0].update(
        connection="waiting",
        wait_reason=reason,
        next_round_at=None if seconds is None else time.time() + seconds - 0.5,
    )

    assert status_cli.main() == 1

    assert f"hub home {GATEWAY_URL} {line} {status_cli.EXIT_MARK}" in printed(capsys)


def test_a_countdown_past_its_moment_prints_connecting(resident, capsys):
    resident.hubs_value[0].update(
        connection="waiting", wait_reason="hub_silent", next_round_at=time.time() - 1
    )

    status_cli.main()

    assert f"hub home {GATEWAY_URL} Connecting… {status_cli.EXIT_MARK}" in printed(
        capsys
    )


def test_a_refused_join_prints_the_codes_wording(resident, capsys):
    resident.hubs_value[0].update(
        connection="waiting",
        wait_reason="join_refused",
        wait_code={"code": "ticket_spent", "params": {}},
    )

    status_cli.main()

    out = capsys.readouterr().out
    assert "Join refused · The hub refused this link" in out
    assert "ticket_spent" not in out


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


# --- the same account as one JSON object ---


def test_json_carries_every_hub_and_its_way_in(resident, capsys):
    resident.hubs_value[0]["reached_through"] = "relay"

    assert status_cli.main(is_json=True) == 0

    status = json.loads(capsys.readouterr().out)
    assert status["version"] == CLIENT_VERSION
    assert status["is_running"] is True
    home, office = status["hubs"]
    assert home == {
        "hub_id": "h1",
        "hub_name": "home",
        "gateway_url": GATEWAY_URL,
        "connection": "connected",
        "wait_reason": "",
        "wait_code": None,
        "next_round_at": None,
        "reached_through": "relay",
        "rtt_ms": None,
        "is_exit": True,
        "last_error": None,
    }
    assert office["reached_through"] == ""


def test_a_connected_hub_shows_its_way_in_and_its_round_trip(resident, capsys):
    resident.hubs_value[0]["reached_through"] = "lan"
    resident.hubs_value[0]["rtt_ms"] = 12
    resident.hubs_value[1]["reached_through"] = "relay"

    assert status_cli.main() == 0

    lines = printed(capsys)
    assert (
        f"hub home {GATEWAY_URL} Connected · LAN · 12 ms {status_cli.EXIT_MARK}"
        in lines
    )
    assert "hub office https://office.lan:8443 Connected · SSH Relay" in lines

    assert status_cli.main(is_json=True) == 0

    home, office = json.loads(capsys.readouterr().out)["hubs"]
    assert (home["rtt_ms"], office["rtt_ms"]) == (12, None)


def test_a_hub_not_connected_shows_no_tags(resident, capsys):
    resident.hubs_value[0].update(
        connection="connecting", reached_through="lan", rtt_ms=12
    )

    status_cli.main()

    assert f"hub home {GATEWAY_URL} Connecting… {status_cli.EXIT_MARK}" in printed(
        capsys
    )


@pytest.mark.parametrize("way", ["direct", "a_way_this_client_does_not_know"])
def test_json_passes_the_hubs_way_in_through_unchanged(resident, capsys, way):
    resident.hubs_value[0]["reached_through"] = way

    status_cli.main(is_json=True)

    assert json.loads(capsys.readouterr().out)["hubs"][0]["reached_through"] == way


def test_json_with_no_resident_reads_the_binding_file(platform, config_path, capsys):
    bind(config_path, bindings=[dict(BINDING), dict(OFFICE_BINDING)])

    assert status_cli.main(is_json=True) == 1

    status = json.loads(capsys.readouterr().out)
    assert status["is_running"] is False
    assert [hub["hub_name"] for hub in status["hubs"]] == ["home", "office"]
    assert {hub["connection"] for hub in status["hubs"]} == {""}


def test_json_of_a_connecting_hub_is_not_a_clean_status(resident, capsys):
    resident.hubs_value[1]["connection"] = "connecting"

    assert status_cli.main(is_json=True) == 1
    assert json.loads(capsys.readouterr().out)["hubs"][1]["connection"] == (
        "connecting"
    )


def test_a_network_connect_in_progress_reads_no_hub_word(resident, capsys):
    resident.hubs_value[0]["overlay"] = dict(
        resident.hubs_value[0]["overlay"], state="off", stage="login", address=""
    )
    resident.hubs_value[0]["jobs"] = dict(
        resident.hubs_value[0]["jobs"], overlay_job="connecting"
    )

    status_cli.main()
    status_cli.main(is_json=True)

    out = capsys.readouterr().out
    assert "Waiting for the hub" not in out and "stage" not in out
    assert "ui.stage.hub" not in out and "ui.overlay.connecting" not in out
