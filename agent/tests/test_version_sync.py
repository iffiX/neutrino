"""One version between hub and agent: refusal upward, self-update downward.

A hub that finds an agent newer than itself turns it away with a coded 409,
which the agent must never read as being let go; a hub that reports a later
version makes the agent pull the hub's baked package and install it in a
transient unit that outlives the process. Nothing here talks to a network:
the channel is replaced at the seam the agent uses it through.
"""

import base64
import hashlib
import json
import os
import subprocess

import pytest

import neutrino_agent.enrollment as enrollment
import neutrino_agent.self_update as self_update
from neutrino_agent import cli
from neutrino_agent.agent import Agent
from neutrino_agent.http_channel import GatewayVersionRefused

PACKAGE_BYTES = b"!<arch>agent-package"


class FakeChannel:
    """Answers heartbeats and hands out package bytes the way the hub would."""

    def __init__(self, hub_version: str, *, named_digest: str = ""):
        self.hub_version = hub_version
        self.named_digest = named_digest
        self.downloads = []

    def post(self, path, payload):
        return {
            "desired_features": {},
            "catalog_hash": "",
            "hub_version": self.hub_version,
        }

    def post_download(self, path, payload, destination):
        self.downloads.append((path, dict(payload), destination))
        with open(destination, "wb") as stream:
            stream.write(PACKAGE_BYTES)
        return self.named_digest or hashlib.sha256(PACKAGE_BYTES).hexdigest()


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "agent.json"
    monkeypatch.setattr(enrollment, "AGENT_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def launched(monkeypatch):
    """Recorded systemd-run invocations, with the real subprocess never hit."""
    commands = []

    def record(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(self_update.subprocess, "run", record)
    return commands


def bind(path, url="http://127.0.0.1:9") -> None:
    path.write_text(json.dumps({"gateway_url": url, "token": "tok"}))


def bound_agent(config_path, monkeypatch, *, hub_version, named_digest=""):
    bind(config_path)
    monkeypatch.setattr("neutrino_agent.agent.AGENT_VERSION", "1.0.0")
    monkeypatch.setattr(self_update, "package_kind", lambda platform: "deb")
    agent = Agent(log=discard)
    agent._channel = FakeChannel(hub_version, named_digest=named_digest)
    return agent


def link_for(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


def discard(message: str) -> None:
    """Swallow the agent's log lines."""


# --- a newer agent is refused, and never unbinds over it ---


def test_a_version_refusal_never_unbinds(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=discard)

    def refuse(path, payload):
        raise GatewayVersionRefused(hub_version="0.1.0", agent_version="0.2.0")

    monkeypatch.setattr(agent._channel, "post", refuse)
    delays = [agent.run_once() for _ in range(4)]

    assert agent._channel is not None
    assert agent._refusals == 0
    assert "gateway_url" in json.loads(config_path.read_text())
    assert "newer than the hub" in agent.last_error()
    # Backing off the way an unreachable hub does, not counting refusals.
    assert delays == [5, 10, 20, 40]


def test_connect_refuses_a_newer_agent_visibly(config_path, monkeypatch):
    def refuse(self, path, payload):
        raise GatewayVersionRefused(hub_version="0.1.0", agent_version="0.2.0")

    monkeypatch.setattr(enrollment.GatewayHttpChannel, "post", refuse)
    link = link_for({"urls": ["http://127.0.0.1:9"], "token": "ticket", "fp": ""})

    with pytest.raises(enrollment.EnrollmentError) as refusal:
        enrollment.enroll(link)

    assert "this agent (0.2.0) is newer than the hub (0.1.0)" in str(refusal.value)
    assert "update the hub first" in str(refusal.value)
    assert "gateway_url" not in enrollment.load_config()


def test_status_words_a_version_refusal_distinctly(config_path, monkeypatch, capsys):
    bind(config_path)

    class StuckAgent:
        def __init__(self, *, log):
            del log

        def run_once(self):
            return 5

        def last_error(self):
            return str(
                GatewayVersionRefused(hub_version="0.1.0", agent_version="0.2.0")
            )

    monkeypatch.setattr(cli, "Agent", StuckAgent)
    monkeypatch.setattr(cli, "_service_state", lambda: "running")

    assert cli._status() == 1
    out = capsys.readouterr().out
    assert "newer than the hub" in out
    assert "hub is updated" in out


# --- an older agent updates itself ---


def test_a_newer_hub_triggers_a_detached_install(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    agent.run_once()

    path, payload, destination = agent._channel.downloads[0]
    assert path == "/api/agent/package"
    assert payload == {"family": "deb"}
    assert launched == [
        [
            "systemd-run",
            "--unit",
            "neutrino_agent_update",
            "--collect",
            "--setenv=DEBIAN_FRONTEND=noninteractive",
            "apt-get",
            "install",
            "-y",
            "--allow-downgrades",
            destination,
        ]
    ]
    assert agent.last_error() == ""
    os.unlink(destination)


def test_a_digest_mismatch_installs_nothing(config_path, monkeypatch, launched):
    agent = bound_agent(
        config_path, monkeypatch, hub_version="9.9.9", named_digest="0" * 64
    )

    agent.run_once()

    assert launched == []
    assert "agent_package_digest_mismatch" in agent.last_error()
    # The refused download is not left on disk.
    assert not os.path.exists(agent._channel.downloads[0][2])


def test_a_failed_target_is_not_retried(config_path, monkeypatch, launched):
    agent = bound_agent(
        config_path, monkeypatch, hub_version="9.9.9", named_digest="0" * 64
    )

    agent.run_once()
    agent.run_once()

    assert len(agent._channel.downloads) == 1
    assert launched == []


def test_a_matching_version_is_left_alone(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="1.0.0")

    agent.run_once()

    assert agent._channel.downloads == []
    assert launched == []
    assert agent.last_error() == ""


def test_an_older_hub_is_not_downgraded_to(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="0.0.1")

    agent.run_once()

    assert agent._channel.downloads == []
    assert launched == []


def test_an_unparseable_hub_version_updates_nothing(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="wat")

    agent.run_once()

    assert agent._channel.downloads == []
    assert launched == []
    assert agent.last_error() == ""


def test_a_launch_failure_is_coded_and_cleaned_up(config_path, monkeypatch):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    def refuse_to_run(command, **kwargs):
        raise OSError("systemd-run is not here")

    monkeypatch.setattr(self_update.subprocess, "run", refuse_to_run)
    agent.run_once()

    assert "agent_update_launch_failed" in agent.last_error()
    assert not os.path.exists(agent._channel.downloads[0][2])


def test_the_rpm_command_uses_the_family_manager(monkeypatch):
    monkeypatch.setattr(
        self_update.shutil,
        "which",
        lambda name: "/usr/bin/dnf" if name == "dnf" else None,
    )

    command = self_update.install_command("rpm", "/tmp/hub.rpm")

    assert command == [
        "systemd-run",
        "--unit",
        "neutrino_agent_update",
        "--collect",
        "dnf",
        "install",
        "-y",
        "/tmp/hub.rpm",
    ]
