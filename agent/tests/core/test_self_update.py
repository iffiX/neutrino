"""Self-update downward: the hub's baked package, verified, installed detached.

A hub that reports a later version makes the agent pull the hub's baked
package and install it in a transient unit that outlives the process.
Nothing here talks to a network: the channel is replaced at the seam the
agent uses it through.
"""

import hashlib
import os
import subprocess

import pytest

import neutrino_agent.core.self_update as self_update
from neutrino_agent.core.channel import GatewayUnreachable
from neutrino_agent.core.loop import Agent
from tests.conftest import bind, discard

PACKAGE_BYTES = b"!<arch>agent-package"


class FakeChannel:
    """Answers heartbeats and hands out package bytes the way the hub would."""

    def __init__(self, hub_version: str, *, named_digest: str = "", has_checksum=True):
        self.hub_version = hub_version
        self.named_digest = named_digest
        self.has_checksum = has_checksum
        self.downloads = []

    def post(self, path, payload):
        return {
            "module_orders": [],
            "catalog_hash": "",
            "hub_version": self.hub_version,
        }

    def post_download(self, path, payload, destination):
        self.downloads.append((path, dict(payload), destination))
        with open(destination, "wb") as stream:
            stream.write(PACKAGE_BYTES)
        if not self.has_checksum:
            return ""
        return self.named_digest or hashlib.sha256(PACKAGE_BYTES).hexdigest()


class UnreachableDownloadChannel(FakeChannel):
    """Beats fine, but the package fetch never comes back."""

    def post_download(self, path, payload, destination):
        self.downloads.append((path, dict(payload), destination))
        raise GatewayUnreachable("cannot reach gateway: gone")


@pytest.fixture
def launched(monkeypatch):
    """Recorded systemd-run invocations, with the real subprocess never hit."""
    commands = []

    def record(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(self_update.subprocess, "run", record)
    return commands


def bound_agent(config_path, monkeypatch, *, hub_version, named_digest=""):
    bind(config_path)
    monkeypatch.setattr("neutrino_agent.core.loop.AGENT_VERSION", "1.0.0")
    monkeypatch.setattr(self_update, "package_kind", lambda platform: "deb")
    agent = Agent(log=discard)
    agent._channel = FakeChannel(hub_version, named_digest=named_digest)
    return agent


def test_a_newer_hub_triggers_a_detached_install(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    agent.run_once()

    path, payload, destination = agent._channel.downloads[0]
    assert path == "/api/agent/package"
    assert payload == {"family": "deb"}
    launched_command = launched[0]
    assert launched_command[:4] == [
        "systemd-run",
        "--unit",
        "neutrino_agent_update",
        "--collect",
    ]
    assert launched_command[4] == "--setenv=DEBIAN_FRONTEND=noninteractive"
    assert launched_command[5:7] == ["sh", "-c"]
    assert f"dpkg -i {destination}" in launched_command[7]
    assert "apt-get -f install -y" in launched_command[7]
    assert agent.last_error() is None
    os.unlink(destination)


def test_a_digest_mismatch_installs_nothing(config_path, monkeypatch, launched):
    agent = bound_agent(
        config_path, monkeypatch, hub_version="9.9.9", named_digest="0" * 64
    )

    agent.run_once()

    assert launched == []
    assert agent.last_error() == {
        "code": "agent_package_digest_mismatch",
        "params": {"target": "9.9.9"},
    }
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
    assert agent.last_error() is None


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
    assert agent.last_error() is None


def test_a_launch_failure_is_coded_and_cleaned_up(config_path, monkeypatch):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    def refuse_to_run(command, **kwargs):
        raise OSError("systemd-run is not here")

    monkeypatch.setattr(self_update.subprocess, "run", refuse_to_run)
    agent.run_once()

    assert agent.last_error() == {
        "code": "agent_update_launch_failed",
        "params": {"target": "9.9.9"},
    }
    assert not os.path.exists(agent._channel.downloads[0][2])


def test_a_missing_checksum_header_refuses_the_install(
    config_path, monkeypatch, launched
):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")
    agent._channel.has_checksum = False

    agent.run_once()

    assert launched == []
    assert agent.last_error() == {
        "code": "agent_package_digest_mismatch",
        "params": {"target": "9.9.9"},
    }
    assert not os.path.exists(agent._channel.downloads[0][2])


def test_a_new_target_version_after_a_failure_is_tried(
    config_path, monkeypatch, launched
):
    agent = bound_agent(
        config_path, monkeypatch, hub_version="9.9.9", named_digest="0" * 64
    )

    agent.run_once()
    agent._channel.hub_version = "9.9.10"
    agent._channel.named_digest = ""
    agent.run_once()

    assert len(agent._channel.downloads) == 2
    assert len(launched) == 1
    assert agent.last_error() is None
    os.unlink(agent._channel.downloads[1][2])


def test_a_successful_target_is_not_relaunched(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    agent.run_once()
    agent.run_once()

    assert len(agent._channel.downloads) == 1
    assert len(launched) == 1
    os.unlink(agent._channel.downloads[0][2])


def test_a_fetch_failure_is_coded_and_latched(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")
    agent._channel = UnreachableDownloadChannel("9.9.9")

    agent.run_once()
    agent.run_once()

    assert launched == []
    assert agent.last_error() == {
        "code": "hub_unreachable",
        "params": {"target": "9.9.9"},
    }
    assert len(agent._channel.downloads) == 1
    assert not os.path.exists(agent._channel.downloads[0][2])


def test_the_rpm_command_falls_back_to_yum_without_dnf(monkeypatch):
    monkeypatch.setattr(self_update.shutil, "which", lambda name: None)

    command = self_update.install_command("rpm", "/tmp/hub.rpm")

    assert "yum reinstall -y /tmp/hub.rpm" in command[6]
    assert "yum install -y /tmp/hub.rpm" in command[6]


def test_the_rpm_command_uses_the_family_manager(monkeypatch):
    monkeypatch.setattr(
        self_update.shutil,
        "which",
        lambda name: "/usr/bin/dnf" if name == "dnf" else None,
    )

    command = self_update.install_command("rpm", "/tmp/hub.rpm")

    assert command[:4] == [
        "systemd-run",
        "--unit",
        "neutrino_agent_update",
        "--collect",
    ]
    assert command[4:6] == ["sh", "-c"]
    assert "dnf reinstall -y /tmp/hub.rpm" in command[6]
    assert "dnf install -y /tmp/hub.rpm" in command[6]


def test_windows_names_the_msi_kind():
    assert self_update.package_kind({"os": "windows", "family": ""}) == "msi"
    assert self_update.package_kind({"os": "linux", "family": "debian"}) == "deb"
    assert self_update.package_kind({"os": "linux", "family": "rhel"}) == "rpm"
    assert self_update.package_kind({"os": "linux", "family": ""}) == ""
    assert self_update.package_kind({"os": "darwin", "family": ""}) == ""


def test_the_msi_command_is_a_detached_msiexec():
    command = self_update.install_command("msi", "C:\\tmp\\hub.msi")

    assert command[0] == "powershell"
    assert "Start-Process msiexec" in command[-1]
    assert "'/quiet'" in command[-1] and "'/norestart'" in command[-1]
    assert "systemd-run" not in command
