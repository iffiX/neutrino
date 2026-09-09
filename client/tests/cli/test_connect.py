"""``nclient connect``: joining a hub, and every way the join is refused.

The walk is the person's: a link on the command line or pasted at the
prompt, an existing binding that is kept unless the answer is yes, each
refusal worded on the way out, and the hint to open the client when no
resident answers. Nothing here reaches a network.
"""

import pytest

import neutrino_client.cli.connect as connect_cli
import neutrino_client.core.channel as channel
import neutrino_client.core.enrollment as enrollment
from neutrino_client.cli import wording
from neutrino_client.control.server import ControlServer
from neutrino_client.core.channel import (
    GatewayRefused,
    GatewayUntrusted,
    GatewayVersionRefused,
)
from tests.conftest import FakeClientPlatform, FakeSession, bind, discard, link_for

GATEWAY_URL = "https://hub.lan:8443"
OLD_GATEWAY_URL = "https://old.lan:8443"
LINK = link_for({"urls": [GATEWAY_URL], "token": "ticket", "fp": "ab" * 32})


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
    raise AssertionError(f"connect asked: {prompt}")


@pytest.fixture
def joined_hub(monkeypatch):
    """A hub that accepts the enrollment; whether a resident runs is the test's."""
    platform = FakeClientPlatform()
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    answer_with(monkeypatch, reply={"token": "device-token", "client_id": "c1"})
    return platform


@pytest.fixture
def resident(joined_hub):
    """A live resident on this person's socket."""
    server = ControlServer(
        session=FakeSession(),
        platform=joined_hub,
        log=discard,
        socket_path=joined_hub.control_socket_path(),
    )
    assert server.start()
    yield server
    server.stop()


def test_a_fresh_join_stores_the_binding_and_names_the_hub(resident, capsys):
    assert connect_cli.main(LINK, is_forced=False) == 0

    streams = capsys.readouterr()
    assert f"joined {GATEWAY_URL}" in streams.out
    assert streams.err == ""
    stored = enrollment.load_config()
    assert stored["gateway_url"] == GATEWAY_URL
    assert stored["token"] == "device-token"


def test_without_a_resident_the_join_hints_at_opening_one(joined_hub, capsys):
    assert connect_cli.main(LINK, is_forced=False) == 0

    streams = capsys.readouterr()
    assert f"joined {GATEWAY_URL}" in streams.out
    assert wording.word_code("resident_not_running") in streams.err
    assert enrollment.load_config()["gateway_url"] == GATEWAY_URL


def test_an_existing_binding_is_kept_when_the_prompt_is_declined(
    monkeypatch, config_path, capsys
):
    bind(config_path, url=OLD_GATEWAY_URL)
    asked = []

    def answer_no(prompt):
        asked.append(prompt)
        return "n"

    monkeypatch.setattr(connect_cli, "input", answer_no, raising=False)
    posted = answer_with(monkeypatch, reply={"token": "device-token"})

    assert connect_cli.main(LINK, is_forced=False) == 1

    assert asked == [f"this person is bound to {OLD_GATEWAY_URL}; replace it? [y/N] "]
    assert "nothing changed" in capsys.readouterr().out
    assert posted == []
    assert enrollment.load_config()["gateway_url"] == OLD_GATEWAY_URL


def test_yes_replaces_the_binding_without_asking(
    joined_hub, monkeypatch, config_path, capsys
):
    bind(config_path, url=OLD_GATEWAY_URL)
    monkeypatch.setattr(connect_cli, "input", refuse_to_ask, raising=False)

    assert connect_cli.main(LINK, is_forced=True) == 0

    assert f"joined {GATEWAY_URL}" in capsys.readouterr().out
    assert enrollment.load_config()["gateway_url"] == GATEWAY_URL


def test_an_empty_link_is_pasted_at_the_prompt(joined_hub, monkeypatch, capsys):
    prompts = []

    def paste(prompt):
        prompts.append(prompt)
        return f"  {LINK}  "

    monkeypatch.setattr(connect_cli, "input", paste, raising=False)

    assert connect_cli.main("", is_forced=False) == 0

    assert prompts == ["paste the enrollment link: "]
    assert f"joined {GATEWAY_URL}" in capsys.readouterr().out


def test_an_empty_prompt_gives_up_in_words(monkeypatch, capsys):
    monkeypatch.setattr(connect_cli, "input", lambda prompt: "   ", raising=False)
    posted = answer_with(monkeypatch, reply={"token": "device-token"})

    assert connect_cli.main("", is_forced=False) == 1

    assert wording.word_code("link_missing") in capsys.readouterr().err
    assert posted == []


@pytest.mark.parametrize(
    "link, code",
    [
        ("not-a-link", "link_unreadable"),
        (
            "neutrino://enroll/"
            + __import__("base64")
            .urlsafe_b64encode(
                b'{"urls": ["http://h"], "token": "t", "kind": "device"}'
            )
            .decode()
            .rstrip("="),
            "link_not_for_client",
        ),
    ],
)
def test_an_unusable_link_is_worded_from_its_code(monkeypatch, capsys, link, code):
    posted = answer_with(monkeypatch, reply={"token": "device-token"})

    assert connect_cli.main(link, is_forced=False) == 1

    assert wording.word_code(code, {}) in capsys.readouterr().err
    assert posted == []
    assert "gateway_url" not in enrollment.load_config()


@pytest.mark.parametrize(
    "error, code",
    [
        (GatewayRefused("401"), "enroll_refused"),
        (GatewayUntrusted("pin"), "hub_untrusted"),
        (
            GatewayVersionRefused(hub_version="0.1.0", client_version="0.2.0"),
            "client_newer_than_hub",
        ),
    ],
)
def test_every_hub_refusal_is_worded_and_stores_nothing(
    monkeypatch, capsys, error, code
):
    answer_with(monkeypatch, error=error)

    assert connect_cli.main(LINK, is_forced=False) == 1

    err = capsys.readouterr().err
    assert err.strip() != code
    assert "gateway_url" not in enrollment.load_config()
    if code == "client_newer_than_hub":
        assert "0.2.0" in err and "0.1.0" in err
