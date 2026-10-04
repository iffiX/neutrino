"""``nclient leave``: leaving one of the hubs a person joined.

Leaving forgets the binding first and tells the hub after, from a thread of
its own, so a hub that is slow or cannot be reached holds nobody. Which hub
goes is the point: one
joined needs no name, several need ``--hub``, and a name nobody joined is
refused. A running resident is asked to do it, so one process writes the
binding file.
"""

import threading

import pytest

import neutrino_client.cli.leave as leave_cli
import neutrino_client.core.channel as channel
import neutrino_client.core.enrollment as enrollment
from neutrino_client.cli import wording
from neutrino_client.control.server import ControlServer
from neutrino_client.exceptions import GatewayRefused, GatewayUnreachable
from tests.conftest import (
    BINDING,
    HUB_ROW,
    OFFICE_BINDING,
    FakeClientPlatform,
    FakeResident,
    bind,
    discard,
    link_for,
)


@pytest.fixture
def platform(monkeypatch):
    """This person's machine, with no resident answering on it."""
    platform = FakeClientPlatform()
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    return platform


@pytest.fixture
def resident(platform):
    """A live resident on this person's socket, holding two hubs."""
    session = FakeResident(platform=platform)
    server = ControlServer(
        resident=session,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    assert server.start()
    yield session
    server.stop()


def posted_to(monkeypatch) -> list:
    """What a leaving person tells the hub, recorded instead of sent; the
    thread that tells it is waited for, so the list is whole."""
    posted = []

    def post(self, path, payload):
        posted.append((path, payload))
        return {}

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)
    monkeypatch.setattr(leave_cli, "main", joined_after(leave_cli.main))
    return posted


def joined_after(main):
    """``main``, then every thread it started telling a hub, finished."""

    def run(*args):
        status = main(*args)
        for thread in threading.enumerate():
            if thread.name == "client_leave":
                thread.join(timeout=5)
        return status

    return run


# --- with a resident running, it is the one writer ---


def test_the_running_resident_is_asked_to_leave_the_hub_named(
    resident, config_path, capsys
):
    bind(config_path, bindings=[dict(BINDING), dict(OFFICE_BINDING)])

    assert leave_cli.main("office") == 0

    assert resident.disconnected == ["h2"]
    assert leave_cli.LEAVE_WORDS.format(hub="office") in capsys.readouterr().out
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1", "c2"]


def test_one_hub_joined_needs_no_name(resident, capsys):
    resident.hubs_value = [dict(HUB_ROW)]

    assert leave_cli.main() == 0

    assert resident.disconnected == ["h1"]
    assert leave_cli.LEAVE_WORDS.format(hub="home") in capsys.readouterr().out


def test_several_hubs_and_no_name_is_refused_in_words(resident, capsys):
    assert leave_cli.main() == 1

    assert resident.disconnected == []
    err = capsys.readouterr().err
    assert wording.word_code("ambiguous_hub", {"hubs": "home, office"}) in err
    assert "home, office" in err


def test_a_hub_nobody_joined_is_refused_in_words(resident, capsys):
    assert leave_cli.main("nowhere") == 1

    assert resident.disconnected == []
    assert wording.word_code("unknown_hub") in capsys.readouterr().err


def test_a_resident_that_forgot_the_hub_is_worded(resident, capsys):
    def forget(hub_id: str = "") -> None:
        raise KeyError(hub_id)

    resident.leave = forget

    assert leave_cli.main("office") == 1

    assert wording.word_code("unknown_hub") in capsys.readouterr().err


# --- with none running, the leaving happens here ---


def test_a_bound_person_leaves_and_says_so(monkeypatch, platform, config_path, capsys):
    bind(config_path, url="https://hub.lan:8443")
    posted = posted_to(monkeypatch)

    assert leave_cli.main() == 0

    assert posted == [("/api/channel/leave", {"id": "c1", "token": "tok"})]
    assert leave_cli.LEAVE_WORDS.format(hub="home") in capsys.readouterr().out
    assert enrollment.bindings() == []


def test_only_the_hub_named_is_left(monkeypatch, platform, config_path, capsys):
    bind(config_path, bindings=[dict(BINDING), dict(OFFICE_BINDING)])
    posted = posted_to(monkeypatch)

    assert leave_cli.main("office") == 0

    assert posted == [("/api/channel/leave", {"id": "c2", "token": "tok2"})]
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1"]
    assert leave_cli.LEAVE_WORDS.format(hub="office") in capsys.readouterr().out


def test_a_binding_is_named_by_its_id_as_well(monkeypatch, platform, config_path):
    bind(config_path, bindings=[dict(BINDING), dict(OFFICE_BINDING)])
    posted_to(monkeypatch)

    assert leave_cli.main("c2") == 0

    assert [binding["id"] for binding in enrollment.bindings()] == ["c1"]


def test_several_bindings_and_no_name_leave_none(
    monkeypatch, platform, config_path, capsys
):
    bind(config_path, bindings=[dict(BINDING), dict(OFFICE_BINDING)])
    posted = posted_to(monkeypatch)

    assert leave_cli.main() == 1

    assert posted == []
    assert [binding["id"] for binding in enrollment.bindings()] == ["c1", "c2"]
    assert wording.word_code("ambiguous_hub", {"hubs": "home, office"}) in (
        capsys.readouterr().err
    )


def test_an_unreachable_hub_does_not_hold_the_person(
    monkeypatch, platform, config_path, capsys
):
    bind(config_path, url="https://hub.lan:8443")

    def refuse(self, path, payload):
        raise GatewayUnreachable("cannot reach hub")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", refuse)

    assert leave_cli.main() == 0

    assert leave_cli.LEAVE_WORDS.format(hub="home") in capsys.readouterr().out
    assert enrollment.bindings() == []


def test_the_binding_is_forgotten_before_the_hub_answers(
    monkeypatch, platform, config_path, capsys
):
    bind(config_path, url="https://hub.lan:8443")
    seen = []
    hold = threading.Event()

    def post(self, path, payload):
        seen.append(enrollment.bindings())
        hold.wait(timeout=5)
        raise GatewayRefused("401")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)

    status = leave_cli.main()
    is_held = not hold.is_set()
    bindings_now = enrollment.bindings()
    hold.set()
    joined_after(lambda: None)()

    assert (status, is_held, bindings_now) == (0, True, [])
    assert seen == [[]]
    assert leave_cli.LEAVE_WORDS.format(hub="home") in capsys.readouterr().out


def test_a_pending_binding_is_forgotten_and_no_hub_is_told(
    monkeypatch, platform, config_path
):
    enrollment.enroll(link_for({"urls": ["https://hub:8443"], "token": "ticket"}))
    posted = posted_to(monkeypatch)

    assert leave_cli.main() == 0

    assert posted == []
    assert enrollment.bindings() == []


def test_an_unbound_person_is_told_they_joined_nothing(platform, capsys):
    assert leave_cli.main() == 1

    streams = capsys.readouterr()
    assert wording.NOT_JOINED in streams.err
    assert "left" not in streams.out
