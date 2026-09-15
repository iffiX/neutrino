"""``nagent join``: joining a hub, and every way the join is refused.

The walk is the operator's: a link on the command line or pasted at the
prompt, an existing binding that is kept unless the answer is yes, and each
refusal the hub can give worded on the way out. Nothing here reaches a
network; the one join POST is answered by the test.
"""

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.join as join_cli
import neutrino_agent.core.channel as channel
import neutrino_agent.core.enrollment as enrollment
from neutrino_agent.exceptions import GatewayRefusedDetail, GatewayUntrusted
from tests.conftest import bind, link_for

GATEWAY_URL = "https://hub.lan:8443"
OLD_GATEWAY_URL = "https://old.lan:8443"
LINK = link_for(
    {"urls": [GATEWAY_URL], "token": "ticket", "fp": "ab" * 32, "role": "agent"}
)


def answer_with(monkeypatch, *, reply=None, error=None):
    """What the hub says to the one join POST this walk makes.

    Args:
        monkeypatch: The test's patcher.
        reply: The JSON the hub answers with.
        error: Raised instead of answering.

    Returns:
        The list the posts land in.
    """
    posted = []

    def join(self, payload):
        posted.append((self._gateway_url, payload))
        if error is not None:
            raise error
        return dict(reply or {"id": "3f9c", "token": "device-token"})

    monkeypatch.setattr(channel.BindingHttpClient, "join", join)
    return posted


def running_service_word() -> str:
    """The service already runs, so the join starts nothing."""
    return "running"


def refuse_to_ask(prompt: str) -> str:
    """Fail the test rather than prompt where no prompt is allowed."""
    raise AssertionError(f"join asked: {prompt}")


@pytest.fixture
def joined_hub(monkeypatch):
    """A hub that accepts the join and a service already running."""
    monkeypatch.setattr(join_cli, "service_state", running_service_word)
    return answer_with(monkeypatch)


def test_a_fresh_join_stores_the_binding_and_names_the_hub(joined_hub, capsys):
    assert join_cli.main(LINK, is_forced=False) == 0

    assert f"joined {GATEWAY_URL} as 3f9c" in capsys.readouterr().out
    stored = enrollment.load_binding()
    assert stored["gateway_url"] == GATEWAY_URL
    assert stored["id"] == "3f9c"
    assert stored["token"] == "device-token"
    assert stored["fingerprint"] == "ab" * 32


def test_the_join_posts_the_seven_fields(joined_hub):
    join_cli.main(LINK, is_forced=False)

    ((url, payload),) = joined_hub
    assert url == GATEWAY_URL
    assert set(payload) == {
        "ticket",
        "role",
        "protocol",
        "machine_id",
        "name",
        "software",
        "platform",
    }
    assert payload["role"] == "agent"


def test_an_existing_binding_is_kept_when_the_prompt_is_declined(
    monkeypatch, config_path, capsys
):
    bind(config_path, url=OLD_GATEWAY_URL)
    asked = []

    def answer_no(prompt):
        asked.append(prompt)
        return "n"

    monkeypatch.setattr(join_cli, "input", answer_no, raising=False)
    posted = answer_with(monkeypatch)

    assert join_cli.main(LINK, is_forced=False) == 1

    assert asked == [f"this machine is bound to {OLD_GATEWAY_URL}; replace it? [y/N] "]
    assert "nothing changed" in capsys.readouterr().out
    assert posted == []
    assert enrollment.load_binding()["gateway_url"] == OLD_GATEWAY_URL


def test_yes_replaces_the_binding_without_asking(
    joined_hub, monkeypatch, config_path, capsys
):
    bind(config_path, url=OLD_GATEWAY_URL)
    monkeypatch.setattr(join_cli, "input", refuse_to_ask, raising=False)

    assert join_cli.main(LINK, is_forced=True) == 0

    assert f"joined {GATEWAY_URL}" in capsys.readouterr().out
    assert enrollment.load_binding()["gateway_url"] == GATEWAY_URL


def test_an_unprivileged_join_is_refused_with_the_command(monkeypatch, capsys):
    monkeypatch.setattr(entry.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(entry.sys, "argv", ["nagent", "join", LINK])

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert (
        "nagent join needs root (it writes the binding and starts the service)" in err
    )
    assert f"sudo nagent join {LINK}" in err


def test_an_empty_link_is_pasted_at_the_prompt(joined_hub, monkeypatch, capsys):
    prompts = []

    def paste(prompt):
        prompts.append(prompt)
        return f"  {LINK}  "

    monkeypatch.setattr(join_cli, "input", paste, raising=False)

    assert join_cli.main("", is_forced=False) == 0

    assert prompts == ["paste the enrollment link: "]
    assert f"joined {GATEWAY_URL}" in capsys.readouterr().out


def test_an_empty_prompt_gives_up_in_words(monkeypatch, capsys):
    def paste_nothing(prompt):
        return "   "

    monkeypatch.setattr(join_cli, "input", paste_nothing, raising=False)
    posted = answer_with(monkeypatch)

    assert join_cli.main("", is_forced=False) == 1

    assert "error: no link was given" in capsys.readouterr().err
    assert posted == []


def test_a_garbage_link_is_refused_in_words(monkeypatch, capsys):
    posted = answer_with(monkeypatch)

    assert join_cli.main("not-a-link", is_forced=False) == 1

    err = capsys.readouterr().err
    assert "error: that is not an enrollment link; copy the whole line from " in err
    assert "the hub's Devices page" in err
    assert posted == []
    assert not enrollment.is_bound()


def test_a_client_link_is_refused_in_words(monkeypatch, capsys):
    posted = answer_with(monkeypatch)
    link = link_for({"urls": [GATEWAY_URL], "token": "ticket", "role": "client"})

    assert join_cli.main(link, is_forced=False) == 1

    assert "error: that link is not for a device" in capsys.readouterr().err
    assert posted == []
    assert not enrollment.is_bound()


def test_a_spent_ticket_is_worded_as_one(monkeypatch, capsys):
    answer_with(monkeypatch, error=GatewayRefusedDetail(code="ticket_spent", params={}))

    assert join_cli.main(LINK, is_forced=False) == 1

    err = capsys.readouterr().err
    assert "error: the hub refused this link; it may have expired" in err
    assert "generate a fresh one on the Devices page" in err
    assert not enrollment.is_bound()


def test_a_certificate_off_the_pin_is_worded_as_one(monkeypatch, capsys):
    answer_with(monkeypatch, error=GatewayUntrusted("certificate off the pin"))

    assert join_cli.main(LINK, is_forced=False) == 1

    err = capsys.readouterr().err
    assert f"{GATEWAY_URL} presented a certificate this link does not pin" in err
    assert "generate a fresh link on the hub's Devices page" in err
    assert not enrollment.is_bound()


@pytest.mark.parametrize(
    "code, params, words",
    [
        (
            "protocol_too_new",
            {"peer": 2, "hub": 1, "min": 1},
            "this agent speaks protocol 2; the hub speaks 1, so update the hub first",
        ),
        (
            "protocol_too_old",
            {"peer": 1, "hub": 3, "min": 2},
            "this agent speaks protocol 1; the hub accepts 2 and up, "
            "so update this agent",
        ),
    ],
)
def test_a_protocol_refusal_names_both_numbers(
    monkeypatch, capsys, code, params, words
):
    answer_with(monkeypatch, error=GatewayRefusedDetail(code=code, params=params))

    assert join_cli.main(LINK, is_forced=False) == 1

    assert f"error: {words}" in capsys.readouterr().err
    assert not enrollment.is_bound()


def test_a_code_without_words_prints_as_itself(monkeypatch, capsys):
    answer_with(monkeypatch, error=GatewayRefusedDetail(code="somebody_new", params={}))

    assert join_cli.main(LINK, is_forced=False) == 1

    assert "error: somebody_new" in capsys.readouterr().err
