"""The VS Code configuration and the checks that keep each server startable."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.vscode.config import VscodeConfig


def config_with(*instances, address="192.168.1.5") -> VscodeConfig:
    return VscodeConfig.from_dict({"address": address, "instances": list(instances)})


ANN = {"account": "ann", "token": "t-ann"}


def test_a_sound_configuration_passes_and_names_no_port():
    config = config_with(ANN, {"account": "bob", "token": "t-bob"})

    config.validate()

    assert config.host == "192.168.1.5"
    assert [instance.port for instance in config.instances] == [0, 0]


def test_no_address_listens_on_loopback_alone():
    config = config_with(ANN, address="")

    assert config.host == "127.0.0.1"


@pytest.mark.parametrize(
    "instances, code, params",
    [
        ([dict(ANN, account="a b")], "account_invalid", {"account": "a b"}),
        ([ANN, dict(ANN, account="ANN")], "account_duplicate", None),
        ([dict(ANN, token="")], "token_missing", {"account": "ann"}),
    ],
)
def test_a_server_that_could_not_start_is_refused_typed(instances, code, params):
    with pytest.raises(ModuleApplyError) as refused:
        config_with(*instances).validate()

    assert refused.value.code == code
    if params is not None:
        assert refused.value.params == params


def test_windows_needs_each_accounts_login():
    config_with(dict(ANN, password="pw")).validate(os_name="windows")

    with pytest.raises(ModuleApplyError) as refused:
        config_with(ANN).validate(os_name="windows")

    assert refused.value.code == "credential_missing"
    assert refused.value.params == {"account": "ann"}
