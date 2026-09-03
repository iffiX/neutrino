"""The running service and the CLI share one binding file.

``nagent connect`` and ``nagent disconnect`` run in their own process, so the
service only stays truthful if it adopts what they wrote. These drive the
adoption path directly; nothing here talks to a network.
"""

import json

import pytest

import neutrino_agent.enrollment as enrollment
import neutrino_agent.http_channel as http_channel
from neutrino_agent.agent import Agent


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "agent.json"
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(path))
    return path


def bind(path, url="http://127.0.0.1:9") -> None:
    path.write_text(json.dumps({"gateway_url": url, "token": "tok"}))


def test_a_binding_written_by_another_process_is_adopted(config_path):
    agent = Agent(log=lambda message: None)
    assert agent._channel is None

    bind(config_path)
    agent._adopt_external_binding()

    assert agent._channel is not None


def test_a_binding_removed_by_another_process_is_let_go(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._desired = {"ai_tools": {"is_enabled": True}}
    agent._pending = {"ai_tools": {"is_enabled": False}}

    config_path.write_text(json.dumps({"device_id": "kept"}))
    agent._adopt_external_binding()

    assert agent._channel is None
    assert agent._desired == {}
    assert agent._pending == {}


def test_an_untouched_file_reloads_nothing(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    channel = agent._channel

    agent._adopt_external_binding()

    assert agent._channel is channel


def test_a_rewrite_of_the_same_binding_wipes_no_state(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._desired = {"ai_tools": {"is_enabled": True}}

    bind(config_path)
    agent._adopt_external_binding()

    assert agent._desired == {"ai_tools": {"is_enabled": True}}
    assert agent._channel is not None


def test_disconnect_leaves_the_service_unbound(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)

    agent.disconnect()

    assert agent._channel is None
    stored = json.loads(config_path.read_text())
    assert "gateway_url" not in stored and "token" not in stored
    agent._adopt_external_binding()
    assert agent._channel is None


def test_repeated_refusals_unbind_the_machine(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)

    def refuse(path, payload):
        raise http_channel.GatewayRefused("gateway refused this machine's token (401)")

    monkeypatch.setattr(agent._channel, "post", refuse)
    delays = [agent.run_once() for _ in range(3)]

    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert "no longer knows this machine" in agent.last_error()
    assert "fresh link" in agent.last_error()
    assert delays[-1] == 2


def test_a_single_refusal_keeps_the_binding(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)

    def refuse(path, payload):
        raise http_channel.GatewayRefused("gateway refused this machine's token (401)")

    monkeypatch.setattr(agent._channel, "post", refuse)
    agent.run_once()

    assert agent._channel is not None
    assert "gateway_url" in json.loads(config_path.read_text())


def answer_in_turn(agent, monkeypatch, answers):
    """Make the channel raise, or reply, one prepared answer per beat."""

    def answer(path, payload):
        outcome = answers.pop(0)
        if outcome is not None:
            raise outcome
        return {"desired_features": {}, "catalog_hash": ""}

    monkeypatch.setattr(agent._channel, "post", answer)


def test_mixed_rejection_kinds_total_to_an_unbind(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    answer_in_turn(
        agent,
        monkeypatch,
        [
            http_channel.GatewayRefused("gateway refused this machine's token (401)"),
            http_channel.GatewayUntrusted(
                "the gateway's certificate does not match the pinned fingerprint"
            ),
            http_channel.GatewayVersionRefused(
                hub_version="0.1.0", agent_version="0.2.0"
            ),
        ],
    )

    for _ in range(3):
        agent.run_once()

    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())
    # The reason names the rejection that tipped the counter.
    assert "newer than the hub" in agent.last_error()


def test_an_unreachable_beat_neither_counts_nor_resets(config_path, monkeypatch):
    """Only a successful beat resets the rejection counter; a broken wire in
    the middle of a run of rejections leaves the count standing."""
    bind(config_path)
    agent = Agent(log=lambda message: None)
    refused = "gateway refused this machine's token (401)"
    answer_in_turn(
        agent,
        monkeypatch,
        [
            http_channel.GatewayRefused(refused),
            http_channel.GatewayRefused(refused),
            http_channel.GatewayUnreachable("cannot reach gateway: timed out"),
            http_channel.GatewayRefused(refused),
        ],
    )

    for _ in range(3):
        agent.run_once()
    assert agent._channel is not None
    assert agent._refusals == 2

    agent.run_once()
    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())


def test_a_successful_beat_resets_the_rejection_count(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    refused = "gateway refused this machine's token (401)"
    answer_in_turn(
        agent,
        monkeypatch,
        [
            http_channel.GatewayRefused(refused),
            http_channel.GatewayRefused(refused),
            None,
            http_channel.GatewayRefused(refused),
        ],
    )

    for _ in range(4):
        agent.run_once()

    assert agent._channel is not None
    assert agent._refusals == 1
    assert "gateway_url" in json.loads(config_path.read_text())


def test_an_adopted_binding_starts_with_a_clean_count(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    refused = "gateway refused this machine's token (401)"
    answer_in_turn(
        agent,
        monkeypatch,
        [
            http_channel.GatewayRefused(refused),
            http_channel.GatewayRefused(refused),
        ],
    )
    for _ in range(2):
        agent.run_once()

    bind(config_path, url="http://127.0.0.1:10")
    agent._adopt_external_binding()

    assert agent._refusals == 0
