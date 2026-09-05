"""The darwin and windows gaps: what a machine cannot do is said, not faked.

Every method the contract names belongs to one capability. A platform that
advertises the capability implements the method; one that does not refuses
with ``unsupported_platform``. The tables below are asserted complete, so a
new contract method without a stub answer fails here.
"""

import collections
import subprocess

import pytest

import neutrino_agent.platforms.darwin as darwin_module
import neutrino_agent.platforms.windows as windows_module
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform

# Contract method -> the capability it belongs to, and a call that reaches
# the platform's own answer.
CONTRACT_CALLS = {
    "human_accounts": ("accounts", (), {}),
    "account_home": ("account_files", ("alice",), {}),
    "control_socket_path": ("control_socket", (), {}),
    "read_peer_identity": ("control_socket", (object(),), {}),
    "run_as_account": ("run_as", ("alice", ["id"]), {}),
    "attach_share": (
        "shares",
        (),
        {
            "account": "alice",
            "share_url": "//hub/media",
            "username": "media",
            "password": "",
            "location": "/mnt/media",
            "credentials_path": "/c",
        },
    ),
    "detach_share": ("shares", (), {"location": "/mnt/media"}),
    "is_share_attached": ("shares", (), {"location": "/mnt/media"}),
    "install_system_packages": ("system_packages", (["cifs-utils"],), {}),
    "remove_system_packages": ("system_packages", (["cifs-utils"],), {}),
    "write_share_credentials": (
        "shares",
        (),
        {"credentials_path": "/c", "username": "media", "password": ""},
    ),
    "read_agent_service_state": ("agent_service", (), {}),
    "start_agent_service": ("agent_service", (), {}),
    "power": ("power", ("reboot",), {}),
    "read_host_metrics": ("metrics", (), {}),
    "install_package": (
        "packages",
        ("/tmp/app.deb",),
        {"package_kind": "deb", "entry": {}},
    ),
    "uninstall_package": ("packages", ("apt-get remove -y app",), {}),
    "install_openssh": ("openssh", ({},), {}),
    "uninstall_openssh": ("openssh", ({},), {}),
    "read_openssh_status": ("openssh", ({},), {}),
}

# Contract methods the base class implements for everyone: the file
# operations riding the step-down seam, and the capability question itself.
BASE_IMPLEMENTED = {
    "has_capability": "",
    "read_account_file": "account_files",
    "read_account_file_mode": "account_files",
    "write_account_file": "account_files",
    "remove_account_file": "account_files",
    "is_path_writable": "run_as",
    "list_directories": "run_as",
    "make_directory": "run_as",
    "has_mount_tooling": "shares",
}

DarwinPwdEntry = collections.namedtuple(
    "DarwinPwdEntry", "pw_name pw_uid pw_shell pw_dir"
)


def test_the_capability_tables_name_every_contract_method():
    contract_methods = {
        name
        for name in vars(AgentPlatform)
        if not name.startswith("_") and callable(getattr(AgentPlatform, name))
    }
    assert contract_methods == set(CONTRACT_CALLS) | set(BASE_IMPLEMENTED)

    named = {capability for capability, _, _ in CONTRACT_CALLS.values()}
    named |= {capability for capability in BASE_IMPLEMENTED.values() if capability}
    advertised = set()
    for platform in (LinuxPlatform(), DarwinPlatform(), WindowsPlatform()):
        advertised |= platform.capabilities
    assert named == advertised


@pytest.mark.parametrize("method_name", sorted(CONTRACT_CALLS))
def test_a_stub_implements_a_capability_or_refuses_it(method_name):
    capability, args, kwargs = CONTRACT_CALLS[method_name]
    for platform in (DarwinPlatform(), WindowsPlatform()):
        if platform.has_capability(capability):
            assert getattr(type(platform), method_name) is not getattr(
                AgentPlatform, method_name
            )
            continue
        with pytest.raises(PlatformUnsupportedError) as caught:
            getattr(platform, method_name)(*args, **kwargs)
        assert caught.value.code == "unsupported_platform"


def test_darwin_the_account_floor_is_the_platform_classes_own_number(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    assert darwin_module.DARWIN_HUMAN_UID_FLOOR == 501
    entries = [
        DarwinPwdEntry("root", 0, "/bin/sh", "/var/root"),
        DarwinPwdEntry("_spotlight", 89, "/usr/bin/false", str(home)),
        DarwinPwdEntry("under_the_floor", 500, "/bin/zsh", str(home)),
        DarwinPwdEntry("mia", 501, "/bin/zsh", str(home)),
        DarwinPwdEntry("shell_less", 502, "/usr/bin/false", str(home)),
        DarwinPwdEntry("homeless", 503, "/bin/zsh", str(tmp_path / "missing")),
    ]
    monkeypatch.setattr(darwin_module.pwd, "getpwall", lambda: entries)

    assert DarwinPlatform().human_accounts() == ["mia"]


def test_darwin_steps_down_with_su_never_sudo(monkeypatch):
    recorded = {}

    def record(command, **kwargs):
        recorded["command"] = list(command)
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(darwin_module.subprocess, "run", record)
    monkeypatch.setattr(darwin_module.os, "geteuid", lambda: 0)

    DarwinPlatform().run_as_account("alice", ["id", "-u"], stdin="typed")

    assert recorded["command"] == ["su", "-", "alice", "-c", "id -u"]
    assert "sudo" not in recorded["command"]
    assert recorded["kwargs"]["input"] == "typed"

    monkeypatch.setattr(darwin_module.os, "geteuid", lambda: 501)
    DarwinPlatform().run_as_account("alice", ["id", "-u"])

    assert recorded["command"] == ["id", "-u"]


def test_windows_account_work_is_file_work_under_the_profile(monkeypatch, tmp_path):
    """Windows cannot become another account, so the files go into the
    profile the account database names, never into the agent's own $HOME."""
    profiles = tmp_path / "Users"
    lying = tmp_path / "lying"
    monkeypatch.setattr(windows_module, "WINDOWS_PROFILES_DIR", str(profiles))
    monkeypatch.setenv("HOME", str(lying))
    monkeypatch.setenv("USERPROFILE", str(lying))
    platform = WindowsPlatform()

    assert platform.account_home("bob") == str(profiles / "bob")
    platform.write_account_file(
        account="bob", relative=".codex/config.toml", text="model = 'x'", mode="600"
    )

    assert (profiles / "bob" / ".codex" / "config.toml").read_text() == "model = 'x'"
    assert not lying.exists()
    assert (
        platform.read_account_file(account="bob", relative=".codex/config.toml")
        == "model = 'x'"
    )
    assert (
        platform.read_account_file_mode(account="bob", relative=".codex/config.toml")
        == ""
    )

    platform.remove_account_file(account="bob", relative=".codex/config.toml")
    assert (
        platform.read_account_file(account="bob", relative=".codex/config.toml") == ""
    )
    platform.remove_account_file(account="bob", relative=".codex/config.toml")
