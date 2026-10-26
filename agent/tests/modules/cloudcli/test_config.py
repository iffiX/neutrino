"""The CloudCLI configuration: parsing, the checks, and what follows from it.

What these pin: an instance names no port, which the agent takes; a bad
account, a repeated account and a missing password or secret are refused
naming the instance;
Windows also needs each account's login; a gateway an older state still
names is not read; the login secret is a
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

INSTANCE = {"account": "ann", "web_password": "p", "token_secret": "s"}


def refusal(instances, os_name="linux"):
    with pytest.raises(ModuleApplyError) as caught:
        CloudcliConfig.from_dict({"instances": instances}).validate(os_name=os_name)
    return caught.value.code, caught.value.params


def test_a_whole_configuration_passes_and_names_no_port():
    config = CloudcliConfig.from_dict(
        {
            "instances": [
                dict(INSTANCE, local_name="cloudcli-ann.m.localhost", cookie_name="c")
            ]
        }
    )

    config.validate()

    (instance,) = config.instances
    assert (instance.port, instance.local_name, instance.cookie_name) == (
        0,
        "cloudcli-ann.m.localhost",
        "c",
    )


@pytest.mark.parametrize(
    "instances, expected",
    [
        ([dict(INSTANCE, account="a b")], ("account_invalid", {"account": "a b"})),
        (
            [INSTANCE, dict(INSTANCE, account="ANN")],
            ("account_duplicate", {"account": "ANN"}),
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


def test_a_gateway_an_older_state_names_is_not_read():
    config = CloudcliConfig.from_dict(
        {"gateway_url": "http://10.0.0.1:8317/", "gateway_key": "k"}
    )

    assert not hasattr(config, "gateway_url")
    assert not hasattr(config, "gateway_key")
    assert not hasattr(config, "environment")


def test_the_login_secret_follows_the_instance_secret():
    assert jwt_secret("s") == jwt_secret("s")
    assert jwt_secret("s") != jwt_secret("t")
    assert len(jwt_secret("s")) == 64


def test_a_short_account_is_padded_to_cloudclis_minimum():
    assert username_of("ann") == "ann"
    assert username_of("al") == "al_"
