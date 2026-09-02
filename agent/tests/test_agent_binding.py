"""The running service and the CLI share one binding file.

``nagent connect`` and ``nagent disconnect`` run in their own process, so the
service only stays truthful if it adopts what they wrote. These drive the
adoption path directly; nothing here talks to a network.
"""

import json

import pytest

import neutrino_agent.enrollment as enrollment
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
