"""The VS Code configuration and the checks that keep each server startable."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.vscode.config import VscodeConfig


def config_with(*instances, address="192.168.1.5") -> VscodeConfig:
    return VscodeConfig.from_dict({"address": address, "instances": list(instances)})


ANN = {"account": "ann", "port": 8000, "token": "t-ann"}


def test_a_sound_configuration_passes_and_names_its_url():
    config = config_with(ANN, {"account": "bob", "port": 8001, "token": "t-bob"})

    config.validate()

    assert config.url_of(config.instances[0]) == "http://192.168.1.5:8000/"


def test_no_address_listens_on_every_address_and_names_the_loopback():
    config = config_with(ANN, address="")

    assert config.host == "0.0.0.0"
    assert config.url_of(config.instances[0]) == "http://127.0.0.1:8000/"


@pytest.mark.parametrize(
    "instances, code, params",
    [
        ([dict(ANN, account="a b")], "account_invalid", {"account": "a b"}),
        ([ANN, dict(ANN, account="ANN", port=8001)], "account_duplicate", None),
        ([dict(ANN, port=80)], "port_invalid", {"port": 80}),
        ([dict(ANN, port="x")], "port_invalid", {"port": 0}),
        ([ANN, dict(ANN, account="bob")], "port_duplicate", {"port": 8000}),
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
