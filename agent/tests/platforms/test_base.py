"""The platform contract: advertised capabilities, honest refusals.

A platform says what it has; invoking what it lacks answers
``unsupported_platform``, never a guess. The capability table is asserted
complete, so a new contract method without a capability fails here.
"""

import pytest

import neutrino_agent.platforms.base as base_module
from neutrino_agent.constants import AGENT_STATE_PATH
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.linux import LinuxPlatform

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
    "power": ("power", ("reboot",), {}),
    "read_host_metrics": ("metrics", (), {}),
    "install_package": (
        "packages",
        ("/tmp/app.deb",),
        {"package_kind": "deb", "entry": {}},
    ),
    "uninstall_package": ("packages", ("apt-get remove -y app",), {}),
}

# Contract methods the base class answers for everyone.
BASE_IMPLEMENTED = {
    "agent_data_dir": "",
    "agent_service_start_hint": "agent_service",
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
    assert named == LinuxPlatform().capabilities


@pytest.mark.parametrize("method_name", sorted(CONTRACT_CALLS))
def test_the_base_contract_refuses_every_capability(method_name):
    _capability, args, kwargs = CONTRACT_CALLS[method_name]

    with pytest.raises(PlatformUnsupportedError) as caught:
        getattr(AgentPlatform(), method_name)(*args, **kwargs)

    assert caught.value.code == "unsupported_platform"


@pytest.mark.parametrize("method_name", sorted(CONTRACT_CALLS))
def test_linux_implements_every_capability_it_advertises(method_name):
    assert getattr(LinuxPlatform, method_name) is not getattr(
        AgentPlatform, method_name
    )


def test_the_base_platform_advertises_nothing():
    assert AgentPlatform().capabilities == frozenset()


def test_the_agent_data_root_defaults_to_the_posix_directory(monkeypatch):
    # The suite-wide fixture redirects the root off the machine; the real
    # value is put back here to pin it with the path that hangs off it.
    monkeypatch.setattr(base_module, "AGENT_DATA_DIR_POSIX", "/etc/neutrino/agent")

    assert AgentPlatform().agent_data_dir() == "/etc/neutrino/agent"
    assert AGENT_STATE_PATH == "/etc/neutrino/agent/state.json"


def test_the_base_start_hint_is_empty_rather_than_another_platforms():
    assert AgentPlatform().agent_service_start_hint() == ""


def test_base_account_home_refuses_rather_than_reading_the_environment(monkeypatch):
    """A root agent's $HOME names root's home, never the account's."""
    monkeypatch.setenv("HOME", "/home/lying")

    with pytest.raises(PlatformUnsupportedError) as caught:
        AgentPlatform().account_home("alice")

    assert caught.value.code == "unsupported_platform"
