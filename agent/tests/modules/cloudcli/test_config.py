"""The CloudCLI configuration: parsing, the checks, and what follows from it.

What these pin: a bad account, a repeated account or port, a port out of
range and a missing password or secret are refused naming the instance;
Windows also needs each account's login; the gateway's three variables
are present only when the hub serves a gateway; the login secret is a
function of the instance's secret alone; and a short account is padded to
the length CloudCLI asks for.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli.config import (
    CloudcliConfig,
    jwt_secret,
    username_of,
)

INSTANCE = {"account": "ann", "port": 3001, "web_password": "p", "token_secret": "s"}


def refusal(instances, os_name="linux"):
    with pytest.raises(ModuleApplyError) as caught:
        CloudcliConfig.from_dict({"instances": instances}).validate(os_name=os_name)
    return caught.value.code, caught.value.params


def test_a_whole_configuration_passes():
    CloudcliConfig.from_dict({"instances": [INSTANCE]}).validate()


@pytest.mark.parametrize(
    "instances, expected",
    [
        ([dict(INSTANCE, account="a b")], ("account_invalid", {"account": "a b"})),
        (
            [INSTANCE, dict(INSTANCE, account="ANN", port=3002)],
            ("account_duplicate", {"account": "ANN"}),
        ),
        ([dict(INSTANCE, port=80)], ("port_invalid", {"port": 80})),
        (
            [INSTANCE, dict(INSTANCE, account="bob")],
            ("port_duplicate", {"port": 3001}),
        ),
        ([dict(INSTANCE, web_password="")], ("token_missing", {"account": "ann"})),
        ([dict(INSTANCE, token_secret="")], ("token_missing", {"account": "ann"})),
    ],
)
def test_a_broken_instance_is_refused_by_name(instances, expected):
    assert refusal(instances) == expected


def test_windows_needs_each_accounts_login():
    assert refusal([INSTANCE], os_name="windows") == (
        "credential_missing",
        {"account": "ann"},
    )
    CloudcliConfig.from_dict({"instances": [dict(INSTANCE, password="x")]}).validate(
        os_name="windows"
    )


def test_the_gateway_reaches_the_environment_only_when_there_is_one():
    config = CloudcliConfig.from_dict(
        {"gateway_url": "http://10.0.0.1:8317/", "gateway_key": "k"}
    )

    assert config.environment() == {
        "ANTHROPIC_BASE_URL": "http://10.0.0.1:8317",
        "ANTHROPIC_AUTH_TOKEN": "k",
        "OPENAI_BASE_URL": "http://10.0.0.1:8317/v1",
    }
    assert CloudcliConfig.from_dict({}).environment() == {}


def test_the_login_secret_follows_the_instance_secret():
    assert jwt_secret("s") == jwt_secret("s")
    assert jwt_secret("s") != jwt_secret("t")
    assert len(jwt_secret("s")) == 64


def test_a_short_account_is_padded_to_cloudclis_minimum():
    assert username_of("ann") == "ann"
    assert username_of("al") == "al_"


def test_the_npm_registry_is_read_from_the_state():
    from neutrino_agent.modules.cloudcli.config import CloudcliConfig

    config = CloudcliConfig.from_dict(
        {"npm_registry": "https://registry.npmmirror.com"}
    )

    assert config.npm_registry == "https://registry.npmmirror.com"
    assert CloudcliConfig.from_dict({}).npm_registry == ""
