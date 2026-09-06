"""``nagent operation``: the one stream, read and followed from a terminal.

The hub holds one operation per device and every surface renders its copy;
this file pins what the terminal copy says — the standing line, the output
tail, the follow loop that ends when the operation closes, and the honest
line when nothing answers.
"""

import pytest

from neutrino_agent.cli import operation as operation_cli
from neutrino_agent.cli import wording
from neutrino_agent.control.server import ControlServer
from tests.cli.test_module import FakeTime
from tests.conftest import (
    ROOT,
    FakeControlAgent,
    FakeSocketPlatform,
    discard,
)


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """One running control server, asked as root."""
    platform = FakeSocketPlatform(str(tmp_path / "agent.sock"))
    agent = FakeControlAgent()
    server = ControlServer(
        agent=agent,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
        is_page_served=False,
    )
    server.start()
    assert server.socket_path
    platform.peer = dict(ROOT)
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    yield agent
    server.stop()


def test_nothing_has_run_is_said_plainly(stack, capsys):
    assert operation_cli.main(is_followed=False) == 0

    assert operation_cli.OPERATION_NONE in capsys.readouterr().out


def test_a_done_operation_prints_its_line_and_output(stack, capsys):
    stack.operation_payload = {
        "kind": "module",
        "action": "install",
        "title": "cc-switch",
        "state": "done",
        "output": "verified\n",
    }

    assert operation_cli.main(is_followed=False) == 0

    out = capsys.readouterr().out
    assert "cc-switch — done" in out
    assert "verified" in out


def test_a_failed_operation_exits_nonzero(stack, capsys):
    stack.operation_payload = {
        "kind": "module",
        "action": "uninstall",
        "title": "cc-switch",
        "state": "failed",
        "output": "refused\n",
    }

    assert operation_cli.main(is_followed=False) == 1

    assert "cc-switch — failed" in capsys.readouterr().out


def test_the_agents_own_operation_is_titled_agent(stack, capsys):
    stack.operation_payload = {
        "kind": "bootstrap",
        "action": "install",
        "title": "",
        "state": "running",
        "output": "",
    }

    assert operation_cli.main(is_followed=False) == 0

    assert "agent — running" in capsys.readouterr().out


def test_follow_polls_until_the_operation_closes(stack, monkeypatch, capsys):
    stack.operation_payload = {
        "kind": "module",
        "action": "install",
        "title": "cc-switch",
        "state": "installing",
        "output": "step one\n",
    }

    def finish():
        stack.operation_payload = dict(
            stack.operation_payload, state="done", output="step one\nstep two\n"
        )

    monkeypatch.setattr(operation_cli, "time", FakeTime([finish]))

    assert operation_cli.main(is_followed=True) == 0

    out = capsys.readouterr().out
    assert "cc-switch — installing" in out
    assert "step one" in out and "step two" in out
    assert out.count("step one") == 1
    assert out.rstrip().endswith("done")


def test_follow_ends_nonzero_when_the_operation_fails(stack, monkeypatch, capsys):
    stack.operation_payload = {
        "kind": "module",
        "action": "install",
        "title": "cc-switch",
        "state": "running",
        "output": "",
    }

    def fail():
        stack.operation_payload = dict(stack.operation_payload, state="failed")

    monkeypatch.setattr(operation_cli, "time", FakeTime([fail]))

    assert operation_cli.main(is_followed=True) == 1

    assert wording.CLI_OPERATION_WORDS["failed"] in capsys.readouterr().err


def test_the_honest_line_when_the_agent_is_dead(tmp_path, monkeypatch, capsys):
    platform = FakeSocketPlatform(str(tmp_path / "missing.sock"))
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)

    assert operation_cli.main(is_followed=False) == 1

    assert wording.AGENT_NOT_RUNNING in capsys.readouterr().err
