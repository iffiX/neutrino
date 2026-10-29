"""``nagent join``: joining a hub, and every way the join is refused.

The walk is the operator's: a link on the command line or pasted at the
prompt, an existing binding that is kept unless the answer is yes, and each
refusal the hub can give worded on the way out. Nothing here reaches a
network; the one ``join`` goes to a transport the test plays.
"""

import io

import pytest

import neutrino_agent.cli.entry as entry
import neutrino_agent.cli.join as join_cli
import neutrino_agent.core.enrollment as enrollment
import neutrino_agent.core.loop as loop_module
from tests.conftest import HUB_KEY, bind, link_for
from tests.transport.fake_transport import FakeTransport, one_shot_for

GATEWAY_URL = "tcp://192.0.2.5:8443"
OLD_GATEWAY_URL = "tcp://192.0.2.6:8443"
NAME_URL = "tcp://hub.neutrino.internal:8443"
LINK = link_for(
    {"urls": [GATEWAY_URL], "token": "ticket", "key": HUB_KEY, "role": "agent"}
)


@pytest.fixture
def fake(monkeypatch):
    """The transport ``nagent join`` starts in its own process, played here."""
    transport = FakeTransport()
    opener = one_shot_for(transport)
    monkeypatch.setattr(
        loop_module,
        "one_shot_transport",
        lambda platform, log=None, **keywords: opener(**keywords),
    )
    yield transport
    transport.close()


def answer_with(fake, *, answer=None):
    """What the hub answers the one join this walk makes.

    Returns:
        The list the joins land in.
    """
    fake.answers["join"] = (
        answer
        if answer is not None
        else {"binding_id": "3f9c", "token": "device-token"}
    )
    return fake.commands


def running_service_word() -> str:
    """The service already runs, so the join starts nothing."""
    return "running"


def refuse_to_ask(prompt: str) -> str:
    """Fail the test rather than prompt where no prompt is allowed."""
    raise AssertionError(f"join asked: {prompt}")


@pytest.fixture
def joined_hub(monkeypatch, fake):
    """A hub that accepts the join and a service already running."""
    monkeypatch.setattr(join_cli, "service_state", running_service_word)
    return answer_with(fake)


def test_a_fresh_join_stores_the_binding_and_names_the_hub(joined_hub, capsys):
    assert join_cli.main(LINK, is_forced=False) == 0

    assert f"joined {GATEWAY_URL} as 3f9c" in capsys.readouterr().out
    stored = enrollment.load_binding()
    assert stored["gateway_url"] == GATEWAY_URL
    assert stored["id"] == "3f9c"
    assert stored["token"] == "device-token"
    assert stored["hub_key"] == HUB_KEY


def test_the_agents_own_log_stays_out_of_the_terminal(monkeypatch, capsys, fake):
    opener = one_shot_for(fake)

    def logging_one_shot(platform, log=print, **keywords):
        log("transport: hub transport started")
        log("transport: control_connected")
        return opener(**keywords)

    monkeypatch.setattr(loop_module, "one_shot_transport", logging_one_shot)
    monkeypatch.setattr(join_cli, "service_state", running_service_word)
    answer_with(fake)

    assert join_cli.main(LINK, is_forced=False) == 0

    assert capsys.readouterr().out.splitlines() == [f"joined {GATEWAY_URL} as 3f9c"]


def test_the_join_carries_the_seven_fields_the_key_and_the_addresses(joined_hub):
    join_cli.main(LINK, is_forced=False)

    (join,) = joined_hub
    assert join["command"] == "join"
    assert join["addresses"] == [NAME_URL, GATEWAY_URL]
    assert join["hub_key"] == HUB_KEY
    assert {
        "ticket",
        "role",
        "protocol",
        "machine_id",
        "name",
        "software",
        "platform",
    } <= set(join)
    assert join["role"] == "agent"


def test_an_existing_binding_is_kept_when_the_prompt_is_declined(
    terminal, monkeypatch, config_path, capsys, fake
):
    bind(config_path, url=OLD_GATEWAY_URL)
    asked = []

    def answer_no(prompt):
        asked.append(prompt)
        return "n"

    monkeypatch.setattr("builtins.input", answer_no)
    posted = answer_with(fake)

    assert join_cli.main(LINK, is_forced=False) == 1

    assert asked == [f"this machine is bound to {OLD_GATEWAY_URL}; replace it? [y/N] "]
    assert "nothing changed" in capsys.readouterr().out
    assert posted == []
    assert enrollment.load_binding()["gateway_url"] == OLD_GATEWAY_URL


def test_with_no_terminal_an_existing_binding_is_kept_and_yes_is_named(
    monkeypatch, config_path, capsys, fake
):
    bind(config_path, url=OLD_GATEWAY_URL)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr("builtins.input", refuse_to_ask)
    posted = answer_with(fake)

    assert join_cli.main(LINK, is_forced=False) == 1

    assert "--yes" in capsys.readouterr().err
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


def test_an_empty_prompt_gives_up_in_words(monkeypatch, capsys, fake):
    def paste_nothing(prompt):
        return "   "

    monkeypatch.setattr(join_cli, "input", paste_nothing, raising=False)
    posted = answer_with(fake)

    assert join_cli.main("", is_forced=False) == 1

    assert "error: no link was given" in capsys.readouterr().err
    assert posted == []


def test_a_garbage_link_is_refused_in_words(monkeypatch, capsys, fake):
    posted = answer_with(fake)

    assert join_cli.main("not-a-link", is_forced=False) == 1

    err = capsys.readouterr().err
    assert "error: that is not an enrollment link; copy the whole line from " in err
    assert "the hub's Agents page" in err
    assert posted == []
    assert not enrollment.is_bound()


def test_a_client_link_is_refused_in_words(monkeypatch, capsys, fake):
    posted = answer_with(fake)
    link = link_for({"urls": [GATEWAY_URL], "token": "ticket", "role": "client"})

    assert join_cli.main(link, is_forced=False) == 1

    assert "error: that link is for a client, not for a device" in (
        capsys.readouterr().err
    )
    assert posted == []
    assert not enrollment.is_bound()


def test_a_spent_ticket_is_worded_as_one(monkeypatch, capsys, fake):
    answer_with(fake, answer={"code": "ticket_spent", "params": {}})

    assert join_cli.main(LINK, is_forced=False) == 1

    err = capsys.readouterr().err
    assert "error: the hub refused this link; it may have expired" in err
    assert "generate a fresh one on the Agents page" in err
    assert not enrollment.is_bound()


def test_an_answer_off_the_links_key_is_worded_as_one(monkeypatch, capsys, fake):
    answer_with(fake, answer={"code": "hub_untrusted", "params": {}})

    assert join_cli.main(LINK, is_forced=False) == 1

    assert "error: what answers is not the hub" in capsys.readouterr().err
    assert not enrollment.is_bound()


def test_no_transport_is_worded_as_one(monkeypatch, capsys):
    def refuse(platform, log=None, **keywords):
        raise OSError("no neutrino_transport here")

    monkeypatch.setattr(loop_module, "one_shot_transport", refuse)

    assert join_cli.main(LINK, is_forced=False) == 1

    assert "the transport could not start" in capsys.readouterr().err


@pytest.mark.parametrize(
    "code, params, words",
    [
        (
            "protocol_too_new",
            {"peer": 5, "hub": 4, "min": 4},
            "this agent speaks protocol 5; the hub speaks 4, so update the hub first",
        ),
        (
            "protocol_too_old",
            {"peer": 3, "hub": 4, "min": 4},
            "this agent speaks protocol 3; the hub accepts 4 and up, "
            "so update this agent",
        ),
    ],
)
def test_a_protocol_refusal_names_both_numbers(
    monkeypatch, capsys, code, params, words, fake
):
    answer_with(fake, answer={"code": code, "params": params})

    assert join_cli.main(LINK, is_forced=False) == 1

    assert f"error: {words}" in capsys.readouterr().err
    assert not enrollment.is_bound()


def test_a_code_without_words_prints_as_itself(monkeypatch, capsys, fake):
    answer_with(fake, answer={"code": "somebody_new", "params": {}})

    assert join_cli.main(LINK, is_forced=False) == 1

    assert "error: somebody_new" in capsys.readouterr().err
