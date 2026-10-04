"""The platform contract: advertised capabilities, honest refusals.

A platform says what it has; invoking what it lacks answers
``unsupported_platform``, never a guess. The capability table is asserted
complete, so a new contract method without a capability fails here.
"""

import pytest

import neutrino_agent.platforms.base as base_module
from neutrino_agent.constants import (
    AGENT_CONFIGURED_DIR,
    AGENT_PACKAGE_DIR,
    AGENT_STATE_PATH,
)
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform

PLATFORM_CLASSES = (LinuxPlatform, WindowsPlatform, DarwinPlatform)

# Contract method -> the capability it belongs to, and a call that reaches
# the platform's own answer.
CONTRACT_CALLS = {
    "human_accounts": ("accounts", (), {}),
    "account_home": ("accounts", ("alice",), {}),
    "control_socket_path": ("control_socket", (), {}),
    "run_as_account": ("run_as", ("alice", ["id"]), {}),
    "install_system_packages": ("system_packages", (["cifs-utils"],), {}),
    "remove_system_packages": ("system_packages", (["cifs-utils"],), {}),
    "read_agent_service_state": ("agent_service", (), {}),
    "start_agent_service": ("agent_service", (), {}),
    "stop_agent_service": ("agent_service", (), {}),
    "power": ("power", ("reboot",), {}),
    "read_host_metrics": ("metrics", (), {}),
    "read_network_interfaces": ("network", (), {}),
    "read_machine_id": ("machine_id", (), {}),
    "install_package": (
        "packages",
        ("/tmp/app.deb",),
        {"package_kind": "deb", "entry": {}},
    ),
    "uninstall_package": ("packages", ("apt-get remove -y app",), {}),
    "smb_server_applier": ("smb_server", (), {}),
    "terminate_process": ("process_terminate", (4242,), {}),
    "remove_added": ("removal", (), {}),
    "remove_agent_program": ("self_removal", (), {}),
}

# Capabilities only a system that carries its own server, has no signals,
# or has no uninstaller has; Linux has every other one.
NOT_ON_LINUX = {"smb_server", "hub_packages", "process_terminate", "self_removal"}

# Contract methods the base class answers for everyone.
BASE_IMPLEMENTED = {
    "agent_log_path": "",
    "agent_data_dir": "",
    "agent_var_dir": "",
    "agent_service_start_hint": "agent_service",
    "open_to_accounts": "hub_packages",
}


def test_the_capability_table_names_every_contract_method():
    contract_methods = {
        name
        for name in vars(AgentPlatform)
        if not name.startswith("_") and callable(getattr(AgentPlatform, name))
    }
    assert contract_methods == set(CONTRACT_CALLS) | set(BASE_IMPLEMENTED)

    named = {capability for capability, _, _ in CONTRACT_CALLS.values()}
    named |= {capability for capability in BASE_IMPLEMENTED.values() if capability}
    assert named == LinuxPlatform().capabilities | NOT_ON_LINUX


@pytest.mark.parametrize("method_name", sorted(CONTRACT_CALLS))
def test_the_base_contract_refuses_every_capability(method_name):
    _capability, args, kwargs = CONTRACT_CALLS[method_name]

    with pytest.raises(PlatformUnsupportedError) as caught:
        getattr(AgentPlatform(), method_name)(*args, **kwargs)

    assert caught.value.code == "unsupported_platform"


@pytest.mark.parametrize("platform_class", PLATFORM_CLASSES)
@pytest.mark.parametrize("method_name", sorted(CONTRACT_CALLS))
def test_a_platform_implements_exactly_the_capabilities_it_advertises(
    platform_class, method_name
):
    capability = CONTRACT_CALLS[method_name][0]
    is_implemented = getattr(platform_class, method_name) is not getattr(
        AgentPlatform, method_name
    )

    assert is_implemented == (capability in platform_class.capabilities)


@pytest.mark.parametrize("platform_class", PLATFORM_CLASSES)
def test_a_platform_advertises_only_capabilities_the_contract_names(platform_class):
    named = {capability for capability, _, _ in CONTRACT_CALLS.values()}
    named |= {capability for capability in BASE_IMPLEMENTED.values() if capability}

    assert platform_class.capabilities <= named


def test_windows_and_macos_install_nothing_and_step_down_to_nobody():
    for platform_class in (WindowsPlatform, DarwinPlatform):
        assert "packages" not in platform_class.capabilities
        assert "system_packages" not in platform_class.capabilities
        assert "run_as" not in platform_class.capabilities
    assert "accounts" in WindowsPlatform.capabilities
    assert "accounts" in DarwinPlatform.capabilities


def test_the_base_platform_advertises_nothing():
    assert AgentPlatform().capabilities == frozenset()


def test_the_agent_data_root_defaults_to_the_posix_directory(monkeypatch):
    # The suite-wide fixture redirects the root off the machine; the real
    # value is put back here to pin it with the path that hangs off it.
    monkeypatch.setattr(base_module, "AGENT_DATA_DIR_POSIX", "/etc/neutrino/agent")

    assert AgentPlatform().agent_data_dir() == "/etc/neutrino/agent"
    assert AGENT_STATE_PATH == "/etc/neutrino/agent/state.json"


def test_the_agent_state_root_defaults_to_the_linux_directory(monkeypatch):
    monkeypatch.setattr(base_module, "AGENT_VAR_DIR", "/var/lib/neutrino/agent")

    assert AgentPlatform().agent_var_dir() == "/var/lib/neutrino/agent"
    assert AGENT_CONFIGURED_DIR == "/var/lib/neutrino/agent/configured"
    assert AGENT_PACKAGE_DIR == "/var/lib/neutrino/agent/packages"


def test_a_directory_opened_to_accounts_is_mode_755(tmp_path):
    directory = tmp_path / "vscode"
    directory.mkdir(mode=0o700)

    AgentPlatform().open_to_accounts(str(directory))

    assert directory.stat().st_mode & 0o777 == 0o755


def test_the_base_start_hint_is_empty_rather_than_another_platforms():
    assert AgentPlatform().agent_service_start_hint() == ""


def test_base_account_home_refuses_rather_than_reading_the_environment(monkeypatch):
    """A root agent's $HOME names root's home, never the account's."""
    monkeypatch.setenv("HOME", "/home/lying")

    with pytest.raises(PlatformUnsupportedError) as caught:
        AgentPlatform().account_home("alice")

    assert caught.value.code == "unsupported_platform"


@pytest.mark.parametrize(
    "name, prefix",
    [
        ("neutrino_vscode@ann.service", "neutrino_"),
        ("neutrino_vscode@.service", "neutrino_"),
        ("neutrino_cloudcli@ann.service", "neutrino_"),
        ("neutrino_code_server@ann.service", "neutrino_"),
        ("neutrino_gitea.service", "neutrino_"),
        ("neutrino_vscode_ann", "neutrino_"),
        ("neutrino_cloudcli_install_ann", "neutrino_"),
        ("neutrino_cloudcli_port_ann", "neutrino_"),
        ("neutrino_smb_fence", "neutrino_"),
        ("NEUTRINO_VSCODE_ann", "neutrino_"),
        ("com.neutrino.vscode.ann", "com.neutrino."),
        ("com.neutrino.cloudcli.ann", "com.neutrino."),
        ("com.neutrino.code_server.ann", "com.neutrino."),
    ],
)
def test_a_name_a_module_gives_what_it_adds_is_taken_with_the_agent(name, prefix):
    assert base_module.is_added_name(name, prefix) is True


@pytest.mark.parametrize(
    "name, prefix",
    [
        ("neutrino_agent.service", "neutrino_"),
        ("neutrino_agent_update.service", "neutrino_"),
        ("neutrino_agent", "neutrino_"),
        ("neutrino_hub_web.service", "neutrino_"),
        ("neutrino_hub_dhcpcd@eth1.service", "neutrino_"),
        ("neutrino_hub_firewall_panel", "neutrino_"),
        ("neutrino_client.service", "neutrino_"),
        ("neutrino_client_netbird.service", "neutrino_"),
        ("neutrino_", "neutrino_"),
        ("rustdesk.service", "neutrino_"),
        ("smbd.service", "neutrino_"),
        ("com.neutrino.agent", "com.neutrino."),
        ("com.neutrino.hub", "com.neutrino."),
        ("com.neutrino.client.netbird", "com.neutrino."),
        ("com.carriez.RustDesk_service", "com.neutrino."),
    ],
)
def test_the_hub_the_client_and_the_agent_itself_are_left_alone(name, prefix):
    assert base_module.is_added_name(name, prefix) is False
