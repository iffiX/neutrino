"""``nagent module``: the operator's walk over the Modules panel.

The matrix as the person types it: privileged and ordinary, the agent
alive and dead, bound and unbound — each cell asserting the words printed
and the exit status, and that no cell lies about the machine. The install
and uninstall verbs post the page's own ask and follow the hub's one
operation stream; the SSH server's uninstall keeps the page's
confirmation.
"""

import builtins

import pytest

from neutrino_agent.cli import module as module_cli
from neutrino_agent.cli import wording
from neutrino_agent.control.server import ControlServer
from tests.conftest import (
    ALICE,
    ROOT,
    FakeControlAgent,
    FakeSocketPlatform,
    bind,
    discard,
)

MODULES = {
    "openssh_server": {
        "title": "SSH server",
        "description": "",
        "kind": "openssh",
        "entry": {"packages": ["openssh-server"], "service": "ssh"},
    },
    "cc_switch": {
        "title": "cc-switch",
        "description": "",
        "kind": "download",
        "entry": {"url": "https://hub/artifact"},
    },
    "anydesk": {
        "title": "AnyDesk",
        "description": "",
        "kind": "download",
        "entry": {"url": "https://hub/artifact"},
    },
    "samba_mount": {
        "title": "Share mounting",
        "description": "",
        "kind": "mount",
        "entry": {},
    },
    "rustdesk": {
        "title": "RustDesk",
        "description": "",
        "kind": "download",
        "entry": None,
    },
}


class FakeModuleAgent(FakeControlAgent):
    """The control agent with a module catalog worth listing."""

    def __init__(self):
        super().__init__()
        self.module_state_map = {
            "openssh_server": {"state": "installed"},
            "cc_switch": {"state": "absent"},
            "anydesk": {
                "state": "failed",
                "code": "no_platform_build",
                "params": {},
            },
        }

    def catalog(self) -> dict:
        return {"modules": MODULES, "services": []}

    def module_states(self) -> dict:
        return self.module_state_map


class FakeTime:
    """A clock whose sleep runs the next step of a scripted machine."""

    def __init__(self, steps=(), tick_s: float = 0.0):
        self.steps = list(steps)
        self.tick_s = tick_s
        self.now = 0.0

    def sleep(self, seconds) -> None:
        del seconds
        self.now += self.tick_s
        if self.steps:
            self.steps.pop(0)()

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def stack(tmp_path, monkeypatch):
    """One running control server, asked as root by default."""
    platform = FakeSocketPlatform(str(tmp_path / "agent.sock"))
    agent = FakeModuleAgent()
    server = ControlServer(
        agent=agent,
        platform=platform,
        log=discard,
        socket_path=platform.control_socket_path(),
    )
    server.start()
    assert server.socket_path
    platform.peer = dict(ROOT)
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)
    yield agent, platform
    server.stop()


def serve_nothing(monkeypatch, tmp_path):
    """No agent on the socket."""
    platform = FakeSocketPlatform(str(tmp_path / "missing.sock"))
    monkeypatch.setattr(wording, "detect_platform", lambda: platform)


# --- list ---


def test_list_words_every_row_as_the_page_does(stack, config_path, capsys):
    bind(config_path)

    assert module_cli.main_list() == 0

    out = capsys.readouterr().out
    assert "openssh_server" in out and "SSH server" in out and "installed" in out
    assert "cc_switch" in out and "not installed" in out
    assert "samba_mount" in out and "built in" in out
    assert "rustdesk" in out and "not available on this machine" in out
    assert "no version of this exists for this machine" in out
    assert "\x1b" not in out


def test_list_says_when_the_machine_joined_no_gateway(stack, capsys):
    assert module_cli.main_list() == 1

    assert wording.NOT_JOINED in capsys.readouterr().out


def test_list_says_when_the_agent_is_dead(tmp_path, monkeypatch, capsys):
    serve_nothing(monkeypatch, tmp_path)

    assert module_cli.main_list() == 1

    assert wording.AGENT_NOT_RUNNING in capsys.readouterr().err


# --- the switch verbs ---


def test_install_posts_the_pages_ask_and_returns_with_no_wait(
    stack, config_path, capsys
):
    agent, _ = stack
    bind(config_path)

    code = module_cli.main_switch(
        "cc_switch", is_enabled=True, is_waited=False, is_confirmed=False
    )

    assert code == 0
    assert agent.requested == [("cc_switch", True)]
    assert module_cli.MODULE_ASKED in capsys.readouterr().out


def test_an_ordinary_caller_hears_the_channels_own_refusal(stack, config_path, capsys):
    agent, platform = stack
    bind(config_path)
    platform.peer = dict(ALICE)

    code = module_cli.main_switch(
        "cc_switch", is_enabled=True, is_waited=False, is_confirmed=False
    )

    assert code == 1
    assert agent.requested == []
    assert wording.CLI_CODE_WORDS["control_scope_refused"] in capsys.readouterr().err


def test_install_follows_the_operation_stream_to_done(
    stack, config_path, monkeypatch, capsys
):
    agent, _ = stack
    bind(config_path)
    running = {
        "kind": "module",
        "action": "install",
        "title": "cc-switch",
        "state": "installing",
        "output": "fetching the artifact\n",
    }
    done = dict(running, state="done", output="fetching the artifact\nverified\n")

    def start():
        agent.operation_payload = running

    def finish():
        agent.operation_payload = done

    monkeypatch.setattr(module_cli, "time", FakeTime([start, finish]))

    code = module_cli.main_switch(
        "cc_switch", is_enabled=True, is_waited=True, is_confirmed=False
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "cc-switch — installing" in out
    assert "fetching the artifact" in out and "verified" in out
    assert out.rstrip().endswith("done")


def test_a_failed_operation_exits_nonzero_with_the_rows_failure(
    stack, config_path, monkeypatch, capsys
):
    agent, _ = stack
    bind(config_path)

    def fail():
        agent.operation_payload = {
            "kind": "module",
            "action": "install",
            "title": "cc-switch",
            "state": "failed",
            "output": "no artifact\n",
        }
        agent.module_state_map["cc_switch"] = {
            "state": "failed",
            "code": "order_failed",
            "params": {},
        }

    monkeypatch.setattr(module_cli, "time", FakeTime([fail]))

    code = module_cli.main_switch(
        "cc_switch", is_enabled=True, is_waited=True, is_confirmed=False
    )

    assert code == 1
    printed = capsys.readouterr()
    assert "no artifact" in printed.out
    assert "failed — the install did not finish" in printed.err


def test_a_hub_that_never_starts_the_order_ends_the_wait_honestly(
    stack, config_path, monkeypatch, capsys
):
    bind(config_path)
    monkeypatch.setattr(module_cli, "time", FakeTime(tick_s=100.0))

    code = module_cli.main_switch(
        "cc_switch", is_enabled=True, is_waited=True, is_confirmed=False
    )

    assert code == 1
    assert module_cli.MODULE_NEVER_STARTED in capsys.readouterr().err


def test_the_ssh_uninstall_asks_first_and_no_keeps_the_machine(
    stack, config_path, monkeypatch, capsys
):
    agent, _ = stack
    bind(config_path)
    monkeypatch.setattr(builtins, "input", lambda prompt: "n")

    code = module_cli.main_switch(
        "openssh_server", is_enabled=False, is_waited=False, is_confirmed=False
    )

    assert code == 1
    assert agent.requested == []
    out = capsys.readouterr().out
    assert module_cli.UNINSTALL_SSH_TITLE in out
    assert module_cli.MODULE_NOTHING_CHANGED in out


def test_the_ssh_uninstall_posts_on_yes_and_skips_the_ask_with_the_flag(
    stack, config_path, monkeypatch, capsys
):
    agent, _ = stack
    bind(config_path)
    monkeypatch.setattr(builtins, "input", lambda prompt: "y")

    assert (
        module_cli.main_switch(
            "openssh_server", is_enabled=False, is_waited=False, is_confirmed=False
        )
        == 0
    )
    assert (
        module_cli.main_switch(
            "openssh_server", is_enabled=False, is_waited=False, is_confirmed=True
        )
        == 0
    )

    assert agent.requested == [("openssh_server", False), ("openssh_server", False)]
    assert capsys.readouterr().out.count(module_cli.UNINSTALL_SSH_TITLE) == 1


# --- the rows nothing can be posted for ---


def test_an_unknown_name_resolves_to_nothing(stack, config_path, capsys):
    bind(config_path)

    code = module_cli.main_switch(
        "no_such_thing", is_enabled=True, is_waited=False, is_confirmed=False
    )

    assert code == 2
    assert "no module named no_such_thing" in capsys.readouterr().err


def test_a_native_row_offers_nothing_to_press(stack, config_path, capsys):
    agent, _ = stack
    bind(config_path)

    assert (
        module_cli.main_switch(
            "samba_mount", is_enabled=True, is_waited=False, is_confirmed=False
        )
        == 0
    )
    assert (
        module_cli.main_switch(
            "samba_mount", is_enabled=False, is_waited=False, is_confirmed=False
        )
        == 1
    )

    assert agent.requested == []
    out = capsys.readouterr().out
    assert out.count(module_cli.MODULE_BUILT_IN) == 2


def test_an_unsupported_row_refuses_honestly(stack, config_path, capsys):
    agent, _ = stack
    bind(config_path)

    code = module_cli.main_switch(
        "rustdesk", is_enabled=True, is_waited=False, is_confirmed=False
    )

    assert code == 1
    assert agent.requested == []
    assert "not available on this machine" in capsys.readouterr().err


def test_a_row_already_there_posts_nothing(stack, config_path, capsys):
    agent, _ = stack
    bind(config_path)

    code = module_cli.main_switch(
        "openssh_server", is_enabled=True, is_waited=False, is_confirmed=False
    )

    assert code == 0
    assert agent.requested == []
    assert "already installed" in capsys.readouterr().out


def test_a_running_operation_holds_the_verbs(stack, config_path, capsys):
    agent, _ = stack
    bind(config_path)
    agent.operation_payload = {
        "kind": "module",
        "action": "install",
        "title": "AnyDesk",
        "state": "running",
        "output": "",
    }

    code = module_cli.main_switch(
        "cc_switch", is_enabled=True, is_waited=False, is_confirmed=False
    )

    assert code == 1
    assert agent.requested == []
    assert module_cli.MODULE_OPERATION_HELD in capsys.readouterr().err


def test_a_mid_step_row_points_at_the_operation(stack, config_path, capsys):
    agent, _ = stack
    bind(config_path)
    agent.module_state_map["cc_switch"] = {"state": "installing"}

    code = module_cli.main_switch(
        "cc_switch", is_enabled=False, is_waited=False, is_confirmed=False
    )

    assert code == 1
    assert agent.requested == []
    assert "mid-step" in capsys.readouterr().err


def test_switch_says_when_the_agent_is_dead(tmp_path, monkeypatch, capsys):
    serve_nothing(monkeypatch, tmp_path)

    code = module_cli.main_switch(
        "cc_switch", is_enabled=True, is_waited=False, is_confirmed=False
    )

    assert code == 1
    assert wording.AGENT_NOT_RUNNING in capsys.readouterr().err
