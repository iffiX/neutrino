"""``nclient join``: joining a hub, and every way the join is refused.

The walk is the person's: a link on the command line or pasted at the
prompt, a hub joined beside the hubs already held and stored pending with
no hub asked, and each unusable link worded on the way out. Which process writes the binding is the point: a running
resident is asked to join, and only a person with none enrolls here.
Nothing here reaches a network.
"""

import pytest

import neutrino_client.cli.join as join_cli
import neutrino_client.core.channel as channel
import neutrino_client.core.enrollment as enrollment
from neutrino_client.cli import wording
from neutrino_client.control.server import ControlServer
from neutrino_client.exceptions import (
    EnrollmentError,
    GatewayProtocolRefused,
    GatewayRefused,
    GatewayUntrusted,
)
from tests.conftest import (
    BINDING,
    HUB_ROW,
    OFFICE_BINDING,
    OFFICE_ROW,
    FakeClientPlatform,
    FakeResident,
    bind,
    discard,
    link_for,
)

GATEWAY_URL = "https://hub.lan:8443"
OLD_GATEWAY_URL = "https://old.lan:8443"
LINK = link_for({"urls": [GATEWAY_URL], "token": "ticket", "fp": "ab" * 32})


class FakeJoiningResident(FakeResident):
    """A resident holding one hub, which takes one more when it is asked."""

    def __init__(self, *, platform=None):
        super().__init__(platform=platform)
        self.hubs_value = [dict(HUB_ROW)]

    def connect(self, link: str) -> None:
        super().connect(link)
        self.hubs_value.append(dict(OFFICE_ROW))


def answer_with(monkeypatch, *, reply=None, error=None):
    posted = []

    def post(self, path, payload):
        posted.append((path, payload))
        if error is not None:
            raise error
        return dict(reply or {})

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)
    return posted


def refuse_to_ask(prompt: str) -> str:
    raise AssertionError(f"join asked: {prompt}")


@pytest.fixture
def joined_hub(monkeypatch):
    """A hub that accepts the enrollment, with no resident of this person."""
    platform = FakeClientPlatform()
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    answer_with(monkeypatch, reply={"id": "c1", "token": "device-token"})
    return platform


@pytest.fixture
def resident(joined_hub):
    """A live resident on this person's socket, holding one hub."""
    session = FakeJoiningResident(platform=joined_hub)
    server = ControlServer(
        resident=session,
        platform=joined_hub,
        log=discard,
        socket_path=joined_hub.control_socket_path(),
    )
    assert server.start()
    yield session
    server.stop()


# --- with a resident running, it is the one writer ---


def test_the_running_resident_is_asked_to_join_and_names_the_hub(resident, capsys):
    assert join_cli.main(LINK) == 0

    streams = capsys.readouterr()
    assert streams.out.strip() == wording.CLIENT_JOINED_LINE.format(
        url=OFFICE_ROW["gateway_url"]
    )
    assert streams.err == ""
    assert resident.connected_links == [LINK]
    assert enrollment.bindings() == []


def test_a_link_the_resident_refuses_is_worded_from_its_code(resident, capsys):
    resident.connect_error = EnrollmentError("link_not_for_client", {"kind": "device"})

    assert join_cli.main(LINK) == 1

    assert wording.word_code("link_not_for_client") in capsys.readouterr().err


# --- with none running, the enrollment runs here ---


def test_a_fresh_join_stores_the_binding_and_hints_at_opening_the_client(
    joined_hub, capsys
):
    assert join_cli.main(LINK) == 0

    streams = capsys.readouterr()
    assert f"joined {GATEWAY_URL}" in streams.out
    assert wording.word_code("resident_not_running") in streams.err
    (stored,) = enrollment.bindings()
    assert stored["gateway_url"] == GATEWAY_URL
    assert (stored["is_pending"], stored["ticket"], stored["token"]) == (
        True,
        "ticket",
        "",
    )


def test_a_second_hub_joins_the_first_and_asks_nothing(
    joined_hub, monkeypatch, config_path, capsys
):
    bind(config_path, url=OLD_GATEWAY_URL)
    monkeypatch.setattr(join_cli, "input", refuse_to_ask, raising=False)
    answer_with(monkeypatch, reply={"id": "c2", "token": "device-token"})

    assert join_cli.main(LINK) == 0

    assert f"joined {GATEWAY_URL}" in capsys.readouterr().out
    assert [binding["gateway_url"] for binding in enrollment.bindings()] == [
        OLD_GATEWAY_URL,
        GATEWAY_URL,
    ]


def test_an_empty_link_is_pasted_at_the_prompt(joined_hub, monkeypatch, capsys):
    prompts = []

    def paste(prompt):
        prompts.append(prompt)
        return f"  {LINK}  "

    monkeypatch.setattr(join_cli, "input", paste, raising=False)

    assert join_cli.main("") == 0

    assert prompts == [join_cli.LINK_PROMPT]
    assert f"joined {GATEWAY_URL}" in capsys.readouterr().out


def test_an_empty_prompt_gives_up_in_words(monkeypatch, capsys):
    monkeypatch.setattr(join_cli, "input", lambda prompt: "   ", raising=False)
    posted = answer_with(monkeypatch, reply={"id": "c1", "token": "device-token"})

    assert join_cli.main("") == 1

    assert wording.word_code("link_missing") in capsys.readouterr().err
    assert posted == []


@pytest.mark.parametrize(
    "link, code",
    [
        ("not-a-link", "link_unreadable"),
        (
            link_for({"urls": ["http://h"], "token": "t", "role": "agent"}),
            "link_not_for_client",
        ),
    ],
)
def test_an_unusable_link_is_worded_from_its_code(monkeypatch, capsys, link, code):
    posted = answer_with(monkeypatch, reply={"id": "c1", "token": "device-token"})

    assert join_cli.main(link) == 1

    assert wording.word_code(code, {}) in capsys.readouterr().err
    assert posted == []
    assert enrollment.bindings() == []


def test_a_join_here_asks_no_hub(monkeypatch, capsys):
    posted = answer_with(monkeypatch, error=GatewayRefused("401"))

    assert join_cli.main(LINK) == 0

    assert posted == []
    assert wording.CLIENT_JOINED_LINE.format(url=GATEWAY_URL) in capsys.readouterr().out
    (stored,) = enrollment.bindings()
    assert stored["is_pending"] is True
