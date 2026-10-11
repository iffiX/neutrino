"""The service texts of VS Code, code-server and CloudCLI, pinned byte for byte.

The fixtures under ``golden/`` were rendered by the code before the shared
account service layer existed. What these pin: the unit templates, the
environment files, the LaunchDaemon plists, the Windows task arguments and
scripts, and the install commands each module produces for fixed inputs.
"""

import json
import ntpath
import os
from pathlib import Path

from neutrino_agent.modules.cloudcli import darwin_applier as cloudcli_darwin
from neutrino_agent.modules.cloudcli import installer as cloudcli_installer
from neutrino_agent.modules.cloudcli import linux_applier as cloudcli_linux
from neutrino_agent.modules.cloudcli import windows_applier as cloudcli_windows
from neutrino_agent.modules.cloudcli.config import CloudcliConfig, jwt_secret
from neutrino_agent.modules.code_server import darwin_applier as code_server_darwin
from neutrino_agent.modules.code_server import installer as code_server_installer
from neutrino_agent.modules.code_server import linux_applier as code_server_linux
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.modules.vscode import darwin_applier as vscode_darwin
from neutrino_agent.modules.vscode import linux_applier as vscode_linux
from neutrino_agent.modules.vscode import windows_applier as vscode_windows
from neutrino_agent.modules.vscode.constants import VSCODE_SERVE_ARGUMENTS

GOLDEN = Path(__file__).parent / "golden"
MAC_STATE = "/Library/Application Support/Neutrino/agent/state"
WIN_STATE = "C:\\ProgramData\\Neutrino\\agent\\state"
WIN_HOME = "C:\\Users\\ann"
LINUX_NODE = "/var/lib/neutrino/agent/cloudcli/node-v22.23.3-linux-x64/bin/node"
MAC_NODE = MAC_STATE + "/cloudcli/node-v22.23.3-darwin-arm64/bin/node"
WIN_NODE = WIN_STATE + "\\cloudcli\\node-v22.23.3-win-x64\\node.exe"
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


def golden_text(name: str) -> str:
    return (GOLDEN / name).read_bytes().decode("utf-8")


def golden_json(name: str) -> dict:
    return json.loads(golden_text(name))


def masked(text: str) -> str:
    """The text with the login secret derived from the test secret taken out."""
    return text.replace(jwt_secret("s"), "{jwt_secret}")


def golden_bytes(name: str) -> bytes:
    return (GOLDEN / name).read_bytes()


def test_vscode_linux_unit_and_environment():
    unit = vscode_linux.render_unit(
        "/var/lib/neutrino/agent/vscode/code", "/var/lib/neutrino/agent/vscode/tokens"
    )
    environment = vscode_linux.render_environment(
        "127.0.0.1", 8000, "/var/lib/neutrino/agent/vscode/tokens/ann.token"
    )

    assert unit == golden_text("vscode_linux_unit.service")
    assert environment == golden_text("vscode_linux_environment.env")


def test_vscode_darwin_plist():
    plist = vscode_darwin.render_plist(
        label="com.neutrino.vscode.ann",
        account="ann",
        cli_path=MAC_STATE + "/vscode/code",
        host="127.0.0.1",
        port=8000,
        token_path=MAC_STATE + "/vscode/tokens/ann.token",
        log_path="/Library/Logs/Neutrino/agent/vscode_ann.log",
    )

    assert plist == golden_bytes("vscode_darwin.plist")


def test_vscode_windows_arguments():
    arguments = vscode_windows.task_arguments(
        WIN_STATE + "\\vscode\\code.exe",
        [
            *VSCODE_SERVE_ARGUMENTS,
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--connection-token-file",
            WIN_STATE + "\\vscode\\tokens\\hanha.token",
        ],
        WIN_STATE + "\\vscode\\hanha.log",
    )

    assert arguments == golden_json("vscode_windows.json")["arguments"]


def test_code_server_linux_unit():
    unit = code_server_linux.render_unit("/var/lib/neutrino/agent/code_server")

    assert unit == golden_text("code_server_linux_unit.service")


def test_code_server_darwin_plist():
    plist = code_server_darwin.render_plist(
        label="com.neutrino.code_server.ann",
        account="ann",
        arguments=code_server_installer.server_arguments(
            MAC_STATE + "/code_server", "ann"
        ),
        home="/Users/ann",
        shell="/bin/zsh",
        log_path="/Library/Logs/Neutrino/agent/code_server_ann.log",
    )

    assert plist == golden_bytes("code_server_darwin.plist")


def test_cloudcli_linux_unit_and_environment():
    unit = cloudcli_linux.render_unit(LINUX_NODE, "/etc/neutrino/agent/cloudcli")
    environment = cloudcli_installer.service_environment(
        CLOUDCLI_INSTANCE,
        upstream_port=41234,
        home="/home/ann",
        os_name="linux",
        node_dir=os.path.dirname(LINUX_NODE),
    )
    environment[cloudcli_linux.SERVER_VARIABLE] = cloudcli_installer.server_path(
        cloudcli_installer.app_dir("/home/ann", "linux")
    )

    assert unit == golden_text("cloudcli_linux_unit.service")
    assert masked(cloudcli_linux.render_environment(environment)) == golden_text(
        "cloudcli_linux_environment.env"
    )


def test_cloudcli_darwin_plist():
    plist = cloudcli_darwin.render_plist(
        label="com.neutrino.cloudcli.ann",
        account="ann",
        node=MAC_NODE,
        server=cloudcli_installer.server_path(
            cloudcli_installer.app_dir("/Users/ann", "darwin")
        ),
        home="/Users/ann",
        environment=cloudcli_installer.service_environment(
            CLOUDCLI_INSTANCE,
            upstream_port=41234,
            home="/Users/ann",
            os_name="darwin",
            node_dir=os.path.dirname(MAC_NODE),
        ),
        log_path="/Library/Logs/Neutrino/agent/cloudcli_ann.log",
    )

    assert masked(plist.decode("utf-8")) == golden_text("cloudcli_darwin.plist")


def test_cloudcli_windows_script_and_arguments():
    app = cloudcli_installer.app_dir(WIN_HOME, "windows", join=ntpath.join)
    script = cloudcli_windows.render_script(
        cloudcli_installer.service_environment(
            CLOUDCLI_INSTANCE,
            upstream_port=41234,
            home=WIN_HOME,
            os_name="windows",
            node_dir=ntpath.dirname(WIN_NODE),
            join=ntpath.join,
        ),
        node=WIN_NODE,
        server=cloudcli_installer.server_path(app, join=ntpath.join),
    )
    arguments = cloudcli_windows.task_arguments(
        WIN_STATE + "\\cloudcli\\run\\ann.cmd", [], WIN_STATE + "\\cloudcli\\ann.log"
    )
    install_script = cloudcli_windows.render_install_script(
        app=app,
        node=WIN_NODE,
        npm=ntpath.join(
            ntpath.dirname(WIN_NODE), "node_modules", "npm", "bin", "npm-cli.js"
        ),
        registry="https://registry.npmmirror.com",
        extra={"npm_config_better_sqlite3_binary_host": "https://m.example/bs3"},
    )
    install_arguments = cloudcli_windows.task_arguments(
        WIN_STATE + "\\cloudcli\\run\\install_ann.cmd",
        [],
        WIN_STATE + "\\cloudcli\\run\\install_ann.log",
    )

    texts = golden_json("cloudcli_windows.json")
    assert masked(script) == texts["script"]
    assert arguments == texts["arguments"]
    assert install_script == texts["install_script"]
    assert install_arguments == texts["install_arguments"]


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


def _unloaded(command, *, is_checked=True, input_text=None, timeout_s=0):
    return CommandResult(list(command), 113, "", "")


def test_cloudcli_linux_install_commands(tmp_path):
    root = str(tmp_path)
    module_dir = os.path.join(root, "var", "cloudcli")
    os.makedirs(os.path.join(module_dir, "node-v22.23.3-linux-x64", "bin"))
    open(
        os.path.join(module_dir, "node-v22.23.3-linux-x64", "bin", "node"), "w"
    ).close()
    os.makedirs(os.path.join(root, "systemd"))
    home = os.path.join(root, "home", "ann")
    recorder = Recorder()
    applier = cloudcli_linux.CloudcliLinuxApplier(
        module_dir=module_dir,
        etc_dir=os.path.join(root, "etc"),
        run=recorder,
        lookup_account=lambda account: (1000, 1000, home),
        systemd_dir=os.path.join(root, "systemd"),
        log=lambda line: None,
    )

    applier.apply(CLOUDCLI_CONFIG, {"ann": 41234})

    lines = [
        json.dumps([timeout_s] + [part.replace(root, "{root}") for part in command])
        for command, timeout_s in recorder.calls
    ]
    assert lines == golden_text("cloudcli_linux_install_commands.jsonl").splitlines()


def test_cloudcli_darwin_install_commands(tmp_path):
    root = str(tmp_path)
    module_dir = os.path.join(root, "Neutrino", "cloudcli")
    os.makedirs(os.path.join(module_dir, "node-v22.23.3-darwin-arm64", "bin"))
    open(
        os.path.join(module_dir, "node-v22.23.3-darwin-arm64", "bin", "node"), "w"
    ).close()
    os.makedirs(os.path.join(root, "LaunchDaemons"))
    home = os.path.join(root, "Users", "ann")
    account = AccountRecorder()
    applier = cloudcli_darwin.CloudcliDarwinApplier(
        module_dir=module_dir,
        record_dir=os.path.join(root, "agent", "cloudcli"),
        run=_unloaded,
        run_as=account,
        lookup_account=lambda name: (501, 20, home, "/bin/zsh"),
        chown=lambda path, uid, gid: None,
        launchd_dir=os.path.join(root, "LaunchDaemons"),
        log_dir=os.path.join(root, "Logs"),
        log=lambda line: None,
    )

    applier.apply(CLOUDCLI_CONFIG, {"ann": 41234})

    lines = [
        json.dumps(
            {
                "uid": entry[0],
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
