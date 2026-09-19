"""Self-update downward: the package down a stream, verified, installed detached.

A hub whose welcome names a later ``software`` makes the agent open a
``package {}`` stream, take the bytes into its package directory, check the
digest the close named, and install the file in a transient unit that
outlives the process. Nothing here talks to a network: the socket is
scripted, and the hub's side of the stream is played by it. The script the
transient unit runs is run for real against package managers stubbed onto
PATH, since what it writes is what the panel reads back.
"""

import functools
import hashlib
import json
import os
import subprocess

import pytest

import neutrino_agent.core.loop as loop_module
import neutrino_agent.core.self_update as self_update
from neutrino_agent.constants import (
    AGENT_REINSTALL_OUTPUT_LIMIT_BYTES,
    AGENT_WS_STREAM_CREDIT_BYTES,
    AGENT_WS_STREAM_ID_BYTES,
)
from neutrino_agent.exceptions import GatewayUnreachable, SelfUpdateError
from neutrino_agent.core.loop import Agent
from tests.conftest import bind, discard
from tests.core.test_loop import DROP_AFTER_REPORT, WELCOME, ClientScript
from tests.core.test_session import ScriptedClient
from tests.streams.fake_channel import FakeChannel

PACKAGE_BYTES = b"!<arch>agent-package"
PACKAGE_OPEN = {"type": "open", "stream": 1, "kind": "package"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PackageHub(ScriptedClient):
    """A scripted socket whose hub answers ``package {}`` with its bytes.

    The bytes go down in two binary frames, then the close names the
    digest; each knob below changes one thing about that answer.
    """

    def __init__(
        self,
        *,
        named_digest: str = "",
        has_digest: bool = True,
        is_dropped: bool = False,
        refusal: str = "",
    ):
        super().__init__()
        self.named_digest = named_digest
        self.has_digest = has_digest
        self.is_dropped = is_dropped
        self.refusal = refusal
        self.opened: list = []

    def send_text(self, text: str) -> None:
        super().send_text(text)
        message = json.loads(text)
        if message.get("type") == "open" and message.get("kind") == "package":
            self.opened.append(message)
            self._answer(message["stream"])

    def _answer(self, stream: int) -> None:
        if self.refusal:
            self.feed(
                {"type": "close", "stream": stream, "code": self.refusal, "params": {}}
            )
            return
        prefix = stream.to_bytes(AGENT_WS_STREAM_ID_BYTES, "big")
        self.feed(prefix + PACKAGE_BYTES[:7])
        if self.is_dropped:
            self.feed(GatewayUnreachable("hung up mid-transfer"))
            return
        self.feed(prefix + PACKAGE_BYTES[7:])
        params = {}
        if self.has_digest:
            params["sha256"] = self.named_digest or sha256(PACKAGE_BYTES)
        self.feed({"type": "close", "stream": stream, "code": "", "params": params})


@pytest.fixture
def launched(monkeypatch):
    """Recorded systemd-run invocations, with the real subprocess never hit."""
    commands = []

    # Every run in the agent captures text, so the stand-in answers with
    # empty text: the metrics read that reaches nvidia-smi on a box with a
    # card parses what comes back.
    def record(command, **kwargs):
        if list(command[:1]) == ["systemd-run"]:
            commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(self_update.subprocess, "run", record)
    return commands


def welcomed_by(hub_version: str) -> list:
    return [dict(WELCOME, software=f"neutrino_hub/{hub_version}"), DROP_AFTER_REPORT]


def bound_agent(config_path, monkeypatch, *, hub_version, **hub):
    """An agent whose every connection is welcomed by a hub of one version,
    and whose package stream that hub answers as the knobs say."""
    bind(config_path)
    monkeypatch.setattr("neutrino_agent.core.loop.AGENT_VERSION", "1.0.0")
    monkeypatch.setattr(self_update, "package_kind", lambda platform: "deb")
    script = ClientScript([], default=welcomed_by(hub_version))
    script.client_class = functools.partial(PackageHub, **hub)
    monkeypatch.setattr(loop_module, "WebSocketClient", script)
    agent = Agent(log=discard)
    agent._script = script
    return agent


def opened(agent) -> list:
    """Every package open sent, across every connection."""
    return [message for client in agent._script.clients for message in client.opened]


def landed(tmp_path) -> list:
    directory = tmp_path / "packages"
    return sorted(os.listdir(directory)) if directory.is_dir() else []


def test_a_newer_hub_takes_the_package_down_a_stream_and_installs_it_detached(
    config_path, monkeypatch, launched, tmp_path
):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    agent.run_once()

    assert opened(agent) == [PACKAGE_OPEN]
    (name,) = landed(tmp_path)
    path = str(tmp_path / "packages" / name)
    assert (tmp_path / "packages" / name).read_bytes() == PACKAGE_BYTES
    launched_command = launched[0]
    assert launched_command[:4] == [
        "systemd-run",
        "--unit",
        "neutrino_agent_update",
        "--collect",
    ]
    assert launched_command[4] == "--setenv=DEBIAN_FRONTEND=noninteractive"
    assert launched_command[5:7] == ["sh", "-c"]
    assert f"dpkg -i {path}" in launched_command[7]
    assert "apt-get -f install -y" in launched_command[7]
    assert agent._update_error is None


def test_credit_is_offered_at_the_open_and_again_as_each_piece_lands(
    config_path, monkeypatch, launched
):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    agent.run_once()

    credits = agent._script.clients[0].frames("credit")
    assert [credit["stream"] for credit in credits] == [1, 1, 1]
    assert [credit["bytes"] for credit in credits] == [
        AGENT_WS_STREAM_CREDIT_BYTES,
        7,
        len(PACKAGE_BYTES) - 7,
    ]


def test_the_package_lands_in_the_agents_own_directory_root_only(
    config_path, monkeypatch, launched, tmp_path
):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    agent.run_once()

    assert (os.stat(tmp_path / "packages").st_mode & 0o777) == 0o700
    assert len(landed(tmp_path)) == 1


def test_a_digest_mismatch_installs_nothing_and_leaves_no_file(
    config_path, monkeypatch, launched, tmp_path
):
    agent = bound_agent(
        config_path, monkeypatch, hub_version="9.9.9", named_digest="0" * 64
    )

    agent.run_once()

    assert launched == []
    assert agent._update_error == {
        "code": "agent_package_digest_mismatch",
        "params": {"target": "9.9.9"},
    }
    assert landed(tmp_path) == []


def test_a_failed_target_is_not_retried(config_path, monkeypatch, launched):
    agent = bound_agent(
        config_path, monkeypatch, hub_version="9.9.9", named_digest="0" * 64
    )

    agent.run_once()
    agent.run_once()

    assert len(opened(agent)) == 1
    assert launched == []


def test_a_socket_dropped_mid_transfer_leaves_no_file_and_locks_no_target(
    config_path, monkeypatch, launched, tmp_path
):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9", is_dropped=True)

    agent.run_once()

    assert launched == []
    assert landed(tmp_path) == []
    assert agent._update_target == ""
    assert agent._update_error == {
        "code": "hub_unreachable",
        "params": {"target": "9.9.9"},
    }

    agent.run_once()

    assert len(opened(agent)) == 2


def test_a_close_that_names_no_digest_is_a_dropped_transfer(
    config_path, monkeypatch, launched, tmp_path
):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9", has_digest=False)

    agent.run_once()
    agent.run_once()

    assert launched == []
    assert landed(tmp_path) == []
    assert len(opened(agent)) == 2


def test_a_hub_that_refuses_the_package_is_coded_and_latched(
    config_path, monkeypatch, launched, tmp_path
):
    agent = bound_agent(
        config_path, monkeypatch, hub_version="9.9.9", refusal="agent_package_missing"
    )

    agent.run_once()
    agent.run_once()

    assert launched == []
    assert landed(tmp_path) == []
    assert len(opened(agent)) == 1
    assert agent._update_error == {
        "code": "agent_package_missing",
        "params": {"target": "9.9.9"},
    }


def test_a_matching_version_is_left_alone(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="1.0.0")

    agent.run_once()

    assert opened(agent) == []
    assert launched == []
    assert agent._update_error is None


def test_an_older_hub_is_not_downgraded_to(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="0.0.1")

    agent.run_once()

    assert opened(agent) == []
    assert launched == []


def test_an_unparseable_hub_version_updates_nothing(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="wat")

    agent.run_once()

    assert opened(agent) == []
    assert launched == []
    assert agent._update_error is None


def test_a_launch_failure_is_coded_and_cleaned_up(config_path, monkeypatch, tmp_path):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    def refuse_to_run(command, **kwargs):
        raise OSError("systemd-run is not here")

    monkeypatch.setattr(self_update.subprocess, "run", refuse_to_run)
    agent.run_once()

    assert agent._update_error == {
        "code": "agent_update_launch_failed",
        "params": {"target": "9.9.9"},
    }
    assert landed(tmp_path) == []


def test_a_new_target_version_after_a_failure_is_tried(
    config_path, monkeypatch, launched
):
    agent = bound_agent(
        config_path, monkeypatch, hub_version="9.9.9", named_digest="0" * 64
    )

    agent.run_once()
    agent._script.default = welcomed_by("9.9.10")
    agent._script.client_class = PackageHub
    agent.run_once()

    assert len(opened(agent)) == 2
    assert len(launched) == 1
    assert agent._update_error is None


def test_a_successful_target_is_not_relaunched(config_path, monkeypatch, launched):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")

    agent.run_once()
    agent.run_once()

    assert len(opened(agent)) == 1
    assert len(launched) == 1


# --- the stream's outcome, as the update reads it ---


def stream_outcome(tmp_path, chunks, close):
    channel = FakeChannel(stream_id=1)
    for chunk in chunks:
        channel.feed(("data", chunk))
    channel.feed(("close", close[0], close[1]))
    return self_update.receive_package(channel, directory=str(tmp_path / "packages"))


def test_receive_package_hands_over_the_file_the_close_vouches_for(tmp_path):
    path = stream_outcome(
        tmp_path, [PACKAGE_BYTES], ("", {"sha256": sha256(PACKAGE_BYTES)})
    )

    assert path.startswith(str(tmp_path / "packages"))
    with open(path, "rb") as stream:
        assert stream.read() == PACKAGE_BYTES


def test_receive_package_names_a_mismatch_with_the_agents_own_code(tmp_path):
    with pytest.raises(SelfUpdateError) as caught:
        stream_outcome(tmp_path, [PACKAGE_BYTES], ("", {"sha256": "0" * 64}))

    assert str(caught.value) == "agent_package_digest_mismatch"
    assert landed(tmp_path) == []


def test_receive_package_passes_the_hubs_refusal_through(tmp_path):
    with pytest.raises(SelfUpdateError) as caught:
        stream_outcome(tmp_path, [], ("agent_package_missing", {}))

    assert str(caught.value) == "agent_package_missing"


def test_receive_package_raises_unreachable_for_a_stream_that_ended_early(tmp_path):
    with pytest.raises(GatewayUnreachable):
        stream_outcome(tmp_path, [PACKAGE_BYTES[:3]], ("", {}))

    assert landed(tmp_path) == []


def test_the_rpm_command_falls_back_to_yum_without_dnf(monkeypatch):
    monkeypatch.setattr(self_update.shutil, "which", lambda name: None)

    command = self_update.install_command("rpm", "/tmp/hub.rpm", data_dir="/etc/agent")

    assert "yum reinstall -y /tmp/hub.rpm" in command[6]
    assert "yum install -y /tmp/hub.rpm" in command[6]


def test_the_rpm_command_uses_the_family_manager(monkeypatch):
    monkeypatch.setattr(
        self_update.shutil,
        "which",
        lambda name: "/usr/bin/dnf" if name == "dnf" else None,
    )

    command = self_update.install_command("rpm", "/tmp/hub.rpm", data_dir="/etc/agent")

    assert command[:4] == [
        "systemd-run",
        "--unit",
        "neutrino_agent_update",
        "--collect",
    ]
    assert command[4:6] == ["sh", "-c"]
    assert "dnf reinstall -y /tmp/hub.rpm" in command[6]
    assert "dnf install -y /tmp/hub.rpm" in command[6]


def test_the_family_names_the_package_kind():
    assert self_update.package_kind({"os": "linux", "family": "debian"}) == "deb"
    assert self_update.package_kind({"os": "linux", "family": "rhel"}) == "rpm"
    assert self_update.package_kind({"os": "linux", "family": ""}) == ""


# --- what the transient unit writes about the install ---


def stub_manager(bin_dir, name: str, *, body: str) -> None:
    """One package manager on PATH, saying and exiting what a test wants.

    Args:
        bin_dir: The directory put first on PATH.
        name: The program's name.
        body: The shell body it runs.
    """
    program = bin_dir / name
    program.write_text("#!/bin/sh\n" + body + "\n")
    program.chmod(0o755)


def run_unit(tmp_path, *, kind: str = "deb", package: str = "hub.deb") -> str:
    """Run the script the unit would run, with the managers stubbed.

    Args:
        tmp_path: The test's directory, which is also the agent's data dir.
        kind: ``deb`` or ``rpm``.
        package: The package file's name.

    Returns:
        What the result file holds, unparsed.
    """
    bin_dir = tmp_path / "bin"
    command = self_update.install_command(
        kind, str(tmp_path / package), data_dir=str(tmp_path)
    )
    environment = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    subprocess.run(["sh", "-c", command[-1]], capture_output=True, env=environment)
    return (tmp_path / "reinstall.json").read_text()


@pytest.fixture
def stubbed(tmp_path):
    """A PATH whose package managers are this test's own."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return bin_dir


def test_the_unit_writes_what_the_install_said_and_how_it_exited(tmp_path, stubbed):
    stub_manager(stubbed, "dpkg", body='echo "Setting up neutrino-agent"')

    written = json.loads(run_unit(tmp_path))

    assert written["package"] == "hub.deb"
    assert written["kind"] == "deb"
    assert written["exit_code"] == 0
    assert written["output"] == "Setting up neutrino-agent\n"
    assert written["started_at"].endswith("Z")
    assert written["finished_at"].endswith("Z")


def test_the_unit_leaves_the_log_and_the_result_root_only(tmp_path, stubbed):
    stub_manager(stubbed, "dpkg", body="echo done")

    run_unit(tmp_path)

    assert (tmp_path / "reinstall.log").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "reinstall.json").stat().st_mode & 0o777 == 0o600


def test_a_failed_install_carries_its_exit_status_and_both_attempts(tmp_path, stubbed):
    stub_manager(stubbed, "dpkg", body='echo "dpkg: dependency problems"; exit 1')
    stub_manager(stubbed, "apt-get", body='echo "fixing"')

    written = json.loads(run_unit(tmp_path))

    assert written["exit_code"] == 1
    assert written["output"].count("dpkg: dependency problems") == 2
    assert "fixing" in written["output"]


def test_the_rpm_unit_writes_the_same_shape(tmp_path, stubbed, monkeypatch):
    monkeypatch.setattr(self_update.shutil, "which", lambda name: None)
    stub_manager(stubbed, "yum", body='echo "Reinstalled"')

    written = json.loads(run_unit(tmp_path, kind="rpm", package="hub.rpm"))

    assert written["kind"] == "rpm"
    assert written["package"] == "hub.rpm"
    assert written["exit_code"] == 0


def test_the_result_carries_only_the_tail_of_a_long_log(tmp_path, stubbed):
    stub_manager(
        stubbed,
        "dpkg",
        body="i=0; while [ $i -lt 400 ]; do "
        "echo 0123456789012345678901234567890123456789; i=$((i+1)); done",
    )

    written = json.loads(run_unit(tmp_path))

    assert len(written["output"]) <= AGENT_REINSTALL_OUTPUT_LIMIT_BYTES
    assert written["output"].endswith("0123456789\n")


def test_output_a_shell_would_choke_on_stays_readable_json(tmp_path, stubbed):
    stub_manager(
        stubbed, "dpkg", body=r"""printf 'a "quote" and a \\ and a\ttab\r\n'"""
    )

    written = json.loads(run_unit(tmp_path))

    assert written["output"] == 'a "quote" and a \\ and a tab\n'


def test_the_result_reads_back_in_the_shape_the_hub_is_given(tmp_path, stubbed):
    stub_manager(stubbed, "dpkg", body="echo done")
    run_unit(tmp_path)

    read = self_update.read_reinstall_result(str(tmp_path))

    assert set(read) == {
        "package",
        "kind",
        "started_at",
        "finished_at",
        "exit_code",
        "output",
    }
    assert read["exit_code"] == 0


def test_no_result_file_reads_as_nothing(tmp_path):
    assert self_update.read_reinstall_result(str(tmp_path)) is None


@pytest.mark.parametrize("written", ["not json", "[]", '{"exit_code": "wat"}'])
def test_a_result_that_cannot_be_read_is_nothing(tmp_path, written):
    (tmp_path / "reinstall.json").write_text(written)

    assert self_update.read_reinstall_result(str(tmp_path)) is None


def test_a_launch_drops_the_result_of_the_reinstall_before_it(
    config_path, monkeypatch, launched, tmp_path
):
    agent = bound_agent(config_path, monkeypatch, hub_version="9.9.9")
    stale = tmp_path / "reinstall.json"
    stale.write_text(json.dumps({"exit_code": 0}))

    agent.run_once()

    assert not stale.exists()
    assert len(launched) == 1
