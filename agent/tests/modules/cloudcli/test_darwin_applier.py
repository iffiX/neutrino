"""CloudCLI on macOS, with launchd, the account database and stepping down faked.

What these pin: each instance is a root-only LaunchDaemon naming its
account in ``UserName``, running the unpacked Node.js with the account's
server script and an environment the plist holds; the ``claude`` the
account's login shell finds leads its ``PATH``; npm runs as the account;
a changed plist is loaded again and an unchanged loaded one is left; an
instance no longer named is unloaded with its files.
"""

import os
import plistlib
import stat

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli.config import CloudcliConfig
from neutrino_agent.modules.cloudcli.darwin_applier import CloudcliDarwinApplier
from neutrino_agent.modules.subprocess_run import CommandResult

NODE_DIR = "node-v22.23.3-darwin-arm64"
CONFIG = CloudcliConfig.from_dict(
    {
        "gateway_url": "http://10.0.0.1:8317",
        "gateway_key": "device-key",
        "instances": [
            {"account": "ann", "port": 3001, "web_password": "p", "token_secret": "s"}
        ],
    }
)


class Launchd:
    def __init__(self):
        self.calls: list = []
        self.loaded: set = set()

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        if command[:2] == ["launchctl", "print"]:
            label = command[2].split("/", 1)[1]
            is_loaded = label in self.loaded
            return CommandResult(
                list(command), 0 if is_loaded else 113, "state = running", ""
            )
        if command[:2] == ["launchctl", "bootstrap"]:
            self.loaded.add(os.path.basename(command[3])[: -len(".plist")])
        return CommandResult(list(command), 0, "", "")


class Account:
    """What ran as the account, and what it answered."""

    def __init__(self):
        self.calls: list = []
        self.claude = "/Users/ann/.local/bin/claude\n"

    def __call__(self, entry, command, *, environment, timeout_s):
        self.calls.append((entry[0], list(command), dict(environment)))
        if command[1:3] == ["-l", "-c"]:
            return CommandResult(list(command), 0, self.claude, "")
        if "install" in command:
            app = command[command.index("--prefix") + 1]
            package = os.path.join(app, "node_modules", "@cloudcli-ai", "cloudcli")
            os.makedirs(package, exist_ok=True)
            with open(os.path.join(package, "package.json"), "w") as stream:
                stream.write('{"version": "1.37.3"}')
        return CommandResult(list(command), 0, "", "")


@pytest.fixture
def launchd():
    return Launchd()


@pytest.fixture
def account():
    return Account()


@pytest.fixture
def applier(launchd, account, tmp_path):
    module_dir = tmp_path / "Neutrino" / "cloudcli"
    (module_dir / NODE_DIR / "bin").mkdir(parents=True)
    (module_dir / NODE_DIR / "bin" / "node").write_text("")
    (tmp_path / "LaunchDaemons").mkdir()
    home = str(tmp_path / "Users" / "ann")

    def lookup(name):
        if name != "ann":
            raise KeyError(name)
        return 501, 20, home, "/bin/zsh"

    held = CloudcliDarwinApplier(
        module_dir=str(module_dir),
        record_dir=str(tmp_path / "agent" / "cloudcli"),
        run=launchd,
        run_as=account,
        lookup_account=lookup,
        chown=lambda path, uid, gid: None,
        launchd_dir=str(tmp_path / "LaunchDaemons"),
        log_dir=str(tmp_path / "Logs"),
        log=lambda line: None,
    )
    held.home = home
    return held


def test_an_instance_is_a_root_only_launchdaemon_of_its_account(
    applier, launchd, account, tmp_path
):
    notes = applier.apply(CONFIG, {"ann": 41234})

    path = tmp_path / "LaunchDaemons" / "com.neutrino.cloudcli.ann.plist"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    plist = plistlib.loads(path.read_bytes())
    assert plist["UserName"] == "ann"
    assert plist["ProgramArguments"][0].endswith(f"{NODE_DIR}/bin/node")
    assert plist["ProgramArguments"][1].endswith(
        "Library/Application Support/Neutrino/cloudcli/app/node_modules/"
        "@cloudcli-ai/cloudcli/dist-server/server/index.js"
    )
    environment = plist["EnvironmentVariables"]
    assert environment["HOST"] == "127.0.0.1"
    assert environment["SERVER_PORT"] == "41234"
    assert environment["PATH"].startswith("/Users/ann/.local/bin:")
    assert environment["ANTHROPIC_AUTH_TOKEN"] == "device-key"
    assert plist["StandardOutPath"].endswith("Logs/cloudcli_ann.log")
    assert ["launchctl", "bootstrap", "system", str(path)] in launchd.calls
    assert account.calls[0][1] == ["/bin/zsh", "-l", "-c", "command -v claude"]
    install = account.calls[1]
    assert install[0] == 501
    assert install[1][-4:-1] == ["install", "@cloudcli-ai/cloudcli@1.37.3", "--prefix"]
    assert install[2]["npm_config_userconfig"].endswith("cloudcli/app/.npmrc")
    assert notes == ["installed CloudCLI for ann", "started CloudCLI of ann"]


def test_an_unchanged_loaded_instance_is_left(applier, launchd):
    applier.apply(CONFIG, {"ann": 41234})
    launchd.calls.clear()

    assert applier.apply(CONFIG, {"ann": 41234}) == []

    assert not [call for call in launchd.calls if call[1] == "bootstrap"]


def test_an_account_without_claude_is_refused(applier, account):
    account.claude = "zsh: command not found: claude\n"

    with pytest.raises(ModuleApplyError) as caught:
        applier.apply(CONFIG, {"ann": 41234})

    assert caught.value.code == "cloudcli_claude_missing"


def test_an_instance_no_longer_named_is_unloaded_with_its_files(
    applier, launchd, tmp_path
):
    applier.apply(CONFIG, {"ann": 41234})

    applier.apply(CloudcliConfig.from_dict({}), {})

    assert ["launchctl", "bootout", "system/com.neutrino.cloudcli.ann"] in launchd.calls
    assert os.listdir(tmp_path / "LaunchDaemons") == []


def test_the_states_and_the_logs_are_each_accounts(applier, launchd):
    applier.apply(CONFIG, {"ann": 41234})

    assert applier.states(["ann", "bob"]) == {
        "ann": {"is_running": True, "code": ""},
        "bob": {"is_running": False, "code": ""},
    }
    assert applier.log_paths(["ann"])[0][1].endswith("cloudcli_ann.log")
