"""CloudCLI on Linux, with systemd, runuser and the account database faked.

What these pin: the template unit runs the unpacked Node.js as ``User=%i``
from the account's root-only environment file; the account's own
``claude`` is looked for in its login shell, then as the account at the
known places in order, and a missing one is refused before anything is
written; npm runs as the account with an environment
of its own, into the account's app directory, and a failure names its
step; a new or changed instance is restarted and an unchanged one only kept
up; and an instance no longer named is disabled and its file deleted.
"""

import os
import stat

import pytest

import neutrino_agent.modules.cloudcli.linux_applier as applier_module
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli.config import CloudcliConfig
from neutrino_agent.modules.cloudcli.constants import CLOUDCLI_CLAUDE_PLACES_SHELL
from neutrino_agent.modules.cloudcli.installer import NATIVE_CHECK_EXIT
from neutrino_agent.modules.cloudcli.linux_applier import (
    CloudcliLinuxApplier,
    render_environment,
    render_unit,
)
from neutrino_agent.modules.subprocess_run import CommandResult

NODE_DIR = "node-v22.23.3-linux-x64"
CONFIG = CloudcliConfig.from_dict(
    {
        "gateway_url": "http://10.0.0.1:8317",
        "gateway_key": "device-key",
        "instances": [
            {"account": "ann", "port": 3001, "web_password": "p", "token_secret": "s"}
        ],
    }
)


class Machine:
    """systemctl, runuser and npm, recorded; answers set per command."""

    def __init__(self, home):
        self.calls: list = []
        self.active: set = set()
        self.claude = "/home/ann/.local/bin/claude\n"
        self.places = ""
        self.npm_exit = 0
        self.npm_output = ""
        self.check_exit = 0
        self.check_output = ""
        self.scope_result = "success"
        self.home = home

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[:2] == ["systemctl", "show"]:
            return CommandResult(list(command), 0, self.scope_result + "\n", "")
        if command[0] == "systemd-run":
            command = command[command.index("--") + 1 :]
        if CLOUDCLI_CLAUDE_PLACES_SHELL in command:
            return CommandResult(list(command), 0, self.places, "")
        if command[:2] == ["runuser", "-l"]:
            return CommandResult(
                list(command), 0 if self.claude else 1, self.claude, ""
            )
        if "install" in command:
            if self.npm_exit == 0:
                package = os.path.join(
                    command[command.index("--prefix") + 1],
                    "node_modules",
                    "@cloudcli-ai",
                    "cloudcli",
                )
                os.makedirs(package, exist_ok=True)
                with open(os.path.join(package, "package.json"), "w") as stream:
                    stream.write('{"version": "1.37.3"}')
            return CommandResult(list(command), self.npm_exit, self.npm_output, "")
        if "-e" in command:
            return CommandResult(list(command), self.check_exit, self.check_output, "")
        return CommandResult(list(command), 0, "", "")

    def unit_state(self, unit):
        return "active" if unit in self.active else "inactive"

    def systemctl(self):
        return [
            call
            for call in self.calls
            if call[0] == "systemctl" and not call[-1].endswith(".scope")
        ]

    def install_call(self):
        return next(call for call in self.calls if call[0] == "systemd-run")


@pytest.fixture
def machine(monkeypatch, tmp_path):
    held = Machine(str(tmp_path / "home" / "ann"))
    monkeypatch.setattr(applier_module, "unit_state", held.unit_state)
    return held


@pytest.fixture
def applier(machine, tmp_path):
    module_dir = tmp_path / "var" / "cloudcli"
    (module_dir / NODE_DIR / "bin").mkdir(parents=True)
    (module_dir / NODE_DIR / "bin" / "node").write_text("")
    (tmp_path / "systemd").mkdir()

    def lookup(account):
        if account != "ann":
            raise KeyError(account)
        return 1000, 1000, machine.home

    return CloudcliLinuxApplier(
        module_dir=str(module_dir),
        run=machine,
        lookup_account=lookup,
        etc_dir=str(tmp_path / "etc"),
        systemd_dir=str(tmp_path / "systemd"),
        log=lambda line: None,
    )


def test_the_template_runs_node_as_the_account_from_its_environment():
    unit = render_unit("/var/lib/neutrino/agent/cloudcli/n/bin/node", "/etc/x")

    assert "User=%i\n" in unit
    assert "EnvironmentFile=/etc/x/%i.env\n" in unit
    assert (
        "ExecStart=/var/lib/neutrino/agent/cloudcli/n/bin/node ${CLOUDCLI_SERVER}\n"
        in unit
    )


def test_an_environment_file_quotes_every_value():
    assert render_environment({"A": 'x "y" \\z'}) == 'A="x \\"y\\" \\\\z"\n'


def test_an_instance_is_installed_as_the_account_then_started(
    applier, machine, tmp_path
):
    notes = applier.apply(CONFIG, {"ann": 41234})

    assert machine.calls[0] == ["runuser", "-l", "ann", "-c", "command -v claude"]
    assert not [call for call in machine.calls if CLOUDCLI_CLAUDE_PLACES_SHELL in call]
    scoped = machine.install_call()
    assert scoped[: scoped.index("--")] == [
        "systemd-run",
        "--scope",
        "--quiet",
        "--unit=neutrino_cloudcli_install_ann.scope",
        "-p",
        "OOMPolicy=stop",
    ]
    install = scoped[scoped.index("--") + 1 :]
    app = os.path.join(
        machine.home, ".local", "share", "neutrino", "agent", "cloudcli", "app"
    )
    assert install[:6] == ["runuser", "-u", "ann", "--", "env", "-i"]
    assert f"npm_config_cache={app}/.npm" in install
    assert f"npm_config_userconfig={app}/.npmrc" in install
    assert f"HOME={machine.home}" in install
    assert install[-4:] == ["install", "@cloudcli-ai/cloudcli@1.37.3", "--prefix", app]
    assert install[install.index("sh") + 3] == app
    assert any("-e" in call for call in machine.calls[machine.calls.index(scoped) :])
    environment = tmp_path / "etc" / "ann.env"
    assert stat.S_IMODE(os.stat(environment).st_mode) == 0o600
    text = environment.read_text()
    assert 'HOST="127.0.0.1"\n' in text
    assert 'SERVER_PORT="41234"\n' in text
    assert "ANTHROPIC" not in text and "OPENAI" not in text
    node_bin = tmp_path / "var" / "cloudcli" / NODE_DIR / "bin"
    assert (
        f'PATH="{node_bin}:/home/ann/.local/bin:/usr/local/bin:/usr/bin:/bin"\n' in text
    )
    assert f'CLOUDCLI_SERVER="{app}/node_modules/@cloudcli-ai/cloudcli/' in text
    assert (tmp_path / "systemd" / "neutrino_cloudcli@.service").is_file()
    assert machine.systemctl() == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "neutrino_cloudcli@ann.service"],
        ["systemctl", "restart", "neutrino_cloudcli@ann.service"],
    ]
    assert notes == ["installed CloudCLI for ann", "started CloudCLI of ann"]


def test_an_unchanged_instance_is_only_kept_up(applier, machine):
    applier.apply(CONFIG, {"ann": 41234})
    machine.calls.clear()

    assert applier.apply(CONFIG, {"ann": 41234}) == []

    assert machine.systemctl() == [
        ["systemctl", "enable", "--now", "neutrino_cloudcli@ann.service"]
    ]
    assert not [call for call in machine.calls if "install" in call]


def test_an_account_without_claude_is_refused_before_anything_is_written(
    applier, machine, tmp_path
):
    machine.claude = ""

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert (caught.value.code, caught.value.params) == (
        "cloudcli_claude_missing",
        {"account": "ann"},
    )
    home = machine.home
    assert machine.calls[1] == [
        "runuser",
        "-u",
        "ann",
        "--",
        "sh",
        "-c",
        CLOUDCLI_CLAUDE_PLACES_SHELL,
        home,
        f"{home}/.local/bin/claude",
        f"{home}/.claude/local/claude",
        f"{home}/.npm-global/bin/claude",
        f"{home}/.volta/bin/claude",
        "/usr/local/bin/claude",
    ]
    assert not (tmp_path / "etc").exists()
    assert machine.systemctl() == []


def test_an_account_the_machine_lacks_is_refused(applier, machine):
    config = CloudcliConfig.from_dict(
        {
            "instances": [
                {
                    "account": "ghost",
                    "port": 3001,
                    "web_password": "p",
                    "token_secret": "s",
                }
            ]
        }
    )

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(config, {"ghost": 41234})

    assert caught.value.code == "account_unknown"
    assert machine.calls == []


def test_a_failed_npm_install_names_its_step(applier, machine):
    machine.npm_exit = 1
    machine.npm_output = "npm error code ECONNRESET"

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert caught.value.code == "cloudcli_npm_install_failed"
    assert machine.systemctl() == []


def test_a_native_module_without_its_binary_names_it(applier, machine):
    machine.check_exit = NATIVE_CHECK_EXIT
    machine.check_output = "better-sqlite3\n"

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert (caught.value.code, caught.value.params["module"]) == (
        "cloudcli_native_module_failed",
        "better-sqlite3",
    )


def test_no_node_is_a_failed_node_download(applier, machine, tmp_path):
    applier.module_dir = str(tmp_path / "empty")

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert caught.value.code == "cloudcli_node_download_failed"


def test_an_instance_no_longer_named_is_disabled_and_its_file_deleted(
    applier, machine, tmp_path
):
    applier.apply(CONFIG, {"ann": 41234})
    machine.calls.clear()

    applier.apply(CloudcliConfig.from_dict({}), {})

    assert ["systemctl", "disable", "--now", "neutrino_cloudcli@ann.service"] in (
        machine.calls
    )
    assert not (tmp_path / "etc" / "ann.env").exists()


def test_the_states_are_read_off_each_unit(applier, machine):
    machine.active.add("neutrino_cloudcli@ann.service")

    assert applier.states(["ann", "bob"]) == {
        "ann": {"is_running": True, "code": ""},
        "bob": {"is_running": False, "code": ""},
    }


def test_remove_withdraws_every_instance_and_the_template(applier, machine, tmp_path):
    applier.apply(CONFIG, {"ann": 41234})

    applier.remove()

    assert not (tmp_path / "systemd" / "neutrino_cloudcli@.service").exists()
    assert applier.units() == []


def test_the_account_reads_installing_while_its_npm_runs(applier, machine):
    seen = []
    answer = machine.__call__

    def run(command, **kwargs):
        if "install" in command:
            seen.append(applier.installing)
        return answer(command, **kwargs)

    applier._run = run
    applier.apply(CONFIG, {"ann": 41234})
    machine.npm_exit = 1
    applier.apply(CONFIG, {"ann": 41234})

    assert seen == [frozenset({"ann"})]
    assert applier.installing == frozenset()


def test_a_failed_install_reads_installing_no_more(applier, machine):
    machine.npm_exit = 1

    with pytest.raises(ModuleApplyError):
        applier.apply(CONFIG, {"ann": 41234})

    assert applier.installing == frozenset()


def test_an_install_the_kernel_killed_for_memory_is_its_own_refusal(applier, machine):
    machine.npm_exit = 137
    machine.scope_result = "oom-kill"

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert (caught.value.code, caught.value.params) == (
        "cloudcli_install_out_of_memory",
        {"account": "ann"},
    )
    assert [
        "systemctl",
        "reset-failed",
        "neutrino_cloudcli_install_ann.scope",
    ] in machine.calls
    assert applier.installing == frozenset()


def test_the_editions_npm_settings_reach_npm_and_a_half_install_is_cleared(
    applier, machine
):
    config = CloudcliConfig.from_dict(
        {
            "npm_registry": "https://registry.npmmirror.com",
            "npm_environment": {
                "npm_config_better_sqlite3_binary_host": "https://m.example/bs3",
                "PATH": "/evil",
            },
            "instances": [
                {
                    "account": "ann",
                    "port": 3001,
                    "web_password": "p",
                    "token_secret": "s",
                }
            ],
        }
    )
    lines = []
    applier._log = lines.append

    applier.apply(config, {"ann": 41234})

    install = machine.install_call()
    assert "npm_config_better_sqlite3_binary_host=https://m.example/bs3" in install
    assert "PATH=/evil" not in install
    assert 'rm -rf "$0/node_modules"' in install[install.index("sh") + 2]
    assert "cloudcli: installing CloudCLI for ann from registry.npmmirror.com" in lines


def test_an_instance_running_with_the_gateway_in_its_environment_is_restarted_once(
    applier, machine, tmp_path
):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "ann.env").write_text(
        'ANTHROPIC_BASE_URL="http://10.0.0.1:8317"\n'
    )
    applier.apply(CONFIG, {"ann": 41234})
    first = [call for call in machine.systemctl() if call[1] == "restart"]
    machine.calls.clear()

    applier.apply(CONFIG, {"ann": 41234})

    assert first == [["systemctl", "restart", "neutrino_cloudcli@ann.service"]]
    assert "ANTHROPIC" not in (tmp_path / "etc" / "ann.env").read_text()
    assert [call for call in machine.systemctl() if call[1] == "restart"] == []


def test_a_claude_the_login_shell_misses_is_taken_from_the_account_s_local_bin(
    applier, machine, tmp_path
):
    machine.claude = ""
    machine.places = f"/usr/local/bin/claude\n{machine.home}/.local/bin/claude\n"

    applier.apply(CONFIG, {"ann": 41234})

    text = (tmp_path / "etc" / "ann.env").read_text()
    node_bin = tmp_path / "var" / "cloudcli" / NODE_DIR / "bin"
    assert f'PATH="{node_bin}:{machine.home}/.local/bin:/usr/local/bin:' in text
    assert f'CLAUDE_CLI_PATH="{machine.home}/.local/bin/claude"\n' in text
