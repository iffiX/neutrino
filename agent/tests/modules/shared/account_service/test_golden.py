"""The service texts of VS Code, code-server, CloudCLI and Codeg, pinned byte for byte.

The fixtures under ``golden/`` were rendered by the code before the shared
account service layer existed, and the hooks of each module through the
layer render the same texts now, with one change: CloudCLI's Node.js is its
``node`` component, so every path that named ``node-v<version>-<os>-<arch>``
names ``node``. Codeg's were rendered by its hooks through the layer when
the module arrived. What these pin: the unit templates, the environment
files, the LaunchDaemon plists, the Windows task arguments and scripts, and
the install commands each module produces for fixed inputs.
"""

import json
import ntpath
import os
from pathlib import Path

from neutrino_agent.modules.cloudcli.config import CloudcliConfig, jwt_secret
from neutrino_agent.modules.cloudcli.hooks import CloudcliHooks
from neutrino_agent.modules.code_server.config import CodeServerConfig
from neutrino_agent.modules.code_server.hooks import CodeServerHooks
from neutrino_agent.modules.codeg.config import CodegConfig, instance_token
from neutrino_agent.modules.codeg.hooks import CodegHooks
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    ServiceMachine,
)
from neutrino_agent.modules.shared.account_service import darwin as darwin_layer
from neutrino_agent.modules.shared.account_service import linux as linux_layer
from neutrino_agent.modules.shared.account_service import windows as windows_layer
from neutrino_agent.modules.shared.instances import NOBODY, TEMPLATE_ACCOUNT
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.hooks import VscodeHooks
from neutrino_agent.platforms.base import AgentPlatform

GOLDEN = Path(__file__).parent / "golden"
LINUX_STATE = "/var/lib/neutrino/agent"
LINUX_CONFIG = "/etc/neutrino/agent"
MAC_STATE = "/Library/Application Support/Neutrino/agent/state"
MAC_CONFIG = "/Library/Application Support/Neutrino/agent/config"
WIN_STATE = "C:\\ProgramData\\Neutrino\\agent\\state"
WIN_CONFIG = "C:\\ProgramData\\Neutrino\\agent\\config"
WIN_HOME = "C:\\Users\\ann"
# The node component's directory, where the hub's archive lands without its
# own top directory.
LINUX_NODE_DIR = "node"
MAC_NODE_DIR = "node"
WIN_NODE_DIR = "node"
ANN = AccountEntry(1000, 1000, "/home/ann", "/bin/bash")
MAC_ANN = AccountEntry(501, 20, "/Users/ann", "/bin/zsh")
WIN_ANN = AccountEntry(0, 0, WIN_HOME, "")
CLOUDCLI_INSTANCE = CloudcliConfig.from_dict(
    {
        "instances": [
            {
                "account": "ann",
                "port": 3001,
                "web_password": "p",
                "token_secret": "s",
                "password": "login-pw",
            }
        ]
    }
).instances[0]
CLOUDCLI_RECORD = {"upstream_port": 41234, "database": "auth.db"}
CLOUDCLI_CONFIG = CloudcliConfig.from_dict(
    {
        "npm_registry": "https://registry.npmmirror.com",
        "npm_environment": {
            "npm_config_better_sqlite3_binary_host": "https://m.example/bs3"
        },
        "instances": [
            {"account": "ann", "port": 3001, "web_password": "p", "token_secret": "s"}
        ],
    }
)


class Platform(AgentPlatform):
    def __init__(self, os_name):
        self.os_name = os_name


def golden_text(name: str) -> str:
    return (GOLDEN / name).read_bytes().decode("utf-8")


def golden_json(name: str) -> dict:
    return json.loads(golden_text(name))


def masked(text: str) -> str:
    """The text with the secrets derived from the test secret taken out."""
    return text.replace(jwt_secret("s"), "{jwt_secret}").replace(
        instance_token("s"), "{codeg_token}"
    )


def machine_for(os_name: str, module: str, state: str, config: str, **tools):
    join = ntpath.join if os_name == "windows" else os.path.join
    return ServiceMachine(
        os_name=os_name,
        module_dir=join(state, module),
        record_dir=join(config, module),
        lookup_account=lambda account: None,
        **tools,
    )


def bound(hooks_class, os_name: str, machine, **kwargs):
    hooks = hooks_class(platform=Platform(os_name), log=lambda line: None, **kwargs)
    hooks.bind(machine, None)
    return hooks


def template_of(hooks):
    instance = hooks.instance_class.from_dict({"account": TEMPLATE_ACCOUNT})
    return hooks.service(instance, NOBODY, {})


def unit_text(hooks, machine) -> str:
    template = template_of(hooks)
    return linux_layer.render_unit(
        template, environment_dir=template.environment_dir or machine.record_dir
    )


def environment_text(service) -> str:
    return linux_layer.render_environment(
        service.environment, is_quoted=service.is_environment_secret
    )


def plist_text(service, machine, entry) -> str:
    log = darwin_layer.log_path(
        service.name, service.account, machine, service.log_name
    )
    return darwin_layer.render_plist(service, home=entry.home, log_path=log).decode()


# --- VS Code ---


def vscode_instance(host="127.0.0.1"):
    config = VscodeConfig.from_dict(
        {"address": "", "instances": [{"account": "ann", "port": 8000, "token": "t"}]}
    )
    return config.instances[0], {"host": host, "port": 8000}


def test_vscode_linux_unit_and_environment():
    machine = machine_for("linux", "vscode", LINUX_STATE, LINUX_CONFIG)
    hooks = bound(VscodeHooks, "linux", machine)
    instance, record = vscode_instance()

    service = hooks.service(instance, ANN, record)

    assert unit_text(hooks, machine) == golden_text("vscode_linux_unit.service")
    assert environment_text(service) == golden_text("vscode_linux_environment.env")


def test_vscode_darwin_plist():
    machine = machine_for("darwin", "vscode", MAC_STATE, MAC_CONFIG)
    hooks = bound(VscodeHooks, "darwin", machine)
    instance, record = vscode_instance()

    service = hooks.service(instance, MAC_ANN, record)

    assert plist_text(service, machine, MAC_ANN) == golden_text("vscode_darwin.plist")


def test_vscode_windows_arguments():
    machine = machine_for("windows", "vscode", WIN_STATE, WIN_CONFIG)
    hooks = bound(VscodeHooks, "windows", machine)
    config = VscodeConfig.from_dict(
        {
            "instances": [
                {"account": "hanha", "port": 8000, "token": "t", "password": "pw"}
            ]
        }
    )

    service = hooks.service(config.instances[0], WIN_ANN, {"host": "127.0.0.1"})

    assert windows_layer.arguments_of(service, machine) == (
        golden_json("vscode_windows.json")["arguments"]
    )


# --- code-server ---


def code_server_instance():
    config = CodeServerConfig.from_dict(
        {"instances": [{"account": "ann", "port": 8443, "secret": "s"}]}
    )
    return config.instances[0], {"account": "ann", "port": 8443, "secret": "s"}


def test_code_server_linux_unit():
    machine = machine_for("linux", "code_server", LINUX_STATE, LINUX_CONFIG)
    hooks = bound(CodeServerHooks, "linux", machine)

    assert unit_text(hooks, machine) == golden_text("code_server_linux_unit.service")


def test_code_server_darwin_plist():
    machine = machine_for("darwin", "code_server", MAC_STATE, MAC_CONFIG)
    hooks = bound(CodeServerHooks, "darwin", machine)
    instance, record = code_server_instance()

    service = hooks.service(instance, MAC_ANN, record)

    assert plist_text(service, machine, MAC_ANN) == golden_text(
        "code_server_darwin.plist"
    )


# --- CloudCLI ---


def cloudcli_machine(os_name, config, tmp_path, node_dir, **tools):
    """A CloudCLI machine whose module directory holds one Node.js, under a fixed name."""
    module_dir = tmp_path / "state" / "cloudcli"
    bin_dir = module_dir / node_dir / ("" if os_name == "windows" else "bin")
    bin_dir.mkdir(parents=True)
    (bin_dir / ("node.exe" if os_name == "windows" else "node")).write_text("")
    join = ntpath.join if os_name == "windows" else os.path.join
    return ServiceMachine(
        os_name=os_name,
        module_dir=str(module_dir),
        record_dir=join(config, "cloudcli"),
        lookup_account=lambda account: None,
        **tools,
    )


def with_fixed_state(text: str, tmp_path, state: str) -> str:
    """The text with the test's module directory read as the real state root.

    The Node.js directory is found by listing the test's own directory, so
    on a Windows state root its separators are the host's until here.
    """
    held = str(tmp_path / "state")
    text = text.replace(held.replace("/", "\\"), state).replace(held, state)
    if "\\" in state:
        text = text.replace(state + "/cloudcli", state + "\\cloudcli")
        text = text.replace("\\cloudcli/", "\\cloudcli\\")
    return text


def test_cloudcli_linux_unit_and_environment(tmp_path):
    machine = cloudcli_machine("linux", LINUX_CONFIG, tmp_path, LINUX_NODE_DIR)
    hooks = bound(CloudcliHooks, "linux", machine)

    unit = unit_text(hooks, machine)
    service = hooks.service(CLOUDCLI_INSTANCE, ANN, CLOUDCLI_RECORD)

    assert with_fixed_state(unit, tmp_path, LINUX_STATE) == golden_text(
        "cloudcli_linux_unit.service"
    )
    assert masked(
        with_fixed_state(environment_text(service), tmp_path, LINUX_STATE)
    ) == golden_text("cloudcli_linux_environment.env")


def test_cloudcli_darwin_plist(tmp_path):
    machine = cloudcli_machine("darwin", MAC_CONFIG, tmp_path, MAC_NODE_DIR)
    hooks = bound(CloudcliHooks, "darwin", machine)

    service = hooks.service(CLOUDCLI_INSTANCE, MAC_ANN, CLOUDCLI_RECORD)

    plist = with_fixed_state(plist_text(service, machine, MAC_ANN), tmp_path, MAC_STATE)
    assert masked(plist) == golden_text("cloudcli_darwin.plist")


def test_cloudcli_windows_script_and_arguments(tmp_path):
    machine = cloudcli_machine("windows", WIN_CONFIG, tmp_path, WIN_NODE_DIR)
    hooks = bound(CloudcliHooks, "windows", machine)
    texts = golden_json("cloudcli_windows.json")

    service = hooks.service(CLOUDCLI_INSTANCE, WIN_ANN, CLOUDCLI_RECORD)
    script = with_fixed_state(windows_layer.render_script(service), tmp_path, WIN_STATE)
    arguments = windows_layer.arguments_of(
        service, machine_for("windows", "cloudcli", WIN_STATE, WIN_CONFIG)
    )

    assert masked(script) == texts["script"]
    assert arguments == texts["arguments"]


def test_cloudcli_windows_install_script_and_arguments(tmp_path):
    runs = []

    def powershell(script, document, timeout_s=120):
        runs.append((script, document))
        return {"tasks": []}

    machine = cloudcli_machine(
        "windows", WIN_CONFIG, tmp_path, WIN_NODE_DIR, powershell=powershell
    )
    hooks = bound(CloudcliHooks, "windows", machine)
    texts = golden_json("cloudcli_windows.json")
    config = CloudcliConfig.from_dict(
        {
            "npm_registry": "https://registry.npmmirror.com",
            "npm_environment": {
                "npm_config_better_sqlite3_binary_host": "https://m.example/bs3"
            },
            "instances": [
                {
                    "account": "ann",
                    "port": 3001,
                    "web_password": "p",
                    "token_secret": "s",
                    "password": "login-pw",
                }
            ],
        }
    )

    hooks.prepare_module()
    hooks.prepare(config, config.instances[0], WIN_ANN)

    _script, document = runs[1]
    assert with_fixed_state(document["script_text"], tmp_path, WIN_STATE) == (
        texts["install_script"]
    )
    assert with_fixed_state(document["arguments"], tmp_path, WIN_STATE) == (
        texts["install_arguments"]
    )


# --- Codeg ---

CODEG_RECORD = {"account": "ann", "port": 3101, "upstream_port": 41234, "secret": "s"}


def codeg_instance(password=""):
    config = CodegConfig.from_dict(
        {
            "instances": [
                {"account": "ann", "port": 3101, "secret": "s", "password": password}
            ]
        }
    )
    return config.instances[0]


def test_codeg_linux_unit_and_environment():
    machine = machine_for("linux", "codeg", LINUX_STATE, LINUX_CONFIG)
    hooks = bound(CodegHooks, "linux", machine)

    service = hooks.service(codeg_instance(), ANN, CODEG_RECORD)

    assert unit_text(hooks, machine) == golden_text("codeg_linux_unit.service")
    assert masked(environment_text(service)) == golden_text(
        "codeg_linux_environment.env"
    )


def test_codeg_darwin_plist():
    machine = machine_for("darwin", "codeg", MAC_STATE, MAC_CONFIG)
    hooks = bound(CodegHooks, "darwin", machine)

    service = hooks.service(codeg_instance(), MAC_ANN, CODEG_RECORD)

    assert masked(plist_text(service, machine, MAC_ANN)) == golden_text(
        "codeg_darwin.plist"
    )


def test_codeg_windows_script_and_arguments():
    machine = machine_for("windows", "codeg", WIN_STATE, WIN_CONFIG)
    hooks = bound(CodegHooks, "windows", machine)
    texts = golden_json("codeg_windows.json")

    service = hooks.service(codeg_instance("login-pw"), WIN_ANN, CODEG_RECORD)

    assert masked(windows_layer.render_script(service)) == texts["script"]
    assert windows_layer.arguments_of(service, machine) == texts["arguments"]


class Recorder:
    """systemctl, systemd-run and runuser, recorded; npm lands the package."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append((list(command), timeout_s))
        if command[0] == "systemd-run":
            _land_package(command[command.index("--prefix") + 1])
        return CommandResult(list(command), 0, "success\n", "")


class AccountRecorder:
    """What ran as the account on a Mac, with which environment."""

    def __init__(self):
        self.calls: list = []

    def __call__(self, entry, command, *, environment, timeout_s):
        self.calls.append((entry, list(command), dict(environment), timeout_s))
        if "install" in command:
            _land_package(command[command.index("--prefix") + 1])
        return CommandResult(list(command), 0, "", "")


def _land_package(app: str) -> None:
    package = os.path.join(app, "node_modules", "@cloudcli-ai", "cloudcli")
    os.makedirs(package, exist_ok=True)
    with open(os.path.join(package, "package.json"), "w", encoding="utf-8") as stream:
        stream.write('{"version": "1.37.3"}')


def test_cloudcli_linux_install_commands(tmp_path):
    root = str(tmp_path)
    recorder = Recorder()
    module_dir = os.path.join(root, "var", "cloudcli")
    os.makedirs(os.path.join(module_dir, LINUX_NODE_DIR, "bin"))
    open(os.path.join(module_dir, LINUX_NODE_DIR, "bin", "node"), "w").close()
    machine = ServiceMachine(
        os_name="linux",
        module_dir=module_dir,
        record_dir=os.path.join(root, "etc"),
        lookup_account=lambda account: None,
        run=recorder,
    )
    hooks = bound(CloudcliHooks, "linux", machine)
    home = os.path.join(root, "home", "ann")

    hooks.prepare(
        CLOUDCLI_CONFIG, CLOUDCLI_CONFIG.instances[0], AccountEntry(1000, 1000, home)
    )

    lines = [
        json.dumps([timeout_s] + [part.replace(root, "{root}") for part in command])
        for command, timeout_s in recorder.calls
    ]
    expected = golden_text("cloudcli_linux_install_commands.jsonl").splitlines()
    assert lines == expected[:3]


def test_cloudcli_darwin_install_commands(tmp_path):
    root = str(tmp_path)
    module_dir = os.path.join(root, "Neutrino", "cloudcli")
    os.makedirs(os.path.join(module_dir, MAC_NODE_DIR, "bin"))
    open(os.path.join(module_dir, MAC_NODE_DIR, "bin", "node"), "w").close()
    machine = ServiceMachine(
        os_name="darwin",
        module_dir=module_dir,
        record_dir=os.path.join(root, "agent", "cloudcli"),
        lookup_account=lambda account: None,
    )
    account = AccountRecorder()
    hooks = bound(CloudcliHooks, "darwin", machine, run_as=account)
    home = os.path.join(root, "Users", "ann")

    hooks.prepare(
        CLOUDCLI_CONFIG,
        CLOUDCLI_CONFIG.instances[0],
        AccountEntry(501, 20, home, "/bin/zsh"),
    )

    lines = [
        json.dumps(
            {
                "uid": entry.uid,
                "timeout_s": timeout_s,
                "command": [part.replace(root, "{root}") for part in command],
                "environment": {
                    key: value.replace(root, "{root}")
                    for key, value in environment.items()
                },
            }
        )
        for entry, command, environment, timeout_s in account.calls
    ]
    assert lines == golden_text("cloudcli_darwin_install_commands.jsonl").splitlines()
