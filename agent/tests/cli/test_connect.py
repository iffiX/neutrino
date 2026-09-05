"""``nagent connect``: joining a hub, and every way the join is refused.

The walk is the operator's: a link on the command line or pasted at the
prompt, an existing binding that is kept unless the answer is yes, and each
refusal the hub can give worded on the way out. Nothing here reaches a
network; the one enroll POST is answered by the test.
"""

import pytest

import neutrino_agent.cli.connect as connect_cli
import neutrino_agent.cli.entry as entry
import neutrino_agent.core.channel as channel
import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.core.channel import (
    GatewayRefused,
    GatewayUntrusted,
    GatewayVersionRefused,
    GatewayWireStale,
)
from tests.conftest import bind, link_for

GATEWAY_URL = "https://hub.lan:8443"
OLD_GATEWAY_URL = "https://old.lan:8443"
LINK = link_for({"urls": [GATEWAY_URL], "token": "ticket", "fp": "ab" * 32})


def answer_with(monkeypatch, *, reply=None, error=None):
    """What the hub says to the one enroll POST this walk makes.

    Args:
        monkeypatch: The test's patcher.
        reply: The JSON the hub answers with.
        error: Raised instead of answering.

    Returns:
        The list the posts land in.
    """
    posted = []

    def post(self, path, payload):
        posted.append((path, payload))
        if error is not None:
            raise error
        return dict(reply or {})

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)
    return posted


def running_service_word() -> str:
    """The service already runs, so the join starts nothing."""
    return "running"


def refuse_to_ask(prompt: str) -> str:
    """Fail the test rather than prompt where no prompt is allowed."""
    raise AssertionError(f"connect asked: {prompt}")


@pytest.fixture
def joined_hub(monkeypatch):
    """A hub that accepts the enrollment and a service already running."""
    monkeypatch.setattr(connect_cli, "service_state", running_service_word)
    return answer_with(monkeypatch, reply={"token": "device-token"})


def test_a_fresh_join_stores_the_binding_and_names_the_hub(joined_hub, capsys):
    assert connect_cli.main(LINK, is_forced=False) == 0

    assert f"joined {GATEWAY_URL}" in capsys.readouterr().out
    stored = enrollment.load_config()
    assert stored["gateway_url"] == GATEWAY_URL
    assert stored["token"] == "device-token"


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

    assert asked == [f"this machine is bound to {OLD_GATEWAY_URL}; replace it? [y/N] "]
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


def test_an_unprivileged_connect_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "connect", LINK])

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert (
        "nagent connect needs root — it writes the binding and starts the service"
        in err
    )
    assert f"sudo nagent connect {LINK}" in err


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
    def paste_nothing(prompt):
        return "   "

    monkeypatch.setattr(connect_cli, "input", paste_nothing, raising=False)
    posted = answer_with(monkeypatch, reply={"token": "device-token"})

    assert connect_cli.main("", is_forced=False) == 1

    assert "error: no link was given" in capsys.readouterr().err
    assert posted == []


def test_a_garbage_link_is_refused_in_words(monkeypatch, capsys):
    posted = answer_with(monkeypatch, reply={"token": "device-token"})

    assert connect_cli.main("not-a-link", is_forced=False) == 1

    err = capsys.readouterr().err
    assert "error: that is not an enrollment link; copy the whole line from " in err
    assert "the gateway's Devices page" in err
    assert posted == []
    assert "gateway_url" not in enrollment.load_config()


def test_an_expired_ticket_is_worded_as_one(monkeypatch, capsys):
    answer_with(monkeypatch, error=GatewayRefused("gateway refused (401)"))

    assert connect_cli.main(LINK, is_forced=False) == 1

    err = capsys.readouterr().err
    assert "the gateway refused this link — it may have expired; generate a " in err
    assert "fresh one on the Devices page" in err
    assert "gateway_url" not in enrollment.load_config()


def test_a_certificate_off_the_pin_is_worded_as_one(monkeypatch, capsys):
    answer_with(monkeypatch, error=GatewayUntrusted("certificate off the pin"))

    assert connect_cli.main(LINK, is_forced=False) == 1

    err = capsys.readouterr().err
    assert f"{GATEWAY_URL} presented a certificate this link does not pin" in err
    assert "generate a fresh link on the hub's Devices page" in err
    assert "gateway_url" not in enrollment.load_config()


def test_a_stale_wire_points_at_reinstalling_from_the_devices_page(monkeypatch, capsys):
    answer_with(monkeypatch, error=GatewayWireStale(hub_wire=3, agent_wire=2))

    assert connect_cli.main(LINK, is_forced=False) == 1

    err = capsys.readouterr().err
    assert "this agent build does not match the hub; reinstall it from the " in err
    assert "hub's Devices page and connect again" in err
    assert "gateway_url" not in enrollment.load_config()


def test_connect_refuses_a_newer_agent_visibly(monkeypatch, capsys):
    answer_with(
        monkeypatch,
        error=GatewayVersionRefused(hub_version="0.1.0", agent_version="0.2.0"),
    )

    assert connect_cli.main(LINK, is_forced=False) == 1

    err = capsys.readouterr().err
    assert "this agent (0.2.0) is newer than the hub (0.1.0)" in err
    assert "update the hub first" in err
    assert "gateway_url" not in enrollment.load_config()
