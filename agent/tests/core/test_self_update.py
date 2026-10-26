"""Self-update downward: the package down a stream, verified, installed detached.

A hub whose welcome names a later ``software`` makes the agent open a
``package {}`` stream, take the bytes into its package directory, check the
digest the close named, and install the file in a transient unit that
outlives the process. Nothing here talks to a network: the transport is
played by a test, and the hub's side of the stream with it. The script the
transient unit runs is run for real from its file, against package managers
stubbed onto PATH and an agent program stubbed in place of the installed
one, since what it writes is what the panel reads back.
"""

import functools
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import neutrino_agent.core.loop as loop_module
import neutrino_agent.core.self_update as self_update
from neutrino_agent.constants import AGENT_REINSTALL_OUTPUT_LIMIT_BYTES
from neutrino_agent.exceptions import GatewayUnreachable, SelfUpdateError
from neutrino_agent.core.loop import Agent
from neutrino_agent.transport.records import encode_close, encode_record
from tests.conftest import bind, discard
from tests.streams.fake_channel import FakeChannel
from tests.transport.fake_transport import FakeTransport, starter_for

PACKAGE_BYTES = b"!<arch>agent-package"
PACKAGE_OPEN = {"kind": "package"}
GOLDEN = Path(__file__).parent / "golden"
GOLDEN_STATE = "C:\\ProgramData\\Neutrino\\agent\\state"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PackageHub:
    """The hub's answer to ``package {}``: its bytes in two records, then the
    close naming the digest; each knob changes one thing about it."""

    def __init__(
        self,
        *,
        named_digest: str = "",
        has_digest: bool = True,
        is_dropped: bool = False,
        refusal: str = "",
    ):
        self.named_digest = named_digest
        self.has_digest = has_digest
        self.is_dropped = is_dropped
        self.refusal = refusal

    def __call__(self, connection) -> None:
        if self.refusal:
            connection.write(encode_close(self.refusal, {}))
            return
        connection.write(encode_record(2) + encode_record(3, PACKAGE_BYTES[:7]))
        if self.is_dropped:
            connection.close()
            return
        connection.write(encode_record(3, PACKAGE_BYTES[7:]))
        params = {}
        if self.has_digest:
            params["sha256"] = self.named_digest or sha256(PACKAGE_BYTES)
        connection.write(encode_close("", params))


@pytest.fixture
def fake():
    transport = FakeTransport()
    yield transport
    transport.close()


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


def bound_agent(config_path, monkeypatch, fake, *, hub_version, **hub):
    """An agent whose every session is welcomed by a hub of one version, and
    whose package stream that hub answers as the knobs say."""
    bind(config_path)
    monkeypatch.setattr("neutrino_agent.core.loop.AGENT_VERSION", "1.0.0")
    monkeypatch.setattr(self_update, "package_kind", lambda platform: "deb")
    fake.on_open = PackageHub(**hub)
    agent = Agent(log=discard, transport_starter=starter_for(fake))
    agent._fake = fake
    agent._hub_version = hub_version
    return agent


def connect(agent) -> None:
    """One session: opened, welcomed, its first report sent and the update it asks for."""
    fake = agent._fake
    if agent.is_online():
        fake.send_event("session_end", code="", params={})
        fake.wait_for(lambda: not agent.is_online())
    agent.run_once()
    fake.welcome(software=f"neutrino_hub/{agent._hub_version}")
    fake.wait_for(agent.is_online)
    agent.run_once()


def opened(agent) -> list:
    """Every package open sent, across every session."""
    return [connection.first["open"] for connection in agent._fake.opened]


def landed(tmp_path) -> list:
    directory = tmp_path / "packages"
    return sorted(os.listdir(directory)) if directory.is_dir() else []


def test_a_newer_hub_takes_the_package_down_a_stream_and_installs_it_detached(
    config_path, monkeypatch, launched, fake, tmp_path
):
    agent = bound_agent(config_path, monkeypatch, fake, hub_version="9.9.9")

    connect(agent)

    assert opened(agent) == [PACKAGE_OPEN]
    assert landed(tmp_path) == ["neutrino_agent.deb"]
    path = str(tmp_path / "packages" / "neutrino_agent.deb")
    assert (tmp_path / "packages" / "neutrino_agent.deb").read_bytes() == (
        PACKAGE_BYTES
    )
    assert launched == [
        [
            "systemd-run",
            "--unit",
            "neutrino_agent_update",
            "--collect",
            "--setenv=DEBIAN_FRONTEND=noninteractive",
            "/bin/sh",
            str(tmp_path / "update.sh"),
        ]
    ]
    script = (tmp_path / "update.sh").read_text()
    assert f"ln -f {path} {tmp_path / 'update.deb'}" in script
    assert (
        "apt-get install -y --allow-downgrades -o DPkg::Lock::Timeout=300 "
        f"{tmp_path / 'update.deb'}" in script
    )
    assert "/usr/bin/nagent --version" in script
    assert agent._update_error is None


def test_the_package_lands_in_the_agents_own_directory_root_only(
    config_path, monkeypatch, launched, fake, tmp_path
):
    agent = bound_agent(config_path, monkeypatch, fake, hub_version="9.9.9")

    connect(agent)

    assert (os.stat(tmp_path / "packages").st_mode & 0o777) == 0o700
    assert len(landed(tmp_path)) == 1


def test_a_digest_mismatch_installs_nothing_and_leaves_no_file(
    config_path, monkeypatch, launched, fake, tmp_path
):
    agent = bound_agent(
        config_path, monkeypatch, fake, hub_version="9.9.9", named_digest="0" * 64
    )

    connect(agent)

    assert launched == []
    assert agent._update_error == {
        "code": "agent_package_digest_mismatch",
        "params": {"target": "9.9.9"},
    }
    assert landed(tmp_path) == []


def test_a_failed_target_is_not_retried(config_path, monkeypatch, launched, fake):
    agent = bound_agent(
        config_path, monkeypatch, fake, hub_version="9.9.9", named_digest="0" * 64
    )

    connect(agent)
    connect(agent)

    assert len(opened(agent)) == 1
    assert launched == []


def test_a_socket_dropped_mid_transfer_leaves_no_file_and_locks_no_target(
    config_path, monkeypatch, launched, fake, tmp_path
):
    agent = bound_agent(
        config_path, monkeypatch, fake, hub_version="9.9.9", is_dropped=True
    )

    connect(agent)

    assert launched == []
    assert landed(tmp_path) == []
    assert agent._update_target == ""
    assert agent._update_error == {
        "code": "hub_unreachable",
        "params": {"target": "9.9.9"},
    }

    connect(agent)

    assert len(opened(agent)) == 2


def test_a_close_that_names_no_digest_is_a_dropped_transfer(
    config_path, monkeypatch, launched, fake, tmp_path
):
    agent = bound_agent(
        config_path, monkeypatch, fake, hub_version="9.9.9", has_digest=False
    )

    connect(agent)
    connect(agent)

    assert launched == []
    assert landed(tmp_path) == []
    assert len(opened(agent)) == 2


def test_a_hub_that_refuses_the_package_is_coded_and_latched(
    config_path, monkeypatch, launched, fake, tmp_path
):
    agent = bound_agent(
        config_path,
        monkeypatch,
        fake,
        hub_version="9.9.9",
        refusal="agent_package_missing",
    )

    connect(agent)
    connect(agent)

    assert launched == []
    assert landed(tmp_path) == []
    assert len(opened(agent)) == 1
    assert agent._update_error == {
        "code": "agent_package_missing",
        "params": {"target": "9.9.9"},
    }


def test_a_matching_version_is_left_alone(config_path, monkeypatch, launched, fake):
    agent = bound_agent(config_path, monkeypatch, fake, hub_version="1.0.0")

    connect(agent)

    assert opened(agent) == []
    assert launched == []
    assert agent._update_error is None


def test_an_older_hub_is_not_downgraded_to(config_path, monkeypatch, launched, fake):
    agent = bound_agent(config_path, monkeypatch, fake, hub_version="0.0.1")

    connect(agent)

    assert opened(agent) == []
    assert launched == []


def test_an_unparseable_hub_version_updates_nothing(
    config_path, monkeypatch, launched, fake
):
    agent = bound_agent(config_path, monkeypatch, fake, hub_version="wat")

    connect(agent)

    assert opened(agent) == []
    assert launched == []
    assert agent._update_error is None


def test_a_launch_failure_is_coded_and_cleaned_up(
    config_path, monkeypatch, tmp_path, fake
):
    agent = bound_agent(config_path, monkeypatch, fake, hub_version="9.9.9")

    def refuse_to_run(command, **kwargs):
        raise OSError("systemd-run is not here")

    monkeypatch.setattr(self_update.subprocess, "run", refuse_to_run)
    connect(agent)

    assert agent._update_error == {
        "code": "agent_update_launch_failed",
        "params": {"target": "9.9.9"},
    }
    assert landed(tmp_path) == []


def test_a_new_target_version_after_a_failure_is_tried(
    config_path, monkeypatch, launched, fake
):
    agent = bound_agent(
        config_path, monkeypatch, fake, hub_version="9.9.9", named_digest="0" * 64
    )

    connect(agent)
    agent._hub_version = "9.9.10"
    agent._fake.on_open = PackageHub()
    connect(agent)

    assert len(opened(agent)) == 2
    assert len(launched) == 1
    assert agent._update_error is None


def test_a_successful_target_is_not_relaunched(
    config_path, monkeypatch, launched, fake
):
    agent = bound_agent(config_path, monkeypatch, fake, hub_version="9.9.9")

    connect(agent)
    connect(agent)

    assert len(opened(agent)) == 1
    assert len(launched) == 1


# --- the stream's outcome, as the update reads it ---


def stream_outcome(tmp_path, chunks, close, kind="deb"):
    channel = FakeChannel(stream_id=1)
    for chunk in chunks:
        channel.feed(("data", chunk))
    channel.feed(("close", close[0], close[1]))
    return self_update.receive_package(
        channel, directory=str(tmp_path / "packages"), kind=kind
    )


def what_installs(kind: str, path: str, **shape) -> str:
    """The text that names the package to its installer: the PowerShell's
    command line on Windows, the script elsewhere."""
    shape = {"state_dir": "/s", "version": "0.5.0", "is_reinstall": False, **shape}
    if kind == "msi":
        return " ".join(self_update.install_command(kind, path, **shape))
    return self_update.install_script(kind, path, **shape)


def test_receive_package_hands_over_the_file_the_close_vouches_for(tmp_path):
    path = stream_outcome(
        tmp_path, [PACKAGE_BYTES], ("", {"sha256": sha256(PACKAGE_BYTES)})
    )

    assert path.startswith(str(tmp_path / "packages"))
    with open(path, "rb") as stream:
        assert stream.read() == PACKAGE_BYTES


@pytest.mark.parametrize("kind", ["deb", "rpm", "msi", "pkg"])
def test_the_installer_sees_the_package_under_its_final_name(tmp_path, kind):
    path = stream_outcome(
        tmp_path, [PACKAGE_BYTES], ("", {"sha256": sha256(PACKAGE_BYTES)}), kind
    )

    assert path == str(tmp_path / "packages" / f"neutrino_agent.{kind}")
    assert landed(tmp_path) == [f"neutrino_agent.{kind}"]
    install = what_installs(kind, path)
    assert f"neutrino_agent.{kind}" in install
    assert ".part" not in install


RELEASE_NAMES = {
    "deb": "neutrino-agent_0.5.0_amd64.deb",
    "rpm": "neutrino-agent-0.5.0-1.x86_64.rpm",
    "msi": "neutrino-agent-0.5.0-windows-amd64.msi",
    "pkg": "neutrino-agent-0.5.0-macos.pkg",
}


@pytest.mark.parametrize("kind", ["deb", "rpm", "msi", "pkg"])
def test_the_package_takes_the_file_name_its_release_gave_it(tmp_path, kind):
    name = RELEASE_NAMES[kind]
    path = stream_outcome(
        tmp_path,
        [PACKAGE_BYTES],
        ("", {"sha256": sha256(PACKAGE_BYTES), "name": name}),
        kind,
    )

    assert path == str(tmp_path / "packages" / name)
    assert landed(tmp_path) == [name]
    install = what_installs(kind, path)
    assert path in install
    assert "neutrino_agent." not in install


def test_the_msi_reinstall_runs_the_file_under_its_release_name():
    path = "C:\\ProgramData\\Neutrino\\agent\\state\\packages\\" + RELEASE_NAMES["msi"]

    script = self_update.install_command(
        "msi", path, state_dir="C:\\s", version="0.5.0", is_reinstall=True
    )[-1]

    assert f'/i "{path}" /qn /norestart' in script
    assert "REINSTALL" not in script


@pytest.mark.parametrize(
    "name",
    [
        "../neutrino-agent.msi",
        "..\\neutrino-agent.msi",
        "sub/neutrino-agent.msi",
        "sub\\neutrino-agent.msi",
        "C:neutrino-agent.msi",
        "C:\\Windows\\neutrino-agent.msi",
        "/etc/neutrino-agent.msi",
        ".neutrino-agent.msi",
        "..msi",
        "neutrino..agent.msi",
        "neutrino agent.msi",
        "neutrino-agent.msi;reboot",
        "neutrino-agent.pkg",
        "",
        7,
        None,
    ],
)
def test_an_unsafe_release_name_falls_back_to_the_agents_own(tmp_path, name):
    path = stream_outcome(
        tmp_path,
        [PACKAGE_BYTES],
        ("", {"sha256": sha256(PACKAGE_BYTES), "name": name}),
        "msi",
    )

    assert path == str(tmp_path / "packages" / "neutrino_agent.msi")
    assert landed(tmp_path) == ["neutrino_agent.msi"]


def test_a_release_name_does_not_skip_the_digest_check(tmp_path):
    with pytest.raises(SelfUpdateError):
        stream_outcome(
            tmp_path,
            [PACKAGE_BYTES],
            ("", {"sha256": "0" * 64, "name": RELEASE_NAMES["msi"]}),
            "msi",
        )

    assert landed(tmp_path) == []


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


def has_dnf(monkeypatch) -> None:
    monkeypatch.setattr(
        self_update.shutil,
        "which",
        lambda name: "/usr/bin/dnf" if name == "dnf" else None,
    )


def test_an_rpm_update_to_another_version_is_dnf_install_alone(monkeypatch):
    """dnf5 answers a reinstall of a version not installed with nothing to
    do and exit 0."""
    has_dnf(monkeypatch)

    script = what_installs("rpm", "/tmp/hub.rpm", version="0.5.2")

    assert "dnf install -y /s/update.rpm" in script
    assert "dnf reinstall" not in script


def test_an_rpm_reinstall_of_the_running_version_is_dnf_reinstall_alone(
    monkeypatch,
):
    has_dnf(monkeypatch)

    script = what_installs("rpm", "/tmp/hub.rpm", version="0.5.2", is_reinstall=True)

    assert "dnf reinstall -y /s/update.rpm" in script
    assert "dnf install" not in script


def test_the_rpm_command_falls_back_to_yum_without_dnf(monkeypatch):
    monkeypatch.setattr(self_update.shutil, "which", lambda name: None)

    assert "yum install -y /s/update.rpm" in what_installs("rpm", "/tmp/hub.rpm")
    assert "yum reinstall -y /s/update.rpm" in what_installs(
        "rpm", "/tmp/hub.rpm", is_reinstall=True
    )


def test_a_deb_install_is_apt_waiting_for_the_dpkg_lock():
    update = what_installs("deb", "/var/lib/neutrino/agent/packages/a.deb")
    reinstall = what_installs(
        "deb", "/var/lib/neutrino/agent/packages/a.deb", is_reinstall=True
    )

    assert (
        "apt-get install -y --allow-downgrades -o DPkg::Lock::Timeout=300 "
        "/s/update.deb" in update
    )
    assert (
        "apt-get install -y --reinstall --allow-downgrades "
        "-o DPkg::Lock::Timeout=300 /s/update.deb" in reinstall
    )
    assert "dpkg -i" not in update + reinstall


@pytest.mark.parametrize("kind", ["deb", "rpm", "pkg"])
def test_the_install_links_the_received_file_to_its_own_before_anything_waits(
    kind,
):
    script = what_installs(kind, f"/var/lib/neutrino/agent/packages/a.{kind}")
    lines = script.splitlines()

    link = next(i for i, line in enumerate(lines) if line.startswith("ln -f "))
    install = next(i for i, line in enumerate(lines) if line.startswith("( "))
    assert lines[link] == (
        f"ln -f /var/lib/neutrino/agent/packages/a.{kind} /s/update.{kind} "
        f"2>/dev/null || cp -f /var/lib/neutrino/agent/packages/a.{kind} "
        f"/s/update.{kind} >> /s/reinstall.log 2>&1"
    )
    assert link < install
    assert "packages/a." not in lines[install]
    assert f"rm -f /s/update.{kind}" in lines[install:]


def test_the_linux_install_runs_a_script_file_in_a_transient_unit(monkeypatch):
    """The unit's command line holds no script text, so systemd has no
    multi-line property to parse on a daemon-reload."""
    has_dnf(monkeypatch)

    command = self_update.install_command(
        "rpm", "/tmp/hub.rpm", state_dir="/etc/agent", version="1", is_reinstall=False
    )

    assert command == [
        "systemd-run",
        "--unit",
        "neutrino_agent_update",
        "--collect",
        "/bin/sh",
        "/etc/agent/update.sh",
    ]


def test_an_update_writes_its_script_root_only_beside_the_state_and_runs_it(
    launched, tmp_path
):
    package = tmp_path / "neutrino-agent_0.5.2_amd64.deb"
    package.write_bytes(b"deb")

    self_update.run_update(
        str(package),
        kind="deb",
        state_dir=str(tmp_path),
        version="0.5.2",
        is_reinstall=False,
    )

    script = tmp_path / "update.sh"
    assert script.stat().st_mode & 0o777 == 0o600
    assert script.read_text() == self_update.install_script(
        "deb",
        str(package),
        state_dir=str(tmp_path),
        version="0.5.2",
        is_reinstall=False,
    )
    assert launched[0][-2:] == ["/bin/sh", str(script)]
    assert not any("\n" in word for word in launched[0])


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


def run_unit(
    tmp_path,
    *,
    kind: str = "deb",
    package: str = "hub.deb",
    version: str = "0.5.2",
    is_reinstall: bool = True,
) -> str:
    """Run the script the unit would run, from its file, with the managers
    stubbed.

    Args:
        tmp_path: The test's directory, which is also the agent's data dir.
        kind: ``deb``, ``rpm`` or ``pkg``.
        package: The package file's name.
        version: The package's version.
        is_reinstall: Whether the package is the version installed now.

    Returns:
        What the result file holds, unparsed.
    """
    bin_dir = tmp_path / "bin"
    (tmp_path / package).write_bytes(b"package")
    script = tmp_path / "update.sh"
    script.write_text(
        self_update.install_script(
            kind,
            str(tmp_path / package),
            state_dir=str(tmp_path),
            version=version,
            is_reinstall=is_reinstall,
        )
    )
    environment = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    subprocess.run(["sh", str(script)], capture_output=True, env=environment)
    return (tmp_path / "reinstall.json").read_text()


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    """A PATH whose package managers are this test's own, and an agent
    program of its own that reports no version until a test gives it one."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for kind in ("deb", "rpm", "pkg"):
        monkeypatch.setitem(
            self_update.PACKAGE_KIND_TO_PROGRAM, kind, str(bin_dir / "nagent")
        )
    return bin_dir


def test_the_unit_writes_what_the_install_said_and_how_it_exited(tmp_path, stubbed):
    stub_manager(stubbed, "apt-get", body='echo "Setting up neutrino-agent"')

    written = json.loads(run_unit(tmp_path))

    assert written["package"] == "hub.deb"
    assert written["kind"] == "deb"
    assert written["version"] == "0.5.2"
    assert written["exit_code"] == 0
    assert written["output"] == "Setting up neutrino-agent\n"
    assert written["started_at"].endswith("Z")
    assert written["finished_at"].endswith("Z")


def test_the_unit_leaves_the_log_and_the_result_root_only(tmp_path, stubbed):
    stub_manager(stubbed, "apt-get", body="echo done")

    run_unit(tmp_path)

    assert (tmp_path / "reinstall.log").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "reinstall.json").stat().st_mode & 0o777 == 0o600


def test_a_failed_install_carries_its_exit_status_and_what_apt_said(tmp_path, stubbed):
    stub_manager(
        stubbed,
        "apt-get",
        body='echo "E: Could not get lock /var/lib/dpkg/lock-frontend"; exit 100',
    )

    written = json.loads(run_unit(tmp_path))

    assert written["exit_code"] == 100
    assert "Could not get lock" in written["output"]


def test_an_update_the_installed_agent_is_at_already_installs_nothing(
    tmp_path, stubbed
):
    """The hub's own update script got there first: success, and no second
    install to restart the agent again."""
    stub_manager(stubbed, "nagent", body="echo 0.5.2")
    calls = tmp_path / "apt_calls"
    stub_manager(stubbed, "apt-get", body=f'echo "$*" >> {calls}')

    written = json.loads(run_unit(tmp_path, is_reinstall=False))

    assert written["exit_code"] == 0
    assert written["output"] == "already 0.5.2\n"
    assert not calls.exists()


def agent_at(stubbed, tmp_path, version: str) -> None:
    """An installed agent of this version, which a stubbed install moves."""
    (tmp_path / "agent_version").write_text(version + "\n")
    stub_manager(stubbed, "nagent", body=f"cat {tmp_path / 'agent_version'}")


@pytest.mark.parametrize("kind", ["deb", "rpm", "pkg"])
def test_an_update_from_another_version_installs(tmp_path, stubbed, kind):
    agent_at(stubbed, tmp_path, "0.5.1")
    calls = tmp_path / "calls"
    for manager in ("apt-get", "dnf", "yum", "installer", "launchctl"):
        stub_manager(
            stubbed,
            manager,
            body=f'echo "{manager} $*" >> {calls}; '
            f"echo 0.5.2 > {tmp_path / 'agent_version'}",
        )

    written = json.loads(
        run_unit(tmp_path, kind=kind, package=f"hub.{kind}", is_reinstall=False)
    )

    assert written["exit_code"] == 0
    assert f"update.{kind}" in calls.read_text().splitlines()[0]
    assert not (tmp_path / f"update.{kind}").exists()


def test_the_install_reads_its_own_link_when_the_received_file_is_cleared(
    tmp_path, stubbed
):
    """The agent another install started clears the packages directory
    while this install waits for the lock."""
    agent_at(stubbed, tmp_path, "0.5.1")
    stub_manager(
        stubbed,
        "apt-get",
        body=f"rm -f {tmp_path / 'hub.deb'}\n"
        'for word in "$@"; do last=$word; done\n'
        '[ -f "$last" ] || { echo "missing $last"; exit 100; }\n'
        f'echo "Setting up from $last"; echo 0.5.2 > {tmp_path / "agent_version"}',
    )

    written = json.loads(run_unit(tmp_path, is_reinstall=False))

    assert written["exit_code"] == 0
    assert written["output"] == f"Setting up from {tmp_path / 'update.deb'}\n"
    assert not (tmp_path / "update.deb").exists()


def test_a_failed_install_that_left_the_target_in_place_is_a_success(tmp_path, stubbed):
    """The hub's own script installed the agent while this install waited
    for the lock; the package manager then refused or found nothing to do."""
    agent_at(stubbed, tmp_path, "0.5.1")
    stub_manager(
        stubbed,
        "apt-get",
        body=f"echo 0.5.2 > {tmp_path / 'agent_version'}; "
        'echo "E: Could not open file"; exit 100',
    )

    written = json.loads(run_unit(tmp_path, is_reinstall=False))

    assert written["exit_code"] == 0
    assert written["output"] == "E: Could not open file\nalready 0.5.2\n"


def test_an_install_that_left_another_version_fails_whatever_apt_said(
    tmp_path, stubbed
):
    agent_at(stubbed, tmp_path, "0.5.1")
    stub_manager(stubbed, "apt-get", body='echo "0 upgraded"')

    written = json.loads(run_unit(tmp_path, is_reinstall=False))

    assert written["exit_code"] == 1
    assert written["output"] == "0 upgraded\nfound version 0.5.1\n"


def test_an_install_that_left_no_agent_fails_naming_none(tmp_path, stubbed):
    stub_manager(stubbed, "apt-get", body='echo "0 upgraded"')

    written = json.loads(run_unit(tmp_path, is_reinstall=False))

    assert written["exit_code"] == 1
    assert written["output"].endswith("found version none\n")


def test_a_failed_reinstall_keeps_its_own_exit(tmp_path, stubbed):
    agent_at(stubbed, tmp_path, "0.5.2")
    stub_manager(stubbed, "apt-get", body="exit 100")

    written = json.loads(run_unit(tmp_path, is_reinstall=True))

    assert written["exit_code"] == 100


def dnf_refusing(stubbed, tmp_path, *, times: int, refusal: str):
    """A dnf that refuses this many times, then installs the target."""
    calls = tmp_path / "dnf_calls"
    stub_manager(
        stubbed,
        "dnf",
        body=f'echo "$*" >> {calls}\n'
        f'if [ "$(wc -l < {calls})" -le {times} ]; then echo "{refusal}"; exit 1; fi\n'
        f"echo Installed; echo 0.5.2 > {tmp_path / 'agent_version'}",
    )
    return calls


def test_dnf_runs_again_while_another_transaction_holds_the_rpm_lock(
    tmp_path, stubbed, monkeypatch
):
    """dnf5 does not wait for the lock: it refuses at once and says so."""
    monkeypatch.setattr(self_update.shutil, "which", lambda name: "/usr/bin/dnf")
    agent_at(stubbed, tmp_path, "0.5.1")
    calls = dnf_refusing(
        stubbed,
        tmp_path,
        times=2,
        refusal="Failed to obtain rpm transaction lock. "
        "Another transaction is in progress.",
    )

    written = json.loads(
        run_unit(tmp_path, kind="rpm", package="hub.rpm", is_reinstall=False)
    )

    assert written["exit_code"] == 0
    assert len(calls.read_text().splitlines()) == 3
    assert written["output"].count("rpm transaction lock") == 2
    assert written["output"].endswith("Installed\n")


def test_dnf_refusing_for_another_reason_is_not_run_again(
    tmp_path, stubbed, monkeypatch
):
    monkeypatch.setattr(self_update.shutil, "which", lambda name: "/usr/bin/dnf")
    agent_at(stubbed, tmp_path, "0.5.1")
    calls = dnf_refusing(stubbed, tmp_path, times=2, refusal="No match for argument")

    written = json.loads(
        run_unit(tmp_path, kind="rpm", package="hub.rpm", is_reinstall=False)
    )

    assert written["exit_code"] == 1
    assert len(calls.read_text().splitlines()) == 1
    assert written["output"] == "No match for argument\n"


def test_a_reinstall_does_not_ask_the_installed_version(tmp_path, stubbed):
    stub_manager(stubbed, "nagent", body="echo 0.5.2")
    calls = tmp_path / "apt_calls"
    stub_manager(stubbed, "apt-get", body=f'echo "$*" >> {calls}')

    json.loads(run_unit(tmp_path, is_reinstall=True))

    assert "--reinstall" in calls.read_text()


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
        "apt-get",
        body="i=0; while [ $i -lt 400 ]; do "
        "echo 0123456789012345678901234567890123456789; i=$((i+1)); done",
    )

    written = json.loads(run_unit(tmp_path))

    assert len(written["output"]) <= AGENT_REINSTALL_OUTPUT_LIMIT_BYTES
    assert written["output"].endswith("0123456789\n")


def test_output_a_shell_would_choke_on_stays_readable_json(tmp_path, stubbed):
    stub_manager(
        stubbed, "apt-get", body=r"""printf 'a "quote" and a \\ and a\ttab\r\n'"""
    )

    written = json.loads(run_unit(tmp_path))

    assert written["output"] == 'a "quote" and a \\ and a tab\n'


def test_the_result_reads_back_in_the_shape_the_hub_is_given(tmp_path, stubbed):
    stub_manager(stubbed, "apt-get", body="echo done")
    run_unit(tmp_path)

    read = self_update.read_reinstall_result(str(tmp_path))

    assert set(read) == {
        "package",
        "kind",
        "version",
        "started_at",
        "finished_at",
        "exit_code",
        "output",
    }
    assert read["exit_code"] == 0


def test_the_result_reads_back_with_its_tokens_masked(tmp_path):
    (tmp_path / "reinstall.json").write_text(
        json.dumps(
            {
                "package": "neutrino_agent.pkg",
                "exit_code": 1,
                "output": "Web UI available at http://h:8000?tkn=abc123\n",
            }
        )
    )

    result = self_update.read_reinstall_result(str(tmp_path))

    assert result["output"] == "Web UI available at http://h:8000?tkn=***\n"
    assert result["version"] == ""


@pytest.mark.parametrize(
    "name, version",
    [
        ("neutrino-agent_0.5.2_amd64.deb", "0.5.2"),
        ("neutrino-agent-0.5.2-1.x86_64.rpm", "0.5.2"),
        ("neutrino-agent-0.5.2-windows-amd64.msi", "0.5.2"),
        ("neutrino-agent-0.5.2-macos-arm64.pkg", "0.5.2"),
        ("neutrino_agent.deb", ""),
        ("", ""),
    ],
)
def test_a_release_name_carries_its_version(name, version):
    assert self_update.release_version(name) == version


@pytest.mark.parametrize(
    "written, is_dropped",
    [
        ({"package": "neutrino-agent_0.5.2_amd64.deb", "exit_code": 100}, True),
        ({"package": "neutrino-agent-0.5.2-1.x86_64.rpm", "exit_code": 1}, True),
        (
            {"package": "neutrino-agent-0.5.2-windows-amd64.msi", "exit_code": 1618},
            True,
        ),
        ({"package": "neutrino-agent-0.5.2-macos-arm64.pkg", "exit_code": 1}, True),
        (
            {"package": "neutrino_agent.deb", "version": "0.5.2", "exit_code": 100},
            True,
        ),
        (
            {
                "package": "neutrino-agent_0.5.2_amd64.deb",
                "version": "0.5.1",
                "exit_code": 100,
            },
            False,
        ),
        ({"package": "neutrino-agent_0.5.1_amd64.deb", "exit_code": 100}, False),
        ({"package": "neutrino_agent.deb", "exit_code": 100}, False),
        ({"package": "neutrino-agent_0.5.2_amd64.deb", "exit_code": 0}, False),
    ],
)
def test_a_failed_result_of_the_running_version_is_dropped(
    tmp_path, written, is_dropped
):
    """The record's own version is compared; a record an older agent wrote
    names none, and its release name says it."""
    record = tmp_path / "reinstall.json"
    record.write_text(json.dumps(written))

    assert self_update.clear_failed_result(str(tmp_path), version="0.5.2") == (
        is_dropped
    )
    assert record.exists() != is_dropped


def test_no_running_version_drops_nothing(tmp_path):
    record = tmp_path / "reinstall.json"
    record.write_text(json.dumps({"package": "neutrino_agent.deb", "exit_code": 1}))

    assert self_update.clear_failed_result(str(tmp_path), version="") is False
    assert record.exists()


def test_the_wait_for_a_result_returns_it_once_written(tmp_path):
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        (tmp_path / "reinstall.json").write_text(
            json.dumps({"exit_code": 1, "finished_at": "t"})
        )

    result = self_update.wait_reinstall_result(
        str(tmp_path), timeout_s=60, sleep=sleep, clock=lambda: 0.0
    )

    assert result["exit_code"] == 1
    assert len(slept) == 1


def test_the_wait_for_a_result_gives_up_at_its_deadline(tmp_path):
    ticks = iter([0.0, 5.0, 11.0])

    result = self_update.wait_reinstall_result(
        str(tmp_path),
        timeout_s=10,
        sleep=lambda seconds: None,
        clock=lambda: next(ticks),
    )

    assert result is None


def test_no_result_file_reads_as_nothing(tmp_path):
    assert self_update.read_reinstall_result(str(tmp_path)) is None


@pytest.mark.parametrize("written", ["not json", "[]", '{"exit_code": "wat"}'])
def test_a_result_that_cannot_be_read_is_nothing(tmp_path, written):
    (tmp_path / "reinstall.json").write_text(written)

    assert self_update.read_reinstall_result(str(tmp_path)) is None


def test_a_launch_drops_the_result_of_the_reinstall_before_it(
    config_path, monkeypatch, launched, fake, tmp_path
):
    agent = bound_agent(config_path, monkeypatch, fake, hub_version="9.9.9")
    stale = tmp_path / "reinstall.json"
    stale.write_text(json.dumps({"exit_code": 0}))

    connect(agent)

    assert not stale.exists()
    assert len(launched) == 1


# --- Windows and macOS: msiexec detached, installer through launchd ---


def test_windows_and_macos_name_their_own_package_kind():
    assert self_update.package_kind({"os": "windows", "family": ""}) == "msi"
    assert self_update.package_kind({"os": "darwin", "family": ""}) == "pkg"


def test_the_msi_runs_quietly_in_powershell_and_writes_the_same_result():
    state_dir = "C:\\ProgramData\\Neutrino\\agent\\state"
    package = state_dir + "\\packages\\neutrino-agent-0.4.0-windows-amd64.msi"

    command = self_update.install_command(
        "msi", package, state_dir=state_dir, version="0.4.0", is_reinstall=False
    )

    assert command[:6] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
    ]
    script = command[6]
    assert "Start-Process -FilePath msiexec.exe -Wait" in script
    assert (
        f'\'/i "{package}" /qn /norestart '
        f'/l*v "{state_dir}\\reinstall.log"\'' in script
    )
    assert "-NoNewWindow" in script
    assert "-WindowStyle" not in script
    assert f"'{state_dir}\\reinstall.json'" in script
    assert "package = 'neutrino-agent-0.4.0-windows-amd64.msi'" in script
    assert "kind = 'msi'" in script
    for field in ("version", "started_at", "finished_at", "exit_code", "output"):
        assert f"{field} = " in script
    assert "WriteAllText" in script


@pytest.mark.parametrize("is_reinstall, wanted", [(False, "'0.4.0'"), (True, "''")])
def test_the_msi_install_reads_the_installed_version_unless_a_reinstall(
    is_reinstall, wanted
):
    """The installed agent naming the version the install is to leaves
    msiexec unrun, the log saying so, and the result an exit of 0."""
    script = self_update.install_command(
        "msi",
        "C:\\s\\packages\\neutrino-agent-0.4.0-windows-amd64.msi",
        state_dir="C:\\s",
        version="0.4.0",
        is_reinstall=is_reinstall,
    )[6]

    assert "$version = '0.4.0'" in script
    assert f"$wanted = {wanted}" in script
    assert f"$program = '{self_update.agent_program_path()}'" in script
    assert self_update.agent_program_path().endswith("\\Neutrino\\agent\\nagent.exe")
    assert "& $program --version 2>$null | Select-Object -Last 1" in script
    assert "if ($wanted -and (Get-Installed) -eq $wanted) {" in script
    assert '[IO.File]::WriteAllText($log, "already $wanted`n")' in script


def test_the_msi_waits_for_the_windows_installer_before_each_try():
    script = what_installs("msi", "C:\\s\\packages\\a.msi")

    assert "[Threading.Mutex]::TryOpenExisting('Global\\_MSIExecute', [ref]$held)" in (
        script
    )
    assert "$deadline = (Get-Date).AddSeconds(300)" in script
    assert "if ($code -eq 1618) { $code = Invoke-Install }" in script


@pytest.mark.parametrize(
    "case, path, state_dir, version, is_reinstall",
    [
        (
            "upgrade",
            GOLDEN_STATE + "\\packages\\neutrino-agent-0.5.2-windows-amd64.msi",
            GOLDEN_STATE,
            "0.5.2",
            False,
        ),
        (
            "reinstall",
            GOLDEN_STATE + "\\packages\\neutrino-agent-0.5.2-windows-amd64.msi",
            GOLDEN_STATE,
            "0.5.2",
            True,
        ),
        ("quoted", "C:\\it's\\agent.msi", "C:\\it's", "0.4.0", False),
    ],
)
def test_the_msi_install_renders_the_golden_command_byte_for_byte(
    monkeypatch, case, path, state_dir, version, is_reinstall
):
    """The golden was rendered before the msiexec wait and retry moved to
    ``installers``; the script that composes them is the same text."""
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    golden = json.loads(
        (GOLDEN / "self_update_msi_commands.json").read_text(encoding="utf-8")
    )

    command = self_update.install_command(
        "msi", path, state_dir=state_dir, version=version, is_reinstall=is_reinstall
    )

    assert command == golden[case]


# --- the Windows install, run in PowerShell where there is one ---

pwsh = shutil.which("pwsh")

# Stands in for msiexec: each call takes the next exit code of FAKE_CODES,
# and every call but a busy one leaves FAKE_LEAVES as the installed version.
WINDOWS_STAND_INS = """
function Start-Process {
    param([string]$FilePath, [switch]$Wait, [switch]$PassThru, [switch]$NoNewWindow,
          [string]$ArgumentList)
    Add-Content -LiteralPath $env:FAKE_ASKED -Value "msiexec $ArgumentList"
    $calls = @(Get-Content -LiteralPath $env:FAKE_ASKED).Count
    $code = [int]($env:FAKE_CODES.Split(',')[$calls - 1])
    if ($code -ne 1618 -and $env:FAKE_LEAVES) {
        Set-Content -LiteralPath $env:FAKE_AGENT -Value $env:FAKE_LEAVES
    }
    return [pscustomobject]@{ ExitCode = $code }
}
"""


def run_windows_install(
    tmp_path, monkeypatch, *, codes: str, leaves: str = "", is_reinstall=False
):
    """Run the PowerShell the Windows install runs, msiexec stood in for.

    Returns:
        The result it wrote, as the agent reads it, and the msiexec calls.
    """
    if pwsh is None:
        pytest.skip("PowerShell is not installed")
    agent = tmp_path / "agent_version"
    agent.write_text("0.5.1\n")
    program = tmp_path / "nagent.exe"
    program.write_text(f"#!/bin/sh\ncat {agent}\n")
    program.chmod(0o755)
    monkeypatch.setattr(self_update, "agent_program_path", lambda: str(program))
    state_dir = str(tmp_path) + "/"
    script = self_update.install_command(
        "msi",
        str(tmp_path / "neutrino-agent-0.5.2-windows-amd64.msi"),
        state_dir=state_dir,
        version="0.5.2",
        is_reinstall=is_reinstall,
    )[6]
    driver = tmp_path / "driver.ps1"
    driver.write_text(WINDOWS_STAND_INS + script)
    asked = tmp_path / "asked"
    subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "FAKE_ASKED": str(asked),
            "FAKE_CODES": codes,
            "FAKE_LEAVES": leaves,
            "FAKE_AGENT": str(agent),
        },
    )
    calls = asked.read_text().splitlines() if asked.exists() else []
    return self_update.read_reinstall_result(state_dir), calls


def test_a_windows_install_another_install_held_off_runs_once_more(
    tmp_path, monkeypatch
):
    result, calls = run_windows_install(
        tmp_path, monkeypatch, codes="1618,0", leaves="0.5.2"
    )

    assert result["exit_code"] == 0
    assert len(calls) == 2


def test_a_windows_install_that_failed_with_the_target_in_place_is_a_success(
    tmp_path, monkeypatch
):
    result, calls = run_windows_install(
        tmp_path, monkeypatch, codes="1603", leaves="0.5.2"
    )

    assert result["exit_code"] == 0
    assert result["output"].endswith("already 0.5.2\n")
    assert len(calls) == 1


def test_a_windows_install_that_left_another_version_fails(tmp_path, monkeypatch):
    result, _calls = run_windows_install(tmp_path, monkeypatch, codes="0")

    assert result["exit_code"] == 1
    assert result["output"].endswith("found version 0.5.1\n")


def test_a_windows_reinstall_keeps_msiexecs_own_exit(tmp_path, monkeypatch):
    result, _calls = run_windows_install(
        tmp_path, monkeypatch, codes="1603", leaves="0.5.2", is_reinstall=True
    )

    assert result["exit_code"] == 1603


def test_a_quote_in_a_path_cannot_end_the_powershell_string():
    command = self_update.install_command(
        "msi",
        "C:\\it's\\agent.msi",
        state_dir="C:\\it's",
        version="0.4.0",
        is_reinstall=False,
    )

    assert "'C:\\it''s\\reinstall.json'" in command[6]


def test_the_msi_is_started_with_no_window_and_outside_the_services_job(
    monkeypatch, tmp_path
):
    started = []

    class Popen:
        def __init__(self, command, **kwargs):
            started.append((command, kwargs["creationflags"]))

    monkeypatch.setattr(self_update.subprocess, "Popen", Popen)
    package = tmp_path / "agent.msi"
    package.write_bytes(b"msi")

    self_update.run_update(
        str(package), kind="msi", state_dir=str(tmp_path), version="", is_reinstall=True
    )

    command, flags = started[0]
    assert command[0] == "powershell.exe"
    assert flags == 0x08000000 | 0x01000000
    assert package.exists()


def test_a_job_that_refuses_breakaway_still_starts_the_install_with_no_window(
    monkeypatch, tmp_path
):
    tried = []
    started = []

    class Popen:
        def __init__(self, command, **kwargs):
            tried.append(kwargs["creationflags"])
            if kwargs["creationflags"] & 0x01000000:
                raise PermissionError("access denied")
            started.append(kwargs["creationflags"])

    monkeypatch.setattr(self_update.subprocess, "Popen", Popen)
    package = tmp_path / "agent.msi"
    package.write_bytes(b"msi")

    self_update.run_update(
        str(package), kind="msi", state_dir=str(tmp_path), version="", is_reinstall=True
    )

    assert tried == [0x08000000 | 0x01000000, 0x08000000]
    assert started == [0x08000000]


def test_an_msi_that_cannot_be_started_is_coded_and_cleaned_up(monkeypatch, tmp_path):
    def refuse(command, **kwargs):
        raise FileNotFoundError("powershell.exe")

    monkeypatch.setattr(self_update.subprocess, "Popen", refuse)
    package = tmp_path / "agent.msi"
    package.write_bytes(b"msi")

    with pytest.raises(SelfUpdateError) as refused:
        self_update.run_update(
            str(package),
            kind="msi",
            state_dir=str(tmp_path),
            version="",
            is_reinstall=True,
        )

    assert str(refused.value) == "agent_update_launch_failed"
    assert not package.exists()


def test_the_pkg_is_installed_by_a_job_submitted_to_launchd():
    shape = {"state_dir": "/Library/x y", "version": "0.5.2", "is_reinstall": False}

    command = self_update.install_command("pkg", "/tmp/agent pkg/neutrino.pkg", **shape)
    script = self_update.install_script("pkg", "/tmp/agent pkg/neutrino.pkg", **shape)

    assert command == [
        "launchctl",
        "submit",
        "-l",
        "neutrino_agent_update",
        "--",
        "/bin/sh",
        "/Library/x y/update.sh",
    ]
    assert "ln -f '/tmp/agent pkg/neutrino.pkg' '/Library/x y/update.pkg'" in script
    assert "installer -pkg '/Library/x y/update.pkg' -target /" in script
    assert "'/Library/x y/reinstall.json'" in script
    assert "/usr/local/bin/nagent --version" in script


def test_a_pkg_update_removes_the_job_the_last_one_left_then_submits(
    monkeypatch, tmp_path
):
    commands = []

    def run(command, **kwargs):
        commands.append(list(command[:3]))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(self_update.subprocess, "run", run)
    package = tmp_path / "agent.pkg"
    package.write_bytes(b"pkg")

    self_update.run_update(
        str(package),
        kind="pkg",
        state_dir=str(tmp_path),
        version="0.5.2",
        is_reinstall=False,
    )

    assert commands == [
        ["launchctl", "remove", "neutrino_agent_update"],
        ["launchctl", "submit", "-l"],
    ]


def test_the_pkg_job_writes_what_installer_said_in_the_same_shape(tmp_path, stubbed):
    stub_manager(
        stubbed, "installer", body='echo "installer: The upgrade was successful."'
    )

    written = json.loads(run_unit(tmp_path, kind="pkg", package="agent.pkg"))

    assert written["package"] == "agent.pkg"
    assert written["kind"] == "pkg"
    assert written["exit_code"] == 0
    assert written["output"] == "installer: The upgrade was successful.\n"


@pytest.mark.parametrize("installer_exit", [0, 1])
def test_the_pkg_job_removes_itself_last_whatever_installer_did(
    tmp_path, stubbed, installer_exit
):
    """launchd runs a submitted job again every ten seconds until it is
    removed, so the job's last act is its own removal, after the result."""
    stub_manager(stubbed, "installer", body=f"echo installing; exit {installer_exit}")
    calls = tmp_path / "launchctl_calls"
    stub_manager(
        stubbed,
        "launchctl",
        body=f'test -s {tmp_path}/reinstall.json && echo "$*" >> {calls}',
    )

    written = json.loads(run_unit(tmp_path, kind="pkg", package="agent.pkg"))

    assert written["exit_code"] == installer_exit
    assert calls.read_text() == "remove neutrino_agent_update\n"
    script = what_installs("pkg", str(tmp_path / "agent.pkg"))
    assert script.splitlines()[-1] == "launchctl remove neutrino_agent_update"


def test_the_linux_unit_and_the_windows_install_run_once():
    """A transient unit with no restart runs once and --collect unloads it
    even after a failure; the Windows install is one detached process."""
    unit = self_update.install_command(
        "deb", "/tmp/a.deb", state_dir="/var/x", version="1", is_reinstall=False
    )
    assert unit[:4] == ["systemd-run", "--unit", "neutrino_agent_update", "--collect"]
    assert not any(word.startswith("--property=Restart") for word in unit)
    assert "launchctl" not in what_installs("deb", "/tmp/a.deb")


def launchctl_answering(monkeypatch, *, printed_rc, printed=""):
    calls = []

    def run(command, **kwargs):
        calls.append(list(command))
        if command[1] == "print":
            return subprocess.CompletedProcess(command, printed_rc, printed, "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(self_update.subprocess, "run", run)
    return calls


def test_a_starting_agent_removes_a_stale_update_job(monkeypatch):
    calls = launchctl_answering(
        monkeypatch, printed_rc=0, printed="\tstate = spawn scheduled\n\truns = 643\n"
    )

    assert self_update.remove_stale_job("pkg") is True
    assert calls[-1] == ["launchctl", "remove", "neutrino_agent_update"]


def test_a_running_update_job_is_the_install_starting_this_agent_and_stays(
    monkeypatch,
):
    calls = launchctl_answering(
        monkeypatch, printed_rc=0, printed="\tstate = running\n"
    )

    assert self_update.remove_stale_job("pkg") is False
    assert ["launchctl", "remove", "neutrino_agent_update"] not in calls


def test_no_job_and_no_launchd_remove_nothing(monkeypatch):
    calls = launchctl_answering(monkeypatch, printed_rc=113)

    assert self_update.remove_stale_job("pkg") is False
    assert self_update.remove_stale_job("deb") is False
    assert len(calls) == 1
